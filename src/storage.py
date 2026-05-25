"""Хранилище: JSONL для сделок + JSON для state.

Файлы:
  data/trader_trades.jsonl — ВСЕ сделки трейдера которые видит бот
                             (включая отфильтрованные — для аналитики)
  data/our_copies.jsonl    — наши копии (только то что прошло фильтры)
  data/state.json          — seen_ids + последний обработанный timestamp
  data/bot.log             — человеко-читаемый лог
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Set


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TRADER_TRADES = DATA_DIR / "trader_trades.jsonl"
OUR_COPIES = DATA_DIR / "our_copies.jsonl"
STATE_FILE = DATA_DIR / "state.json"
BOT_LOG = DATA_DIR / "bot.log"


def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def write_trader_trade(record: dict):
    ensure_data_dir()
    with open(TRADER_TRADES, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_our_copy(record: dict):
    ensure_data_dir()
    with open(OUR_COPIES, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def log(msg: str):
    """Пишет в bot.log + в stdout."""
    ensure_data_dir()
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(BOT_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"seen_ids": [], "copy_n": 0, "last_target": ""}


def save_state(state: dict):
    ensure_data_dir()
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def seen_ids_to_set(state: dict) -> Set[str]:
    return set(state.get("seen_ids", []))


def trim_seen(seen: Set[str], max_size: int = 5000) -> Set[str]:
    """Обрезает seen чтоб не пухло. Сохраняет последние max_size."""
    if len(seen) <= max_size:
        return seen
    # set неупорядочен, поэтому просто берём произвольные max_size
    return set(list(seen)[-max_size:])
