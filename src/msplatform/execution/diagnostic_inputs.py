"""Authenticate and freeze the consumed records of an ideal-field diagnostic."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from msplatform.execution.manifest_verification import _select_consumed_output, verify_run_manifest
from msplatform.execution.retention import file_record, verify_record as verify_run_record
from msplatform.io.manifest_records import record_path

PROJECT_ID = "single_reflection_oa_tof_mass_analyzer"


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def stage_diagnostic_inputs(source_run: Path, destination: Path, receipt: Path, cases: list[str]) -> dict:
    """Freeze only a terminal diagnostic's actual logs, ION tables and controls.

    The caller holds the existing terminal-consumption guard during this copy.
    No Formal package or solver installation is consulted on this branch.
    """
    source_run = source_run.resolve(strict=True)
    manifest_path = source_run / 'run_manifest.json'
    manifest = load_json(manifest_path)
    if manifest.get('status') not in {'success', 'failed', 'interrupted'}:
        raise ValueError('diagnostic analysis requires a terminal source run')
    config_path = record_path(manifest['run_config'], base_dir=source_run)
    config = load_json(config_path)
    mode = config.get('mode')
    if mode not in {'simion_ideal_field_matrix', 'simion_field_idealization_sweep'}:
        raise ValueError('analysis source must be an ideal-field diagnostic run')
    count = config.get('particles') if mode == 'simion_ideal_field_matrix' else config.get('particle_count')
    seed = config.get('seed')
    if type(count) is not int or count < 1 or type(seed) is not int:
        raise ValueError('source diagnostic particle count and seed are missing or invalid')
    if not cases or len(cases) != len(set(cases)) or any(
            not isinstance(case, str) or not case.isascii() or not case.replace('_', '').isalnum()
            for case in cases):
        raise ValueError('explicit diagnostic cases must be unique safe identifiers')
    sources = {f'logs/{case}.log': source_run / 'logs' / f'{case}.log' for case in cases}
    consumed_inputs = []
    if mode == 'simion_ideal_field_matrix':
        if any(len(case.split('__')) != 2 or not all(part for part in case.split('__')) for case in cases):
            raise ValueError('matrix cases must be distribution/mode names')
        sources.update({f'ions/ions_{case.split("__")[0]}_N{count}.ion':
            source_run / 'simion' / f'ions_{case.split("__")[0]}_N{count}.ion' for case in cases})
    else:
        sources[f'ions/oatof_N{count}.ion'] = source_run / 'simion' / f'oatof_N{count}.ion'
        case_record = manifest.get('inputs', {}).get('case_config')
        if not isinstance(case_record, dict):
            raise ValueError('sweep source lacks a frozen case configuration')
        case_path = record_path(case_record, base_dir=source_run)
        case_path.relative_to(source_run)
        consumed_inputs = [('case_config', case_path)]
    try:
        verify_run_manifest(
            manifest_path, require_status=manifest['status'], require_project=PROJECT_ID,
            require_run_id=source_run.name, require_mode=mode,
            require_local_run_config=True, consumer_projection_id='ideal_field_diagnostic_analysis',
            consumed_inputs=consumed_inputs, consumed_outputs=list(sources.values()),
        )
    except (AssertionError, ValueError) as error:
        error.add_note("ACTION=provide_complete_manifest_bound_diagnostic_logs_and_original_ION_or_run_normal_diagnostic")
        raise
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f'diagnostic input destination already exists: {destination}')
    records = {}
    try:
        destination.mkdir(parents=True)
        if mode == 'simion_field_idealization_sweep':
            case_config = load_json(case_path)
            rows = case_config.get('cases')
            if (not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows)
                    or [row.get('id') for row in rows] != cases
                    or any(not isinstance(row.get('selector'), str) for row in rows)):
                raise ValueError('sweep cases differ from the frozen case configuration')
            target = destination / 'case_config.json'
            shutil.copyfile(case_path, target)
            frozen = dict(case_record, path=str(target))
            verify_run_record('frozen sweep configuration', frozen)
            records['case_config.json'] = dict(frozen, source_path=str(case_path))
        for relative, source in sources.items():
            _, bound = _select_consumed_output(manifest['outputs'], source, base_dir=source_run)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            frozen = dict(bound, path=str(target))
            verify_run_record('frozen diagnostic input', frozen)
            records[relative] = dict(frozen, source_path=str(source))
        for name, source, bound in (('source_run_config.json', config_path, manifest['run_config']),
                                    ('source_run_manifest.json', manifest_path, file_record(manifest_path))):
            target = destination / name
            shutil.copyfile(source, target)
            frozen = dict(bound, path=str(target))
            verify_run_record('frozen diagnostic authority', frozen)
            records[name] = dict(frozen, source_path=str(source))
        payload = dict(schema_version=1, role='oa_tof_ideal_field_analysis_source',
            source_run_id=manifest['run_id'], source_status=manifest['status'], particle_count=count,
            seed=seed, cases=cases, inputs=records)
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps(payload, indent=2)+'\n', encoding='utf-8', newline='\n')
    except Exception:
        if destination.exists():
            shutil.rmtree(destination)
        raise
    return payload



def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--receipt', required=True, type=Path)
    parser.add_argument('--case', action='append', required=True)
    args = parser.parse_args()
    print(json.dumps(stage_diagnostic_inputs(args.source_run, args.destination, args.receipt, args.case)))


if __name__ == '__main__':
    main()
