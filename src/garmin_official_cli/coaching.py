"""Coaching analysis of one decoded FIT activity: the planned workout, how each step was
executed, rep-by-rep interval stats, even km/mile splits and aerobic drift.

Everything is computed locally from the official .FIT download. The only Garmin-derived
values are ones the device itself wrote into the file (training effect, training load,
RPE, feel, time in zone, grade-adjusted speed).
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from .output import round_or_none
from .projections import FEEL, M_PER_MI, distance, pace

FOOT_SPORTS = {"running", "walking", "hiking"}
TIMER_STOPS = {"stop", "stop_all", "stop_disable", "stop_disable_all"}
LONG_SEGMENT_S = 15 * 60  # segments at least this long get their own decoupling figure
HR_SETTLE_S = 5 * 60  # ignored at the start of a run for overall drift
EDGE_S = 5  # seconds averaged for a segment's start/end heart rate
RECOVERY_PEAK_S = 30  # window at the start of a recovery where the previous rep's HR peak shows
MAX_SAMPLE_GAP_S = 10  # a longer gap between records is not weighted as moving time
SPEED_SMOOTHING_S = 10  # GPS speed is averaged over this trailing window before checking a pace target
MIN_MOVING_MPS = 0.5
ELEVATION_HYSTERESIS_M = 1.0
REP_INTENSITIES = {"active", "interval"}
UNITS = {"speed": "m/s", "heart_rate": "bpm", "power": "W", "cadence": "spm"}


# --- small helpers ------------------------------------------------------------


def text(value: Any) -> str | None:
    """FIT strings can come back split on stray NULs (a reused device buffer); keep the real text."""
    if isinstance(value, list):
        value = next((v for v in value if isinstance(v, str) and v.strip()), None)
    if not isinstance(value, str):
        return None
    return value.split("\x00", 1)[0].strip() or None


def number(value: Any) -> float | None:
    """A finite float, or None (FIT uses NaN for fields a device left unset)."""
    return round_or_none(value, 9)


def first(*values: Any) -> Any:
    return next((v for v in values if number(v) is not None), None)


def cadence(value: Any, fraction: Any, foot: bool) -> float | None:
    """FIT running cadence counts one foot (strides/min); steps/min is double that."""
    v = number(value)
    if v is None:
        return None
    v += number(fraction) or 0.0
    return round(v * 2 if foot else v, 1)


def wmean(pairs: Iterable[tuple[Any, Any]]) -> float | None:
    """Weighted mean of (value, weight) pairs, skipping missing values."""
    total = weight = 0.0
    for value, w in pairs:
        v, w = number(value), number(w)
        if v is None or not w:
            continue
        total += v * w
        weight += w
    return total / weight if weight else None


def mm_to(value: Any, div: float, digits: int) -> float | None:
    v = number(value)
    return round(v / div, digits) if v is not None else None


def clock_text(seconds: float) -> str:
    s = round(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def whole(value: Any) -> int | None:
    v = number(value)
    return round(v) if v is not None else None


def drop_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


# --- the timer clock ----------------------------------------------------------


class Clock:
    """Maps wall-clock timestamps to timer seconds, removing time the timer was stopped."""

    def __init__(self, start: datetime, events: Iterable[dict[str, Any]]):
        self.start = start
        self.pauses: list[tuple[datetime, datetime]] = []
        stopped: datetime | None = None
        timer = sorted(
            (e for e in events if e.get("event") == "timer" and isinstance(e.get("timestamp"), datetime)),
            key=lambda e: e["timestamp"],
        )
        for e in timer:
            if e.get("event_type") in TIMER_STOPS and stopped is None:
                stopped = e["timestamp"]
            elif e.get("event_type") == "start" and stopped is not None:
                self.pauses.append((stopped, e["timestamp"]))
                stopped = None

    def timer_s(self, t: datetime) -> float:
        total = (t - self.start).total_seconds()
        for begin, end in self.pauses:
            if t <= begin:
                break
            total -= (min(t, end) - begin).total_seconds()
        return total


# --- records ------------------------------------------------------------------


def series(records: Iterable[dict[str, Any]], clock: Clock, foot: bool) -> list[dict[str, Any]]:
    rows = []
    for r in records:
        ts = r.get("timestamp")
        if not isinstance(ts, datetime):
            continue
        rows.append(
            {
                "t": clock.timer_s(ts),
                "d": number(r.get("distance")),
                "v": number(first(r.get("enhanced_speed"), r.get("speed"))),
                "hr": number(r.get("heart_rate")),
                "cad": cadence(r.get("cadence"), r.get("fractional_cadence"), foot),
                "alt": number(first(r.get("enhanced_altitude"), r.get("altitude"))),
                "pw": number(r.get("power")),
            }
        )
    rows.sort(key=lambda x: x["t"])
    smooth(rows)
    for a, b in zip(rows, rows[1:]):
        a["w"] = min(max(b["t"] - a["t"], 0.0), MAX_SAMPLE_GAP_S)
    if rows:
        rows[-1]["w"] = 1.0
    return rows


def smooth(rows: list[dict[str, Any]]) -> None:
    """Trailing time-window mean of speed, stored as ``vs``."""
    lo, total, count = 0, 0.0, 0
    for i, r in enumerate(rows):
        if r["v"] is not None:
            total += r["v"]
            count += 1
        while rows[lo]["t"] <= r["t"] - SPEED_SMOOTHING_S:
            if rows[lo]["v"] is not None:
                total -= rows[lo]["v"]
                count -= 1
            lo += 1
        r["vs"] = total / count if count else None


def window(rows: list[dict[str, Any]], times: list[float], t0: float, t1: float) -> list[dict[str, Any]]:
    return rows[bisect_left(times, t0) : bisect_left(times, t1)]


def mean_of(rows: Iterable[dict[str, Any]], key: str) -> float | None:
    return wmean((r[key], r["w"]) for r in rows)


def elevation(rows: Iterable[dict[str, Any]]) -> tuple[float | None, float | None]:
    """Gain and loss with a small hysteresis so barometer noise does not add up."""
    gain = loss = 0.0
    ref: float | None = None
    seen = False
    for r in rows:
        alt = r["alt"]
        if alt is None:
            continue
        seen = True
        if ref is None:
            ref = alt
        elif alt - ref >= ELEVATION_HYSTERESIS_M:
            gain += alt - ref
            ref = alt
        elif ref - alt >= ELEVATION_HYSTERESIS_M:
            loss += ref - alt
            ref = alt
    return (round(gain), round(loss)) if seen else (None, None)


def decoupling(rows: list[dict[str, Any]], miles: bool) -> dict[str, Any] | None:
    """Aerobic decoupling (Pa:HR): efficiency (speed / HR) in the first half vs the second half.

    Positive means heart rate rose relative to pace. Under about 5% on a steady run is a solid
    aerobic base. Grade is not corrected, so hilly routes inflate or deflate it."""
    moving = [r for r in rows if (r["v"] or 0) > MIN_MOVING_MPS and r["hr"]]
    total = sum(r["w"] for r in moving)
    if total < 10 * 60:
        return None
    acc, half = 0.0, 0
    for i, r in enumerate(moving):
        acc += r["w"]
        if acc >= total / 2:
            half = i + 1
            break
    halves = []
    for part in (moving[:half], moving[half:]):
        v, hr = mean_of(part, "v"), mean_of(part, "hr")
        if not v or not hr:
            return None
        halves.append({"pace": pace(v, miles), "avg_hr": round(hr), "ef": v / hr})
    pct = (halves[0]["ef"] - halves[1]["ef"]) / halves[0]["ef"] * 100
    return {
        "pct": round(pct, 1),
        "first_half": {k: halves[0][k] for k in ("pace", "avg_hr")},
        "second_half": {k: halves[1][k] for k in ("pace", "avg_hr")},
    }


# --- zones --------------------------------------------------------------------


def zones(time_in_zone: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Session time in HR zones and power buckets, as the device computed them.

    HR buckets follow Garmin Connect's zones: bucket N is (boundary N-1, boundary N], so
    bucket 0 is time below zone 1."""
    session = next((z for z in time_in_zone if z.get("reference_mesg") == "session"), None)
    if not session:
        return None
    out: dict[str, Any] = {}
    bounds = [b for b in session.get("hr_zone_high_boundary") or [] if number(b) is not None]
    times = [number(t) or 0.0 for t in session.get("time_in_hr_zone") or []]
    if len(bounds) > 1 and times:
        total = sum(times) or 1.0
        out["hr"] = {
            "method": session.get("hr_calc_type"),
            "max_hr": session.get("max_heart_rate"),
            "threshold_hr": session.get("threshold_heart_rate") or None,
            "below_zone1_s": round(times[0]),
            "segment_bucket_order": ["below_z1"] + [f"z{i}" for i in range(1, len(bounds))] + ["above_max"],
            "zones": [
                {
                    "zone": i,
                    "low": bounds[i - 1],
                    "high": bounds[i],
                    "time_s": round(times[i]) if i < len(times) else 0,
                    "pct": round(times[i] / total * 100, 1) if i < len(times) else 0.0,
                }
                for i in range(1, len(bounds))
            ],
        }
    pbounds = [b for b in session.get("power_zone_high_boundary") or [] if number(b) is not None]
    ptimes = [number(t) or 0.0 for t in session.get("time_in_power_zone") or []]
    if pbounds and ptimes:
        out["power"] = {
            "ftp": session.get("functional_threshold_power"),
            "buckets": [
                {"low": pbounds[i - 1] if i else 0, "high": b, "time_s": round(ptimes[i]) if i < len(ptimes) else 0}
                for i, b in enumerate(pbounds)
            ],
        }
    return out or None


