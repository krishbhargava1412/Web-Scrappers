#!/usr/bin/env python3
"""Twitter / X Profile & Tweet Scraper
========================================
Scrapes public Twitter/X profiles and tweets by loading x.com in a
headless Chromium browser (Playwright) and intercepting the internal
GraphQL API responses that Twitter's frontend makes.

Usage:
    python twitter_scraper.py --user "elonmusk" --tweets --limit 20
    python twitter_scraper.py --user "MKBHD" --user "sundarpichai" --output output

Requirements:
    pip install playwright
    python -m playwright install chromium

Architecture:
    Nitter instances are largely dead as of 2026.  This scraper instead
    uses Playwright to open the real x.com profile page.  As the page
    loads, Twitter's JS makes GraphQL API calls (UserByScreenName,
    UserTweets) which carry structured JSON.  We intercept those API
    responses in-flight, giving us the exact same data the Twitter web
    client displays — including full engagement metrics and media URLs.

    Profile data (followers, bio, etc.) is extracted from the intercepted
    UserByScreenName API response.  Tweet data (text, likes, views, etc.)
    comes from the UserTweets API response.

    Because the browser executes real JavaScript and passes all anti-bot
    checks, this approach is far more reliable than Nitter instances or
    raw API requests.

Limitations:
    - Requires Playwright + Chromium browser binary.
    - Slower than pure requests-based scrapers (~15–30s per user).
    - Twitter may occasionally show CAPTCHA or login prompts.
    - Only public profiles and tweets are accessible.
"""

from __future__ import annotations

import csv
import json
import logging
import random
import re
import sys
import time
import argparse
from dataclasses import dataclass, fields, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Configuration ─────────────────────────────────────────────────────────────

OUTPUT_DIR = "output"
DELAY_BETWEEN_USERS = (3, 6)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# Force UTF-8 stdout on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ── Data Models ───────────────────────────────────────────────────────────────

@dataclass
class TwitterProfile:
    username: str
    display_name: str
    bio: str
    followers: str
    following: str
    tweet_count: str
    joined: str
    location: str
    website: str
    verified: str
    profile_image: str
    banner_image: str
    url: str


@dataclass
class Tweet:
    username: str
    tweet_id: str
    text: str
    created_at: str
    likes: str
    retweets: str
    replies: str
    quotes: str
    views: str
    bookmarks: str
    is_retweet: str
    is_reply: str
    has_media: str
    media_urls: str
    hashtags: str
    mentions: str
    url: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_print(text: str) -> None:
    """Print with fallback for terminals that choke on Unicode."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"))


# ── Playwright-based Twitter Scraper ──────────────────────────────────────────

def scrape_user(
    username: str,
    fetch_tweets: bool = True,
    limit: int = 20,
    headless: bool = True,
) -> tuple[Optional[TwitterProfile], list[Tweet]]:
    """Scrape a Twitter/X user's profile and tweets via Playwright.

    Opens x.com/<username> in headless Chromium, intercepts the GraphQL
    API responses (UserByScreenName, UserTweets), and parses the JSON
    payloads for structured profile and tweet data.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error(
            "Playwright is required for Twitter scraping.\n"
            "Install with: pip install playwright && python -m playwright install chromium"
        )
        return None, []

    username = username.lstrip("@")
    profile_url = f"https://x.com/{username}"

    log.info(f"[Twitter] Launching browser for @{username}")

    api_data: dict[str, dict] = {}

    def _capture_response(response):
        """Intercept Twitter GraphQL API responses."""
        url = response.url
        try:
            if "UserBy" in url and response.status == 200:
                api_data["user"] = response.json()
            elif "UserTweets" in url and response.status == 200:
                api_data["tweets"] = response.json()
        except Exception:
            pass

    profile: Optional[TwitterProfile] = None
    tweets: list[Tweet] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/136.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.on("response", _capture_response)

        try:
            page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            log.warning(f"[Twitter] Navigation timeout (may still work): {e}")

        # Wait for API responses to arrive
        page.wait_for_timeout(5000)

        # If we need more tweets and haven't hit limit, scroll to trigger more
        if fetch_tweets:
            scroll_count = 0
            max_scrolls = max(limit // 7, 2)
            while scroll_count < max_scrolls:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)
                scroll_count += 1

        # ── Parse profile from API response ──
        if "user" in api_data:
            profile = _parse_profile_api(api_data["user"], username)
        else:
            # Fallback: extract from DOM
            profile = _parse_profile_dom(page, username)

        # ── Parse tweets from API response ──
        if fetch_tweets and "tweets" in api_data:
            tweets = _parse_tweets_api(api_data["tweets"], username, limit)

        browser.close()

    if profile:
        log.info(
            f"[Twitter] Profile @{username}: "
            f"{profile.followers} followers, {profile.tweet_count} tweets"
        )
    else:
        log.warning(f"[Twitter] Could not extract profile for @{username}")

    if fetch_tweets:
        log.info(f"[Twitter] Extracted {len(tweets)} tweets for @{username}")

    return profile, tweets


