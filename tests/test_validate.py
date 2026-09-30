"""The checks catch broken schedules (not just pass good ones)."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from repayment_schedule import ScheduleValidationError, generate_schedule
from repayment_schedule.dates import load_calendar
from repayment_schedule.validate import run_checks

from .conftest import make_inputs

RESULT = generate_schedule(make_inputs(term_months=24))


def _checks(rows=None, **overrides):
    s = RESULT.summary
    kwargs = dict(
        rows=list(rows or RESULT.rows),
        principal=s.principal,
        retained_interest=s.retained_interest,
        regular_final_payment=s.level_instalment,
        v3_tolerance=s.v3_tolerance,
        disbursement_date=RESULT.inputs.disbursement_date,
        calendar=load_calendar(),
        eir_annual=s.eir_annual,
        eir_expected=s.eir_annual,
    )
    kwargs.update(overrides)
    return {c.code: c for c in run_checks(**kwargs)}


def _failed(checks):
    return {code for code, c in checks.items() if not c.passed}


def test_good_schedule_passes_everything():
    assert _failed(_checks()) == set()


def test_final_balance_not_cleared():
    rows = list(RESULT.rows)
    rows[-1] = replace(rows[-1], payment=rows[-1].payment - Decimal("0.01"),
                       principal_repaid=rows[-1].principal_repaid - Decimal("0.01"),
                       closing_balance=Decimal("0.01"))
    assert {"V1", "V2", "V4"} <= _failed(_checks(rows))


def test_row_arithmetic_break():
    rows = list(RESULT.rows)
    rows[5] = replace(rows[5], interest=rows[5].interest + Decimal("0.01"))
    assert "V5" in _failed(_checks(rows))


def test_negative_balance():
    rows = list(RESULT.rows)
    rows[3] = replace(rows[3], closing_balance=Decimal("-1"))
    assert "V5" in _failed(_checks(rows))


def test_final_adjustment_beyond_tolerance():
    checks = _checks(regular_final_payment=RESULT.rows[-1].payment + Decimal("1.00"))
    assert _failed(checks) == {"V3"}


def test_non_business_day_and_non_increasing_dates():
    rows = list(RESULT.rows)
    rows[2] = replace(rows[2], payment_date=date(2027, 1, 16))  # Saturday
    rows[4] = replace(rows[4], payment_date=rows[3].payment_date)
    detail = _checks(rows)["V6"].detail
    assert "not a business day at periods [3]" in detail
    assert "not strictly increasing at periods [5]" in detail


def test_eir_sanity_is_a_warning():
    checks = _checks(eir_expected=RESULT.summary.eir_annual + Decimal("0.001"))
    assert checks["V7"].severity == "WARNING" and not checks["V7"].passed


def test_hard_failure_raises_with_details(monkeypatch):
    import repayment_schedule.schedule as schedule

    monkeypatch.setattr(schedule, "_regular_final_payment", lambda *a: Decimal("1"))
    with pytest.raises(ScheduleValidationError, match="V3 Final-payment adjustment") as err:
        schedule.generate_schedule(make_inputs(term_months=12))
    assert not err.value.result.passed
    result = schedule.generate_schedule(make_inputs(term_months=12), raise_on_failure=False)
    assert [c.code for c in result.checks if not c.passed] == ["V3"]
