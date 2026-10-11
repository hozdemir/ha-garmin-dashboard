"""Read-only probe of long-term statistics coverage for candidate chart metrics.

Usage: HA_URL=... HA_TOKEN=... python stats_probe.py <out.json> <days> <statistic_id> [...]
Writes raw daily statistics to <out.json> (keep it in gitignored dev/raw/) and
prints coverage only: days with data, first/last day, and day-to-day changes.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
import sys

import aiohttp


async def main(out, days, ids):
    url = os.environ["HA_URL"].rstrip("/").replace("http", "ws", 1) + "/api/websocket"
    start = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    async with aiohttp.ClientSession() as s, s.ws_connect(url) as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": os.environ["HA_TOKEN"]})
        await ws.receive_json()
        await ws.send_json({"id": 1, "type": "recorder/statistics_during_period", "start_time": start,
                            "statistic_ids": ids, "period": "day", "types": ["mean", "min", "max", "state", "sum"]})
        daily = (await ws.receive_json())["result"]
        await ws.send_json({"id": 2, "type": "history/history_during_period",
                            "start_time": (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(),
                            "entity_ids": ids, "minimal_response": True, "no_attributes": True})
        history = (await ws.receive_json())["result"]
    json.dump({"daily": daily, "history": history}, open(out, "w"), indent=1)
    for sid in ids:
        rows = daily.get(sid, [])
        changes = sum(1 for a, b in zip(rows, rows[1:]) if a.get("max") != b.get("max"))
        first = datetime.fromtimestamp(rows[0]["start"] / 1000).date() if rows else None
        last = datetime.fromtimestamp(rows[-1]["start"] / 1000).date() if rows else None
        hist = len(history.get(sid, []))
        print(f"{sid:58} days={len(rows):3} {first}..{last} max-changes={changes:3} history-points={hist}")


asyncio.run(main(sys.argv[1], int(sys.argv[2]), sys.argv[3:]))
