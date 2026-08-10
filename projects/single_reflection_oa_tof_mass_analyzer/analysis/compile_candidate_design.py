"""Compile an approved oa-TOF proposal into isolated candidate contracts only."""

from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]
from common.contracts.machine_contracts import load_json, sha256, validate_schema
from common.contracts.validate_design_request import validate_request
from common.multipole.grounded_shield import require_grounded_potential
from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_time_focus import accelerator_state, focus_drift_mm
from projects.single_reflection_oa_tof_mass_analyzer.analysis.geometry_contract import BASELINE_PATH, MODE_PATH, NUMERICS_PATH, resolve_contract, serialized
from projects.single_reflection_oa_tof_mass_analyzer.analysis.oatof_oaaccelerator_coupling import solve_coupled_reflectron_fields


CATALOG_PATH = PROJECT_ROOT / "config" / "design_variables.json"
ENVELOPE_PATH = PROJECT_ROOT / "config" / "optimization_envelope.json"
REGISTRY_PATH = REPO_ROOT / "config" / "project_registry.json"


class EnvelopeReviewRequired(ValueError):
    """The requested candidate is valid in principle but exceeds the approved envelope."""


def _derive_accelerator_focus(baseline: dict[str, Any]) -> None:
    geometry = baseline["geometry_mm"]
    derivation = baseline["geometry_derivation"]["accelerator"]
    voltage = baseline["electrodes_V"]
    d1, d2 = float(derivation["d1_mm"]), float(derivation["d2_mm"])
    drift = focus_drift_mm(float(voltage["repeller"]), float(voltage["grid1"]), d1, d2)
    if drift <= 0:
        raise ValueError("accelerator time focus must lie beyond grid2")
    focus = float(geometry["accelerator_focus_z"])
    grid2 = focus - drift
    grid1 = grid2 - d2
    repeller = grid1 - d1
    geometry["L_accel"] = d1 + d2
    geometry["accelerator_repeller_z"] = repeller
    geometry["accelerator_grid1_z"] = grid1
    geometry["accelerator_grid2_z"] = grid2
    derivation["canonical_repeller_z_mm"] = repeller
    derivation["canonical_grid1_z_mm"] = grid1
    derivation["canonical_grid2_z_mm"] = grid2
    derivation["canonical_focus_z_mm"] = focus
    derivation["focus_drift_after_grid2_mm"] = drift
    baseline["particle_source"]["center_z_mm"] = repeller + d1 / 2.0


def pointer_tokens(pointer: str) -> list[str]:
    return [token.replace("~1", "/").replace("~0", "~") for token in pointer.lstrip("/").split("/")]


def pointer_get(document: dict[str, Any], pointer: str) -> Any:
    value: Any = document
    for token in pointer_tokens(pointer):
        value = value[token]
    return value


def pointer_set(document: dict[str, Any], pointer: str, value: int | float) -> None:
    parent: Any = document
    tokens = pointer_tokens(pointer)
    for token in tokens[:-1]:
        parent = parent[token]
    parent[tokens[-1]] = value


