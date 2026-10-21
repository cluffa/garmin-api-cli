"""Envelope rendering, output formats, secret redaction and generic projection helpers."""

from __future__ import annotations

import json
import math
import sys
from collections.abc import Iterable, Mapping
from typing import Any, TextIO

FORMATS = ("json", "json-pretty", "toon")

# Secret values registered at runtime (API key, bearer token). Every emitted
# string passes through redact() so a secret echoed back by a server error
# message can never reach stdout/stderr.
_SECRETS: set[str] = set()
REDACTED = "[REDACTED]"


def register_secret(value: str | None) -> None:
    if value and len(value) >= 8:
        _SECRETS.add(value)


def clear_secrets() -> None:
    _SECRETS.clear()


def redact(text: str) -> str:
    for secret in sorted(_SECRETS, key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    return text


def _clean(value: Any) -> Any:
    """Make a payload JSON-safe (NaN/inf -> null, tuples -> lists, bytes refused)."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, Mapping):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def render(payload: Any, fmt: str) -> str:
    payload = _clean(payload)
    if fmt == "json-pretty":
        text = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    elif fmt == "toon":
        import toon

        text = toon.encode(json.loads(json.dumps(payload, default=str)))
    else:
        text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, default=str)
    return redact(text)


def success(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def failure(error: Mapping[str, Any]) -> dict[str, Any]:
    return {"ok": False, "error": dict(error)}


def emit(payload: Any, fmt: str = "json", stream: TextIO | None = None) -> None:
    stream = stream if stream is not None else sys.stdout
    stream.write(render(payload, fmt) + "\n")
    stream.flush()


# ---------------------------------------------------------------------------
# Generic projection helpers
# ---------------------------------------------------------------------------


def dig(obj: Any, path: str, default: Any = None) -> Any:
    """Return ``obj[a][b][c]`` for ``path="a.b.c"``; ``default`` if any hop is missing."""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, Mapping) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


def pick(obj: Mapping[str, Any] | None, mapping: Mapping[str, str]) -> dict[str, Any]:
    """Build ``{out_key: dig(obj, src_path)}``; keys whose value is missing are kept as null."""
    if not isinstance(obj, Mapping):
        return {k: None for k in mapping}
    return {out: dig(obj, src) for out, src in mapping.items()}


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def round_or_none(value: Any, digits: int = 2) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, digits)


def scalars(obj: Mapping[str, Any], *, skip: Iterable[str] = ()) -> dict[str, Any]:
    """Top-level scalar fields of a mapping (drops nested lists/dicts)."""
    skipped = set(skip)
    return {
        k: v
        for k, v in obj.items()
        if k not in skipped and not isinstance(v, (Mapping, list, tuple))
    }
