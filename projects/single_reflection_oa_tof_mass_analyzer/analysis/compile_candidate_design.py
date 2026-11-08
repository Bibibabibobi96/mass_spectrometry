"""Compile an approved oa-TOF proposal into isolated candidate contracts only."""

from __future__ import annotations

from msplatform.components.single_reflection_oa_tof.design_compilation import (
    EnvelopeReviewRequired as EnvelopeReviewRequired,
    _derive_accelerator_focus as _derive_accelerator_focus,
    pointer_tokens as pointer_tokens,
    pointer_get as pointer_get,
    pointer_set as pointer_set,
    _derive_reflectron_for_flight_length as _derive_reflectron_for_flight_length,
    derive_accelerator_outer_envelope_min_z as derive_accelerator_outer_envelope_min_z,
    derive_shield_bounds as derive_shield_bounds,
    _validate_invariants as _canonical_validate_invariants,
    compile_design_overrides as _canonical_compile_overrides,
)

import argparse
import copy
import json
import math
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]
from msplatform.contracts.machine_contracts import load_json, sha256, validate_schema
from common.contracts.validate_design_request import validate_request
from projects.single_reflection_oa_tof_mass_analyzer.analysis.geometry_contract import BASELINE_PATH, MODE_PATH, NUMERICS_PATH, resolve_contract, serialized


CATALOG_PATH = PROJECT_ROOT / "config" / "design_variables.json"
ENVELOPE_PATH = PROJECT_ROOT / "config" / "optimization_envelope.json"
REGISTRY_PATH = REPO_ROOT / "config" / "project_registry.json"


def compile_design_overrides(base_contract, overrides):
    return _canonical_compile_overrides(base_contract, overrides, catalog=load_json(CATALOG_PATH))

def _validate_invariants(baseline):
    return _canonical_validate_invariants(baseline, catalog=load_json(CATALOG_PATH))


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
        derive_shield_bounds(
            candidate, derive_accelerator_outer_envelope_min_z(candidate)
        )
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


def write_candidate(proposal_path: Path, output_dir: Path, *,
                    solver_numerics_contract: Path | None = None) -> tuple[Path, Path, Path]:
    candidate, report, _ = compile_proposal(proposal_path)
    numerics_source = (NUMERICS_PATH if solver_numerics_contract is None else solver_numerics_contract).resolve(strict=True)
    numerics_payload = numerics_source.read_bytes()
    output_dir.mkdir(parents=True, exist_ok=False)
    baseline_path = output_dir / "candidate_baseline.json"
    resolved_path = output_dir / "candidate_resolved_geometry.json"
    numerics_path = output_dir / "candidate_solver_numerics.json"
    report_path = output_dir / "candidate_diff.json"
    baseline_path.write_text(json.dumps(candidate, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Freeze the selected pure-data contract once; all resolution consumes this
    # copy rather than later external/default values. Validation stays with the
    # existing geometry/numerics resolver and its original policies.
    numerics_path.write_bytes(numerics_payload)
    resolved = resolve_contract(baseline_path=baseline_path, mode_path=MODE_PATH, numerics_path=numerics_path)
    report["provenance"]["solver_numerics"] = {"path": str(numerics_source),
        "sha256": resolved["inputs"]["solver_numerics_sha256"]}
    report["zero_change_reference_reproduction"] = (
        report["zero_change_reference_reproduction"] and
        resolved["inputs"]["solver_numerics_sha256"].upper() ==
        report["provenance"]["formal_solver_numerics"]["sha256"].upper())
    resolved_path.write_text(serialized(resolved), encoding="utf-8")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return baseline_path, resolved_path, report_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proposal", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--solver-numerics-contract", type=Path,
                        help="Explicit solver numerics JSON; default remains the project contract")
    args = parser.parse_args()
    try:
        baseline, resolved, report = write_candidate(args.proposal, args.output_dir,
            solver_numerics_contract=args.solver_numerics_contract)
    except EnvelopeReviewRequired as exc:
        raise SystemExit(str(exc)) from exc
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"CANDIDATE_COMPILE=FAIL {exc}") from exc
    print(f"CANDIDATE_COMPILE=PASS BASELINE={baseline.resolve()} RESOLVED={resolved.resolve()} NUMERICS={(resolved.parent / 'candidate_solver_numerics.json').resolve()} DIFF={report.resolve()}")


if __name__ == "__main__":
    main()
