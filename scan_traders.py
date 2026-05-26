"""Сканер прибыльных трейдеров на Polymarket.

Использует официальный leaderboard API:
  https://data-api.polymarket.com/v1/leaderboard

Запуск:
    python3 scan_traders.py                              # топ-25 OVERALL по PnL за месяц
    python3 scan_traders.py --category POLITICS          # топ политических
    python3 scan_traders.py --category CRYPTO            # топ крипто (для нашего бота!)
    python3 scan_traders.py --period DAY                 # за сутки
    python3 scan_traders.py --period WEEK                # за неделю
    python3 scan_traders.py --period ALL                 # за всё время
    python3 scan_traders.py --order VOL                  # сортировать по обороту
    python3 scan_traders.py --limit 50                   # топ-50
    python3 scan_traders.py --all-categories             # топ-10 в каждой категории
    python3 scan_traders.py --activity                   # + последняя сделка каждого

Категории: OVERALL, POLITICS, SPORTS, CRYPTO, CULTURE, MENTIONS,
           WEATHER, ECONOMICS, TECH, FINANCE
Периоды:   DAY, WEEK, MONTH, ALL
Order:     PNL, VOL
"""
import argparse
import sys
import time
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import requests


LEADERBOARD_API = "https://data-api.polymarket.com/v1/leaderboard"
ACTIVITY_API = "https://data-api.polymarket.com/activity"

ALL_CATEGORIES = [
    "OVERALL", "POLITICS", "SPORTS", "CRYPTO", "CULTURE",
    "MENTIONS", "WEATHER", "ECONOMICS", "TECH", "FINANCE",
]
ALL_PERIODS = ["DAY", "WEEK", "MONTH", "ALL"]
ALL_ORDERS = ["PNL", "VOL"]


