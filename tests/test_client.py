import json
import os
import stat

import pytest

from conftest import BASE, FAKE_KEY, FAKE_TOKEN, json_response, make_jwt
from garmin_official_cli import endpoints as ep
from garmin_official_cli.client import (
    HttpResponse,
    PersonalApiClient,
    Settings,
    TrainingApiClient,
    TransportError,
    jwt_expiry,
    parse_key_text,
    resolve_key,
)
from garmin_official_cli.errors import ApiError, AuthError, UnsupportedError

TOKEN_PATH = ep.TOKEN.path


def settings(tmp_path, **env):
    return Settings.from_env({"HOME": str(tmp_path / "home"), **env})


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("GARMIN_PERSONAL_API_KEY=GCDC_abc\n", "GCDC_abc"),
        ("export GARMIN_PERSONAL_API_KEY='GCDC_abc'\n", "GCDC_abc"),
        ('# comment\nOTHER=1\nGARMIN_PERSONAL_API_KEY="GCDC_abc"\n', "GCDC_abc"),
        ("GCDC_rawkey\n", "GCDC_rawkey"),
        ("OTHER=1\n", None),
        ("GARMIN_PERSONAL_API_KEY=\n", None),
        ("", None),
    ],
)
def test_parse_key_text(text, expected):
    assert parse_key_text(text) == expected


def test_key_resolution_order(tmp_path):
    home = tmp_path / "home"
    env_file = home / ".config/garmin/personal-api-key.env"
    raw_file = home / ".config/garmin/connect-personal-api-key"
    with pytest.raises(AuthError, match="no Garmin Personal API key"):
        resolve_key(settings(tmp_path))
    raw_file.parent.mkdir(parents=True)
    raw_file.write_text("GCDC_from_raw_file\n")
    assert resolve_key(settings(tmp_path)).kind == "garmin_key_file"
    env_file.write_text("GARMIN_PERSONAL_API_KEY=GCDC_from_env_file\n")
    src = resolve_key(settings(tmp_path))
    assert (src.kind, src.value, src.path) == ("env_file", "GCDC_from_env_file", env_file)
    src = resolve_key(settings(tmp_path, GARMIN_PERSONAL_API_KEY="GCDC_from_env"))
    assert (src.kind, src.value) == ("env", "GCDC_from_env")
    custom = tmp_path / "custom.env"
    custom.write_text("GARMIN_PERSONAL_API_KEY=GCDC_custom\n")
    assert resolve_key(settings(tmp_path, GARMIN_PERSONAL_API_KEY_FILE=str(custom))).value == "GCDC_custom"


def test_key_resolution_errors(tmp_path):
    with pytest.raises(AuthError, match="empty"):
        resolve_key(settings(tmp_path, GARMIN_PERSONAL_API_KEY="  "))
    with pytest.raises(AuthError, match="missing file"):
        resolve_key(settings(tmp_path, GARMIN_PERSONAL_API_KEY_FILE=str(tmp_path / "nope")))
    bad = tmp_path / "bad.env"
    bad.write_text("SOMETHING_ELSE=1\n")
    with pytest.raises(AuthError, match="no GARMIN_PERSONAL_API_KEY"):
        resolve_key(settings(tmp_path, GARMIN_PERSONAL_API_KEY_FILE=str(bad)))


def test_settings_env_overrides(tmp_path):
    s = settings(
        tmp_path,
        GARMIN_API_BASE_URL="https://example.test/",
        GARMIN_API_KEY_HEADER="X-Api-Key",
        GARMIN_API_KEY_SCHEME="",
        GARMIN_API_TIMEOUT="bogus",
    )
    assert (s.base_url, s.key_header, s.key_scheme, s.timeout) == ("https://example.test", "X-Api-Key", "", 30.0)
    assert settings(tmp_path, GARMIN_PERSONAL_API_BASE_URL="https://b.test").base_url == "https://b.test"
    d = settings(tmp_path)
    assert (d.base_url, d.key_header, d.key_scheme) == (ep.PERSONAL_DEFAULT_BASE_URL, "Authorization", "ApiKey")


def test_token_exchange_headers_and_cache(tmp_path, transport):
    s = settings(tmp_path, GARMIN_PERSONAL_API_KEY=FAKE_KEY)
    transport.add("GET", "/x", {"ok": 1})
    client = PersonalApiClient(s, transport, clock=lambda: 1_000_000)
    assert client.get_path("/x") == {"ok": 1}
    post = transport.calls[0]
    assert post.method == "POST" and post.url == BASE + TOKEN_PATH
    assert post.headers["Authorization"] == f"ApiKey {FAKE_KEY}"
    get = transport.calls[1]
    assert get.headers["Authorization"] == f"Bearer {FAKE_TOKEN}"
    cache = s.token_cache_path
    assert stat.S_IMODE(cache.stat().st_mode) == 0o600
    assert stat.S_IMODE(cache.parent.stat().st_mode) == 0o700
    assert FAKE_KEY not in cache.read_text()  # only a fingerprint of the key is cached
    # A second client reuses the cached token: no second exchange.
    client2 = PersonalApiClient(s, transport, clock=lambda: 1_000_000)
    client2.get_path("/x")
    assert [c.method for c in transport.calls] == ["POST", "GET", "GET"]


