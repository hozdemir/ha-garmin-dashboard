"""Shared fixtures: a synthetic garmin_connect source loaded into a test HA."""

from __future__ import annotations

from collections.abc import Generator
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "cyberjunky_3_0_19.json").read_text())


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(request: pytest.FixtureRequest) -> None:
    """Load integrations from custom_components/.

    The recorder must be set up before `hass`, so tests that use it get it first.
    """
    if "recorder_mock" in request.fixturenames:
        request.getfixturevalue("recorder_mock")
    request.getfixturevalue("enable_custom_integrations")


@pytest.fixture(autouse=True)
def source_version() -> Generator[MagicMock]:
    """Pretend the source integration is installed at the fixture's version."""
    integration = MagicMock(version=FIXTURE["source_version"])
    with patch(
        "custom_components.garmin_dashboard.profile.async_get_integration",
        return_value=integration,
    ):
        yield integration


@pytest.fixture(autouse=True)
def no_panel_frontend() -> Generator[None]:
    """The real frontend package is not installed in tests; keep panel registration local."""
    panels: dict[str, dict[str, Any]] = {}

    async def register(hass: HomeAssistant, **kwargs: Any) -> None:
        if kwargs["frontend_url_path"] in panels:
            raise ValueError("Overwriting panel")
        panels[kwargs["frontend_url_path"]] = kwargs

    def remove(hass: HomeAssistant, url_path: str, **_: Any) -> None:
        panels.pop(url_path, None)

    with (
        patch("custom_components.garmin_dashboard.panel_custom.async_register_panel", side_effect=register),
        patch("custom_components.garmin_dashboard.frontend.async_remove_panel", side_effect=remove),
        patch("homeassistant.components.http.HomeAssistantHTTP.async_register_static_paths"),
    ):
        yield panels


def load_source(
    hass: HomeAssistant,
    *,
    states: bool = True,
    overrides: dict[str, str] | None = None,
) -> MockConfigEntry:
    """Register the fixture's entities under a loaded garmin_connect entry."""
    source = MockConfigEntry(
        domain="garmin_connect", entry_id=FIXTURE["source_entry_id"], title="user@example.com"
    )
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    registry = er.async_get(hass)
    for item in FIXTURE["entities"]:
        domain, object_id = item["entity_id"].split(".", 1)
        registry.async_get_or_create(
            domain,
            "garmin_connect",
            item["unique_id"],
            suggested_object_id=object_id,
            config_entry=source,
            translation_key=item["translation_key"],
            original_name=item["original_name"],
            disabled_by=er.RegistryEntryDisabler(item["disabled_by"]) if item["disabled_by"] else None,
        )
    if states:
        for item in FIXTURE["states"]:
            value = (overrides or {}).get(item["entity_id"], item["state"])
            hass.states.async_set(item["entity_id"], value, item["attributes"])
    return source


def entity_for(translation_key: str, sport: str | None = None) -> str:
    """Entity ID of a fixture sensor by translation key (and sport)."""
    for item in FIXTURE["entities"]:
        if item["translation_key"] == translation_key and (sport is None or item["unique_id"].endswith(f"_{sport}")):
            return item["entity_id"]
    raise KeyError(translation_key)
