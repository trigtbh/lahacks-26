import httpx
import asyncio

async def test():
    async with httpx.AsyncClient(follow_redirects=False) as client:
        r = await client.get("http://localhost:8000/auth/slack?user_id=akshai")
        print("Status:", r.status_code)
        print("Location:", r.headers.get("location"))

asyncio.run(test())
