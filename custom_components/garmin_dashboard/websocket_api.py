"""Admin-only local WebSocket API (spec §12)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, SCHEMA_VERSION
from .profile import ProfileRuntime


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register commands once per HA run; handlers look up live profiles."""
    websocket_api.async_register_command(hass, ws_profiles)
    websocket_api.async_register_command(hass, ws_snapshot)
    websocket_api.async_register_command(hass, ws_subscribe)


def _profiles(hass: HomeAssistant) -> dict[str, ProfileRuntime]:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    return entries[0].runtime_data.profiles if entries else {}


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
