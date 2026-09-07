#!/usr/bin/env python3
"""Screen a run-local L0 voltage candidate with the analytic 2-D L1 map."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import MirrorL0Design
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l1 import map_at_energy
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import load_contract


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--l0", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    l0 = json.loads(arguments.l0.read_text(encoding="utf-8"))
    contract = load_contract(arguments.contract)
    energy_v = float(contract["nominal"]["energy_per_charge_v"])
    design = MirrorL0Design(
        float(l0["transverse_half_gap_mm"]),
        tuple(float(value) for value in l0["transition_z_mm"]),
        tuple(float(value) for value in l0["electrode_voltages_v"]),
        l0.get("terminal_electrode_plane_z_mm"),
        float(l0["electrode_voltages_v"][-1]) if l0.get("terminal_electrode_plane_z_mm") is not None else None,
    )
    mapping = map_at_energy(energy_v, design)
    result = {
        "status": "l1_screen_pass" if mapping.stable and mapping.gamma_degrees is not None else "l1_screen_fail",
        "source_l0_status": l0.get("status"),
        "energy_v": energy_v,
        "matrix_x_alpha": [list(row) for row in mapping.matrix],
        "determinant": mapping.determinant,
        "reversibility_difference": mapping.reversibility_difference,
        "gamma_degrees": mapping.gamma_degrees,
        "stable": mapping.stable,
        "limitations": ["Infinite-y analytic field only", "No 3-D CAD field, PA, IOB, or flight result"],
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"MIRROR_L1_CANDIDATE: status={result['status']} output={arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
