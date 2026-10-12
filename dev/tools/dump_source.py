"""Read-only dump of the garmin_connect integration's registry/state shape.

Usage: python dump_source.py <out_dir>   (needs HA_URL and HA_TOKEN env vars)

Only issues read commands. Output contains real personal data; keep it in a
gitignored directory and derive anonymized fixtures from it.
"""

import asyncio
import json
import os
import sys

import aiohttp

SOURCE_DOMAIN = "garmin_connect"


class Client:
    def __init__(self, ws):
        self.ws = ws
        self.msg_id = 0

    async def call(self, payload):
        self.msg_id += 1
        await self.ws.send_json({"id": self.msg_id, **payload})
        while True:
            msg = await self.ws.receive_json()
            if msg.get("id") == self.msg_id:
                if not msg.get("success", False):
                    return {"_error": msg.get("error")}
                return msg["result"]


async def main(out_dir):
    url = os.environ["HA_URL"].rstrip("/").replace("http", "ws", 1) + "/api/websocket"
    async with aiohttp.ClientSession() as session, session.ws_connect(url) as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": os.environ["HA_TOKEN"]})
        auth = await ws.receive_json()
        if auth["type"] != "auth_ok":
            sys.exit(f"auth failed: {auth}")
        c = Client(ws)

        entries = await c.call({"type": "config_entries/get", "domain": SOURCE_DOMAIN})
        entry_ids = {e["entry_id"] for e in entries}
        registry = await c.call({"type": "config/entity_registry/list"})
        source_entities = [e for e in registry if e.get("config_entry_id") in entry_ids]
        full = await c.call(
            {
                "type": "config/entity_registry/get_entries",
                "entity_ids": [e["entity_id"] for e in source_entities],
            }
        )
        devices = await c.call({"type": "config/device_registry/list"})
        source_devices = [d for d in devices if entry_ids & set(d.get("config_entries", []))]
        states = await c.call({"type": "get_states"})
        ids = {e["entity_id"] for e in source_entities}
        source_states = [s for s in states if s["entity_id"] in ids]
        manifest = await c.call({"type": "manifest/get", "integration": SOURCE_DOMAIN})
        stats = await c.call({"type": "recorder/list_statistic_ids"})
        source_stats = [s for s in stats if s.get("statistic_id") in ids] if isinstance(stats, list) else stats
        core = await c.call({"type": "get_config"})

    dump = {
        "ha_version": core.get("version"),
        "unit_system": core.get("unit_system"),
        "time_zone": core.get("time_zone"),
        "manifest": manifest,
        "config_entries": entries,
        "devices": source_devices,
        "entity_registry": full,
        "states": source_states,
        "statistic_ids": source_stats,
    }
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "source_dump.json")
    with open(path, "w") as f:
        json.dump(dump, f, indent=2, ensure_ascii=False, default=str)
    print(
        f"wrote {path}: {len(entries)} entries, {len(source_entities)} entities, "
        f"{len(source_states)} states, {len(source_devices)} devices"
    )


asyncio.run(main(sys.argv[1]))
