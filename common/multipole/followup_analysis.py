"""Analyze governed no-acceleration directional and solver follow-up evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable

from common.multipole.numerical_observables import (
    CANDIDATE_OBSERVABLE_FIELDS,
    PARTICLE_ENVELOPE_FIELDS,
    observable_differences,
    run_data,
    sha256_file,
)
from common.multipole.numerical_qualification import (
    evaluate,
    load_engineering_progression_contract,
)


FACTORIAL_ARMS = {
    "A": ((0.3, 0.3, 0.3), 80),
    "R": ((0.2, 0.2, 0.3), 80),
    "Z": ((0.3, 0.3, 0.2), 80),
    "I": ((0.2, 0.2, 0.2), 80),
    "T": ((0.2, 0.2, 0.2), 160),
}
ENGINEERING_AXES = {
    "spatial",
    "spatial_radial",
    "spatial_axial",
    "spatial_isotropic",
    "temporal",
    "cross_solver",
}
PLAN_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def load_resolution(path: Path) -> dict[str, Any]:
    contract = json.loads(path.read_text(encoding="utf-8-sig"))
    if contract.get("role") != "multipole_no_acceleration_followup_effect_resolution":
        raise ValueError("unexpected follow-up effect-resolution contract")
    bins = contract.get("fixed_bins")
    if not isinstance(bins, dict) or not bins:
        raise ValueError("effect-resolution contract has no fixed bins")
    for field, specification in bins.items():
        if set(specification) != {"minimum", "maximum", "count"}:
            raise ValueError(f"fixed-bin keys differ for {field}")
        low = float(specification["minimum"])
        high = float(specification["maximum"])
        count = int(specification["count"])
        if not math.isfinite(low) or not math.isfinite(high) or high <= low or count < 2:
            raise ValueError(f"invalid fixed-bin specification for {field}")
    return contract


def normalized_cell_xyz(numerics: dict[str, Any]) -> tuple[float, float, float]:
    if "cell_mm_xyz" in numerics:
        value = numerics["cell_mm_xyz"]
        if not isinstance(value, dict) or set(value) != {"x", "y", "z"}:
            raise ValueError("cell_mm_xyz must contain exactly x, y and z")
        return tuple(float(value[axis]) for axis in ("x", "y", "z"))
    if "cell_mm" in numerics:
        value = float(numerics["cell_mm"])
        return value, value, value
    raise ValueError("SIMION numerics contain no cell-size contract")


def fixed_bin_index(value: float, specification: dict[str, Any]) -> int:
    low = float(specification["minimum"])
    high = float(specification["maximum"])
    count = int(specification["count"])
    if not math.isfinite(value) or value < low or value > high:
        raise ValueError("value is outside the preregistered fixed-bin range")
    if value == high:
        return count - 1
    return min(count - 1, int((value - low) / (high - low) * count))


def engineering_bin_stability(
    left: dict[str, Any],
    right: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    fields = contract["engineering_stability"]["required_per_particle_bin_stability"]
    if left["source_particle_ids"] != right["source_particle_ids"]:
        return {"status": "FAIL_SOURCE_PARTICLE_ID_SET_CHANGED"}
    if left["handoff_particle_ids"] != right["handoff_particle_ids"]:
        return {"status": "FAIL_HANDOFF_PARTICLE_ID_SET_CHANGED"}
    changes: dict[str, list[int]] = {field: [] for field in fields}
    out_of_range: dict[str, list[int]] = {field: [] for field in fields}
    for particle_id in left["handoff_particle_ids"]:
        for field in fields:
            specification = contract["fixed_bins"][field]
            try:
                left_bin = fixed_bin_index(
                    float(left["_handoff"][particle_id][field]), specification
                )
                right_bin = fixed_bin_index(
                    float(right["_handoff"][particle_id][field]), specification
                )
            except ValueError:
                out_of_range[field].append(particle_id)
                continue
            if left_bin != right_bin:
                changes[field].append(particle_id)
    out_of_range = {field: ids for field, ids in out_of_range.items() if ids}
    changes = {field: ids for field, ids in changes.items() if ids}
    if out_of_range:
        status = contract["engineering_stability"]["out_of_range_result"]
    elif changes:
        status = contract["engineering_stability"]["changed_bin_result"]
    else:
        status = contract["engineering_stability"]["unchanged_bin_result"]
    return {
        "status": status,
        "changed_particle_ids_by_field": changes,
        "out_of_range_particle_ids_by_field": out_of_range,
    }


def paired_report(
    left: dict[str, Any],
    right: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    if left["project"] != right["project"]:
        raise ValueError("paired runs belong to different projects")
    if left["particle_source_sha256"] != right["particle_source_sha256"]:
        raise ValueError("paired runs use different particle sources")
    if (
        left["physical_resolved_design_sha256"]
        != right["physical_resolved_design_sha256"]
    ):
        raise ValueError("paired runs contain different physical resolved designs")
    return {
        "left_run_id": left["run_id"],
        "right_run_id": right["run_id"],
        "left_solver": left["solver"],
        "right_solver": right["solver"],
        "resolved_design_total_sha_exact_match": (
            left["resolved_design_sha256"] == right["resolved_design_sha256"]
        ),
        "physical_resolved_design_sha_exact_match": True,
        "differences": observable_differences(left, right),
        "engineering_resolution": engineering_bin_stability(left, right, contract),
    }


def _signed_interaction(a: float, r: float, z: float, i: float) -> float:
    return i - r - z + a


def factorial_interaction(runs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    summary = {
        field: _signed_interaction(
            float(runs["A"]["observables"][field]),
            float(runs["R"]["observables"][field]),
            float(runs["Z"]["observables"][field]),
            float(runs["I"]["observables"][field]),
        )
        for field in CANDIDATE_OBSERVABLE_FIELDS
    }
    common_ids = set(runs["A"]["handoff_particle_ids"])
    for arm in ("R", "Z", "I"):
        common_ids &= set(runs[arm]["handoff_particle_ids"])
    particle_rms: dict[str, float] = {}
    for field in PARTICLE_ENVELOPE_FIELDS:
        interactions = [
            _signed_interaction(
                float(runs["A"]["_handoff"][particle_id][field]),
                float(runs["R"]["_handoff"][particle_id][field]),
                float(runs["Z"]["_handoff"][particle_id][field]),
                float(runs["I"]["_handoff"][particle_id][field]),
            )
            for particle_id in sorted(common_ids)
        ]
        particle_rms[field] = math.sqrt(
            sum(value * value for value in interactions) / len(interactions)
        )
    return {
        "definition": "I - R - Z + A",
        "summary_observable_signed_interaction": summary,
        "paired_particle_interaction_rms": particle_rms,
    }


def analyze_factorial(
    manifests: dict[str, Path],
    resolution_path: Path,
) -> dict[str, Any]:
    contract = load_resolution(resolution_path)
    runs = {arm: run_data(path) for arm, path in manifests.items()}
    if set(runs) != set(FACTORIAL_ARMS):
        raise ValueError("factorial analysis requires exactly A, R, Z, I and T")
    project = runs["A"]["project"]
    for arm, (expected_cell, expected_steps) in FACTORIAL_ARMS.items():
        run = runs[arm]
        if run["project"] != project or run["solver"] != "SIMION":
            raise ValueError(f"{arm} is not the expected project SIMION run")
        actual_cell = normalized_cell_xyz(run["numerics"])
        actual_steps = int(run["numerics"]["trajectory"]["rf_steps_per_period"])
        if actual_cell != expected_cell or actual_steps != expected_steps:
            raise ValueError(f"{arm} numerics differ from the frozen factorial arm")
    comparisons = {
        "A_to_R_radial": paired_report(runs["A"], runs["R"], contract),
        "A_to_Z_axial": paired_report(runs["A"], runs["Z"], contract),
        "Z_to_I_radial": paired_report(runs["Z"], runs["I"], contract),
        "R_to_I_axial": paired_report(runs["R"], runs["I"], contract),
        "I_to_T_temporal": paired_report(runs["I"], runs["T"], contract),
    }
    return {
        "schema_version": 1,
        "role": "multipole_simion_anisotropic_factorial_analysis",
        "status": "DIAGNOSTIC_COMPLETE",
        "project_id": project,
        "arm_run_ids": {arm: runs[arm]["run_id"] for arm in FACTORIAL_ARMS},
        "comparisons": comparisons,
        "factorial_interaction": factorial_interaction(runs),
        "scientific_claim": (
            "Numerical direction sensitivity only; absolute physical accuracy and "
            "solver superiority are not qualified."
        ),
    }


def analyze_triangle(
    legacy_manifest: Path,
    hybrid_manifest: Path,
    simion_manifest: Path,
    resolution_path: Path,
) -> dict[str, Any]:
    contract = load_resolution(resolution_path)
    legacy = run_data(legacy_manifest)
    hybrid = run_data(hybrid_manifest)
    simion = run_data(simion_manifest)
    if legacy["solver"] != "COMSOL" or hybrid["solver"] != "COMSOL":
        raise ValueError("triangle COMSOL arms are mislabeled")
    if simion["solver"] != "SIMION":
        raise ValueError("triangle SIMION arm is mislabeled")
    pairs = {
        "legacy_comsol_to_hybrid_comsol": paired_report(legacy, hybrid, contract),
        "legacy_comsol_to_simion": paired_report(legacy, simion, contract),
        "hybrid_comsol_to_simion": paired_report(hybrid, simion, contract),
    }
    movement = {}
    for field in CANDIDATE_OBSERVABLE_FIELDS:
        legacy_distance = abs(
            float(legacy["observables"][field]) - float(simion["observables"][field])
        )
        hybrid_distance = abs(
            float(hybrid["observables"][field]) - float(simion["observables"][field])
        )
        movement[field] = {
            "legacy_comsol_absolute_distance_to_simion": legacy_distance,
            "hybrid_comsol_absolute_distance_to_simion": hybrid_distance,
            "hybrid_moves_toward_simion": hybrid_distance < legacy_distance,
        }
    return {
        "schema_version": 1,
        "role": "multipole_no_acceleration_solver_triangle_analysis",
        "status": "POSTHOC_DIAGNOSTIC_COMPLETE",
        "project_id": legacy["project"],
        "pairs": pairs,
        "movement_relative_to_simion": movement,
        "provenance_class": (
            "strict_total_sha"
            if len(
                {
                    legacy["resolved_design_sha256"],
                    hybrid["resolved_design_sha256"],
                    simion["resolved_design_sha256"],
                }
            )
            == 1
            else "authority_revision_physical_payload_match"
        ),
        "scientific_claim": (
            "Movement toward or away from SIMION is diagnostic and does not prove "
            "that either discretization is more accurate."
        ),
    }


def analyze_pair(
    left_manifest: Path,
    right_manifest: Path,
    resolution_path: Path,
    comparison_id: str,
) -> dict[str, Any]:
    if not comparison_id.strip():
        raise ValueError("comparison_id must not be empty")
    contract = load_resolution(resolution_path)
    left = run_data(left_manifest)
    right = run_data(right_manifest)
    comparison = paired_report(left, right, contract)
    return {
        "schema_version": 1,
        "role": "multipole_no_acceleration_paired_followup_analysis",
        "status": "DIAGNOSTIC_COMPLETE",
        "comparison_id": comparison_id,
        "project_id": left["project"],
        "comparison": comparison,
        "scientific_claim": (
            "Paired engineering sensitivity at the preregistered fixed-bin "
            "resolution only; absolute physical accuracy and solver superiority "
            "are not qualified."
        ),
    }


def _strict_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} keys differ")


def _plan_relative_file(plan_root: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} path must be a nonempty string")
    relative = Path(value)
    if relative.is_absolute():
        raise ValueError(f"{label} path must be relative to the plan")
    resolved = (plan_root / relative).resolve()
    try:
        resolved.relative_to(plan_root)
    except ValueError as exc:
        raise ValueError(f"{label} path escapes the plan directory") from exc
    if not resolved.is_file():
        raise ValueError(f"{label} file does not exist")
    return resolved


def _load_engineering_batch_plan(
    plan_path: Path,
) -> tuple[dict[str, Path], list[dict[str, str]], str]:
    plan_path = plan_path.resolve()
    payload = plan_path.read_bytes()
    plan_sha256 = hashlib.sha256(payload).hexdigest().upper()
    document = json.loads(payload.decode("utf-8-sig"))
    if not isinstance(document, dict):
        raise ValueError("engineering batch plan must be an object")
    _strict_keys(
        document,
        {"schema_version", "role", "runs", "comparisons"},
        "engineering batch plan",
    )
    if (
        type(document["schema_version"]) is not int
        or document["schema_version"] != 1
        or document["role"] != "multipole_engineering_reanalysis_plan"
    ):
        raise ValueError("engineering batch plan identity differs")
    run_specs = document["runs"]
    comparisons = document["comparisons"]
    if not isinstance(run_specs, dict) or not run_specs:
        raise ValueError("engineering batch plan has no runs")
    if not isinstance(comparisons, list) or not comparisons:
        raise ValueError("engineering batch plan has no comparisons")

    run_paths: dict[str, Path] = {}
    for key, specification in run_specs.items():
        if not isinstance(key, str) or not PLAN_IDENTIFIER.fullmatch(key):
            raise ValueError("engineering batch run key is invalid")
        if not isinstance(specification, dict):
            raise ValueError(f"engineering batch run {key} must be an object")
        _strict_keys(specification, {"manifest"}, f"engineering batch run {key}")
        run_paths[key] = _plan_relative_file(
            plan_path.parent, specification["manifest"], f"run {key} manifest"
        )
    if len(set(run_paths.values())) != len(run_paths):
        raise ValueError("engineering batch run manifests must be unique")

    validated: list[dict[str, str]] = []
    comparison_ids: set[str] = set()
    comparison_keys: set[tuple[str, str, str]] = set()
    used_runs: set[str] = set()
    for index, comparison in enumerate(comparisons):
        if not isinstance(comparison, dict):
            raise ValueError(f"engineering comparison {index} must be an object")
        _strict_keys(
            comparison,
            {"comparison_id", "baseline", "peer", "axis"},
            f"engineering comparison {index}",
        )
        comparison_id = comparison["comparison_id"]
        baseline = comparison["baseline"]
        peer = comparison["peer"]
        axis = comparison["axis"]
        if (
            not isinstance(comparison_id, str)
            or not PLAN_IDENTIFIER.fullmatch(comparison_id)
            or comparison_id in comparison_ids
        ):
            raise ValueError("engineering comparison_id is invalid or duplicated")
        if (
            not isinstance(baseline, str)
            or not PLAN_IDENTIFIER.fullmatch(baseline)
            or not isinstance(peer, str)
            or not PLAN_IDENTIFIER.fullmatch(peer)
        ):
            raise ValueError("engineering comparison run reference is invalid")
        if baseline not in run_paths or peer not in run_paths or baseline == peer:
            raise ValueError("engineering comparison run reference is invalid")
        if not isinstance(axis, str) or axis not in ENGINEERING_AXES:
            raise ValueError("engineering comparison axis is unsupported")
        comparison_key = (baseline, peer, axis)
        if comparison_key in comparison_keys:
            raise ValueError("engineering comparison pair is duplicated")
        comparison_ids.add(comparison_id)
        comparison_keys.add(comparison_key)
        used_runs.update((baseline, peer))
        validated.append(
            {
                "comparison_id": comparison_id,
                "baseline": baseline,
                "peer": peer,
                "axis": axis,
            }
        )
    if used_runs != set(run_paths):
        raise ValueError("engineering batch plan contains unused runs")
    return run_paths, validated, plan_sha256


def load_engineering_batch_plan(
    plan_path: Path,
) -> tuple[dict[str, Path], list[dict[str, str]]]:
    run_paths, comparisons, _ = _load_engineering_batch_plan(plan_path)
    return run_paths, comparisons


def engineering_batch(
    plan_path: Path,
    policy_path: Path,
    functional_contract_path: Path,
    *,
    run_loader: Callable[[Path], dict[str, Any]] = run_data,
    evaluator: Callable[
        [dict[str, Any], dict[str, Any], str, dict[str, Any]],
        dict[str, Any],
    ] = evaluate,
) -> dict[str, Any]:
    run_paths, comparisons, plan_sha256 = _load_engineering_batch_plan(plan_path)
    contract, contract_provenance = load_engineering_progression_contract(
        policy_path, functional_contract_path
    )
    manifest_sha256 = {
        key: sha256_file(path) for key, path in run_paths.items()
    }
    runs = {key: run_loader(path) for key, path in run_paths.items()}
    if any(
        sha256_file(run_paths[key]) != digest
        for key, digest in manifest_sha256.items()
    ):
        raise ValueError("engineering batch run manifest changed during loading")
    if sha256_file(plan_path.resolve()) != plan_sha256:
        raise ValueError("engineering batch plan changed during analysis")
    required_provenance = ("run_id", "project", "solver")
    for key, run in runs.items():
        if not isinstance(run, dict) or any(
            not isinstance(run.get(field), str) or not run[field]
            for field in required_provenance
        ):
            raise ValueError(f"engineering batch run {key} provenance is invalid")
    run_ids = [run["run_id"] for run in runs.values()]
    if len(run_ids) != len(set(run_ids)):
        raise ValueError("engineering batch run IDs must be unique")

    results = []
    statuses = []
    for comparison in comparisons:
        result = evaluator(
            runs[comparison["baseline"]],
            runs[comparison["peer"]],
            comparison["axis"],
            contract,
        )
        status = result.get("engineering_progression_status")
        if (
            result.get("claim_profile") != "engineering_progression"
            or result.get("status") != status
            or status
            not in {"PASS", "FAIL", "NOT_EVALUATED_DO_NOT_PROGRESS"}
        ):
            raise ValueError("engineering evaluator returned an invalid result")
        statuses.append(status)
        results.append({**comparison, "result": result})

    if sha256_file(plan_path.resolve()) != plan_sha256:
        raise ValueError("engineering batch plan changed during analysis")
    if any(
        sha256_file(run_paths[key]) != digest
        for key, digest in manifest_sha256.items()
    ):
        raise ValueError("engineering batch run manifest changed during analysis")

    policy_status = contract["engineering_progression_policy"]["status"]
    if "FAIL" in statuses:
        decision_status = "FAIL"
    elif "NOT_EVALUATED_DO_NOT_PROGRESS" in statuses:
        decision_status = "NOT_EVALUATED_DO_NOT_PROGRESS"
    elif policy_status != "ACTIVE_ENGINEERING_PROGRESSION_POLICY":
        decision_status = "NOT_EVALUATED_DO_NOT_PROGRESS"
    elif statuses and all(status == "PASS" for status in statuses):
        decision_status = "PASS"
    else:
        raise ValueError("engineering batch decision cannot be aggregated")
    counts = {
        status: statuses.count(status)
        for status in ("PASS", "FAIL", "NOT_EVALUATED_DO_NOT_PROGRESS")
    }
    plan_path = plan_path.resolve()
    return {
        "schema_version": 1,
        "role": "multipole_engineering_reanalysis_batch",
        "execution_status": "ANALYSIS_COMPLETE",
        "decision_status": decision_status,
        "numerical_convergence_status": "DEFERRED_NOT_WAIVED",
        "plan": {
            "path": str(plan_path),
            "sha256": plan_sha256,
        },
        "contracts": contract_provenance,
        "runs": {
            key: {
                "manifest": {
                    "path": str(run_paths[key]),
                    "sha256": manifest_sha256[key],
                },
                "run_id": run["run_id"],
                "project": run["project"],
                "solver": run["solver"],
            }
            for key, run in runs.items()
        },
        "comparison_counts": counts,
        "comparisons": results,
        "claim_limit": contract["claim_limit"],
    }


def write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(
                json.dumps(document, indent=2, ensure_ascii=False) + "\n"
            )
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolution", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    factorial = subparsers.add_parser("factorial")
    for arm in FACTORIAL_ARMS:
        factorial.add_argument(f"--{arm.lower()}", required=True, type=Path)
    triangle = subparsers.add_parser("triangle")
    triangle.add_argument("--legacy-comsol", required=True, type=Path)
    triangle.add_argument("--hybrid-comsol", required=True, type=Path)
    triangle.add_argument("--simion", required=True, type=Path)
    pair = subparsers.add_parser("pair")
    pair.add_argument("--left", required=True, type=Path)
    pair.add_argument("--right", required=True, type=Path)
    pair.add_argument("--comparison-id", required=True)
    engineering = subparsers.add_parser("engineering-batch")
    engineering.add_argument("--plan", required=True, type=Path)
    engineering.add_argument("--engineering-policy", required=True, type=Path)
    engineering.add_argument("--functional-contract", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.command == "engineering-batch":
        document = engineering_batch(
            arguments.plan,
            arguments.engineering_policy,
            arguments.functional_contract,
        )
    elif arguments.resolution is None:
        parser.error("--resolution is required for diagnostic follow-up commands")
    elif arguments.command == "factorial":
        document = analyze_factorial(
            {
                arm: getattr(arguments, arm.lower())
                for arm in FACTORIAL_ARMS
            },
            arguments.resolution,
        )
    elif arguments.command == "triangle":
        document = analyze_triangle(
            arguments.legacy_comsol,
            arguments.hybrid_comsol,
            arguments.simion,
            arguments.resolution,
        )
    else:
        document = analyze_pair(
            arguments.left,
            arguments.right,
            arguments.resolution,
            arguments.comparison_id,
        )
    write_json(arguments.output, document)
    if arguments.command == "engineering-batch":
        print(
            "MULTIPOLE_ENGINEERING_REANALYSIS="
            f"{document['decision_status']} OUTPUT={arguments.output.resolve()}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
