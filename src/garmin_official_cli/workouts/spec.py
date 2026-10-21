"""Workout spec: parsing, validation and translation toward the Training API workout format.

Pure local logic: no network. The translated payload targets the official Training
API workout JSON (``workoutName`` / ``sport`` / ``steps`` with ``WorkoutStep`` and
``WorkoutRepeatStep`` entries). Field names and enum values follow Garmin's
Training API documentation as far as it could be verified; see docs/API_NOTES.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..projections import M_PER_MI

PROVIDER = "garmin-official-cli"

SPORTS = {
    "running": "RUNNING",
    "cycling": "CYCLING",
    "swimming": "LAP_SWIMMING",
    "strength": "STRENGTH_TRAINING",
    "cardio": "CARDIO_TRAINING",
    "generic": "GENERIC",
}
INTENSITY = {
    "warmup": "WARMUP",
    "interval": "INTERVAL",
    "active": "ACTIVE",
    "recovery": "RECOVERY",
    "rest": "REST",
    "cooldown": "COOLDOWN",
}
TARGETS = ("pace", "speed", "power", "hr")
MAX_REPEAT = 99
MAX_STEPS = 100  # executable steps per workout (Garmin device limit is around 100)

_TIME_TOKEN = re.compile(r"(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|min|mins|minute|minutes|s|sec|secs|second|seconds)")
_TIME_UNITS = {"h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600, "min": 60, "mins": 60,
               "minute": 60, "minutes": 60, "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1}
_DIST = re.compile(r"^(\d+(?:\.\d+)?)\s*(m|km|k|mi|mile|miles|yd)$")
_DIST_UNITS = {"m": 1.0, "km": 1000.0, "k": 1000.0, "mi": M_PER_MI, "mile": M_PER_MI, "miles": M_PER_MI, "yd": 0.9144}
_PACE = re.compile(r"^(\d{1,2}):([0-5]\d)\s*/\s*(km|mi)$")
_SPEED = re.compile(r"^(\d+(?:\.\d+)?)\s*(km/h|kph|mph|m/s)?$")


class SpecError(ValueError):
    pass


# --- value parsers --------------------------------------------------------------


def parse_time(value: Any) -> float:
    """``"10min"``, ``"45s"``, ``"1h30min"``, ``"mm:ss"``, ``"h:mm:ss"`` or a number of seconds."""
    if isinstance(value, bool):
        raise SpecError("time must be a string like '10min' or a number of seconds")
    if isinstance(value, (int, float)):
        secs = float(value)
    elif isinstance(value, str):
        s = value.strip().lower()
        if re.fullmatch(r"\d+(:\d{2}){1,2}", s):
            parts = [int(p) for p in s.split(":")]
            secs = 0.0
            for p in parts:
                secs = secs * 60 + p
        else:
            pos, secs = 0, 0.0
            for m in _TIME_TOKEN.finditer(s):
                if s[pos : m.start()].strip():
                    raise SpecError(f"cannot parse time {value!r}")
                secs += float(m.group(1)) * _TIME_UNITS[m.group(2)]
                pos = m.end()
            if pos == 0 or s[pos:].strip():
                raise SpecError(f"cannot parse time {value!r} (use e.g. '10min', '45s', '1h30min')")
    else:
        raise SpecError("time must be a string or number")
    if secs <= 0 or secs > 24 * 3600:
        raise SpecError(f"time {value!r} out of range (0, 24h]")
    return secs


def parse_distance(value: Any) -> float:
    """``"400m"``, ``"1km"``, ``"1mi"`` -> meters."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise SpecError("distance must be a string like '1km' or a number of meters")
    if isinstance(value, (int, float)):
        meters = float(value)
    else:
        m = _DIST.match(value.strip().lower())
        if not m:
            raise SpecError(f"cannot parse distance {value!r} (use e.g. '400m', '1km', '1mi')")
        meters = float(m.group(1)) * _DIST_UNITS[m.group(2)]
    if meters <= 0 or meters > 1_000_000:
        raise SpecError(f"distance {value!r} out of range")
    return round(meters, 3)


def parse_pace(value: Any) -> float:
    """``"4:00/km"`` / ``"6:30/mi"`` -> speed in m/s."""
    if not isinstance(value, str):
        raise SpecError("pace must be a string like '4:30/km'")
    m = _PACE.match(value.strip().lower())
    if not m:
        raise SpecError(f"cannot parse pace {value!r} (use 'm:ss/km' or 'm:ss/mi')")
    secs = int(m.group(1)) * 60 + int(m.group(2))
    if secs <= 0:
        raise SpecError(f"pace {value!r} must be positive")
    return round((1000.0 if m.group(3) == "km" else M_PER_MI) / secs, 4)


