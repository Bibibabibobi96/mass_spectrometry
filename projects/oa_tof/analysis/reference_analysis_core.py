"""Implementation of the canonical oa-TOF peak-analysis workflow.

Examples
--------
Analyze one CSV or GUI-exported XLSX::

    python reference_analysis.py single INPUT --mass 524 --output OUTPUT

Verify all frozen migration baselines::

    python reference_analysis.py verify-baselines
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy
from scipy import stats

from projects.oa_tof.analysis.peak_metrics import (
    AnalysisSettings,
    bootstrap_resolution_difference,
    compare_peak_shapes,
    compute_detector_metrics,
    compute_peak_metrics,
    compute_paired_tof_delta_source_metrics,
    compute_source_mapping_metrics,
)


ANALYSIS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = ANALYSIS_DIR.parent
REPO_ROOT = PROJECT_DIR.parents[1]
DEFAULT_CONTRACT = PROJECT_DIR / "config" / "analysis_contract.json"
PHYSICAL_CONTRACT = PROJECT_DIR / "config" / "resolved_geometry.json"
_physical_geometry = json.loads(PHYSICAL_CONTRACT.read_text(encoding="utf-8"))
DEFAULT_DETECTOR_CENTER_X_MM = float(
    _physical_geometry["coordinate_convention"]["detector_x"]
)
DEFAULT_DETECTOR_CENTER_Y_MM = 0.0
DEFAULT_BASELINES = PROJECT_DIR / "config" / "analysis_baselines.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _normalized_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _find_column(
    frame: pd.DataFrame, aliases: tuple[str, ...], required: bool = False
) -> str | None:
    normalized = {_normalized_name(column): str(column) for column in frame.columns}
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    if required:
        raise ValueError(
            f"Required column not found; aliases={aliases}; columns={list(frame.columns)}"
        )
    return None


def _parse_hit(values: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(values):
        return values.fillna(False)
    normalized = values.astype(str).str.strip().str.lower()
    truthy = {"1", "true", "yes", "y", "hit", "splat"}
    falsy = {"0", "false", "no", "n", "miss", "nan", "none", ""}
    unknown = ~normalized.isin(truthy | falsy)
    if bool(unknown.any()):
        bad = sorted(normalized[unknown].unique().tolist())
        raise ValueError(f"Unrecognized hit values: {bad}")
    return normalized.isin(truthy)


def _read_source_table(path: Path) -> tuple[pd.DataFrame, str]:
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        return pd.read_excel(path, engine="openpyxl"), "Excel human import"
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path), "CSV machine source"
    if path.suffix.lower() in {".log", ".txt"}:
        pattern = re.compile(
            r"^TRACE:\s*detector_crossing\s+ion=(\d+)\s+"
            r"t=([-+0-9.eE]+)\s+x=([-+0-9.eE]+)\s+"
            r"y=([-+0-9.eE]+)\s+z=([-+0-9.eE]+)\s+"
            r"r=([-+0-9.eE]+)\s+zmax=([-+0-9.eE]+)"
        )
        records: list[dict[str, float | int | str]] = []
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                match = pattern.match(line.strip())
                if match is None:
                    continue
                records.append(
                    {
                        "Ion": int(match.group(1)),
                        "TofUs": float(match.group(2)),
                        "DetectorXmm": float(match.group(3)),
                        "DetectorYmm": float(match.group(4)),
                        "DetectorZmm": float(match.group(5)),
                        "RadiusMm": float(match.group(6)),
                        "ZMaxMm": float(match.group(7)),
                        "Event": "detector_crossing",
                    }
                )
        if not records:
            raise ValueError(f"No SIMION detector_crossing TRACE records found: {path}")
        return pd.DataFrame.from_records(records), "SIMION detector_crossing TRACE"
    raise ValueError(f"Unsupported input extension: {path.suffix}")


def read_particle_table(
    path: Path,
    detector_center_x_mm: float = DEFAULT_DETECTOR_CENTER_X_MM,
    detector_center_y_mm: float = DEFAULT_DETECTOR_CENTER_Y_MM,
    column_overrides: dict[str, str] | None = None,
    declared_event: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Normalize supported COMSOL/SIMION CSV or GUI XLSX columns."""

    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    source, source_format = _read_source_table(path)
    if source.empty:
        raise ValueError(f"Input table is empty: {path}")

    overrides = column_overrides or {}

    def source_column(
        canonical: str, aliases: tuple[str, ...], required: bool = False
    ) -> str | None:
        if canonical in overrides:
            selected = overrides[canonical]
            if selected not in source.columns:
                raise ValueError(
                    f"Configured {canonical} column {selected!r} is absent; "
                    f"columns={list(source.columns)}"
                )
            return selected
        return _find_column(source, aliases, required)

    ion_column = source_column(
        "particle_id",
        ("particleid", "ion", "ionnumber", "ionno", "particlenumber"),
    )
    tof_column = source_column(
        "tof_us", ("tofus", "timeofflightus", "tof", "timeofflight"), True
    )
    hit_column = source_column("hit", ("hit", "detected", "arrived"))

    particle_id_generated = ion_column is None
    particle_id = (
        np.arange(1, len(source) + 1, dtype=np.int64)
        if particle_id_generated
        else pd.to_numeric(source[ion_column], errors="coerce")
    )
    normalized = pd.DataFrame(
        {
            "particle_id": particle_id,
            "tof_us": pd.to_numeric(source[tof_column], errors="coerce"),
        }
    )
    if hit_column is not None:
        normalized["hit"] = _parse_hit(source[hit_column])
    else:
        normalized["hit"] = True

    local_x = source_column(
        "detector_local_x_mm",
        ("detectorlocalxmm", "localxmm", "impactlocalxmm"),
    )
    local_y = source_column(
        "detector_local_y_mm",
        ("detectorlocalymm", "localymm", "impactlocalymm"),
    )
    global_x = source_column("detector_x_mm", ("detectorxmm", "xmm", "x"))
    global_y = source_column("detector_y_mm", ("detectorymm", "ymm", "y"))
    if local_x is not None and local_y is not None:
        normalized["detector_x_mm"] = pd.to_numeric(source[local_x], errors="coerce")
        normalized["detector_y_mm"] = pd.to_numeric(source[local_y], errors="coerce")
    elif global_x is not None and global_y is not None:
        normalized["detector_x_mm"] = (
            pd.to_numeric(source[global_x], errors="coerce") - detector_center_x_mm
        )
        normalized["detector_y_mm"] = (
            pd.to_numeric(source[global_y], errors="coerce") - detector_center_y_mm
        )

    optional_columns = {
        "detector_z_mm": ("detectorzmm", "zmm", "z"),
        "logged_radius_mm": ("radiusmm", "rmm", "r"),
        "pa_instance": ("painstance", "painstanceno", "instance", "instanceid"),
        "initial_x_mm": ("x0mm", "initialxmm"),
        "initial_y_mm": ("y0mm", "initialymm"),
        "initial_z_mm": ("z0mm", "initialzmm"),
        "initial_energy_eV": ("energyev", "initialenergyev"),
    }
    for canonical, aliases in optional_columns.items():
        selected_column = source_column(canonical, aliases)
        if selected_column is not None:
            normalized[canonical] = pd.to_numeric(
                source[selected_column], errors="coerce"
            )
    event_column = source_column("event", ("event", "eventname", "eventtype"))
    if event_column is not None:
        normalized["event"] = (
            source[event_column].astype("string").fillna("").str.strip().astype(str)
        )
        event_provenance = "source_column"
    elif declared_event is not None and declared_event.strip():
        normalized["event"] = declared_event.strip()
        event_provenance = "operator_declared_from_data_recording_event_selection"
    else:
        event_provenance = "absent"
    if declared_event is not None and event_column is not None:
        declared = declared_event.strip().lower()
        recorded = normalized["event"].astype(str).str.strip().str.lower()
        if bool((recorded != declared).any()):
            raise ValueError("Declared event conflicts with values in the event column")

    if bool(normalized["particle_id"].isna().any()):
        raise ValueError("particle_id contains missing or nonnumeric values")
    if bool((normalized["particle_id"] % 1 != 0).any()):
        raise ValueError("particle_id must contain integers")
    normalized["particle_id"] = normalized["particle_id"].astype("int64")
    if bool(normalized["particle_id"].duplicated().any()):
        duplicates = normalized.loc[
            normalized["particle_id"].duplicated(), "particle_id"
        ].tolist()
        raise ValueError(f"Duplicate particle_id values: {duplicates[:10]}")
    detected = normalized.loc[normalized["hit"]].copy()
    if len(detected) < 3:
        raise ValueError("Fewer than three detected particles")
    if bool(detected["tof_us"].isna().any()) or bool(
        (~np.isfinite(detected["tof_us"])).any()
    ):
        raise ValueError("Detected particles contain missing or non-finite tof_us")
    if bool((detected["tof_us"] <= 0).any()):
        raise ValueError("Detected particles contain non-positive tof_us")
    for coordinate in ("detector_x_mm", "detector_y_mm"):
        if coordinate in detected and bool(detected[coordinate].isna().any()):
            raise ValueError(f"{coordinate} contains missing values")
    for numeric in ("detector_z_mm", "logged_radius_mm", "pa_instance"):
        if numeric in detected and bool(
            detected[numeric].isna().any() | (~np.isfinite(detected[numeric])).any()
        ):
            raise ValueError(f"{numeric} contains missing or non-finite values")

    metadata = {
        "source_format": source_format,
        "source_rows": int(len(source)),
        "detected_rows": int(len(detected)),
        "missed_rows": int(len(source) - len(detected)),
        "hit_fraction": float(len(detected) / len(source)),
        "hit_column_present": hit_column is not None,
        "hit_assumed_from_detector_export": hit_column is None,
        "particle_id_generated": particle_id_generated,
        "event_column_present": event_column is not None,
        "event_provenance": event_provenance,
        "pa_instance_column_present": "pa_instance" in normalized,
        "detector_z_column_present": "detector_z_mm" in normalized,
        "column_overrides": overrides,
        "source_columns": [str(column) for column in source.columns],
    }
    return detected.reset_index(drop=True), metadata


