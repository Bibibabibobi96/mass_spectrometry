"""Pure reference and SIMION-GEM source generator for the MR-TOF prototype.

The only coordinate frame accepted here is the project frame: z is reflection,
y is drift, x is transverse focusing, and z=0 is the injection midplane.  This
module deliberately does not import the oa-TOF implementation: its accelerator
is a separate candidate, even though it uses the same two-uniform-field theory.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class CandidateContractError(ValueError):
    """Raised when the prototype contract cannot describe a physical candidate."""


@dataclass(frozen=True)
class TwoZoneFocus:
    field_1_v_per_mm: float
    field_2_v_per_mm: float
    energy_per_charge_v: float
    focus_after_exit_mm: float
    accelerator_translation_z_mm: float


def _number(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise CandidateContractError(f"{name} must be finite")
    return result


def load_contract(path: Path) -> dict[str, Any]:
    """Load and minimally validate the MR-TOF-only candidate contract."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("project_id") != "parallel_mirror_dual_stripe_mr_tof":
        raise CandidateContractError("project_id must identify the MR-TOF project")
    frame = data.get("coordinate_system", {})
    if frame.get("frame_id") != "astral.xyz.reflection_z.drift_y.transverse_x.v1":
        raise CandidateContractError("candidate must use the documented Astral coordinate frame")
    stripe = data.get("dual_stripe", {})
    if stripe.get("physical_electrode_count") != 4 or stripe.get("theoretical_response_count") != 2:
        raise CandidateContractError("dual stripe requires four physical electrodes and two responses")
    if _number(stripe["minimum_width_mm"], "minimum_width_mm") <= 0.0:
        raise CandidateContractError("stripe widths must remain positive")
    if _number(stripe["maximum_width_mm"], "maximum_width_mm") < _number(stripe["minimum_width_mm"], "minimum_width_mm"):
        raise CandidateContractError("maximum stripe width must be >= minimum width")
    return data


def derive_two_zone_focus(contract: dict[str, Any]) -> TwoZoneFocus:
    """Derive the first-order focus and rigid placement at the z=0 interface."""
    frame = contract.get("coordinate_system", {})
    if frame.get("frame_id") != "astral.xyz.reflection_z.drift_y.transverse_x.v1":
        raise CandidateContractError("candidate must use the documented Astral coordinate frame")
    accelerator = contract["accelerator"]
    repeller = _number(accelerator["repeller_v"], "repeller_v")
    grid_1 = _number(accelerator["intermediate_grid_v"], "intermediate_grid_v")
    exit_grid = _number(accelerator["exit_grid_v"], "exit_grid_v")
    gap_1 = _number(accelerator["gap_1_mm"], "gap_1_mm")
    gap_2 = _number(accelerator["gap_2_mm"], "gap_2_mm")
    release = _number(accelerator["release_position_in_gap_1_mm"], "release_position_in_gap_1_mm")
    if not repeller > grid_1 > exit_grid or not 0.0 < release < gap_1 or gap_2 <= 0.0:
        raise CandidateContractError("two-zone accelerator voltages or gaps are not physically ordered")
    field_1 = (repeller - grid_1) / gap_1
    field_2 = (grid_1 - exit_grid) / gap_2
    energy = repeller - field_1 * release - exit_grid
    after_1 = energy - (grid_1 - exit_grid)
    if energy <= 0.0 or after_1 <= 0.0:
        raise CandidateContractError("nominal ion cannot cross both accelerator zones")
    root_energy = math.sqrt(energy)
    root_after_1 = math.sqrt(after_1)
    focus = (root_energy ** 3 / field_1) * (
        1.0 / root_after_1 + field_1 / field_2 * (1.0 / root_energy - 1.0 / root_after_1)
    )
    if focus < 0.0:
        raise CandidateContractError("first-order focus is upstream of accelerator exit")
    # Local exit is gap1+gap2; translating it by -(local exit + focus) places focus at z=0.
    return TwoZoneFocus(field_1, field_2, energy, focus, -(gap_1 + gap_2 + focus))


def build_simion_gem(contract: dict[str, Any]) -> str:
    """Emit a reviewable legacy-GEM electrode map with stable electrode IDs.

    This is a topology source, not an approval to run SIMION: CAD dimensions and
    full PA bounds remain subject to the project CAD audit and numerical contract.
    """
    mirror = contract["mirror"]
    stripe = contract["dual_stripe"]
    edges = [_number(value, "electrode_z_edges_mm") for value in mirror["electrode_z_edges_mm"]]
    if len(edges) != 5 or edges != sorted(edges) or edges[0] <= 0.0:
        raise CandidateContractError("five positive ordered mirror electrode edges are required")
    width = _number(stripe["maximum_width_mm"], "maximum_width_mm")
    corridor = _number(stripe["central_grounded_corridor_mm"], "central_grounded_corridor_mm")
    lines = [
        "; MR-TOF Candidate-only topology source for SIMION 2020 legacy GEM.",
        "; Frame: x transverse focus, y drift, z reflection; central plane is z=0.",
        "; IDs 1..5 right mirror, 6..10 left mirror, 11..14 physical dual stripes.",
        "; Stripe pairs (11,12) and (13,14) share independently adjustable voltages.",
        "pa_define(801,801,1601, planar,none,electrostatic,,,0.25,0.25,0.25, surface=none)",
        "locate(400,400,800) {",
    ]
    for index, edge in enumerate(edges, start=1):
        lines.append(f"  e({index}) {{ box3D(-{width},-{width},{edge - 2}, {width},{width},{edge + 2}) }}")
        lines.append(f"  e({index + 5}) {{ box3D(-{width},-{width},{-edge - 2}, {width},{width},{-edge + 2}) }}")
    half = corridor / 2.0
    lines.extend([
        f"  e(11) {{ box3D(-{width},-{width},-{half}, {width},-{width / 2}, {half}) }}",
        f"  e(12) {{ box3D(-{width},{width / 2},-{half}, {width},{width}, {half}) }}",
        f"  e(13) {{ box3D(-{width / 2},-{width},-{half}, {width / 2},-{width / 2}, {half}) }}",
        f"  e(14) {{ box3D(-{width / 2},{width / 2},-{half}, {width / 2},{width}, {half}) }}",
        "  ; The accelerator, prism, grounded guard, detector and raw-node ideal grids are generated only after CAD audit.",
        "}",
        "",
    ])
    return "\n".join(lines)


def write_gem(contract_path: Path, output_path: Path) -> TwoZoneFocus:
    """Validate a contract, emit its GEM source, and return the focus placement."""
    contract = load_contract(contract_path)
    focus = derive_two_zone_focus(contract)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_simion_gem(contract), encoding="utf-8", newline="\n")
    return focus
