"""Turn source states into the dashboard's own metric model."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import math
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import State
from homeassistant.util import dt as dt_util

from .discovery import Resolution
from .providers.cyberjunky import FreshnessClass, MetricSpec

_DISTANCE_TO_M = {"m": 1.0, "km": 1000.0, "mi": 1609.344, "ft": 0.3048, "yd": 0.9144, "cm": 0.01}
_DURATION_TO_S = {"s": 1.0, "min": 60.0, "h": 3600.0, "d": 86400.0}
# Units each numeric kind accepts as-is; anything else is "invalid", not guessed.
_PASSTHROUGH_UNITS: dict[str, set[str | None]] = {
    "count": {"steps", None},
    "energy": {"kcal"},
    "percent": {"%", None},
    "score": {None, "%"},
    "heart_rate": {"bpm"},
    "power": {"W"},
    "vo2max": {"mL/(kg·min)", None},
    "hrv": {"ms"},
    "level": {"level", None},
    "power_ratio": {"W/kg"},
}
_STALE_AFTER: dict[FreshnessClass, timedelta] = {
    "intraday": timedelta(hours=6),
    "daily": timedelta(hours=24),
}


def _iso(value: datetime | None) -> str | None:
    return dt_util.as_utc(value).isoformat() if value else None


def _parse_number(raw: str) -> float | None:
    try:
        number = float(raw)
    except TypeError, ValueError:
        return None
    return number if math.isfinite(number) else None


def normalize_value(spec: MetricSpec, raw: str, unit: str | None) -> tuple[Any, str | None] | None:
    """Return (value, canonical unit), or None when the value breaks the contract."""
    if spec.kind == "category":
        return (raw, None) if raw.strip() else None
    number = _parse_number(raw)
    if number is None or number < 0:
        return None
    if spec.kind == "distance":
        factor = _DISTANCE_TO_M.get(unit or "")
        return (number * factor, "m") if factor else None
    if spec.kind == "duration":
        factor = _DURATION_TO_S.get(unit or "")
        return (number * factor, "s") if factor else None
    if unit not in _PASSTHROUGH_UNITS[spec.kind]:
        return None
    if spec.kind in ("percent", "score") and number > 100:
        return None
    return (int(number) if number.is_integer() else number, unit)


def _source_date(spec: MetricSpec, state: State) -> date | None:
    if spec.date_attribute is None:
        return None
    raw = state.attributes.get(spec.date_attribute)
    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _freshness(spec: MetricSpec, state: State, source_date: date | None, now: datetime) -> str:
    today = dt_util.as_local(now).date()
    if spec.freshness in ("slow", "event"):
        return "fresh"
    if spec.freshness == "nightly":
        if source_date is None:
            return "unknown"
        return "fresh" if source_date >= today - timedelta(days=1) else "stale"
    if spec.freshness == "daily" and source_date is not None:
        return "fresh" if source_date >= today else "stale"
    return "fresh" if now - state.last_updated <= _STALE_AFTER[spec.freshness] else "stale"


def build_metric(spec: MetricSpec, resolution: Resolution, state: State | None, now: datetime) -> dict[str, Any]:
    """Build one Metric from a resolution and its current state."""
    metric: dict[str, Any] = {
        "key": spec.key,
        "section": spec.section,
        "kind": spec.kind,
        "value": None,
        "unit": None,
        "status": "missing",
        "freshness": "unknown",
        "observed_at": _iso(now),
        "ha_updated_at": None,
        "measured_at": None,
        "source_date": None,
    }
    if resolution.status != "resolved":
        metric["status"] = resolution.status
        return metric
    # A restored state means the source no longer provides this entity.
    if state is None or state.attributes.get("restored"):
        return metric

    metric["ha_updated_at"] = _iso(state.last_updated)
    if state.state == STATE_UNAVAILABLE:
        metric["status"] = "unavailable"
        return metric
    raw = state.state if spec.value_attribute is None else state.attributes.get(spec.value_attribute)
    if raw is None or raw == STATE_UNKNOWN:
        metric["status"] = "unknown"
        return metric

    normalized = normalize_value(spec, str(raw), state.attributes.get("unit_of_measurement"))
    if normalized is None:
        metric["status"] = "invalid"
        return metric

    source_date = _source_date(spec, state)
    metric["value"], metric["unit"] = normalized
    metric["status"] = "available"
    metric["source_date"] = source_date.isoformat() if source_date else None
    metric["freshness"] = _freshness(spec, state, source_date, now)
    return metric
