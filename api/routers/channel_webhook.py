# api/routers/channel_webhook.py
import os, json, hmac, hashlib, base64, logging
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

from api.clients.channeltalk_client import send_message_to_userchat
from api.db.session import get_session
from api.db.crud import upsert_user, add_inquery, get_recent_inqueries
from api.db.models import ChatLog  # 봇 로그 저장에 사용

# ==== 추가 ====
from sqlalchemy import text as sa_text
# ==============

load_dotenv()
logging.basicConfig(level=logging.INFO)

router = APIRouter(prefix="/channel", tags=["channel"])

WEBHOOK_SIGNING_SECRET = os.getenv("CHANNELTALK_WEBHOOK_SECRET", "") or ""
WEBHOOK_QUERY_TOKEN    = os.getenv("CHANNELTALK_WEBHOOK_TOKEN", "") or ""
CHANNEL_DEBUG          = os.getenv("CHANNEL_DEBUG", "false").lower() in ("1", "true", "yes", "y")

SIGNING_ENABLED = bool(WEBHOOK_SIGNING_SECRET)
TOKEN_ENABLED   = bool(WEBHOOK_QUERY_TOKEN)


# ===== 서명/토큰 검증 =====
def verify_signature(raw: bytes, sig: str | None) -> bool:
    if not SIGNING_ENABLED:
        return True
    if not sig:
        return False
    dig = hmac.new(WEBHOOK_SIGNING_SECRET.encode(), raw, hashlib.sha256).digest()
    expect = base64.b64encode(dig).decode()
    return hmac.compare_digest(expect, sig)

def verify_query_token(tok: str | None) -> bool:
    if not TOKEN_ENABLED:
        return True
    if not tok:
        return False
    return hmac.compare_digest(tok, WEBHOOK_QUERY_TOKEN)

def is_verified(request: Request, raw: bytes) -> bool:
    return verify_signature(raw, request.headers.get("X-Signature")) \
        or verify_query_token(request.query_params.get("token"))


# ===== 추출 유틸 =====
def extract_user_chat_id(payload: dict) -> str | None:
    ent = payload.get("entity") or {}
    if isinstance(ent, dict) and ent.get("chatId") is not None:
        return str(ent["chatId"])

    data = payload.get("data") or {}
    for k in ("userChatId", "chatId"):
        v = data.get(k)
        if v is not None:
            return str(v)

    msgs = payload.get("messages")
    if isinstance(msgs, list) and msgs and isinstance(msgs[0], dict):
        cid = msgs[0].get("chatId")
        if cid is not None:
            return str(cid)

    return None

def extract_text(payload: dict) -> str:
    ent = payload.get("entity") or {}
    if isinstance(ent, dict):
        t = (ent.get("plainText") or "").strip()
        if t:
            return t
        blocks = ent.get("blocks") or []
        if isinstance(blocks, list) and blocks and isinstance(blocks[0], dict):
            if blocks[0].get("type") == "text":
                t = (blocks[0].get("value") or "").strip()
                if t:
                    return t

    msgs = payload.get("messages") or []
    if isinstance(msgs, list) and msgs and isinstance(msgs[0], dict):
        t = (msgs[0].get("plainText") or "").strip()
        if t:
            return t
        blocks = msgs[0].get("blocks") or []
        if isinstance(blocks, list) and blocks and isinstance(blocks[0], dict):
            if blocks[0].get("type") == "text":
                t = (blocks[0].get("value") or "").strip()
                if t:
                    return t

    data = payload.get("data")
    if isinstance(data, dict):
        t = (data.get("plainText") or "").strip()
        if t:
            return t

    return ""

def extract_fullname(payload: dict) -> str | None:
    refers = payload.get("refers") or {}
    if isinstance(refers, dict):
        u = refers.get("user") or {}
        if isinstance(u, dict):
            name = u.get("name")
            return str(name) if name else None

    ent = payload.get("entity") or {}
    if isinstance(ent, dict):
        name = ent.get("name")
        if name:
            return str(name)

    return None

def split_name(fullname: str | None):
    if not fullname:
        return None, None
    p = str(fullname).strip().split(maxsplit=1)
    return (p[0], p[1]) if len(p) > 1 else (p[0], None)

def combine_name(first: str | None, last: str | None) -> str | None:
    if first and last:
        return f"{first} {last}"
    return first or last or None

