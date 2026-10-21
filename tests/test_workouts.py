import json

import pytest

from conftest import json_response
from garmin_official_cli.workouts.schema import SCHEMA
from garmin_official_cli.workouts.spec import (
    SpecError,
    parse_distance,
    parse_pace,
    parse_speed,
    parse_target,
    parse_time,
    validate_spec,
)

GOOD = {
    "workouts": [
        {
            "name": "Wk1 Tue",
            "sport": "running",
            "date": "2026-07-21",
            "notes": "cruise intervals",
            "steps": [
                {"type": "warmup", "duration": {"time": "10min"}, "note": "easy"},
                {
                    "repeat": 5,
                    "steps": [
                        {"type": "interval", "duration": {"distance": "1km"}, "target": {"pace": ["4:00/km", "3:50/km"]}},
                        {"type": "recovery", "duration": {"time": "2min"}},
                    ],
                },
                {"type": "cooldown", "duration": {"time": "10min"}},
            ],
        }
    ]
}


@pytest.mark.parametrize(
    ("value", "secs"),
    [("10min", 600), ("45s", 45), ("1h30min", 5400), ("1h 30min 15s", 5415), ("4:00", 240), ("1:02:03", 3723), (90, 90)],
)
def test_parse_time(value, secs):
    assert parse_time(value) == secs


@pytest.mark.parametrize("value", ["", "10", "10m", "abc", "-5min", "25h", True, None, "10min x"])
def test_parse_time_rejects(value):
    with pytest.raises(SpecError):
        parse_time(value)


def test_parse_distance_pace_speed():
    assert parse_distance("400m") == 400
    assert parse_distance("1km") == 1000
    assert parse_distance("1mi") == 1609.344
    assert parse_distance("5k") == 5000
    with pytest.raises(SpecError):
        parse_distance("1 furlong")
    assert parse_pace("4:00/km") == pytest.approx(4.1667, abs=1e-4)
    assert parse_pace("8:00/mi") == pytest.approx(3.3528, abs=1e-4)
    with pytest.raises(SpecError):
        parse_pace("4:75/km")
    assert parse_speed("36km/h") == 10.0
    assert parse_speed(36) == 10.0
    assert parse_speed("5m/s") == 5.0
    assert parse_speed("10mph") == pytest.approx(4.4704, abs=1e-4)


def test_parse_target_orders_low_high():
    t = parse_target({"pace": ["4:00/km", "3:50/km"]})
    assert t["targetType"] == "PACE" and t["targetValueLow"] < t["targetValueHigh"]
    assert parse_target({"hr": [150, 140]}) == {"targetType": "HEART_RATE", "targetValueLow": 140, "targetValueHigh": 150}
    assert parse_target({"power": "250W"}) == {"targetType": "POWER", "targetValueLow": 250, "targetValueHigh": 250}
    for bad in ({"hr": [10, 20]}, {"cadence": 90}, {"hr": 1, "power": 2}, {"hr": [1, 2, 3]}):
        with pytest.raises(SpecError):
            parse_target(bad)


def test_translation_to_training_api_format():
    report = validate_spec(GOOD)
    assert report["valid"] and report["count"] == 1
    r = report["results"][0]
    w = r["training_api_workout"]
    assert w["workoutName"] == "Wk1 Tue" and w["sport"] == "RUNNING" and w["description"] == "cruise intervals"
    warm, rep, cool = w["steps"]
    assert warm == {
        "type": "WorkoutStep", "stepOrder": 1, "intensity": "WARMUP", "description": "easy",
        "durationType": "TIME", "durationValue": 600.0, "durationValueType": None,
        "targetType": "OPEN", "targetValue": None, "targetValueLow": None, "targetValueHigh": None, "targetValueType": None,
    }
    assert rep["type"] == "WorkoutRepeatStep" and rep["repeatValue"] == 5 and rep["stepOrder"] == 2
    assert rep["repeatType"] == "REPEAT_UNTIL_STEPS_CMPLT"
    interval = rep["steps"][0]
    assert interval["stepOrder"] == 3 and interval["intensity"] == "INTERVAL"
    assert interval["durationType"] == "DISTANCE" and interval["durationValue"] == 1000 and interval["durationValueType"] == "METER"
    assert interval["targetType"] == "PACE"
    assert cool["stepOrder"] == 5 and cool["intensity"] == "COOLDOWN"
    assert r["executable_steps"] == 4
    assert r["estimated_duration_s"] == 600 + 5 * 120 + 600
    assert r["training_api_schedule"] == {"workoutId": None, "date": "2026-07-21"}


def test_open_step_and_single_workout_forms():
    single = {"name": "Open", "sport": "cycling", "steps": [{"type": "active", "target": {"power": [200, 250]}}]}
    for spec in (single, [single]):
        r = validate_spec(spec)["results"][0]
        step = r["training_api_workout"]["steps"][0]
        assert step["durationType"] == "OPEN" and step["targetType"] == "POWER"
        assert r["training_api_workout"]["sport"] == "CYCLING"
        assert r["estimated_duration_s"] is None


