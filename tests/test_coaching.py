from datetime import UTC, datetime, timedelta

from fitbuilder import build_messages, message, ts
from test_activity import zipped
from garmin_official_cli.client import HttpResponse
from garmin_official_cli.coaching import Context, analyze, api_steps, cadence, describe, fit_steps, target, text

START = datetime(2026, 10, 20, 11, 0, tzinfo=UTC)
PAUSE_AT, PAUSE_S = 1200, 30  # timer second the watch was stopped at, and for how long

# (step index, intensity, timer seconds, speed m/s, HR at start, HR at end)
PHASES = [
    (0, 2, 600, 2.5, 120, 120),  # warmup 1500 m, auto-lapped at 1000 m
    (1, 0, 60, 4.2, 140, 170),  # rep 1 (in target)
    (2, 4, 60, 2.0, 170, 120),  # recovery
    (1, 0, 60, 4.1, 140, 170),  # rep 2 (in target)
    (2, 4, 60, 2.0, 170, 120),
    (1, 0, 60, 3.8, 140, 170),  # rep 3 (too slow)
    (2, 4, 60, 2.0, 170, 120),
    (4, 3, 600, 2.5, 130, 130),  # cooldown 1500 m, paused once
]


def wall(timer_s: float) -> datetime:
    return START + timedelta(seconds=timer_s + (PAUSE_S if timer_s > PAUSE_AT else 0))


def interval_fit(with_workout: bool = True) -> bytes:
    out, samples, laps = [], [], []
    t = dist = 0.0
    for step, intensity, secs, speed, hr0, hr1 in PHASES:
        cuts = [0, 400, 600] if step == 0 else [0, secs]  # warmup: auto lap at 1000 m
        for a, b in zip(cuts, cuts[1:]):
            lap_samples = []
            for k in range(a, b):
                hr = round(hr0 + (hr1 - hr0) * k / secs)
                samples.append((t + k - a, dist + speed * (k - a), speed, hr))
                lap_samples.append(hr)
            n = b - a
            laps.append(dict(start=t, timer=n, elapsed=n + (PAUSE_S if t < PAUSE_AT < t + n else 0), dist=speed * n,
                             speed=speed, hrs=lap_samples, step=step, intensity=intensity))
            t += n
            dist += speed * n
    if with_workout:
        out.append(message(1, "workout", [(8, "str", "Test Intervals"), (17, "str", "Three fast minutes"),
                                         (4, "enum", 1), (6, "u16", 5)]))
        steps = [
            [(254, "u16", 0), (1, "enum", 1), (2, "u32", 150000), (3, "enum", 2), (7, "enum", 2)],
            [(254, "u16", 1), (1, "enum", 0), (2, "u32", 60000), (3, "enum", 0), (4, "u32", 0),
             (5, "u32", 4000), (6, "u32", 4500), (7, "enum", 0), (8, "str", "Smooth")],
            [(254, "u16", 2), (1, "enum", 0), (2, "u32", 60000), (3, "enum", 2), (7, "enum", 4)],
            [(254, "u16", 3), (1, "enum", 6), (2, "u32", 1), (4, "u32", 3)],
            [(254, "u16", 4), (1, "enum", 1), (2, "u32", 150000), (3, "enum", 2), (7, "enum", 3)],
        ]
        out += [message(2, "workout_step", f) for f in steps]
    out.append(message(3, "event", [(253, "u32", ts(START)), (0, "enum", 0), (1, "enum", 0)]))
    out.append(message(3, "event", [(253, "u32", ts(wall(PAUSE_AT))), (0, "enum", 0), (1, "enum", 4)]))
    out.append(message(3, "event", [(253, "u32", ts(wall(PAUSE_AT)) + PAUSE_S), (0, "enum", 0), (1, "enum", 0)]))
    for tt, d, v, hr in samples:
        out.append(message(4, "record", [(253, "u32", ts(wall(tt))), (5, "u32", round(d * 100)),
                                         (6, "u16", round(v * 1000)), (3, "u8", hr), (4, "u8", 85),
                                         (2, "u16", (250 + 500) * 5)]))
    for i, lap in enumerate(laps):
        fields = [(254, "u16", i), (2, "u32", ts(wall(lap["start"]))), (7, "u32", lap["elapsed"] * 1000),
                  (8, "u32", lap["timer"] * 1000), (9, "u32", round(lap["dist"] * 100)),
                  (13, "u16", round(lap["speed"] * 1000)), (15, "u8", round(sum(lap["hrs"]) / len(lap["hrs"]))),
                  (16, "u8", max(lap["hrs"])), (17, "u8", 85), (23, "enum", lap["intensity"]),
                  (24, "enum", 2 if lap["step"] in (0, 4) else 1), (25, "enum", 1)]
        if with_workout:
            fields.append((71, "u16", lap["step"]))
        out.append(message(5, "lap", fields))
    out.append(message(6, "time_in_zone", [(253, "u32", ts(wall(t))), (0, "u16", 18), (1, "u16", 0),
                                           (2, "u32", [0, 600000, 700000, 120000, 140000, 0, 0]),
                                           (6, "u8", [105, 132, 150, 155, 169, 193]), (10, "enum", 3),
                                           (11, "u8", 193)]))
    out.append(message(7, "session", [(2, "u32", ts(START)), (5, "enum", 1), (7, "u32", round((t + PAUSE_S) * 1000)),
                                      (8, "u32", round(t * 1000)), (9, "u32", round(dist * 100)), (16, "u8", 135),
                                      (17, "u8", 170), (24, "u8", 31), (192, "u8", 75), (193, "u8", 70)]))
    return build_messages(START, out)


