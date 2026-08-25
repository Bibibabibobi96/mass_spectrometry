"""Atomically publish the five frozen C3-J3 real-field Candidate inputs.

The publisher is deliberately not an optimiser.  It consumes the already
passing C2-J3 direction, maps all five finite-difference points exactly, and
places the resulting family and candidate inputs in one immutable Candidate
run.  Downstream SIMION runs can therefore bind a particular point by hash
without regenerating it or consulting detector data.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence

from common.contracts.artifact_naming import validate_run_id
from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import load_json
from projects.single_reflection_oa_tof_mass_analyzer.analysis.paper1_c3_j3_mapping import (
    compile_c2_j3_physical_control_family,
    compile_c3_j3_variant_candidate,
)


PROJECT_ID = "single_reflection_oa_tof_mass_analyzer"
PUBLISH_MODE = "paper1_c3_j3_candidate_compile"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORKSPACE_ROOT = REPOSITORY_ROOT.parent
SCALES: tuple[int, ...] = (-2, -1, 0, 1, 2)


def _workspace_relative(path: Path, workspace_root: Path, *, label: str) -> str:
    try:
        return path.resolve().relative_to(workspace_root.resolve()).as_posix()
    except ValueError as error:
        raise ValueError(f"{label} must be inside the workspace") from error


def _write_exclusive_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")


def _publish_manifest(*, run_dir: Path, run_config: Path, outputs: Sequence[Path]) -> None:
    pending = run_dir / ".run_manifest.json.pending"
    command = [
        sys.executable, "-m", "common.contracts.write_run_manifest",
        "--run-config", str(run_config), "--manifest", str(pending),
        "--status", "success", "--software", f"Python {sys.version_info.major}.{sys.version_info.minor}",
    ]
    for output in outputs:
        command.extend(("--output", str(output)))
    completed = subprocess.run(
        command, cwd=REPOSITORY_ROOT, check=False, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError("C3-J3 Candidate manifest publication failed: " + (completed.stdout + completed.stderr).strip())
    manifest = load_json(pending)
    if (
        manifest.get("role") != "simulation_run_manifest"
        or manifest.get("status") != "success"
        or manifest.get("project") != PROJECT_ID
        or manifest.get("mode") != PUBLISH_MODE
        or manifest.get("formal_eligible") is not False
    ):
        raise RuntimeError("C3-J3 Candidate manifest identity differs")
    records = [manifest["run_config"], *manifest["inputs"].values(), *manifest["outputs"]]
    for record in records:
        record["path"] = os.path.relpath(Path(str(record["path"])).resolve(), run_dir).replace("\\", "/")
    pending.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    verified = subprocess.run(
        [
            sys.executable, "-m", "common.contracts.verify_run_manifest", str(pending),
            "--require-status", "success", "--require-local-run-config",
            "--require-run-id", str(manifest["run_id"]), "--require-project", PROJECT_ID,
            "--require-mode", PUBLISH_MODE,
        ],
        cwd=REPOSITORY_ROOT, check=False, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60,
    )
    if verified.returncode != 0:
        raise RuntimeError("C3-J3 Candidate manifest verification failed: " + (verified.stdout + verified.stderr).strip())
    os.replace(pending, run_dir / "run_manifest.json")


def _portable_family(family: Mapping[str, Any], workspace_root: Path) -> dict[str, Any]:
    result = copy.deepcopy(family)
    for label, record in (("campaign", result["campaign"]), ("C2-J3 result", result["c2_j3_result"]), ("base Candidate", result["base_candidate"])):
        record["path"] = _workspace_relative(Path(str(record["path"])), workspace_root, label=label)
    return result


def publish_c3_j3_candidates(
    *, campaign_path: Path, c2_result_path: Path, source_id: str,
    base_candidate_path: Path, run_dir: Path,
    workspace_root: Path = DEFAULT_WORKSPACE_ROOT,
) -> dict[str, Any]:
    """Publish one hash-bound five-point C3-J3 Candidate family atomically."""

    workspace_root = workspace_root.resolve()
    campaign_path, c2_result_path = campaign_path.resolve(), c2_result_path.resolve()
    base_candidate_path, run_dir = base_candidate_path.resolve(), run_dir.resolve()
    validate_run_id(run_dir.name)
    canonical_runs = (workspace_root / "artifacts" / "projects" / PROJECT_ID / "runs").resolve()
    if run_dir.parent != canonical_runs:
        raise ValueError("C3-J3 Candidate run_dir must use the canonical workspace artifact root")
    if run_dir.exists():
        raise FileExistsError(f"C3-J3 Candidate run directory already exists: {run_dir}")
    for label, path in (("campaign", campaign_path), ("C2-J3 result", c2_result_path), ("base Candidate", base_candidate_path)):
        if not path.is_file():
            raise FileNotFoundError(f"C3-J3 {label} is missing: {path}")
        _workspace_relative(path, workspace_root, label=label)
    code_sources = {
        "publisher_source": Path(__file__).resolve(),
        "mapping_source": REPOSITORY_ROOT / "projects/single_reflection_oa_tof_mass_analyzer/analysis/paper1_c3_j3_mapping.py",
        "candidate_schema": REPOSITORY_ROOT / "common/contracts/schemas/oatof_three_zone_simion_candidate_resolved.schema.json",
    }
    for label, path in code_sources.items():
        _workspace_relative(path, workspace_root, label=label)
    canonical_runs.mkdir(parents=True, exist_ok=True)
    lock_path = canonical_runs / f".{run_dir.name}.publish.lock"
    try:
        lock_path.open("x", encoding="utf-8").close()
    except FileExistsError as error:
        raise FileExistsError(f"C3-J3 Candidate publication is already active: {run_dir}") from error
    staging: Path | None = None
    try:
        staging = Path(tempfile.mkdtemp(prefix=f".{run_dir.name}.pending-", dir=canonical_runs))
        raw_family = compile_c2_j3_physical_control_family(
            campaign_path=campaign_path, c2_result_path=c2_result_path,
            source_id=source_id, candidate_path=base_candidate_path,
        )
        family = _portable_family(raw_family, workspace_root)
        family_path = staging / "results" / "c3_j3_physical_control_family.json"
        _write_exclusive_json(family_path, family)
        candidates: dict[str, Path] = {}
        family_record = {
            "path": _workspace_relative(run_dir / "results" / family_path.name, workspace_root, label="published physical family"),
            "bytes": family_path.stat().st_size,
            "sha256": file_sha256(family_path),
        }
        for scale in SCALES:
            candidate = compile_c3_j3_variant_candidate(
                base_candidate_path=base_candidate_path, physical_family_path=family_path, scale_h=float(scale),
            )
            candidate["c3_j3_evidence"]["physical_family"] = family_record
            output = staging / "results" / f"three_zone_c3_j3_scale_{scale:+d}_candidate_resolved.json"
            _write_exclusive_json(output, candidate)
            candidates[str(scale)] = output
        summary_path, run_config_path = staging / "summary.json", staging / "run_config.json"
        relative = lambda path: os.path.relpath(path, staging).replace("\\", "/")
        _write_exclusive_json(run_config_path, {
            "schema_version": 1, "role": "oatof_paper1_c3_j3_candidate_run_config",
            "run_id": run_dir.name, "project": PROJECT_ID, "mode": PUBLISH_MODE,
            "inputs": {
                "campaign": relative(campaign_path), "c2_j3_result": relative(c2_result_path),
                "base_candidate": relative(base_candidate_path),
                **{name: relative(path) for name, path in code_sources.items()},
            },
            "parameters": {"source_id": source_id, "scales_h": list(SCALES), "qualification": "CANDIDATE_ONLY"},
            "formal_gate_passed": False,
        })
        _write_exclusive_json(summary_path, {
            "schema_version": 1, "role": "oatof_paper1_c3_j3_candidate_summary", "status": "success",
            "run_id": run_dir.name, "source_id": source_id, "qualification": "CANDIDATE_ONLY",
            "physical_family": {"path": f"results/{family_path.name}", "bytes": family_path.stat().st_size, "sha256": file_sha256(family_path)},
            "candidates": {scale: {"path": str(path.relative_to(staging)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": file_sha256(path)} for scale, path in candidates.items()},
            "claim_limit": "Frozen C3-J3 Candidate inputs only; no PA, SIMION, derivative, peak-width, transmission, or Formal result.",
            "formal_gate_passed": False,
        })
        _publish_manifest(run_dir=staging, run_config=run_config_path, outputs=(family_path, *candidates.values(), summary_path))
        staging.rename(run_dir)
    except BaseException:
        if staging is not None and staging.exists():
            shutil.rmtree(staging)
        raise
    finally:
        lock_path.unlink(missing_ok=True)
    return load_json(run_dir / "summary.json")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--c2-j3-result", required=True, type=Path)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--base-candidate", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--workspace-root", type=Path, default=DEFAULT_WORKSPACE_ROOT)
    arguments = parser.parse_args(argv)
    publish_c3_j3_candidates(
        campaign_path=arguments.campaign, c2_result_path=arguments.c2_j3_result,
        source_id=arguments.source_id, base_candidate_path=arguments.base_candidate,
        run_dir=arguments.run_dir, workspace_root=arguments.workspace_root,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
