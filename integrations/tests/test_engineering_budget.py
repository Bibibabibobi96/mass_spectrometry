"""Real PowerShell budget admission without solver execution."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 unavailable")
class EngineeringBudgetTests(unittest.TestCase):
    def test_shared_budget_and_actual_entry_loaders(self):
        code = r"""param($RepoRoot,$Temporary)
$ErrorActionPreference='Stop'
$relative='integrations';$sharedRuntime='integrations/runtime'
foreach($entry in @('integrations/workflows/local_frontend/execute.ps1','integrations/workflows/cooled_frontend/execute.ps1')){
 Remove-Item Function:Initialize-IntegrationStageBudget -ErrorAction SilentlyContinue
 $tokens=$null;$errors=$null
 $ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $RepoRoot $entry),[ref]$tokens,[ref]$errors)
 if($errors.Count){throw $errors[0]}
 foreach($statement in $ast.EndBlock.Statements){
  if($statement-is[Management.Automation.Language.PipelineAst]){
   $command=$statement.PipelineElements[0]
   if($command-is[Management.Automation.Language.CommandAst]-and$command.InvocationOperator-eq'Dot'){Invoke-Expression $command.Extent.Text}
  }
 }
 if(-not(Get-Command Initialize-IntegrationStageBudget -ErrorAction SilentlyContinue)){throw "missing entry budget: $entry"}
}
. (Join-Path $RepoRoot 'integrations/runtime/engineering_budget.ps1')
$document=@{schema_version=2;role='integration_resolved_engineering_budget';integration_id='instrument_assembly';workflow_id='fixture';retention_class='solver_review';particle_count=100;stage_limits=@{transport=@{solver='simion';automatic_retry_count=0;wall_clock_seconds=60;transient_run_directory_bytes=1000;process_tree_working_set_bytes=2000;minimum_system_available_memory_bytes=1;compact_final_retained_bytes=800}}}
$source=Join-Path $Temporary budget.json
$document|ConvertTo-Json -Depth 20|Set-Content -LiteralPath $source
function Get-RunFileSha256 { throw 'budget must reuse the public copier identity without rehashing' }
$selection=@{ResolvedBudget=$source;ExpectedIntegrationId='instrument_assembly';ExpectedWorkflowId='fixture';StageId='transport';Solver='simion'}
$inputs=Join-Path $Temporary inputs
$frozen=Initialize-IntegrationStageBudget @selection -InputDir $inputs -ExpectedRetentionClass solver_review
if($frozen.limits.wall_clock_seconds-ne60){throw 'frozen budget projection differs'}
if($frozen.resolved_budget_sha256-cne(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash){throw 'frozen budget identity differs'}
if(@(Get-ChildItem $inputs -File).Count-ne1){throw 'unexpected budget artifacts'}
$loaded=Get-Content $frozen.frozen_budget -Raw|ConvertFrom-Json
$loaded.stage_limits|Add-Member -NotePropertyName workbench -NotePropertyValue $loaded.stage_limits.transport
$selectionFromDocument=@{Document=$loaded;ExpectedIntegrationId='instrument_assembly';ExpectedWorkflowId='fixture';Solver='simion';ExpectedRetentionClass='solver_review'}
foreach($stage in @('transport','workbench')){
 $limits=Get-IntegrationStageBudget @selectionFromDocument -StageId $stage
 if($limits.wall_clock_seconds-ne60){throw 'same-document stage projection differs'}
}
$unexpected=$document|ConvertTo-Json -Depth 20|ConvertFrom-Json
$unexpected.stage_limits.transport|Add-Member -NotePropertyName ignored_setting -NotePropertyValue 1
$unexpectedRejected=$false
try{$null=Get-IntegrationStageBudget @selectionFromDocument -Document $unexpected -StageId transport}catch{$unexpectedRejected=$true}
if(-not$unexpectedRejected){throw 'schema2 stage accepted an unsupported field'}
$missingRejected=$false
try{$null=Get-IntegrationStageBudget @selectionFromDocument -StageId missing}catch{$missingRejected=$true}
if(-not$missingRejected){throw 'missing second stage accepted'}
if(@(Get-ChildItem $inputs -File).Count-ne1){throw 'stage selection created a duplicate frozen budget'}
# Existing connection caller remains schema1 and defaults to compact.
$document.schema_version=1;$document.Remove('workflow_id');$document.connection_profile_id='fixture';$document.retention_class='compact'
$document|ConvertTo-Json -Depth 20|Set-Content -LiteralPath $source
$connection=@{ResolvedBudget=$source;ExpectedIntegrationId='instrument_assembly';ExpectedConnectionProfileId='fixture';StageId='transport';Solver='simion'}
$null=Initialize-IntegrationStageBudget @connection -InputDir (Join-Path $Temporary connection)
foreach($mutation in @('schema','owner','solver','retry','positive','retention','particles','stage')){
 $bad=$document|ConvertTo-Json -Depth 20|ConvertFrom-Json -AsHashtable
 switch($mutation){
  schema {$bad.schema_version=2}
  owner {$bad.integration_id='wrong'}
  solver {$bad.stage_limits.transport.solver='comsol'}
  retry {$bad.stage_limits.transport.automatic_retry_count=1}
  positive {$bad.stage_limits.transport.wall_clock_seconds=0}
  retention {$bad.retention_class='unknown'}
  particles {$bad.particle_count=0}
  stage {$bad.stage_limits=@{}}
 }
 $bad|ConvertTo-Json -Depth 20|Set-Content -LiteralPath $source
 $rejected=$false
 try{$null=Initialize-IntegrationStageBudget @connection -InputDir (Join-Path $Temporary $mutation)}catch{$rejected=$true}
 if(-not$rejected){throw "invalid budget accepted: $mutation"}
}
'BUDGET_BEHAVIOR=PASS'
"""
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "budget.ps1"
            script.write_text(code, encoding="utf-8")
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(script), str(REPO), temporary],
                cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=60,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BUDGET_BEHAVIOR=PASS", result.stdout)
