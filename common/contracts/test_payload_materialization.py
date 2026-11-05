"""Inert raw-suffix byte transport; no SIMION, PA parser or scientific field claim."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from msplatform.execution.context import ExecutionContext
from msplatform.execution.manifest_records import file_record
from msplatform.execution.payload_inputs import materialize_payloads, _outputs
from msplatform.execution.processes import ProcessExecutionError
from msplatform.execution.resources import resource_path
from msplatform.execution.run_session import RunSession


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows file-share/robocopy transport required")
class PayloadMaterializationTests(unittest.TestCase):
    def session(self, root):
        run = root / "run"
        run.mkdir()
        for name in ("inputs", "results", "logs"):
            (run / name).mkdir()
        (run / "run_config.json").write_text('{"inputs":{}}', encoding="utf-8")
        context = ExecutionContext(workspace=root, python_executable=Path(sys.executable),
            powershell_executable=Path(shutil.which("pwsh")), tools={},
            host_state_path=Path(os.environ["MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH"]),
            policy_path=resource_path("host_resource_policy.json"))
        return RunSession(context=context, artifact_root=root / "artifacts", run_id="inert-payload-fixture",
            project="software_fixture", mode="analysis", package={"run_dir": str(run), "artifact_run_dir": str(run)},
            capacity_session={}, execution_request=root / "not-used-request.json", result_path=root / "result.json",
            expected_operation_ids=("materialize_geometry",))

    def test_actual_run_session_materializes_raw_suffixes_without_native_or_source_mutation(self):
        with tempfile.TemporaryDirectory(prefix="payload 中文 ") as directory:
            root = Path(directory)
            session = self.session(root)
            sources, copies = [], []
            for name, data in (("geometry.pa#", b"INERT_NOT_PA\0"*100), ("geometry.pa-surf", bytes(range(128)))):
                source = root / name
                source.write_bytes(data)
                sources.append((source, data))
                copies.append(dict(source_record=file_record(source, "solver_native_binary"),
                    destination=str(session.run_dir / "model" / name)))
            # Only capacity fixture bookkeeping is stubbed; public process owner,
            # host lease, worker, copying, hashes and operation receipts are real.
            with patch.object(session, "renew_capacity", return_value={}):
                try:
                    records = materialize_payloads(tuple(copies), session=session, limits=None)
                except ProcessExecutionError as failure:
                    for path in session.log_dir.glob("*.stderr.log"):
                        failure.add_note(path.read_text(encoding="utf-8-sig"))
                    raise
            self.assertEqual(len(records), 2)
            self.assertEqual(session.operations[0]["observation"]["returncode"], 0)
            self.assertTrue(session.operations[0]["observation"]["exit_confirmed"])
            self.assertTrue(session.writers_stopped)
            for record, (source, data) in zip(records, sources, strict=True):
                target = Path(record["path"])
                self.assertFalse(target.samefile(source))
                self.assertEqual(target.read_bytes(), data)
                self.assertEqual(record["sha256"], hashlib.sha256(data).hexdigest().upper())
                self.assertEqual(record["retention_role"], "solver_native_binary")
                target.write_bytes(b"OWNED_MODEL_EDIT")
                self.assertEqual(source.read_bytes(), data)
            config = json.loads(session.run_config.read_text(encoding="utf-8"))
            self.assertEqual(len(config["inputs"]), 3)
            self.assertTrue(all(session.file_roles[p] == "required_evidence" for p in config["inputs"].values()))

    def test_wrong_frozen_identity_fails_real_worker_and_releases_without_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = self.session(root)
            source = root / "raw.pa#"
            source.write_bytes(b"INERT_NOT_NATIVE")
            record = file_record(source, "solver_native_binary")
            record["sha256"] = "0"*64
            target = session.run_dir / "model.pa#"
            with patch.object(session, "renew_capacity", return_value={}):
                with self.assertRaises(ProcessExecutionError):
                    materialize_payloads((dict(source_record=record, destination=str(target)),), session=session, limits=None)
            self.assertFalse(target.exists())
            self.assertTrue(session.writers_stopped)
            receipt = json.loads((session.result_dir / "materialize_geometry_payload_receipt.json").read_text())
            self.assertEqual(receipt["status"], "failed")
            self.assertIn("SHA256", receipt["primary"])
            source.write_bytes(b"SOURCE_HANDLE_RELEASED")

    def test_existing_destination_and_bad_release_receipt_do_not_succeed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = self.session(root)
            source, target = root / "source.pa-surf", session.run_dir / "existing.pa-surf"
            source.write_bytes(b"one")
            target.write_bytes(b"two")
            copies = [dict(source_record=file_record(source, "solver_native_binary"), destination=str(target))]
            with self.assertRaises(ValueError):
                materialize_payloads(copies, session=session, limits=None)
            self.assertEqual(target.read_bytes(), b"two")
            output = file_record(target, "solver_native_binary")
            copies[0]["source_record"] = file_record(target, "solver_native_binary")
            with self.assertRaisesRegex(ValueError, "guard release"):
                _outputs(dict(schema_version=1, role="payload_materialization", status="success", primary=None,
                    secondary_errors=[], outputs=[output], source_and_destination_releases=[]), copies)

    def test_inert_small_file_forced_unbuffered_branch_keeps_original_guard_and_hash(self):
        with tempfile.TemporaryDirectory(prefix="payload_j_中文 ") as directory:
            root = Path(directory)
            source, target = root / "raw source.pa#", root / "raw target.pa-surf"
            payload = bytes(range(256))*4
            source.write_bytes(payload)
            script = r'''
. $env:PAYLOAD_LEAF -UnbufferedIdentityReader {
 param($Source,$Length)
 $value=@(& $env:TEST_PYTHON -I -B -c 'import sys;from msplatform.execution.file_identity import file_sha256_unbuffered;print(file_sha256_unbuffered(sys.argv[1]))' $Source)
 if($LASTEXITCODE-ne0){throw 'real unbuffered reader failed'}
 return $value
}
if($global:MassSpectrometryShortPaUnbufferedThresholdBytes-ne8MB){throw 'Default tier changed'}
$global:MassSpectrometryShortPaUnbufferedThresholdBytes=1 # inert-byte fixture branch selection only
$identity=Protect-ImmutablePaSource -Source $env:SOURCE -ExpectedBytes 1024 -ExpectedSha256 $env:DIGEST
$blocked=$false
try{$writer=[IO.File]::OpenWrite($env:SOURCE);$writer.Dispose()}catch [IO.IOException]{$blocked=$true}
if(-not$blocked){throw 'Source writer not blocked'}
$stream=[IO.File]::OpenRead($env:SOURCE)
try{Copy-StandalonePaBytes -SourceStream $stream -Destination $env:TARGET -Length 1024}finally{$stream.Dispose()}
$copied=Protect-ImmutablePaSource -Source $env:TARGET -ExpectedBytes 1024 -ExpectedSha256 $env:DIGEST
$null=Unprotect-ImmutablePaSource -Source $env:TARGET
$null=Unprotect-ImmutablePaSource -Source $env:SOURCE
'INERT_UNBUFFERED_BYTES=PASS'
'''
            result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script],
                cwd=root,
                env=dict(os.environ, PAYLOAD_LEAF=str(resource_path("payload_file_support.ps1")),
                    TEST_PYTHON=sys.executable, SOURCE=str(source), TARGET=str(target),
                    DIGEST=hashlib.sha256(payload).hexdigest().upper()),
                capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn("INERT_UNBUFFERED_BYTES=PASS", result.stdout)
            self.assertEqual(target.read_bytes(), payload)
            self.assertEqual(source.read_bytes(), payload)


if __name__ == "__main__":
    unittest.main()
