"""Config flow: source detection and activity sensor opt-in."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.garmin_dashboard.const import DOMAIN

from .conftest import FIXTURE, entity_for, load_source


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


async def test_multiple_sources_require_a_choice(hass: HomeAssistant) -> None:
    load_source(hass)
    other = MockConfigEntry(domain="garmin_connect", title="Second account")
    other.add_to_hass(hass)
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pick_source"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"source": other.entry_id})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["sources"][0]["source_entry_id"] == other.entry_id
    assert result["data"]["sources"][0]["display_name"] == "Second account"


async def test_second_dashboard_entry_is_blocked(hass: HomeAssistant) -> None:
    load_source(hass)
    MockConfigEntry(domain=DOMAIN, data={"sources": []}).add_to_hass(hass)
    result = await _start(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
