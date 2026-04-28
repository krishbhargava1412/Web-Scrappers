#!/usr/bin/env python3
"""Reddit Subreddit & Post Scraper
====================================
Scrapes posts, comments, upvotes, and user info from subreddits using
Reddit's public JSON endpoints (no API key required).

Usage:
    python reddit_scraper.py --subreddit technology --sort hot --limit 25
    python reddit_scraper.py --subreddit python --subreddit programming --sort top --timeframe week
    python reddit_scraper.py --subreddit india --comments --max-comments 10 --output output

Requirements:
    pip install requests

Limitations:
    - Uses Reddit's public .json endpoints, no authentication needed.
    - Rate limited to ~60 requests/minute by Reddit.
    - Comments are limited to the first page (top-level + some nested).
"""

from __future__ import annotations

import csv
import json
import logging
import random
import re
import time
import argparse
from dataclasses import dataclass, fields, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

# ── Configuration ─────────────────────────────────────────────────────────────

DEFAULT_SUBREDDITS = ["technology", "python"]
OUTPUT_DIR = "output"

REDDIT_BASE = "https://www.reddit.com"

USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/18.0 Safari/605.1.15"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) "
        "Gecko/20100101 Firefox/128.0"
    ),
]

DELAY_BETWEEN_REQUESTS = (1.5, 3.0)
MAX_POSTS_PER_PAGE = 25

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)


# ── Data Models ───────────────────────────────────────────────────────────────

@dataclass
class RedditPost:
    subreddit: str
    post_id: str
    title: str
    author: str
    score: int
    upvote_ratio: float
    num_comments: int
    created_utc: str
    url: str
    permalink: str
    selftext: str
    link_flair: str
    is_self: str
    is_nsfw: str
    is_pinned: str
    awards: int


@dataclass
class RedditComment:
    subreddit: str
    post_id: str
    comment_id: str
    author: str
    body: str
    score: int
    created_utc: str
    depth: int
    is_op: str
    permalink: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_headers() -> dict[str, str]:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }


def fetch_json(
    session: requests.Session,
    url: str,
    params: Optional[dict] = None,
    max_retries: int = 3,
) -> Optional[dict]:
    """Fetch a Reddit JSON endpoint with retries."""
    for attempt in range(1, max_retries + 1):
        try:
            session.headers.update(get_headers())
            response = session.get(url, params=params, timeout=20)

            if response.status_code == 429:
                wait = int(response.headers.get("Retry-After", 10))
                log.warning(f"Rate limited, waiting {wait}s (attempt {attempt})")
                time.sleep(wait)
                continue

            response.raise_for_status()
            return response.json()

        except requests.exceptions.HTTPError as e:
            log.warning(f"HTTP error {e.response.status_code} for {url} (attempt {attempt})")
            if attempt < max_retries:
                time.sleep(random.uniform(3, 6))
        except requests.exceptions.RequestException as e:
            log.warning(f"Request failed for {url}: {e} (attempt {attempt})")
            if attempt < max_retries:
                time.sleep(random.uniform(2, 5))
        except json.JSONDecodeError as e:
            log.warning(f"JSON decode error for {url}: {e}")
            return None
    return None


def random_delay() -> None:
    time.sleep(random.uniform(*DELAY_BETWEEN_REQUESTS))


def format_utc(timestamp: float) -> str:
    """Convert a UNIX timestamp to a human-readable UTC string."""
    try:
        return (
            datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
            .strftime("%Y-%m-%d %H:%M:%S UTC")
        )
    except (ValueError, OSError):
        return ""


def truncate(text: str, max_len: int = 500) -> str:
    """Truncate long text for CSV readability."""
    if not text:
        return ""
    text = text.replace("\n", " ").replace("\r", "").strip()
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


# ── Reddit Post Scraper ──────────────────────────────────────────────────────

