"""Pure trajectory census and explicitly referenced time-distribution analysis.

Callers verify producer/source/clock records and project device events into
neutral observations. No physical status or original mother is reconstructed.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict
import math

import numpy as np

from msplatform.analysis.particle_census import partition_cohort, subset_efficiency
from msplatform.analysis.peak_metrics import AnalysisSettings, compute_time_peak_metrics
from msplatform.contracts.clock import ClockIdentity


def _finite(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(label + " must be a finite number")
    return float(value)


def _observation_rows(observations, mother, selection):
    if selection is not None:
        if (not isinstance(selection, Mapping) or set(selection) != {"observation_id", "direction", "occurrence"}
                or not isinstance(selection["observation_id"], str) or not selection["observation_id"]
                or selection["direction"] not in {"outward", "inward"}
                or type(selection["occurrence"]) is not int or selection["occurrence"] < 1):
            raise ValueError("observation selection requires explicit ID/direction/positive occurrence")
    result, seen = {}, set()
    for row in observations:
        if not isinstance(row, Mapping):
            raise ValueError("observations must contain mappings")
        pid = row["particle_id"]
        if type(pid) is not int or pid not in mother:
            raise ValueError("observation ID is outside the complete original mother")
        time = _finite(row["instrument_time_us"], "observation instrument time")
        event_keys = {"observation_id", "direction", "occurrence"}
        present = event_keys & row.keys()
        if present and present != event_keys:
            raise ValueError("observation occurrence identity is incomplete")
        if present:
            if (not isinstance(row["observation_id"], str) or not row["observation_id"]
                    or row["direction"] not in {"outward", "inward"}
                    or type(row["occurrence"]) is not int or row["occurrence"] < 1):
                raise ValueError("observation occurrence identity is invalid")
            identity = (pid, row["observation_id"], row["direction"], row["occurrence"])
        else:
            identity = (pid,)
        if identity in seen:
            raise ValueError("duplicate original observation identity")
        seen.add(identity)
        if selection is not None and any(row.get(key) != value for key, value in selection.items()):
            continue
        if pid in result:
            raise ValueError("multiple observations require an explicit occurrence selection")
        result[pid] = time
    return result


def analyze_trajectory(*, mother_particle_ids, relative_weights, classifications, categories,
                       observations: Sequence[Mapping], selected_particle_ids,
                       clock: ClockIdentity, method: str, time_reference_instrument_us=None,
                       observation_selection=None, settings: AnalysisSettings | None = None) -> dict:
    """Analyze explicit neutral observations without tools or accuracy verdicts.

    IDs and classifications cover the original complete mother; selected IDs
    are caller declared, never inferred from detected survivors. Times are
    absolute instrument microseconds under the supplied verified clock. A peak
    uses one common explicit reference, never particle-specific birth or age.
    Unknown/censored categories remain exactly caller classified. Missing
    observations do not remove their IDs or weights from the mother denominator.
    """
    if not isinstance(clock, ClockIdentity):
        raise ValueError("analysis requires an explicit verified ClockIdentity")
    if method not in {"census", "time_peak"}:
        raise ValueError("unsupported trajectory analysis method")
    if settings is not None and not isinstance(settings, AnalysisSettings):
        raise ValueError("settings must be AnalysisSettings or None")
    census = partition_cohort(mother_particle_ids, classifications, categories=categories,
                              relative_weights=relative_weights)
    mother = census["mother_particle_ids"]
    selected = subset_efficiency(mother, selected_particle_ids, mother, relative_weights=relative_weights)
    ids = selected["numerator_particle_ids"]
    observed = _observation_rows(observations, set(mother), observation_selection)
    available = [pid for pid in ids if pid in observed]
    missing = [pid for pid in ids if pid not in observed]
    coverage = subset_efficiency(mother, available, mother, relative_weights=relative_weights)
    result = dict(schema_version=1, role="trajectory_analysis", method=method,
                  status="analysis_completed", census=census, selected_population=selected,
                  observed_population=coverage, selected_particle_ids=ids,
                  observed_particle_ids=available, missing_observation_particle_ids=missing,
                  clock=asdict(clock), observation_selection=(dict(observation_selection)
                      if observation_selection is not None else None),
                  peak_metrics=None, spectra=None, unavailable_reason=None,
                  qualification="descriptive_analysis_only; no clock, convergence, field or mass calibration qualification")
    if method == "census":
        return result
    reference = _finite(time_reference_instrument_us, "common instrument reference")
    result["time_axis"] = dict(quantity="time_since_common_instrument_reference", unit="us",
                               reference_instrument_time_us=reference, clock=asdict(clock))
    if missing or len(available) < 3:
        result.update(status="insufficient_observations", unavailable_reason=(
            "selected_observations_missing" if missing else "fewer_than_three_selected_observations"))
        return result
    times = np.asarray([observed[pid] - reference for pid in ids], dtype=float)
    if not np.all(np.isfinite(times)) or np.any(times <= 0):
        raise ValueError("selected instrument times must follow the common reference")
    weights = np.asarray([1. if relative_weights is None else relative_weights[pid] for pid in ids], dtype=float)
    if not np.all(weights == weights[0]):
        result.update(status="unsupported_weight_policy", unavailable_reason="time_peak_requires_equal_positive_relative_weights")
        return result
    if np.std(times, ddof=1) <= 0:
        result.update(status="insufficient_observations", unavailable_reason="zero_time_variance")
        return result
    metrics, spectra = compute_time_peak_metrics(times, settings, weights=weights)
    result["peak_metrics"] = metrics
    result["spectra"] = {key: value.tolist() for key, value in spectra.items()}
    result["time_equivalent_resolution_scope"] = "time-distribution equivalent only; not a mass-spectrum resolution or calibration"
    return result
