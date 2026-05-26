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


def fetch_market_by_condition_id(condition_id: str, timeout: float = 8.0) -> Optional[Dict[str, Any]]:
    """Универсально получает market info по condition_id.
    Работает для ЛЮБОГО типа маркета (крипто/погода/политика/спорт).

    Gamma по умолчанию фильтрует только активные маркеты. Для резолвенных
    нужно явно запросить с closed=true. Делаем двухпроходный поиск.
    """
    if not condition_id:
        return None

    def _try(extra_params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        params = {"condition_ids": condition_id, "limit": 1}
        params.update(extra_params)
        try:
            r = requests.get(f"{GAMMA_BASE}/markets", params=params, timeout=timeout)
            if r.status_code != 200:
                return None
            data = r.json()
            if isinstance(data, list) and data:
                return data[0]
            if isinstance(data, dict) and data.get("question"):
                return data
            return None
        except Exception:
            return None

    # 1. Без фильтра (по умолчанию Gamma вернёт только active маркеты)
    m = _try({})
    if m:
        return m

    # 2. Closed-only (для резолвенных)
    m = _try({"closed": "true"})
    if m:
        return m

    # 3. Archived (на всякий случай)
    m = _try({"archived": "true"})
    return m


def _market_to_outcome(market: Dict[str, Any]) -> Dict[str, Any]:
    """Парсит market info → {status, winner, prices}."""
    try:
        outs_raw = market.get("outcomes", '["?","?"]')
        outs = json.loads(outs_raw) if isinstance(outs_raw, str) else outs_raw
        pr_raw = market.get("outcomePrices", "[]")
        prices = json.loads(pr_raw) if isinstance(pr_raw, str) else (pr_raw or [])
    except Exception:
        return {"status": "parse_error"}

    if len(prices) < 2:
        return {"status": "active", "prices": prices}
    # Резолв: одна из цен = "1" (всё выплачено в эту сторону)
    if str(prices[0]) == "1":
        return {"status": "resolved", "winner": outs[0], "prices": prices}
    if str(prices[1]) == "1":
        return {"status": "resolved", "winner": outs[1], "prices": prices}
    return {"status": "active", "prices": prices}


def get_outcome(
    title: str,
    condition_id: Optional[str] = None,
    slug: Optional[str] = None,
) -> Dict[str, Any]:
    """Возвращает статус и winner для маркета.

    Стратегия (по приоритету):
      1) Если есть slug — /markets/slug/{slug} (прямой lookup, работает для
         резолвенных и активных без фильтрации)
      2) Иначе если condition_id — /markets?condition_ids=X с двухпроходной
         попыткой (default → closed=true)
      3) Иначе title-based slug (только для крипто Up/Down)

    Возможные status: resolved, active, parse_error, not_found.
    """
    # Приоритет 1: slug (надёжнее всего — прямой lookup)
    if slug:
        market = fetch_market_by_slug(slug)
        if market:
            result = _market_to_outcome(market)
            result["slug"] = slug
            return result
        # slug не нашёлся — попробуем condition_id если есть

    # Приоритет 2: condition_id
    if condition_id:
        market = fetch_market_by_condition_id(condition_id)
        if market:
            result = _market_to_outcome(market)
            result["condition_id"] = condition_id
            return result
        return {"status": "not_found", "condition_id": condition_id}

    # Приоритет 3: title parsing (для крипто Up/Down)
    parts = title_to_slug_parts(title)
    if not parts:
        return {"status": "parse_error"}

    asset_code, tf, ts = parts
    crypto_slug = build_slug(asset_code, tf, ts)
    market = fetch_market_by_slug(crypto_slug)
    if not market:
        return {"status": "not_found", "slug": crypto_slug}

    result = _market_to_outcome(market)
    result["slug"] = crypto_slug
    return result
