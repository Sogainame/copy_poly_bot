"""Анализ последних N копий — где утекают деньги.

Запуск:
    python3 analyze_last.py          # последние 100
    python3 analyze_last.py 500      # последние 500
    python3 analyze_last.py 1000     # последние 1000

Показывает:
  - Сводка PnL по последним N сделкам
  - Разбивка по диапазонам цены (где утечка)
  - Разбивка по сторонам (BUY Up / BUY Down — что лучше)
  - Разбивка по таймфрейму (5m / 15m)
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.analyzer import load_jsonl, load_outcome_cache, fetch_outcomes_with_progress
from src.filters import extract_window_info
from src.storage import OUR_COPIES


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


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100

    all_copies = load_jsonl(OUR_COPIES)
    if not all_copies:
        print("Нет копий. Запусти bot.py.")
        return

    # Сортируем по времени сделки трейдера (parent_ts), берём последние N
    all_copies.sort(key=lambda r: r.get("parent_ts", 0) or 0)
    last = all_copies[-n:]

    if not last:
        print(f"Меньше {n} копий в файле.")
        return

    first_ts = last[0].get("parent_ts", 0)
    last_ts = last[-1].get("parent_ts", 0)
    first_dt = datetime.fromtimestamp(int(first_ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    last_dt = datetime.fromtimestamp(int(last_ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    print(f"\nАнализ последних {len(last)} копий")
    print(f"Период: {first_dt}  →  {last_dt}")
    print(f"Длительность: {(last_ts - first_ts) / 60:.1f} минут\n")

    # Подгружаем outcome для всех окон в этой выборке (из кеша, новые запросим)
    cache = load_outcome_cache()
    titles = list({r.get("title", "") for r in last if r.get("title")})
    cache = fetch_outcomes_with_progress(titles, cache)

    # Считаем PnL по каждой сделке
    rows = []
    for r in last:
        title = r.get("title", "")
        oc = cache.get(title, {"status": "unknown"})
        side = r.get("side") or "BUY"
        outcome = r.get("outcome", "?")
        my_usd = float(r.get("my_usd", 0))
        my_shares = float(r.get("my_shares", 0))
        my_price = (my_usd / my_shares) if my_shares > 0 else 0.0
        w = extract_window_info(title)

        if oc.get("status") != "resolved" or side != "BUY":
            continue  # не считаем active / SELL

        winner = oc["winner"]
        if outcome == winner:
            got = my_shares * 1.0
            pnl = got - my_usd
        else:
            got = 0.0
            pnl = -my_usd

        rows.append({
            "price": my_price,
            "side": side,
            "outcome": outcome,
            "my_usd": my_usd,
            "got": got,
            "pnl": pnl,
            "asset": w.get("asset"),
            "tf": w.get("tf"),
            "winner": winner,
        })

    if not rows:
        print("Ни одна из последних сделок ещё не резолвилась. Подожди.")
        return

    # ====== Общая сводка ======
    print("=" * 70)
    print(f"СВОДКА ПО ПОСЛЕДНИМ {len(last)} КОПИЯМ")
    print("=" * 70)
    total_spent = sum(r["my_usd"] for r in rows)
    total_got = sum(r["got"] for r in rows)
    total_pnl = total_got - total_spent
    roi = (total_pnl / total_spent * 100) if total_spent > 0 else 0
    wins = sum(1 for r in rows if r["pnl"] > 0)
    losses = sum(1 for r in rows if r["pnl"] <= 0)
    winrate = (wins / len(rows) * 100) if rows else 0
    print(f"Сделок резолвилось:   {len(rows)}  ({wins} в плюс / {losses} в минус, винрейт {winrate:.0f}%)")
    print(f"Поставил:             ${total_spent:>10,.2f}")
    print(f"Получил:              ${total_got:>10,.2f}")
    print(f"PnL:                  ${total_pnl:>+10,.2f}")
    print(f"ROI:                  {roi:>+9.1f}%")
    print()

    # ====== Разбивка по диапазонам цены ======
    print("=" * 70)
    print("РАЗБИВКА ПО ЦЕНЕ ВХОДА (где деньги утекают / приходят)")
    print("=" * 70)
    print(f"{'Диапазон':<28} | {'Сделок':>7} | {'Spent':>9} | {'Got':>9} | {'PnL':>9} | ROI")
    print("-" * 80)
    for lo, hi, label in PRICE_BUCKETS:
        bucket = [r for r in rows if lo <= r["price"] < hi]
        if not bucket:
            continue
        spent = sum(r["my_usd"] for r in bucket)
        got = sum(r["got"] for r in bucket)
        pnl = got - spent
        b_roi = (pnl / spent * 100) if spent > 0 else 0
        b_wins = sum(1 for r in bucket if r["pnl"] > 0)
        b_winrate = (b_wins / len(bucket) * 100)
        print(
            f"{label:<28} | {len(bucket):>7} | ${spent:>7.2f} | ${got:>7.2f} | "
            f"${pnl:>+7.2f} | {b_roi:>+6.1f}%  (вр {b_winrate:.0f}%)"
        )
    print()

    # ====== Разбивка по таймфрейму ======
    print("=" * 70)
    print("РАЗБИВКА ПО ТАЙМФРЕЙМУ")
    print("=" * 70)
    print(f"{'ТФ':<10} | {'Сделок':>7} | {'Spent':>9} | {'Got':>9} | {'PnL':>9} | ROI")
    print("-" * 70)
    for tf_name in ("5", "15"):
        tf_int = int(tf_name)
        bucket = [r for r in rows if r.get("tf") == tf_int]
        if not bucket:
            continue
        spent = sum(r["my_usd"] for r in bucket)
        got = sum(r["got"] for r in bucket)
        pnl = got - spent
        b_roi = (pnl / spent * 100) if spent > 0 else 0
        print(
            f"{tf_name + 'm':<10} | {len(bucket):>7} | ${spent:>7.2f} | ${got:>7.2f} | "
            f"${pnl:>+7.2f} | {b_roi:>+6.1f}%"
        )
    print()

    # ====== Разбивка по стороне (Up/Down) ======
    print("=" * 70)
    print("РАЗБИВКА ПО СТОРОНЕ")
    print("=" * 70)
    print(f"{'Сторона':<10} | {'Сделок':>7} | {'Spent':>9} | {'Got':>9} | {'PnL':>9} | ROI")
    print("-" * 70)
    for side in ("Up", "Down"):
        bucket = [r for r in rows if r["outcome"] == side]
        if not bucket:
            continue
        spent = sum(r["my_usd"] for r in bucket)
        got = sum(r["got"] for r in bucket)
        pnl = got - spent
        b_roi = (pnl / spent * 100) if spent > 0 else 0
        print(
            f"BUY {side:<6} | {len(bucket):>7} | ${spent:>7.2f} | ${got:>7.2f} | "
            f"${pnl:>+7.2f} | {b_roi:>+6.1f}%"
        )
    print()


if __name__ == "__main__":
    main()