def load_contract(path: Path = DEFAULT_CONTRACT) -> tuple[dict[str, Any], AnalysisSettings]:
    with path.open("r", encoding="utf-8") as stream:
        contract = json.load(stream)
    kde = contract["kde"]
    settings = AnalysisSettings(
        grid_points=int(kde["grid_points"]),
        bandwidth_multiplier=float(kde["bandwidth_multiplier"]),
        mode_threshold_fraction=float(kde["significant_mode_threshold_fraction"]),
    )
    return contract, settings


def runtime_provenance(contract_path: Path) -> dict[str, Any]:
    return {
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "numpy_version": np.__version__,
        "scipy_version": scipy.__version__,
        "pandas_version": pd.__version__,
        "matplotlib_version": matplotlib.__version__,
        "analysis_contract": str(contract_path.resolve()),
        "analysis_contract_sha256": sha256_file(contract_path),
    }


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value)!r}")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(
            value,
            stream,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        )
        stream.write("\n")


def _plot_single(
    frame: pd.DataFrame,
    metrics: dict[str, Any],
    spectra: dict[str, np.ndarray],
    label: str,
    output: Path,
) -> None:
    figure, axes = plt.subplots(2, 2, figsize=(12.5, 8.0), constrained_layout=True)

    time_axis = axes[0, 0]
    time_axis.plot(
        spectra["time_grid_us"], spectra["time_density_normalized"], linewidth=1.8
    )
    time_axis.axhline(0.5, color="0.4", linestyle=":")
    time_axis.axvline(float(spectra["time_half_left_us"]), color="0.4", linestyle="--")
    time_axis.axvline(float(spectra["time_half_right_us"]), color="0.4", linestyle="--")
    time_axis.set(xlabel="TOF [us]", ylabel="Normalized intensity", title="Intensity-time spectrum")
    time_axis.grid(True, alpha=0.3)

    mass_axis = axes[0, 1]
    mass_axis.plot(
        spectra["mass_grid_Da"], spectra["mass_density_normalized"], linewidth=1.8
    )
    mass_axis.axhline(0.5, color="0.4", linestyle=":")
    mass_axis.axvline(float(spectra["mass_half_left_Da"]), color="0.4", linestyle="--")
    mass_axis.axvline(float(spectra["mass_half_right_Da"]), color="0.4", linestyle="--")
    mass_axis.set(
        xlabel="Apparent mass [Da]",
        ylabel="Normalized intensity",
        title=f"Direct FWHM={metrics['direct_fwhm_mass_Da']:.8g} Da; R={metrics['mass_resolution']:.1f}",
    )
    mass_axis.grid(True, alpha=0.3)

    qq_axis = axes[1, 0]
    standardized = np.sort(
        (spectra["tof_us"] - np.mean(spectra["tof_us"]))
        / np.std(spectra["tof_us"], ddof=1)
    )
    probabilities = (np.arange(1, standardized.size + 1) - 0.5) / standardized.size
    normal_quantiles = stats.norm.ppf(probabilities)
    qq_axis.scatter(normal_quantiles, standardized, s=8, alpha=0.5)
    limits = [min(normal_quantiles[0], standardized[0]), max(normal_quantiles[-1], standardized[-1])]
    qq_axis.plot(limits, limits, "k--", linewidth=1.0)
    qq_axis.set(
        xlabel="Normal quantile",
        ylabel="Observed standardized TOF",
        title=f"Q-Q: skew={metrics['tof_skewness']:.3f}, excess kurtosis={metrics['tof_excess_kurtosis']:.3f}",
    )
    qq_axis.grid(True, alpha=0.3)

    impact_axis = axes[1, 1]
    if {"detector_x_mm", "detector_y_mm"}.issubset(frame.columns):
        impact = impact_axis.hexbin(
            frame["detector_x_mm"],
            frame["detector_y_mm"],
            gridsize=45,
            mincnt=1,
            cmap="viridis",
        )
        figure.colorbar(impact, ax=impact_axis, label="Impacts per hexagon")
        impact_axis.set_aspect("equal", adjustable="box")
        impact_axis.set(
            xlabel="Detector local x [mm]",
            ylabel="Detector local y [mm]",
            title="Detector-plane impact density",
        )
        impact_axis.grid(True, alpha=0.2)
    else:
        impact_axis.axis("off")
        impact_axis.text(
            0.5,
            0.5,
            "Detector coordinates are not present\nin this source table.",
            ha="center",
            va="center",
        )

    figure.suptitle(
        f"{label}: N={metrics['particles']}, mean TOF={metrics['mean_tof_us']:.9f} us"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=200, facecolor="white")
    plt.close(figure)


