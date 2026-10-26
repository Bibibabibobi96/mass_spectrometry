"""Admit one sealed completed native flight for the existing joint analyzer.

This internal stage freezes only the new author contract and source manifest.
The original preparation, merge receipt and logs remain at their producer paths;
the scientific analyzer owns their full content and native-state verification.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common.contracts.capacity_ledger import load_capacity_ledger
from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import require_completed_terminal_publication
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial import resolve_trajectory_recording


def prepare_analysis_inputs(source_run: Path, contract: Path, output_inputs: Path) -> dict:
    """Select published native-completion evidence and freeze small analysis inputs."""
    source_run = source_run.resolve()
    manifest_path = source_run / "run_manifest.json"
    require_completed_terminal_publication(manifest_path)
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8-sig"))
    if (manifest.get("project"), manifest.get("mode")) != ("instrument_assembly", "prepared_joint"):
        raise ValueError("Analysis source requires instrument_assembly/prepared_joint")
    if manifest.get("status") not in {"success", "failed"}:
        raise ValueError("Analysis source requires a terminal native flight")
    config_record = manifest["run_config"]
    if record_path(config_record, base_dir=source_run) != source_run / "run_config.json":
        raise ValueError("Analysis source manifest does not bind its own run_config")
    verify_record("source run_config", config_record, base_dir=source_run)
    config = json.loads((source_run / "run_config.json").read_text(encoding="utf-8-sig"))
    if (config.get("project"), config.get("mode"), config.get("run_id")) != (
        "instrument_assembly", "prepared_joint", source_run.name
    ) or manifest.get("run_id") != source_run.name:
        raise ValueError("Analysis source run identity differs from its manifest")
    artifact_root = Path(config["capacity_ledger_lifecycle"]["artifact_root"]).resolve()
    ledger = load_capacity_ledger(artifact_root)
    relative = source_run.relative_to(artifact_root).as_posix()
    entry = next((item for item in (ledger or {}).get("objects", []) if item["path"] == relative), None)
    if entry is None or entry.get("owner") != "instrument_assembly" or entry.get("status") != "ready" or "disposition" in entry:
        raise ValueError("Analysis source must be sealed ready in its owner's capacity ledger")
    records = [*manifest.get("inputs", {}).values(), *manifest.get("outputs", [])]

    def published(path: Path) -> dict:
        matches = [record for record in records if record_path(record, base_dir=source_run) == path]
        identities = {(record.get("bytes"), record.get("sha256")) for record in matches}
        if not matches or len(identities) != 1 or not all(record.get("exists") for record in matches):
            raise ValueError(f"Analysis source path is not unambiguously manifest-bound: {path}")
        return matches[0]

    def read_evidence(path: Path) -> dict:
        verify_record(str(path), published(path), base_dir=source_run)
        return json.loads(path.read_text(encoding="utf-8-sig"))

    summary = read_evidence(source_run / "summary.json")
    if summary.get("status") != manifest["status"] or (
        manifest["status"] == "failed" and summary.get("failure_stage") != "automatic_joint_diagnostics"
    ):
        raise ValueError("Analysis source failed before automatic joint diagnostics")
    preparation_path = source_run / "results/prepared_joint_trial.json"
    merge_path = source_run / "results/batch_log_merge_receipt.json"
    prepared = read_evidence(preparation_path)
    merge = read_evidence(merge_path)
    if prepared.get("role") != "mrtof_prepared_joint_trial" or prepared.get("source_mode") != "measured_population":
        raise ValueError("Analysis requires the original measured-population preparation")
    expected = prepared["expected_particle_ids"]
    if (merge.get("schema_version") != 1 or merge.get("role") != "mrtof_measured_batch_log_merge"
            or merge.get("status") != "success" or merge.get("all_batch_losses_retained") is not True
            or merge.get("id_rebasing_applied") is not False or merge.get("original_particle_ids") != expected
            or merge.get("particle_count") != prepared["launched_particle_count"]
            or merge.get("mother_particle_count") != prepared["mother_particle_count"]
            or merge.get("solver_epoch_instrument_time_us") != prepared["solver_epoch_instrument_time_us"]
            or not merge.get("batches")):
        raise ValueError("Analysis source lacks a complete original-ID native merge")

    def bind_merge_record(record: dict, expected_path: Path | None = None) -> Path:
        path = record_path(record, base_dir=merge_path.parent)
        declared = published(path)
        if (expected_path is not None and path != expected_path) or any(
            record.get(key) != declared.get(key) for key in ("bytes", "sha256")
        ):
            raise ValueError(f"Native merge identity differs from source manifest: {path}")
        return path

    bind_merge_record(merge["preparation"], preparation_path)
    log = bind_merge_record(merge["merged_log"])
    for batch in merge["batches"]:
        for key in ("log", "batch_receipt", "fly2"):
            bind_merge_record(batch[key])
    # The merger already verified terminal per-ion census and completed native
    # batches. Its sealed receipt is admission evidence; analyze-joint verifies
    # the actual log, batch receipts and launched states once at consumption.
    contract_bytes = contract.read_bytes()
    recording = resolve_trajectory_recording(json.loads(contract_bytes.decode("utf-8-sig")))
    if recording is None:
        raise ValueError("Joint analysis requires the original retained-observation budget")
    output_inputs.mkdir(parents=True, exist_ok=True)
    frozen_manifest = output_inputs / "source_run_manifest.json"
    frozen_contract = output_inputs / "analysis_contract.json"
    frozen_manifest.write_bytes(manifest_bytes)
    frozen_contract.write_bytes(contract_bytes)
    result = dict(
        schema_version=1, role="prepared_joint_analysis_inputs", source_run=str(source_run),
        preparation=str(preparation_path), merged_log=str(log), merge_receipt=str(merge_path),
        source_manifest=str(frozen_manifest), analysis_contract=str(frozen_contract),
        recording=recording,
        mother_particle_count=prepared["mother_particle_count"], launched_particle_count=prepared["launched_particle_count"],
        protected_paths=[str(source_run), *prepared["protected_paths"]],
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output-inputs", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare_analysis_inputs(args.source_run, args.contract, args.output_inputs)))


if __name__ == "__main__":
    main()
