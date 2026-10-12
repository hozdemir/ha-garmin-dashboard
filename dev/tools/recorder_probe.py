"""Time the recorder queries the dashboard's charts make, against a real HA (read-only).

Usage: HA_URL=... HA_TOKEN=... python recorder_probe.py [samples]
Uses the same calls as the chart service: hourly statistics for trends and
24 h state history for "today" charts. Prints timings only.
"""

import asyncio
from datetime import UTC, datetime, timedelta
import os
import statistics
import sys
import time

import aiohttp

QUERIES = [
    ("hourly stats, 30 d", "stats", "sensor.resting_heart_rate", 30),
    ("hourly stats, 90 d", "stats", "sensor.resting_heart_rate", 90),
    ("daily stats, 90 d", "daily", "sensor.body_battery_most_recent", 90),
    ("state history, 24 h", "history", "sensor.body_battery_most_recent", 1),
]


async def main(samples):
    url = os.environ["HA_URL"].rstrip("/").replace("http", "ws", 1) + "/api/websocket"
    async with aiohttp.ClientSession() as session, session.ws_connect(url, max_msg_size=0) as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": os.environ["HA_TOKEN"]})
        await ws.receive_json()
        n = 0
        for name, kind, entity, days in QUERIES:
            times = []
            for _ in range(samples):
                n += 1
                start = (datetime.now(UTC) - timedelta(days=days)).isoformat()
                if kind == "history":
                    msg = {
                        "type": "history/history_during_period",
                        "start_time": start,
                        "entity_ids": [entity],
                        "minimal_response": True,
                        "no_attributes": True,
                        "significant_changes_only": False,
                    }
                else:
                    msg = {
                        "type": "recorder/statistics_during_period",
                        "start_time": start,
                        "statistic_ids": [entity],
                        "period": "hour" if kind == "stats" else "day",
                        "types": ["min", "max", "mean"],
                    }
                t0 = time.perf_counter()
                await ws.send_json({"id": n, **msg})
                while (reply := await ws.receive_json()).get("id") != n:
                    pass
                times.append((time.perf_counter() - t0) * 1000)
                rows = len(next(iter(reply["result"].values()), []))
            times.sort()
            p95 = times[max(0, round(0.95 * len(times)) - 1)]
            print(f"{name:22} rows={rows:5}  median={statistics.median(times):6.1f} ms  p95={p95:6.1f} ms")


asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 20))
