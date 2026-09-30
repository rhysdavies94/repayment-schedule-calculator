from decimal import Decimal

import pytest

from repayment_schedule import round_penny


@pytest.mark.parametrize(
    "amount, expected",
    [
        ("0.005", "0.01"),
        ("0.015", "0.02"),
        ("0.025", "0.03"),
        ("2.675", "2.68"),  # below the half as a float, exactly half as a Decimal
        ("1.004999", "1.00"),
        ("1.0050", "1.01"),
        ("-0.005", "-0.01"),
        ("100", "100.00"),
    ],
)
def test_round_penny_half_up(amount, expected):
    assert str(round_penny(Decimal(amount))) == expected
