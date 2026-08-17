"""Compare transverse-collapsed and full-observed-6D source states."""

from __future__ import annotations

import argparse
import copy
import csv
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from common.contracts.artifact_naming import validate_run_id
from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.compare_single_flight_apertures import (
    _event_maps,
    _pair_event,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.run_publication import (
    freeze_repository_inputs,
    load_json,
    portable_path,
    publish_manifest,
    record_for_path,
    verified_record,
    write_pending_json,
)


INTEGRATION_ID = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
MODE = "observed_transverse_sensitivity_comparison"
ARM_C = "observed_z_vz_energy_transverse_collapsed"
ARM_D = "full_observed_6d"
EXPECTED_IDS = set(range(1, 101))


def _record_path(record: Any, label: str) -> Path:
    value = verified_record(label, record)
    return Path(str(value["path"])).resolve()


def _named_record(records: Any, name: str, label: str) -> Path:
    iterable = records.values() if isinstance(records, dict) else records
    matches = [
        record
        for record in iterable or []
        if isinstance(record, dict) and Path(str(record.get("path", ""))).name == name
    ]
    if len(matches) != 1:
        raise ContractError(f"{label} {name} is not bound exactly once")
    return _record_path(matches[0], f"{label} {name}")


def _load_arm(runs_root: Path, parent_run_id: str, expected_arm: str) -> dict[str, Any]:
    validate_run_id(parent_run_id)
    parent = (runs_root / parent_run_id).resolve()
    manifest_path = parent / "run_manifest.json"
    manifest = load_json(manifest_path, "parent manifest")
    if (
        manifest.get("role") != "simulation_run_manifest"
        or manifest.get("status") != "success"
        or manifest.get("run_id") != parent_run_id
        or manifest.get("project") != INTEGRATION_ID
        or manifest.get("mode") != "multipole_family_source_closure"
    ):
        raise ContractError("parent manifest identity differs")
    config_path = _record_path(manifest.get("run_config"), "parent run_config")
    config = load_json(config_path, "parent run_config")
    identity = config.get("source_particle_identity", {})
    projection = identity.get("observed_pre_pulse_projection", {})
    if (
        config.get("particle_count") != 100
        or config.get("formal_gate_passed") is not False
        or projection.get("arm_id") != expected_arm
    ):
        raise ContractError("parent observed arm identity differs")
    child_manifest_path = Path(str(config.get("inputs", {}).get("single_flight_transport_manifest", "")))
    if not child_manifest_path.is_absolute():
        child_manifest_path = (Path(str(config["project_root"])) / child_manifest_path).resolve()
    parent_child_record = record_for_path(manifest.get("inputs"), child_manifest_path, "parent child manifest")
    child_manifest = load_json(child_manifest_path, "child manifest")
    if (
        parent_child_record.get("sha256") != verified_record("parent child manifest", parent_child_record).get("sha256")
        or child_manifest.get("role") != "simulation_run_manifest"
        or child_manifest.get("status") != "success"
        or child_manifest.get("formal_eligible") is not False
    ):
        raise ContractError("child manifest identity differs")
    child_config_path = _record_path(child_manifest.get("run_config"), "child run_config")
    child_config = load_json(child_config_path, "child run_config")
    if (
        child_config.get("project") != INTEGRATION_ID
        or child_config.get("upstream_source_identity") != identity
        or child_config.get("formal_gate_passed") is not False
    ):
        raise ContractError("child source identity differs from parent")
    checkpoints = _named_record(child_manifest.get("outputs"), "single_flight_particle_checkpoints.csv", "child output")
    summary = _named_record(child_manifest.get("outputs"), "summary.json", "child output")
    projection_receipt = parent / "inputs" / "observed_pre_pulse_projection_receipt.json"
    if not projection_receipt.is_file():
        raise ContractError("parent projection receipt is missing")
    return {
        "parent_manifest": manifest_path,
        "parent_config": config_path,
        "child_manifest": child_manifest_path,
        "child_config": child_config_path,
        "checkpoints": checkpoints,
        "summary": summary,
        "projection_receipt": projection_receipt,
        "source_identity": identity,
        "child_parameters": child_config.get("parameters"),
    }


def _paired_authority_gate(c: dict[str, Any], d: dict[str, Any]) -> None:
    left, right = copy.deepcopy(c["source_identity"]), copy.deepcopy(d["source_identity"])
    left["observed_pre_pulse_projection"].pop("arm_id")
    right["observed_pre_pulse_projection"].pop("arm_id")
    if left != right:
        raise ContractError("collapsed/full source authorities differ beyond arm_id")
    excluded = {
        "resolved_population_contract_sha256",
        "three_zone_solver_gate_id",
        "three_zone_n1_solver_authorization_receipt_sha256",
        "three_zone_n1_producer_parent_manifest_sha256",
        "three_zone_source_identity_sha256",
    }
    c_parameters = {key: value for key, value in c["child_parameters"].items() if key not in excluded}
    d_parameters = {key: value for key, value in d["child_parameters"].items() if key not in excluded}
    if c_parameters != d_parameters:
        raise ContractError("collapsed/full PA, geometry, or numerical identities differ")
    c_receipt = load_json(c["projection_receipt"], "C projection receipt")
    d_receipt = load_json(d["projection_receipt"], "D projection receipt")
    for key in (
        "manifest",
        "prepared_arms",
        "observed_state",
        "old_geometry",
        "current_target",
        "current_subset_receipt",
    ):
        if c_receipt["authorities"][key]["sha256"] != d_receipt["authorities"][key]["sha256"]:
            raise ContractError(f"collapsed/full projection {key} authority differs")
    if (
        c_receipt["projection"] != d_receipt["projection"]
        or c_receipt["invariants"] != d_receipt["invariants"]
        or any(c_receipt["arms"][arm]["sha256"] != d_receipt["arms"][arm]["sha256"] for arm in (ARM_C, ARM_D))
    ):
        raise ContractError("collapsed/full projection paired-state identity differs")


def compare_frames(
    c_frame: pd.DataFrame,
    d_frame: pd.DataFrame,
    c_peak: dict[str, Any],
    d_peak: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Compare strict detector cohorts, reusing the canonical event pairing helper."""
    c_detector = _event_maps(c_frame)["detector_crossing"]
    d_detector = _event_maps(d_frame)["detector_crossing"]
    if set(c_detector) != EXPECTED_IDS or set(d_detector) != EXPECTED_IDS:
        raise ContractError("collapsed/full detector particle IDs must each be exactly 1..100")
    metrics, residuals = _pair_event(c_detector, d_detector)
    rows: list[dict[str, Any]] = []
    for residual in residuals:
        row = {"particle_id": int(residual["particle_id"])}
        row["delta_time_full_minus_collapsed_ns"] = residual["delta_time_small_minus_wide_ns"]
        for axis in "xyz":
            row[f"delta_{axis}_full_minus_collapsed_mm"] = residual[f"delta_{axis}_mm"]
            raw_velocity = float(residual[f"delta_v{axis}_m_s"])
            row[f"delta_v{axis}_full_minus_collapsed_m_s"] = raw_velocity if math.isfinite(raw_velocity) else None
        row["position_delta_norm_mm"] = float(
            np.sqrt(sum(float(row[f"delta_{axis}_full_minus_collapsed_mm"]) ** 2 for axis in "xyz"))
        )
        velocity_components = [row[f"delta_v{axis}_full_minus_collapsed_m_s"] for axis in "xyz"]
        row["velocity_delta_norm_m_s"] = (
            float(np.sqrt(sum(float(value) ** 2 for value in velocity_components)))
            if all(value is not None for value in velocity_components)
            else None
        )
        rows.append(row)

    def distribution(field: str) -> dict[str, float | int | None]:
        values = np.asarray([float(row[field]) for row in rows if row[field] is not None])
        if values.size == 0:
            return {
                "available_count": 0,
                "mean": None,
                "sample_sigma": None,
                "rms": None,
                "max_abs": None,
            }
        return {
            "available_count": int(values.size),
            "mean": float(np.mean(values)),
            "sample_sigma": float(np.std(values, ddof=1)),
            "rms": float(np.sqrt(np.mean(values**2))),
            "max_abs": float(np.max(np.abs(values))),
        }

    paired = {field: distribution(field) for field in rows[0] if field != "particle_id"}
    peak_delta = {
        field: float(d_peak[field]) - float(c_peak[field])
        for field in ("mean_tof_us", "std_tof_ns", "direct_fwhm_tof_ns", "mass_resolution")
    }
    peak_delta["direct_fwhm_tof_pct"] = 100.0 * peak_delta["direct_fwhm_tof_ns"] / float(c_peak["direct_fwhm_tof_ns"])
    peak_delta["std_tof_pct"] = 100.0 * peak_delta["std_tof_ns"] / float(c_peak["std_tof_ns"])
    peak_delta["mass_resolution_pct"] = 100.0 * peak_delta["mass_resolution"] / float(c_peak["mass_resolution"])
    result = {
        "schema_version": 1,
        "role": "rf_oatof_observed_transverse_sensitivity_comparison",
        "status": "FUNCTIONAL_ONLY",
        "formal_gate_passed": False,
        "paired_particle_count": 100,
        "detector_identity": {
            "transverse_collapsed_particles": metrics["wide_particles"],
            "full_observed_6d_particles": metrics["small_particles"],
            "common_particles": metrics["common_particles"],
            "transverse_collapsed_only_particles": metrics["wide_only_particles"],
            "full_observed_6d_only_particles": metrics["small_only_particles"],
            "jaccard_identity": metrics["jaccard_identity"],
            "mean_delta_time_full_minus_collapsed_ns": metrics["mean_delta_time_small_minus_wide_ns"],
            "rms_delta_time_full_minus_collapsed_ns": metrics["rms_delta_time_ns"],
            "position_vector_rms_full_minus_collapsed_mm": metrics["position_vector_rms_mm"],
            "velocity_vector_rms_full_minus_collapsed_m_s": metrics["velocity_vector_rms_m_s"],
        },
        "paired_detector_deltas_full_minus_collapsed": paired,
        "peak_metrics": {
            "transverse_collapsed": c_peak,
            "full_observed_6d": d_peak,
            "full_minus_collapsed": peak_delta,
        },
        "thresholds": None,
        "qualification_decision_made": False,
    }
    return result, rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    pending = path.with_name(f".{path.name}.pending")
    pending.parent.mkdir(parents=True, exist_ok=True)
    with pending.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    os.replace(pending, path)


def publish(repo_root: Path, run_id: str, c_parent_id: str, d_parent_id: str) -> Path:
    validate_run_id(run_id)
    repo_root = repo_root.resolve()
    workspace = repo_root.parent
    runs_root = workspace / "artifacts" / "projects" / INTEGRATION_ID / "runs"
    run_dir = runs_root / run_id
    if run_dir.exists():
        raise ContractError(f"analysis run already exists: {run_dir}")
    c = _load_arm(runs_root, c_parent_id, ARM_C)
    d = _load_arm(runs_root, d_parent_id, ARM_D)
    _paired_authority_gate(c, d)
    inputs = {f"C_{key}": value for key, value in c.items() if isinstance(value, Path)}
    inputs.update({f"D_{key}": value for key, value in d.items() if isinstance(value, Path)})
    inputs["implementation"] = Path(__file__).resolve()
    run_dir.mkdir(parents=True)
    frozen = freeze_repository_inputs(inputs, repo_root=repo_root, run_dir=run_dir)
    config_path, summary_path = run_dir / "run_config.json", run_dir / "summary.json"
    result_path = run_dir / "results" / "observed_transverse_sensitivity.json"
    pairs_path = run_dir / "results" / "observed_transverse_detector_pairs.csv"
    manifest_path = run_dir / "run_manifest.json"
    config = {
        "schema_version": 2,
        "run_id": run_id,
        "project": INTEGRATION_ID,
        "mode": MODE,
        "project_root": str(workspace),
        "inputs": {key: portable_path(value, workspace) for key, value in frozen.items()},
        "parameters": {
            "transverse_collapsed_parent_run_id": c_parent_id,
            "full_observed_6d_parent_run_id": d_parent_id,
            "analysis_class": "FUNCTIONAL_ONLY",
            "particle_count": 100,
            "qualification_decision_made": False,
        },
        "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None},
        "formal_gate_passed": False,
    }
    write_pending_json(config_path, config)
    write_pending_json(
        summary_path,
        {
            "schema_version": 1,
            "role": "rf_oatof_observed_transverse_sensitivity_summary",
            "status": "interrupted",
            "analysis_status": "NOT_RUN",
            "formal_gate_passed": False,
        },
    )
    pending = manifest_path.with_name(".run_manifest.json.pending")
    publish_manifest(
        repo_root=repo_root,
        run_config=config_path,
        manifest_path=pending,
        status="interrupted",
        outputs=(summary_path,),
        project=INTEGRATION_ID,
        mode=MODE,
        label="observed-transverse-sensitivity",
    )
    os.replace(pending, manifest_path)
    c_summary = load_json(c["summary"], "C child summary")
    d_summary = load_json(d["summary"], "D child summary")
    result, rows = compare_frames(
        pd.read_csv(c["checkpoints"]),
        pd.read_csv(d["checkpoints"]),
        c_summary["pulse_effective_peak"],
        d_summary["pulse_effective_peak"],
    )
    write_pending_json(result_path, result)
    _write_csv(pairs_path, rows)
    summary = {
        "schema_version": 1,
        "role": "rf_oatof_observed_transverse_sensitivity_summary",
        "status": "success",
        "analysis_status": "FUNCTIONAL_ONLY",
        "paired_particle_count": 100,
        "result": portable_path(result_path, run_dir),
        "paired_detector_rows": portable_path(pairs_path, run_dir),
        "formal_gate_passed": False,
    }
    write_pending_json(summary_path, summary)
    publish_manifest(
        repo_root=repo_root,
        run_config=config_path,
        manifest_path=pending,
        status="success",
        outputs=(result_path, pairs_path, summary_path),
        project=INTEGRATION_ID,
        mode=MODE,
        label="observed-transverse-sensitivity",
    )
    os.replace(pending, manifest_path)
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--collapsed-parent-run-id", required=True)
    parser.add_argument("--full-parent-run-id", required=True)
    args = parser.parse_args()
    manifest = publish(
        repo_root=args.repo_root,
        run_id=args.run_id,
        c_parent_id=args.collapsed_parent_run_id,
        d_parent_id=args.full_parent_run_id,
    )
    print(f"OBSERVED_TRANSVERSE_SENSITIVITY=PASS MANIFEST={manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
