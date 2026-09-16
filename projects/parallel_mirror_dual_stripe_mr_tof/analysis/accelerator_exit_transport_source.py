"""Bind one frozen accelerator-exit observation to the P1/P2 transport source."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from common.contracts.particle_physics import kinetic_energy_ev
from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_handoff import (
    ProjectPhaseSpaceState,
)


_SHA256_HEX_LENGTH = 64


def _required_finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CandidateContractError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise CandidateContractError(f"{label} must be a finite number")
    return result


def _required_integer(value: Any, label: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise CandidateContractError(f"{label} must be an integer not less than {minimum}")
    return value


def _required_sha256(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _SHA256_HEX_LENGTH
        or any(character not in "0123456789abcdefABCDEF" for character in value)
    ):
        raise CandidateContractError(f"{label} must be one SHA-256 hex digest")
    return value.lower()


def _required_vector(value: Any, label: str) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise CandidateContractError(f"{label} must contain three project-frame components")
    return tuple(
        _required_finite(component, f"{label}[{index}]")
        for index, component in enumerate(value)
    )


def materialize_accelerator_exit_transport_source(
    *,
    observation_path: Path,
    expected_observation_sha256: str,
    expected_particle_mass_th: float,
    expected_charge_state: int,
    receipt_path: Path,
) -> tuple[ProjectPhaseSpaceState, dict[str, Any]]:
    """Validate and publish one measured accelerator-exit state without reconstruction.

    The expected digest and species are explicit caller-owned bindings.  Position
    and velocity are copied directly from the solver observation; this adapter
    performs no energy-to-speed or direction reconstruction.
    """
    expected_sha = _required_sha256(
        expected_observation_sha256, "expected accelerator-exit observation SHA-256",
    )
    actual_sha = file_sha256(observation_path).lower()
    if actual_sha != expected_sha:
        raise CandidateContractError("accelerator-exit observation SHA-256 differs from the frozen input")
    try:
        observation = json.loads(observation_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CandidateContractError("accelerator-exit observation is not readable JSON") from error
    if (
        not isinstance(observation, dict)
        or observation.get("schema_version") != 1
        or observation.get("role") != "mrtof_accelerator_exit_observation"
        or observation.get("status") != "observed"
        or observation.get("qualification") != "source_to_accelerator_exit_diagnostic_only"
        or observation.get("coordinate_frame") != "project"
    ):
        raise CandidateContractError("accelerator-exit observation identity is invalid")

    inputs = observation.get("inputs")
    if not isinstance(inputs, dict) or set(inputs) != {
        "log_sha256", "source_receipt_sha256",
    }:
        raise CandidateContractError("accelerator-exit observation input identity is incomplete")
    log_sha = _required_sha256(inputs["log_sha256"], "accelerator-exit log SHA-256")
    source_sha = _required_sha256(
        inputs["source_receipt_sha256"], "accelerator-exit source-receipt SHA-256",
    )

    safe_exit = observation.get("safe_exit_state")
    required_state_fields = {
        "ion", "time_us", "position_mm", "velocity_mm_per_us", "particle_mass_th",
        "charge_state", "kinetic_energy_ev", "from_instance", "to_instance",
    }
    if not isinstance(safe_exit, dict) or set(safe_exit) != required_state_fields:
        raise CandidateContractError("accelerator safe-exit state is incomplete")
    ion = _required_integer(safe_exit["ion"], "safe-exit ion", minimum=1)
    time_us = _required_finite(safe_exit["time_us"], "safe-exit time")
    if time_us < 0.0:
        raise CandidateContractError("safe-exit time must not precede source release")
    position = _required_vector(safe_exit["position_mm"], "safe-exit position")
    velocity = _required_vector(safe_exit["velocity_mm_per_us"], "safe-exit velocity")
    if velocity[2] >= 0.0:
        raise CandidateContractError("accelerator safe-exit source must travel toward negative project z")
    mass = _required_finite(safe_exit["particle_mass_th"], "safe-exit particle mass")
    charge = _required_integer(safe_exit["charge_state"], "safe-exit charge state", minimum=1)
    expected_mass = _required_finite(expected_particle_mass_th, "expected particle mass")
    expected_charge = _required_integer(
        expected_charge_state, "expected charge state", minimum=1,
    )
    if mass <= 0.0 or expected_mass <= 0.0 or mass != expected_mass or charge != expected_charge:
        raise CandidateContractError("accelerator safe-exit species differs from the frozen species")
    kinetic_energy = _required_finite(safe_exit["kinetic_energy_ev"], "safe-exit kinetic energy")
    if kinetic_energy <= 0.0:
        raise CandidateContractError("safe-exit kinetic energy must be positive")
    from_instance = _required_integer(
        safe_exit["from_instance"], "safe-exit source instance", minimum=1,
    )
    to_instance = _required_integer(
        safe_exit["to_instance"], "safe-exit destination instance", minimum=0,
    )
    if from_instance == to_instance:
        raise CandidateContractError("safe-exit instance transition must leave the accelerator")

    energy_components = tuple(
        kinetic_energy_ev(
            mass,
            *(1000.0 * velocity[index] if index == axis else 0.0 for index in range(3)),
        )
        for axis in range(3)
    )
    reconstructed_energy = sum(energy_components)
    if not math.isclose(
        reconstructed_energy, kinetic_energy, rel_tol=1e-9, abs_tol=1e-9,
    ):
        raise CandidateContractError(
            "safe-exit kinetic energy differs from its recorded velocity components"
        )

    state = ProjectPhaseSpaceState(position, velocity)
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "role": "mrtof_two_prism_segmented_transport_source",
        "status": "materialized",
        "qualification": "measured_accelerator_exit_to_segmented_transport_input_only",
        "coordinate_frame": "project",
        "particle_mass_th": mass,
        "charge_state": charge,
        "ion": ion,
        "time_us": time_us,
        "position_mm": list(state.position_mm),
        "velocity_mm_per_us": list(state.velocity_mm_per_us),
        "kinetic_energy_ev": kinetic_energy,
        "kinetic_energy_components_ev": {
            "x": energy_components[0],
            "y": energy_components[1],
            "z": energy_components[2],
            "total": reconstructed_energy,
        },
        "accelerator_instance_transition": {
            "from_instance": from_instance,
            "to_instance": to_instance,
        },
        "transverse_diagnostic": {
            "x_mm": state.position_mm[0],
            "vx_mm_per_us": state.velocity_mm_per_us[0],
            "semantics": "measured x/vx retained for the downstream y-z projection diagnostic",
        },
        "input": {
            "accelerator_exit_observation": {
                "path": str(observation_path.resolve()),
                "sha256": actual_sha,
                "log_sha256": log_sha,
                "source_receipt_sha256": source_sha,
            },
        },
        "limitations": [
            "This receipt supplies a measured source state; it does not qualify P1/P2 transport.",
            "No velocity component is reconstructed or replaced by a nominal energy or direction.",
        ],
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    return state, receipt
