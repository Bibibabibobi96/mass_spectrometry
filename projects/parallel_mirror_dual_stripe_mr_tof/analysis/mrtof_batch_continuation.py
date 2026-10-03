"""MR-TOF adapter for the repository SIMION whole-batch continuation protocol."""

from __future__ import annotations

import argparse
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


TERMINAL_PATTERN = re.compile(r"^MRTOF_EVENT terminal ion=(?P<ion>\d+) .+$")
NEVER_STATE_PATTERN = re.compile(r"(?!)")
POLICY = TraceContinuationPolicy(
    terminal_prefix="MRTOF_EVENT terminal ",
    terminal_pattern=TERMINAL_PATTERN,
    state_prefix="MRTOF_EVENT __no_continuation_state__ ",
    state_pattern=NEVER_STATE_PATTERN,
    # The repository launcher prints this only after SIMION Fly returns
    # normally; it is the last nonempty line after SIMION's own Fly-completed
    # status record.
    completion_prefix="IOB_FLIGHT: PASS iob=",
    allow_auxiliary_trace=True,
    retain_entire_log=True,
)

# Small direct execution inputs that determine the already-materialized flight.
# Upstream geometry, voltage, source, and pulse identities are already sealed
# inside ``trial_materialization``; repeating them here would add no recovery
# information.  PA payloads stay behind their existing identity manifests.
REQUIRED_INPUT_ROLES = (
    "resolved_iob_pose",
    "operating_point_lua",
    "frozen_source_fly2",
    "iob_builder",
    "iob_seed",
    "native_corridor_priority_contract",
    "flight_program",
    "mirror_cycle_counter",
    "voltage_map",
    "flight_launcher",
    "native_corridor_bank_cache_manifest",
    "native_system_runtime_bundle",
)


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def _configured_path(config: Mapping[str, Any], role: str) -> Path:
    value = (config.get("inputs") or {}).get(role)
    if not isinstance(value, str) or not value:
        raise ContractError(f"MR-TOF continuation input is missing: {role}")
    path = Path(value).resolve()
    if not path.is_file():
        raise ContractError(f"MR-TOF continuation input is missing: {role}")
    return path


def build_continuation_plan(
    *, predecessor_run_dir: Path, current_run_config: Path, output_dir: Path,
) -> dict[str, Any]:
    current = _load_object(current_run_config, "current MR-TOF run configuration")
    trial_path = _configured_path(current, "trial_materialization")
    trial = _load_object(trial_path, "current MR-TOF trial materialization")
    particle_count = int(trial.get("source_particle_count", 0))
    particle_ids = list(range(1, particle_count + 1))
    if particle_count < 2:
        raise ContractError("MR-TOF batch continuation requires an N>1 cohort")
    cohort_paths = {
        role: _configured_path(current, role) for role in REQUIRED_INPUT_ROLES
    }
    return build_batch_continuation_plan(
        predecessor_run_dir=predecessor_run_dir,
        particle_ids=particle_ids,
        expected_execution_mode="mrtof_native_corridor_bunch",
        contract_input_role="trial_materialization",
        expected_contract_sha256=file_sha256(trial_path),
        cohort_input_paths=cohort_paths,
        policy=POLICY,
        output_dir=output_dir,
        continuation_dir_name="mrtof_batch_continuation",
        log_glob="logs/native_two_prism_flight__batch{index:02d}.log",
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
        "MRTOF_BATCH_CONTINUATION=PASS "
        f"COMPLETED={result['completed_particle_count']} "
        f"REPLAY={result['replay_particle_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
