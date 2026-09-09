[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$GeometryReviewRunPath,
  [Parameter(Mandatory)][ValidateSet('mirror_turn_positive','mirror_turn_negative','central_transport','stripe_mirror_bridge_positive','stripe_mirror_bridge_negative')][string]$Region,
  [Parameter(Mandatory)][ValidateSet(1.0,0.5,0.25)][double]$ScaleFactor,
  [string]$ContractPath='',
  [string]$RunId='',
  [string]$SimionExe='',
  [string]$PythonExe=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

function Invoke-ProjectPython {
  param([Parameter(Mandatory)][string[]]$Arguments)
  Push-Location -LiteralPath $repoRoot
  $saved=$env:PYTHONPATH
  try {
    $env:PYTHONPATH=$repoRoot
    $output=& $python @Arguments
    if($LASTEXITCODE-ne 0){throw "Python stage failed: $($Arguments -join ' ')"}
    return @($output)
  } finally {$env:PYTHONPATH=$saved;Pop-Location}
}

function Invoke-SimionStage {
  param([Parameter(Mandatory)][string]$Stage,[Parameter(Mandatory)][string[]]$Arguments)
  Push-Location -LiteralPath $solverDir
  try {
    & $simion @Arguments 2>&1|Tee-Object -FilePath (Join-Path $logDir "$Stage.log")
    if($LASTEXITCODE-ne 0){throw "SIMION stage failed: $Stage"}
  } finally {Pop-Location}
}

$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$projectRoot=Join-Path $repoRoot "projects\$projectId"
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$simion=if($SimionExe){[IO.Path]::GetFullPath($SimionExe)}else{Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
if(-not(Test-Path -LiteralPath $python -PathType Leaf)){throw "Python executable is missing: $python"}
if(-not(Test-Path -LiteralPath $simion -PathType Leaf)){throw "SIMION executable is missing: $simion"}
$geometryRun=(Resolve-Path -LiteralPath $GeometryReviewRunPath).Path
$geometryManifest=Join-Path $geometryRun 'run_manifest.json'
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $geometryManifest --require-status success
if($LASTEXITCODE-ne 0){throw 'Geometry-review run manifest is not verified success.'}
$globalFamilyDirectory=Join-Path $geometryRun 'simion'
$reviewedContractSource=Join-Path $globalFamilyDirectory 'simion_prototype_contract.json'
$globalGemSource=Join-Path $globalFamilyDirectory 'mrtof_analyzer.gem'
$contractInput=if([string]::IsNullOrWhiteSpace($ContractPath)){
  Join-Path $projectRoot 'config\simion_candidate_two_zone.json'
}else{(Resolve-Path -LiteralPath $ContractPath).Path}
foreach($path in @($contractInput,$reviewedContractSource,$globalGemSource,(Join-Path $globalFamilyDirectory 'mrtof_analyzer.pa#'))){
  if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Required reviewed analyser input is missing: $path"}
}
if([string]::IsNullOrWhiteSpace($RunId)){
  $scaleToken=([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:G}',$ScaleFactor)).Replace('.','p')
  $RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+"__build__simion__analyzer-local-$Region-$scaleToken"
}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
. (Join-Path $repoRoot 'common\parallel_gate_support.ps1')
$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'analyzer_local_dirichlet_pa_family' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass compact `
  -AdditionalDirectories @('simion') -UseShortExecutionPath
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir
$logDir=$package.log_dir;$solverDir=Join-Path $runDir 'simion';$runConfig=$package.run_config;$summary=$package.summary
$artifactRoot=Join-Path $workspaceRoot 'artifacts';$cacheRoot=Join-Path $artifactRoot 'common\simion\pa_family_cache'
$temporaryFamily=$null;$lease=$null;$terminalized=$false;$hostOutcome='failed';$failureStage='preflight'
try {
  $failureStage='freeze_contract'
  $frozenContract=Copy-VerifiedRunInput -Source $contractInput -Destination (Join-Path $inputDir 'simion_candidate_two_zone.json')
  $frozenReviewedContract=Copy-VerifiedRunInput -Source $reviewedContractSource -Destination (Join-Path $inputDir 'geometry_review_simion_prototype_contract.json')
  $canonicalGlobalGem=Join-Path $solverDir 'canonical_global_mrtof_analyzer.gem'
  Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.split_candidate_geometry',
    '--contract',$frozenContract,'--component','analyzer','--output',$canonicalGlobalGem)|Out-Null
  if(-not(Test-RunFilesIdentical -Left $canonicalGlobalGem -Right $globalGemSource)){
    throw 'Current baseline changes the reviewed global analyser GEM; the coarse PA family cannot be reused.'
  }
  $planPath=Join-Path $resultDir 'analyzer_local_refinement_plan.json'
  Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_refinement_plan','--contract',$frozenContract,'--output',$planPath)|Out-Null
  $plan=Get-Content -Raw -LiteralPath $planPath|ConvertFrom-Json -Depth 30
  $profile=@($plan.profiles|Where-Object {[double]$_.scale_factor-eq$ScaleFactor})
  if($profile.Count-ne 1){throw 'Requested local mesh scale did not resolve uniquely.'}
  $profileKey=switch($Region){
    'mirror_turn_positive' {'mirror_turn'}
    'mirror_turn_negative' {'mirror_turn_negative'}
    'central_transport' {'central_transport'}
    'stripe_mirror_bridge_positive' {'stripe_mirror_bridge'}
    'stripe_mirror_bridge_negative' {'stripe_mirror_bridge_negative'}
  }
  $selected=$profile[0].$profileKey
  [int64]$estimatedFamilyBytes=[int64]$selected.estimated_family_bytes
  $failureStage='capacity_preflight'
  $capacityStartup=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -RequiredHeadroomBytes ([int64](2*$estimatedFamilyBytes)) -ProtectedPaths @($package.artifact_run_dir,$geometryRun)
  $capacityStartupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $capacityStartupPath -Depth 14 -Value $capacityStartup

  $failureStage='derive_family_contract'
  $gem=Join-Path $solverDir "mrtof_analyzer_local_$Region.gem"
  Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_patch_geometry',
    '--contract',$frozenContract,'--region',$Region,'--scale-factor',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$ScaleFactor)),'--output',$gem)|Out-Null
  $familyContractPath=Join-Path $resultDir 'analyzer_local_pa_family_contract.json'
  Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_pa_family',
    '--contract',$frozenContract,'--region',$Region,'--scale-factor',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$ScaleFactor)),
    '--local-gem',$gem,'--global-family-directory',$globalFamilyDirectory,'--simion-executable',$simion,
    '--simion-release','SIMION 2020','--output',$familyContractPath)|Out-Null
  $familyContract=Get-Content -Raw -LiteralPath $familyContractPath|ConvertFrom-Json -Depth 30
  $identityPath=Join-Path $resultDir 'pa_family_cache_identity.json'
  Write-RunJson -Path $identityPath -Depth 30 -Value $familyContract.identity
  $filenames=@($familyContract.family_filenames|ForEach-Object{[string]$_})
  $cacheArguments=@('-m','common.simion.pa_family_cache','--action','probe','--cache-root',$cacheRoot,
    '--identity',$identityPath,'--filenames',($filenames-join ','))
  $probeLines=Invoke-ProjectPython -Arguments $cacheArguments
  $probe=($probeLines-join "`n")|ConvertFrom-Json
  $cacheDisposition=[string]$probe.disposition
  if($cacheDisposition-eq'corrupt'){throw "Local PA cache is corrupt: $($probe.detail)"}
  if($cacheDisposition-ne'hit'){
    $failureStage='build_local_family'
    $temporaryFamily=Join-Path ([IO.Path]::GetTempPath()) ('mrtof_local_pa_family_'+[guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $temporaryFamily|Out-Null
    $physicalRaw=Join-Path $temporaryFamily 'physical_ids.pa#'
    $prefix=[string]$familyContract.family_prefix
    $groupedRaw=Join-Path $temporaryFamily "$prefix.pa#"
    $lease=Enter-HostExecutionLease -Role SIMION -RunId $RunId
    Invoke-SimionStage -Stage 'compile_local_patch_gem' -Arguments @('--nogui','--noprompt','gem2pa',$gem,$physicalRaw)
    $mapping=@($familyContract.raw_physical_to_local_electrode_id.PSObject.Properties|
      Sort-Object {[int]$_.Name}|ForEach-Object{"$($_.Name):$($_.Value)"})-join','
    Invoke-SimionStage -Stage 'remap_local_electrode_ids' -Arguments @('--nogui','--noprompt','lua',
      (Join-Path $repoRoot 'common\simion\remap_pa_electrode_ids.lua'),$physicalRaw,$groupedRaw,$mapping)
    $coarseOrigin=(@($familyContract.coarse_origin_project_mm|ForEach-Object{[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$_)})-join',')
    $patchOrigin=(@($familyContract.patch_origin_project_mm|ForEach-Object{[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$_)})-join',')
    Invoke-SimionStage -Stage 'build_local_zero_response' -Arguments @('--nogui','--noprompt','lua',
      (Join-Path $repoRoot 'common\simion\build_dirichlet_patch_basis.lua'),$groupedRaw,
      (Join-Path $temporaryFamily ([string]$familyContract.zero_response.output_filename)),'-','-',$coarseOrigin,$patchOrigin)
    foreach($recipe in @($familyContract.response_recipes)){
      $sourcePaths=@($recipe.source_basis_paths|ForEach-Object{[string]$_})-join'|'
      Invoke-SimionStage -Stage ("build_local_basis_{0:D2}"-f[int]$recipe.local_id) -Arguments @('--nogui','--noprompt','lua',
        (Join-Path $repoRoot 'common\simion\build_dirichlet_patch_basis.lua'),$groupedRaw,
        (Join-Path $temporaryFamily ([string]$recipe.output_filename)),$sourcePaths,([string]$recipe.local_id),$coarseOrigin,$patchOrigin)
    }
    $failureStage='publish_local_family_cache'
    $publishLines=Invoke-ProjectPython -Arguments @('-m','common.simion.pa_family_cache','--action','publish',
      '--cache-root',$cacheRoot,'--identity',$identityPath,'--filenames',($filenames-join ','),'--source-directory',$temporaryFamily)
    $publication=($publishLines-join "`n")|ConvertFrom-Json
    $cacheDisposition=[string]$publication.disposition
  } else {$publication=$probe}
  $publicationPath=Join-Path $resultDir 'pa_family_cache_publication.json'
  Write-RunJson -Path $publicationPath -Depth 20 -Value $publication
  if($null-ne$temporaryFamily){Remove-GateTemporaryDirectory -Path $temporaryFamily -ExpectedNamePrefix 'mrtof_local_pa_family_';$temporaryFamily=$null}
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome success -RunId $RunId;$lease=$null}

  $summaryValue=[ordered]@{
    schema_version=1;role='mrtof_analyzer_local_dirichlet_pa_family';status='success'
    qualification='local_basis_family_cached__interface_and_flight_not_yet_verified'
    region=$Region;scale_factor=$ScaleFactor;grid_shape=@($selected.grid_shape)
    estimated_family_bytes=$estimatedFamilyBytes;cache_disposition=$cacheDisposition
    cache_key=[string]$publication.cache_key
    reason='Built or reused all eight contract response groups with coarse-basis Dirichlet faces. IOB priority, interface continuity, particle flight, and spatial convergence remain separate gates.'
  }
  Write-RunJson -Path $summary -Depth 20 -Value $summaryValue
  $config=Get-Content -Raw -LiteralPath $runConfig|ConvertFrom-Json -AsHashtable
  $config.inputs=[ordered]@{geometry_review_manifest=$geometryManifest;baseline_contract=$frozenContract;geometry_review_contract=$frozenReviewedContract;reviewed_global_analyzer_gem=$globalGemSource;canonical_global_analyzer_gem=$canonicalGlobalGem;local_gem=$gem;family_contract=$familyContractPath;cache_identity=$identityPath}
  $config.parameters=[ordered]@{region=$Region;scale_factor=$ScaleFactor;grid_shape=@($selected.grid_shape);cache_key=[string]$publication.cache_key}
  Write-RunJson -Path $runConfig -Depth 20 -Value $config
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $failureStage='capacity_terminal'
  [int64]$maximum=[int64](Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File|Measure-Object Length -Sum).Sum
  $capacityTerminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -ProtectedPaths @($package.artifact_run_dir,$geometryRun) -KnownMeasuredBytes ([int64]$capacityStartup.measured_after_bytes) -MaximumNewArtifactBytes $maximum
  $capacityTerminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json'
  Write-RunJson -Path $capacityTerminalPath -Depth 14 -Value $capacityTerminal
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success `
    -Software @('SIMION 2020','Python 3.11') -Outputs @($summary,$planPath,$familyContractPath,$identityPath,$publicationPath,$canonicalGlobalGem,$gem,$capacityStartupPath,$capacityTerminalPath,$retention)
  $terminalized=$true;$hostOutcome='success'
  Write-Host "MRTOF_ANALYZER_LOCAL_PA_FAMILY=PASS RUN_ID=$RunId REGION=$Region SCALE=$ScaleFactor CACHE=$cacheDisposition"
} catch {
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
    -SummaryRole 'mrtof_analyzer_local_dirichlet_pa_family' -Reason $_.Exception.Message -Software @('SIMION 2020','Python 3.11') -Status failed -FailureStage $failureStage;$terminalized=$true}
  throw
} finally {
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $hostOutcome -RunId $RunId}
  if($null-ne$temporaryFamily){Remove-GateTemporaryDirectory -Path $temporaryFamily -ExpectedNamePrefix 'mrtof_local_pa_family_'}
  Remove-RunPackageExecutionAlias -Package $package
}
