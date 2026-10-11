"""Garmin Dashboard: a ready-made Garmin panel for Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from . import websocket_api
from .charts import ChartService
from .const import (
    CONF_DISPLAY_NAME,
    CONF_PROFILE_ID,
    CONF_SOURCE_ENTRY_ID,
    CONF_SOURCES,
    DOMAIN,
    PANEL_COMPONENT,
    PANEL_ICON,
    PANEL_JS,
    PANEL_URL_PATH,
    STATIC_URL,
)
from .preferences import PreferenceStore
from .profile import ProfileRuntime

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_WWW = Path(__file__).parent / "www"


@dataclass
class DashboardData:
    """Runtime data of the single dashboard config entry."""

    charts: ChartService
    preferences: PreferenceStore
    profiles: dict[str, ProfileRuntime] = field(default_factory=dict)


type GarminDashboardConfigEntry = ConfigEntry[DashboardData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register things that live for the whole HA run (cannot be unregistered)."""
    websocket_api.async_register(hass)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL, str(_WWW), cache_headers=False)]
    )
    return True


def _asset_version() -> str:
    """Content hash so browsers never run a stale bundle after an update."""
    path = _WWW / PANEL_JS
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12] if path.exists() else "missing"


async def async_setup_entry(hass: HomeAssistant, entry: GarminDashboardConfigEntry) -> bool:
    """Start profiles and register the panel."""
    preferences = PreferenceStore(hass)
    await preferences.async_load()
    data = DashboardData(charts=ChartService(hass), preferences=preferences)
    for source in entry.data[CONF_SOURCES]:
        profile = ProfileRuntime(
            hass, source[CONF_PROFILE_ID], source[CONF_SOURCE_ENTRY_ID], source[CONF_DISPLAY_NAME]
        )
        await profile.async_start()
        data.profiles[profile.profile_id] = profile
    entry.runtime_data = data

    version = await hass.async_add_executor_job(_asset_version)
    # A reload may run while an old registration exists; never register twice.
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_COMPONENT,
        sidebar_title="Garmin",
        sidebar_icon=PANEL_ICON,
        module_url=f"{STATIC_URL}/{PANEL_JS}?v={version}",
        require_admin=True,
        config={"schema_version": 1},
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GarminDashboardConfigEntry) -> bool:
    """Remove the panel and every listener; leave the source untouched."""
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    for profile in entry.runtime_data.profiles.values():
        profile.async_stop()
    return True


async def async_remove_entry(hass: HomeAssistant, entry: GarminDashboardConfigEntry) -> None:
    """Delete only this integration's own preferences."""
    await PreferenceStore(hass).async_remove()
