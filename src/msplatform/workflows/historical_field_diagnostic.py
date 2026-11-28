"""Analyze a sealed historical field sweep without its former run owner."""
from __future__ import annotations

import csv
import json
from pathlib import Path
import shutil

from msplatform.backends.simion.field_intervention import analyze_field_intervention, resolve_field_selector
from msplatform.execution.native_source_guard import guard_historical_run
from msplatform.execution.owner import store_growth_accountant
from msplatform.io.manifest_records import file_record, verify_record

_PROJECT = 'single_reflection_oa_tof_mass_analyzer'
_MODE = 'simion_field_idealization_sweep'


def analyze_recorded_field_sweep(*, source_manifest: Path, artifact_store, budget_bytes: int,
                                 detector_radius_mm: float = 40.0) -> dict:
    """Publish one read-only analysis of a successful v1 diagnostic sweep.

    Cases, source population and logs come exclusively from the original
    manifest. Failed/interrupted histories are deliberately not admitted as
    complete sweeps. No vendor process, old lifecycle owner or resampling runs.
    """
    if type(budget_bytes) is not int or budget_bytes <= 0:
        raise ValueError('budget_bytes must be a positive integer')
    manifest = file_record(Path(source_manifest).resolve(strict=True), 'required_evidence')
    with guard_historical_run(manifest, expected_project=_PROJECT, expected_mode=_MODE) as source:
        count = source.config.get('particle_count')
        seed = source.config.get('seed')
        if type(count) is not int or count < 1 or type(seed) is not int:
            raise ValueError('historical diagnostic count or seed differs')
        config_record = source.input('case_config')
        config = json.loads(Path(config_record['path']).read_text(encoding='utf-8-sig'))
        cases = config.get('cases')
        if not isinstance(cases, list) or not cases:
            raise ValueError('historical diagnostic cases are missing')
        ids = []
        for case in cases:
            if not isinstance(case, dict):
                raise ValueError('historical diagnostic case is malformed')
            name = case.get('id')
            if (not isinstance(name, str) or not name.isascii()
                    or not name.replace('_', '').isalnum() or name in ids):
                raise ValueError('historical diagnostic case identity differs')
            resolve_field_selector(case.get('selector'))
            ids.append(name)
        records = {'case_config.json': config_record,
                   'source_run_manifest.json': manifest,
                   'source_run_config.json': dict(source.manifest['run_config'],
                                                  path=str(source.root/'run_config.json')),
                   'source.ion': source.output(f'simion/oatof_N{count}.ion')}
        records.update({f'logs/{name}.log': source.output(f'logs/{name}.log') for name in ids})
        run_id, work = artifact_store.begin_run()
        with artifact_store.run_writer(run_id):
            try:
                with artifact_store.reserve(budget_bytes) as reservation:
                    artifact_store.mark_running(run_id)
                    account = store_growth_accountant(artifact_store, reservation, budget_bytes, work)
                    frozen = {}
                    for name, record in records.items():
                        target = work/'inputs'/name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(record['path'], target)
                        frozen_record = dict(record, path=str(target))
                        verify_record('frozen diagnostic input', frozen_record)
                        frozen[name] = target
                    account(work)
                    rows = []
                    for case in cases:
                        frame, metrics = analyze_field_intervention(case=case,
                            log=frozen[f'logs/{case["id"]}.log'], particle_table=frozen['source.ion'],
                            particle_count=count, detector_radius_mm=detector_radius_mm)
                        result_path = work/'results'/f'{case["id"]}_particles.csv'
                        result_path.parent.mkdir(parents=True, exist_ok=True)
                        frame.to_csv(result_path, index=False)
                        rows.append(dict(case_id=case['id'], selector=case['selector'],
                            detected=metrics['Hit'], mean_tof_us=metrics['MeanTofUs'],
                            tof_std_ns=metrics['StdTofNs'], landing_max_mm=metrics['MaxHitRadiusMm'],
                            solve_seconds=None, particle_csv=f'results/{case["id"]}_particles.csv'))
                        account(work)
                    summary = dict(schema_version=1, status='success',
                        particle_count=count, seed=seed, detector_radius_mm=detector_radius_mm,
                        source_run_id=source.config['run_id'], source_manifest=manifest,
                        purpose='method feasibility, not precision agreement', cases=rows,
                        capability_boundary='SIMION regional Ez interventions only; no independent global Ex/Ey')
                    (work/'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False)+'\n', encoding='utf8')
                    with (work/'sweep_summary.csv').open('w', encoding='utf8', newline='') as stream:
                        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                        writer.writeheader()
                        writer.writerows(rows)
                    account(work)
                    _, published = artifact_store.publish_run(work, run_id=run_id)
                return dict(store_run_id=run_id, store_run_path=str(published), cases=len(rows))
            except BaseException as failure:
                status = artifact_store.run_status(run_id)['execution_status']
                if status == 'running':
                    artifact_store.finish_run(run_id, 'failed', reason=str(failure))
                elif status == 'queued':
                    artifact_store.set_queued_reason(run_id, str(failure))
                failure.add_note('Store run_id: ' + run_id)
                raise
