"""Training calendar: today's and the next workout, and the goal race.

Field shapes come from ha_garmin 0.1.49 (`_trim_calendar_workout_item`,
`_trim_goal_event`): workouts carry `date` (YYYY-MM-DD), `title` and
`sportTypeKey`; the goal event carries `eventName`, `date`, `targetDistance`
with `targetDistanceUnit`, and race-time projections in seconds. Workout
`duration`/`distance` units are not documented, so they are not shown.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
import math
from typing import Any

MAX_UPCOMING = 5
_DISTANCE_UNIT_TO_M = {
    "meter": 1.0,
    "meters": 1.0,
    "m": 1.0,
    "kilometer": 1000.0,
    "kilometers": 1000.0,
    "km": 1000.0,
    "mile": 1609.344,
    "miles": 1609.344,
    "mi": 1609.344,
}


def _text(value: Any, limit: int = 120) -> str | None:
    return value.strip()[:limit] or None if isinstance(value, str) else None


def _date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _positive(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value > 0 else None


def workout(raw: Any, today: date) -> dict[str, Any] | None:
    """One scheduled workout from today on, or None."""
    if not isinstance(raw, Mapping):
        return None
    when = _date(raw.get("date"))
    title = _text(raw.get("title"))
    if when is None or title is None or when < today:
        return None
    return {"title": title, "sport": _text(raw.get("sportTypeKey"), 64), "date": when.isoformat()}


def goal_event(raw: Any, today: date) -> dict[str, Any] | None:
    """The goal race with a countdown, or None when absent or already past."""
    if not isinstance(raw, Mapping):
        return None
    when = _date(raw.get("date"))
    name = _text(raw.get("eventName"))
    if when is None or name is None or when < today:
        return None
    distance = _positive(raw.get("targetDistance"))
    unit = raw.get("targetDistanceUnit")
    factor = _DISTANCE_UNIT_TO_M.get(unit.strip().lower()) if isinstance(unit, str) else None
    return {
        "name": name,
        "date": when.isoformat(),
        "days_until": (when - today).days,
        # Unknown distance units are dropped, never guessed.
        "distance_meters": distance * factor if distance is not None and factor else None,
        "predicted_seconds": _positive(raw.get("predictedRaceTimeDurationSeconds")),
    }


def training_plan(today_attrs: Any, next_attrs: Any, goal_attrs: Any, today: date) -> dict[str, Any] | None:
    """Combine the three source sensors; None when there is nothing scheduled."""
    today_workout = workout(today_attrs, today)
    if today_workout is not None and today_workout["date"] != today.isoformat():
        today_workout = None
    upcoming_raw = next_attrs.get("upcoming") if isinstance(next_attrs, Mapping) else None
    upcoming = [w for w in (workout(item, today) for item in (upcoming_raw or [])[:20]) if w is not None]
    upcoming.sort(key=lambda w: w["date"])
    next_workout = workout(next_attrs, today)
    if next_workout is not None and today_workout is not None and next_workout == today_workout:
        next_workout = next((w for w in upcoming if w != today_workout), None)
    plan = {
        "today": today_workout,
        "next": next_workout,
        "upcoming": [w for w in upcoming if w not in (today_workout, next_workout)][:MAX_UPCOMING],
        "goal": goal_event(goal_attrs, today),
    }
    if not (plan["today"] or plan["next"] or plan["upcoming"] or plan["goal"]):
        return None
    return plan
