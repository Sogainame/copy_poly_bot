"""Фильтр маркетов по типу актива + таймфрейму."""
import re
from typing import Optional, Tuple, List

# Карта префиксов в title → внутренний код
ASSET_PREFIXES = {
    "Bitcoin Up or Down": "btc",
    "Ethereum Up or Down": "eth",
    "Solana Up or Down": "sol",
    "XRP Up or Down": "xrp",
    "Dogecoin Up or Down": "doge",
}

TIME_RE = re.compile(r'(\d+):(\d+)([AP]M)-(\d+):(\d+)([AP]M)')


def parse_market(title: str) -> Optional[Tuple[str, int]]:
    """Возвращает (asset_code, timeframe_minutes) или None.
    Примеры:
      'Bitcoin Up or Down - May 25, 12:30AM-12:45AM ET' -> ('btc', 15)
      'Ethereum Up or Down - May 25, 12:30AM-12:35AM ET' -> ('eth', 5)
    """
    if not title:
        return None
    asset_code = None
    for prefix, code in ASSET_PREFIXES.items():
        if title.startswith(prefix):
            asset_code = code
            break
    if not asset_code:
        return None

    m = TIME_RE.search(title)
    if not m:
        return None

    def to_min(h, mm, ampm):
        h = int(h) % 12
        if ampm == 'PM':
            h += 12
        return h * 60 + int(mm)

    start = to_min(m.group(1), m.group(2), m.group(3))
    end = to_min(m.group(4), m.group(5), m.group(6))
    diff = (end - start) % (24 * 60)
    if diff in (5, 15):
        return asset_code, diff
    return None


def match_filter(title: str, allowed: List[str]) -> bool:
    """True если маркет подходит под фильтр."""
    parsed = parse_market(title)
    if not parsed:
        return False
    asset_code, tf = parsed
    code = f"{asset_code}-{tf}m"
    return code in allowed
