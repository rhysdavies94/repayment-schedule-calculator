"""Hypothesis: random valid loans always pass the hard checks V1 to V6."""

from datetime import date, timedelta
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from repayment_schedule import LoanInputs, generate_schedule

SETTINGS = settings(max_examples=1000, deadline=None,
                    suppress_health_check=[HealthCheck.too_slow])

pennies = st.integers(min_value=100_000, max_value=500_000_000).map(lambda p: Decimal(p) / 100)
rates = st.integers(min_value=0, max_value=2500).map(lambda bp: Decimal(bp) / 10000)
day_counts = st.sampled_from(["ACT_365", "ACT_360", "30E_360"])
disbursements = st.dates(min_value=date(2019, 1, 1), max_value=date(2035, 12, 31))


@st.composite
def loans(draw):
    structure, treatment = draw(
        st.sampled_from(
            [("AMORTISING", "PAID"), ("INTEREST_ONLY", "PAID"), ("INTEREST_ONLY", "ROLLED")]
        )
    )
    term = draw(st.integers(min_value=1, max_value=360))
    disbursement = draw(disbursements)
    first_payment = disbursement + timedelta(days=draw(st.integers(min_value=5, max_value=62)))
    principal = draw(pennies)

    max_retained = term - 1 if structure == "AMORTISING" else term
    retained = draw(st.one_of(st.just(0), st.integers(min_value=0, max_value=min(max_retained, 24))))
    balloon = Decimal("0")
    if structure == "AMORTISING" and draw(st.booleans()):
        balloon = (principal * Decimal(draw(st.integers(1, 60))) / 100).quantize(Decimal("0.01"))
    fees = (principal * Decimal(draw(st.integers(0, 5))) / 100).quantize(Decimal("0.01"))

    return dict(
        loan_id="H",
        principal=principal,
        annual_rate=draw(rates),
        day_count=draw(day_counts),
        structure=structure,
        interest_treatment=treatment,
        retained_months=retained,
        disbursement_date=disbursement,
        first_payment_date=first_payment,
        term_months=term,
        balloon_amount=balloon,
        capitalised_fees=fees,
    )


def _hard_checks(result):
    return {c.code: c for c in result.checks if c.severity == "HARD"}


@SETTINGS
@given(loans())
def test_random_loans_pass_hard_checks(params):
    result = generate_schedule(LoanInputs(**params), raise_on_failure=False)
    failed = {code: c.detail for code, c in _hard_checks(result).items() if not c.passed}
    assert not failed, failed
    assert set(_hard_checks(result)) == {"V1", "V2", "V3", "V4", "V5", "V6"}


@settings(max_examples=300, deadline=None)
@given(
    net=st.integers(min_value=100_000, max_value=300_000_000).map(lambda p: Decimal(p) / 100),
    rate=rates,
    retained=st.integers(min_value=1, max_value=18),
    extra=st.integers(min_value=0, max_value=24),
    day_count=day_counts,
    disbursement=disbursements,
    fee_pct=st.integers(0, 3),
)
def test_gross_up_hits_net_advance_exactly(net, rate, retained, extra, day_count, disbursement,
                                           fee_pct):
    fees = (net * fee_pct / 100).quantize(Decimal("0.01"))
    result = generate_schedule(
        LoanInputs(
            net_advance=net,
            annual_rate=rate,
            day_count=day_count,
            structure="INTEREST_ONLY",
            retained_months=retained,
            disbursement_date=disbursement,
            first_payment_date=disbursement + timedelta(days=30),
            term_months=retained + extra,
            capitalised_fees=fees,
        )
    )
    assert result.summary.net_advance == net
