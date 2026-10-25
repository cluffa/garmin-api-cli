"""`capabilities` (one-call discovery) and `api get` (raw Personal API passthrough)."""

from __future__ import annotations

from typing import Any

import click

from .. import __version__
from .. import endpoints as ep
from ..dates import DEFAULT_MAX_DAYS
from ..errors import UsageError
from ..models import SUPPORT, UNSUPPORTED, workout_publish_support
from ..workouts.schema import SCHEMA
from .common import State, pass_state

ENV_VARS = {
    "GARMIN_PERSONAL_API_KEY": "the Personal API key (takes precedence over key files)",
    "GARMIN_PERSONAL_API_KEY_FILE": "explicit key file (env-file or raw-key format)",
    "GARMIN_PERSONAL_API_KEY_EXPIRES": "optional YYYY-MM-DD key expiry, reported by auth status",
    "GARMIN_API_BASE_URL": f"Personal API base URL (default {ep.PERSONAL_DEFAULT_BASE_URL})",
    "GARMIN_API_KEY_HEADER": "header carrying the key in the token exchange (default Authorization)",
    "GARMIN_API_KEY_SCHEME": "scheme prefix for the key header (default ApiKey; empty = raw key)",
    "GARMIN_API_TIMEOUT": "HTTP timeout in seconds (default 30)",
    "GARMIN_BEARER_TOKEN_CACHE": "bearer-token cache path (default ~/.config/garmin-official-cli/bearer-token.json)",
    "GARMIN_TRAINING_API_BASE_URL": f"Training API base URL (default {ep.TRAINING_DEFAULT_BASE_URL})",
    "GARMIN_TRAINING_API_TOKEN": "Starter-tier Training API user access token (does not exist yet)",
}


def _params(cmd: click.Command) -> list[dict[str, Any]]:
    out = []
    for p in cmd.params:
        if isinstance(p, click.Option):
            if p.name == "help":
                continue
            out.append({"option": max(p.opts, key=len), "flag": p.is_flag, "default": None if p.is_flag else p.default, "help": p.help})
        elif isinstance(p, click.Argument) and p.name != "args":
            out.append({"argument": p.human_readable_name, "required": p.required})
    return out


def walk(group: click.Group, prefix: str = "") -> list[tuple[str, click.Command]]:
    out = []
    for name in sorted(group.commands):
        cmd = group.commands[name]
        path = f"{prefix}{name}"
        if isinstance(cmd, click.Group):
            out.extend(walk(cmd, path + " "))
        else:
            out.append((path, cmd))
    return out


def command_table(root: click.Group, state: State) -> list[dict[str, Any]]:
    rows = []
    for path, cmd in walk(root):
        support = workout_publish_support(bool(state.settings.training_token)) if path == "workout publish" else SUPPORT[path]
        rows.append(
            {
                "command": path,
                "help": (cmd.help or "").removeprefix("[UNSUPPORTED] "),
                **support.to_dict(),
                "params": _params(cmd),
            }
        )
    return rows


# Command sequences for common agent tasks; docs/COACHING.md maps each coaching need to a field.
WORKFLOWS = {
    "coach_review_month": [
        "stats weekly  # volume, longest run, weekly HR-zone time, z1_z2_pct, training load",
        "activity list --range -30d:today --limit 200  # per run: training effect, load, HR zones, cadence",
        "health hrv -30d:today; health sleep -30d:today; health heart-rate -30d:today  # recovery trend",
        "activity analyze <id>  # per key run: plan vs. execution, reps, even splits, drift, zones, RPE",
        "activity get <id>  # adds compliance score, stamina, Body Battery change, typed split summaries",
    ],
    "review_one_workout": [
        "activity workout <id>  # what was planned (API)",
        "activity analyze <id>  # how each step went (FIT); pass --miles for mile splits",
    ],
}


@click.command("capabilities", help="One-call discovery: every command with support status, the workout schema, config.")
@click.pass_context
def capabilities(ctx: click.Context) -> None:
    state = ctx.ensure_object(State)
    root = ctx.find_root().command
    assert isinstance(root, click.Group)
    rows = command_table(root, state)
    state.ok(
        {
            "name": "garmin",
            "version": __version__,
            "api": {
                "program": "Garmin Connect Developer Program",
                "active_tier": "personal",
                "delivery": "pull",
                "base_url": state.settings.base_url,
                "starter_tier": "application submitted 2026-10-21, approval pending",
            },
            "global_options": {"--format": ["json", "json-pretty", "toon"], "--full": "raw payloads instead of slim projections"},
            "date_specs": ["today", "yesterday", "tomorrow", "-7d", "+7d", "YYYY-MM-DD", "START:END"],
            "max_days_default": DEFAULT_MAX_DAYS,
            "exit_codes": {"0": "success", "1": "internal", "2": "usage", "3": "auth", "4": "api / unsupported"},
            "workflows": WORKFLOWS,
            "commands": rows,
            "unsupported": [r["command"] for r in rows if r["status"] == UNSUPPORTED],
            "workout_schema": SCHEMA,
            "env": ENV_VARS,
        }
    )


@click.group("api", help="Raw access to Personal API GET endpoints.")
def api() -> None:
    pass


@api.command("get", help="GET any Personal API path and return its JSON, e.g. /biometric-service/heartRateZones/v2.")
@click.argument("path")
@click.option("--param", "params", multiple=True, metavar="KEY=VALUE", help="Query parameter (repeatable).")
@pass_state
def api_get(state: State, path: str, params: tuple[str, ...]) -> None:
    if not path.startswith("/") or "://" in path:
        raise UsageError("PATH must be an absolute API path starting with '/'", example="/userprofile-service/userprofile/settings")
    query: dict[str, str] = {}
    for item in params:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise UsageError(f"--param must be KEY=VALUE, got {item!r}")
        query[key] = value
    state.ok(state.client.get_path(path, query or None))
