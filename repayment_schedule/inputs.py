"""LoanInputs, enums, money helpers and input checks.

Inputs are coerced to their proper types (Decimal, date, enum) and checked
once, before any calculation. A failed check raises InputError listing every
problem found, in plain words.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import Enum

PENNY = Decimal("0.01")
ZERO = Decimal("0.00")


def round_penny(amount: Decimal) -> Decimal:
    """Round a money amount to the penny, half-up."""
    return amount.quantize(PENNY, rounding=ROUND_HALF_UP)


class DayCount(str, Enum):
    ACT_365 = "ACT_365"
    ACT_360 = "ACT_360"
    THIRTY_E_360 = "30E_360"


class Structure(str, Enum):
    AMORTISING = "AMORTISING"
    INTEREST_ONLY = "INTEREST_ONLY"


class InterestTreatment(str, Enum):
    PAID = "PAID"
    ROLLED = "ROLLED"


class HolidayCalendar(str, Enum):
    ENGLAND_WALES = "ENGLAND_WALES"


class InputError(ValueError):
    """Raised when loan inputs fail a check. The message lists every failure."""


def _to_decimal(name: str, value) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise InputError(f"{name} must be a number, got {value!r}")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise InputError(f"{name} must be a number, got {value!r}") from None
    if not result.is_finite():
        raise InputError(f"{name} must be a finite number, got {value!r}")
    return result


def _to_date(name: str, value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise InputError(f"{name} must be a date (YYYY-MM-DD), got {value!r}") from None


def _to_enum(enum: type[Enum], name: str, value) -> Enum:
    if isinstance(value, enum):
        return value
    try:
        return enum(value)
    except ValueError:
        allowed = ", ".join(m.value for m in enum)
        raise InputError(f"{name} must be one of {allowed}, got {value!r}") from None


def _to_int(name: str, value) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InputError(f"{name} must be a whole number, got {value!r}")
    return value


def _is_pennies(amount: Decimal) -> bool:
    return amount == amount.quantize(PENNY)


@dataclass(frozen=True, kw_only=True)
class LoanInputs:
    """One loan's details at disbursement. Field names match the PRD Inputs table."""

    annual_rate: Decimal
    day_count: DayCount
    structure: Structure
    disbursement_date: date
    first_payment_date: date
    term_months: int
    loan_id: str | None = None
    principal: Decimal | None = None
    net_advance: Decimal | None = None
    interest_treatment: InterestTreatment = InterestTreatment.PAID
    retained_months: int = 0
    balloon_amount: Decimal = ZERO
    capitalised_fees: Decimal = ZERO
    holiday_calendar: HolidayCalendar = HolidayCalendar.ENGLAND_WALES

    def __post_init__(self) -> None:
        coerced = {
            "annual_rate": _to_decimal("annual_rate", self.annual_rate),
            "day_count": _to_enum(DayCount, "day_count", self.day_count),
            "structure": _to_enum(Structure, "structure", self.structure),
            "disbursement_date": _to_date("disbursement_date", self.disbursement_date),
            "first_payment_date": _to_date("first_payment_date", self.first_payment_date),
            "term_months": _to_int("term_months", self.term_months),
            "loan_id": None if self.loan_id is None else str(self.loan_id),
            "principal": _to_decimal("principal", self.principal),
            "net_advance": _to_decimal("net_advance", self.net_advance),
            "interest_treatment": _to_enum(
                InterestTreatment, "interest_treatment", self.interest_treatment
            ),
            "retained_months": _to_int("retained_months", self.retained_months),
            "balloon_amount": _to_decimal("balloon_amount", self.balloon_amount or 0),
            "capitalised_fees": _to_decimal("capitalised_fees", self.capitalised_fees or 0),
            "holiday_calendar": _to_enum(
                HolidayCalendar, "holiday_calendar", self.holiday_calendar
            ),
        }
        for name, value in coerced.items():
            object.__setattr__(self, name, value)
        errors = check_inputs(self)
        if errors:
            raise InputError("Invalid loan inputs: " + "; ".join(errors))
        for name in ("principal", "net_advance", "balloon_amount", "capitalised_fees"):
            amount = getattr(self, name)
            if amount is not None:
                object.__setattr__(self, name, amount.quantize(PENNY))

    @classmethod
    def field_names(cls) -> list[str]:
        return [f.name for f in fields(cls)]


def check_inputs(inputs: LoanInputs) -> list[str]:
    """Return every input problem as a plain-English message (empty if none)."""
    errors: list[str] = []
    amortising = inputs.structure is Structure.AMORTISING

    if (inputs.principal is None) == (inputs.net_advance is None):
        errors.append("give exactly one of principal or net_advance")
    if inputs.net_advance is not None and inputs.retained_months == 0:
        errors.append("net_advance can only be given when retained_months > 0")
    for name in ("principal", "net_advance"):
        amount = getattr(inputs, name)
        if amount is not None:
            if amount <= 0:
                errors.append(f"{name} must be greater than 0, got {amount}")
            elif not _is_pennies(amount):
                errors.append(f"{name} must be in whole pennies, got {amount}")

    if inputs.annual_rate < 0:
        errors.append(f"annual_rate must be 0 or more, got {inputs.annual_rate}")
    if inputs.term_months < 1:
        errors.append(f"term_months must be at least 1, got {inputs.term_months}")
    if inputs.interest_treatment is InterestTreatment.ROLLED and amortising:
        errors.append("ROLLED interest is only allowed on INTEREST_ONLY loans")
    if inputs.first_payment_date <= inputs.disbursement_date:
        errors.append(
            f"first_payment_date {inputs.first_payment_date} must be after "
            f"disbursement_date {inputs.disbursement_date}"
        )

    if inputs.retained_months < 0:
        errors.append(f"retained_months must be 0 or more, got {inputs.retained_months}")
    elif inputs.retained_months > inputs.term_months:
        errors.append(
            f"retained_months ({inputs.retained_months}) cannot exceed "
            f"term_months ({inputs.term_months})"
        )
    elif amortising and inputs.retained_months == inputs.term_months:
        errors.append(
            "retained_months must be less than term_months on AMORTISING loans, "
            "so there is at least one instalment to solve"
        )

    balloon = inputs.balloon_amount
    if balloon < 0:
        errors.append(f"balloon_amount must be 0 or more, got {balloon}")
    elif not _is_pennies(balloon):
        errors.append(f"balloon_amount must be in whole pennies, got {balloon}")
    elif balloon > 0 and not amortising:
        errors.append("balloon_amount is only allowed on AMORTISING loans")
    elif balloon > 0 and inputs.principal is not None and balloon >= inputs.principal:
        errors.append(
            f"balloon_amount ({balloon}) must be less than principal ({inputs.principal})"
        )

    fees = inputs.capitalised_fees
    if fees < 0:
        errors.append(f"capitalised_fees must be 0 or more, got {fees}")
    elif not _is_pennies(fees):
        errors.append(f"capitalised_fees must be in whole pennies, got {fees}")

    return errors
