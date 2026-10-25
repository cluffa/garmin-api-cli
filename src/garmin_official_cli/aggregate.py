"""Local aggregations over official daily/activity data (no derived Garmin metrics)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

from .dates import week_start
from .output import dig, round_or_none
from .projections import M_PER_MI, hr_zone_seconds, pace

def _day(value: Any) -> date | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def weekly_steps(days: Iterable[dict[str, Any]], *, first_weekday: int = 0) -> list[dict[str, Any]]:
    buckets: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for d in days:
        day = _day(d.get("calendarDate"))
        if day is not None:
            buckets[week_start(day, first_weekday)].append(d)
    out = []
    for start in sorted(buckets):
        rows = buckets[start]
        steps = [r["totalSteps"] for r in rows if isinstance(r.get("totalSteps"), int)]
        dist = [r["totalDistance"] for r in rows if isinstance(r.get("totalDistance"), (int, float))]
        out.append(
            {
                "week_start": start.isoformat(),
                "days": len(rows),
                "total_steps": sum(steps),
                "avg_steps": round(sum(steps) / len(steps)) if steps else None,
                "total_distance_m": round(sum(dist)) if dist else None,
            }
        )
    return out


def weekly_stress(days: Iterable[dict[str, Any]], *, first_weekday: int = 0) -> list[dict[str, Any]]:
    buckets: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for d in days:
        day = _day(d.get("calendarDate"))
        if day is not None:
            buckets[week_start(day, first_weekday)].append(d)
    out = []
    for start in sorted(buckets):
        rows = buckets[start]
        levels = [
            v
            for r in rows
            if isinstance(v := dig(r, "values.overallStressLevel"), (int, float)) and v >= 0
        ]
        high = [v for r in rows if isinstance(v := dig(r, "values.highStressDuration"), (int, float))]
        out.append(
            {
                "week_start": start.isoformat(),
                "days": len(rows),
                "days_with_data": len(levels),
                "avg_stress": round(sum(levels) / len(levels), 1) if levels else None,
                "max_daily_avg_stress": max(levels) if levels else None,
                "high_stress_s": sum(high) if high else None,
            }
        )
    return out


def is_running(activity: dict[str, Any]) -> bool:
    return "running" in (dig(activity, "activityType.typeKey") or "")


def activity_day(activity: dict[str, Any]) -> date | None:
    return _day(activity.get("startTimeLocal"))


def running_weekly(activities: Iterable[dict[str, Any]], *, ref: date, first_weekday: int = 0) -> dict[str, Any]:
    """Weekly running volume: this week, previous week, prior-4-complete-weeks average, longest run.

    Each week also carries running time in HR zones 1-5, the share of it in zones 1-2 (the
    easy side of an 80/20 split), and the summed Garmin training load of its runs."""
    this_week = week_start(ref, first_weekday)
    weeks = [this_week - timedelta(weeks=i) for i in range(5)]  # current + 4 complete weeks
    totals: dict[date, dict[str, Any]] = {
        w: {"meters": 0.0, "runs": 0, "seconds": 0.0, "load": 0.0, "zones": [0.0] * 5} for w in weeks
    }
    longest: dict[str, Any] | None = None
    for a in activities:
        if not is_running(a):
            continue
        day = activity_day(a)
        if day is None or day > ref:
            continue
        w = week_start(day, first_weekday)
        if w not in totals:
            continue
        meters = float(a.get("distance") or 0)
        totals[w]["meters"] += meters
        totals[w]["runs"] += 1
        totals[w]["seconds"] += float(a.get("duration") or 0)
        totals[w]["load"] += float(a.get("activityTrainingLoad") or 0)
        for i, z in enumerate(hr_zone_seconds(a) or []):
            totals[w]["zones"][i] += z
        if longest is None or meters > longest["meters"]:
            longest = {"meters": meters, "id": a.get("activityId"), "name": a.get("activityName"), "date": day.isoformat()}

    def fmt(meters: float) -> dict[str, float]:
        return {"km": round(meters / 1000, 2), "mi": round(meters / M_PER_MI, 2)}

    def intensity(w: date) -> dict[str, Any]:
        zones = totals[w]["zones"]
        total = sum(zones)
        return {
            "hr_zones_s": [round(z) for z in zones],
            "z1_z2_pct": round((zones[0] + zones[1]) / total * 100, 1) if total else None,
            "training_load": round(totals[w]["load"], 1),
        }

    prior = [totals[w]["meters"] for w in weeks[1:]]
    return {
        "week_start": this_week.isoformat(),
        "as_of": ref.isoformat(),
        "this_week": {**fmt(totals[this_week]["meters"]), "runs": totals[this_week]["runs"]},
        "previous_week": {**fmt(totals[weeks[1]]["meters"]), "runs": totals[weeks[1]]["runs"]},
        "four_week_avg": fmt(sum(prior) / 4),
        "longest_run": (
            {**fmt(longest["meters"]), "id": longest["id"], "name": longest["name"], "date": longest["date"]}
            if longest
            else None
        ),
        "weeks": [
            {"week_start": w.isoformat(), **fmt(totals[w]["meters"]), "runs": totals[w]["runs"], **intensity(w)}
            for w in reversed(weeks)
        ],
    }


def progress(activities: Iterable[dict[str, Any]], *, miles: bool = False) -> dict[str, Any]:
    by_type: dict[str, dict[str, float]] = defaultdict(
        lambda: {"count": 0, "meters": 0.0, "seconds": 0.0, "calories": 0.0, "elevation_gain_m": 0.0}
    )
    for a in activities:
        t = dig(a, "activityType.typeKey") or "unknown"
        row = by_type[t]
        row["count"] += 1
        row["meters"] += float(a.get("distance") or 0)
        row["seconds"] += float(a.get("duration") or 0)
        row["calories"] += float(a.get("calories") or 0)
        row["elevation_gain_m"] += float(a.get("elevationGain") or 0)
    unit = "mi" if miles else "km"
    div = M_PER_MI if miles else 1000

    def shape(row: dict[str, float]) -> dict[str, Any]:
        speed = row["meters"] / row["seconds"] if row["seconds"] else None
        return {
            "count": int(row["count"]),
            f"distance_{unit}": round(row["meters"] / div, 2),
            "duration_h": round(row["seconds"] / 3600, 2),
            "calories": round(row["calories"]),
            "elevation_gain_m": round_or_none(row["elevation_gain_m"], 1),
            "avg_pace": pace(speed, miles) if row["meters"] else None,
        }

    total = {"count": 0, "meters": 0.0, "seconds": 0.0, "calories": 0.0, "elevation_gain_m": 0.0}
    for row in by_type.values():
        for k in total:
            total[k] += row[k]
    return {
        "by_type": {t: shape(r) for t, r in sorted(by_type.items(), key=lambda kv: -kv[1]["count"])},
        "total": shape(total),
    }
