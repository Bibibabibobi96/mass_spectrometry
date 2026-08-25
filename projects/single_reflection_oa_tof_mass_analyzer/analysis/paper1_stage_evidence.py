"""Atomic stage-evidence package for the Paper 1 gated workflow."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


_CONCLUSIONS = {"PASS_CONTINUE", "FAIL_STOP", "INCONCLUSIVE_REVISE"}


@dataclass(frozen=True)
class StageEvidence:
    """Immutable content that every completed Paper 1 stage must expose."""

    stage_id: str
    conclusion: str
    claim_limit: str
    inputs: Mapping[str, Any]
    metrics: Mapping[str, Any]
    claims_supported: Sequence[str]
    claims_prohibited: Sequence[str]
    failures: Sequence[str]


def publish_stage_evidence(destination: Path, evidence: StageEvidence) -> Path:
    """Atomically publish the five required stage documents under ``destination``."""

    if not evidence.stage_id or evidence.conclusion not in _CONCLUSIONS:
        raise ValueError("stage evidence has an invalid stage ID or conclusion")
    if destination.exists():
        raise FileExistsError(f"stage evidence destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.pending-", dir=destination.parent))
    try:
        payload = asdict(evidence)
        contract = (
            f"# {evidence.stage_id} stage contract\n\n"
            f"- Claim limit: {evidence.claim_limit}\n"
            f"- Conclusion vocabulary: PASS_CONTINUE, FAIL_STOP, INCONCLUSIVE_REVISE\n"
        )
        report = (
            f"# {evidence.stage_id} stage report\n\n"
            f"- Conclusion: `{evidence.conclusion}`\n"
            f"- Metrics: `{json.dumps(dict(evidence.metrics), sort_keys=True)}`\n"
            f"- Failures: `{json.dumps(list(evidence.failures))}`\n"
        )
        conclusion = (
            f"# {evidence.stage_id} conclusion\n\n"
            f"`{evidence.conclusion}`\n\n"
            f"Supported: {', '.join(evidence.claims_supported) or 'none'}\n\n"
            f"Prohibited: {', '.join(evidence.claims_prohibited) or 'none'}\n"
        )
        (staging / "stage_contract.md").write_text(contract, encoding="utf-8", newline="\n")
        (staging / "stage_report.md").write_text(report, encoding="utf-8", newline="\n")
        (staging / "stage_conclusion.md").write_text(conclusion, encoding="utf-8", newline="\n")
        for name, document in (("stage_manifest.json", {"schema_version": 1, "role": "oatof_paper1_stage_manifest", **payload}), ("stage_report.json", {"schema_version": 1, "role": "oatof_paper1_stage_report", **payload})):
            (staging / name).write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        os.replace(staging, destination)
    except BaseException:
        for child in staging.glob("*"):
            child.unlink()
        staging.rmdir()
        raise
    return destination
