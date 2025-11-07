# api/scripts/inspect_schema.py
import asyncio
import logging
import os
from dotenv import load_dotenv
from sqlalchemy import text, inspect
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import create_async_engine

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")

DB_URL = os.getenv("DB_URL")
if not DB_URL:
    DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
    DB_NAME = os.getenv("DB_NAME", "channel")
    DB_USER = os.getenv("DB_USER", "channel")
    DB_PASS = os.getenv("DB_PASS", "")
    DB_URL = f"mysql+asyncmy://{DB_USER}:{DB_PASS}@{DB_HOST}:3306/{DB_NAME}?charset=utf8mb4"

async def main():
    url = make_url(DB_URL)
    logging.info(f"== TARGET == dialect={url.get_backend_name()} host={url.host} db={url.database} user={url.username}")

    engine = create_async_engine(DB_URL, future=True)

    async with engine.begin() as conn:
        # 현재 데이터베이스 / 호스트
        row = (await conn.execute(text("SELECT @@hostname AS host, DATABASE() AS db"))).one()
        logging.info(f"== SESSION == host={row.host} db={row.db}")

        # 동기 인스펙터로 안전 실행
        def reflect(sync_conn):
            insp = inspect(sync_conn)
            data = {}
            data["tables"] = insp.get_table_names()
            per_table = {}
            for t in data["tables"]:
                cols = insp.get_columns(t)
                pk = insp.get_pk_constraint(t)
                idx = insp.get_indexes(t)
                fks = insp.get_foreign_keys(t)
                per_table[t] = {
                    "columns": [
                        {
                            "name": c["name"],
                            "type": str(c["type"]),
                            "nullable": c.get("nullable"),
                            "default": c.get("default"),
                        } for c in cols
                    ],
                    "primary_key": pk,
                    "indexes": idx,
                    "foreign_keys": fks,
                }
            return data, per_table

        meta, per_table = await conn.run_sync(reflect)

        logging.info("== TABLES ==")
        for t in meta["tables"]:
            logging.info(f"- {t}")

        # SHOW CREATE TABLE & COUNT
        for t in meta["tables"]:
            logging.info(f"\n== {t} :: SHOW CREATE TABLE ==")
            crt = await conn.execute(text(f"SHOW CREATE TABLE `{t}`"))
            _, ddl = crt.fetchone()
            logging.info(ddl)

            logging.info(f"== {t} :: COLUMNS / PK / INDEX / FK ==")
            logging.info(per_table[t])

            cnt = (await conn.execute(text(f"SELECT COUNT(*) AS c FROM `{t}`"))).scalar_one()
            logging.info(f"== {t} :: COUNT == {cnt}")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
