import json
from datetime import date
from importlib.resources import files

import pytest

from repayment_schedule.dates import (
    easter_sunday,
    load_calendar,
    nominal_dates,
    projected_england_wales_holidays,
)

CAL = load_calendar()


@pytest.mark.parametrize(
    "nominal, adjusted",
    [
        (date(2026, 11, 16), date(2026, 11, 16)),  # Monday, no move
        (date(2026, 11, 14), date(2026, 11, 16)),  # Saturday -> Monday
        (date(2026, 11, 15), date(2026, 11, 16)),  # Sunday -> Monday
        # Christmas 2026 is a Friday; Boxing Day (Sat) is substituted to Mon 28
        (date(2026, 12, 25), date(2026, 12, 29)),
        (date(2026, 12, 26), date(2026, 12, 29)),
        (date(2026, 12, 28), date(2026, 12, 29)),
        # Christmas 2027 Sat, Boxing Day Sun: substitutes Mon 27 and Tue 28
        (date(2027, 12, 25), date(2027, 12, 29)),
        (date(2027, 12, 27), date(2027, 12, 29)),
        # Good Friday 26 Mar 2027 and Easter Monday 29 Mar
        (date(2027, 3, 26), date(2027, 3, 30)),
        # New Year 2028 is a Saturday; substitute Monday 3 Jan
        (date(2028, 1, 1), date(2028, 1, 4)),
        # Modified following: Sat 31 Oct 2026 would roll into November, so back to Fri 30
        (date(2026, 10, 31), date(2026, 10, 30)),
        # Sun 31 Jan 2027 -> Fri 29 Jan
        (date(2027, 1, 31), date(2027, 1, 29)),
        # Summer bank holiday Mon 31 Aug 2026 is the month end -> back to Fri 28
        (date(2026, 8, 31), date(2026, 8, 28)),
    ],
)
def test_modified_following(nominal, adjusted):
    assert CAL.adjust(nominal) == adjusted
    assert CAL.is_business_day(adjusted)


def test_nominal_dates_use_month_end_when_day_missing():
    assert nominal_dates(date(2026, 1, 31), 5) == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 30),
        date(2026, 5, 31),
    ]
    assert nominal_dates(date(2027, 11, 30), 4)[3] == date(2028, 2, 29)


def test_nominal_dates_do_not_drift_after_a_move():
    dates = nominal_dates(date(2026, 12, 25), 3)
    assert dates == [date(2026, 12, 25), date(2027, 1, 25), date(2027, 2, 25)]


def test_easter():
    assert easter_sunday(2026) == date(2026, 4, 5)
    assert easter_sunday(2027) == date(2027, 3, 28)
    assert easter_sunday(2038) == date(2038, 4, 25)


def test_projection_rules_match_feed_in_ordinary_years():
    """Projected holidays equal the GOV.UK feed except in years with one-offs."""
    raw = json.loads(
        files("repayment_schedule").joinpath("data", "uk_bank_holidays.json").read_text("utf-8")
    )
    feed = {date.fromisoformat(e["date"]) for e in raw["england-and-wales"]["events"]}
    one_off_years = {2020, 2022, 2023}  # VE day, Jubilee and State Funeral, Coronation
    for year in range(CAL.first_year, CAL.last_year + 1):
        if year in one_off_years:
            continue
        assert projected_england_wales_holidays(year) == {d for d in feed if d.year == year}, year


def test_dates_beyond_feed_are_projected():
    assert CAL.is_projected(date(CAL.last_year + 1, 1, 1))
    assert not CAL.is_business_day(date(2030, 12, 25))
    assert not CAL.is_business_day(date(2030, 4, 19))  # Good Friday 2030