def _parse_profile_api(data: dict, username: str) -> Optional[TwitterProfile]:
    """Parse profile data from the UserByScreenName GraphQL response."""
    try:
        result = data.get("data", {}).get("user", {}).get("result", {})
        legacy = result.get("legacy", {})
        if not legacy:
            return None

        # Website from entities
        website = "N/A"
        url_entity = legacy.get("entities", {}).get("url", {}).get("urls", [])
        if url_entity:
            website = url_entity[0].get("expanded_url", url_entity[0].get("url", "N/A"))

        return TwitterProfile(
            username=legacy.get("screen_name", username),
            display_name=legacy.get("name", username),
            bio=legacy.get("description", "N/A") or "N/A",
            followers=str(legacy.get("followers_count", 0)),
            following=str(legacy.get("friends_count", 0)),
            tweet_count=str(legacy.get("statuses_count", 0)),
            joined=legacy.get("created_at", "N/A"),
            location=legacy.get("location", "N/A") or "N/A",
            website=website,
            verified="Yes" if result.get("is_blue_verified") else "No",
            profile_image=legacy.get("profile_image_url_https", "N/A").replace("_normal", "_400x400"),
            banner_image=legacy.get("profile_banner_url", "N/A"),
            url=f"https://x.com/{username}",
        )
    except Exception as e:
        log.debug(f"[Twitter] Profile API parse error: {e}")
        return None


def _parse_profile_dom(page, username: str) -> Optional[TwitterProfile]:
    """Fallback: extract profile data from the rendered DOM."""
    try:
        # Display name
        name_el = page.locator("[data-testid='UserName']").first
        if name_el.count() == 0:
            return None
        name_text = name_el.inner_text(timeout=3000)
        lines = name_text.split("\n")
        display_name = lines[0].strip() if lines else username

        # Bio
        bio_el = page.locator("[data-testid='UserDescription']").first
        bio = bio_el.inner_text(timeout=2000) if bio_el.count() > 0 else "N/A"

        # Follower/following counts
        # Twitter uses /verified_followers or /followers, and /following
        followers = "0"
        following = "0"
        for link in page.locator(
            f"a[href$='/{username}/verified_followers'], "
            f"a[href$='/{username}/followers'], "
            f"a[href$='/{username}/following']"
        ).all():
            text = link.inner_text(timeout=2000)
            m = re.search(r"([\d,.]+[KMB]?)", text, re.IGNORECASE)
            if not m:
                continue
            val = m.group(1)
            if "follower" in text.lower():
                followers = val
            elif "following" in text.lower():
                following = val

        # Join date and location from profile header
        joined = "N/A"
        location = "N/A"
        website = "N/A"
        header = page.locator("[data-testid='UserProfileHeader_Items']").first
        if header.count() > 0:
            header_text = header.inner_text(timeout=2000)
            # Join date: "Joined January 2009"
            jm = re.search(r"Joined\s+(.+)", header_text)
            if jm:
                joined = jm.group(1).strip()
            # Location is usually the first line
            header_lines = [l.strip() for l in header_text.split("\n") if l.strip()]
            for hl in header_lines:
                if not hl.startswith("Joined") and not hl.startswith("Born") and "." in hl or len(hl) > 3:
                    if not hl.startswith("http"):
                        location = hl
                        break
            # Website link
            link_el = header.locator("a[href]").first
            if link_el.count() > 0:
                website = link_el.get_attribute("href") or "N/A"

        return TwitterProfile(
            username=username,
            display_name=display_name,
            bio=bio[:500] if bio else "N/A",
            followers=followers,
            following=following,
            tweet_count="N/A",
            joined=joined,
            location=location,
            website=website,
            verified="N/A",
            profile_image="N/A",
            banner_image="N/A",
            url=f"https://x.com/{username}",
        )
    except Exception as e:
        log.debug(f"[Twitter] DOM profile parse error: {e}")
        return None


