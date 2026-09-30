"""generate_schedule(): the single period loop, the solves, and validation.

Pure: the same LoanInputs always give the same ScheduleResult, with no I/O
beyond reading the packaged holiday calendar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Callable, Sequence

from . import solver
from .dates import BusinessCalendar, load_calendar, nominal_dates
from .daycount import basis, days_between, year_fraction
from .inputs import (
    PENNY,
    ZERO,
    InputError,
    LoanInputs,
    Structure,
    round_penny,
)
from .structures import PaymentRule, payment_rule, period_payment, split_payment
from .validate import (
    HARD,
    CheckResult,
    ScheduleValidationError,
    run_checks,
)

RATE_PLACES = Decimal("0.0000000001")

# V3 tolerance = coefficient x S + 0.01 (PRD). 0.005 covers rounding the
# instalment only; per-period interest rounding compounds by the same factors,
# so the true worst case is 0.01. See README "Open questions".
V3_ROUNDING_COEFFICIENT = Decimal("0.005")


@dataclass(frozen=True)
class Period:
    number: int
    nominal_date: date
    start_date: date
    payment_date: date
    days: int
    basis: int


@dataclass(frozen=True)
class ScheduleRow:
    period: int
    nominal_date: date
    payment_date: date
    days: int
    opening_balance: Decimal
    interest: Decimal
    payment: Decimal
    interest_paid: Decimal
    principal_repaid: Decimal
    interest_rolled: Decimal
    interest_retained: Decimal
    closing_balance: Decimal


@dataclass(frozen=True)
class Summary:
    loan_id: str | None
    principal: Decimal
    capitalised_fees: Decimal
    retained_interest: Decimal
    net_advance: Decimal  # principal - capitalised fees - retained interest
    level_instalment: Decimal | None  # amortising only
    total_interest: Decimal
    total_payable: Decimal
    final_payment: Decimal
    final_payment_adjustment: Decimal
    v3_tolerance: Decimal
    rounding_factor_sum: Decimal  # S in the V3 tolerance
    eir_annual: Decimal
    eir_monthly: Decimal


@dataclass(frozen=True)
class ScheduleResult:
    inputs: LoanInputs
    summary: Summary
    rows: tuple[ScheduleRow, ...]
    checks: tuple[CheckResult, ...]
    warnings: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks if c.severity == HARD)


def build_periods(inputs: LoanInputs, calendar: BusinessCalendar) -> list[Period]:
    """Periods from disbursement, each ending on its adjusted payment date."""
    periods = []
    start = inputs.disbursement_date
    for number, nominal in enumerate(
        nominal_dates(inputs.first_payment_date, inputs.term_months), start=1
    ):
        paid = calendar.adjust(nominal)
        if paid <= start:
            raise InputError(
                f"period {number}: adjusted payment date {paid} is not after {start}"
            )
        periods.append(
            Period(
                number, nominal, start, paid,
                days_between(start, paid, inputs.day_count), basis(inputs.day_count),
            )
        )
        start = paid
    return periods


def _roll(
    principal,
    rate,
    periods: Sequence[Period],
    rule: PaymentRule,
    retained_months: int,
    instalment,
    money: Callable,
    final_is_regular: bool = False,
) -> list[tuple]:
    """The period loop. Returns (opening, interest, payment, retained, closing) per period.

    `money` is round_penny for the real schedule and the identity for the
    unrounded float dry runs the solvers use.
    """
    n = len(periods)
    opening = principal
    out = []
    for p in periods:
        interest = money(opening * rate * p.days / p.basis)
        payment, retained = period_payment(
            rule, p.number, n, retained_months, opening, interest, instalment, final_is_regular
        )
        closing = opening + interest - payment - retained
        out.append((opening, interest, payment, retained, closing))
        opening = closing
    return out


def _identity(x):
    return x


def _dry_final_balance(principal, inputs, periods, rule) -> Callable[[float], float]:
    """B_n(P): unrounded final balance after paying P in every non-retained period."""
    p0, rate = float(principal), float(inputs.annual_rate)

    def final_balance(instalment: float) -> float:
        return _roll(p0, rate, periods, rule, inputs.retained_months, instalment,
                     _identity, final_is_regular=True)[-1][4]

    return final_balance


def _retained_interest(principal: Decimal, inputs: LoanInputs, periods: Sequence[Period]) -> Decimal:
    return sum(
        (round_penny(principal * inputs.annual_rate * p.days / p.basis)
         for p in periods[: inputs.retained_months]),
        ZERO,
    )


def gross_up(inputs: LoanInputs, periods: Sequence[Period]) -> Decimal:
    """Gross principal G whose G - fees - rounded retained interest == net_advance."""
    rate = float(inputs.annual_rate)
    retained_dcf = sum(p.days / p.basis for p in periods[: inputs.retained_months])
    net, fees = inputs.net_advance, inputs.capitalised_fees

    g_star = solver.solve_gross_up(
        lambda g: g * rate * retained_dcf, float(net), float(fees)
    )
    g0 = round_penny(Decimal(repr(g_star)))
    # Rounded retained interest can differ from the unrounded solve by up to
    # half a penny per retained month, so search outward from the rounded solve,
    # nearest penny first. Net rises by at most 1p per 1p of G, so an exact
    # match always exists within this window.
    window = inputs.retained_months + 5
    for step in range(window + 1):
        for g in (g0 + step * PENNY, g0 - step * PENNY):
            if g - fees - _retained_interest(g, inputs, periods) == net:
                return g
    raise InputError(
        f"no gross principal within {window}p of {g0} gives a net advance of exactly {net}"
    )


def _rows(inputs, periods, principal, instalment, rule) -> list[ScheduleRow]:
    raw = _roll(principal, inputs.annual_rate, periods, rule,
                inputs.retained_months, instalment, round_penny)
    rows = []
    unpaid = ZERO
    for p, (opening, interest, payment, retained, closing) in zip(periods, raw):
        interest_paid, principal_repaid, rolled, unpaid = split_payment(
            payment, interest, retained, unpaid
        )
        rows.append(
            ScheduleRow(
                p.number, p.nominal_date, p.payment_date, p.days, opening, interest,
                payment, interest_paid, principal_repaid, rolled, retained, closing,
            )
        )
    return rows


def _choose_instalment(inputs, periods, principal, rule, p_star: float):
    """Try the floor and ceiling pennies of P*; keep the smaller final adjustment.

    A candidate that drives any balance negative is only used if both do.
    """
    exact = Decimal(repr(max(p_star, 0.0)))
    candidates = sorted({exact.quantize(PENNY, ROUND_FLOOR), exact.quantize(PENNY, ROUND_CEILING)})
    best = None
    for candidate in candidates:
        rows = _rows(inputs, periods, principal, candidate, rule)
        adjustment = rows[-1].payment - (candidate + inputs.balloon_amount)
        negative = any(r.closing_balance < 0 for r in rows)
        key = (negative, abs(adjustment))
        if best is None or key < best[0]:
            best = (key, candidate, rows)
    return best[1], best[2]


def _regular_final_payment(inputs, rows, instalment) -> Decimal:
    """V3's regular payment: P + balloon, or balance plus interest on interest-only."""
    if inputs.structure is Structure.AMORTISING:
        return instalment + inputs.balloon_amount
    final = rows[-1]
    return final.opening_balance + final.interest - final.interest_retained


