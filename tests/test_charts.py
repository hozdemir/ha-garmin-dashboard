"""Chart series extraction rules and the chart command."""

from datetime import timedelta
from typing import Any
from unittest.mock import patch

from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.garmin_dashboard.charts import (
    CHARTS_BY_ID,
    GAP_MS,
    ChartService,
    change_points,
    daily_range,
    downsample,
    history_points,
    last_per_day,
)
from custom_components.garmin_dashboard.const import DOMAIN

from .conftest import entity_for
from .test_init import PROFILE_ID, _setup

HOUR = 3600.0
T0 = 1_760_000_000.0  # epoch seconds, like recorder statistics rows


def _rows(*values: tuple[float | None, float | None]) -> list[dict[str, Any]]:
    """Hourly statistics rows from (min, max) pairs."""
    return [{"start": T0 + i * HOUR, "min": lo, "max": hi} for i, (lo, hi) in enumerate(values)]


def ident(value: Any) -> float:
    return float(value)


def test_one_night_held_for_two_days_is_one_point() -> None:
    # Sleep score 74 sits in HA for 30 hours, then 79 arrives.
    rows = _rows(*[(74, 74)] * 30, *[(79, 79)] * 30)
    assert [v for _, v in change_points(rows, ident)] == [74, 79]


def test_transition_hours_are_not_averaged_into_a_fake_value() -> None:
    rows = _rows((56, 56), (56, 61), (61, 61))
    points = change_points(rows, ident)
    assert [v for _, v in points] == [56, 61]
    assert points[1][0] == int((T0 + 2 * HOUR) * 1000)


def test_long_hole_becomes_a_gap_not_a_bridge() -> None:
    rows = [*_rows((50, 50)), {"start": T0 + 72 * HOUR, "min": 50, "max": 50}]
    points = change_points(rows, ident)
    assert [v for _, v in points] == [50, None, 50]
    assert points[1][0] - points[0][0] < GAP_MS


def test_nightly_zero_placeholder_is_not_a_night() -> None:
    # Real pattern: sleep duration drops to 0 at the Garmin day change, the
    # night's value arrives in the morning.
    rows = _rows((343, 343), (0, 0), (0, 0), (372, 372), (0, 0), (320, 320))
    assert [v for _, v in change_points(rows, ident, zero_is_placeholder=True)] == [343, 372, 320]
    assert 0 in [v for _, v in change_points(rows, ident)]


