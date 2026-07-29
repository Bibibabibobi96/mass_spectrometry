"""Publish real three-mode solver handoff states and their dispersion binding."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from common.contracts.component_particle_state import (
    write_component_particle_state_csv,
)
from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import validate_schema
from common.contracts.particle_physics import kinetic_energy_ev, mass_to_charge_th
from common.multipole.numerical_qualification import (
    load_json,
    manifest_record,
    primary_state_filename,
    solver_name,
)
from common.multipole.three_mode_dispersion import MODE_IDS


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


def _source_rows(path: Path) -> dict[int, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = {int(row["particle_id"]): row for row in csv.DictReader(handle)}
    if sorted(rows) != list(range(1, len(rows) + 1)):
        raise ValueError("particle source IDs must be contiguous and one-based")
    return rows


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


def publish_handoff(
    state_path: Path,
    source_path: Path,
    output_path: Path,
    *,
    project_id: str,
) -> None:
    sources = _source_rows(source_path)
    with state_path.open(encoding="utf-8-sig", newline="") as handle:
        states = [
            row
            for row in csv.DictReader(handle)
            if row["event"] == "handoff" and row["status"] == "transmitted"
        ]
    if not states:
        raise ValueError("solver state has no transmitted handoff rows")
    state_ids = [int(row["particle_id"]) for row in states]
    if len(state_ids) != len(set(state_ids)):
        raise ValueError("solver state duplicates a transmitted handoff particle")
    if not set(state_ids).issubset(sources):
        raise ValueError("solver handoff contains an unknown source particle")
    output_rows: list[dict[str, Any]] = []
    for state in states:
        particle_id = int(state["particle_id"])
        source = sources[particle_id]
        mass_amu = float(source["mass_amu"])
        charge_state = int(source["charge_state"])
        velocity = (
            float(state["velocity_x_m_s"]),
            float(state["velocity_y_m_s"]),
            float(state["velocity_axial_m_s"]),
        )
        instrument_time = float(state["time_us"])
        elapsed_time = float(state["elapsed_time_us"])
        birth_time = instrument_time - elapsed_time
        output_rows.append(
            {
                "particle_id": particle_id,
                "parent_particle_id": "",
                "generation": 0,
                "species_id": f"ion_{mass_amu:g}amu_z{charge_state}",
                "particle_weight": 1,
                "source_component_id": project_id,
                "target_component_id": "downstream_interface",
                "state_event": "canonical_handoff",
                "frame_id": "multipole_exit_frame",
                "clock_epoch_id": "instrument_trigger",
                "instrument_time_us": instrument_time,
                "lineage_age_us": elapsed_time,
                "particle_age_us": elapsed_time,
                "last_component_elapsed_time_us": elapsed_time,
                "lineage_birth_time_us": birth_time,
                "particle_birth_time_us": birth_time,
                "mass_to_charge_Th": mass_to_charge_th(mass_amu, charge_state),
                "mass_amu": mass_amu,
                "charge_state": charge_state,
                "position_x_mm": float(state["transverse_x_mm"]),
                "position_y_mm": float(state["transverse_y_mm"]),
                "position_z_mm": float(state["axial_z_mm"]),
                "velocity_x_m_s": velocity[0],
                "velocity_y_m_s": velocity[1],
                "velocity_z_m_s": velocity[2],
                "kinetic_energy_eV": kinetic_energy_ev(mass_amu, *velocity),
                "phase_reference_id": "multipole_rf_drive",
                "phase_rad": float(state["rf_phase_rad"]),
            }
        )
    write_component_particle_state_csv(output_path, output_rows)


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
    if len(manifest_paths) != len(MODE_IDS):
        raise ValueError("exactly three ordered mode manifests are required")
    manifests = [load_json(path) for path in manifest_paths]
    if any(
        manifest.get("status") != "success" or manifest.get("project") != project_id
        for manifest in manifests
    ):
        raise ValueError("mode manifests must be successful runs from one project")
    solvers = [solver_name(manifest) for manifest in manifests]
    if len(set(solvers)) != 1:
        raise ValueError("three-mode binding requires one solver")
    solver_id = solvers[0].lower()
    run_configs = [_verified_run_config(manifest) for manifest in manifests]
    if [
        config["parameters"]["operating_mode_id"] for config in run_configs
    ] != list(MODE_IDS):
        raise ValueError("ordered run operating modes differ from the public method")
    for manifest in manifests:
        _verified_run_input(manifest, "solver_numerics")
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
    for mode_id, manifest in zip(MODE_IDS, manifests, strict=True):
        state_path = _verified_run_output(
            manifest, primary_state_filename(manifest, solvers[0])
        )
        source_path = _verified_run_input(manifest, "particle_source")
        output_path = output_dir / f"{mode_id}__handoff.csv"
        publish_handoff(
            state_path,
            source_path,
            output_path,
            project_id=project_id,
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--preregistration", required=True, type=Path)
    parser.add_argument("--no-acceleration-manifest", required=True, type=Path)
    parser.add_argument("--segmented-manifest", required=True, type=Path)
    parser.add_argument("--exit-plate-manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    binding = publish_binding(
        args.repo_root.resolve(),
        args.preregistration.resolve(),
        [
            args.no_acceleration_manifest.resolve(),
            args.segmented_manifest.resolve(),
            args.exit_plate_manifest.resolve(),
        ],
        args.output_dir.resolve(),
    )
    print(
        "MULTIPOLE_THREE_MODE_BINDING=PASS "
        f"PROJECT={binding['project_id']} SOLVER={binding['solver_id']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
