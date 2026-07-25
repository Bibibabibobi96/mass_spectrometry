"""Compare one solver at the two preregistered RF time resolutions."""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

try:
    from projects.rf_quadrupole_collision_cooling.analysis.compare_particle_state import (
        aggregate,
        load,
        optional_relative_difference,
        within,
        wrapped_phase_difference,
    )
except ModuleNotFoundError:
    from compare_particle_state import (
        aggregate,
        load,
        optional_relative_difference,
        within,
        wrapped_phase_difference,
    )
try:
    from projects.rf_quadrupole_collision_cooling.analysis.validate_paired_particle_source_binding import (
        resolve_binding,
    )
except ModuleNotFoundError:
    from validate_paired_particle_source_binding import resolve_binding


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def verify_record(name: str, record: dict[str, Any]) -> Path:
    path = Path(record["path"]).resolve()
    if not path.is_file():
        raise ValueError(f"{name} is missing: {path}")
    if path.stat().st_size != int(record["bytes"]):
        raise ValueError(f"{name} byte count changed: {path}")
    if sha256(path) != str(record["sha256"]).upper():
        raise ValueError(f"{name} SHA-256 changed: {path}")
    return path


def load_manifest(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    if manifest.get("status") != "success":
        raise ValueError(f"source manifest is not success: {path}")
    config_path = verify_record("run config", manifest["run_config"])
    for name, record in manifest.get("inputs", {}).items():
        verify_record(f"manifest input {name}", record)
    for index, record in enumerate(manifest.get("outputs", []), start=1):
        verify_record(f"manifest output {index}", record)
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    for field in ("run_id", "project", "mode"):
        if manifest.get(field) != config.get(field):
            raise ValueError(f"manifest and run config {field} differ")
    return manifest, config


def find_record(
    records: list[dict[str, Any]], filename: str
) -> tuple[Path, dict[str, Any]]:
    matches = [
        (Path(record["path"]).resolve(), record)
        for record in records
        if Path(record["path"]).name.lower() == filename.lower()
    ]
    if len(matches) != 1:
        raise ValueError(f"manifest must contain exactly one {filename}")
    return matches[0]


def particle_record(manifest: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    record = manifest.get("inputs", {}).get("particle_table")
    if not isinstance(record, dict):
        raise ValueError("manifest particle_table input is missing")
    return Path(record["path"]).resolve(), record


def canonicalize(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: canonicalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [canonicalize(item) for item in value]
    return value


def normalized_run_config(
    config: dict[str, Any],
    manifest: dict[str, Any],
    varied_parameter: str,
) -> dict[str, Any]:
    normalized = copy.deepcopy(config)
    for key in list(normalized):
        if (
            key in {"run_id", "project_root", varied_parameter}
            or key.endswith("_dir")
            or key.endswith("_path")
        ):
            normalized.pop(key)
    if varied_parameter == "rf_steps_per_period":
        provenance = normalized.get("provenance")
        if isinstance(provenance, dict):
            provenance.pop("rf_steps_per_period", None)
            provenance.pop("rf_steps_override", None)
    normalized["inputs"] = {
        name: {
            "bytes": int(record["bytes"]),
            "sha256": str(record["sha256"]).upper(),
        }
        for name, record in sorted(manifest.get("inputs", {}).items())
        if name != "particle_source_binding"
    }
    return canonicalize(normalized)


def solver_from_role(role: str) -> str:
    roles = {
        "rf_quadrupole_simion_run_config": "SIMION",
        "rf_quadrupole_comsol_run_config": "COMSOL",
    }
    if role not in roles:
        raise ValueError(f"unsupported transport run-config role: {role}")
    return roles[role]


def numerical_pair(
    solver: str, matrix: dict[str, Any], contract: dict[str, Any], contract_path: Path
) -> tuple[int, int]:
    if solver != "SIMION":
        return int(matrix["baseline_value"]), int(matrix["refined_value"])
    relative = contract.get("simion_solver_numerics_contract")
    if not isinstance(relative, str) or not relative:
        raise ValueError("SIMION solver-numerics contract identity is missing")
    project_root = contract_path.resolve().parents[1]
    numerics_path = (project_root / relative).resolve()
    if not numerics_path.is_file():
        raise ValueError("SIMION solver-numerics contract is missing")
    numerics = json.loads(numerics_path.read_text(encoding="utf-8-sig"))
    if numerics.get("role") != "rf_quadrupole_simion_solver_numerics":
        raise ValueError("SIMION solver-numerics contract role is invalid")
    baseline_key = matrix.get("baseline_value_source")
    values_key = matrix.get("comparison_values_source")
    baseline = int(numerics[baseline_key])
    values = [int(value) for value in numerics[values_key]]
    if len(values) != 2 or baseline not in values:
        raise ValueError("SIMION convergence values must be one baseline/refined pair")
    refined = next(value for value in values if value != baseline)
    return baseline, refined


def config_input_path(config: dict[str, Any], name: str) -> Path:
    value = Path(config["inputs"][name])
    if value.is_absolute():
        return value.resolve()
    return (Path(config["project_root"]) / value).resolve()


def recompute_source_binding(
    config: dict[str, Any],
    expected_representation: str,
) -> dict[str, Any]:
    required = {
        "particle_table",
        "consumed_particle_table",
        "source_ion11",
        "source_canonical10",
        "particle_bundle_metadata",
        "particle_source_family",
        "particle_source_distribution",
        "resolved_design",
    }
    if not required.issubset(config.get("inputs", {})):
        raise ValueError("run config lacks paired particle source inputs")
    consumed = config_input_path(config, "particle_table")
    if consumed != config_input_path(config, "consumed_particle_table"):
        raise ValueError("run config particle_table is not the consumed source")
    binding = resolve_binding(
        config_input_path(config, "particle_bundle_metadata"),
        config_input_path(config, "particle_source_family"),
        config_input_path(config, "particle_source_distribution"),
        config_input_path(config, "resolved_design"),
        str(config["operating_point"]),
        int(config["particles"]),
        expected_representation,
        consumed,
    )
    if binding["representation_equivalence"] != "PASS":
        raise ValueError("paired particle representation equivalence failed")
    provenance = config.get("provenance", {})
    scalar_fields = (
        "source_sample_family_sha256",
        "source_family_sha256",
        "distribution_sha256",
        "latent_sha256",
        "coordinate_mapping_version",
        "operating_point_id",
        "particle_count",
        "representation",
        "consumed_sha256",
        "ion11_sha256",
        "canonical10_sha256",
        "representation_equivalence",
    )
    for field in scalar_fields:
        if str(provenance.get(field)) != str(binding[field]):
            raise ValueError(f"run provenance differs from recomputed {field}")
    for field in (
        "n1000_parent",
        "ion11_n1000_parent",
        "canonical10_n1000_parent",
    ):
        if provenance.get(field) != binding[field]:
            raise ValueError(f"run provenance differs from recomputed {field}")
    return binding


def load_pa_core_inventory(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    inventory_path, _ = find_record(manifest.get("outputs", []), "SHA256SUMS.csv")
    with inventory_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    inventory = {
        row["file"]: {
            "bytes": int(row["bytes"]),
            "sha256": row["sha256"].upper(),
        }
        for row in rows
        if row["file"].lower().startswith("quad_monolithic.pa")
    }
    if not inventory:
        raise ValueError("SIMION PA core inventory is empty")
    for filename, identity in inventory.items():
        asset = inventory_path.parent / filename
        if (
            not asset.is_file()
            or asset.stat().st_size != identity["bytes"]
            or sha256(asset) != identity["sha256"]
        ):
            raise ValueError(f"SIMION PA core asset differs from inventory: {asset}")
    return inventory


def event_ids(
    rows: dict[tuple[int, str], dict[str, str]], event: str
) -> set[int]:
    return {particle_id for particle_id, row_event in rows if row_event == event}


def residual_row(
    particle_id: int,
    baseline: dict[str, str] | None,
    refined: dict[str, str] | None,
) -> dict[str, float | int | str]:
    status = (
        "paired"
        if baseline is not None and refined is not None
        else "baseline_only"
        if baseline is not None
        else "refined_only"
        if refined is not None
        else "neither"
    )
    row: dict[str, float | int | str] = {
        "particle_id": particle_id,
        "handoff_pair_status": status,
        "position_residual_mm": "",
        "velocity_residual_m_s": "",
        "tof_residual_us": "",
        "energy_residual_eV": "",
        "rf_phase_residual_rad": "",
    }
    if baseline is None or refined is None:
        return row
    dx = float(baseline["transverse_x_mm"]) - float(
        refined["transverse_x_mm"]
    )
    dy = float(baseline["transverse_y_mm"]) - float(
        refined["transverse_y_mm"]
    )
    dvz = float(baseline["velocity_axial_m_s"]) - float(
        refined["velocity_axial_m_s"]
    )
    dvx = float(baseline["velocity_x_m_s"]) - float(refined["velocity_x_m_s"])
    dvy = float(baseline["velocity_y_m_s"]) - float(refined["velocity_y_m_s"])
    row.update(
        {
            "position_residual_mm": math.hypot(dx, dy),
            "velocity_residual_m_s": math.sqrt(
                dvz * dvz + dvx * dvx + dvy * dvy
            ),
            "tof_residual_us": float(baseline["elapsed_time_us"])
            - float(refined["elapsed_time_us"]),
            "energy_residual_eV": float(baseline["kinetic_energy_eV"])
            - float(refined["kinetic_energy_eV"]),
            "rf_phase_residual_rad": wrapped_phase_difference(
                float(baseline["rf_phase_rad"]),
                float(refined["rf_phase_rad"]),
            ),
        }
    )
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-manifest", required=True, type=Path)
    parser.add_argument("--refined-manifest", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--census-output", required=True, type=Path)
    args = parser.parse_args()

    contract = json.loads(args.contract.read_text(encoding="utf-8-sig"))
    if (
        contract.get("role")
        != "rf_quadrupole_same_solver_numerical_convergence_contract"
        or contract.get("status") != "numerical_screen_candidate_only"
    ):
        raise ValueError("same-solver numerical convergence contract is invalid")
    baseline_manifest, baseline_config = load_manifest(args.baseline_manifest)
    refined_manifest, refined_config = load_manifest(args.refined_manifest)
    baseline_solver = solver_from_role(str(baseline_config.get("role")))
    refined_solver = solver_from_role(str(refined_config.get("role")))
    if baseline_solver != refined_solver:
        raise ValueError("same-solver comparison received different solvers")
    solver = baseline_solver
    matrix = contract["comparisons"][solver]
    if baseline_config.get("role") != matrix["run_config_role"]:
        raise ValueError("run-config role differs from the preregistered matrix")
    varied = matrix["varied_parameter"]
    baseline_value, refined_value = numerical_pair(
        solver, matrix, contract, args.contract
    )
    if (
        baseline_config.get(varied) != baseline_value
        or refined_config.get(varied) != refined_value
    ):
        raise ValueError("numerical step pair differs from the preregistered matrix")
    for field in ("project", "mode", "operating_point"):
        if baseline_config.get(field) != refined_config.get(field):
            raise ValueError(f"source run {field} differs")
    if baseline_config.get("mode") != contract["required_mode"]:
        raise ValueError("source run mode differs from the preregistered matrix")
    expected_representation = "canonical10" if solver == "SIMION" else "ion11"
    baseline_binding = recompute_source_binding(
        baseline_config, expected_representation
    )
    refined_binding = recompute_source_binding(refined_config, expected_representation)
    _, baseline_particle_record = particle_record(baseline_manifest)
    _, refined_particle_record = particle_record(refined_manifest)
    if (
        str(baseline_particle_record["sha256"]).upper()
        != str(refined_particle_record["sha256"]).upper()
    ):
        raise ValueError("source particle SHA-256 differs")
    particles = int(baseline_binding["particle_count"])
    if particles <= 0 or int(refined_binding["particle_count"]) != particles:
        raise ValueError("source particle count differs or is empty")
    source_identity_fields = (
        "bundle_metadata_sha256",
        "source_sample_family_sha256",
        "source_family_sha256",
        "distribution_sha256",
        "latent_sha256",
        "coordinate_mapping_version",
        "operating_point_id",
        "particle_count",
        "representation",
        "consumed_sha256",
        "ion11_sha256",
        "canonical10_sha256",
        "representation_equivalence",
        "ion11_n1000_parent",
        "canonical10_n1000_parent",
    )
    if any(
        baseline_binding[field] != refined_binding[field]
        for field in source_identity_fields
    ):
        raise ValueError("same-solver paired source binding identity differs")
    if normalized_run_config(
        baseline_config, baseline_manifest, varied
    ) != normalized_run_config(refined_config, refined_manifest, varied):
        raise ValueError(
            "run configs differ outside the preregistered numerical parameter"
        )

    baseline_state_path, _ = find_record(
        baseline_manifest.get("outputs", []), "particle_state.csv"
    )
    refined_state_path, _ = find_record(
        refined_manifest.get("outputs", []), "particle_state.csv"
    )
    baseline_summary_path, _ = find_record(
        baseline_manifest.get("outputs", []), "solver_summary.json"
    )
    refined_summary_path, _ = find_record(
        refined_manifest.get("outputs", []), "solver_summary.json"
    )
    baseline_summary = json.loads(
        baseline_summary_path.read_text(encoding="utf-8-sig")
    )
    refined_summary = json.loads(
        refined_summary_path.read_text(encoding="utf-8-sig")
    )
    asset_identity: dict[str, Any]
    mesh_element_identity = True
    if solver == "SIMION":
        baseline_pa = load_pa_core_inventory(baseline_manifest)
        refined_pa = load_pa_core_inventory(refined_manifest)
        if baseline_pa != refined_pa:
            raise ValueError("SIMION PA core SHA-256 inventory differs")
        asset_identity = {"pa_core_inventory": baseline_pa}
    else:
        baseline_elements = baseline_summary.get("mesh_elements_total")
        refined_elements = refined_summary.get("mesh_elements_total")
        if not isinstance(baseline_elements, int) or not isinstance(
            refined_elements, int
        ):
            raise ValueError("COMSOL solver summary lacks integer mesh element count")
        mesh_element_identity = baseline_elements == refined_elements
        asset_identity = {
            "baseline_mesh_elements_total": baseline_elements,
            "refined_mesh_elements_total": refined_elements,
            "policy": matrix["mesh_element_policy"],
        }

    baseline_rows = load(baseline_state_path)
    refined_rows = load(refined_state_path)
    expected_ids = set(range(1, particles + 1))
    if event_ids(baseline_rows, "source") != expected_ids or event_ids(
        refined_rows, "source"
    ) != expected_ids:
        raise ValueError("particle-state source IDs differ from the particle source")
    baseline_aggregate = aggregate(baseline_rows, particles)
    refined_aggregate = aggregate(refined_rows, particles)
    baseline_handoff = event_ids(baseline_rows, "handoff")
    refined_handoff = event_ids(refined_rows, "handoff")
    acceptance = contract["acceptance"]
    metrics = {
        "transmission_absolute_difference": abs(
            float(baseline_aggregate["transmission"])
            - float(refined_aggregate["transmission"])
        ),
        "mean_tof_relative_difference": optional_relative_difference(
            baseline_aggregate["mean_tof_us"],
            refined_aggregate["mean_tof_us"],
        ),
        "rms_radius_relative_difference": optional_relative_difference(
            baseline_aggregate["rms_radius_mm"],
            refined_aggregate["rms_radius_mm"],
        ),
        "rms_divergence_relative_difference": optional_relative_difference(
            baseline_aggregate["rms_divergence_deg"],
            refined_aggregate["rms_divergence_deg"],
        ),
        "mean_energy_relative_difference": optional_relative_difference(
            baseline_aggregate["mean_energy_eV"],
            refined_aggregate["mean_energy_eV"],
        ),
    }
    gates = {
        "handoff_particle_id_sets": baseline_handoff == refined_handoff
        and bool(baseline_handoff),
        "transmission": within(
            metrics["transmission_absolute_difference"],
            acceptance["transmission_absolute_difference"],
        ),
        "mean_tof": within(
            metrics["mean_tof_relative_difference"],
            acceptance["mean_tof_relative_difference"],
        ),
        "rms_radius": within(
            metrics["rms_radius_relative_difference"],
            acceptance["rms_radius_relative_difference"],
        ),
        "rms_divergence": within(
            metrics["rms_divergence_relative_difference"],
            acceptance["rms_divergence_relative_difference"],
        ),
        "mean_energy": within(
            metrics["mean_energy_relative_difference"],
            acceptance["mean_energy_relative_difference"],
        ),
        "mesh_element_identity": mesh_element_identity,
    }
    events = contract["event_census_schema"]
    census_rows: list[dict[str, Any]] = []
    for particle_id in range(1, particles + 1):
        row: dict[str, Any] = {"particle_id": particle_id}
        for event in events:
            row[f"baseline_{event}"] = int((particle_id, event) in baseline_rows)
            row[f"refined_{event}"] = int((particle_id, event) in refined_rows)
        row.update(
            residual_row(
                particle_id,
                baseline_rows.get((particle_id, "handoff")),
                refined_rows.get((particle_id, "handoff")),
            )
        )
        census_rows.append(row)
    event_census = {
        side: {
            event: sum(
                1
                for particle_id in expected_ids
                if (particle_id, event) in rows
            )
            for event in events
        }
        for side, rows in (
            ("baseline", baseline_rows),
            ("refined", refined_rows),
        )
    }
    result = {
        "schema_version": 1,
        "role": "rf_quadrupole_same_solver_numerical_convergence_result",
        "status": "PASS" if all(gates.values()) else "FAIL",
        "execution_status": "success",
        "claim_status": contract["status"],
        "solver": solver,
        "mode": baseline_config["mode"],
        "operating_point": baseline_config["operating_point"],
        "particles": particles,
        "numerical_parameter": {
            "name": varied,
            "baseline": baseline_config[varied],
            "refined": refined_config[varied],
        },
        "inputs": {
            "baseline_manifest_sha256": sha256(args.baseline_manifest),
            "refined_manifest_sha256": sha256(args.refined_manifest),
            "particle_source_sha256": str(
                baseline_particle_record["sha256"]
            ).upper(),
            "contract_sha256": sha256(args.contract),
        },
        "source_identity": {
            field: baseline_binding[field] for field in source_identity_fields
        },
        "asset_identity": asset_identity,
        "event_census": event_census,
        "baseline": baseline_aggregate,
        "refined": refined_aggregate,
        "thresholds": {
            key: value
            for key, value in acceptance.items()
            if key != "handoff_particle_id_sets"
        },
        "metrics": metrics,
        "gates": gates,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    census_fields = [
        "particle_id",
        *[
            field
            for event in events
            for field in (f"baseline_{event}", f"refined_{event}")
        ],
        "handoff_pair_status",
        "position_residual_mm",
        "velocity_residual_m_s",
        "tof_residual_us",
        "energy_residual_eV",
        "rf_phase_residual_rad",
    ]
    with args.census_output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=census_fields)
        writer.writeheader()
        writer.writerows(census_rows)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
