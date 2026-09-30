"""Day counts and year fractions for each convention."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from .inputs import DayCount

_BASIS = {DayCount.ACT_365: 365, DayCount.ACT_360: 360, DayCount.THIRTY_E_360: 360}


def basis(convention: DayCount) -> int:
    """Days in the year under the convention (the denominator)."""
    return _BASIS[convention]


def days_between(start: date, end: date, convention: DayCount) -> int:
    """Days from start to end under the convention (the numerator)."""
    if convention is DayCount.THIRTY_E_360:
        d1, d2 = min(start.day, 30), min(end.day, 30)
        return 360 * (end.year - start.year) + 30 * (end.month - start.month) + (d2 - d1)
    return (end - start).days


def year_fraction(start: date, end: date, convention: DayCount) -> Decimal:
    """Day-count fraction from start to end under the convention."""
    return Decimal(days_between(start, end, convention)) / Decimal(basis(convention))
