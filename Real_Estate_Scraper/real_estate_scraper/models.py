from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PropertyListing:
    site: str
    query: str
    title: str = "N/A"
    price: str = "N/A"
    area: str = "N/A"
    bhk: str = "N/A"
    locality: str = "N/A"
    city: str = "N/A"
    builder: str = "N/A"
    property_type: str = "N/A"
    amenities: str = "N/A"
    url: str = "N/A"
    image_url: str = "N/A"
    source_url: str = "N/A"
