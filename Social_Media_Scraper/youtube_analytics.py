#!/usr/bin/env python3
"""YouTube Channel & Video Analytics Scraper
==============================================
Scrapes public YouTube channel statistics, video listings, and engagement
metrics using yt-dlp's extraction engine (already installed) and YouTube's
public Innertube API.

Usage:
    python youtube_analytics.py --channel "@mkbhd" --videos --limit 20
    python youtube_analytics.py --channel "UCBcRF18a7Qf58cCRy5xuWwQ" --output output
    python youtube_analytics.py --search "python tutorial" --limit 10

Requirements:
    pip install yt-dlp requests

Limitations:
    - Uses public data only; no YouTube Data API key required.
    - Subscriber counts may be approximate (YouTube rounds them).
    - Video view/like counts are fetched per-video and may be rate limited.
"""

from __future__ import annotations

import csv
import json
import logging
import random
import re
import subprocess
import sys
import time
import argparse
from dataclasses import dataclass, fields, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

# ── Configuration ─────────────────────────────────────────────────────────────

OUTPUT_DIR = "output"

INNERTUBE_API_URL = "https://www.youtube.com/youtubei/v1/browse"
INNERTUBE_SEARCH_URL = "https://www.youtube.com/youtubei/v1/search"
INNERTUBE_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"

INNERTUBE_CONTEXT = {
    "client": {
        "clientName": "WEB",
        "clientVersion": "2.20250101.00.00",
        "hl": "en",
        "gl": "US",
    }
}

USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
]

DELAY_BETWEEN_REQUESTS = (1.0, 2.5)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)


# ── Data Models ───────────────────────────────────────────────────────────────

@dataclass
class YouTubeChannel:
    channel_id: str
    name: str
    handle: str
    subscribers: str
    total_views: str
    video_count: str
    description: str
    joined_date: str
    country: str
    url: str
    thumbnail_url: str


@dataclass
class YouTubeVideo:
    channel_name: str
    channel_id: str
    video_id: str
    title: str
    views: str
    likes: str
    duration: str
    upload_date: str
    description: str
    tags: str
    category: str
    url: str
    thumbnail_url: str
    comment_count: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_headers() -> dict[str, str]:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "Origin": "https://www.youtube.com",
        "Referer": "https://www.youtube.com/",
    }


def random_delay() -> None:
    time.sleep(random.uniform(*DELAY_BETWEEN_REQUESTS))


def parse_count(text: str) -> str:
    """Parse YouTube abbreviated counts like '1.2M', '345K' to raw numbers or keep as-is."""
    if not text:
        return "0"
    text = text.strip().replace(",", "")
    # Already a number
    if text.isdigit():
        return text
    # Abbreviated
    multipliers = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    match = re.match(r"^([\d.]+)\s*([KMB])", text, re.IGNORECASE)
    if match:
        num = float(match.group(1))
        mult = multipliers.get(match.group(2).upper(), 1)
        return str(int(num * mult))
    # Extract any number
    digits = re.sub(r"[^\d]", "", text)
    return digits or "0"


def format_duration(seconds: int) -> str:
    """Convert seconds to HH:MM:SS or MM:SS."""
    if seconds <= 0:
        return "0:00"
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


# ── yt-dlp based extraction (most reliable) ──────────────────────────────────

def extract_with_ytdlp(url: str, extra_args: Optional[list[str]] = None) -> Optional[dict]:
    """Use yt-dlp to extract metadata without downloading."""
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--dump-json",
        "--no-download",
        "--no-warnings",
        "--flat-playlist",
    ]
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(url)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if result.returncode != 0:
            log.warning(f"yt-dlp error: {result.stderr[:200]}")
            return None

        # yt-dlp may output multiple JSON objects (one per video)
        lines = [line for line in result.stdout.strip().split("\n") if line.strip()]
        if not lines:
            return None

        # Return all entries as a list
        entries = []
        for line in lines:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if len(entries) == 1:
            return entries[0]
        return {"_type": "playlist", "entries": entries}

    except subprocess.TimeoutExpired:
        log.warning("yt-dlp timed out")
        return None
    except Exception as e:
        log.warning(f"yt-dlp extraction failed: {e}")
        return None