async def test_provisional_overnight_value_is_replaced_by_the_days_last(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("Europe/Istanbul")
    day = dt_util.parse_datetime("2026-10-05T00:00:00+03:00")
    ms = lambda h: int((day + timedelta(hours=h)).timestamp() * 1000)  # noqa: E731
    # Real resting-HR pattern: 62 at 02:00 (provisional), 54 at 09:00, next day 61 then 60.
    points = [(ms(2), 62.0), (ms(9), 54.0), (ms(27), 61.0), (ms(33), 60.0)]
    assert last_per_day(points) == [(ms(0), 54.0), (ms(24), 60.0)]


def test_last_per_day_keeps_gaps() -> None:
    points = [(0, 1.0), (1, None), (5 * 86_400_000, 2.0)]
    assert [v for _, v in last_per_day(points)] == [1.0, None, 2.0]


def test_unconvertible_values_are_skipped() -> None:
    rows = _rows((1, 1), (2, 2))
    assert change_points(rows, lambda v: None if v == 1 else v) == [(int((T0 + HOUR) * 1000), 2)]


def test_history_unknown_is_a_gap_never_zero() -> None:
    now = dt_util.utcnow()
    states = [
        State("sensor.x", "60", last_changed=now),
        {"state": "unavailable", "last_changed": (now + timedelta(hours=1)).isoformat()},
        {"state": "unknown", "last_changed": (now + timedelta(hours=2)).isoformat()},
        {"state": "55", "last_changed": (now + timedelta(hours=3)).isoformat()},
    ]
    assert [v for _, v in history_points(states, ident)] == [60, None, 55]


def test_daily_range() -> None:
    rows = [{"start": T0, "min": 12, "max": 88}, {"start": T0 + 24 * HOUR, "min": None, "max": None}]
    assert daily_range(rows, ident) == [(int(T0 * 1000), 12, 88)]


def test_downsample_keeps_ends_and_gaps() -> None:
    points = [(i, float(i)) for i in range(5000)]
    points[2501] = (2501, None)
    kept = downsample(points, 1000)
    assert len(kept) <= 1002
    assert kept[0] == points[0] and kept[-1] == points[-1]
    assert (2501, None) in kept


@pytest.mark.parametrize(("requested", "expected"), [(7, 7), (90, 90), (365, 30), (None, 30)])
def test_trend_range_is_limited_to_presets(requested: int | None, expected: int) -> None:
    assert ChartService.range_for(CHARTS_BY_ID["resting_hr"], requested) == expected
    assert ChartService.range_for(CHARTS_BY_ID["steps_today"], requested) == 1


def test_no_multi_day_step_totals_offered() -> None:
    for chart in CHARTS_BY_ID.values():
        if "steps" in chart.metrics:
            assert chart.method == "cumulative_today"


async def test_chart_command_reads_recorder(
    recorder_mock, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    await _setup(hass)
    steps = entity_for("total_steps")
    attrs = hass.states.get(steps).attributes
    hass.states.async_set(steps, "9000", attrs)
    hass.states.async_set(steps, "unavailable", {})
    hass.states.async_set(steps, "9500", attrs)
    await async_wait_recording_done(hass)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/chart", "profile_id": PROFILE_ID, "chart_id": "steps_today"})
    reply = await client.receive_json()
    assert reply["success"], reply
    result = reply["result"]
    assert result["method"] == "cumulative_today"
    assert result["goal"] == 10000
    values = [v for _, v in result["series"][0]["points"]]
    assert values[-3:] == [9000, None, 9500]


async def test_chart_without_recorder_reports_it(hass: HomeAssistant, hass_ws_client: WebSocketGenerator) -> None:
    await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/chart", "profile_id": PROFILE_ID, "chart_id": "resting_hr"})
    reply = await client.receive_json()
    assert reply["error"]["code"] == "recorder_unavailable"


async def test_current_chart_works_without_recorder(hass: HomeAssistant, hass_ws_client: WebSocketGenerator) -> None:
    await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/chart", "profile_id": PROFILE_ID, "chart_id": "sleep_stages"})
    reply = await client.receive_json()
    assert reply["success"]
    assert [s["metric"] for s in reply["result"]["series"]] == ["sleep_deep", "sleep_light", "sleep_rem", "sleep_awake"]
    # Minutes from the source arrive as seconds.
    assert reply["result"]["series"][0]["points"][0][1] == 60


async def test_non_admin_cannot_read_charts(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, hass_read_only_access_token: str
) -> None:
    await _setup(hass)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json_auto_id({"type": f"{DOMAIN}/chart", "profile_id": PROFILE_ID, "chart_id": "sleep_stages"})
    assert (await client.receive_json())["error"]["code"] == "unauthorized"


async def test_hrv_chart_carries_the_current_balanced_range(hass: HomeAssistant) -> None:
    await _setup(hass)
    hass.states.async_set(
        entity_for("hrv_baseline"), "52", {"unit_of_measurement": "ms", "balancedLow": 46, "balancedUpper": 61}
    )
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    service, profile = entry.runtime_data.charts, entry.runtime_data.profiles[PROFILE_ID]
    with patch.object(service, "_statistics", return_value=[]):
        payload = await service.async_chart(profile, CHARTS_BY_ID["hrv"], 30)
    assert payload["band"] == {"low": 46, "high": 61, "current_only": True}


async def test_no_band_when_the_range_is_unknown(hass: HomeAssistant) -> None:
    await _setup(hass)
    hass.states.async_set(entity_for("hrv_baseline"), "52", {"unit_of_measurement": "ms"})
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    service, profile = entry.runtime_data.charts, entry.runtime_data.profiles[PROFILE_ID]
    with patch.object(service, "_statistics", return_value=[]):
        payload = await service.async_chart(profile, CHARTS_BY_ID["hrv"], 7)
    assert payload["band"] is None
