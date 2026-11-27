"""Validate fixed-mirror/Stripe source and terminal-mirror voltage authorities."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .candidate_contract import CandidateContractError, derive_mirror_voltage_bounds


def load_object(path: Path) -> dict[str, Any]:
    """Read one JSON object with the MR contract error on a non-object root."""
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise CandidateContractError(f"expected a JSON object in {path}")
    return value


def finite(value: Any, label: str) -> float:
    """Return one finite non-Boolean real or raise the MR contract error."""
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise CandidateContractError(f"{label} must be finite")
    return float(value)


def vector(value: Any, count: int | None, label: str) -> list[float]:
    """Return a nonempty finite vector with an optional exact length."""
    if not isinstance(value, list) or not value or (count is not None and len(value) != count):
        expected = f"{count} values" if count is not None else "at least one value"
        raise CandidateContractError(f"{label} must contain {expected}")
    return [finite(item, label) for item in value]


def fixed_mirror_stripe_source_state(
    authority: dict[str, Any],
    mirror_summary: dict[str, Any],
    stripe_summary: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[dict[str, Any], float, float, list[float], float]:
    """Validate the fixed-grid mirror/variable-slow-energy downstream receipt."""
    if (
        authority.get("schema_version") != 1
        or authority.get("role") != "mrtof_fixed_mirror_stripe_downstream_operating_authority"
        or authority.get("status") != "success"
    ):
        raise CandidateContractError("fixed mirror/Stripe downstream authority is invalid")
    if (
        mirror_summary.get("schema_version") != 1
        or mirror_summary.get("role") != "mrtof_mirror_turn_fixed_grid_validation"
        or mirror_summary.get("status") != "success"
    ):
        raise CandidateContractError("fixed mirror summary identity is invalid")
    if (
        stripe_summary.get("schema_version") != 3
        or stripe_summary.get("role") != "mrtof_dual_stripe_paper_theory_instance_specific_operating_seed_family"
        or stripe_summary.get("status") != "fixed_grid_native_mirror_exact_K_slow_energy_and_spatial_return_inverse_complete"
    ):
        raise CandidateContractError("fixed-mirror Stripe summary identity is invalid")
    seed = stripe_summary.get("selected_seed")
    materialized = seed.get("native_spatial_return_materialization") if isinstance(seed, dict) else None
    if not isinstance(seed, dict) or not isinstance(materialized, dict):
        raise CandidateContractError("fixed-mirror Stripe summary lacks its materialization")
    axial = finite(authority.get("axial_energy_per_charge_v"), "fixed mirror axial energy")
    slow = finite(authority.get("slow_energy_per_charge_v"), "selected slow energy")
    target_k = finite(authority.get("target_period_ratio"), "fixed mirror/Stripe target K")
    predicted_k = finite(authority.get("predicted_period_ratio"), "fixed mirror/Stripe predicted K")
    mirror_voltages = vector(authority.get("mirror_voltages_v"), 5, "fixed-grid mirror voltages")
    stripe_biases = vector(authority.get("stripe_biases_v"), 2, "fixed-mirror Stripe biases")
    if slow <= 0.0 or axial <= 0.0 or not math.isclose(target_k, predicted_k, rel_tol=0.0, abs_tol=1e-12):
        raise CandidateContractError("fixed mirror/Stripe energy or K identity is invalid")
    expected = (
        finite(seed.get("selected_axial_energy_per_charge_v"), "Stripe axial energy"),
        finite(seed.get("selected_exact_K_slow_energy_per_charge_v"), "Stripe slow energy"),
        finite(seed.get("target_drift_period_ratio"), "Stripe target K"),
        finite(seed.get("predicted_continuous_oscillation_count"), "Stripe predicted K"),
    )
    materialized_biases = vector(materialized.get("stripe_biases_v"), 2, "materialized Stripe biases")
    if (
        expected != (axial, slow, target_k, predicted_k)
        or vector(seed.get("stripe_biases_v"), 2, "Stripe seed biases") != stripe_biases
        or materialized_biases != stripe_biases
        or finite(materialized.get("axial_energy_per_charge_v"), "materialized axial energy") != axial
        or finite(materialized.get("source_slow_energy_per_charge_v"), "materialized slow energy") != slow
    ):
        raise CandidateContractError("fixed mirror/Stripe authority differs from its source summary")
    energy_contract = contract.get("accelerator_energy_contract")
    if not isinstance(energy_contract, dict):
        raise CandidateContractError("MR-TOF contract lacks its accelerator energy envelope")
    reference = finite(
        energy_contract.get("net_gain_reference_center_per_charge_v"), "contract net-gain reference centre"
    )
    half_range = finite(
        energy_contract.get("net_gain_center_search_half_range_per_charge_v"), "contract net-gain search half-range"
    )
    if not reference - half_range <= axial <= reference + half_range:
        raise CandidateContractError("fixed-grid mirror energy is outside the contract search envelope")
    return seed, slow, axial, mirror_voltages, target_k


def apply_terminal_mirror_variation(
    *, variation: dict[str, Any] | None, base_voltages: list[float],
    contract: dict[str, Any], axial_energy_v: float,
) -> tuple[list[float], dict[str, Any] | None]:
    """Validate and apply one absolute terminal-mirror voltage target."""
    if variation is None:
        return base_voltages, None
    if (
        variation.get("schema_version") != 1
        or variation.get("role") != "mrtof_terminal_time_mirror_voltage_variation"
        or variation.get("status") != "screening_candidate_materialized"
        or variation.get("qualification") not in {
            "diagnostic_only__complete_3d_detector_response_pending",
            "bare_mirror_prediction_outside_old_zero_slope_budget__complete_system_response_required",
        }
    ):
        raise CandidateContractError("terminal-time mirror variation identity is invalid")
    base = vector(variation.get("base_mirror_voltages_v"), 5, "terminal-time variation base mirror voltages")
    target = vector(variation.get("target_mirror_voltages_v"), 5, "terminal-time variation target mirror voltages")
    delta = vector(variation.get("voltage_delta_v"), 4, "terminal-time variation voltage delta")
    if base != base_voltages or base[0] != 0.0 or target[0] != 0.0:
        raise CandidateContractError("terminal-time mirror variation is not bound to the selected mirror authority")
    if any(
        not math.isclose(target[index + 1] - base[index + 1], delta[index], rel_tol=0.0, abs_tol=1e-9)
        for index in range(4)
    ):
        raise CandidateContractError("terminal-time mirror variation delta is inconsistent")
    lower, upper = derive_mirror_voltage_bounds(contract, selected_center_v=axial_energy_v)
    if any(value < low or value > high for value, low, high in zip(target[1:], lower, upper, strict=True)):
        raise CandidateContractError("terminal-time mirror variation violates the mirror envelope")
    identity = {
        "mode": variation.get("mode"),
        "coordinate": variation.get("coordinate"),
        "voltage_delta_v": delta,
        "source_seed": variation.get("source_seed"),
    }
    return target, identity
