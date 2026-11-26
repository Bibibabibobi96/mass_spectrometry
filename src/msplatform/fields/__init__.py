"""Declared static analytic fields for the reference particle tracer."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray


class FieldProvider(Protocol):
    """A field evaluated in a declared frame and experiment-relative seconds."""
    capabilities: dict[str, object]

    def sample(self, position_m: NDArray[np.float64], time_s: float) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Return E (V/m), B (T); an absent field is not an implicit zero."""
        ...


@dataclass(frozen=True)
class UniformField:
    """Spatially unbounded, prescribed and static uniform electric and magnetic fields."""
    electric_field_v_m: NDArray[np.float64]
    magnetic_field_t: NDArray[np.float64]

    @property
    def capabilities(self) -> dict[str, object]:
        return {"representation": "uniform", "electric": True, "magnetic": True,
                "time_dependence": "static", "coupling": "prescribed", "domain": "unbounded"}

    def sample(self, position_m: NDArray[np.float64], time_s: float) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Return the declared static field vectors in SI units."""
        return self.electric_field_v_m, self.magnetic_field_t
