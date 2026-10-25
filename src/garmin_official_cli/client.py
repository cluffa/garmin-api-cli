"""HTTP layer: settings from the environment, API-key discovery, bearer-token exchange.

All network I/O goes through a :class:`Transport`, so tests swap in a fake
transport and never touch the network. The API key and the bearer token are
registered with :func:`output.register_secret` the moment they are loaded, so
they are redacted from anything the CLI prints.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode

from . import endpoints as ep
from .errors import ApiError, AuthError, UnsupportedError
from .output import register_secret

KEY_ENV_VAR = "GARMIN_PERSONAL_API_KEY"
KEY_FILE_ENV_VAR = "GARMIN_PERSONAL_API_KEY_FILE"
KEY_PREFIX = "GCDC_"
TOKEN_REFRESH_WINDOW_SECONDS = 60 * 60
KEY_MANAGEMENT_URL = "https://connect.garmin.com/app/settings/personalApiToken"


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    base_url: str = ep.PERSONAL_DEFAULT_BASE_URL
    key_header: str = "Authorization"
    key_scheme: str = "ApiKey"
    timeout: float = 30.0
    home: Path = field(default_factory=Path.home)
    key_file: Path | None = None  # explicit GARMIN_PERSONAL_API_KEY_FILE
    token_cache: Path | None = None
    training_base_url: str = ep.TRAINING_DEFAULT_BASE_URL
    training_token: str | None = None
    env_key: str | None = None  # value of $GARMIN_PERSONAL_API_KEY, if set

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        home = Path(env.get("HOME") or Path.home())
        timeout_raw = env.get("GARMIN_API_TIMEOUT", "30")
        try:
            timeout = float(timeout_raw)
        except ValueError:
            timeout = 30.0
        key_file = env.get(KEY_FILE_ENV_VAR)
        cache = env.get("GARMIN_BEARER_TOKEN_CACHE")
        return cls(
            base_url=(
                env.get("GARMIN_API_BASE_URL")
                or env.get("GARMIN_PERSONAL_API_BASE_URL")
                or ep.PERSONAL_DEFAULT_BASE_URL
            ).rstrip("/"),
            key_header=env.get("GARMIN_API_KEY_HEADER") or "Authorization",
            key_scheme=env.get("GARMIN_API_KEY_SCHEME", "ApiKey"),
            timeout=timeout if timeout > 0 else 30.0,
            home=home,
            key_file=Path(key_file).expanduser() if key_file else None,
            token_cache=Path(cache).expanduser() if cache else None,
            training_base_url=(env.get("GARMIN_TRAINING_API_BASE_URL") or ep.TRAINING_DEFAULT_BASE_URL).rstrip("/"),
            training_token=env.get("GARMIN_TRAINING_API_TOKEN") or None,
            env_key=env.get(KEY_ENV_VAR),
        )

    @property
    def default_env_file(self) -> Path:
        return self.home / ".config" / "garmin" / "personal-api-key.env"

    @property
    def garmin_default_key_file(self) -> Path:
        """Default key file of Garmin's own client (raw key, no ``NAME=``)."""
        return self.home / ".config" / "garmin" / "connect-personal-api-key"

    @property
    def token_cache_path(self) -> Path:
        return self.token_cache or self.home / ".config" / "garmin-official-cli" / "bearer-token.json"


# ---------------------------------------------------------------------------
# API key discovery
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KeySource:
    kind: str  # "env" | "key_file" | "env_file" | "garmin_key_file"
    path: Path | None
    value: str = field(repr=False)


def parse_key_text(text: str) -> str | None:
    """Extract the key from an env file (``GARMIN_PERSONAL_API_KEY=...``) or a raw key file."""
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("#")]
    assignments = False
    for line in lines:
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        name, sep, value = line.partition("=")
        if not sep:
            continue
        assignments = True
        if name.strip() == KEY_ENV_VAR:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value.strip() or None
    if not assignments and len(lines) == 1:
        return lines[0]
    return None


def file_mode(path: Path) -> int | None:
    if os.name != "posix":  # Windows has no POSIX modes; st_mode reports 0o666 regardless of ACLs
        return None
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return None


def candidate_key_files(settings: Settings) -> list[tuple[str, Path]]:
    if settings.key_file is not None:
        return [("key_file", settings.key_file)]
    return [("env_file", settings.default_env_file), ("garmin_key_file", settings.garmin_default_key_file)]