def _derive_reflectron_for_flight_length(baseline: dict[str, Any]) -> None:
    geometry = baseline["geometry_mm"]
    derivation = baseline["geometry_derivation"]["reflectron"]
    accelerator_derivation = baseline["geometry_derivation"]["accelerator"]
    voltage = baseline["electrodes_V"]
    flight = float(geometry["L_flight"])
    total_field_free = 2.0 * flight
    accelerator = accelerator_state(
        float(voltage["repeller"]),
        float(voltage["grid1"]),
        float(accelerator_derivation["d1_mm"]),
        float(accelerator_derivation["d2_mm"]),
    )
    source_width = float(baseline["particle_source"]["size_z_mm"])
    spatial_half_range = accelerator.field1_v_per_mm * source_width / 2.0
    intrinsic_half_range = float(
        derivation.get("intrinsic_axial_energy_per_charge_half_range_V", 0.0)
    )
    energy_min = (
        accelerator.nominal_energy_per_charge_v
        - spatial_half_range
        - intrinsic_half_range
    )
    energy_max = (
        accelerator.nominal_energy_per_charge_v
        + spatial_half_range
        + intrinsic_half_range
    )
    fields = solve_coupled_reflectron_fields(
        accelerator,
        float(geometry["L_stage1"]),
        flight,
        flight,
        energy_min_v=energy_min,
        energy_max_v=energy_max,
        stage2_margin_fraction=float(derivation["stage2_margin_fraction"]),
        stage2_margin_mm=float(derivation.get("stage2_margin_absolute_mm", 0.0)),
    )
    stage2_raw_mm = fields.required_stage2_depth_mm
    stage2 = round(stage2_raw_mm, int(derivation["engineering_length_decimals_mm"]))
    mirror_voltage = (
        fields.stage1_voltage_drop_v
        + fields.stage2_field_v_per_mm * stage2_raw_mm
    )
    voltage_decimals = int(derivation["engineering_voltage_decimals_V"])
    geometry["L_stage2"] = stage2
    geometry["L_reflectron"] = geometry["L_stage1"] + stage2
    baseline["electrodes_V"]["midgrid"] = round(
        fields.stage1_voltage_drop_v, voltage_decimals
    )
    baseline["electrodes_V"]["backplate"] = round(mirror_voltage, voltage_decimals)
    derivation["total_field_free_length_mm"] = total_field_free
    derivation["outbound_field_free_length_mm"] = flight
    derivation["return_field_free_length_mm"] = flight
    derivation.pop("incident_energy_eV", None)
    derivation.update(
        {
            "model_id": "oatof.oaaccelerator_reflectron_coupled.ideal_1d.v1",
            "nominal_energy_per_charge_V": accelerator.nominal_energy_per_charge_v,
            "source_release_full_width_mm": source_width,
            "spatial_energy_half_range_V": spatial_half_range,
            "intrinsic_axial_energy_per_charge_half_range_V": intrinsic_half_range,
            "energy_min_V": energy_min,
            "energy_max_V": energy_max,
            "stage2_margin_basis": "full_energy_envelope_high_tail_penetration",
            "stage2_margin_absolute_mm": float(
                derivation.get("stage2_margin_absolute_mm", 0.0)
            ),
            "rule": (
                "Solve the coupled accelerator-to-detector first- and second-order "
                "conditions for U_R1 and F_2; derive the source-correlated full "
                "energy envelope from accelerator E_A1 and source z width; set "
                "L_stage2=((W_max-U_R1)/F_2)*(1+margin_fraction)+margin_absolute; "
                "derive V_backplate=U_R1+F_2*L_stage2_raw; round only final "
                "engineering lengths and voltages."
            ),
        }
    )


def _derive_shield_bounds(baseline: dict[str, Any]) -> None:
    geometry = baseline["geometry_mm"]
    near = (
        geometry["accelerator_repeller_z"]
        - geometry["accelerator_repeller_thickness"]
        - geometry["accelerator_rear_clearance"]
        - geometry["accelerator_shield_wall"]
        - geometry["shield_near_endcap_gap"]
    )
    far = geometry["L_flight"] + geometry["L_reflectron"] + geometry["ring_thickness"] + geometry["shield_axial_gap"]
    geometry["shield_bore_z_min"] = near
    geometry["shield_bore_z_max"] = far
    geometry["shield_outer_z_min"] = near - geometry["shield_endcap_thickness"]
    geometry["shield_outer_z_max"] = far + geometry["shield_endcap_thickness"]


