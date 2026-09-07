"""Immutable batch continuation adapter for continuous OA-TOF full flight."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
from typing import Any, Mapping

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from common.simion.batch_continuation import (
    TraceContinuationPolicy,
    build_batch_continuation_plan,
)


SOURCE_RELEASE_PREFIX = "TRACE: source_release"
SOURCE_RELEASE_PATTERN = re.compile(
    r"^TRACE: source_release ion=(?P<ion>\d+) particle_id=(?P<particle_id>\d+) .+$"
)
TERMINAL_PREFIX = "TRACE: handoff_terminal_raw"
TERMINAL_PATTERN = re.compile(
    r"^TRACE: handoff_terminal_raw ion=(?P<ion>\d+) instance=\d+ .+$"
)
NEVER_STATE_PATTERN = re.compile(r"(?!)")

FULL_FLIGHT_POLICY = TraceContinuationPolicy(
    terminal_prefix=TERMINAL_PREFIX,
    terminal_pattern=TERMINAL_PATTERN,
    state_prefix="TRACE: __no_full_flight_state__",
    state_pattern=NEVER_STATE_PATTERN,
    completion_prefix="status,Fly completed.",
    release_prefix=SOURCE_RELEASE_PREFIX,
    release_pattern=SOURCE_RELEASE_PATTERN,
    allow_auxiliary_trace=True,
    retain_entire_log=True,
)

# These inputs jointly freeze the source cohort, clock/program, physical
# geometry, field semantics, numerical grid and the independently cached PA
# providers that existed as stable run-config roles before continuation was
# introduced.  Domain-local contract hashes are additionally embedded in the
# program metadata; their selected PA generation keys are checked below.
FROZEN_INPUT_ROLES = (
    "mother_particle_source",
    "initial_global_state",
    "particle_row_map",
    "resolved_connection",
    "resolved_source_contract",
    "resolved_population_contract",
    "resolved_single_flight_execution_profile",
    "upstream_resolved_design",
    "oatof_resolved_geometry",
    "pulse_schedule",
    "resolved_region_field_contract",
    "frontend_contract",
    "program_metadata",
    "frontend_pa_cache_manifest",
    "flight_tube_pa_cache_manifest",
    "three_zone_t5_candidate",
)

IDENTITY_PARAMETER_NAMES = (
    "connection_profile_id",
    "layout_profile_id",
    "architecture_generation_id",
    "source_profile_id",
    "frontend_grid_profile_id",
    "frontend_cell_mm_xyz",
    "oatof_numerical_profile_id",
    "trajectory_quality",
    "time_integration_profile_id",
    "rf_steps_per_period",
    "accelerator_field_profile_id",
    "resolved_region_field_contract_sha256",
    "resolved_region_field_semantic_sha256",
    "resolved_population_contract_sha256",
    "clock_basis",
    "pulse_time_us",
    "pulse_width_us",
    "post_pulse_observation_window_us",
    "reflectron_pa0_sha256",
    "frontend_pa0_sha256",
    "accelerator_main_reference_aperture_mm",
    "accelerator_entrance_local_aperture_mm",
    "domain_split_iob_instance_count",
    "three_zone_candidate_sha256",
)

PA_IDENTITY_ROLES = (
    "frontend",
    "full_coarse_bridge",
    "fine_upstream",
    "accelerator_main",
    "accelerator_entrance_local",
    "flight_tube",
    "reflectron",
)


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def _configured_path(
    config: Mapping[str, Any], role: str, *, retired_run_dir: Path | None = None,
) -> Path:
    value = (config.get("inputs") or {}).get(role)
    if not isinstance(value, str) or not value:
        raise ContractError(f"full-flight continuation input is missing: {role}")
    path = Path(value).resolve()
    if not path.is_file() and retired_run_dir is not None:
        path = (retired_run_dir / "inputs" / Path(value).name).resolve()
    if not path.is_file():
        raise ContractError(f"full-flight continuation input is missing: {role}")
    return path


def _pa_identity(parameters: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    dispositions = parameters.get("pa_cache_dispositions")
    if not isinstance(dispositions, dict):
        raise ContractError("full-flight continuation PA identity is missing")
    result: dict[str, dict[str, Any]] = {}
    for role in PA_IDENTITY_ROLES:
        value = dispositions.get(role)
        if not isinstance(value, dict):
            raise ContractError(f"full-flight continuation PA identity is missing: {role}")
        result[role] = {"role": value.get("role"), "key": value.get("key")}
    return result


def _identity_projection(config: Mapping[str, Any]) -> dict[str, Any]:
    parameters = config.get("parameters")
    if not isinstance(parameters, dict):
        raise ContractError("full-flight continuation parameters are missing")
    return {
        "parameters": {name: parameters.get(name) for name in IDENTITY_PARAMETER_NAMES},
        "pa_generations": _pa_identity(parameters),
    }


def _particle_ids_from_row_map(path: Path) -> list[int]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        values = [int(row["source_particle_id"]) for row in rows]
    except (OSError, UnicodeError, csv.Error, KeyError, TypeError, ValueError) as exc:
        raise ContractError("full-flight continuation particle row map is invalid") from exc
    if values != list(range(1, len(values) + 1)):
        raise ContractError("full-flight continuation requires canonical ordered particle IDs")
    return values


def build_continuation_plan(
    *, predecessor_run_dir: Path, current_run_config: Path, output_dir: Path,
) -> dict[str, Any]:
    """Verify both immutable runs and plan replay of only unfinished batches."""

    current = _load_object(current_run_config, "current full-flight run configuration")
    predecessor = _load_object(
        predecessor_run_dir / "run_config.json",
        "predecessor full-flight run configuration",
    )
    if _identity_projection(predecessor) != _identity_projection(current):
        raise ContractError("full-flight continuation geometry, field, clock or PA identity differs")
    current_program = _load_object(
        _configured_path(
            current, "program_metadata", retired_run_dir=current_run_config.parent,
        ), "current full-flight program metadata"
    )
    predecessor_program = _load_object(
        _configured_path(
            predecessor, "program_metadata", retired_run_dir=predecessor_run_dir,
        ),
        "predecessor full-flight program metadata",
    )
    if (
        current_program != predecessor_program
        or current_program.get("source_release_mode") != "continuous_frontend"
        or current_program.get("terminate_after_pulse") is not False
        or current_program.get("clock_basis") != "canonical_instrument_time_us"
    ):
        raise ContractError("full-flight continuation program identity differs")
    if (current.get("inputs") or {}).get("pre_pulse_time_series_contract"):
        raise ContractError("full-flight continuation cannot resume pre-pulse screening")

    row_map = _configured_path(
        current, "particle_row_map", retired_run_dir=current_run_config.parent,
    )
    particle_ids = _particle_ids_from_row_map(row_map)
    cohort_paths = {
        role: _configured_path(
            current, role, retired_run_dir=current_run_config.parent,
        )
        for role in FROZEN_INPUT_ROLES
    }
    return build_batch_continuation_plan(
        predecessor_run_dir=predecessor_run_dir,
        particle_ids=particle_ids,
        expected_execution_mode=None,
        contract_input_role="program_metadata",
        expected_contract_sha256=file_sha256(cohort_paths["program_metadata"]),
        cohort_input_paths=cohort_paths,
        policy=FULL_FLIGHT_POLICY,
        output_dir=output_dir,
        continuation_dir_name="full_flight_batch_continuation",
        log_glob="logs/simion__batch{index:02d}*.stdout.log",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predecessor-run-dir", required=True, type=Path)
    parser.add_argument("--current-run-config", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    result = build_continuation_plan(
        predecessor_run_dir=args.predecessor_run_dir,
        current_run_config=args.current_run_config,
        output_dir=args.output_dir,
    )
    print(
        "SIMION_FULL_FLIGHT_BATCH_CONTINUATION=PASS "
        f"COMPLETED={result['completed_particle_count']} "
        f"REPLAY={result['replay_particle_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
