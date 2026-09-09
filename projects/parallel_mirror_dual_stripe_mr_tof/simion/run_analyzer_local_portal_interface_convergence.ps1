[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$CenterTraceRunPath,
  [Parameter(Mandatory)][string]$CoarseCentralRunPath,
  [Parameter(Mandatory)][string]$CoarseBridgeRunPath,
  [Parameter(Mandatory)][string]$CoarseNegativeBridgeRunPath,
  [Parameter(Mandatory)][string]$CoarseMirrorRunPath,
  [Parameter(Mandatory)][string]$FineCentralRunPath,
  [Parameter(Mandatory)][string]$FineBridgeRunPath,
  [Parameter(Mandatory)][string]$FineNegativeBridgeRunPath,
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

$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$simion=if($SimionExe){[IO.Path]::GetFullPath($SimionExe)}else{Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
if(-not(Test-Path -LiteralPath $python -PathType Leaf)){throw "Python executable is missing: $python"}
if(-not(Test-Path -LiteralPath $simion -PathType Leaf)){throw "SIMION executable is missing: $simion"}
if([string]::IsNullOrWhiteSpace($RunId)){
  $RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__analysis__simion__analyzer-local-portal-interface'
}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
. (Join-Path $PSScriptRoot 'analyzer_local_family_support.ps1')
$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'analyzer_local_portal_interface_convergence' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass compact `
  -UseShortExecutionPath
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir
$logDir=$package.log_dir;$runConfig=$package.run_config;$summary=$package.summary
$artifactRoot=Join-Path $workspaceRoot 'artifacts';$cacheRoot=Join-Path $artifactRoot 'common\simion\pa_family_cache'
$lease=$null;$terminalized=$false;$hostOutcome='failed';$failureStage='preflight';$cacheAliases=@()
try {
  $traceRun=(Resolve-Path -LiteralPath $CenterTraceRunPath).Path
  $traceManifest=Join-Path $traceRun 'run_manifest.json'
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $traceManifest --require-status success|Out-Null
  if($LASTEXITCODE-ne 0){throw 'Centre portal-trace run is not verified success.'}
  $traceObservation=Get-Content -Raw -LiteralPath (Join-Path $traceRun 'results\two_prism_trial_observation.json')|ConvertFrom-Json -Depth 40
  if($traceObservation.patch_interface_diagnostic.qualification-ne'portal_seed_only__accepted_bundle_envelope_not_yet_defined' -or
     -not[bool]$traceObservation.patch_interface_diagnostic.only_z_faces_crossed){
    throw 'Centre trace is not a qualified z-face-only portal seed.'
  }
  $traceLog=Join-Path $traceRun 'logs\native_two_prism_flight.log'
  $traceTrial=Get-Content -Raw -LiteralPath (Join-Path $traceRun 'results\two_prism_trial_materialization.json')|ConvertFrom-Json -Depth 40
  $families=@(
    Get-VerifiedAnalyzerLocalFamily -SourceRunPath $CoarseCentralRunPath -ExpectedRegion central_transport -ExpectedScale 1.0 -Label coarse_central -PythonExe $python -RepoRoot $repoRoot
    Get-VerifiedAnalyzerLocalFamily -SourceRunPath $CoarseBridgeRunPath -ExpectedRegion stripe_mirror_bridge_positive -ExpectedScale 1.0 -Label coarse_bridge -PythonExe $python -RepoRoot $repoRoot
    Get-VerifiedAnalyzerLocalFamily -SourceRunPath $CoarseNegativeBridgeRunPath -ExpectedRegion stripe_mirror_bridge_negative -ExpectedScale 1.0 -Label coarse_negative_bridge -PythonExe $python -RepoRoot $repoRoot
    Get-VerifiedAnalyzerLocalFamily -SourceRunPath $CoarseMirrorRunPath -ExpectedRegion mirror_turn_positive -ExpectedScale 1.0 -Label coarse_mirror -PythonExe $python -RepoRoot $repoRoot
    Get-VerifiedAnalyzerLocalFamily -SourceRunPath $FineCentralRunPath -ExpectedRegion central_transport -ExpectedScale 0.5 -Label fine_central -PythonExe $python -RepoRoot $repoRoot
    Get-VerifiedAnalyzerLocalFamily -SourceRunPath $FineBridgeRunPath -ExpectedRegion stripe_mirror_bridge_positive -ExpectedScale 0.5 -Label fine_bridge -PythonExe $python -RepoRoot $repoRoot
    Get-VerifiedAnalyzerLocalFamily -SourceRunPath $FineNegativeBridgeRunPath -ExpectedRegion stripe_mirror_bridge_negative -ExpectedScale 0.5 -Label fine_negative_bridge -PythonExe $python -RepoRoot $repoRoot
    Get-VerifiedAnalyzerLocalFamily -SourceRunPath $FineMirrorRunPath -ExpectedRegion mirror_turn_positive -ExpectedScale 0.5 -Label fine_mirror -PythonExe $python -RepoRoot $repoRoot
  )
  $failureStage='freeze_inputs'
  $frozenTraceLog=Copy-VerifiedRunInput -Source $traceLog -Destination (Join-Path $inputDir 'center_portal_trace.log')
  $frozenInputs=[ordered]@{center_trace_manifest=$traceManifest;center_trace_log=$frozenTraceLog}
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
    -RequiredHeadroomBytes 52428800 -ProtectedPaths @($package.artifact_run_dir,$traceRun) `
    -ProtectedCacheKeys @($families.cache_key)
  $capacityStartupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $capacityStartupPath -Depth 14 -Value $capacityStartup

  $failureStage='probe_cache_families'
  foreach($family in $families){
    Resolve-AnalyzerLocalFamilyCacheGeneration -Family $family -PythonExe $python -RepoRoot $repoRoot -CacheRoot $cacheRoot|Out-Null
    $cacheAlias=New-RunExecutionAlias -TargetDirectory $family.generation_directory
    $cacheAliases+=$cacheAlias
    $family|Add-Member -NotePropertyName runtime_directory -NotePropertyValue $cacheAlias.execution_alias
    $frozenInputs["$($family.label)_cache_manifest"]=(Join-Path $family.generation_directory 'cache_manifest.json')
  }
  $groups=@($families[0].contract.response_recipes|ForEach-Object{[string]$_.group})
  if($groups.Count-ne 8 -or @($groups|Select-Object -Unique).Count-ne 8){throw 'Response group namespace differs.'}
  foreach($family in $families){
    $observed=@($family.contract.response_recipes|ForEach-Object{[string]$_.group})
    if(($observed-join '|')-ne($groups-join '|')){throw "Response group order differs: $($family.label)"}
  }
  $physicalVoltages=@($traceTrial.analyzer_electrode_voltages_v|ForEach-Object{[double]$_})
  $groupVoltages=@()
  foreach($recipe in @($families[0].contract.response_recipes)){
    $values=@($recipe.physical_ids|ForEach-Object{$physicalVoltages[[int]$_-1]})
    if(@($values|Where-Object{[math]::Abs($_-$values[0])-gt 1e-10}).Count-ne 0){
      throw "Physical electrode voltages differ inside response group $($recipe.group)."
    }
    $groupVoltages+=[double]$values[0]
  }
  $config=Get-Content -Raw -LiteralPath $runConfig|ConvertFrom-Json -AsHashtable
  $config.inputs=$frozenInputs
  $config.parameters=[ordered]@{
    scale_factors=@(1.0,0.5);seams=@(
      'negative_central_to_bridge','positive_central_to_bridge',
      'negative_bridge_to_mirror','positive_bridge_to_mirror'
    )
    response_groups=$groups;cache_keys=@($families.cache_key)
  }
  Write-RunJson -Path $runConfig -Depth 20 -Value $config
  Write-RunJson -Path $summary -Depth 8 -Value ([ordered]@{
    schema_version=1;role='mrtof_analyzer_local_portal_interface_convergence';status='checkpoint'
    reason='Verified center portal trace and eight local PA-family cache generations; seam sampling is starting.'
  })
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status checkpoint `
    -Software @('SIMION 2020','Python 3.11') -Outputs @($summary,$capacityStartupPath)|Out-Null

  $failureStage='prepare_portal_samples'
  $sampleReceipt=Join-Path $resultDir 'analyzer_local_portal_samples.json'
  $sampleDirectory=Join-Path $resultDir 'portal_samples'
  Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_portal_interface',
    'prepare-samples','--log',$frozenTraceLog,'--output-directory',$sampleDirectory,'--receipt',$sampleReceipt)|Out-Null
  $samples=Get-Content -Raw -LiteralPath $sampleReceipt|ConvertFrom-Json -Depth 20

  $failureStage='compare_local_fields'
  $comparisonScript=Join-Path $repoRoot 'common\simion\compare_pa_fields_at_samples.lua'
  $basisVoltageScript=Join-Path $repoRoot 'common\simion\measure_pa_basis_voltage.lua'
  $comparisonLog=Join-Path $logDir 'simion_portal_interface_comparisons.log'
  $comparisonRecords=@();$csvOutputs=@();$normalizationOutputs=@();$basisByScale=[ordered]@{}
  $lease=Enter-HostExecutionLease -Role SIMION -RunId $RunId
  foreach($scale in @(1.0,0.5)){
    $central=$families|Where-Object{$_.region-eq'central_transport' -and [double]$_.scale-eq$scale}
    $bridge=$families|Where-Object{$_.region-eq'stripe_mirror_bridge_positive' -and [double]$_.scale-eq$scale}
    $negativeBridge=$families|Where-Object{$_.region-eq'stripe_mirror_bridge_negative' -and [double]$_.scale-eq$scale}
    $mirror=$families|Where-Object{$_.region-eq'mirror_turn_positive' -and [double]$_.scale-eq$scale}
    if($null-eq$central -or $null-eq$bridge -or $null-eq$negativeBridge -or $null-eq$mirror){throw "Local family set is missing at scale $scale"}
    $token=[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:0.###}',$scale).Replace('.','p')
    $basisValues=@()
    foreach($family in @($central,$bridge,$negativeBridge,$mirror)){
      $activeLocalId=if($family.region-eq'mirror_turn_positive'){1}else{5}
      $basisCsv=Join-Path $resultDir "basis_voltage__${token}__$($family.region).csv"
      & $simion --nogui --noprompt lua $basisVoltageScript `
        (Join-Path $family.runtime_directory "$($family.contract.family_prefix).pa$activeLocalId") `
        (Join-Path $family.runtime_directory "$($family.contract.family_prefix).pa#") $activeLocalId $basisCsv `
        2>&1|Tee-Object -FilePath $comparisonLog -Append
      if($LASTEXITCODE-ne 0){throw "SIMION basis-voltage measurement failed: $scale/$($family.region)"}
      $basisValues+=[double](Import-Csv -LiteralPath $basisCsv).basis_voltage_V
      $normalizationOutputs+=$basisCsv
    }
    if(@($basisValues|Where-Object{[math]::Abs($_-$basisValues[0])-gt 1e-9}).Count-ne 0){
      throw "Local-family basis voltages differ at scale $scale"
    }
    $basisByScale[[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$scale)]=$basisValues[0]
    foreach($seam in @($samples.seams)){
      $familyA=$families|Where-Object{$_.region-eq([string]$seam.region_a) -and [double]$_.scale-eq$scale}
      $familyB=$families|Where-Object{$_.region-eq([string]$seam.region_b) -and [double]$_.scale-eq$scale}
      if($null-eq$familyA -or $null-eq$familyB){throw "Portal family pair is missing: $scale/$($seam.seam)"}
      $originA=(@($familyA.contract.patch_origin_project_mm|ForEach-Object{
        [string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$_)
      })-join ',')
      $originB=(@($familyB.contract.patch_origin_project_mm|ForEach-Object{
        [string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$_)
      })-join ',')
      foreach($group in $groups){
        $recipeA=$familyA.contract.response_recipes|Where-Object{$_.group-eq$group}
        $recipeB=$familyB.contract.response_recipes|Where-Object{$_.group-eq$group}
        if($null-eq$recipeA -or $null-eq$recipeB){throw "Response recipe is missing: $scale/$($seam.seam)/$group"}
        $csv=Join-Path $resultDir "portal__${token}__$($seam.seam)__${group}.csv"
        & $simion --nogui --noprompt lua $comparisonScript `
          (Join-Path $familyA.runtime_directory ([string]$recipeA.output_filename)) $originA `
          (Join-Path $familyB.runtime_directory ([string]$recipeB.output_filename)) $originB `
          ([string]$seam.transform_a) ([string]$seam.transform_b) ([string]$seam.sample_csv) $csv 2>&1|Tee-Object -FilePath $comparisonLog -Append
        if($LASTEXITCODE-ne 0){throw "SIMION portal comparison failed: $scale/$($seam.seam)/$group"}
        $csvOutputs+=$csv
        $comparisonRecords+=[ordered]@{
          scale_factor=$scale;seam=[string]$seam.seam;group=$group;csv_path=$csv
        }
      }
    }
  }
  Exit-HostExecutionLease -Lease $lease -Outcome success -RunId $RunId;$lease=$null;$hostOutcome='success'

  $measurementInput=Join-Path $inputDir 'portal_comparison_input.json'
  Write-RunJson -Path $measurementInput -Depth 12 -Value ([ordered]@{
    schema_version=1;role='mrtof_analyzer_local_portal_comparison_input'
    scale_factors=@(1.0,0.5);seams=@(
      'negative_central_to_bridge','positive_central_to_bridge',
      'negative_bridge_to_mirror','positive_bridge_to_mirror'
    )
    response_groups=$groups;comparisons=$comparisonRecords
    operating_group_voltages_V=$groupVoltages;basis_voltage_V_by_scale=$basisByScale
  })
  $failureStage='analyze_portals'
  $result=Join-Path $resultDir 'analyzer_local_portal_interface_convergence.json'
  Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_portal_interface',
    'analyze','--input',$measurementInput,'--output',$result)|Out-Null
  $metrics=Get-Content -Raw -LiteralPath $result|ConvertFrom-Json -Depth 40
  Write-RunJson -Path $summary -Depth 15 -Value ([ordered]@{
    schema_version=1;role='mrtof_analyzer_local_portal_interface_convergence';status='success'
    qualification=[string]$metrics.qualification;comparison_count=[int]$metrics.comparison_count
    maximum_abs_delta_potential_V=$metrics.maximum_abs_delta_potential_V
    maximum_abs_delta_ez_V_per_mm=$metrics.maximum_abs_delta_ez_V_per_mm
    operating_point=$metrics.operating_point
    reason='Central-to-bridge and bridge-to-mirror local fields were measured on four center-trajectory handoff seams. No acceptance threshold is inferred.'
  })
  $config=Get-Content -Raw -LiteralPath $runConfig|ConvertFrom-Json -AsHashtable
  $config.inputs.portal_comparison_input=$measurementInput
  Write-RunJson -Path $runConfig -Depth 20 -Value $config
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $failureStage='capacity_terminal'
  [int64]$maximum=[int64](Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File|Measure-Object Length -Sum).Sum
  $capacityTerminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -ProtectedPaths @($package.artifact_run_dir,$traceRun) -ProtectedCacheKeys @($families.cache_key) `
    -KnownMeasuredBytes ([int64]$capacityStartup.measured_after_bytes) -MaximumNewArtifactBytes $maximum
  $capacityTerminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json'
  Write-RunJson -Path $capacityTerminalPath -Depth 14 -Value $capacityTerminal
  $sampleCsvs=@($samples.seams|ForEach-Object{[string]$_.sample_csv})
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success `
    -Software @('SIMION 2020','Python 3.11') `
    -Outputs (@($summary,$sampleReceipt,$measurementInput,$result,$comparisonLog,$capacityStartupPath,$capacityTerminalPath,$retention)+$sampleCsvs+$normalizationOutputs+$csvOutputs)
  $terminalized=$true
  Write-Host "MRTOF_ANALYZER_LOCAL_PORTAL_INTERFACE=PASS RUN_ID=$RunId COMPARISONS=$($metrics.comparison_count)"
} catch {
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
    -SummaryRole 'mrtof_analyzer_local_portal_interface_convergence' -Reason $_.Exception.Message `
    -Software @('SIMION 2020','Python 3.11') -Status failed -FailureStage $failureStage;$terminalized=$true}
  throw
} finally {
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $hostOutcome -RunId $RunId}
  foreach($cacheAlias in $cacheAliases){
    Remove-RunExecutionAlias -ExecutionAlias $cacheAlias.execution_alias -TargetDirectory $cacheAlias.target_directory
  }
  Remove-RunPackageExecutionAlias -Package $package
}
