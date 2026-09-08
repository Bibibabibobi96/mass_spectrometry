"""Derive a voltage-only accelerator focus trial on reviewed fixed geometry."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    derive_operating_energy_envelope,
    derive_stage_2_ring_voltages,
    derive_two_zone_focus,
    load_contract,
)

_VOLTAGE_FIELDS = frozenset({"repeller_v", "intermediate_grid_v", "exit_grid_v"})


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def accelerator_geometry_contract(accelerator: dict[str, Any]) -> dict[str, Any]:
    """Return the accelerator fields that must remain fixed during voltage trials."""
    return {key: copy.deepcopy(value) for key, value in accelerator.items() if key not in _VOLTAGE_FIELDS}


def require_reviewed_geometry(current: dict[str, Any], reviewed: dict[str, Any]) -> None:
    """Fail unless a candidate differs from the reviewed assembly only in voltages."""
    for key in ("coordinate_system", "prisms"):
        if current.get(key) != reviewed.get(key):
            raise CandidateContractError(f"current {key} differs from the reviewed PA/IOB contract")
    current_accelerator = current.get("accelerator")
    reviewed_accelerator = reviewed.get("accelerator")
    if not isinstance(current_accelerator, dict) or not isinstance(reviewed_accelerator, dict):
        raise CandidateContractError("voltage trial requires current and reviewed accelerator contracts")
    if accelerator_geometry_contract(current_accelerator) != accelerator_geometry_contract(reviewed_accelerator):
        raise CandidateContractError("current accelerator geometry differs from the reviewed PA/IOB contract")


def derive_voltage_trial(
    current: dict[str, Any], reviewed: dict[str, Any], first_gap_drop_v: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Derive endpoint/ring voltages while preserving the reviewed physical placement."""
    require_reviewed_geometry(current, reviewed)
    drop = float(first_gap_drop_v)
    if not math.isfinite(drop) or drop <= 0.0:
        raise CandidateContractError("first-gap voltage drop must be finite and positive")
    source = current.get("particle_source", {})
    species = source.get("species", {}) if isinstance(source, dict) else {}
    charge = float(species.get("charge_e", 0.0))
    if not math.isfinite(charge) or charge <= 0.0:
        raise CandidateContractError("accelerator voltage trial requires a positive ion")
    trial = copy.deepcopy(current)
    accelerator = trial["accelerator"]
    gap_1 = float(accelerator["gap_1_mm"])
    release = float(accelerator["release_position_in_gap_1_mm"])
    exit_v = float(accelerator["exit_grid_v"])
    if not all(math.isfinite(value) for value in (gap_1, release, exit_v)) or not 0.0 < release < gap_1:
        raise CandidateContractError("accelerator release must lie strictly inside finite gap 1")
    energy_per_charge_v = derive_operating_energy_envelope(current).net_gain_reference_center_v
    repeller_v = exit_v + energy_per_charge_v + drop * release / gap_1
    intermediate_v = repeller_v - drop
    accelerator["repeller_v"] = repeller_v
    accelerator["intermediate_grid_v"] = intermediate_v
    rings = list(derive_stage_2_ring_voltages(trial))
    focus = derive_two_zone_focus(trial)
    trial["candidate_derivation"] = {
        "role": "fixed_reviewed_geometry_accelerator_voltage_trial",
        "first_gap_drop_v": drop,
        "energy_per_charge_v": energy_per_charge_v,
        "physical_placement_source": "reviewed_contract_not_trial_focus",
    }
    receipt = {
        "schema_version": 1,
        "role": "mrtof_fixed_geometry_accelerator_voltage_trial",
        "status": "derived",
        "first_gap_drop_v": drop,
        "energy_per_charge_v": energy_per_charge_v,
        "endpoint_voltages_v": [repeller_v, intermediate_v, exit_v],
        "ring_voltages_v": rings,
        "analytic_focus_after_exit_mm": focus.focus_after_exit_mm,
        "semantics": "voltage-only trial; reviewed PA geometry and workbench placement remain invariant",
    }
    return trial, receipt


def materialize(
    current_path: Path, reviewed_path: Path, first_gap_drop_v: float,
    output_path: Path, receipt_path: Path,
) -> dict[str, Any]:
    current = load_contract(current_path)
    reviewed = load_contract(reviewed_path)
    trial, receipt = derive_voltage_trial(current, reviewed, first_gap_drop_v)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(trial, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt.update({
        "source_contract_sha256": _sha256(current_path),
        "reviewed_contract_sha256": _sha256(reviewed_path),
        "trial_contract_sha256": _sha256(output_path),
    })
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--reviewed", required=True, type=Path)
    parser.add_argument("--first-gap-drop-v", required=True, type=float)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    arguments = parser.parse_args()
    receipt = materialize(
        arguments.current, arguments.reviewed, arguments.first_gap_drop_v,
        arguments.output, arguments.receipt,
    )
    print(f"MRTOF_ACCELERATOR_VOLTAGE_TRIAL=PASS drop_v={receipt['first_gap_drop_v']:.12g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
