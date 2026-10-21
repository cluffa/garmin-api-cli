"""`stats`: daily summaries plus local aggregations; Garmin-derived metrics are stubs."""

from __future__ import annotations

from datetime import timedelta

import click

from .. import aggregate
from .. import endpoints as ep
from ..dates import DateRange, parse_date, week_start
from ..errors import UsageError
from ..output import as_list
from ..projections import daily_summary
from .activity import search_activities
from .common import DATE_ARGS, State, add_unsupported, fetch_list, max_days_option, pass_state, range_argument, resolve_range

MAX_ACTIVITIES = 5000


@click.group("stats", help="Daily summaries and locally aggregated training volume.")
def stats() -> None:
    pass


@stats.command("summary", context_settings=DATE_ARGS, help="Daily summary: steps, distance, floors, calories, HR, intensity minutes, stress, Body Battery, respiration.")
@range_argument()
@max_days_option
@pass_state
def summary(state: State, range_spec: str | None, max_days: int) -> None:
    rng = resolve_range(range_spec, max_days)
    days = fetch_list(state.client, ep.DAILY_SUMMARIES, rng, lambda p: as_list((p or {}).get("data")))
    if state.full:
        state.ok(days[0] if rng.is_single and len(days) == 1 else days)
        return
    projected = [daily_summary(d) for d in days]
    state.ok((projected[0] if projected else None) if rng.is_single else projected)


@stats.command("weekly", context_settings=DATE_ARGS, help="Weekly running volume: this week, previous week, 4-week average, longest run, run count.")
@click.argument("date_spec", metavar="[DATE]", required=False)
@click.option("--week-start", "first_day", type=click.Choice(["monday", "sunday"]), default="monday", show_default=True)
@pass_state
def weekly(state: State, date_spec: str | None, first_day: str) -> None:
    ref = parse_date(date_spec or "today")
    first = 0 if first_day == "monday" else 6
    rng = DateRange(week_start(ref, first) - timedelta(weeks=4), ref)
    acts = search_activities(state.client, limit=MAX_ACTIVITIES, activity_type="running", rng=rng)
    if state.full:
        state.ok(acts)
        return
    state.ok(aggregate.running_weekly(acts, ref=ref, first_weekday=first))


@stats.command("progress", context_settings=DATE_ARGS, help="Activity totals per type between START and END (default END: today).")
@click.argument("start")
@click.argument("end", required=False, default="today")
@click.option("--type", "activity_type", help="Only this activity type key.")
@click.option("--miles", is_flag=True)
@max_days_option
@pass_state
def progress(state: State, start: str, end: str, activity_type: str | None, miles: bool, max_days: int) -> None:
    if ":" in start:
        raise UsageError("pass START and END as two arguments")
    rng = resolve_range(f"{start}:{end}", max_days)
    acts = search_activities(state.client, limit=MAX_ACTIVITIES, activity_type=activity_type, rng=rng)
    if state.full:
        state.ok(acts)
        return
    state.ok({"range": rng.to_dict(), **aggregate.progress(acts, miles=miles)})


add_unsupported(stats, "records", "Personal records.")
add_unsupported(stats, "training-status", "Training status (load, load ratio, focus).")
add_unsupported(stats, "readiness", "Training readiness score.")
