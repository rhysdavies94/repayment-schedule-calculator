from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from repayment_schedule import InputError, generate_schedule, round_penny
from repayment_schedule.inputs import ZERO

from .conftest import make_inputs


def _sum(rows, field):
    return sum((getattr(r, field) for r in rows), ZERO)


def test_deterministic():
    inputs = make_inputs()
    assert generate_schedule(inputs) == generate_schedule(inputs)


def test_amortising_level_instalment_and_final_adjustment():
    result = generate_schedule(make_inputs())
    p = result.summary.level_instalment
    assert all(r.payment == p for r in result.rows[:-1])
    assert result.rows[-1].closing_balance == ZERO
    assert abs(result.summary.final_payment_adjustment) <= result.summary.v3_tolerance
    assert result.passed


def test_first_period_runs_from_disbursement_to_adjusted_date():
    # 15 Nov 2026 is a Sunday: pays Mon 16th, and interest accrues to the 16th
    result = generate_schedule(make_inputs())
    first, second = result.rows[0], result.rows[1]
    assert first.payment_date == date(2026, 11, 16)
    assert first.days == 32
    assert second.nominal_date == date(2026, 12, 15)
    assert second.days == 29


def test_christmas_payment_moves_forward_and_next_returns_to_nominal():
    result = generate_schedule(
        make_inputs(disbursement_date="2026-11-25", first_payment_date="2026-12-25", term_months=12)
    )
    first, second = result.rows[0], result.rows[1]
    assert first.payment_date == date(2026, 12, 29)
    assert second.nominal_date == date(2027, 1, 25)
    assert second.payment_date == date(2027, 1, 25)
    assert first.days == 34 and second.days == 27


def test_month_end_weekend_moves_back():
    result = generate_schedule(
        make_inputs(disbursement_date="2026-09-30", first_payment_date="2026-10-31", term_months=6)
    )
    assert result.rows[0].payment_date == date(2026, 10, 30)
    assert result.rows[1].nominal_date == date(2026, 11, 30)


def test_balloon_left_to_final_payment():
    result = generate_schedule(make_inputs(balloon_amount="40000"))
    p = result.summary.level_instalment
    assert abs(result.rows[-1].payment - (p + Decimal("40000"))) <= result.summary.v3_tolerance
    assert result.rows[-2].closing_balance > Decimal("40000")


def test_interest_only_paid_act_360():
    result = generate_schedule(
        make_inputs(structure="INTEREST_ONLY", day_count="ACT_360", term_months=12)
    )
    for r in result.rows[:-1]:
        assert r.payment == r.interest == r.interest_paid
        assert r.closing_balance == Decimal("100000.00")
    assert result.rows[-1].principal_repaid == Decimal("100000.00")
    assert result.summary.level_instalment is None


def test_rolled_interest_compounds_and_settles_at_maturity():
    result = generate_schedule(
        make_inputs(structure="INTEREST_ONLY", interest_treatment="ROLLED", term_months=12)
    )
    rows = result.rows
    for prev, row in zip(rows, rows[1:]):
        assert row.opening_balance == prev.closing_balance
    for r in rows[:-1]:
        assert r.payment == ZERO and r.interest_rolled == r.interest
    # Interest on period 2 is charged on principal plus period 1's rolled interest
    assert rows[1].opening_balance == Decimal("100000.00") + rows[0].interest
    final = rows[-1]
    assert final.interest_paid == _sum(rows, "interest")
    assert final.principal_repaid == Decimal("100000.00")


def test_retained_interest_on_gross_then_amortising():
    result = generate_schedule(make_inputs(retained_months=6, term_months=36))
    retention, rest = result.rows[:6], result.rows[6:]
    for r in retention:
        assert r.payment == ZERO
        assert r.interest_retained == r.interest
        assert r.opening_balance == r.closing_balance == Decimal("100000.00")
        assert r.interest == round_penny(Decimal("100000") * Decimal("0.09") * r.days / 365)
    assert result.summary.retained_interest == _sum(retention, "interest")
    assert result.summary.net_advance == Decimal("100000.00") - result.summary.retained_interest
    assert all(r.payment == result.summary.level_instalment for r in rest[:-1])


