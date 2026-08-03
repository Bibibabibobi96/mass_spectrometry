"""Publish real three-mode solver handoff states and their dispersion binding."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.component_particle_state import (
    write_component_particle_state_csv,
)
from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import validate_schema
from common.contracts.particle_physics import kinetic_energy_ev, mass_to_charge_th
from common.contracts.particle_state import PARTICLE_STATE_COLUMNS
from common.multipole.numerical_observables import (
    load_json,
    manifest_record,
    primary_state_filename,
    solver_name,
)
from common.multipole.three_mode_dispersion import MODE_IDS


SOURCE_COLUMNS = [
    "particle_id",
    "birth_time_s",
    "x_mm",
    "y_mm",
    "z_mm",
    "vx_m_s",
    "vy_m_s",
    "vz_m_s",
    "mass_amu",
    "charge_state",
]
HANDOFF_CONTRACT_KEYS = {
    "schema_version",
    "role",
    "selector",
    "geometry",
    "population",
    "canonical_state",
}


def _reference(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": file_sha256(path)}


def _repo_path(repo_root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (repo_root / path).resolve()


def _preregistered_reference(
    repo_root: Path,
    reference: dict[str, str],
) -> dict[str, str]:
    path = _repo_path(repo_root, reference["path"])
    if not path.is_file() or file_sha256(path) != reference["sha256"]:
        raise ValueError(f"preregistered file identity differs: {path}")
    return _reference(path)


def _verified_run_input(
    manifest: dict[str, Any],
    role: str,
) -> Path:
    record = manifest["inputs"][role]
    path = Path(record["path"])
    if not path.is_file() or file_sha256(path) != record["sha256"]:
        raise ValueError(f"run input identity differs: {role}")
    return path


def _verified_run_config(manifest: dict[str, Any]) -> dict[str, Any]:
    record = manifest["run_config"]
    path = Path(record["path"])
    if not path.is_file() or file_sha256(path) != record["sha256"]:
        raise ValueError("run config identity differs")
    return load_json(path)


def _verified_run_output(
    manifest: dict[str, Any],
    filename: str,
) -> Path:
    path = manifest_record(manifest, filename)
    records = [
        record
        for record in manifest["outputs"]
        if Path(record["path"]).name == filename
    ]
    if file_sha256(path) != records[0]["sha256"]:
        raise ValueError(f"run output identity differs: {filename}")
    return path


def _require_exact_keys(
    value: Any,
    expected: set[str],
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        actual = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise ValueError(f"{label} fields differ: {actual}")
    return value


def _finite_number(
    value: Any,
    label: str,
    *,
    positive: bool = False,
    nonnegative: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    number = float(value)
    if (
        not math.isfinite(number)
        or (positive and number <= 0)
        or (nonnegative and number < 0)
    ):
        raise ValueError(f"{label} has an invalid numeric value")
    return number


def _source_rows(
    path: Path,
    *,
    expected_count: int,
    particle_id_policy: str,
) -> dict[int, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != SOURCE_COLUMNS:
            raise ValueError("particle source columns differ")
        raw_rows = list(reader)
    if len(raw_rows) != expected_count:
        raise ValueError("particle source count differs from handoff contract")
    rows: dict[int, dict[str, str]] = {}
    for row in raw_rows:
        raw_particle_id = row["particle_id"].strip()
        particle_id = int(raw_particle_id)
        if str(particle_id) != raw_particle_id:
            raise ValueError("particle source ID must be a canonical integer")
        if particle_id in rows:
            raise ValueError("particle source contains duplicate particle_id")
        rows[particle_id] = row
    if (
        particle_id_policy != "contiguous_one_based"
        or sorted(rows) != list(range(1, expected_count + 1))
    ):
        raise ValueError("particle source IDs must be contiguous and one-based")
    return rows


def _validate_handoff_contract(contract: Any) -> dict[str, Any]:
    value = _require_exact_keys(contract, HANDOFF_CONTRACT_KEYS, "handoff contract")
    if (
        value["schema_version"] != 1
        or value["role"] != "multipole_handoff_publication_contract"
    ):
        raise ValueError("handoff contract identity differs")
    selector = _require_exact_keys(
        value["selector"], {"event", "status"}, "handoff selector"
    )
    if (
        not isinstance(selector["event"], str)
        or not selector["event"]
        or not isinstance(selector["status"], str)
        or not selector["status"]
    ):
        raise ValueError("handoff selector values must be nonempty")
    geometry = _require_exact_keys(
        value["geometry"],
        {
            "axial_plane_mm",
            "absolute_tolerance_mm",
            "require_positive_axial_velocity",
        },
        "handoff geometry",
    )
    geometry["axial_plane_mm"] = _finite_number(
        geometry["axial_plane_mm"], "handoff axial plane"
    )
    geometry["absolute_tolerance_mm"] = _finite_number(
        geometry["absolute_tolerance_mm"],
        "handoff plane tolerance",
        positive=True,
    )
    if geometry["require_positive_axial_velocity"] is not True:
        raise ValueError("handoff contract must require positive axial velocity")
    population = _require_exact_keys(
        value["population"],
        {
            "expected_source_particle_count",
            "source_particle_id_policy",
            "handoff_particle_id_policy",
        },
        "handoff population",
    )
    count = population["expected_source_particle_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise ValueError("expected source particle count must be a positive integer")
    if (
        population["source_particle_id_policy"] != "contiguous_one_based"
        or population["handoff_particle_id_policy"]
        != "unique_subset_of_source"
    ):
        raise ValueError("handoff particle identity policy differs")
    canonical = _require_exact_keys(
        value["canonical_state"],
        {
            "state_event",
            "frame_id",
            "clock_epoch_id",
            "source_component_id",
            "target_component_id",
            "lineage_policy",
            "species_policy",
            "particle_weight",
            "phase_reference_id",
            "clock_tolerance_us",
        },
        "canonical handoff state",
    )
    for name in (
        "state_event",
        "frame_id",
        "clock_epoch_id",
        "source_component_id",
        "target_component_id",
        "phase_reference_id",
    ):
        if not isinstance(canonical[name], str) or not canonical[name]:
            raise ValueError(f"canonical handoff {name} must be nonempty")
    if (
        canonical["lineage_policy"]
        != "root_birth_time_plus_component_elapsed_time"
        or canonical["species_policy"]
        != "frozen_particle_source_mass_and_charge"
    ):
        raise ValueError("canonical handoff lineage or species policy differs")
    canonical["particle_weight"] = _finite_number(
        canonical["particle_weight"], "canonical particle weight", positive=True
    )
    canonical["clock_tolerance_us"] = _finite_number(
        canonical["clock_tolerance_us"],
        "canonical clock tolerance",
        positive=True,
    )
    return value


def _three_mode_handoff_contract(
    project_id: str,
    resolved: dict[str, Any],
    source_path: Path,
) -> dict[str, Any]:
    with source_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != SOURCE_COLUMNS:
            raise ValueError("particle source columns differ")
        source_count = sum(1 for _ in reader)
    return {
        "schema_version": 1,
        "role": "multipole_handoff_publication_contract",
        "selector": {"event": "handoff", "status": "transmitted"},
        "geometry": {
            "axial_plane_mm": resolved["interfaces_mm"]["exit"][
                "handoff_plane_z_mm"
            ],
            "absolute_tolerance_mm": 1e-9,
            "require_positive_axial_velocity": True,
        },
        "population": {
            "expected_source_particle_count": source_count,
            "source_particle_id_policy": "contiguous_one_based",
            "handoff_particle_id_policy": "unique_subset_of_source",
        },
        "canonical_state": {
            "state_event": "canonical_handoff",
            "frame_id": "multipole_exit_frame",
            "clock_epoch_id": "instrument_trigger",
            "source_component_id": project_id,
            "target_component_id": "downstream_interface",
            "lineage_policy": "root_birth_time_plus_component_elapsed_time",
            "species_policy": "frozen_particle_source_mass_and_charge",
            "particle_weight": 1,
            "phase_reference_id": "multipole_rf_drive",
            "clock_tolerance_us": 1e-9,
        },
    }


def _normalized_geometry(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 12)
    if isinstance(value, list):
        return [_normalized_geometry(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _normalized_geometry(item)
            for key, item in value.items()
        }
    return value


def _mechanical_signature(resolved: dict[str, Any]) -> dict[str, Any]:
    axial = resolved["segmentation"]["axial_acceleration"]["derived"]
    return _normalized_geometry(
        {
            "geometry_mm": resolved["geometry_mm"],
            "interfaces_mm": resolved["interfaces_mm"],
            "segments": [
                {
                    "segment_index": index,
                    "z_min_mm": segment["z_min_mm"],
                    "z_max_mm": segment["z_max_mm"],
                }
                for index, segment in enumerate(axial["segments"], start=1)
            ],
        }
    )


def _content_sha256(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def _verified_mode_runs(
    manifest_paths: list[Path],
    *,
    project_id: str,
) -> tuple[
    list[dict[str, Any]],
    str,
    list[dict[str, Any]],
    list[dict[str, Any]],
    set[str],
    set[str],
]:
    if len(manifest_paths) != len(MODE_IDS):
        raise ValueError("exactly three ordered mode manifests are required")
    manifests = [load_json(path) for path in manifest_paths]
    if any(
        manifest.get("status") != "success"
        or manifest.get("project") != project_id
        for manifest in manifests
    ):
        raise ValueError("mode manifests must be successful runs from one project")
    solvers = [solver_name(manifest) for manifest in manifests]
    if len(set(solvers)) != 1:
        raise ValueError("three-mode binding requires one solver")
    run_configs = [_verified_run_config(manifest) for manifest in manifests]
    if [
        config["parameters"]["operating_mode_id"] for config in run_configs
    ] != list(MODE_IDS):
        raise ValueError("ordered run operating modes differ from the public method")
    for manifest in manifests:
        _verified_run_input(manifest, "solver_numerics")
        _verified_run_input(manifest, "particle_source")
    resolved_designs = [
        load_json(_verified_run_input(manifest, "multipole_resolved_design"))
        for manifest in manifests
    ]
    mechanical_signatures = [
        _mechanical_signature(resolved) for resolved in resolved_designs
    ]
    if any(
        signature != mechanical_signatures[0]
        for signature in mechanical_signatures[1:]
    ):
        raise ValueError("three modes do not share one mechanical geometry")
    numerics_sha = {
        manifest["inputs"]["solver_numerics"]["sha256"] for manifest in manifests
    }
    particle_sha = {
        manifest["inputs"]["particle_source"]["sha256"] for manifest in manifests
    }
    if len(numerics_sha) != 1 or len(particle_sha) != 1:
        raise ValueError("three modes must share solver numerics and particle source")
    return (
        manifests,
        solvers[0].lower(),
        resolved_designs,
        mechanical_signatures,
        numerics_sha,
        particle_sha,
    )


def publish_handoff(
    state_path: Path,
    source_path: Path,
    output_path: Path,
    *,
    contract: dict[str, Any],
) -> dict[str, Any]:
    governed = _validate_handoff_contract(contract)
    population = governed["population"]
    canonical = governed["canonical_state"]
    geometry = governed["geometry"]
    selector = governed["selector"]
    sources = _source_rows(
        source_path,
        expected_count=population["expected_source_particle_count"],
        particle_id_policy=population["source_particle_id_policy"],
    )
    with state_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != PARTICLE_STATE_COLUMNS:
            raise ValueError("solver state must use the exact 17-column schema")
        states = [
            row
            for row in reader
            if row["event"] == selector["event"]
            and row["status"] == selector["status"]
        ]
    if not states:
        raise ValueError("solver state has no selected handoff rows")
    raw_state_ids = [row["particle_id"].strip() for row in states]
    state_ids = [int(value) for value in raw_state_ids]
    if any(str(value) != raw for value, raw in zip(state_ids, raw_state_ids)):
        raise ValueError("solver handoff ID must be a canonical integer")
    if len(state_ids) != len(set(state_ids)):
        raise ValueError("solver state duplicates a selected handoff particle")
    if not set(state_ids).issubset(sources):
        raise ValueError("solver handoff contains an unknown source particle")
    output_rows: list[dict[str, Any]] = []
    for state in states:
        particle_id = int(state["particle_id"])
        source = sources[particle_id]
        mass_amu = _finite_number(
            float(source["mass_amu"]),
            f"source particle {particle_id} mass_amu",
            positive=True,
        )
        charge_state = int(source["charge_state"])
        if charge_state == 0:
            raise ValueError("source particle charge_state must be nonzero")
        axial_z = _finite_number(
            float(state["axial_z_mm"]),
            f"handoff particle {particle_id} axial_z_mm",
        )
        if (
            abs(axial_z - geometry["axial_plane_mm"])
            > geometry["absolute_tolerance_mm"]
        ):
            raise ValueError("selected handoff row differs from expected axial plane")
        velocity = (
            _finite_number(
                float(state["velocity_x_m_s"]),
                f"handoff particle {particle_id} velocity_x_m_s",
            ),
            _finite_number(
                float(state["velocity_y_m_s"]),
                f"handoff particle {particle_id} velocity_y_m_s",
            ),
            _finite_number(
                float(state["velocity_axial_m_s"]),
                f"handoff particle {particle_id} velocity_axial_m_s",
            ),
        )
        if velocity[2] <= 0:
            raise ValueError("selected handoff row is not a positive forward crossing")
        instrument_time = _finite_number(
            float(state["time_us"]),
            f"handoff particle {particle_id} time_us",
        )
        elapsed_time = _finite_number(
            float(state["elapsed_time_us"]),
            f"handoff particle {particle_id} elapsed_time_us",
            nonnegative=True,
        )
        birth_time = _finite_number(
            float(source["birth_time_s"]) * 1e6,
            f"source particle {particle_id} birth_time_us",
        )
        if (
            abs(instrument_time - birth_time - elapsed_time)
            > canonical["clock_tolerance_us"]
        ):
            raise ValueError("selected handoff row differs from source lineage clock")
        phase = _finite_number(
            float(state["rf_phase_rad"]),
            f"handoff particle {particle_id} rf_phase_rad",
        )
        transverse_x = _finite_number(
            float(state["transverse_x_mm"]),
            f"handoff particle {particle_id} transverse_x_mm",
        )
        transverse_y = _finite_number(
            float(state["transverse_y_mm"]),
            f"handoff particle {particle_id} transverse_y_mm",
        )
        output_rows.append(
            {
                "particle_id": particle_id,
                "parent_particle_id": "",
                "generation": 0,
                "species_id": f"ion_{mass_amu:g}amu_z{charge_state}",
                "particle_weight": canonical["particle_weight"],
                "source_component_id": canonical["source_component_id"],
                "target_component_id": canonical["target_component_id"],
                "state_event": canonical["state_event"],
                "frame_id": canonical["frame_id"],
                "clock_epoch_id": canonical["clock_epoch_id"],
                "instrument_time_us": instrument_time,
                "lineage_age_us": elapsed_time,
                "particle_age_us": elapsed_time,
                "last_component_elapsed_time_us": elapsed_time,
                "lineage_birth_time_us": birth_time,
                "particle_birth_time_us": birth_time,
                "mass_to_charge_Th": mass_to_charge_th(mass_amu, charge_state),
                "mass_amu": mass_amu,
                "charge_state": charge_state,
                "position_x_mm": transverse_x,
                "position_y_mm": transverse_y,
                "position_z_mm": axial_z,
                "velocity_x_m_s": velocity[0],
                "velocity_y_m_s": velocity[1],
                "velocity_z_m_s": velocity[2],
                "kinetic_energy_eV": kinetic_energy_ev(mass_amu, *velocity),
                "phase_reference_id": canonical["phase_reference_id"],
                "phase_rad": phase,
            }
        )
    return write_component_particle_state_csv(output_path, output_rows)


def publish_binding(
    repo_root: Path,
    preregistration_path: Path,
    manifest_paths: list[Path],
    output_dir: Path,
) -> dict[str, Any]:
    preregistration = load_json(preregistration_path)
    bootstrap = preregistration.get("bootstrap")
    if not (
        isinstance(bootstrap, dict)
        and isinstance(bootstrap.get("seed"), int)
        and isinstance(bootstrap.get("resamples"), int)
        and bootstrap["resamples"] > 0
    ):
        raise ValueError(
            "preregistration must freeze bootstrap seed and positive resample count"
        )
    project_id = preregistration["project_id"]
    if preregistration.get("preregistered_before_run") is not True:
        raise ValueError("analysis plan was not preregistered before the runs")
    if [mode["mode_id"] for mode in preregistration["modes"]] != list(MODE_IDS):
        raise ValueError("preregistered modes differ from the public method")
    (
        manifests,
        solver_id,
        resolved_designs,
        mechanical_signatures,
        numerics_sha,
        particle_sha,
    ) = _verified_mode_runs(manifest_paths, project_id=project_id)
    source_references = {
        count: _preregistered_reference(repo_root, reference)
        for count, reference in preregistration["source_family"].items()
        if count in {"n100", "n1000"}
    }
    selected_counts = [
        count for count, reference in source_references.items()
        if particle_sha == {reference["sha256"]}
    ]
    if len(selected_counts) != 1:
        raise ValueError("run particle source differs from preregistration")
    source_count_id = selected_counts[0]
    analysis_particle_count = {"n100": 100, "n1000": 1000}[source_count_id]
    expected_particle_sha = source_references[source_count_id]["sha256"]
    output_dir.mkdir(parents=True, exist_ok=True)
    handoff_references: list[dict[str, str]] = []
    for mode_id, manifest, resolved in zip(
        MODE_IDS, manifests, resolved_designs, strict=True
    ):
        state_path = _verified_run_output(
            manifest, primary_state_filename(manifest, solver_id.upper())
        )
        source_path = _verified_run_input(manifest, "particle_source")
        output_path = output_dir / f"{mode_id}__handoff.csv"
        publish_handoff(
            state_path,
            source_path,
            output_path,
            contract=_three_mode_handoff_contract(
                project_id,
                resolved,
                source_path,
            ),
        )
        handoff_references.append(_reference(output_path))
    geometry_reference = _preregistered_reference(
        repo_root, preregistration["geometry"]
    )
    geometry_path = Path(geometry_reference["path"])
    geometry = load_json(geometry_path)["mechanical_baseline"]
    resolved_geometry = resolved_designs[0]["geometry_mm"]
    resolved_interfaces = resolved_designs[0]["interfaces_mm"]
    resolved_mechanical_baseline = _normalized_geometry(
        {
            "inscribed_radius_r0_mm": resolved_geometry["inscribed_radius_r0"],
            "rod_radius_ratio": resolved_geometry["rod_radius_ratio"],
            "rod_z_min_mm": resolved_geometry["rod_z_min"],
            "rod_z_max_mm": resolved_geometry["rod_z_max"],
            "rod_segments": mechanical_signatures[0]["segments"],
            "release_plane_z_mm": resolved_interfaces["entrance"][
                "release_plane_z_mm"
            ],
            "entrance_aperture_plate_faces_z_mm": [
                resolved_interfaces["entrance"][
                    "aperture_plate_upstream_face_z_mm"
                ],
                resolved_interfaces["entrance"][
                    "aperture_plate_downstream_face_z_mm"
                ],
            ],
            "exit_aperture_plate_faces_z_mm": [
                resolved_interfaces["exit"]["aperture_plate_upstream_face_z_mm"],
                resolved_interfaces["exit"]["aperture_plate_downstream_face_z_mm"],
            ],
            "handoff_plane_z_mm": resolved_interfaces["exit"]["handoff_plane_z_mm"],
            "near_interface_census_plane_z_mm": resolved_interfaces["exit"][
                "census_plane_z_mm"
            ],
        }
    )
    expected_mechanical_baseline = {
        key: _normalized_geometry(geometry[key])
        for key in resolved_mechanical_baseline
    }
    if resolved_mechanical_baseline != expected_mechanical_baseline:
        raise ValueError("run geometry differs from the preregistered mechanical baseline")
    invariant_sha = preregistration["geometry"]["sha256"]
    modes = []
    for mode_id, mode_preregistration, handoff in zip(
        MODE_IDS, preregistration["modes"], handoff_references, strict=True
    ):
        voltage_reference = _preregistered_reference(
            repo_root, mode_preregistration["voltage_contract"]
        )
        modes.append(
            {
                "mode_id": mode_id,
                "geometry_invariant_sha256": invariant_sha,
                "particle_source_sha256": expected_particle_sha,
                "solver_numerics_sha256": next(iter(numerics_sha)),
                "voltage_contract": voltage_reference,
                "handoff_state": handoff,
            }
        )
    binding = {
        "schema_version": 1,
        "role": "multipole_three_mode_dispersion_binding",
        "project_id": project_id,
        "solver_id": solver_id,
        "solver_numerics_sha256": next(iter(numerics_sha)),
        "analysis_plan_preregistered_before_run": True,
        "published_after_real_runs": True,
        "analysis_particle_count": analysis_particle_count,
        "retention_class": "compact",
        "frame_id": "multipole_exit_frame",
        "clock_epoch_id": "instrument_trigger",
        "handoff_state_event": "canonical_handoff",
        "geometry": {
            "geometry_invariant_sha256": invariant_sha,
            "rod_z_min_mm": geometry["rod_z_min_mm"],
            "rod_z_max_mm": geometry["rod_z_max_mm"],
            "handoff_plane_z_mm": geometry["handoff_plane_z_mm"],
            "near_interface_plane_z_mm": geometry[
                "near_interface_census_plane_z_mm"
            ],
        },
        "source_family": source_references,
        "modes": modes,
        "qualification_bindings": {
            name: _preregistered_reference(repo_root, reference)
            for name, reference in preregistration[
                "qualification_bindings"
            ].items()
        },
        "bootstrap": bootstrap,
    }
    validate_schema(binding, "three_mode_dispersion_binding.schema.json")
    binding_path = output_dir / "binding.json"
    binding_path.write_text(json.dumps(binding, indent=2) + "\n", encoding="utf-8")
    return binding


def publish_posthoc_binding(
    repo_root: Path,
    project_id: str,
    manifest_paths: list[Path],
    output_dir: Path,
) -> dict[str, Any]:
    """Publish a descriptive-only binding without creating formal evidence."""
    (
        manifests,
        solver_id,
        resolved_designs,
        mechanical_signatures,
        numerics_sha,
        particle_sha,
    ) = _verified_mode_runs(manifest_paths, project_id=project_id)
    source_paths = {
        "n100": (
            repo_root
            / "common/multipole/sources/rf_multipole_family_mother_sample_v1_100.csv"
        ).resolve(),
        "n1000": (
            repo_root
            / "common/multipole/sources/rf_multipole_family_mother_sample_v1_1000.csv"
        ).resolve(),
    }
    source_references = {
        name: _reference(path) for name, path in source_paths.items()
    }
    selected_counts = [
        name
        for name, reference in source_references.items()
        if particle_sha == {reference["sha256"]}
    ]
    if len(selected_counts) != 1:
        raise ValueError("run particle source differs from the public family source")
    selected_count = selected_counts[0]
    analysis_particle_count = {"n100": 100, "n1000": 1000}[selected_count]
    resolved = resolved_designs[0]
    geometry = resolved["geometry_mm"]
    interfaces = resolved["interfaces_mm"]
    invariant_sha = _content_sha256(mechanical_signatures[0])
    output_dir.mkdir(parents=True, exist_ok=True)
    modes = []
    for mode_id, manifest, manifest_path, mode_resolved in zip(
        MODE_IDS,
        manifests,
        manifest_paths,
        resolved_designs,
        strict=True,
    ):
        state_path = _verified_run_output(
            manifest, primary_state_filename(manifest, solver_id.upper())
        )
        source_path = _verified_run_input(manifest, "particle_source")
        handoff_path = output_dir / f"{mode_id}__handoff.csv"
        publish_handoff(
            state_path,
            source_path,
            handoff_path,
            contract=_three_mode_handoff_contract(
                project_id,
                mode_resolved,
                source_path,
            ),
        )
        modes.append(
            {
                "mode_id": mode_id,
                "geometry_invariant_sha256": invariant_sha,
                "particle_source_sha256": source_references[selected_count]["sha256"],
                "solver_numerics_sha256": next(iter(numerics_sha)),
                "source_run_manifest": _reference(manifest_path),
                "handoff_state": _reference(handoff_path),
            }
        )
    binding = {
        "schema_version": 1,
        "role": "multipole_three_mode_dispersion_posthoc_binding",
        "analysis_class": "POSTHOC_DESCRIPTIVE",
        "project_id": project_id,
        "solver_id": solver_id,
        "solver_numerics_sha256": next(iter(numerics_sha)),
        "analysis_plan_preregistered_before_run": False,
        "recorded_after_runs": True,
        "analysis_particle_count": analysis_particle_count,
        "retention_class": "compact",
        "frame_id": "multipole_exit_frame",
        "clock_epoch_id": "instrument_trigger",
        "handoff_state_event": "canonical_handoff",
        "geometry": {
            "geometry_invariant_sha256": invariant_sha,
            "rod_z_min_mm": geometry["rod_z_min"],
            "rod_z_max_mm": geometry["rod_z_max"],
            "handoff_plane_z_mm": interfaces["exit"]["handoff_plane_z_mm"],
            "near_interface_plane_z_mm": interfaces["exit"]["census_plane_z_mm"],
        },
        "source_family": source_references,
        "modes": modes,
        "claim_limit": (
            "POSTHOC_DESCRIPTIVE reports point diagnostics from selected existing "
            "runs only. It computes no uncertainty interval, acceptance decision, "
            "numerical-equivalence decision, optimization claim, or Candidate/Formal "
            "qualification."
        ),
    }
    validate_schema(
        binding, "three_mode_dispersion_posthoc_binding.schema.json"
    )
    (output_dir / "binding.json").write_text(
        json.dumps(binding, indent=2) + "\n", encoding="utf-8"
    )
    return binding


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument(
        "--analysis-class",
        choices=("formal", "posthoc", "handoff"),
        default="formal",
    )
    parser.add_argument("--preregistration", type=Path)
    parser.add_argument("--project-id")
    parser.add_argument("--no-acceleration-manifest", type=Path)
    parser.add_argument("--segmented-manifest", type=Path)
    parser.add_argument("--exit-plate-manifest", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--handoff-contract", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    handoff_arguments = (
        args.handoff_contract,
        args.state,
        args.source,
        args.output,
    )
    three_mode_arguments = (
        args.repo_root,
        args.no_acceleration_manifest,
        args.segmented_manifest,
        args.exit_plate_manifest,
        args.output_dir,
    )
    if args.analysis_class == "handoff":
        if any(value is None for value in handoff_arguments):
            parser.error(
                "--handoff-contract, --state, --source and --output are "
                "required for handoff analysis"
            )
        if any(value is not None for value in three_mode_arguments) or (
            args.preregistration is not None or args.project_id is not None
        ):
            parser.error(
                "handoff analysis accepts only its contract, state, source "
                "and output paths"
            )
        report = publish_handoff(
            args.state.resolve(),
            args.source.resolve(),
            args.output.resolve(),
            contract=load_json(args.handoff_contract.resolve()),
        )
        print(
            "MULTIPOLE_HANDOFF_PUBLICATION=PASS "
            f"PARTICLES={report['particles']}"
        )
        return 0
    if any(value is None for value in three_mode_arguments):
        parser.error(
            "--repo-root, all three manifest paths and --output-dir are "
            "required for three-mode analysis"
        )
    if any(value is not None for value in handoff_arguments):
        parser.error("three-mode analysis does not accept handoff-only paths")
    manifest_paths = [
        args.no_acceleration_manifest.resolve(),
        args.segmented_manifest.resolve(),
        args.exit_plate_manifest.resolve(),
    ]
    if args.analysis_class == "formal":
        if args.preregistration is None:
            parser.error("--preregistration is required for formal analysis")
        binding = publish_binding(
            args.repo_root.resolve(),
            args.preregistration.resolve(),
            manifest_paths,
            args.output_dir.resolve(),
        )
    else:
        if not args.project_id:
            parser.error("--project-id is required for posthoc analysis")
        binding = publish_posthoc_binding(
            args.repo_root.resolve(),
            args.project_id,
            manifest_paths,
            args.output_dir.resolve(),
        )
    print(
        "MULTIPOLE_THREE_MODE_BINDING=PASS "
        f"PROJECT={binding['project_id']} SOLVER={binding['solver_id']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
