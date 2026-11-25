"""Signal ingestion connectors (GDELT DOC 2.0, YouTube Data API v3, manual capture, demo seed)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
import os
import re
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.parse
import urllib.request

from ipx_terminal.db import TerminalDB, normalize_ticker


class _MetaHTMLParser(HTMLParser):
    """Lightweight stdlib HTML title + OpenGraph/meta tag extractor."""

    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.title_parts: List[str] = []
        self.meta: Dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: List[Any]) -> None:
        tag_l = tag.lower()
        if tag_l == "title":
            self.in_title = True
            return
        if tag_l == "meta":
            attr_map = {str(k).lower(): str(v) for k, v in attrs if v is not None}
            key = (attr_map.get("property") or attr_map.get("name") or "").strip().lower()
            val = attr_map.get("content", "").strip()
            if key and val and key not in self.meta:
                self.meta[key] = val

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)

    @property
    def page_title(self) -> str:
        return " ".join("".join(self.title_parts).split()).strip()


def _detect_platform_from_url(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower()
    path = urllib.parse.urlparse(url).path.lower()
    if "youtube.com" in host or "youtu.be" in host:
        return "YouTube Shorts" if "/shorts/" in path else "YouTube"
    if "tiktok.com" in host:
        return "TikTok"
    if "instagram.com" in host:
        return "Instagram Reels" if "/reel" in path else "Instagram"
    if "x.com" in host or "twitter.com" in host:
        return "X"
    if "facebook.com" in host or "fb.watch" in host:
        return "Facebook Reels" if "/reel" in path else "Facebook"
    if "reddit.com" in host:
        return "Reddit"
    if "spotify.com" in host:
        return "Spotify"
    return host.replace("www.", "") or "Web"


def _http_get_text(url: str, timeout: int = 12) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(250_000).decode("utf-8", errors="replace")


def extract_url_metadata(url: str) -> Dict[str, Any]:
    """Extract structured t_0 metadata from a social/web URL using oEmbed + HTML meta tags."""
    clean_url = url.strip()
    if not clean_url.startswith(("http://", "https://")):
        raise ValueError("URL must start with http:// or https://")

    platform = _detect_platform_from_url(clean_url)
    title = ""
    author = ""
    description = ""
    metrics: Dict[str, Any] = {"url": clean_url}
    samples: List[str] = []

    # 1. Try public oEmbed first for YouTube, TikTok, and X (fast, reliable, zero API key)
    oembed_url = None
    if platform in ("YouTube", "YouTube Shorts"):
        oembed_url = f"https://www.youtube.com/oembed?url={urllib.parse.quote(clean_url, safe='')}&format=json"
    elif platform == "TikTok":
        oembed_url = f"https://www.tiktok.com/oembed?url={urllib.parse.quote(clean_url, safe='')}"
    elif platform == "X":
        oembed_url = f"https://publish.twitter.com/oembed?url={urllib.parse.quote(clean_url, safe='')}"

    if oembed_url:
        try:
            oe = _http_get_json(oembed_url, timeout=10)
            title = str(oe.get("title") or "").strip()
            author = str(oe.get("author_name") or "").strip()
            if oe.get("html") and platform == "X":
                text_only = re.sub(r"<[^>]+>", " ", str(oe["html"]))
                text_only = " ".join(text_only.split()).strip()
                if text_only:
                    description = text_only
                    samples.append(text_only[:220])
        except Exception:
            pass

    # 2. Fetch HTML meta tags / public view counts as enrichment or fallback
    try:
        html = _http_get_text(clean_url, timeout=12)
        parser = _MetaHTMLParser()
        parser.feed(html)
        if not title:
            title = parser.meta.get("og:title") or parser.meta.get("twitter:title") or parser.page_title
        if not description:
            description = (
                parser.meta.get("og:description")
                or parser.meta.get("description")
                or parser.meta.get("twitter:description")
                or ""
            )
        # Extract public YouTube viewCount if present in page JSON
        vc = re.search(r'"viewCount"\s*:\s*"?(\d+)"?', html)
        if vc:
            metrics["views"] = int(vc.group(1))
        ic = re.search(r'"interactionCount"\s*:\s*"?(\d+)"?', html)
        if ic and "views" not in metrics:
            metrics["views"] = int(ic.group(1))
    except Exception:
        pass

    if not title:
        title = f"{platform} signal — {clean_url[:60]}"
    if description and description not in samples:
        samples.append(description[:220])

    summary_parts = [f"Auto-captured {platform} signal"]
    if author:
        summary_parts.append(f"by {author}")
    summary_parts.append(f"titled '{title}'.")
    if description and description != title:
        summary_parts.append(description[:320])
    if "views" in metrics:
        summary_parts.append(f"Observed views at t_0: {metrics['views']:,}.")

    return {
        "platform": platform,
        "title": title[:160],
        "author": author,
        "summary": " ".join(summary_parts).strip(),
        "metrics": metrics,
        "samples": samples[:3],
    }


def ingest_url(
    db: TerminalDB,
    url: str,
    ticker: str,
    sector: str = "POP",
    entity_name: Optional[str] = None,
    owner_holder: str = "Independent / Unknown",
    extra_metrics: Optional[Dict[str, Any]] = None,
    notes: str = "",
) -> Dict[str, Any]:
    """Auto-extract metadata from a URL and store a scored t_0 signal snapshot."""
    meta = extract_url_metadata(url)
    metrics = dict(meta["metrics"])
    if extra_metrics:
        metrics.update(extra_metrics)
    summary = meta["summary"]
    if notes.strip():
        summary = f"{summary} Analyst note: {notes.strip()}"

    mentioned = [entity_name or normalize_ticker(ticker)]
    if meta["author"] and meta["author"] not in mentioned:
        mentioned.append(meta["author"])

    return db.insert_signal(
        ticker=ticker,
        title=meta["title"],
        summary=summary,
        platforms=[meta["platform"]],
        metrics=metrics,
        samples=meta["samples"],
        entities_mentioned=mentioned,
        source_type="url_ingest",
        url=url.strip(),
        sector=sector,
        entity_name=entity_name or meta["author"] or normalize_ticker(ticker),
        owner_holder=owner_holder,
    )


def sweep_watchlist(
    db: TerminalDB,
    tickers: Optional[List[str]] = None,
    timespan: str = "24h",
    max_records: int = 8,
) -> Dict[str, Any]:
    """Run GDELT sweeps across watchlist entities and report overdue 48-72h predictions."""
    entities = db.list_entities()
    if tickers:
        wanted = {normalize_ticker(t) for t in tickers}
        entities = [e for e in entities if e["ticker"] in wanted]

    ingested: List[Dict[str, Any]] = []
    errors: List[str] = []
    for ent in entities[:5]:
        query = f'"{ent["name"].split("—")[0].strip()}"'
        try:
            sig = ingest_gdelt(
                db=db,
                query=query,
                ticker=ent["ticker"],
                sector=ent["sector"],
                entity_name=ent["name"],
                owner_holder=ent["owner_holder"],
                max_records=max_records,
                timespan=timespan,
            )
            ingested.append({"ticker": ent["ticker"], "signal_id": sig["id"], "cvs": sig["cvs_score"]})
        except Exception as exc:
            errors.append(f"{ent['ticker']}: {exc}")

    overdue = [p for p in db.list_predictions(status="pending", limit=200) if p["overdue"]]
    return {
        "swept_count": len(ingested),
        "ingested": ingested,
        "errors": errors,
        "overdue_predictions": [
            {"id": p["id"], "case_code": p["case_code"], "ticker": p["ticker"], "due_at": p["due_at"]}
            for p in overdue
        ],
    }


def _http_get_json(url: str, timeout: int = 15) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "IPX-Terminal/0.1 (+https://ipx-terminal.local)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ingest_gdelt(
    db: TerminalDB,
    query: str,
    ticker: str,
    sector: str = "POP",
    entity_name: Optional[str] = None,
    owner_holder: str = "Independent / Unknown",
    max_records: int = 12,
    timespan: str = "24h",
) -> Dict[str, Any]:
    """Ingest live global news signals from GDELT DOC 2.0 API into a t_0 signal snapshot."""
    params = urllib.parse.urlencode(
        {
            "query": query,
            "mode": "ArtList",
            "maxrecords": str(max_records),
            "timespan": timespan,
            "format": "json",
            "sort": "DateDesc",
        }
    )
    url = f"https://api.gdeltproject.org/api/v2/doc/doc?{params}"
    payload = _http_get_json(url)
    articles = payload.get("articles") or []

    domains = sorted({a.get("domain", "") for a in articles if a.get("domain")})
    titles = [a.get("title", "").strip() for a in articles if a.get("title")]
    languages = sorted({a.get("language", "") for a in articles if a.get("language")})

    summary = (
        f"GDELT DOC 2.0 sweep for '{query}' over the last {timespan} returned "
        f"{len(articles)} articles across {len(domains)} distinct domains "
        f"({', '.join(domains[:5]) or 'none'})."
    )
    return db.insert_signal(
        ticker=ticker,
        title=f"GDELT News Pulse: {query} ({len(articles)} articles / {timespan})",
        summary=summary,
        platforms=["GDELT", "News"],
        metrics={
            "query": query,
            "timespan": timespan,
            "gdelt_articles": len(articles),
            "distinct_domains": len(domains),
            "languages": languages[:6],
        },
        samples=titles[:5],
        entities_mentioned=[entity_name or normalize_ticker(ticker), query],
        source_type="gdelt",
        url=articles[0].get("url", "") if articles else "",
        sector=sector,
        entity_name=entity_name or query,
        owner_holder=owner_holder,
    )


def ingest_youtube(
    db: TerminalDB,
    query: str,
    ticker: str,
    sector: str = "CREATORS",
    entity_name: Optional[str] = None,
    owner_holder: str = "Independent / Unknown",
    api_key: Optional[str] = None,
    max_results: int = 5,
) -> Dict[str, Any]:
    """Ingest live YouTube Data API v3 search + video stats into a t_0 signal snapshot."""
    key = api_key or os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        raise ValueError("YOUTUBE_API_KEY is required for YouTube Data API v3 ingestion")

    search_params = urllib.parse.urlencode(
        {
            "part": "snippet",
            "q": query,
            "type": "video",
            "order": "viewCount",
            "maxResults": str(max_results),
            "key": key,
        }
    )
    search_data = _http_get_json(f"https://www.googleapis.com/youtube/v3/search?{search_params}")
    items = search_data.get("items") or []
    video_ids = [item["id"]["videoId"] for item in items if item.get("id", {}).get("videoId")]
    if not video_ids:
        raise ValueError(f"No YouTube videos found for query '{query}'")

    stats_params = urllib.parse.urlencode(
        {
            "part": "snippet,statistics",
            "id": ",".join(video_ids),
            "key": key,
        }
    )
    stats_data = _http_get_json(f"https://www.googleapis.com/youtube/v3/videos?{stats_params}")
    videos = stats_data.get("items") or []

    total_views = 0
    total_likes = 0
    total_comments = 0
    channels = set()
    samples: List[str] = []
    for vid in videos:
        st = vid.get("statistics", {})
        sn = vid.get("snippet", {})
        total_views += int(st.get("viewCount", 0))
        total_likes += int(st.get("likeCount", 0))
        total_comments += int(st.get("commentCount", 0))
        if sn.get("channelTitle"):
            channels.add(sn["channelTitle"])
        if sn.get("title"):
            samples.append(f"{sn['title']} ({int(st.get('viewCount', 0)):,} views)")

    top_url = f"https://www.youtube.com/watch?v={video_ids[0]}"
    summary = (
        f"YouTube Data API v3 sweep for '{query}' captured {len(videos)} top videos across "
        f"{len(channels)} channels totaling {total_views:,} views, {total_likes:,} likes, "
        f"and {total_comments:,} comments."
    )
    return db.insert_signal(
        ticker=ticker,
        title=f"YouTube Velocity Pulse: {query} ({total_views:,} views)",
        summary=summary,
        platforms=["YouTube", "YouTube Shorts"],
        metrics={
            "query": query,
            "videos_sampled": len(videos),
            "unique_creators": len(channels),
            "views": total_views,
            "likes": total_likes,
            "comments": total_comments,
        },
        samples=samples[:5],
        entities_mentioned=[entity_name or normalize_ticker(ticker), *sorted(channels)[:4]],
        source_type="youtube",
        url=top_url,
        sector=sector,
        entity_name=entity_name or query,
        owner_holder=owner_holder,
    )


def seed_demo_workspace(db: TerminalDB, force: bool = False) -> Dict[str, int]:
    """Populate 100% real-world Content IP entities, signals, and predictions across all 7 sectors."""
    existing = db.list_entities()
    if existing and not force:
        return {"entities": 0, "signals": 0, "predictions": 0, "resolved": 0}

    entities_spec = [
        (
            "FAOUZ.UN",
            "Faouzia — 'UNETHICAL'",
            "MUSIC",
            "Faouzia / Warner Music Group (Recording & Publishing)",
            "song",
            ["UNETHICAL", "Faouzia", "TikTok Add to Music App"],
            "Real 2026 breakout single propelled from TikTok & Spotify viral momentum to Faouzia's first-ever Billboard Hot 100 entry and Billboard Global 200 placement.",
        ),
        (
            "SOMBR.BF",
            "Sombr — 'Back to Friends'",
            "MUSIC",
            "Sombr / Warner Records",
            "song",
            ["Back to Friends", "Sombr", "Billboard Global 200"],
            "Real TikTok sleeper-turned-megahit logging sustained multi-week Billboard Global 200 and Spotify streaming performance.",
        ),
        (
            "SONY.RMG",
            "Sony Music Publishing × Recognition Music Group (Hipgnosis)",
            "DEALS",
            "Sony Music Publishing & GIC (Singapore Sovereign Wealth Fund JV)",
            "franchise",
            ["Recognition Music Group", "Hipgnosis Songs Fund", "Blackstone", "45,000-song catalog"],
            "Real $3.5B–$4.0B mega-acquisition closing Sony Music Publishing + GIC's purchase of the 45,000+ song Recognition Music Group (formerly Hipgnosis) catalog.",
        ),
        (
            "NVDA.IP",
            "NVIDIA / Jensen Huang Persona",
            "POP",
            "NVIDIA Corp. (Public Equity / Executive Likeness)",
            "brand",
            ["Jensen Huang", "Leather Jacket CEO", "NVIDIA AI"],
            "Executive persona and hardware IP generating real viral AI lip-sync parodies on X and unauthorized likeness posts on Instagram.",
        ),
        (
            "KATT.FMT",
            "Katt Williams Cutout CapCut Format",
            "CREATORS",
            "Katt Williams / CapCut Template Ecosystem",
            "format",
            ["Katt Williams CapCut", "Husband's Work Ethic", "@jcrow73"],
            "Real TikTok CapCut green-screen cutout template by @jcrow73 showing a ~45% share-to-like ratio (35.3K shares on 78.6K likes).",
        ),
        (
            "JUSTUS.R",
            "Justus_Reid — 'Rebuilding my House' Series",
            "CREATORS",
            "Justus_Reid (@justus_reid, 739K YouTube Subscribers)",
            "creator",
            ["Justus_Reid", "5000€ House", "Rebuilding my House Part 4"],
            "Serialized home-renovation YouTube Shorts creator; high raw view counts driven by loyal existing subscribers rather than a remixable trend.",
        ),
        (
            "MRSPRAY",
            "Mr. Spray — Cancun Street Art Reels",
            "CREATORS",
            "Mr. Spray (Independent Creator)",
            "creator",
            ["Mr. Spray", "Mexican Street Magician Transforms My Suitcase"],
            "Single-platform Facebook Reels algorithmic spectacle hitting 1.2M likes with no cross-platform meme or news spillover.",
        ),
        (
            "GTA6",
            "Grand Theft Auto VI",
            "GAMING",
            "Take-Two Interactive / Rockstar Games",
            "franchise",
            ["GTA VI", "Rockstar", "@EsemicolonR"],
            "Flagship gaming IP generating 1M-view X commentary clips inside tight niche gaming subcultures.",
        ),
        (
            "LEAF.NHL",
            "Toronto Maple Leafs / Kalshi Shorts",
            "SPORTS",
            "MLSE / NHL (Sponsor: Kalshi)",
            "sports",
            ["Maple Leafs", "@thefknshow", "Kalshi Sports"],
            "Real NHL commentary YouTube Short hitting 4.8x subscriber baseline (272K views on 56.6K subs) with an integrated Kalshi prediction-market sponsorship.",
        ),
        (
            "MGMIKE",
            "Magic Mike Franchise Parody",
            "FILM_TV",
            "Warner Bros. Discovery",
            "film_tv",
            ["Magic Mike at Home", "@lewsharpy", "We Got X at Home"],
            "Real TikTok living-room visual parody ('We got magic mike at home') by @lewsharpy reaching 310.9K likes and 21.8K shares.",
        ),
    ]

    for spec in entities_spec:
        db.upsert_entity(*spec)

    # 100% real-world signals (real tracks, real M&A deal, and real v0.3-real posts with real URLs)
    signals_spec: List[Dict[str, Any]] = [
        # FAOUZ.UN (real 2026 MUSIC breakout)
        {
            "ticker": "FAOUZ.UN",
            "captured_at": "2026-11-22T15:00:00Z",
            "title": "Faouzia — 'UNETHICAL' surges via TikTok short-form clips & Add to Music App saves",
            "summary": "Faouzia's breakup single 'UNETHICAL' accelerated across TikTok short-form edits and Spotify saves, crossing into multi-million daily Spotify streams and triggering broad social discovery.",
            "platforms": ["TikTok", "Spotify", "Instagram Reels"],
            "metrics": {
                "unique_creators_using_sound": 180,
                "save_rate_pct": 5.2,
                "google_trends_index": 48,
                "breakout_ratio_views_to_followers": 9.4,
            },
            "samples": ["Faouzia — 'UNETHICAL' (TikTok viral breakup edit sound)"],
            "entities_mentioned": ["Faouzia", "UNETHICAL", "Warner Music Group"],
            "source_type": "real_web",
        },
        {
            "ticker": "FAOUZ.UN",
            "captured_at": "2026-11-24T18:00:00Z",
            "title": "Faouzia — 'UNETHICAL' debuts on Billboard Hot 100 & Billboard Global 200",
            "summary": "Confirmed cross-platform breakout: Faouzia's 'UNETHICAL' earned her first-ever Billboard Hot 100 entry and major Billboard Global 200 placement backed by millions of daily Spotify streams.",
            "platforms": ["TikTok", "Spotify", "Billboard", "Google Trends", "News"],
            "metrics": {
                "billboard_hot_100_entry": True,
                "billboard_global_200": True,
                "google_trends_index": 74,
                "gdelt_articles": 14,
            },
            "samples": ["Billboard: Faouzia scores first-ever Billboard Hot 100 entry with 'UNETHICAL'"],
            "entities_mentioned": ["Faouzia", "UNETHICAL", "Billboard"],
            "source_type": "real_web",
        },
        # SOMBR.BF (real 2026 MUSIC sustained viral catalog)
        {
            "ticker": "SOMBR.BF",
            "captured_at": "2026-11-24T14:00:00Z",
            "title": "Sombr — 'Back to Friends' sustains historic multi-week Billboard Global 200 run",
            "summary": "Following its viral TikTok takeoff, Sombr's 'Back to Friends' converted short-form video loops into sustained global Spotify streaming volume and historic multi-week Billboard Global 200 longevity.",
            "platforms": ["TikTok", "Spotify", "Billboard", "YouTube"],
            "metrics": {
                "billboard_global_200": True,
                "google_trends_index": 64,
                "gdelt_articles": 9,
            },
            "samples": ["TikTok Music Report: 'Back to Friends' converts viral clips into long-term Spotify streaming power"],
            "entities_mentioned": ["Sombr", "Back to Friends", "Warner Records"],
            "source_type": "real_web",
        },
        # SONY.RMG (real 2026 DEALS megadeal)
        {
            "ticker": "SONY.RMG",
            "captured_at": "2026-11-24T16:00:00Z",
            "title": "Sony Music Publishing & GIC close $3.5B–$4B acquisition of Recognition Music Group (Hipgnosis)",
            "summary": "Sony Music Publishing, via a joint venture with Singapore sovereign wealth fund GIC, closed its landmark $3.5B–$4.0B acquisition of Recognition Music Group (formerly Hipgnosis Songs Fund, managed by Blackstone), covering 45,000+ songs.",
            "platforms": ["GDELT", "News", "X", "Google Trends"],
            "metrics": {
                "deal_value_usd_b": 3.75,
                "catalog_song_count": 45000,
                "gdelt_articles": 24,
                "google_trends_index": 68,
            },
            "samples": ["Music Business Worldwide: Sony Music Publishing & GIC close $3.5B–$4B Recognition Music Group deal"],
            "entities_mentioned": ["Sony Music Publishing", "Recognition Music Group", "Hipgnosis", "GIC", "Blackstone"],
            "source_type": "real_web",
        },
        # KATT.FMT (real v0.3-real TikTok post)
        {
            "ticker": "KATT.FMT",
            "captured_at": "2026-11-24T19:00:00Z",
            "title": "TikTok @jcrow73 Katt Williams CapCut template hits 45% share-to-like ratio",
            "summary": "TikTok video by @jcrow73 with overlay text 'When someone asks me about my husband's work ethic' over a front-porch background with a green-screen cutout of Katt Williams and a 'CapCut · Try this template' prompt. Metrics: 78.6K likes, 35.3K shares (~45% share-to-like), 5,954 bookmarks, 464 comments.",
            "platforms": ["TikTok"],
            "metrics": {
                "likes": 78600,
                "shares": 35300,
                "bookmarks": 5954,
                "comments": 464,
                "share_to_like_ratio": 0.449,
                "capcut_template_enabled": True,
            },
            "samples": ["'When someone asks me about my husband's work ethic'"],
            "entities_mentioned": ["Katt Williams", "CapCut", "@jcrow73"],
            "url": "https://www.tiktok.com/@jcrow73/video/7701835190682881293",
            "source_type": "real_post",
        },
        # NVDA.IP (2 real v0.3-real posts)
        {
            "ticker": "NVDA.IP",
            "captured_at": "2026-11-23T19:19:00Z",
            "title": "X @greghunkins: AI Jensen Huang Kanye 2005 Grammys speech hits 488.2K views",
            "summary": "X video post by @greghunkins captioned 'Jensen Huang gives his return speech as CEO of NVIDIA' showing AI-generated Jensen Huang in a white suit on a blue-lit award-show stage with giant 'AW' letters. Metrics: 488.2K views, 9.4K likes, 1.9K bookmarks, 851 reposts, 61 replies.",
            "platforms": ["X"],
            "metrics": {"views": 488200, "likes": 9400, "reposts": 851, "bookmarks": 1900, "replies": 61},
            "samples": ["'Jensen Huang gives his return speech as CEO of NVIDIA'", "'Kanye Grammys award 2005'"],
            "entities_mentioned": ["Jensen Huang", "NVIDIA", "Kanye West"],
            "url": "https://x.com/greghunkins/status/2125036647548908005",
            "source_type": "real_post",
        },
        {
            "ticker": "NVDA.IP",
            "captured_at": "2026-11-24T18:00:00Z",
            "title": "IG @cgpw: Unauthorized AI Jensen Huang mirror selfie with gold GPU hits 106K likes",
            "summary": "Verified Instagram account @cgpw (labeled 'AI content') posted an AI-generated mirror selfie of NVIDIA CEO Jensen Huang in a black NVIDIA t-shirt holding a gold triple-fan GPU surrounded by four young women. Metrics at 1 day: 106K likes, 385 comments.",
            "platforms": ["Instagram"],
            "metrics": {"likes": 106000, "comments": 385, "ai_generated_label": True},
            "samples": ["'His Huangout'", "'Tá difícil investir...'"],
            "entities_mentioned": ["Jensen Huang", "NVIDIA", "@cgpw"],
            "url": "https://www.instagram.com/p/DgGXIyJIm_j/",
            "source_type": "real_post",
        },
        # GTA6 (real v0.3-real X post)
        {
            "ticker": "GTA6",
            "captured_at": "2026-11-19T12:20:00Z",
            "title": "X @EsemicolonR: Captionless GTA 6 meme-phone clip hits 1M views inside commentary bubble",
            "summary": "Captionless video post on X by commentary creator E;R (@EsemicolonR) showing a first-person GTA 6-style beach/car driving clip. Metrics: 1M views, 46K likes, 9.3K bookmarks, 4K reposts, 198 replies; hyper-niche X/gaming commentary jokes.",
            "platforms": ["X"],
            "metrics": {"views": 1000000, "likes": 46000, "reposts": 4000, "bookmarks": 9300, "replies": 198},
            "samples": ["'Grand Theft O Algo'"],
            "entities_mentioned": ["E;R", "GTA 6", "Rockstar Games"],
            "url": "https://x.com/EsemicolonR/status/2123481490851791146",
            "source_type": "real_post",
        },
        # LEAF.NHL (real v0.3-real YouTube Short)
        {
            "ticker": "LEAF.NHL",
            "captured_at": "2026-11-24T17:00:00Z",
            "title": "YT Shorts @thefknshow: Maple Leafs 'They know it's over' hits 4.8x subs with Kalshi sponsor",
            "summary": "Sports creator @thefknshow (56.6K subscribers) uploaded a Maple Leafs breakdown Short hitting 272K views (4.8x subscriber baseline) with an integrated Kalshi prediction-market sponsorship.",
            "platforms": ["YouTube Shorts"],
            "metrics": {"views": 272000, "creator_subscribers": 56600, "breakout_ratio_views_to_followers": 4.8},
            "samples": ["'They know it's over — sponsored by Kalshi'"],
            "entities_mentioned": ["Toronto Maple Leafs", "Kalshi", "@thefknshow"],
            "source_type": "real_post",
        },
        # MGMIKE (real v0.3-real TikTok post)
        {
            "ticker": "MGMIKE",
            "captured_at": "2024-09-21T12:00:00Z",
            "title": "TikTok @lewsharpy: 'We got magic mike at home' hits 310.9K likes",
            "summary": "Verified TikTok creator @lewsharpy posted a living-room dance parody with on-screen text 'We got magic mike at home' and #MagicMikeAtHome. Metrics: 310.9K likes, 21.8K shares, 15.8K bookmarks, 401 comments.",
            "platforms": ["TikTok"],
            "metrics": {"likes": 310900, "shares": 21800, "bookmarks": 15800, "comments": 401},
            "samples": ["'We got magic mike at home'"],
            "entities_mentioned": ["Magic Mike", "@lewsharpy"],
            "url": "https://www.tiktok.com/@lewsharpy/video/7417165001837858081",
            "source_type": "real_post",
        },
        # JUSTUS.R (real v0.3-real YouTube Short)
        {
            "ticker": "JUSTUS.R",
            "captured_at": "2026-11-24T19:00:00Z",
            "title": "YT Shorts @justus_reid: 'Rebuilding my House - Part 4' hits 156K views in 6h (0.21x subs)",
            "summary": "Creator Justus_Reid (@justus_reid, 739K subscribers) uploaded 'Rebuilding my House - Part 4' ~6 hours ago. Raw metrics at 6h: 156,332 views (0.21x subs), 14,579 likes, 192 comments from loyal serialized fans.",
            "platforms": ["YouTube Shorts"],
            "metrics": {"hours_live": 6, "creator_subscribers": 739000, "views": 156332, "likes": 14579, "comments": 192},
            "samples": ["'Man I remember the first episode of my 5000€ house'"],
            "entities_mentioned": ["Justus_Reid"],
            "url": "https://www.youtube.com/shorts/O8P8iXzWlzQ",
            "source_type": "real_post",
        },
        # MRSPRAY (real v0.3-real Facebook Reel)
        {
            "ticker": "MRSPRAY",
            "captured_at": "2026-11-24T19:00:00Z",
            "title": "FB Reels Mr. Spray: Cancun suitcase spray-paint hits 1.2M likes",
            "summary": "Public Facebook Reel by 'Mr. Spray' titled 'Mexican Street Magician Transforms My Suitcase 🤯' filmed in Cancun. Metrics: 1.2M likes, 18.7K comments, 24K shares on Facebook Reels, with no cross-platform meme or news adoption.",
            "platforms": ["Facebook Reels"],
            "metrics": {"likes": 1200000, "comments": 18700, "shares": 24000},
            "samples": ["'Mexican Street Magician Transforms My Suitcase 🤯'"],
            "entities_mentioned": ["Mr. Spray", "Cancun"],
            "url": "https://www.facebook.com/reel/1392351423052206",
            "source_type": "real_post",
        },
    ]

    inserted_signals: List[Dict[str, Any]] = []
    for item in signals_spec:
        sig = db.insert_signal(**item)
        inserted_signals.append(sig)

    by_ticker: Dict[str, List[Dict[str, Any]]] = {}
    for sig in inserted_signals:
        by_ticker.setdefault(sig["ticker"], []).append(sig)

    # 4 resolved real-world predictions (ready for immediate IPX-Eval JSONL export!)
    resolved_specs = [
        {
            "signal": by_ticker["FAOUZ.UN"][0],
            "category": "breakout",
            "predicted_label": "breakout",
            "confidence": 0.90,
            "difficulty": "medium",
            "window": 48,
            "gt_label": "breakout",
            "secondary": "tiktok_to_billboard_hot100",
            "concepts": [
                ["faouzia", "unethical"],
                ["tiktok", "spotify", "save"],
                ["billboard", "hot 100", "breakout"],
            ],
            "rationale": "Verified: Faouzia's 'UNETHICAL' converted viral TikTok & Spotify save momentum into her first-ever Billboard Hot 100 entry and Billboard Global 200 placement.",
            "outcome_metrics": {"billboard_hot_100": True, "billboard_global_200": True},
        },
        {
            "signal": by_ticker["KATT.FMT"][0],
            "category": "breakout",
            "predicted_label": "breakout",
            "confidence": 0.88,
            "difficulty": "hard",
            "window": 72,
            "gt_label": "breakout",
            "secondary": "capcut_template_high_share_ratio",
            "concepts": [
                ["share", "35.3k", "45%", "share-to-like"],
                ["capcut", "template", "cutout", "remix"],
                ["katt williams", "breakout"],
            ],
            "rationale": "Confirmed breakout mechanic: 35.3K shares on 78.6K likes (~45% share-to-like ratio), 5,954 bookmarks, and a 1-tap CapCut cutout template.",
            "outcome_metrics": {},
        },
        {
            "signal": by_ticker["GTA6"][0],
            "category": "contagion",
            "predicted_label": "echo_chamber",
            "confidence": 0.84,
            "difficulty": "hard",
            "window": 48,
            "gt_label": "echo_chamber",
            "secondary": "niche_x_gaming_commentary_bubble",
            "concepts": [
                ["1m", "46k", "single platform", "x"],
                ["inside joke", "commentary", "grand theft o algo", "subculture"],
                ["echo chamber", "cross-platform", "mainstream"],
            ],
            "rationale": "Confirmed echo_chamber: despite 1M views and 46K likes on X, the captionless edit and creator-specific replies remained inside a niche X/gaming commentary bubble.",
            "outcome_metrics": {},
        },
        {
            "signal": by_ticker["NVDA.IP"][0],
            "category": "lineage",
            "predicted_label": "character_transplant",
            "confidence": 0.86,
            "difficulty": "hard",
            "window": None,
            "gt_label": "character_transplant",
            "secondary": "ai_lipsync_pop_culture_speech_swap",
            "concepts": [
                ["kanye", "2005", "grammy", "speech"],
                ["jensen huang", "nvidia", "ceo"],
                ["character transplant", "swap", "ai", "white suit"],
            ],
            "rationale": "Confirmed character_transplant: Kanye West's 2005 Grammys white-suit acceptance speech template was preserved and transplanted onto NVIDIA CEO Jensen Huang via AI video.",
            "outcome_metrics": {},
        },
    ]

    for spec in resolved_specs:
        pred = db.create_prediction(
            signal_id=spec["signal"]["id"],
            category=spec["category"],
            predicted_label=spec["predicted_label"],
            confidence=spec["confidence"],
            difficulty=spec["difficulty"],
            outcome_window_hours=spec["window"],
            analyst_notes="Verified real-world IPX Terminal call.",
        )
        db.resolve_prediction(
            prediction_id=pred["id"],
            ground_truth_label=spec["gt_label"],
            secondary_label=spec["secondary"],
            required_concepts=spec["concepts"],
            rationale=spec["rationale"],
            outcome_window_hours=spec["window"],
            outcome_metrics=spec["outcome_metrics"],
        )

    # 3 pending real-world predictions in the LOG desk
    pending_specs = [
        (by_ticker["NVDA.IP"][1], "ip_catalyst", "rights_risk", 0.89, 48, "Unauthorized AI CEO likeness + NVIDIA branding."),
        (by_ticker["LEAF.NHL"][0], "ip_catalyst", "brand_partnership", 0.92, 48, "Kalshi prediction-market integration on 4.8x Short."),
        (by_ticker["SONY.RMG"][0], "ip_catalyst", "ma_deal", 0.94, 72, "Sony Music Publishing + GIC $3.5B-$4B Recognition/Hipgnosis catalog close."),
    ]
    for sig, cat, label, conf, win, notes in pending_specs:
        db.create_prediction(
            signal_id=sig["id"],
            category=cat,
            predicted_label=label,
            confidence=conf,
            outcome_window_hours=win,
            analyst_notes=notes,
        )

    return {
        "entities": len(entities_spec),
        "signals": len(inserted_signals),
        "predictions": len(resolved_specs) + len(pending_specs),
        "resolved": len(resolved_specs),
    }
