import asyncio, websockets

async def main():
    url = "ws://localhost:8000/ws/bot-1"
    try:
        async with websockets.connect(url) as ws:
            print("WS CONNECTED OK:", url)
            await ws.send("ping")
            await asyncio.sleep(0.2)
    except Exception as e:
        print("WS FAILED:", type(e).__name__, str(e).replace('\n', ' '))

asyncio.run(main())
