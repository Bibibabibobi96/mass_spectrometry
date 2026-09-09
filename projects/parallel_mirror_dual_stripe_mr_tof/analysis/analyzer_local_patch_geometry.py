"""Generate a clipped analyser GEM for one contract-owned refinement patch."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_refinement_plan import (
    derive_local_refinement_plan,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.full_candidate_geometry import _number
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import resolve_geometry
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    load_contract,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.split_candidate_geometry import (
    _analyzer_geometry_lines,
)


REGIONS = (
    "mirror_turn_positive", "central_transport",
    "stripe_mirror_bridge_positive", "stripe_mirror_bridge_negative",
)


def _profile_key(region: str) -> str:
    return {
        "mirror_turn_positive": "mirror_turn",
        "central_transport": "central_transport",
        "stripe_mirror_bridge_positive": "stripe_mirror_bridge",
        "stripe_mirror_bridge_negative": "stripe_mirror_bridge_negative",
    }[region]


def build_local_patch_gem(contract_path: Path, region: str, scale_factor: float) -> str:
    if region not in REGIONS:
        raise CandidateContractError(f"unsupported analyser patch region: {region}")
    contract = load_contract(contract_path)
    plan = derive_local_refinement_plan(contract_path)
    selected: dict[str, Any] | None = None
    profile_key = _profile_key(region)
    for profile in plan["profiles"]:
        if float(profile["scale_factor"]) == float(scale_factor):
            selected = profile[profile_key]
            break
    if selected is None:
        raise CandidateContractError("requested patch scale is not declared by the contract")
    box = [float(value) for value in selected["box_project_mm"]]
    mesh = [float(value) for value in selected["mesh_mm_per_gu"]]
    span = [box[index + 3] - box[index] for index in range(3)]
    shape = [round(span[index] / mesh[index]) + 1 for index in range(3)]
    if shape != selected["grid_shape"]:
        raise CandidateContractError("local GEM dimensions differ from the refinement plan")
    resolved = resolve_geometry(contract)
    lines = [
        "; Contract-derived local MR-TOF analyser refinement geometry.",
        f"; region={region} scale_factor={_number(float(scale_factor))}",
        "; Boundary nodes are populated from the global basis by common/simion/build_dirichlet_patch_basis.lua.",
        f"pa_define({shape[0]},{shape[1]},{shape[2]},planar,none,electrostatic,, {_number(mesh[0])},{_number(mesh[1])},{_number(mesh[2])},surface=none)",
        f"locate({_number(-box[0])},{_number(-box[1])},{_number(-box[2])}) {{",
    ]
    lines.extend(_analyzer_geometry_lines(resolved))
    lines.extend(("}", ""))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--region", required=True, choices=REGIONS)
    parser.add_argument("--scale-factor", required=True, type=float)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    text = build_local_patch_gem(arguments.contract, arguments.region, arguments.scale_factor)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
