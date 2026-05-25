"""Опциональные Telegram-алерты."""
import requests


def send(token: str, chat_id: str, text: str, timeout: float = 5.0) -> bool:
    if not token or not chat_id:
        return False
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=timeout,
        )
        return True
    except Exception:
        return False
