from datetime import date, timedelta
from decimal import Decimal

import pytest

from repayment_schedule import InterestTreatment, Structure
from repayment_schedule.schedule import Period, _dry_final_balance
from repayment_schedule.solver import solve_eir, solve_instalment
from repayment_schedule.structures import payment_rule

from .conftest import make_inputs

RULE = payment_rule(Structure.AMORTISING, InterestTreatment.PAID)


def _regular_30_day_periods(n):
    start = date(2026, 1, 15)
    return [Period(i, start, start, start + timedelta(days=30), 30, 360) for i in range(1, n + 1)]


def _solve(rate, n, principal, balloon=0.0):
    inputs = make_inputs(annual_rate=str(rate), day_count="30E_360", term_months=n)
    final_balance = _dry_final_balance(Decimal(principal), inputs, _regular_30_day_periods(n), RULE)
    return solve_instalment(final_balance, float(balloon), principal * (1 + rate * n / 12))


@pytest.mark.parametrize(
    "rate, n, principal",
    [(0.09, 60, 100000), (0.0495, 300, 250000), (0.12, 12, 5000), (0.0001, 36, 20000)],
)
def test_instalment_matches_annuity_formula_on_regular_30e_periods(rate, n, principal):
    r = rate / 12
    annuity = principal * r / (1 - (1 + r) ** -n)
    assert _solve(rate, n, principal) == pytest.approx(annuity, abs=1e-6)


def test_instalment_with_balloon_matches_formula():
    rate, n, principal, balloon = 0.09, 60, 100000, 40000
    r = rate / 12
    expected = (principal - balloon * (1 + r) ** -n) * r / (1 - (1 + r) ** -n)
    assert _solve(rate, n, principal, balloon) == pytest.approx(expected, abs=1e-6)


def test_zero_rate_instalment_is_straight_line():
    assert _solve(0.0, 10, 1000) == pytest.approx(100.0, abs=1e-8)


def test_eir_of_simple_annual_loan():
    # 1000 out, 1100 back after one year: 10%
    assert solve_eir([(0.0, -1000.0), (1.0, 1100.0)]) == pytest.approx(0.10, abs=1e-12)


def test_eir_zero_rate():
    flows = [(0.0, -1200.0)] + [(k / 12, 100.0) for k in range(1, 13)]
    assert solve_eir(flows) == pytest.approx(0.0, abs=1e-12)
