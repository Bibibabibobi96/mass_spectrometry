"""Pure protocol checks and Windows bridge fixtures without a real host ledger."""

import json
import importlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from common import host_resource_python as adapter


def result(value=None, code=0, stderr=b""):
    output = b"" if value is None else (adapter._RESULT + json.dumps(value)).encode()
    return subprocess.CompletedProcess([], code, stdout=output, stderr=stderr)


class PythonHeavyProtocolTests(unittest.TestCase):
    def test_communication_failure_waits_for_owned_root_without_killing_it(self):
        real_popen = subprocess.Popen
        for failure, close_fails in ((RuntimeError("fixture communication failure"), False),
                                     (KeyboardInterrupt("fixture interrupt"), False),
                                     (RuntimeError("fixture communication failure"), True)):
            with self.subTest(error=type(failure).__name__, close_fails=close_fails), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                marker = root / "finished.txt"
                processes = []

                def start_child(*_args, **kwargs):
                    child = real_popen([
                        sys.executable, "-B", "-c",
                        "import pathlib,sys,time; sys.stdin.buffer.read(); "
                        "p=pathlib.Path(sys.argv[1]); "
                        "[(p.write_text(''.join(str(n)+'\\n' for n in range(i+1))),time.sleep(.025)) for i in range(6)]; "
                        "print('NATIVE_FINISHED'); sys.exit(7)", str(marker),
                    ], **kwargs)
                    processes.append(child)
                    communicate = child.communicate
                    first = True

                    def interrupted(*args, **options):
                        nonlocal first
                        if first:
                            first = False
                            raise failure
                        return communicate(*args, **options)

                    child.communicate = interrupted
                    if close_fails:
                        close = child.stdin.close
                        first_close = True

                        def failed_close():
                            nonlocal first_close
                            close()
                            if first_close:
                                first_close = False
                                raise OSError("fixture stdin close failure")

                        child.stdin.close = failed_close
                    return child

                try:
                    with patch.object(adapter.subprocess, "Popen", side_effect=start_child):
                        with self.assertRaises(type(failure)) as raised:
                            adapter._bridge("assert")
                    self.assertIs(raised.exception, failure)
                    self.assertEqual(processes[0].poll(), 7)
                    self.assertEqual(marker.read_text().splitlines(), list(map(str, range(6))))
                    self.assertTrue(failure.bridge_process_exit_confirmed)
                    self.assertEqual(failure.bridge_process_returncode, 7)
                    # Waiting for the bridge root cannot attest to native descendants.
                    self.assertIs(failure.observed_process_exit_confirmed, False)
                    if close_fails:
                        self.assertTrue(any("stdin close failure" in note for note in failure.__notes__))
                    size = marker.stat().st_size
                    time.sleep(.05)
                    self.assertEqual(marker.stat().st_size, size)
                finally:
                    for child in processes:
                        if child.stdin and not child.stdin.closed:
                            child.stdin.close()
                        child.wait()

    def test_bridge_preserves_cwd_without_an_extra_solver_deadline(self):
        for operation in ("enter", "call", "assert"):
            with self.subTest(operation=operation), \
                    patch.object(adapter.os, "name", "nt"), \
                    patch.object(adapter.sys, "version_info", (3, 11)), \
                    patch.object(adapter.subprocess, "Popen") as start:
                start.return_value.communicate.return_value = (b"", b"")
                start.return_value.returncode = 0
                adapter._bridge(operation)
                self.assertEqual(start.call_args.kwargs["cwd"], Path.cwd())
                self.assertIsNone(start.return_value.communicate.call_args.kwargs["timeout"])
                self.assertEqual(start.call_args.kwargs["stdout"], subprocess.PIPE if operation == "assert" else None)

    def test_secondary_wait_failure_is_explicitly_unconfirmed_without_killing(self):
        for secondary in (KeyboardInterrupt("second interrupt"), OSError("wait unavailable")):
            with self.subTest(error=type(secondary).__name__), tempfile.TemporaryDirectory() as directory:
                marker = Path(directory) / "finished"
                child = subprocess.Popen([
                    sys.executable, "-B", "-c",
                    "import pathlib,sys,time; sys.stdin.buffer.read(); time.sleep(.08); "
                    "pathlib.Path(sys.argv[1]).write_text('finished')", str(marker),
                ], cwd=directory, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                original = RuntimeError("original communication error")
                try:
                    with patch.object(child, "wait", side_effect=secondary):
                        adapter._finish_bridge_after_failure(child, original)
                    self.assertIs(original.bridge_process_exit_confirmed, False)
                    self.assertIs(original.observed_process_exit_confirmed, False)
                    self.assertTrue(any("BRIDGE_ROOT_EXIT_UNCONFIRMED" in note for note in original.__notes__))
                finally:
                    child.wait()
                    for stream in (child.stdin, child.stdout, child.stderr):
                        stream.close()
                self.assertEqual(marker.read_text(), "finished")

    def test_bad_missing_or_success_with_nonzero_result_fails_closed(self):
        success = {"schema_version": 1, "role": adapter._CALL_RESULT_ROLE,
                   "status": "success", "value": adapter._encode_value({"answer": 1})}
        malformed_error = {"schema_version": 1, "role": adapter._CALL_RESULT_ROLE, "status": "failed",
                           "error": {"type": "ValueError", "module": "builtins", "message": "broken",
                                     "notes": [], "observed_process_exit_confirmed": "true"}}
        incomplete_exit = {**malformed_error, "error": {**malformed_error["error"],
                                                       "observed_process_exit_confirmed": True}}
        for payload, code in ((None, 1), (None, 0), (b"{", 1), (b"{}", 0),
                              (json.dumps(success).encode(), 0), (json.dumps(success).encode(), 1), (json.dumps(malformed_error).encode(), 1),
                              (json.dumps(incomplete_exit).encode(), 1)):
            with self.subTest(payload=payload, code=code):
                paths = []

                def bridge(_operation, **request):
                    path = Path(request["result_path"])
                    paths.append(path)
                    if payload is not None:
                        path.write_bytes(payload)
                    return result(code=code)

                with patch.dict(os.environ, {}, clear=True), patch.object(adapter, "_bridge", side_effect=bridge):
                    with self.assertRaises(RuntimeError) as raised:
                        adapter.run_heavy_function("fixture", "pool")
                self.assertIs(raised.exception.observed_process_exit_confirmed, False)
                self.assertIsNone(raised.exception.observed_process_returncode)
                self.assertIs(raised.exception.host_release_confirmed, False)
                self.assertFalse(paths[0].parent.exists())

    def test_host_release_requires_real_owned_matching_transaction(self):
        released = {"inherited": False, "token": "same", "result": {"status": "released", "token": "same"}, "error": None}
        cases = [None, {**released, "inherited": True}, {**released, "inherited": "false"},
                 {**released, "result": {"status": "released", "token": "other"}},
                 {**released, "result": {"status": "released", "token": "same", "live_process_ids": [7]}},
                 {**released, "result": {"status": "acquired", "token": "same", "reason": "owner_released_descendants_still_live"}},
                 {**released, "result": None, "error": "release failed"}]
        for release in cases:
            with self.subTest(release=release), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "result.json"
                adapter._write_call_result(path, status="success", value=1, host_release=release)
                completion = {}
                with self.assertRaises(RuntimeError) as raised:
                    adapter._read_call_result(path, result(), "fixture.pool", completion)
                self.assertFalse(completion["host_release_confirmed"])
                self.assertFalse(raised.exception.host_release_confirmed)
        with self.assertRaisesRegex(ValueError, "empty per-call"):
            adapter.run_heavy_function("fixture", "pool", completion_receipt={"old": "proof"})

    def test_parent_error_retains_later_release_without_overriding_native_unknown(self):
        original = KeyboardInterrupt("parent communication interrupted")
        original.bridge_process_exit_confirmed = True
        original.bridge_process_returncode = 0
        original.observed_process_exit_confirmed = False
        original.observed_process_returncode = None
        release = {"inherited": False, "token": "owned", "result": {"status": "released", "token": "owned"}, "error": None}

        def bridge(_operation, **request):
            adapter._write_call_result(Path(request["result_path"]), status="success", value=1, host_release=release)
            raise original

        proof = {}
        with patch.dict(os.environ, {}, clear=True), patch.object(adapter, "_bridge", side_effect=bridge):
            with self.assertRaises(KeyboardInterrupt) as raised:
                adapter.run_heavy_function("fixture", "pool", completion_receipt=proof)
        self.assertIs(raised.exception, original)
        self.assertTrue(proof["host_release_confirmed"])
        self.assertEqual(original.host_release, release)
        self.assertFalse(original.observed_process_exit_confirmed)

    def test_unconfirmed_bridge_retains_its_existing_result_directory(self):
        paths = []
        failure = KeyboardInterrupt("owner wait was interrupted")
        failure.bridge_process_exit_confirmed = False
        failure.observed_process_exit_confirmed = False

        def bridge(_operation, **request):
            paths.append(Path(request["result_path"]))
            raise failure

        try:
            with patch.dict(os.environ, {}, clear=True), patch.object(adapter, "_bridge", side_effect=bridge):
                with self.assertRaises(KeyboardInterrupt) as raised:
                    adapter.run_heavy_function("fixture", "pool")
            self.assertIs(raised.exception, failure)
            self.assertTrue(paths[0].parent.is_dir())
            self.assertTrue(any(str(paths[0].parent) in note and "BRIDGE_RESULT_RETAINED" in note
                                for note in failure.__notes__))
        finally:
            for path in paths:
                shutil.rmtree(path.parent)

    def test_result_cleanup_failure_keeps_worker_error_and_explicit_exit_fact(self):
        paths = []
        remove = shutil.rmtree

        def bridge(_operation, **request):
            path = Path(request["result_path"])
            paths.append(path)
            error = ValueError("original worker failure")
            error.observed_process_exit_confirmed = True
            error.observed_process_returncode = 9
            error.add_note("worker note")
            adapter._write_call_result(path, status="failed", error=adapter._worker_error(error))
            return result(code=1)

        try:
            with patch.dict(os.environ, {}, clear=True), patch.object(adapter, "_bridge", side_effect=bridge), \
                    patch.object(adapter.shutil, "rmtree", side_effect=OSError("cleanup unavailable")):
                with self.assertRaisesRegex(RuntimeError, "original worker failure") as raised:
                    adapter.run_heavy_function("fixture", "pool")
            self.assertEqual(raised.exception.worker_error_type, "ValueError")
            self.assertIs(raised.exception.observed_process_exit_confirmed, True)
            self.assertEqual(raised.exception.observed_process_returncode, 9)
            self.assertIn("worker note", raised.exception.__notes__)
            self.assertTrue(any("cleanup unavailable" in note for note in raised.exception.__notes__))
        finally:
            for path in paths:
                remove(path.parent)

    def test_error_receipt_publication_failure_keeps_the_original_exception(self):
        request = {"module": "fixture", "function": "pool", "args": adapter._encode_value(()),
                   "kwargs": adapter._encode_value({}), "result_path": "unused-result.json"}
        failure = KeyboardInterrupt("original worker interrupt")

        def fail():
            raise failure

        with patch.object(sys, "stdin", io.StringIO(json.dumps(request))), \
                patch.object(adapter, "_bridge", return_value=result({"heavy": True})), \
                patch.object(adapter.importlib, "import_module", return_value=SimpleNamespace(pool=fail)), \
                patch.object(adapter, "_write_call_result", side_effect=OSError("publication unavailable")):
            with self.assertRaises(KeyboardInterrupt) as raised:
                adapter._execute_call()
        self.assertIs(raised.exception, failure)
        self.assertTrue(any("publication unavailable" in note for note in failure.__notes__))

    def test_stage_codec_preserves_paths_tuples_and_dictionary_keys(self):
        value = {"kind": "path", "value": "not a Path", "items": (Path("中文 $literal"), [1, None])}
        self.assertEqual(adapter._decode_value(adapter._encode_value(value)), value)
        with self.assertRaises(TypeError):
            adapter._encode_value(object())

    def test_inherited_stage_call_refuses_light_before_calling_function(self):
        with patch.dict(os.environ, {adapter._TOKEN: "light"}, clear=True), \
                patch.object(adapter, "_bridge", return_value=result(code=1, stderr=b"not heavy")), \
                patch.object(adapter.importlib, "import_module") as imported:
            with self.assertRaisesRegex(RuntimeError, "not heavy"):
                adapter.run_heavy_function("fixture", "pool", Path("literal"))
            imported.assert_not_called()

    def test_owned_entry_verifies_instead_of_trusting_token(self):
        with patch.dict(os.environ, {adapter._TOKEN: "claimed"}, clear=True), \
                patch.object(adapter, "_bridge", return_value=result({"heavy": True})) as bridge:
            adapter.ensure_heavy_entry("project.work", ["literal"])
            bridge.assert_called_once_with("assert")

    def test_invalid_or_light_token_fails_closed(self):
        with patch.dict(os.environ, {adapter._TOKEN: "light"}, clear=True), \
                patch.object(adapter, "_bridge", return_value=result(code=1, stderr=b"not heavy")):
            with self.assertRaisesRegex(RuntimeError, "not heavy"):
                adapter.ensure_heavy_entry("project.work")

    def test_unowned_entry_preserves_module_arguments_and_exit_code(self):
        arguments = ["space argument", "中文", "$(literal)", 'a"b']
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(adapter, "_bridge", return_value=result(code=17)) as bridge:
            with self.assertRaises(SystemExit) as raised:
                adapter.ensure_heavy_entry("project.work", arguments)
            self.assertEqual(raised.exception.code, 17)
            bridge.assert_called_once_with("enter", module="project.work", argv=arguments, role="GATE", stage="theory_compute")

    def test_explicit_solver_stage_uses_same_bridge(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(adapter, "_bridge", return_value=result()) as bridge:
            with self.assertRaises(SystemExit):
                adapter.ensure_heavy_entry("project.flight", [], role="SIMION", stage="flight")
            bridge.assert_called_once_with("enter", module="project.flight", argv=[], role="SIMION", stage="flight")

    def test_missing_token_during_reentry_never_recurses(self):
        with patch.dict(os.environ, {adapter._REENTRY: "1"}, clear=True), \
                patch.object(adapter, "_bridge") as bridge:
            with self.assertRaisesRegex(RuntimeError, "lost its heavy token"):
                adapter.ensure_heavy_entry("project.work")
            bridge.assert_not_called()

    def test_rejects_non_module_commands(self):
        for module in ("__main__", "-c", "pkg;command", "path/file.py"):
            with self.subTest(module=module), self.assertRaises(ValueError):
                adapter.ensure_heavy_entry(module, [])

    def test_assert_requires_unique_machine_record(self):
        for output in (b"", b"HOST_RESOURCE_PYTHON_RESULT={}\nHOST_RESOURCE_PYTHON_RESULT={}"):
            with self.subTest(output=output), self.assertRaisesRegex(RuntimeError, "unique result"):
                adapter._read_result(subprocess.CompletedProcess([], 0, stdout=output))

    def test_runtime_version_is_explicit(self):
        with patch.object(sys, "version_info", (3, 12)), self.assertRaisesRegex(RuntimeError, "3.11"):
            adapter._bridge("assert")


_FACADE = r'''
function Record-Event($text) { [IO.File]::AppendAllText($env:FIXTURE_EVENTS, $text + "`n") }
function Get-HostResourceBudget { param($Role,$Stage) Record-Event "budget:$Role/$Stage"; return @{heavy_stage=(-not $env:FIXTURE_UNLISTED)} }
function Enter-HostResourceStage {
    param($Role,$Stage,$Budget)
    Record-Event "enter:$Role/$Stage"
    $env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN=if($Budget.heavy_stage){'fixture-heavy'}else{'fixture-light'}
    return @{token=$env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN;inherited=$false}
}
function Assert-HostResourceHeavyStage {
    param($Lease)
    Record-Event 'assert'
    if ($env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN -ne 'fixture-heavy') { throw 'fixture token is not heavy' }
}
function Exit-HostResourceStage {
    param($Lease,[switch]$PassThru)
    Record-Event 'release'
    if ($env:FIXTURE_RELEASE_FAIL) { throw 'fixture release failure' }
    if ($PassThru) {
        if ($env:FIXTURE_RELEASE_RETAIN) {
            return @{token=$Lease.token;status='acquired';reason='owner_released_descendants_still_live';live_process_ids=@(999)}
        }
        return @{token=$(if($env:FIXTURE_RELEASE_BAD_TOKEN){'different'}else{$Lease.token});status='released'}
    }
}
'''

_TASK = '''
import json, os, sys
from pathlib import Path
from common.host_resource_python import ensure_heavy_entry
ensure_heavy_entry("fixture_task")
assert Path.cwd() == Path(os.environ["FIXTURE_EVENTS"]).parent
with Path(os.environ["FIXTURE_EVENTS"]).open("a", encoding="utf-8") as stream:
    stream.write("task\\n")
print("TASK_ARGV=" + json.dumps(sys.argv[1:], ensure_ascii=False))
if os.environ.get("FIXTURE_EXCEPTION"):
    raise ValueError("fixture task error")
raise SystemExit(int(os.environ.get("FIXTURE_EXIT", "0")))
'''

_CALL_TASK = '''
import json, os, sys, tempfile
from pathlib import Path
from common.host_resource_python import run_heavy_function
def pool(path, *, payload):
    assert isinstance(path, Path)
    print("POOL_PROGRESS", flush=True)
    print("POOL_STDERR", file=sys.stderr, flush=True)
    with Path(os.environ["FIXTURE_EVENTS"]).open("a") as stream:
        stream.write("pool\\n")
    if os.environ.get("FIXTURE_EXCEPTION"):
        raise ValueError("fixture pool failure")
    return {"path": path, "payload": payload}
if __name__ == "__main__":
    value=run_heavy_function("fixture_task", "pool", Path("中文 $(literal)"), payload={"kind":"path"})
    assert value == {"path": Path("中文 $(literal)"), "payload": {"kind":"path"}}
    assert not list(Path(tempfile.gettempdir()).glob("host-resource-python-call-*"))
    print("POOL_RESULT=PASS", flush=True)
'''

_CALL_ERROR_TASK = '''
import json, os
from pathlib import Path
from common.host_resource_python import run_heavy_function
def pool():
    with Path(os.environ["FIXTURE_EVENTS"]).open("a") as stream:
        stream.write("pool\\n")
    kind = os.environ["FIXTURE_ERROR_KIND"]
    error = {"value": ValueError("worker failure"), "keyboard": KeyboardInterrupt("worker interrupted"),
             "system_exit": SystemExit(0)}[kind]
    error.observed_process_exit_confirmed = False
    error.observed_process_returncode = None
    error.add_note("native writer exit remains unknown")
    raise error
if __name__ == "__main__":
    try:
        run_heavy_function("fixture_task", "pool")
    except BaseException as error:
        print("BRIDGE_FAILURE=" + json.dumps({
            "type": type(error).__name__, "worker_type": getattr(error, "worker_error_type", None),
            "worker_module": getattr(error, "worker_error_module", None),
            "worker_message": getattr(error, "worker_error_message", None),
            "exit_confirmed": getattr(error, "observed_process_exit_confirmed", None),
            "returncode": getattr(error, "observed_process_returncode", "missing"),
            "notes": getattr(error, "__notes__", []),
            "host_release": getattr(error, "host_release", None),
            "host_release_confirmed": getattr(error, "host_release_confirmed", False),
        }), flush=True)
        raise
'''

_CALL_COMPLETION_TASK = '''
import json, os, subprocess, sys
from pathlib import Path
from common.host_resource_python import run_heavy_function

def pool():
    marker = Path(os.environ["FIXTURE_EVENTS"]).with_name("native-writes.txt")
    child = subprocess.Popen([sys.executable, "-B", "-c",
        "import pathlib,sys,time; p=pathlib.Path(sys.argv[1]); "
        "[(p.write_text(str(i)),time.sleep(.025)) for i in range(4)]", str(marker)])
    assert child.wait() == 0 and marker.read_text() == "3"
    return (Path("中文"), 7)

if __name__ == "__main__":
    completion = {}
    try:
        value = run_heavy_function("fixture_task", "pool", completion_receipt=completion)
        assert value == (Path("中文"), 7)
    finally:
        print("COMPLETION=" + json.dumps(completion), flush=True)
'''


class HeavyConsumerEntryTests(unittest.TestCase):
    def test_theory_clis_check_before_reading_inputs_or_computing(self):
        consumers = {
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0_hardware_candidate":
                ["--contract", "missing.json", "--output", "unused.json"],
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0_l1_hardware_candidate":
                ["--l0-receipt", "missing.json", "--contract", "missing.json", "--output", "unused.json"],
            "projects.rf_multipole_ion_optics.runtime.run_ideal_transport": [
                "--project-root", "missing", "--design-profile-id", "hexapole_no_acceleration_full_length"
            ],
            "projects.single_reflection_oa_tof_mass_analyzer.workflows.ideal_source_comparison.run_comparison":
                ["--seed", "1", "--config", "missing.json"],
        }
        for name, arguments in consumers.items():
            with self.subTest(module=name):
                module = importlib.import_module(name)
                with patch.object(sys, "argv", [name, *arguments]), \
                        patch.object(adapter, "ensure_heavy_entry", side_effect=SystemExit(77)) as enter:
                    with self.assertRaises(SystemExit) as raised:
                        module.main()
                    self.assertEqual(raised.exception.code, 77)
                    self.assertEqual(enter.call_args.args[0], name)

    def test_oa_plan_does_not_request_heavy_permission(self):
        module = importlib.import_module(
            "projects.single_reflection_oa_tof_mass_analyzer.workflows.ideal_source_comparison.run_comparison"
        )
        with patch.object(module, "load_json", return_value={}), \
                patch.object(module, "build_case_plan", return_value=[]), \
                patch.object(adapter, "ensure_heavy_entry") as enter, patch("builtins.print"):
            self.assertEqual(module.main(["--plan", "--seed", "1"]), 0)
            enter.assert_not_called()

    def test_execution_policy_provenance_does_not_change_oa_numerical_identity(self):
        module = importlib.import_module(
            "projects.single_reflection_oa_tof_mass_analyzer.workflows.ideal_source_comparison.run_comparison"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "common").mkdir()
            for name in ("host_resource_python.py", "host_resource_python.ps1", "host_execution_lease.ps1",
                         "host_resource_scheduler.py", "host_resource_policy.json"):
                (root / "common" / name).write_text("fixture-original", encoding="utf-8")
            config = root / "config.json"
            config.write_text('{"scope":"fixture"}', encoding="utf-8")
            with patch.object(module, "REPO_ROOT", root), \
                    patch.object(module, "_inputs", return_value={"experiment": config}), \
                    patch.object(module, "_command", return_value="fixture"):
                first, identity = module._prepare_run(
                    config, seed=1, run_id="20260914_180000__analysis__python__host-entry-a",
                    resume_from=None, artifact_root=root / "artifacts",
                )
                (root / "common/host_resource_policy.json").write_text("fixture-updated", encoding="utf-8")
                second, resumed_identity = module._prepare_run(
                    config, seed=1, run_id="20260914_180001__analysis__python__host-entry-b",
                    resume_from=first, artifact_root=root / "artifacts",
                )
                self.assertEqual(identity, resumed_identity)
                first_config = json.loads((first / "run_config.json").read_text(encoding="utf-8"))
                second_config = json.loads((second / "run_config.json").read_text(encoding="utf-8"))
                self.assertNotEqual(first_config["execution_source_sha256"], second_config["execution_source_sha256"])


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell 7 bridge fixture")
class WindowsPythonHeavyBridgeTests(unittest.TestCase):
    def test_real_bridge_preserves_return_value_and_exposes_owned_release_only(self):
        for environment, confirmed, code in (({}, True, 0), ({"FIXTURE_RELEASE_RETAIN": "1"}, False, 1),
                                             ({"FIXTURE_RELEASE_FAIL": "1"}, False, 1),
                                             ({"FIXTURE_RELEASE_BAD_TOKEN": "1"}, False, 1),
                                             ({"MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN": "fixture-heavy"}, False, 0)):
            with self.subTest(environment=environment):
                completed, events, _ = self.run_fixture(task=_CALL_COMPLETION_TASK, **environment)
                self.assertEqual(completed.returncode, code, completed.stderr)
                line = next(line for line in completed.stdout.decode().splitlines() if line.startswith("COMPLETION="))
                proof = json.loads(line.split("=", 1)[1])
                self.assertIs(proof["host_release_confirmed"], confirmed)
                if confirmed:
                    self.assertTrue(proof["bridge_process_exit_confirmed"])
                    self.assertEqual(proof["host_release"]["result"], {"status": "released", "token": "fixture-heavy"})
                if "MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN" in environment:
                    self.assertTrue(proof["host_release"]["inherited"])
                    self.assertIsNone(proof["host_release"]["result"])
                    self.assertNotIn("release", events)

    def test_release_failure_does_not_replace_worker_error_or_native_unknown(self):
        completed, _, _ = self.run_fixture(task=_CALL_ERROR_TASK, FIXTURE_ERROR_KIND="value", FIXTURE_RELEASE_FAIL="1")
        self.assertNotEqual(completed.returncode, 0)
        line = next(line for line in completed.stdout.decode().splitlines() if line.startswith("BRIDGE_FAILURE="))
        failure = json.loads(line.split("=", 1)[1])
        self.assertEqual(failure["worker_type"], "ValueError")
        self.assertEqual(failure["worker_message"], "worker failure")
        self.assertFalse(failure["exit_confirmed"])
        self.assertFalse(failure["host_release_confirmed"])
        self.assertEqual(failure["host_release"]["error"], "fixture release failure")
        self.assertTrue(any("fixture release failure" in note for note in failure["notes"]))

    def test_exit_pass_thru_returns_actual_record_and_inherited_returns_nothing(self):
        import base64
        source = str(Path(adapter.__file__).with_name("host_execution_lease.ps1")).replace("'", "''")
        script = """
$ErrorActionPreference='Stop'
. '__SOURCE__'
$script:returned=[pscustomobject]@{status='acquired';token='fixture';reason='owner_released_descendants_still_live'}
function Invoke-HostResourceTransaction { param($StatePath,$Request) return $script:returned }
$lease=[pscustomobject]@{token='fixture';role='GATE';stage='fixture';inherited=$false;state_path='unused';
  completed_work_processes=@();environment_set=$true;previous_environment=@{HOST_PASS_THRU_TEST='restored'}}
$env:HOST_PASS_THRU_TEST='changed'
$record=Exit-HostResourceStage -Lease $lease -PassThru
if(-not[Object]::ReferenceEquals($record,$script:returned)){throw 'Receipt was reconstructed.'}
if($env:HOST_PASS_THRU_TEST-ne'restored'){throw 'Environment not restored.'}
if($null-ne(Exit-HostResourceStage -Lease $lease)){throw 'Default call gained pipeline output.'}
$script:returned=[pscustomobject]@{status='released';token='fixture'}
if((Exit-HostResourceStage -Lease $lease -PassThru).status-ne'released'){throw 'Released result lost.'}
$lease.inherited=$true
if($null-ne(Exit-HostResourceStage -Lease $lease -PassThru)){throw 'Inherited caller invented release.'}
'PASS_THRU=PASS'
""".replace("__SOURCE__", source)
        encoded = base64.b64encode(script.encode("utf-16-le")).decode()
        completed = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                                   cwd=Path(adapter.__file__).resolve().parent.parent, capture_output=True, timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(b"PASS_THRU=PASS", completed.stdout)

    def test_worker_exception_exit_unknown_survives_the_real_bridge(self):
        for kind, expected in (("value", "ValueError"), ("keyboard", "KeyboardInterrupt"),
                               ("system_exit", "SystemExit")):
            with self.subTest(kind=kind):
                completed, events, _ = self.run_fixture(task=_CALL_ERROR_TASK, FIXTURE_ERROR_KIND=kind)
                self.assertNotEqual(completed.returncode, 0)
                line = next(line for line in completed.stdout.decode().splitlines()
                            if line.startswith("BRIDGE_FAILURE="))
                failure = json.loads(line.split("=", 1)[1])
                self.assertEqual(failure["type"], "RuntimeError")
                self.assertEqual(failure["worker_type"], expected)
                self.assertEqual(failure["worker_module"], "builtins")
                self.assertIs(failure["exit_confirmed"], False)
                self.assertIsNone(failure["returncode"])
                self.assertIn("native writer exit remains unknown", failure["notes"])
                self.assertTrue(failure["host_release_confirmed"])
                self.assertFalse(failure["exit_confirmed"])
                self.assertEqual(events[-1], "release")

    def run_fixture(self, *, flags=0, task=_TASK, real_scheduler=False, **extra):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            common = root / "common"
            common.mkdir()
            (common / "__init__.py").write_text("", encoding="utf-8")
            for suffix in (".py", ".ps1"):
                shutil.copyfile(Path(adapter.__file__).with_suffix(suffix), common / ("host_resource_python" + suffix))
            facade = _FACADE
            if real_scheduler:
                for name in ("host_resource_scheduler.py", "host_resource_policy.json"):
                    shutil.copyfile(Path(adapter.__file__).with_name(name), common / name)
                source = str(Path(adapter.__file__).with_name("host_execution_lease.ps1")).replace("'", "''")
                # Retain actual process identities and the actual scheduler;
                # only fixture host pressure is fixed, in its own empty ledger.
                facade = ". '" + source + "'\n" + r'''
$script:fixtureSnapshot=${function:Get-HostResourceSnapshot}
function Get-HostResourceSnapshot {
    $value=& $script:fixtureSnapshot
    $value.cpu_percent=0; $value.available_memory_bytes=64GB; $value.total_memory_bytes=64GB; $value.io_pressure=$false
    return $value
}
'''
            (common / "host_execution_lease.ps1").write_text(facade, encoding="utf-8")
            (root / "fixture_task.py").write_text(task, encoding="utf-8")
            events = root / "events.txt"
            environment = os.environ.copy()
            for key in list(environment):
                if key.startswith("MASS_SPECTROMETRY_") or key.startswith("FIXTURE_"):
                    del environment[key]
            environment.update(PYTHONPATH=str(root), PYTHONIOENCODING="utf-8", FIXTURE_EVENTS=str(events), TMP=str(root), TEMP=str(root))
            environment.update(extra)
            if real_scheduler:
                environment["MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH"] = str(root / "state.sqlite3")
            arguments = ["space argument", "中文", "$(literal)", 'a"b', ""]
            completed = subprocess.run(
                [sys.executable, "-B", "-m", "fixture_task", *arguments], cwd=root, env=environment,
                capture_output=True, creationflags=flags, timeout=45,
            )
            recorded = events.read_text(encoding="utf-8").splitlines() if events.exists() else []
            self.assertEqual(list(root.glob("host-resource-python-call-*")), [])
            return completed, recorded, arguments

    def test_real_host_release_after_a_short_native_child_uses_private_ledger(self):
        completed, _, _ = self.run_fixture(task=_CALL_COMPLETION_TASK, real_scheduler=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        line = next(line for line in completed.stdout.decode().splitlines() if line.startswith("COMPLETION="))
        proof = json.loads(line.split("=", 1)[1])
        self.assertTrue(proof["host_release_confirmed"])
        release = proof["host_release"]
        self.assertFalse(release["inherited"])
        self.assertEqual(release["result"], {"status": "released", "token": release["token"]})

    def test_function_stage_returns_paths_streams_progress_and_releases(self):
        completed, events, _ = self.run_fixture(task=_CALL_TASK)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(b"POOL_PROGRESS", completed.stdout)
        self.assertIn(b"POOL_STDERR", completed.stderr)
        self.assertIn(b"POOL_RESULT=PASS", completed.stdout)
        self.assertEqual(events.count("enter:SIMION/flight"), 1)
        self.assertEqual(events.count("pool"), 1)
        self.assertEqual(events[-1], "release")

    def test_function_stage_failure_keeps_traceback_and_releases(self):
        completed, events, _ = self.run_fixture(task=_CALL_TASK, FIXTURE_EXCEPTION="1")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(b"fixture pool failure", completed.stderr)
        self.assertNotIn(b"POOL_RESULT=PASS", completed.stdout)
        self.assertEqual(events[-1], "release")

    def test_function_stage_inherits_heavy_without_second_grant(self):
        completed, events, _ = self.run_fixture(task=_CALL_TASK, MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN="fixture-heavy")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(events, ["assert", "pool"])

    def test_function_stage_rejects_light_and_release_failure(self):
        completed, events, _ = self.run_fixture(task=_CALL_TASK, MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN="fixture-light")
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(events, ["assert"])
        completed, events, _ = self.run_fixture(task=_CALL_TASK, FIXTURE_RELEASE_FAIL="1")
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(events[-1], "release")
        self.assertNotIn(b"POOL_RESULT=PASS", completed.stdout)

    def test_normal_and_hidden_reentry_preserve_argv_and_release(self):
        for flags in (0, subprocess.CREATE_NO_WINDOW):
            with self.subTest(flags=flags):
                completed, events, arguments = self.run_fixture(flags=flags)
                self.assertEqual(completed.returncode, 0, repr(completed.stderr))
                records = completed.stdout.decode("utf-8").splitlines()
                self.assertEqual(json.loads(next(line[10:] for line in records if line.startswith("TASK_ARGV="))), arguments)
                self.assertEqual(events.count("enter:GATE/theory_compute"), 1)
                self.assertEqual(events.count("task"), 1)
                self.assertEqual(events[-1], "release")
                self.assertIn("budget:GATE/theory_compute", events)
                self.assertLess(events.index("assert"), events.index("task"))

    def test_inherited_heavy_only_asserts_without_releasing_parent(self):
        completed, events, _ = self.run_fixture(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN="fixture-heavy")
        self.assertEqual(completed.returncode, 0, repr(completed.stderr))
        self.assertEqual(events, ["assert", "task"])

    def test_inherited_invalid_token_cannot_start_task(self):
        completed, events, _ = self.run_fixture(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN="fixture-light")
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(events, ["assert"])

    def test_task_failure_exit_and_exception_release_owned_grant(self):
        for environment, code in (({"FIXTURE_EXIT": "19"}, 19), ({"FIXTURE_EXCEPTION": "1"}, 1)):
            with self.subTest(environment=environment):
                completed, events, _ = self.run_fixture(**environment)
                self.assertEqual(completed.returncode, code, repr(completed.stderr))
                self.assertEqual(events[-1], "release")

    def test_unlisted_stage_fails_assert_and_releases_without_task(self):
        completed, events, _ = self.run_fixture(FIXTURE_UNLISTED="1")
        self.assertEqual(completed.returncode, 1)
        self.assertNotIn("task", events)
        self.assertEqual(events[-1], "release")

    def test_release_failure_cannot_report_success(self):
        for environment, message in (({"FIXTURE_RELEASE_FAIL": "1"}, b"HOST_RESOURCE_PYTHON_RELEASE_ERROR="),
                                     ({"FIXTURE_RELEASE_RETAIN": "1"}, b"HOST_RESOURCE_PYTHON_RELEASE_UNCONFIRMED")):
            with self.subTest(environment=environment):
                completed, events, _ = self.run_fixture(**environment)
                self.assertEqual(completed.returncode, 1)
                self.assertEqual(events[-1], "release")
                self.assertIn(message, completed.stderr)


if __name__ == "__main__":
    unittest.main()
