"""Compare one solver at the two preregistered RF time resolutions."""

from __future__ import annotations

import argparse
import copy
import csv
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256 as sha256
from projects.rf_quadrupole_ion_optics.analysis.particle_state_comparison_core import (
    aggregate_handoff,
    event_ids,
    load_event_table,
    optional_symmetric_relative_difference,
    residual_values,
)
from projects.rf_quadrupole_ion_optics.analysis.validate_paired_particle_source_binding import (
    resolve_binding,
)


def within_acceptance(value: float | None, maximum: float) -> bool:
    return value is not None and value <= maximum


def verify_record(name: str, record: dict[str, Any]) -> Path:
    path = Path(record["path"]).resolve()
    if not path.is_file():
        raise ValueError(f"{name} is missing: {path}")
    if path.stat().st_size != int(record["bytes"]):
        raise ValueError(f"{name} byte count changed: {path}")
    if sha256(path) != str(record["sha256"]).upper():
        raise ValueError(f"{name} SHA-256 changed: {path}")
    return path


def validate_source_run_identity(
    path: Path,
    manifest: dict[str, Any],
    config: dict[str, Any],
) -> None:
    identity = json.loads(path.read_text(encoding="utf-8-sig"))
    if set(identity) != {
        "schema_version",
        "role",
        "source_manifest",
        "run",
        "run_config",
    }:
        raise ValueError("portable source-run identity fields differ")
    source = identity["source_manifest"]
    run = identity["run"]
    run_config = identity["run_config"]
    if (
        identity["schema_version"] != 1
        or identity["role"] != "portable_source_run_identity"
        or set(source)
        != {"schema_version", "role", "bytes", "sha256"}
        or source["schema_version"] != manifest.get("schema_version")
        or source["role"] != manifest.get("role")
        or int(source["bytes"]) <= 0
        or len(str(source["sha256"])) != 64
        or set(run) != {"run_id", "project", "mode", "status"}
        or run
        != {
            "run_id": manifest.get("run_id"),
            "project": manifest.get("project"),
            "mode": manifest.get("mode"),
            "status": manifest.get("status"),
        }
        or set(run_config)
        != {"schema_version", "role", "workflow_id"}
        or run_config
        != {
            "schema_version": config.get("schema_version"),
            "role": config.get("role"),
            "workflow_id": str(config.get("workflow_id", "")),
        }
    ):
        raise ValueError("portable source-run identity differs from its closure")
    try:
        int(str(source["sha256"]), 16)
    except ValueError as error:
        raise ValueError("portable source-manifest SHA-256 is invalid") from error


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
    portable_closure = manifest.get("portable_closure")
    if portable_closure is not None:
        identity_record = portable_closure.get("source_run_identity")
        if not isinstance(identity_record, dict):
            raise ValueError("portable closure source-run identity is missing")
        identity_path = verify_record("source-run identity", identity_record)
        validate_source_run_identity(identity_path, manifest, config)
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


