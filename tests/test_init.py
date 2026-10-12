"""Lifecycle, panel registration and the admin-only WebSocket API."""

from typing import Any
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.garmin_dashboard.const import DOMAIN, PANEL_URL_PATH

from .conftest import FIXTURE, entity_for, load_source

PROFILE_ID = "p1"


async def _setup(hass: HomeAssistant, **source_kwargs: Any) -> MockConfigEntry:
    load_source(hass, **source_kwargs)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garmin",
        data={
            "sources": [
                {"profile_id": PROFILE_ID, "source_entry_id": FIXTURE["source_entry_id"], "display_name": "Garmin"}
            ]
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_panel_is_admin_only_and_registered_once(
    hass: HomeAssistant, no_panel_frontend: dict[str, dict[str, Any]]
) -> None:
    entry = await _setup(hass)
    assert no_panel_frontend[PANEL_URL_PATH]["require_admin"] is True

    assert await hass.config_entries.async_reload(entry.entry_id)
    assert await hass.config_entries.async_reload(entry.entry_id)
    assert list(no_panel_frontend) == [PANEL_URL_PATH]

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert no_panel_frontend == {}


async def test_snapshot_shape(hass: HomeAssistant, hass_ws_client: WebSocketGenerator) -> None:
    await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/snapshot", "profile_id": PROFILE_ID})
    reply = await client.receive_json()
    assert reply["success"]
    snapshot = reply["result"]
    assert snapshot["schema_version"] == 1
    assert snapshot["source_status"] == "ready"
    assert snapshot["metrics"]["steps"]["value"] == 8500
    assert snapshot["metrics"]["distance_day"]["value"] == 6200
    assert snapshot["metrics"]["ftp_cycling"]["source_date"] == "2026-01-15"
    assert snapshot["source_synced_at"] == "2026-01-15T07:30:00+00:00"
    assert [g["distance_meters"] for g in snapshot["gear"]] == [12000]
    assert "movement" in snapshot["capabilities"]


async def test_non_admin_is_denied_everything(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, hass_read_only_access_token: str
) -> None:
    await _setup(hass)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    for msg in (
        {"type": f"{DOMAIN}/profiles"},
        {"type": f"{DOMAIN}/snapshot", "profile_id": PROFILE_ID},
        {"type": f"{DOMAIN}/subscribe", "profile_id": PROFILE_ID},
    ):
        await client.send_json_auto_id(msg)
        reply = await client.receive_json()
        assert not reply["success"]
        assert reply["error"]["code"] == "unauthorized"


async def test_unknown_profile_is_rejected(hass: HomeAssistant, hass_ws_client: WebSocketGenerator) -> None:
    await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/snapshot", "profile_id": "someone-else"})
    reply = await client.receive_json()
    assert reply["error"]["code"] == "profile_not_found"


async def test_subscription_pushes_on_state_change(hass: HomeAssistant, hass_ws_client: WebSocketGenerator) -> None:
    await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/subscribe", "profile_id": PROFILE_ID})
    assert (await client.receive_json())["success"]
    first = (await client.receive_json())["event"]

    steps = entity_for("total_steps")
    hass.states.async_set(steps, "9100", hass.states.get(steps).attributes)
    hass.states.async_set(steps, "9200", hass.states.get(steps).attributes)
    pushed = (await client.receive_json())["event"]
    assert pushed["revision"] > first["revision"]
    assert pushed["metrics"]["steps"]["value"] == 9200


async def test_last_value_is_kept_during_outage(hass: HomeAssistant, hass_ws_client: WebSocketGenerator) -> None:
    entry = await _setup(hass)
    profile = entry.runtime_data.profiles[PROFILE_ID]
    profile.snapshot()
    steps = entity_for("total_steps")
    hass.states.async_set(steps, "unavailable", {})
    metric = profile.snapshot()["metrics"]["steps"]
    assert (metric["status"], metric["value"], metric["freshness"]) == ("unavailable", 8500, "stale")


async def test_removed_source_is_reported(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    await hass.config_entries.async_remove(FIXTURE["source_entry_id"])
    profile = entry.runtime_data.profiles[PROFILE_ID]
    assert profile.source_status == "removed"


async def test_unsupported_source_version(hass: HomeAssistant, source_version) -> None:
    source_version.version = "9.9.9"
    entry = await _setup(hass)
    assert entry.runtime_data.profiles[PROFILE_ID].source_status == "unsupported"


async def test_rename_after_setup_keeps_metric(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    er.async_get(hass).async_update_entity(entity_for("total_steps"), new_entity_id="sensor.renamed_steps")
    hass.states.async_set("sensor.renamed_steps", "8500", {"unit_of_measurement": "steps"})
    await hass.async_block_till_done()
    metric = entry.runtime_data.profiles[PROFILE_ID].snapshot()["metrics"]["steps"]
    assert (metric["status"], metric["value"]) == ("available", 8500)


async def test_diagnostics_has_no_identifiers(hass: HomeAssistant) -> None:
    from custom_components.garmin_dashboard.diagnostics import async_get_config_entry_diagnostics

    entry = await _setup(hass)
    report = str(await async_get_config_entry_diagnostics(hass, entry))
    for secret in (FIXTURE["source_entry_id"], "user@example.com", "sensor.", PROFILE_ID, "8500"):
        assert secret not in report


DEVICES = {
    "last_used_device": {
        "userDeviceId": 7,
        "lastUsedDeviceName": "Custom name",
        "lastSyncTime": "2026-01-15T08:00:00+00:00",
    },
    "devices": [
        {"deviceId": 3, "productDisplayName": "Index S2", "displayName": "Bathroom", "serialNumber": "SER-3"},
        {"deviceId": 7, "productDisplayName": "Edge 840", "displayName": "My bike", "serialNumber": "SER-7"},
    ],
}


async def test_sync_time_falls_back_to_the_device_and_names_its_model(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    profile = entry.runtime_data.profiles[PROFILE_ID]
    hass.states.async_set(entity_for("last_synced"), "unknown", {"device_class": "timestamp"})
    hass.states.async_set(entity_for("devices"), "2", DEVICES)
    snapshot = profile.snapshot()
    assert snapshot["source_synced_at"] == "2026-01-15T08:00:00+00:00"
    assert snapshot["source_sync_device"] == "Edge 840"
    # Custom names and serial numbers never reach the panel.
    for private in ("Custom name", "My bike", "Bathroom", "SER-7"):
        assert private not in str(snapshot)


async def test_newer_summary_time_wins_without_a_device_name(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    profile = entry.runtime_data.profiles[PROFILE_ID]
    hass.states.async_set(entity_for("last_synced"), "2026-01-15T09:00:00+00:00", {})
    hass.states.async_set(entity_for("devices"), "2", DEVICES)
    snapshot = profile.snapshot()
    assert (snapshot["source_synced_at"], snapshot["source_sync_device"]) == ("2026-01-15T09:00:00+00:00", None)


async def test_no_sync_time_anywhere(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    profile = entry.runtime_data.profiles[PROFILE_ID]
    hass.states.async_set(entity_for("last_synced"), "unknown", {})
    hass.states.async_set(entity_for("devices"), "1", {"last_used_device": {"lastSyncTime": "not a time"}})
    snapshot = profile.snapshot()
    assert (snapshot["source_synced_at"], snapshot["source_sync_device"]) == (None, None)


async def test_expired_garmin_sign_in_is_reported(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    profile = entry.runtime_data.profiles[PROFILE_ID]
    source = hass.config_entries.async_get_entry(FIXTURE["source_entry_id"])
    with patch.object(type(source), "async_get_active_flows", return_value=iter([{"flow_id": "x"}])):
        assert profile.source_status == "reauth"
    assert profile.source_status == "ready"


async def test_cycling_metrics(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    profile = entry.runtime_data.profiles[PROFILE_ID]
    hass.states.async_set(entity_for("power_to_weight", "cycling"), "3.4", {"unit_of_measurement": "W/kg"})
    hass.states.async_set(
        entity_for("lactate_threshold_hr"),
        "172",
        {"unit_of_measurement": "bpm", "heartRateCycling": 165, "calendarDate": "2026-01-10"},
    )
    metrics = profile.snapshot()["metrics"]
    assert (metrics["ptw_cycling"]["value"], metrics["ptw_cycling"]["unit"]) == (3.4, "W/kg")
    assert metrics["lthr_running"]["value"] == 172
    assert metrics["lthr_cycling"]["value"] == 165
    assert metrics["lthr_cycling"]["source_date"] == "2026-01-10"


async def test_missing_attribute_value_is_unknown_not_zero(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    hass.states.async_set(entity_for("lactate_threshold_hr"), "172", {"unit_of_measurement": "bpm"})
    metric = entry.runtime_data.profiles[PROFILE_ID].snapshot()["metrics"]["lthr_cycling"]
    assert (metric["status"], metric["value"]) == ("unknown", None)