def route_fit(transport, fit: bytes, aid: str = "77") -> None:
    transport.add("GET", f"/download-service/files/activity/{aid}", HttpResponse(200, zipped(f"{aid}_ACTIVITY.fit", fit)))


def test_analyze_interval_session(cli, transport):
    route_fit(transport, interval_fit())
    r = cli("activity", "analyze", "77")
    assert r.code == 0, r.err
    d = r.data
    a = d["activity"]
    assert a["sport"] == "running" and a["rpe"] == 7.0 and a["feel"] == "strong" and a["paused_s"] == 30
    assert d["cadence_unit"] == "spm"
    w = d["workout"]
    assert w["name"] == "Test Intervals" and w["description"] == "Three fast minutes"
    assert w["summary"] == "1.5 km warmup, 3 x (1:00 active @ 3:42-4:10/km, 1:00 recovery), 1.5 km cooldown"
    assert w["steps"][3] == {"step": 3, "repeat": {"steps": [1, 2], "times": 3}}
    assert w["steps"][1]["notes"] == "Smooth"

    segs = d["segments"]
    assert [s["role"] for s in segs] == ["warmup", "rep", "recovery", "rep", "recovery", "rep", "recovery", "cooldown"]
    warm, rep1, rec1, rep3, cool = segs[0], segs[1], segs[2], segs[5], segs[7]
    assert warm["laps"] == [1, 2] and warm["distance_km"] == 1.5 and warm["pct_of_planned"] == 100.0
    assert (rep1["rep"], rep1["of"], rep1["in_target"]) == (1, 3, True) and rep1["time_in_target_pct"] > 80
    assert rep1["avg_cadence"] == 170.0 and rep1["planned"] == "1:00 active @ 3:42-4:10/km"
    assert rep3["in_target"] is False and rep3["rep"] == 3
    assert rec1["hr_end"] < 125 and rec1["hr_drop_bpm"] >= 40
    assert cool["elapsed_s"] == 630.0 and cool["timer_s"] == 600.0
    assert "decoupling" not in warm  # a warmup's HR is still settling

    (iv,) = d["intervals"]
    assert iv["planned_reps"] == 3 and iv["completed_reps"] == 3 and iv["in_target_reps"] == 2
    assert iv["pace_by_rep"] == ["3:58/km", "4:04/km", "4:23/km"]
    assert iv["fade_pct"] == -9.5
    assert len(iv["recovery_hr_end_by_rep"]) == 3

    rows = d["splits"]["rows"]
    assert d["splits"]["unit"] == "km" and len(rows) == 5
    assert rows[0]["time_s"] == 400.0 and rows[0]["roles"] == ["warmup"]
    assert "rep" in rows[1]["roles"] and rows[-1]["distance_km"] < 1
    assert d["drift"] is None and any("interval" in n for n in d["notes"])
    assert d["pauses"] == [{"at_s": PAUSE_AT, "duration_s": PAUSE_S}]
    hr = d["zones"]["hr"]
    assert hr["max_hr"] == 193 and hr["zones"][1] == {"zone": 2, "low": 132, "high": 150, "time_s": 700, "pct": 44.9}


