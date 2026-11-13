import json
import unittest
from pathlib import Path
from unittest.mock import patch

from msplatform.backends.comsol import assembly_electrostatic_model as mod
HERE = Path(__file__).resolve().parent

class ExplicitRequestTests(unittest.TestCase):
    def setUp(self):
        self.projection = {'electrode_groups': [{'instance_id': 'a', 'electrode_group_id': 'one'}, {'instance_id': 'b', 'electrode_group_id': 'two'}]}
        self.request = {'group_voltages': [{'instance_id': 'b', 'electrode_group_id': 'two', 'voltage_v': -3}, {'instance_id': 'a', 'electrode_group_id': 'one', 'voltage_v': 2}], 'relative_permittivity': 1, 'exterior': {'kind': 'potential', 'voltage_v': 0}, 'mesh': {'global_automatic_level': 5, 'electrode_hmax_mm': 4}, 'study': {'kind': 'stationary'}}
    def test_explicit_request_order_and_values(self):
        result = mod.validate_request(self.projection, self.request)
        self.assertEqual([r['voltage_v'] for r in result['group_voltages']], [2, -3])
        self.assertEqual(result['study'], {'kind':'stationary'})
    def test_missing_duplicate_unknown_and_nonfinite_refuse(self):
        import copy
        for mutation in ('missing', 'duplicate', 'unknown', 'nan', 'mesh', 'study'):
            value = copy.deepcopy(self.request)
            if mutation == 'missing': value['group_voltages'].pop()
            if mutation == 'duplicate': value['group_voltages'][1] = value['group_voltages'][0]
            if mutation == 'unknown': value['group_voltages'][0]['instance_id'] = 'other'
            if mutation == 'nan': value['group_voltages'][0]['voltage_v'] = float('nan')
            if mutation == 'mesh': value['mesh']['electrode_hmax_mm'] = 0
            if mutation == 'study': del value['study']
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): mod.validate_request(self.projection, value)
    def test_one_group_scalar_voltage_and_face_are_accepted(self):
        projection={'electrode_groups':[{'instance_id':'one','electrode_group_id':'g'}]}
        request=dict(self.request,group_voltages=[{'instance_id':'one','electrode_group_id':'g','voltage_v':2}])
        request=mod.validate_request(projection,request)
        row={'operation':'build','scope':'assembly_electrostatic_unsolved','group_keys':['one/g'],'group_voltages_v':2,'relative_permittivity':1,'exterior_voltage_v':0,'mesh':request['mesh'],'compute_calls':0,'solution_count':0,'model_rewritten':True,'model_path':str(HERE/'model.mph'),'vacuum_domains':[1],'outer_faces':[4],'group_faces':[3]}
        mod._check_report(row,'build',projection,request,HERE/'model.mph')

    def test_report_must_be_unsolved_and_bound_to_request(self):
        request=mod.validate_request(self.projection,self.request)
        row={'operation':'build','scope':'assembly_electrostatic_unsolved','group_keys':['a/one','b/two'],'group_voltages_v':[2,-3],'relative_permittivity':1,'exterior_voltage_v':0,'mesh':request['mesh'],'compute_calls':0,'solution_count':0,'model_rewritten':True,'model_path':str(HERE/'model.mph'),'vacuum_domains':[1],'outer_faces':[1],'group_faces':[[2],3]}
        mod._check_report(row,'build',self.projection,request,HERE/'model.mph')
        for key in ('compute_calls','solution_count','exterior_voltage_v'):
            bad=dict(row);bad[key]=1
            with self.subTest(key=key),self.assertRaises(ValueError): mod._check_report(bad,'build',self.projection,request,HERE/'model.mph')
    def test_invalid_groups_stop_before_managed_owner(self):
        source = type('Source', (), {'metadata': {'backend':'comsol','scope':'geometry_only','native_reopen_verified':True}, 'data_path': lambda self, name: HERE/'projection-test.json'})()
        with patch.object(mod,'open_artifact',return_value=source), patch.object(mod,'run_managed_stage') as owner, patch.object(Path,'read_text',return_value=json.dumps(self.projection)):
            with self.assertRaises(ValueError): mod.prepare_model(None,request={},context=None)
            owner.assert_not_called()

    def test_valid_public_dispatch_uses_existing_managed_owner(self):
        import tempfile
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); projection=root/'projection.json';projection.write_text(json.dumps(self.projection),encoding='utf8')
            executable=root/'comsol.exe';executable.touch();matlab=root/'matlab';matlab.mkdir()
            source=SimpleNamespace(metadata={'backend':'comsol','scope':'geometry_only','native_reopen_verified':True},data_path=lambda name:projection,reference={'manifest':{'path':'source.json'}})
            context=SimpleNamespace(tools={'comsol_launcher':executable,'matlab_root':matlab})
            stage={'limits':{'transient_run_directory_bytes':123},'artifact_retention':{}}
            final=object()
            with patch.object(mod,'open_artifact',side_effect=[source,final]), patch.object(mod,'read_stage_policy',return_value=(stage,{})), patch.object(mod,'file_record',return_value={}), patch.object(mod,'run_managed_stage',return_value={'manifest':{'path':'result.json'}}) as owner:
                result=mod.prepare_model({},request=self.request,context=context)
            self.assertIs(result,final)
            args=owner.call_args.kwargs
            self.assertEqual(args['expected_operation_ids'],('build_model','reopen_model'))
            self.assertEqual(args['action'].func,mod.execute_model)
            self.assertEqual(args['source_references'],[{'manifest_record':source.reference['manifest']}])
            self.assertEqual(args['payload']['request']['study'],{'kind':'stationary'})
            self.assertEqual(args['operation_dependencies'],{'reopen_model':['build_model']})

    def test_missing_required_native_resource_refuses_before_copy(self):
        from msplatform.backends.comsol import native_execution
        from types import SimpleNamespace
        session=SimpleNamespace(input_dir=HERE/'not-created')
        with patch.object(native_execution,'native_resource_path',side_effect=FileNotFoundError('assembly_electrostatic_model.m')):
            with self.assertRaisesRegex(FileNotFoundError,'assembly_electrostatic_model'):
                native_execution.freeze_native_sources(session,mod._NATIVE_SOURCES)
        self.assertFalse((HERE/'not-created').exists())

    def test_actual_action_binds_geometry_and_checks_cold_tamper(self):
        import tempfile
        from types import SimpleNamespace
        from msplatform.io.manifest_records import file_record
        for tamper in (False,True):
            with self.subTest(tamper=tamper), tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary)
                for directory in ('inputs','results','logs','original'): (root/directory).mkdir()
                original={}
                baseline={'group_keys':['a/one','b/two'],'group_faces':[[2],3],'vacuum_domains':[1],'outer_faces':[4]}
                for name in ('projection','geometry_validation','model','descriptor','build_geometry','reopen_geometry'):
                    path=root/'original'/(name+('.mph' if name=='model' else '.json'))
                    path.write_text(json.dumps(baseline) if name=='reopen_geometry' else 'fixture',encoding='utf8')
                    original[name]=path
                source=SimpleNamespace(data_path=lambda name: original[name], data_records={name:file_record(path,'solver_native_binary' if name=='model' else 'required_evidence') for name,path in original.items()}, data_locations=original,reference={'manifest':{'path':str(root/'source-manifest.json')}})
                context=SimpleNamespace(workspace=root,python_executable=root/'python',powershell_executable=root/'pwsh',host_state_path=root/'state',policy_path=root/'policy',tools={'comsol_launcher':root/'comsol','matlab_root':root})
                added={}
                session=SimpleNamespace(expected_operation_ids=('build_model','reopen_model'),input_dir=root/'inputs',result_dir=root/'results',log_dir=root/'logs',run_dir=root,context=context,run_id='inert',declare_file=lambda path,role:path,add_input=lambda name,record:added.update({name:record}))
                request=mod.validate_request(self.projection,self.request); output=root/'assembly-electrostatic-unsolved.mph'; calls=[]
                def simulate(operation,**kwargs):
                    calls.append((operation,kwargs))
                    mode='build' if operation=='build_model' else 'reopen'
                    if mode=='build': output.write_bytes(b'inert model')
                    if mode=='reopen' and tamper: output.write_bytes(b'tampered model')
                    (root/'logs'/(operation+'.bootstrap.log')).write_text('STATUS=PASS',encoding='utf8')
                    row=dict(baseline,operation=mode,scope='assembly_electrostatic_unsolved',model_path=str(output),group_voltages_v=[2,-3],relative_permittivity=1,exterior_voltage_v=0,mesh=request['mesh'],compute_calls=0,solution_count=0,model_rewritten=(mode=='build'))
                    (root/'results'/(operation+'.json')).write_text(json.dumps(row),encoding='utf8')
                session.run_process=simulate
                with patch.object(mod,'freeze_native_sources',return_value=(root/'native'/'launcher.ps1',[])), patch.object(mod,'declare_runtime_files'), patch.object(mod,'require_launcher_completion'):
                    if tamper:
                        with self.assertRaises((AssertionError,ValueError)): mod.execute_model(session,source=source,projection=self.projection,request=request,limits={})
                    else:
                        result=mod.execute_model(session,source=source,projection=self.projection,request=request,limits={})
                        product=result['manifest_extra_fields']['products']['model']
                        self.assertEqual(product['kind'],'prepared_model')
                        first_guard=[r['path'] for r in calls[0][1]['immutable_input_records']]
                        second_guard=[r['path'] for r in calls[1][1]['immutable_input_records']]
                        self.assertIn(str(original['model']),first_guard)
                        self.assertNotIn(str(original['model']),second_guard)
                        self.assertFalse((root/'inputs/geometry/model.mph').exists())
                        self.assertEqual(product['metadata']['field_status'],'not_solved')
                        self.assertEqual(product['data']['projection'],added['geometry_projection'])
                        self.assertEqual(set(product['data']),{'model','request','geometry_manifest','projection','descriptor','geometry_validation','reopen_geometry','build_model','reopen_model'})

if __name__ == '__main__': unittest.main()