def extract_single_video(url: str) -> Optional[dict]:
    """Extract full metadata for a single video (not flat)."""
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--dump-json",
        "--no-download",
        "--no-warnings",
        url,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except Exception:
        return None


# ── Channel Scraper ───────────────────────────────────────────────────────────

def scrape_channel(
    session: requests.Session,
    channel_input: str,
) -> Optional[YouTubeChannel]:
    """Scrape channel metadata using yt-dlp."""
    # Determine URL
    if channel_input.startswith("http"):
        url = channel_input
    elif channel_input.startswith("@"):
        url = f"https://www.youtube.com/{channel_input}"
    elif channel_input.startswith("UC"):
        url = f"https://www.youtube.com/channel/{channel_input}"
    else:
        url = f"https://www.youtube.com/@{channel_input}"

    log.info(f"[YouTube] Fetching channel info: {url}")

    # Use yt-dlp to extract channel page
    data = extract_with_ytdlp(url + "/about", ["--playlist-items", "0"])

    # Fallback: try fetching channel page HTML
    if not data:
        data = extract_with_ytdlp(url, ["--playlist-items", "1"])

    if not data:
        log.warning(f"[YouTube] Could not extract channel data for '{channel_input}'")
        return None

    # Extract from yt-dlp data
    channel_id = data.get("channel_id") or data.get("uploader_id") or ""
    channel_name = data.get("channel") or data.get("uploader") or channel_input

    return YouTubeChannel(
        channel_id=channel_id,
        name=channel_name,
        handle=data.get("uploader_id") or "",
        subscribers=str(data.get("channel_follower_count") or "N/A"),
        total_views="N/A",  # Not always available via yt-dlp
        video_count="N/A",
        description=data.get("description", "")[:300] or "N/A",
        joined_date="N/A",
        country=data.get("location") or "N/A",
        url=data.get("channel_url") or url,
        thumbnail_url=data.get("thumbnail") or "N/A",
    )


# ── Video List Scraper ────────────────────────────────────────────────────────

