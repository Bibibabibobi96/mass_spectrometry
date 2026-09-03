[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$GeometryReviewRunPath,
  [string]$RunId = '',
  [string]$SimionExe = '',
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# This runner consumes a completed, separately GUI-reviewable IOB package. It
# is intentionally N=1 and reports the complete terminal event chain only.
function Copy-RequiredRunInput {
  param([Parameter(Mandatory)][string]$Source,[Parameter(Mandatory)][string]$Destination,[Parameter(Mandatory)][string]$Label)
  if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) { throw "$Label is missing: $Source" }
  Copy-VerifiedRunInput -Source $Source -Destination $Destination
}
function Invoke-MrtofPython { param([Parameter(Mandatory)][string[]]$Arguments)
  Push-Location -LiteralPath $repoRoot
  $savedPythonPath=$env:PYTHONPATH
  try { $env:PYTHONPATH=$repoRoot; & $python @Arguments; if($LASTEXITCODE -ne 0){throw "MR-TOF Python failed: $($Arguments -join ' ')"} }
  finally { $env:PYTHONPATH=$savedPythonPath; Pop-Location }
}
function Invoke-MrtofSimionStep { param([Parameter(Mandatory)][string]$Stage,[Parameter(Mandatory)][string[]]$Arguments)
  Push-Location -LiteralPath $solverDir
  try { & $simion @Arguments 2>&1 | Tee-Object -FilePath (Join-Path $logDir "$Stage.log"); if($LASTEXITCODE -ne 0){throw "SIMION stage failed: $Stage"} }
  finally { Pop-Location }
}

