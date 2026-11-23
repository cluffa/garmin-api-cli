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
from .. import dates as _dates
from ..projections import (
    body_battery_day,
    fitness_age,
    food_log_day,
    heart_rate_day,
    hr_zones,
    hrv_day,
    hrv_summary,
    hydration_day,
    sleep_day,
    spo2_day,
    steps_day,
    stress_day,
    user_settings,
    vo2max_day,
    weight_day,
    weight_entry,
    weight_goal,
)
from .common import DATE_ARGS, State, fetch_chunks, fetch_list, max_days_option, pass_state, per_day, range_argument, resolve_range


@click.group(
    "health",
    help="Health/wellness data: steps, heart rate, sleep, stress, weight, HRV, Body Battery, "
    "hydration, SpO2, fitness age, HR zones, VO2 max, nutrition, weight goals, profile settings, menstrual cycle.",
)
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
_list_command(
    "vo2max", ep.MAXMET_DAILY, vo2max_day,
    "VO2 max estimates over a date or range (366-day chunks). Sparse: only days with a new estimate appear.",
    default="-30d:today",
)
_list_command(
    "hydration", ep.HYDRATION, hydration_day,
    "Daily hydration over a date or range (31-day request chunks). Empty unless hydration is logged in Garmin Connect.",
)
_list_command(
    "wellness-activity", ep.WELLNESS_ACTIVITIES, lambda d: d,
    "Wellness activity summaries (yoga, breathwork, meditation...) over a date or range. "
    "Slim output is the raw records: the endpoint returned [] for every probed range on this account, "
    "so no field projection is defined yet.",
)


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


@health.command(
    "weight",
    context_settings=DATE_ARGS,
    help="Weight over a date or range (grams converted to kg). Default: daily summaries from weight/range. "
    "--entries: every individual weigh-in from weight/all.",
)
@range_argument("-30d:today")
@click.option("--entries", is_flag=True, help="List each weigh-in (weight/all) instead of per-day summaries (weight/range).")
@max_days_option
@pass_state
def weight(state: State, range_spec: str | None, entries: bool, max_days: int) -> None:
    rng = resolve_range(range_spec, max_days, "-30d:today")
    if entries:
        rows = fetch_list(state.client, ep.WEIGHT_ALL, rng)
        if state.full:
            state.ok(rows)
            return
        state.ok(sorted((weight_entry(e) for e in rows if isinstance(e, dict)), key=lambda r: r["date"] or ""))
        return
    payloads = fetch_chunks(state.client, ep.WEIGHT_RANGE, rng)
    if state.full:
        state.ok(payloads[0] if len(payloads) == 1 else payloads)
        return
    days = [d for p in payloads for d in as_list((p or {}).get("dailyWeightSummaries"))]
    state.ok(sorted((weight_day(d) for d in days), key=lambda r: r["date"] or ""))


@health.command("weight-goal", context_settings=DATE_ARGS, help="Effective weight goal over a date or range.")
@range_argument()
@max_days_option
@pass_state
def weight_goal_cmd(state: State, range_spec: str | None, max_days: int) -> None:
    rng = resolve_range(range_spec, max_days)
    payloads = fetch_chunks(state.client, ep.WEIGHT_GOAL, rng)
    if state.full:
        state.ok(payloads[0] if len(payloads) == 1 else payloads)
        return
    goals: list[dict] = []
    for p in payloads:
        for g in weight_goal(p):
            if g not in goals:
                goals.append(g)
    state.ok(goals[0] if rng.is_single and len(goals) == 1 else goals)


def _per_day_command(name: str, endpoint: ep.Endpoint, project, help_text: str):
    """Register a command backed by a {date}-path endpoint, heart-rate style."""

    @health.command(name, context_settings=DATE_ARGS, help=help_text)
    @range_argument()
    @max_days_option
    @pass_state
    def _cmd(state: State, range_spec: str | None, max_days: int) -> None:
        rng = resolve_range(range_spec, max_days)
        fetch = lambda d: state.client.get_json(endpoint, date=d.isoformat())  # noqa: E731
        state.ok(per_day(rng, fetch, (lambda p: p) if state.full else project))

    return _cmd


_per_day_command(
    "spo2", ep.SPO2_ACCLIMATION, spo2_day,
    "SpO2 and altitude acclimation for a date (or per-day over a range). One request per day.",
)
_per_day_command(
    "fitness-age", ep.FITNESS_AGE, fitness_age,
    "Fitness age for a date (or per-day over a range). One request per day.",
)
_per_day_command(
    "nutrition", ep.FOOD_LOGS, food_log_day,
    "Garmin food logs (goals + logged foods per meal) for a date (or per-day over a range). One request per day.",
)


@health.command("hr-zones", help="Heart rate zone definitions per sport (floors expanded into ranges).")
@pass_state
def hr_zones_cmd(state: State) -> None:
    raw = state.client.get_json(ep.HR_ZONES)
    state.ok(raw if state.full else hr_zones(raw))


@health.command("settings", help="User profile settings: units, formats, time zone, hydration containers (display name not projected).")
@pass_state
def settings_cmd(state: State) -> None:
    raw = state.client.get_json(ep.USER_SETTINGS)
    state.ok(raw if state.full else user_settings(raw))


@health.command(
    "menstrual-summary",
    context_settings=DATE_ARGS,
    help="Menstrual cycle summary for a date (or per-day over a range). Null on accounts with no cycle data; "
    "no slim projection is defined (no recorded example exists to project from), so output matches --full.",
)
@range_argument()
@max_days_option
@pass_state
def menstrual_summary(state: State, range_spec: str | None, max_days: int) -> None:
    rng = resolve_range(range_spec, max_days)
    fetch = lambda d: state.client.get_json(ep.MENSTRUAL_SUMMARY, date=d.isoformat())  # noqa: E731
    state.ok(per_day(rng, fetch, lambda p: p))


@health.command(
    "menstrual-day",
    context_settings=DATE_ARGS,
    help="Menstrual cycle day view for a date (or per-day over a range); the API's todayDate parameter is "
    "always today. Null on accounts with no cycle data; output matches --full (see menstrual-summary).",
)
@range_argument()
@max_days_option
@pass_state
def menstrual_day(state: State, range_spec: str | None, max_days: int) -> None:
    rng = resolve_range(range_spec, max_days)
    today = _dates.today().isoformat()
    fetch = lambda d: state.client.get_json(  # noqa: E731
        ep.MENSTRUAL_DAYVIEW, date=d.isoformat(), params={"todayDate": today}
    )
    state.ok(per_day(rng, fetch, lambda p: p))


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