def normalized_frozen_python_identity(
    config: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any] | None:
    frozen = config.get("frozen_python")
    if frozen is None:
        return None
    if not isinstance(frozen, dict):
        raise ValueError("frozen Python identity is invalid")
    package = frozen.get("package")
    execution = frozen.get("execution")
    if not isinstance(package, dict) or not isinstance(execution, dict):
        raise ValueError("frozen Python package or execution identity is missing")
    files = package.get("files")
    modules = execution.get("frozen_modules")
    third_party = execution.get("third_party")
    if (
        not isinstance(files, list)
        or not files
        or not isinstance(modules, list)
        or not isinstance(third_party, list)
    ):
        raise ValueError("frozen Python inventory is invalid")
    file_identity: list[dict[str, str]] = []
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError("frozen Python file identity is invalid")
        relative = Path(str(entry.get("relative_path", "")))
        digest = str(entry.get("sha256", "")).upper()
        if (
            relative.as_posix() in {"", "."}
            or relative.is_absolute()
            or ".." in relative.parts
            or len(digest) != 64
        ):
            raise ValueError("frozen Python relative path or SHA-256 is invalid")
        try:
            int(digest, 16)
        except ValueError as error:
            raise ValueError("frozen Python SHA-256 is invalid") from error
        file_identity.append(
            {
                "relative_path": relative.as_posix(),
                "sha256": digest,
            }
        )
    code_records = [
        record
        for name, record in sorted(manifest.get("inputs", {}).items())
        if name.startswith("frozen_python_code_")
    ]
    package_hashes = sorted(entry["sha256"] for entry in file_identity)
    manifest_hashes = sorted(
        str(record["sha256"]).upper() for record in code_records
    )
    if package_hashes != manifest_hashes:
        raise ValueError(
            "frozen Python package differs from manifest code inventory"
        )
    support = manifest.get("inputs", {}).get(
        "frozen_python_package_support"
    )
    if not isinstance(support, dict):
        raise ValueError("frozen Python package support identity is missing")
    module_names = sorted(str(entry.get("name", "")) for entry in modules)
    module = str(execution.get("module", ""))
    if not module or not all(module_names):
        raise ValueError("frozen Python module identity is invalid")
    distributions = sorted(
        (
            {
                "name": str(entry.get("name", "")),
                "version": str(entry.get("version", "")),
            }
            for entry in third_party
        ),
        key=lambda entry: (entry["name"].lower(), entry["version"]),
    )
    if not all(entry["name"] and entry["version"] for entry in distributions):
        raise ValueError("frozen Python distribution identity is invalid")
    return {
        "module": module,
        "files": sorted(
            file_identity,
            key=lambda entry: entry["relative_path"].lower(),
        ),
        "modules": module_names,
        "third_party": distributions,
        "package_support_sha256": str(support["sha256"]).upper(),
    }


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
    if varied_parameter == "comsol_rf_steps_per_period":
        normalized.pop("solver_numerics_profile_id", None)
        normalized.pop("numerical_experiment_id", None)
        compiled = normalized.get("compiled_solver_numerics")
        if isinstance(compiled, dict):
            compiled["selection"] = {
                "validated_registered_pair_member": True
            }
            trajectory = compiled.get("trajectory")
            if isinstance(trajectory, dict):
                trajectory.pop("rf_steps_per_period", None)
    frozen_python_identity = normalized_frozen_python_identity(
        config, manifest
    )
    if frozen_python_identity is None:
        normalized.pop("frozen_python", None)
    else:
        normalized["frozen_python"] = frozen_python_identity
    normalized["inputs"] = {
        name: {
            "bytes": int(record["bytes"]),
            "sha256": str(record["sha256"]).upper(),
        }
        for name, record in sorted(manifest.get("inputs", {}).items())
        if name != "particle_source_binding"
    }
    return canonicalize(normalized)


def validate_source_numerics_authority(
    solver: str,
    manifest: dict[str, Any],
    config: dict[str, Any],
    authority_path: Path,
) -> None:
    input_role = (
        "comsol_solver_numerics"
        if solver == "COMSOL"
        else "numerical_contract"
    )
    record = manifest.get("inputs", {}).get(input_role)
    if not isinstance(record, dict):
        raise ValueError(f"{solver} solver-numerics input is missing")
    authority_digest = sha256(authority_path)
    if str(record["sha256"]).upper() != authority_digest:
        raise ValueError(
            f"{solver} solver-numerics input differs from workflow authority"
        )
    if solver == "COMSOL":
        authority = json.loads(
            authority_path.read_text(encoding="utf-8-sig")
        )
        provenance = config.get("provenance", {})
        if (
            authority.get("role")
            != "rf_quadrupole_comsol_solver_numerics"
            or config.get("solver_numerics_contract_id")
            != authority.get("contract_id")
            or config.get("solver_numerics_contract_logical_sha256")
            != authority.get("logical_sha256")
            or provenance.get("solver_numerics_sha256") != authority_digest
        ):
            raise ValueError(
                "COMSOL solver-numerics authority identity differs"
            )
    else:
        authority = json.loads(
            authority_path.read_text(encoding="utf-8-sig")
        )
        provenance = config.get("provenance", {})
        if (
            authority.get("role")
            != "rf_quadrupole_simion_solver_numerics"
            or provenance.get("solver_numerics_contract_sha256")
            != authority_digest
        ):
            raise ValueError(
                "SIMION solver-numerics authority identity differs"
            )


def validate_derived_numerical_identity(
    solver: str,
    config: dict[str, Any],
    numerical_value: int,
) -> None:
    if solver != "COMSOL":
        return
    expected = {
        80: ("baseline", ""),
        160: (
            "time_refined_160",
            "same_solver_numerical_convergence",
        ),
    }
    if numerical_value not in expected:
        raise ValueError("COMSOL numerical value has no registered profile")
    profile_id, experiment_id = expected[numerical_value]
    usage = "production" if numerical_value == 80 else "registered_experiment"
    compiled = config.get("compiled_solver_numerics")
    if not isinstance(compiled, dict):
        raise ValueError("COMSOL compiled numerical identity is missing")
    authority = compiled.get("authority")
    selection = compiled.get("selection")
    mesh = compiled.get("mesh")
    trajectory = compiled.get("trajectory")
    if (
        config.get("solver_numerics_profile_id") != profile_id
        or config.get("numerical_experiment_id") != experiment_id
        or compiled.get("schema_version") != 1
        or compiled.get("role")
        != "rf_quadrupole_compiled_comsol_solver_numerics"
        or not isinstance(authority, dict)
        or authority.get("contract_id")
        != config.get("solver_numerics_contract_id")
        or authority.get("logical_sha256")
        != config.get("solver_numerics_contract_logical_sha256")
        or selection
        != {
            "profile_id": profile_id,
            "usage": usage,
            "numerical_experiment_id": experiment_id,
        }
        or not isinstance(mesh, dict)
        or mesh.get("global_auto_level")
        != config.get("comsol_mesh_auto_level")
        or not isinstance(trajectory, dict)
        or trajectory.get("rf_steps_per_period") != numerical_value
        or trajectory.get("maximum_time_us")
        != config.get("maximum_time_us")
    ):
        raise ValueError(
            "COMSOL numerical profile identity differs from its RF step count"
        )


