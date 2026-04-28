# Web Scrapper

A collection of Python scraping and downloading utilities:

- `Alibaba_Indiamart_scrapper/` scrapes product listings from IndiaMart and Alibaba using either a lightweight `requests` scraper or a full `Playwright` browser scraper with anti-bot stealth.
- `Ecommerce_Scraper/` scrapes product listings and reviews from Amazon (India & US) and Flipkart, plus a cross-platform price comparator.
- `Social_Media_Scraper/` scrapes Reddit posts/comments, YouTube channel analytics, Google Maps business listings, and Twitter/X profiles and tweets.
- `Influencer_Marketing_Scrapper/` discovers public influencer profiles across platforms such as Instagram, Facebook, TikTok, YouTube, X, and LinkedIn using market-specific keyword configs.
- `truecaller_scraper/` validates Indian phone numbers from CSV files and checks them with a Scrapy + Playwright Truecaller spider.
- `Stock_Market_Scraper/` fetches latest stock prices for complete market universes (India NSE, US Nasdaq/NYSE) from Yahoo Finance with crumb-based authentication.
- `Video_Downloader/` downloads videos from YouTube and 1000+ other sites using `yt-dlp`.

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

Copy `.env.example` to `.env` and fill in proxy or cookie values if needed. FFmpeg must be available on `PATH` for the video downloader when downloading separate audio/video streams.

## Unified Desktop App

Run the hub from the project root:

```powershell
.\venv\Scripts\python.exe scraper_hub.py
```

The hub provides one desktop window with tabs for:

- IndiaMart/Alibaba product scraping (requests or Playwright)
- Amazon/Flipkart e-commerce scraping with optional review extraction
- Cross-platform price comparison (Amazon India, Amazon US, Flipkart)
- Reddit subreddit post and comment scraping
- YouTube channel analytics and video stats
- Google Maps business listing extraction
- Twitter/X profile and tweet scraping
- Influencer discovery
- Truecaller phone validation/scraping
- Stock market price scraping
- Universal and YouTube video downloads

Each tab builds the command for the existing scraper, runs it in the right project folder, and streams logs into the app. The live log is trimmed to the last 5 000 lines to prevent excessive memory usage. Use the stop button to interrupt a running task.

The hub runs on Windows, macOS, and Linux. On Windows it uses native process groups for clean subprocess termination; on other platforms it falls back to standard POSIX signals.

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

Both product scrapers accept runtime options for the unified app or direct CLI use:

```powershell
..\venv\Scripts\python.exe scraper_playwright.py --site all --query "steel pipes" --query "copper wire" --output products_output.csv
..\venv\Scripts\python.exe scraper_requests.py --site indiamart --query "cnc router machine" --output products_output.csv
```

The requests scraper supports `--use-env-proxies` to honor `HTTP_PROXY` / `HTTPS_PROXY` environment variables. It reuses a single HTTP session across all requests for connection pooling and cookie persistence.

If no `--query` is provided, the scripts fall back to `PRODUCTS_TO_SEARCH` inside the file. Outputs are written to `products_output.csv` unless `--output` is provided.

Alibaba may show verification or CAPTCHA pages. The Playwright scraper uses `alibaba_browser_profile/` so cookies and local storage can be reused after manual verification. That folder is ignored by Git.

## Stock Market Price Scraper

Fetch latest prices for complete supported market universes instead of typing every symbol manually.

Supported all-stock universes:

- India NSE equities from the NSE equity list
- US Nasdaq-listed and other US exchange-listed securities from Nasdaq Trader symbol directories

The scraper authenticates with Yahoo Finance using a crumb token before fetching price data. If the crumb cannot be obtained, the scraper continues but some requests may return errors. All quote timestamps are stored in UTC.

Fetch all markets:

