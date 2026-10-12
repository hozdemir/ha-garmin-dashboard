"""Generate fully synthetic preview data for screenshots and demos.

Usage: python dev/tools/synthetic_preview.py dev/preview/synthetic.json

No real person's data: values come from a seeded generator, activity names are
generic and the route is a made-up loop. Safe to commit and to publish.
"""

from datetime import UTC, datetime, timedelta
import json
import math
import random
import sys

random.seed(20261012)
NOW = datetime(2026, 10, 12, 18, 30, tzinfo=UTC)
DAY_MS = 86_400_000


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def metric(key, section, kind, value, unit=None, freshness="fresh", source_date=None):
    return {
        "key": key,
        "section": section,
        "kind": kind,
        "value": value,
        "unit": unit,
        "status": "available" if value is not None else "missing",
        "freshness": freshness,
        "observed_at": NOW.isoformat(),
        "ha_updated_at": NOW.isoformat(),
        "measured_at": None,
        "source_date": source_date,
    }


def daily(days, base, spread, lo=None, hi=None, decimals=0):
    out, value = [], base
    for i in range(days, 0, -1):
        value += random.uniform(-spread, spread) + (base - value) * 0.15
        v = round(value, decimals) if decimals else round(value)
        if lo is not None:
            v = max(lo, v)
        if hi is not None:
            v = min(hi, v)
        midnight = (NOW - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        out.append([ms(midnight), v])
    return out


def chart(chart_id, group, form, method, series, per_day=False, days=30, goal=None):
    start = NOW - (timedelta(hours=24) if group == "today" else timedelta(days=days))
    payload = {
        "chart_id": chart_id,
        "group": group,
        "form": form,
        "method": method,
        "per_day": per_day,
        "range_days": 1 if group == "today" else days,
        "start": start.isoformat(),
        "end": NOW.isoformat(),
        "series": series,
    }
    if goal is not None:
        payload["goal"] = goal
    return payload


def body_battery_today():
    points, value = [], 35.0
    for i in range(96):
        t = NOW - timedelta(minutes=15 * (96 - i))
        hour = t.hour + 3  # pretend local time UTC+3
        value += 1.6 if 0 <= hour % 24 < 7 else -random.uniform(0.2, 1.1)
        value = max(5, min(100, value))
        points.append([ms(t), round(value)])
    return points


def steps_today(final=7432):
    points, total = [], 0
    start = NOW.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=3)
    t = start
    while t < NOW:
        total += random.choice([0, 0, 150, 400, 900, 2200]) if 4 < (t.hour + 3) % 24 < 23 else 0
        points.append([ms(t), total])
        t += timedelta(minutes=30)
    # Scale so the line ends at the tile's value.
    return [[t, round(v * final / total)] for t, v in points] if total else points


def route():
    pts = []
    for i in range(400):
        a = 2 * math.pi * i / 400
        r = 0.03 + 0.008 * math.sin(5 * a) + 0.004 * math.cos(11 * a)
        pts.append([round(r * math.sin(a), 6), round(1.6 * r * math.cos(a), 6)])
    lats, lons = [p[0] for p in pts], [p[1] for p in pts]
    return {
        "title": "Sunday Loop",
        "points": pts,
        "bounds": [min(lats), min(lons), max(lats), max(lons)],
        "source_points": len(pts),
        "invalid_points": 0,
        "simplified": False,
    }


def activities():
    names = [
        ("Sunday Loop", "road_biking", 72000, 9300, 148),
        ("Recovery Spin", "road_biking", 25000, 3600, 121),
        ("Morning Run", "running", 8200, 2700, 152),
        ("Hill Repeats", "road_biking", 41000, 6100, 158),
        ("Evening Walk", "walking", 4300, 3300, 98),
        ("Tempo Run", "running", 10000, 2950, 164),
        ("Commute", "cycling", 12000, 2400, 128),
    ]
    out = []
    for i, (title, sport, dist, dur, hr) in enumerate(names):
        start = NOW - timedelta(days=i * 1.7 + 0.3)
        zones = [dur * f for f in (0.08, 0.27, 0.38, 0.22, 0.05)]
        out.append(
            {
                "id": str(1000 + i),
                "id_source": "source",
                "sport": sport,
                "title": title,
                "started_at": start.isoformat(),
                "duration_seconds": dur,
                "moving_seconds": dur * 0.97,
                "distance_meters": dist,
                "average_speed_mps": dist / dur,
                "max_speed_mps": dist / dur * 1.8,
                "average_heart_rate_bpm": hr,
                "max_heart_rate_bpm": hr + 24,
                "average_power_w": 182 if "biking" in sport else None,
                "normalized_power_w": 201 if "biking" in sport else None,
                "elevation_gain_m": round(dist / 90),
                "calories_kcal": round(dur / 4.5),
                "aerobic_effect": 3.1,
                "anaerobic_effect": 1.2,
                "training_load": 96 + i * 7,
                "hr_zone_seconds": zones,
            }
        )
    return out


