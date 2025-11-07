# api/scripts/main.py
from fastapi import FastAPI
from api.routers.channel_webhook import router as channel_router
from api.db.session import init_models


app = FastAPI(title="EventLive API")


@app.on_event("startup")
async def on_startup():
    """
    앱 시작 시 DB 모델 테이블 생성 (Alembic 도입 전 초기화용)
    """
    await init_models()


# 라우터 등록
app.include_router(channel_router)


# 헬스체크 (배포 환경 / 로드밸런서 체크용)
@app.get("/health")
async def health():
    return {"ok": True}