SOURCE_COLUMNS = {
    "initial_x_mm",
    "initial_y_mm",
    "initial_z_mm",
    "initial_energy_eV",
}


def _plot_source_mapping(
    frame: pd.DataFrame,
    arrays: dict[str, np.ndarray],
    metrics: dict[str, Any],
    output: Path,
) -> None:
    figure, axis = plt.subplots(figsize=(10.5, 6.5), constrained_layout=True)
    points = axis.scatter(
        frame["initial_z_mm"],
        frame["tof_us"],
        c=frame["initial_energy_eV"],
        s=14,
        alpha=0.45,
        cmap="viridis",
    )
    axis.plot(
        arrays["z_plot_mm"],
        arrays["z_quadratic_fit_tof_us"],
        color="black",
        linewidth=2.0,
        label="z-only quadratic fit",
    )
    vertex = metrics["quadratic_vertex_z_mm"]
    if metrics["vertex_inside_source"] and vertex is not None:
        axis.axvline(vertex, color="red", linestyle="--", label="quadratic vertex")
    figure.colorbar(points, ax=axis, label="Initial energy [eV]")
    axis.set(
        xlabel="Initial z [mm]",
        ylabel="Detector TOF [us]",
        title=(
            "Initial-z to TOF mapping: "
            f"quadratic R²={metrics['z_only_quadratic_r_squared']:.4f}"
        ),
    )
    axis.grid(True, alpha=0.3)
    axis.legend()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=220, facecolor="white")
    plt.close(figure)


def _plot_source_mapping_comparison(
    left_frame: pd.DataFrame,
    right_frame: pd.DataFrame,
    source_frame: pd.DataFrame,
    left_arrays: dict[str, np.ndarray],
    right_arrays: dict[str, np.ndarray],
    left_metrics: dict[str, Any],
    right_metrics: dict[str, Any],
    left_label: str,
    right_label: str,
    output: Path,
) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(13.5, 5.8), constrained_layout=True)
    z = source_frame["initial_z_mm"].to_numpy()
    energy = source_frame["initial_energy_eV"].to_numpy()
    left_tof = left_frame["tof_us"].to_numpy()
    right_tof = right_frame["tof_us"].to_numpy()
    left_mean = float(np.mean(left_tof))
    right_mean = float(np.mean(right_tof))

    axes[0].scatter(
        z,
        1.0e3 * (left_tof - left_mean),
        c=energy,
        cmap="viridis",
        marker="o",
        s=22,
        alpha=0.45,
        label=f"{left_label} particles",
    )
    axes[0].scatter(
        z,
        1.0e3 * (right_tof - right_mean),
        c=energy,
        cmap="viridis",
        marker="x",
        s=24,
        alpha=0.55,
        label=f"{right_label} particles",
    )
    axes[0].plot(
        left_arrays["z_plot_mm"],
        1.0e3 * (left_arrays["z_quadratic_fit_tof_us"] - left_mean),
        linewidth=2.2,
        label=f"{left_label} quadratic fit",
    )
    axes[0].plot(
        right_arrays["z_plot_mm"],
        1.0e3 * (right_arrays["z_quadratic_fit_tof_us"] - right_mean),
        linewidth=2.2,
        label=f"{right_label} quadratic fit",
    )
    axes[0].set(
        xlabel="Initial z [mm]",
        ylabel="TOF - solver mean [ns]",
        title=(
            "Initial-z transfer mapping\n"
            f"vertices: {left_label}={left_metrics['quadratic_vertex_z_mm']:.4f} mm, "
            f"{right_label}={right_metrics['quadratic_vertex_z_mm']:.4f} mm"
        ),
    )
    axes[0].legend(fontsize=8)
    axes[0].grid(True, alpha=0.3)

    difference_ns = 1.0e3 * (right_tof - left_tof)
    fit_difference_ns = 1.0e3 * (
        right_arrays["z_quadratic_fit_tof_us"]
        - left_arrays["z_quadratic_fit_tof_us"]
    )
    points = axes[1].scatter(z, difference_ns, c=energy, cmap="viridis", s=24, alpha=0.65)
    axes[1].plot(
        left_arrays["z_plot_mm"],
        fit_difference_ns,
        color="black",
        linewidth=2.2,
        label=f"quadratic fit: {right_label} - {left_label}",
    )
    axes[1].axhline(float(np.mean(difference_ns)), color="red", linestyle="--", label="mean difference")
    axes[1].set(
        xlabel="Initial z [mm]",
        ylabel=f"{right_label} - {left_label} TOF [ns]",
        title="Paired solver TOF difference",
    )
    axes[1].legend(fontsize=8)
    axes[1].grid(True, alpha=0.3)
    figure.colorbar(points, ax=axes[1], label="Initial energy [eV]")
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=220, facecolor="white")
    plt.close(figure)


def audit_simion_recording(
    frame: pd.DataFrame,
    import_metadata: dict[str, Any],
    expected_particles: int,
    expected_pa_instance: int,
    expected_detector_z_mm: float,
    detector_radius_mm: float,
    program_state: str = "on",
    tolerance_mm: float = 1.0e-9,
) -> dict[str, Any]:
    """Strictly verify a GUI Data Recording export and its detector provenance."""

    if expected_particles <= 0 or detector_radius_mm <= 0 or tolerance_mm <= 0:
        raise ValueError("Recording expectations must be positive")
    identifiers = frame["particle_id"].to_numpy(dtype=np.int64)
    sequential = np.array_equal(
        np.sort(identifiers), np.arange(1, expected_particles + 1, dtype=np.int64)
    )
    has_detector_xy = {"detector_x_mm", "detector_y_mm"}.issubset(frame.columns)
    radius = (
        np.hypot(frame["detector_x_mm"], frame["detector_y_mm"])
        if has_detector_xy
        else np.asarray([], dtype=float)
    )
    has_z = "detector_z_mm" in frame
    z = frame["detector_z_mm"].to_numpy(dtype=float) if has_z else np.asarray([])
    has_instance = "pa_instance" in frame
    instances = (
        frame["pa_instance"].to_numpy(dtype=float)
        if has_instance
        else np.asarray([])
    )
    has_event = "event" in frame
    event_text = (
        frame["event"].astype(str).str.strip().str.lower()
        if has_event
        else pd.Series(dtype=str)
    )
    events_nonempty = bool(
        has_event and (~event_text.isin({"", "nan", "none", "null"})).all()
    )
    checks = {
        "program_was_enabled": program_state.strip().lower() == "on",
        "source_row_count_matches": import_metadata["source_rows"]
        == expected_particles,
        "detected_row_count_matches": len(frame) == expected_particles,
        "particle_ids_are_unique_sequential_1_to_n": sequential,
        "event_column_present_and_nonempty": events_nonempty,
        "pa_instance_column_present": has_instance,
        "all_pa_instances_match": bool(
            has_instance and np.all(instances == expected_pa_instance)
        ),
        "detector_z_column_present": has_z,
        "detector_plane_is_constant": bool(
            has_z and np.ptp(z) <= tolerance_mm
        ),
        "detector_plane_matches_expected": bool(
            has_z and np.all(np.abs(z - expected_detector_z_mm) <= tolerance_mm)
        ),
        "detector_xy_columns_present": has_detector_xy,
        "all_impacts_inside_detector_radius": bool(
            has_detector_xy and np.all(radius <= detector_radius_mm + tolerance_mm)
        ),
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "expected": {
            "particles": int(expected_particles),
            "pa_instance": int(expected_pa_instance),
            "detector_z_mm": float(expected_detector_z_mm),
            "detector_radius_mm": float(detector_radius_mm),
            "tolerance_mm": float(tolerance_mm),
        },
        "observed": {
            "operator_declared_program_state": program_state.strip().lower(),
            "source_rows": int(import_metadata["source_rows"]),
            "detected_rows": int(len(frame)),
            "particle_id_min": int(np.min(identifiers)),
            "particle_id_max": int(np.max(identifiers)),
            "detector_z_min_mm": float(np.min(z)) if has_z else None,
            "detector_z_max_mm": float(np.max(z)) if has_z else None,
            "maximum_impact_radius_mm": float(np.max(radius))
            if has_detector_xy
            else None,
            "events": sorted(event_text.unique().tolist())
            if has_event
            else [],
            "pa_instances": sorted(np.unique(instances).tolist())
            if has_instance
            else [],
        },
    }


