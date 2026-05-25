"""Copy Poly Bot — entry point.

Запуск:
    python3 bot.py

Останавливается через Ctrl+C. Состояние сохраняется в data/state.json.
При перезапуске продолжает с того же места (не копирует уже виденные сделки).
"""
import time
import signal
import sys
from datetime import datetime, timezone

from src.config import load_config
from src.storage import (
    log,
    load_state,
    save_state,
    seen_ids_to_set,
    trim_seen,
    write_trader_trade,
    write_our_copy,
    TRADER_TRADES,
    OUR_COPIES,
    BOT_LOG,
    STATE_FILE,
)
from src.watcher import fetch_trades, trade_dedup_key
from src.filters import match_filter, parse_market
from src.copy_engine import calc_my_bet, build_trader_record, build_copy_record, execute_live_buy
from src.telegram import send as tg_send


SHOULD_STOP = False


def handle_sigint(sig, frame):
    global SHOULD_STOP
    SHOULD_STOP = True
    log("[SIGINT] остановка после текущей итерации...")


signal.signal(signal.SIGINT, handle_sigint)
signal.signal(signal.SIGTERM, handle_sigint)


def main():
    global SHOULD_STOP
    cfg = load_config()

    log("=" * 70)
    log(f"Copy Poly Bot — старт")
    log(f"Target wallet:  {cfg.target_wallet}")
    log(f"Mode:           {cfg.mode.upper()}")
    log(f"Bet:            {cfg.bet_pct*100:.0f}% (мин ${cfg.bet_min}, макс ${cfg.bet_max})")
    log(f"Filter:         {', '.join(cfg.filter_markets)}")
    log(f"Poll interval:  {cfg.poll_interval}s | api_limit={cfg.api_limit} | retries={cfg.max_retries}")
    log(f"Files:          trader→{TRADER_TRADES.name}, copies→{OUR_COPIES.name}, log→{BOT_LOG.name}")
    log("=" * 70)

    state = load_state()
    if state.get("last_target") and state["last_target"] != cfg.target_wallet:
        log(f"[!] Target изменился: {state['last_target']} → {cfg.target_wallet}")
        log("    Старые seen_ids сохраняются. Чтобы начать с нуля — удали data/state.json")
    state["last_target"] = cfg.target_wallet

    seen = seen_ids_to_set(state)
    copy_n = state.get("copy_n", 0)

    # === Прогрев ===
    # При первом запуске все текущие сделки помечаем как уже виденные,
    # чтобы не плодить стартовый спам/дубликаты.
    initial = fetch_trades(
        wallet=cfg.target_wallet,
        limit=cfg.api_limit,
        max_retries=cfg.max_retries,
    )
    new_keys = set()
    for t in initial:
        new_keys.add(trade_dedup_key(t))
    fresh = new_keys - seen
    seen.update(new_keys)
    save_state({"seen_ids": list(seen), "copy_n": copy_n, "last_target": cfg.target_wallet})
    log(f"Прогрев: {len(initial)} текущих сделок (новых для нас: {len(fresh)}). Слушаю.\n")

    iter_count = 0
    err_streak = 0

    while not SHOULD_STOP:
        iter_count += 1
        try:
            trades = fetch_trades(
                wallet=cfg.target_wallet,
                limit=cfg.api_limit,
                max_retries=cfg.max_retries,
            )
            if not trades:
                err_streak += 1
                if err_streak == 1 or err_streak % 30 == 0:
                    log(f"[WARN] fetch вернул пусто ({err_streak} итераций подряд)")
            else:
                err_streak = 0

            new_to_process = []
            for t in trades:
                key = trade_dedup_key(t)
                if key in seen:
                    continue
                seen.add(key)
                new_to_process.append((key, t))

            # Сортируем от старых к новым (хронологический порядок)
            new_to_process.sort(key=lambda x: x[1].get("timestamp", 0))

            for key, t in new_to_process:
                # Записываем КАЖДУЮ его сделку (даже отфильтрованную)
                trader_rec = build_trader_record(t, key)
                write_trader_trade(trader_rec)

                # Фильтры: BUY only + размер + маркет
                side = t.get("side")
                size = float(t.get("size", 0))
                title = t.get("title", "")

                if side != "BUY":
                    continue
                if size < cfg.min_size_shares:
                    continue
                if not match_filter(title, cfg.filter_markets):
                    continue

                price = float(t.get("price", 0))
                if price <= 0:
                    continue

                his_usd = size * price
                my_usd = calc_my_bet(his_usd, cfg.bet_pct, cfg.bet_min, cfg.bet_max)
                my_shares = round(my_usd / price, 4)
                copy_n += 1

                copy_rec = build_copy_record(
                    copy_n=copy_n, parent=t, my_usd=my_usd,
                    my_shares=my_shares, mode=cfg.mode, dedup_key=key,
                )

                outcome = t.get("outcome", "?")
                short = title.replace("Bitcoin Up or Down - ", "").replace("Ethereum Up or Down - ", "ETH ")
                msg = (
                    f"COPY #{copy_n} {outcome:4} @{price:.3f} → "
                    f"{my_shares:.2f}sh ${my_usd:.2f} "
                    f"(он ${his_usd:.2f}) | {short}"
                )
                log(msg)

                if cfg.mode == "live":
                    try:
                        execute_live_buy(t, my_usd, cfg)
                    except NotImplementedError as e:
                        log(f"[!] {e}"); SHOULD_STOP = True; break
                    except Exception as e:
                        log(f"[LIVE ERR] {type(e).__name__}: {e}")
                        copy_rec["executed"] = False
                        copy_rec["error"] = str(e)

                write_our_copy(copy_rec)

                if cfg.tg_token and cfg.tg_chat:
                    tg_send(cfg.tg_token, cfg.tg_chat, msg)

            # Сохраняем стейт периодически
            if new_to_process or iter_count % 10 == 0:
                seen = trim_seen(seen)
                save_state({"seen_ids": list(seen), "copy_n": copy_n, "last_target": cfg.target_wallet})

            # Heartbeat
            if iter_count % 300 == 0:
                log(f"[HB] iter={iter_count}, copies={copy_n}, seen={len(seen)}")

        except Exception as e:
            log(f"[MAIN ERR] {type(e).__name__}: {e}")
            time.sleep(2)

        time.sleep(cfg.poll_interval)

    save_state({"seen_ids": list(seen), "copy_n": copy_n, "last_target": cfg.target_wallet})
    log(f"=== Остановлен. Всего копий: {copy_n} ===")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"FATAL: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
