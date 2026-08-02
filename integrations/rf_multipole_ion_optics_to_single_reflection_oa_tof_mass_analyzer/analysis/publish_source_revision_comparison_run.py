"""Publish a governed three-arm RF-source and oaTOF downstream comparison."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from common.contracts.artifact_naming import validate_run_id
from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from common.multipole.exit_state_plot import (
    export_figure,
    load_exit_state,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.paired_downstream_analysis import (
    BranchData,
    _load_branch,
    _paired,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.publish_paired_downstream_run import (
    INTEGRATION_ID,
    _load,
    _parent_run,
    _terminal_branch,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.run_publication import (
    portable_path as _portable,
    publish_manifest as _shared_publish_manifest,
    restore_interrupted as _shared_restore_interrupted,
    terminalize_failure as _shared_terminalize_failure,
    write_pending_json as _write_pending_json,
)

OUTPUT_MODE = "multipole_family_source_revision_comparison_n100"
OUTPUT_ROLE = "rf_oatof_source_revision_comparison"
SUMMARY_ROLE = "integration_family_source_revision_comparison_summary"
REQUEST_ROLE = "rf_oatof_source_revision_triangle_request"
SOURCE_COMPARISON_RELATIVE_PATH = (
    "integrations/"
    "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
    "analysis/publish_source_revision_comparison_run.py"
)
PAIRED_ANALYSIS_RELATIVE_PATH = (
    "integrations/"
    "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
    "analysis/paired_downstream_analysis.py"
)
EXIT_STATE_PLOT_RELATIVE_PATH = "common/multipole/exit_state_plot.py"
BRANCH_LABELS = (
    "baseline_comsol",
    "hybrid_comsol",
    "baseline_simion",
)
PAIR_DEFINITIONS = (
    (
        "baseline_comsol__vs__hybrid_comsol",
        "baseline_comsol",
        "hybrid_comsol",
    ),
    (
        "baseline_comsol__vs__baseline_simion",
        "baseline_comsol",
        "baseline_simion",
    ),
    (
        "hybrid_comsol__vs__baseline_simion",
        "hybrid_comsol",
        "baseline_simion",
    ),
)
PLOT_BIN_COUNT = 24
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
_PROFILE_FAMILY = re.compile(r"^rf_(quadrupole|hexapole|octupole)_")


def _publish_source_revision_manifest(
    *,
    repo_root: Path,
    run_config: Path,
    manifest_path: Path,
    status: str,
    outputs: Sequence[Path],
) -> None:
    _shared_publish_manifest(
        repo_root=repo_root,
        run_config=run_config,
        manifest_path=manifest_path,
        status=status,
        outputs=outputs,
        project=INTEGRATION_ID,
        mode=OUTPUT_MODE,
        label="source-revision",
    )


def _restore_interrupted(
    *,
    summary_path: Path,
    manifest_path: Path,
    manifest_pending: Path,
    summary_bytes: bytes,
    manifest_bytes: bytes,
) -> None:
    _shared_restore_interrupted(
        summary_path=summary_path,
        manifest_path=manifest_path,
        manifest_pending=manifest_pending,
        summary_bytes=summary_bytes,
        manifest_bytes=manifest_bytes,
    )


def _terminalize_failure(
    *,
    repo_root: Path,
    run_config_path: Path,
    summary_path: Path,
    manifest_path: Path,
    manifest_pending: Path,
    failed_summary: Mapping[str, Any],
    planned_outputs: Sequence[Path],
    interrupted_summary_bytes: bytes,
    interrupted_manifest_bytes: bytes,
) -> None:
    _shared_terminalize_failure(
        publish=_publish_source_revision_manifest,
        repo_root=repo_root,
        run_config_path=run_config_path,
        summary_path=summary_path,
        manifest_path=manifest_path,
        manifest_pending=manifest_pending,
        failed_summary=failed_summary,
        candidate_outputs=planned_outputs,
        interrupted_summary_bytes=interrupted_summary_bytes,
        interrupted_manifest_bytes=interrupted_manifest_bytes,
    )


def _particle_set_comparison(
    left_ids: set[int],
    right_ids: set[int],
) -> dict[str, Any]:
    return {
        "sets_exact": left_ids == right_ids,
        "common_particle_count": len(left_ids & right_ids),
        "common_particle_ids": sorted(left_ids & right_ids),
        "symmetric_difference_count": len(left_ids ^ right_ids),
        "left_only_particle_ids": sorted(left_ids - right_ids),
        "right_only_particle_ids": sorted(right_ids - left_ids),
    }


def _pair_edge(
    left: BranchData,
    right: BranchData,
    *,
    left_label: str,
    right_label: str,
) -> dict[str, Any]:
    local_sets = _particle_set_comparison(set(left.states), set(right.states))
    crossing_sets = _particle_set_comparison(
        {
            particle_id
            for particle_id, row in left.downstream.items()
            if row["crossing"]
        },
        {
            particle_id
            for particle_id, row in right.downstream.items()
            if row["crossing"]
        },
    )
    hit_sets = _particle_set_comparison(
        {
            particle_id
            for particle_id, row in left.downstream.items()
            if row["hit"]
        },
        {
            particle_id
            for particle_id, row in right.downstream.items()
            if row["hit"]
        },
    )
    return {
        "schema_version": 2,
        "pair": {
            "left_label": left_label,
            "right_label": right_label,
            "difference_convention": "right_minus_left",
        },
        "census": {
            "left": left.metrics["census"],
            "right": right.metrics["census"],
        },
        "local_accelerator_exit": {
            "particle_sets": local_sets,
            "paired_continuous_diagnostics": _paired(
                left,
                right,
                left_label=left_label,
                right_label=right_label,
                schema_version=2,
            ),
        },
        "detector": {
            "crossing_particle_sets": crossing_sets,
            "hit_particle_sets": hit_sets,
        },
    }


def _comparison_metrics(
    baseline: BranchData,
    revised: BranchData,
) -> dict[str, Any]:
    """Return the preregistered baseline-COMSOL versus hybrid-COMSOL metrics."""
    edge = _pair_edge(
        baseline,
        revised,
        left_label="baseline_comsol",
        right_label="hybrid_comsol",
    )
    paired = edge["local_accelerator_exit"]["paired_continuous_diagnostics"]
    result: dict[str, Any] = {}
    for metric, census_name in COUNT_FIELDS.items():
        baseline_value = int(baseline.metrics["census"][census_name])
        revised_value = int(revised.metrics["census"][census_name])
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
    return {
        "required_metrics": result,
        "common_local_exit_particle_count": paired["paired_particle_count"],
        "common_local_exit_particle_ids": paired["paired_particle_ids"],
        "local_exit_particle_symmetric_difference_count": edge[
            "local_accelerator_exit"
        ]["particle_sets"]["symmetric_difference_count"],
        "detector_hit_symmetric_difference_count": edge["detector"][
            "hit_particle_sets"
        ]["symmetric_difference_count"],
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


def _profile_family(profile_id: str) -> str:
    match = _PROFILE_FAMILY.match(profile_id)
    if match is None:
        raise ContractError(f"source-revision profile family is invalid: {profile_id}")
    return match.group(1)


def _validate_source_revision_result(
    document: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Accept immutable schema-v1 results and the governed schema-v2 triangle."""
    if (
        document.get("role") != OUTPUT_ROLE
        or document.get("status") != "INCONCLUSIVE_DIAGNOSTIC_ONLY"
    ):
        raise ContractError("source-revision result identity differs")
    schema_version = document.get("schema_version")
    comparisons = document.get("comparisons")
    if not isinstance(comparisons, list):
        raise ContractError("source-revision result comparisons are invalid")
    if schema_version == 1:
        return document
    if schema_version != 2 or len(comparisons) != 3:
        raise ContractError("source-revision result schema/count differs")
    required_edges = {name for name, _, _ in PAIR_DEFINITIONS}
    for comparison in comparisons:
        if (
            not isinstance(comparison, Mapping)
            or set(comparison.get("branches", {})) != set(BRANCH_LABELS)
            or set(comparison.get("pairwise_edges", {})) != required_edges
        ):
            raise ContractError("source-revision triangle fields differ")
        for edge in comparison["pairwise_edges"].values():
            pair = edge.get("pair", {})
            if pair.get("difference_convention") != "right_minus_left":
                raise ContractError("source-revision triangle direction differs")
    return document


