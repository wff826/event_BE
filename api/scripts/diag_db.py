import asyncio, os
from datetime import datetime
from api.db.session import engine, AsyncSessionLocal, init_models
from api.db.models import ChannelUser, ChatLog
from sqlalchemy import select, func

def mask_url(url: str) -> str:
    if not url: return "(empty)"
    # mysql+asyncmy://user:pass@host:3306/db?query
    try:
        head, tail = url.split("://", 1)
        auth, rest = tail.split("@", 1)
        if ":" in auth:
            u, p = auth.split(":", 1)
            auth = f"{u}:***"
        return f"{head}://{auth}@{rest}"
    except Exception:
        return url

async def main():
    print("== DB URL ==")
    from api.db.session import DB_URL
    print(mask_url(DB_URL))

    print("== create_all ==")
    await init_models()

    async with AsyncSessionLocal() as s:
        # 1) 간단 SELECT: 테이블 존재 여부
        for tbl in (ChannelUser, ChatLog):
            q = select(func.count()).select_from(tbl)
            cnt = (await s.execute(q)).scalar_one()
            print(f"count({tbl.__tablename__}) = {cnt}")

        # 2) 테스트 쓰기
        test_uid = "diag_user_123"
        u = (await s.execute(select(ChannelUser).where(ChannelUser.channel_user_id==test_uid))).scalar_one_or_none()
        if u is None:
            u = ChannelUser(channel_user_id=test_uid, name="Diag User")
            s.add(u)
            await s.commit()
            await s.refresh(u)
            print("inserted ChannelUser:", u.id, u.channel_user_id)
        else:
            print("found ChannelUser:", u.id, u.channel_user_id)

        log = ChatLog(channel_user_id=test_uid, role="user", message=f"diag ping {datetime.now():%H:%M:%S}")
        s.add(log)
        await s.commit()
        await s.refresh(log)
        print("inserted ChatLog:", log.id, log.channel_user_id, log.message)

        rows = (await s.execute(
            select(ChatLog).where(ChatLog.channel_user_id==test_uid).order_by(ChatLog.id.desc()).limit(3)
        )).scalars().all()
        print("recent logs:")
        for r in rows:
            print(" -", r.id, r.role, r.message, r.created_at)

if __name__ == "__main__":
    asyncio.run(main())
