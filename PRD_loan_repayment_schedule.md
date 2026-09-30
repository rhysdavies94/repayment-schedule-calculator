# PRD: Loan Repayment Schedule Service

Sep 30, 2026 · Rhys

## Overview

We will build a Python Jupyter notebook that takes one loan's details at disbursement and outputs a validated customer repayment schedule, the contractual instalment and the IFRS 9 EIR. The calculation core is a small pure-Python package. The notebook is a thin shell over it, so the same core can later run as a Cloud Run function with no rewrite.

**In scope (v1)**

- One loan per run, at a single fixed rate for the whole term.
- Two structures: amortising (capital and interest) and interest-only bullet, plus parameters for rolled and retained interest.
- Day counts: Actual/360, Actual/365 Fixed, 30E/360.
- Monthly payments with UK bank holiday and weekend adjustment.
- Penny rounding each period, with any residual pennies taken on the final payment.
- Built-in validation, on-screen display and CSV export.

**Out of scope (v1)**

- Variable or stepped rates, rate changes mid-term.
- Early redemption, overpayments, payment holidays and arrears.
- Portfolio or batch runs (these come with the Cloud Run version).
- Accounting entries, ECL or staging.

**Design principles**

1. Simple and generic: new loan types are new small functions, not changes to the engine.
2. Pure functions: same inputs always give the same schedule, with no I/O in the core.
3. Money in `Decimal`: floats are used only inside the solvers, and never for stored amounts.
4. Every schedule is validated before it is returned.

## Product rules

Two loan structures share one engine, and they differ only in what is paid each month. Rolled and retained interest are parameters that change how interest is met, not separate products, so they can be combined with either structure where it makes sense.

### Loan structures

| Structure | Monthly payment | Principal repaid | Interest treatment |
| --- | --- | --- | --- |
| Amortising | Level instalment (solved at outset) | Across the term | Paid monthly |
| Interest-only | Interest for the period, or nothing if rolled | Bullet at maturity | Paid monthly, or rolled (see below) |

### Interest treatment parameters

`interest_treatment` is a parameter, not a loan type. It controls what happens to interest that the customer does not pay in a period.

- `PAID` (default): interest is settled by each payment.
- `ROLLED`: unpaid interest is added to the balance on each payment date, so it compounds monthly. All of it is settled with the principal at maturity.

In v1, `ROLLED` is allowed only on interest-only loans. A rolled-interest bridging loan is therefore `INTEREST_ONLY` + `ROLLED`.

`retained_months` (default 0) sets how many months of interest are retained at disbursement. For those months, interest is calculated on the total (gross) balance and deducted from the advance. The customer pays nothing and the balance stays at gross. From the next month, the loan's structure and `interest_treatment` apply as normal.

| Example loan | Parameters |
| --- | --- |
| Retained bridge, nothing due until redemption | `INTEREST_ONLY`, `retained_months` = term |
| 6 months retained, then capital and interest | `AMORTISING`, `retained_months` = 6 (instalment solved over the remaining months) |
| 6 months retained, then interest rolled up | `INTEREST_ONLY` + `ROLLED`, `retained_months` = 6 |

Balloon payments on amortising loans are handled as a bullet: a `balloon_amount` input leaves that amount outstanding at maturity, and the level instalment is solved to amortise only the rest.

### Principal input

The user enters the gross principal, which is the balance the customer owes on day one. Any fees capitalised under IFRS 9 are already included in it. A separate `capitalised_fees` input is used only to derive the net cash advanced for the EIR, and does not change the customer schedule.

When `retained_months` > 0, the user can instead enter the net advance. The engine then solves for the gross principal whose retained interest brings it back to that net figure (see Algorithms).

### Day-count conventions

Interest for each period = opening balance × annual rate × day-count fraction, rounded to the penny.

| Convention | Day-count fraction |
| --- | --- |
| Actual/365 Fixed | Actual days ÷ 365 |
| Actual/360 | Actual days ÷ 360 |
| 30E/360 | 30E days ÷ 360 |

