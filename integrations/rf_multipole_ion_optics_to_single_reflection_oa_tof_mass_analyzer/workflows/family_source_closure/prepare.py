"""Prepare one campaign-declared multipole-to-oaTOF execution."""

from __future__ import annotations

import argparse
import copy
import csv
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import shutil
from typing import Any
import warnings

from common.contracts.artifact_naming import validate_run_id
from common.contracts.file_identity import (
    canonical_json_sha256 as _canonical_sha256,
    file_sha256,
    repository_text_sha256,
)
from common.contracts.machine_contracts import ContractError, validate_schema
from common.contracts.particle_count_policy import validate_positive_particle_count
from common.contracts.particle_physics import kinetic_energy_ev
from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.verify_artifact_layout import verify_verified_pulse_cache_entry
from common.simion.resource_profile import discover_resource_profiles
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
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.select_real_field_pulse_time import (
    pulse_selection_content_identity,
)
from common.multipole.component_port import build_exit_component_port
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.resolved_region_field import (
    build_resolved_region_field_contract,
    canonical_profile_id,
    field_profile,
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
    resolve_ordered_subset_source_particle_ids,
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
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.materialize_pre_pulse_time_series import (
    TIME_SERIES_RESTART_RECEIPT_ROLE,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_layout import (
    compile_geometry_and_port,
    derive_pulse_schedule,
    select_profile,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source import (
    materialize as materialize_single_flight_source,
    materialize_independent_ion_source_volume,
    materialize_ideal_linear_source,
    materialize_pre_pulse_restart,
    materialize_terminal_handoff_continuation,
    resolve_source_materialization_profile,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_execution_profile import (
    resolve_execution_profile,
    unique_named_profile,
)


INTEGRATION_ID = (
    "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
)
CAMPAIGN_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "config" / "schemas" / (
    "rf_multipole_oatof_experiment_campaign.schema.json"
)
RESOLVED_CAMPAIGN_SCHEMA_PATH = CAMPAIGN_SCHEMA_PATH.parent / (
    "rf_multipole_oatof_resolved_experiment_campaign.schema.json"
)
PRE_PULSE_CAMPAIGN_PROFILE_REGISTRY_PATH = CAMPAIGN_SCHEMA_PATH.parent.parent / (
    "pre_pulse_campaign_profiles.json"
)
INTEGRATION_SCHEMA_DIR = CAMPAIGN_SCHEMA_PATH.parent
UPSTREAM_PROJECTS = {
    "rf_quadrupole_ion_optics",
    "rf_hexapole_ion_optics",
    "rf_octupole_ion_optics",
}
PULSE_TRANSITION_RELATIVE_PATH = "results/pulse_timing_transition.json"


def _three_zone_field_profile(profile_id: str) -> dict[str, Any]:
    """Resolve the active profile whose topology enables three-zone theory."""

    try:
        profile = field_profile(profile_id)
    except ValueError as exc:
        raise ContractError(
            "post-pulse theory working point requires a supported three-zone field profile"
        ) from exc
    if not isinstance(profile.get("topology_id"), str):
        raise ContractError("post-pulse theory working point requires a supported three-zone field profile")
    return profile


def validate_three_zone_candidate_binding(
    experiment: dict[str, Any], layout_profile: dict[str, Any]
) -> dict[str, Any] | None:
    """Bind Candidate evidence from the selected layout method, not its name."""

    candidate = experiment.get("single_flight_three_zone_candidate")
    requires_candidate = layout_profile.get("method") == "t5_frozen_three_zone_candidate_v1"
    if requires_candidate and not isinstance(candidate, dict):
        raise ContractError("three-zone T5 layout requires a Candidate file binding")
    if not requires_candidate and candidate is not None:
        raise ContractError("single-flight Candidate file binding requires a three-zone T5 layout")
    return candidate if requires_candidate else None


def resolve_generated_pre_pulse_ordered_subset(
    experiment: dict[str, Any],
    source_materialization_profile: dict[str, Any] | None,
) -> list[int] | None:
    """Resolve a registered ordered subset and bind its declared population."""

    declaration = experiment.get("generated_pre_pulse_ordered_subset")
    if declaration is None:
        return None
    if not isinstance(declaration, dict):
        raise ContractError("generated ordered subset declaration is invalid")
    if experiment.get("source_release_mode") != "pre_pulse_restart":
        raise ContractError("generated ordered subset requires a pre-pulse restart")
    if experiment.get("pre_pulse_source_state") is not None:
        raise ContractError("generated ordered subset conflicts with a supplied restart")
    if (
        source_materialization_profile is None
        or source_materialization_profile.get("materialization_mode")
        != "resolved_layout_pulse_ideal_linear_z_vz"
    ):
        raise ContractError("generated ordered subset requires an ideal-linear mother")
    try:
        source_ids = resolve_ordered_subset_source_particle_ids(declaration)
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError("generated ordered subset selection is invalid") from exc
    try:
        mother_count = int(source_materialization_profile["particle_count"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError("generated ordered subset mother population is invalid") from exc
    if max(source_ids) > mother_count:
        raise ContractError("generated ordered subset exceeds mother population")
    population = experiment.get("single_flight_population")
    execution = population.get("execution_population", {}) if isinstance(population, dict) else {}
    denominators = population.get("denominators", {}) if isinstance(population, dict) else {}
    expected_count = len(source_ids)
    expected_ordered_sha256 = _canonical_sha256(list(range(1, expected_count + 1)))
    if (
        execution.get("particle_count") != expected_count
        or execution.get("ordered_particle_id_sha256") != expected_ordered_sha256
        or denominators.get("population_count") != expected_count
        or denominators.get("eligible_population_count") != expected_count
    ):
        raise ContractError("generated ordered subset population identity differs")
    return source_ids


def validate_active_post_pulse_restart_working_point(
    experiment: dict[str, Any],
    *,
    require_theory_working_point: bool = True,
) -> None:
    """Require the formal theory closure for an active restart row only."""
    if not require_theory_working_point:
        return
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
    validate_schema(
        transition, INTEGRATION_SCHEMA_DIR / "rf_oatof_pulse_timing_transition.schema.json"
    )
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
        "first_n_rows_in_frozen_file_order",
        "prepared_deterministic_prefix",
        "first_n_rows_in_frozen_file_order",
    ) and isinstance(count, int) and not isinstance(count, bool) and count > 0:
        return "prepared_deterministic_prefix", count
    if identity == (
        "continuous_injection_full_population",
        "source_contract_particle_source",
        "all_rows_in_frozen_file_order",
    ) and isinstance(count, int) and not isinstance(count, bool) and count > 0:
        return "source_contract_particle_source", count
    raise ContractError("automatic pulse timing population differs")


def resolve_single_flight_dispatch_plan(
    experiment: dict[str, Any], *, execution_particle_count: int,
    rf_steps_per_period: int | None = None,
    execution_profile: dict[str, Any] | None = None,
    resource_profiles: list[dict[str, Any]] | None = None,
    workload_topology_id: str | None = None,
) -> dict[str, Any]:
    """Resolve execution-only dispatch without deriving the governed population.

    The returned object is an execution artifact only.  It never contributes to
    campaign or handoff identity; those remain defined by the resolved source
    and numerical contracts.  A resource policy controls only host reserves
    and CPU use.  Only manifest-verified single-process profiles can estimate
    a batch; without one the shared scheduler emits a one-batch bootstrap
    plan.  The retired fixed batch-count field has no role in either decision.
    """

    try:
        if (
            isinstance(rf_steps_per_period, bool)
            or not isinstance(rf_steps_per_period, int)
            or rf_steps_per_period < 1
        ):
            raise ValueError("single-flight RF time profile is unresolved")
        request = {
            "solver": "SIMION",
            "field_kind": "rf",
            "rf_steps_per_period": rf_steps_per_period,
            "particle_count": execution_particle_count,
            "independent_particles": True,
            "time_integration_profile_id": str(
                experiment["single_flight_time_integration_profile_id"]
            ),
            "frontend_grid_profile_id": experiment.get(
                "single_flight_frontend_grid_profile_id"
            ),
            "oatof_numerical_profile_id": experiment.get(
                "single_flight_oatof_numerical_profile_id"
            ),
            "trajectory_quality_profile_id": experiment.get(
                "single_flight_trajectory_quality_profile_id"
            ),
            "accelerator_field_profile_id": experiment.get(
                "single_flight_accelerator_field_profile_id"
            ),
            "workload_topology_id": workload_topology_id,
        }
        if execution_profile is not None:
            request.update({
                "frontend_cell_mm_xyz": execution_profile["frontend_cell_mm_xyz"],
                "accelerator_overlay_cell_mm_xyz": execution_profile[
                    "accelerator_overlay_cell_mm_xyz"
                ],
                "reflectron_cell_mm": execution_profile["reflectron_cell_mm"],
                "trajectory_quality": execution_profile["trajectory_quality"],
            })
    except (KeyError, ValueError) as error:
        raise ContractError("single-flight automatic dispatch is invalid") from error
    from common.simion.resource_scheduler import (
        plan_simion_dispatch,
    )
    profiles = [] if resource_profiles is None else resource_profiles
    # CPU and memory planning is repository policy.  A scientific campaign
    # can select the physical workload but cannot tune scheduler reserves,
    # safety factors, or lane counts.
    try:
        return plan_simion_dispatch(request, profiles)
    except ValueError as error:
        raise ContractError("single-flight resource scheduler planning failed") from error


def validate_pre_pulse_time_series_campaign(campaign: dict[str, Any]) -> None:
    """Fail closed on detector-blind RF pre-pulse screening or a single snapshot."""

    contract = campaign.get("pre_pulse_time_series_screening")
    if contract is None:
        return
    rows = campaign["experiments"]
    is_single_snapshot = (
        contract.get("sample_count") == 1
        and contract.get("relative_start_index") == 0
        and contract.get("relative_end_index") == 0
    )
    required_claim = (
        "DETECTOR_BLIND_SOURCE_ONLY" if is_single_snapshot else "FUNCTIONAL_ONLY"
    )
    if not rows:
        raise ContractError("pre-pulse time-series campaign scope differs")
    if required_claim not in campaign["claim_limit"]:
        warnings.warn(
            "pre-pulse campaign claim_limit omits the conventional "
            f"{required_claim} marker; semantic detector-blind constraints "
            "remain enforced",
            UserWarning,
            stacklevel=2,
        )
    for row in rows:
        source = row["source"]
        population = row["single_flight_population"]
        execution = population["execution_population"]
        denominators = population.get("denominators", {})
        source_authority = population.get("source_authority", {})
        population_identity = (
            population.get("population_mode"),
            source_authority.get("table_binding"),
            execution.get("selection_algorithm"),
        )
        is_legacy_n100_prefix = population_identity == (
            "first_100_rows_in_frozen_file_order",
            "prepared_deterministic_prefix",
            "first_100_rows_in_frozen_file_order",
        ) and execution.get("particle_count") == 100
        is_prepared_prefix_population = population_identity == (
            "first_n_rows_in_frozen_file_order",
            "prepared_deterministic_prefix",
            "first_n_rows_in_frozen_file_order",
        ) and 0 < execution.get("particle_count", 0) <= source.get("launched_particle_count", 0)
        is_full_source_contract_population = population_identity == (
            "continuous_injection_full_population",
            "source_contract_particle_source",
            "all_rows_in_frozen_file_order",
        ) and execution.get("particle_count") == source.get("launched_particle_count")
        is_materialized_volume_population = population_identity == (
            "independent_spatial_velocity_ion_source_snapshot",
            "prepared_materialized_ion_source_volume",
            "all_rows_in_frozen_file_order",
        ) and execution.get("particle_count") == source.get("launched_particle_count")
        is_terminal_handoff_population = population_identity in {
            (
                "terminal_handoff_continuation",
                "terminal_handoff_continuation_global_state",
                "all_transmitted_terminal_handoffs_in_source_particle_id_order",
            ),
            (
                "terminal_handoff_continuation",
                "terminal_handoff_continuation_global_state",
                "first_n_transmitted_terminal_handoffs_in_source_particle_id_order",
            ),
            (
                "terminal_handoff_continuation",
                "terminal_handoff_continuation_global_state",
                "explicit_single_terminal_handoff_particle_id_v1",
            ),
        } and (
            row.get("source_release_mode") == "continuous_frontend_handoff"
            and 0 < execution.get("particle_count", 0) < source.get("launched_particle_count", 0)
        )
        if (
            contract.get("active_scope") != "pre_pulse_frontend_accelerator"
            or contract.get("pa_cache_keys", {}).get("flight_tube") is not None
            or contract.get("pa_cache_keys", {}).get("reflectron") is not None
            or source.get("authority_scope") != "source_population"
            or not isinstance(source.get("launched_particle_count"), int)
            or source["launched_particle_count"] < execution.get("particle_count", 0)
            or not (
                is_legacy_n100_prefix
                or is_prepared_prefix_population
                or is_full_source_contract_population
                or is_materialized_volume_population
                or is_terminal_handoff_population
            )
            or denominators.get("population_count") != (
                source.get("launched_particle_count") if is_terminal_handoff_population
                else execution.get("particle_count")
            )
            or denominators.get("eligible_population_count")
            != (source.get("launched_particle_count") if is_terminal_handoff_population
                else execution.get("particle_count"))
            or contract["sample_count"]
            != (
                (contract["relative_end_index"] - contract["relative_start_index"])
                // int(contract.get("sample_stride_rf_steps", 1))
                + 1
            )
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
    execution_profile: dict[str, Any] | None = None,
    resolved_connection: dict[str, Any] | None = None,
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
    sample_stride = int(specification.get("sample_stride_rf_steps", 1))
    if (
        sample_stride < 1
        or relative_end < relative_start
        or (relative_end - relative_start) % sample_stride != 0
    ):
        raise ContractError("pre-pulse time-series RF sampling stride differs")
    automatic = base_schedule is not None
    seed_time_us = float(
        base_schedule["pulse_effective_time_us"]
        if automatic
        else specification["anchor_time_us"]
    )
    grid_origin_us = seed_time_us + relative_start * step_us
    sample_count = (relative_end - relative_start) // sample_stride + 1
    sample_times_us = [
        grid_origin_us + index * sample_stride * step_us
        for index in range(sample_count)
    ]
    if (
        sample_count != specification["sample_count"]
        or not math.isclose(sample_times_us[-1], seed_time_us + relative_end * step_us,
                            rel_tol=1e-15, abs_tol=1e-15)
        or not all(right > left for left, right in zip(
            sample_times_us, sample_times_us[1:], strict=False
        ))
    ):
        raise ContractError("pre-pulse time-series RF grid does not close")
    overlay_layout = (
        "whole_accelerator_v1"
        if execution_profile is None
        else execution_profile.get("accelerator_overlay_layout", "whole_accelerator_v1")
    )
    connector_length_mm = (
        0.0 if resolved_connection is None
        else float(resolved_connection["connector"]["length_mm"])
    )
    if connector_length_mm >= 50.0:
        active_pa_cache_roles = [
            "fine_upstream",
            "accelerator_entrance_zone_collision",
        ]
    elif overlay_layout == "whole_accelerator_v1":
        active_pa_cache_roles = ["frontend", "accelerator_overlay"]
    elif overlay_layout == "two_local_v1":
        active_pa_cache_roles = [
            "frontend",
            "accelerator_entrance_overlay",
            "accelerator_intermediate_overlay",
        ]
    else:
        raise ContractError("pre-pulse accelerator-overlay layout is unsupported")
    contract = {
        "schema_version": 5 if automatic and connector_length_mm >= 50.0 else 3 if automatic and overlay_layout == "two_local_v1" else 2 if automatic else 1,
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
                "required": active_pa_cache_roles,
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
            "sample_stride_rf_steps": sample_stride,
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
        contract,
        INTEGRATION_SCHEMA_DIR / "rf_oatof_pre_pulse_time_series_screening_contract.schema.json",
    )
    return contract


SCREENING_SOURCE_COLUMNS = [
    "particle_id", "birth_time_s", "x_mm", "y_mm", "z_mm",
    "vx_m_s", "vy_m_s", "vz_m_s", "mass_amu", "charge_state",
]


def write_pulse_resolution_screening_prefix(
    source_path: Path, output_path: Path, *, ordered_particle_ids: list[int],
) -> str:
    """Write one explicitly ordered, frozen subset of the canonical mother."""
    with source_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows, columns = list(reader), reader.fieldnames
    if columns != SCREENING_SOURCE_COLUMNS or not rows:
        raise ContractError("pulse-resolution mother source is not canonical")
    mother_ids = [int(row["particle_id"]) for row in rows]
    if mother_ids != list(range(1, len(rows) + 1)):
        raise ContractError("pulse-resolution mother-source IDs must be contiguous")
    if (
        not ordered_particle_ids
        or any(isinstance(item, bool) or not isinstance(item, int) for item in ordered_particle_ids)
        or len(set(ordered_particle_ids)) != len(ordered_particle_ids)
        or not set(ordered_particle_ids).issubset(mother_ids)
    ):
        raise ContractError("pulse-resolution frozen source cohort is not an ordered mother subset")
    rows_by_id = {int(row["particle_id"]): row for row in rows}
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCREENING_SOURCE_COLUMNS,
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows_by_id[particle_id] for particle_id in ordered_particle_ids)
    return file_sha256(output_path)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ContractError(f"JSON object required: {path}")
    return value


def _write_json(
    path: Path, document: dict[str, Any], *, sort_keys: bool = False
) -> None:
    path.write_text(
        json.dumps(document, indent=2, sort_keys=sort_keys) + "\n",
        encoding="utf-8",
    )


def expand_pre_pulse_campaign_profile(campaign: dict[str, Any]) -> dict[str, Any]:
    """Inject one versioned execution profile before materializing v7 rows.

    The profile is authoring convenience only.  Its complete values are copied
    into the resolved campaign, while candidate/source/cohort evidence remains
    explicit in the authored campaign and cannot be hidden in a mutable preset.
    """
    profile_id = campaign.get("pre_pulse_campaign_profile_id")
    if profile_id is None:
        return copy.deepcopy(campaign)
    if not isinstance(profile_id, str) or not profile_id:
        raise ContractError("pre-pulse campaign profile ID is invalid")
    registry = _load(PRE_PULSE_CAMPAIGN_PROFILE_REGISTRY_PATH)
    if registry.get("role") != "rf_multipole_oatof_pre_pulse_campaign_profile_registry":
        raise ContractError("pre-pulse campaign profile registry role differs")
    profiles = {
        item.get("profile_id"): item for item in registry.get("profiles", [])
        if isinstance(item, dict) and isinstance(item.get("profile_id"), str)
    }
    if profile_id not in profiles:
        raise ContractError(f"pre-pulse campaign profile is not unique: {profile_id}")
    profile = profiles[profile_id]
    parent_id = profile.get("extends")
    if parent_id is not None:
        if not isinstance(parent_id, str) or parent_id not in profiles:
            raise ContractError("pre-pulse campaign profile parent is invalid")
        parent = profiles[parent_id]
        if parent.get("extends") is not None:
            raise ContractError("pre-pulse campaign profiles permit one inheritance level")
        overrides = profile.get("overrides")
        if set(profile) != {"profile_id", "revision", "extends", "overrides"} or not isinstance(overrides, dict):
            raise ContractError("pre-pulse campaign profile inheritance shape differs")
        parent_defaults = parent.get("defaults")
        if not isinstance(parent_defaults, dict) or set(overrides) - {"campaign", "experiment_shared"}:
            raise ContractError("pre-pulse campaign profile inheritance defaults differ")
        profile = {
            "profile_id": profile_id,
            "defaults": {
                "campaign": {
                    **copy.deepcopy(parent_defaults.get("campaign", {})),
                    **copy.deepcopy(overrides.get("campaign", {})),
                },
                "experiment_shared": {
                    **copy.deepcopy(parent_defaults.get("experiment_shared", {})),
                    **copy.deepcopy(overrides.get("experiment_shared", {})),
                },
            },
        }
    defaults = profile.get("defaults")
    if not isinstance(defaults, dict) or set(defaults) != {
        "campaign", "experiment_shared"
    }:
        raise ContractError("pre-pulse campaign profile defaults differ")
    campaign_defaults = defaults["campaign"]
    shared_defaults = defaults["experiment_shared"]
    if not isinstance(campaign_defaults, dict) or not isinstance(shared_defaults, dict):
        raise ContractError("pre-pulse campaign profile defaults must be objects")
    result = copy.deepcopy(campaign)
    result.pop("pre_pulse_campaign_profile_id")
    for key, value in campaign_defaults.items():
        if key in result:
            raise ContractError(f"pre-pulse campaign profile duplicates authored field: {key}")
        result[key] = copy.deepcopy(value)
    experiments = result.get("experiments")
    if not isinstance(experiments, dict) or not isinstance(experiments.get("shared"), dict):
        raise ContractError("pre-pulse campaign profile requires flat experiment authoring")
    authored_shared = experiments["shared"]
    overlap = set(authored_shared).intersection(shared_defaults)
    if overlap:
        raise ContractError(
            "pre-pulse campaign profile duplicates authored shared field: " +
            ", ".join(sorted(overlap))
        )
    experiments["shared"] = {
        **copy.deepcopy(shared_defaults), **copy.deepcopy(authored_shared)
    }
    return result


def expand_flat_experiment_authoring(
    campaign: dict[str, Any], *, execution_run_id: str | None = None
) -> dict[str, Any]:
    """Materialize a v7 authoring contract into its generated run rows."""
    campaign = expand_pre_pulse_campaign_profile(campaign)
    source = campaign.get("experiments")
    if not isinstance(source, dict):
        raise ContractError("experiments must be a v7 authoring object")
    if set(source) != {"shared", "variation_axes", "rows"}:
        raise ContractError("flat experiment authoring keys differ")
    shared = source["shared"]
    axes = source["variation_axes"]
    rows = source["rows"]
    if not isinstance(shared, dict) or not isinstance(axes, list) or not isinstance(rows, list):
        raise ContractError("flat experiment authoring shape differs")
    if (
        any(not isinstance(axis, str) or not axis for axis in axes)
        or len(axes) != len(set(axes))
    ):
        raise ContractError("flat experiment variation axes are invalid")
    row_identity = {"sequence", "experiment_id", "run_id"}
    if set(axes).intersection(row_identity):
        raise ContractError("flat experiment variation axes cannot contain row identity")
    expanded: list[dict[str, Any]] = []
    if execution_run_id is not None and len(rows) != 1:
        raise ContractError("an execution run ID requires exactly one minimal authored row")
    for sequence, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ContractError("flat experiment row must be an object")
        if set(row) != {"experiment_id", "values"}:
            raise ContractError("flat experiment rows must contain only experiment_id and values")
        overrides = row["values"]
        if not isinstance(overrides, dict) or not set(overrides).issubset(set(axes)):
            raise ContractError("flat experiment row override is not an allowed variation axis")
        materialized = copy.deepcopy(shared)
        if set(materialized).intersection(row_identity):
            raise ContractError("flat experiment shared controls cannot contain row identity")
        materialized.update(copy.deepcopy(overrides))
        materialized["sequence"] = sequence
        materialized["experiment_id"] = row["experiment_id"]
        materialized["run_id"] = (
            execution_run_id if execution_run_id is not None else "execution_pending"
        )
        expanded.append(materialized)
    if not expanded:
        raise ContractError("flat experiment authoring must contain at least one row")
    result = copy.deepcopy(campaign)
    result["experiments"] = expanded
    return result


def require_minimal_flat_experiment_authoring(campaign: dict[str, Any]) -> None:
    """Validate semantic constraints not expressible by the v7 JSON schema."""

    source = campaign.get("experiments")
    if not isinstance(source, dict) or set(source) != {
        "shared", "variation_axes", "rows"
    }:
        raise ContractError("executable campaign must use flat minimal authoring")
    rows = source.get("rows")
    if not isinstance(rows, list) or not rows or any(
        not isinstance(row, dict) or set(row) != {"experiment_id", "values"}
        for row in rows
    ):
        raise ContractError(
            "executable campaign rows must contain only experiment_id and values"
        )


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
    if top_level == "execution_strategy" or any(
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
        INTEGRATION_SCHEMA_DIR / "rf_oatof_detector_blind_pulse_timing_candidate_receipt.schema.json",
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
    screening_receipt = _load(receipt_authority("pre_pulse_time_series_receipt"))
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
    receipt_pa_cache_keys = receipt.get("pa_cache_keys")
    # Schema-v3 selection receipts from the active campaign predate the
    # domain-split cache-key encoding.  Their authoritative screening receipt
    # is already hash-bound above, so it is the sole safe source for the
    # missing pre-pulse PA identity while this in-flight evidence is consumed.
    if receipt_pa_cache_keys is None:
        receipt_pa_cache_keys = screening_receipt.get("pa_cache_keys")
    if not isinstance(receipt_pa_cache_keys, dict):
        raise ContractError("pulse candidate pre-pulse PA identity is missing")
    content_basis, content_key = pulse_selection_content_identity(
        contract=screening_contract,
        source=current_source,
        connection=current_connection,
        geometry=current_geometry,
        spatial_profile=profiles[0],
        selector_source_sha256=selector_record.get("sha256"),
        # Preserve the selection receipt's historical content identity.  The
        # fallback above is solely for the later verified-reuse projection.
        pa_cache_keys=receipt.get("pa_cache_keys"),
    )
    reuse_basis, verified_content_key = build_verified_pulse_reuse_projection(
        screening_contract=screening_contract,
        resolved_source=current_source,
        resolved_connection=current_connection,
        resolved_geometry=current_geometry,
        spatial_profile=profiles[0],
        pa_cache_keys=receipt_pa_cache_keys,
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
        validate_schema(
            receipt,
            INTEGRATION_SCHEMA_DIR / "rf_oatof_verified_pulse_timing_receipt.schema.json",
        )
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
        try:
            profile = field_profile(
                experiment["single_flight_accelerator_field_profile_id"]
            )
        except ValueError as exc:
            raise ContractError(
                "post-pulse combined diagnostic requires an authorized field profile"
            ) from exc
        if profile.get("post_pulse_diagnostic_state_transform_allowed") is not True:
            raise ContractError(
                "post-pulse combined diagnostic requires an authorized field profile"
            )
        return (
            experiment["single_flight_accelerator_field_profile_id"]
            + "_"
            + authority["diagnostic_state_transform"]
        )
    if axis == theory_axis:
        _three_zone_field_profile(
            experiment["single_flight_accelerator_field_profile_id"]
        )
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


def post_pulse_handoff_profile_identity(experiment: dict[str, Any]) -> dict[str, str]:
    """Return only the producer properties that affect a frozen restart state.

    Downstream mesh, grid, trajectory quality, and time integration govern the
    new consumer run; they cannot alter an already recorded pulse-epoch state.
    """

    return {
        "connection_profile_id": experiment["connection_profile_id"],
        "source_profile_id": experiment["source_profile_id"],
        "layout_profile_id": experiment["single_flight_layout_profile_id"],
        "architecture_generation_id": experiment["architecture_generation_id"],
        "field_overlay_id": experiment["field_overlay_id"],
    }


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
    validate_schema(
        schedule,
        INTEGRATION_SCHEMA_DIR / "rf_oatof_resolved_single_flight_pulse_schedule.schema.json",
    )
    validate_schema(
        verified_receipt,
        INTEGRATION_SCHEMA_DIR / "rf_oatof_verified_pulse_timing_receipt.schema.json",
    )
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
    target_profiles = post_pulse_handoff_profile_identity(experiment)
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
            INTEGRATION_SCHEMA_DIR / "rf_oatof_manifest_bound_pre_pulse_restart_materialization_receipt.schema.json",
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


def _population_source_table(
    path: Path,
    *,
    workspace: Path,
    input_role: str,
    table_binding: str,
) -> dict[str, Any]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ContractError("population source table lacks particle identities")
    # A canonical pre-pulse restart state has two identities: its transient,
    # contiguous simulation_particle_id and the frozen mother-cohort
    # source_particle_id.  The latter is the population identity that must
    # agree with the receipt, so never substitute the simulation row index.
    identity_column = (
        "source_particle_id"
        if "source_particle_id" in rows[0]
        else "particle_id"
    )
    if identity_column not in rows[0]:
        raise ContractError("population source table lacks particle identities")
    try:
        particle_ids = [int(row[identity_column]) for row in rows]
    except (TypeError, ValueError) as exc:
        raise ContractError("population source particle identities are invalid") from exc
    if any(particle_id < 1 for particle_id in particle_ids):
        raise ContractError("population source particle identities must be positive")
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
            receipt,
            INTEGRATION_SCHEMA_DIR / "rf_oatof_pre_pulse_ordered_subset_receipt.schema.json",
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


def _validate_time_series_restart_state(
    source_path: Path,
    receipt_path: Path,
    source_record: dict[str, Any],
    schedule: dict[str, Any],
) -> dict[str, Any]:
    """Bind a detector-blind time-series restart to its exact pulse schedule."""

    receipt = _load(receipt_path)
    validate_schema(
        receipt,
        INTEGRATION_SCHEMA_DIR
        / "rf_oatof_manifest_bound_time_series_restart_materialization_receipt.schema.json",
    )
    target = receipt["pulse_target_state"]
    selection = receipt["selection"]
    pulse_time_us = float(schedule["pulse_effective_time_us"])
    expected_locus = "accelerator_stage1_interior_finite_observed_3d_cloud"
    if (
        receipt["role"] != TIME_SERIES_RESTART_RECEIPT_ROLE
        or target["sha256"] != source_record["sha256"]
        or target["particle_count"] != source_record["particle_count"]
        or target["source_state_epoch"] != "pulse_effective_time"
        or target["source_state_locus"]["kind"] != expected_locus
        or target["coordinate_frame"] != "oatof_global_cartesian"
        or target["clock_basis"] != "canonical_instrument_time_us"
        or target["clock_authority"] != "resolved_single_flight_pulse_schedule"
        or not math.isclose(
            float(target["pulse_effective_time_us"]),
            pulse_time_us,
            rel_tol=0.0,
            abs_tol=1e-9,
        )
        or selection["detector_results_used"]
        or selection["selection_uses_detector_outcome"]
        or not selection["pulse_disabled"]
        or not selection["postselection_prohibited"]
    ):
        raise ContractError("time-series restart receipt identity differs")
    _, rows, row_map = materialize_pre_pulse_restart(
        source_path, pulse_time_us, return_row_map=True
    )
    count = len(rows)
    # ``particle_id`` in the rendered restart rows is a local SIMION index.
    # Bind the receipt to the immutable source identity instead.
    ordered_ids = [int(row["source_particle_id"]) for row in row_map]
    ordered_id_sha256 = _canonical_sha256(ordered_ids)
    if (
        count != source_record["particle_count"]
        or target["particle_count"] != count
        or target["ordered_particle_id_sha256"] != ordered_id_sha256
    ):
        raise ContractError("time-series restart population differs")
    tolerances = {
        "position_rowwise_abs_tolerance_mm": float(
            source_record["position_rowwise_abs_tolerance_mm"]
        ),
        "velocity_rowwise_abs_tolerance_m_per_s": float(
            source_record["velocity_rowwise_abs_tolerance_m_per_s"]
        ),
        "clock_abs_tolerance_us": float(source_record["clock_abs_tolerance_us"]),
        "energy_abs_tolerance_eV": float(source_record["energy_abs_tolerance_eV"]),
    }
    if any(value <= 0.0 or not math.isfinite(value) for value in tolerances.values()):
        raise ContractError("time-series restart tolerances must be positive")
    maximum_clock_error = 0.0
    maximum_energy_error = 0.0
    for row in rows:
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
                )
                - float(row["kinetic_energy_eV"])
            ),
        )
    if (
        maximum_clock_error > tolerances["clock_abs_tolerance_us"]
        or maximum_energy_error > tolerances["energy_abs_tolerance_eV"]
    ):
        raise ContractError("time-series restart target-state validation failed")
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
        "tolerances": tolerances,
        "maximum_errors": {
            "position_rowwise_abs_mm": 0.0,
            "velocity_rowwise_abs_m_per_s": 0.0,
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
            or fixed_kinetic_energy_eV is None
            or not math.isfinite(fixed_kinetic_energy_eV)
            or fixed_kinetic_energy_eV <= 0
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


def _unique_named_profile(
    configuration: dict[str, Any],
    collection: str,
    profile_id: str,
    failure: str,
) -> dict[str, Any]:
    try:
        return unique_named_profile(configuration, collection, profile_id, failure)
    except ValueError as exc:
        raise ContractError(str(exc)) from exc


@dataclass(frozen=True)
class ResolvedSingleFlightProfiles:
    """Validated single-flight configuration selected by one campaign row."""

    configuration: dict[str, Any]
    frontend_grid_profile_id: str | None
    source_materialization_profile_id: str | None
    source_materialization_profile: dict[str, Any] | None
    grid_profiles: list[dict[str, Any]]
    execution_profile: dict[str, Any] | None
    accelerator_field_profile_id: str | None
    field_profiles: list[dict[str, Any]]
    three_zone_region_modes: dict[str, Any] | None


def _resolve_single_flight_profiles(
    root: Path,
    experiment: dict[str, Any],
    execution_strategy: str,
    *,
    exploration: bool = False,
) -> ResolvedSingleFlightProfiles:
    """Load and fail-close validate all runtime profiles selected by one row."""

    configuration = _load(
        root / "integrations" / INTEGRATION_ID / "config" /
        "simion_single_flight.json"
    )
    frontend_grid_profile_id = experiment.get("single_flight_frontend_grid_profile_id")
    source_materialization_profile_id = experiment.get(
        "single_flight_source_materialization_profile_id"
    )
    source_materialization_profile = None
    if source_materialization_profile_id is not None:
        if execution_strategy != "simion_single_flight":
            raise ContractError(
                "source materialization profiles require SIMION single flight"
            )
        try:
            source_materialization_profile = resolve_source_materialization_profile(
                _unique_named_profile(
                    configuration,
                    "source_materialization_profiles",
                    source_materialization_profile_id,
                    "single-flight source materialization profile must resolve exactly once",
                ),
                root / "integrations" / INTEGRATION_ID,
            )
        except (KeyError, OSError, TypeError, ValueError) as exc:
            raise ContractError("source phase-space authority is invalid") from exc
    grid_profiles: list[dict[str, Any]] = []
    if execution_strategy == "simion_single_flight":
        selected_frontend_grid_profile_id = (
            frontend_grid_profile_id
            if frontend_grid_profile_id is not None
            else configuration["default_frontend_grid_profile_id"]
        )
        grid_profiles = [_unique_named_profile(
            configuration,
            "frontend_grid_profiles",
            selected_frontend_grid_profile_id,
            "single-flight frontend grid profile must resolve exactly once",
        )]
    elif frontend_grid_profile_id is not None:
        raise ContractError(
            "single-flight frontend grid profiles require SIMION single flight"
        )
    oatof_numerical_profile_id = experiment.get(
        "single_flight_oatof_numerical_profile_id"
    )
    if (
        oatof_numerical_profile_id is not None
        and execution_strategy != "simion_single_flight"
    ):
        raise ContractError("oaTOF numerical profiles require SIMION single flight")
    trajectory_quality_profile_id = experiment.get(
        "single_flight_trajectory_quality_profile_id"
    )
    if (
        trajectory_quality_profile_id is not None
        and execution_strategy != "simion_single_flight"
    ):
        _unique_named_profile(
            configuration,
            "trajectory_quality_profiles",
            trajectory_quality_profile_id,
            "trajectory-quality profile must resolve exactly once",
        )
    time_integration_profile_id = experiment.get(
        "single_flight_time_integration_profile_id"
    )
    if (
        time_integration_profile_id is not None
        and execution_strategy != "simion_single_flight"
    ):
        _unique_named_profile(
            configuration,
            "time_integration_profiles",
            time_integration_profile_id,
            "time-integration profile must resolve exactly once",
        )
    spatial_window_profile_id = experiment.get(
        "single_flight_spatial_window_profile_id"
    )
    if spatial_window_profile_id is not None:
        if execution_strategy != "simion_single_flight":
            raise ContractError("spatial-window profiles require SIMION single flight")
    accelerator_field_profile_id = (
        canonical_profile_id(experiment.get(
            "single_flight_accelerator_field_profile_id",
            configuration["default_accelerator_field_profile_id"],
        ))
        if execution_strategy == "simion_single_flight"
        else None
    )
    field_profiles: list[dict[str, Any]] = []
    if accelerator_field_profile_id is not None:
        if execution_strategy != "simion_single_flight":
            raise ContractError(
                "single-flight accelerator field profiles require SIMION single flight"
            )
        field_profiles = [
            item for item in configuration["accelerator_field_profiles"]
            if canonical_profile_id(item["profile_id"]) == accelerator_field_profile_id
        ]
        if len(field_profiles) != 1:
            raise ContractError(
                "single-flight accelerator field profile must resolve exactly once"
            )
    three_zone_region_modes = experiment.get("single_flight_three_zone_region_modes")
    region_mode_authority = (
        field_profiles[0].get("region_mode_authority")
        if field_profiles
        else None
    )
    if region_mode_authority == "experiment":
        expected_region_modes = {
            "accelerator_zone1", "accelerator_zone2", "accelerator_zone3",
            "drift", "reflectron_stage1", "reflectron_stage2",
        }
        if not isinstance(three_zone_region_modes, dict) or set(
            three_zone_region_modes
        ) != expected_region_modes:
            raise ContractError("explicit three-zone field profile requires all region modes")
    elif region_mode_authority is None and three_zone_region_modes is not None:
        raise ContractError("explicit three-zone region modes require their explicit field profile")
    elif region_mode_authority is not None:
        raise ContractError("single-flight field profile region-mode authority is unsupported")
    numerical_overrides = experiment.get("single_flight_numerical_overrides")
    if numerical_overrides is not None and not exploration:
        raise ContractError("inline single-flight numerics require exploration status")
    execution_profile = None
    if execution_strategy == "simion_single_flight":
        try:
            execution_profile = resolve_execution_profile(
                configuration,
                frontend_grid_profile_id=frontend_grid_profile_id,
                oatof_numerical_profile_id=oatof_numerical_profile_id,
                trajectory_quality_profile_id=trajectory_quality_profile_id,
                time_integration_profile_id=time_integration_profile_id,
                maximum_time_of_flight_us=experiment.get(
                    "single_flight_maximum_time_of_flight_us"
                ),
                spatial_window_profile_id=spatial_window_profile_id,
                numerical_overrides=numerical_overrides,
            )
        except ValueError as exc:
            raise ContractError("single-flight numerical configuration is invalid") from exc
    return ResolvedSingleFlightProfiles(
        configuration=configuration,
        frontend_grid_profile_id=frontend_grid_profile_id,
        source_materialization_profile_id=source_materialization_profile_id,
        source_materialization_profile=source_materialization_profile,
        grid_profiles=grid_profiles,
        execution_profile=execution_profile,
        accelerator_field_profile_id=accelerator_field_profile_id,
        field_profiles=field_profiles,
        three_zone_region_modes=three_zone_region_modes,
    )


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
    try:
        launched_count = validate_positive_particle_count(
            source["launched_particle_count"]
        )
    except ValueError as exc:
        raise ContractError("source launched particle count is invalid") from exc
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
            INTEGRATION_SCHEMA_DIR
            / "rf_multipole_oatof_source_population_receipt.schema.json",
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


def _select_preparation_experiment(
    *,
    root: Path,
    campaign_path: Path,
    experiment_id: str,
    exploration: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load one repository-managed campaign and select its unique experiment."""

    campaign_path = campaign_path.resolve()
    if not campaign_path.is_relative_to(root):
        raise ContractError("integration campaign must be repository-managed")
    if exploration:
        authored_campaign = _load(campaign_path)
        validate_schema(authored_campaign, CAMPAIGN_SCHEMA_PATH)
        require_minimal_flat_experiment_authoring(authored_campaign)
        campaign = expand_flat_experiment_authoring(authored_campaign)
        validate_schema(campaign, RESOLVED_CAMPAIGN_SCHEMA_PATH)
        validate_pre_pulse_time_series_campaign(campaign)
        if campaign["integration_id"] != INTEGRATION_ID:
            raise ContractError("campaign integration identity differs")
        if campaign.get("status") != "exploration":
            raise ContractError(
                "exploration preparation requires campaign.status=exploration"
            )
    else:
        lifecycle_registry = _load(
            root / "integrations" / INTEGRATION_ID / "config" / "diagnostics" /
            "lifecycle_registry.json"
        )
        campaign_relative_path = campaign_path.relative_to(root).as_posix()
        active_rows = [
            row for row in lifecycle_registry.get("active_campaigns", [])
            if isinstance(row, dict) and row.get("path") == campaign_relative_path
        ]
        if len(active_rows) != 1:
            raise ContractError(
                "campaign is not an active lifecycle authority; preparation is forbidden"
            )
        authored_campaign = _load(campaign_path)
        validate_schema(authored_campaign, CAMPAIGN_SCHEMA_PATH)
        require_minimal_flat_experiment_authoring(authored_campaign)
        campaign = expand_flat_experiment_authoring(authored_campaign)
        validate_schema(campaign, RESOLVED_CAMPAIGN_SCHEMA_PATH)
        validate_pre_pulse_time_series_campaign(campaign)
        if campaign["integration_id"] != INTEGRATION_ID:
            raise ContractError("campaign integration identity differs")
    identities = [item["experiment_id"] for item in campaign["experiments"]]
    sequences = [item["sequence"] for item in campaign["experiments"]]
    if len(identities) != len(set(identities)) or len(sequences) != len(set(sequences)):
        raise ContractError("campaign experiment IDs and sequences must be unique")
    matches = [
        item for item in campaign["experiments"]
        if item["experiment_id"] == experiment_id
    ]
    if len(matches) != 1:
        raise ContractError("campaign experiment must resolve exactly once")
    experiment = matches[0]
    if not exploration and campaign.get("status") != "authorized":
        raise ContractError(
            "active lifecycle campaign must be authorized before preparation"
        )
    validate_active_post_pulse_restart_working_point(
        experiment,
        require_theory_working_point=not exploration,
    )
    return campaign, experiment


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
    exploration: bool = False,
    execution_run_id: str | None = None,
) -> tuple[Path, Path]:
    root = repo_root.resolve()
    workspace = root.parent
    campaign, experiment = _select_preparation_experiment(
        root=root,
        campaign_path=campaign_path,
        experiment_id=experiment_id,
        exploration=exploration,
    )
    if execution_run_id is not None:
        validate_run_id(execution_run_id)
        experiment = copy.deepcopy(experiment)
        experiment["run_id"] = execution_run_id
    source = experiment["source"]
    execution_strategy = experiment.get("execution_strategy", "staged_three_stage")
    single_flight_execution_mode = experiment.get(
        "single_flight_execution_mode", "particle_flight"
    )
    if execution_strategy != "simion_single_flight":
        if "single_flight_execution_mode" in experiment:
            raise ContractError(
                "single-flight execution mode requires simion_single_flight"
            )
    elif single_flight_execution_mode not in (
        "particle_flight", "program_axis_field_export"
    ):
        raise ContractError("single-flight execution mode is unsupported")
    pa_cache_policy = experiment.get("single_flight_pa_cache_policy")
    pa_cache_policy_provenance = None
    if execution_strategy == "simion_single_flight":
        if pa_cache_policy is None:
            raise ContractError(
                "single-flight execution requires an explicit PA cache policy"
            )
        pa_cache_policy_provenance = "explicit_campaign_row"
    pa_cache_generation_binding = _resolve_pa_cache_generation_binding(experiment)
    pulse_schedule_policy = experiment.get("single_flight_pulse_schedule_policy")
    population_declaration = experiment.get("single_flight_population")
    pre_pulse_time_series_specification = campaign.get(
        "pre_pulse_time_series_screening"
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
    if execution_strategy == "simion_single_flight" and campaign["schema_version"] < 3:
        raise ContractError(
            "SolverAuthorized single-flight execution requires a schema-v3 successor campaign"
        )
    if execution_strategy == "simion_single_flight" and population_declaration is None:
        raise ContractError("schema-v3 single flight requires a resolved population input")
    local_aperture_mm = experiment.get("accelerator_entrance_local_aperture_mm")
    if local_aperture_mm is not None:
        if execution_strategy != "simion_single_flight" or not isinstance(
            local_aperture_mm, dict
        ) or set(local_aperture_mm) != {"width", "height"}:
            raise ContractError("local accelerator aperture declaration is invalid")
        try:
            local_aperture_values = {
                axis: float(local_aperture_mm[axis]) for axis in ("width", "height")
            }
        except (TypeError, ValueError) as error:
            raise ContractError("local accelerator aperture declaration is invalid") from error
        if not all(math.isfinite(value) and value > 0 for value in local_aperture_values.values()):
            raise ContractError("local accelerator aperture dimensions are invalid")
        local_aperture_mm = local_aperture_values
    if (
        execution_strategy == "simion_single_flight"
        and pulse_schedule_policy is None
    ):
        raise ContractError("single-flight execution requires a pulse schedule")
    resolved_profiles = _resolve_single_flight_profiles(
        root,
        experiment,
        execution_strategy,
        exploration=campaign.get("status") == "exploration",
    )
    single_flight_configuration = resolved_profiles.configuration
    frontend_grid_profile_id = resolved_profiles.frontend_grid_profile_id
    source_materialization_profile_id = (
        resolved_profiles.source_materialization_profile_id
    )
    source_materialization_profile = resolved_profiles.source_materialization_profile
    grid_profiles = resolved_profiles.grid_profiles
    execution_profile = resolved_profiles.execution_profile
    accelerator_field_profile_id = resolved_profiles.accelerator_field_profile_id
    field_profiles = resolved_profiles.field_profiles
    three_zone_region_modes = resolved_profiles.three_zone_region_modes
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
    generated_ordered_source_ids = resolve_generated_pre_pulse_ordered_subset(
        experiment, source_materialization_profile
    )
    if (
        field_overlay_id is not None
        and frontend_grid_profile_id is not None
        and grid_profiles[0].get("field_overlay_id") != field_overlay_id
    ):
        raise ContractError("frontend grid field-overlay identity differs")
    pre_pulse_source_path = None
    pre_pulse_receipt_path = None
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
        if pre_pulse_source_state is not None:
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
    validate_schema(
        runtime_binding,
        INTEGRATION_SCHEMA_DIR / "rf_multipole_oatof_runtime_binding.schema.json",
    )
    if (
        runtime_binding["schema_version"] != 4
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
    validate_schema(
        source_adapter,
        INTEGRATION_SCHEMA_DIR / "rf_multipole_oatof_source_adapter.schema.json",
    )
    policy_record = runtime_binding["contracts"]["execution_policy_contract"]
    policy_path = _repo_record(root, policy_record, "integration execution policy")
    policy = _load(policy_path)
    validate_schema(
        policy,
        INTEGRATION_SCHEMA_DIR / "rf_multipole_oatof_execution_policy.schema.json",
    )
    evidence = _load_source_evidence(
        workspace=workspace,
        experiment=experiment,
        expected_project_id=expected_project_id,
        receipt_output_path=plan_output.with_name(
            "resolved_source_population_receipt.json"
        ),
    )
    source = evidence["source"]
    # A pre-pulse screen is a projection of the exact mother cohort that will
    # be released into SIMION.  The independent ion-source volume has no
    # dependence on the pulse schedule, so materialize it before deriving any
    # screening prefix.  This prevents the legacy source-contract CSV from
    # silently becoming the pre-pulse population authority.
    materialized_source_path = None
    materialization_receipt_path = None
    materialization_receipt = None
    if (
        source_materialization_profile is not None
        and source_materialization_profile["materialization_mode"]
        == "independent_spatial_velocity_ion_source_snapshot"
    ):
        materialized_source_path = plan_output.parent / "inputs" / (
            "single_flight_materialized_particle_source.csv"
        )
        materialization_receipt_path = plan_output.parent / "inputs" / (
            "single_flight_source_materialization_receipt.json"
        )
        materialization_receipt = materialize_independent_ion_source_volume(
            materialized_source_path,
            materialization_receipt_path,
            source_materialization_profile,
            root / "integrations" / INTEGRATION_ID,
        )
    pulse_prefix_source_path = (
        materialized_source_path
        if materialized_source_path is not None
        else _workspace_record(
            workspace, source["particle_source"], "pre-pulse time-series mother source"
        )
    )
    pulse_prefix_path = None
    pulse_prefix_sha256 = None
    pulse_population_plan_path = None
    pulse_population_count = None
    if pre_pulse_time_series_specification is not None:
        pulse_population_count = int(
            population_declaration["execution_population"]["particle_count"]
        )
        smoke_particle_id = (
            source_materialization_profile.get("functional_smoke_particle_id")
            if source_materialization_profile is not None
            else None
        )
        if pulse_population_count == 1 and smoke_particle_id is not None:
            if (
                isinstance(smoke_particle_id, bool)
                or not isinstance(smoke_particle_id, int)
                or smoke_particle_id < 1
                or smoke_particle_id > int(source_materialization_profile["particle_count"])
            ):
                raise ContractError("independent-source functional smoke member is invalid")
            # Functional-only N=1 confirms the plumbing with a registered
            # near-axis member of the same frozen N=5000 mother.  Scientific
            # cases always retain their complete ordered population.
            prefix_ids = [smoke_particle_id]
        else:
            prefix_ids = list(range(1, pulse_population_count + 1))
        pulse_prefix_path = plan_output.parent / "inputs" / (
            "pre_pulse_time_series_screening_prefix_n"
            + str(pulse_population_count) + ".csv"
        )
        pulse_prefix_path.parent.mkdir(parents=True, exist_ok=True)
        pulse_prefix_sha256 = write_pulse_resolution_screening_prefix(
            pulse_prefix_source_path,
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
            f"automatic_pulse_timing_prefix_n{pulse_population_count}.csv"
            )
            pulse_prefix_path.parent.mkdir(parents=True, exist_ok=True)
            pulse_prefix_sha256 = write_pulse_resolution_screening_prefix(
                pulse_prefix_source_path,
                pulse_prefix_path,
                ordered_particle_ids=list(range(1, pulse_population_count + 1)),
            )
            pulse_population_plan_path = "inputs/" + pulse_prefix_path.name
        else:
            pulse_prefix_path = pulse_prefix_source_path
            pulse_prefix_sha256 = file_sha256(pulse_prefix_path)
            pulse_population_plan_path = (
                "inputs/" + pulse_prefix_path.name
                if materialized_source_path is not None
                else source["particle_source"]["path"]
            )
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
    if design_reference is not None:
        resolved_source_contract["design_reference"] = {
            "run_id": design_reference["run_id"],
            "manifest": copy.deepcopy(design_reference["manifest"]),
        }
    validate_schema(
        resolved_source_contract,
        INTEGRATION_SCHEMA_DIR / "rf_multipole_oatof_source_contract.schema.json",
    )
    plan_output.parent.mkdir(parents=True, exist_ok=True)
    resolved_source_contract_path = plan_output.with_name(
        "resolved_source_contract.json"
    )
    _write_json(resolved_source_contract_path, resolved_source_contract)

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
    _write_json(upstream_port_path, upstream_port)
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
        three_zone_candidate_binding = validate_three_zone_candidate_binding(
            experiment, layout_profile
        )
        three_zone_candidate_path = None
        if layout_profile["method"] == "t5_frozen_three_zone_candidate_v1":
            if experiment_overrides:
                raise ContractError(
                    "three-zone T5 layout prohibits experiment design overrides"
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
            if not isinstance(selected_field_profile.get("field_id"), str) or not (
                selected_field_profile["field_id"]
            ):
                raise ContractError(
                    "three-zone field profile scientific identity is absent"
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
        if (
            experiment.get("single_flight_oatof_numerical_profile_id") is not None
            and execution_profile is not None
        ):
            reflectron_mesh = execution_profile["reflectron_cell_mm"]
            geometry["simion_geometry_build"]["reflectron"]["cell_axial_mm"] = float(
                reflectron_mesh["axial"]
            )
            geometry["simion_geometry_build"]["reflectron"]["cell_radial_mm"] = float(
                reflectron_mesh["radial"]
            )
        geometry_path = plan_output.with_name("resolved_oatof_geometry.json")
        _write_json(geometry_path, geometry)
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
        # The connection resolver runs with the repository as its managed
        # root, whereas this derived port itself is stored in the run-local
        # workspace.  Its authority therefore needs a repository-relative
        # geometry path, not a second workspace-relative path.
        downstream_port["authority"]["source_contract"] = (
            geometry_path.resolve().relative_to(root.parent.resolve()).as_posix()
        )
        downstream_port["authority"]["source_sha256"] = file_sha256(geometry_path)
        downstream_port_path = plan_output.with_name("resolved_downstream_port.json")
        _write_json(downstream_port_path, downstream_port)
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
    _write_json(resolved_registry_path, resolved_registry)

    source_identity = {
        "source_branch_id": solver_id,
        "solver_id": solver_id,
        "run_id": source["run_id"],
        "project_id": expected_project_id,
        "manifest_sha256": source["manifest"]["sha256"],
        "event_sha256": source["state"]["sha256"],
        "particle_source_sha256": source["particle_source"]["sha256"],
        "metadata_sha256": source["metadata"]["sha256"],
    }
    if observed_pre_pulse_projection is not None:
        source_identity["observed_pre_pulse_projection"] = copy.deepcopy(
            observed_pre_pulse_projection
        )
    row_sha256 = _canonical_sha256(experiment)
    execution_particle_count = (
        int(population_declaration["execution_population"]["particle_count"])
        if execution_strategy == "simion_single_flight"
        else evidence["particle_count"]
    )
    if execution_strategy == "simion_single_flight":
        # A PA topology is a resource property, not a scientific control. The
        # shared scheduler must not reuse a full-flight peak for the minimal
        # three-instance detector-blind pre-pulse IOB (or vice versa).
        workload_topology_id = (
            "pre_pulse_minimal_3_instance_iob_v1"
            if pre_pulse_time_series_specification is not None
            else "post_pulse_5_instance_iob_v1"
            if source_release_mode == "pre_pulse_restart"
            else "axis_field_export_5_instance_iob_v1"
            if single_flight_execution_mode == "program_axis_field_export"
            else "full_flight_7_instance_iob_v1"
        )
        resource_profiles = discover_resource_profiles(
            workspace / "artifacts" / "projects" / INTEGRATION_ID / "runs"
        )
        single_flight_dispatch_plan = resolve_single_flight_dispatch_plan(
            experiment, execution_particle_count=execution_particle_count,
            rf_steps_per_period=(
                int(execution_profile["rf_steps_per_period"])
                if execution_profile is not None else None
            ),
            execution_profile=execution_profile,
            resource_profiles=resource_profiles,
            workload_topology_id=workload_topology_id,
        )
    else:
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
    _write_json(resolved_budget_path, resolved_budget)

    resolved_path, plan_path = write_resolved_and_plan(
        resolved_registry_path,
        experiment["connection_profile_id"],
        resolved_output,
        plan_output,
        repo_root=root,
    )
    terminal_handoff_global_state_path = None
    terminal_handoff_receipt_path = None
    terminal_handoff_smoke_source_particle_id = None
    terminal_handoff_execution_particle_count = None
    terminal_handoff_upstream_loss_count = None
    source_zvz_affine_receipt_path = None
    source_zvz_theory_working_point_path = None
    resolved_population_path = None
    pulse_timing_state = None
    base_schedule = None
    resolved_pulse_schedule = None
    pulse_restart_validation_path = None
    if source_release_mode == "continuous_frontend_handoff":
        # The upstream terminal state is the physical handoff.  Build an
        # identity-bearing global view only for population registration; the
        # runner re-materializes from this same immutable terminal CSV.
        raw_source_path = _workspace_record(
            workspace, source["particle_source"], "terminal handoff mass/charge source"
        )
        with raw_source_path.open(encoding="utf-8-sig", newline="") as handle:
            raw_rows = list(csv.DictReader(handle))
        masses = {float(row["mass_amu"]) for row in raw_rows}
        charges = {int(row["charge_state"]) for row in raw_rows}
        if len(masses) != 1 or len(charges) != 1:
            raise ContractError("terminal handoff requires one frozen mass and charge")
        terminal_handoff_mass_amu = next(iter(masses))
        terminal_handoff_charge_state = next(iter(charges))
        smoke_value = experiment.get("terminal_handoff_smoke_source_particle_id")
        if smoke_value is not None:
            if (
                isinstance(smoke_value, bool)
                or not isinstance(smoke_value, int)
                or smoke_value < 1
                or population_declaration["execution_population"]["particle_count"] != 1
                or population_declaration["execution_population"]["selection_algorithm"]
                != "explicit_single_terminal_handoff_particle_id_v1"
            ):
                raise ContractError("terminal-handoff smoke population declaration differs")
            terminal_handoff_smoke_source_particle_id = smoke_value
        elif population_declaration["execution_population"]["selection_algorithm"] == (
            "first_n_transmitted_terminal_handoffs_in_source_particle_id_order"
        ):
            terminal_handoff_execution_particle_count = population_declaration[
                "execution_population"
            ]["particle_count"]
        try:
            _, handoff_rows, _, handoff_receipt = materialize_terminal_handoff_continuation(
                design_evidence["state_path"], _load(resolved_path),
                mass_amu=terminal_handoff_mass_amu,
                charge_state=terminal_handoff_charge_state,
                smoke_source_particle_id=terminal_handoff_smoke_source_particle_id,
                execution_particle_count=terminal_handoff_execution_particle_count,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("terminal handoff continuation materialization failed") from exc
        if int(handoff_receipt["mother_particle_count"]) != evidence["launched_particle_count"]:
            raise ContractError("terminal handoff mother cohort differs from source authority")
        terminal_handoff_upstream_loss_count = int(handoff_receipt["upstream_loss_count"])
        terminal_handoff_global_state_path = plan_output.parent / "inputs" / (
            "terminal_handoff_continuation_global_state.csv"
        )
        terminal_handoff_global_state_path.parent.mkdir(parents=True, exist_ok=True)
        with terminal_handoff_global_state_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(handoff_rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(handoff_rows)
        terminal_handoff_receipt_path = plan_output.parent / "inputs" / (
            "terminal_handoff_continuation_receipt.json"
        )
        _write_json(terminal_handoff_receipt_path, handoff_receipt)
        # Detector-blind pre-pulse screening must use the same physical
        # handoff population that will enter the OA run, never a raw-source
        # prefix selected only for the legacy continuous-front-end path.
        pulse_prefix_path = terminal_handoff_global_state_path
        pulse_prefix_sha256 = file_sha256(terminal_handoff_global_state_path)
        pulse_population_count = len(handoff_rows)
        pulse_population_plan_path = "inputs/" + terminal_handoff_global_state_path.name
    if layout_files is not None:
        schedule = None
        if pulse_schedule_policy is not None:
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
                _write_json(
                    pulse_restart_validation_path, restart_reuse["validation"]
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
            else:
                schedule = None
                if (
                    pulse_prefix_sha256 is not None
                    and pre_pulse_time_series_specification is None
                    and cache_miss_policy is not None
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
            validate_schema(
                schedule,
                INTEGRATION_SCHEMA_DIR / "rf_oatof_resolved_single_flight_pulse_schedule.schema.json",
            )
            schedule_path = plan_output.with_name("resolved_single_flight_pulse_schedule.json")
            _write_json(schedule_path, schedule)
            layout_files["schedule"] = schedule_path
            # A pre-pulse screen must be centred on the exact schedule that
            # this run will use.  A campaign may describe window width and RF
            # sampling density, but it must not replace the resolved physical
            # pulse time with a stale hand-written epoch.
            resolved_pulse_schedule = schedule
        if (
            pre_pulse_source_path is not None
            and pre_pulse_source_state is not None
            and pre_pulse_receipt_path is not None
            and post_pulse_restart_authority is None
            and _load(pre_pulse_receipt_path).get("role")
            == TIME_SERIES_RESTART_RECEIPT_ROLE
        ):
            pulse_restart_validation = _validate_time_series_restart_state(
                pre_pulse_source_path,
                pre_pulse_receipt_path,
                pre_pulse_source_state,
                schedule,
            )
            pulse_restart_validation_path = plan_output.with_name(
                "canonical_pulse_restart_target_state_validation.json"
            )
            _write_json(pulse_restart_validation_path, pulse_restart_validation)
        elif (
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
            _write_json(pulse_restart_validation_path, pulse_restart_validation)
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
            == "independent_spatial_velocity_ion_source_snapshot"
        ):
            if (
                materialized_source_path is None
                or materialization_receipt_path is None
                or materialization_receipt is None
            ):
                raise ContractError(
                    "independent ion-source volume must materialize before pulse preparation"
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
                    INTEGRATION_SCHEMA_DIR / "rf_oatof_source_zvz_affine_receipt.schema.json",
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ContractError("automatic source z--vz identification failed") from exc
        theory_working_point_request = experiment.get(
            "single_flight_source_zvz_theory_working_point"
        )
        if theory_working_point_request is not None:
            if source_zvz_affine_receipt_path is None or resolved_region_field_contract_path is None:
                raise ContractError("source theory working point requires source z--vz binding")
            if not field_profiles or not isinstance(
                field_profiles[0].get("topology_id"), str
            ):
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
                _write_json(source_zvz_theory_working_point_path, working_point)
                validate_schema(
                    _load(source_zvz_theory_working_point_path),
                    INTEGRATION_SCHEMA_DIR / "rf_oatof_theory_working_point.schema.json",
                )
                _write_json(geometry_path, geometry)
                downstream_port["authority"]["source_sha256"] = file_sha256(geometry_path)
                _write_json(downstream_port_path, downstream_port)
                _write_json(resolved_registry_path, resolved_registry)
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
                pulse_target_source_path is None
                or materialization_receipt_path is None
            ):
                raise ContractError(
                    "generated ordered subset requires a materialized mother"
                )
            if generated_ordered_source_ids is None:
                raise ContractError("generated ordered subset resolution is missing")
            ordered_source_ids = generated_ordered_source_ids
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
                INTEGRATION_SCHEMA_DIR / "rf_oatof_pre_pulse_ordered_subset_receipt.schema.json",
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
                    INTEGRATION_SCHEMA_DIR / "rf_oatof_observed_pre_pulse_projection_receipt.schema.json",
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
            _write_json(pulse_restart_validation_path, pulse_restart_validation)
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
        elif table_binding in {
            "prepared_materialized_particle_source",
            "prepared_materialized_ion_source_volume",
        }:
            if materialized_source_path is None:
                raise ContractError("population declaration requires a materialized source table")
            population_path = materialized_source_path
            population_input_role = (
                "single_flight_materialized_ion_source_volume"
                if table_binding == "prepared_materialized_ion_source_volume"
                else "single_flight_materialized_particle_source"
            )
        elif table_binding == "prepared_deterministic_prefix":
            if pulse_prefix_path is None:
                raise ContractError("population declaration requires a deterministic prefix table")
            population_path = pulse_prefix_path
            population_input_role = population_declaration["source_authority"][
                "input_role"
            ]
        elif table_binding == "terminal_handoff_continuation_global_state":
            if terminal_handoff_global_state_path is None:
                raise ContractError("population declaration requires a terminal handoff state")
            population_path = terminal_handoff_global_state_path
            population_input_role = "terminal_handoff_continuation_global_state"
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
        )
        resolved_population_path = plan_output.with_name(
            "resolved_population_contract.json"
        )
        _write_json(resolved_population_path, resolved_population)
    pre_pulse_time_series_contract_path = None
    if (
        pre_pulse_time_series_specification is not None
        or pulse_timing_state == "discovery_required"
    ):
        if (
            pulse_prefix_path is None or pulse_prefix_sha256 is None
            or resolved_population_path is None or resolved_region_field_contract is None
            or layout_files is None or execution_profile is None
            or not field_profiles
        ):
            raise ContractError("pre-pulse time-series prepared identity is incomplete")
        screening_specification = pre_pulse_time_series_specification
        if (
            resolved_pulse_schedule is not None
            and screening_specification is not None
            and "time_grid_profile_id" not in screening_specification
        ):
            # Legacy authoring contracts named an absolute anchor.  Once a
            # resolved schedule becomes authoritative, inherit its registered
            # RF-grid identity from the execution policy when available.  A
            # valid already-resolved schedule does not need a cache-miss
            # policy merely to obtain a label: its own immutable schedule is
            # the timing authority.
            screening_specification = copy.deepcopy(screening_specification)
            screening_specification["time_grid_profile_id"] = (
                cache_miss_policy["time_grid_profile_id"]
                if cache_miss_policy is not None
                else "resolved_schedule_native_rf_grid_v1"
            )
        if screening_specification is None:
            native_rf_steps = int(execution_profile["rf_steps_per_period"])
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
            resolved_connection=_load(resolved_path),
            selected_field_profile=field_profiles[0],
            region_field_semantic_sha256=resolved_region_field_contract[
                "semantic_sha256"
            ],
            rf_steps_per_period=int(screening_specification["rf_steps_per_period"]),
            specification=screening_specification,
            # The resolved execution profile is the numerical authority.  An
            # exploration override need not duplicate a registered profile
            # merely to label this generated screening contract.
            time_integration_profile_id=str(
                execution_profile["time_integration_profile_id"]
            ),
            base_schedule=resolved_pulse_schedule,
            execution_profile=execution_profile,
        )
        pre_pulse_time_series_contract_path = plan_output.parent / "inputs" / (
            "pre_pulse_time_series_screening_contract.json"
        )
        _write_json(
            pre_pulse_time_series_contract_path, pre_pulse_time_series_contract
        )
    pa_cache_generation_binding_path = None
    if pa_cache_generation_binding is not None:
        pa_cache_generation_binding_path = plan_output.parent / "inputs" / (
            "single_flight_pa_cache_generation_binding.json"
        )
        _write_json(pa_cache_generation_binding_path, pa_cache_generation_binding)
    resolved_execution_profile_path = None
    if execution_profile is not None:
        resolved_execution_profile_path = plan_output.parent / "inputs" / (
            "resolved_single_flight_execution_profile.json"
        )
        _write_json(resolved_execution_profile_path, execution_profile, sort_keys=True)
    frozen_authoring_path = plan_output.parent / "inputs" / (
        "frozen_campaign_experiment.json"
    )
    frozen_campaign = {
        key: copy.deepcopy(campaign[key])
        for key in (
            "role", "integration_id", "campaign_id", "schema_version", "status",
        )
    }
    if campaign.get("pre_pulse_time_series_screening") is not None:
        frozen_campaign["pre_pulse_time_series_screening"] = copy.deepcopy(
            campaign["pre_pulse_time_series_screening"]
        )
    _write_json(frozen_authoring_path, {
        "schema_version": 1,
        "role": "rf_oatof_frozen_campaign_experiment",
        "campaign_source": {
            "path": campaign_path.relative_to(root).as_posix(),
        },
        "campaign": frozen_campaign,
        "experiment_row_sha256": row_sha256,
        "experiment": experiment,
    })
    plan = _load(plan_path)
    plan["execution_steps"] = [
        {
            "step_id": "rf_to_oatof_transfer",
            "adapter": "powershell",
            "entrypoint": mapping["adapter_entrypoint"],
            "arguments": [
                f"adapter_sha256={mapping['adapter_sha256']}",
                f"campaign_path={campaign_path.relative_to(root).as_posix()}",
                "frozen_campaign_experiment_filename=inputs/"
                + frozen_authoring_path.name,
                "frozen_campaign_experiment_sha256="
                + file_sha256(frozen_authoring_path),
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
                "single_flight_execution_mode=" + single_flight_execution_mode,
                "single_flight_pa_cache_policy=" + pa_cache_policy,
                "single_flight_pa_cache_policy_provenance="
                + pa_cache_policy_provenance,
                "resolved_single_flight_execution_profile_filename=inputs/"
                + resolved_execution_profile_path.name,
                "resolved_single_flight_execution_profile_sha256="
                + file_sha256(resolved_execution_profile_path),
            ]) + ([] if local_aperture_mm is None else [
            "accelerator_entrance_local_aperture_width_mm="
            + str(local_aperture_mm["width"]),
            "accelerator_entrance_local_aperture_height_mm="
            + str(local_aperture_mm["height"]),
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
            ]) + ([] if terminal_handoff_global_state_path is None else [
                "terminal_handoff_state_path=" + _workspace_relative(
                    design_evidence["state_path"], workspace
                ),
                "terminal_handoff_state_sha256=" + source["state"]["sha256"],
                "terminal_handoff_mother_particle_count="
                + str(evidence["launched_particle_count"]),
                "terminal_handoff_continued_particle_count="
                + str(len(handoff_rows)),
                "terminal_handoff_mass_amu=" + format(terminal_handoff_mass_amu, ".17g"),
                "terminal_handoff_charge_state=" + str(terminal_handoff_charge_state),
                "terminal_handoff_upstream_loss_count="
                + str(terminal_handoff_upstream_loss_count),
            ] + ([] if terminal_handoff_smoke_source_particle_id is None else [
                "terminal_handoff_smoke_source_particle_id="
                + str(terminal_handoff_smoke_source_particle_id),
            ]) + ([] if terminal_handoff_execution_particle_count is None else [
                "terminal_handoff_execution_particle_count="
                + str(terminal_handoff_execution_particle_count),
            ]) + [
            "terminal_handoff_receipt_filename=inputs/"
                + terminal_handoff_receipt_path.name,
                "terminal_handoff_receipt_sha256="
                + file_sha256(terminal_handoff_receipt_path),
            ]) + ([] if source_profile_id is None else [
                "source_profile_id=" + source_profile_id,
                "field_overlay_id=" + field_overlay_id,
            ]) + ([] if pre_pulse_source_path is None else [
                "pre_pulse_source_state_path="
                + _workspace_relative(pre_pulse_source_path, workspace),
                "pre_pulse_source_state_sha256=" + pre_pulse_source_state["sha256"],
                "pre_pulse_source_state_count="
                + str(pre_pulse_source_state["particle_count"]),
            ]) + ([] if pre_pulse_source_path is None or pulse_restart_validation_path is None else [
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
            INTEGRATION_SCHEMA_DIR / "rf_oatof_resolved_pulse_timing_orchestration.schema.json",
        )
        orchestration_path = plan_output.with_name(
            "resolved_pulse_timing_orchestration.json"
        )
        _write_json(orchestration_path, orchestration)
        plan["execution_steps"][0]["arguments"].extend([
            "pulse_timing_orchestration_filename=" + orchestration_path.name,
            "pulse_timing_orchestration_sha256=" + file_sha256(orchestration_path),
            "pulse_timing_orchestration_state=" + pulse_timing_state,
        ])
    execution_arguments: dict[str, str] = {}
    for argument in plan["execution_steps"][0]["arguments"]:
        name, separator, value = argument.partition("=")
        if not separator or not name or name in execution_arguments:
            raise ContractError("resolved execution plan arguments are invalid")
        execution_arguments[name] = value
    resolved_execution_plan = {
        "schema_version": 1,
        "role": "rf_oatof_resolved_execution_plan",
        "campaign_id": campaign["campaign_id"],
        "experiment_id": experiment_id,
        "experiment_row_sha256": row_sha256,
        "execution_strategy": execution_strategy,
        "arguments": execution_arguments,
    }
    resolved_execution_plan_path = plan_output.with_name("resolved_execution_plan.json")
    _write_json(resolved_execution_plan_path, resolved_execution_plan, sort_keys=True)
    plan["execution_steps"][0]["arguments"].extend([
        "resolved_execution_plan_filename=" + resolved_execution_plan_path.name,
        "resolved_execution_plan_sha256=" + file_sha256(resolved_execution_plan_path),
    ])
    validate_schema(plan, "composition_plan.schema.json")
    _write_json(plan_path, plan)
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
    parser.add_argument("--exploration", action="store_true")
    parser.add_argument("--execution-run-id")
    args = parser.parse_args()
    if args.list_experiment_ids or args.print_experiment_json or args.semantic_diff_experiment_json:
        authored_campaign = _load(args.campaign)
        validate_schema(authored_campaign, CAMPAIGN_SCHEMA_PATH)
        require_minimal_flat_experiment_authoring(authored_campaign)
        campaign = expand_flat_experiment_authoring(authored_campaign)
        validate_schema(campaign, RESOLVED_CAMPAIGN_SCHEMA_PATH)
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
        exploration=args.exploration,
        execution_run_id=args.execution_run_id,
    )
    print(f"FAMILY_SOURCE_CLOSURE_PREPARE=PASS RESOLVED={resolved} PLAN={plan}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
