"""Actual frozen preparation and inert vendor transport; no field solver."""
from __future__ import annotations

import copy
import os
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.write_run_manifest import build_run_manifest, file_record
from common.contracts.capacity_ledger import initialize_capacity_ledger, record_capacity_object
from common.contracts.capacity_protection import create_capacity_protection_lease
from common.contracts.run_capacity_lifecycle import seal_checkpoint
from common.simion import test_pa_family_cache as public_cache_tests
from integrations.workflows.paired_accelerator_static_field import runtime
from integrations.runtime import paired_accelerator_model
from projects.single_reflection_oa_tof_mass_analyzer.tests.analysis import test_paired_accelerator_static_field_prepare as preparation_tests

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT/'integrations/workflows/paired_accelerator_static_field'


class PairedStaticExecutionTests(unittest.TestCase):
    def test_sample_coordinates_round_trip_exactly_and_reject_a_true_ulp_change(self):
        pairs=[('89.94434260835371','89.944342608353708'),
               ('201.4266955495302','201.42669554953019')]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);expected=root/'prepared.csv';actual=root/'native.csv'
            expected.write_text('point_id,x_mm,y_mm,z_mm\n'+
                ''.join(f'{i},0,0,{prepared}\n' for i,(prepared,_) in enumerate(pairs,1)),encoding='utf-8')
            header='point_id,x_mm,y_mm,z_mm,Ex_V_per_m,Ey_V_per_m,Ez_V_per_m\n'
            rows=[f'{i},0,0,{native},0,0,0\n' for i,(_,native) in enumerate(pairs,1)]
            actual.write_text(header+''.join(rows),encoding='utf-8')
            plan={'sample_points':{'path':str(expected)}}
            for prepared,native in pairs:self.assertEqual(float(prepared).hex(),float(native).hex())
            runtime.validate_samples(plan,actual)
            for index,(_,native) in enumerate(pairs):
                with self.subTest(coordinate=native):
                    changed=rows.copy()
                    changed[index]=f'{index+1},0,0,{math.nextafter(float(native),math.inf):.17g},0,0,0\n'
                    actual.write_text(header+''.join(changed),encoding='utf-8')
                    with self.assertRaisesRegex(ValueError,'coverage differs'):
                        runtime.validate_samples(plan,actual)

    def test_python_owner_transport_retains_json_and_nonzero_stderr_under_redirection(self):
        """Run the extracted owner function and real public context with Python."""
        script=r"""param($Source,$RepoRoot,$Python,$Directory)
$ErrorActionPreference='Stop'
. (Join-Path $RepoRoot 'common/contracts/run_artifact_support.ps1')
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$errors=$null;$tokens=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$function=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-PairedPython'},$true)
. ([scriptblock]::Create($function.Extent.Text))
$assignment=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq'$header'},$true)
. ([scriptblock]::Create($assignment.Extent.Text))
$package=@{log_dir=$Directory;run_dir=$Directory};$frozen=@{execution_root=$RepoRoot}
$outer=Join-Path $Directory outer.log
& {
 $paths=@(1..240|ForEach-Object{"C:\实验 space\受保护路径\member_$_.pa"})
 $payload=@{lease_id='真实容量租约';owner='paired-static:冻结 run';protected_paths=$paths}|ConvertTo-Json -Compress
 if($payload.Length-lt5000){throw 'large argument fixture unexpectedly short'}
 $stage='round_trip'
 $result=Invoke-PairedPython -Code 'print(json.dumps(dict(capacity=json.loads(sys.argv[1]),cwd=str(Path.cwd()))))' -Arguments @($payload)
 if($result.capacity.owner-ne'paired-static:冻结 run'-or$result.capacity.protected_paths.Count-ne240){throw 'capacity JSON argument changed'}
 if($result.cwd-ne$RepoRoot){throw 'public tool root context was bypassed'}
 $saved=Get-Content (Join-Path $Directory round_trip.python.stdout.json) -Raw|ConvertFrom-Json -AsHashtable
 if($saved.capacity.protected_paths[239]-ne$paths[239]){throw 'stdout JSON was truncated or Unicode changed'}
 $capacity=@{lease_id='真实容量租约';owner='paired-static:冻结 run';protected_paths=$paths;startup_gate=@{ledger_report=('x'*120000)}}
 if(($capacity|ConvertTo-Json -Compress -Depth 10).Length-le100000){throw 'full capacity fixture must exceed Windows argv budget'}
 $cachePath=Join-Path $Directory pa_cache_plan.json
 foreach($name in @('$cacheLease','$cacheArguments')){
  $assignment=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq$name},$true)
  if($null-eq$assignment){throw "owner assignment missing: $name"}
  . ([scriptblock]::Create($assignment.Extent.Text))
 }
 if($cacheArguments.Count-ne3-or$cacheArguments[2].Length-ge512){throw 'owner passed the capacity report instead of the small lease'}
 $leaseArgument=$cacheArguments[2]|ConvertFrom-Json -AsHashtable
 if(($leaseArgument.Keys|Sort-Object)-join','-ne'lease_id,owner'){throw 'lease argv must contain exactly the two required fields'}
 $stage='lease_projection'
 $result=Invoke-PairedPython -Code 'print(json.dumps(dict(capacity=json.loads(sys.argv[3]),run=sys.argv[1],plan=sys.argv[2])))' -Arguments $cacheArguments
 if($result.capacity.lease_id-ne$capacity.lease_id-or$result.capacity.owner-ne$capacity.owner){throw 'projected lease changed in Python'}
 if($result.run-ne$Directory-or$result.plan-ne$cachePath){throw 'actual owner argument order changed'}
 $stage='nonzero';$failed=$false
 try{
  $null=Invoke-PairedPython -Code 'print("partial stdout retained");sys.stderr.buffer.write("真实 Python 失败\n".encode("utf-8"));sys.exit(7)'
 }catch{
  if($_.Exception.Message-notlike'*真实 Python 失败*'){throw}
  $failed=$true
 }
 if(-not$failed){throw 'nonzero Python exit was swallowed'}
 if((Get-Content (Join-Path $Directory nonzero.python.stdout.json) -Raw)-notlike'*partial stdout retained*'){throw 'failed stdout lost'}
 if((Get-Content (Join-Path $Directory nonzero.python.stderr.log) -Raw)-notlike'*真实 Python 失败*'){throw 'failed stderr lost'}
 'PYTHON_TRANSPORT=PASS'
} *> $outer
Get-Content -LiteralPath $outer
"""
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);wrapper=root/'python_transport.ps1'
            wrapper.write_text(script,encoding='utf-8',newline='\n')
            result=subprocess.run(['pwsh','-NoProfile','-NonInteractive','-File',str(wrapper),
                str(WORKFLOW/'execute.ps1'),str(ROOT),sys.executable,str(root)],
                cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=60)
            outer=root/'outer.log'
            self.assertEqual(result.returncode,0,result.stdout+result.stderr+
                (outer.read_text(encoding='utf-8') if outer.exists() else ''))
            self.assertIn('PYTHON_TRANSPORT=PASS',result.stdout)

    def test_native_stage_transitions_bind_actual_public_parameters(self):
        """Exercise both owner calls with the public signature, without admission."""
        script=r"""param($Source,$Public)
$ErrorActionPreference='Stop'
$errors=$null;$tokens=$null
$api=[Management.Automation.Language.Parser]::ParseFile($Public,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$function=$api.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Update-HostResourceStage'},$true)
# Keep actual mandatory/type metadata; replace only resource transactions.
$body=$function.Body.ParamBlock.Extent.Text+"`n"+@'
if($RetainedMemoryBytes-ne0){throw 'completed native child must retain zero memory'}
$script:stages.Add($Stage)
return $Lease
'@
Set-Item Function:Update-HostResourceStage ([scriptblock]::Create($body))
$owner=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$calls=@($owner.FindAll({param($n)$n-is[Management.Automation.Language.CommandAst]-and$n.GetCommandName()-eq'Update-HostResourceStage'},$true))
if($calls.Count-ne2){throw 'expected both native stage transitions'}
$script:stages=[Collections.Generic.List[string]]::new()
$lease=@{role='SIMION'};$budget=@{host_budgets=@{simion_refine=@{};simion_prepare=@{}}}
foreach($call in $calls){$null=& ([scriptblock]::Create($call.Extent.Text))}
if(($script:stages-join',')-ne'pa_refine,prepare'){throw 'wrong stage sequence'}
'STAGE_PARAMETERS=PASS'
"""
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'stage_parameters.ps1'
            path.write_text(script,encoding='utf-8',newline='\n')
            result=subprocess.run(['pwsh','-NoProfile','-NonInteractive','-File',str(path),
                str(WORKFLOW/'execute.ps1'),str(ROOT/'common/host_execution_lease.ps1')],
                cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('STAGE_PARAMETERS=PASS',result.stdout)

    def prepared(self, root):
        author=root/'author';author.mkdir()
        fixture=preparation_tests.PairedAcceleratorStaticFieldPrepareTests()
        request=fixture._request(author)
        source=fixture._write_request(author,request)
        run=root/'run';(run/'inputs/sources').mkdir(parents=True)
        for name,record in request['source_records'].items():
            shutil.copyfile(record['path'],run/f'inputs/sources/{name}.json')
        shutil.copyfile(source,run/'inputs/request.json')
        runtime.write(run/'run_config.json',{'parameters':{'request_source_path':str(source)}})
        for name in ('results','logs','comsol'):(run/name).mkdir()
        return run,author

    def test_snapshots_preserve_canonical_membership_without_live_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            run,author=self.prepared(Path(directory))
            shutil.rmtree(author)
            plan=runtime.prepare_run(run)
            self.assertEqual(plan['composition_plan']['scope']['instance_ids'],['oatof'])
            self.assertTrue(Path(plan['native_geometry_compilation']['gem_record']['path']).is_file())
            source=run/'inputs/sources/oatof_resolved.json'
            source.write_text('{}')
            with self.assertRaises((ValueError,AssertionError)):
                runtime.prepare_run(run)

    def test_real_frozen_closure_prepares_without_checkout_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run,author=self.prepared(root)
            command=f". '{ROOT}/integrations/runtime/dependencies.ps1'; $null=Freeze-ConsumerDependencies -RepoRoot '{ROOT}' -ContractPath '{ROOT}/integrations/config/runtime_dependencies.json' -InputDir '{run}/inputs' -OwnerId instrument_assembly -ConsumerId paired_accelerator_static_field"
            result=subprocess.run(['pwsh','-NoProfile','-Command',command],cwd=ROOT,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            snapshot=run/'inputs/runtime_snapshot'
            shutil.rmtree(author)
            environment=dict(os.environ);environment.pop('PYTHONPATH',None)
            result=subprocess.run([sys.executable,'-B','-s','-c',
                "from pathlib import Path; from integrations.workflows.paired_accelerator_static_field import runtime; "
                "assert Path(runtime.__file__).is_relative_to(Path.cwd()); "
                "runtime.prepare_run(Path(__import__('sys').argv[1]));print('FROZEN_PREPARE=PASS')",str(run)],
                cwd=snapshot,env=environment,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('FROZEN_PREPARE=PASS',result.stdout)

    def test_task_transport_and_complete_point_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run,_=self.prepared(root);plan=runtime.prepare_run(run)
            tasks=runtime.materialize_tasks(run,ROOT,root/'ordinary.pa')
            self.assertIn(",'');",Path(tasks['matlab']).read_text())
            build=runtime.field_build_arguments(plan)
            voltages=list(map(float,build['voltages'].split(',')))
            for electrode,value in plan['static_on_electrode_voltages_v'].items():
                self.assertEqual(voltages[int(electrode)-1],value)
            lua=Path('C:/Program Files/SIMION-2020/lua.exe')
            if lua.is_file():
                grid=plan['native_geometry_compilation']['grid'];pitch=grid['cell_mm_xyz'];n=grid['dimensions']
                wrapper=root/'inert_export.lua'
                wrapper.write_text(f"""local pa={{potential_type='electric',nx={n['nx']},ny={n['ny']},nz={n['nz']},
dx_mm={pitch['x']},dy_mm={pitch['y']},dz_mm={pitch['z']}}}
function pa:close() end
function pa:inside_vc() return true end
function pa:field_vc() return -2,6,-4 end
simion={{pas={{open=function(self,path) assert(path=='{(root/'ordinary.pa').as_posix()}');return pa end}}}}
dofile('{Path(tasks['lua']).as_posix()}')
""",encoding='utf-8',newline='\n')
                result=subprocess.run([str(lua),str(wrapper)],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=20)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertIn('PAIRED_FIELD_EXPORT=PASS samples=2',result.stdout)
                exported=__import__('pandas').read_csv(run/'results/simion_field_samples.csv')
                self.assertEqual(exported['point_id'].tolist(),[11,12])
                self.assertEqual(exported['Ex_V_per_m'].tolist(),[-2/pitch['x']*1000]*2)
            (root/'saved model.mph').write_bytes(b'inert source identity only')
            restored=runtime.materialize_tasks(run,ROOT,root/'ordinary.pa',saved_model=root/'saved model.mph')
            self.assertIn("saved model.mph');",Path(restored['matlab']).read_text())
            points=__import__('pandas').read_csv(plan['sample_points']['path'])
            for axis in 'xyz':points[f'E{axis}_V_per_m']=0.
            output=run/'results/simion_field_samples.csv';points.iloc[::-1].to_csv(output,index=False)
            runtime.validate_samples(plan,output)
            points.iloc[:1].to_csv(output,index=False)
            with self.assertRaises(ValueError):runtime.validate_samples(plan,output)

    def test_saved_solution_requires_bound_completion_bvp_and_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run,_=self.prepared(root);plan=runtime.prepare_run(run)
            producer=root/'producer';(producer/'comsol').mkdir(parents=True)
            source_plan=producer/'inputs/bvp/paired_accelerator_static_field_plan.json'
            runtime.write(source_plan,plan)
            backend=Path('projects')/runtime.PROJECT/'comsol/build_and_export_paired_accelerator_field.m'
            for owner in (run,producer):
                target=owner/'inputs/runtime_snapshot'/backend;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(ROOT/backend,target)
            model=producer/'comsol/paired_accelerator_static.mph';model.write_bytes(b'inert solved-model identity only')
            completion=producer/'comsol/comsol_field_solution.json'
            config=producer/'run_config.json'
            runtime.write(config,dict(schema_version=1,run_id='20261025_233000__test__python__paired-model-source',
                project='instrument_assembly',mode='paired_accelerator_static_field',
                inputs={'plan':str(source_plan),'backend':str(producer/'inputs/runtime_snapshot'/backend)}))
            manifest_path=producer/'run_manifest.json';snapshot=run/'inputs/comsol_source_manifest.json'

            def publish(fact, *, tetrahedra_literal=None):
                runtime.write(completion,fact)
                if tetrahedra_literal is not None:
                    text=completion.read_text(encoding='utf-8')
                    self.assertIn('"tetrahedra": 31',text)
                    completion.write_text(text.replace('"tetrahedra": 31',f'"tetrahedra": {tetrahedra_literal}'),encoding='utf-8')
                manifest=build_run_manifest(config,'failed',output_paths=[completion,model])
                runtime.write(manifest_path,manifest);runtime.write(snapshot,manifest)
                return manifest

            for stage in ('prepared_saved','solved_saved'):
                with self.subTest(stage=stage):
                    fact=dict(schema_version=1,role='oatof_paired_accelerator_static_field_solution',
                        status=stage,solution_present=stage=='solved_saved',solution_tag='sol1',
                        plan_path=str(source_plan),model_path=str(model),study_tag='std1',
                        mesh_complete=True,tetrahedra=31)
                    manifest=publish(fact)
                    with patch.object(paired_accelerator_model, 'verify_record',
                                      wraps=paired_accelerator_model.verify_record) as verification:
                        metadata=paired_accelerator_model.load_paired_static_model_source(manifest_path,snapshot)
                    self.assertEqual(metadata['source_stage'],stage)
                    self.assertEqual(metadata['model']['sha256'],file_record(model)['sha256'])
                    self.assertTrue(verification.call_args_list)
                    self.assertNotIn(str(model),[str(call.args[1]['path']) for call in verification.call_args_list])
                    result=runtime.comsol_reuse(run,manifest_path)
                    self.assertEqual(result['source_stage'],stage)
                    self.assertEqual(result['model']['sha256'],file_record(model)['sha256'])
                    for literal in ('3.1037688E+7','31.0','31'):
                        with self.subTest(stage=stage,tetrahedra_literal=literal):
                            publish(fact,tetrahedra_literal=literal)
                            self.assertEqual(runtime.comsol_reuse(run,manifest_path)['source_stage'],stage)
                    plan_path=run/'inputs/bvp/paired_accelerator_static_field_plan.json'
                    request_path=run/'inputs/request.json';request=runtime.read(request_path)
                    refined=copy.deepcopy(request)
                    refined['numerical_domain']['cell_mm_xyz']={axis:value/2 for axis,value in request['numerical_domain']['cell_mm_xyz'].items()}
                    runtime.write(request_path,refined)
                    recompiled=runtime.prepare_run(run)
                    self.assertNotEqual(recompiled['native_geometry_compilation']['grid'],plan['native_geometry_compilation']['grid'])
                    self.assertEqual(runtime.comsol_reuse(run,manifest_path)['source_stage'],stage)
                    runtime.write(request_path,request);runtime.prepare_run(run)
                    raster=copy.deepcopy(plan)
                    raster['accelerator_geometry']['numerical_port_width_mm']*=2
                    raster['accelerator_geometry']['numerical_port_height_mm']*=2
                    raster['accelerator_geometry']['accelerator_port_aperture_discretization']['numerical_carve_width_mm']*=2
                    renumbered=copy.deepcopy(plan)
                    bindings=renumbered['native_geometry_compilation']['electrode_bindings'][plan['oatof_instance_id']]
                    for role,value in bindings.items():
                        bindings[role]=[item+100 for item in value] if isinstance(value,list) else value+100
                    renumbered['static_on_electrode_voltages_v']={str(int(key)+100):value for key,value in plan['static_on_electrode_voltages_v'].items()}
                    for name,changed in (('raster_only',raster),('numeric_electrode_ids',renumbered)):
                        with self.subTest(stage=stage,reusable=name):
                            runtime.write(plan_path,changed)
                            self.assertEqual(runtime.comsol_reuse(run,manifest_path)['source_stage'],stage)
                    for name in ('port_center','port_shape','port_width','port_height','metal_geometry','comsol_mesh','outer_box','electrical'):
                        with self.subTest(stage=stage,physical_change=name):
                            changed=copy.deepcopy(plan)
                            port=changed['composition_plan']['components'][plan['oatof_instance_id']]['ports']['side_entry']
                            if name=='port_center':port['center_mm'][1]+=.1
                            elif name=='port_shape':port['cross_section']['shape']='ellipse'
                            elif name=='port_width':port['cross_section']['width_mm']+=.1
                            elif name=='port_height':port['cross_section']['height_mm']+=.1
                            elif name=='metal_geometry':changed['accelerator_geometry']['shield_outer_width_mm']+=1
                            elif name=='comsol_mesh':changed['numerical_domain']['comsol_mesh']['global_automatic_level']+=1
                            elif name=='outer_box':changed['numerical_domain']['pa_bounds_mm']['x_min']-=1
                            else:changed['accelerator_electrical']['operating_voltages_v']['repeller']+=1
                            runtime.write(plan_path,changed)
                            with self.assertRaisesRegex(ValueError,'common BVP differs'):
                                runtime.comsol_reuse(run,manifest_path)
                    runtime.write(plan_path,plan)
                    task=runtime.materialize_tasks(run,ROOT,root/'existing.pa',saved_model=model,saved_model_stage=result['source_stage'])
                    call=Path(task['matlab']).read_text()
                    self.assertIn(", 'prepared_saved');" if stage=='prepared_saved' else ".mph');",call)
                    self.assertEqual("'prepared_saved'" in call,stage=='prepared_saved')
                    for name,mutation in {
                        'wrong_model':lambda item:item.update(model_path=str(root/'other.mph')),
                        'wrong_plan':lambda item:item.update(plan_path=str(root/'other.json')),
                        'wrong_state':lambda item:item.update(solution_present=stage!='solved_saved'),
                        'missing_stage':lambda item:item.pop('status'),
                    }.items():
                        with self.subTest(stage=stage,invalid=name):
                            changed=dict(fact);mutation(changed);publish(changed)
                            with self.assertRaises(ValueError):runtime.comsol_reuse(run,manifest_path)
                    if stage=='prepared_saved':
                        for change in ({'mesh_complete':False},{'tetrahedra':0},{'study_tag':'std_other'}):
                            publish(dict(fact,**change))
                            with self.assertRaisesRegex(ValueError,'native COMSOL fact required'):
                                runtime.comsol_reuse(run,manifest_path)
                        for literal in ('true','false','0','-1','0.0','31.25','NaN','Infinity','-Infinity','"31"','null'):
                            with self.subTest(invalid_tetrahedra_literal=literal):
                                publish(fact,tetrahedra_literal=literal)
                                with self.assertRaisesRegex(ValueError,'native COMSOL fact required'):
                                    runtime.comsol_reuse(run,manifest_path)
                    publish(fact)
                    changed=runtime.read(source_plan);changed['static_on_electrode_voltages_v']['1']+=1
                    runtime.write(source_plan,changed);publish(fact)
                    with self.assertRaisesRegex(ValueError,'BVP differs'):runtime.comsol_reuse(run,manifest_path)
                    runtime.write(source_plan,plan);publish(fact)
                    target=run/'inputs/runtime_snapshot'/backend;original=target.read_bytes()
                    target.write_bytes(original+b'\n% Current export consumer comment only\n')
                    self.assertEqual(runtime.comsol_reuse(run,manifest_path)['source_stage'],stage)
                    target.write_bytes(original)
                    for source in (source_plan,completion,model,producer/'inputs/runtime_snapshot'/backend):
                        with self.subTest(stage=stage,tampered_source=source.name):
                            original=source.read_bytes();source.write_bytes(original+b'\nchanged source bytes\n')
                            try:
                                with self.assertRaises((ValueError,AssertionError)):runtime.comsol_reuse(run,manifest_path)
                            finally:source.write_bytes(original)
                    manifest['outputs']=[file_record(model)];runtime.write(snapshot,manifest)
                    with self.assertRaisesRegex(ValueError,'manifest-bound'):runtime.comsol_reuse(run,manifest_path)
            with self.assertRaisesRegex(ValueError,'model stage required'):
                runtime.materialize_tasks(run,ROOT,root/'existing.pa',saved_model_stage='prepared_saved')

    @unittest.skipUnless(os.name=='nt','Windows run junction lifecycle')
    def test_native_model_facts_survive_removal_of_run_execution_junction(self):
        """Project actual task paths; inert native facts never assert a real solve."""
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);producer,_=self.prepared(root);plan=runtime.prepare_run(producer)
            alias=root/'short-run'
            junction=root/'junction.ps1'
            junction.write_text("param($AliasPath,$TargetPath,$Action)\n$ErrorActionPreference='Stop'\n"
                "if($Action-eq'create'){$null=New-Item -ItemType Junction -Path $AliasPath -Target $TargetPath}\n"
                "else{if((Get-Item -LiteralPath $AliasPath).LinkType-ne'Junction'){throw 'Expected junction'};"
                "[IO.Directory]::Delete($AliasPath)}\n",encoding='utf-8')
            result=subprocess.run(['pwsh','-NoProfile','-File',str(junction),str(alias),str(producer),'create'],
                cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            try:
                self.assertEqual(alias.resolve(strict=True),producer.resolve(strict=True))
                task=runtime.materialize_tasks(alias,ROOT,root/'existing.pa')
                call=Path(task['matlab']).read_text()
                arguments=re.search(r"build_and_export_paired_accelerator_field\('([^']*)','([^']*)',''\);",call)
                self.assertIsNotNone(arguments,call)
                fact_plan=Path(arguments[1]);fact_model=Path(arguments[2])/'paired_accelerator_static.mph'
            finally:
                # Remove only the verified junction, never its scientific target.
                result=subprocess.run(['pwsh','-NoProfile','-File',str(junction),str(alias),str(producer),'remove'],
                    cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertFalse(alias.exists())
            self.assertEqual(fact_plan,producer/'inputs/bvp/paired_accelerator_static_field_plan.json')
            self.assertEqual(fact_model,producer/'comsol/paired_accelerator_static.mph')
            model=producer/'comsol/paired_accelerator_static.mph';model.write_bytes(b'inert model identity only')
            backend=Path('projects')/runtime.PROJECT/'comsol/build_and_export_paired_accelerator_field.m'
            consumer=root/'consumer';(consumer/'inputs/bvp').mkdir(parents=True)
            runtime.write(consumer/'inputs/bvp/paired_accelerator_static_field_plan.json',plan)
            for owner in (producer,consumer):
                target=owner/'inputs/runtime_snapshot'/backend;target.parent.mkdir(parents=True)
                shutil.copyfile(ROOT/backend,target)
            config=producer/'run_config.json';runtime.write(config,dict(schema_version=1,
                run_id='20261025_234000__test__python__paired-junction-source',project='instrument_assembly',
                mode='paired_accelerator_static_field',inputs={'plan':str(fact_plan),
                    'backend':str(producer/'inputs/runtime_snapshot'/backend)}))
            completion=producer/'comsol/comsol_field_solution.json'
            for stage in ('prepared_saved','solved_saved'):
                with self.subTest(stage=stage):
                    runtime.write(completion,dict(schema_version=1,role='oatof_paired_accelerator_static_field_solution',
                        status=stage,solution_present=stage=='solved_saved',solution_tag='sol1',study_tag='std1',
                        mesh_complete=True,tetrahedra=31,plan_path=str(fact_plan),model_path=str(fact_model)))
                    manifest=build_run_manifest(config,'failed',output_paths=[completion,model])
                    manifest_path=producer/'run_manifest.json';runtime.write(manifest_path,manifest)
                    runtime.write(consumer/'inputs/comsol_source_manifest.json',manifest)
                    self.assertEqual(runtime.comsol_reuse(consumer,manifest_path)['source_stage'],stage)

    def test_native_authorization_rejected_before_run_or_vendor(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run,author=self.prepared(root)
            result=subprocess.run(['pwsh','-NoProfile','-File',str(WORKFLOW/'execute.ps1'),
                '-Request',str(author/'request.json'),'-ArtifactRoot',str(root/'artifacts')],
                cwd=ROOT,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=30)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('requires SolverAuthorized',result.stderr)
            self.assertFalse((root/'artifacts').exists())

    def test_public_dry_run_publishes_managed_preparation_without_native(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);_,author=self.prepared(root)
            artifacts=root/'artifacts'
            artifacts.mkdir()
            initialize_capacity_ledger(artifacts,objects=[])
            run_id='20261025_010001__test__python__paired-static-entry'
            result=subprocess.run(['pwsh','-NoProfile','-File',str(WORKFLOW/'execute.ps1'),
                '-Request',str(author/'request.json'),'-ArtifactRoot',str(artifacts),
                '-Python',sys.executable,'-RunId',run_id,'-DryRun'],
                cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            run=artifacts/'projects/instrument_assembly/runs'/run_id
            summary=runtime.read(run/'summary.json')
            self.assertFalse(summary['native_executed'])
            self.assertEqual(runtime.read(run/'run_manifest.json')['status'],'success')
            self.assertTrue((run/'inputs/bvp/paired_accelerator.gem').is_file())
            self.assertFalse(any(run.rglob('*.pa')))
            self.assertFalse(any(run.rglob('*.mph')))

    def test_owner_retention_and_terminal_boundaries_close_success_and_failure(self):
        """Run actual owner boundaries and public lifecycle; skip all vendor work."""
        script=r"""param($Source,$RepoRoot,$Python,$ArtifactRoot,$Outcome,$RunId)
$ErrorActionPreference='Stop'
. (Join-Path $RepoRoot 'common/contracts/run_artifact_support.ps1')
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$owner=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.TryStatementAst]-and$null-ne$n.Finally},$false))[0]
$terminal=@($owner.Body.Statements|Where-Object{$_.Extent.Text-eq"`$stage='terminal_publication'"})[0]
$early=@($owner.Body.FindAll({param($n)$n-is[Management.Automation.Language.CommandAst]-and$n.GetCommandName()-eq'Apply-RunArtifactRetention'-and$n.Extent.StartOffset-lt$terminal.Extent.StartOffset},$true))
$success=[scriptblock]::Create((@($owner.Body.Statements|Where-Object{$_.Extent.StartOffset-ge$terminal.Extent.StartOffset}).Extent.Text-join"`n"))
$handler=[scriptblock]::Create(($owner.CatchClauses[0].Body.Statements.Extent.Text-join"`n"))
$finalizer=[scriptblock]::Create(($owner.Finally.Statements.Extent.Text-join"`n"))
$project='instrument_assembly';$software=@('Python lifecycle fixture');$reason='Inert owner-boundary lifecycle regression; no solver.'
$package=New-RunPackage -Python $Python -RepoRoot $RepoRoot -ArtifactRoot (Join-Path $ArtifactRoot 'projects/instrument_assembly') `
 -Project $project -Mode paired_accelerator_static_field -RunId $RunId -Software $software `
 -RetentionContractEnabled -RetentionClass solver_review -RetentionReason $reason `
 -CapacityLedgerLifecycleEnabled -CapacityLedgerArtifactRoot $ArtifactRoot -AdditionalDirectories @('comsol','simion')
$capacity=Enter-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -ArtifactRoot $ArtifactRoot `
 -RunDirectory $package.artifact_run_dir -CommittedNewBytes 0 -Owner ('paired-static:'+$RunId)
$lease=$null;$guard=$null;$buildAlias=$null;$terminalized=$false;$stage='inert_vendor_boundary'
$DryRun=$false;$reusedComsol=$false;$comsolSourceStage='';$plan=@{sample_points=@{count=2}}
$failureMessage=''
$sourceBranch=@($owner.Body.FindAll({param($n)$n-is[Management.Automation.Language.IfStatementAst]-and
 $n.Clauses[0].Item1.Extent.Text-eq'-not$DryRun-and$ComsolSourceManifest'},$true))
$renewal=@($owner.Body.FindAll({param($n)$n-is[Management.Automation.Language.CommandAst]-and
 $n.GetCommandName()-eq'Update-ArtifactWorkflowCapacitySession'-and$n.Extent.Text-like'*ProtectedPaths $protected*'},$true))
if($sourceBranch.Count-ne1-or$renewal.Count-ne1){throw 'Expected one actual model source/renewal boundary'}
$actualModel=Join-Path $ArtifactRoot 'original_model_owner/comsol/inert.mph'
$ComsolSourceManifest=Join-Path $ArtifactRoot 'selected_export_owner/run_manifest.json'
New-Item -ItemType Directory -Path (Split-Path $actualModel),(Split-Path $ComsolSourceManifest)-Force|Out-Null
[IO.File]::WriteAllText($actualModel,'INERT_IDENTITY_ONLY_NOT_A_MODEL')
[IO.File]::WriteAllText($ComsolSourceManifest,'{"fixture":"inert source boundary only"}')
$protected=@((Split-Path $ComsolSourceManifest));$cache=@{cache_key=('A'*64)};$budget=@{committed_new_bytes=0}
function Invoke-PairedPython {param($Code,$Arguments)
 [pscustomobject]@{model=[pscustomobject]@{path=$actualModel};source_stage='solved_saved'}
}
try{
 try{
  . ([scriptblock]::Create($sourceBranch[0].Extent.Text))
  $update=. ([scriptblock]::Create($renewal[0].Extent.Text));$capacity=$update.session
  if($capacity.protected_paths-notcontains$actualModel){throw 'Actual original model absent from renewed protection'}
  $stored=Get-Content (Join-Path $ArtifactRoot ('common/capacity_protection_leases/'+$capacity.lease_id+'.json')) -Raw|ConvertFrom-Json
  $relative=[IO.Path]::GetRelativePath($ArtifactRoot,$actualModel).Replace('\','/')
  if($stored.protected_paths-notcontains$relative){throw 'Public lease did not persist original model protection'}
  foreach($call in $early){$null=& ([scriptblock]::Create($call.Extent.Text))}
  Write-RunJson -Path (Join-Path $package.result_dir 'inert_boundary.json') -Value @{solver_executed=$false}
  if($Outcome-eq'failed'){throw 'INERT_SCIENTIFIC_STAGE_FAILURE'}
  . $success
 }catch{. $handler}
}catch{$failureMessage=$_.Exception.Message}
finally{. $finalizer}
$manifest=Get-Content -LiteralPath (Join-Path $package.artifact_run_dir 'run_manifest.json') -Raw|ConvertFrom-Json
if($manifest.status-ne$Outcome){throw "Owner terminal expected $Outcome; got $($manifest.status); $failureMessage"}
if($Outcome-eq'success'-and$failureMessage){throw $failureMessage}
if($Outcome-eq'failed'-and$failureMessage-ne'INERT_SCIENTIFIC_STAGE_FAILURE'){throw "Original failure changed: $failureMessage"}
$receipt=Get-Content (Join-Path $package.artifact_run_dir 'retention_actions.json') -Raw|ConvertFrom-Json
if($receipt.status-ne'complete'){throw 'Retention was not reconciled.'}
'OWNER_LIFECYCLE=PASS'
"""
        for outcome in ('success','failed'):
            with self.subTest(outcome=outcome),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);artifacts=root/'artifacts';artifacts.mkdir()
                initialize_capacity_ledger(artifacts,objects=[])
                wrapper=root/'owner_boundaries.ps1';wrapper.write_text(script,encoding='utf-8',newline='\n')
                run_id=f'20261026_040001__test__python__paired-owner-{outcome}'
                result=subprocess.run(['pwsh','-NoProfile','-File',str(wrapper),str(WORKFLOW/'execute.ps1'),
                    str(ROOT),sys.executable,str(artifacts),outcome,run_id],cwd=ROOT,capture_output=True,
                    text=True,encoding='utf-8',errors='replace',timeout=180)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertIn('OWNER_LIFECYCLE=PASS',result.stdout)
                run=artifacts/'projects/instrument_assembly/runs'/run_id
                self.assertEqual(runtime.read(run/'run_manifest.json')['status'],outcome)
                ledger=runtime.read(artifacts/'common/capacity_ledger.json')
                entry=next(row for row in ledger['objects'] if row['path']==run.relative_to(artifacts).as_posix())
                self.assertEqual(entry['status'],'ready')

    def test_invalid_saved_model_source_fails_before_any_vendor_and_seals_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);_,author=self.prepared(root)
            artifacts=root/'artifacts';artifacts.mkdir()
            initialize_capacity_ledger(artifacts,objects=[])
            wrong=artifacts/'projects/instrument_assembly/runs/20261025_010000__test__python__inert-producer/run_manifest.json'
            runtime.write(wrong,{'role':'not_a_terminal_run'})
            run_id='20261025_010002__test__python__paired-static-invalid-source'
            result=subprocess.run(['pwsh','-NoProfile','-File',str(WORKFLOW/'execute.ps1'),
                '-Request',str(author/'request.json'),'-ArtifactRoot',str(artifacts),
                '-Python',sys.executable,'-RunId',run_id,'-SolverAuthorized',
                '-ExecutionBudgetPath',str(root/'budget_never_consumed.json'),'-ComsolSourceManifest',str(wrong)],
                cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('terminal instrument_assembly COMSOL producer required',result.stderr)
            run=artifacts/'projects/instrument_assembly/runs'/run_id
            self.assertEqual(runtime.read(run/'run_manifest.json')['status'],'failed')
            self.assertEqual(runtime.read(run/'summary.json')['failure_stage'],'verify_saved_comsol_source')
            self.assertFalse((run/'inputs/execution_budget.json').exists())
            self.assertFalse(any(run.rglob('*.pa')))

    def test_actual_finally_releases_capacity_before_seal_and_never_rewrites_terminal(self):
        script=r"""param($Source,$Run)
$ErrorActionPreference='Stop'
$errors=$null;$tokens=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$owner=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.TryStatementAst]-and$null-ne$n.Finally},$false))[0]
$finalizer=[scriptblock]::Create(($owner.Finally.Statements.Extent.Text-join"`n"))
$script:released=$false;$terminalized=$true;$guard=$null;$buildAlias=$null
$capacity=@{fixture=$true};$package=@{run_config=(Join-Path $Run run_config.json)}
$RepoRoot='unused';$ArtifactRoot=$Run;$project='instrument_assembly';$reason='inert seal failure'
$Python='Fixture-Python'
function Exit-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session)$script:released=$true}
function Fixture-Python {
 if(-not$script:released){throw 'capacity not released before seal'}
 if($args-notcontains'seal-stopped-payload'){throw 'unexpected native invocation'}
 throw 'INERT_SEAL_FAILURE'
}
function Remove-RunPackageExecutionAlias {throw 'must not reach alias removal after seal failure'}
$before=[IO.File]::ReadAllText((Join-Path $Run run_manifest.json))
try{. $finalizer;throw 'seal failure swallowed'}catch{if($_.Exception.Message-ne'INERT_SEAL_FAILURE'){throw}}
if([IO.File]::ReadAllText((Join-Path $Run run_manifest.json))-cne$before){throw 'published terminal changed'}
'FINALIZER_FAILURE=PASS'
"""
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            runtime.write(root/'run_manifest.json',{'status':'success','science':'retained'})
            runtime.write(root/'run_config.json',{})
            path=root/'test.ps1';path.write_text(script,encoding='utf-8',newline='\n')
            result=subprocess.run(['pwsh','-NoProfile','-File',str(path),str(WORKFLOW/'execute.ps1'),str(root)],
                cwd=root,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('FINALIZER_FAILURE=PASS',result.stdout)

    def test_export_failure_publishes_saved_model_and_allows_explicit_reuse(self):
        """Real owner catch/public writer; inert bytes are not a native solved MPH."""
        script=r"""param($Source,$RepoRoot,$Python,$Run)
$ErrorActionPreference='Stop'
. (Join-Path $RepoRoot 'common/contracts/run_artifact_support.ps1')
$errors=$null;$tokens=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$owner=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.TryStatementAst]-and$null-ne$n.Finally},$false))[0]
$handler=[scriptblock]::Create(($owner.CatchClauses[0].Body.Statements.Extent.Text-join"`n"))
$package=@{run_dir=$Run;run_config=(Join-Path $Run run_config.json);summary=(Join-Path $Run summary.json)}
$lease=$null;$terminalized=$false;$software=@('Python inert test');$stage='comsol_field'
try{try{throw 'INERT_EXPORT_FAILURE_AFTER_SAVE'}catch{. $handler}}
catch{if($_.Exception.Message-ne'INERT_EXPORT_FAILURE_AFTER_SAVE'){throw}}
if(-not$terminalized){throw 'failed owner not published'}
'FAILED_MODEL_PUBLICATION=PASS'
"""
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);producer,_=self.prepared(root);plan=runtime.prepare_run(producer)
            runtime.write(producer/'run_config.json',dict(schema_version=1,project='instrument_assembly',
                run_id='20261025_010003__test__python__paired-export-failure',mode='paired_accelerator_static_field',inputs={}))
            backend=Path('projects')/runtime.PROJECT/'comsol/build_and_export_paired_accelerator_field.m'
            target=producer/'inputs/runtime_snapshot'/backend;target.parent.mkdir(parents=True)
            shutil.copyfile(ROOT/backend,target)
            model=producer/'comsol/paired_accelerator_static.mph';model.write_bytes(b'inert solved-model publication boundary')
            runtime.write(producer/'comsol/comsol_field_solution.json',dict(
                schema_version=1,role='oatof_paired_accelerator_static_field_solution',
                status='solved_saved',solution_present=True,solution_tag='sol1',
                plan_path=str(producer/'inputs/bvp/paired_accelerator_static_field_plan.json'),model_path=str(model)))
            wrapper=root/'publish_failure.ps1';wrapper.write_text(script,encoding='utf-8',newline='\n')
            result=subprocess.run(['pwsh','-NoProfile','-File',str(wrapper),str(WORKFLOW/'execute.ps1'),
                str(ROOT),sys.executable,str(producer)],cwd=producer,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            manifest=runtime.read(producer/'run_manifest.json')
            self.assertEqual(manifest['status'],'failed')
            self.assertEqual(runtime.read(producer/'summary.json')['reason'],'INERT_EXPORT_FAILURE_AFTER_SAVE')
            bound={Path(row['path']).name for row in manifest['outputs']}
            self.assertTrue({'paired_accelerator_static.mph','comsol_field_solution.json'}<=bound)
            consumer=root/'next';(consumer/'inputs/bvp').mkdir(parents=True)
            runtime.write(consumer/'inputs/bvp/paired_accelerator_static_field_plan.json',plan)
            runtime.write(consumer/'inputs/comsol_source_manifest.json',manifest)
            frozen=consumer/'inputs/runtime_snapshot'/backend;frozen.parent.mkdir(parents=True)
            shutil.copyfile(ROOT/backend,frozen)
            restored=runtime.comsol_reuse(consumer,producer/'run_manifest.json')
            self.assertEqual(Path(restored['model']['path']),model)
            tasks=runtime.materialize_tasks(consumer,ROOT,root/'unused.pa',saved_model=model)
            self.assertIn(model.as_posix(),Path(tasks['matlab']).read_text())
            plan_path=consumer/'inputs/bvp/paired_accelerator_static_field_plan.json'
            for field,value in (('global_automatic_level',7),
                                ('electrode_boundary_maximum_element_size_mm',.25),
                                ('electrode_boundary_growth_rate',1.2)):
                with self.subTest(field=field):
                    changed=runtime.read(plan_path)
                    changed['numerical_domain']['comsol_mesh'][field]=value
                    runtime.write(plan_path,changed)
                    with self.assertRaisesRegex(ValueError,'common BVP differs'):
                        runtime.comsol_reuse(consumer,producer/'run_manifest.json')
                    runtime.write(plan_path,plan)
            frozen.write_bytes(frozen.read_bytes()+b'\n% changed backend\n')
            self.assertEqual(runtime.comsol_reuse(consumer,producer/'run_manifest.json')['source_stage'],'solved_saved')

    def test_working_field_identity_excludes_sampling_and_comsol_only_mesh(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run,_=self.prepared(root);runtime.prepare_run(run)
            executable=root/'inert_simion.exe';executable.write_bytes(b'identity-only; never executed')
            original=runtime.cache_plan(run,ROOT,executable,root/'cache')
            plan_path=run/'inputs/bvp/paired_accelerator_static_field_plan.json'
            plan=runtime.read(plan_path)
            plan['sample_points']['count']=1000
            plan['numerical_domain']['comsol_mesh'] = dict(global_automatic_level=7,
                electrode_boundary_maximum_element_size_mm=.25, electrode_boundary_growth_rate=1.2)
            runtime.write(plan_path,plan)
            same=runtime.cache_plan(run,ROOT,executable,root/'cache')
            self.assertEqual(original['cache_key'],same['cache_key'])
            key=next(iter(plan['static_on_electrode_voltages_v']))
            plan['static_on_electrode_voltages_v'][key]+=1.
            runtime.write(plan_path,plan)
            self.assertNotEqual(original['cache_key'],runtime.cache_plan(run,ROOT,executable,root/'cache')['cache_key'])

    def test_public_cache_build_verify_publish_hit_never_copies_hit_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run,_=self.prepared(root);runtime.prepare_run(run)
            executable=root/'inert_simion.exe';executable.write_bytes(b'not executed')
            public=public_cache_tests.PAFamilyCacheTest()
            public.setUp();self.addCleanup(public.tearDown)
            _,cache=public._artifact_cache()
            governed=public.producer_run_config.parent
            shutil.copytree(run/'inputs',governed/'inputs')
            shutil.copytree(run/'logs',governed/'logs')
            run=governed
            plan=runtime.cache_plan(run,ROOT,executable,cache)
            first=runtime.advance_cache(run,plan)
            self.assertEqual(first['action_required'],'build')
            payload=Path(first['build_directory'])/runtime.PA_NAME
            payload.write_bytes(b'inert publication test member; not a qualified PA')
            prepared=runtime.advance_cache(run,plan)
            self.assertEqual(prepared['action_required'],'verify')
            evidence=run/'logs/native_inert_boundary.txt';evidence.write_text('inert transaction wiring only')
            published=runtime.advance_cache(run,plan,evidence)
            self.assertEqual(published['action_required'],'complete')
            with patch('shutil.copyfile',side_effect=AssertionError('HIT must not materialize PA')):
                hit=runtime.advance_cache(run,plan)
            self.assertEqual(hit['generation_directory'],published['generation_directory'])
            self.assertTrue((Path(hit['generation_directory'])/runtime.PA_NAME).is_file())

    def test_terminal_producer_handoff_uses_public_transaction_and_canonical_run_id(self):
        public=public_cache_tests.PAFamilyCacheTest()
        public.setUp();self.addCleanup(public.tearDown)
        artifacts,cache=public._artifact_cache()
        predecessor=public.producer_run_config.parent
        (predecessor/'inputs').mkdir()
        identity=public_cache_tests.identity()
        runtime.write(predecessor/'inputs/pa_cache_identity.json',identity)
        config=runtime.read(public.producer_run_config)
        config['artifact_retention']=dict(policy_version=1,**{'class':'solver_review'},reason='inert handoff regression')
        config['inputs']={'identity':str(predecessor/'inputs/pa_cache_identity.json')}
        runtime.write(public.producer_run_config,config)
        plan=dict(cache_root=str(cache),cache_key=runtime.canonical_pa_family_cache_key(identity),
                  identity=identity,filenames=list(public.names))
        first=runtime.advance_cache(predecessor,plan)
        scratch=Path(first['scratch_directory'])/'working.pa#'
        scratch.write_bytes(b'inert scratch is preserved, never certified as a completed field')
        runtime.write(predecessor/'run_manifest.json',build_run_manifest(public.producer_run_config,'failed'))
        record_capacity_object(artifacts,path=predecessor,object_class='rebuildable_payload',bytes_count=0,
            status='writing',owner=predecessor.parent.parent.name,recovery_reason='inert producer stopped',
            review_deadline='2026-11-01')
        stopped=seal_checkpoint(artifacts,public.producer_run_config,owner=predecessor.parent.parent.name,
            writing_stopped=True,retain_payload=True,retention_reason='inert handoff regression')
        receipt=public.root/'stopped_receipt.json';runtime.write(receipt,stopped)
        successor=predecessor.with_name('20261025_220000__test__python__paired-successor')
        (successor/'inputs').mkdir(parents=True)
        config['run_id']=successor.name;config['inputs']={}
        runtime.write(successor/'run_config.json',config)
        record_capacity_object(artifacts,path=successor,object_class='rebuildable_payload',bytes_count=0,
            status='writing',owner=predecessor.parent.parent.name,recovery_reason='inert successor active',
            review_deadline='2026-11-01')
        session=dict(lease_id='paired-handoff-fixture',owner='paired-successor-fixture')
        create_capacity_protection_lease(artifacts,lease_id=session['lease_id'],owner=session['owner'],
            ttl_seconds=300,protected_cache_keys=[plan['cache_key']],protected_paths=[successor])
        transaction=Path(first['transaction_directory'])/'transaction.json'
        before=transaction.read_bytes()
        with self.assertRaisesRegex(ValueError,'explicit public stopped receipt'):
            runtime.advance_cache(successor,plan,capacity_session=session)
        self.assertEqual(transaction.read_bytes(),before)
        changed=dict(plan,identity={**identity,'handoff_invalid_geometry':'changed'})
        with self.assertRaisesRegex(ValueError,'scientific identity differs'):
            runtime.advance_cache(successor,changed,capacity_session=session,producer_stopped_receipt=receipt)
        self.assertEqual(transaction.read_bytes(),before)
        alias=public.root/'run_short_alias'
        if os.name == 'nt':
            linked=subprocess.run(['cmd','/c','mklink','/J',str(alias),str(successor)],
                cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
            self.assertEqual(linked.returncode,0,linked.stdout+linked.stderr)
        else:
            alias.symlink_to(successor,target_is_directory=True)
        resumed=runtime.advance_cache(alias,plan,capacity_session=session,producer_stopped_receipt=receipt)
        self.assertEqual(resumed['action_required'],'build')
        actual=runtime.read(transaction)
        self.assertEqual(actual['owner'],'paired-static:'+successor.name)
        self.assertEqual(Path(actual['producer']['run_config_path']),successor/'run_config.json')
        self.assertEqual(actual['producer_handoff']['prior_owner'],'paired-static:'+predecessor.name)
        self.assertEqual(actual['files'],[])
        self.assertIsNone(actual['inventory_sha256'])
        self.assertEqual(scratch.read_bytes(),b'inert scratch is preserved, never certified as a completed field')
        self.assertEqual(runtime.advance_cache(alias,plan)['action_required'],'build')

    def test_terminal_sealed_inventory_is_verified_and_published_without_handoff_or_rebuild(self):
        public=public_cache_tests.PAFamilyCacheTest()
        public.setUp();self.addCleanup(public.tearDown)
        artifacts,cache=public._artifact_cache()
        predecessor=public.producer_run_config.parent
        (predecessor/'inputs').mkdir();(predecessor/'logs').mkdir()
        identity=public_cache_tests.identity()
        runtime.write(predecessor/'inputs/pa_cache_identity.json',identity)
        config=runtime.read(public.producer_run_config)
        config['artifact_retention']=dict(policy_version=1,**{'class':'solver_review'},reason='inert sealed inventory regression')
        config['inputs']={'identity':str(predecessor/'inputs/pa_cache_identity.json')}
        runtime.write(public.producer_run_config,config)
        plan=dict(cache_root=str(cache),cache_key=runtime.canonical_pa_family_cache_key(identity),
                  identity=identity,filenames=list(public.names),verifier_path=str(ROOT/'common/simion/native_completion.py'))
        first=runtime.advance_cache(predecessor,plan)
        payload=Path(first['build_directory'])
        for name in public.names:(payload/name).write_bytes(b'inert transaction member; not a qualified PA')
        sealed=runtime.advance_cache(predecessor,plan)
        self.assertEqual(sealed['action_required'],'verify')
        transaction=Path(sealed['transaction_directory'])/'transaction.json'
        before=runtime.read(transaction)
        self.assertTrue(before['inventory_sha256'])
        runtime.write(predecessor/'run_manifest.json',build_run_manifest(public.producer_run_config,'failed'))
        record_capacity_object(artifacts,path=predecessor,object_class='rebuildable_payload',bytes_count=0,
            status='writing',owner=predecessor.parent.parent.name,recovery_reason='inert producer stopped',
            review_deadline='2026-11-01')
        seal_checkpoint(artifacts,public.producer_run_config,owner=predecessor.parent.parent.name,
            writing_stopped=True,retain_payload=True,retention_reason='inert sealed inventory regression')
        successor=predecessor.with_name('20261025_230000__test__python__paired-sealed-successor')
        (successor/'inputs').mkdir(parents=True);(successor/'logs').mkdir()
        config['run_id']=successor.name;config['inputs']={}
        runtime.write(successor/'run_config.json',config)
        record_capacity_object(artifacts,path=successor,object_class='rebuildable_payload',bytes_count=0,
            status='writing',owner=predecessor.parent.parent.name,recovery_reason='inert successor active',
            review_deadline='2026-11-01')
        resumed=runtime.advance_cache(successor,plan)
        self.assertEqual(resumed['action_required'],'verify')
        self.assertEqual(resumed['build_directory'],sealed['build_directory'])
        after=runtime.read(transaction)
        for field in ('owner','producer','files','inventory_sha256'):self.assertEqual(after[field],before[field])
        self.assertNotIn('producer_handoff',after)
        original=runtime.read(successor/'inputs/pa_original_producer.json')
        self.assertEqual(original['owner'],before['owner'])
        self.assertEqual(original['inventory_sha256'],before['inventory_sha256'])
        evidence=successor/'logs/inert_native_facts.txt';evidence.write_text('inert publication wiring only',encoding='utf-8')
        published=runtime.advance_cache(successor,plan,evidence)
        self.assertEqual(published['action_required'],'complete')
        self.assertEqual(runtime.read(transaction)['owner'],before['owner'])
        for name in public.names:
            self.assertEqual((Path(published['generation_directory'])/name).read_bytes(),
                             b'inert transaction member; not a qualified PA')


if __name__=='__main__':unittest.main()
