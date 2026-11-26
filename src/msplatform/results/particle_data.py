"""Versioned SI particle tables and sampled trajectories, independent of solvers.

Parquet IDs are int64 and scientific scalars are binary64. HDF5 stores columnar
samples, with explicit frame/clock metadata; no pickle or backend runtime is used.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

import h5py
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from msplatform.analysis.particle_census import partition_cohort, subset_efficiency


def _data_version(metadata: Mapping[str, Any]) -> int:
    version = metadata.get("schema_version", 1)
    if type(version) is not int or version not in (1, 2):
        raise ValueError("unsupported particle data version")
    if version == 2 and metadata.get("initial_state_basis") != "native_birth_verified":
        raise ValueError("version2 requires explicit verified native birth provenance")
    return version


def _schema(kind: str, metadata: Mapping[str, Any]) -> pa.Schema:
    vector = pa.list_(pa.field("element", pa.float64()), 3)
    fields = [("particle_id", pa.int64()), ("species_id", pa.string()),
              ("position_m", vector), ("velocity_m_s", vector), ("time_s", pa.float64())]
    if kind == "initial_states":
        fields += [("mass_kg", pa.float64()), ("charge_state", pa.int64()),
                   ("charge_c", pa.float64()), ("weight", pa.float64()),
                   ("parent_particle_id", pa.int64()), ("lineage_status", pa.string())]
    else:
        fields += [("physical_outcome", pa.string()), ("stop_reason", pa.string()),
                   ("component_id", pa.string()), ("electrode_id", pa.string()),
                   ("surface_id", pa.string()), ("attribution_method", pa.string()),
                   ("attribution_status", pa.string()), ("started", pa.bool_()),
                   ("backend_version", pa.string()), ("native_termination_code", pa.string()),
                   ("native_entity_id", pa.string()), ("detail", pa.string())]
        if kind == "events":
            fields += [("event_kind", pa.string()), ("event_sequence", pa.int64()), ("crossing_direction", pa.int64())]
    info = {**metadata, "schema_version": _data_version(metadata), "kind": kind, "unit_system": "SI"}
    return pa.schema(fields, metadata={b"msplatform": json.dumps(info, sort_keys=True).encode()})


def write_particle_data(directory: Path, result: Any, *, metadata: Mapping[str, Any]) -> None:
    """Write four distinct data products into an existing private work directory."""
    version = _data_version(metadata)
    for kind in ("initial_states", "terminal_states", "events"):
        rows = getattr(result, kind)
        schema = _schema(kind, metadata)
        if any(set(row) != set(schema.names) for row in rows):
            raise ValueError(f"unrecognized {kind} fields; refusing silent data loss")
        # The explicit schema also preserves typed columns for a valid zero-hit table.
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), directory / f"{kind}.parquet")
    with h5py.File(directory / "trajectories.h5", "x") as stream:
        stream.attrs["msplatform"] = json.dumps({**metadata, "schema_version": version, "unit_system": "SI"})
        for name in ("particle_id", "time_s", "position_m", "velocity_m_s"):
            values = np.asarray(result.trajectories[name], dtype="int64" if name == "particle_id" else "float64")
            stream.create_dataset(name, data=values, chunks=True)
    (directory / "execution.json").write_text(json.dumps({
        "schema_version": version, "execution_status": result.execution_status,
        "data_integrity": result.data_integrity,
    }, allow_nan=False, indent=2), encoding="utf-8")


def read_particle_data(directory: Path) -> dict[str, Any]:
    """Read and validate typed published products; raise for malformed products."""
    data: dict[str, Any] = {}
    common = None
    version = None
    for kind in ("initial_states", "terminal_states", "events"):
        table = pq.read_table(directory / f"{kind}.parquet")
        metadata = json.loads((table.schema.metadata or {}).get(b"msplatform", b"{}"))
        actual_version = _data_version(metadata)
        if (version is not None and version != actual_version) or metadata.get("kind") != kind or metadata.get("unit_system") != "SI":
            raise ValueError(f"invalid {kind} schema metadata")
        version = actual_version
        expected = _schema(kind, {k: v for k, v in metadata.items() if k not in {"kind", "unit_system"}})
        if not table.schema.equals(expected, check_metadata=True):
            raise ValueError(f"invalid {kind} column types")
        identity = {k: metadata[k] for k in ("frame_id", "clock")}
        if version == 2:
            identity["initial_state_basis"] = metadata["initial_state_basis"]
        if common is not None and common != identity:
            raise ValueError("particle products disagree on frame/clock")
        common = identity
        data[kind] = table.to_pylist()
    with h5py.File(directory / "trajectories.h5", "r") as stream:
        metadata = json.loads(stream.attrs["msplatform"])
        if metadata.get("schema_version") != version or any(metadata.get(k) != common[k] for k in common):
            raise ValueError("trajectory schema/frame/clock mismatch")
        data["trajectories"] = {name: stream[name][:] for name in ("particle_id", "time_s", "position_m", "velocity_m_s")}
    trajectory = data["trajectories"]
    size = len(trajectory["particle_id"])
    for name, values in trajectory.items():
        shape = (size, 3) if name in {"position_m", "velocity_m_s"} else (size,)
        dtype = np.dtype("int64" if name == "particle_id" else "float64")
        if values.shape != shape or values.dtype != dtype or not np.all(np.isfinite(values)):
            raise ValueError(f"invalid trajectory {name}")
    data.update(json.loads((directory / "execution.json").read_text(encoding="utf-8")))
    if data.get("schema_version") != version:
        raise ValueError("execution and scientific data versions disagree")
    data["metadata"] = common
    _validate_records(data)
    return data


def _validate_records(data: Mapping[str, Any]) -> None:
    """Validate scientific values in addition to the file format's column types."""
    if data.get("schema_version") not in (1, 2) or data["execution_status"] not in {"succeeded", "failed", "cancelled"}:
        raise ValueError("unsupported execution contract")
    for kind in ("initial_states", "terminal_states", "events"):
        seen = set()
        for row in data[kind]:
            pid = row["particle_id"]
            if type(pid) is not int or pid <= 0 or (kind != "events" and pid in seen):
                raise ValueError("particle records require original positive unique integer IDs")
            seen.add(pid)
            if not row["species_id"]:
                raise ValueError("missing particle species identity")
            for name in ("position_m", "velocity_m_s", "time_s"):
                value = row[name]
                if value is None:
                    if kind == "initial_states" or row["stop_reason"] not in {"cancelled", "numerical_failure"}:
                        raise ValueError("missing physical state without an incomplete stop reason")
                    continue
                values = value if isinstance(value, list) else [value]
                if any(not math.isfinite(v) for v in values):
                    raise ValueError("nonfinite scientific state")
            if kind == "initial_states":
                if any(not math.isfinite(row[k]) or row[k] <= 0 for k in ("mass_kg", "weight")):
                    raise ValueError("mass and statistical weight must be positive finite")
                expected_lineage = "primary_birth" if data["schema_version"] == 2 else "unavailable_initial_snapshot"
                if row["parent_particle_id"] is not None or row["lineage_status"] != expected_lineage:
                    raise ValueError("initial-state lineage contradicts the versioned birth/snapshot contract")
            elif row["physical_outcome"] not in {"detected", "surface_hit", "escaped", "unknown"} or row["stop_reason"] not in {
                    "normal", "time_limit", "cancelled", "numerical_failure"}:
                raise ValueError("unsupported physical outcome/stop reason")
    mother = {r["particle_id"]: r for r in data["initial_states"]}
    for row in data["terminal_states"] + data["events"]:
        if row["particle_id"] not in mother or row["species_id"] != mother[row["particle_id"]]["species_id"]:
            raise ValueError("result identity disagrees with initial cohort")
        if row["time_s"] is not None and row["time_s"] < mother[row["particle_id"]]["time_s"]:
            raise ValueError("result precedes particle birth")
    last_event: dict[int, tuple[int, float]] = {}
    for row in data["events"]:
        pid = row["particle_id"]
        previous = last_event.get(pid, (0, mother[pid]["time_s"]))
        if (row["event_sequence"] != previous[0] + 1 or row["time_s"] < previous[1]
                or row["crossing_direction"] not in {-1, 0, 1}):
            raise ValueError("event sequence, direction or time is invalid")
        last_event[pid] = (row["event_sequence"], row["time_s"])
    last_time = {}
    for pid, time in zip(data["trajectories"]["particle_id"], data["trajectories"]["time_s"]):
        pid = int(pid)
        if pid not in mother or time < last_time.get(pid, mother[pid]["time_s"]):
            raise ValueError("trajectory identity/time violates initial cohort")
        last_time[pid] = time


