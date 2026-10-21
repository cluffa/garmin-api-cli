"""`health`: daily wellness data from the Personal API."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import click

from .. import aggregate
from .. import endpoints as ep
from ..dates import DateRange, parse_date, week_start
from ..errors import UsageError
from ..output import as_list
from ..projections import (
    body_battery_day,
    heart_rate_day,
    hrv_day,
    hrv_summary,
    sleep_day,
    steps_day,
    stress_day,
    weight_day,
)
from .common import DATE_ARGS, State, fetch_chunks, fetch_list, max_days_option, pass_state, per_day, range_argument, resolve_range


@click.group("health", help="Health/wellness data: steps, heart rate, sleep, stress, weight, HRV, Body Battery.")
def health() -> None:
    pass


def _list_command(name: str, endpoint: ep.Endpoint, project, help_text: str, default: str = "today"):
    @health.command(name, context_settings=DATE_ARGS, help=help_text)
    @range_argument(default)
    @max_days_option
    @pass_state
    def _cmd(state: State, range_spec: str | None, max_days: int) -> None:
        rng = resolve_range(range_spec, max_days, default)
        days = fetch_list(state.client, endpoint, rng)
        state.ok(days if state.full else [project(d) for d in days])

    return _cmd


_list_command("steps", ep.DAILY_STEPS, steps_day, "Daily steps over a date or range (28-day request chunks).")
_list_command("stress", ep.DAILY_STRESS, stress_day, "Daily stress over a date or range (28-day request chunks).")
_list_command("body-battery", ep.BODY_BATTERY, body_battery_day, "Body Battery daily reports over a date or range.")


@health.command("heart-rate", context_settings=DATE_ARGS, help="Daily heart rate (resting/min/max). One request per day.")
@range_argument()
@max_days_option
@pass_state
def heart_rate(state: State, range_spec: str | None, max_days: int) -> None:
    rng = resolve_range(range_spec, max_days)
    fetch = lambda d: state.client.get_json(ep.DAILY_HEART_RATE, params={"date": d.isoformat()})  # noqa: E731
    state.ok(per_day(rng, fetch, (lambda p: p) if state.full else heart_rate_day))


@health.command("sleep", context_settings=DATE_ARGS, help="Sleep for a date (dailySleep) or a range (sleep summaries, 31-day chunks).")
@range_argument()
@max_days_option
@pass_state
def sleep(state: State, range_spec: str | None, max_days: int) -> None:
    rng = resolve_range(range_spec, max_days)
    if rng.is_single:
        raw = state.client.get_json(ep.DAILY_SLEEP, params={"date": rng.start.isoformat()})
        state.ok(raw if state.full else sleep_day(raw))
        return
    days = fetch_list(state.client, ep.SLEEP_SUMMARIES, rng)
    state.ok(days if state.full else [sleep_day(d) for d in days])


@health.command("hrv", context_settings=DATE_ARGS, help="HRV: summary + reading count for a date, or daily summaries for a range.")
@range_argument()
@max_days_option
@pass_state
def hrv(state: State, range_spec: str | None, max_days: int) -> None:
    rng = resolve_range(range_spec, max_days)
    if rng.is_single:
        raw = state.client.get_json(ep.HRV_DAY, date=rng.start.isoformat())
        state.ok(raw if state.full else hrv_day(raw))
        return
    days = fetch_list(state.client, ep.HRV_SUMMARIES, rng, lambda p: as_list((p or {}).get("hrvSummaries")))
    state.ok(days if state.full else [hrv_summary(d) for d in days])


@health.command("weight", context_settings=DATE_ARGS, help="Weigh-ins over a date or range (grams converted to kg).")
@range_argument("-30d:today")
@max_days_option
@pass_state
def weight(state: State, range_spec: str | None, max_days: int) -> None:
    rng = resolve_range(range_spec, max_days, "-30d:today")
    payloads = fetch_chunks(state.client, ep.WEIGHT_RANGE, rng)
    if state.full:
        state.ok(payloads[0] if len(payloads) == 1 else payloads)
        return
    days = [d for p in payloads for d in as_list((p or {}).get("dailyWeightSummaries"))]
    state.ok(sorted((weight_day(d) for d in days), key=lambda r: r["date"] or ""))


def _weeks_range(date_spec: str | None, weeks: int, max_days: int) -> DateRange:
    if weeks < 1:
        raise UsageError("--weeks must be >= 1")
    end = parse_date(date_spec or "today")
    start = week_start(end) - timedelta(weeks=weeks - 1)
    rng = DateRange(start, end)
    if rng.days > max_days:
        raise UsageError(f"{weeks} weeks span {rng.days} days, above the cap of {max_days}", hint="pass --max-days")
    return rng


def _weekly(name: str, endpoint: ep.Endpoint, agg, help_text: str):
    @health.command(name, context_settings=DATE_ARGS, help=help_text)
    @click.argument("date_spec", metavar="[DATE]", required=False)
    @click.option("--weeks", type=int, default=52, show_default=True)
    @max_days_option
    @pass_state
    def _cmd(state: State, date_spec: str | None, weeks: int, max_days: int) -> None:
        rng = _weeks_range(date_spec, weeks, max_days)
        days = fetch_list(state.client, endpoint, rng)
        data: Any = days if state.full else {"range": rng.to_dict(), "weeks": agg(days)}
        state.ok(data)

    return _cmd


_weekly("weekly-steps", ep.DAILY_STEPS, aggregate.weekly_steps, "Weekly step totals (Mon-start weeks ending at DATE), aggregated locally.")
_weekly("weekly-stress", ep.DAILY_STRESS, aggregate.weekly_stress, "Weekly average stress (Mon-start weeks ending at DATE), aggregated locally.")
