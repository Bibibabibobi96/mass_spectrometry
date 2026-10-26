"""Audit one fixed-grid S1/S2/P1/P2 finite-3-D workpoint step.

The five input runs are one baseline and four positive single-axis voltage
perturbations.  They must share geometry, source, mirror, accelerator, target K,
and trajectory numerics.  This module does not launch SIMION; it turns those
immutable observations into a rank-audited, bounded linear correction.  A
previous fine-grid Jacobian may also be transported to a new baseline when the
field geometry, mesh, mirror/Stripe authority, targets, and energy are
unchanged.  That path is only a seed: it always requires one real center-flight
confirmation before the proposal can be accepted.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
from dataclasses import asdict
import json
import math
import re
from pathlib import Path
import shutil
from typing import Any, Mapping, Sequence

import numpy as np

from common.contracts.file_identity import file_sha256
from common.contracts.verify_run_manifest import record_path, verify_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_mirror_stripe_l0 import (
    classify_constraint_system,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_operating_point import (
    _load_object,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial import (
    _bunch_center_source_state, _source_release_record, _collision_geometry_projection,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import (
    load_binding, _record, _validate_native_surface_absence, native_refine_numerics,
    validate_native_consumer_view, load_native_response_basis,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider import PS_GROUPS, candidate_authority, compile_request
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.fixed_mirror_stripe_operating_point import _named_record


def _trajectory_physics_identity(
    manifest: Mapping[str, Any], raw_sha256: str,
    record_name: str = "trajectory_numerics_contract",
) -> str:
    """Hash flight physics, excluding the downstream solver/controller policy."""
    record = manifest.get("inputs", {}).get(record_name)
    if not isinstance(record, Mapping):
        raise CandidateContractError(f"trial manifest lacks its {record_name}")
    path = record_path(record)
    verify_record(record_name, record, base_dir=path.parent)
    if file_sha256(path).lower() != str(raw_sha256).lower():
        raise CandidateContractError(f"trial {record_name} identity differs from materialization")
    contract = _load_object(path)
    profile = contract.pop("downstream_fixed_grid_workpoint_profile", None)
    if not isinstance(profile, Mapping):
        raise CandidateContractError("trajectory contract lacks downstream workpoint profile")
    # This declared millimetre coordinate is a real number. PS OA pose
    # resolution may serialize -55 as -55.0 without changing flight physics.
    contract["accelerator"]["focus_y_anchor"]["project_y_mm"] = _finite(
        contract["accelerator"]["focus_y_anchor"]["project_y_mm"], "accelerator y anchor mm")
    if record_name == "reviewed_geometry_contract":
        # Review preserves its raw seal, but the flight consumes the resolved OA
        # position override. Other reviewed physics remains part of the identity.
        resolved_record = manifest.get("inputs", {}).get("trajectory_numerics_contract")
        if not isinstance(resolved_record, Mapping):
            raise CandidateContractError("trial lacks its resolved trajectory contract")
        resolved_path = record_path(resolved_record)
        verify_record("trajectory_numerics_contract", resolved_record, base_dir=resolved_path.parent)
        resolved = _load_object(resolved_path)
        try:
            anchor = resolved["accelerator"]["focus_y_anchor"]["project_y_mm"]
            contract["accelerator"]["focus_y_anchor"]["project_y_mm"] = _finite(
                anchor, "resolved accelerator y anchor mm")
        except (KeyError, TypeError) as exc:
            raise CandidateContractError("trial contracts lack their accelerator y anchor") from exc
    encoded = json.dumps(contract, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


UNKNOWN_NAMES = (
    "stripe_1_voltage_v",
    "stripe_2_voltage_v",
    "prism_1_voltage_v",
    "prism_2_voltage_v",
)
RESIDUAL_NAMES = (
    "P1_P2_positive_mirror_turn_y_mm",
    "P1_P2_P2_shield_low_field_signed_vy_over_vz",
    "Stripe_slow_turn_y_minus_L_mm",
    "Stripe_target_phase_y_minus_origin_mm",
)


def workpoint_residual_names(materialization: Mapping[str, Any]) -> tuple[str, ...]:
    """Select explicit scientific residual units without relabelling old angle rows."""
    if materialization.get("prism_handoff_target") is not None:
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_l0 import CONVERGING_PRISM_ENERGY_RESIDUAL
        return (RESIDUAL_NAMES[0], CONVERGING_PRISM_ENERGY_RESIDUAL, *RESIDUAL_NAMES[2:])
    return RESIDUAL_NAMES


def _finite(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise CandidateContractError(f"{label} must be finite")
    return float(value)


def _static_solver_numerics(solver: Mapping[str, Any]) -> dict[str, Any]:
    """Project sealed Study/solver trees onto the provider's named readback in volts."""
    keys = (
        "active_mesh_tag", "fc_solver", "fc_active", "iterative_active", "iterative_solver", "multigrid_active",
        "mg_prefun", "mg_cycle", "mg_amgauto", "mg_loweramg", "mg_prefermatfree",
        "stationary_control", "stationary_stol", "study_usestol", "study_stol",
        "scale_method", "scale_v", "field_scale_method", "rhob", "errorchk", "prefuntype", "nlinnormuse",
    )
    if "solver" not in solver:
        extra = ("fine_order", "fine_discretization", "manual_levels", "coarse_mesh", "coarse_discretization",
                 "coarse_order", "mg_casegen", "mg_caseuse", "mg_caseassem", "mg_levels", "mg_assemble",
                 "mg_keep", "matrix_format", "iterative_active_children", "pr", "po", "coarse_active_children", "coarse_solver")
        return {key: solver[key] for key in (*keys, *extra) if key in solver}
    nodes = {solver["study_step"]["path"]: solver["study_step"]}
    pending = list(solver["solver"])
    while pending:
        node = pending.pop()
        if node["path"] in nodes:
            raise CandidateContractError("duplicate sealed solver node")
        nodes[node["path"]] = node
        pending.extend(node["children"])

    def value(path: str, name: str) -> Any:
        rows = [p for p in nodes[path]["properties"] if p["name"] == name]
        if len(rows) != 1 or rows[0]["read_error"]:
            raise CandidateContractError(f"sealed solver property unavailable: {path}/{name}")
        return rows[0]["value"]

    stat, fc, it, mg, var = "sol1/s1", "sol1/s1/fc1", "sol1/s1/i1", "sol1/s1/i1/mg1", "sol1/v1"
    if value(it, "linsolver") != "cg":
        raise CandidateContractError("ordinary scalar solver tree is not the reviewed CG/mg1 path")
    mesh = value("std1/stat", "mesh")
    if len(mesh) != 2 or mesh[0] != "geom1":
        raise CandidateContractError("sealed Study does not bind one geom1 mesh")
    properties = {
        "fc_solver": (fc,"linsolver"), "iterative_solver": (it,"linsolver"),
        "mg_prefun": (mg,"prefun"), "mg_cycle": (mg,"mgcycle"), "mg_amgauto": (mg,"amgauto"),
        "mg_loweramg": (mg,"loweramg"), "mg_prefermatfree": (mg,"prefermatfree"),
        "stationary_control": (stat,"control"), "stationary_stol": (stat,"stol"),
        "study_stol": ("std1/stat","stol"), "scale_method": (var,"scalemethod"), "scale_v": (var,"scaleval"),
        "field_scale_method": (var+"/comp1_V","scalemethod"), "rhob": (it,"rhob"),
        "errorchk": (it,"errorchk"), "prefuntype": (it,"prefuntype"), "nlinnormuse": (it,"nlinnormuse"),
    }
    result = {key: value(*pair) for key, pair in properties.items()}
    use_stol = value("std1/stat", "usestol")
    if use_stol not in ("on", "off"):
        raise CandidateContractError("sealed Study tolerance switch is invalid")
    result.update(active_mesh_tag=mesh[1], fc_active=nodes[fc]["is_active"],
                  iterative_active=nodes[it]["is_active"], multigrid_active=nodes[mg]["is_active"],
                  study_usestol=use_stol == "on")
    return result


