"""Validate the solver-neutral S2 passive connector geometry contract."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

try:
    from . import build_interface_handoff
except ImportError:  # Direct script execution from the project Static gate.
    import build_interface_handoff


PROJECT_ROOT = Path(__file__).parents[1]
DEFAULT_CONTRACT = PROJECT_ROOT / "config" / "rf_to_oatof_s2_passive_connector.json"


def _load_relative(path: str) -> dict[str, Any]:
    resolved = (PROJECT_ROOT / path).resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _assert_close(actual: float, expected: float, name: str) -> None:
    if not math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(f"{name} differs: expected {expected}, got {actual}")


def validate_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    """Validate inherited geometry, rigid poses and fail-closed S2 permissions."""
    contract = json.loads(path.read_text(encoding="utf-8"))
    if contract.get("role") != "rf_to_oatof_s2_passive_grounded_connector_candidate":
        raise ValueError("S2 connector role differs")
    if contract.get("stage") != "S2":
        raise ValueError("S2 connector stage differs")

    stage_plan = _load_relative(contract["inputs"]["stage_plan"])
    if stage_plan.get("current_stage") != "S2":
        raise ValueError("stage plan has not advanced to S2")
    stage = next(item for item in stage_plan["stages"] if item["id"] == "S2")
    if stage.get("status") != "static_contract_ready_function_runtime_not_started":
        raise ValueError("S2 stage status differs")

    s1 = _load_relative(contract["inputs"]["s1_joint_field"])
    interface = _load_relative(contract["inputs"]["interface_reference"])
    registration = contract["nominal_registration"]
    gap_mm = float(registration["connector_gap_mm"])
    _assert_close(gap_mm, 1.0, "connector gap")
    if gap_mm <= 0.0:
        raise ValueError("S2 connector gap must be positive")

    rotation = registration["source_component_pose"]["rotation_component_to_instrument"]
    build_interface_handoff.validate_rotation_matrix(rotation)
    if rotation != s1["nominal_registration"]["source_component_pose"]["rotation_component_to_instrument"]:
        raise ValueError("S2 source rotation must inherit S1")

    target_center = interface["boundaries"]["target_entry_surface"]["center_mm"]
    if registration["target_entry_center_instrument_mm"] != target_center:
        raise ValueError("S2 target entry center differs from the interface reference")
    expected_source_center = [target_center[0] - gap_mm, target_center[1], target_center[2]]
    if registration["source_exit_center_instrument_mm"] != expected_source_center:
        raise ValueError("S2 source exit center does not realize the frozen gap")

    local_center = registration["source_exit_center_local_mm"]
    rotated_center = [sum(rotation[row][col] * local_center[col] for col in range(3)) for row in range(3)]
    expected_translation = [expected_source_center[index] - rotated_center[index] for index in range(3)]
    for index, value in enumerate(registration["source_component_pose"]["translation_mm"]):
        _assert_close(value, expected_translation[index], f"source translation[{index}]")

    geometry = contract["passive_connector_geometry"]
    source_radius = float(interface["boundaries"]["source_exit_surface"]["physical_aperture"]["radius_mm"])
    _assert_close(geometry["upstream_clear_aperture"]["radius_mm"], source_radius, "upstream aperture radius")
    _assert_close(geometry["cavity"]["inner_radius_mm"], source_radius, "connector cavity radius")
    _assert_close(geometry["length_mm"], gap_mm, "connector length")
    _assert_close(geometry["axial_extent_x_mm"][1] - geometry["axial_extent_x_mm"][0], gap_mm, "connector axial extent")

    downstream = geometry["downstream_entry_aperture"]
    _assert_close(downstream["full_width_y_mm"], s1["port_sweep"]["selected_n100_candidate_full_width_y_mm"], "oa port width")
    _assert_close(downstream["full_height_z_mm"], s1["port_sweep"]["full_height_z_mm"], "oa port height")
    if downstream["center_mm"] != target_center:
        raise ValueError("S2 downstream aperture center differs")
    if geometry["secondary_internal_aperture_allowed"] or geometry["active_electrode_allowed"]:
        raise ValueError("S2 must remain a passive connector without a second aperture")

    fields = contract["field_ownership"]
    _assert_close(fields["common_ground_V"], 0.0, "common ground")
    if fields["oa_extraction_pulse_included"]:
        raise ValueError("S2 must not include oa pulse capture")
    permissions = contract["permissions"]
    if permissions["field_solve_allowed"] or permissions["particle_runtime_allowed"]:
        raise ValueError("S2 runtime must remain blocked before the geometry builder exists")
    if permissions["s2_stage_pass_allowed"] or permissions["formal_promotion_allowed"]:
        raise ValueError("Static S2 contract cannot authorize qualification or promotion")
    return contract


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    args = parser.parse_args()
    contract = validate_contract(args.contract)
    gap_mm = contract["nominal_registration"]["connector_gap_mm"]
    print(
        "S2_PASSIVE_CONNECTOR=PASS "
        f"GAP_MM={gap_mm:g} FIELD_SOLVE_ALLOWED=false PARTICLE_RUNTIME_ALLOWED=false"
    )


if __name__ == "__main__":
    main()
