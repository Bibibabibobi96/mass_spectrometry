"""Emit the native full-flight corridor GEM from the resolved MR-TOF geometry.

The corridor is not a hand-maintained copy of one of the five local patches.
Its box, mesh and electrode namespace are derived from the same resolved
contract used by the analyser PA.  The emitted geometry keeps the physical
electrode IDs; the stream runner remaps those IDs to the dense native family
namespace before creating ``pa#``/``pa0``.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_corridor_plan import (
    derive_native_corridor_plan,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_candidate_geometry import _number
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_system_geometry import (
    _analyzer_geometry_lines,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import resolve_geometry
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    load_contract,
)


def build_native_corridor_gem(contract_path: Path) -> str:
    """Return a corridor GEM clipped by SIMION's derived PA envelope."""
    contract = load_contract(contract_path)
    plan = derive_native_corridor_plan(contract_path)
    box = tuple(float(value) for value in plan["box_project_mm"])
    mesh = tuple(float(value) for value in plan["mesh_mm_per_gu"])
    shape = tuple(int(value) for value in plan["grid_shape"])
    if len(box) != 6 or len(mesh) != 3 or len(shape) != 3:
        raise CandidateContractError("native corridor plan has an invalid box, mesh or shape")
    if any(value <= 0 for value in mesh) or any(value < 2 for value in shape):
        raise CandidateContractError("native corridor mesh and shape must be positive")
    resolved = resolve_geometry(contract)
    mapping = plan["physical_to_local_electrode_id"]
    required = {str(identifier) for identifier in range(1, 21)}
    if set(mapping) != required:
        raise CandidateContractError("corridor physical-to-local map must cover analyser IDs 1..20")
    # GEM is emitted in the physical namespace.  Remapping is a separate,
    # explicit step so the canonical geometry remains auditable and reusable.
    lines = [
        "; MR-TOF native full-flight corridor: generated from resolved canonical geometry.",
        "; Physical IDs 1..20 are retained here; the stream runner remaps them to local IDs 1..8/0.",
        f"; contract={contract_path.resolve()}",
        f"; corridor_box_project_mm={','.join(_number(value) for value in box)}",
        f"; mesh_mm_per_gu={','.join(_number(value) for value in mesh)}",
        f"; grid_shape={','.join(str(value) for value in shape)}",
        f"pa_define({shape[0]},{shape[1]},{shape[2]},planar,none,electrostatic,,{_number(mesh[0])},{_number(mesh[1])},{_number(mesh[2])},surface=none)",
        f"locate({_number(-box[0])},{_number(-box[1])},{_number(-box[2])}) {{",
    ]
    lines.extend(_analyzer_geometry_lines(resolved))
    lines.extend(("}", ""))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    text = build_native_corridor_gem(args.contract)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
