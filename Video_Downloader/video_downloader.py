#!/usr/bin/env python3
"""
Universal Web Video Downloader
-------------------------------
Download videos from 1000+ websites including:
  YouTube, Instagram, Twitter/X, Facebook, TikTok, Vimeo,
  Dailymotion, Reddit, Twitch, LinkedIn, Pinterest, and many more.

Dependencies:
  pip install yt-dlp requests colorama
  Also install FFmpeg: https://ffmpeg.org/download.html
"""

import sys
import os
import argparse
import importlib.util
import shutil
from pathlib import Path
from datetime import datetime

try:
    import yt_dlp
except ImportError:
    print("❌  yt-dlp not found. Run: pip install yt-dlp")
    sys.exit(1)

try:
    from colorama import Fore, Style, init
    init(autoreset=True)
    OK    = Fore.GREEN  + "✅"
    ERR   = Fore.RED    + "❌"
    INFO  = Fore.CYAN   + "ℹ️ "
    WARN  = Fore.YELLOW + "⚠️ "
    RESET = Style.RESET_ALL
except ImportError:
    OK = "✅"; ERR = "❌"; INFO = "ℹ️ "; WARN = "⚠️ "; RESET = ""


# ─────────────────────────────────────────────────────────────
# Supported Sites (sample — yt-dlp supports 1000+ in total)
# ─────────────────────────────────────────────────────────────

SUPPORTED_SITES = [
    "youtube.com / youtu.be",
    "instagram.com",
    "twitter.com / x.com",
    "facebook.com",
    "tiktok.com",
    "vimeo.com",
    "dailymotion.com",
    "reddit.com",
    "twitch.tv",
    "linkedin.com",
    "pinterest.com",
    "bilibili.com",
    "rumble.com",
    "odysee.com",
    "bitchute.com",
    "streamable.com",
    "imgur.com",
    "ted.com",
    "bbc.co.uk",
    "cnn.com",
    "nytimes.com",
    "espn.com",
    "... and 1000+ more",
]

QUALITY_FORMATS = {
    "best":   "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
    "1080p":  "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]",
    "720p":   "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]",
    "480p":   "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]",
    "360p":   "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]",
    "audio":  "bestaudio/best",
}


def has_impersonation_support() -> bool:
    """Return True when yt-dlp can use browser impersonation dependencies."""
    return importlib.util.find_spec("curl_cffi") is not None


def print_impersonation_help():
    print(f"{WARN}  Browser impersonation support is not installed.")
    print("   Some sites, including Dailymotion, may require it to avoid blocked media requests.")
    print('   Install it in the same Python environment used for this script:')
    print('   python -m pip install -U "yt-dlp[default,curl-cffi]"')
    print()


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def has_js_runtime() -> bool:
    return shutil.which("deno") is not None or shutil.which("node") is not None


def print_ffmpeg_help():
    print(f"{WARN}  FFmpeg is not installed or is not on PATH.")
    print("   YouTube often downloads video and audio separately, so FFmpeg is required to merge them.")
    print("   Install it, then close and reopen PowerShell:")
    print("   winget install Gyan.FFmpeg")
    print()


def print_js_runtime_help():
    print(f"{WARN}  No JavaScript runtime found on PATH.")
    print("   YouTube extraction may miss some formats without Deno or Node.js.")
    print("   Optional install:")
    print("   winget install DenoLand.Deno")
    print()


# ─────────────────────────────────────────────────────────────
# Progress Hook
# ─────────────────────────────────────────────────────────────

def make_progress_hook(show_progress: bool):
    def hook(d):
        if not show_progress:
            return
        if d["status"] == "downloading":
            pct   = d.get("_percent_str", "?").strip()
            speed = d.get("_speed_str",   "?").strip()
            eta   = d.get("_eta_str",     "?").strip()
            size  = d.get("_total_bytes_str", d.get("_total_bytes_estimate_str", "?")).strip()
            print(f"\r   ⬇️  {pct:>6}  |  {speed:>12}  |  ETA {eta:>6}  |  Size {size}   ",
                  end="", flush=True)
        elif d["status"] == "finished":
            fname = Path(d["filename"]).name
            print(f"\n{OK}  Saved → {fname}{RESET}")
        elif d["status"] == "error":
            print(f"\n{ERR}  Failed → {d.get('filename','unknown')}{RESET}")
    return hook


# ─────────────────────────────────────────────────────────────
# Build yt-dlp Options
# ─────────────────────────────────────────────────────────────

