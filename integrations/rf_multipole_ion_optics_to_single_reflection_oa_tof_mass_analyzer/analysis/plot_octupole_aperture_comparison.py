"""Compare two oaTOF interface apertures for one frozen octupole cohort."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np

from common.analysis.peak_metrics import (
    compute_peak_metrics,
)


COLORS = {"all": "#777777", "wide": "#0072b2", "small": "#d55e00", "ideal": "#252525"}
IDEAL_CENTER = {"x": -48.8, "y": 0.0, "z": -18.42918680341103}
IDEAL_HALF_MM = 0.5


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _stats(values: list[float]) -> dict[str, float]:
    return {
        "mean": statistics.fmean(values),
        "sample_sigma": statistics.stdev(values),
        "minimum": min(values),
        "maximum": max(values),
    }


def _manifest(run: Path) -> dict[str, object]:
    value = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
    if value.get("status") != "success" or value.get("run_id") != run.name:
        raise ValueError(f"run is not a successful immutable source: {run}")
    return value


def _hit_particle_ids(interface_run: Path) -> set[int]:
    mapping = {
        int(row["solver_row_index"]): int(row["particle_id"])
        for row in _rows(interface_run / "inputs" / "row_map.csv")
    }
    return {
        mapping[int(row["Ion"])]
        for row in _rows(interface_run / "results" / "simion_downstream_particles.csv")
        if row["Hit"].strip().lower() == "true"
    }


def _detector_tof(run: Path) -> np.ndarray:
    values = [
        float(row["TofUs"])
        for row in _rows(run / "results" / "simion_downstream_particles.csv")
        if row["Hit"].strip().lower() == "true"
    ]
    return np.asarray(values, dtype=float)


def analyze(
    formal_run: Path,
    wide_interface: Path,
    small_interface: Path,
    wide_analyzer: Path,
    small_analyzer: Path,
    launched_particles: int,
) -> tuple[dict[str, object], dict[str, object]]:
    for run in (formal_run, wide_interface, small_interface, wide_analyzer, small_analyzer):
        _manifest(run)
    wide_config = json.loads((wide_interface / "run_config.json").read_text(encoding="utf-8"))
    small_config = json.loads((small_interface / "run_config.json").read_text(encoding="utf-8"))
    pulse_time_us = float(wide_config["parameters"]["pulse_time_us"])
    if not np.isclose(pulse_time_us, float(small_config["parameters"]["pulse_time_us"]), atol=1e-12):
        raise ValueError("aperture branches do not share one pulse time")

    canonical = _rows(wide_interface / "inputs" / "canonical_oatof_entry.csv")
    small_canonical = _rows(small_interface / "inputs" / "canonical_oatof_entry.csv")
    if canonical != small_canonical:
        raise ValueError("aperture branches do not use the same frozen particles")
    predicted: dict[int, dict[str, float]] = {}
    handoff: dict[int, dict[str, float]] = {}
    for row in canonical:
        particle_id = int(row["particle_id"])
        dt_us = pulse_time_us - float(row["instrument_time_us"])
        handoff[particle_id] = {axis: float(row[f"position_{axis}_mm"]) for axis in "xyz"}
        predicted[particle_id] = {
            axis: handoff[particle_id][axis] + float(row[f"velocity_{axis}_m_s"]) * dt_us / 1000.0
            for axis in "xyz"
        }

    cohorts = {
        "all": set(predicted),
        "wide": _hit_particle_ids(wide_interface),
        "small": _hit_particle_ids(small_interface),
    }
    if not cohorts["small"].issubset(cohorts["all"]) or not cohorts["wide"].issubset(cohorts["all"]):
        raise ValueError("aperture survivor identity escapes the frozen mother cohort")

    ideal_rows = _rows(formal_run / "results" / "source_mapping_particles.csv")
    ideal = [
        {axis: float(row[f"initial_{axis}_mm"]) for axis in "xyz"}
        for row in ideal_rows
    ]
    spatial: dict[str, object] = {
        "ideal": {"particles": len(ideal), **{
            axis: _stats([row[axis] for row in ideal]) for axis in "xyz"
        }}
    }
    for name, ids in cohorts.items():
        spatial[name] = {
            "particles": len(ids),
            **{axis: _stats([predicted[item][axis] for item in ids]) for axis in "xyz"},
            "inside_ideal_source_volume": sum(
                all(abs(predicted[item][axis] - IDEAL_CENTER[axis]) <= IDEAL_HALF_MM for axis in "xyz")
                for item in ids
            ),
        }
        spatial[name]["inside_ideal_source_volume_fraction"] = (
            spatial[name]["inside_ideal_source_volume"] / len(ids)
        )

    tof = {"wide": _detector_tof(wide_analyzer), "small": _detector_tof(small_analyzer)}
    resolution: dict[str, object] = {}
    spectra: dict[str, object] = {}
    for name, values in tof.items():
        resolution[name], spectra[name] = compute_peak_metrics(values, 100.0)
    formal_metrics = json.loads(
        (formal_run / "results" / "comparison_metrics.json").read_text(encoding="utf-8")
    )
    ideal_resolution = formal_metrics["right"]["metrics"]

    handoff_count = len(canonical)
    detector_counts = {name: len(values) for name, values in tof.items()}
    transport = {
        "launched_particles": launched_particles,
        "octupole_handoff_particles": handoff_count,
        "octupole_handoff_transmission": handoff_count / launched_particles,
        "wide": {
            "aperture_mm": [1.0, 0.9],
            "interface_exit_particles": len(cohorts["wide"]),
            "interface_conditional_transmission": len(cohorts["wide"]) / handoff_count,
            "detector_particles": detector_counts["wide"],
            "total_transmission_from_launched": detector_counts["wide"] / launched_particles,
        },
        "small": {
            "aperture_mm": [0.5, 0.5],
            "interface_exit_particles": len(cohorts["small"]),
            "interface_conditional_transmission": len(cohorts["small"]) / handoff_count,
            "detector_particles": detector_counts["small"],
            "total_transmission_from_launched": detector_counts["small"] / launched_particles,
        },
    }
    transport["small_vs_wide_detector_transmission_ratio"] = (
        detector_counts["small"] / detector_counts["wide"]
    )

    result = {
        "schema_version": 1,
        "role": "octupole_oatof_aperture_comparison_diagnostic",
        "status": "INCONCLUSIVE_DIAGNOSTIC_ONLY",
        "pulse_time_us": pulse_time_us,
        "spatial_model": "field-free ballistic left-limit projection from the common oaTOF handoff state",
        "spatial_distribution_at_pulse": spatial,
        "transport": transport,
        "resolution": {
            "ideal_simion_n1000_mass524": {
                key: ideal_resolution[key]
                for key in ("particles", "mean_tof_us", "direct_fwhm_tof_ns", "mass_resolution")
            },
            "wide_mass100": resolution["wide"],
            "small_mass100": resolution["small"],
        },
        "comparison_limits": [
            "aperture results are one N=1000 mother-cohort diagnostic without aperture or mesh convergence",
            "ideal reference uses mass 524 Da while octupole-fed branches use mass 100 Da",
            "direct KDE FWHM is estimator-equivalent, but detector sample sizes differ (1000, 396, 90)",
        ],
        "claims": {"diagnostic_only": True, "formal_resolution_claim_allowed": False},
    }
    data = {"ideal": ideal, "predicted": predicted, "handoff": handoff, "cohorts": cohorts,
            "tof": tof, "spectra": spectra}
    return result, data


def plot(result: dict[str, object], data: dict[str, object], output: Path) -> None:
    figure, axes = plt.subplots(2, 3, figsize=(16, 9.2), constrained_layout=True)
    predicted, cohorts = data["predicted"], data["cohorts"]

    ax = axes[0, 0]
    handoff = data["handoff"]
    ax.scatter([v["y"] for v in handoff.values()], [v["z"] for v in handoff.values()],
               s=9, alpha=0.35, color=COLORS["all"], label="N=459 handoff")
    for name, width, height in (("1.0×0.9 mm", 1.0, 0.9), ("0.5×0.5 mm", 0.5, 0.5)):
        ax.add_patch(Rectangle((-width / 2, IDEAL_CENTER["z"] - height / 2), width, height,
                               fill=False, linewidth=2, label=name))
    ax.set(title="A  Common handoff cohort and apertures", xlabel="y / mm", ylabel="z / mm")
    ax.set_aspect("equal", adjustable="box"); ax.legend(fontsize=8); ax.grid(alpha=0.2)

    ax = axes[0, 1]
    ax.add_patch(Rectangle((IDEAL_CENTER["x"] - 0.5, IDEAL_CENTER["z"] - 0.5), 1, 1,
                           fill=False, color=COLORS["ideal"], linewidth=2, label="ideal 1 mm source"))
    for name in ("wide", "small"):
        ids = cohorts[name]
        ax.scatter([predicted[i]["x"] for i in ids], [predicted[i]["z"] for i in ids],
                   s=10, alpha=0.45, color=COLORS[name], label=f"{name} survivors")
    ax.set(title="B  Ballistic position at pulse left limit", xlabel="x / mm", ylabel="z / mm")
    ax.legend(fontsize=8); ax.grid(alpha=0.2)

    ax = axes[0, 2]
    spatial = result["spatial_distribution_at_pulse"]
    for index, axis in enumerate("xyz"):
        for offset, name in enumerate(("ideal", "all", "wide", "small")):
            stats = spatial[name][axis]
            ax.errorbar(index + (offset - 1.5) * 0.15, stats["mean"] - IDEAL_CENTER[axis],
                        yerr=stats["sample_sigma"], fmt="o", capsize=2, color=COLORS[name],
                        label=name if index == 0 else None)
    ax.axhline(0, color="#555555", linewidth=1); ax.set_xticks(range(3), list("xyz"))
    ax.set(title="C  Centroid offset ± sample σ", ylabel="offset from ideal center / mm")
    ax.legend(fontsize=8); ax.grid(axis="y", alpha=0.25)

    ax = axes[1, 0]
    transport = result["transport"]
    labels = ["octupole\nhandoff", "1.0×0.9\ninterface", "1.0×0.9\ndetector",
              "0.5×0.5\ninterface", "0.5×0.5\ndetector"]
    counts = [transport["octupole_handoff_particles"], transport["wide"]["interface_exit_particles"],
              transport["wide"]["detector_particles"], transport["small"]["interface_exit_particles"],
              transport["small"]["detector_particles"]]
    bars = ax.bar(range(5), np.asarray(counts) / transport["launched_particles"] * 100,
                  color=[COLORS["all"], COLORS["wide"], COLORS["wide"], COLORS["small"], COLORS["small"]])
    ax.bar_label(bars, labels=[f"{n}\n({n / transport['launched_particles']:.1%})" for n in counts], fontsize=8)
    ax.set_xticks(range(5), labels); ax.set_ylim(0, 55); ax.set_ylabel("fraction of launched N=1000 / %")
    ax.set(title="D  End-to-end transmission census"); ax.grid(axis="y", alpha=0.25)

    ax = axes[1, 1]
    for name in ("wide", "small"):
        spectrum = data["spectra"][name]
        centered_ns = (spectrum["time_grid_us"] - np.mean(data["tof"][name])) * 1000
        ax.plot(centered_ns, spectrum["time_density_normalized"], color=COLORS[name], label=name)
    ax.set(title="E  Detector TOF KDE (centered)", xlabel="TOF − mean / ns", ylabel="normalized density")
    ax.legend(); ax.grid(alpha=0.25)

    ax = axes[1, 2]
    resolution = result["resolution"]
    names = ("ideal_simion_n1000_mass524", "wide_mass100", "small_mass100")
    values = [resolution[name]["mass_resolution"] for name in names]
    bars = ax.bar(range(3), values, color=[COLORS["ideal"], COLORS["wide"], COLORS["small"]])
    ax.bar_label(bars, labels=[f"{value:.0f}" for value in values], fontsize=9)
    ax.set_yscale("log"); ax.set_xticks(range(3), ["ideal SIMION\nN=1000", "1.0×0.9\nNhit=396", "0.5×0.5\nNhit=90"])
    ax.set(title="F  Direct-KDE mass resolution", ylabel="R = m/Δm")
    ax.grid(axis="y", alpha=0.25, which="both")

    figure.suptitle("Octupole N=1000 → oaTOF aperture comparison\nINCONCLUSIVE_DIAGNOSTIC_ONLY", fontsize=14)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=190)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--formal-run", required=True, type=Path)
    parser.add_argument("--wide-interface", required=True, type=Path)
    parser.add_argument("--small-interface", required=True, type=Path)
    parser.add_argument("--wide-analyzer", required=True, type=Path)
    parser.add_argument("--small-analyzer", required=True, type=Path)
    parser.add_argument("--launched-particles", required=True, type=int)
    parser.add_argument("--output-figure", required=True, type=Path)
    parser.add_argument("--output-metrics", required=True, type=Path)
    args = parser.parse_args()
    result, data = analyze(args.formal_run, args.wide_interface, args.small_interface,
                           args.wide_analyzer, args.small_analyzer, args.launched_particles)
    plot(result, data, args.output_figure)
    args.output_metrics.parent.mkdir(parents=True, exist_ok=True)
    args.output_metrics.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("OCTUPOLE_APERTURE_COMPARISON=PASS")


if __name__ == "__main__":
    main()
