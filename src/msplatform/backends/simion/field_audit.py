"""Unique bounded physical-audit identity/reuse transport, shared by old and installed callers."""
from pathlib import Path
import json
from msplatform.io.file_identity import file_sha256, canonical_json_sha256
from msplatform.io.manifest_records import file_record, verify_record
from .pa_family_cache import load_pa_family_cache_transaction
from .field_identity import render_audit_spec


def audit_input_identity(plan: dict) -> str:
    return canonical_json_sha256(dict(domain_id=plan['domain_id'], grid=plan['grid'],
        boundary_policy=plan['boundary_policy'], gem=plan['identity']['gem'],
        physical_electrode_ids=plan['physical_electrode_ids'],
        physical_samples=[{key: row[key] for key in ('electrode_id', 'gu')} for row in plan['physical_samples']],
        working_points=[{key: row[key] for key in ('kind', 'voltage_argument')} for row in plan['working_points']]))

def reusable_audit(plan: dict, generation: Path, verifier: Path) -> dict | None:
    source = plan.get('frozen_field_source')
    if source is not None:
        record = source.get('audit_record')
        if record is None:
            return None
        verify_record('source field audit', record)
    else:
        transaction = load_pa_family_cache_transaction(generation.parent.parent.parent, plan['cache_key'])
        evidence = transaction.get('verification')
        if evidence is None:
            return None
        audit_path = Path(evidence['verification_output_path'])
        if not audit_path.is_file():
            return None
        record = dict(path=str(audit_path), bytes=audit_path.stat().st_size,
                      sha256=evidence['verification_output_sha256'])
        verify_record('published field audit', record)
    report = json.loads(Path(record['path']).read_text(encoding='utf-8-sig'))
    if (report.get('status') != 'pass' or report.get('audit_input_sha256') != audit_input_identity(plan)
            or report.get('audit_verifier_sha256') != file_sha256(verifier)):
        return None
    return file_record(Path(record['path']))

def write_audit_spec(plan: dict, raw: Path, payload: Path, output: Path) -> None:
    """Write the canonical bounded audit transport."""
    output.write_text(render_audit_spec(plan,raw,payload),encoding='utf-8',newline='\n')
