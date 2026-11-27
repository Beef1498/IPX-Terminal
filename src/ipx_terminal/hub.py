"""Command Center Hub services: Write-token auth, GitHub Live Updates, IPX-Eval sync, and Orchestration map."""

from __future__ import annotations

import hmac
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.error
import urllib.parse
import urllib.request

from ipx_terminal.config import (
    APP_VERSION,
    DEFAULT_EVAL_REPO,
    DEFAULT_GITHUB_REPOS,
    DEFAULT_ORCHESTRATION_PATH,
    PROJECT_ROOT,
)
from ipx_terminal.db import TerminalDB
from ipx_terminal.scoring import utc_now_iso

_GITHUB_CACHE: Dict[str, Any] = {"fetched_at": 0.0, "payload": None}
_GITHUB_CACHE_TTL_SEC = 300.0


# ------------------------------------------------------------------
# Write-Passcode / Token Auth (2A: Public Read-Only + Passcode Writes)
# ------------------------------------------------------------------
def get_configured_write_token() -> str:
    direct = (
        os.environ.get("IPX_WRITE_TOKEN", "").strip()
        or os.environ.get("IPX_ADMIN_PASSCODE", "").strip()
    )
    if direct:
        return direct
    for k, v in os.environ.items():
        if k.upper() in ("IPX_WRITE_TOKEN", "IPX_ADMIN_PASSCODE") and v.strip():
            return v.strip()
    return ""


