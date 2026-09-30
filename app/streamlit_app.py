"""Loan schedule explorer: a Streamlit shell over the repayment_schedule core.

Two modes:
- Golden scenarios: browse the signed-off test cases in tests/golden/.
- Build your own: enter any loan (or start from a golden case) and see its
  schedule recalculated live. The URL carries the inputs, so it can be shared.

Run locally:   uv run streamlit run app/streamlit_app.py
Deploy:        Streamlit Community Cloud, entrypoint app/streamlit_app.py
               (dependencies come from app/requirements.txt).
"""

from __future__ import annotations

import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # the core package lives at the repo root

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from repayment_schedule import (  # noqa: E402
    InputError,
    LoanInputs,
    ScheduleResult,
    generate_schedule,
)
from repayment_schedule.dates import add_months  # noqa: E402
from repayment_schedule.export import (  # noqa: E402
    MONEY_COLUMNS,
    checks_dataframe,
    csv_filename,
    csv_text,
    schedule_dataframe,
    summary_dataframe,
)
from repayment_schedule.golden import GoldenCase, compare, list_cases, load_case  # noqa: E402

st.set_page_config(page_title="Loan schedule explorer", page_icon="📅", layout="wide")

GOLDEN, CUSTOM = "Golden scenarios", "Build your own"
GROSS, NET = "Gross principal", "Net advance"
DAY_COUNT_LABELS = {"ACT_365": "Actual/365 Fixed", "ACT_360": "Actual/360", "30E_360": "30E/360"}
STRUCTURE_LABELS = {"AMORTISING": "Amortising (capital and interest)",
                    "INTEREST_ONLY": "Interest-only (bullet)"}
TREATMENT_LABELS = {"PAID": "Paid monthly", "ROLLED": "Rolled up (compounds monthly)"}

CASES = list_cases()


def case_label(name: str) -> str:
    number, _, rest = name.partition("_")
    return f"{number} · {rest.replace('_', ' ').capitalize()}"


# --- Running the engine ------------------------------------------------------

@st.cache_data(show_spinner=False)
def run_case(name: str) -> tuple[GoldenCase, ScheduleResult | None, str | None]:
    case = load_case(name)
    result, error = run_params(tuple(case.params.items()))
    return case, result, error


@st.cache_data(show_spinner=False, max_entries=500)
def run_params(items: tuple) -> tuple[ScheduleResult | None, str | None]:
    """Run one loan. Takes a tuple of (field, value) so it can be cached."""
    try:
        return generate_schedule(LoanInputs(**dict(items)), raise_on_failure=False), None
    except InputError as err:
        return None, str(err).removeprefix("Invalid loan inputs: ")
    except ValueError as err:  # e.g. no gross principal gives the requested net advance
        return None, str(err)


# --- Build-your-own form state -------------------------------------------------
# Widgets are keyed "f_<name>". Values live in session state, so they can be
# prefilled from a golden case or from the URL before the widgets are drawn.

def blank_form() -> dict:
    disbursement = date.today()
    return {
        "f_loan_id": "MY-LOAN",
        "f_basis": GROSS,
        "f_amount": 100_000.00,
        "f_rate_pct": 8.95,
        "f_day_count": "ACT_365",
        "f_structure": "AMORTISING",
        "f_treatment": "PAID",
        "f_retained": 0,
        "f_disbursement": disbursement,
        "f_first_payment": add_months(disbursement, 1, disbursement.day),
        "f_term": 60,
        "f_balloon": 0.0,
        "f_fees": 0.0,
    }


