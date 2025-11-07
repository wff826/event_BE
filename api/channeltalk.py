# event/api/channeltalk.py
import os, re, json, hmac, hashlib
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

# ---- env (local) ----
load_dotenv()
WEBHOOK_SECRET = os.getenv("CHANNELTALK_WEBHOOK_SECRET", "")
CHANNELTALK_API_BASE = os.getenv("CHANNELTALK_API_BASE", "https://api.channel.io/open/v5")
CHANNELTALK_API_TOKEN = os.getenv("CHANNELTALK_API_TOKEN", "")
REDIS_URL = os.getenv("REDIS_URL", "")

# ---- optional redis (fallback to in-memory) ----
R = None
COMMANDS: Dict[str, str] = {}   # fallback memory (ex: {"입장줄":"45분"})
FAQ: List[Dict[str, str]] = []  # fallback memory
LOC: Dict[str, List[Dict[str, float | str]]] = {}  # {"화장실":[{"name":..,"lat":..,"lng":..}]}

if REDIS_URL:
    try:
        import redis  # type: ignore
        R = redis.from_url(REDIS_URL, decode_responses=True)
    except Exception:
        R = None  # keep fallback

# ---- app ----
app = FastAPI(title="EventLive", version="0.3.0")

# ---------- models (for Swagger request body) ----------
class WebhookPayload(BaseModel):
    user: Optional[dict] = None      # {"id": "...", "type": "operator"|"user", ...}
    userChat: Optional[dict] = None  # {"id": "..."} (채널톡 실제 payload 기준)
    userChatId: Optional[str] = None
    message: Optional[str] = None    # 사용자가 보낸 텍스트

