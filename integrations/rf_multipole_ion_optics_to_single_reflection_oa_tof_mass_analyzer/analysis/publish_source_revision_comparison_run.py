"""Publish a compact diagnostic comparison of baseline and revised COMSOL sources."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from common.contracts.artifact_naming import validate_run_id
from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.paired_downstream_analysis import (
    BranchData,
    _load_branch,
    _paired,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.publish_paired_downstream_run import (
    INTEGRATION_ID,
    _load,
    _parent_run,
    _portable,
    _record_for_path,
    _terminal_branch,
    _verify_record,
    _write_pending_json,
)

OUTPUT_MODE = "multipole_family_source_revision_comparison_n100"
OUTPUT_ROLE = "rf_oatof_source_revision_comparison"
SUMMARY_ROLE = "integration_family_source_revision_comparison_summary"
REQUIRED_METRICS = (
    "rf_exit_count",
    "oatof_entry_count",
    "active_at_pulse_count",
    "local_accelerator_exit_count",
    "detector_crossing_count",
    "detector_hit_count",
    "common_local_exit_position_rms_mm",
    "common_local_exit_velocity_rms_m_per_s",
    "common_local_exit_time_rms_us",
    "common_local_exit_energy_rms_eV",
)
COUNT_FIELDS = {
    "rf_exit_count": "rf_exit",
    "oatof_entry_count": "oatof_entry",
    "active_at_pulse_count": "active_at_pulse",
    "local_accelerator_exit_count": "local_accelerator_exit",
    "detector_crossing_count": "detector_crossing",
    "detector_hit_count": "detector_hit",
}


def _publish_source_revision_manifest(
    *,
    repo_root: Path,
    run_config: Path,
    manifest_path: Path,
    outputs: Sequence[Path],
) -> None:
    command = [
        sys.executable,
        "-m",
        "common.contracts.write_run_manifest",
        "--run-config",
        str(run_config),
        "--manifest",
        str(manifest_path),
        "--status",
        "success",
        "--software",
        f"Python {sys.version_info.major}.{sys.version_info.minor}",
    ]
    for output in outputs:
        command.extend(("--output", str(output)))
    completed = subprocess.run(
        command,
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise ContractError(
            "source-revision manifest publication failed: "
            + (completed.stdout + completed.stderr).strip()
        )
    manifest = _load(manifest_path, "source-revision manifest")
    run_config_value = _load(run_config, "source-revision run_config")
    if (
        manifest.get("role") != "simulation_run_manifest"
        or manifest.get("status") != "success"
        or manifest.get("run_id") != run_config_value.get("run_id")
        or manifest.get("project") != INTEGRATION_ID
        or manifest.get("mode") != OUTPUT_MODE
        or manifest.get("formal_eligible") is not False
    ):
        raise ContractError("source-revision manifest identity differs")
    _verify_record("source-revision manifest run_config", manifest.get("run_config"))
    for output in outputs:
        _record_for_path(
            manifest.get("outputs"),
            output,
            f"source-revision output {output.name}",
        )
    verify = subprocess.run(
        [
            sys.executable,
            "-m",
            "common.contracts.verify_run_manifest",
            str(manifest_path),
            "--require-status",
            "success",
            "--require-local-run-config",
            "--require-run-id",
            str(run_config_value["run_id"]),
            "--require-project",
            INTEGRATION_ID,
            "--require-mode",
            OUTPUT_MODE,
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if verify.returncode != 0:
        raise ContractError(
            "source-revision manifest verification failed: "
            + (verify.stdout + verify.stderr).strip()
        )


def _comparison_metrics(
    baseline: BranchData,
    revised: BranchData,
) -> dict[str, Any]:
    paired = _paired(baseline, revised)
    baseline_census = baseline.metrics["census"]
    revised_census = revised.metrics["census"]
    result: dict[str, Any] = {}
    for metric, census_name in COUNT_FIELDS.items():
        baseline_value = int(baseline_census[census_name])
        revised_value = int(revised_census[census_name])
        result[metric] = {
            "baseline": baseline_value,
            "revised": revised_value,
            "delta_revised_minus_baseline": revised_value - baseline_value,
        }
    result.update(
        {
            "common_local_exit_position_rms_mm": paired["position_mm"]["distance"][
                "rms"
            ],
            "common_local_exit_velocity_rms_m_per_s": paired["velocity_m_s"][
                "distance"
            ]["rms"],
            "common_local_exit_time_rms_us": paired["instrument_time_us"]["rms"],
            "common_local_exit_energy_rms_eV": paired["kinetic_energy_eV"]["rms"],
        }
    )
    baseline_local = set(baseline.states)
    revised_local = set(revised.states)
    baseline_hits = {
        particle_id
        for particle_id, row in baseline.downstream.items()
        if row["hit"]
    }
    revised_hits = {
        particle_id
        for particle_id, row in revised.downstream.items()
        if row["hit"]
    }
    return {
        "required_metrics": result,
        "common_local_exit_particle_count": paired["paired_particle_count"],
        "common_local_exit_particle_ids": paired["paired_particle_ids"],
        "local_exit_particle_symmetric_difference_count": len(
            baseline_local ^ revised_local
        ),
        "detector_hit_symmetric_difference_count": len(
            baseline_hits ^ revised_hits
        ),
        "paired_diagnostics": paired,
    }


def _validate_preregistration(
    preregistration: Mapping[str, Any],
    *,
    profile_id: str,
    source_revision_id: str,
    baseline_parent_run_id: str,
) -> None:
    expected = {
        "schema_version": 1,
        "role": "integration_family_source_revision_preregistration",
        "integration_id": INTEGRATION_ID,
        "source_revision_id": source_revision_id,
        "preregistered_before_run": True,
        "execution_status": "NOT_RUN",
    }
    if any(preregistration.get(name) != value for name, value in expected.items()):
        raise ContractError(f"{source_revision_id} preregistration identity differs")
    profile = preregistration.get("profile")
    comparison = preregistration.get("comparison")
    if (
        not isinstance(profile, Mapping)
        or profile.get("connection_profile_id") != profile_id
        or profile.get("source_branch_ids") != ["comsol"]
        or profile.get("particle_count") != 100
        or not isinstance(comparison, Mapping)
        or comparison.get("baseline_parent_run_id") != baseline_parent_run_id
        or comparison.get("only_changed_variable")
        != "upstream_comsol_source_revision"
        or comparison.get("required_metrics") != list(REQUIRED_METRICS)
    ):
        raise ContractError(f"{source_revision_id} preregistration scope differs")


def publish_source_revision_comparison_run(
    *,
    repo_root: Path,
    run_id: str,
    comparisons: Sequence[tuple[str, str, str, str, str]],
) -> Path:
    """Validate three preregistered comparisons and publish one compact run."""
    repo_root = repo_root.resolve()
    workspace_root = repo_root.parent
    try:
        validate_run_id(run_id)
    except ValueError as error:
        raise ContractError("source-revision analysis run_id is invalid") from error
    if len(comparisons) != 3:
        raise ContractError("source-revision analysis requires exactly three comparisons")
    profile_ids = [item[0] for item in comparisons]
    revision_ids = [item[1] for item in comparisons]
    parent_ids = [parent for item in comparisons for parent in item[3:]]
    if (
        len(set(profile_ids)) != 3
        or len(set(revision_ids)) != 3
        or len(set(parent_ids)) != 6
    ):
        raise ContractError("profiles, revisions, and parent runs must be unique")

    runs_root = (
        workspace_root / "artifacts" / "projects" / INTEGRATION_ID / "runs"
    ).resolve()
    run_dir = (runs_root / run_id).resolve()
    if run_dir.parent != runs_root or run_dir.exists():
        raise ContractError("source-revision analysis output already exists or is invalid")

    request: dict[str, Any] = {
        "schema_version": 1,
        "role": "rf_oatof_source_revision_comparison_request",
        "integration_id": INTEGRATION_ID,
        "comparisons": [],
    }
    results: list[dict[str, Any]] = []
    input_paths: dict[str, Path] = {}
    for (
        profile_id,
        source_revision_id,
        prereg_relative,
        baseline_parent_id,
        revised_parent_id,
    ) in sorted(comparisons):
        prereg_path = (repo_root / prereg_relative).resolve()
        preregistration = _load(
            prereg_path, f"{source_revision_id} preregistration"
        )
        _validate_preregistration(
            preregistration,
            profile_id=profile_id,
            source_revision_id=source_revision_id,
            baseline_parent_run_id=baseline_parent_id,
        )
        input_paths[f"{source_revision_id}_preregistration"] = prereg_path
        branches: dict[str, BranchData] = {}
        request_item: dict[str, Any] = {
            "profile_id": profile_id,
            "source_revision_id": source_revision_id,
            "preregistration": {
                "path": str(prereg_path),
                "sha256": file_sha256(prereg_path),
            },
        }
        for label, parent_id in (
            ("baseline", baseline_parent_id),
            ("revised", revised_parent_id),
        ):
            parent_config, terminal_manifest = _parent_run(
                workspace_root=workspace_root,
                runs_root=runs_root,
                profile_id=profile_id,
                solver="comsol",
                parent_run_id=parent_id,
            )
            actual_revision = parent_config.get("source_revision_id", "baseline")
            expected_revision = (
                "baseline" if label == "baseline" else source_revision_id
            )
            if actual_revision in (None, ""):
                actual_revision = "baseline"
            if actual_revision != expected_revision:
                raise ContractError(
                    f"{source_revision_id} {label} parent source revision differs"
                )
            parent_manifest = runs_root / parent_id / "run_manifest.json"
            key = f"{source_revision_id}_{label}"
            input_paths[f"{key}_parent_manifest"] = parent_manifest
            input_paths[f"{key}_terminal_manifest"] = terminal_manifest
            branch_request = _terminal_branch(
                repo_root=repo_root,
                workspace_root=workspace_root,
                profile_id=profile_id,
                solver="comsol",
                parent_config=parent_config,
                manifest_path=terminal_manifest,
            )
            request_item[label] = branch_request
            branches[label] = _load_branch(
                branch_request,
                workspace_root,
                source_revision_id,
                "comsol",
            )
        request["comparisons"].append(request_item)
        metrics = _comparison_metrics(branches["baseline"], branches["revised"])
        results.append(
            {
                "profile_id": profile_id,
                "source_revision_id": source_revision_id,
                "baseline_parent_run_id": baseline_parent_id,
                "revised_parent_run_id": revised_parent_id,
                **metrics,
            }
        )

    mother_hashes = {
        branch["source_input"]["sha256"]
        for item in request["comparisons"]
        for label in ("baseline", "revised")
        for branch in (item[label],)
    }
    if len(mother_hashes) != 1:
        raise ContractError("source revisions do not share one mother source")

    implementation = Path(__file__).resolve()
    request_path = run_dir / "inputs" / "source_revision_comparison_request.json"
    result_path = run_dir / "results" / "source_revision_comparison.json"
    run_config_path = run_dir / "run_config.json"
    summary_path = run_dir / "summary.json"
    manifest_path = run_dir / "run_manifest.json"
    input_paths["source_revision_comparison_request"] = request_path
    input_paths["source_revision_comparison_implementation"] = implementation
    input_paths["requirements_lock"] = repo_root / "requirements-lock.txt"
    run_config = {
        "schema_version": 2,
        "run_id": run_id,
        "project": INTEGRATION_ID,
        "mode": OUTPUT_MODE,
        "project_root": str(workspace_root),
        "inputs": {
            name: _portable(path, workspace_root)
            for name, path in sorted(input_paths.items())
        },
        "parameters": {
            "particle_count": 100,
            "profile_ids": sorted(profile_ids),
            "source_revision_ids": sorted(revision_ids),
            "only_changed_variable": "upstream_comsol_source_revision",
            "required_metrics": list(REQUIRED_METRICS),
            "acceptance_thresholds_applied": False,
            "qualification_decision_made": False,
        },
        "artifact_retention": {
            "policy_version": 1,
            "class": "compact",
            "reason": None,
        },
        "formal_gate_passed": False,
    }
    result = {
        "schema_version": 1,
        "role": OUTPUT_ROLE,
        "status": "INCONCLUSIVE_DIAGNOSTIC_ONLY",
        "only_changed_variable": "upstream_comsol_source_revision",
        "shared_mother_source_sha256": next(iter(mother_hashes)),
        "acceptance_thresholds_applied": False,
        "qualification_decision_made": False,
        "comparisons": results,
    }
    summary = {
        "schema_version": 1,
        "role": SUMMARY_ROLE,
        "status": "success",
        "analysis_status": "INCONCLUSIVE_DIAGNOSTIC_ONLY",
        "comparison_count": 3,
        "profile_ids": sorted(profile_ids),
        "source_revision_ids": sorted(revision_ids),
        "shared_mother_source_sha256": next(iter(mother_hashes)),
        "result": "results/source_revision_comparison.json",
        "formal_gate_passed": False,
    }

    run_dir.mkdir(parents=True, exist_ok=False)
    _write_pending_json(request_path, request)
    _write_pending_json(result_path, result)
    _write_pending_json(run_config_path, run_config)
    _write_pending_json(summary_path, summary)
    pending_manifest = manifest_path.with_name(".run_manifest.json.pending")
    _publish_source_revision_manifest(
        repo_root=repo_root,
        run_config=run_config_path,
        manifest_path=pending_manifest,
        outputs=(result_path, summary_path),
    )
    os.replace(pending_manifest, manifest_path)
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--comparison",
        action="append",
        nargs=5,
        metavar=(
            "PROFILE",
            "REVISION",
            "PREREGISTRATION",
            "BASELINE_PARENT",
            "REVISED_PARENT",
        ),
        required=True,
    )
    args = parser.parse_args()
    manifest = publish_source_revision_comparison_run(
        repo_root=args.repo_root,
        run_id=args.run_id,
        comparisons=[tuple(item) for item in args.comparison],
    )
    print(
        "SOURCE_REVISION_COMPARISON=PASS "
        f"STATUS=INCONCLUSIVE_DIAGNOSTIC_ONLY MANIFEST={manifest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
