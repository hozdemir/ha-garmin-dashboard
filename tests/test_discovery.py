"""Metric resolution against the synthetic 3.0.19 fixture."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.garmin_dashboard.discovery import disabled_activity_entities, resolve_profile
from custom_components.garmin_dashboard.providers.cyberjunky import CATALOG

from .conftest import FIXTURE, entity_for, load_source


async def test_every_catalog_metric_resolves(hass: HomeAssistant) -> None:
    load_source(hass)
    mapping = resolve_profile(hass, FIXTURE["source_entry_id"])
    assert {key: r.status for key, r in mapping.metrics.items()} == {
        spec.key: "resolved" for spec in CATALOG
    }


async def test_sport_specific_ftp_is_not_mixed_up(hass: HomeAssistant) -> None:
    load_source(hass)
    mapping = resolve_profile(hass, FIXTURE["source_entry_id"])
    assert mapping.metrics["ftp_cycling"].entity_id == entity_for("functional_threshold_power", "cycling")
    assert mapping.metrics["ftp_running"].entity_id == entity_for("functional_threshold_power", "running")


async def test_rename_follows_registry(hass: HomeAssistant) -> None:
    load_source(hass)
    registry = er.async_get(hass)
    registry.async_update_entity(entity_for("total_steps"), new_entity_id="sensor.my_steps")
    mapping = resolve_profile(hass, FIXTURE["source_entry_id"])
    assert mapping.metrics["steps"].entity_id == "sensor.my_steps"


async def test_legacy_email_unique_ids_are_ignored(hass: HomeAssistant) -> None:
    load_source(hass)
    mapping = resolve_profile(hass, FIXTURE["source_entry_id"])
    legacy = {e["entity_id"] for e in FIXTURE["entities"] if e["unique_id"].startswith("user@example.com_")}
    assert legacy
    assert not legacy & mapping.entity_ids


async def test_gear_found_by_unique_id(hass: HomeAssistant) -> None:
    load_source(hass)
    mapping = resolve_profile(hass, FIXTURE["source_entry_id"])
    assert [g.entity_id for g in mapping.gear] == ["sensor.gear_1"]


async def test_duplicate_translation_key_is_ambiguous(hass: HomeAssistant) -> None:
    source = load_source(hass)
    er.async_get(hass).async_get_or_create(
        "sensor", "garmin_connect", f"{source.entry_id}_totalStepsCopy",
        config_entry=source, translation_key="total_steps",
    )
    mapping = resolve_profile(hass, FIXTURE["source_entry_id"])
    assert mapping.metrics["steps"].status == "ambiguous"
    assert mapping.metrics["steps"].entity_id is None


async def test_only_integration_disabled_activity_sensors_are_offered(hass: HomeAssistant) -> None:
    load_source(hass)
    offered = disabled_activity_entities(hass, FIXTURE["source_entry_id"])
    assert sorted(offered) == sorted([entity_for("last_activity"), entity_for("last_activities")])

    er.async_get(hass).async_update_entity(
        entity_for("last_activity"), disabled_by=er.RegistryEntryDisabler.USER
    )
    assert disabled_activity_entities(hass, FIXTURE["source_entry_id"]) == [entity_for("last_activities")]
