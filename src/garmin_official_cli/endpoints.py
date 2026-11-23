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
WEIGHT_ALL = Endpoint("weight_all", "GET", "/weight-service/weight/all/{start}/{end}", max_days=366)
# 60 days verified; 90 returned HTTP 500. 31 keeps a margin.
DAILY_SUMMARIES = Endpoint("daily_summaries", "GET", "/usersummary-service/v2/dailysummaries", max_days=31)
USER_SUMMARY = Endpoint("user_summary", "GET", "/usersummary-service/usersummary/daily")  # ?calendarDate=
# 31 days is Garmin's documented cap for hydration (Garmin's client + S8 clients agree);
# a 327-day single call returned HTTP 400 on 2026-11-23.
HYDRATION = Endpoint("hydration", "GET", "/usersummary-service/stats/hydration/daily/{start}/{end}", max_days=31)
# A 90-day call returned the goal on 2026-11-23; no tighter cap measured, so chunk at the global cap.
WEIGHT_GOAL = Endpoint("weight_goal", "GET", "/goal-service/goal/user/effective/weightgoal/{start}/{end}", max_days=366)
FOOD_LOGS = Endpoint("food_logs", "GET", "/nutrition-service/food/logs/{date}")
USER_SETTINGS = Endpoint("user_settings", "GET", "/userprofile-service/userprofile/settings")
HR_ZONES = Endpoint("hr_zones", "GET", "/biometric-service/heartRateZones/v2")
FITNESS_AGE = Endpoint("fitness_age", "GET", "/fitnessage-service/fitnessage/v2/{date}")
SPO2_ACCLIMATION = Endpoint("spo2_acclimation", "GET", "/wellness-service/wellness/daily/spo2acclimation/{date}")
WELLNESS_ACTIVITIES = Endpoint(
    "wellness_activities", "GET", "/wellnessactivity-service/activity/summary/range/{start}/{end}", max_days=366
)
MENSTRUAL_SUMMARY = Endpoint("menstrual_summary", "GET", "/periodichealth-service/menstrualcycle/summary/{date}")
MENSTRUAL_DAYVIEW = Endpoint(
    "menstrual_dayview", "GET", "/periodichealth-service/menstrualcycle/dayview/{date}"
)  # ?todayDate= is supplied by the command

# Personal API GET endpoints with no dedicated command; call them with `garmin api get PATH`.
# (Empty since 2026-11-23: every path Garmin's client wraps now has a command. Kept so
# future spec paths have an obvious home.)
OTHER_PERSONAL_PATHS: tuple[str, ...] = ()

# --- Training API (Starter Business tier, push/cloud model) ---------------------
TRAINING_WORKOUT_CREATE = Endpoint(
    "training_workout_create", "POST", "/training-api/workout", api="training", source=SOURCE_TRAINING_DOC
)
TRAINING_SCHEDULE_CREATE = Endpoint(
    "training_schedule_create", "POST", "/training-api/schedule", api="training", source=SOURCE_TRAINING_DOC
)

ALL = tuple(v for v in list(globals().values()) if isinstance(v, Endpoint))