def parse_speed(value: Any) -> float:
    """``"30km/h"``, ``"18mph"``, ``"5m/s"`` or a bare number (km/h) -> m/s."""
    if isinstance(value, bool):
        raise SpecError("speed must be a string or number")
    if isinstance(value, (int, float)):
        num, unit = float(value), "km/h"
    elif isinstance(value, str):
        m = _SPEED.match(value.strip().lower())
        if not m:
            raise SpecError(f"cannot parse speed {value!r} (use e.g. '30km/h', '18mph')")
        num, unit = float(m.group(1)), m.group(2) or "km/h"
    else:
        raise SpecError("speed must be a string or number")
    mps = {"km/h": num / 3.6, "kph": num / 3.6, "mph": num * M_PER_MI / 3600, "m/s": num}[unit]
    if mps <= 0 or mps > 40:
        raise SpecError(f"speed {value!r} out of range")
    return round(mps, 4)


def _int_in(value: Any, lo: int, hi: int, what: str) -> int:
    if isinstance(value, str):
        value = value.strip().lower().removesuffix("w").removesuffix("bpm").strip()
        try:
            value = int(value)
        except ValueError:
            raise SpecError(f"{what} must be an integer") from None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        raise SpecError(f"{what} must be an integer")
    if not lo <= value <= hi:
        raise SpecError(f"{what} {value} out of range [{lo}, {hi}]")
    return int(value)


def _pair(raw: Any, parse) -> tuple[float, float]:
    values = raw if isinstance(raw, list) else [raw]
    if len(values) not in (1, 2):
        raise SpecError("target range must be a value or a [low, high] pair")
    parsed = [parse(v) for v in values]
    return (min(parsed), max(parsed))


def parse_target(target: Any) -> dict[str, Any]:
    if not isinstance(target, dict) or len(target) != 1:
        raise SpecError(f"target must be an object with exactly one of {', '.join(TARGETS)}")
    kind, raw = next(iter(target.items()))
    if kind == "pace":
        low, high = _pair(raw, parse_pace)
        return {"targetType": "PACE", "targetValueLow": low, "targetValueHigh": high}
    if kind == "speed":
        low, high = _pair(raw, parse_speed)
        return {"targetType": "SPEED", "targetValueLow": low, "targetValueHigh": high}
    if kind == "power":
        low, high = _pair(raw, lambda v: _int_in(v, 1, 2500, "power"))
        return {"targetType": "POWER", "targetValueLow": low, "targetValueHigh": high}
    if kind == "hr":
        low, high = _pair(raw, lambda v: _int_in(v, 30, 250, "heart rate"))
        return {"targetType": "HEART_RATE", "targetValueLow": low, "targetValueHigh": high}
    raise SpecError(f"unknown target {kind!r}; use one of {', '.join(TARGETS)}")


# --- validation + translation ------------------------------------------------------


@dataclass
class Issue:
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "message": self.message}


@dataclass
class _Ctx:
    issues: list[Issue] = field(default_factory=list)
    order: int = 0
    executable: int = 0

    def err(self, path: str, message: str) -> None:
        self.issues.append(Issue(path, message))

    def next_order(self) -> int:
        self.order += 1
        return self.order


def _translate_steps(steps: Any, path: str, ctx: _Ctx, sport: str, depth: int) -> list[dict[str, Any]]:
    if not isinstance(steps, list) or not steps:
        ctx.err(path, "steps must be a non-empty list")
        return []
    out: list[dict[str, Any]] = []
    for i, step in enumerate(steps):
        p = f"{path}[{i}]"
        if not isinstance(step, dict):
            ctx.err(p, "step must be an object")
            continue
        if "repeat" in step:
            extra = set(step) - {"repeat", "steps"}
            if extra:
                ctx.err(p, f"unknown keys in repeat group: {', '.join(sorted(extra))}")
            if depth >= 2:
                ctx.err(p, "repeat groups may nest at most two levels")
            try:
                n = _int_in(step.get("repeat"), 1, MAX_REPEAT, "repeat")
            except SpecError as exc:
                ctx.err(f"{p}.repeat", str(exc))
                n = 1
            order = ctx.next_order()
            children = _translate_steps(step.get("steps"), f"{p}.steps", ctx, sport, depth + 1)
            out.append(
                {
                    "type": "WorkoutRepeatStep",
                    "stepOrder": order,
                    "repeatType": "REPEAT_UNTIL_STEPS_CMPLT",
                    "repeatValue": n,
                    "steps": children,
                }
            )
            continue
        extra = set(step) - {"type", "duration", "target", "note"}
        if extra:
            ctx.err(p, f"unknown keys in step: {', '.join(sorted(extra))}")
        stype = step.get("type")
        if stype not in INTENSITY:
            ctx.err(f"{p}.type", f"type must be one of {', '.join(INTENSITY)}")
        ctx.executable += 1
        wire: dict[str, Any] = {
            "type": "WorkoutStep",
            "stepOrder": ctx.next_order(),
            "intensity": INTENSITY.get(stype, "ACTIVE"),
            "description": None,
            "durationType": "OPEN",
            "durationValue": None,
            "durationValueType": None,
            "targetType": "OPEN",
            "targetValue": None,
            "targetValueLow": None,
            "targetValueHigh": None,
            "targetValueType": None,
        }
        note = step.get("note")
        if note is not None:
            if not isinstance(note, str):
                ctx.err(f"{p}.note", "note must be a string")
            elif len(note) > 512:
                ctx.err(f"{p}.note", "note must be at most 512 characters")
            else:
                wire["description"] = note
        duration = step.get("duration")
        if duration is not None:
            if not isinstance(duration, dict) or len(duration) != 1 or next(iter(duration)) not in ("time", "distance"):
                ctx.err(f"{p}.duration", "duration must be {\"time\": ...} or {\"distance\": ...}")
            else:
                kind, raw = next(iter(duration.items()))
                try:
                    if kind == "time":
                        wire.update(durationType="TIME", durationValue=parse_time(raw), durationValueType=None)
                    else:
                        wire.update(durationType="DISTANCE", durationValue=parse_distance(raw), durationValueType="METER")
                except SpecError as exc:
                    ctx.err(f"{p}.duration.{kind}", str(exc))
        target = step.get("target")
        if target is not None:
            try:
                t = parse_target(target)
                if t["targetType"] == "PACE" and sport != "RUNNING":
                    raise SpecError("pace targets are only valid for running workouts")
                wire.update(t)
            except SpecError as exc:
                ctx.err(f"{p}.target", str(exc))
        out.append(wire)
    return out


