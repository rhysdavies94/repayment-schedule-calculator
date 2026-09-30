"""Validation checks V1 to V7, run on Decimal amounts so comparisons are exact."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Sequence

from .dates import BusinessCalendar
from .inputs import ZERO

if TYPE_CHECKING:
    from .schedule import ScheduleResult, ScheduleRow

HARD = "HARD"
WARNING = "WARNING"

EIR_SANITY_TOLERANCE = Decimal("0.0001")  # 1bp


@dataclass(frozen=True)
class CheckResult:
    code: str
    name: str
    severity: str
    passed: bool
    detail: str


class ScheduleValidationError(Exception):
    """A hard check failed. Carries the full result so the checks can be shown."""

    def __init__(self, result: ScheduleResult):
        self.result = result
        self.failures = [c for c in result.checks if c.severity == HARD and not c.passed]
        lines = [f"{c.code} {c.name}: {c.detail}" for c in self.failures]
        super().__init__("Schedule failed hard validation checks:\n" + "\n".join(lines))


def _check(code: str, name: str, passed: bool, detail: str, severity: str = HARD) -> CheckResult:
    return CheckResult(code, name, severity, passed, detail)


def run_checks(
    *,
    rows: Sequence[ScheduleRow],
    principal: Decimal,
    retained_interest: Decimal,
    regular_final_payment: Decimal,
    v3_tolerance: Decimal,
    disbursement_date: date,
    calendar: BusinessCalendar,
    eir_annual: Decimal,
    eir_expected: Decimal | None,
) -> list[CheckResult]:
    """Run V1 to V7. `eir_expected` is None when V7 does not apply (fees or retention)."""
    final = rows[-1]
    total_payments = sum((r.payment for r in rows), ZERO)
    total_interest = sum((r.interest for r in rows), ZERO)
    total_principal = sum((r.principal_repaid for r in rows), ZERO)

    checks = [
        _check(
            "V1", "Final balance cleared", final.closing_balance == ZERO,
            f"final closing balance {final.closing_balance}",
        ),
        _check(
            "V2", "Principal repaid", total_principal == principal,
            f"sum of principal_repaid {total_principal} vs principal {principal}",
        ),
    ]

    adjustment = final.payment - regular_final_payment
    checks.append(
        _check(
            "V3", "Final-payment adjustment", abs(adjustment) <= v3_tolerance,
            f"final payment {final.payment} vs regular {regular_final_payment}: "
            f"adjustment {adjustment}, tolerance {v3_tolerance}",
        )
    )

    lhs = total_payments + retained_interest
    rhs = principal + total_interest
    checks.append(
        _check(
            "V4", "Cash reconciles", lhs == rhs,
            f"payments {total_payments} + retained {retained_interest} = {lhs}; "
            f"principal {principal} + interest {total_interest} = {rhs}",
        )
    )

    bad_rows = [
        r.period
        for r in rows
        if r.closing_balance != r.opening_balance + r.interest - r.payment - r.interest_retained
        or r.opening_balance < 0
        or r.closing_balance < 0
    ]
    checks.append(
        _check(
            "V5", "Row arithmetic", not bad_rows,
            "all rows reconcile with no negative balances" if not bad_rows
            else f"rows failing arithmetic or negative balance: {bad_rows}",
        )
    )

    dates = [disbursement_date] + [r.payment_date for r in rows]
    not_increasing = [rows[i].period for i in range(len(rows)) if dates[i + 1] <= dates[i]]
    not_business = [r.period for r in rows if not calendar.is_business_day(r.payment_date)]
    date_problems = []
    if not_increasing:
        date_problems.append(f"not strictly increasing at periods {not_increasing}")
    if not_business:
        date_problems.append(f"not a business day at periods {not_business}")
    checks.append(
        _check(
            "V6", "Dates", not date_problems,
            "; ".join(date_problems) or "strictly increasing, all business days",
        )
    )

    if eir_expected is None:
        checks.append(
            _check("V7", "EIR sanity", True,
                   "not applicable (capitalised fees or retention)", WARNING)
        )
    else:
        gap = abs(eir_annual - eir_expected)
        checks.append(
            _check(
                "V7", "EIR sanity", gap <= EIR_SANITY_TOLERANCE,
                f"EIR {eir_annual} vs effective annual {eir_expected}: "
                f"gap {gap * 10000:.2f}bp (limit 1bp)",
                WARNING,
            )
        )
    return checks
