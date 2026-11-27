"""Guard and project one exact OA focus author using the backend science owner."""
from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping

from msplatform.backends.simion.oa_focus_model_projection import build_focus_model
from msplatform.io.file_identity import guarded_file_identity
from msplatform.io.manifest_records import file_record, verify_record


def project_focus_model(campaign_path: Path, *, geometry_profile: Mapping[str, Any],
                        mesh_mm_per_gu: list[float], clock: Mapping[str, Any]) -> dict[str, Any]:
    """Hold exact original bytes and resolve them through the single projection owner."""
    path=Path(campaign_path).resolve(strict=True)
    record=file_record(path,'required_evidence')
    contract_path=Path(str(files('msplatform.components.orthogonal_accelerator').joinpath('component_contract.json'))).resolve(strict=True)
    contract_record=file_record(contract_path,'required_evidence')
    with guarded_file_identity(path,expected_bytes=record['bytes'],expected_sha256=record['sha256']), \
         guarded_file_identity(contract_path,expected_bytes=contract_record['bytes'],expected_sha256=contract_record['sha256']):
        campaign=json.loads(path.read_text(encoding='utf8'))
        contract=json.loads(contract_path.read_text(encoding='utf8'))
        result=build_focus_model(campaign,component_contract=contract,campaign_record=record,contract_record=contract_record,
            geometry_profile=geometry_profile,mesh_mm_per_gu=mesh_mm_per_gu,clock=clock)
        verify_record('focus campaign author',record)
        verify_record('focus component contract',contract_record)
        return result