def _validate_invariants(baseline: dict[str, Any]) -> None:
    require_grounded_potential(baseline["electrodes_V"]["shield"], "oaTOF shield")
    geometry = baseline["geometry_mm"]
    rings = baseline["rings"]
    if not geometry["bore_r"] < geometry["ring_outer_r"] < geometry["flight_tube_r"]:
        raise ValueError("reflectron radial order must be bore < ring outer radius < shield inner radius")
    if geometry["detector_radius"] > geometry["flight_tube_r"]:
        raise ValueError("detector radius must lie inside the shield")
    if geometry["ring_thickness"] >= geometry["L_stage1"] / (rings["stage1_count"] + 1):
        raise ValueError("stage-1 rings overlap at the requested count and thickness")
    if geometry["ring_thickness"] >= geometry["L_stage2"] / (rings["stage2_count"] + 1):
        raise ValueError("stage-2 rings overlap at the requested count and thickness")
    accelerator = baseline["geometry_derivation"]["accelerator"]
    if geometry["accelerator_ring_thickness"] >= accelerator["d2_mm"] / (rings["accelerator_count"] + 1):
        raise ValueError("accelerator rings overlap at the requested count and thickness")
    if baseline["particle_source"]["size_z_mm"] > accelerator["d1_mm"]:
        raise ValueError("particle-source axial size must fit between repeller and grid1")
    if geometry["accelerator_exit_grid_half_width"] < geometry["accelerator_bore_half"]:
        raise ValueError("accelerator exit grid must cover the clear aperture")
    if not math.isclose(geometry["L_reflectron"], geometry["L_stage1"] + geometry["L_stage2"], abs_tol=1e-10):
        raise ValueError("reflectron length identity failed")
    if not math.isclose(geometry["L_accel"], accelerator["d1_mm"] + accelerator["d2_mm"], abs_tol=1e-10):
        raise ValueError("accelerator length identity failed")


