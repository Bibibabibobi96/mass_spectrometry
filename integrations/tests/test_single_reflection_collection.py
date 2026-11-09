"""Bounded synthetic native logs test real preparation and analyzer contracts."""
from __future__ import annotations

import csv
import copy
import json
import math
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from msplatform.backends.simion.tracking_collection import canonical_census, read_native_events
from msplatform.execution.inputs import python_import_roots
from msplatform.execution.retention import file_record
from integrations.tests.test_single_reflection_preparation import fixture, write_json
from msplatform.workflows.single_reflection_flight.prepare import prepare
from msplatform.workflows.single_reflection_flight.collect import collect_log, compare_collections, select_pulse
from msplatform.workflows.single_reflection_flight.pulse import resolve_phase_flight

ROOT = Path(__file__).resolve().parents[2]


class SingleReflectionCollectionTests(unittest.TestCase):
    def observed_fixture(self):
        from integrations.tests.test_single_reflection_runtime import WorkbenchMaterializationTests
        from integrations.tests.test_single_reflection_preparation import scientific_preparation_fixture
        from integrations.tests.test_single_reflection_program import field_observation_spec
        from msplatform.workflows.single_reflection_flight.runtime import _prepare_context,materialize_batches
        from msplatform.backends.simion.particle_batching import plan_single_wave_batches

        owner = WorkbenchMaterializationTests()
        owner.setUp()
        self.addCleanup(owner.doCleanups)
        folder = owner.root/'observed_collection'
        folder.mkdir()
        request_path,owner.run,request = scientific_preparation_fixture(folder,recorded_birth=True)
        flight = dict(pulse=dict(mode='timed',time_us=10.,width_us=3.),maximum_flight_us=200.,
                      maximum_step_us=.001,trajectory_quality=17,rf_steps_per_period=80)
        spec = field_observation_spec(anchor=1,clock='instrument_clock_epoch_v1')
        validation = request_path.parent/'validation.json'
        write_json(validation,dict(native_field_observation=spec))
        request.update(validation_contract=file_record(validation),flight=flight)
        write_json(request_path,request)
        owner.preparation = prepare(request_path,owner.run)
        write_json(owner.run/'run_config.json',dict(project='instrument_assembly'))
        owner.geometry = json.loads((owner.run/'inputs/frontend_geometry.json').read_text())
        owner.publish_fields()
        context = _prepare_context(owner.preparation,owner.field_receipt,file_record(owner.downstream_path),
                                   owner.run,snapshot_root=owner.snapshot,flight=flight)
        workbench = materialize_batches(owner.run,'full_instrument',plan_single_wave_batches(100,2),context=context)
        for case in workbench['batches']:
            iob = Path(case['outputs']['program']['path']).with_suffix('.iob')
            iob.write_bytes(b'INERT_IOB_NOT_NATIVE_EVIDENCE')
            case['outputs']['iob'] = file_record(iob)
            low,high = case['source_row_range']
            lines = []
            for ion,row in enumerate(context['source'][low-1:high],1):
                pid,t = int(row['particle_id']),float(row['instrument_time_us'])
                state = ' '.join(f'{axis}_mm={float(row[f"position_{axis}_mm"]):.17g}' for axis in 'xyz')
                state += ' '+' '.join(f'v{axis}_mm_per_us={float(row[f"velocity_{axis}_m_s"])/1000:.17g}' for axis in 'xyz')
                xyz = ' '.join(f'{axis}={float(row[f"position_{axis}_mm"]):.17g}' for axis in 'xyz')
                lines.extend((f'TRACE: source_release ion={ion} particle_id={pid} instrument_time_us={t:.17g} {state}',
                    f'TRACE: handoff_terminal_raw ion={ion} instance=3 instrument_time_us={t+1:.17g} {state}',
                    f'TRACE: non_detector_splat ion={ion} instance=3 t={t+1:.17g} {xyz} zmax=0'))
            lines.append(f'status,Fly completed. {high-low+1} splats')
            log = owner.run/(case['case_id']+'.log')
            log.write_text('\n'.join(lines)+'\n',encoding='utf-8')
            case.update(stdout=str(log),replay_stdout=str(log))
        metadata = workbench['batches'][0]['build_metadata']['native_field_observation']
        header = dict(schema_version=1,role='single_reflection_applied_field_observation_header',
                      specification=spec,context=metadata['context'])
        fields = metadata['context']['field_records']['parent']
        rows = []
        for index,bucket in enumerate(spec['buckets']):
            for ordinal in range(2):
                t = (bucket['time_min_us']+bucket['time_max_us'])/2
                active = 10 <= t < 13
                row = dict(schema_version=1,role='single_reflection_applied_field_query',basis='efield_adjust_query_only',
                    record_seq=len(rows)+1,callback_seq=len(rows)+1,bucket_id=bucket['bucket_id'],instrument_time_us=t,
                    solver_elapsed_us=t-1,particle_id=1,ion_number=1,instance_index=3,domain_id='parent',
                    world_frame_id='oatof_global',world_position_mm=[1,2,3],grid_spacing_mm=[.3,.25,.1],
                    instance_scale=1,instance_rotation_deg=[0,0,0],entry_gradient_gu=[10,20,30],
                    rf_members=[dict(coefficient_used=.5,native_field_gu=[2,-3,5],native_path=fields['rf_reference']['path'])],pulse_active_used=active,
                    pulse_basis='actual_field_vc_used' if active else 'not_applied_not_queried',pa_gu=[1,2,3],
                    after_dynamic_gradient_gu=[9,21.5,27.5],region_override=dict(replace_all=False),
                    after_region_gradient_gu=[9,21.5,27.5],final_gradient_gu=[9,21.5,27.5],actual_rf_phase_rad=.37,
                    rf_phase_basis='unwrapped_kernel_phase_at',
                    carrier_native_field_gu=[-10,-20,-30],
                    carrier_native_path=fields['carrier_off']['path'])
                if active: row.update(pulse_scale_used=1,pulse_native_field_gu=[7,11,-13],pulse_native_path=fields['pulse_delta']['path'])
                rows.append(row)
        summary = dict(schema_version=1,role='single_reflection_applied_field_observation_summary',rows=16,
                       counts={bucket['bucket_id']:2 for bucket in spec['buckets']},coverage_complete=True,stopped_by='row_cap',deadline_seen=False)
        return owner,workbench,header,rows,summary

    def test_applied_field_evidence_is_separate_bounded_and_published_without_changing_mother_events(self):
        owner,workbench,header,rows,summary = self.observed_fixture()
        path = Path(workbench['batches'][0]['stdout'])
        native = path.read_text()
        baseline = collect_log(owner.preparation,workbench,owner.run)
        self.assertEqual(baseline['native_field_observation']['status'],'INCONCLUSIVE')
        partial = dict(summary,rows=2,counts={key:(2 if key==rows[0]['bucket_id'] else 0) for key in summary['counts']},
                       coverage_complete=False,stopped_by='native_end')
        path.write_text(native+f'TRACE: applied_field_observation_header {json.dumps(header)}\n'+
            ''.join(f'TRACE: applied_field_observation {json.dumps(row)}\n' for row in rows[:2])+
            f'TRACE: applied_field_observation_summary {json.dumps(partial)}\n',encoding='utf-8')
        incomplete = collect_log(owner.preparation,workbench,owner.run)['native_field_observation']
        self.assertEqual(incomplete['status'],'INCONCLUSIVE')
        self.assertEqual(len(incomplete['missing_buckets']),7)
        traces = [f'TRACE: applied_field_observation_header {json.dumps(header)}',
                  *(f'TRACE: applied_field_observation {json.dumps(row)}' for row in rows),
                  f'TRACE: applied_field_observation_summary {json.dumps(summary)}']
        path.write_text(native+'\n'.join(traces)+'\n',encoding='utf-8')
        result = collect_log(owner.preparation,workbench,owner.run)
        self.assertEqual(result['native_field_observation']['status'],'RECORDED')
        self.assertEqual(result['native_field_observation']['missing_buckets'],[])
        self.assertEqual(result['native_field_observation']['queries'],rows)
        for key in ('canonical_events','census','native_terminals','native_shared_states'):
            self.assertEqual(result[key],baseline[key])
        prep,bench = owner.run/'prep.json',owner.run/'bench.json'
        write_json(prep,owner.preparation);write_json(bench,workbench)
        output = owner.run/'results/observed'
        command = [sys.executable,'-m','msplatform.workflows.single_reflection_flight.collect',
                   '--preparation',str(prep),'--workbench',str(bench),'--run',str(owner.run),'--output',str(output)]
        completed = subprocess.run(command,cwd=ROOT, env={**os.environ, "PYTHONPATH": os.pathsep.join(python_import_roots(ROOT)), "PYTHONNOUSERSITE": "1"},capture_output=True,text=True,timeout=60,check=False)
        self.assertEqual(completed.returncode,0,completed.stdout+completed.stderr)
        receipt = json.loads(completed.stdout)
        self.assertEqual(receipt['output_records']['native_field_observation.json'],file_record(output/'native_field_observation.json'))
        self.assertEqual(json.loads((output/'collection.json').read_text())['native_field_observation_status'],'RECORDED')
        failed = owner.run/'results/io_failure'
        failed.mkdir()
        (failed/'native_field_observation.json').write_text('original protected evidence')
        command[command.index('--output')+1] = str(failed)
        rejected = subprocess.run(command,cwd=ROOT, env={**os.environ, "PYTHONPATH": os.pathsep.join(python_import_roots(ROOT)), "PYTHONNOUSERSITE": "1"},capture_output=True,text=True,timeout=60,check=False)
        self.assertNotEqual(rejected.returncode,0)
        self.assertEqual((failed/'native_field_observation.json').read_text(),'original protected evidence')

    def test_applied_field_parser_rejects_unknown_duplicate_unbound_and_overcap_queries(self):
        owner,workbench,header,rows,summary = self.observed_fixture()
        path = Path(workbench['batches'][0]['stdout'])
        native = path.read_text()
        for change in ('undeclared','wrong_batch','duplicate','version','source','context','window','nonfinite','cap','summary',
                       'bad_json','duplicate_json_key','bytes'):
            h,r,s = copy.deepcopy(header),copy.deepcopy(rows),copy.deepcopy(summary)
            target = path
            if change == 'version': r[0]['schema_version'] = True
            elif change == 'source': r[0]['particle_id'] = 101
            elif change == 'context': h['context']['input_records']['source']['sha256'] = 'a'*64
            elif change == 'window': r[0]['instrument_time_us'] = 999
            elif change == 'nonfinite': r[0]['final_gradient_gu'][0] = float('nan')
            elif change == 'duplicate': r.insert(1,copy.deepcopy(r[0]))
            elif change == 'cap': r.append(copy.deepcopy(r[-1]))
            elif change == 'summary': s['counts'][next(iter(s['counts']))] = 1
            elif change == 'wrong_batch': target = Path(workbench['batches'][1]['stdout'])
            original = target.read_text()
            if change == 'undeclared':
                validation = Path(owner.preparation['input_records']['validation_contract']['path'])
                validation_bytes = validation.read_bytes()
                write_json(validation,{})
                owner.preparation['input_records']['validation_contract'] = file_record(validation)
            traces = [f'TRACE: applied_field_observation_header {json.dumps(h)}',
                      *(f'TRACE: applied_field_observation {json.dumps(row)}' for row in r),
                      f'TRACE: applied_field_observation_summary {json.dumps(s)}']
            if change == 'bad_json': traces[1] = 'TRACE: applied_field_observation {'
            elif change == 'duplicate_json_key': traces[1] = traces[1].replace('{','{"schema_version":1,',1)
            elif change == 'bytes': traces[0] += ' '*(524288+1)
            target.write_text(original+'\n'.join(traces)+'\n',encoding='utf-8')
            with self.subTest(change=change),self.assertRaises(ValueError):
                collect_log(owner.preparation,workbench,owner.run)
            target.write_text(original,encoding='utf-8')
            if change == 'undeclared':
                validation.write_bytes(validation_bytes)
                owner.preparation['input_records']['validation_contract'] = file_record(validation)
        path.write_text(native+'TRACE: applied_field_observation_unknown {}\n',encoding='utf-8')
        with self.assertRaises(ValueError): collect_log(owner.preparation,workbench,owner.run)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        request_path, self.run, request = fixture(self.root)
        self.flight = dict(pulse=dict(mode='held_off'), maximum_flight_us=10., maximum_step_us=.1,
                           trajectory_quality=8, rf_steps_per_period=32)
        request['flight'] = self.flight
        write_json(request_path, request)
        self.preparation = prepare(request_path, self.run)
        folder = self.run / 'simion/full_instrument'
        folder.mkdir(parents=True)
        outputs = {}
        for key, filename in (('iob', 'instrument.iob'), ('program', 'instrument.lua'),
                              ('particles', 'instrument.fly2'), ('build_spec', 'iob_build.lua')):
            path = folder / filename
            path.write_text('INERT_CONTROL_NOT_NATIVE_EVIDENCE', encoding='utf-8')
            outputs[key] = file_record(path)
        provenance = json.loads((self.run / 'inputs/source_provenance.json').read_text())
        self.workbench = dict(role='single_reflection_workbench_preparation', phase='full_instrument', particle_count=100,
            source_transform_applied=False, source_record=self.preparation['outputs']['projected_source'],
            clock_epoch_id=provenance['clock_epoch_id'], outputs=outputs, inputs={}, flight=copy.deepcopy(self.flight))
        with (self.run / 'inputs/projected_source.csv').open(newline='', encoding='utf-8-sig') as stream:
            self.source = list(csv.DictReader(stream))
        self.lines = []
        for source in self.source:
            pid = int(source['particle_id'])
            t = float(source['instrument_time_us'])
            state = ' '.join(f'{a}_mm={float(source[f"position_{a}_mm"]):.17g}' for a in 'xyz')
            state += ' ' + ' '.join(f'v{a}_mm_per_us={float(source[f"velocity_{a}_m_s"])/1000:.17g}' for a in 'xyz')
            self.lines.append(f'TRACE: source_release ion={pid} particle_id={pid} instrument_time_us={t:.17g} {state}')
            self.lines.append(f'TRACE: handoff_terminal_raw ion={pid} instance=3 instrument_time_us={t+1:.17g} {state}')
            xyz = ' '.join(f'{a}={float(source[f"position_{a}_mm"]):.17g}' for a in 'xyz')
            self.lines.append(f'TRACE: non_detector_splat ion={pid} instance=3 t={t+1:.17g} {xyz} zmax=0')
        self.lines.append(f'status,Fly completed. {len(self.source)} splats')
        self.log = self.run / 'native.stdout.log'
        self.write_log(self.lines)

    def write_log(self, lines, name=None):
        path = self.log if name is None else self.run / name
        path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        return path

    def collect(self, path=None):
        return collect_log(self.preparation, self.workbench, self.run, path or self.log)

    @unittest.skipUnless(os.name == 'nt', 'Windows execution junction semantics')
    def test_collection_embeds_enduring_input_paths_after_junction_removal(self):
        alias = self.root / 'execution_alias'
        linked = subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(self.run)],
            cwd=self.root, capture_output=True, text=True, check=False, timeout=30)
        self.assertEqual(linked.returncode, 0, linked.stdout + linked.stderr)
        original = copy.deepcopy(self.preparation)
        try:
            for record in [self.preparation['input_records']['request'], *(
                    self.preparation['outputs'][key] for key in
                    ('frontend_geometry', 'frontend_field_design', 'projected_source'))]:
                record['path'] = str(alias / Path(record['path']).relative_to(self.run))
            self.workbench['source_record'] = self.preparation['outputs']['projected_source']
            result = self.collect()
        finally:
            os.rmdir(alias)
        for name, record in (
                ('request_record', original['input_records']['request']),
                ('geometry_record', original['outputs']['frontend_geometry']),
                ('field_design_record', original['outputs']['frontend_field_design']),
                ('source_record', original['outputs']['projected_source'])):
            self.assertEqual(result[name], record)
            self.assertTrue(Path(result[name]['path']).is_file())

    def split_batches(self):
        original = copy.deepcopy(self.workbench)
        count = len(self.source)
        middle = count//2
        cases = []
        for index, (start, end) in enumerate(((0,middle),(middle,count)),1):
            lines = [re.sub(r'\bion=(\d+)', lambda m: 'ion='+str(int(m[1])-start), line)
                     for line in self.lines[3*start:3*end]]+[f'status,Fly completed. {end-start} splats']
            log = self.write_log(lines, f'batch_{index}.stdout.log')
            case = copy.deepcopy(original)
            case.update(source_row_range=[start+1,end],expected_particle_ids=[int(row['particle_id'])
                for row in self.source[start:end]],stdout=str(log),replay_stdout=str(log))
            cases.append(case)
        self.workbench['batches'] = cases
        return cases

    def test_batch_logs_require_each_native_completion_and_exact_cohort_coverage(self):
        cases = self.split_batches()
        baseline = self.collect()
        self.assertEqual(len(baseline['native_terminals']),100)
        self.assertEqual(len(baseline['log_record']),2)
        replay = collect_log(self.preparation,self.workbench,self.run,replay=True)
        self.assertTrue(compare_collections(baseline,replay)['passed'])
        path = Path(cases[1]['stdout'])
        original = path.read_text()
        path.write_text(original.replace('status,Fly completed.',''))
        with self.assertRaisesRegex(ValueError,'completion sentinel'):
            self.collect()
        path.write_text(original)
        cases[1]['expected_particle_ids'] = cases[0]['expected_particle_ids']
        with self.assertRaisesRegex(ValueError,'source-row binding'):
            self.collect()

    def test_inline_flight_is_derived_from_authority_and_shared_by_all_batches(self):
        self.workbench['flight']['maximum_step_us'] = .2
        with self.assertRaisesRegex(ValueError, 'frozen scientific request'):
            self.collect()
        self.workbench['flight'] = copy.deepcopy(self.flight)
        cases = self.split_batches()
        cases[1]['flight']['trajectory_quality'] += 1
        with self.assertRaisesRegex(ValueError, 'batch flight differs'):
            self.collect()

    def discovery(self, candidates):
        author = dict(self.flight, pulse=dict(mode='discover', width_us=.1, candidate_times_us=candidates))
        request_path = Path(self.preparation['input_records']['request']['path'])
        request = json.loads(request_path.read_text())
        request['flight'] = author
        write_json(request_path, request)
        self.preparation['input_records']['request'] = file_record(request_path)
        self.flight = resolve_phase_flight(author, phase='discovery')
        self.workbench['flight'] = copy.deepcopy(self.flight)
        self.workbench['phase'] = 'discovery'

    def shared_line(self, pid=1, target=1.5, actual=None):
        g = json.loads(Path(self.preparation['outputs']['frontend_geometry']['path']).read_text())['accelerator_projection']
        z = (g['repeller_front_z_mm'] + g['grid1_z_mm']) / 2
        return (f'TRACE: native_shared_time ion={pid} particle_id={pid} instance=3 '
                f'candidate_time_us={target:.17g} instrument_time_us={target if actual is None else actual:.17g} '
                f'x_mm={g["axis_x_mm"]:.17g} y_mm={g["axis_y_mm"]:.17g} z_mm={z:.17g} '
                'vx_mm_per_us=1 vy_mm_per_us=2 vz_mm_per_us=3 kinetic_energy_eV=4')

    def collection_record(self, collection, name='discovery_collection.json'):
        path = self.run / name
        write_json(path, collection)
        return file_record(path)

    def test_segmented_cut_stop_is_nonloss_and_deadline_censored_with_raw_facts(self):
        selected=copy.deepcopy(self.source[:2])
        for row,pid in zip(selected,(11,1009),strict=True): row['particle_id']=str(pid)
        source_path=self.run/'inputs/projected_source.csv'
        with source_path.open('w',encoding='utf-8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=selected[0].keys(),lineterminator='\n');writer.writeheader();writer.writerows(selected)
        source_record=file_record(source_path)
        self.preparation['outputs']['projected_source']=source_record
        provenance_path=self.run/'inputs/source_provenance.json'
        old=json.loads(provenance_path.read_text())
        clocks={key:self.preparation['input_records'][key] for key in ('clock_authority','instrument_epoch')}
        records=[dict(particle_id=int(row['particle_id']),species_id='ion',mass_amu=100.,charge_state=1,particle_weight=.5,
                      particle_birth_time_us=float(row['instrument_time_us']),lineage_birth_time_us=float(row['instrument_time_us']),parent_particle_id=None,generation=0) for row in selected]
        provenance=dict(schema_version=2,role='single_reflection_canonical_source_provenance',state_kind='source_birth',
            particle_count=2,execution_particle_ids=[11,1009],mother_particle_ids=[11,1009],mother_records=records,
            mother_fates=[dict(particle_id=pid,status='not_propagated') for pid in (11,1009)],
            clock_epoch_id=old['clock_epoch_id'],clock_authority_sha256=clocks['instrument_epoch']['sha256'],clock_records=clocks,
            consumed_plane_events=[],target_frame_id=old['target_frame_id'],state_time_semantics='original_birth_instrument_time')
        write_json(provenance_path,provenance);self.preparation['outputs']['source_provenance']=file_record(provenance_path)
        self.workbench.update(particle_count=2,source_record=source_record)
        definition=dict(schema_version=1,observation_id='cut',source_instance_id='multipole',port_id='mechanical_exit',max_records=10)
        policy=dict(schema_version=1,scope='segmented_upstream',observation_id='cut',direction='outward',occurrence=1)
        self.workbench['build_metadata']=dict(plane_observations=[definition],propagation_stop=policy,
            source_clock=dict(original_birth_times_us=[float(r['instrument_time_us']) for r in selected],absolute_deadlines_us=[float(r['instrument_time_us'])+2 for r in selected]))
        lines=[]
        for native,row in enumerate(selected,1):
            pid,t=int(row['particle_id']),float(row['instrument_time_us'])
            state=' '.join(f'{a}_mm={float(row[f"position_{a}_mm"]):.17g}' for a in 'xyz')+' '+' '.join(f'v{a}_mm_per_us={float(row[f"velocity_{a}_m_s"])/1000:.17g}' for a in 'xyz')
            lines.append(f'TRACE: source_release ion={native} particle_id={pid} instrument_time_us={t:.17g} {state}')
            if native==1:
                lines.append(f'TRACE: handoff_terminal_raw ion=1 instance=3 instrument_time_us={t:.17g} x_mm=-1 y_mm=0 z_mm=0 vx_mm_per_us=1 vy_mm_per_us=0 vz_mm_per_us=0')
                fields=dict(observation_id='cut',ion=1,particle_id=pid,direction='outward',occurrence=1,instrument_time_us=t+1,x_mm=0,y_mm=0,z_mm=0,vx_mm_per_us=1,vy_mm_per_us=0,vz_mm_per_us=0,
                    step_start_instrument_time_us=t,step_end_instrument_time_us=t+2,signed_distance_before_mm=-1,signed_distance_after_mm=1,method='accepted_step_linear_interpolation')
                for end,x in (('start',-1),('end',1)):
                    fields.update({f'step_{end}_{a}_mm':(x if a=='x' else 0) for a in 'xyz'})
                    fields.update({f'step_{end}_v{a}_mm_per_us':(1 if a=='x' else 0) for a in 'xyz'})
                lines.append('PLANE_OBSERVATION_V1: '+' '.join(f'{k}={v}' for k,v in fields.items()))
                lines.append(f'TRACE: single_flight_handoff ion=1 particle_id={pid} instrument_time_us={t+1:.17g} x_mm=0 y_mm=0 z_mm=0 vx_mm_per_us=1 vy_mm_per_us=0 vz_mm_per_us=0 step_start_instrument_time_us={t:.17g} step_end_instrument_time_us={t+2:.17g} step_start_x_mm=-1 step_end_x_mm=1')
                lines.append(f'HANDOFF_ACCEPTED_ENDPOINT_V1: observation_id=cut ion=1 particle_id={pid} direction=outward occurrence=1 event_instrument_time_us={t+1:.17g} endpoint_instrument_time_us={t+2:.17g} instance=3 x_mm=1 y_mm=0 z_mm=0 vx_mm_per_us=1 vy_mm_per_us=0 vz_mm_per_us=0 method=other_actions_accepted_step_end raw_ion_splat=0 time_step_us=2')
                lines.append(f'HANDOFF_CUT_STOP_V2: observation_id=cut ion=1 particle_id={pid} direction=outward occurrence=1 event_instrument_time_us={t+1:.17g} endpoint_instrument_time_us={t:.17g} instance=3 x_mm=-1 y_mm=0 z_mm=0 vx_mm_per_us=1 vy_mm_per_us=0 vz_mm_per_us=0 method=accepted_step_dual_boundary_stop')
            else:
                lines.append(f'TRACE: handoff_terminal_raw ion=2 instance=3 instrument_time_us={t+2:.17g} {state}')
                xyz=' '.join(f'{a}_mm={float(row[f"position_{a}_mm"]):.17g}' for a in 'xyz')
                lines.append(f'TRACE: timeout_splat ion=2 instance=3 instrument_time_us={t+2:.17g} {xyz} zmax_mm=0')
        lines.append('status,Fly completed. 2 splats')
        result=self.collect(self.write_log(lines))
        outcomes=result['census']['terminal_taxonomy']['particle_outcomes']
        self.assertEqual([r['category'] for r in outcomes],['handoff_cut_stop','censored_no_handoff_by_deadline'])
        self.assertEqual(outcomes[1]['raw_terminal_category'],'timeout_splat')
        self.assertEqual(outcomes[0]['event_instrument_time_us']-1,outcomes[0]['terminal_instrument_time_us'])
        self.assertEqual(result['plane_observations']['rows'][0]['x_mm'],0)
        self.assertEqual(result['native_terminals'][0]['x_mm'],-1)
        self.assertEqual(result['original_mother']['mother_records'],records)
        self.assertTrue(result['observation_complete'])
        self.assertEqual(result['census']['terminal_taxonomy']['role'],'segmented_upstream_terminal_taxonomy')
        self.assertTrue(compare_collections(result,self.collect())['passed'])
        # Declared diagnostic cap stays incomplete, not evidence of no crossing.
        capped=lines[:-1]+['PLANE_OBSERVATION_INCOMPLETE_V1: observation_id=cut reason=declared_record_cap',lines[-1]]
        self.assertFalse(self.collect(self.write_log(capped))['observation_complete'])
        for bad in (lines+[lines[-2]], [line.replace('endpoint_instrument_time_us=', 'bad_endpoint=') for line in lines],
                    [line.replace('particle_id=11 direction=outward','particle_id=12 direction=outward') for line in lines]):
            with self.assertRaises(ValueError): self.collect(self.write_log(bad))
        for prefix in ('HANDOFF_ACCEPTED_ENDPOINT_V1:', 'HANDOFF_CUT_STOP_V2:'):
            for before, after in (('occurrence=1', 'occurrence=2'), ('particle_id=11', 'particle_id=12'),
                                  ('x_mm=1 ', 'x_mm=2 '), ('x_mm=-1 ', 'x_mm=-2 '),
                                  ('y_mm=0 ', 'y_mm=2 '), ('z_mm=0 ', 'z_mm=2 '),
                                  ('vx_mm_per_us=1 ', 'vx_mm_per_us=2 '),
                                  ('vy_mm_per_us=0 ', 'vy_mm_per_us=2 '),
                                  ('vz_mm_per_us=0 ', 'vz_mm_per_us=2 '),
                                  ('endpoint_instrument_time_us=', 'endpoint_instrument_time_us=9'),
                                  ('instance=3', 'instance=4'),
                                  ('event_instrument_time_us=', 'event_instrument_time_us=9')):
                changed=[line.replace(before,after) if line.startswith(prefix) else line for line in lines]
                if changed != lines:
                    with self.subTest(prefix=prefix, change=before), self.assertRaises(ValueError):
                        self.collect(self.write_log(changed))
        for replacement in ('raw_ion_splat=1', 'raw_ion_splat=unknown', 'time_step_us=0'):
            changed=[line.replace('raw_ion_splat=0',replacement) if replacement.startswith('raw_') else
                     line.replace('time_step_us=2',replacement) for line in lines]
            with self.subTest(replacement=replacement), self.assertRaises(ValueError): self.collect(self.write_log(changed))
        with self.assertRaisesRegex(ValueError,'endpoint record'):
            self.collect(self.write_log([line for line in lines if not line.startswith('HANDOFF_ACCEPTED_ENDPOINT_V1:')]))
        physical=lines[:-1]+[f'TRACE: non_detector_splat ion=1 instance=3 t={float(selected[0]["instrument_time_us"])+2:.17g} x=1 y=0 z=0 zmax=0',lines[-1]]
        with self.assertRaisesRegex(ValueError,'physical terminal'): self.collect(self.write_log(physical))
        self.workbench['build_metadata']['source_clock']['absolute_deadlines_us'][1]+=1
        with self.assertRaisesRegex(ValueError,'deadline censor'): self.collect(self.write_log(lines))
        self.workbench['build_metadata']['source_clock']['absolute_deadlines_us'][1]-=1
        self.workbench['build_metadata'].pop('propagation_stop')
        with self.assertRaisesRegex(ValueError,'undeclared'): self.collect(self.write_log(lines))

    def test_real_v2_cut_wire_preserves_raw_start_and_only_original_plane_window(self):
        from msplatform.backends.simion.tracking_collection import (
            read_native_evidence, read_plane_observations, read_cut_stop_events, _validate_states)

        # Exact six wire rows from SDK14 upstream02 PID1000003, not a new native run.
        lines = ['TRACE: source_release ion=1 particle_id=1000003 instrument_time_us=0.57225318875429465 x_mm=-170.11362184380704 y_mm=-0.081660003573429091 z_mm=-18.321709055243165 vx_mm_per_us=1.9595682006629771 vy_mm_per_us=-0.10535913222607861 vz_mm_per_us=-0.091679913138928329 simion_native_kinetic_energy_eV=1.9999999107680824 source_instance=3', 'PLANE_OBSERVATION_V1: observation_id=case_c_rf_mechanical_exit_v1 ion=1 particle_id=1000003 direction=outward occurrence=1 instrument_time_us=43.073491218580166 x_mm=-89.013621843807044 y_mm=-1.0333156801556351 z_mm=-17.585043912978673 vx_mm_per_us=2.0038979786977649 vy_mm_per_us=-0.08380463899423142 vz_mm_per_us=0.30612644357667668 step_start_instrument_time_us=43.072181818181825 step_end_instrument_time_us=43.074181818181827 signed_distance_before_mm=-0.0026242189904053248 signed_distance_after_mm=0.0013840568490195437 step_start_x_mm=-89.01624606279745 step_start_y_mm=-1.033205727053351 step_start_z_mm=-17.585444887121891 step_end_x_mm=-89.012237786958025 step_end_y_mm=-1.0333736712550228 step_end_z_mm=-17.584832432530117 step_start_vx_mm_per_us=2.004906647938911 step_start_vy_mm_per_us=-0.084508696918616108 step_start_vz_mm_per_us=0.30655007652319227 step_end_vx_mm_per_us=2.0033659897224898 step_end_vy_mm_per_us=-0.083433307106186294 step_end_vz_mm_per_us=0.30590301249747215 method=accepted_step_linear_interpolation', 'TRACE: single_flight_handoff ion=1 particle_id=1000003 instrument_time_us=43.073491218580166 tof_since_pulse_us=-36.97788178241003 x_mm=-89.013621843807044 y_mm=-1.0333156801556351 z_mm=-17.585043912978673 vx_mm_per_us=2.0038979786977649 vy_mm_per_us=-0.08380463899423142 vz_mm_per_us=0.30612644357667668 kinetic_energy_eV=2.1331448179706545 survival_status=alive step_start_instrument_time_us=43.072181818181825 step_end_instrument_time_us=43.074181818181827 step_start_x_mm=-89.01624606279745 step_end_x_mm=-89.012237786958025', 'HANDOFF_ACCEPTED_ENDPOINT_V1: observation_id=case_c_rf_mechanical_exit_v1 ion=1 particle_id=1000003 direction=outward occurrence=1 event_instrument_time_us=43.073491218580166 endpoint_instrument_time_us=43.074181818181827 instance=3 x_mm=-89.012237786958025 y_mm=-1.0333736712550228 z_mm=-17.584832432530117 vx_mm_per_us=2.0033659897224898 vy_mm_per_us=-0.083433307106186294 vz_mm_per_us=0.30590301249747215 method=other_actions_accepted_step_end raw_ion_splat=0 time_step_us=0.002', 'TRACE: handoff_terminal_raw ion=1 instance=3 instrument_time_us=43.072181818181825 x_mm=-89.01624606279745 y_mm=-1.033205727053351 z_mm=-17.585444887121891 vx_mm_per_us=2.004906647938911 vy_mm_per_us=-0.084508696918616108 vz_mm_per_us=0.30655007652319227', 'HANDOFF_CUT_STOP_V2: observation_id=case_c_rf_mechanical_exit_v1 ion=1 particle_id=1000003 direction=outward occurrence=1 event_instrument_time_us=43.073491218580166 endpoint_instrument_time_us=43.072181818181825 instance=3 x_mm=-89.01624606279745 y_mm=-1.033205727053351 z_mm=-17.585444887121891 vx_mm_per_us=2.004906647938911 vy_mm_per_us=-0.084508696918616108 vz_mm_per_us=0.30655007652319227 method=accepted_step_dual_boundary_stop']
        source = {1000003: {'particle_id': 1000003, 'parent_particle_id': None, 'generation': 0, 'species_id': 'ion_100amu_charge_plus_1', 'particle_weight': 1.0, 'source_component_id': 'multipole', 'target_component_id': 'multipole', 'state_event': 'source_birth', 'frame_id': 'oatof_global', 'clock_epoch_id': 'instrument_clock_epoch_v1', 'instrument_time_us': 0.5722531887542947, 'lineage_birth_time_us': 0.5722531887542947, 'particle_birth_time_us': 0.5722531887542947, 'lineage_age_us': 0.0, 'particle_age_us': 0.0, 'last_component_elapsed_time_us': 0.0, 'mass_amu': 100.0, 'charge_state': 1, 'mass_to_charge_Th': 100.0, 'position_x_mm': -170.11362184380704, 'position_y_mm': -0.08166000357342909, 'position_z_mm': -18.321709055243165, 'velocity_x_m_s': 1959.568200662977, 'velocity_y_m_s': -105.35913222607861, 'velocity_z_m_s': -91.67991313892833, 'kinetic_energy_eV': 2.0, 'phase_reference_id': None, 'phase_rad': None}}
        log = self.write_log(lines + ['status,Fly completed. 1 splats'])
        flight = dict(pulse=dict(mode='timed', time_us=80.0513730009902, width_us=7.2727272727272725))
        terminals, locations, _, _ = read_native_evidence(log, source, flight)
        definition = dict(schema_version=1, observation_id='case_c_rf_mechanical_exit_v1',
                          source_instance_id='multipole', port_id='mechanical_exit', max_records=100000)
        observations = read_plane_observations([log], [1000003], [1], [definition])
        stops = read_cut_stop_events([log], [1000003], [1],
            dict(observation_id=definition['observation_id']), observations, terminals)
        row = next(row for row in read_native_events([log], 100., [1000003])['rows']
                   if row['event'] == 'multipole_handoff')
        window = observations['rows'][0]
        self.assertEqual(terminals[1000003]['instrument_time_us'], 43.072181818181825)
        self.assertEqual(float(stops[1000003]['accepted_endpoint']['endpoint_instrument_time_us']), 43.074181818181827)
        self.assertEqual(row['instrument_time_us'], 43.073491218580166)
        with self.assertRaisesRegex(ValueError, 'outside native lifetime'):
            _validate_states([row], source, terminals, locations, log)
        windows = {1000003: window}
        _validate_states([row], source, terminals, locations, log, cut_observation_windows=windows)
        for key in ('instrument_time_us', 'x_mm', 'y_mm', 'z_mm', 'vx_mm_per_us',
                    'vy_mm_per_us', 'vz_mm_per_us', 'step_start_instrument_time_us',
                    'step_end_instrument_time_us', 'step_start_x_mm', 'step_end_x_mm'):
            bad = dict(row, **{key: math.nextafter(row[key], math.inf)})
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'outside native lifetime'):
                _validate_states([bad], source, terminals, locations, log, cut_observation_windows=windows)
        for event in ('pre_pulse_state', 'native_shared_time', 'local_accelerator_exit'):
            with self.subTest(event=event), self.assertRaisesRegex(ValueError, 'outside native lifetime'):
                _validate_states([dict(row, event=event)], source, terminals, locations, log,
                                 cut_observation_windows=windows)
        with self.assertRaisesRegex(ValueError, 'outside native lifetime'):
            _validate_states([dict(row, particle_id=1000004)],
                {1000004: source[1000003]}, {1000004: terminals[1000003]}, {}, log,
                cut_observation_windows=windows)

    def test_modern_sparse_source_collection_binds_full_mother_weight_birth_and_both_clock_records(self):
        selected = copy.deepcopy(self.source[:2])
        for row, pid, arrival in zip(selected, (11,1009), (2.,5.), strict=True):
            row.update(particle_id=str(pid), instrument_time_us=str(arrival))
        source_path = self.run / "inputs/projected_source.csv"
        with source_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=selected[0].keys(), lineterminator="\n")
            writer.writeheader(); writer.writerows(selected)
        source_record = file_record(source_path)
        self.preparation["outputs"]["projected_source"] = source_record
        provenance_path = self.run / "inputs/source_provenance.json"
        old = json.loads(provenance_path.read_text())
        mother_ids = [11,1009,3007]
        records = [dict(particle_id=pid,species_id="ion",mass_amu=100.,charge_state=1,particle_weight=weight,
                        particle_birth_time_us=birth,lineage_birth_time_us=birth,parent_particle_id=None,generation=0)
                   for pid,weight,birth in ((11,.5,.25),(1009,2.,.75),(3007,3.,1.))]
        clocks = {key:self.preparation["input_records"][key] for key in ("clock_authority","instrument_epoch")}
        provenance = dict(schema_version=2,role="single_reflection_canonical_source_provenance",state_kind="plane_crossing",
            particle_count=2,execution_particle_ids=[11,1009],mother_particle_ids=mother_ids,mother_records=records,
            mother_fates=[dict(particle_id=pid,category="upstream_observation" if pid!=3007 else "unknown") for pid in mother_ids],
            clock_epoch_id=old["clock_epoch_id"],clock_authority_sha256=clocks["instrument_epoch"]["sha256"],
            clock_records=clocks,consumed_plane_events=[dict(particle_id=int(row["particle_id"]),observation_id="exit",direction="outward",occurrence=1,
                instrument_time_us=float(row["instrument_time_us"]),position_mm=[float(row[f"position_{a}_mm"]) for a in "xyz"]) for row in selected],
            target_frame_id=old["target_frame_id"],state_time_semantics="per_particle_arrival_instrument_time_without_original_birth_reset")
        write_json(provenance_path,provenance)
        self.preparation["outputs"]["source_provenance"] = file_record(provenance_path)
        self.workbench.update(particle_count=2,source_record=source_record)
        lines = []
        for native, row in enumerate(selected,1):
            pid,t=int(row["particle_id"]),float(row["instrument_time_us"])
            state=" ".join(f'{a}_mm={float(row[f"position_{a}_mm"]):.17g}' for a in "xyz")+" "+" ".join(f'v{a}_mm_per_us={float(row[f"velocity_{a}_m_s"])/1000:.17g}' for a in "xyz")
            xyz=" ".join(f'{a}={float(row[f"position_{a}_mm"]):.17g}' for a in "xyz")
            lines.extend((f'TRACE: source_release ion={native} particle_id={pid} instrument_time_us={t} {state}',
                          f'TRACE: handoff_terminal_raw ion={native} instance=3 instrument_time_us={t+1} {state}',
                          f'TRACE: non_detector_splat ion={native} instance=3 t={t+1} {xyz} zmax=0'))
        lines.append("status,Fly completed. 2 splats")
        result = self.collect(self.write_log(lines))
        self.assertEqual(result["schema_version"],2)
        self.assertEqual(result["role"],"single_reflection_canonical_source_collection")
        self.assertEqual([row["particle_id"] for row in result["native_terminals"]],[11,1009])
        self.assertEqual(result["original_mother"]["mother_records"],records)
        self.assertEqual(result["original_mother"]["mother_particle_ids"],mother_ids)
        changed = copy.deepcopy(result);changed["original_mother"]["mother_records"][0]["particle_weight"]=7.
        self.assertFalse(compare_collections(result,changed)["passed"])
        self.assertTrue(compare_collections(result,self.collect())["passed"])
        provenance["clock_records"]["clock_authority"] = dict(clocks["clock_authority"],sha256="0"*64)
        write_json(provenance_path,provenance)
        self.preparation["outputs"]["source_provenance"]=file_record(provenance_path)
        with self.assertRaisesRegex(ValueError,"clock record"):
            self.collect()

    def test_recorded_pre_pulse_continuation_keeps_parent_ledger_and_replay(self):
        selected = [self.source[7], self.source[6]]
        for row in selected:
            row['instrument_time_us'] = '10'
        source_path = self.run / 'inputs/projected_source.csv'
        with source_path.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=selected[0].keys(), lineterminator='\n')
            writer.writeheader(); writer.writerows(selected)
        source_record = file_record(source_path)
        self.preparation['outputs']['projected_source'] = source_record
        provenance_path = self.run / 'inputs/source_provenance.json'
        provenance = json.loads(provenance_path.read_text())
        provenance.update(source_kind='recorded_pre_pulse_state', particle_count=2,
            continued_particle_ids=[8, 7], continued_particle_count=2,
            original_mother_particle_ids=list(range(1, 101)), original_mother_particle_count=100,
            uncontinued_mother_particle_ids=[*range(1, 7), *range(9, 101)], restart_state_time_us=10.,
            original_birth_times_us={'8': 8., '7': 7.})
        write_json(provenance_path, provenance)
        self.preparation['outputs']['source_provenance'] = file_record(provenance_path)
        self.workbench.update(particle_count=2, source_record=source_record)
        self.source = selected
        self.lines = []
        for native_ion, row in enumerate(selected, 1):
            pid, t = int(row['particle_id']), float(row['instrument_time_us'])
            state = ' '.join(f'{a}_mm={float(row[f"position_{a}_mm"]):.17g}' for a in 'xyz')
            state += ' ' + ' '.join(f'v{a}_mm_per_us={float(row[f"velocity_{a}_m_s"])/1000:.17g}' for a in 'xyz')
            self.lines.extend((f'TRACE: source_release ion={native_ion} particle_id={pid} instrument_time_us={t:.17g} {state}',
                f'TRACE: handoff_terminal_raw ion={native_ion} instance=3 instrument_time_us={t+1:.17g} {state}',
                f'TRACE: non_detector_splat ion={native_ion} instance=3 t={t+1:.17g} x={float(row["position_x_mm"]):.17g} y={float(row["position_y_mm"]):.17g} z={float(row["position_z_mm"]):.17g} zmax=0'))
        self.lines.append(f'status,Fly completed. {len(selected)} splats')
        result = self.collect(self.write_log(self.lines))
        self.assertEqual(result['role'], 'single_reflection_recorded_pre_pulse_continuation_collection')
        self.assertEqual(result['continuation']['continued_particle_ids'], [8, 7])
        self.assertEqual(result['continuation']['original_mother_particle_count'], 100)
        self.assertEqual(len(result['native_terminals']), 2)
        replay = self.collect(self.write_log(self.lines, 'replay.stdout.log'))
        comparison = compare_collections(result, replay)
        self.assertTrue(comparison['passed'])
        self.assertEqual(comparison['continued_count'], 2)
        self.split_batches()
        batched = self.collect()
        self.assertEqual([row['particle_id'] for row in batched['native_terminals']],[8,7])
        self.assertEqual(batched['continuation'],result['continuation'])
        self.discovery([10.5])
        for case in self.workbench['batches']:
            case['flight'] = copy.deepcopy(self.workbench['flight'])
            path = Path(case['stdout'])
            lines = path.read_text().splitlines()
            sample = self.shared_line(pid=case['expected_particle_ids'][0],target=10.5)
            lines.insert(1,re.sub(r'\bion=\d+','ion=1',sample))
            path.write_text('\n'.join(lines)+'\n')
        discovery = self.collect()
        decision = select_pulse(self.preparation,self.run,self.collection_record(discovery))
        self.assertEqual(decision['schema_version'],2)
        self.assertEqual(decision['selection']['execution_cohort_count'],2)
        self.assertEqual(discovery['continuation']['original_mother_particle_count'],100)

    def test_discovery_collects_actual_shared_states_for_complete_mother(self):
        candidates = [float(row['instrument_time_us']) + .5 for row in self.source]
        self.discovery(candidates)
        shared = [self.shared_line(pid, t) for pid, t in enumerate(candidates, 1)]
        result = self.collect(self.write_log([*shared, *self.lines]))
        self.assertEqual(len(result['native_shared_states']), 100)
        self.assertEqual(len(result['native_terminals']), 100)
        self.assertEqual(result['census']['census']['source_release'], 100)
        for pid, row in enumerate(result['native_shared_states'], 1):
            self.assertEqual(row['particle_id'], pid)
            self.assertEqual(row['candidate_time_us'], candidates[pid-1])
            self.assertEqual(row['instrument_time_us'], candidates[pid-1])
            self.assertEqual([row[f'v{a}_mm_per_us'] for a in 'xyz'], [1., 2., 3.])
            self.assertEqual(row['kinetic_energy_eV'], 4.)
        record = self.collection_record(result)
        self.log.unlink()  # Selection consumes the verified collection, not raw log again.
        decision = select_pulse(self.preparation, self.run, record)
        self.assertEqual(decision['status'], 'success')
        self.assertEqual(decision['input_records']['collection'], record)

    def test_discovery_preserves_actual_time_with_only_serialization_allowance(self):
        self.discovery([1.5])
        actual = 1.5 + 16 * math.ulp(1.5)
        result = self.collect(self.write_log([self.shared_line(actual=actual), *self.lines]))
        row = result['native_shared_states'][0]
        self.assertEqual(row['candidate_time_us'], 1.5)
        self.assertEqual(row['instrument_time_us'], actual)
        self.assertNotEqual(row['candidate_time_us'], row['instrument_time_us'])
        for line in (self.shared_line(actual=1.5 + 64 * math.ulp(1.5)),
                     self.shared_line(target=1.5 + math.ulp(1.5))):
            with self.subTest(line=line), self.assertRaisesRegex(ValueError, 'shared-time'):
                self.collect(self.write_log([line, *self.lines]))

    def test_discovery_rejects_duplicate_unknown_malformed_and_outside_lifetime(self):
        self.discovery([.5, 1.5, 2.5])
        valid = self.shared_line()
        cases = {
            'duplicate': [valid, valid],
            'unknown_id': [self.shared_line(pid=101)],
            'wrong_id': [valid.replace('particle_id=1 ', 'particle_id=2 ')],
            'nonfinite': [valid.replace('vx_mm_per_us=1 ', 'vx_mm_per_us=nan ')],
            'missing_state': [valid.replace(' vy_mm_per_us=2', '')],
            'duplicate_field': [valid + ' instance=3'],
            'before_birth': [self.shared_line(target=.5)],
            'after_terminal': [self.shared_line(target=2.5)],
        }
        for name, extra in cases.items():
            with self.subTest(case=name), self.assertRaises(ValueError):
                self.collect(self.write_log([*extra, *self.lines]))

    def test_discovery_missing_observation_is_unsupported_and_binding_mismatch_rejected(self):
        self.discovery([1.5])
        collection = self.collect()
        self.assertEqual(collection['native_shared_states'], [])
        record = self.collection_record(collection)
        decision = select_pulse(self.preparation, self.run, record)
        self.assertEqual(decision['status'], 'no_supported_candidate')
        self.assertNotIn('actual_pulse_time_us', decision)
        tally = decision['selection']['candidate_status_counts'][0]
        self.assertEqual(tally['numerical_unsupported'], 1)
        self.assertEqual(tally['not_born'], 99)
        for key in ('request_record', 'geometry_record', 'field_design_record', 'source_record', 'phase', 'native_complete', 'flight'):
            changed = copy.deepcopy(collection)
            if key.endswith('_record'):
                changed[key]['bytes'] += 1
            elif key == 'phase':
                changed[key] = 'full_instrument'
            elif key == 'flight':
                changed[key]['observation_times_us'] = [1.6]
            else:
                changed[key] = False
            with self.subTest(key=key), self.assertRaises(ValueError):
                select_pulse(self.preparation, self.run, self.collection_record(changed))
        outside = self.root / 'outside_collection.json'
        write_json(outside, collection)
        with self.assertRaisesRegex(ValueError, 'escapes'):
            select_pulse(self.preparation, self.run, file_record(outside))

    def test_discovery_cli_writes_negative_decision_before_nonzero_exit(self):
        self.discovery([1.5])
        record = self.collection_record(self.collect())
        preparation, workbench = self.run/'preparation.json', self.run/'workbench.json'
        write_json(preparation, self.preparation)
        write_json(workbench, self.workbench)
        output = self.run/'results/discovery'
        command = [sys.executable, '-m', 'msplatform.workflows.single_reflection_flight.collect',
                   '--preparation', str(preparation), '--workbench', str(workbench), '--run', str(self.run),
                   '--output', str(output), '--select-pulse', '--collection-record', json.dumps(record)]
        result = subprocess.run(command, cwd=ROOT, env={**os.environ, "PYTHONPATH": os.pathsep.join(python_import_roots(ROOT)), "PYTHONNOUSERSITE": "1"}, capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(result.returncode, 1, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertFalse(receipt['passed'])
        decision_path = output/'pulse_decision.json'
        self.assertEqual(receipt['output_records']['pulse_decision.json'], file_record(decision_path))
        decision = json.loads(decision_path.read_text())
        self.assertEqual(decision['status'], 'no_supported_candidate')
        self.assertNotIn('actual_pulse_time_us', decision)

    def test_complete_100_mother_held_off_zero_detector_and_replay(self):
        original = (self.run / 'inputs/projected_source.csv').read_bytes()
        baseline = self.collect()
        replay = self.collect(self.write_log(['native header', *self.lines], 'replay.stdout.log'))
        self.assertTrue(compare_collections(baseline, replay)['passed'])
        self.assertEqual(baseline['census']['census']['source_release'], 100)
        self.assertEqual(baseline['census']['census']['detector_crossing'], 0)
        self.assertEqual(len(baseline['native_terminals']), 100)
        self.assertIsNone(baseline['census']['pulse_effective_time_us'])
        self.assertNotIn('pulse_effective_peak', baseline['census'])
        self.assertEqual((self.run / 'inputs/projected_source.csv').read_bytes(), original)

    def test_timed_all_lost_before_pulse_still_has_complete_census(self):
        self.flight['pulse'] = dict(mode='timed', time_us=200., width_us=2.)
        self.workbench['flight'] = copy.deepcopy(self.flight)
        path = Path(self.preparation['input_records']['request']['path'])
        request = json.loads(path.read_text())
        request['flight'] = self.flight
        write_json(path, request)
        self.preparation['input_records']['request'] = file_record(path)
        result = self.collect()
        self.assertEqual(result['census']['pulse_effective_time_us'], 200.)
        self.assertEqual(result['census']['census']['pre_pulse_state'], 0)
        self.assertEqual(result['census']['terminal_taxonomy']['terminal_outcome_count'], 100)

    def test_timed_replay_compares_actual_pulse_state_and_rejects_duplicate(self):
        self.flight['pulse'] = dict(mode='timed', time_us=1.5, width_us=.1)
        self.workbench['flight'] = copy.deepcopy(self.flight)
        path = Path(self.preparation['input_records']['request']['path'])
        request = json.loads(path.read_text())
        request['flight'] = self.flight
        write_json(path, request)
        self.preparation['input_records']['request'] = file_record(path)
        pulse = 'TRACE: handoff_pulse_on ion=1 instrument_time_us=1.5 x_mm=0 y_mm=0 z_mm=0 vx_mm_per_us=1 vy_mm_per_us=0 vz_mm_per_us=0'
        baseline = self.collect(self.write_log([self.lines[0], pulse, *self.lines[1:]], 'pulse.log'))
        replay = self.collect(self.write_log([self.lines[0], pulse.replace('x_mm=0 ', 'x_mm=0.1 '), *self.lines[1:]], 'pulse_changed.log'))
        self.assertFalse(compare_collections(baseline, replay)['passed'])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.collect(self.write_log([self.lines[0], pulse, pulse, *self.lines[1:]], 'pulse_duplicate.log'))

    def test_missing_duplicate_drifting_birth_terminal_and_completion_rejected(self):
        cases = {
            'birth_missing': self.lines[1:],
            'birth_duplicate': [self.lines[0], *self.lines],
            'birth_clock': [self.lines[0].replace('instrument_time_us=1 ', 'instrument_time_us=1.01 '), *self.lines[1:]],
            'terminal_missing': [self.lines[0], *self.lines[2:]],
            'terminal_duplicate': [self.lines[0], self.lines[1], *self.lines[1:]],
            'lifetime': [self.lines[0], self.lines[1].replace('instrument_time_us=2 ', 'instrument_time_us=0 '), *self.lines[2:]],
            'census_missing': [*self.lines[:2], *self.lines[3:]],
            'native_incomplete': self.lines[:-1],
            'heldoff_pulse': [*self.lines, 'TRACE: handoff_pulse_on ion=1 instrument_time_us=1'],
        }
        for case, lines in cases.items():
            with self.subTest(case=case), self.assertRaises(ValueError):
                self.collect(self.write_log(lines, case + '.log'))

    def test_replay_detects_per_id_terminal_and_controls_drift(self):
        baseline = self.collect()
        changed = list(self.lines)
        changed[1] = changed[1].replace('instance=3', 'instance=2')
        changed[2] = changed[2].replace('instance=3', 'instance=2')
        replay = self.collect(self.write_log(changed, 'different.log'))
        self.assertFalse(compare_collections(baseline, replay)['passed'])
        Path(self.workbench['outputs']['program']['path']).write_text('CHANGED', encoding='utf-8')
        with self.assertRaises(Exception):
            self.collect()

    def test_detector_projection_is_distinct_and_serialization_allowance_is_bounded(self):
        lines = list(self.lines)
        lines[1] = lines[1].replace('instance=3', 'instance=4')
        lines[2] = 'TRACE: detector_crossing ion=1 t=1.25 x=0 y=0 z=0 r=0 zmax=1'
        baseline = self.collect(self.write_log(lines, 'detected.log'))
        self.assertEqual(baseline['census']['census']['detector_crossing'], 1)
        self.assertEqual(baseline['native_terminals'][0]['instrument_time_us'], 2.)
        end = baseline['census']['terminal_taxonomy']['particle_outcomes'][0]
        self.assertEqual(end['terminal_instrument_time_us'], 2.25)
        self.assertNotIn('vx_mm_per_us', end)
        replay = copy.deepcopy(baseline)
        value = replay['native_terminals'][0]['vx_mm_per_us']
        replay['native_terminals'][0]['vx_mm_per_us'] = value + math.ulp(max(1., abs(value)))
        self.assertTrue(compare_collections(baseline, replay)['passed'])
        replay['native_terminals'][0]['vx_mm_per_us'] = value + 128 * math.ulp(max(1., abs(value)))
        self.assertFalse(compare_collections(baseline, replay)['passed'])

    def test_three_x_observations_keep_actual_brackets_and_replay_events(self):
        source = self.source[0]
        t = float(source['instrument_time_us'])
        extras = []
        for offset, event in enumerate(('single_flight_handoff', 'accelerator_sidewall_inner_forward', 'accelerator_axis_forward'), 1):
            extras.append(f'TRACE: {event} ion=1 particle_id=1 instrument_time_us={t+offset/4:.17g} '
                f'x_mm={offset/4} y_mm=0 z_mm=0 vx_mm_per_us=1 vy_mm_per_us=0 vz_mm_per_us=0 '
                f'step_start_instrument_time_us={t:.17g} step_end_instrument_time_us={t+1:.17g} step_start_x_mm=0 step_end_x_mm=1')
        baseline = self.collect(self.write_log([self.lines[0], *extras, *self.lines[1:]], 'crossings.log'))
        self.assertEqual(baseline['census']['census']['accelerator_axis_forward'], 1)
        crossing = next(row for row in baseline['canonical_events'] if row['event'] == 'multipole_handoff')
        self.assertEqual(crossing['step_end_x_mm'], 1.)
        comparison = compare_collections(baseline, self.collect())
        self.assertFalse(comparison['passed'])
        with self.assertRaisesRegex(ValueError, 'bracket'):
            self.collect(self.write_log([self.lines[0], extras[0].split(' step_start_')[0], *self.lines[1:]], 'unbracketed.log'))

    def test_cli_existing_output_directory_and_saved_replay_evidence(self):
        preparation, workbench = self.run / 'preparation.json', self.run / 'workbench.json'
        write_json(preparation, self.preparation)
        write_json(workbench, self.workbench)
        output = self.run / 'results/single_reflection/flight'
        output.mkdir(parents=True)
        existing = output / 'native.stderr.log'
        existing.write_text('original evidence', encoding='utf-8')
        command = [sys.executable, '-m', 'msplatform.workflows.single_reflection_flight.collect',
            '--preparation', str(preparation), '--workbench', str(workbench), '--run', str(self.run),
            '--log', str(self.log), '--output', str(output)]
        result = subprocess.run(command, cwd=ROOT, env={**os.environ, "PYTHONPATH": os.pathsep.join(python_import_roots(ROOT)), "PYTHONNOUSERSITE": "1"}, capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['passed'])
        baseline_record=json.loads(result.stdout)['output_records']['collection.json']
        replay_log=self.run/'replay.stdout.log'
        replay_log.write_bytes(self.log.read_bytes())
        self.log.unlink()  # Replay must consume the first collection, not parse the old raw log again.
        command[command.index('--log')+1]=str(replay_log)
        replay = subprocess.run([*command, '--baseline-record', json.dumps(baseline_record)], cwd=ROOT, env={**os.environ, "PYTHONPATH": os.pathsep.join(python_import_roots(ROOT)), "PYTHONNOUSERSITE": "1"},
            capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(replay.returncode, 0, replay.stderr)
        self.assertEqual(existing.read_text(), 'original evidence')
        self.assertTrue((output / 'replay_comparison.json').is_file())
        baseline_record['bytes']+=1
        command[command.index('--output')+1]=str(output/'bad_baseline')
        rejected=subprocess.run([*command,'--baseline-record',json.dumps(baseline_record)],cwd=ROOT, env={**os.environ, "PYTHONPATH": os.pathsep.join(python_import_roots(ROOT)), "PYTHONNOUSERSITE": "1"},
            capture_output=True,text=True,timeout=60,check=False)
        self.assertNotEqual(rejected.returncode,0)
        self.assertIn('baseline collection',rejected.stderr)



class CanonicalCensusTests(unittest.TestCase):
    def test_census_has_no_randomness_requirement_or_peak_computation(self):
        text = "\n".join([
            "TRACE: source_release ion=1 particle_id=1 instrument_time_us=1 x_mm=0 y_mm=0 z_mm=0 vx_mm_per_us=0 vy_mm_per_us=0 vz_mm_per_us=1",
            "TRACE: accelerator_sidewall_inner_forward ion=1 particle_id=1 instrument_time_us=1.25 x_mm=0.25 y_mm=0 z_mm=0 vx_mm_per_us=1 vy_mm_per_us=0 vz_mm_per_us=0 step_start_instrument_time_us=1 step_end_instrument_time_us=2 step_start_x_mm=0 step_end_x_mm=1",
            "TRACE: accelerator_axis_forward ion=1 particle_id=1 instrument_time_us=1.5 x_mm=0.5 y_mm=0 z_mm=0 vx_mm_per_us=1 vy_mm_per_us=0 vz_mm_per_us=0 step_start_instrument_time_us=1 step_end_instrument_time_us=2 step_start_x_mm=0 step_end_x_mm=1",
            "TRACE: non_detector_splat ion=1 instance=3 t=2 x=1 y=0 z=0 zmax=0",
        ])
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "native.log"
            log.write_text(text, encoding="utf-8")
            for pulse in (None, 10.0):
                evidence = read_native_events([log], 100., [1])
                summary = canonical_census(evidence, [1], pulse_time_us=pulse)
                self.assertEqual(summary["census"]["detector_crossing"], 0)
                self.assertFalse(summary["peak_or_bootstrap_computed"])
                self.assertEqual(summary["terminal_taxonomy"]["terminal_outcome_count"], 1)
                self.assertEqual(evidence['rows'][1]["step_start_instrument_time_us"], 1.)
                self.assertEqual(summary["census"]["accelerator_axis_forward"], 1)


class CanonicalPlaneHandoffTests(unittest.TestCase):
    def oracle(self):
        from msplatform.assembly.handoff import HandoffClock, HandoffMother
        from msplatform.contracts.clock import ClockIdentity
        from msplatform.contracts.rigid_transform import RigidTransform
        records = {11:dict(parent_particle_id=None, generation=0, species_id="ion", mass_amu=100., charge_state=1,
                       particle_weight=.5, particle_birth_time_us=.25, lineage_birth_time_us=.25, source_component_entry_time_us=.25),
                   1009:dict(parent_particle_id=None, generation=0, species_id="ion", mass_amu=100., charge_state=1,
                       particle_weight=2., particle_birth_time_us=.75, lineage_birth_time_us=.75, source_component_entry_time_us=.75)}
        mother = HandoffMother(records, [dict(particle_id=pid, category="observed_upstream") for pid in records])
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        epoch = root / "instrument_epoch.json"
        epoch.write_text('{"epoch_us":0}\n', encoding="utf-8")
        authority = root / "clock_authority.json"
        authority.write_text(json.dumps({"authority":file_record(epoch)}), encoding="utf-8")
        self.clock_records = dict(clock_authority=file_record(authority), instrument_epoch=file_record(epoch))
        identity = ClockIdentity("epoch", self.clock_records["instrument_epoch"]["sha256"])
        transform = RigidTransform.from_contract(dict(schema_version=1,role="rigid_transform",from_frame_id="world",to_frame_id="world",rotation=[[1,0,0],[0,1,0],[0,0,1]],translation_mm=[0,0,0]))
        definition = dict(schema_version=1, observation_id="exit", source_instance_id="rf", port_id="mechanical_exit", max_records=10)
        rows = []
        for pid, t in ((11,2.),(1009,5.)):
            rows.append(dict(particle_id=pid, observation_id="exit", direction="outward", occurrence=1,
                instrument_time_us=t, x_mm=0., y_mm=2., z_mm=3., vx_mm_per_us=1.,vy_mm_per_us=0.,vz_mm_per_us=0.,
                method="accepted_step_linear_interpolation", step_start_instrument_time_us=t-.1,step_end_instrument_time_us=t+.1,
                signed_distance_before_mm=-.1,signed_distance_after_mm=.1))
        table = dict(schema_version=1,role="single_reflection_plane_observations",status="complete",definitions=[definition],rows=rows)
        self.consumed_events = [dict(particle_id=row["particle_id"],observation_id="exit",direction="outward",occurrence=1,
            instrument_time_us=row["instrument_time_us"],position_mm=[row[a+"_mm"] for a in "xyz"]) for row in rows]
        return table, dict(observation_id="exit",direction="outward",occurrence=1,source_instance_id="rf",target_instance_id="tof",
            frame_id="world",transform=transform,clock=HandoffClock(identity,identity),mother=mother,producer_completed=True)

    def test_sparse_weighted_non_simultaneous_plane_states_preserve_original_mother(self):
        from msplatform.backends.simion.source import prepare_plane_handoff_states, project_handoff_source, render_restart_fly2, execution_particle_ids
        table, args = self.oracle()
        original = copy.deepcopy(args["mother"])
        # Later/other-direction events are retained and do not replace the declared occurrence.
        table["rows"].append(dict(table["rows"][0], direction="inward", occurrence=1, instrument_time_us=3.))
        table["rows"].append(dict(table["rows"][0], occurrence=2, instrument_time_us=4.))
        result = prepare_plane_handoff_states(table, **args)
        rows, provenance = project_handoff_source(result, clock_records=self.clock_records, consumed_plane_events=self.consumed_events)
        self.assertEqual(execution_particle_ids(provenance,999), [11,1009])
        self.assertEqual([float(row["instrument_time_us"]) for row in rows], [2.,5.])
        self.assertEqual([row["particle_birth_time_us"] for row in result.rows], [.25,.75])
        self.assertEqual([row["particle_age_us"] for row in result.rows], [1.75,4.25])
        self.assertEqual([row["particle_weight"] for row in result.rows], [.5,2.])
        self.assertEqual([row["velocity_x_m_s"] for row in result.rows], [1000.,1000.])
        self.assertEqual(args["mother"], original)
        self.assertEqual(provenance["mother_particle_ids"], [11,1009])
        self.assertEqual(render_restart_fly2(rows).count("tob = 0"), 2)

    def test_source_birth_uses_same_projector_without_fake_handoff_or_reindex(self):
        from msplatform.backends.simion.source import prepare_plane_handoff_states, project_source_states, GLOBAL_COLUMNS
        table, args = self.oracle()
        selected = prepare_plane_handoff_states(table, **args)
        states = copy.deepcopy(list(selected.rows))
        for row in states:
            row.update(instrument_time_us=row["particle_birth_time_us"],particle_age_us=0.,lineage_age_us=0.,
                       last_component_elapsed_time_us=0.,state_event="source_birth")
        projected, provenance = project_source_states(states,mother=args["mother"],clock=args["clock"].target,
            state_kind="source_birth",clock_records=self.clock_records)
        self.assertEqual(list(projected[0]),GLOBAL_COLUMNS)
        self.assertEqual([float(row["instrument_time_us"]) for row in projected],[.25,.75])
        self.assertEqual(provenance["execution_particle_ids"],[11,1009])
        self.assertEqual(provenance["state_kind"],"source_birth")
        with self.assertRaises(ValueError):
            project_source_states(states[:1],mother=args["mother"],clock=args["clock"].target,state_kind="source_birth",clock_records=self.clock_records)
        with self.assertRaises(ValueError):
            project_source_states(selected.rows,mother=args["mother"],clock=args["clock"].target,state_kind="source_birth",clock_records=self.clock_records)

    def test_zero_transfer_and_invalid_completion_occurrence_clock_or_id_fail_closed(self):
        from msplatform.backends.simion.source import prepare_plane_handoff_states, project_handoff_source, execution_particle_ids, validate_native_particle_ids
        table, args = self.oracle()
        empty = prepare_plane_handoff_states(dict(table,rows=[]), **args)
        rows, provenance = project_handoff_source(empty, clock_records=self.clock_records)
        self.assertEqual(rows, [])
        self.assertEqual(provenance["mother_particle_ids"], [11,1009])
        self.assertEqual(execution_particle_ids(provenance,0), [])
        for bad in (dict(table,status="incomplete"), dict(table,rows=[table["rows"][0],table["rows"][0]])):
            with self.assertRaises(ValueError): prepare_plane_handoff_states(bad, **args)
        with self.assertRaises(ValueError): prepare_plane_handoff_states(table, **dict(args,producer_completed=False))
        self.assertEqual(validate_native_particle_ids([11,2**53-1]), [11,2**53-1])
        for ids in ([2**53], [2**53+1], [True], [11,11], [1.5]):
            with self.subTest(ids=ids), self.assertRaises(ValueError): validate_native_particle_ids(ids)
        broken = dict(provenance);broken.pop("mother_records")
        with self.assertRaises(ValueError): execution_particle_ids(broken,0)


if __name__ == '__main__':
    unittest.main()
