"""Read one recorded OA-to-MR receipt as historical evidence only."""
from __future__ import annotations

import json
from pathlib import Path

from msplatform.execution.native_source_guard import guard_historical_run
from msplatform.io.manifest_records import file_record


def read_historical_oa_mr_receipt(*, source_manifest: Path) -> dict:
    """Read the exact v1 receipt from a successful v2 legacy run.

    Referenced PA families and flight results are not opened or certified.  The
    historical candidate status remains evidence, not a current field or birth.
    """
    manifest=file_record(Path(source_manifest).resolve(strict=True),'required_evidence')
    with guard_historical_run(manifest,expected_project='orthogonal_accelerator',
                              expected_mode='component_focus_workflow') as source:
        record=source.output('results/mrtof_runtime_receipt.json')
        receipt=json.loads(Path(record['path']).read_text(encoding='utf-8-sig'))
        if (not isinstance(receipt,dict) or receipt.get('schema_version')!=1
                or receipt.get('role')!='orthogonal_accelerator_mrtof_runtime_receipt'
                or receipt.get('status')!='published_standalone_response_bank'
                or not isinstance(receipt.get('mrtof_projection'),dict)):
            raise ValueError('historical OA-to-MR receipt identity differs')
        return dict(schema_version=1,role='historical_oa_mr_receipt_evidence',
            source_manifest=manifest,source_receipt=record,original_receipt=receipt,
            interpretation='historical_only_referenced_payloads_not_verified')
