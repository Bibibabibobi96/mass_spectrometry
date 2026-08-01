"""Artifact lifecycle shared by the analytic multipole transport runners."""

from __future__ import annotations

import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator, Mapping

from common.contracts.artifact_naming import validate_run_id
from common.contracts.artifact_project import ensure_artifact_project
from common.multipole.design_profile import resolve_design_profile
from common.multipole.family_contract import (
    from_high_order_resolved_design,
    l1_l2_transport_contract_from_resolved_design,
    operating_contract_document,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_PROJECTS_ROOT = REPO_ROOT.parent / "artifacts" / "projects"


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_manifest(run_config: Path, status: str, outputs: list[Path]) -> None:
    command = [sys.executable, str(REPO_ROOT / "common/contracts/write_run_manifest.py"), "--run-config", str(run_config)]
    command.extend(("--status", status, "--software", f"Python {sys.version_info.major}.{sys.version_info.minor}"))
    command.extend(argument for output in outputs for argument in ("--output", str(output)))
    subprocess.run(command, check=True, cwd=REPO_ROOT, timeout=60)


class TransportRun(SimpleNamespace):
    """One prepared analytic transport run and its frozen scientific input document."""

    def complete(self, fields: Mapping[str, Any]) -> None:
        """Record the fields required for successful terminalization."""
        if self.completion is not None:
            raise RuntimeError("transport run completion was already recorded")
        self.completion = dict(fields)


def _finalize(run: TransportRun, status: str, fields: Mapping[str, Any]) -> None:
    summary = run.run_dir / "summary.json"
    _write_json(summary, {**fields, "schema_version": 1, "role": run.summary_role, "status": status})
    outputs = run.outputs if status == "success" else [path for path in run.outputs if path.is_file()]
    _write_manifest(run.run_dir / "run_config.json", status, [*outputs, summary] if status == "success" else [summary, *outputs])


@contextmanager
def transport_run(
    project_root: Path, run_id: str, *, mode: str, run_config_role: str, summary_role: str,
    parameters: Mapping[str, Any], identity_inputs: Mapping[str, Path], output_names: tuple[str, ...],
) -> Iterator[TransportRun]:
    """Prepare, freeze, and terminalize one analytic multipole transport run."""
    validate_run_id(run_id)
    descriptor = json.loads((project_root / "config/project.json").read_text(encoding="utf-8"))
    project_id = descriptor["project_id"]
    resolution = resolve_design_profile(REPO_ROOT, project_id, "no_acceleration_full_length")
    resolved_design = resolution["resolved_design"]
    contract = l1_l2_transport_contract_from_resolved_design(resolved_design)
    run_dir = ensure_artifact_project(ARTIFACT_PROJECTS_ROOT, project_id) / "runs" / run_id
    if run_dir.exists():
        raise FileExistsError(f"run directory already exists: {run_dir}")
    input_dir, result_dir = run_dir / "inputs", run_dir / "results"
    for directory in (input_dir, result_dir, run_dir / "logs"):
        directory.mkdir(parents=True)
    frozen_resolved, frozen_mode = input_dir / "resolved_design.json", input_dir / f"{mode}.json"
    family_operating = input_dir / "family_operating_contract.json"
    _write_json(frozen_resolved, resolved_design)
    _write_json(
        frozen_mode,
        json.loads((project_root / f"config/modes/{mode}.json").read_text(encoding="utf-8")),
    )
    frozen_design = json.loads(frozen_resolved.read_text(encoding="utf-8"))
    if frozen_design["identity"]["project_id"] != project_id:
        raise RuntimeError("project identity changed while resolved design input was frozen")
    _write_json(
        family_operating,
        operating_contract_document(from_high_order_resolved_design(frozen_design)),
    )
    inputs = {**identity_inputs, "resolved_design": frozen_resolved, "mode": frozen_mode, "family_operating_contract": family_operating}
    _write_json(run_dir / "run_config.json", {
        "schema_version": 1, "role": run_config_role, "run_id": run_id, "project": project_id,
        "mode": mode, "project_root": str(project_root),
        "inputs": {name: str(path) for name, path in inputs.items()},
        "parameters": dict(parameters), "formal_gate_passed": False,
    })
    run = TransportRun(contract=contract, run_dir=run_dir, result_dir=result_dir, summary_role=summary_role,
                       outputs=[result_dir / name for name in output_names], completion=None)
    _finalize(run, "interrupted", {})
    try:
        yield run
        if run.completion is None:
            raise RuntimeError("transport run completed without a success summary")
        _finalize(run, "success", run.completion)
    except Exception as exception:
        _finalize(run, "failed", {"reason": str(exception)})
        raise
