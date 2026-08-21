"""Compare the ideal oaTOF source with actual multipole-fed pulse cohorts."""

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
from matplotlib.patches import Rectangle
import numpy as np

from common.contracts.component_particle_state import validate_component_particle_state_csv
from common.contracts.particle_physics import kinetic_energy_ev
from common.analysis.peak_metrics import FWHM_FACTOR


COLORS = {
    "ideal": "#252525", "octupole": "#0072b2", "quadrupole": "#d55e00",
    "octupole_comsol": "#56b4e9", "octupole_simion": "#0072b2",
    "quadrupole_comsol": "#e69f00", "quadrupole_simion": "#d55e00",
}


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _mean_sigma(values: list[float]) -> dict[str, float]:
    return {
        "mean": statistics.fmean(values),
        "sample_sigma": statistics.stdev(values) if len(values) > 1 else 0.0,
        "minimum": min(values), "maximum": max(values),
    }


def _pulse_state(path: Path) -> list[dict[str, float]]:
    result = []
    for row in _rows(path):
        if int(row["active_at_pulse"]) != 1:
            continue
        velocity = tuple(float(row[f"v{key}_m_s"]) for key in "xyz")
        result.append(
            {key: float(row[f"{key}_mm"]) for key in "xyz"}
            | {f"v{key}": value for key, value in zip("xyz", velocity)}
            | {"energy": kinetic_energy_ev(100.0, *velocity)}
        )
    return result


def _grid2(run: Path) -> list[dict[str, float]]:
    matches = list((run / "inputs").glob("canonical_*accelerator_exit.csv"))
    if len(matches) != 1:
        raise ValueError(f"grid2 canonical state is not unique: {run}")
    validate_component_particle_state_csv(matches[0])
    result = []
    for row in _rows(matches[0]):
        vx, vy, vz = (float(row[f"velocity_{axis}_m_s"]) for axis in "xyz")
        result.append({
            "angle_x": math.degrees(math.atan2(vx, vz)),
            "angle_y": math.degrees(math.atan2(vy, vz)),
            "energy": float(row["kinetic_energy_eV"]),
        })
    return result


def _hit_tof(run: Path) -> list[float]:
    return [
        float(row["TofUs"]) for row in _rows(run / "results" / "simion_downstream_particles.csv")
        if row["Hit"].strip().lower() == "true" and row["TofUs"].strip()
    ]


def _resolution_proxy(tof_us: list[float]) -> dict[str, float | int | None]:
    mean = statistics.fmean(tof_us) if tof_us else None
    sigma_ns = statistics.stdev(tof_us) * 1000.0 if len(tof_us) > 1 else None
    fwhm_ns = FWHM_FACTOR * sigma_ns if sigma_ns is not None else None
    resolution = mean * 1000.0 / (2.0 * fwhm_ns) if fwhm_ns else None
    return {
        "hits": len(tof_us), "mean_tof_us": mean,
        "sample_sigma_tof_ns": sigma_ns,
        "gaussian_fwhm_tof_proxy_ns": fwhm_ns,
        "mass_resolution_gaussian_fwhm_proxy": resolution,
    }


