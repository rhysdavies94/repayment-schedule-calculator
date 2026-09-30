"""Nominal and business-day adjusted payment dates.

Bank holidays come from the packaged GOV.UK feed (data/uk_bank_holidays.json),
with no network call at run time. For years the feed does not cover, the
standard England and Wales holidays are projected from the statutory rules
(including substitute days), and the dates are reported as projected so the
caller can warn. One-off holidays (coronations, jubilees) cannot be projected.
"""

from __future__ import annotations

import calendar as _cal
import json
from dataclasses import dataclass
from datetime import date, timedelta
from functools import cache
from importlib.resources import files

from .inputs import HolidayCalendar

_FEED_FILE = "uk_bank_holidays.json"
_FEED_DIVISION = {HolidayCalendar.ENGLAND_WALES: "england-and-wales"}


def add_months(start: date, months: int, day: int) -> date:
    """The given day `months` after start's month, capped at that month's last day."""
    year, month0 = divmod(start.month - 1 + months, 12)
    year += start.year
    month = month0 + 1
    return date(year, month, min(day, _cal.monthrange(year, month)[1]))


def nominal_dates(first_payment_date: date, term_months: int) -> list[date]:
    """Contractual due dates, on the first payment's day of month."""
    day = first_payment_date.day
    return [add_months(first_payment_date, k, day) for k in range(term_months)]


def easter_sunday(year: int) -> date:
    """Gregorian Easter Sunday (anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _first_monday(year: int, month: int) -> date:
    d = date(year, month, 1)
    return d + timedelta(days=(7 - d.weekday()) % 7)


def _last_monday(year: int, month: int) -> date:
    d = date(year, month, _cal.monthrange(year, month)[1])
    return d - timedelta(days=d.weekday())


@cache
def projected_england_wales_holidays(year: int) -> frozenset[date]:
    """Standard England and Wales bank holidays for a year, from the rules."""
    new_year = date(year, 1, 1)
    if new_year.weekday() >= 5:
        new_year += timedelta(days=7 - new_year.weekday())
    easter = easter_sunday(year)

    christmas_weekday = date(year, 12, 25).weekday()
    if christmas_weekday == 5:  # Sat: Christmas -> Mon 27, Boxing Day -> Tue 28
        christmas = [date(year, 12, 27), date(year, 12, 28)]
    elif christmas_weekday == 6:  # Sun: Boxing Day Mon 26, Christmas -> Tue 27
        christmas = [date(year, 12, 26), date(year, 12, 27)]
    elif christmas_weekday == 4:  # Fri: Boxing Day (Sat) -> Mon 28
        christmas = [date(year, 12, 25), date(year, 12, 28)]
    else:
        christmas = [date(year, 12, 25), date(year, 12, 26)]

    return frozenset(
        [
            new_year,
            easter - timedelta(days=2),
            easter + timedelta(days=1),
            _first_monday(year, 5),
            _last_monday(year, 5),
            _last_monday(year, 8),
            *christmas,
        ]
    )


@dataclass(frozen=True)
class BusinessCalendar:
    """Weekends plus published bank holidays, projected beyond the feed."""

    name: HolidayCalendar
    published: frozenset[date]
    first_year: int
    last_year: int

    def is_projected(self, d: date) -> bool:
        return not self.first_year <= d.year <= self.last_year

    def holidays_in(self, year: int) -> frozenset[date]:
        if self.first_year <= year <= self.last_year:
            return frozenset(d for d in self.published if d.year == year)
        return projected_england_wales_holidays(year)

    def is_business_day(self, d: date) -> bool:
        if d.weekday() >= 5:
            return False
        if self.is_projected(d):
            return d not in projected_england_wales_holidays(d.year)
        return d not in self.published

    def adjust(self, d: date) -> date:
        """Modified following: next business day, unless that changes month."""
        following = d
        while not self.is_business_day(following):
            following += timedelta(days=1)
        if following.month == d.month:
            return following
        preceding = d
        while not self.is_business_day(preceding):
            preceding -= timedelta(days=1)
        return preceding


@cache
def load_calendar(name: HolidayCalendar = HolidayCalendar.ENGLAND_WALES) -> BusinessCalendar:
    """Load the packaged GOV.UK bank holiday feed for one division."""
    raw = files("repayment_schedule").joinpath("data", _FEED_FILE).read_text(encoding="utf-8")
    events = json.loads(raw)[_FEED_DIVISION[name]]["events"]
    published = frozenset(date.fromisoformat(e["date"]) for e in events)
    years = [d.year for d in published]
    return BusinessCalendar(name, published, min(years), max(years))
