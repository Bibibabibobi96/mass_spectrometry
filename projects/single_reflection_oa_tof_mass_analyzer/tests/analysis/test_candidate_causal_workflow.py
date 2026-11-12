from __future__ import annotations
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from msplatform.contracts.machine_contracts import load_json
from common.contracts.capacity_ledger import load_capacity_ledger
from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_run_lifecycle import start_candidate_run
from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_source_closure import frozen_source_path
from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import run_candidate_workflow as candidate_workflow
from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow import CandidateWorkflowError, run_candidate_workflow
from projects.single_reflection_oa_tof_mass_analyzer.tests.analysis.test_support.candidate_fixtures import CandidateFixtures, PROJECT_ROOT, REPO_ROOT
from projects.single_reflection_oa_tof_mass_analyzer.tests.analysis.test_candidate_workflow import (
    cold_export_failed_child_fixture,
    postprocess_public_entry,
    postprocess_source_fixture,
)


class CandidateAnalysisReuseTests(CandidateFixtures, unittest.TestCase):
    def test_normal_reuse_reuses_same_authority_and_reanalyzes_changed_authority(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis import prepare_candidate_run as preparation
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import candidate_comsol_stage
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            _,plan=self.native_workflow_plan(root,"20261031_130000")
            observed=[]
            base=self.native_fake_executor(observed)
            def producer(stage,runtime,simion):
                evidence=base(stage,runtime,simion)
                if stage["stage_id"]=="comsol_candidate":
                    run=Path(runtime["run_root"])
                    request=Path(evidence["analysis_request"])
                    receipt=candidate_comsol_stage.analyze_detector_request(request,runtime["execution_source_closure"],
                        run/"logs/analysis.log",runtime=candidate_workflow)
                    evidence["analysis_receipt"]=str(receipt)
                return evidence
            parent,_=run_candidate_workflow(plan,sys.executable,stage_executor=producer)
            before={path:path.read_bytes() for path in parent.rglob("*") if path.is_file()}
            ledger_before=load_capacity_ledger(root/"artifacts")
            authority="projects/single_reflection_oa_tof_mass_analyzer/config/analysis_contract.json"
            parent_closure=load_json(parent/"candidate_workflow_plan.json")["execution_source_closure"]
            parent_analysis=Path(frozen_source_path(parent_closure,authority)).read_bytes()
            original_freeze=preparation.freeze_candidate_source_closure
            analysis=root/"explicit_analysis.json"
            document=load_json(PROJECT_ROOT/"config/analysis_contract.json")
            document["kde"]["bandwidth_multiplier"]=1.2
            analysis.write_text(json.dumps(document),encoding="utf-8")
            children=[]
            for index,case in enumerate(("same","changed")):
                with self.subTest(case=case):
                    def freeze(*args,**kwargs):
                        if case=="changed":
                            kwargs["analysis_contract"]=analysis
                        return original_freeze(*args,**kwargs)
                    with mock.patch.object(preparation,"freeze_candidate_source_closure",side_effect=freeze):
                        _,child_plan=self.native_workflow_plan(root,f"20261031_13{index+1}000")
                    child_authority=Path(frozen_source_path(load_json(child_plan)["execution_source_closure"],authority))
                    self.assertEqual(child_authority.read_bytes(),analysis.read_bytes() if case=="changed" else parent_analysis)
                    if case=="changed":
                        self.assertNotEqual(child_authority.read_bytes(),parent_analysis)
                    child_observed=[]
                    with mock.patch.object(candidate_workflow,"_run_managed_stage_command",side_effect=AssertionError("COMSOL must not start")) as native, \
                            mock.patch.object(candidate_comsol_stage,"analyze_detector_request",wraps=candidate_comsol_stage.analyze_detector_request) as analyze:
                        child,summary=run_candidate_workflow(child_plan,sys.executable,
                            stage_executor=self.native_fake_executor(child_observed),reuse_parent=parent,reuse_through="cad_candidate")
                    native.assert_not_called()
                    stage=next(item for item in summary["stages"] if item["stage_id"]=="comsol_candidate")
                    self.assertEqual(child_observed,["static_inputs","structural_acceptance"])
                    self.assertEqual(stage["native_execution"],"reused")
                    self.assertEqual(stage["analysis_execution"],"reused" if case=="same" else "executed")
                    self.assertEqual(analyze.call_count,0 if case=="same" else 1)
                    self.assertEqual({path:path.read_bytes() for path in parent.rglob("*") if path.is_file()},before)
                    self.assertNotIn(child,children)
                    children.append(child)
                    self.assertEqual(load_json(child/"run_manifest.json")["run_id"],child.name)
                    config=load_json(child/"run_config.json")
                    self.assertEqual(config["run_id"],child.name)
                    for reused_stage in ("comsol_candidate","simion_candidate","cad_candidate"):
                        proof=Path(config["inputs"][f"stage_reuse_{reused_stage}_provenance"])
                        self.assertTrue(proof.is_relative_to(child))
                        self.assertEqual(load_json(proof)["run_id"],child.name)
                        self.assertEqual(load_json(proof)["parent_run_id"],parent.name)
                    # Injected executors exercise the engine, not the public
                    # owner: they must leave its capacity ledger unchanged.
                    self.assertEqual(load_capacity_ledger(root/"artifacts"),ledger_before)
                    if case!="same":
                        self.assertTrue(Path(stage["evidence"]["analysis_receipt"]).is_relative_to(child))


class CandidateCausalPhaseTests(CandidateFixtures, unittest.TestCase):
    def test_actual_engine_binds_four_phase_owners_and_successor_flattens_origins(self):
        from msplatform.execution.retention import file_record
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import run_candidate_workflow as workflow
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, plan_path = self.native_workflow_plan(root, '20261031_201001')
            original = self.native_fake_executor([])
            def produce(stage, plan, executable):
                evidence = original(stage, plan, executable)
                if stage['stage_id'] == 'comsol_candidate':
                    run = Path(plan['run_root'])
                    events = run/'results/software_detector_events.csv'
                    events.write_text('Ion,Hit,Status\n'+''.join(f'{i},1,detector_hit\n' for i in range(1,101)), encoding='utf-8')
                    request = run/'results/software.analysis_request.json'
                    request.write_text(json.dumps({'role':'oatof_comsol_detector_events_analysis_request','raw_events_csv':str(events),'analysis_output_dir':str(run/'results/analysis')}), encoding='utf-8')
                    receipt = run/'results/software_analysis_receipt.json'
                    receipt.write_text(json.dumps({'raw_events':file_record(events)}), encoding='utf-8')
                    evidence.update(analysis_request=str(request), analysis_receipt=str(receipt),
                        analysis_contract=frozen_source_path(plan['execution_source_closure'], 'projects/single_reflection_oa_tof_mass_analyzer/config/analysis_contract.json'))
                return evidence
            parent, _ = workflow.run_candidate_workflow(plan_path, sys.executable, stage_executor=produce)
            before = {path:path.read_bytes() for path in parent.rglob('*') if path.is_file()}
            origins = workflow._comsol_phase_sources(parent)
            self.assertEqual(set(origins), {'native','export','analysis','sync'})
            self.assertEqual({row['owner_directory'] for row in origins.values()}, {str(parent)})
            _, child_plan = self.native_workflow_plan(root, '20261031_201002')
            calls = []
            model = Path(next(stage for stage in load_json(parent/'summary.json')['stages'] if stage['stage_id']=='comsol_candidate')['evidence']['model'])
            reads = []
            original_open = Path.open
            def track_open(path, *args, **kwargs):
                mode = args[0] if args else kwargs.get('mode','r')
                if path.resolve() == model.resolve() and 'r' in mode:
                    reads.append(str(path))
                return original_open(path, *args, **kwargs)
            with mock.patch.object(Path, 'open', track_open):
                child, summary = workflow.run_candidate_workflow(child_plan, sys.executable,
                    stage_executor=self.native_fake_executor(calls), reuse_parent=parent, reuse_through='cad_candidate')
            self.assertEqual(len(reads), 1, reads)
            self.assertEqual(calls, ['static_inputs','structural_acceptance'])
            self.assertEqual(summary['status'], 'success')
            child_origins = workflow._comsol_phase_sources(child)
            self.assertEqual({row['owner_directory'] for row in child_origins.values()}, {str(parent)})
            self.assertEqual(before, {path:path.read_bytes() for path in before})

    def test_analysis_implementation_change_runs_only_frozen_csv_analysis(self):
        from msplatform.execution.retention import file_record
        from projects.single_reflection_oa_tof_mass_analyzer.analysis import candidate_source_closure as source_owner
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import run_candidate_workflow as workflow
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, reference, _, _ = postprocess_source_fixture(root/'event_fixture')
            reference_request = next((reference/'results').glob('*.analysis_request.json'))
            reference_document = load_json(reference_request)
            _, first_plan = self.native_workflow_plan(root, '20261031_202001')
            original = self.native_fake_executor([])
            def produce(stage, plan, executable):
                evidence = original(stage, plan, executable)
                if stage['stage_id'] == 'comsol_candidate':
                    run = Path(plan['run_root'])
                    events = run/'results/events.csv'
                    events.write_bytes(Path(reference_document['raw_events_csv']).read_bytes())
                    document = dict(reference_document, raw_events_csv=str(events), analysis_output_dir=str(run/'results/analysis'))
                    request = run/'results/events.analysis_request.json'
                    request.write_text(json.dumps(document), encoding='utf-8')
                    receipt = run/'results/analysis_receipt.json'
                    receipt.write_text(json.dumps({'raw_events':file_record(events)}), encoding='utf-8')
                    evidence.update(analysis_request=str(request), analysis_receipt=str(receipt),
                        analysis_contract=frozen_source_path(plan['execution_source_closure'], 'projects/single_reflection_oa_tof_mass_analyzer/config/analysis_contract.json'))
                return evidence
            parent, _ = workflow.run_candidate_workflow(first_plan, sys.executable, stage_executor=produce)
            before = {path:path.read_bytes() for path in parent.rglob('*') if path.is_file()}
            source_id = 'projects/single_reflection_oa_tof_mass_analyzer/analysis/reference_analysis_core.py'
            old_source_path = source_owner._source_path
            changed = root/'current_analysis.py'
            changed.write_bytes(old_source_path(source_id).read_bytes()+b'\n# explicit analysis-only source fixture revision\n')
            def author_source(identifier):
                return changed if identifier == source_id else old_source_path(identifier)
            with mock.patch.object(source_owner, '_source_path', side_effect=author_source):
                _, second_plan = self.native_workflow_plan(root, '20261031_202002')
                calls = []
                child, summary = workflow.run_candidate_workflow(second_plan, sys.executable,
                    stage_executor=self.native_fake_executor(calls), reuse_parent=parent, reuse_through='cad_candidate')
                self.assertEqual(calls, ['static_inputs','structural_acceptance'])
                comsol = next(stage for stage in summary['stages'] if stage['stage_id']=='comsol_candidate')
                self.assertEqual(comsol['phase_execution'], {'native':'reused','export':'reused','analysis':'executed','sync':'reused'})
                self.assertTrue(Path(comsol['evidence']['analysis_receipt']).is_relative_to(child))
                self.assertEqual(workflow._comsol_phase_sources(child)['analysis']['owner_directory'],str(child))
                _, third_plan = self.native_workflow_plan(root, '20261031_202003')
                grandchild, latest = workflow.run_candidate_workflow(third_plan, sys.executable,
                    stage_executor=self.native_fake_executor([]), reuse_parent=child, reuse_through='cad_candidate')
                third = next(stage for stage in latest['stages'] if stage['stage_id']=='comsol_candidate')
                self.assertEqual(set(third['phase_execution'].values()), {'reused'})
                self.assertEqual(third['evidence']['analysis_receipt'],comsol['evidence']['analysis_receipt'])
                self.assertEqual(workflow._comsol_phase_sources(grandchild)['native']['owner_directory'],str(parent))
            self.assertEqual(before, {path:path.read_bytes() for path in before})

    def _observed_raw_save_fixture(self, stage, plan, root, *, exit_code=1, save_state="raw_complete"):
        """Actual registered Python writer, never a COMSOL model or solve."""
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.native_stage_completion import append_native_stage_completion
        run = Path(plan['run_root'])
        config = load_json(run/'run_config.json')
        model = Path(stage['model_path'])
        context = {'schema_version':1,'role':'oatof_saved_particle_solution','solution_tag':'sol2','dataset_tag':'pdset1',
            'native_particle_solve_count':1,'particle_count':100,'solution_times_s':[0,1e-6],
            'saved_model_bytes':len(b'opaque software fixture; not a COMSOL model'),
            'model_save_state':save_state,
            'contract_path':config['inputs']['candidate_resolved_geometry.json'],'source_path':config['inputs']['candidate_particle_table']}
        payload=root/'inert_payload.json'
        payload.write_text(json.dumps({'model':str(model),'context':context,'report':stage['report_path'],'exit_code':exit_code}),encoding='utf-8')
        ready=root/'inert_ready'
        worker=root/'inert_writer.py'
        worker.write_text("import json,sys,time\nfrom pathlib import Path\nwhile not Path(sys.argv[2]).exists():time.sleep(.01)\np=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))\nm=Path(p['model']);m.parent.mkdir(parents=True,exist_ok=True);m.write_bytes(b'opaque software fixture; not a COMSOL model')\nPath(str(m)+'.postprocess.json').write_text(json.dumps(p['context']),encoding='utf-8')\nPath(p['report']).write_text('STATUS='+('FAIL' if p['exit_code'] else 'PASS')+'\\nERROR=SAVED_BEFORE_EXTRACT\\n',encoding='utf-8')\nraise SystemExit(p['exit_code'])\n",encoding='utf-8')
        host=REPO_ROOT/'common/host_execution_lease.ps1'
        quote=lambda value:"'"+str(value).replace("'","''")+"'"
        script=("$ErrorActionPreference='Stop'; Remove-Item Env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN -ErrorAction SilentlyContinue; "
            "$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH="+quote(root/'fixture_host.sqlite3')+"; . "+quote(host)+"; "
            "$b=Get-HostResourceBudget -Role GATE -Stage software_validation;$b.cpu_cores=1;$b.memory_bytes=256MB;"
            "$lease=Enter-HostResourceStage -Role GATE -Stage software_validation -Budget $b;"
            "$p=$null;try{$p=Start-Process -FilePath "+quote(sys.executable)+" -ArgumentList @('-I','-B',"+quote('"'+str(worker)+'"')+","+quote('"'+str(payload)+'"')+","+quote('"'+str(ready)+'"')+") -WorkingDirectory "+quote(root)+" -WindowStyle Hidden -PassThru;"
            "$lease=Register-HostResourceProcess -Lease $lease -ProcessId $p.Id;"
            "[IO.File]::WriteAllText("+quote(ready)+",'ready');"
            "$lease=Wait-HostResourceProcess -Lease $lease -Process $p;"
            "$observation=@{exit_confirmed=[bool]$p.HasExited;returncode=[int]$p.ExitCode};"
            "}finally{[IO.File]::WriteAllText("+quote(ready)+",'ready');if($null-ne$p){$p.WaitForExit()};"
            "$released=Exit-HostResourceStage -Lease $lease -PassThru};"
            "Write-Output ('RECEIPT_JSON='+(@{observation=$observation;host_release=@{inherited=[bool]$lease.inherited;token=$lease.token;result=$released;error=$null}}|ConvertTo-Json -Depth 16 -Compress))")
        observed=subprocess.run(['pwsh','-NoProfile','-NonInteractive','-Command',script],cwd=REPO_ROOT,capture_output=True,text=True,encoding='utf-8',timeout=60)
        self.assertEqual(observed.returncode,0,observed.stdout+observed.stderr)
        facts=json.loads(next(line.removeprefix('RECEIPT_JSON=') for line in observed.stdout.splitlines() if line.startswith('RECEIPT_JSON=')))
        self.assertEqual(facts['observation'],{'exit_confirmed':True,'returncode':exit_code})
        self.assertFalse(facts['host_release']['inherited'])
        self.assertEqual(facts['host_release']['result']['status'],'released')
        receipt=run/'logs/comsol_build_completion.json'
        receipt.write_text(json.dumps({'schema_version':1,'role':'comsol_launcher_completion','run_id':run.name,
            'fixture':'SOFTWARE_ONLY_REGISTERED_PYTHON_WRITER_NOT_COMSOL',
            'operations':[{'operation_id':'actual-inert-python-writer','observation':facts['observation']}],
            'host_release':facts['host_release']}),encoding='utf-8')
        plan['writer_completion']={'operations':[],'resource_releases':[]}
        append_native_stage_completion(plan['writer_completion'],receipt,role='comsol_launcher_completion',run_id=run.name)
        return model

    def test_stopped_raw_save_then_export_failure_keeps_native_receipt_and_original_failure(self):
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import run_candidate_workflow as workflow
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, plan_path = self.native_workflow_plan(root, '20261031_203001')
            original = self.native_fake_executor([])
            def after_save(stage, plan, executable):
                if stage['stage_id'] != 'comsol_candidate':
                    return original(stage, plan, executable)
                from types import SimpleNamespace
                from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.candidate_comsol_stage import execute_comsol_native_build
                def fail_after_save(*args,**kwargs):
                    self._observed_raw_save_fixture(stage,plan,root)
                    raise RuntimeError('SAVED_BEFORE_EXTRACT')
                return execute_comsol_native_build(stage,plan,runtime=SimpleNamespace(
                    _run_managed_stage_command=fail_after_save,
                    _record_candidate_native_completion=workflow._record_candidate_native_completion))
            with self.assertRaisesRegex(workflow.CandidateWorkflowError,'SAVED_BEFORE_EXTRACT') as failure:
                workflow.run_candidate_workflow(plan_path,sys.executable,stage_executor=after_save)
            parent=failure.exception.run_root
            summary=load_json(parent/'summary.json')
            self.assertEqual(summary['status'],'failed')
            main=next(row for row in summary['stages'] if row['stage_id']=='comsol_candidate')
            self.assertEqual(main['status'],'failed')
            native=next(row for row in summary['stages'] if row['stage_id']=='comsol_native')
            self.assertEqual(native['status'],'success')
            self.assertEqual(workflow._resolve_reuse_stage_owner(parent,'comsol_candidate')['receipt_stage_id'],'comsol_native')
            origins=workflow._comsol_phase_sources(parent)
            self.assertEqual(origins['native']['status'],'success')
            self.assertEqual({origins[name]['status'] for name in ('export','analysis','sync')},{'pending'})
            # Consume the failed parent's successful native receipt through
            # the real public validator: never require a false whole-stage PASS.
            before={path:path.read_bytes() for path in parent.rglob('*') if path.is_file()}
            _,child_plan_path=self.native_workflow_plan(root,'20261031_203002')
            child=start_candidate_run(child_plan_path)
            child_plan=load_json(child/'candidate_workflow_plan.json')
            original(child_plan['stages'][0],child_plan,sys.executable)
            context=workflow._stage_context(child,child_plan,'comsol_candidate',sys.executable)
            workflow._declare_context_inputs(child,{'comsol_candidate':context},provenance={'comsol_candidate'})
            receipt=load_json(parent/'stage_receipts/comsol_native.json')['outputs']['model']
            model=parent/receipt['path']
            with workflow.guarded_file_identity(model,expected_bytes=receipt['bytes'],expected_sha256=receipt['sha256']) as guard:
                proof=workflow.validate_and_write_stage_reuse(child,parent_run_root=parent,
                    project=PROJECT_ROOT.name,stage_contexts={'comsol_native':context},
                    allow_provisional_manifest=True,identity_guards={model.resolve():guard},
                    provenance_input_name='stage_reuse_comsol_candidate_provenance')
            proof=load_json(proof)
            self.assertEqual(proof['parent_run_status'],'failed')
            self.assertEqual([row['stage_id'] for row in proof['reused_stages']],['comsol_native'])
            self.assertEqual(before,{path:path.read_bytes() for path in before})

    def test_producer_native_and_full_receipts_share_one_live_model_identity(self):
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import run_candidate_workflow as workflow
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            _, plan_path=self.native_workflow_plan(root,'20261031_204001')
            model_path=Path(next(stage for stage in load_json(plan_path)['stages'] if stage['stage_id']=='comsol_candidate')['model_path'])
            calls=[];receipt_reads=[];reads=[]
            original=self.native_fake_executor(calls)
            original_open=Path.open
            original_receipt=workflow.write_stage_receipt
            def track_open(path,*args,**kwargs):
                mode=args[0] if args else kwargs.get('mode','r')
                if path.resolve()==model_path.resolve() and 'r' in mode:
                    reads.append(str(path))
                return original_open(path,*args,**kwargs)
            def write_receipt(*args,**kwargs):
                before=len(reads)
                result=original_receipt(*args,**kwargs)
                if kwargs['stage_id'] in {'comsol_native','comsol_candidate'}:
                    receipt_reads.append((kwargs['stage_id'],before,len(reads)))
                return result
            def produce(stage,plan,executable):
                if stage['stage_id']!='comsol_candidate':
                    return original(stage,plan,executable)
                model=self._observed_raw_save_fixture(stage,plan,root,exit_code=0)
                self.assertTrue(workflow._record_candidate_native_completion(stage,plan))
                run=Path(plan['run_root'])
                csv=run/'results/software.csv'
                csv.write_text('Ion,Hit,Status\n'+''.join(f'{index},1,detector_hit\n' for index in range(1,101)),encoding='utf-8')
                request=run/'results/software.analysis_request.json'
                request.write_text(json.dumps({'role':'oatof_comsol_detector_events_analysis_request','raw_events_csv':str(csv)}),encoding='utf-8')
                analysis=run/'results/software_analysis_receipt.json';analysis.write_text('{}',encoding='utf-8')
                sync=run/'logs/software_sync.txt';sync.write_text('STATUS=PASS\n',encoding='utf-8')
                return {'model':str(model),'build_report':stage['report_path'],'sync_report':str(sync),
                    'analysis_request':str(request),'analysis_receipt':str(analysis),
                    'analysis_contract':frozen_source_path(plan['execution_source_closure'],'projects/single_reflection_oa_tof_mass_analyzer/config/analysis_contract.json')}
            with mock.patch.object(Path,'open',track_open),mock.patch.object(workflow,'write_stage_receipt',side_effect=write_receipt):
                parent,summary=workflow.run_candidate_workflow(plan_path,sys.executable,stage_executor=produce)
            self.assertEqual(summary['status'],'success')
            self.assertEqual([row[0] for row in receipt_reads],['comsol_native','comsol_candidate'])
            self.assertEqual([(before,after) for _,before,after in receipt_reads],[(1,1),(1,1)])
            native=load_json(parent/'stage_receipts/comsol_native.json')['outputs']['model']
            complete=load_json(parent/'stage_receipts/comsol_candidate.json')['outputs']['model']
            self.assertEqual((native['bytes'],native['sha256']),(complete['bytes'],complete['sha256']))
            print('PRODUCER_MODEL_READS='+json.dumps({'guard_and_two_receipts':1,'including_terminal_manifest':len(reads)}),flush=True)
            self.assertEqual(len(reads),2,'one producer identity plus the independent terminal manifest boundary')

    def test_normal_failed_export_parent_uses_original_cli_csv_only_without_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            artifact,science,parent,_=cold_export_failed_child_fixture(root,normal_phase=True)
            # The already exported data, original contract and source are enough.
            # Removing only this explicit opaque fixture model happens before
            # the parent byte snapshot; no production run or solver is touched.
            (science/'comsol/model.mph').unlink()
            before={path:path.read_bytes() for owner in (science,parent) for path in owner.rglob('*') if path.is_file()}
            invoke=postprocess_public_entry(root,artifact)
            child_id='20261031_205001__analysis__python__normal-export-csv'
            result=invoke(['--postprocess-from',str(parent),'--run-id',child_id])
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            child=artifact/'projects'/PROJECT_ROOT.name/'runs'/child_id
            summary=load_json(child/'summary.json')
            self.assertEqual(summary['evidence']['native_launch_count'],0)
            self.assertFalse(list(child.rglob('*.mph')))
            completion=(child/'results/execution_completion.json').read_bytes()
            recovered=invoke(['--resume-finalization',str(child)])
            self.assertEqual(recovered.returncode,0,recovered.stdout+recovered.stderr)
            self.assertEqual(completion,(child/'results/execution_completion.json').read_bytes())
            self.assertEqual(before,{path:path.read_bytes() for path in before})


    def test_report_and_cleanup_do_not_change_native_but_field_and_task_inputs_do(self):
        from msplatform.contracts.machine_contracts import sha256
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_source_closure import candidate_comsol_source_phases
        with tempfile.TemporaryDirectory() as temporary:
            _,path=self.native_workflow_plan(Path(temporary),'20261031_213001')
            closure=load_json(path)['execution_source_closure']
            original=candidate_comsol_source_phases(closure)
            code=Path(closure['code_root'])
            def replace_source(identifier,transform):
                source=code/identifier
                text=source.read_text(encoding='utf-8')
                source.write_text(transform(text),encoding='utf-8',newline='\n')
                record=next(row for row in closure['sources'] if row['source_id']==identifier)
                record.update(bytes=source.stat().st_size,sha256=sha256(source))
            prefix='projects/single_reflection_oa_tof_mass_analyzer/'
            replace_source(prefix+'comsol/oatof_report_model_timing.m',lambda text:text+'\n% display-only change\n')
            replace_source(prefix+'workflows/design_candidate/run_candidate_workflow.py',lambda text:text+'\n# cleanup presentation only\n')
            self.assertEqual(candidate_comsol_source_phases(closure),original)
            replace_source(prefix+'comsol/oatof_build_saved_particle_solution.m',
                lambda text:text.replace("es.selection.named('sel_vac');","es.selection.named('sel_all');"))
            field_changed=candidate_comsol_source_phases(closure)
            self.assertNotEqual(field_changed['native'],original['native'])
            replace_source(prefix+'workflows/design_candidate/candidate_comsol_stage.py',
                lambda text:text.replace('return "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_contract_build.m", environment',
                    'environment["OATOF_CANDIDATE_CONTRACT_PATH"]="different-science"\n    return "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_contract_build.m", environment'))
            task_changed=candidate_comsol_source_phases(closure)
            self.assertNotEqual(task_changed['native']['dispatch'],field_changed['native']['dispatch'])

    def test_analysis_phase_preserves_only_recorded_historical_identity_source(self):
        from msplatform.contracts.machine_contracts import sha256
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_source_closure import candidate_comsol_source_phases
        with tempfile.TemporaryDirectory() as temporary:
            _, path = self.native_workflow_plan(Path(temporary), '20261031_213010')
            closure = load_json(path)['execution_source_closure']
            old_id = 'common/contracts/file_identity.py'
            new_id = 'src/msplatform/io/file_identity.py'
            actual = {row['source_id'] for row in closure['sources']}
            self.assertIn(new_id, actual)
            self.assertNotIn(old_id, actual)
            fresh = candidate_comsol_source_phases(closure)
            ids = {row['source_id'] for row in fresh['analysis']['sources']}
            self.assertIn(new_id, ids)
            self.assertNotIn(old_id, ids)
            # Inert test-owned record, not an authentic archived source.
            old_file = Path(closure['code_root']) / old_id
            old_file.parent.mkdir(parents=True, exist_ok=True)
            old_file.write_bytes(b'# inert historical provenance fixture\n')
            old_hash = sha256(old_file)
            closure['sources'].append(dict(source_id=old_id, source_sha256=old_hash,
                                           sha256=old_hash, bytes=old_file.stat().st_size,
                                           transformations=[]))
            before = old_file.read_bytes()
            historical = candidate_comsol_source_phases(closure)
            old_rows = [row for row in historical['analysis']['sources'] if row['source_id'] == old_id]
            self.assertEqual(old_rows, [dict(source_id=old_id, bytes=len(before), sha256=old_hash)])
            self.assertEqual(old_file.read_bytes(), before)
            old_file.unlink()
            with self.assertRaisesRegex(ValueError, 'frozen candidate source changed'):
                candidate_comsol_source_phases(closure)

    def test_real_normal_native_and_sync_commands_consume_unique_task_environment_builders(self):
        from types import SimpleNamespace
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import candidate_comsol_stage as adapter
        with tempfile.TemporaryDirectory() as temporary:
            _,path=self.native_workflow_plan(Path(temporary),'20261031_213002')
            plan=load_json(path);stage=next(row for row in plan['stages'] if row['stage_id']=='comsol_candidate')
            calls=[];publications=[]
            def observed(command,log,actual_plan,completion,role,environment):
                report=Path(command[command.index('-ReportPath')+1]);report.parent.mkdir(parents=True,exist_ok=True)
                report.write_text('STATUS=PASS\n',encoding='utf-8')
                calls.append((command,environment,role))
            runtime=SimpleNamespace(_run_managed_stage_command=observed,
                _record_candidate_native_completion=lambda *args:publications.append('stopped-raw-proof-requested') or True)
            adapter.execute_comsol_native_build(stage,plan,runtime=runtime)
            adapter.execute_comsol_model_sync(stage,plan,runtime=runtime)
            self.assertEqual(len(calls),2)
            self.assertEqual(publications,['stopped-raw-proof-requested'])
            closure=plan['execution_source_closure']
            for actual,builder in zip(calls,(adapter.comsol_native_inputs,adapter.comsol_sync_inputs)):
                task,environment=builder(stage,closure)
                self.assertEqual(actual[0][actual[0].index('-TaskScript')+1],frozen_source_path(closure,task))
                self.assertEqual(actual[1],environment)
                self.assertEqual(actual[2],'comsol_launcher_completion')
                self.assertIn('-RunDir',actual[0])


    def test_actual_formal_consumer_preserves_per_stage_cross_root_proofs_and_rejects_owner_swap(self):
        from msplatform.execution.retention import file_record
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);inputs=root/'formal/inputs';inputs.mkdir(parents=True)
            candidate=root/'candidate';candidate.mkdir()
            config={'inputs':{},'provenance':{'stage_reuse':{}}}
            original_paths=[];model=None
            for index,stage_id in enumerate(('comsol_candidate','simion_candidate')):
                owner=root/f'root{index}'/'artifacts/projects/p/runs'/f'20261031_22000{index}__sim__cross__owner'
                owner.mkdir(parents=True)
                manifest=owner/'run_manifest.json';manifest.write_text(json.dumps({'run_id':owner.name,'owner':index}),encoding='utf-8')
                source=owner/'same.dat';source.write_bytes(b'original-model' if index==0 else b'original-simion')
                if index==0:model=source
                proof=candidate/f'{stage_id}.json'
                proof.write_text(json.dumps({'parent_run_id':owner.name,'parent_manifest':file_record(manifest),
                    'reused_stages':[{'stage_id':'comsol_native' if index==0 else stage_id,
                        'outputs':{'model':file_record(source)}}]}),encoding='utf-8')
                name=f'stage_reuse_{stage_id}_provenance'
                config['inputs'][name]=str(proof)
                config['inputs'][f'stage_reuse_{stage_id}_source_manifest']=str(manifest)
                config['provenance']['stage_reuse'][stage_id]=file_record(proof)
                original_paths.extend((manifest,source,proof))
            config_path=candidate/'run_config.json';config_path.write_text(json.dumps(config),encoding='utf-8')
            before={path:path.read_bytes() for path in original_paths}
            script=root/'formal_probe.ps1'
            text=r"""$ErrorActionPreference='Stop'
. '@@SUPPORT@@'
$source=Get-Content -Raw -LiteralPath '@@FORMAL@@'
$first=$source.IndexOf('$reuseInputs = [ordered]@{}')
$last=$source.IndexOf('$candidateSimion = Join-Path',$first)
if($first-lt0-or$last-le$first){throw 'Formal consumer boundary missing'}
$consumer=[ScriptBlock]::Create($source.Substring($first,$last-$first))
$candidateConfig=Get-Content -Raw '@@CONFIG@@'|ConvertFrom-Json
$comsolStage=@([pscustomobject]@{execution='reused'})
$candidateRoot='@@CANDIDATE@@';$candidateMphSource='@@MODEL@@'
$inputDir='@@INPUTS@@'
& $consumer
$swap=Get-Content -Raw '@@CONFIG@@'|ConvertFrom-Json
$swap.inputs.stage_reuse_comsol_candidate_source_manifest=$swap.inputs.stage_reuse_simion_candidate_source_manifest
$candidateConfig=$swap
$rejected=$false;$reason=$null
try{& $consumer}catch{$rejected=$true;$reason=$_.Exception.Message}
[ordered]@{rejected=$rejected;reason=$reason;copied=@(Get-ChildItem -LiteralPath $inputDir -File|Select-Object -ExpandProperty Name)}|ConvertTo-Json -Depth 8 -Compress
"""
            values={'SUPPORT':str(REPO_ROOT/'common/contracts/run_artifact_support.ps1'),
                'FORMAL':str(PROJECT_ROOT/'workflows/formal_reference/run_formal_validation.ps1'),
                'CONFIG':str(config_path),'CANDIDATE':str(candidate),'MODEL':str(model),'INPUTS':str(inputs)}
            for key,value in values.items():text=text.replace('@@'+key+'@@',value.replace("'","''"))
            script.write_text(text,encoding='utf-8',newline='\n')
            result=subprocess.run(['pwsh','-NoProfile','-NonInteractive','-File',str(script)],cwd=REPO_ROOT,
                capture_output=True,text=True,encoding='utf-8',timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            observed=json.loads(result.stdout.strip().splitlines()[-1])
            self.assertTrue(observed['rejected'])
            self.assertIn('original owner',observed['reason'])
            self.assertIn('candidate_stage_reuse_comsol_candidate_source_manifest.json',observed['copied'])
            self.assertIn('candidate_stage_reuse_simion_candidate_source_manifest.json',observed['copied'])
            self.assertEqual(before,{path:path.read_bytes() for path in before})



    def test_same_size_gui_save_failure_is_unknown_and_does_not_publish_native(self):
        from types import SimpleNamespace
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import candidate_comsol_stage as adapter
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            _,plan_path=self.native_workflow_plan(root,'20261031_223001')
            original=self.native_fake_executor([])
            def execute(stage,plan,executable):
                if stage['stage_id']!='comsol_candidate':return original(stage,plan,executable)
                def save_failed(*args,**kwargs):
                    self._observed_raw_save_fixture(stage,plan,root,save_state='gui_update_started')
                    raise RuntimeError('GUI_SAVE_PRIMARY')
                return adapter.execute_comsol_native_build(stage,plan,runtime=SimpleNamespace(
                    _run_managed_stage_command=save_failed,
                    _record_candidate_native_completion=candidate_workflow._record_candidate_native_completion))
            with self.assertRaisesRegex(CandidateWorkflowError,'GUI_SAVE_PRIMARY') as failed:
                run_candidate_workflow(plan_path,sys.executable,stage_executor=execute)
            parent=failed.exception.run_root;summary=load_json(parent/'summary.json')
            self.assertEqual(summary['data_validity'],'unknown')
            self.assertEqual(summary['model_save_status'],'unknown')
            self.assertEqual(summary['scientific_result'],'not_evaluated_save_incomplete')
            self.assertEqual(summary['candidate_decision'],'no_candidate_decision')
            self.assertEqual(summary['failure_substage'],'gui_model_save')
            self.assertIn('--postprocess-from',summary['recovery_action'])
            self.assertFalse((parent/'stage_receipts/comsol_native.json').exists())
            self.assertNotIn('comsol_native',[row['stage_id'] for row in summary['stages']])
            self.assertIn('MODEL_SAVE_COMPLETION_UNKNOWN',' '.join(getattr(failed.exception,'__notes__',[])))

    def test_cold_save_marker_rejects_unfinished_model_but_keeps_csv_and_bound_legacy_completion(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for label,state,events,legacy,accepted in (
                    ('started','gui_update_started',False,False,False),
                    ('complete','gui_update_complete',False,False,True),
                    ('csv','gui_update_started',True,False,True),
                    ('legacy',None,False,True,True),
                    ('missing',None,False,False,False)):
                with self.subTest(label=label):
                    scope=root/label;scope.mkdir()
                    artifact,parent,_,_=postprocess_source_fixture(scope,cold=not events,retain_model=events,
                        save_state=state,legacy_save_complete=legacy)
                    before={path:path.read_bytes() for path in parent.rglob('*') if path.is_file()}
                    if accepted:
                        selected=select_postprocess_parent(parent,artifact)
                        self.assertEqual(selected['exports'] is not None,events)
                    else:
                        with self.assertRaisesRegex(ValueError,'MODEL_SAVE_COMPLETION_'):
                            select_postprocess_parent(parent,artifact)
                    self.assertEqual(before,{path:path.read_bytes() for path in before})
