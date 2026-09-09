[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$GeometryReviewRunPath,
  [Parameter(Mandatory)][string]$CoarseCentralRunPath,
  [Parameter(Mandatory)][string]$CoarseMirrorRunPath,
  [Parameter(Mandatory)][string]$FineCentralRunPath,
  [Parameter(Mandatory)][string]$FineMirrorRunPath,
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

function Get-VerifiedLocalFamily {
  param(
    [Parameter(Mandatory)][string]$SourceRunPath,
    [Parameter(Mandatory)][string]$ExpectedRegion,
    [Parameter(Mandatory)][double]$ExpectedScale,
    [Parameter(Mandatory)][string]$Label
  )
  $sourceRun=(Resolve-Path -LiteralPath $SourceRunPath).Path
  $manifest=Join-Path $sourceRun 'run_manifest.json'
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $manifest --require-status success|Out-Null
  if($LASTEXITCODE-ne 0){throw "Local-family run is not verified success: $sourceRun"}
  $sourceSummary=Get-Content -Raw -LiteralPath (Join-Path $sourceRun 'summary.json')|ConvertFrom-Json
  if($sourceSummary.role-ne'mrtof_analyzer_local_dirichlet_pa_family' -or
     $sourceSummary.region-ne$ExpectedRegion -or
     [double]$sourceSummary.scale_factor-ne$ExpectedScale){
    throw "Local-family run identity differs for $Label."
  }
  $contractSource=Join-Path $sourceRun 'results\analyzer_local_pa_family_contract.json'
  $identitySource=Join-Path $sourceRun 'results\pa_family_cache_identity.json'
  $publicationSource=Join-Path $sourceRun 'results\pa_family_cache_publication.json'
  foreach($path in @($contractSource,$identitySource,$publicationSource)){
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Local-family evidence is missing: $path"}
  }
  $contract=Get-Content -Raw -LiteralPath $contractSource|ConvertFrom-Json -Depth 40
  $publication=Get-Content -Raw -LiteralPath $publicationSource|ConvertFrom-Json
  if([string]$publication.cache_key-ne[string]$sourceSummary.cache_key){
    throw "Local-family publication key differs for $Label."
  }
  return [pscustomobject]@{
    label=$Label;source_run=$sourceRun;manifest=$manifest;contract_source=$contractSource
    identity_source=$identitySource;publication_source=$publicationSource
    contract=$contract;cache_key=[string]$publication.cache_key
    region=$ExpectedRegion;scale=$ExpectedScale
    frozen_contract=$null;frozen_identity=$null;frozen_publication=$null
    generation_directory=$null
  }
}

$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$simion=if($SimionExe){[IO.Path]::GetFullPath($SimionExe)}else{Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
if(-not(Test-Path -LiteralPath $python -PathType Leaf)){throw "Python executable is missing: $python"}
if(-not(Test-Path -LiteralPath $simion -PathType Leaf)){throw "SIMION executable is missing: $simion"}
$geometryRun=(Resolve-Path -LiteralPath $GeometryReviewRunPath).Path
$geometryManifest=Join-Path $geometryRun 'run_manifest.json'
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $geometryManifest --require-status success
if($LASTEXITCODE-ne 0){throw 'Geometry-review run manifest is not verified success.'}
$globalFamilyDirectory=Join-Path $geometryRun 'simion'
if([string]::IsNullOrWhiteSpace($RunId)){
  $RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__analysis__simion__analyzer-local-interface-convergence'
}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'analyzer_local_interface_convergence' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass compact `
  -UseShortExecutionPath
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir
$logDir=$package.log_dir;$runConfig=$package.run_config;$summary=$package.summary
$artifactRoot=Join-Path $workspaceRoot 'artifacts';$cacheRoot=Join-Path $artifactRoot 'common\simion\pa_family_cache'
$lease=$null;$terminalized=$false;$hostOutcome='failed';$failureStage='preflight'
try {
  $families=@(
    Get-VerifiedLocalFamily -SourceRunPath $CoarseCentralRunPath -ExpectedRegion central_transport -ExpectedScale 1.0 -Label coarse_central
    Get-VerifiedLocalFamily -SourceRunPath $CoarseMirrorRunPath -ExpectedRegion mirror_turn_positive -ExpectedScale 1.0 -Label coarse_mirror
    Get-VerifiedLocalFamily -SourceRunPath $FineCentralRunPath -ExpectedRegion central_transport -ExpectedScale 0.5 -Label fine_central
    Get-VerifiedLocalFamily -SourceRunPath $FineMirrorRunPath -ExpectedRegion mirror_turn_positive -ExpectedScale 0.5 -Label fine_mirror
  )
  $failureStage='freeze_inputs'
  $frozenInputs=[ordered]@{geometry_review_manifest=$geometryManifest}
  foreach($family in $families){
    $family.frozen_contract=Copy-VerifiedRunInput -Source $family.contract_source `
      -Destination (Join-Path $inputDir "$($family.label)_family_contract.json")
    $family.frozen_identity=Copy-VerifiedRunInput -Source $family.identity_source `
      -Destination (Join-Path $inputDir "$($family.label)_cache_identity.json")
    $family.frozen_publication=Copy-VerifiedRunInput -Source $family.publication_source `
      -Destination (Join-Path $inputDir "$($family.label)_cache_publication.json")
    $frozenInputs["$($family.label)_source_manifest"]=$family.manifest
    $frozenInputs["$($family.label)_family_contract"]=$family.frozen_contract
    $frozenInputs["$($family.label)_cache_identity"]=$family.frozen_identity
    $frozenInputs["$($family.label)_cache_publication"]=$family.frozen_publication
  }
  $capacityStartup=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -RequiredHeadroomBytes 104857600 -ProtectedPaths @($package.artifact_run_dir,$geometryRun) `
    -ProtectedCacheKeys @($families.cache_key)
  $capacityStartupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $capacityStartupPath -Depth 14 -Value $capacityStartup

  $failureStage='probe_cache_families'
  foreach($family in $families){
    $names=@($family.contract.family_filenames|ForEach-Object{[string]$_})
    $lines=Invoke-ProjectPython -Arguments @('-m','common.simion.pa_family_cache','--action','probe',
      '--cache-root',$cacheRoot,'--identity',$family.frozen_identity,'--filenames',($names-join ','))
    $probe=($lines-join "`n")|ConvertFrom-Json
    if($probe.disposition-ne'hit' -or [string]$probe.cache_key-ne$family.cache_key){
      throw "Required local PA family is not an intact cache hit: $($family.label)"
    }
    $family.generation_directory=[string]$probe.generation_directory
    $cacheManifest=Join-Path $family.generation_directory 'cache_manifest.json'
    $frozenInputs["$($family.label)_cache_manifest"]=$cacheManifest
  }
  $config=Get-Content -Raw -LiteralPath $runConfig|ConvertFrom-Json -AsHashtable
  $config.inputs=$frozenInputs
  $config.parameters=[ordered]@{
    scale_factors=@(1.0,0.5);physical_sample_spacing_mm=1.0
    regions=@('central_transport','mirror_turn_positive')
    cache_keys=@($families.cache_key)
  }
  Write-RunJson -Path $runConfig -Depth 20 -Value $config
  Write-RunJson -Path $summary -Depth 8 -Value ([ordered]@{
    schema_version=1;role='mrtof_analyzer_local_interface_convergence';status='checkpoint'
    reason='All four local PA families are verified cache hits; interface sampling is starting.'
    cache_keys=@($families.cache_key)
  })
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status checkpoint `
    -Software @('SIMION 2020','Python 3.11') -Outputs @($summary,$capacityStartupPath)|Out-Null

  $groups=@($families[0].contract.response_recipes|ForEach-Object{[string]$_.group})
  if($groups.Count-ne 8 -or @($groups|Select-Object -Unique).Count-ne 8){throw 'Response group namespace differs.'}
  foreach($family in $families){
    $observed=@($family.contract.response_recipes|ForEach-Object{[string]$_.group})
    if(($observed-join '|')-ne($groups-join '|')){throw "Response group order differs: $($family.label)"}
  }
  $failureStage='sample_interfaces'
  $comparisonRecords=@();$nativeRecords=@();$csvOutputs=@()
  $comparisonScript=Join-Path $repoRoot 'common\simion\compare_dirichlet_patch_interface.lua'
  $simionLog=Join-Path $logDir 'simion_interface_comparisons.log'
  $lease=Enter-HostExecutionLease -Role SIMION -RunId $RunId
  foreach($family in $families){
    $mesh=[double]$family.contract.identity.mesh.mm_per_gu[0]
    if(@($family.contract.identity.mesh.mm_per_gu|Where-Object{[double]$_-ne$mesh}).Count-ne 0){
      throw "Local interface sampling requires isotropic patch mesh: $($family.label)"
    }
    $stride=[int][math]::Round(1.0/$mesh)
    if($stride-lt 1 -or [math]::Abs($stride*$mesh-1.0)-gt 1e-12){
      throw "Local mesh does not align to the 1-mm physical sample lattice: $($family.label)"
    }
    $coarseOrigin=(@($family.contract.coarse_origin_project_mm|ForEach-Object{
      [string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$_)
    })-join ',')
    $patchOrigin=(@($family.contract.patch_origin_project_mm|ForEach-Object{
      [string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$_)
    })-join ',')
    $raw=Join-Path $family.generation_directory "$($family.contract.family_prefix).pa#"
    foreach($recipe in @($family.contract.response_recipes)){
      foreach($source in @($recipe.source_basis_paths)){
        if(-not(Test-Path -LiteralPath $source -PathType Leaf) -or
           -not([IO.Path]::GetFullPath($source).StartsWith($globalFamilyDirectory+[IO.Path]::DirectorySeparatorChar,
             [StringComparison]::OrdinalIgnoreCase))){
          throw "Coarse basis source is outside the reviewed global family: $source"
        }
      }
      $sourceText=@($recipe.source_basis_paths)-join'|'
      $csv=Join-Path $resultDir "matched__$($family.label)__$($recipe.group).csv"
      & $simion --nogui --noprompt lua $comparisonScript `
        (Join-Path $family.generation_directory ([string]$recipe.output_filename)) `
        $raw $sourceText $coarseOrigin $patchOrigin $csv $stride matched_lattice `
        2>&1|Tee-Object -FilePath $simionLog -Append
      if($LASTEXITCODE-ne 0){throw "SIMION interface comparison failed: $($family.label)/$($recipe.group)"}
      $csvOutputs+=$csv
      $comparisonRecords+=[ordered]@{
        scale_factor=[double]$family.scale;region=[string]$family.region
        group=[string]$recipe.group;csv_path=$csv;cache_key=[string]$family.cache_key
      }
      $nativeCsv=Join-Path $resultDir "native__$($family.label)__$($recipe.group).csv"
      & $simion --nogui --noprompt lua $comparisonScript `
        (Join-Path $family.generation_directory ([string]$recipe.output_filename)) `
        $raw $sourceText $coarseOrigin $patchOrigin $nativeCsv 1 native_all_nodes `
        2>&1|Tee-Object -FilePath $simionLog -Append
      if($LASTEXITCODE-ne 0){throw "SIMION native interface scan failed: $($family.label)/$($recipe.group)"}
      $csvOutputs+=$nativeCsv
      $nativeRecords+=[ordered]@{
        scale_factor=[double]$family.scale;region=[string]$family.region
        group=[string]$recipe.group;csv_path=$nativeCsv;cache_key=[string]$family.cache_key
      }
    }
  }
  Exit-HostExecutionLease -Lease $lease -Outcome success -RunId $RunId;$lease=$null
  $hostOutcome='success'

  $measurementInput=Join-Path $inputDir 'interface_measurement_input.json'
  Write-RunJson -Path $measurementInput -Depth 12 -Value ([ordered]@{
    schema_version=1;role='mrtof_analyzer_local_interface_measurement_input'
    scale_factors=@(1.0,0.5);physical_sample_spacing_mm=1.0
    regions=@('central_transport','mirror_turn_positive');response_groups=$groups
    comparisons=$comparisonRecords;native_face_scans=$nativeRecords
  })
  $failureStage='analyze_interfaces'
  $result=Join-Path $resultDir 'analyzer_local_interface_convergence.json'
  Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_interface',
    '--input',$measurementInput,'--output',$result)|Out-Null
  $metrics=Get-Content -Raw -LiteralPath $result|ConvertFrom-Json -Depth 40
  Write-RunJson -Path $summary -Depth 15 -Value ([ordered]@{
    schema_version=1;role='mrtof_analyzer_local_interface_convergence';status='success'
    qualification=[string]$metrics.qualification;comparison_count=[int]$metrics.comparison_count
    native_patch_face_nodes_evaluated=$metrics.native_patch_face_nodes_evaluated
    maximum_abs_dirichlet_potential_mismatch_V=[double]$metrics.maximum_abs_dirichlet_potential_mismatch_V
    maximum_abs_normal_field_mismatch_V_per_mm=$metrics.maximum_abs_normal_field_mismatch_V_per_mm
    reason='Matched 1-mm physical-lattice measurements are complete. No acceptance threshold is inferred.'
  })
  $config=Get-Content -Raw -LiteralPath $runConfig|ConvertFrom-Json -AsHashtable
  $config.inputs.interface_measurement_input=$measurementInput
  Write-RunJson -Path $runConfig -Depth 20 -Value $config
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $failureStage='capacity_terminal'
  [int64]$maximum=[int64](Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File|Measure-Object Length -Sum).Sum
  $capacityTerminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -ProtectedPaths @($package.artifact_run_dir,$geometryRun) -ProtectedCacheKeys @($families.cache_key) `
    -KnownMeasuredBytes ([int64]$capacityStartup.measured_after_bytes) -MaximumNewArtifactBytes $maximum
  $capacityTerminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json'
  Write-RunJson -Path $capacityTerminalPath -Depth 14 -Value $capacityTerminal
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success `
    -Software @('SIMION 2020','Python 3.11') `
    -Outputs (@($summary,$measurementInput,$result,$simionLog,$capacityStartupPath,$capacityTerminalPath,$retention)+$csvOutputs)
  $terminalized=$true
  Write-Host "MRTOF_ANALYZER_LOCAL_INTERFACE=PASS RUN_ID=$RunId COMPARISONS=$($metrics.comparison_count)"
} catch {
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
    -SummaryRole 'mrtof_analyzer_local_interface_convergence' -Reason $_.Exception.Message `
    -Software @('SIMION 2020','Python 3.11') -Status failed -FailureStage $failureStage;$terminalized=$true}
  throw
} finally {
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $hostOutcome -RunId $RunId}
  Remove-RunPackageExecutionAlias -Package $package
}
