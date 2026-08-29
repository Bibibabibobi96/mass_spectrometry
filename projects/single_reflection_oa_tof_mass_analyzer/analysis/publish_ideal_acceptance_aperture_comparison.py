"""Atomically publish one manifest-bound 300 mm aperture comparison.

The two aperture readers deliberately remain pure, fail-closed analysis
functions.  This module is their only production publisher: it binds the
campaign and every consumed arm manifest to a canonical analysis artifact,
then publishes the comparison JSON together with the standard run trio.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable

from common.contracts.artifact_naming import validate_run_id

from projects.single_reflection_oa_tof_mass_analyzer.analysis import (
    analyze_ideal_acceptance_aperture_campaign as pre_pulse,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis import (
    analyze_ideal_acceptance_aperture_full_flight as full_flight,
)


PROJECT_ID = "single_reflection_oa_tof_mass_analyzer"
PUBLISH_MODE = "analysis"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORKSPACE_ROOT = REPOSITORY_ROOT.parent
MODES: dict[str, tuple[str, str, Callable[..., dict[str, Any]]]] = {
    "pre-pulse": (
        pre_pulse.CAMPAIGN_ID,
        "ideal_acceptance_300mm_aperture_pre_pulse_comparison.json",
        pre_pulse.analyze_campaign,
    ),
    "full-flight": (
        full_flight.CAMPAIGN_ID,
        "ideal_acceptance_300mm_aperture_full_flight_comparison.json",
        full_flight.analyze_campaign,
    ),
}
MODE_CAMPAIGN_IDS: dict[str, frozenset[str]] = {
    "pre-pulse": pre_pulse.CAMPAIGN_IDS,
    "full-flight": full_flight.CAMPAIGN_IDS,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"missing {label}: {path}")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def _write_exclusive_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _resolve_record_path(record: dict[str, Any], *, base: Path, label: str) -> Path:
    value = record.get("path")
    expected_sha = record.get("sha256")
    if not isinstance(value, str) or not isinstance(expected_sha, str):
        raise ValueError(f"{label} lacks path or SHA-256")
    path = Path(value)
    resolved = (path if path.is_absolute() else base / path).resolve()
    if not resolved.is_file() or _sha256(resolved) != expected_sha.upper():
        raise ValueError(f"{label} differs from its recorded SHA-256")
    return resolved


def _collect_input_artifacts(*, campaign_path: Path, runs_root: Path, mode: str) -> dict[str, Path]:
    """Return every campaign/run receipt consumed by the selected reader.

    The reader performs the detailed physical/identity verification.  This
    second, shallow pass makes those exact receipts immutable inputs of the
    newly published analysis run instead of leaving their identities only in
    a bare result JSON.
    """

    expected_campaign_ids = MODE_CAMPAIGN_IDS[mode]
    campaign = _load_json(campaign_path, "campaign")
    if campaign.get("campaign_id") not in expected_campaign_ids:
        raise ValueError(f"campaign identity is not valid for {mode}")
    rows = campaign.get("experiments", {}).get("rows")
    if not isinstance(rows, list) or len(rows) != 8:
        raise ValueError("campaign must contain exactly eight arms")
    inputs: dict[str, Path] = {"campaign": campaign_path.resolve()}
    for index, row in enumerate(rows, start=1):
        run_id = row.get("run_id") if isinstance(row, dict) else None
        if not isinstance(run_id, str):
            raise ValueError(f"campaign arm {index} lacks run_id")
        parent_manifest = (runs_root / run_id / "run_manifest.json").resolve()
        parent = _load_json(parent_manifest, f"arm {index} run manifest")
        inputs[f"arm_{index:02d}_manifest"] = parent_manifest
        if mode == "full-flight":
            child_record = parent.get("inputs", {}).get("single_flight_transport_manifest")
            if not isinstance(child_record, dict):
                raise ValueError(f"arm {index} lacks single-flight child manifest")
            inputs[f"arm_{index:02d}_single_flight_manifest"] = _resolve_record_path(
                child_record, base=parent_manifest.parent, label=f"arm {index} child manifest"
            )
    return inputs


def _publish_manifest(*, run_dir: Path, run_config: Path, outputs: tuple[Path, ...]) -> None:
    pending = run_dir / ".run_manifest.json.pending"
    command = [
        sys.executable, "-m", "common.contracts.write_run_manifest",
        "--run-config", str(run_config), "--manifest", str(pending),
        "--status", "success", "--software", f"Python {sys.version_info.major}.{sys.version_info.minor}",
    ]
    for output in outputs:
        command.extend(("--output", str(output)))
    completed = subprocess.run(
        command, cwd=REPOSITORY_ROOT, check=False, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    if completed.returncode:
        raise RuntimeError("aperture comparison manifest publication failed: " + (completed.stdout + completed.stderr).strip())
    manifest = _load_json(pending, "pending run manifest")
    if (manifest.get("role") != "simulation_run_manifest" or manifest.get("status") != "success" or
            manifest.get("project") != PROJECT_ID or manifest.get("mode") != PUBLISH_MODE or
            manifest.get("formal_eligible") is not False):
        raise RuntimeError("aperture comparison manifest identity differs")
    published_run_id = manifest.get("run_id")
    if not isinstance(published_run_id, str):
        raise RuntimeError("aperture comparison manifest lacks run ID")
    for record in [manifest["run_config"], *manifest["inputs"].values(), *manifest["outputs"]]:
        record["path"] = os.path.relpath(Path(str(record["path"])).resolve(), run_dir).replace("\\", "/")
    pending.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verified = subprocess.run(
        [sys.executable, "-m", "common.contracts.verify_run_manifest", str(pending),
         "--require-status", "success", "--require-local-run-config", "--require-run-id", published_run_id,
         "--require-project", PROJECT_ID, "--require-mode", PUBLISH_MODE],
        cwd=REPOSITORY_ROOT, check=False, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60,
    )
    if verified.returncode:
        raise RuntimeError("aperture comparison manifest verification failed: " + (verified.stdout + verified.stderr).strip())
    os.replace(pending, run_dir / "run_manifest.json")


def publish_aperture_comparison(
    *, campaign_path: Path, runs_root: Path, run_dir: Path, mode: str,
    threshold_mm: float = 4.0, workspace_root: Path = DEFAULT_WORKSPACE_ROOT,
) -> dict[str, Any]:
    """Run one fail-closed reader and atomically publish its immutable result."""

    if mode not in MODES:
        raise ValueError(f"unsupported comparison mode: {mode}")
    workspace_root = workspace_root.resolve()
    campaign_path, runs_root, run_dir = campaign_path.resolve(), runs_root.resolve(), run_dir.resolve()
    validate_run_id(run_dir.name)
    canonical_runs = (workspace_root / "artifacts" / "projects" / PROJECT_ID / "runs").resolve()
    if run_dir.parent != canonical_runs:
        raise ValueError("analysis run_dir must use the canonical workspace artifact root")
    if run_dir.exists():
        raise FileExistsError(f"analysis run directory already exists: {run_dir}")
    inputs = _collect_input_artifacts(campaign_path=campaign_path, runs_root=runs_root, mode=mode)
    _, result_name, analyzer = MODES[mode]
    # Run the reader before creating any artifact directory: a rejected arm
    # therefore leaves no partial success-looking output behind.
    result = analyzer(campaign_path=campaign_path, runs_root=runs_root, threshold_mm=threshold_mm)
    if not isinstance(result, dict) or result.get("campaign", {}).get("sha256") != _sha256(campaign_path):
        raise RuntimeError("aperture comparison reader returned an unverifiable result")

    canonical_runs.mkdir(parents=True, exist_ok=True)
    lock_path = canonical_runs / f".{run_dir.name}.publish.lock"
    try:
        lock_path.open("x", encoding="utf-8").close()
    except FileExistsError as error:
        raise FileExistsError(f"analysis publication is already active: {run_dir}") from error
    staging: Path | None = None
    try:
        staging = Path(tempfile.mkdtemp(prefix=f".{run_dir.name}.pending-", dir=canonical_runs))
        result_path, summary_path, config_path = staging / "results" / result_name, staging / "summary.json", staging / "run_config.json"
        _write_exclusive_json(result_path, result)
        relative = lambda path: os.path.relpath(path, staging).replace("\\", "/")
        _write_exclusive_json(config_path, {
            "schema_version": 2,
            "role": "ideal_acceptance_300mm_aperture_comparison_run_config",
            "run_id": run_dir.name, "project": PROJECT_ID, "mode": PUBLISH_MODE,
            "inputs": {name: relative(path) for name, path in inputs.items()},
            "parameters": {"comparison_mode": mode, "axial_width_threshold_mm": threshold_mm},
            "formal_gate_passed": False,
            "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None},
        })
        _write_exclusive_json(summary_path, {
            "schema_version": 1, "role": "ideal_acceptance_300mm_aperture_comparison_summary",
            "status": "success", "run_id": run_dir.name, "qualification": result.get("qualification"),
            "comparison": {"path": f"results/{result_name}", "sha256": _sha256(result_path), "bytes": result_path.stat().st_size},
            "formal_gate_passed": False,
        })
        _publish_manifest(run_dir=staging, run_config=config_path, outputs=(result_path, summary_path))
        if run_dir.exists():
            raise FileExistsError(f"analysis run directory already exists: {run_dir}")
        staging.rename(run_dir)
    except BaseException:
        if staging is not None and staging.exists():
            shutil.rmtree(staging)
        raise
    finally:
        lock_path.unlink(missing_ok=True)
    return _load_json(run_dir / "summary.json", "published analysis summary")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--runs-root", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--mode", choices=tuple(MODES), required=True)
    parser.add_argument("--axial-width-threshold-mm", type=float, default=4.0)
    parser.add_argument("--workspace-root", type=Path, default=DEFAULT_WORKSPACE_ROOT)
    args = parser.parse_args()
    summary = publish_aperture_comparison(
        campaign_path=args.campaign, runs_root=args.runs_root, run_dir=args.run_dir,
        mode=args.mode, threshold_mm=args.axial_width_threshold_mm, workspace_root=args.workspace_root,
    )
    print(f"APERTURE_COMPARISON_PUBLISH=PASS MODE={args.mode} RUN_ID={summary['run_id']}")


if __name__ == "__main__":
    main()
