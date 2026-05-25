"""Анализатор: PnL по КАЖДОЙ моей сделке (BTC 5m).

Каждая строка = одна моя ставка. Видно:
  Время сделки | Окно | BUY/SELL | Up/Down | Цена | Поставил | Резолв | Получил | PnL
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any

from . import gamma
from .filters import extract_window_info
from .storage import OUR_COPIES


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def compute_pnl():
    """Главный отчёт: PnL по каждой нашей сделке (только BTC 5m)."""
    ours = load_jsonl(OUR_COPIES)
    if not ours:
        print("Нет наших копий. Запусти bot.py и подожди пока появятся сделки.")
        return

    # Кеш резолвов окон, чтобы не дёргать Gamma 1500 раз
    outcome_cache: Dict[str, Dict[str, Any]] = {}

    rows = []
    for r in ours:
        title = r.get("title", "")
        w = extract_window_info(title)

        # Только BTC 5m
        if w["asset"] != "BTC" or w["tf"] != 5:
            continue

        if title not in outcome_cache:
            outcome_cache[title] = gamma.get_outcome(title)
        oc = outcome_cache[title]

        side = r.get("side") or "BUY"  # default для старых записей без поля
        outcome = r.get("outcome", "?")
        my_usd = float(r.get("my_usd", 0))
        my_shares = float(r.get("my_shares", 0))
        my_price = (my_usd / my_shares) if my_shares > 0 else 0.0

        ts = r.get("parent_ts", 0)
        trade_time = (
            datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%H:%M:%S")
            if ts else "??:??:??"
        )

        row = {
            "copy_n": r.get("copy_n"),
            "time": trade_time,
            "window": w["short_window"].replace("BTC 5m ", ""),  # "9:30-9:35"
            "side": side,
            "outcome": outcome,
            "price": my_price,
            "my_usd": my_usd,
            "my_shares": my_shares,
            "status": oc.get("status"),
            "winner": oc.get("winner"),
        }

        if oc.get("status") == "resolved" and side == "BUY":
            winner = oc["winner"]
            if outcome == winner:
                got = my_shares * 1.0   # каждый share выигравшей стороны = $1
                pnl = got - my_usd
            else:
                got = 0.0
                pnl = -my_usd
            row["got"] = got
            row["pnl"] = pnl

        rows.append(row)

    # Сортировка: по окну, потом по времени
    rows.sort(key=lambda r: (r.get("window", ""), r.get("time", "")))
    print_report(rows)


def print_report(rows: List[Dict[str, Any]]):
    width = 110
    print("\n" + "=" * width)
    print("МОИ СДЕЛКИ — PnL по каждой ставке (только BTC 5m)")
    print("=" * width)
    print(
        f"{'#':>5} | {'Окно':>10} | {'Время':>8} | {'Сторона':>7} | "
        f"{'Цена':>5} | {'Поставил':>9} | {'Резолв':>7} | {'Получил':>8} | {'PnL':>9}"
    )
    print("-" * width)

    total_spent = 0.0
    total_got = 0.0
    wins = 0
    losses = 0
    pending = 0
    sells = 0

    for r in rows:
        n = r.get("copy_n") or "?"
        side_lbl = f"{r['side']} {r['outcome']}"  # "BUY Up" / "SELL Down" / etc

        if r.get("side") == "SELL":
            # SELL в DRY не считаем в PnL (нет реального инвентаря)
            print(
                f"{n:>5} | {r['window']:>10} | {r['time']:>8} | {side_lbl:>7} | "
                f"{r['price']:>5.3f} | ${r['my_usd']:>7.2f} | {'SELL':>7} | {'—':>8} | {'(не в PnL)':>9}"
            )
            sells += 1
            continue

        if r.get("status") == "resolved":
            pnl = r["pnl"]
            print(
                f"{n:>5} | {r['window']:>10} | {r['time']:>8} | {side_lbl:>7} | "
                f"{r['price']:>5.3f} | ${r['my_usd']:>7.2f} | {r['winner']:>7} | "
                f"${r['got']:>6.2f} | ${pnl:>+7.2f}"
            )
            total_spent += r["my_usd"]
            total_got += r["got"]
            if pnl > 0:
                wins += 1
            else:
                losses += 1
        elif r.get("status") == "active":
            print(
                f"{n:>5} | {r['window']:>10} | {r['time']:>8} | {side_lbl:>7} | "
                f"{r['price']:>5.3f} | ${r['my_usd']:>7.2f} | {'ACTIVE':>7} | {'—':>8} | {'—':>9}"
            )
            pending += 1
        else:
            st = (r.get("status") or "?")[:7]
            print(
                f"{n:>5} | {r['window']:>10} | {r['time']:>8} | {side_lbl:>7} | "
                f"{r['price']:>5.3f} | ${r['my_usd']:>7.2f} | {st:>7} | {'—':>8} | {'—':>9}"
            )

    print("-" * width)

    total_resolved = wins + losses
    pnl = total_got - total_spent
    roi = (pnl / total_spent * 100) if total_spent > 0 else 0
    winrate = (wins / total_resolved * 100) if total_resolved > 0 else 0

    print()
    print("=== ИТОГО ===")
    print(f"Сделок завершено:     {total_resolved}  ({wins} в плюс / {losses} в минус, винрейт {winrate:.0f}%)")
    if pending:
        print(f"Сделок ждут резолва:  {pending}")
    if sells:
        print(f"Сделок SELL:          {sells}  (в DRY не учитываются в PnL)")
    print(f"Поставил всего:       ${total_spent:>10,.2f}")
    print(f"Получил всего:        ${total_got:>10,.2f}")
    print(f"PnL:                  ${pnl:>+10,.2f}")
    print(f"ROI:                  {roi:>+9.1f}%")
    print()
