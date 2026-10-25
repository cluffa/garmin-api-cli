"""Every official endpoint path the CLI calls, in one place.

Correct a path or a range limit here and every command follows. Sources and
verification status for each entry are documented in ``docs/API_NOTES.md``.

Personal API paths come from Garmin's own client, ``garmin-connect-personal-api-python``
1.0.0 (Apache-2.0, published by Garmin Ltd. on 2026-10-21), except where marked
``source="live-probe"``. ``max_days`` values were measured against the live API on
2026-10-21: a longer span returns HTTP 400 (or 500).
"""

from __future__ import annotations

from dataclasses import dataclass, field

PERSONAL_DEFAULT_BASE_URL = "https://personal.connectapi.garmin.com"
TRAINING_DEFAULT_BASE_URL = "https://apis.garmin.com"

SOURCE_GARMIN_CLIENT = "garmin-connect-personal-api-python 1.0.0"
SOURCE_LIVE_PROBE = "live probe 2026-10-21"
SOURCE_TRAINING_DOC = "Garmin Training API docs (not publicly verified)"


@dataclass(frozen=True)
class Endpoint:
    name: str
    method: str
    path: str  # str.format template, e.g. "/hrv-service/hrv/{date}"
    api: str = "personal"  # "personal" | "training"
    max_days: int | None = None  # longest inclusive date span accepted in one call
    params: dict[str, str] = field(default_factory=dict)  # fixed query params
    accept: str = "application/json"
    source: str = SOURCE_GARMIN_CLIENT

    def format(self, **values: object) -> str:
        return self.path.format(**values)


# --- Personal API: auth ------------------------------------------------------
TOKEN = Endpoint(
    "token", "POST", "/personalapitoken-service/personal-api/personal-api-key/token", accept="*/*"
)

# --- Personal API: activities --------------------------------------------------
ACTIVITY_SEARCH = Endpoint("activity_search", "GET", "/activitylist-service/activities/search/activities")
ACTIVITY = Endpoint("activity", "GET", "/activity-service/activity/{activity_id}")
ACTIVITY_DETAILS = Endpoint(
    "activity_details", "GET", "/activity-service/activity/{activity_id}/details", source=SOURCE_LIVE_PROBE
)
ACTIVITY_WORKOUTS = Endpoint("activity_workouts", "GET", "/activity-service/activity/{activity_id}/workouts")
ACTIVITY_DOWNLOAD = Endpoint(
    "activity_download",
    "GET",
    "/download-service/files/activity/{activity_id}",
    accept="application/zip, application/x-zip-compressed, application/octet-stream",
)

# --- Personal API: health ------------------------------------------------------
DAILY_STEPS = Endpoint("daily_steps", "GET", "/usersummary-service/stats/steps/daily/{start}/{end}", max_days=28)
DAILY_STRESS = Endpoint("daily_stress", "GET", "/usersummary-service/stats/stress/daily/{start}/{end}", max_days=28)
DAILY_SLEEP = Endpoint("daily_sleep", "GET", "/sleep-service/sleep/dailySleep")  # ?date=
SLEEP_SUMMARIES = Endpoint(
    "sleep_summaries", "GET", "/sleep-service/sleep/dailySleepSummariesByDate", max_days=31
)  # ?startDate=&endDate=
BODY_BATTERY = Endpoint(
    "body_battery", "GET", "/wellness-service/wellness/bodyBattery/reports/daily", max_days=31
)  # ?startDate=&endDate=
DAILY_HEART_RATE = Endpoint("daily_heart_rate", "GET", "/wellness-service/wellness/dailyHeartRate")  # ?date=
HRV_DAY = Endpoint("hrv_day", "GET", "/hrv-service/hrv/{date}")
HRV_SUMMARIES = Endpoint("hrv_summaries", "GET", "/hrv-service/hrv/daily/{start}/{end}", max_days=366)
WEIGHT_RANGE = Endpoint(
    "weight_range", "GET", "/weight-service/weight/range/{start}/{end}", max_days=366, params={"includeAll": "true"}
)
# 60 days verified; 90 returned HTTP 500. 31 keeps a margin.
DAILY_SUMMARIES = Endpoint("daily_summaries", "GET", "/usersummary-service/v2/dailysummaries", max_days=31)

# Other Personal API GET endpoints Garmin's client wraps. The CLI has no dedicated
# commands for them; call them with `garmin api get PATH`.
OTHER_PERSONAL_PATHS = (
    "/usersummary-service/stats/hydration/daily/{start}/{end}",
    "/goal-service/goal/user/effective/weightgoal/{start}/{end}",
    "/nutrition-service/food/logs/{date}",
    "/userprofile-service/userprofile/settings",
    "/biometric-service/heartRateZones/v2",
    "/fitnessage-service/fitnessage/v2/{date}",
    "/wellness-service/wellness/daily/spo2acclimation/{date}",
    "/wellnessactivity-service/activity/summary/range/{start}/{end}",
    "/periodichealth-service/menstrualcycle/summary/{date}",
    "/periodichealth-service/menstrualcycle/dayview/{date}?todayDate={today}",
)

# --- Training API (Starter Business tier, push/cloud model) ---------------------
TRAINING_WORKOUT_CREATE = Endpoint(
    "training_workout_create", "POST", "/training-api/workout", api="training", source=SOURCE_TRAINING_DOC
)
TRAINING_SCHEDULE_CREATE = Endpoint(
    "training_schedule_create", "POST", "/training-api/schedule", api="training", source=SOURCE_TRAINING_DOC
)

ALL = tuple(v for v in list(globals().values()) if isinstance(v, Endpoint))