def analyze_single(
    input_path: Path,
    output_dir: Path,
    nominal_mass_Da: float,
    label: str | None = None,
    detector_center_x_mm: float = DEFAULT_DETECTOR_CENTER_X_MM,
    detector_center_y_mm: float = DEFAULT_DETECTOR_CENTER_Y_MM,
    contract_path: Path = DEFAULT_CONTRACT,
    column_overrides: dict[str, str] | None = None,
    declared_event: str | None = None,
) -> dict[str, Any]:
    contract, settings = load_contract(contract_path)
    frame, import_metadata = read_particle_table(
        input_path,
        detector_center_x_mm,
        detector_center_y_mm,
        column_overrides=column_overrides,
        declared_event=declared_event,
    )
    metrics, spectra = compute_peak_metrics(
        frame["tof_us"].to_numpy(), nominal_mass_Da, settings
    )
    if {"detector_x_mm", "detector_y_mm"}.issubset(frame.columns):
        metrics["detector"] = compute_detector_metrics(
            frame["detector_x_mm"].to_numpy(), frame["detector_y_mm"].to_numpy()
        )
    source_arrays: dict[str, np.ndarray] | None = None
    if SOURCE_COLUMNS.issubset(frame.columns):
        source_metrics, source_arrays = compute_source_mapping_metrics(
            frame["tof_us"].to_numpy(),
            frame["initial_x_mm"].to_numpy(),
            frame["initial_y_mm"].to_numpy(),
            frame["initial_z_mm"].to_numpy(),
            frame["initial_energy_eV"].to_numpy(),
        )
        metrics["source_mapping"] = source_metrics

    output_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "schema_version": int(contract["schema_version"]),
        "status": "PASS",
        "label": label or input_path.stem,
        "input": {
            "path": str(input_path.resolve()),
            "bytes": input_path.stat().st_size,
            "sha256": sha256_file(input_path),
            **import_metadata,
        },
        "settings": settings.to_dict(),
        "runtime": runtime_provenance(contract_path),
        "metrics": metrics,
    }
    write_json(output_dir / "metrics.json", result)
    frame.to_csv(output_dir / "particles_normalized.csv", index=False)
    pd.DataFrame(
        {
            "tof_grid_us": spectra["time_grid_us"],
            "tof_density": spectra["time_density"],
            "tof_intensity_normalized": spectra["time_density_normalized"],
            "mass_grid_Da": spectra["mass_grid_Da"],
            "mass_density": spectra["mass_density"],
            "mass_intensity_normalized": spectra["mass_density_normalized"],
        }
    ).to_csv(output_dir / "spectra.csv", index=False)
    _plot_single(frame, metrics, spectra, result["label"], output_dir / "peak_overview.png")
    if source_arrays is not None:
        pd.DataFrame(
            {
                "initial_z_bin_center_mm": source_arrays["z_bin_center_mm"],
                "particle_count": source_arrays["z_bin_particle_count"],
                "mean_tof_us": source_arrays["z_bin_mean_tof_us"],
                "std_tof_ns": source_arrays["z_bin_std_tof_ns"],
            }
        ).to_csv(output_dir / "source_mapping_bins.csv", index=False)
        _plot_source_mapping(
            frame,
            source_arrays,
            metrics["source_mapping"],
            output_dir / "initial_z_tof_mapping.png",
        )
    return result


def analyze_simion_recording(
    input_path: Path,
    output_dir: Path,
    nominal_mass_Da: float,
    expected_particles: int,
    expected_pa_instance: int,
    expected_detector_z_mm: float,
    detector_radius_mm: float,
    detector_center_x_mm: float = DEFAULT_DETECTOR_CENTER_X_MM,
    detector_center_y_mm: float = DEFAULT_DETECTOR_CENTER_Y_MM,
    column_overrides: dict[str, str] | None = None,
    declared_event: str | None = None,
    program_state: str = "on",
) -> dict[str, Any]:
    result = analyze_single(
        input_path,
        output_dir,
        nominal_mass_Da,
        label="SIMION GUI Data Recording",
        detector_center_x_mm=detector_center_x_mm,
        detector_center_y_mm=detector_center_y_mm,
        column_overrides=column_overrides,
        declared_event=declared_event,
    )
    frame, import_metadata = read_particle_table(
        input_path,
        detector_center_x_mm,
        detector_center_y_mm,
        column_overrides=column_overrides,
        declared_event=declared_event,
    )
    audit = audit_simion_recording(
        frame,
        import_metadata,
        expected_particles,
        expected_pa_instance,
        expected_detector_z_mm,
        detector_radius_mm,
        program_state,
    )
    write_json(output_dir / "recording_audit.json", audit)
    result["recording_audit"] = audit
    result["status"] = audit["status"]
    write_json(output_dir / "metrics.json", result)
    return result


