# Web Scrapper

A collection of Python scraping and downloading utilities:

- `Alibaba_Indiamart_scrapper/` scrapes product listings from IndiaMart and Alibaba.
- `truecaller_scraper/` validates Indian phone numbers from CSV files and checks them with a Scrapy + Playwright Truecaller spider.
- `Video_Downloader/` downloads videos from YouTube and many other sites using `yt-dlp`.

> Note: the folder name and project files use the existing spelling, `Scrapper`, to match the current workspace.

## Requirements

- Python 3.11 or newer
- FFmpeg for video/audio merging with `yt-dlp`
- Chromium browser binaries installed by Playwright

## Setup

From the project root:

```powershell
python -m venv venv
.\venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

FFmpeg must be available on `PATH` for the video downloader when downloading separate audio/video streams.

## IndiaMart and Alibaba Scrapers

Requests-based scraper:

```powershell
cd Alibaba_Indiamart_scrapper
..\venv\Scripts\python.exe scraper_requests.py
```

Playwright scraper:

```powershell
cd Alibaba_Indiamart_scrapper
..\venv\Scripts\python.exe scraper_playwright.py
```

Edit `PRODUCTS_TO_SEARCH` inside the script to change search terms. Outputs are written to `products_output.csv`.

Alibaba may show verification or CAPTCHA pages. The Playwright scraper uses `alibaba_browser_profile/` so cookies and local storage can be reused after manual verification. That folder is ignored by Git.

## Truecaller Phone Scraper

Run local validation only:

```powershell
cd truecaller_scraper
..\venv\Scripts\python.exe run_scraper.py all_leads_phones.csv --column PhoneNumbers --output-dir ./results --local-only
```

Run validation plus scraping:

```powershell
cd truecaller_scraper
..\venv\Scripts\python.exe run_scraper.py all_leads_phones.csv --column PhoneNumbers --output-dir ./results --speed balanced
```

Speed presets:

```text
safe      lower load, fewer blocks, slowest
balanced  recommended default
fast      faster, may increase blocks or Playwright instability
```

Manual tuning example:

```powershell
..\venv\Scripts\python.exe run_scraper.py all_leads_phones.csv --column PhoneNumbers --output-dir ./results --concurrency 4 --delay 0.5 --page-wait-ms 2500 --page-pause 0.1 --retries 0 --no-autothrottle
```

Important generated files:

- `_all_for_scraping.csv` all detected phone candidates from the input CSV
- `_valid_for_scraping.csv` locally valid phone candidates
- `local_invalid.csv` locally rejected candidates
- `scraped_valid.csv` Truecaller confirmed rows
- `scraped_invalid.csv` Truecaller not-found or invalid rows
- `scraped_blocked.csv` blocked, rate-limited, or error rows
- `FINAL_REPORT.txt` final summary

## Video Downloaders

Universal downloader:

```powershell
cd Video_Downloader
..\venv\Scripts\python.exe video_downloader.py "https://example.com/video-url"
```

YouTube-focused downloader:

```powershell
cd Video_Downloader
..\venv\Scripts\python.exe youtube_downloader.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

Use `--help` on either script to see quality, playlist, cookies, and output options.

## Repository Hygiene

The `.gitignore` excludes:

- virtual environments
- Python caches
- browser profiles and Playwright cache artifacts
- downloaded media
- generated CSV/report outputs
- local environment files and logs

Keep source files, documentation, and small sample inputs in Git. Keep large result files, browser profiles, and downloaded media out of Git.

## Responsible Use

Scraping can violate site terms or trigger blocking when run too aggressively. Use reasonable delays, respect access controls, and avoid collecting or distributing personal data without a lawful basis.
