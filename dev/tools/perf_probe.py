"""Measure dashboard latency on a dev HA (run inside the HA container).

Usage: TOKEN=... python perf_probe.py [samples]

- first snapshot: new connection -> auth -> subscribe -> first snapshot event
- charts: each trend chart for 30 days, cache cleared via `refresh` (uncached) and repeated (cached)
- update: a state change on the steps sensor -> pushed snapshot (includes the 250 ms debounce).
  The sensor's original state is restored afterwards.
"""

import asyncio
import os
import statistics
import sys
import time

import aiohttp

WS = "ws://localhost:8123/api/websocket"
REST = "http://localhost:8123/api"
TREND_CHARTS = ["body_battery_range", "sleep_score", "sleep_duration", "resting_hr", "hrv", "vo2max"]


class Ws:
    def __init__(self, ws):
        self.ws, self.n = ws, 0

    async def send(self, **msg):
        self.n += 1
        await self.ws.send_json({"id": self.n, **msg})
        return self.n

    async def until(self, pred):
        while True:
            msg = await self.ws.receive_json()
            if pred(msg):
                return msg

    async def call(self, **msg):
        mid = await self.send(**msg)
        return await self.until(lambda m: m.get("id") == mid and m.get("type") == "result")


async def connect(session):
    ws = await session.ws_connect(WS)
    await ws.receive_json()
    await ws.send_json({"type": "auth", "access_token": os.environ["TOKEN"]})
    await ws.receive_json()
    return Ws(ws)


def p95(values):
    return sorted(values)[max(0, int(round(0.95 * len(values))) - 1)]


def report(name, ms):
    print(
        f"{name:34} n={len(ms):3}  median={statistics.median(ms):7.1f} ms  p95={p95(ms):7.1f} ms  max={max(ms):7.1f} ms"
    )


async def main(samples):
    headers = {"Authorization": f"Bearer {os.environ['TOKEN']}"}
    async with aiohttp.ClientSession() as session:
        first = []
        for _ in range(samples):
            t0 = time.perf_counter()
            c = await connect(session)
            pid = (await c.call(type="garmin_dashboard/profiles"))["result"]["profiles"][0]["profile_id"]
            mid = await c.send(type="garmin_dashboard/subscribe", profile_id=pid)
            await c.until(lambda m, mid=mid: m.get("id") == mid and m.get("type") == "event")
            first.append((time.perf_counter() - t0) * 1000)
            await c.ws.close()
        report("first snapshot (connect+subscribe)", first)

        c = await connect(session)
        pid = (await c.call(type="garmin_dashboard/profiles"))["result"]["profiles"][0]["profile_id"]
        uncached, cached = [], []
        for _ in range(max(3, samples // 5)):
            await c.call(type="garmin_dashboard/refresh", profile_id=pid)
            for chart in TREND_CHARTS:
                t0 = time.perf_counter()
                await c.call(type="garmin_dashboard/chart", profile_id=pid, chart_id=chart, range_days=30)
                uncached.append((time.perf_counter() - t0) * 1000)
                t0 = time.perf_counter()
                await c.call(type="garmin_dashboard/chart", profile_id=pid, chart_id=chart, range_days=30)
                cached.append((time.perf_counter() - t0) * 1000)
        report("trend chart 30 d (uncached)", uncached)
        report("trend chart 30 d (cached)", cached)

        registry = (await c.call(type="config/entity_registry/list"))["result"]
        steps = next(
            e["entity_id"]
            for e in registry
            if e.get("platform") == "garmin_connect" and e.get("translation_key") == "total_steps"
        )
        async with session.get(f"{REST}/states/{steps}", headers=headers) as r:
            original = await r.json()
        mid = await c.send(type="garmin_dashboard/subscribe", profile_id=pid)
        await c.until(lambda m: m.get("id") == mid and m.get("type") == "event")
        updates = []
        try:
            for i in range(samples):
                value = str(100000 + i)
                t0 = time.perf_counter()
                async with session.post(
                    f"{REST}/states/{steps}",
                    headers=headers,
                    json={"state": value, "attributes": original["attributes"]},
                ):
                    pass
                await c.until(
                    lambda m, v=int(value): (
                        m.get("id") == mid and m.get("type") == "event" and m["event"]["metrics"]["steps"]["value"] == v
                    )
                )
                updates.append((time.perf_counter() - t0) * 1000)
        finally:
            async with session.post(
                f"{REST}/states/{steps}",
                headers=headers,
                json={"state": original["state"], "attributes": original["attributes"]},
            ):
                pass
        report("state change -> pushed snapshot", updates)


asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 30))
