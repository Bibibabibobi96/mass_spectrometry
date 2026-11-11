"""SIMION native field views for prepared MR joint-flight consumers."""
from __future__ import annotations

from decimal import Decimal
import math
from pathlib import Path
from typing import Any

from msplatform.backends.comsol.static_field_binding import load_binding, native_response_operator
from msplatform.backends.simion.resources import structural_seed_path
from msplatform.components.parallel_mirror_dual_stripe_mr_tof.candidate_voltage import candidate_authority, PS_GROUPS

# Existing binding protocol provider identifier (see prepare_accelerator_interface).
ION_PROCESSOR = "dual_pressure_rectilinear_ion_processor"


def collision_workbench_layout(binding: dict[str, Any]) -> dict[str, Any]:
    """Project the loader-verified IP collision topology without changing fields."""
    roles = ["global_fallback", "native_corridor", "ion_processor_collision", "detector"]
    overlay = binding.get("collision_overlay")
    if overlay is not None:
        if (overlay.get("schema_version") != 1 or overlay.get("role") != "mrtof_analyzer_collision_overlay"
                or not binding.get("source_descriptor_path")):
            raise ValueError("Collision patch requires the verified overlay descriptor")
        roles.append("analyzer_collision_patch")
    if [item["role"] for item in binding["instances"]] != roles:
        raise ValueError("IP collision instances differ from the verified four/five-role topology")
    priority = dict(schema_version=1, role="mrtof_native_corridor_iob_priority_contract",
        accelerator_provider="dual_pressure_rectilinear_ion_processor",
        instances=[dict(role=role, priority_number=index) for index, role in enumerate(roles, 1)])
    if overlay is not None:
        priority["collision_overlay"] = dict(overlay, pa_path=binding["instances"][4]["pa_path"])
    return dict(roles=roles, priority=priority,
        seed=str(structural_seed_path(len(roles))))


def compile_memory_consumer_crops(contract: dict[str, Any], reference: dict[str, Any],
                                  binding: dict[str, Any]) -> dict[str, Any]:
    """Project frozen stored-x authority into in-memory views of full solved mirrors."""
    targets = contract["simion"]["numerical_profiles"]["native_static_field"]["target_layout"]["windows"]
    reference_windows = reference["field_binding"]["refinement_windows"]
    if len(targets) != len(reference_windows):
        raise ValueError("Frozen MR window policy order differs from its reference")
    available = {window["name"]: window for window in binding["refinement_windows"]}
    crops = {}
    for reference_window, target in zip(reference_windows, targets):
        if "stored_xmax_mm" not in target:
            continue
        name = reference_window["name"]
        if name not in {"positive_integer_grid_a", "negative_integer_grid_a"}:
            raise ValueError("In-memory crop is restricted to mirror field windows")
        level = available[name]
        grid = level["grid"]
        if grid["pitch_mm"][0] != target["pitch_mm"][0]:
            raise ValueError("Memory consumer x pitch differs from the frozen window policy")
        xmax, origin, pitch = (Decimal(str(value)) for value in (
            target["stored_xmax_mm"], grid["origin_mm"][0], grid["pitch_mm"][0]))
        points = (xmax-origin)/pitch
        if origin != 0 or points != points.to_integral_value():
            raise ValueError("Stored mirror x limit must align with its x-mirror grid")
        source_dimensions = list(grid["dimensions"])
        dimensions = [int(points)+1, *source_dimensions[1:]]
        if not 1 < dimensions[0] <= source_dimensions[0]:
            raise ValueError("Mirror consumer crop exceeds the source grid")
        active_xmax = max(Decimal(str(abs(value))) for value in level["active_box_mm"][0])
        if active_xmax+pitch > xmax:
            raise ValueError("Mirror consumer crop lacks the existing gradient halo")
        crops[name] = dict(source_dimensions=source_dimensions, consumer_dimensions=dimensions,
                           start_grid=[0, 0, 0], width_grid=[value-1 for value in dimensions])
    return crops


