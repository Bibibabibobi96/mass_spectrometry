"""Admit one sealed completed native flight for the existing joint analyzer.

This internal stage freezes only the new author contract and source manifest.
The original preparation, merge receipt and logs remain at their producer paths;
the scientific analyzer owns their full content and per-particle state verification.
"""
from __future__ import annotations

import argparse
from functools import partial
import json
from pathlib import Path

from msplatform.contracts.trajectory_recording import resolve_trajectory_recording
from msplatform.execution.native_source_guard import guard_historical_measured_flight
from msplatform.execution.retention import classify_file
from msplatform.io.manifest_records import (
    file_record,
    record_path,
    require_completed_terminal_publication,
    verify_record as _verify_record,
)
from msplatform.results.historical_joint_source import validate_joint_run_identity, validate_joint_recorded_evidence

verify_record = partial(_verify_record, retention_classifier=classify_file)


def prepare_analysis_inputs(source_run: Path, contract: Path, output_inputs: Path) -> dict:
    """Select published native-completion evidence and freeze small analysis inputs."""
    source_run = source_run.resolve()
    manifest_path = source_run / "run_manifest.json"
    require_completed_terminal_publication(manifest_path)
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8-sig"))
    config_record = manifest["run_config"]
    if record_path(config_record, base_dir=source_run) != source_run / "run_config.json":
        raise ValueError("Analysis source manifest does not bind its own run_config")
    verify_record("source run_config", config_record, base_dir=source_run)
    config = json.loads((source_run / "run_config.json").read_text(encoding="utf-8-sig"))
    validate_joint_run_identity(manifest, config, run_id=source_run.name)
    manifest_record = file_record(manifest_path, "required_evidence")
    with guard_historical_measured_flight(manifest_record) as historical:
        manifest = historical.manifest
        config = historical.config
        manifest_bytes = manifest_path.read_bytes()
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
        preparation_path = source_run / "results/prepared_joint_trial.json"
        merge_path = source_run / "results/batch_log_merge_receipt.json"
        prepared = read_evidence(preparation_path)
        merge = read_evidence(merge_path)
        validate_joint_recorded_evidence(manifest, config, summary, prepared, merge, run_id=source_run.name)

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
        if contract.resolve() != frozen_contract.resolve():
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
