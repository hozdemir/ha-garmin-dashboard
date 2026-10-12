"""Resolve canonical metrics to entities of one source config entry."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .providers import cyberjunky as provider

ResolutionStatus = Literal["resolved", "disabled", "missing", "ambiguous"]


@dataclass(frozen=True, slots=True)
class Resolution:
    """Where one canonical metric comes from."""

    status: ResolutionStatus
    entity_id: str | None = None
    disabled_by: str | None = None


@dataclass(frozen=True, slots=True)
class Gear:
    """One gear sensor of the source."""

    gear_id: str
    entity_id: str
    disabled: bool


@dataclass(slots=True)
class ProfileMapping:
    """Result of resolving one source entry."""

    metrics: dict[str, Resolution] = field(default_factory=dict)
    gear: list[Gear] = field(default_factory=list)
    activity_entities: dict[str, Resolution] = field(default_factory=dict)
    route: Resolution = field(default_factory=lambda: Resolution("missing"))
    last_synced: Resolution = field(default_factory=lambda: Resolution("missing"))
    devices: Resolution = field(default_factory=lambda: Resolution("missing"))

    @property
    def entity_ids(self) -> set[str]:
        """All entity IDs this profile reads state from."""
        found = [r.entity_id for r in self.metrics.values() if r.status == "resolved"]
        found += [g.entity_id for g in self.gear if not g.disabled]
        found += [r.entity_id for r in self.activity_entities.values() if r.status == "resolved"]
        found += [r.entity_id for r in (self.route, self.last_synced, self.devices) if r.status == "resolved"]
        return {entity_id for entity_id in found if entity_id}


def _to_resolution(candidates: list[er.RegistryEntry]) -> Resolution:
    if not candidates:
        return Resolution("missing")
    if len(candidates) > 1:
        return Resolution("ambiguous")
    entry = candidates[0]
    if entry.disabled_by is not None:
        return Resolution("disabled", entry.entity_id, entry.disabled_by.value)
    return Resolution("resolved", entry.entity_id)


def resolve_profile(hass: HomeAssistant, source_entry_id: str) -> ProfileMapping:
    """Map every catalog metric of a source entry to an entity, without guessing."""
    registry = er.async_get(hass)
    by_key: dict[str, list[er.RegistryEntry]] = defaultdict(list)
    mapping = ProfileMapping()

    for entry in er.async_entries_for_config_entry(registry, source_entry_id):
        # Legacy unique IDs (e.g. "{email}_{key}") belong to an older source schema.
        if provider.unique_id_suffix(entry.unique_id, source_entry_id) is None:
            continue
        if (gear_id := provider.gear_uuid_of(entry.unique_id, source_entry_id)) is not None:
            mapping.gear.append(Gear(gear_id, entry.entity_id, entry.disabled_by is not None))
            continue
        if entry.translation_key:
            by_key[entry.translation_key].append(entry)

    for spec in provider.CATALOG:
        candidates = by_key.get(spec.translation_key, [])
        if spec.sport is not None:
            candidates = [
                c
                for c in candidates
                if provider.sport_of(spec.translation_key, c.unique_id, source_entry_id) == spec.sport
            ]
        mapping.metrics[spec.key] = _to_resolution(candidates)

    for key in provider.ACTIVITY_TRANSLATION_KEYS:
        mapping.activity_entities[key] = _to_resolution(by_key.get(key, []))
    mapping.route = _to_resolution(by_key.get(provider.ROUTE_TRANSLATION_KEY, []))
    mapping.last_synced = _to_resolution(by_key.get(provider.LAST_SYNCED_TRANSLATION_KEY, []))
    mapping.devices = _to_resolution(by_key.get(provider.DEVICES_TRANSLATION_KEY, []))
    mapping.gear.sort(key=lambda gear: gear.gear_id)
    return mapping


def disabled_activity_entities(hass: HomeAssistant, source_entry_id: str) -> list[str]:
    """Activity sensors the source disabled by default (never ones the user disabled)."""
    mapping = resolve_profile(hass, source_entry_id)
    return [
        r.entity_id
        for r in mapping.activity_entities.values()
        if r.status == "disabled"
        and r.entity_id is not None
        and r.disabled_by == er.RegistryEntryDisabler.INTEGRATION.value
    ]