def test_analyze_miles_and_no_workout(cli, transport):
    route_fit(transport, interval_fit(with_workout=False))
    d = cli("activity", "analyze", "77", "--miles").data
    assert d["workout"] is None and d["intervals"] == []
    assert len(d["segments"]) == 9 and d["segments"][0]["role"] == "warmup"  # plain laps, one per lap
    assert d["splits"]["unit"] == "mi" and "roles" not in d["splits"]["rows"][0]
    assert d["drift"] is not None and "pct" in d["drift"]
    assert any("no structured workout" in n for n in d["notes"])


def test_analyze_full_returns_messages(cli, transport):
    route_fit(transport, interval_fit())
    full = cli("--full", "activity", "analyze", "77").data
    assert {"workout_mesgs", "workout_step_mesgs", "record_mesgs", "lap_mesgs"} <= set(full["messages"])


def test_splits_report_steps_and_spm(cli, transport):
    route_fit(transport, interval_fit())
    d = cli("activity", "splits", "77").data
    assert d["cadence_unit"] == "spm" and d["count"] == 9
    assert d["laps"][2]["step"] == 1 and d["laps"][2]["avg_cadence"] == 170.0


WORKOUTS = [{
    "index": 0, "workoutName": "Taper Quality", "timeCreated": "2026-10-09T13:57:23.0", "sport": "RUNNING",
    "manufacturer": "GARMIN", "multisportSet": None, "workoutPhrase": None,
    "steps": [
        {"stepIndex": 0, "intensity": "WARMUP", "durationType": "DISTANCE", "durationValue": 3218.0, "targetType": "OPEN",
         "targetValue": 0.0, "targetValueLow": None, "targetValueHigh": None, "notes": None},
        {"stepIndex": 1, "intensity": "ACTIVE", "durationType": "TIME", "durationValue": 300.0, "targetType": "SPEED",
         "targetValue": 0.0, "targetValueLow": 3.284, "targetValueHigh": 3.388, "notes": None},
        {"stepIndex": 2, "intensity": "RECOVERY", "durationType": "TIME", "durationValue": 120.0, "targetType": "HEART_RATE",
         "targetValue": 0.0, "targetValueLow": 220.0, "targetValueHigh": 240.0, "notes": None},
        {"stepIndex": 3, "intensity": None, "durationType": "REPEAT_UNTIL_STEPS_CMPLT", "durationValue": 1.0,
         "targetType": None, "targetValue": 3.0, "targetValueLow": None, "targetValueHigh": None, "notes": None},
        {"stepIndex": 4, "intensity": "COOLDOWN", "durationType": "OPEN", "durationValue": None, "targetType": "OPEN",
         "targetValue": 0.0, "targetValueLow": None, "targetValueHigh": None, "notes": "Easy home"},
    ],
}]


def test_activity_workout(cli, transport):
    transport.add("GET", "/activity-service/activity/77/workouts", WORKOUTS)
    d = cli("activity", "workout", "77", "--miles").data
    (w,) = d["workouts"]
    assert w["name"] == "Taper Quality" and w["sport"] == "running" and w["created_utc"] == "2026-10-09T13:57:23.0"
    assert w["summary"] == ("2 mi warmup, 3 x (5:00 active @ 7:55-8:10/mi, 2:00 recovery @ 120-140 bpm), "
                            "lap button cooldown")
    assert w["steps"][4] == {"step": 4, "intensity": "cooldown", "duration": {"type": "open"}, "notes": "Easy home"}
    assert cli("--full", "activity", "workout", "77").data == WORKOUTS
    transport.add("GET", "/activity-service/activity/78/workouts", [])
    assert cli("activity", "workout", "78").data == {"id": 78, "workouts": []}


