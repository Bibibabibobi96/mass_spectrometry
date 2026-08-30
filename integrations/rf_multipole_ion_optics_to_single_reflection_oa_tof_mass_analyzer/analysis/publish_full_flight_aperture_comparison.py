"""Publish an immutable eight-arm, full-mother-cohort aperture comparison.

This publisher deliberately has no paired-survivor mode.  Each arm is read
against its own complete frozen mother cohort; detector hits
only determine that arm's detected peak and never define a comparison cohort.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from common.contracts.artifact_naming import validate_run_id
from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.run_publication import (
    freeze_repository_inputs,
    portable_path,
    publish_manifest,
    record_for_path,
    write_pending_json,
)


INTEGRATION_ID = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
MODE = "rf_oatof_full_flight_aperture_comparison"
RESULT_ROLE = "rf_oatof_full_flight_aperture_comparison"
SUMMARY_ROLE = "rf_oatof_full_flight_aperture_comparison_summary"
IMPLEMENTATION_RELATIVE_PATH = (
    "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
    "analysis/publish_full_flight_aperture_comparison.py"
)
SOURCE_FILES = (
    "run_manifest.json",
    "run_config.json",
    "summary.json",
    "inputs/single_flight_initial_global_state.csv",
    "results/single_flight_particle_checkpoints.csv",
    "results/single_flight_accelerator_checkpoint_evolution.csv",
)


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        import json

        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ContractError(f"cannot load {label}: {path}") from error
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be a JSON object")
    return value


def _read_mother_ids(path: Path, case_id: str) -> tuple[list[int], str]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or "particle_id" not in reader.fieldnames:
                raise ContractError(f"{case_id} mother table lacks particle_id")
            ids = [int(row["particle_id"]) for row in reader]
    except (OSError, TypeError, ValueError) as error:
        raise ContractError(f"{case_id} mother table particle IDs are invalid") from error
    if not ids or len(set(ids)) != len(ids) or any(value <= 0 for value in ids):
        raise ContractError(f"{case_id} mother cohort identities are invalid")
    return ids, file_sha256(path)


def _positive_population_count(value: Any, *, case_id: str, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractError(f"{case_id} {field} is invalid")
    return value


def _source_release_width_acceptance_mm(config: Mapping[str, Any], *, case_id: str) -> float:
    parameters = config.get("parameters")
    if not isinstance(parameters, Mapping):
        raise ContractError(f"{case_id} resolved run parameters are missing")
    value = parameters.get("source_release_full_width_mm")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{case_id} source-release full-width acceptance is missing")
    acceptance_mm = float(value)
    if not math.isfinite(acceptance_mm) or acceptance_mm <= 0:
        raise ContractError(f"{case_id} source-release full-width acceptance is invalid")
    return acceptance_mm


def _checkpoint_entry_arrays(path: Path, mother_ids: set[int], case_id: str) -> tuple[np.ndarray, np.ndarray, set[int]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            needed = {"particle_id", "event", "z_mm", "vz_mm_per_us"}
            if reader.fieldnames is None or not needed.issubset(reader.fieldnames):
                raise ContractError(f"{case_id} checkpoint columns differ")
            entries = [row for row in reader if row["event"] == "pre_pulse_state"]
    except OSError as error:
        raise ContractError(f"cannot read {case_id} checkpoints") from error
    seen: set[int] = set()
    z_values: list[float] = []
    vz_values: list[float] = []
    for row in entries:
        try:
            particle_id = int(row["particle_id"])
            z_mm = float(row["z_mm"])
            vz_mm_per_us = float(row["vz_mm_per_us"])
        except (TypeError, ValueError) as error:
            raise ContractError(f"{case_id} accelerator-entry checkpoint is invalid") from error
        if particle_id not in mother_ids or particle_id in seen:
            raise ContractError(f"{case_id} accelerator-entry identities are invalid")
        if not math.isfinite(z_mm) or not math.isfinite(vz_mm_per_us):
            raise ContractError(f"{case_id} accelerator-entry phase space is non-finite")
        seen.add(particle_id)
        z_values.append(z_mm)
        vz_values.append(vz_mm_per_us)
    if len(z_values) < 4:
        raise ContractError(f"{case_id} needs at least four detector-blind accelerator-entry states")
    return np.asarray(z_values), np.asarray(vz_values), seen


def _polynomial_diagnostics(z_mm: np.ndarray, vz_mm_per_us: np.ndarray, degree: int) -> dict[str, Any]:
    coefficients = np.polyfit(z_mm, vz_mm_per_us, degree)
    residual = vz_mm_per_us - np.polyval(coefficients, z_mm)
    result: dict[str, Any] = {
        "degree": degree,
        "coefficients_descending_power": [float(value) for value in coefficients],
        "residual_sample_sigma_mm_per_us": float(np.std(residual, ddof=1)),
        "residual_rms_mm_per_us": float(np.sqrt(np.mean(np.square(residual)))),
        "residual_abs_p95_mm_per_us": float(np.quantile(np.abs(residual), 0.95)),
    }
    if degree == 1:
        result.update(k_per_us=float(coefficients[0]), intercept_mm_per_us=float(coefficients[1]))
    elif degree == 2:
        result["quadratic_coefficient_per_mm_us"] = float(coefficients[0])
    else:
        result["cubic_coefficient_per_mm2_us"] = float(coefficients[0])
    return result


def _published_higher_order_reference(path: Path, case_id: str) -> dict[str, Any]:
    """Retain the standard checkpoint-evolution high-order diagnostics verbatim."""

    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, csv.Error) as error:
        raise ContractError(f"cannot read {case_id} checkpoint evolution") from error
    matching = [row for row in rows if row.get("event") == "pre_pulse_state"]
    required = {
        "z_vz_k_m_per_s_per_mm",
        "z_vz_linear_residual_sigma_m_per_s",
        "z_vz_cubic_coefficient_m_per_s_per_mm3",
        "z_vz_cubic_random_residual_rms_m_per_s",
    }
    if len(matching) != 1 or not required.issubset(matching[0]):
        raise ContractError(f"{case_id} checkpoint evolution lacks pre-pulse high-order z-vz diagnostics")
    return {key: matching[0][key] for key in sorted(required)}


def _terminal_loss_taxonomy(summary: Mapping[str, Any], mother_ids: set[int], case_id: str) -> dict[str, Any]:
    taxonomy = summary.get("terminal_taxonomy")
    if not isinstance(taxonomy, dict) or taxonomy.get("role") != "rf_oatof_full_flight_terminal_taxonomy":
        raise ContractError(f"{case_id} terminal taxonomy is missing")
    if taxonomy.get("classification_is_mutually_exclusive_and_exhaustive") is not True:
        raise ContractError(f"{case_id} terminal taxonomy is not exhaustive")
    records = taxonomy.get("particle_outcomes")
    if not isinstance(records, list) or len(records) != len(mother_ids):
        raise ContractError(f"{case_id} terminal taxonomy does not cover the mother cohort")
    outcome_ids = {record.get("particle_id") for record in records if isinstance(record, dict)}
    if outcome_ids != mother_ids:
        raise ContractError(f"{case_id} terminal taxonomy identities differ from the mother cohort")
    counts = taxonomy.get("category_counts")
    if not isinstance(counts, dict) or sum(counts.values()) != len(mother_ids):
        raise ContractError(f"{case_id} terminal taxonomy counts differ")
    return {"category_counts": counts, "mother_cohort_count": len(mother_ids)}


def _required_peak_metrics(summary: Mapping[str, Any], case_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    peak = summary.get("pulse_effective_peak")
    bootstrap = summary.get("full_pulse_eligible_bootstrap")
    if not isinstance(peak, dict) or not isinstance(bootstrap, dict):
        raise ContractError(f"{case_id} lacks full-flight direct peak or bootstrap metrics")
    required = {"direct_fwhm_tof_ns", "direct_fwhm_mass_Da", "mass_resolution", "tail_fraction_outside_3sigma"}
    if not required.issubset(peak) or any(not math.isfinite(float(peak[key])) for key in required):
        raise ContractError(f"{case_id} direct peak metrics are invalid")
    if bootstrap.get("status") != "computed":
        raise ContractError(f"{case_id} bootstrap resolution interval was not computed")
    interval_keys = ("resolution_p2p5", "resolution_p97p5")
    try:
        interval_low, interval_high = (float(bootstrap[key]) for key in interval_keys)
    except (KeyError, TypeError, ValueError) as error:
        raise ContractError(f"{case_id} bootstrap resolution interval is incomplete") from error
    if (
        not math.isfinite(interval_low)
        or not math.isfinite(interval_high)
        or interval_low <= 0
        or interval_high < interval_low
    ):
        raise ContractError(f"{case_id} bootstrap resolution interval is invalid")
    return peak, bootstrap


def _verify_manifest_bound_source_files(manifest: Mapping[str, Any], run: Path, case_id: str) -> None:
    """Require the consumed source evidence to be bound by its success manifest."""

    try:
        record_for_path([manifest.get("run_config")], run / "run_config.json", f"{case_id} run config")
        for name in (
            "summary.json",
            "inputs/single_flight_initial_global_state.csv",
            "results/single_flight_particle_checkpoints.csv",
            "results/single_flight_accelerator_checkpoint_evolution.csv",
        ):
            record_for_path(
                [*manifest.get("inputs", {}).values(), *manifest.get("outputs", [])],
                run / name,
                f"{case_id} {name}",
            )
    except (TypeError, AttributeError) as error:
        raise ContractError(f"{case_id} success manifest records are invalid") from error


def _analyze_case(case_id: str, run: Path) -> tuple[dict[str, Any], str]:
    missing = [name for name in SOURCE_FILES if not (run / name).is_file()]
    if missing:
        raise ContractError(f"{case_id} source run is missing required input: {missing[0]}")
    manifest = _load_json(run / "run_manifest.json", f"{case_id} manifest")
    config = _load_json(run / "run_config.json", f"{case_id} config")
    summary = _load_json(run / "summary.json", f"{case_id} summary")
    if manifest.get("status") != "success" or manifest.get("run_id") != run.name or summary.get("status") != "success":
        raise ContractError(f"{case_id} is not a successful full-flight run")
    _verify_manifest_bound_source_files(manifest, run, case_id)
    if summary.get("role") != "rf_oatof_simion_single_flight_summary" or summary.get("analysis_scope") != "full_single_flight_with_pulse_eligibility":
        raise ContractError(f"{case_id} is not a pulse-on full-flight analysis")
    source = summary.get("source_population")
    if not isinstance(source, dict) or source.get("simulation_population_basis") != "candidate_full_population":
        raise ContractError(f"{case_id} uses a conditional or restart population")
    if summary.get("pulse_eligibility_validation_applied") is not True:
        raise ContractError(f"{case_id} did not validate pulse eligibility")
    mother_order, mother_sha = _read_mother_ids(run / "inputs" / "single_flight_initial_global_state.csv", case_id)
    mother_ids = set(mother_order)
    candidate_count = _positive_population_count(
        source.get("candidate_population_count"), case_id=case_id,
        field="candidate population count"
    )
    simulated_count = _positive_population_count(
        source.get("simulated_population_count"), case_id=case_id,
        field="simulated population count"
    )
    if candidate_count != len(mother_ids) or simulated_count != len(mother_ids):
        raise ContractError(f"{case_id} does not simulate its complete frozen mother cohort")
    full_width_acceptance_mm = _source_release_width_acceptance_mm(config, case_id=case_id)
    z_mm, vz_mm_per_us, entry_ids = _checkpoint_entry_arrays(
        run / "results" / "single_flight_particle_checkpoints.csv", mother_ids, case_id
    )
    published_higher_order = _published_higher_order_reference(
        run / "results" / "single_flight_accelerator_checkpoint_evolution.csv", case_id
    )
    terminal_taxonomy = _terminal_loss_taxonomy(summary, mother_ids, case_id)
    peak, bootstrap = _required_peak_metrics(summary, case_id)
    linear = _polynomial_diagnostics(z_mm, vz_mm_per_us, 1)
    quadratic = _polynomial_diagnostics(z_mm, vz_mm_per_us, 2)
    cubic = _polynomial_diagnostics(z_mm, vz_mm_per_us, 3)
    return {
        "source_run_id": run.name,
        "mother_cohort_count": len(mother_ids),
        "accelerator_entry_count": len(entry_ids),
        "accelerator_entry_fraction_of_mother": len(entry_ids) / len(mother_ids),
        "accelerator_entry_axial_width_mm": {
            "full_width": float(np.max(z_mm) - np.min(z_mm)),
            "quantile_width_05_to_95": float(np.quantile(z_mm, .95) - np.quantile(z_mm, .05)),
            "threshold_full_width_mm": full_width_acceptance_mm,
            "passed": bool(float(np.max(z_mm) - np.min(z_mm)) <= full_width_acceptance_mm),
            "population_basis": "all_observed_pre_pulse_state_particles_without_detector_filter",
        },
        "z_vz": {
            "linear": linear,
            "quadratic": quadratic,
            "cubic": cubic,
            "random_residual_model_degree": 3,
            "random_residual_sample_sigma_mm_per_us": cubic["residual_sample_sigma_mm_per_us"],
            "higher_order_residual_sigma_reduction_vs_linear_mm_per_us": {
                "quadratic": linear["residual_sample_sigma_mm_per_us"] - quadratic["residual_sample_sigma_mm_per_us"],
                "cubic": linear["residual_sample_sigma_mm_per_us"] - cubic["residual_sample_sigma_mm_per_us"],
            },
            "published_checkpoint_evolution_reference": published_higher_order,
        },
        "transmission_and_terminal_losses": {
            "detector_fraction_of_mother": summary.get("transmission", {}).get("detector_fraction_of_candidate_population"),
            "terminal_taxonomy": terminal_taxonomy,
        },
        "detector_peak": {
            "population_basis": "this_arm_detector_hits_only; never a cross-arm common-hit cohort",
            "direct_fwhm_tof_ns": peak["direct_fwhm_tof_ns"],
            "direct_fwhm_mass_Da": peak["direct_fwhm_mass_Da"],
            "mass_resolution": peak["mass_resolution"],
            "tail_fraction_outside_3sigma": peak["tail_fraction_outside_3sigma"],
            "peak_metrics": peak,
            "bootstrap_resolution": bootstrap,
        },
        "provenance": {
            "source_files": {name: {"path": str(run / name), "sha256": file_sha256(run / name)} for name in SOURCE_FILES},
            "source_initial_state_sha256": mother_sha,
            "run_config_mode": config.get("mode"),
        },
    }, mother_sha


def publish_full_flight_aperture_comparison(*, repo_root: Path, run_id: str, cases: Mapping[str, Path]) -> Path:
    """Publish the full eight-arm comparison after verifying every source arm."""

    repo_root = repo_root.resolve()
    workspace_root = repo_root.parent.resolve()
    try:
        validate_run_id(run_id)
    except ValueError as error:
        raise ContractError("full-flight aperture comparison run_id is invalid") from error
    if len(cases) != 8 or len(set(cases)) != 8:
        raise ContractError("full-flight aperture comparison requires exactly eight unique arms")
    normalized: dict[str, Path] = {}
    for case_id, raw_path in cases.items():
        if not isinstance(case_id, str) or not case_id.strip() or case_id != case_id.strip():
            raise ContractError("full-flight aperture case ID is invalid")
        path = Path(raw_path).resolve()
        if not path.is_dir() or not path.is_relative_to(workspace_root):
            raise ContractError(f"{case_id} source run is missing or outside workspace")
        normalized[case_id] = path
    analyzed = {case_id: _analyze_case(case_id, path) for case_id, path in sorted(normalized.items())}
    source_shas = {value[1] for value in analyzed.values()}
    if len(source_shas) != 1:
        raise ContractError("full-flight arms do not use the same frozen mother cohort")
    mother_counts = {value[0]["mother_cohort_count"] for value in analyzed.values()}
    if len(mother_counts) != 1:
        raise ContractError("full-flight arms do not use the same mother cohort count")
    mother_cohort_count = next(iter(mother_counts))
    result = {
        "schema_version": 1,
        "role": RESULT_ROLE,
        "status": "REAL_FIELD_EXPLORATORY_ONLY",
        "controlled_variables": {
            "case_count": 8,
            "mother_cohort_count": mother_cohort_count,
            "mother_cohort_initial_state_sha256_identical": True,
            "comparison_denominator": "full_mother_cohort",
            "common_hit_selection_used": False,
            "detector_peak_population_rule": "each arm uses its own detector hits only",
        },
        "cases": {case_id: value[0] for case_id, value in analyzed.items()},
        "limits": [
            "Each direct FWHM/resolution describes detector hits in that arm, with full-mother-cohort transmission and losses reported separately.",
            "This comparison is exploratory and does not grant Candidate or Formal qualification.",
        ],
    }
    runs_root = workspace_root / "artifacts" / "projects" / INTEGRATION_ID / "runs"
    run_dir = (runs_root / run_id).resolve()
    if run_dir.parent != runs_root.resolve() or run_dir.exists():
        raise ContractError("full-flight aperture comparison output already exists or is invalid")
    implementation = repo_root / IMPLEMENTATION_RELATIVE_PATH
    if not implementation.is_file():
        raise ContractError("full-flight aperture comparison implementation is missing")
    run_dir.mkdir(parents=True, exist_ok=False)
    result_path = run_dir / "results" / "full_flight_aperture_comparison.json"
    request_path = run_dir / "inputs" / "full_flight_aperture_comparison_request.json"
    run_config_path = run_dir / "run_config.json"
    summary_path = run_dir / "summary.json"
    manifest_path = run_dir / "run_manifest.json"
    write_pending_json(request_path, {"schema_version": 1, "role": "rf_oatof_full_flight_aperture_comparison_request", "cases": [{"case_id": case_id, "run_path": str(path)} for case_id, path in sorted(normalized.items())]})
    input_paths: dict[str, Path] = {"comparison_request": request_path, "publication_implementation": implementation}
    for index, (_, path) in enumerate(sorted(normalized.items()), start=1):
        for name in SOURCE_FILES:
            input_paths[f"case_{index}_{name.replace('/', '_').replace('.', '_')}"] = path / name
    frozen = freeze_repository_inputs(input_paths, repo_root=repo_root, run_dir=run_dir)
    run_config = {"schema_version": 2, "run_id": run_id, "project": INTEGRATION_ID, "mode": MODE, "project_root": str(workspace_root), "inputs": {name: portable_path(path, workspace_root) for name, path in sorted(frozen.items())}, "parameters": {"case_count": 8, "mother_cohort_count": mother_cohort_count, "axial_width_threshold_mm_by_case": {case_id: value[0]["accelerator_entry_axial_width_mm"]["threshold_full_width_mm"] for case_id, value in analyzed.items()}, "common_hit_selection_allowed": False, "formal_gate_passed": False}, "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None}, "formal_gate_passed": False}
    write_pending_json(run_config_path, run_config)
    write_pending_json(summary_path, {"schema_version": 1, "role": SUMMARY_ROLE, "status": "interrupted", "analysis_status": "NOT_RUN", "formal_gate_passed": False})
    pending_manifest = manifest_path.with_name(".run_manifest.json.pending")
    publish_manifest(repo_root=repo_root, run_config=run_config_path, manifest_path=pending_manifest, status="interrupted", outputs=(summary_path,), project=INTEGRATION_ID, mode=MODE, label="full-flight-aperture-comparison")
    os.replace(pending_manifest, manifest_path)
    write_pending_json(result_path, result)
    write_pending_json(summary_path, {"schema_version": 1, "role": SUMMARY_ROLE, "status": "success", "analysis_status": "REAL_FIELD_EXPLORATORY_ONLY", "case_count": 8, "result": "results/full_flight_aperture_comparison.json", "formal_gate_passed": False})
    publish_manifest(repo_root=repo_root, run_config=run_config_path, manifest_path=pending_manifest, status="success", outputs=(result_path, summary_path), project=INTEGRATION_ID, mode=MODE, label="full-flight-aperture-comparison")
    os.replace(pending_manifest, manifest_path)
    return manifest_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--case", action="append", nargs=2, metavar=("CASE_ID", "RUN_PATH"), required=True)
    args = parser.parse_args(argv)
    cases: dict[str, Path] = {}
    for case_id, run_path in args.case:
        if case_id in cases:
            raise ContractError("full-flight aperture case IDs must be unique")
        cases[case_id] = Path(run_path)
    manifest = publish_full_flight_aperture_comparison(repo_root=args.repo_root, run_id=args.run_id, cases=cases)
    print(f"FULL_FLIGHT_APERTURE_COMPARISON=PASS STATUS=REAL_FIELD_EXPLORATORY_ONLY MANIFEST={manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
