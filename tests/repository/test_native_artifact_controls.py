"""Store native fencing behavior; fixture host receipts are not native qualification."""
from __future__ import annotations

from multiprocessing import get_context
from contextlib import closing, ExitStack
import copy
from pathlib import Path
import json
import os
import sqlite3
import shutil
import sys
import tempfile
import time
import unittest

from msplatform.storage import ArtifactStore


def _host(path: Path, *, roots: list | None = None, present: bool = True) -> None:
    record = {"token": "fixture-token", "owner": {"pid": 7, "started": "123"},
              "status": "acquired", "work_roots": roots or []}
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY, document TEXT NOT NULL)")
        db.execute("INSERT OR REPLACE INTO state VALUES(1,?)", (json.dumps({"schema_version": 1,
                   "records": [record] if present else []}),))


def _native(ready, release, done) -> None:
    ready.set()
    release.wait(30)
    done.set()


def _controller(root: str, host: str, asset: str, started, native_ready, native_release, native_done, result) -> None:
    store = ArtifactStore(root)
    run, work = store.begin_run()
    (work / "input").write_bytes(b"frozen")
    with store.run_writer(run):
        store.mark_running(run)
        with store.claim_token(asset) as (claim, _), store.reserve(9) as reservation:
            binding = store.bind_native_controls(run, host_state_path=Path(host), host_token="fixture-token",
                host_owner={"pid": 7, "started": "123"}, operation_id="fly", claim_ids=(claim,),
                reservation_ids=(reservation,))
            worker = get_context("spawn").Process(target=_native, args=(native_ready, native_release, native_done))
            worker.start()
            if not native_ready.wait(20):
                raise RuntimeError("native fixture did not start")
            result.send((run, binding, worker.pid))
            started.set()
            worker.join(30)


def _real_controller(root: str, asset: str, started, block_binding=None, block_worker=None, guard_source=False) -> None:
    from msplatform.execution.context import ExecutionContext
    from msplatform.execution.native_artifact_controls import protect_native_controls
    from msplatform.execution.processes import run_observed_process
    from msplatform.execution.resources import resource_path
    base = Path(root)
    store = ArtifactStore(base / "store")
    if block_binding is not None:
        original_bind = store.bind_native_controls
        def waiting_bind(*args, **kwargs):
            block_binding.set()
            get_context("spawn").Event().wait(30)
            return original_bind(*args, **kwargs)
        store.bind_native_controls = waiting_bind
    if block_worker is not None:
        original_record = store.record_native_worker
        def waiting_record(*args, **kwargs):
            block_worker.set()
            get_context("spawn").Event().wait(30)
            return original_record(*args, **kwargs)
        store.record_native_worker = waiting_record
    context = ExecutionContext(workspace=base, python_executable=Path(sys.executable).resolve(),
        powershell_executable=Path(shutil.which("pwsh")).resolve(), tools={},
        host_state_path=base / "actual-host.sqlite", policy_path=resource_path("host_resource_policy.json"))
    run, work = store.begin_run()
    (work / "input").write_bytes(b"frozen")
    with ExitStack() as sources, store.run_writer(run):
        store.mark_running(run)
        protected = {}
        if guard_source:
            from types import SimpleNamespace
            from msplatform.execution.capacity_protection import create_capacity_protection_lease
            from msplatform.execution.run_session import RunSession
            from msplatform.io.file_identity import guarded_file_identity
            from msplatform.io.manifest_records import file_record
            old_root = base / "old-owner"
            old_root.mkdir()
            source = old_root / "source.pa"
            source.write_bytes(b"immutable native field")
            sources.enter_context(guarded_file_identity(source))
            create_capacity_protection_lease(old_root, lease_id="source", owner="fixture", ttl_seconds=3600,
                                            protected_paths=[source])
            holder = SimpleNamespace(_holder_started_at_utc_ticks=None)
            protected = {"immutable_input_records": [file_record(source, "required_evidence")],
                "immutable_input_session": {"schema_version": 1, "role": "run_immutable_input_session",
                "run_id": "native-fixture", "operation_id": "worker", "lease_id": "source",
                "artifact_root": str(old_root), "lease_owner": "fixture", "holder_pid": os.getpid(),
                "holder_started_at_utc_ticks": RunSession._holder_start_ticks(holder)}}
        with store.claim_token(asset) as (claim, _), store.reserve(9) as reservation:
            with protect_native_controls(store, run_id=run, claim_ids=(claim,),
                                         reservation_ids=(reservation,), work_directory=work):
                started.set()
                code = "import pathlib,time,sys;p=pathlib.Path(sys.argv[1]);p.with_name('worker-started').touch();\nwhile not p.exists(): time.sleep(.05)"
                run_observed_process(context, executable=Path(sys.executable).resolve(),
                    arguments=["-c", code, str(base / "release-worker")], working_directory=base,
                    run_directory=base, stdout_path=base / "stdout.log", stderr_path=base / "stderr.log",
                    usage_path=base / "usage.json", role="GATE", stage="native_fixture", run_id="native-fixture",
                    limits=None, operation_id="worker", **protected)


def _real_group_controller(root: str, asset: str, started, quick=False, pressure=False, block_attempt=None) -> None:
    from unittest.mock import patch
    from msplatform.execution.native_artifact_controls import protect_native_controls
    from msplatform.execution.processes import run_observed_process_group
    from msplatform.execution.resources import resource_path
    from msplatform.io.manifest_records import file_record
    from tests.contracts.test_batch_processes import BatchProcessTests
    base = Path(root)
    store = ArtifactStore(base / "store")
    if block_attempt is not None:
        original_record = store.record_native_group_worker
        def wait_second(*args, **kwargs):
            if kwargs.get("attempt") == 2:
                block_attempt.set()
                get_context("spawn").Event().wait(60)
            return original_record(*args, **kwargs)
        store.record_native_group_worker = wait_second
    context, data, folder, _, plan, specs = BatchProcessTests().fixture(base)
    if pressure:
        plan["limits"].update(memory_critical_seconds=1, memory_recovery_stable_seconds=1,
                              launch_stagger_seconds=1, memory_policy="normal", memory_admission_reserve_bytes=plan["limits"]["memory_critical_reserve_bytes"] + 1)
        owner = folder / "batch_process_owner.ps1"
        text = owner.read_text(encoding="utf-8")
        marker = "function Get-SystemCpuPercent {return 0}"
        injection = """
$script:originalStop=${function:Stop-ManagedSolverProcesses}
function Get-RepositoryAvailableMemoryBytes {
 if((Test-Path -LiteralPath 'HEALTHY')-and(Test-Path -LiteralPath 'FAILURE')-and-not(Test-Path -LiteralPath 'STOPPED')){return [int64]1}
 return [int64](64GB)
}
function Stop-ManagedSolverProcesses {param([int[]]$ProcessIds,[hashtable]$ExpectedStartedAtUtcTicks=@{})
 & $script:originalStop -ProcessIds $ProcessIds -ExpectedStartedAtUtcTicks $ExpectedStartedAtUtcTicks
 [IO.File]::WriteAllText('STOPPED','stopped')
}
""".replace("HEALTHY", str(base / "healthy.started")).replace("FAILURE", str(base / "failure.started")).replace("STOPPED", str(base / "pressure-stopped"))
        owner.write_text(text.replace(marker, marker + injection), encoding="utf-8", newline="\n")
    code = "import pathlib,time,sys;root=pathlib.Path(sys.argv[1]);(root/(sys.argv[2]+'.started')).touch();\nwhile not (root/'release-group').exists(): time.sleep(.05)"
    if pressure:
        code = code.replace("while not (root/'release-group').exists():", "while not (root/'release-group').exists() and not (sys.argv[2]=='healthy' and (root/'release-healthy').exists()):")
    for spec in specs:
        if not quick or spec["operation_id"] == "healthy":
            spec["arguments"] = ["-I", "-c", code, str(base), spec["operation_id"]]
    run, work = store.begin_run()
    (work / "input").write_bytes(b"frozen")
    with store.run_writer(run):
        store.mark_running(run)
        with store.claim_token(asset) as (claim, _), store.reserve(9) as reservation:
            with protect_native_controls(store, run_id=run, claim_ids=(claim,),
                                         reservation_ids=(reservation,), work_directory=work):
                started.set()
                with patch("msplatform.execution.processes.resource_path", side_effect=
                           lambda name: folder / name if name == "batch_process_owner.ps1" else resource_path(name)):
                    run_observed_process_group(context, specifications=specs, dispatch_plan=plan,
                        run_directory=base, usage_path=base / "group.json", role="GATE", stage="unclassified",
                        run_id="protected-group", immutable_input_records=[file_record(data, "solver_native_binary")])


