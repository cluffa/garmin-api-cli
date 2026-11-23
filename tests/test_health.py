from conftest import (
    bb_day,
    fixture,
    hrv_summary_day,
    json_response,
    range_handler,
    sleep_summary_day,
    steps_day,
    stress_day,
)

STEPS = "/usersummary-service/stats/steps/daily/"
STRESS = "/usersummary-service/stats/stress/daily/"


def route_range(transport, prefix, make, wrap=lambda x: x):
    transport.add_prefix("GET", prefix, range_handler(make, style="path", wrap=wrap))


def test_steps_single_and_chunked(cli, transport):
    route_range(transport, STEPS, steps_day)
    r = cli("health", "steps")
    assert r.data == [{"date": "2026-10-21", "steps": 8000, "goal": 8000, "distance_m": 6000}]
    r = cli("health", "steps", "-40d:today")
    assert len(r.data) == 41
    assert [d["date"] for d in r.data] == sorted(d["date"] for d in r.data)
    calls = transport.data_calls()[1:]
    assert [c.path for c in calls] == [
        "/usersummary-service/stats/steps/daily/2026-09-11/2026-10-08",
        "/usersummary-service/stats/steps/daily/2026-10-09/2026-10-21",
    ]


def test_stress_negative_level_is_null(cli, transport):
    route_range(transport, STRESS, stress_day)
    d = cli("health", "stress", "-3d:today").data
    assert [x["avg_stress"] for x in d] == [20, 21, None, 23]
    assert d[0]["high_s"] == 600


def test_sleep_single_and_range(cli, transport):
    transport.add("GET", "/sleep-service/sleep/dailySleep", fixture("sleep.json"))
    d = cli("health", "sleep").data
    assert d["date"] == "2026-10-21" and d["sleep_s"] == 27000 and d["score"] == 82 and d["score_qualifier"] == "GOOD"
    assert d["start_local"] == "2026-10-19T22:00:00"
    assert transport.data_calls()[0].params == {"date": "2026-10-21"}
    transport.add("GET", "/sleep-service/sleep/dailySleepSummariesByDate", range_handler(sleep_summary_day, style="params"))
    d = cli("health", "sleep", "-40d:today").data
    assert len(d) == 41 and d[0]["date"] == "2026-09-11"
    assert len([c for c in transport.data_calls() if "Summaries" in c.path]) == 2  # 31 + 10


def test_sleep_no_data_is_null(cli, transport):
    transport.add("GET", "/sleep-service/sleep/dailySleep", {})
    assert cli("health", "sleep").data is None


def test_heart_rate_per_day_with_partial_failure(cli, transport):
    def handler(call):
        if call.params["date"] == "2026-10-20":
            return json_response({"error": "x"}, 500)
        return {**fixture("heart_rate.json"), "calendarDate": call.params["date"]}

    transport.add("GET", "/wellness-service/wellness/dailyHeartRate", handler)
    single = cli("health", "heart-rate", "2026-10-19").data
    assert single == {"date": "2026-10-19", "resting_hr": 44, "min_hr": 41, "max_hr": 170, "resting_hr_7d_avg": 45, "samples": 3}
    r = cli("health", "heart-rate", "2026-10-19:2026-10-21")
    assert r.code == 0
    assert [x["date"] for x in r.data] == ["2026-10-19", "2026-10-20", "2026-10-21"]
    assert r.data[1]["data"] is None and "500" in r.data[1]["error"]
    assert r.data[2]["data"]["resting_hr"] == 44


def test_heart_rate_all_days_fail(cli, transport):
    transport.add("GET", "/wellness-service/wellness/dailyHeartRate", json_response({}, 500))
    r = cli("health", "heart-rate", "-2d:today")
    assert r.code == 4 and r.error["type"] == "api"


def test_heart_rate_auth_failure_aborts_range(cli, transport):
    transport.add("GET", "/wellness-service/wellness/dailyHeartRate", json_response({}, 403))
    r = cli("health", "heart-rate", "-2d:today")
    assert r.code == 3
    assert len(transport.data_calls()) == 1