For 30E/360, day 31 becomes day 30 at both the start and end dates:

```latex
\text{days} = 360(Y_2 - Y_1) + 30(M_2 - M_1) + (\min(D_2,30) - \min(D_1,30))
```

### Dates

- Interest accrues from the disbursement date. The first period runs from disbursement to the first payment date, and may be longer or shorter than a month.
- Payments are due on the same day each month (the nominal date). If that day is a weekend or England and Wales bank holiday, the payment moves to the next business day (modified following). If that would push it into the next calendar month, it moves back to the previous business day instead.
- The next period still uses the nominal date, so a moved payment does not drift the schedule.
- Interest accrues to the actual (adjusted) payment date, so a moved payment changes the day count on both sides of it.
- For a nominal day that does not exist in a month (for example the 31st in June), the month's last calendar day is used before business-day adjustment.

### Rounding

- Interest is rounded to the penny each period (half-up).
- The level instalment is rounded to the penny at the outset.
- The final payment clears the remaining balance exactly, so it absorbs the rounding residual. That residual must be pennies, never pounds (see Validation rules).

### EIR and instalment at outset

The engine outputs two figures at disbursement: the contractual level instalment and the EIR. The EIR is the IRR of the loan's dated cash flows: the net cash advanced goes out on the disbursement date, and every scheduled payment comes in on its adjusted date.

```latex
\text{net advance} = \text{principal} - \text{capitalised fees} - \text{retained interest}
```

The EIR is measured on the loan's contractual day-count basis only, so time is measured with the same year fraction as the interest. It is reported as an annual rate, with a monthly equivalent alongside.

## Inputs

All inputs live in one flat parameter set. The notebook's parameter cell and the future Cloud Run JSON payload use the same fields.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `loan_id` | str | No | Carried onto the output and the CSV file name |
| `principal` | Decimal (£) | Yes, unless `net_advance` is given | Gross balance at day one, including capitalised fees |
| `net_advance` | Decimal (£) | Only when `retained_months` > 0, instead of `principal` | Engine grosses up to the principal |
| `annual_rate` | Decimal | Yes | Nominal annual rate, e.g. `0.0895` |
| `day_count` | enum | Yes | `ACT_365`, `ACT_360`, `30E_360` |
| `structure` | enum | Yes | `AMORTISING` or `INTEREST_ONLY` |
| `interest_treatment` | enum | No | `PAID` (default) or `ROLLED` |
| `retained_months` | int | No | Months of interest retained at outset; defaults to 0 |
| `disbursement_date` | date | Yes | Interest accrues from here |
| `first_payment_date` | date | Yes | Sets the nominal payment day |
| `term_months` | int | Yes | Number of monthly payment dates |
| `balloon_amount` | Decimal (£) | No | Amortising only; defaults to 0 |
| `capitalised_fees` | Decimal (£) | No | Used only for net advance in the EIR; defaults to 0 |
| `holiday_calendar` | enum | No | Defaults to `ENGLAND_WALES` |

Inputs are checked before any calculation, for example:

- principal (or net advance) > 0 and rate ≥ 0;
- exactly one of `principal` or `net_advance`, with `net_advance` only when `retained_months` > 0;
- `ROLLED` only on interest-only loans;
- first payment date after disbursement;
- `retained_months` ≤ `term_months`, and < `term_months` for amortising loans;
- balloon < principal, and only on amortising loans.

A failed check stops the run with a plain error message.

## Architecture

The architecture is a pure calculation core with two thin shells: the notebook now, and a Cloud Run handler later. Everything that differs between loans lives in small, swappable modules under one period loop.

Data flow: Notebook (parameter cell) or Cloud Run handler (JSON, later) → `inputs.py` → `schedule.py` period loop, which calls `dates.py`, `daycount.py`, `structures.py` and `solver.py` → `validate.py` → result (summary, EIR, checks, schedule rows).

Inputs are checked once, the loop calls the four helpers for each period, and nothing leaves the core until every hard check has passed.