def params_to_form(params: dict) -> dict:
    """Golden-case (or URL) params -> form state, filling gaps from the blank form."""
    form = blank_form()
    basis = NET if params.get("net_advance") not in (None, "") else GROSS
    amount = params.get("net_advance") if basis == NET else params.get("principal")
    form.update({
        "f_loan_id": params.get("loan_id") or "",
        "f_basis": basis,
        "f_amount": float(amount or form["f_amount"]),
        "f_rate_pct": float(Decimal(str(params.get("annual_rate", "0.0895"))) * 100),
        "f_day_count": params.get("day_count", "ACT_365"),
        "f_structure": params.get("structure", "AMORTISING"),
        "f_treatment": params.get("interest_treatment", "PAID"),
        "f_retained": int(params.get("retained_months", 0)),
        "f_term": int(params.get("term_months", 60)),
        "f_balloon": float(params.get("balloon_amount", 0) or 0),
        "f_fees": float(params.get("capitalised_fees", 0) or 0),
    })
    for key, field in (("f_disbursement", "disbursement_date"),
                       ("f_first_payment", "first_payment_date")):
        if params.get(field):
            form[key] = date.fromisoformat(str(params[field]))
    return form


def _money(x: float) -> str:
    return f"{x:.2f}"


def form_to_params(state) -> dict:
    """Form state -> LoanInputs fields (money as exact strings)."""
    amortising = state.f_structure == "AMORTISING"
    net = state.f_basis == NET and state.f_retained > 0
    params = {
        "loan_id": state.f_loan_id.strip() or None,
        "principal": None if net else _money(state.f_amount),
        "net_advance": _money(state.f_amount) if net else None,
        "annual_rate": str((Decimal(str(state.f_rate_pct)) / 100).normalize()),
        "day_count": state.f_day_count,
        "structure": state.f_structure,
        "interest_treatment": "PAID" if amortising else state.f_treatment,
        "retained_months": int(state.f_retained),
        "disbursement_date": state.f_disbursement.isoformat(),
        "first_payment_date": state.f_first_payment.isoformat(),
        "term_months": int(state.f_term),
        "balloon_amount": _money(state.f_balloon) if amortising else "0.00",
        "capitalised_fees": _money(state.f_fees),
    }
    return {k: v for k, v in params.items() if v is not None}


def load_form(params: dict | None) -> None:
    for key, value in (params_to_form(params) if params else blank_form()).items():
        st.session_state[key] = value


# --- First load: restore mode, case or custom loan from the URL ---------------

if "mode" not in st.session_state:
    qp = st.query_params
    st.session_state.mode = CUSTOM if qp.get("mode") == "custom" else GOLDEN
    st.session_state.case = qp.get("case") if qp.get("case") in CASES else CASES[0]
    load_form({k: v for k, v in qp.items() if k != "mode"} if qp.get("mode") == "custom" else None)
    st.session_state.start_from = ""

# Streamlit drops a widget's state when it is not drawn (hidden fields, or the
# whole form in golden mode). Re-saving the keys each run keeps them.
for _key in blank_form():
    if _key in st.session_state:
        st.session_state[_key] = st.session_state[_key]


# --- Callbacks ------------------------------------------------------------------

def step(offset: int) -> None:
    i = CASES.index(st.session_state.case)
    st.session_state.case = CASES[(i + offset) % len(CASES)]


def customise_case() -> None:
    load_form(load_case(st.session_state.case).params)
    st.session_state.mode = CUSTOM


def start_from_changed() -> None:
    choice = st.session_state.start_from
    load_form(load_case(choice).params if choice else None)


def disbursement_changed() -> None:
    """Keep the first payment a month after disbursement unless the user has set it later."""
    d = st.session_state.f_disbursement
    if st.session_state.f_first_payment <= d:
        st.session_state.f_first_payment = add_months(d, 1, d.day)


# --- Result view (shared by both modes) ----------------------------------------

def money(value) -> str:
    return "n/a" if value is None else f"£{value:,.2f}"


def display_schedule(result: ScheduleResult) -> pd.DataFrame:
    """Floats for on-screen display only; the CSV download keeps exact Decimals."""
    df = schedule_dataframe(result)
    for col in MONEY_COLUMNS:
        df[col] = df[col].astype(float)
    return df


def params_table(params: dict) -> pd.DataFrame:
    return pd.DataFrame([(k, "" if v is None else str(v)) for k, v in params.items()],
                        columns=["field", "value"])