def scrape_channel_videos(
    session: requests.Session,
    channel_input: str,
    limit: int = 20,
    fetch_details: bool = False,
) -> tuple[Optional[YouTubeChannel], list[YouTubeVideo]]:
    """Scrape video list from a YouTube channel."""
    # Determine URL
    if channel_input.startswith("http"):
        url = channel_input.rstrip("/")
        if "/videos" not in url:
            url += "/videos"
    elif channel_input.startswith("@"):
        url = f"https://www.youtube.com/{channel_input}/videos"
    elif channel_input.startswith("UC"):
        url = f"https://www.youtube.com/channel/{channel_input}/videos"
    else:
        url = f"https://www.youtube.com/@{channel_input}/videos"

    log.info(f"[YouTube] Fetching videos: {url}")
    data = extract_with_ytdlp(url, ["--playlist-items", f"1:{limit}"])

    if not data:
        log.warning(f"[YouTube] No video data returned for '{channel_input}'")
        return None, []

    videos: list[YouTubeVideo] = []
    entries = data.get("entries", [data]) if data.get("_type") == "playlist" else [data]
    channel_name = ""
    channel_id = ""

    for entry in entries[:limit]:
        vid_id = entry.get("id") or entry.get("url", "").split("=")[-1]
        if not vid_id:
            continue

        ch_name = entry.get("channel") or entry.get("uploader") or ""
        ch_id = entry.get("channel_id") or entry.get("uploader_id") or ""
        if ch_name:
            channel_name = ch_name
        if ch_id:
            channel_id = ch_id

        title = entry.get("title") or "N/A"
        views = str(entry.get("view_count") or "N/A")
        likes = str(entry.get("like_count") or "N/A")
        duration = entry.get("duration")
        duration_str = format_duration(int(duration)) if duration else "N/A"
        upload_date = entry.get("upload_date") or ""
        if upload_date and len(upload_date) == 8:
            upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
        description = (entry.get("description") or "")[:300]
        tags = ", ".join(entry.get("tags") or [])[:200]

        videos.append(YouTubeVideo(
            channel_name=ch_name or channel_name,
            channel_id=ch_id or channel_id,
            video_id=vid_id,
            title=title,
            views=views,
            likes=likes,
            duration=duration_str,
            upload_date=upload_date,
            description=description or "N/A",
            tags=tags or "N/A",
            category=entry.get("categories", ["N/A"])[0] if entry.get("categories") else "N/A",
            url=f"https://www.youtube.com/watch?v={vid_id}",
            thumbnail_url=entry.get("thumbnail") or "N/A",
            comment_count=str(entry.get("comment_count") or "N/A"),
        ))

    # Optionally fetch full details for each video (slower but more data)
    if fetch_details and videos:
        log.info(f"[YouTube] Fetching detailed stats for {len(videos)} videos...")
        for i, video in enumerate(videos):
            if video.views == "N/A" or video.likes == "N/A":
                detail = extract_single_video(video.url)
                if detail:
                    video.views = str(detail.get("view_count") or video.views)
                    video.likes = str(detail.get("like_count") or video.likes)
                    video.comment_count = str(detail.get("comment_count") or video.comment_count)
                    if not video.tags or video.tags == "N/A":
                        video.tags = ", ".join(detail.get("tags") or [])[:200] or "N/A"
                random_delay()

    # Build channel info from video data
    channel_info = None
    if channel_name:
        channel_info = YouTubeChannel(
            channel_id=channel_id,
            name=channel_name,
            handle="",
            subscribers="N/A",
            total_views="N/A",
            video_count=str(len(videos)),
            description="N/A",
            joined_date="N/A",
            country="N/A",
            url=f"https://www.youtube.com/channel/{channel_id}" if channel_id else "",
            thumbnail_url="N/A",
        )

    log.info(f"[YouTube] Fetched {len(videos)} videos for '{channel_name or channel_input}'")
    return channel_info, videos


# ── YouTube Search ────────────────────────────────────────────────────────────

def search_youtube(
    session: requests.Session,
    query: str,
    limit: int = 10,
) -> list[YouTubeVideo]:
    """Search YouTube for videos matching a query using yt-dlp."""
    url = f"ytsearch{limit}:{query}"
    log.info(f"[YouTube] Searching: '{query}' (limit: {limit})")

    data = extract_with_ytdlp(url)
    if not data:
        return []

    videos: list[YouTubeVideo] = []
    entries = data.get("entries", [data]) if data.get("_type") == "playlist" else [data]

    for entry in entries[:limit]:
        vid_id = entry.get("id") or ""
        if not vid_id:
            continue

        duration = entry.get("duration")
        duration_str = format_duration(int(duration)) if duration else "N/A"
        upload_date = entry.get("upload_date") or ""
        if upload_date and len(upload_date) == 8:
            upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"

        videos.append(YouTubeVideo(
            channel_name=entry.get("channel") or entry.get("uploader") or "N/A",
            channel_id=entry.get("channel_id") or "",
            video_id=vid_id,
            title=entry.get("title") or "N/A",
            views=str(entry.get("view_count") or "N/A"),
            likes=str(entry.get("like_count") or "N/A"),
            duration=duration_str,
            upload_date=upload_date,
            description=(entry.get("description") or "")[:300] or "N/A",
            tags=", ".join(entry.get("tags") or [])[:200] or "N/A",
            category=entry.get("categories", ["N/A"])[0] if entry.get("categories") else "N/A",
            url=f"https://www.youtube.com/watch?v={vid_id}",
            thumbnail_url=entry.get("thumbnail") or "N/A",
            comment_count=str(entry.get("comment_count") or "N/A"),
        ))

    log.info(f"[YouTube] Search returned {len(videos)} videos")
    return videos


