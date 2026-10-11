"""Admin-only local WebSocket API."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .charts import CHARTS_BY_ID
from .const import DOMAIN, SCHEMA_VERSION
from .preferences import validate as validate_preferences
from .profile import ProfileRuntime


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register commands once per HA run; handlers look up live profiles."""
    websocket_api.async_register_command(hass, ws_profiles)
    websocket_api.async_register_command(hass, ws_snapshot)
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_chart)
    websocket_api.async_register_command(hass, ws_preferences_get)
    websocket_api.async_register_command(hass, ws_preferences_set)


def _data(hass: HomeAssistant):
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    return entries[0].runtime_data if entries else None


def _profiles(hass: HomeAssistant) -> dict[str, ProfileRuntime]:
    data = _data(hass)
    return data.profiles if data else {}


def _get_profile(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> ProfileRuntime | None:
    profile = _profiles(hass).get(msg["profile_id"])
    if profile is None:
        connection.send_error(msg["id"], "profile_not_found", "Profile not found")
    return profile


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/profiles"})
@websocket_api.require_admin
@callback
def ws_profiles(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """List profiles and their source status."""
    connection.send_result(msg["id"], {
        "schema_version": SCHEMA_VERSION,
        "profiles": [
            {
                "profile_id": profile.profile_id,
                "display_name": profile.display_name,
                "source_status": profile.source_status,
                "status": profile.status_summary(),
            }
            for profile in _profiles(hass).values()
        ],
    })


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/snapshot", vol.Required("profile_id"): str}
)
@websocket_api.require_admin
@callback
def ws_snapshot(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the current snapshot of one profile."""
    if (profile := _get_profile(hass, connection, msg)) is not None:
        connection.send_result(msg["id"], profile.snapshot())


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/subscribe", vol.Required("profile_id"): str}
)
@websocket_api.require_admin
@callback
def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Send a full snapshot, then a full snapshot on every change."""
    if (profile := _get_profile(hass, connection, msg)) is None:
        return
    msg_id = msg["id"]

    @callback
    def forward(snapshot: dict[str, Any]) -> None:
        connection.send_message(websocket_api.event_message(msg_id, snapshot))

    connection.subscriptions[msg_id] = profile.async_subscribe(forward)
    connection.send_result(msg_id)
    forward(profile.snapshot())


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/chart",
        vol.Required("profile_id"): str,
        vol.Required("chart_id"): vol.In(list(CHARTS_BY_ID)),
        vol.Optional("range_days"): int,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_chart(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return one chart's series, read from HA's own records."""
    if (profile := _get_profile(hass, connection, msg)) is None:
        return
    chart = CHARTS_BY_ID[msg["chart_id"]]
    if chart.method != "current" and "recorder" not in hass.config.components:
        connection.send_error(msg["id"], "recorder_unavailable", "Recorder is not running")
        return
    service = _data(hass).charts
    range_days = service.range_for(chart, msg.get("range_days"))
    connection.send_result(msg["id"], await service.async_chart(profile, chart, range_days))


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/preferences/get", vol.Required("profile_id"): str}
)
@websocket_api.require_admin
@callback
def ws_preferences_get(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return a profile's display preferences."""
    if _get_profile(hass, connection, msg) is not None:
        connection.send_result(msg["id"], _data(hass).preferences.get(msg["profile_id"]))


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/preferences/set",
        vol.Required("profile_id"): str,
        vol.Required("preferences"): dict,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_preferences_set(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Replace a profile's display preferences after strict validation."""
    if _get_profile(hass, connection, msg) is None:
        return
    try:
        validate_preferences(msg["preferences"])
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_preferences", str(err))
        return
    saved = await _data(hass).preferences.async_set(msg["profile_id"], msg["preferences"])
    connection.send_result(msg["id"], saved)
