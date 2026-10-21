"""Root command, global options, and the envelope/exit-code contract."""

from __future__ import annotations

import sys
from collections.abc import Sequence

import click

from . import __version__
from .commands.activity import activity
from .commands.auth import auth
from .commands.badge import badge
from .commands.common import State
from .commands.health import health
from .commands.meta import api, capabilities
from .commands.stats import stats
from .commands.workout import workout
from .errors import EXIT_INTERNAL, EXIT_USAGE, CliError
from .output import FORMATS, emit, failure


@click.group(
    "garmin-official",
    help="Agent-first CLI for Garmin Connect on the official Developer Program APIs (Personal tier, pull). "
    "Every command prints a JSON envelope; see `capabilities`.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option("--format", "fmt", type=click.Choice(FORMATS), default="json", show_default=True, help="Output format.")
@click.option("--full", is_flag=True, help="Return raw Garmin payloads instead of slim projections.")
@click.version_option(__version__, prog_name="garmin-official")
@click.pass_context
def root(ctx: click.Context, fmt: str, full: bool) -> None:
    state = ctx.ensure_object(State)
    state.fmt, state.full = fmt, full


for command in (auth, activity, health, stats, workout, badge, capabilities, api):
    root.add_command(command)


def _sniff_format(argv: Sequence[str]) -> str:
    """Best-effort --format detection so even parse errors honour it."""
    for i, arg in enumerate(argv):
        if arg == "--format" and i + 1 < len(argv) and argv[i + 1] in FORMATS:
            return argv[i + 1]
        if arg.startswith("--format=") and arg.split("=", 1)[1] in FORMATS:
            return arg.split("=", 1)[1]
    return "json"


def run(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    fmt = _sniff_format(args)
    try:
        rv = root.main(args=args, prog_name="garmin-official", standalone_mode=False, obj=State())
        return rv if isinstance(rv, int) else 0
    except CliError as exc:
        emit(failure(exc.to_dict()), fmt, sys.stderr)
        return exc.exit_code
    except click.UsageError as exc:
        error = {"type": "usage", "message": exc.format_message()}
        if exc.ctx is not None:
            error["command"] = exc.ctx.command_path
        emit(failure(error), fmt, sys.stderr)
        return EXIT_USAGE
    except click.ClickException as exc:  # e.g. FileError
        emit(failure({"type": "usage", "message": exc.format_message()}), fmt, sys.stderr)
        return EXIT_USAGE
    except click.Abort:
        emit(failure({"type": "internal", "message": "aborted"}), fmt, sys.stderr)
        return EXIT_INTERNAL
    except Exception as exc:  # noqa: BLE001 - last-resort envelope
        emit(failure({"type": "internal", "message": f"{type(exc).__name__}: {exc}"}), fmt, sys.stderr)
        return EXIT_INTERNAL


def main() -> None:
    sys.exit(run())
