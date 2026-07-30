"""Analyze nested N=100 and N=1000 multipole transport samples."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any, Iterable

from common.multipole.followup_analysis import load_resolution, paired_report
from common.multipole.numerical_qualification import (
    load_json,
    manifest_record,
    observable_differences,
    run_data,
)

CONTINUOUS_METRICS = {
    "rms_radius_mm": ("radial_position_mm", "rms"),
    "rms_divergence_deg": ("divergence_angle_deg", "rms"),
    "mean_energy_eV": ("kinetic_energy_eV", "mean"),
    "mean_tof_us": ("elapsed_time_us", "mean"),
}


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _metric(values: Iterable[float], method: str) -> float:
    samples = list(values)
    if not samples:
        raise ValueError("continuous observable has no transmitted samples")
    if method == "mean":
        return sum(samples) / len(samples)
    if method == "rms":
        return math.sqrt(sum(value * value for value in samples) / len(samples))
    raise ValueError(f"unknown metric method: {method}")


def observables_for_ids(data: dict[str, Any], source_ids: list[int]) -> dict[str, float]:
    handoff = data["_handoff"]
    transmitted = [particle_id for particle_id in source_ids if particle_id in handoff]
    result = {"transmission_fraction": len(transmitted) / len(source_ids)}
    for name, (field, method) in CONTINUOUS_METRICS.items():
        result[name] = _metric(
            (float(handoff[particle_id][field]) for particle_id in transmitted), method
        )
    return result


def bootstrap_intervals(
    data: dict[str, Any],
    *,
    resamples: int,
    seed: int,
    confidence_level: float,
) -> dict[str, dict[str, float]]:
    source_ids = data["source_particle_ids"]
    rng = random.Random(seed)
    distributions: dict[str, list[float]] = {
        "transmission_fraction": [],
        **{name: [] for name in CONTINUOUS_METRICS},
    }
    for _ in range(resamples):
        sampled_ids = rng.choices(source_ids, k=len(source_ids))
        values = observables_for_ids(data, sampled_ids)
        for name, value in values.items():
            distributions[name].append(value)
    tail = (1.0 - confidence_level) / 2.0
    point = observables_for_ids(data, source_ids)
    return {
        name: {
            "estimate": point[name],
            "lower": _percentile(values, tail),
            "upper": _percentile(values, 1.0 - tail),
        }
        for name, values in distributions.items()
    }


def bootstrap_intervals_for_size(
    data: dict[str, Any],
    *,
    sample_size: int,
    resamples: int,
    seed: int,
    confidence_level: float,
) -> dict[str, dict[str, float]]:
    source_ids = data["source_particle_ids"]
    rng = random.Random(seed)
    distributions = {name: [] for name in CONTINUOUS_METRICS}
    for _ in range(resamples):
        values = observables_for_ids(data, rng.choices(source_ids, k=sample_size))
        for name in CONTINUOUS_METRICS:
            distributions[name].append(values[name])
    tail = (1.0 - confidence_level) / 2.0
    full_estimates = observables_for_ids(data, source_ids)
    return {
        name: {
            "full_n1000_reference": full_estimates[name],
            "lower": _percentile(values, tail),
            "upper": _percentile(values, 1.0 - tail),
            "relative_half_width": (
                (_percentile(values, 1.0 - tail) - _percentile(values, tail))
                / (2.0 * abs(full_estimates[name]))
            ),
        }
        for name, values in distributions.items()
    }


def verify_nested_sources(
    *,
    repo_root: Path,
    preregistration: dict[str, Any],
) -> dict[str, Any]:
    contract = preregistration["nested_source_contract"]
    n100_path = repo_root / contract["n100_path"]
    n1000_path = repo_root / contract["n1000_path"]
    if _sha256(n100_path) != contract["n100_sha256"]:
        raise ValueError("N=100 source hash differs from preregistration")
    if _sha256(n1000_path) != contract["n1000_sha256"]:
        raise ValueError("N=1000 source hash differs from preregistration")
    with n100_path.open(encoding="utf-8-sig", newline="") as handle:
        n100_rows = list(csv.DictReader(handle))
    with n1000_path.open(encoding="utf-8-sig", newline="") as handle:
        n1000_rows = list(csv.DictReader(handle))
    if n100_rows != n1000_rows[: len(n100_rows)]:
        raise ValueError("N=100 source is not the exact ordered N=1000 prefix")
    return {
        "status": "PASS",
        "n100_count": len(n100_rows),
        "n1000_count": len(n1000_rows),
        "exact_ordered_prefix": True,
    }


def prefix_reproduction(
    n100: dict[str, Any], n1000: dict[str, Any]
) -> dict[str, Any]:
    ids = n100["source_particle_ids"]
    if ids != n1000["source_particle_ids"][: len(ids)]:
        raise ValueError("run source particle IDs do not preserve the nested prefix")
    if set(ids) != set(n100["_handoff"]) or not set(ids).issubset(n1000["_handoff"]):
        raise ValueError("prefix reproduction requires all prefix particles at handoff")
    fields = (
        "elapsed_time_us",
        "axial_z_mm",
        "transverse_x_mm",
        "transverse_y_mm",
        "velocity_axial_m_s",
        "velocity_x_m_s",
        "velocity_y_m_s",
        "kinetic_energy_eV",
    )
    by_field = {}
    for field in fields:
        differences = [
            float(n100["_handoff"][particle_id][field])
            - float(n1000["_handoff"][particle_id][field])
            for particle_id in ids
        ]
        by_field[field] = {
            "maximum_absolute_difference": max(abs(value) for value in differences),
            "rms_difference": math.sqrt(
                sum(value * value for value in differences) / len(differences)
            ),
        }
    return {
        "status": "PASS",
        "particle_count": len(ids),
        "field_differences": by_field,
    }


def _relative_change(n100: float, n1000: float) -> float:
    return (n1000 - n100) / n100 if n100 else 0.0


def wilson_interval(successes: int, total: int) -> dict[str, float]:
    if total <= 0 or successes < 0 or successes > total:
        raise ValueError("Wilson interval requires 0 <= successes <= positive total")
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    half_width = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / total
            + z * z / (4.0 * total * total)
        )
        / denominator
    )
    return {
        "estimate": proportion,
        "lower": max(0.0, center - half_width),
        "upper": min(1.0, center + half_width),
    }


def case_transmission_summary(data: dict[str, Any]) -> dict[str, Any]:
    metrics = load_json(
        manifest_record(data["manifest"], "finite_3d_transport_metrics.json")
    )
    cases = metrics.get("cases", {})
    primary_id = metrics.get("primary_case_id")
    control_id = metrics.get("control_case_id")
    if primary_id not in cases or control_id not in cases:
        raise ValueError("transport metrics do not contain primary and control cases")

    def summarize(case_id: str) -> dict[str, Any]:
        case = cases[case_id]
        particles = int(case["particles"])
        transmitted = int(
            case.get("transmitted", case.get("hits", case.get("census_plane_crossings")))
        )
        return {
            "case_id": case_id,
            "particles": particles,
            "transmitted": transmitted,
            "transmission_fraction": transmitted / particles,
            "wilson_95_interval": wilson_interval(transmitted, particles),
        }

    return {
        "primary": summarize(str(primary_id)),
        "zero_rf_control": summarize(str(control_id)),
    }


def analyze(
    *,
    repo_root: Path,
    preregistration_path: Path,
    n100_manifest: Path,
    n1000_manifest: Path,
    comsol_manifest: Path,
    comsol_n1000_manifest: Path | None = None,
    comsol_n100_t320_manifest: Path | None = None,
    resolution_path: Path | None = None,
) -> dict[str, Any]:
    preregistration = _load_json(preregistration_path)
    analysis_contract = preregistration["analysis_contract"]
    n100 = run_data(n100_manifest)
    n1000 = run_data(n1000_manifest)
    comsol = run_data(comsol_manifest)
    if n100["solver"] != "SIMION" or n1000["solver"] != "SIMION":
        raise ValueError("nested sampling comparison requires two SIMION runs")
    if comsol["solver"] != "COMSOL":
        raise ValueError("cross-solver reference must be COMSOL")
    if n100["numerics"] != n1000["numerics"]:
        raise ValueError("N=100 and N=1000 SIMION numerics differ")
    if n100["physical_resolved_design_sha256"] != n1000["physical_resolved_design_sha256"]:
        raise ValueError("N=100 and N=1000 physical designs differ")
    if n100["source_particle_ids"] != comsol["source_particle_ids"]:
        raise ValueError("SIMION and COMSOL N=100 source particle IDs differ")

    nested = verify_nested_sources(
        repo_root=repo_root, preregistration=preregistration
    )
    prefix = prefix_reproduction(n100, n1000)
    n100_values = observables_for_ids(n100, n100["source_particle_ids"])
    n1000_values = observables_for_ids(n1000, n1000["source_particle_ids"])
    prefix_values = observables_for_ids(
        n1000, n1000["source_particle_ids"][: len(n100["source_particle_ids"])]
    )
    comsol_values = observables_for_ids(comsol, comsol["source_particle_ids"])
    seed = int(analysis_contract["bootstrap_seed"])
    resamples = int(analysis_contract["bootstrap_resamples"])
    confidence = float(analysis_contract["confidence_level"])
    result = {
        "schema_version": 1,
        "role": "multipole_n1000_sampling_result",
        "status": "PASS",
        "project_id": n100["project"],
        "source_contract": nested,
        "run_ids": {
            "simion_n100": n100["run_id"],
            "simion_n1000": n1000["run_id"],
            "comsol_n100_reference": comsol["run_id"],
        },
        "prefix_reproduction": prefix,
        "sampling_comparison": {
            "simion_n100": n100_values,
            "simion_n1000_prefix100": prefix_values,
            "simion_n1000_full": n1000_values,
            "relative_change_n100_to_n1000": {
                name: _relative_change(n100_values[name], n1000_values[name])
                for name in n100_values
            },
            "bootstrap": {
                "method": analysis_contract["bootstrap_method"],
                "resamples": resamples,
                "seed": seed,
                "confidence_level": confidence,
                "n100": bootstrap_intervals(
                    n100,
                    resamples=resamples,
                    seed=seed,
                    confidence_level=confidence,
                ),
                "n1000": bootstrap_intervals(
                    n1000,
                    resamples=resamples,
                    seed=seed + 1,
                    confidence_level=confidence,
                ),
            },
            "interpretation_limit": (
                "The samples are nested, not independent. Intervals quantify "
                "source-sample uncertainty only, not numerical or physical-model error."
            ),
        },
        "cross_solver_n100_reference": {
            "simion": n100_values,
            "comsol": comsol_values,
            "comsol_bootstrap": bootstrap_intervals(
                comsol,
                resamples=resamples,
                seed=seed + 2,
                confidence_level=confidence,
            ),
            "relative_change_simion_to_comsol": {
                name: _relative_change(n100_values[name], comsol_values[name])
                for name in n100_values
            },
            "existing_normalized_and_paired_differences": observable_differences(
                n100, comsol
            ),
            "interpretation_limit": (
                "This is a common-source N=100 reference comparison. Solver and "
                "numerical-discretization effects remain combined; it is not an "
                "accuracy ranking."
            ),
        },
        "posthoc_sample_size_diagnostic": {
            "status": "POSTHOC_DESCRIPTIVE",
            "method": (
                "Bootstrap samples of size 100, 300, 500 and 1000 drawn from the "
                "completed SIMION N=1000 empirical distribution."
            ),
            "intervals_by_sample_size": {
                str(sample_size): bootstrap_intervals_for_size(
                    n1000,
                    sample_size=sample_size,
                    resamples=resamples,
                    seed=seed + 100 + sample_size,
                    confidence_level=confidence,
                )
                for sample_size in (100, 300, 500, 1000)
            },
            "interpretation_limit": (
                "This diagnostic was selected after observing the N=1000 result. "
                "It estimates source-sample precision and is not a preregistered "
                "acceptance test or a substitute for a new independent sample."
            ),
        },
        "claim_limit": preregistration["claim_limit"],
    }
    if comsol_n1000_manifest is None:
        return result
    if comsol_n100_t320_manifest is None or resolution_path is None:
        raise ValueError(
            "COMSOL N=1000 bridge requires the N=100 t320 and resolution inputs"
        )
    comsol_n1000 = run_data(comsol_n1000_manifest)
    comsol_n100_t320 = run_data(comsol_n100_t320_manifest)
    if comsol_n1000["solver"] != "COMSOL" or comsol_n100_t320["solver"] != "COMSOL":
        raise ValueError("COMSOL bridge inputs are mislabeled")
    if comsol["numerics"] != comsol_n1000["numerics"]:
        raise ValueError("COMSOL N=100 and N=1000 t160 numerics differ")
    physical_hashes = {
        n100["physical_resolved_design_sha256"],
        n1000["physical_resolved_design_sha256"],
        comsol["physical_resolved_design_sha256"],
        comsol_n1000["physical_resolved_design_sha256"],
        comsol_n100_t320["physical_resolved_design_sha256"],
    }
    if len(physical_hashes) != 1:
        raise ValueError("bridge runs contain different physical resolved designs")
    if (
        comsol["source_particle_ids"]
        != comsol_n1000["source_particle_ids"][: len(comsol["source_particle_ids"])]
    ):
        raise ValueError("COMSOL N=100 source IDs are not the N=1000 prefix")
    if n1000["particle_source_sha256"] != comsol_n1000["particle_source_sha256"]:
        raise ValueError("SIMION and COMSOL N=1000 particle sources differ")

    resolution = load_resolution(resolution_path)
    comsol_n1000_values = observables_for_ids(
        comsol_n1000, comsol_n1000["source_particle_ids"]
    )
    simion_shift = result["sampling_comparison"]["relative_change_n100_to_n1000"]
    comsol_shift = {
        name: _relative_change(comsol_values[name], comsol_n1000_values[name])
        for name in comsol_values
    }
    result["comsol_bridge"] = {
        "run_ids": {
            "comsol_n100_t160": comsol["run_id"],
            "comsol_n100_t320": comsol_n100_t320["run_id"],
            "comsol_n1000_t160": comsol_n1000["run_id"],
            "simion_n1000": n1000["run_id"],
        },
        "comsol_n100_to_n1000_prefix_reproduction": prefix_reproduction(
            comsol, comsol_n1000
        ),
        "comsol_n1000": comsol_n1000_values,
        "comsol_n1000_bootstrap": bootstrap_intervals(
            comsol_n1000,
            resamples=resamples,
            seed=seed + 3,
            confidence_level=confidence,
        ),
        "relative_sampling_shift_by_solver": {
            "simion": simion_shift,
            "comsol": comsol_shift,
            "comsol_minus_simion": {
                name: comsol_shift[name] - simion_shift[name]
                for name in simion_shift
            },
        },
        "paired_comparisons": {
            "comsol_n100_t160_to_t320": paired_report(
                comsol, comsol_n100_t320, resolution
            ),
            "simion_to_comsol_n1000": paired_report(
                n1000, comsol_n1000, resolution
            ),
        },
        "transmission_cases": {
            "simion_n100": case_transmission_summary(n100),
            "simion_n1000": case_transmission_summary(n1000),
            "comsol_n100": case_transmission_summary(comsol),
            "comsol_n1000": case_transmission_summary(comsol_n1000),
        },
        "interpretation_limit": (
            "Sampling shifts and common-source paired differences are descriptive. "
            "They do not establish solver equivalence, superiority, or absolute accuracy."
        ),
    }
    return result


def plot_sampling_result(result: dict[str, Any], output: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    sampling = result["sampling_comparison"]
    bootstrap = sampling["bootstrap"]
    cross_solver = result["cross_solver_n100_reference"]
    comsol = cross_solver["comsol"]
    comsol_bootstrap = cross_solver["comsol_bootstrap"]
    labels = {
        "rms_radius_mm": "RMS radius",
        "rms_divergence_deg": "RMS divergence",
        "mean_energy_eV": "Mean energy",
        "mean_tof_us": "Mean time of flight",
    }
    units = {
        "rms_radius_mm": "mm",
        "rms_divergence_deg": "deg",
        "mean_energy_eV": "eV",
        "mean_tof_us": "us",
    }
    fig, axes = plt.subplots(2, 2, figsize=(10.5, 7.5), constrained_layout=True)
    colors = ("#4477AA", "#228833", "#CC6677")
    for axis, name in zip(axes.flat, labels, strict=True):
        n100 = bootstrap["n100"][name]
        n1000 = bootstrap["n1000"][name]
        estimates = [n100["estimate"], n1000["estimate"], comsol[name]]
        tick_labels = ("SIMION\nN=100", "SIMION\nN=1000", "COMSOL\nN=100")
        lower = [
            n100["estimate"] - n100["lower"],
            n1000["estimate"] - n1000["lower"],
            comsol[name] - comsol_bootstrap[name]["lower"],
        ]
        upper = [
            n100["upper"] - n100["estimate"],
            n1000["upper"] - n1000["estimate"],
            comsol_bootstrap[name]["upper"] - comsol[name],
        ]
        if "comsol_bridge" in result:
            bridge = result["comsol_bridge"]
            comsol_n1000 = bridge["comsol_n1000"][name]
            comsol_n1000_bootstrap = bridge["comsol_n1000_bootstrap"][name]
            estimates.append(comsol_n1000)
            lower.append(comsol_n1000 - comsol_n1000_bootstrap["lower"])
            upper.append(comsol_n1000_bootstrap["upper"] - comsol_n1000)
            tick_labels = (
                "SIMION\nN=100",
                "SIMION\nN=1000",
                "COMSOL\nN=100",
                "COMSOL\nN=1000",
            )
        plot_colors = colors if len(estimates) == 3 else (*colors, "#AA4499")
        for index, (estimate, color) in enumerate(
            zip(estimates, plot_colors, strict=True)
        ):
            axis.errorbar(
                index,
                estimate,
                yerr=([lower[index]], [upper[index]]),
                fmt="o",
                color=color,
                capsize=4,
                markersize=7,
            )
        axis.set_xticks(range(len(tick_labels)), tick_labels)
        axis.set_title(labels[name])
        axis.set_ylabel(units[name])
        axis.grid(axis="y", alpha=0.25)
    fig.suptitle(
        "Quadrupole no-acceleration sampling comparison\n"
        "Error bars: preregistered 95% source-sample bootstrap intervals",
        fontsize=13,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--preregistration", required=True, type=Path)
    parser.add_argument("--n100-manifest", required=True, type=Path)
    parser.add_argument("--n1000-manifest", required=True, type=Path)
    parser.add_argument("--comsol-manifest", required=True, type=Path)
    parser.add_argument("--comsol-n1000-manifest", type=Path)
    parser.add_argument("--comsol-n100-t320-manifest", type=Path)
    parser.add_argument("--resolution", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--plot", type=Path)
    args = parser.parse_args()
    result = analyze(
        repo_root=args.repo_root.resolve(),
        preregistration_path=args.preregistration.resolve(),
        n100_manifest=args.n100_manifest.resolve(),
        n1000_manifest=args.n1000_manifest.resolve(),
        comsol_manifest=args.comsol_manifest.resolve(),
        comsol_n1000_manifest=(
            args.comsol_n1000_manifest.resolve()
            if args.comsol_n1000_manifest is not None
            else None
        ),
        comsol_n100_t320_manifest=(
            args.comsol_n100_t320_manifest.resolve()
            if args.comsol_n100_t320_manifest is not None
            else None
        ),
        resolution_path=(
            args.resolution.resolve() if args.resolution is not None else None
        ),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if args.plot is not None:
        plot_sampling_result(result, args.plot)
    print(
        "MULTIPOLE_N1000_SAMPLING=PASS "
        f"PROJECT={result['project_id']} OUTPUT={args.output.resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