def _single_fault_controller(root: str, asset: str, started, mode: str) -> None:
    from unittest.mock import patch
    from msplatform.execution.context import ExecutionContext
    from msplatform.execution.native_artifact_controls import protect_native_controls
    from msplatform.execution.processes import run_observed_process
    from msplatform.execution.resources import resource_path
    base = Path(root)
    folder = base / "single-owner"
    folder.mkdir()
    for name in ("process_owner.ps1", "host_execution_lease.ps1", "resource_process_support.ps1", "payload_file_support.ps1"):
        text = resource_path(name).read_text(encoding="utf-8")
        if name == "process_owner.ps1":
            if mode == "quick":
                needle = "      while($registration-eq'registered'-and-not(Test-Path"
                injection = "      if($registration-eq'quick_exit'){while(-not(Test-Path -LiteralPath '" + str(base / "release-single") + "')){Start-Sleep -Milliseconds 30}}\n"
                text = text.replace(needle, injection + needle)
            else:
                text = text.replace("  $onStarted=$null", "  function Register-HostResourceProcess {throw 'INJECTED_REGISTRATION_FAILURE'}\n  $onStarted=$null")
        (folder / name).write_text(text, encoding="utf-8", newline="\n")
    context = ExecutionContext(workspace=base, python_executable=Path(sys.executable),
        powershell_executable=Path(shutil.which("pwsh")), tools={},
        host_state_path=Path(os.environ["MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH"]),
        policy_path=resource_path("host_resource_policy.json"))
    store = ArtifactStore(base / "store")
    run, work = store.begin_run()
    code = ("import time;time.sleep(.2)" if mode == "quick" else
            "import pathlib,time,sys;p=pathlib.Path(sys.argv[1]);p.with_name('single-started').touch();\nwhile not p.exists():time.sleep(.05)")
    with store.run_writer(run):
        store.mark_running(run)
        with store.claim_token(asset) as (claim, _), store.reserve(9) as reservation:
            with protect_native_controls(store, run_id=run, claim_ids=(claim,), reservation_ids=(reservation,), work_directory=work):
                started.set()
                with patch("msplatform.execution.processes.resource_path", side_effect=
                           lambda name: folder / name if name == "process_owner.ps1" else resource_path(name)):
                    run_observed_process(context, executable=Path(sys.executable),
                        arguments=["-c", code, str(base / "release-single")], working_directory=base,
                        run_directory=base, stdout_path=base/"single.out", stderr_path=base/"single.err",
                        usage_path=base/"single.json", role="GATE", stage="unclassified", run_id="single-fault",
                        limits=None, operation_id="single")


class NativeArtifactControlsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ArtifactStore(self.root / "store")
        work = self.store.new_work()
        (work / "field").write_bytes(b"field")
        self.asset = self.store.put_asset("field", "key", work)
        self.host = self.root / "host.sqlite"
        _host(self.host)

    def test_dead_holder_and_live_worker_retain_every_bound_control(self) -> None:
        context = get_context("spawn")
        started, native_ready, native_release, native_done = (context.Event() for _ in range(4))
        receive, send = context.Pipe(duplex=False)
        process = context.Process(target=_controller, args=(str(self.store.root), str(self.host), self.asset,
            started, native_ready, native_release, native_done, send))
        process.start()
        try:
            self.assertTrue(started.wait(20))
            run, binding, worker_pid = receive.recv()
            process.terminate()
            process.join(20)
            self.assertFalse(process.is_alive())
            self.assertEqual(self.store.recover_controls(), [])
            self.assertEqual(self.store.recover_interrupted_runs(), [])
            self.assertEqual(self.store.collect(100)["released_bytes"], 0)
            self.assertEqual(self.store.run_status(run)["execution_status"], "running")
            with self.store._db() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM claims").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT SUM(remaining) FROM reservations").fetchone()[0], 9)
                self.assertEqual(db.execute("SELECT state FROM native_bindings WHERE id=?", (binding,)).fetchone()[0], "active")
            self.assertEqual(self.store.recover_controls(), [])
            native_release.set()
            self.assertTrue(native_done.wait(20))
            # Without a verified host-owner completion, even a stopped fixture stays protected.
            self.assertEqual(self.store.recover_controls(), [])
            # Fixture-only receipt tests the later state transition; it is not
            # claimed as a real scheduler/native completion observation.
            _host(self.host, roots=[{"pid": worker_pid, "started": "1234"}])
            self.store.record_native_worker(binding, process_id=worker_pid, started_at_utc_ticks=1234)
            _host(self.host, present=False)
            completion = {"writers_stopped": True, "operations": [{"operation_id": "fly",
                "resource_release_id": "release", "observation": {"exit_confirmed": True, "returncode": 0,
                "process_id": worker_pid, "process_started_at_utc_ticks": 1234}}],
                "resource_releases": [{"release_id": "release", "completion_receipt": {"host_release": {
                "inherited": False, "token": "fixture-token", "error": None,
                "result": {"status": "released", "token": "fixture-token"}}}}]}
            self.assertTrue(self.store.complete_native_controls(binding, completion=completion))
            self.assertFalse(self.store.complete_native_controls(binding, completion=completion))
            self.assertEqual(self.store.collect(100)["released_bytes"], 5)
            self.assertEqual(self.store.recover_interrupted_runs(), [run])
        finally:
            if process.is_alive():
                process.terminate()
                process.join(20)
            native_release.set()

    def test_pre_handshake_owner_failure_retains_untrusted_diagnostics(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import patch
        from msplatform.execution.processes import _invoke_native_artifact_owner, _interpret_process_result, ProcessExecutionError
        class FailedOwner:
            returncode = 7
            def communicate(self, _request):
                return b'owner stdout', b'host acquire failed'
        context = SimpleNamespace(powershell_executable=Path(sys.executable), host_state_path=self.host,
                                  python_executable=Path(sys.executable))
        inherited = {'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN': 'parent-token',
                     'MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID': '123',
                     'MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE': 'GATE'}
        with patch.dict(os.environ, inherited), patch('msplatform.execution.processes.subprocess.Popen',
                return_value=FailedOwner()) as launched:
            with self.assertRaisesRegex(ValueError, 'host acquire failed') as caught:
                _invoke_native_artifact_owner(context, {}, {'work_directory': self.root},
                                              _interpret_process_result, 'process_owner.ps1')
        environment = launched.call_args.kwargs['env']
        for name in inherited:
            self.assertNotIn(name, environment)
        self.assertEqual(environment['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH'], str(self.host))
        error = caught.exception
        self.assertIsInstance(error.__cause__, ProcessExecutionError)
        self.assertTrue(error.execution_bridge_started)
        self.assertEqual(error.owner_stdout, b'owner stdout')
        self.assertEqual(error.owner_stderr, b'host acquire failed')
        self.assertEqual(error.owner_returncode, 7)
        self.assertEqual(error.unverified_owner_receipt, {})

    def test_standalone_store_stage_publishes_and_preserves_failure(self) -> None:
        from unittest.mock import patch
        from msplatform.backends.simion import native_completion
        from msplatform.execution.context import ExecutionContext
        from msplatform.execution.owner import run_managed_stage
        from msplatform.execution.resources import resource_path
        from msplatform.io.manifest_records import file_record
        budget = self.root / 'budget.json'
        budget.write_text('{"bytes":1000000}', encoding='utf-8')
        context = ExecutionContext(workspace=self.root / 'standalone', python_executable=Path(sys.executable),
            powershell_executable=Path(shutil.which('pwsh') or sys.executable), tools={},
            host_state_path=self.host, policy_path=resource_path('host_resource_policy.json'))
        def action(session):
            output = session.declare_file(session.result_dir / 'output.bin', 'solver_native_binary')
            output.write_bytes(b'standalone')
            return dict(status='success', summary={}, output_paths=[str(output)],
                        required_output_paths=[str(output)], retention_preserve_paths=[], manifest_extra_fields={})
        arguments = dict(descriptor=dict(project='instrument_assembly', mode='test', software=[]),
            run_id='20261127_000000__test__python__standalone', payload={}, committed_new_bytes=1000000,
            commitment_inputs=[file_record(budget, 'required_evidence')],
            retention={'policy_version': 1, 'class': 'solver_review', 'reason': 'test'},
            expected_operation_ids=[], operation_dependencies={}, action=action,
            action_record=file_record(Path(__file__), 'required_evidence'), completion_api=lambda: native_completion,
            artifact_store=self.store)
        with patch('msplatform.execution.owner.path_capacity', return_value={'legacy_windows_compatible': True}):
            result = run_managed_stage(context, **arguments)
        self.assertEqual(result['status'], 'success')
        self.assertTrue(Path(result['manifest']['path']).is_file())
        self.assertEqual(self.store.run_status(result['store_run_id'])['execution_status'], 'succeeded')
        self.assertFalse((context.workspace / 'artifacts').exists())
        self.store.collect(1000000)
        self.assertTrue(Path(result['manifest']['path']).is_file())
        def failed(_session):
            raise RuntimeError('real action failure')
        arguments.update(run_id='20261127_000001__test__python__standalone', action=failed)
        with patch('msplatform.execution.owner.path_capacity', return_value={'legacy_windows_compatible': True}):
            with self.assertRaisesRegex(RuntimeError, 'real action failure') as caught:
                run_managed_stage(context, **arguments)
        failed_run = next(note.removeprefix('Store run_id: ') for note in caught.exception.__notes__
                          if note.startswith('Store run_id: '))
        self.assertEqual(self.store.run_status(failed_run)['execution_status'], 'failed')
        self.assertEqual(self.store.run_status(failed_run)['publication_status'], 'unpublished')
        def reported_failure(_session):
            return dict(status='failed', summary={}, output_paths=[], required_output_paths=[],
                        retention_preserve_paths=[], manifest_extra_fields={})
        arguments.update(run_id='20261127_000002__test__python__standalone', action=reported_failure)
        with patch('msplatform.execution.owner.path_capacity', return_value={'legacy_windows_compatible': True}):
            result = run_managed_stage(context, **arguments)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.store.run_status(result['store_run_id'])['execution_status'], 'failed')
        self.assertIsNone(result['store_run_path'])
        def reported_interruption(_session):
            return dict(status='interrupted', summary={}, output_paths=[], required_output_paths=[],
                        retention_preserve_paths=[], manifest_extra_fields={})
        arguments.update(run_id='20261127_000003__test__python__standalone', action=reported_interruption)
        with patch('msplatform.execution.owner.path_capacity', return_value={'legacy_windows_compatible': True}):
            result = run_managed_stage(context, **arguments)
        self.assertEqual(result['status'], 'interrupted')
        self.assertEqual(self.store.run_status(result['store_run_id'])['execution_status'], 'failed')
        self.assertIsNone(result['store_run_path'])

    def test_managed_store_stage_publishes_at_stable_path_without_old_ledger(self) -> None:
        from contextlib import ExitStack
        from unittest.mock import patch
        from msplatform.backends.simion import native_completion
        from msplatform.execution.context import ExecutionContext
        from msplatform.execution.native_artifact_controls import protect_native_controls
        from msplatform.execution.owner import managed_native_store, run_managed_stage
        from msplatform.execution.resources import resource_path
        from msplatform.io.manifest_records import file_record
        budget = self.root / "budget.json"
        budget.write_text('{"bytes":100}', encoding="utf-8")
        context = ExecutionContext(workspace=self.root / "study", python_executable=Path(sys.executable),
            powershell_executable=Path(shutil.which("pwsh") or sys.executable), tools={},
            host_state_path=self.host, policy_path=resource_path("host_resource_policy.json"))
        def action(session):
            output = session.declare_file(session.result_dir / "output.bin", "solver_native_binary")
            output.write_bytes(b"native stand-in")
            product = {"schema_version": 1, "kind": "geometry_artifact", "status": "complete",
                       "metadata": {}, "data": {"geometry": file_record(output, "solver_native_binary")}}
            return dict(status="success", summary={}, output_paths=[str(output)],
                        required_output_paths=[str(output)], retention_preserve_paths=[],
                        manifest_extra_fields={"products": {"geometry": product}})
        run, work = self.store.begin_run()
        with self.store.run_writer(run):
            self.store.mark_running(run)
            with ExitStack() as lifetime, self.store.claim_token(self.asset) as (claim, _), self.store.reserve(1000000) as reservation:
                with protect_native_controls(self.store, run_id=run, claim_ids=(claim,),
                        reservation_ids=(reservation,), work_directory=work), managed_native_store(
                        self.store, task_key="actual-task-key", lifetime=lifetime, account=lambda _path: None), patch.object(
                        __import__("msplatform.execution.owner", fromlist=["owner"]), "path_capacity", return_value={"legacy_windows_compatible": True}):
                    result = run_managed_stage(context, descriptor=dict(project="instrument_assembly", mode="test", software=[]),
                        run_id="20261127_000000__test__python__store-stage", payload={}, committed_new_bytes=100,
                        commitment_inputs=[file_record(budget, "required_evidence")],
                        retention={"policy_version": 1, "class": "solver_review", "reason": "inert test"},
                        expected_operation_ids=[], operation_dependencies={}, action=action,
                        action_record=file_record(Path(__file__), "required_evidence"), completion_api=lambda: native_completion)
                self.assertEqual(result["status"], "success")
                manifest = Path(result["manifest"]["path"])
                self.assertTrue(manifest.is_file())
                self.assertTrue(manifest.is_relative_to(self.store.root / "assets" / "native_stage"))
                self.assertFalse((context.workspace / "artifacts").exists())
                from msplatform.execution.native_source_guard import guard_native_source
                with guard_native_source({"manifest": result["manifest"], "product_id": "geometry"},
                        expected_kind="geometry_artifact", expected_artifact_root=context.workspace / "artifacts",
                        artifact_store=self.store) as artifact:
                    self.assertEqual(artifact.data_path("geometry").read_bytes(), b"native stand-in")
                    self.assertEqual(self.store.collect(100)["released_bytes"], 0)
                (manifest.parent / "results" / "output.bin").write_bytes(b"tampered")
                with self.assertRaisesRegex(ValueError, "incomplete or modified"):
                    with guard_native_source({"manifest": result["manifest"], "product_id": "geometry"},
                            expected_kind="geometry_artifact", expected_artifact_root=context.workspace / "artifacts",
                            artifact_store=self.store):
                        pass
            self.store.finish_run(run, "succeeded")

    @unittest.skipUnless(os.name == "nt", "Windows immutable file sharing required")
    def test_store_stage_replays_completed_terminal_after_seal_interruption(self) -> None:
        from contextlib import ExitStack
        from unittest.mock import patch
        from msplatform.backends.simion import native_completion
        from msplatform.execution import owner
        from msplatform.execution.context import ExecutionContext
        from msplatform.execution.native_artifact_controls import protect_native_controls
        from msplatform.execution.resources import resource_path
        from msplatform.io.manifest_records import file_record
        budget = self.root / "budget.json"
        budget.write_text('{"bytes":100}', encoding="utf-8")
        context = ExecutionContext(workspace=self.root / "study", python_executable=Path(sys.executable),
            powershell_executable=Path(shutil.which("pwsh") or sys.executable), tools={},
            host_state_path=self.host, policy_path=resource_path("host_resource_policy.json"))
        def action(session):
            output = session.declare_file(session.result_dir / "output.bin", "solver_native_binary")
            output.write_bytes(b"original")
            def interrupted(**_kwargs):
                raise OSError("seal interrupted")
            session._store_seal = interrupted
            return dict(status="success", summary={}, output_paths=[str(output)],
                        required_output_paths=[str(output)], retention_preserve_paths=[], manifest_extra_fields={})
        run, work = self.store.begin_run()
        with self.store.run_writer(run):
            self.store.mark_running(run)
            with ExitStack() as lifetime, self.store.claim_token(self.asset) as (claim, _), self.store.reserve(1000000) as reservation:
                with protect_native_controls(self.store, run_id=run, claim_ids=(claim,), reservation_ids=(reservation,),
                        work_directory=work), owner.managed_native_store(self.store, task_key="interrupted-stage", lifetime=lifetime,
                        account=lambda _path: None), patch.object(owner, "path_capacity", return_value={"legacy_windows_compatible": True}):
                    with self.assertRaisesRegex(OSError, "seal interrupted"):
                        owner.run_managed_stage(context, descriptor=dict(project="instrument_assembly", mode="test", software=[]),
                            run_id="20261127_000000__test__python__recover-stage", payload={}, committed_new_bytes=100,
                            commitment_inputs=[file_record(budget, "required_evidence")],
                            retention={"policy_version": 1, "class": "solver_review", "reason": "inert test"},
                            expected_operation_ids=[], operation_dependencies={}, action=action,
                            action_record=file_record(Path(__file__), "required_evidence"), completion_api=lambda: native_completion)
            self.store.finish_run(run, "failed", reason="owner interrupted")
        with self.store._db() as db:
            identity, state = db.execute("SELECT id,state FROM assets WHERE key LIKE 'interrupted-stage:%'").fetchone()
        self.assertEqual(state, "publishing")
        self.assertTrue(owner.recover_managed_native_store_stage(self.store, identity, context=context))
        self.assertFalse(owner.recover_managed_native_store_stage(self.store, identity, context=context))
        with self.store.claim_verified(identity) as path:
            self.assertEqual(next(path.rglob("output.bin")).read_bytes(), b"original")

    @unittest.skipUnless(os.name == "nt", "Windows immutable file sharing required")
    def test_store_stage_replays_failed_terminal_without_success_cache(self) -> None:
        from contextlib import ExitStack
        from unittest.mock import patch
        from msplatform.backends.simion import native_completion
        from msplatform.execution import owner
        from msplatform.execution.context import ExecutionContext
        from msplatform.execution.native_artifact_controls import protect_native_controls
        from msplatform.execution.resources import resource_path
        from msplatform.io.manifest_records import file_record
        budget = self.root / "budget.json"
        budget.write_text('{"bytes":100}', encoding="utf-8")
        context = ExecutionContext(workspace=self.root / "study", python_executable=Path(sys.executable),
            powershell_executable=Path(shutil.which("pwsh") or sys.executable), tools={},
            host_state_path=self.host, policy_path=resource_path("host_resource_policy.json"))
        def action(session):
            output = session.declare_file(session.result_dir / "output.bin", "solver_native_binary")
            output.write_bytes(b"original")
            def interrupted(**_kwargs):
                raise OSError("seal interrupted")
            session._store_seal = interrupted
            raise RuntimeError("original native failure")
        run, work = self.store.begin_run()
        with self.store.run_writer(run):
            self.store.mark_running(run)
            with ExitStack() as lifetime, self.store.claim_token(self.asset) as (claim, _), self.store.reserve(1000000) as reservation:
                with protect_native_controls(self.store, run_id=run, claim_ids=(claim,), reservation_ids=(reservation,),
                        work_directory=work), owner.managed_native_store(self.store, task_key="failed-stage", lifetime=lifetime,
                        account=lambda _path: None), patch.object(owner, "path_capacity", return_value={"legacy_windows_compatible": True}):
                    with self.assertRaisesRegex(RuntimeError, "original native failure"):
                        owner.run_managed_stage(context, descriptor=dict(project="instrument_assembly", mode="test", software=[]),
                            run_id="20261127_000000__test__python__recover-stage", payload={}, committed_new_bytes=100,
                            commitment_inputs=[file_record(budget, "required_evidence")],
                            retention={"policy_version": 1, "class": "solver_review", "reason": "inert test"},
                            expected_operation_ids=[], operation_dependencies={}, action=action,
                            action_record=file_record(Path(__file__), "required_evidence"), completion_api=lambda: native_completion)
            self.store.finish_run(run, "failed", reason="owner interrupted")
        with self.store._db() as db:
            identity, state = db.execute("SELECT id,state FROM assets WHERE key LIKE 'failed-stage:%'").fetchone()
        self.assertEqual(state, "publishing")
        self.assertTrue(owner.recover_managed_native_store_stage(self.store, identity, context=context))
        self.assertFalse(owner.recover_managed_native_store_stage(self.store, identity, context=context))
        with self.store._db() as db:
            state, reason, relative = db.execute("SELECT state,failure,path FROM assets WHERE id=?", (identity,)).fetchone()
        self.assertEqual(state, "failed")
        self.assertIn("original native failure", reason)
        self.assertEqual(next((self.store.root / relative).rglob("output.bin")).read_bytes(), b"original")

    @unittest.skipUnless(os.name == "nt", "Windows immutable file sharing required")
    def test_store_stage_guards_explicit_borrowed_old_owner_field(self) -> None:
        from contextlib import ExitStack
        from unittest.mock import patch
        from msplatform.backends.simion import native_completion
        from msplatform.execution import owner
        from msplatform.execution.context import ExecutionContext
        from msplatform.execution.native_artifact_controls import protect_native_controls
        from msplatform.execution.native_source_guard import guard_native_source
        from msplatform.execution.resources import resource_path
        from msplatform.io.manifest_records import file_record
        from tests.execution.test_native_source_guard import NativeSourceGuardTests
        legacy_root, borrowed, origin = NativeSourceGuardTests().fixture(self.root)
        origin_path = Path(origin["manifest"]["path"])
        document = json.loads(origin_path.read_text(encoding="utf-8"))
        document["products"]["geometry"]["kind"] = "field_bundle"
        origin_path.write_text(json.dumps(document), encoding="utf-8")
        origin["manifest"] = file_record(origin_path)
        budget = self.root / "budget.json"
        budget.write_text('{"bytes":100}', encoding="utf-8")
        context = ExecutionContext(workspace=self.root / "study", python_executable=Path(sys.executable),
            powershell_executable=Path(shutil.which("pwsh") or sys.executable), tools={},
            host_state_path=self.host, policy_path=resource_path("host_resource_policy.json"))
        def action(session):
            record = file_record(borrowed, "required_evidence")
            session.add_input("borrowed", record)
            product = {"schema_version": 1, "kind": "field_bundle", "status": "complete",
                "metadata": {"ground_source_reference": origin}, "data": {"payload": record}}
            return dict(status="success", summary={}, output_paths=[], required_output_paths=[],
                        retention_preserve_paths=[], manifest_extra_fields={"products": {"fields": product}})
        run, work = self.store.begin_run()
        with self.store.run_writer(run):
            self.store.mark_running(run)
            with ExitStack() as lifetime, self.store.claim_token(self.asset) as (claim, _), self.store.reserve(1000000) as reservation:
                with protect_native_controls(self.store, run_id=run, claim_ids=(claim,), reservation_ids=(reservation,),
                        work_directory=work), owner.managed_native_store(self.store, task_key="borrowed", lifetime=lifetime, account=lambda _path: None), patch.object(
                        owner, "path_capacity", return_value={"legacy_windows_compatible": True}):
                    result = owner.run_managed_stage(context, descriptor=dict(project="instrument_assembly", mode="test", software=[]),
                        run_id="20261127_000000__test__python__borrowed", payload={}, committed_new_bytes=100,
                        commitment_inputs=[file_record(budget, "required_evidence")],
                        retention={"policy_version": 1, "class": "solver_review", "reason": "inert test"},
                        expected_operation_ids=[], operation_dependencies={}, action=action,
                        action_record=file_record(Path(__file__), "required_evidence"), completion_api=lambda: native_completion)
                with guard_native_source({"manifest": result["manifest"], "product_id": "fields"},
                        expected_kind="field_bundle", expected_artifact_root=legacy_root, artifact_store=self.store) as artifact:
                    self.assertEqual(artifact.data_path("payload"), borrowed)
                    with self.assertRaises(OSError):
                        borrowed.unlink()
            self.store.finish_run(run, "succeeded")

    @unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell required")
    def test_managed_store_stage_runs_protected_short_process(self) -> None:
        from contextlib import ExitStack
        from unittest.mock import patch
        from msplatform.backends.simion import native_completion
        from msplatform.execution import owner
        from msplatform.execution.context import ExecutionContext
        from msplatform.execution.native_artifact_controls import protect_native_controls
        from msplatform.execution.resources import resource_path
        from msplatform.io.manifest_records import file_record
        budget = self.root / "budget.json"
        budget.write_text('{"bytes":100}', encoding="utf-8")
        context = ExecutionContext(workspace=self.root / "study", python_executable=Path(sys.executable),
            powershell_executable=Path(shutil.which("pwsh")), tools={},
            host_state_path=self.root / "actual-host.sqlite", policy_path=resource_path("host_resource_policy.json"))
        source = self.root / "immutable-source.bin"
        source.write_bytes(b"original")
        def action(session):
            code = "from pathlib import Path; import sys; p=Path(sys.argv[1]);\ntry:p.write_bytes(b'changed')\nexcept OSError:pass\nelse:raise SystemExit(3)"
            session.run_process("worker", executable=Path(sys.executable), arguments=["-c", code, str(source)],
                role="GATE", stage="store_fixture", limits=None,
                immutable_input_records=[file_record(source, "required_evidence")])
            output = session.declare_file(session.result_dir / "output.bin", "solver_native_binary")
            output.write_bytes(b"native stand-in")
            return dict(status="success", summary={}, output_paths=[str(output)],
                        required_output_paths=[str(output)], retention_preserve_paths=[], manifest_extra_fields={})
        run, work = self.store.begin_run()
        with self.store.run_writer(run):
            self.store.mark_running(run)
            with ExitStack() as lifetime, self.store.claim_token(self.asset) as (claim, _), self.store.reserve(1000000) as reservation:
                with protect_native_controls(self.store, run_id=run, claim_ids=(claim,), reservation_ids=(reservation,),
                        work_directory=work), owner.managed_native_store(self.store, task_key="worker-task", lifetime=lifetime, account=lambda _path: None), patch.object(
                        owner, "path_capacity", return_value={"legacy_windows_compatible": True}):
                    result = owner.run_managed_stage(context, descriptor=dict(project="instrument_assembly", mode="test", software=[]),
                        run_id="20261127_000000__test__python__store-child", payload={}, committed_new_bytes=100,
                        commitment_inputs=[file_record(budget, "required_evidence")],
                        retention={"policy_version": 1, "class": "solver_review", "reason": "inert test"},
                        expected_operation_ids=["worker"], operation_dependencies={}, action=action,
                        action_record=file_record(Path(__file__), "required_evidence"), completion_api=lambda: native_completion)
                self.assertEqual(result["status"], "success")
                self.assertEqual(source.read_bytes(), b"original")
                self.assertFalse((context.workspace / "artifacts").exists())
                with self.store._db() as db:
                    self.assertEqual(db.execute("SELECT state FROM native_bindings WHERE run_id=?", (run,)).fetchall(), [("complete",)])
            self.store.finish_run(run, "succeeded")

    @unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell required")
    def test_managed_store_stage_launch_failure_keeps_failed_evidence(self) -> None:
        from contextlib import ExitStack
        from unittest.mock import patch
        from msplatform.backends.simion import native_completion
        from msplatform.execution import owner
        from msplatform.execution.context import ExecutionContext
        from msplatform.execution.native_artifact_controls import protect_native_controls
        from msplatform.execution.processes import ProcessExecutionError
        from msplatform.execution.resources import resource_path
        from msplatform.io.manifest_records import file_record
        budget = self.root / "budget.json"
        budget.write_text('{"bytes":100}', encoding="utf-8")
        invalid = self.root / "invalid.exe"
        invalid.write_bytes(b"not a native executable")
        context = ExecutionContext(workspace=self.root / "study", python_executable=Path(sys.executable),
            powershell_executable=Path(shutil.which("pwsh")), tools={},
            host_state_path=self.root / "actual-host.sqlite", policy_path=resource_path("host_resource_policy.json"))
        def action(session):
            session.run_process("worker", executable=invalid, arguments=[], role="GATE", stage="store_fixture", limits=None)
        run, work = self.store.begin_run()
        with self.store.run_writer(run):
            self.store.mark_running(run)
            with ExitStack() as lifetime, self.store.claim_token(self.asset) as (claim, _), self.store.reserve(1000000) as reservation:
                with protect_native_controls(self.store, run_id=run, claim_ids=(claim,), reservation_ids=(reservation,),
                        work_directory=work), owner.managed_native_store(self.store, task_key="failed-task", lifetime=lifetime, account=lambda _path: None), patch.object(
                        owner, "path_capacity", return_value={"legacy_windows_compatible": True}):
                    with self.assertRaises(ProcessExecutionError):
                        owner.run_managed_stage(context, descriptor=dict(project="instrument_assembly", mode="test", software=[]),
                            run_id="20261127_000000__test__python__store-failure", payload={}, committed_new_bytes=100,
                            commitment_inputs=[file_record(budget, "required_evidence")],
                            retention={"policy_version": 1, "class": "solver_review", "reason": "inert test"},
                            expected_operation_ids=["worker"], operation_dependencies={}, action=action,
                            action_record=file_record(Path(__file__), "required_evidence"), completion_api=lambda: native_completion)
                with self.store._db() as db:
                    row = db.execute(
                        "SELECT state,failure,path FROM assets WHERE key LIKE 'failed-task:%'").fetchone()
                self.assertEqual(row[0], "failed")
                self.assertTrue(row[1])
                self.assertTrue((self.store.root / row[2]).is_dir())
                self.assertFalse((context.workspace / "artifacts").exists())
            self.store.finish_run(run, "failed", reason="child launch failed")

    def test_inplace_asset_cannot_close_while_native_binding_is_active(self) -> None:
        run, _work = self.store.begin_run()
        with self.store.run_writer(run):
            self.store.mark_running(run)
            with self.store.inplace_asset("native_stage", "inplace-native") as (asset, path, claim, seal):
                (path / "partial").write_bytes(b"evidence")
                with self.store.reserve(9) as reservation:
                    self.store.bind_native_controls(run, host_state_path=self.host, host_token="fixture-token",
                        host_owner={"pid": 7, "started": "123"}, operation_id="worker", claim_ids=(claim,),
                        reservation_ids=(reservation,))
                    with self.assertRaisesRegex(ValueError, "still protected"):
                        seal()
                    self.store.collect(100)
                    self.assertTrue((path / "partial").is_file())
        with self.assertRaisesRegex(ValueError, "still protected"):
            self.store._recover_inplace_asset(asset, verify=lambda _path: ("failed", "unproved"))
        self.assertEqual((path / "partial").read_bytes(), b"evidence")
        self.assertIsNone(self.store.find_asset("inplace-native"))

    def test_fixture_completion_requires_exact_worker_and_release(self) -> None:
        run, _ = self.store.begin_run()
        with self.store.run_writer(run):
            self.store.mark_running(run)
            with self.store.claim_token(self.asset) as (claim, _), self.store.reserve(9) as reservation:
                binding = self.store.bind_native_controls(run, host_state_path=self.host, host_token="fixture-token",
                    host_owner={"pid": 7, "started": "123"}, operation_id="fly",
                    claim_ids=(claim,), reservation_ids=(reservation,))
                with self.assertRaises(ValueError):
                    self.store.record_native_worker(binding, process_id=12, started_at_utc_ticks=1234)
                _host(self.host, roots=[{"pid": 12, "started": "1234"}])
                self.store.record_native_worker(binding, process_id=12, started_at_utc_ticks=1234)
                completion = {"writers_stopped": True, "operations": [{"operation_id": "fly",
                    "resource_release_id": "release", "observation": {"exit_confirmed": True, "returncode": 0,
                    "process_id": 12, "process_started_at_utc_ticks": 1234}}],
                    "resource_releases": [{"release_id": "release", "completion_receipt": {"host_release": {
                    "inherited": False, "token": "fixture-token", "error": None,
                    "result": {"status": "released", "token": "fixture-token"}}}}]}
                with self.assertRaises(ValueError):
                    self.store.complete_native_controls(binding, completion=completion)
                _host(self.host, present=False)
                for field in ("worker", "token", "unconfirmed", "inherited"):
                    invalid = copy.deepcopy(completion)
                    if field == "worker":
                        invalid["operations"][0]["observation"]["process_id"] = 13
                    elif field == "token":
                        invalid["resource_releases"][0]["completion_receipt"]["host_release"]["token"] = "other"
                    elif field == "unconfirmed":
                        invalid["writers_stopped"] = False
                    else:
                        invalid["resource_releases"][0]["completion_receipt"]["host_release"]["inherited"] = True
                    with self.subTest(field=field), self.assertRaises(ValueError):
                        self.store.complete_native_controls(binding, completion=invalid)
                self.assertEqual(self.store.collect(100)["released_bytes"], 0)
                self.assertTrue(self.store.complete_native_controls(binding, completion=completion))
                self.assertFalse(self.store.complete_native_controls(binding, completion=completion))
                self.assertEqual(self.store.collect(100)["released_bytes"], 0)
                _host(self.host, roots=[{"pid": 12, "started": "1234"}])
                second = self.store.bind_native_controls(run, host_state_path=self.host, host_token="fixture-token",
                    host_owner={"pid": 7, "started": "123"}, operation_id="fly",
                    claim_ids=(claim,), reservation_ids=(reservation,))
                self.store.record_native_worker(second, process_id=12, started_at_utc_ticks=1234)
                _host(self.host, present=False)
                self.assertTrue(self.store.complete_native_controls(second, completion=completion))
                self.assertEqual(self.store.collect(100)["released_bytes"], 0)
            self.assertEqual(self.store.collect(100)["released_bytes"], 5)

    def test_field_member_passes_precise_sources_to_process_owner(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from msplatform.backends.simion.field_worker import run_member
        from msplatform.io.manifest_records import file_record
        inputs, results, logs = (self.root / name for name in ("inputs", "results", "logs"))
        for directory in (inputs, results, logs):
            directory.mkdir()
        raw, parent, lua = (self.root / name for name in ("raw.pa#", "parent.pa", "builder.lua"))
        for path in (raw, parent, lua):
            path.write_bytes(path.name.encode())
        ctx = SimpleNamespace(workspace=self.root, python_executable=Path(sys.executable),
            powershell_executable=Path(shutil.which("pwsh") or sys.executable), host_state_path=self.host,
            policy_path=self.host, execution_root=self.root, tools={})
        session = SimpleNamespace(expected_operation_ids=("member",), input_dir=inputs, result_dir=results,
            log_dir=logs, artifact_run_dir=self.root, run_config=self.root / "run_config.json",
            capacity_session={"lease_id": "lease", "owner": "owner"}, context=ctx,
            declare_file=lambda path, _role: path, canonical_path=lambda path: Path(path), add_input=MagicMock())
        captured = {}
        def run_process(_operation, **kwargs):
            captured.update(kwargs)
            request = file_record(inputs / "member.json", "required_evidence")
            (results / "member.json").write_text(json.dumps({"status": "success", "request": request}), encoding="utf-8")
        session.run_process = run_process
        run_member(session, operation_id="member", limits={}, parameters={"cache_root": self.root / "cache",
            "resources": {"operating_builder": lua}, "raw_geometry_record": file_record(raw, "solver_native_binary"),
            "published_parent": {"record": file_record(parent, "solver_native_binary")}})
        paths = {Path(record["path"]) for record in captured["immutable_input_records"]}
        self.assertEqual(paths, {raw, parent, lua, inputs / "member.json"})

    @unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell required")
    def test_os_launch_failure_reconciles_without_releasing_live_outer_controls(self) -> None:
        from msplatform.execution.context import ExecutionContext
        from msplatform.execution.native_artifact_controls import protect_native_controls, reconcile_native_receipt
        from msplatform.execution.processes import ProcessExecutionError, run_observed_process
        from msplatform.execution.resources import resource_path
        invalid = self.root / "invalid.exe"
        invalid.write_bytes(b"not an executable image")
        context = ExecutionContext(workspace=self.root, python_executable=Path(sys.executable).resolve(),
            powershell_executable=Path(shutil.which("pwsh")).resolve(), tools={},
            host_state_path=self.root / "actual-host.sqlite", policy_path=resource_path("host_resource_policy.json"))
        run, work = self.store.begin_run()
        with self.store.run_writer(run):
            self.store.mark_running(run)
            with self.store.claim_token(self.asset) as (claim, _), self.store.reserve(9) as reservation:
                with protect_native_controls(self.store, run_id=run, claim_ids=(claim,),
                                             reservation_ids=(reservation,), work_directory=work):
                    with self.assertRaises(ProcessExecutionError) as caught:
                        run_observed_process(context, executable=invalid, arguments=[], working_directory=self.root,
                            run_directory=self.root, stdout_path=self.root / "stdout.log", stderr_path=self.root / "stderr.log",
                            usage_path=self.root / "usage.json", role="GATE", stage="native_fixture", run_id="native-fixture",
                            limits=None, operation_id="worker")
                    self.assertTrue(caught.exception.receipt["error"]["message"])
                    self.assertIs(caught.exception.receipt["not_started"], True)
                    receipt, = work.glob("*.receipt.json")
                    durable = json.loads(receipt.read_text(encoding="utf-8"))
                    self.assertEqual(durable["not_started"], {"operation_id": "worker", "reason": "os_start_failed"})
                    self.assertFalse(reconcile_native_receipt(self.store, receipt))
                    self.assertEqual(self.store.collect(100)["released_bytes"], 0)
            self.assertEqual(self.store.collect(100)["released_bytes"], 5)

    @unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell required")
    def test_not_started_recovery_requires_matching_durable_identity(self) -> None:
        from unittest.mock import patch
        from msplatform.execution.context import ExecutionContext
        from msplatform.execution.native_artifact_controls import protect_native_controls
        from msplatform.execution.processes import run_observed_process
        from msplatform.execution.resources import resource_path
        invalid = self.root / "invalid.exe"
        invalid.write_bytes(b"not an executable image")
        context = ExecutionContext(workspace=self.root, python_executable=Path(sys.executable).resolve(),
            powershell_executable=Path(shutil.which("pwsh")).resolve(), tools={},
            host_state_path=self.root / "actual-host.sqlite", policy_path=resource_path("host_resource_policy.json"))
        run, work = self.store.begin_run()
        with self.store.run_writer(run):
            self.store.mark_running(run)
            with self.assertRaisesRegex(RuntimeError, "interrupt reconciliation"):
                with self.store.claim_token(self.asset) as (claim, _), self.store.reserve(9) as reservation:
                    with protect_native_controls(self.store, run_id=run, claim_ids=(claim,),
                            reservation_ids=(reservation,), work_directory=work), patch(
                            "msplatform.execution.native_artifact_controls.reconcile_native_receipt",
                            side_effect=RuntimeError("interrupt reconciliation")):
                        run_observed_process(context, executable=invalid, arguments=[], working_directory=self.root,
                            run_directory=self.root, stdout_path=self.root / "stdout.log", stderr_path=self.root / "stderr.log",
                            usage_path=self.root / "usage.json", role="GATE", stage="native_fixture", run_id="native-fixture",
                            limits=None, operation_id="worker")
        receipt, = work.glob("*.receipt.json")
        original = receipt.read_bytes()
        missing = json.loads(original)
        missing.pop("not_started")
        receipt.write_text(json.dumps(missing), encoding="utf-8")
        self.store.recover_controls()
        self.assertEqual(self.store.collect(100)["released_bytes"], 0)
        broken = json.loads(original)
        broken["not_started"]["operation_id"] = "other"
        receipt.write_text(json.dumps(broken), encoding="utf-8")
        self.store.recover_controls()
        self.assertEqual(self.store.collect(100)["released_bytes"], 0)
        receipt.write_bytes(original)
        self.store.recover_controls()
        self.store.recover_controls()
        self.assertEqual(self.store.collect(100)["released_bytes"], 5)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell required")
    def test_real_single_process_owner_records_protected_completion(self) -> None:
        from msplatform.execution.context import ExecutionContext
        from msplatform.execution.native_artifact_controls import protect_native_controls
        from msplatform.execution.processes import run_observed_process
        from msplatform.execution.resources import resource_path
        context = ExecutionContext(workspace=self.root, python_executable=Path(sys.executable).resolve(),
            powershell_executable=Path(shutil.which("pwsh")).resolve(), tools={},
            host_state_path=self.root / "actual-host.sqlite", policy_path=resource_path("host_resource_policy.json"))
        run, work = self.store.begin_run()
        with self.store.run_writer(run):
            self.store.mark_running(run)
            with self.store.claim_token(self.asset) as (claim, _), self.store.reserve(9) as reservation:
                with protect_native_controls(self.store, run_id=run, claim_ids=(claim,),
                                             reservation_ids=(reservation,), work_directory=work):
                    receipt = run_observed_process(context, executable=Path(sys.executable).resolve(),
                        arguments=["-c", "import time; time.sleep(10)"], working_directory=self.root,
                        run_directory=self.root, stdout_path=self.root / "stdout.log", stderr_path=self.root / "stderr.log",
                        usage_path=self.root / "usage.json", role="GATE", stage="native_fixture", run_id="native-fixture",
                        limits=None, operation_id="worker")
                    self.assertEqual(receipt["observation"]["exit_code"], 0)
                    self.assertEqual(self.store.collect(100)["released_bytes"], 0)
                self.assertEqual(len(list(work.glob("*.receipt.json"))), 1)
                from msplatform.workflows.native_evidence import summarize_native_workers
                evidence = summarize_native_workers(work)
                self.assertEqual(evidence["status"], "available", evidence)
                self.assertEqual(evidence["observed_completed_worker_count"], 1)
                self.assertEqual([row["returncode"] for row in evidence["workers"]], [0])
            self.assertEqual(self.store.collect(100)["released_bytes"], 5)
            _, published = self.store.publish_run(work, run_id=run)
            self.assertEqual(self.store.inspect_run(run), published)
            self.assertEqual(summarize_native_workers(published)["observed_completed_worker_count"], 1)

    @unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell required")
    def test_real_batch_owner_protects_complete_worker_set(self) -> None:
        from unittest.mock import patch
        from msplatform.execution.native_artifact_controls import protect_native_controls
        from msplatform.execution.processes import run_observed_process_group
        from msplatform.execution.resources import resource_path
        from msplatform.io.manifest_records import file_record
        from tests.contracts.test_batch_processes import BatchProcessTests
        fixture = BatchProcessTests()
        context, data, folder, _, plan, specs = fixture.fixture(self.root)
        for spec in specs:
            spec["arguments"][5] = "6"
        run, work = self.store.begin_run()
        with self.store.run_writer(run):
            self.store.mark_running(run)
            with self.store.claim_token(self.asset) as (claim, _), self.store.reserve(9) as reservation:
                with protect_native_controls(self.store, run_id=run, claim_ids=(claim,),
                                             reservation_ids=(reservation,), work_directory=work):
                    with patch("msplatform.execution.processes.resource_path", side_effect=
                               lambda name: folder / name if name == "batch_process_owner.ps1" else resource_path(name)):
                        receipt = run_observed_process_group(context, specifications=specs, dispatch_plan=plan,
                            run_directory=self.root, usage_path=self.root / "group.json", role="GATE",
                            stage="unclassified", run_id="protected-group",
                            immutable_input_records=[file_record(data, "solver_native_binary")])
                    self.assertEqual(set(receipt["observations"]), {"healthy", "failure", "pending"})
                    self.assertEqual(receipt["not_started"], [])
                    from msplatform.workflows.native_evidence import summarize_native_workers
                    evidence = summarize_native_workers(work)
                    self.assertEqual(evidence["status"], "available", evidence)
                    self.assertEqual(evidence["observed_completed_worker_count"], 3)
                    self.assertEqual([row["returncode"] for row in evidence["workers"]], [0, 0, 0])
                    with self.store._db() as db:
                        self.assertEqual(db.execute("SELECT COUNT(*) FROM native_group_workers WHERE worker_pid IS NOT NULL").fetchone()[0], 3)
                    self.assertEqual(self.store.collect(100)["released_bytes"], 0)
            self.assertEqual(self.store.collect(100)["released_bytes"], 5)
            _, published = self.store.publish_run(work, run_id=run)
            self.assertEqual(self.store.inspect_run(run), published)
            self.assertEqual(summarize_native_workers(published)["observed_completed_worker_count"], 3)

    @unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell required")
    def test_single_quick_receipt_recovers_after_controller_death(self) -> None:
        context = get_context("spawn")
        started = context.Event()
        controller = context.Process(target=_single_fault_controller, args=(str(self.root), self.asset, started, "quick"))
        controller.start()
        try:
            self.assertTrue(started.wait(20))
            deadline = time.monotonic() + 45
            registration = None
            while time.monotonic() < deadline:
                paths = list((self.store.root / "work").glob("*/native-control-*.worker.json"))
                if paths:
                    registration = json.loads(paths[0].read_text(encoding="utf-8"))
                    break
                if not controller.is_alive():
                    self.fail("controller exited before quick receipt")
                time.sleep(.05)
            self.assertEqual(registration["registration"], "quick_exit")
            with self.store._db() as db:
                run_id = db.execute("SELECT run_id FROM native_bindings WHERE id=?", (registration["binding_id"],)).fetchone()[0]
            controller.terminate()
            controller.join(20)
            self.assertEqual(self.store.recover_interrupted_runs(), [])
            self.assertEqual(self.store.collect(100)["released_bytes"], 0)
            (self.root / "release-single").touch()
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline and not list((self.store.root / "work").glob("*/native-control-*.receipt.json")):
                time.sleep(.05)
            self.assertEqual(self.store.recover_interrupted_runs(), [run_id], self.store.native_recovery_issues())
            self.assertEqual(self.store.recover_interrupted_runs(), [])
            self.assertEqual(self.store.collect(100)["released_bytes"], 5)
        finally:
            (self.root / "release-single").touch()
            if controller.is_alive():
                controller.terminate()
                controller.join(20)

    @unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell required")
    def test_live_worker_registration_failure_never_becomes_quick_exit(self) -> None:
        context = get_context("spawn")
        started = context.Event()
        controller = context.Process(target=_single_fault_controller, args=(str(self.root), self.asset, started, "live"))
        controller.start()
        try:
            self.assertTrue(started.wait(20))
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline and not (self.root / "single-started").exists():
                time.sleep(.05)
            self.assertTrue((self.root / "single-started").is_file())
            self.assertEqual(self.store.recover_interrupted_runs(), [])
            self.assertEqual(self.store.collect(100)["released_bytes"], 0)
            self.assertEqual(list((self.store.root / "work").glob("*/native-control-*.worker.json")), [])
            (self.root / "release-single").touch()
            controller.join(45)
            self.assertFalse(controller.is_alive())
            self.assertNotEqual(controller.exitcode, 0)
            self.assertEqual(self.store.recover_interrupted_runs(), [])
            self.assertEqual(self.store.collect(100)["released_bytes"], 0)
        finally:
            (self.root / "release-single").touch()
            if controller.is_alive():
                controller.terminate()
                controller.join(20)

    @unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell required")
    def test_single_quick_exit_receipt_covers_success_and_failure(self) -> None:
        from unittest.mock import patch
        from msplatform.execution import native_artifact_controls as controls
        from msplatform.execution.context import ExecutionContext
        from msplatform.execution.native_artifact_controls import protect_native_controls
        from msplatform.execution.processes import ProcessExecutionError, run_observed_process
        from msplatform.execution.resources import resource_path
        for returncode in (0, 7):
            with self.subTest(returncode=returncode):
                context = ExecutionContext(workspace=self.root, python_executable=Path(sys.executable),
                    powershell_executable=Path(shutil.which("pwsh")), tools={},
                    host_state_path=Path(os.environ["MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH"]),
                    policy_path=resource_path("host_resource_policy.json"))
                run, work = self.store.begin_run()
                observed = []
                original = controls.reconcile_native_receipt
                def reconcile(instance, receipt):
                    worker = Path(str(receipt).replace(".receipt.json", ".worker.json"))
                    observed.append(json.loads(worker.read_text(encoding="utf-8")))
                    return original(instance, receipt)
                with self.store.run_writer(run):
                    self.store.mark_running(run)
                    with self.store.claim_token(self.asset) as (claim, _), self.store.reserve(9) as reservation:
                        with protect_native_controls(self.store, run_id=run, claim_ids=(claim,),
                                                     reservation_ids=(reservation,), work_directory=work):
                            with patch.object(controls, "reconcile_native_receipt", side_effect=reconcile):
                                call = dict(context=context, executable=Path(sys.executable),
                                    arguments=["-c", f"import time,sys;time.sleep(.2);sys.exit({returncode})"],
                                    working_directory=self.root, run_directory=self.root,
                                    stdout_path=work/"out", stderr_path=work/"err", usage_path=work/"usage.json",
                                    role="GATE", stage="unclassified", run_id="single-quick", limits=None, operation_id="quick")
                                if returncode:
                                    with self.assertRaises(ProcessExecutionError):
                                        run_observed_process(**call)
                                else:
                                    run_observed_process(**call)
                            self.assertEqual(observed[0]["registration"], "quick_exit")
                            self.assertEqual(self.store.collect(100)["released_bytes"], 0)

    @unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell required")
    def test_group_quick_exit_and_mixed_failure_remain_proven(self) -> None:
        from unittest.mock import patch
        from msplatform.execution import native_artifact_controls as controls
        from msplatform.execution.native_artifact_controls import protect_native_controls
        from msplatform.execution.processes import ProcessExecutionError, run_observed_process_group
        from msplatform.execution.resources import resource_path
        from msplatform.io.manifest_records import file_record
        from tests.contracts.test_batch_processes import BatchProcessTests
        for fault in (None, "exit7"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                context, data, folder, _, plan, specs = BatchProcessTests().fixture(base, fault=fault)
                store = ArtifactStore(base / "store")
                source = store.new_work()
                (source / "data").write_bytes(b"asset")
                asset = store.put_asset("fixture", "quick", source, retention="cache")
                run, work = store.begin_run()
                observed = []
                original = controls.reconcile_native_receipt
                def reconcile(instance, receipt):
                    worker = Path(str(receipt).replace(".receipt.json", ".worker.json"))
                    observed.extend(json.loads(worker.read_text(encoding="utf-8"))["workers"])
                    return original(instance, receipt)
                with store.run_writer(run):
                    store.mark_running(run)
                    with store.claim_token(asset) as (claim, _), store.reserve(9) as reservation:
                        with protect_native_controls(store, run_id=run, claim_ids=(claim,),
                                                     reservation_ids=(reservation,), work_directory=work):
                            with patch("msplatform.execution.processes.resource_path", side_effect=
                                       lambda name: folder / name if name == "batch_process_owner.ps1" else resource_path(name)), \
                                 patch.object(controls, "reconcile_native_receipt", side_effect=reconcile):
                                call = dict(context=context, specifications=specs, dispatch_plan=plan,
                                    run_directory=base, usage_path=base / "group.json", role="GATE", stage="unclassified",
                                    run_id="protected-quick", immutable_input_records=[file_record(data, "solver_native_binary")])
                                if fault:
                                    with self.assertRaises(ProcessExecutionError) as caught:
                                        run_observed_process_group(**call)
                                    self.assertEqual(caught.exception.receipt["observations"]["failure"]["exit_code"], 7)
                                    self.assertIn("pending", caught.exception.receipt["not_started"])
                                else:
                                    run_observed_process_group(**call)
                            self.assertTrue(any(item["registration"] == "quick_exit" for item in observed), observed)
                            with store._db() as db:
                                self.assertEqual(db.execute("SELECT state FROM native_bindings").fetchone()[0], "complete")
                        self.assertEqual(store.collect(100)["released_bytes"], 0)
                self.assertEqual(store.collect(100)["released_bytes"], 5)

    @unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell required")
    def test_group_controller_death_preserves_all_workers_and_automatically_recovers(self) -> None:
        context = get_context("spawn")
        started = context.Event()
        controller = context.Process(target=_real_group_controller, args=(str(self.root), self.asset, started))
        controller.start()
        try:
            self.assertTrue(started.wait(20))
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                with self.store._db() as db:
                    count = db.execute("SELECT COUNT(*) FROM native_group_workers WHERE worker_pid IS NOT NULL").fetchone()[0]
                if count >= 2:
                    break
                if not controller.is_alive():
                    self.fail("controller exited before both workers registered")
                time.sleep(.05)
            self.assertEqual(count, 2)
            with self.store._db() as db:
                run_id = db.execute("SELECT run_id FROM native_bindings WHERE operation_id='group'").fetchone()[0]
            controller.terminate()
            controller.join(20)
            self.assertFalse(controller.is_alive())
            self.assertEqual(self.store.recover_interrupted_runs(), [])
            self.assertEqual(self.store.collect(100)["released_bytes"], 0)
            with self.assertRaises(PermissionError):
                (self.root / "immutable.bin").unlink()
            (self.root / "release-group").touch()
            deadline = time.monotonic() + 60
            receipt = None
            while time.monotonic() < deadline:
                receipts = list((self.store.root / "work").glob("*/native-control-*.receipt.json"))
                if receipts:
                    receipt = receipts[0]
                    break
                time.sleep(.05)
            self.assertIsNotNone(receipt)
            result = self.store.recover_interrupted_runs()
            self.assertEqual(result, [run_id], self.store.native_recovery_issues())
            self.assertEqual(self.store.recover_interrupted_runs(), [])
            self.assertEqual(self.store.collect(100)["released_bytes"], 5)
            (self.root / "immutable.bin").unlink()
        finally:
            (self.root / "release-group").touch()
            if controller.is_alive():
                controller.terminate()
                controller.join(20)

    @unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell required")
    def test_quick_group_registration_survives_controller_death(self) -> None:
        context = get_context("spawn")
        started = context.Event()
        controller = context.Process(target=_real_group_controller, args=(str(self.root), self.asset, started, True))
        controller.start()
        try:
            self.assertTrue(started.wait(20))
            deadline = time.monotonic() + 60
            registration = None
            while time.monotonic() < deadline:
                for path in (self.store.root / "work").glob("*/native-control-*.worker.json"):
                    record = json.loads(path.read_text(encoding="utf-8"))
                    if any(item["registration"] == "quick_exit" for item in record["workers"]):
                        registration = record
                        break
                if registration:
                    break
                if not controller.is_alive():
                    self.fail("controller exited before quick registration")
                time.sleep(.05)
            self.assertIsNotNone(registration)
            with self.store._db() as db:
                run_id = db.execute("SELECT run_id FROM native_bindings WHERE id=?", (registration["binding_id"],)).fetchone()[0]
            controller.terminate()
            controller.join(20)
            self.assertEqual(self.store.recover_interrupted_runs(), [])
            self.assertEqual(self.store.collect(100)["released_bytes"], 0)
            (self.root / "release-group").touch()
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and not list((self.store.root / "work").glob("*/native-control-*.receipt.json")):
                time.sleep(.05)
            self.assertEqual(self.store.recover_interrupted_runs(), [run_id], self.store.native_recovery_issues())
            self.assertEqual(self.store.recover_interrupted_runs(), [])
            self.assertEqual(self.store.collect(100)["released_bytes"], 5)
        finally:
            (self.root / "release-group").touch()
            if controller.is_alive():
                controller.terminate()
                controller.join(20)

    @unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell required")
    def test_real_pressure_relaunch_preserves_every_attempt(self) -> None:
        context = get_context("spawn")
        started = context.Event()
        controller = context.Process(target=_real_group_controller, args=(str(self.root), self.asset, started, False, True))
        controller.start()
        try:
            self.assertTrue(started.wait(20))
            deadline = time.monotonic() + 80
            attempts = []
            while time.monotonic() < deadline:
                with self.store._db() as db:
                    attempts = db.execute("SELECT operation_id,attempt,worker_pid,worker_started FROM native_group_attempts ORDER BY operation_id,attempt").fetchall()
                if (self.root / "pressure-stopped").exists():
                    (self.root / "release-healthy").touch()
                if any(item[1] == 2 for item in attempts):
                    break
                if not controller.is_alive():
                    self.fail("controller exited before pressure relaunch")
                time.sleep(.05)
            self.assertTrue((self.root / "pressure-stopped").exists())
            retry = next(item for item in attempts if item[1] == 2)
            original = next(item for item in attempts if item[0] == retry[0] and item[1] == 1)
            self.assertNotEqual(original[2:], retry[2:])
            self.assertEqual(self.store.collect(100)["released_bytes"], 0)
            with self.assertRaises(PermissionError):
                (self.root / "immutable.bin").unlink()
            (self.root / "release-group").touch()
            controller.join(60)
            self.assertFalse(controller.is_alive())
            self.assertEqual(controller.exitcode, 0)
            with self.store._db() as db:
                self.assertEqual(db.execute("SELECT state FROM native_bindings").fetchone()[0], "complete")
                completion = json.loads(db.execute("SELECT completion FROM native_bindings").fetchone()[0])
                final_count = db.execute("SELECT COUNT(*) FROM native_group_attempts").fetchone()[0]
            self.assertEqual(len(completion["operations"]), final_count)
            self.assertEqual(self.store.collect(100)["released_bytes"], 5)
        finally:
            (self.root / "release-group").touch()
            if controller.is_alive():
                controller.terminate()
                controller.join(20)

    @unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell required")
    def test_pressure_relaunch_controller_dies_before_ack_and_reconciles(self) -> None:
        context = get_context("spawn")
        started, blocked = context.Event(), context.Event()
        controller = context.Process(target=_real_group_controller,
                                     args=(str(self.root), self.asset, started, False, True, blocked))
        controller.start()
        try:
            self.assertTrue(started.wait(20))
            deadline = time.monotonic() + 80
            while time.monotonic() < deadline and not blocked.is_set():
                if (self.root / "pressure-stopped").exists():
                    (self.root / "release-healthy").touch()
                if not controller.is_alive():
                    self.fail("controller exited before retry registration")
                time.sleep(.05)
            self.assertTrue(blocked.is_set())
            worker_path = next((self.store.root / "work").glob("*/native-control-*.worker.json"))
            registration = json.loads(worker_path.read_text(encoding="utf-8"))
            with self.store._db() as db:
                run_id = db.execute("SELECT run_id FROM native_bindings WHERE id=?", (registration["binding_id"],)).fetchone()[0]
            controller.terminate()
            controller.join(20)
            self.assertEqual(self.store.recover_interrupted_runs(), [])
            self.assertEqual(self.store.collect(100)["released_bytes"], 0)
            (self.root / "release-group").touch()
            receipt = Path(str(worker_path).replace(".worker.json", ".receipt.json"))
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and not receipt.exists():
                time.sleep(.05)
            self.assertTrue(receipt.is_file())
            original = worker_path.read_bytes()
            records = json.loads(original)["workers"]
            retry_name = next(item["operation_id"] for item in records if item["attempt"] == 2)
            for ordinal in (1, 2):
                invalid = json.loads(original)
                item = next(item for item in invalid["workers"] if item["operation_id"] == retry_name and item["attempt"] == ordinal)
                item["process_id"] += 1
                worker_path.write_text(json.dumps(invalid), encoding="utf-8")
                self.assertEqual(self.store.recover_interrupted_runs(), [])
                self.assertTrue(self.store.native_recovery_issues())
                self.assertEqual(self.store.collect(100)["released_bytes"], 0)
            worker_path.write_bytes(original)
            self.assertEqual(self.store.recover_interrupted_runs(), [run_id], self.store.native_recovery_issues())
            self.assertEqual(self.store.recover_interrupted_runs(), [])
            self.assertEqual(self.store.collect(100)["released_bytes"], 5)
        finally:
            (self.root / "release-group").touch()
            if controller.is_alive():
                controller.terminate()
                controller.join(20)

    @unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell required")
    def test_pressure_relaunch_controller_dies_after_ack_and_reconciles(self) -> None:
        context = get_context("spawn")
        started = context.Event()
        controller = context.Process(target=_real_group_controller,
                                     args=(str(self.root), self.asset, started, False, True))
        controller.start()
        try:
            self.assertTrue(started.wait(20))
            deadline = time.monotonic() + 80
            acknowledged = None
            while time.monotonic() < deadline:
                if (self.root / "pressure-stopped").exists():
                    (self.root / "release-healthy").touch()
                paths = list((self.store.root / "work").glob("*/native-control-*.worker-ack.json"))
                if paths:
                    ack = json.loads(paths[0].read_text(encoding="utf-8"))
                    if any(item["attempt"] == 2 for item in ack.get("attempts", [])):
                        acknowledged = ack
                        break
                if not controller.is_alive():
                    self.fail("controller exited before retry acknowledgement")
                time.sleep(.05)
            self.assertIsNotNone(acknowledged)
            with self.store._db() as db:
                run_id = db.execute("SELECT run_id FROM native_bindings WHERE id=?", (acknowledged["binding_id"],)).fetchone()[0]
            controller.terminate()
            controller.join(20)
            self.assertEqual(self.store.recover_interrupted_runs(), [])
            self.assertEqual(self.store.collect(100)["released_bytes"], 0)
            (self.root / "release-group").touch()
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and not list((self.store.root / "work").glob("*/native-control-*.receipt.json")):
                time.sleep(.05)
            self.assertEqual(self.store.recover_interrupted_runs(), [run_id], self.store.native_recovery_issues())
            self.assertEqual(self.store.recover_interrupted_runs(), [])
            self.assertEqual(self.store.collect(100)["released_bytes"], 5)
        finally:
            (self.root / "release-group").touch()
            if controller.is_alive():
                controller.terminate()
                controller.join(20)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell required")
    def test_real_worker_failure_releases_binding_only_after_observed_exit(self) -> None:
        from msplatform.execution.context import ExecutionContext
        from msplatform.execution.native_artifact_controls import protect_native_controls
        from msplatform.execution.processes import ProcessExecutionError, run_observed_process
        from msplatform.execution.resources import resource_path
        context = ExecutionContext(workspace=self.root, python_executable=Path(sys.executable).resolve(),
            powershell_executable=Path(shutil.which("pwsh")).resolve(), tools={},
            host_state_path=self.root / "actual-host.sqlite", policy_path=resource_path("host_resource_policy.json"))
        run, work = self.store.begin_run()
        with self.store.run_writer(run):
            self.store.mark_running(run)
            with self.store.claim_token(self.asset) as (claim, _), self.store.reserve(9) as reservation:
                with protect_native_controls(self.store, run_id=run, claim_ids=(claim,),
                                             reservation_ids=(reservation,), work_directory=work):
                    with self.assertRaises(ProcessExecutionError):
                        run_observed_process(context, executable=Path(sys.executable).resolve(),
                            arguments=["-c", "import time,sys; time.sleep(7); sys.exit(3)"], working_directory=self.root,
                            run_directory=self.root, stdout_path=self.root / "stdout.log", stderr_path=self.root / "stderr.log",
                            usage_path=self.root / "usage.json", role="GATE", stage="native_fixture", run_id="native-fixture",
                            limits=None, operation_id="worker")
                    with self.store._db() as db:
                        self.assertEqual(db.execute("SELECT state FROM native_bindings").fetchone()[0], "complete")
                    self.assertEqual(self.store.collect(100)["released_bytes"], 0)
            self.assertEqual(self.store.collect(100)["released_bytes"], 5)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell required")
    def test_real_owner_keeps_protection_after_controller_is_killed(self) -> None:
        context = get_context("spawn")
        started = context.Event()
        controller = context.Process(target=_real_controller, args=(str(self.root), self.asset, started))
        controller.start()
        try:
            self.assertTrue(started.wait(20))
            deadline = time.monotonic() + 45
            acknowledgements = []
            while time.monotonic() < deadline:
                acknowledgements = list((self.store.root / "work").glob("*/native-control-*.worker-ack.json"))
                if acknowledgements and (self.root / "worker-started").exists():
                    break
                if not controller.is_alive():
                    self.fail("controller exited before worker acknowledgement")
                time.sleep(.05)
            self.assertTrue(acknowledgements, "protected worker did not acknowledge")
            binding_id = json.loads(acknowledgements[0].read_text(encoding="utf-8"))["binding_id"]
            with self.store._db() as db:
                run_id = db.execute("SELECT run_id FROM native_bindings WHERE id=?", (binding_id,)).fetchone()[0]
            frozen_input = (acknowledgements[0].parent / "input").read_bytes()
            controller.terminate()
            controller.join(20)
            self.assertFalse(controller.is_alive())
            self.assertEqual(self.store.recover_controls(), [])
            self.assertEqual(self.store.recover_interrupted_runs(), [])
            self.assertEqual(self.store.collect(100)["released_bytes"], 0)
            (self.root / "release-worker").touch()
            receipt_path = Path(str(acknowledgements[0]).replace(".worker-ack.json", ".receipt.json"))
            deadline = time.monotonic() + 45
            while not receipt_path.exists() and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertTrue(receipt_path.is_file(), "original owner did not persist a receipt")
            worker_file = Path(str(receipt_path).replace(".receipt.json", ".worker.json"))
            original = worker_file.read_bytes()
            invalid = json.loads(original)
            invalid["nonce"] = "other"
            worker_file.write_text(json.dumps(invalid), encoding="utf-8")
            self.assertEqual(self.store.recover_interrupted_runs(), [])
            issues = self.store.native_recovery_issues()
            self.assertEqual(len(issues), 1)
            self.assertEqual(issues[0]["binding_id"], binding_id)
            self.assertIn("registration and release receipts differ", issues[0]["reason"].lower())
            self.assertEqual(self.store.collect(100)["released_bytes"], 0)
            worker_file.write_bytes(original)
            self.assertEqual(self.store.recover_interrupted_runs(), [run_id])
            self.assertEqual(self.store.recover_interrupted_runs(), [])
            self.assertEqual(self.store.native_recovery_issues(), [])
            self.assertEqual((acknowledgements[0].parent / "input").read_bytes(), frozen_input)
            self.assertEqual(self.store.collect(100)["released_bytes"], 5)
        finally:
            (self.root / "release-worker").touch()
            if controller.is_alive():
                controller.terminate()
                controller.join(20)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell required")
    def test_real_owner_does_not_launch_when_controller_dies_before_binding(self) -> None:
        context = get_context("spawn")
        started, binding = context.Event(), context.Event()
        controller = context.Process(target=_real_controller, args=(str(self.root), self.asset, started, binding))
        controller.start()
        try:
            self.assertTrue(started.wait(20))
            self.assertTrue(binding.wait(30))
            controller.terminate()
            controller.join(20)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                with closing(sqlite3.connect(self.root / "actual-host.sqlite")) as db:
                    state = json.loads(db.execute("SELECT document FROM state WHERE id=1").fetchone()[0])
                if not state["records"]:
                    break
                time.sleep(.05)
            self.assertFalse(state["records"], "owner did not release its host lease")
            self.assertFalse((self.root / "worker-started").exists())
        finally:
            if controller.is_alive():
                controller.terminate()
                controller.join(20)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell required")
    def test_real_registration_receipt_reconciles_when_controller_dies_before_record(self) -> None:
        context = get_context("spawn")
        started, recording = context.Event(), context.Event()
        controller = context.Process(target=_real_controller, args=(str(self.root), self.asset, started, None, recording))
        controller.start()
        try:
            self.assertTrue(started.wait(20))
            self.assertTrue(recording.wait(35))
            registrations = list((self.store.root / "work").glob("*/native-control-*.worker.json"))
            self.assertEqual(len(registrations), 1)
            controller.terminate()
            controller.join(20)
            self.assertEqual(self.store.recover_controls(), [])
            self.assertEqual(self.store.collect(100)["released_bytes"], 0)
            (self.root / "release-worker").touch()
            receipt = Path(str(registrations[0]).replace(".worker.json", ".receipt.json"))
            deadline = time.monotonic() + 45
            while not receipt.exists() and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertTrue(receipt.is_file())
            binding_id = json.loads(receipt.read_text(encoding="utf-8"))["binding_id"]
            with self.store._db() as db:
                run_id = db.execute("SELECT run_id FROM native_bindings WHERE id=?", (binding_id,)).fetchone()[0]
            self.assertEqual(self.store.recover_interrupted_runs(), [run_id])
            self.assertEqual(self.store.recover_interrupted_runs(), [])
            self.assertEqual(self.store.collect(100)["released_bytes"], 5)
        finally:
            (self.root / "release-worker").touch()
            if controller.is_alive():
                controller.terminate()
                controller.join(20)

    @unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell required")
    def test_process_owner_retains_session_source_guard_after_controller_death(self) -> None:
        context = get_context("spawn")
        started = context.Event()
        controller = context.Process(target=_real_controller, args=(str(self.root), self.asset, started, None, None, True))
        controller.start()
        try:
            self.assertTrue(started.wait(20))
            deadline = time.monotonic() + 45
            acknowledgements = []
            while time.monotonic() < deadline:
                acknowledgements = list((self.store.root / "work").glob("*/native-control-*.worker-ack.json"))
                if acknowledgements and (self.root / "worker-started").exists():
                    break
                if not controller.is_alive():
                    self.fail("controller exited before guarded worker started")
                time.sleep(.05)
            self.assertTrue(acknowledgements)
            source = self.root / "old-owner" / "source.pa"
            controller.terminate()
            controller.join(20)
            with self.assertRaises(PermissionError):
                source.unlink()
            self.assertEqual(source.read_bytes(), b"immutable native field")
            (self.root / "release-worker").touch()
            receipt = Path(str(acknowledgements[0]).replace(".worker-ack.json", ".receipt.json"))
            deadline = time.monotonic() + 45
            while not receipt.exists() and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertTrue(receipt.exists())
            source.unlink()
            self.assertFalse(source.exists())
        finally:
            (self.root / "release-worker").touch()
            if controller.is_alive():
                controller.terminate()
                controller.join(20)


if __name__ == "__main__":
    unittest.main()
