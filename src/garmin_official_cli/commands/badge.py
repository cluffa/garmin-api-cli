"""`badge`: badges and challenges. No official API offers them, so every command is a stub."""

from __future__ import annotations

import click

from .common import add_unsupported


@click.group("badge", help="[UNSUPPORTED] Badges and challenges (no official API).")
def badge() -> None:
    pass


add_unsupported(badge, "earned", "Recently earned badges.")
add_unsupported(badge, "in-progress", "Badges currently in progress.")
add_unsupported(badge, "available", "Available badge challenges.")
add_unsupported(badge, "adhoc", "Ad-hoc challenges.")
add_unsupported(badge, "challenges", "All badge challenges.")
