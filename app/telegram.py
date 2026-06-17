import json
from typing import Any
from urllib import error as urlerror
from urllib import parse, request as urlrequest

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_PROXY


def telegram_enabled() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def telegram_api(method: str, data: dict[str, Any]) -> dict[str, Any]:
    if not telegram_enabled():
        return {"enabled": False}

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    body = parse.urlencode(data).encode("utf-8")

    opener = urlrequest.build_opener()
    if TELEGRAM_PROXY:
        opener = urlrequest.build_opener(
            urlrequest.ProxyHandler(
                {
                    "http": TELEGRAM_PROXY,
                    "https": TELEGRAM_PROXY,
                }
            )
        )

    req = urlrequest.Request(api_url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with opener.open(req, timeout=15) as resp:
            return {"enabled": True, "status": resp.status}
    except urlerror.URLError as exc:
        return {"enabled": True, "error": str(exc)}


def send_telegram_message(text: str, reply_markup: dict[str, Any] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": "true",
    }
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)

    return telegram_api("sendMessage", data)


def answer_telegram_callback(callback_query_id: str, text: str) -> dict[str, Any]:
    return telegram_api("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text})


def edit_telegram_message(chat_id: str, message_id: int, text: str) -> dict[str, Any]:
    return telegram_api(
        "editMessageText",
        {
            "chat_id": chat_id,
            "message_id": str(message_id),
            "text": text,
            "disable_web_page_preview": "true",
        },
    )
