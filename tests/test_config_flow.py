"""Config flow: source detection and activity sensor opt-in."""

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.garmin_dashboard.const import DOMAIN

from .conftest import FIXTURE, SECOND_SOURCE_ENTRY_ID, entity_for, load_source


async def _start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})


async def test_no_source_aborts_with_guidance(hass: HomeAssistant) -> None:
    result = await _start(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_source"


async def test_single_source_offers_activity_opt_in_and_enables_on_yes(hass: HomeAssistant) -> None:
    load_source(hass)
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "activities"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"enable_activities": True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    source = result["data"]["sources"][0]
    assert source["source_entry_id"] == FIXTURE["source_entry_id"]
    # The e-mail-looking source title never becomes the display name.
    assert source["display_name"] == "Garmin"

    registry = er.async_get(hass)
    assert registry.async_get(entity_for("last_activity")).disabled_by is None
    assert registry.async_get(entity_for("last_activities")).disabled_by is None
    # Nothing else of the source was touched.
    assert registry.async_get(entity_for("bmi")).disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_declining_leaves_sensors_disabled(hass: HomeAssistant) -> None:
    load_source(hass)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"enable_activities": False})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert er.async_get(hass).async_get(entity_for("last_activity")).disabled_by is not None


async def test_no_activity_step_when_sensors_already_enabled(hass: HomeAssistant) -> None:
    load_source(hass)
    registry = er.async_get(hass)
    for key in ("last_activity", "last_activities"):
        registry.async_update_entity(entity_for(key), disabled_by=None)
    result = await _start(hass)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_multiple_accounts_are_chosen_and_named(hass: HomeAssistant) -> None:
    load_source(hass)
    load_source(hass, entry_id=SECOND_SOURCE_ENTRY_ID, title="Partner", suffix="_2")
    result = await _start(hass)
    assert result["step_id"] == "accounts"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"accounts": [FIXTURE["source_entry_id"], SECOND_SOURCE_ENTRY_ID]}
    )
    assert result["step_id"] == "names"
    # The e-mail-like title is not offered as a name; the other title is.
    defaults = {str(k): k.default() for k in result["data_schema"].schema}
    assert defaults == {"name_1": "Garmin", "name_2": "Partner"}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name_1": "Me", "name_2": "Partner"})
    assert result["step_id"] == "activities"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"enable_activities": True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    profiles = result["data"]["sources"]
    assert [(p["source_entry_id"], p["display_name"]) for p in profiles] == [
        (FIXTURE["source_entry_id"], "Me"),
        (SECOND_SOURCE_ENTRY_ID, "Partner"),
    ]
    assert profiles[0]["profile_id"] != profiles[1]["profile_id"]
    # Activity sensors of both accounts were enabled.
    registry = er.async_get(hass)
    assert registry.async_get(entity_for("last_activity", suffix="_2")).disabled_by is None


async def test_account_choice_and_names_are_validated(hass: HomeAssistant) -> None:
    load_source(hass)
    load_source(hass, entry_id=SECOND_SOURCE_ENTRY_ID, title="Partner", suffix="_2")
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"accounts": []})
    assert result["errors"] == {"base": "no_accounts"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"accounts": [FIXTURE["source_entry_id"], SECOND_SOURCE_ENTRY_ID]}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name_1": "Same", "name_2": "same"})
    assert result["errors"] == {"base": "name_taken"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name_1": " ", "name_2": "B"})
    assert result["errors"] == {"base": "invalid_name"}


async def test_choosing_one_of_two_accounts(hass: HomeAssistant) -> None:
    load_source(hass)
    load_source(hass, entry_id=SECOND_SOURCE_ENTRY_ID, title="Partner", suffix="_2")
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"accounts": [SECOND_SOURCE_ENTRY_ID]})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name_1": "Partner"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"enable_activities": False})
    assert [p["source_entry_id"] for p in result["data"]["sources"]] == [SECOND_SOURCE_ENTRY_ID]


async def test_second_dashboard_entry_is_blocked(hass: HomeAssistant) -> None:
    load_source(hass)
    MockConfigEntry(domain=DOMAIN, data={"sources": []}).add_to_hass(hass)
    result = await _start(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
