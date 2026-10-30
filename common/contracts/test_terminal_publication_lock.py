"""Terminal publication serializes journal replay and standard manifest writes."""

import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from common.contracts.capacity_protection import process_file_lock
from common.contracts.write_run_manifest import (
    TERMINAL_JOURNAL_NAME, TERMINAL_LOCK_NAME, build_run_manifest,
    publish_run_manifest, publish_terminal_state, replay_terminal_publication,
)
from common.contracts import write_run_manifest


class TerminalPublicationLockTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, dict, dict]:
        config = root / "run_config.json"
        config.write_text(json.dumps({"schema_version": 1, "run_id": "20261029_120000__sim__simion__fixture",
            "project": "fixture", "mode": "fixture", "inputs": {}}), encoding="utf-8")
        (root / "summary.json").write_text('{"status":"checkpoint"}', encoding="utf-8")
        checkpoint = build_run_manifest(config, "checkpoint")
        (root / "run_manifest.json").write_text(json.dumps(checkpoint), encoding="utf-8")
        failed = build_run_manifest(config, "failed")
        return config, {"status": "failed"}, failed

    def test_checkpoint_updates_but_terminal_manifest_cannot_be_overwritten(self):
        repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, _, _ = self._fixture(root)
            command = [sys.executable, "-m", "common.contracts.write_run_manifest", "--run-config", str(config)]
            for status in ("checkpoint", "checkpoint", "success"):
                result = subprocess.run([*command, "--status", status], cwd=repo, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            before = (root / "run_manifest.json").read_bytes()
            result = subprocess.run([*command, "--status", "failed"], cwd=repo, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already published terminal", result.stderr)
            self.assertEqual((root / "run_manifest.json").read_bytes(), before)

    def test_writer_excludes_its_held_lock_from_enumerated_outputs(self):
        repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, _, _ = self._fixture(root)
            lock = root / TERMINAL_LOCK_NAME
            lock.write_bytes(b"\0")
            payload = root / "result.txt"
            payload.write_text("result", encoding="utf-8")
            command = [sys.executable, "-m", "common.contracts.write_run_manifest", "--run-config", str(config),
                       "--status", "success", "--output", str(lock), "--output", str(payload)]
            result = subprocess.run(command, cwd=repo, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            manifest = json.loads((root / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual([item["path"] for item in manifest["outputs"]], [str(payload.resolve())])

    def test_superseded_is_a_terminal_manifest(self):
        repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, _, _ = self._fixture(root)
            command = [sys.executable, "-m", "common.contracts.write_run_manifest", "--run-config", str(config)]
            self.assertEqual(subprocess.run([*command, "--status", "superseded"], cwd=repo, capture_output=True, timeout=30).returncode, 0)
            before = (root / "run_manifest.json").read_bytes()
            self.assertNotEqual(subprocess.run([*command, "--status", "success"], cwd=repo, capture_output=True, timeout=30).returncode, 0)
            self.assertEqual((root / "run_manifest.json").read_bytes(), before)

    def test_only_explicit_same_owner_provisional_can_transition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, _, _ = self._fixture(root)
            provisional = build_run_manifest(config, "interrupted", extra_fields={"lifecycle_state": "provisional"})
            (root / "run_manifest.json").write_text(json.dumps(provisional), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "already published"):
                publish_run_manifest(config, "checkpoint")
            wrong = dict(provisional, project="other")
            (root / "run_manifest.json").write_text(json.dumps(wrong), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "already published"):
                publish_run_manifest(config, "checkpoint", allow_provisional=True)
            (root / "run_manifest.json").write_text(json.dumps(provisional), encoding="utf-8")
            self.assertEqual(publish_run_manifest(config, "checkpoint", allow_provisional=True)["status"], "checkpoint")

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_standard_writer_and_journal_publisher_cannot_overwrite_each_other(self):
        repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, summary, failed = self._fixture(root)
            intent = root / "intent.json"
            intent.write_text(json.dumps({"summary": summary, "manifest": failed}), encoding="utf-8")
            journal_command = [sys.executable, "-c", (
                "import json,sys;from pathlib import Path;"
                "from common.contracts.write_run_manifest import publish_terminal_state;"
                "p=Path(sys.argv[1]);d=json.loads(Path(sys.argv[2]).read_text());"
                "publish_terminal_state(p,d['summary'],d['manifest'])"), str(root), str(intent)]
            wrapper = root / "writer.ps1"
            wrapper.write_text("""param($Repo,$Python,$Config)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
Write-VerifiedRunManifest -Python $Python -RepoRoot $Repo -RunConfig $Config -Status success
""", encoding="utf-8")
            standard_command = [shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-File", str(wrapper),
                                str(repo), sys.executable, str(config)]
            with process_file_lock(root / TERMINAL_LOCK_NAME):
                processes = [subprocess.Popen(command, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                             for command in (journal_command, standard_command)]
            results = [process.communicate(timeout=30) for process in processes]
            codes = [process.returncode for process in processes]
            self.assertEqual(sorted(codes), [0, 1], results)
            manifest = json.loads((root / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertIn(manifest["status"], {"success", "failed"})
            self.assertFalse((root / ".run_terminal_publication.json").exists())

    @unittest.skipUnless(sys.platform == "win32" and shutil.which("pwsh"), "Windows shared reader required")
    def test_two_independent_readers_block_publication_until_both_release_empty_lock(self):
        repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, summary, manifest = self._fixture(root)
            before = (root / "run_manifest.json").read_bytes()
            reader = root / "reader.ps1"
            reader.write_text("""param($Repo,$Run,$Ready,$Release)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
$guard=Enter-RunTerminalConsumptionGuard -RunDirectory $Run
try {
 [IO.File]::WriteAllText($Ready,'shared reader acquired')
 $deadline=[datetime]::UtcNow.AddSeconds(30)
 while(-not(Test-Path -LiteralPath $Release)) {
  if([datetime]::UtcNow-ge$deadline){throw 'Reader fixture release barrier timed out'}
  Start-Sleep -Milliseconds 20
 }
} finally {$guard.Dispose()}
""", encoding="utf-8")
            releases = [root / f"release-{index}" for index in range(2)]
            ready = [root / f"ready-{index}" for index in range(2)]
            processes = []
            try:
                for index in range(2):
                    processes.append(subprocess.Popen(
                        [shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-File", str(reader),
                         str(repo), str(root), str(ready[index]), str(releases[index])],
                        cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
                deadline = time.monotonic() + 20
                while not all(path.exists() for path in ready):
                    self.assertTrue(all(process.poll() is None for process in processes), "Reader exited before acquisition")
                    self.assertLess(time.monotonic(), deadline, "Second reader could not acquire shared lock")
                    time.sleep(.02)
                lock = root / TERMINAL_LOCK_NAME
                self.assertEqual(lock.stat().st_size, 0)
                # Shorten only the real lock's fixture wait, not its behavior.
                with patch.object(write_run_manifest, "process_file_lock",
                                  side_effect=lambda path: process_file_lock(path, timeout_seconds=.2)):
                    with self.assertRaises(TimeoutError):
                        publish_terminal_state(root, summary, manifest)
                    self.assertFalse((root / TERMINAL_JOURNAL_NAME).exists())
                    self.assertEqual((root / "run_manifest.json").read_bytes(), before)
                    self.assertEqual(lock.stat().st_size, 0)
                    releases[0].write_text("release first", encoding="utf-8")
                    first = processes[0].communicate(timeout=30)
                    self.assertEqual(processes[0].returncode, 0, first)
                    with self.assertRaises(TimeoutError):
                        publish_terminal_state(root, summary, manifest)
                    self.assertFalse((root / TERMINAL_JOURNAL_NAME).exists())
                    self.assertEqual(lock.stat().st_size, 0)
                releases[1].write_text("release second", encoding="utf-8")
                second = processes[1].communicate(timeout=30)
                self.assertEqual(processes[1].returncode, 0, second)
                publish_terminal_state(root, summary, manifest)
                self.assertEqual(json.loads((root / "run_manifest.json").read_text(encoding="utf-8"))["status"], "failed")
                self.assertFalse((root / TERMINAL_JOURNAL_NAME).exists())
                self.assertEqual(lock.stat().st_size, 1)
            finally:
                # Release only these fixture barriers; healthy children finish.
                for path in releases:
                    path.write_text("fixture teardown", encoding="utf-8")
                for process in processes:
                    process.communicate(timeout=30)

    def test_stale_journal_cannot_replace_a_different_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, failed_summary, failed = self._fixture(root)
            success = build_run_manifest(config, "success")
            publish_terminal_state(root, {"status": "success"}, success)
            before = (root / "run_manifest.json").read_bytes()
            (root / TERMINAL_JOURNAL_NAME).write_text(json.dumps({"schema_version": 1,
                "role": "run_terminal_publication_journal", "run_id": success["run_id"],
                "documents": {"summary.json": failed_summary, "run_manifest.json": failed}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "conflicts"):
                replay_terminal_publication(root)
            self.assertEqual((root / "run_manifest.json").read_bytes(), before)

    def test_interrupted_journal_replays_exact_intent_without_reentering_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, summary, manifest = self._fixture(root)
            write = write_run_manifest.write_json_atomic
            def fail_summary(path, document):
                if path.name == "summary.json":
                    raise OSError("injected publication failure")
                return write(path, document)
            with patch.object(write_run_manifest, "write_json_atomic", side_effect=fail_summary):
                with self.assertRaisesRegex(OSError, "injected"):
                    publish_terminal_state(root, summary, manifest)
            self.assertTrue((root / TERMINAL_JOURNAL_NAME).is_file())
            self.assertEqual(replay_terminal_publication(root), (summary, manifest))
            self.assertFalse((root / TERMINAL_JOURNAL_NAME).exists())

    def test_lock_released_on_process_exit_and_exception(self):
        repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / TERMINAL_LOCK_NAME
            command = [sys.executable, "-c", (
                "import os,sys;from pathlib import Path;"
                "from common.contracts.capacity_protection import process_file_lock;"
                "lock=process_file_lock(Path(sys.argv[1]));lock.__enter__();os._exit(0)"), str(lock)]
            self.assertEqual(subprocess.run(command, cwd=repo, timeout=30).returncode, 0)
            with process_file_lock(lock, timeout_seconds=1):
                pass
            with self.assertRaisesRegex(RuntimeError, "fixture"):
                with process_file_lock(lock, timeout_seconds=1):
                    raise RuntimeError("fixture")
            with process_file_lock(lock, timeout_seconds=1):
                self.assertTrue(lock.exists())


if __name__ == "__main__":
    unittest.main()