def summarize_particle_data(data: Mapping[str, Any]) -> dict[str, Any]:
    """Count outcomes against the complete initial mother cohort, including missing records."""
    initial = data["initial_states"]
    mother = [row["particle_id"] for row in initial]
    weights = {row["particle_id"]: row["weight"] for row in initial}
    terminal: dict[int, Any] = {}
    for row in data["terminal_states"]:
        pid = row["particle_id"]
        if pid not in weights or pid in terminal:
            raise ValueError("terminal IDs must be unique members of initial cohort")
        terminal[pid] = row
    categories = ("detected", "surface_hit", "escaped", "unknown", "missing_record")
    classifications = [(pid, terminal[pid]["physical_outcome"] if pid in terminal else "missing_record") for pid in mother]
    census = partition_cohort(mother, classifications, categories=categories, relative_weights=weights)
    detected = census["particle_ids_by_category"]["detected"]
    efficiency = subset_efficiency(mother, detected, mother, relative_weights=weights)
    trajectory_ids = set(map(int, data["trajectories"]["particle_id"]))
    if not trajectory_ids <= set(mother):
        raise ValueError("trajectory has foreign particle IDs")
    if any(row["particle_id"] not in weights for row in data["events"]):
        raise ValueError("event has foreign particle IDs")
    missing = [pid for pid in mother if pid not in terminal or terminal[pid].get("time_s") is None]
    integrity = dict(data["data_integrity"])
    if missing:
        integrity["status"] = "incomplete"
    return {"schema_version": 1, "execution_status": data["execution_status"],
            "data_integrity": integrity,
            "missing_terminal_ids": missing, "census": census, "detection_efficiency": efficiency,
            "arrival_analysis": {"status": "applicable" if detected else "not_applicable",
                                 "reason": None if detected else "zero_detected_particles"},
            "stop_reasons": {reason: sum(row["stop_reason"] == reason for row in terminal.values())
                             for reason in sorted({row["stop_reason"] for row in terminal.values()})}}
