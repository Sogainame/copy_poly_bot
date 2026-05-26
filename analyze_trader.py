"""Анализ ПОСЛЕДНИХ СДЕЛОК ТРЕЙДЕРА напрямую с Polymarket Data API.

НЕ использует our_copies.jsonl. Дёргает Polymarket напрямую.
Считает PnL по реальным деньгам трейдера на основе реальных резолвов окон.

Запуск:
    python3 analyze_trader.py          # последние 500
    python3 analyze_trader.py 1000     # последние 1000
    python3 analyze_trader.py 5000     # последние 5000 (страницами)
"""
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

import requests

from src.config import load_config
from src.filters import extract_window_info
from src.analyzer import load_outcome_cache, fetch_outcomes_with_progress


DATA_API = "https://data-api.polymarket.com/activity"
PAGE_SIZE = 500   # max per page для Data API


def fetch_trader_history(wallet: str, n: int) -> list:
    """Дёргает последние N сделок трейдера через Data API. Постранично с offset."""
    all_trades = []
    offset = 0
    print(f"Загружаю сделки трейдера {wallet}...")
    while len(all_trades) < n:
        need = min(PAGE_SIZE, n - len(all_trades))
        url = f"{DATA_API}?user={wallet}&type=TRADE&limit={need}&offset={offset}"
        try:
            r = requests.get(url, timeout=15)
        except Exception as e:
            print(f"  Ошибка: {e}")
            break
        if r.status_code == 429:
            print("  Rate limit, ждём 5 сек...")
            time.sleep(5)
            continue
        if r.status_code != 200:
            print(f"  HTTP {r.status_code}, прерываю")
            break
        try:
            data = r.json()
        except Exception:
            break
        if not data:
            break
        all_trades.extend(data)
        offset += len(data)
        print(f"  [{len(all_trades)}/{n}]")
        if len(data) < need:
            break  # больше нечего загружать
        time.sleep(0.3)  # вежливо к API
    return all_trades[:n]


PRICE_BUCKETS = [
    (0.00, 0.05, "0.00-0.05 (deep lottery)"),
    (0.05, 0.15, "0.05-0.15 (lottery)"),
    (0.15, 0.30, "0.15-0.30 (cheap)"),
    (0.30, 0.50, "0.30-0.50 (mid-low)"),
    (0.50, 0.70, "0.50-0.70 (mid-high)"),
    (0.70, 0.85, "0.70-0.85 (expensive)"),
    (0.85, 0.95, "0.85-0.95 (locked-in)"),
    (0.95, 1.01, "0.95-1.00 (final)"),
]


