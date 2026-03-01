import asyncio
import websockets
import random
import sys

TARGET = sys.argv[1]
CLIENTS = int(sys.argv[2])
RECONNECT_DELAY = 1


async def client_worker():
    while True:
        try:
            async with websockets.connect(TARGET) as ws:
                while True:
                    await ws.send("ping")
                    await asyncio.sleep(5)
        except:
            await asyncio.sleep(random.uniform(0, RECONNECT_DELAY))


async def main():
    tasks = [client_worker() for _ in range(CLIENTS)]
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())