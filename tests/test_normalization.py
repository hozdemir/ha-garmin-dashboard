"""Value, unit, status and freshness rules."""

from datetime import timedelta

import pytest

from homeassistant.core import State
from homeassistant.util import dt as dt_util

from custom_components.garmin_dashboard.discovery import Resolution
from custom_components.garmin_dashboard.normalization import build_metric
from custom_components.garmin_dashboard.providers.cyberjunky import CATALOG_BY_KEY

RESOLVED = Resolution("resolved", "sensor.x")


def _state(value: str, unit: str | None = None, updated_ago: timedelta = timedelta(0), **attrs) -> State:
    now = dt_util.utcnow() - updated_ago
    if unit is not None:
        attrs["unit_of_measurement"] = unit
    return State("sensor.x", value, attrs, last_changed=now, last_updated=now)


def _metric(key: str, state: State | None, resolution: Resolution = RESOLVED) -> dict:
    return build_metric(CATALOG_BY_KEY[key], resolution, state, dt_util.utcnow())


@pytest.mark.parametrize(
    ("unit", "raw", "meters"),
    [("m", "6200", 6200), ("km", "6.2", 6200), ("mi", "1", 1609.344)],
)
def test_distance_follows_the_states_unit(unit: str, raw: str, meters: float) -> None:
    metric = _metric("distance_day", _state(raw, unit))
    assert metric["status"] == "available"
    assert metric["unit"] == "m"
    assert metric["value"] == pytest.approx(meters)


def test_duration_minutes_become_seconds() -> None:
    assert _metric("sleep_duration", _state("432", "min"))["value"] == 432 * 60


@pytest.mark.parametrize("unit", [None, "parsec", "weeks"])
def test_unknown_units_are_invalid_not_guessed(unit: str | None) -> None:
    assert _metric("distance_day", _state("5", unit))["status"] == "invalid"


@pytest.mark.parametrize("raw", ["-3", "nan", "inf", "abc"])
def test_nonsense_numbers_are_invalid(raw: str) -> None:
    metric = _metric("steps", _state(raw, "steps"))
    assert metric["status"] == "invalid"
    assert metric["value"] is None


def test_zero_is_valid_data() -> None:
    metric = _metric("steps", _state("0", "steps"))
    assert metric["status"] == "available"
    assert metric["value"] == 0


def test_percent_over_100_is_invalid() -> None:
    assert _metric("body_battery", _state("140", "%"))["status"] == "invalid"


@pytest.mark.parametrize(("raw", "status"), [("unknown", "unknown"), ("unavailable", "unavailable")])
def test_ha_special_states(raw: str, status: str) -> None:
    metric = _metric("steps", _state(raw, "steps"))
    assert metric["status"] == status
    assert metric["value"] is None


def test_restored_state_counts_as_missing() -> None:
    assert _metric("steps", _state("10", "steps", restored=True))["status"] == "missing"


@pytest.mark.parametrize("status", ["disabled", "missing", "ambiguous"])
def test_resolution_status_passes_through(status: str) -> None:
    assert _metric("steps", None, Resolution(status))["status"] == status


def test_slow_metrics_never_go_stale_by_age() -> None:
    metric = _metric("vo2max", _state("51", "mL/(kg·min)", updated_ago=timedelta(days=60)))
    assert metric["freshness"] == "fresh"


def test_intraday_metric_goes_stale_after_six_hours() -> None:
    assert _metric("body_battery", _state("60", "%", updated_ago=timedelta(hours=7)))["freshness"] == "stale"
    assert _metric("body_battery", _state("60", "%", updated_ago=timedelta(hours=1)))["freshness"] == "fresh"


def test_nightly_metric_without_date_has_unknown_freshness() -> None:
    assert _metric("sleep_score", _state("81"))["freshness"] == "unknown"


def test_nightly_metric_uses_source_date() -> None:
    today = dt_util.now().date()
    fresh = _metric("hrv_status", _state("Balanced", calendarDate=today.isoformat()))
    old = _metric("hrv_status", _state("Balanced", calendarDate=(today - timedelta(days=3)).isoformat()))
    assert (fresh["freshness"], fresh["source_date"]) == ("fresh", today.isoformat())
    assert old["freshness"] == "stale"


def test_category_value_is_kept_as_text() -> None:
    metric = _metric("training_status", _state("Productive"))
    assert (metric["status"], metric["value"]) == ("available", "Productive")
