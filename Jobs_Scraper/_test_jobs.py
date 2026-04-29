"""Test 2: headed mode (non-headless) + advanced stealth + alternative URLs."""
import sys, json, re
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

with sync_playwright() as pw:
    # Try NON-headless with window hidden offscreen
    browser = pw.chromium.launch(
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--window-position=-2000,-2000",  # offscreen
            "--window-size=1366,768",
        ],
    )

    # === Indeed with headed mode ===
    print("=== Indeed (headed + stealth) ===")
    ctx = browser.new_context(
        viewport={"width": 1366, "height": 768},
        locale="en-IN",
        timezone_id="Asia/Kolkata",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/136.0.0.0 Safari/537.36"
        ),
    )
    page = ctx.new_page()
    page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        delete navigator.__proto__.webdriver;
        window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){} };
        Object.defineProperty(navigator, 'plugins', { 
            get: () => [1, 2, 3, 4, 5] 
        });
        Object.defineProperty(navigator, 'languages', { 
            get: () => ['en-US', 'en', 'hi'] 
        });
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
    """)
    
    try:
        page.goto("https://in.indeed.com/jobs?q=python+developer&l=Bangalore", 
                   wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(6000)
        
        title = page.title()
        print(f"  Title: {title}")
        
        if "moment" not in title.lower():
            html = page.content()
            soup = BeautifulSoup(html, "lxml")
            cards = soup.select("div.job_seen_beacon, td.resultContent, div.cardOutline")
            titles = soup.select("h2.jobTitle a, h2.jobTitle span[title], a.jcs-JobTitle")
            print(f"  Cards: {len(cards)}, Titles: {len(titles)}")
            for t in titles[:3]:
                print(f"    - {t.get_text(strip=True)[:60]}")
        else:
            print("  Still blocked by Cloudflare")
    except Exception as e:
        print(f"  Error: {e}")
    ctx.close()
    
    # === Naukri headed mode ===
    print("\n=== Naukri (headed + stealth) ===")
    ctx2 = browser.new_context(
        viewport={"width": 1366, "height": 768},
        locale="en-IN",
        timezone_id="Asia/Kolkata",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/136.0.0.0 Safari/537.36"
        ),
    )
    page2 = ctx2.new_page()
    page2.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        delete navigator.__proto__.webdriver;
        window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){} };
    """)
    
    api_data = []
    def capture(resp):
        url = resp.url
        ct = resp.headers.get("content-type", "")
        if "json" in ct and resp.status == 200:
            try:
                data = resp.json()
                if isinstance(data, dict) and ("jobDetails" in str(data)[:500] or "noOfJobs" in str(data)[:500] or "title" in str(data)[:500]):
                    api_data.append({"url": url[:120], "data": data})
            except Exception:
                pass
    page2.on("response", capture)
    
    try:
        page2.goto("https://www.naukri.com/", wait_until="domcontentloaded", timeout=20000)
        page2.wait_for_timeout(3000)
        
        hp_title = page2.title()
        print(f"  Homepage title: {hp_title}")
        
        if "denied" not in hp_title.lower():
            page2.goto("https://www.naukri.com/python-developer-jobs-in-bangalore",
                        wait_until="domcontentloaded", timeout=20000)
            page2.wait_for_timeout(5000)
            
            search_title = page2.title()
            print(f"  Search title: {search_title}")
            
            html2 = page2.content()
            soup2 = BeautifulSoup(html2, "lxml")
            
            # Modern Naukri uses React - check for job elements
            for sel in ["div.srp-jobtuple-wrapper", "article.jobTuple", 
                         "div[class*='jobTuple']", "div[class*='cust-job']",
                         "div.styles_jlc__main", "a[class*='title']"]:
                els = soup2.select(sel)
                if els:
                    print(f"  Found with '{sel}': {len(els)}")
                    break
            
            # Check intercepted API
            print(f"  API responses captured: {len(api_data)}")
            for ad in api_data[:3]:
                print(f"    URL: {ad['url']}")
                preview = json.dumps(ad['data'], indent=2)[:400]
                print(f"    Data: {preview}")
        else:
            print("  Still blocked at homepage level")
    except Exception as e:
        print(f"  Error: {e}")
    
    ctx2.close()
    browser.close()
