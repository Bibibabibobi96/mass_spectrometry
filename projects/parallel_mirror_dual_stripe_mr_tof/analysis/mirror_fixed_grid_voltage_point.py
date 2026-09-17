"""Materialize one bounded fixed-grid mirror-voltage diagnostic point."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_voltage_family import (
    GROUPS,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


def _object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateContractError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise CandidateContractError(f"{label} must be an object")
    return value


def build_fixed_grid_point_receipt(
    *, correction_path: Path, family_path: Path, contract_path: Path, output_path: Path,
) -> dict[str, Any]:
    correction = _object(correction_path, "fixed-grid correction")
    family = _object(family_path, "coarse L0 family")
    contract = _object(contract_path, "MR-TOF contract")
    inputs = correction.get("inputs")
    common_valid = (
        correction.get("role") != "mrtof_fixed_grid_multifidelity_voltage_correction"
        or not isinstance(inputs, Mapping)
        or inputs.get("family_sha256") != file_sha256(family_path)
    )
    if common_valid:
        raise CandidateContractError("correction does not authorize a fixed-grid point")
    if correction.get("status") in {
        "no_local_gamma_bracket__additional_fixed_grid_secant_required",
        "gamma_root_outside_local_trust_region__additional_fixed_grid_secant_required",
    }:
        point = correction.get("recommended_secant_fixed_grid_point")
        if not isinstance(point, Mapping):
            raise CandidateContractError("correction lacks its recommended secant point")
        qualification = "diagnostic_secant_point_only__not_a_candidate_operating_point"
        purpose = str(point["purpose"])
        voltages = [float(value) for value in point.get("mirror_voltages_v", [])]
        coarse_slopes = [
            float(value) for value in point["coarse_normalized_period_slopes_per_v"]
        ]
        e_step = float(point["mirror_E_step_from_source_v"])
        source_refinement_sha256 = str(inputs["refinement_sha256"])
        limitations = [
            "This point measures a local fixed-grid secant and is not an operating candidate.",
            "Its result must be combined with the source fixed-grid point before another proposal is made.",
        ]
    elif correction.get("status") == "secant_proposal_only__independent_fixed_grid_validation_required":
        qualification = "secant_model_proposal_fixed_grid_validation_only__not_accepted"
        chord_count = int(
            correction.get("secant_diagnostics", {}).get(
                "independent_voltage_chord_count", 1,
            )
        )
        if chord_count <= 0:
            raise CandidateContractError("correction secant count must be positive")
        purpose = (
            "independently_validate_rank_one_secant_voltage_proposal"
            if chord_count == 1
            else "independently_validate_constrained_multisecant_voltage_proposal"
        )
        voltages = [float(value) for value in correction.get("proposed_mirror_voltages_v", [])]
        coarse_slopes = []
        e_step = float(voltages[-1] - correction["source_mirror_voltages_v"][-1])
        source_refinement_sha256 = str(correction["source_refinement_sha256"])
        limitations = (
            ["This point independently tests a two-point rank-one discrepancy proposal."]
            if chord_count == 1
            else [
                f"This point independently tests a discrepancy proposal constrained by {chord_count} voltage chords."
            ]
        ) + [
            "It is not accepted until fixed-grid L0, stability, gamma and Tbar gates pass."
        ]
    else:
        raise CandidateContractError("correction does not authorize one fixed-grid secant point")
    if len(voltages) != 5 or voltages[0] != 0.0 or not all(map(math.isfinite, voltages)):
        raise CandidateContractError("fixed-grid secant voltage vector is invalid")
    bounds = family.get("voltage_bounds_v")
    if not isinstance(bounds, Mapping):
        raise CandidateContractError("coarse L0 family lacks voltage bounds")
    for group, voltage in zip(GROUPS, voltages[1:], strict=True):
        pair = bounds.get(group)
        if not isinstance(pair, list) or len(pair) != 2:
            raise CandidateContractError(f"coarse L0 family lacks {group} bounds")
        if not float(pair[0]) <= voltage <= float(pair[1]):
            raise CandidateContractError(f"fixed-grid secant {group} voltage is out of bounds")
    energies = [float(value) for value in family.get("energy_centers_ev", [])]
    if len(energies) != 3 or voltages[-1] <= max(energies):
        raise CandidateContractError("fixed-grid secant does not retain E reflection margin")
    profile = contract["mirror"]["theory_requirements"][
        "fixed_grid_multifidelity_correction_profile"
    ]
    if profile.get("status") != "local_proposal_only__independent_fixed_grid_validation_required":
        raise CandidateContractError("current correction profile is not active")
    receipt = {
        "schema_version": 1,
        "role": "mrtof_fixed_grid_mirror_voltage_point",
        "status": "prepared_for_independent_fixed_grid_diagnostic",
        "qualification": qualification,
        "purpose": purpose,
        "source_root_index": int(correction["source_root_index"]),
        "source_refinement_sha256": source_refinement_sha256,
        "source_correction_sha256": file_sha256(correction_path),
        "source_family_sha256": file_sha256(family_path),
        "source_contract_sha256": file_sha256(contract_path),
        "mirror_voltages_v": voltages,
        "mirror_E_step_from_source_v": e_step,
        "coarse_normalized_period_slopes_per_v": coarse_slopes,
        "energy_centers_ev": energies,
        "period_slope_derivative_step_ev": float(
            family["period_slope_derivative_step_ev"]
        ),
        "discrepancy_model_independent_voltage_chord_count": (
            chord_count
            if correction.get("status")
            == "secant_proposal_only__independent_fixed_grid_validation_required"
            else 0
        ),
        "limitations": limitations,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return receipt


def build_secant_point_receipt(
    *, correction_path: Path, family_path: Path, contract_path: Path, output_path: Path,
) -> dict[str, Any]:
    """Backward-compatible Python API for the first diagnostic secant point."""

    return build_fixed_grid_point_receipt(
        correction_path=correction_path,
        family_path=family_path,
        contract_path=contract_path,
        output_path=output_path,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--correction", type=Path, required=True)
    parser.add_argument("--family", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    build_fixed_grid_point_receipt(
        correction_path=args.correction,
        family_path=args.family,
        contract_path=args.contract,
        output_path=args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
