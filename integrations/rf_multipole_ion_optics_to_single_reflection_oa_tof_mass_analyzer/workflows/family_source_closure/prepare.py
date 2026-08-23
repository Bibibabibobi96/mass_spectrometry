"""Prepare one campaign-declared multipole-to-oaTOF execution."""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil
from typing import Any

from common.contracts.artifact_naming import validate_run_id
from common.contracts.component_particle_state import (
    validate_component_particle_state_csv,
)
from common.contracts.file_identity import (
    canonical_json_sha256 as _canonical_sha256,
    file_sha256,
    repository_text_sha256,
)
from common.contracts.machine_contracts import ContractError, validate_schema
from common.contracts.particle_count_policy import validate_standard_particle_count
from common.contracts.particle_physics import kinetic_energy_ev
from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.verify_artifact_layout import verify_verified_pulse_cache_entry
from common.integration.adapter_contract import (
    load_execution_adapter_registry,
    resolve_execution_mapping,
)
from common.integration.resolve_connection import (
    derive_mating_translation_with_gap,
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
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.select_real_field_pulse_time import (
    pulse_selection_content_identity,
)
from common.multipole.component_port import build_exit_component_port
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.resolved_region_field import (
    build_resolved_region_field_contract,
    canonical_profile_id,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.source_zvz_affine import (
    derive_three_zone_working_point,
    write_receipt as write_source_zvz_affine_receipt,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.resolved_population import (
    compile_resolved_population_contract,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.source_population import (
    write_source_population_receipt,
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
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.pulse_reuse_identity_projection import (
    build_verified_pulse_reuse_projection,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.materialize_manifest_bound_pre_pulse_restart import (
    materialize as materialize_manifest_bound_pre_pulse_restart,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_layout import (
    compile_geometry_and_port,
    derive_pulse_schedule,
    select_profile,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source import (
    materialize as materialize_single_flight_source,
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
AUTO_PULSE_POLICY_ID = "auto_detector_blind_discovery_and_confirmation_v1"
AUTO_PULSE_GRID_PROFILE_ID = "ballistic_seed_native_dt_minus0p35_plus1p65_v1"
PULSE_TRANSITION_RELATIVE_PATH = "results/pulse_timing_transition.json"
ACTIVE_POST_PULSE_WORKING_POINT_POLICY = (
    "source_zvz_three_zone_theory_working_point_required_v1"
)


def validate_active_post_pulse_restart_working_point(
    experiment: dict[str, Any],
) -> None:
    """Require automatic theory closure for an active restart row only."""
    if (
        experiment.get("source_release_mode") != "pre_pulse_restart"
        or experiment.get("post_pulse_restart_reuse_authority") is None
    ):
        return
    if (
        experiment.get("single_flight_source_zvz_affine_policy")
        != "source_zvz_affine_identify_and_bind_v1"
    ):
        raise ContractError(
            "active manifest-bound post-pulse restart requires source z--vz binding"
        )
    theory_request = experiment.get("single_flight_source_zvz_theory_working_point")
    if (
        not isinstance(theory_request, dict)
        or theory_request.get("policy_id")
        != "source_zvz_three_zone_theory_working_point_v1"
    ):
        raise ContractError(
            "active manifest-bound post-pulse restart requires the source z--vz theory working point"
        )
    authority = experiment["post_pulse_restart_reuse_authority"]
    if (
        not isinstance(authority, dict)
        or authority.get("post_pulse_variation_axis")
        != "accelerator_field_profile_id_and_source_zvz_theory_working_point"
    ):
        raise ContractError(
            "active manifest-bound post-pulse restart requires the theory variation axis"
        )


def _derive_pulse_discovery_run_id(original_run_id: str) -> str:
    """Derive one canonical internal discovery identity from the target run."""

    identity = validate_run_id(original_run_id)
    detail = identity.get("detail")
    if not isinstance(detail, str) or not detail.startswith("n"):
        raise ContractError("automatic pulse timing requires a particle-count run detail")
    retry = f"__r{identity['retry']}" if identity.get("retry") else ""
    run_id = (
        f"{identity['stamp']}__sim__cross__pulse-timing-discovery__{detail}{retry}"
    )
    validate_run_id(run_id)
    return run_id


def _materialize_pulse_discovery_package(
    *,
    source_directory: Path,
    stage_directory: Path,
    stage_plan_bytes: bytes,
    resolved_filename: str,
    repo_root: Path,
) -> None:
    """Publish one complete prepared discovery package or remove the partial copy."""

    if stage_directory.exists():
        raise ContractError("automatic pulse discovery run directory already exists")
    stage_directory.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(source_directory, stage_directory)
        stage_plan_path = stage_directory / "composition_plan.json"
        stage_plan_path.write_bytes(stage_plan_bytes)
        verify_composition_plan(
            stage_plan_path,
            stage_directory / resolved_filename,
            repo_root=repo_root,
        )
    except Exception:
        if (
            stage_directory.exists()
            and not (stage_directory / "run_manifest.json").exists()
        ):
            shutil.rmtree(stage_directory)
        raise


def _resolve_pulse_transition(
    workspace: Path, transition_path: Path,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Resolve a manifest-bound discovery transition into internal authority."""

    path = transition_path.resolve()
    artifacts = (workspace / "artifacts").resolve()
    if not path.is_relative_to(artifacts) or not path.is_file():
        raise ContractError("pulse timing transition is missing or escapes artifacts")
    transition = _load(path)
    validate_schema(transition, "rf_oatof_pulse_timing_transition.schema.json")
    parent_dir = path.parent.parent
    parent_manifest_path = parent_dir / "run_manifest.json"
    if not parent_manifest_path.is_file():
        raise ContractError("pulse timing transition parent manifest is missing")
    parent_manifest = _load(parent_manifest_path)
    if (
        parent_manifest.get("status") != "success"
        or parent_manifest.get("project") != INTEGRATION_ID
        or parent_manifest.get("run_id") != transition["discovery_run_id"]
    ):
        raise ContractError("pulse timing transition parent identity differs")
    transition_matches = []
    receipt_matches = []
    for record in parent_manifest.get("outputs", []):
        record_file = record_path(record, base_dir=parent_dir).resolve()
        if record_file == path:
            transition_matches.append(record)
        if record_file == (
            workspace / transition["candidate_selection_receipt"]["path"]
        ).resolve():
            receipt_matches.append(record)
    if len(transition_matches) != 1 or len(receipt_matches) != 1:
        raise ContractError("pulse timing transition is not uniquely manifest-bound")
    for label, record in (
        ("transition", transition_matches[0]),
        ("candidate selection receipt", receipt_matches[0]),
    ):
        try:
            verify_record(label, record, base_dir=parent_dir)
        except (AssertionError, KeyError, TypeError) as exc:
            raise ContractError(f"pulse timing {label} identity differs") from exc
    candidate_receipt_path = _workspace_record(
        workspace,
        transition["candidate_selection_receipt"],
        "pulse timing candidate selection receipt",
    )
    candidate_receipt = _load(candidate_receipt_path)
    if candidate_receipt.get("content_key") != transition["content_key"]:
        raise ContractError("pulse timing transition content key differs")
    authority = {
        "authority_mode": "detector_blind_candidate_confirmation_v1",
        "candidate_parent_manifest": {
            "path": _workspace_relative(parent_manifest_path, workspace),
            "sha256": file_sha256(parent_manifest_path),
        },
        "candidate_selection_receipt": {
            "path": _workspace_relative(candidate_receipt_path, workspace),
            "sha256": file_sha256(candidate_receipt_path),
        },
        "confirmation_policy_id": "identical_identity_pulse_on_full_flight_v1",
    }
    return authority, {
        "path": _workspace_relative(path, workspace),
        "sha256": file_sha256(path),
    }

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


def validate_connector_gap_screen_campaign(
    campaign: dict[str, Any], profile_registry: dict[str, Any],
) -> None:
    """Fail closed on the detector-blind five-row connector-gap matrix."""
    contract = campaign.get("connector_gap_screen")
    if contract is None:
        return
    rows = campaign["experiments"]
    profile_ids = (
        contract["primary_connection_profile_ids"]
        + contract["report_only_connection_profile_ids"]
    )
    if len(rows) != 5 or [row["connection_profile_id"] for row in rows] != profile_ids:
        raise ContractError("connector-gap campaign profile order differs")
    expected_roles = ["primary"] * 4 + ["stress_report_only"]
    if [row.get("connector_gap_evidence_role") for row in rows] != expected_roles:
        raise ContractError("connector-gap campaign evidence roles differ")
    profiles = {
        profile["connection_profile_id"]: profile
        for profile in profile_registry["profiles"]
    }
    observed_gaps: list[float] = []
    for profile_id in profile_ids:
        profile = profiles.get(profile_id)
        if profile is None:
            raise ContractError("connector-gap campaign profile is not registered")
        expected_gap = float(profile["spatial_registration"]["expected_gap_mm"])
        connector_length = float(profile["connector"]["length_mm"])
        if expected_gap != connector_length:
            raise ContractError("connector-gap profile registration and length differ")
        observed_gaps.append(expected_gap)
    if observed_gaps != [0.0, 3.2, 6.4, 12.8, 25.6]:
        raise ContractError("connector-gap campaign distance matrix differs")
    allowed_axes = set(contract["allowed_variation_axes"])
    normalized_rows = []
    for row in rows:
        try:
            validate_run_id(str(row["run_id"]))
        except (TypeError, ValueError) as exc:
            raise ContractError("connector-gap campaign run_id is invalid") from exc
        source = row.get("source", {})
        population = row.get("single_flight_population", {})
        execution = population.get("execution_population", {})
        denominators = population.get("denominators", {})
        authority = population.get("source_authority", {})
        if (
            row.get("source_release_mode") != "continuous_frontend"
            or any(key in row for key in (
                "pre_pulse_source_state", "generated_pre_pulse_ordered_subset",
                "observed_pre_pulse_projection", "staged_grid2_source_state",
            ))
            or source.get("authority_scope") != "source_population"
            or source.get("launched_particle_count") != contract["mother_sample_count"]
            or source.get("particle_source", {}).get("sha256")
            != contract["mother_particle_source_sha256"]
            or population.get("population_mode")
            != "first_100_rows_in_frozen_file_order"
            or authority.get("table_binding") != "prepared_deterministic_prefix"
            or authority.get("input_role") != "connector_gap_screening_prefix"
            or execution.get("particle_count") != contract["screening_prefix_count"]
            or execution.get("ordered_particle_id_sha256")
            != contract["ordered_particle_id_sha256"]
            or execution.get("selection_algorithm") != contract["selection_algorithm"]
            or denominators.get("population_count")
            != contract["original_denominator_count"]
            or denominators.get("eligible_population_count")
            != contract["original_denominator_count"]
        ):
            raise ContractError("connector-gap source or population identity differs")
        normalized_rows.append({
            key: value for key, value in row.items() if key not in allowed_axes
        })
    if any(row != normalized_rows[0] for row in normalized_rows[1:]):
        raise ContractError("connector-gap campaign changes a frozen control")


def _automatic_pulse_population_binding(
    population: dict[str, Any],
) -> tuple[str, int]:
    """Return the population-table bindings supported by auto pulse timing."""

    authority = population.get("source_authority", {})
    execution = population.get("execution_population", {})
    count = execution.get("particle_count")
    identity = (
        population.get("population_mode"),
        authority.get("table_binding"),
        execution.get("selection_algorithm"),
    )
    if identity == (
        "first_100_rows_in_frozen_file_order",
        "prepared_deterministic_prefix",
        "first_100_rows_in_frozen_file_order",
    ) and count == 100:
        return "prepared_deterministic_prefix", 100
    if identity == (
        "continuous_injection_full_population",
        "source_contract_particle_source",
        "all_rows_in_frozen_file_order",
    ) and isinstance(count, int) and not isinstance(count, bool) and count > 0:
        return "source_contract_particle_source", count
    raise ContractError("automatic pulse timing population differs")


def resolve_single_flight_dispatch_plan(
    experiment: dict[str, Any], *, execution_particle_count: int,
    workspace: Path | None = None,
) -> dict[str, Any]:
    """Resolve execution-only dispatch without deriving the governed population.

    The returned object is an execution artifact only.  It never contributes to
    campaign or handoff identity; those remain defined by the resolved source
    and numerical contracts.  Legacy rows are represented explicitly so their
    frozen behavior is observable while new memory-policy rows retain the
    scheduler's automatic decision.
    """

    memory_policy = experiment.get("single_flight_batch_memory_policy")
    if memory_policy is not None:
        if workspace is None:
            raise ContractError("single-flight memory batch policy lacks workspace context")
        receipt_ref = memory_policy["resource_usage_receipt"]
        receipt_path = (workspace / receipt_ref["path"]).resolve()
        if not receipt_path.is_file() or file_sha256(receipt_path) != receipt_ref["sha256"]:
            raise ContractError("single-flight memory batch receipt is missing or differs")
        receipt = _load(receipt_path)
        peak = receipt.get("peak_process_tree_working_set_bytes")
        if isinstance(peak, bool) or not isinstance(peak, int) or peak < 1:
            raise ContractError("single-flight memory batch receipt lacks a positive peak")
        from common.simion.resource_scheduler import plan_simion_dispatch
        try:
            time_profile = str(experiment["single_flight_time_integration_profile_id"])
            if not time_profile.startswith("dt") or not time_profile[2:].isdigit():
                raise ValueError("single-flight RF time profile lacks its steps per period")
            request = {
                "solver": "SIMION",
                "field_kind": "rf",
                "rf_steps_per_period": int(time_profile[2:]),
                "particle_count": execution_particle_count,
                "independent_particles": True,
                "default_parallel_batches": int(memory_policy.get("default_batch_count", 1)),
                "maximum_parallel_batches": int(memory_policy.get("maximum_batch_count", execution_particle_count)),
                # The receipt is already the measured upper bound used for a
                # one-batch bootstrap when no exact profile identity matches.
                "unknown_per_batch_reservation_bytes": peak,
                "reserve_available_memory_bytes": int(memory_policy["reserve_available_memory_bytes"]),
                "memory_safety_numerator": int(memory_policy.get("memory_safety_numerator", 115)),
                "memory_safety_denominator": int(memory_policy.get("memory_safety_denominator", 100)),
                "cpu_cores_per_batch": int(memory_policy.get("cpu_cores_per_batch", 1)),
                "reserve_cpu_cores": int(memory_policy.get("reserve_cpu_cores", 0)),
                "frontend_grid_profile_id": experiment.get("single_flight_frontend_grid_profile_id"),
                "oatof_numerical_profile_id": experiment.get("single_flight_oatof_numerical_profile_id"),
                "trajectory_quality_profile_id": experiment.get("single_flight_trajectory_quality_profile_id"),
                "time_integration_profile_id": time_profile,
                "accelerator_field_profile_id": experiment.get("single_flight_accelerator_field_profile_id"),
            }
            profile = {
                "resource_identity": {
                    key: request[key]
                    for key in (
                        "solver", "field_kind", "rf_steps_per_period",
                        "frontend_grid_profile_id", "oatof_numerical_profile_id",
                        "trajectory_quality_profile_id", "time_integration_profile_id",
                        "accelerator_field_profile_id",
                    )
                },
                "per_batch_peak_working_set_bytes": peak,
            }
            decision = plan_simion_dispatch(
                request, [profile],
            )
        except ValueError as error:
            raise ContractError("single-flight memory batch policy is invalid") from error
        return decision

    value = experiment.get("single_flight_batch_count", 1)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError("single-flight batch count must be an integer")
    if not 1 <= value <= execution_particle_count:
        raise ContractError(
            "single-flight batch count must be between one and the resolved population count"
        )
    return {
        "schema_version": 1,
        "role": "simion_legacy_fixed_dispatch_plan",
        "solver": "SIMION",
        "field_kind": "rf",
        "particle_count": execution_particle_count,
        "resource_identity": {},
        "estimation": {
            "kind": "legacy_explicit_batch_count",
            "reason": "campaign_row_preserves_frozen_execution_contract",
        },
        "limits": {"maximum_parallel_batches": value},
        "waves": [{
            "index": 1,
            "kind": "legacy_fixed",
            "batch_count": value,
            "particle_count": execution_particle_count,
        }],
    }


def resolve_single_flight_batch_count(
    experiment: dict[str, Any], *, execution_particle_count: int,
    workspace: Path | None = None,
) -> int:
    """Compatibility projection of the resolved dispatch plan."""

    plan = resolve_single_flight_dispatch_plan(
        experiment,
        execution_particle_count=execution_particle_count,
        workspace=workspace,
    )
    return int(plan["waves"][0]["batch_count"])


def validate_pre_pulse_time_series_campaign(campaign: dict[str, Any]) -> None:
    """Fail closed on a one-row detector-blind actual-field time screen."""

    contract = campaign.get("pre_pulse_time_series_screening")
    if contract is None:
        return
    rows = campaign["experiments"]
    if len(rows) != 1 or "FUNCTIONAL_ONLY" not in campaign["claim_limit"]:
        raise ContractError("pre-pulse time-series campaign scope differs")
    row = rows[0]
    source = row["source"]
    population = row["single_flight_population"]
    execution = population["execution_population"]
    denominators = population.get("denominators", {})
    source_authority = population.get("source_authority", {})
    if (
        contract.get("active_scope") != "pre_pulse_frontend_accelerator"
        or contract.get("pa_cache_keys", {}).get("flight_tube") is not None
        or contract.get("pa_cache_keys", {}).get("reflectron") is not None
        or source.get("authority_scope") != "source_population"
        or not isinstance(source.get("launched_particle_count"), int)
        or source["launched_particle_count"] < execution.get("particle_count", 0)
        or population.get("population_mode")
        != "first_100_rows_in_frozen_file_order"
        or source_authority.get("table_binding") != "prepared_deterministic_prefix"
        or execution.get("selection_algorithm")
        != "first_100_rows_in_frozen_file_order"
        or denominators.get("population_count") != execution.get("particle_count")
        or denominators.get("eligible_population_count")
        != execution.get("particle_count")
        or contract["sample_count"]
        != contract["relative_end_index"] - contract["relative_start_index"] + 1
    ):
        raise ContractError("pre-pulse time-series source, population, or grid differs")


def compile_pre_pulse_time_series_contract(
    *, campaign: dict[str, Any], experiment: dict[str, Any],
    experiment_row_sha256: str, upstream_resolved_design: dict[str, Any],
    resolved_source_contract_sha256: str, resolved_population_contract_sha256: str,
    prepared_prefix_sha256: str, layout_profile: dict[str, Any],
    selected_field_profile: dict[str, Any], region_field_semantic_sha256: str,
    rf_steps_per_period: int, specification: dict[str, Any] | None = None,
    base_schedule: dict[str, Any] | None = None,
    time_integration_profile_id: str | None = None,
) -> dict[str, Any]:
    """Compile exact RF-grid sample times and all runner-checked identities."""

    specification = (
        campaign["pre_pulse_time_series_screening"]
        if specification is None
        else specification
    )
    drive = upstream_resolved_design["drive"]
    frequency_hz = float(drive["frequency_Hz"])
    if rf_steps_per_period != specification["rf_steps_per_period"]:
        raise ContractError("pre-pulse time-series upstream RF grid differs")
    expected_frequency = specification.get("expected_upstream_frequency_hz")
    if expected_frequency is not None and frequency_hz != float(expected_frequency):
        raise ContractError("pre-pulse time-series upstream RF grid differs")
    period_us = 1_000_000.0 / frequency_hz
    step_us = period_us / rf_steps_per_period
    relative_start = int(specification["relative_start_index"])
    relative_end = int(specification["relative_end_index"])
    automatic = base_schedule is not None
    seed_time_us = float(
        base_schedule["pulse_effective_time_us"]
        if automatic
        else specification["anchor_time_us"]
    )
    grid_origin_us = seed_time_us + relative_start * step_us
    sample_count = relative_end - relative_start + 1
    sample_times_us = [grid_origin_us + index * step_us for index in range(sample_count)]
    if (
        sample_count != specification["sample_count"]
        or not math.isclose(sample_times_us[-1], seed_time_us + relative_end * step_us,
                            rel_tol=1e-15, abs_tol=1e-15)
        or not all(right > left for left, right in zip(
            sample_times_us, sample_times_us[1:], strict=False
        ))
    ):
        raise ContractError("pre-pulse time-series RF grid does not close")
    contract = {
        "schema_version": 2 if automatic else 1,
        "role": "rf_oatof_pre_pulse_time_series_screening_contract",
        "mode": specification["mode"],
        "active_scope": specification["active_scope"],
        "claim_limit": "FUNCTIONAL_ONLY",
        "identities": {
            "campaign_id": campaign["campaign_id"],
            "experiment_id": experiment["experiment_id"],
            "experiment_row_sha256": experiment_row_sha256,
            "connection_profile_id": experiment["connection_profile_id"],
            "source_profile_id": experiment["source_profile_id"],
            "resolved_source_contract_sha256": resolved_source_contract_sha256,
            "resolved_population_contract_sha256": resolved_population_contract_sha256,
            "mother_particle_source_sha256": prepared_prefix_sha256,
            "ordered_particle_id_sha256": experiment["single_flight_population"]
                ["execution_population"]["ordered_particle_id_sha256"],
            "layout_profile_id": experiment["single_flight_layout_profile_id"],
            "architecture_generation_id": experiment["architecture_generation_id"],
            "topology_id": layout_profile["topology_id"],
            "geometry_id": layout_profile["geometry_id"],
            "frontend_electrode_topology_id": layout_profile["frontend_electrode_topology_id"],
            "field_id": selected_field_profile["field_id"],
            "field_profile_id": experiment["single_flight_accelerator_field_profile_id"],
            "region_field_semantic_sha256": region_field_semantic_sha256,
            "frontend_grid_profile_id": experiment["single_flight_frontend_grid_profile_id"],
            "field_overlay_id": experiment["field_overlay_id"],
            "oatof_numerical_profile_id": experiment["single_flight_oatof_numerical_profile_id"],
            "trajectory_quality_profile_id": experiment["single_flight_trajectory_quality_profile_id"],
            "time_integration_profile_id": (
                experiment["single_flight_time_integration_profile_id"]
                if time_integration_profile_id is None
                else time_integration_profile_id
            ),
            "spatial_window_profile_id": specification["spatial_window_profile_id"],
        },
        **(
            {"pa_cache_roles": {
                "identity_source": "runner_materialized_verified_pa_cache_receipt",
                "required": ["frontend", "accelerator_overlay"],
                "prohibited": ["flight_tube", "reflectron"],
            }}
            if automatic
            else {"pa_cache_keys": copy.deepcopy(specification["pa_cache_keys"])}
        ),
        "rf_time_grid": {
            "derivation": (
                "ballistic_seed_time_us + relative_index*period_us/rf_steps_per_period"
                if automatic
                else "grid_origin_us + sample_index*period_us/rf_steps_per_period"
            ),
            "waveform": drive["waveform"], "frequency_hz": frequency_hz,
            "phase_rad": float(drive["phase_rad"]),
            "rf_steps_per_period": rf_steps_per_period,
            "period_us": period_us, "step_us": step_us,
            **(
                {
                    "time_grid_profile_id": specification["time_grid_profile_id"],
                    "ballistic_seed_time_us": seed_time_us,
                    "ballistic_seed_sample_index": -relative_start,
                }
                if automatic
                else {
                    "anchor_time_us": seed_time_us,
                    "anchor_sample_index": -relative_start,
                }
            ),
            "grid_origin_us": grid_origin_us,
            "requested_relative_start_index": relative_start,
            "requested_relative_end_index": relative_end,
            "start_index": 0, "end_index": sample_count - 1,
            "sample_count": sample_count,
        },
        "sample_times_us": sample_times_us,
        **(
            {"selection_order": copy.deepcopy(specification["selection_order"])}
            if "selection_order" in specification
            else {}
        ),
        "pulse_disabled": specification["pulse_disabled"],
        "terminate_at_window_end": specification["terminate_at_window_end"],
        "resolution_claim_allowed": specification["resolution_claim_allowed"],
        "prohibited_outputs": copy.deepcopy(specification["prohibited_outputs"]),
    }
    candidate = experiment.get("single_flight_three_zone_candidate")
    if isinstance(candidate, dict):
        contract["identities"]["candidate_sha256"] = candidate["sha256"]
    validate_schema(
        contract, "rf_oatof_pre_pulse_time_series_screening_contract.schema.json"
    )
    return contract


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


def expand_flat_experiment_authoring(campaign: dict[str, Any]) -> dict[str, Any]:
    """Expand shared experiment controls and explicit per-row variation axes.

    The on-disk authoring form remains compact.  Consumers receive the same
    fully materialized rows as the legacy array form, so every selected run can
    still freeze one complete, independently verifiable contract.
    """
    source = campaign.get("experiments")
    if isinstance(source, list):
        return campaign
    if not isinstance(source, dict):
        raise ContractError("experiments must be an array or flat authoring object")
    if set(source) != {"shared", "variation_axes", "rows"}:
        raise ContractError("flat experiment authoring keys differ")
    shared = source["shared"]
    axes = source["variation_axes"]
    rows = source["rows"]
    if not isinstance(shared, dict) or not isinstance(axes, list) or not isinstance(rows, list):
        raise ContractError("flat experiment authoring shape differs")
    if not axes or any(not isinstance(axis, str) or not axis for axis in axes) or len(axes) != len(set(axes)):
        raise ContractError("flat experiment variation axes are invalid")
    row_identity = {"sequence", "experiment_id", "run_id"}
    if set(axes).intersection(row_identity):
        raise ContractError("flat experiment variation axes cannot contain row identity")
    expanded: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"sequence", "experiment_id", "run_id", "overrides"}:
            raise ContractError("flat experiment row must contain identity and overrides only")
        overrides = row["overrides"]
        if not isinstance(overrides, dict) or not set(overrides).issubset(set(axes)):
            raise ContractError("flat experiment row override is not an allowed variation axis")
        materialized = copy.deepcopy(shared)
        if set(materialized).intersection(row_identity):
            raise ContractError("flat experiment shared controls cannot contain row identity")
        materialized.update(copy.deepcopy(overrides))
        materialized.update({key: row[key] for key in ("sequence", "experiment_id", "run_id")})
        expanded.append(materialized)
    if not expanded:
        raise ContractError("flat experiment authoring must contain at least one row")
    result = copy.deepcopy(campaign)
    result["experiments"] = expanded
    return result


def _semantic_diff_category(path: tuple[str, ...]) -> str:
    """Classify a resolved field for review output only, never for policy."""

    top_level = path[0] if path else ""
    if top_level in {"sequence", "experiment_id", "run_id"}:
        return "run_control"
    if top_level in {
        "source",
        "single_flight_design_reference",
        "post_pulse_restart_reuse_authority",
    } or any(part.endswith("sha256") for part in path):
        return "evidence_or_provenance"
    if top_level in {"single_flight_population", "analysis_randomness"}:
        return "source_cohort_or_sampling"
    if top_level in {
        "resolution_qualification",
        "claim_limit",
        "spatial_window_profile_id",
        "source_region_diagnostic_profile_id",
    }:
        return "analysis_or_qualification"
    if top_level in {
        "single_flight_batch_memory_policy",
        "single_flight_batch_count",
        "execution_strategy",
    } or any(
        token in part
        for part in path
        for token in ("grid", "numerical", "trajectory", "time_profile")
    ):
        return "solver_numerics_or_resource_control"
    if top_level in {
        "connection_profile_id",
        "source_profile_id",
        "accelerator_field_profile_id",
        "single_flight_accelerator_field_profile_id",
        "field_profile_id",
        "source_zvz_theory_working_point",
    }:
        return "physical_design_or_field"
    return "declared_configuration"


def _semantic_diff_values(
    before: object, after: object, path: tuple[str, ...] = ()
) -> list[dict[str, Any]]:
    if isinstance(before, dict) and isinstance(after, dict):
        changes: list[dict[str, Any]] = []
        for key in sorted(set(before) | set(after)):
            changes.extend(
                _semantic_diff_values(before.get(key), after.get(key), path + (key,))
            )
        return changes
    if before == after:
        return []
    return [{
        "path": ".".join(path),
        "category": _semantic_diff_category(path),
        "before": before,
        "after": after,
    }]


def semantic_diff_experiments(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic, review-only diff of two materialized rows."""

    changes = _semantic_diff_values(before, after)
    return {
        "role": "rf_oatof_campaign_semantic_diff",
        "classification_scope": "review_only_not_execution_policy",
        "before_experiment_id": before.get("experiment_id"),
        "after_experiment_id": after.get("experiment_id"),
        "changed_field_count": len(changes),
        "changes": changes,
    }


def _is_solver_authorized_consumer(row: dict[str, Any]) -> bool:
    """Return whether a row consumes a hash-bound N=1 solver authorization."""

    return row["three_zone_solver_gate"]["stage"] in {
        "n100_solver_authorized_consumer", "solver_authorized_consumer"
    }


def _validate_three_zone_gate_pair(
    gated: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate one N=1 producer and its hash-bound solver consumer."""

    if len(gated) != 2:
        raise ContractError("each three-zone solver gate requires exactly two rows")
    producers = [
        row for row in gated
        if row["three_zone_solver_gate"]["stage"] == "n1_smoke_producer"
    ]
    consumers = [
        row for row in gated
        if _is_solver_authorized_consumer(row)
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
    consumer_stage = consumer["three_zone_solver_gate"]["stage"]
    if consumer_stage == "solver_authorized_consumer":
        count = consumer.get("single_flight_population", {}).get(
            "execution_population", {}
        ).get("particle_count")
        if not isinstance(count, int) or count < 1:
            raise ContractError("three-zone solver gate successor particle count is invalid")
        expected = ((producer, 1, "n1_center_source_id_500_v1", "080A9ED428559EF602668B4C00F114F1A11C3F6B02A435F0BDC154578E4D7F22"),)
    else:
        expected = ()
    realization = (
        producer.get("single_flight_layout_profile_id"),
        producer.get("architecture_generation_id"),
        consumer.get("generated_pre_pulse_ordered_subset", {}).get("selection_id"),
    )
    layout_profile_id = producer.get("single_flight_layout_profile_id")
    architecture_generation_id = producer.get("architecture_generation_id")
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
    if consumer_stage == "n100_solver_authorized_consumer" and realization not in supported_realizations:
        raise ContractError(
            "three-zone solver gate layout, architecture, or N=100 selection differs"
        )
    if consumer_stage == "n100_solver_authorized_consumer":
        _, _, n100_selection_id = realization
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
    consumer_stage = consumer["three_zone_solver_gate"]["stage"]
    expected_schema_version = 1 if consumer_stage == "n100_solver_authorized_consumer" else 2
    expected_status = (
        "N100_SOLVER_AUTHORIZED"
        if consumer_stage == "n100_solver_authorized_consumer"
        else "SOLVER_AUTHORIZED"
    )
    expected_particle_count = consumer["single_flight_population"][
        "execution_population"
    ]["particle_count"]
    if (
        receipt.get("schema_version") != expected_schema_version
        or receipt.get("gate_id") != producer["three_zone_solver_gate"]["gate_id"]
        or receipt.get("decision") != "PASS"
        or receipt.get("authorization_status") != expected_status
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
            "particle_count": expected_particle_count,
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


def _resolve_candidate_confirmation_schedule(
    *, root: Path, experiment: dict[str, Any], policy: dict[str, Any],
    authority: dict[str, Any],
    population_declaration: dict[str, Any], prepared_prefix_sha256: str,
    resolved_connection_path: Path, resolved_source_path: Path,
    resolved_geometry_path: Path, single_flight_configuration: dict[str, Any],
    base_schedule: dict[str, Any], pilot_verified_receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Compile one pulse-on schedule from a manifest-bound detector-blind candidate."""

    if authority["authority_mode"] != "detector_blind_candidate_confirmation_v1":
        raise ContractError("candidate pulse confirmation authority mode is unsupported")
    workspace = root.parent
    parent_manifest_path = _workspace_record(
        workspace, authority["candidate_parent_manifest"],
        "pulse candidate parent manifest",
    )
    candidate_receipt_path = _workspace_record(
        workspace, authority["candidate_selection_receipt"],
        "pulse candidate selection receipt",
    )
    parent_manifest = _load(parent_manifest_path)
    if (
        parent_manifest.get("role") != "simulation_run_manifest"
        or parent_manifest.get("status") != "success"
        or parent_manifest.get("project") != INTEGRATION_ID
        or parent_manifest.get("mode") not in {
            "multipole_family_source_closure",
            "detector_blind_real_field_pulse_timing_candidate_replay",
        }
        or parent_manifest.get("formal_eligible") is not False
    ):
        raise ContractError("pulse candidate parent manifest identity differs")
    try:
        verify_record(
            "pulse candidate parent run_config", parent_manifest["run_config"],
            base_dir=parent_manifest_path.parent,
        )
        receipt_records = [
            record for record in parent_manifest.get("outputs", [])
            if record_path(record, base_dir=parent_manifest_path.parent).resolve()
            == candidate_receipt_path.resolve()
        ]
        if len(receipt_records) != 1:
            raise ContractError("pulse candidate receipt is not a unique parent output")
        verify_record(
            "pulse candidate receipt", receipt_records[0],
            base_dir=parent_manifest_path.parent,
        )
    except (AssertionError, KeyError, TypeError) as exc:
        raise ContractError("pulse candidate parent manifest verification failed") from exc
    receipt = _load(candidate_receipt_path)
    validate_schema(
        receipt,
        "rf_oatof_detector_blind_pulse_timing_candidate_receipt.schema.json",
    )
    if (
        receipt.get("status") != "success"
        or receipt.get("qualification") != "candidate_selection"
        or receipt.get("reusable_verified_pulse") is not False
        or receipt.get("pulse_confirmation_status") != "NOT_RUN"
        or receipt.get("detector_results_used") is not False
        or receipt.get("selection_uses_detector_outcome") is not False
    ):
        raise ContractError("pulse candidate receipt qualification differs")

    def receipt_authority(name: str) -> Path:
        record = receipt.get("authorities", {}).get(name)
        if not isinstance(record, dict):
            raise ContractError(f"pulse candidate authority is missing: {name}")
        return _workspace_record(workspace, record, f"pulse candidate {name}")

    screening_contract = _load(receipt_authority("pre_pulse_time_series_contract"))
    candidate_population = _load(receipt_authority("resolved_population_contract"))
    candidate_population_table = receipt_authority("population_table")
    selector_record = receipt.get("authorities", {}).get("selector_source")
    if not isinstance(selector_record, dict):
        raise ContractError("pulse candidate selector source identity differs")
    current_geometry = _load(resolved_geometry_path)
    profile_id = screening_contract["identities"]["spatial_window_profile_id"]
    profiles = [
        profile
        for profile in single_flight_configuration[
            "source_region_diagnostic_profiles"
        ]
        if profile.get("profile_id") == profile_id
    ]
    execution_population = population_declaration["execution_population"]
    candidate_execution = candidate_population["execution_population"]
    winner_population = receipt["candidates_ranked"][0]["population_identity"]
    if (
        len(profiles) != 1
        or file_sha256(candidate_population_table)
        != candidate_population["source_authority"]["table"]["sha256"]
        or candidate_execution["particle_count"] != winner_population["count"]
        or candidate_execution["ordered_particle_id_sha256"]
        != winner_population["ordered_particle_id_sha256"]
    ):
        raise ContractError("pulse candidate population identity differs")
    if pilot_verified_receipt_path is None and (
        _automatic_pulse_population_binding(population_declaration)[0]
        != population_declaration["source_authority"]["table_binding"]
        or prepared_prefix_sha256 != file_sha256(candidate_population_table)
        or execution_population["particle_count"] != winner_population["count"]
        or execution_population["ordered_particle_id_sha256"]
        != winner_population["ordered_particle_id_sha256"]
    ):
        raise ContractError("pulse candidate confirmation population identity differs")
    current_identities = {
        "connection_profile_id": experiment["connection_profile_id"],
        "source_profile_id": experiment["source_profile_id"],
        "layout_profile_id": experiment["single_flight_layout_profile_id"],
        "architecture_generation_id": experiment["architecture_generation_id"],
        "frontend_grid_profile_id": experiment["single_flight_frontend_grid_profile_id"],
        "field_overlay_id": experiment["field_overlay_id"],
        "oatof_numerical_profile_id": experiment["single_flight_oatof_numerical_profile_id"],
        "trajectory_quality_profile_id": experiment[
            "single_flight_trajectory_quality_profile_id"
        ],
        "spatial_window_profile_id": policy["cache_miss_policy"][
            "spatial_window_profile_id"
        ],
    }
    candidate = experiment.get("single_flight_three_zone_candidate")
    if isinstance(candidate, dict):
        current_identities["candidate_sha256"] = candidate["sha256"]
    if any(
        screening_contract["identities"].get(key) != value
        for key, value in current_identities.items()
    ) or (
        screening_contract["rf_time_grid"].get("time_grid_profile_id")
        != policy["cache_miss_policy"]["time_grid_profile_id"]
        or not math.isclose(
            float(screening_contract["rf_time_grid"]["period_us"]),
            float(base_schedule["rf_period_us"]), rel_tol=0.0, abs_tol=1e-15,
        )
    ):
        raise ContractError("pulse candidate physical identity differs")
    current_source = _load(resolved_source_path)
    current_connection = _load(resolved_connection_path)
    content_basis, content_key = pulse_selection_content_identity(
        contract=screening_contract,
        source=current_source,
        connection=current_connection,
        geometry=current_geometry,
        spatial_profile=profiles[0],
        selector_source_sha256=selector_record.get("sha256"),
        pa_cache_keys=receipt.get("pa_cache_keys"),
    )
    reuse_basis, verified_content_key = build_verified_pulse_reuse_projection(
        screening_contract=screening_contract,
        resolved_source=current_source,
        resolved_connection=current_connection,
        resolved_geometry=current_geometry,
        spatial_profile=profiles[0],
        pa_cache_keys=receipt.get("pa_cache_keys", {}),
    )
    selected_time_us = float(receipt["selected_time_us"])
    receipt_key_is_valid = (
        receipt.get("content_key") == _canonical_sha256(receipt["content_key_basis"])
    )
    if pilot_verified_receipt_path is None:
        content_identity_matches = (
            content_basis == receipt["content_key_basis"]
            and content_key == receipt["content_key"]
        )
    else:
        pilot_receipt = _load(pilot_verified_receipt_path)
        stored_reuse_basis = receipt.get("verified_reuse_content_key_basis")
        stored_reuse_key = receipt.get("verified_reuse_content_key")
        content_identity_matches = (
            math.isclose(
                float(pilot_receipt.get("selected_time_us")), selected_time_us,
                rel_tol=0.0, abs_tol=1e-12,
            )
            and (
                stored_reuse_basis is None
                or (
                    stored_reuse_basis == reuse_basis
                    and stored_reuse_key == verified_content_key
                    and stored_reuse_key == _canonical_sha256(stored_reuse_basis)
                )
            )
        )
    if (
        not receipt_key_is_valid
        or not content_identity_matches
        or not math.isfinite(selected_time_us)
        or selected_time_us <= 0
        or not math.isclose(
            float(base_schedule["pulse_effective_time_us"]),
            float(receipt["ballistic_seed_time_us"]),
            rel_tol=0.0, abs_tol=1e-12,
        )
    ):
        raise ContractError("pulse candidate content identity or time differs")
    schedule = copy.deepcopy(base_schedule)
    schedule.update({
        "method": "detector_blind_real_field_pulse_timing_candidate_confirmation_v1",
        "pulse_base_time_us": selected_time_us,
        "pulse_offset_us": 0.0,
        "pulse_effective_time_us": selected_time_us,
        "claim_status": "FUNCTIONAL_ONLY",
        "execution_authority": {
            "mode": authority["authority_mode"],
            "content_key": verified_content_key,
            "candidate_parent_manifest": {
                "path": _workspace_relative(parent_manifest_path, workspace),
                "sha256": file_sha256(parent_manifest_path),
            },
            "candidate_selection_receipt": {
                "path": _workspace_relative(candidate_receipt_path, workspace),
                "sha256": file_sha256(candidate_receipt_path),
            },
            "selection_preregistered": receipt["selection_preregistered"],
            "confirmation_selection_authorized": True,
            "confirmation_policy_id": authority["confirmation_policy_id"],
        },
    })
    if pilot_verified_receipt_path is not None:
        schedule["execution_authority"]["pilot_verified_receipt"] = {
            "path": _workspace_relative(pilot_verified_receipt_path, workspace),
            "sha256": file_sha256(pilot_verified_receipt_path),
        }
    return schedule


def _select_strongest_verified_pulse_match(
    matches: list[dict[str, Any]],
) -> dict[str, Any]:
    """Choose the largest confirmed population, failing tied time ambiguity."""
    strongest_count = max(match["population_count"] for match in matches)
    strongest = [
        match for match in matches if match["population_count"] == strongest_count
    ]
    selected_time_us = float(strongest[0]["receipt"]["selected_time_us"])
    if any(
        not math.isclose(
            float(match["receipt"]["selected_time_us"]), selected_time_us,
            rel_tol=0.0, abs_tol=1e-12,
        )
        for match in strongest[1:]
    ):
        raise ContractError("strongest verified pulse cache times are ambiguous")
    return sorted(
        strongest,
        key=lambda match: (
            not match["native"], match["receipt_path"].as_posix()
        ),
    )[0]


def _resolve_cached_verified_pulse_schedule(
    *, root: Path, experiment: dict[str, Any], policy: dict[str, Any],
    population_declaration: dict[str, Any], prepared_prefix_sha256: str,
    resolved_connection_path: Path, resolved_source_path: Path,
    resolved_geometry_path: Path, single_flight_configuration: dict[str, Any],
    base_schedule: dict[str, Any],
) -> dict[str, Any] | None:
    """Reuse a verified pulse receipt when the full content identity matches."""

    workspace = root.parent
    cache_root = (
        workspace / "artifacts" / "projects" / INTEGRATION_ID
        / "cache" / "verified_pulse"
    )
    if not cache_root.is_dir():
        return None
    matches: list[dict[str, Any]] = []
    for receipt_path in sorted(cache_root.glob("*/verified_pulse_timing_receipt.json")):
        try:
            receipt = verify_verified_pulse_cache_entry(
                receipt_path.parent,
                workspace_root=workspace,
                verify_hashes=True,
            )
        except (AssertionError, OSError, ValueError):
            continue
        validate_schema(receipt, "rf_oatof_verified_pulse_timing_receipt.schema.json")
        candidate = receipt["candidate_authority"]
        candidate_authority = {
            "authority_mode": "detector_blind_candidate_confirmation_v1",
            "candidate_parent_manifest": {
                key: candidate["parent_manifest"][key] for key in ("path", "sha256")
            },
            "candidate_selection_receipt": {
                key: candidate["selection_receipt"][key] for key in ("path", "sha256")
            },
            "confirmation_policy_id": "identical_identity_pulse_on_full_flight_v1",
        }
        try:
            schedule = _resolve_candidate_confirmation_schedule(
                root=root,
                experiment=experiment,
                policy=policy,
                authority=candidate_authority,
                population_declaration=population_declaration,
                prepared_prefix_sha256=prepared_prefix_sha256,
                resolved_connection_path=resolved_connection_path,
                resolved_source_path=resolved_source_path,
                resolved_geometry_path=resolved_geometry_path,
                single_flight_configuration=single_flight_configuration,
                base_schedule=base_schedule,
                pilot_verified_receipt_path=receipt_path,
            )
        # A cache entry is advisory until its full candidate lineage parses
        # and verifies.  Historical/interrupted publications can leave a
        # truncated candidate receipt behind; it must not block an unrelated
        # current experiment from finding another valid entry or discovering
        # its own detector-blind pulse.
        except (ContractError, OSError, ValueError):
            continue
        if math.isclose(
            schedule["pulse_effective_time_us"], receipt["selected_time_us"],
            rel_tol=0.0, abs_tol=1e-12,
        ):
            selection_receipt_path = _workspace_record(
                workspace, candidate["selection_receipt"],
                "verified pulse selection receipt",
            )
            selection_receipt = _load(selection_receipt_path)
            selection_count = selection_receipt.get("population_denominator_count")
            confirmation_count = receipt.get("census", {}).get("launched")
            if (
                not isinstance(selection_count, int)
                or not isinstance(confirmation_count, int)
                or selection_count <= 0
                or selection_count != confirmation_count
            ):
                raise ContractError("verified pulse population evidence differs")
            matches.append({
                "receipt_path": receipt_path,
                "receipt": receipt,
                "schedule": schedule,
                "population_count": confirmation_count,
                "native": (
                    receipt["content_key"]
                    == schedule["execution_authority"]["content_key"]
                ),
            })
    if not matches:
        return None
    selected = _select_strongest_verified_pulse_match(matches)
    receipt_path = selected["receipt_path"]
    receipt = selected["receipt"]
    schedule = selected["schedule"]
    for name in ("child_manifest", "pulse_schedule", "summary"):
        _workspace_record(
            workspace, receipt["verification_authority"][name],
            f"verified pulse {name}",
        )
    target_population_count = population_declaration["execution_population"][
        "particle_count"
    ]
    if selected["population_count"] >= target_population_count:
        schedule["method"] = "verified_real_field_pulse_timing_reuse_v1"
        reuse_content_key = schedule["execution_authority"]["content_key"]
        schedule.pop("execution_authority")
        schedule["verified_reuse_authority"] = {
            "mode": "verified_pulse_timing_reuse_v1",
            "content_key": reuse_content_key,
            "verified_receipt": {
                "path": _workspace_relative(receipt_path, workspace),
                "sha256": file_sha256(receipt_path),
            },
        }
        if receipt["content_key"] != reuse_content_key:
            schedule["verified_reuse_authority"]["source_content_key"] = receipt[
                "content_key"
            ]
    else:
        schedule["method"] = "verified_pilot_pulse_timing_confirmation_v1"
    return schedule


def _repo_record(root: Path, record: dict[str, str], label: str) -> Path:
    root = root.resolve()
    path = (root / record["path"]).resolve()
    if (
        not path.is_relative_to(root)
        or not path.is_file()
        or repository_text_sha256(path) != record["sha256"]
    ):
        raise ContractError(f"{label} is missing, stale or escapes the repository")
    return path


def _repo_byte_record(root: Path, record: dict[str, str], label: str) -> Path:
    root = root.resolve()
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


def _resolve_pa_cache_generation_binding(
    experiment: dict[str, Any],
) -> dict[str, Any] | None:
    """Validate an optional exact immutable PA-generation requirement."""

    binding = experiment.get("single_flight_pa_cache_generation_binding")
    if binding is None:
        return None
    if experiment.get("single_flight_pa_cache_policy") != "require_existing":
        raise ContractError(
            "exact PA cache generation binding requires require_existing policy"
        )
    if binding.get("binding_mode") != "require_exact_schema_v3_generations_v1":
        raise ContractError("PA cache generation binding mode is unsupported")
    generations = binding.get("cache_generations")
    if not isinstance(generations, list) or not generations:
        raise ContractError("PA cache generation binding is empty")
    roles = [item.get("role") for item in generations if isinstance(item, dict)]
    if len(roles) != len(generations) or len(roles) != len(set(roles)):
        raise ContractError("PA cache generation binding roles must be unique")
    return copy.deepcopy(binding)


def _validate_post_pulse_variation_axis(
    *,
    experiment: dict[str, Any],
    authority: dict[str, Any],
    producer_field_profile: str,
) -> str:
    """Fail closed unless a restart consumer changes only its declared axis."""
    axis = authority["post_pulse_variation_axis"]
    theory_axis = "accelerator_field_profile_id_and_source_zvz_theory_working_point"
    if (
        axis != theory_axis
        and experiment.get("single_flight_source_zvz_theory_working_point") is not None
    ):
        raise ContractError("post-pulse theory working point requires its declared variation axis")
    if axis == "time_integration_profile_id":
        if experiment["single_flight_accelerator_field_profile_id"] != producer_field_profile:
            raise ContractError("post-pulse reuse differs outside the time-integration axis")
        return experiment["single_flight_time_integration_profile_id"]
    if axis == "accelerator_field_profile_id":
        return experiment["single_flight_accelerator_field_profile_id"]
    if axis == "diagnostic_state_transform":
        if experiment["single_flight_accelerator_field_profile_id"] != producer_field_profile:
            raise ContractError("post-pulse diagnostic differs outside state transform")
        return authority["diagnostic_state_transform"]
    if axis == "accelerator_field_profile_id_and_diagnostic_state_transform":
        if experiment["single_flight_accelerator_field_profile_id"] != "full_domain_three_zone_piecewise_ideal_field":
            raise ContractError("post-pulse combined diagnostic requires the fixed full-ideal field")
        return (
            experiment["single_flight_accelerator_field_profile_id"]
            + "_"
            + authority["diagnostic_state_transform"]
        )
    if axis == theory_axis:
        if experiment["single_flight_accelerator_field_profile_id"] not in {
            "accelerator_ideal_three_zone_real_reflectron",
            "accelerator_real_three_zone_ideal_reflectron",
            "three_zone_explicit_region_modes",
            "accelerator_real_three_zone_pa_real_reflectron",
            "full_domain_three_zone_piecewise_ideal_field",
        }:
            raise ContractError("post-pulse theory working point requires a supported three-zone field profile")
        if experiment.get("single_flight_source_zvz_affine_policy") != "source_zvz_affine_identify_and_bind_v1":
            raise ContractError("post-pulse theory working point requires source z--vz binding")
        theory_request = experiment.get("single_flight_source_zvz_theory_working_point")
        if (
            not isinstance(theory_request, dict)
            or theory_request.get("policy_id") != "source_zvz_three_zone_theory_working_point_v1"
        ):
            raise ContractError("post-pulse theory working point authority is missing")
        return (
            experiment["single_flight_accelerator_field_profile_id"]
            + "_"
            + theory_request["policy_id"]
        )
    raise ContractError("post-pulse variation axis is unsupported")


def _resolve_post_pulse_restart_reuse(
    *,
    root: Path,
    experiment: dict[str, Any],
    authority: dict[str, Any],
    population_declaration: dict[str, Any],
    resolved_connection_path: Path,
    resolved_source_path: Path,
    resolved_geometry_path: Path,
    upstream_design_path: Path,
    plan_output: Path,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """Validate one successful child and materialize its pulse-epoch cloud."""

    workspace = root.parent
    producer_manifest_path = _workspace_record(
        workspace, authority["producer_manifest"], "post-pulse producer manifest"
    )
    checkpoint_path = _workspace_record(
        workspace, authority["checkpoint_output"], "post-pulse checkpoint output"
    )
    producer_schedule_path = _workspace_record(
        workspace, authority["producer_pulse_schedule"], "post-pulse producer schedule"
    )
    verified_receipt_path = _workspace_record(
        workspace, authority["verified_pulse_receipt"], "verified pulse receipt"
    )
    manifest = _load(producer_manifest_path)
    if (
        manifest.get("role") != "simulation_run_manifest"
        or manifest.get("status") != "success"
        or manifest.get("project") != INTEGRATION_ID
        or manifest.get("mode") != "rf_to_oatof_simion_single_flight"
        or manifest.get("formal_eligible") is not False
    ):
        raise ContractError("post-pulse producer manifest identity differs")
    try:
        verify_record(
            "post-pulse producer run_config", manifest["run_config"],
            base_dir=producer_manifest_path.parent,
        )
    except (AssertionError, KeyError, TypeError) as exc:
        raise ContractError("post-pulse producer run_config identity differs") from exc
    run_config_path = record_path(
        manifest["run_config"], base_dir=producer_manifest_path.parent
    )
    run_config = _load(run_config_path)
    inputs = manifest.get("inputs")
    outputs = manifest.get("outputs")
    if not isinstance(inputs, dict) or not isinstance(outputs, list):
        raise ContractError("post-pulse producer manifest records are incomplete")

    def verified_input(name: str) -> Path:
        record = inputs.get(name)
        try:
            verify_record(name, record, base_dir=producer_manifest_path.parent)
        except (AssertionError, KeyError, TypeError) as exc:
            raise ContractError(f"post-pulse producer input differs: {name}") from exc
        return record_path(record, base_dir=producer_manifest_path.parent).resolve()

    checkpoint_records = [
        record for record in outputs
        if record_path(record, base_dir=producer_manifest_path.parent).resolve()
        == checkpoint_path.resolve()
    ]
    if len(checkpoint_records) != 1:
        raise ContractError("post-pulse checkpoint is not a unique producer output")
    try:
        verify_record(
            "post-pulse checkpoint", checkpoint_records[0],
            base_dir=producer_manifest_path.parent,
        )
    except (AssertionError, KeyError, TypeError) as exc:
        raise ContractError("post-pulse checkpoint manifest identity differs") from exc

    producer_schedule_input = verified_input("pulse_schedule")
    source_input = verified_input("resolved_source_contract")
    connection_input = verified_input("resolved_connection")
    geometry_input = verified_input("oatof_resolved_geometry")
    design_input = verified_input("upstream_resolved_design")
    if producer_schedule_input != producer_schedule_path.resolve():
        raise ContractError("post-pulse producer schedule is not manifest-bound")
    def source_contract_identity(value: dict[str, Any]) -> str:
        """Bind derivation receipts by content SHA, not run-local materialization path."""
        normalized = copy.deepcopy(value)
        for branch in normalized.get("source_branches", {}).values():
            source = branch.get("source", {})
            # The receipt only records the local derivation of an already-bound
            # upstream source state.  It is not part of the physical source
            # identity and older successful producers legitimately predate it.
            source.pop("population_derivation_receipt", None)
        return _canonical_sha256(normalized)

    for current, producer, label in (
        (resolved_source_path, source_input, "source"),
        (upstream_design_path, design_input, "upstream RF design"),
    ):
        current_value = _load(current)
        producer_value = _load(producer)
        current_identity = (
            source_contract_identity(current_value)
            if label == "source" else _canonical_sha256(current_value)
        )
        producer_identity = (
            source_contract_identity(producer_value)
            if label == "source" else _canonical_sha256(producer_value)
        )
        if current_identity != producer_identity:
            raise ContractError(f"post-pulse producer and consumer {label} differ")
    axis = authority["post_pulse_variation_axis"]
    if _canonical_sha256(_load(resolved_geometry_path)) != _canonical_sha256(_load(geometry_input)):
        raise ContractError("post-pulse producer and consumer geometry differ")
    connection_keys = (
        "selection", "spatial_registration", "connector", "port_geometry",
        "transition_aperture", "effective_clear_radius_mm",
        "potential_alignment", "clock_alignment", "field_ownership_segments",
    )
    current_connection = _load(resolved_connection_path)
    producer_connection = _load(connection_input)
    if _canonical_sha256({
        key: current_connection[key] for key in connection_keys
    }) != _canonical_sha256({
        key: producer_connection[key] for key in connection_keys
    }):
        raise ContractError("post-pulse producer and consumer connection differ")

    schedule = _load(producer_schedule_path)
    verified_receipt = _load(verified_receipt_path)
    validate_schema(schedule, "rf_oatof_resolved_single_flight_pulse_schedule.schema.json")
    validate_schema(verified_receipt, "rf_oatof_verified_pulse_timing_receipt.schema.json")
    verified_child = _workspace_record(
        workspace, verified_receipt["verification_authority"]["child_manifest"],
        "verified pulse child manifest",
    )
    verified_schedule = _workspace_record(
        workspace, verified_receipt["verification_authority"]["pulse_schedule"],
        "verified pulse schedule",
    )
    pulse_time_us = float(schedule["pulse_effective_time_us"])
    if (
        verified_child != producer_manifest_path.resolve()
        or verified_schedule != producer_schedule_path.resolve()
        or not math.isclose(
            float(verified_receipt["selected_time_us"]), pulse_time_us,
            rel_tol=0.0, abs_tol=1e-12,
        )
    ):
        raise ContractError("verified pulse does not authorize the producer checkpoint")

    parameters = run_config.get("parameters", {})
    target_profiles = {
        "connection_profile_id": experiment["connection_profile_id"],
        "source_profile_id": experiment["source_profile_id"],
        "layout_profile_id": experiment["single_flight_layout_profile_id"],
        "architecture_generation_id": experiment["architecture_generation_id"],
        "frontend_grid_profile_id": experiment["single_flight_frontend_grid_profile_id"],
        "field_overlay_id": experiment["field_overlay_id"],
        "oatof_numerical_profile_id": experiment["single_flight_oatof_numerical_profile_id"],
        "trajectory_quality_profile_id": experiment[
            "single_flight_trajectory_quality_profile_id"
        ],
    }
    if any(parameters.get(key) != value for key, value in target_profiles.items()):
        raise ContractError("post-pulse producer and consumer profile identity differs")
    producer_time_profile = parameters.get("time_integration_profile_id")
    producer_field_profile = parameters.get("accelerator_field_profile_id")
    consumer_profile = _validate_post_pulse_variation_axis(
        experiment=experiment,
        authority=authority,
        producer_field_profile=producer_field_profile,
    )

    def binding(path: Path) -> dict[str, str]:
        return {
            "path": _workspace_relative(path, workspace),
            "sha256": file_sha256(path),
        }

    output_path = plan_output.parent / "inputs" / "post_pulse_restart_state.csv"
    receipt_path = plan_output.parent / "inputs" / (
        "post_pulse_restart_materialization_receipt.json"
    )
    try:
        receipt = materialize_manifest_bound_pre_pulse_restart(
            child_manifest_path=producer_manifest_path,
            workspace_root=workspace,
            state_output_path=output_path,
            receipt_output_path=receipt_path,
            diagnostic_state_transform=authority.get("diagnostic_state_transform"),
            producer_time_integration_profile_id=producer_time_profile,
            consumer_time_integration_profile_id=(
                experiment["single_flight_time_integration_profile_id"]
            ),
        )
        validate_schema(
            receipt,
            "rf_oatof_manifest_bound_pre_pulse_restart_materialization_receipt.schema.json",
        )
    except (ContractError, KeyError, OSError, TypeError, ValueError) as exc:
        raise ContractError("post-pulse restart materialization failed") from exc
    if (
        receipt["producer"]["manifest"]["sha256"]
        != authority["producer_manifest"]["sha256"]
        or receipt["producer"]["checkpoints"]["sha256"]
        != authority["checkpoint_output"]["sha256"]
        or receipt["authorities"]["pulse_schedule"]["sha256"]
        != authority["producer_pulse_schedule"]["sha256"]
    ):
        raise ContractError("post-pulse materialization authorities differ")
    time_integration = receipt.get("time_integration")
    if (
        not isinstance(time_integration, dict)
        or time_integration.get("producer_time_integration_profile_id")
        != producer_time_profile
        or time_integration.get("consumer_time_integration_profile_id")
        != experiment["single_flight_time_integration_profile_id"]
        or time_integration.get("producer_stage_reintegration") is not False
    ):
        raise ContractError("post-pulse time-integration boundary differs")
    if (
        receipt.get("reuse_scope", {}).get("upstream_repropagation_required") is not False
        or receipt.get("reuse_scope", {}).get("pulse_timing_reselection_required") is not False
    ):
        raise ContractError("post-pulse restart repeats producer-stage work")
    if axis in {"diagnostic_state_transform", "accelerator_field_profile_id_and_diagnostic_state_transform"} and (
        receipt.get("diagnostic", {}).get("state_transform")
        != authority["diagnostic_state_transform"]
    ):
        raise ContractError("post-pulse diagnostic transform receipt differs")
    execution = population_declaration["execution_population"]
    if (
        execution["particle_count"]
        != receipt["pulse_target_state"]["particle_count"]
        or execution["ordered_particle_id_sha256"]
        != receipt["pulse_target_state"]["ordered_particle_id_sha256"]
    ):
        raise ContractError("post-pulse restart population identity differs")
    tolerance = {
        "position_rowwise_abs_tolerance_mm": 1e-9,
        "velocity_rowwise_abs_tolerance_m_per_s": 1e-6,
        "clock_abs_tolerance_us": 1e-9,
        "energy_abs_tolerance_eV": 5e-9,
    }
    source_record = {
        "path": _workspace_relative(output_path, workspace),
        "sha256": file_sha256(output_path),
        "particle_count": receipt["pulse_target_state"]["particle_count"],
        "coordinate_frame": "oatof_global_cartesian",
        "release_event": "pre_pulse_state",
        "materialization_receipt": binding(receipt_path),
        "source_state_epoch": "pulse_effective_time",
        "source_state_locus": "accelerator_stage1_interior_finite_observed_3d_cloud",
        **tolerance,
        "postselection_prohibited": True,
    }
    validation = {
        "schema_version": 1,
        "role": "canonical_pulse_restart_target_state_validation",
        "status": "PASS",
        "target_pulse_state_sha256": source_record["sha256"],
        "materialization_receipt_sha256": file_sha256(receipt_path),
        "source_state_epoch": "pulse_effective_time",
        "source_state_locus": source_record["source_state_locus"],
        "coordinate_frame": "oatof_global_cartesian",
        "clock_basis": "canonical_instrument_time_us",
        "clock_authority": "resolved_single_flight_pulse_schedule",
        "ordered_particle_id_sha256": receipt["pulse_target_state"][
            "ordered_particle_id_sha256"
        ],
        "particle_count": source_record["particle_count"],
        "tolerances": tolerance,
        "selection": {
            "event": "pre_pulse_state",
            "pulse_eligibility": "eligible",
            "detector_results_used": False,
            "postselection_prohibited": True,
        },
    }
    schedule_authority = {
        "mode": authority["authority_mode"],
        "variation_axis": axis,
        "producer_manifest": binding(producer_manifest_path),
        "checkpoint_output": binding(checkpoint_path),
        "producer_pulse_schedule": binding(producer_schedule_path),
        "verified_pulse_receipt": binding(verified_receipt_path),
        "materialization_receipt": binding(receipt_path),
        "provider_profiles": {
            "time_integration_profile_id": producer_time_profile,
            "trajectory_quality_profile_id": parameters.get(
                "trajectory_quality_profile_id"
            ),
            "accelerator_field_profile_id": producer_field_profile,
        },
        "consumer_profile_id": consumer_profile,
        "producer_time_integration_profile_id": producer_time_profile,
        "consumer_time_integration_profile_id": experiment[
            "single_flight_time_integration_profile_id"
        ],
    }
    return output_path, source_record, {
        "producer_schedule": schedule,
        "schedule_authority": schedule_authority,
        "materialization_receipt_path": receipt_path,
        "validation": validation,
    }


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
    # The harness path in this compact receipt is historical provenance.  The
    # characterization has been moved out of tests/; production preparation
    # must bind only the compact selection receipt and the production renderer,
    # not execute or require a test harness.
    identity_files = [
        ("selection_receipt_path", "selection_receipt_sha256", "selection receipt"),
        ("production_renderer_path", "production_renderer_sha256", "production renderer"),
    ]
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
    receipt_output_path: Path,
) -> dict[str, Any]:
    source = copy.deepcopy(experiment["source"])
    launched_count = validate_standard_particle_count(
        int(source["launched_particle_count"])
    )
    population_binding = source.pop("particle_count_binding")
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
    try:
        population_receipt = write_source_population_receipt(
            state_path,
            receipt_output_path,
            expected_state_sha256=source["state"]["sha256"],
            selector=population_binding["selector"],
        )
        validate_schema(
            population_receipt,
            "rf_multipole_oatof_source_population_receipt.schema.json",
        )
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise ContractError("source population derivation failed") from exc
    selected_count = int(population_receipt["particle_count"])
    if selected_count > launched_count:
        raise ContractError("derived source particle count exceeds launched count")
    source["particle_count"] = selected_count
    source["population_derivation_receipt"] = {
        "path": _workspace_relative(receipt_output_path, workspace),
        "sha256": file_sha256(receipt_output_path),
    }
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
    pulse_timing_transition_path: Path | None = None,
    materialize_pulse_timing_stage: bool = False,
) -> tuple[Path, Path]:
    root = repo_root.resolve()
    workspace = root.parent
    campaign_path = campaign_path.resolve()
    if not campaign_path.is_relative_to(root):
        raise ContractError("integration campaign must be repository-managed")
    campaign = expand_flat_experiment_authoring(_load(campaign_path))
    validate_schema(campaign, "rf_multipole_oatof_experiment_campaign.schema.json")
    validate_pre_pulse_time_series_campaign(campaign)
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
    lifecycle_registry = _load(
        root / "integrations" / INTEGRATION_ID / "config" / "diagnostics" /
        "lifecycle_registry.json"
    )
    campaign_relative_path = campaign_path.relative_to(root).as_posix()
    active_rows = [
        row for row in lifecycle_registry.get("active_campaigns", [])
        if isinstance(row, dict) and row.get("path") == campaign_relative_path
    ]
    if active_rows:
        if len(active_rows) != 1 or (
            lifecycle_registry.get("active_post_pulse_restart_working_point_policy")
            != ACTIVE_POST_PULSE_WORKING_POINT_POLICY
        ):
            raise ContractError("active lifecycle working-point policy is invalid")
        validate_active_post_pulse_restart_working_point(experiment)
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
    pa_cache_generation_binding = _resolve_pa_cache_generation_binding(experiment)
    pulse_schedule_policy = experiment.get("single_flight_pulse_schedule_policy")
    population_declaration = experiment.get("single_flight_population")
    pre_pulse_time_series_specification = campaign.get(
        "pre_pulse_time_series_screening"
    )
    fixed_pulse_authority = (
        pulse_schedule_policy.get("fixed_execution_authority", {})
        if isinstance(pulse_schedule_policy, dict)
        else {}
    )
    if fixed_pulse_authority.get("authority_mode") == (
        "detector_blind_candidate_confirmation_v1"
    ):
        raise ContractError(
            "manual pulse candidate confirmation is retired; use the automatic transition"
        )
    cache_miss_policy = (
        pulse_schedule_policy.get("cache_miss_policy")
        if isinstance(pulse_schedule_policy, dict)
        else None
    )
    transition_authority = None
    transition_binding = None
    declared_transition = experiment.get("pulse_timing_transition_authority")
    if declared_transition is not None:
        if pulse_timing_transition_path is not None:
            raise ContractError("pulse timing transition authority is duplicated")
        if cache_miss_policy is None:
            raise ContractError(
                "pulse timing transition authority requires automatic cache-miss policy"
            )
        pulse_timing_transition_path = _workspace_record(
            workspace, declared_transition, "pulse timing transition authority"
        )
    if pulse_timing_transition_path is not None:
        if cache_miss_policy is None:
            raise ContractError("pulse timing transition requires automatic cache-miss policy")
        transition_authority, transition_binding = _resolve_pulse_transition(
            workspace, pulse_timing_transition_path
        )
    pulse_candidate_confirmation = transition_authority is not None
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
    grid_profiles: list[dict[str, Any]] = []
    if execution_strategy == "simion_single_flight":
        selected_frontend_grid_profile_id = (
            frontend_grid_profile_id
            if frontend_grid_profile_id is not None
            else single_flight_configuration["default_frontend_grid_profile_id"]
        )
        grid_profiles = [
            item for item in single_flight_configuration["frontend_grid_profiles"]
            if item["profile_id"] == selected_frontend_grid_profile_id
        ]
        if len(grid_profiles) != 1:
            raise ContractError(
                "single-flight frontend grid profile must resolve exactly once"
            )
    elif frontend_grid_profile_id is not None:
        raise ContractError(
            "single-flight frontend grid profiles require SIMION single flight"
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
    time_integration_profile = None
    if time_integration_profile_id is not None:
        matches = [
            item for item in single_flight_configuration["time_integration_profiles"]
            if item["profile_id"] == time_integration_profile_id
        ]
        if len(matches) != 1:
            raise ContractError("time-integration profile must resolve exactly once")
        time_integration_profile = matches[0]
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
    three_zone_region_modes = experiment.get("single_flight_three_zone_region_modes")
    if accelerator_field_profile_id == "three_zone_explicit_region_modes":
        expected_region_modes = {
            "accelerator_zone1", "accelerator_zone2", "accelerator_zone3",
            "drift", "reflectron_stage1", "reflectron_stage2",
        }
        if not isinstance(three_zone_region_modes, dict) or set(
            three_zone_region_modes
        ) != expected_region_modes:
            raise ContractError("explicit three-zone field profile requires all region modes")
    elif three_zone_region_modes is not None:
        raise ContractError("explicit three-zone region modes require their explicit field profile")
    source_release_mode = experiment.get("source_release_mode")
    architecture_generation_id = experiment.get("architecture_generation_id")
    source_profile_id = experiment.get("source_profile_id")
    field_overlay_id = experiment.get("field_overlay_id")
    pre_pulse_source_state = experiment.get("pre_pulse_source_state")
    post_pulse_restart_authority = experiment.get(
        "post_pulse_restart_reuse_authority"
    )
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
            and post_pulse_restart_authority is None
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
        or post_pulse_restart_authority is not None
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
    validate_connector_gap_screen_campaign(campaign, profile_registry)
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
    policy_path = _repo_record(root, policy_record, "integration execution policy")
    policy = _load(policy_path)
    validate_schema(policy, "rf_multipole_oatof_execution_policy.schema.json")
    evidence = _load_source_evidence(
        workspace=workspace,
        experiment=experiment,
        expected_project_id=expected_project_id,
        receipt_output_path=plan_output.with_name(
            "resolved_source_population_receipt.json"
        ),
    )
    source = evidence["source"]
    pulse_contract = campaign.get("pulse_resolution_optimization")
    connector_gap_contract = campaign.get("connector_gap_screen")
    pulse_cohort_policy = None
    historical_cohort_reference = None
    paired_cohort_authority = None
    pulse_prefix_path = None
    pulse_prefix_sha256 = None
    pulse_population_plan_path = None
    pulse_population_count = None
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
    elif connector_gap_contract is not None:
        prefix_ids = list(range(1, connector_gap_contract["screening_prefix_count"] + 1))
        pulse_prefix_path = (
            plan_output.parent / "inputs" / "connector_gap_screening_prefix_n100.csv"
        )
        pulse_prefix_path.parent.mkdir(parents=True, exist_ok=True)
        pulse_prefix_sha256 = write_pulse_resolution_screening_prefix(
            _workspace_record(
                workspace, source["particle_source"], "connector-gap mother source"
            ),
            pulse_prefix_path,
            ordered_particle_ids=prefix_ids,
        )
    elif pre_pulse_time_series_specification is not None:
        prefix_ids = list(range(1, 101))
        pulse_prefix_path = plan_output.parent / "inputs" / (
            "pre_pulse_time_series_screening_prefix_n100.csv"
        )
        pulse_prefix_path.parent.mkdir(parents=True, exist_ok=True)
        pulse_prefix_sha256 = write_pulse_resolution_screening_prefix(
            _workspace_record(
                workspace, source["particle_source"],
                "pre-pulse time-series mother source",
            ),
            pulse_prefix_path,
            ordered_particle_ids=prefix_ids,
        )
    elif (
        pulse_candidate_confirmation or cache_miss_policy is not None
    ) and post_pulse_restart_authority is None:
        table_binding, pulse_population_count = (
            _automatic_pulse_population_binding(population_declaration)
        )
        if table_binding == "prepared_deterministic_prefix":
            pulse_prefix_path = plan_output.parent / "inputs" / (
                "automatic_pulse_timing_prefix_n100.csv"
            )
            pulse_prefix_path.parent.mkdir(parents=True, exist_ok=True)
            pulse_prefix_sha256 = write_pulse_resolution_screening_prefix(
                _workspace_record(
                    workspace, source["particle_source"],
                    "automatic pulse timing mother source",
                ),
                pulse_prefix_path,
                ordered_particle_ids=list(range(1, 101)),
            )
            pulse_population_plan_path = "inputs/" + pulse_prefix_path.name
        else:
            pulse_prefix_path = _workspace_record(
                workspace, source["particle_source"],
                "automatic pulse timing full population",
            )
            pulse_prefix_sha256 = file_sha256(pulse_prefix_path)
            pulse_population_plan_path = source["particle_source"]["path"]
    if pulse_prefix_path is not None and pulse_population_plan_path is None:
        pulse_population_plan_path = "inputs/" + pulse_prefix_path.name
    if pulse_prefix_path is not None and pulse_population_count is None:
        pulse_population_count = population_declaration["execution_population"][
            "particle_count"
        ]
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
            receipt_output_path=plan_output.with_name(
                "resolved_design_source_population_receipt.json"
            ),
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
                "accelerator_real_three_zone_ideal_reflectron":
                    "three_zone_real_pa_plus_reflectron_piecewise_uniform_ideal_field_v1",
                "three_zone_explicit_region_modes":
                    "three_zone_explicit_region_modes_v1",
                "accelerator_real_three_zone_pa_real_reflectron":
                    "three_zone_refined_pa_field_v1",
                "full_domain_three_zone_piecewise_ideal_field":
                    "three_zone_plus_reflectron_piecewise_uniform_ideal_field_v1",
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
                three_zone_region_modes=three_zone_region_modes,
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
        registration["translation_mm"] = derive_mating_translation_with_gap(
            registration["rotation_upstream_to_downstream"],
            upstream_port["mating_surface"]["center_mm"],
            upstream_port["mating_surface"]["outward_normal"],
            downstream_port["mating_surface"]["center_mm"],
            float(registration["expected_gap_mm"]),
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
        if _is_solver_authorized_consumer(experiment):
            if (
                resolved_region_field_contract is None
                or layout_profile is None
                or not field_profiles
            ):
                raise ContractError("three-zone solver authorization identity is incomplete")
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
    if execution_strategy == "simion_single_flight":
        single_flight_dispatch_plan = resolve_single_flight_dispatch_plan(
            experiment, execution_particle_count=execution_particle_count,
            workspace=workspace,
        )
        single_flight_batch_count = int(
            single_flight_dispatch_plan["waves"][0]["batch_count"]
        )
    else:
        single_flight_batch_count = 1
        single_flight_dispatch_plan = None
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
        resolved_budget["single_flight_dispatch_plan"] = (
            single_flight_dispatch_plan
        )
        resolved_budget["single_flight_pa_cache_policy"] = pa_cache_policy
        resolved_budget["single_flight_pa_cache_policy_provenance"] = (
            pa_cache_policy_provenance
        )
        if pa_cache_generation_binding is not None:
            resolved_budget["single_flight_pa_cache_generation_binding"] = (
                pa_cache_generation_binding
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
    source_zvz_affine_receipt_path = None
    source_zvz_theory_working_point_path = None
    resolved_population_path = None
    pulse_timing_state = None
    base_schedule = None
    pulse_restart_validation_path = None
    if layout_files is not None:
        schedule = None
        if not staged_grid2_mode:
            fixed_authority = pulse_schedule_policy.get("fixed_execution_authority")
            authority_mode = (
                fixed_authority.get("authority_mode")
                if isinstance(fixed_authority, dict)
                else None
            )
            if authority_mode == "frozen_historical_schedule_v1":
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
                base_schedule = derive_pulse_schedule(
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
                if post_pulse_restart_authority is not None:
                    (
                        pre_pulse_source_path,
                        pre_pulse_source_state,
                        restart_reuse,
                    ) = _resolve_post_pulse_restart_reuse(
                        root=root,
                        experiment=experiment,
                        authority=post_pulse_restart_authority,
                        population_declaration=population_declaration,
                        resolved_connection_path=resolved_path,
                        resolved_source_path=resolved_source_contract_path,
                        resolved_geometry_path=layout_files["geometry"],
                        upstream_design_path=upstream_resolved_design_path,
                        plan_output=plan_output,
                    )
                    pre_pulse_receipt_path = restart_reuse[
                        "materialization_receipt_path"
                    ]
                    pulse_restart_validation_path = plan_output.with_name(
                        "canonical_pulse_restart_target_state_validation.json"
                    )
                    pulse_restart_validation_path.write_text(
                        json.dumps(restart_reuse["validation"], indent=2) + "\n",
                        encoding="utf-8",
                    )
                    producer_schedule = restart_reuse["producer_schedule"]
                    if not math.isclose(
                        float(base_schedule["rf_period_us"]),
                        float(producer_schedule["rf_period_us"]),
                        rel_tol=0.0, abs_tol=1e-15,
                    ):
                        raise ContractError("post-pulse producer RF period differs")
                    pulse_time_us = float(
                        producer_schedule["pulse_effective_time_us"]
                    )
                    schedule = copy.deepcopy(base_schedule)
                    schedule.update({
                        "method": "manifest_bound_post_pulse_restart_reuse_v1",
                        "pulse_base_time_us": pulse_time_us,
                        "pulse_offset_us": 0.0,
                        "pulse_effective_time_us": pulse_time_us,
                        "pulse_width_us": float(producer_schedule["pulse_width_us"]),
                        "source_state_path": pre_pulse_source_state["path"],
                        "source_state_sha256": pre_pulse_source_state["sha256"],
                        "claim_status": "FUNCTIONAL_ONLY",
                        "post_pulse_restart_reuse_authority": restart_reuse[
                            "schedule_authority"
                        ],
                    })
                    pulse_timing_state = (
                        "ready_verified" if cache_miss_policy is not None else None
                    )
                elif transition_authority is not None:
                    if pulse_prefix_sha256 is None:
                        raise ContractError(
                            "pulse timing confirmation requires a prepared population prefix"
                        )
                    schedule = _resolve_candidate_confirmation_schedule(
                        root=root,
                        experiment=experiment,
                        policy=pulse_schedule_policy,
                        authority=transition_authority,
                        population_declaration=population_declaration,
                        prepared_prefix_sha256=pulse_prefix_sha256,
                        resolved_connection_path=resolved_path,
                        resolved_source_path=resolved_source_contract_path,
                        resolved_geometry_path=layout_files["geometry"],
                        single_flight_configuration=single_flight_configuration,
                        base_schedule=base_schedule,
                    )
                    pulse_timing_state = "confirmation_required"
                elif authority_mode is None:
                    schedule = None
                    if (
                        pulse_prefix_sha256 is not None
                        and pre_pulse_time_series_specification is None
                    ):
                        schedule = _resolve_cached_verified_pulse_schedule(
                            root=root,
                            experiment=experiment,
                            policy=pulse_schedule_policy,
                            population_declaration=population_declaration,
                            prepared_prefix_sha256=pulse_prefix_sha256,
                            resolved_connection_path=resolved_path,
                            resolved_source_path=resolved_source_contract_path,
                            resolved_geometry_path=layout_files["geometry"],
                            single_flight_configuration=single_flight_configuration,
                            base_schedule=base_schedule,
                        )
                    if schedule is None:
                        schedule = base_schedule
                        if cache_miss_policy is not None:
                            pulse_timing_state = "discovery_required"
                    elif cache_miss_policy is not None:
                        pulse_timing_state = "ready_verified"
                else:
                    raise ContractError("single-flight pulse authority mode is unsupported")
            validate_schema(
                schedule, "rf_oatof_resolved_single_flight_pulse_schedule.schema.json"
            )
            schedule_path = plan_output.with_name("resolved_single_flight_pulse_schedule.json")
            schedule_path.write_text(json.dumps(schedule, indent=2) + "\n", encoding="utf-8")
            layout_files["schedule"] = schedule_path
        if (
            pre_pulse_source_path is not None
            and source_materialization_profile is not None
            and post_pulse_restart_authority is None
        ):
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
        source_zvz_affine_policy = experiment.get("single_flight_source_zvz_affine_policy")
        working_point_source = None
        if source_zvz_affine_policy is not None:
            if source_zvz_affine_policy != "source_zvz_affine_identify_and_bind_v1":
                raise ContractError("source z--vz affine policy is unsupported")
            working_point_source = pre_pulse_source_path or materialized_source_path
            if working_point_source is None:
                working_point_source = _workspace_record(
                    workspace, source["particle_source"], "z--vz source state"
                )
            if (
                pre_pulse_source_path is None
                and source_materialization_profile is not None
                and source_materialization_profile.get("materialization_mode")
                == "canonical_multipole_source"
            ):
                _, global_rows = materialize_single_flight_source(
                    working_point_source, _load(resolved_path)
                )
                mapped_source_path = plan_output.parent / "inputs" / (
                    "source_zvz_working_point_state.csv"
                )
                with mapped_source_path.open(
                    "w", encoding="utf-8", newline=""
                ) as handle:
                    writer = csv.DictWriter(
                        handle,
                        fieldnames=[
                            "particle_id", "instrument_time_us", "mass_amu",
                            "charge_state", "position_x_mm", "position_y_mm",
                            "position_z_mm", "velocity_x_m_s", "velocity_y_m_s",
                            "velocity_z_m_s", "kinetic_energy_eV",
                        ],
                        lineterminator="\n",
                    )
                    writer.writeheader()
                    writer.writerows(global_rows)
                working_point_source = mapped_source_path
            source_zvz_affine_receipt_path = plan_output.parent / "inputs" / "source_zvz_affine_receipt.json"
            try:
                write_source_zvz_affine_receipt(
                    source_zvz_affine_receipt_path, source_state_path=working_point_source
                )
                validate_schema(
                    _load(source_zvz_affine_receipt_path),
                    "rf_oatof_source_zvz_affine_receipt.schema.json",
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ContractError("automatic source z--vz identification failed") from exc
        theory_working_point_request = experiment.get(
            "single_flight_source_zvz_theory_working_point"
        )
        if theory_working_point_request is not None:
            if source_zvz_affine_receipt_path is None or resolved_region_field_contract_path is None:
                raise ContractError("source theory working point requires source z--vz binding")
            if accelerator_field_profile_id not in {
                "accelerator_ideal_three_zone_real_reflectron",
                "accelerator_real_three_zone_ideal_reflectron",
                "three_zone_explicit_region_modes",
                "accelerator_real_three_zone_pa_real_reflectron",
                "full_domain_three_zone_piecewise_ideal_field",
            }:
                raise ContractError("source theory working point requires a supported three-zone field profile")
            try:
                working_point = derive_three_zone_working_point(
                    source_receipt=_load(source_zvz_affine_receipt_path),
                    resolved_geometry=geometry,
                    resolved_geometry_input_sha256=file_sha256(geometry_path),
                    theory_request={
                        key: theory_working_point_request[key]
                        for key in (
                            "first_zone_drop_v", "nominal_energy_per_charge_v",
                            "reflectron_stage1_voltage_v",
                        )
                    },
                )
                geometry["accelerator_topology"] = working_point["accelerator_topology"]
                potentials = working_point["accelerator_topology"]["potentials_v"]
                geometry["electrodes_V"].update({
                    "repeller": potentials["repeller"],
                    "grid1": potentials["intermediate1"],
                    "intermediate2": potentials["intermediate2"],
                    "grid2": potentials["exit"],
                    "entgrid": working_point["reflectron"]["entrance_voltage_v"],
                    "midgrid": working_point["reflectron"]["stage1_voltage_v"],
                    "backplate": working_point["reflectron"]["backplate_voltage_v"],
                })
                source_zvz_theory_working_point_path = plan_output.parent / "inputs" / "source_zvz_theory_working_point.json"
                source_zvz_theory_working_point_path.write_text(
                    json.dumps(working_point, indent=2) + "\n", encoding="utf-8"
                )
                validate_schema(
                    _load(source_zvz_theory_working_point_path),
                    "rf_oatof_theory_working_point.schema.json",
                )
                geometry_path.write_text(json.dumps(geometry, indent=2) + "\n", encoding="utf-8")
                downstream_port["authority"]["source_sha256"] = file_sha256(geometry_path)
                downstream_port_path.write_text(
                    json.dumps(downstream_port, indent=2) + "\n", encoding="utf-8"
                )
                resolved_registry_path.write_text(
                    json.dumps(resolved_registry, indent=2) + "\n", encoding="utf-8"
                )
                resolved_path, _ = write_resolved_and_plan(
                    resolved_registry_path,
                    experiment["connection_profile_id"],
                    resolved_output,
                    plan_output,
                    repo_root=root,
                )
                resolved_region_field_contract = build_resolved_region_field_contract(
                    geometry_path, resolved_region_field_contract_path,
                    accelerator_field_profile_id,
                    accelerator_topology=working_point["accelerator_topology"],
                    three_zone_region_modes=three_zone_region_modes,
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ContractError("source theory working point derivation failed") from exc
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
            population_input_role = population_declaration["source_authority"][
                "input_role"
            ]
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
    pre_pulse_time_series_contract_path = None
    if (
        pre_pulse_time_series_specification is not None
        or pulse_timing_state == "discovery_required"
    ):
        if (
            pulse_prefix_path is None or pulse_prefix_sha256 is None
            or resolved_population_path is None or resolved_region_field_contract is None
            or layout_files is None or time_integration_profile is None
            or not field_profiles
        ):
            raise ContractError("pre-pulse time-series prepared identity is incomplete")
        screening_specification = pre_pulse_time_series_specification
        if screening_specification is None:
            native_rf_steps = int(time_integration_profile["rf_steps_per_period"])
            relative_start_index = math.floor(-0.35 * native_rf_steps)
            relative_end_index = math.ceil(1.65 * native_rf_steps)
            screening_specification = {
                "mode": "real_pa_rf_pre_pulse_time_series",
                "active_scope": "pre_pulse_frontend_accelerator",
                "time_grid_profile_id": cache_miss_policy["time_grid_profile_id"],
                "relative_start_index": relative_start_index,
                "relative_end_index": relative_end_index,
                "rf_steps_per_period": native_rf_steps,
                "sample_count": relative_end_index - relative_start_index + 1,
                "spatial_window_profile_id": cache_miss_policy[
                    "spatial_window_profile_id"
                ],
                "pulse_disabled": True,
                "terminate_at_window_end": True,
                "resolution_claim_allowed": False,
                "prohibited_outputs": [
                    "detector_crossing",
                    "resolution_metrics",
                    "single_flight_spatial_six_panel",
                ],
            }
        pre_pulse_time_series_contract = compile_pre_pulse_time_series_contract(
            campaign=campaign,
            experiment=experiment,
            experiment_row_sha256=row_sha256,
            upstream_resolved_design=design_evidence["resolved_design"],
            resolved_source_contract_sha256=file_sha256(resolved_source_contract_path),
            resolved_population_contract_sha256=file_sha256(resolved_population_path),
            prepared_prefix_sha256=pulse_prefix_sha256,
            layout_profile=layout_profile,
            selected_field_profile=field_profiles[0],
            region_field_semantic_sha256=resolved_region_field_contract[
                "semantic_sha256"
            ],
            rf_steps_per_period=int(screening_specification["rf_steps_per_period"]),
            specification=screening_specification,
            time_integration_profile_id=next(
                profile["profile_id"]
                for profile in single_flight_configuration["time_integration_profiles"]
                if int(profile["rf_steps_per_period"])
                == int(screening_specification["rf_steps_per_period"])
            ),
            base_schedule=(
                base_schedule if pulse_timing_state == "discovery_required" else None
            ),
        )
        pre_pulse_time_series_contract_path = plan_output.parent / "inputs" / (
            "pre_pulse_time_series_screening_contract.json"
        )
        pre_pulse_time_series_contract_path.write_text(
            json.dumps(pre_pulse_time_series_contract, indent=2) + "\n",
            encoding="utf-8",
        )
    pa_cache_generation_binding_path = None
    if pa_cache_generation_binding is not None:
        pa_cache_generation_binding_path = plan_output.parent / "inputs" / (
            "single_flight_pa_cache_generation_binding.json"
        )
        pa_cache_generation_binding_path.write_text(
            json.dumps(pa_cache_generation_binding, indent=2) + "\n",
            encoding="utf-8",
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
                "single_flight_batch_count=" + str(single_flight_batch_count),
            ]) + ([] if pa_cache_generation_binding_path is None else [
                "single_flight_pa_cache_generation_binding_filename=inputs/"
                + pa_cache_generation_binding_path.name,
                "single_flight_pa_cache_generation_binding_sha256="
                + file_sha256(pa_cache_generation_binding_path),
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
            ]) + ([] if connector_gap_contract is None else [
                "connector_gap_prefix_filename=inputs/" + pulse_prefix_path.name,
                "connector_gap_prefix_sha256=" + pulse_prefix_sha256,
            ]) + ([] if pre_pulse_time_series_contract_path is None else [
                "pre_pulse_time_series_prefix_filename="
                + pulse_population_plan_path,
                "pre_pulse_time_series_prefix_sha256=" + pulse_prefix_sha256,
                "pre_pulse_time_series_prefix_count="
                + str(pulse_population_count),
                "pre_pulse_time_series_contract_filename=inputs/"
                + pre_pulse_time_series_contract_path.name,
                "pre_pulse_time_series_contract_sha256="
                + file_sha256(pre_pulse_time_series_contract_path),
                "pre_pulse_time_series_time_integration_profile_id="
                + str(pre_pulse_time_series_contract["identities"][
                    "time_integration_profile_id"
                ]),
            ]) + ([] if not pulse_candidate_confirmation else [
                "pulse_candidate_confirmation_prefix_filename="
                + pulse_population_plan_path,
                "pulse_candidate_confirmation_prefix_sha256="
                + pulse_prefix_sha256,
                "pulse_candidate_confirmation_prefix_count="
                + str(pulse_population_count),
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
            ])) + ([] if pre_pulse_source_path is None or pulse_restart_validation_path is None else [
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
            ]) + ([] if "single_flight_maximum_time_of_flight_us" not in experiment else [
                "single_flight_maximum_time_of_flight_us="
                + format(
                    float(experiment["single_flight_maximum_time_of_flight_us"]),
                    ".17g",
                ),
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
            ]) + ([] if source_zvz_affine_receipt_path is None else [
                "source_zvz_affine_receipt_filename=inputs/"
                + source_zvz_affine_receipt_path.name,
                "source_zvz_affine_receipt_sha256="
                + file_sha256(source_zvz_affine_receipt_path),
            ]) + ([] if source_zvz_theory_working_point_path is None else [
                "source_zvz_theory_working_point_filename=inputs/"
                + source_zvz_theory_working_point_path.name,
                "source_zvz_theory_working_point_sha256="
                + file_sha256(source_zvz_theory_working_point_path),
                "source_zvz_theory_geometry_input_sha256="
                + working_point["resolved_geometry_input_sha256"],
            ]) + ([] if three_zone_authorization is None else [
                name + "=" + value
                for name, value in three_zone_authorization.items()
            ]),
        }
    ]
    materialized_discovery = None
    if cache_miss_policy is not None:
        if pulse_timing_state is None or layout_files is None or "schedule" not in layout_files:
            raise ContractError("automatic pulse timing state is incomplete")
        stage = None
        transition_relative_path = None
        if pulse_timing_state != "ready_verified":
            stage_id = (
                "pulse_timing_discovery"
                if pulse_timing_state == "discovery_required"
                else "pulse_timing_confirmation"
            )
            stage_run_id = (
                _derive_pulse_discovery_run_id(experiment["run_id"])
                if pulse_timing_state == "discovery_required"
                else experiment["run_id"]
            )
            if pulse_timing_state == "confirmation_required":
                stage_output = plan_output.parent
            else:
                stage_output = (
                    workspace / "artifacts" / "projects" / INTEGRATION_ID
                    / "runs" / stage_run_id
                )
            stage_plan = copy.deepcopy(plan)
            if pulse_timing_state == "discovery_required":
                if materialize_pulse_timing_stage:
                    if stage_output.exists():
                        raise ContractError(
                            "automatic pulse discovery run directory already exists"
                        )
                    stage_resolved_path = stage_output / resolved_path.name
                    stage_plan_path = stage_output / "composition_plan.json"
                    stage_plan["resolved_connection"] = {
                        "path": _workspace_relative(stage_resolved_path, workspace),
                        "sha256": file_sha256(resolved_path),
                    }
                else:
                    stage_resolved_path = resolved_path
                    stage_plan_path = plan_output.with_name(
                        stage_id + "_composition_plan.json"
                    )
            else:
                stage_resolved_path = resolved_path
                stage_plan_path = plan_output.with_name(
                    stage_id + "_composition_plan.json"
                )
            stage_plan["execution_steps"][0]["arguments"].append(
                "pulse_timing_internal_stage=" + stage_id
            )
            validate_schema(stage_plan, "composition_plan.schema.json")
            stage_plan_bytes = (
                json.dumps(stage_plan, indent=2) + "\n"
            ).encode("utf-8")
            if (
                pulse_timing_state == "discovery_required"
                and materialize_pulse_timing_stage
            ):
                materialized_discovery = (
                    plan_output.parent,
                    stage_output,
                    stage_plan_bytes,
                    resolved_path.name,
                )
            else:
                stage_plan_path.write_bytes(stage_plan_bytes)
                verify_composition_plan(
                    stage_plan_path, stage_resolved_path, repo_root=root
                )
            stage = {
                "stage_id": stage_id,
                "run_id": stage_run_id,
                "output_directory": _workspace_relative(stage_output, workspace),
                "resolved_connection": {
                    "path": _workspace_relative(stage_resolved_path, workspace),
                    "sha256": file_sha256(resolved_path),
                },
                "composition_plan": {
                    "path": _workspace_relative(stage_plan_path, workspace),
                    "sha256": hashlib.sha256(stage_plan_bytes).hexdigest().upper(),
                },
            }
            if pulse_timing_state == "discovery_required":
                transition_relative_path = PULSE_TRANSITION_RELATIVE_PATH
        orchestration = {
            "schema_version": 1,
            "role": "rf_oatof_resolved_pulse_timing_orchestration",
            "campaign_id": campaign["campaign_id"],
            "experiment_id": experiment_id,
            "experiment_row_sha256": row_sha256,
            "original_run_id": experiment["run_id"],
            "target_output_directory": _workspace_relative(plan_output.parent, workspace),
            "state": pulse_timing_state,
            "cache_miss_policy_id": cache_miss_policy["mode"],
            "time_grid_profile_id": cache_miss_policy["time_grid_profile_id"],
            "spatial_window_profile_id": cache_miss_policy[
                "spatial_window_profile_id"
            ],
            "requested_schedule": {
                "path": _workspace_relative(layout_files["schedule"], workspace),
                "sha256": file_sha256(layout_files["schedule"]),
            },
            **({"stage": stage} if stage is not None else {}),
            **(
                {"transition_relative_path": transition_relative_path}
                if transition_relative_path is not None
                else {}
            ),
            **(
                {"transition": transition_binding}
                if pulse_timing_state == "confirmation_required"
                else {}
            ),
        }
        validate_schema(
            orchestration,
            "rf_oatof_resolved_pulse_timing_orchestration.schema.json",
        )
        orchestration_path = plan_output.with_name(
            "resolved_pulse_timing_orchestration.json"
        )
        orchestration_path.write_text(
            json.dumps(orchestration, indent=2) + "\n", encoding="utf-8"
        )
        plan["execution_steps"][0]["arguments"].extend([
            "pulse_timing_orchestration_filename=" + orchestration_path.name,
            "pulse_timing_orchestration_sha256=" + file_sha256(orchestration_path),
            "pulse_timing_orchestration_state=" + pulse_timing_state,
        ])
    validate_schema(plan, "composition_plan.schema.json")
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    verify_composition_plan(plan_path, resolved_path, repo_root=root)
    if materialized_discovery is not None:
        _materialize_pulse_discovery_package(
            source_directory=materialized_discovery[0],
            stage_directory=materialized_discovery[1],
            stage_plan_bytes=materialized_discovery[2],
            resolved_filename=materialized_discovery[3],
            repo_root=root,
        )
    return resolved_path, plan_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--profile-registry", required=True, type=Path)
    parser.add_argument("--adapter-registry", required=True, type=Path)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--experiment-id")
    parser.add_argument("--resolved-output", type=Path)
    parser.add_argument("--plan-output", type=Path)
    parser.add_argument("--list-experiment-ids", action="store_true")
    parser.add_argument("--print-experiment-json")
    parser.add_argument(
        "--semantic-diff-experiment-json", nargs=2, metavar=("BEFORE", "AFTER")
    )
    parser.add_argument("--pulse-timing-transition", type=Path)
    parser.add_argument("--materialize-pulse-timing-stage", action="store_true")
    args = parser.parse_args()
    if args.list_experiment_ids or args.print_experiment_json or args.semantic_diff_experiment_json:
        campaign = expand_flat_experiment_authoring(_load(args.campaign))
        validate_schema(campaign, "rf_multipole_oatof_experiment_campaign.schema.json")
        if args.semantic_diff_experiment_json:
            before_id, after_id = args.semantic_diff_experiment_json
            rows_by_id = {
                row["experiment_id"]: row for row in campaign["experiments"]
            }
            if before_id not in rows_by_id or after_id not in rows_by_id:
                parser.error("--semantic-diff-experiment-json requires two known experiment IDs")
            print(json.dumps(
                semantic_diff_experiments(rows_by_id[before_id], rows_by_id[after_id]),
                separators=(",", ":"),
            ))
            return 0
        if args.print_experiment_json:
            matches = [
                row for row in campaign["experiments"]
                if row["experiment_id"] == args.print_experiment_json
            ]
            if len(matches) != 1:
                parser.error("--print-experiment-json must resolve exactly one experiment")
            print(json.dumps(matches[0], separators=(",", ":")))
            return 0
        for row in sorted(campaign["experiments"], key=lambda item: item["sequence"]):
            print(row["experiment_id"])
        return 0
    if args.experiment_id is None or args.resolved_output is None or args.plan_output is None:
        parser.error("--experiment-id, --resolved-output and --plan-output are required unless listing")
    resolved, plan = prepare_family_source_closure(
        repo_root=args.repo_root,
        profile_registry_path=args.profile_registry,
        adapter_registry_path=args.adapter_registry,
        campaign_path=args.campaign,
        experiment_id=args.experiment_id,
        resolved_output=args.resolved_output,
        plan_output=args.plan_output,
        pulse_timing_transition_path=args.pulse_timing_transition,
        materialize_pulse_timing_stage=args.materialize_pulse_timing_stage,
    )
    print(f"FAMILY_SOURCE_CLOSURE_PREPARE=PASS RESOLVED={resolved} PLAN={plan}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