```powershell
cd Stock_Market_Scraper
..\venv\Scripts\python.exe stock_price_scraper.py --market india --output-dir output
..\venv\Scripts\python.exe stock_price_scraper.py --market us --output-dir output
..\venv\Scripts\python.exe stock_price_scraper.py --market all --output-dir output --json --zip
```

Fetch specific symbols only (does not load any market universe):

```powershell
..\venv\Scripts\python.exe stock_price_scraper.py --symbol AAPL --symbol TCS.NS --output-dir output
```

Combine a market universe with extra manual symbols:

```powershell
..\venv\Scripts\python.exe stock_price_scraper.py --market india --symbol AAPL --symbol 7203.T --output-dir output
```

Useful options:

```text
--batch-size N    Yahoo quote batch size, must be >= 1 (default: 80)
--delay SECS      Delay between batches (default: 0.4)
--limit N         Limit total symbols for testing (0 = no limit)
--json            Also write JSON output
--zip             Also create a timestamped zip archive
--no-chart-fallback  Disable per-symbol chart API fallback
--use-env-proxies    Honor HTTP(S)_PROXY environment variables
```

Main outputs:

- `stock_symbols_YYYYMMDD_HHMMSS.csv`
- `stock_prices_YYYYMMDD_HHMMSS.csv`
- `stock_market_prices_YYYYMMDD_HHMMSS.zip` (when `--zip` is used)

If a symbol source (NSE or Nasdaq Trader) is temporarily unavailable, the scraper logs a warning and continues with the remaining sources.

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

The default output directory is `./results`, matching the hub GUI default.

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

Outputs are written to timestamped folders under `Influencer_Marketing_Scrapper/output/`. A seen-profiles history file is maintained to avoid duplicate discoveries across runs.

## Video Downloaders

Universal downloader (supports 1000+ sites):

```powershell
cd Video_Downloader
..\venv\Scripts\python.exe video_downloader.py "https://example.com/video-url"
```

YouTube-focused downloader:

