"""Apply the chart extraction rules to real hourly statistics (read-only).

Usage: HA_URL=... HA_TOKEN=... python change_points_probe.py <days> <statistic_id> [...]
Run from the repo root inside the HA image so `custom_components` imports.
Prints counts and day coverage only.
"""
import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
import os
import sys

import aiohttp

sys.path.insert(0, os.getcwd())
from custom_components.garmin_dashboard.charts import change_points  # noqa: E402


async def main(days, ids):
    url = os.environ["HA_URL"].rstrip("/").replace("http", "ws", 1) + "/api/websocket"
    start = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    async with aiohttp.ClientSession() as s, s.ws_connect(url) as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": os.environ["HA_TOKEN"]})
        await ws.receive_json()
        await ws.send_json({"id": 1, "type": "recorder/statistics_during_period", "start_time": start,
                            "statistic_ids": ids, "period": "hour", "types": ["min", "max", "mean"]})
        rows = (await ws.receive_json())["result"]
    for sid in ids:
        data = [{**r, "start": r["start"] / 1000} for r in rows.get(sid, [])]
        pts = change_points(data, float)
        values = [p for p in pts if p[1] is not None]
        per_day = Counter(datetime.fromtimestamp(p[0] / 1000).date() for p in values)
        multi = sum(1 for c in per_day.values() if c > 1)
        transitions = sum(1 for r in data if r.get("min") is not None and r["min"] != r["max"])
        print(f"{sid:48} hours={len(data):5} points={len(values):4} gaps={len(pts) - len(values):2} "
              f"days_with_point={len(per_day):3} days_with_>1={multi:3} skipped_transition_hours={transitions}")


asyncio.run(main(int(sys.argv[1]), sys.argv[2:]))
