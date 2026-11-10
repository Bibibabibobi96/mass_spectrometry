"""Actual worker/child/transaction transport using explicitly inert bytes, never SIMION."""
from pathlib import Path
import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from common.contracts.test_simion_geometry_compiler import compiler_inputs
from msplatform.backends.simion.compiler import compile_geometry
from msplatform.backends.simion.field_worker import run_member, _require_published_parent
from msplatform.backends.simion import pa_family_cache as cache
from msplatform.backends.simion.native_plans import plan_solve_fields, operating_member_identity
from msplatform.backends.simion.pa_family_cache import canonical_pa_family_cache_key
from msplatform.backends.simion.resources import native_resource_path
from msplatform.execution import owner
from msplatform.execution.capacity_admission import _capacity_policy
from msplatform.execution.context import ExecutionContext
from msplatform.io.manifest_records import file_record
from msplatform.execution.resources import resource_path
from msplatform.execution.run_session import RunSession
from msplatform.execution.processes import ProcessExecutionError
from msplatform.io.file_identity import file_sha256
from msplatform.backends.simion import field_worker


INERT_WORKER = r'''
"""TEST ONLY: replace native command transport with inert Python file producers."""
import json,sys
from pathlib import Path
from msplatform.backends.simion import field_worker as worker
original=worker._native_operation
def inert(context,op,**kwargs):
    # Preserve canonical plan/identity/audit and only replace native transport.
    # These are inert protocol fixtures, never numerical/native evidence.
    audit=op['operation_id'].startswith('audit_')
    text=json.dumps({'status':'pass','fixture':'INERT_NOT_SCIENTIFIC_EVIDENCE'}) if audit else 'INERT_NOT_PA'
    code="from pathlib import Path;outputs="+repr(op['outputs'])+";text="+repr(text)+"\nfor p in outputs: Path(p).parent.mkdir(parents=True,exist_ok=True);Path(p).write_text(text,encoding='utf-8')\nprint("+repr(op['success_marker'])+")"
    return original(context,dict(op,arguments=['-c',code]),**kwargs)
worker._native_operation=inert
worker.main()
'''

INERT_FAULT = r'''
original_native=worker._native_operation
def fault_native(context,op,**kwargs):
    if op['operation_id'].startswith(FAULT_STAGE+'_'):
        code = "import sys;print('INERT_FAULT',flush=True);sys.exit(7)"
        if op['operation_id'].startswith('export_'):
            code = "from pathlib import Path;outputs="+repr(op['outputs'])+"\nfor p in outputs: Path(p).parent.mkdir(parents=True,exist_ok=True);Path(p).write_text('PARTIAL_EXPORT_NOT_PA')\n"+("print("+repr(op['success_marker'])+")" if RECEIPT_FAILURE else code)
        return original(context,dict(op,arguments=['-c',code]),**kwargs)
    return original_native(context,op,**kwargs)
worker._native_operation=fault_native
if RECEIPT_FAILURE:
    actual_observed=worker.run_observed_process
    def lose_export_receipt(*args,**kwargs):
        receipt=actual_observed(*args,**kwargs)
        if Path(kwargs['stdout_path']).name.startswith('export_'):
            # Explicit inert transport fault AFTER the real process has closed.
            # Its completion envelope is unavailable to the consuming worker.
            from msplatform.execution.processes import ProcessExecutionError
            raise ProcessExecutionError('INJECTED_MISSING_NATIVE_COMPLETION_RECEIPT',{})
        return receipt
    worker.run_observed_process=lose_export_receipt
if ACCOUNTING_FAILURE:
    actual_advance=worker.cache.advance_pa_family_cache_transaction
    def fault_accounting(*args,**kwargs):
        if kwargs.get('record_stage_only'): raise OSError('INJECTED_STOPPED_ACCOUNTING_FAILURE')
        return actual_advance(*args,**kwargs)
    worker.cache.advance_pa_family_cache_transaction=fault_accounting
if PUBLICATION_FAILURE:
    def fault_publication(*args,**kwargs): raise OSError('INJECTED_PUBLICATION_FINALIZATION_FAILURE')
    worker.cache._complete_transaction_publication=fault_publication
'''


