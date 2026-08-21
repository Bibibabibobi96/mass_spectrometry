"""Finalize completed one-wave SIMION batches without launching a solver.

This generic recovery entry point is deliberately limited to immutable batch
artifacts.  It verifies their parent-manifest identities and local SIMION IDs,
then creates a distinct child run containing canonical merged outputs and a
provenance receipt.  It never modifies the parent run and never invokes SIMION.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.particle_state import canonical_sources, validate_particle_state
from common.contracts.write_run_manifest import main as write_manifest_main
from common.simion.particle_batching import merge_rebased_particle_csvs, merge_simion_summaries


def _document(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _record(path: Path) -> dict[str, Any]:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": file_sha256(path)}


def _require_parent_record(parent_manifest: dict[str, Any], path: Path) -> dict[str, Any]:
    wanted = str(path.resolve())
    matches = [item for item in parent_manifest.get("outputs", []) if item.get("path") == wanted]
    if len(matches) != 1:
        raise ValueError(f"parent manifest does not uniquely record raw output: {path}")
    record = matches[0]
    if not record.get("exists") or record.get("sha256") != file_sha256(path):
        raise ValueError(f"raw output hash differs from parent manifest: {path}")
    return _record(path)


def _require_parent_input(parent_manifest: dict[str, Any], role: str, path: Path) -> dict[str, Any]:
    """Verify an immutable parent input before freezing it into a child run."""
    record = parent_manifest.get("inputs", {}).get(role, {})
    if str(path.resolve()) != record.get("path") or not record.get("exists"):
        raise ValueError(f"parent manifest input identity differs: {role}")
    if record.get("sha256") != file_sha256(path):
        raise ValueError(f"parent manifest input hash differs: {role}")
    return _record(path)


def _validate_plan(plan: dict[str, Any]) -> list[dict[str, int]]:
    if (plan.get("role") != "simion_single_wave_particle_batch_plan"
            or plan.get("dispatch") != "single_wave_parallel"):
        raise ValueError("unsupported batch plan role or dispatch")
    count = plan.get("particle_count")
    batches = plan.get("batches")
    if not isinstance(count, int) or count < 1 or not isinstance(batches, list) or not batches:
        raise ValueError("invalid batch plan population")
    cursor = 1
    normalized: list[dict[str, int]] = []
    for expected_index, item in enumerate(batches, start=1):
        try:
            batch = {name: int(item[name]) for name in (
                "index", "count", "particle_id_min", "particle_id_max", "simion_particle_id_offset"
            )}
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("batch plan has malformed batch") from error
        if (batch["index"] != expected_index or batch["particle_id_min"] != cursor
                or batch["particle_id_max"] - batch["particle_id_min"] + 1 != batch["count"]
                or batch["simion_particle_id_offset"] != cursor - 1):
            raise ValueError("batch plan intervals or offsets are not canonical")
        cursor = batch["particle_id_max"] + 1
        normalized.append(batch)
    if cursor - 1 != count or plan.get("batch_count") != len(normalized):
        raise ValueError("batch plan does not cover its declared population")
    return normalized


def _validate_local_ids(path: Path, expected_count: int) -> None:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or reader.fieldnames[0] != "particle_id":
            raise ValueError(f"raw state lacks leading particle_id column: {path}")
        ids: set[int] = set()
        for row in reader:
            try:
                local_id = int(row["particle_id"])
            except (KeyError, ValueError) as error:
                raise ValueError(f"raw state has invalid local particle ID: {path}") from error
            ids.add(local_id)
    if ids != set(range(1, expected_count + 1)):
        raise ValueError(f"raw state local IDs do not exactly cover 1..{expected_count}: {path}")


def finalize_completed_batches(
    parent_run: Path, recovery_run: Path, case_name: str, particle_source: Path,
    frequency_hz: float, phase_rad: float, rod_exit_mm: float, handoff_mm: float,
) -> Path:
    """Validate immutable completed batches and publish a recovery child run."""
    parent_run = parent_run.resolve()
    recovery_run = recovery_run.resolve()
    if parent_run == recovery_run or recovery_run.exists():
        raise ValueError("recovery run must be a new directory distinct from its parent")
    parent_manifest_path = parent_run / "run_manifest.json"
    parent_config_path = parent_run / "run_config.json"
    parent_manifest = _document(parent_manifest_path)
    parent_config = _document(parent_config_path)
    if parent_manifest.get("status") == "success":
        raise ValueError("a successful parent does not require finalize-only recovery")
    plan_path = Path(parent_config["inputs"]["simion_execution_batch_plan"]).resolve()
    plan = _document(plan_path)
    batches = _validate_plan(plan)
    if file_sha256(plan_path) != parent_manifest["inputs"]["simion_execution_batch_plan"]["sha256"]:
        raise ValueError("batch plan hash differs from parent manifest")
    source = particle_source.resolve()
    _require_parent_input(parent_manifest, "particle_source", source)
    metadata = Path(parent_config["inputs"]["particle_source_metadata"]).resolve()
    _require_parent_input(parent_manifest, "particle_source_metadata", metadata)
    resolved_design = Path(parent_config["inputs"]["multipole_resolved_design"]).resolve()
    _require_parent_input(parent_manifest, "multipole_resolved_design", resolved_design)
    if set(canonical_sources(source)) != set(range(1, plan["particle_count"] + 1)):
        raise ValueError("particle source IDs differ from the batch plan population")

    results = parent_run / "results"
    states: list[tuple[Path, int]] = []
    summaries: list[Path] = []
    raw_records: list[dict[str, Any]] = []
    for batch in batches:
        suffix = f"batch_{batch['index']:02d}"
        state = results / f"particle_states__{case_name}__{suffix}.csv"
        summary = results / f"simion_summary__{case_name}__{suffix}.json"
        if not state.is_file() or not summary.is_file():
            raise ValueError(f"completed raw batch artifacts are missing: {suffix}")
        raw_records.extend((_require_parent_record(parent_manifest, state), _require_parent_record(parent_manifest, summary)))
        _validate_local_ids(state, batch["count"])
        document = _document(summary)
        if document.get("particles") != batch["count"]:
            raise ValueError(f"batch summary population differs from plan: {summary}")
        states.append((state, batch["simion_particle_id_offset"]))
        summaries.append(summary)

    recovery_results = recovery_run / "results"
    recovery_results.mkdir(parents=True)
    recovery_inputs = recovery_run / "inputs"
    recovery_inputs.mkdir()
    frozen_source = recovery_inputs / "particle_source.csv"
    frozen_metadata = recovery_inputs / "particle_source_metadata.json"
    frozen_resolved_design = recovery_inputs / "multipole_resolved_design.json"
    shutil.copyfile(source, frozen_source)
    shutil.copyfile(metadata, frozen_metadata)
    shutil.copyfile(resolved_design, frozen_resolved_design)
    if (file_sha256(frozen_source) != file_sha256(source)
            or file_sha256(frozen_metadata) != file_sha256(metadata)
            or file_sha256(frozen_resolved_design) != file_sha256(resolved_design)):
        raise AssertionError("frozen recovery source bytes differ from parent")
    merged_state = recovery_results / f"particle_states__{case_name}.csv"
    merged_summary = recovery_results / f"simion_summary__{case_name}.json"
    merge_rebased_particle_csvs(states, merged_state)
    merge_simion_summaries(summaries, plan, merged_summary)
    report = validate_particle_state(
        merged_state, canonical_sources(source), frequency_hz, phase_rad, rod_exit_mm, handoff_mm
    )
    report.update(solver="SIMION", recovery_mode="finalize_completed_batches")
    report_path = recovery_results / f"particle_state_contract__{case_name}.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    receipt = {
        "schema_version": 1,
        "role": "simion_completed_batch_finalize_receipt",
        "action": "finalize_only_no_solver_launch",
        "parent_run": {"path": str(parent_run), "run_id": parent_manifest.get("run_id"),
                       "manifest": _record(parent_manifest_path), "run_config": _record(parent_config_path)},
        "batch_plan": _record(plan_path), "raw_batch_artifacts": raw_records,
        "frozen_source": {"parent_particle_source": _record(source),
                          "parent_particle_source_metadata": _record(metadata),
                          "parent_resolved_design": _record(resolved_design),
                          "child_particle_source": _record(frozen_source),
                          "child_particle_source_metadata": _record(frozen_metadata),
                          "child_resolved_design": _record(frozen_resolved_design)},
        "validated": {"batch_count": len(batches), "particle_count": plan["particle_count"],
                      "local_ids": "exact_1_to_batch_count", "state_contract": "PASS"},
    }
    receipt_path = recovery_run / "finalize_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    recovery_config = {
        "schema_version": 1, "role": "simion_finalize_only_recovery_run_config",
        "run_id": recovery_run.name, "project": parent_config.get("project"),
        "mode": "finalize_completed_batches_recovery", "formal_gate_passed": False,
        "provenance": {"parent_run_id": parent_manifest.get("run_id"), "parent_manifest_sha256": file_sha256(parent_manifest_path)},
        "parameters": {"design_profile_id": parent_config.get("parameters", {}).get("design_profile_id")},
        "inputs": {"parent_manifest": str(parent_manifest_path), "parent_run_config": str(parent_config_path),
                   "batch_plan": str(plan_path), "particle_source": str(frozen_source),
                   "particle_source_metadata": str(frozen_metadata),
                   "multipole_resolved_design": str(frozen_resolved_design),
                   "finalize_receipt": str(receipt_path)},
    }
    config_path = recovery_run / "run_config.json"
    config_path.write_text(json.dumps(recovery_config, indent=2) + "\n", encoding="utf-8")
    old_argv = sys.argv
    try:
        sys.argv = ["write_run_manifest", "--run-config", str(config_path), "--status", "success",
                    "--output", str(merged_state), "--output", str(merged_summary), "--output", str(report_path),
                    "--output", str(receipt_path)]
        for software in parent_manifest.get("software", []):
            if isinstance(software, str) and software:
                sys.argv.extend(("--software", software))
        write_manifest_main()
    finally:
        sys.argv = old_argv
    return recovery_run / "run_manifest.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-run", required=True, type=Path)
    parser.add_argument("--recovery-run", required=True, type=Path)
    parser.add_argument("--case-name", required=True)
    parser.add_argument("--particle-source", required=True, type=Path)
    parser.add_argument("--frequency-hz", required=True, type=float)
    parser.add_argument("--phase-rad", required=True, type=float)
    parser.add_argument("--rod-exit-mm", required=True, type=float)
    parser.add_argument("--handoff-mm", required=True, type=float)
    args = parser.parse_args()
    manifest = finalize_completed_batches(**vars(args))
    print(f"SIMION_FINALIZE_ONLY_RECOVERY=PASS MANIFEST={manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
