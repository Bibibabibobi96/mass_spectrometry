"""SIMION detector-crossing census and birth-relative diagnostic metrics."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from msplatform.analysis.peak_metrics import FWHM_FACTOR
from msplatform.backends.simion import ion_table as simion_ion_table


DETECTOR_PATTERN = re.compile(
    r"TRACE: detector_crossing ion=(\d+) "
    r"t=([-+0-9.eE]+) x=([-+0-9.eE]+) y=([-+0-9.eE]+) "
    r"z=([-+0-9.eE]+) r=([-+0-9.eE]+) zmax=([-+0-9.eE]+)"
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


def analyze_simion_log(
    log_path: Path,
    ion_path: Path,
    *,
    mode: str,
    distribution: str,
    detector_radius_mm: float,
    allow_incomplete_census: bool,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Diagnose unique plane events using birth-relative Gaussian proxies.

    Missing events remain unobserved members of the source population. These
    auxiliary time statistics do not establish pulse-relative mass resolution.
    """
    if not math.isfinite(detector_radius_mm) or detector_radius_mm <= 0:
        raise ValueError("detector_radius_mm must be finite and positive")
    initial = simion_ion_table.read_ion_table(ion_path).set_index("Ion", drop=False)
    if not np.all(np.isfinite(initial.to_numpy(dtype=float))):
        raise ValueError("ION source contains non-finite values")
    rows: list[dict[str, Any]] = []
    observed_ids: set[int] = set()
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = DETECTOR_PATTERN.search(line)
        if not match:
            if "TRACE: detector_crossing" in line:
                raise ValueError(f"Malformed detector crossing in {log_path}: {line}")
            continue
        ion = int(match.group(1))
        if ion not in initial.index:
            raise ValueError(f"Detector crossing references absent ion {ion}")
        if ion in observed_ids:
            raise ValueError(f"Duplicate detector crossing for ion {ion}")
        observed_ids.add(ion)
        source = initial.loc[ion]
        event = np.asarray([float(match.group(index)) for index in range(2, 8)])
        if not np.all(np.isfinite(event)):
            raise ValueError(f"Detector crossing contains non-finite values for ion {ion}")
        radius = float(match.group(6))
        if radius < 0 or float(match.group(2)) <= float(source["TobUs"]):
            raise ValueError(f"Invalid detector radius or birth-relative TOF for ion {ion}")
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
    columns = [
        "Mode", "Distribution", "Ion", "MassAmu", "ChargeState", "X0Mm",
        "Y0Mm", "Z0Mm", "EnergyEv", "TofUs", "InstrumentTimeUs", "XMm",
        "YMm", "RadiusMm", "ZmaxMm", "Hit",
    ]
    crossings = pd.DataFrame(rows, columns=columns)
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
        full = (
            missing_rows[columns].copy() if full.empty
            else pd.concat([full, missing_rows[columns]], ignore_index=True)
        )
    full["Hit"] = full["Hit"].astype(bool)
    full["ObservationStatus"] = np.where(
        full["Ion"].isin(observed_ids), "recorded_crossing", "not_observed"
    )
    full = full.sort_values("Ion").reset_index(drop=True)

    hits = full[full["Hit"]]
    misses = full[~full["Hit"]]
    hit_tof = hits["TofUs"].to_numpy(dtype=float)
    std_tof_us = _sample_std(hit_tof)
    fwhm_tof_us = float(FWHM_FACTOR * std_tof_us)
    peak_status = (
        "no_hits" if hit_tof.size == 0 else
        "insufficient_samples" if hit_tof.size < 2 else
        "zero_variance" if std_tof_us == 0 else "computed"
    )
    proxy_resolution = (
        _mean(hit_tof) / (2.0 * fwhm_tof_us)
        if peak_status == "computed" else math.nan
    )

    def values(frame: pd.DataFrame, column: str) -> np.ndarray:
        return frame[column].to_numpy(dtype=float)

    summary = {
        "DiagnosticMethod": "birth_relative_sample_sigma_gaussian_proxy_v1",
        "TofTimeReference": "particle_birth",
        "ResolutionClaim": False,
        "PeakStatus": peak_status,
        "SourceParticleIds": initial["Ion"].astype(int).tolist(),
        "CrossingParticleIds": sorted(observed_ids),
        "HitParticleIds": hits["Ion"].astype(int).tolist(),
        "UnobservedParticleIds": [int(ion) for ion in missing],
        "Mode": mode,
        "Distribution": distribution,
        "Emitted": int(len(initial)),
        "Crossed": int(len(crossings)),
        "Unobserved": int(len(missing)),
        "Hit": int(len(hits)),
        "EfficiencyPct": 100.0 * len(hits) / len(initial),
        "MeanTofUs": _finite_or_none(_mean(hit_tof)),
        "StdTofNs": _finite_or_none(1000.0 * std_tof_us),
        "GaussianProxyFwhmTofNs": _finite_or_none(1000.0 * fwhm_tof_us),
        "GaussianProxyTimeEquivalentResolution": _finite_or_none(proxy_resolution),
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
        "analysis_metadata": {
            "schema_version": 1,
            "method_id": "birth_relative_sample_sigma_gaussian_proxy_v1",
            "status": peak_status,
            "scientific_qualification": "not_assessed",
            "resolution_claim_allowed": False,
            "sample_sigma_ddof": 1,
            "weight_policy": "equal_particle_ids",
            "sample_unit": "original_source_particle_id",
            "sample_count": int(len(hits)),
            "weight_sum": float(len(hits)),
            "effective_sample_count": float(len(hits)),
            "settings": {
                "gaussian_sigma_to_fwhm_factor": FWHM_FACTOR,
                "detector_radius_mm": detector_radius_mm,
                "allow_incomplete_census": allow_incomplete_census,
            },
            "units": {"tof": "us", "time_width": "ns", "position": "mm", "energy": "eV"},
            "time_reference": {
                "kind": "particle_birth",
                "expression": "detector_crossing.t - ION.TobUs",
                "clock_qualification": "birth_relative_only_no_pulse_epoch",
            },
            "observation": {
                "event": "detector_crossing",
                "multiplicity": "one_recorded_event_per_original_source_id",
                "hit_selection": "recorded RadiusMm <= detector_radius_mm",
                "unobserved_policy": "retain_source_id_as_not_observed; no_physical_loss_inference",
                "source_ion_file": str(ion_path.resolve()),
                "event_log": str(log_path.resolve()),
            },
            "metric_scope": {
                "primary_peak": "hits",
                "AllCrossingStdTofNs": "recorded_crossings",
                "CorrTof": "hits",
                "CorrRadius": "recorded_crossings",
                "MissMean": "non_hits_including_unobserved_source_ids",
            },
            "cohorts": {
                name: {"sample_count": count, "weight_sum": float(count),
                       "effective_sample_count": float(count)}
                for name, count in (
                    ("source", len(initial)), ("recorded_crossings", len(crossings)),
                    ("hits", len(hits)), ("non_hits_including_unobserved_source_ids", len(misses)),
                )
            },
            "width_definition": "FWHM_FACTOR * sample_std(hit_tof, ddof=1); Gaussian proxy, not direct half-height width",
            "time_equivalent_ratio_definition": "mean(hit_tof) / (2 * Gaussian proxy width); no mass-resolution qualification",
            "null_policy": "empty/singleton sample width is null; zero variance width is zero and ratio is null",
        },
    }
    return full, summary
