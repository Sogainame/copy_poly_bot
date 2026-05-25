"""Анализатор: PnL по окнам + сравнение трейдер vs мы."""
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Any

from . import gamma
from .storage import TRADER_TRADES, OUR_COPIES


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


def group_by_title(records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    out = defaultdict(list)
    for r in records:
        title = r.get("title", "?")
        out[title].append(r)
    return out


def summarize_window(records: List[Dict[str, Any]], usd_field: str = "usd") -> Dict[str, float]:
    """Подсчёт UP $/DOWN $/count для окна."""
    up_usd = 0.0
    down_usd = 0.0
    up_n = 0
    down_n = 0
    for r in records:
        usd = float(r.get(usd_field, 0))
        side = r.get("outcome", "")
        if side == "Up":
            up_usd += usd
            up_n += 1
        elif side == "Down":
            down_usd += usd
            down_n += 1
    return {
        "up_usd": up_usd,
        "down_usd": down_usd,
        "up_n": up_n,
        "down_n": down_n,
        "total_usd": up_usd + down_usd,
        "total_n": up_n + down_n,
    }


def summarize_window_shares(records: List[Dict[str, Any]]) -> Dict[str, float]:
    """Подсчёт UP/DOWN shares для НАШИХ копий (для расчёта PnL)."""
    up_sh = 0.0
    down_sh = 0.0
    up_usd = 0.0
    down_usd = 0.0
    for r in records:
        sh = float(r.get("my_shares", 0))
        usd = float(r.get("my_usd", 0))
        side = r.get("outcome", "")
        if side == "Up":
            up_sh += sh
            up_usd += usd
        elif side == "Down":
            down_sh += sh
            down_usd += usd
    return {"up_sh": up_sh, "down_sh": down_sh, "up_usd": up_usd, "down_usd": down_usd, "spent": up_usd + down_usd}


def compute_pnl():
    """Главный отчёт: PnL + сравнение по каждому окну."""
    trader = load_jsonl(TRADER_TRADES)
    ours = load_jsonl(OUR_COPIES)

    if not trader and not ours:
        print("Нет данных. Запусти bot.py и подожди пока появятся сделки.")
        return

    by_title_trader = group_by_title(trader)
    by_title_ours = group_by_title(ours)
    all_titles = set(by_title_trader.keys()) | set(by_title_ours.keys())

    rows = []
    for title in all_titles:
        outcome = gamma.get_outcome(title)
        trader_sum = summarize_window(by_title_trader.get(title, []))
        our_sum = summarize_window_shares(by_title_ours.get(title, []))

        row = {
            "title": title,
            "outcome_status": outcome.get("status"),
            "winner": outcome.get("winner"),
            "trader": trader_sum,
            "ours": our_sum,
        }

        if outcome.get("status") == "resolved":
            winner = outcome["winner"]
            our_got = our_sum["up_sh"] if winner == "Up" else our_sum["down_sh"]
            our_pnl = our_got - our_sum["spent"]
            row["our_got"] = our_got
            row["our_pnl"] = our_pnl
            row["our_roi"] = (our_pnl / our_sum["spent"] * 100) if our_sum["spent"] > 0 else 0
        rows.append(row)

    # Сортируем по title
    rows.sort(key=lambda r: r["title"])
    print_report(rows)


def print_report(rows: List[Dict[str, Any]]):
    print("\n" + "=" * 140)
    print("СВОДКА: ТРЕЙДЕР vs МЫ (по окнам)")
    print("=" * 140)
    print(
        f"{'Окно':<46} | {'Trader UP$':>10} | {'Trader DN$':>10} | "
        f"{'Our spent':>9} | {'Winner':>7} | {'Our got':>8} | {'Our PnL':>8} | ROI"
    )
    print("-" * 140)

    total_trader_usd = 0.0
    total_spent = 0.0
    total_got = 0.0
    resolved = 0
    active = 0

    for r in rows:
        short = r["title"].replace("Bitcoin Up or Down - ", "").replace("Ethereum Up or Down - ", "ETH ")[:44]
        t = r["trader"]
        o = r["ours"]
        winner = r.get("winner", "?") or "-"
        total_trader_usd += t["total_usd"]

        if r["outcome_status"] == "resolved":
            pnl = r["our_pnl"]
            roi = r["our_roi"]
            print(
                f"{short:<46} | ${t['up_usd']:>8.0f} | ${t['down_usd']:>8.0f} | "
                f"${o['spent']:>7.2f} | {winner:>7} | ${r['our_got']:>6.2f} | ${pnl:>+6.2f} | {roi:+6.1f}%"
            )
            total_spent += o["spent"]
            total_got += r["our_got"]
            resolved += 1
        elif r["outcome_status"] == "active":
            active += 1
            print(
                f"{short:<46} | ${t['up_usd']:>8.0f} | ${t['down_usd']:>8.0f} | "
                f"${o['spent']:>7.2f} | {'ACTIVE':>7} | -      | -      | -"
            )
        else:
            status = r["outcome_status"] or "unknown"
            print(
                f"{short:<46} | ${t['up_usd']:>8.0f} | ${t['down_usd']:>8.0f} | "
                f"${o['spent']:>7.2f} | {status[:7]:>7} | -      | -      | -"
            )

    print("-" * 140)
    pnl_total = total_got - total_spent
    roi = (pnl_total / total_spent * 100) if total_spent > 0 else 0
    print()
    print(f"=== ИТОГО ===")
    print(f"Окон резолвенных:    {resolved}")
    print(f"Окон активных:       {active}")
    print(f"Трейдер потратил:    ${total_trader_usd:,.2f}")
    print(f"Мы потратили:        ${total_spent:,.2f}  ({total_spent/total_trader_usd*100 if total_trader_usd else 0:.1f}% от трейдера)")
    print(f"Мы получили:         ${total_got:,.2f}")
    print(f"Наш PnL:             ${pnl_total:+,.2f}")
    print(f"Наш ROI:             {roi:+.1f}%")
    print()