def test_full_term_retention_nothing_due_until_maturity():
    result = generate_schedule(
        make_inputs(structure="INTEREST_ONLY", retained_months=12, term_months=12)
    )
    assert all(r.payment == ZERO for r in result.rows[:-1])
    assert result.rows[-1].payment == Decimal("100000.00")
    assert result.summary.total_interest == result.summary.retained_interest


@pytest.mark.parametrize("net", ["400000.00", "123456.78", "99999.99", "1000.01", "750000.03"])
@pytest.mark.parametrize("fees", ["0", "2500.00"])
def test_gross_up_lands_on_net_advance_to_the_penny(net, fees):
    result = generate_schedule(
        make_inputs(principal=None, net_advance=net, retained_months=6, term_months=24,
                    capitalised_fees=fees, annual_rate="0.1075")
    )
    s = result.summary
    assert s.net_advance == Decimal(net)
    assert s.principal - s.capitalised_fees - s.retained_interest == Decimal(net)


def test_capitalised_fees_raise_eir_without_changing_schedule():
    plain = generate_schedule(make_inputs())
    with_fees = generate_schedule(make_inputs(capitalised_fees="1500"))
    assert plain.rows == with_fees.rows
    assert with_fees.summary.eir_annual > plain.summary.eir_annual
    assert with_fees.summary.net_advance == Decimal("98500.00")


def test_eir_close_to_effective_rate_without_fees():
    result = generate_schedule(make_inputs(day_count="30E_360"))
    ear = (1 + Decimal("0.09") / 12) ** 12 - 1
    assert abs(result.summary.eir_annual - ear) < Decimal("0.0001")
    v7 = next(c for c in result.checks if c.code == "V7")
    assert v7.passed


@pytest.mark.parametrize("day_count", ["ACT_365", "ACT_360", "30E_360"])
def test_each_day_count_passes(day_count):
    assert generate_schedule(make_inputs(day_count=day_count)).passed


def test_zero_rate():
    result = generate_schedule(make_inputs(annual_rate="0", term_months=12))
    assert result.summary.total_interest == ZERO
    assert result.summary.level_instalment == Decimal("8333.33")
    assert result.rows[-1].payment == Decimal("8333.37")
    assert result.summary.eir_annual == ZERO


def test_long_term_v3_tolerance_scales():
    result = generate_schedule(make_inputs(principal="250000", term_months=300))
    s = result.summary
    assert Decimal("1000") < s.rounding_factor_sum < Decimal("1300")
    assert s.v3_tolerance > Decimal("5")
    assert result.passed


def test_long_first_period_capitalises_interest_shortfall():
    # 46-day first period on a 25-year loan: first period interest exceeds the instalment
    result = generate_schedule(
        make_inputs(principal="250000", term_months=300, disbursement_date="2026-10-01")
    )
    first = result.rows[0]
    assert first.interest > first.payment
    assert first.principal_repaid == ZERO
    assert first.interest_rolled == first.interest - first.payment
    assert result.passed


def test_warns_when_dates_go_beyond_the_published_calendar():
    result = generate_schedule(make_inputs(term_months=60))
    assert any("projected" in w for w in result.warnings)
    short = generate_schedule(make_inputs(term_months=12))
    assert not short.warnings


def test_first_payment_adjusted_onto_disbursement_is_rejected():
    # Sat 31 Oct 2026 rolls back to Fri 30 Oct, the disbursement date
    with pytest.raises(InputError, match="not after"):
        generate_schedule(
            make_inputs(disbursement_date="2026-10-30", first_payment_date="2026-10-31")
        )


def test_net_advance_must_be_positive():
    with pytest.raises(InputError, match="net cash advanced must be positive"):
        generate_schedule(make_inputs(capitalised_fees="100000"))


def test_inputs_are_immutable():
    inputs = make_inputs()
    with pytest.raises(Exception):
        inputs.principal = Decimal("1")
    assert replace(inputs, term_months=12).term_months == 12
