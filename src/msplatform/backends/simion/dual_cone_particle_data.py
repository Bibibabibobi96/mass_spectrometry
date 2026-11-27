"""Convert verified dual-cone callback evidence and samples to SI results."""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import numpy as np

from msplatform.results.detector_observation import detector_observation
from msplatform.results.model import TraceResult
from msplatform.contracts.particle_physics import CONSTANTS


def adapt_dual_cone_results(source_rows: Sequence[Mapping], final_rows: Sequence[Mapping],
                            sample_rows: Sequence[Mapping], evidence: Mapping, *,
                            species: Mapping, backend_version: str) -> TraceResult:
    """Adapt actual callback states; inputs are already in the declared workbench frame.

    Caller supplies source rows in that frame after applying its actual Assembly
    transform. Samples retain their actual callback times; no exact-time claim is
    made. Terminal plane reach is not a detector observation.
    """
    if (not isinstance(backend_version, str) or not backend_version
            or species.get("species_kind") != "ion" or type(species.get("charge_state")) is not int
            or species["charge_state"] <= 0):
        raise ValueError("dual-cone output requires an explicit positive-ion species and backend version")
    def indexed(rows, id_key):
        result = {}
        for row in rows:
            pid = int(row[id_key])
            if pid <= 0 or pid in result:
                raise ValueError("duplicate or invalid original particle identity")
            result[pid] = row
        return result
    source, final = indexed(source_rows, "particle_id"), indexed(final_rows, "ion_number")
    if not source or set(source) != set(final) or evidence.get("status") != "recorded_v1":
        raise ValueError("source, terminal and actual callback evidence must be complete")
    facts = indexed(evidence.get("particle_evidence", []), "particle_id")
    if set(facts) != set(source):
        raise ValueError("callback evidence differs from the original cohort")
    columns = ("x_mm", "y_mm", "z_mm", "vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us")
    def numbers(row, keys):
        values = [float(row[key]) for key in keys]
        if not all(math.isfinite(value) for value in values):
            raise ValueError("nonfinite dual-cone state")
        return values
    def state(row, time_key):
        values = numbers(row, (time_key, *columns))
        return values[0] * 1e-6, [x * 1e-3 for x in values[1:4]], [x * 1e3 for x in values[4:7]]
    initial, terminal = [], []
    for pid, source_row in source.items():
        if float(source_row["birth_time_s"]) != 0:
            raise ValueError("dual-cone callback time requires zero-time births")
        if (int(source_row["charge_state"]) != species["charge_state"]
                or float(source_row["mass_amu"]) * CONSTANTS["atomic_mass_constant_kg"] != species["mass_kg"]
                or species["charge_c"] != species["charge_state"] * CONSTANTS["elementary_charge_c"]):
            raise ValueError("source mass and charge differ from the canonical species")
        raw = facts[pid]["raw"]
        records = raw.get("records", [])
        phases = {row["event"]: row for row in records}
        if raw.get("status") != "recorded_v1" or len(phases) != len(records) or not {"initialize", "terminate"} <= phases.keys():
            raise ValueError("actual initialize and terminate callbacks are required")
        birth, end = phases["initialize"], phases["terminate"]
        for name in columns:
            if float(format(float(birth[name]), ".9g")) != float(format(float(source_row[name]), ".9g")):
                raise ValueError("native initialize differs from the transformed source")
            if float(format(float(end[name]), ".9g")) != float(final[pid][name]):
                raise ValueError("native terminate differs from final-state CSV")
        if float(format(float(end["raw_tof_us"]), ".9g")) != float(final[pid]["time_us"]):
            raise ValueError("native terminate time differs from final-state CSV")
        start_t, start_p, start_v = state(birth, "raw_tof_us")
        end_t, end_p, end_v = state(end, "raw_tof_us")
        if start_t != 0 or end_t < start_t:
            raise ValueError("native callback lifetime differs from zero-time source")
        initial.append(dict(particle_id=pid, species_id=species["species_id"], position_m=start_p,
            velocity_m_s=start_v, time_s=start_t, mass_kg=species["mass_kg"], charge_state=species["charge_state"],
            charge_c=species["charge_c"], weight=1., parent_particle_id=None, lineage_status="primary_birth"))
        code = int(final[pid]["splat"])
        if code not in (0, 1, 2, 3):
            raise ValueError("unknown dual-cone program termination code")
        if code == 3:
            raise ValueError("gas-field support was lost during native tracking")
        terminal.append(dict(particle_id=pid, species_id=species["species_id"], position_m=end_p,
            velocity_m_s=end_v, time_s=end_t, physical_outcome="unknown", stop_reason="time_limit" if code == 2 else "normal",
            component_id=None, electrode_id=None, surface_id=None, attribution_method="unavailable",
            attribution_status="unavailable", started=True, backend_version=backend_version,
            native_termination_code=None if end.get("splat") is None else str(end["splat"]),
            native_entity_id=None, detail="dual_cone_program_terminal_code=" + str(code)))
    samples = {}
    for row in sample_rows:
        pid = int(row["ion_number"])
        if pid not in source:
            raise ValueError("sample references an unknown particle")
        time, position, velocity = state(row, "time_us")
        end_time = float(final[pid]["time_us"]) * 1e-6
        if time < 0 or time > end_time:
            raise ValueError("sample lies outside the native particle lifetime")
        key = (pid, time)
        if key in samples and samples[key] != (position, velocity):
            raise ValueError("contradictory duplicate native samples")
        samples[key] = (position, velocity)
    ids = list(source)
    return TraceResult(initial, terminal, [], {
        "particle_id": np.asarray([key[0] for key in samples], dtype=np.int64),
        "time_s": np.asarray([key[1] for key in samples], dtype=np.float64),
        "position_m": np.asarray([row[0] for row in samples.values()], dtype=np.float64).reshape(-1, 3),
        "velocity_m_s": np.asarray([row[1] for row in samples.values()], dtype=np.float64).reshape(-1, 3)},
        "succeeded", {"status": "complete", "mother_count": len(ids),
            "detector_observation": detector_observation("not_requested", ids, reason="detector_not_requested")})
