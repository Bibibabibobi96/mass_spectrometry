"""Analyze paired real RF-to-oaTOF downstream branches without qualification."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from common.contracts.component_particle_state import (
    csv_columns,
    validate_component_particle_state_csv,
)
from common.contracts.file_identity import file_sha256
from common.contracts.verify_run_manifest import verify_record
from projects.single_reflection_oa_tof_mass_analyzer.analysis.peak_metrics import (
    compute_detector_metrics,
    compute_peak_metrics,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.reference_analysis import (
    DEFAULT_DETECTOR_CENTER_X_MM,
    DEFAULT_DETECTOR_CENTER_Y_MM,
)

INTEGRATION_ID = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
REQUEST_ROLE = "rf_oatof_paired_downstream_analysis_request"
RESULT_ROLE = "rf_oatof_paired_downstream_analysis"
TERMINAL_MODE = "rf_to_oatof_analyzer_transport_n100"
SOLVERS = ("comsol", "simion")
BRANCH_KEYS = {
    "manifest",
    "canonical_local_exit",
    "row_map",
    "downstream_particles",
    "metrics",
    "summary",
    "resolved_connection",
    "runtime_binding",
    "source_manifest",
    "source_state",
    "source_input",
}
REFERENCE_KEYS = {"path", "sha256"}
SOURCE_IDENTITY_KEYS = {
    "source_branch_id",
    "solver_id",
    "run_id",
    "project_id",
    "manifest_sha256",
    "event_sha256",
    "particle_source_sha256",
    "metadata_sha256",
}
REPO_ROOT = Path(__file__).resolve().parents[3]
ROW_MAP_COLUMNS = [
    "solver_row_index",
    "particle_id",
    "instrument_time_us",
    "lineage_age_us",
    "particle_age_us",
    "solver_birth_time_us",
    "azimuth_deg",
    "elevation_deg",
]
DOWNSTREAM_COLUMNS = {
    "Ion",
    "MassAmu",
    "ChargeState",
    "X0Mm",
    "Y0Mm",
    "Z0Mm",
    "TofUs",
    "InstrumentTimeUs",
    "XMm",
    "YMm",
    "RadiusMm",
    "Hit",
}
SEMANTIC_FIELDS = (
    "species_id",
    "parent_particle_id",
    "generation",
    "particle_weight",
    "mass_amu",
    "charge_state",
    "source_component_id",
    "target_component_id",
)
OBJECTIVE_DIRECTIONS = {
    "worst_detector_hit_fraction": "maximize",
    "worst_mass_resolution": "maximize",
    "worst_direct_fwhm_tof_ns": "minimize",
    "worst_landing_rms_radius_mm": "minimize",
    "detector_hit_symmetric_difference_count": "minimize",
    "local_exit_particle_symmetric_difference_count": "minimize",
    "paired_position_rms_distance_mm": "minimize",
    "paired_velocity_rms_distance_m_s": "minimize",
    "paired_time_rms_difference_us": "minimize",
    "paired_energy_rms_difference_eV": "minimize",
}
_SHA256 = re.compile(r"^[0-9A-F]{64}$")


class DownstreamAnalysisError(ValueError):
    """Raised when paired evidence is incomplete or inconsistent."""


@dataclass(frozen=True)
class BranchData:
    summary: dict[str, Any]
    metrics: dict[str, Any]
    states: dict[int, dict[str, Any]]
    downstream: dict[int, dict[str, Any]]
    source_lineage: dict[str, str]
    binding_identity: dict[str, str]


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DownstreamAnalysisError(f"{label} must be an object")
    return value


def _exact(value: Mapping[str, Any], keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise DownstreamAnalysisError(
            f"{label} fields differ; missing={sorted(keys - set(value))}, "
            f"unknown={sorted(set(value) - keys)}"
        )


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DownstreamAnalysisError(f"{label} must be finite")
    result = float(value)
    if not math.isfinite(result):
        raise DownstreamAnalysisError(f"{label} must be finite")
    return result


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise DownstreamAnalysisError(f"cannot load {label}: {path}") from error
    if not isinstance(value, dict):
        raise DownstreamAnalysisError(f"{label} root must be an object")
    return value


def _reference(value: Any, base: Path, label: str) -> tuple[Path, str]:
    item = _mapping(value, label)
    _exact(item, REFERENCE_KEYS, label)
    raw_path, sha256 = item["path"], item["sha256"]
    if not isinstance(raw_path, str) or not raw_path:
        raise DownstreamAnalysisError(f"{label}.path must be nonempty")
    path = Path(raw_path)
    path = path.resolve() if path.is_absolute() else (base / path).resolve()
    if not path.is_file():
        raise DownstreamAnalysisError(f"{label} is missing: {path}")
    if not isinstance(sha256, str) or not _SHA256.fullmatch(sha256):
        raise DownstreamAnalysisError(f"{label}.sha256 must be uppercase SHA-256")
    if file_sha256(path) != sha256:
        raise DownstreamAnalysisError(f"{label} SHA-256 differs")
    return path, sha256


def _record_for_path(
    records: Any,
    path: Path,
    label: str,
) -> dict[str, Any]:
    iterable = records.values() if isinstance(records, Mapping) else records
    if not isinstance(iterable, (list, tuple, type({}.values()))):
        raise DownstreamAnalysisError(f"{label} manifest records are invalid")
    matches = [
        record
        for record in iterable
        if isinstance(record, dict)
        and Path(str(record.get("path", ""))).resolve() == path
    ]
    if len(matches) != 1:
        raise DownstreamAnalysisError(f"{label} is not bound exactly once")
    try:
        verify_record(label, matches[0])
    except (AssertionError, KeyError, TypeError) as error:
        raise DownstreamAnalysisError(f"{label} identity failed: {error}") from error
    return matches[0]


def _read_csv(path: Path, label: str) -> tuple[list[str], list[dict[str, str]]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            return list(reader.fieldnames or []), list(reader)
    except OSError as error:
        raise DownstreamAnalysisError(f"cannot load {label}: {path}") from error


def _load_states(
    path: Path,
    frame_id: str,
    clock_epoch_id: str,
    label: str,
) -> dict[int, dict[str, Any]]:
    try:
        report = validate_component_particle_state_csv(path)
    except (OSError, ValueError) as error:
        raise DownstreamAnalysisError(f"{label} canonical state: {error}") from error
    if report["frame_ids"] != [frame_id] or report["clock_epoch_ids"] != [clock_epoch_id]:
        raise DownstreamAnalysisError(f"{label} canonical frame/clock differs")
    fields, rows = _read_csv(path, label)
    if fields != csv_columns():
        raise DownstreamAnalysisError(f"{label} canonical columns differ")
    states: dict[int, dict[str, Any]] = {}
    for row in rows:
        particle_id = int(row["particle_id"])
        states[particle_id] = {
            **{name: row[name] for name in SEMANTIC_FIELDS},
            "parent_particle_id": (
                None if row["parent_particle_id"] == "" else int(row["parent_particle_id"])
            ),
            "generation": int(row["generation"]),
            "particle_weight": float(row["particle_weight"]),
            "mass_amu": float(row["mass_amu"]),
            "charge_state": int(row["charge_state"]),
            "position": tuple(float(row[f"position_{axis}_mm"]) for axis in "xyz"),
            "velocity": tuple(float(row[f"velocity_{axis}_m_s"]) for axis in "xyz"),
            "instrument_time_us": float(row["instrument_time_us"]),
            "kinetic_energy_eV": float(row["kinetic_energy_eV"]),
        }
    return states


def _load_downstream(
    row_map_path: Path,
    downstream_path: Path,
    states: Mapping[int, Mapping[str, Any]],
    label: str,
) -> dict[int, dict[str, Any]]:
    map_fields, map_rows = _read_csv(row_map_path, f"{label} row map")
    if map_fields != ROW_MAP_COLUMNS or not map_rows:
        raise DownstreamAnalysisError(f"{label} row map schema/census differs")
    solver_to_particle = {
        int(row["solver_row_index"]): int(row["particle_id"]) for row in map_rows
    }
    if len(solver_to_particle) != len(map_rows) or set(solver_to_particle.values()) != set(states):
        raise DownstreamAnalysisError(f"{label} row map identity differs")
    fields, rows = _read_csv(downstream_path, f"{label} downstream particles")
    if not DOWNSTREAM_COLUMNS.issubset(fields) or len(rows) != len(map_rows):
        raise DownstreamAnalysisError(f"{label} downstream schema/census differs")
    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        solver_id = int(row["Ion"])
        if solver_id not in solver_to_particle:
            raise DownstreamAnalysisError(f"{label} downstream Ion identity differs")
        particle_id = solver_to_particle[solver_id]
        if particle_id in result:
            raise DownstreamAnalysisError(f"{label} downstream Ion identity differs")
        hit_text = row["Hit"].strip().lower()
        if hit_text not in {"true", "false"}:
            raise DownstreamAnalysisError(f"{label} downstream Hit is invalid")
        terminal = []
        for name in ("TofUs", "InstrumentTimeUs", "XMm", "YMm", "RadiusMm"):
            text = row[name].strip()
            value = None if not text or text.lower() == "nan" else float(text)
            if value is not None and not math.isfinite(value):
                raise DownstreamAnalysisError(f"{label} downstream {name} is nonfinite")
            terminal.append(value)
        if any(value is None for value in terminal) and not all(
            value is None for value in terminal
        ):
            raise DownstreamAnalysisError(f"{label} detector state is partial")
        hit = hit_text == "true"
        if hit and all(value is None for value in terminal):
            raise DownstreamAnalysisError(f"{label} hit lacks detector state")
        mass = _finite(float(row["MassAmu"]), f"{label}.MassAmu")
        charge = int(float(row["ChargeState"]))
        if mass != states[particle_id]["mass_amu"] or charge != states[particle_id]["charge_state"]:
            raise DownstreamAnalysisError(f"{label} downstream species differs")
        result[particle_id] = {
            "hit": hit,
            "crossing": terminal[0] is not None,
            "tof_us": terminal[0],
            "instrument_time_us": terminal[1],
            "x_mm": terminal[2],
            "y_mm": terminal[3],
            "radius_mm": terminal[4],
        }
    if set(result) != set(states):
        raise DownstreamAnalysisError(f"{label} downstream rows differ from row map")
    return result


def _validate_source_manifest(
    manifest_path: Path,
    state_path: Path,
    input_path: Path,
    expected: Mapping[str, Any],
    label: str,
) -> dict[str, str]:
    manifest = _load_json(manifest_path, f"{label} source manifest")
    if (
        manifest.get("role") != "simulation_run_manifest"
        or manifest.get("status") != "success"
        or manifest.get("run_id") != expected["run_id"]
        or manifest.get("project") != expected["project_id"]
        or file_sha256(manifest_path) != expected["manifest_sha256"]
    ):
        raise DownstreamAnalysisError(f"{label} source manifest identity differs")
    state_record = _record_for_path(manifest.get("outputs"), state_path, f"{label} source state")
    input_record = _record_for_path(manifest.get("inputs"), input_path, f"{label} source input")
    if (
        str(state_record.get("sha256", "")).upper() != expected["event_sha256"]
        or str(input_record.get("sha256", "")).upper()
        != expected["particle_source_sha256"]
    ):
        raise DownstreamAnalysisError(f"{label} source artifact identity differs")
    return {
        "source_branch_id": str(expected["source_branch_id"]),
        "source_solver_id": str(expected["solver_id"]),
        "source_run_id": str(expected["run_id"]),
        "source_project_id": str(expected["project_id"]),
        "source_manifest_sha256": file_sha256(manifest_path),
        "source_state_sha256": str(state_record["sha256"]).upper(),
        "source_input_sha256": str(input_record["sha256"]).upper(),
        "source_metadata_sha256": str(expected["metadata_sha256"]),
    }


def _source_identity(
    runtime: Mapping[str, Any],
    run_config: Mapping[str, Any],
    solver: str,
    label: str,
) -> dict[str, str]:
    contracts = _mapping(runtime.get("contracts"), f"{label} runtime contracts")
    contract_path, _ = _reference(
        contracts.get("source_contract"),
        REPO_ROOT,
        f"{label} runtime source contract",
    )
    contract = _load_json(contract_path, f"{label} source contract")
    if (
        contract.get("schema_version") != 2
        or contract.get("role") != "rf_multipole_oatof_source_contract"
        or contract.get("upstream_project_id") != runtime.get("upstream_project_id")
    ):
        raise DownstreamAnalysisError(f"{label} source contract identity differs")
    branches = _mapping(contract.get("source_branches"), f"{label} source branches")
    branch = _mapping(branches.get(solver), f"{label} source branch {solver}")
    if branch.get("solver_id") != solver:
        raise DownstreamAnalysisError(f"{label} source branch solver differs")
    source = _mapping(branch.get("source"), f"{label} source branch record")

    def source_sha(name: str) -> str:
        reference = _mapping(source.get(name), f"{label} source {name}")
        value = reference.get("sha256")
        if not isinstance(value, str) or not _SHA256.fullmatch(value):
            raise DownstreamAnalysisError(
                f"{label} source {name}.sha256 must be uppercase SHA-256"
            )
        return value

    expected = {
        "source_branch_id": solver,
        "solver_id": solver,
        "run_id": str(source.get("run_id", "")),
        "project_id": str(branch.get("recorded_project_id", "")),
        "manifest_sha256": source_sha("manifest"),
        "event_sha256": source_sha("state"),
        "particle_source_sha256": source_sha("particle_source"),
        "metadata_sha256": source_sha("metadata"),
    }
    parameters = _mapping(run_config.get("parameters"), f"{label} run parameters")
    propagated = _mapping(
        run_config.get("upstream_source_identity"),
        f"{label} upstream_source_identity",
    )
    _exact(propagated, SOURCE_IDENTITY_KEYS, f"{label} upstream_source_identity")
    if (
        parameters.get("source_branch_id") != solver
        or propagated.get("source_branch_id") != solver
        or propagated.get("solver_id") != solver
    ):
        raise DownstreamAnalysisError(f"{label} terminal source branch/solver differs")
    if dict(propagated) != expected:
        raise DownstreamAnalysisError(
            f"{label} propagated upstream source identity differs"
        )
    return expected


def _load_branch(
    raw: Any,
    base: Path,
    candidate_id: str,
    solver: str,
) -> BranchData:
    branch = _mapping(raw, f"{candidate_id}.{solver}")
    _exact(branch, BRANCH_KEYS, f"{candidate_id}.{solver}")
    refs = {
        name: _reference(branch[name], base, f"{candidate_id}.{solver}.{name}")
        for name in BRANCH_KEYS
    }
    paths = {name: value[0] for name, value in refs.items()}
    manifest = _load_json(paths["manifest"], f"{candidate_id}.{solver} manifest")
    if (
        manifest.get("schema_version") != 2
        or manifest.get("role") != "simulation_run_manifest"
        or manifest.get("status") != "success"
        or manifest.get("mode") != TERMINAL_MODE
    ):
        raise DownstreamAnalysisError(f"{candidate_id}.{solver} terminal manifest differs")
    run_record = manifest.get("run_config")
    if not isinstance(run_record, dict):
        raise DownstreamAnalysisError(f"{candidate_id}.{solver} run_config is missing")
    try:
        verify_record("run_config", run_record)
    except (AssertionError, KeyError, TypeError) as error:
        raise DownstreamAnalysisError(f"{candidate_id}.{solver} run_config: {error}") from error
    run_config = _load_json(Path(run_record["path"]), f"{candidate_id}.{solver} run_config")
    if any(run_config.get(key) != manifest.get(key) for key in ("run_id", "project", "mode")):
        raise DownstreamAnalysisError(f"{candidate_id}.{solver} run identity differs")
    for name in (
        "canonical_local_exit",
        "row_map",
        "runtime_binding",
        "resolved_connection",
    ):
        record = _record_for_path(manifest.get("inputs"), paths[name], f"{candidate_id}.{solver}.{name}")
        config_name = {"canonical_local_exit": "canonical", "row_map": "row_map"}.get(name, name)
        configured = _mapping(run_config.get("inputs"), "run_config.inputs").get(config_name)
        if not isinstance(configured, str) or Path(configured).resolve() != paths[name]:
            raise DownstreamAnalysisError(f"{candidate_id}.{solver} run_config path differs: {name}")
        if str(record.get("sha256", "")).upper() != refs[name][1]:
            raise DownstreamAnalysisError(f"{candidate_id}.{solver} manifest SHA differs: {name}")
    for name in ("downstream_particles", "metrics", "summary"):
        _record_for_path(manifest.get("outputs"), paths[name], f"{candidate_id}.{solver}.{name}")
    resolved = _load_json(paths["resolved_connection"], "resolved connection")
    runtime = _load_json(paths["runtime_binding"], "runtime binding")
    profile_id = resolved.get("selection", {}).get("connection_profile_id")
    if (
        resolved.get("role") != "resolved_connection_do_not_edit"
        or resolved.get("compatibility", {}).get("status") != "pass"
        or runtime.get("role") != "rf_multipole_oatof_runtime_binding"
        or runtime.get("integration_id") != INTEGRATION_ID
        or runtime.get("connection_profile_id") != profile_id
    ):
        raise DownstreamAnalysisError(f"{candidate_id}.{solver} binding identity differs")
    upstream_project_id = runtime.get("upstream_project_id")
    if (
        not isinstance(upstream_project_id, str)
        or not upstream_project_id
        or manifest.get("project") != upstream_project_id
        or run_config.get("project") != upstream_project_id
        or run_config.get("mode") != TERMINAL_MODE
    ):
        raise DownstreamAnalysisError(
            f"{candidate_id}.{solver} terminal mode/project differs"
        )
    expected_source = _source_identity(
        runtime, run_config, solver, f"{candidate_id}.{solver}"
    )
    frame_id = resolved["port_geometry"]["downstream"]["coordinate_frame"]["frame_id"]
    clock_id = resolved["port_geometry"]["downstream"]["clock"]["origin_id"]
    states = _load_states(paths["canonical_local_exit"], frame_id, clock_id, f"{candidate_id}.{solver}")
    downstream = _load_downstream(paths["row_map"], paths["downstream_particles"], states, f"{candidate_id}.{solver}")
    metrics = _load_json(paths["metrics"], f"{candidate_id}.{solver} metrics")
    summary = _load_json(paths["summary"], f"{candidate_id}.{solver} summary")
    if (
        metrics.get("role") != "rf_to_oatof_analyzer_transport_function_audit"
        or metrics.get("status") != "PASS"
        or summary.get("role") != "rf_to_oatof_analyzer_transport_summary"
        or summary.get("status") != "success"
        or summary.get("census") != metrics.get("census")
        or metrics.get("frame_id") != frame_id
        or metrics.get("clock_epoch_id") != clock_id
    ):
        raise DownstreamAnalysisError(f"{candidate_id}.{solver} summary/metrics differ")
    census = metrics["census"]
    hits = sum(item["hit"] for item in downstream.values())
    crossings = sum(item["crossing"] for item in downstream.values())
    if (
        census.get("local_accelerator_exit") != len(states)
        or census.get("detector_crossing") != crossings
        or census.get("detector_hit") != hits
    ):
        raise DownstreamAnalysisError(f"{candidate_id}.{solver} observed census differs")
    lineage = _validate_source_manifest(
        paths["source_manifest"],
        paths["source_state"],
        paths["source_input"],
        expected_source,
        f"{candidate_id}.{solver}",
    )
    return BranchData(
        summary,
        metrics,
        states,
        downstream,
        lineage,
        {
            "connection_profile_id": str(profile_id),
            "resolved_connection_sha256": refs["resolved_connection"][1],
            "runtime_binding_sha256": refs["runtime_binding"][1],
        },
    )


def _differences(values: Sequence[float]) -> dict[str, float]:
    if not values:
        raise DownstreamAnalysisError("paired local-exit intersection is empty")
    return {
        "mean_signed": math.fsum(values) / len(values),
        "rms": math.sqrt(math.fsum(value * value for value in values) / len(values)),
        "maximum_absolute": max(abs(value) for value in values),
    }


def _vector_differences(left: Sequence[tuple[float, ...]], right: Sequence[tuple[float, ...]]) -> dict[str, Any]:
    components = {
        axis: _differences([b[index] - a[index] for a, b in zip(left, right, strict=True)])
        for index, axis in enumerate("xyz")
    }
    distances = [math.dist(a, b) for a, b in zip(left, right, strict=True)]
    return {
        "components_simion_minus_comsol": components,
        "distance": {
            "mean": math.fsum(distances) / len(distances),
            "rms": math.sqrt(math.fsum(value * value for value in distances) / len(distances)),
            "maximum": max(distances),
        },
    }


def _detector_metrics(branch: BranchData) -> dict[str, Any]:
    hit_ids = sorted(particle_id for particle_id, row in branch.downstream.items() if row["hit"])
    if len(hit_ids) < 3:
        raise DownstreamAnalysisError("direct FWHM requires at least three detector hits")
    tof = np.asarray([branch.downstream[item]["instrument_time_us"] for item in hit_ids])
    mass = branch.states[hit_ids[0]]["mass_amu"]
    try:
        peak, _ = compute_peak_metrics(tof, mass)
        landing = compute_detector_metrics(
            np.asarray([branch.downstream[item]["x_mm"] - DEFAULT_DETECTOR_CENTER_X_MM for item in hit_ids]),
            np.asarray([branch.downstream[item]["y_mm"] - DEFAULT_DETECTOR_CENTER_Y_MM for item in hit_ids]),
        )
    except ValueError as error:
        raise DownstreamAnalysisError(f"detector metrics failed: {error}") from error
    radii = [branch.downstream[item]["radius_mm"] for item in hit_ids]
    if any(radius is None for radius in radii):
        raise DownstreamAnalysisError("detector hit radius is missing")
    return {
        "observation_plane": "detector_plane",
        "detector_hit_count": len(hit_ids),
        "detector_hit_fraction": len(hit_ids) / len(branch.states),
        "detector_hit_particle_ids": hit_ids,
        "mean_instrument_time_us": float(peak["mean_tof_us"]),
        "direct_fwhm_tof_ns": float(peak["direct_fwhm_tof_ns"]),
        "direct_fwhm_mass_Da": float(peak["direct_fwhm_mass_Da"]),
        "mass_resolution": float(peak["mass_resolution"]),
        "landing": {**landing, "reported_rms_radius_mm": math.sqrt(math.fsum(r * r for r in radii) / len(radii))},
        "velocity": {"status": "not_observed", "reason": "downstream detector artifact has no velocity"},
        "kinetic_energy": {"status": "not_observed", "reason": "downstream detector artifact has no energy"},
    }


def _paired(comsol: BranchData, simion: BranchData) -> dict[str, Any]:
    common = sorted(set(comsol.states) & set(simion.states))
    for particle_id in common:
        changed = [
            field
            for field in SEMANTIC_FIELDS
            if comsol.states[particle_id][field] != simion.states[particle_id][field]
        ]
        if changed:
            raise DownstreamAnalysisError(
                f"paired canonical species/lineage differs for particle {particle_id}: {', '.join(changed)}"
            )
    left = [comsol.states[item] for item in common]
    right = [simion.states[item] for item in common]
    return {
        "observation_plane": "local_accelerator_exit",
        "paired_particle_count": len(common),
        "paired_particle_ids": common,
        "position_mm": _vector_differences(
            [item["position"] for item in left], [item["position"] for item in right]
        ),
        "velocity_m_s": _vector_differences(
            [item["velocity"] for item in left], [item["velocity"] for item in right]
        ),
        "instrument_time_us": _differences(
            [b["instrument_time_us"] - a["instrument_time_us"] for a, b in zip(left, right, strict=True)]
        ),
        "kinetic_energy_eV": _differences(
            [b["kinetic_energy_eV"] - a["kinetic_energy_eV"] for a, b in zip(left, right, strict=True)]
        ),
        "detector_velocity": {"status": "not_observed"},
        "detector_kinetic_energy": {"status": "not_observed"},
    }


def _objective(candidate: Mapping[str, Any]) -> dict[str, float]:
    branch = candidate["branch_metrics"]
    paired = candidate["paired_diagnostics"]
    discrete = candidate["discrete_comparison"]
    return {
        "worst_detector_hit_fraction": min(branch[s]["detector_hit_fraction"] for s in SOLVERS),
        "worst_mass_resolution": min(branch[s]["mass_resolution"] for s in SOLVERS),
        "worst_direct_fwhm_tof_ns": max(branch[s]["direct_fwhm_tof_ns"] for s in SOLVERS),
        "worst_landing_rms_radius_mm": max(branch[s]["landing"]["reported_rms_radius_mm"] for s in SOLVERS),
        "detector_hit_symmetric_difference_count": float(discrete["detector_hit_symmetric_difference_count"]),
        "local_exit_particle_symmetric_difference_count": float(discrete["local_exit_particle_symmetric_difference_count"]),
        "paired_position_rms_distance_mm": paired["position_mm"]["distance"]["rms"],
        "paired_velocity_rms_distance_m_s": paired["velocity_m_s"]["distance"]["rms"],
        "paired_time_rms_difference_us": paired["instrument_time_us"]["rms"],
        "paired_energy_rms_difference_eV": paired["kinetic_energy_eV"]["rms"],
    }


def _dominates(left: Mapping[str, float], right: Mapping[str, float]) -> bool:
    comparisons = [
        left[name] >= right[name] if direction == "maximize" else left[name] <= right[name]
        for name, direction in OBJECTIVE_DIRECTIONS.items()
    ]
    strict = [
        left[name] > right[name] if direction == "maximize" else left[name] < right[name]
        for name, direction in OBJECTIVE_DIRECTIONS.items()
    ]
    return all(comparisons) and any(strict)


def label_pareto_candidates(vectors: Mapping[str, Mapping[str, float]]) -> dict[str, dict[str, Any]]:
    """Label strict nondominance without weights, scores, or thresholds."""
    if not vectors:
        raise DownstreamAnalysisError("Pareto analysis requires candidates")
    normalized: dict[str, dict[str, float]] = {}
    for candidate_id, raw in vectors.items():
        if not candidate_id or set(raw) != set(OBJECTIVE_DIRECTIONS):
            raise DownstreamAnalysisError(f"Pareto objective fields differ for {candidate_id}")
        normalized[candidate_id] = {name: _finite(raw[name], f"{candidate_id}.{name}") for name in OBJECTIVE_DIRECTIONS}
    return {
        candidate_id: {
            "pareto_label": "DOMINATED" if dominators else "NONDOMINATED",
            "dominated_by_candidate_ids": dominators,
            "objectives": normalized[candidate_id],
        }
        for candidate_id in sorted(normalized)
        for dominators in [[
            other_id
            for other_id in sorted(normalized)
            if other_id != candidate_id and _dominates(normalized[other_id], normalized[candidate_id])
        ]]
    }


def analyze_request(request: Mapping[str, Any], request_base: Path) -> dict[str, Any]:
    """Analyze explicit paired branches and return diagnostic-only Pareto labels."""
    _exact(request, {"schema_version", "role", "integration_id", "candidates"}, "request")
    if request.get("schema_version") != 1 or request.get("role") != REQUEST_ROLE or request.get("integration_id") != INTEGRATION_ID:
        raise DownstreamAnalysisError("request identity differs")
    candidates = request["candidates"]
    if not isinstance(candidates, list) or not candidates:
        raise DownstreamAnalysisError("request candidates must be nonempty")
    results = []
    seen: set[str] = set()
    for raw in candidates:
        candidate = _mapping(raw, "candidate")
        _exact(candidate, {"candidate_id", "comsol", "simion"}, "candidate")
        candidate_id = candidate["candidate_id"]
        if not isinstance(candidate_id, str) or not candidate_id or candidate_id in seen:
            raise DownstreamAnalysisError("candidate_id must be nonempty and unique")
        seen.add(candidate_id)
        branches = {solver: _load_branch(candidate[solver], request_base, candidate_id, solver) for solver in SOLVERS}
        left, right = branches["comsol"], branches["simion"]
        if left.source_lineage["source_input_sha256"] != right.source_lineage["source_input_sha256"]:
            raise DownstreamAnalysisError(f"{candidate_id} shared mother source differs")
        if left.binding_identity != right.binding_identity:
            raise DownstreamAnalysisError(f"{candidate_id} resolved/runtime binding differs")
        local_left, local_right = set(left.states), set(right.states)
        hit_left = {item for item, row in left.downstream.items() if row["hit"]}
        hit_right = {item for item, row in right.downstream.items() if row["hit"]}
        result = {
            "candidate_id": candidate_id,
            "connection_profile_id": left.binding_identity["connection_profile_id"],
            "source_lineage": {solver: branch.source_lineage for solver, branch in branches.items()},
            "binding_identity": left.binding_identity,
            "discrete_comparison": {
                "local_exit_particle_sets_exact": local_left == local_right,
                "local_exit_particle_symmetric_difference_count": len(local_left ^ local_right),
                "comsol_only_local_exit_particle_ids": sorted(local_left - local_right),
                "simion_only_local_exit_particle_ids": sorted(local_right - local_left),
                "detector_hit_sets_exact": hit_left == hit_right,
                "detector_hit_symmetric_difference_count": len(hit_left ^ hit_right),
                "comsol_only_detector_hit_particle_ids": sorted(hit_left - hit_right),
                "simion_only_detector_hit_particle_ids": sorted(hit_right - hit_left),
                "census": {solver: branch.metrics["census"] for solver, branch in branches.items()},
            },
            "paired_diagnostics": _paired(left, right),
            "branch_metrics": {solver: _detector_metrics(branch) for solver, branch in branches.items()},
        }
        result["pareto_objectives"] = _objective(result)
        results.append(result)
    pareto = label_pareto_candidates({item["candidate_id"]: item["pareto_objectives"] for item in results})
    for item in results:
        item["pareto"] = pareto[item["candidate_id"]]
    return {
        "schema_version": 1,
        "role": RESULT_ROLE,
        "status": "INCONCLUSIVE_DIAGNOSTIC_ONLY",
        "integration_id": INTEGRATION_ID,
        "acceptance_thresholds_applied": False,
        "qualification_decision_made": False,
        "scalar_objective_used": False,
        "objective_directions": OBJECTIVE_DIRECTIONS,
        "candidates": sorted(results, key=lambda item: item["candidate_id"]),
        "pareto_front_candidate_ids": sorted(item for item, label in pareto.items() if label["pareto_label"] == "NONDOMINATED"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    request_path = args.request.resolve()
    result = analyze_request(_load_json(request_path, "request"), request_path.parent)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"RF_OATOF_PAIRED_DOWNSTREAM_ANALYSIS=INCONCLUSIVE_DIAGNOSTIC_ONLY CANDIDATES={len(result['candidates'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