def resolve_key(settings: Settings) -> KeySource:
    """Find the Personal API key: $GARMIN_PERSONAL_API_KEY, then the key files, in order."""
    if settings.env_key is not None:
        value = settings.env_key.strip()
        if not value:
            raise AuthError(f"${KEY_ENV_VAR} is set but empty")
        register_secret(value)
        return KeySource("env", None, value)
    for kind, path in candidate_key_files(settings):
        if not path.exists():
            if kind == "key_file":
                raise AuthError(f"${KEY_FILE_ENV_VAR} points to a missing file: {path}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise AuthError(f"cannot read key file {path}: {exc.strerror}") from None
        value = parse_key_text(text)
        if not value:
            raise AuthError(f"no {KEY_ENV_VAR}=... entry found in {path}")
        register_secret(value)
        return KeySource(kind, path, value)
    raise AuthError(
        "no Garmin Personal API key configured",
        hint=f"set ${KEY_ENV_VAR} or create {settings.default_env_file} (mode 600); "
        "see `garmin auth set-key`",
    )


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


@dataclass
class HttpResponse:
    status: int
    content: bytes = b""
    headers: Mapping[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.content) if self.content.strip() else None


class TransportError(Exception):
    """Network-level failure (DNS, TLS, timeout...)."""


class Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        timeout: float = 30.0,
    ) -> HttpResponse: ...


class RequestsTransport:
    def __init__(self) -> None:
        import requests

        self._requests = requests
        self._session = requests.Session()

    def request(self, method, url, *, headers, params=None, json_body=None, timeout=30.0) -> HttpResponse:
        try:
            r = self._session.request(
                method, url, headers=dict(headers), params=params, json=json_body, timeout=timeout
            )
        except self._requests.RequestException as exc:
            raise TransportError(f"{type(exc).__name__}: {exc}") from None
        return HttpResponse(r.status_code, r.content, dict(r.headers))


# ---------------------------------------------------------------------------
# Bearer token cache
# ---------------------------------------------------------------------------


def jwt_expiry(token: str) -> float | None:
    try:
        payload = token.split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return float(data["exp"])
    except (IndexError, KeyError, TypeError, ValueError):
        return None


def key_fingerprint(base_url: str, key: str) -> str:
    return hashlib.sha256(f"{base_url}\0{key}".encode()).hexdigest()


@dataclass(frozen=True)
class CachedToken:
    access_token: str = field(repr=False)
    expires_at: float
    fingerprint: str


def read_token_cache(path: Path) -> CachedToken | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return CachedToken(str(data["access_token"]), float(data["expires_at"]), str(data["fingerprint"]))
    except (OSError, KeyError, TypeError, ValueError):
        return None


def write_token_cache(path: Path, token: CachedToken) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(
            {"fingerprint": token.fingerprint, "access_token": token.access_token, "expires_at": token.expires_at},
            fh,
        )
    os.chmod(path, 0o600)


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------


def _error_body(resp: HttpResponse, limit: int = 300) -> str | None:
    body = resp.text.strip()
    return body[:limit] if body else None


def _raise_for_status(resp: HttpResponse, method: str, path: str) -> None:
    if resp.ok:
        return
    body = _error_body(resp)
    where = f"{method} {path}"
    if resp.status in (401, 403):
        raise AuthError(
            f"{where} returned HTTP {resp.status}",
            status=resp.status,
            body=body,
            hint="the key may be expired/revoked; run `garmin auth status --verify`",
        )
    if resp.status == 404:
        raise ApiError(
            f"{where} returned HTTP 404",
            status=404,
            body=body,
            hint="the id/date does not exist, or the Personal API does not expose this path",
        )
    if resp.status == 429:
        raise ApiError(f"{where} was rate limited (HTTP 429)", status=429, body=body)
    raise ApiError(f"{where} returned HTTP {resp.status}", status=resp.status, body=body)


