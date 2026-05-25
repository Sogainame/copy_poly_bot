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
    """Главный отчёт: ТОЛЬКО наши копии. Сколько поставил → сколько получил → PnL/ROI."""
    ours = load_jsonl(OUR_COPIES)

    if not ours:
        print("Нет наших копий. Запусти bot.py и подожди пока появятся сделки.")
        return

    by_title_ours = group_by_title(ours)

    rows = []
    for title, records in by_title_ours.items():
        our_sum = summarize_window_shares(records)

        # Пропускаем окна где мы ничего не поставили (исторический мусор)
        if our_sum["spent"] <= 0:
            continue

        outcome = gamma.get_outcome(title)

        row = {
            "title": title,
            "outcome_status": outcome.get("status"),
            "winner": outcome.get("winner"),
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

    rows.sort(key=lambda r: r["title"])
    print_report(rows)


def print_report(rows: List[Dict[str, Any]]):
    print("\n" + "=" * 92)
    print("МОИ КОПИИ — ОТЧЁТ PnL")
    print("=" * 92)
    print(
        f"{'Окно':<44} | {'Поставил':>10} | {'Победил':>8} | "
        f"{'Получил':>10} | {'PnL':>10} | ROI"
    )
    print("-" * 92)

    total_spent = 0.0
    total_got = 0.0
    resolved = 0
    active = 0
    wins = 0
    losses = 0

    for r in rows:
        short = (
            r["title"]
            .replace("Bitcoin Up or Down - ", "BTC ")
            .replace("Ethereum Up or Down - ", "ETH ")
            .replace("Solana Up or Down - ", "SOL ")
            .replace("XRP Up or Down - ", "XRP ")[:42]
        )
        o = r["ours"]
        winner = r.get("winner", "?") or "-"

        if r["outcome_status"] == "resolved":
            pnl = r["our_pnl"]
            roi = r["our_roi"]
            print(
                f"{short:<44} | ${o['spent']:>8.2f} | {winner:>8} | "
                f"${r['our_got']:>8.2f} | ${pnl:>+8.2f} | {roi:>+6.1f}%"
            )
            total_spent += o["spent"]
            total_got += r["our_got"]
            resolved += 1
            if pnl > 0:
                wins += 1
            else:
                losses += 1
        elif r["outcome_status"] == "active":
            active += 1
            print(
                f"{short:<44} | ${o['spent']:>8.2f} | {'ACTIVE':>8} | "
                f"{'—':>9} | {'—':>9} | —"
            )
        else:
            status = r["outcome_status"] or "unknown"
            print(
                f"{short:<44} | ${o['spent']:>8.2f} | {status[:8]:>8} | "
                f"{'—':>9} | {'—':>9} | —"
            )

    print("-" * 92)
    pnl_total = total_got - total_spent
    roi = (pnl_total / total_spent * 100) if total_spent > 0 else 0
    winrate = (wins / resolved * 100) if resolved > 0 else 0
    print()
    print(f"=== ИТОГО ===")
    print(f"Окон сыграно:         {resolved}  ({wins} в плюс / {losses} в минус, винрейт {winrate:.0f}%)")
    if active:
        print(f"Окон активных:        {active}  (ещё не резолвились — не считаются)")
    print(f"Поставил всего:       ${total_spent:>10,.2f}")
    print(f"Получил всего:        ${total_got:>10,.2f}")
    print(f"PnL (прибыль/убыток): ${pnl_total:>+10,.2f}")
    print(f"ROI:                  {roi:>+9.1f}%")
    print()
