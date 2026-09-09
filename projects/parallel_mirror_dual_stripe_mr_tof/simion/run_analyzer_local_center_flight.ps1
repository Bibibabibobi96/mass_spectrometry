[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$WorkbenchRunPath,
  [ValidateSet('center_screening','center_refined','center_precision')][string]$TrajectoryProfile='center_screening',
  [string]$RunId='',
  [string]$SimionExe='',
  [string]$PythonExe=''
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$simion=if($SimionExe){[IO.Path]::GetFullPath($SimionExe)}else{Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
$workbenchRun=(Resolve-Path -LiteralPath $WorkbenchRunPath).Path
$workbenchManifest=Join-Path $workbenchRun 'run_manifest.json'
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $workbenchManifest --require-status success --require-project $projectId --require-mode analyzer_local_replacement_workbench
if($LASTEXITCODE-ne0){throw 'Local-replacement Workbench manifest verification failed.'}
$iob=Join-Path $workbenchRun 'simion\mrtof_local_replacement.iob'
$workbenchConfig=Get-Content -Raw -LiteralPath (Join-Path $workbenchRun 'run_config.json')|ConvertFrom-Json -Depth 40
$operatingManifest=(Resolve-Path -LiteralPath ([string]$workbenchConfig.inputs.operating_run_manifest)).Path
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $operatingManifest --require-status success --require-project $projectId
if($LASTEXITCODE-ne0){throw 'Operating-point manifest verification failed.'}
$operatingRun=Split-Path -Parent $operatingManifest
$materializationSource=Join-Path $operatingRun 'results\two_prism_trial_materialization.json'
$contract=Get-Content -Raw -LiteralPath (Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\config\simion_candidate_two_zone.json')|ConvertFrom-Json -Depth 50
$profile=$contract.simion.trajectory_profiles.$TrajectoryProfile
if($null-eq$profile){throw "Trajectory profile is absent: $TrajectoryProfile"}
$maximumStep=[double]$profile.maximum_step_us
if($maximumStep-le0){throw 'Trajectory maximum step must be positive.'}
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+"__sim__simion__mrtof-local-center-$TrajectoryProfile-n1"}
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") -RunId $RunId -Project $projectId -Mode 'analyzer_local_replacement_center_flight' -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass compact
$resultDir=$package.result_dir;$logDir=$package.log_dir;$runConfig=$package.run_config;$summary=$package.summary
$terminalized=$false;$failureStage='preflight';$lease=$null;$hostOutcome='failed'
try {
  $materialization=Copy-VerifiedRunInput -Source $materializationSource -Destination (Join-Path $package.input_dir 'two_prism_trial_materialization.json')
  $boundFiles=@($iob)
  $manifestDocument=Get-Content -Raw -LiteralPath $workbenchManifest|ConvertFrom-Json -Depth 40
  foreach($record in @($manifestDocument.outputs)){
    $path=[string]$record.path
    if($path -like "$workbenchRun\simion\*"){$boundFiles+=$path}
  }
  $boundFiles=@($boundFiles|Sort-Object -Unique)
  foreach($path in $boundFiles){if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Workbench-bound file is missing: $path"}}
  $before=@{};foreach($path in $boundFiles){$before[$path]=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash}
  $configuration=Get-Content -Raw -LiteralPath $runConfig|ConvertFrom-Json -AsHashtable
  $configuration.inputs=[ordered]@{workbench_run_manifest=$workbenchManifest;operating_run_manifest=$operatingManifest;operating_iob=$iob;operating_point_materialization=$materialization}
  $configuration.parameters=[ordered]@{particle_count=1;trajectory_profile=$TrajectoryProfile;maximum_step_us=$maximumStep;prism_mode='static_injection_only';mesh_role='global_1mm_with_local_0p5mm_replacements'}
  Write-RunJson -Path $runConfig -Depth 20 -Value $configuration
  $failureStage='native_center_flight';$lease=Enter-HostExecutionLease -Role SIMION -RunId $RunId
  $rawLog=Join-Path $logDir 'native_center_flight.log'
  Push-Location -LiteralPath (Split-Path -Parent $iob)
  try {
    & $simion --nogui --noprompt fly --adjustable "maximum_step_us=$([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$maximumStep))" $iob 2>&1|Tee-Object -FilePath $rawLog
    if($LASTEXITCODE-ne0){throw 'SIMION local-replacement center flight failed.'}
  } finally {Pop-Location}
  foreach($path in $boundFiles){if((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash-ne$before[$path]){throw "Read-only flight changed a Workbench-bound file: $path"}}
  $failureStage='event_analysis';$result=Join-Path $resultDir 'analyzer_local_center_result.json'
  Push-Location -LiteralPath $repoRoot
  try {
    $saved=$env:PYTHONPATH;$env:PYTHONPATH=$repoRoot
    & $python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_center_result --log $rawLog --materialization $materialization --output $result
    if($LASTEXITCODE-ne0){throw 'Local center event analysis failed.'}
  } finally {$env:PYTHONPATH=$saved;Pop-Location}
  $observed=Get-Content -Raw -LiteralPath $result|ConvertFrom-Json -Depth 30
  Write-RunJson -Path $summary -Depth 20 -Value $observed
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success -Software @('SIMION 2020','Python 3.11') -Outputs @($summary,$rawLog,$result,$retention)
  $terminalized=$true;$hostOutcome='success';Write-Host "MRTOF_LOCAL_CENTER_FLIGHT=PASS RUN_ID=$RunId"
} catch {
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_analyzer_local_replacement_center_flight' -Reason $_.Exception.Message -Software @('SIMION 2020','Python 3.11') -Status failed -FailureStage $failureStage;$terminalized=$true}
  throw
} finally {
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $hostOutcome -RunId $RunId}
}
