"""DataFrames for display and the CSV export. The only module that writes files."""

from __future__ import annotations

import re
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

import pandas as pd

from .schedule import ScheduleResult

SCHEDULE_COLUMNS = [
    "period",
    "nominal_date",
    "payment_date",
    "days",
    "opening_balance",
    "interest",
    "payment",
    "interest_paid",
    "principal_repaid",
    "interest_rolled",
    "interest_retained",
    "closing_balance",
]
MONEY_COLUMNS = SCHEDULE_COLUMNS[4:]


def schedule_dataframe(result: ScheduleResult) -> pd.DataFrame:
    """Schedule rows with Decimal amounts kept exact."""
    return pd.DataFrame([asdict(r) for r in result.rows], columns=SCHEDULE_COLUMNS)


def summary_dataframe(result: ScheduleResult) -> pd.DataFrame:
    s = result.summary
    items = [
        ("Loan ID", s.loan_id or ""),
        ("Principal (gross)", s.principal),
        ("Capitalised fees", s.capitalised_fees),
        ("Retained interest", s.retained_interest),
        ("Net advance", s.net_advance),
        ("Level instalment", s.level_instalment if s.level_instalment is not None else "n/a"),
        ("Total interest", s.total_interest),
        ("Total payable", s.total_payable),
        ("Final payment", s.final_payment),
        ("Final-payment adjustment", s.final_payment_adjustment),
        ("V3 tolerance", s.v3_tolerance),
        ("EIR (annual)", f"{s.eir_annual * 100:.4f}%"),
        ("EIR (monthly equivalent)", f"{s.eir_monthly * 100:.4f}%"),
    ]
    return pd.DataFrame(items, columns=["item", "value"]).set_index("item")


def checks_dataframe(result: ScheduleResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "check": c.code,
                "name": c.name,
                "type": c.severity.title(),
                "result": "PASS" if c.passed else ("WARN" if c.severity != "HARD" else "FAIL"),
                "detail": c.detail,
            }
            for c in result.checks
        ]
    ).set_index("check")


def csv_filename(result: ScheduleResult) -> str:
    loan_id = re.sub(r"[^A-Za-z0-9_-]+", "_", result.inputs.loan_id or "loan")
    return f"schedule_{loan_id}_{result.inputs.disbursement_date.isoformat()}.csv"


def csv_text(result: ScheduleResult) -> str:
    """The schedule as CSV text: plain 2dp values, no symbols or separators."""
    df = schedule_dataframe(result)
    for col in MONEY_COLUMNS:
        df[col] = df[col].map(lambda x: f"{Decimal(x):.2f}")
    return df.to_csv(index=False, lineterminator="\n")


def write_csv(result: ScheduleResult, directory: str | Path = ".") -> Path:
    """Write the schedule CSV as schedule_<loan_id>_<disbursement_date>.csv."""
    path = Path(directory) / csv_filename(result)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(csv_text(result), encoding="utf-8", newline="")
    return path
