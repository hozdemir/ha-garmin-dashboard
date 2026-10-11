"""Contract for cyberjunky/home-assistant-garmin_connect.

Everything here was verified against a live install of source version 3.0.19
(see docs/phase0-findings.md). Metrics are matched by registry
``translation_key``; unique IDs are only used to tell sport-specific
duplicates apart and to find gear, never parsed by splitting on underscores.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SUPPORTED_VERSIONS: frozenset[str] = frozenset({"3.0.19"})

Section = Literal["movement", "recovery", "training"]
Kind = Literal["count", "distance", "duration", "energy", "percent", "score",
               "heart_rate", "power", "vo2max", "category", "hrv"]
FreshnessClass = Literal["intraday", "daily", "nightly", "slow", "event"]


@dataclass(frozen=True, slots=True)
class MetricSpec:
    """One canonical metric and where the source provides it."""

    key: str
    translation_key: str
    section: Section
    kind: Kind
    freshness: FreshnessClass
    # Set for metrics the source repeats once per sport under one translation_key.
    sport: str | None = None
    # Attribute holding the Garmin calendar date of the value, if any.
    date_attribute: str | None = None


CATALOG: tuple[MetricSpec, ...] = (
    MetricSpec("steps", "total_steps", "movement", "count", "daily"),
    MetricSpec("steps_goal", "daily_step_goal", "movement", "count", "daily"),
    MetricSpec("distance_day", "total_distance", "movement", "distance", "daily"),
    MetricSpec("calories_active", "active_calories", "movement", "energy", "daily"),
    MetricSpec("calories_total", "total_calories", "movement", "energy", "daily"),
    MetricSpec("body_battery", "body_battery_most_recent", "recovery", "percent", "intraday"),
    MetricSpec("sleep_score", "sleep_score", "recovery", "score", "nightly"),
    MetricSpec("sleep_duration", "sleep_duration", "recovery", "duration", "nightly"),
    MetricSpec("hrv_status", "hrv_status", "recovery", "category", "nightly",
               date_attribute="calendarDate"),
    MetricSpec("hrv_last_night", "hrv_last_night_avg", "recovery", "hrv", "nightly"),
    MetricSpec("resting_hr", "resting_heart_rate", "recovery", "heart_rate", "daily"),
    MetricSpec("training_readiness", "training_readiness", "training", "percent", "daily"),
    MetricSpec("training_status", "training_status", "training", "category", "daily"),
    MetricSpec("recovery_time", "recovery_time", "training", "duration", "intraday"),
    MetricSpec("vo2max", "vo2_max", "training", "vo2max", "slow"),
    MetricSpec("ftp_cycling", "functional_threshold_power", "training", "power", "slow",
               sport="cycling", date_attribute="calendar_date"),
    MetricSpec("ftp_running", "functional_threshold_power", "training", "power", "slow",
               sport="running", date_attribute="calendar_date"),
)

CATALOG_BY_KEY: dict[str, MetricSpec] = {spec.key: spec for spec in CATALOG}

# Source sensors the Activities screen needs; disabled by the source by default.
ACTIVITY_TRANSLATION_KEYS: tuple[str, ...] = ("last_activity", "last_activities")
ROUTE_TRANSLATION_KEY = "last_activity_route"
LAST_SYNCED_TRANSLATION_KEY = "last_synced"

# Unique-ID infixes after "{entry_id}_" for sport-specific sensors.
_SPORT_PREFIXES: dict[str, str] = {"functional_threshold_power": "ftp_"}
_GEAR_PREFIX = "gear_"


def unique_id_suffix(unique_id: str, source_entry_id: str) -> str | None:
    """Strip the exact entry-id prefix, or None for foreign/legacy unique IDs."""
    prefix = f"{source_entry_id}_"
    if not unique_id.startswith(prefix):
        return None
    return unique_id[len(prefix):]


def sport_of(translation_key: str, unique_id: str, source_entry_id: str) -> str | None:
    """Return the sport a sport-specific sensor belongs to."""
    infix = _SPORT_PREFIXES.get(translation_key)
    suffix = unique_id_suffix(unique_id, source_entry_id)
    if infix is None or suffix is None or not suffix.startswith(infix):
        return None
    return suffix[len(infix):] or None


def gear_uuid_of(unique_id: str, source_entry_id: str) -> str | None:
    """Return the gear UUID for a gear sensor, else None."""
    suffix = unique_id_suffix(unique_id, source_entry_id)
    if suffix is None or not suffix.startswith(_GEAR_PREFIX):
        return None
    return suffix[len(_GEAR_PREFIX):] or None
