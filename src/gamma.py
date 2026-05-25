"""Клиент Gamma API: получение информации о маркетах и резолва."""
import json
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Dict, Any

import requests

GAMMA_BASE = "https://gamma-api.polymarket.com"

MONTHS = {
    'January': 1, 'February': 2, 'March': 3, 'April': 4, 'May': 5, 'June': 6,
    'July': 7, 'August': 8, 'September': 9, 'October': 10, 'November': 11, 'December': 12
}

ASSET_PREFIX_MAP = {
    "Bitcoin": "btc",
    "Ethereum": "eth",
    "Solana": "sol",
    "XRP": "xrp",
    "Dogecoin": "doge",
}


def title_to_slug_parts(title: str, current_year: int = None) -> Optional[Tuple[str, int, int]]:
    """Парсит title в (slug_asset, timeframe_minutes, unix_ts_start_utc).
    Пример: 'Bitcoin Up or Down - May 25, 12:30AM-12:45AM ET' -> ('btc', 15, 1779683400)
    """
    if not title:
        return None

    asset_code = None
    for word, code in ASSET_PREFIX_MAP.items():
        if title.startswith(word):
            asset_code = code
            break
    if not asset_code:
        return None

    m = re.search(
        r'-\s*(\w+)\s+(\d+),\s*(\d+):(\d+)([AP]M)-(\d+):(\d+)([AP]M)\s*ET',
        title
    )
    if not m:
        return None

    mon, day, h, mm, ap, h2, mm2, ap2 = m.groups()
    month = MONTHS.get(mon)
    if not month:
        return None

    hour = int(h) % 12
    if ap == 'PM':
        hour += 12
    hour2 = int(h2) % 12
    if ap2 == 'PM':
        hour2 += 12
    diff = ((hour2 * 60 + int(mm2)) - (hour * 60 + int(mm))) % (24 * 60)
    tf = 15 if diff == 15 else (5 if diff == 5 else None)
    if not tf:
        return None

    # ET → UTC. May-Oct = EDT (UTC-4), Nov-Mar = EST (UTC-5).
    et_offset = 4 if 3 < month < 11 else 5

    # Год — текущий по умолчанию (с поправкой что бот может работать в декабре->январь)
    year = current_year or datetime.now(timezone.utc).year
    dt_utc = datetime(year, month, int(day), hour, int(mm), tzinfo=timezone.utc) + timedelta(hours=et_offset)
    ts = int(dt_utc.timestamp())

    return asset_code, tf, ts


def build_slug(asset_code: str, tf_minutes: int, ts: int) -> str:
    return f"{asset_code}-updown-{tf_minutes}m-{ts}"


def fetch_market_by_slug(slug: str, timeout: float = 8.0) -> Optional[Dict[str, Any]]:
    """Получает market info по slug. None при ошибке."""
    try:
        r = requests.get(f"{GAMMA_BASE}/markets/slug/{slug}", timeout=timeout)
        if r.status_code != 200:
            return None
        data = r.json()
        if isinstance(data, dict) and data.get("question"):
            return data
        return None
    except Exception:
        return None


def get_outcome(title: str) -> Dict[str, Any]:
    """Возвращает статус и winner для окна по title.
    Возможные status: resolved, active, parse_error, not_found.
    """
    parts = title_to_slug_parts(title)
    if not parts:
        return {"status": "parse_error"}

    asset_code, tf, ts = parts
    slug = build_slug(asset_code, tf, ts)
    market = fetch_market_by_slug(slug)
    if not market:
        return {"status": "not_found", "slug": slug}

    try:
        outs = json.loads(market.get("outcomes", '["?","?"]'))
        pr_raw = market.get("outcomePrices", "[]")
        prices = json.loads(pr_raw) if pr_raw else []
    except Exception:
        return {"status": "parse_error"}

    if len(prices) < 2:
        return {"status": "active", "prices": prices, "slug": slug}
    if prices[0] == "1":
        return {"status": "resolved", "winner": outs[0], "prices": prices, "slug": slug}
    if prices[1] == "1":
        return {"status": "resolved", "winner": outs[1], "prices": prices, "slug": slug}
    return {"status": "active", "prices": prices, "slug": slug}
