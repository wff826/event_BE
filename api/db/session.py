import os
from typing import AsyncIterator
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)

load_dotenv()

# 우선순위: DB_URL > 조합형 환경변수
DB_URL = os.getenv("DB_URL")
if not DB_URL:
    DB_HOST = os.getenv("DB_HOST", "211.118.63.85")
    DB_NAME = os.getenv("DB_NAME", "channel")
    DB_USER = os.getenv("DB_USER", "channel")
    DB_PASS = os.getenv("DB_PASS", "")
    DB_URL = f"mysql+asyncmy://{DB_USER}:{DB_PASS}@{DB_HOST}:3306/{DB_NAME}?charset=utf8mb4"

engine = create_async_engine(
    DB_URL,
    pool_pre_ping=True,
    pool_recycle=1800,
    echo=False,   # 필요하면 True
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """
    FastAPI Depends에서 사용할 비동기 세션 컨텍스트 매니저
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

# --- 앱 시작 시 1회 호출하여 테이블 생성 ---
async def init_models() -> None:
    """
    models.Base 기준으로 테이블을 생성합니다.
    Alembic 도입 전 임시 초기화 용도.
    """
    from api.db.models import Base  # 지연 임포트로 순환참조 방지
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