```powershell
cd Video_Downloader
..\venv\Scripts\python.exe youtube_downloader.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

Available quality presets: `best`, `1080p`, `720p`, `480p`, `360p`, `audio`.

```powershell
..\venv\Scripts\python.exe video_downloader.py -q audio "https://example.com/video-url"
```

For sites that require login, use `--username` and `--password`. The `--password` flag prompts securely via the terminal when given without a value:

```powershell
..\venv\Scripts\python.exe video_downloader.py --username user --password "https://example.com/video-url"
```

Use `--help` on either script to see all playlist, cookies, proxy, and output options.

## E-Commerce Scrapers (Amazon, Flipkart, Price Comparator)

### Amazon Product Scraper

Scrape Amazon India and/or US product listings:

```powershell
cd Ecommerce_Scraper
..\venv\Scripts\python.exe amazon_scraper.py --query "wireless earbuds" --region india
..\venv\Scripts\python.exe amazon_scraper.py --query "gaming laptop" --region us --output results.csv
```

With customer review scraping:

```powershell
..\venv\Scripts\python.exe amazon_scraper.py --query "smartphone" --region both --reviews --max-reviews 15
```

Key options:

```text
--region {india,us,both}  Amazon region (default: both)
--reviews                 Also scrape customer reviews
--max-pages N             Search result pages per query (default: 3)
--max-reviews N           Reviews per product (default: 10)
--use-env-proxies         Honor HTTP(S)_PROXY environment variables
```

Output files: `amazon_products.csv` (listings) and `amazon_reviews.csv` (reviews).

### Flipkart Product Scraper

```powershell
cd Ecommerce_Scraper
..\venv\Scripts\python.exe flipkart_scraper.py --query "wireless earbuds"
..\venv\Scripts\python.exe flipkart_scraper.py --query "laptop" --query "smartwatch" --max-pages 5 --output results.csv
```

Key options:

```text
--max-pages N         Search result pages per query (default: 3)
--use-env-proxies     Honor HTTP(S)_PROXY environment variables
```

### Cross-Platform Price Comparator

Compare prices across Amazon India, Amazon US, and Flipkart simultaneously:

```powershell
cd Ecommerce_Scraper
..\venv\Scripts\python.exe price_comparator.py --query "wireless earbuds"
..\venv\Scripts\python.exe price_comparator.py --query "laptop" --site amazon_india --site flipkart
..\venv\Scripts\python.exe price_comparator.py --query "phone case" --site all --max-pages 2
```

Available sites: `all`, `amazon_india`, `amazon_us`, `flipkart`.

The comparator normalises prices, detects currencies, sorts results by price, and prints a summary table highlighting the best deal across platforms.

## Social Media Scrapers

### Reddit Scraper

Scrape subreddit posts, comments, and metadata using Reddit's public JSON endpoints (no API key needed):

```powershell
cd Social_Media_Scraper
..\venv\Scripts\python.exe reddit_scraper.py --subreddit technology --sort hot --limit 25
..\venv\Scripts\python.exe reddit_scraper.py --subreddit python --subreddit programming --sort top --timeframe week
..\venv\Scripts\python.exe reddit_scraper.py --subreddit india --comments --max-comments 10 --info
```

Search across subreddits:

```powershell
..\venv\Scripts\python.exe reddit_scraper.py --subreddit python --search "web scraping" --limit 15
```

Key options:

```text
--sort {hot,new,top,rising,controversial}  Post sort order (default: hot)
--timeframe {hour,day,week,month,year,all}  For top/controversial (default: week)
--limit N             Max posts per subreddit (default: 25)
--comments            Scrape comments from top posts
--max-comments N      Max comments per post (default: 20)
--info                Fetch subreddit metadata (subscribers, etc.)
```

### YouTube Channel Analytics

Scrape channel stats and video listings using yt-dlp (already installed):

```powershell
cd Social_Media_Scraper
..\venv\Scripts\python.exe youtube_analytics.py --channel "@mkbhd" --videos --limit 20
..\venv\Scripts\python.exe youtube_analytics.py --channel "UCBcRF18a7Qf58cCRy5xuWwQ" --details
..\venv\Scripts\python.exe youtube_analytics.py --search "python tutorial" --limit 10
```

Key options:

```text
--channel HANDLE      Channel @handle, ID, or URL (repeatable)
--search QUERY        Search YouTube videos
--videos              Fetch video list for each channel
--details             Full per-video metadata (slower, more data)
--limit N             Max videos per channel/search (default: 20)
```

### Google Maps Business Scraper

Scrape business listings from Google Maps using Playwright (headless Chromium). Google Maps is fully JavaScript-rendered, so a real browser engine is required:

```powershell
cd Social_Media_Scraper
..\venv\Scripts\python.exe google_maps_scraper.py --query "restaurants" --location "Mumbai"
..\venv\Scripts\python.exe google_maps_scraper.py --query "dentist" --location "Delhi" --limit 20
..\venv\Scripts\python.exe google_maps_scraper.py --query "coffee shop" --location "New York" --headed
```

Key options:

```text
--location TEXT       City or area (appended to query)
--limit N             Max results per query (default: 20)
--headed              Show browser window (useful for debugging)
```

### Twitter/X Scraper

Scrape public Twitter/X profiles and tweets using Playwright (headless Chromium). The scraper intercepts Twitter's internal GraphQL API calls for structured data:

```powershell
cd Social_Media_Scraper
..\venv\Scripts\python.exe twitter_scraper.py --user "elonmusk" --tweets --limit 20
..\venv\Scripts\python.exe twitter_scraper.py --user "narendramodi" --user "MKBHD" --tweets
..\venv\Scripts\python.exe twitter_scraper.py --user "sundarpichai" --headed
```

Key options:

```text
--user USERNAME       Twitter username (repeatable)
--tweets              Scrape recent tweets
--limit N             Max tweets per user (default: 20)
--headed              Show browser window (useful for debugging)
```

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
