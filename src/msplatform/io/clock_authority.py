"""Read and bind the explicit clock-authority files without discovering a workspace."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from msplatform.contracts.clock import bind_clock_authority_identity, validate_clock_authority_structure
from msplatform.contracts.machine_contracts import SCHEMA_DIR
from msplatform.io.file_identity import file_sha256

SCHEMA_PATH = SCHEMA_DIR / 'canonical_clock_authority.schema.json'
FROZEN_PACKAGE_RESOURCES = ('contracts/schemas/canonical_clock_authority.schema.json',)


def validate_clock_authority(contract_path: Path, repository_root: Path) -> dict[str, Any]:
    """Validate the clock schema, contained authority path and actual file SHA."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
    contract = json.loads(contract_path.read_text(encoding='utf-8-sig'))
    validate_clock_authority_structure(contract, schema)
    authority_path = (repository_root / contract['authority']['path']).resolve()
    root = repository_root.resolve()
    if authority_path != root and root not in authority_path.parents:
        raise ValueError('clock authority path escapes the repository')
    if not authority_path.is_file():
        raise ValueError('clock authority file is missing')
    return bind_clock_authority_identity(contract, file_sha256(authority_path))
