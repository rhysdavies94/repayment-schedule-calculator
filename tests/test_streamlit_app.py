"""The Streamlit scenario explorer runs every golden case and its controls work."""

from pathlib import Path

import pytest

from repayment_schedule.golden import list_cases

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")
CASES = list_cases()


def _app() -> AppTest:
    return AppTest.from_file(APP, default_timeout=30).run()


def test_opens_on_first_case():
    at = _app()
    assert not at.exception
    assert at.session_state.case == CASES[0]
    assert "What it proves" in at.markdown[0].value
    assert [t.label for t in at.tabs] == [
        "Summary", "Validation", "Schedule", "Inputs", "Golden comparison"
    ]


@pytest.mark.parametrize("case", CASES)
def test_every_case_renders(case):
    at = _app()
    at.selectbox[0].select(case).run()
    assert not at.exception, at.exception
    assert not at.error
    assert any("Hard checks pass" in m.value for m in at.markdown)
    assert any("Awaiting sign-off" in m.value for m in at.markdown)


def test_previous_and_next_buttons_wrap():
    at = _app()
    at.button[1].click().run()  # Next
    assert at.session_state.case == CASES[1]
    at.button[0].click().run()  # Previous
    at.button[0].click().run()
    assert at.session_state.case == CASES[-1]
    assert not at.exception


def test_projected_calendar_warning_shown_for_long_loans():
    at = _app()
    at.selectbox[0].select("04_amortising_25_years").run()
    assert any("projected" in w.value for w in at.warning)
