"""Solver-neutral oa-TOF diagnostics invoked by orchestration scripts."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DETECTOR_PATTERN = re.compile(
    r"TRACE: detector_crossing ion=(\d+) "
    r"t=([-+0-9.eE]+) x=([-+0-9.eE]+) y=([-+0-9.eE]+) "
    r"z=([-+0-9.eE]+) r=([-+0-9.eE]+) zmax=([-+0-9.eE]+)"
)
FIELD_PATTERN = re.compile(
    r"^FIELD_(.+)_PA_LOCAL_E_V_PER_MM="
    r"([-+0-9.eE]+),([-+0-9.eE]+),([-+0-9.eE]+)$"
)


def _finite_or_none(value: float) -> float | None:
    return float(value) if math.isfinite(value) else None


def _mean(values: np.ndarray) -> float:
    return float(np.mean(values)) if values.size else math.nan


def _sample_std(values: np.ndarray) -> float:
    return float(np.std(values, ddof=1)) if values.size >= 2 else math.nan


def _correlation(left: np.ndarray, right: np.ndarray) -> float:
    if left.size != right.size or left.size < 2:
        return math.nan
    if np.ptp(left) == 0 or np.ptp(right) == 0:
        return math.nan
    return float(np.corrcoef(left, right)[0, 1])


def read_ion_table(path: Path) -> pd.DataFrame:
    rows: list[dict[str, float | int]] = []
    for ion, line in enumerate(path.read_text(encoding="ascii").splitlines(), start=1):
        if not line.strip():
            continue
        columns = line.split(",")
        if len(columns) < 9:
            raise ValueError(f"Malformed ION line {ion} in {path}")
        rows.append(
            {
                "Ion": ion,
                "TobUs": float(columns[0]),
                "MassAmu": float(columns[1]),
                "ChargeState": int(float(columns[2])),
                "X0Mm": float(columns[3]),
                "Y0Mm": float(columns[4]),
                "Z0Mm": float(columns[5]),
                "EnergyEv": float(columns[8]),
            }
        )
    if not rows:
        raise ValueError(f"ION file is empty: {path}")
    return pd.DataFrame(rows)


def analyze_simion_log(
    log_path: Path,
    ion_path: Path,
    *,
    mode: str,
    distribution: str,
    detector_radius_mm: float,
    allow_incomplete_census: bool,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    initial = read_ion_table(ion_path).set_index("Ion", drop=False)
    rows: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = DETECTOR_PATTERN.search(line)
        if not match:
            continue
        ion = int(match.group(1))
        if ion not in initial.index:
            raise ValueError(f"Detector crossing references absent ion {ion}")
        source = initial.loc[ion]
        radius = float(match.group(6))
        rows.append(
            {
                "Mode": mode,
                "Distribution": distribution,
                "Ion": ion,
                "MassAmu": float(source["MassAmu"]),
                "ChargeState": int(source["ChargeState"]),
                "X0Mm": float(source["X0Mm"]),
                "Y0Mm": float(source["Y0Mm"]),
                "Z0Mm": float(source["Z0Mm"]),
                "EnergyEv": float(source["EnergyEv"]),
                "TofUs": float(match.group(2)) - float(source["TobUs"]),
                "InstrumentTimeUs": float(match.group(2)),
                "XMm": float(match.group(3)),
                "YMm": float(match.group(4)),
                "RadiusMm": radius,
                "ZmaxMm": float(match.group(7)),
                "Hit": radius <= detector_radius_mm,
            }
        )
    crossings = pd.DataFrame(rows)
    if crossings.empty and not allow_incomplete_census:
        raise ValueError(f"No detector_crossing records found in {log_path}")
    if (
        len(crossings) != len(initial)
        or (not crossings.empty and crossings["Ion"].nunique() != len(initial))
    ) and not allow_incomplete_census:
        raise ValueError(
            "Incomplete detector-plane census: "
            f"emitted={len(initial)}, crossings={len(crossings)}, "
            f"unique_ions={crossings['Ion'].nunique() if not crossings.empty else 0}"
        )

    full = crossings.copy()
    missing = initial.index.difference(crossings["Ion"] if not crossings.empty else [])
    if len(missing):
        missing_rows = initial.loc[missing].reset_index(drop=True)
        missing_rows = missing_rows.assign(
            Mode=mode,
            Distribution=distribution,
            TofUs=np.nan,
            InstrumentTimeUs=np.nan,
            XMm=np.nan,
            YMm=np.nan,
            RadiusMm=np.nan,
            ZmaxMm=np.nan,
            Hit=False,
        )
        full = pd.concat([full, missing_rows[full.columns]], ignore_index=True)
    full = full.sort_values("Ion").reset_index(drop=True)

    hits = full[full["Hit"]]
    misses = full[~full["Hit"]]
    hit_tof = hits["TofUs"].to_numpy(dtype=float)
    std_tof_us = _sample_std(hit_tof)
    fwhm_tof_us = 2.0 * math.sqrt(2.0 * math.log(2.0)) * std_tof_us

    def values(frame: pd.DataFrame, column: str) -> np.ndarray:
        return frame[column].to_numpy(dtype=float)

    summary = {
        "Mode": mode,
        "Distribution": distribution,
        "Emitted": int(len(initial)),
        "Crossed": int(len(crossings)),
        "Hit": int(len(hits)),
        "EfficiencyPct": 100.0 * len(hits) / len(initial),
        "MeanTofUs": _finite_or_none(_mean(hit_tof)),
        "StdTofNs": _finite_or_none(1000.0 * std_tof_us),
        "FwhmTofNs": _finite_or_none(1000.0 * fwhm_tof_us),
        "ResolutionFwhm": _finite_or_none(_mean(hit_tof) / (2.0 * fwhm_tof_us)),
        "AllCrossingStdTofNs": _finite_or_none(
            1000.0 * _sample_std(values(crossings, "TofUs"))
        ),
        "MaxHitRadiusMm": _finite_or_none(
            float(hits["RadiusMm"].max()) if len(hits) else math.nan
        ),
        "MaxCrossingRadiusMm": _finite_or_none(
            float(crossings["RadiusMm"].max()) if len(crossings) else math.nan
        ),
        "MeanZmaxMm": _finite_or_none(_mean(values(crossings, "ZmaxMm"))),
        "CorrTofX0": _finite_or_none(
            _correlation(values(hits, "X0Mm"), hit_tof)
        ),
        "CorrTofY0": _finite_or_none(
            _correlation(values(hits, "Y0Mm"), hit_tof)
        ),
        "CorrTofZ0": _finite_or_none(
            _correlation(values(hits, "Z0Mm"), hit_tof)
        ),
        "CorrTofEnergy": _finite_or_none(
            _correlation(values(hits, "EnergyEv"), hit_tof)
        ),
        "CorrRadiusX0": _finite_or_none(
            _correlation(values(crossings, "X0Mm"), values(crossings, "RadiusMm"))
        ),
        "CorrRadiusY0": _finite_or_none(
            _correlation(values(crossings, "Y0Mm"), values(crossings, "RadiusMm"))
        ),
        "CorrRadiusZ0": _finite_or_none(
            _correlation(values(crossings, "Z0Mm"), values(crossings, "RadiusMm"))
        ),
        "CorrRadiusEnergy": _finite_or_none(
            _correlation(
                values(crossings, "EnergyEv"), values(crossings, "RadiusMm")
            )
        ),
        "HitMeanZ0Mm": _finite_or_none(_mean(values(hits, "Z0Mm"))),
        "MissMeanZ0Mm": _finite_or_none(_mean(values(misses, "Z0Mm"))),
        "HitMeanEnergyEv": _finite_or_none(_mean(values(hits, "EnergyEv"))),
        "MissMeanEnergyEv": _finite_or_none(_mean(values(misses, "EnergyEv"))),
        "Log": str(log_path.resolve()),
    }
    return full, summary


def compare_particle_exports(
    reference_path: Path,
    candidate_path: Path,
    *,
    max_tof_difference_us: float,
    max_landing_difference_mm: float,
) -> dict[str, Any]:
    reference = pd.read_csv(reference_path)
    candidate = pd.read_csv(candidate_path)
    required = {"Ion", "TofUs", "XMm", "YMm"}
    for label, frame in (("reference", reference), ("candidate", candidate)):
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"{label} CSV misses columns: {sorted(missing)}")
        if frame["Ion"].duplicated().any():
            raise ValueError(f"{label} CSV contains duplicate Ion values")
    if set(reference["Ion"]) != set(candidate["Ion"]):
        raise ValueError("Particle ID coverage differs between exports")
    merged = reference.merge(
        candidate,
        on="Ion",
        suffixes=("_reference", "_candidate"),
        validate="one_to_one",
    )
    delta_tof = (
        merged["TofUs_candidate"].to_numpy()
        - merged["TofUs_reference"].to_numpy()
    )
    landing = np.hypot(
        merged["XMm_candidate"] - merged["XMm_reference"],
        merged["YMm_candidate"] - merged["YMm_reference"],
    ).to_numpy()
    max_tof = float(np.max(np.abs(delta_tof)))
    max_landing = float(np.max(landing))
    passed = (
        max_tof <= max_tof_difference_us
        and max_landing <= max_landing_difference_mm
    )
    return {
        "reference_csv": str(reference_path.resolve()),
        "candidate_csv": str(candidate_path.resolve()),
        "particles": int(len(merged)),
        "mean_delta_tof_us": float(np.mean(delta_tof)),
        "rms_delta_tof_us": float(np.sqrt(np.mean(delta_tof**2))),
        "max_abs_delta_tof_us": max_tof,
        "rms_landing_delta_mm": float(np.sqrt(np.mean(landing**2))),
        "max_landing_delta_mm": max_landing,
        "max_allowed_tof_difference_us": max_tof_difference_us,
        "max_allowed_landing_difference_mm": max_landing_difference_mm,
        "status": "PASS" if passed else "FAIL",
    }


def calculate_pulse_timing(
    canonical_path: Path,
    *,
    source_center_x_mm: float,
    target_origin_x_mm: float,
) -> dict[str, float]:
    frame = pd.read_csv(canonical_path)
    required = {"instrument_time_us", "velocity_x_m_s"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Canonical handoff CSV misses columns: {sorted(missing)}")
    if frame.empty or not np.isfinite(frame[list(required)].to_numpy()).all():
        raise ValueError("Canonical handoff timing inputs must be finite and nonempty")
    entry_to_center_mm = source_center_x_mm - target_origin_x_mm
    mean_velocity_mm_us = float(frame["velocity_x_m_s"].mean() / 1000.0)
    if entry_to_center_mm <= 0 or mean_velocity_mm_us <= 0:
        raise ValueError("Effective entry-plane timing inputs are invalid")
    mean_handoff_us = float(frame["instrument_time_us"].mean())
    return {
        "mean_handoff_time_us": mean_handoff_us,
        "mean_injection_velocity_mm_per_us": mean_velocity_mm_us,
        "entry_to_source_center_mm": entry_to_center_mm,
        "pulse_time_us": mean_handoff_us + entry_to_center_mm / mean_velocity_mm_us,
    }


def line_fit(frame: pd.DataFrame, value_column: str) -> dict[str, float]:
    x = frame["particle_count"].to_numpy(dtype=float)
    y = frame[value_column].to_numpy(dtype=float)
    if x.size < 2 or np.ptp(x) == 0:
        raise ValueError("Linear fit needs at least two distinct particle counts")
    slope, intercept = np.polyfit(x, y, 1)
    residual = y - (intercept + slope * x)
    total = y - np.mean(y)
    denominator = float(np.sum(total**2))
    r_squared = (
        1.0 - float(np.sum(residual**2)) / denominator
        if denominator > 0
        else 1.0
    )
    return {
        "intercept_seconds": float(intercept),
        "slope_seconds_per_particle": float(slope),
        "r_squared": r_squared,
    }


def build_benchmark_metrics(
    samples_path: Path,
    *,
    run_id: str,
    mass_amu: float,
    charge_state: int,
    simion_repeats: int,
) -> dict[str, Any]:
    samples = pd.read_csv(samples_path)
    required = {"solver", "particle_count", "wall_seconds"}
    missing = required - set(samples.columns)
    if missing:
        raise ValueError(f"Timing samples miss columns: {sorted(missing)}")
    comsol = samples[samples["solver"] == "COMSOL"]
    simion = samples[samples["solver"] == "SIMION"]
    if "particle_seconds" not in comsol:
        raise ValueError("Timing samples miss COMSOL particle_seconds")
    return {
        "schema_version": 1,
        "role": "oa_tof_single_mass_scaling_benchmark",
        "run_id": run_id,
        "mass_amu": mass_amu,
        "charge_state": charge_state,
        "particle_counts": sorted(
            int(value) for value in samples["particle_count"].unique()
        ),
        "simion_repeats": simion_repeats,
        "comsol_wall_fit": line_fit(comsol, "wall_seconds"),
        "comsol_particle_fit": line_fit(comsol, "particle_seconds"),
        "simion_wall_fit": line_fit(simion, "wall_seconds"),
    }


def mass_spectrum_max_tof_us(mode_path: Path, reference_mass_amu: float) -> float:
    mode = json.loads(mode_path.read_text(encoding="utf-8"))
    masses = [float(species["mass_amu"]) for species in mode["species"]]
    if not masses or min(masses) <= 0 or reference_mass_amu <= 0:
        raise ValueError("Masses used for TOF scaling must be positive")
    return float(math.ceil(90.0 * math.sqrt(max(masses) / reference_mass_amu)))


def compare_field_reports(left_path: Path, right_path: Path) -> dict[str, float | int]:
    def read(path: Path) -> dict[str, np.ndarray]:
        values: dict[str, np.ndarray] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            match = FIELD_PATTERN.match(line)
            if match:
                values[match.group(1)] = np.asarray(match.groups()[1:], dtype=float)
        if not values:
            raise ValueError(f"Field report contains no samples: {path}")
        return values

    left = read(left_path)
    right = read(right_path)
    if set(left) != set(right):
        raise ValueError("Field report sample coverage differs")
    relative: list[float] = []
    maximum_absolute = 0.0
    for key in sorted(left):
        difference = float(np.linalg.norm(right[key] - left[key]))
        scale = max(float(np.linalg.norm(left[key])), float(np.linalg.norm(right[key])))
        maximum_absolute = max(maximum_absolute, difference)
        relative.append(difference / scale if scale > np.finfo(float).eps else 0.0)
    return {
        "sample_points": len(left),
        "max_symmetric_relative_difference": max(relative),
        "max_absolute_difference_V_per_mm": maximum_absolute,
    }


def _write_key_value_report(report: dict[str, Any], path: Path) -> None:
    lines = [f"{key.upper()}={value}" for key, value in report.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    log_parser = subparsers.add_parser("analyze-simion-log")
    log_parser.add_argument("--log", type=Path, required=True)
    log_parser.add_argument("--ion-file", type=Path, required=True)
    log_parser.add_argument("--mode", required=True)
    log_parser.add_argument("--distribution", required=True)
    log_parser.add_argument("--detector-radius-mm", type=float, default=40.0)
    log_parser.add_argument("--particle-csv", type=Path)
    log_parser.add_argument("--allow-incomplete-census", action="store_true")
    compare_parser = subparsers.add_parser("compare-particle-exports")
    compare_parser.add_argument("--reference", type=Path, required=True)
    compare_parser.add_argument("--candidate", type=Path, required=True)
    compare_parser.add_argument("--report", type=Path, required=True)
    compare_parser.add_argument("--max-tof-difference-us", type=float, default=0.001)
    compare_parser.add_argument(
        "--max-landing-difference-mm", type=float, default=0.05
    )
    timing_parser = subparsers.add_parser("pulse-timing")
    timing_parser.add_argument("--canonical", type=Path, required=True)
    timing_parser.add_argument("--source-center-x-mm", type=float, required=True)
    timing_parser.add_argument("--target-origin-x-mm", type=float, required=True)
    benchmark_parser = subparsers.add_parser("benchmark-metrics")
    benchmark_parser.add_argument("--samples", type=Path, required=True)
    benchmark_parser.add_argument("--output", type=Path, required=True)
    benchmark_parser.add_argument("--run-id", required=True)
    benchmark_parser.add_argument("--mass-amu", type=float, required=True)
    benchmark_parser.add_argument("--charge-state", type=int, required=True)
    benchmark_parser.add_argument("--simion-repeats", type=int, required=True)
    max_tof_parser = subparsers.add_parser("mass-spectrum-max-tof")
    max_tof_parser.add_argument("--mode", type=Path, required=True)
    max_tof_parser.add_argument("--reference-mass-amu", type=float, required=True)
    field_parser = subparsers.add_parser("compare-field-reports")
    field_parser.add_argument("--left", type=Path, required=True)
    field_parser.add_argument("--right", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "analyze-simion-log":
        particles, summary = analyze_simion_log(
            args.log,
            args.ion_file,
            mode=args.mode,
            distribution=args.distribution,
            detector_radius_mm=args.detector_radius_mm,
            allow_incomplete_census=args.allow_incomplete_census,
        )
        if args.particle_csv:
            args.particle_csv.parent.mkdir(parents=True, exist_ok=True)
            particles.to_csv(args.particle_csv, index=False)
        print(json.dumps(summary, allow_nan=False))
        return 0
    if args.command == "compare-particle-exports":
        report = compare_particle_exports(
            args.reference,
            args.candidate,
            max_tof_difference_us=args.max_tof_difference_us,
            max_landing_difference_mm=args.max_landing_difference_mm,
        )
        _write_key_value_report(report, args.report)
        print(json.dumps(report, allow_nan=False))
        return 0 if report["status"] == "PASS" else 1
    if args.command == "pulse-timing":
        timing = calculate_pulse_timing(
            args.canonical,
            source_center_x_mm=args.source_center_x_mm,
            target_origin_x_mm=args.target_origin_x_mm,
        )
        print(json.dumps(timing, allow_nan=False))
        return 0
    if args.command == "benchmark-metrics":
        metrics = build_benchmark_metrics(
            args.samples,
            run_id=args.run_id,
            mass_amu=args.mass_amu,
            charge_state=args.charge_state,
            simion_repeats=args.simion_repeats,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(metrics, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(metrics, allow_nan=False))
        return 0
    if args.command == "mass-spectrum-max-tof":
        max_tof = mass_spectrum_max_tof_us(args.mode, args.reference_mass_amu)
        print(f"{max_tof:.17g}")
        return 0
    comparison = compare_field_reports(args.left, args.right)
    print(json.dumps(comparison, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
