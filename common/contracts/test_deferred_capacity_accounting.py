"""Unresolved stopped-stage accounting keeps its original capacity owner."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

from common.contracts.capacity_ledger import initialize_capacity_ledger, load_capacity_ledger
from common.contracts.capacity_protection import load_capacity_protection_leases

ROOT = Path(__file__).resolve().parents[2]
OWNER_SOURCE = ROOT/'common/contracts/run_artifact_workflow.ps1'
PWSH = shutil.which('pwsh')


@unittest.skipUnless(PWSH, 'PowerShell 7 required')
class DeferredCapacityAccountingTests(unittest.TestCase):
    def test_completed_writer_defers_to_original_accounting_owner_without_recompute(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);artifacts=root/'artifacts';artifacts.mkdir()
            initialize_capacity_ledger(artifacts,objects=[])
            owner=OWNER_SOURCE
            script=root/'check.ps1'
            script.write_text(r"""param($Owner,$Repo,$Python,$Artifacts,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. $Owner
function Invoke-ArtifactCapacityGate {return @{satisfied=$true;fixture_admission=$true}}
$project=Join-Path $Artifacts 'projects/instrument_assembly'
$runId='20261030_120000__test__python__deferred-accounting'
$package=New-RunPackage -Python $Python -RepoRoot $Repo -ArtifactRoot $project -RunId $runId -Project instrument_assembly -Mode public_accounting_fixture -Software @('inert fixture') -RetentionContractEnabled -RetentionClass solver_review -RetentionReason 'small stopped-stage accounting fault fixture' -CapacityLedgerLifecycleEnabled
$entry=Join-Path $package.input_dir owner.ps1
[IO.File]::WriteAllText($entry,'throw "Prepared computation must never restart during accounting recovery"')
$authority=Join-Path $package.input_dir budget.json
Write-RunJson -Path $authority -Value @{committed_new_bytes=1048576}
$session=Enter-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $Repo -ArtifactRoot $Artifacts -RunDirectory $package.artifact_run_dir -CommittedNewBytes 1048576 -ProtectedPaths @($package.artifact_run_dir) -Owner ('run-artifact-workflow:instrument_assembly:'+$runId)
$context=Initialize-RunArtifactPowerShellOwner -Python $Python -RepoRoot $Repo -Package $package -CapacitySession $session -EntrypointPath $entry -CommitmentInputPaths @($authority)
$payload=Join-Path $package.result_dir science.json
[IO.File]::WriteAllText($payload,'INERT_COMPLETED_OUTPUT_NOT_SOLVER_EVIDENCE')
$counter=Join-Path $Root compute_count.txt;[IO.File]::WriteAllText($counter,'1')
$manifest=Join-Path $package.artifact_run_dir run_manifest.json
$manifestBefore=[IO.File]::ReadAllBytes($manifest)
$session|Add-Member -NotePropertyName defer_capacity_finalization -NotePropertyValue 'INJECTED_STOPPED_STAGE_ACCOUNTING_FAILURE' -Force
$leasePath=Join-Path $Artifacts ('common/capacity_protection_leases/'+$session.lease_id+'.json')
$leaseBefore=[IO.File]::ReadAllBytes($leasePath)
$primary=$null;try{throw 'PRIMARY_SCIENTIFIC_STAGE_FAILURE'}catch{$primary=$_}
$caught=$null
try{$null=Complete-RunArtifactPowerShellOwner -Context $context -Status failed -Summary @{schema_version=1;role='inert_capacity_fixture';execution_status='failed';data_validity='incomplete';scientific_result='NOT_EVALUATED'} -OutputPaths @($payload) -WriterCompletion @{operations=@();resource_releases=@()} -WritersStopped $true -OriginalFailure $primary}catch{$caught=$_}
if($null-eq$caught){throw 'Unresolved accounting was finalized'}
if(-not$context.completion_written-or-not(Test-Path -LiteralPath (Join-Path $package.result_dir execution_completion.json))){throw 'Actual stopped completion was not retained'}
for($attempt=0;$attempt-lt3;$attempt++){
 if($attempt-eq2){
  # An older recovery transport cannot erase a hold in the original run session.
  $transport=Get-Content -LiteralPath $context.result_path -Raw|ConvertFrom-Json -AsHashtable
  $mask=$session|ConvertTo-Json -Depth 64|ConvertFrom-Json -AsHashtable
  $null=$mask.Remove('defer_capacity_finalization')
  $transport.recovery_session=$mask
  $transport.execution_request_sha256=(Get-FileHash -LiteralPath $context.request_path -Algorithm SHA256).Hash
  Write-RunJson -Atomic -Path $context.result_path -Value $transport -Depth 64
 }
 if($attempt){try{$null=Invoke-RunArtifactWorkflow -RequestPath $context.request_path -ResultPath $context.result_path -ResumeFinalization;throw 'Accounting hold silently cleared'}catch{if($_.Exception.Message-notlike'*Capacity accounting is deferred*'){throw}}}
 $result=Get-Content -LiteralPath $context.result_path -Raw|ConvertFrom-Json -AsHashtable
 if($result.execution_status-ne'capacity_accounting_deferred'-or$result.resume_action-ne'return_to_capacity_accounting_owner'-or-not$result.writers_confirmed-or$result.lease_released-or$result.capacity_finalized-or$result.terminal_published){throw 'Deferred accounting mislabeled or released'}
 if($result.exception.message-ne'PRIMARY_SCIENTIFIC_STAGE_FAILURE'-or($result.secondary_errors-join' ')-notlike'*INJECTED_STOPPED_STAGE_ACCOUNTING_FAILURE*'){throw 'Primary/accounting errors not separated'}
 if(-not[Convert]::ToBase64String([IO.File]::ReadAllBytes($manifest)).Equals([Convert]::ToBase64String($manifestBefore))){throw 'Deferred accounting rewrote terminal/checkpoint evidence'}
 if(-not[Convert]::ToBase64String([IO.File]::ReadAllBytes($leasePath)).Equals([Convert]::ToBase64String($leaseBefore))){throw 'Original positive commitment or lease changed'}
 if([IO.File]::ReadAllText($payload)-ne'INERT_COMPLETED_OUTPUT_NOT_SOLVER_EVIDENCE'-or[IO.File]::ReadAllText($counter)-ne'1'){throw 'Completed output changed or computation restarted'}
 if(Test-Path -LiteralPath (Join-Path $package.artifact_run_dir retention_actions.json)){throw 'Retention ran before accounting reconciliation'}
}
Write-RunJson -Path (Join-Path $Root evidence.json) -Value @{run=$package.artifact_run_dir;result=$context.result_path;lease_id=$session.lease_id;committed_new_bytes=$session.committed_new_bytes}
'PUBLIC_DEFERRED_ACCOUNTING=PASS'
""",encoding='utf-8',newline='\n')
            result=subprocess.run([PWSH,'-NoProfile','-File',str(script),str(owner),str(ROOT),sys.executable,str(artifacts),str(root)],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=45)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('PUBLIC_DEFERRED_ACCOUNTING=PASS',result.stdout)
            evidence=json.loads((root/'evidence.json').read_text(encoding='utf-8-sig'))
            protection=load_capacity_protection_leases(artifacts)
            self.assertEqual(protection['committed_new_bytes'],1048576)
            self.assertIn(Path(evidence['run']).resolve(),protection['protected_paths'])
            ledger=load_capacity_ledger(artifacts)
            self.assertEqual(next(row for row in ledger['objects'] if row['path']==str(Path(evidence['run']).relative_to(artifacts)).replace('\\','/'))['status'],'writing')
