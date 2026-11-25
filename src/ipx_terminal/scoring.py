"""Time-decayed Cultural Velocity Score (CVS) and Cross-Platform Contagion Index."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Tuple

PLATFORM_GROUPS = {
    "short_form": {"tiktok", "instagram reels", "instagram", "youtube shorts", "facebook reels", "snapchat"},
    "microblog": {"x", "twitter", "threads", "bluesky"},
    "community": {"reddit", "discord", "twitch", "4chan"},
    "long_form": {"youtube", "netflix", "hulu", "max", "prime video", "apple tv+"},
    "audio": {"spotify", "apple music", "shazam", "soundcloud"},
    "search_news": {"google trends", "gdelt", "news", "wikipedia", "polymarket", "kalshi"},
}


def parse_iso_utc(timestamp: str) -> datetime:
    """Parse an ISO-8601 UTC timestamp into a timezone-aware datetime."""
    cleaned = timestamp.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _classify_platform_buckets(platforms: List[str]) -> int:
    buckets = set()
    for raw in platforms:
        norm = raw.strip().lower()
        matched = False
        for bucket, members in PLATFORM_GROUPS.items():
            if norm in members or any(m in norm for m in members):
                buckets.add(bucket)
                matched = True
        if not matched and norm:
            buckets.add(f"other:{norm}")
    return len(buckets)


def compute_velocity_and_contagion(
    platforms: List[str],
    metrics: Dict[str, Any],
    captured_at: str,
    reference_time: Optional[datetime] = None,
    half_life_hours: float = 48.0,
) -> Tuple[float, float, str]:
    """Compute (cvs_score, contagion_index, contagion_stage) from a t_0 signal snapshot.

    Returns:
      - cvs_score: 0.0..100.0 (time-decayed Cultural Velocity Score)
      - contagion_index: 0.0..100.0 (Cross-Platform Contagion Index)
      - contagion_stage: 'echo_chamber' | 'emerging_contagion' | 'mainstream_breakout'
    """
    views = _safe_float(metrics.get("views") or metrics.get("median_views") or metrics.get("total_views"))
    likes = _safe_float(metrics.get("likes"))
    shares = _safe_float(metrics.get("shares") or metrics.get("reposts"))
    comments = _safe_float(metrics.get("comments") or metrics.get("replies"))
    followers = _safe_float(
        metrics.get("creator_subscribers")
        or metrics.get("creator_followers")
        or metrics.get("median_creator_followers")
    )
    breakout_ratio = _safe_float(metrics.get("breakout_ratio_views_to_followers"))
    if breakout_ratio <= 0 and views > 0 and followers > 0:
        breakout_ratio = views / followers

    share_to_like = _safe_float(metrics.get("share_to_like_ratio"))
    if share_to_like <= 0 and shares > 0 and likes > 0:
        share_to_like = shares / likes

    save_rate_pct = _safe_float(metrics.get("save_rate_pct"))
    unique_creators = _safe_float(
        metrics.get("unique_creators_using_sound")
        or metrics.get("unique_creators")
        or metrics.get("matching_clips_24h")
    )
    gdelt_articles = _safe_float(metrics.get("gdelt_articles") or metrics.get("article_count"))
    google_trends = _safe_float(metrics.get("google_trends_index"))
    overlap_pct = _safe_float(metrics.get("x_audience_overlap_pct"), default=-1.0)
    paid_boost = bool(metrics.get("paid_boost_detected", False))

    # 1. Breakout / engagement component (0..45)
    breakout_pts = 0.0
    if breakout_ratio > 0:
        breakout_pts += min(25.0, math.log1p(breakout_ratio) * 9.5)
    elif views > 0:
        breakout_pts += min(18.0, math.log10(max(10.0, views)) * 3.0)
    elif likes > 0:
        breakout_pts += min(16.0, math.log10(max(10.0, likes)) * 3.0)

    if share_to_like > 0:
        breakout_pts += min(15.0, share_to_like * 35.0)
    if save_rate_pct > 0:
        breakout_pts += min(10.0, save_rate_pct * 2.0)
    if comments > 0 and likes > 0:
        breakout_pts += min(5.0, (comments / likes) * 40.0)
    breakout_pts = min(45.0, breakout_pts)

    # 2. Creator / remix breadth component (0..25)
    breadth_pts = 0.0
    if unique_creators > 0:
        breadth_pts += min(18.0, math.log1p(unique_creators) * 4.5)
    if gdelt_articles > 0:
        breadth_pts += min(12.0, math.log1p(gdelt_articles) * 4.0)
    if google_trends > 0:
        breadth_pts += min(10.0, google_trends * 0.12)
    breadth_pts = min(25.0, breadth_pts)

    # 3. Cross-platform contagion component (0..30 for CVS, 0..100 for Contagion Index)
    distinct_platforms = len({p.strip().lower() for p in platforms if p.strip()})
    bucket_count = _classify_platform_buckets(platforms)

    contagion = 12.0 * min(distinct_platforms, 5) + 14.0 * min(bucket_count, 4)
    if gdelt_articles >= 5:
        contagion += min(18.0, math.log1p(gdelt_articles) * 5.0)
    if google_trends >= 20:
        contagion += min(16.0, google_trends * 0.2)
    if share_to_like >= 0.20:
        contagion += 10.0
    if overlap_pct >= 75.0:
        contagion -= 25.0
    elif 0 <= overlap_pct <= 35.0:
        contagion += 10.0
    if distinct_platforms <= 1 and gdelt_articles == 0 and google_trends < 15:
        contagion = min(contagion, 32.0)
    contagion_index = round(max(0.0, min(100.0, contagion)), 1)

    if contagion_index >= 68.0:
        contagion_stage = "mainstream_breakout"
    elif contagion_index >= 38.0:
        contagion_stage = "emerging_contagion"
    else:
        contagion_stage = "echo_chamber"

    raw_cvs = breakout_pts + breadth_pts + (contagion_index * 0.30)
    if paid_boost:
        raw_cvs *= 0.65

    # Exponential time decay relative to reference_time (clamped so slightly future timestamps don't amplify)
    ref = reference_time or datetime.now(timezone.utc)
    try:
        cap_dt = parse_iso_utc(captured_at)
        age_hours = max(0.0, (ref - cap_dt).total_seconds() / 3600.0)
    except ValueError:
        age_hours = 0.0

    decay = math.exp(-math.log(2.0) * (age_hours / max(1.0, half_life_hours)))
    # Keep a 0.35 floor so historical seeded signals remain readable in the tape
    effective_decay = 0.35 + 0.65 * decay
    cvs_score = round(max(0.0, min(100.0, raw_cvs * effective_decay)), 1)

    return cvs_score, contagion_index, contagion_stage