def analyze(
    formal_run: Path, oct_pulse_run: Path, quad_pulse_run: Path,
    downstream_runs: dict[str, Path],
) -> tuple[dict[str, object], dict[str, object]]:
    formal_metrics = json.loads(
        (formal_run / "results" / "comparison_metrics.json").read_text(encoding="utf-8")
    )
    ideal_rows = _rows(formal_run / "results" / "source_mapping_particles.csv")
    ideal = [
        {"x": float(row["initial_x_mm"]), "y": float(row["initial_y_mm"]),
         "z": float(row["initial_z_mm"]), "energy": float(row["initial_energy_eV"])}
        for row in ideal_rows
    ]
    pulse = {
        "octupole": _pulse_state(
            oct_pulse_run / "results" / "pulse_capture_pulse_left_limit_state.csv"
        ),
        "quadrupole": _pulse_state(
            quad_pulse_run / "results" / "pulse_capture_pulse_left_limit_state.csv"
        ),
    }
    snapshots = {
        "octupole": json.loads((oct_pulse_run / "results" /
            "pulse_capture_pulse_geometry_snapshot.json").read_text(encoding="utf-8")),
        "quadrupole": json.loads((quad_pulse_run / "results" /
            "pulse_capture_pulse_geometry_snapshot.json").read_text(encoding="utf-8")),
    }
    grid2 = {name: _grid2(run) for name, run in downstream_runs.items()}
    current_tof = {name: _hit_tof(run) for name, run in downstream_runs.items()}
    ideal_tof = {
        "ideal_comsol": [float(row["TofUs"]) for row in _rows(
            formal_run / "results" / "comsol_particles.csv")],
        "ideal_simion": [float(row["TofUs"]) for row in _rows(
            formal_run / "results" / "simion_particles.csv")],
    }

    source_stats: dict[str, object] = {}
    for name, rows in (("ideal", ideal), *pulse.items()):
        source_stats[name] = {
            "particles": len(rows),
            **{axis: _mean_sigma([row[axis] for row in rows]) for axis in "xyz"},
            "kinetic_energy_eV": _mean_sigma([row["energy"] for row in rows]),
        }
    for name in pulse:
        source_stats[name]["velocity_m_s"] = {
            axis: _mean_sigma([row[f"v{axis}"] for row in pulse[name]])
            for axis in "xyz"
        }
        source_stats[name]["inside_ideal_source_volume"] = int(
            snapshots[name]["active_inside_ideal_reference_volume"]
        )
        source_stats[name]["inside_ideal_source_volume_fraction"] = float(
            snapshots[name]["active_ideal_reference_volume_fraction"]
        )
        source_stats[name]["pre_pulse_accelerator_losses"] = int(
            snapshots[name]["frozen_accelerator_losses_before_pulse"]
        )

    grid2_stats = {
        name: {
            "particles": len(rows),
            "angle_x_deg": _mean_sigma([row["angle_x"] for row in rows]),
            "angle_y_deg": _mean_sigma([row["angle_y"] for row in rows]),
            "energy_eV": _mean_sigma([row["energy"] for row in rows]),
        } for name, rows in grid2.items()
    }
    resolutions = {
        "ideal_comsol_direct_kde": {
            "particles": int(formal_metrics["left"]["metrics"]["particles"]),
            "direct_fwhm_tof_ns": formal_metrics["left"]["metrics"]["direct_fwhm_tof_ns"],
            "mass_resolution": formal_metrics["left"]["metrics"]["mass_resolution"],
        },
        "ideal_simion_direct_kde": {
            "particles": int(formal_metrics["right"]["metrics"]["particles"]),
            "direct_fwhm_tof_ns": formal_metrics["right"]["metrics"]["direct_fwhm_tof_ns"],
            "mass_resolution": formal_metrics["right"]["metrics"]["mass_resolution"],
        },
        **{name: _resolution_proxy(values) for name, values in current_tof.items()},
    }
    result = {
        "schema_version": 1,
        "role": "rf_oatof_ideal_actual_resolution_gap_diagnostic",
        "status": "INCONCLUSIVE_DIAGNOSTIC_ONLY",
        "source_space": source_stats,
        "grid2": grid2_stats,
        "resolution": resolutions,
        "estimator_warning": (
            "ideal values use direct KDE FWHM at N=1000; current values use Gaussian "
            "sample-sigma FWHM proxies at Nhit=3..34 and are not estimator-equivalent"
        ),
        "claims": {"diagnostic_only": True, "resolution_claim_allowed": False},
    }
    plot_data = {
        "ideal": ideal, "pulse": pulse, "grid2": grid2,
        "ideal_tof": ideal_tof, "current_tof": current_tof,
        "geometry": snapshots["octupole"]["geometry_mm"],
    }
    return result, plot_data


def _ecdf_abs_centered_ns(values: list[float]) -> tuple[np.ndarray, np.ndarray]:
    mean = statistics.fmean(values)
    x = np.sort(np.maximum(np.abs((np.asarray(values) - mean) * 1000.0), 1e-3))
    return x, np.arange(1, len(x) + 1) / len(x)


