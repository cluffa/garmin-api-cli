"""`activity`: list / get / download (.FIT) / splits (FIT laps) / workout (plan) / analyze (coaching view)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import click

from .. import endpoints as ep
from ..client import PersonalApiClient
from ..dates import DateRange
from ..errors import ApiError, UnsupportedError, UsageError
from ..coaching import Context, api_steps, workout_view
from ..fit import analysis_from_download, decode_fit, decode_laps, extract_original, splits_from_download
from ..models import NONE
from ..projections import activity_detail, activity_samples, activity_summary
from .common import State, max_days_option, pass_state, resolve_range

PAGE_SIZE = 100


@click.group("activity", help="Activities from the Personal API (JSON summaries + original .FIT files).")
def activity() -> None:
    pass


def search_activities(
    client: PersonalApiClient,
    *,
    limit: int,
    start: int = 0,
    activity_type: str | None = None,
    rng: DateRange | None = None,
) -> list[dict[str, Any]]:
    """Page through the activity search until ``limit`` items or the end of the results."""
    out: list[dict[str, Any]] = []
    offset = start
    while len(out) < limit:
        page = min(PAGE_SIZE, limit - len(out))
        params: dict[str, Any] = {"start": offset, "limit": page}
        if activity_type:
            params["activityType"] = activity_type
        if rng is not None:
            params["startDate"] = rng.start.isoformat()
            params["endDate"] = rng.end.isoformat()
        batch = client.get_json(ep.ACTIVITY_SEARCH, params=params)
        if not isinstance(batch, list):
            raise ApiError("activity search returned an unexpected payload", got=type(batch).__name__)
        out.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return out


def _activity_id(value: str) -> str:
    if not value.isascii() or not value.isdecimal() or int(value) <= 0:
        raise UsageError(f"activity id must be a positive integer, got {value!r}")
    return value


@activity.command("list", help="Recent activities, newest first (slim; --full for raw).")
@click.option("--limit", type=click.IntRange(1, 10000), default=20, show_default=True)
@click.option("--start", type=click.IntRange(0), default=0, show_default=True, help="Offset into the results.")
@click.option("--type", "activity_type", help="Activity type key, e.g. running, cycling.")
@click.option("--range", "range_spec", help="Only activities in this date range, e.g. -30d:today.")
@click.option("--miles", is_flag=True, help="Distances in miles, pace per mile.")
@max_days_option
@pass_state
def list_cmd(state: State, limit: int, start: int, activity_type: str | None, range_spec: str | None, miles: bool, max_days: int) -> None:
    rng = resolve_range(range_spec, max_days) if range_spec else None
    items = search_activities(state.client, limit=limit, start=start, activity_type=activity_type, rng=rng)
    state.ok(items if state.full else [activity_summary(a, miles=miles) for a in items])


@activity.command("get", help="One activity's summary (slim; --full for raw).")
@click.argument("activity_id")
@click.option("--miles", is_flag=True)
@click.option("--samples", is_flag=True, help="Include the time-series detail samples (one extra request).")
@pass_state
def get_cmd(state: State, activity_id: str, miles: bool, samples: bool) -> None:
    aid = _activity_id(activity_id)
    a = state.client.get_json(ep.ACTIVITY, activity_id=aid)
    data: dict[str, Any] = a if state.full else activity_detail(a, miles=miles)
    if samples:
        details = state.client.get_json(ep.ACTIVITY_DETAILS, activity_id=aid)
        if state.full:
            data = {"activity": a, "details": details}
        else:
            data["samples"] = activity_samples(details or {})
    state.ok(data)


@activity.command("download", help="Download the original activity file (.FIT). TCX/GPX are unsupported officially.")
@click.argument("activity_id")
@click.option(
    "--format-file",
    "file_format",
    type=click.Choice(["fit", "tcx", "gpx"]),
    default="fit",
    show_default=True,
    help="fit = original file. tcx/gpx return the unsupported envelope.",
)
@click.option("--out", "out_path", type=click.Path(dir_okay=False, path_type=Path), help="Output path (default <id>.fit).")
@click.option("--zip", "keep_zip", is_flag=True, help="Save Garmin's ZIP as-is instead of extracting the file.")
@click.option("--force", is_flag=True, help="Overwrite an existing output file.")
@pass_state
def download_cmd(state: State, activity_id: str, file_format: str, out_path: Path | None, keep_zip: bool, force: bool) -> None:
    aid = _activity_id(activity_id)
    if file_format in ("tcx", "gpx"):
        raise UnsupportedError(
            f"{file_format.upper()} export is not available through the official Garmin Connect APIs",
            reason="the official Activity API / Personal API deliver activity files as the original upload "
            "(.FIT for device recordings) only; the Connect TCX/GPX export endpoints return HTTP 404 on the "
            "Personal API (verified 2026-10-21)",
            tier_required=NONE,
            hint="use --format-file fit and convert locally (e.g. with the Garmin FIT SDK or GPSBabel)",
        )
    payload = state.client.get_bytes(ep.ACTIVITY_DOWNLOAD, activity_id=aid)
    if keep_zip:
        content, name, fmt = payload, f"{aid}.zip", "zip"
    else:
        original = extract_original(payload)
        content, name, fmt = original.content, original.name, original.extension or "bin"
    dest = out_path or Path(f"{aid}.{fmt}")
    if dest.exists() and not force:
        raise UsageError(f"{dest} already exists", hint="pass --force to overwrite or --out to choose another path")
    tmp = dest.with_name(f".{dest.name}.part")
    tmp.write_bytes(content)
    os.replace(tmp, dest)
    state.ok({"id": int(aid), "path": str(dest), "format": fmt, "bytes": len(content), "original_name": name})


@activity.command("splits", help="Laps/splits decoded from the activity's official .FIT file.")
@click.argument("activity_id")
@click.option("--miles", is_flag=True, help="Distances in miles, pace per mile.")
@pass_state
def splits_cmd(state: State, activity_id: str, miles: bool) -> None:
    aid = _activity_id(activity_id)
    payload = state.client.get_bytes(ep.ACTIVITY_DOWNLOAD, activity_id=aid)
    if state.full:
        original = extract_original(payload)
        state.ok({"id": int(aid), "file": original.name, "lap_mesgs": decode_laps(original.content)})
        return
    state.ok({"id": int(aid), **splits_from_download(payload, miles=miles)})


@activity.command(
    "workout",
    help="The structured workout that was run during an activity (plan steps, targets, repeats). Empty if none.",
)
@click.argument("activity_id")
@click.option("--miles", is_flag=True, help="Distances in miles, pace per mile.")
@pass_state
def workout_cmd(state: State, activity_id: str, miles: bool) -> None:
    aid = _activity_id(activity_id)
    workouts = state.client.get_json(ep.ACTIVITY_WORKOUTS, activity_id=aid)
    if state.full:
        state.ok(workouts)
        return
    ctx = Context()  # % of max HR / FTP targets stay as percentages; `activity analyze` resolves them
    state.ok(
        {
            "id": int(aid),
            "workouts": [
                {
                    "index": w.get("index"),
                    "created_utc": w.get("timeCreated"),
                    **workout_view(w.get("workoutName"), None, w.get("sport"), api_steps(w.get("steps") or []), ctx, miles),
                }
                for w in workouts or []
            ],
        }
    )


@activity.command(
    "analyze",
    help="Coaching view from the activity's .FIT: plan vs. execution per step, rep stats, even splits, drift, zones.",
)
@click.argument("activity_id")
@click.option("--miles", is_flag=True, help="Distances in miles, pace per mile, even splits per mile.")
@pass_state
def analyze_cmd(state: State, activity_id: str, miles: bool) -> None:
    aid = _activity_id(activity_id)
    payload = state.client.get_bytes(ep.ACTIVITY_DOWNLOAD, activity_id=aid)
    if state.full:
        original = extract_original(payload)
        state.ok({"id": int(aid), "file": original.name, "messages": decode_fit(original.content)})
        return
    state.ok({"id": int(aid), **analysis_from_download(payload, miles=miles)})