def _plot_comparison(
    left_metrics: dict[str, Any],
    left_spectra: dict[str, np.ndarray],
    right_metrics: dict[str, Any],
    right_spectra: dict[str, np.ndarray],
    comparison: dict[str, Any],
    comparison_spectra: dict[str, np.ndarray],
    left_label: str,
    right_label: str,
    output: Path,
) -> None:
    figure, axes = plt.subplots(2, 2, figsize=(12.5, 8.0), constrained_layout=True)
    axes[0, 0].plot(left_spectra["mass_grid_Da"], left_spectra["mass_density_normalized"], label=left_label)
    axes[0, 0].plot(right_spectra["mass_grid_Da"], right_spectra["mass_density_normalized"], label=right_label)
    axes[0, 0].set(xlabel="Apparent mass [Da]", ylabel="Normalized intensity", title="Absolute mass peaks")
    axes[0, 0].legend()

    grid = comparison_spectra["standardized_grid"]
    left_density = comparison_spectra["left_density_normalized"]
    right_density = comparison_spectra["right_density_normalized"]
    axes[0, 1].plot(grid, left_density, label=left_label)
    axes[0, 1].plot(grid, right_density, label=right_label)
    axes[0, 1].set(
        xlabel="(TOF-mean)/sample std",
        ylabel="Normalized intensity",
        title=f"Shape overlap={comparison['standardized_kde_overlap']:.3f}",
    )
    axes[0, 1].legend()

    axes[1, 0].plot(grid, left_density - right_density, color="black")
    axes[1, 0].axhline(0, color="0.4", linestyle="--")
    axes[1, 0].set(
        xlabel="(TOF-mean)/sample std",
        ylabel=f"{left_label} - {right_label}",
        title="Signed standardized-shape difference",
    )

    quantiles = np.linspace(0.01, 0.99, 99)
    left_quantiles = np.quantile(comparison_spectra["left_standardized_tof"], quantiles)
    right_quantiles = np.quantile(comparison_spectra["right_standardized_tof"], quantiles)
    axes[1, 1].scatter(right_quantiles, left_quantiles, s=12)
    axes[1, 1].plot([-3, 3], [-3, 3], "k--")
    axes[1, 1].set_aspect("equal", adjustable="box")
    paired_correlation = comparison["paired_standardized_tof_correlation"]
    relationship_text = (
        f"paired r={paired_correlation:.4f}"
        if paired_correlation is not None
        else "independent samples"
    )
    axes[1, 1].set(
        xlim=(-3, 3),
        ylim=(-3, 3),
        xlabel=f"{right_label} standardized TOF quantile",
        ylabel=f"{left_label} standardized TOF quantile",
        title=f"KS={comparison['standardized_ks_distance']:.3f}; {relationship_text}",
    )
    for axis in axes.flat:
        axis.grid(True, alpha=0.3)
    figure.suptitle(
        f"Peak comparison: R={left_metrics['mass_resolution']:.1f} vs {right_metrics['mass_resolution']:.1f}"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=200, facecolor="white")
    plt.close(figure)


def _plot_detector_comparison(
    left_frame: pd.DataFrame,
    right_frame: pd.DataFrame,
    left_metrics: dict[str, float],
    right_metrics: dict[str, float],
    left_label: str,
    right_label: str,
    paired: bool,
    output: Path,
) -> None:
    left_x = left_frame["detector_x_mm"].to_numpy(dtype=float)
    left_y = left_frame["detector_y_mm"].to_numpy(dtype=float)
    right_x = right_frame["detector_x_mm"].to_numpy(dtype=float)
    right_y = right_frame["detector_y_mm"].to_numpy(dtype=float)
    extent = 1.08 * max(
        1.0,
        float(np.max(np.abs(np.concatenate((left_x, left_y, right_x, right_y))))),
    )

    figure, axes = plt.subplots(1, 3, figsize=(15.5, 5.2), constrained_layout=True)
    datasets = (
        (axes[0], left_x, left_y, left_metrics, left_label, "tab:blue"),
        (axes[1], right_x, right_y, right_metrics, right_label, "tab:orange"),
    )
    for axis, x, y, metrics, label, color in datasets:
        axis.scatter(x, y, s=22, alpha=0.75, color=color, edgecolors="none")
        axis.scatter(
            metrics["impact_centroid_x_mm"],
            metrics["impact_centroid_y_mm"],
            marker="x",
            s=90,
            linewidths=2.0,
            color="black",
            label="centroid",
        )
        axis.set_title(
            f"{label}\nRMS radius={metrics['impact_rms_radius_mm']:.3f} mm"
        )
        axis.legend(loc="upper right")

    axes[2].scatter(
        left_x,
        left_y,
        s=26,
        alpha=0.65,
        color="tab:blue",
        label=left_label,
    )
    axes[2].scatter(
        right_x,
        right_y,
        s=24,
        alpha=0.65,
        facecolors="none",
        edgecolors="tab:orange",
        linewidths=1.0,
        label=right_label,
    )
    if paired:
        for left_x_value, left_y_value, right_x_value, right_y_value in zip(
            left_x, left_y, right_x, right_y, strict=True
        ):
            axes[2].plot(
                (left_x_value, right_x_value),
                (left_y_value, right_y_value),
                color="0.65",
                linewidth=0.35,
                alpha=0.55,
                zorder=0,
            )
        axes[2].set_title("Paired landing displacement")
    else:
        axes[2].set_title("Landing overlay")
    axes[2].legend(loc="upper right")

    for axis in axes:
        axis.axhline(0.0, color="0.75", linewidth=0.8)
        axis.axvline(0.0, color="0.75", linewidth=0.8)
        axis.set(
            xlim=(-extent, extent),
            ylim=(-extent, extent),
            xlabel="Detector local x [mm]",
            ylabel="Detector local y [mm]",
        )
        axis.set_aspect("equal", adjustable="box")
        axis.grid(True, alpha=0.25)
    figure.suptitle("Detector-plane landing comparison")
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=200, facecolor="white")
    plt.close(figure)


