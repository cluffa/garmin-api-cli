"""Original-file handling: unzip the official download and decode FIT laps locally."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from typing import Any

from .errors import ApiError
from .output import round_or_none
from .projections import distance, pace


@dataclass(frozen=True)
class OriginalFile:
    name: str
    content: bytes

    @property
    def extension(self) -> str:
        return self.name.rsplit(".", 1)[-1].lower() if "." in self.name else ""

    @property
    def is_fit(self) -> bool:
        return self.extension == "fit" or self.content[8:12] == b".FIT"


def extract_original(payload: bytes) -> OriginalFile:
    """The download endpoint returns a ZIP holding the original upload (normally one .fit)."""
    if payload[:4] != b"PK\x03\x04":
        # Not a ZIP: accept a bare FIT body defensively.
        if payload[8:12] == b".FIT":
            return OriginalFile("activity.fit", payload)
        raise ApiError("activity download was neither a ZIP nor a FIT file")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            if not names:
                raise ApiError("activity download ZIP is empty")
            fit_names = [n for n in names if n.lower().endswith(".fit")]
            name = (fit_names or names)[0]
            return OriginalFile(name.rsplit("/", 1)[-1], zf.read(name))
    except zipfile.BadZipFile:
        raise ApiError("activity download ZIP is corrupt") from None


def decode_laps(fit_bytes: bytes) -> list[dict[str, Any]]:
    from garmin_fit_sdk import Decoder, Stream

    decoder = Decoder(Stream.from_byte_array(bytearray(fit_bytes)))
    if not decoder.is_fit():
        raise ApiError("original activity file is not a valid FIT file")
    messages, errors = decoder.read(
        apply_scale_and_offset=True,
        convert_datetimes_to_dates=True,
        convert_types_to_strings=True,
        merge_heart_rates=False,
    )
    laps = messages.get("lap_mesgs", [])
    if errors and not laps:
        raise ApiError("could not decode FIT file", detail=str(errors[0])[:200])
    return laps


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def lap_projection(lap: dict[str, Any], index: int, *, miles: bool) -> dict[str, Any]:
    unit = "mi" if miles else "km"
    speed = lap.get("enhanced_avg_speed", lap.get("avg_speed"))
    timer = lap.get("total_timer_time")
    return {
        "lap": index + 1,
        "start_utc": _iso(lap.get("start_time")),
        f"distance_{unit}": distance(lap.get("total_distance"), miles),
        "timer_s": round_or_none(timer, 1),
        "elapsed_s": round_or_none(lap.get("total_elapsed_time"), 1),
        "pace": pace(speed, miles),
        "avg_speed_mps": round_or_none(speed, 3),
        "avg_hr": lap.get("avg_heart_rate"),
        "max_hr": lap.get("max_heart_rate"),
        "avg_cadence": lap.get("avg_running_cadence", lap.get("avg_cadence")),
        "avg_power": lap.get("avg_power"),
        "ascent_m": lap.get("total_ascent"),
        "descent_m": lap.get("total_descent"),
        "calories": lap.get("total_calories"),
        "intensity": lap.get("intensity"),
        "split_type": lap.get("lap_trigger"),
    }


def splits_from_download(payload: bytes, *, miles: bool) -> dict[str, Any]:
    original = extract_original(payload)
    if not original.is_fit:
        raise ApiError(
            f"original file is .{original.extension or '?'}, not FIT; laps can only be decoded from FIT",
            file=original.name,
        )
    laps = decode_laps(original.content)
    return {
        "source": "fit_laps",
        "file": original.name,
        "count": len(laps),
        "laps": [lap_projection(lap, i, miles=miles) for i, lap in enumerate(laps)],
    }
