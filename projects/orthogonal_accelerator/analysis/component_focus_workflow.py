"""Compile one provider-owned closed two-zone focus workflow from caller inputs.

The caller supplies a narrow component request and a repository ion-release
specification.  This compiler freezes their resolved campaign and PA plan.  It
never starts SIMION, reads a PA cache, or materializes particles.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import tempfile
from typing import Any

from common.contracts.particle_physics import speed_m_s_from_kinetic_energy_ev
from common.ion_release.release import validate_release_spec
from projects.orthogonal_accelerator.analysis.component_focus_analysis import _load_campaign
from projects.orthogonal_accelerator.analysis.component_focus_pa_plan import derive
from projects.orthogonal_accelerator.analysis.accelerator_time_focus import accelerator_state, time_to_plane_s
from projects.orthogonal_accelerator.simion.two_zone_candidate import _load_geometry_profile


class ComponentFocusWorkflowError(ValueError):
    """Raised when a caller cannot form one closed component workflow."""


_REQUEST_KEYS = {
    "schema_version", "role", "consumer_project_id", "geometry_profile_id",
    "time_focus", "numerics", "acceptance", "simion_projection",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_request(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ComponentFocusWorkflowError("component workflow request is unreadable") from error
    if (not isinstance(value, dict) or set(value) != _REQUEST_KEYS
            or value["schema_version"] != 1
            or value["role"] != "orthogonal_accelerator_component_focus_request"
            or not isinstance(value["consumer_project_id"], str)
            or not value["consumer_project_id"]):
        raise ComponentFocusWorkflowError("component workflow request has missing or unknown fields")
    return value


def _load_release(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        validate_release_spec(value)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise ComponentFocusWorkflowError("component workflow release specification is invalid") from error
    if value["frame_id"] != "orthogonal_accelerator_exit_origin_v1":
        raise ComponentFocusWorkflowError("component workflow release must use the accelerator exit-origin frame")
    if value["particle_count"] != 100:
        raise ComponentFocusWorkflowError("component workflow requires exactly N=100 release states")
    if value["geometry"]["shape"] != "cylinder":
        raise ComponentFocusWorkflowError("component workflow requires a cylindrical release")
    return value


def _number(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise ComponentFocusWorkflowError(f"{label} must be finite")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ComponentFocusWorkflowError(f"{label} must be finite") from error
    if not math.isfinite(result):
        raise ComponentFocusWorkflowError(f"{label} must be finite")
    return result


def _place_release_at_first_gap_center(request: dict[str, Any], release: dict[str, Any]) -> dict[str, Any]:
    """Provider owns the axial source position; consumers supply only its envelope."""
    resolved = json.loads(json.dumps(release))
    profile = _load_geometry_profile(request["geometry_profile_id"])
    resolved["geometry"]["center_mm"][2] = float(profile["gap_2_mm"]) + float(profile["gap_1_mm"]) / 2.0
    return resolved


def _operating_point(request: dict[str, Any], release: dict[str, Any]) -> dict[str, Any]:
    """Derive the nine Fast-Adjust voltages; callers never select them."""
    focus = request["time_focus"]
    if not isinstance(focus, dict) or set(focus) != {
        "final_energy_per_charge_v", "focus_plane_offset_from_exit_mm",
        "gap1_voltage_drop_bounds_v",
    }:
        raise ComponentFocusWorkflowError("component workflow time_focus is invalid")
    energy = _number(focus["final_energy_per_charge_v"], "final_energy_per_charge_v")
    offset = _number(focus["focus_plane_offset_from_exit_mm"], "focus_plane_offset_from_exit_mm")
    bounds = focus["gap1_voltage_drop_bounds_v"]
    if energy <= 0.0 or offset > 0.0 or not isinstance(bounds, list) or len(bounds) != 2:
        raise ComponentFocusWorkflowError("component workflow time_focus bounds are invalid")
    lower, upper = (_number(value, "gap1 voltage-drop bound") for value in bounds)
    if not 0.0 < lower < upper:
        raise ComponentFocusWorkflowError("component workflow time_focus voltage bounds are invalid")
    profile = _load_geometry_profile(request["geometry_profile_id"])
    gap1, gap2 = float(profile["gap_1_mm"]), float(profile["gap_2_mm"])
    center_z = _number(release["geometry"]["center_mm"][2], "release centre z")
    release_position = gap1 + gap2 - center_z
    if not 0.0 < release_position < gap1:
        raise ComponentFocusWorkflowError("release centre is outside provider first acceleration gap")
    target = -offset

    def state_for(drop: float):
        repeller = energy + drop * release_position / gap1
        grid1 = repeller - drop
        return accelerator_state(repeller, grid1, gap1, gap2, exit_v=0.0,
                                 release_position_mm=release_position,
                                 require_downstream_focus=False, zero_tolerance_mm=0.0)

    # A small deterministic bracket scan avoids assuming the caller's old
    # voltage point.  The first physical root is the only candidate in this
    # workflow; no trial PA or flight is needed to derive it.
    previous_drop, previous_value = lower, state_for(lower).first_order_focus_drift_mm - target
    root: float | None = lower if previous_value == 0.0 else None
    if root is None:
        for index in range(1, 201):
            candidate = lower + (upper - lower) * index / 200.0
            value = state_for(candidate).first_order_focus_drift_mm - target
            if value == 0.0 or previous_value * value < 0.0:
                left, right = previous_drop, candidate
                for _ in range(100):
                    middle = (left + right) / 2.0
                    middle_value = state_for(middle).first_order_focus_drift_mm - target
                    if abs(middle_value) <= 1.0e-10:
                        left = right = middle
                        break
                    if previous_value * middle_value <= 0.0:
                        right = middle
                    else:
                        left, previous_value = middle, middle_value
                root = (left + right) / 2.0
                break
            previous_drop, previous_value = candidate, value
    if root is None:
        raise ComponentFocusWorkflowError("provider time-focus voltage root is not bracketed")
    state = state_for(root)
    voltages = [0.0, state.repeller_relative_v, state.intermediate_relative_v, 0.0]
    voltages.extend(state.intermediate_relative_v * index / 6.0 for index in range(5, 0, -1))
    sampling, species, geometry = release["sampling"], release["species"], release["geometry"]
    transverse_speed = speed_m_s_from_kinetic_energy_ev(
        _number(species["mass_amu"], "release mass"),
        _number(sampling["kinetic_energy"]["center_ev"], "release kinetic energy"),
    ) * _number(sampling["nominal_direction"][1], "release nominal y direction")
    transit_s = time_to_plane_s(
        state.nominal_energy_per_charge_v,
        _number(species["mass_amu"], "release mass") / abs(_number(species["charge_state"], "release charge state")),
        state.intermediate_relative_v, state.field1_v_per_mm, state.field2_v_per_mm, -offset,
    )
    instance_center_y = _number(geometry["center_mm"][1], "release centre y") + transverse_speed * transit_s * 500.0
    return {"acceleration_direction": "-z", "focus_plane_offset_from_exit_mm": offset,
            "electrode_voltages_v": voltages, "instance_center_y_mm": instance_center_y}


def compile_workflow(request_path: Path, release_path: Path) -> dict[str, Any]:
    """Return the resolved campaign and PA plan for exactly one child build/flight.

    The release is copied unchanged into the campaign.  The resulting PA plan
    contains only geometry-deriving release fields (the cylinder envelope and
    its required first-gap placement); velocities and particle identities stay
    flight-only and are excluded from the PA cache identity by the existing
    cache module.
    """
    request = _load_request(request_path)
    release = _load_release(release_path)
    resolved_release = _place_release_at_first_gap_center(request, release)
    campaign = {
        "schema_version": 1,
        "role": "orthogonal_accelerator_component_focus_campaign",
        "geometry_profile_id": request["geometry_profile_id"],
        "release_spec": resolved_release,
        "operating_point": _operating_point(request, resolved_release),
        "numerics": request["numerics"],
        "acceptance": request["acceptance"],
        "simion_projection": request["simion_projection"],
    }
    # Reuse the existing campaign validator before deriving the one PA plan.
    # It also rejects requests that do not match the provider-owned profile.
    with tempfile.TemporaryDirectory(prefix="orthogonal_accelerator_focus_") as directory:
        temporary_campaign = Path(directory) / "campaign.json"
        try:
            temporary_campaign.write_text(json.dumps(campaign, indent=2) + "\n", encoding="utf-8")
            _load_campaign(temporary_campaign)
            plan = derive(temporary_campaign)
        except OSError as error:
            raise ComponentFocusWorkflowError("component workflow cannot write its resolved campaign") from error
    return {
        "schema_version": 1,
        "role": "orthogonal_accelerator_component_focus_workflow_plan",
        "status": "derived",
        "consumer_project_id": request["consumer_project_id"],
        "qualification": "provider_owned_native_pa_and_n100_component_flight_pending",
        "request_sha256": _sha256(request_path),
        "release_spec_sha256": _sha256(release_path),
        "release_cache_effect": "run_only_unless_the_provider_plan_changes_from_the_release_cylinder_envelope_or_first_gap_placement",
        "campaign": campaign,
        "pa_plan": plan,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--release-spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = compile_workflow(args.request, args.release_spec)
    except (OSError, ValueError) as error:
        print(f"ACCELERATOR_COMPONENT_FOCUS_WORKFLOW=FAIL ERROR={error}")
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("ACCELERATOR_COMPONENT_FOCUS_WORKFLOW=PASS "
          f"CONSUMER={result['consumer_project_id']} "
          f"PA_PROFILE={result['pa_plan']['geometry_profile_id']} N=100")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
