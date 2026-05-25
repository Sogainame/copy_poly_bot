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


def extract_window_info(title: str) -> dict:
    """Извлекает информацию об окне для логирования.

    Возвращает dict с ключами:
      asset:        'BTC'/'ETH'/'SOL'/'XRP'/'DOGE'/'?'
      tf:           5/15/None (минут)
      short_window: краткое имя для строки лога ('BTC 5m 7:00-7:05')
      full_window:  полное имя для заголовка ('7:00AM-7:05AM ET')
      key:          уникальный ключ окна для дедупа заголовков
    """
    asset = "?"
    if title:
        for prefix, code in ASSET_PREFIXES.items():
            if title.startswith(prefix):
                asset = code.upper()
                break

    parsed = parse_market(title)
    tf = parsed[1] if parsed else None

    m = TIME_RE.search(title or "")
    if m:
        full_window = f"{m.group(1)}:{m.group(2)}{m.group(3)}-{m.group(4)}:{m.group(5)}{m.group(6)} ET"
        short_time = f"{m.group(1)}:{m.group(2)}-{m.group(4)}:{m.group(5)}"
        short_window = f"{asset} {tf}m {short_time}" if tf else f"{asset} {short_time}"
        key = f"{asset}_{tf}m_{full_window}"
    else:
        full_window = (title or "?")[:40]
        short_window = (title or "?")[:30]
        key = title or "?"

    return {
        "asset": asset,
        "tf": tf,
        "short_window": short_window,
        "full_window": full_window,
        "key": key,
    }
