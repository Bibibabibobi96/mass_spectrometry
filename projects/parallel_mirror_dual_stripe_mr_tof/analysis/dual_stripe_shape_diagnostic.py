"""Publish the fixed-CAD Stripe structure diagnostic from a managed mirror run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_l0 import (
    identify_fixed_cad_component_shapes,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_candidate_receipt import (
    load_managed_mirror_candidate,
)


def build_diagnostic(mirror_manifest: Path, downstream_contract: Path) -> dict[str, Any]:
    """Bind the current Stripe-only contract extension to an unchanged mirror projection."""
    mirror = load_managed_mirror_candidate(mirror_manifest, downstream_contract)
    shape = identify_fixed_cad_component_shapes(mirror.contract)
    return {
        "schema_version": 1,
        "role": "mrtof_fixed_cad_dual_stripe_structure_diagnostic",
        "status": "success",
        "qualification": "diagnostic_only__L_and_voltage_solution_pending",
        "managed_mirror_input": {
            "run_id": mirror.run_id,
            "manifest_sha256": mirror.manifest_sha256,
            "parent_contract_sha256": mirror.contract_sha256,
            "downstream_contract_sha256": mirror.downstream_contract_sha256,
            "projection_match": True,
            "selected_mirror_voltages_v": list(mirror.design.electrode_voltages_v),
            "nominal_reduced_period_mm_per_sqrt_v": mirror.nominal_reduced_period_mm_per_sqrt_v,
            "nominal_axial_width_W_mm": mirror.nominal_axial_width_w_mm,
        },
        "shape_structure": shape,
        "next_gate": "close the actual downstream unknown/residual rank before publishing L or any Stripe/P1/P2 voltage",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mirror-manifest", required=True, type=Path)
    parser.add_argument("--downstream-contract", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    result = build_diagnostic(arguments.mirror_manifest, arguments.downstream_contract)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"MRTOF_DUAL_STRIPE_STRUCTURE_DIAGNOSTIC=PASS OUTPUT={arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
