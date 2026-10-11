"""Recent activities and the last synced route."""

from typing import Any

from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.garmin_dashboard.activities import (
    MAX_ACTIVITIES,
    MAX_ROUTE_POINTS,
    normalize_activities,
    normalize_activity,
    normalize_route,
)
from custom_components.garmin_dashboard.const import DOMAIN
from custom_components.garmin_dashboard.preferences import default_preferences

from .conftest import entity_for
from .test_init import PROFILE_ID, _setup


def _activity(activity_id: int | None, start: str, **extra: Any) -> dict[str, Any]:
    return {
        "activityId": activity_id, "activityName": "Morning Ride", "activityType": "road_biking",
        "startTime": start, "distance": 24000.0, "duration": 3600.0, "movingDuration": 3500.0,
        "averageSpeed": 6.67, "averageHR": 140.0, "startLatitude": 41.0, "startLongitude": 29.0,
        "hrTimeInZone_1": 600.0, "hrTimeInZone_2": 1200.0, "hrTimeInZone_3": 1200.0,
        "hrTimeInZone_4": 500.0, "hrTimeInZone_5": 100.0, **extra,
    }


def test_units_and_fields() -> None:
    a = normalize_activity(_activity(1, "2026-10-11T09:00:00+03:00"))
    assert a["id"] == "1"
    assert a["started_at"] == "2026-10-11T06:00:00+00:00"
    assert (a["distance_meters"], a["duration_seconds"], a["average_speed_mps"]) == (24000, 3600, 6.67)
    assert a["hr_zone_seconds"] == [600, 1200, 1200, 500, 100]


def test_coordinates_never_leave_the_backend() -> None:
    a = normalize_activity(_activity(1, "2026-10-11T09:00:00+03:00", locationName="Somewhere"))
    assert not any("lat" in k.lower() or "lon" in k.lower() or "location" in k.lower() for k in a)


def test_newest_first_regardless_of_source_order_and_deduped() -> None:
    raw = [_activity(1, "2026-10-01T08:00:00+00:00"), _activity(3, "2026-10-03T08:00:00+00:00"),
           _activity(2, "2026-10-02T08:00:00+00:00")]
    result = normalize_activities(raw, latest=_activity(3, "2026-10-03T08:00:00+00:00"))
    assert [a["id"] for a in result["activities"]] == ["3", "2", "1"]


def test_broken_records_are_skipped_or_kept_with_gaps() -> None:
    raw = ["junk", {"activityName": "no id, no start"}, _activity(5, "2026-10-01T08:00:00+00:00",
           distance=float("nan"), averageHR=-3, duration="abc")]
    result = normalize_activities(raw)
    assert result["skipped"] == 2
    kept = result["activities"][0]
    assert (kept["distance_meters"], kept["average_heart_rate_bpm"], kept["duration_seconds"]) == (None, None, None)


def test_missing_id_falls_back_to_start_time_and_is_reported() -> None:
    result = normalize_activities([_activity(None, "2026-10-01T08:00:00+00:00")])
    assert result["activities"][0]["id"].startswith("start:")
    assert result["key_collisions_possible"]


def test_list_is_capped() -> None:
    raw = [_activity(i, f"2026-01-01T00:00:{i % 60:02d}+00:00") for i in range(MAX_ACTIVITIES + 5)]
    result = normalize_activities(raw)
    assert len(result["activities"]) == MAX_ACTIVITIES
    assert result["truncated"]


def test_route_validation_and_simplification() -> None:
    poly = [{"lat": 41 + i * 1e-5, "lon": 29 + i * 1e-5} for i in range(9000)]
    poly[10] = {"lat": 200, "lon": 0}
    poly[11] = {"lat": "x", "lon": 1}
    route = normalize_route({"polyline": poly, "activity_name": "Ride"})
    assert route["invalid_points"] == 2
    assert len(route["points"]) == MAX_ROUTE_POINTS
    assert route["points"][0] == [41.0, 29.0]
    assert route["simplified"]


def test_unusable_route_is_none() -> None:
    assert normalize_route({"polyline": []}) is None
    assert normalize_route({"polyline": [{"lat": 1, "lon": 1}]}) is None
    assert normalize_route({"polyline": "not a list"}) is None


async def _enable_activity_sensors(hass: HomeAssistant) -> None:
    registry = er.async_get(hass)
    for key in ("last_activity", "last_activities"):
        registry.async_update_entity(entity_for(key), disabled_by=None)
    hass.states.async_set(entity_for("last_activities"), "2", {"last_activities": [
        _activity(1, "2026-10-01T08:00:00+00:00"),
        _activity(2, "2026-10-02T08:00:00+00:00", activityName="<img src=x onerror=alert(1)>"),
    ]})
    hass.states.async_set(entity_for("last_activity"), "x", _activity(2, "2026-10-02T08:00:00+00:00"))
    await hass.async_block_till_done()


async def test_snapshot_lists_activities(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    await _enable_activity_sensors(hass)
    snapshot = entry.runtime_data.profiles[PROFILE_ID].snapshot()
    assert [a["id"] for a in snapshot["activities"]] == ["2", "1"]
    # Titles are plain text; escaping is the panel's job and is never bypassed.
    assert snapshot["activities"][0]["title"] == "<img src=x onerror=alert(1)>"
    assert "activities" in snapshot["capabilities"]


async def test_route_command_respects_preference(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    entry = await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/route", "profile_id": PROFILE_ID})
    reply = (await client.receive_json())["result"]
    assert reply["hidden"] is False
    assert len(reply["route"]["points"]) == 4

    await entry.runtime_data.preferences.async_set(PROFILE_ID, {**default_preferences(), "show_route": False})
    await client.send_json_auto_id({"type": f"{DOMAIN}/route", "profile_id": PROFILE_ID})
    assert (await client.receive_json())["result"] == {"hidden": True}


async def test_non_admin_cannot_read_route(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, hass_read_only_access_token: str
) -> None:
    await _setup(hass)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json_auto_id({"type": f"{DOMAIN}/route", "profile_id": PROFILE_ID})
    assert (await client.receive_json())["error"]["code"] == "unauthorized"
