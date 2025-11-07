import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

# send_message_to_userchat 가져오기
from api.clients.channeltalk_client import send_message_to_userchat

TEST_USER_CHAT_ID = os.getenv("TEST_USER_CHAT_ID", "")

async def main():
    if not TEST_USER_CHAT_ID:
        print("❗ TEST_USER_CHAT_ID 환경변수를 설정하거나 코드에 직접 넣으세요.")
        return

    res = await send_message_to_userchat(
        user_chat_id=TEST_USER_CHAT_ID,
        text="✅ 연결 테스트 완료!",
    )
    print("Result:", res)

if __name__ == "__main__":
    asyncio.run(main())