def test_target_encodings():
    ctx = Context({"hr": {"max_hr": 190, "zones": [{"zone": 2, "low": 132, "high": 150}]}, "power": {"ftp": 400}})

    def t(kind, low, high, zone=0):
        return target({"target_type": kind, "target_zone": zone, "target_low": low, "target_high": high}, ctx, False)

    assert t("heart_rate", 250, 270) == {"type": "heart_rate", "low": 150, "high": 170, "unit": "bpm"}
    assert t("heart_rate", 70, 80) == {"type": "heart_rate", "pct_max_hr": [70, 80], "low": 133, "high": 152, "unit": "bpm"}
    assert t("heart_rate", 0, 0, zone=2) == {"type": "heart_rate", "zone": 2, "low": 132, "high": 150, "unit": "bpm"}
    assert t("power", 1300, 1350) == {"type": "power", "low": 300, "high": 350, "unit": "W"}
    assert t("power", 90, 100)["low"] == 360
    assert t("speed", 0, 0, zone=3) == {"type": "speed", "zone": 3}
    assert t("power_lap", 1200, 1250)["type"] == "power"
    assert t("open", None, None) is None
    assert t("heart_rate", 70, 80)["unit"] == "bpm"
    no_max = target({"target_type": "heart_rate", "target_zone": 0, "target_low": 70, "target_high": 80}, Context(), False)
    assert no_max == {"type": "heart_rate", "pct_max_hr": [70, 80], "raw_low": 70, "raw_high": 80}


def test_fit_and_api_steps_agree():
    fit = fit_steps([
        {"message_index": 0, "duration_type": "time", "duration_value": 60000, "duration_time": 60.0, "target_type": "speed",
         "target_value": 0, "custom_target_value_low": 3284, "custom_target_value_high": 3388, "intensity": "active"},
        {"message_index": 1, "duration_type": "repeat_until_steps_cmplt", "duration_value": 0, "duration_step": 0,
         "target_value": 5, "repeat_steps": 5},
    ])
    api = api_steps([
        {"stepIndex": 0, "intensity": "ACTIVE", "durationType": "TIME", "durationValue": 60.0, "targetType": "SPEED",
         "targetValue": 0.0, "targetValueLow": 3.284, "targetValueHigh": 3.388},
        {"stepIndex": 1, "durationType": "REPEAT_UNTIL_STEPS_CMPLT", "durationValue": 0.0, "targetValue": 5.0},
    ])
    assert describe(fit, Context(), False) == describe(api, Context(), False) == "5 x (1:00 active @ 4:55-5:05/km)"


def test_text_and_cadence_helpers():
    # FIT strings from a reused device buffer come back split on NUL bytes.
    assert text(["Easy 10", "", "20", "", "des"]) == "Easy 10"
    assert text("Tempo\x00junk") == "Tempo" and text("") is None and text(None) is None
    assert cadence(79, 0.96875, True) == 159.9 and cadence(88, None, False) == 88.0 and cadence(None, 0.5, True) is None


def test_long_run_drift_and_segment_decoupling():
    start = datetime(2026, 10, 20, 7, 0, tzinfo=UTC)
    # 40 min steady at 3 m/s; HR climbs from 140 to 156: positive decoupling.
    records = [{"timestamp": start + timedelta(seconds=i), "distance": 3.0 * i, "speed": 3.0,
                "heart_rate": 140 + 16 * i / 2400} for i in range(2400)]
    lap = {"message_index": 0, "start_time": start, "total_timer_time": 2400.0, "total_elapsed_time": 2400.0,
           "total_distance": 7200.0, "avg_heart_rate": 148, "max_heart_rate": 156, "intensity": "active", "sport": "running"}
    d = analyze({"record_mesgs": records, "lap_mesgs": [lap], "session_mesgs": [{"start_time": start, "sport": "running"}]})
    assert d["drift"]["pct"] > 4 and d["drift"]["second_half"]["avg_hr"] > d["drift"]["first_half"]["avg_hr"]
    assert d["segments"][0]["decoupling"]["pct"] > 4
    assert [r["time_s"] for r in d["splits"]["rows"]][:2] == [333.3, 333.3]
