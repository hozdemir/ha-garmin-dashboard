"""Build a synthetic test fixture from a raw source dump.

Usage: python make_fixture.py <source_dump.json> <fixture_out.json>

Keeps only the *shape* of the source: translation keys, unique-ID schemes,
disabled flags, units, device/state classes and attribute names. Every value,
name, identifier and coordinate is replaced with synthetic data, so the output
is safe to commit (spec §17: fixtures are never real personal data).
"""

import json
import sys
import uuid

FAKE_ENTRY_ID = "01SOURCEENTRY000000000000"
FAKE_EMAIL = "user@example.com"

# Plausible synthetic values for the states the tests read; everything else
# numeric becomes 1, so no real measurement survives.
SYNTHETIC = {
    "total_steps": "8500", "daily_step_goal": "10000", "total_distance": "6200",
    "active_calories": "540", "total_calories": "2410", "body_battery_most_recent": "62",
    "sleep_score": "81", "sleep_duration": "432", "hrv_status": "Balanced",
    "hrv_last_night_avg": "54", "resting_heart_rate": "52", "training_readiness": "70",
    "training_status": "Productive", "recovery_time": "12", "vo2_max": "51",
    "last_synced": "2026-01-15T07:30:00+00:00", "last_activity": "Morning Ride",
    "last_activities": "3", "last_activity_route": "4",
}
# Attributes whose values are kept as synthetic placeholders (names only matter).
KEEP_ATTRIBUTES = {"unit_of_measurement", "device_class", "state_class", "restored", "sport",
                   "calendar_date", "calendarDate", "is_stale", "gear_uuid", "gear_status_name"}


def main(src, dst):
    dump = json.load(open(src))
    real_entry = dump["config_entries"][0]["entry_id"]
    registry = dump["entity_registry"]
    registry = list(registry.values()) if isinstance(registry, dict) else registry
    states = {s["entity_id"]: s for s in dump["states"]}

    entities, fake_states = [], []
    gear_index = 0
    for index, entry in enumerate(sorted(registry, key=lambda e: e["unique_id"])):
        unique_id = entry["unique_id"]
        if unique_id.startswith(real_entry + "_"):
            suffix = unique_id[len(real_entry) + 1:]
        else:
            suffix = None  # legacy "{email}_{key}" scheme
        tk = entry.get("translation_key")
        if suffix and suffix.startswith("gear_"):
            gear_index += 1
            suffix = f"gear_{uuid.UUID(int=gear_index).hex}"
            entity_id = f"sensor.gear_{gear_index}"
        elif tk:
            sport = suffix.split("_", 1)[1] if suffix and suffix.startswith(("ftp_", "ptw_")) else None
            entity_id = f"{entry['entity_id'].split('.')[0]}.garmin_{tk}" + (f"_{sport}" if sport else "")
        else:
            entity_id = f"sensor.legacy_{index}"
        fake_uid = f"{FAKE_ENTRY_ID}_{suffix}" if suffix else f"{FAKE_EMAIL}_legacy{index}"
        entities.append({
            "entity_id": entity_id,
            "unique_id": fake_uid,
            "translation_key": tk,
            "disabled_by": entry.get("disabled_by"),
            "original_name": f"Gear {gear_index}" if suffix and suffix.startswith("gear_") else entry.get("original_name"),
        })

        state = states.get(entry["entity_id"])
        if state is None:
            continue
        attrs = {k: v for k, v in state["attributes"].items() if k in KEEP_ATTRIBUTES}
        if "calendar_date" in attrs:
            attrs["calendar_date"] = "2026-01-15"
        if "calendarDate" in attrs:
            attrs["calendarDate"] = "2026-01-15"
        if "is_stale" in attrs:
            attrs["is_stale"] = False
        if "gear_uuid" in attrs:
            attrs["gear_uuid"] = uuid.UUID(int=gear_index).hex
        if tk == "last_activity_route":
            attrs = {"polyline": [{"lat": 0.0, "lon": 0.0}, {"lat": 0.01, "lon": 0.0},
                                  {"lat": 0.01, "lon": 0.01}, {"lat": 0.0, "lon": 0.01}],
                     "has_polyline": True, "activity_name": "Morning Ride"}
        # Catalog metrics always get a value so the fixture models a healthy account.
        if tk in SYNTHETIC:
            value = SYNTHETIC[tk]
        elif state["state"] in ("unknown", "unavailable"):
            value = state["state"]
        elif tk == "functional_threshold_power":
            value = "250"
        elif suffix and suffix.startswith("gear_"):
            value = "12000"
        else:
            value = "1"
        fake_states.append({"entity_id": entity_id, "state": value, "attributes": attrs})

    fixture = {
        "source_version": dump["manifest"]["version"],
        "source_entry_id": FAKE_ENTRY_ID,
        "entities": entities,
        "states": fake_states,
    }
    with open(dst, "w") as f:
        json.dump(fixture, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {dst}: {len(entities)} entities, {len(fake_states)} states")


main(*sys.argv[1:3])
