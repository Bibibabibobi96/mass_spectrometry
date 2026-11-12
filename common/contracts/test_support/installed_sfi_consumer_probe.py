"""Installed SFI source-to-public-track wiring, with an inert field and owner."""
import json
from pathlib import Path
import sys
import sysconfig
from types import SimpleNamespace
from unittest.mock import patch


def run(preparation, run_directory, expected_ids, arm, timer, blocked_roots):
    """Exercise actual installed binding and public planning without native actions."""
    from msplatform.backends.simion.compiler import compile_geometry
    from msplatform.backends.simion.model import PHYSICS, compile_prepared_model, project_resolved_drive
    from msplatform.execution.terminal_publication import publish_terminal_state
    from msplatform.io.manifest_records import file_record
    from msplatform.workflows.single_reflection_flight import recorded_birth

    with timer('sfi_saved_field_consumer', str(arm)):
        purelib = Path(sysconfig.get_paths()['purelib']).resolve()
        assert Path(recorded_birth.__file__).resolve() == purelib/'msplatform/workflows/single_reflection_flight/recorded_birth.py'
        run = Path(run_directory)
        request = json.loads((run/'inputs/request.json').read_text(encoding='utf-8-sig'))
        assert request['source']['kind'] == 'recorded_birth' and request['flight']['pulse']['mode'] == 'timed'
        source_records = {**preparation['input_records'], **preparation['outputs']}
        source_manifest = dict(schema_version=2, role='simulation_run_manifest', run_id='installed-sfi-fixture',
            project='instrument_assembly', mode='single_reflection_flight', status='success', inputs=source_records, outputs=[])
        publish_terminal_state(run, {'status':'success'}, source_manifest)
        producer = file_record(run/'run_manifest.json')
        components = {name:json.loads(Path(preparation['input_records']['instance_design__'+name]['path']).read_text())
                      for name in request['providers']['instances']}
        assembly = json.loads((run/'inputs/composition_plan.json').read_text())
        domains = {name:{key:value for key,value in domain.items() if key != 'refine_convergence_v'}
                   for name,domain in request['numerics']['frontend_domains'].items()}
        tof = components['oatof']
        compiled = compile_geometry({'composition_plan':assembly, 'components_resolved':components},
            numerics=dict(frontend_domains=domains, geometry_build=tof['simion_geometry_build'],
                detector_marker=tof['simion_detector_marker'],
                electrode_group_native_ids={name:value['electrode_bindings']
                                            for name,value in request['providers']['instances'].items()}))
        # Exercise the installed physical detector compiler and the actual source-free
        # native plan. The owner and all native operations remain uncalled here.
        import hashlib
        import subprocess
        from msplatform.backends.simion import downstream as detector_compiler, native_plans as detector_plans, tof_geometry as detector_geometry
        from msplatform.backends.simion.resources import gem_template_path, gem_template_text, native_resource_path, structural_seed_path
        from msplatform.execution.resources import resource_path
        from msplatform.io.manifest_records import verify_record
        for module, relative in ((detector_compiler, 'downstream.py'), (detector_plans, 'native_plans.py'),
                                 (detector_geometry, 'tof_geometry.py')):
            assert Path(module.__file__).resolve() == purelib / 'msplatform/backends/simion' / relative
        detector_spec = next(row for row in compiled.downstream_specs if row['role'] == 'detector')
        body = detector_spec['physical_detector']
        marker = tof['simion_detector_marker']
        assert body['radius_mm'] == tof['geometry_mm']['detector_radius'] == 40.
        assert body['height_mm'] == tof['geometry_mm']['detector_thickness'] == 1.
        assert marker['active_plane_z_mm'] == tof['geometry_mm']['detector_z'] == 0.
        assert marker['absorber_thickness_mm'] == .1 and marker['capture_depth_mm'] == .02
        row = next(row for row in compiled.frontend_geometry['downstream_pa_instances'] if row['role'] == 'detector')
        assert row['physical_detector'] == body and row['numerical_marker'] == marker
        assert row['nz'] == body['back_cells'] + body['front_cells'] + 1
        assert row['z_mm'] + body['back_cells'] * marker['cell_z_mm'] == marker['active_plane_z_mm']
        template = gem_template_path('detector')
        assert template.resolve().is_relative_to(purelib)
        assert gem_template_text('detector') == detector_spec['template_text']
        assert 'cylinder(0,0,0,$(radius),,$(absorber_thickness))' in detector_spec['template_text']
        count = 4 + int('entrance_refinement' in compiled.frontend_geometry['numerical_domains'])
        seed = structural_seed_path(count)
        plan_root = run.parent / (run.name + '-detector-plan-only')
        with patch('subprocess.Popen', side_effect=AssertionError('geometry planning started a process')):
            plan = detector_plans.plan_geometry_build(compiled, run_directory=plan_root,
                seed_record=file_record(seed), native_path_resource=resource_path('native_run_path.lua'))
        assert not plan_root.exists()
        operation = next(item for item in plan.operations if item['operation_id'] == 'geometry_detector')
        assert operation['arguments'][-1] == 'geometry-only'
        assert all('refine' not in item['arguments'] and 'fly' not in item['arguments'] for item in plan.operations)
        projection = plan.materializations[str(plan_root / 'inputs/downstream_projection.lua')]
        assert 'detector_body' in projection and 'detector_marker' in projection
        original = template.read_bytes()
        record = file_record(template)
        try:
            template.write_bytes(bytes([original[0] ^ 1]) + original[1:])
            try:
                verify_record('installed detector GEM', record)
            except AssertionError as error:
                assert 'SHA-256 changed' in str(error) and str(template) in str(error)
            else:
                raise AssertionError('tampered installed detector GEM accepted')
            template.unlink()
            try:
                gem_template_text('detector')
            except FileNotFoundError as error:
                assert 'installed SIMION GEM resource is missing: oatof_detector_ground.gem' in str(error)
            else:
                raise AssertionError('missing installed detector GEM fell back')
        finally:
            template.write_bytes(original)
        assert template.read_bytes() == original and hashlib.sha256(original).hexdigest() == hashlib.sha256(template.read_bytes()).hexdigest()
        builder = native_resource_path('build_detector_variant.lua')
        assert builder.resolve().is_relative_to(purelib)
        builder_original = builder.read_bytes()
        try:
            builder.unlink()
            try:
                detector_plans.plan_geometry_build(compiled, run_directory=plan_root,
                    seed_record=file_record(seed), native_path_resource=resource_path('native_run_path.lua'))
            except FileNotFoundError as error:
                assert 'installed SIMION native resource is missing: build_detector_variant.lua' in str(error)
            else:
                raise AssertionError('missing installed detector builder accepted')
        finally:
            builder.write_bytes(builder_original)
        assert builder.read_bytes() == builder_original
        # A fresh isolated process must not recover a physically absent owner from the checkout.
        owner_path = Path(detector_compiler.__file__).resolve()
        owner_original = owner_path.read_bytes()
        try:
            owner_path.unlink()
            code = """import importlib,importlib.abc,json,os,pathlib,sys
blocked=[pathlib.Path(p).resolve() for p in json.loads(sys.argv[1])]
def audit(event,args):
 if event=='open' and args and isinstance(args[0],(str,bytes)):
  p=pathlib.Path(os.fsdecode(args[0])).resolve()
  if any(p.is_relative_to(root) for root in blocked): raise AssertionError('author read: '+str(p))
sys.addaudithook(audit)
class Deny(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'common','projects','integrations'}: raise AssertionError('author import: '+fullname)
sys.meta_path.insert(0,Deny())
try:
 importlib.import_module('msplatform.backends.simion.downstream')
except ModuleNotFoundError as e:
 assert e.name == 'msplatform.backends.simion.downstream', repr(e)
 print('MISSING_DETECTOR_OWNER=PASS')
else:
 raise AssertionError('missing owner imported')
"""
            child = subprocess.run([sys.executable, '-I', '-X', 'utf8', '-B', '-c', code, json.dumps([str(p) for p in blocked_roots])], cwd=run.parent,
                capture_output=True, text=True, encoding='utf-8', timeout=30, check=False)
            assert child.returncode == 0 and 'MISSING_DETECTOR_OWNER=PASS' in child.stdout, (child.returncode, child.stdout, child.stderr)
        finally:
            owner_path.write_bytes(owner_original)
        assert owner_path.read_bytes() == owner_original
        epoch = preparation['input_records']['instrument_epoch']
        drive = project_resolved_drive(compiled, components, pulse=request['flight']['pulse'],
            clock=dict(clock_epoch_id='instrument_clock_epoch_v1', authority_sha256=epoch['sha256'],
                       phase_reference_instrument_time_us=0.))
        model = compile_prepared_model(compiled, components, drive=drive, physics=PHYSICS)
        field_run = run.parent/(run.name+'-inert-field')
        field_run.mkdir()
        model_path = field_run/'compiled_model.json'
        model_path.write_text(json.dumps(model.document), encoding='utf-8')
        data = {'compiled_model':file_record(model_path), 'instrument_epoch':epoch,
                'clock_authority':preparation['input_records']['clock_authority']}
        metadata = dict(backend='simion', field_status='available', source_status='not_requested',
            model_identity_sha256=model.document['model_identity_sha256'], clock=model.document['drive']['clock'],
            fixture_only=True)
        field_manifest = dict(schema_version=2, role='simulation_run_manifest', run_id='inert-field',
            project='instrument_assembly', mode='software-fixture', status='success', inputs=data, outputs=[],
            products={'fields':dict(schema_version=1,kind='field_bundle',status='complete',metadata=metadata,data=data)})
        publish_terminal_state(field_run, {'status':'success'}, field_manifest)
        field_ref = {'manifest':file_record(field_run/'run_manifest.json'), 'product_id':'fields'}
        context = SimpleNamespace(tools={'simion':Path(sys.executable)})
        stage = {'limits':{'transient_run_directory_bytes':1}, 'artifact_retention':{}}
        with patch('msplatform.execution.stage_policy.read_stage_policy', return_value=(stage, {})), \
             patch('msplatform.execution.owner.run_managed_stage', return_value={'manifest':{}}) as owner, \
             patch('msplatform.results.artifacts.open_artifact', return_value='installed-public-track'):
            result = recorded_birth.track_recorded_birth(preparation_manifest=producer, fields=field_ref,
                species_id='installed_fixture_species', expected_particle_ids=[int(value) for value in expected_ids],
                observations={'plane_observations':[]}, context=context)
        assert result == 'installed-public-track'
        call = owner.call_args.kwargs
        assert call['payload']['propagation']['scope'] == 'continuous_assembly'
        assert len(call['payload']['particles']['mother']['records']) == len(expected_ids)
        assert {'manifest_record':producer} in call['source_references']
        assert 'source_provenance' in call['payload']['birth_source_authority']['records']
        # Both corruptions are applied only to this private fixture and always restored.
        source_path = Path(preparation['input_records']['particle_source']['path'])
        with patch('msplatform.execution.owner.run_managed_stage') as negative_owner:
            for label, path in (('particle_source', source_path), ('compiled_model', model_path)):
                original = path.read_bytes()
                negative_owner.reset_mock()
                try:
                    path.write_bytes(original + b'\n')
                    try:
                        recorded_birth.track_recorded_birth(preparation_manifest=producer, fields=field_ref,
                            species_id='installed_fixture_species', expected_particle_ids=[int(value) for value in expected_ids],
                            observations={'plane_observations':[]}, context=context)
                    except AssertionError as error:
                        assert 'byte count changed' in str(error) and str(path) in str(error), (label, str(error))
                    else:
                        raise AssertionError('tampered ' + label + ' accepted')
                    negative_owner.assert_not_called()
                finally:
                    path.write_bytes(original)
                assert path.read_bytes() == original
        assert not (run/'simion').exists()
