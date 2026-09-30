"""The Streamlit explorer: golden scenarios and build-your-own loans."""

from pathlib import Path

import pytest

from repayment_schedule.golden import list_cases, load_case

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")
CASES = list_cases()


def _app(**query) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30)
    for key, value in query.items():
        at.query_params[key] = value
    return at.run()


def _markdown(at) -> str:
    return "\n".join(m.value for m in at.markdown)


def _metric(at, label):
    return next(m.value for m in at.metric if m.label == label)


# --- Golden scenarios --------------------------------------------------------------

def test_opens_on_first_golden_case():
    at = _app()
    assert not at.exception
    assert at.session_state.mode == "Golden scenarios"
    assert at.session_state.case == CASES[0]
    assert "What it proves" in _markdown(at)
    assert [t.label for t in at.tabs] == [
        "Summary", "Validation", "Schedule", "Inputs", "Golden comparison"
    ]


@pytest.mark.parametrize("case", CASES)
def test_every_golden_case_renders(case):
    at = _app()
    at.selectbox(key="case").select(case).run()
    assert not at.exception, at.exception
    assert not at.error
    assert "Hard checks pass" in _markdown(at)
    assert "Awaiting sign-off" in _markdown(at)


def test_previous_and_next_buttons_wrap():
    at = _app()
    next_button = next(b for b in at.button if b.label == "Next ▶")
    next_button.click().run()
    assert at.session_state.case == CASES[1]
    prev_button = next(b for b in at.button if b.label == "◀ Previous")
    prev_button.click().run()
    prev_button.click().run()
    assert at.session_state.case == CASES[-1]


def test_projected_calendar_warning_shown_for_long_loans():
    at = _app()
    at.selectbox(key="case").select("04_amortising_25_years").run()
    assert any("projected" in w.value for w in at.warning)


def test_golden_case_link():
    at = _app(case="05_interest_only_act360")
    assert at.session_state.case == "05_interest_only_act360"


# --- Build your own ----------------------------------------------------------------

def _custom() -> AppTest:
    at = _app()
    at.radio(key="mode").set_value("Build your own").run()
    assert not at.exception
    return at


def test_blank_custom_loan_calculates():
    at = _custom()
    assert "Custom loan" in _markdown(at)
    assert "Hard checks pass" in _markdown(at)
    assert _metric(at, "Principal") == "£100,000.00"
    assert [t.label for t in at.tabs] == ["Summary", "Validation", "Schedule", "Inputs"]


def test_edits_recalculate():
    at = _custom()
    before = _metric(at, "Level instalment")
    at.number_input(key="f_rate_pct").set_value(12.5).run()
    after = _metric(at, "Level instalment")
    assert after != before
    at.number_input(key="f_term").set_value(12).run()
    assert "Hard checks pass" in _markdown(at)


def test_interest_only_rolled_with_retention_and_net_advance():
    at = _custom()
    at.selectbox(key="f_structure").set_value("INTEREST_ONLY").run()
    at.selectbox(key="f_treatment").set_value("ROLLED").run()
    at.number_input(key="f_term").set_value(12).run()
    at.number_input(key="f_retained").set_value(6).run()
    at.radio(key="f_basis").set_value("Net advance").run()
    at.number_input(key="f_amount").set_value(250000.0).run()
    assert not at.exception and not at.error
    assert _metric(at, "Level instalment") == "n/a"
    net = next(r for r in at.dataframe[0].value.itertuples() if r.item == "Net advance")
    assert net.value == "250000.00"


def test_invalid_inputs_show_plain_errors():
    at = _custom()
    at.number_input(key="f_amount").set_value(0.0).run()
    assert at.error and "principal must be greater than 0" in at.error[0].value
    assert not at.exception


def test_customise_golden_case_prefills_form():
    at = _app()
    at.selectbox(key="case").select("03_amortising_balloon").run()
    next(b for b in at.button if b.label == "Customise this scenario").click().run()
    assert at.session_state.mode == "Build your own"
    assert at.session_state.f_balloon == 80000.0
    assert at.session_state.f_term == 84
    assert "Hard checks pass" in _markdown(at)


def test_start_from_golden_case():
    at = _custom()
    at.selectbox(key="start_from").set_value("06_interest_only_rolled_12m").run()
    params = load_case("06_interest_only_rolled_12m").params
    assert at.session_state.f_structure == "INTEREST_ONLY"
    assert at.session_state.f_treatment == "ROLLED"
    assert at.session_state.f_amount == float(params["principal"])


def test_hidden_fields_survive_mode_switches():
    at = _custom()
    at.number_input(key="f_balloon").set_value(20000.0).run()
    at.radio(key="mode").set_value("Golden scenarios").run()
    at.radio(key="mode").set_value("Build your own").run()
    assert at.session_state.f_balloon == 20000.0


def test_custom_loan_link_round_trip():
    at = _custom()
    at.number_input(key="f_rate_pct").set_value(7.25).run()
    at.number_input(key="f_term").set_value(36).run()
    link = {k: at.query_params[k][0] if isinstance(at.query_params[k], list)
            else at.query_params[k] for k in at.query_params}
    assert link["mode"] == "custom" and link["annual_rate"] == "0.0725"

    shared = _app(**link)
    assert shared.session_state.mode == "Build your own"
    assert shared.session_state.f_term == 36
    assert _metric(shared, "Level instalment") == _metric(at, "Level instalment")
