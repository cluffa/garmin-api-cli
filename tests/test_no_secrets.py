"""Lint: the real Personal API key (or anything shaped like one) must never be in the repo.

Failure messages name files only, never the matching value.
"""

import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache"}
KEY_SHAPE = re.compile(rb"GCDC_[A-Za-z0-9_\-+/=.~:]{20,}")
# Captured at import (collection) time, before the autouse fixture swaps HOME.
REAL_HOME = Path.home()
ALLOWED_FAKES = {b"GCDC_fake_test_key_not_real_0000", b"GCDC_another_fake_key_000"}


def repo_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT, capture_output=True, check=True, text=True,
        ).stdout.split()
        files = [ROOT / f for f in out]
    except (OSError, subprocess.CalledProcessError):
        files = [p for p in ROOT.rglob("*") if p.is_file() and not SKIP_DIRS & set(p.relative_to(ROOT).parts)]
    return [f for f in files if f.is_file()]


def real_key() -> bytes | None:
    from garmin_official_cli.client import parse_key_text

    value = os.environ.get("GARMIN_PERSONAL_API_KEY")
    if not value:
        try:
            value = parse_key_text((REAL_HOME / ".config/garmin/personal-api-key.env").read_text())
        except OSError:
            value = None
    return value.encode() if value else None


def test_no_key_shaped_strings_in_repo():
    offenders = []
    for f in repo_files():
        found = set(KEY_SHAPE.findall(f.read_bytes())) - ALLOWED_FAKES
        if found:
            offenders.append(str(f.relative_to(ROOT)))
    assert not offenders, f"key-shaped strings found in: {offenders}"


def test_real_key_not_in_repo():
    key = real_key()
    if key is None:
        return  # no local key on this machine: nothing to compare against
    offenders = [str(f.relative_to(ROOT)) for f in repo_files() if key in f.read_bytes()]
    assert not offenders, f"the real Personal API key appears in: {offenders}"


def test_gitignore_excludes_key_material():
    rules = (ROOT / ".gitignore").read_text().splitlines()
    for rule in (".env", "*.env", "personal-api-key*", "*bearer-token*.json"):
        assert rule in rules