```
repayment_schedule/
  inputs.py        # LoanInputs, enums, input checks
  dates.py         # nominal and adjusted payment dates
  daycount.py      # year_fraction(start, end, convention)
  structures.py    # payment rule per structure, rolled/retained
  solver.py        # brentq solves: instalment, gross-up, EIR
  schedule.py      # generate_schedule() -> ScheduleResult
  validate.py      # V1 to V7
  export.py        # DataFrame and CSV
  data/uk_bank_holidays.json
notebooks/generate_schedule.ipynb
tests/golden/  tests/test_*.py
```

The package needs four dependencies: `pandas` for display and CSV, `scipy` for the instalment, gross-up and EIR solves, `pydantic` (from the Cloud Run phase) and `hypothesis` (tests only). Bank holidays are loaded from the packaged GOV.UK calendar file, with no network call at run time.

## Algorithms

One period loop builds every schedule; each structure only supplies the payment rule for a period. The level instalment, the retained gross-up and the EIR are all solved with `scipy.optimize.brentq`, with no hand-built solvers.

### Period loop (all structures)

For each period *i*, the engine works through these steps:

1. Day-count fraction: `dcf_i = year_fraction(start_i, end_i, day_count)`, where `start_i` is the previous adjusted payment date (or disbursement) and `end_i` is this adjusted payment date.
2. Interest: `interest_i = round_penny(opening_i × rate × dcf_i)`.
3. Payment: `payment_i` comes from the structure's rule (table below).
4. Closing balance: `closing_i = opening_i + interest_i − payment_i`, and `opening_{i+1} = closing_i`.

The final period is the same for every structure: payment = opening + interest, so closing is exactly £0.00.

| Period type | Payment rule, periods 1 to n−1 | Where interest goes |
| --- | --- | --- |
| Retention period (any structure, periods ≤ R) | 0 from the customer; `interest_i` is drawn from the retention | Paid from retention; balance stays at gross |
| Amortising | Level instalment *P*, solved over the periods after retention | Paid |
| Interest-only, `PAID` | `interest_i` | Paid |
| Interest-only, `ROLLED` | 0 | Added to the balance and compounds monthly |

Each row splits the payment into `interest_paid` and `principal_repaid`. When interest is rolled, on the final payment `interest_paid` includes all interest rolled up to that date, so principal repaid across the term always sums to the original principal.

### Solving the level instalment

*P* is solved with `scipy.optimize.brentq` on an unrounded dry run of the schedule, finding the instalment where the final balance equals the balloon:

```latex
f(P) = B_n(P) - \text{balloon} = 0, \quad P \in [0,\ \text{principal} \times (1 + \text{rate} \times \text{term in years})]
```

- The dry run uses the real period loop, so all day counts, broken first periods and moved payment dates are handled.
- The upper bound is the principal plus simple interest for the whole term, which always overshoots, so the bracket always holds a root.
- `xtol=1e-10` keeps the unrounded answer well inside a penny.
- For 30E/360 loans with all-regular 30-day periods, the tests cross-check *P* against the textbook annuity formula.

*P** is then rounded to the penny. Both the floor and ceiling values are tried, and the one with the smaller final-payment adjustment is kept. The rounded schedule is then built as above.

### Retained interest (`retained_months` > 0)

The retained amount is the sum of the rounded interest for periods 1 to R, calculated on the gross balance. It is shown on the schedule header, deducted from the net advance, and appears in each retention row as `interest_retained`. The customer pays nothing in those rows.

**Gross-up from a net advance.** When `net_advance` is given, `brentq` solves for the gross principal *G* where *G* − retained interest(*G*) = net advance. The solve works on unrounded retained interest, because the rounded version is a step function. The engine then rounds *G* to the penny, rebuilds with rounded interest, and nudges *G* by a penny if the net figure is a penny out.

### EIR

The EIR solves NPV = 0 over the dated cash flows, using Brent's method (`scipy.optimize.brentq`) with time measured in the loan's own day count:

