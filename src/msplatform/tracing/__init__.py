"""Continuous prescribed-field reference tracing in SI units.

SciPy solve_ivp DOP853 integrates the nonrelativistic Lorentz equation. Event
roots require a sign change in a step; callers must choose max_step_s adequate
for their geometry and dynamics, and tangencies are not detected reliably.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import math
from typing import Any, Protocol

import numpy as np
import scipy
from scipy.integrate import solve_ivp

from msplatform.analysis.particle_census import partition_cohort
from msplatform.fields import FieldProvider, UniformField
from msplatform.physics import CONSTANTS, GasEnvironment, normalize_charge_c


@dataclass
class TraceResult:
    """Separate scientific records, sampled SI trajectories, execution and integrity."""
    initial_states: list[dict[str, Any]]
    terminal_states: list[dict[str, Any]]
    events: list[dict[str, Any]]
    trajectories: dict[str, np.ndarray]
    execution_status: str
    data_integrity: dict[str, Any]


class ParticleTracer(Protocol):
    """Tracer for a continuous trajectory in one experiment-relative clock."""
    capabilities: dict[str, Any]

    def trace(self, recipe: Mapping[str, Any], *, cancelled: Callable[[], bool] | None = None) -> TraceResult:
        """Trace the declared mother cohort or report incomplete execution."""
        ...


def _number(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if positive and result <= 0:
        raise ValueError(f"{name} must be positive")
    return result


def _vector(value: Any, name: str) -> np.ndarray:
    if not isinstance(value, (tuple, list, np.ndarray)) or len(value) != 3:
        raise ValueError(f"{name} must have three components")
    return np.array([_number(x, name) for x in value], dtype=np.float64)


def _required(mapping: Mapping[str, Any], fields: set[str], name: str,
              optional: frozenset[str] = frozenset()) -> None:
    if not isinstance(mapping, Mapping):
        raise ValueError(f"{name} must be a mapping")
    missing = fields - mapping.keys()
    extra = mapping.keys() - fields - optional
    if missing or extra:
        raise ValueError(f"{name} missing {sorted(missing)} or unknown fields {sorted(extra)}")


def preflight(recipe: Mapping[str, Any]) -> UniformField:
    """Validate the supported combination and its required SI scientific inputs."""
    if not isinstance(recipe, Mapping):
        raise ValueError("resolved recipe must be a mapping")
    _required(recipe, {"schema_version", "frame_id", "clock", "constants", "gas_environment", "field_source",
                       "particle_tracer", "initial_states", "numerics", "surfaces", "recording"}, "recipe",
              frozenset({"label", "assembly", "recipe_id", "particle_field_coupling"}))
    if recipe["schema_version"] != 1 or not isinstance(recipe["frame_id"], str) or not recipe["frame_id"]:
        raise ValueError("unsupported schema or missing frame")
    if any(k in recipe for k in ("transport_mode", "particle_tracker")):
        raise ValueError("legacy transport/tracker selection is unsupported")
    if recipe["particle_tracer"] != "scipy_dop853":
        raise ValueError("unsupported particle_tracer")
    if recipe.get("particle_field_coupling", "prescribed") != "prescribed":
        raise ValueError("only prescribed particle-field coupling is supported")
    field = recipe["field_source"]
    if not isinstance(field, Mapping):
        raise ValueError("field_source must be a mapping")
    _required(field, {"kind", "time_dependence", "electric_field_v_m", "magnetic_field_t"}, "field_source")
    if field["kind"] != "uniform" or field["time_dependence"] != "static":
        raise ValueError("only static uniform E and B are supported")
    env = recipe["gas_environment"]
    if not isinstance(env, Mapping) or dict(env) != GasEnvironment("vacuum").to_dict():
        raise ValueError("only the public vacuum environment without collisions is supported")
    _required(recipe["clock"], {"basis", "unit"}, "clock")
    if recipe["clock"] != {"basis": "experiment_relative", "unit": "s"}:
        raise ValueError("clock must explicitly declare experiment-relative seconds")
    if not isinstance(recipe["constants"], Mapping) or dict(recipe["constants"]) != dict(CONSTANTS):
        raise ValueError("constants must match the public versioned constant set")
    if recipe["recording"] != {"trajectory": "sampled"}:
        raise ValueError("only explicit sampled trajectory recording is supported")
    num = recipe["numerics"]
    _required(num, {"end_time_s", "rtol", "position_atol_m", "velocity_atol_m_s", "max_step_s", "sample_count"}, "numerics")
    end = _number(num["end_time_s"], "end_time_s", positive=True)
    for key in ("rtol", "position_atol_m", "velocity_atol_m_s", "max_step_s"):
        _number(num[key], key, positive=True)
    if num["rtol"] >= 1:
        raise ValueError("rtol must be less than one")
    if type(num["sample_count"]) is not int or num["sample_count"] < 2:
        raise ValueError("sample_count must be an integer at least 2")
    particles = recipe["initial_states"]
    if not isinstance(particles, list) or not particles:
        raise ValueError("initial_states must be a nonempty list")
    ids = set()
    for p in particles:
        _required(p, {"particle_id", "species_id", "position_m", "velocity_m_s", "time_s", "mass_kg", "charge_state", "charge_c", "weight", "parent_particle_id", "lineage_status"}, "initial state")
        if p["parent_particle_id"] is not None or p["lineage_status"] != "unavailable_initial_snapshot":
            raise ValueError("reference inputs only support an initial snapshot with unavailable lineage")
        pid = p["particle_id"]
        if type(pid) is not int or not 0 < pid < 2**63 or pid in ids:
            raise ValueError("particle_id must be unique positive int64")
        ids.add(pid)
        if not isinstance(p["species_id"], str) or not p["species_id"]:
            raise ValueError("species_id required")
        _vector(p["position_m"], "position_m")
        _vector(p["velocity_m_s"], "velocity_m_s")
        if not 0 <= _number(p["time_s"], "time_s") < end:
            raise ValueError("end_time_s must follow every initial time")
        _number(p["mass_kg"], "mass_kg", positive=True)
        _number(p["weight"], "weight", positive=True)
        normalize_charge_c(p["charge_state"], p["charge_c"])
    surfaces = recipe["surfaces"]
    if not isinstance(surfaces, list):
        raise ValueError("surfaces must be a list")
    names = set()
    terminal_planes = set()
    for s in surfaces:
        _required(s, {"surface_id", "component_id", "electrode_id", "axis", "position_m", "kind"}, "surface")
        if not all(isinstance(s[k], str) and s[k] for k in ("surface_id", "component_id")) or s["surface_id"] in names:
            raise ValueError("surface and component identities must be explicit and unique")
        names.add(s["surface_id"])
        if s["kind"] == "electrode" and s["electrode_id"] is None:
            raise ValueError("electrode surface requires electrode identity")
        if s["electrode_id"] is not None and (not isinstance(s["electrode_id"], str) or not s["electrode_id"]):
            raise ValueError("electrode identity must be a nonempty string or null")
        if type(s["axis"]) is not int or s["axis"] not in (0, 1, 2) or s["kind"] not in ("detector", "electrode", "observation"):
            raise ValueError("unsupported plane axis or kind")
        coordinate = _number(s["position_m"], "surface position_m")
        if s["kind"] != "observation":
            plane = (s["axis"], coordinate)
            if plane in terminal_planes:
                raise ValueError("coincident terminal planes have undefined competing outcomes")
            terminal_planes.add(plane)
    return UniformField(_vector(field["electric_field_v_m"], "electric_field_v_m"),
                        _vector(field["magnetic_field_t"], "magnetic_field_t"))

class _Cancelled(Exception):
    pass


def _surface_event(surface: Mapping[str, Any]) -> Callable[[float, np.ndarray], float]:
    axis, coordinate = surface["axis"], surface["position_m"]

    def crossing(_time: float, state: np.ndarray) -> float:
        return float(state[axis] - coordinate)

    crossing.terminal = surface["kind"] != "observation"
    crossing.direction = 0
    return crossing


def _terminal(particle: Mapping[str, Any], state: np.ndarray | None, time: float | None,
              outcome: str, reason: str, surface: Mapping[str, Any] | None, *, started: bool,
              detail: str | None = None) -> dict[str, Any]:
    return {"particle_id": particle["particle_id"], "species_id": particle["species_id"],
            "position_m": None if state is None else state[:3].tolist(),
            "velocity_m_s": None if state is None else state[3:].tolist(), "time_s": time,
            "physical_outcome": outcome, "stop_reason": reason, "started": started,
            "component_id": None if surface is None else surface["component_id"],
            "electrode_id": None if surface is None else surface["electrode_id"],
            "surface_id": None if surface is None else surface["surface_id"],
            "attribution_method": "unavailable" if surface is None else "analytic_plane_event",
            "attribution_status": "unavailable" if surface is None else "known",
            "backend_version": "scipy_" + scipy.__version__,
            "native_termination_code": None, "native_entity_id": None, "detail": detail}


def _solve_particle(particle: Mapping[str, Any], field: FieldProvider, recipe: Mapping[str, Any],
                    cancelled: Callable[[], bool] | None) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, np.ndarray]]:
    num = recipe["numerics"]
    initial = np.r_[particle["position_m"], particle["velocity_m_s"]].astype(np.float64)
    start = float(particle["time_s"])
    surfaces = sorted(recipe["surfaces"], key=lambda surface: surface["kind"] != "observation")
    events = [_surface_event(surface) for surface in surfaces]
    def rhs(time: float, state: np.ndarray) -> np.ndarray:
        if cancelled is not None and cancelled():
            raise _Cancelled()
        electric, magnetic = field.sample(state[:3], time)
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            q_m = np.float64(particle["charge_c"]) / np.float64(particle["mass_kg"])
            return np.r_[state[3:], q_m * (electric + np.cross(state[3:], magnetic))]

    try:
        sol = solve_ivp(rhs, (start, num["end_time_s"]), initial, method="DOP853", dense_output=True,
                        events=events or None, rtol=num["rtol"],
                        atol=[num["position_atol_m"]] * 3 + [num["velocity_atol_m_s"]] * 3,
                        max_step=num["max_step_s"])
    except _Cancelled:
        return _terminal(particle, None, None, "unknown", "cancelled", None, started=True), [], {}
    except (FloatingPointError, ValueError) as error:
        return _terminal(particle, None, None, "unknown", "numerical_failure", None, started=True,
                         detail=f"{type(error).__name__}: {error}"), [], {}
    if not sol.success:
        return _terminal(particle, None, None, "unknown", "numerical_failure", None, started=True,
                         detail=str(sol.message)), [], {}
    event_rows = []
    terminal_surface = None
    if events:
        for surface, times, states in zip(surfaces, sol.t_events, sol.y_events):
            for time, state in zip(times, states):
                row = _terminal(particle, state, float(time), "unknown", "normal", surface, started=True)
                row["event_kind"] = surface["kind"]
                velocity = state[3 + surface["axis"]]
                row["crossing_direction"] = int(velocity > 0) - int(velocity < 0)
                event_rows.append(row)
                if surface["kind"] != "observation" and time == sol.t[-1]:
                    terminal_surface = surface
    event_rows.sort(key=lambda row: (row["time_s"], row["surface_id"]))
    for sequence, row in enumerate(event_rows, start=1):
        row["event_sequence"] = sequence
    if sol.status == 1 and terminal_surface is None:
        raise RuntimeError("solver terminated at an event without a matching surface")
    outcome = ("detected" if terminal_surface and terminal_surface["kind"] == "detector" else
               "surface_hit" if terminal_surface else "unknown")
    reason = "normal" if terminal_surface else "time_limit"
    terminal = _terminal(particle, sol.y[:, -1], float(sol.t[-1]), outcome, reason, terminal_surface, started=True)
    # Sampling covers the actual continuous interval, including terminal event time.
    times = np.linspace(start, sol.t[-1], num["sample_count"], dtype=np.float64)
    values = sol.sol(times).T
    trajectory = {"particle_id": np.full(len(times), particle["particle_id"], dtype=np.int64),
                  "time_s": times, "position_m": values[:, :3], "velocity_m_s": values[:, 3:]}
    return terminal, event_rows, trajectory


class ScipyParticleTracer:
    """DOP853 nonrelativistic, prescribed static uniform E/B with plane events."""
    capabilities = {"electric": True, "magnetic": True, "time_dependence": "static",
                    "field_representation": "uniform", "collisions": False, "coupling": "prescribed",
                    "geometry": "axis_aligned_plane", "checkpoint": False}

    def trace(self, recipe: Mapping[str, Any], *, cancelled: Callable[[], bool] | None = None) -> TraceResult:
        """Integrate each original particle, preserving clock and complete cohort identities."""
        field = preflight(recipe)
        initial = [dict(particle) for particle in recipe["initial_states"]]
        for particle in initial:
            particle["charge_c"] = normalize_charge_c(particle["charge_state"], particle["charge_c"])
        terminals, event_rows, samples = [], [], []
        stopped = False
        for particle in initial:
            if stopped or (cancelled is not None and cancelled()):
                stopped = True
                terminals.append(_terminal(particle, None, None, "unknown", "cancelled", None, started=False))
                continue
            terminal, events, trajectory = _solve_particle(particle, field, recipe, cancelled)
            terminals.append(terminal)
            event_rows.extend(events)
            if trajectory:
                samples.append(trajectory)
            if terminal["stop_reason"] == "cancelled":
                stopped = True
        categories = ["normal", "time_limit", "cancelled", "numerical_failure"]
        partition = partition_cohort([p["particle_id"] for p in initial],
                                     [(t["particle_id"], t["stop_reason"]) for t in terminals],
                                     categories=categories,
                                     relative_weights={p["particle_id"]: p["weight"] for p in initial})
        arrays = {}
        for key in ("particle_id", "time_s", "position_m", "velocity_m_s"):
            arrays[key] = (np.concatenate([sample[key] for sample in samples], axis=0) if samples else
                           np.empty((0, 3) if key in ("position_m", "velocity_m_s") else (0,),
                                    dtype=np.int64 if key == "particle_id" else np.float64))
        failed = partition["counts"]["numerical_failure"] > 0
        status = "failed" if failed else "cancelled" if stopped else "succeeded"
        missing = [t["particle_id"] for t in terminals if t["time_s"] is None]
        integrity = {"status": "incomplete" if missing else "complete", "missing_terminal_particle_ids": missing,
                     "mother_count": len(initial), "terminal_record_count": len(terminals),
                     "counts_by_stop_reason": partition["counts"]}
        return TraceResult(initial, terminals, event_rows, arrays, status, integrity)


def trace_particles(recipe: Mapping[str, Any], *, cancelled: Callable[[], bool] | None = None) -> TraceResult:
    """Trace a resolved SI recipe using the selected supported tracer."""
    return ScipyParticleTracer().trace(recipe, cancelled=cancelled)
