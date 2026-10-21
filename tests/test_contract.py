"""Envelope + exit-code contract, unsupported stubs, capabilities and docs consistency."""

import json
from pathlib import Path

import pytest

from conftest import json_response
from garmin_official_cli.cli import root
from garmin_official_cli.commands.meta import walk
from garmin_official_cli.models import SUPPORT, UNSUPPORTED

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = [path for path, _ in walk(root)]
UNSUPPORTED_COMMANDS = [c for c, s in SUPPORT.items() if s.status == UNSUPPORTED and c != "workout publish"]

# Every command of the old CLI (from its README) must exist here, supported or stubbed.
OLD_CLI_COMMANDS = [
    "auth login", "auth status", "auth logout",
    "workout validate", "workout create", "workout list", "workout get", "workout delete",
    "workout schedule", "workout unschedule", "workout scheduled", "workout schema",
    "activity list", "activity get", "activity download", "activity splits",
    "health steps", "health heart-rate", "health sleep", "health body-battery", "health hrv",
    "health stress", "health weight", "health weekly-steps", "health weekly-stress",
    "stats summary", "stats training-status", "stats readiness", "stats records", "stats progress", "stats weekly",
    "badge earned", "badge in-progress", "badge available", "badge adhoc", "badge challenges",
    "capabilities",
]


def test_registry_matches_command_tree():
    assert sorted(COMMANDS) == sorted(SUPPORT)


@pytest.mark.parametrize("command", OLD_CLI_COMMANDS)
def test_old_commands_all_exist(command):
    assert command in COMMANDS


@pytest.mark.parametrize("command", UNSUPPORTED_COMMANDS)
def test_unsupported_envelope(cli, transport, command):
    # Old-style arguments/options must not turn into usage errors.
    r = cli(*command.split(), "123", "2026-10-21", "--limit", "5")
    assert r.code == 4
    assert r.out == ""
    env = json.loads(r.err)
    assert env["ok"] is False
    err = env["error"]
    assert set(err) == {"type", "message", "reason", "tier_required"}
    assert err["type"] == "unsupported"
    assert err["reason"] and err["tier_required"] in ("none", "starter")
    assert transport.calls == []  # no fake data, no network


def test_unsupported_respects_format(cli):
    r = cli("--format", "json-pretty", "badge", "earned")
    assert r.code == 4 and r.err.startswith("{\n")


def test_success_goes_to_stdout_only(cli):
    r = cli("workout", "schema")
    assert r.code == 0 and r.err == ""
    assert r.json["ok"] is True


def test_usage_errors_exit_2(cli):
    for args in (["health", "steps", "notadate"], ["activity", "get", "abc"], ["nosuchcommand"],
                 ["activity", "list", "--limit", "0"], ["health", "steps", "-400d:today"]):
        r = cli(*args)
        assert r.code == 2, args
        assert r.error["type"] == "usage"


def test_max_days_override(cli, transport):
    transport.add("GET", "/hrv-service/hrv/daily/2025-09-14/2026-09-14", {"hrvSummaries": []})
    transport.add("GET", "/hrv-service/hrv/daily/2026-09-15/2026-10-21", {"hrvSummaries": []})
    assert cli("health", "hrv", "-402d:today").code == 2
    r = cli("health", "hrv", "-402d:today", "--max-days", "403")
    assert r.code == 0, r.err
    assert len(transport.data_calls()) == 2


def test_auth_error_exit_3(cli, monkeypatch):
    monkeypatch.delenv("GARMIN_PERSONAL_API_KEY")
    r = cli("health", "steps")
    assert r.code == 3 and r.error["type"] == "auth"


def test_api_error_exit_4(cli, transport):
    transport.add("GET", "/activity-service/activity/42", json_response({"error": "boom"}, 500))
    r = cli("activity", "get", "42")
    assert r.code == 4
    assert r.error["type"] == "api" and r.error["status"] == 500


def test_internal_error_exit_1(cli, monkeypatch):
    from garmin_official_cli.commands import common

    monkeypatch.setattr(common.State, "ok", lambda self, data: 1 / 0)
    r = cli("workout", "schema")
    assert r.code == 1 and r.error["type"] == "internal"


def test_help_and_version(cli):
    assert cli("--help").code == 0
    assert cli("health", "--help").code == 0
    assert cli("--version").code == 0


def test_capabilities(cli):
    r = cli("capabilities")
    assert r.code == 0
    d = r.data
    rows = {row["command"]: row for row in d["commands"]}
    assert sorted(rows) == sorted(COMMANDS)
    for row in rows.values():
        assert row["status"] in ("supported", "partial", "unsupported")
        assert row["reason"] and row["tier"]
    assert rows["workout publish"]["status"] == "unsupported"
    assert rows["activity download"]["status"] == "partial"
    assert rows["health body-battery"]["status"] == "supported"
    assert set(d["unsupported"]) == set(UNSUPPORTED_COMMANDS) | {"workout publish"}
    assert d["workout_schema"]["title"]
    assert "GARMIN_API_BASE_URL" in d["env"] and "GARMIN_API_KEY_HEADER" in d["env"]


def test_capabilities_publish_becomes_partial_with_token(cli, monkeypatch):
    monkeypatch.setenv("GARMIN_TRAINING_API_TOKEN", "fake-training-token-123")
    rows = {row["command"]: row for row in cli("capabilities").data["commands"]}
    assert rows["workout publish"]["status"] == "partial"


@pytest.mark.parametrize("doc", ["GAP_ANALYSIS.md", "README.md"])
def test_docs_cover_every_command(doc):
    text = (ROOT / doc).read_text()
    missing = [c for c in COMMANDS if f"`{c}" not in text]
    assert not missing, f"{doc} does not mention: {missing}"


def test_gap_analysis_lists_every_unsupported_command_with_status():
    lines = (ROOT / "GAP_ANALYSIS.md").read_text().splitlines()
    for command in set(UNSUPPORTED_COMMANDS) | {"workout publish"}:
        rows = [ln for ln in lines if ln.startswith("|") and f"`{command}" in ln]
        assert rows and any("unsupported" in ln.lower() for ln in rows), command
