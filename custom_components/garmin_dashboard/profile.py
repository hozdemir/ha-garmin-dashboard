"""Runtime state of one dashboard profile (one source config entry)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util

from .activities import normalize_activities, normalize_route, parse_aware_time
from .const import DOMAIN, SCHEMA_VERSION, SOURCE_DOMAIN, UPDATE_DEBOUNCE_SECONDS
from .discovery import ProfileMapping, Resolution, resolve_profile
from .normalization import build_metric
from .plan import training_plan
from .providers import cyberjunky as provider

SnapshotListener = Callable[[dict[str, Any]], None]

_GEAR_SPEC = provider.MetricSpec("gear_distance", "", "training", "distance", "slow")

_SOURCE_STATUS = {
    ConfigEntryState.LOADED: "ready",
    ConfigEntryState.SETUP_IN_PROGRESS: "starting",
    ConfigEntryState.NOT_LOADED: "starting",
    ConfigEntryState.SETUP_RETRY: "starting",
    ConfigEntryState.UNLOAD_IN_PROGRESS: "starting",
}


class ProfileRuntime:
    """Tracks the entities of one source entry and pushes snapshots."""

    def __init__(self, hass: HomeAssistant, profile_id: str, source_entry_id: str, display_name: str) -> None:
        self.hass = hass
        self.profile_id = profile_id
        self.source_entry_id = source_entry_id
        self.display_name = display_name
        self.mapping = ProfileMapping()
        self.source_version: str | None = None
        self._revision = 0
        self._listeners: set[SnapshotListener] = set()
        self._last_available: dict[str, dict[str, Any]] = {}
        self._activity_report: dict[str, Any] = {}
        self._unsub_states: CALLBACK_TYPE | None = None
        self._unsub_registry: CALLBACK_TYPE | None = None
        self._unsub_debounce: CALLBACK_TYPE | None = None

    async def async_start(self) -> None:
        """Resolve the mapping and start listening."""
        try:
            self.source_version = str((await async_get_integration(self.hass, SOURCE_DOMAIN)).version)
        except Exception:  # noqa: BLE001 - a missing source is reported via source_status
            self.source_version = None
        self._remap()
        self._unsub_registry = self.hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, self._on_registry_updated)

    @callback
    def async_stop(self) -> None:
        """Drop every listener and subscription."""
        for unsub in (self._unsub_states, self._unsub_registry, self._unsub_debounce):
            if unsub is not None:
                unsub()
        self._unsub_states = self._unsub_registry = self._unsub_debounce = None
        self._listeners.clear()
        for issue in ("source_removed", "unsupported_source"):
            ir.async_delete_issue(self.hass, DOMAIN, f"{issue}_{self.profile_id}")

    @property
    def compatible(self) -> bool:
        return self.source_version in provider.SUPPORTED_VERSIONS

    @property
    def source_status(self) -> str:
        entry = self.hass.config_entries.async_get_entry(self.source_entry_id)
        if entry is None:
            return "removed"
        if not self.compatible:
            return "unsupported"
        # Garmin sign-ins expire (e.g. MFA sessions); the source then waits for a new login.
        if any(entry.async_get_active_flows(self.hass, {SOURCE_REAUTH})):
            return "reauth"
        return _SOURCE_STATUS.get(entry.state, "offline")

    @callback
    def _remap(self) -> None:
        self.mapping = resolve_profile(self.hass, self.source_entry_id)
        if self._unsub_states is not None:
            self._unsub_states()
        self._unsub_states = async_track_state_change_event(
            self.hass, sorted(self.mapping.entity_ids), self._on_state_changed
        )
        self._sync_issues()

    @callback
    def _sync_issues(self) -> None:
        """Surface problems the user can fix in HA's Repairs, and clear them once fixed."""
        status = self.source_status
        issues = {
            "source_removed": (status == "removed", {"profile": self.display_name}),
            "unsupported_source": (
                status == "unsupported",
                {
                    "profile": self.display_name,
                    "version": self.source_version or "?",
                    "supported": ", ".join(sorted(provider.SUPPORTED_VERSIONS)),
                },
            ),
        }
        for key, (active, placeholders) in issues.items():
            issue_id = f"{key}_{self.profile_id}"
            if active:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key=key,
                    translation_placeholders=placeholders,
                )
            else:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    @callback
    def _on_registry_updated(self, event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        entity_id = event.data["entity_id"]
        entry = er.async_get(self.hass).async_get(entity_id)
        if entry is None or entry.config_entry_id == self.source_entry_id or entity_id in self.mapping.entity_ids:
            self._remap()
            self._schedule_push()

    @callback
    def _on_state_changed(self, event: Event) -> None:
        self._schedule_push()

    @callback
    def _schedule_push(self) -> None:
        if self._unsub_debounce is None:
            self._unsub_debounce = async_call_later(self.hass, UPDATE_DEBOUNCE_SECONDS, self._push)

    @callback
    def _push(self, _now: Any = None) -> None:
        self._unsub_debounce = None
        if not self._listeners:
            return
        snapshot = self.snapshot()
        for listener in list(self._listeners):
            listener(snapshot)

    @callback
    def async_refresh(self) -> None:
        """Re-resolve sensors and re-read HA's states. Never asks Garmin for anything."""
        self._remap()
        self._push()

    @callback
    def async_subscribe(self, listener: SnapshotListener) -> CALLBACK_TYPE:
        self._listeners.add(listener)

        @callback
        def unsubscribe() -> None:
            self._listeners.discard(listener)

        return unsubscribe

    @callback
    def snapshot(self) -> dict[str, Any]:
        """Build the ProfileSnapshot from current states."""
        self._revision += 1
        now = dt_util.utcnow()
        metrics: dict[str, dict[str, Any]] = {}
        for spec in provider.CATALOG:
            resolution = self.mapping.metrics.get(spec.key)
            if resolution is None:
                continue
            state = self.hass.states.get(resolution.entity_id) if resolution.entity_id else None
            metric = build_metric(spec, resolution, state, now)
            metrics[spec.key] = self._with_last_value(metric)

        return {
            "schema_version": SCHEMA_VERSION,
            "profile_id": self.profile_id,
            "display_name": self.display_name,
            "revision": self._revision,
            # When the dashboard read Home Assistant's states for this snapshot.
            "observed_at": now.isoformat(),
            "source_status": self.source_status,
            **self._source_sync(),
            "metrics": metrics,
            "gear": self._gear(),
            "sensors": self._connected_sensors(),
            "plan": self._plan(),
            **self._activities(),
            "capabilities": self._capabilities(metrics),
        }

    @callback
    def metric(self, key: str) -> dict[str, Any] | None:
        """One normalized metric, without bumping the snapshot revision."""
        spec = provider.CATALOG_BY_KEY.get(key)
        resolution = self.mapping.metrics.get(key)
        if spec is None or resolution is None:
            return None
        state = self.hass.states.get(resolution.entity_id) if resolution.entity_id else None
        return build_metric(spec, resolution, state, dt_util.utcnow())

    def _with_last_value(self, metric: dict[str, Any]) -> dict[str, Any]:
        """Keep showing the last good value (marked stale) during an outage."""
        key = metric["key"]
        if metric["status"] == "available":
            self._last_available[key] = metric
            return metric
        last = self._last_available.get(key)
        if metric["status"] == "unavailable" and last is not None:
            return {
                **metric,
                "value": last["value"],
                "unit": last["unit"],
                "source_date": last["source_date"],
                "freshness": "stale",
            }
        return metric

    def _resolved_state(self, resolution: Resolution):
        if resolution.status != "resolved" or resolution.entity_id is None:
            return None
        state = self.hass.states.get(resolution.entity_id)
        return None if state is None or state.attributes.get("restored") else state

    def _source_sync(self) -> dict[str, Any]:
        """When a Garmin device last synced, and which model, if the source says.

        Any Garmin device counts (watch, bike computer, scale...). The daily
        summary's time is empty until a device syncs on the new Garmin day, so the
        last used device's own sync time is used as well; the newer one wins.
        """
        summary = self._resolved_state(self.mapping.last_synced)
        summary_time = parse_aware_time(summary.state) if summary is not None else None
        device_time, model = None, None
        devices = self._resolved_state(self.mapping.devices)
        if devices is not None:
            last_used = devices.attributes.get(provider.LAST_USED_DEVICE_ATTRIBUTE)
            if isinstance(last_used, dict):
                device_time = parse_aware_time(last_used.get("lastSyncTime"))
                model = _device_model(devices.attributes.get(provider.DEVICE_LIST_ATTRIBUTE), last_used)
        if device_time is not None and (summary_time is None or device_time >= summary_time):
            return {"source_synced_at": dt_util.as_utc(device_time).isoformat(), "source_sync_device": model}
        if summary_time is not None:
            return {"source_synced_at": dt_util.as_utc(summary_time).isoformat(), "source_sync_device": None}
        return {"source_synced_at": None, "source_sync_device": None}

    def _plan(self) -> dict[str, Any] | None:
        """Scheduled workouts and the goal race, dated by HA's local calendar day."""
        attrs = {}
        for name, resolution in self.mapping.plan.items():
            state = self._resolved_state(resolution)
            attrs[name] = dict(state.attributes) if state is not None else None
        return training_plan(attrs.get("today"), attrs.get("next"), attrs.get("goal"), dt_util.now().date())

    def _connected_sensors(self) -> list[dict[str, Any]]:
        """Paired sensors and their batteries; never serial numbers, IDs or image URLs.

        The source's connection and low-battery times carry no time zone, so they
        are not shown rather than guessed.
        """
        state = self._resolved_state(self.mapping.connected_sensors)
        raw = state.attributes.get("sensors") if state is not None else None
        if not isinstance(raw, list):
            return []
        sensors = []
        for item in raw[:20]:
            if not isinstance(item, dict):
                continue
            level = item.get("batteryLevel")
            sensors.append(
                {
                    "type": _short_text(item.get("sensorType"), 40) or "UNKNOWN",
                    "manufacturer": _short_text(item.get("manufacturer"), 40),
                    "battery_status": _short_text(item.get("batteryStatus"), 20),
                    "battery_level": level
                    if isinstance(level, int) and not isinstance(level, bool) and 0 <= level <= 100
                    else None,
                }
            )
        return sensors

    def _activity_state(self, key: str):
        resolution = self.mapping.activity_entities.get(key)
        if resolution is None or resolution.status != "resolved" or resolution.entity_id is None:
            return None
        state = self.hass.states.get(resolution.entity_id)
        if state is None or state.attributes.get("restored"):
            return None
        return state

    def _activities(self) -> dict[str, Any]:
        """Recent activities exactly as far as the source provides them."""
        listing = self._activity_state("last_activities")
        latest = self._activity_state("last_activity")
        result = normalize_activities(
            listing.attributes.get("last_activities") if listing else None,
            dict(latest.attributes) if latest else None,
        )
        self._activity_report = {
            "skipped": result["skipped"],
            "key_collisions_possible": result["key_collisions_possible"],
        }
        return {
            "activities": result["activities"],
            "activities_truncated": result["truncated"],
        }

    @callback
    def route(self) -> dict[str, Any] | None:
        """The last synced route; never linked to an activity (the source gives no ID)."""
        resolution = self.mapping.route
        if resolution.status != "resolved" or resolution.entity_id is None:
            return None
        state = self.hass.states.get(resolution.entity_id)
        if state is None or state.attributes.get("restored"):
            return None
        return normalize_route(state.attributes)

    def _gear(self) -> list[dict[str, Any]]:
        gear: list[dict[str, Any]] = []
        for item in self.mapping.gear:
            if item.disabled:
                continue
            state = self.hass.states.get(item.entity_id)
            if state is None or state.attributes.get("restored"):
                continue
            metric = build_metric(
                _GEAR_SPEC,
                Resolution("resolved", item.entity_id),
                state,
                dt_util.utcnow(),
            )
            name = state.attributes.get("friendly_name") or state.attributes.get("gear_model_name")
            gear.append(
                {
                    "id": item.gear_id,
                    "name": name if isinstance(name, str) else None,
                    "status": metric["status"],
                    "distance_meters": metric["value"],
                    "retired": str(state.attributes.get("gear_status_name", "")).lower() == "retired",
                }
            )
        return gear

    def _capabilities(self, metrics: dict[str, dict[str, Any]]) -> list[str]:
        sections = {
            provider.CATALOG_BY_KEY[key].section
            for key, metric in metrics.items()
            if metric["status"] not in ("missing", "ambiguous")
        }
        capabilities = sorted(sections)
        if self.mapping.gear:
            capabilities.append("gear")
        if any(r.status == "resolved" for r in self.mapping.activity_entities.values()):
            capabilities.append("activities")
        if self.mapping.route.status == "resolved":
            capabilities.append("route")
        return capabilities

    def status_summary(self) -> dict[str, Any]:
        """Counts for the status screen and diagnostics; no values."""
        counts: dict[str, int] = {}
        for resolution in self.mapping.metrics.values():
            counts[resolution.status] = counts.get(resolution.status, 0) + 1
        return {
            "source_version": self.source_version,
            "compatible": self.compatible,
            "metric_status": {key: r.status for key, r in self.mapping.metrics.items()},
            "metric_counts": counts,
            "activity_sensors": {key: r.status for key, r in self.mapping.activity_entities.items()},
            "gear_count": len(self.mapping.gear),
            "route_sensor": self.mapping.route.status,
            "activity_report": self._activity_report,
        }


def _device_model(device_list: Any, last_used: dict[str, Any]) -> str | None:
    """Model name of the last used device, matched by device ID."""
    device_id = last_used.get("userDeviceId")
    if device_id is None or not isinstance(device_list, list):
        return None
    for device in device_list:
        if isinstance(device, dict) and str(device.get("deviceId")) == str(device_id):
            model = device.get("productDisplayName")
            return model.strip()[:60] or None if isinstance(model, str) else None
    return None


def _short_text(value: Any, limit: int) -> str | None:
    return value.strip()[:limit] or None if isinstance(value, str) else None
