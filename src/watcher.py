"""Watcher: polling Polymarket Data API с retry на 429."""
import time
from typing import List, Dict, Any

import requests

DATA_API = "https://data-api.polymarket.com"


def fetch_trades(
    wallet: str,
    limit: int = 20,
    max_retries: int = 5,
    timeout: float = 8.0,
) -> List[Dict[str, Any]]:
    """Получает последние сделки кошелька с retry на 429/5xx."""
    url = f"{DATA_API}/activity?user={wallet}&type=TRADE&limit={limit}"

    for attempt in range(max_retries):
        try:
            r = requests.get(url, timeout=timeout)
            if r.status_code == 200:
                data = r.json()
                return data if isinstance(data, list) else []
            if r.status_code == 429:
                # Rate limit. Exponential backoff.
                wait = min(2 ** attempt, 30)
                time.sleep(wait)
                continue
            if 500 <= r.status_code < 600:
                wait = min(2 ** attempt, 15)
                time.sleep(wait)
                continue
            # 4xx (кроме 429) — не ретраим
            return []
        except requests.exceptions.RequestException:
            wait = min(2 ** attempt, 10)
            time.sleep(wait)
            continue
    return []


def trade_dedup_key(t: Dict[str, Any]) -> str:
    """Уникальный ключ сделки.
    Если есть transactionHash — используем его (надёжнее всего).
    Иначе fallback на (timestamp, asset, size, price, side).
    """
    tx = t.get("transactionHash") or t.get("transaction_hash")
    if tx:
        return f"tx:{tx}"
    return (
        f"{t.get('timestamp', 0)}_"
        f"{t.get('asset', '')}_"
        f"{t.get('size', '')}_"
        f"{t.get('price', '')}_"
        f"{t.get('side', '')}"
    )
