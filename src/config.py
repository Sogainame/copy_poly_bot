"""Загрузка и валидация конфига."""
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List

import yaml
from dotenv import load_dotenv

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


@dataclass
class Config:
    target_wallet: str
    bet_pct: float
    bet_min: float
    bet_max: float
    filter_keywords: List[str]   # слова в title маркета. Пусто = копируем всё
    filter_markets: List[str]    # deprecated, оставлен для обратной совместимости
    min_size_shares: float
    poll_interval: float
    api_limit: int
    max_retries: int
    mode: str

    # Из .env
    tg_token: str = ""
    tg_chat: str = ""
    builder_api_key: str = ""
    builder_secret: str = ""
    builder_passphrase: str = ""
    proxy_wallet: str = ""

    def validate(self):
        if not self.target_wallet.startswith("0x") or len(self.target_wallet) != 42:
            raise ValueError(f"target_wallet выглядит некорректно: {self.target_wallet}")
        if self.bet_pct <= 0 or self.bet_pct > 1:
            raise ValueError("bet_pct должен быть 0..1")
        if self.bet_min < 1:
            raise ValueError("bet_min должен быть >= 1.0 (минимум Polymarket)")
        if self.bet_max < self.bet_min:
            raise ValueError("bet_max < bet_min")
        if self.poll_interval < 0.1:
            raise ValueError("poll_interval слишком мал (риск бана)")
        if self.mode not in ("dry", "live"):
            raise ValueError("mode должен быть 'dry' или 'live'")
        if self.mode == "live" and not self.builder_api_key:
            raise ValueError("LIVE требует BUILDER_API_KEY в .env")


def load_config() -> Config:
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        y = yaml.safe_load(f)

    cfg = Config(
        target_wallet=y["target_wallet"],
        bet_pct=float(y["bet_pct"]),
        bet_min=float(y["bet_min"]),
        bet_max=float(y["bet_max"]),
        filter_keywords=list(y.get("filter_keywords", [])),
        filter_markets=list(y.get("filter_markets", [])),
        min_size_shares=float(y.get("min_size_shares", 1)),
        poll_interval=float(y.get("poll_interval", 1.0)),
        api_limit=int(y.get("api_limit", 20)),
        max_retries=int(y.get("max_retries", 5)),
        mode=str(y.get("mode", "dry")).lower(),
        tg_token=os.getenv("TG_TOKEN", ""),
        tg_chat=os.getenv("TG_CHAT", ""),
        builder_api_key=os.getenv("BUILDER_API_KEY", ""),
        builder_secret=os.getenv("BUILDER_SECRET", ""),
        builder_passphrase=os.getenv("BUILDER_PASSPHRASE", ""),
        proxy_wallet=os.getenv("PROXY_WALLET_ADDRESS", ""),
    )
    cfg.validate()
    return cfg
