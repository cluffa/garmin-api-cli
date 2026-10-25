"""JSON Schema for the workout spec (what `workout schema` prints)."""

from __future__ import annotations

from typing import Any

from .spec import INTENSITY, MAX_REPEAT, SPORTS

_PAIR = lambda item: {"oneOf": [item, {"type": "array", "items": item, "minItems": 1, "maxItems": 2}]}  # noqa: E731

STEP: dict[str, Any] = {
    "type": "object",
    "required": ["type"],
    "additionalProperties": False,
    "properties": {
        "type": {"enum": list(INTENSITY)},
        "duration": {
            "description": "omit for an open (lap-button) step",
            "oneOf": [
                {"type": "object", "required": ["time"], "additionalProperties": False,
                 "properties": {"time": {"type": ["string", "number"], "examples": ["10min", "45s", "1h30min", "4:00"]}}},
                {"type": "object", "required": ["distance"], "additionalProperties": False,
                 "properties": {"distance": {"type": ["string", "number"], "examples": ["400m", "1km", "1mi"]}}},
            ],
        },
        "target": {
            "oneOf": [
                {"type": "object", "required": ["pace"], "additionalProperties": False,
                 "properties": {"pace": _PAIR({"type": "string", "pattern": r"^\d{1,2}:[0-5]\d/(km|mi)$"})},
                 "description": "running only"},
                {"type": "object", "required": ["speed"], "additionalProperties": False,
                 "properties": {"speed": _PAIR({"type": ["string", "number"], "examples": ["30km/h", "18mph"]})}},
                {"type": "object", "required": ["power"], "additionalProperties": False,
                 "properties": {"power": _PAIR({"type": ["integer", "string"], "examples": [250, "250W"]})}},
                {"type": "object", "required": ["hr"], "additionalProperties": False,
                 "properties": {"hr": _PAIR({"type": ["integer", "string"], "examples": [150]})}},
            ]
        },
        "note": {"type": "string", "maxLength": 512},
    },
}

REPEAT: dict[str, Any] = {
    "type": "object",
    "required": ["repeat", "steps"],
    "additionalProperties": False,
    "properties": {
        "repeat": {"type": "integer", "minimum": 1, "maximum": MAX_REPEAT},
        "steps": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/stepOrRepeat"}},
    },
}

WORKOUT: dict[str, Any] = {
    "type": "object",
    "required": ["name", "steps"],
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string", "minLength": 1, "maxLength": 80},
        "sport": {"enum": list(SPORTS), "default": "running"},
        "date": {"type": "string", "format": "date", "description": "publish also schedules the workout on this date"},
        "notes": {"type": "string"},
        "steps": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/stepOrRepeat"}},
    },
}

SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "garmin workout spec",
    "type": "object",
    "required": ["workouts"],
    "additionalProperties": False,
    "properties": {"workouts": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/workout"}}},
    "$defs": {
        "workout": WORKOUT,
        "step": STEP,
        "repeat": REPEAT,
        "stepOrRepeat": {"oneOf": [{"$ref": "#/$defs/step"}, {"$ref": "#/$defs/repeat"}]},
    },
}