def _to_rate(x: float) -> Decimal:
    return Decimal(repr(x)).quantize(RATE_PLACES)


def generate_schedule(inputs: LoanInputs, *, raise_on_failure: bool = True) -> ScheduleResult:
    """Build, solve and validate one loan's schedule.

    Raises ScheduleValidationError if any hard check fails (unless
    raise_on_failure is False, when the failing result is returned).
    """
    calendar = load_calendar(inputs.holiday_calendar)
    periods = build_periods(inputs, calendar)
    rule = payment_rule(inputs.structure, inputs.interest_treatment)

    principal = inputs.principal if inputs.principal is not None else gross_up(inputs, periods)
    if inputs.balloon_amount >= principal:
        raise InputError(
            f"balloon_amount ({inputs.balloon_amount}) must be less than principal ({principal})"
        )

    # Level instalment and the V3 rounding factor S (amortising only).
    instalment = None
    s_factor = 0.0
    if inputs.structure is Structure.AMORTISING:
        final_balance = _dry_final_balance(principal, inputs, periods, rule)
        term_years = float(year_fraction(inputs.disbursement_date, periods[-1].payment_date,
                                         inputs.day_count))
        # PRD bound plus a margin: on a one-instalment loan the bound is the
        # root itself, and float noise could leave both ends on the same side.
        upper = float(principal) * (1 + float(inputs.annual_rate) * term_years) * 1.01 + 1
        p_star = solver.solve_instalment(final_balance, float(inputs.balloon_amount), upper)
        s_factor = final_balance(0.0) - final_balance(1.0)
        instalment, rows = _choose_instalment(inputs, periods, principal, rule, p_star)
    else:
        rows = _rows(inputs, periods, principal, None, rule)

    rounding_factor_sum = Decimal(repr(s_factor)).quantize(Decimal("0.0001"))
    v3_tolerance = (V3_ROUNDING_COEFFICIENT * rounding_factor_sum + PENNY).quantize(
        Decimal("0.0001"), ROUND_CEILING
    )

    retained_interest = sum((r.interest_retained for r in rows), ZERO)
    net_advance = principal - inputs.capitalised_fees - retained_interest
    if net_advance <= 0:
        raise InputError(
            f"net cash advanced must be positive: principal {principal} - fees "
            f"{inputs.capitalised_fees} - retained interest {retained_interest} = {net_advance}"
        )

    # EIR on the contractual day-count basis.
    cashflows = [(0.0, -float(net_advance))] + [
        (float(year_fraction(inputs.disbursement_date, r.payment_date, inputs.day_count)),
         float(r.payment))
        for r in rows
        if r.payment
    ]
    eir = solver.solve_eir(cashflows)
    eir_annual = _to_rate(eir)
    eir_monthly = _to_rate((1 + eir) ** (1 / 12) - 1)

    eir_expected = None
    if inputs.capitalised_fees == 0 and inputs.retained_months == 0:
        eir_expected = _to_rate((1 + float(inputs.annual_rate) / 12) ** 12 - 1)

    regular_final = _regular_final_payment(inputs, rows, instalment)
    checks = run_checks(
        rows=rows,
        principal=principal,
        retained_interest=retained_interest,
        regular_final_payment=regular_final,
        v3_tolerance=v3_tolerance,
        disbursement_date=inputs.disbursement_date,
        calendar=calendar,
        eir_annual=eir_annual,
        eir_expected=eir_expected,
    )

    warnings = []
    projected = sorted({p.payment_date.year for p in periods if calendar.is_projected(p.payment_date)})
    if projected:
        warnings.append(
            f"The GOV.UK bank holiday feed covers {calendar.first_year}-{calendar.last_year}. "
            f"Holidays for {projected[0]}-{projected[-1]} are projected from the standard "
            "England and Wales rules; one-off holidays in those years are not known."
        )
    warnings += [f"{c.code} {c.name}: {c.detail}" for c in checks
                 if c.severity != HARD and not c.passed]

    total_interest = sum((r.interest for r in rows), ZERO)
    summary = Summary(
        loan_id=inputs.loan_id,
        principal=principal,
        capitalised_fees=inputs.capitalised_fees,
        retained_interest=retained_interest,
        net_advance=net_advance,
        level_instalment=instalment,
        total_interest=total_interest,
        total_payable=sum((r.payment for r in rows), ZERO),
        final_payment=rows[-1].payment,
        final_payment_adjustment=rows[-1].payment - regular_final,
        v3_tolerance=v3_tolerance,
        rounding_factor_sum=rounding_factor_sum,
        eir_annual=eir_annual,
        eir_monthly=eir_monthly,
    )
    result = ScheduleResult(inputs, summary, tuple(rows), tuple(checks), tuple(warnings))
    if raise_on_failure and not result.passed:
        raise ScheduleValidationError(result)
    return result
