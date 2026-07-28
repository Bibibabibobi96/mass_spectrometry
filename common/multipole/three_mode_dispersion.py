"""Analyze preregistered three-mode multipole particle dispersion experiments."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any

from common.contracts.component_particle_state import (
    csv_columns,
    validate_component_particle_state_csv,
)
from common.contracts.machine_contracts import ContractError, validate_schema
from common.contracts.particle_count_policy import validate_prefix_particle_sources
from common.contracts.file_identity import file_sha256


CONTRACT_PATH = Path(__file__).with_name("three_mode_dispersion_contract.json")
NUMERICAL_QUALIFICATION_PATH = Path(__file__).with_name("numerical_qualification.json")
RETENTION_POLICY_PATH = Path(__file__).parents[1] / "contracts" / "artifact_retention.json"
MODE_IDS = (
    "no_acceleration_full_length",
    "segmented_rod_axial_acceleration",
    "exit_aperture_plate_acceleration",
)
CONTINUOUS_METRICS = (
    "radius_mm",
    "angular_divergence_mrad",
    "kinetic_energy_eV",
    "component_tof_us",
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789ABCDEF" for character in value)
    )


def _validate_source(path: Path, expected_sha256: str, label: str) -> None:
    _require(path.is_file(), f"{label} is missing")
    _require(_is_sha256(expected_sha256), f"{label} frozen SHA-256 is invalid")
    _require(
        file_sha256(path) == expected_sha256,
        f"{label} SHA-256 differs from frozen binding",
    )


def _resolve_path(binding_path: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (binding_path.parent / path).resolve()


def _load_rows(path: Path) -> list[dict[str, Any]]:
    validate_component_particle_state_csv(path)
    integer_fields = {"particle_id", "generation", "charge_state"}
    nullable_integer_fields = {"parent_particle_id"}
    numeric_fields = {
        "particle_weight",
        "instrument_time_us",
        "lineage_age_us",
        "particle_age_us",
        "last_component_elapsed_time_us",
        "lineage_birth_time_us",
        "particle_birth_time_us",
        "mass_to_charge_Th",
        "mass_amu",
        "position_x_mm",
        "position_y_mm",
        "position_z_mm",
        "velocity_x_m_s",
        "velocity_y_m_s",
        "velocity_z_m_s",
        "kinetic_energy_eV",
        "phase_rad",
    }
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        _require(reader.fieldnames == csv_columns(), "canonical state columns differ")
        for raw in reader:
            row: dict[str, Any] = {}
            for field, value in raw.items():
                if field in integer_fields:
                    row[field] = int(value)
                elif field in nullable_integer_fields:
                    row[field] = None if value == "" else int(value)
                elif field in numeric_fields:
                    row[field] = None if value == "" else float(value)
                else:
                    row[field] = None if value == "" else value
            rows.append(row)
    return rows


def _validate_method_contract(contract: dict[str, Any]) -> None:
    _require(contract.get("schema_version") == 1, "method schema_version differs")
    _require(
        contract.get("role") == "multipole_three_mode_dispersion_method_contract",
        "method role differs",
    )
    _require(
        tuple(contract["voltage_modes"]) == MODE_IDS,
        "three voltage modes differ from the frozen method",
    )
    comparison_pairs = {
        (item["left_mode"], item["right_mode"])
        for item in contract["paired_comparisons"]
    }
    _require(
        comparison_pairs
        == {
            (MODE_IDS[1], MODE_IDS[0]),
            (MODE_IDS[2], MODE_IDS[0]),
            (MODE_IDS[1], MODE_IDS[2]),
        },
        "paired comparisons differ from the frozen method",
    )
    offsets = {
        item["observation_id"]: item.get("offset_from_handoff_mm")
        for item in contract["observation_planes"]
    }
    _require(
        offsets
        == {
            "handoff": 0,
            "near_interface": None,
            "field_free_plus_5mm": 5,
            "field_free_plus_20mm": 20,
            "field_free_plus_50mm": 50,
        },
        "observation planes differ from the frozen method",
    )
    retention = load_json(RETENTION_POLICY_PATH)
    _require(
        contract["retention"]["authority"]
        == "common/contracts/artifact_retention.json"
        and contract["retention"]["required_class"] == "compact"
        and "compact" in retention["classes"],
        "compact retention authority differs",
    )
    numerical = load_json(NUMERICAL_QUALIFICATION_PATH)
    _require(
        contract["engineering_stop_policy"]["authority"]
        == "common/multipole/numerical_qualification.json#/engineering_stop_policy"
        and numerical["engineering_stop_policy"]["forbidden_response"],
        "engineering stop-policy authority differs",
    )


def _validate_binding(
    binding: dict[str, Any], binding_path: Path, contract: dict[str, Any]
) -> dict[str, Any]:
    try:
        validate_schema(binding, "three_mode_dispersion_binding.schema.json")
    except ContractError as error:
        raise ValueError(f"three-mode binding: {error}") from error
    _require(binding.get("schema_version") == 1, "binding schema_version differs")
    _require(
        binding.get("role") == "multipole_three_mode_dispersion_binding",
        "binding role differs",
    )
    _require(
        binding.get("analysis_plan_preregistered_before_run") is True,
        "binding does not identify a preregistered analysis plan",
    )
    _require(
        binding.get("published_after_real_runs") is True,
        "binding was not published after real runs",
    )
    _require(binding.get("retention_class") == "compact", "retention must be compact")
    count = int(binding["analysis_particle_count"])
    _require(count in (100, 1000), "analysis particle count must be N=100 or N=1000")
    bootstrap = binding["bootstrap"]
    _require(
        isinstance(bootstrap.get("seed"), int)
        and isinstance(bootstrap.get("resamples"), int)
        and bootstrap["resamples"] > 0,
        "bootstrap seed and positive resample count must be preregistered",
    )
    geometry = binding["geometry"]
    handoff_z = float(geometry["handoff_plane_z_mm"])
    near_z = float(geometry["near_interface_plane_z_mm"])
    _require(near_z >= handoff_z, "near-interface plane precedes handoff")
    invariant_sha = geometry["geometry_invariant_sha256"]
    _require(_is_sha256(invariant_sha), "geometry invariant SHA-256 is invalid")
    modes = binding["modes"]
    _require(
        [item["mode_id"] for item in modes] == list(MODE_IDS),
        "binding must contain the exact three ordered voltage modes",
    )
    _require(
        all(item["geometry_invariant_sha256"] == invariant_sha for item in modes),
        "voltage modes do not preserve one geometry invariant",
    )
    for item in modes:
        voltage_reference = item["voltage_contract"]
        voltage_path = _resolve_path(binding_path, voltage_reference["path"])
        _validate_source(
            voltage_path,
            voltage_reference["sha256"],
            f"{item['mode_id']} voltage contract",
        )
        voltage = load_json(voltage_path)
        _require(
            voltage.get("project_id") == binding["project_id"]
            and voltage.get("mode_id") == item["mode_id"]
            and voltage.get("geometry_invariant_sha256") == invariant_sha,
            f"{item['mode_id']} voltage contract identity or geometry differs",
        )
    required_bindings = set(contract["required_prerun_bindings"])
    qualification = binding["qualification_bindings"]
    _require(
        set(qualification) == required_bindings,
        "project acceptance, effect-resolution and engineering-budget bindings are required",
    )
    expected_roles = {
        "project_acceptance_contract": "multipole_dispersion_acceptance_contract",
        "project_effect_resolution_contract": "multipole_dispersion_effect_resolution_contract",
        "project_engineering_budget_contract": "multipole_engineering_budget_contract",
    }
    required_content = {
        "project_acceptance_contract": "acceptance_criteria",
        "project_effect_resolution_contract": "effect_resolution",
        "project_engineering_budget_contract": "pilot_authorization",
    }
    for name, reference in qualification.items():
        path = _resolve_path(binding_path, reference["path"])
        _validate_source(path, reference["sha256"], name)
        document = load_json(path)
        _require(
            document.get("role") == expected_roles[name]
            and document.get("project_id") == binding["project_id"]
            and bool(document.get("contract_id")),
            f"{name} role, project or contract identity differs",
        )
        _require(
            document.get("preregistered_before_run") is True,
            f"{name} is not preregistered",
        )
        _require(
            isinstance(document.get(required_content[name]), dict)
            and bool(document[required_content[name]]),
            f"{name} has no preregistered project-specific content",
        )
    source = binding["source_family"]
    n100_path = _resolve_path(binding_path, source["n100"]["path"])
    n1000_path = _resolve_path(binding_path, source["n1000"]["path"])
    validate_prefix_particle_sources(
        n100_path,
        n1000_path,
        expected_n100_sha256=source["n100"]["sha256"],
        expected_n1000_sha256=source["n1000"]["sha256"],
    )
    selected_source_sha256 = (
        source["n100"]["sha256"] if count == 100 else source["n1000"]["sha256"]
    )
    numerics_sha256 = binding["solver_numerics_sha256"]
    _require(_is_sha256(numerics_sha256), "solver numerics SHA-256 is invalid")
    _require(
        all(
            item["particle_source_sha256"] == selected_source_sha256
            and item["solver_numerics_sha256"] == numerics_sha256
            for item in modes
        ),
        "voltage modes do not share one selected source and solver numerics identity",
    )
    return {
        "count": count,
        "handoff_z_mm": handoff_z,
        "near_interface_offset_mm": near_z - handoff_z,
        "n100_path": n100_path,
        "n1000_path": n1000_path,
        "geometry_invariant_sha256": invariant_sha,
        "solver_numerics_sha256": numerics_sha256,
    }


def _percentile(values: list[float], probability: float) -> float:
    _require(bool(values), "percentile population is empty")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _weighted_mean(values: list[float], weights: list[float]) -> float:
    weighted_sum = math.fsum(
        value * weight for value, weight in zip(values, weights, strict=True)
    )
    return weighted_sum / math.fsum(weights)


def _weighted_rms(values: list[float], weights: list[float]) -> float:
    return math.sqrt(
        math.fsum(value * value * weight for value, weight in zip(values, weights, strict=True))
        / math.fsum(weights)
    )


def _weighted_percentile(values: list[float], weights: list[float], probability: float) -> float:
    ordered = sorted(zip(values, weights, strict=True))
    target = probability * math.fsum(weights)
    cumulative = 0.0
    for value, weight in ordered:
        cumulative += weight
        if cumulative >= target:
            return value
    return ordered[-1][0]


def project_state(row: dict[str, Any], distance_mm: float) -> dict[str, Any]:
    """Project one canonical state through a field-free +z drift."""
    _require(distance_mm >= 0.0, "field-free projection distance must be nonnegative")
    vz = float(row["velocity_z_m_s"])
    _require(vz > 0.0, f"particle {row['particle_id']} velocity_z_m_s must be positive")
    ratio_x = float(row["velocity_x_m_s"]) / vz
    ratio_y = float(row["velocity_y_m_s"]) / vz
    delta_time_us = distance_mm * 1000.0 / vz
    x = float(row["position_x_mm"]) + ratio_x * distance_mm
    y = float(row["position_y_mm"]) + ratio_y * distance_mm
    transverse_speed = math.hypot(
        float(row["velocity_x_m_s"]), float(row["velocity_y_m_s"])
    )
    return {
        "particle_id": row["particle_id"],
        "particle_weight": float(row["particle_weight"]),
        "radius_mm": math.hypot(x, y),
        "angular_divergence_mrad": 1000.0 * math.atan2(transverse_speed, vz),
        "kinetic_energy_eV": float(row["kinetic_energy_eV"]),
        "component_tof_us": float(row["last_component_elapsed_time_us"]) + delta_time_us,
    }


def _population_metrics(states: dict[int, dict[str, Any]]) -> dict[str, float]:
    values = list(states.values())
    weights = [item["particle_weight"] for item in values]
    radii = [item["radius_mm"] for item in values]
    angles = [abs(item["angular_divergence_mrad"]) for item in values]
    energies = [item["kinetic_energy_eV"] for item in values]
    times = [item["component_tof_us"] for item in values]
    return {
        "rms_radius_mm": _weighted_rms(radii, weights),
        "p95_radius_mm": _weighted_percentile(radii, weights, 0.95),
        "rms_angular_divergence_mrad": _weighted_rms(angles, weights),
        "p95_absolute_angular_divergence_mrad": _weighted_percentile(
            angles, weights, 0.95
        ),
        "mean_kinetic_energy_eV": _weighted_mean(energies, weights),
        "p95_kinetic_energy_eV": _weighted_percentile(energies, weights, 0.95),
        "mean_component_tof_us": _weighted_mean(times, weights),
        "p95_component_tof_us": _weighted_percentile(times, weights, 0.95),
    }


def _bootstrap_seed(base_seed: int, identity: str) -> int:
    digest = hashlib.sha256(f"{base_seed}:{identity}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _paired_bootstrap_ci(
    differences: list[float],
    weights: list[float],
    resamples: int,
    seed: int,
    identity: str,
) -> list[float]:
    rng = random.Random(_bootstrap_seed(seed, identity))
    count = len(differences)
    estimates = []
    for _ in range(resamples):
        selected = [rng.randrange(count) for _ in range(count)]
        selected_values = [differences[index] for index in selected]
        selected_weights = [weights[index] for index in selected]
        estimates.append(_weighted_mean(selected_values, selected_weights))
    return [_percentile(estimates, 0.025), _percentile(estimates, 0.975)]


def _paired_summary(
    left: dict[int, dict[str, Any]],
    right: dict[int, dict[str, Any]],
    resamples: int,
    seed: int,
    identity: str,
) -> dict[str, Any]:
    common_ids = sorted(set(left) & set(right))
    if not common_ids:
        return {
            "common_survivor_ids": [],
            "continuous_metrics_status": "UNAVAILABLE_NO_COMMON_SURVIVORS",
            "continuous_metrics": None,
        }
    metrics: dict[str, Any] = {}
    weights = [left[item]["particle_weight"] for item in common_ids]
    for metric in CONTINUOUS_METRICS:
        differences = [left[item][metric] - right[item][metric] for item in common_ids]
        metrics[metric] = {
            "mean_difference": _weighted_mean(differences, weights),
            "rms_difference": _weighted_rms(differences, weights),
            "p95_absolute_difference": _weighted_percentile(
                [abs(value) for value in differences], weights, 0.95
            ),
            "paired_bootstrap_95_percent_interval": _paired_bootstrap_ci(
                differences, weights, resamples, seed, f"{identity}:{metric}"
            ),
        }
    return {
        "common_survivor_ids": common_ids,
        "continuous_metrics_status": "AVAILABLE",
        "continuous_metrics": metrics,
    }


def analyze_experiment(binding_path: Path) -> dict[str, Any]:
    """Validate all frozen inputs and return unqualified three-mode diagnostics."""
    contract = load_json(CONTRACT_PATH)
    _validate_method_contract(contract)
    binding = load_json(binding_path)
    resolved = _validate_binding(binding, binding_path, contract)
    source_path = (
        resolved["n100_path"] if resolved["count"] == 100 else resolved["n1000_path"]
    )
    source_rows = _load_rows(source_path)
    source_ids = [row["particle_id"] for row in source_rows]
    _require(
        source_ids == list(range(1, resolved["count"] + 1)),
        "selected source particle IDs must be contiguous, ordered and one-based",
    )
    source_by_id = {row["particle_id"]: row for row in source_rows}
    source_weight = math.fsum(float(row["particle_weight"]) for row in source_rows)

    observations = {
        "handoff": 0.0,
        "near_interface": resolved["near_interface_offset_mm"],
        "field_free_plus_5mm": 5.0,
        "field_free_plus_20mm": 20.0,
        "field_free_plus_50mm": 50.0,
    }
    mode_results: dict[str, Any] = {}
    projected_by_mode: dict[str, dict[str, dict[int, dict[str, Any]]]] = {}
    for mode_binding in binding["modes"]:
        mode_id = mode_binding["mode_id"]
        state_path = _resolve_path(binding_path, mode_binding["handoff_state"]["path"])
        _validate_source(
            state_path,
            mode_binding["handoff_state"]["sha256"],
            f"{mode_id} handoff state",
        )
        rows = _load_rows(state_path)
        handoff: dict[int, dict[str, Any]] = {}
        for row in rows:
            particle_id = row["particle_id"]
            _require(particle_id in source_by_id, f"{mode_id} has an unknown particle ID")
            _require(
                row["state_event"] == binding["handoff_state_event"],
                f"{mode_id} state_event differs from handoff binding",
            )
            _require(
                row["frame_id"] == binding["frame_id"]
                and row["clock_epoch_id"] == binding["clock_epoch_id"],
                f"{mode_id} frame or clock differs",
            )
            _require(
                float(row["position_z_mm"]) == resolved["handoff_z_mm"],
                f"{mode_id} state is not on the canonical handoff plane",
            )
            source = source_by_id[particle_id]
            _require(
                (
                    row["species_id"],
                    row["mass_amu"],
                    row["charge_state"],
                    row["particle_weight"],
                )
                == (
                    source["species_id"],
                    source["mass_amu"],
                    source["charge_state"],
                    source["particle_weight"],
                ),
                f"{mode_id} particle identity or weight differs from source",
            )
            project_state(row, 0.0)
            handoff[particle_id] = row
        lost_ids = sorted(set(source_by_id) - set(handoff))
        projected = {
            observation_id: {
                particle_id: project_state(row, distance)
                for particle_id, row in handoff.items()
            }
            for observation_id, distance in observations.items()
        }
        projected_by_mode[mode_id] = projected
        transmitted_weight = math.fsum(
            float(row["particle_weight"]) for row in handoff.values()
        )
        mode_results[mode_id] = {
            "source_particles": resolved["count"],
            "transmitted_particles": len(handoff),
            "lost_particle_ids": lost_ids,
            "count_transmission": len(handoff) / resolved["count"],
            "weighted_transmission": transmitted_weight / source_weight,
            "observations": {
                observation_id: _population_metrics(states)
                for observation_id, states in projected.items()
            },
        }

    comparisons: dict[str, Any] = {}
    bootstrap = binding["bootstrap"]
    for comparison in contract["paired_comparisons"]:
        comparison_id = comparison["comparison_id"]
        left_id = comparison["left_mode"]
        right_id = comparison["right_mode"]
        observations_result = {
            observation_id: _paired_summary(
                projected_by_mode[left_id][observation_id],
                projected_by_mode[right_id][observation_id],
                bootstrap["resamples"],
                bootstrap["seed"],
                f"{comparison_id}:{observation_id}",
            )
            for observation_id in observations
        }
        comparisons[comparison_id] = {
            "left_mode": left_id,
            "right_mode": right_id,
            "full_source_transmission_difference": (
                mode_results[left_id]["count_transmission"]
                - mode_results[right_id]["count_transmission"]
            ),
            "observations": observations_result,
        }

    return {
        "schema_version": 1,
        "role": "multipole_three_mode_dispersion_analysis",
        "status": "UNQUALIFIED_ANALYSIS_ONLY",
        "project_id": binding["project_id"],
        "solver_id": binding["solver_id"],
        "analysis_particle_count": resolved["count"],
        "geometry_invariant_sha256": resolved["geometry_invariant_sha256"],
        "solver_numerics_sha256": resolved["solver_numerics_sha256"],
        "source_family": binding["source_family"],
        "retention_class": "compact",
        "mode_results": mode_results,
        "paired_comparisons": comparisons,
        "bootstrap": {
            **bootstrap,
            "confidence_level": 0.95,
            "paired_resampling_unit": "particle_id",
        },
        "qualification_bindings": binding["qualification_bindings"],
        "engineering_stop_policy": contract["engineering_stop_policy"],
        "claim_limit": contract["claim_limit"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = analyze_experiment(args.binding)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        "THREE_MODE_DISPERSION=PASS "
        f"STATUS={result['status']} N={result['analysis_particle_count']}"
    )


if __name__ == "__main__":
    main()
