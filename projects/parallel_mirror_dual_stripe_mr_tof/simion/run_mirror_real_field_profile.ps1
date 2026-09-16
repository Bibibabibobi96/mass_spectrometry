[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$ExactKRunPath,
  [Parameter(Mandatory)][string]$CoarseWorkbenchRunPath,
  [Parameter(Mandatory)][string]$CoarsePrewarmRunPath,
  [Parameter(Mandatory)][string]$FineWorkbenchRunPath,
  [Parameter(Mandatory)][string]$FinePrewarmRunPath,
  [double]$ProbeYmm=280.0,
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
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__analysis__simion__mrtof-mirror-axis-field-profile'}
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
$artifactRoot=Join-Path $workspaceRoot 'artifacts'
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $artifactRoot "projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'grounded_auxiliary_mirror_axis_field_profile' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass compact `
  -AdditionalDirectories @('simion') -UseShortExecutionPath
$runDir=$package.run_dir;$resultDir=$package.result_dir;$solverDir=Join-Path $runDir 'simion'
$runConfig=$package.run_config;$summary=$package.summary;$terminalized=$false;$lease=$null;$hostOutcome='failed';$failureStage='preflight'
function Invoke-ProjectPython([string[]]$Arguments){Push-Location $repoRoot;$saved=$env:PYTHONPATH;try{$env:PYTHONPATH=$repoRoot;& $python @Arguments;if($LASTEXITCODE-ne0){throw "Python failed: $($Arguments-join' ')"}}finally{$env:PYTHONPATH=$saved;Pop-Location}}
function ArtifactPath([string]$Path){$full=[IO.Path]::GetFullPath($Path);$exec=[IO.Path]::GetFullPath([string]$package.run_dir).TrimEnd([char[]]@(92,47));$artifact=[IO.Path]::GetFullPath([string]$package.artifact_run_dir).TrimEnd([char[]]@(92,47));if($full.StartsWith($exec,[StringComparison]::OrdinalIgnoreCase)){return $artifact+$full.Substring($exec.Length)};$full}
try{
  $roots=@($ExactKRunPath,$CoarseWorkbenchRunPath,$CoarsePrewarmRunPath,$FineWorkbenchRunPath,$FinePrewarmRunPath)|ForEach-Object{(Resolve-Path -LiteralPath $_).Path}
  foreach($root in $roots){& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') (Join-Path $root 'run_manifest.json') --require-status success;if($LASTEXITCODE-ne0){throw "Input manifest failed: $root"}}
  $failureStage='capacity_preflight'
  $startup=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -ProtectedPaths (@($package.artifact_run_dir)+$roots)
  $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json';Write-RunJson -Path $startupPath -Depth 14 -Value $startup
  $failureStage='materialize_grounded_auxiliary_fields'
  $cacheRoot=Join-Path $artifactRoot 'common\simion\pa_family_cache'
  $directories=@((Join-Path $solverDir 'coarse'),(Join-Path $solverDir 'fine'))
  $prewarms=@($roots[2],$roots[4])
  for($index=0;$index-lt2;$index++){
    New-Item -ItemType Directory -Path $directories[$index] -Force|Out-Null
    Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.local_operating_pa_cache','--action','materialize',
      '--identity-input',(Join-Path $prewarms[$index] 'results\local_operating_pa_cache_identity.json'),'--cache-root',$cacheRoot,
      '--destination-directory',$directories[$index])
  }
  $failureStage='prepare_samples'
  Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_profile','prepare',
    '--coarse-workbench',$roots[1],'--fine-workbench',$roots[3],'--output-directory',$resultDir,'--probe-y-mm',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$ProbeYmm)))
  $contractPath=Join-Path $resultDir 'profile_contract.json';$contract=Get-Content $contractPath -Raw|ConvertFrom-Json -Depth 20
  $files=@{negative_mirror='local_negative_mirror.pa';negative_bridge='local_negative_bridge.pa';central='local_central.pa';positive_bridge='local_positive_bridge.pa';positive_mirror='local_positive_mirror.pa'}
  $compare=Join-Path $repoRoot 'common\simion\compare_pa_fields_at_samples.lua'
  $lease=Enter-HostExecutionLease -Role SIMION -Stage mirror_field_sampling -RunId $RunId
  foreach($region in $contract.regions){
    $originA=(@($region.coarse_origin_mm)|ForEach-Object{[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$_)})-join','
    $originB=(@($region.fine_origin_mm)|ForEach-Object{[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$_)})-join','
    $output=Join-Path $resultDir ("comparison_{0}.csv"-f$region.label)
    & $simion --nogui --noprompt lua $compare (Join-Path $directories[0] $files[[string]$region.label]) $originA `
      (Join-Path $directories[1] $files[[string]$region.label]) $originB identity identity ([string]$region.sample_csv) $output
    if($LASTEXITCODE-ne0){throw "SIMION field sampling failed: $($region.label)"}
  }
  Exit-HostExecutionLease -Lease $lease -Outcome success -RunId $RunId;$lease=$null
  $failureStage='analyze'
  $analysis=Join-Path $resultDir 'mirror_axis_field_comparison.json'
  Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_profile','analyze',
    '--contract',$contractPath,'--exact-k-run',$roots[0],'--samples-directory',$resultDir,'--output',$analysis)
  $report=Get-Content $analysis -Raw|ConvertFrom-Json -Depth 30
  Write-RunJson -Path $summary -Depth 20 -Value ([ordered]@{schema_version=1;role=$report.role;status='success';qualification=$report.qualification;probe_y_mm=$ProbeYmm;coarse_mesh_mm_per_gu=$report.coarse_mesh_mm_per_gu;fine_mesh_mm_per_gu=$report.fine_mesh_mm_per_gu;global_metrics=$report.global_metrics;region_metrics=$report.region_metrics})
  $configuration=Get-Content $runConfig -Raw|ConvertFrom-Json -AsHashtable
  $configuration.inputs=[ordered]@{exact_k_run_manifest=Join-Path $roots[0] 'run_manifest.json';coarse_workbench_manifest=Join-Path $roots[1] 'run_manifest.json';coarse_prewarm_manifest=Join-Path $roots[2] 'run_manifest.json';fine_workbench_manifest=Join-Path $roots[3] 'run_manifest.json';fine_prewarm_manifest=Join-Path $roots[4] 'run_manifest.json'}
  $configuration.parameters=[ordered]@{probe_y_mm=$ProbeYmm;sample_count=639;stripes_and_prisms_grounded=$true;lifecycle_stage='terminal'}
  Write-RunJson -Path $runConfig -Depth 20 -Value $configuration
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $terminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -ProtectedPaths (@($package.artifact_run_dir)+$roots)
  $terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  $outputs=@($summary,$contractPath,$analysis,$startupPath,$terminalPath,$retention)+@(Get-ChildItem $resultDir -Filter 'comparison_*.csv'|ForEach-Object{$_.FullName})
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success -Software @('SIMION 2020','Python 3.11') -Outputs ($outputs|ForEach-Object{ArtifactPath $_})|Out-Null
  $terminalized=$true;$hostOutcome='success';Write-Host "MRTOF_MIRROR_FIELD_PROFILE=PASS RUN_ID=$RunId"
}catch{
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome failed -RunId $RunId;$lease=$null}
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_grounded_auxiliary_mirror_axis_field_profile' -Reason $_.Exception.Message -Software @('SIMION 2020','Python 3.11') -FailureStage $failureStage;$terminalized=$true}
  throw
}finally{
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $hostOutcome -RunId $RunId}
  Remove-RunPackageExecutionAlias -Package $package
}