def scrape_subreddit_posts(
    session: requests.Session,
    subreddit: str,
    sort: str = "hot",
    timeframe: str = "day",
    limit: int = 25,
) -> list[RedditPost]:
    """Scrape posts from a subreddit using the .json endpoint."""
    posts: list[RedditPost] = []
    after: Optional[str] = None
    fetched = 0

    while fetched < limit:
        batch_size = min(100, limit - fetched)
        url = f"{REDDIT_BASE}/r/{subreddit}/{sort}.json"
        params: dict = {"limit": str(batch_size), "raw_json": "1"}
        if sort == "top" or sort == "controversial":
            params["t"] = timeframe
        if after:
            params["after"] = after

        log.info(f"[Reddit] r/{subreddit}/{sort} — fetching {batch_size} posts (offset: {fetched})")
        data = fetch_json(session, url, params=params)

        if not data or "data" not in data:
            log.warning(f"[Reddit] No data returned for r/{subreddit}")
            break

        children = data["data"].get("children", [])
        if not children:
            break

        for child in children:
            if child.get("kind") != "t3":
                continue
            d = child["data"]

            posts.append(RedditPost(
                subreddit=subreddit,
                post_id=d.get("id", ""),
                title=truncate(d.get("title", ""), 300),
                author=d.get("author", "[deleted]"),
                score=d.get("score", 0),
                upvote_ratio=d.get("upvote_ratio", 0.0),
                num_comments=d.get("num_comments", 0),
                created_utc=format_utc(d.get("created_utc", 0)),
                url=d.get("url", ""),
                permalink=f"{REDDIT_BASE}{d.get('permalink', '')}",
                selftext=truncate(d.get("selftext", ""), 500),
                link_flair=d.get("link_flair_text") or "",
                is_self="Yes" if d.get("is_self") else "No",
                is_nsfw="Yes" if d.get("over_18") else "No",
                is_pinned="Yes" if d.get("stickied") else "No",
                awards=d.get("total_awards_received", 0),
            ))
            fetched += 1
            if fetched >= limit:
                break

        after = data["data"].get("after")
        if not after:
            break

        random_delay()

    log.info(f"[Reddit] r/{subreddit}: fetched {len(posts)} posts")
    return posts


# ── Reddit Comment Scraper ────────────────────────────────────────────────────

def scrape_post_comments(
    session: requests.Session,
    subreddit: str,
    post_id: str,
    max_comments: int = 20,
) -> list[RedditComment]:
    """Scrape comments from a specific Reddit post."""
    url = f"{REDDIT_BASE}/r/{subreddit}/comments/{post_id}.json"
    params = {"limit": str(max_comments), "sort": "top", "raw_json": "1"}

    log.info(f"[Reddit] Fetching comments for post {post_id} in r/{subreddit}")
    data = fetch_json(session, url, params=params)

    if not data or not isinstance(data, list) or len(data) < 2:
        return []

    comments: list[RedditComment] = []
    op_author = ""

    # First element is the post itself
    post_children = data[0].get("data", {}).get("children", [])
    if post_children and post_children[0].get("kind") == "t3":
        op_author = post_children[0]["data"].get("author", "")

    # Second element contains comments
    comment_children = data[1].get("data", {}).get("children", [])

    def extract_comments(children: list[dict], depth: int = 0) -> None:
        for child in children:
            if child.get("kind") != "t1":
                continue
            if len(comments) >= max_comments:
                return

            d = child["data"]
            author = d.get("author", "[deleted]")

            comments.append(RedditComment(
                subreddit=subreddit,
                post_id=post_id,
                comment_id=d.get("id", ""),
                author=author,
                body=truncate(d.get("body", ""), 500),
                score=d.get("score", 0),
                created_utc=format_utc(d.get("created_utc", 0)),
                depth=depth,
                is_op="Yes" if author == op_author else "No",
                permalink=f"{REDDIT_BASE}{d.get('permalink', '')}",
            ))

            # Recurse into replies
            replies = d.get("replies")
            if isinstance(replies, dict):
                reply_children = replies.get("data", {}).get("children", [])
                extract_comments(reply_children, depth + 1)

    extract_comments(comment_children)
    log.info(f"[Reddit] Post {post_id}: fetched {len(comments)} comments")
    return comments


# ── Subreddit Info ────────────────────────────────────────────────────────────

