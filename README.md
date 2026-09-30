# Loan repayment schedule calculator

Takes one loan's details at disbursement and returns a validated customer
repayment schedule, the contractual level instalment and the IFRS 9 EIR. See
`PRD_loan_repayment_schedule.md` for the product rules.

The calculation core (`repayment_schedule/`) is pure Python with no I/O apart
from reading the packaged bank holiday file. The notebook is a thin shell over
it, and a Cloud Run handler can later be another one.

## Setup

Dependencies are managed with [uv](https://docs.astral.sh/uv/):

```
uv sync
```

`requirements.txt` is exported from the lock file
(`uv export --no-hashes --no-emit-project -o requirements.txt`) for tools that need it.

## Use

Notebook: open `notebooks/generate_schedule.ipynb`, edit the parameters cell and
run all cells. It shows the summary, the V1–V7 checks and the schedule, and writes
`schedule_<loan_id>_<disbursement_date>.csv`. To run it headless:

```
uv run papermill notebooks/generate_schedule.ipynb out.ipynb -p loan_id LN-001 -p principal 250000.00 -p term_months 120
```

## Golden scenario explorer (Streamlit)

`app/streamlit_app.py` is a web app for the golden cases in `tests/golden/`:

- a sidebar picker with ◀ ▶ buttons;
- headline figures and status badges (hard checks, sign-off, warnings);
- tabs for the summary, V1–V7 checks, schedule, inputs and golden comparison, which shows every difference to the penny once a case is signed off;
- a CSV download button.

The loading and comparison logic is in `repayment_schedule/golden.py`, shared
with `tests/test_golden.py`.

Run locally:

```
uv run streamlit run app/streamlit_app.py
```

### Deploy to Streamlit Community Cloud

1. Push this folder to a GitHub repository.
2. At https://share.streamlit.io choose **Create app → Deploy a public app from GitHub**.
3. Pick the repository and branch, and set the main file path to `app/streamlit_app.py`.
4. Optionally set a custom subdomain under **Advanced settings**. Python 3.12 is fine.
5. Deploy. The link is `https://<subdomain>.streamlit.app`, and each push to the branch redeploys.

Community Cloud installs from `app/requirements.txt`, since the entrypoint's
folder is searched before the repository root. That file holds only the runtime
dependencies and Streamlit. Regenerate it after changing dependencies:

```
uv export --no-hashes --no-emit-project --no-dev --group app -o app/requirements.txt
```

If the repository is private, the app is private too; share it by inviting
viewers' emails in the app's settings.

## Python API

```python
from repayment_schedule import LoanInputs, generate_schedule

result = generate_schedule(LoanInputs(
    loan_id="LN-001", principal="250000.00", annual_rate="0.0895", day_count="ACT_365",
    structure="AMORTISING", disbursement_date="2026-10-15",
    first_payment_date="2026-11-15", term_months=60,
))
result.summary.level_instalment, result.summary.eir_annual
```

`generate_schedule` raises `InputError` for bad inputs and
`ScheduleValidationError` if any hard check fails. Pass `raise_on_failure=False`
to get the failing result back instead.

## Layout

```
repayment_schedule/
  inputs.py      LoanInputs, enums, input checks, round_penny
  dates.py       nominal and modified-following payment dates, bank holidays
  daycount.py    days_between / year_fraction per convention
  structures.py  payment rule per structure, retained and rolled interest
  solver.py      brentq solves: instalment, gross-up, EIR
  schedule.py    generate_schedule() -> ScheduleResult
  validate.py    V1 to V7
  export.py      DataFrames and CSV
  golden.py      load golden cases, compare a result to signed-off outputs
  data/uk_bank_holidays.json   GOV.UK feed (https://www.gov.uk/bank-holidays.json)
notebooks/generate_schedule.ipynb   papermill-friendly single loan run
app/streamlit_app.py                golden scenario explorer (Streamlit)
app/requirements.txt                Community Cloud dependencies (uv export)
tests/           unit, Hypothesis property and golden tests
tests/golden/    one folder per golden case
```

## Tests

```
uv run pytest
```

Golden cases live in `tests/golden/<case>/`:

- `input.json` holds the loan parameters and what the case proves.
- `expected_schedule.csv` has the schedule columns, with the header only until it is filled.
- `expected_summary.json` holds the headline figures, as placeholders.

To sign off a case, paste the spreadsheet schedule into the CSV using the same
columns and 2dp values. Then fill the summary figures and set `"status": "SIGNED_OFF"`.
Until then the comparison is skipped, but every golden input still runs through
the engine and must pass the hard checks.

## Updating the bank holidays

Download https://www.gov.uk/bank-holidays.json over
`repayment_schedule/data/uk_bank_holidays.json` on each release. For years the
feed doesn't cover, the engine projects the standard England and Wales holidays,
including substitute days, and adds a warning to the result. One-off holidays
such as coronations can't be projected.

## Decisions taken where the PRD is silent or ambiguous

- **Row arithmetic with retention.** In retention periods the interest comes
  from the retention, so V5 checks
  `closing = opening + interest − payment − interest_retained`. The PRD's
  formula leaves out the retained term, which would contradict "balance stays at gross".
- **Final period of a full-term retention.** The payment is the balance only,
  because the final period's interest was retained.
- **Net advance with fees.** `net_advance` means the cash actually paid out,
  `principal − capitalised_fees − retained_interest`, the same figure the EIR uses.
  The gross-up solves to it exactly.
- **Interest shortfall on amortising loans.** A long broken first period can
  charge more interest than the level instalment. The unpaid interest is added to
  the balance, shown in `interest_rolled`, and settled first by later payments,
  so principal repaid never goes negative.
- **Instalment rounding.** Between the floor and ceiling pennies, a candidate
  that would make any balance negative is used only if both do.
- **Instalment bracket.** The upper bound is the PRD's
  `principal × (1 + rate × T)`, plus a 1% + £1 margin. On a one-instalment loan
  the PRD bound is exactly the root, so float noise could break the bracket.
- **V7 benchmark.** The effective annual rate used is `(1 + rate/12)^12 − 1`.
- **First payment moved onto the disbursement date.** For example, disbursing on
  Fri 30 Oct with the first payment due Sat 31 Oct. This is rejected as an input error.

## Open questions

- **V3 tolerance is too tight.** `0.005 × S + 0.01` covers rounding the
  instalment, but not per-period interest rounding, which compounds by the same
  factors. About 0.9% of random amortising loans fail V3 on rounding alone, with
  the worst case at 1.31 × `0.005 × S`. The theoretical worst case is
  `0.01 × S + 0.01`. The coefficient is `V3_ROUNDING_COEFFICIENT` in `schedule.py`.
- **Bank holiday feed ends in 2028.** How should dates after that be treated?
  The current behaviour projects them from the statutory rules and warns.