def compile_design_overrides(
    base_contract: dict[str, Any], overrides: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply catalog variables and automatically close all theoretical dependencies."""
    catalog = load_json(CATALOG_PATH)
    validate_schema(catalog, "design_variable_catalog.schema.json")
    definitions = {item["variable_id"]: item for item in catalog["variables"]}
    values: dict[str, float | int] = {}
    for item in overrides:
        variable_id = str(item["variable"])
        if variable_id in values:
            raise ValueError(f"duplicate design override: {variable_id}")
        definition = definitions.get(variable_id)
        if definition is None:
            raise ValueError(f"unknown design override: {variable_id}")
        if definition["kind"] == "derived":
            raise ValueError(f"derived variable cannot be specified: {variable_id}")
        if definition["kind"] == "topology":
            raise ValueError(
                f"topology variable requires a dedicated compiler: {variable_id}"
            )
        if item["unit"] != definition["unit"]:
            raise ValueError(f"unit mismatch for {variable_id}")
        value = float(item["value"])
        if not math.isfinite(value) or not definition["minimum"] <= value <= definition["maximum"]:
            raise ValueError(f"design override outside compilation bounds: {variable_id}")
        if definition["kind"] == "integer":
            if not value.is_integer():
                raise ValueError(f"integer design override required: {variable_id}")
            values[variable_id] = int(value)
        else:
            values[variable_id] = value

    candidate = copy.deepcopy(base_contract)
    reflectron_voltage_ids = {
        "reflectron_midgrid_voltage", "reflectron_backplate_voltage"
    }
    for variable_id, value in values.items():
        if variable_id not in reflectron_voltage_ids:
            pointer_set(candidate, definitions[variable_id]["json_pointer"], value)
    accelerator_focus_inputs = {
        "accelerator_repeller_voltage", "accelerator_grid1_voltage",
        "accelerator_stage1_length", "accelerator_stage2_length",
    }
    if accelerator_focus_inputs & values.keys():
        _derive_accelerator_focus(candidate)
    coupled_longitudinal_inputs = accelerator_focus_inputs | {
        "flight_length", "reflectron_stage1_length", "source_release_full_width"
    }
    if coupled_longitudinal_inputs & values.keys():
        _derive_reflectron_for_flight_length(candidate)
    if values:
        _derive_shield_bounds(candidate)
    for variable_id in reflectron_voltage_ids & values.keys():
        pointer_set(
            candidate, definitions[variable_id]["json_pointer"], values[variable_id]
        )
    _validate_invariants(candidate)

    changed = []
    rebuild_effects: set[str] = set()
    for variable_id, value in values.items():
        definition = definitions[variable_id]
        before = pointer_get(base_contract, definition["json_pointer"])
        after = pointer_get(candidate, definition["json_pointer"])
        if before != after:
            changed.append({
                "variable": variable_id, "before": before, "after": after,
                "unit": definition["unit"],
            })
            rebuild_effects.update(definition["rebuild_effects"])
    rebuild_plan = {
        "frontend_pa": bool(
            accelerator_focus_inputs & values.keys()
            or any(name.startswith("accelerator_") and "voltage" not in name
                   for name in values)
        ),
        "flight_tube_pa": bool(
            accelerator_focus_inputs & values.keys()
            or {"flight_length", "accelerator_shield_wall_thickness",
             "accelerator_rear_clearance", "accelerator_repeller_thickness",
             "reflectron_shield_inner_radius",
             "reflectron_shield_wall_thickness",
             "reflectron_shield_endcap_thickness",
             "reflectron_shield_near_endcap_gap"} & values.keys()
        ),
        "reflectron_pa": bool(
            coupled_longitudinal_inputs & values.keys()
            or any(name.startswith("reflectron_") and "voltage" not in name
                   for name in values)
        ),
    }
    return candidate, {
        "method": "catalog_design_overrides_with_theory_closure_v1",
        "changed_variables": changed,
        "rebuild_effects": sorted(rebuild_effects),
        "simion_rebuild_plan": rebuild_plan,
    }


def _envelope_excesses(baseline: dict[str, Any], envelope: dict[str, Any]) -> list[str]:
    geometry = baseline["geometry_mm"]
    rings = baseline["rings"]
    limits = envelope["tof_limits"]
    values = {
        "max_flight_length_mm": geometry["L_flight"],
        "max_positive_axial_extent_mm": geometry["shield_outer_z_max"] - geometry["detector_z"],
        "max_outer_radius_mm": geometry["flight_tube_r"] + geometry["flight_tube_wall"],
        "max_stage1_electrode_count": rings["stage1_count"],
        "max_stage2_electrode_count": rings["stage2_count"],
    }
    return [f"{name}: candidate={value:g} approved_max={limits[name]:g}" for name, value in values.items() if value > limits[name] + 1e-10]


def _variable_envelope_excesses(
    values: dict[str, dict[str, Any]], envelope: dict[str, Any]
) -> list[str]:
    limits = {
        item["variable_id"]: item
        for item in envelope["design_variable_limits"]
    }
    excesses: list[str] = []
    for variable_id, item in values.items():
        limit = limits.get(variable_id)
        if limit is None:
            continue
        elif item["unit"] != limit["unit"]:
            excesses.append(f"{variable_id}: envelope unit differs")
        elif not limit["minimum"] <= item["value"] <= limit["maximum"]:
            excesses.append(
                f"{variable_id}: candidate={item['value']:g} approved="
                f"[{limit['minimum']:g}, {limit['maximum']:g}]"
            )
    return excesses


def _constraint_passes(value: float, operator: str, threshold: float) -> bool:
    return {">=": value >= threshold, ">": value > threshold, "<=": value <= threshold,
            "<": value < threshold, "=": math.isclose(value, threshold, rel_tol=0.0, abs_tol=1e-12)}[operator]


def compile_proposal(proposal_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    proposal_path = proposal_path.resolve()
    proposal = load_json(proposal_path)
    validate_schema(proposal, "candidate_proposal.schema.json")
    if proposal["project_id"] != "single_reflection_oa_tof_mass_analyzer":
        raise ValueError(
            "candidate proposal project_id must be "
            "single_reflection_oa_tof_mass_analyzer"
        )
    request_path = Path(proposal["request"]["path"])
    if not request_path.is_absolute():
        request_path = (proposal_path.parent / request_path).resolve()
    if sha256(request_path) != proposal["request"]["sha256"]:
        raise ValueError("design request hash differs from candidate proposal")
    request = load_json(request_path)
    registry = load_json(REGISTRY_PATH)
    selection = validate_request(request, registry)
    if selection["status"] != "READY" or selection["selected_project_id"] != "single_reflection_oa_tof_mass_analyzer":
        raise ValueError(
            "design request is not ready for "
            f"single_reflection_oa_tof_mass_analyzer: {selection['status']}"
        )
    if request["status"] != "approved":
        raise ValueError("candidate compilation requires an approved design request")

    catalog = load_json(CATALOG_PATH)
    envelope = load_json(ENVELOPE_PATH)
    validate_schema(catalog, "design_variable_catalog.schema.json")
    validate_schema(envelope, "optimization_envelope.schema.json")
    if envelope["status"] != "approved":
        raise ValueError("optimization envelope is not approved")
    if envelope["reference"]["baseline_sha256"] != sha256(BASELINE_PATH):
        raise ValueError("optimization envelope reference baseline is stale")
    definitions = {item["variable_id"]: item for item in catalog["variables"]}
    requested = set(request["design_variables"])
    values: dict[str, dict[str, Any]] = {}
    for item in proposal["values"]:
        variable_id = item["variable"]
        if variable_id in values:
            raise ValueError(f"duplicate candidate variable: {variable_id}")
        if variable_id not in requested:
            raise ValueError(f"candidate variable was not approved by the request: {variable_id}")
        definition = definitions.get(variable_id)
        if definition is None:
            raise ValueError(f"candidate variable is absent from the catalog: {variable_id}")
        if definition["kind"] == "derived":
            raise ValueError(f"derived variable cannot be proposed: {variable_id}")
        if definition["kind"] == "topology":
            raise ValueError(
                f"topology variable requires a dedicated compiler: {variable_id}"
            )
        if item["unit"] != definition["unit"]:
            raise ValueError(f"unit mismatch for {variable_id}: {item['unit']} != {definition['unit']}")
        value = item["value"]
        if not definition["minimum"] <= value <= definition["maximum"]:
            raise ValueError(f"candidate value outside static safety bounds: {variable_id}")
        if definition["kind"] == "integer" and not float(value).is_integer():
            raise ValueError(f"integer candidate variable requires an integer value: {variable_id}")
        values[variable_id] = item

    formal = load_json(BASELINE_PATH)
    candidate = copy.deepcopy(formal)
    accelerator_voltage_ids = {"accelerator_repeller_voltage", "accelerator_grid1_voltage"}
    reflectron_voltage_ids = {"reflectron_midgrid_voltage", "reflectron_backplate_voltage"}
    voltage_ids = accelerator_voltage_ids | reflectron_voltage_ids
    for variable_id, item in values.items():
        if variable_id not in voltage_ids:
            definition = definitions[variable_id]
            value = int(item["value"]) if definition["kind"] == "integer" else item["value"]
            pointer_set(candidate, definition["json_pointer"], value)
    for variable_id in accelerator_voltage_ids & values.keys():
        pointer_set(candidate, definitions[variable_id]["json_pointer"], values[variable_id]["value"])
    accelerator_focus_inputs = accelerator_voltage_ids | {
        "accelerator_stage1_length", "accelerator_stage2_length"
    }
    if accelerator_focus_inputs & values.keys():
        _derive_accelerator_focus(candidate)
    longitudinal_inputs = accelerator_focus_inputs | {
        "flight_length", "reflectron_stage1_length", "source_release_full_width"
    }
    if longitudinal_inputs & values.keys():
        _derive_reflectron_for_flight_length(candidate)
    if values:
        _derive_shield_bounds(candidate)
    for variable_id, item in values.items():
        if variable_id in reflectron_voltage_ids:
            pointer_set(candidate, definitions[variable_id]["json_pointer"], item["value"])
    _validate_invariants(candidate)

    envelope_applies = any(
        definitions[variable_id]["optimization_role"] != "accelerator_bidirectional"
        for variable_id in values
    )
    excesses = _variable_envelope_excesses(values, envelope)
    if envelope_applies:
        excesses.extend(_envelope_excesses(candidate, envelope))
    if excesses:
        raise EnvelopeReviewRequired("NEEDS_ENVELOPE_REVIEW: " + "; ".join(excesses))
    for constraint in request["constraints"]:
        definition = definitions.get(constraint["parameter"])
        if definition is None:
            raise ValueError(f"candidate compiler cannot evaluate constraint: {constraint['parameter']}")
        if constraint["unit"] != definition["unit"]:
            raise ValueError(f"constraint unit mismatch: {constraint['parameter']}")
        actual = float(pointer_get(candidate, definition["json_pointer"]))
        if not _constraint_passes(actual, constraint["operator"], float(constraint["value"])):
            raise ValueError(f"candidate violates constraint {constraint['parameter']} {constraint['operator']} {constraint['value']} {constraint['unit']}; actual={actual:g}")

    changes = []
    for variable_id, definition in definitions.items():
        before = pointer_get(formal, definition["json_pointer"])
        after = pointer_get(candidate, definition["json_pointer"])
        if before != after:
            changes.append({"variable": variable_id, "before": before, "after": after,
                            "unit": definition["unit"], "change_origin": "proposed" if variable_id in values else "derived",
                            "rebuild_effects": definition["rebuild_effects"]})
    derived_fields = {
        "accelerator_total_length": ("/geometry_mm/L_accel", "mm"),
        "accelerator_repeller_z": ("/geometry_mm/accelerator_repeller_z", "mm"),
        "accelerator_grid1_z": ("/geometry_mm/accelerator_grid1_z", "mm"),
        "accelerator_grid2_z": ("/geometry_mm/accelerator_grid2_z", "mm"),
        "particle_source_center_z": ("/particle_source/center_z_mm", "mm"),
        "reflectron_stage2_length": ("/geometry_mm/L_stage2", "mm"),
        "reflectron_total_length": ("/geometry_mm/L_reflectron", "mm"),
        "shield_bore_z_min": ("/geometry_mm/shield_bore_z_min", "mm"),
        "shield_bore_z_max": ("/geometry_mm/shield_bore_z_max", "mm"),
        "shield_outer_z_min": ("/geometry_mm/shield_outer_z_min", "mm"),
        "shield_outer_z_max": ("/geometry_mm/shield_outer_z_max", "mm"),
    }
    derived_changes = []
    for field, (pointer, unit) in derived_fields.items():
        before, after = pointer_get(formal, pointer), pointer_get(candidate, pointer)
        if before != after:
            derived_changes.append({"field": field, "before": before, "after": after, "unit": unit})
    report = {
        "schema_version": 1,
        "role": "oa_tof_candidate_contract_diff",
        "candidate_id": proposal["candidate_id"],
        "request_id": request["request_id"],
        "provenance": {
            "proposal": {"path": str(proposal_path), "sha256": sha256(proposal_path)},
            "request": {"path": str(request_path), "sha256": sha256(request_path)},
            "design_variable_catalog": {"path": str(CATALOG_PATH), "sha256": sha256(CATALOG_PATH)},
            "formal_solver_numerics": {"path": str(NUMERICS_PATH), "sha256": sha256(NUMERICS_PATH)},
        },
        "optimization_envelope": {"envelope_id": envelope["envelope_id"], "sha256": sha256(ENVELOPE_PATH)},
        "formal_baseline_sha256": sha256(BASELINE_PATH),
        "changed_variables": changes,
        "derived_changes": derived_changes,
        "zero_change_reference_reproduction": not changes,
        "solver_or_cad_executed": False,
    }
    return candidate, report, request


def write_candidate(proposal_path: Path, output_dir: Path) -> tuple[Path, Path, Path]:
    candidate, report, _ = compile_proposal(proposal_path)
    output_dir.mkdir(parents=True, exist_ok=False)
    baseline_path = output_dir / "candidate_baseline.json"
    resolved_path = output_dir / "candidate_resolved_geometry.json"
    numerics_path = output_dir / "candidate_solver_numerics.json"
    report_path = output_dir / "candidate_diff.json"
    baseline_path.write_text(json.dumps(candidate, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    numerics_path.write_text(NUMERICS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    resolved_path.write_text(serialized(resolve_contract(baseline_path=baseline_path, mode_path=MODE_PATH, numerics_path=numerics_path)), encoding="utf-8")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return baseline_path, resolved_path, report_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proposal", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        baseline, resolved, report = write_candidate(args.proposal, args.output_dir)
    except EnvelopeReviewRequired as exc:
        raise SystemExit(str(exc)) from exc
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"CANDIDATE_COMPILE=FAIL {exc}") from exc
    print(f"CANDIDATE_COMPILE=PASS BASELINE={baseline.resolve()} RESOLVED={resolved.resolve()} NUMERICS={(resolved.parent / 'candidate_solver_numerics.json').resolve()} DIFF={report.resolve()}")


if __name__ == "__main__":
    main()
