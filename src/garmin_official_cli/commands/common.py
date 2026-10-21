"""Shared command plumbing: CLI state, output helpers, range fetching, unsupported stubs."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import click

from .. import endpoints as ep
from ..client import PersonalApiClient, Settings, Transport
from ..dates import DEFAULT_MAX_DAYS, DateRange, parse_range
from ..errors import ApiError, CliError, UnsupportedError
from ..models import support_for
from ..output import emit, success

# Lets relative date specs such as "-7d:today" pass as positional arguments
# instead of being parsed as (unknown) short options.
DATE_ARGS = {"ignore_unknown_options": True}

# Tests replace this to inject a fake transport; None means real HTTP.
TRANSPORT_FACTORY: Callable[[], Transport] | None = None


@dataclass
class State:
    fmt: str = "json"
    full: bool = False
    settings: Settings = field(default_factory=Settings.from_env)
    _client: PersonalApiClient | None = None

    @property
    def client(self) -> PersonalApiClient:
        if self._client is None:
            transport = TRANSPORT_FACTORY() if TRANSPORT_FACTORY else None
            self._client = PersonalApiClient(self.settings, transport)
        return self._client

    def ok(self, data: Any) -> None:
        emit(success(data), self.fmt, sys.stdout)


pass_state = click.make_pass_decorator(State, ensure=True)


def max_days_option(f: Callable) -> Callable:
    return click.option(
        "--max-days",
        type=int,
        default=DEFAULT_MAX_DAYS,
        show_default=True,
        help="Cap on the number of days a range may span.",
    )(f)


def range_argument(default: str = "today") -> Callable:
    def deco(f: Callable) -> Callable:
        return click.argument("range_spec", metavar="[RANGE]", required=False, default=None)(f)

    return deco


def resolve_range(spec: str | None, max_days: int, default: str = "today") -> DateRange:
    return parse_range(spec, default=default, max_days=max_days)


def range_call(client: PersonalApiClient, endpoint: ep.Endpoint, chunk: DateRange) -> Any:
    """Call a range endpoint whose dates live either in the path or in startDate/endDate params."""
    s, e = chunk.start.isoformat(), chunk.end.isoformat()
    if "{start}" in endpoint.path:
        return client.get_json(endpoint, start=s, end=e)
    return client.get_json(endpoint, params={"startDate": s, "endDate": e})


def fetch_chunks(client: PersonalApiClient, endpoint: ep.Endpoint, rng: DateRange) -> list[Any]:
    """One request per ``endpoint.max_days`` chunk; returns the raw payload of each chunk."""
    size = endpoint.max_days or rng.days
    return [range_call(client, endpoint, chunk) for chunk in rng.chunks(size)]


def fetch_list(
    client: PersonalApiClient,
    endpoint: ep.Endpoint,
    rng: DateRange,
    extract: Callable[[Any], list[Any]] = lambda p: p if isinstance(p, list) else [],
) -> list[Any]:
    """Fetch a range endpoint in chunks and concatenate its per-day records."""
    out: list[Any] = []
    for payload in fetch_chunks(client, endpoint, rng):
        out.extend(extract(payload) or [])
    return out


def per_day(rng: DateRange, fetch: Callable[[date], Any], project: Callable[[Any], Any]) -> Any:
    """Day-by-day loop for endpoints without a range variant.

    Single date -> the day's payload. Range -> ``[{date, data}]`` ascending; a failed
    day carries ``data: null`` plus ``error``. Fails (exit 4) only when every day failed.
    """
    if rng.is_single:
        return project(fetch(rng.start))
    results, failures = [], 0
    for day in rng:
        try:
            results.append({"date": day.isoformat(), "data": project(fetch(day))})
        except CliError as exc:
            if exc.exit_code == 3:  # auth failures abort the whole range
                raise
            failures += 1
            results.append({"date": day.isoformat(), "data": None, "error": exc.message})
    if failures == len(results):
        raise ApiError(f"all {failures} days failed", first_error=results[0].get("error"))
    return results


def unsupported(command_path: str) -> None:
    s = support_for(command_path)
    raise UnsupportedError(
        f"`{command_path}` is not available through the official Garmin Connect APIs",
        reason=s.reason,
        tier_required=s.tier,
    )


def add_unsupported(group: click.Group, name: str, help_text: str) -> None:
    """Register a stub that accepts any old-style arguments and returns the unsupported envelope."""
    path = f"{group.name} {name}"

    @group.command(
        name,
        help=f"[UNSUPPORTED] {help_text}",
        context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
        add_help_option=True,
    )
    @click.argument("args", nargs=-1, type=click.UNPROCESSED)
    def _stub(args: tuple[str, ...]) -> None:
        unsupported(path)