def scrape_subreddit_info(
    session: requests.Session,
    subreddit: str,
) -> Optional[dict]:
    """Fetch subreddit metadata (subscribers, description, etc.)."""
    url = f"{REDDIT_BASE}/r/{subreddit}/about.json"
    data = fetch_json(session, url, params={"raw_json": "1"})
    if not data or "data" not in data:
        return None

    d = data["data"]
    return {
        "name": d.get("display_name", subreddit),
        "title": d.get("title", ""),
        "subscribers": d.get("subscribers", 0),
        "active_users": d.get("accounts_active", 0),
        "description": truncate(d.get("public_description", ""), 300),
        "created_utc": format_utc(d.get("created_utc", 0)),
        "is_nsfw": d.get("over18", False),
        "url": f"{REDDIT_BASE}/r/{subreddit}/",
    }


# ── Search across subreddits ─────────────────────────────────────────────────

def search_reddit(
    session: requests.Session,
    query: str,
    subreddit: Optional[str] = None,
    sort: str = "relevance",
    timeframe: str = "all",
    limit: int = 25,
) -> list[RedditPost]:
    """Search Reddit for posts matching a query."""
    if subreddit:
        url = f"{REDDIT_BASE}/r/{subreddit}/search.json"
        params = {"q": query, "restrict_sr": "on", "sort": sort, "t": timeframe,
                  "limit": str(min(limit, 100)), "raw_json": "1"}
    else:
        url = f"{REDDIT_BASE}/search.json"
        params = {"q": query, "sort": sort, "t": timeframe,
                  "limit": str(min(limit, 100)), "raw_json": "1"}

    log.info(f"[Reddit] Searching: '{query}' (sort={sort}, t={timeframe})")
    data = fetch_json(session, url, params=params)
    if not data or "data" not in data:
        return []

    posts: list[RedditPost] = []
    for child in data["data"].get("children", [])[:limit]:
        if child.get("kind") != "t3":
            continue
        d = child["data"]
        sub = d.get("subreddit", "unknown")
        posts.append(RedditPost(
            subreddit=sub,
            post_id=d.get("id", ""),
            title=truncate(d.get("title", ""), 300),
            author=d.get("author", "[deleted]"),
            score=d.get("score", 0),
            upvote_ratio=d.get("upvote_ratio", 0.0),
            num_comments=d.get("num_comments", 0),
            created_utc=format_utc(d.get("created_utc", 0)),
            url=d.get("url", ""),
            permalink=f"{REDDIT_BASE}{d.get('permalink', '')}",
            selftext=truncate(d.get("selftext", ""), 500),
            link_flair=d.get("link_flair_text") or "",
            is_self="Yes" if d.get("is_self") else "No",
            is_nsfw="Yes" if d.get("over_18") else "No",
            is_pinned="Yes" if d.get("stickied") else "No",
            awards=d.get("total_awards_received", 0),
        ))

    log.info(f"[Reddit] Search returned {len(posts)} posts")
    return posts


# ── CSV Writers ───────────────────────────────────────────────────────────────

def save_posts_csv(posts: list[RedditPost], filepath: Path) -> None:
    if not posts:
        log.warning("No posts to save.")
        return
    filepath.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [f.name for f in fields(RedditPost)]
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for p in posts:
            writer.writerow(asdict(p))
    log.info(f"Saved {len(posts)} posts to '{filepath}'")


def save_comments_csv(comments: list[RedditComment], filepath: Path) -> None:
    if not comments:
        log.warning("No comments to save.")
        return
    filepath.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [f.name for f in fields(RedditComment)]
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for c in comments:
            writer.writerow(asdict(c))
    log.info(f"Saved {len(comments)} comments to '{filepath}'")


