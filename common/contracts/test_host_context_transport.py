"""The public run environment survives actual PowerShell -File JSON argv."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from msplatform.execution.context import ExecutionContext
from msplatform.execution.run_session import RunSession


REPO = Path(__file__).resolve().parents[2]
PWSH = shutil.which("pwsh")


@unittest.skipUnless(PWSH, "PowerShell 7 is required for actual -File transport")
class HostContextTransportTests(unittest.TestCase):
    def test_run_environment_preserves_explicit_context_through_file_json_argv(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace-\u03bb-O'Brien"
            workspace.mkdir()
            ledger = root / "shared-\u00e9-owner's" / "custom.sqlite3"
            policy = root / "policy-\u03c0-owner's.json"
            policy.write_text('{"configuration_only": true}', encoding="utf-8")
            context = ExecutionContext(workspace=workspace,
                python_executable=Path(sys.executable).resolve(),
                powershell_executable=Path(PWSH).resolve(), tools={},
                host_state_path=ledger, policy_path=policy)
            run = workspace / "not-materialized-run"
            session = RunSession(context=context, artifact_root=root / "artifacts",
                run_id="20261109_000000__test__python__host-context", project="instrument_assembly",
                mode="transport_test", package=dict(run_dir=str(run), artifact_run_dir=str(run)),
                capacity_session={}, execution_request=run / "inputs/execution_request.json",
                result_path=run / "result.json")
            expected = dict(workspace=str(workspace), python_executable=str(Path(sys.executable).resolve()),
                            host_state_path=str(ledger), policy_path=str(policy))
            carrier = session.environment["MASS_SPECTROMETRY_HOST_CONTEXT_JSON"]
            self.assertEqual(json.loads(carrier), expected)
            fixture = workspace / "private-fixture.ps1"
            fixture.write_text(r'''param([Parameter(Mandatory)][string]$ContextJson,
      [Parameter(Mandatory)][string]$SupportPath)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$parsed=$ContextJson|ConvertFrom-Json -AsHashtable
. $SupportPath -HostContext $parsed
Write-Output ('HOST_CONTEXT_RESULT='+$env:MASS_SPECTROMETRY_HOST_CONTEXT_JSON)
''', encoding="utf-8")
            self.assertFalse(ledger.exists())
            child = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", str(fixture),
                "-ContextJson", carrier, "-SupportPath", str(REPO / "src/msplatform/execution/resources/host_execution_lease.ps1")],
                cwd=workspace, env=dict(os.environ), capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
            output = [line.removeprefix("HOST_CONTEXT_RESULT=") for line in child.stdout.splitlines()
                      if line.startswith("HOST_CONTEXT_RESULT=")]
            self.assertEqual(len(output), 1, child.stdout)
            self.assertEqual(json.loads(output[0]), expected)
            self.assertFalse(ledger.exists(), "Configuration-only initialization must not create a scheduler database")
            self.assertEqual(list(root.rglob("*.sqlite3")), [])
            self.assertFalse(run.exists(), "Reading the run environment must not materialize a run")


if __name__ == "__main__":
    unittest.main()
