# Web Scrapper

A collection of Python scraping and downloading utilities:

- `Alibaba_Indiamart_scrapper/` scrapes product listings from IndiaMart and Alibaba.
- `Influencer_Marketing_Scrapper/` discovers public influencer profiles across platforms such as Instagram, Facebook, TikTok, YouTube, X, and LinkedIn using market-specific keyword configs.
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

## Unified Desktop App

Run the hub from the project root:

```powershell
.\venv\Scripts\python.exe scraper_hub.py
```

The hub provides one desktop window with tabs for:

- IndiaMart/Alibaba product scraping
- Influencer discovery
- Truecaller phone validation/scraping
- Stock market price scraping
- Universal and YouTube video downloads

Each tab builds the command for the existing scraper, runs it in the right project folder, and streams logs into the app. Use the stop button to interrupt a running task.

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

Both product scrapers also accept runtime options for the unified app or direct CLI use:

```powershell
..\venv\Scripts\python.exe scraper_playwright.py --site all --query "steel pipes" --query "copper wire" --output products_output.csv
..\venv\Scripts\python.exe scraper_requests.py --site indiamart --query "cnc router machine" --output products_output.csv
```

If no `--query` is provided, the scripts fall back to `PRODUCTS_TO_SEARCH` inside the file. Outputs are written to `products_output.csv` unless `--output` is provided.

Alibaba may show verification or CAPTCHA pages. The Playwright scraper uses `alibaba_browser_profile/` so cookies and local storage can be reused after manual verification. That folder is ignored by Git.

## Stock Market Price Scraper

Fetch latest prices for complete supported market universes instead of typing every symbol manually.

Supported all-stock universes:

- India NSE equities from the NSE equity list
- US Nasdaq-listed and other US exchange-listed securities from Nasdaq Trader symbol directories

Price data is fetched in batches from Yahoo Finance quote endpoints and saved with a timestamp.

```powershell
cd Stock_Market_Scraper
..\venv\Scripts\python.exe stock_price_scraper.py --market india --output-dir output
..\venv\Scripts\python.exe stock_price_scraper.py --market us --output-dir output
..\venv\Scripts\python.exe stock_price_scraper.py --market all --output-dir output --json --zip
```

Main outputs:

- `stock_symbols_YYYYMMDD_HHMMSS.csv`
- `stock_prices_YYYYMMDD_HHMMSS.csv`

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

## Influencer Marketing Scraper

Run one market from the sample config:

```powershell
cd Influencer_Marketing_Scrapper
..\venv\Scripts\python.exe run_scraper.py --config .\markets.sample.json --market india
```

Run every configured market:

```powershell
cd Influencer_Marketing_Scrapper
..\venv\Scripts\python.exe run_scraper.py --config .\markets.sample.json --all-markets
```

Optional overrides:

```powershell
..\venv\Scripts\python.exe run_scraper.py --config .\markets.sample.json --market uae --platform instagram facebook youtube --limit-per-query 15
```

Outputs are written to timestamped folders under `Influencer_Marketing_Scrapper/output/`.

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
