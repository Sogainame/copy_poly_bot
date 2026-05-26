"""Движок копирования: DRY (только логи) и LIVE (реальные ордера в будущем)."""
from typing import Dict, Any, Optional
from datetime import datetime, timezone


def calc_my_bet(his_usd: float, pct: float, min_usd: float, max_usd: float) -> float:
    """Размер моей копии: pct от его, в коридоре [min_usd, max_usd]."""
    return round(max(min_usd, min(his_usd * pct, max_usd)), 2)


def build_trader_record(t: Dict[str, Any], dedup_key: str) -> Dict[str, Any]:
    """Структурированная запись о сделке трейдера для trader_trades.jsonl."""
    size = float(t.get("size", 0))
    price = float(t.get("price", 0))
    return {
        "dedup_key": dedup_key,
        "ts": t.get("timestamp"),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "side": t.get("side"),
        "outcome": t.get("outcome"),
        "size": size,
        "price": price,
        "usd": round(size * price, 4),
        "asset": t.get("asset"),
        "conditionId": t.get("conditionId"),
        "slug": t.get("slug"),
        "transactionHash": t.get("transactionHash") or t.get("transaction_hash"),
        "title": t.get("title"),
    }


def build_copy_record(
    copy_n: int,
    parent: Dict[str, Any],
    my_usd: float,
    my_shares: float,
    mode: str,
    dedup_key: str,
) -> Dict[str, Any]:
    """Структурированная запись о нашей копии для our_copies.jsonl."""
    return {
        "copy_n": copy_n,
        "parent_dedup_key": dedup_key,
        "parent_ts": parent.get("timestamp"),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "side": parent.get("side"),
        "outcome": parent.get("outcome"),
        "asset": parent.get("asset"),
        "conditionId": parent.get("conditionId"),
        "slug": parent.get("slug"),
        "title": parent.get("title"),
        "his_size": float(parent.get("size", 0)),
        "his_price": float(parent.get("price", 0)),
        "his_usd": round(float(parent.get("size", 0)) * float(parent.get("price", 0)), 4),
        "my_usd": my_usd,
        "my_shares": my_shares,
        "executed": (mode == "live"),  # в DRY ничего не исполняем
    }


def execute_live_buy(parent: Dict[str, Any], my_usd: float, cfg) -> Optional[Dict[str, Any]]:
    """LIVE: реальный ордер. Заглушка — реализуется отдельно при переходе на LIVE.
    Возвращает order info или None при ошибке.
    """
    raise NotImplementedError(
        "LIVE режим ещё не реализован. Запусти в DRY (mode: dry в config.yaml)."
    )
