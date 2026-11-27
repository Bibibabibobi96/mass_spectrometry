"""Scientific metrics for a normalized historical single-reflection export."""

from __future__ import annotations

import numpy as np
import pandas as pd

from msplatform.analysis.peak_metrics import (
    AnalysisSettings, compute_detector_metrics, compute_nominal_mass_peak_metrics,
    compute_peak_metrics, compute_source_mapping_metrics,
)

SOURCE_COLUMNS = {"initial_x_mm", "initial_y_mm", "initial_z_mm", "initial_energy_eV"}


def analyze_peak_frame(frame: pd.DataFrame, nominal_mass_Da: float,
                       settings: AnalysisSettings, *, result_schema_version: int):
    """Compute the original peak, detector and optional source metrics."""
    if type(result_schema_version) is not int or result_schema_version not in (3, 4):
        raise ValueError("unsupported peak result schema_version")
    if result_schema_version == 4:
        metrics, spectra = compute_nominal_mass_peak_metrics(
            frame["tof_us"].to_numpy(), nominal_mass_Da, settings,
        )
    else:
        metrics, spectra = compute_peak_metrics(
            frame["tof_us"].to_numpy(), nominal_mass_Da, settings,
            include_result_metadata=True,
        )
    if {"detector_x_mm", "detector_y_mm"}.issubset(frame.columns):
        metrics["detector"] = compute_detector_metrics(
            frame["detector_x_mm"].to_numpy(), frame["detector_y_mm"].to_numpy()
        )
    source_arrays: dict[str, np.ndarray] | None = None
    if SOURCE_COLUMNS.issubset(frame.columns):
        source_metrics, source_arrays = compute_source_mapping_metrics(
            frame["tof_us"].to_numpy(), frame["initial_x_mm"].to_numpy(),
            frame["initial_y_mm"].to_numpy(), frame["initial_z_mm"].to_numpy(),
            frame["initial_energy_eV"].to_numpy(),
        )
        metrics["source_mapping"] = source_metrics
    return metrics, spectra, source_arrays
