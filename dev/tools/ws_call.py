"""Send WebSocket commands to the dev HA. Usage: TOKEN=... python ws_call.py '<json>' ['<json>' ...]

A message may reference the previous result with "$profile" (first profile_id).
"""
import asyncio
import json
import os
import sys

import aiohttp


async def main(messages):
    async with aiohttp.ClientSession() as s, s.ws_connect("ws://localhost:8123/api/websocket") as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": os.environ["TOKEN"]})
        await ws.receive_json()
        profile = None
        for msg_id, raw in enumerate(messages, start=1):
            msg = json.loads(raw.replace("$profile", profile or ""))
            await ws.send_json({"id": msg_id, **msg})
            reply = await ws.receive_json()
            if msg["type"].endswith("/subscribe"):
                reply = [reply, await ws.receive_json()]
            print(json.dumps(reply, ensure_ascii=False, indent=1))
            result = reply.get("result") if isinstance(reply, dict) else None
            if isinstance(result, dict) and result.get("profiles"):
                profile = result["profiles"][0]["profile_id"]

asyncio.run(main(sys.argv[1:]))
