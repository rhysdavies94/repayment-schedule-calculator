"""Golden cases: fixed inputs against schedules signed off from an independent spreadsheet.

Until a case's expected files are filled and marked SIGNED_OFF, the comparison
is skipped; the inputs are still run through the engine so every case is
known to build and pass its hard checks.
"""

import csv
import json
import shutil

import pytest

from repayment_schedule import LoanInputs, generate_schedule
from repayment_schedule.export import write_csv
from repayment_schedule.golden import DEFAULT_GOLDEN_DIR, compare, list_cases, load_case

CASES = list_cases()


def test_golden_cases_found():
    assert len(CASES) >= 15


@pytest.mark.parametrize("case", CASES)
def test_golden_input_builds_and_validates(case):
    golden = load_case(case)
    assert generate_schedule(LoanInputs(**golden.params)).passed


@pytest.mark.parametrize("case", CASES)
def test_golden_matches_signed_off_schedule(case):
    golden = load_case(case)
    if not golden.signed_off:
        pytest.skip("expected outputs are placeholders awaiting sign-off")
    diffs = compare(generate_schedule(LoanInputs(**golden.params)), golden)
    assert not diffs, "\n".join(diffs[:20])


# --- compare() itself, on a signed-off copy filled from the engine ------------

def _signed_off_copy(tmp_path, case, tweak=None):
    """Copy a case, fill its expected outputs from the engine, optionally tweak one value."""
    root = tmp_path / "golden"
    shutil.copytree(DEFAULT_GOLDEN_DIR / case, root / case)
    golden = load_case(case, root)
    result = generate_schedule(LoanInputs(**golden.params))
    rows = list(csv.DictReader(write_csv(result, tmp_path).open(newline="")))
    if tweak:
        rows[tweak[0]][tweak[1]] = tweak[2]
    with (root / case / "expected_schedule.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    s = result.summary
    summary = {"status": "SIGNED_OFF", "level_instalment": str(s.level_instalment),
               "eir_annual": str(s.eir_annual), "eir_tolerance": "0.000001"}
    (root / case / "expected_summary.json").write_text(json.dumps(summary))
    return load_case(case, root)


def test_compare_signed_off_match(tmp_path):
    golden = _signed_off_copy(tmp_path, "01_amortising_30e360_regular")
    assert golden.signed_off
    assert compare(generate_schedule(LoanInputs(**golden.params)), golden) == []


def test_compare_reports_a_penny_difference(tmp_path):
    golden = _signed_off_copy(tmp_path, "01_amortising_30e360_regular",
                              tweak=(4, "interest", "999.99"))
    diffs = compare(generate_schedule(LoanInputs(**golden.params)), golden)
    assert len(diffs) == 1 and diffs[0].startswith("period 5 interest")