def _parse_tweets_api(data: dict, username: str, limit: int) -> list[Tweet]:
    """Parse tweets from the UserTweets GraphQL response."""
    tweets: list[Tweet] = []

    try:
        instructions = (
            data.get("data", {})
            .get("user", {})
            .get("result", {})
            .get("timeline", {})
            .get("timeline", {})
            .get("instructions", [])
        )
    except Exception:
        return tweets

    for instruction in instructions:
        entries = instruction.get("entries", [])
        for entry in entries:
            if len(tweets) >= limit:
                break

            content = entry.get("content", {})
            if content.get("__typename") != "TimelineTimelineItem":
                continue

            item = content.get("itemContent", {})
            if item.get("itemType") != "TimelineTweet":
                continue

            tweet_result = item.get("tweet_results", {}).get("result", {})

            # Handle visibility-wrapped tweets
            if tweet_result.get("__typename") == "TweetWithVisibilityResults":
                tweet_result = tweet_result.get("tweet", {})

            if tweet_result.get("__typename") not in ("Tweet", None, ""):
                if tweet_result.get("__typename") == "TweetTombstone":
                    continue  # deleted/hidden tweet

            legacy = tweet_result.get("legacy", {})
            if not legacy:
                continue

            text = legacy.get("full_text", "")
            tweet_id = legacy.get("id_str", "")

            # Engagement metrics
            likes = str(legacy.get("favorite_count", 0))
            retweets_count = str(legacy.get("retweet_count", 0))
            replies_count = str(legacy.get("reply_count", 0))
            quotes = str(legacy.get("quote_count", 0))
            views = str(tweet_result.get("views", {}).get("count", "0"))
            bookmarks = str(legacy.get("bookmark_count", 0))

            # Metadata
            created_at = legacy.get("created_at", "N/A")
            is_retweet = "Yes" if "retweeted_status_result" in legacy else "No"
            is_reply = "Yes" if legacy.get("in_reply_to_status_id_str") else "No"

            # Media
            media_entities = legacy.get("extended_entities", {}).get("media", [])
            media_urls = [m.get("media_url_https", "") for m in media_entities if m.get("media_url_https")]
            has_media = "Yes" if media_urls else "No"

            # Hashtags and mentions from entities
            hashtag_entities = legacy.get("entities", {}).get("hashtags", [])
            hashtags = ", ".join(h.get("text", "") for h in hashtag_entities)

            mention_entities = legacy.get("entities", {}).get("user_mentions", [])
            mentions = ", ".join(m.get("screen_name", "") for m in mention_entities)

            tweet_url = f"https://x.com/{username}/status/{tweet_id}" if tweet_id else ""

            tweets.append(Tweet(
                username=username,
                tweet_id=tweet_id,
                text=text[:500],
                created_at=created_at,
                likes=likes,
                retweets=retweets_count,
                replies=replies_count,
                quotes=quotes,
                views=views,
                bookmarks=bookmarks,
                is_retweet=is_retweet,
                is_reply=is_reply,
                has_media=has_media,
                media_urls="; ".join(media_urls),
                hashtags=hashtags,
                mentions=mentions,
                url=tweet_url,
            ))

        if len(tweets) >= limit:
            break

    return tweets


# ── CSV Writers ───────────────────────────────────────────────────────────────

