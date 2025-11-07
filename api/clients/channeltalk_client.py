# api/clients/channeltalk_client.py
import os, asyncio
from typing import Optional, Dict, Any
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=ENV_PATH)

CHANNELTALK_API_BASE = os.getenv("CHANNELTALK_API_BASE", "https://api.channel.io/open/v5")
CHANNELTALK_BOT_NAME = os.getenv("CHANNELTALK_BOT_NAME", "EventOK")

_httpx_client = None

def _client():
    global _httpx_client
    if _httpx_client is None:
        import httpx
        _httpx_client = httpx.AsyncClient(timeout=10)
    return _httpx_client

def _auth_headers() -> Dict[str, str]:
    """Open API v5 인증: x-access-key / x-access-secret"""
    key = os.getenv("CHANNELTALK_ACCESS_KEY")
    sec = os.getenv("CHANNELTALK_ACCESS_SECRET")
    if not key or not sec:
        raise RuntimeError("Set CHANNELTALK_ACCESS_KEY & CHANNELTALK_ACCESS_SECRET")
    return {
        "Content-Type": "application/json",
        "x-access-key": key,
        "x-access-secret": sec,
    }

async def send_message_to_userchat(
    user_chat_id: str,
    text: str,
    *,
    bot_name: Optional[str] = None,
    plain: bool = True
):
    if not user_chat_id:
        return {"ok": False, "reason": "no_user_chat_id"}

    params = {"botName": bot_name or CHANNELTALK_BOT_NAME}
    url = f"{CHANNELTALK_API_BASE}/user-chats/{user_chat_id}/messages"
    body = {"plainText": text} if plain else {"blocks": [{"type": "text", "value": text}]}
    headers = _auth_headers()

    backoff = 0.5
    for _ in range(5):
        resp = await _client().post(url, params=params, headers=headers, json=body)
        if resp.status_code < 400:
            try:
                return resp.json()
            except Exception:
                return {"ok": True}
        if resp.status_code in (429, 500, 502, 503, 504):
            await asyncio.sleep(backoff)
            backoff *= 2
            continue
        return {"ok": False, "status": resp.status_code, "error": resp.text}

    return {"ok": False, "status": 502, "error": "retry_exceeded"}