def test_hrv_single_and_range(cli, transport):
    transport.add("GET", "/hrv-service/hrv/2026-10-20", fixture("hrv_day.json"))
    d = cli("health", "hrv", "yesterday").data
    assert d == {"date": "2026-10-20", "last_night_avg": 60, "last_night_5min_high": 90, "weekly_avg": 55,
                 "status": "BALANCED", "baseline_low": 50, "baseline_high": 62, "feedback": "HRV_BALANCED_1", "readings": 2}
    route_range(transport, "/hrv-service/hrv/daily/", hrv_summary_day, wrap=lambda days: {"hrvSummaries": days, "userProfilePk": 1})
    d = cli("health", "hrv", "-6d:today").data
    assert len(d) == 7 and d[-1]["last_night_avg"] == 56


def test_body_battery(cli, transport):
    transport.add("GET", "/wellness-service/wellness/bodyBattery/reports/daily", range_handler(bb_day, style="params"))
    d = cli("health", "body-battery", "-1d:today").data
    assert d[0] == {"date": "2026-10-20", "charged": 50, "drained": 60, "highest": 95, "lowest": 30,
                    "end_of_day_level": "MODERATE", "end_of_day_feedback": "DAY_RECOVERING"}


def test_weight_grams_to_kg_sorted(cli, transport):
    transport.add("GET", "/weight-service/weight/range/2026-09-21/2026-10-21", fixture("weight.json"))
    d = cli("health", "weight").data  # default range -30d:today
    assert [x["date"] for x in d] == ["2026-10-01", "2026-10-15"]
    assert d[1]["weight_kg"] == 80.5 and d[1]["muscle_mass_kg"] == 38.0 and d[1]["body_fat_pct"] == 18.5
    assert d[0]["bmi"] is None
    assert cli("--full", "health", "weight").data == fixture("weight.json")


def test_weekly_steps_and_stress(cli, transport):
    route_range(transport, STEPS, steps_day)
    d = cli("health", "weekly-steps", "--weeks", "2").data
    assert d["range"] == {"start": "2026-10-12", "end": "2026-10-21", "days": 10}
    w1, w2 = d["weeks"]
    assert w1["week_start"] == "2026-10-12" and w1["days"] == 7 and w1["total_steps"] == sum(8000 + i * 100 for i in range(7))
    assert w2["days"] == 3
    route_range(transport, STRESS, stress_day)
    s = cli("health", "weekly-stress", "2026-10-18", "--weeks", "1").data["weeks"][0]
    assert s["days"] == 7 and s["days_with_data"] == 6 and s["high_stress_s"] == 4200
    assert cli("health", "weekly-steps", "--weeks", "60").code == 2

# --- endpoints promoted from `api get` on 2026-11-23 ---------------------------

HYDRATION = "/usersummary-service/stats/hydration/daily/"


def hydration_day(d, i):
    return {
        "calendarDate": d.isoformat(), "valueInML": 1500 + i * 100, "goalInML": 3000,
        "sweatLossInML": 200, "activityIntakeInML": 250, "lastEntryTimestampLocal": f"{d.isoformat()}T12:00:00.0",
    }


def test_hydration_single_range_and_chunking(cli, transport):
    route_range(transport, HYDRATION, hydration_day)
    r = cli("health", "hydration", "2026-10-21")
    assert r.data == [{"date": "2026-10-21", "hydration_ml": 1500, "goal_ml": 3000, "sweat_loss_ml": 200,
                       "activity_intake_ml": 250, "last_entry_local": "2026-10-21T12:00:00.0"}]
    r = cli("health", "hydration", "-40d:today")
    assert len(r.data) == 41
    calls = transport.data_calls()[1:]
    assert [c.path for c in calls] == [
        "/usersummary-service/stats/hydration/daily/2026-09-11/2026-10-11",
        "/usersummary-service/stats/hydration/daily/2026-10-12/2026-10-21",
    ]  # 31-day chunks


