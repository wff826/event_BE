# api/scripts/check_auth.py
import os, asyncio, httpx
from dotenv import load_dotenv
load_dotenv()

BASE = os.getenv("CHANNELTALK_API_BASE", "https://api.channel.io/open/v5")
HEADERS = {
    "x-access-key": os.getenv("CHANNELTALK_ACCESS_KEY", ""),
    "x-access-secret": os.getenv("CHANNELTALK_ACCESS_SECRET", ""),
}

async def main():
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{BASE}/user-chats", headers=HEADERS, params={"state":"opened","sortOrder":"desc","limit":1})
        print("status:", r.status_code)
        print("body:", r.text)

if __name__ == "__main__":
    asyncio.run(main())