def test_validation_errors_have_paths_and_batch_is_per_workout():
    spec = {
        "workouts": [
            GOOD["workouts"][0],
            {
                "name": "",
                "sport": "rowing",
                "date": "07/21",
                "extra": 1,
                "steps": [
                    {"type": "sprint", "duration": {"time": "soon"}},
                    {"repeat": 0, "steps": []},
                    {"type": "interval", "target": {"pace": "4:00/km"}, "duration": {"laps": 2}},
                ],
            },
        ]
    }
    report = validate_spec(spec)
    assert report["valid"] is False
    ok, bad = report["results"]
    assert ok["ok"] is True
    paths = {e["path"] for e in bad["errors"]}
    assert {
        "workouts[1]", "workouts[1].name", "workouts[1].sport", "workouts[1].date",
        "workouts[1].steps[0].type", "workouts[1].steps[0].duration.time",
        "workouts[1].steps[1].repeat", "workouts[1].steps[1].steps", "workouts[1].steps[2].duration",
    } <= paths


def test_pace_only_for_running():
    spec = {"name": "Bike", "sport": "cycling", "steps": [{"type": "interval", "target": {"pace": "3:00/km"}}]}
    errors = validate_spec(spec)["results"][0]["errors"]
    assert errors[0]["path"] == "workouts[0].steps[0].target"


def test_bad_top_level():
    for spec in ({"workouts": []}, "x", 3, {"workouts": [], "x": 1}):
        with pytest.raises(SpecError):
            validate_spec(spec)


def test_schema_shape():
    assert SCHEMA["$schema"].startswith("https://json-schema.org/")
    assert set(SCHEMA["$defs"]) == {"workout", "step", "repeat", "stepOrRepeat"}
    assert SCHEMA["$defs"]["step"]["properties"]["type"]["enum"][0] == "warmup"


# --- CLI ---------------------------------------------------------------------


def test_validate_sources(cli, tmp_path):
    text = json.dumps(GOOD)
    assert cli("workout", "validate", "--json", text).data["valid"] is True
    f = tmp_path / "spec.json"
    f.write_text(text)
    assert cli("workout", "validate", "--file", str(f)).data["valid"] is True
    assert cli("workout", "validate", stdin=text).data["valid"] is True
    for args in (["--json", text, "--file", str(f)], []):
        r = cli("workout", "validate", *args)
        assert r.code == 2 and r.error["type"] == "usage"
    r = cli("workout", "validate", "--json", "{not json")
    assert r.code == 2 and "not valid JSON" in r.error["message"]


def test_validate_invalid_spec_exit_2_with_results(cli):
    r = cli("workout", "validate", "--json", json.dumps({"name": "x", "steps": [{"type": "nope"}]}))
    assert r.code == 2
    assert r.error["results"][0]["errors"][0]["path"] == "workouts[0].steps[0].type"


def test_validate_makes_no_network_calls(cli, transport, monkeypatch):
    monkeypatch.delenv("GARMIN_PERSONAL_API_KEY")
    assert cli("workout", "validate", "--json", json.dumps(GOOD)).code == 0
    assert transport.calls == []


def test_schema_command(cli):
    assert cli("workout", "schema").data == json.loads(json.dumps(SCHEMA))


def test_publish_without_starter_credentials(cli, transport):
    r = cli("workout", "publish", "--json", json.dumps(GOOD))
    assert r.code == 4
    err = r.error
    assert err["type"] == "unsupported" and err["tier_required"] == "starter"
    assert "Starter" in err["reason"] and "pending" in err["reason"]
    assert transport.calls == []


def test_publish_with_token_posts_and_schedules(cli, transport, monkeypatch):
    monkeypatch.setenv("GARMIN_TRAINING_API_TOKEN", "fake-training-token-abc")
    transport.add("POST", "/training-api/workout", {"workoutId": 555})
    transport.add("POST", "/training-api/schedule", lambda call: json_response(777))
    r = cli("workout", "publish", "--json", json.dumps(GOOD))
    assert r.code == 0, r.err
    assert r.data == {"published": 1, "results": [
        {"index": 0, "name": "Wk1 Tue", "workout_id": 555, "schedule_id": 777, "date": "2026-07-21", "ok": True}]}
    post, sched = transport.calls
    assert post.url == "https://apis.garmin.com/training-api/workout"
    assert post.headers["Authorization"] == "Bearer fake-training-token-abc"
    assert post.json_body["workoutName"] == "Wk1 Tue"
    assert sched.json_body == {"workoutId": 555, "date": "2026-07-21"}
    assert "fake-training-token-abc" not in r.out


def test_publish_partial_failure(cli, transport, monkeypatch):
    monkeypatch.setenv("GARMIN_TRAINING_API_TOKEN", "fake-training-token-abc")
    outcomes = iter([json_response({"workoutId": 1}), json_response({"message": "bad"}, 400)])
    transport.add("POST", "/training-api/workout", lambda call: next(outcomes))
    spec = {"workouts": [{"name": "A", "steps": [{"type": "warmup"}]}, {"name": "B", "steps": [{"type": "warmup"}]}]}
    r = cli("workout", "publish", "--json", json.dumps(spec))
    assert r.code == 4
    results = r.error["results"]
    assert [x["ok"] for x in results] == [True, False]
    assert results[1]["error"]["status"] == 400
