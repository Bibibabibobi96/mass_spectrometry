[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$GeometryReviewRunPath,
  [ValidateSet('accelerator_focus_center_fly2','accelerator_focus_bunch_fly2')][string]$SourceKey='accelerator_focus_center_fly2',
  [string]$BaselineContractPath='',
  [string]$RunId='',
  [string]$SimionExe='',
  [string]$PythonExe=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

function Copy-RequiredInput {
  param([string]$Source,[string]$Destination,[string]$Label)
  if(-not(Test-Path -LiteralPath $Source -PathType Leaf)){throw "$Label is missing: $Source"}
  Copy-VerifiedRunInput -Source $Source -Destination $Destination
}
function Invoke-ProjectPython {
  param([string[]]$Arguments)
  Push-Location -LiteralPath $repoRoot
  $saved=$env:PYTHONPATH
  try{$env:PYTHONPATH=$repoRoot;& $python @Arguments;if($LASTEXITCODE -ne 0){throw "Python failed: $($Arguments -join ' ')"}}
  finally{$env:PYTHONPATH=$saved;Pop-Location}
}

$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$simion=if($SimionExe){[IO.Path]::GetFullPath($SimionExe)}else{Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
if(-not(Test-Path -LiteralPath $simion -PathType Leaf)){throw "SIMION executable is missing: $simion"}
$baselinePath=if($BaselineContractPath){(Resolve-Path -LiteralPath $BaselineContractPath).Path}else{Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\config\simion_candidate_two_zone.json'}
$baseline=Get-Content -LiteralPath $baselinePath -Raw -Encoding UTF8|ConvertFrom-Json
$countKey=if($SourceKey-eq'accelerator_focus_center_fly2'){'center_particle_count'}else{'candidate_bunch_particle_count'}
$expectedCount=[int]$baseline.particle_source.$countKey
if($expectedCount -le 0){throw 'accelerator focus source has invalid particle count'}
$geometryRun=(Resolve-Path -LiteralPath $GeometryReviewRunPath).Path
$geometrySimion=Join-Path $geometryRun 'simion'
$geometryResults=Join-Path $geometryRun 'results'
$sourceManifestPath=Join-Path $geometrySimion 'prototype_input_manifest.json'
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+"__sim__simion__mrtof-accelerator-focus-n$expectedCount"}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'two_zone_accelerator_first_time_focus' -Software @('SIMION 2020','Python 3.11') `
  -RetentionContractEnabled -RetentionClass solver_review -RetentionReason 'Independent accelerator z=0 first-time-focus evidence.' `
  -AdditionalDirectories @('simion') -UseShortExecutionPath
$runDir=$package.run_dir;$resultDir=$package.result_dir;$logDir=$package.log_dir;$solverDir=Join-Path $runDir 'simion'
$runConfig=$package.run_config;$summary=$package.summary;$artifactRoot=Join-Path $workspaceRoot 'artifacts'
$terminalized=$false;$failureStage='preflight';$hostExecutionOutcome='failed';$lease=$null
try{
  $names=@('mrtof_three_component_candidate.iob','mrtof_analyzer.pa0','mrtof_accelerator.pa0','mrtof_detector.pa#',
    'mrtof_three_component_candidate.operating_point.lua','mrtof_three_component_candidate.voltage_map.lua','simion_prototype_contract.json')
  $geometryReview=Join-Path $geometrySimion 'three_component_geometry_review.json'
  $structureReport=Join-Path $geometryResults 'iob_structure_report.txt'
  $sourceBuilderPath=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\materialize_accelerator_focus_source.py'
  $sources=@($sourceManifestPath,$baselinePath,$geometryReview,$structureReport,$sourceBuilderPath,
    (Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\simion\mrtof_accelerator_focus.lua'),
    (Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\simion\run_iob_flight.lua'),
    (Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\accelerator_focus_simion_analysis.py'))
  foreach($name in $names){$sources+=(Join-Path $geometrySimion $name)}
  [int64]$copyBytes=0;foreach($path in $sources){if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "focus input is missing: $path"};$copyBytes+=(Get-Item -LiteralPath $path).Length}
  $failureStage='capacity_preflight'
  $startup=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -RequiredHeadroomBytes $copyBytes -ProtectedPaths @($package.artifact_run_dir)
  $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json';Write-RunJson -Path $startupPath -Depth 14 -Value $startup
  $failureStage='freeze_reviewed_pa_iob'
  foreach($name in $names){Copy-RequiredInput (Join-Path $geometrySimion $name) (Join-Path $solverDir $name) "reviewed $name"|Out-Null}
  Copy-RequiredInput $sourceManifestPath (Join-Path $solverDir 'prototype_input_manifest.json') 'source manifest'|Out-Null
  Copy-RequiredInput $geometryReview (Join-Path $solverDir 'three_component_geometry_review.json') 'geometry review receipt'|Out-Null
  Copy-RequiredInput $structureReport (Join-Path $solverDir 'iob_structure_report.txt') 'IOB structure report'|Out-Null
  $frozenBaseline=Copy-RequiredInput $baselinePath (Join-Path $solverDir 'simion_candidate_two_zone.json') 'current baseline contract'
  $sourceBuilder=Copy-RequiredInput $sourceBuilderPath (Join-Path $solverDir 'materialize_accelerator_focus_source.py') 'focus source builder'
  $focusFly2=Join-Path $solverDir 'mrtof_three_component_candidate.fly2';$sourceReceipt=Join-Path $resultDir 'accelerator_focus_source_receipt.json'
  $failureStage='materialize_axial_source';Invoke-ProjectPython -Arguments @($sourceBuilder,'--contract',$frozenBaseline,'--reviewed-contract',(Join-Path $solverDir 'simion_prototype_contract.json'),'--source-key',$SourceKey,'--output',$focusFly2,'--receipt',$sourceReceipt)
  Copy-RequiredInput (Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\simion\mrtof_accelerator_focus.lua') (Join-Path $solverDir 'mrtof_three_component_candidate.lua') 'focus program'|Out-Null
  $launcher=Copy-RequiredInput (Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\simion\run_iob_flight.lua') (Join-Path $solverDir 'run_iob_flight.lua') 'flight launcher'
  $analyzer=Copy-RequiredInput (Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\accelerator_focus_simion_analysis.py') (Join-Path $solverDir 'accelerator_focus_simion_analysis.py') 'focus analyzer'
  $config=Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $sourceIdentity=Get-Content -LiteralPath $sourceReceipt -Raw -Encoding UTF8|ConvertFrom-Json
  $config.inputs=[ordered]@{reviewed_iob=(Join-Path $solverDir 'mrtof_three_component_candidate.iob');reviewed_accelerator_pa0=(Join-Path $solverDir 'mrtof_accelerator.pa0');geometry_review_receipt=(Join-Path $solverDir 'three_component_geometry_review.json');iob_structure_report=(Join-Path $solverDir 'iob_structure_report.txt');geometry_source_manifest=(Join-Path $solverDir 'prototype_input_manifest.json');consumed_fly2=$focusFly2;baseline_contract=$frozenBaseline;reviewed_contract=(Join-Path $solverDir 'simion_prototype_contract.json');source_receipt=$sourceReceipt}
  $config.parameters.source_key=$SourceKey;$config.parameters.particle_count=$expectedCount;$config.parameters.source_sha256=$sourceIdentity.fly2_sha256
  Write-RunJson -Path $runConfig -Value $config
  $failureStage='native_accelerator_focus';$lease=Enter-HostExecutionLease -Role SIMION -RunId $RunId
  Push-Location -LiteralPath $solverDir
  try{& $simion '--nogui' '--noprompt' 'lua' $launcher (Join-Path $solverDir 'mrtof_three_component_candidate.iob') 2>&1|Tee-Object -FilePath (Join-Path $logDir 'native_accelerator_focus.log');if($LASTEXITCODE -ne 0){throw 'SIMION accelerator focus flight failed'}}finally{Pop-Location}
  $rawLog=Join-Path $logDir 'native_accelerator_focus.log';$analysis=Join-Path $resultDir 'accelerator_focus_analysis.json'
  $failureStage='focus_analysis';Invoke-ProjectPython -Arguments @($analyzer,$rawLog,$frozenBaseline,$analysis,'--expected-count',"$expectedCount")
  $analysisValue=Get-Content -LiteralPath $analysis -Raw -Encoding UTF8|ConvertFrom-Json
  Write-RunJson -Path $summary -Value ([ordered]@{schema_version=1;role='mrtof_two_zone_accelerator_first_time_focus';status='success';qualification='candidate_prototype_numeric_focus_only';particle_count=$expectedCount;focus_particle_count=$analysisValue.focus_particle_count;timing=$analysisValue.timing})
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $failureStage='capacity_terminal';$maximum=[int64](Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File|Measure-Object Length -Sum).Sum
  $terminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -ProtectedPaths @($package.artifact_run_dir) -KnownMeasuredBytes ([int64]$startup.measured_after_bytes) -MaximumNewArtifactBytes $maximum
  $terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success -Software @('SIMION 2020','Python 3.11') -Outputs @($summary,$rawLog,$analysis,$sourceReceipt,$startupPath,$terminalPath,$retention)
  $terminalized=$true;$hostExecutionOutcome='success';Write-Host "MRTOF_ACCELERATOR_FOCUS_FLIGHT=PASS RUN_ID=$RunId"
}catch{
  if(-not $terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_two_zone_accelerator_first_time_focus' -Reason $_.Exception.Message -Software @('SIMION 2020','Python 3.11') -Status failed -FailureStage $failureStage;$terminalized=$true}
  throw
}finally{
  if(-not $terminalized -and(Test-Path -LiteralPath $runConfig -PathType Leaf)){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_two_zone_accelerator_first_time_focus' -Reason 'Runner stopped before terminal evidence publication.' -Software @('SIMION 2020','Python 3.11') -Status interrupted -FailureStage $failureStage;$hostExecutionOutcome='interrupted'}
  if($null -ne $lease){Exit-HostExecutionLease -Lease $lease -Outcome $hostExecutionOutcome -RunId $RunId}
  Remove-RunPackageExecutionAlias -Package $package
}