def analyze_comparison(
    left_path: Path,
    right_path: Path,
    output_dir: Path,
    nominal_mass_Da: float,
    left_label: str = "left",
    right_label: str = "right",
    paired_particle_ids_required: bool = False,
    bootstrap_resamples: int = 0,
    bootstrap_seed: int = 20260715,
    contract_path: Path = DEFAULT_CONTRACT,
) -> dict[str, Any]:
    contract, settings = load_contract(contract_path)
    left_frame, left_import = read_particle_table(left_path)
    right_frame, right_import = read_particle_table(right_path)
    if paired_particle_ids_required and not np.array_equal(
        left_frame["particle_id"].to_numpy(), right_frame["particle_id"].to_numpy()
    ):
        raise ValueError("Paired comparison requires identical ordered particle_id values")
    if paired_particle_ids_required and (
        left_import["particle_id_generated"] or right_import["particle_id_generated"]
    ):
        raise ValueError("Paired comparison forbids generated particle_id values")

    left_metrics, left_spectra = compute_peak_metrics(
        left_frame["tof_us"].to_numpy(), nominal_mass_Da, settings
    )
    right_metrics, right_spectra = compute_peak_metrics(
        right_frame["tof_us"].to_numpy(), nominal_mass_Da, settings
    )
    comparison, comparison_spectra = compare_peak_shapes(
        left_frame["tof_us"].to_numpy(), right_frame["tof_us"].to_numpy(), settings
    )
    paired_ids = np.array_equal(
        left_frame["particle_id"].to_numpy(), right_frame["particle_id"].to_numpy()
    )
    paired_landing = paired_particle_ids_required and paired_ids
    detector_columns = {"detector_x_mm", "detector_y_mm"}
    detector_comparison: dict[str, Any] | None = None
    if detector_columns.issubset(left_frame.columns) and detector_columns.issubset(
        right_frame.columns
    ):
        left_detector = compute_detector_metrics(
            left_frame["detector_x_mm"].to_numpy(),
            left_frame["detector_y_mm"].to_numpy(),
        )
        right_detector = compute_detector_metrics(
            right_frame["detector_x_mm"].to_numpy(),
            right_frame["detector_y_mm"].to_numpy(),
        )
        left_metrics["detector"] = left_detector
        right_metrics["detector"] = right_detector
        centroid_distance = float(
            np.hypot(
                right_detector["impact_centroid_x_mm"]
                - left_detector["impact_centroid_x_mm"],
                right_detector["impact_centroid_y_mm"]
                - left_detector["impact_centroid_y_mm"],
            )
        )
        detector_comparison = {
            "centroid_distance_mm": centroid_distance,
            "rms_radius_right_minus_left_mm": right_detector[
                "impact_rms_radius_mm"
            ]
            - left_detector["impact_rms_radius_mm"],
        }
        if paired_landing:
            paired_distance = np.hypot(
                right_frame["detector_x_mm"].to_numpy()
                - left_frame["detector_x_mm"].to_numpy(),
                right_frame["detector_y_mm"].to_numpy()
                - left_frame["detector_y_mm"].to_numpy(),
            )
            detector_comparison.update(
                {
                    "paired_mean_landing_distance_mm": float(
                        np.mean(paired_distance)
                    ),
                    "paired_rms_landing_distance_mm": float(
                        np.sqrt(np.mean(paired_distance**2))
                    ),
                    "paired_max_landing_distance_mm": float(
                        np.max(paired_distance)
                    ),
                }
            )
        comparison["detector_landing"] = detector_comparison
    comparison["sample_relationship"] = (
        "paired_fixed_particles" if paired_particle_ids_required else "independent_runs"
    )
    if paired_particle_ids_required:
        paired_tof_delta_ns = 1000.0 * (
            right_frame["tof_us"].to_numpy()
            - left_frame["tof_us"].to_numpy()
        )
        centered_delta_ns = paired_tof_delta_ns - np.mean(paired_tof_delta_ns)
        comparison["paired_tof_difference"] = {
            "mean_right_minus_left_ns": float(np.mean(paired_tof_delta_ns)),
            "rms_ns": float(np.sqrt(np.mean(paired_tof_delta_ns**2))),
            "mean_removed_rms_ns": float(
                np.sqrt(np.mean(centered_delta_ns**2))
            ),
            "max_abs_ns": float(np.max(np.abs(paired_tof_delta_ns))),
        }
    else:
        comparison["paired_standardized_tof_correlation"] = None
    source_frame: pd.DataFrame | None = None
    if paired_particle_ids_required and SOURCE_COLUMNS.issubset(right_frame.columns):
        source_frame = right_frame
    elif paired_particle_ids_required and SOURCE_COLUMNS.issubset(left_frame.columns):
        source_frame = left_frame
    left_source_arrays: dict[str, np.ndarray] | None = None
    right_source_arrays: dict[str, np.ndarray] | None = None
    if source_frame is not None:
        source_arguments = (
            source_frame["initial_x_mm"].to_numpy(),
            source_frame["initial_y_mm"].to_numpy(),
            source_frame["initial_z_mm"].to_numpy(),
            source_frame["initial_energy_eV"].to_numpy(),
        )
        left_source, left_source_arrays = compute_source_mapping_metrics(
            left_frame["tof_us"].to_numpy(), *source_arguments
        )
        right_source, right_source_arrays = compute_source_mapping_metrics(
            right_frame["tof_us"].to_numpy(), *source_arguments
        )
        comparison["source_mapping"] = {
            f"{left_label}_corr_tof_initial_z": left_source["corr_tof_initial_z"],
            f"{right_label}_corr_tof_initial_z": right_source["corr_tof_initial_z"],
            f"{left_label}_corr_tof_initial_energy": left_source[
                "corr_tof_initial_energy"
            ],
            f"{right_label}_corr_tof_initial_energy": right_source[
                "corr_tof_initial_energy"
            ],
            f"{left_label}_source_z2_energy_xy_fit_r_squared": left_source[
                "source_z2_energy_xy_fit_r_squared"
            ],
            f"{right_label}_source_z2_energy_xy_fit_r_squared": right_source[
                "source_z2_energy_xy_fit_r_squared"
            ],
            f"{left_label}_metrics": left_source,
            f"{right_label}_metrics": right_source,
        }
        comparison["paired_tof_difference"]["source_mapping"] = (
            compute_paired_tof_delta_source_metrics(
                paired_tof_delta_ns, *source_arguments
            )
        )
        comparison.update(
            {
                "left_corr_tof_initial_z": left_source["corr_tof_initial_z"],
                "right_corr_tof_initial_z": right_source["corr_tof_initial_z"],
                "left_corr_tof_initial_energy": left_source[
                    "corr_tof_initial_energy"
                ],
                "right_corr_tof_initial_energy": right_source[
                    "corr_tof_initial_energy"
                ],
                "left_source_z2_energy_xy_fit_r_squared": left_source[
                    "source_z2_energy_xy_fit_r_squared"
                ],
                "right_source_z2_energy_xy_fit_r_squared": right_source[
                    "source_z2_energy_xy_fit_r_squared"
                ],
            }
        )
    if bootstrap_resamples > 0:
        if not paired_ids:
            raise ValueError("Bootstrap comparison requires identical ordered particle_id values")
        bootstrap = bootstrap_resolution_difference(
            left_frame["tof_us"].to_numpy(),
            right_frame["tof_us"].to_numpy(),
            nominal_mass_Da,
            resamples=bootstrap_resamples,
            seed=bootstrap_seed,
            settings=settings,
        )
        comparison["paired_bootstrap"] = bootstrap
        comparison.update(
            {
                "bootstrap_absolute_resolution_difference_pct_p2p5": bootstrap[
                    "absolute_resolution_difference_pct_p2p5"
                ],
                "bootstrap_absolute_resolution_difference_pct_median": bootstrap[
                    "absolute_resolution_difference_pct_median"
                ],
                "bootstrap_absolute_resolution_difference_pct_p97p5": bootstrap[
                    "absolute_resolution_difference_pct_p97p5"
                ],
            }
        )
    result = {
        "schema_version": int(contract["schema_version"]),
        "status": "PASS",
        "nominal_mass_Da": nominal_mass_Da,
        "left": {
            "label": left_label,
            "path": str(left_path.resolve()),
            "sha256": sha256_file(left_path),
            "import": left_import,
            "metrics": left_metrics,
        },
        "right": {
            "label": right_label,
            "path": str(right_path.resolve()),
            "sha256": sha256_file(right_path),
            "import": right_import,
            "metrics": right_metrics,
        },
        "comparison": comparison,
        "settings": settings.to_dict(),
        "runtime": runtime_provenance(contract_path),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "comparison_metrics.json", result)
    pd.DataFrame(
        {
            "standardized_grid": comparison_spectra["standardized_grid"],
            f"{left_label}_density": comparison_spectra["left_density"],
            f"{right_label}_density": comparison_spectra["right_density"],
            f"{left_label}_intensity_normalized": comparison_spectra["left_density_normalized"],
            f"{right_label}_intensity_normalized": comparison_spectra["right_density_normalized"],
        }
    ).to_csv(output_dir / "comparison_spectra.csv", index=False)
    _plot_comparison(
        left_metrics,
        left_spectra,
        right_metrics,
        right_spectra,
        comparison,
        comparison_spectra,
        left_label,
        right_label,
        output_dir / "peak_shape_comparison.png",
    )
    if detector_comparison is not None:
        if paired_landing:
            detector_particles = pd.DataFrame(
                {
                    "particle_id": left_frame["particle_id"].to_numpy(),
                    f"{left_label}_detector_x_mm": left_frame[
                        "detector_x_mm"
                    ].to_numpy(),
                    f"{left_label}_detector_y_mm": left_frame[
                        "detector_y_mm"
                    ].to_numpy(),
                    f"{right_label}_detector_x_mm": right_frame[
                        "detector_x_mm"
                    ].to_numpy(),
                    f"{right_label}_detector_y_mm": right_frame[
                        "detector_y_mm"
                    ].to_numpy(),
                }
            )
            detector_particles["paired_landing_distance_mm"] = np.hypot(
                right_frame["detector_x_mm"].to_numpy()
                - left_frame["detector_x_mm"].to_numpy(),
                right_frame["detector_y_mm"].to_numpy()
                - left_frame["detector_y_mm"].to_numpy(),
            )
        else:
            detector_particles = pd.concat(
                (
                    left_frame[["particle_id", "detector_x_mm", "detector_y_mm"]]
                    .assign(solver=left_label),
                    right_frame[["particle_id", "detector_x_mm", "detector_y_mm"]]
                    .assign(solver=right_label),
                ),
                ignore_index=True,
            )
        detector_particles.to_csv(
            output_dir / "detector_landing_particles.csv", index=False
        )
        _plot_detector_comparison(
            left_frame,
            right_frame,
            left_metrics["detector"],
            right_metrics["detector"],
            left_label,
            right_label,
            paired_landing,
            output_dir / "detector_landing_comparison.png",
        )
    if (
        source_frame is not None
        and left_source_arrays is not None
        and right_source_arrays is not None
    ):
        pd.DataFrame(
            {
                "particle_id": left_frame["particle_id"].to_numpy(),
                "initial_x_mm": source_frame["initial_x_mm"].to_numpy(),
                "initial_y_mm": source_frame["initial_y_mm"].to_numpy(),
                "initial_z_mm": source_frame["initial_z_mm"].to_numpy(),
                "initial_energy_eV": source_frame["initial_energy_eV"].to_numpy(),
                f"{left_label}_tof_us": left_frame["tof_us"].to_numpy(),
                f"{right_label}_tof_us": right_frame["tof_us"].to_numpy(),
                f"{right_label}_minus_{left_label}_tof_ns": 1.0e3
                * (
                    right_frame["tof_us"].to_numpy()
                    - left_frame["tof_us"].to_numpy()
                ),
            }
        ).to_csv(output_dir / "source_mapping_particles.csv", index=False)
        pd.DataFrame(
            {
                "initial_z_mm": left_source_arrays["z_plot_mm"],
                f"{left_label}_quadratic_fit_tof_us": left_source_arrays[
                    "z_quadratic_fit_tof_us"
                ],
                f"{right_label}_quadratic_fit_tof_us": right_source_arrays[
                    "z_quadratic_fit_tof_us"
                ],
                f"{right_label}_minus_{left_label}_fit_tof_ns": 1.0e3
                * (
                    right_source_arrays["z_quadratic_fit_tof_us"]
                    - left_source_arrays["z_quadratic_fit_tof_us"]
                ),
            }
        ).to_csv(output_dir / "source_mapping_fits.csv", index=False)
        _plot_source_mapping_comparison(
            left_frame,
            right_frame,
            source_frame,
            left_source_arrays,
            right_source_arrays,
            left_source,
            right_source,
            left_label,
            right_label,
            output_dir / "source_mapping_comparison.png",
        )
    return result