def build_opts(
    output_dir: str,
    quality: str,
    audio_only: bool,
    subtitles: bool,
    limit: int,
    cookies_file: str,
    proxy: str,
    no_progress: bool,
    username: str,
    password: str,
) -> dict:

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    fmt = QUALITY_FORMATS.get(quality, QUALITY_FORMATS["best"])
    if audio_only:
        fmt = QUALITY_FORMATS["audio"]

    # Output filename template
    outtmpl = str(output_dir / "%(extractor_key)s - %(title).80s [%(id)s].%(ext)s")

    opts = {
        "format":               fmt,
        "outtmpl":              outtmpl,
        "merge_output_format":  "mp4" if not audio_only else "mp3",
        "progress_hooks":       [make_progress_hook(not no_progress)],
        "ignoreerrors":         False,
        "geo_bypass":           True,
        "nocheckcertificate":   True,
        "retries":              5,
        "fragment_retries":     5,
        "concurrent_fragment_downloads": 4,
        "writeinfojson":        False,
        "writethumbnail":       False,
        "quiet":                no_progress,
        "no_warnings":          no_progress,
    }

    # Subtitles
    if subtitles:
        opts.update({
            "writesubtitles":    True,
            "writeautomaticsub": True,
            "subtitleslangs":    ["en"],
        })

    # Playlist / channel limit
    if limit:
        opts["playlistend"] = limit

    # Cookies (for age-restricted or login-required videos)
    if cookies_file and Path(cookies_file).exists():
        opts["cookiefile"] = cookies_file

    # Proxy
    if proxy:
        opts["proxy"] = proxy

    # Authentication (for sites that require login)
    if username and password:
        opts["username"] = username
        opts["password"] = password

    # Postprocessors
    postprocessors = []
    if audio_only:
        postprocessors.append({
            "key":            "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        })
    else:
        postprocessors.append({
            "key":             "FFmpegVideoConvertor",
            "preferedformat":  "mp4",
        })

    opts["postprocessors"] = postprocessors
    return opts


# ─────────────────────────────────────────────────────────────
# Core Downloader
# ─────────────────────────────────────────────────────────────

class UniversalDownloader:

    def print_banner(self):
        print(f"""
{Fore.CYAN if 'Fore' in dir() else ''}
╔══════════════════════════════════════════════════╗
║       🌐  Universal Web Video Downloader         ║
║          Powered by yt-dlp — 1000+ sites         ║
╚══════════════════════════════════════════════════╝
{RESET}""")

    def list_sites(self):
        print(f"\n{INFO}  Commonly supported sites:{RESET}\n")
        for site in SUPPORTED_SITES:
            print(f"   • {site}")
        print(f"\n   Full list: https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md\n")

    def get_info(self, url: str) -> dict | None:
        """Fetch video info without downloading."""
        opts = {"quiet": True, "skip_download": True, "ignoreerrors": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    def print_info(self, url: str):
        """Print available formats and metadata for a URL."""
        print(f"\n{INFO}  Fetching info for: {url}{RESET}\n")
        opts = {"quiet": False, "skip_download": True, "listformats": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if info:
            print(f"\n   Title    : {info.get('title','N/A')}")
            print(f"   Site     : {info.get('extractor_key','N/A')}")
            print(f"   Duration : {info.get('duration','N/A')}s")
            print(f"   Views    : {info.get('view_count','N/A')}")

    def download(
        self,
        urls: list[str],
        output_dir: str   = "downloads",
        quality: str      = "best",
        audio_only: bool  = False,
        subtitles: bool   = False,
        limit: int        = None,
        cookies_file: str = None,
        proxy: str        = None,
        no_progress: bool = False,
        username: str     = None,
        password: str     = None,
    ):
        self.print_banner()

        opts = build_opts(
            output_dir=output_dir,
            quality=quality,
            audio_only=audio_only,
            subtitles=subtitles,
            limit=limit,
            cookies_file=cookies_file,
            proxy=proxy,
            no_progress=no_progress,
            username=username,
            password=password,
        )

        out_path = Path(output_dir).resolve()
        mode = "MP3 (audio)" if audio_only else f"MP4 ({quality})"

        print(f"  URLs     : {len(urls)}")
        print(f"  Quality  : {mode}")
        print(f"  Output   : {out_path}")
        if subtitles:
            print(f"  Subtitles: English")
        if limit:
            print(f"  Limit    : {limit} videos per playlist/channel")
        print()

        if not has_impersonation_support():
            print_impersonation_help()
        if not audio_only and not has_ffmpeg():
            print_ffmpeg_help()
        if not has_js_runtime():
            print_js_runtime_help()

        start = datetime.now()

        failures = []
        with yt_dlp.YoutubeDL(opts) as ydl:
            for url in urls:
                try:
                    result = ydl.download([url])
                    if result:
                        failures.append((url, f"yt-dlp returned error code {result}"))
                except Exception as exc:
                    failures.append((url, str(exc)))

        elapsed = (datetime.now() - start).seconds
        completed = len(urls) - len(failures)
        if failures:
            print(f"\n{WARN}  Finished with {len(failures)} failed URL(s) in {elapsed}s.")
            print(f"{OK}  Successful downloads: {completed}")
            for url, reason in failures:
                print(f"{ERR}  Failed: {url}")
                print(f"     Reason: {reason}")
            print(f"\nFiles saved to: {out_path}\n")
        else:
            print(f"\nAll done in {elapsed}s!  Files saved to: {out_path}\n")


    def download_from_file(self, filepath: str, **kwargs):
        """Read URLs from a text file (one per line) and download all."""
        path = Path(filepath)
        if not path.exists():
            print(f"{ERR}  File not found: {filepath}{RESET}")
            return
        urls = [line.strip() for line in path.read_text().splitlines()
                if line.strip() and not line.startswith("#")]
        print(f"{INFO}  Loaded {len(urls)} URLs from {filepath}{RESET}")
        self.download(urls, **kwargs)


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(
        description="🌐 Universal Web Video Downloader — 1000+ sites supported",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXAMPLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # Download a single video (any supported site)
  python video_downloader.py https://www.youtube.com/watch?v=dQw4w9WgXcQ
  python video_downloader.py https://www.tiktok.com/@user/video/123456
  python video_downloader.py https://vimeo.com/123456789
  python video_downloader.py https://www.instagram.com/reel/ABC123/
  python video_downloader.py https://twitter.com/user/status/123456

  # Download in specific quality
  python video_downloader.py <URL> -q 720p

  # Download audio only as MP3
  python video_downloader.py <URL> --audio

  # Download with subtitles
  python video_downloader.py <URL> --subtitles

  # Save to a custom folder
  python video_downloader.py <URL> -o my_videos

  # Download multiple URLs at once
  python video_downloader.py <URL1> <URL2> <URL3>

  # Download from a text file (one URL per line)
  python video_downloader.py --file urls.txt -o batch_downloads

  # Download a YouTube playlist (limit to 20 videos)
  python video_downloader.py "https://youtube.com/playlist?list=PL..." --max 20

  # Use cookies for login-required videos (export from browser)
  python video_downloader.py <URL> --cookies cookies.txt

  # Use a proxy
  python video_downloader.py <URL> --proxy socks5://127.0.0.1:1080

  # Show info and available formats without downloading
  python video_downloader.py <URL> --info

  # List all supported websites
  python video_downloader.py --list-sites
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        """,
    )

    parser.add_argument("urls", nargs="*", help="One or more video URLs")
    parser.add_argument("-q", "--quality",
                        choices=["best", "1080p", "720p", "480p", "360p"],
                        default="best",
                        help="Video quality (default: best)")
    parser.add_argument("-o", "--output",
                        default="downloads",
                        help="Output folder (default: ./downloads)")
    parser.add_argument("--audio",      action="store_true", help="Download audio only as MP3")
    parser.add_argument("--subtitles",  action="store_true", help="Download English subtitles")
    parser.add_argument("--max",        type=int, default=None,
                        help="Max videos for playlists/channels")
    parser.add_argument("--file",       metavar="FILE",
                        help="Text file with one URL per line")
    parser.add_argument("--cookies",    metavar="FILE",
                        help="Cookies file for login-required videos")
    parser.add_argument("--proxy",      metavar="URL",
                        help="Proxy URL e.g. socks5://127.0.0.1:1080")
    parser.add_argument("--username",   help="Username for sites that require login")
    parser.add_argument("--password",   help="Password for sites that require login")
    parser.add_argument("--info",       action="store_true",
                        help="Show info & available formats only (no download)")
    parser.add_argument("--list-sites", action="store_true",
                        help="List commonly supported websites")
    parser.add_argument("--no-progress", action="store_true",
                        help="Suppress progress output")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    dl = UniversalDownloader()

    if args.list_sites:
        dl.list_sites()
        return

    if not args.urls and not args.file:
        parser.print_help()
        return

    if args.info:
        for url in args.urls:
            dl.print_info(url)
        return

    kwargs = dict(
        output_dir   = args.output,
        quality      = args.quality,
        audio_only   = args.audio,
        subtitles    = args.subtitles,
        limit        = args.max,
        cookies_file = args.cookies,
        proxy        = args.proxy,
        no_progress  = args.no_progress,
        username     = args.username,
        password     = args.password,
    )

    if args.file:
        dl.download_from_file(args.file, **kwargs)
    elif args.urls:
        dl.download(args.urls, **kwargs)


if __name__ == "__main__":
    main()