def test_custom_key_header(tmp_path, transport):
    s = settings(tmp_path, GARMIN_PERSONAL_API_KEY=FAKE_KEY, GARMIN_API_KEY_HEADER="X-Key", GARMIN_API_KEY_SCHEME="")
    PersonalApiClient(s, transport).obtain_token()
    assert transport.calls[0].headers["X-Key"] == FAKE_KEY
    assert "Authorization" not in transport.calls[0].headers


def test_cache_invalidated_by_key_change_and_expiry(tmp_path, transport):
    s1 = settings(tmp_path, GARMIN_PERSONAL_API_KEY=FAKE_KEY)
    PersonalApiClient(s1, transport).obtain_token()
    s2 = settings(tmp_path, GARMIN_PERSONAL_API_KEY="GCDC_another_fake_key_000")
    PersonalApiClient(s2, transport).obtain_token()
    assert sum(c.method == "POST" for c in transport.calls) == 2
    # Token within the 1-hour refresh window is replaced.
    soon = make_jwt(2_000)
    transport.add("POST", TOKEN_PATH, HttpResponse(200, soon.encode()))
    PersonalApiClient(s2, transport, clock=lambda: 0).obtain_token(force=True)
    PersonalApiClient(s2, transport, clock=lambda: 0).obtain_token()
    assert sum(c.method == "POST" for c in transport.calls) == 4


def test_401_triggers_one_refresh_then_auth_error(tmp_path, transport):
    s = settings(tmp_path, GARMIN_PERSONAL_API_KEY=FAKE_KEY)
    statuses = iter([401, 200])
    transport.add("GET", "/x", lambda call: json_response({"n": 1}, next(statuses)))
    assert PersonalApiClient(s, transport).get_path("/x") == {"n": 1}
    assert [c.method for c in transport.calls] == ["POST", "GET", "POST", "GET"]
    transport.add("GET", "/y", json_response({}, 401))
    with pytest.raises(AuthError) as exc:
        PersonalApiClient(s, transport).get_path("/y")
    assert exc.value.exit_code == 3


@pytest.mark.parametrize(("status", "exc_type"), [(403, AuthError), (404, ApiError), (429, ApiError), (500, ApiError)])
def test_status_mapping(tmp_path, transport, status, exc_type):
    s = settings(tmp_path, GARMIN_PERSONAL_API_KEY=FAKE_KEY)
    transport.add("GET", "/z", json_response({"error": "x"}, status))
    with pytest.raises(exc_type) as exc:
        PersonalApiClient(s, transport).get_path("/z")
    assert exc.value.details["status"] == status


def test_token_exchange_failures(tmp_path, transport):
    s = settings(tmp_path, GARMIN_PERSONAL_API_KEY=FAKE_KEY)
    transport.add("POST", TOKEN_PATH, json_response({"error": "bad key"}, 401))
    with pytest.raises(AuthError):
        PersonalApiClient(s, transport).obtain_token()
    transport.add("POST", TOKEN_PATH, HttpResponse(200, b"not-a-jwt"))
    with pytest.raises(ApiError, match="JWT"):
        PersonalApiClient(s, transport).obtain_token()


def test_network_error_is_api_error(tmp_path):
    class Boom:
        def request(self, *a, **k):
            raise TransportError("ConnectTimeout: timed out")

    s = settings(tmp_path, GARMIN_PERSONAL_API_KEY=FAKE_KEY)
    with pytest.raises(ApiError, match="network error"):
        PersonalApiClient(s, Boom()).obtain_token()


def test_endpoint_params_and_bytes(tmp_path, transport):
    s = settings(tmp_path, GARMIN_PERSONAL_API_KEY=FAKE_KEY)
    transport.add("GET", "/weight-service/weight/range/2026-01-01/2026-01-31", {"dailyWeightSummaries": []})
    transport.add("GET", "/download-service/files/activity/5", HttpResponse(200, b"PK\x03\x04zip"))
    transport.add("GET", "/download-service/files/activity/6", HttpResponse(200, b""))
    c = PersonalApiClient(s, transport)
    c.get_json(ep.WEIGHT_RANGE, start="2026-01-01", end="2026-01-31")
    assert transport.calls[-1].params == {"includeAll": "true"}
    assert c.get_bytes(ep.ACTIVITY_DOWNLOAD, activity_id=5) == b"PK\x03\x04zip"
    assert "zip" in transport.calls[-1].headers["Accept"]
    with pytest.raises(ApiError, match="empty"):
        c.get_bytes(ep.ACTIVITY_DOWNLOAD, activity_id=6)


def test_jwt_expiry():
    assert jwt_expiry(make_jwt(123)) == 123.0
    assert jwt_expiry("garbage") is None


def test_training_client_requires_starter_credentials(tmp_path, transport):
    with pytest.raises(UnsupportedError) as exc:
        TrainingApiClient(settings(tmp_path), transport).post_json(ep.TRAINING_WORKOUT_CREATE, {})
    err = exc.value.to_dict()
    assert err["type"] == "unsupported" and err["tier_required"] == "starter"
    assert "pending" in err["reason"]
    assert transport.calls == []


def test_endpoints_module_is_single_source():
    names = [e.name for e in ep.ALL]
    assert len(names) == len(set(names))
    for e in ep.ALL:
        assert e.path.startswith("/")
        assert e.method in ("GET", "POST")
