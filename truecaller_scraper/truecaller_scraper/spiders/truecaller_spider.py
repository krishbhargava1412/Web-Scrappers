"""
Truecaller Phone Number Spider
================================
Uses Scrapy + Playwright to scrape Truecaller's public phone lookup pages.

Truecaller URL format:
  https://www.truecaller.com/search/in/<10-digit-number>

Playwright is required because Truecaller is a React/JS-rendered SPA.

Usage:
    cd truecaller_scraper
    scrapy crawl truecaller \
        -a csv_file=numbers.csv \
        -a phone_column=phone \
        -a output_dir=./results
"""

import re
import asyncio
import pandas as pd
import scrapy
from truecaller_scraper.items import PhoneItem

def extract_digits(raw):
    cleaned = re.sub(r"[^\d+]", "", str(raw).strip())
    if cleaned.startswith("+91"):
        cleaned = cleaned[3:]
    elif cleaned.startswith("0091"):
        cleaned = cleaned[4:]
    elif cleaned.startswith("91") and len(cleaned) > 10:
        cleaned = cleaned[2:]
    return cleaned if cleaned.isdigit() and 10 <= len(cleaned) <= 11 else None


class TruecallerSpider(scrapy.Spider):
    name = "truecaller"
    allowed_domains = ["truecaller.com"]
    BASE_URL = "https://www.truecaller.com/search/in/{number}"

    custom_settings = {
        "DOWNLOAD_HANDLERS": {
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        },
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
        "PLAYWRIGHT_BROWSER_TYPE": "chromium",
        "PLAYWRIGHT_LAUNCH_OPTIONS": {
            "headless": True,
            "args": ["--no-sandbox", "--disable-blink-features=AutomationControlled",
                     "--disable-dev-shm-usage", "--disable-gpu"],
        },
        "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": 30000,
        "PLAYWRIGHT_MAX_CONTEXTS": 1,
        "PLAYWRIGHT_CONTEXTS": {
            "default": {
                "viewport": {"width": 1280, "height": 800},
                "user_agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/124.0.0.0 Safari/537.36"),
                "java_script_enabled": True,
                "ignore_https_errors": True,
                "locale": "en-IN",
                "timezone_id": "Asia/Kolkata",
            }
        },
        "DOWNLOAD_DELAY": 4,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "CONCURRENT_REQUESTS": 1,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 3,
        "AUTOTHROTTLE_MAX_DELAY": 20,
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 2,
        "ITEM_PIPELINES": {
            "truecaller_scraper.pipelines.PhoneValidationPipeline": 100,
            "truecaller_scraper.pipelines.CsvExportPipeline": 200,
        },
        "ROBOTSTXT_OBEY": False,
        "LOG_LEVEL": "INFO",
    }

    def __init__(self, csv_file="numbers.csv", phone_column=None,
                 output_dir="./scraper_output", page_wait_ms=8000,
                 page_pause=1.5, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.csv_file     = csv_file
        self.phone_column = phone_column
        self.output_dir   = output_dir
        self.page_wait_ms = int(float(page_wait_ms))
        self.page_pause   = float(page_pause)
        self._stats       = {"scraped": 0, "blocked": 0, "errors": 0}

    async def close_page(self, page):
        if not page:
            return
        try:
            await page.close()
        except Exception:
            pass

    def start_requests(self):
        self.logger.info(f"Loading numbers from: {self.csv_file}")
        try:
            df = pd.read_csv(self.csv_file, dtype=str)
        except Exception as e:
            self.logger.error(f"Failed to read CSV: {e}")
            return

        col = self.phone_column
        if col is None:
            candidates = [c for c in df.columns if any(kw in c.lower()
                for kw in ["phone", "mobile", "number", "contact", "cell", "tel"])]
            col = candidates[0] if candidates else df.columns[0]
            self.logger.info(f"Using phone column: '{col}'")

        self.logger.info(f"Total numbers to process: {len(df)}")

        for _, row in df.iterrows():
            raw = str(row[col]).strip()
            digits = extract_digits(raw)

            if digits is None:
                yield PhoneItem(source_row=row.get("source_row", ""),
                                candidate_index=row.get("candidate_index", ""),
                                original_cell=row.get("original_cell", ""),
                                original_number=raw, normalized_number="",
                                csv_CIN=row.get("csv_CIN", ""),
                                csv_CompanyName=row.get("csv_CompanyName", ""),
                                csv_Emails=row.get("csv_Emails", ""),
                                csv_Website=row.get("csv_Website", ""),
                                validation_status="INVALID",
                                validation_reason="Could not extract Indian digits")
                continue

            url = self.BASE_URL.format(number=digits)
            yield scrapy.Request(
                url=url,
                callback=self.parse_truecaller,
                errback=self.handle_error,
                meta={
                    "playwright": True,
                    "playwright_context": "default",
                    "playwright_include_page": True,
                    "original_number": raw,
                    "digits": digits,
                    "row_data": row.to_dict(),
                    "handle_httpstatus_list": [403, 404, 429, 503],
                },
                dont_filter=True,
            )

    async def parse_truecaller(self, response):
        page   = response.meta.get("playwright_page")
        raw    = response.meta["original_number"]
        digits = response.meta["digits"]
        row_data = response.meta.get("row_data", {})

        item = PhoneItem(
            source_row=row_data.get("source_row", ""),
            candidate_index=row_data.get("candidate_index", ""),
            original_cell=row_data.get("original_cell", ""),
            original_number=raw,
            normalized_number=digits,
            csv_CIN=row_data.get("csv_CIN", ""),
            csv_CompanyName=row_data.get("csv_CompanyName", ""),
            csv_Emails=row_data.get("csv_Emails", ""),
            csv_Website=row_data.get("csv_Website", ""),
            source_url=response.url,
        )

        if response.status in (403, 429):
            item["validation_status"] = "BLOCKED"
            item["validation_reason"] = f"HTTP {response.status} - rate limited"
            self._stats["blocked"] += 1
            await self.close_page(page)
            yield item; return

        if response.status == 404:
            item["validation_status"] = "INVALID"
            item["validation_reason"] = "Number not found on Truecaller (404)"
            await self.close_page(page)
            yield item; return

        try:
            if page:
                try:
                    await page.wait_for_load_state("networkidle", timeout=self.page_wait_ms)
                except Exception:
                    pass
                await page.evaluate("window.scrollBy(0, 400)")
                if self.page_pause > 0:
                    await asyncio.sleep(self.page_pause)
                html = await page.content()
            else:
                html = response.text

            sel = scrapy.Selector(text=html)

            name = (sel.css("h1.profile-name::text").get()
                    or sel.css("[class*='ProfileName']::text").get()
                    or sel.css("[class*='profile'] h1::text").get()
                    or sel.css("h1::text").get()
                    or sel.css("title::text").re_first(r"^(.+?)\s*[-|]")
                    or "")

            spam_score = (sel.css("[class*='spam'] [class*='label']::text").get()
                          or sel.css("[class*='Spam'] span::text").get()
                          or sel.css(".spam-score::text").get() or "")

            spam_type = (sel.css("[class*='spamType']::text").get()
                         or sel.css("[class*='spam-type']::text").get()
                         or sel.css("[class*='category']::text").get() or "")

            location = (sel.css("[class*='location']::text").get()
                        or sel.css("[class*='Location']::text").get() or "")

            carrier_name = (sel.css("[class*='carrier']::text").get()
                            or sel.css("[class*='operator']::text").get() or "")

            line_type = (sel.css("[class*='lineType']::text").get()
                         or sel.css("[class*='line-type']::text").get() or "")

            tags = [t.strip() for t in sel.css("[class*='tag']::text, [class*='Tag']::text").getall() if t.strip()]

            comments_raw = (sel.css("[class*='comment'] span::text").get()
                            or sel.css("[class*='Comment'] [class*='count']::text").get() or "")
            try: comments_count = int(re.sub(r"\D", "", comments_raw))
            except: comments_count = 0

            page_text = " ".join(sel.css("body *::text").getall()).lower()
            not_found = ["not found", "no results", "unknown number", "couldn't find", "no information"]

            if any(s in page_text for s in not_found) and not name.strip():
                item["validation_status"] = "INVALID"
                item["validation_reason"] = "Truecaller: no record found for this number"
            else:
                item["validation_status"] = "VALID"
                item["validation_reason"] = "Found on Truecaller"

            item["name"]           = name.strip()
            item["spam_score"]     = spam_score.strip()
            item["spam_type"]      = spam_type.strip()
            item["location"]       = location.strip()
            item["carrier"]        = carrier_name.strip()
            item["line_type"]      = line_type.strip()
            item["tags"]           = "; ".join(tags)
            item["comments_count"] = comments_count
            self._stats["scraped"] += 1

        except Exception as e:
            self.logger.warning(f"Parse error for {digits}: {e}")
            item["validation_status"] = "ERROR"
            item["validation_reason"] = f"Parse error: {str(e)[:120]}"
            self._stats["errors"] += 1
        finally:
            await self.close_page(page)

        yield item

    async def handle_error(self, failure):
        request = failure.request
        raw    = request.meta.get("original_number", "")
        digits = request.meta.get("digits", "")
        row_data = request.meta.get("row_data", {})
        page   = request.meta.get("playwright_page")
        self.logger.warning(f"Request failed for {digits}: {failure.getErrorMessage()}")
        await self.close_page(page)
        yield PhoneItem(source_row=row_data.get("source_row", ""),
                        candidate_index=row_data.get("candidate_index", ""),
                        original_cell=row_data.get("original_cell", ""),
                        original_number=raw, normalized_number=digits,
                        csv_CIN=row_data.get("csv_CIN", ""),
                        csv_CompanyName=row_data.get("csv_CompanyName", ""),
                        csv_Emails=row_data.get("csv_Emails", ""),
                        csv_Website=row_data.get("csv_Website", ""),
                        source_url=request.url, validation_status="ERROR",
                        validation_reason=f"Request failed: {failure.getErrorMessage()[:120]}")
        self._stats["errors"] += 1

    def closed(self, reason):
        self.logger.info(f"Spider closed ({reason}): scraped={self._stats['scraped']}, "
                         f"blocked={self._stats['blocked']}, errors={self._stats['errors']}")
