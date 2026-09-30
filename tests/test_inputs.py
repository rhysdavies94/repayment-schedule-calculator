from datetime import date
from decimal import Decimal

import pytest

from repayment_schedule import DayCount, InputError, Structure

from .conftest import make_inputs


def test_coerces_plain_python_values():
    inputs = make_inputs(principal=250000, annual_rate=0.0895, day_count="30E_360")
    assert inputs.principal == Decimal("250000.00")
    assert inputs.annual_rate == Decimal("0.0895")
    assert inputs.day_count is DayCount.THIRTY_E_360
    assert inputs.structure is Structure.AMORTISING
    assert inputs.disbursement_date == date(2026, 10, 15)


@pytest.mark.parametrize(
    "overrides, message",
    [
        (dict(principal="0"), "principal must be greater than 0"),
        (dict(principal="100.001"), "whole pennies"),
        (dict(annual_rate="-0.01"), "annual_rate must be 0 or more"),
        (dict(principal=None), "exactly one of principal or net_advance"),
        (dict(net_advance="1000", retained_months=3), "exactly one of principal or net_advance"),
        (dict(principal=None, net_advance="1000"), "net_advance can only be given"),
        (dict(interest_treatment="ROLLED"), "ROLLED interest is only"),
        (dict(first_payment_date="2026-10-15"), "must be after disbursement_date"),
        (dict(retained_months=61), "cannot exceed term_months"),
        (dict(retained_months=60), "less than term_months on AMORTISING"),
        (dict(balloon_amount="100000"), "must be less than principal"),
        (dict(structure="INTEREST_ONLY", balloon_amount="10"), "only allowed on AMORTISING"),
        (dict(day_count="ACT_ACT"), "day_count must be one of"),
        (dict(term_months=0), "term_months must be at least 1"),
        (dict(term_months=12.0), "term_months must be a whole number"),
        (dict(disbursement_date="15/10/2026"), "must be a date"),
        (dict(capitalised_fees="-1"), "capitalised_fees must be 0 or more"),
    ],
)
def test_bad_inputs_raise_plain_errors(overrides, message):
    with pytest.raises(InputError, match=message):
        make_inputs(**overrides)


def test_all_errors_reported_together():
    with pytest.raises(InputError) as err:
        make_inputs(annual_rate="-1", term_months=0)
    assert "annual_rate" in str(err.value) and "term_months" in str(err.value)


def test_interest_only_allows_full_term_retention():
    make_inputs(structure="INTEREST_ONLY", retained_months=60)
