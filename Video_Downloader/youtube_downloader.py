#!/usr/bin/env python3
"""
YouTube Video Downloader
------------------------
Downloads YouTube videos as .mp4 files using yt-dlp.

Features:
  - Download a single video
  - Download an entire playlist
  - Download all videos from a channel
  - Choose video quality (best, 1080p, 720p, 480p, 360p, audio-only)
  - Auto-saves metadata alongside each video

Dependencies:
  pip install yt-dlp
"""

import argparse
import sys
from pathlib import Path

try:
    import yt_dlp
except ImportError:
    print("❌ yt-dlp not found. Install it with: pip install yt-dlp")
    sys.exit(1)


# ─────────────────────────────────────────────
# Quality Presets
# ─────────────────────────────────────────────

QUALITY_FORMATS = {
    "best":    "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
    "1080p":   "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]",
    "720p":    "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]",
    "480p":    "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]",
    "360p":    "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360][ext=mp4]",
    "audio":   "bestaudio[ext=m4a]/bestaudio",
}


# ─────────────────────────────────────────────
# Progress Hook
# ─────────────────────────────────────────────

def progress_hook(d):
    if d["status"] == "downloading":
        percent = d.get("_percent_str", "?%").strip()
        speed   = d.get("_speed_str", "?").strip()
        eta     = d.get("_eta_str", "?").strip()
        print(f"\r   ⬇️  {percent}  |  Speed: {speed}  |  ETA: {eta}   ", end="", flush=True)
    elif d["status"] == "finished":
        print(f"\n   ✅ Download complete → {d['filename']}")
    elif d["status"] == "error":
        print(f"\n   ❌ Error downloading: {d.get('filename', 'unknown')}")


# ─────────────────────────────────────────────
# Build yt-dlp Options
# ─────────────────────────────────────────────

def build_opts(output_dir: str, quality: str, limit: int = None) -> dict:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    fmt = QUALITY_FORMATS.get(quality, QUALITY_FORMATS["best"])
    ext = "m4a" if quality == "audio" else "mp4"

    opts = {
        "format": fmt,
        "outtmpl": str(output_dir / "%(uploader)s - %(title)s [%(id)s].%(ext)s"),
        "merge_output_format": ext,
        "progress_hooks": [progress_hook],
        "ignoreerrors": True,
        "geo_bypass": True,
        "writeinfojson": True,       # Save metadata as .info.json
        "writethumbnail": True,      # Save thumbnail
        "embedthumbnail": True,      # Embed thumbnail in mp4
        "postprocessors": [
            {
                "key": "FFmpegVideoConvertor",
                "preferedformat": ext,
            },
            {
                "key": "EmbedThumbnail",
            },
        ],
    }

    if limit:
        opts["playlistend"] = limit

    return opts


# ─────────────────────────────────────────────
# Downloader
# ─────────────────────────────────────────────

class YoutubeDownloader:

    def download(self, url: str, output_dir: str = "downloads", quality: str = "best", limit: int = None):
        """Universal download — works for single videos, playlists, and channels."""
        opts = build_opts(output_dir, quality, limit)
        print(f"\n🎬 Starting download")
        print(f"   URL     : {url}")
        print(f"   Quality : {quality}")
        print(f"   Output  : {Path(output_dir).resolve()}\n")

        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

        print(f"\n🎉 All done! Files saved to: {Path(output_dir).resolve()}")


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(
        description="YouTube Video Downloader — download .mp4 files from YouTube",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download a single video in best quality
  python youtube_downloader.py https://www.youtube.com/watch?v=dQw4w9WgXcQ

  # Download in 720p to a custom folder
  python youtube_downloader.py https://www.youtube.com/watch?v=dQw4w9WgXcQ -q 720p -o my_videos

  # Download a full playlist
  python youtube_downloader.py "https://youtube.com/playlist?list=PL..." -o playlist_downloads

  # Download top 10 videos from a channel
  python youtube_downloader.py https://www.youtube.com/@MrBeast --max 10 -o mrbeast

  # Download audio only (.m4a)
  python youtube_downloader.py https://www.youtube.com/watch?v=dQw4w9WgXcQ -q audio
        """,
    )

    parser.add_argument("url", help="YouTube video, playlist, or channel URL")
    parser.add_argument(
        "-q", "--quality",
        choices=["best", "1080p", "720p", "480p", "360p", "audio"],
        default="best",
        help="Video quality (default: best)",
    )
    parser.add_argument(
        "-o", "--output",
        default="downloads",
        help="Output folder (default: ./downloads)",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=None,
        help="Max number of videos to download (for playlists/channels)",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    downloader = YoutubeDownloader()
    downloader.download(
        url=args.url,
        output_dir=args.output,
        quality=args.quality,
        limit=args.max,
    )


if __name__ == "__main__":
    main()
