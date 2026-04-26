# Influencer Marketing Scrapper

This scraper is built for influencer marketing research across public social
profiles and profile-like pages. It is designed to be reusable across markets
by changing a JSON config instead of editing Python code.

Supported discovery targets:

- `instagram`
- `facebook`
- `tiktok`
- `youtube`
- `x`
- `linkedin`

Best-effort auto-discovery is strongest on:

- `youtube`
- `linkedin`
- `x`

Extraction/enrichment is supported for:

- `instagram`
- `facebook`
- `tiktok`

The scraper works in two stages:

1. Search for public profile URLs using market-specific keywords.
2. Fetch each public page and extract lightweight profile metadata.

Notes:

- It only targets publicly accessible pages.
- Some platforms expose limited public metadata without login.
- Facebook and Instagram frequently change markup and may rate-limit scraping.
- Search engines can block automated traffic. The CLI supports fallback search
  engines and query caps to reduce this.
- Use respectful delays and review each platform's terms before running at
  scale.

## Setup

From the repository root:

```powershell
cd Influencer_Marketing_Scrapper
..\venv\Scripts\python.exe run_scraper.py --config .\markets.sample.json --market india
```

By default, weak public-discovery platforms such as `instagram`, `facebook`,
and `tiktok` are skipped unless you provide `--seed-file` or explicitly pass
`--allow-weak-discovery`.

If DuckDuckGo blocks requests, try a smaller run with a fallback engine order:

```powershell
..\venv\Scripts\python.exe run_scraper.py `
  --config .\markets.sample.json `
  --market india `
  --platform instagram `
  --search-engine bing_browser bing_rss bing duckduckgo `
  --max-queries-per-platform 5 `
  --limit-per-query 5
```

`bing_browser` uses Playwright-driven Chromium to render search pages before
parsing them, which is usually more reliable than plain HTML or RSS requests.
The default engine order now skips DuckDuckGo to avoid repeated timeout-heavy
runs in environments where it is not responsive.
For YouTube, the scraper now also includes a native public search path instead
of relying only on external search engines.

## Config

The config file contains one or more markets. Each market can define:

- `countries`
- `languages`
- `niches`
- `cities`
- `platforms`
- `search_terms`

You can keep one config file for multiple markets and run a single market with
`--market`, or all markets with `--all-markets`.

## Output

Each run creates a timestamped folder inside `output/` with:

- `profiles.csv` normalized influencer rows
- `profiles.jsonl` raw structured records
- `run_summary.json` counts, timing, and settings used
- `search_debug.csv` raw discovery candidates and rejection reasons

The scraper also keeps a rolling `output/seen_profiles.csv` history by
default, so future runs can skip creators it has already processed.

## Seeded Mode

When search engines do not return reliable public profile URLs for a platform,
you can feed the scraper a seed file and let it extract profile metadata
directly.

Seed CSV example:

```csv
platform,url,title
instagram,https://www.instagram.com/examplecreator/,Example Creator
youtube,https://www.youtube.com/@examplechannel,Example Channel
```

The sample URLs are placeholders only. Replace them with real public profile
URLs before running a production scrape, otherwise some rows may return `400`
or `404` responses and be skipped.

Run with a seed file:

```powershell
..\venv\Scripts\python.exe run_scraper.py `
  --config .\markets.sample.json `
  --market india `
  --platform instagram youtube `
  --seed-file .\seed_profiles.csv
```

## Non-Repeating Runs

By default the scraper writes previously processed profile URLs to
`output/seen_profiles.csv` and skips them on later runs. It also shuffles
candidate URLs before extraction so repeated runs do not always process the
same ordering first.

To avoid wasting time on weak discovery surfaces, the scraper also stops a
platform early after 2 consecutive empty queries by default. Override that with
`--stop-after-empty-queries`.

If you still want to try direct discovery on weaker surfaces, use:

```powershell
..\venv\Scripts\python.exe run_scraper.py `
  --config .\markets.sample.json `
  --market india `
  --platform instagram `
  --allow-weak-discovery
```

## Example

```powershell
..\venv\Scripts\python.exe run_scraper.py `
  --config .\markets.sample.json `
  --market uae `
  --platform instagram facebook youtube `
  --limit-per-query 15 `
  --delay-min 1.5 `
  --delay-max 3.0
```
