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