def lap_zone_times(time_in_zone: list[dict[str, Any]]) -> dict[int, list[float]]:
    return {
        z["reference_index"]: [number(t) or 0.0 for t in z.get("time_in_hr_zone") or []]
        for z in time_in_zone
        if z.get("reference_mesg") == "lap" and z.get("reference_index") is not None
    }


class Context:
    """What target decoding needs from the athlete's settings (all optional)."""

    def __init__(self, zone_info: dict[str, Any] | None = None):
        hr = (zone_info or {}).get("hr") or {}
        self.max_hr = number(hr.get("max_hr"))
        self.hr_zones = {z["zone"]: (z["low"], z["high"]) for z in hr.get("zones", [])}
        self.ftp = number(((zone_info or {}).get("power") or {}).get("ftp"))


# --- the planned workout ------------------------------------------------------


def fit_steps(step_mesgs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize FIT workout_step messages (raw device units) to the API's step units."""
    out = []
    for s in sorted(step_mesgs, key=lambda s: s.get("message_index") or 0):
        dtype = s.get("duration_type")
        dtype = dtype if isinstance(dtype, str) else None
        raw = number(s.get("duration_value"))
        repeat = bool(dtype and dtype.startswith("repeat"))
        if dtype == "time":
            dvalue = first(s.get("duration_time"), raw / 1000 if raw is not None else None)
        elif dtype == "distance":
            dvalue = first(s.get("duration_distance"), raw / 100 if raw is not None else None)
        else:
            dvalue = raw
        ttype = s.get("target_type") if isinstance(s.get("target_type"), str) else None
        low, high = number(s.get("custom_target_value_low")), number(s.get("custom_target_value_high"))
        if ttype in ("speed", "speed_lap"):
            low = low / 1000 if low is not None else None
            high = high / 1000 if high is not None else None
        out.append(
            {
                "index": s.get("message_index"),
                "name": text(s.get("wkt_step_name")),
                "intensity": s.get("intensity") if not repeat else None,
                "duration_type": dtype,
                "duration_value": dvalue if not repeat else None,
                "target_type": ttype if not repeat else None,
                "target_zone": int(number(s.get("target_value")) or 0) if not repeat else 0,
                "target_low": low,
                "target_high": high,
                "notes": text(s.get("notes")),
                "repeat_from": int(first(s.get("duration_step"), raw) or 0) if repeat else None,
                "repeat_count": int(first(s.get("repeat_steps"), s.get("target_value")) or 0) if repeat else None,
            }
        )
    return out


def api_steps(steps: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize /activity-service/activity/{id}/workouts steps (WorkoutStepDTO)."""
    out = []
    for s in sorted(steps, key=lambda s: s.get("stepIndex") or 0):
        dtype = (s.get("durationType") or "").lower() or None
        repeat = bool(dtype and dtype.startswith("repeat"))
        ttype = (s.get("targetType") or "").lower() or None
        out.append(
            {
                "index": s.get("stepIndex"),
                "name": text(s.get("name")),
                "intensity": (s.get("intensity") or "").lower() or None,
                "duration_type": dtype,
                "duration_value": number(s.get("durationValue")) if not repeat else None,
                "target_type": ttype if not repeat else None,
                "target_zone": int(number(s.get("targetValue")) or 0) if not repeat else 0,
                "target_low": number(s.get("targetValueLow")),
                "target_high": number(s.get("targetValueHigh")),
                "notes": text(s.get("notes")),
                "repeat_from": int(number(s.get("durationValue")) or 0) if repeat else None,
                "repeat_count": int(number(s.get("targetValue")) or 0) if repeat else None,
            }
        )
    return out


def _hr(value: float | None, ctx: Context) -> float | None:
    """Garmin encodes HR targets as bpm + 100, or as % of max HR when 100 or less."""
    if value is None or value <= 0:
        return None
    if value > 100:
        return value - 100
    return round(ctx.max_hr * value / 100) if ctx.max_hr else None


def _power(value: float | None, ctx: Context) -> float | None:
    """Garmin encodes power targets as watts + 1000, or as % of FTP when 1000 or less."""
    if value is None or value <= 0:
        return None
    if value > 1000:
        return value - 1000
    return round(ctx.ftp * value / 100) if ctx.ftp else None


def target(step: dict[str, Any], ctx: Context, miles: bool) -> dict[str, Any] | None:
    ttype = step.get("target_type")
    if not ttype or ttype == "open":
        return None
    kind = ttype.removesuffix("_lap")
    kind = "power" if kind.startswith("power") else kind
    out: dict[str, Any] = {"type": kind}
    zone = step.get("target_zone") or 0
    raw_low, raw_high = step.get("target_low"), step.get("target_high")
    if zone and not (raw_low or raw_high):
        out["zone"] = zone
        if kind != "heart_rate" or zone not in ctx.hr_zones:
            return out
        low, high = ctx.hr_zones[zone]
    elif kind == "heart_rate":
        low, high = _hr(raw_low, ctx), _hr(raw_high, ctx)
        if raw_high is not None and raw_high <= 100:
            out["pct_max_hr"] = [raw_low, raw_high]
    elif kind == "power":
        low, high = _power(raw_low, ctx), _power(raw_high, ctx)
        if raw_high is not None and raw_high <= 1000:
            out["pct_ftp"] = [raw_low, raw_high]
    else:
        low, high = raw_low, raw_high
    if low is None or high is None or kind not in UNITS:
        return {**out, "raw_low": raw_low, "raw_high": raw_high}
    low, high = sorted((low, high))
    out.update(low=round(low, 3), high=round(high, 3), unit=UNITS[kind])
    if kind == "speed":
        fast, slow = pace(high, miles), pace(low, miles)
        if fast and slow:
            out["pace"] = f"{fast.split('/')[0]}-{slow}"
    return out


def target_text(t: dict[str, Any] | None) -> str | None:
    if not t:
        return None
    if "pace" in t:
        return t["pace"]
    if "low" in t:
        return f"{t['low']:g}-{t['high']:g} {t['unit']}"
    if "zone" in t:
        return f"{t['type'].replace('_', ' ')} zone {t['zone']}"
    return t["type"].replace("_", " ")


def duration_view(step: dict[str, Any], miles: bool) -> dict[str, Any]:
    dtype, value = step.get("duration_type"), step.get("duration_value")
    if dtype == "time" and value is not None:
        return {"type": "time", "s": round(value, 1)}
    if dtype == "distance" and value is not None:
        unit = "mi" if miles else "km"
        return {"type": "distance", "m": round(value, 1), unit: distance(value, miles)}
    if dtype == "open":
        return {"type": "open"}  # ends on the lap button
    return {"type": dtype, "value": value}


def duration_text(step: dict[str, Any], miles: bool) -> str:
    d = duration_view(step, miles)
    if d["type"] == "time":
        return clock_text(d["s"])
    if d["type"] == "distance":
        if d["m"] < 1000:
            return f"{d['m']:g} m"
        unit = "mi" if miles else "km"
        return f"{d[unit]:g} {unit}"
    if d["type"] == "open":
        return "lap button"
    return f"{d['type']} {d['value']}"


def step_text(step: dict[str, Any], ctx: Context, miles: bool) -> str:
    parts = [duration_text(step, miles), step.get("intensity") or "step"]
    t = target_text(target(step, ctx, miles))
    if t:
        parts.append(f"@ {t}")
    return " ".join(parts)


def repeat_owners(steps: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Step index -> the innermost repeat step that repeats it."""
    owner: dict[int, dict[str, Any]] = {}
    for s in steps:  # inner repeats come before the outer ones that contain them
        if s["repeat_count"] is None:
            continue
        for i in range(s["repeat_from"], s["index"]):
            owner.setdefault(i, s)
    return owner


def describe(steps: list[dict[str, Any]], ctx: Context, miles: bool) -> str:
    """One line for the whole workout, e.g. '2 mi warmup, 3 x (5:00 active @ 4:55-5:04/km, ...)'."""
    parts: list[tuple[int, str]] = []
    for s in steps:
        if s["repeat_count"] is None:
            parts.append((s["index"], step_text(s, ctx, miles)))
            continue
        inner = [p for p in parts if p[0] >= s["repeat_from"]]
        parts = [p for p in parts if p[0] < s["repeat_from"]]
        parts.append((s["repeat_from"], f"{s['repeat_count']} x ({', '.join(t for _, t in inner)})"))
    return ", ".join(t for _, t in parts)


def plan(steps: list[dict[str, Any]], ctx: Context, miles: bool) -> list[dict[str, Any]]:
    rows = []
    for s in steps:
        if s["repeat_count"] is not None:
            rows.append({"step": s["index"], "repeat": {"steps": [s["repeat_from"], s["index"] - 1], "times": s["repeat_count"]}})
            continue
        rows.append(
            drop_none(
                {
                    "step": s["index"],
                    "intensity": s["intensity"],
                    "name": s["name"],
                    "duration": duration_view(s, miles),
                    "target": target(s, ctx, miles),
                    "notes": s["notes"],
                }
            )
        )
    return rows


def workout_view(name: Any, description: Any, sport: Any, steps: list[dict[str, Any]], ctx: Context, miles: bool) -> dict[str, Any]:
    return {
        "name": text(name),
        "description": text(description),
        "sport": sport.lower() if isinstance(sport, str) else sport,
        "summary": describe(steps, ctx, miles),
        "steps": plan(steps, ctx, miles),
    }


# --- executed segments --------------------------------------------------------


def lap_groups(laps: list[dict[str, Any]], splits: list[dict[str, Any]], owners: dict[int, dict[str, Any]]) -> list[list[int]]:
    """Lap positions grouped into executed workout steps.

    The device writes one interval_* split per step it ran, naming its first lap and lap
    count, so a warmup auto-lapped into two miles is one step. Laps no split covers (some
    firmware skips the warmup's split) merge with the previous lap of the same step, except
    in a one-step repeat, where each lap is its own rep."""
    position = {lap.get("message_index", i): i for i, lap in enumerate(laps)}
    groups: list[list[int]] = []
    covered: set[int] = set()
    for sp in splits:
        if not str(sp.get("split_type") or "").startswith("interval_"):
            continue
        start, count = sp.get("first_lap_index"), sp.get("num_laps")
        if start not in position or not count:
            continue
        idx = [position[start] + k for k in range(int(count)) if position[start] + k < len(laps)]
        if idx and not covered.intersection(idx):
            groups.append(idx)
            covered.update(idx)
    loose: list[list[int]] = []
    for i, lap in enumerate(laps):
        if i in covered:
            continue
        step = lap.get("wkt_step_index")
        prev = loose[-1][-1] if loose else None
        single_step_repeat = step in owners and owners[step]["repeat_from"] == owners[step]["index"] - 1
        if prev == i - 1 and step is not None and laps[prev].get("wkt_step_index") == step and not single_step_repeat:
            loose[-1].append(i)
        else:
            loose.append([i])
    return sorted(groups + loose)


def role(step: dict[str, Any] | None, owner: dict[str, Any] | None, intensity: Any, has_workout: bool) -> str:
    if step is None:
        return "unplanned" if has_workout else str(intensity or "lap")
    kind = step.get("intensity") or intensity
    if owner is not None and kind in REP_INTENSITIES:
        return "rep"
    if kind in REP_INTENSITIES:
        return "work"
    return str(kind or "other")


def completion(step: dict[str, Any] | None, timer: float, dist: float) -> float | None:
    """How much of a time- or distance-based step was done, in percent of the plan."""
    if not step or not step.get("duration_value"):
        return None
    done = {"time": timer, "distance": dist}.get(step.get("duration_type") or "")
    return round(done / step["duration_value"] * 100, 1) if done is not None else None


def in_range(value: float | None, t: dict[str, Any] | None) -> bool | None:
    if value is None or not t or "low" not in t:
        return None
    return t["low"] <= value <= t["high"]


def target_metric(t: dict[str, Any] | None) -> str | None:
    return {"speed": "vs", "heart_rate": "hr", "power": "pw", "cadence": "cad"}.get((t or {}).get("type", ""))


def time_in_target(rows: list[dict[str, Any]], t: dict[str, Any] | None) -> float | None:
    key = target_metric(t)
    if key is None or "low" not in (t or {}):
        return None
    total = hit = 0.0
    for r in rows:
        if r[key] is None:
            continue
        total += r["w"]
        if t["low"] <= r[key] <= t["high"]:
            hit += r["w"]
    return round(hit / total * 100, 1) if total else None


class Analysis:
    def __init__(self, messages: dict[str, list[dict[str, Any]]], *, miles: bool):
        self.m = messages
        self.miles = miles
        self.unit = "mi" if miles else "km"
        self.session = (messages.get("session_mesgs") or [{}])[0]
        self.laps = sorted(messages.get("lap_mesgs") or [], key=lambda l: l.get("message_index") or 0)
        sport = self.session.get("sport") or next((l.get("sport") for l in self.laps if l.get("sport")), None)
        self.sport = sport if isinstance(sport, str) else None
        self.foot = self.sport in FOOT_SPORTS
        start = self.session.get("start_time") or next((l.get("start_time") for l in self.laps), None)
        if not isinstance(start, datetime):
            records = messages.get("record_mesgs") or []
            start = records[0].get("timestamp") if records else None
        self.clock = Clock(start, messages.get("event_mesgs") or []) if isinstance(start, datetime) else None
        self.rows = series(messages.get("record_mesgs") or [], self.clock, self.foot) if self.clock else []
        self.times = [r["t"] for r in self.rows]
        tiz = messages.get("time_in_zone_mesgs") or []
        self.zones = zones(tiz)
        self.lap_zones = lap_zone_times(tiz)
        self.ctx = Context(self.zones)
        workout = (messages.get("workout_mesgs") or [None])[0]
        self.steps = fit_steps(messages.get("workout_step_mesgs") or [])
        self.workout = workout if workout or self.steps else None
        self.by_index = {s["index"]: s for s in self.steps}
        self.owners = repeat_owners(self.steps)
        self.notes: list[str] = []

    # -- pieces --

    def activity(self) -> dict[str, Any]:
        s = self.session
        timer, elapsed = number(s.get("total_timer_time")), number(s.get("total_elapsed_time"))
        speed = first(s.get("enhanced_avg_speed"), s.get("avg_speed"))
        rpe, feel = number(s.get("workout_rpe")), number(s.get("workout_feel"))
        profile = (self.m.get("user_profile_mesgs") or [{}])[0]
        start = s.get("start_time")
        return {
            "sport": self.sport,
            "sub_sport": s.get("sub_sport") if isinstance(s.get("sub_sport"), str) else None,
            "start_utc": start.isoformat() if isinstance(start, datetime) else None,
            "timer_s": round_or_none(timer, 1),
            "elapsed_s": round_or_none(elapsed, 1),
            "paused_s": round(elapsed - timer, 1) if timer is not None and elapsed is not None else None,
            f"distance_{self.unit}": distance(s.get("total_distance"), self.miles),
            "pace": pace(speed, self.miles),
            "gap_pace": pace(s.get("avg_grade_adjusted_speed"), self.miles),
            "avg_hr": s.get("avg_heart_rate"),
            "max_hr": s.get("max_heart_rate"),
            "min_hr": s.get("min_heart_rate"),
            "avg_cadence": cadence(first(s.get("avg_running_cadence"), s.get("avg_cadence")), s.get("avg_fractional_cadence"), self.foot),
            "avg_power": s.get("avg_power"),
            "normalized_power": s.get("normalized_power"),
            "ascent_m": s.get("total_ascent"),
            "descent_m": s.get("total_descent"),
            "calories": s.get("total_calories"),
            "aerobic_te": round_or_none(s.get("total_training_effect"), 1),
            "anaerobic_te": round_or_none(s.get("total_anaerobic_training_effect"), 1),
            "training_load": round_or_none(s.get("training_load_peak"), 1),
            "rpe": round(rpe / 10, 1) if rpe is not None else None,
            "feel": FEEL.get(int(feel), feel) if feel is not None else None,
            "step_length_m": mm_to(s.get("avg_step_length"), 1000, 2),
            "gct_ms": whole(s.get("avg_stance_time")),
            "vertical_oscillation_cm": mm_to(s.get("avg_vertical_oscillation"), 10, 1),
            "vertical_ratio_pct": round_or_none(s.get("avg_vertical_ratio"), 1),
            "device_units": profile.get("dist_setting") if isinstance(profile.get("dist_setting"), str) else None,
        }

    def workout_block(self) -> dict[str, Any] | None:
        if self.workout is None:
            return None
        w = self.workout or {}
        return workout_view(w.get("wkt_name"), w.get("wkt_description"), w.get("sport"), self.steps, self.ctx, self.miles)

    def segments(self) -> list[dict[str, Any]]:
        if not self.laps:
            return []
        splits = self.m.get("split_mesgs") or []
        groups = lap_groups(self.laps, splits, self.owners) if self.workout is not None else [[i] for i in range(len(self.laps))]
        reps: dict[int, int] = {}
        out = []
        for n, group in enumerate(groups, 1):
            laps = [self.laps[i] for i in group]
            step_index = laps[0].get("wkt_step_index")
            step = self.by_index.get(step_index)
            owner = self.owners.get(step_index) if step else None
            rep = None
            if owner is not None:
                if step_index == owner["repeat_from"]:
                    reps[owner["index"]] = reps.get(owner["index"], 0) + 1
                rep = reps.get(owner["index"])
            out.append(self.segment(n, group, laps, step, owner, rep))
        return out

    def segment(self, n, group, laps, step, owner, rep) -> dict[str, Any]:
        weights = [number(l.get("total_timer_time")) or 0.0 for l in laps]
        timer = sum(weights)
        dist = sum(number(l.get("total_distance")) or 0.0 for l in laps)
        elapsed = sum(number(l.get("total_elapsed_time")) or 0.0 for l in laps)
        lap_mean = lambda key: wmean(zip((l.get(key) for l in laps), weights))  # noqa: E731
        lap_max = lambda key: max((v for l in laps if (v := number(l.get(key))) is not None), default=None)  # noqa: E731
        start = laps[0].get("start_time")
        t0 = self.clock.timer_s(start) if self.clock and isinstance(start, datetime) else None
        rows = window(self.rows, self.times, t0, t0 + timer) if t0 is not None else []
        t = target(step, self.ctx, self.miles) if step else None
        speed = dist / timer if timer else None
        avg_hr, avg_pw = lap_mean("avg_heart_rate"), lap_mean("avg_power")
        cad = wmean(
            zip((cadence(first(l.get("avg_running_cadence"), l.get("avg_cadence")), l.get("avg_fractional_cadence"), self.foot) for l in laps), weights)
        )
        metric = {"vs": speed, "hr": avg_hr, "pw": avg_pw, "cad": cad}.get(target_metric(t) or "")
        zone_rows = [self.lap_zones[lap.get("message_index", i)] for i, lap in zip(group, laps) if lap.get("message_index", i) in self.lap_zones]
        hr_zones = [round(sum(col)) for col in zip(*zone_rows)] if zone_rows else None
        seg_role = role(step, owner, laps[0].get("intensity"), self.workout is not None)
        hr_rows = [r for r in rows if r["hr"]]
        head = [r for r in hr_rows if r["t"] < t0 + EDGE_S] if hr_rows else []
        tail = [r for r in hr_rows if r["t"] >= t0 + timer - EDGE_S] if hr_rows else []
        hr_end = mean_of(tail, "hr")
        hr_drop = None
        if seg_role in ("recovery", "rest") and hr_rows and hr_end is not None:
            peak = max((r["hr"] for r in hr_rows if r["t"] < t0 + RECOVERY_PEAK_S), default=None)
            hr_drop = round(peak - hr_end) if peak is not None else None
        steady = seg_role not in ("rep", "recovery", "rest", "warmup")  # a warmup's HR is still rising from rest
        drift = decoupling(rows, self.miles) if timer >= LONG_SEGMENT_S and steady else None
        return drop_none(
            {
                "seg": n,
                "laps": [i + 1 for i in group],
                "role": seg_role,
                "step": step["index"] if step else None,
                "rep": rep,
                "of": owner["repeat_count"] if owner is not None and rep is not None else None,
                "planned": step_text(step, self.ctx, self.miles) if step else None,
                "pct_of_planned": completion(step, timer, dist),
                "start_s": round(t0) if t0 is not None else None,
                "timer_s": round(timer, 1),
                "elapsed_s": round(elapsed, 1) if abs(elapsed - timer) >= 1 else None,
                f"distance_{self.unit}": distance(dist, self.miles),
                "distance_m": round(dist, 1),
                "pace": pace(speed, self.miles),
                "gap_pace": pace(lap_mean("avg_grade_adjusted_speed"), self.miles),
                "avg_hr": round(avg_hr) if avg_hr is not None else None,
                "max_hr": whole(lap_max("max_heart_rate")),
                "hr_start": round(v) if (v := mean_of(head, "hr")) is not None else None,
                "hr_end": round(hr_end) if hr_end is not None else None,
                "hr_drop_bpm": hr_drop,
                "avg_cadence": round(cad, 1) if cad is not None else None,
                "step_length_m": mm_to(lap_mean("avg_step_length"), 1000, 2),
                "gct_ms": whole(lap_mean("avg_stance_time")),
                "vertical_ratio_pct": round_or_none(lap_mean("avg_vertical_ratio"), 1),
                "avg_power": round(avg_pw) if avg_pw is not None else None,
                "normalized_power": whole(lap_mean("normalized_power")),
                "ascent_m": whole(sum(number(l.get("total_ascent")) or 0 for l in laps)),
                "descent_m": whole(sum(number(l.get("total_descent")) or 0 for l in laps)),
                "hr_zones_s": hr_zones,
                "target": t,
                "in_target": in_range(metric, t),
                "time_in_target_pct": time_in_target(rows, t),
                "decoupling": drift,
            }
        )

    def intervals(self, segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        reps = [s for s in segments if s["role"] == "rep"]
        for step_index in sorted({s["step"] for s in reps}):
            owner = self.owners[step_index]
            mine = [s for s in reps if s["step"] == step_index]
            recoveries = {
                s["rep"]: s
                for s in segments
                if s.get("step") in self.owners
                and self.owners[s["step"]]["index"] == owner["index"]
                and s["role"] in ("recovery", "rest")
            }
            speeds = [s["distance_m"] / s["timer_s"] for s in mine if s["timer_s"]]
            mean_speed = sum(speeds) / len(speeds) if speeds else None
            by_time = self.by_index[step_index].get("duration_type") == "time"
            t = mine[0].get("target")
            row = {
                "step": step_index,
                "repeat_step": owner["index"],
                "planned": step_text(self.by_index[step_index], self.ctx, self.miles),
                "planned_reps": owner["repeat_count"],
                "completed_reps": len(mine),
                "target": target_text(t),
                "in_target_reps": sum(1 for s in mine if s.get("in_target")) if t and "low" in t else None,
                "pace_by_rep": [s.get("pace") for s in mine],
                ("distance_m_by_rep" if by_time else "time_s_by_rep"): [s["distance_m"] if by_time else s["timer_s"] for s in mine],
                "avg_hr_by_rep": [s.get("avg_hr") for s in mine],
                "max_hr_by_rep": [s.get("max_hr") for s in mine],
                "time_in_target_pct_by_rep": [s.get("time_in_target_pct") for s in mine] if t and "low" in t else None,
                "avg_pace": pace(mean_speed, self.miles),
                "spread_pct": round((max(speeds) - min(speeds)) / mean_speed * 100, 1) if mean_speed and len(speeds) > 1 else None,
                "fade_pct": round((speeds[-1] - speeds[0]) / speeds[0] * 100, 1) if len(speeds) > 1 and speeds[0] else None,
                "recovery_hr_end_by_rep": [recoveries[s["rep"]].get("hr_end") if s["rep"] in recoveries else None for s in mine],
                "recovery_hr_drop_by_rep": [recoveries[s["rep"]].get("hr_drop_bpm") if s["rep"] in recoveries else None for s in mine],
            }
            out.append(drop_none(row))
        return out

    def even_splits(self, segments: list[dict[str, Any]]) -> dict[str, Any] | None:
        rows = [r for r in self.rows if r["d"] is not None]
        if len(rows) < 2:
            return None
        size = M_PER_MI if self.miles else 1000.0
        ds, ts = [r["d"] for r in rows], [r["t"] for r in rows]

        def time_at(d: float) -> float:
            i = bisect_left(ds, d)
            if i <= 0:
                return ts[0]
            if i >= len(ds):
                return ts[-1]
            d0, d1 = ds[i - 1], ds[i]
            return ts[i - 1] + (ts[i] - ts[i - 1]) * ((d - d0) / (d1 - d0) if d1 > d0 else 0)

        spans = [(s["start_s"], s["start_s"] + s["timer_s"], s["role"]) for s in segments if "start_s" in s]
        out, d0, n = [], ds[0], 0
        while d0 < ds[-1] - 1:
            n += 1
            d1 = min((n) * size, ds[-1])
            t0, t1 = time_at(d0), time_at(d1)
            part = window(self.rows, self.times, t0, t1)
            moving = [r for r in part if (r["v"] or 0) > MIN_MOVING_MPS]
            gain, loss = elevation(part)
            roles = []
            for a, b, r in spans:
                if min(b, t1) - max(a, t0) >= 5 and r not in roles:
                    roles.append(r)
            hr = mean_of(part, "hr")
            cad = mean_of(moving, "cad")
            pw = mean_of(part, "pw")
            row = {
                "split": n,
                f"distance_{self.unit}": distance(d1 - d0, self.miles),
                "time_s": round(t1 - t0, 1),
                "pace": pace((d1 - d0) / (t1 - t0) if t1 > t0 else None, self.miles),
                "avg_hr": round(hr) if hr is not None else None,
                "max_hr": whole(max((r["hr"] for r in part if r["hr"]), default=None)),
                "avg_cadence": round(cad, 1) if cad is not None else None,
                "avg_power": round(pw) if pw is not None else None,
                "ascent_m": gain,
                "descent_m": loss,
            }
            if self.workout is not None:
                row["roles"] = roles
            out.append(row)
            d0 = d1
        return {"unit": self.unit, "rows": out}

    def drift(self, segments: list[dict[str, Any]]) -> dict[str, Any] | None:
        if any(s["role"] == "rep" for s in segments):
            self.notes.append("overall drift is skipped for interval sessions; long steady segments carry their own decoupling")
            return None
        rows = [r for r in self.rows if r["t"] >= HR_SETTLE_S]
        return decoupling(rows, self.miles)

    def pauses(self) -> list[dict[str, Any]]:
        if not self.clock:
            return []
        return [
            {"at_s": round(self.clock.timer_s(begin)), "duration_s": round((end - begin).total_seconds())}
            for begin, end in self.clock.pauses
        ]

    def run(self) -> dict[str, Any]:
        segments = self.segments()
        if self.workout is None:
            self.notes.append("no structured workout in this file: segments are the recorded laps")
        if not self.rows:
            self.notes.append("no per-second records: even splits, start/end HR, time in target and drift are unavailable")
        return {
            "activity": self.activity(),
            "cadence_unit": "spm" if self.foot else "rpm",
            "zones": self.zones,
            "workout": self.workout_block(),
            "segments": segments,
            "intervals": self.intervals(segments),
            "splits": self.even_splits(segments),
            "drift": self.drift(segments),
            "pauses": self.pauses(),
            "notes": self.notes,
        }


def analyze(messages: dict[str, list[dict[str, Any]]], *, miles: bool = False) -> dict[str, Any]:
    return Analysis(messages, miles=miles).run()
