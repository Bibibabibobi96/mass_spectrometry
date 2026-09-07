"""Publish a compact detector-blind pre-pulse handoff from a short run directory."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from common.contracts.artifact_naming import validate_run_id
from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError, validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.scan_pre_pulse_trace_pulse_time import (
    HANDOFF_RECEIPT_SCHEMA_PATH,
    extract_natural_terminal_states,
    pulse_population_partition,
)


INTEGRATION_ID = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
MODE = "rf_oatof_compact_pre_pulse_handoff_recovery"
RESULT_NAMES = (
    "pre_pulse_compact_handoff.csv",
    "pre_pulse_compact_handoff_receipt.json",
    "pre_pulse_compact_handoff_selection.json",
)
TERMINAL_STATE_NAME = "pre_pulse_particle_terminal_states.csv"
COMPACT_SELECTION_METHODS = {
    "native_trace_detector_blind_pulse_selection_v1",
    "native_trace_detector_blind_pulse_selection_v2",
}


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")


def _binding(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": file_sha256(path)}


def _manifest_binding(manifest: dict[str, Any], section: str, name: str, path: Path) -> None:
    """Require the source success manifest to bind this still-present file."""

    records = manifest.get(section)
    record = records.get(name) if isinstance(records, dict) else None
    if not isinstance(record, dict) and section == "outputs" and isinstance(records, list):
        record = next((item for item in records if isinstance(item, dict) and Path(str(item.get("path", ""))).resolve() == path.resolve()), None)
    if not isinstance(record, dict) or not record.get("exists"):
        raise ContractError(f"compact handoff source manifest lacks {section} binding for {name}")
    if record.get("bytes") != path.stat().st_size or record.get("sha256") != file_sha256(path):
        raise ContractError(f"compact handoff source {section} differs from its manifest")


def _frozen_particle_ids(row_map: Path) -> list[int]:
    try:
        with row_map.open(encoding="utf-8-sig", newline="") as handle:
            ids = [int(row["source_particle_id"]) for row in csv.DictReader(handle)]
    except (OSError, UnicodeError, KeyError, ValueError) as exc:
        raise ContractError("compact handoff frozen particle row map is unreadable") from exc
    if not ids or len(ids) != len(set(ids)):
        raise ContractError("compact handoff frozen particle row map is invalid")
    return ids


def _handoff_particle_ids(path: Path) -> list[int]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            ids = [int(row["particle_id"]) for row in csv.DictReader(handle)]
    except (OSError, UnicodeError, KeyError, ValueError) as exc:
        raise ContractError("compact handoff state is unreadable") from exc
    if not ids or len(ids) != len(set(ids)):
        raise ContractError("compact handoff state identities are invalid")
    return ids


def _retained_trace_bindings(source_run_dir: Path, trace_paths: list[Path]) -> list[dict[str, Any]]:
    """Verify the task-retained TRACE copies only by recorded old names/bytes.

    The compact source deliberately retained no TRACE SHA-256.  This is not a
    substitute for such a binding: it records the strictly weaker evidence.
    """
    actions = _load(source_run_dir / "retention_actions.json", "compact handoff retention actions")
    removed = actions.get("removed")
    if not isinstance(removed, list):
        raise ContractError("compact handoff retention actions are incomplete")
    expected = {
        Path(str(item.get("path", ""))).name: item.get("bytes")
        for item in removed if isinstance(item, dict) and str(item.get("path", "")).endswith(".trace.log")
    }
    if not trace_paths or len({path.name for path in trace_paths}) != len(trace_paths):
        raise ContractError("terminal TRACE recovery paths are invalid")
    bindings = []
    for path in trace_paths:
        path = path.resolve()
        if not path.is_file() or expected.get(path.name) != path.stat().st_size:
            raise ContractError("task-retained TRACE does not match source retention name/bytes")
        bindings.append(_binding(path))
    if set(path.name for path in trace_paths) != set(expected):
        raise ContractError("task-retained TRACE set differs from source retention actions")
    return bindings


def publish(*, repo_root: Path, source_run_dir: Path, output_run_dir: Path,
            terminal_trace_logs: list[Path] | None = None) -> Path:
    """Create a manifest-bound compact handoff without retaining raw TRACE."""

    source_run_dir = source_run_dir.resolve()
    output_run_dir = output_run_dir.resolve()
    identity = validate_run_id(output_run_dir.name)
    if identity["activity"] != "analysis" or identity["scope"] != "python":
        raise ContractError("compact handoff recovery run ID must be analysis/python")
    if output_run_dir.exists():
        raise ContractError("compact handoff recovery output already exists")
    source_results = source_run_dir / "results"
    sources = {name: source_results / name for name in RESULT_NAMES}
    if any(not path.is_file() for path in sources.values()):
        raise ContractError("compact handoff source outputs are incomplete")
    source_contract = source_run_dir / "inputs" / "pre_pulse_time_series_screening_contract.json"
    source_row_map = source_run_dir / "inputs" / "single_flight_particle_row_map.csv"
    source_manifest_path = source_run_dir / "run_manifest.json"
    if not source_contract.is_file() or not source_row_map.is_file() or not source_manifest_path.is_file():
        raise ContractError("compact handoff source inputs are incomplete")
    source_manifest = _load(source_manifest_path, "compact handoff source manifest")
    if source_manifest.get("role") != "simulation_run_manifest" or source_manifest.get("status") != "success":
        raise ContractError("compact handoff source manifest is not successful")
    for name, path in sources.items():
        _manifest_binding(source_manifest, "outputs", name, path)
    _manifest_binding(source_manifest, "outputs", "retention_actions", source_run_dir / "retention_actions.json")
    _manifest_binding(source_manifest, "inputs", "particle_row_map", source_row_map)

    receipt = _load(sources["pre_pulse_compact_handoff_receipt.json"], "compact handoff receipt")
    target = receipt.get("pulse_target_state")
    selection = receipt.get("selection")
    if (
        receipt.get("role") != "rf_oatof_compact_pre_pulse_trace_handoff_receipt"
        or receipt.get("status") != "success"
        or receipt.get("method") not in COMPACT_SELECTION_METHODS
        or not isinstance(target, dict)
        or not isinstance(selection, dict)
    ):
        raise ContractError("compact handoff source receipt differs")
    frozen_ids = _frozen_particle_ids(source_row_map)
    producer = receipt.get("producer")
    source_contract_binding = producer.get("screening_contract") if isinstance(producer, dict) else None
    if (not isinstance(source_contract_binding, dict) or source_contract_binding.get("bytes") != source_contract.stat().st_size
            or source_contract_binding.get("sha256") != file_sha256(source_contract)):
        raise ContractError("compact handoff source screening contract differs from receipt")
    selected_ids = selection.get("pulse_eligible_particle_ids")
    handoff_ids = _handoff_particle_ids(sources["pre_pulse_compact_handoff.csv"])
    if (not isinstance(selected_ids, list) or handoff_ids != selected_ids
            or target.get("particle_count") != len(selected_ids)
            or target.get("ordered_particle_id_sha256") != hashlib.sha256(
                json.dumps(selected_ids, separators=(",", ":")).encode("utf-8")
            ).hexdigest().upper()):
        raise ContractError("compact handoff state differs from selected cohort")
    try:
        selection["pulse_population_partition"] = pulse_population_partition(
            mother_count=int(selection["mother_population_count"]),
            alive_count=int(selection["alive_count"]),
            eligible_count=int(selection["pulse_eligible_count"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError("compact handoff source pulse population is incomplete") from exc
    if selection["mother_population_count"] != len(frozen_ids):
        raise ContractError("compact handoff source mother population differs from frozen row map")

    try:
        results = output_run_dir / "results"
        inputs = output_run_dir / "inputs"
        results.mkdir(parents=True)
        inputs.mkdir()
        for name, source in sources.items():
            shutil.copy2(source, results / name)
        frozen_contract = inputs / "pre_pulse_time_series_screening_contract.json"
        frozen_row_map = inputs / "single_flight_particle_row_map.csv"
        frozen_manifest = inputs / "source_run_manifest.json"
        frozen_receipt = inputs / "source_pre_pulse_compact_handoff_receipt.json"
        shutil.copy2(source_contract, frozen_contract)
        shutil.copy2(source_row_map, frozen_row_map)
        shutil.copy2(source_manifest_path, frozen_manifest)
        shutil.copy2(sources["pre_pulse_compact_handoff_receipt.json"], frozen_receipt)
        handoff = results / "pre_pulse_compact_handoff.csv"
        if target.get("sha256") != file_sha256(handoff):
            raise ContractError("compact handoff state differs from source receipt")
        target["path"] = str(handoff)
        if not isinstance(producer, dict):  # defensive after source binding check
            raise ContractError("compact handoff producer is incomplete")
        producer["screening_contract"] = {
            "path": str(frozen_contract), "bytes": frozen_contract.stat().st_size,
            "sha256": file_sha256(frozen_contract),
        }
        producer["source_receipt"] = _binding(frozen_receipt)
        producer["source_manifest"] = _binding(frozen_manifest)
        producer["frozen_particle_row_map"] = _binding(frozen_row_map)
        census = receipt.get("natural_terminal_census")
        terminal_output = results / TERMINAL_STATE_NAME
        if isinstance(census, dict) and isinstance(census.get("terminal_state"), dict):
            # Receipts may contain a run-local junction path; source results is
            # the canonical durable location and is separately manifest-bound.
            source_terminal = source_results / TERMINAL_STATE_NAME
            source_binding = census["terminal_state"]
            if (not source_terminal.is_file() or source_binding.get("bytes") != source_terminal.stat().st_size
                    or source_binding.get("sha256") != file_sha256(source_terminal)):
                raise ContractError("compact handoff source terminal state differs")
            _manifest_binding(source_manifest, "outputs", "terminal_state", source_terminal)
            shutil.copy2(source_terminal, terminal_output)
            census["terminal_state"] = _binding(terminal_output)
        else:
            logs = [path.resolve() for path in (terminal_trace_logs or [])]
            trace_bindings = _retained_trace_bindings(source_run_dir, logs)
            census = extract_natural_terminal_states(
                trace_paths=logs, frozen_particle_ids=frozen_ids, output_path=terminal_output,
            )
            producer["terminal_trace_recovery"] = {
                "method": "task_retained_trace_name_bytes_match_v1",
                "trace_logs": trace_bindings,
                "verification_limit": "source retention actions record original names and bytes only; no source TRACE sha256 exists",
            }
        if (
            census.get("mother_population_count") != len(frozen_ids)
            or census.get("accounted_particle_count") != len(frozen_ids)
            or census.get("terminal_particle_count", -1) + census.get("unknown_terminal_count", -1) != len(frozen_ids)
            or census.get("complete") != (census.get("unknown_terminal_count") == 0)
        ):
            raise ContractError("compact handoff natural terminal census differs from frozen cohort")
        receipt["natural_terminal_census"] = census
        validate_schema(receipt, HANDOFF_RECEIPT_SCHEMA_PATH)
        _write(results / "pre_pulse_compact_handoff_receipt.json", receipt)
        config = {
            "schema_version": 2, "run_id": output_run_dir.name,
            "project": INTEGRATION_ID, "mode": MODE,
            "project_root": str(repo_root.parent),
            "inputs": {"screening_contract": str(frozen_contract), "particle_row_map": str(frozen_row_map),
                       "source_manifest": str(frozen_manifest), "source_receipt": str(frozen_receipt)},
            "parameters": {
                "selected_time_us": selection.get("pulse_effective_time_us"),
                "particle_count": target.get("particle_count"), "raw_trace_retained": False,
                "selection_method": receipt["method"],
            },
            "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None},
            "formal_gate_passed": False,
        }
        config_path = output_run_dir / "run_config.json"
        _write(config_path, config)
        summary = output_run_dir / "summary.json"
        _write(summary, {
            "schema_version": 1, "role": "rf_oatof_compact_pre_pulse_handoff_recovery_summary",
            "status": "success", "claim_status": "DETECTOR_BLIND_PRE_PULSE_HANDOFF_ONLY",
            "selected_time_us": selection.get("pulse_effective_time_us"),
            "particle_count": target.get("particle_count"), "raw_trace_retained": False,
            "natural_terminal_census": receipt["natural_terminal_census"],
            "pulse_population_partition": selection["pulse_population_partition"],
            **({"ranking": selection["ranking"]} if receipt["method"]
               == "native_trace_detector_blind_pulse_selection_v2" else {}),
        })
        manifest = output_run_dir / "run_manifest.json"
        completed = subprocess.run([
            sys.executable, "-m", "common.contracts.write_run_manifest",
            "--run-config", str(config_path), "--manifest", str(manifest),
            "--status", "success", "--software", f"Python {sys.version_info.major}.{sys.version_info.minor}",
            "--output", str(summary), "--output", str(handoff),
            "--output", str(results / "pre_pulse_compact_handoff_receipt.json"),
            "--output", str(results / "pre_pulse_compact_handoff_selection.json"),
            "--output", str(terminal_output),
        ], cwd=repo_root, capture_output=True, text=True, timeout=300)
        if completed.returncode:
            detail = (completed.stderr or completed.stdout).strip()
            raise ContractError(
                f"compact handoff manifest publication failed: {detail}"
            )
        return manifest
    except Exception:
        if output_run_dir.exists() and not (output_run_dir / "run_manifest.json").exists():
            shutil.rmtree(output_run_dir)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--source-run-dir", required=True, type=Path)
    parser.add_argument("--output-run-dir", required=True, type=Path)
    parser.add_argument("--terminal-trace-log", action="append", type=Path,
                        help="Task-retained completed TRACE log; only for a legacy receipt lacking terminal state.")
    arguments = parser.parse_args()
    manifest = publish(
        repo_root=arguments.repo_root.resolve(),
        source_run_dir=arguments.source_run_dir,
        output_run_dir=arguments.output_run_dir,
        terminal_trace_logs=arguments.terminal_trace_log,
    )
    print(f"COMPACT_PRE_PULSE_HANDOFF_PUBLISHED=PASS MANIFEST={manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
