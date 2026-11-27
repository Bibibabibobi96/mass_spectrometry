"""Peak analysis of verified-birth SI detector events, with explicit time basis."""
from __future__ import annotations

import math
from typing import Any, Mapping

import pandas as pd

from msplatform.analysis.peak_metrics import AnalysisSettings
from msplatform.analysis.single_reflection_peak_analysis import analyze_peak_frame


def analyze_native_detector_peak(data: Mapping[str, Any], *, species_id: str, surface_id: str,
                                 nominal_mass_da: float, settings: AnalysisSettings,
                                 declared_surface_ids: tuple[str, ...]) -> dict[str, Any]:
    """Analyze selected detector events by elapsed time from each verified native birth.

    The input is an already validated SI particle data product. No surface or
    detector coordinates are inferred from a position or an unknown terminal.
    """
    if not isinstance(species_id, str) or not species_id or not isinstance(surface_id, str) or not surface_id:
        raise ValueError("explicit species and detector surface are required")
    if (not isinstance(declared_surface_ids, tuple) or not declared_surface_ids
            or any(not isinstance(value, str) or not value for value in declared_surface_ids)
            or len(set(declared_surface_ids)) != len(declared_surface_ids) or surface_id not in declared_surface_ids):
        raise ValueError("selected detector surface is not declared by the frozen producer")
    if isinstance(nominal_mass_da, bool) or not isinstance(nominal_mass_da, (float, int)) or not math.isfinite(nominal_mass_da) or nominal_mass_da <= 0:
        raise ValueError("nominal mass must be positive finite")
    metadata = data.get("metadata", {})
    if data.get("schema_version") != 2 or metadata.get("initial_state_basis") != "native_birth_verified":
        raise ValueError("peak flight times require verified native birth")
    integrity = data.get("data_integrity", {})
    coverage = integrity.get("detector_observation", {})
    if (data.get("execution_status") != "succeeded" or integrity.get("status") != "complete"
            or coverage.get("status") != "complete"):
        raise ValueError("complete detector observation is required")
    cohort = [row for row in data["initial_states"] if row["species_id"] == species_id]
    if not cohort:
        raise ValueError("selected species is absent from the original cohort")
    birth = {row["particle_id"]: row for row in cohort}
    if len(birth) != len(cohort) or any(row.get("lineage_status") != "primary_birth" for row in cohort):
        raise ValueError("selected original birth identities differ")
    if len({row["weight"] for row in cohort}) != 1:
        raise ValueError("weighted peak analysis is not implemented")
    selected = {}
    for event in data["events"]:
        if event["event_kind"] != "detector" or event["surface_id"] != surface_id or event["particle_id"] not in birth:
            continue
        particle_id = event["particle_id"]
        if event.get("physical_outcome") != "detected" or event.get("attribution_status") != "known":
            raise ValueError("selected detector event lacks native detector attribution")
        if particle_id in selected or event["species_id"] != species_id:
            raise ValueError("detector event is duplicated or has a different species")
        elapsed_s = event["time_s"] - birth[particle_id]["time_s"]
        if not math.isfinite(elapsed_s) or elapsed_s <= 0:
            raise ValueError("detector event must follow its verified birth")
        selected[particle_id] = elapsed_s * 1e6
    summary = {"time_basis": "flight_time_from_verified_birth", "time_unit": "us",
               "species_id": species_id, "surface_id": surface_id, "mother_count": len(cohort),
               "detector_observed_count": len(selected), "not_detected_count": len(cohort) - len(selected)}
    if len(selected) < 3:
        return {"status": "unavailable", "reason": "fewer_than_three_detector_events",
                "summary": summary, "metrics": None, "spectra": None}
    frame = pd.DataFrame({"tof_us": list(selected.values())})
    metrics, spectra, _ = analyze_peak_frame(frame, float(nominal_mass_da), settings, result_schema_version=4)
    return {"status": "complete", "reason": None, "summary": summary, "metrics": metrics, "spectra": spectra}
