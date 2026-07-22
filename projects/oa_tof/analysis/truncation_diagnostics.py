"""Diagnose how source and detector acceptance cuts change oa-TOF peaks."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from projects.oa_tof.analysis.mass_spectrum import load_mode
from projects.oa_tof.analysis.peak_metrics import (
    AnalysisSettings,
    bootstrap_resolution_distribution,
    compute_peak_metrics,
)
from projects.oa_tof.analysis.reference_analysis import read_particle_table


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _paired_frames(left_path: Path, right_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    left, _ = read_particle_table(left_path)
    right, _ = read_particle_table(right_path)
    left = left.sort_values("particle_id").reset_index(drop=True)
    right = right.sort_values("particle_id").reset_index(drop=True)
    if not np.array_equal(left["particle_id"], right["particle_id"]):
        raise ValueError("Truncation diagnostics require identical paired particle IDs")
    required = {
        "initial_x_mm", "initial_y_mm", "initial_z_mm", "initial_energy_eV",
        "detector_x_mm", "detector_y_mm",
    }
    for label, frame in (("left", left), ("right", right)):
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"{label} particle table lacks {sorted(missing)}")
    for column in ("initial_x_mm", "initial_y_mm", "initial_z_mm", "initial_energy_eV"):
        if not np.allclose(left[column], right[column], rtol=0, atol=1e-9):
            raise ValueError(f"Paired source column differs across solvers: {column}")
    return left, right


def _family_masks(
    mode: dict[str, Any], frame: pd.DataFrame, family: str
) -> list[tuple[str, float, np.ndarray]]:
    diagnostic = mode["truncation_diagnostic"]
    if family == "energy":
        values = frame["initial_energy_eV"].to_numpy()
        result = []
        for low, high in diagnostic["energy_windows_ev"]:
            if low is None:
                result.append(("all", np.inf, np.ones(len(frame), dtype=bool)))
            else:
                result.append((f"{low:g}-{high:g} eV", float(high - low), (values >= low) & (values <= high)))
        return result
    if family == "radius":
        radius = np.hypot(frame["detector_x_mm"], frame["detector_y_mm"])
        return [
            (f"r <= {limit:g} mm", float(limit), radius <= float(limit))
            for limit in diagnostic["active_radius_limits_mm"]
        ]
    if family == "source_z":
        source_center = float(
            json.loads(
                (Path(__file__).resolve().parents[1] / "config" / "resolved_geometry.json").read_text(encoding="utf-8")
            )["particle_source"]["center_z_mm"]
        )
        z = frame["initial_z_mm"].to_numpy()
        return [
            (
                f"z width {width:g} mm", float(width),
                np.abs(z - source_center) <= 0.5 * float(width),
            )
            for width in diagnostic["source_z_widths_mm"]
        ]
    raise ValueError(f"Unknown cut family: {family}")


def _evaluate_policy(
    frames: dict[str, pd.DataFrame],
    masks: dict[str, list[tuple[str, float, np.ndarray]]],
    family: str,
    policy: str,
    nominal_mass: float,
    resamples: int,
    seed: int,
    settings: AnalysisSettings,
) -> list[dict[str, Any]]:
    common_count = min(int(np.count_nonzero(mask)) for values in masks.values() for _, _, mask in values)
    if common_count < 20:
        raise ValueError(f"{family}/{policy} retains only {common_count} particles")
    records: list[dict[str, Any]] = []
    ordinal = 0
    for solver, frame in frames.items():
        for label, threshold, mask in masks[solver]:
            ordinal += 1
            tof = frame.loc[mask, "tof_us"].to_numpy()
            exact, _ = compute_peak_metrics(tof, nominal_mass, settings)
            bootstrap = bootstrap_resolution_distribution(
                tof,
                nominal_mass,
                resamples=resamples,
                seed=seed + ordinal,
                sample_size=common_count,
                replace=False,
                settings=settings,
            )
            median_r = bootstrap["resolution_median"]
            records.append(
                {
                    "family": family,
                    "acceptance_policy": policy,
                    "solver": solver,
                    "cut": label,
                    "threshold": threshold,
                    "retained": int(mask.sum()),
                    "retained_fraction": float(mask.mean()),
                    "matched_sample_size": common_count,
                    "exact_fwhm_mass_Da": exact["direct_fwhm_mass_Da"],
                    "exact_resolution": exact["mass_resolution"],
                    "matched_fwhm_mass_Da_median": nominal_mass / median_r,
                    "matched_fwhm_mass_Da_p2p5": nominal_mass / bootstrap["resolution_p97p5"],
                    "matched_fwhm_mass_Da_p97p5": nominal_mass / bootstrap["resolution_p2p5"],
                    "matched_resolution_median": median_r,
                    "tof_skewness": exact["tof_skewness"],
                    "tof_excess_kurtosis": exact["tof_excess_kurtosis"],
                    "tail_fraction_outside_3sigma": exact["tail_fraction_outside_3sigma"],
                    "significant_kde_modes": exact["significant_kde_modes"],
                }
            )
    return records


def _common_intersection_masks(
    left_masks: list[tuple[str, float, np.ndarray]],
    right_masks: list[tuple[str, float, np.ndarray]],
) -> list[tuple[str, float, np.ndarray]]:
    if [item[0] for item in left_masks] != [item[0] for item in right_masks]:
        raise ValueError("Radius cut labels differ across solvers")
    return [
        (left[0], left[1], left[2] & right[2])
        for left, right in zip(left_masks, right_masks, strict=True)
    ]


def analyze_truncation(
    left_path: Path,
    right_path: Path,
    mode_path: Path,
    output_dir: Path,
    left_label: str = "COMSOL",
    right_label: str = "SIMION",
    nominal_mass: float = 524.0,
) -> dict[str, Any]:
    mode = load_mode(mode_path)
    left, right = _paired_frames(left_path, right_path)
    frames = {left_label: left, right_label: right}
    diagnostic = mode["truncation_diagnostic"]
    settings = AnalysisSettings()
    resamples = int(diagnostic["bootstrap_resamples"])
    seed = int(diagnostic["bootstrap_seed"])
    records: list[dict[str, Any]] = []
    masks_by_family: dict[str, dict[str, list[tuple[str, float, np.ndarray]]]] = {}

    for family in ("energy", "radius", "source_z"):
        solver_masks = {
            label: _family_masks(mode, frame, family)
            for label, frame in frames.items()
        }
        masks_by_family[family] = solver_masks
        policy = "solver_specific" if family == "radius" else "shared_source_gate"
        records.extend(
            _evaluate_policy(
                frames, solver_masks, family, policy, nominal_mass,
                resamples, seed + 10000 * (len(records) + 1), settings,
            )
        )
        if family == "radius":
            intersection = _common_intersection_masks(
                solver_masks[left_label], solver_masks[right_label]
            )
            paired_masks = {left_label: intersection, right_label: intersection}
            records.extend(
                _evaluate_policy(
                    frames, paired_masks, family, "paired_intersection",
                    nominal_mass, resamples, seed + 90000, settings,
                )
            )

    table = pd.DataFrame(records)
    output_dir.mkdir(parents=True, exist_ok=True)
    table.to_csv(output_dir / "truncation_metrics.csv", index=False)

    colors = {left_label: "#1f77b4", right_label: "#d62728"}
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5), constrained_layout=True)
    for axis, family in zip(axes, ("energy", "radius", "source_z"), strict=True):
        policy = "solver_specific" if family == "radius" else "shared_source_gate"
        selected = table[(table["family"] == family) & (table["acceptance_policy"] == policy)]
        for solver in (left_label, right_label):
            rows = selected[selected["solver"] == solver].sort_values("retained_fraction")
            y = rows["matched_fwhm_mass_Da_median"].to_numpy()
            lower = y - rows["matched_fwhm_mass_Da_p2p5"].to_numpy()
            upper = rows["matched_fwhm_mass_Da_p97p5"].to_numpy() - y
            axis.errorbar(
                100 * rows["retained_fraction"], y, yerr=np.vstack([lower, upper]),
                marker="o", capsize=3, color=colors[solver], label=solver,
            )
            for _, row in rows.iterrows():
                axis.annotate(str(row["cut"]), (100 * row["retained_fraction"], row["matched_fwhm_mass_Da_median"]), fontsize=7)
        axis.set(xlabel="retained particles (%)", ylabel="matched-N FWHM (Da)", title=family.replace("_", " "))
        axis.grid(alpha=0.25)
    axes[0].legend()
    fig.savefig(output_dir / "truncation_sensitivity.png", dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(3, 2, figsize=(11, 11), constrained_layout=True)
    rng = np.random.default_rng(seed)
    for row_index, family in enumerate(("energy", "radius", "source_z")):
        for column_index, solver in enumerate((left_label, right_label)):
            axis = axes[row_index, column_index]
            family_masks = masks_by_family[family][solver]
            common_n = min(int(mask.sum()) for _, _, mask in family_masks)
            for line_index, (label, _, mask) in enumerate((family_masks[0], family_masks[-1])):
                candidates = np.flatnonzero(mask)
                selected_ids = rng.choice(candidates, common_n, replace=False)
                metrics, spectra = compute_peak_metrics(
                    frames[solver].iloc[selected_ids]["tof_us"].to_numpy(), nominal_mass, settings
                )
                axis.plot(
                    spectra["mass_grid_Da"] - nominal_mass,
                    spectra["mass_density_normalized"],
                    label=f"{label}; N={common_n}",
                    linewidth=1.5,
                    linestyle="-" if line_index == 0 else "--",
                )
            axis.set(title=f"{solver}: {family.replace('_', ' ')}", xlabel="apparent mass - 524 (Da)", ylabel="normalized density")
            axis.legend(fontsize=8)
    fig.savefig(output_dir / "truncation_peak_overlays.png", dpi=180)
    plt.close(fig)

    result = {
        "schema_version": 1,
        "status": "PASS",
        "role": "oa_tof_formal_n1000_posthoc_truncation_diagnostic",
        "physical_interpretation": {
            "energy_and_source_z": "post-hoc gates are equivalent to source truncation only for this noninteracting, 100-percent-hit particle set",
            "radius": "post-hoc active-area acceptance mask; detector metal geometry and electrostatic field are unchanged",
            "formal_baseline_changed": False,
        },
        "python": platform.python_version(),
        "bootstrap_resamples": resamples,
        "inputs": {
            "left": {"path": str(left_path), "sha256": _sha256(left_path)},
            "right": {"path": str(right_path), "sha256": _sha256(right_path)},
            "mode": {"path": str(mode_path), "sha256": _sha256(mode_path)},
        },
        "records": table.to_dict(orient="records"),
    }
    (output_dir / "truncation_summary.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"TRUNCATION_DIAGNOSTIC=PASS OUTPUT={output_dir}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--left", required=True, type=Path)
    parser.add_argument("--right", required=True, type=Path)
    parser.add_argument("--mode-config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--left-label", default="COMSOL")
    parser.add_argument("--right-label", default="SIMION")
    parser.add_argument("--mass", type=float, default=524.0)
    args = parser.parse_args()
    analyze_truncation(
        args.left.resolve(), args.right.resolve(), args.mode_config.resolve(),
        args.output.resolve(), args.left_label, args.right_label, args.mass,
    )


if __name__ == "__main__":
    main()
