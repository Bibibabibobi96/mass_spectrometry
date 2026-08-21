"""Plot one grid2-to-oaTOF run as a six-panel diagnostic and estimate R."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle

from common.contracts.component_particle_state import validate_component_particle_state_csv
from common.analysis.peak_metrics import FWHM_FACTOR


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def analyze(canonical_path: Path, downstream_path: Path) -> dict[str, object]:
    validate_component_particle_state_csv(canonical_path)
    canonical = _rows(canonical_path)
    downstream = _rows(downstream_path)
    if len(canonical) != len(downstream):
        raise ValueError("grid2 and downstream particle censuses differ")
    hits = [
        row for row in downstream
        if row["Hit"].strip().lower() == "true" and row["TofUs"].strip()
    ]
    tofs = [float(row["TofUs"]) for row in hits]
    mean_tof_us = statistics.fmean(tofs) if tofs else None
    sigma_tof_us = statistics.stdev(tofs) if len(tofs) > 1 else None
    fwhm_tof_us = FWHM_FACTOR * sigma_tof_us if sigma_tof_us is not None else None
    resolution = (
        mean_tof_us / (2.0 * fwhm_tof_us)
        if mean_tof_us is not None and fwhm_tof_us not in (None, 0.0)
        else None
    )
    return {
        "schema_version": 1,
        "role": "rf_oatof_grid2_downstream_six_panel_diagnostic",
        "status": "INCONCLUSIVE_DIAGNOSTIC_ONLY",
        "grid2_particles": len(canonical),
        "detector_hits": len(hits),
        "detector_hit_efficiency": len(hits) / len(canonical),
        "resolution": {
            "hit_particles": len(hits),
            "mean_analyzer_tof_us": mean_tof_us,
            "sample_sigma_analyzer_tof_ns": (
                sigma_tof_us * 1000.0 if sigma_tof_us is not None else None
            ),
            "gaussian_fwhm_tof_proxy_ns": (
                fwhm_tof_us * 1000.0 if fwhm_tof_us is not None else None
            ),
            "mass_resolution_gaussian_fwhm_proxy": resolution,
            "definition": "R=m/delta_m=t_mean/(2*2.35482*sigma_t)",
            "scope": "Gaussian FWHM proxy from detected analyzer TOF; not direct peak FWHM",
        },
        "claims": {
            "diagnostic_only": True,
            "convergence_complete": False,
            "resolution_claim_allowed": False,
        },
    }


def plot(
    canonical_path: Path, downstream_path: Path, geometry_path: Path,
    result: dict[str, object], label: str, output_path: Path,
) -> None:
    canonical = _rows(canonical_path)
    downstream = _rows(downstream_path)
    hits = [
        row for row in downstream
        if row["Hit"].strip().lower() == "true" and row["TofUs"].strip()
    ]
    geometry = json.loads(geometry_path.read_text(encoding="utf-8-sig"))
    detector_x = float(geometry["coordinate_convention"]["detector_x"])
    detector_radius = float(geometry["geometry_mm"]["detector_radius"])

    x = [float(row["position_x_mm"]) for row in canonical]
    y = [float(row["position_y_mm"]) for row in canonical]
    angle_x = [
        math.degrees(math.atan2(
            float(row["velocity_x_m_s"]), float(row["velocity_z_m_s"])
        )) for row in canonical
    ]
    angle_y = [
        math.degrees(math.atan2(
            float(row["velocity_y_m_s"]), float(row["velocity_z_m_s"])
        )) for row in canonical
    ]
    energy = [float(row["kinetic_energy_eV"]) for row in canonical]
    tof = [float(row["TofUs"]) for row in hits]
    tof_mean = statistics.fmean(tof) if tof else 0.0

    figure, axes = plt.subplots(2, 3, figsize=(15.2, 9.0), constrained_layout=True)
    axes[0, 0].scatter(x, y, s=24, color="#2166ac", alpha=0.8)
    axes[0, 0].set(title="A  grid2 transverse state", xlabel="x / mm", ylabel="y / mm")
    axes[0, 0].grid(alpha=0.25)

    axes[0, 1].scatter(angle_x, angle_y, s=24, color="#7b3294", alpha=0.8)
    axes[0, 1].set(title="B  grid2 angular state", xlabel="atan(vx/vz) / deg", ylabel="atan(vy/vz) / deg")
    axes[0, 1].grid(alpha=0.25)

    axes[0, 2].hist(energy, bins="auto", color="#e08214", edgecolor="white")
    axes[0, 2].set(title="C  grid2 kinetic energy", xlabel="energy / eV", ylabel="particles")
    axes[0, 2].grid(axis="y", alpha=0.25)

    hit_x = [float(row["XMm"]) - detector_x for row in hits]
    hit_y = [float(row["YMm"]) for row in hits]
    axes[1, 0].scatter(hit_x, hit_y, s=30, color="#1b9e77", alpha=0.85)
    axes[1, 0].add_patch(Circle((0.0, 0.0), detector_radius, fill=False,
                                linestyle="--", color="#525252"))
    axes[1, 0].set_aspect("equal", adjustable="box")
    axes[1, 0].set(title="D  detector hits", xlabel="x - detector center / mm", ylabel="y / mm")
    axes[1, 0].grid(alpha=0.25)

    centered_tof_ns = [(value - tof_mean) * 1000.0 for value in tof]
    axes[1, 1].hist(centered_tof_ns, bins="auto", color="#d95f02", edgecolor="white")
    axes[1, 1].set(title="E  detected analyzer TOF", xlabel="TOF - mean / ns", ylabel="hits")
    axes[1, 1].grid(axis="y", alpha=0.25)

    misses = len(canonical) - len(hits)
    axes[1, 2].bar(["grid2", "hit", "miss"], [len(canonical), len(hits), misses],
                   color=["#67a9cf", "#1b9e77", "#de2d26"])
    resolution = result["resolution"]
    value = resolution["mass_resolution_gaussian_fwhm_proxy"]
    fwhm = resolution["gaussian_fwhm_tof_proxy_ns"]
    axes[1, 2].text(
        0.03, 0.96,
        f"R proxy = {value:.3g}\nFWHM proxy = {fwhm:.3g} ns\nNhit = {len(hits)}"
        if value is not None and fwhm is not None else "R proxy unavailable",
        transform=axes[1, 2].transAxes, va="top",
        bbox={"facecolor": "white", "alpha": 0.85, "edgecolor": "#bdbdbd"},
    )
    axes[1, 2].set(title="F  census and resolution proxy", ylabel="particles")
    axes[1, 2].grid(axis="y", alpha=0.25)

    figure.suptitle(
        f"{label}\nINCONCLUSIVE_DIAGNOSTIC_ONLY — no convergence or resolution claim",
        fontsize=13,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical", required=True, type=Path)
    parser.add_argument("--downstream", required=True, type=Path)
    parser.add_argument("--geometry", required=True, type=Path)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output-figure", required=True, type=Path)
    parser.add_argument("--output-metrics", required=True, type=Path)
    args = parser.parse_args()
    result = analyze(args.canonical, args.downstream)
    plot(args.canonical, args.downstream, args.geometry, result, args.label,
         args.output_figure)
    args.output_metrics.parent.mkdir(parents=True, exist_ok=True)
    args.output_metrics.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        "GRID2_DOWNSTREAM_SIX_PANEL=PASS "
        f"HITS={result['detector_hits']}/{result['grid2_particles']}"
    )


if __name__ == "__main__":
    main()
