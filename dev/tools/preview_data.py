"""Build panel preview data from a real HA install (read-only).

Usage (repo root, inside the HA image):
    HA_URL=... HA_TOKEN=... python dev/tools/preview_data.py <out.json> [trend_days]

Resolves catalog metrics by translation_key exactly like the integration,
reads current states, state history and hourly/daily statistics, and runs the
integration's own normalization and chart extraction. The output contains real
personal data: write it under dev/raw/ (gitignored) only.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
import sys

import aiohttp

sys.path.insert(0, os.getcwd())
from homeassistant.core import State  # noqa: E402
from homeassistant.util import dt as dt_util  # noqa: E402

from custom_components.garmin_dashboard.charts import (  # noqa: E402
    CHARTS,
    _canonical_unit,
    _converter,
    change_points,
    daily_range,
    downsample,
    history_points,
    last_per_day,
)
from custom_components.garmin_dashboard.discovery import Resolution  # noqa: E402
from custom_components.garmin_dashboard.normalization import build_metric  # noqa: E402
from custom_components.garmin_dashboard.providers.cyberjunky import CATALOG, sport_of  # noqa: E402


class Ws:
    def __init__(self, ws):
        self.ws, self.n = ws, 0

    async def call(self, **msg):
        self.n += 1
        await self.ws.send_json({"id": self.n, **msg})
        while True:
            reply = await self.ws.receive_json()
            if reply.get("id") == self.n:
                return reply["result"]


def _state(raw: dict) -> State:
    return State(raw["entity_id"], raw["state"], raw["attributes"],
                 last_changed=dt_util.parse_datetime(raw["last_changed"]),
                 last_updated=dt_util.parse_datetime(raw["last_updated"]))


async def main(out: str, trend_days: int) -> None:
    url = os.environ["HA_URL"].rstrip("/").replace("http", "ws", 1) + "/api/websocket"
    async with aiohttp.ClientSession() as session, session.ws_connect(url) as raw_ws:
        await raw_ws.receive_json()
        await raw_ws.send_json({"type": "auth", "access_token": os.environ["HA_TOKEN"]})
        await raw_ws.receive_json()
        ws = Ws(raw_ws)
        entry_id = (await ws.call(type="config_entries/get", domain="garmin_connect"))[0]["entry_id"]
        registry = [e for e in await ws.call(type="config/entity_registry/list")
                    if e.get("config_entry_id") == entry_id and e["unique_id"].startswith(entry_id + "_")]
        states = {s["entity_id"]: s for s in await ws.call(type="get_states")}
        config = await ws.call(type="get_config")

        entity_of: dict[str, str] = {}
        for spec in CATALOG:
            matches = [e for e in registry if e.get("translation_key") == spec.translation_key
                       and (spec.sport is None or sport_of(spec.translation_key, e["unique_id"], entry_id) == spec.sport)]
            if len(matches) == 1 and not matches[0].get("disabled_by"):
                entity_of[spec.key] = matches[0]["entity_id"]

        now = dt_util.utcnow()
        metrics = {}
        for spec in CATALOG:
            entity_id = entity_of.get(spec.key)
            resolution = Resolution("resolved", entity_id) if entity_id else Resolution("missing")
            state = _state(states[entity_id]) if entity_id in states else None
            metrics[spec.key] = build_metric(spec, resolution, state, now)

        charts = {}
        for chart in CHARTS:
            if chart.method == "intraday":
                start = now - timedelta(hours=24)
            elif chart.method == "cumulative_today":
                start = dt_util.start_of_local_day(dt_util.now().astimezone(dt_util.get_time_zone(config["time_zone"])))
            else:
                start = now - timedelta(days=trend_days)
            series = []
            for key in chart.metrics:
                entity_id = entity_of.get(key)
                if not entity_id:
                    continue
                unit = states.get(entity_id, {}).get("attributes", {}).get("unit_of_measurement")
                convert = _converter(key, unit)
                entry = {"metric": key, "kind": next(s.kind for s in CATALOG if s.key == key),
                         "unit": _canonical_unit(key, unit)}
                if chart.method == "current":
                    st = states.get(entity_id)
                    entry["points"] = [] if st is None else [
                        (int(dt_util.parse_datetime(st["last_changed"]).timestamp() * 1000), convert(st["state"]))]
                elif chart.method in ("intraday", "cumulative_today"):
                    hist = await ws.call(type="history/history_during_period", start_time=start.isoformat(),
                                         entity_ids=[entity_id], minimal_response=True, no_attributes=True,
                                         significant_changes_only=False)
                    items = [{"state": h["s"], "last_changed": datetime.fromtimestamp(h["lu"], timezone.utc).isoformat()}
                             for h in hist.get(entity_id, [])]
                    entry["points"] = downsample(history_points(items, convert))
                else:
                    period = "day" if chart.method == "daily_range" else "hour"
                    rows = (await ws.call(type="recorder/statistics_during_period", start_time=start.isoformat(),
                                          statistic_ids=[entity_id], period=period,
                                          types=["min", "max", "mean"])).get(entity_id, [])
                    rows = [{**r, "start": r["start"] / 1000} for r in rows]
                    if chart.method == "daily_range":
                        entry["ranges"] = daily_range(rows, convert)
                    else:
                        points = change_points(rows, convert, zero_is_placeholder=chart.zero_is_placeholder)
                        entry["points"] = downsample(last_per_day(points) if chart.one_per_day else points)
                series.append(entry)
            payload = {"chart_id": chart.id, "group": chart.group, "form": chart.form, "method": chart.method,
                       "per_day": chart.one_per_day,
                       "range_days": 1 if chart.group == "today" else trend_days,
                       "start": start.isoformat(), "end": now.isoformat(), "series": series}
            if chart.goal_metric:
                goal = metrics.get(chart.goal_metric)
                payload["goal"] = goal["value"] if goal and goal["status"] == "available" else None
            charts[chart.id] = payload

    snapshot = {
        "schema_version": 1, "profile_id": "preview", "display_name": "Garmin", "revision": 1,
        "source_status": "ready", "source_synced_at": None, "metrics": metrics, "gear": [],
        "activities": [], "capabilities": ["movement", "recovery", "training"],
    }
    with open(out, "w") as f:
        json.dump({"snapshot": snapshot, "charts": charts,
                   "unit_length": config["unit_system"]["length"]}, f, ensure_ascii=False)
    print(f"wrote {out}: {len(metrics)} metrics, {len(charts)} charts")


asyncio.run(main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 30))
