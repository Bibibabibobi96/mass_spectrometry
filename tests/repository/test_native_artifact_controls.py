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
            self.assertEqual(self.store.collect(100)["released_bytes"], 5)

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
