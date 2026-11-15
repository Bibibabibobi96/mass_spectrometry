"""Neutral producer proof and isolated provider-free static projection."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from common.contracts import test_static_world_model as fixture
from msplatform.backends.simion import assembly_geometry, generic_geometry, model


class NeutralColdProjectionTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.StaticWorldModelTests(methodName='runTest')
        self.case.setUp()
        self.compiled = self.case.compiled
        self.sealed = generic_geometry.seal_neutral_geometry_for_publication(self.compiled)

    def test_source_validation_precedes_producer_projection(self):
        proof = self.sealed.frontend_geometry['producer_validated_members']
        self.assertEqual(len(proof['members']), 2)
        self.assertTrue(all('shape' in row and 'transform' in row and 'source_refs' in row for row in proof['members']))
        with self.assertRaisesRegex(ValueError, 'caller-supplied'):
            generic_geometry.seal_neutral_geometry_for_publication(self.sealed)
        forged = copy.deepcopy(self.compiled)
        forged.frontend_gems['world'] += '-- forged'
        with self.assertRaisesRegex(ValueError, 'canonical source'):
            generic_geometry.seal_neutral_geometry_for_publication(forged)
        stale = copy.deepcopy(self.compiled)
        stale.frontend_geometry['source_snapshot']['components_source']['first']['width_mm'] = 20
        with self.assertRaises(ValueError):
            generic_geometry.seal_neutral_geometry_for_publication(stale)
        with self.assertRaises(ValueError):
            model.compile_prepared_model(self.sealed, self.case.assembly.components_resolved,
                                         drive=self.case.drive, physics=model.RF_PHYSICS)

    def test_projection_tamper_and_static_physics_refuse(self):
        generic_geometry.validate_published_neutral_geometry(self.sealed)
        for mode in ('shape', 'group', 'pose', 'gem', 'witness', 'port', 'interface', 'grid'):
            candidate = copy.deepcopy(self.sealed)
            proof = candidate.frontend_geometry['producer_validated_members']['members']
            if mode == 'shape': proof[0]['shape']['parts'][0]['size_mm'][0] += 1
            elif mode == 'group': proof[0]['electrode_group_id'] = 'wrong'
            elif mode == 'pose': proof[0]['transform']['translation_mm'][0] += 1
            elif mode == 'gem': candidate.frontend_gems['world'] += '-- changed'
            elif mode == 'witness': candidate.frontend_geometry['metal_witnesses'][0]['gu'] = [0,0,0]
            elif mode == 'port': candidate.frontend_geometry['source_snapshot']['composition_plan']['components']['first']['ports']['out']['center_mm'][0] += 1
            elif mode == 'interface': candidate.frontend_geometry['source_snapshot']['composition_plan']['components']['first']['component_electrodes'][0]['electrode_group_id'] = 'changed'
            else: candidate.frontend_geometry['dimensions'][0] += 1
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                generic_geometry.validate_published_neutral_geometry(candidate)
        with self.assertRaises(ValueError):
            model._compile_static_world_published_model(self.sealed, self.case.assembly.components_resolved,
                drive=self.case.drive, physics=dict(model.RF_PHYSICS, boundary_policy='grounded_pa_faces'))
        bad = copy.deepcopy(self.case.drive); bad['groups']['first']['body']['voltage_v'] = float('nan')
        with self.assertRaises(ValueError):
            model._compile_static_world_published_model(self.sealed, self.case.assembly.components_resolved,
                drive=bad, physics=model.RF_PHYSICS)

    def test_isolated_cold_projection_needs_no_provider_registration(self):
        import msplatform
        module_paths = {name: str(Path(module.__file__).resolve()) for name, module in
                        (('assembly_geometry', assembly_geometry), ('generic_geometry', generic_geometry), ('model', model))}
        payload = dict(compiled=asdict(self.sealed), components=self.case.assembly.components_resolved,
                       drive=self.case.drive, physics=model.RF_PHYSICS, modules=module_paths,
                       source_root=str(Path(msplatform.__file__).resolve().parent.parent))
        code = '''
import importlib.util,json,sys
sys.path.insert(0,sys.argv[2])
p=json.load(open(sys.argv[1],encoding="utf-8"))
for name in ("assembly_geometry","generic_geometry","model"):
 key="msplatform.backends.simion."+name
 spec=importlib.util.spec_from_file_location(key,p["modules"][name]);m=importlib.util.module_from_spec(spec);sys.modules[key]=m;spec.loader.exec_module(m)
from msplatform.components.registry import project_descriptor
try: project_descriptor("toy_registered")
except ValueError: pass
else: raise AssertionError("unexpected toy provider registration")
from msplatform.backends.simion.compiler import CompiledSimionGeometry
from msplatform.backends.simion.model import _compile_static_world_published_model
p["compiled"]["downstream_specs"]=tuple(p["compiled"]["downstream_specs"])
c=CompiledSimionGeometry(**p["compiled"])
m=_compile_static_world_published_model(c,p["components"],drive=p["drive"],physics=p["physics"])
assert len(m.document["native_drive_rows"])==2
print("COLD_PROJECTION=PASS")
print("COLD_MODEL="+json.dumps(m.document,sort_keys=True))
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = root/'projection.json'
            request.write_text(json.dumps(payload), encoding='utf-8')
            result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(request), payload['source_root']],
                                    cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('COLD_PROJECTION=PASS', result.stdout)
            actual = json.loads(next(line.removeprefix('COLD_MODEL=') for line in result.stdout.splitlines()
                                     if line.startswith('COLD_MODEL=')))
            expected = model.compile_prepared_model(self.compiled, self.case.assembly.components_resolved,
                                                   drive=self.case.drive, physics=model.RF_PHYSICS).document
            self.assertEqual(actual['drive'], expected['drive'])
            self.assertEqual(actual['native_drive_rows'], expected['native_drive_rows'])
            self.assertEqual(actual['physics'], expected['physics'])
            actual.pop('model_identity_sha256'); expected.pop('model_identity_sha256')
            actual['geometry']['frontend_geometry'].pop('producer_validated_members')
            self.assertEqual(actual, expected)

    def test_public_build_rejects_untrusted_projection_before_owner(self):
        from unittest.mock import patch
        from msplatform.backends.simion import operations
        limits = dict(wall_clock_seconds=120, transient_run_directory_bytes=1048576,
            process_tree_working_set_bytes=1048576, minimum_system_available_memory_bytes=1048576,
            compact_final_retained_bytes=1048576, automatic_retry_count=0)
        policy = dict(schema_version=1, role='execution_stage_policy', stages={'build_geometry': dict(
            limits=limits, artifact_retention={'policy_version':1, 'class':'solver_review', 'reason':'inert test'})})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'stage.json'
            path.write_text(json.dumps(policy), encoding='utf-8')
            context = SimpleNamespace(tools={'simion':Path(sys.executable)}, stage_policy_path=path, environment=None)
            with patch('msplatform.execution.owner.run_managed_stage') as owner:
                with self.assertRaisesRegex(ValueError, 'caller-supplied'):
                    operations.build_geometry(self.sealed, context=context)
                damaged = copy.deepcopy(self.compiled)
                damaged.frontend_gems['world'] += '-- forged'
                with self.assertRaisesRegex(ValueError, 'canonical source'):
                    operations.build_geometry(damaged, context=context)
                owner.assert_not_called()
    @unittest.skipUnless(sys.platform == 'win32', 'Windows process owner required')
    def test_actual_public_geometry_and_cold_model_owner(self):
        import os
        from unittest.mock import patch
        import msplatform
        from common.contracts.test_support.sfi_scalar_owner_fixture import make_context
        from msplatform.backends.simion import operations
        from msplatform.execution.run_session import RunSession
        _inert_simion_leaf.original = RunSession.run_process
        private = {'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN':'',
                   'MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID':'',
                   'MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE':''}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, private):
            root = Path(directory)
            context, _, _ = make_context(root)
            policy = json.loads(context.stage_policy_path.read_text(encoding='utf-8'))
            for name in ('build_geometry', 'prepare_model'):
                policy['stages'][name] = copy.deepcopy(policy['stages']['track'])
            context.stage_policy_path.write_text(json.dumps(policy), encoding='utf-8')
            with patch.object(RunSession, 'run_process', new=_inert_simion_leaf):
                geometry = operations.build_geometry(self.compiled, context=context)
            drive = dict(groups=self.case.drive['groups'], clock=dict(phase_reference_instrument_time_us=0),
                         clock_authority=dict(example_resource='instrument_clock_authority_v1.json'))
            request = dict(geometry=geometry.reference, drive=drive, context=dict(
                workspace=str(context.workspace), python=str(context.python_executable),
                powershell=str(context.powershell_executable), simion=str(context.tools['simion']),
                host_state=str(context.host_state_path), policy=str(context.policy_path),
                capacity_policy=str(context.capacity_policy_path), stage_policy=str(context.stage_policy_path)))
            request_path=root/'cold_request.json'; request_path.write_text(json.dumps(request), encoding='utf-8')
            repo = Path(fixture.__file__).resolve().parents[2]
            source = Path(msplatform.__file__).resolve().parent.parent
            module_paths={name:str(Path(module.__file__).resolve()) for name,module in
                (('assembly_geometry',assembly_geometry),('generic_geometry',generic_geometry),('model',model),('operations',operations))}
            modules=root/'modules.json';modules.write_text(json.dumps(module_paths),encoding='utf-8')
            child = '''
import importlib.util,json,sys
sys.path[:0]=[sys.argv[2],sys.argv[3]]
import msplatform.backends.simion as package
paths=json.load(open(sys.argv[4],encoding="utf-8"))
for name in ("assembly_geometry","generic_geometry","model","operations"):
 key="msplatform.backends.simion."+name;spec=importlib.util.spec_from_file_location(key,paths[name]);m=importlib.util.module_from_spec(spec);sys.modules[key]=m;spec.loader.exec_module(m);setattr(package,name,m)
s=importlib.util.spec_from_file_location("cold_fixture",sys.argv[5]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m._cold_public_model(sys.argv[1])
'''
            result=subprocess.run([sys.executable,'-I','-B','-c',child,str(request_path),str(repo),str(source),
                                   str(modules),str(Path(__file__).resolve())],cwd=root,capture_output=True,
                                  text=True,encoding='utf-8',timeout=600,check=False)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('PUBLIC_COLD_MODEL=PASS',result.stdout)
            cold = json.loads(next(line.removeprefix('PUBLIC_COLD_MODEL_JSON=') for line in result.stdout.splitlines()
                                   if line.startswith('PUBLIC_COLD_MODEL_JSON=')))
            provider_drive = dict(groups=copy.deepcopy(self.case.drive['groups']), clock=copy.deepcopy(cold['drive']['clock']))
            provider = model.compile_prepared_model(self.compiled, self.case.assembly.components_resolved,
                                                     drive=provider_drive, physics=model.RF_PHYSICS).document
            self.assertEqual(cold['drive'], provider['drive'])
            self.assertEqual(cold['native_drive_rows'], provider['native_drive_rows'])
            self.assertEqual(cold['physics'], provider['physics'])
            cold.pop('model_identity_sha256'); provider.pop('model_identity_sha256')
            cold['geometry']['frontend_geometry'].pop('producer_validated_members')
            self.assertEqual(cold, provider)

def _inert_simion_leaf(session, operation_id, *, immutable_input_records=(), **kwargs):
    """Replace only the vendor process; keep the real public managed owner."""
    if kwargs['role'] != 'SIMION':
        return _inert_simion_leaf.original(session, operation_id,
            immutable_input_records=immutable_input_records, **kwargs)
    run = session.run_dir
    code = 'from pathlib import Path\nimport json\n'
    if operation_id == 'geometry_world':
        for path in (run/'simion/geometry/world.pa#', run/'simion/geometry/world.pa-surf',
                     run/'results/world_surface.csv'):
            code += 'p=Path('+repr(str(path))+');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"INERT_ONLY")\n'
        geometry = json.loads((session.input_dir/'compiled_geometry.json').read_text(encoding='utf-8'))['frontend_geometry']
        state = dict(schema_version=1, mode='present', grid=geometry['dimensions'],
                     pitch=[geometry['pitch_mm']]*3, scanned_nodes=None, offset_nodes=None)
        code += 'Path('+repr(str(run/'results/world_surface_state.json'))+').write_text('+repr(json.dumps(state, separators=(',', ':')))+',encoding="utf8")\n'
        code += 'print("BUILD_GEOMETRY=PASS ROLE=world")\n'
    elif operation_id in ('build_geometry', 'verify_geometry'):
        if operation_id == 'build_geometry':
            for path in (run/'simion/geometry/geometry.iob', run/'simion/geometry/geometry.fly2'):
                code += 'p=Path('+repr(str(path))+');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"INERT_ONLY")\n'
        code += 'print('+repr('NEUTRAL_WORLD_GEOMETRY_IOB=PASS' if operation_id == 'build_geometry'
                              else 'NEUTRAL_WORLD_GEOMETRY_IOB_REOPEN=PASS')+')\n'
    elif operation_id == 'materialize_geometry':
        raise AssertionError('existing real materializer should own this operation')
    elif operation_id in ('build_model', 'verify_model'):
        if operation_id == 'build_model':
            for path in (run/'simion/geometry/geometry.iob', run/'simion/geometry/geometry.fly2'):
                code += 'p=Path('+repr(str(path))+');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"INERT_ONLY")\n'
        else:
            output = run/'results/model_drive_readback.txt'
            document = session.input_dir/'compiled_model.json'
            code += ('m=json.loads(Path('+repr(str(document))+').read_text(encoding="utf-8"));'
                     'p=Path('+repr(str(output))+');p.parent.mkdir(parents=True,exist_ok=True);'
                     'p.write_text(json.dumps({"fixture":"INERT_ONLY","model_identity_sha256":m["model_identity_sha256"],'
                     '"groups":m["native_drive_rows"],"clock":m["drive"]["clock"]}),encoding="utf-8")\n')
        code += 'print('+repr('NEUTRAL_WORLD_MODEL_BUILD=PASS' if operation_id == 'build_model'
                              else 'NEUTRAL_WORLD_MODEL_READBACK=PASS')+')\n'
    else:
        raise AssertionError('unexpected inert SIMION operation '+operation_id)
    return _inert_simion_leaf.original(session, operation_id, executable=Path(sys.executable),
        arguments=['-I','-B','-c',code], role='GATE', stage='inert_static_world', limits=kwargs['limits'],
        immutable_input_records=immutable_input_records)


def _cold_public_model(request_path):
    """Called only by isolated child; no registration of the external toy provider."""
    import os
    from unittest.mock import patch
    from msplatform.backends.simion import operations
    from msplatform.components.registry import project_descriptor
    from msplatform.execution.context import ExecutionContext
    from msplatform.execution.run_session import RunSession
    request = json.loads(Path(request_path).read_text(encoding='utf-8'))
    try:
        project_descriptor('toy_registered')
    except ValueError:
        pass
    else:
        raise AssertionError('external provider was implicitly registered')
    data = request['context']
    context = ExecutionContext(workspace=Path(data['workspace']), python_executable=Path(data['python']),
        powershell_executable=Path(data['powershell']), tools={'simion': Path(data['simion'])},
        host_state_path=Path(data['host_state']), policy_path=Path(data['policy']),
        capacity_policy_path=Path(data['capacity_policy']), stage_policy_path=Path(data['stage_policy']))
    _inert_simion_leaf.original = RunSession.run_process
    private = {'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN':'',
               'MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID':'',
               'MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE':''}
    with patch.dict(os.environ, private), patch.object(RunSession, 'run_process', new=_inert_simion_leaf):
        result = operations.prepare_model(request['geometry'], drive=request['drive'],
                                          physics=model.RF_PHYSICS, context=context)
    doc = json.loads(result.data_path('compiled_model').read_text(encoding='utf-8'))
    assert len(doc['native_drive_rows']) == 2
    print('PUBLIC_COLD_MODEL=PASS', flush=True)
    print('PUBLIC_COLD_MODEL_JSON='+json.dumps(doc,sort_keys=True), flush=True)
