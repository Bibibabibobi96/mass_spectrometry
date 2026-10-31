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
    def test_completed_simion_samples_reuse_bound_identity_without_pa_or_model_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run,producer,model,samples,_,_=self.completed_comsol_source(root)
            runtime.comsol_reuse(run,producer/'run_manifest.json')
            cache_identity=dict(geometry='TEST_ONLY frozen BVP',mesh=[1,1,1])
            identity=producer/'inputs/pa_cache_identity.json';runtime.write(identity,cache_identity)
            exporter_relative=Path('projects/single_reflection_oa_tof_mass_analyzer/simion/export_paired_accelerator_field.lua')
            exporter=producer/'inputs/runtime_snapshot'/exporter_relative;exporter.parent.mkdir(parents=True);shutil.copyfile(ROOT/exporter_relative,exporter)
            simion=producer/'results/simion_field_samples.csv';simion.parent.mkdir(exist_ok=True);shutil.copyfile(samples,simion)
            facts=producer/'logs/simion_field_native_facts.txt';facts.parent.mkdir(exist_ok=True)
            facts.write_text('backend=SIMION\napi=pa:field_vc\nnative_field_unit=V/gu\nexport_field_unit=V/m\nfield_sign=negative_potential_gradient\npoint_count=115\n')
            config=runtime.read(producer/'run_config.json');config['inputs'].update(simion_identity=str(identity),simion_exporter=str(exporter));runtime.write(producer/'run_config.json',config)
            outputs=[Path(row['path']) for row in runtime.read(producer/'run_manifest.json')['outputs']]+[simion,facts]
            manifest=build_run_manifest(producer/'run_config.json','success',output_paths=outputs);runtime.write(producer/'run_manifest.json',manifest);runtime.write(run/'inputs/comsol_source_manifest.json',manifest)
            model.unlink()
            with patch.object(runtime,'verify_record',wraps=runtime.verify_record) as verified:
                selected=runtime.completed_simion_exports(run,producer/'run_manifest.json',dict(identity=cache_identity),ROOT)
            self.assertEqual(Path(selected['samples']['path']),simion)
            self.assertFalse(any(Path(call.args[1]['path'])==model or Path(call.args[1]['path']).suffix in {'.pa','.pa0','.mph'} for call in verified.call_args_list))
            self.assertIsNone(runtime.completed_simion_exports(run,producer/'run_manifest.json',dict(identity=dict(cache_identity,mesh=[2,1,1])),ROOT))
            facts.write_text(facts.read_text()+'corruption\n')
            with self.assertRaises(AssertionError): runtime.completed_simion_exports(run,producer/'run_manifest.json',dict(identity=cache_identity),ROOT)


    def capacity_isolated_owner(self, root):
        """Startup capacity admission is inert; lease and lifecycle operations remain real."""
        source=(WORKFLOW/'execute.ps1').read_text(encoding='utf-8')
        # dependencies.ps1 reloads the public capacity adapter. Install the
        # fixture after that import so host disk policy stays outside this test.
        boundary=". (Join-Path $RepoRoot 'integrations/runtime/dependencies.ps1')"
        self.assertEqual(source.count(boundary),1)
        owner=root/'inert_capacity_owner.ps1'
        owner.write_text(source.replace(boundary,boundary+"\nfunction Invoke-ArtifactCapacityGate { Write-Host 'TEST_CAPACITY_ADMISSION=ISOLATED'; [pscustomobject]@{satisfied_after_apply=$true} }"),
            encoding='utf-8',newline='\n')
        return owner

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

    def completed_comsol_source(self, root):
        """Publish 115 inert sample rows; model bytes never represent a solve."""
        root=root.resolve()
        run,_=self.prepared(root);plan=runtime.prepare_run(run)
        producer=root/'producer';(producer/'comsol').mkdir(parents=True)
        points=producer/'inputs/bvp/paired_accelerator_field_points.csv'
        points.parent.mkdir(parents=True)
        frame=__import__('pandas').read_csv(plan['sample_points']['path']).iloc[[0]*115].copy()
        frame['point_id']=range(1,116);frame.to_csv(points,index=False)
        previous=copy.deepcopy(plan);previous['sample_points']=dict(file_record(points),count=115)
        plan_path=producer/'inputs/bvp/paired_accelerator_static_field_plan.json'
        runtime.write(plan_path,previous)
        runtime.write(run/'inputs/bvp/paired_accelerator_static_field_plan.json',previous)
        backend=Path('projects')/runtime.PROJECT/'comsol/build_and_export_paired_accelerator_field.m'
        frozen=producer/'inputs/runtime_snapshot'/backend;frozen.parent.mkdir(parents=True)
        shutil.copyfile(ROOT/backend,frozen)
        model=producer/'comsol/paired_accelerator_static.mph';model.write_bytes(b'inert model identity only')
        solution=producer/'comsol/comsol_field_solution.json'
        runtime.write(solution,dict(schema_version=1,role='oatof_paired_accelerator_static_field_solution',
            status='solved_saved',solution_present=True,solution_tag='sol1',
            plan_path=str(plan_path),model_path=str(model)))
        samples=producer/'comsol/comsol_field_samples.csv'
        for axis in 'xyz':frame[f'E{axis}_V_per_m']=0.
        frame.to_csv(samples,index=False)
        facts=producer/'comsol/comsol_field_native_facts.json'
        runtime.write(facts,dict(backend='COMSOL',coordinate_unit='mm',field_unit=['V/m']*3,
            point_count=115,plan_path=str(plan_path),model_path=str(model),sample_path=str(samples)))
        config=producer/'run_config.json'
        runtime.write(config,dict(schema_version=1,run_id='20261026_010000__test__python__inert-static-exports',
            project='instrument_assembly',mode='paired_accelerator_static_field',
            inputs={'plan':str(plan_path),'points':str(points),'backend':str(frozen)}))

        def publish(outputs=None):
            manifest=build_run_manifest(config,'success',output_paths=outputs or [solution,model,samples,facts])
            runtime.write(producer/'run_manifest.json',manifest)
            runtime.write(run/'inputs/comsol_source_manifest.json',manifest)
        publish()
        return run,producer,model,samples,facts,publish

    def test_completed_static_exports_reuse_115_points_without_model_read_or_matlab(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run,producer,model,samples,facts,_=self.completed_comsol_source(root)
            before=(samples.read_bytes(),facts.read_bytes())
            with patch.object(runtime,'verify_record',wraps=runtime.verify_record) as verified:
                source=runtime.comsol_reuse(run,producer/'run_manifest.json')
            self.assertFalse(any(Path(call.args[1]['path'])==model for call in verified.call_args_list))
            self.assertEqual(Path(source['exports']['samples']['path']),samples)
            self.assertEqual(Path(source['exports']['native_facts']['path']),facts)
            model.unlink()  # Completed exports do not consume this inert payload.
            self.assertEqual(runtime.comsol_reuse(run,producer/'run_manifest.json')['exports'],source['exports'])
            tasks=runtime.materialize_tasks(run,ROOT,root/'not-opened.pa',
                saved_model=model,comsol_required=False)
            self.assertIsNone(tasks['matlab'])
            self.assertTrue(Path(tasks['lua']).is_file())
            self.assertFalse((run/'inputs/run_comsol_field.m').exists())
            self.assertEqual((samples.read_bytes(),facts.read_bytes()),before)

            # A published export consumer carries the same original facts and
            # explicit bindings; it must not invent a new model or walk history.
            inputs={'plan':str(run/'inputs/bvp/paired_accelerator_static_field_plan.json'),
                'source':str(run/'inputs/comsol_source.json'),
                'source_manifest':str(run/'inputs/comsol_source_manifest.json')}
            inputs.update({'completed_'+name:record['path'] for name,record in source['exports'].items()})
            runtime.write(run/'run_config.json',dict(schema_version=1,project='instrument_assembly',
                run_id='20261026_010001__test__python__inert-export-consumer',
                mode='paired_accelerator_static_field',inputs=inputs))
            manifest=build_run_manifest(run/'run_config.json','success')
            runtime.write(run/'run_manifest.json',manifest)
            next_run=root/'next';(next_run/'inputs/bvp').mkdir(parents=True)
            shutil.copyfile(run/'inputs/bvp/paired_accelerator_static_field_plan.json',
                next_run/'inputs/bvp/paired_accelerator_static_field_plan.json')
            runtime.write(next_run/'inputs/comsol_source_manifest.json',manifest)
            with patch.object(runtime,'verify_record',wraps=runtime.verify_record) as verified:
                reused=runtime.comsol_reuse(next_run,run/'run_manifest.json')
            self.assertEqual(reused['exports'],source['exports'])
            self.assertFalse(any(Path(call.args[1]['path'])==model for call in verified.call_args_list))

    def test_new_points_or_incomplete_exports_keep_saved_model_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run,producer,model,samples,facts,publish=self.completed_comsol_source(root)
            path=run/'inputs/bvp/paired_accelerator_static_field_plan.json';original=runtime.read(path)
            changed=copy.deepcopy(original);points=run/'inputs/new_points.csv'
            frame=__import__('pandas').read_csv(original['sample_points']['path'])
            frame.loc[0,'x_mm']+=.01;frame.to_csv(points,index=False)
            changed['sample_points']=dict(file_record(points),count=115);runtime.write(path,changed)
            solution=producer/'comsol/comsol_field_solution.json'
            variants=[('new_points',None),('no_facts',[solution,model,samples]),
                      ('no_samples',[solution,model,facts]),('no_exports',[solution,model])]
            for name,outputs in variants:
                with self.subTest(reason=name):
                    runtime.write(path,changed if name=='new_points' else original);publish(outputs)
                    with patch.object(runtime,'verify_record',wraps=runtime.verify_record) as verified:
                        source=runtime.comsol_reuse(run,producer/'run_manifest.json')
                    self.assertIsNone(source['exports'])
                    self.assertEqual(sum(Path(c.args[1]['path'])==model for c in verified.call_args_list),1)
                    task=runtime.materialize_tasks(run,ROOT,root/'not-opened.pa',saved_model=model)
                    self.assertIn(model.as_posix(),Path(task['matlab']).read_text())

    def test_declared_export_corruption_and_wrong_native_identity_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run,producer,_,samples,facts,publish=self.completed_comsol_source(root)
            for path in (samples,facts):
                original=path.read_bytes();path.write_bytes(original+b'changed')
                try:
                    with self.subTest(corrupt=path.name),self.assertRaises((ValueError,AssertionError)):
                        runtime.comsol_reuse(run,producer/'run_manifest.json')
                finally:path.write_bytes(original)
            original=runtime.read(facts)
            for key,value in (('model_path',str(root/'wrong.mph')),('sample_path',str(root/'other.csv')),
                              ('point_count',114),('backend','SIMION'),('field_unit',['V/mm']*3),
                              ('coordinate_unit','m'),('plan_path',str(root/'unbound.json'))):
                with self.subTest(identity=key):
                    runtime.write(facts,dict(original,**{key:value}));publish()
                    with self.assertRaises(ValueError):runtime.comsol_reuse(run,producer/'run_manifest.json')
            runtime.write(facts,original);publish()

    def test_actual_owner_completed_exports_skip_comsol_and_report_native_scope(self):
        """Execute the actual branch/task/summary AST with an inert launcher."""
        script=r"""param($Source,$Directory)
$ErrorActionPreference='Stop'
$errors=$null;$tokens=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$branch=$ast.Find({param($n)$n-is[Management.Automation.Language.IfStatementAst]-and
 $n.Clauses[0].Item1.Extent.Text-eq'$completedComsolExports'-and$n.Extent.Text-like'*comsol_bootstrap.txt*'},$true)
$summaryNode=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and
 $n.Left.Extent.Text-eq'$summary'-and$n.Extent.Text-like"*role='paired_accelerator_static_field_summary'*"},$true)
if($null-eq$branch-or$null-eq$summaryNode){throw 'Actual owner boundaries missing'}
$RepoRoot=$Directory;$Python='unused';$RunId='inert';$stage='inert';$DryRun=$false
$package=@{run_dir=$Directory;artifact_run_dir=$Directory;input_dir=$Directory;log_dir=$Directory;summary='unused'}
$null=New-Item -ItemType Directory -Path (Join-Path $Directory logs) -Force
$nativeOperations=[Collections.Generic.List[object]]::new();$nativeOperations.Add(@{TEST_ONLY='inert SIMION boundary'})
$failure=$null;$hostReleaseUnknown=$false;$writerUnknown=$false;$ResultPath='TEST_ONLY';$phaseTimings=@{};$runClock=[Diagnostics.Stopwatch]::StartNew();$completedSimionExports=$null
$frozen=@{execution_root=$Directory};$pa='unused';$budget=@{host_budgets=@{comsol=@{}};limits=@{}}
$plan=@{sample_points=@{count=115}};$reusedComsol=$true;$comsolSourceStage='solved_saved'
$launcher=Join-Path $Directory 'common/comsol/run_comsol_r2025b.ps1'
$null=New-Item -ItemType Directory -Path (Split-Path $launcher) -Force
@'
param($TaskScript,$ReportPath,$ResourceBudgets,$RunId,$CompletionPath,$Limits,$RunDir,$UsagePath)
[IO.File]::WriteAllText($CompletionPath,'{"operations":[],"host_release":{"inherited":false,"token":"TEST_ONLY_NO_NATIVE","result":{"status":"released","token":"TEST_ONLY_NO_NATIVE"},"error":null}}')
$global:nativeCalls++;$global:LASTEXITCODE=0
'@ | Set-Content -LiteralPath $launcher
$global:nativeCalls=0
function Invoke-PairedPython {param($Code,$Arguments) $script:taskInvocation=@($Code,$Arguments);@{lua='inert.lua';matlab='inert.m'}}
function Set-PairedStage {param($Name);$script:stage=$Name}
foreach($completed in @($true,$false)){
 $completedComsolExports=if($completed){@{samples=@{path='borrowed-original.csv'}}}else{$null}
 $savedModel=if($completed){'absent-original.mph'}else{''}
 foreach($name in @('$comsolNativeExecuted','$taskArguments','$taskCode','$tasks')){
  $assignment=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq$name},$true)
  . ([scriptblock]::Create($assignment.Extent.Text))
 }
 if($taskArguments[5]-ne$(if($completed){'false'}else{'true'})){throw 'MATLAB materialization decision differs'}
 if(-not$taskCode.Contains('comsol_required=sys.argv[6]')){throw 'Factory does not receive the actual decision'}
 $assignment=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq'$comsolSamples'},$true)
 . ([scriptblock]::Create($assignment.Extent.Text))
 . ([scriptblock]::Create($branch.Extent.Text))
 . ([scriptblock]::Create($summaryNode.Extent.Text))
 $publishedSummary=$summary
 if($completed){
  if($global:nativeCalls-ne0-or$comsolSamples-ne'borrowed-original.csv'){throw 'Completed exports invoked native or changed sample ownership'}
  if(-not$publishedSummary.comsol_reused_exports-or$publishedSummary.comsol_native_executed){throw 'Reused COMSOL summary scope differs'}
 }else{
  if($global:nativeCalls-ne1-or-not$publishedSummary.comsol_native_executed){throw 'Cold/native branch silently skipped'}
 }
 if(-not$publishedSummary.native_executed){throw 'SIMION diagnostic execution must not be relabelled as wholly nonnative'}
}
'OWNER_EXPORT_REUSE=PASS'
"""
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);wrapper=root/'owner_export_reuse.ps1'
            wrapper.write_text(script,encoding='utf-8',newline='\n')
            result=subprocess.run(['pwsh','-NoProfile','-File',str(wrapper),
                str(WORKFLOW/'execute.ps1'),str(root)],cwd=ROOT,capture_output=True,
                text=True,encoding='utf-8',errors='replace',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('OWNER_EXPORT_REUSE=PASS',result.stdout)

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
            root=Path(directory).resolve();_,author=self.prepared(root)
            artifacts=root/'artifacts'
            artifacts.mkdir()
            initialize_capacity_ledger(artifacts,objects=[])
            run_id='20261025_010001__test__python__paired-static-entry'
            result=subprocess.run(['pwsh','-NoProfile','-File',str(self.capacity_isolated_owner(root)),
                '-Request',str(author/'request.json'),'-ArtifactRoot',str(artifacts),
                '-Python',sys.executable,'-RunId',run_id,'-DryRun','-RepoRoot',str(ROOT)],
                cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            run=artifacts/'projects/instrument_assembly/runs'/run_id
            self.assertIn('TEST_CAPACITY_ADMISSION=ISOLATED', result.stdout)
            summary=runtime.read(run/'summary.json')
            self.assertFalse(summary['native_executed'])
            self.assertEqual(runtime.read(run/'run_manifest.json')['status'],'success')
            self.assertTrue((run/'inputs/bvp/paired_accelerator.gem').is_file())
            self.assertFalse(any(run.rglob('*.pa')))
            self.assertFalse(any(run.rglob('*.mph')))

    def test_invalid_saved_model_source_fails_before_any_vendor_and_seals_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();_,author=self.prepared(root)
            artifacts=root/'artifacts';artifacts.mkdir()
            initialize_capacity_ledger(artifacts,objects=[])
            wrong=artifacts/'projects/instrument_assembly/runs/20261025_010000__test__python__inert-producer/run_manifest.json'
            runtime.write(wrong,{'role':'not_a_terminal_run'})
            run_id='20261025_010002__test__python__paired-static-invalid-source'
            budget=root/'budget_not_parsed.json'
            runtime.write(budget,{'TEST_ONLY':'source rejected before budget interpretation'})
            result=subprocess.run(['pwsh','-NoProfile','-File',str(self.capacity_isolated_owner(root)),
                '-Request',str(author/'request.json'),'-ArtifactRoot',str(artifacts),
                '-Python',sys.executable,'-RunId',run_id,'-SolverAuthorized',
                '-ExecutionBudgetPath',str(budget),'-ComsolSourceManifest',str(wrong),'-RepoRoot',str(ROOT)],
                cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('terminal instrument_assembly COMSOL producer required',result.stderr)
            run=artifacts/'projects/instrument_assembly/runs'/run_id
            self.assertEqual(runtime.read(run/'run_manifest.json')['status'],'failed')
            self.assertEqual(runtime.read(run/'summary.json')['failure_stage'],'verify_saved_comsol_source')
            self.assertEqual((run/'inputs/execution_budget.json').read_bytes(),budget.read_bytes())
            self.assertFalse(any(run.rglob('*.pa')))

    def test_export_failure_publishes_saved_model_and_allows_explicit_reuse(self):
        """Failed-owner saved-source reuse; inert bytes are not a native solved MPH."""
        # The shared finalizer owns publication faults. This test exercises the
        # saved-source reader against an explicitly failed, manifest-bound owner.
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
            config=runtime.read(producer/'run_config.json')
            config['inputs'].update({str(path.relative_to(producer/'inputs')):str(path) for path in (producer/'inputs').rglob('*') if path.is_file()})
            runtime.write(producer/'run_config.json',config)
            manifest=build_run_manifest(producer/'run_config.json','failed',
                output_paths=[model,producer/'comsol/comsol_field_solution.json'])
            runtime.write(producer/'run_manifest.json',manifest)
            self.assertEqual(manifest['status'],'failed')
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
