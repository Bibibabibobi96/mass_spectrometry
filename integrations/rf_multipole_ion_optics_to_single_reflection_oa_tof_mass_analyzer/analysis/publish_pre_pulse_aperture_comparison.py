"""Publish an immutable detector-blind comparison of pre-pulse aperture runs."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from common.contracts.artifact_naming import validate_run_id
from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.compare_single_flight_apertures import (
    analyze_pre_pulse_source_only_apertures,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.run_publication import (
    freeze_repository_inputs,
    portable_path,
    publish_manifest,
    write_pending_json,
)


INTEGRATION_ID = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
MODE = "rf_oatof_pre_pulse_aperture_comparison"
RESULT_ROLE = "rf_oatof_pre_pulse_aperture_comparison"
SUMMARY_ROLE = "rf_oatof_pre_pulse_aperture_comparison_summary"
IMPLEMENTATION_RELATIVE_PATH = (
    "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
    "analysis/publish_pre_pulse_aperture_comparison.py"
)
COMPARISON_IMPLEMENTATION_RELATIVE_PATH = (
    "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
    "analysis/compare_single_flight_apertures.py"
)
SOURCE_FILES = (
    "run_manifest.json",
    "run_config.json",
    "inputs/single_flight_initial_global_state.csv",
    "results/pre_pulse_time_series_states.csv",
    "results/pre_pulse_time_series_screening_receipt.json",
)


def _validated_cases(
    cases: Mapping[str, Path], *, workspace_root: Path
) -> dict[str, Path]:
    if len(cases) < 2:
        raise ContractError("pre-pulse aperture publication requires at least two cases")
    normalized: dict[str, Path] = {}
    for case_id, path in cases.items():
        if not isinstance(case_id, str) or not case_id.strip() or case_id != case_id.strip():
            raise ContractError("pre-pulse aperture case ID is invalid")
        if case_id in normalized:
            raise ContractError("pre-pulse aperture case IDs must be unique")
        run = Path(path).resolve()
        if not run.is_dir() or not run.is_relative_to(workspace_root):
            raise ContractError(f"{case_id} source run is missing or outside workspace")
        missing = [name for name in SOURCE_FILES if not (run / name).is_file()]
        if missing:
            raise ContractError(f"{case_id} source run is missing required input: {missing[0]}")
        normalized[case_id] = run
    return normalized


def _source_reference(case_id: str, run: Path) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "run_path": str(run),
        "files": {
            name: {"path": str(run / name), "sha256": file_sha256(run / name)}
            for name in SOURCE_FILES
        },
    }


def publish_pre_pulse_aperture_comparison(
    *, repo_root: Path, run_id: str, cases: Mapping[str, Path]
) -> Path:
    """Freeze source provenance and publish a detector-blind aperture comparison."""

    repo_root = repo_root.resolve()
    workspace_root = repo_root.parent.resolve()
    try:
        validate_run_id(run_id)
    except ValueError as error:
        raise ContractError("pre-pulse aperture comparison run_id is invalid") from error
    normalized_cases = _validated_cases(cases, workspace_root=workspace_root)
    result = analyze_pre_pulse_source_only_apertures(normalized_cases)
    if result.get("status") != "DETECTOR_BLIND_SOURCE_ONLY" or result.get("role") != RESULT_ROLE:
        raise ContractError("pre-pulse aperture comparison result identity differs")

    runs_root = workspace_root / "artifacts" / "projects" / INTEGRATION_ID / "runs"
    run_dir = (runs_root / run_id).resolve()
    if run_dir.parent != runs_root.resolve() or run_dir.exists():
        raise ContractError("pre-pulse aperture comparison output already exists or is invalid")
    implementation = repo_root / IMPLEMENTATION_RELATIVE_PATH
    comparison_implementation = repo_root / COMPARISON_IMPLEMENTATION_RELATIVE_PATH
    if not implementation.is_file() or not comparison_implementation.is_file():
        raise ContractError("pre-pulse aperture comparison implementation is missing")

    run_dir.mkdir(parents=True, exist_ok=False)
    result_path = run_dir / "results" / "pre_pulse_aperture_comparison.json"
    request_path = run_dir / "inputs" / "pre_pulse_aperture_comparison_request.json"
    run_config_path = run_dir / "run_config.json"
    summary_path = run_dir / "summary.json"
    manifest_path = run_dir / "run_manifest.json"
    request = {
        "schema_version": 1,
        "role": "rf_oatof_pre_pulse_aperture_comparison_request",
        "integration_id": INTEGRATION_ID,
        "analysis_scope": "DETECTOR_BLIND_SOURCE_ONLY",
        "cases": [_source_reference(case_id, run) for case_id, run in sorted(normalized_cases.items())],
    }
    write_pending_json(request_path, request)
    input_paths: dict[str, Path] = {
        "comparison_request": request_path,
        "publication_implementation": implementation,
        "comparison_implementation": comparison_implementation,
    }
    for index, (_, run) in enumerate(sorted(normalized_cases.items()), start=1):
        for name in SOURCE_FILES:
            input_paths[f"case_{index}_{name.replace('/', '_').replace('.', '_')}"] = run / name
    frozen = freeze_repository_inputs(input_paths, repo_root=repo_root, run_dir=run_dir)
    run_config = {
        "schema_version": 2,
        "run_id": run_id,
        "project": INTEGRATION_ID,
        "mode": MODE,
        "project_root": str(workspace_root),
        "inputs": {name: portable_path(path, workspace_root) for name, path in sorted(frozen.items())},
        "parameters": {
            "case_ids": sorted(normalized_cases),
            "case_count": len(normalized_cases),
            "analysis_scope": "DETECTOR_BLIND_SOURCE_ONLY",
            "resolution_claim_allowed": False,
            "formal_gate_passed": False,
        },
        "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None},
        "formal_gate_passed": False,
    }
    write_pending_json(run_config_path, run_config)
    write_pending_json(
        summary_path,
        {
            "schema_version": 1,
            "role": SUMMARY_ROLE,
            "status": "interrupted",
            "analysis_status": "NOT_RUN",
            "analysis_scope": "DETECTOR_BLIND_SOURCE_ONLY",
            "formal_gate_passed": False,
        },
    )
    pending_manifest = manifest_path.with_name(".run_manifest.json.pending")
    publish_manifest(
        repo_root=repo_root, run_config=run_config_path, manifest_path=pending_manifest,
        status="interrupted", outputs=(summary_path,), project=INTEGRATION_ID,
        mode=MODE, label="pre-pulse-aperture-comparison",
    )
    os.replace(pending_manifest, manifest_path)
    write_pending_json(result_path, result)
    write_pending_json(
        summary_path,
        {
            "schema_version": 1,
            "role": SUMMARY_ROLE,
            "status": "success",
            "analysis_status": "DETECTOR_BLIND_SOURCE_ONLY",
            "analysis_scope": "DETECTOR_BLIND_SOURCE_ONLY",
            "case_count": len(normalized_cases),
            "result": "results/pre_pulse_aperture_comparison.json",
            "formal_gate_passed": False,
        },
    )
    publish_manifest(
        repo_root=repo_root, run_config=run_config_path, manifest_path=pending_manifest,
        status="success", outputs=(result_path, summary_path), project=INTEGRATION_ID,
        mode=MODE, label="pre-pulse-aperture-comparison",
    )
    os.replace(pending_manifest, manifest_path)
    return manifest_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--case", action="append", nargs=2, metavar=("CASE_ID", "RUN_PATH"), required=True)
    args = parser.parse_args(argv)
    parsed_cases: dict[str, Path] = {}
    for case_id, run_path in args.case:
        if case_id in parsed_cases:
            raise ContractError("pre-pulse aperture case IDs must be unique")
        parsed_cases[case_id] = Path(run_path)
    manifest = publish_pre_pulse_aperture_comparison(
        repo_root=args.repo_root, run_id=args.run_id, cases=parsed_cases
    )
    print(f"PRE_PULSE_APERTURE_COMPARISON=PASS STATUS=DETECTOR_BLIND_SOURCE_ONLY MANIFEST={manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
