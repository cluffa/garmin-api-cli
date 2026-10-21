"""Offline test harness: fake transport, fixed clock, isolated HOME, synthetic payloads."""

from __future__ import annotations

import base64
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from garmin_official_cli import dates, output
from garmin_official_cli.cli import run
from garmin_official_cli.client import HttpResponse
from garmin_official_cli.commands import common

sys.path.insert(0, str(Path(__file__).parent))

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 21)
FAKE_KEY = "GCDC_fake_test_key_not_real_0000"
BASE = "https://personal.connectapi.garmin.com"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def make_jwt(exp: float) -> str:
    def b64(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'none'})}.{b64({'exp': exp, 'sub': 'test'})}.sig"


FAKE_TOKEN = make_jwt(4102444800)  # 2100-01-01


def json_response(payload: Any, status: int = 200) -> HttpResponse:
    return HttpResponse(status, json.dumps(payload).encode(), {"Content-Type": "application/json"})


@dataclass
class Call:
    method: str
    url: str
    path: str
    headers: dict[str, str]
    params: dict[str, Any] | None
    json_body: Any


Handler = Callable[[Call], HttpResponse] | HttpResponse | Any


@dataclass
class FakeTransport:
    """Routes ``(METHOD, path)`` to a response, a payload, or a callable(call)."""

    routes: dict[tuple[str, str], Handler] = field(default_factory=dict)
    prefixes: list[tuple[str, str, Handler]] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)

    def add(self, method: str, path: str, handler: Handler) -> FakeTransport:
        self.routes[(method, path)] = handler
        return self

    def add_prefix(self, method: str, prefix: str, handler: Handler) -> FakeTransport:
        self.prefixes.append((method, prefix, handler))
        return self

    def request(self, method, url, *, headers, params=None, json_body=None, timeout=30.0) -> HttpResponse:
        path = urlsplit(url).path
        call = Call(method, url, path, dict(headers), dict(params) if params else None, json_body)
        self.calls.append(call)
        handler = self.routes.get((method, path))
        if handler is None:
            handler = next((h for m, p, h in self.prefixes if m == method and path.startswith(p)), None)
        if handler is None:
            return json_response({"error": "NOT_FOUND", "status": 404}, 404)
        if callable(handler):
            handler = handler(call)
        if isinstance(handler, HttpResponse):
            return handler
        return json_response(handler)

    def data_calls(self) -> list[Call]:
        return [c for c in self.calls if "personalapitoken-service" not in c.path]


@dataclass
class Result:
    code: int
    out: str
    err: str

    @property
    def json(self) -> Any:
        return json.loads(self.out)

    @property
    def error(self) -> dict[str, Any]:
        env = json.loads(self.err)
        assert env["ok"] is False
        return env["error"]

    @property
    def data(self) -> Any:
        env = self.json
        assert env["ok"] is True, self.err
        return env["data"]


@pytest.fixture
def transport() -> FakeTransport:
    t = FakeTransport()
    t.add("POST", "/personalapitoken-service/personal-api/personal-api-key/token", HttpResponse(200, FAKE_TOKEN.encode()))
    return t


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Every test: fresh HOME, no real GARMIN_* env, fixed 'today', no network."""
    import os

    for name in list(os.environ):
        if name.startswith("GARMIN_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.setattr(dates, "today", lambda: TODAY)
    monkeypatch.chdir(tmp_path)

    def no_network(*a, **k):
        raise AssertionError("tests must not create a real HTTP transport")

    monkeypatch.setattr("garmin_official_cli.client.RequestsTransport.__init__", no_network)
    output.clear_secrets()
    yield
    output.clear_secrets()
    common.TRANSPORT_FACTORY = None


@pytest.fixture
def cli(monkeypatch, capsys, transport):
    """Invoke the CLI with a fake key and the fake transport."""
    monkeypatch.setenv("GARMIN_PERSONAL_API_KEY", FAKE_KEY)
    common.TRANSPORT_FACTORY = lambda: transport

    def invoke(*args: str, stdin: str | None = None) -> Result:
        if stdin is not None:
            import io

            monkeypatch.setattr(sys, "stdin", _FakeStdin(stdin))
        else:
            monkeypatch.setattr(sys, "stdin", _FakeStdin(None))
        code = run(list(args))
        captured = capsys.readouterr()
        return Result(code, captured.out, captured.err)

    return invoke


class _FakeStdin:
    def __init__(self, text: str | None) -> None:
        self._text = text

    def isatty(self) -> bool:
        return self._text is None

    def read(self) -> str:
        return self._text or ""


# --- synthetic day-series generators (official Personal API shapes) --------------


def day_list(start: date, end: date, make: Callable[[date, int], dict]) -> list[dict]:
    out, cur, i = [], start, 0
    while cur <= end:
        out.append(make(cur, i))
        cur += timedelta(days=1)
        i += 1
    return out


def steps_day(d: date, i: int) -> dict:
    return {"calendarDate": d.isoformat(), "totalSteps": 8000 + i * 100, "totalDistance": 6000 + i * 50, "stepGoal": 8000}


def stress_day(d: date, i: int) -> dict:
    level = -1 if i == 2 else 20 + i
    return {
        "calendarDate": d.isoformat(),
        "values": {"overallStressLevel": level, "restStressDuration": 30000, "lowStressDuration": 10000,
                   "mediumStressDuration": 3000, "highStressDuration": 600},
    }


def sleep_summary_day(d: date, i: int) -> dict:
    return {**fixture("sleep.json"), "calendarDate": d.isoformat(), "sleepTimeSeconds": 25000 + i}


def bb_day(d: date, i: int) -> dict:
    return {
        "date": d.isoformat(), "charged": 50 + i, "drained": 60,
        "bodyBatteryValuesArray": [[1, 30], [2, 95], [3, None], [4, 40]],
        "endOfDayBodyBatteryDynamicFeedbackEvent": {"bodyBatteryLevel": "MODERATE", "feedbackShortType": "DAY_RECOVERING"},
    }


def hrv_summary_day(d: date, i: int) -> dict:
    return {**fixture("hrv_day.json")["hrvSummary"], "calendarDate": d.isoformat(), "lastNightAvg": 50 + i}


def daily_summary_day(d: date, i: int) -> dict:
    return {
        "calendarDate": d.isoformat(), "source": "garmin",
        "movement": {"steps": {"goal": 8000, "value": 10000 + i, "distanceInMeters": 8000.0}, "floorsAscended": {"value": 7}},
        "calories": {"burnedResting": 1800, "burnedActive": 700, "burnedTotal": 2500},
        "heartRate": {"minValue": 40, "maxValue": 160, "restingValue": 45},
        "intensityMinutes": {"goal": 150, "moderate": 20, "vigorous": 30},
        "stress": {"avgLevel": 25, "maxLevel": 90, "qualifier": "calm"},
        "bodyBattery": {"minValue": 20, "maxValue": 95, "chargedValue": 60, "drainedValue": 70, "latestValue": 30},
        "respiration": {"avgValue": 13}, "pulseOx": {"avgAltitudeInMeters": 200.0}, "hydration": {"consumedInMl": 1500},
    }


def range_handler(make: Callable[[date, int], dict], *, style: str, wrap: Callable[[list], Any] = lambda x: x):
    """Handler that answers a range endpoint from its path ({start}/{end}) or startDate/endDate params."""

    def handler(call: Call):
        if style == "path":
            s, e = call.path.rstrip("/").split("/")[-2:]
        else:
            s, e = call.params["startDate"], call.params["endDate"]
        return wrap(day_list(date.fromisoformat(s), date.fromisoformat(e), make))

    return handler