def print_summary(label: str, rows: list, sell_count: int = 0):
    if not rows:
        print(f"{label}: нет резолвенных сделок")
        return
    spent = sum(r["spent"] for r in rows)
    got = sum(r["got"] for r in rows)
    pnl = got - spent
    roi = (pnl / spent * 100) if spent > 0 else 0
    wins = sum(1 for r in rows if r["pnl"] > 0)
    losses = sum(1 for r in rows if r["pnl"] <= 0)
    winrate = (wins / len(rows) * 100) if rows else 0
    print(f"BUY резолвилось: {len(rows)}  ({wins} в плюс / {losses} в минус, винрейт {winrate:.0f}%)")
    if sell_count:
        print(f"SELL сделок:     {sell_count}  (не учтены — закрытие позиций)")
    print(f"Поставил:        ${spent:>10,.2f}")
    print(f"Получил:         ${got:>10,.2f}")
    print(f"PnL:             ${pnl:>+10,.2f}")
    print(f"ROI:             {roi:>+9.1f}%")


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 500

    cfg = load_config()
    wallet = cfg.target_wallet

    print(f"\n{'=' * 70}")
    print(f"АНАЛИЗ ПОСЛЕДНИХ {n} СДЕЛОК ТРЕЙДЕРА (напрямую с Polymarket)")
    print(f"{'=' * 70}")

    trades = fetch_trader_history(wallet, n)
    if not trades:
        print("Сделок не получено.")
        return

    first_ts = min(int(t.get("timestamp", 0)) for t in trades if t.get("timestamp"))
    last_ts = max(int(t.get("timestamp", 0)) for t in trades if t.get("timestamp"))
    first_dt = datetime.fromtimestamp(first_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    last_dt = datetime.fromtimestamp(last_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\nПолучено сделок: {len(trades)}")
    print(f"Период: {first_dt}  →  {last_dt}")
    print(f"Длительность: {(last_ts - first_ts) / 60:.1f} минут\n")

    # Кеш резолвов
    cache = load_outcome_cache()
    items = [
        (t.get("title", ""), t.get("conditionId"))
        for t in trades if t.get("title")
    ]
    cache = fetch_outcomes_with_progress(items, cache)

    # Считаем PnL для BUY
    rows = []
    sell_count = 0
    pending = 0
    for t in trades:
        side = t.get("side") or "BUY"
        outcome = t.get("outcome", "?")
        price = float(t.get("price", 0))
        size = float(t.get("size", 0))
        title = t.get("title", "")
        oc = cache.get(title, {"status": "unknown"})
        w = extract_window_info(title)

        if side == "SELL":
            sell_count += 1
            continue
        if oc.get("status") != "resolved":
            pending += 1
            continue

        spent = size * price
        winner = oc["winner"]
        if outcome == winner:
            got = size * 1.0
            pnl = got - spent
        else:
            got = 0.0
            pnl = -spent

        rows.append({
            "price": price,
            "outcome": outcome,
            "spent": spent,
            "got": got,
            "pnl": pnl,
            "asset": w.get("asset"),
            "tf": w.get("tf"),
            "winner": winner,
        })

    if not rows:
        print(f"Ни одна BUY сделка из {len(trades)} ещё не резолвилась "
              f"({pending} ждут резолва, {sell_count} SELL). Подожди или возьми больше N.")
        return

    print("=" * 70)
    print(f"ОБЩИЙ PnL ТРЕЙДЕРА")
    print("=" * 70)
    print_summary("Все", rows, sell_count)
    if pending:
        print(f"Ждут резолва:    {pending}")
    print()

    # ===== По монете =====
    print("=" * 70)
    print("ПО МОНЕТЕ")
    print("=" * 70)
    by_asset = defaultdict(list)
    for r in rows:
        by_asset[r.get("asset") or "?"].append(r)
    print(f"{'Монета':<8} | {'Сделок':>7} | {'Spent':>10} | {'Got':>10} | {'PnL':>10} | ROI")
    print("-" * 70)
    for asset in sorted(by_asset):
        bucket = by_asset[asset]
        spent = sum(r["spent"] for r in bucket)
        got = sum(r["got"] for r in bucket)
        pnl = got - spent
        b_roi = (pnl / spent * 100) if spent > 0 else 0
        print(f"{asset:<8} | {len(bucket):>7} | ${spent:>8.2f} | ${got:>8.2f} | ${pnl:>+8.2f} | {b_roi:>+6.1f}%")
    print()

    # ===== По таймфрейму =====
    print("=" * 70)
    print("ПО ТАЙМФРЕЙМУ")
    print("=" * 70)
    by_tf = defaultdict(list)
    for r in rows:
        by_tf[r.get("tf")].append(r)
    print(f"{'ТФ':<8} | {'Сделок':>7} | {'Spent':>10} | {'Got':>10} | {'PnL':>10} | ROI")
    print("-" * 70)
    for tf in sorted(by_tf, key=lambda x: (x is None, x)):
        bucket = by_tf[tf]
        spent = sum(r["spent"] for r in bucket)
        got = sum(r["got"] for r in bucket)
        pnl = got - spent
        b_roi = (pnl / spent * 100) if spent > 0 else 0
        label = f"{tf}m" if tf else "?"
        print(f"{label:<8} | {len(bucket):>7} | ${spent:>8.2f} | ${got:>8.2f} | ${pnl:>+8.2f} | {b_roi:>+6.1f}%")
    print()

    # ===== По цене =====
    print("=" * 80)
    print("ПО ЦЕНЕ ВХОДА")
    print("=" * 80)
    print(f"{'Диапазон':<28} | {'Сделок':>7} | {'Spent':>10} | {'Got':>10} | {'PnL':>10} | ROI")
    print("-" * 80)
    for lo, hi, label in PRICE_BUCKETS:
        bucket = [r for r in rows if lo <= r["price"] < hi]
        if not bucket:
            continue
        spent = sum(r["spent"] for r in bucket)
        got = sum(r["got"] for r in bucket)
        pnl = got - spent
        b_roi = (pnl / spent * 100) if spent > 0 else 0
        wins = sum(1 for r in bucket if r["pnl"] > 0)
        winrate = wins / len(bucket) * 100
        print(f"{label:<28} | {len(bucket):>7} | ${spent:>8.2f} | ${got:>8.2f} | ${pnl:>+8.2f} | {b_roi:>+6.1f}%  (вр {winrate:.0f}%)")
    print()


if __name__ == "__main__":
    main()
