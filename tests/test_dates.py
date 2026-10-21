from datetime import date

import pytest

from garmin_official_cli.dates import DateRange, parse_date, parse_range, week_start
from garmin_official_cli.errors import UsageError

REF = date(2026, 10, 21)


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("today", REF),
        ("TODAY", REF),
        ("yesterday", date(2026, 10, 20)),
        ("tomorrow", date(2026, 10, 22)),
        ("-7d", date(2026, 10, 14)),
        ("+7d", date(2026, 10, 28)),
        ("-0d", REF),
        ("2026-02-28", date(2026, 2, 28)),
        (" 2026-01-01 ", date(2026, 1, 1)),
    ],
)
def test_parse_date(spec, expected):
    assert parse_date(spec, ref=REF) == expected


@pytest.mark.parametrize("spec", ["", "7d", "-7", "-7w", "2026-13-01", "2026/01/01", "next week", "--7d"])
def test_parse_date_rejects(spec):
    with pytest.raises(UsageError):
        parse_date(spec, ref=REF)


def test_range_forms():
    assert parse_range("-7d:today", ref=REF) == DateRange(date(2026, 10, 14), REF)
    assert parse_range("2026-07-01:2026-07-31", ref=REF).days == 31
    single = parse_range("yesterday", ref=REF)
    assert single.is_single and single.start == date(2026, 10, 20)
    assert parse_range(None, ref=REF) == DateRange(REF, REF)
    assert parse_range(None, default="-30d:today", ref=REF).days == 31


@pytest.mark.parametrize("spec", ["today:-1d", ":today", "-7d:", "a:b"])
def test_range_rejects(spec):
    with pytest.raises(UsageError):
        parse_range(spec, ref=REF)


def test_range_cap_and_override():
    assert parse_range("-365d:today", ref=REF).days == 366
    with pytest.raises(UsageError, match="cap of 366"):
        parse_range("-366d:today", ref=REF)
    assert parse_range("-400d:today", max_days=401, ref=REF).days == 401
    with pytest.raises(UsageError):
        parse_range("-1d:today", max_days=1, ref=REF)


def test_chunks_cover_range_exactly():
    rng = parse_range("-60d:today", ref=REF)
    chunks = list(rng.chunks(28))
    assert [c.days for c in chunks] == [28, 28, 5]
    assert chunks[0].start == rng.start and chunks[-1].end == rng.end
    assert sum(c.days for c in chunks) == rng.days
    assert list(DateRange(REF, REF).chunks(28)) == [DateRange(REF, REF)]


def test_iter_and_week_start():
    assert len(list(parse_range("-2d:today", ref=REF))) == 3
    assert week_start(REF) == date(2026, 10, 19)  # Monday
    assert week_start(REF, 6) == date(2026, 10, 18)  # Sunday
    assert week_start(date(2026, 10, 19)) == date(2026, 10, 19)
