"""Config and options flows: choose Garmin accounts, name them, offer activity sensors."""

from __future__ import annotations

from typing import Any
import uuid

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

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
HACS_SOURCE_URL = (
    "https://my.home-assistant.io/redirect/hacs_repository/"
    "?owner=cyberjunky&repository=home-assistant-garmin_connect&category=integration"
)
SOURCE_SETUP_URL = "https://my.home-assistant.io/redirect/config_flow_start/?domain=garmin_connect"
CONF_ACCOUNTS = "accounts"
CONF_ENABLE_ACTIVITIES = "enable_activities"
MAX_NAME_LENGTH = 40


def _available_sources(hass: HomeAssistant) -> dict[str, ConfigEntry]:
    return {
        entry.entry_id: entry
        for entry in hass.config_entries.async_entries(SOURCE_DOMAIN)
        if entry.disabled_by is None
    }


def _default_name(source: ConfigEntry | None, taken: set[str]) -> str:
    """Source titles are often the Garmin login e-mail; never surface that as a name."""
    base = source.title if source is not None and "@" not in source.title else "Garmin"
    base = base[:MAX_NAME_LENGTH]
    name, n = base, 2
    while name.casefold() in taken:
        name, n = f"{base} {n}", n + 1
    return name


class _AccountSteps:
    """Steps shared by setup and later changes: pick accounts, name them, activities."""

    hass: HomeAssistant

    def _init_accounts(self, existing: list[dict[str, Any]]) -> None:
        # Profiles that already exist keep their ID, and with it their preferences.
        self._existing = {p[CONF_SOURCE_ENTRY_ID]: p for p in existing}
        self._selected: list[str] = []
        self._names: dict[str, str] = {}

    def _account_options(self) -> list[SelectOptionDict]:
        sources = _available_sources(self.hass)
        options = [SelectOptionDict(value=entry_id, label=entry.title) for entry_id, entry in sources.items()]
        # A profile whose Garmin account was removed from HA can still be deselected here.
        for entry_id, profile in self._existing.items():
            if entry_id not in sources:
                options.append(SelectOptionDict(value=entry_id, label=f"{profile[CONF_DISPLAY_NAME]} (removed)"))
        return options

    def _accounts_form(self, step_id: str, default: list[str], errors: dict[str, str] | None = None):
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id=step_id,
            data_schema=vol.Schema({
                vol.Required(CONF_ACCOUNTS, default=default): SelectSelector(
                    SelectSelectorConfig(options=self._account_options(), multiple=True,
                                         mode=SelectSelectorMode.LIST)
                )
            }),
            errors=errors or {},
        )

    def _accept_accounts(self, chosen: list[str]) -> str | None:
        """Store the choice; return an error key if it is not acceptable."""
        valid = {o["value"] for o in self._account_options()}
        chosen = [c for c in dict.fromkeys(chosen) if c in valid]
        if not chosen:
            return "no_accounts"
        self._selected = chosen
        return None

    def _names_form(self, errors: dict[str, str] | None = None):
        sources = _available_sources(self.hass)
        taken: set[str] = set()
        schema: dict[Any, Any] = {}
        for index, entry_id in enumerate(self._selected, start=1):
            current = self._names.get(entry_id) or (
                self._existing[entry_id][CONF_DISPLAY_NAME] if entry_id in self._existing
                else _default_name(sources.get(entry_id), taken)
            )
            taken.add(current.casefold())
            schema[vol.Required(f"name_{index}", default=current)] = TextSelector()
        labels = "\n".join(
            f"{index}. {sources[e].title if e in sources else self._existing[e][CONF_DISPLAY_NAME]}"
            for index, e in enumerate(self._selected, start=1)
        )
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="names",
            data_schema=vol.Schema(schema),
            description_placeholders={"accounts": labels},
            errors=errors or {},
        )

    def _accept_names(self, user_input: dict[str, Any]) -> str | None:
        names: dict[str, str] = {}
        seen: set[str] = set()
        for index, entry_id in enumerate(self._selected, start=1):
            name = str(user_input.get(f"name_{index}", "")).strip()
            if not name or len(name) > MAX_NAME_LENGTH:
                return "invalid_name"
            if name.casefold() in seen:
                return "name_taken"
            seen.add(name.casefold())
            names[entry_id] = name
        self._names = names
        return None

    def _pending_activity_entities(self) -> list[str]:
        """Integration-disabled activity sensors of newly added accounts only."""
        return [
            entity_id
            for entry_id in self._selected
            if entry_id not in self._existing
            for entity_id in disabled_activity_entities(self.hass, entry_id)
        ]

    def _activities_form(self):
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="activities",
            data_schema=vol.Schema({vol.Required(CONF_ENABLE_ACTIVITIES, default=True): bool}),
        )

    def _apply_activities(self, enable: bool) -> None:
        pending = self._pending_activity_entities()
        if not enable or not pending:
            return
        registry = er.async_get(self.hass)
        reload: set[str] = set()
        for entity_id in pending:
            entry = registry.async_update_entity(entity_id, disabled_by=None)
            if entry.config_entry_id:
                reload.add(entry.config_entry_id)
        for entry_id in reload:
            self.hass.config_entries.async_schedule_reload(entry_id)

    def _profiles(self) -> list[dict[str, Any]]:
        sources = _available_sources(self.hass)
        taken = {n.casefold() for n in self._names.values()}
        profiles = []
        for entry_id in self._selected:
            existing = self._existing.get(entry_id)
            name = self._names.get(entry_id) or (
                existing[CONF_DISPLAY_NAME] if existing else _default_name(sources.get(entry_id), taken)
            )
            profiles.append({
                CONF_PROFILE_ID: existing[CONF_PROFILE_ID] if existing else uuid.uuid4().hex,
                CONF_SOURCE_ENTRY_ID: entry_id,
                CONF_DISPLAY_NAME: name,
            })
        return profiles


