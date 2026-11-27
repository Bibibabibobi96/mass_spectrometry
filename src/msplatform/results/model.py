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


def merge_trace_batches(results: list[dict[str, Any]]) -> TraceResult:
    status = "succeeded"
    if any(row["execution_status"] == "failed" for row in results):
        status = "failed"
    elif any(row["execution_status"] == "cancelled" for row in results):
        status = "cancelled"
    from msplatform.results.detector_observation import merge_detector_observations
    coverage = merge_detector_observations([(row["initial_states"], row["data_integrity"]) for row in results])
    return TraceResult(
        initial_states=[p for r in results for p in r["initial_states"]],
        terminal_states=[p for r in results for p in r["terminal_states"]],
        events=[p for r in results for p in r["events"]],
        trajectories={name: np.concatenate([r["trajectories"][name] for r in results], axis=0)
                      for name in ("particle_id", "time_s", "position_m", "velocity_m_s")},
        execution_status=status,
        data_integrity={"status": "complete" if all(r["data_integrity"].get("status") == "complete" for r in results)
                        else "incomplete", "batch_integrity": [r["data_integrity"] for r in results],
                        "detector_observation": coverage},
    )
