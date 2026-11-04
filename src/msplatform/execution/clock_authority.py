"""Validate explicit clock-authority data; no repository discovery or solver state."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from msplatform.contracts.machine_contracts import SCHEMA_DIR
from msplatform.io.file_identity import file_sha256

SCHEMA_PATH = SCHEMA_DIR / "canonical_clock_authority.schema.json"


def validate_clock_authority(contract_path: Path, repository_root: Path) -> dict[str, Any]:
    """Validate semantics and bind the unique authority to its frozen bytes."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    Draft202012Validator(schema).validate(contract)
    authority_path = (repository_root / contract["authority"]["path"]).resolve()
    root = repository_root.resolve()
    if authority_path != root and root not in authority_path.parents:
        raise ValueError("clock authority path escapes the repository")
    if not authority_path.is_file():
        raise ValueError("clock authority file is missing")
    actual_sha256 = file_sha256(authority_path)
    if actual_sha256 != contract["authority"]["sha256"]:
        raise ValueError("clock authority SHA-256 differs from frozen bytes")
    return {
        "schema_version": 1,
        "role": "canonical_clock_authority_validation",
        "status": "PASS",
        "clock_epoch_id": contract["clock_epoch_id"],
        "authority_sha256": actual_sha256,
    }
