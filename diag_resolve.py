"""Диагностика резолва: смотрим что Polymarket реально возвращает.

Берёт несколько последних сделок трейдера и для каждой:
  1) Печатает все поля сделки из Data API
  2) Если есть conditionId — дёргает Gamma /markets?condition_ids=...
  3) Печатает что Gamma вернул (closed, resolved, outcomes, outcomePrices)

Usage:
    python3 diag_resolve.py                                   # текущий target_wallet
    python3 diag_resolve.py 0x488c725253fc21c7a9ca812030dc2f6343f98c1c
"""
import json
import sys

import requests

from src.config import load_config


DATA_API = "https://data-api.polymarket.com/activity"
GAMMA_BASE = "https://gamma-api.polymarket.com"


def fetch_trades(wallet: str, limit: int = 5):
    """Берём не самые последние, а из середины (offset=100) — там скорее резолвенные старые."""
    print(f"Запрашиваю {limit} сделок трейдера {wallet[:10]}... (offset=100, чтоб попасть на резолвенные)")
    r = requests.get(
        DATA_API,
        params={"user": wallet, "type": "TRADE", "limit": limit, "offset": 100},
        timeout=15,
    )
    print(f"  HTTP {r.status_code}")
    if r.status_code != 200:
        print(f"  Body: {r.text[:300]}")
        return []
    return r.json()


def fetch_market_by_condition(cid: str):
    print(f"  Запрос: GET {GAMMA_BASE}/markets?condition_ids={cid}")
    r = requests.get(
        f"{GAMMA_BASE}/markets",
        params={"condition_ids": cid, "limit": 1},
        timeout=15,
    )
    print(f"  HTTP {r.status_code}")
    if r.status_code != 200:
        print(f"  Body: {r.text[:300]}")
        return None
    try:
        data = r.json()
    except Exception as e:
        print(f"  Ошибка JSON: {e}")
        return None
    if not data:
        print(f"  Gamma вернул пустой массив/null")
        return None
    if isinstance(data, list):
        return data[0]
    return data


def main():
    wallet = sys.argv[1] if len(sys.argv) > 1 else load_config().target_wallet

    trades = fetch_trades(wallet, limit=3)
    if not trades:
        print("Нет сделок.")
        return

    print(f"\n=== Получено {len(trades)} сделок ===\n")

    for i, t in enumerate(trades, 1):
        print(f"╔══════════════════ СДЕЛКА #{i} ══════════════════╗")
        # Все ключи которые есть в trade record
        print("Все поля сделки (Polymarket Data API):")
        for k, v in t.items():
            val = str(v)[:80]
            print(f"  {k}: {val}")
        print()

        cid = t.get("conditionId")
        if not cid:
            print("  !!! conditionId ОТСУТСТВУЕТ — fetch не возможен")
            print()
            continue

        print(f"Запрашиваю Gamma по conditionId={cid[:20]}...")
        m = fetch_market_by_condition(cid)
        if not m:
            print("  Gamma не вернул маркет\n")
            continue

        print("\nВсе поля маркета от Gamma:")
        # Только важные поля чтобы не залить
        important_keys = [
            "question", "slug", "active", "closed", "archived",
            "outcomes", "outcomePrices", "resolutionSource",
            "endDate", "closedTime", "umaResolutionStatuses",
            "marketType", "negRisk", "volume", "liquidity",
        ]
        for k in important_keys:
            if k in m:
                val = str(m[k])[:100]
                print(f"  {k}: {val}")

        # Тест моего парсера
        print("\nПарсинг моим _market_to_outcome:")
        try:
            from src.gamma import _market_to_outcome
            result = _market_to_outcome(m)
            print(f"  → {result}")
        except Exception as e:
            print(f"  ОШИБКА: {e}")

        print()


if __name__ == "__main__":
    main()
