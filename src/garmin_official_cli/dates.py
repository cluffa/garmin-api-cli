"""Unified date specs: ``today``, ``yesterday``, ``-7d``, ``+7d``, ``YYYY-MM-DD`` and ``start:end``."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta

from .errors import UsageError

DEFAULT_MAX_DAYS = 366
_RELATIVE = re.compile(r"^([+-])(\d{1,5})d$")


def today() -> date:
    """Local calendar date. Indirected so tests can monkeypatch it."""
    return date.today()


def parse_date(spec: str, *, ref: date | None = None) -> date:
    ref = ref or today()
    s = spec.strip().lower()
    if s == "today":
        return ref
    if s == "yesterday":
        return ref - timedelta(days=1)
    if s == "tomorrow":
        return ref + timedelta(days=1)
    m = _RELATIVE.match(s)
    if m:
        delta = timedelta(days=int(m.group(2)))
        return ref - delta if m.group(1) == "-" else ref + delta
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise UsageError(
            f"invalid date spec {spec!r}",
            hint="use today, yesterday, -7d, +7d, YYYY-MM-DD, or start:end",
        ) from None


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def is_single(self) -> bool:
        return self.start == self.end

    def __iter__(self) -> Iterator[date]:
        cur = self.start
        while cur <= self.end:
            yield cur
            cur += timedelta(days=1)

    def chunks(self, size: int) -> Iterator[DateRange]:
        """Split into consecutive sub-ranges of at most ``size`` days."""
        if size < 1:
            raise ValueError("chunk size must be >= 1")
        cur = self.start
        while cur <= self.end:
            stop = min(cur + timedelta(days=size - 1), self.end)
            yield DateRange(cur, stop)
            cur = stop + timedelta(days=1)

    def to_dict(self) -> dict[str, str | int]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat(), "days": self.days}


def parse_range(
    spec: str | None,
    *,
    default: str = "today",
    max_days: int = DEFAULT_MAX_DAYS,
    ref: date | None = None,
) -> DateRange:
    spec = default if spec is None or not spec.strip() else spec
    if ":" in spec:
        left, _, right = spec.partition(":")
        if not left.strip() or not right.strip():
            raise UsageError(f"invalid range {spec!r}", hint="use start:end, e.g. -7d:today")
        start, end = parse_date(left, ref=ref), parse_date(right, ref=ref)
    else:
        start = end = parse_date(spec, ref=ref)
    if start > end:
        raise UsageError(
            f"range start {start.isoformat()} is after end {end.isoformat()}",
        )
    rng = DateRange(start, end)
    if max_days < 1:
        raise UsageError("--max-days must be >= 1")
    if rng.days > max_days:
        raise UsageError(
            f"range spans {rng.days} days, above the cap of {max_days}",
            hint="narrow the range or pass --max-days deliberately",
        )
    return rng


def week_start(d: date, first_weekday: int = 0) -> date:
    """Start of the week containing ``d``. ``first_weekday``: 0 = Monday ... 6 = Sunday."""
    return d - timedelta(days=(d.weekday() - first_weekday) % 7)
