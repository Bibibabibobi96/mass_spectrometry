"""Original project CLI adapters; the common owner holds the failure matrix."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

from common.contracts import test_run_artifact_workflow as owner_fixture
from common.contracts.write_run_manifest import file_record

REPO = owner_fixture.REPO
OWNER = owner_fixture.OWNER
PWSH = shutil.which("pwsh")


@unittest.skipUnless(PWSH, "PowerShell 7 required")
class OwnerFinalizationRecoveryTests(unittest.TestCase):
    def test_rf_original_cli_resumes_existing_owner_completion(self) -> None:
        helper = owner_fixture.RunArtifactWorkflowTests()
        with tempfile.TemporaryDirectory(prefix="workflow-rf-cli-") as directory:
            root = Path(directory)
            _, run, _, _ = helper.invoke_fixture(root, {}, failure_stage="retention_before", project="rf_multipole_ion_optics")
            request_path = run / "inputs/execution_request.json"
            request = json.loads(request_path.read_text(encoding="utf-8-sig"))
            entry = run / "inputs/owner.ps1"
            entry.write_text("# frozen all-reuse owner fixture\n", encoding="utf-8")
            request["prepared"] = {"owner_kind": "powershell", "entrypoint": file_record(entry)}
            request_path.write_text(json.dumps(request), encoding="utf-8")
            completion_path = run / "results/execution_completion.json"
            completion = json.loads(completion_path.read_text(encoding="utf-8-sig"))
            completion.update(execution_request=file_record(request_path), writer_completion={"operations": [], "resource_releases": []},
                              resource_usage_paths=[], resource_profile=None)
            completion_path.write_text(json.dumps(completion), encoding="utf-8")
            (root / "result.json").unlink()
            initial = helper.run_ps(root, f""". '{OWNER}'
Write-RunJson -Atomic -Path '{run / 'logs/prepared_wait.json'}' -Value @{{schema_version=1;role='run_artifact_powershell_owner_wait';owner_pid=$PID;owner_start_utc_ticks=(Get-Process -Id $PID).StartTime.ToUniversalTime().Ticks;native_writers_confirmed=$true;exception=$null;observation_error=$null}}
""")
            self.assertEqual(initial.returncode, 0, initial.stdout + initial.stderr)
            fixture_repo = root / "simulation_repo"
            shutil.copytree(REPO / "common", fixture_repo / "common", ignore=shutil.ignore_patterns("__pycache__"))
            relative = Path("projects/rf_multipole_ion_optics/workflows/no_collision_transport/run_simion.ps1")
            cli = fixture_repo / relative
            cli.parent.mkdir(parents=True)
            shutil.copyfile(REPO / relative, cli)
            outcome = subprocess.run([PWSH, "-NoProfile", "-File", str(cli), "-ResumeFinalization", "-RunId", run.name,
                                      "-PythonExe", sys.executable, "-ResultPath", str(root / "result.json")],
                                     cwd=fixture_repo, capture_output=True, text=True, encoding="utf-8", timeout=90)
            self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
            self.assertIn("MULTIPOLE_SIMION_FINALIZATION=success", outcome.stdout)
            self.assertEqual(json.loads((root / "result.json").read_text(encoding="utf-8-sig"))["status"], "success")
            self.assertEqual((root / "callback_count.txt").read_text(), "1")
