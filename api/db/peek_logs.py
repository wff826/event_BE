# api/db/peek_logs.py
import asyncio
from sqlalchemy import text
from api.db.session import get_session

async def main():
    async with get_session() as session:
        row = (await session.execute(text("SELECT DATABASE(), USER()"))).first()
        print("DB:", tuple(row) if row else None)

        tables = await session.execute(text("SHOW TABLES"))
        print("TABLES:", [r[0] for r in tables.fetchall()])

        q = """
        SELECT
          iq.id,
          iq.`user` AS user_id,
          COALESCE(CONCAT(u.f_name, ' ', COALESCE(u.l_name, '')), '(noname)') AS name,
          LEFT(iq.content, 120) AS content,
          iq.responded,
          iq.created_at
        FROM inquery AS iq
        LEFT JOIN `user` AS u ON u.id = iq.`user`
        ORDER BY iq.id DESC
        LIMIT 10;
        """
        rows = (await session.execute(text(q))).mappings().all()

        print("\n=== Recent Inqueries ===")
        for r in rows:
            responded = "✅" if r["responded"] else "⏳"
            print(f"[{r['id']}] {r['created_at']} {responded} "
                  f"{r['user_id']} ({r['name']}): {r['content']}")

if __name__ == "__main__":
    asyncio.run(main())
