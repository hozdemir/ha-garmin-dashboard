"""Per-profile display preferences, stored with HA's versioned Store.

Preferences only hide and reorder things; they never change what is read or
how it is matched. Visibility is stored as *hidden* lists so anything added in
a later release shows up by default without touching saved choices.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .charts import CHARTS, DEFAULT_TREND_RANGE, TREND_RANGES
from .const import DOMAIN
from .providers.cyberjunky import CATALOG

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.preferences"

SECTIONS: tuple[str, ...] = ("movement", "recovery", "training", "gear", "activities")
METRIC_KEYS: frozenset[str] = frozenset(spec.key for spec in CATALOG)
CHART_IDS: frozenset[str] = frozenset(chart.id for chart in CHARTS)

PREFERENCES_SCHEMA = vol.Schema(
    {
        vol.Required("section_order"): [vol.In(SECTIONS)],
        vol.Required("hidden_sections"): [vol.In(SECTIONS)],
        vol.Required("hidden_metrics"): [vol.In(METRIC_KEYS)],
        vol.Required("hidden_charts"): [vol.In(CHART_IDS)],
        vol.Required("trend_range_days"): vol.In(TREND_RANGES),
        vol.Required("show_route"): bool,
    },
    extra=vol.PREVENT_EXTRA,
)


def default_preferences() -> dict[str, Any]:
    """Everything visible except charts that are off by default."""
    return {
        "section_order": list(SECTIONS),
        "hidden_sections": [],
        "hidden_metrics": [],
        "hidden_charts": sorted(chart.id for chart in CHARTS if not chart.default_visible),
        "trend_range_days": DEFAULT_TREND_RANGE,
        "show_route": True,
    }


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def sanitize(raw: Any) -> dict[str, Any]:
    """Drop unknown keys from stored data and fill in anything new.

    Used on load: a release that removes a metric or chart must not break a
    stored profile, and a release that adds a section must still show it.
    """
    prefs = default_preferences()
    if not isinstance(raw, dict):
        return prefs
    if isinstance(order := raw.get("section_order"), list):
        known = _dedupe([s for s in order if s in SECTIONS])
        prefs["section_order"] = known + [s for s in SECTIONS if s not in known]
    for key, allowed in (
        ("hidden_sections", SECTIONS),
        ("hidden_metrics", METRIC_KEYS),
        ("hidden_charts", CHART_IDS),
    ):
        if isinstance(values := raw.get(key), list):
            prefs[key] = _dedupe([v for v in values if v in allowed])
    if raw.get("trend_range_days") in TREND_RANGES:
        prefs["trend_range_days"] = raw["trend_range_days"]
    if isinstance(raw.get("show_route"), bool):
        prefs["show_route"] = raw["show_route"]
    return prefs


def validate(raw: Any) -> dict[str, Any]:
    """Strict validation for writes from the panel; unknown keys are rejected."""
    prefs = PREFERENCES_SCHEMA(raw)
    if sorted(prefs["section_order"]) != sorted(SECTIONS):
        raise vol.Invalid("section_order must list every section exactly once")
    for key in ("hidden_sections", "hidden_metrics", "hidden_charts"):
        prefs[key] = _dedupe(prefs[key])
    return prefs


class PreferenceStore:
    """Preferences of all profiles in one Store file."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        stored = await self._store.async_load() or {}
        profiles = stored.get("profiles", {}) if isinstance(stored, dict) else {}
        self._data = {pid: sanitize(prefs) for pid, prefs in profiles.items()}

    def get(self, profile_id: str) -> dict[str, Any]:
        return dict(self._data.get(profile_id) or default_preferences())

    async def async_set(self, profile_id: str, prefs: dict[str, Any]) -> dict[str, Any]:
        self._data[profile_id] = validate(prefs)
        await self._store.async_save({"profiles": self._data})
        return self.get(profile_id)

    async def async_prune(self, keep: set[str]) -> None:
        """Forget preferences of profiles that no longer exist."""
        if set(self._data) - keep:
            self._data = {pid: prefs for pid, prefs in self._data.items() if pid in keep}
            await self._store.async_save({"profiles": self._data})

    async def async_remove(self) -> None:
        await self._store.async_remove()
