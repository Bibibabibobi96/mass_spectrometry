"""Prepare one campaign-declared multipole-to-oaTOF execution."""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from common.contracts.artifact_naming import validate_run_id
from common.contracts.component_particle_state import (
    validate_component_particle_state_csv,
)
from common.contracts.file_identity import file_sha256, repository_text_sha256
from common.contracts.machine_contracts import ContractError, validate_schema
from common.contracts.particle_count_policy import validate_standard_particle_count
from common.contracts.particle_physics import kinetic_energy_ev
from common.contracts.verify_run_manifest import record_path, verify_record
from common.integration.adapter_contract import (
    load_execution_adapter_registry,
    resolve_execution_mapping,
)
from common.integration.resolve_connection import (
    derive_direct_mating_translation,
    load_connection_profile_registry,
    verify_composition_plan,
    write_resolved_and_plan,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.materialize_simion_grid2_state import (
    materialize as materialize_legacy_grid2_state,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.register_pulse_resolution_result import (
    validate_frozen_baseline_evidence,
)
from common.multipole.component_port import build_exit_component_port
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.resolved_region_field import (
    FULL_ID,
    build_resolved_region_field_contract,
    canonical_profile_id,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.resolved_population import (
    compile_resolved_population_contract,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.ordered_pre_pulse_subset import (
    materialize_ordered_pre_pulse_subset,
    ordered_subset_source_particle_ids,
    validate_ordered_pre_pulse_subset,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.observed_pre_pulse_projection import (
    ARM_AFFINE_FIXED_10EV,
    ARM_COLLAPSED,
    ARM_FULL,
    ARM_OBSERVED_FIXED_10EV,
    project_observed_pre_pulse_states,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_layout import (
    compile_geometry_and_port,
    derive_pulse_schedule,
    select_profile,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source import (
    materialize_ideal_linear_source,
    materialize_pre_pulse_restart,
    resolve_source_materialization_profile,
)


INTEGRATION_ID = (
    "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
)
UPSTREAM_PROJECTS = {
    "rf_quadrupole_ion_optics",
    "rf_hexapole_ion_optics",
    "rf_octupole_ion_optics",
}

def validate_full_domain_affine_width_numerics_campaign(
    campaign: dict[str, Any], single_flight: dict[str, Any], policy: dict[str, Any],
    root: Path,
) -> None:
    """Fail closed on the pending Stage-B five-cell matrix."""

    if campaign.get("campaign_id") not in {
        "canonical_long_affine_arm8_width_numerics_n1000",
        "canonical_long_affine_arm8_width_numerics_restart_n1000",
        "canonical_long_full_domain_restart_affine_width_numerics_n1000_v3_successor",
    }:
        return

    rows = [
        row for row in campaign["experiments"]
        if canonical_profile_id(
            row.get("single_flight_accelerator_field_profile_id", "accelerator_real_pa")
        ) == FULL_ID
    ]
    if not rows:
        return
    if len(rows) != len(campaign["experiments"]):
        raise ContractError("full-domain ideal rows cannot be mixed with another campaign")
    observed = {
        (
            row.get("single_flight_source_materialization_profile_id"),
            row.get("single_flight_trajectory_quality_profile_id"),
            row.get("single_flight_time_integration_profile_id"),
        )
        for row in rows
    }
    expected = {
        ("canonical_ideal_linear_z_vz_1mm_n1000", "tqual_8", "dt160"),
        ("canonical_ideal_linear_z_vz_1p5mm_n1000", "tqual_8", "dt160"),
        ("canonical_ideal_linear_z_vz_2p2mm_n1000", "tqual_8", "dt160"),
        ("canonical_ideal_linear_z_vz_2p2mm_n1000", "tqual_8", "dt320"),
        ("canonical_ideal_linear_z_vz_2p2mm_n1000", "tqual_108", "dt160"),
    }
    if len(rows) != 5 or observed != expected:
        raise ContractError("full-domain affine width/numerics matrix differs")
    registration = campaign.get("preregistration")
    release_modes = {row.get("source_release_mode") for row in rows}
    if release_modes != {"pre_pulse_restart"}:
        if campaign.get("status") != "archived_invalid":
            raise ContractError("non-restart full-domain width campaign must remain archived")
    elif campaign.get("status") == "authorized":
        if registration is None:
            raise ContractError("authorized full-domain matrix requires preregistration")
        document = registration["document"]
        document_path = (root / document["path"]).resolve()
        if (
            not document_path.is_relative_to(root)
            or not document_path.is_file()
            or document_path.stat().st_size != int(document["bytes"])
            or file_sha256(document_path) != document["sha256"]
        ):
            raise ContractError("full-domain matrix preregistration document differs")
        row_hashes = {
            row["experiment_id"]: _canonical_sha256(row) for row in rows
        }
        if registration["frozen_experiment_row_sha256"] != row_hashes:
            raise ContractError("full-domain matrix preregistered row identities differ")
    elif campaign.get("status") != "PENDING_PREREGISTRATION":
        raise ContractError("full-domain matrix registration status differs")
    source_profiles = {
        item["profile_id"]: item
        for item in single_flight["source_materialization_profiles"]
    }
    expected_widths = {
        "canonical_ideal_linear_z_vz_1mm_n1000": 1.0,
        "canonical_ideal_linear_z_vz_1p5mm_n1000": 1.5,
        "canonical_ideal_linear_z_vz_2p2mm_n1000": 2.2,
    }
    for profile_id, width in expected_widths.items():
        profile = source_profiles.get(profile_id, {})
        if (
            int(profile.get("particle_count", 0)) != 1000
            or float(profile.get("source_full_width_mm", float("nan"))) != width
            or profile.get("phase_space_authority")
            != "config/accelerator_phase_space_match.json"
            or (profile.get("mass_amu"), profile.get("charge_state"),
                profile.get("kinetic_energy_eV")) != (100.0, 1, 10.0)
        ):
            raise ContractError("full-domain affine source authority differs")
    fixed = {
        "execution_strategy": "simion_single_flight",
        "single_flight_layout_profile_id": "symmetric_10ev_source_z22_finite_interval_theory",
        "single_flight_frontend_grid_profile_id": "frontend_isotropic_020_accelerator_overlay_z005",
        "single_flight_oatof_numerical_profile_id": "oatof_formal_mesh",
        "single_flight_accelerator_field_profile_id": FULL_ID,
        "architecture_generation_id": "finite_interval_2p2mm_matched_voltage_v1",
        "field_overlay_id": "accelerator_overlay_z005",
    }
    for row in rows:
        if any(row.get(key) != value for key, value in fixed.items()):
            raise ContractError("full-domain width/numerics fixed control differs")
        if campaign["schema_version"] >= 3:
            if row.get("single_flight_pulse_schedule_policy") != {
                "policy_id": "multipole_handoff_ballistic_centroid_v1",
                "offset_rf_periods": 0,
                "pulse_width_us": 1.0,
            }:
                raise ContractError("full-domain width/numerics pulse policy differs")
        elif row.get("single_flight_pulse_offset_rf_periods") != 0:
            raise ContractError("historical full-domain pulse offset differs")
        if row.get("source_profile_id") != row.get(
            "single_flight_source_materialization_profile_id"
        ):
            raise ContractError("full-domain width/numerics source identity differs")
    release_modes = {row.get("source_release_mode") for row in rows}
    if release_modes == {"continuous_frontend"}:
        if release_modes != {"continuous_frontend"} or any(
            row.get("pre_pulse_source_state") is not None for row in rows
        ):
            raise ContractError("archived continuous source path differs")
    else:
        if release_modes != {"pre_pulse_restart"}:
            raise ContractError("official full-domain source path must be pre-pulse restart")
        expected_restart_sources = {
            "canonical_ideal_linear_z_vz_1mm_n1000": (
                "22ADAC66F610064AD73E78FC9B17AB850A8FA59B3D6175EE0B5F10357FBC0539",
                "A59E16B3783DCDE7930070286C58D5BA6BA8DC0B9756DE61B410A07975672B5B",
            ),
            "canonical_ideal_linear_z_vz_1p5mm_n1000": (
                "2411F2BB62939E1CA74F627ABD567937C698848AB0E332A67784B0F2F8405624",
                "7A8FFC4D6E2A4D9B67560592B7401A72984137ACC8AE6F79388275DA494927C2",
            ),
            "canonical_ideal_linear_z_vz_2p2mm_n1000": (
                "75DF5222C32846CA16F7594404067020AEFD1CFCB2577FC8E86BF18A08493D4E",
                "7B1D722A9E73635938847EC31DEF0B45824098E1F44D4A7A1B036F6CF02392E6",
            ),
        }
        for row in rows:
            restart = row.get("pre_pulse_source_state", {})
            expected_source, expected_receipt = expected_restart_sources[
                row["single_flight_source_materialization_profile_id"]
            ]
            receipt = restart.get("materialization_receipt", {})
            if (
                restart.get("sha256") != expected_source
                or receipt.get("sha256") != expected_receipt
                or restart.get("particle_count") != 1000
                or restart.get("source_state_epoch") != "pulse_effective_time"
                or restart.get("postselection_prohibited") is not True
            ):
                raise ContractError("official full-domain restart source identity differs")
    grids = {
        item["profile_id"]: item for item in single_flight["frontend_grid_profiles"]
    }
    if int(grids[fixed["single_flight_frontend_grid_profile_id"]]["max_parallel_batches"]) != 3:
        raise ContractError(
            "full-domain width/numerics requires five batches dispatched as 3+2 waves"
        )
    if int(policy["stage_limits"]["single_flight_transport"][
        "minimum_system_available_memory_bytes"
    ]) != 4 * 1024**3:
        raise ContractError("full-domain width/numerics memory gate must be 4 GiB")


def validate_pulse_resolution_optimization_campaign(
    campaign: dict[str, Any], *, execution_requested: bool,
    experiment: dict[str, Any] | None = None,
) -> None:
    """Validate cross-field optimization semantics before any solver input is read."""
    contract = campaign.get("pulse_resolution_optimization")
    if contract is None:
        return
    matrix = contract["comparison_matrix"]
    experiments = {row["experiment_id"]: row for row in campaign["experiments"]}
    if len(matrix) != len(experiments):
        raise ContractError("pulse-resolution comparison matrix must match campaign rows")
    for row in matrix:
        experiment_row = experiments.get(row["experiment_id"])
        if (
            experiment_row is None
            or row["sequence"] != experiment_row["sequence"]
            or row["source_profile_id"] != experiment_row["source_profile_id"]
            or row["field_profile_id"]
            != experiment_row["single_flight_accelerator_field_profile_id"]
        ):
            raise ContractError("pulse-resolution direct comparison matrix differs")
    execution_modes = {
        row.get("pulse_resolution_execution_mode") for row in experiments.values()
    }
    if None in execution_modes or len(execution_modes) != 1:
        raise ContractError("pulse-resolution campaign must use one execution mode")
    if campaign.get("status") == "authorized" and "preregistration" in campaign:
        registration = campaign["preregistration"]
        frozen_rows = registration["frozen_experiment_row_sha256"]
        if set(frozen_rows) != set(experiments) or any(
            frozen_rows[experiment_id] != _canonical_sha256(experiment_row)
            for experiment_id, experiment_row in experiments.items()
        ):
            raise ContractError("authorized candidate experiment row SHA differs")
    if execution_requested:
        if campaign.get("status") != "authorized":
            raise ContractError("pending pulse-resolution campaign cannot execute")
        if experiment is None:
            raise ContractError("pulse-resolution execution requires a selected row")
        if experiment.get("execution_strategy") != "simion_single_flight":
            raise ContractError("pulse-resolution N=100 experiment is not executable")


SCREENING_SOURCE_COLUMNS = [
    "particle_id", "birth_time_s", "x_mm", "y_mm", "z_mm",
    "vx_m_s", "vy_m_s", "vz_m_s", "mass_amu", "charge_state",
]


def write_pulse_resolution_screening_prefix(
    source_path: Path, output_path: Path, *, ordered_particle_ids: list[int],
) -> str:
    """Write the deterministic governed mother-sample prefix with no sampling."""
    with source_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows, columns = list(reader), reader.fieldnames
    if columns != SCREENING_SOURCE_COLUMNS or not rows:
        raise ContractError("pulse-resolution mother source is not canonical")
    mother_ids = [int(row["particle_id"]) for row in rows]
    if mother_ids != list(range(1, len(rows) + 1)):
        raise ContractError("pulse-resolution mother-source IDs must be contiguous")
    if not ordered_particle_ids or ordered_particle_ids != mother_ids[:len(ordered_particle_ids)]:
        raise ContractError("pulse-resolution frozen source cohort is not the mother prefix")
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCREENING_SOURCE_COLUMNS,
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows[:len(ordered_particle_ids)])
    return file_sha256(output_path)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ContractError(f"JSON object required: {path}")
    return value


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def _validate_three_zone_gate_pair(
    gated: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate one N=1 producer/N=100 consumer pair."""

    if len(gated) != 2:
        raise ContractError("each three-zone solver gate requires exactly two rows")
    producers = [
        row for row in gated
        if row["three_zone_solver_gate"]["stage"] == "n1_smoke_producer"
    ]
    consumers = [
        row for row in gated
        if row["three_zone_solver_gate"]["stage"] == "n100_solver_authorized_consumer"
    ]
    if len(producers) != 1 or len(consumers) != 1:
        raise ContractError("three-zone solver gate requires one producer and one consumer")
    producer, consumer = producers[0], consumers[0]
    for row in (producer, consumer):
        try:
            validate_run_id(str(row.get("run_id", "")))
        except (TypeError, ValueError) as exc:
            raise ContractError("three-zone solver gate run_id is invalid") from exc
    if consumer["three_zone_solver_gate"].get("predecessor_experiment_id") != producer["experiment_id"]:
        raise ContractError("three-zone N=100 predecessor does not identify the N=1 row")
    realization = (
        producer.get("single_flight_layout_profile_id"),
        producer.get("architecture_generation_id"),
        consumer.get("generated_pre_pulse_ordered_subset", {}).get("selection_id"),
    )
    supported_realizations = {
        (
            "three_zone_t5_primary_v1",
            "three_zone_t5_frozen_primary_v1",
            "n100_file_order_source_ids_1_to_100_v1",
        ),
        (
            "three_zone_t5_primary_shaping_rings_1p4_v1",
            "three_zone_t5_frozen_primary_shaping_rings_1p4_v1",
            "n100_uniform_full_width_source_ids_1_to_1000_v1",
        ),
    }
    if realization not in supported_realizations:
        raise ContractError(
            "three-zone solver gate layout, architecture, or N=100 selection differs"
        )
    layout_profile_id, architecture_generation_id, n100_selection_id = realization
    expected = (
        (
            producer,
            1,
            "n1_center_source_id_500_v1",
            "080A9ED428559EF602668B4C00F114F1A11C3F6B02A435F0BDC154578E4D7F22",
        ),
        (
            consumer,
            100,
            n100_selection_id,
            "F9E2DBDE0AE4640704FB66EE02C101CF84ABE35137363D62647622606DF61279",
        ),
    )
    for row, count, selection_id, ordered_id_sha256 in expected:
        execution_population = row.get("single_flight_population", {}).get(
            "execution_population", {}
        )
        actual_count = execution_population.get("particle_count")
        actual_selection = row.get("generated_pre_pulse_ordered_subset", {}).get(
            "selection_id"
        )
        if (
            actual_count != count
            or actual_selection != selection_id
            or execution_population.get("ordered_particle_id_sha256")
            != ordered_id_sha256
        ):
            raise ContractError("three-zone solver gate population or ordered selection differs")
        required_identity = {
            "execution_strategy": "simion_single_flight",
            "single_flight_layout_profile_id": layout_profile_id,
            "architecture_generation_id": architecture_generation_id,
            "single_flight_accelerator_field_profile_id":
                "accelerator_real_three_zone_pa_real_reflectron",
            "source_release_mode": "pre_pulse_restart",
        }
        if any(row.get(key) != value for key, value in required_identity.items()):
            raise ContractError("three-zone solver gate execution identity is not the real-PA path")
        required_keys = (
            "single_flight_three_zone_candidate", "architecture_generation_id",
            "single_flight_source_materialization_profile_id", "source_profile_id",
            "single_flight_frontend_grid_profile_id",
            "single_flight_oatof_numerical_profile_id",
            "single_flight_trajectory_quality_profile_id",
            "single_flight_time_integration_profile_id", "single_flight_pa_cache_policy",
            "connection_profile_id", "field_overlay_id",
        )
        if any(key not in row for key in required_keys):
            raise ContractError("three-zone solver gate scientific identity is incomplete")

    def comparable(row: dict[str, Any]) -> dict[str, Any]:
        value = copy.deepcopy(row)
        for key in (
            "sequence", "experiment_id", "run_id", "three_zone_solver_gate",
            "generated_pre_pulse_ordered_subset",
        ):
            value.pop(key, None)
        population = value.get("single_flight_population", {})
        execution_population = population.get("execution_population", {})
        execution_population.pop("particle_count", None)
        execution_population.pop("ordered_particle_id_sha256", None)
        denominators = population.get("denominators", {})
        denominators.pop("population_count", None)
        denominators.pop("eligible_population_count", None)
        return value

    if comparable(producer) != comparable(consumer):
        raise ContractError("three-zone solver gate rows differ beyond population and run identity")
    return producer, consumer


def _three_zone_gate_pairs(
    campaign: dict[str, Any],
) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    """Validate and return every schema-v6 pair grouped by solver gate ID."""

    gated = [row for row in campaign["experiments"] if "three_zone_solver_gate" in row]
    if not gated:
        return {}
    if campaign["schema_version"] != 6:
        raise ContractError("three-zone solver gates require a schema-v6 campaign")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in gated:
        gate_id = row["three_zone_solver_gate"]["gate_id"]
        grouped.setdefault(gate_id, []).append(row)
    pairs = {
        gate_id: _validate_three_zone_gate_pair(rows)
        for gate_id, rows in grouped.items()
    }
    observed_pairs = [
        pair
        for pair in pairs.values()
        if "observed_pre_pulse_projection" in pair[0]
    ]
    if not observed_pairs:
        return pairs
    observed_arms = {
        pair[0]["observed_pre_pulse_projection"]["arm_id"]
        for pair in observed_pairs
    }
    valid_arm_sets = (
        {
            "affine_zvz_fixed_10eV_transverse_collapsed",
            "observed_zvz_fixed_10eV_transverse_collapsed",
        },
        {
            "full_observed_6d",
            "observed_z_vz_energy_transverse_collapsed",
        },
    )
    if len(observed_pairs) != len(observed_arms) or observed_arms not in valid_arm_sets:
        raise ContractError(
            "observed source projection requires one unique complete A/B or legacy C/D arm set"
        )

    def cross_arm_comparable(row: dict[str, Any]) -> dict[str, Any]:
        value = copy.deepcopy(row)
        for key in ("sequence", "experiment_id", "run_id", "three_zone_solver_gate"):
            value.pop(key, None)
        value["observed_pre_pulse_projection"].pop("arm_id")
        return value

    reference_pair = observed_pairs[0]
    if any(
        cross_arm_comparable(reference) != cross_arm_comparable(candidate)
        for candidate_pair in observed_pairs[1:]
        for reference, candidate in zip(reference_pair, candidate_pair, strict=True)
    ):
        raise ContractError(
            "observed source projection arms differ beyond arm and run identity"
        )
    return pairs


def _resolve_three_zone_n1_authorization(
    *, workspace: Path, campaign: dict[str, Any], campaign_path: Path,
    producer: dict[str, Any], consumer: dict[str, Any],
    source_identity: dict[str, Any], layout_profile: dict[str, Any],
    selected_field_profile: dict[str, Any],
    resolved_region_field_contract: dict[str, Any],
) -> dict[str, str]:
    """Load and close the producer parent manifest and PASS authorization receipt."""

    manifest_path = (
        workspace / "artifacts" / "projects" / INTEGRATION_ID / "runs"
        / producer["run_id"] / "run_manifest.json"
    ).resolve()
    if not manifest_path.is_file():
        raise ContractError("three-zone N=1 producer parent manifest is missing")
    manifest = _load(manifest_path)
    expected_manifest = {
        "role": "simulation_run_manifest", "status": "success",
        "run_id": producer["run_id"], "project": INTEGRATION_ID,
        "mode": "multipole_family_source_closure",
    }
    if (
        any(manifest.get(key) != value for key, value in expected_manifest.items())
        or manifest.get("formal_eligible") is not False
    ):
        raise ContractError("three-zone N=1 producer parent manifest identity differs")
    try:
        verify_record("run_config", manifest["run_config"], base_dir=manifest_path.parent)
        for name, record in manifest.get("inputs", {}).items():
            verify_record(f"input {name}", record, base_dir=manifest_path.parent)
        for index, record in enumerate(manifest.get("outputs", []), start=1):
            verify_record(f"output {index}", record, base_dir=manifest_path.parent)
    except (AssertionError, KeyError, TypeError) as exc:
        raise ContractError("three-zone N=1 producer parent manifest verification failed") from exc
    matches: list[tuple[Path, dict[str, Any]]] = []
    for record in manifest.get("outputs", []):
        path = record_path(record, base_dir=manifest_path.parent)
        if path.suffix.lower() != ".json":
            continue
        value = _load(path)
        if value.get("role") == "rf_oatof_three_zone_n1_solver_authorization_receipt":
            matches.append((path, value))
    if len(matches) != 1:
        raise ContractError("producer parent must contain one three-zone N=1 authorization receipt")
    receipt_path, receipt = matches[0]
    validate_schema(
        receipt, "rf_oatof_three_zone_n1_solver_authorization_receipt.schema.json"
    )
    expected_identities = {
        "candidate_sha256": consumer["single_flight_three_zone_candidate"]["sha256"],
        "layout_profile_id": consumer["single_flight_layout_profile_id"],
        "architecture_generation_id": consumer["architecture_generation_id"],
        "topology_id": layout_profile["topology_id"],
        "geometry_id": layout_profile["geometry_id"],
        "frontend_electrode_topology_id": layout_profile["frontend_electrode_topology_id"],
        "accelerator_field_profile_id": consumer["single_flight_accelerator_field_profile_id"],
        "field_id": selected_field_profile["field_id"],
        "resolved_region_field_semantic_sha256": resolved_region_field_contract["semantic_sha256"],
        "source_identity_sha256": _canonical_sha256(source_identity),
    }
    if (
        receipt.get("gate_id") != producer["three_zone_solver_gate"]["gate_id"]
        or receipt.get("decision") != "PASS"
        or receipt.get("authorization_status") != "N100_SOLVER_AUTHORIZED"
        or receipt.get("campaign") != {
            "campaign_id": campaign["campaign_id"],
            "campaign_sha256": repository_text_sha256(campaign_path),
        }
        or receipt.get("producer", {}).get("experiment_id") != producer["experiment_id"]
        or receipt.get("producer", {}).get("experiment_row_sha256") != _canonical_sha256(producer)
        or receipt.get("producer", {}).get("integration_run_id") != producer["run_id"]
        or receipt.get("authorized_successor") != {
            "experiment_id": consumer["experiment_id"],
            "experiment_row_sha256": _canonical_sha256(consumer),
            "particle_count": 100,
        }
        or receipt.get("identities") != expected_identities
    ):
        raise ContractError("three-zone N=1 authorization receipt identity or decision differs")
    return {
        "three_zone_n1_authorization_receipt_path": _workspace_relative(receipt_path, workspace),
        "three_zone_n1_authorization_receipt_sha256": file_sha256(receipt_path),
        "three_zone_n1_producer_parent_manifest_path": _workspace_relative(manifest_path, workspace),
        "three_zone_n1_producer_parent_manifest_sha256": file_sha256(manifest_path),
        "three_zone_source_identity_sha256": _canonical_sha256(source_identity),
    }


def _pulse_resolution_cohort_policy(experiment: dict[str, Any]) -> str:
    """Derive cohort handling from the existing execution-mode authority."""

    mode = experiment["pulse_resolution_execution_mode"]
    if mode == "screening_prefix_n100_baseline_registration":
        return "establish_observed_authority"
    if mode == "screening_prefix_n100_paired_candidate":
        return "require_frozen_baseline_authority"
    raise ContractError(f"unsupported pulse-resolution execution mode: {mode}")


def _resolve_pulse_resolution_historical_reference(
    root: Path, campaign: dict[str, Any]
) -> dict[str, Any]:
    """Validate the old checkpoint as migration evidence, not current authority."""

    declaration = campaign["pulse_resolution_cohort_authority"]
    if declaration["role"] != "rf_oatof_historical_migration_reference":
        raise ContractError("baseline cohort declaration is not historical evidence")
    checkpoint_record = declaration["checkpoint"]
    checkpoint_path = root.parent / checkpoint_record["path"]
    if (
        not checkpoint_path.is_file()
        or file_sha256(checkpoint_path) != checkpoint_record["sha256"]
    ):
        raise ContractError("pulse-resolution cohort checkpoint identity differs")
    with checkpoint_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    source_ids = sorted({
        int(row["particle_id"]) for row in rows if row["event"] == "source_release"
    })
    if _canonical_sha256(source_ids) != declaration["source_release"][
        "ordered_particle_id_sha256"
    ]:
        raise ContractError("historical source-release identity differs")
    return {
        "role": declaration["role"],
        "checkpoint": checkpoint_record,
        "source_release": {
            "selector": declaration["source_release"]["selector"],
            "ordered_particle_ids": source_ids,
            "ordered_particle_id_sha256": declaration["source_release"][
                "ordered_particle_id_sha256"
            ],
        },
    }


def _resolve_fixed_pulse_schedule(
    *, root: Path, campaign: dict[str, Any], experiment: dict[str, Any],
    experiment_id: str, experiment_row_sha256: str,
    population_declaration_sha256: str, policy: dict[str, Any],
) -> dict[str, Any]:
    """Bind a successor schedule to the frozen historical schedule and receipt."""

    authority = policy["fixed_execution_authority"]
    if authority["authority_mode"] != "frozen_historical_schedule_v1":
        raise ContractError("fixed pulse execution authority mode is unsupported")

    def load_bound_file(record: dict[str, str]) -> dict[str, Any]:
        path = root.parent / record["path"]
        if not path.is_file() or file_sha256(path) != record["sha256"]:
            raise ContractError(f"fixed pulse authority identity differs: {record['path']}")
        return _load(path)

    source_schedule = load_bound_file(authority["source_schedule"])
    source = experiment["source"]
    execution_population = experiment["single_flight_population"]["execution_population"]
    if (
        execution_population["ordered_particle_id_sha256"]
        != campaign["pulse_resolution_cohort_authority"]["source_release"][
            "ordered_particle_id_sha256"
        ]
        or source["state"]["sha256"] != authority["source_state_sha256"]
    ):
        raise ContractError("fixed pulse source/cohort identity differs")

    expected_schedule_fields = {
        "method": policy["policy_id"],
        "source_state_sha256": authority["source_state_sha256"],
        "pulse_base_time_us": authority["pulse_effective_time_us"],
        "pulse_offset_rf_periods": policy["offset_rf_periods"],
        "pulse_offset_us": 0.0,
        "pulse_effective_time_us": authority["pulse_effective_time_us"],
        "pulse_width_us": policy["pulse_width_us"],
    }
    observed_schedule_fields = {
        "method": source_schedule["method"],
        "source_state_sha256": source_schedule["source_state_sha256"],
        "pulse_base_time_us": source_schedule["base_derived_pulse_time_us"],
        "pulse_offset_rf_periods": source_schedule["pulse_offset_rf_periods"],
        "pulse_offset_us": source_schedule["pulse_offset_us"],
        "pulse_effective_time_us": source_schedule["derived_pulse_time_us"],
        "pulse_width_us": source_schedule["pulse_width_us"],
    }
    if observed_schedule_fields != expected_schedule_fields:
        raise ContractError("fixed pulse source schedule fields differ from successor contract")

    schedule = {
        "schema_version": 1,
        "role": "rf_oatof_resolved_single_flight_pulse_schedule",
        "campaign_id": campaign["campaign_id"],
        "experiment_id": experiment_id,
        "experiment_row_sha256": experiment_row_sha256,
        "population_declaration_sha256": population_declaration_sha256,
        "policy": {key: policy[key] for key in ("policy_id", "offset_rf_periods", "pulse_width_us")},
        "rf_period_us": authority["rf_period_us"],
        "pulse_base_time_us": authority["pulse_effective_time_us"],
        "pulse_offset_us": 0.0,
        "pulse_effective_time_us": authority["pulse_effective_time_us"],
        "pulse_width_us": policy["pulse_width_us"],
    }
    for key in (
        "layout_profile_id", "method", "source_state_sha256", "population_counts",
        "selected_particle_ids", "mean_entry_time_us", "mean_velocity_x_m_s",
        "mean_kinetic_energy_eV", "target_centroid_x_mm", "entry_surface_x_mm",
        "base_predicted_centroid_error_x_mm", "predicted_centroid_error_x_mm",
        "claim_status",
    ):
        schedule[key] = source_schedule[key]
    schedule["source_state_path"] = experiment["source"]["state"]["path"]
    return schedule


def _repo_record(root: Path, record: dict[str, str], label: str) -> Path:
    path = (root / record["path"]).resolve()
    if (
        not path.is_relative_to(root)
        or not path.is_file()
        or repository_text_sha256(path) != record["sha256"]
    ):
        raise ContractError(f"{label} is missing, stale or escapes the repository")
    return path


def _repo_byte_record(root: Path, record: dict[str, str], label: str) -> Path:
    path = (root / record["path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file() or (
        file_sha256(path) != record["sha256"]
    ):
        raise ContractError(f"{label} is missing, stale or escapes the repository")
    return path


def _workspace_path(workspace: Path, raw: str, label: str) -> Path:
    value = Path(raw)
    path = value.resolve() if value.is_absolute() else (workspace / value).resolve()
    artifacts = (workspace / "artifacts").resolve()
    if not path.is_relative_to(artifacts) or not path.is_file():
        raise ContractError(f"{label} is missing or escapes workspace artifacts")
    return path


def _workspace_record(
    workspace: Path, record: dict[str, str], label: str
) -> Path:
    path = _workspace_path(workspace, record["path"], label)
    if file_sha256(path) != record["sha256"]:
        raise ContractError(f"{label} SHA-256 is stale")
    return path


def _workspace_relative(path: Path, workspace: Path) -> str:
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError as exc:
        raise ContractError(f"path escapes the workspace: {path}") from exc


def _resolve_staged_loader_validation(
    root: Path,
    record: dict[str, str],
    source_sha256: str,
    source_rows: list[dict[str, str]],
) -> tuple[dict[str, Any], Path]:
    receipt_path = _repo_byte_record(
        root, record, "staged loader authorization budget"
    )
    receipt = _load(receipt_path)
    if receipt.get("schema_version") not in {1, 2}:
        raise ContractError("staged loader authorization schema version differs")
    if receipt["schema_version"] == 2:
        raw_evidence = receipt.get("raw_evidence", {})
        container = raw_evidence.get("container", {})
        expected_members = [
            {
                "name": "staged_grid2_n34_simion_fly2_loader_ab_characterization.json",
                "bytes": 623508,
                "sha256": "08E4C988D0D64C5B6D4EC50F64B74D3C439D06AFABCDAF07E57D66A74126E0E5",
            },
            {
                "name": "staged_grid2_n34_simion_fly2_loader_authorization_budget.json",
                "bytes": 311736,
                "sha256": "3C55554E41C9D016C3A2DEC8CB11DC1FFC1436FC843805D0E8987CDE32CDF1FE",
            },
        ]
        if (
            raw_evidence.get("role")
            != "rf_oatof_simion_fly2_loader_raw_receipt_evidence"
            or raw_evidence.get("producer_run_id")
            != "20260815_223500__migration__repo__staged-grid2-loader-receipt-compact-v2"
            or raw_evidence.get("retention_class") != "compact"
            or raw_evidence.get("runtime_decompression_required") is not False
            or container
            != {
                "path": "artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20260815_223500__migration__repo__staged-grid2-loader-receipt-compact-v2/results/staged_grid2_n34_simion_fly2_loader_raw_receipts.zip",
                "bytes": 53068,
                "sha256": "86DB4FB500C2C9EF1FDD32541CACD9A0D054D190D572B6CF5EAFE12C9C59C559",
                "format": "zip_deflate_fixed_metadata_v1",
            }
            or raw_evidence.get("members") != expected_members
        ):
            raise ContractError("staged loader compact raw-evidence descriptor differs")
        container_path = _workspace_record(
            root.parent,
            {"path": container.get("path"), "sha256": container.get("sha256")},
            "staged loader compact raw-evidence container",
        )
        if container_path.stat().st_size != container.get("bytes"):
            raise ContractError("staged loader compact raw-evidence bytes differ")
    identities = receipt.get("identities", {})
    scope = receipt.get("claim_scope", {})
    budget = receipt.get("authorized_budget", {})
    witness = receipt.get("n34_exact_vector_witness_gate", {})
    if (
        receipt.get("role") != "rf_oatof_simion_fly2_loader_authorization_budget"
        or receipt.get("status") != "PASS"
        or scope.get("representation") != "standard_beam_direct_velocity_vector"
        or scope.get("canonical_source_sha256") != source_sha256
        or scope.get("future_sources_or_renderers_authorized") is not False
        or scope.get("continuous_velocity_domain_authorized") is not False
        or {float(row["mass_amu"]) for row in source_rows}
        != {float(scope.get("mass_amu", -1))}
        or {int(row["charge_state"]) for row in source_rows}
        != {int(scope.get("charge_state", 0))}
        or witness.get("velocity_all_pass") is not True
        or witness.get("energy_all_pass") is not True
    ):
        raise ContractError("staged loader authorization scope or witness gate differs")
    identity_files = [
        ("selection_receipt_path", "selection_receipt_sha256", "selection receipt"),
        ("production_renderer_path", "production_renderer_sha256", "production renderer"),
    ]
    if receipt["schema_version"] == 1:
        identity_files.append(("harness_path", "harness_sha256", "loader harness"))
    elif (
        identities.get("harness_path")
        != "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/tests/verify_simion_fly2_loader_characterization.py"
        or identities.get("harness_sha256")
        != "827854E703F65135E8056D94F3B61AEF74E1FFC94EFEC65F31B30F6C85AA9A7E"
    ):
        raise ContractError("staged loader historical harness identity differs")
    for path_key, sha_key, label in identity_files:
        path = (root / identities[path_key]).resolve()
        if (
            not path.is_relative_to(root)
            or not path.is_file()
            or file_sha256(path) != identities[sha_key]
        ):
            raise ContractError(f"staged loader {label} identity differs")
    velocity = budget.get("velocity", {})
    energy = budget.get("derived_energy", {})
    if (
        velocity.get("authorized_relative_bound") != 2e-8
        or velocity.get("absolute_floor_m_per_s") != 0
        or velocity.get("zero_speed_must_be_exact") is not True
        or velocity.get("safety_factor") != 4
        or energy.get("authorized_relative_bound") != 3e-8
        or energy.get("absolute_floor_eV") != 0
        or energy.get("zero_energy_must_be_exact") is not True
        or energy.get("safety_factor") != 4
        or energy.get("authority")
        != "actual_velocity_plus_canonical_mass_common_function"
        or budget.get("native_ion_ke") != "diagnostic_only"
    ):
        raise ContractError("staged loader authorization budget differs")
    return ({
        "role": "rf_oatof_resolved_source_release_validation",
        "loader_authorization_budget": record,
        "representation": scope["representation"],
        "canonical_source_sha256": source_sha256,
        "solver_executable_sha256": identities["simion_executable_sha256"],
        "production_renderer_sha256": identities["production_renderer_sha256"],
        "identity_position_clock_policy": "ordered_id_row_map_position_clock_exact",
        "velocity": {
            "relative_bound": velocity["authorized_relative_bound"],
            "absolute_floor_m_per_s": 0,
            "zero_speed_must_be_exact": True,
        },
        "derived_energy": {
            "relative_bound": energy["authorized_relative_bound"],
            "absolute_floor_eV": 0,
            "zero_energy_must_be_exact": True,
            "authority": energy["authority"],
        },
        "native_ion_ke_role": "diagnostic_only",
    }, receipt_path)


def _population_source_table(
    path: Path,
    *,
    workspace: Path,
    input_role: str,
    table_binding: str,
) -> dict[str, Any]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or "particle_id" not in rows[0]:
        raise ContractError("population source table lacks particle identities")
    try:
        particle_ids = [int(row["particle_id"]) for row in rows]
    except (TypeError, ValueError) as exc:
        raise ContractError("population source particle identities are invalid") from exc
    if len(particle_ids) != len(set(particle_ids)):
        raise ContractError("population source particle identities are not unique")
    return {
        "input_role": input_role,
        "table_binding": table_binding,
        "table": {
            "path": _workspace_relative(path, workspace),
            "sha256": file_sha256(path),
        },
        "particle_count": len(particle_ids),
        "ordered_particle_ids": {
            "encoding": "canonical_compact_json_integer_array_v1",
            "sha256": _canonical_sha256(particle_ids),
        },
    }


def _validate_canonical_pulse_restart_state(
    source_path: Path,
    receipt_path: Path,
    source_record: dict[str, Any],
    profile: dict[str, Any],
    geometry: dict[str, Any],
    schedule: dict[str, Any],
) -> dict[str, Any]:
    receipt = _load(receipt_path)
    target = receipt.get("pulse_target_state", {})
    expected_locus = "accelerator_stage1_interior_fixed_transverse_finite_local_z_interval"
    if (
        receipt.get("profile_id") != profile["profile_id"]
        or target.get("sha256") != source_record["sha256"]
        or target.get("particle_count") != source_record["particle_count"]
        or target.get("source_state_epoch") != "pulse_effective_time"
        or target.get("source_state_locus", {}).get("kind") != expected_locus
        or target.get("coordinate_frame") != "oatof_global_cartesian"
        or target.get("clock_basis") != "canonical_instrument_time_us"
        or target.get("clock_authority") != "resolved_single_flight_pulse_schedule"
    ):
        raise ContractError("canonical pulse restart receipt identity differs")
    pulse_time_us = float(schedule["pulse_effective_time_us"])
    subset_source_ids = None
    if receipt.get("role") == "rf_oatof_pre_pulse_ordered_subset_receipt":
        validate_schema(
            receipt, "rf_oatof_pre_pulse_ordered_subset_receipt.schema.json"
        )
        mother = receipt["mother_pulse_target_state"]
        mother_source_path = (
            receipt_path.parent / mother["path"]
        ).resolve()
        mother_receipt_path = (
            receipt_path.parent / mother["materialization_receipt"]["path"]
        ).resolve()
        if (
            not mother_source_path.is_relative_to(receipt_path.parent.resolve())
            or not mother_receipt_path.is_relative_to(receipt_path.parent.resolve())
            or not mother_source_path.is_file()
            or not mother_receipt_path.is_file()
        ):
            raise ContractError("ordered subset mother files are unavailable")
        try:
            normalized_rows = validate_ordered_pre_pulse_subset(
                source_path,
                receipt,
                mother_source_path,
                mother_receipt_path,
                pulse_time_us=pulse_time_us,
            )
        except (KeyError, OSError, TypeError, ValueError) as exc:
            raise ContractError("ordered pre-pulse subset validation failed") from exc
        subset_source_ids = receipt["selection"]["ordered_source_particle_ids"]
        if int(profile["particle_count"]) != mother["particle_count"]:
            raise ContractError("ordered subset mother population differs from profile")
    else:
        _, normalized_rows = materialize_pre_pulse_restart(
            source_path, pulse_time_us
        )
    count = len(normalized_rows)
    if (
        target.get("particle_count") != count
        or source_record["particle_count"] != count
    ):
        raise ContractError("canonical pulse restart population differs")
    ordered_ids = [int(row["particle_id"]) for row in normalized_rows]
    ordered_id_sha256 = _canonical_sha256(ordered_ids)
    if target.get("ordered_particle_id_sha256") != ordered_id_sha256:
        raise ContractError("canonical pulse restart ordered particle identity differs")
    particle_source = geometry["particle_source"]
    center_x = float(particle_source["center_x_mm"])
    center_y = float(particle_source["center_y_mm"])
    center_z = float(particle_source["center_z_mm"])
    width = float(profile["source_full_width_mm"])
    mean_vz = float(profile["mean_velocity_z_m_per_s"])
    slope = float(profile["velocity_z_slope_m_per_s_per_mm"])
    position_tolerance = float(source_record["position_rowwise_abs_tolerance_mm"])
    velocity_tolerance = float(source_record["velocity_rowwise_abs_tolerance_m_per_s"])
    maximum_position_error = 0.0
    maximum_velocity_error = 0.0
    maximum_clock_error = 0.0
    maximum_energy_error = 0.0
    for index, row in enumerate(normalized_rows):
        if subset_source_ids is None:
            expected_z = (
                center_z
                if count == 1
                else center_z - width / 2.0 + width * index / (count - 1)
            )
        else:
            mother_count = int(profile["particle_count"])
            expected_z = (
                center_z - width / 2.0
                + width * (subset_source_ids[index] - 1) / (mother_count - 1)
            )
        expected_vz = mean_vz + slope * (expected_z - center_z)
        maximum_position_error = max(
            maximum_position_error,
            abs(float(row["position_x_mm"]) - center_x),
            abs(float(row["position_y_mm"]) - center_y),
            abs(float(row["position_z_mm"]) - expected_z),
        )
        maximum_velocity_error = max(
            maximum_velocity_error,
            abs(float(row["velocity_z_m_s"]) - expected_vz),
        )
        maximum_clock_error = max(
            maximum_clock_error,
            abs(float(row["instrument_time_us"]) - pulse_time_us),
        )
        maximum_energy_error = max(
            maximum_energy_error,
            abs(
                kinetic_energy_ev(
                    float(row["mass_amu"]),
                    *(float(row[f"velocity_{axis}_m_s"]) for axis in "xyz"),
                ) - float(row["kinetic_energy_eV"])
            ),
        )
    if (
        maximum_position_error > position_tolerance
        or maximum_velocity_error > velocity_tolerance
        or maximum_clock_error > float(source_record["clock_abs_tolerance_us"])
        or maximum_energy_error > float(source_record["energy_abs_tolerance_eV"])
    ):
        raise ContractError("canonical pulse restart target-state validation failed")
    return {
        "schema_version": 1,
        "role": "canonical_pulse_restart_target_state_validation",
        "status": "PASS",
        "target_pulse_state_sha256": source_record["sha256"],
        "materialization_receipt_sha256": source_record["materialization_receipt"]["sha256"],
        "source_state_epoch": "pulse_effective_time",
        "source_state_locus": expected_locus,
        "coordinate_frame": "oatof_global_cartesian",
        "clock_basis": "canonical_instrument_time_us",
        "clock_authority": "resolved_single_flight_pulse_schedule",
        "ordered_particle_id_sha256": ordered_id_sha256,
        "particle_count": count,
        "tolerances": {
            "position_rowwise_abs_tolerance_mm": position_tolerance,
            "velocity_rowwise_abs_tolerance_m_per_s": velocity_tolerance,
            "clock_abs_tolerance_us": float(source_record["clock_abs_tolerance_us"]),
            "energy_abs_tolerance_eV": float(source_record["energy_abs_tolerance_eV"]),
        },
        "maximum_errors": {
            "position_rowwise_abs_mm": maximum_position_error,
            "velocity_rowwise_abs_m_per_s": maximum_velocity_error,
            "clock_abs_us": maximum_clock_error,
            "energy_abs_eV": maximum_energy_error,
        },
    }


def _validate_observed_pre_pulse_projection(
    *,
    receipt: dict[str, Any],
    receipt_path: Path,
    selected_arm: str,
    selected_path: Path,
    full_path: Path,
    collapsed_path: Path,
    affine_fixed_10ev_path: Path | None,
    observed_fixed_10ev_path: Path | None,
    current_target_path: Path,
    current_subset_receipt_path: Path,
    pulse_time_us: float,
    affine_authority: dict[str, float] | None,
    fixed_kinetic_energy_eV: float | None,
) -> dict[str, Any]:
    expected_invariants = {
        "full_observed_velocity_preserved": True,
        "full_observed_position_common_translation": True,
        "collapsed_z_vz_energy_clock_equal_full": True,
        "collapsed_x_y_equal_current_center": True,
        "collapsed_vy_zero": True,
        "collapsed_positive_vx_preserves_transverse_speed": True,
        "energy_recomputed_from_velocity": True,
    }
    four_arm = selected_arm in {ARM_AFFINE_FIXED_10EV, ARM_OBSERVED_FIXED_10EV}
    if four_arm:
        expected_invariants.update({
            "all_arms_observed_z_id_clock_equal": True,
            "affine_arm_vz_from_frozen_authority": True,
            "observed_fixed_arm_observed_vz_preserved": True,
            "fixed_10eV_arms_energy_equal": True,
            "fixed_10eV_arms_centered_xy_vy_zero_positive_vx": True,
        })
    if (
        receipt.get("role") != "rf_oatof_observed_pre_pulse_projection_receipt"
        or receipt.get("status") != "PASS"
        or receipt.get("invariants") != expected_invariants
        or selected_arm not in {
            ARM_AFFINE_FIXED_10EV, ARM_OBSERVED_FIXED_10EV,
            ARM_FULL, ARM_COLLAPSED,
        }
        or receipt.get("schema_version") != (2 if four_arm else 1)
    ):
        raise ContractError("observed pre-pulse projection receipt is invalid")
    expected_refs = {
        "current_target": current_target_path,
        "current_subset_receipt": current_subset_receipt_path,
    }
    for name, path in expected_refs.items():
        record = receipt.get("authorities", {}).get(name, {})
        if Path(str(record.get("path", ""))).resolve() != path.resolve() or record.get(
            "sha256"
        ) != file_sha256(path):
            raise ContractError(f"observed projection {name} authority differs")
    arm_paths = {ARM_FULL: full_path, ARM_COLLAPSED: collapsed_path}
    if four_arm:
        if affine_fixed_10ev_path is None or observed_fixed_10ev_path is None:
            raise ContractError("four-arm projection outputs are incomplete")
        arm_paths.update({
            ARM_AFFINE_FIXED_10EV: affine_fixed_10ev_path,
            ARM_OBSERVED_FIXED_10EV: observed_fixed_10ev_path,
        })
    for arm_id, path in arm_paths.items():
        record = receipt.get("arms", {}).get(arm_id, {})
        if Path(str(record.get("path", ""))).resolve() != path.resolve() or record.get(
            "sha256"
        ) != file_sha256(path):
            raise ContractError(f"observed projection {arm_id} output differs")
    rows_by_arm = {
        arm_id: materialize_pre_pulse_restart(path, pulse_time_us)[1]
        for arm_id, path in arm_paths.items()
    }
    full_rows = rows_by_arm[ARM_FULL]
    collapsed_rows = rows_by_arm[ARM_COLLAPSED]
    if (
        any(len(rows) != len(full_rows) for rows in rows_by_arm.values())
        or selected_path != arm_paths[selected_arm]
    ):
        raise ContractError("observed projection paired population differs")
    exact_paired_fields = (
        "particle_id", "instrument_time_us", "mass_amu", "charge_state",
        "position_z_mm", "velocity_z_m_s",
    )
    if any(
        any(full[field] != collapsed[field] for field in exact_paired_fields)
        for full, collapsed in zip(full_rows, collapsed_rows, strict=True)
    ):
        raise ContractError("observed projection longitudinal paired invariants differ")
    if any(
        abs(
            float(full["kinetic_energy_eV"])
            - float(collapsed["kinetic_energy_eV"])
        )
        > 5e-9
        for full, collapsed in zip(full_rows, collapsed_rows, strict=True)
    ):
        raise ContractError("observed projection paired energy differs")
    if four_arm:
        projection = receipt.get("projection", {})
        if (
            affine_authority is None
            or fixed_kinetic_energy_eV != 10.0
            or projection.get("method")
            != "observed_z_four_arm_energy_decomposition_v2"
            or projection.get("fixed_kinetic_energy_eV") != fixed_kinetic_energy_eV
            or projection.get("affine_authority") != affine_authority
        ):
            raise ContractError("four-arm affine or fixed-energy authority differs")
        shared_fields = (
            "particle_id", "instrument_time_us", "mass_amu", "charge_state",
            "position_z_mm",
        )
        reference_rows = rows_by_arm[ARM_FULL]
        if any(
            any(reference[field] != candidate[field] for field in shared_fields)
            for arm_id, rows in rows_by_arm.items()
            if arm_id != ARM_FULL
            for reference, candidate in zip(reference_rows, rows, strict=True)
        ):
            raise ContractError(
                "four-arm ID, clock, species, or observed-z invariant differs"
            )
        affine_rows = rows_by_arm[ARM_AFFINE_FIXED_10EV]
        observed_fixed_rows = rows_by_arm[ARM_OBSERVED_FIXED_10EV]
        current_center = projection["current_center_mm"]
        for affine, observed_fixed, collapsed, full in zip(
            affine_rows, observed_fixed_rows, collapsed_rows, full_rows, strict=True
        ):
            expected_affine_vz = (
                affine_authority["mean_velocity_z_m_per_s"]
                + affine_authority["velocity_z_slope_m_per_s_per_mm"]
                * (
                    float(affine["position_z_mm"])
                    - affine_authority["center_z_mm"]
                )
            )
            if (
                abs(float(affine["velocity_z_m_s"]) - expected_affine_vz) > 1e-9
                or observed_fixed["velocity_z_m_s"] != collapsed["velocity_z_m_s"]
                or collapsed["velocity_z_m_s"] != full["velocity_z_m_s"]
                or any(
                    abs(float(row["kinetic_energy_eV"]) - fixed_kinetic_energy_eV)
                    > 5e-9
                    for row in (affine, observed_fixed)
                )
                or any(
                    float(row["position_x_mm"]) != float(current_center[0])
                    or float(row["position_y_mm"]) != float(current_center[1])
                    or float(row["velocity_y_m_s"]) != 0.0
                    or float(row["velocity_x_m_s"]) <= 0.0
                    for row in (affine, observed_fixed)
                )
            ):
                raise ContractError("four-arm physical invariants differ")
    return {
        "schema_version": 1,
        "role": "canonical_pulse_restart_target_state_validation",
        "status": "PASS",
        "projection_arm_id": selected_arm,
        "target_pulse_state_sha256": file_sha256(selected_path),
        "materialization_receipt_sha256": file_sha256(receipt_path),
        "source_state_epoch": "pulse_effective_time",
        "source_state_locus": "accelerator_stage1_interior_finite_observed_3d_cloud",
        "particle_count": len(full_rows),
        "paired_longitudinal_state_preserved": True,
    }


def _unique_profile(document: dict[str, Any], profile_id: str) -> dict[str, Any]:
    matches = [
        item
        for item in document["profiles"]
        if item["connection_profile_id"] == profile_id
    ]
    if len(matches) != 1:
        raise ContractError(f"connection profile is not unique: {profile_id}")
    return matches[0]


def _source_solver(manifest: dict[str, Any]) -> str:
    software = " ".join(str(item).lower() for item in manifest.get("software", []))
    matches = [name for name in ("comsol", "simion") if name in software]
    if len(matches) != 1:
        raise ContractError("source manifest solver identity is not unique")
    return matches[0]


def _verify_manifest_record(
    workspace: Path,
    record: dict[str, Any],
    expected_path: Path,
    expected_sha256: str,
    label: str,
) -> None:
    if not record.get("exists"):
        raise ContractError(f"source manifest {label} record is absent")
    path = _workspace_path(workspace, str(record["path"]), label)
    if path != expected_path.resolve() or record["sha256"] != expected_sha256:
        raise ContractError(f"source manifest {label} identity differs")


def _load_source_evidence(
    *,
    workspace: Path,
    experiment: dict[str, Any],
    expected_project_id: str,
) -> dict[str, Any]:
    source = experiment["source"]
    launched_count = validate_standard_particle_count(
        int(source["launched_particle_count"])
    )
    selected_count = int(source["particle_count"])
    if selected_count > launched_count:
        raise ContractError("selected source particle count exceeds launched count")
    manifest_path = _workspace_record(workspace, source["manifest"], "source manifest")
    state_path = _workspace_record(workspace, source["state"], "source state")
    particle_source_path = _workspace_record(
        workspace, source["particle_source"], "source particle table"
    )
    metadata_path = _workspace_record(workspace, source["metadata"], "source metadata")
    manifest = _load(manifest_path)
    if (
        manifest.get("role") != "simulation_run_manifest"
        or manifest.get("status") != "success"
        or manifest.get("run_id") != source["run_id"]
        or manifest.get("project") != expected_project_id
        or expected_project_id not in UPSTREAM_PROJECTS
    ):
        raise ContractError("source manifest run/project/status identity differs")
    source_role = source["particle_source_manifest_input_role"]
    _verify_manifest_record(
        workspace,
        manifest.get("inputs", {}).get(source_role, {}),
        particle_source_path,
        source["particle_source"]["sha256"],
        "particle source",
    )
    _verify_manifest_record(
        workspace,
        manifest.get("inputs", {}).get("particle_source_metadata", {}),
        metadata_path,
        source["metadata"]["sha256"],
        "particle source metadata",
    )
    matching_states = [
        record
        for record in manifest.get("outputs", [])
        if record.get("sha256") == source["state"]["sha256"]
    ]
    if len(matching_states) != 1:
        raise ContractError("source state is not uniquely frozen by its manifest")
    _verify_manifest_record(
        workspace,
        matching_states[0],
        state_path,
        source["state"]["sha256"],
        "source state",
    )
    design_record = manifest.get("inputs", {}).get("multipole_resolved_design", {})
    design_path = _workspace_path(
        workspace, str(design_record.get("path", "")), "source resolved design"
    )
    if (
        not design_record.get("exists")
        or file_sha256(design_path) != design_record.get("sha256")
    ):
        raise ContractError("source resolved design is absent or stale")
    resolved_design = _load(design_path)
    validate_schema(resolved_design, "multipole_resolved_design.schema.json")
    run_config_record = manifest.get("run_config", {})
    run_config_path = _workspace_path(
        workspace, str(run_config_record.get("path", "")), "source run config"
    )
    if (
        not run_config_record.get("exists")
        or file_sha256(run_config_path) != run_config_record.get("sha256")
    ):
        raise ContractError("source run config is absent or stale")
    run_config = _load(run_config_path)
    design_profile_id = run_config.get("parameters", {}).get("design_profile_id")
    if (
        not isinstance(design_profile_id, str)
        or not design_profile_id
        or resolved_design["identity"]["project_id"] != expected_project_id
    ):
        raise ContractError("source design profile/project identity differs")
    terminal = resolved_design.get("downstream_terminal")
    if (
        not isinstance(terminal, dict)
        or terminal.get("terminal_profile_id") != "oatof_shield_terminal"
        or terminal.get("surface_role") != "aperture_outer_tangent_plane"
        or float(terminal.get("rod_end_clearance_mm", -1.0)) != 1.0
        or terminal.get("upstream_terminal_electrode_present") is not False
    ):
        raise ContractError("source design does not freeze the governed oaTOF terminal")
    return {
        "source": source,
        "manifest": manifest,
        "state_path": state_path,
        "solver_id": _source_solver(manifest),
        "resolved_design": resolved_design,
        "resolved_design_path": design_path,
        "resolved_design_sha256": design_record["sha256"],
        "design_profile_id": design_profile_id,
        "launched_particle_count": launched_count,
        "particle_count": selected_count,
    }


def prepare_family_source_closure(
    *,
    repo_root: Path,
    profile_registry_path: Path,
    adapter_registry_path: Path,
    campaign_path: Path,
    experiment_id: str,
    resolved_output: Path,
    plan_output: Path,
) -> tuple[Path, Path]:
    root = repo_root.resolve()
    workspace = root.parent
    campaign_path = campaign_path.resolve()
    if not campaign_path.is_relative_to(root):
        raise ContractError("integration campaign must be repository-managed")
    campaign = _load(campaign_path)
    validate_schema(campaign, "rf_multipole_oatof_experiment_campaign.schema.json")
    if campaign["integration_id"] != INTEGRATION_ID:
        raise ContractError("campaign integration identity differs")
    identities = [item["experiment_id"] for item in campaign["experiments"]]
    sequences = [item["sequence"] for item in campaign["experiments"]]
    if len(identities) != len(set(identities)) or len(sequences) != len(set(sequences)):
        raise ContractError("campaign experiment IDs and sequences must be unique")
    three_zone_gate_pairs = _three_zone_gate_pairs(campaign)
    matches = [item for item in campaign["experiments"] if item["experiment_id"] == experiment_id]
    if len(matches) != 1:
        raise ContractError("campaign experiment must resolve exactly once")
    experiment = matches[0]
    selected_three_zone_gate = experiment.get("three_zone_solver_gate")
    three_zone_gate_pair = (
        three_zone_gate_pairs[selected_three_zone_gate["gate_id"]]
        if selected_three_zone_gate is not None
        else None
    )
    source = experiment["source"]
    validate_pulse_resolution_optimization_campaign(
        campaign, execution_requested=True, experiment=experiment
    )
    validated_baseline_path = None
    validated_baseline = None
    if experiment.get("pulse_resolution_execution_mode") == (
        "screening_prefix_n100_paired_candidate"
    ):
        baseline_record = campaign["pulse_resolution_baseline_evidence"]
        validated_baseline_path = _workspace_record(
            workspace, baseline_record, "pulse-resolution baseline result"
        )
        validated_baseline = _load(validated_baseline_path)
        try:
            validate_frozen_baseline_evidence(
                campaign,
                validated_baseline,
                file_sha256(validated_baseline_path),
            )
        except ValueError as error:
            raise ContractError(str(error)) from error
    execution_strategy = experiment.get("execution_strategy", "staged_three_stage")
    pa_cache_policy = experiment.get("single_flight_pa_cache_policy")
    pa_cache_policy_provenance = None
    if execution_strategy == "simion_single_flight":
        if pa_cache_policy is None:
            pa_cache_policy = "legacy_unspecified"
            pa_cache_policy_provenance = "legacy_validate_only_compatibility"
        else:
            pa_cache_policy_provenance = "explicit_campaign_row"
    pulse_schedule_policy = experiment.get("single_flight_pulse_schedule_policy")
    population_declaration = experiment.get("single_flight_population")
    staged_grid2_mode = experiment.get("source_release_mode") == "staged_grid2_restart"
    if execution_strategy == "simion_single_flight" and campaign["schema_version"] < 3:
        raise ContractError(
            "SolverAuthorized single-flight execution requires a schema-v3 successor campaign"
        )
    if execution_strategy == "simion_single_flight" and population_declaration is None:
        raise ContractError("schema-v3 single flight requires a resolved population input")
    if execution_strategy == "simion_single_flight" and (
        (staged_grid2_mode and pulse_schedule_policy is not None)
        or (not staged_grid2_mode and pulse_schedule_policy is None)
    ):
        raise ContractError(
            "staged grid2 forbids a pulse schedule; other single-flight modes require one"
        )
    frontend_grid_profile_id = experiment.get(
        "single_flight_frontend_grid_profile_id"
    )
    single_flight_configuration = _load(
        root / "integrations" / INTEGRATION_ID / "config" /
        "simion_single_flight.json"
    )
    source_materialization_profile_id = experiment.get(
        "single_flight_source_materialization_profile_id"
    )
    source_materialization_profile = None
    if source_materialization_profile_id is not None:
        if execution_strategy != "simion_single_flight":
            raise ContractError(
                "source materialization profiles require SIMION single flight"
            )
        matches = [
            item
            for item in single_flight_configuration["source_materialization_profiles"]
            if item["profile_id"] == source_materialization_profile_id
        ]
        if len(matches) != 1:
            raise ContractError(
                "single-flight source materialization profile must resolve exactly once"
            )
        try:
            source_materialization_profile = resolve_source_materialization_profile(
                matches[0], root / "integrations" / INTEGRATION_ID,
            )
        except (KeyError, OSError, TypeError, ValueError) as exc:
            raise ContractError("source phase-space authority is invalid") from exc
    if frontend_grid_profile_id is not None:
        if execution_strategy != "simion_single_flight":
            raise ContractError(
                "single-flight frontend grid profiles require SIMION single flight"
            )
        grid_profiles = [
            item for item in single_flight_configuration["frontend_grid_profiles"]
            if item["profile_id"] == frontend_grid_profile_id
        ]
        if len(grid_profiles) != 1:
            raise ContractError(
                "single-flight frontend grid profile must resolve exactly once"
            )
    oatof_numerical_profile_id = experiment.get(
        "single_flight_oatof_numerical_profile_id"
    )
    oatof_numerical_profile = None
    if oatof_numerical_profile_id is not None:
        if execution_strategy != "simion_single_flight":
            raise ContractError("oaTOF numerical profiles require SIMION single flight")
        matches = [
            item for item in single_flight_configuration["oatof_numerical_profiles"]
            if item["profile_id"] == oatof_numerical_profile_id
        ]
        if len(matches) != 1:
            raise ContractError("oaTOF numerical profile must resolve exactly once")
        oatof_numerical_profile = matches[0]
    trajectory_quality_profile_id = experiment.get(
        "single_flight_trajectory_quality_profile_id"
    )
    if trajectory_quality_profile_id is not None:
        matches = [
            item for item in single_flight_configuration["trajectory_quality_profiles"]
            if item["profile_id"] == trajectory_quality_profile_id
        ]
        if len(matches) != 1:
            raise ContractError("trajectory-quality profile must resolve exactly once")
    time_integration_profile_id = experiment.get(
        "single_flight_time_integration_profile_id"
    )
    if time_integration_profile_id is not None:
        matches = [
            item for item in single_flight_configuration["time_integration_profiles"]
            if item["profile_id"] == time_integration_profile_id
        ]
        if len(matches) != 1:
            raise ContractError("time-integration profile must resolve exactly once")
    spatial_window_profile_id = experiment.get(
        "single_flight_spatial_window_profile_id"
    )
    if spatial_window_profile_id is not None:
        if execution_strategy != "simion_single_flight":
            raise ContractError("spatial-window profiles require SIMION single flight")
        matches = [
            item for item in single_flight_configuration["spatial_window_profiles"]
            if item["profile_id"] == spatial_window_profile_id
        ]
        if len(matches) != 1:
            raise ContractError("spatial-window profile must resolve exactly once")
    accelerator_field_profile_id = (
        canonical_profile_id(experiment.get(
            "single_flight_accelerator_field_profile_id",
            single_flight_configuration["default_accelerator_field_profile_id"],
        ))
        if execution_strategy == "simion_single_flight"
        else None
    )
    if accelerator_field_profile_id is not None:
        if execution_strategy != "simion_single_flight":
            raise ContractError(
                "single-flight accelerator field profiles require SIMION single flight"
            )
        field_profiles = [
            item for item in single_flight_configuration["accelerator_field_profiles"]
            if canonical_profile_id(item["profile_id"]) == accelerator_field_profile_id
        ]
        if len(field_profiles) != 1:
            raise ContractError(
                "single-flight accelerator field profile must resolve exactly once"
            )
    source_release_mode = experiment.get("source_release_mode")
    architecture_generation_id = experiment.get("architecture_generation_id")
    source_profile_id = experiment.get("source_profile_id")
    field_overlay_id = experiment.get("field_overlay_id")
    pre_pulse_source_state = experiment.get("pre_pulse_source_state")
    generated_pre_pulse_ordered_subset = experiment.get(
        "generated_pre_pulse_ordered_subset"
    )
    observed_pre_pulse_projection = experiment.get("observed_pre_pulse_projection")
    staged_grid2_source_state = experiment.get("staged_grid2_source_state")
    identity_values = (
        architecture_generation_id, source_profile_id, field_overlay_id,
    )
    if any(value is not None for value in identity_values) and not all(
        isinstance(value, str) and value for value in identity_values
    ):
        raise ContractError("single-flight architecture/source/field identity is incomplete")
    if execution_strategy == "simion_single_flight" and not (
        isinstance(source_release_mode, str) and source_release_mode
    ):
        raise ContractError("single-flight source release identity is incomplete")
    if (
        source_materialization_profile is not None
        and source_materialization_profile["source_profile_id"] != source_profile_id
    ):
        raise ContractError("source materialization and campaign source identities differ")
    if (
        field_overlay_id is not None
        and frontend_grid_profile_id is not None
        and grid_profiles[0].get("field_overlay_id") != field_overlay_id
    ):
        raise ContractError("frontend grid field-overlay identity differs")
    pre_pulse_source_path = None
    pre_pulse_receipt_path = None
    staged_grid2_source_path = None
    staged_grid2_bridge_template_path = None
    staged_grid2_bridge_trace_path = None
    staged_grid2_bridge_characterization_path = None
    staged_grid2_bridge_receipt_path = None
    staged_grid2_producer_manifest = None
    staged_loader_validation = None
    staged_loader_budget_path = None
    if source_release_mode == "pre_pulse_restart":
        if execution_strategy != "simion_single_flight" or (
            pre_pulse_source_state is None
            and generated_pre_pulse_ordered_subset is None
        ):
            raise ContractError("pre-pulse restart requires a governed source-state record")
        if pre_pulse_source_state is not None:
            pre_pulse_source_path = _workspace_record(
                workspace, pre_pulse_source_state, "pre-pulse source state"
            )
        if (
            pre_pulse_source_state is not None
            and source_materialization_profile is not None
        ):
            required_restart_fields = {
                "materialization_receipt", "source_state_epoch", "source_state_locus",
                "position_rowwise_abs_tolerance_mm",
                "velocity_rowwise_abs_tolerance_m_per_s", "clock_abs_tolerance_us",
                "energy_abs_tolerance_eV", "postselection_prohibited",
            }
            if not required_restart_fields.issubset(pre_pulse_source_state):
                raise ContractError("canonical pulse restart validation contract is incomplete")
            pre_pulse_receipt_path = _workspace_record(
                workspace,
                pre_pulse_source_state["materialization_receipt"],
                "pre-pulse source materialization receipt",
            )
    elif (
        pre_pulse_source_state is not None
        or generated_pre_pulse_ordered_subset is not None
    ):
        raise ContractError("pre-pulse source state requires pre-pulse restart mode")
    if source_release_mode == "staged_grid2_restart":
        if execution_strategy != "simion_single_flight" or staged_grid2_source_state is None:
            raise ContractError(
                "staged grid2 restart requires a governed canonical source-state record"
            )
        staged_grid2_source_path = _workspace_record(
            workspace, staged_grid2_source_state, "staged grid2 source state"
        )
        if source.get("authority_scope") != "connection_lineage_only":
            raise ContractError(
                "staged grid2 upstream source is connection lineage only"
            )
        overlay_present = field_overlay_id != "none"
        if (int(staged_grid2_source_state["simion_start_instance"]) == 5) != overlay_present:
            raise ContractError(
                "staged grid2 instance 3 requires no overlay and instance 5 requires overlay"
            )
        staged_grid2_producer_manifest_path = _workspace_record(
            workspace,
            staged_grid2_source_state["producer_manifest"],
            "staged grid2 producer manifest",
        )
        staged_grid2_producer_manifest = _load(staged_grid2_producer_manifest_path)
        if (
            staged_grid2_producer_manifest.get("role") != "simulation_run_manifest"
            or staged_grid2_producer_manifest.get("status") != "success"
            or staged_grid2_producer_manifest.get("run_id")
            != staged_grid2_source_state["producer_run_id"]
        ):
            raise ContractError("staged grid2 producer manifest identity differs")
        staged_grid2_bridge = staged_grid2_source_state.get("legacy_bridge")
        if staged_grid2_bridge is not None:
            staged_grid2_bridge_template_path = _workspace_record(
                workspace, staged_grid2_bridge["template"],
                "staged grid2 legacy bridge template",
            )
            staged_grid2_bridge_trace_path = _workspace_record(
                workspace, staged_grid2_bridge["trace"],
                "staged grid2 legacy bridge trace",
            )
            characterization_record = staged_grid2_bridge[
                "receipt_characterization"
            ]
            staged_grid2_bridge_characterization_path = (
                root / characterization_record["path"]
            ).resolve()
            if (
                not staged_grid2_bridge_characterization_path.is_relative_to(root)
                or not staged_grid2_bridge_characterization_path.is_file()
                or file_sha256(staged_grid2_bridge_characterization_path)
                != characterization_record["sha256"]
            ):
                raise ContractError(
                    "staged grid2 bridge characterization identity differs"
                )
        staged_validation = validate_component_particle_state_csv(
            staged_grid2_source_path
        )
        if (
            staged_validation["rows"]
            != int(staged_grid2_source_state["particle_count"])
            or staged_validation["frame_ids"]
            != [staged_grid2_source_state["frame_id"]]
            or staged_validation["clock_epoch_ids"]
            != [staged_grid2_source_state["clock_epoch_id"]]
        ):
            raise ContractError(
                "staged grid2 canonical table differs from its campaign receipt"
            )
        with staged_grid2_source_path.open(
            encoding="utf-8-sig", newline=""
        ) as handle:
            staged_rows = list(csv.DictReader(handle))
        if any(
            row["state_event"] != staged_grid2_source_state["state_event"]
            or row["target_component_id"]
            != "single_reflection_oa_tof_mass_analyzer"
            for row in staged_rows
        ):
            raise ContractError(
                "staged grid2 source event or target differs from its campaign receipt"
            )
        if campaign["schema_version"] >= 5:
            staged_loader_validation, staged_loader_budget_path = (
                _resolve_staged_loader_validation(
                    root,
                    staged_grid2_source_state["loader_authorization_budget"],
                    staged_grid2_source_state["sha256"],
                    staged_rows,
                )
            )
    elif staged_grid2_source_state is not None:
        raise ContractError(
            "staged grid2 source state requires staged grid2 restart mode"
        )
    profile_registry = load_connection_profile_registry(profile_registry_path)
    profile = _unique_profile(profile_registry, experiment["connection_profile_id"])
    expected_project_id = profile["upstream"]["project_id"]

    adapter_registry = load_execution_adapter_registry(adapter_registry_path)
    mapping = resolve_execution_mapping(
        adapter_registry, experiment["connection_profile_id"], repo_root=root
    )
    runtime_binding_record = {
        "path": mapping["runtime_binding_path"],
        "sha256": mapping["runtime_binding_sha256"],
    }
    runtime_binding_path = _repo_record(
        root, runtime_binding_record, "family runtime binding"
    )
    runtime_binding = _load(runtime_binding_path)
    validate_schema(runtime_binding, "rf_multipole_oatof_runtime_binding.schema.json")
    if (
        runtime_binding["schema_version"] != 3
        or runtime_binding["connection_profile_id"]
        != experiment["connection_profile_id"]
        or runtime_binding["upstream_project_id"] != expected_project_id
    ):
        raise ContractError("active family runtime binding identity differs")
    source_adapter_record = runtime_binding["contracts"]["source_adapter_contract"]
    source_adapter_path = _repo_record(
        root, source_adapter_record, "family source adapter"
    )
    source_adapter = _load(source_adapter_path)
    validate_schema(source_adapter, "rf_multipole_oatof_source_adapter.schema.json")
    policy_record = runtime_binding["contracts"]["execution_policy_contract"]
    if policy_record != campaign["execution_policy"]:
        raise ContractError("campaign and runtime execution policies differ")
    policy_path = _repo_record(root, policy_record, "integration execution policy")
    policy = _load(policy_path)
    validate_schema(policy, "rf_multipole_oatof_execution_policy.schema.json")
    validate_full_domain_affine_width_numerics_campaign(
        campaign, single_flight_configuration, policy, root
    )

    evidence = _load_source_evidence(
        workspace=workspace,
        experiment=experiment,
        expected_project_id=expected_project_id,
    )
    source = evidence["source"]
    pulse_contract = campaign.get("pulse_resolution_optimization")
    pulse_cohort_policy = None
    historical_cohort_reference = None
    paired_cohort_authority = None
    pulse_prefix_path = None
    pulse_prefix_sha256 = None
    if pulse_contract is not None:
        pulse_cohort_policy = _pulse_resolution_cohort_policy(experiment)
        if pulse_cohort_policy == "establish_observed_authority":
            historical_cohort_reference = (
                _resolve_pulse_resolution_historical_reference(root, campaign)
            )
            prefix_ids = historical_cohort_reference["source_release"][
                "ordered_particle_ids"
            ]
        else:
            if validated_baseline is None:
                raise ContractError("paired candidate lacks validated baseline evidence")
            paired_cohort_authority = validated_baseline.get(
                "observed_cohort_authority"
            )
            if not isinstance(paired_cohort_authority, dict):
                raise ContractError("baseline observed cohort authority is missing")
            prefix_ids = paired_cohort_authority["source_release"][
                "ordered_particle_ids"
            ]
        pulse_prefix_path = plan_output.parent / "inputs" / (
            "pulse_resolution_arm1_all_real_screening_prefix_n100.csv"
        )
        pulse_prefix_path.parent.mkdir(parents=True, exist_ok=True)
        pulse_prefix_sha256 = write_pulse_resolution_screening_prefix(
            _workspace_record(workspace, source["particle_source"],
                              "pulse-resolution mother source"),
            pulse_prefix_path,
            ordered_particle_ids=prefix_ids,
        )
    single_flight_source = experiment.get("single_flight_particle_source")
    single_flight_source_path = None
    selection_receipt = None
    if single_flight_source is not None:
        if execution_strategy != "simion_single_flight":
            raise ContractError("single-flight particle-source overrides require SIMION single flight")
        single_flight_source_path = _repo_record(
            root, single_flight_source, "single-flight particle source"
        )
        with single_flight_source_path.open(encoding="utf-8-sig", newline="") as handle:
            source_rows = list(csv.DictReader(handle))
        expected_columns = [
            "particle_id", "birth_time_s", "x_mm", "y_mm", "z_mm",
            "vx_m_s", "vy_m_s", "vz_m_s", "mass_amu", "charge_state",
        ]
        if not source_rows or list(source_rows[0]) != expected_columns:
            raise ContractError("single-flight particle source columns differ")
        if len(source_rows) != int(single_flight_source["particle_count"]):
            raise ContractError("single-flight particle source count differs")
        if [int(row["particle_id"]) for row in source_rows] != list(range(1, len(source_rows) + 1)):
            raise ContractError("single-flight particle source IDs must be contiguous")
        if single_flight_source["sampling_mode"] == "pulse_eligible_conditional":
            receipt = single_flight_source.get("selection_receipt")
            if receipt is None:
                raise ContractError("conditional source requires a selection receipt")
            receipt_path = _repo_record(
                root, receipt, "single-flight selection receipt"
            )
            selection_receipt = _load(receipt_path)
            if (
                selection_receipt.get("selected_count") != len(source_rows)
                or selection_receipt.get("candidate_eligible_count", 0) < len(source_rows)
                or selection_receipt.get("candidate_launched_count", 0)
                < selection_receipt.get("candidate_eligible_count", 0)
            ):
                raise ContractError("conditional-source receipt population differs")
    solver_id = evidence["solver_id"]
    if execution_strategy == "simion_single_flight" and solver_id != "simion":
        raise ContractError("SIMION single-flight execution requires a SIMION source run")
    design_evidence = evidence
    design_reference = experiment.get("single_flight_design_reference")
    if design_reference is not None:
        if execution_strategy != "simion_single_flight":
            raise ContractError("design references are only valid for SIMION single flight")
        design_evidence = _load_source_evidence(
            workspace=workspace,
            experiment={"source": design_reference},
            expected_project_id=expected_project_id,
        )
        if design_evidence["solver_id"] != "simion":
            raise ContractError("single-flight design reference requires a SIMION run")
    handoff_publication_record = source.get(
        "handoff_publication_contract",
        runtime_binding["contracts"]["handoff_publication_contract"],
    )
    handoff_publication_path = _repo_record(
        root, handoff_publication_record, "handoff publication contract"
    )
    handoff_publication = _load(handoff_publication_path)
    if (
        handoff_publication.get("schema_version") != 1
        or handoff_publication.get("role")
        != "multipole_handoff_publication_contract"
        or handoff_publication.get("population", {}).get(
            "expected_source_particle_count"
        )
        != source["launched_particle_count"]
        or handoff_publication.get("canonical_state", {}).get(
            "source_component_id"
        )
        != expected_project_id
    ):
        raise ContractError(
            "handoff publication contract differs from the selected source population"
        )
    adapter = copy.deepcopy(source_adapter["adapter"])
    adapter["dependencies"] = {
        "handoff_publication_contract": handoff_publication_record
    }
    resolved_source = copy.deepcopy(source)
    resolved_source.pop("handoff_publication_contract", None)
    resolved_source.pop("authority_scope", None)
    resolved_source_contract = {
        "schema_version": 2,
        "role": "rf_multipole_oatof_source_contract",
        "upstream_project_id": expected_project_id,
        "selector": copy.deepcopy(source_adapter["selector"]),
        "adapter": adapter,
        "canonical_state": copy.deepcopy(source_adapter["canonical_state"]),
        "source_branches": {
            solver_id: {
                "solver_id": solver_id,
                "recorded_project_id": expected_project_id,
                "source": resolved_source,
            }
        },
    }
    if staged_grid2_mode:
        resolved_source_contract["authority_scope"] = "connection_lineage_only"
    if design_reference is not None:
        resolved_source_contract["design_reference"] = {
            "run_id": design_reference["run_id"],
            "manifest": copy.deepcopy(design_reference["manifest"]),
        }
    validate_schema(
        resolved_source_contract, "rf_multipole_oatof_source_contract.schema.json"
    )
    plan_output.parent.mkdir(parents=True, exist_ok=True)
    resolved_source_contract_path = plan_output.with_name(
        "resolved_source_contract.json"
    )
    resolved_source_contract_path.write_text(
        json.dumps(resolved_source_contract, indent=2) + "\n", encoding="utf-8"
    )

    upstream_resolved_design_path = plan_output.with_name(
        "upstream_resolved_design.json"
    )
    shutil.copyfile(design_evidence["resolved_design_path"], upstream_resolved_design_path)
    if file_sha256(upstream_resolved_design_path) != design_evidence["resolved_design_sha256"]:
        raise ContractError("frozen upstream resolved design identity differs")

    upstream_port = build_exit_component_port(
        design_evidence["resolved_design"],
        design_profile_id=design_evidence["design_profile_id"],
        authority_path=_workspace_relative(upstream_resolved_design_path, workspace),
        authority_sha256=design_evidence["resolved_design_sha256"],
    )
    upstream_port_path = plan_output.with_name("resolved_upstream_port.json")
    upstream_port_path.write_text(
        json.dumps(upstream_port, indent=2) + "\n", encoding="utf-8"
    )
    resolved_registry = {
        "schema_version": profile_registry["schema_version"],
        "role": profile_registry["role"],
        "integration_id": profile_registry["integration_id"],
        "profiles": [copy.deepcopy(profile)],
    }
    resolved_upstream = resolved_registry["profiles"][0]["upstream"]
    if resolved_upstream.pop("port_binding", None) != "source_run_resolved_design":
        raise ContractError("upstream port is not runtime-bound to source design")
    resolved_upstream["port_contract"] = _workspace_relative(
        upstream_port_path, workspace
    )
    layout_files: dict[str, Path] | None = None
    resolved_region_field_contract_path: Path | None = None
    resolved_region_field_contract: dict[str, Any] | None = None
    if campaign["schema_version"] >= 3:
        if execution_strategy != "simion_single_flight":
            raise ContractError("single-flight layout profiles require SIMION single flight")
        layout_registry_path = (
            root / "integrations" / INTEGRATION_ID / "config" /
            "single_flight_layout_profiles.json"
        )
        layout_profile = select_profile(
            _load(layout_registry_path), experiment["single_flight_layout_profile_id"]
        )
        if (
            architecture_generation_id is not None
            and layout_profile["architecture_generation_id"]
            != architecture_generation_id
        ):
            raise ContractError("layout profile architecture generation differs")
        experiment_overrides = experiment.get("single_flight_design_overrides", [])
        three_zone_candidate = None
        three_zone_candidate_binding = None
        three_zone_candidate_path = None
        if layout_profile["method"] == "t5_frozen_three_zone_candidate_v1":
            if experiment_overrides:
                raise ContractError(
                    "three-zone T5 layout prohibits experiment design overrides"
                )
            three_zone_candidate_binding = experiment.get(
                "single_flight_three_zone_candidate"
            )
            if not isinstance(three_zone_candidate_binding, dict):
                raise ContractError(
                    "three-zone T5 layout requires a Candidate file binding"
                )
            three_zone_candidate_path = _workspace_record(
                workspace,
                three_zone_candidate_binding,
                "three-zone T5 Candidate",
            )
            three_zone_candidate = _load(three_zone_candidate_path)
            validate_schema(
                three_zone_candidate,
                "oatof_three_zone_simion_candidate_resolved.schema.json",
            )
            selected_field_profile = field_profiles[0]
            expected_profile_identities = {
                "topology_id": layout_profile["topology_id"],
                "geometry_id": layout_profile["geometry_id"],
                "frontend_electrode_topology_id": layout_profile[
                    "frontend_electrode_topology_id"
                ],
            }
            if any(
                selected_field_profile.get(key) != value
                for key, value in expected_profile_identities.items()
            ):
                raise ContractError(
                    "three-zone field and layout profile identities differ"
                )
            expected_field_ids = {
                "accelerator_ideal_three_zone_real_reflectron":
                    "three_zone_piecewise_uniform_ideal_field_v1",
                "accelerator_real_three_zone_pa_real_reflectron":
                    "three_zone_refined_pa_field_v1",
            }
            if (
                selected_field_profile.get("field_id")
                != expected_field_ids.get(accelerator_field_profile_id)
            ):
                raise ContractError(
                    "three-zone field profile scientific identity differs"
                )
        if experiment_overrides:
            inherited = list(layout_profile.get("design_overrides", []))
            variables = [item["variable"] for item in inherited + experiment_overrides]
            if len(variables) != len(set(variables)):
                raise ContractError("single-flight design override variable is duplicated")
            layout_profile["design_overrides"] = inherited + copy.deepcopy(
                experiment_overrides
            )
        base_geometry_path = (
            root / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json"
        )
        base_downstream_port_path = (root / profile["downstream"]["port_contract"]).resolve()
        geometry, downstream_port, _ = compile_geometry_and_port(
            _load(base_geometry_path),
            _load(base_downstream_port_path),
            layout_profile,
            three_zone_candidate=three_zone_candidate,
            three_zone_candidate_binding=three_zone_candidate_binding,
        )
        if oatof_numerical_profile is not None:
            reflectron_mesh = oatof_numerical_profile["reflectron_cell_mm"]
            geometry["simion_geometry_build"]["reflectron"]["cell_axial_mm"] = float(
                reflectron_mesh["axial"]
            )
            geometry["simion_geometry_build"]["reflectron"]["cell_radial_mm"] = float(
                reflectron_mesh["radial"]
            )
        geometry_path = plan_output.with_name("resolved_oatof_geometry.json")
        geometry_path.write_text(json.dumps(geometry, indent=2) + "\n", encoding="utf-8")
        resolved_region_field_contract_path = (
            plan_output.parent / "inputs" / "resolved_region_field_contract.json"
        )
        try:
            resolved_region_field_contract = build_resolved_region_field_contract(
                geometry_path,
                resolved_region_field_contract_path,
                accelerator_field_profile_id or "accelerator_real_pa",
                accelerator_topology=geometry.get("accelerator_topology"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("resolved region field contract is invalid") from exc
        downstream_port["authority"]["source_contract"] = _workspace_relative(
            geometry_path, workspace
        )
        downstream_port["authority"]["source_sha256"] = file_sha256(geometry_path)
        downstream_port_path = plan_output.with_name("resolved_downstream_port.json")
        downstream_port_path.write_text(
            json.dumps(downstream_port, indent=2) + "\n", encoding="utf-8"
        )
        validate_schema(downstream_port, "component_port.schema.json")
        resolved_registry["profiles"][0]["downstream"]["port_contract"] = (
            _workspace_relative(downstream_port_path, workspace)
        )
        registration = resolved_registry["profiles"][0]["spatial_registration"]
        registration["translation_mm"] = derive_direct_mating_translation(
            registration["rotation_upstream_to_downstream"],
            upstream_port["mating_surface"]["center_mm"],
            downstream_port["mating_surface"]["center_mm"],
        )
        layout_files = {
            "registry": layout_registry_path,
            "geometry": geometry_path,
            "downstream_port": downstream_port_path,
        }
        if three_zone_candidate_path is not None:
            layout_files["three_zone_candidate"] = three_zone_candidate_path
    resolved_registry_path = plan_output.with_name(
        "resolved_connection_profile_registry.json"
    )
    resolved_registry_path.write_text(
        json.dumps(resolved_registry, indent=2) + "\n", encoding="utf-8"
    )

    source_identity = (
        {
            "authority_role": "staged_grid2_canonical_source_state",
            "source_branch_id": solver_id,
            "solver_id": "simion",
            "run_id": staged_grid2_source_state["producer_run_id"],
            "project_id": staged_grid2_producer_manifest["project"],
            "manifest_sha256": staged_grid2_source_state["producer_manifest"]["sha256"],
            "event_sha256": staged_grid2_source_state["sha256"],
            "particle_source_sha256": staged_grid2_source_state["sha256"],
            "metadata_sha256": staged_grid2_source_state["sha256"],
            "state_event": staged_grid2_source_state["state_event"],
            "clock_epoch_id": staged_grid2_source_state["clock_epoch_id"],
        }
        if staged_grid2_mode
        else {
            "source_branch_id": solver_id,
            "solver_id": solver_id,
            "run_id": source["run_id"],
            "project_id": expected_project_id,
            "manifest_sha256": source["manifest"]["sha256"],
            "event_sha256": source["state"]["sha256"],
            "particle_source_sha256": source["particle_source"]["sha256"],
            "metadata_sha256": source["metadata"]["sha256"],
        }
    )
    if observed_pre_pulse_projection is not None:
        source_identity["observed_pre_pulse_projection"] = copy.deepcopy(
            observed_pre_pulse_projection
        )
    row_sha256 = _canonical_sha256(experiment)
    three_zone_authorization: dict[str, str] | None = None
    if three_zone_gate_pair is not None:
        producer, consumer = three_zone_gate_pair
        gate_stage = experiment["three_zone_solver_gate"]["stage"]
        if gate_stage == "n100_solver_authorized_consumer":
            if (
                resolved_region_field_contract is None
                or layout_profile is None
                or not field_profiles
            ):
                raise ContractError("three-zone N=100 authorization identity is incomplete")
            three_zone_authorization = _resolve_three_zone_n1_authorization(
                workspace=workspace,
                campaign=campaign,
                campaign_path=campaign_path,
                producer=producer,
                consumer=consumer,
                source_identity=source_identity,
                layout_profile=layout_profile,
                selected_field_profile=field_profiles[0],
                resolved_region_field_contract=resolved_region_field_contract,
            )
    registration_receipt_path = None
    registration_receipt_sha256 = None
    if pulse_contract is not None:
        with pulse_prefix_path.open(encoding="utf-8", newline="") as handle:
            prefix_ids = [int(row["particle_id"]) for row in csv.DictReader(handle)]
        expected_prefix_ids = (
            historical_cohort_reference["source_release"]["ordered_particle_ids"]
            if pulse_cohort_policy == "establish_observed_authority"
            else paired_cohort_authority["source_release"]["ordered_particle_ids"]
        )
        if prefix_ids != expected_prefix_ids:
            raise ContractError("pulse-resolution governed prefix IDs differ")
        paired_candidate = experiment["pulse_resolution_execution_mode"] == (
            "screening_prefix_n100_paired_candidate"
        )
        if paired_candidate:
            baseline_record = campaign["pulse_resolution_baseline_evidence"]
            if validated_baseline_path is None or validated_baseline is None:
                raise ContractError("paired screening baseline preflight was not completed")
            baseline_path = validated_baseline_path
            baseline = validated_baseline
            if (
                baseline.get("role") != "rf_oatof_pulse_resolution_baseline_result"
                or baseline.get("baseline_authority_id")
                != baseline_record["authority_id"]
                or baseline.get("campaign_id")
                != baseline_record["baseline_campaign_id"]
                or baseline.get("campaign_sha256")
                != baseline_record["baseline_campaign_sha256"]
                or baseline.get("experiment_id") != "pulse_resolution_baseline"
                or baseline.get("prefix", {}).get("ordered_particle_ids") != prefix_ids
                or baseline.get("cohort_authority_mode")
                != "establish_observed_authority"
                or baseline.get("observed_cohort_authority")
                != paired_cohort_authority
                or baseline.get("analysis_randomness")
                != population_declaration["analysis_randomness"]
            ):
                raise ContractError("paired screening baseline result identity differs")
            registration_receipt_path = plan_output.parent / "inputs" / (
                "pulse_resolution_baseline_evidence.json"
            )
            shutil.copy2(baseline_path, registration_receipt_path)
            registration_receipt_sha256 = file_sha256(registration_receipt_path)
        else:
            registration_receipt = {
            "schema_version": 1,
            "role": "rf_oatof_pulse_resolution_baseline_registration_authority",
            "campaign_id": campaign["campaign_id"],
            "campaign_sha256": repository_text_sha256(campaign_path),
            "experiment_id": experiment_id,
            "experiment_row_sha256": row_sha256,
            "direct_contract": {
                "source_run_id": source["run_id"],
                "source_state_sha256": source["state"]["sha256"],
                "layout_profile_id": experiment["single_flight_layout_profile_id"],
                "frontend_grid_profile_id": experiment[
                    "single_flight_frontend_grid_profile_id"
                ],
                "field_profile_id": experiment[
                    "single_flight_accelerator_field_profile_id"
                ],
            },
            "mother_sample": {
                "run_id": source["run_id"],
                "manifest": source["manifest"],
                "particle_source": source["particle_source"],
                "particle_count": source["launched_particle_count"],
            },
            "prefix": {
                "path": "inputs/" + pulse_prefix_path.name,
                "sha256": pulse_prefix_sha256,
                "count": len(prefix_ids),
                "selection_algorithm": population_declaration[
                    "execution_population"
                ]["selection_algorithm"],
                "selection_seed": population_declaration[
                    "execution_population"
                ]["selection_seed"],
                "ordered_particle_ids": prefix_ids,
                "particle_id_sha256_ordered": _canonical_sha256(prefix_ids).lower(),
            },
            "analysis_randomness": population_declaration["analysis_randomness"],
            "cohort_authority_mode": pulse_cohort_policy,
            "historical_migration_reference": historical_cohort_reference,
            "execution_status": "baseline_registered_not_candidate",
            "solver_execution_performed": False,
            "promotion_gate_invoked": False,
            "promotion_status": "not_evaluated",
            "formal_gate_passed": False,
        }
            registration_receipt["receipt_sha256"] = _canonical_sha256(
                registration_receipt
            ).lower()
            registration_receipt_path = plan_output.parent / "inputs" / (
                "pulse_resolution_real_beam_real_accelerator_real_reflectron_"
                "n100_baseline_registration_authority.json"
            )
            registration_receipt_path.write_text(
                json.dumps(registration_receipt, indent=2) + "\n", encoding="utf-8"
            )
            registration_receipt_sha256 = file_sha256(registration_receipt_path)
    execution_particle_count = (
        int(population_declaration["execution_population"]["particle_count"])
        if execution_strategy == "simion_single_flight"
        else evidence["particle_count"]
    )
    resolved_budget = {
        "schema_version": 1,
        "role": "integration_resolved_engineering_budget",
        "integration_id": INTEGRATION_ID,
        "connection_profile_id": experiment["connection_profile_id"],
        "campaign_id": campaign["campaign_id"],
        "experiment_id": experiment_id,
        "experiment_row_sha256": row_sha256,
        "execution_strategy": execution_strategy,
        "policy_id": policy["policy_id"],
        "source_identity": source_identity,
        "launched_particle_count": execution_particle_count,
        "particle_count": execution_particle_count,
        "retention_class": policy["retention_class"],
        "stage_limits": policy["stage_limits"],
        "budget_exhaustion_result": policy["budget_exhaustion_result"],
    }
    if execution_strategy == "simion_single_flight":
        resolved_budget["single_flight_pa_cache_policy"] = pa_cache_policy
        resolved_budget["single_flight_pa_cache_policy_provenance"] = (
            pa_cache_policy_provenance
        )
    if frontend_grid_profile_id is not None and grid_profiles[0].get(
        "accelerator_overlay"
    ):
        estimate = grid_profiles[0]["accelerator_overlay"].get(
            "transient_disk_estimate"
        )
        if estimate is not None:
            dimensions = estimate["overlay_grid_dimensions"]
            grid_points = (
                int(dimensions["nx"])
                * int(dimensions["ny"])
                * int(dimensions["nz"])
            )
            pa_family_bytes = (
                grid_points
                * int(estimate["bytes_per_grid_point"])
                * int(estimate["overlay_pa_family_file_count"])
            )
            transient_bytes = round(
                (
                    pa_family_bytes
                    + int(estimate["coarse_frontend_and_iob_bytes"])
                )
                * float(estimate["headroom_factor"])
            )
            resolved_budget["stage_limits"]["single_flight_transport"][
                "transient_run_directory_bytes"
            ] = max(
                transient_bytes,
                int(
                    resolved_budget["stage_limits"]["single_flight_transport"][
                        "transient_run_directory_bytes"
                    ]
                ),
            )
            resolved_budget["transient_disk_estimate"] = {
                "profile_id": frontend_grid_profile_id,
                "formula": "ceil((grid_points*bytes_per_grid_point*pa_family_file_count+coarse_frontend_and_iob_bytes)*headroom_factor)",
                "grid_points": grid_points,
                "estimated_bytes": transient_bytes,
            }
    resolved_budget_path = plan_output.with_name("resolved_engineering_budget.json")
    resolved_budget_path.write_text(
        json.dumps(resolved_budget, indent=2) + "\n", encoding="utf-8"
    )

    resolved_path, plan_path = write_resolved_and_plan(
        resolved_registry_path,
        experiment["connection_profile_id"],
        resolved_output,
        plan_output,
        repo_root=root,
    )
    if staged_grid2_bridge_template_path is not None:
        staged_grid2_generated_path = plan_output.with_name(
            "staged_grid2_canonical_source_state.csv"
        )
        staged_grid2_bridge_receipt_path = plan_output.with_name(
            "staged_grid2_legacy_bridge_receipt.json"
        )
        materialize_legacy_grid2_state(
            staged_grid2_bridge_template_path,
            staged_grid2_bridge_trace_path,
            staged_grid2_generated_path,
            staged_grid2_bridge_receipt_path,
        )
        staged_grid2_bridge = staged_grid2_source_state["legacy_bridge"]
        if (
            file_sha256(staged_grid2_generated_path)
            != staged_grid2_source_state["sha256"]
            or file_sha256(staged_grid2_bridge_receipt_path)
            != file_sha256(staged_grid2_bridge_characterization_path)
        ):
            raise ContractError(
                "staged grid2 controlled bridge output or receipt hash differs"
            )
        staged_grid2_source_path = staged_grid2_generated_path
    materialized_source_path = None
    resolved_population_path = None
    if layout_files is not None:
        schedule = None
        if not staged_grid2_mode:
            if pulse_schedule_policy.get("fixed_execution_authority") is not None:
                schedule = _resolve_fixed_pulse_schedule(
                    root=root,
                    campaign=campaign,
                    experiment=experiment,
                    experiment_id=experiment_id,
                    experiment_row_sha256=row_sha256,
                    population_declaration_sha256=_canonical_sha256(population_declaration),
                    policy=pulse_schedule_policy,
                )
            else:
                schedule = derive_pulse_schedule(
                    design_evidence["state_path"], _load(resolved_path), _load(layout_files["geometry"]),
                    layout_profile,
                    campaign_id=campaign["campaign_id"],
                    experiment_id=experiment_id,
                    experiment_row_sha256=row_sha256,
                    population_declaration_sha256=_canonical_sha256(population_declaration),
                    policy=pulse_schedule_policy,
                    rf_frequency_hz=float(
                        design_evidence["resolved_design"]["drive"]["frequency_Hz"]
                    ),
                )
            validate_schema(
                schedule, "rf_oatof_resolved_single_flight_pulse_schedule.schema.json"
            )
            schedule_path = plan_output.with_name("resolved_single_flight_pulse_schedule.json")
            schedule_path.write_text(json.dumps(schedule, indent=2) + "\n", encoding="utf-8")
            layout_files["schedule"] = schedule_path
        if pre_pulse_source_path is not None and source_materialization_profile is not None:
            pulse_restart_validation = _validate_canonical_pulse_restart_state(
                pre_pulse_source_path,
                pre_pulse_receipt_path,
                pre_pulse_source_state,
                source_materialization_profile,
                geometry,
                schedule,
            )
            pulse_restart_validation_path = plan_output.with_name(
                "canonical_pulse_restart_target_state_validation.json"
            )
            pulse_restart_validation_path.write_text(
                json.dumps(pulse_restart_validation, indent=2) + "\n",
                encoding="utf-8",
            )
        if (
            source_materialization_profile is not None
            and source_materialization_profile["materialization_mode"]
            == "resolved_layout_pulse_ideal_linear_z_vz"
        ):
            materialized_source_path = plan_output.parent / "inputs" / (
                "single_flight_materialized_particle_source.csv"
            )
            materialization_receipt_path = plan_output.parent / "inputs" / (
                "single_flight_source_materialization_receipt.json"
            )
            pulse_target_source_path = plan_output.parent / "inputs" / (
                "single_flight_pulse_target_state.csv"
            )
            materialization_receipt = materialize_ideal_linear_source(
                materialized_source_path,
                materialization_receipt_path,
                _load(resolved_path),
                geometry,
                schedule,
                source_materialization_profile,
                pulse_target_source_path,
            )
        elif (
            source_materialization_profile is not None
            and source_materialization_profile["materialization_mode"]
            != "canonical_multipole_source"
        ):
            raise ContractError("source materialization mode is unsupported")
        if generated_pre_pulse_ordered_subset is not None:
            if (
                source_materialization_profile is None
                or source_materialization_profile["materialization_mode"]
                != "resolved_layout_pulse_ideal_linear_z_vz"
                or int(source_materialization_profile["particle_count"]) != 1000
                or pulse_target_source_path is None
                or materialization_receipt_path is None
            ):
                raise ContractError(
                    "generated ordered subset requires one N=1000 ideal-linear mother"
                )
            try:
                ordered_source_ids = ordered_subset_source_particle_ids(
                    generated_pre_pulse_ordered_subset["selection_id"]
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ContractError(
                    "generated ordered subset selection is invalid"
                ) from exc
            pre_pulse_source_path = (
                plan_output.parent
                / "inputs"
                / "single_flight_pre_pulse_ordered_subset.csv"
            )
            pre_pulse_receipt_path = (
                plan_output.parent
                / "inputs"
                / "single_flight_pre_pulse_ordered_subset_receipt.json"
            )
            ordered_subset_receipt = materialize_ordered_pre_pulse_subset(
                pulse_target_source_path,
                materialization_receipt_path,
                pre_pulse_source_path,
                pre_pulse_receipt_path,
                pulse_time_us=float(schedule["pulse_effective_time_us"]),
                ordered_source_particle_ids=ordered_source_ids,
            )
            validate_schema(
                ordered_subset_receipt,
                "rf_oatof_pre_pulse_ordered_subset_receipt.schema.json",
            )
            ideal_subset_validation = _validate_canonical_pulse_restart_state(
                pre_pulse_source_path,
                pre_pulse_receipt_path,
                {
                    "sha256": file_sha256(pre_pulse_source_path),
                    "particle_count": len(ordered_source_ids),
                    "materialization_receipt": {
                        "sha256": file_sha256(pre_pulse_receipt_path)
                    },
                    "position_rowwise_abs_tolerance_mm": 1e-9,
                    "velocity_rowwise_abs_tolerance_m_per_s": 1e-6,
                    "clock_abs_tolerance_us": 1e-9,
                    "energy_abs_tolerance_eV": 5e-9,
                },
                source_materialization_profile,
                geometry,
                schedule,
            )
            projection_receipt = None
            if observed_pre_pulse_projection is not None:
                authority_paths = {
                    key: _workspace_record(
                        workspace, observed_pre_pulse_projection[key],
                        f"observed projection {key}",
                    )
                    for key in (
                        "authority_manifest", "prepared_arms", "observed_state",
                        "old_geometry",
                    )
                }
                current_target_path = pre_pulse_source_path
                current_subset_receipt_path = pre_pulse_receipt_path
                full_path = plan_output.parent / "inputs" / "observed_pre_pulse_full_6d.csv"
                collapsed_path = (
                    plan_output.parent / "inputs" / "observed_pre_pulse_collapsed.csv"
                )
                affine_fixed_10ev_path = (
                    plan_output.parent / "inputs"
                    / "affine_zvz_fixed_10eV_transverse_collapsed.csv"
                )
                observed_fixed_10ev_path = (
                    plan_output.parent / "inputs"
                    / "observed_zvz_fixed_10eV_transverse_collapsed.csv"
                )
                projection_receipt_path = (
                    plan_output.parent / "inputs"
                    / "observed_pre_pulse_projection_receipt.json"
                )
                selected_arm = observed_pre_pulse_projection["arm_id"]
                four_arm_projection = selected_arm in {
                    ARM_AFFINE_FIXED_10EV, ARM_OBSERVED_FIXED_10EV,
                }
                affine_authority = (
                    {
                        "mean_velocity_z_m_per_s": float(
                            source_materialization_profile[
                                "mean_velocity_z_m_per_s"
                            ]
                        ),
                        "velocity_z_slope_m_per_s_per_mm": float(
                            source_materialization_profile[
                                "velocity_z_slope_m_per_s_per_mm"
                            ]
                        ),
                        "center_z_mm": float(
                            ordered_subset_receipt["resolved_target_center_mm"][2]
                        ),
                    }
                    if four_arm_projection else None
                )
                fixed_kinetic_energy_eV = (
                    float(source_materialization_profile["kinetic_energy_eV"])
                    if four_arm_projection else None
                )
                projection_receipt = project_observed_pre_pulse_states(
                    authority_manifest_path=authority_paths["authority_manifest"],
                    prepared_arms_path=authority_paths["prepared_arms"],
                    observed_state_path=authority_paths["observed_state"],
                    old_geometry_path=authority_paths["old_geometry"],
                    current_target_path=current_target_path,
                    current_subset_receipt_path=current_subset_receipt_path,
                    full_output_path=full_path,
                    collapsed_output_path=collapsed_path,
                    receipt_output_path=projection_receipt_path,
                    affine_fixed_10ev_output_path=(
                        affine_fixed_10ev_path if four_arm_projection else None
                    ),
                    observed_fixed_10ev_output_path=(
                        observed_fixed_10ev_path if four_arm_projection else None
                    ),
                    affine_mean_velocity_z_m_per_s=(
                        affine_authority["mean_velocity_z_m_per_s"]
                        if affine_authority is not None else None
                    ),
                    affine_velocity_z_slope_m_per_s_per_mm=(
                        affine_authority["velocity_z_slope_m_per_s_per_mm"]
                        if affine_authority is not None else None
                    ),
                    affine_center_z_mm=(
                        affine_authority["center_z_mm"]
                        if affine_authority is not None else None
                    ),
                    fixed_kinetic_energy_eV=fixed_kinetic_energy_eV,
                )
                validate_schema(
                    projection_receipt,
                    "rf_oatof_observed_pre_pulse_projection_receipt.schema.json",
                )
                pre_pulse_source_path = {
                    ARM_AFFINE_FIXED_10EV: affine_fixed_10ev_path,
                    ARM_OBSERVED_FIXED_10EV: observed_fixed_10ev_path,
                    ARM_FULL: full_path,
                    ARM_COLLAPSED: collapsed_path,
                }[selected_arm]
                pre_pulse_receipt_path = projection_receipt_path
            pre_pulse_source_state = {
                "path": _workspace_relative(pre_pulse_source_path, workspace),
                "sha256": file_sha256(pre_pulse_source_path),
                "particle_count": len(ordered_source_ids),
                "coordinate_frame": "oatof_global_cartesian",
                "release_event": "pre_pulse_state",
                "materialization_receipt": {
                    "path": _workspace_relative(pre_pulse_receipt_path, workspace),
                    "sha256": file_sha256(pre_pulse_receipt_path),
                },
                "source_state_epoch": "pulse_effective_time",
                "source_state_locus": (
                    "accelerator_stage1_interior_finite_observed_3d_cloud"
                    if projection_receipt is not None else
                    "accelerator_stage1_interior_fixed_transverse_finite_local_z_interval"
                ),
                "position_rowwise_abs_tolerance_mm": 1e-9,
                "velocity_rowwise_abs_tolerance_m_per_s": 1e-6,
                "clock_abs_tolerance_us": 1e-9,
                "energy_abs_tolerance_eV": 5e-9,
                "postselection_prohibited": True,
            }
            pulse_restart_validation = (
                _validate_observed_pre_pulse_projection(
                    receipt=projection_receipt,
                    receipt_path=pre_pulse_receipt_path,
                    selected_arm=selected_arm,
                    selected_path=pre_pulse_source_path,
                    full_path=full_path,
                    collapsed_path=collapsed_path,
                    affine_fixed_10ev_path=(
                        affine_fixed_10ev_path if four_arm_projection else None
                    ),
                    observed_fixed_10ev_path=(
                        observed_fixed_10ev_path if four_arm_projection else None
                    ),
                    current_target_path=current_target_path,
                    current_subset_receipt_path=current_subset_receipt_path,
                    pulse_time_us=float(schedule["pulse_effective_time_us"]),
                    affine_authority=affine_authority,
                    fixed_kinetic_energy_eV=fixed_kinetic_energy_eV,
                )
                if projection_receipt is not None
                else ideal_subset_validation
            )
            pulse_restart_validation_path = plan_output.with_name(
                "canonical_pulse_restart_target_state_validation.json"
            )
            pulse_restart_validation_path.write_text(
                json.dumps(pulse_restart_validation, indent=2) + "\n",
                encoding="utf-8",
            )
        table_binding = population_declaration["source_authority"]["table_binding"]
        if table_binding == "source_contract_particle_source":
            population_path = _workspace_record(
                workspace, source["particle_source"], "population source contract table"
            )
            population_input_role = source["particle_source_manifest_input_role"]
        elif table_binding == "experiment_single_flight_particle_source":
            if single_flight_source_path is None:
                raise ContractError("population declaration requires an experiment source table")
            population_path = single_flight_source_path
            population_input_role = "single_flight_particle_source"
        elif table_binding == "experiment_pre_pulse_source_state":
            if pre_pulse_source_path is None:
                raise ContractError("population declaration requires a pre-pulse source table")
            population_path = pre_pulse_source_path
            population_input_role = "pre_pulse_source_state"
        elif table_binding == "experiment_staged_grid2_source_state":
            if staged_grid2_source_path is None:
                raise ContractError(
                    "population declaration requires a staged grid2 canonical table"
                )
            population_path = staged_grid2_source_path
            population_input_role = "staged_grid2_source_state"
        elif table_binding == "prepared_materialized_particle_source":
            if materialized_source_path is None:
                raise ContractError("population declaration requires a materialized source table")
            population_path = materialized_source_path
            population_input_role = "single_flight_materialized_particle_source"
        elif table_binding == "prepared_deterministic_prefix":
            if pulse_prefix_path is None:
                raise ContractError("population declaration requires a deterministic prefix table")
            population_path = pulse_prefix_path
            population_input_role = "pulse_resolution_screening_prefix"
        elif table_binding == "staged_upstream_source":
            population_path = _workspace_record(
                workspace, source["particle_source"], "staged population source table"
            )
            population_input_role = source["particle_source_manifest_input_role"]
        else:
            raise ContractError("population source table binding is unsupported")
        resolved_population = compile_resolved_population_contract(
            campaign_id=campaign["campaign_id"],
            experiment_id=experiment_id,
            experiment_row_sha256=row_sha256,
            population_declaration_sha256=_canonical_sha256(population_declaration),
            execution_strategy=execution_strategy,
            source_release_mode=source_release_mode,
            declaration=population_declaration,
            source_table=_population_source_table(
                population_path,
                workspace=workspace,
                input_role=population_input_role,
                table_binding=table_binding,
            ),
            contract_schema_version=(2 if campaign["schema_version"] >= 5 else 1),
            source_release_validation=staged_loader_validation,
            paired_cohort_authority=paired_cohort_authority,
            cohort_authority_mode=pulse_cohort_policy,
        )
        resolved_population_path = plan_output.with_name(
            "resolved_population_contract.json"
        )
        resolved_population_path.write_text(
            json.dumps(resolved_population, indent=2) + "\n", encoding="utf-8"
        )
    plan = _load(plan_path)
    plan["execution_steps"] = [
        {
            "step_id": "rf_to_oatof_transfer",
            "adapter": "powershell",
            "entrypoint": mapping["adapter_entrypoint"],
            "arguments": [
                f"adapter_registry_sha256={repository_text_sha256(adapter_registry_path)}",
                f"campaign_path={campaign_path.relative_to(root).as_posix()}",
                f"campaign_sha256={repository_text_sha256(campaign_path)}",
                f"campaign_id={campaign['campaign_id']}",
                f"experiment_id={experiment_id}",
                f"experiment_row_sha256={row_sha256}",
                f"execution_strategy={execution_strategy}",
                f"runtime_binding_path={runtime_binding_record['path']}",
                f"runtime_binding_sha256={runtime_binding_record['sha256']}",
                f"source_branch_id={solver_id}",
                "resolved_budget_filename=resolved_engineering_budget.json",
                f"resolved_budget_sha256={file_sha256(resolved_budget_path)}",
                "resolved_source_contract_filename=resolved_source_contract.json",
                f"resolved_source_contract_sha256={file_sha256(resolved_source_contract_path)}",
                "upstream_resolved_design_filename=upstream_resolved_design.json",
                "upstream_resolved_design_sha256="
                + design_evidence["resolved_design_sha256"],
            ] + ([] if execution_strategy != "simion_single_flight" else [
                "single_flight_pa_cache_policy=" + pa_cache_policy,
                "single_flight_pa_cache_policy_provenance="
                + pa_cache_policy_provenance,
            ]) + ([] if single_flight_source is None else [
                f"single_flight_particle_source_path={single_flight_source['path']}",
                f"single_flight_particle_source_sha256={single_flight_source['sha256']}",
                f"single_flight_particle_source_count={single_flight_source['particle_count']}",
            ]) + ([] if source_materialization_profile is None else [
                "single_flight_source_materialization_profile_id="
                + source_materialization_profile_id,
            ]) + ([] if source_materialization_profile is None or
                    source_materialization_profile["materialization_mode"] ==
                    "canonical_multipole_source" else [
                "single_flight_materialized_source_filename="
                "inputs/single_flight_materialized_particle_source.csv",
                "single_flight_materialized_source_sha256="
                + materialization_receipt["particle_source"]["sha256"],
                "single_flight_materialized_source_count="
                + str(materialization_receipt["particle_count"]),
                "single_flight_materialization_receipt_filename="
                "inputs/single_flight_source_materialization_receipt.json",
                "single_flight_materialization_receipt_sha256="
                + file_sha256(materialization_receipt_path),
            ]) + ([] if pulse_contract is None else [
                "pulse_resolution_execution_mode="
                + experiment["pulse_resolution_execution_mode"],
                "pulse_resolution_prefix_filename=inputs/"
                + pulse_prefix_path.name,
                "pulse_resolution_prefix_sha256=" + pulse_prefix_sha256,
                "pulse_resolution_registration_filename=inputs/"
                + registration_receipt_path.name,
                "pulse_resolution_registration_sha256="
                + registration_receipt_sha256,
            ]) + ([] if layout_files is None else [
                f"layout_profile_id={experiment['single_flight_layout_profile_id']}",
                "architecture_generation_id="
                + layout_profile["architecture_generation_id"],
                "resolved_oatof_geometry_filename=resolved_oatof_geometry.json",
                f"resolved_oatof_geometry_sha256={file_sha256(layout_files['geometry'])}",
                "resolved_population_contract_filename=resolved_population_contract.json",
                f"resolved_population_contract_sha256={file_sha256(resolved_population_path)}",
                f"single_flight_layout_registry_sha256={repository_text_sha256(layout_files['registry'])}",
                "resolved_oatof_bore_radius_mm="
                + format(float(geometry["geometry_mm"]["bore_r"]), ".17g"),
                "resolved_oatof_ring_outer_radius_mm="
                + format(float(geometry["geometry_mm"]["ring_outer_r"]), ".17g"),
                "resolved_oatof_shield_inner_radius_mm="
                + format(float(geometry["geometry_mm"]["flight_tube_r"]), ".17g"),
            ]) + ([] if layout_files is None or "schedule" not in layout_files else [
                "resolved_single_flight_pulse_schedule_filename=resolved_single_flight_pulse_schedule.json",
                f"resolved_single_flight_pulse_schedule_sha256={file_sha256(layout_files['schedule'])}",
            ]) + ([] if layout_files is None or "three_zone_candidate" not in layout_files else [
                "single_flight_three_zone_candidate_path="
                + experiment["single_flight_three_zone_candidate"]["path"],
                "single_flight_three_zone_candidate_sha256="
                + experiment["single_flight_three_zone_candidate"]["sha256"],
            ]) + ([] if source_release_mode is None else [
                "source_release_mode=" + source_release_mode,
            ]) + ([] if source_profile_id is None else [
                "source_profile_id=" + source_profile_id,
                "field_overlay_id=" + field_overlay_id,
            ]) + ([] if pre_pulse_source_path is None else [
                "pre_pulse_source_state_path="
                + _workspace_relative(pre_pulse_source_path, workspace),
                "pre_pulse_source_state_sha256=" + pre_pulse_source_state["sha256"],
                "pre_pulse_source_state_count="
                + str(pre_pulse_source_state["particle_count"]),
            ]) + ([] if staged_grid2_source_path is None else [
                "staged_grid2_source_state_path="
                + _workspace_relative(staged_grid2_source_path, workspace),
                "staged_grid2_source_state_sha256="
                + staged_grid2_source_state["sha256"],
                "staged_grid2_source_state_count="
                + str(staged_grid2_source_state["particle_count"]),
                "staged_grid2_start_instance="
                + str(staged_grid2_source_state["simion_start_instance"]),
                "staged_grid2_clock_epoch_id="
                + staged_grid2_source_state["clock_epoch_id"],
                "staged_grid2_producer_run_id="
                + staged_grid2_source_state["producer_run_id"],
                "staged_grid2_producer_manifest_path="
                + staged_grid2_source_state["producer_manifest"]["path"],
                "staged_grid2_producer_manifest_sha256="
                + staged_grid2_source_state["producer_manifest"]["sha256"],
            ] + ([] if staged_grid2_bridge_receipt_path is None else [
                "staged_grid2_bridge_receipt_path="
                + _workspace_relative(staged_grid2_bridge_receipt_path, workspace),
                "staged_grid2_bridge_receipt_sha256="
                + file_sha256(staged_grid2_bridge_receipt_path),
            ])) + ([] if pre_pulse_source_path is None or source_materialization_profile is None else [
                "pre_pulse_restart_position_tolerance_mm="
                + format(float(pre_pulse_source_state["position_rowwise_abs_tolerance_mm"]), ".17g"),
                "pre_pulse_restart_velocity_tolerance_m_per_s="
                + format(float(pre_pulse_source_state["velocity_rowwise_abs_tolerance_m_per_s"]), ".17g"),
                "pre_pulse_restart_clock_tolerance_us="
                + format(float(pre_pulse_source_state["clock_abs_tolerance_us"]), ".17g"),
                "pre_pulse_restart_energy_tolerance_eV="
                + format(float(pre_pulse_source_state["energy_abs_tolerance_eV"]), ".17g"),
                "pre_pulse_restart_validation_filename="
                + pulse_restart_validation_path.name,
                "pre_pulse_restart_validation_sha256="
                + file_sha256(pulse_restart_validation_path),
            ]) + ([] if "single_flight_frontend_grid_profile_id" not in experiment else [
                "single_flight_frontend_grid_profile_id="
                + experiment["single_flight_frontend_grid_profile_id"],
            ]) + ([] if "single_flight_oatof_numerical_profile_id" not in experiment else [
                "single_flight_oatof_numerical_profile_id="
                + experiment["single_flight_oatof_numerical_profile_id"],
            ]) + ([] if "single_flight_trajectory_quality_profile_id" not in experiment else [
                "single_flight_trajectory_quality_profile_id="
                + experiment["single_flight_trajectory_quality_profile_id"],
            ]) + ([] if "single_flight_time_integration_profile_id" not in experiment else [
                "single_flight_time_integration_profile_id="
                + experiment["single_flight_time_integration_profile_id"],
            ]) + ([] if "single_flight_spatial_window_profile_id" not in experiment else [
                "single_flight_spatial_window_profile_id="
                + experiment["single_flight_spatial_window_profile_id"],
            ]) + ([] if resolved_region_field_contract_path is None else [
                "resolved_region_field_contract_filename=inputs/"
                + resolved_region_field_contract_path.name,
                "resolved_region_field_contract_sha256="
                + file_sha256(resolved_region_field_contract_path),
                "resolved_region_field_semantic_sha256="
                + str(resolved_region_field_contract["semantic_sha256"]),
                "resolved_region_field_profile_id="
                + str(resolved_region_field_contract["semantic"]["canonical_profile_id"]),
            ]) + ([] if three_zone_authorization is None else [
                name + "=" + value
                for name, value in three_zone_authorization.items()
            ]),
        }
    ]
    validate_schema(plan, "composition_plan.schema.json")
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    verify_composition_plan(plan_path, resolved_path, repo_root=root)
    return resolved_path, plan_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--profile-registry", required=True, type=Path)
    parser.add_argument("--adapter-registry", required=True, type=Path)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--resolved-output", required=True, type=Path)
    parser.add_argument("--plan-output", required=True, type=Path)
    args = parser.parse_args()
    resolved, plan = prepare_family_source_closure(
        repo_root=args.repo_root,
        profile_registry_path=args.profile_registry,
        adapter_registry_path=args.adapter_registry,
        campaign_path=args.campaign,
        experiment_id=args.experiment_id,
        resolved_output=args.resolved_output,
        plan_output=args.plan_output,
    )
    print(f"FAMILY_SOURCE_CLOSURE_PREPARE=PASS RESOLVED={resolved} PLAN={plan}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