def solver_from_role(role: str) -> str:
    roles = {
        "rf_quadrupole_simion_run_config": "SIMION",
        "rf_quadrupole_comsol_run_config": "COMSOL",
    }
    if role not in roles:
        raise ValueError(f"unsupported transport run-config role: {role}")
    return roles[role]


def numerical_pair(
    solver: str,
    matrix: dict[str, Any],
    contract: dict[str, Any],
    contract_path: Path,
    simion_numerics_path: Path | None,
) -> tuple[int, int]:
    if solver != "SIMION":
        return int(matrix["baseline_value"]), int(matrix["refined_value"])
    relative = contract.get("simion_solver_numerics_contract")
    if relative != "config/simion_solver_numerics.json":
        raise ValueError("SIMION solver-numerics contract identity is missing")
    numerics_path = simion_numerics_path
    if numerics_path is None:
        numerics_path = contract_path.resolve().parents[1] / relative
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
    inventory: dict[str, dict[str, Any]] = {}
    for row in rows:
        filename = row["file"]
        if not filename.lower().startswith("quad_monolithic.pa"):
            continue
        if Path(filename).name != filename or filename in inventory:
            raise ValueError("SIMION PA core inventory filename is invalid or duplicated")
        byte_count = int(row["bytes"])
        digest = row["sha256"].upper()
        if byte_count <= 0 or len(digest) != 64:
            raise ValueError("SIMION PA core inventory identity is invalid")
        try:
            int(digest, 16)
        except ValueError as error:
            raise ValueError(
                "SIMION PA core inventory SHA-256 is invalid"
            ) from error
        inventory[filename] = {
            "bytes": byte_count,
            "sha256": digest,
        }
    if not inventory:
        raise ValueError("SIMION PA core inventory is empty")
    return inventory


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
    row.update(residual_values(particle_id, baseline, refined))
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-manifest", required=True, type=Path)
    parser.add_argument("--refined-manifest", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--comsol-numerics", type=Path)
    parser.add_argument("--simion-numerics", type=Path)
    parser.add_argument("--particle-count-policy", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--census-output", required=True, type=Path)
    args = parser.parse_args()

    contract = json.loads(args.contract.read_text(encoding="utf-8-sig"))
    particle_policy = json.loads(
        args.particle_count_policy.read_text(encoding="utf-8-sig")
    )
    if (
        contract.get("role")
        != "rf_quadrupole_same_solver_numerical_convergence_contract"
        or contract.get("status") != "numerical_screen_candidate_only"
    ):
        raise ValueError("same-solver numerical convergence contract is invalid")
    if particle_policy.get("role") != "repository_particle_count_policy":
        raise ValueError("particle-count policy identity differs")
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
    authority_path = (
        args.comsol_numerics if solver == "COMSOL" else args.simion_numerics
    )
    if authority_path is None:
        raise ValueError(f"{solver} solver-numerics authority is required")
    validate_source_numerics_authority(
        solver, baseline_manifest, baseline_config, authority_path
    )
    validate_source_numerics_authority(
        solver, refined_manifest, refined_config, authority_path
    )
    varied = matrix["varied_parameter"]
    baseline_value, refined_value = numerical_pair(
        solver, matrix, contract, args.contract, args.simion_numerics
    )
    if (
        baseline_config.get(varied) != baseline_value
        or refined_config.get(varied) != refined_value
    ):
        raise ValueError("numerical step pair differs from the preregistered matrix")
    validate_derived_numerical_identity(
        solver, baseline_config, baseline_value
    )
    validate_derived_numerical_identity(
        solver, refined_config, refined_value
    )
    for field in ("project", "mode", "operating_point"):
        if baseline_config.get(field) != refined_config.get(field):
            raise ValueError(f"source run {field} differs")
    if baseline_config.get("mode") != contract["required_mode"]:
        raise ValueError("source run mode differs from the preregistered matrix")
    particles = int(baseline_config.get("particles", 0))
    if particles <= 0 or int(refined_config.get("particles", 0)) != particles:
        raise ValueError("source particle count differs or is empty")
    minimum_particles = int(particle_policy["functional_check_count"])
    sample_size_eligible = particles >= minimum_particles
    _, baseline_particle_record = particle_record(baseline_manifest)
    _, refined_particle_record = particle_record(refined_manifest)
    if (
        str(baseline_particle_record["sha256"]).upper()
        != str(refined_particle_record["sha256"]).upper()
    ):
        raise ValueError("source particle SHA-256 differs")
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
    source_identity: dict[str, Any] = {}
    if sample_size_eligible:
        expected_representation = (
            "canonical10" if solver == "SIMION" else "ion11"
        )
        baseline_binding = recompute_source_binding(
            baseline_config, expected_representation
        )
        refined_binding = recompute_source_binding(
            refined_config, expected_representation
        )
        if (
            int(baseline_binding["particle_count"]) != particles
            or int(refined_binding["particle_count"]) != particles
        ):
            raise ValueError("bound particle count differs from run config")
        if any(
            baseline_binding[field] != refined_binding[field]
            for field in source_identity_fields
        ):
            raise ValueError(
                "same-solver paired source binding identity differs"
            )
        source_identity = {
            field: baseline_binding[field] for field in source_identity_fields
        }
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

    baseline_rows = load_event_table(baseline_state_path)
    refined_rows = load_event_table(refined_state_path)
    expected_ids = set(range(1, particles + 1))
    if event_ids(baseline_rows, "source") != expected_ids or event_ids(
        refined_rows, "source"
    ) != expected_ids:
        raise ValueError("particle-state source IDs differ from the particle source")
    baseline_aggregate = aggregate_handoff(baseline_rows, particles)
    refined_aggregate = aggregate_handoff(refined_rows, particles)
    baseline_handoff = event_ids(baseline_rows, "handoff")
    refined_handoff = event_ids(refined_rows, "handoff")
    acceptance = contract["acceptance"]
    metrics = {
        "transmission_absolute_difference": abs(
            float(baseline_aggregate["transmission"])
            - float(refined_aggregate["transmission"])
        ),
        "mean_tof_relative_difference": optional_symmetric_relative_difference(
            baseline_aggregate["mean_tof_us"],
            refined_aggregate["mean_tof_us"],
        ),
        "rms_radius_relative_difference": optional_symmetric_relative_difference(
            baseline_aggregate["rms_radius_mm"],
            refined_aggregate["rms_radius_mm"],
        ),
        "rms_divergence_relative_difference": optional_symmetric_relative_difference(
            baseline_aggregate["rms_divergence_deg"],
            refined_aggregate["rms_divergence_deg"],
        ),
        "mean_energy_relative_difference": optional_symmetric_relative_difference(
            baseline_aggregate["mean_energy_eV"],
            refined_aggregate["mean_energy_eV"],
        ),
    }
    evaluated_gates = {
        "handoff_particle_id_sets": baseline_handoff == refined_handoff
        and bool(baseline_handoff),
        "transmission": within_acceptance(
            metrics["transmission_absolute_difference"],
            acceptance["transmission_absolute_difference"],
        ),
        "mean_tof": within_acceptance(
            metrics["mean_tof_relative_difference"],
            acceptance["mean_tof_relative_difference"],
        ),
        "rms_radius": within_acceptance(
            metrics["rms_radius_relative_difference"],
            acceptance["rms_radius_relative_difference"],
        ),
        "rms_divergence": within_acceptance(
            metrics["rms_divergence_relative_difference"],
            acceptance["rms_divergence_relative_difference"],
        ),
        "mean_energy": within_acceptance(
            metrics["mean_energy_relative_difference"],
            acceptance["mean_energy_relative_difference"],
        ),
        "mesh_element_identity": mesh_element_identity,
    }
    gates = evaluated_gates if sample_size_eligible else {}
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
        "status": (
            "NOT_EVALUATED"
            if not sample_size_eligible
            else "PASS"
            if all(gates.values())
            else "FAIL"
        ),
        "execution_status": "success",
        "claim_status": contract["status"],
        "solver": solver,
        "mode": baseline_config["mode"],
        "operating_point": baseline_config["operating_point"],
        "particles": particles,
        "minimum_functional_particles": minimum_particles,
        "sample_size_eligible": sample_size_eligible,
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
            "particle_count_policy_sha256": sha256(
                args.particle_count_policy
            ),
        },
        "source_identity": source_identity,
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
