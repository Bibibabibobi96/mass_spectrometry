"""Emit the native full-flight corridor GEM from the resolved MR-TOF geometry.

The corridor is not a hand-maintained copy of one of the five local patches.
Its box, mesh and electrode namespace are derived from the same resolved
contract used by the analyser PA.  The emitted geometry keeps the physical
electrode IDs; the stream runner remaps those IDs to the dense native family
namespace before creating ``pa#``/``pa0``.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from collections.abc import Mapping

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


def build_native_corridor_gem(
    contract_path: Path,
    *,
    physical_electrode_voltages_v: Mapping[int, float] | None = None,
    physical_to_local_electrode_id: Mapping[int, int] | None = None,
) -> str:
    """Return a corridor GEM clipped by SIMION's derived PA envelope."""
    contract = load_contract(contract_path)
    plan = derive_native_corridor_plan(contract_path)
    box = tuple(float(value) for value in plan["box_project_mm"])
    mesh = tuple(float(value) for value in plan["mesh_mm_per_gu"])
    surface_mode = str(plan["surface_mode"])
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
        f"pa_define({shape[0]},{shape[1]},{shape[2]},planar,x,electrostatic,,{_number(mesh[0])},{_number(mesh[1])},{_number(mesh[2])},surface={surface_mode})",
        f"locate({_number(0.0 if box[0] == 0.0 else -box[0])},{_number(-box[1])},{_number(-box[2])}) {{",
    ]
    if physical_electrode_voltages_v is not None and physical_to_local_electrode_id is not None:
        raise CandidateContractError("corridor GEM accepts voltages or local IDs, not both")
    replacement_values: Mapping[int, float | int] | None = physical_electrode_voltages_v
    if physical_to_local_electrode_id is not None:
        if set(physical_to_local_electrode_id) != set(range(1, 21)):
            raise CandidateContractError("corridor local-ID map must cover physical IDs 1..20")
        if any(type(value) is not int or not 0 <= value <= 8 for value in physical_to_local_electrode_id.values()):
            raise CandidateContractError("corridor local electrode IDs must be integers in 0..8")
        replacement_values = physical_to_local_electrode_id
    geometry_lines = _analyzer_geometry_lines(resolved)
    if replacement_values is not None:
        unknown = set(replacement_values) - set(range(1, 21))
        if unknown:
            raise CandidateContractError(
                f"corridor replacement values contain unknown physical IDs: {sorted(unknown)}"
            )

        def replace_voltage(line: str) -> str:
            match = re.match(r"^(\s*)e\((\d+)\)(.*)$", line)
            if match is None:
                return line
            identifier = int(match.group(2))
            voltage = float(replacement_values.get(identifier, 0.0))
            if voltage != voltage or abs(voltage) == float("inf"):
                raise CandidateContractError("corridor response voltage must be finite")
            return f"{match.group(1)}e({_number(voltage)}){match.group(3)}"

        geometry_lines = [replace_voltage(line) for line in geometry_lines]
    lines.extend(geometry_lines)
    lines.extend(("}", ""))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--active-physical-ids", default="")
    parser.add_argument("--basis-voltage-v", type=float, default=10_000.0)
    parser.add_argument("--physical-to-local-map", default="")
    args = parser.parse_args()
    if args.active_physical_ids and args.physical_to_local_map:
        raise CandidateContractError("active physical IDs and local-ID map are mutually exclusive")
    voltages = None
    if args.active_physical_ids:
        identifiers = [int(value) for value in args.active_physical_ids.split(",")]
        if not identifiers or len(set(identifiers)) != len(identifiers):
            raise CandidateContractError("active physical IDs must be a unique nonempty list")
        voltages = {identifier: args.basis_voltage_v for identifier in identifiers}
    local_mapping = None
    if args.physical_to_local_map:
        pairs = [value.split(":", maxsplit=1) for value in args.physical_to_local_map.split(",")]
        if any(len(pair) != 2 for pair in pairs):
            raise CandidateContractError("physical-to-local map must use physical:local pairs")
        local_mapping = {int(pair[0]): int(pair[1]) for pair in pairs}
        if len(local_mapping) != len(pairs):
            raise CandidateContractError("physical-to-local map contains duplicate physical IDs")
    text = build_native_corridor_gem(
        args.contract,
        physical_electrode_voltages_v=voltages,
        physical_to_local_electrode_id=local_mapping,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
