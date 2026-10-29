"""Solver-free checks of reusable RF batch completion evidence."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from projects.rf_multipole_ion_optics.runtime.simion_batch_completion import validate_batch_completion


class SimionBatchCompletionTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_failed_owner_binds_retained_receipt_and_outputs(self):
        repo = Path(__file__).resolve().parents[4]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runs/20261029_120000__sim__simion__rf-receipt"
            root.mkdir(parents=True)
            (root / "results").mkdir()
            (root / "logs").mkdir()
            (root / "run_config.json").write_text(json.dumps({
                "schema_version": 2, "run_id": "20261029_120000__sim__simion__rf-receipt", "project": "rf_multipole_ion_optics",
                "mode": "resolved_design_transport", "inputs": {}, "formal_gate_passed": False,
                "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None},
            }), encoding="utf-8")
            receipt = root / "results/simion_batch_completion__rf_on__batch_01.json"
            state = root / "results/particle_states__rf_on__batch_01.csv"
            log = root / "logs/simion_stdout__fly__rf_on__batch_1.txt"
            receipt.write_text('{"role":"multipole_simion_completed_batch"}', encoding="utf-8")
            state.write_text("particle_id,event\n1,terminal\n", encoding="utf-8")
            log.write_text("Fly completed. 1 splats\n", encoding="utf-8")
            script = r"""param($Repo,$Python,$Root)
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
Complete-FailedRun -Python $Python -RepoRoot $Repo -RunConfig (Join-Path $Root 'run_config.json') `
 -Summary (Join-Path $Root 'summary.json') -SummaryRole 'rf_test_summary' `
 -Reason 'injected analysis failure' -Software @('SIMION 2020')
"""
            script_path = root / "fail-owner.ps1"
            script_path.write_text(script, encoding="utf-8")
            result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(script_path),
                                     str(repo), sys.executable, str(root)], cwd=repo,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            manifest = json.loads((root / "run_manifest.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(manifest["status"], "failed")
            bound = {Path(record["path"]) for record in manifest["outputs"] if record["exists"]}
            self.assertTrue({receipt, state, log} <= bound)

    def test_requires_native_completion_and_complete_local_terminal_population(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log, state, summary, mechanical = (root / name for name in ("stdout", "state.csv", "summary.json", "exit.csv"))
            log.write_text("status,Fly completed. 2 splats, 1.25 seconds\n", encoding="utf-8")
            state.write_text("particle_id,event\n2,terminal\n1,source\n1,terminal\n", encoding="utf-8")
            summary.write_text(json.dumps({"solver": "SIMION", "particles": 2}), encoding="utf-8")
            mechanical.write_text("particle_id\n2\n", encoding="utf-8")
            def validate():
                validate_batch_completion(stdout=log, state=state, summary=summary,
                                          particle_count=2, mechanical=mechanical)
            validate()
            log.write_text("status,Fly completed.\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate()
            log.write_text("status,Fly completed. 2 splats\n", encoding="utf-8")
            state.write_text("particle_id,event\n1,terminal\n1,terminal\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "terminal rows"):
                validate()
            state.write_text("particle_id,event\n1,terminal\n2,terminal\n", encoding="utf-8")
            mechanical.write_text("particle_id\n3\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "mechanical exit"):
                validate()

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_runner_receipts_only_stopped_complete_workers(self):
        repo = Path(__file__).resolve().parents[4]
        runner = repo / "projects/rf_multipole_ion_optics/runtime/run_simion_finite_3d_transport.ps1"
        source = runner.read_text(encoding="utf-8-sig")
        action = source[source.index("      $checkpointAction={"):
                        source.index("      $wave=Invoke-SimionBatchPhase", source.index("      $checkpointAction={"))]
        self.assertNotIn("Write-VerifiedRunManifest", action)
        self.assertIn("$outputs+=@($batchCompletionReceipts)", source)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "stdout.txt").write_text("status,Fly completed. 2 splats\n", encoding="utf-8")
            (root / "state.csv").write_text("particle_id,event\n1,terminal\n2,terminal\n", encoding="utf-8")
            (root / "summary.json").write_text('{"solver":"SIMION","particles":2}', encoding="utf-8")
            script = root / "check.ps1"
            script.write_text("""param($Repo,$Python,$Root)
$ErrorActionPreference='Stop'
$codeRoot=$Repo;$manifestRepoRoot=$Repo;$python=$Python;$runConfig='fixture';$name='primary';$resultDir=$Root;$runDir=$Root
$mechanicalExitEnabled=$false;$RetentionClass='compact';$checkpointOutputs=[Collections.ArrayList]::new()
$nativeOperations=[Collections.ArrayList]::new()
$retainedTrajectoryOutputs=[Collections.ArrayList]::new()
$batchCompletionReceipts=[Collections.ArrayList]::new()
$script:retainedFormalBatchOutputs=@{}
$batchRuns=@(@{batch=@{index=1;particle_id_min=1;particle_id_max=2};state=(Join-Path $Root 'state.csv');summary=(Join-Path $Root 'summary.json')})
$batchState=[pscustomobject]@{runs=$batchRuns}
$record=@{exit_code=0;root_process_id=123;root_process_started_at_utc_ticks=456;specification=@{stdout=(Join-Path $Root 'stdout.txt');scheduler_batch=@{index=1;count=2}}}
$script:publications=0
function Write-RunJson {param($Path,$Value,[switch]$Atomic)
 if(-not$Atomic-or$Value.role-ne'multipole_simion_completed_batch'-or$Value.particle_count-ne2){throw 'unexpected receipt'}
 if(@($Value.outputs|Where-Object{[IO.Path]::IsPathRooted($_)}).Count){throw 'receipt contains execution alias'}
 $Value|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $Path
 $script:publications++
}
""" + action + """
& $checkpointAction $record
if($script:publications-ne1){throw 'completed worker was not checkpointed'}
Set-Content -LiteralPath (Join-Path $Root 'state.csv') -Value 'particle_id,event`n1,terminal'
$caught=$false;try{& $checkpointAction $record}catch{$caught=$true}
if(-not$caught-or$script:publications-ne1){throw 'incomplete worker was checkpointed'}
Set-Content -LiteralPath (Join-Path $Root 'state.csv') -Value "particle_id,event`n1,terminal`n2,terminal"
$checkpointOutputs.Clear()
$script:retainedFormalBatchOutputs=@{primary=@{state=(Join-Path $Root 'state.csv');summary=(Join-Path $Root 'summary.json')}}
$batchRuns[0].state=Join-Path $Root 'batch_01_state.csv'
$batchRuns[0].summary=Join-Path $Root 'batch_01_summary.json'
& $checkpointAction $record
if($script:publications-ne2-or
   -not(Test-Path $batchRuns[0].state)-or-not(Test-Path $batchRuns[0].summary)){
 throw 'observed first worker was not bound to its replanned batch paths'
}
$script:retainedFormalBatchOutputs=@{};$RetentionClass='qualification'
$batchRuns[0].trajectory=Join-Path $Root 'trajectory.csv'
$caught=$false;try{& $checkpointAction $record}catch{$caught=$true}
if(-not$caught-or$script:publications-ne2){throw 'required trajectory absence was accepted'}
Set-Content -LiteralPath $batchRuns[0].trajectory -Value 'particle_id,time_us'
& $checkpointAction $record
if($script:publications-ne3-or-not$retainedTrajectoryOutputs.Contains($batchRuns[0].trajectory)){
 throw 'retained trajectory was not bound'
}
""", encoding="utf-8")
            result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(script),
                                     str(repo), sys.executable, str(root)], cwd=repo,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
