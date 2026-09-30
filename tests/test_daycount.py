from datetime import date
from decimal import Decimal

import pytest

from repayment_schedule.daycount import days_between, year_fraction
from repayment_schedule.inputs import DayCount

ACT365, ACT360, E30 = DayCount.ACT_365, DayCount.ACT_360, DayCount.THIRTY_E_360


@pytest.mark.parametrize(
    "start, end, convention, days, fraction",
    [
        (date(2026, 1, 15), date(2026, 2, 15), ACT365, 31, Decimal(31) / 365),
        (date(2026, 1, 15), date(2027, 1, 15), ACT365, 365, Decimal(1)),
        (date(2028, 1, 15), date(2029, 1, 15), ACT365, 366, Decimal(366) / 365),
        (date(2028, 2, 1), date(2028, 3, 1), ACT360, 29, Decimal(29) / 360),
        (date(2026, 2, 1), date(2026, 3, 1), ACT360, 28, Decimal(28) / 360),
        # 30E/360: day 31 becomes 30 at both ends
        (date(2026, 1, 31), date(2026, 2, 28), E30, 28, Decimal(28) / 360),
        (date(2026, 3, 31), date(2026, 4, 30), E30, 30, Decimal(30) / 360),
        (date(2026, 1, 30), date(2026, 3, 31), E30, 60, Decimal(60) / 360),
        (date(2026, 5, 31), date(2026, 7, 31), E30, 60, Decimal(60) / 360),
        (date(2025, 12, 15), date(2026, 1, 15), E30, 30, Decimal(30) / 360),
        (date(2028, 2, 29), date(2028, 3, 31), E30, 31, Decimal(31) / 360),
        (date(2026, 1, 15), date(2031, 1, 15), E30, 1800, Decimal(5)),
    ],
)
def test_year_fraction(start, end, convention, days, fraction):
    assert days_between(start, end, convention) == days
    assert year_fraction(start, end, convention) == fraction
