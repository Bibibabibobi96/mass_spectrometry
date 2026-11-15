"""Public geometry-to-model owner with explicitly inert native leaves."""
import copy,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from common.contracts import test_ip_mr_model as fixture
from common.contracts.test_support.sfi_scalar_owner_fixture import make_context
from msplatform.backends.simion import operations
from msplatform.backends.simion.model import RF_IP_PHYSICS
from msplatform.backends.simion.native_plans import plan_geometry_build
from msplatform.backends.simion.resources import structural_seed_path
from msplatform.execution.run_session import RunSession
from msplatform.io.manifest_records import file_record,verify_record

class ManagedEmptyGeometryTests(unittest.TestCase):
 def test_public_geometry_to_model_empty_surface(self):
  fixture.IpMrModelTests.setUpClass();compiled=fixture.IpMrModelTests.compiled
  drive=copy.deepcopy(fixture.IpMrModelTests.drive);drive['clock']={'phase_reference_instrument_time_us':0.};drive['clock_authority']={'example_resource':'instrument_clock_authority_v1.json'}
  calls=[];original=RunSession.run_process
  def inert(session,operation_id,*,immutable_input_records=(),**kwargs):
   if kwargs['role']!='SIMION':return original(session,operation_id,immutable_input_records=immutable_input_records,**kwargs)
   calls.append(operation_id);run=session.run_dir;code='from pathlib import Path\nimport json\n'
   if operation_id.startswith('geometry_'):
    seed=file_record(structural_seed_path(len(compiled.frontend_gems)),'required_evidence')
    plan=plan_geometry_build(compiled,run_directory=run,seed_record=seed,native_path_resource=session.input_dir/'native_sources/native_run_path.lua')
    op=next(x for x in plan.operations if x['operation_id']==operation_id);role=operation_id.removeprefix('geometry_')
    domain=compiled.frontend_geometry['numerical_domains'][role];dims=[domain['dimensions']['n'+a] for a in 'xyz'];pitch=[domain['cell_mm_xyz'][a] for a in 'xyz']
    empty=role==next(iter(compiled.frontend_gems))
    state=dict(schema_version=1,mode='empty' if empty else 'present',grid=dims,pitch=pitch,scanned_nodes=dims[0]*dims[1]*dims[2] if empty else None,offset_nodes=0 if empty else None)
    for path in op['outputs']:
     payload=json.dumps(state) if str(path).endswith('_surface_state.json') else 'INERT_ONLY'
     code+='p=Path('+repr(path)+');p.parent.mkdir(parents=True,exist_ok=True);p.write_text('+repr(payload)+',encoding="utf8")\n'
    if not empty:code+='p=Path('+repr(op['optional_surface'])+');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"INERT_ONLY")\n'
    code+='print('+repr(op['success_marker'])+')\n'
   elif operation_id in ('build_geometry','verify_geometry','build_model','verify_model'):
    if operation_id in ('build_geometry','build_model'):
     for path in (run/'simion/geometry/geometry.iob',run/'simion/geometry/geometry.fly2'):
      code+='p=Path('+repr(str(path))+');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"INERT_ONLY")\n'
    if operation_id=='verify_model':
     code+='m=json.loads(Path('+repr(str(session.input_dir/'compiled_model.json'))+').read_text(encoding="utf8"));p=Path('+repr(str(run/'results/model_drive_readback.txt'))+');p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps({"fixture":"INERT_ONLY","model_identity_sha256":m["model_identity_sha256"],"groups":m["native_drive_rows"],"clock":m["drive"]["clock"]}),encoding="utf8")\n'
    code+='print('+repr(('IP_MR_GEOMETRY_IOB' if 'geometry' in operation_id else 'IP_MR_MODEL')+('_REOPEN' if operation_id=='verify_geometry' else '_BUILD' if operation_id=='build_model' else '_READBACK' if operation_id=='verify_model' else '')+'=PASS')+')\n'
   else:raise AssertionError('unexpected native leaf '+operation_id)
   return original(session,operation_id,executable=Path(sys.executable),arguments=['-I','-B','-c',code],role='GATE',stage='inert_geometry_model',limits=kwargs['limits'],immutable_input_records=immutable_input_records)
  with tempfile.TemporaryDirectory(prefix='empty-surface-owner-') as d,patch.dict(os.environ,{'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN':''}):
   context,_,_=make_context(Path(d));policy=json.loads(context.stage_policy_path.read_text(encoding='utf8'))
   for name in ('build_geometry','prepare_model'):policy['stages'][name]=copy.deepcopy(policy['stages']['track'])
   context.stage_policy_path.write_text(json.dumps(policy),encoding='utf8')
   with patch.object(RunSession,'run_process',new=inert):
    geometry=operations.build_geometry(compiled,context=context)
    empty=next(iter(compiled.frontend_gems));asset=geometry.metadata['native_assets'][empty]
    self.assertIn('surface_state',asset);self.assertNotIn('fractional_surface',asset)
    state=json.loads(geometry.data_path(asset['surface_state']).read_text());self.assertEqual(state['mode'],'empty')
    model=operations.prepare_model(geometry,drive=drive,physics=RF_IP_PHYSICS,context=context)
    owned=model.metadata['native_assets'][empty];self.assertIn('surface_state',owned);self.assertNotIn('fractional_surface',owned)
    for record in model.data_records.values():verify_record('managed synthetic model record',record)
    self.assertEqual(calls[-2:],['build_model','verify_model'])