class GarminDashboardConfigFlow(_AccountSteps, ConfigFlow, domain=DOMAIN):
    """Set up the single dashboard entry."""

    VERSION = 1

    def __init__(self) -> None:
        self._init_accounts([])

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> GarminDashboardOptionsFlow:
        return GarminDashboardOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Find source entries; ask nothing when there is exactly one."""
        sources = _available_sources(self.hass)
        if not sources:
            return self.async_abort(
                reason="no_source",
                description_placeholders={
                    "docs_url": SOURCE_DOCS_URL, "hacs_url": HACS_SOURCE_URL, "setup_url": SOURCE_SETUP_URL,
                },
            )
        if len(sources) == 1:
            self._selected = list(sources)
            return await self.async_step_activities()
        return await self.async_step_accounts()

    async def async_step_accounts(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose which Garmin accounts to show (all by default)."""
        if user_input is not None:
            if error := self._accept_accounts(user_input[CONF_ACCOUNTS]):
                return self._accounts_form("accounts", user_input[CONF_ACCOUNTS], {"base": error})
            return await self.async_step_names()
        return self._accounts_form("accounts", list(_available_sources(self.hass)))

    async def async_step_names(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Name each profile; names show in the panel's profile picker."""
        if user_input is not None:
            if error := self._accept_names(user_input):
                return self._names_form({"base": error})
            return await self.async_step_activities()
        return self._names_form()

    async def async_step_activities(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Offer to enable activity sensors the source ships disabled."""
        if self._pending_activity_entities() and user_input is None:
            return self._activities_form()
        self._apply_activities(bool(user_input and user_input[CONF_ENABLE_ACTIVITIES]))
        return self.async_create_entry(title="Garmin", data={CONF_SOURCES: self._profiles()})


class GarminDashboardOptionsFlow(_AccountSteps, OptionsFlow):
    """Add or remove accounts and rename profiles later."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._init_accounts(self.config_entry.data[CONF_SOURCES])
        return await self.async_step_accounts()

    async def async_step_accounts(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            if error := self._accept_accounts(user_input[CONF_ACCOUNTS]):
                return self._accounts_form("accounts", user_input[CONF_ACCOUNTS], {"base": error})
            return await self.async_step_names()
        return self._accounts_form("accounts", list(self._existing))

    async def async_step_names(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            if error := self._accept_names(user_input):
                return self._names_form({"base": error})
            return await self.async_step_activities()
        return self._names_form()

    async def async_step_activities(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._pending_activity_entities() and user_input is None:
            return self._activities_form()
        self._apply_activities(bool(user_input and user_input[CONF_ENABLE_ACTIVITIES]))
        self.hass.config_entries.async_update_entry(
            self.config_entry, data={**self.config_entry.data, CONF_SOURCES: self._profiles()}
        )
        self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
        return self.async_create_entry(data={})
