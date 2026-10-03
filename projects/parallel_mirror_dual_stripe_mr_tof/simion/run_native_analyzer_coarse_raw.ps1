[CmdletBinding()]
param([string]$RunId='',[string]$SimionExe='',[string]$PythonExe='')

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$artifactRoot=Join-Path $workspaceRoot 'artifacts'
$projectArtifactRoot=Join-Path $artifactRoot "projects\$projectId"
$cacheRoot=Join-Path $artifactRoot 'common\simion\pa_family_cache'
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$simion=if($SimionExe){[IO.Path]::GetFullPath($SimionExe)}else{Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
$contract=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\config\simion_candidate_two_zone.json'
if(-not$RunId){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__build__simion__mrtof-symmetric-coarse-raw'}
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\parallel_gate_support.ps1')
. (Join-Path $repoRoot 'common\simion\short_pa_path_support.ps1')

function Invoke-RootPython([string[]]$Arguments){
  $lines=@(Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {& $python @Arguments;if($LASTEXITCODE-ne0){throw "Python stage failed: $($Arguments-join' ')"}})
  return $lines
}
function Invoke-Transaction([string]$Identity,[string]$Owner='',[string]$Evidence=''){
  $arguments=@('-m','common.simion.pa_family_cache','--action','advance-transaction','--cache-root',$cacheRoot,'--identity',$Identity,
    '--filenames','mrtof_analyzer.pa#','--recovery-policy','none','--published-pin-reason','MR-TOF symmetric full-domain 1 mm boundary source','--producer-run-config',$runConfig)
  if($Owner){$arguments+=@('--owner',$Owner)};if($Evidence){$arguments+=@('--verification-evidence',$Evidence)}
  return ((@(Invoke-RootPython $arguments)-join"`n")|ConvertFrom-Json -Depth 30)
}
function Invoke-FallbackTransaction([string]$Identity,[string]$Owner='',[string]$Evidence=''){
  $arguments=@('-m','common.simion.pa_family_cache','--action','advance-transaction','--cache-root',$cacheRoot,'--identity',$Identity,
    '--filenames','mrtof_analyzer_global_fallback.pa','--recovery-policy','none','--published-pin-reason','MR-TOF symmetric full-domain 1 mm collision fallback','--producer-run-config',$runConfig)
  if($Owner){$arguments+=@('--owner',$Owner)};if($Evidence){$arguments+=@('--verification-evidence',$Evidence)}
  return ((@(Invoke-RootPython $arguments)-join"`n")|ConvertFrom-Json -Depth 30)
}

$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $projectArtifactRoot -RunId $RunId -Project $projectId `
  -Mode 'native_analyzer_symmetric_coarse_raw' -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass compact -CapacityLedgerLifecycleEnabled -UseShortExecutionPath
$summary=$package.summary;$runConfig=$package.run_config;$resultDir=$package.result_dir;$capacity=$null;$lease=$null;$terminal=$false
$identity=Join-Path $resultDir 'coarse_raw_identity.json';$gem=Join-Path $resultDir 'mrtof_analyzer.gem';$verifyLog=Join-Path $resultDir 'coarse_raw_verify.log';$evidence=Join-Path $resultDir 'coarse_raw_verification.json'
$fallbackIdentity=Join-Path $resultDir 'global_fallback_identity.json';$fallbackVerifyLog=Join-Path $resultDir 'global_fallback_verify.log';$fallbackEvidence=Join-Path $resultDir 'global_fallback_verification.json'
try{
  Invoke-RootPython @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_analyzer_coarse_raw','--contract',$contract,'--simion-executable',$simion,'--simion-release','SIMION 2020','--identity-output',$identity,'--gem-output',$gem)|Out-Null
  $probe=((@(Invoke-RootPython @('-m','common.simion.pa_family_cache','--action','probe','--cache-root',$cacheRoot,'--identity',$identity,'--filenames','mrtof_analyzer.pa#'))-join"`n")|ConvertFrom-Json -Depth 30)
  $plan=Get-Content $identity -Raw|ConvertFrom-Json -Depth 20
  [int64]$estimatedBytes=[int64]$plan.geometry.grid_shape[0]*[int64]$plan.geometry.grid_shape[1]*[int64]$plan.geometry.grid_shape[2]*8
  Write-RunJson -Path $fallbackIdentity -Depth 20 -Value ([ordered]@{
    geometry=[ordered]@{role='mrtof_symmetric_global_collision_fallback';source_coarse_raw_cache_key=[string]$probe.cache_key;grid_shape=@($plan.geometry.grid_shape)}
    gem=[ordered]@{source='published_symmetric_coarse_raw_geometry'}
    basis_namespace=[ordered]@{artifact_role='low_priority_collision_geometry_only__native_corridor_is_field_authority'}
    mesh=[ordered]@{mm_per_gu=@($plan.mesh.mm_per_gu)}
    grid_phase=$plan.grid_phase
    surface='none'
    simion_identity=$plan.simion_identity
    refine_policy=[ordered]@{operation='byte_identical_standalone_name_copy';refine_performed=$false}
    builder_identity=[ordered]@{short_pa_path_support_sha256=(Get-FileHash (Join-Path $repoRoot 'common\simion\short_pa_path_support.ps1') -Algorithm SHA256).Hash}
  })
  $fallbackProbe=((@(Invoke-RootPython @('-m','common.simion.pa_family_cache','--action','probe','--cache-root',$cacheRoot,'--identity',$fallbackIdentity,'--filenames','mrtof_analyzer_global_fallback.pa'))-join"`n")|ConvertFrom-Json -Depth 30)
  [int64]$committedBytes=$(if($probe.disposition-eq'hit'){0}else{$estimatedBytes})+$(if($fallbackProbe.disposition-eq'hit'){0}else{$estimatedBytes})
  $capacity=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -RunDirectory $package.artifact_run_dir -CommittedNewBytes $committedBytes -ProtectedPaths @($package.artifact_run_dir) -ProtectedCacheKeys @([string]$probe.cache_key,[string]$fallbackProbe.cache_key) -Owner "mrtof-coarse-raw:$RunId"
  if($probe.disposition-eq'hit'){$publication=$probe}else{
    if($probe.disposition-ne'miss'){throw "Coarse raw cache is not usable: $($probe.disposition)"}
    $state=Invoke-Transaction $identity ([string]$capacity.owner)
    if($state.action_required-ne'build'){throw "Coarse raw transaction cannot build: $($state.action_required)"}
    $raw=Join-Path ([string]$state.build_directory) 'mrtof_analyzer.pa#'
    $lease=Enter-HostExecutionLease -Role SIMION -Stage prepare -RunId $RunId
    & (Join-Path $repoRoot 'common\simion\run_gem2pa.ps1') -SimionExe $simion -GemPath $gem -OutputPaPath $raw
    Exit-HostExecutionLease -Lease $lease -Outcome success -RunId $RunId;$lease=$null
    $state=Invoke-Transaction $identity
    if($state.action_required-ne'verify'){throw "Coarse raw transaction cannot verify: $($state.action_required)"}
    $shape=@($plan.geometry.grid_shape)
    & $simion --nogui --noprompt lua (Join-Path $PSScriptRoot 'verify_native_analyzer_coarse_raw.lua') (Join-Path ([string]$state.build_directory) 'mrtof_analyzer.pa#') $shape[0] $shape[1] $shape[2] 2>&1|Tee-Object $verifyLog|Out-Host
    if($LASTEXITCODE-ne0){throw 'Coarse raw verification failed.'}
    Write-RunJson -Path $evidence -Depth 10 -Value ([ordered]@{schema_version=1;role='simion_pa_family_verification';status='pass';cache_key=[string]$state.cache_key;inventory_sha256=[string]$state.inventory_sha256;solver_release='SIMION 2020';verifier_path=(Join-Path $PSScriptRoot 'verify_native_analyzer_coarse_raw.lua');verifier_sha256=(Get-FileHash (Join-Path $PSScriptRoot 'verify_native_analyzer_coarse_raw.lua') -Algorithm SHA256).Hash;verification_output_path=$verifyLog;verification_output_sha256=(Get-FileHash $verifyLog -Algorithm SHA256).Hash})
    $publication=Invoke-Transaction $identity '' $evidence
    if($publication.action_required-ne'complete'){throw "Coarse raw transaction did not publish: $($publication.action_required)"}
  }
  $rawGeneration=Join-Path ([string]$publication.generation_directory) 'mrtof_analyzer.pa#'
  $rawManifest=Get-Content -LiteralPath (Join-Path ([string]$publication.generation_directory) 'cache_manifest.json') -Raw|ConvertFrom-Json -Depth 30
  $rawRecord=@($rawManifest.files|Where-Object name -CEQ 'mrtof_analyzer.pa#')
  if($rawRecord.Count-ne1){throw 'Published coarse raw manifest has no unique raw member.'}
  if($fallbackProbe.disposition-eq'hit'){$fallbackPublication=$fallbackProbe}else{
    if($fallbackProbe.disposition-ne'miss'){throw "Global fallback cache is not usable: $($fallbackProbe.disposition)"}
    $fallbackState=Invoke-FallbackTransaction $fallbackIdentity ([string]$capacity.owner)
    if($fallbackState.action_required-ne'build'){throw "Global fallback transaction cannot build: $($fallbackState.action_required)"}
    $fallbackBuild=Join-Path ([string]$fallbackState.build_directory) 'mrtof_analyzer_global_fallback.pa'
    New-ShortPaCopy -Source $rawGeneration -Destination $fallbackBuild -ExpectedBytes ([int64]$rawRecord[0].bytes) -ExpectedSha256 ([string]$rawRecord[0].sha256)|Out-Null
    Publish-ShortPaCopyDestination -Path $fallbackBuild|Out-Null
    $fallbackState=Invoke-FallbackTransaction $fallbackIdentity
    if($fallbackState.action_required-ne'verify'){throw "Global fallback transaction cannot verify: $($fallbackState.action_required)"}
    $shape=@($plan.geometry.grid_shape)
    & $simion --nogui --noprompt lua (Join-Path $PSScriptRoot 'verify_native_analyzer_coarse_raw.lua') (Join-Path ([string]$fallbackState.build_directory) 'mrtof_analyzer_global_fallback.pa') $shape[0] $shape[1] $shape[2] 2>&1|Tee-Object $fallbackVerifyLog|Out-Host
    if($LASTEXITCODE-ne0){throw 'Global collision fallback verification failed.'}
    Write-RunJson -Path $fallbackEvidence -Depth 10 -Value ([ordered]@{schema_version=1;role='simion_pa_family_verification';status='pass';cache_key=[string]$fallbackState.cache_key;inventory_sha256=[string]$fallbackState.inventory_sha256;solver_release='SIMION 2020';verifier_path=(Join-Path $PSScriptRoot 'verify_native_analyzer_coarse_raw.lua');verifier_sha256=(Get-FileHash (Join-Path $PSScriptRoot 'verify_native_analyzer_coarse_raw.lua') -Algorithm SHA256).Hash;verification_output_path=$fallbackVerifyLog;verification_output_sha256=(Get-FileHash $fallbackVerifyLog -Algorithm SHA256).Hash})
    $fallbackPublication=Invoke-FallbackTransaction $fallbackIdentity '' $fallbackEvidence
    if($fallbackPublication.action_required-ne'complete'){throw "Global fallback transaction did not publish: $($fallbackPublication.action_required)"}
  }
  $publicationPath=Join-Path $resultDir 'pa_family_cache_publication.json';Write-RunJson -Path $publicationPath -Depth 30 -Value $publication
  $fallbackPublicationPath=Join-Path $resultDir 'global_fallback_cache_publication.json';Write-RunJson -Path $fallbackPublicationPath -Depth 30 -Value $fallbackPublication
  $fallbackPa=Join-Path ([string]$fallbackPublication.generation_directory) 'mrtof_analyzer_global_fallback.pa'
  Write-RunJson -Path $summary -Depth 10 -Value ([ordered]@{schema_version=1;role='mrtof_symmetric_coarse_raw';status='success';cache_key=[string]$publication.cache_key;generation_sha256=[string]$publication.generation_sha256;reused=($probe.disposition-eq'hit');global_fallback_cache_key=[string]$fallbackPublication.cache_key;global_fallback_generation_sha256=[string]$fallbackPublication.generation_sha256;global_fallback_role='low_priority_collision_geometry_only'})
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $outputs=@($summary,$identity,$gem,$publicationPath,$fallbackIdentity,$fallbackPublicationPath,$fallbackPa,$retention);foreach($p in @($verifyLog,$evidence,$fallbackVerifyLog,$fallbackEvidence)){if(Test-Path $p){$outputs+=@($p)}}
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
  $terminal=$true;Write-Host "MRTOF_SYMMETRIC_COARSE_RAW=PASS RUN_ID=$RunId CACHE_KEY=$($publication.cache_key)"
}catch{
  if(-not$terminal){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_symmetric_coarse_raw' -Reason $_.Exception.Message -Software @('SIMION 2020','Python 3.11') -Status failed -FailureStage 'build_or_publish';$terminal=$true};throw
}finally{
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome failed -RunId $RunId}
  if($null-ne$capacity){$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity}
  Remove-RunPackageExecutionAlias -Package $package
}
