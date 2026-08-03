"""Publish a descriptive comparison of completed multipole-to-oaTOF campaign runs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from common.contracts.artifact_naming import validate_run_id
from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from common.multipole.exit_state_plot import _git_identity
from projects.single_reflection_oa_tof_mass_analyzer.analysis.peak_metrics import (
    FWHM_FACTOR,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.run_publication import (
    freeze_repository_inputs,
    load_json,
    portable_path,
    publish_manifest,
    record_for_path,
    restore_interrupted,
    terminalize_failure,
    verified_record,
    write_pending_json,
)


INTEGRATION_ID = (
    "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
)
PARENT_MODE = "multipole_family_source_closure"
TERMINAL_MODE = "rf_to_oatof_analyzer_transport"
OUTPUT_MODE = "multipole_oatof_campaign_descriptive_comparison"
OUTPUT_ROLE = "rf_multipole_oatof_campaign_descriptive_comparison"
SUMMARY_ROLE = "rf_multipole_oatof_campaign_comparison_summary"
REQUEST_ROLE = "rf_multipole_oatof_campaign_comparison_request"
IMPLEMENTATION_RELATIVE_PATH = (
    "integrations/"
    "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
    "analysis/publish_campaign_comparison_run.py"
)
STAGES = (
    "rf_exit",
    "oatof_entry",
    "active_at_pulse",
    "local_accelerator_exit",
    "detector_crossing",
    "detector_hit",
)
STAGE_LABELS = (
    "RF exit",
    "oaTOF entry",
    "Pulse active",
    "Local accel. exit",
    "Detector crossing",
    "Detector hit",
)
COLORS = ("#0072B2", "#E69F00", "#009E73", "#D55E00")
MARKERS = ("o", "s", "^", "D")
LINESTYLES = ("-", "--", "-.", ":")


@dataclass(frozen=True)
class CaseInputs:
    """Verified immutable paths for one completed parent run."""

    label: str
    parent_run_id: str
    parent_manifest: Path
    parent_summary: Path
    parent_config: Mapping[str, Any]
    campaign_sequence: int
    terminal_manifest: Path
    terminal_metrics: Path
    downstream_particles: Path


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def _record_path(label: str, record: Any) -> Path:
    verified = verified_record(label, record)
    path = Path(str(verified["path"])).resolve()
    if not path.is_file():
        raise ContractError(f"{label} path is missing: {path}")
    return path


def _output_named(manifest: Mapping[str, Any], name: str, label: str) -> Path:
    records = manifest.get("outputs")
    if not isinstance(records, list):
        raise ContractError(f"{label} outputs are invalid")
    matches = [
        record
        for record in records
        if isinstance(record, dict)
        and Path(str(record.get("path", ""))).name == name
    ]
    if len(matches) != 1:
        raise ContractError(f"{label} output {name} is not bound exactly once")
    return _record_path(f"{label} output {name}", matches[0])


def _workspace_path(raw: Any, workspace_root: Path) -> Path:
    path = Path(str(raw))
    return path.resolve() if path.is_absolute() else (workspace_root / path).resolve()


def _manifest_reference(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": file_sha256(path)}


def _publish_analysis_manifest(
    *,
    repo_root: Path,
    run_config: Path,
    manifest_path: Path,
    status: str,
    outputs: Sequence[Path],
) -> None:
    publish_manifest(
        repo_root=repo_root,
        run_config=run_config,
        manifest_path=manifest_path,
        status=status,
        outputs=outputs,
        project=INTEGRATION_ID,
        mode=OUTPUT_MODE,
        label="campaign-comparison",
    )


def _load_case_inputs(
    *,
    repo_root: Path,
    workspace_root: Path,
    runs_root: Path,
    label: str,
    parent_run_id: str,
) -> CaseInputs:
    if not label.strip():
        raise ContractError("campaign comparison label must be nonempty")
    try:
        validate_run_id(parent_run_id)
    except ValueError as error:
        raise ContractError(f"{label} parent run_id is invalid") from error
    repo_root = repo_root.resolve()
    workspace_root = workspace_root.resolve()
    runs_root = runs_root.resolve()
    parent_root = (runs_root / parent_run_id).resolve()
    if parent_root.parent != runs_root or not parent_root.is_dir():
        raise ContractError(f"{label} parent run is missing")
    parent_manifest_path = parent_root / "run_manifest.json"
    parent_manifest = load_json(parent_manifest_path, f"{label} parent manifest")
    if any(
        parent_manifest.get(name) != value
        for name, value in {
            "schema_version": 2,
            "role": "simulation_run_manifest",
            "run_id": parent_run_id,
            "project": INTEGRATION_ID,
            "mode": PARENT_MODE,
            "status": "success",
        }.items()
    ):
        raise ContractError(f"{label} parent manifest identity differs")
    parent_config_path = _record_path(
        f"{label} parent run_config", parent_manifest.get("run_config")
    )
    if parent_config_path.parent != parent_root:
        raise ContractError(f"{label} parent run_config is nonlocal")
    parent_config = load_json(parent_config_path, f"{label} parent run_config")
    profile_id = parent_config.get("connection_profile_id")
    solver = parent_config.get("source_branch_id")
    if (
        parent_config.get("schema_version") != 2
        or parent_config.get("run_id") != parent_run_id
        or parent_config.get("project") != INTEGRATION_ID
        or parent_config.get("mode") != PARENT_MODE
        or parent_config.get("formal_gate_passed") is not False
        or not isinstance(profile_id, str)
        or solver not in {"comsol", "simion"}
    ):
        raise ContractError(f"{label} parent profile/source identity differs")

    campaign_value = parent_config.get("campaign_path", "")
    campaign_path = Path(str(campaign_value))
    if not campaign_path.is_absolute():
        campaign_path = repo_root / campaign_path
    campaign_path = campaign_path.resolve()
    if (
        not campaign_path.is_relative_to(repo_root)
        or not campaign_path.is_file()
        or file_sha256(campaign_path) != parent_config.get("campaign_sha256")
    ):
        raise ContractError(f"{label} campaign identity differs")
    campaign = load_json(campaign_path, f"{label} campaign")
    experiment_id = parent_config.get("experiment_id")
    if (
        campaign.get("schema_version") != 1
        or campaign.get("role") != "rf_multipole_oatof_experiment_campaign"
        or campaign.get("integration_id") != INTEGRATION_ID
        or campaign.get("campaign_id") != parent_config.get("campaign_id")
        or not isinstance(experiment_id, str)
    ):
        raise ContractError(f"{label} campaign contract differs")
    experiments = campaign.get("experiments")
    matches = (
        [
            row
            for row in experiments
            if isinstance(row, dict) and row.get("experiment_id") == experiment_id
        ]
        if isinstance(experiments, list)
        else []
    )
    sequences = (
        [row.get("sequence") for row in experiments if isinstance(row, dict)]
        if isinstance(experiments, list)
        else []
    )
    if (
        len(sequences) != len(experiments or [])
        or any(not isinstance(value, int) or isinstance(value, bool) for value in sequences)
        or len(sequences) != len(set(sequences))
    ):
        raise ContractError(f"{label} campaign sequences are invalid")
    if len(matches) != 1:
        raise ContractError(f"{label} campaign experiment does not resolve once")
    experiment = matches[0]
    source = experiment.get("source")
    source_identity = parent_config.get("source_particle_identity")
    source_records = source if isinstance(source, dict) else {}

    def source_sha256(name: str) -> Any:
        record = source_records.get(name)
        return record.get("sha256") if isinstance(record, dict) else None

    expected_source = {
        "run_id": source_records.get("run_id"),
        "manifest_sha256": source_sha256("manifest"),
        "event_sha256": source_sha256("state"),
        "particle_source_sha256": source_sha256("particle_source"),
        "metadata_sha256": source_sha256("metadata"),
    }
    if (
        not isinstance(experiment.get("sequence"), int)
        or isinstance(experiment.get("sequence"), bool)
        or experiment.get("run_id") != parent_run_id
        or experiment.get("connection_profile_id") != profile_id
        or _canonical_sha256(experiment)
        != parent_config.get("experiment_row_sha256")
        or source_records.get("launched_particle_count")
        != parent_config.get("launched_particle_count")
        or source_records.get("particle_count") != parent_config.get("particle_count")
        or not isinstance(source_identity, dict)
        or source_identity.get("source_branch_id") != solver
        or source_identity.get("solver_id") != solver
        or any(source_identity.get(key) != value for key, value in expected_source.items())
    ):
        raise ContractError(f"{label} campaign row/source identity differs")

    parent_summary_path = _output_named(
        parent_manifest, "summary.json", f"{label} parent"
    )
    parent_summary = load_json(parent_summary_path, f"{label} parent summary")
    if any(
        parent_summary.get(name) != value
        for name, value in {
            "schema_version": 1,
            "role": "integration_family_source_closure_summary",
            "status": "success",
            "connection_profile_id": profile_id,
            "campaign_id": campaign["campaign_id"],
            "experiment_id": experiment_id,
            "experiment_row_sha256": parent_config["experiment_row_sha256"],
            "source_branch_id": solver,
            "launched_particle_count": parent_config["launched_particle_count"],
            "particle_count": parent_config["particle_count"],
            "formal_gate_passed": False,
        }.items()
    ):
        raise ContractError(f"{label} parent summary identity differs")

    stages = parent_config.get("stage_runs")
    analyzer = (
        [stage for stage in stages if isinstance(stage, dict) and stage.get("phase") == "analyzer_transport"]
        if isinstance(stages, list)
        else []
    )
    if len(analyzer) != 1:
        raise ContractError(f"{label} parent must bind one analyzer stage")
    stage = analyzer[0]
    stage_root = _workspace_path(stage.get("path", ""), workspace_root)
    terminal_manifest_path = stage_root / "run_manifest.json"
    stage_project = parent_config["source_particle_identity"]["project_id"]
    expected_stage_runs_root = (
        workspace_root / "artifacts" / "projects" / stage_project / "runs"
    ).resolve()
    if (
        stage_root.parent != expected_stage_runs_root
        or stage.get("run_id") != stage_root.name
        or not terminal_manifest_path.is_file()
        or stage.get("manifest_sha256") != file_sha256(terminal_manifest_path)
    ):
        raise ContractError(f"{label} analyzer stage identity differs")
    parent_inputs = parent_config.get("inputs")
    if (
        not isinstance(parent_inputs, dict)
        or _workspace_path(parent_inputs.get("analyzer_transport_manifest", ""), workspace_root)
        != terminal_manifest_path
    ):
        raise ContractError(f"{label} parent analyzer binding differs")
    parent_manifest_record = record_for_path(
        parent_manifest.get("inputs"), terminal_manifest_path, f"{label} terminal manifest"
    )
    if parent_manifest_record.get("sha256") != stage.get("manifest_sha256"):
        raise ContractError(f"{label} parent analyzer SHA-256 differs")

    terminal_manifest = load_json(
        terminal_manifest_path, f"{label} analyzer terminal manifest"
    )
    if any(
        terminal_manifest.get(name) != value
        for name, value in {
            "schema_version": 2,
            "role": "simulation_run_manifest",
            "mode": TERMINAL_MODE,
            "status": "success",
        }.items()
    ):
        raise ContractError(f"{label} analyzer terminal manifest differs")
    terminal_config_path = _record_path(
        f"{label} analyzer run_config", terminal_manifest.get("run_config")
    )
    if terminal_config_path.parent != stage_root:
        raise ContractError(f"{label} analyzer run_config is nonlocal")
    terminal_config = load_json(terminal_config_path, f"{label} analyzer run_config")
    parameters = terminal_config.get("parameters")
    if (
        terminal_config.get("run_id") != stage.get("run_id")
        or terminal_config.get("project") != source_identity.get("project_id")
        or terminal_config.get("mode") != TERMINAL_MODE
        or terminal_config.get("upstream_source_identity") != source_identity
        or not isinstance(parameters, dict)
        or parameters.get("connection_profile_id") != profile_id
        or parameters.get("source_branch_id") != solver
    ):
        raise ContractError(f"{label} analyzer source identity differs")
    return CaseInputs(
        label=label.strip(),
        parent_run_id=parent_run_id,
        parent_manifest=parent_manifest_path,
        parent_summary=parent_summary_path,
        parent_config=parent_config,
        campaign_sequence=experiment["sequence"],
        terminal_manifest=terminal_manifest_path,
        terminal_metrics=_output_named(
            terminal_manifest,
            "analyzer_transport_metrics.json",
            f"{label} analyzer terminal",
        ),
        downstream_particles=_output_named(
            terminal_manifest,
            "simion_downstream_particles.csv",
            f"{label} analyzer terminal",
        ),
    )


def _finite_float(raw: str, label: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as error:
        raise ContractError(f"{label} must be numeric") from error
    if not math.isfinite(value):
        raise ContractError(f"{label} must be finite")
    return value


def _compute_case(case: CaseInputs) -> dict[str, Any]:
    parent_summary = load_json(case.parent_summary, f"{case.label} parent summary")
    terminal_metrics = load_json(
        case.terminal_metrics, f"{case.label} analyzer metrics"
    )
    census = parent_summary.get("census")
    if (
        parent_summary.get("status") != "success"
        or parent_summary.get("claim_status") != "FUNCTIONAL_SCREEN_ONLY"
        or not isinstance(census, dict)
        or set(census) != set(STAGES)
        or census != terminal_metrics.get("census")
    ):
        raise ContractError(f"{case.label} census/claim identity differs")
    counts: dict[str, int] = {}
    previous: int | None = None
    for stage in STAGES:
        value = census[stage]
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            or (previous is not None and value > previous)
        ):
            raise ContractError(f"{case.label} census is invalid at {stage}")
        counts[stage] = value
        previous = value
    if counts["rf_exit"] < 1 or counts["detector_hit"] < 1:
        raise ContractError(f"{case.label} requires RF-exit and detector-hit particles")

    required_columns = {"Ion", "TofUs", "RadiusMm", "Hit"}
    row_count = 0
    hits: list[tuple[float, float]] = []
    with case.downstream_particles.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not required_columns.issubset(reader.fieldnames):
            raise ContractError(f"{case.label} downstream CSV columns differ")
        seen_ids: set[int] = set()
        for row in reader:
            row_count += 1
            try:
                particle_id = int(row["Ion"])
            except (TypeError, ValueError) as error:
                raise ContractError(f"{case.label} particle ID is invalid") from error
            if particle_id < 1 or particle_id in seen_ids:
                raise ContractError(f"{case.label} particle IDs are invalid")
            seen_ids.add(particle_id)
            hit_text = row["Hit"].strip().lower()
            if hit_text not in {"true", "false"}:
                raise ContractError(f"{case.label} Hit value is invalid")
            if hit_text == "true":
                hits.append(
                    (
                        _finite_float(row["TofUs"], f"{case.label} TofUs"),
                        _finite_float(row["RadiusMm"], f"{case.label} RadiusMm"),
                    )
                )
            elif row["TofUs"].strip() or row["RadiusMm"].strip():
                raise ContractError(f"{case.label} non-hit detector values are nonempty")
    if row_count != counts["local_accelerator_exit"] or len(hits) != counts["detector_hit"]:
        raise ContractError(f"{case.label} downstream CSV census differs")

    tof_us = [item[0] for item in hits]
    radii_mm = [item[1] for item in hits]
    mean_tof_us = statistics.fmean(tof_us)
    sigma_tof_us = statistics.stdev(tof_us)
    gaussian_fwhm_tof_ns = float(FWHM_FACTOR) * sigma_tof_us * 1000.0
    resolution_proxy = (
        mean_tof_us / (2.0 * gaussian_fwhm_tof_ns / 1000.0)
        if gaussian_fwhm_tof_ns > 0.0
        else None
    )
    source = case.parent_config.get("source_particle_identity")
    if not isinstance(source, dict):
        raise ContractError(f"{case.label} source identity is missing")
    denominator = counts["rf_exit"]
    return {
        "label": case.label,
        "parent_run_id": case.parent_run_id,
        "campaign_id": case.parent_config["campaign_id"],
        "experiment_id": case.parent_config["experiment_id"],
        "campaign_sequence": case.campaign_sequence,
        "experiment_row_sha256": case.parent_config["experiment_row_sha256"],
        "connection_profile_id": case.parent_config["connection_profile_id"],
        "source_branch_id": case.parent_config["source_branch_id"],
        "source_run_id": source.get("run_id"),
        "source_project_id": source.get("project_id"),
        "census": counts,
        "cumulative_retention_fraction": {
            stage: counts[stage] / denominator for stage in STAGES
        },
        "analyzer_metrics": {
            "detector_hit_count": len(hits),
            "detector_hit_fraction_of_rf_exit": len(hits) / denominator,
            "detector_hit_fraction_of_local_accelerator_exit": (
                len(hits) / counts["local_accelerator_exit"]
            ),
            "mean_analyzer_tof_us": mean_tof_us,
            "sample_sigma_analyzer_tof_ns": sigma_tof_us * 1000.0,
            "gaussian_fwhm_tof_proxy_ns": gaussian_fwhm_tof_ns,
            "time_domain_resolution_proxy": resolution_proxy,
            "maximum_hit_radius_mm": max(radii_mm),
            "tof_proxy_scope": (
                "descriptive Gaussian proxy from detector hits; not direct FWHM, "
                "not a resolution qualification"
            ),
        },
        "inputs": {
            "parent_manifest": _manifest_reference(case.parent_manifest),
            "terminal_manifest": _manifest_reference(case.terminal_manifest),
            "parent_summary": _manifest_reference(case.parent_summary),
            "terminal_metrics": _manifest_reference(case.terminal_metrics),
            "downstream_particles": _manifest_reference(case.downstream_particles),
        },
    }


def build_campaign_comparison_figure(
    cases: Sequence[Mapping[str, Any]],
):
    """Build the three-panel report figure without saving or showing it."""
    import matplotlib.pyplot as plt

    if len(cases) < 2 or len(cases) > len(COLORS):
        raise ContractError("campaign comparison figure requires two to four cases")
    with plt.rc_context(
        {
            "font.size": 8,
            "axes.labelsize": 9,
            "axes.titlesize": 10,
            "legend.fontsize": 8,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
        }
    ):
        figure, axes = plt.subplots(
            1, 3, figsize=(183 / 25.4, 90 / 25.4), constrained_layout=True
        )
        x_stage = list(range(len(STAGES)))
        x_case = list(range(len(cases)))
        for index, case in enumerate(cases):
            style = {
                "color": COLORS[index],
                "marker": MARKERS[index],
                "linestyle": LINESTYLES[index],
                "linewidth": 1.2,
                "markersize": 4.5,
                "label": case["label"],
            }
            axes[0].plot(
                x_stage,
                [100.0 * case["cumulative_retention_fraction"][stage] for stage in STAGES],
                **style,
            )
            axes[1].scatter(
                [index],
                [100.0 * case["analyzer_metrics"]["detector_hit_fraction_of_rf_exit"]],
                color=COLORS[index],
                marker=MARKERS[index],
                s=32,
            )
            axes[2].errorbar(
                [index],
                [case["analyzer_metrics"]["mean_analyzer_tof_us"]],
                yerr=[case["analyzer_metrics"]["sample_sigma_analyzer_tof_ns"] / 1000.0],
                color=COLORS[index],
                marker=MARKERS[index],
                linestyle="none",
                capsize=3,
                markersize=5,
            )
        axes[0].set_xticks(x_stage, STAGE_LABELS, rotation=30, ha="right")
        axes[0].set_ylabel("Cumulative retention (% of RF exit)")
        axes[0].set_ylim(0.0, 105.0)
        axes[0].set_title("(a) Stage retention")
        short_labels = [f"Case {index + 1}" for index in x_case]
        axes[1].set_xticks(x_case, short_labels)
        axes[1].set_ylabel("Detector hits (% of RF exit)")
        axes[1].set_ylim(bottom=0.0)
        axes[1].set_title("(b) End-to-end hit fraction")
        axes[2].set_xticks(x_case, short_labels)
        axes[2].set_ylabel("Analyzer TOF (µs)\nmean ± sample σ")
        axes[2].set_title("(c) Hit TOF")
        for axis in axes:
            axis.grid(axis="y", color="#D9D9D9", linewidth=0.6)
            axis.set_axisbelow(True)
        handles, labels = axes[0].get_legend_handles_labels()
        figure.legend(
            handles,
            labels,
            loc="outside upper center",
            ncol=min(len(cases), 2),
            frameon=False,
        )
        return figure, axes


def _write_text_atomic(path: Path, text: str) -> None:
    pending = path.with_name(f".{path.name}.pending")
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_text(text, encoding="utf-8", newline="\n")
    os.replace(pending, path)


def _render_report_markdown(cases: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# Multipole→oaTOF campaign descriptive comparison",
        "",
        "> This is a post-hoc descriptive functional screen. The selected parent runs do not share a controlled comparison or equivalence contract. The table must not be used to rank performance, claim equivalence, numerical convergence, Candidate status, or Formal qualification.",
        "",
        "| Case | RF→entry→pulse→local exit→crossing→hit | Hit / RF exit | Analyzer TOF mean ± sample σ (µs) | Gaussian FWHM proxy (ns) | Max hit radius (mm) |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for case in cases:
        census = case["census"]
        metrics = case["analyzer_metrics"]
        chain = "→".join(str(census[stage]) for stage in STAGES)
        lines.append(
            "| {label} | `{chain}` | {hit:.2f}% | {mean:.6f} ± {sigma:.6f} | {fwhm:.3f} | {radius:.3f} |".format(
                label=case["label"],
                chain=chain,
                hit=100.0 * metrics["detector_hit_fraction_of_rf_exit"],
                mean=metrics["mean_analyzer_tof_us"],
                sigma=metrics["sample_sigma_analyzer_tof_ns"] / 1000.0,
                fwhm=metrics["gaussian_fwhm_tof_proxy_ns"],
                radius=metrics["maximum_hit_radius_mm"],
            )
        )
    lines.extend(
        [
            "",
            "The normalization denominator is each run's own RF-exit cohort. TOF statistics use detector hits only; no rows were removed beyond the existing `Hit=true` event classification. The FWHM value is `2.3548 × sample σ`, not a direct measured FWHM, and the detector-hit counts are too small for a resolution qualification.",
            "",
            "Result: `INCONCLUSIVE_DIAGNOSTIC_ONLY`.",
            "",
        ]
    )
    return "\n".join(lines)


def _comparability(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    fields = {
        "campaign_id": "campaign",
        "experiment_id": "experiment",
        "source_project_id": "multipole_family_or_source_project",
        "connection_profile_id": "connection_profile",
        "source_run_id": "source_run",
    }
    differing = [
        label
        for field, label in fields.items()
        if len({str(case.get(field)) for case in cases}) > 1
    ]
    if len({case["census"]["rf_exit"] for case in cases}) > 1:
        differing.append("rf_exit_cohort_size")
    return {
        "performance_ranking_allowed": False,
        "controlled_comparison_contract_supplied": False,
        "differing_declared_axes": differing,
        "reason": (
            "selected parent runs were not supplied with a controlled comparison "
            "or equivalence contract"
        ),
    }


def _export_figure(
    *,
    cases: Sequence[Mapping[str, Any]],
    output: Path,
    figure_manifest: Path,
    repo_root: Path | None = None,
) -> None:
    import matplotlib.pyplot as plt

    figure, _ = build_campaign_comparison_figure(cases)
    pending = output.with_name(f".{output.name}.pending")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        figure.savefig(pending, format="png", dpi=300, facecolor="white")
    finally:
        plt.close(figure)
    os.replace(pending, output)
    write_pending_json(
        figure_manifest,
        {
            "schema_version": 1,
            "role": "rf_multipole_oatof_campaign_comparison_figure_manifest",
            "purpose": "posthoc descriptive comparison of normalized stage retention and analyzer hit TOF",
            "figure": _manifest_reference(output),
            "git": _git_identity(repo_root),
            "source_runs": [
                {
                    "label": case["label"],
                    "run_id": case["parent_run_id"],
                    "parent_manifest": case["inputs"]["parent_manifest"],
                    "terminal_manifest": case["inputs"]["terminal_manifest"],
                }
                for case in cases
            ],
            "dimensions_mm": {"width": 183, "height": 90},
            "format": "PNG",
            "dpi": 300,
            "style_profile": "publication_double",
            "units": {
                "cumulative_retention": "percent of per-case RF-exit count",
                "detector_hit_fraction": "percent of per-case RF-exit count",
                "analyzer_tof": "microsecond",
            },
            "category_encoding": {
                case["label"]: {
                    "color": COLORS[index],
                    "marker": MARKERS[index],
                    "line_style": LINESTYLES[index],
                }
                for index, case in enumerate(cases)
            },
            "normalization": "cumulative count divided by each case's RF-exit count",
            "tof_statistic": "detector-hit analyzer TofUs mean plus/minus sample standard deviation (ddof=1)",
            "filter": "existing detector event classification Hit=true only",
            "binning": None,
            "fit": None,
            "qualification_decision_made": False,
        },
    )


def publish_campaign_comparison_run(
    *, repo_root: Path, run_id: str, cases: Sequence[tuple[str, str]]
) -> Path:
    """Validate completed parents and publish one compact descriptive analysis run."""
    repo_root = repo_root.resolve()
    workspace_root = repo_root.parent
    try:
        validate_run_id(run_id)
    except ValueError as error:
        raise ContractError("campaign comparison run_id is invalid") from error
    if len(cases) < 2 or len(cases) > len(COLORS):
        raise ContractError("campaign comparison requires two to four cases")
    labels = [label.strip() for label, _ in cases]
    parent_ids = [parent for _, parent in cases]
    if len(set(labels)) != len(labels) or len(set(parent_ids)) != len(parent_ids):
        raise ContractError("campaign comparison labels and parent runs must be unique")
    runs_root = (
        workspace_root / "artifacts" / "projects" / INTEGRATION_ID / "runs"
    ).resolve()
    run_dir = (runs_root / run_id).resolve()
    if run_dir.parent != runs_root or run_dir.exists():
        raise ContractError("campaign comparison output already exists or is invalid")
    case_inputs = [
        _load_case_inputs(
            repo_root=repo_root,
            workspace_root=workspace_root,
            runs_root=runs_root,
            label=label,
            parent_run_id=parent_id,
        )
        for label, parent_id in cases
    ]
    request_path = run_dir / "inputs" / "campaign_comparison_request.json"
    result_path = run_dir / "results" / "campaign_comparison.json"
    report_path = run_dir / "results" / "campaign_comparison.md"
    figure_path = run_dir / "results" / "campaign_comparison.png"
    figure_manifest_path = run_dir / "results" / "campaign_comparison.figure.json"
    run_config_path = run_dir / "run_config.json"
    summary_path = run_dir / "summary.json"
    manifest_path = run_dir / "run_manifest.json"
    implementation_path = repo_root / IMPLEMENTATION_RELATIVE_PATH
    requirements_lock = repo_root / "requirements-lock.txt"
    if not implementation_path.is_file() or not requirements_lock.is_file():
        raise ContractError("campaign comparison implementation inputs are missing")
    request = {
        "schema_version": 1,
        "role": REQUEST_ROLE,
        "integration_id": INTEGRATION_ID,
        "cases": [
            {
                "label": case.label,
                "parent_run_id": case.parent_run_id,
                "parent_manifest": _manifest_reference(case.parent_manifest),
            }
            for case in case_inputs
        ],
        "analysis_class": "POSTHOC_DESCRIPTIVE",
        "qualification_decision_made": False,
    }
    input_paths: dict[str, Path] = {
        "campaign_comparison_request": request_path,
        "campaign_comparison_implementation": implementation_path,
        "requirements_lock": requirements_lock,
    }
    for index, case in enumerate(case_inputs, start=1):
        input_paths.update(
            {
                f"case_{index}_parent_manifest": case.parent_manifest,
                f"case_{index}_parent_summary": case.parent_summary,
                f"case_{index}_terminal_manifest": case.terminal_manifest,
                f"case_{index}_terminal_metrics": case.terminal_metrics,
                f"case_{index}_downstream_particles": case.downstream_particles,
            }
        )
    run_config: dict[str, Any] = {
        "schema_version": 2,
        "run_id": run_id,
        "project": INTEGRATION_ID,
        "mode": OUTPUT_MODE,
        "project_root": str(workspace_root),
        "inputs": {},
        "parameters": {
            "case_count": len(case_inputs),
            "parent_run_ids": parent_ids,
            "analysis_class": "POSTHOC_DESCRIPTIVE",
            "retention_denominator": "per_case_rf_exit",
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
        "schema_version": 1,
        "role": SUMMARY_ROLE,
        "analysis_class": "POSTHOC_DESCRIPTIVE",
        "case_count": len(case_inputs),
        "parent_run_ids": parent_ids,
        "acceptance_thresholds_applied": False,
        "qualification_decision_made": False,
        "formal_gate_passed": False,
    }

    run_dir.mkdir(parents=True, exist_ok=False)
    write_pending_json(request_path, request)
    frozen_inputs = freeze_repository_inputs(
        input_paths, repo_root=repo_root, run_dir=run_dir
    )
    run_config["inputs"] = {
        name: portable_path(path, workspace_root)
        for name, path in sorted(frozen_inputs.items())
    }
    write_pending_json(run_config_path, run_config)
    interrupted_summary = {
        **summary_base,
        "status": "interrupted",
        "analysis_status": "NOT_RUN",
        "result": None,
        "report": None,
        "figure": None,
    }
    write_pending_json(summary_path, interrupted_summary)
    manifest_pending = manifest_path.with_name(".run_manifest.json.pending")
    _publish_analysis_manifest(
        repo_root=repo_root,
        run_config=run_config_path,
        manifest_path=manifest_pending,
        status="interrupted",
        outputs=(summary_path,),
    )
    os.replace(manifest_pending, manifest_path)
    interrupted_summary_bytes = summary_path.read_bytes()
    interrupted_manifest_bytes = manifest_path.read_bytes()
    planned_outputs = (
        result_path,
        report_path,
        figure_path,
        figure_manifest_path,
        summary_path,
    )

    failure_stage = "case_analysis"
    try:
        case_results = [_compute_case(case) for case in case_inputs]
        result = {
            "schema_version": 1,
            "role": OUTPUT_ROLE,
            "status": "INCONCLUSIVE_DIAGNOSTIC_ONLY",
            "analysis_class": "POSTHOC_DESCRIPTIVE",
            "comparability": _comparability(case_results),
            "acceptance_thresholds_applied": False,
            "qualification_decision_made": False,
            "cases": case_results,
        }
        failure_stage = "result_publication"
        write_pending_json(result_path, result)
        _write_text_atomic(report_path, _render_report_markdown(case_results))
        failure_stage = "figure_publication"
        _export_figure(
            cases=case_results,
            output=figure_path,
            figure_manifest=figure_manifest_path,
            repo_root=repo_root,
        )
        summary = {
            **summary_base,
            "status": "success",
            "analysis_status": "INCONCLUSIVE_DIAGNOSTIC_ONLY",
            "result": "results/campaign_comparison.json",
            "report": "results/campaign_comparison.md",
            "figure": "results/campaign_comparison.png",
        }
        write_pending_json(summary_path, summary)
        failure_stage = "success_manifest_publication"
        _publish_analysis_manifest(
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
        restore_interrupted(
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
            "analysis_status": "FAILED",
            "result": "results/campaign_comparison.json" if result_path.is_file() else None,
            "report": "results/campaign_comparison.md" if report_path.is_file() else None,
            "figure": "results/campaign_comparison.png" if figure_path.is_file() else None,
            "failure_stage": failure_stage,
            "reason": str(error),
            "error_type": type(error).__name__,
        }
        terminalize_failure(
            publish=_publish_analysis_manifest,
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
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--case",
        action="append",
        nargs=2,
        metavar=("LABEL", "PARENT_RUN_ID"),
        required=True,
    )
    args = parser.parse_args()
    manifest = publish_campaign_comparison_run(
        repo_root=args.repo_root,
        run_id=args.run_id,
        cases=[tuple(item) for item in args.case],
    )
    print(
        "CAMPAIGN_COMPARISON=PASS STATUS=INCONCLUSIVE_DIAGNOSTIC_ONLY "
        f"MANIFEST={manifest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