def frozen_worker_fixture(session, script: Path) -> Path:
    """Bind this candidate's actual core under the original run, even with -I."""
    from msplatform.execution.inputs import enumerate_python_sources, freeze_file
    author = Path(__file__).resolve().parents[2]
    snapshot = session.input_dir / "field_worker_source"
    for relative in enumerate_python_sources(author, package_roots=["src/msplatform"],
            resource_suffixes=[".json", ".ps1", ".lua", ".gem", ".m", ".iob", ".pa0", ".pa"]):
        destination = session.declare_file(snapshot / relative, "required_evidence")
        destination.parent.mkdir(parents=True, exist_ok=True)
        freeze_file(author / relative, destination)
    selected = {}
    for name, relative in dict(worker="src/msplatform/backends/simion/field_worker.py",
                               native_plans="src/msplatform/backends/simion/native_plans.py").items():
        selected[name] = dict(path=str(snapshot / relative), sha256=file_sha256(author / relative))
    bootstrap = ("import sys,hashlib\nfrom pathlib import Path\n"
        + "sys.path.insert(0," + repr(str(snapshot / "src")) + ")\n"
        + "from msplatform.backends.simion import field_worker,native_plans\n"
        + "selected=" + repr(selected) + "\n"
        + "for name,module in [('worker',field_worker),('native_plans',native_plans)]:\n"
        + " p=Path(module.__file__).resolve();expected=selected[name]\n"
        + " assert p==Path(expected['path']).resolve(),('FROZEN_WORKER_ORIGIN',p)\n"
        + " assert hashlib.sha256(p.read_bytes()).hexdigest().upper()==expected['sha256'].upper(),('FROZEN_WORKER_SHA',p)\n")
    target = session.declare_file(session.input_dir / "inert_worker.py", "required_evidence")
    target.write_text(bootstrap + script.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    session.add_input("selected_worker_implementation", file_record(snapshot / "src/msplatform/backends/simion/field_worker.py", "required_evidence"))
    session.add_input("selected_worker_fixture", file_record(target, "required_evidence"))
    return target


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell required")
class FieldWorkerTests(unittest.TestCase):
    def test_large_tool_preflight_keeps_request_bound_failure_receipt_without_cache_or_native(self):
        from common.contracts.test_simion_field_action import public_case
        from msplatform.backends.simion.field_execution import plan_fields_execution
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model, numerical, _contract, _clock_root = public_case()
            plan = plan_fields_execution(model, numerics=numerical)['field_plan']
            context = ExecutionContext(workspace=root/'study', python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')), tools={'simion':Path(sys.executable)},
                host_state_path=root/'private.sqlite3', policy_path=resource_path('host_resource_policy.json'))
            script = root/'preflight_worker.py'
            script.write_text('''import sys
from msplatform.io import manifest_records
from msplatform.backends.simion import field_worker
manifest_records._UNBUFFERED_SOLVER_PAYLOAD_BYTES=1
def forbidden(*args,**kwargs): raise AssertionError('EXECUTABLE_MUST_NOT_USE_PA_UNBUFFERED_READER')
manifest_records.file_sha256_unbuffered=forbidden
field_worker._native_operation=forbidden
field_worker.main()
''', encoding='utf-8')
            raw = root/'raw.pa#'
            raw.write_bytes(b'INERT_NOT_NATIVE_GEOMETRY')
            resources = {}
            for name in ('operating_builder','exporter','verifier'):
                path = root/(name+'.lua')
                path.write_text('-- INERT NOT EXECUTED', encoding='utf-8')
                resources[name] = path
            budget = root/'budget.json'
            budget.write_text('{"bytes":1048576}', encoding='utf-8')
            base_tool = dict(simion_identity=dict(release='SIMION 2020',
                executable_bytes=Path(sys.executable).stat().st_size, executable_sha256=file_sha256(sys.executable)),
                builder_identity={name:file_sha256(resources[name]) for name in ('operating_builder','exporter')})
            actual = RunSession.run_process
            def transport(session, operation_id, **kwargs):
                kwargs['arguments'] = ['-I','-B','-X','utf8',str(frozen_worker_fixture(session, script)),kwargs['arguments'][-1]]
                return actual(session, operation_id, **kwargs)
            private = dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN='', MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID='',
                MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE='', MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(context.host_state_path))
            policy = dict(_capacity_policy(), target_gib=1, minimum_free_gib=0)
            with patch.dict(os.environ, private), patch(
                    'msplatform.execution.capacity_admission._capacity_policy', return_value=policy), patch.object(
                    RunSession, 'run_process', new=transport):
                for case in ('valid_tool_bad_builder','tool_sha','tool_bytes'):
                    with self.subTest(case=case):
                        tool = copy.deepcopy(base_tool)
                        if case == 'tool_sha': tool['simion_identity']['executable_sha256'] = 'F'*64
                        elif case == 'tool_bytes': tool['simion_identity']['executable_bytes'] += 1
                        else: tool['builder_identity']['operating_builder'] = 'F'*64
                        def action(session):
                            session.add_input('preflight_fixture', file_record(script, 'required_evidence'))
                            return run_member(session, operation_id='member', parameters=dict(field_plan=plan,
                                domain_id='parent', member_id='carrier_off', tool_identity=tool,
                                raw_geometry_record=file_record(raw,'solver_native_binary'), resources=resources,
                                cache_root=session.artifact_root/'common/simion/pa_family_cache'), limits={})
                        run_id = '20261104_120000__test__python__preflight-'+case.replace('_','-')
                        with self.assertRaisesRegex(ProcessExecutionError,'Observed process failed with exit 1') as caught:
                            owner.run_managed_stage(context, descriptor=dict(project='instrument_assembly', mode='inert_preflight',software=[]),
                                run_id=run_id, payload={}, committed_new_bytes=1048576,
                                commitment_inputs=[file_record(budget,'required_evidence')],
                                retention=dict(policy_version=1, **{'class':'solver_review'},reason='inert preflight failure'),
                                expected_operation_ids=['member'],operation_dependencies={},action=action,
                                action_record=file_record(Path(__file__),'required_evidence'),
                                completion_api=lambda:SimpleNamespace(recoverable_batch_logs=lambda _root:set()))
                        self.assertFalse(any('accounting receipt failed' in value for value in getattr(caught.exception,'__notes__',[])))
                        run = context.workspace/'artifacts/projects/instrument_assembly/runs'/run_id
                        report = json.loads((run/'results/member.json').read_text())
                        self.assertEqual(report['status'],'failed')
                        self.assertEqual(report['native_count'],0)
                        self.assertEqual(report['native_operations'],[])
                        self.assertFalse(report['preflight_completed'])
                        self.assertFalse(report['cache_mutation_attempted'])
                        self.assertFalse(report['cache_transaction_attempted'])
                        self.assertFalse(report['accounting_deferred'])
                        self.assertIsNone(report['stopped_stage_accounting'])
                        self.assertEqual(report['request'],file_record(run/'inputs/member.json','required_evidence'))
                        expected = 'builder source identity differs' if case == 'valid_tool_bad_builder' else 'SHA-256 changed' if case == 'tool_sha' else 'byte count changed'
                        self.assertIn(expected,report['exception']['message'])
                        self.assertNotIn('UNBUFFERED',report['exception']['message'])
                        result_path = context.workspace/'artifacts/projects/instrument_assembly/scratch/workflow_results'/run_id/'result.json'
                        result = json.loads(result_path.read_text())
                        self.assertEqual(result['stage'],'complete')
                        self.assertEqual(result['exception']['message'],'Observed process failed with exit 1')
                        self.assertTrue(result['writers_confirmed'])
                        self.assertEqual(result['capacity_session']['status'],'released')
                        completion = json.loads((run/'results/execution_completion.json').read_text())
                        observation = completion['writer_completion']['operations'][0]['observation']
                        self.assertTrue(observation['exit_confirmed'])
                        self.assertGreater(observation['process_id'],0)
                        self.assertGreater(observation['process_started_at_utc_ticks'],0)
                        self.assertFalse((context.workspace/'artifacts/common/simion/pa_family_cache').exists())

    def test_unsafe_receipt_path_is_never_written_by_direct_worker_or_main(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); run=root/'run';run.mkdir()
            outside=root/'outside.json';outside.write_text('{"sentinel":true}',encoding='utf-8')
            original=outside.read_bytes()
            context=ExecutionContext(workspace=root,python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')),tools={},host_state_path=root/'private.sqlite3',
                policy_path=resource_path('host_resource_policy.json'))
            request=root/'request.json'
            value=dict(schema_version=1,context={name:str(getattr(context,name)) for name in (
                'workspace','python_executable','powershell_executable','host_state_path','policy_path','execution_root')},
                parameters=dict(cache_root=str(root/'cache'),run_directory=str(run),producer_run_config=str(run/'run_config.json'),
                    log_directory=str(run/'logs/member'),receipt_path=str(outside),resources={}))
            value['context']['tools']={}
            request.write_text(json.dumps(value),encoding='utf-8')
            with patch.object(sys,'argv',['field_worker',str(request)]), self.assertRaisesRegex(ValueError,'Member paths'):
                field_worker.main()
            self.assertEqual(outside.read_bytes(),original)
            with self.assertRaisesRegex(ValueError,'Member paths'):
                field_worker.execute_member(context,field_plan={},domain_id='parent',member_id='carrier_off',
                    tool_identity={},raw_geometry_record={},resources={},cache_root=root/'cache',
                    producer_run_config=run/'run_config.json',capacity_lease_id='',capacity_lease_owner='',
                    run_directory=run,log_directory=run/'logs/member',limits={},receipt_path=outside)
            self.assertEqual(outside.read_bytes(),original)

    def test_real_worker_cold_then_hit_share_inner_token_and_release_only_outer_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, numerics, _ = compiler_inputs(root / "author")
            compiled = compile_geometry(assembly, numerics=numerics)
            domains = copy.deepcopy(numerics["frontend_domains"])
            domains["parent"]["refine_convergence_v"] = dict(carrier_off=.001, rf_reference=.002, pulse_delta=.003)
            plan = plan_solve_fields(compiled, assembly["components_resolved"],
                drive=dict(pulse_voltage_policy_id="all_accelerator_electrodes_zero_before_pulse_v1", rf_reference_voltage_v=10000.),
                numerics=dict(boundary_policy="native_zero_neumann", frontend_domains=domains))
            resources = dict(operating_builder=native_resource_path("build_dirichlet_patch_operating_pa.lua"),
                exporter=native_resource_path("export_detached_standalone_pa.lua"),
                verifier=native_resource_path("audit_frontend_working_fields.lua"))
            tool = dict(simion_identity=dict(release="SIMION 2020", executable_bytes=Path(sys.executable).stat().st_size,
                executable_sha256=file_sha256(sys.executable)),
                builder_identity={name:file_sha256(resources[name]) for name in ("operating_builder", "exporter")})
            # Synthetic tool identity is confined to this explicitly inert fixture.
            key = canonical_pa_family_cache_key(operating_member_identity(plan, domain_id="parent",
                member_id="carrier_off", tool_identity=tool))
            raw = root / "raw.pa#"
            raw.write_bytes(b"INERT_NOT_GEOMETRY")
            raw_before = raw.read_bytes()
            script = root / "inert_worker.py"
            script.write_text(INERT_WORKER, encoding="utf-8")
            current = dict(script=script, plan=plan, member_id="carrier_off")
            budget = root / "budget.json"
            budget.write_text('{"bytes":10485760}', encoding="utf-8")
            context = ExecutionContext(workspace=root / "study", python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which("pwsh")), tools={"simion":Path(sys.executable)},
                host_state_path=root / "private-host.sqlite3", policy_path=resource_path("host_resource_policy.json"))
            policy = dict(_capacity_policy(), target_gib=1, minimum_free_gib=0)
            environment = dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN="",
                MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID="", MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE="",
                MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(context.host_state_path))
            actual_run_process = RunSession.run_process
            def inert_transport(session, operation_id, **kwargs):
                self.assertEqual(kwargs["arguments"][4:6], ["-m", "msplatform.backends.simion.field_worker"])
                kwargs["arguments"] = ["-I", "-B", "-X", "utf8", str(frozen_worker_fixture(session, current["script"])), kwargs["arguments"][-1]]
                try:
                    return actual_run_process(session, operation_id, **kwargs)
                except BaseException as failure:
                    stderr = session.log_dir / "operation_0001.stderr.log"
                    if stderr.is_file():
                        failure.add_note("INERT_WORKER_STDERR=" + stderr.read_text(encoding="utf-8"))
                    raise
            reports = []
            def action(session):
                session.add_input("inert_fixture", file_record(current["script"], "required_evidence"))
                reports.append(run_member(session, operation_id="member", parameters=dict(field_plan=current["plan"],
                    domain_id="parent", member_id=current["member_id"], tool_identity=tool,
                    raw_geometry_record=file_record(raw, "solver_native_binary"), resources=resources,
                    cache_root=session.artifact_root / "common/simion/pa_family_cache"), limits={}))
                parent = dict(cache_key=reports[-1]["cache_key"], record=dict(reports[-1]["record"], kind="carrier_off"))
                parent_kwargs = dict(lease_id=session.capacity_session["lease_id"], lease_owner=session.capacity_session["owner"])
                cache_root = session.artifact_root / "common/simion/pa_family_cache"
                _require_published_parent(cache_root, parent, "carrier_off", **parent_kwargs)
                if reports[-1]['native_count']:
                    transaction_path = cache_root / cache.TRANSACTION_DIRECTORY / reports[-1]['cache_key'] / cache.TRANSACTION_NAME
                    original_transaction = transaction_path.read_bytes()
                    self.assertEqual(cache.load_pa_family_cache_transaction(cache_root, reports[-1]['cache_key'])['published_pin_reason'],
                                     'Retain standalone fields required by published field products.')
                    with self.assertRaisesRegex(ValueError, 'published pin policy differs'):
                        cache.advance_pa_family_cache_transaction(cache_root,
                            operating_member_identity(current['plan'], domain_id='parent', member_id='carrier_off', tool_identity=tool),
                            ['frontend.carrier_off.pa'], owner=session.artifact_run_dir.name, producer_run_config=session.run_config,
                            recovery_policy='none', published_pin_reason='INERT_WRONG_EXISTING_PIN_REASON')
                    self.assertEqual(transaction_path.read_bytes(), original_transaction)
                for mutation in ("missing", "bytes", "sha256", "path", "lease"):
                    with self.subTest(parent=mutation):
                        changed = copy.deepcopy(parent)
                        kwargs = dict(parent_kwargs)
                        if mutation == "missing": changed["cache_key"] = "F" * 64
                        elif mutation == "bytes": changed["record"]["bytes"] += 1
                        elif mutation == "sha256": changed["record"]["sha256"] = "F" * 64
                        elif mutation == "path": changed["record"]["path"] = str(raw)
                        else: kwargs["lease_id"] = "absent-fixture-lease"
                        with self.assertRaises(ValueError):
                            _require_published_parent(cache_root, changed, "carrier_off", **kwargs)
                return dict(status="success", summary=dict(fixture="INERT_ONLY"), output_paths=[],
                    required_output_paths=[], retention_preserve_paths=[], manifest_extra_fields={})
            with patch.dict(os.environ, environment), patch(
                    "msplatform.execution.capacity_admission._capacity_policy", return_value=policy), patch.object(
                    RunSession, "run_process", new=inert_transport):
                for suffix in ("cold", "hit"):
                    result = owner.run_managed_stage(context,
                        descriptor=dict(project="instrument_assembly", mode="inert_field_transport", software=[]),
                        run_id="20261104_120000__test__python__field-"+suffix, payload={},
                        committed_new_bytes=10485760, commitment_inputs=[file_record(budget, "required_evidence")],
                        retention=dict(policy_version=1, **{"class":"solver_review"}, reason="inert worker fixture"),
                        expected_operation_ids=["member"], operation_dependencies={}, protected_cache_keys=[key],
                        action=action, action_record=file_record(Path(__file__), "required_evidence"),
                        completion_api=lambda: SimpleNamespace(recoverable_batch_logs=lambda _root: set()))
                    self.assertEqual(result["stage"], "complete")
                    completion = json.loads((Path(result["run_directory"])/"results/execution_completion.json").read_text())
                    writers = completion["writer_completion"]
                    self.assertEqual(len(writers["operations"]), 1)
                    self.assertEqual(len(writers["resource_releases"]), 1)
                    outer = writers["resource_releases"][0]["completion_receipt"]["host_release"]
                    self.assertFalse(outer["inherited"])
                    self.assertEqual(outer["result"]["status"], "released")
                    for row in reports[-1]["native_operations"]:
                        inner = row["receipt"]["host_release"]
                        self.assertTrue(inner["inherited"])
                        self.assertEqual(inner["token"], outer["token"])
                        self.assertGreater(row["receipt"]["observation"]["root_process_id"], 0)
                cache_root = context.workspace / "artifacts/common/simion/pa_family_cache"
                pointer = cache_root / key / cache.POINTER_NAME
                original_pointer = pointer.read_bytes()
                try:
                    broken = json.loads(original_pointer)
                    broken["generation_sha256"] = "F" * 64
                    pointer.write_text(json.dumps(broken), encoding="utf-8")
                    with self.assertRaises(ProcessExecutionError):
                        owner.run_managed_stage(context,
                            descriptor=dict(project="instrument_assembly", mode="inert_field_transport", software=[]),
                            run_id="20261104_120000__test__python__field-corrupt", payload={},
                            committed_new_bytes=10485760, commitment_inputs=[file_record(budget, "required_evidence")],
                            retention=dict(policy_version=1, **{"class":"solver_review"}, reason="inert corrupt cache fixture"),
                            expected_operation_ids=["member"], operation_dependencies={}, protected_cache_keys=[key],
                            action=action, action_record=file_record(Path(__file__), "required_evidence"),
                            completion_api=lambda: SimpleNamespace(recoverable_batch_logs=lambda _root: set()))
                    corrupt_run = context.workspace / "artifacts/projects/instrument_assembly/runs/20261104_120000__test__python__field-corrupt"
                    report = json.loads((corrupt_run/"results/member.json").read_text())
                    self.assertEqual(report["native_count"], 0)
                    self.assertIn("cache is not reusable", report["exception"]["message"])
                    self.assertFalse(report["accounting_deferred"])
                finally:
                    pointer.write_bytes(original_pointer)
                for index, stage in enumerate(("export", "audit", "accounting", "publication", "receipt"), 1):
                    with self.subTest(failure=stage):
                        fault_script = root / (stage + "_inert_worker.py")
                        fault_code = "FAULT_STAGE=" + repr("never" if stage == "publication" else "audit" if stage == "audit" else "export")
                        fault_code += "\nACCOUNTING_FAILURE=" + repr(stage == "accounting")
                        fault_code += "\nPUBLICATION_FAILURE=" + repr(stage == "publication") + "\nRECEIPT_FAILURE=" + repr(stage == "receipt") + "\n" + INERT_FAULT
                        fault_script.write_text(INERT_WORKER.replace("worker.main()", fault_code + "\nworker.main()"), encoding="utf-8")
                        fault_plan = copy.deepcopy(plan)
                        fault_plan["field_design"]["domains"][0]["refine_convergence_v"]["carrier_off"] = .004 + index * .001
                        fault_key = canonical_pa_family_cache_key(operating_member_identity(fault_plan,
                            domain_id="parent", member_id="carrier_off", tool_identity=tool))
                        current.update(script=fault_script, plan=fault_plan)
                        fault_run_id = "20261104_120000__test__python__field-" + stage
                        with self.assertRaisesRegex(ProcessExecutionError, "Observed process failed with exit 1"):
                            owner.run_managed_stage(context,
                                descriptor=dict(project="instrument_assembly", mode="inert_field_transport", software=[]),
                                run_id=fault_run_id, payload={}, committed_new_bytes=10485760,
                                commitment_inputs=[file_record(budget, "required_evidence")],
                                retention=dict(policy_version=1, **{"class":"solver_review"}, reason="inert worker fault"),
                                expected_operation_ids=["member"], operation_dependencies={}, protected_cache_keys=[fault_key],
                                action=action, action_record=file_record(Path(__file__), "required_evidence"),
                                completion_api=lambda: SimpleNamespace(recoverable_batch_logs=lambda _root: set()))
                        run = context.workspace / "artifacts/projects/instrument_assembly/runs" / fault_run_id
                        report = json.loads((run/"results/member.json").read_text())
                        self.assertEqual(report["status"], "failed")
                        self.assertEqual(report["native_count"], 3 if stage in {"audit","publication"} else 2)
                        self.assertEqual(report["accounting_deferred"], stage in {"accounting","publication"})
                        if stage in {"export", "accounting", "receipt"}:
                            transaction = cache.load_pa_family_cache_transaction(cache_root, fault_key)
                            directory = cache_root / cache.TRANSACTION_DIRECTORY / fault_key
                            self.assertEqual((directory / "build-scratch/frontend.carrier_off.pa").read_text(),
                                             "PARTIAL_EXPORT_NOT_PA")
                            self.assertFalse((directory / "payload/frontend.carrier_off.pa").exists())
                            self.assertEqual(transaction["status"], "building")
                        if stage == "receipt":
                            self.assertEqual(report["native_operations"][-1]["receipt"], {})
                            self.assertIn("INJECTED_MISSING_NATIVE_COMPLETION_RECEIPT", report["exception"]["message"])
                        result_path = context.workspace / "artifacts/projects/instrument_assembly/scratch/workflow_results" / fault_run_id / "result.json"
                        failed = json.loads(result_path.read_text())
                        self.assertTrue(failed["writers_confirmed"])
                        self.assertEqual(failed["exception"]["message"], "Observed process failed with exit 1")
                        if stage in {"accounting","publication"}:
                            self.assertEqual(failed["resume_action"], "return_to_capacity_accounting_owner")
                            self.assertFalse(failed["lease_released"])
                            if stage == "accounting":
                                self.assertIn("INJECTED_STOPPED_ACCOUNTING_FAILURE", report["accounting_error"])
                            else:
                                self.assertIn("INJECTED_PUBLICATION_FINALIZATION_FAILURE", report["exception"]["message"])
                                from msplatform.execution.capacity_ledger import load_capacity_ledger
                                ledger = load_capacity_ledger(context.workspace/'artifacts')
                                entry = next(row for row in ledger['objects'] if row.get('class') == 'published_cache'
                                             and row.get('identity') == cache.load_pa_family_cache_transaction(cache_root,fault_key)['generation_sha256'])
                                self.assertEqual(entry['status'], 'writing')
                                self.assertEqual(entry['bytes'], cache._key_root_bytes(cache_root/fault_key))
                                self.assertNotIn('newly_accounted_cache_bytes', report)
                            self.assertFalse((run/"retention_actions.json").exists())
                        else:
                            self.assertEqual(failed["stage"], "complete")
                            self.assertEqual(report["stopped_stage_accounting"]["status"], "building")
            self.assertEqual([row["native_count"] for row in reports], [3, 0])
            self.assertGreater(reports[0]['newly_accounted_cache_bytes'], 0)
            self.assertEqual(reports[0]['newly_accounted_cache_bytes'],
                             reports[0]['key_bytes_after'] - reports[0]['key_bytes_before'])
            self.assertEqual(reports[1]['newly_accounted_cache_bytes'], 0)
            self.assertEqual([row["cache_disposition"] for row in reports], ["miss", "hit"])
            self.assertEqual(reports[0]["record"], reports[1]["record"])
            self.assertEqual(Path(reports[0]["record"]["path"]).read_bytes(), b"INERT_NOT_PA")
            self.assertEqual(raw.read_bytes(), raw_before)


