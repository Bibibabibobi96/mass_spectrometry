"""Original project CLI adapters; the common owner holds the failure matrix."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from common.contracts import test_run_artifact_workflow as owner_fixture
from common.contracts.capacity_protection import load_capacity_protection_leases

REPO = owner_fixture.REPO
OWNER = owner_fixture.OWNER
PWSH = shutil.which("pwsh")


@unittest.skipUnless(PWSH, "PowerShell 7 required")
class OwnerFinalizationRecoveryTests(unittest.TestCase):
    def test_original_cli_replays_after_seal_and_rejects_unknown_writer(self) -> None:
        helper = owner_fixture.RunArtifactWorkflowTests()
        project = "dual_pressure_rectilinear_ion_processor"
        cli = REPO / "projects" / project / "simion/run_functional.ps1"
        for failure in ("publication", "seal", "unknown"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory(prefix="ip-owner-recovery-") as directory:
                root = Path(directory)
                _, run, _, _ = helper.invoke_fixture(root, {}, project=project, retention="solver_review", failure_stage="retention_before")
                config_path = run / "run_config.json"
                config = json.loads(config_path.read_text(encoding="utf-8-sig"))
                config["mode"] = "native_electrode_functional"
                config_path.write_text(json.dumps(config), encoding="utf-8")
                for relative in ("inputs/execution_request.json", "results/execution_completion.json", "logs/prepared_wait.json"):
                    (run / relative).unlink()
                entry = run / "inputs/run_functional.ps1"
                shutil.copyfile(cli, entry)
                budget = run / "inputs/runtime_profiles.json"
                budget.write_text('{"fixture_budget_bytes":1048576}', encoding="utf-8")
                result_path = run.parent.parent / "scratch/workflow_results" / run.name / "result.json"
                hook = "function Publish-WorkflowTerminal { throw 'IP_PUBLICATION_SENTINEL' }" if failure == "publication" else ""
                if failure == "seal":
                    hook = """$actualCapacity=${function:Invoke-RunCapacityCommand}
function Invoke-RunCapacityCommand {
 param($Python,$RepoRoot,$Arguments,$FailureLabel)
 if('seal-stopped-payload'-in$Arguments){throw 'IP_SEAL_SENTINEL'}
 & $actualCapacity @PSBoundParameters
}
"""
                execution = "writer_completion_unknown" if failure == "unknown" else "completed"
                validity = "unknown" if failure == "unknown" else "valid"
                science = "unknown" if failure == "unknown" else "passed"
                first = helper.run_ps(root, f""". '{OWNER}'
function Invoke-ArtifactCapacityGate {{ return @{{satisfied=$true;fixture_admission=$true}} }}
function Invoke-ResourceBudgetedProcess {{throw 'NATIVE_MUST_NOT_START'}}
$session=Get-Content '{run / 'logs/capacity_session.json'}' -Raw|ConvertFrom-Json
$package=@{{native_path_preparation=@{{calls=0;elapsed_seconds=0.0;transport_bytes=0L}};run_config='{config_path}';run_dir='{run}';artifact_run_dir='{run}'}}
$context=Initialize-RunArtifactPowerShellOwner -Python '{sys.executable}' -RepoRoot '{REPO}' -Package $package -CapacitySession $session -EntrypointPath '{entry}' -CommitmentInputPaths @('{budget}') -Software @('Python')
{hook}
try {{
 $outcome=Complete-RunArtifactPowerShellOwner -Context $context -Status success -Summary @{{role='ion_processor_functional_summary';execution_status='{execution}';data_validity='{validity}';science_status='{science}';phase_durations_seconds=@{{analysis=0.1}};total_elapsed_seconds=0.1}} -OutputPaths @('{run / 'results/science.json'}') -WriterCompletion @{{operations=@();resource_releases=@()}} -WritersStopped ${str(failure != 'unknown').lower()}
 throw 'Expected closeout injection did not fail'
}} catch {{
 if($_.Exception.Message-notmatch'IP_PUBLICATION_SENTINEL|IP_SEAL_SENTINEL|writer completion is unknown'){{throw}}
 if($context.completion_written-ne${str(failure != 'unknown').lower()}){{throw 'Completion persistence state differs'}}
}}
""")
                self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
                result = json.loads(result_path.read_text(encoding="utf-8-sig"))
                self.assertEqual(result["resume_action"], "inspect_writer_completion" if failure == "unknown" else "resume_finalization")
                if failure == "unknown":
                    self.assertEqual(result["execution_status"], "writer_completion_unknown")
                    self.assertEqual(result["data_validity"], "unknown")
                    self.assertEqual(result["recovery_action"], "inspect_writer_completion")
                    self.assertEqual(result["phase_timings_seconds"], {"analysis": 0.1})
                terminal_before = (run / "run_manifest.json").read_bytes()
                command = [PWSH, "-NoProfile", "-File", str(cli), "-RunId", run.name,
                           "-ResultPath", str(result_path), "-ResumeFinalization"]
                resumed = subprocess.run(command, cwd=REPO, env={**os.environ,"SIMULATION_PYTHON_EXE":sys.executable}, capture_output=True, text=True, encoding="utf-8", timeout=90)
                if failure == "unknown":
                    self.assertNotEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
                    self.assertEqual((run / "run_manifest.json").read_bytes(), terminal_before)
                    self.assertIn(run.resolve(), load_capacity_protection_leases(root / "artifacts")["protected_paths"])
                    continue
                self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
                result = json.loads(result_path.read_text(encoding="utf-8-sig"))
                self.assertTrue(result["terminal_published"] and result["capacity_finalized"] and result["lease_released"])
                self.assertEqual(result["scientific_result"], "passed")
                self.assertGreaterEqual(result["total_elapsed_seconds"], 0.1)
                if failure == "seal":
                    self.assertEqual((run / "run_manifest.json").read_bytes(), terminal_before)
                manifest_bytes = (run / "run_manifest.json").read_bytes()
                summary_bytes = (run / "summary.json").read_bytes()
                repeated = subprocess.run(command, cwd=REPO, env={**os.environ,"SIMULATION_PYTHON_EXE":sys.executable}, capture_output=True, text=True, encoding="utf-8", timeout=90)
                self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
                self.assertEqual((run / "run_manifest.json").read_bytes(), manifest_bytes)
                self.assertEqual((run / "summary.json").read_bytes(), summary_bytes)
                self.assertEqual((root / "callback_count.txt").read_text(), "1")