def save_profiles_csv(profiles: list[TwitterProfile], filepath: Path) -> None:
    if not profiles:
        return
    filepath.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [f.name for f in fields(TwitterProfile)]
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for p in profiles:
            writer.writerow(asdict(p))
    log.info(f"Saved {len(profiles)} profiles to '{filepath}'")


def save_tweets_csv(tweets: list[Tweet], filepath: Path) -> None:
    if not tweets:
        return
    filepath.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [f.name for f in fields(Tweet)]
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for t in tweets:
            writer.writerow(asdict(t))
    log.info(f"Saved {len(tweets)} tweets to '{filepath}'")


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape Twitter/X profiles and tweets (Playwright-based)."
    )
    parser.add_argument(
        "-u", "--user", action="append", default=[],
        help="Twitter username (without @). Repeat for multiple.",
    )
    parser.add_argument(
        "--tweets", action="store_true",
        help="Also scrape recent tweets for each user.",
    )
    parser.add_argument(
        "--limit", type=int, default=20,
        help="Maximum tweets per user (default: 20).",
    )
    parser.add_argument(
        "--headed", action="store_true",
        help="Run browser in headed (visible) mode for debugging.",
    )
    parser.add_argument(
        "-o", "--output-dir", default=OUTPUT_DIR,
        help=f"Output directory (default: {OUTPUT_DIR}).",
    )
    return parser


def main(
    users: Optional[list[str]] = None,
    fetch_tweets: bool = False,
    limit: int = 20,
    headless: bool = True,
    output_dir: str = OUTPUT_DIR,
) -> int:
    if not users:
        _safe_print("No users specified. Use --user <username>.")
        return 1

    output_path = Path(output_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    all_profiles: list[TwitterProfile] = []
    all_tweets: list[Tweet] = []

    for username in users:
        profile, tweets = scrape_user(
            username,
            fetch_tweets=fetch_tweets,
            limit=limit,
            headless=headless,
        )
        if profile:
            all_profiles.append(profile)
        all_tweets.extend(tweets)

        if len(users) > 1:
            time.sleep(random.uniform(*DELAY_BETWEEN_USERS))

    # Save
    if all_profiles:
        save_profiles_csv(all_profiles, output_path / f"twitter_profiles_{timestamp}.csv")
    if all_tweets:
        save_tweets_csv(all_tweets, output_path / f"twitter_tweets_{timestamp}.csv")

    # Summary
    _safe_print(f"\n{'=' * 70}")
    _safe_print("  Twitter/X Scraper Results")
    _safe_print(f"{'=' * 70}")
    for profile in all_profiles:
        _safe_print(f"\n  @{profile.username} ({profile.display_name})")
        _safe_print(
            f"    Followers: {profile.followers}  |  Following: {profile.following}  |  "
            f"Tweets: {profile.tweet_count}"
        )
        if profile.bio != "N/A":
            bio_safe = profile.bio[:80].encode("ascii", errors="replace").decode("ascii")
            _safe_print(f"    Bio: {bio_safe}")

    user_tweets: dict[str, list[Tweet]] = {}
    for t in all_tweets:
        user_tweets.setdefault(t.username, []).append(t)
    for uname, tweets in user_tweets.items():
        _safe_print(f"\n  @{uname}: {len(tweets)} tweets scraped")
        for t in tweets[:5]:
            text_safe = t.text[:50].encode("ascii", errors="replace").decode("ascii")
            _safe_print(
                f"    Likes: {t.likes:>8s}  RT: {t.retweets:>8s}  "
                f"Views: {t.views:>10s}  {text_safe}..."
            )

    _safe_print(f"\n  Total: {len(all_profiles)} profiles, {len(all_tweets)} tweets")
    _safe_print(f"  Output: {output_path.resolve()}")
    return 0


if __name__ == "__main__":
    args = build_parser().parse_args()
    raise SystemExit(
        main(
            users=args.user or None,
            fetch_tweets=args.tweets,
            limit=args.limit,
            headless=not args.headed,
            output_dir=args.output_dir,
        )
    )
