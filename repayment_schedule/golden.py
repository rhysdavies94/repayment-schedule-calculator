"""Load golden cases and compare a result against their signed-off expected outputs.

Shared by tests/test_golden.py and the scenario explorer notebook. Each case is
a folder under tests/golden/ holding input.json, expected_schedule.csv and
expected_summary.json.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .export import MONEY_COLUMNS, SCHEDULE_COLUMNS
from .schedule import ScheduleResult

DEFAULT_GOLDEN_DIR = Path(__file__).resolve().parents[1] / "tests" / "golden"

SUMMARY_MONEY = [
    "principal", "net_advance", "retained_interest", "level_instalment",
    "total_interest", "total_payable", "final_payment",
]
SUMMARY_RATES = ["eir_annual", "eir_monthly"]


@dataclass(frozen=True)
class GoldenCase:
    name: str
    proves: str
    params: dict
    expected_rows: list[dict]
    expected_summary: dict

    @property
    def signed_off(self) -> bool:
        return self.expected_summary.get("status") == "SIGNED_OFF" and bool(self.expected_rows)


def list_cases(root: Path = DEFAULT_GOLDEN_DIR) -> list[str]:
    return sorted(p.name for p in Path(root).iterdir() if (p / "input.json").exists())


def load_case(name: str, root: Path = DEFAULT_GOLDEN_DIR) -> GoldenCase:
    folder = Path(root) / name
    spec = json.loads((folder / "input.json").read_text("utf-8"))
    with (folder / "expected_schedule.csv").open(newline="", encoding="utf-8") as f:
        expected_rows = list(csv.DictReader(f))
    summary = json.loads((folder / "expected_summary.json").read_text("utf-8"))
    return GoldenCase(name, spec.get("proves", ""), spec["params"], expected_rows, summary)


def compare(result: ScheduleResult, case: GoldenCase) -> list[str]:
    """Differences between a result and the case's expected outputs (empty if it matches).

    Money must match to the penny; EIRs within the case's eir_tolerance.
    """
    diffs = []
    if len(result.rows) != len(case.expected_rows):
        diffs.append(f"row count: got {len(result.rows)}, expected {len(case.expected_rows)}")
    for row, expected in zip(result.rows, case.expected_rows):
        for col in SCHEDULE_COLUMNS:
            actual = getattr(row, col)
            if col in MONEY_COLUMNS:
                same = actual == Decimal(expected[col])
            else:
                same = str(actual) == expected[col]
            if not same:
                diffs.append(f"period {row.period} {col}: got {actual}, expected {expected[col]}")

    summary = case.expected_summary
    for field in SUMMARY_MONEY:
        if summary.get(field) is not None:
            actual = getattr(result.summary, field)
            if actual != Decimal(summary[field]):
                diffs.append(f"{field}: got {actual}, expected {summary[field]}")
    tolerance = Decimal(summary.get("eir_tolerance") or "0.000001")
    for field in SUMMARY_RATES:
        if summary.get(field) is not None:
            actual = getattr(result.summary, field)
            if abs(actual - Decimal(summary[field])) > tolerance:
                diffs.append(f"{field}: got {actual}, expected {summary[field]} (±{tolerance})")
    return diffs