def translate_workout(w: Any, path: str, ctx: _Ctx) -> dict[str, Any] | None:
    if not isinstance(w, dict):
        ctx.err(path, "workout must be an object")
        return None
    extra = set(w) - {"name", "sport", "date", "notes", "steps"}
    if extra:
        ctx.err(path, f"unknown keys in workout: {', '.join(sorted(extra))}")
    name = w.get("name")
    if not isinstance(name, str) or not name.strip():
        ctx.err(f"{path}.name", "name is required")
    elif len(name) > 80:
        ctx.err(f"{path}.name", "name must be at most 80 characters")
    sport_key = w.get("sport", "running")
    sport = SPORTS.get(sport_key) if isinstance(sport_key, str) else None
    if sport is None:
        ctx.err(f"{path}.sport", f"sport must be one of {', '.join(SPORTS)}")
        sport = "GENERIC"
    when = w.get("date")
    if when is not None:
        try:
            if not isinstance(when, str):
                raise ValueError
            date.fromisoformat(when)
        except ValueError:
            ctx.err(f"{path}.date", "date must be YYYY-MM-DD")
    notes = w.get("notes")
    if notes is not None and not isinstance(notes, str):
        ctx.err(f"{path}.notes", "notes must be a string")
    before = ctx.executable
    steps = _translate_steps(w.get("steps"), f"{path}.steps", ctx, sport, 0)
    if ctx.executable - before > MAX_STEPS:
        ctx.err(f"{path}.steps", f"at most {MAX_STEPS} executable steps per workout")
    return {
        "workoutName": name,
        "description": notes,
        "sport": sport,
        "workoutProvider": PROVIDER,
        "workoutSourceId": PROVIDER,
        "steps": steps,
    }


def normalize_spec(spec: Any) -> list[Any]:
    """Accept ``{"workouts": [...]}``, a bare list, or a single workout object."""
    if isinstance(spec, dict) and "workouts" in spec:
        workouts = spec["workouts"]
        if set(spec) - {"workouts"}:
            raise SpecError("top-level object may only contain 'workouts'")
    elif isinstance(spec, list):
        workouts = spec
    elif isinstance(spec, dict):
        workouts = [spec]
    else:
        raise SpecError("spec must be a JSON object or array")
    if not isinstance(workouts, list) or not workouts:
        raise SpecError("'workouts' must be a non-empty list")
    return workouts


def validate_spec(spec: Any) -> dict[str, Any]:
    """Validate and translate every workout; failures are reported per workout."""
    workouts = normalize_spec(spec)
    results = []
    for i, w in enumerate(workouts):
        ctx = _Ctx()
        wire = translate_workout(w, f"workouts[{i}]", ctx)
        name = w.get("name") if isinstance(w, dict) else None
        result: dict[str, Any] = {"index": i, "name": name, "ok": not ctx.issues}
        if ctx.issues:
            result["errors"] = [x.to_dict() for x in ctx.issues]
        else:
            result["executable_steps"] = ctx.executable
            result["estimated_duration_s"] = estimate_duration(wire["steps"]) if wire else None
            result["training_api_workout"] = wire
            if isinstance(w, dict) and w.get("date"):
                result["training_api_schedule"] = {"workoutId": None, "date": w["date"]}
        results.append(result)
    return {
        "valid": all(r["ok"] for r in results),
        "count": len(results),
        "results": results,
    }


def estimate_duration(steps: list[dict[str, Any]]) -> float | None:
    """Sum of time-based step durations (distance/open steps make it a lower bound)."""
    total = 0.0
    for s in steps:
        if s["type"] == "WorkoutRepeatStep":
            total += s["repeatValue"] * (estimate_duration(s["steps"]) or 0)
        elif s["durationType"] == "TIME":
            total += s["durationValue"]
    return total or None
