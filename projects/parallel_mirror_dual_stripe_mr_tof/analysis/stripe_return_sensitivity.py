"""Plan and analyse a five-state Stripe return sensitivity diagnostic.

This module never launches SIMION.  The plan contains only calls to the
project's authoritative ``run_two_prism_trial.ps1`` flight runner.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from common.contracts.artifact_naming import validate_run_id
from common.contracts.verify_run_manifest import record_path, verify_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import parse_events
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import CandidateContractError


PROJECT = "parallel_mirror_dual_stripe_mr_tof"
CORRECT_HANDOFF_RESIDUALS = (
    "P1_P2_positive_mirror_turn_y_mm",
    "P1_P2_P2_shield_low_field_signed_vy_over_vz",
)
STATE_DELTAS = (
    ("baseline", 0.0, 0.0),
    ("s1_minus", -1.0, 0.0),
    ("s1_plus", 1.0, 0.0),
    ("s2_minus", 0.0, -1.0),
    ("s2_plus", 0.0, 1.0),
)
COHORTS = (("center_ion1", 1, 1), ("boundary_ions97_98", 97, 98))


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CandidateContractError(f"cannot read JSON: {path}") from error
    if not isinstance(value, dict):
        raise CandidateContractError(f"JSON root must be an object: {path}")
    return value


def _finite(value: object, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise CandidateContractError(f"{label} must be finite") from error
    if not math.isfinite(result):
        raise CandidateContractError(f"{label} must be finite")
    return result


def _verified_run_documents(
    manifest_path: Path,
) -> tuple[dict[str, Any], Path, dict[str, Any], Path, dict[str, Any]]:
    """Apply the public full-manifest record semantics and bind local documents."""
    manifest_path = manifest_path.resolve()
    manifest_root = manifest_path.parent
    manifest = _load(manifest_path)
    try:
        if manifest.get("schema_version", 1) not in {1, 2}:
            raise AssertionError("unsupported run manifest schema")
        verify_record("run_config", manifest["run_config"], base_dir=manifest_root)
        run_config_path = record_path(manifest["run_config"], base_dir=manifest_root)
        if run_config_path != (manifest_root / "run_config.json").resolve():
            raise AssertionError("run_config is not the local run_config.json")
        inputs = manifest.get("inputs")
        outputs = manifest.get("outputs")
        if not isinstance(inputs, dict) or not isinstance(outputs, list):
            raise AssertionError("manifest inputs/outputs have invalid types")
        for name, record in inputs.items():
            verify_record(f"input {name}", record, base_dir=manifest_root)
        for index, record in enumerate(outputs, 1):
            verify_record(f"output {index}", record, base_dir=manifest_root)
        summary_path = (manifest_root / "summary.json").resolve()
        summary_records = [
            record for record in outputs
            if record_path(record, base_dir=manifest_root) == summary_path
        ]
        if len(summary_records) != 1:
            raise AssertionError("summary.json is not a unique local manifest output")
    except (AssertionError, KeyError, TypeError, ValueError) as error:
        raise CandidateContractError(
            f"run manifest record verification failed: {manifest_path}: {error}"
        ) from error
    return manifest, run_config_path, _load(run_config_path), summary_path, _load(summary_path)


def _run(path: Path, label: str) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
    root = path.resolve()
    manifest, _config_path, config, _summary_path, summary = _verified_run_documents(
        root / "run_manifest.json"
    )
    if manifest.get("project") != PROJECT or manifest.get("status") != "success":
        raise CandidateContractError(f"{label} is not a successful {PROJECT} run")
    if config.get("project") != PROJECT or config.get("run_id") != manifest.get("run_id"):
        raise CandidateContractError(f"{label} run identity is inconsistent")
    if summary.get("status") != "success":
        raise CandidateContractError(f"{label} summary is not successful")
    return root, manifest, config, summary


def _manifest_parent(path: object, label: str) -> str:
    manifest = Path(str(path)).resolve()
    if manifest.name != "run_manifest.json" or not manifest.is_file():
        raise CandidateContractError(f"{label} manifest path is invalid")
    return str(manifest.parent)


def _same_parent_inputs(reference: dict[str, Any], other: dict[str, Any], label: str) -> None:
    keys = (
        "geometry_run_manifest", "mirror_run_manifest", "stripe_run_manifest",
        "accelerator_run_manifest", "local_workbench_run_manifest",
        "bunch_source_run_manifest",
    )
    for key in keys:
        if reference.get(key) != other.get(key):
            raise CandidateContractError(f"{label} changes frozen input {key}")


def _source_receipt_from_manifest(path: object) -> Path:
    manifest_path = Path(str(path)).resolve()
    manifest, _config_path, config, _summary_path, summary = _verified_run_documents(
        manifest_path
    )
    if manifest.get("project") != PROJECT or manifest.get("status") != "success":
        raise CandidateContractError(
            "frozen source manifest is not a successful project run"
        )
    if config.get("project") != PROJECT or config.get("run_id") != manifest.get("run_id"):
        raise CandidateContractError("frozen source run identity is inconsistent")
    if summary.get("status") != "success":
        raise CandidateContractError("frozen source summary is not successful")
    matches = [
        record_path(record, base_dir=manifest_path.parent)
        for record in manifest.get("outputs", [])
        if record_path(record, base_dir=manifest_path.parent).name
        == "bunch_source_receipt.json"
    ]
    if len(matches) != 1 or not matches[0].is_file():
        raise CandidateContractError("frozen source manifest must publish one bunch_source_receipt.json")
    return matches[0]


def build_plan(definition_path: Path, runner_path: Path) -> dict[str, Any]:
    definition = _load(definition_path)
    if definition.get("schema_version") != 1 or definition.get("role") != "mrtof_stripe_return_sensitivity_definition":
        raise CandidateContractError("Stripe sensitivity definition identity is invalid")
    delta = _finite(definition.get("delta_voltage_v"), "delta_voltage_v")
    if delta <= 0.0:
        raise CandidateContractError("delta_voltage_v must be explicitly positive")
    prefix = definition.get("member_run_id_prefix")
    if not isinstance(prefix, str) or not prefix.strip() or prefix != prefix.strip():
        raise CandidateContractError("member_run_id_prefix must be a nonempty trimmed string")
    refs = definition.get("baseline_runs")
    if not isinstance(refs, dict) or set(refs) != {"r26", "r27", "r28", "r29"}:
        raise CandidateContractError("definition must bind exactly r26/r27/r28/r29 baseline runs")
    r26 = _run(Path(refs["r26"]), "r26")
    r27 = _run(Path(refs["r27"]), "r27")
    r28 = _run(Path(refs["r28"]), "r28")
    r29 = _run(Path(refs["r29"]), "r29")
    for item, label in ((r26, "r26"), (r27, "r27"), (r28, "r28"), (r29, "r29")):
        if item[2].get("mode") != "finite_3d_two_prism_voltage_trial":
            raise CandidateContractError(f"{label} is not a two-prism flight")
    r26_residuals = r26[3].get("residuals")
    if not isinstance(r26_residuals, dict) or not set(CORRECT_HANDOFF_RESIDUALS) <= set(r26_residuals):
        raise CandidateContractError("r26 does not establish the correct P1/P2 handoff residual system")
    c27 = r27[2]
    p27 = c27.get("parameters", {})
    if p27.get("flight_scope") != "complete_three_dimensional_static_return" or p27.get("accelerator_pulse", {}).get("mode") != "static":
        raise CandidateContractError("r27 must be the static natural-return baseline")
    trial27 = _load(r27[0] / "results" / "two_prism_trial_materialization.json")
    if _finite(trial27.get("target_drift_period_ratio"), "r27 target K") != 25.5:
        raise CandidateContractError("r27 must bind K=25.5")
    inputs27 = c27.get("inputs", {})
    if not isinstance(inputs27, dict):
        raise CandidateContractError("r27 has no frozen input map")
    for item, label in ((r28, "r28"), (r29, "r29")):
        _same_parent_inputs(inputs27, item[2].get("inputs", {}), label)
        params = item[2].get("parameters", {})
        selection = params.get("source_selection", {})
        if (params.get("accelerator_pulse", {}).get("mode") != "static"
                or selection.get("particle_id_min") != 97 or selection.get("particle_id_max") != 98):
            raise CandidateContractError(f"{label} is not the frozen static ions97-98 boundary replay")
    prism = p27.get("prism_1_voltage_v"), p27.get("prism_2_voltage_v")
    stripes = p27.get("stripe_biases_v")
    if not isinstance(stripes, list) or len(stripes) != 2:
        raise CandidateContractError("r27 lacks two Stripe biases")
    p1, p2 = (_finite(prism[0], "P1"), _finite(prism[1], "P2"))
    s1, s2 = (_finite(stripes[0], "S1"), _finite(stripes[1], "S2"))
    source_receipt = _source_receipt_from_manifest(inputs27.get("bunch_source_run_manifest"))
    runner = runner_path.resolve()
    if runner.name != "run_two_prism_trial.ps1" or not runner.is_file():
        raise CandidateContractError("plan must call the authoritative run_two_prism_trial.ps1")
    common = [
        "pwsh", "-NoProfile", "-File", str(runner),
        "-GeometryReviewRunPath", _manifest_parent(inputs27.get("geometry_run_manifest"), "geometry"),
        "-MirrorRunPath", _manifest_parent(inputs27.get("mirror_run_manifest"), "mirror"),
        "-StripeRunPath", _manifest_parent(inputs27.get("stripe_run_manifest"), "Stripe"),
        "-AcceleratorRunPath", _manifest_parent(inputs27.get("accelerator_run_manifest"), "accelerator"),
        "-LocalWorkbenchRunPath", _manifest_parent(inputs27.get("local_workbench_run_manifest"), "local workbench"),
        "-BunchSourceReceiptPath", str(source_receipt),
        "-Prism1VoltageV", repr(p1), "-Prism2VoltageV", repr(p2),
        "-TrajectoryProfileId", str(p27.get("trajectory_profile", {}).get("profile_id")),
    ]
    tasks: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    for state, ds1, ds2 in STATE_DELTAS:
        values = [s1 + ds1 * delta, s2 + ds2 * delta]
        states.append({"state": state, "stripe_biases_v": values, "delta_multipliers": [ds1, ds2]})
        if state == "baseline":
            continue
        for cohort, first, last in COHORTS:
            state_token = state.replace("_", "-")
            cohort_token = cohort.replace("_", "-")
            run_id = f"{prefix}-{state_token}-{cohort_token}"
            try:
                validate_run_id(run_id)
            except ValueError as error:
                raise CandidateContractError(
                    f"generated member run ID is invalid: {run_id}: {error}"
                ) from error
            argv = common + [
                "-Stripe1VoltageV", repr(values[0]), "-Stripe2VoltageV", repr(values[1]),
                "-BunchParticleIdMin", str(first), "-BunchParticleIdMax", str(last),
                "-RunId", run_id,
            ]
            tasks.append({
                "state": state, "cohort": cohort, "particle_ids": list(range(first, last + 1)),
                "run_id": run_id, "stripe_biases_v": values, "argv": argv,
            })
    return {
        "schema_version": 1,
        "role": "mrtof_stripe_return_sensitivity_plan",
        "status": "commands_generated__simion_not_started",
        "qualification": "diagnostic_only__delta_is_not_a_theory_operating_point",
        "delta_voltage_v": delta,
        "baseline_runs": {key: str(Path(value).resolve()) for key, value in refs.items()},
        "frozen": {
            "target_drift_period_ratio": 25.5,
            "prism_voltages_v": [p1, p2], "stripe_baseline_v": [s1, s2],
            "geometry_run_manifest": inputs27["geometry_run_manifest"],
            "mirror_run_manifest": inputs27["mirror_run_manifest"],
            "stripe_run_manifest": inputs27["stripe_run_manifest"],
            "accelerator_run_manifest": inputs27["accelerator_run_manifest"],
            "local_workbench_run_manifest": inputs27["local_workbench_run_manifest"],
            "bunch_source_run_manifest": inputs27["bunch_source_run_manifest"],
            "accelerator_pulse_mode": "static",
            "p1_p2_residual_names": list(CORRECT_HANDOFF_RESIDUALS),
        },
        "states": states,
        "baseline_observations": [
            {
                "state": "baseline", "cohort": cohort,
                "particle_ids": list(range(first, last + 1)),
                "source_run_id": r27[1]["run_id"], "source_run_path": str(r27[0]),
            }
            for cohort, first, last in COHORTS
        ],
        "tasks": tasks,
        "execution_policy": "commands_only__caller_controls_resource_admission",
    }


def _events_for_ion(events: list[dict[str, Any]], ion: int) -> list[dict[str, Any]]:
    return [event for event in events if int(event["ion"]) == ion]


def _one(events: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    matches = [event for event in events if event["kind"] == kind]
    if len(matches) != 1:
        raise CandidateContractError(f"particle must have exactly one {kind} event")
    return matches[0]


def _particle_metrics(events: list[dict[str, Any]], trial: dict[str, Any], lip_y: float, lip_z: float) -> dict[str, Any]:
    reference = _one(events, "p2_low_field_reference")
    turn = _one(events, "pre_origin_positive_mirror_turn")
    phase = _one(events, "drift_phase_origin")
    target = _one(events, "target_k_phase_sample")
    terminal = _one(events, "terminal")
    slow = [event for event in events if event["kind"] == "slow_turn" and event["t_us"] > phase["t_us"]]
    if not slow:
        raise CandidateContractError("particle lacks a post-origin slow turn")
    ratio = reference["vy_mm_us"] / reference["vz_mm_us"]
    target_ratio = _finite(trial.get("target_low_field_tangent_ratio_vy_over_vz"), "target tangent ratio")
    post_target = [event for event in events if event["t_us"] > target["t_us"]]
    crossings = [
        event for event in post_target
        if event["kind"] == "patch_interface"
        and event.get("name") == "mirror_turn_negative__z_max"
        and event.get("direction") == 1
        and abs(event["z_mm"] - lip_z) <= 1e-3
    ]
    collision_at_lip = terminal["splat"] == -1 and abs(terminal["z_mm"] - lip_z) <= 1e-3
    lip_event = terminal if collision_at_lip else (crossings[0] if crossings else None)
    return {
        "positive_mirror_turn_y_residual_mm": turn["y_mm"] - trial["target_positive_mirror_turn_y_mm"],
        "p2_low_field_tangent_ratio_residual": ratio - target_ratio,
        "target_k_phase_y_mm": target["y_mm"],
        "target_k": target["k"],
        "slow_turn_y_minus_L_mm": slow[0]["y_mm"] - trial["target_slow_turn_y_mm"],
        "return_p2_lip_y_mm": None if lip_event is None else lip_event["y_mm"],
        "return_p2_lip_margin_mm": None if lip_event is None else lip_y - lip_event["y_mm"],
        "terminal_splat": int(terminal["splat"]),
        "classification": "detector" if terminal["splat"] == 1 else "electrode_collision" if terminal["splat"] == -1 else "other",
    }


def _shield_lip_coordinates(shield: dict[str, Any]) -> tuple[float, float]:
    aperture_y = shield.get("cross_aperture", {}).get("y_mm")
    polygon = shield.get("outer_polygon_yz_mm")
    if not isinstance(aperture_y, list) or len(aperture_y) < 2:
        raise CandidateContractError("electrode-20 shield must define its y aperture")
    if (
        not isinstance(polygon, list)
        or len(polygon) < 3
        or any(not isinstance(point, list) or len(point) != 2 for point in polygon)
    ):
        raise CandidateContractError("electrode-20 shield must define a two-dimensional yz polygon")
    lip_y = max(_finite(value, "electrode-20 shield aperture y") for value in aperture_y)
    lip_z = min(_finite(point[1], "electrode-20 shield polygon z") for point in polygon)
    return lip_y, lip_z


def analyze_plan(plan_path: Path, output_path: Path) -> dict[str, Any]:
    plan = _load(plan_path)
    if plan.get("role") != "mrtof_stripe_return_sensitivity_plan" or len(plan.get("tasks", [])) != 8:
        raise CandidateContractError("input is not one complete baseline-plus-eight-perturbation plan")
    geometry_run = Path(plan["baseline_runs"]["r27"])
    baseline_observations = plan.get("baseline_observations")
    expected_baseline = [
        ("center_ion1", [1]), ("boundary_ions97_98", [97, 98]),
    ]
    if (
        not isinstance(baseline_observations, list)
        or len(baseline_observations) != 2
        or any(
            item.get("state") != "baseline"
            or item.get("cohort") != cohort
            or item.get("particle_ids") != particle_ids
            or Path(item.get("source_run_path", "")).resolve() != geometry_run.resolve()
            for item, (cohort, particle_ids) in zip(
                baseline_observations, expected_baseline, strict=True
            )
        )
    ):
        raise CandidateContractError("baseline observations must bind ion1/97/98 directly to r27")
    r27_config = _load(geometry_run / "run_config.json")
    contract_manifest = Path(r27_config["inputs"]["geometry_run_manifest"])
    contract_run = contract_manifest.parent
    contract = _load(contract_run / "simion" / "simion_prototype_contract.json")
    shield = [item for item in contract["prisms"]["ground_shields"] if item.get("id") == 20]
    if len(shield) != 1:
        raise CandidateContractError("geometry must contain exactly one electrode-20 grounded shield")
    lip_y, lip_z = _shield_lip_coordinates(shield[0])
    rows: dict[str, dict[str, Any]] = {"baseline": {}}
    baseline_root, _baseline_manifest, _baseline_config, _baseline_summary = _run(
        geometry_run, "r27 baseline"
    )
    baseline_trial = _load(baseline_root / "results" / "two_prism_trial_materialization.json")
    baseline_events = parse_events(
        (baseline_root / "logs" / "native_two_prism_flight.log").read_text(encoding="utf-8")
    )
    for ion in (1, 97, 98):
        rows["baseline"][str(ion)] = _particle_metrics(
            _events_for_ion(baseline_events, ion), baseline_trial, lip_y, float(lip_z)
        )
    for task in plan["tasks"]:
        run_path = geometry_run.parent / task["run_id"]
        _root, _manifest, config, _summary = _run(run_path, task["run_id"])
        params = config.get("parameters", {})
        if (params.get("prism_1_voltage_v") != plan["frozen"]["prism_voltages_v"][0]
                or params.get("prism_2_voltage_v") != plan["frozen"]["prism_voltages_v"][1]
                or params.get("stripe_biases_v") != task["stripe_biases_v"]
                or params.get("accelerator_pulse", {}).get("mode") != "static"):
            raise CandidateContractError("member changes a frozen voltage-state or pulse identity")
        inputs = config.get("inputs", {})
        for key in (
            "geometry_run_manifest", "mirror_run_manifest", "stripe_run_manifest", "accelerator_run_manifest",
            "local_workbench_run_manifest", "bunch_source_run_manifest",
        ):
            if inputs.get(key) != plan["frozen"][key]:
                raise CandidateContractError(f"member changes frozen input {key}")
        selection = params.get("source_selection", {})
        if (selection.get("particle_id_min") != task["particle_ids"][0]
                or selection.get("particle_id_max") != task["particle_ids"][-1]):
            raise CandidateContractError("member source selection differs from its planned cohort")
        trial = _load(run_path / "results" / "two_prism_trial_materialization.json")
        if _finite(trial.get("target_drift_period_ratio"), "member target K") != 25.5:
            raise CandidateContractError("member changes the frozen K=25.5 phase target")
        events = parse_events((run_path / "logs" / "native_two_prism_flight.log").read_text(encoding="utf-8"))
        for ion in task["particle_ids"]:
            rows.setdefault(task["state"], {})[str(ion)] = _particle_metrics(
                _events_for_ion(events, ion), trial, lip_y, float(lip_z)
            )
    delta = _finite(plan["delta_voltage_v"], "plan delta")
    metric_names = (
        "positive_mirror_turn_y_residual_mm", "p2_low_field_tangent_ratio_residual",
        "target_k_phase_y_mm", "slow_turn_y_minus_L_mm", "return_p2_lip_margin_mm",
    )
    derivatives: dict[str, Any] = {}
    for ion in (1, 97, 98):
        derivatives[str(ion)] = {}
        for metric in metric_names:
            if rows["s1_minus"][str(ion)][metric] is None or rows["s1_plus"][str(ion)][metric] is None:
                d1 = None
            else:
                d1 = (rows["s1_plus"][str(ion)][metric] - rows["s1_minus"][str(ion)][metric]) / (2 * delta)
            if rows["s2_minus"][str(ion)][metric] is None or rows["s2_plus"][str(ion)][metric] is None:
                d2 = None
            else:
                d2 = (rows["s2_plus"][str(ion)][metric] - rows["s2_minus"][str(ion)][metric]) / (2 * delta)
            derivatives[str(ion)][metric] = [d1, d2]
    boundary = [derivatives[str(ion)]["return_p2_lip_margin_mm"] for ion in (97, 98)]
    if any(any(value is None for value in vector) for vector in boundary):
        direction = None
    else:
        gradient = np.mean(np.asarray(boundary, dtype=float), axis=0)
        norm = float(np.linalg.norm(gradient))
        direction = None if norm == 0.0 else (gradient / norm).tolist()
    assessment = {
        "status": "sampled_derivatives_reported__no_acceptance_threshold",
        "sampled_boundary_unit_direction_dS1_dS2": direction,
        "sampled_particle_ids": [97, 98],
        "full_bunch_predictive_qualification": "not_evaluated__extrapolation_prohibited",
        "entry_preservation_qualification": "not_classified_without_user_acceptance_threshold",
    }
    if direction is not None:
        assessment["predicted_per_volt"] = {
            "ion1_entry_residual_changes": [
                float(np.dot(derivatives["1"][name], direction))
                for name in metric_names[:2]
            ],
            "boundary_lip_margin_changes_mm": [float(np.dot(vector, direction)) for vector in boundary],
        }
    result = {
        "schema_version": 1, "role": "mrtof_stripe_return_sensitivity_analysis",
        "status": "complete", "qualification": "diagnostic_only__not_an_operating_point",
        "lip_geometry": {"electrode_id": 20, "plane_z_mm": lip_z, "opening_upper_y_mm": lip_y},
        "states": rows, "central_difference_derivatives_per_v": derivatives,
        "linear_direction_assessment": assessment,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--definition", required=True, type=Path)
    plan.add_argument("--runner", required=True, type=Path)
    plan.add_argument("--output", required=True, type=Path)
    analyse = sub.add_parser("analyze")
    analyse.add_argument("--plan", required=True, type=Path)
    analyse.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = build_plan(args.definition, args.runner) if args.command == "plan" else analyze_plan(args.plan, args.output)
    if args.command == "plan":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"MRTOF_STRIPE_RETURN_SENSITIVITY={result['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
