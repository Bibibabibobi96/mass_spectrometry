"""Artifact lifecycle shared by the analytic multipole transport runners."""

from __future__ import annotations

import json
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator, Mapping

from common.contracts.artifact_naming import validate_run_id
from common.contracts.artifact_project import ensure_artifact_project
from common.contracts.write_run_manifest import build_run_manifest, publish_run_manifest, publish_terminal_state
from projects.rf_multipole_ion_optics.runtime.design_profile import resolve_design_profile
from projects.rf_multipole_ion_optics.core.family_contract import (
    from_high_order_resolved_design,
    l1_l2_transport_contract_from_resolved_design,
    operating_contract_document,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_PROJECTS_ROOT = REPO_ROOT.parent / "artifacts" / "projects"


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class TransportRun(SimpleNamespace):
    """One prepared analytic transport run and its frozen scientific input document."""

    def complete(self, fields: Mapping[str, Any]) -> None:
        """Record the fields required for successful terminalization."""
        if self.completion is not None:
            raise RuntimeError("transport run completion was already recorded")
        self.completion = dict(fields)


def _finalize(run: TransportRun, status: str, fields: Mapping[str, Any]) -> None:
    summary = run.run_dir / "summary.json"
    document = {**fields, "schema_version": 1, "role": run.summary_role, "status": status}
    outputs = run.outputs if status == "success" else [path for path in run.outputs if path.is_file()]
    output_paths = [*outputs, summary] if status == "success" else [summary, *outputs]
    config = run.run_dir / "run_config.json"
    software = [f"Python {sys.version_info.major}.{sys.version_info.minor}"]
    if status == "interrupted":
        _write_json(summary, document)
        publish_run_manifest(config, status, software=software, output_paths=output_paths,
                             extra_fields={"lifecycle_state": "provisional"})
    else:
        manifest = build_run_manifest(config, status, software=software, output_paths=output_paths,
                                      virtual_documents={summary: document}, extra_fields={"lifecycle_state": "terminal"})
        publish_terminal_state(run.run_dir, document, manifest, allow_provisional=True)


@contextmanager
def transport_run(
    project_root: Path, run_id: str, *, mode: str, run_config_role: str, summary_role: str,
    design_profile_id: str, parameters: Mapping[str, Any], identity_inputs: Mapping[str, Path], output_names: tuple[str, ...],
) -> Iterator[TransportRun]:
    """Prepare, freeze, and terminalize one analytic multipole transport run."""
    validate_run_id(run_id)
    descriptor = json.loads((project_root / "config/project.json").read_text(encoding="utf-8"))
    project_id = descriptor["project_id"]
    resolution = resolve_design_profile(REPO_ROOT, project_id, design_profile_id)
    resolved_design = resolution["resolved_design"]
    structural_variant_id = resolution["profile"]["structural_variant_id"]
    if structural_variant_id not in {"hexapole", "octupole"} or design_profile_id != f"{structural_variant_id}_no_acceleration_full_length":
        raise ValueError("L1/L2 transport only supports the registered hexapole/octupole no-acceleration baseline designs")
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
        json.loads((project_root / f"config/modes/{structural_variant_id}_{mode}.json").read_text(encoding="utf-8")),
    )
    frozen_design = json.loads(frozen_resolved.read_text(encoding="utf-8"))
    if frozen_design["identity"]["project_id"] != project_id:
        raise RuntimeError("project identity changed while resolved design input was frozen")
    _write_json(
        family_operating,
        operating_contract_document(from_high_order_resolved_design(frozen_design)),
    )
    frozen_identity = {}
    for name, source in identity_inputs.items():
        destination = input_dir / f"identity_{name}{source.suffix}"
        shutil.copyfile(source, destination)
        frozen_identity[name] = destination
    inputs = {**frozen_identity, "resolved_design": frozen_resolved, "mode": frozen_mode, "family_operating_contract": family_operating}
    _write_json(run_dir / "run_config.json", {
        "schema_version": 1, "role": run_config_role, "run_id": run_id, "project": project_id,
        "mode": mode, "project_root": str(project_root),
        "design_profile_id": design_profile_id, "structural_variant_id": structural_variant_id,
        "inputs": {name: str(path) for name, path in inputs.items()},
        "parameters": dict(parameters), "formal_gate_passed": False,
    })
    run = TransportRun(contract=contract, run_dir=run_dir, result_dir=result_dir, summary_role=summary_role,
                       outputs=[result_dir / name for name in output_names], completion=None, frozen_identity=frozen_identity)
    _finalize(run, "interrupted", {})
    try:
        yield run
        if run.completion is None:
            raise RuntimeError("transport run completed without a success summary")
        _finalize(run, "success", run.completion)
    except Exception as exception:
        try:
            _finalize(run, "failed", {"reason": str(exception)})
        except Exception as closure_error:
            exception.add_note(f"Failure finalization also failed: {closure_error}")
        raise