```latex
-\text{net advance} + \sum_i \frac{\text{payment}_i}{(1 + \text{EIR})^{t_i}} = 0, \quad t_i = \text{year\_fraction}(\text{disbursement}, \text{date}_i, \text{day\_count})
```

The monthly equivalent is (1 + EIR)^(1/12) − 1. With no fees and no retention, the EIR should sit within about 1bp of the contractual rate's effective annual equivalent. The engine runs this as a sanity check and flags a warning if it doesn't.

## Validation rules

Every schedule passes all hard checks before it is shown or exported; a failure raises an error that names the check and the figures. Checks run on `Decimal` amounts, so every comparison is exact to the penny.

| # | Check | Rule | Type |
| --- | --- | --- | --- |
| V1 | Final balance cleared | Closing balance in the last period = £0.00 exactly | Hard |
| V2 | Principal repaid | Σ `principal_repaid` = `principal` exactly | Hard |
| V3 | Final-payment adjustment | \|final payment − regular payment for that structure\| ≤ the loan's own tolerance (see below) | Hard |
| V4 | Cash reconciles | Σ payments + retained interest = principal + Σ interest | Hard |
| V5 | Row arithmetic | Every row: closing = opening + interest − payment, and no negative balances | Hard |
| V6 | Dates | Payment dates strictly increasing and all on business days | Hard |
| V7 | EIR sanity | With no fees or retention, EIR within 1bp of the contractual rate's effective annual equivalent | Warning |

For V3, the "regular payment" depends on the structure:

- **Amortising:** *P* + balloon.
- **Interest-only (paid or rolled), with or without retention:** the balance plus that period's interest, so the adjustment is zero by construction.

V3 is therefore a real test only for amortising loans, which is where rounding builds up.

**Long-term amortising loans.** Rounding *P* to the penny moves the final balance by up to £0.005 × *S*, where *S* is the sum of the per-period compounding factors. Picking the better of floor and ceiling minimises this, but cannot remove it.

| Example loan | *S* (approx.) | Worst-case final adjustment |
| --- | --- | --- |
| 5 years at 9% | 75 | £0.38 |
| 25 years at 9% | 1,120 | £5.60 |

The V3 tolerance therefore scales with each loan, so long-term loans don't fail on penny-rounding arithmetic alone:

```latex
\text{tolerance (£)} = 0.005 \times S + 0.01
```

*S* is measured from two unrounded dry runs, with instalments of £0 and £1: *S* = *B_n*(0) − *B_n*(1). The extra £0.01 covers per-period interest rounding. A breach means a real error, not rounding, and the tolerance used is shown in the summary.

## Notebook design and output

The notebook has five cells and contains no calculation logic. It imports the package, reads the parameter cell, and displays and exports the result.

1. **Parameters:** one cell tagged `parameters` (papermill-compatible), holding the fields from Inputs as plain Python values.
2. **Run:** `result = generate_schedule(LoanInputs(**params))`.
3. **Summary:** principal, net advance, level instalment, retained interest, total interest, total payable, EIR (annual and monthly), final-payment adjustment.
4. **Validation:** V1–V7 shown as a pass/fail table. The run stops here if any hard check fails.
5. **Schedule and export:** the schedule shown as a formatted DataFrame, and written to `schedule_<loan_id>_<disbursement_date>.csv`.

### Schedule columns

| Column | Description |
| --- | --- |
| `period` | 1 to n |
| `nominal_date` | Contractual due date before adjustment |
| `payment_date` | Business-day adjusted date |
| `days` | Days in the period under the chosen convention |
| `opening_balance` | Brought forward |
| `interest` | Interest charged in the period |
| `payment` | Amount due from the customer |
| `interest_paid` | Interest settled by this payment |
| `principal_repaid` | Principal settled by this payment |
| `interest_rolled` | Interest added to the balance (rolled only) |
| `interest_retained` | Interest met from the retention (retained only) |
| `closing_balance` | Carried forward |

The CSV file keeps raw values to two decimal places, with no currency symbols or thousand separators, so it loads cleanly into BigQuery or Excel.

## Path to Cloud Run

