from conftest import daily_summary_day, fixture, range_handler

SEARCH = "/activitylist-service/activities/search/activities"
SUMMARIES = "/usersummary-service/v2/dailysummaries"


def test_summary_single_and_range(cli, transport):
    transport.add("GET", SUMMARIES, range_handler(daily_summary_day, style="params", wrap=lambda d: {"data": d}))
    d = cli("stats", "summary", "yesterday").data
    assert d["date"] == "2026-10-20" and d["steps"] == 10000 and d["resting_hr"] == 45
    assert d["body_battery_max"] == 95 and d["intensity_vigorous_min"] == 30 and d["respiration_avg"] == 13
    assert d["spo2_avg"] is None  # absent fields project to null
    assert transport.data_calls()[0].params == {"startDate": "2026-10-20", "endDate": "2026-10-20"}
    r = cli("stats", "summary", "-40d:today").data
    assert len(r) == 41
    assert len([c for c in transport.data_calls() if c.path == SUMMARIES]) == 3  # 1 + two 31-day chunks


def test_weekly_running(cli, transport):
    transport.add("GET", SEARCH, fixture("activities.json"))
    d = cli("stats", "weekly").data
    call = transport.data_calls()[0]
    assert call.params["activityType"] == "running"
    assert call.params["startDate"] == "2026-09-21" and call.params["endDate"] == "2026-10-21"
    assert d["week_start"] == "2026-10-19"
    assert d["this_week"] == {"km": 10.0, "mi": 6.21, "runs": 1}  # the ride is excluded
    assert d["previous_week"]["runs"] == 1 and d["previous_week"]["km"] == 21.1  # trail run on Sunday 10-18
    assert d["longest_run"]["id"] == 9000000001
    assert d["four_week_avg"]["km"] == round(21097.5 / 4 / 1000, 2)
    assert len(d["weeks"]) == 5
    s = cli("stats", "weekly", "--week-start", "sunday").data
    assert s["week_start"] == "2026-10-18" and s["this_week"]["runs"] == 2


def test_progress(cli, transport):
    transport.add("GET", SEARCH, fixture("activities.json"))
    d = cli("stats", "progress", "-30d", "today").data
    assert d["range"]["days"] == 31
    assert d["total"]["count"] == 3
    assert d["by_type"]["running"] == {"count": 1, "distance_km": 10.0, "duration_h": 0.75, "calories": 720,
                                       "elevation_gain_m": 55.0, "avg_pace": "4:30/km"}
    assert "trail_running" in d["by_type"] and "cycling" in d["by_type"]
    assert cli("stats", "progress", "-1d:today").code == 2
    assert cli("stats", "progress", "today", "-30d").code == 2
