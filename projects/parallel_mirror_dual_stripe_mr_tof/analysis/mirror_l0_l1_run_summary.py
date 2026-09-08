"""Validate managed mirror L0/L1 receipts and publish a compact run summary."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    derive_mirror_voltage_bounds,
    derive_operating_energy_envelope,
    load_contract,
)


L0_STATUS = "l0_voltage_family_member_not_l1_validated"
L1_STATUS = "l1_family_continued_to_gamma_target__peak_field_and_3d_validation_pending"
GAMMA_SELECTION_STATUS = (
    "gamma_target_selected_with_probe_convergence__peak_field_and_3d_validation_pending"
)


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CandidateContractError(f"{label} is not readable JSON: {path}") from error
    if not isinstance(value, dict):
        raise CandidateContractError(f"{label} must be a JSON object")
    return value


def _finite_float(value: object, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise CandidateContractError(f"{label} must be numeric") from error
    if not math.isfinite(result):
        raise CandidateContractError(f"{label} must be finite")
    return result


def validate_and_summarize(contract_path: Path, l0_path: Path, l1_path: Path) -> dict[str, Any]:
    """Fail closed on an incomplete L0/L1 chain and return its Candidate metrics."""

    contract = load_contract(contract_path)
    l0 = _load_json(l0_path, "L0 receipt")
    l1 = _load_json(l1_path, "L1 receipt")
    contract_sha256 = file_sha256(contract_path)
    l0_sha256 = file_sha256(l0_path)
    if l0.get("status") != L0_STATUS:
        raise CandidateContractError(f"L0 receipt status is not accepted: {l0.get('status')}")
    if l1.get("status") != L1_STATUS:
        raise CandidateContractError(f"L1 receipt status is not accepted: {l1.get('status')}")
    if l0.get("input", {}).get("contract_sha256") != contract_sha256:
        raise CandidateContractError("L0 receipt does not bind the frozen contract")
    if l1.get("input", {}).get("contract", {}).get("sha256") != contract_sha256:
        raise CandidateContractError("L1 receipt does not bind the frozen contract")
    if l1.get("input", {}).get("l0_receipt", {}).get("sha256") != l0_sha256:
        raise CandidateContractError("L1 receipt does not bind the supplied L0 receipt")

    search = l0.get("parallel_restart_search")
    if not isinstance(search, dict):
        raise CandidateContractError("L0 receipt omits parallel_restart_search")
    profile = contract["mirror"]["theory_requirements"]["global_l0_search_profile"]
    restart_count = int(search.get("restart_count", -1))
    if restart_count != int(profile["restart_count"]):
        raise CandidateContractError("L0 restart count differs from the frozen search profile")
    accepted_indices = search.get("accepted_l0_restart_indices")
    if not isinstance(accepted_indices, list) or not accepted_indices:
        raise CandidateContractError("L0 search accepted no family member")
    if any(not isinstance(index, int) or index < 0 or index >= restart_count for index in accepted_indices):
        raise CandidateContractError("L0 accepted restart indices are invalid")

    continuation = l1.get("gamma_target_continuation")
    convergence = l1.get("gamma_target_probe_convergence")
    if not isinstance(continuation, dict) or continuation.get("status") != GAMMA_SELECTION_STATUS:
        raise CandidateContractError("L1 gamma-target continuation did not pass")
    if not isinstance(convergence, dict) or convergence.get("status") != "pass":
        raise CandidateContractError("L1 finite-difference probe convergence did not pass")
    residual_degrees = abs(_finite_float(continuation.get("gamma_residual_degrees"), "gamma residual"))
    residual_limit_degrees = _finite_float(
        continuation.get("maximum_gamma_residual_degrees"), "gamma residual limit"
    )
    if residual_degrees > residual_limit_degrees:
        raise CandidateContractError("L1 gamma residual exceeds its declared tolerance")

    selected = continuation.get("l0_receipt")
    if not isinstance(selected, dict):
        raise CandidateContractError("L1 continuation omits its selected L0-family member")
    voltages = selected.get("electrode_voltages_v")
    slopes = selected.get("normalized_period_slopes_per_v")
    if not isinstance(voltages, list) or len(voltages) != 5:
        raise CandidateContractError("selected mirror voltage vector must contain A--E")
    if not isinstance(slopes, list) or len(slopes) != 3:
        raise CandidateContractError("selected mirror receipt must report three local period slopes")
    voltages_v = [_finite_float(value, "mirror voltage") for value in voltages]
    slopes_per_v = [_finite_float(value, "normalized period slope") for value in slopes]
    if voltages_v[0] != 0.0:
        raise CandidateContractError("mirror electrode A must remain grounded")
    energies_v = list(derive_operating_energy_envelope(contract).mirror_energy_nodes_v)
    if voltages_v[-1] <= max(energies_v):
        raise CandidateContractError("mirror electrode E must remain above the maximum energy node")
    lower_bounds, upper_bounds = derive_mirror_voltage_bounds(contract)
    if any(not low <= value <= high for value, low, high in zip(voltages_v[1:], lower_bounds, upper_bounds, strict=True)):
        raise CandidateContractError("selected mirror member violates the derived voltage envelope")
    slope_limit = _finite_float(selected.get("maximum_abs_normalized_period_slope_per_v"), "slope limit")
    maximum_abs_slope = max(abs(value) for value in slopes_per_v)
    if maximum_abs_slope > slope_limit:
        raise CandidateContractError("selected mirror member exceeds the L0 slope tolerance")

    stable_count = int(l1.get("l1_stable_count", -1))
    if int(l1.get("l0_accepted_count", -1)) != len(accepted_indices) or stable_count <= 0:
        raise CandidateContractError("L1 family counts are inconsistent or contain no stable member")
    root_family = l1.get("gamma_target_root_family")
    if root_family is None:
        gamma_root_count = 1
    else:
        if not isinstance(root_family, dict):
            raise CandidateContractError("L1 gamma-target root family must be an object")
        roots = root_family.get("roots")
        if (
            root_family.get("status") != "complete_stable_seed_intersection_family__downstream_selection_pending"
            or not isinstance(roots, list)
            or len(roots) != int(root_family.get("distinct_root_count", -1))
            or len(roots) != int(root_family.get("probe_converged_root_count", -1))
            or not roots
        ):
            raise CandidateContractError("L1 gamma-target root family is incomplete or internally inconsistent")
        gamma_root_count = len(roots)
    return {
        "schema_version": 1,
        "role": "mrtof_mirror_l0_l1_candidate_summary",
        "status": "success",
        "qualification": "analytic_2d_candidate__peak_field_and_3d_validation_pending",
        "input_identity": {
            "contract_sha256": contract_sha256,
            "l0_receipt_sha256": l0_sha256,
            "l1_receipt_sha256": file_sha256(l1_path),
        },
        "search": {
            "restart_count": restart_count,
            "accepted_l0_count": len(accepted_indices),
            "l1_stable_count": stable_count,
            "gamma_target_root_count": gamma_root_count,
            "actual_parallel_workers": int(l0["input"]["actual_parallel_workers"]),
        },
        "selected_mirror_voltages_v": dict(zip(("A", "B", "C", "D", "E"), voltages_v)),
        "maximum_abs_normalized_period_slope_per_v": maximum_abs_slope,
        "gamma_degrees": _finite_float(continuation["l1_screen"]["nominal_mapping"]["gamma_degrees"], "gamma"),
        "gamma_residual_degrees": residual_degrees,
        "gamma_probe_convergence": {
            "last_adjacent_gamma_change_degrees": _finite_float(
                convergence.get("last_adjacent_gamma_change_degrees"), "adjacent gamma change"
            ),
            "last_adjacent_relative_Tbar_change": _finite_float(
                convergence.get("last_adjacent_relative_Tbar_change"), "relative Tbar change"
            ),
        },
        "limitations": [
            "This is an infinite-y analytic 2-D mirror Candidate, not a three-dimensional field or flight result.",
            "Peak-field ranking, real slots and covers, SIMION trajectory clearance, and grid convergence remain pending.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--l0-receipt", required=True, type=Path)
    parser.add_argument("--l1-receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    summary = validate_and_summarize(arguments.contract, arguments.l0_receipt, arguments.l1_receipt)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"MRTOF_MIRROR_L0_L1_SUMMARY=PASS OUTPUT={arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
