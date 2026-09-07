"""Publish one manifest-bound post-pulse campaign from frozen handoff evidence."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from common.contracts.artifact_naming import validate_run_id
from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.derive_post_pulse_successor import (
    derive_campaign,
)


INTEGRATION_ID = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
MODE = "rf_oatof_derived_post_pulse_campaign"


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")


def publish(*, repo_root: Path, parent_manifest: Path, compact_receipt: Path | None = None,
            materialization_manifest: Path | None = None,
            output_run_dir: Path, execution_mode: str = "particle_flight") -> Path:
    """Derive and manifest one post-pulse campaign without copying its handoff."""

    parent_manifest = parent_manifest.resolve()
    if (compact_receipt is None) == (materialization_manifest is None):
        raise ContractError("supply exactly one restart evidence path")
    evidence = (compact_receipt or materialization_manifest).resolve()
    evidence_role = "compact_receipt" if compact_receipt is not None else "materialization_manifest"
    output_run_dir = output_run_dir.resolve()
    identity = validate_run_id(output_run_dir.name)
    if identity["activity"] != "analysis" or identity["scope"] != "python":
        raise ContractError("derived post-pulse run ID must be analysis/python")
    if output_run_dir.exists():
        raise ContractError("derived post-pulse output already exists")
    if not parent_manifest.is_file() or not evidence.is_file():
        raise ContractError("derived post-pulse authority is missing")
    try:
        results = output_run_dir / "results"
        results.mkdir(parents=True)
        campaign_path = results / "derived_post_pulse_campaign.json"
        campaign = derive_campaign(
            repo_root=repo_root, parent_manifest_path=parent_manifest,
            materialization_manifest_path=evidence if materialization_manifest is not None else None,
            compact_receipt_path=evidence if compact_receipt is not None else None,
            output_path=campaign_path,
            execution_mode=execution_mode,
        )
        row = campaign["experiments"]["rows"][0]
        config_path = output_run_dir / "run_config.json"
        _write(config_path, {
            "schema_version": 2, "run_id": output_run_dir.name,
            "project": INTEGRATION_ID, "mode": MODE,
            "project_root": str(repo_root.parent),
            "inputs": {"parent_manifest": str(parent_manifest), evidence_role: str(evidence)},
            "parameters": {"derived_campaign_id": campaign["campaign_id"], "experiment_id": row["experiment_id"], "execution_mode": execution_mode},
            "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None},
            "formal_gate_passed": False,
        })
        summary = output_run_dir / "summary.json"
        _write(summary, {
            "schema_version": 1, "role": "rf_oatof_derived_post_pulse_campaign_summary",
            "status": "success", "campaign_id": campaign["campaign_id"],
            "experiment_id": row["experiment_id"],
            "execution_mode": execution_mode,
            "source_release_mode": campaign["experiments"]["shared"]["source_release_mode"],
        })
        manifest = output_run_dir / "run_manifest.json"
        completed = subprocess.run([
            sys.executable, "-m", "common.contracts.write_run_manifest",
            "--run-config", str(config_path), "--manifest", str(manifest),
            "--status", "success", "--software", f"Python {sys.version_info.major}.{sys.version_info.minor}",
            "--output", str(summary), "--output", str(campaign_path),
        ], cwd=repo_root, capture_output=True, text=True, timeout=300)
        if completed.returncode:
            raise ContractError(
                "derived post-pulse manifest publication failed: " +
                (completed.stderr or completed.stdout).strip()
            )
        return campaign_path
    except Exception:
        if output_run_dir.exists() and not (output_run_dir / "run_manifest.json").exists():
            shutil.rmtree(output_run_dir)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--parent-manifest", required=True, type=Path)
    evidence = parser.add_mutually_exclusive_group(required=True)
    evidence.add_argument("--compact-receipt", type=Path)
    evidence.add_argument("--materialization-manifest", type=Path)
    parser.add_argument("--output-run-dir", required=True, type=Path)
    parser.add_argument("--execution-mode", choices=["particle_flight", "program_axis_field_export"], default="particle_flight")
    arguments = parser.parse_args()
    campaign = publish(
        repo_root=arguments.repo_root.resolve(), parent_manifest=arguments.parent_manifest,
        compact_receipt=arguments.compact_receipt, output_run_dir=arguments.output_run_dir,
        materialization_manifest=arguments.materialization_manifest,
        execution_mode=arguments.execution_mode,
    )
    print(f"DERIVED_POST_PULSE_CAMPAIGN_PUBLISHED=PASS CAMPAIGN={campaign}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