The Cloud Run function is a second thin shell over the same core, so moving to it is packaging work rather than a rebuild. What changes:

- **Entry point:** an HTTP handler (`functions-framework`) takes a JSON payload, builds a `LoanInputs` object, calls `generate_schedule`, and returns JSON (summary, validation results, schedule rows). A failed hard check returns HTTP 422 with the check details.
- **Input schema:** `LoanInputs` becomes a Pydantic model. Field-level validation and error messages then come for free, and the JSON schema can be published to callers.
- **Money as strings in JSON:** amounts go in and out as decimal strings (`"250000.00"`), so no float rounding happens in transit.
- **Bank holidays:** the holiday calendar is packaged with the service and refreshed on each release, with no live calls at request time. A startup check fails if the calendar ends before the latest possible maturity date.
- **Optional sinks:** write the schedule to BigQuery or GCS, keyed on `loan_id` and a hash of the inputs, so repeat calls are idempotent.

A few things stay the same, and are what make the move cheap:

- the core package is unchanged, with no web or cloud imports in it;
- the same golden test cases run against both the notebook and the function;
- the notebook's parameter cell maps one-to-one onto the JSON payload.

## Testing strategy

Three layers of tests: golden cases that match schedules signed off by the business, property tests that throw random loans at the validators, and unit tests for dates and day counts.

### Golden cases

Each case below is a fixed input with an expected schedule, built independently in a spreadsheet, signed off by the lending or finance team, and stored as CSV under `tests/golden/`.

| Case | What it proves |
| --- | --- |
| Amortising, 30E/360, regular periods | Instalment matches the closed-form annuity |
| Amortising, ACT/365, broken first period | Solver handles irregular periods |
| Amortising with balloon | Balloon left outstanding, instalment correct |
| Amortising, 25 years | V3 tolerance scales and passes on a long term |
| Interest-only, ACT/360 | Monthly interest plus bullet |
| Interest-only with `ROLLED`, 12 months | Monthly compounding and final settlement |
| Amortising with 6 months retained | Retention on gross balance and follow-on solve |
| Interest-only, retained for the full term | Whole-term retention with nothing due until maturity |
| Retention grossed up from net advance | Gross-up lands on the net figure to the penny |
| Payment falls on Christmas or Easter | Date moves forward, next period returns to the nominal date |
| Payment due on the last business day of a month that falls on a weekend | Modified following moves it back, not into the next month |
| Disbursement on the 31st | End-of-month and 30E/360 day-31 handling |
| Term crossing 29 February | Leap-year day counts under ACT/365 |
| With capitalised fees | EIR above the contractual rate, customer schedule unchanged |
| Same loan under each day count | EIR measured on the contractual basis |

### Property tests (Hypothesis)

These generate thousands of random valid loans (principal, rate, term, dates, structure) and assert that V1–V6 always pass. Any rounding or date edge case that slips through the golden set gets caught here.

### Unit tests

- `year_fraction` for each convention, against hand-worked examples.
- Business-day roll across weekends, Christmas, Boxing Day and substitute holidays.
- `round_penny` behaviour at exact half-pennies.

## Decisions and assumptions

### Decisions

| Topic | Decision |
| --- | --- |
| Solvers | `scipy.optimize.brentq` for the instalment, the retained gross-up and the EIR |
| Rolled interest | A parameter (`interest_treatment`), not a loan type; unpaid interest compounds monthly |
| Retained interest | A parameter (`retained_months`), not a loan type; supports gross-up from a net advance |
| V3 tolerance | Scales with each loan's rounding bound |
| Business-day rule | Modified following for weekends and bank holidays |
| EIR basis | Contractual day count only |
| Golden cases | No existing schedules to match; cases are built independently in a spreadsheet and signed off |

### Assumptions

- "30E/60" in the brief means 30E/360.
- Interest-only means monthly interest with the principal as a single bullet at maturity.
- Retained interest is calculated on the gross principal.
- Interest accrues to the adjusted payment date, not the nominal date.
- In v1, `ROLLED` applies only to interest-only loans.
