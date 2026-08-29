"""Validate and retain recoverable pre-pulse SIMION batch prefixes.

SIMION does not expose a portable in-process trajectory checkpoint.  The
durable recovery unit is therefore a terminally recorded particle: an
interrupted batch contributes only its validated contiguous terminal prefix;
the next run launches its missing suffix with the original global ID mapping.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Sequence

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.materialize_pre_pulse_time_series import (
    PROHIBITED_DOWNSTREAM_PATTERN,
    TERMINAL_PATTERN,
    TERMINAL_PREFIX,
    TRACE_PATTERN,
    TRACE_PREFIX,
)


ROLE = "rf_oatof_pre_pulse_batch_continuation_plan"


def _load_object(path: Path, role: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{role} is unreadable") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{role} must be an object")
    return value


def _manifest_hashes(run_dir: Path) -> dict[Path, str]:
    manifest = _load_object(run_dir / "run_manifest.json", "predecessor manifest")
    if (
        manifest.get("role") != "simulation_run_manifest"
        or manifest.get("status") not in {"failed", "interrupted"}
    ):
        raise ContractError("pre-pulse continuation predecessor manifest status differs")
    records = manifest.get("outputs")
    if not isinstance(records, list):
        raise ContractError("pre-pulse continuation predecessor outputs are missing")
    result: dict[Path, str] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        path, digest = record.get("path"), record.get("sha256")
        if isinstance(path, str) and isinstance(digest, str) and len(digest) == 64:
            result[Path(path).resolve()] = digest.upper()
    config_record = manifest.get("run_config")
    if not isinstance(config_record, dict):
        raise ContractError("pre-pulse continuation predecessor run config is unbound")
    config_path = run_dir / "run_config.json"
    if config_record.get("sha256") != file_sha256(config_path):
        raise ContractError("pre-pulse continuation predecessor run config hash differs")
    return result


def _imported_trace_hashes(run_dir: Path) -> dict[Path, str]:
    """Load prior imported-prefix bindings for a second or later recovery."""
    plan_path = run_dir / "inputs" / "pre_pulse_batch_continuation" / (
        "pre_pulse_batch_continuation_plan.json"
    )
    if not plan_path.is_file():
        return {}
    plan = _load_object(plan_path, "prior pre-pulse continuation plan")
    if plan.get("role") != ROLE or not isinstance(plan.get("batches"), list):
        raise ContractError("prior pre-pulse continuation plan differs")
    result: dict[Path, str] = {}
    for batch in plan["batches"]:
        trace = batch.get("imported_completed_trace") if isinstance(batch, dict) else None
        if not isinstance(trace, dict):
            continue
        path, digest = trace.get("path"), trace.get("sha256")
        if not isinstance(path, str) or not isinstance(digest, str) or len(digest) != 64:
            raise ContractError("prior pre-pulse imported trace binding differs")
        result[Path(path).resolve()] = digest.upper()
    return result


def _batch_logs(run_dir: Path, index: int) -> list[Path]:
    imported = run_dir / "inputs" / "imported_completed_batches" / (
        f"batch{index:02d}.stdout.log"
    )
    logs = [imported] if imported.is_file() else []
    logs.extend(sorted((run_dir / "logs").glob(f"simion__batch{index:02d}*.stdout.log")))
    if not logs:
        return []
    if len({path.resolve() for path in logs}) != len(logs):
        raise ContractError("pre-pulse continuation batch log is duplicated")
    return logs


def _validate_plan(plan: dict[str, Any], particle_ids: Sequence[int]) -> list[dict[str, int]]:
    if plan.get("role") != "simion_single_wave_particle_batch_plan":
        raise ContractError("pre-pulse continuation batch plan role differs")
    batches = plan.get("batches")
    if not isinstance(batches, list) or not batches:
        raise ContractError("pre-pulse continuation batch plan is empty")
    expected = list(particle_ids)
    actual: list[int] = []
    normalized: list[dict[str, int]] = []
    for index, batch in enumerate(batches, start=1):
        if not isinstance(batch, dict):
            raise ContractError("pre-pulse continuation batch is invalid")
        try:
            first = int(batch["particle_id_min"])
            last = int(batch["particle_id_max"])
            count = int(batch["count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("pre-pulse continuation batch range is invalid") from exc
        if int(batch.get("index", -1)) != index or count < 1 or last - first + 1 != count:
            raise ContractError("pre-pulse continuation batch range differs")
        actual.extend(range(first, last + 1))
        normalized.append({"index": index, "first": first, "last": last, "count": count})
    if actual != expected:
        raise ContractError("pre-pulse continuation batch plan does not cover frozen cohort")
    return normalized


def _completed_prefix(
    paths: Sequence[Path], *, first: int, count: int, expected_hashes: dict[Path, str]
) -> tuple[int, list[str], list[dict[str, str]]]:
    """Return one verified terminal prefix and sanitized TRACE lines."""
    expected = first
    terminal_ids: set[int] = set()
    state_keys: set[tuple[int, int]] = set()
    retained: list[tuple[int, str]] = []
    sources: list[dict[str, str]] = []
    saw_completed = False
    for path in paths:
        expected_hash = expected_hashes.get(path.resolve())
        if expected_hash is None or file_sha256(path) != expected_hash:
            raise ContractError("pre-pulse continuation source log hash differs")
        try:
            lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
        except (OSError, UnicodeError) as exc:
            raise ContractError("pre-pulse continuation log is unreadable") from exc
        sources.append({"path": str(path), "sha256": file_sha256(path)})
        for line in lines:
            if PROHIBITED_DOWNSTREAM_PATTERN.match(line):
                raise ContractError("pre-pulse continuation emitted prohibited downstream TRACE")
            if line.startswith(TERMINAL_PREFIX):
                match = TERMINAL_PATTERN.fullmatch(line)
                if match is None:
                    raise ContractError("pre-pulse continuation terminal TRACE is malformed")
                particle_id = int(match["particle_id"])
                if particle_id != expected or particle_id in terminal_ids:
                    raise ContractError("pre-pulse continuation terminal IDs are not a contiguous prefix")
                terminal_ids.add(particle_id)
                retained.append((particle_id, line))
                expected += 1
            elif line.startswith(TRACE_PREFIX):
                match = TRACE_PATTERN.fullmatch(line)
                if match is None:
                    raise ContractError("pre-pulse continuation state TRACE is malformed")
                particle_id = int(match["particle_id"])
                sample_index = int(match["sample_index"])
                key = (particle_id, sample_index)
                if particle_id < first or particle_id >= first + count or key in state_keys:
                    raise ContractError("pre-pulse continuation state identity differs")
                state_keys.add(key)
                retained.append((particle_id, line))
            elif line.startswith("status,Fly completed."):
                saw_completed = True
    completed = len(terminal_ids)
    if completed > count or (saw_completed and completed != count):
        raise ContractError("pre-pulse continuation completion sentinel differs")
    cutoff = first + completed
    sanitized = [line for particle_id, line in retained if particle_id < cutoff]
    return completed, sanitized, sources


def build_continuation_plan(
    *, predecessor_run_dir: Path, particle_ids: Sequence[int],
    expected_contract_sha256: str, output_dir: Path,
) -> dict[str, Any]:
    """Create a batch-by-batch replay plan from an interrupted predecessor."""
    predecessor_run_dir = predecessor_run_dir.resolve()
    expected_hashes = _manifest_hashes(predecessor_run_dir)
    expected_hashes.update(_imported_trace_hashes(predecessor_run_dir))
    config = _load_object(predecessor_run_dir / "run_config.json", "predecessor run configuration")
    parameters = config.get("parameters")
    if not isinstance(parameters, dict) or parameters.get("execution_mode") != "real_pa_rf_pre_pulse_time_series":
        raise ContractError("pre-pulse continuation predecessor mode differs")
    if parameters.get("particle_count") != len(particle_ids) or parameters.get("launched_particle_count") != len(particle_ids):
        raise ContractError("pre-pulse continuation predecessor population differs")
    contract = predecessor_run_dir / "inputs" / "pre_pulse_time_series_screening_contract.json"
    if not contract.is_file() or file_sha256(contract) != expected_contract_sha256.upper():
        raise ContractError("pre-pulse continuation contract identity differs")
    plan = _load_object(predecessor_run_dir / "inputs" / "simion_execution_batch_plan.json", "predecessor batch plan")
    batches = _validate_plan(plan, particle_ids)
    imported_root = output_dir / "imported_completed_batches"
    output: list[dict[str, Any]] = []
    for batch in batches:
        logs = _batch_logs(predecessor_run_dir, batch["index"])
        completed, retained, sources = _completed_prefix(
            logs, first=batch["first"], count=batch["count"], expected_hashes=expected_hashes
        ) if logs else (0, [], [])
        imported = None
        if completed:
            imported_root.mkdir(parents=True, exist_ok=True)
            path = imported_root / f"batch{batch['index']:02d}.stdout.log"
            path.write_text("\n".join(retained) + "\n", encoding="utf-8", newline="\n")
            imported = {"path": str(path), "sha256": file_sha256(path)}
        output.append({
            "index": batch["index"], "particle_id_min": batch["first"],
            "particle_id_max": batch["last"], "count": batch["count"],
            "completed_particle_count": completed,
            "replay_particle_id_min": batch["first"] + completed,
            "replay_particle_count": batch["count"] - completed,
            "imported_completed_trace": imported, "source_logs": sources,
        })
    result = {
        "schema_version": 1, "role": ROLE, "status": "ready",
        "predecessor_run_dir": str(predecessor_run_dir),
        "predecessor_batch_plan_sha256": file_sha256(predecessor_run_dir / "inputs" / "simion_execution_batch_plan.json"),
        "expected_contract_sha256": expected_contract_sha256.upper(),
        "particle_count": len(particle_ids), "batches": output,
        "completed_particle_count": sum(item["completed_particle_count"] for item in output),
        "replay_particle_count": sum(item["replay_particle_count"] for item in output),
    }
    if result["completed_particle_count"] + result["replay_particle_count"] != len(particle_ids):
        raise AssertionError("continuation plan does not cover frozen cohort")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "pre_pulse_batch_continuation_plan.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return result


def _particle_ids_from_row_map(path: Path) -> list[int]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            values = [int(row["source_particle_id"]) for row in reader]
    except (OSError, UnicodeError, csv.Error, KeyError, TypeError, ValueError) as exc:
        raise ContractError("pre-pulse continuation particle row map is invalid") from exc
    if not values or values != list(range(1, len(values) + 1)):
        raise ContractError("pre-pulse continuation particle row map is not canonical")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predecessor-run-dir", required=True, type=Path)
    parser.add_argument("--particle-row-map", required=True, type=Path)
    parser.add_argument("--contract-sha256", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    result = build_continuation_plan(
        predecessor_run_dir=args.predecessor_run_dir,
        particle_ids=_particle_ids_from_row_map(args.particle_row_map),
        expected_contract_sha256=args.contract_sha256, output_dir=args.output_dir,
    )
    print(
        "PRE_PULSE_BATCH_CONTINUATION=PASS "
        f"COMPLETED={result['completed_particle_count']} REPLAY={result['replay_particle_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