def _static_field_problem(materialization: Mapping[str, Any], source_diagnostic: dict[str, Any] | None = None,
                          *, trial_manifest: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    """Bind independently sealed candidate fields to one saved-mesh/numerics family."""
    field = materialization.get("field_binding")
    if not isinstance(field, Mapping) or field.get("mode") not in (
            "comsol_static_scalar_v", "native_static_pa"):
        return None
    binding = (_sealed_native_trial_binding(field, trial_manifest, materialization)
               if field["mode"] == "native_static_pa" and trial_manifest is not None
               else load_binding(Path(field["path"])))
    if field["mode"] == "native_static_pa" and trial_manifest is not None and source_diagnostic is not None:
        source_diagnostic.update(scope="sealed_native_trial_metadata__not_payload_availability",
                                 binding_record=trial_manifest["inputs"]["static_field_binding"])
    if field["mode"] == "native_static_pa":
        problem = _native_static_binding_problem(binding, materialization, canonical_consumer_layout=True)
        if source_diagnostic is not None:
            source_diagnostic["consumed_ps_voltages_v"] = [
                binding["authority"]["analyzer_electrode_voltages_v"][ids[0]-1]
                for ids in PS_GROUPS.values()]
        if binding.get("consumer_view") and source_diagnostic is not None:
            source_diagnostic.update(consumer_view=binding["consumer_view"],
                stored_layout=[dict(grid=level["grid"], active_box_mm=level.get("active_box_mm"))
                               for level in (binding, *binding["refinement_windows"])])
    elif binding.get("representation") in (
        "exploratory_affine_s_responses", "exploratory_affine_ps_responses",
        "exploratory_materialized_affine_s_responses", "exploratory_materialized_affine_ps_responses",
    ):
        expected = binding["authority"]["analyzer_electrode_voltages_v"]
        if materialization["analyzer_electrode_voltages_v"] != expected:
            raise CandidateContractError("combined field voltages differ from materialization")
        requested = [*materialization["stripe_biases_v"], *materialization["prism_voltages_v"]]
        if any(any(float(expected[i-1]) != float(value) for i in ids)
               for value, ids in zip(requested, PS_GROUPS.values(), strict=True)):
            raise CandidateContractError("combined field P/S voltages differ from materialization")
        # Consumption representation and source terms stay in the materialization;
        # the frozen scientific problem is the same validated static field family.
        problem = dict(binding["response_family"])
    else:
        problem = _static_binding_problem(binding, materialization, field["path"], source_diagnostic)
    # The binding/projection verifies each sealed geometry file. Compare its
    # scientific content here, not the exporter/provider JSON serialization;
    # original byte identities remain in the binding/materialization records.
    geometry = json.dumps(binding["geometry"], sort_keys=True, separators=(",", ":"), allow_nan=False)
    problem["geometry_sha256"] = hashlib.sha256(geometry.encode("utf-8")).hexdigest()
    return problem


def _sealed_native_trial_binding(field: Mapping[str, Any], manifest: Mapping[str, Any],
                                 materialization: Mapping[str, Any]) -> dict[str, Any]:
    """Read sealed flight metadata without reopening its historical PA payloads.

    This is a historical analysis projection, not permission for a new flight;
    live load_binding continues to require all payloads.
    """
    record = manifest.get("inputs", {}).get("static_field_binding")
    if not isinstance(record, Mapping) or Path(record["path"]).resolve() != Path(field["path"]).resolve():
        raise CandidateContractError("trial lacks its bound static field descriptor")
    verify_record("static_field_binding", record, base_dir=Path(field["path"]).parent)
    descriptor = _load_object(Path(field["path"]))
    if descriptor.get("role") != "mrtof_native_static_field_binding" or descriptor.get("schema_version") != 1:
        raise CandidateContractError("trial native descriptor identity differs")

    def sealed_record(owner: str, path: str) -> dict[str, Any]:
        evidence = _load_object(Path(owner))
        resolved_path = Path(path).resolve()
        matches = [r for r in [*evidence["outputs"], *evidence.get("inputs", {}).values()]
                   if isinstance(r, Mapping) and Path(r.get("path", "")).resolve() == resolved_path]
        if evidence.get("status") != "success" or not matches or len({(r["bytes"], r["sha256"]) for r in matches}) != 1:
            raise CandidateContractError("native source lacks a unique successful sealed record")
        return matches[0]

    levels = [field, *field["refinement_windows"]]
    specs = [descriptor["parent"], *descriptor["refinement_windows"]]
    if len(levels) != len(specs):
        raise CandidateContractError("native trial window count differs from descriptor")
    resolved, plans = [], []
    for index, (level, spec) in enumerate(zip(levels, specs, strict=True)):
        if level["grid"] != spec["grid"] or Path(level["manifest"]).resolve() != Path(spec["manifest"]).resolve():
            raise CandidateContractError("native trial grid or source differs from descriptor")
        documents = {}
        for name, key in (("scalar_pa", "pa_path"), ("surface", "surface_path"),
                          ("voltage_authority", "voltage_authority_path"),
                          ("geometry_authority", "geometry_authority_path"), ("numerical_plan", "numerical_plan_path")):
            path = spec[key]
            if name == "surface" and path is None:
                if level["sources"][name] is not None or level["records"][name] is not None:
                    raise CandidateContractError("native trial surface absence differs from descriptor")
                _validate_native_surface_absence(Path(spec["manifest"]), Path(spec["pa_path"]))
                continue
            frozen = level["records"][name]
            actual = sealed_record(spec["manifest"], path)
            if (Path(level["sources"][name]).resolve() != Path(path).resolve()
                    or Path(frozen["path"]).resolve() != Path(path).resolve()
                    or any(frozen[k] != actual[k] for k in ("bytes", "sha256"))):
                raise CandidateContractError("native trial source record differs from descriptor")
            if name not in ("scalar_pa", "surface"):
                verify_record(name, frozen, base_dir=Path(path).parent)
                documents[name] = _load_object(Path(path))
        plan, grid = documents["numerical_plan"], level["grid"]
        if (plan["pitch_mm"] != grid["pitch_mm"] or plan["dimensions"] != grid["dimensions"]
                or plan["box_mm"][:3] != grid["origin_mm"]):
            raise CandidateContractError("native trial numerical plan differs from grid")
        boundary = plan.get("boundary_mode")
        if index == 0 and boundary is None and "Five outer e(0) faces, no x=0 wall" in plan.get("physical_expression", ""):
            boundary = "grounded_enclosure"
        if boundary != ("x_mirror_five_faces" if index else "grounded_enclosure"):
            raise CandidateContractError("native trial boundary identity differs")
        item = dict(level, authority=documents["voltage_authority"], geometry=documents["geometry_authority"],
                    native_solver_numerics=dict(native_refine_numerics(plan, Path(spec["manifest"])),
                                                boundary_mode=boundary))
        if (not index and ("native_solver_numerics" in level or "numerical_contract_path" in plan)
                and level.get("native_solver_numerics") != item["native_solver_numerics"]):
            raise CandidateContractError("native trial parent stopping identity differs")
        if index:
            if (any(level[k] != item[k] for k in ("authority", "geometry", "native_solver_numerics"))
                    or any(level[k] != spec[k] for k in ("name", "active_box_mm"))
                    or item["authority"] != resolved[0]["authority"] or item["geometry"] != resolved[0]["geometry"]
                    or Path(plan["parent_manifest"]).resolve() != Path(spec["parent_manifest"]).resolve()):
                raise CandidateContractError("native trial window lineage differs")
        resolved.append(item)
        plans.append(plan)
    # Resolve the same sealed (manifest, PA) ancestry as the live native loader;
    # first-match flight priority is not parent-before-child solve order.
    identities = [(Path(s["manifest"]).resolve(), Path(s["pa_path"]).resolve()) for s in specs]
    parents = {}
    for index, plan in enumerate(plans[1:], 1):
        identity = (Path(plan["parent_manifest"]).resolve(), Path(plan["parent_pa"]).resolve())
        if identity not in identities:
            raise CandidateContractError("native trial window parent differs from declared sealed levels")
        parent_index = identities.index(identity)
        source_grid = resolved[parent_index]["grid"]
        if any(resolved[other]["grid"] != source_grid for other, value in enumerate(identities) if value == identity):
            raise CandidateContractError("native trial boundary source aliases have conflicting grids")
        parents[index] = parent_index
        if any(plan["box_mm"][a] < source_grid["origin_mm"][a] or plan["box_mm"][a+3] >
               source_grid["origin_mm"][a] + (source_grid["dimensions"][a]-1)*source_grid["pitch_mm"][a]
               for a in range(3)):
            raise CandidateContractError("native trial window extends outside its boundary source domain")
    for index in parents:
        visited = set()
        while index:
            if index in visited:
                raise CandidateContractError("native trial boundary source contains a self-reference or cycle")
            visited.add(index)
            index = parents[index]
    instances = [dict(i, record=sealed_record(i["manifest"], i["pa_path"])) for i in descriptor["instances"]]
    config_record = manifest["run_config"]
    config_path = record_path(config_record)
    verify_record("run_config", config_record, base_dir=config_path.parent)
    config = _load_object(config_path)
    flown = config.get("provenance", {}).get("upstream_manifest_verification", {}).get("geometry", {}).get("instances")
    def instance_identity(item: Mapping[str, Any]) -> dict[str, Any]:
        return dict(role=item["role"], origin_mm=item["origin_mm"],
                    manifest=str(Path(item["manifest"]).resolve()), pa_path=str(Path(item["pa_path"]).resolve()),
                    record=dict(path=str(Path(item["record"]["path"]).resolve()),
                                bytes=item["record"]["bytes"], sha256=item["record"]["sha256"]))
    if (not isinstance(flown, list) or [instance_identity(i) for i in flown] != [instance_identity(i) for i in instances]
            or materialization.get("collision_geometry") != _collision_geometry_projection(resolved[0]["geometry"])):
        raise CandidateContractError("native trial collision instances or materialized solids differ")
    return dict(resolved[0], mode="native_static_pa", instances=instances, refinement_windows=resolved[1:],
                **({"consumer_view": validate_native_consumer_view(descriptor["consumer_view"])}
                   if "consumer_view" in descriptor else {}))


def _native_original_consumer_layout(binding: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Trace sealed crop/composition metadata, never the historical PA payloads."""
    view = validate_native_consumer_view(binding.get("consumer_view"))
    levels = [binding, *binding["refinement_windows"]]
    original, current_plans, original_plans = [], [], []

    def document(owner: Path, path: Path) -> dict[str, Any]:
        verify_record("native_consumer_provenance", _record(owner, path), base_dir=owner.parent)
        return _load_object(path)

    for level in levels:
        owner = Path(level["manifest"])
        plan_path = Path(level["sources"]["numerical_plan"])
        plan = document(owner, plan_path)
        current_plans.append(plan)
        visited = set()
        while True:
            identity = str(plan_path.resolve())
            if identity in visited:
                raise CandidateContractError("consumer view source plan cycle")
            visited.add(identity)
            numerics = dict(native_refine_numerics(plan, owner), boundary_mode=plan.get("boundary_mode"))
            if (plan.get("consumer_view") != view or plan.get("refine_performed") is not False
                    or numerics != level["native_solver_numerics"]):
                raise CandidateContractError("consumer view source solver identity differs")
            if "consumer_view_source" in plan:
                break
            receipt = document(owner, Path(plan["materialization_receipt_path"]))
            if receipt.get("status") != "PASS":
                raise CandidateContractError("consumer view composition lacks a successful receipt")
            owner = Path(plan["source_solve_manifest"])
            plan_path = Path(plan["source_solve_plan_path"])
            plan = document(owner, plan_path)
        spec = plan["consumer_view_source"]
        source_owner = Path(spec["manifest"])
        source_plan = document(source_owner, Path(spec["numerical_plan_path"]))
        source_geometry = document(source_owner, Path(spec["geometry_authority_path"]))
        grid = spec["grid"]
        expected = copy.deepcopy(grid)
        expected["dimensions"][0] = 5
        receipt = document(owner, Path(plan["consumer_view_receipt_path"]))
        source_numerics = dict(native_refine_numerics(source_plan, source_owner),
                               boundary_mode=source_plan.get("boundary_mode"))
        if (view is None or grid.get("symmetry") != "x" or grid["origin_mm"][0] != 0
                or grid["dimensions"][0] <= 5 or level["grid"] != expected
                or source_plan["dimensions"] != grid["dimensions"]
                or source_plan["pitch_mm"] != grid["pitch_mm"] or source_plan["box_mm"][:3] != grid["origin_mm"]
                or source_numerics != level["native_solver_numerics"] or source_geometry != level["geometry"]
                or receipt.get("status") != "PASS" or receipt.get("refine_after_crop") is not False
                or receipt.get("full_dimensions") != grid["dimensions"]
                or receipt.get("consumer_dimensions") != expected["dimensions"]):
            raise CandidateContractError("consumer view differs from original three-dimensional consumption")
        if "name" in level and (spec["name"] != level["name"] or level["active_box_mm"] != [
                [-2*grid["pitch_mm"][0], 2*grid["pitch_mm"][0]], *spec["active_box_mm"][1:]]):
            raise CandidateContractError("consumer view changes ordered window coverage")
        original.append(spec)
        original_plans.append(source_plan)
    current_ids = [(Path(x["manifest"]).resolve(), Path(x["sources"]["scalar_pa"]).resolve()) for x in levels]
    original_ids = [(Path(x["manifest"]).resolve(), Path(x["pa_path"]).resolve()) for x in original]
    for current, prior in zip(current_plans[1:], original_plans[1:], strict=True):
        parent = (Path(current["parent_manifest"]).resolve(), Path(current["parent_pa"]).resolve())
        old_parent = (Path(prior["parent_manifest"]).resolve(), Path(prior["parent_pa"]).resolve())
        if (parent not in current_ids or old_parent not in original_ids
                or current_ids.index(parent) != original_ids.index(old_parent)):
            raise CandidateContractError("consumer view changes parent boundary ancestry")
    return original


def assert_native_provider_storage_resume(prior: Mapping[str, Any], current: Mapping[str, Any]) -> None:
    """Allow only an exact full-bank to sealed centre-view storage substitution."""
    if prior == current:
        return
    locators = {"source_binding_path", "source_field_manifest", "numerical_contract_path", "response_basis_paths"}
    if (prior.get("role") != "mrtof_native_static_field_provider_request"
            or current.get("role") != prior["role"]
            or {k: v for k, v in prior.items() if k not in locators}
            != {k: v for k, v in current.items() if k not in locators}
            or set(prior.get("response_basis_paths", {})) != set(current.get("response_basis_paths", {}))):
        raise CandidateContractError("static recovery differs beyond storage view locators")
    old_contract = _load_object(Path(prior["numerical_contract_path"]))
    new_contract = _load_object(Path(current["numerical_contract_path"]))
    profile = new_contract["simion"]["numerical_profiles"]["native_static_field"]
    if validate_native_consumer_view(profile.pop("consumer_view", None)) is None or new_contract != old_contract:
        raise CandidateContractError("static recovery numerical contract differs beyond consumer view")
    baseline = load_binding(Path(current["source_binding_path"]))

    def same_source(previous_path: str, candidate: Mapping[str, Any]) -> None:
        previous = _load_object(Path(previous_path))
        originals = _native_original_consumer_layout(candidate)
        expected = [previous["parent"], *previous["refinement_windows"]]
        if (previous.get("consumer_view") or originals != expected
                or [{k: instance[k] for k in ("role", "manifest", "pa_path", "origin_mm")}
                    for instance in candidate["instances"]] != previous["instances"]):
            raise CandidateContractError("static recovery view is not the prior exact source and collision layout")
        authority_path = Path(expected[0]["voltage_authority_path"])
        owner = Path(expected[0]["manifest"])
        verify_record("prior_authority", _record(owner, authority_path), base_dir=owner.parent)
        if candidate["authority"] != _load_object(authority_path):
            raise CandidateContractError("static recovery storage view changes its source voltage anchor")

    same_source(prior["source_binding_path"], baseline)
    previous = _load_object(Path(prior["source_binding_path"]))
    if (Path(prior["source_field_manifest"]).resolve() != Path(previous["parent"]["manifest"]).resolve()
            or Path(current["source_field_manifest"]).resolve() != Path(baseline["manifest"]).resolve()):
        raise CandidateContractError("static recovery source manifest differs")
    for axis, path in current.get("response_basis_paths", {}).items():
        response = load_native_response_basis(Path(path), baseline)
        previous_path = prior["response_basis_paths"][axis]
        previous = _load_object(Path(previous_path))
        if response["response_basis"] != previous.get("response_basis"):
            raise CandidateContractError("static recovery response definition differs")
        same_source(previous_path, response)


def _native_static_binding_problem(binding: Mapping[str, Any], materialization: Mapping[str, Any], *,
                                   canonical_consumer_layout: bool = False) -> dict[str, Any]:
    """Keep native discretization fixed while allowing the existing four P/S axes."""
    if binding.get("mode") != "native_static_pa":
        raise CandidateContractError("native trial must consume its actual native static binding")
    expected = binding["authority"]["analyzer_electrode_voltages_v"]
    ps_ids = {electrode for ids in PS_GROUPS.values() for electrode in ids}
    recorded = materialization["analyzer_electrode_voltages_v"]
    # Same 1e-9 V compatibility as static_field_binding.validate_voltages,
    # confined to the four adjustable P/S axes; other electrodes stay exact.
    if len(recorded) != len(expected) or any(
            (not math.isclose(float(a), float(b), rel_tol=0, abs_tol=1e-9)
             if i in ps_ids else a != b)
            for i, (a, b) in enumerate(zip(recorded, expected), 1)):
        raise CandidateContractError("native static field full voltages differ from materialization")
    requested = [*materialization["stripe_biases_v"], *materialization["prism_voltages_v"]]
    for value, ids in zip(requested, PS_GROUPS.values(), strict=True):
        if any(not math.isclose(float(expected[i - 1]), float(value), rel_tol=0, abs_tol=1e-9) for i in ids):
            raise CandidateContractError("native static field P/S voltages differ from materialization")
    authority = copy.deepcopy(binding["authority"])
    for ids in PS_GROUPS.values():
        for electrode in ids:
            authority["analyzer_electrode_voltages_v"][electrode - 1] = None
    # A changed-voltage parent PA has different bytes but the same collision
    # geometry. Its grid/geometry are already bound above; the other independent
    # collision instances must remain exactly the same sealed assets.
    collisions = [dict(role=i["role"], origin_mm=i["origin_mm"],
                       record={key: i["record"][key] for key in ("bytes", "sha256")} if n else None)
                  for n, i in enumerate(binding["instances"])]
    layout = [binding, *binding.get("refinement_windows", [])]
    if canonical_consumer_layout and binding.get("consumer_view"):
        center = _bunch_center_source_state(dict(materialization))
        position = center.position_mm if center else materialization.get("source_position_project_mm")
        velocity = center.velocity_mm_per_us if center else materialization.get("source_direction_project")
        if (not isinstance(position, (list, tuple)) or not isinstance(velocity, (list, tuple))
                or len(position) != 3 or len(velocity) != 3 or position[0] != 0 or velocity[0] != 0):
            raise CandidateContractError("consumer view scientific projection requires actual source x=0 and vx=0")
        layout = _native_original_consumer_layout(binding)
    return dict(mode="native_static_pa", fixed_authority=authority,
                grid=layout[0]["grid"],
                refinement_windows=[dict(name=original["name"], grid=original["grid"], active_box_mm=original["active_box_mm"],
                                         solver_numerics=w["native_solver_numerics"])
                                    for w, original in zip(binding.get("refinement_windows", []), layout[1:], strict=True)],
                solver_numerics=binding["native_solver_numerics"], collision_instances=collisions)


def _parameterized_static_plan(binding: Mapping[str, Any], manifest: Path,
                               records: Mapping[str, Any], diagnostic: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Separate the saved mesh origin from a real parameterized solve; no equivalence claim."""
    def read_sealed(owner: Path, path: Path) -> dict[str, Any]:
        _record(owner, path)
        return _load_object(path)

    export_manifest = Path(records["source_export_manifest"]["path"])
    source_manifest = Path(records["parameter_source_manifest"]["path"])
    read_sealed(manifest, export_manifest)
    read_sealed(manifest, source_manifest)
    export = read_sealed(export_manifest, export_manifest.parent / "inputs" / "diagnostic_plan.json")
    solve = read_sealed(source_manifest, source_manifest.parent / "inputs" / "diagnostic_plan.json")
    result = read_sealed(source_manifest, source_manifest.parent / "results" / "result.json")
    authority = read_sealed(source_manifest, source_manifest.parent / "inputs" / "frozen_input.json")
    geometry = read_sealed(source_manifest, source_manifest.parent / "inputs" / "resolved_geometry.json")
    parameter = read_sealed(source_manifest, source_manifest.parent / "results" / "parameter_readback.json")
    solved = read_sealed(source_manifest, source_manifest.parent / "results" / "solved_parameter_readback.json")
    changed_ids = solve["parameter"]["electrode_ids"]
    if "qualification_candidate" in solve:
        source = read_sealed(source_manifest, source_manifest.parent / "inputs" / "source_authority.json")
        candidate = read_sealed(source_manifest, source_manifest.parent / "inputs" / "candidate_affine_binding.json")
        try:
            target = candidate_authority(source, candidate["target_ps_voltages_v"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CandidateContractError("parameterized field lacks its declared PS target") from exc
        changed_ids = [i for i, (old, new) in enumerate(zip(
            source["analyzer_electrode_voltages_v"], target["analyzer_electrode_voltages_v"], strict=True), 1) if old != new]
        if (target != authority or solve["parameter"]["electrode_ids"] not in [list(ids) for ids in PS_GROUPS.values()]
                or not set(solve["parameter"]["electrode_ids"]) <= set(changed_ids)):
            raise CandidateContractError("parameterized field differs from declared full PS authority")
    if (Path(export["source_run"]).resolve() != source_manifest.parent.resolve()
            or not result.get("field_solved") or result.get("status") != "success"
            or authority != binding["authority"] or geometry != binding["geometry"]
            or len(authority["analyzer_electrode_voltages_v"]) != 20
            or parameter.get("actual_voltages_v") != authority["analyzer_electrode_voltages_v"]
            or not parameter.get("parametric_active") or parameter.get("unit") != "V"
            or parameter.get("name") != solve["parameter"]["name"]
            or export.get("parameter_name") != parameter.get("name")
            or export.get("parameter_voltage_v") != solved.get("values_v")
            or parameter.get("changed_physical_ids") != changed_ids
            or solved.get("names") != [parameter["name"]]
            or solved.get("solnum") != export.get("solnum") or export.get("solnum") != 1
            or solved.get("values_v") != authority["analyzer_electrode_voltages_v"][solve["parameter"]["electrode_ids"][0]-1]
            or solve.get("potential_order") != "2"):
        raise CandidateContractError("parameterized field actual source/geometry/voltages/solution differs")
    for key in ("active_mesh_tag", "solution_tag", "dataset_tag"):
        if export[key] != solve[key] or (key in binding["grid"] and export[key] != binding["grid"][key]):
            raise CandidateContractError("parameterized field mesh/dataset differs from export")
    before = read_sealed(source_manifest, source_manifest.parent / "results" / "solver_before.json")
    after = read_sealed(source_manifest, source_manifest.parent / "results" / "solver_after.json")
    before_solver = _static_solver_numerics(before)
    solver = _static_solver_numerics(after)
    expected_solver = dict(before_solver)
    if "strict_stopping" in solve:
        stopping = solve["strict_stopping"]
        tolerance = _finite(stopping["study_stol"], "declared strict Study tolerance")
        if (tolerance <= 0 or tolerance > _finite(before_solver["study_stol"], "source Study tolerance")
                or tolerance > _finite(before_solver["stationary_stol"], "source Stationary tolerance")
                or not before_solver["study_usestol"] or before_solver["stationary_control"] != "stat"
                or stopping.get("study_usestol_unchanged") is not True
                or stopping.get("stationary_control_unchanged") != "stat"
                or stopping.get("stationary_stol_not_explicitly_set") is not True
                or solver["stationary_stol"] not in (before_solver["stationary_stol"], tolerance)):
            raise CandidateContractError("parameterized field changed undeclared stopping controls")
        expected_solver.update(study_stol=tolerance, stationary_stol=solver["stationary_stol"])
    if solver != expected_solver or solver["active_mesh_tag"] != result["active_mesh_tag"]:
        raise CandidateContractError("parameterized field changed actual solver/mesh")
    grid_request = read_sealed(export_manifest, export_manifest.parent / "inputs" / "grid_authority.json")
    plan = compile_request(grid_request)
    if (Path(solve["source_mph"]).resolve() != Path(plan["source_mph_record"]["path"]).resolve()
            or int(result["tetrahedra"]) != plan["expected_tetrahedra"]):
        raise CandidateContractError("parameterized field saved mesh origin differs")
    # The grid request identifies the saved mesh, not this solve's voltage
    # target. Use the actual full authority verified above for consumption.
    plan = {**plan, "candidate_authority": copy.deepcopy(authority)}
    model_record = _record(source_manifest, Path(export["source_mph"]))
    if diagnostic is not None:
        native_log = source_manifest.parent / "logs" / "native.log"
        native_log_record = _record(source_manifest, native_log)
        dof = re.findall(r"Number of degrees of freedom solved for:\s*(\d+)",
                         native_log.read_text(encoding="utf-8-sig", errors="replace")) if native_log.is_file() else []
        diagnostic.update(parameter_source_manifest=str(source_manifest), source_export_manifest=str(export_manifest),
                          actual_model_record=model_record, parameter_readback=parameter, solved_parameter_readback=solved,
                          actual_solver_numerics=solver,
                          native_log_record=native_log_record, native_dof_counts=list(dict.fromkeys(map(int, dof))),
                          qualification="engineering_exploration__parameterized_literal_operator_equivalence_not_established")
    return plan, solver


def _strict_saved_static_plan(binding: Mapping[str, Any], manifest: Path,
                              records: Mapping[str, Any], diagnostic: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Consume an honestly sealed saved-field rerun; stopping changes are not mesh origins."""
    def read(owner: Path, path: Path) -> dict[str, Any]:
        _record(owner, path)
        return _load_object(path)

    export_manifest = Path(records["source_export_manifest"]["path"])
    source_manifest = Path(records["source_model_manifest"]["path"])
    read(manifest, export_manifest)
    read(manifest, source_manifest)
    export = read(export_manifest, export_manifest.parent / "inputs" / "diagnostic_plan.json")
    if export.get("role") != "once_only_read_only_strict_s2_scalar_export":
        raise CandidateContractError("strict saved field export role differs")
    source = source_manifest.parent
    solve = read(source_manifest, source / "inputs" / "diagnostic_plan.json")
    result = read(source_manifest, source / "results" / "result.json")
    roles = [item for item in solve["source_runs"] if item["role"] == "s2"]
    if len(roles) != 1:
        raise CandidateContractError("strict saved field requires one original S2 source")
    original = roles[0]
    authority = read(source_manifest, Path(original["frozen_input"]))
    geometry = read(source_manifest, Path(original["resolved_geometry"]))
    solved = read(source_manifest, source / "results" / "authority_after.json")
    before = _static_solver_numerics(read(source_manifest, source / "results" / "solver_before.json"))
    solver = _static_solver_numerics(read(source_manifest, source / "results" / "solver_after.json"))
    stopping = {"study_stol", "stationary_stol"}
    tolerance = _finite(solve["strict_study_stol"], "strict Study tolerance")
    if (tolerance <= 0 or any(solver.get(key) != tolerance for key in stopping)
            or any(tolerance > _finite(before[key], key) for key in stopping)
            or {k: v for k, v in before.items() if k not in stopping}
            != {k: v for k, v in solver.items() if k not in stopping}):
        raise CandidateContractError("strict saved field changed undeclared solver controls")
    values = authority["analyzer_electrode_voltages_v"]
    if (Path(export["source_run"]).resolve() != source.resolve()
            or not result.get("field_solved") or result.get("status") != "success"
            or authority != binding["authority"] or geometry != binding["geometry"]
            or len(values) != 20 or solved.get("voltages_v") != values
            or solved.get("parameter_names") != [export["parameter_name"]]
            or solved.get("parameter_values_v") != export["parameter_voltage_v"]
            or original["parameter_name"] != export["parameter_name"]
            or original["parameter_value_v"] != export["parameter_voltage_v"]
            or original["expected_voltages_v"] != values
            or solved.get("solnum") != export["solnum"] or export["solnum"] != 1
            or solve["solution_number"] != export["solnum"] or solve.get("potential_order") != "2"):
        raise CandidateContractError("strict saved field source/voltages/solution differs")
    for key, actual in (("active_mesh_tag", result["active_mesh_tag"]),
                        ("solution_tag", solved["solution"]), ("dataset_tag", solved["dataset"])):
        if (export[key] != actual or (key != "active_mesh_tag" and solve[key] != actual)
                or (key in binding["grid"] and binding["grid"][key] != actual)):
            raise CandidateContractError("strict saved field mesh/dataset differs")
    old_manifest = Path(original["manifest"])
    read(source_manifest, old_manifest)
    original_run = Path(original["mph"]).parent.parent
    origin = read(old_manifest, original_run / "inputs" / "diagnostic_plan.json")
    plan = compile_request(read(export_manifest, export_manifest.parent / "inputs" / "grid_authority.json"))
    if (Path(origin["source_mph"]).resolve() != Path(plan["source_mph_record"]["path"]).resolve()
            or origin.get("potential_order") != "2"
            or origin.get("parameter", {}).get("name") != original["parameter_name"]
            or origin.get("parameter", {}).get("electrode_ids") != list(PS_GROUPS["s2"])
            or int(result["tetrahedra"]) != plan["expected_tetrahedra"]
            or solver["active_mesh_tag"] != result["active_mesh_tag"]):
        raise CandidateContractError("strict saved field mesh origin differs")
    expected_model = source / "comsol" / solve["strict_mph_name"]
    if Path(export["source_mph"]).resolve() != expected_model.resolve():
        raise CandidateContractError("strict saved field model differs from solved output")
    model_record = _record(source_manifest, expected_model)
    if diagnostic is not None:
        diagnostic.update(source_model_manifest=str(source_manifest), source_export_manifest=str(export_manifest),
                          actual_model_record=model_record, solved_voltage_readback=solved,
                          actual_solver_numerics=solver, solver_before=before,
                          qualification="engineering_exploration__strict_saved_rerun_not_full_field_qualification")
    return plan, solver


def _static_binding_problem(binding: Mapping[str, Any], materialization: Mapping[str, Any],
                            binding_path: str, source_diagnostic: dict[str, Any] | None = None) -> dict[str, Any]:
    """The existing resolved-binding family projection, shared by response validation."""
    manifest = Path(binding["export_manifest"])
    records = _load_object(manifest)["inputs"]
    parameterized = {"source_export_manifest", "parameter_source_manifest"} <= set(records)
    strict_saved = {"source_export_manifest", "source_model_manifest"} <= set(records)
    plans = [r for r in records.values() if Path(r["path"]).name in ("plan.json", "diagnostic_plan.json")]
    if not parameterized and not strict_saved and len(plans) != 1:
        raise CandidateContractError("static field must bind exactly one sealed export plan")
    if strict_saved:
        plan, solver = _strict_saved_static_plan(binding, manifest, records, source_diagnostic)
        export_plan = None
    elif parameterized:
        plan, solver = _parameterized_static_plan(binding, manifest, records, source_diagnostic)
        export_plan = None
    else:
        plan_path = Path(_named_record(plans, Path(plans[0]["path"]).name, "scalar export plan")["path"])
        _record(manifest, plan_path)
        export_plan = _load_object(plan_path)
    provider = export_plan is not None and export_plan.get("role") == "mrtof_same_mesh_field_provider_request"
    if provider:
        request = export_plan
        solver_path = plan_path.with_name("solver_before.json")
        after_path = plan_path.with_name("solver_after.json")
        _record(manifest, solver_path)
        _record(manifest, after_path)
        solver = _static_solver_numerics(_load_object(solver_path))
        if solver != _static_solver_numerics(_load_object(after_path)):
            raise CandidateContractError("candidate solve changed sealed solver numerics")
    elif not parameterized and not strict_saved:
        # A read-only request to the existing compiler, not a provider run/identity.
        request = {key: export_plan[key] for key in (
            "artifact_retention", "resource_threshold_action", "solve_memory_bytes", "solve_seconds", "artifact_budget_bytes")}
        request.update(schema_version=1, role="mrtof_same_mesh_field_provider_request",
                       source_binding_path=binding_path,
                       source_field_manifest=str(Path(export_plan["source_model_summary"]).with_name("run_manifest.json")),
                       candidate_voltages_v=dict(zip(PS_GROUPS, [*materialization["stripe_biases_v"], *materialization["prism_voltages_v"]], strict=True)))
        source_manifest = Path(request["source_field_manifest"])
        source_records = _load_object(source_manifest)["outputs"]
        solver_path = Path(_named_record(source_records, "solver_configured.json", "source solver readback")["path"])
        _record(source_manifest, solver_path)
        solver = _static_solver_numerics(_load_object(solver_path))
    if not parameterized and not strict_saved:
        plan = compile_request(request)
    if plan["candidate_authority"] != binding["authority"]:
        raise CandidateContractError("compiled field voltages differ from bound actual authority")
    if solver["active_mesh_tag"] != plan["active_mesh_tag"]:
        raise CandidateContractError("actual solver mesh differs from the sealed source mesh")
    if any(binding["grid"][key] != plan["export_grid"][key] for key in ("origin_mm", "pitch_mm", "dimensions")):
        raise CandidateContractError("candidate field grid differs from its source family")
    expected = binding["authority"]["analyzer_electrode_voltages_v"]
    requested = [*materialization["stripe_biases_v"], *materialization["prism_voltages_v"]]
    for value, ids in zip(requested, PS_GROUPS.values()):
        if any(not math.isclose(float(expected[i - 1]), float(value), rel_tol=0, abs_tol=1e-9) for i in ids):
            raise CandidateContractError("static candidate field voltages differ from materialization")
    if [float(v) for v in materialization["analyzer_electrode_voltages_v"]] != [float(v) for v in expected]:
        raise CandidateContractError("static full field voltage authority differs from materialization")
    authority = copy.deepcopy(binding["authority"])
    for ids in PS_GROUPS.values():
        for electrode in ids:
            authority["analyzer_electrode_voltages_v"][electrode - 1] = None
    return dict(mode="comsol_static_scalar_v", fixed_authority=authority,
                geometry_sha256=binding["records"]["geometry_authority"]["sha256"],
                source_mesh_record=plan["source_mph_record"], source_dataset=plan["source_dataset"],
                export_grid={k: v for k, v in plan["export_grid"].items() if k != "block_points"},
                solver_numerics=solver, assembly_manifest=binding["assembly_manifest"],
                collision_manifest=binding["collision_manifest"])


def native_bank_identity(receipt: Mapping[str, Any]) -> dict[str, str]:
    """Return stable scientific identity, excluding private per-flight paths."""
    if (receipt.get("schema_version") != 1
            or receipt.get("role") != "mrtof_private_native_corridor_family"
            or receipt.get("status") != "prepared"
            or receipt.get("response_refine_performed") is not False
            or receipt.get("published_native_members_opened") is not False
            or receipt.get("controller_refine") != "solutions={0}"):
        raise CandidateContractError("native corridor runtime receipt is invalid")
    result = {}
    for name in ("cache_key", "generation_sha256"):
        value = receipt.get(name)
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
            raise CandidateContractError(f"native corridor receipt lacks {name}")
        result[name] = value.upper()
    return result


def _center_source_projection(materialization: Mapping[str, Any], observation: Mapping[str, Any]) -> dict[str, Any] | None:
    """Project only an explicitly selected frozen diagnostic centre, not a queue ID guess."""
    if materialization.get("source_cohort_role") != "controlled_diagnostic":
        return None
    selection = materialization.get("source_selection")
    center = materialization.get("source_center_state")
    if not isinstance(selection, Mapping) or not isinstance(center, Mapping):
        return None
    if (selection.get("role") != "contiguous_frozen_source_diagnostic_selection"
            or center.get("particle_id") != 1
            or 1 not in materialization.get("source_expected_particle_ids", [])):
        return None
    cohort = materialization.get("source_cohort")
    if not isinstance(cohort, Mapping):
        raise CandidateContractError("selected centre lacks its source cohort authority")
    frame, clock = cohort.get("frame_id"), cohort.get("clock_basis")
    if not isinstance(frame, str) or not frame or not isinstance(clock, str) or not clock:
        raise CandidateContractError("selected centre lacks frame/clock identity")
    if materialization.get("source_clock_basis") != clock:
        raise CandidateContractError("selected centre clock differs from its cohort")
    state = _bunch_center_source_state(dict(materialization))
    expected = _source_release_record(
        state, center["mass_th"], center["charge_e"], _finite(center.get("tob_us"), "centre birth time"),
    )
    actual = observation.get("source_release_state")
    if not isinstance(actual, Mapping) or any(actual.get(k) != v for k, v in expected.items()):
        raise CandidateContractError("selected centre release state differs from frozen source")
    return {"source_release_state": expected, "frame_id": frame, "clock_basis": clock}


def _trial(manifest_path: Path, freeze_dir: Path | None = None, *, require_target_phase: bool = True) -> dict[str, Any]:
    """Read the named observation projection; do not rehash unused PA payloads."""
    manifest = _load_object(manifest_path)
    if (manifest.get("status") != "success"
            or (manifest.get("project"), manifest.get("mode")) not in {
                ("instrument_assembly", "oa_mr"),
                ("parallel_mirror_dual_stripe_mr_tof", "finite_3d_two_prism_voltage_trial"),
            }):
        raise CandidateContractError(f"not a successful downstream trial: {manifest_path}")
    records = {"run_config": manifest["run_config"]}
    for filename in ("two_prism_trial_observation.json", "two_prism_trial_materialization.json"):
        matches = [record for record in manifest["outputs"]
                   if record_path(record, base_dir=manifest_path.parent).name == filename]
        if len(matches) != 1:
            raise CandidateContractError(f"trial must bind exactly one {filename}")
        records[filename] = matches[0]
    native_records = [record for record in manifest["outputs"]
                      if record_path(record, base_dir=manifest_path.parent).name == "native_corridor_runtime_family.json"]
    if len(native_records) > 1:
        raise CandidateContractError("trial binds duplicate native corridor receipts")
    if native_records:
        records["native_corridor_runtime_family.json"] = native_records[0]
    documents = {}
    for name, record in records.items():
        path = record_path(record, base_dir=manifest_path.parent)
        if freeze_dir is not None:
            freeze_dir.mkdir(parents=True, exist_ok=True)
            destination = freeze_dir / path.name
            shutil.copyfile(path, destination)
            record = {**record, "path": str(destination)}
            path = destination
        verify_record(name, record, base_dir=manifest_path.parent)
        documents[name] = _load_object(path)
    if freeze_dir is not None:
        shutil.copyfile(manifest_path, freeze_dir / "run_manifest.json")
    parameters = documents["run_config"].get("parameters", {})
    native_mode = parameters.get("pa_binding_mode") == "native_corridor_private_fast_adjust_family__four_instances__n1"
    if native_mode != bool(native_records):
        raise CandidateContractError("native corridor binding mode and receipt disagree")
    bank_identity = native_bank_identity(documents["native_corridor_runtime_family.json"]) if native_mode else None
    observation = documents["two_prism_trial_observation.json"]
    materialization = documents["two_prism_trial_materialization.json"]
    if require_target_phase and observation.get("status") not in {"full_drift_observed", "target_phase_observed", "detected"}:
        raise CandidateContractError("downstream workpoint trial must observe the target drift phase")
    stripes = materialization.get("stripe_biases_v")
    prisms = observation.get("prism_voltages_v")
    if prisms != materialization.get("prism_voltages_v"):
        raise CandidateContractError("observed prism voltages differ from materialization")
    residuals = observation.get("residuals")
    if not isinstance(stripes, list) or len(stripes) != 2 or not isinstance(prisms, list) or len(prisms) != 2:
        raise CandidateContractError("downstream workpoint trial lacks four electrode voltages")
    if require_target_phase and not isinstance(residuals, dict):
        raise CandidateContractError("downstream workpoint trial lacks its residual map")
    inputs = materialization.get("inputs")
    if not isinstance(inputs, dict):
        raise CandidateContractError("downstream workpoint trial lacks frozen input identities")
    inputs = dict(inputs)
    # These three records currently point at the same resolved project contract.
    # Compare its flight-physics projection once; controller step sizes, trust
    # limits, iteration budget, and acceptance thresholds are not flight inputs.
    raw_contract_identity = inputs.pop("contract_sha256", None)
    raw_accelerator_identity = inputs.pop("accelerator_geometry_contract_sha256", None)
    raw_trajectory_identity = inputs.pop("trajectory_contract_sha256", None)
    if raw_trajectory_identity is None:
        # Legacy non-native trial fixtures predate the trajectory contract
        # input.  Their complete input map remains the strict identity.
        if raw_contract_identity is not None:
            inputs["contract_sha256"] = raw_contract_identity
        if raw_accelerator_identity is not None:
            inputs["accelerator_geometry_contract_sha256"] = raw_accelerator_identity
    elif not isinstance(raw_trajectory_identity, str) or not raw_trajectory_identity:
        raise CandidateContractError("downstream workpoint trial has an invalid trajectory contract identity")
    else:
        if raw_contract_identity != raw_trajectory_identity or raw_accelerator_identity != raw_trajectory_identity:
            raise CandidateContractError("resolved contract input identities disagree")
        inputs["trajectory_physics_contract_sha256"] = _trajectory_physics_identity(
            manifest, raw_trajectory_identity
        )
        raw_reviewed_identity = inputs.pop("reviewed_contract_sha256", None)
        if not isinstance(raw_reviewed_identity, str) or not raw_reviewed_identity:
            raise CandidateContractError("trial lacks its reviewed contract identity")
        inputs["reviewed_physics_contract_sha256"] = _trajectory_physics_identity(
            manifest, raw_reviewed_identity, "reviewed_geometry_contract"
        )
    target_names = (
        "target_drift_period_ratio",
        "target_positive_mirror_turn_y_mm",
        "target_low_field_tangent_ratio_vy_over_vz",
        "target_slow_turn_y_mm",
    )
    center_projection = _center_source_projection(materialization, observation)
    if center_projection is not None:
        # The verified selected centre, not its diagnostic mother cohort, is
        # this N=1 controller's source identity. Keep the raw receipt in evidence.
        inputs.pop("bunch_source_receipt_sha256", None)
    field_source: dict[str, Any] = {}
    static_problem = _static_field_problem(materialization, field_source, trial_manifest=manifest)
    return {
        "manifest": str(manifest_path.resolve()),
        "manifest_sha256": file_sha256(manifest_path),
        "consumer_projection": {
            "id": "mrtof_downstream_workpoint_observation",
            "records": records,
            "scope": "run_config_and_two_trial_json_outputs__not_full_PA_verification",
            "fly2_sha256": materialization["fly2_sha256"],
            **({"field_source": field_source} if field_source else {}),
        },
        "voltages_v": [_finite(value, "downstream voltage") for value in
                       field_source.get("consumed_ps_voltages_v", (*stripes, *prisms))],
        "residual_vector": ([_finite(residuals.get(name), name) for name in workpoint_residual_names(materialization)]
                            if require_target_phase else []),
        "frozen_problem": {
            **({"prism_handoff_target": materialization["prism_handoff_target"]}
               if materialization.get("prism_handoff_target") is not None else {}),
            **({"static_field_problem": static_problem}
               if isinstance(materialization.get("field_binding"), Mapping)
               and materialization["field_binding"].get("mode") in (
                   "comsol_static_scalar_v", "native_static_pa") else {}),
            "native_bank_identity": bank_identity,
            "inputs": inputs,
            "targets": {name: _finite(materialization.get(name), name) for name in target_names},
            "source_position_project_mm": materialization.get("source_position_project_mm"),
            "source_direction_project": materialization.get("source_direction_project"),
            "trajectory_profile": materialization.get("trajectory_profile"),
            "accelerator_pulse": materialization.get("accelerator_pulse"),
            "accelerator_instance": materialization.get("accelerator_instance"),
            "mirror_voltages_v": materialization["mirror_voltages_v"],
            "selected_axial_energy_per_charge_v": materialization["selected_axial_energy_per_charge_v"],
            "source_slow_kinetic_energy_per_charge_v": materialization["source_slow_kinetic_energy_per_charge_v"],
            **({"source_center_projection": center_projection} if center_projection is not None
               else {"fly2_sha256": materialization["fly2_sha256"]}),
            "drift_phase_contract": materialization["drift_phase_contract"],
            "nonaccelerator_mesh_mm_per_gu": materialization["nonaccelerator_mesh_mm_per_gu"],
        },
    }


def assert_trial_matches_jacobian(proposal: Mapping[str, Any], child_manifest: Path) -> dict[str, Any]:
    """Bind each real observation to the audited baseline's physical problem."""
    baseline_name = proposal.get("baseline_manifest")
    if not isinstance(baseline_name, str) or not baseline_name:
        raise CandidateContractError("initial Jacobian lacks its baseline manifest")
    baseline_path = Path(baseline_name)
    consumed = proposal.get("consumed_trials", [])
    matches = [item for item in consumed if isinstance(item, Mapping)
               and Path(str(item.get("manifest", ""))).resolve() == baseline_path.resolve()]
    if len(matches) != 1 or str(matches[0].get("manifest_sha256", "")).lower() != file_sha256(baseline_path).lower():
        raise CandidateContractError("initial Jacobian baseline manifest identity differs")
    baseline = _trial(baseline_path)
    child = _trial(child_manifest, require_target_phase=False)
    expected, actual = baseline["frozen_problem"], child["frozen_problem"]
    if expected != actual:
        changed = sorted(key for key in set(expected) | set(actual) if expected.get(key) != actual.get(key))
        raise CandidateContractError(f"child changes initial Jacobian frozen physical problem: {changed}")
    return child


def resolve_active_stripe_axes(profile: Mapping[str, Any]) -> tuple[int, ...]:
    """Resolve the explicitly authored voltage coordinates, without a default."""
    names = profile.get("active_stripe_axes")
    if names == [UNKNOWN_NAMES[0]]:
        return (0,)
    if names == list(UNKNOWN_NAMES[:2]):
        return (0, 1)
    raise CandidateContractError("active_stripe_axes must explicitly name S1 alone or S1/S2 in canonical order")


def resolve_numerics(contract: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict[str, Any]:
    """Derive bounded local-solve controls from the baseline and frozen trial."""
    profile = contract["downstream_fixed_grid_workpoint_profile"]
    if profile["schema_version"] != 1 or profile["parameter_scale_rule"] != "absolute_baseline_voltage":
        raise CandidateContractError("unsupported downstream workpoint profile")
    if profile["voltage_bounds_rule"] != "stripe_seed_energy_envelope_with_baseline_sign__prism_initial_search_window":
        raise CandidateContractError("unsupported downstream voltage envelope rule")
    energy = _finite(baseline["frozen_problem"]["selected_axial_energy_per_charge_v"], "axial energy")
    deviation = _finite(contract["accelerator_energy_contract"]["maximum_particle_net_gain_deviation_per_charge_v"], "energy half-window")
    seed = contract["dual_stripe_l0"]["operating_seed_search"]
    floor = energy * _finite(seed["minimum_abs_bias_fraction_of_nominal_energy"], "minimum bias fraction")
    if energy <= deviation or deviation <= 0 or floor <= 0:
        raise CandidateContractError("invalid downstream energy/bias envelope")
    voltage = baseline["voltages_v"]
    axes = resolve_active_stripe_axes(profile)
    if not voltage[0] < -floor or (axes == (0, 1) and not voltage[1] > floor):
        raise CandidateContractError("active downstream Stripe seed has invalid bias polarity")
    if axes == (0,) and voltage[1] != 0.0:
        raise CandidateContractError("inactive S2 must remain grounded at zero volts")
    prism_window = contract["prism_transport"]["two_prism_injection_l0"]["voltage_polarity_contract"]["current_initial_search_window_v"]
    target_ratio = baseline["frozen_problem"]["targets"]["target_low_field_tangent_ratio_vy_over_vz"]
    angle_scale = math.radians(_finite(profile["angle_residual_scale_degrees"], "angle scale"))
    if not 0 < angle_scale < math.pi / 2:
        raise CandidateContractError("angle scale must be positive and below 90 degrees")
    target_angle = math.atan(target_ratio)
    ratio_scale = min(math.tan(target_angle + angle_scale) - target_ratio,
                      target_ratio - math.tan(target_angle - angle_scale))
    target = baseline["frozen_problem"].get("prism_handoff_target")
    if target is not None:
        if axes != (0,):
            raise CandidateContractError("clean-phase Prism target requires the single-S1 staged controller")
        ratio_scale = _finite(target.get("energy_tolerance_per_charge_v"), "clean-phase energy scale")
    tiers = profile["jacobian_relative_step_tiers"]
    coarse_relative_step = _finite(tiers["coarse"], "coarse relative voltage step")
    if coarse_relative_step <= 0.0:
        raise CandidateContractError("coarse relative voltage step must be positive")
    parameter_scales = [max(abs(value), 1.0) for value in voltage]
    return {
        "active_stripe_axes": [UNKNOWN_NAMES[axis] for axis in axes],
        "lower_bounds_v": [-energy, floor if 1 in axes else 0.0, prism_window["prism_1"][0], prism_window["prism_2"][0]],
        "upper_bounds_v": [-floor, math.nextafter(energy - deviation, -math.inf) if 1 in axes else 0.0, prism_window["prism_1"][1], prism_window["prism_2"][1]],
        "parameter_scales_v": parameter_scales,
        "residual_scales": [profile["position_residual_scale_mm"], ratio_scale,
                            profile["slow_turn_residual_scale_mm"], profile["return_phase_residual_scale_mm"]],
        "maximum_abs_step_v": [coarse_relative_step * value for value in parameter_scales],
        "relative_rank_tolerance": contract["dual_stripe_l0"]["determination_numerics"]["relative_singular_value_rank_tolerance"],
        "compatibility_tolerance": contract["dual_stripe_l0"]["determination_numerics"]["scaled_irreducible_residual_norm_tolerance"],
    }


def solve_linearized_step(
    baseline: Mapping[str, Any],
    perturbations: Sequence[Mapping[str, Any]],
    *,
    lower_bounds_v: Sequence[float],
    upper_bounds_v: Sequence[float],
    parameter_scales_v: Sequence[float],
    residual_scales: Sequence[float],
    maximum_abs_step_v: Sequence[float],
    relative_rank_tolerance: float,
    compatibility_tolerance: float,
) -> dict[str, Any]:
    """Return a full-rank signed one-sided Jacobian correction with one trust scale."""
    if len(perturbations) != 4:
        raise CandidateContractError("downstream workpoint needs exactly four perturbations")
    vectors = [np.asarray(item["voltages_v"], dtype=float) for item in (baseline, *perturbations)]
    residual_vectors = [np.asarray(item["residual_vector"], dtype=float) for item in (baseline, *perturbations)]
    if any(value.shape != (4,) or not np.all(np.isfinite(value)) for value in (*vectors, *residual_vectors)):
        raise CandidateContractError("downstream voltage and residual vectors must be finite four-vectors")
    if any(item["frozen_problem"] != baseline["frozen_problem"] for item in perturbations):
        raise CandidateContractError("downstream perturbations change the frozen physical problem")
    base_v, base_r = vectors[0], residual_vectors[0]
    columns: list[np.ndarray] = []
    steps: list[float] = []
    for index, trial_v in enumerate(vectors[1:]):
        delta = trial_v - base_v
        changed = np.flatnonzero(delta != 0.0)
        if changed.tolist() != [index]:
            raise CandidateContractError(
                f"perturbation {index + 1} must change only {UNKNOWN_NAMES[index]} by a nonzero step"
            )
        steps.append(float(delta[index]))
        columns.append((residual_vectors[index + 1] - base_r) / delta[index])
    jacobian = np.column_stack(columns)
    lower = np.asarray(lower_bounds_v, dtype=float)
    upper = np.asarray(upper_bounds_v, dtype=float)
    parameter_scales = np.asarray(parameter_scales_v, dtype=float)
    residual_scale_array = np.asarray(residual_scales, dtype=float)
    maximum_step = np.asarray(maximum_abs_step_v, dtype=float)
    if any(value.shape != (4,) or not np.all(np.isfinite(value)) for value in (lower, upper, parameter_scales, residual_scale_array, maximum_step)):
        raise CandidateContractError("downstream bounds, scales, and trust limits must be finite four-vectors")
    if np.any(lower >= base_v) or np.any(base_v >= upper):
        raise CandidateContractError("baseline downstream voltages must lie strictly inside their bounds")
    if np.any(parameter_scales <= 0.0) or np.any(residual_scale_array <= 0.0) or np.any(maximum_step <= 0.0):
        raise CandidateContractError("downstream scales and trust limits must be positive")
    rank_tolerance = _finite(relative_rank_tolerance, "relative rank tolerance")
    if rank_tolerance <= 0.0:
        raise CandidateContractError("relative rank tolerance must be positive")
    result = solve_with_jacobian(
        baseline,
        jacobian,
        lower_bounds_v=lower,
        upper_bounds_v=upper,
        parameter_scales_v=parameter_scales,
        residual_scales=residual_scale_array,
        maximum_abs_step_v=maximum_step,
        relative_rank_tolerance=rank_tolerance,
        compatibility_tolerance=compatibility_tolerance,
    )
    return {"stencil_steps_v": steps, **result}


def solve_with_jacobian(
    baseline: Mapping[str, Any],
    jacobian_rows: Sequence[Sequence[float]],
    *,
    lower_bounds_v: Sequence[float],
    upper_bounds_v: Sequence[float],
    parameter_scales_v: Sequence[float],
    residual_scales: Sequence[float],
    maximum_abs_step_v: Sequence[float],
    relative_rank_tolerance: float,
    compatibility_tolerance: float,
) -> dict[str, Any]:
    """Apply one bounded Newton step from an already audited local Jacobian."""
    base_v = np.asarray(baseline["voltages_v"], dtype=float)
    base_r = np.asarray(baseline["residual_vector"], dtype=float)
    jacobian = np.asarray(jacobian_rows, dtype=float)
    lower = np.asarray(lower_bounds_v, dtype=float)
    upper = np.asarray(upper_bounds_v, dtype=float)
    parameter_scales = np.asarray(parameter_scales_v, dtype=float)
    residual_scale_array = np.asarray(residual_scales, dtype=float)
    maximum_step = np.asarray(maximum_abs_step_v, dtype=float)
    if (base_v.shape != (4,) or base_r.shape != (4,) or jacobian.shape != (4, 4)
            or not np.all(np.isfinite(base_v)) or not np.all(np.isfinite(base_r))
            or not np.all(np.isfinite(jacobian))):
        raise CandidateContractError("downstream baseline and Jacobian must be finite four-dimensional arrays")
    if any(value.shape != (4,) or not np.all(np.isfinite(value))
           for value in (lower, upper, parameter_scales, residual_scale_array, maximum_step)):
        raise CandidateContractError("downstream bounds, scales, and trust limits must be finite four-vectors")
    if np.any(lower >= base_v) or np.any(base_v >= upper):
        raise CandidateContractError("baseline downstream voltages must lie strictly inside their bounds")
    if np.any(parameter_scales <= 0.0) or np.any(residual_scale_array <= 0.0) or np.any(maximum_step <= 0.0):
        raise CandidateContractError("downstream scales and trust limits must be positive")
    rank_tolerance = _finite(relative_rank_tolerance, "relative rank tolerance")
    if rank_tolerance <= 0.0:
        raise CandidateContractError("relative rank tolerance must be positive")
    classification = classify_constraint_system(
        UNKNOWN_NAMES,
        RESIDUAL_NAMES,
        jacobian_rows=jacobian.tolist(),
        residuals=base_r.tolist(),
        parameter_scales=parameter_scales.tolist(),
        residual_scales=residual_scale_array.tolist(),
        relative_rank_tolerance=rank_tolerance,
        compatibility_tolerance=compatibility_tolerance,
    )
    if classification.status != "square_exact":
        raise CandidateContractError(
            f"downstream finite-3-D Jacobian is not square exact: {classification.status}"
        )
    raw_step = np.linalg.solve(jacobian, -base_r)
    nonzero = np.abs(raw_step) > 0
    alpha = min(1.0, float(np.min(maximum_step[nonzero] / np.abs(raw_step[nonzero])))) if np.any(nonzero) else 1.0
    for index, component in enumerate(raw_step):
        if component > 0.0:
            alpha = min(alpha, float((upper[index] - base_v[index]) / component))
        elif component < 0.0:
            alpha = min(alpha, float((lower[index] - base_v[index]) / component))
    alpha = max(0.0, min(1.0, alpha))
    if alpha <= 0.0:
        raise CandidateContractError("no positive bounded trust step is available")
    applied = alpha * raw_step
    proposed = base_v + applied
    predicted = base_r + jacobian @ applied
    return {
        "unknown_names": list(UNKNOWN_NAMES),
        "residual_names": list(RESIDUAL_NAMES),
        "baseline_voltages_v": base_v.tolist(),
        "baseline_residuals": dict(zip(RESIDUAL_NAMES, base_r.tolist())),
        "physical_jacobian_rows": jacobian.tolist(),
        "classification": asdict(classification),
        "unbounded_linear_correction_v": raw_step.tolist(),
        "trust_scale": alpha,
        "applied_correction_v": applied.tolist(),
        "proposed_voltages_v": proposed.tolist(),
        "predicted_residuals": dict(zip(RESIDUAL_NAMES, predicted.tolist())),
    }


def _transport_invariants(trial: Mapping[str, Any]) -> dict[str, Any]:
    frozen = trial["frozen_problem"]
    inputs = frozen["inputs"]
    required_input_names = (
        "fixed_mirror_stripe_authority_sha256",
        "mirror_summary_sha256",
        ("reviewed_physics_contract_sha256" if "reviewed_physics_contract_sha256" in inputs
         else "reviewed_contract_sha256"),
        "stripe_summary_sha256",
    )
    missing = [name for name in required_input_names if name not in inputs]
    if missing:
        raise CandidateContractError(f"transport baseline lacks invariant identities: {missing}")
    return {
        "native_bank_identity": frozen.get("native_bank_identity"),
        **({"static_field_problem": frozen["static_field_problem"]}
           if "static_field_problem" in frozen else {}),
        "field_authorities": {name: inputs[name] for name in required_input_names},
        "targets": frozen["targets"],
        "mirror_voltages_v": frozen["mirror_voltages_v"],
        "selected_axial_energy_per_charge_v": frozen["selected_axial_energy_per_charge_v"],
        "source_slow_kinetic_energy_per_charge_v": frozen["source_slow_kinetic_energy_per_charge_v"],
        "drift_phase_contract": frozen["drift_phase_contract"],
        "trajectory_profile": frozen["trajectory_profile"],
        "nonaccelerator_mesh_mm_per_gu": frozen["nonaccelerator_mesh_mm_per_gu"],
    }


def audit_transported(
    definition: Mapping[str, Any],
    contract: Mapping[str, Any],
    contract_path: Path,
    freeze_dir: Path | None,
) -> dict[str, Any]:
    """Transport a prior audited fine-grid Jacobian to one compatible baseline."""
    allowed = {"schema_version", "role", "contract", "baseline_manifest", "prior_workpoint_manifest"}
    if set(definition) != allowed:
        raise CandidateContractError("transport definition only binds contract, baseline, and prior audit")
    baseline = _trial(
        Path(definition["baseline_manifest"]),
        freeze_dir / "baseline" if freeze_dir else None,
    )
    prior_manifest_path = Path(definition["prior_workpoint_manifest"])
    prior_manifest = _load_object(prior_manifest_path)
    if (prior_manifest.get("status") != "success"
            or prior_manifest.get("project") != "parallel_mirror_dual_stripe_mr_tof"
            or prior_manifest.get("mode") != "downstream_fixed_grid_workpoint"):
        raise CandidateContractError("prior Jacobian must come from a successful downstream workpoint run")
    prior_records = [
        record for record in prior_manifest.get("outputs", [])
        if record_path(record, base_dir=prior_manifest_path.parent).name == "downstream_fixed_grid_workpoint.json"
    ]
    if len(prior_records) != 1:
        raise CandidateContractError("prior workpoint manifest must bind one workpoint audit")
    verify_record("prior_workpoint_audit", prior_records[0], base_dir=prior_manifest_path.parent)
    prior_path = record_path(prior_records[0], base_dir=prior_manifest_path.parent)
    prior = _load_object(prior_path)
    if (prior.get("role") != "mrtof_downstream_fixed_grid_workpoint_audit"
            or prior.get("status") != "linearized_candidate_step"
            or prior.get("unknown_names") != list(UNKNOWN_NAMES)
            or prior.get("residual_names") != list(RESIDUAL_NAMES)):
        raise CandidateContractError("prior workpoint audit is not an eligible four-variable Jacobian source")
    if freeze_dir is not None:
        freeze_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(prior_path, freeze_dir / "prior_workpoint_audit.json")
        shutil.copyfile(prior_manifest_path, freeze_dir / "prior_workpoint_manifest.json")
    prior_baseline = _trial(
        Path(prior["baseline_manifest"]),
        freeze_dir / "prior_baseline" if freeze_dir else None,
    )
    prior_invariants = _transport_invariants(prior_baseline)
    current_invariants = _transport_invariants(baseline)
    if prior_invariants != current_invariants:
        changed = [name for name in prior_invariants if prior_invariants[name] != current_invariants[name]]
        raise CandidateContractError(f"prior Jacobian changes transport invariants: {changed}")
    target_k = _finite(contract["nominal"]["target_drift_period_ratio"], "target K")
    if (baseline["frozen_problem"]["targets"]["target_drift_period_ratio"] != target_k
            or prior.get("target_drift_period_ratio") != target_k):
        raise CandidateContractError("contract target K differs from transported Jacobian inputs")
    numerics = resolve_numerics(contract, baseline)
    if resolve_active_stripe_axes(contract["downstream_fixed_grid_workpoint_profile"]) != (0, 1):
        raise CandidateContractError("single active Stripe requires the staged controller, not a transported four-axis model")
    result = solve_with_jacobian(
        baseline,
        prior["physical_jacobian_rows"],
        **{key: value for key, value in numerics.items() if key != "active_stripe_axes"},
    )
    source_baseline = np.asarray(prior["baseline_voltages_v"], dtype=float)
    target_baseline = np.asarray(baseline["voltages_v"], dtype=float)
    source_trust = np.asarray(prior["resolved_numerics"]["maximum_abs_step_v"], dtype=float)
    transport_offset = target_baseline - source_baseline
    return {
        "schema_version": 1,
        "role": "mrtof_downstream_fixed_grid_workpoint_audit",
        "status": "transported_linearized_candidate_step",
        "qualification": "transported_fine_grid_jacobian_seed__requires_one_real_center_flight_confirmation",
        "target_drift_period_ratio": target_k,
        "contract_sha256": file_sha256(contract_path),
        "native_bank_identity": baseline["frozen_problem"].get("native_bank_identity"),
        "resolved_numerics": numerics,
        "baseline_manifest": baseline["manifest"],
        "prior_workpoint_manifest": str(prior_manifest_path.resolve()),
        "prior_workpoint_manifest_sha256": file_sha256(prior_manifest_path),
        "prior_workpoint_audit": str(prior_path.resolve()),
        "prior_workpoint_audit_sha256": file_sha256(prior_path),
        "prior_baseline_manifest": prior_baseline["manifest"],
        "transport_invariants": current_invariants,
        "jacobian_use": "transported_local_approximation",
        "transport_offset_from_source_baseline_v": transport_offset.tolist(),
        "source_trust_radius_v": source_trust.tolist(),
        "outside_source_trust_radius": bool(np.any(np.abs(transport_offset) > source_trust)),
        "requires_real_center_flight_confirmation": True,
        "allowed_changed_state": {
            "source_position_project_mm": {
                "prior": prior_baseline["frozen_problem"]["source_position_project_mm"],
                "current": baseline["frozen_problem"]["source_position_project_mm"],
            },
            "source_direction_project": {
                "prior": prior_baseline["frozen_problem"]["source_direction_project"],
                "current": baseline["frozen_problem"]["source_direction_project"],
            },
            "accelerator_pulse": {
                "prior": prior_baseline["frozen_problem"]["accelerator_pulse"],
                "current": baseline["frozen_problem"]["accelerator_pulse"],
            },
            "fly2_sha256": {
                "prior": prior_baseline["frozen_problem"]["fly2_sha256"],
                "current": baseline["frozen_problem"]["fly2_sha256"],
            },
        },
        "consumed_trials": [{
            key: baseline[key] for key in ("manifest", "manifest_sha256", "consumer_projection")
        }],
        **result,
    }


def audit(definition_path: Path, freeze_dir: Path | None = None) -> dict[str, Any]:
    """Audit five immutable trials under one contract-owned numerical profile."""
    definition = _load_object(definition_path)
    role = definition.get("role")
    if definition.get("schema_version") != 1 or role not in {
        "mrtof_downstream_fixed_grid_workpoint_definition",
        "mrtof_downstream_transported_jacobian_definition",
    }:
        raise CandidateContractError("invalid downstream workpoint definition role")
    contract_path = Path(definition["contract"])
    contract = _load_object(contract_path)
    if role == "mrtof_downstream_transported_jacobian_definition":
        return audit_transported(definition, contract, contract_path, freeze_dir)
    if set(definition) != {"schema_version", "role", "contract", "baseline_manifest", "perturbation_manifests"}:
        raise CandidateContractError("definition only transports contract and trial paths; numerical overrides are forbidden")
    baseline = _trial(Path(definition["baseline_manifest"]), freeze_dir / "baseline" if freeze_dir else None)
    perturbation_map = definition.get("perturbation_manifests")
    if not isinstance(perturbation_map, dict) or set(perturbation_map) != set(UNKNOWN_NAMES):
        raise CandidateContractError("definition must bind one perturbation manifest per downstream voltage")
    target_k = _finite(contract["nominal"]["target_drift_period_ratio"], "target K")
    if baseline["frozen_problem"]["targets"]["target_drift_period_ratio"] != target_k:
        raise CandidateContractError("contract target K differs from the frozen trials")
    perturbations = [_trial(Path(perturbation_map[name]), freeze_dir / name if freeze_dir else None)
                     for name in UNKNOWN_NAMES]
    numerics = resolve_numerics(contract, baseline)
    if resolve_active_stripe_axes(contract["downstream_fixed_grid_workpoint_profile"]) != (0, 1):
        raise CandidateContractError("single active Stripe requires the staged controller, not a full four-axis audit")
    result = solve_linearized_step(
        baseline, perturbations,
        **{key: value for key, value in numerics.items() if key != "active_stripe_axes"},
    )
    stripes = result["proposed_voltages_v"][:2]
    seed = contract["dual_stripe_l0"]["operating_seed_search"]
    energy = baseline["frozen_problem"]["selected_axial_energy_per_charge_v"]
    if (min(map(abs, stripes)) / max(map(abs, stripes)) < seed["minimum_bias_magnitude_ratio"]
            or abs(stripes[0] - stripes[1]) < energy * seed["minimum_bias_separation_fraction_of_nominal_energy"]):
        raise CandidateContractError("proposed Stripe pair violates the seed nondegeneracy rules")
    return {
        "schema_version": 1,
        "role": "mrtof_downstream_fixed_grid_workpoint_audit",
        "status": "linearized_candidate_step",
        "qualification": "linearized_candidate_proposal__requires_real_flight_confirmation_on_reused_response_fields",
        "target_drift_period_ratio": target_k,
        "contract_sha256": file_sha256(contract_path),
        "native_bank_identity": baseline["frozen_problem"].get("native_bank_identity"),
        "resolved_numerics": numerics,
        "consumed_trials": [
            {key: trial[key] for key in ("manifest", "manifest_sha256", "consumer_projection")}
            for trial in (baseline, *perturbations)
        ],
        "baseline_manifest": baseline["manifest"],
        "perturbation_manifests": {
            name: str(Path(perturbation_map[name]).resolve()) for name in UNKNOWN_NAMES
        },
        **result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--definition", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--freeze-input-dir", type=Path)
    args = parser.parse_args()
    result = audit(args.definition, args.freeze_input_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"MRTOF_DOWNSTREAM_FIXED_GRID_WORKPOINT={result['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
