import csv

from repayment_schedule import generate_schedule
from repayment_schedule.export import (
    SCHEDULE_COLUMNS,
    checks_dataframe,
    csv_filename,
    summary_dataframe,
    write_csv,
)

from .conftest import make_inputs


def test_csv_has_plain_two_decimal_values(tmp_path):
    result = generate_schedule(make_inputs(loan_id="LN/001 A", term_months=12))
    path = write_csv(result, tmp_path)
    assert path.name == "schedule_LN_001_A_2026-10-15.csv"
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0]) == SCHEDULE_COLUMNS
    assert len(rows) == 12
    assert rows[0]["opening_balance"] == "100000.00"
    assert rows[0]["payment_date"] == "2026-11-16"
    for row in rows:
        for col in SCHEDULE_COLUMNS[4:]:
            value = row[col]
            assert "," not in value and "£" not in value
            assert len(value.split(".")[1]) == 2


def test_default_filename_without_loan_id():
    result = generate_schedule(make_inputs(loan_id=None, term_months=12))
    assert csv_filename(result) == "schedule_loan_2026-10-15.csv"


def test_display_frames():
    result = generate_schedule(make_inputs(term_months=12))
    assert list(checks_dataframe(result).index) == [f"V{i}" for i in range(1, 8)]
    assert "EIR (annual)" in summary_dataframe(result).index
