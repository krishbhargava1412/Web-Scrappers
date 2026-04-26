from __future__ import annotations

import json
from pathlib import Path

from .models import MarketConfig


def _merged_list(primary: object, fallback: object) -> list[str]:
    if isinstance(primary, list) and primary:
        return [str(item).strip() for item in primary if str(item).strip()]
    if isinstance(fallback, list):
        return [str(item).strip() for item in fallback if str(item).strip()]
    return []


def load_market_configs(config_path: str | Path) -> dict[str, MarketConfig]:
    path = Path(config_path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    defaults = payload.get("global_defaults", {})
    markets = payload.get("markets", {})
    configs: dict[str, MarketConfig] = {}

    for market_name, market_payload in markets.items():
        configs[market_name] = MarketConfig(
            name=market_name,
            countries=_merged_list(market_payload.get("countries"), defaults.get("countries")),
            languages=_merged_list(market_payload.get("languages"), defaults.get("languages")),
            niches=_merged_list(market_payload.get("niches"), defaults.get("niches")),
            cities=_merged_list(market_payload.get("cities"), defaults.get("cities")),
            platforms=_merged_list(market_payload.get("platforms"), defaults.get("platforms")),
            search_terms=_merged_list(market_payload.get("search_terms"), defaults.get("search_terms")),
        )

    return configs