def validate_candidate_binding(binding: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Keep the actual IP operator fixed while allowing only four P/S coordinates."""
    collision_workbench_layout(binding)
    if baseline.get("collision_overlay") and not binding.get("collision_overlay"):
        raise ValueError("Candidate cannot silently remove the prepared collision overlay")
    if binding.get("collision_overlay"):
        # The public loader verifies the complete overlay and its original four
        # instances. Compare only its source field operator, not collision pitch.
        source = load_binding(Path(binding["source_descriptor_path"]))
        baseline_source = (load_binding(Path(baseline["source_descriptor_path"]))
                           if baseline.get("collision_overlay") else baseline)
        return validate_candidate_binding(source, baseline_source)
    roles = ["global_fallback", "native_corridor", "ion_processor_collision", "detector"]
    if (binding.get("accelerator_provider") != ION_PROCESSOR
            or [r["role"] for r in binding["instances"]] != roles
            or binding["geometry"] != baseline["geometry"]
            or binding["authority"].get("assembly") != baseline["authority"].get("assembly")):
        raise ValueError("Candidate field must retain the prepared IP replacement geometry and four roles")
    values = binding["authority"]["analyzer_electrode_voltages_v"]
    candidate = {key: values[ids[0]-1] for key, ids in PS_GROUPS.items()}
    if binding["authority"] != candidate_authority(baseline["authority"], candidate):
        raise ValueError("Candidate field changed fixed non-P/S or IP15 voltage authority")
    if native_response_operator(binding, baseline["authority"]) != native_response_operator(baseline, baseline["authority"]):
        raise ValueError("Candidate field changed the prepared actual numerical IP operator")
    if (binding["instances"][0]["pa_path"] != binding["sources"]["scalar_pa"]
            or binding["instances"][0]["origin_mm"] != binding["grid"]["origin_mm"]):
        raise ValueError("Candidate global collision instance must reuse its new scalar parent")
    return candidate


def native_projection(binding: dict[str, Any]) -> dict[str, Any]:
    def level(item):
        grid = item["grid"]
        return dict(mode="native_static_pa", scalar_pa=item["sources"]["scalar_pa"],
                    origin_mm=grid["origin_mm"], pitch_mm=grid["pitch_mm"], dimensions=grid["dimensions"], symmetry="x")
    result = level(binding)
    result.update(accelerator_provider=ION_PROCESSOR, assembly_scope="full_c0_ion_processor_replacement",
                  analyzer_voltages_v=binding["authority"]["analyzer_electrode_voltages_v"],
                  collision_pa_path=binding["instances"][1]["pa_path"],
                  collision_geometry_pa_paths=[item["pa_path"] for item in binding["instances"]
                                               if item["role"] in ("ion_processor_collision", "detector")],
                  refinement_windows=[dict(level(item), name=item["name"], active_box_mm=item["active_box_mm"])
                                      for item in binding["refinement_windows"]])
    if binding.get("collision_overlay"):
        result["collision_overlay"] = collision_workbench_layout(binding)["priority"]["collision_overlay"]
    return result


def audit_field_coverage(points: list[dict], windows: list[dict]) -> dict:
    """Prove the actual first-match route and native gradient halo for every point."""
    winners = []
    for point in points:
        position = point["position_mm"]
        winner = next(((rank, window) for rank, window in enumerate(windows)
                       if all(lo <= x <= hi for x, (lo, hi) in zip(position, window["active_box_mm"]))), None)
        if winner is None or winner[1]["name"] != "ion_processor_local":
            raise ValueError("interface audit is not entirely routed through the IP fine field")
        rank, window = winner
        grid = window["grid"]
        for axis, x in enumerate(position):
            q = (x-grid["origin_mm"][axis])/grid["pitch_mm"][axis]
            if axis == 0:
                if grid["symmetry"] != "x" or grid["origin_mm"][0] != 0:
                    raise ValueError("IP fine audit requires its declared x symmetry")
                q = abs(q)
            if ((axis != 0 and math.floor(q)-1 < 0)
                    or math.ceil(q)+1 >= grid["dimensions"][axis]):
                raise ValueError("interface audit lacks the flight adapter gradient halo")
        winners.append(rank)
    if not winners or len(set(winners)) != 1:
        raise ValueError("interface audit requires one actual flight field route")
    return dict(first_match_rank_zero_based=winners[0], field_name="ion_processor_local",
                sample_count=len(points), active_box_and_gradient_halo_verified=True)
