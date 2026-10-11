"""Chart catalog and series extraction from Home Assistant's own records.

Each series type is read with the one method that does not misstate it:

- ``intraday``: raw state history over a short window (continuous measurements).
- ``cumulative_today``: state history since local midnight (daily-reset totals).
- ``change_points``: hourly statistics, emitting a point only when a stable
  value changes. One-value-per-measurement metrics (sleep score, resting HR,
  VO2max...) stay constant for a day or more in HA; daily mean/max would count
  one night twice.
- ``daily_range``: per-HA-day min/max of a continuous measurement.

Multi-day totals of daily-reset counters (steps per day) are deliberately not
offered: the counter's end-of-day value does not match the real daily total.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from typing import Any, Literal

from homeassistant.components.recorder import get_instance, history, statistics
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util

from .normalization import normalize_value
from .providers.cyberjunky import CATALOG_BY_KEY

Method = Literal["intraday", "cumulative_today", "change_points", "daily_range", "current"]
Group = Literal["today", "trends"]
Form = Literal["line", "area", "step", "columns", "dots", "range_columns", "stacked_bar"]

TREND_RANGES: tuple[int, ...] = (7, 30, 90)
DEFAULT_TREND_RANGE = 30
INTRADAY_WINDOW = timedelta(hours=24)
MAX_POINTS = 1000
CACHE_SECONDS = 300
# A hole in the records longer than this is drawn as a gap, not bridged by a line.
GAP_MS = 48 * 3600 * 1000

Point = tuple[int, float | None]  # (epoch ms, value); None marks a gap


@dataclass(frozen=True, slots=True)
class ChartSpec:
    """One chart: which metrics, read how, drawn as what."""

    id: str
    group: Group
    form: Form
    metrics: tuple[str, ...]
    method: Method
    default_visible: bool = True
    goal_metric: str | None = None


CHARTS: tuple[ChartSpec, ...] = (
    ChartSpec("body_battery_today", "today", "area", ("body_battery",), "intraday"),
    ChartSpec("steps_today", "today", "line", ("steps",), "cumulative_today", goal_metric="steps_goal"),
    ChartSpec("stress_today", "today", "line", ("stress_avg",), "intraday", default_visible=False),
    ChartSpec("sleep_stages", "today", "stacked_bar",
              ("sleep_deep", "sleep_light", "sleep_rem", "sleep_awake"), "current"),
    ChartSpec("body_battery_range", "trends", "range_columns", ("body_battery",), "daily_range"),
    ChartSpec("sleep_score", "trends", "dots", ("sleep_score",), "change_points"),
    ChartSpec("sleep_duration", "trends", "columns", ("sleep_duration",), "change_points"),
    ChartSpec("resting_hr", "trends", "line", ("resting_hr",), "change_points"),
    ChartSpec("hrv", "trends", "line", ("hrv_last_night",), "change_points"),
    ChartSpec("weekly_steps", "trends", "line", ("weekly_step_avg",), "change_points"),
    ChartSpec("vo2max", "trends", "step", ("vo2max",), "change_points"),
    ChartSpec("ftp_cycling", "trends", "step", ("ftp_cycling",), "change_points"),
)
CHARTS_BY_ID: dict[str, ChartSpec] = {chart.id: chart for chart in CHARTS}


def _ms(when: datetime | float) -> int:
    if isinstance(when, datetime):
        return int(when.timestamp() * 1000)
    # Recorder statistics rows carry epoch seconds.
    return int(when * 1000)


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def history_points(states: Iterable[State | Mapping[str, Any]], convert) -> list[Point]:
    """State history as points; unknown/unavailable become gaps, never zeros."""
    points: list[Point] = []
    for item in states:
        if isinstance(item, State):
            raw, when = item.state, item.last_changed
        else:
            raw, when = item["state"], dt_util.parse_datetime(item["last_changed"])
        if when is None:
            continue
        if raw in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            if points and points[-1][1] is not None:
                points.append((_ms(when), None))
            continue
        value = convert(raw)
        if value is not None:
            points.append((_ms(when), value))
    return points


def change_points(rows: Iterable[Mapping[str, Any]], convert) -> list[Point]:
    """Emit a point at the first stable hour of each new value.

    Hours whose min and max differ are transitions; their mean is a blend of
    two measurements and is skipped. A hole longer than GAP_MS in the records
    becomes a gap, and the value after it is emitted even if unchanged.
    """
    points: list[Point] = []
    last: float | None = None
    last_seen: int | None = None
    for row in rows:
        low, high = _finite(row.get("min")), _finite(row.get("max"))
        if low is None or high is None or low != high:
            continue
        value = convert(high)
        if value is None:
            continue
        start = _ms(row["start"])
        if last_seen is not None and start - last_seen > GAP_MS and points:
            points.append((last_seen + 3600 * 1000, None))
            last = None
        last_seen = start
        if value == last:
            continue
        points.append((start, value))
        last = value
    return points


def daily_range(rows: Iterable[Mapping[str, Any]], convert) -> list[tuple[int, float, float]]:
    """(day start ms, low, high) per HA day with data."""
    out: list[tuple[int, float, float]] = []
    for row in rows:
        low, high = _finite(row.get("min")), _finite(row.get("max"))
        if low is None or high is None:
            continue
        low_v, high_v = convert(low), convert(high)
        if low_v is not None and high_v is not None:
            out.append((_ms(row["start"]), low_v, high_v))
    return out


def downsample(points: list[Point], limit: int = MAX_POINTS) -> list[Point]:
    """Keep at most `limit` points, always keeping gaps, first and last."""
    if len(points) <= limit:
        return points
    step = math.ceil(len(points) / limit)
    kept = [p for i, p in enumerate(points) if i % step == 0 or p[1] is None]
    if kept[-1] != points[-1]:
        kept.append(points[-1])
    return kept


def _converter(metric_key: str, unit: str | None):
    """Convert raw recorder values with the same rules as the live snapshot."""
    spec = CATALOG_BY_KEY[metric_key]

    def convert(raw: Any) -> float | None:
        normalized = normalize_value(spec, str(raw), unit)
        if normalized is None or not isinstance(normalized[0], (int, float)):
            return None
        return float(normalized[0])

    return convert


def _canonical_unit(metric_key: str, unit: str | None) -> str | None:
    kind = CATALOG_BY_KEY[metric_key].kind
    return {"distance": "m", "duration": "s"}.get(kind, unit)


class ChartService:
    """Builds chart payloads for one profile, with a short shared cache."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._cache: dict[tuple[str, str, int], tuple[datetime, dict[str, Any]]] = {}

    @staticmethod
    def range_for(chart: ChartSpec, requested: int | None) -> int:
        if chart.group == "today":
            return 1
        return requested if requested in TREND_RANGES else DEFAULT_TREND_RANGE

    async def async_chart(
        self, profile, chart: ChartSpec, range_days: int
    ) -> dict[str, Any]:
        key = (profile.profile_id, chart.id, range_days)
        now = dt_util.utcnow()
        cached = self._cache.get(key)
        if cached and cached[0] > now:
            return cached[1]
        payload = await self._build(profile, chart, range_days, now)
        if chart.method != "current":
            self._cache[key] = (now + timedelta(seconds=CACHE_SECONDS), payload)
        return payload

    async def _build(self, profile, chart: ChartSpec, range_days: int, now: datetime) -> dict[str, Any]:
        if chart.method == "intraday":
            start = now - INTRADAY_WINDOW
        elif chart.method == "cumulative_today":
            start = dt_util.start_of_local_day()
        else:
            start = now - timedelta(days=range_days)

        series: list[dict[str, Any]] = []
        for metric_key in chart.metrics:
            resolution = profile.mapping.metrics.get(metric_key)
            if resolution is None or resolution.status != "resolved" or resolution.entity_id is None:
                continue
            entity_id = resolution.entity_id
            state = self.hass.states.get(entity_id)
            unit = state.attributes.get("unit_of_measurement") if state else None
            convert = _converter(metric_key, unit)
            entry: dict[str, Any] = {
                "metric": metric_key,
                "kind": CATALOG_BY_KEY[metric_key].kind,
                "unit": _canonical_unit(metric_key, unit),
            }
            if chart.method == "current":
                entry["points"] = [] if state is None else [
                    (_ms(state.last_changed), convert(state.state))
                ]
            elif chart.method in ("intraday", "cumulative_today"):
                states = await self._history(entity_id, start, now)
                entry["points"] = downsample(history_points(states, convert))
            elif chart.method == "change_points":
                rows = await self._statistics(entity_id, start, now, "hour")
                entry["points"] = downsample(change_points(rows, convert))
            else:
                rows = await self._statistics(entity_id, start, now, "day")
                entry["ranges"] = daily_range(rows, convert)
            series.append(entry)

        payload: dict[str, Any] = {
            "chart_id": chart.id,
            "group": chart.group,
            "form": chart.form,
            "method": chart.method,
            "range_days": range_days,
            "start": start.isoformat(),
            "end": now.isoformat(),
            "series": series,
        }
        if chart.goal_metric:
            goal = profile.metric(chart.goal_metric)
            payload["goal"] = goal["value"] if goal and goal["status"] == "available" else None
        return payload

    async def _history(self, entity_id: str, start: datetime, end: datetime) -> list[Any]:
        result = await get_instance(self.hass).async_add_executor_job(
            lambda: history.get_significant_states(
                self.hass, start, end, [entity_id],
                include_start_time_state=True, significant_changes_only=False,
                minimal_response=True, no_attributes=True,
            )
        )
        return result.get(entity_id, [])

    async def _statistics(self, entity_id: str, start: datetime, end: datetime, period: str) -> list[Any]:
        result = await get_instance(self.hass).async_add_executor_job(
            statistics.statistics_during_period,
            self.hass, start, end, {entity_id}, period, None, {"min", "max", "mean"},
        )
        return result.get(entity_id, [])
