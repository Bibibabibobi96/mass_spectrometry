"""Bind the structural candidate owner's required request-adjacent proposal."""
from pathlib import Path
from typing import Any

from common.contracts.machine_contracts import load_json, sha256, validate_schema


def resolve_execution_binding(repo_root: Path, project_id: str, bindings: dict[str, str],
                              *, request_path: Path | None = None) -> dict[str, Any]:
    if project_id != "single_reflection_oa_tof_mass_analyzer" or request_path is None:
        raise ValueError("Candidate execution binding needs its planned request identity")
    proposal = request_path.resolve().parent/"candidate_proposal.json"
    if proposal.is_file():
        document = load_json(proposal)
        validate_schema(document, "candidate_proposal.schema.json")
        if document["project_id"] != project_id or document["request"]["sha256"] != sha256(request_path):
            raise ValueError("candidate proposal differs from its planned request identity")
    return dict(project_id=project_id, structural_variant_id=None, authorized_run_id=None,
                input_paths=[str(proposal)] if proposal.is_file() else [],
                missing_inputs=[] if proposal.is_file() else [
                    f"approved request must be accompanied by candidate_proposal.json: {proposal}"])
