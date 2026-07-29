"""Validate the topology-free pulse-capture numerical contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = PROJECT_ROOT / "config" / "rf_to_oatof_pulse_capture.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    """Return the validated pulse-only contract."""
    contract = _load(path)
    if (
        contract.get("schema_version") != 1
        or contract.get("role") != "rf_to_oatof_pulse_capture"
        or contract.get("phase") != "pulse_capture"
        or contract.get("topology_source") != "resolved_connection"
    ):
        raise ValueError("pulse-capture contract identity differs")
    if set(contract) != {
        "schema_version",
        "role",
        "status",
        "phase",
        "topology_source",
        "inputs",
        "waveform",
        "runtime",
        "permissions",
    }:
        raise ValueError("pulse-capture contract contains duplicate authority")
    waveform = contract["waveform"]
    if waveform != {
        "pre_pulse_oatof_field_scale": 0.0,
        "pulse_oatof_field_scale": 1.0,
        "post_pulse_oatof_field_scale": 0.0,
        "rise_fall_model": "ideal_finite_step",
        "post_pulse_tracking_time_us": 8.0,
    }:
        raise ValueError("pulse-capture zero-physics-change waveform differs")
    runtime = contract["runtime"]
    if (
        runtime.get("dense_trajectories_saved") is not False
        or int(runtime.get("minimum_active_at_pulse", 0)) < 1
        or int(runtime.get("minimum_local_accelerator_exit", 0)) < 1
        or runtime.get("detector_tracking_included") is not False
    ):
        raise ValueError("pulse-capture runtime boundary differs")
    permissions = contract["permissions"]
    if (
        permissions.get("schedule_derivation_allowed") is not True
        or permissions.get("nominal_particle_runtime_allowed") is not True
        or permissions.get("downstream_handoff_allowed_after_local_exit_audit")
        is not True
        or permissions.get("phase_pass_allowed") is not False
        or permissions.get("formal_promotion_allowed") is not False
    ):
        raise ValueError("pulse-capture qualification boundary differs")
    inputs = contract["inputs"]
    for relative in inputs.values():
        if not (PROJECT_ROOT / relative).resolve().is_file():
            raise ValueError(f"pulse-capture input is missing: {relative}")
    return contract


def main() -> None:
    validate_contract()
    print("PULSE_CAPTURE_CONTRACT=PASS PHASE_PASS_ALLOWED=false")


if __name__ == "__main__":
    main()
