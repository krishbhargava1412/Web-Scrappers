from __future__ import annotations

import json
import re
from collections.abc import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .models import PropertyListing


SITE_ROOTS = {
    "magicbricks": "https://www.magicbricks.com",
    "99acres": "https://www.99acres.com",
}


def clean_text(value: object) -> str:
    if value is None:
        return "N/A"
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or "N/A"


def parse_listing_page(
    soup: BeautifulSoup,
    site: str,
    query: str,
    location: str,
    source_url: str,
) -> list[PropertyListing]:
    listings = _parse_json_ld(soup, site, query, location, source_url)
    if listings:
        return listings
    return _parse_visible_cards(soup, site, query, location, source_url)


def _parse_json_ld(
    soup: BeautifulSoup,
    site: str,
    query: str,
    location: str,
    source_url: str,
) -> list[PropertyListing]:
    listings: list[PropertyListing] = []
    for script in soup.select("script[type='application/ld+json']"):
        raw = script.string or script.get_text()
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for item in _walk_json_ld_items(data):
            listing = _listing_from_json_ld(item, site, query, location, source_url)
            if listing and listing.title != "N/A":
                listings.append(listing)
    return listings


def _walk_json_ld_items(data: object) -> Iterable[dict]:
    if isinstance(data, list):
        for entry in data:
            yield from _walk_json_ld_items(entry)
        return
    if not isinstance(data, dict):
        return

    item_type = data.get("@type")
    if item_type in {"Apartment", "House", "Residence", "SingleFamilyResidence", "Product"}:
        yield data

    for key in ("itemListElement", "@graph"):
        values = data.get(key)
        if isinstance(values, list):
            for value in values:
                if isinstance(value, dict) and isinstance(value.get("item"), dict):
                    yield from _walk_json_ld_items(value["item"])
                else:
                    yield from _walk_json_ld_items(value)


def _listing_from_json_ld(
    item: dict,
    site: str,
    query: str,
    location: str,
    source_url: str,
) -> PropertyListing | None:
    title = clean_text(item.get("name") or item.get("headline"))
    if title == "N/A":
        return None

    address = item.get("address") if isinstance(item.get("address"), dict) else {}
    offers = item.get("offers") if isinstance(item.get("offers"), dict) else {}
    floor_size = item.get("floorSize") if isinstance(item.get("floorSize"), dict) else {}

    price = clean_text(offers.get("price"))
    currency = clean_text(offers.get("priceCurrency"))
    if price != "N/A" and currency != "N/A":
        price = f"{price} {currency}"

    area = clean_text(floor_size.get("value"))
    unit = clean_text(floor_size.get("unitText"))
    if area != "N/A" and unit != "N/A":
        area = f"{area} {unit}"

    image = item.get("image")
    if isinstance(image, list):
        image = image[0] if image else None

    city = clean_text(address.get("addressRegion") or location)
    locality = clean_text(address.get("addressLocality"))

    return PropertyListing(
        site=site,
        query=query,
        title=title,
        price=price,
        area=area,
        bhk=_extract_bhk(title, item.get("numberOfRooms")),
        locality=locality,
        city=city,
        builder=clean_text(item.get("brand") or item.get("seller")),
        property_type=clean_text(item.get("@type")),
        url=_absolute_url(site, clean_text(item.get("url"))),
        image_url=clean_text(image),
        source_url=source_url,
    )


def _parse_visible_cards(
    soup: BeautifulSoup,
    site: str,
    query: str,
    location: str,
    source_url: str,
) -> list[PropertyListing]:
    selectors = [
        "[data-testid*='property-card']",
        "[data-label*='property']",
        "article",
        ".mb-srp__card",
        ".projectTuple",
        ".srpTuple",
    ]
    cards: list[Tag] = []
    for selector in selectors:
        cards = [card for card in soup.select(selector) if isinstance(card, Tag)]
        if cards:
            break

    listings: list[PropertyListing] = []
    for card in cards:
        link = card.select_one("a[href]")
        title = clean_text(link.get_text(" ", strip=True) if link else _first_text(card, ["h2", "h3", "[class*='title']"]))
        if title == "N/A" or len(title) < 4:
            continue
        text = card.get_text(" | ", strip=True)
        locality, city = _split_location(_first_text(card, ["[class*='location']", "[class*='loc']", "[class*='address']"]), location)
        listings.append(
            PropertyListing(
                site=site,
                query=query,
                title=title,
                price=_first_regex(text, [r"(?:Rs\.?|INR|₹)\s*[\d,.]+\s*(?:Cr|Lac|Lakh|K|Thousand)?", r"[\d,.]+\s*(?:Cr|Lac|Lakh)\b"]),
                area=_first_regex(text, [r"[\d,]+\s*(?:sq\.?\s*ft|sqft|sqm|sq\.?\s*m)", r"[\d,]+\s*acre"]),
                bhk=_extract_bhk(text),
                locality=locality,
                city=city,
                builder=_first_text(card, ["[class*='builder']", "[class*='seller']", "[class*='developer']"]),
                property_type=_first_regex(text, [r"\b(?:Apartment|Flat|Villa|House|Plot|Office|Shop)\b"]),
                amenities=_first_text(card, ["[class*='amenit']", "[class*='feature']", "[class*='highlight']"]),
                url=_absolute_url(site, clean_text(link.get("href") if link else None)),
                image_url=clean_text((card.select_one("img") or {}).get("src") if card.select_one("img") else None),
                source_url=source_url,
            )
        )
    return listings


def _first_text(card: Tag, selectors: list[str]) -> str:
    for selector in selectors:
        node = card.select_one(selector)
        if node:
            text = clean_text(node.get_text(" ", strip=True))
            if text != "N/A":
                return text
    return "N/A"


def _first_regex(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return clean_text(match.group(0))
    return "N/A"


def _extract_bhk(text: object, rooms: object = None) -> str:
    if rooms not in (None, "", "N/A"):
        return clean_text(rooms)
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*BHK\b", clean_text(text), re.IGNORECASE)
    return match.group(1) if match else "N/A"


def _split_location(value: str, fallback_city: str) -> tuple[str, str]:
    if value == "N/A":
        return "N/A", clean_text(fallback_city)
    parts = [clean_text(part) for part in value.split(",") if clean_text(part) != "N/A"]
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return parts[0], clean_text(fallback_city)


def _absolute_url(site: str, url: str) -> str:
    if url == "N/A":
        return "N/A"
    return urljoin(SITE_ROOTS.get(site, ""), url)
