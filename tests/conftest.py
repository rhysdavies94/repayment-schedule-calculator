from repayment_schedule import LoanInputs

BASE = dict(
    loan_id="T1",
    principal="100000.00",
    annual_rate="0.09",
    day_count="ACT_365",
    structure="AMORTISING",
    disbursement_date="2026-10-15",
    first_payment_date="2026-11-15",
    term_months=60,
)


def make_inputs(**overrides) -> LoanInputs:
    """BASE loan with overrides; an override of None removes the field."""
    params = {**BASE, **overrides}
    return LoanInputs(**{k: v for k, v in params.items() if v is not None})
