import csv
from pathlib import Path

from data_intelligence_scraper.cli import build_parser
from data_intelligence_scraper.pipeline import (
    build_duckduckgo_search_url,
    build_github_search_url,
    build_google_search_url,
    search_serp,
    write_csv,
)
from data_intelligence_scraper.models import IntelligenceRecord


def test_build_parser_accepts_modes_and_repeatable_inputs():
    args = build_parser().parse_args(
        [
            "--mode",
            "news",
            "--feed-url",
            "https://example.com/rss.xml",
            "--feed-url",
            "https://example.com/atom.xml",
            "--limit",
            "15",
            "--serp-provider",
            "duckduckgo",
            "--serp-browser",
            "always",
            "--serp-headed",
        ]
    )

    assert args.mode == "news"
    assert args.feed_url == ["https://example.com/rss.xml", "https://example.com/atom.xml"]
    assert args.limit == 15
    assert args.serp_provider == "duckduckgo"
    assert args.serp_browser == "always"
    assert args.serp_headed is True


def test_build_google_search_url_encodes_query_and_limit():
    url = build_google_search_url("open source intelligence", 25)

    assert "google.com/search" in url
    assert "open+source+intelligence" in url
    assert "num=25" in url


def test_build_duckduckgo_search_url_encodes_query():
    url = build_duckduckgo_search_url("hotel deals")

    assert "html.duckduckgo.com/html/" in url
    assert "hotel+deals" in url


def test_search_serp_auto_falls_back_to_duckduckgo(monkeypatch):
    calls = []

    def fake_fetch_text(session, url, timeout):
        calls.append(url)
        if "google.com" in url:
            return "<html><title>blocked</title></html>"
        return """
        <div class="result">
          <a class="result__a" href="https://example.com">Example</a>
          <a class="result__snippet">Fallback snippet.</a>
        </div>
        """

    monkeypatch.setattr("data_intelligence_scraper.pipeline.fetch_text", fake_fetch_text)

    records = search_serp(
        session=object(),
        query="hotels",
        limit=10,
        provider="auto",
        browser_mode="never",
        headed=False,
        timeout=20,
    )

    assert len(records) == 1
    assert records[0].title == "Example"
    assert any("google.com" in url for url in calls)
    assert any("duckduckgo.com" in url for url in calls)


def test_search_serp_can_use_browser_when_provider_is_blocked(monkeypatch):
    monkeypatch.setattr("data_intelligence_scraper.pipeline.fetch_text", lambda session, url, timeout: "<html>blocked</html>")
    monkeypatch.setattr(
        "data_intelligence_scraper.pipeline.fetch_rendered_html",
        lambda url, timeout, headless: """
        <div class="g">
          <a href="https://example.com/browser"><h3>Browser Result</h3></a>
          <div class="VwiC3b">Rendered snippet.</div>
        </div>
        """,
    )

    records = search_serp(
        session=object(),
        query="hotels",
        limit=10,
        provider="google",
        browser_mode="always",
        headed=True,
        timeout=20,
    )

    assert len(records) == 1
    assert records[0].title == "Browser Result"


def test_build_github_search_url_includes_topic_language_and_sort():
    url = build_github_search_url("scraper", language="Python", topic="osint", limit=20)

    assert "api.github.com/search/repositories" in url
    assert "scraper+language%3APython+topic%3Aosint" in url
    assert "per_page=20" in url


def test_write_csv_creates_expected_columns():
    output = Path("Data_Intelligence_Scraper") / "output" / "test_intelligence.csv"
    record = IntelligenceRecord(source="news", query="rss", title="Headline", url="https://example.com")

    write_csv([record], output)

    rows = list(csv.DictReader(output.open(encoding="utf-8-sig")))
    assert rows[0]["source"] == "news"
    assert rows[0]["title"] == "Headline"
    assert rows[0]["url"] == "https://example.com"
