[CmdletBinding()]
param(
  [string]$ProviderRun='',
  [string]$ReviewedRun='',
  [string]$RunId='',
  [string]$SimionExe='',
  [string]$PythonExe=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$projectRoot=Join-Path $repoRoot "projects\$projectId"
$artifactRoot=Join-Path $workspaceRoot 'artifacts'
$projectRuns=Join-Path $artifactRoot "projects\$projectId\runs"
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$simion=if($SimionExe){[IO.Path]::GetFullPath($SimionExe)}else{Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
$provider=if($ProviderRun){(Resolve-Path -LiteralPath $ProviderRun).Path}else{Join-Path $projectRuns '20260916_001500__build__simion__mrtof-return-grid-three-component-iob-r41'}
$reviewed=if($ReviewedRun){(Resolve-Path -LiteralPath $ReviewedRun).Path}else{Join-Path $projectRuns '20260916_124000__build__simion__mrtof-return-grid-three-component-iob-r51'}
foreach($path in @($python,$simion)){if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Required file is missing: $path"}}
foreach($path in @($provider,$reviewed)){if(-not(Test-Path -LiteralPath $path -PathType Container)){throw "Required run is missing: $path"}}
if(-not$RunId){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__build__simion__mrtof-reviewed-analyzer-source'}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
. (Join-Path $repoRoot 'common\parallel_gate_support.ps1')

function Invoke-ProjectPython {
  param([Parameter(Mandatory)][string[]]$Arguments)
  Push-Location -LiteralPath $repoRoot
  $saved=$env:PYTHONPATH
  try {
    $env:PYTHONPATH=$repoRoot
    & $python @Arguments
    if($LASTEXITCODE-ne 0){throw "Python stage failed: $($Arguments -join ' ')"}
  } finally {$env:PYTHONPATH=$saved;Pop-Location}
}

function Invoke-SimionExport {
  param([Parameter(Mandatory)][int]$PhysicalId,[Parameter(Mandatory)][string[]]$LuaArguments)
  Push-Location -LiteralPath $nativeStaging
  try {
    $simionArguments=@('--nogui','--noprompt','lua')+$LuaArguments
    & $simion @simionArguments 2>&1 |
      Tee-Object -FilePath (Join-Path $logDir ("export_response_{0:D2}.log"-f$PhysicalId))
    if($LASTEXITCODE-ne 0){throw "SIMION standalone export failed for physical ID $PhysicalId"}
  } finally {Pop-Location}
}

$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $artifactRoot "projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'reviewed_analyzer_source_prepare' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled `
  -RetentionClass solver_review `
  -RetentionReason 'Freeze reviewed analyzer-source cache identities and detached physical response evidence.'
$inputDir=$package.input_dir;$resultDir=$package.result_dir;$logDir=$package.log_dir
$runConfig=$package.run_config;$summary=$package.summary
$cacheRoot=Join-Path $artifactRoot 'common\simion\pa_family_cache'
$adapter=Join-Path $projectRoot 'analysis\reviewed_analyzer_source_cache.py'
$exporter=Join-Path $repoRoot 'common\simion\export_fast_adjusted_standalone_pa.lua'
$lease=$null;$terminalized=$false;$hostOutcome='failed';$failureStage='preflight'
$nativeStaging=$null;$preparedOutputs=$null;$stageReceiptPath=$null
$inspectionPath=$null;$receiptPath=$null;$capacityStartupPath=$null
$retentionReceiptPath=Join-Path (Split-Path -Parent $runConfig) 'retention_actions.json'

try {
  $frozenAdapter=Copy-VerifiedRunInput -Source $adapter -Destination (Join-Path $inputDir 'reviewed_analyzer_source_cache.py')
  $frozenExporter=Copy-VerifiedRunInput -Source $exporter -Destination (Join-Path $inputDir 'export_fast_adjusted_standalone_pa.lua')
  $frozenProviderManifest=Copy-VerifiedRunInput -Source (Join-Path $provider 'run_manifest.json') -Destination (Join-Path $inputDir 'provider_run_manifest.json')
  $frozenProviderReview=Copy-VerifiedRunInput -Source (Join-Path $provider 'simion\three_component_geometry_review.json') -Destination (Join-Path $inputDir 'provider_geometry_review.json')
  $frozenReviewedManifest=Copy-VerifiedRunInput -Source (Join-Path $reviewed 'run_manifest.json') -Destination (Join-Path $inputDir 'reviewed_run_manifest.json')
  $frozenReviewedReview=Copy-VerifiedRunInput -Source (Join-Path $reviewed 'simion\three_component_geometry_review.json') -Destination (Join-Path $inputDir 'reviewed_geometry_review.json')
  $inspectionPath=Join-Path $resultDir 'reviewed_source_inspection.json'
  $failureStage='inspect_reviewed_sources'
  $inspectionText=Invoke-ProjectPython -Arguments @(
    '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.reviewed_analyzer_source_cache',
    '--action','inspect','--cache-root',$cacheRoot,'--provider-run',$provider,'--reviewed-run',$reviewed,
    '--simion-executable',$simion,'--simion-release','SIMION 2020'
  )
  $inspection=$inspectionText|ConvertFrom-Json -Depth 60
  Write-RunJson -Path $inspectionPath -Depth 60 -Value $inspection
  $preparedDisposition=[string]$inspection.cache_probe.prepared.disposition
  $rawDisposition=[string]$inspection.cache_probe.raw.disposition
  if($preparedDisposition-eq'corrupt' -or $rawDisposition-eq'corrupt'){
    throw "Reviewed source cache is corrupt: prepared=$preparedDisposition raw=$rawDisposition"
  }
  $cacheHit=($preparedDisposition-eq'hit' -and $rawDisposition-eq'hit')
  [int64]$sourceBytes=[int64](@($inspection.source_inventory)|Measure-Object -Property bytes -Sum).Sum
  [int64]$rawBytes=[int64]$inspection.evidence.provider.analyzer_raw_pa.bytes
  [int64]$responseBytes=14*[int64]$inspection.evidence.provider.basis_arrays.'2'.bytes
  [int64]$requiredBytes=if($cacheHit){0}else{$sourceBytes+2*($rawBytes+$responseBytes)+1GB}
  $protectedCacheKeys=@([string]$inspection.prepared_cache_key,[string]$inspection.raw_cache_key)
  $failureStage='capacity_startup'
  $capacityStartup=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -RequiredHeadroomBytes $requiredBytes -ProtectedPaths @($package.artifact_run_dir,$provider,$reviewed) `
    -ProtectedCacheKeys $protectedCacheKeys
  $capacityStartupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $capacityStartupPath -Depth 20 -Value $capacityStartup

  $receiptPath=Join-Path $resultDir 'reviewed_analyzer_source_cache_receipt.json'
  if($cacheHit){
    $failureStage='validate_cache_hit'
    $receiptText=Invoke-ProjectPython -Arguments @(
      '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.reviewed_analyzer_source_cache',
      '--action','receipt-from-hit','--cache-root',$cacheRoot,'--inspection',$inspectionPath
    )
  } else {
    $lease=Enter-HostExecutionLease -Role SIMION -Stage mrtof_pa_prepare -RunId $RunId
    # Assign both cleanup-visible variables before creating either directory.
    $nativeStaging=Join-Path ([IO.Path]::GetTempPath()) ('mrtof_reviewed_analyzer_native_'+[guid]::NewGuid().ToString('N'))
    $preparedOutputs=Join-Path ([IO.Path]::GetTempPath()) ('mrtof_reviewed_analyzer_prepared_'+[guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $nativeStaging|Out-Null
    New-Item -ItemType Directory -Path $preparedOutputs|Out-Null
    $failureStage='stage_reviewed_native_source'
    $stageText=Invoke-ProjectPython -Arguments @(
      '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.reviewed_analyzer_source_cache',
      '--action','stage-native','--cache-root',$cacheRoot,'--inspection',$inspectionPath,
      '--staging-directory',$nativeStaging
    )
    $stageReceipt=$stageText|ConvertFrom-Json -Depth 40
    $stageReceiptPath=Join-Path $resultDir 'native_staging_receipt.json'
    Write-RunJson -Path $stageReceiptPath -Depth 40 -Value $stageReceipt
    $failureStage='plan_standalone_exports'
    $planText=Invoke-ProjectPython -Arguments @(
      '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.reviewed_analyzer_source_cache',
      '--action','export-plan','--cache-root',$cacheRoot,'--inspection',$inspectionPath,
      '--staging-directory',$nativeStaging,'--output-directory',$preparedOutputs
    )
    $plan=$planText|ConvertFrom-Json -Depth 50
    foreach($export in @($plan.exports)){
      $failureStage="export_physical_response_$([int]$export.physical_id)"
      Invoke-SimionExport -PhysicalId ([int]$export.physical_id) -LuaArguments @($export.lua_arguments|ForEach-Object{[string]$_})
    }
    $failureStage='publish_prepared_cache'
    $receiptText=Invoke-ProjectPython -Arguments @(
      '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.reviewed_analyzer_source_cache',
      '--action','publish-prepared','--cache-root',$cacheRoot,'--inspection',$inspectionPath,
      '--staging-directory',$nativeStaging,'--output-directory',$preparedOutputs
    )
  }
  $receipt=$receiptText|ConvertFrom-Json -Depth 80
  Write-RunJson -Path $receiptPath -Depth 80 -Value $receipt
  Write-RunJson -Path $summary -Depth 20 -Value ([ordered]@{
    schema_version=1;role='mrtof_reviewed_analyzer_source_prepare';status='success'
    qualification='reviewed_source_cache_only__no_flight_or_focus_claim'
    cache_hit=$cacheHit;native_generation_published=$false
    prepared_cache_key=[string]$receipt.prepared_standalone_generation.cache_key
    raw_cache_key=[string]$receipt.raw_geometry_generation.cache_key
    physical_response_ids=@(2,3,4,5,7,8,9,10,11,12,13,14,16,17)
  })
  $config=Get-Content -Raw -LiteralPath $runConfig|ConvertFrom-Json -AsHashtable
  $config.inputs=[ordered]@{
    provider_run_manifest=$frozenProviderManifest;provider_geometry_review=$frozenProviderReview
    reviewed_run_manifest=$frozenReviewedManifest;reviewed_geometry_review=$frozenReviewedReview
    adapter=$frozenAdapter;standalone_exporter=$frozenExporter
  }
  $config.parameters=[ordered]@{mesh_mm_per_gu=@($inspection.mesh.mm_per_gu);source_member_count=22;native_generation_published=$false;physical_response_ids=@(2,3,4,5,7,8,9,10,11,12,13,14,16,17);prepared_cache_key=[string]$inspection.prepared_cache_key;raw_cache_key=[string]$inspection.raw_cache_key}
  Write-RunJson -Path $runConfig -Depth 40 -Value $config
  $failureStage='retention'
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $failureStage='capacity_terminal'
  [int64]$runBytes=[int64](Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File|Measure-Object Length -Sum).Sum
  [int64]$publishedCacheBytes=0
  foreach($generation in @($receipt.prepared_standalone_generation,$receipt.raw_geometry_generation)){
    if([string]$generation.disposition-eq'published'){
      $generationDirectory=[IO.Path]::GetFullPath([string]$generation.generation_directory)
      $manifestPath=Join-Path $generationDirectory 'cache_manifest.json'
      $pointerPath=Join-Path (Split-Path -Parent (Split-Path -Parent $generationDirectory)) 'current_generation.json'
      $publishedCacheBytes+=[int64](@($generation.inventory)|Measure-Object -Property bytes -Sum).Sum
      $publishedCacheBytes+=[int64](Get-Item -LiteralPath $manifestPath).Length
      $publishedCacheBytes+=[int64](Get-Item -LiteralPath $pointerPath).Length
    }
  }
  $capacityTerminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -ProtectedPaths @($package.artifact_run_dir,$provider,$reviewed) -ProtectedCacheKeys $protectedCacheKeys `
    -KnownMeasuredBytes ([int64]$capacityStartup.measured_after_bytes) -MaximumNewArtifactBytes ($runBytes+$publishedCacheBytes)
  $capacityTerminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json'
  Write-RunJson -Path $capacityTerminalPath -Depth 20 -Value $capacityTerminal
  $outputs=@($summary,$inspectionPath,$receiptPath,$capacityStartupPath,$capacityTerminalPath,$retention)
  if($null-ne$stageReceiptPath){$outputs+=$stageReceiptPath}
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success `
    -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
  $terminalized=$true;$hostOutcome='success'
  Write-Host "MRTOF_REVIEWED_ANALYZER_SOURCE=PASS RUN_ID=$RunId CACHE_HIT=$cacheHit"
} catch {
  $failure=$_
  if(-not$terminalized){
    if(Test-Path -LiteralPath $retentionReceiptPath -PathType Leaf){
      # Apply-RunArtifactRetention owns this single-publication receipt. If it
      # wrote the receipt before failing, preserve the original failure rather
      # than calling Complete-FailedRun and masking it with "already exists".
      Write-RunJson -Path $summary -Depth 12 -Value ([ordered]@{
        schema_version=1;role='mrtof_reviewed_analyzer_source_prepare';status='failed'
        reason=$failure.Exception.Message;failure_stage=$failureStage
      })
      $failureOutputs=@($summary,$retentionReceiptPath)
      foreach($candidate in @($inspectionPath,$receiptPath,$capacityStartupPath,$stageReceiptPath)){
        if($null-ne$candidate -and(Test-Path -LiteralPath $candidate -PathType Leaf)){$failureOutputs+=$candidate}
      }
      Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status failed `
        -Software @('SIMION 2020','Python 3.11') -Outputs $failureOutputs
    } else {
      Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
        -SummaryRole 'mrtof_reviewed_analyzer_source_prepare' -Reason $failure.Exception.Message `
        -Software @('SIMION 2020','Python 3.11') -Status failed -FailureStage $failureStage
    }
    $terminalized=$true
  }
  throw $failure
} finally {
  if($null-ne$preparedOutputs -and(Test-Path -LiteralPath $preparedOutputs -PathType Container)){
    Remove-GateTemporaryDirectory -Path $preparedOutputs -ExpectedNamePrefix 'mrtof_reviewed_analyzer_prepared_'
  }
  if($null-ne$nativeStaging -and(Test-Path -LiteralPath $nativeStaging -PathType Container)){
    Remove-GateTemporaryDirectory -Path $nativeStaging -ExpectedNamePrefix 'mrtof_reviewed_analyzer_native_'
  }
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $hostOutcome -RunId $RunId}
  Remove-RunPackageExecutionAlias -Package $package
}
