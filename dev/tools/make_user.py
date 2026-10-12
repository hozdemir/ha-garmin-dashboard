"""Create a non-admin user 'viewer' on the dev HA and print a long-lived token for it."""

import asyncio
import os
import secrets

import aiohttp

B = "http://localhost:8123"


async def main():
    pw = secrets.token_urlsafe(16)
    async with aiohttp.ClientSession() as s:
        ws = await s.ws_connect(f"{B}/api/websocket")
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": os.environ["TOKEN"]})
        await ws.receive_json()
        await ws.send_json(
            {"id": 1, "type": "config/auth/create", "name": "Viewer", "group_ids": ["system-users"], "local_only": True}
        )
        uid = (await ws.receive_json())["result"]["user"]["id"]
        await ws.send_json(
            {
                "id": 2,
                "type": "config/auth_provider/homeassistant/create",
                "user_id": uid,
                "username": "viewer",
                "password": pw,
            }
        )
        await ws.receive_json()
        await ws.close()
        r = await (
            await s.post(
                f"{B}/auth/login_flow",
                json={"client_id": f"{B}/", "handler": ["homeassistant", None], "redirect_uri": f"{B}/"},
            )
        ).json()
        r = await (
            await s.post(
                f"{B}/auth/login_flow/{r['flow_id']}", json={"client_id": f"{B}/", "username": "viewer", "password": pw}
            )
        ).json()
        tok = await (
            await s.post(
                f"{B}/auth/token", data={"grant_type": "authorization_code", "code": r["result"], "client_id": f"{B}/"}
            )
        ).json()
        ws = await s.ws_connect(f"{B}/api/websocket")
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": tok["access_token"]})
        await ws.receive_json()
        await ws.send_json(
            {"id": 1, "type": "auth/long_lived_access_token", "client_name": "viewer-tests", "lifespan": 3650}
        )
        print((await ws.receive_json())["result"])


asyncio.run(main())