$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$simion=if($SimionExe){[IO.Path]::GetFullPath($SimionExe)}else{Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
if(-not(Test-Path -LiteralPath $simion -PathType Leaf)){throw "SIMION executable is missing: $simion"}
$geometryRun=(Resolve-Path -LiteralPath $GeometryReviewRunPath).Path
$geometrySimion=Join-Path $geometryRun 'simion'
$geometryResults=Join-Path $geometryRun 'results'
$geometryIob=Join-Path $geometrySimion 'mrtof_three_component_candidate.iob'
$geometryReview=Join-Path $geometrySimion 'three_component_geometry_review.json'
$geometryReport=Join-Path $geometryResults 'iob_structure_report.txt'
$sourceManifest=Join-Path $geometrySimion 'prototype_input_manifest.json'
$sourceFly2=Join-Path $geometrySimion 'mrtof_candidate_center.fly2'
foreach($path in @($geometryIob,$geometryReview,$geometryReport,$sourceManifest,$sourceFly2,
  (Join-Path $geometrySimion 'simion_prototype_contract.json'),
  (Join-Path $geometrySimion 'mrtof_analyzer.pa0'),(Join-Path $geometrySimion 'mrtof_accelerator.pa0'),(Join-Path $geometrySimion 'mrtof_detector.pa#'))){
  if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Completed geometry-review input is missing: $path"}
}
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__fly__simion__mrtof-three-component-center-n1'}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'three_component_candidate_center_flight' -Software @('SIMION 2020','Python 3.11') `
  -RetentionContractEnabled -RetentionClass solver_review -RetentionReason 'N=1 native trajectory event-chain evidence retains the reviewed IOB and raw log.' `
  -AdditionalDirectories @('simion') -UseShortExecutionPath
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir;$logDir=$package.log_dir;$solverDir=Join-Path $runDir 'simion'
$runConfig=$package.run_config;$summary=$package.summary;$artifactRoot=Join-Path $workspaceRoot 'artifacts'
$terminalized=$false;$failureStage='preflight';$hostExecutionOutcome='failed';$hostExecutionLease=$null
try {
  $failureStage='capacity_preflight'
  $frozenSources=@($geometryIob,$geometryReview,$geometryReport,$sourceManifest,$sourceFly2,
    (Join-Path $geometrySimion 'simion_prototype_contract.json'),
    (Join-Path $geometrySimion 'mrtof_analyzer.pa0'),(Join-Path $geometrySimion 'mrtof_accelerator.pa0'),(Join-Path $geometrySimion 'mrtof_detector.pa#'),
    (Join-Path $geometrySimion 'mrtof_three_component_candidate.lua'),(Join-Path $geometrySimion 'mrtof_three_component_candidate.fly2'),
    (Join-Path $geometrySimion 'mrtof_three_component_candidate.operating_point.lua'),(Join-Path $geometrySimion 'mrtof_three_component_candidate.voltage_map.lua'),
    (Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\simion\run_iob_flight.lua'),
    (Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\simion_event_analysis.py'),
    (Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\three_component_simion_flight_manifest.py'))
  [int64]$copyBytes=0;foreach($path in $frozenSources){if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Required flight input is missing: $path"};$copyBytes+=[int64](Get-Item -LiteralPath $path).Length}
  $startup=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -RequiredHeadroomBytes $copyBytes -ProtectedPaths @($package.artifact_run_dir)
  $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json';Write-RunJson -Path $startupPath -Depth 14 -Value $startup
  $failureStage='freeze_reviewed_iob'
  foreach($name in @('mrtof_three_component_candidate.iob','mrtof_three_component_candidate.lua','mrtof_three_component_candidate.fly2','mrtof_three_component_candidate.operating_point.lua','mrtof_three_component_candidate.voltage_map.lua','mrtof_analyzer.pa0','mrtof_accelerator.pa0','mrtof_detector.pa#','three_component_geometry_review.json','prototype_input_manifest.json','simion_prototype_contract.json','mrtof_candidate_center.fly2')){
    Copy-RequiredRunInput -Source (Join-Path $geometrySimion $name) -Destination (Join-Path $solverDir $name) -Label "reviewed $name" | Out-Null
  }
  $frozenReport=Copy-RequiredRunInput -Source $geometryReport -Destination (Join-Path $solverDir 'iob_structure_report.txt') -Label 'reviewed IOB structure report'
  $flightLauncher=Copy-RequiredRunInput -Source (Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\simion\run_iob_flight.lua') -Destination (Join-Path $solverDir 'run_iob_flight.lua') -Label 'IOB flight launcher'
  $eventAnalyzer=Copy-RequiredRunInput -Source (Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\simion_event_analysis.py') -Destination (Join-Path $solverDir 'simion_event_analysis.py') -Label 'event analyzer'
  $receiptWriter=Copy-RequiredRunInput -Source (Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\three_component_simion_flight_manifest.py') -Destination (Join-Path $solverDir 'three_component_simion_flight_manifest.py') -Label 'flight receipt writer'
  if(-not(Test-RunFilesIdentical -Left (Join-Path $solverDir 'mrtof_three_component_candidate.fly2') -Right (Join-Path $solverDir 'mrtof_candidate_center.fly2'))){throw 'IOB companion Fly2 differs from the selected center source.'}
  $config=Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $config.inputs=[ordered]@{geometry_review_run=$geometryRun;reviewed_iob=(Join-Path $package.artifact_run_dir 'simion\mrtof_three_component_candidate.iob');geometry_review=(Join-Path $package.artifact_run_dir 'simion\three_component_geometry_review.json');source_manifest=(Join-Path $package.artifact_run_dir 'simion\prototype_input_manifest.json');source_key='center_fly2';consumed_fly2=(Join-Path $package.artifact_run_dir 'simion\mrtof_three_component_candidate.fly2')};Write-RunJson -Path $runConfig -Value $config
  $failureStage='native_center_flight';$hostExecutionLease=Enter-HostExecutionLease -Role SIMION -RunId $RunId
  Invoke-MrtofSimionStep -Stage 'native_center_flight' -Arguments @('--nogui','--noprompt','lua',$flightLauncher,'--',(Join-Path $solverDir 'mrtof_three_component_candidate.iob'))
  $rawLog=Join-Path $logDir 'native_center_flight.log';$eventAnalysis=Join-Path $resultDir 'center_event_analysis.json'
  $failureStage='event_analysis';Invoke-MrtofPython -Arguments @($eventAnalyzer,$rawLog,$eventAnalysis,'--input-manifest',(Join-Path $solverDir 'prototype_input_manifest.json'),'--source-key','center_fly2')
  $receipt=Join-Path $resultDir 'three_component_center_flight_receipt.json';$failureStage='flight_receipt'
  Invoke-MrtofPython -Arguments @($receiptWriter,'--geometry-review-manifest',(Join-Path $solverDir 'three_component_geometry_review.json'),'--source-input-manifest',(Join-Path $solverDir 'prototype_input_manifest.json'),'--source-key','center_fly2','--raw-log',$rawLog,'--event-analysis',$eventAnalysis,'--consumed-fly2',(Join-Path $solverDir 'mrtof_three_component_candidate.fly2'),'--output',$receipt)
  Write-RunJson -Path $summary -Value ([ordered]@{schema_version=1;role='mrtof_three_component_candidate_center_flight';status='success';qualification='candidate_prototype_event_chain_only';particle_count=1;reason='One reviewed-IOb center source was flown and all terminal events were retained; no resolution claim is made.'})
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $failureStage='capacity_terminal';$maximum=[int64](Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File|Measure-Object Length -Sum).Sum
  $terminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -ProtectedPaths @($package.artifact_run_dir) -KnownMeasuredBytes ([int64]$startup.measured_after_bytes) -MaximumNewArtifactBytes $maximum
  $terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success -Software @('SIMION 2020','Python 3.11') -Outputs @($summary,$rawLog,$eventAnalysis,$receipt,$startupPath,$terminalPath,$retention)
  $terminalized=$true;$hostExecutionOutcome='success';Write-Host "MRTOF_THREE_COMPONENT_CENTER_FLIGHT=PASS RUN_ID=$RunId"
} catch { if(-not $terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_three_component_candidate_center_flight' -Reason $_.Exception.Message -Software @('SIMION 2020','Python 3.11') -Status failed -FailureStage $failureStage -PreserveRawOutputs;$terminalized=$true};throw }
finally { if(-not $terminalized -and(Test-Path -LiteralPath $runConfig -PathType Leaf)){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_three_component_candidate_center_flight' -Reason 'Runner stopped before terminal evidence publication.' -Software @('SIMION 2020','Python 3.11') -Status interrupted -FailureStage $failureStage -PreserveRawOutputs;$hostExecutionOutcome='interrupted'};if($null -ne $hostExecutionLease){Exit-HostExecutionLease -Lease $hostExecutionLease -Outcome $hostExecutionOutcome -RunId $RunId};Remove-RunPackageExecutionAlias -Package $package }