def load_source_revision_result(path: Path) -> Mapping[str, Any]:
    """Load either historical schema v1 or current schema v2 without rewriting."""
    return _validate_source_revision_result(_load(path, "source-revision result"))


def _branch_summary(branch: BranchData) -> dict[str, Any]:
    return {
        "source_lineage": branch.source_lineage,
        "binding_identity": branch.binding_identity,
        "census": branch.metrics["census"],
        "local_accelerator_exit_particle_ids": sorted(branch.states),
        "detector_crossing_particle_ids": sorted(
            particle_id
            for particle_id, row in branch.downstream.items()
            if row["crossing"]
        ),
        "detector_hit_particle_ids": sorted(
            particle_id
            for particle_id, row in branch.downstream.items()
            if row["hit"]
        ),
    }


def _comparison_result(
    *,
    profile_id: str,
    source_revision_id: str,
    parent_run_ids: Mapping[str, str],
    branches: Mapping[str, BranchData],
) -> dict[str, Any]:
    profile_ids = {
        branch.binding_identity["connection_profile_id"]
        for branch in branches.values()
    }
    if profile_ids != {profile_id}:
        raise ContractError(f"{source_revision_id} branch profile bindings differ")
    if (
        branches["baseline_comsol"].binding_identity
        != branches["baseline_simion"].binding_identity
    ):
        raise ContractError(
            f"{source_revision_id} baseline COMSOL/SIMION bindings differ"
        )
    resolved_hashes = {
        branch.binding_identity["resolved_connection_sha256"]
        for branch in branches.values()
    }
    if len(resolved_hashes) != 1:
        raise ContractError(
            f"{source_revision_id} three-arm resolved connections differ"
        )
    mother_hashes = {
        branch.source_lineage["source_input_sha256"]
        for branch in branches.values()
    }
    if len(mother_hashes) != 1:
        raise ContractError(f"{source_revision_id} branches do not share one mother source")
    required = _comparison_metrics(
        branches["baseline_comsol"],
        branches["hybrid_comsol"],
    )
    edges = {
        edge_id: _pair_edge(
            branches[left_label],
            branches[right_label],
            left_label=left_label,
            right_label=right_label,
        )
        for edge_id, left_label, right_label in PAIR_DEFINITIONS
    }
    return {
        "profile_id": profile_id,
        "source_revision_id": source_revision_id,
        "parent_run_ids": dict(parent_run_ids),
        "shared_mother_source_sha256": next(iter(mother_hashes)),
        "source_revision_required_metrics": required["required_metrics"],
        "branches": {
            label: _branch_summary(branches[label]) for label in BRANCH_LABELS
        },
        "pairwise_edges": edges,
    }


