"""Config flow: pick the Garmin source and optionally enable activity sensors."""

from __future__ import annotations

from typing import Any
import uuid

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_DISPLAY_NAME,
    CONF_PROFILE_ID,
    CONF_SOURCE_ENTRY_ID,
    CONF_SOURCES,
    DOMAIN,
    SOURCE_DOMAIN,
)
from .discovery import disabled_activity_entities

SOURCE_DOCS_URL = "https://github.com/cyberjunky/home-assistant-garmin_connect"
CONF_SOURCE = "source"
CONF_ENABLE_ACTIVITIES = "enable_activities"


def _default_display_name(source: ConfigEntry) -> str:
    # Source titles are often the Garmin login e-mail; never surface that as a name.
    return "Garmin" if "@" in source.title else source.title


class GarminDashboardConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up the single dashboard entry."""

    VERSION = 1

    def __init__(self) -> None:
        self._source: ConfigEntry | None = None

    def _sources(self) -> list[ConfigEntry]:
        return [
            entry
            for entry in self.hass.config_entries.async_entries(SOURCE_DOMAIN)
            if entry.disabled_by is None
        ]

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Find source entries; choose automatically when there is only one."""
        sources = self._sources()
        if not sources:
            return self.async_abort(
                reason="no_source", description_placeholders={"docs_url": SOURCE_DOCS_URL}
            )
        if len(sources) == 1:
            self._source = sources[0]
            return await self.async_step_activities()
        return await self.async_step_pick_source()

    async def async_step_pick_source(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask which account to show (one account until multi-profile lands in v0.3)."""
        sources = {entry.entry_id: entry for entry in self._sources()}
        if user_input is not None and user_input[CONF_SOURCE] in sources:
            self._source = sources[user_input[CONF_SOURCE]]
            return await self.async_step_activities()
        return self.async_show_form(
            step_id="pick_source",
            data_schema=vol.Schema(
                {vol.Required(CONF_SOURCE): vol.In({k: e.title for k, e in sources.items()})}
            ),
        )

    async def async_step_activities(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer to enable the source's activity sensors it ships disabled (spec §7.3.1)."""
        assert self._source is not None
        disabled = disabled_activity_entities(self.hass, self._source.entry_id)
        if disabled and user_input is None:
            return self.async_show_form(
                step_id="activities",
                data_schema=vol.Schema({vol.Required(CONF_ENABLE_ACTIVITIES, default=True): bool}),
            )
        if disabled and user_input and user_input[CONF_ENABLE_ACTIVITIES]:
            registry = er.async_get(self.hass)
            for entity_id in disabled:
                registry.async_update_entity(entity_id, disabled_by=None)
            self.hass.config_entries.async_schedule_reload(self._source.entry_id)
        return self._create()

    def _create(self) -> ConfigFlowResult:
        assert self._source is not None
        return self.async_create_entry(
            title="Garmin",
            data={
                CONF_SOURCES: [
                    {
                        CONF_PROFILE_ID: uuid.uuid4().hex,
                        CONF_SOURCE_ENTRY_ID: self._source.entry_id,
                        CONF_DISPLAY_NAME: _default_display_name(self._source),
                    }
                ]
            },
        )
