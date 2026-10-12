"""Create a long-lived token on the dev HA. Usage: AT=<short-lived token> python create_token.py"""

import asyncio
import os

import aiohttp


async def main():
    async with aiohttp.ClientSession() as s, s.ws_connect("ws://localhost:8123/api/websocket") as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": os.environ["AT"]})
        await ws.receive_json()
        await ws.send_json(
            {
                "id": 1,
                "type": "auth/long_lived_access_token",
                "client_name": "garmin-dashboard-dev-tools",
                "lifespan": 3650,
            }
        )
        print((await ws.receive_json())["result"])


asyncio.run(main())
