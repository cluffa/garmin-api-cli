"""Support-status registry: one entry per command, consumed by `capabilities`,
the unsupported stubs, and the docs-consistency tests."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .client import STARTER_BLOCKER

SUPPORTED = "supported"
PARTIAL = "partial"
UNSUPPORTED = "unsupported"

# tier values: the official tier that provides the feature, or "none" when no tier does.
PERSONAL = "personal"
STARTER = "starter"
ENTERPRISE = "enterprise"
LOCAL = "local"  # pure local logic, no API needed
NONE = "none"

NOT_AN_OFFICIAL_TYPE = (
    "not an official Garmin Connect Developer Program data type; the Personal API gateway "
    "returns HTTP 404 for the Connect endpoint (verified 2026-10-21) and no Business API offers it"
)
TRAINING_PUBLISH_ONLY = (
    "the official Training API (Starter tier, push/cloud model, approval pending) is publish-only: "
    "it can send a workout to Garmin Connect for device sync, but exposes no workout library or "
    "calendar management for the user's own workouts; the Personal API gateway returns HTTP 404 "
    "for workout-service and calendar-service (verified 2026-10-21)"
)


@dataclass(frozen=True)
class Support:
    status: str
    tier: str
    reason: str
    old_command: str | None = None  # the old CLI command this replaces, if any

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


def _s(reason: str, tier: str = PERSONAL, old: str | None = None) -> Support:
    return Support(SUPPORTED, tier, reason, old)


def _p(reason: str, tier: str = PERSONAL, old: str | None = None) -> Support:
    return Support(PARTIAL, tier, reason, old)


def _u(reason: str, tier: str = NONE, old: str | None = None) -> Support:
    return Support(UNSUPPORTED, tier, reason, old)


SUPPORT: dict[str, Support] = {
    # auth
    "auth status": _s("reports key configuration and bearer-token cache state; --verify exchanges the key", old="auth status"),
    "auth set-key": _s("prints setup guidance for the Personal API key; never reads or writes the key", LOCAL),
    "auth refresh": _s("forces a new key -> bearer-token exchange"),
    "auth logout": _s("deletes the cached bearer token (the key itself is left untouched)", LOCAL, "auth logout"),
    "auth login": _u(
        "email/password + MFA login is gone by design: official APIs authenticate with a Personal API key "
        "(Personal tier) or OAuth app authorization (Business tiers); this CLI handles no passwords",
        old="auth login",
    ),
    # activity
    "activity list": _s("Personal API activity search (JSON)", old="activity list"),
    "activity get": _s("Personal API activity summary (JSON); --samples adds the detail time series", old="activity get"),
    "activity download": _p(
        "original file only (.FIT for device-recorded activities, delivered in a ZIP); TCX/GPX export is not "
        "offered by any official API",
        old="activity download",
    ),
    "activity splits": _p(
        "laps decoded locally from the official .FIT download; the Connect splits endpoints are not exposed "
        "(HTTP 404), so typed split labels are limited to the FIT lap trigger",
        old="activity splits",
    ),
    # health
    "health steps": _s("Personal API daily steps (range endpoint, 28-day chunks)", old="health steps"),
    "health heart-rate": _s("Personal API daily heart rate (one request per day)", old="health heart-rate"),
    "health sleep": _s("Personal API daily sleep / sleep summaries (31-day chunks)", old="health sleep"),
    "health stress": _s("Personal API daily stress (range endpoint, 28-day chunks)", old="health stress"),
    "health weight": _s("Personal API weight range (366-day chunks)", old="health weight"),
    "health hrv": _s("Personal API HRV summary + readings (single day) or HRV summaries (range)", old="health hrv"),
    "health body-battery": _s(
        "Personal API Body Battery daily reports (31-day chunks); available on the Personal tier even though "
        "it is not a standard Business Health API summary type",
        old="health body-battery",
    ),
    "health weekly-steps": _s("local weekly aggregation over official daily steps", old="health weekly-steps"),
    "health weekly-stress": _s("local weekly aggregation over official daily stress", old="health weekly-stress"),
    # stats
    "stats summary": _s("Personal API daily summaries (v2)", old="stats summary"),
    "stats weekly": _s("local aggregation of official running activities", old="stats weekly"),
    "stats progress": _s("local aggregation of official activities between two dates", old="stats progress"),
    "stats records": _u(f"personal records are {NOT_AN_OFFICIAL_TYPE}", old="stats records"),
    "stats training-status": _u(
        f"training status is a Garmin Connect proprietary derived metric; {NOT_AN_OFFICIAL_TYPE}",
        old="stats training-status",
    ),
    "stats readiness": _u(
        f"training readiness is a Garmin Connect proprietary derived metric; {NOT_AN_OFFICIAL_TYPE}",
        old="stats readiness",
    ),
    # badges
    **{
        f"badge {name}": _u(f"badges and challenges are {NOT_AN_OFFICIAL_TYPE}", old=f"badge {name}")
        for name in ("earned", "in-progress", "available", "adhoc", "challenges")
    },
    # workouts
    "workout validate": _s("local spec validation + translation to the Training API workout format", LOCAL, "workout validate"),
    "workout schema": _s("local JSON schema of the workout spec", LOCAL, "workout schema"),
    "workout publish": _u(STARTER_BLOCKER, STARTER, "workout create"),
    "workout create": _u(
        "renamed: use `workout publish` (Training API, Starter tier). " + STARTER_BLOCKER, STARTER, "workout create"
    ),
    **{
        f"workout {name}": _u(TRAINING_PUBLISH_ONLY, old=f"workout {name}")
        for name in ("list", "get", "delete", "schedule", "unschedule", "scheduled")
    },
    # meta
    "capabilities": _s("one-call discovery incl. support status per command", LOCAL, "capabilities"),
    "api get": _s("raw GET passthrough to any Personal API path (for endpoints without a dedicated command)"),
}


def support_for(command_path: str) -> Support:
    return SUPPORT[command_path]


def workout_publish_support(training_token_present: bool) -> Support:
    if training_token_present:
        return _p(
            "publishes via the Training API with $GARMIN_TRAINING_API_TOKEN; publish-only (no library/calendar "
            "management). Request format is unverified until tested against Garmin's API",
            STARTER,
            "workout create",
        )
    return SUPPORT["workout publish"]
