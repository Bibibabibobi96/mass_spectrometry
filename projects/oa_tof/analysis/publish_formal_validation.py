"""Publish a formal oa-TOF cross-solver record from direct current-asset runs."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
REPO = PROJECT.parents[1]
ARTIFACTS = REPO.parent / "artifacts" / "projects" / "oa_tof"
CONFIG = PROJECT / "config"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest().upper()


def artifact(path: Path) -> str:
    path = path.resolve()
    try:
        return path.relative_to(ARTIFACTS.resolve()).as_posix()
    except ValueError as error:
        raise ValueError(f"Formal evidence must be under {ARTIFACTS}: {path}") from error


def report_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    if values.get("STATUS") != "PASS":
        raise ValueError(f"Run report is not PASS: {path}")
    return values


def metric_block(side: dict, csv_path: Path) -> dict:
    metrics = side["metrics"]
    detector = metrics["detector"]
    if int(metrics["particles"]) != 1000 or float(side["import"]["hit_fraction"]) != 1.0:
        raise ValueError(f"Formal side {side['label']} is not 1000/1000")
    if digest(csv_path) != side["sha256"]:
        raise ValueError(f"Comparison input hash does not match {csv_path}")
    return {
        "particle_csv_artifact_relative_path": artifact(csv_path),
        "particle_csv_sha256": digest(csv_path),
        "hit_fraction": "1000/1000",
        **{key: metrics[key] for key in (
            "mean_tof_us", "direct_fwhm_tof_ns", "direct_fwhm_mass_Da",
            "mass_resolution", "tof_skewness", "hwhm_asymmetry_right_over_left",
            "significant_kde_modes",
        )},
        **{key: detector[key] for key in (
            "impact_centroid_x_mm", "impact_centroid_y_mm", "impact_rms_radius_mm",
        )},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--comsol-csv", type=Path, required=True)
    parser.add_argument("--comsol-report", type=Path, required=True)
    parser.add_argument("--simion-csv", type=Path, required=True)
    parser.add_argument("--simion-summary", type=Path, required=True)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument(
        "--validation-scope",
        default="direct_rerun_of_current_formal_comsol_and_simion_assets",
        choices=(
            "direct_rerun_of_current_formal_comsol_and_simion_assets",
            "validated_candidate_assets_promoted_atomically_to_current_formal",
        ),
    )
    parser.add_argument("--output", type=Path, default=CONFIG / "formal_validation.json")
    args = parser.parse_args()

    comparison = json.loads(args.comparison.read_text(encoding="utf-8-sig"))
    if comparison.get("status") != "PASS" or comparison.get("schema_version") != 3:
        raise ValueError("Comparison is not a PASS schema-v3 result")
    comsol_report = report_values(args.comsol_report)
    simion_summary = json.loads(args.simion_summary.read_text(encoding="utf-8-sig"))
    if int(simion_summary["Hit"]) != 1000 or int(simion_summary["Emitted"]) != 1000:
        raise ValueError("SIMION summary is not 1000/1000")

    baseline = CONFIG / "baseline.json"
    analysis_contract = CONFIG / "analysis_contract.json"
    ion = ARTIFACTS / "formal/simion/oatof_comsol_524amu_gaussian_N1000.ion"
    mph = ARTIFACTS / "formal/comsol/oa_tof__model.mph"
    iob = ARTIFACTS / "formal/simion/oatof_ideal_grounded.iob"
    simion_manifest = ARTIFACTS / "formal/simion/run_manifest.json"
    validation_manifest = ARTIFACTS / "runs" / args.run_id / "run_manifest.json"
    comsol_promotion_report = ARTIFACTS / "formal/comsol/promotion_report.txt"
    cad_sync_report = ARTIFACTS / "formal/cad/formal_cad_sync_report.txt"
    promotion_paths = (
        validation_manifest,
        comsol_promotion_report,
        cad_sync_report,
    ) if args.validation_scope == (
        "validated_candidate_assets_promoted_atomically_to_current_formal"
    ) else ()
    for path in (baseline, analysis_contract, ion, mph, iob, simion_manifest,
                 args.comsol_csv, args.comsol_report, args.simion_csv,
                 args.simion_summary, args.comparison, *promotion_paths):
        if not path.is_file():
            raise FileNotFoundError(path)
    if promotion_paths:
        report_values(comsol_promotion_report)
        report_values(cad_sync_report)
        validation_record = json.loads(validation_manifest.read_text(encoding="utf-8-sig"))
        if validation_record.get("status") != "success":
            raise ValueError("Promotion source validation run is not successful")

    comp = comparison["comparison"]
    landing = comp["detector_landing"]
    bootstrap = comp["paired_bootstrap"]
    record = {
        "schema_version": 4,
        "status": "formal_cross_solver_validation",
        "validated_on": date.today().isoformat(),
        "run_id": args.run_id,
        "validation_scope": args.validation_scope,
        "physical_contract": "baseline.json",
        "physical_contract_sha256": digest(baseline),
        "analysis_contract": "analysis_contract.json",
        "analysis_contract_sha256": digest(analysis_contract),
        "shared_particles": {
            "mass_amu": 524.0, "charge_e": 1, "particles": 1000,
            "initial_energy_mean_eV": 5.0, "initial_energy_sigma_eV": 0.4,
            "ion_table_artifact_relative_path": artifact(ion),
            "ion_table_bytes": ion.stat().st_size, "ion_table_sha256": digest(ion),
        },
        "comsol": {
            "model_role": "formal", "field_mode": "real",
            "formal_mph_artifact_relative_path": artifact(mph),
            "formal_mph_bytes": mph.stat().st_size, "formal_mph_sha256": digest(mph),
            "accelerator_hmax_mm": 1.0,
            "mesh_tetrahedra": int(comsol_report["MESH_ELEMENTS"]),
            "fine_output_step_ns": 0.2, "field_free_output_step_ns": 50.0,
            **metric_block(comparison["left"], args.comsol_csv),
        },
        "simion": {
            "model_role": "formal", "trajectory_quality": 8,
            "iob_artifact_relative_path": artifact(iob), "iob_sha256": digest(iob),
            "delivery_manifest_artifact_relative_path": artifact(simion_manifest),
            "delivery_manifest_sha256": digest(simion_manifest),
            **metric_block(comparison["right"], args.simion_csv),
        },
        "comparison": {
            "comsol_resolution_higher_than_simion_pct": 100.0 * (
                comparison["left"]["metrics"]["mass_resolution"] /
                comparison["right"]["metrics"]["mass_resolution"] - 1.0),
            "mean_tof_difference_simion_minus_comsol_ns": comp["mean_tof_difference_right_minus_left_ns"],
            **{key: comp[key] for key in (
                "standardized_kde_overlap", "standardized_ks_distance",
                "standardized_ks_pvalue", "paired_standardized_tof_correlation",
                "bootstrap_absolute_resolution_difference_pct_p2p5",
                "bootstrap_absolute_resolution_difference_pct_median",
                "bootstrap_absolute_resolution_difference_pct_p97p5",
            )},
            "bootstrap_resamples": bootstrap["resamples_valid"],
            "bootstrap_seed": bootstrap["seed"],
            "paired_tof_difference": comp["paired_tof_difference"],
            "detector_centroid_distance_mm": landing["centroid_distance_mm"],
            "paired_mean_landing_distance_mm": landing["paired_mean_landing_distance_mm"],
            "paired_rms_landing_distance_mm": landing["paired_rms_landing_distance_mm"],
            "paired_max_landing_distance_mm": landing["paired_max_landing_distance_mm"],
        },
        "comparison_artifact_relative_path": artifact(args.comparison),
        "comparison_artifact_sha256": digest(args.comparison),
        "run_evidence": {
            "comsol_report_artifact_relative_path": artifact(args.comsol_report),
            "comsol_report_sha256": digest(args.comsol_report),
            "simion_summary_artifact_relative_path": artifact(args.simion_summary),
            "simion_summary_sha256": digest(args.simion_summary),
        },
    }
    if promotion_paths:
        record["promotion_evidence"] = {
            "validation_run_manifest_artifact_relative_path": artifact(validation_manifest),
            "validation_run_manifest_sha256": digest(validation_manifest),
            "comsol_promotion_report_artifact_relative_path": artifact(comsol_promotion_report),
            "comsol_promotion_report_sha256": digest(comsol_promotion_report),
            "cad_sync_report_artifact_relative_path": artifact(cad_sync_report),
            "cad_sync_report_sha256": digest(cad_sync_report),
        }
    args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"FORMAL_VALIDATION_PUBLISHED={args.output}")


if __name__ == "__main__":
    main()
