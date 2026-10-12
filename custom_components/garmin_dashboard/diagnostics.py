"""Diagnostics: versions, metric keys and status codes only."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import GarminDashboardConfigEntry
from .const import SCHEMA_VERSION


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: GarminDashboardConfigEntry) -> dict[str, Any]:
    """Return a report without values, names, entity IDs or unique IDs."""
    return {
        "schema_version": SCHEMA_VERSION,
        "profiles": [
            {
                "profile": f"profile_{index}",
                "source_status": profile.source_status,
                **profile.status_summary(),
            }
            for index, profile in enumerate(entry.runtime_data.profiles.values(), start=1)
        ],
    }
