"""Materialize an axial accelerator-focus Fly2 without rebuilding any PA."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.accelerator_focus_voltage_trial import (
    require_reviewed_geometry,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.materialize_simion_prototype import (
    accelerator_focus_fly2,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import load_contract


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def materialize(
    contract_path: Path,
    reviewed_contract_path: Path,
    source_key: str,
    output_path: Path,
    receipt_path: Path,
) -> dict[str, Any]:
    current = load_contract(contract_path)
    reviewed = load_contract(reviewed_contract_path)
    require_reviewed_geometry(current, reviewed)
    current_source = current.get("particle_source", {})
    reviewed_source = reviewed.get("particle_source", {})
    current_species = current_source.get("species") if isinstance(current_source, dict) else None
    reviewed_species = reviewed_source.get("species") if isinstance(reviewed_source, dict) else None
    identity_keys = ("mass_th", "charge_e")
    if (
        not isinstance(current_species, dict)
        or not isinstance(reviewed_species, dict)
        or any(current_species.get(key) != reviewed_species.get(key) for key in identity_keys)
    ):
        raise ValueError("current source species identity differs from the reviewed PA/IOB contract")
    focus_profile = current_source.get("accelerator_focus_diagnostic")
    if (
        not isinstance(focus_profile, dict)
        or focus_profile.get("status") != "diagnostic_only__zero_ke_axial_release"
        or focus_profile.get("initial_kinetic_energy_ev") != 0
    ):
        raise ValueError("current contract omits the named zero-KE accelerator-focus diagnostic")
    count_keys = {
        "accelerator_focus_center_fly2": "center_particle_count",
        "accelerator_focus_bunch_fly2": "candidate_bunch_particle_count",
    }
    if source_key not in count_keys:
        raise ValueError(f"unsupported accelerator focus source key: {source_key}")
    source = current_source
    count_key = count_keys[source_key]
    width = 0.0 if count_key == "center_particle_count" else float(source["accelerator_focus_axial_full_width_mm"])
    text = accelerator_focus_fly2(
        current, source, count_key, width, placement_contract=reviewed,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8", newline="\n")
    count = int(source[count_key])
    release = float(current["accelerator"]["release_position_in_gap_1_mm"])
    receipt = {
        "schema_version": 1,
        "role": "mrtof_accelerator_focus_axial_source",
        "status": "materialized",
        "source_key": source_key,
        "particle_count": count,
        "release_interval_in_gap_1_mm": [release - width / 2.0, release + width / 2.0],
        "baseline_contract_sha256": _sha256(contract_path),
        "reviewed_geometry_contract_sha256": _sha256(reviewed_contract_path),
        "fly2_sha256": _sha256(output_path),
        "semantics": "deterministic axial zero-KE release family on reviewed fixed placement; no PA or IOB geometry was regenerated",
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--reviewed-contract", required=True, type=Path)
    parser.add_argument("--source-key", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    receipt = materialize(args.contract, args.reviewed_contract, args.source_key, args.output, args.receipt)
    print(f"MRTOF_ACCELERATOR_FOCUS_SOURCE=PASS particles={receipt['particle_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