def main(out):
    m = {
        "steps": metric("steps", "movement", "count", 7432, "steps"),
        "steps_goal": metric("steps_goal", "movement", "count", 9000, "steps"),
        "floors_up": metric("floors_up", "movement", "floors", 6.4, "floors"),
        "floors_down": metric("floors_down", "movement", "floors", 5.1, "floors"),
        "floors_goal": metric("floors_goal", "movement", "floors", 10, "floors"),
        "distance_day": metric("distance_day", "movement", "distance", 5830, "m"),
        "calories_active": metric("calories_active", "movement", "energy", 612, "kcal"),
        "calories_total": metric("calories_total", "movement", "energy", 2540, "kcal"),
        "body_battery": metric("body_battery", "recovery", "percent", 58, "%"),
        "sleep_score": metric("sleep_score", "recovery", "score", 82, None, source_date="2026-10-12"),
        "sleep_duration": metric("sleep_duration", "recovery", "duration", 7.4 * 3600, "s"),
        "hrv_status": metric("hrv_status", "recovery", "category", "BALANCED", source_date="2026-10-12"),
        "hrv_last_night": metric("hrv_last_night", "recovery", "hrv", 54, "ms"),
        "resting_hr": metric("resting_hr", "recovery", "heart_rate", 51, "bpm"),
        "training_readiness": metric("training_readiness", "training", "percent", 74, "%"),
        "training_status": metric("training_status", "training", "category", "Productive"),
        "recovery_time": metric("recovery_time", "training", "duration", 14 * 3600, "s"),
        "vo2max": metric("vo2max", "training", "vo2max", 51, "mL/(kg·min)"),
        "ftp_cycling": metric("ftp_cycling", "training", "power", 254, "W", source_date="2026-10-02"),
        "ftp_running": metric("ftp_running", "training", "power", 318, "W", source_date="2026-09-20"),
        "weekly_step_avg": metric("weekly_step_avg", "movement", "count", 8650, "steps"),
        "sleep_deep": metric("sleep_deep", "recovery", "duration", 1.3 * 3600, "s"),
        "sleep_light": metric("sleep_light", "recovery", "duration", 4.1 * 3600, "s"),
        "sleep_rem": metric("sleep_rem", "recovery", "duration", 1.6 * 3600, "s"),
        "sleep_awake": metric("sleep_awake", "recovery", "duration", 0.4 * 3600, "s"),
        "stress_avg": metric("stress_avg", "recovery", "level", 28, "level"),
        "bb_charged": metric("bb_charged", "recovery", "percent", 62, "%"),
        "bb_drained": metric("bb_drained", "recovery", "percent", 41, "%"),
        "bb_highest": metric("bb_highest", "recovery", "percent", 82, "%"),
        "bb_lowest": metric("bb_lowest", "recovery", "percent", 24, "%"),
        "stress_rest": metric("stress_rest", "recovery", "duration", 312 * 60, "s"),
        "stress_low": metric("stress_low", "recovery", "duration", 198 * 60, "s"),
        "stress_medium": metric("stress_medium", "recovery", "duration", 74 * 60, "s"),
        "stress_high": metric("stress_high", "recovery", "duration", 21 * 60, "s"),
        "spo2_avg": metric("spo2_avg", "recovery", "percent", 95, "%"),
        "spo2_latest": metric("spo2_latest", "recovery", "percent", 96, "%"),
        "sleep_need": metric("sleep_need", "recovery", "duration", 8 * 3600, "s"),
        "hrv_balanced_low": metric("hrv_balanced_low", "recovery", "hrv", 48, "ms"),
        "hrv_balanced_high": metric("hrv_balanced_high", "recovery", "hrv", 62, "ms"),
        "weight": metric("weight", "body", "mass", 74.3, "kg"),
        "ptw_cycling": metric("ptw_cycling", "training", "power_ratio", 3.42, "W/kg", source_date="2026-10-02"),
        "lthr_cycling": metric("lthr_cycling", "training", "heart_rate", 165, "bpm", source_date="2026-09-28"),
        "lthr_running": metric("lthr_running", "training", "heart_rate", 172, "bpm", source_date="2026-09-28"),
    }
    t_last = ms(NOW - timedelta(hours=9))

    def s(key, kind, unit, points=None, ranges=None):
        entry = {"metric": key, "kind": kind, "unit": unit}
        if points is not None:
            entry["points"] = points
        if ranges is not None:
            entry["ranges"] = ranges
        return entry

    bb_ranges = [
        [t, lo, max(lo + 20, hi)]
        for (t, lo), (_, hi) in zip(daily(30, 18, 6, 5, 60), daily(30, 88, 6, 40, 100), strict=True)
    ]
    ftp = [[ms(NOW - timedelta(days=30)), 246], [ms(NOW - timedelta(days=10)), 254]]
    vo2 = [[ms(NOW - timedelta(days=30)), 50], [ms(NOW - timedelta(days=18)), 51]]
    charts = {
        "body_battery_today": chart(
            "body_battery_today", "today", "area", "intraday", [s("body_battery", "percent", "%", body_battery_today())]
        ),
        "steps_today": chart(
            "steps_today", "today", "line", "cumulative_today", [s("steps", "count", "steps", steps_today())], goal=9000
        ),
        "sleep_stages": chart(
            "sleep_stages",
            "today",
            "stacked_bar",
            "current",
            [
                s(k, "duration", "s", [[t_last, m[k]["value"]]])
                for k in ("sleep_deep", "sleep_light", "sleep_rem", "sleep_awake")
            ],
        ),
        "stress_breakdown": chart(
            "stress_breakdown",
            "today",
            "stacked_bar",
            "current",
            [
                s(k, "duration", "s", [[ms(NOW), m[k]["value"]]])
                for k in ("stress_rest", "stress_low", "stress_medium", "stress_high")
            ],
        ),
        "stress_today": chart("stress_today", "today", "line", "intraday", []),
        "body_battery_range": chart(
            "body_battery_range",
            "trends",
            "range_columns",
            "daily_range",
            [s("body_battery", "percent", "%", ranges=bb_ranges)],
        ),
        "sleep_score": chart(
            "sleep_score",
            "trends",
            "dots",
            "change_points",
            [s("sleep_score", "score", None, daily(30, 78, 9, 40, 98))],
            per_day=True,
        ),
        "sleep_duration": chart(
            "sleep_duration",
            "trends",
            "columns",
            "change_points",
            [s("sleep_duration", "duration", "s", [[t, v * 60] for t, v in daily(30, 440, 45, 300, 560)])],
            per_day=True,
        ),
        "resting_hr": chart(
            "resting_hr",
            "trends",
            "line",
            "change_points",
            [s("resting_hr", "heart_rate", "bpm", daily(30, 52, 1.5))],
            per_day=True,
        ),
        "hrv": {
            **chart(
                "hrv",
                "trends",
                "line",
                "change_points",
                [s("hrv_last_night", "hrv", "ms", daily(30, 55, 5))],
                per_day=True,
            ),
            "band": {"low": 48, "high": 62, "current_only": True},
        },
        "weekly_steps": chart(
            "weekly_steps",
            "trends",
            "line",
            "change_points",
            [s("weekly_step_avg", "count", "steps", daily(30, 8600, 350))],
            per_day=True,
        ),
        "vo2max": chart("vo2max", "trends", "step", "change_points", [s("vo2max", "vo2max", "mL/(kg·min)", vo2)]),
        "ftp_cycling": chart("ftp_cycling", "trends", "step", "change_points", [s("ftp_cycling", "power", "W", ftp)]),
        "weight": chart(
            "weight",
            "trends",
            "dots",
            "change_points",
            [s("weight", "mass", "kg", [[t, round(v / 10, 1)] for t, v in daily(30, 743, 4, 735, 752)][::3])],
            per_day=True,
        ),
        "ptw_cycling": chart(
            "ptw_cycling",
            "trends",
            "step",
            "change_points",
            [s("ptw_cycling", "power_ratio", "W/kg", [[t, round(v / 74.3, 2)] for t, v in ftp])],
        ),
    }
    snapshot = {
        "schema_version": 1,
        "profile_id": "preview",
        "display_name": "Garmin",
        "revision": 1,
        "observed_at": NOW.isoformat(),
        "source_status": "ready",
        "source_synced_at": (NOW - timedelta(minutes=12)).isoformat(),
        "source_sync_device": "Edge 840",
        "metrics": m,
        "gear": [
            {"id": "g1", "name": "Road bike", "status": "available", "distance_meters": 8_412_000, "retired": False},
            {"id": "g2", "name": "Running shoes", "status": "available", "distance_meters": 512_000, "retired": False},
        ],
        "plan": {
            "today": {"title": "Sweet spot 3x12", "sport": "cycling", "date": "2026-10-12"},
            "next": {"title": "Endurance ride", "sport": "cycling", "date": "2026-10-14"},
            "upcoming": [{"title": "Tempo run", "sport": "running", "date": "2026-10-16"}],
            "goal": {
                "name": "Autumn Gran Fondo",
                "date": "2026-11-08",
                "days_until": 27,
                "distance_meters": 128000,
                "predicted_seconds": 16200,
            },
        },
        "sensors": [
            {"type": "BIKE_POWER", "manufacturer": "Garmin", "battery_status": "LOW", "battery_level": None},
            {"type": "HEART_RATE", "manufacturer": "Garmin", "battery_status": "GOOD", "battery_level": 86},
            {"type": "BIKE_RADAR", "manufacturer": "Garmin", "battery_status": "GOOD", "battery_level": None},
        ],
        "activities": activities(),
        "activities_truncated": False,
        "capabilities": ["movement", "recovery", "training", "gear", "activities", "route"],
    }
    with open(out, "w") as f:
        json.dump({"snapshot": snapshot, "charts": charts, "route": route(), "unit_length": "km"}, f)
    print(f"wrote {out}")


main(sys.argv[1])
