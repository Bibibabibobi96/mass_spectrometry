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
    artifact_entries = (
        (record["shared_particles"], "ion_table"),
        (record["comsol"], "particle_csv"),
        (record["simion"], "iob"),
        (record["simion"], "particle_csv"),
    )
    for section, stem in artifact_entries:
        require_hash(
            ARTIFACT_ROOT / section[f"{stem}_artifact_relative_path"],
            section[f"{stem}_sha256"],
        )

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