def test_hydration_empty(cli, transport):
    route_range(transport, HYDRATION, hydration_day)
    transport.prefixes.clear()
    transport.add_prefix("GET", HYDRATION, [])
    assert cli("health", "hydration", "-6d:today").data == []


MAXMET = "/metrics-service/metrics/maxmet/daily/"


def maxmet_day(d, i):
    cycling = None
    if i % 2 == 1:
        cycling = {"calendarDate": d.isoformat(), "vo2MaxPreciseValue": 48.5, "vo2MaxValue": 48.0,
                   "sport": "CYCLING", "subSport": "GENERIC"}
    return {
        "generic": {"calendarDate": d.isoformat(), "vo2MaxPreciseValue": 50.0 + i * 0.1, "vo2MaxValue": 50.0,
                    "sport": "RUNNING", "subSport": "GENERIC"},
        "cycling": cycling,
    }


def test_vo2max_single_range_and_default(cli, transport):
    route_range(transport, MAXMET, maxmet_day)
    r = cli("health", "vo2max", "2026-10-21")
    assert r.data == [{"date": "2026-10-21", "vo2max": 50.0, "vo2max_precise": 50.0, "sport": "RUNNING",
                       "sub_sport": "GENERIC", "cycling_vo2max": None, "cycling_vo2max_precise": None}]
    r = cli("health", "vo2max", "2026-10-19:2026-10-21")
    assert [x["vo2max_precise"] for x in r.data] == [50.0, 50.1, 50.2]
    assert r.data[1]["cycling_vo2max"] == 48.0 and r.data[1]["cycling_vo2max_precise"] == 48.5
    r = cli("health", "vo2max")  # default range -30d:today
    assert len(r.data) == 31
    full = cli("--full", "health", "vo2max", "2026-10-21").data
    assert full[0]["generic"]["calendarDate"] == "2026-10-21" and full[0]["cycling"] is None


def test_weight_entries(cli, transport):
    transport.add("GET", "/weight-service/weight/all/2026-09-21/2026-10-21", fixture("weight_all.json"))
    d = cli("health", "weight", "--entries").data  # default range -30d:today
    assert [x["date"] for x in d] == ["2026-10-01", "2026-10-15"]  # sorted ascending
    assert d[1]["weight_kg"] == 80.5 and d[1]["muscle_mass_kg"] == 38.0 and d[1]["weight_delta_kg"] == -0.3
    assert d[1]["timestamp_gmt"] == "2026-10-15T05:00:00"
    assert d[0]["bmi"] is None
    assert cli("--full", "health", "weight", "--entries").data == fixture("weight_all.json")


def test_weight_goal(cli, transport):
    transport.add_prefix("GET", "/goal-service/goal/user/effective/weightgoal/", fixture("weight_goal.json"))
    d = cli("health", "weight-goal", "2026-10-21").data
    assert d == {"category": "MANUAL", "type": "WEIGHT_GRAMS", "name": None, "start_date": "2026-01-01",
                 "end_date": None, "tracking_period": "DAILY", "created": "2026-01-01T00:00:00.0",
                 "updated": "2026-01-02T00:00:00.0", "goal_kg": 75.0, "goal_value": 75000.0}
    assert cli("--full", "health", "weight-goal", "2026-10-21").data == fixture("weight_goal.json")


def test_hr_zones(cli, transport):
    transport.add("GET", "/biometric-service/heartRateZones/v2", fixture("hr_zones.json"))
    d = cli("health", "hr-zones").data
    default, cycling = d
    assert default["sport"] == "DEFAULT" and default["method"] == "LACTATE_THRESHOLD"
    assert default["max_hr_used"] == 188 and default["lactate_threshold_hr_used"] == 165
    assert default["zones"] == [
        {"zone": 1, "low": 100, "high": 127}, {"zone": 2, "low": 128, "high": 145},
        {"zone": 3, "low": 146, "high": 151}, {"zone": 4, "low": 152, "high": 164},
        {"zone": 5, "low": 165, "high": 188},
    ]
    assert cycling["zones"][4] == {"zone": 5, "low": 165, "high": 185}
    assert cli("--full", "health", "hr-zones").data == fixture("hr_zones.json")


