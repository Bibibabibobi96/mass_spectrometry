"""Verify and compare the four managed COMSOL runs without survivor filtering."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.artifact_naming import validate_run_id
from common.contracts.file_identity import file_sha256
from common.contracts.particle_state import (
    PARTICLE_STATE_COLUMNS,
    canonical_sources,
    validate_particle_state,
)
from common.contracts.verify_run_manifest import verify_record
from projects.rf_quadrupole_collision_cooling.analysis.generate_interface_particle_table import (
    validate_bundle,
)


ROLE = "rf_quadrupole_axial_acceleration_four_arm_post_run_acceptance"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _contained_file(root: Path, value: str, label: str) -> Path:
    path = Path(value).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"{label} is missing or outside its managed run: {path}")
    return path


def _bundle_artifact(
    metadata: dict[str, Any], selector: dict[str, Any]
) -> dict[str, Any]:
    matches = [
        item
        for item in metadata["artifacts"]
        if item["operating_point_id"] == selector["operating_point_id"]
        and int(item["particle_count"]) == int(selector["particle_count"])
        and item["representation"] == selector["representation"]
    ]
    if len(matches) != 1:
        raise ValueError("bundle does not uniquely satisfy an arm source selector")
    return matches[0]


def _repository_file(relative: str) -> Path:
    path = (REPOSITORY_ROOT / relative).resolve()
    if not path.is_relative_to(REPOSITORY_ROOT) or not path.is_file():
        raise ValueError(f"contract authority is missing or escapes repository: {relative}")
    return path


def _json_pointer(document: dict[str, Any], pointer: str) -> Any:
    if not pointer.startswith("/"):
        raise ValueError("acceptance-surface JSON pointer is invalid")
    value: Any = document
    for encoded in pointer[1:].split("/"):
        token = encoded.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or token not in value:
            raise ValueError("acceptance-surface JSON pointer does not resolve")
        value = value[token]
    return value


def _validate_joint_contract(
    contract: dict[str, Any], bundle_metadata_path: Path
) -> tuple[dict[str, Any], float]:
    project_id = contract.get("project_id")
    if (
        contract.get("schema_version") != 1
        or contract.get("role")
        != "rf_quadrupole_axial_acceleration_four_arm_experiment"
        or not isinstance(project_id, str)
    ):
        raise ValueError("four-arm experiment identity is invalid")
    arms = contract.get("arms")
    selectors = contract.get("source_selectors")
    if not isinstance(arms, list) or len(arms) != 4 or not isinstance(selectors, dict):
        raise ValueError("four-arm experiment inventory is invalid")
    arm_ids = [arm.get("arm_id") for arm in arms]
    if any(not isinstance(arm_id, str) for arm_id in arm_ids) or len(set(arm_ids)) != 4:
        raise ValueError("four-arm IDs are invalid or duplicated")
    for arm in arms:
        if (
            arm.get("source_selector") not in selectors
            or not isinstance(arm.get("design_profile_id"), str)
            or not isinstance(arm.get("primary_case_id"), str)
        ):
            raise ValueError(f"arm {arm.get('arm_id')} binding is incomplete")
    comparison = contract.get("comparison_contract", {})
    execution_order = comparison.get("execution_order")
    expected_comsol_order = [f"COMSOL_{arm_id}" for arm_id in arm_ids]
    if (
        not isinstance(execution_order, list)
        or execution_order[: len(arms)] != expected_comsol_order
        or execution_order[len(arms) : len(arms) + 1] != ["COMSOL_delta_report"]
    ):
        raise ValueError("four-arm COMSOL execution order differs from arm order")
    paired = comparison.get("paired_population")
    if paired != {
        "all_source_particle_ids_required": True,
        "loss_filtering_allowed": False,
        "common_survivor_filtering_allowed": False,
    }:
        raise ValueError("four-arm paired population must prohibit filtering")
    c_vs_d = comparison.get("C_vs_D")
    if c_vs_d != {
        "reporting_mode": "delta_only",
        "equivalence_tolerance": None,
        "equivalence_claim_allowed": False,
    }:
        raise ValueError("C/D reporting must remain delta-only without tolerance")
    post_run = comparison.get("post_run_acceptance")
    if not isinstance(post_run, dict) or not isinstance(
        post_run.get("comparisons"), list
    ):
        raise ValueError("four-arm post-run acceptance binding is missing")
    if (
        not isinstance(post_run.get("terminal_event"), str)
        or not isinstance(post_run.get("terminal_status"), str)
        or not isinstance(post_run.get("terminal_reason"), str)
        or not isinstance(post_run.get("state_output"), str)
        or not isinstance(post_run.get("metrics_output"), str)
        or not isinstance(post_run.get("comparison_fields"), list)
        or not isinstance(post_run.get("descriptive_aggregations"), list)
        or not isinstance(post_run.get("claim_limit"), str)
    ):
        raise ValueError("four-arm post-run acceptance fields are invalid")
    aggregation_names: set[str] = set()
    for aggregation in post_run["descriptive_aggregations"]:
        output_name = aggregation.get("output_name")
        if (
            not isinstance(output_name, str)
            or output_name in aggregation_names
            or aggregation.get("field") not in post_run["comparison_fields"]
            or aggregation.get("operation") not in {"mean", "rms"}
        ):
            raise ValueError("four-arm descriptive aggregation is invalid")
        aggregation_names.add(output_name)
    known_ids = set(arm_ids)
    comparison_ids: set[str] = set()
    for declaration in post_run["comparisons"]:
        comparison_id = declaration.get("comparison_id")
        if (
            not isinstance(comparison_id, str)
            or comparison_id in comparison_ids
            or declaration.get("minuend_arm_id") not in known_ids
            or declaration.get("subtrahend_arm_id") not in known_ids
            or declaration.get("reporting_mode")
            not in {"functional_delta", "delta_only"}
        ):
            raise ValueError("four-arm comparison declaration is invalid")
        comparison_ids.add(comparison_id)
    authorities = contract.get("authorities", {})
    metadata = validate_bundle(
        bundle_metadata_path,
        _repository_file(authorities["source_family"]),
        _repository_file(authorities["distribution"]),
        _repository_file(authorities["bundle_preflight_resolved"]),
    )
    surface = comparison.get("acceptance_surface", {})
    interface_path = _repository_file(surface["contract"])
    interface = _load(interface_path)
    detector = _json_pointer(interface, surface["json_pointer"])
    if not isinstance(detector, dict) or not math.isfinite(float(detector["z_mm"])):
        raise ValueError("acceptance-surface contract lacks a finite z_mm")
    return metadata, float(detector["z_mm"])


def _manifest_output(manifest: dict[str, Any], expected: Path) -> None:
    matches = [
        record
        for record in manifest.get("outputs", [])
        if Path(record["path"]).resolve() == expected
    ]
    if len(matches) != 1:
        raise ValueError(f"managed manifest does not uniquely freeze output: {expected}")


def _manifest_input(
    manifest: dict[str, Any], name: str, expected: Path, arm_id: str
) -> None:
    record = manifest.get("inputs", {}).get(name)
    if record is None or Path(record["path"]).resolve() != expected:
        raise ValueError(f"arm {arm_id} manifest does not freeze input {name}")


def _state_rows(
    path: Path, terminal_event: str
) -> tuple[dict[int, dict[str, str]], set[int]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != PARTICLE_STATE_COLUMNS:
            raise ValueError("primary particle-state columns differ from canonical contract")
        rows = list(reader)
    source_ids = {
        int(row["particle_id"]) for row in rows if row["event"] == "source"
    }
    terminal_rows = [row for row in rows if row["event"] == terminal_event]
    terminal: dict[int, dict[str, str]] = {}
    for row in terminal_rows:
        particle_id = int(row["particle_id"])
        if particle_id in terminal:
            raise ValueError(f"duplicate terminal row for particle {particle_id}")
        terminal[particle_id] = row
    if len(source_ids) != sum(row["event"] == "source" for row in rows):
        raise ValueError("duplicate source particle ID")
    return terminal, source_ids


def _verify_arm(
    arm: dict[str, Any],
    selector: dict[str, Any],
    artifact: dict[str, Any],
    metadata: dict[str, Any],
    run_root: Path,
    detector_z_mm: float,
    post_run: dict[str, Any],
    project_id: str,
) -> dict[str, Any]:
    root = run_root.resolve()
    validate_run_id(root.name)
    manifest_path = root / "run_manifest.json"
    config_path = root / "run_config.json"
    if not manifest_path.is_file() or not config_path.is_file():
        raise ValueError(f"arm {arm['arm_id']} lacks its managed run records")
    manifest = _load(manifest_path)
    if (
        manifest.get("role") != "simulation_run_manifest"
        or manifest.get("status") != "success"
    ):
        raise ValueError(f"arm {arm['arm_id']} manifest is not success")
    manifest_config = Path(manifest["run_config"]["path"]).resolve()
    if manifest_config != config_path:
        raise ValueError(f"arm {arm['arm_id']} manifest does not freeze local run_config")
    verify_record("run_config", manifest["run_config"])
    for name, record in manifest.get("inputs", {}).items():
        _contained_file(root, record["path"], f"arm {arm['arm_id']} input {name}")
        verify_record(f"input {name}", record)
    for index, record in enumerate(manifest.get("outputs", []), start=1):
        _contained_file(root, record["path"], f"arm {arm['arm_id']} output {index}")
        verify_record(f"output {index}", record)

    config = _load(config_path)
    expected_identity = {
        "run_id": root.name,
        "project": project_id,
        "mode": post_run["run_mode"],
    }
    for field, expected in expected_identity.items():
        if manifest.get(field) != expected or config.get(field) != expected:
            raise ValueError(f"arm {arm['arm_id']} {field} identity differs")
    if config.get("role") != "multipole_resolved_comsol_run_config":
        raise ValueError(f"arm {arm['arm_id']} run_config role differs")
    parameters = config.get("parameters", {})
    provenance = config.get("provenance", {})
    expected_point = selector["operating_point_id"]
    expected_family_sha = metadata["inputs"]["source_family_sha256"]
    if (
        parameters.get("design_profile_id") != arm["design_profile_id"]
        or parameters.get("operating_point_id") != expected_point
        or provenance.get("particle_source_sha256") != artifact["sha256"]
        or provenance.get("source_family_sha256") != expected_family_sha
        or provenance.get("operating_point_id") != expected_point
        or provenance.get("particle_source_operating_point_binding")
        != {
            "operating_point_id": expected_point,
            "source_family_sha256": expected_family_sha,
        }
    ):
        raise ValueError(f"arm {arm['arm_id']} source/profile binding differs")

    inputs = config.get("inputs", {})
    for name, value in inputs.items():
        if isinstance(value, str):
            declared = _contained_file(
                root, value, f"arm {arm['arm_id']} declared input {name}"
            )
            _manifest_input(manifest, name, declared, arm["arm_id"])
        elif value is not None:
            raise ValueError(f"arm {arm['arm_id']} input {name} is not a path or null")
    required_inputs = {
        "design_profile_resolution",
        "multipole_resolved_design",
        "particle_source",
        "particle_source_metadata",
        "particle_source_family",
    }
    if not required_inputs.issubset(inputs):
        raise ValueError(f"arm {arm['arm_id']} lacks frozen identity inputs")
    frozen_inputs = {
        name: _contained_file(root, inputs[name], f"arm {arm['arm_id']} input {name}")
        for name in required_inputs
    }
    for name, path in frozen_inputs.items():
        _manifest_input(manifest, name, path, arm["arm_id"])
    profile_resolution = _load(frozen_inputs["design_profile_resolution"])
    if profile_resolution.get("profile", {}).get("design_profile_id") != arm[
        "design_profile_id"
    ]:
        raise ValueError(f"arm {arm['arm_id']} frozen profile identity differs")
    resolved = _load(frozen_inputs["multipole_resolved_design"])
    if provenance.get("parent_resolved_design_sha256") != resolved.get(
        "resolved_sha256"
    ):
        raise ValueError(f"arm {arm['arm_id']} resolved-design identity differs")
    resolved_detector_z = float(
        resolved["interfaces_mm"]["exit"]["particle_plane_z_mm"]
    )
    if not math.isclose(
        resolved_detector_z, detector_z_mm, rel_tol=0.0, abs_tol=1e-9
    ):
        raise ValueError(f"arm {arm['arm_id']} resolved acceptance plane differs")
    source = frozen_inputs["particle_source"]
    family = frozen_inputs["particle_source_family"]
    source_metadata = _load(frozen_inputs["particle_source_metadata"])
    if (
        file_sha256(source) != artifact["sha256"]
        or file_sha256(family) != expected_family_sha
        or source_metadata.get("source_sha256") != artifact["sha256"]
        or source_metadata.get("operating_point_binding")
        != provenance["particle_source_operating_point_binding"]
    ):
        raise ValueError(f"arm {arm['arm_id']} frozen source identity differs")
    evidence_reference = arm.get("evidence_contract")
    frozen_evidence = inputs.get("evidence_contract")
    if evidence_reference is None:
        if frozen_evidence is not None:
            raise ValueError(f"arm {arm['arm_id']} freezes unexpected evidence")
    else:
        if not isinstance(frozen_evidence, str):
            raise ValueError(f"arm {arm['arm_id']} lacks its required evidence input")
        evidence = frozen_inputs.get("evidence_contract")
        if evidence is None:
            evidence = _contained_file(
                root, frozen_evidence, f"arm {arm['arm_id']} evidence contract"
            )
        if file_sha256(evidence) != file_sha256(_repository_file(evidence_reference)):
            raise ValueError(f"arm {arm['arm_id']} evidence contract identity differs")

    state = _contained_file(
        root, str(root / post_run["state_output"]), "primary particle state"
    )
    _manifest_output(manifest, state)
    state_report = validate_particle_state(
        state,
        canonical_sources(source),
        float(resolved["drive"]["frequency_Hz"]),
        float(resolved["drive"]["phase_rad"]),
        float(resolved["geometry_mm"]["rod_z_max"]),
        float(resolved["interfaces_mm"]["exit"]["plate_z_max_mm"]),
    )
    terminal, source_ids = _state_rows(state, post_run["terminal_event"])
    expected_ids = set(canonical_sources(source))
    if source_ids != expected_ids or set(terminal) != expected_ids:
        raise ValueError(
            f"arm {arm['arm_id']} does not preserve the complete source ID set"
        )
    if len(expected_ids) != int(selector["particle_count"]):
        raise ValueError(f"arm {arm['arm_id']} particle count differs from selector")
    for particle_id, row in terminal.items():
        if (
            row["status"] != post_run["terminal_status"]
            or row["terminal_reason"] != post_run["terminal_reason"]
            or not math.isclose(
                float(row["axial_z_mm"]), detector_z_mm, rel_tol=0.0, abs_tol=1e-9
            )
        ):
            raise ValueError(
                f"arm {arm['arm_id']} particle {particle_id} failed acceptance detector"
            )
    metrics_path = _contained_file(
        root, str(root / post_run["metrics_output"]), "transport metrics"
    )
    metrics = _load(metrics_path)
    _manifest_output(manifest, metrics_path.resolve())
    if metrics.get("primary_case_id") != arm["primary_case_id"]:
        raise ValueError(f"arm {arm['arm_id']} primary case identity differs")
    return {
        "run_id": root.name,
        "design_profile_id": arm["design_profile_id"],
        "operating_point_id": expected_point,
        "primary_case_id": arm["primary_case_id"],
        "source_sha256": artifact["sha256"],
        "source_particle_count": len(source_ids),
        "acceptance_detector_count": len(terminal),
        "full_source_id_set": "PASS",
        "state_contract": state_report["status"],
        "terminal": terminal,
        "resolved_axial_drive": resolved["axial_drive"],
    }


def _aggregate(
    rows: dict[int, dict[str, str]], field: str, operation: str
) -> float:
    values = [float(row[field]) for row in rows.values()]
    if operation == "mean":
        return sum(values) / len(values)
    if operation == "rms":
        return math.sqrt(sum(value * value for value in values) / len(values))
    raise ValueError(f"unsupported descriptive aggregation: {operation}")


def _comparison(
    declaration: dict[str, Any],
    fields: list[str],
    aggregations: list[dict[str, str]],
    arm_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    minuend_id = declaration["minuend_arm_id"]
    subtrahend_id = declaration["subtrahend_arm_id"]
    minuend = arm_results[minuend_id]["terminal"]
    subtrahend = arm_results[subtrahend_id]["terminal"]
    if set(minuend) != set(subtrahend):
        raise ValueError(
            f"comparison {declaration['comparison_id']} lacks a full paired ID set"
        )
    per_id = [
        {
            "particle_id": particle_id,
            **{
                f"delta_{field}": float(minuend[particle_id][field])
                - float(subtrahend[particle_id][field])
                for field in fields
            },
        }
        for particle_id in sorted(minuend)
    ]
    return {
        "comparison_id": declaration["comparison_id"],
        "direction": f"{minuend_id}_minus_{subtrahend_id}",
        "reporting_mode": declaration["reporting_mode"],
        "paired_particle_count": len(per_id),
        "common_survivor_filtering": False,
        "per_particle_delta": per_id,
        "descriptive_delta": {
            aggregation["output_name"]: _aggregate(
                minuend, aggregation["field"], aggregation["operation"]
            )
            - _aggregate(
                subtrahend, aggregation["field"], aggregation["operation"]
            )
            for aggregation in aggregations
        },
    }


def analyze_four_arm_runs(
    contract_path: Path,
    bundle_metadata_path: Path,
    run_roots: dict[str, Path],
) -> dict[str, Any]:
    """Verify all four managed runs and return only paired descriptive deltas."""
    contract = _load(contract_path)
    metadata, detector_z = _validate_joint_contract(
        contract, bundle_metadata_path
    )
    arms = contract["arms"]
    arm_ids = [arm["arm_id"] for arm in arms]
    if set(run_roots) != set(arm_ids):
        raise ValueError("run-root arm IDs differ from the experiment contract")
    selectors = contract["source_selectors"]
    post_run = contract["comparison_contract"]["post_run_acceptance"]
    arm_results: dict[str, dict[str, Any]] = {}
    for arm in arms:
        selector = selectors[arm["source_selector"]]
        artifact = _bundle_artifact(metadata, selector)
        arm_results[arm["arm_id"]] = _verify_arm(
            arm,
            selector,
            artifact,
            metadata,
            run_roots[arm["arm_id"]],
            detector_z,
            post_run,
            contract["project_id"],
        )
    id_sets = [
        set(result["terminal"]) for result in arm_results.values()
    ]
    if any(ids != id_sets[0] for ids in id_sets[1:]):
        raise ValueError("four-arm full terminal ID sets differ")
    accelerated = contract["comparison_contract"]["accelerated_arm_invariants"]
    accelerated_arm_ids = accelerated["arm_ids"]
    if (
        not isinstance(accelerated_arm_ids, list)
        or len(accelerated_arm_ids) < 2
        or any(arm_id not in arm_results for arm_id in accelerated_arm_ids)
    ):
        raise ValueError("accelerated-arm invariant binding is invalid")
    required_resolved_fields = accelerated["resolved_fields_required_equal"]
    for arm_id in accelerated_arm_ids:
        drive = arm_results[arm_id]["resolved_axial_drive"]
        for field in required_resolved_fields:
            value = drive.get(field)
            if (
                field not in drive
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise ValueError(
                    f"accelerated arm {arm_id} lacks finite resolved field: {field}"
                )
    reference_drive = arm_results[accelerated_arm_ids[0]]["resolved_axial_drive"]
    for arm_id in accelerated_arm_ids[1:]:
        candidate_drive = arm_results[arm_id]["resolved_axial_drive"]
        for field in required_resolved_fields:
            if candidate_drive[field] != reference_drive[field]:
                raise ValueError(
                    f"accelerated-arm frozen resolved field differs: {field}"
                )
    public_arms = {
        arm_id: {
            key: value
            for key, value in result.items()
            if key not in {"terminal", "resolved_axial_drive"}
        }
        for arm_id, result in arm_results.items()
    }
    comparisons = [
        _comparison(
            declaration,
            post_run["comparison_fields"],
            post_run["descriptive_aggregations"],
            arm_results,
        )
        for declaration in post_run["comparisons"]
    ]
    c_vs_d = contract["comparison_contract"]["C_vs_D"]
    return {
        "schema_version": 1,
        "role": ROLE,
        "status": "PASS",
        "bundle_identity": {
            "metadata_sha256": file_sha256(bundle_metadata_path),
            "latent_sha256": metadata["latent_sha256"],
            "sample_family_sha256": metadata["sample_family_sha256"],
        },
        "acceptance_detector_z_mm": detector_z,
        "full_four_arm_id_set": "PASS",
        "loss_filtering": False,
        "common_survivor_filtering": False,
        "arms": public_arms,
        "comparisons": comparisons,
        "C_D_equivalence_claim_allowed": c_vs_d["equivalence_claim_allowed"],
        "C_D_equivalence_tolerance": c_vs_d["equivalence_tolerance"],
        "claim_limit": post_run["claim_limit"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--bundle-metadata", required=True, type=Path)
    parser.add_argument(
        "--run-root",
        action="append",
        required=True,
        metavar="ARM_ID=PATH",
        help="Managed run root for one contract arm; repeat once per arm.",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    run_roots: dict[str, Path] = {}
    for binding in args.run_root:
        arm_id, separator, value = binding.partition("=")
        if not separator or not arm_id or not value or arm_id in run_roots:
            raise ValueError(f"invalid or duplicate --run-root binding: {binding}")
        run_roots[arm_id] = Path(value)
    result = analyze_four_arm_runs(args.contract, args.bundle_metadata, run_roots)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