class PersonalApiClient:
    """Read-only client for the Garmin Connect Personal API (pull)."""

    def __init__(
        self,
        settings: Settings,
        transport: Transport | None = None,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self.transport = transport or RequestsTransport()
        self.clock = clock
        self._key: KeySource | None = None
        self._token: str | None = None
        self.request_count = 0

    # -- auth ---------------------------------------------------------------
    @property
    def key(self) -> KeySource:
        if self._key is None:
            self._key = resolve_key(self.settings)
        return self._key

    def _auth_header_value(self) -> str:
        scheme = self.settings.key_scheme.strip()
        return f"{scheme} {self.key.value}" if scheme else self.key.value

    def obtain_token(self, *, force: bool = False) -> CachedToken:
        fp = key_fingerprint(self.settings.base_url, self.key.value)
        cache_path = self.settings.token_cache_path
        if not force:
            cached = read_token_cache(cache_path)
            if (
                cached is not None
                and cached.fingerprint == fp
                and cached.expires_at - self.clock() > TOKEN_REFRESH_WINDOW_SECONDS
            ):
                register_secret(cached.access_token)
                self._token = cached.access_token
                return cached
        url = self.settings.base_url + ep.TOKEN.path
        resp = self._send(
            "POST", url, headers={"Accept": ep.TOKEN.accept, self.settings.key_header: self._auth_header_value()}
        )
        _raise_for_status(resp, "POST", ep.TOKEN.path)
        access = resp.text.strip()
        register_secret(access)
        exp = jwt_expiry(access)
        if exp is None:
            raise ApiError("the token endpoint did not return a JWT with an exp claim")
        token = CachedToken(access, exp, fp)
        write_token_cache(cache_path, token)
        self._token = access
        return token

    def _bearer(self) -> str:
        if self._token is None:
            self.obtain_token()
        assert self._token is not None
        return self._token

    # -- requests -----------------------------------------------------------
    def _send(self, method: str, url: str, **kwargs: Any) -> HttpResponse:
        self.request_count += 1
        try:
            return self.transport.request(method, url, timeout=self.settings.timeout, **kwargs)
        except TransportError as exc:
            raise ApiError(f"network error calling {method} {url.split('?')[0]}", detail=str(exc)) from None

    def get_response(self, path: str, *, params: Mapping[str, Any] | None = None, accept: str = "application/json") -> HttpResponse:
        url = self.settings.base_url + path
        for attempt in (0, 1):
            headers = {"Accept": accept, "Authorization": f"Bearer {self._bearer()}"}
            resp = self._send("GET", url, headers=headers, params=dict(params) if params else None)
            if resp.status == 401 and attempt == 0:
                # The cached token was revoked early; exchange the key once and retry.
                self.obtain_token(force=True)
                continue
            break
        shown = f"{path}?{urlencode(params)}" if params else path
        _raise_for_status(resp, "GET", shown)
        return resp

    def get_json(self, endpoint: ep.Endpoint, *, params: Mapping[str, Any] | None = None, **path_values: Any) -> Any:
        merged = {**endpoint.params, **(params or {})}
        resp = self.get_response(endpoint.format(**path_values), params=merged or None, accept=endpoint.accept)
        try:
            return resp.json()
        except ValueError:
            raise ApiError(f"{endpoint.name}: response was not valid JSON", body=_error_body(resp)) from None

    def get_bytes(self, endpoint: ep.Endpoint, **path_values: Any) -> bytes:
        resp = self.get_response(endpoint.format(**path_values), params=endpoint.params or None, accept=endpoint.accept)
        if not resp.content:
            raise ApiError(f"{endpoint.name}: empty response body")
        return resp.content

    def get_path(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        resp = self.get_response(path, params=params)
        try:
            return resp.json()
        except ValueError:
            return {"content_type": resp.headers.get("Content-Type"), "bytes": len(resp.content)}


STARTER_BLOCKER = (
    "Garmin Training API access requires Starter Business tier credentials. "
    "Alex's Starter application was submitted 2026-10-21 and approval is pending; "
    "no Training API credentials exist yet."
)


class TrainingApiClient:
    """Publish-only client for the Training API (Starter Business tier).

    The Training API is cloud-to-cloud: it authenticates with a user access token
    issued to a registered Business app through Garmin's OAuth flow. Until such a
    token exists (``$GARMIN_TRAINING_API_TOKEN``), every call raises the uniform
    ``unsupported`` error naming the blocker.
    """

    def __init__(self, settings: Settings, transport: Transport | None = None) -> None:
        self.settings = settings
        self._transport = transport

    def require_credentials(self) -> str:
        token = self.settings.training_token
        if not token:
            raise UnsupportedError(
                "workout publishing needs Garmin Training API (Starter tier) credentials",
                reason=STARTER_BLOCKER,
                tier_required="starter",
                hint="once approved, complete the app's OAuth user authorization and set $GARMIN_TRAINING_API_TOKEN",
            )
        register_secret(token)
        return token

    def post_json(self, endpoint: ep.Endpoint, body: Any) -> Any:
        token = self.require_credentials()
        transport = self._transport or RequestsTransport()
        url = self.settings.training_base_url + endpoint.path
        try:
            resp = transport.request(
                "POST",
                url,
                headers={"Accept": "application/json", "Content-Type": "application/json", "Authorization": f"Bearer {token}"},
                json_body=body,
                timeout=self.settings.timeout,
            )
        except TransportError as exc:
            raise ApiError(f"network error calling POST {endpoint.path}", detail=str(exc)) from None
        _raise_for_status(resp, "POST", endpoint.path)
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text[:300]}
