import csv
from pathlib import Path

import pytest

from real_estate_scraper.cli import build_parser
from real_estate_scraper.pipeline import (
    build_search_url,
    build_search_targets,
    dedupe_listings,
    fetch_listing_html,
    write_csv,
)
from real_estate_scraper.models import PropertyListing


def test_build_parser_accepts_repeatable_queries_and_sites():
    args = build_parser().parse_args(
        [
            "--site",
            "magicbricks",
            "--query",
            "2 bhk",
            "--query",
            "villa",
            "--location",
            "Pune",
            "--max-pages",
            "2",
            "--browser",
            "always",
            "--headed",
            "--url",
            "https://www.99acres.com/search/property/buy/andheri-west?city=12&page=1",
        ]
    )

    assert args.site == ["magicbricks"]
    assert args.query == ["2 bhk", "villa"]
    assert args.location == "Pune"
    assert args.max_pages == 2
    assert args.browser == "always"
    assert args.headed is True
    assert args.url == ["https://www.99acres.com/search/property/buy/andheri-west?city=12&page=1"]


@pytest.mark.parametrize("site", ["magicbricks", "99acres"])
def test_build_search_url_contains_query_location_and_page(site):
    url = build_search_url(site, "2 bhk flat", "Mumbai", 3)

    assert "2+bhk+flat" in url
    assert "Mumbai" in url or "mumbai" in url
    assert "page=3" in url


def test_99acres_search_url_uses_location_slug_instead_of_city_name_param():
    url = build_search_url("99acres", "2 bhk flat", "Andheri West Mumbai", 1)

    assert "/search/property/buy/andheri-west-mumbai" in url
    assert "city=Andheri" not in url
    assert "keyword=2+bhk+flat" in url
    assert "res_com=R" in url


def test_build_search_targets_accepts_raw_urls():
    targets = build_search_targets(
        sites=["99acres"],
        queries=["2 bhk flat"],
        location="Mumbai",
        max_pages=2,
        urls=["https://www.99acres.com/search/property/buy/andheri-west?city=12&page=1"],
    )

    assert targets == [
        (
            "99acres",
            "direct-url",
            "https://www.99acres.com/search/property/buy/andheri-west?city=12&page=1",
        )
    ]


def test_dedupe_listings_prefers_url_then_title_location():
    first = PropertyListing(site="magicbricks", query="2 bhk", title="Flat", url="https://example.com/a")
    duplicate_url = PropertyListing(site="magicbricks", query="2 bhk", title="Flat copy", url="https://example.com/a")
    duplicate_text = PropertyListing(site="magicbricks", query="2 bhk", title="Flat", locality="Andheri", city="Mumbai")
    duplicate_text_again = PropertyListing(site="99acres", query="2 bhk", title="Flat", locality="Andheri", city="Mumbai")

    result = dedupe_listings([first, duplicate_url, duplicate_text, duplicate_text_again])

    assert result == [first, duplicate_text]


def test_99acres_auto_fetch_falls_back_to_browser_when_requests_blocked(monkeypatch):
    calls = []

    def fake_fetch_html(session, url, timeout):
        calls.append(("requests", url))
        return None

    def fake_fetch_rendered_html(url, timeout, headless):
        calls.append(("browser", url, headless))
        return "<html>rendered</html>"

    monkeypatch.setattr("real_estate_scraper.pipeline.fetch_html", fake_fetch_html)
    monkeypatch.setattr("real_estate_scraper.pipeline.fetch_rendered_html", fake_fetch_rendered_html)

    html = fetch_listing_html(
        session=object(),
        site="99acres",
        url="https://www.99acres.com/search",
        browser_mode="auto",
        headed=True,
        timeout=10,
    )

    assert html == "<html>rendered</html>"
    assert calls == [
        ("requests", "https://www.99acres.com/search"),
        ("browser", "https://www.99acres.com/search", False),
    ]


def test_magicbricks_auto_fetch_does_not_use_browser(monkeypatch):
    monkeypatch.setattr("real_estate_scraper.pipeline.fetch_html", lambda session, url, timeout: "<html>ok</html>")

    def fail_browser(*args, **kwargs):
        raise AssertionError("browser fallback should not run")

    monkeypatch.setattr("real_estate_scraper.pipeline.fetch_rendered_html", fail_browser)

    html = fetch_listing_html(
        session=object(),
        site="magicbricks",
        url="https://www.magicbricks.com/search",
        browser_mode="auto",
        headed=False,
        timeout=10,
    )

    assert html == "<html>ok</html>"


def test_write_csv_creates_expected_columns():
    output = Path("Real_Estate_Scraper") / "output" / "test_property_listings.csv"
    listing = PropertyListing(
        site="99acres",
        query="villa",
        title="Ready Villa",
        price="Rs. 2 Cr",
        city="Bengaluru",
    )

    write_csv([listing], output)

    rows = list(csv.DictReader(output.open(encoding="utf-8-sig")))
    assert rows[0]["site"] == "99acres"
    assert rows[0]["title"] == "Ready Villa"
    assert rows[0]["price"] == "Rs. 2 Cr"
