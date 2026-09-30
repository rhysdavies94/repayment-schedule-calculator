"""Loan repayment schedule, level instalment and IFRS 9 EIR calculator."""

from .inputs import (
    DayCount,
    HolidayCalendar,
    InputError,
    InterestTreatment,
    LoanInputs,
    Structure,
    round_penny,
)
from .schedule import ScheduleResult, ScheduleRow, Summary, generate_schedule
from .validate import CheckResult, ScheduleValidationError

__all__ = [
    "CheckResult",
    "DayCount",
    "HolidayCalendar",
    "InputError",
    "InterestTreatment",
    "LoanInputs",
    "ScheduleResult",
    "ScheduleRow",
    "ScheduleValidationError",
    "Structure",
    "Summary",
    "generate_schedule",
    "round_penny",
]
