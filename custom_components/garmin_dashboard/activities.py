"""Recent activities and the last synced route, normalized from source attributes.

Verified against source 3.0.19: `distance` is meters, `duration`/`movingDuration`
are seconds, `averageSpeed` is m/s (distance / duration / speed == 1.00),
`startTime` is ISO 8601 with offset. The list arrives oldest-first and the
sensor state is not the list length, so neither is relied on.

Coordinates and raw attribute dicts never leave this module except as a
validated, simplified route.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import math
from typing import Any

from homeassistant.util import dt as dt_util

MAX_ACTIVITIES = 50
MAX_ROUTE_INPUT_POINTS = 10_000
MAX_ROUTE_POINTS = 2_000
HR_ZONES = 5


def _number(value: Any, *, minimum: float = 0.0) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except TypeError, ValueError:
        return None
    if not math.isfinite(number) or number < minimum:
        return None
    return number


def _text(value: Any, limit: int = 200) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:limit] or None


def parse_aware_time(value: Any) -> datetime | None:
    """Live state attributes hold a datetime; JSON dumps hold an ISO string."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = dt_util.parse_datetime(value)
    else:
        return None
    if parsed is None or parsed.tzinfo is None:
        # A naive time cannot be placed on the timeline safely.
        return None
    return parsed


def normalize_activity(raw: Any) -> dict[str, Any] | None:
    """One activity, or None when it cannot be identified at all."""
    if not isinstance(raw, Mapping):
        return None
    started = parse_aware_time(raw.get("startTime"))
    activity_id = raw.get("activityId")
    if isinstance(activity_id, bool) or not isinstance(activity_id, (int, str)) or str(activity_id) == "":
        activity_id = None
    if activity_id is None and started is None:
        return None
    zones = [_number(raw.get(f"hrTimeInZone_{i}")) for i in range(1, HR_ZONES + 1)]
    return {
        # Without a source ID the start time is the key; collisions are reported in diagnostics.
        "id": str(activity_id) if activity_id is not None else f"start:{started.isoformat()}",
        "id_source": "source" if activity_id is not None else "start_time",
        "sport": _text(raw.get("activityType"), 64) or "other",
        "title": _text(raw.get("activityName")),
        "started_at": dt_util.as_utc(started).isoformat() if started else None,
        "duration_seconds": _number(raw.get("duration")),
        "moving_seconds": _number(raw.get("movingDuration")),
        "distance_meters": _number(raw.get("distance")),
        "average_speed_mps": _number(raw.get("averageSpeed")),
        "max_speed_mps": _number(raw.get("maxSpeed")),
        "average_heart_rate_bpm": _number(raw.get("averageHR"), minimum=1),
        "max_heart_rate_bpm": _number(raw.get("maxHR"), minimum=1),
        "average_power_w": _number(raw.get("avgPower")),
        "normalized_power_w": _number(raw.get("normPower")),
        "elevation_gain_m": _number(raw.get("elevationGain")),
        "calories_kcal": _number(raw.get("calories")),
        "aerobic_effect": _number(raw.get("aerobicTrainingEffect")),
        "anaerobic_effect": _number(raw.get("anaerobicTrainingEffect")),
        "training_load": _number(raw.get("activityTrainingLoad")),
        "hr_zone_seconds": zones if any(z is not None for z in zones) else None,
    }


def normalize_activities(raw_list: Any, latest: Any = None) -> dict[str, Any]:
    """Dedupe by ID, sort newest first, cap the list; report what was dropped."""
    items: list[Any] = list(raw_list) if isinstance(raw_list, list) else []
    if latest is not None:
        items.append(latest)
    by_id: dict[str, dict[str, Any]] = {}
    skipped = 0
    for raw in items:
        activity = normalize_activity(raw)
        if activity is None:
            skipped += 1
            continue
        by_id.setdefault(activity["id"], activity)
    ordered = sorted(
        by_id.values(),
        key=lambda a: (a["started_at"] or "", a["id"]),
        reverse=True,
    )
    return {
        "activities": ordered[:MAX_ACTIVITIES],
        "truncated": len(ordered) > MAX_ACTIVITIES,
        "skipped": skipped,
        "key_collisions_possible": any(a["id_source"] == "start_time" for a in ordered),
    }


def _valid_point(point: Any) -> tuple[float, float] | None:
    if not isinstance(point, Mapping):
        return None
    lat, lon = _number(point.get("lat"), minimum=-90), _number(point.get("lon"), minimum=-180)
    if lat is None or lon is None or lat > 90 or lon > 180:
        return None
    return (lat, lon)


def _simplify(points: list[tuple[float, float]], limit: int) -> list[tuple[float, float]]:
    """Evenly thin a track to `limit` points, always keeping both ends."""
    if len(points) <= limit:
        return points
    step = (len(points) - 1) / (limit - 1)
    return [points[round(i * step)] for i in range(limit)]


def normalize_route(attributes: Mapping[str, Any]) -> dict[str, Any] | None:
    """The last synced route as [lat, lon] pairs, or None when absent or unusable."""
    raw = attributes.get("polyline")
    if not isinstance(raw, list) or not raw:
        return None
    raw = raw[:MAX_ROUTE_INPUT_POINTS]
    points = [p for p in (_valid_point(item) for item in raw) if p is not None]
    if len(points) < 2:
        return None
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    simplified = _simplify(points, MAX_ROUTE_POINTS)
    return {
        "title": _text(attributes.get("activity_name")),
        "points": [[round(lat, 6), round(lon, 6)] for lat, lon in simplified],
        "bounds": [min(lats), min(lons), max(lats), max(lons)],
        "source_points": len(raw),
        "invalid_points": len(raw) - len(points),
        "simplified": len(simplified) < len(points),
    }
