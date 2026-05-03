import json

from data_intelligence_scraper.extractors import (
    parse_duckduckgo_serp,
    parse_github_search,
    parse_google_serp,
    parse_rss_feed,
    parse_whois_text,
)


def test_parse_rss_feed_extracts_items():
    xml = """
    <rss version="2.0">
      <channel>
        <title>Example News</title>
        <item>
          <title>Market update</title>
          <link>https://example.com/market</link>
          <description>Stocks moved higher.</description>
          <pubDate>Fri, 01 May 2026 10:00:00 GMT</pubDate>
          <author>news@example.com</author>
        </item>
      </channel>
    </rss>
    """

    records = parse_rss_feed(xml, feed_url="https://example.com/rss.xml", limit=10)

    assert len(records) == 1
    assert records[0].source == "news"
    assert records[0].title == "Market update"
    assert records[0].url == "https://example.com/market"
    assert records[0].summary == "Stocks moved higher."
    assert records[0].published == "Fri, 01 May 2026 10:00:00 GMT"


def test_parse_github_search_extracts_repository_fields():
    payload = json.dumps(
        {
            "items": [
                {
                    "full_name": "octo/example",
                    "html_url": "https://github.com/octo/example",
                    "description": "Example repository",
                    "stargazers_count": 120,
                    "forks_count": 8,
                    "language": "Python",
                    "updated_at": "2026-05-01T00:00:00Z",
                    "owner": {"login": "octo"},
                }
            ]
        }
    )

    records = parse_github_search(payload, query="web scraper", limit=5)

    assert len(records) == 1
    assert records[0].source == "github"
    assert records[0].title == "octo/example"
    assert records[0].score == "120 stars, 8 forks"
    assert records[0].language == "Python"
    assert records[0].author == "octo"


def test_parse_google_serp_extracts_organic_results():
    html = """
    <html><body>
      <div class="g">
        <a href="https://example.com/page"><h3>Example Result</h3></a>
        <div class="VwiC3b">Short search snippet.</div>
      </div>
    </body></html>
    """

    records = parse_google_serp(html, query="example", limit=10)

    assert len(records) == 1
    assert records[0].source == "serp"
    assert records[0].title == "Example Result"
    assert records[0].url == "https://example.com/page"
    assert records[0].summary == "Short search snippet."


def test_parse_duckduckgo_serp_extracts_html_results():
    html = """
    <html><body>
      <div class="result">
        <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fhotel">Hotel Result</a>
        <a class="result__snippet">Useful hotel search snippet.</a>
      </div>
    </body></html>
    """

    records = parse_duckduckgo_serp(html, query="hotels", limit=10)

    assert len(records) == 1
    assert records[0].source == "serp"
    assert records[0].title == "Hotel Result"
    assert records[0].url == "https://example.com/hotel"
    assert records[0].summary == "Useful hotel search snippet."


def test_parse_whois_text_extracts_domain_metadata():
    text = """
    Domain Name: EXAMPLE.COM
    Registrar: Example Registrar, Inc.
    Creation Date: 1995-08-14T04:00:00Z
    Registry Expiry Date: 2026-08-13T04:00:00Z
    Name Server: A.IANA-SERVERS.NET
    Name Server: B.IANA-SERVERS.NET
    """

    record = parse_whois_text("example.com", text)

    assert record.source == "whois"
    assert record.title == "example.com"
    assert record.domain == "example.com"
    assert "Example Registrar" in record.summary
    assert "A.IANA-SERVERS.NET" in record.metadata_json
