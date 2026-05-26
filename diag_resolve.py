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


def fetch_trades(wallet: str, offset: int = 0, limit: int = 1):
    print(f"Запрашиваю {limit} сделок трейдера {wallet[:10]}... (offset={offset})")
    r = requests.get(
        DATA_API,
        params={"user": wallet, "type": "TRADE", "limit": limit, "offset": offset},
        timeout=15,
    )
    print(f"  HTTP {r.status_code}")
    if r.status_code != 200:
        print(f"  Body: {r.text[:300]}")
        return []
    return r.json() or []


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

    # Берём сделки с разных offset чтобы попасть и в свежие и в СТАРЫЕ
    # (старые точно резолвены — смотрим что Gamma вернёт для них)
    offsets = [0, 500, 1500, 2500]
    all_trades = []
    seen_cids = set()
    for off in offsets:
        trs = fetch_trades(wallet, offset=off, limit=3)
        for t in trs:
            cid = t.get("conditionId")
            if cid and cid not in seen_cids:
                seen_cids.add(cid)
                t["_offset"] = off
                all_trades.append(t)
                if len(all_trades) >= 6:  # хватит
                    break
        if len(all_trades) >= 6:
            break

    if not all_trades:
        print("Нет сделок.")
        return

    print(f"\n=== Получено {len(all_trades)} разных маркетов с offset'ами {offsets} ===\n")

    for i, t in enumerate(all_trades, 1):
        print(f"╔══════════════════ МАРКЕТ #{i} (offset={t['_offset']}) ══════════════════╗")
        # Только важные поля
        keys = ["timestamp", "title", "side", "outcome", "price", "size", "conditionId"]
        for k in keys:
            v = t.get(k)
            val = str(v)[:80] if v is not None else "None"
            print(f"  {k}: {val}")
        # Дата сделки → читаемо
        ts = t.get("timestamp", 0)
        if ts:
            from datetime import datetime, timezone
            dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            print(f"  trade_date: {dt}")
        print()

        cid = t.get("conditionId")
        if not cid:
            print("  !!! conditionId ОТСУТСТВУЕТ — fetch не возможен")
            print()
            continue

        m = fetch_market_by_condition(cid)
        if not m:
            print("  Gamma не вернул маркет\n")
            continue

        print("Важные поля маркета от Gamma:")
        important_keys = [
            "question", "active", "closed", "archived",
            "outcomes", "outcomePrices",
            "endDate", "closedTime", "umaResolutionStatuses",
            "negRisk", "volume",
        ]
        for k in important_keys:
            if k in m:
                val = str(m[k])[:100]
                print(f"  {k}: {val}")

        # Тест моего парсера
        from src.gamma import _market_to_outcome
        result = _market_to_outcome(m)
        print(f"\n  _market_to_outcome → {result}")
        print()


if __name__ == "__main__":
    main()
