"""The three brentq solves: level instalment, retained gross-up and EIR.

Floats are used only here. Callers pass float functions built from the real
period loop and convert results back to Decimal.
"""

from __future__ import annotations

from typing import Callable, Sequence

from scipy.optimize import brentq

XTOL = 1e-10


def solve_instalment(
    final_balance: Callable[[float], float], balloon: float, upper: float
) -> float:
    """Unrounded P with final_balance(P) == balloon, bracketed on [0, upper]."""
    return brentq(lambda p: final_balance(p) - balloon, 0.0, upper, xtol=XTOL)


def solve_gross_up(
    retained_interest: Callable[[float], float], net_advance: float, fees: float
) -> float:
    """Gross principal G with G - fees - retained_interest(G) == net_advance."""

    def f(g: float) -> float:
        return g - fees - retained_interest(g) - net_advance

    # G >= net + fees, and equals it at a 0% rate: step below so f(lower) < 0.
    lower = net_advance + fees - 1.0
    upper = 2 * (net_advance + fees)
    while f(upper) < 0:
        upper *= 2
        if upper > lower * 1e6:
            raise ValueError(
                "retained interest is at least as large as the gross principal; "
                "no gross principal gives this net advance"
            )
    return brentq(f, lower, upper, xtol=XTOL)


def npv(rate: float, cashflows: Sequence[tuple[float, float]]) -> float:
    return sum(amount / (1.0 + rate) ** t for t, amount in cashflows)


def solve_eir(cashflows: Sequence[tuple[float, float]]) -> float:
    """Annual rate r with sum(amount / (1 + r) ** t) == 0; t in years."""
    lower, upper = -0.9, 1.0
    while npv(upper, cashflows) > 0:
        upper *= 2
        if upper > 1e6:
            raise ValueError("EIR not found: NPV stays positive at very high rates")
    while npv(lower, cashflows) < 0:
        lower = (lower - 1.0) / 2  # halve the distance to -100%
        if lower < -1 + 1e-9:
            raise ValueError("EIR not found: NPV stays negative at very low rates")
    return brentq(lambda r: npv(r, cashflows), lower, upper, xtol=1e-12)