def fetch_leaderboard(
    category: str = "OVERALL",
    period: str = "MONTH",
    order: str = "PNL",
    limit: int = 25,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Запрашивает leaderboard через официальный API."""
    params = {
        "category": category,
        "timePeriod": period,
        "orderBy": order,
        "limit": limit,
        "offset": offset,
    }
    try:
        r = requests.get(LEADERBOARD_API, params=params, timeout=15)
    except Exception as e:
        print(f"  Ошибка сети: {e}")
        return []
    if r.status_code == 429:
        print("  Rate limit, ждём 5с...")
        time.sleep(5)
        return fetch_leaderboard(category, period, order, limit, offset)
    if r.status_code != 200:
        print(f"  HTTP {r.status_code}: {r.text[:200]}")
        return []
    try:
        return r.json() or []
    except Exception:
        return []


def fetch_last_activity(wallet: str) -> Optional[Dict[str, Any]]:
    """Получает последнюю сделку трейдера для проверки активности."""
    try:
        r = requests.get(
            ACTIVITY_API,
            params={"user": wallet, "type": "TRADE", "limit": 1},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        if not data:
            return None
        return data[0]
    except Exception:
        return None


def format_money(x: float) -> str:
    """Форматирует деньги: $12,345.67 / $1.23M / $1.23B"""
    if abs(x) >= 1_000_000_000:
        return f"${x/1_000_000_000:+.2f}B"
    if abs(x) >= 1_000_000:
        return f"${x/1_000_000:+.2f}M"
    if abs(x) >= 1_000:
        return f"${x/1_000:+.1f}K"
    return f"${x:+.2f}"


def format_age(ts: int) -> str:
    """Возвращает 'X мин/час/дней назад' от ts (unix)."""
    if not ts:
        return "?"
    delta_sec = int(time.time()) - int(ts)
    if delta_sec < 60:
        return f"{delta_sec}с"
    if delta_sec < 3600:
        return f"{delta_sec // 60}мин"
    if delta_sec < 86400:
        return f"{delta_sec // 3600}ч"
    return f"{delta_sec // 86400}д"


def print_table(
    rows: List[Dict[str, Any]],
    title: str,
    with_activity: bool = False,
):
    """Печатает таблицу трейдеров."""
    if not rows:
        print(f"\n{title}: пусто\n")
        return

    print(f"\n{'=' * 110}")
    print(f"  {title}")
    print(f"{'=' * 110}")

    hdr = f"{'#':>3} | {'Username':<28} | {'PnL':>10} | {'Volume':>10} | {'Wallet':<14}"
    if with_activity:
        hdr += f" | {'Последняя сделка':<22}"
    print(hdr)
    print("-" * 110)

    for r in rows:
        rank = str(r.get("rank", "?"))
        name = (r.get("userName") or "—")[:28]
        pnl = float(r.get("pnl", 0) or 0)
        vol = float(r.get("vol", 0) or 0)
        wallet = r.get("proxyWallet", "")
        wallet_short = wallet[:6] + "…" + wallet[-4:] if len(wallet) > 14 else wallet
        badge = "✓ " if r.get("verifiedBadge") else "  "

        line = (
            f"{rank:>3} | {badge}{name:<26} | {format_money(pnl):>10} | "
            f"{format_money(vol):>10} | {wallet_short:<14}"
        )

        if with_activity:
            activity = r.get("_activity")
            if activity:
                ts = activity.get("timestamp", 0)
                title_short = (activity.get("title", "") or "")[:30]
                line += f" | {format_age(ts):>5} назад ({title_short})"
            else:
                line += f" | {'нет данных':>22}"

        print(line)
    print()


def parse_args():
    p = argparse.ArgumentParser(
        description="Поиск прибыльных трейдеров на Polymarket",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument("--category", default="OVERALL", choices=ALL_CATEGORIES)
    p.add_argument("--period", default="MONTH", choices=ALL_PERIODS)
    p.add_argument("--order", default="PNL", choices=ALL_ORDERS)
    p.add_argument("--limit", type=int, default=25,
                   help="Размер выборки (1-50)")
    p.add_argument("--all-categories", action="store_true",
                   help="Топ-N по каждой категории отдельно")
    p.add_argument("--activity", action="store_true",
                   help="Дополнительно дёрнуть последнюю сделку каждого трейдера "
                        "(медленнее: +1 запрос на каждого)")
    return p.parse_args()


def enrich_with_activity(rows: List[Dict[str, Any]]):
    """Добавляет _activity (последнюю сделку) к каждому трейдеру."""
    if not rows:
        return
    print(f"  Запрашиваю последнюю активность для {len(rows)} трейдеров...")
    for i, r in enumerate(rows, 1):
        wallet = r.get("proxyWallet")
        if wallet:
            r["_activity"] = fetch_last_activity(wallet)
        if i % 5 == 0 or i == len(rows):
            print(f"    [{i}/{len(rows)}]", flush=True)
        time.sleep(0.15)  # вежливо


def main():
    args = parse_args()

    if not 1 <= args.limit <= 50:
        print("Limit должен быть 1-50 (ограничение Polymarket API)")
        sys.exit(1)

    if args.all_categories:
        # Топ по каждой категории отдельно — лимит порежем чтобы быстрее
        limit = min(args.limit, 10)
        print(f"\nСканирую топ-{limit} в каждой категории "
              f"(period={args.period}, order={args.order})...")
        for cat in ALL_CATEGORIES:
            rows = fetch_leaderboard(
                category=cat, period=args.period, order=args.order, limit=limit
            )
            if args.activity:
                enrich_with_activity(rows)
            title = (
                f"{cat}  |  {args.period}  |  по {args.order}  "
                f"(топ-{limit})"
            )
            print_table(rows, title, with_activity=args.activity)
            time.sleep(0.3)
    else:
        # Простой режим — одна категория
        print(f"\nЗапрашиваю leaderboard: "
              f"{args.category} / {args.period} / по {args.order} / топ-{args.limit}")
        rows = fetch_leaderboard(
            category=args.category,
            period=args.period,
            order=args.order,
            limit=args.limit,
        )
        if args.activity:
            enrich_with_activity(rows)
        title = (
            f"{args.category}  |  {args.period}  |  по {args.order}  "
            f"(топ-{len(rows)})"
        )
        print_table(rows, title, with_activity=args.activity)

    print("Подсказка: чтобы скопировать кошелёк трейдера в config — "
          "найди интересного в списке и скопируй его proxyWallet "
          "(см. вывод activity для полного адреса).\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nПрервано.")
