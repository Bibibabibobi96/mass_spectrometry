"""Summarize paired multipole campaign exit states without making a qualification claim."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any

from common.contracts.file_identity import file_sha256 as _sha256
from common.contracts.machine_contracts import ContractError, validate_schema
from common.contracts.verify_run_manifest import record_path
from common.multipole.campaign_status import _verify_manifest as verify_campaign_manifest
from common.multipole.numerical_qualification import run_data


MODES = {
    "no_acceleration",
    "no_acceleration_5ev",
    "segmented_acceleration",
    "exit_aperture_plate_acceleration",
}
PAIR_DEFINITIONS = (
    (
        "initial_5ev_vs_initial_2ev",
        "no_acceleration",
        "no_acceleration_5ev",
    ),
    (
        "segmented_vs_no_acceleration",
        "no_acceleration",
        "segmented_acceleration",
    ),
    (
        "exit_aperture_plate_vs_no_acceleration",
        "no_acceleration",
        "exit_aperture_plate_acceleration",
    ),
    (
        "exit_aperture_plate_vs_segmented",
        "segmented_acceleration",
        "exit_aperture_plate_acceleration",
    ),
    (
        "segmented_vs_initial_5ev",
        "no_acceleration_5ev",
        "segmented_acceleration",
    ),
)

CATALOG_ROLE = "multipole_campaign_analysis_capability_catalog"
PREFLIGHT_ROLE = "multipole_campaign_analysis_preflight"


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _resolve_catalog_module(repo_root: Path, module: str) -> str:
    prefix = "common.multipole."
    leaf = module.removeprefix(prefix)
    if not module.startswith(prefix) or not leaf.isidentifier() or "." in leaf:
        raise ValueError(f"analysis capability module is outside common.multipole: {module}")
    if not (repo_root / Path(*module.split("."))).with_suffix(".py").is_file():
        raise ValueError(f"analysis capability module is missing: {module}")
    return module


def _verify_manifest_cli(
    path: Path,
    *,
    repo_root: Path,
    project_id: str,
    run_id: str,
    mode: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    command = [
        sys.executable, "-m", "common.contracts.verify_run_manifest", str(path),
        "--require-status", "success", "--require-project", project_id,
        "--require-run-id", run_id, "--require-local-run-config",
    ]
    if mode is not None:
        command.extend(("--require-mode", mode))
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        cwd=repo_root,
        timeout=60,
    )
    if completed.returncode:
        raise ValueError("run manifest verification failed")
    manifest = _load_json(path)
    config = _load_json(record_path(manifest["run_config"], base_dir=path.parent))
    return manifest, config


def _source_binding(
    status_row: dict[str, Any],
    row: dict[str, Any],
    capability: dict[str, Any],
    *,
    campaign_id: str,
    campaign_sha256: str,
) -> tuple[str, str, dict[str, Any] | None]:
    if status_row["status"] == "NOT_STARTED":
        return "PENDING", "source run is not present", None
    if status_row["status"] != "SUCCESS":
        return "FAILED", status_row.get("reason", f"source run status is {status_row['status']}"), None
    manifest_path = Path(status_row["manifest"]).resolve()
    run_dir = manifest_path.parent
    try:
        manifest = _load_json(manifest_path)
        config = _load_json(record_path(manifest["run_config"], base_dir=run_dir))
        if manifest.get("role") != capability["input_roles"]["source_run_manifest"]:
            raise ValueError("source run manifest role differs")
        provenance = config.get("provenance", {})
        parameters = config.get("parameters", {})
        expected = (
            provenance.get("runtime_selection_kind") == "campaign_experiment"
            and provenance.get("campaign_id") == campaign_id
            and provenance.get("campaign_sha256") == campaign_sha256
            and provenance.get("experiment_id") == row["experiment_id"]
            and parameters.get("experiment_id") == row["experiment_id"]
        )
        if not expected:
            raise ValueError("source run campaign binding differs")
        figure_records = [
            record
            for record in manifest.get("outputs", [])
            if record_path(record, base_dir=run_dir).name
            == "exit_state_diagnostics.json"
        ]
        if len(figure_records) != 1:
            raise ValueError("source figure manifest output is not unique")
        figure_path = record_path(figure_records[0], base_dir=run_dir)
        if not figure_path.is_relative_to(run_dir):
            raise ValueError("source figure manifest escapes its run")
        figure = _load_json(figure_path)
        if (
            figure.get("role") != capability["input_roles"]["source_figure_manifest"]
            or len(figure.get("series", [])) != 1
        ):
            raise ValueError("source figure manifest identity differs")
        series = figure["series"][0]
        if series.get("run_id") != row["authorized_run_id"]:
            raise ValueError("source figure run identity differs")
        state_record = series.get("canonical_state", {})
        state_path = Path(str(state_record.get("path", "")))
        if not state_path.is_absolute():
            state_path = figure_path.parent / state_path
        state_path = state_path.resolve()
        if not state_path.is_file() or not state_path.is_relative_to(run_dir):
            raise ValueError("source state is missing or escapes its run")
        state_sha256 = _sha256(state_path)
        if state_sha256 != str(state_record.get("sha256", "")).upper():
            raise ValueError("source state SHA-256 differs")
        state_outputs = [
            record
            for record in manifest.get("outputs", [])
            if record_path(record, base_dir=run_dir) == state_path
        ]
        if len(state_outputs) != 1:
            raise ValueError("source state is not uniquely frozen by its run manifest")
    except (AssertionError, KeyError, OSError, TypeError, ValueError) as error:
        return "FAILED", str(error), None
    return (
        "READY",
        "verified success source run",
        {
            "experiment_id": row["experiment_id"],
            "project_id": row["project_id"],
            "run_id": row["authorized_run_id"],
            "run_manifest_path": str(manifest_path),
            "figure_manifest_path": str(figure_path),
            "state_path": str(state_path),
            "state_sha256": state_sha256,
        },
    )


def _existing_analysis_state(
    run_dir: Path,
    *,
    repo_root: Path,
    project_id: str,
    run_id: str,
    mode: str,
    campaign_sha256: str,
    catalog_sha256: str,
    request: dict[str, Any],
    capability: dict[str, Any],
) -> tuple[str, str]:
    if not run_dir.exists():
        return "ABSENT", "analysis run is not present"
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.is_file():
        return "FAILED", "analysis run has no manifest"
    try:
        manifest, config = _verify_manifest_cli(
            manifest_path,
            repo_root=repo_root,
            project_id=project_id,
            run_id=run_id,
            mode=mode,
        )
        provenance = config.get("provenance", {})
        parameters = config.get("parameters", {})
        if (
            provenance.get("campaign_sha256") != campaign_sha256
            or provenance.get("analysis_capability_catalog_sha256")
            != catalog_sha256
            or parameters.get("capability_id") != request["capability_id"]
            or parameters.get("baseline_experiment_id")
            != request["baseline_experiment_id"]
        ):
            raise ValueError("analysis run binding differs")
        recorded = {
            record_path(record, base_dir=run_dir)
            for record in manifest.get("outputs", [])
        }
        required = {
            (run_dir / relative).resolve()
            for relative in capability["fixed_output_roles"].values()
        }
        if not required.issubset(recorded):
            raise ValueError("analysis output role is not frozen")
    except (AssertionError, KeyError, OSError, TypeError, ValueError) as error:
        return "FAILED", str(error)
    return "COMPLETE", "verified success analysis run"


def campaign_request_preflight(
    repo_root: Path, workspace_root: Path, campaign_path: Path
) -> dict[str, Any]:
    """Validate v4 analysis requests and return a read-only normalized execution plan."""

    repo_root = repo_root.resolve()
    workspace_root = workspace_root.resolve()
    campaign_path = campaign_path.resolve()
    campaign_root = (repo_root / "common" / "multipole" / "campaigns").resolve()
    if not campaign_path.is_file() or not campaign_path.is_relative_to(campaign_root):
        raise ValueError("campaign path must name a file in common/multipole/campaigns")
    campaign = _load_json(campaign_path)
    try:
        validate_schema(campaign, "multipole_transport_experiment_campaign.schema.json")
    except ContractError as error:
        raise ValueError(f"invalid multipole transport campaign: {error}") from error
    status_by_experiment = {}
    for row in campaign["experiments"]:
        run_dir = workspace_root / "artifacts" / "projects" / row["project_id"] / "runs" / row["authorized_run_id"]
        manifest_path = run_dir / "run_manifest.json"
        if not run_dir.is_dir():
            status, manifest, reason = "NOT_STARTED", None, "source run is not present"
        elif not manifest_path.is_file():
            status, manifest, reason = "PRESENT_WITHOUT_MANIFEST", None, "source run has no manifest"
        else:
            try:
                status, manifest = verify_campaign_manifest(
                    manifest_path, project_id=row["project_id"], run_id=row["authorized_run_id"]
                )
                reason = f"source run status is {status}"
            except (AssertionError, KeyError, OSError, TypeError, ValueError) as error:
                status, manifest, reason = "INVALID_MANIFEST", str(manifest_path), str(error)
        status_by_experiment[row["experiment_id"]] = {
            "status": status, "manifest": manifest, "reason": reason
        }
    if campaign["schema_version"] != 4:
        return {
            "schema_version": 1,
            "role": PREFLIGHT_ROLE,
            "campaign_id": campaign["campaign_id"],
            "campaign_path": str(campaign_path),
            "campaign_sha256": _sha256(campaign_path),
            "analyses": [],
        }
    catalog_path = repo_root / "common" / "multipole" / "analysis_capabilities.json"
    catalog = _load_json(catalog_path)
    if catalog.get("schema_version") != 1 or catalog.get("role") != CATALOG_ROLE:
        raise ValueError("analysis capability catalog identity differs")
    capability_ids = [item["capability_id"] for item in catalog["capabilities"]]
    if len(capability_ids) != len(set(capability_ids)):
        raise ValueError("analysis capability IDs are not unique")
    rows_by_id = {row["experiment_id"]: row for row in campaign["experiments"]}
    if len(rows_by_id) != len(campaign["experiments"]):
        raise ValueError("campaign experiment IDs are not unique")
    run_ids = [request["analysis_run_id"] for request in campaign["analysis_requests"]]
    if len(run_ids) != len(set(run_ids)):
        raise ValueError("analysis run IDs are not unique")
    campaign_sha256 = _sha256(campaign_path)
    catalog_sha256 = _sha256(catalog_path)
    analyses = []
    for request in campaign["analysis_requests"]:
        matches = [
            item
            for item in catalog["capabilities"]
            if item["capability_id"] == request["capability_id"]
        ]
        if len(matches) != 1:
            raise ValueError(f"Unknown analysis capability: {request['capability_id']}")
        capability = matches[0]
        modules = {
            name: _resolve_catalog_module(repo_root, module)
            for name, module in capability["consumer"].items()
        }
        references = request["experiment_ids"]
        if not (
            capability["series_count"]["minimum"]
            <= len(references)
            <= capability["series_count"]["maximum"]
        ):
            raise ValueError("analysis series count is outside its capability envelope")
        if request["baseline_experiment_id"] not in references:
            raise ValueError("analysis baseline is not one of its experiment_ids")
        try:
            rows = [rows_by_id[experiment_id] for experiment_id in references]
        except KeyError as error:
            raise ValueError(
                f"analysis references a missing campaign experiment: {error.args[0]}"
            ) from error
        baseline = rows_by_id[request["baseline_experiment_id"]]
        for row in rows:
            if row["project_id"] not in capability["allowed_projects"]:
                raise ValueError(f"analysis project is outside capability: {row['project_id']}")
            if row["solver"] not in capability["allowed_solvers"]:
                raise ValueError(f"analysis solver is outside capability: {row['solver']}")
            for field in capability["required_consistency"]:
                if field == "campaign_id":
                    continue
                if field not in row or field not in baseline:
                    raise ValueError(f"required consistency field is missing: {field}")
                if row[field] != baseline[field]:
                    raise ValueError(f"analysis consistency differs for {field}")
        supplied = request["parameters"]
        unknown = set(supplied).difference(capability["allowed_parameters"])
        if unknown:
            raise ValueError(f"analysis parameter is not allowed: {sorted(unknown)[0]}")
        parameters = {}
        for name, definition in capability["allowed_parameters"].items():
            value = supplied.get(name, definition["default"])
            if definition["type"] != "integer" or type(value) is not int:
                raise ValueError(f"analysis parameter type differs: {name}")
            if not definition["minimum"] <= value <= definition["maximum"]:
                raise ValueError(f"analysis parameter is outside its capability envelope: {name}")
            parameters[name] = value
        project_id = baseline["project_id"]
        run_id = request["analysis_run_id"]
        mode = f"multipole_campaign_{request['capability_id']}"
        run_dir = (
            workspace_root / "artifacts" / "projects" / project_id / "runs" / run_id
        ).resolve()
        status, reason = _existing_analysis_state(
            run_dir,
            repo_root=repo_root,
            project_id=project_id,
            run_id=run_id,
            mode=mode,
            campaign_sha256=campaign_sha256,
            catalog_sha256=catalog_sha256,
            request=request,
            capability=capability,
        )
        sources = []
        if status == "ABSENT":
            source_states = [
                _source_binding(
                    status_by_experiment[row["experiment_id"]],
                    row,
                    capability,
                    campaign_id=campaign["campaign_id"],
                    campaign_sha256=campaign_sha256,
                )
                for row in rows
            ]
            failed = next((item for item in source_states if item[0] == "FAILED"), None)
            if failed:
                status, reason = "FAILED", failed[1]
            elif any(item[0] != "READY" for item in source_states):
                status, reason = "PENDING", "referenced simulations are not all complete"
            else:
                status, reason = "READY", "all referenced simulations are verified success"
                sources = [item[2] for item in source_states]
        analyses.append(
            {
                "status": status,
                "reason": reason,
                "capability_id": request["capability_id"],
                "analysis_run_id": run_id,
                "baseline_experiment_id": request["baseline_experiment_id"],
                "experiment_ids": references,
                "project_id": project_id,
                "mode": mode,
                "parameters": parameters,
                "consumer": modules,
                "fixed_settings": capability["fixed_settings"],
                "fixed_output_roles": capability["fixed_output_roles"],
                "claim_class": capability["claim_class"],
                "sources": sources,
            }
        )
    return {
        "schema_version": 1,
        "role": PREFLIGHT_ROLE,
        "campaign_id": campaign["campaign_id"],
        "campaign_path": str(campaign_path),
        "campaign_sha256": campaign_sha256,
        "catalog_path": str(catalog_path.resolve()),
        "catalog_sha256": catalog_sha256,
        "analyses": analyses,
    }


def _mean(values: list[float]) -> float:
    return math.fsum(values) / len(values)


def _rms_about(values: list[float], center: float) -> float:
    return math.sqrt(math.fsum((value - center) ** 2 for value in values) / len(values))


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * probability
    low, high = math.floor(index), math.ceil(index)
    if low == high:
        return ordered[low]
    fraction = index - low
    return ordered[low] + fraction * (ordered[high] - ordered[low])


def _correlation(left: list[float], right: list[float]) -> float | None:
    left_mean, right_mean = _mean(left), _mean(right)
    numerator = math.fsum(
        (x - left_mean) * (y - right_mean)
        for x, y in zip(left, right, strict=True)
    )
    left_norm = math.sqrt(math.fsum((x - left_mean) ** 2 for x in left))
    right_norm = math.sqrt(math.fsum((y - right_mean) ** 2 for y in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return None
    return numerator / (left_norm * right_norm)


def summarize_run(data: dict[str, Any]) -> dict[str, Any]:
    """Return centroid/deviation/tail metrics for the canonical handoff population."""

    rows = list(data["_handoff"].values())
    if not rows:
        raise ValueError("run has no handoff rows")
    values = {
        name: [float(row[name]) for row in rows]
        for name in (
            "transverse_x_mm",
            "transverse_y_mm",
            "radial_position_mm",
            "divergence_angle_deg",
            "kinetic_energy_eV",
            "elapsed_time_us",
            "velocity_axial_m_s",
            "velocity_x_m_s",
            "velocity_y_m_s",
        )
    }
    theta_x = [
        math.degrees(math.atan2(vx, axial))
        for vx, axial in zip(
            values["velocity_x_m_s"], values["velocity_axial_m_s"], strict=True
        )
    ]
    theta_y = [
        math.degrees(math.atan2(vy, axial))
        for vy, axial in zip(
            values["velocity_y_m_s"], values["velocity_axial_m_s"], strict=True
        )
    ]
    observables = data["observables"]
    direction_tilt = math.degrees(
        math.acos(
            max(-1.0, min(1.0, float(observables["mean_beam_direction_unit_z"])))
        )
    )
    energy_mean = _mean(values["kinetic_energy_eV"])
    time_mean = _mean(values["elapsed_time_us"])
    provenance = data["config"].get("provenance", {})
    return {
        "run_id": data["run_id"],
        "project_id": data["project"],
        "solver": data["solver"],
        "particle_source_sha256": data["particle_source_sha256"],
        "particle_source_authority_sha256": provenance.get(
            "particle_source_authority_sha256", data["particle_source_sha256"]
        ),
        "physical_resolved_design_sha256": data[
            "physical_resolved_design_sha256"
        ],
        "campaign_id": provenance.get("campaign_id"),
        "experiment_id": provenance.get("experiment_id"),
        "transmitted_particles": len(rows),
        "transmission": float(observables["transmission"]),
        "centroid_x_mm": float(observables["transverse_centroid_x_mm"]),
        "centroid_y_mm": float(observables["transverse_centroid_y_mm"]),
        "centered_spatial_rms_spread_mm": float(
            observables["centered_spatial_rms_spread_mm"]
        ),
        "mean_direction_tilt_deg": direction_tilt,
        "mean_direction_x_deg": _mean(theta_x),
        "mean_direction_y_deg": _mean(theta_y),
        "centered_angular_rms_spread_deg": float(
            observables["centered_angular_rms_spread_deg"]
        ),
        "mean_energy_eV": energy_mean,
        "centered_rms_energy_spread_eV": _rms_about(
            values["kinetic_energy_eV"], energy_mean
        ),
        "mean_elapsed_time_us": time_mean,
        "centered_rms_elapsed_time_spread_us": _rms_about(
            values["elapsed_time_us"], time_mean
        ),
        "p95_radius_mm": _percentile(values["radial_position_mm"], 0.95),
        "p99_radius_mm": _percentile(values["radial_position_mm"], 0.99),
        "p95_divergence_deg": _percentile(
            values["divergence_angle_deg"], 0.95
        ),
        "p99_divergence_deg": _percentile(
            values["divergence_angle_deg"], 0.99
        ),
        "position_angle_correlation_x": _correlation(
            values["transverse_x_mm"], theta_x
        ),
        "position_angle_correlation_y": _correlation(
            values["transverse_y_mm"], theta_y
        ),
    }


SERIES_DELTA_FIELDS = (
    "transmission",
    "centered_spatial_rms_spread_mm",
    "mean_direction_tilt_deg",
    "centered_angular_rms_spread_deg",
    "mean_energy_eV",
    "centered_rms_energy_spread_eV",
    "mean_elapsed_time_us",
    "centered_rms_elapsed_time_spread_us",
    "p95_radius_mm",
    "p99_radius_mm",
    "p95_divergence_deg",
    "p99_divergence_deg",
)


def compare_to_baseline(
    baseline: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    """Compare a governed campaign series to its declared baseline."""

    return {
        "baseline_run_id": baseline["run_id"],
        "candidate_run_id": candidate["run_id"],
        "centroid_shift_mm": math.hypot(
            _delta(baseline, candidate, "centroid_x_mm"),
            _delta(baseline, candidate, "centroid_y_mm"),
        ),
        "candidate_minus_baseline": {
            field: _delta(baseline, candidate, field)
            for field in SERIES_DELTA_FIELDS
        },
    }


def analyze_series(
    entries: list[tuple[str, Path]], baseline_label: str
) -> dict[str, Any]:
    """Summarize one declared campaign variable matrix without qualifying it."""

    if not entries:
        raise ValueError("campaign series must not be empty")
    labels = [label for label, _ in entries]
    if any(not label for label in labels) or len(labels) != len(set(labels)):
        raise ValueError("campaign series labels must be non-empty and unique")
    if baseline_label not in labels:
        raise ValueError("declared baseline label is absent from campaign series")

    loaded = [(label, run_data(manifest)) for label, manifest in entries]
    reference = loaded[0][1]
    reference_provenance = reference["config"].get("provenance", {})
    reference_authority = reference_provenance.get(
        "particle_source_authority_sha256", reference["particle_source_sha256"]
    )
    reference_basis = reference_provenance.get("simion_pa_basis", {}).get(
        "fingerprint_sha256"
    )
    campaign_ids = {
        reference_provenance.get("campaign_id")
    }
    for label, data in loaded[1:]:
        provenance = data["config"].get("provenance", {})
        authority = provenance.get(
            "particle_source_authority_sha256", data["particle_source_sha256"]
        )
        if data["project"] != reference["project"] or data["solver"] != reference["solver"]:
            raise ValueError(f"campaign series {label} differs in project or solver")
        basis = provenance.get("simion_pa_basis", {}).get("fingerprint_sha256")
        if not reference_basis or basis != reference_basis:
            raise ValueError(f"campaign series {label} differs in SIMION PA basis")
        if data["source_particle_ids"] != reference["source_particle_ids"]:
            raise ValueError(f"campaign series {label} differs in source particle-ID cohort")
        if authority != reference_authority:
            raise ValueError(f"campaign series {label} differs in source authority")
        campaign_ids.add(provenance.get("campaign_id"))

    series = []
    by_label: dict[str, dict[str, Any]] = {}
    for label, data in loaded:
        summary = summarize_run(data)
        summary["label"] = label
        series.append(summary)
        by_label[label] = summary
    baseline = by_label[baseline_label]
    return {
        "schema_version": 1,
        "role": "multipole_campaign_variable_series_summary",
        "analysis_class": "POSTHOC_DESCRIPTIVE",
        "baseline_label": baseline_label,
        "identity": {
            "project_id": reference["project"],
            "solver": reference["solver"],
            "campaign_ids": sorted(
                campaign_id for campaign_id in campaign_ids if campaign_id
            ),
            "particle_source_authority_sha256": reference_authority,
            "simion_pa_basis_fingerprint_sha256": reference_basis,
            "source_particle_ids": reference["source_particle_ids"],
        },
        "series": series,
        "comparisons": {
            label: compare_to_baseline(baseline, by_label[label])
            for label in labels
            if label != baseline_label
        },
        "claim_limit": (
            "Descriptive campaign handoff diagnostics only; not a convergence, "
            "optimization, solver-equivalence, Candidate, or Formal claim."
        ),
    }


def series_markdown_report(document: dict[str, Any]) -> str:
    lines = [
        "# 多极杆 campaign 变量矩阵出口状态对照",
        "",
        "本报告使用规范 handoff 事件，并以声明的 baseline 给出差值。",
        "",
        "|系列|透射|质心 x / y (mm)|空间 RMS (mm)|平均方向 (°)|角 RMS (°)|平均能量 / 展宽 (eV)|p95 / p99 半径 (mm)|p95 / p99 角度 (°)|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in document["series"]:
        lines.append(
            "|{label}|{transmission:.3f}|{centroid_x_mm:.4f} / {centroid_y_mm:.4f}|"
            "{centered_spatial_rms_spread_mm:.4f}|{mean_direction_tilt_deg:.4f}|"
            "{centered_angular_rms_spread_deg:.4f}|{mean_energy_eV:.4f} / "
            "{centered_rms_energy_spread_eV:.4f}|{p95_radius_mm:.4f} / "
            "{p99_radius_mm:.4f}|{p95_divergence_deg:.4f} / "
            "{p99_divergence_deg:.4f}|".format(**item)
        )
    lines.extend(
        [
            "",
            f"Baseline：`{document['baseline_label']}`。正差值表示候选更大。",
            "",
            "|系列|透射 Δ|质心位移 (mm)|空间 RMS Δ (mm)|角 RMS Δ (°)|平均能量 Δ (eV)|能量展宽 Δ (eV)|p95 半径 Δ (mm)|p95 角度 Δ (°)|",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for label, comparison in document["comparisons"].items():
        delta = comparison["candidate_minus_baseline"]
        lines.append(
            f"|{label}|{delta['transmission']:.3f}|"
            f"{comparison['centroid_shift_mm']:.4f}|"
            f"{delta['centered_spatial_rms_spread_mm']:.4f}|"
            f"{delta['centered_angular_rms_spread_deg']:.4f}|"
            f"{delta['mean_energy_eV']:.4f}|"
            f"{delta['centered_rms_energy_spread_eV']:.4f}|"
            f"{delta['p95_radius_mm']:.4f}|"
            f"{delta['p95_divergence_deg']:.4f}|"
        )
    lines.extend(["", f"声明边界：{document['claim_limit']}", ""])
    return "\n".join(lines)


def _delta(left: dict[str, Any], right: dict[str, Any], field: str) -> float:
    return float(right[field]) - float(left[field])


def compare_pair(
    no_acceleration: dict[str, Any],
    segmented: dict[str, Any],
) -> dict[str, Any]:
    if (
        no_acceleration["project_id"] != segmented["project_id"]
        or no_acceleration.get(
            "particle_source_authority_sha256",
            no_acceleration["particle_source_sha256"],
        )
        != segmented.get(
            "particle_source_authority_sha256",
            segmented["particle_source_sha256"],
        )
    ):
        raise ValueError("paired campaign arms differ in project or particle source")
    centroid_shift = math.hypot(
        _delta(no_acceleration, segmented, "centroid_x_mm"),
        _delta(no_acceleration, segmented, "centroid_y_mm"),
    )
    fields = (
        "transmission",
        "centered_spatial_rms_spread_mm",
        "mean_direction_tilt_deg",
        "centered_angular_rms_spread_deg",
        "mean_energy_eV",
        "centered_rms_energy_spread_eV",
        "mean_elapsed_time_us",
        "centered_rms_elapsed_time_spread_us",
        "p95_radius_mm",
        "p99_radius_mm",
        "p95_divergence_deg",
        "p99_divergence_deg",
    )
    return {
        "no_acceleration_run_id": no_acceleration["run_id"],
        "segmented_acceleration_run_id": segmented["run_id"],
        "centroid_shift_mm": centroid_shift,
        "segmented_minus_no_acceleration": {
            field: _delta(no_acceleration, segmented, field) for field in fields
        },
    }


def compare_modes(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    left_mode: str,
    right_mode: str,
) -> dict[str, Any]:
    """Compare two declared modes with an explicit right-minus-left direction."""

    if (
        left["project_id"] != right["project_id"]
        or left.get(
            "particle_source_authority_sha256", left["particle_source_sha256"]
        )
        != right.get(
            "particle_source_authority_sha256", right["particle_source_sha256"]
        )
    ):
        raise ValueError("paired campaign arms differ in project or particle source")
    fields = (
        "transmission",
        "centered_spatial_rms_spread_mm",
        "mean_direction_tilt_deg",
        "centered_angular_rms_spread_deg",
        "mean_energy_eV",
        "centered_rms_energy_spread_eV",
        "mean_elapsed_time_us",
        "centered_rms_elapsed_time_spread_us",
        "p95_radius_mm",
        "p99_radius_mm",
        "p95_divergence_deg",
        "p99_divergence_deg",
    )
    return {
        "left_mode": left_mode,
        "right_mode": right_mode,
        "left_run_id": left["run_id"],
        "right_run_id": right["run_id"],
        "centroid_shift_mm": math.hypot(
            _delta(left, right, "centroid_x_mm"),
            _delta(left, right, "centroid_y_mm"),
        ),
        "right_minus_left": {
            field: _delta(left, right, field) for field in fields
        },
    }


def analyze(arms: list[tuple[str, str, str, Path]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    series: list[dict[str, Any]] = []
    for family, mode, label, manifest in arms:
        if mode not in MODES:
            raise ValueError(f"unsupported campaign analysis mode: {mode}")
        if mode in grouped.setdefault(family, {}):
            raise ValueError(f"duplicate family/mode arm: {family}/{mode}")
        summary = summarize_run(run_data(manifest))
        summary.update({"family": family, "mode": mode, "label": label})
        grouped[family][mode] = summary
        series.append(summary)
    comparisons: dict[str, dict[str, dict[str, Any]]] = {}
    for family, modes in grouped.items():
        required_modes = {"no_acceleration", "segmented_acceleration"}
        if not required_modes.issubset(modes):
            raise ValueError(
                "family must contain no-acceleration and segmented modes: "
                f"{family}"
            )
        family_pairs = {}
        for pair_id, left_mode, right_mode in PAIR_DEFINITIONS:
            if left_mode in modes and right_mode in modes:
                family_pairs[pair_id] = compare_modes(
                    modes[left_mode],
                    modes[right_mode],
                    left_mode=left_mode,
                    right_mode=right_mode,
                )
        comparisons[family] = family_pairs
    return {
        "schema_version": 2,
        "role": "multipole_campaign_engineering_summary",
        "analysis_class": "POSTHOC_DESCRIPTIVE",
        "series": series,
        "comparisons": comparisons,
        "claim_limit": (
            "N=100 SIMION handoff diagnostics for the declared arms; "
            "not a convergence, optimization, solver-equivalence, Candidate, or Formal claim."
        ),
    }


def markdown_report(document: dict[str, Any]) -> str:
    lines = [
        "# 多极杆 H15 多模式与初始能量对照",
        "",
        "本报告为 N=100 SIMION 事后工程描述。全部指标取规范 handoff 事件；"
        "它不证明数值收敛、最优设计、求解器等价、Candidate 或 Formal 资格。",
        "",
        "## 各臂出口状态",
        "",
        "|系列|透射|质心 x / y (mm)|中心化空间 RMS (mm)|平均方向倾角 (°)|中心化角 RMS (°)|平均能量 / 展宽 (eV)|平均时间 / 展宽 (µs)|p95 半径 / 角度|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in document["series"]:
        lines.append(
            "|{label}|{transmission:.3f}|{centroid_x_mm:.4f} / "
            "{centroid_y_mm:.4f}|{centered_spatial_rms_spread_mm:.4f}|"
            "{mean_direction_tilt_deg:.4f}|{centered_angular_rms_spread_deg:.4f}|"
            "{mean_energy_eV:.4f} / {centered_rms_energy_spread_eV:.4f}|"
            "{mean_elapsed_time_us:.4f} / "
            "{centered_rms_elapsed_time_spread_us:.4f}|"
            "{p95_radius_mm:.4f} / {p95_divergence_deg:.4f}|".format(**item)
        )
    lines.extend(
        [
            "",
            "## 模式间变化",
            "",
            "正值表示右侧模式更大，负值表示更小。",
            "",
            "|家族|比较（右−左）|质心位移 (mm)|空间 RMS Δ (mm)|平均方向倾角 Δ (°)|角 RMS Δ (°)|平均能量 Δ (eV)|能量展宽 Δ (eV)|平均时间 Δ (µs)|p95 角度 Δ (°)|",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for family, family_pairs in document["comparisons"].items():
        for comparison in family_pairs.values():
            delta = comparison["right_minus_left"]
            pair_label = (
                f"{comparison['right_mode']} − {comparison['left_mode']}"
            )
            lines.append(
                f"|{family}|{pair_label}|"
                f"{comparison['centroid_shift_mm']:.4f}|"
                f"{delta['centered_spatial_rms_spread_mm']:.4f}|"
                f"{delta['mean_direction_tilt_deg']:.4f}|"
                f"{delta['centered_angular_rms_spread_deg']:.4f}|"
                f"{delta['mean_energy_eV']:.4f}|"
                f"{delta['centered_rms_energy_spread_eV']:.4f}|"
                f"{delta['mean_elapsed_time_us']:.4f}|"
                f"{delta['p95_divergence_deg']:.4f}|"
            )
    lines.extend(["", f"声明边界：{document['claim_limit']}", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument(
        "--arm",
        action="append",
        nargs=4,
        metavar=("FAMILY", "MODE", "LABEL", "MANIFEST"),
    )
    inputs.add_argument(
        "--series",
        action="append",
        nargs=2,
        metavar=("LABEL", "MANIFEST"),
    )
    inputs.add_argument("--campaign-preflight", type=Path)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--baseline-label")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    if args.campaign_preflight:
        if not args.repo_root or not args.workspace_root:
            parser.error(
                "--repo-root and --workspace-root are required with --campaign-preflight"
            )
        if args.output or args.markdown or args.baseline_label:
            parser.error("analysis-output arguments are invalid with --campaign-preflight")
        document = campaign_request_preflight(
            args.repo_root, args.workspace_root, args.campaign_preflight
        )
        print(json.dumps(document, separators=(",", ":"), ensure_ascii=False))
        return 0
    if not args.output or not args.markdown:
        parser.error("--output and --markdown are required for analysis")
    if args.repo_root or args.workspace_root:
        parser.error("preflight roots are only valid with --campaign-preflight")
    if args.series:
        if not args.baseline_label:
            parser.error("--baseline-label is required with --series")
        document = analyze_series(
            [(label, Path(path)) for label, path in args.series],
            args.baseline_label,
        )
        markdown = series_markdown_report(document)
    else:
        if args.baseline_label:
            parser.error("--baseline-label is only valid with --series")
        document = analyze(
            [(family, mode, label, Path(path)) for family, mode, label, path in args.arm]
        )
        markdown = markdown_report(document)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    args.markdown.write_text(markdown, encoding="utf-8")
    print(
        "MULTIPOLE_CAMPAIGN_ANALYSIS=PASS "
        f"COMPARISONS={len(document['comparisons'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
