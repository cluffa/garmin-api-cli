"""`auth`: Personal API key status and bearer-token cache. No passwords anywhere."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import click

from ..client import (
    KEY_ENV_VAR,
    KEY_FILE_ENV_VAR,
    KEY_MANAGEMENT_URL,
    KEY_PREFIX,
    candidate_key_files,
    file_mode,
    key_fingerprint,
    read_token_cache,
    resolve_key,
)
from ..errors import AuthError, CliError
from .common import State, add_unsupported, pass_state

KEY_EXPIRY_NOTE = (
    "Garmin Personal API keys are valid for one year from creation and only one key may exist at a time; "
    f"check or rotate it at {KEY_MANAGEMENT_URL}. Set $GARMIN_PERSONAL_API_KEY_EXPIRES (YYYY-MM-DD) to have "
    "auth status report days remaining."
)


@click.group("auth", help="Personal API key status and bearer-token cache.")
def auth() -> None:
    pass


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds")


def _file_info(kind: str, path) -> dict[str, Any]:
    mode = file_mode(path)
    return {
        "kind": kind,
        "path": str(path),
        "exists": path.exists(),
        "mode": f"{mode:04o}" if mode is not None else None,
        "secure": (mode & 0o077 == 0) if mode is not None else None,
    }


def collect_status(state: State) -> dict[str, Any]:
    import os

    settings = state.settings
    status: dict[str, Any] = {
        "configured": False,
        "source": None,
        "env_var_set": settings.env_key is not None,
        "key_files": [_file_info(kind, path) for kind, path in candidate_key_files(settings)],
        "key_prefix_ok": None,
        "base_url": settings.base_url,
        "key_header": settings.key_header,
        "key_scheme": settings.key_scheme,
        "key_expiry_note": KEY_EXPIRY_NOTE,
    }
    expires = os.environ.get("GARMIN_PERSONAL_API_KEY_EXPIRES")
    if expires:
        try:
            days = (datetime.fromisoformat(expires).date() - datetime.now().date()).days
            status["key_expires"] = {"date": expires, "days_remaining": days}
        except ValueError:
            status["key_expires"] = {"date": expires, "error": "not YYYY-MM-DD"}
    try:
        src = resolve_key(settings)
    except AuthError as exc:
        status["error"] = exc.message
        if "hint" in exc.details:
            status["hint"] = exc.details["hint"]
        src = None
    cache_path = settings.token_cache_path
    cache = read_token_cache(cache_path)
    token_info: dict[str, Any] = {"path": str(cache_path), "exists": cache_path.exists()}
    if src is not None:
        status.update(
            configured=True,
            source=src.kind,
            source_path=str(src.path) if src.path else None,
            key_prefix_ok=src.value.startswith(KEY_PREFIX),
        )
    if cache is not None:
        token_info["expires_at"] = _iso(cache.expires_at)
        token_info["expired"] = cache.expires_at <= state.client.clock()
        if src is not None:
            token_info["matches_current_key"] = cache.fingerprint == key_fingerprint(settings.base_url, src.value)
    status["token_cache"] = token_info
    return status


@auth.command("status", help="Is a Personal API key configured? Where from? Token cache state. Never prints the key.")
@click.option("--verify", is_flag=True, help="Also exchange the key for a bearer token (one live request).")
@pass_state
def status_cmd(state: State, verify: bool) -> None:
    status = collect_status(state)
    if not status["configured"]:
        raise AuthError(status.get("error") or "no Personal API key configured", auth_status=status)
    if verify:
        try:
            token = state.client.obtain_token(force=True)
        except CliError as exc:
            status["verified"] = False
            raise type(exc)(exc.message, **{**exc.details, "auth_status": status}) from None
        status["verified"] = True
        status["token_cache"].update(exists=True, expires_at=_iso(token.expires_at), expired=False, matches_current_key=True)
    state.ok(status)


@auth.command("set-key", help="Show how to configure the Personal API key (guidance only; reads/writes nothing).")
@pass_state
def set_key(state: State) -> None:
    path = state.settings.default_env_file
    state.ok(
        {
            "steps": [
                f"Create (or rotate) a Personal API key at {KEY_MANAGEMENT_URL}. Keys start with {KEY_PREFIX!r}; "
                "only one may exist at a time and creating a new one replaces the old.",
                f"mkdir -p {path.parent} && chmod 700 {path.parent}",
                f"Write a single line `{KEY_ENV_VAR}=<your key>` to {path} with an editor (not `echo`, "
                "which leaves the key in shell history).",
                f"chmod 600 {path}",
                "Run `garmin-official auth status --verify`.",
            ],
            "env_file": str(path),
            "env_file_format": f"{KEY_ENV_VAR}=<key>",
            "alternatives": {
                "environment": f"export {KEY_ENV_VAR}=... (takes precedence over files)",
                "custom_file": f"export {KEY_FILE_ENV_VAR}=/path/to/file",
                "garmin_client_file": str(state.settings.garmin_default_key_file) + " (raw key, shared with Garmin's gc-personal)",
            },
            "note": "This CLI never handles passwords. The key is the only credential on the Personal tier.",
        }
    )


@auth.command("refresh", help="Force a new key -> bearer-token exchange and cache it.")
@pass_state
def refresh(state: State) -> None:
    token = state.client.obtain_token(force=True)
    state.ok({"refreshed": True, "expires_at": _iso(token.expires_at), "cache": str(state.settings.token_cache_path)})


@auth.command("logout", help="Delete the cached bearer token. The API key itself is not touched.")
@pass_state
def logout(state: State) -> None:
    path = state.settings.token_cache_path
    existed = path.exists()
    if existed:
        path.unlink()
    state.ok({"deleted": existed, "path": str(path)})


add_unsupported(auth, "login", "Email/password + MFA login. Gone by design: the official API uses a Personal API key.")
