"""Verify the current formal cross-solver record and its external artifacts."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path


ANALYSIS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = ANALYSIS_DIR.parent
REPO_ROOT = PROJECT_DIR.parents[1]
ARTIFACT_ROOT = REPO_ROOT.parent / "artifacts" / "projects" / "oa_tof"
CONFIG_PATH = PROJECT_DIR / "config" / "formal_validation.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def require_hash(path: Path, expected: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError(f"SHA-256 mismatch for {path}: {actual} != {expected}")


def require_close(label: str, actual: float, expected: float) -> None:
    if not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-12):
        raise ValueError(f"{label} mismatch: {actual} != {expected}")


def require_artifact_references(node: object) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key.endswith("artifact_relative_path"):
                hash_candidates = (
                    key[: -len("_relative_path")] + "_sha256",
                    key[: -len("_artifact_relative_path")] + "_sha256",
                )
                hash_key = next(
                    (candidate for candidate in hash_candidates if candidate in node),
                    None,
                )
                if hash_key is None:
                    raise ValueError(
                        f"Missing one of {hash_candidates} beside {key}"
                    )
                require_hash(ARTIFACT_ROOT / str(value), str(node[hash_key]))
            else:
                require_artifact_references(value)
    elif isinstance(node, list):
        for value in node:
            require_artifact_references(value)


def main() -> None:
    record = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if record["status"] != "formal_cross_solver_validation":
        raise ValueError("Formal validation record is not active")

    require_hash(
        PROJECT_DIR / "config" / record["physical_contract"],
        record["physical_contract_sha256"],
    )
    require_hash(
        PROJECT_DIR / "config" / record["analysis_contract"],
        record["analysis_contract_sha256"],
    )
    require_artifact_references(record)
    if record.get("schema_version", 0) < 4:
        diagnostics = record.get("diagnostics", {})
        if diagnostics.get("status") != "peak_shoulder_source_localized":
            raise ValueError("Formal peak-shoulder diagnostic is not localized")
    else:
        validation_scope = record.get("validation_scope")
        allowed_scopes = {
            "direct_rerun_of_current_formal_comsol_and_simion_assets",
            "validated_candidate_assets_promoted_atomically_to_current_formal",
        }
        if validation_scope not in allowed_scopes:
            raise ValueError(f"Unsupported formal validation scope: {validation_scope}")
        if validation_scope == "validated_candidate_assets_promoted_atomically_to_current_formal":
            promotion = record.get("promotion_evidence")
            if not isinstance(promotion, dict):
                raise ValueError("Promoted formal validation lacks promotion evidence")
            for key in (
                "validation_run_manifest_artifact_relative_path",
                "comsol_promotion_report_artifact_relative_path",
                "cad_sync_report_artifact_relative_path",
            ):
                if key not in promotion:
                    raise ValueError(f"Promoted formal validation lacks {key}")
            validation_manifest = json.loads(
                (ARTIFACT_ROOT / promotion["validation_run_manifest_artifact_relative_path"])
                .read_text(encoding="utf-8-sig")
            )
            if validation_manifest.get("status") != "success":
                raise ValueError("Promotion source validation run is not successful")
            for key in (
                "comsol_promotion_report_artifact_relative_path",
                "cad_sync_report_artifact_relative_path",
            ):
                report = (
                    ARTIFACT_ROOT / promotion[key]
                ).read_text(encoding="utf-8-sig")
                if "STATUS=PASS" not in report.splitlines():
                    raise ValueError(f"Promotion report is not PASS: {promotion[key]}")
    comparison_path = ARTIFACT_ROOT / record["comparison_artifact_relative_path"]
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    if comparison["status"] != "PASS":
        raise ValueError("Canonical comparison result did not pass")

    for side, solver in (("left", "comsol"), ("right", "simion")):
        metrics = comparison[side]["metrics"]
        for key in (
            "mean_tof_us",
            "direct_fwhm_tof_ns",
            "direct_fwhm_mass_Da",
            "mass_resolution",
            "tof_skewness",
            "hwhm_asymmetry_right_over_left",
            "significant_kde_modes",
        ):
            require_close(f"{solver}.{key}", metrics[key], record[solver][key])
        for key in (
            "impact_centroid_x_mm",
            "impact_centroid_y_mm",
            "impact_rms_radius_mm",
        ):
            require_close(
                f"{solver}.{key}", metrics["detector"][key], record[solver][key]
            )

    canonical_comparison = comparison["comparison"]
    for key in (
        "mean_tof_difference_right_minus_left_ns",
        "standardized_kde_overlap",
        "standardized_ks_distance",
        "standardized_ks_pvalue",
        "paired_standardized_tof_correlation",
        "bootstrap_absolute_resolution_difference_pct_p2p5",
        "bootstrap_absolute_resolution_difference_pct_median",
        "bootstrap_absolute_resolution_difference_pct_p97p5",
    ):
        record_key = (
            "mean_tof_difference_simion_minus_comsol_ns"
            if key == "mean_tof_difference_right_minus_left_ns"
            else key
        )
        require_close(
            f"comparison.{key}",
            canonical_comparison[key],
            record["comparison"][record_key],
        )
    detector_comparison = canonical_comparison["detector_landing"]
    for result_key, record_key in (
        ("centroid_distance_mm", "detector_centroid_distance_mm"),
        ("paired_mean_landing_distance_mm", "paired_mean_landing_distance_mm"),
        ("paired_rms_landing_distance_mm", "paired_rms_landing_distance_mm"),
        ("paired_max_landing_distance_mm", "paired_max_landing_distance_mm"),
    ):
        require_close(
            f"comparison.detector_landing.{result_key}",
            detector_comparison[result_key],
            record["comparison"][record_key],
        )

    resolution_difference = 100.0 * (
        record["comsol"]["mass_resolution"] - record["simion"]["mass_resolution"]
    ) / record["simion"]["mass_resolution"]
    require_close(
        "comparison.comsol_resolution_higher_than_simion_pct",
        resolution_difference,
        record["comparison"]["comsol_resolution_higher_than_simion_pct"],
    )
    print("FORMAL_VALIDATION_STATUS=PASS")


if __name__ == "__main__":
    main()