# ── CSV Writers ───────────────────────────────────────────────────────────────

def save_channels_csv(channels: list[YouTubeChannel], filepath: Path) -> None:
    if not channels:
        return
    filepath.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [f.name for f in fields(YouTubeChannel)]
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for ch in channels:
            writer.writerow(asdict(ch))
    log.info(f"Saved {len(channels)} channels to '{filepath}'")


def save_videos_csv(videos: list[YouTubeVideo], filepath: Path) -> None:
    if not videos:
        log.warning("No videos to save.")
        return
    filepath.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [f.name for f in fields(YouTubeVideo)]
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for v in videos:
            writer.writerow(asdict(v))
    log.info(f"Saved {len(videos)} videos to '{filepath}'")


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape YouTube channel stats and video analytics."
    )
    parser.add_argument(
        "-c", "--channel",
        action="append",
        default=[],
        help="YouTube channel handle (@name), ID (UCxxxx), or URL. Repeat for multiple.",
    )
    parser.add_argument(
        "-s", "--search",
        default="",
        help="Search YouTube for videos matching this query.",
    )
    parser.add_argument(
        "--videos",
        action="store_true",
        help="Fetch video list for each channel.",
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="Fetch full details per video (slower, more complete data).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum videos to fetch per channel or search (default: 20).",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=OUTPUT_DIR,
        help=f"Output directory (default: {OUTPUT_DIR}).",
    )
    return parser


def main(
    channels: Optional[list[str]] = None,
    search_query: str = "",
    fetch_videos: bool = False,
    fetch_details: bool = False,
    limit: int = 20,
    output_dir: str = OUTPUT_DIR,
) -> int:
    output_path = Path(output_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    session = requests.Session()
    session.headers.update(get_headers())

    all_channels: list[YouTubeChannel] = []
    all_videos: list[YouTubeVideo] = []

    # Channel scraping
    if channels:
        for ch_input in channels:
            if fetch_videos or not search_query:
                channel_info, videos = scrape_channel_videos(
                    session, ch_input, limit=limit, fetch_details=fetch_details,
                )
                if channel_info:
                    # Also get subscriber count from channel page
                    full_info = scrape_channel(session, ch_input)
                    if full_info:
                        full_info.video_count = channel_info.video_count
                        all_channels.append(full_info)
                    else:
                        all_channels.append(channel_info)
                all_videos.extend(videos)
            else:
                info = scrape_channel(session, ch_input)
                if info:
                    all_channels.append(info)
            random_delay()

    # Search
    if search_query:
        videos = search_youtube(session, search_query, limit=limit)
        all_videos.extend(videos)

    # Save
    if all_channels:
        save_channels_csv(all_channels, output_path / f"youtube_channels_{timestamp}.csv")
    if all_videos:
        save_videos_csv(all_videos, output_path / f"youtube_videos_{timestamp}.csv")

    # Print summary
    if all_channels:
        print(f"\n{'─' * 70}")
        print("  YouTube Channel Summary")
        print(f"{'─' * 70}")
        for ch in all_channels:
            print(f"  {ch.name}")
            print(f"    Subscribers: {ch.subscribers}  |  Videos: {ch.video_count}")
            print(f"    URL: {ch.url}")
        print()

    if all_videos:
        print(f"  Total videos fetched: {len(all_videos)}")
        top = sorted(
            [v for v in all_videos if v.views.isdigit()],
            key=lambda v: int(v.views),
            reverse=True,
        )[:5]
        if top:
            print(f"\n  Top {len(top)} by views:")
            for v in top:
                print(f"    {int(v.views):>12,} views | {v.title[:50]}")

    print(f"\n  Output: {output_path.resolve()}")
    return 0


if __name__ == "__main__":
    args = build_parser().parse_args()
    raise SystemExit(
        main(
            channels=args.channel or None,
            search_query=args.search,
            fetch_videos=args.videos,
            fetch_details=args.details,
            limit=args.limit,
            output_dir=args.output_dir,
        )
    )
