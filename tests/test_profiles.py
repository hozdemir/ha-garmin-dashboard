"""Several Garmin accounts: options flow, isolation and Repairs."""

import asyncio

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.garmin_dashboard.const import DOMAIN
from custom_components.garmin_dashboard.preferences import default_preferences

from .conftest import FIXTURE, SECOND_SOURCE_ENTRY_ID, entity_for, load_source


async def _setup_two(hass: HomeAssistant) -> MockConfigEntry:
    load_source(hass)
    load_source(
        hass,
        entry_id=SECOND_SOURCE_ENTRY_ID,
        title="Partner",
        suffix="_2",
        overrides={entity_for("total_steps", suffix="_2"): "1234"},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garmin",
        data={
            "sources": [
                {"profile_id": "a", "source_entry_id": FIXTURE["source_entry_id"], "display_name": "Me"},
                {"profile_id": "b", "source_entry_id": SECOND_SOURCE_ENTRY_ID, "display_name": "Partner"},
            ]
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_profiles_never_mix_data(hass: HomeAssistant) -> None:
    entry = await _setup_two(hass)
    profiles = entry.runtime_data.profiles
    assert profiles["a"].snapshot()["metrics"]["steps"]["value"] == 8500
    assert profiles["b"].snapshot()["metrics"]["steps"]["value"] == 1234
    assert not profiles["a"].mapping.entity_ids & profiles["b"].mapping.entity_ids


async def test_subscription_ignores_the_other_account(hass: HomeAssistant, hass_ws_client: WebSocketGenerator) -> None:
    await _setup_two(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/subscribe", "profile_id": "a"})
    assert (await client.receive_json())["success"]
    await client.receive_json()  # initial snapshot

    steps_b = entity_for("total_steps", suffix="_2")
    hass.states.async_set(steps_b, "9999", hass.states.get(steps_b).attributes)
    await hass.async_block_till_done()
    # Longer than the 250 ms debounce: profile "a" must get nothing.
    try:
        async with asyncio.timeout(0.6):
            message = await client.receive_json()
    except TimeoutError:
        message = None
    assert message is None


async def test_options_flow_adds_renames_and_removes(hass: HomeAssistant) -> None:
    load_source(hass)
    load_source(hass, entry_id=SECOND_SOURCE_ENTRY_ID, title="Partner", suffix="_2")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garmin",
        data={
            "sources": [
                {"profile_id": "a", "source_entry_id": FIXTURE["source_entry_id"], "display_name": "Me"},
            ]
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await entry.runtime_data.preferences.async_set("a", {**default_preferences(), "hidden_sections": ["gear"]})

    # Add the second account and rename the first.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "accounts"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"accounts": [FIXTURE["source_entry_id"], SECOND_SOURCE_ENTRY_ID]}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name_1": "Hakan", "name_2": "Partner"}
    )
    assert result["step_id"] == "activities"  # only the new account is asked about
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"enable_activities": False})
    await hass.async_block_till_done()
    sources = entry.data["sources"]
    assert (sources[0]["profile_id"], sources[0]["display_name"]) == ("a", "Hakan")
    assert len(sources) == 2
    # The kept profile keeps its preferences across the reload.
    assert entry.runtime_data.preferences.get("a")["hidden_sections"] == ["gear"]

    # Remove the first account: its profile and preferences go away.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"accounts": [SECOND_SOURCE_ENTRY_ID]}
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"name_1": "Partner"})
    await hass.async_block_till_done()
    assert [s["source_entry_id"] for s in entry.data["sources"]] == [SECOND_SOURCE_ENTRY_ID]
    assert entry.runtime_data.preferences.get("a") == default_preferences()
    assert list(entry.runtime_data.profiles) == [sources[1]["profile_id"]]


async def test_removed_source_raises_a_repair_and_never_switches_account(hass: HomeAssistant) -> None:
    entry = await _setup_two(hass)
    await hass.config_entries.async_remove(SECOND_SOURCE_ENTRY_ID)
    await hass.async_block_till_done()
    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, "source_removed_b") is not None
    assert issues.async_get_issue(DOMAIN, "source_removed_a") is None
    snapshot = entry.runtime_data.profiles["b"].snapshot()
    assert snapshot["source_status"] == "removed"
    assert snapshot["metrics"]["steps"]["value"] is None

    # The removed account can be dropped in the options flow; the issue goes with it.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    labels = {o["value"]: o["label"] for o in result["data_schema"].schema["accounts"].config["options"]}
    assert labels[SECOND_SOURCE_ENTRY_ID] == "Partner (removed)"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"accounts": [FIXTURE["source_entry_id"]]}
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"name_1": "Me"})
    await hass.async_block_till_done()
    assert issues.async_get_issue(DOMAIN, "source_removed_b") is None


async def test_unsupported_version_raises_a_repair(hass: HomeAssistant, source_version) -> None:
    source_version.version = "9.9.9"
    await _setup_two(hass)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "unsupported_source_a")
    assert issue is not None
    assert issue.translation_placeholders["version"] == "9.9.9"
