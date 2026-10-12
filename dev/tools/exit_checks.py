"""Phase 0 exit checks against the dev HA (rename, admin-only, reload).

Usage: TOKEN=<admin token> USER_TOKEN=<non-admin token> python exit_checks.py
Restores every entity ID it renames.
"""

import asyncio
import json
import os

import aiohttp

URL = "ws://localhost:8123/api/websocket"


class Ws:
    def __init__(self, ws):
        self.ws, self.n = ws, 0

    async def call(self, **msg):
        self.n += 1
        await self.ws.send_json({"id": self.n, **msg})
        while True:
            reply = await self.ws.receive_json()
            if reply.get("id") == self.n and reply.get("type") == "result":
                return reply


async def connect(session, token):
    ws = await session.ws_connect(URL)
    await ws.receive_json()
    await ws.send_json({"type": "auth", "access_token": token})
    assert (await ws.receive_json())["type"] == "auth_ok"
    return Ws(ws)


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    return ok


async def main():
    results = []
    async with aiohttp.ClientSession() as session:
        admin = await connect(session, os.environ["TOKEN"])
        profiles = (await admin.call(type="garmin_dashboard/profiles"))["result"]["profiles"]
        pid = profiles[0]["profile_id"]
        before = (await admin.call(type="garmin_dashboard/snapshot", profile_id=pid))["result"]

        # Rename: entity IDs change, mapping must follow via the registry.
        registry = (await admin.call(type="config/entity_registry/list"))["result"]
        steps = next(
            e["entity_id"]
            for e in registry
            if e.get("platform") == "garmin_connect" and e.get("translation_key") == "total_steps"
        )
        ftp = next(
            e["entity_id"]
            for e in registry
            if e.get("platform") == "garmin_connect"
            and e.get("translation_key") == "functional_threshold_power"
            and e["unique_id"].endswith("_ftp_cycling")
        )
        renames = {steps: "sensor.my_renamed_steps", ftp: "sensor.bike_power_renamed"}
        try:
            for old, new in renames.items():
                r = await admin.call(type="config/entity_registry/update", entity_id=old, new_entity_id=new)
                assert r["success"], r
            await asyncio.sleep(1)
            after = (await admin.call(type="garmin_dashboard/snapshot", profile_id=pid))["result"]
            for key in ("steps", "ftp_cycling"):
                results.append(
                    check(
                        f"rename keeps {key}",
                        after["metrics"][key]["status"] == "available"
                        and after["metrics"][key]["value"] == before["metrics"][key]["value"],
                    )
                )
        finally:
            for old, new in renames.items():
                await admin.call(type="config/entity_registry/update", entity_id=new, new_entity_id=old)

        # Admin-only: panel and every custom command.
        user = await connect(session, os.environ["USER_TOKEN"])
        for cmd in ("profiles", "snapshot", "subscribe"):
            extra = {} if cmd == "profiles" else {"profile_id": pid}
            r = await user.call(type=f"garmin_dashboard/{cmd}", **extra)
            results.append(
                check(
                    f"non-admin denied: {cmd}",
                    not r["success"] and r["error"]["code"] == "unauthorized",
                    json.dumps(r.get("error")),
                )
            )
        panels = (await user.call(type="get_panels"))["result"]
        results.append(check("non-admin panel list has no garmin", "garmin" not in panels))
        panels = (await admin.call(type="get_panels"))["result"]
        results.append(
            check("admin panel registered with require_admin", panels.get("garmin", {}).get("require_admin") is True)
        )

        # Reload: single panel, profiles still served.
        entry = [e for e in (await admin.call(type="config_entries/get", domain="garmin_dashboard"))["result"]][0]
        async with session.post(
            f"http://localhost:8123/api/config/config_entries/entry/{entry['entry_id']}/reload",
            headers={"Authorization": f"Bearer {os.environ['TOKEN']}"},
        ) as resp:
            results.append(check("reload request ok", resp.status == 200))
        async with session.post(
            f"http://localhost:8123/api/config/config_entries/entry/{entry['entry_id']}/reload",
            headers={"Authorization": f"Bearer {os.environ['TOKEN']}"},
        ) as resp:
            results.append(check("second reload ok", resp.status == 200))
        panels = (await admin.call(type="get_panels"))["result"]
        results.append(check("one garmin panel after reloads", list(panels).count("garmin") == 1))
        r = await admin.call(type="garmin_dashboard/profiles")
        results.append(check("profiles served after reload", r["success"] and len(r["result"]["profiles"]) == 1))

    print(f"\n{sum(results)}/{len(results)} passed")


asyncio.run(main())