def plot(result: dict[str, object], data: dict[str, object], output: Path) -> None:
    pulse = data["pulse"]
    geometry = data["geometry"]
    figure, axes = plt.subplots(2, 3, figsize=(16.0, 9.4), constrained_layout=True)

    ax = axes[0, 0]
    ax.add_patch(Rectangle(
        (geometry["center_x"] - geometry["shield_outer_half"], geometry["shield_z_min"]),
        2 * geometry["shield_outer_half"], geometry["shield_z_max"] - geometry["shield_z_min"],
        fill=False, color="#969696", linewidth=1.5, label="grounded shield",
    ))
    for label, z, half in (
        ("repeller", geometry["repeller_z"], geometry["ring_outer_half"]),
        ("grid1", geometry["grid1_z"], geometry["grid1_half"]),
        ("grid2", geometry["grid2_z"], geometry["grid2_half"]),
    ):
        ax.plot([geometry["center_x"] - half, geometry["center_x"] + half], [z, z],
                linewidth=2, label=label)
    ax.add_patch(Rectangle((-49.3, -18.92918680341103), 1.0, 1.0,
                           fill=False, color=COLORS["ideal"], linewidth=2,
                           label="ideal 1 mm source"))
    for name in ("octupole", "quadrupole"):
        ax.scatter([row["x"] for row in pulse[name]], [row["z"] for row in pulse[name]],
                   s=18, alpha=0.65, color=COLORS[name], label=f"{name} at pulse")
    ax.set(title="A  Source position inside accelerator (x–z)", xlabel="x / mm", ylabel="z / mm")
    ax.legend(fontsize=7, ncol=2); ax.grid(alpha=0.2)

    ax = axes[0, 1]
    ax.add_patch(Rectangle((-53.8, -5.0), 10.0, 10.0, fill=False,
                           color="#969696", linewidth=1.5, label="accelerator bore"))
    ax.add_patch(Rectangle((-49.3, -0.5), 1.0, 1.0, fill=False,
                           color=COLORS["ideal"], linewidth=2, label="ideal source"))
    for name in ("octupole", "quadrupole"):
        ax.scatter([row["x"] for row in pulse[name]], [row["y"] for row in pulse[name]],
                   s=20, alpha=0.65, color=COLORS[name], label=name)
    ax.set_aspect("equal", adjustable="box")
    ax.set(title="B  Source position inside accelerator (x–y)", xlabel="x / mm", ylabel="y / mm")
    ax.legend(fontsize=8); ax.grid(alpha=0.2)

    ax = axes[0, 2]
    centers = {"x": -48.8, "y": 0.0, "z": -18.42918680341103}
    markers = {"ideal": "o", "octupole": "s", "quadrupole": "^"}
    for index, axis in enumerate("xyz"):
        for offset, name in enumerate(("ideal", "octupole", "quadrupole")):
            stats = result["source_space"][name][axis]
            ax.errorbar(index + (offset - 1) * 0.17, stats["mean"] - centers[axis],
                        yerr=stats["sample_sigma"], fmt=markers[name], capsize=3,
                        color=COLORS[name], label=name if index == 0 else None)
    ax.axhline(0, color="#636363", linewidth=1)
    ax.set_xticks(range(3), ["x", "y", "z"])
    ax.set(title="C  Source centroid offset ± sample σ", ylabel="offset from ideal center / mm")
    ax.legend(fontsize=8); ax.grid(axis="y", alpha=0.25)

    ax = axes[1, 0]
    for name, rows in data["grid2"].items():
        ax.scatter([row["angle_x"] for row in rows], [row["energy"] for row in rows],
                   s=20, alpha=0.65, color=COLORS[name], label=name.replace("_", " "))
    ax.axhspan(1920, 2080, color="#bdbdbd", alpha=0.2, label="ideal design energy band")
    ax.set(title="D  grid2 angle–energy state", xlabel="atan(vx/vz) / deg", ylabel="energy / eV")
    ax.legend(fontsize=7); ax.grid(alpha=0.2)

    ax = axes[1, 1]
    tof_sets = {**data["ideal_tof"], **data["current_tof"]}
    for name, values in tof_sets.items():
        x, y = _ecdf_abs_centered_ns(values)
        color = COLORS.get(name, "#000000")
        linestyle = "--" if name.startswith("ideal") else "-"
        ax.plot(x, y, label=name.replace("_", " "), color=color, linestyle=linestyle)
    ax.set_xscale("log")
    ax.set(title="E  Absolute centered TOF error ECDF", xlabel="|TOF - mean| / ns", ylabel="cumulative fraction")
    ax.legend(fontsize=7); ax.grid(alpha=0.25, which="both")

    ax = axes[1, 2]
    order = ["ideal_comsol_direct_kde", "ideal_simion_direct_kde",
             "octupole_comsol", "octupole_simion", "quadrupole_comsol", "quadrupole_simion"]
    values = [
        result["resolution"][name].get("mass_resolution")
        or result["resolution"][name].get("mass_resolution_gaussian_fwhm_proxy")
        for name in order
    ]
    ax.bar(range(len(order)), values, color=["#666666", "#252525", "#56b4e9", "#0072b2", "#e69f00", "#d55e00"])
    ax.set_yscale("log")
    ax.set_xticks(range(len(order)), ["ideal\nCOMSOL", "ideal\nSIMION", "oct\nCOMSOL", "oct\nSIMION", "quad\nCOMSOL", "quad\nSIMION"])
    ax.set(title="F  Resolution: ideal direct KDE vs current proxy", ylabel="mass resolution R")
    ax.grid(axis="y", alpha=0.25, which="both")

    figure.suptitle(
        "Ideal oaTOF source vs multipole-fed pulse cohorts\n"
        "INCONCLUSIVE_DIAGNOSTIC_ONLY — estimator and sample sizes differ",
        fontsize=14,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=190)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--formal-run", required=True, type=Path)
    parser.add_argument("--oct-pulse-run", required=True, type=Path)
    parser.add_argument("--quad-pulse-run", required=True, type=Path)
    for name in ("oct-comsol", "oct-simion", "quad-comsol", "quad-simion"):
        parser.add_argument(f"--{name}-run", required=True, type=Path)
    parser.add_argument("--output-figure", required=True, type=Path)
    parser.add_argument("--output-metrics", required=True, type=Path)
    args = parser.parse_args()
    runs = {
        "octupole_comsol": args.oct_comsol_run,
        "octupole_simion": args.oct_simion_run,
        "quadrupole_comsol": args.quad_comsol_run,
        "quadrupole_simion": args.quad_simion_run,
    }
    result, data = analyze(args.formal_run, args.oct_pulse_run, args.quad_pulse_run, runs)
    plot(result, data, args.output_figure)
    args.output_metrics.parent.mkdir(parents=True, exist_ok=True)
    args.output_metrics.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("IDEAL_ACTUAL_RESOLUTION_GAP=PASS")


if __name__ == "__main__":
    main()