def _figure_paths(result_dir: Path, profile_id: str) -> tuple[Path, Path]:
    family = _profile_family(profile_id)
    return (
        result_dir / f"{family}__rf-exit-state-triangle.png",
        result_dir / f"{family}__rf-exit-state-triangle.figure.json",
    )


def _render_source_triangle(
    *,
    request_item: Mapping[str, Any],
    branches: Mapping[str, BranchData],
    output: Path,
    manifest: Path,
    repo_root: Path,
) -> None:
    labels = {
        "baseline_comsol": "Baseline COMSOL",
        "hybrid_comsol": "Hybrid COMSOL",
        "baseline_simion": "Baseline SIMION",
    }
    states = []
    run_ids = []
    for branch_label in BRANCH_LABELS:
        source_reference = request_item[branch_label]["source_state"]
        source_path = Path(str(source_reference["path"]))
        states.append(load_exit_state(source_path, labels[branch_label]))
        run_ids.append(branches[branch_label].source_lineage["source_run_id"])
    family = _profile_family(str(request_item["profile_id"]))
    export_figure(
        states,
        output,
        manifest,
        f"RF {family} source exit-state triangle",
        "Posthoc descriptive baseline COMSOL, hybrid COMSOL, and baseline SIMION source comparison",
        bin_count=PLOT_BIN_COUNT,
        repo_root=repo_root,
        run_ids=run_ids,
    )


