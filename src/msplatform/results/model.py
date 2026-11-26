"""Solver-neutral in-memory SI tracing result shared by numerical adapters."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class TraceResult:
    """Separate original cohort, measured terminal/events and sampled SI states."""
    initial_states: list[dict[str, Any]]
    terminal_states: list[dict[str, Any]]
    events: list[dict[str, Any]]
    trajectories: dict[str, np.ndarray]
    execution_status: str
    data_integrity: dict[str, Any]
