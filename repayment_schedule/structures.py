"""Payment rule per structure, plus the retained and rolled interest handling.

The period loop asks `period_payment` what the customer pays each period. A new
loan type is a new small rule function added to `_RULES`; the loop is unchanged.

Rules work on either Decimal (the real schedule) or float (solver dry runs),
so they only use arithmetic that preserves the input type.
"""

from __future__ import annotations

from typing import Callable, TypeVar

from .inputs import InterestTreatment, Structure

Money = TypeVar("Money")  # Decimal in the schedule, float in solver dry runs

# (opening balance, interest for the period, level instalment) -> payment
PaymentRule = Callable[[Money, Money, Money], Money]


def _amortising(opening, interest, instalment):
    return instalment


def _interest_only_paid(opening, interest, instalment):
    return interest


def _interest_only_rolled(opening, interest, instalment):
    return interest * 0


_RULES: dict[tuple[Structure, InterestTreatment], PaymentRule] = {
    (Structure.AMORTISING, InterestTreatment.PAID): _amortising,
    (Structure.INTEREST_ONLY, InterestTreatment.PAID): _interest_only_paid,
    (Structure.INTEREST_ONLY, InterestTreatment.ROLLED): _interest_only_rolled,
}


def payment_rule(structure: Structure, treatment: InterestTreatment) -> PaymentRule:
    try:
        return _RULES[(structure, treatment)]
    except KeyError:
        raise ValueError(f"no payment rule for {structure.value} + {treatment.value}") from None


def period_payment(
    rule: PaymentRule,
    period: int,
    n: int,
    retained_months: int,
    opening,
    interest,
    instalment,
    final_is_regular: bool = False,
):
    """Return (payment, interest_retained) for one period.

    Retention periods (period <= retained_months) have their interest met from
    the retention. The final period clears the balance, unless
    `final_is_regular` is set (the instalment solver's dry run, which pays the
    level instalment in the last period too and leaves the balloon).
    """
    retained = interest if period <= retained_months else interest * 0
    if period == n and not final_is_regular:
        return opening + interest - retained, retained
    if period <= retained_months:
        return interest * 0, retained
    return rule(opening, interest, instalment), retained


def split_payment(payment, interest, interest_retained, unpaid_interest_bf):
    """Split a payment into interest and principal.

    Interest the customer has not paid (rolled, or a shortfall when an
    instalment is below a long first period's interest) is carried forward and
    added to the balance; later payments settle it before any principal. So on
    a rolled loan the final payment's interest_paid includes all rolled
    interest, and principal repaid always sums to the original principal.

    Returns (interest_paid, principal_repaid, interest_rolled, unpaid_interest_cf).
    """
    due = unpaid_interest_bf + interest - interest_retained
    interest_paid = min(payment, due)
    unpaid_interest_cf = due - interest_paid
    interest_rolled = max(unpaid_interest_cf - unpaid_interest_bf, interest * 0)
    return interest_paid, payment - interest_paid, interest_rolled, unpaid_interest_cf