def show_result(result: ScheduleResult, params: dict, badges: list[str],
                golden: GoldenCase | None = None, diffs: list[str] | None = None) -> None:
    badges = [":green-badge[Hard checks pass]" if result.passed
              else ":red-badge[Hard check failed]", *badges]
    if result.warnings:
        badges.append(f":orange-badge[{len(result.warnings)} warning(s)]")
    st.markdown(" ".join(badges))

    s = result.summary
    cols = st.columns(5)
    cols[0].metric("Principal", money(s.principal))
    cols[1].metric("Level instalment", money(s.level_instalment))
    cols[2].metric("Total interest", money(s.total_interest))
    cols[3].metric("EIR (annual)", f"{s.eir_annual * 100:.4f}%")
    cols[4].metric("Final-payment adjustment", money(s.final_payment_adjustment),
                   help=f"V3 tolerance £{s.v3_tolerance}")

    for warning in result.warnings:
        st.warning(warning)
    if not result.passed:
        st.error("A hard validation check failed, so the schedule is not shown or exported. "
                 "See the Validation tab for the figures.")

    names = ["Summary", "Validation", "Schedule", "Inputs"]
    if golden is not None:
        names.append("Golden comparison")
    tabs = dict(zip(names, st.tabs(names)))

    with tabs["Summary"]:
        summary = summary_dataframe(result).reset_index()
        summary["value"] = summary["value"].astype(str)
        st.dataframe(summary, hide_index=True, width="content")

    with tabs["Validation"]:
        colours = {"PASS": "green", "FAIL": "red", "WARN": "orange"}
        st.dataframe(
            checks_dataframe(result).reset_index().style.map(
                lambda v: f"color: {colours.get(v, 'inherit')}; font-weight: 600",
                subset=["result"]),
            hide_index=True,
            width="stretch",
        )

    with tabs["Schedule"]:
        if result.passed:
            st.dataframe(
                display_schedule(result),
                hide_index=True,
                width="stretch",
                column_config={c: st.column_config.NumberColumn(format="%.2f")
                               for c in MONEY_COLUMNS},
            )
            st.download_button("Download schedule CSV", data=csv_text(result),
                               file_name=csv_filename(result), mime="text/csv",
                               icon=":material/download:")
        else:
            st.info("Withheld: a hard validation check failed.")

    with tabs["Inputs"]:
        st.dataframe(params_table(params), hide_index=True)
        st.download_button(
            "Download inputs as golden-case input.json",
            data=json.dumps({"proves": "", "params": params}, indent=2) + "\n",
            file_name="input.json",
            mime="application/json",
            icon=":material/data_object:",
            help="Save under tests/golden/<case>/ with the expected outputs to add a golden case.",
        )

    if golden is not None:
        with tabs["Golden comparison"]:
            if diffs is None:
                st.info(
                    "Expected outputs are placeholders. Fill `expected_schedule.csv` and "
                    f"`expected_summary.json` in `tests/golden/{golden.name}/` from the signed-off "
                    'spreadsheet and set `"status": "SIGNED_OFF"` to compare here.'
                )
            elif not diffs:
                st.success("Matches the signed-off schedule and summary to the penny.")
            else:
                st.error(f"{len(diffs)} differences from the signed-off outputs")
                st.dataframe(pd.DataFrame({"difference": diffs}), hide_index=True,
                             width="stretch")


# --- Sidebar ----------------------------------------------------------------------