def publish_source_revision_comparison_run(
    *,
    repo_root: Path,
    run_id: str,
    comparisons: Sequence[tuple[str, str, str, str, str, str]],
) -> Path:
    """Validate three explicit three-arm comparisons and publish one compact run."""
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
        or len(set(parent_ids)) != 9
    ):
        raise ContractError("profiles, revisions, and parent runs must be unique")

    runs_root = (
        workspace_root / "artifacts" / "projects" / INTEGRATION_ID / "runs"
    ).resolve()
    run_dir = (runs_root / run_id).resolve()
    if run_dir.parent != runs_root or run_dir.exists():
        raise ContractError("source-revision analysis output already exists or is invalid")

    request: dict[str, Any] = {
        "schema_version": 2,
        "role": REQUEST_ROLE,
        "integration_id": INTEGRATION_ID,
        "comparisons": [],
    }
    input_paths: dict[str, Path] = {}
    parent_run_ids: dict[str, dict[str, str]] = {}
    for (
        profile_id,
        source_revision_id,
        prereg_relative,
        baseline_comsol_parent_id,
        hybrid_comsol_parent_id,
        baseline_simion_parent_id,
    ) in sorted(comparisons):
        prereg_path = (repo_root / prereg_relative).resolve()
        preregistration = _load(
            prereg_path, f"{source_revision_id} preregistration"
        )
        _validate_preregistration(
            preregistration,
            profile_id=profile_id,
            source_revision_id=source_revision_id,
            baseline_parent_run_id=baseline_comsol_parent_id,
        )
        input_paths[f"{source_revision_id}_preregistration"] = prereg_path
        ids = {
            "baseline_comsol": baseline_comsol_parent_id,
            "hybrid_comsol": hybrid_comsol_parent_id,
            "baseline_simion": baseline_simion_parent_id,
        }
        parent_run_ids[profile_id] = ids
        request_item: dict[str, Any] = {
            "profile_id": profile_id,
            "source_revision_id": source_revision_id,
            "preregistration": {
                "path": str(prereg_path),
                "sha256": file_sha256(prereg_path),
            },
        }
        for branch_label, solver, expected_revision in (
            ("baseline_comsol", "comsol", "baseline"),
            ("hybrid_comsol", "comsol", source_revision_id),
            ("baseline_simion", "simion", "baseline"),
        ):
            parent_id = ids[branch_label]
            parent_config, terminal_manifest = _parent_run(
                workspace_root=workspace_root,
                runs_root=runs_root,
                profile_id=profile_id,
                solver=solver,
                parent_run_id=parent_id,
            )
            actual_revision = parent_config.get("source_revision_id", "baseline")
            if actual_revision in (None, ""):
                actual_revision = "baseline"
            if actual_revision != expected_revision:
                raise ContractError(
                    f"{source_revision_id} {branch_label} parent source revision differs"
                )
            key = f"{source_revision_id}_{branch_label}"
            parent_manifest = runs_root / parent_id / "run_manifest.json"
            input_paths[f"{key}_parent_manifest"] = parent_manifest
            input_paths[f"{key}_terminal_manifest"] = terminal_manifest
            request_item[branch_label] = _terminal_branch(
                repo_root=repo_root,
                workspace_root=workspace_root,
                profile_id=profile_id,
                solver=solver,
                parent_config=parent_config,
                manifest_path=terminal_manifest,
            )
        request["comparisons"].append(request_item)

    request_path = run_dir / "inputs" / "source_revision_comparison_request.json"
    result_path = run_dir / "results" / "source_revision_comparison.json"
    run_config_path = run_dir / "run_config.json"
    summary_path = run_dir / "summary.json"
    manifest_path = run_dir / "run_manifest.json"
    figure_paths = {
        item["profile_id"]: _figure_paths(run_dir / "results", item["profile_id"])
        for item in request["comparisons"]
    }
    implementation_paths = {
        "source_revision_comparison_implementation": (
            repo_root / SOURCE_COMPARISON_RELATIVE_PATH
        ),
        "paired_analysis_implementation": repo_root / PAIRED_ANALYSIS_RELATIVE_PATH,
        "exit_state_plot_implementation": repo_root / EXIT_STATE_PLOT_RELATIVE_PATH,
        "requirements_lock": repo_root / "requirements-lock.txt",
    }
    for name, path in implementation_paths.items():
        if not path.is_file():
            raise ContractError(f"source-revision implementation input is missing: {name}")
        input_paths[name] = path
    input_paths["source_revision_comparison_request"] = request_path
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
            "comparison_schema_version": 2,
            "particle_count": 100,
            "profile_ids": sorted(profile_ids),
            "source_revision_ids": sorted(revision_ids),
            "branch_labels": list(BRANCH_LABELS),
            "pair_ids": [name for name, _, _ in PAIR_DEFINITIONS],
            "parent_run_ids": parent_run_ids,
            "only_changed_variable": "upstream_comsol_source_revision",
            "source_revision_required_metrics": list(REQUIRED_METRICS),
            "plot_bin_count": PLOT_BIN_COUNT,
            "plot_scale_policy": "pooled_three_series_per_profile",
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
    summary_base = {
        "schema_version": 2,
        "role": SUMMARY_ROLE,
        "comparison_count": 3,
        "profile_ids": sorted(profile_ids),
        "source_revision_ids": sorted(revision_ids),
        "branch_labels": list(BRANCH_LABELS),
        "pair_ids": [name for name, _, _ in PAIR_DEFINITIONS],
        "acceptance_thresholds_applied": False,
        "qualification_decision_made": False,
        "formal_gate_passed": False,
    }

    run_dir.mkdir(parents=True, exist_ok=False)
    _write_pending_json(request_path, request)
    _write_pending_json(run_config_path, run_config)
    interrupted_summary = {
        **summary_base,
        "status": "interrupted",
        "analysis_status": "NOT_RUN",
        "shared_mother_source_sha256": None,
        "result": None,
        "figures": [],
    }
    _write_pending_json(summary_path, interrupted_summary)
    manifest_pending = manifest_path.with_name(".run_manifest.json.pending")
    _publish_source_revision_manifest(
        repo_root=repo_root,
        run_config=run_config_path,
        manifest_path=manifest_pending,
        status="interrupted",
        outputs=(summary_path,),
    )
    os.replace(manifest_pending, manifest_path)
    interrupted_summary_bytes = summary_path.read_bytes()
    interrupted_manifest_bytes = manifest_path.read_bytes()
    planned_outputs = [
        result_path,
        summary_path,
        *[
            path
            for profile_paths in figure_paths.values()
            for path in profile_paths
        ],
    ]

    failure_stage = "three_arm_analysis"
    try:
        results = []
        shared_mother_hashes: set[str] = set()
        figure_records = []
        for request_item in request["comparisons"]:
            source_revision_id = request_item["source_revision_id"]
            branches = {
                label: _load_branch(
                    request_item[label],
                    workspace_root,
                    source_revision_id,
                    "simion" if label == "baseline_simion" else "comsol",
                )
                for label in BRANCH_LABELS
            }
            comparison_result = _comparison_result(
                profile_id=request_item["profile_id"],
                source_revision_id=source_revision_id,
                parent_run_ids=parent_run_ids[request_item["profile_id"]],
                branches=branches,
            )
            output, figure_manifest = figure_paths[request_item["profile_id"]]
            failure_stage = f"figure_{_profile_family(request_item['profile_id'])}"
            _render_source_triangle(
                request_item=request_item,
                branches=branches,
                output=output,
                manifest=figure_manifest,
                repo_root=repo_root,
            )
            comparison_result["source_exit_state_figure"] = {
                "path": output.relative_to(run_dir).as_posix(),
                "manifest": figure_manifest.relative_to(run_dir).as_posix(),
                "shared_scale_policy": "pooled_three_series_per_profile",
                "bin_count": PLOT_BIN_COUNT,
            }
            results.append(comparison_result)
            shared_mother_hashes.add(
                comparison_result["shared_mother_source_sha256"]
            )
            figure_records.append(comparison_result["source_exit_state_figure"])
        if len(shared_mother_hashes) != 1:
            raise ContractError("all three profiles must share one mother source")
        shared_mother_sha256 = next(iter(shared_mother_hashes))
        result = {
            "schema_version": 2,
            "role": OUTPUT_ROLE,
            "status": "INCONCLUSIVE_DIAGNOSTIC_ONLY",
            "analysis_class": "POSTHOC_DESCRIPTIVE",
            "only_changed_variable": "upstream_comsol_source_revision",
            "shared_mother_source_sha256": shared_mother_sha256,
            "acceptance_thresholds_applied": False,
            "qualification_decision_made": False,
            "comparisons": results,
        }
        summary = {
            **summary_base,
            "status": "success",
            "analysis_status": "INCONCLUSIVE_DIAGNOSTIC_ONLY",
            "analysis_class": "POSTHOC_DESCRIPTIVE",
            "shared_mother_source_sha256": shared_mother_sha256,
            "result": "results/source_revision_comparison.json",
            "figures": figure_records,
        }
        failure_stage = "result_publication"
        _write_pending_json(result_path, result)
        load_source_revision_result(result_path)
        _write_pending_json(summary_path, summary)
        failure_stage = "success_manifest_publication"
        _publish_source_revision_manifest(
            repo_root=repo_root,
            run_config=run_config_path,
            manifest_path=manifest_pending,
            status="success",
            outputs=planned_outputs,
        )
        failure_stage = "success_manifest_commit"
        os.replace(manifest_pending, manifest_path)
        return manifest_path
    except (KeyboardInterrupt, SystemExit):
        _restore_interrupted(
            summary_path=summary_path,
            manifest_path=manifest_path,
            manifest_pending=manifest_pending,
            summary_bytes=interrupted_summary_bytes,
            manifest_bytes=interrupted_manifest_bytes,
        )
        raise
    except Exception as error:
        failed_summary = {
            **summary_base,
            "status": "failed",
            "analysis_status": (
                "INCONCLUSIVE_DIAGNOSTIC_ONLY"
                if result_path.is_file()
                else "FAILED"
            ),
            "analysis_class": "POSTHOC_DESCRIPTIVE",
            "shared_mother_source_sha256": None,
            "result": (
                "results/source_revision_comparison.json"
                if result_path.is_file()
                else None
            ),
            "figures": [
                {
                    "path": path.relative_to(run_dir).as_posix(),
                }
                for path in planned_outputs
                if path.suffix == ".png" and path.is_file()
            ],
            "failure_stage": failure_stage,
            "reason": str(error),
            "error_type": type(error).__name__,
        }
        _terminalize_failure(
            repo_root=repo_root,
            run_config_path=run_config_path,
            summary_path=summary_path,
            manifest_path=manifest_path,
            manifest_pending=manifest_pending,
            failed_summary=failed_summary,
            planned_outputs=planned_outputs,
            interrupted_summary_bytes=interrupted_summary_bytes,
            interrupted_manifest_bytes=interrupted_manifest_bytes,
        )
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--comparison",
        action="append",
        nargs=6,
        metavar=(
            "PROFILE",
            "REVISION",
            "PREREGISTRATION",
            "BASELINE_COMSOL_PARENT",
            "HYBRID_COMSOL_PARENT",
            "BASELINE_SIMION_PARENT",
        ),
        required=True,
    )
    args = parser.parse_args()
    if len(args.comparison) != 3:
        parser.error("--comparison must be supplied exactly three times")
    manifest = publish_source_revision_comparison_run(
        repo_root=args.repo_root,
        run_id=args.run_id,
        comparisons=[tuple(item) for item in args.comparison],
    )
    print(
        "SOURCE_REVISION_COMPARISON=PASS "
        f"SCHEMA_VERSION=2 STATUS=INCONCLUSIVE_DIAGNOSTIC_ONLY "
        f"MANIFEST={manifest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
