"""Constants for Garmin Dashboard."""

from typing import Final

DOMAIN: Final = "garmin_dashboard"
SOURCE_DOMAIN: Final = "garmin_connect"

PANEL_URL_PATH: Final = "garmin"
PANEL_COMPONENT: Final = "garmin-dashboard-panel"
PANEL_ICON: Final = "mdi:watch"
STATIC_URL: Final = "/garmin_dashboard_static"
PANEL_JS: Final = "garmin-dashboard-panel.js"

CONF_SOURCES: Final = "sources"
CONF_PROFILE_ID: Final = "profile_id"
CONF_SOURCE_ENTRY_ID: Final = "source_entry_id"
CONF_DISPLAY_NAME: Final = "display_name"

SCHEMA_VERSION: Final = 1

# Coalesce bursts of state events for one profile into a single push.
UPDATE_DEBOUNCE_SECONDS: Final = 0.25