def save_subreddit_info_csv(infos: list[dict], filepath: Path) -> None:
    if not infos:
        return
    filepath.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(infos[0].keys())
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(infos)
    log.info(f"Saved {len(infos)} subreddit info entries to '{filepath}'")


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape Reddit subreddits, posts, and comments."
    )
    parser.add_argument(
        "-r", "--subreddit",
        action="append",
        default=[],
        help="Subreddit to scrape (without r/). Repeat for multiple.",
    )
    parser.add_argument(
        "-q", "--search",
        default="",
        help="Search query (searches across Reddit or within --subreddit).",
    )
    parser.add_argument(
        "--sort",
        choices=["hot", "new", "top", "rising", "controversial", "relevance"],
        default="hot",
        help="Sort order for posts (default: hot). 'relevance' is for search.",
    )
    parser.add_argument(
        "--timeframe",
        choices=["hour", "day", "week", "month", "year", "all"],
        default="week",
        help="Timeframe for top/controversial sort (default: week).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Maximum posts to fetch per subreddit (default: 25).",
    )
    parser.add_argument(
        "--comments",
        action="store_true",
        help="Also scrape comments from the top posts.",
    )
    parser.add_argument(
        "--max-comments",
        type=int,
        default=20,
        help="Max comments per post (default: 20).",
    )
    parser.add_argument(
        "--comment-posts",
        type=int,
        default=5,
        help="Number of top posts to fetch comments from (default: 5).",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=OUTPUT_DIR,
        help=f"Output directory (default: {OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--info",
        action="store_true",
        help="Also fetch subreddit metadata (subscribers, etc.).",
    )
    parser.add_argument(
        "--use-env-proxies",
        action="store_true",
        help="Honor HTTP(S)_PROXY environment variables.",
    )
    return parser


def main(
    subreddits: Optional[list[str]] = None,
    search_query: str = "",
    sort: str = "hot",
    timeframe: str = "week",
    limit: int = 25,
    scrape_comments: bool = False,
    max_comments: int = 20,
    comment_posts: int = 5,
    output_dir: str = OUTPUT_DIR,
    fetch_info: bool = False,
    use_env_proxies: bool = False,
) -> int:
    subreddits = subreddits or DEFAULT_SUBREDDITS
    output_path = Path(output_dir)

    session = requests.Session()
    session.headers.update(get_headers())
    session.trust_env = use_env_proxies

    all_posts: list[RedditPost] = []
    all_comments: list[RedditComment] = []
    all_infos: list[dict] = []

    # Subreddit info
    if fetch_info:
        for sub in subreddits:
            info = scrape_subreddit_info(session, sub)
            if info:
                all_infos.append(info)
                print(f"  r/{sub}: {info['subscribers']:,} subscribers, "
                      f"{info['active_users']:,} online")
            random_delay()

    # Search or browse
    if search_query:
        for sub in subreddits:
            posts = search_reddit(
                session, search_query, subreddit=sub,
                sort=sort if sort != "hot" else "relevance",
                timeframe=timeframe, limit=limit,
            )
            all_posts.extend(posts)
            random_delay()
    else:
        for sub in subreddits:
            posts = scrape_subreddit_posts(
                session, sub, sort=sort,
                timeframe=timeframe, limit=limit,
            )
            all_posts.extend(posts)
            random_delay()

    # Comments
    if scrape_comments and all_posts:
        # Pick top posts by score
        top_posts = sorted(all_posts, key=lambda p: p.score, reverse=True)[:comment_posts]
        for post in top_posts:
            comments = scrape_post_comments(
                session, post.subreddit, post.post_id,
                max_comments=max_comments,
            )
            all_comments.extend(comments)
            random_delay()

    # Save
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_posts_csv(all_posts, output_path / f"reddit_posts_{timestamp}.csv")
    if all_comments:
        save_comments_csv(all_comments, output_path / f"reddit_comments_{timestamp}.csv")
    if all_infos:
        save_subreddit_info_csv(all_infos, output_path / f"reddit_subreddits_{timestamp}.csv")

    print(f"\nDone! {len(all_posts)} posts scraped from {len(subreddits)} subreddit(s)")
    if all_comments:
        print(f"     {len(all_comments)} comments scraped")
    print(f"     Output: {output_path.resolve()}")
    return 0


if __name__ == "__main__":
    args = build_parser().parse_args()
    raise SystemExit(
        main(
            subreddits=args.subreddit or None,
            search_query=args.search,
            sort=args.sort,
            timeframe=args.timeframe,
            limit=args.limit,
            scrape_comments=args.comments,
            max_comments=args.max_comments,
            comment_posts=args.comment_posts,
            output_dir=args.output_dir,
            fetch_info=args.info,
            use_env_proxies=args.use_env_proxies,
        )
    )