with st.sidebar:
    st.radio("Mode", [GOLDEN, CUSTOM], key="mode", horizontal=True,
             label_visibility="collapsed")

    if st.session_state.mode == GOLDEN:
        st.header("Scenario")
        st.selectbox("Golden case", CASES, format_func=case_label, key="case",
                     label_visibility="collapsed")
        left, right = st.columns(2)
        left.button("◀ Previous", on_click=step, args=(-1,), width="stretch")
        right.button("Next ▶", on_click=step, args=(1,), width="stretch")
        st.button("Customise this scenario", on_click=customise_case, width="stretch",
                  icon=":material/tune:",
                  help="Copy this case's inputs into Build your own and edit them.")
        st.caption(f"{len(CASES)} golden cases from `tests/golden/`, each run through "
                   "the engine with V1–V7 validation.")
    else:
        st.header("Your loan")
        st.selectbox("Start from", ["", *CASES], key="start_from", on_change=start_from_changed,
                     format_func=lambda n: case_label(n) if n else "Blank loan",
                     help="Prefill the form from a golden case, then edit it.")
        state = st.session_state
        st.text_input("Loan ID", key="f_loan_id")
        st.selectbox("Structure", list(STRUCTURE_LABELS), key="f_structure",
                     format_func=STRUCTURE_LABELS.get)
        if state.f_structure == "INTEREST_ONLY":
            st.selectbox("Interest", list(TREATMENT_LABELS), key="f_treatment",
                         format_func=TREATMENT_LABELS.get)
        st.number_input("Term (months)", key="f_term", min_value=1, max_value=600, step=1)
        st.number_input("Retained months", key="f_retained", min_value=0, max_value=600, step=1,
                        help="Months of interest retained from the advance at disbursement.")
        if state.f_retained > 0:
            st.radio("Amount entered as", [GROSS, NET], key="f_basis", horizontal=True,
                     help="With retention you can enter the net cash advanced and the engine "
                          "grosses it up.")
        amount_label = "Net advance (£)" if state.f_basis == NET and state.f_retained > 0 \
            else "Gross principal (£)"
        st.number_input(amount_label, key="f_amount", min_value=0.0, step=1000.0, format="%.2f")
        st.number_input("Annual rate (%)", key="f_rate_pct", min_value=0.0, max_value=100.0,
                        step=0.05, format="%.4f")
        st.selectbox("Day count", list(DAY_COUNT_LABELS), key="f_day_count",
                     format_func=DAY_COUNT_LABELS.get)
        st.date_input("Disbursement date", key="f_disbursement", on_change=disbursement_changed,
                      min_value=date(2000, 1, 1), max_value=date(2100, 12, 31), format="DD/MM/YYYY")
        st.date_input("First payment date", key="f_first_payment",
                      min_value=date(2000, 1, 1), max_value=date(2100, 12, 31), format="DD/MM/YYYY",
                      help="Sets the payment day of the month.")
        if state.f_structure == "AMORTISING":
            st.number_input("Balloon (£)", key="f_balloon", min_value=0.0, step=1000.0,
                            format="%.2f")
        st.number_input("Capitalised fees (£)", key="f_fees", min_value=0.0, step=100.0,
                        format="%.2f", help="Included in the principal. Used only for the EIR.")
        st.button("Reset to blank loan", on_click=load_form, args=(None,), width="stretch")


# --- Main area ----------------------------------------------------------------------

if st.session_state.mode == GOLDEN:
    st.query_params.from_dict({"case": st.session_state.case})
    case, result, input_error = run_case(st.session_state.case)
    st.title(case_label(case.name))
    st.markdown(f"**What it proves:** {case.proves}")
    if input_error:
        st.error(f"Input error: {input_error}")
        st.dataframe(params_table(case.params), hide_index=True)
    else:
        diffs = compare(result, case) if case.signed_off else None
        golden_badge = (":gray-badge[Awaiting sign-off]" if diffs is None
                        else f":red-badge[Golden: {len(diffs)} differences]" if diffs
                        else ":green-badge[Golden match]")
        show_result(result, case.params, [golden_badge], golden=case, diffs=diffs)
else:
    params = form_to_params(st.session_state)
    st.query_params.from_dict({"mode": "custom", **params})
    st.title(params.get("loan_id") or "Your loan")
    st.markdown("Edit the loan in the sidebar; the schedule recalculates as you go. "
                "**The page URL holds these inputs, so you can share it.**")
    result, input_error = run_params(tuple(params.items()))
    if input_error:
        st.error("**Check the inputs:**\n\n" + "\n".join(
            f"- {msg}" for msg in input_error.split("; ")))
    else:
        show_result(result, params, [":blue-badge[Custom loan]"])
