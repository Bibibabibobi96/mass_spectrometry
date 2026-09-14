"""Pure protocol checks and Windows bridge fixtures without a real host ledger."""

import json
import importlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from common import host_resource_python as adapter


def result(value=None, code=0, stderr=b""):
    output = b"" if value is None else (adapter._RESULT + json.dumps(value)).encode()
    return subprocess.CompletedProcess([], code, stdout=output, stderr=stderr)


class PythonHeavyProtocolTests(unittest.TestCase):
    def test_bridge_preserves_cwd_without_an_extra_solver_deadline(self):
        for operation in ("enter", "call", "assert"):
            with self.subTest(operation=operation), \
                    patch.object(adapter.os, "name", "nt"), \
                    patch.object(adapter.sys, "version_info", (3, 11)), \
                    patch.object(adapter.subprocess, "run", return_value=result()) as run:
                adapter._bridge(operation)
                self.assertEqual(run.call_args.kwargs["cwd"], Path.cwd())
                self.assertIsNone(run.call_args.kwargs["timeout"])

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
    return @{token=$env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN}
}
function Assert-HostResourceHeavyStage {
    param($Lease)
    Record-Event 'assert'
    if ($env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN -ne 'fixture-heavy') { throw 'fixture token is not heavy' }
}
function Exit-HostResourceStage {
    param($Lease)
    Record-Event 'release'
    if ($env:FIXTURE_RELEASE_FAIL) { throw 'fixture release failure' }
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


class HeavyConsumerEntryTests(unittest.TestCase):
    def test_theory_clis_check_before_reading_inputs_or_computing(self):
        consumers = {
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0_hardware_candidate":
                ["--contract", "missing.json", "--output", "unused.json"],
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0_l1_hardware_candidate":
                ["--l0-receipt", "missing.json", "--contract", "missing.json", "--output", "unused.json"],
            "common.multipole.run_ideal_transport": ["--project-root", "missing"],
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
    def run_fixture(self, *, flags=0, task=_TASK, **extra):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            common = root / "common"
            common.mkdir()
            (common / "__init__.py").write_text("", encoding="utf-8")
            for suffix in (".py", ".ps1"):
                shutil.copyfile(Path(adapter.__file__).with_suffix(suffix), common / ("host_resource_python" + suffix))
            (common / "host_execution_lease.ps1").write_text(_FACADE, encoding="utf-8")
            (root / "fixture_task.py").write_text(task, encoding="utf-8")
            events = root / "events.txt"
            environment = os.environ.copy()
            for key in list(environment):
                if key.startswith("MASS_SPECTROMETRY_") or key.startswith("FIXTURE_"):
                    del environment[key]
            environment.update(PYTHONPATH=str(root), PYTHONIOENCODING="utf-8", FIXTURE_EVENTS=str(events), TMP=str(root), TEMP=str(root))
            environment.update(extra)
            arguments = ["space argument", "中文", "$(literal)", 'a"b', ""]
            completed = subprocess.run(
                [sys.executable, "-B", "-m", "fixture_task", *arguments], cwd=root, env=environment,
                capture_output=True, creationflags=flags, timeout=45,
            )
            recorded = events.read_text(encoding="utf-8").splitlines() if events.exists() else []
            self.assertEqual(list(root.glob("host-resource-python-call-*")), [])
            return completed, recorded, arguments

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
        completed, events, _ = self.run_fixture(FIXTURE_RELEASE_FAIL="1")
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(events[-1], "release")
        self.assertIn(b"HOST_RESOURCE_PYTHON_RELEASE_ERROR=", completed.stderr)


if __name__ == "__main__":
    unittest.main()
