[CmdletBinding()]
param(
 [Parameter(Mandatory)][string]$RunPath,
 [switch]$ManualGuiConfirmed,
 [string]$PythonExe=''
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$repoRoot=(Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$run=(Resolve-Path -LiteralPath $RunPath).Path
$planPath=Join-Path $run 'inputs/gui_replay_plan.json'
if(-not(Test-Path -LiteralPath $planPath -PathType Leaf)){throw 'GUI replay plan is missing; finalize refused before allocation'}
$configPath=Join-Path $run 'run_config.json'
if(-not(Test-Path -LiteralPath $configPath -PathType Leaf)){throw 'GUI replay run config is missing'}
$config=Get-Content -LiteralPath $configPath -Raw -Encoding UTF8|ConvertFrom-Json
if($config.project-ne'dual_pressure_rectilinear_ion_processor'-or$config.mode-ne'native_gui_replay'){
 throw 'Finalize requires an independently prepared native_gui_replay run'
}
$plan=Get-Content -LiteralPath $planPath -Raw -Encoding UTF8|ConvertFrom-Json
$baseline=(Resolve-Path -LiteralPath $plan.baseline_run).Path
if($baseline-eq$run){throw 'GUI replay cannot finalize its baseline run'}
. (Join-Path $repoRoot 'common/require_powershell7.ps1')
. (Join-Path $repoRoot 'common/contracts/run_artifact_support.ps1')
if(-not $PythonExe){$PythonExe=Join-Path $repoRoot '.venv/Scripts/python.exe'}
$capacity=$null;$lease=$null;$published=$false;$accepted=$false
$savedPythonPath=$env:PYTHONPATH;$env:PYTHONPATH=$repoRoot
Push-Location $repoRoot
try {
 $profileJson=& $PythonExe -c 'import json,sys; from pathlib import Path; from projects.dual_pressure_rectilinear_ion_processor.analysis.batching import frozen_runtime_profile; print(json.dumps(frozen_runtime_profile(Path(sys.argv[1]),allow_legacy=True)))' $run
 if($LASTEXITCODE-ne0){throw 'Replay frozen runtime profile is invalid'}
 $profile=$profileJson|ConvertFrom-Json
 if($profile.retention_class-ne'solver_review'){throw 'Replay requires the frozen solver_review profile'}
 $protectedPaths=@($baseline)
 $committed=$profile.committed_new_bytes
 $guiBudget=Join-Path $run 'inputs/gui_execution_budget.json'
 if(Test-Path -LiteralPath $guiBudget){$committed=(Get-Content $guiBudget -Raw|ConvertFrom-Json).committed_new_bytes}
 $resident=[long](Get-ChildItem -LiteralPath $run -Recurse -File|Measure-Object -Property Length -Sum).Sum
 $committed=[long][Math]::Max(64MB,($committed-$resident))
 $capacity=Enter-ArtifactWorkflowCapacitySession -Python $PythonExe -RepoRoot $repoRoot -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -RunDirectory $run -CommittedNewBytes $committed -ProtectedPaths $protectedPaths
 $lease=Enter-HostExecutionLease -Role GATE -Stage postprocess
 $arguments=@('-m','projects.dual_pressure_rectilinear_ion_processor.analysis.functional','finalize-replay','--run',$run)
 if($ManualGuiConfirmed){$arguments+='--manual-gui-confirmed'}
 & $PythonExe @arguments
 $analysisExit=$LASTEXITCODE
 $comparisonPath=Join-Path $run 'results/gui_comparison.json'
 if(-not(Test-Path -LiteralPath $comparisonPath -PathType Leaf)){throw "Replay comparison was not published; action exit=$analysisExit"}
 $comparison=Get-Content -LiteralPath $comparisonPath -Raw -Encoding UTF8|ConvertFrom-Json
 $summaryPath=Join-Path $run 'summary.json'
 $summary=Get-Content -LiteralPath $summaryPath -Raw -Encoding UTF8|ConvertFrom-Json
 if($comparison.role-ne'ion_processor_gui_replay_comparison'-or$summary.role-ne'ion_processor_functional_summary'){
  throw 'Replay comparison or measured physical summary role is invalid'
 }
 if([bool]$comparison.gui_visual_review-ne[bool]$ManualGuiConfirmed){throw 'Manual GUI evidence flag differs from explicit confirmation'}
 $accepted=$analysisExit-eq0-and$summary.status-eq'success'-and$summary.functional_status-in@('functional_pass','exploration_pass')
 $null=Apply-RunArtifactRetention -Python $PythonExe -RepoRoot $repoRoot -RunConfig $configPath
 $outputs=@(Get-ChildItem -LiteralPath $run -Recurse -File|Where-Object{$_.Name-notin@('run_manifest.json','run_config.json')-and-not$_.Name.StartsWith('.')}|ForEach-Object{$_.FullName})
 $status=$(if($accepted){'success'}else{'failed'})
 Write-RunManifest -Python $PythonExe -RepoRoot $repoRoot -RunConfig $configPath -Status $status -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
 & $PythonExe -m common.contracts.verify_run_manifest (Join-Path $run 'run_manifest.json') --require-status $status --require-project dual_pressure_rectilinear_ion_processor --require-local-run-config
 if($LASTEXITCODE-ne0){throw 'Final GUI replay manifest verification failed'}
 Exit-ArtifactWorkflowCapacitySession -Python $PythonExe -RepoRoot $repoRoot -Session $capacity|Out-Null
 $capacity=$null
 & $PythonExe -m common.contracts.run_capacity_lifecycle --action seal-stopped-payload --artifact-root (Join-Path $workspaceRoot 'artifacts') --run-config $configPath --owner dual_pressure_rectilinear_ion_processor --confirm-writing-stopped --retention-reason 'Retain independent GUI replay field references, workbench and measured comparison'
 if($LASTEXITCODE-ne0){throw 'Final GUI replay payload sealing failed'}
 $published=$true
 Write-Output "GUI_REPLAY_FINALIZED STATUS=$(if($accepted){'success'}else{'failed'}) MANUAL_GUI_CONFIRMED=$([bool]$ManualGuiConfirmed) RUN=$run"
 if(-not$accepted){throw 'Measured replay or physical acceptance failed; physical summary and comparison preserved'}
} finally {
 if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $(if($published-and$accepted){'success'}else{'failed'}) -RunId $config.run_id}
 if($null-ne$capacity){Exit-ArtifactWorkflowCapacitySession -Python $PythonExe -RepoRoot $repoRoot -Session $capacity|Out-Null}
 $env:PYTHONPATH=$savedPythonPath
 Pop-Location
}