def _relative_difference_pct(value: float, reference: float) -> float:
    return 100.0 * (value - reference) / reference


def _check_reference_values(
    actual: dict[str, Any],
    expected: dict[str, Any],
    relative_tolerance: float,
    absolute_tolerance: float,
) -> dict[str, dict[str, Any]]:
    checks: dict[str, dict[str, Any]] = {}
    for key, expected_value in expected.items():
        actual_value = actual[key]
        if isinstance(expected_value, int) and not isinstance(expected_value, bool):
            passed = int(actual_value) == expected_value
        else:
            passed = bool(
                np.isclose(
                    float(actual_value),
                    float(expected_value),
                    rtol=relative_tolerance,
                    atol=absolute_tolerance,
                )
            )
        checks[key] = {
            "actual": actual_value,
            "expected": expected_value,
            "pass": passed,
        }
    return checks


def verify_baselines(
    manifest_path: Path = DEFAULT_BASELINES,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    with manifest_path.open("r", encoding="utf-8") as stream:
        manifest = json.load(stream)
    contract_path = manifest_path.parent / manifest["analysis_contract"]
    artifact_project = (
        REPO_ROOT.parent / "artifacts" / manifest["artifact_project_relative"]
    )
    if output_dir is None:
        output_dir = artifact_project / "results" / "reference_analysis" / "baseline"
    output_dir.mkdir(parents=True, exist_ok=True)

    tolerance = manifest["canonical_tolerance"]
    relative_tolerance = float(tolerance["relative"])
    absolute_tolerance = float(tolerance["absolute"])

    results_by_id: dict[str, dict[str, Any]] = {}
    entry_reports: list[dict[str, Any]] = []
    overall_pass = True
    for entry in manifest["entries"]:
        input_path = artifact_project / entry["relative_path"]
        identity = {
            "exists": input_path.is_file(),
            "bytes_match": False,
            "sha256_match": False,
            "rows_match": False,
        }
        report: dict[str, Any] = {"id": entry["id"], "path": str(input_path), "identity": identity}
        if input_path.is_file():
            identity["bytes_match"] = input_path.stat().st_size == int(entry["bytes"])
            identity["sha256_match"] = sha256_file(input_path) == entry["sha256"]
            frame, _ = read_particle_table(input_path)
            identity["rows_match"] = len(frame) == int(entry["rows"])
            result = analyze_single(
                input_path,
                output_dir / entry["id"],
                float(entry["nominal_mass_Da"]),
                label=entry["id"],
                contract_path=contract_path,
            )
            results_by_id[entry["id"]] = result
            legacy = entry.get("legacy_matlab_reference", {})
            metrics = result["metrics"]
            report["canonical_metrics"] = metrics
            report["canonical_reference_checks"] = _check_reference_values(
                metrics,
                entry["canonical_reference"],
                relative_tolerance,
                absolute_tolerance,
            )
            report["legacy_matlab_reference"] = legacy
            report["canonical_vs_legacy_difference_pct"] = {
                "mean_tof_us": _relative_difference_pct(metrics["mean_tof_us"], legacy["mean_tof_us"]),
                "std_tof_ns": _relative_difference_pct(metrics["std_tof_ns"], legacy["std_tof_ns"]),
                "fwhm_mass_Da": _relative_difference_pct(metrics["direct_fwhm_mass_Da"], legacy["fwhm_mass_Da"]),
                "mass_resolution": _relative_difference_pct(metrics["mass_resolution"], legacy["mass_resolution"]),
            }
        canonical_checks = report.get("canonical_reference_checks", {})
        entry_pass = all(identity.values()) and all(
            check["pass"] for check in canonical_checks.values()
        )
        report["status"] = "PASS" if entry_pass else "FAIL"
        overall_pass = overall_pass and entry_pass
        entry_reports.append(report)

    comparison_reports: list[dict[str, Any]] = []
    entries = {entry["id"]: entry for entry in manifest["entries"]}
    for comparison in manifest.get("comparisons", []):
        left_entry = entries[comparison["left"]]
        right_entry = entries[comparison["right"]]
        result = analyze_comparison(
            artifact_project / left_entry["relative_path"],
            artifact_project / right_entry["relative_path"],
            output_dir / comparison["id"],
            float(left_entry["nominal_mass_Da"]),
            left_label=left_entry["solver"],
            right_label=right_entry["solver"],
            paired_particle_ids_required=bool(comparison["paired_particle_ids_required"]),
            bootstrap_resamples=int(
                comparison.get("bootstrap", {}).get("resamples", 0)
            ),
            bootstrap_seed=int(
                comparison.get("bootstrap", {}).get("seed", 20260715)
            ),
            contract_path=contract_path,
        )
        legacy = comparison.get("legacy_matlab_reference", {})
        canonical = result["comparison"]
        canonical_checks = _check_reference_values(
            canonical,
            comparison["canonical_reference"],
            relative_tolerance,
            absolute_tolerance,
        )
        comparison_pass = all(check["pass"] for check in canonical_checks.values())
        overall_pass = overall_pass and comparison_pass
        comparison_reports.append(
            {
                "id": comparison["id"],
                "status": "PASS" if comparison_pass else "FAIL",
                "canonical": canonical,
                "canonical_reference_checks": canonical_checks,
                "legacy_matlab_reference": legacy,
                "canonical_minus_legacy": {
                    key: canonical[key] - legacy[key] for key in legacy
                },
            }
        )

    verification = {
        "schema_version": int(manifest["schema_version"]),
        "status": "PASS" if overall_pass else "FAIL",
        "manifest": str(manifest_path.resolve()),
        "manifest_sha256": sha256_file(manifest_path),
        "artifact_project": str(artifact_project),
        "entries": entry_reports,
        "comparisons": comparison_reports,
        "runtime": runtime_provenance(contract_path),
    }
    write_json(output_dir / "baseline_verification.json", verification)
    return verification


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_column_mapping_arguments(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--particle-id-column")
        command_parser.add_argument("--tof-column")
        command_parser.add_argument("--event-column")
        command_parser.add_argument("--pa-instance-column")
        command_parser.add_argument("--x-column")
        command_parser.add_argument("--y-column")
        command_parser.add_argument("--z-column")
        command_parser.add_argument("--declared-event")

    single = subparsers.add_parser("single", help="Analyze one CSV or XLSX particle table")
    single.add_argument("input", type=Path)
    single.add_argument("--mass", type=float, required=True, dest="nominal_mass_Da")
    single.add_argument("--output", type=Path, required=True)
    single.add_argument("--label")
    single.add_argument("--detector-center-x-mm", type=float, default=DEFAULT_DETECTOR_CENTER_X_MM)
    single.add_argument("--detector-center-y-mm", type=float, default=DEFAULT_DETECTOR_CENTER_Y_MM)
    add_column_mapping_arguments(single)

    recording = subparsers.add_parser(
        "simion-recording", help="Analyze and strictly audit a SIMION GUI export"
    )
    recording.add_argument("input", type=Path)
    recording.add_argument("--mass", type=float, required=True, dest="nominal_mass_Da")
    recording.add_argument("--output", type=Path, required=True)
    recording.add_argument("--expected-particles", type=int, required=True)
    recording.add_argument("--expected-pa-instance", type=int, required=True)
    recording.add_argument("--expected-detector-z-mm", type=float, required=True)
    recording.add_argument("--detector-radius-mm", type=float, required=True)
    recording.add_argument("--detector-center-x-mm", type=float, default=DEFAULT_DETECTOR_CENTER_X_MM)
    recording.add_argument("--detector-center-y-mm", type=float, default=DEFAULT_DETECTOR_CENTER_Y_MM)
    recording.add_argument("--program-state", choices=("on", "off"), default="on")
    add_column_mapping_arguments(recording)

    compare = subparsers.add_parser("compare", help="Compare two solver particle tables")
    compare.add_argument("left", type=Path)
    compare.add_argument("right", type=Path)
    compare.add_argument("--mass", type=float, required=True, dest="nominal_mass_Da")
    compare.add_argument("--output", type=Path, required=True)
    compare.add_argument("--left-label", default="left")
    compare.add_argument("--right-label", default="right")
    compare.add_argument("--require-paired-particle-ids", action="store_true")
    compare.add_argument("--bootstrap-resamples", type=int, default=0)
    compare.add_argument("--bootstrap-seed", type=int, default=20260715)

    baselines = subparsers.add_parser("verify-baselines", help="Verify frozen migration baselines")
    baselines.add_argument("--manifest", type=Path, default=DEFAULT_BASELINES)
    baselines.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    column_overrides = {
        canonical: value
        for canonical, value in {
            "particle_id": getattr(arguments, "particle_id_column", None),
            "tof_us": getattr(arguments, "tof_column", None),
            "event": getattr(arguments, "event_column", None),
            "pa_instance": getattr(arguments, "pa_instance_column", None),
            "detector_x_mm": getattr(arguments, "x_column", None),
            "detector_y_mm": getattr(arguments, "y_column", None),
            "detector_z_mm": getattr(arguments, "z_column", None),
        }.items()
        if value is not None
    }
    try:
        if arguments.command == "single":
            result = analyze_single(
                arguments.input,
                arguments.output,
                arguments.nominal_mass_Da,
                arguments.label,
                arguments.detector_center_x_mm,
                arguments.detector_center_y_mm,
                column_overrides=column_overrides,
                declared_event=arguments.declared_event,
            )
        elif arguments.command == "simion-recording":
            result = analyze_simion_recording(
                arguments.input,
                arguments.output,
                arguments.nominal_mass_Da,
                arguments.expected_particles,
                arguments.expected_pa_instance,
                arguments.expected_detector_z_mm,
                arguments.detector_radius_mm,
                arguments.detector_center_x_mm,
                arguments.detector_center_y_mm,
                column_overrides=column_overrides,
                declared_event=arguments.declared_event,
                program_state=arguments.program_state,
            )
        elif arguments.command == "compare":
            result = analyze_comparison(
                arguments.left,
                arguments.right,
                arguments.output,
                arguments.nominal_mass_Da,
                arguments.left_label,
                arguments.right_label,
                arguments.require_paired_particle_ids,
                arguments.bootstrap_resamples,
                arguments.bootstrap_seed,
            )
        else:
            result = verify_baselines(arguments.manifest, arguments.output)
    except Exception as error:  # CLI gate must return a nonzero status with a concise cause.
        print(f"STATUS=FAIL\nERROR={type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(f"STATUS={result['status']}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
