"""Training calendar normalization."""

from datetime import date

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.garmin_dashboard.plan import goal_event, training_plan, workout

from .conftest import entity_for
from .test_init import PROFILE_ID, _setup

TODAY = date(2026, 10, 12)


def test_workout_fields_and_past_days() -> None:
    raw = {"date": "2026-10-12", "title": "Threshold 3x10", "sportTypeKey": "cycling", "duration": 3600}
    assert workout(raw, TODAY) == {"title": "Threshold 3x10", "sport": "cycling", "date": "2026-10-12"}
    assert workout({**raw, "date": "2026-10-11"}, TODAY) is None
    assert workout({"date": "nope", "title": "x"}, TODAY) is None
    assert workout({"date": "2026-10-13"}, TODAY) is None


def test_goal_event_countdown_and_units() -> None:
    raw = {
        "eventName": "City Half",
        "date": "2026-11-01",
        "targetDistance": 21.0975,
        "targetDistanceUnit": "kilometer",
        "predictedRaceTimeDurationSeconds": 6300,
    }
    goal = goal_event(raw, TODAY)
    assert goal["days_until"] == 20
    assert round(goal["distance_meters"]) == 21098
    assert goal["predicted_seconds"] == 6300
    assert goal_event({**raw, "targetDistanceUnit": "furlong"}, TODAY)["distance_meters"] is None
    assert goal_event({**raw, "date": "2026-10-01"}, TODAY) is None
    assert goal_event({**raw, "predictedRaceTimeDurationSeconds": -5}, TODAY)["predicted_seconds"] is None


def test_plan_combines_and_dedupes() -> None:
    today = {"date": "2026-10-12", "title": "Easy spin", "sportTypeKey": "cycling"}
    nxt = {
        **today,
        "upcoming": [
            {"date": "2026-10-15", "title": "Long ride", "sportTypeKey": "cycling"},
            today,
            {"date": "2026-10-13", "title": "Intervals", "sportTypeKey": "cycling"},
        ],
    }
    plan = training_plan(today, nxt, None, TODAY)
    assert plan["today"]["title"] == "Easy spin"
    assert plan["next"]["title"] == "Intervals"
    assert [w["title"] for w in plan["upcoming"]] == ["Long ride"]
    assert plan["goal"] is None


def test_no_plan_is_none() -> None:
    assert training_plan({}, {"upcoming": []}, {}, TODAY) is None
    assert training_plan(None, None, None, TODAY) is None


async def test_snapshot_plan_and_weight(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    today = dt_util.now().date().isoformat()
    hass.states.async_set(
        entity_for("today_scheduled_workout"),
        "Easy spin",
        {"date": today, "title": "Easy spin", "sportTypeKey": "cycling"},
    )
    hass.states.async_set(entity_for("weight"), "165", {"unit_of_measurement": "lb", "device_class": "weight"})
    snapshot = entry.runtime_data.profiles[PROFILE_ID].snapshot()
    assert snapshot["plan"]["today"]["title"] == "Easy spin"
    weight = snapshot["metrics"]["weight"]
    assert weight["unit"] == "kg"
    assert round(weight["value"], 2) == 74.84
