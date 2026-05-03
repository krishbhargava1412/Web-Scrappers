from bs4 import BeautifulSoup

from real_estate_scraper.extractors import parse_listing_page


def test_parse_listing_page_extracts_json_ld_offer_and_address():
    html = """
    <html><head>
      <script type="application/ld+json">
      {
        "@type": "ItemList",
        "itemListElement": [{
          "@type": "ListItem",
          "item": {
            "@type": "Apartment",
            "name": "2 BHK Apartment in Andheri West",
            "url": "/property-123",
            "image": "https://img.example/home.jpg",
            "floorSize": {"value": 950, "unitText": "sq ft"},
            "numberOfRooms": 2,
            "address": {"addressLocality": "Andheri West", "addressRegion": "Mumbai"},
            "offers": {"price": 18500000, "priceCurrency": "INR"}
          }
        }]
      }
      </script>
    </head><body></body></html>
    """

    listings = parse_listing_page(
        BeautifulSoup(html, "lxml"),
        site="magicbricks",
        query="2 bhk",
        location="Mumbai",
        source_url="https://www.magicbricks.com/search",
    )

    assert len(listings) == 1
    listing = listings[0]
    assert listing.title == "2 BHK Apartment in Andheri West"
    assert listing.price == "18500000 INR"
    assert listing.area == "950 sq ft"
    assert listing.bhk == "2"
    assert listing.locality == "Andheri West"
    assert listing.city == "Mumbai"
    assert listing.url == "https://www.magicbricks.com/property-123"
    assert listing.image_url == "https://img.example/home.jpg"


def test_parse_listing_page_falls_back_to_visible_cards():
    html = """
    <article data-testid="property-card">
      <a href="https://www.99acres.com/listing-456">Ready 3 BHK Villa</a>
      <div class="price">Rs. 2.4 Cr</div>
      <div class="area">1,800 sqft</div>
      <div class="location">Whitefield, Bengaluru</div>
      <div class="builder">Sunrise Developers</div>
      <div class="amenities">Pool, Gym, Parking</div>
    </article>
    """

    listings = parse_listing_page(
        BeautifulSoup(html, "lxml"),
        site="99acres",
        query="villa",
        location="Bengaluru",
        source_url="https://www.99acres.com/search",
    )

    assert len(listings) == 1
    listing = listings[0]
    assert listing.title == "Ready 3 BHK Villa"
    assert listing.price == "Rs. 2.4 Cr"
    assert listing.area == "1,800 sqft"
    assert listing.bhk == "3"
    assert listing.locality == "Whitefield"
    assert listing.city == "Bengaluru"
    assert listing.builder == "Sunrise Developers"
    assert listing.amenities == "Pool, Gym, Parking"