def extract_request_token(headers: Any) -> str:
    if not headers:
        return ""
    direct = str(headers.get("X-IPX-Token") or "").strip()
    if direct:
        return direct
    auth = str(headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def is_write_authorized(headers: Any, candidate_token: Optional[str] = None) -> bool:
    expected = get_configured_write_token()
    if not expected:
        return True
    provided = candidate_token.strip() if candidate_token is not None else extract_request_token(headers)
    if not provided:
        return False
    return hmac.compare_digest(provided, expected)


# ------------------------------------------------------------------
# GitHub REST Helpers
# ------------------------------------------------------------------
def _normalize_repo_slug(raw: str) -> str:
    cleaned = raw.strip().rstrip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    if "github.com/" in cleaned:
        cleaned = cleaned.split("github.com/", 1)[1]
    parts = [p for p in cleaned.split("/") if p]
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return cleaned


def get_tracked_repos() -> List[str]:
    env_val = os.environ.get("IPX_GITHUB_REPOS", "").strip()
    if env_val:
        repos = [_normalize_repo_slug(r) for r in env_val.split(",") if r.strip()]
        return [r for r in repos if "/" in r]
    return list(DEFAULT_GITHUB_REPOS)


def get_eval_repo() -> str:
    env_val = os.environ.get("IPX_EVAL_REPO", "").strip()
    return _normalize_repo_slug(env_val) if env_val else DEFAULT_EVAL_REPO


def _github_get_json(url: str, timeout: int = 12) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"IPX-Command-Center/{APP_VERSION}",
    }
    gh_token = os.environ.get("GITHUB_TOKEN", "").strip()
    if gh_token:
        headers["Authorization"] = f"Bearer {gh_token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _local_git_commits(repo_slug: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Fallback to local git log for IPX-Terminal when offline or rate-limited."""
    if not (PROJECT_ROOT / ".git").exists():
        return []
    try:
        out = subprocess.check_output(
            [
                "git",
                "-C",
                str(PROJECT_ROOT),
                "log",
                f"-n{limit}",
                "--pretty=format:%H%x1f%h%x1f%an%x1f%aI%x1f%s",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except Exception:
        return []
    commits: List[Dict[str, Any]] = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) < 5:
            continue
        sha, short_sha, author, date_iso, message = parts[:5]
        commits.append(
            {
                "repo": repo_slug,
                "sha": sha,
                "short_sha": short_sha,
                "author": author,
                "date": date_iso,
                "message": message,
                "url": f"https://github.com/{repo_slug}/commit/{sha}",
                "source": "local_git",
            }
        )
    return commits


def fetch_github_updates(force_refresh: bool = False) -> Dict[str, Any]:
    """Fetch live repo metadata, releases/tags, and commit stream across tracked IPX GitHub repos."""
    now = time.time()
    if (
        not force_refresh
        and _GITHUB_CACHE["payload"] is not None
        and (now - float(_GITHUB_CACHE["fetched_at"])) < _GITHUB_CACHE_TTL_SEC
    ):
        cached = dict(_GITHUB_CACHE["payload"])
        cached["cached"] = True
        return cached

    repos_out: List[Dict[str, Any]] = []
    releases_out: List[Dict[str, Any]] = []
    commits_out: List[Dict[str, Any]] = []
    errors: List[str] = []

    for slug in get_tracked_repos():
        html_url = f"https://github.com/{slug}"
        repo_card: Dict[str, Any] = {
            "slug": slug,
            "name": slug.split("/")[-1],
            "html_url": html_url,
            "commits_url": f"{html_url}/commits",
            "releases_url": f"{html_url}/releases",
            "issues_url": f"{html_url}/issues",
            "description": "",
            "default_branch": "main",
            "pushed_at": None,
            "stars": None,
            "open_issues": None,
            "latest_version": None,
            "status": "live",
        }
        try:
            meta = _github_get_json(f"https://api.github.com/repos/{slug}")
            repo_card.update(
                {
                    "description": meta.get("description") or "",
                    "default_branch": meta.get("default_branch") or "main",
                    "pushed_at": meta.get("pushed_at"),
                    "stars": meta.get("stargazers_count"),
                    "open_issues": meta.get("open_issues_count"),
                    "private": bool(meta.get("private", False)),
                }
            )
            raw_commits = _github_get_json(f"https://api.github.com/repos/{slug}/commits?per_page=10")
            if isinstance(raw_commits, list):
                for c in raw_commits:
                    sha = str(c.get("sha") or "")
                    commit_obj = c.get("commit") or {}
                    author_obj = commit_obj.get("author") or {}
                    msg = str(commit_obj.get("message") or "").splitlines()[0]
                    commits_out.append(
                        {
                            "repo": slug,
                            "sha": sha,
                            "short_sha": sha[:7],
                            "author": author_obj.get("name") or (c.get("author") or {}).get("login") or "unknown",
                            "date": author_obj.get("date") or "",
                            "message": msg,
                            "url": c.get("html_url") or f"{html_url}/commit/{sha}",
                            "source": "github_api",
                        }
                    )
            raw_releases = _github_get_json(f"https://api.github.com/repos/{slug}/releases?per_page=5")
            if isinstance(raw_releases, list) and raw_releases:
                repo_card["latest_version"] = raw_releases[0].get("tag_name") or raw_releases[0].get("name")
                for rel in raw_releases:
                    releases_out.append(
                        {
                            "repo": slug,
                            "tag": rel.get("tag_name") or "",
                            "name": rel.get("name") or rel.get("tag_name") or "Release",
                            "published_at": rel.get("published_at") or rel.get("created_at") or "",
                            "body": (rel.get("body") or "").strip()[:500],
                            "url": rel.get("html_url") or f"{html_url}/releases",
                            "prerelease": bool(rel.get("prerelease", False)),
                        }
                    )
            else:
                raw_tags = _github_get_json(f"https://api.github.com/repos/{slug}/tags?per_page=4")
                if isinstance(raw_tags, list) and raw_tags:
                    repo_card["latest_version"] = raw_tags[0].get("name")
        except Exception as exc:
            repo_card["status"] = "degraded"
            errors.append(f"{slug}: {exc}")
            if slug.lower().endswith("/ipx-terminal"):
                fallback = _local_git_commits(slug, limit=10)
                if fallback:
                    commits_out.extend(fallback)
                    repo_card["pushed_at"] = fallback[0]["date"]
                    repo_card["status"] = "local_fallback"

        if not repo_card["latest_version"] and slug.lower().endswith("/ipx-terminal"):
            repo_card["latest_version"] = f"v{APP_VERSION}"
        repos_out.append(repo_card)

    commits_out.sort(key=lambda c: str(c.get("date") or ""), reverse=True)
    releases_out.sort(key=lambda r: str(r.get("published_at") or ""), reverse=True)

    payload = {
        "app_version": APP_VERSION,
        "fetched_at": utc_now_iso(),
        "cached": False,
        "github_token_configured": bool(os.environ.get("GITHUB_TOKEN", "").strip()),
        "repos": repos_out,
        "releases": releases_out,
        "commits": commits_out[:25],
        "errors": errors,
    }
    _GITHUB_CACHE["fetched_at"] = now
    _GITHUB_CACHE["payload"] = payload
    return payload


# ------------------------------------------------------------------
# IPX-Eval Auto-Sync (GitHub Repo + Optional Local Directory)
# ------------------------------------------------------------------
def _opt_float(val: Any) -> Optional[float]:
    if val in (None, ""):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _opt_int(val: Any) -> Optional[int]:
    if val in (None, ""):
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _normalize_eval_payload(item: Dict[str, Any], default_run_id: str, source: str) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    model_name = (
        item.get("model_name")
        or item.get("model")
        or item.get("model_id")
        or item.get("checkpoint")
    )
    if not model_name:
        return None
    run_id = str(item.get("run_id") or item.get("id") or default_run_id).strip()

    # Support nested summary dicts if present
    summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
    overall = _opt_float(
        item.get("overall_score")
        if item.get("overall_score") is not None
        else summary.get("overall_score", item.get("score"))
    )
    acc = _opt_float(
        item.get("accuracy_pct")
        if item.get("accuracy_pct") is not None
        else summary.get("accuracy_pct", item.get("accuracy"))
    )
    if acc is not None and 0.0 < acc <= 1.0:
        acc = round(acc * 100.0, 2)
    if overall is not None and 0.0 < overall <= 1.0:
        overall = round(overall * 100.0, 2)

    recall = _opt_float(
        item.get("concept_recall_pct")
        if item.get("concept_recall_pct") is not None
        else summary.get("concept_recall_pct", item.get("concept_recall"))
    )
    if recall is not None and 0.0 < recall <= 1.0:
        recall = round(recall * 100.0, 2)

    cat_scores = item.get("category_scores") or item.get("by_category") or summary.get("by_category") or {}
    if not isinstance(cat_scores, dict):
        cat_scores = {}

    return {
        "run_id": run_id,
        "model_name": str(model_name),
        "model_family": str(item.get("model_family") or ""),
        "dataset_version": str(item.get("dataset_version") or item.get("dataset") or "v0.3"),
        "hardware": str(item.get("hardware") or "DGX Spark"),
        "status": str(item.get("status") or "completed"),
        "overall_score": overall,
        "accuracy_pct": acc,
        "concept_recall_pct": recall,
        "total_cases": _opt_int(item.get("total_cases") or summary.get("total_cases") or 0) or 0,
        "passed_cases": _opt_int(item.get("passed_cases") or summary.get("passed_cases") or 0) or 0,
        "train_loss": _opt_float(item.get("train_loss")),
        "eval_loss": _opt_float(item.get("eval_loss")),
        "step": _opt_int(item.get("step")),
        "epoch": _opt_float(item.get("epoch")),
        "category_scores": cat_scores,
        "metrics": item.get("metrics") if isinstance(item.get("metrics"), dict) else {},
        "commit_sha": str(item.get("commit_sha") or item.get("git_sha") or ""),
        "source": source,
        "notes": str(item.get("notes") or ""),
        "started_at": item.get("started_at") or item.get("timestamp"),
        "created_at": item.get("created_at") or item.get("timestamp"),
    }


def _ingest_eval_json_doc(db: TerminalDB, doc: Any, stem: str, source: str) -> int:
    count = 0
    items: List[Dict[str, Any]] = []
    if isinstance(doc, list):
        items = [x for x in doc if isinstance(x, dict)]
    elif isinstance(doc, dict):
        if isinstance(doc.get("runs"), list):
            items = [x for x in doc["runs"] if isinstance(x, dict)]
        elif isinstance(doc.get("leaderboard"), list):
            items = [x for x in doc["leaderboard"] if isinstance(x, dict)]
        else:
            items = [doc]
    for idx, item in enumerate(items):
        norm = _normalize_eval_payload(item, default_run_id=f"{stem}-{idx + 1}", source=source)
        if norm:
            db.upsert_eval_run(**norm)
            count += 1
    return count


def sync_github_eval_runs(db: TerminalDB, repo: Optional[str] = None) -> Dict[str, Any]:
    """Pull committed eval/training JSON results from IPX-eval GitHub repo (and optional local folder)."""
    slug = _normalize_repo_slug(repo) if repo else get_eval_repo()
    synced = 0
    files_checked: List[str] = []
    errors: List[str] = []

    candidate_paths = ["results", "runs", "reports", "leaderboards", "leaderboard.json", "results.json"]
    for rel in candidate_paths:
        url = f"https://api.github.com/repos/{slug}/contents/{rel}"
        try:
            listing = _github_get_json(url, timeout=10)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue
            errors.append(f"{slug}/{rel}: HTTP {exc.code}")
            continue
        except Exception as exc:
            errors.append(f"{slug}/{rel}: {exc}")
            continue

        entries = listing if isinstance(listing, list) else [listing]
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("type") != "file":
                continue
            name = str(entry.get("name") or "")
            if not name.endswith(".json"):
                continue
            dl_url = entry.get("download_url")
            if not dl_url:
                continue
            files_checked.append(f"{slug}/{entry.get('path', name)}")
            try:
                doc = _github_get_json(str(dl_url), timeout=10)
                synced += _ingest_eval_json_doc(db, doc, stem=Path(name).stem, source="github_sync")
            except Exception as exc:
                errors.append(f"{name}: {exc}")

    # Optional local fallback directory (e.g., when running on Mac/DGX alongside IPX-Eval)
    local_dir_env = os.environ.get("IPX_EVAL_LOCAL_DIR", "").strip()
    if local_dir_env:
        local_root = Path(local_dir_env)
        for sub in ("results", "runs", "reports"):
            target_dir = local_root / sub
            if target_dir.is_dir():
                for fp in sorted(target_dir.glob("*.json")):
                    files_checked.append(str(fp))
                    try:
                        doc = json.loads(fp.read_text(encoding="utf-8"))
                        synced += _ingest_eval_json_doc(db, doc, stem=fp.stem, source="local_eval_sync")
                    except Exception as exc:
                        errors.append(f"{fp.name}: {exc}")

    return {
        "repo": slug,
        "synced_count": synced,
        "files_checked": files_checked,
        "errors": errors,
        "synced_at": utc_now_iso(),
    }


# ------------------------------------------------------------------
# Orchestration Topology (Software + Hardware + Live Telemetry)
# ------------------------------------------------------------------
def get_orchestration_map(db: TerminalDB) -> Dict[str, Any]:
    if DEFAULT_ORCHESTRATION_PATH.is_file():
        topo = json.loads(DEFAULT_ORCHESTRATION_PATH.read_text(encoding="utf-8"))
    else:
        topo = {"version": APP_VERSION, "hardware": [], "software": [], "flows": []}

    stats = db.get_dashboard_stats()
    eval_summary = db.get_eval_summary()
    db_size_kb = round(db.db_path.stat().st_size / 1024.0, 1) if db.db_path.is_file() else 0.0

    topo["runtime"] = {
        "app_version": APP_VERSION,
        "checked_at": utc_now_iso(),
        "db_path": str(db.db_path),
        "db_size_kb": db_size_kb,
        "write_protected": bool(get_configured_write_token()),
        "tracked_repos": get_tracked_repos(),
        "eval_repo": get_eval_repo(),
        "stats": stats,
        "eval_runs_total": eval_summary["total_runs"],
        "eval_models_count": eval_summary["models_count"],
        "integrations": {
            "scrapecreators": bool(os.environ.get("SCRAPECREATORS_API_KEY", "").strip()),
            "github_token": bool(os.environ.get("GITHUB_TOKEN", "").strip()),
            "ai_scorer": bool(os.environ.get("OPENAI_API_KEY", "").strip() or os.environ.get("IPX_AI_API_KEY", "").strip()),
            "youtube_api": bool(os.environ.get("YOUTUBE_API_KEY", "").strip()),
            "write_passcode": bool(get_configured_write_token()),
        },
    }
    return topo
