"""Анализатор: PnL по КАЖДОЙ моей сделке.

Каждая строка = одна моя ставка. Видно:
  Время сделки | Окно | BUY/SELL | Up/Down | Цена | Поставил | Резолв | Получил | PnL
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any

from . import gamma
from .config import load_config
from .filters import extract_window_info, match_keywords
from .storage import OUR_COPIES

OUTCOME_CACHE = OUR_COPIES.parent / "outcome_cache.json"


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


def load_outcome_cache() -> Dict[str, Dict[str, Any]]:
    """Кеш резолвов на диске. Резолв окна не меняется после резолва — кешируем навсегда."""
    if not OUTCOME_CACHE.exists():
        return {}
    try:
        return json.loads(OUTCOME_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_outcome_cache(cache: Dict[str, Dict[str, Any]]):
    OUTCOME_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_outcomes_with_progress(titles: List[str], cache: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Запрашивает резолвы для всех titles. Кешированные resolved пропускаются.
    Печатает прогресс чтобы было видно что работает.
    """
    to_fetch = []
    for t in titles:
        cached = cache.get(t)
        # Кешируем только resolved (active может стать resolved позже)
        if cached and cached.get("status") == "resolved":
            continue
        to_fetch.append(t)

    if not to_fetch:
        print(f"Все {len(titles)} окон уже в кеше, запросов к Polymarket не нужно.")
        return cache

    print(f"Запрашиваю резолвы {len(to_fetch)} окон из Polymarket Gamma API...")
    for i, title in enumerate(to_fetch, 1):
        cache[title] = gamma.get_outcome(title)
        # Прогресс каждые 10 запросов или на последнем
        if i % 10 == 0 or i == len(to_fetch):
            print(f"  [{i}/{len(to_fetch)}] {title[:60]}", flush=True)

    save_outcome_cache(cache)
    print(f"Готово. Резолвы сохранены в кеш ({OUTCOME_CACHE.name}).\n")
    return cache


def compute_pnl():
    """Главный отчёт: PnL по каждой нашей сделке."""
    cfg = load_config()
    ours = load_jsonl(OUR_COPIES)
    if not ours:
        print("Нет наших копий. Запусти bot.py и подожди пока появятся сделки.")
        return

    # Фильтр по filter_keywords (если пусто — берём все)
    ours = [r for r in ours if match_keywords(r.get("title", ""), cfg.filter_keywords)]
    if not ours:
        print(f"Нет копий по текущему filter_keywords={cfg.filter_keywords}.")
        return

    # Кеш резолвов на диске
    cache = load_outcome_cache()
    titles = list({r.get("title", "") for r in ours if r.get("title")})
    cache = fetch_outcomes_with_progress(titles, cache)

    rows = []
    for r in ours:
        title = r.get("title", "")
        w = extract_window_info(title)
        oc = cache.get(title, {"status": "unknown"})

        side = r.get("side") or "BUY"
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
            "window": w["short_window"],
            "asset": w["asset"],
            "tf": w["tf"],
            "side": side,
            "outcome": outcome,
            "price": my_price,
            "my_usd": my_usd,
            "my_shares": my_shares,
            "status": oc.get("status"),
            "winner": oc.get("winner"),
        }

        # PnL расчёт:
        #   BUY (resolved): купили → если выиграл — got=shares×$1, иначе got=$0
        #   SELL (любой статус): продали → got=my_usd (выручка с продажи в моменте)
        if side == "SELL":
            # SELL = получили деньги (выручка от продажи)
            row["got"] = my_usd
            row["pnl"] = my_usd      # как чистая прибыль в моменте продажи
        elif oc.get("status") == "resolved" and side == "BUY":
            winner = oc["winner"]
            if outcome == winner:
                got = my_shares * 1.0
                pnl = got - my_usd
            else:
                got = 0.0
                pnl = -my_usd
            row["got"] = got
            row["pnl"] = pnl

        rows.append(row)

    rows.sort(key=lambda r: (r.get("window", ""), r.get("time", "")))
    print_report(rows)


def print_report(rows: List[Dict[str, Any]]):
    width = 110
    print("\n" + "=" * width)
    print("МОИ СДЕЛКИ — PnL по каждой ставке")
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
            # SELL = выручка от продажи в моменте, учитывается в PnL
            got = r.get("got", r["my_usd"])
            print(
                f"{n:>5} | {r['window']:>10} | {r['time']:>8} | {side_lbl:>7} | "
                f"{r['price']:>5.3f} | {'—':>9} | {'SELL':>7} | ${got:>6.2f} | ${got:>+7.2f}"
            )
            total_got += got
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
    print(f"BUY завершено:        {total_resolved}  ({wins} в плюс / {losses} в минус, винрейт {winrate:.0f}%)")
    if pending:
        print(f"BUY ждут резолва:     {pending}")
    if sells:
        print(f"SELL (выручка):       {sells}")
    print(f"Поставил всего:       ${total_spent:>10,.2f}  (только BUY)")
    print(f"Получил всего:        ${total_got:>10,.2f}  (резолв BUY + SELL выручка)")
    print(f"PnL:                  ${pnl:>+10,.2f}")
    print(f"ROI:                  {roi:>+9.1f}%  (от Поставил)")
    print()
