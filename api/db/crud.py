# api/db/crud.py
from typing import Optional, List
from sqlalchemy import select, desc
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ChannelUser, ChatLog

__all__ = ["upsert_user", "add_inquery", "get_recent_inqueries"]


async def upsert_user(
    session: AsyncSession,
    user_id: str,                 # == ChannelUser.channel_user_id
    name: Optional[str] = None,
) -> ChannelUser:
    """
    channel_user_id 기준으로 ChannelUser 생성/갱신 (비동기)
    """
    try:
        stmt = select(ChannelUser).where(ChannelUser.channel_user_id == user_id)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()

        if user is None:
            user = ChannelUser(channel_user_id=user_id, name=name)
            session.add(user)
        else:
            if name is not None:
                user.name = name

        await session.commit()
        await session.refresh(user)
        return user
    except SQLAlchemyError:
        await session.rollback()
        raise


async def add_inquery(
    session: AsyncSession,
    user_id: str,                 # == ChatLog.channel_user_id
    content: str,
) -> int:
    """
    사용자 문의를 ChatLog에 저장 (role='user')
    """
    try:
        log = ChatLog(
            channel_user_id=user_id,
            role="user",
            message=content,
        )
        session.add(log)
        await session.commit()
        await session.refresh(log)
        return log.id
    except SQLAlchemyError:
        await session.rollback()
        raise


async def get_recent_inqueries(
    session: AsyncSession,
    user_id: str,
    limit: int = 5,
) -> List[ChatLog]:
    """
    해당 사용자의 최근 사용자 메시지(=inquery) 반환
    """
    stmt = (
        select(ChatLog)
        .where(ChatLog.channel_user_id == user_id)
        .where(ChatLog.role == "user")
        .order_by(desc(ChatLog.created_at))
        .limit(limit)
    )
    res = await session.execute(stmt)
    rows = res.scalars().all()
    return list(rows)
