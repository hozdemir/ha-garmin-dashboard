"""Display preferences: defaults, strict writes, tolerant loads, persistence."""

from typing import Any

import pytest
import voluptuous as vol
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from homeassistant.core import HomeAssistant

from custom_components.garmin_dashboard.const import DOMAIN
from custom_components.garmin_dashboard.preferences import (
    SECTIONS,
    PreferenceStore,
    default_preferences,
    sanitize,
    validate,
)

from .test_init import PROFILE_ID, _setup


def test_defaults_show_everything_but_stress() -> None:
    prefs = default_preferences()
    assert prefs["hidden_sections"] == [] and prefs["hidden_metrics"] == []
    assert prefs["hidden_charts"] == ["stress_today"]
    assert prefs["trend_range_days"] == 30


@pytest.mark.parametrize(
    "change",
    [
        {"hidden_metrics": ["not_a_metric"]},
        {"hidden_charts": ["pie_chart"]},
        {"trend_range_days": 365},
        {"section_order": ["movement"]},
        {"surprise": True},
    ],
)
def test_writes_reject_unknown_values(change: dict[str, Any]) -> None:
    with pytest.raises(vol.Invalid):
        validate({**default_preferences(), **change})


def test_loads_drop_removed_keys_and_add_new_sections() -> None:
    stored = {
        "section_order": ["training", "movement"],
        "hidden_metrics": ["steps", "metric_removed_in_new_release"],
        "hidden_charts": ["chart_removed"],
        "trend_range_days": 7,
    }
    prefs = sanitize(stored)
    assert prefs["section_order"][:2] == ["training", "movement"]
    assert sorted(prefs["section_order"]) == sorted(SECTIONS)
    assert prefs["hidden_metrics"] == ["steps"]
    assert prefs["hidden_charts"] == []
    assert prefs["trend_range_days"] == 7


async def test_preferences_survive_restart(hass: HomeAssistant, hass_storage: dict[str, Any]) -> None:
    store = PreferenceStore(hass)
    await store.async_load()
    prefs = {**default_preferences(), "hidden_metrics": ["calories_total"], "trend_range_days": 90}
    await store.async_set("p1", prefs)

    reloaded = PreferenceStore(hass)
    await reloaded.async_load()
    assert reloaded.get("p1")["hidden_metrics"] == ["calories_total"]
    assert reloaded.get("unknown-profile") == default_preferences()


async def test_preferences_api_roundtrip(hass: HomeAssistant, hass_ws_client: WebSocketGenerator) -> None:
    await _setup(hass)
    client = await hass_ws_client(hass)
    prefs = {**default_preferences(), "hidden_sections": ["gear"]}
    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/preferences/set", "profile_id": PROFILE_ID, "preferences": prefs}
    )
    assert (await client.receive_json())["result"]["hidden_sections"] == ["gear"]

    await client.send_json_auto_id({"type": f"{DOMAIN}/preferences/get", "profile_id": PROFILE_ID})
    assert (await client.receive_json())["result"]["hidden_sections"] == ["gear"]

    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/preferences/set", "profile_id": PROFILE_ID,
         "preferences": {**prefs, "hidden_charts": ["nope"]}}
    )
    assert (await client.receive_json())["error"]["code"] == "invalid_preferences"

    await client.send_json_auto_id({"type": f"{DOMAIN}/preferences/reset", "profile_id": PROFILE_ID})
    assert (await client.receive_json())["result"] == default_preferences()


async def test_non_admin_cannot_change_preferences(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, hass_read_only_access_token: str
) -> None:
    await _setup(hass)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/preferences/set", "profile_id": PROFILE_ID, "preferences": default_preferences()}
    )
    assert (await client.receive_json())["error"]["code"] == "unauthorized"


async def test_removing_the_entry_deletes_preferences(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    entry = await _setup(hass)
    await entry.runtime_data.preferences.async_set(PROFILE_ID, default_preferences())
    assert f"{DOMAIN}.preferences" in hass_storage
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert f"{DOMAIN}.preferences" not in hass_storage
