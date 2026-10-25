import io
import zipfile
from datetime import UTC, datetime

from conftest import fixture, json_response
from fitbuilder import build_fit
from garmin_official_cli.client import HttpResponse

SEARCH = "/activitylist-service/activities/search/activities"


def zipped(name: str, content: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, content)
    return buf.getvalue()


LAPS = [
    dict(start=datetime(2026, 10, 20, 11, 0, tzinfo=UTC), elapsed_s=300, timer_s=298, distance_m=1000, speed_mps=3.3557,
         avg_hr=150, max_hr=160, intensity=2, trigger=2),
    dict(start=datetime(2026, 10, 20, 11, 5, tzinfo=UTC), elapsed_s=480, timer_s=480, distance_m=1609.344, speed_mps=3.3528,
         avg_hr=165, max_hr=172, intensity=0, trigger=0),
]


def test_list_slim_projection(cli, transport):
    transport.add("GET", SEARCH, fixture("activities.json"))
    r = cli("activity", "list", "--limit", "3")
    assert r.code == 0
    first = r.data[0]
    assert first == {
        "id": 9000000003, "name": "Tempo Run", "type": "running", "start_local": "2026-10-20 07:00:00",
        "duration_s": 2700.0, "moving_s": 2690.0, "distance_km": 10.0, "pace": "4:30/km", "avg_hr": 158.0,
        "max_hr": 175.0, "calories": 720.0, "elevation_gain_m": 55.0, "training_load": 140.2,
        "aerobic_te": 3.4, "te_label": "tempo", "avg_cadence_spm": 172.0, "hr_zones_s": [120.0, 600.0, 900.0, 1000.0, 80.0],
    }
    assert transport.data_calls()[0].params == {"start": 0, "limit": 3}


def test_list_miles_filters_and_full(cli, transport):
    transport.add("GET", SEARCH, fixture("activities.json"))
    r = cli("activity", "list", "--miles", "--type", "running", "--range", "-7d:today")
    assert r.data[0]["distance_mi"] == 6.21 and r.data[0]["pace"] == "7:15/mi"
    assert transport.data_calls()[0].params == {
        "start": 0, "limit": 20, "activityType": "running", "startDate": "2026-10-14", "endDate": "2026-10-21"}
    assert cli("--full", "activity", "list").data == fixture("activities.json")


def test_list_paginates(cli, transport):
    page = [{"activityId": i} for i in range(100)]
    pages = iter([page, page[:5]])
    transport.add("GET", SEARCH, lambda call: next(pages))
    r = cli("activity", "list", "--limit", "250")
    assert len(r.data) == 105
    assert [c.params["start"] for c in transport.data_calls()] == [0, 100]


def test_get_projection_and_samples(cli, transport):
    transport.add("GET", "/activity-service/activity/9000000003", fixture("activity.json"))
    transport.add("GET", "/activity-service/activity/9000000003/details", fixture("activity_details.json"))
    d = cli("activity", "get", "9000000003").data
    assert d["type"] == "running" and d["distance_km"] == 10.0 and d["pace"] == "4:30/km"
    assert d["file_format"] == "fit" and d["lap_count"] == 10 and d["location"] == "Testville"
    assert (d["rpe"], d["feel"], d["compliance_score"], d["te_label"]) == (6.0, "strong", 88, "tempo")
    assert d["gap_pace"] == "4:27/km" and d["avg_cadence_spm"] == 172.0 and d["stride_length_m"] == 1.29
    assert d["split_summaries"] == [{"type": "interval_active", "count": 3, "distance_m": 3000.0, "duration_s": 780.0}]
    s = cli("activity", "get", "9000000003", "--samples").data["samples"]
    assert s["metrics"] == ["directTimestamp", "directHeartRate", "directSpeed"]
    assert s["count"] == 3 and s["samples"][1]["directHeartRate"] == 125.0
    full = cli("--full", "activity", "get", "9000000003", "--samples").data
    assert set(full) == {"activity", "details"}


def test_get_404(cli):
    r = cli("activity", "get", "1")
    assert r.code == 4 and r.error["status"] == 404


def test_download_fit(cli, transport, tmp_path):
    fit = build_fit(LAPS)
    transport.add("GET", "/download-service/files/activity/77", HttpResponse(200, zipped("77_ACTIVITY.fit", fit)))
    r = cli("activity", "download", "77")
    assert r.code == 0
    assert r.data == {"id": 77, "path": "77.fit", "format": "fit", "bytes": len(fit), "original_name": "77_ACTIVITY.fit"}
    assert (tmp_path / "77.fit").read_bytes() == fit
    # Refuses to overwrite without --force.
    r = cli("activity", "download", "77")
    assert r.code == 2
    assert cli("activity", "download", "77", "--force").code == 0
    r = cli("activity", "download", "77", "--zip", "--out", "raw.zip")
    assert r.data["format"] == "zip" and zipfile.is_zipfile(tmp_path / "raw.zip")


def test_download_tcx_gpx_unsupported(cli, transport):
    for fmt in ("tcx", "gpx"):
        r = cli("activity", "download", "77", "--format-file", fmt)
        assert r.code == 4
        err = r.error
        assert err["type"] == "unsupported" and err["tier_required"] == "none" and "FIT" in err["reason"]
    assert transport.calls == []


def test_splits_from_fit_laps(cli, transport):
    transport.add("GET", "/download-service/files/activity/77", HttpResponse(200, zipped("77_ACTIVITY.fit", build_fit(LAPS))))
    d = cli("activity", "splits", "77").data
    assert d["source"] == "fit_laps" and d["count"] == 2
    lap1, lap2 = d["laps"]
    assert lap1["distance_km"] == 1.0 and lap1["pace"] == "4:58/km" and lap1["avg_hr"] == 150
    assert lap1["intensity"] == "warmup" and lap1["split_type"] == "distance"
    assert lap2["split_type"] == "manual" and lap2["timer_s"] == 480.0
    m = cli("activity", "splits", "77", "--miles").data["laps"][1]
    assert m["distance_mi"] == 1.0 and m["pace"] == "8:00/mi"
    full = cli("--full", "activity", "splits", "77").data
    assert len(full["lap_mesgs"]) == 2


def test_splits_non_fit_original(cli, transport):
    transport.add("GET", "/download-service/files/activity/78", HttpResponse(200, zipped("78.gpx", b"<gpx/>")))
    r = cli("activity", "splits", "78")
    assert r.code == 4 and "not FIT" in r.error["message"]
