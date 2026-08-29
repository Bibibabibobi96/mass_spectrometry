"""OA-TOF adapter for the repository-wide SIMION batch continuation protocol."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import re
from typing import Any

from common.contracts.machine_contracts import ContractError
from common.simion.batch_continuation import (
    TraceContinuationPolicy,
    build_batch_continuation_plan,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.materialize_pre_pulse_time_series import (
    PROHIBITED_DOWNSTREAM_PATTERN,
    TERMINAL_PATTERN,
    TERMINAL_PREFIX,
    TRACE_PATTERN,
    TRACE_PREFIX,
)


SOURCE_RELEASE_PREFIX = "TRACE: source_release"
SOURCE_RELEASE_PATTERN = re.compile(
    r"^TRACE: source_release ion=(?P<ion>\d+) particle_id=(?P<particle_id>\d+) .+$"
)


PRE_PULSE_POLICY = TraceContinuationPolicy(
    terminal_prefix=TERMINAL_PREFIX,
    terminal_pattern=TERMINAL_PATTERN,
    state_prefix=TRACE_PREFIX,
    state_pattern=TRACE_PATTERN,
    completion_prefix="status,Fly completed.",
    prohibited_patterns=(PROHIBITED_DOWNSTREAM_PATTERN,),
    release_prefix=SOURCE_RELEASE_PREFIX,
    release_pattern=SOURCE_RELEASE_PATTERN,
)


def build_continuation_plan(
    *, predecessor_run_dir: Path, particle_ids: list[int], expected_contract_sha256: str,
    mother_particle_source: Path, initial_global_state: Path, particle_row_map: Path, output_dir: Path,
) -> dict[str, Any]:
    """Build a shared plan with the OA-TOF pre-pulse TRACE policy."""

    return build_batch_continuation_plan(
        predecessor_run_dir=predecessor_run_dir,
        particle_ids=particle_ids,
        expected_execution_mode="real_pa_rf_pre_pulse_time_series",
        contract_input_role="pre_pulse_time_series_contract",
        expected_contract_sha256=expected_contract_sha256,
        cohort_input_paths={
            "mother_particle_source": mother_particle_source,
            "initial_global_state": initial_global_state,
            "particle_row_map": particle_row_map,
        },
        policy=PRE_PULSE_POLICY,
        output_dir=output_dir,
        continuation_dir_name="pre_pulse_batch_continuation",
    )


def _particle_ids_from_row_map(path: Path) -> list[int]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            values = [int(row["source_particle_id"]) for row in csv.DictReader(handle)]
    except (OSError, UnicodeError, csv.Error, KeyError, TypeError, ValueError) as exc:
        raise ContractError("pre-pulse continuation particle row map is invalid") from exc
    if not values or values != list(range(1, len(values) + 1)):
        raise ContractError("pre-pulse continuation particle row map is not canonical")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predecessor-run-dir", required=True, type=Path)
    parser.add_argument("--particle-row-map", required=True, type=Path)
    parser.add_argument("--mother-particle-source", required=True, type=Path)
    parser.add_argument("--initial-global-state", required=True, type=Path)
    parser.add_argument("--contract-sha256", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    result = build_continuation_plan(
        predecessor_run_dir=args.predecessor_run_dir,
        particle_ids=_particle_ids_from_row_map(args.particle_row_map),
        expected_contract_sha256=args.contract_sha256,
        mother_particle_source=args.mother_particle_source,
        initial_global_state=args.initial_global_state,
        particle_row_map=args.particle_row_map,
        output_dir=args.output_dir,
    )
    print(
        "SIMION_BATCH_CONTINUATION=PASS "
        f"COMPLETED={result['completed_particle_count']} REPLAY={result['replay_particle_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
