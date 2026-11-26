"""Versioned physical data used by the reference tracing workflow."""

from .reference import CONSTANTS, GasEnvironment
from decimal import Decimal, localcontext
import math

__all__ = ["CONSTANTS", "GasEnvironment", "normalize_charge_c"]


def normalize_charge_c(charge_state: int, charge_c: float | Decimal | int) -> float:
    """Validate charge against the frozen constant and return its canonical binary64 value.

    Accept precisely binary64 multiplication or exact decimal multiplication
    rounded once to binary64. No numerical tolerance or alternate constant is used.
    """
    if type(charge_state) is not int or charge_state == 0 or not -(2**63) <= charge_state < 2**63:
        raise ValueError("charge_state must be a nonzero signed int64")
    if isinstance(charge_c, bool) or not isinstance(charge_c, (int, float, Decimal)):
        raise ValueError("charge_c must be finite and numeric")
    value = float(charge_c)
    if not math.isfinite(value):
        raise ValueError("charge_c must be finite and numeric")
    canonical = charge_state * CONSTANTS["elementary_charge_c"]
    with localcontext() as context:
        context.prec = 50
        decimal_product = float(Decimal(charge_state) * Decimal(str(CONSTANTS["elementary_charge_c"])))
    if value != canonical and value != decimal_product:
        raise ValueError("charge_c disagrees with charge_state and constants")
    return canonical
