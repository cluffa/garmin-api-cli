import json
import os

import pytest

from conftest import FAKE_KEY, json_response
from garmin_official_cli import endpoints as ep


def test_status_configured_from_env(cli):
    r = cli("auth", "status")
    assert r.code == 0
    d = r.data
    assert d["configured"] and d["source"] == "env" and d["key_prefix_ok"] is True
    assert FAKE_KEY not in r.out and FAKE_KEY not in r.err


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes; Windows chmod only toggles read-only")
def test_status_from_env_file_reports_mode(cli, monkeypatch, tmp_path):
    monkeypatch.delenv("GARMIN_PERSONAL_API_KEY")
    f = tmp_path / "home/.config/garmin/personal-api-key.env"
    f.parent.mkdir(parents=True)
    f.write_text(f"GARMIN_PERSONAL_API_KEY={FAKE_KEY}\n")
    f.chmod(0o644)
    d = cli("auth", "status").data
    assert d["source"] == "env_file"
    info = d["key_files"][0]
    assert info["exists"] and info["mode"] == "0644" and info["secure"] is False


def test_status_unconfigured_is_auth_error(cli, monkeypatch):
    monkeypatch.delenv("GARMIN_PERSONAL_API_KEY")
    r = cli("auth", "status")
    assert r.code == 3
    err = r.error
    assert err["type"] == "auth"
    assert err["auth_status"]["configured"] is False
    assert r.out == ""


def test_status_verify(cli, transport):
    r = cli("auth", "status", "--verify")
    assert r.code == 0 and r.data["verified"] is True
    assert transport.calls[0].method == "POST"
    assert FAKE_KEY not in r.out
    transport.add("POST", ep.TOKEN.path, json_response({"message": f"invalid key {FAKE_KEY}"}, 401))
    r = cli("auth", "status", "--verify")
    assert r.code == 3
    assert r.error["auth_status"]["verified"] is False
    assert FAKE_KEY not in r.err  # server echo is redacted


def test_expiry_env(cli, monkeypatch):
    monkeypatch.setenv("GARMIN_PERSONAL_API_KEY_EXPIRES", "2099-01-01")
    assert cli("auth", "status").data["key_expires"]["days_remaining"] > 0


def test_refresh_and_logout(cli, tmp_path):
    r = cli("auth", "refresh")
    assert r.code == 0 and r.data["refreshed"]
    cache = tmp_path / "home/.config/garmin-official-cli/bearer-token.json"
    assert cache.exists()
    assert cli("auth", "status").data["token_cache"]["matches_current_key"] is True
    assert cli("auth", "logout").data == {"deleted": True, "path": str(cache)}
    assert not cache.exists()
    assert cli("auth", "logout").data["deleted"] is False


def test_set_key_is_guidance_only(cli, tmp_path):
    r = cli("auth", "set-key")
    assert r.code == 0
    assert "personalApiToken" in json.dumps(r.data)
    assert not (tmp_path / "home/.config/garmin").exists()
