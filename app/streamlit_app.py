"""Golden scenario explorer: a Streamlit shell over the repayment_schedule core.

Run locally:   uv run --group app streamlit run app/streamlit_app.py
Deploy:        Streamlit Community Cloud, entrypoint app/streamlit_app.py
               (dependencies come from app/requirements.txt).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # the core package lives at the repo root

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from repayment_schedule import InputError, LoanInputs, ScheduleResult, generate_schedule  # noqa: E402
from repayment_schedule.export import (  # noqa: E402
    MONEY_COLUMNS,
    checks_dataframe,
    csv_filename,
    csv_text,
    schedule_dataframe,
    summary_dataframe,
)
from repayment_schedule.golden import GoldenCase, compare, list_cases, load_case  # noqa: E402

st.set_page_config(page_title="Golden scenario explorer", page_icon="📅", layout="wide")


def case_label(name: str) -> str:
    number, _, rest = name.partition("_")
    return f"{number} · {rest.replace('_', ' ').capitalize()}"


@st.cache_data(show_spinner=False)
def run_case(name: str) -> tuple[GoldenCase, ScheduleResult | None, str | None]:
    """Load a golden case and run it. Cached: results are deterministic."""
    case = load_case(name)
    try:
        return case, generate_schedule(LoanInputs(**case.params), raise_on_failure=False), None
    except InputError as err:
        return case, None, str(err)


def money(value) -> str:
    return "n/a" if value is None else f"£{value:,.2f}"


def display_schedule(result: ScheduleResult) -> pd.DataFrame:
    """Floats for on-screen display only; the CSV download keeps exact Decimals."""
    df = schedule_dataframe(result)
    for col in MONEY_COLUMNS:
        df[col] = df[col].astype(float)
    return df


# --- Scenario selection ------------------------------------------------------

cases = list_cases()
if "case" not in st.session_state or st.session_state.case not in cases:
    st.session_state.case = cases[0]


def step(offset: int) -> None:
    i = cases.index(st.session_state.case)
    st.session_state.case = cases[(i + offset) % len(cases)]


with st.sidebar:
    st.header("Scenario")
    st.selectbox("Golden case", cases, format_func=case_label, key="case",
                 label_visibility="collapsed")
    left, right = st.columns(2)
    left.button("◀ Previous", on_click=step, args=(-1,), width="stretch")
    right.button("Next ▶", on_click=step, args=(1,), width="stretch")
    st.caption(
        f"{len(cases)} golden cases from `tests/golden/`. Each runs through the same "
        "engine as the notebook, with V1–V7 validation."
    )

case, result, input_error = run_case(st.session_state.case)

# --- Header -----------------------------------------------------------------

st.title(case_label(case.name))
st.markdown(f"**What it proves:** {case.proves}")

if input_error:
    st.error(f"Input error: {input_error}")
    st.dataframe(pd.DataFrame(case.params.items(), columns=["field", "value"]),
                 hide_index=True)
    st.stop()

diffs = compare(result, case) if case.signed_off else None
badges = [":green-badge[Hard checks pass]" if result.passed else ":red-badge[Hard check failed]"]
if diffs is None:
    badges.append(":gray-badge[Awaiting sign-off]")
elif diffs:
    badges.append(f":red-badge[Golden: {len(diffs)} differences]")
else:
    badges.append(":green-badge[Golden match]")
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

# --- Tabs -------------------------------------------------------------------

summary_tab, checks_tab, schedule_tab, inputs_tab, golden_tab = st.tabs(
    ["Summary", "Validation", "Schedule", "Inputs", "Golden comparison"]
)

with summary_tab:
    summary = summary_dataframe(result).reset_index()
    summary["value"] = summary["value"].astype(str)
    st.dataframe(summary, hide_index=True, width="content")

with checks_tab:
    checks = checks_dataframe(result).reset_index()
    colours = {"PASS": "green", "FAIL": "red", "WARN": "orange"}
    st.dataframe(
        checks.style.map(lambda v: f"color: {colours.get(v, 'inherit')}; font-weight: 600",
                         subset=["result"]),
        hide_index=True,
        width="stretch",
    )

with schedule_tab:
    st.dataframe(
        display_schedule(result),
        hide_index=True,
        width="stretch",
        column_config={col: st.column_config.NumberColumn(format="%.2f") for col in MONEY_COLUMNS},
    )
    st.download_button(
        "Download CSV",
        data=csv_text(result),
        file_name=csv_filename(result),
        mime="text/csv",
        icon=":material/download:",
    )

with inputs_tab:
    st.dataframe(
        pd.DataFrame([(k, "" if v is None else str(v)) for k, v in case.params.items()],
                     columns=["field", "value"]),
        hide_index=True,
    )

with golden_tab:
    if diffs is None:
        st.info(
            "Expected outputs are placeholders. Fill `expected_schedule.csv` and "
            f"`expected_summary.json` in `tests/golden/{case.name}/` from the signed-off "
            'spreadsheet and set `"status": "SIGNED_OFF"` to compare here.'
        )
    elif not diffs:
        st.success("Matches the signed-off schedule and summary to the penny.")
    else:
        st.error(f"{len(diffs)} differences from the signed-off outputs")
        st.dataframe(pd.DataFrame({"difference": diffs}), hide_index=True,
                     width="stretch")