class ExplicitFutureGeometryTests(unittest.TestCase):
    def _plan(self, root):
        from common.contracts.test_simion_field_action import public_case
        from msplatform.backends.simion.field_execution import plan_fields_execution
        model, numerical, _clock, _root = public_case()
        plan = plan_fields_execution(model, numerics=numerical)["field_plan"]
        resources = {key: native_resource_path(name) for key, name in (
            ("operating_builder", "build_dirichlet_patch_operating_pa.lua"),
            ("exporter", "export_detached_standalone_pa.lua"),
            ("verifier", "audit_frontend_working_fields.lua"))}
        tool = dict(simion_identity=dict(release="SIMION 2020", executable_bytes=Path(sys.executable).stat().st_size,
                                        executable_sha256=file_sha256(sys.executable)),
                    builder_identity={key: file_sha256(resources[key]) for key in ("operating_builder", "exporter")})
        return plan, resources, tool

    def test_future_path_plans_the_same_operations_without_inventing_a_record_or_creating_file(self):
        from msplatform.backends.simion.native_plans import plan_operating_member
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, resources, tool = self._plan(root)
            raw = root / "frontend.pa#"; raw.write_bytes(b"INERT_REAL_RECORD_NOT_PA")
            arguments = dict(domain_id="parent", member_id="carrier_off", tool_identity=tool,
                             working_directory=root / "scratch", payload_directory=root / "payload", resource_paths=resources)
            actual = plan_operating_member(plan, raw_geometry_record=file_record(raw, "solver_native_binary"), **arguments)
            raw.unlink()
            future = plan_operating_member(plan, raw_geometry_record=None, raw_geometry_path=raw, **arguments)
            self.assertEqual(future, actual)
            self.assertFalse(raw.exists())
            with self.assertRaisesRegex(ValueError, "actual raw record or explicit future"):
                plan_operating_member(plan, raw_geometry_record=None, **arguments)
            with self.assertRaisesRegex(ValueError, "declared .pa#"):
                plan_operating_member(plan, raw_geometry_record=None, raw_geometry_path=root / "wrong.pa0", **arguments)

    def test_future_path_alone_or_escaped_output_cannot_authorize_native_work(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); run = root / "run"; (run / "inputs").mkdir(parents=True)
            (run / "results").mkdir(); (run / "run_config.json").write_text("{}")
            artifact_root = root / "artifacts"; cache_root = artifact_root / "common/simion/pa_family_cache"
            plan, resources, tool = self._plan(root)
            gem = run / "inputs/frontend.gem"; gem.write_bytes(b"INERT_GEM_NOT_EXECUTED")
            gem_record = file_record(gem, "required_evidence")
            context = ExecutionContext(workspace=root, python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which("pwsh")), tools={"simion":Path(sys.executable)},
                host_state_path=root / "unused.sqlite3", policy_path=resource_path("host_resource_policy.json"))
            session = dict(lease_id="original", owner="owner", artifact_root=str(artifact_root), committed_new_bytes=0)
            with patch.object(field_worker, "inherited_host_token", return_value="INERT_PREFLIGHT_ONLY"), patch.object(
                    field_worker, "_native_operation") as native, patch.object(cache, "probe_pa_family_cache") as probe:
                for case in ("missing_gem", "escaped_raw"):
                    args = {} if case == "missing_gem" else dict(gem_geometry_record=gem_record,
                        capacity_session=session, reserved_run_payload_bytes=0)
                    destination = run / "simion/raw.pa#" if case == "missing_gem" else root / "outside.pa#"
                    with self.subTest(case=case), self.assertRaisesRegex(ValueError, "requires frozen GEM|original-run ownership"):
                        field_worker.execute_member(context, field_plan=plan, domain_id="parent", member_id="carrier_off",
                            tool_identity=tool, raw_geometry_record=None, raw_geometry_path=destination,
                            resources=resources, cache_root=cache_root, producer_run_config=run / "run_config.json",
                            capacity_lease_id="original", capacity_lease_owner="owner", run_directory=run,
                            log_directory=run / "logs" / case, limits={}, receipt_path=run / "results" / (case+".json"), **args)
                    self.assertFalse(destination.exists())
                native.assert_not_called(); probe.assert_not_called()