def classify_actor(payload: dict) -> str:
    ent = payload.get("entity") or {}
    if isinstance(ent, dict):
        pt = ent.get("personType")
        if pt in ("user", "bot"):
            return pt

    msgs = payload.get("messages")
    if isinstance(msgs, list) and msgs:
        pt = (msgs[0] or {}).get("personType")
        if pt in ("user", "bot"):
            return pt

    refers = payload.get("refers") or {}
    online = refers.get("online") or {}
    if isinstance(online, dict):
        pt = online.get("personType")
        if pt in ("user", "bot"):
            return pt

    return "unknown"

def extract_owner_id(payload: dict) -> str | None:
    refers = payload.get("refers") or {}
    if isinstance(refers, dict):
        user_chat = refers.get("userChat") or {}
        if isinstance(user_chat, dict) and user_chat.get("userId"):
            return str(user_chat["userId"])
        u = refers.get("user") or {}
        if isinstance(u, dict) and u.get("id"):
            return str(u["id"])
        online = refers.get("online") or {}
        if isinstance(online, dict) and online.get("personId"):
            return str(online["personId"])

    ent = payload.get("entity") or {}
    if isinstance(ent, dict) and ent.get("personId"):
        return str(ent["personId"])

    return None


# ==== 추가: RAW SQL (async) ====
async def execute_raw_query(sql: str):
    async with get_session() as s:
        res = await s.execute(sa_text(sql))
        return res.fetchall()
# =======================


# ===== 비즈 유틸 =====
async def route_reply(text: str) -> str:
    """
    (대동제/락페/해키) + (화장실/무대/안내/부스/금지물품/분실물)
    → DB 조회 후 가장 가까운 지점 링크 또는 공지 메시지 반환
    """
    if not text:
        return "문의가 접수되었어요. 최대한 빨리 답변드릴게요 🙏"

    t = text.strip()

    # prefix → loc & 임시 사용자 좌표 (실좌표 있으면 대체)
    prefix_map = {
        "대동제": {"loc": 1, "user_long": 0.0,   "user_lati": 0.0},
        "락페":  {"loc": 2, "user_long": 126.0, "user_lati": 37.0},
        "해키":  {"loc": 3, "user_long": 0.0,   "user_lati": 0.0},
    }
    matched_prefix = next((p for p in prefix_map.keys() if t.startswith(p)), None)
    if not matched_prefix:
        # 기타 일반 명령 처리(/ping, /help 등)는 아래에서 처리하도록 빠져나감
        pass
    else:
        loc = prefix_map[matched_prefix]["loc"]
        user_long = float(prefix_map[matched_prefix]["user_long"])
        user_lati = float(prefix_map[matched_prefix]["user_lati"])

        def ends(sfx: str) -> bool:
            return t.endswith(sfx)

        # 공지
        if ends("금지물품"):
            row = await execute_raw_query(
                f"select * from message where msg_type = '물품 공지' and loc = {loc} order by id limit 1"
            )
            row = row[0] if row else None
            return row[3] if row else "등록된 금지물품 공지가 아직 없어요."

        if ends("분실물"):
            row = await execute_raw_query(
                f"select * from message where msg_type = '분실물 공지' and loc = {loc} order by id limit 1"
            )
            row = row[0] if row else None
            return row[3] if row else "등록된 분실물 공지가 아직 없어요."

        # 공통 유틸
        def find_closest(rows, user_long: float, user_lati: float):
            best_row, best_dist = None, float("inf")
            for r in rows or []:
                try:
                    pos_long = float(r[4])
                    pos_lati = float(r[5])
                except (ValueError, TypeError, IndexError):
                    continue
                d = (pos_long - user_long) ** 2 + (pos_lati - user_lati) ** 2
                if d < best_dist:
                    best_dist, best_row = d, r
            return best_row

        def make_map_msg(kind_label: str, r) -> str:
            if not r:
                return f"{kind_label} 정보가 아직 없어요."
            title = str(r[3])
            lng = str(r[4])
            lat = str(r[5])
            return f'가장 가까운 {kind_label}은(는) "https://map.naver.com?lng={lng}&lat={lat}&title={title}" 입니다'

        # 좌표형
        if ends("화장실"):
            rows = await execute_raw_query(
                f"select * from point where pos_type = 'toilet' and loc = {loc}"
            )
            return make_map_msg("화장실", find_closest(rows, user_long, user_lati))

        if ends("무대"):
            rows = await execute_raw_query(
                f"select * from point where pos_type = 'stage' and loc = {loc}"
            )
            return make_map_msg("무대", find_closest(rows, user_long, user_lati))

        if ends("안내"):
            rows = await execute_raw_query(
                f"select * from point where pos_type = 'helpdesk' and loc = {loc}"
            )
            return make_map_msg("안내데스크", find_closest(rows, user_long, user_lati))

        if ends("부스"):
            rows = await execute_raw_query(
                f"select * from point where pos_type = 'booth' and loc = {loc}"
            )
            return make_map_msg("부스", find_closest(rows, user_long, user_lati))

        # prefix는 맞지만 상세 키워드가 없을 때
        return "원하시는 항목(화장실/무대/안내/부스/금지물품/분실물)을 붙여서 다시 말씀해 주세요."

    # === 일반 명령 처리 ===
    lower = (text or "").lower().strip()
    if lower == "/ping":
        return "pong 🏓"
    if lower.startswith("/help"):
        return "명령어: /ping, /help, /history (최근 문의 5건), /inq <내용>"

    return "문의가 접수되었어요. 최대한 빨리 답변드릴게요 🙏"