def test_fitness_age(cli, transport):
    transport.add("GET", "/fitnessage-service/fitnessage/v2/2026-10-21", fixture("fitness_age.json"))
    d = cli("health", "fitness-age", "2026-10-21").data
    assert d["chronological_age"] == 30 and d["fitness_age"] == 25.4 and d["achievable_fitness_age"] == 23.1
    assert d["components"]["bmi"]["value"] == 24.0 and d["components"]["bmi"]["target_value"] == 21.0
    assert d["components"]["vigorousDaysAvg"]["stale"] is True
    assert cli("--full", "health", "fitness-age", "2026-10-21").data == fixture("fitness_age.json")


def test_spo2(cli, transport):
    transport.add("GET", "/wellness-service/wellness/daily/spo2acclimation/2026-10-21", fixture("spo2.json"))
    d = cli("health", "spo2", "2026-10-21").data
    assert d["date"] == "2026-10-21" and d["avg_spo2"] == 97.0 and d["lowest_spo2"] == 94.0
    assert d["hourly_readings"] == 2  # the null hour does not count
    assert d["altitude_acclimation_m"] == 310
    assert d["sleep_start_local"] == "2026-10-20T22:30:00.0"


def test_nutrition(cli, transport):
    transport.add("GET", "/nutrition-service/food/logs/2026-10-21", fixture("food_logs.json"))
    d = cli("health", "nutrition", "2026-10-21").data
    assert d["date"] == "2026-10-21"
    assert d["goals"]["calories"] == 2200 and d["goals"]["calories_adjusted"] == 2400
    breakfast, lunch = d["meals"]
    assert breakfast["meal_name"] == "Breakfast" and breakfast["goals"]["protein_g"] == 41.0
    food = breakfast["foods"][0]
    assert food["name"] == "Synthetic Oats" and food["amount"] == 80.0 and food["servings"] == 2.0
    assert food["calories"] == 300.0 and food["fiber_g"] == 8.0
    assert lunch["foods"] == [] and d["foods"] == []
    assert cli("--full", "health", "nutrition", "2026-10-21").data == fixture("food_logs.json")


def test_settings_projection_drops_display_name(cli, transport):
    transport.add("GET", "/userprofile-service/userprofile/settings", fixture("user_settings.json"))
    d = cli("health", "settings").data
    assert d["measurement_system"] == "metric" and d["time_zone"] == "Europe/Berlin"
    assert d["first_day_of_week"] == "sunday" and d["time_format"] == "time_twenty_four_hr"
    assert d["hydration_containers"] == [{"name": "Bottle", "volume": 750, "unit": "milliliter"}]
    assert "displayName" not in str(d) and "display_name" not in d
    assert cli("--full", "health", "settings").data == fixture("user_settings.json")


def test_wellness_activity_passthrough(cli, transport):
    rows = [{"calendarDate": "2026-10-21", "activityType": "yoga", "durationInSeconds": 1800}]
    transport.add_prefix("GET", "/wellnessactivity-service/activity/summary/range/", rows)
    assert cli("health", "wellness-activity", "-6d:today").data == rows
    transport.prefixes.clear()
    transport.add_prefix("GET", "/wellnessactivity-service/activity/summary/range/", [])
    assert cli("health", "wellness-activity", "-6d:today").data == []


def test_menstrual_null_on_empty_account(cli, transport):
    transport.add("GET", "/periodichealth-service/menstrualcycle/summary/2026-10-21", json_response(None))
    transport.add("GET", "/periodichealth-service/menstrualcycle/dayview/2026-10-21", json_response(None))
    assert cli("health", "menstrual-summary", "2026-10-21").data is None
    r = cli("health", "menstrual-day", "2026-10-21")
    assert r.data is None
    assert transport.data_calls()[-1].params == {"todayDate": "2026-10-21"}
