import asyncio
import websockets
import sys
import time

TARGET = sys.argv[1]
CLIENTS = int(sys.argv[2])
ACTIVE_DURATION = int(sys.argv[3]) if len(sys.argv) > 3 else 0

# Stagger the connection ramp-up over 90 seconds. 
# This ensures that as HPA scales up pods, new connections naturally load balance to them.
RAMP_UP_DURATION = 90
GLOBAL_START_TIME = time.time()

async def client_worker(client_index):
    # Linear stagger for each client to ramp up smoothly
    delay = (client_index / CLIENTS) * RAMP_UP_DURATION
    await asyncio.sleep(delay)

    while True:
        elapsed = time.time() - GLOBAL_START_TIME
        if ACTIVE_DURATION > 0 and elapsed > ACTIVE_DURATION:
            # If we are disconnected and trying to reconnect during IDLE phase, give up permanently.
            return

        try:
            async with websockets.connect(TARGET, ping_interval=None, ping_timeout=None) as ws:
                while True:
                    elapsed = time.time() - GLOBAL_START_TIME
                    if ACTIVE_DURATION > 0 and elapsed > ACTIVE_DURATION:
                        # --- IDLE PHASE ---
                        # Stop sending pings, keep connection open by consuming messages.
                        async for _ in ws:
                            pass
                        # If the server closes the connection during IDLE phase (e.g. pod terminated),
                        # we exit completely to show permanent connection loss.
                        return

                    # --- ACTIVE PHASE ---
                    await ws.send("ping")
                    await asyncio.sleep(5)

        except Exception:
            elapsed = time.time() - GLOBAL_START_TIME
            if ACTIVE_DURATION > 0 and elapsed > ACTIVE_DURATION:
                # Do not reconnect if an exception happened during IDLE phase
                return
            await asyncio.sleep(1)

async def main():
    tasks = [client_worker(i) for i in range(CLIENTS)]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())