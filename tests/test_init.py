"""Lifecycle, panel registration and the admin-only WebSocket API (spec §6.4, §12, §14)."""

from typing import Any

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.garmin_dashboard.const import DOMAIN, PANEL_URL_PATH

from .conftest import FIXTURE, entity_for, load_source

PROFILE_ID = "p1"


async def _setup(hass: HomeAssistant, **source_kwargs: Any) -> MockConfigEntry:
    load_source(hass, **source_kwargs)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garmin",
        data={"sources": [{"profile_id": PROFILE_ID, "source_entry_id": FIXTURE["source_entry_id"],
                           "display_name": "Garmin"}]},
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


async def test_subscription_pushes_on_state_change(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
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


async def test_last_value_is_kept_during_outage(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
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
