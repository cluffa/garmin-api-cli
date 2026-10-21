"""`workout`: local validate/schema; publish behind the Starter-credentials boundary."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

from .. import endpoints as ep
from ..client import TrainingApiClient
from ..errors import ApiError, CliError, UsageError
from ..workouts.schema import SCHEMA
from ..workouts.spec import SpecError, validate_spec
from . import common
from .common import State, add_unsupported, pass_state


@click.group("workout", help="Workout specs: validate/translate locally; publish via the Training API (Starter tier).")
def workout() -> None:
    pass


def spec_source(f):
    f = click.option("--json", "json_text", help="Inline JSON spec.")(f)
    f = click.option("--file", "file_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), help="JSON spec file.")(f)
    return f


def load_spec(json_text: str | None, file_path: Path | None) -> Any:
    stdin_has_data = not sys.stdin.isatty() if hasattr(sys.stdin, "isatty") else False
    sources = [s for s in (json_text is not None, file_path is not None) if s]
    if len(sources) > 1:
        raise UsageError("provide exactly one spec source: --json, --file, or stdin")
    if json_text is not None:
        raw = json_text
    elif file_path is not None:
        raw = file_path.read_text(encoding="utf-8")
    elif stdin_has_data:
        raw = sys.stdin.read()
    else:
        raise UsageError("no spec provided", hint="use --json '<spec>', --file spec.json, or pipe JSON on stdin")
    if not raw.strip():
        raise UsageError("spec is empty")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UsageError(f"spec is not valid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})") from None


def checked(spec: Any) -> dict[str, Any]:
    try:
        report = validate_spec(spec)
    except SpecError as exc:
        raise UsageError(f"invalid spec: {exc}") from None
    if not report["valid"]:
        bad = sum(not r["ok"] for r in report["results"])
        raise UsageError(f"{bad} of {report['count']} workouts failed validation", results=report["results"])
    return report


@workout.command("validate", help="Dry run: validate a spec and show its Training API translation. No network.")
@spec_source
@pass_state
def validate(state: State, json_text: str | None, file_path: Path | None) -> None:
    state.ok(checked(load_spec(json_text, file_path)))


@workout.command("schema", help="Print the workout spec JSON schema.")
@pass_state
def schema(state: State) -> None:
    state.ok(SCHEMA)


@workout.command(
    "publish",
    help="Validate, then publish each workout to Garmin Connect via the Training API (and schedule it if it has "
    "a date). Needs Starter-tier credentials ($GARMIN_TRAINING_API_TOKEN); until then returns the unsupported envelope.",
)
@spec_source
@pass_state
def publish(state: State, json_text: str | None, file_path: Path | None) -> None:
    client = TrainingApiClient(state.settings, common.TRANSPORT_FACTORY() if common.TRANSPORT_FACTORY else None)
    # Fail on the credential boundary first: no point validating what cannot be sent.
    client.require_credentials()
    report = checked(load_spec(json_text, file_path))
    results = []
    for r in report["results"]:
        entry: dict[str, Any] = {"index": r["index"], "name": r["name"]}
        try:
            created = client.post_json(ep.TRAINING_WORKOUT_CREATE, r["training_api_workout"])
            workout_id = (created or {}).get("workoutId") if isinstance(created, dict) else None
            entry["workout_id"] = workout_id
            if r.get("training_api_schedule"):
                if workout_id is None:
                    raise ApiError("workout created but no workoutId returned; cannot schedule")
                body = {**r["training_api_schedule"], "workoutId": workout_id}
                sched = client.post_json(ep.TRAINING_SCHEDULE_CREATE, body)
                entry["schedule_id"] = sched if not isinstance(sched, dict) else sched.get("scheduleId", sched)
                entry["date"] = body["date"]
            entry["ok"] = True
        except CliError as exc:
            entry.update(ok=False, error=exc.to_dict())
        results.append(entry)
    failed = [e for e in results if not e["ok"]]
    if failed:
        raise ApiError(f"{len(failed)} of {len(results)} workouts failed to publish", results=results)
    state.ok({"published": len(results), "results": results})


add_unsupported(workout, "create", "Old name for publish. Use `workout publish`.")
add_unsupported(workout, "list", "List saved workouts.")
add_unsupported(workout, "get", "Get one saved workout by ID.")
add_unsupported(workout, "delete", "Delete a saved workout.")
add_unsupported(workout, "schedule", "Schedule an existing workout to a date.")
add_unsupported(workout, "unschedule", "Remove a scheduled workout.")
add_unsupported(workout, "scheduled", "List scheduled workouts for a date or range.")