# ---------- helpers ----------
def verify_signature(raw_body: bytes, signature: Optional[str]) -> bool:
    if not WEBHOOK_SECRET:
        return True
    if not signature:
        return False
    expected = hmac.new(WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

def is_operator(evt: Dict[str, Any]) -> bool:
    user = evt.get("user") or {}
    return bool(user.get("type") == "operator" or user.get("isOperator") is True)

def classify_intent(text: str) -> str:
    if re.search(r"(입장줄|대기시간|주차|줄)", text): return "command"
    if re.search(r"(화장실|흡연장|부스|푸드|먹거리|보관|분실물)", text): return "location"
    if any(k in text for k in ["티켓","분실","돗자리","반입"]): return "faq"
    return "other"

# --- storage wrappers (redis or memory) ---
def set_cmd(key: str, val: str):
    if R: R.setex(f"cmd:{key}", 3600, val)  # 1h TTL
    else: COMMANDS[key] = val

def get_cmd(key: str) -> Optional[str]:
    return R.get(f"cmd:{key}") if R else COMMANDS.get(key)

def save_faq(keywords_csv: str, answer: str):
    if R:
        key = f"faq:{hash(keywords_csv)}"
        R.hset(key, mapping={"keywords": keywords_csv, "answer": answer})
    else:
        FAQ.append({"keywords": keywords_csv, "answer": answer})

def list_faqs() -> List[Dict[str, str]]:
    if R:
        out: List[Dict[str, str]] = []
        for k in R.scan_iter("faq:*"):
            rec = R.hgetall(k)
            if rec: out.append({"keywords": rec.get("keywords",""), "answer": rec.get("answer","")})
        return out
    return FAQ

def add_location(category: str, name: str, lat: float, lng: float):
    if R:
        key = f"loc:{category}"
        R.rpush(key, json.dumps({"name": name, "lat": lat, "lng": lng}))
    else:
        LOC.setdefault(category, []).append({"name": name, "lat": lat, "lng": lng})

def nearest(category: str, lat: float, lng: float) -> Optional[Dict[str, Any]]:
    if R:
        items = [json.loads(x) for x in R.lrange(f"loc:{category}", 0, -1)]
    else:
        items = LOC.get(category, [])
    if not items: return None
    return min(items, key=lambda o: (o["lat"]-lat)**2 + (o["lng"]-lng)**2)

def infer_location_category(text: str) -> str:
    if "화장실" in text: return "화장실"
    if "부스" in text: return "부스"
    if ("푸드" in text) or ("먹거리" in text): return "푸드"
    return "기타"

def handle_operator(text: str) -> str:
    # /입장줄 30분 | /주차 만석 | /faq 키1,키2=답변 | /loc 화장실 A1 37.55 127.02
    if not text.startswith("/"):
        return "형식: /입장줄 30분 | /faq 키1,키2=답변 | /loc 카테고리 이름 lat lng"
    m = re.match(r"/(\S+)\s+(.+)", text)
    if not m:
        return "형식 오류: /입장줄 30분 | /faq 키1,키2=답변 | /loc 카테고리 이름 lat lng"
    cmd, arg = m.group(1), m.group(2)

    if cmd in ["입장줄","주차","대기시간","입장시간"]:
        set_cmd(cmd, arg)
        return f"[OK] {cmd} = {arg}"
    if cmd.lower() == "faq":
        if "=" not in arg: return "형식: /faq 키1,키2=답변"
        kws, ans = arg.split("=", 1)
        save_faq(kws, ans)
        return "[OK] FAQ 저장"
    if cmd.lower() == "loc":
        parts = arg.split()
        if len(parts) != 4: return "형식: /loc <카테고리> <이름> <lat> <lng>"
        cat, name, s_lat, s_lng = parts
        try:
            add_location(cat, name, float(s_lat), float(s_lng))
        except ValueError:
            return "좌표 숫자 형식 오류"
        return f"[OK] {cat}:{name} 좌표 저장"
    return "알 수 없는 커맨드"

# ---------- routes ----------
@app.get("/")
def health():
    return {"ok": True, "msg": "EventLive backend is running"}

# Vercel 배포 시: /api/channeltalk  + 아래 경로가 합쳐짐
@app.post("/")
@app.post("/webhook")
async def webhook(payload: WebhookPayload, request: Request):
    # optional signature check (실서버에서만 활성 추천)
    sig = request.headers.get("X-Signature") or request.headers.get("X-Channel-Signature")
    raw = await request.body()
    if not verify_signature(raw, sig):
        raise HTTPException(status_code=401, detail="bad signature")

    text = (payload.message or "").strip()
    evt = payload.model_dump()
    user_chat_id = str(
        payload.userChatId
        or (payload.userChat or {}).get("id")
        or ""
    )

    # operator path
    if is_operator(evt) and text.startswith("/"):
        msg = handle_operator(text)
        return JSONResponse({"ok": True, "role": "operator", "msg": msg})

    # user path
    intent = classify_intent(text)
    if intent == "command":
        key = "입장줄" if ("줄" in text or "대기" in text) else ("주차" if "주차" in text else "입장줄")
        val = get_cmd(key)
        reply = f"현재 {key} 상태는 '{val}' 입니다." if val else "아직 등록된 현장 정보가 없어요. 운영진에 연결해드릴게요."
    elif intent == "faq":
        reply = "관련 안내를 찾지 못했어요. 운영진에 연결해드릴게요."
        for rec in list_faqs():
            kws = [w.strip() for w in rec["keywords"].split(",") if w.strip()]
            if any(w in text for w in kws):
                reply = rec["answer"]; break
    elif intent == "location":
        m = re.search(r"(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)", text)
        if not m:
            reply = "좌표를 함께 보내주시면 가까운 위치를 찾아드려요. 예) '화장실 37.55,127.02'"
        else:
            lat, lng = float(m.group(1)), float(m.group(2))
            cat = infer_location_category(text)
            spot = nearest(cat, lat, lng)
            reply = (f"가까운 {cat}: {spot['name']} (lat {spot['lat']}, lng {spot['lng']})"
                     if spot else "등록된 위치 정보가 없어요. 운영진에 문의해 주세요.")
    else:
        reply = "무엇을 도와드릴까요? 예) '입장 줄', '주차', '티켓 분실'"

    # 지금은 로컬 개발 단계이므로 채널톡 전송 대신 JSON 응답만
    # 실제 전송은 아래 함수로 붙이면 됨:
    # await send_message_to_userchat(user_chat_id, reply, bot_name="EventLiveBot")

    return JSONResponse({"ok": True, "role": "user", "reply": reply, "userChatId": user_chat_id})

# ---------- (옵션) ChannelTalk 전송 클라이언트 ----------
# 사용 시: httpx 추가 필요 (requirements.txt에 이미 포함)
# async def send_message_to_userchat(user_chat_id: str, text: str, bot_name: Optional[str] = None):
#     if not user_chat_id: return
#     import httpx
#     headers = {"Authorization": f"Bearer {CHANNELTALK_API_TOKEN}", "Content-Type": "application/json"}
#     params = {"botName": bot_name} if bot_name else None
#     body = {"message": {"text": text}}
#     url = f"{CHANNELTALK_API_BASE}/user-chats/{user_chat_id}/messages"
#     async with httpx.AsyncClient(timeout=5.0) as client:
#         r = await client.post(url, headers=headers, params=params, json=body)
#         r.raise_for_status()