# ===== 사용자 메시지 처리 =====
async def _process_user_and_reply(
    owner_id: str,
    f_name: str | None,
    l_name: str | None,
    user_chat_id: str,
    text: str,
):
    display_name = combine_name(f_name, l_name)
    t = (text or "").lower().strip()

    if t.startswith("/history"):
        async with get_session() as s:
            rows = await get_recent_inqueries(s, user_id=owner_id, limit=5)
        lines = [f"- {r.message}" for r in rows] or ["(문의 없음)"]
        reply = "최근 문의:\n" + "\n".join(lines)
        await send_message_to_userchat(user_chat_id, reply)
        return

    if t.startswith("/inq"):
        body = text.split(" ", 1)[1].strip() if " " in (text or "") else ""
        async with get_session() as s:
            await upsert_user(s, user_id=owner_id, name=display_name)
            await add_inquery(s, user_id=owner_id, content=(body or "(내용 없음)"))
        await send_message_to_userchat(user_chat_id, "문의가 접수되었어요. 최대한 빨리 답변드릴게요 🙏")
        return

    async with get_session() as s:
        await upsert_user(s, user_id=owner_id, name=display_name)
        log_id = await add_inquery(s, user_id=owner_id, content=(text or "(내용 없음)"))
        if CHANNEL_DEBUG:
            logging.info("DBG :: saved user log_id=%s uid=%s msg=%r", log_id, owner_id, text)

    reply_msg = await route_reply(text)
    await send_message_to_userchat(user_chat_id, reply_msg)


# ===== 웹훅 엔드포인트 =====
@router.post("/webhook")
async def channel_webhook(request: Request):
    raw = await request.body()

    if CHANNEL_DEBUG:
        try:
            raw_text = raw.decode("utf-8", errors="replace")
        except Exception:
            raw_text = "<decode failed>"
        logging.info("\n===== WEBHOOK RAW PAYLOAD START =====\n%s\n===== WEBHOOK RAW PAYLOAD END =====", raw_text)

    if not is_verified(request, raw):
        raise HTTPException(status_code=401, detail="unauthorized webhook")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        payload = {}

    actor    = classify_actor(payload)
    chat_id  = extract_user_chat_id(payload)
    text     = extract_text(payload)
    owner_id = extract_owner_id(payload) or "unknown"
    fullname = extract_fullname(payload)
    f_name, l_name = split_name(fullname)

    if CHANNEL_DEBUG:
        logging.info("DBG :: actor=%s owner=%s chat=%s text=%r fullname=%r", actor, owner_id, chat_id, text, fullname)

    if not chat_id:
        return JSONResponse({"ok": False, "reason": "no_userChatId_in_payload"})

    if actor == "user":
        await _process_user_and_reply(owner_id, f_name, l_name, chat_id, text)
        return JSONResponse({"ok": True, "handled": "user"})

    if actor == "bot":
        async with get_session() as s:
            await upsert_user(s, user_id=owner_id, name=combine_name(f_name, l_name))
            bot_log = ChatLog(channel_user_id=owner_id, role="bot", message=(text or "(내용 없음)"))
            s.add(bot_log)
            await s.commit()
            await s.refresh(bot_log)
        if CHANNEL_DEBUG:
            logging.info("DBG :: saved bot log_id=%s uid=%s msg=%r", bot_log.id, owner_id, text)
        return JSONResponse({"ok": True, "stored": "bot"})

    if CHANNEL_DEBUG:
        logging.info("DBG :: skipped unknown actor")
    return JSONResponse({"ok": True, "skipped": "unknown-actor"})
