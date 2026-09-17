[CmdletBinding()]
param(
  [string]$ContractPath='',
  [string]$RecoverySourceRunPath='',
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
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$simion=if($SimionExe){[IO.Path]::GetFullPath($SimionExe)}else{Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
$contract=if($ContractPath){(Resolve-Path -LiteralPath $ContractPath).Path}else{Join-Path $projectRoot 'config\simion_candidate_two_zone.json'}
foreach($path in @($python,$simion,$contract)){if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Required input is missing: $path"}}
if(-not$RunId){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__build__simion__mrtof-accelerator-pa-family'}

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

function Invoke-SimionStage {
  param([Parameter(Mandatory)][string]$Stage,[Parameter(Mandatory)][string[]]$Arguments)
  Push-Location -LiteralPath $solverDir
  try {
    & $simion @Arguments 2>&1|Tee-Object -FilePath (Join-Path $logDir "$Stage.log")
    if($LASTEXITCODE-ne 0){throw "SIMION stage failed: $Stage"}
  } finally {Pop-Location}
}

function Assert-ManifestOutputIdentity {
  param([Parameter(Mandatory)]$Manifest,[Parameter(Mandatory)][string]$Path,[Parameter(Mandatory)][string]$Label)
  $resolved=(Resolve-Path -LiteralPath $Path).Path
  $records=@($Manifest.outputs|Where-Object{
    [string]::Equals([IO.Path]::GetFullPath([string]$_.path),$resolved,[StringComparison]::OrdinalIgnoreCase)
  })
  if($records.Count-ne1){throw "$Label is not uniquely frozen by the recovery manifest: $resolved"}
  $item=Get-Item -LiteralPath $resolved -Force
  $hash=(Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash
  if([int64]$records[0].bytes-ne[int64]$item.Length-or[string]$records[0].sha256-ne$hash){
    throw "$Label differs from its recovery manifest identity: $resolved"
  }
}

$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'accelerator_pa_family_build' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled `
  -RetentionClass solver_review `
  -RetentionReason 'Fine-grid accelerator PA family is required for native return-aperture review and the next assembled single-ion flight.' `
  -AdditionalDirectories @('simion') -UseShortExecutionPath
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir
$logDir=$package.log_dir;$solverDir=Join-Path $runDir 'simion';$runConfig=$package.run_config;$summary=$package.summary
$artifactRoot=Join-Path $workspaceRoot 'artifacts';$cacheRoot=Join-Path $artifactRoot 'common\simion\pa_family_cache'
$lease=$null;$terminalized=$false;$hostOutcome='failed';$failureStage='preflight'
$temporaryFamily=$null;$stabilityReceiptPath=$null
$recoverySourceRun=if($RecoverySourceRunPath){(Resolve-Path -LiteralPath $RecoverySourceRunPath).Path}else{''}
$frozenRecoveryManifest=$null;$frozenRecoveryIdentity=$null
$recoveryUsed=$false

# New-RunPackage may expose a short execution alias for SIMION. Persist only
# the corresponding canonical artifact path because the alias is removed in
# finally. This matches the established three-component package contract.
function ConvertTo-ArtifactRunPath {
  param([Parameter(Mandatory)][string]$Path)
  $full=[IO.Path]::GetFullPath($Path)
  $executionRoot=[IO.Path]::GetFullPath([string]$package.run_dir).TrimEnd([char[]]@(92,47))
  $artifactRunRoot=[IO.Path]::GetFullPath([string]$package.artifact_run_dir).TrimEnd([char[]]@(92,47))
  if($full.Equals($executionRoot,[StringComparison]::OrdinalIgnoreCase)){return $artifactRunRoot}
  if($full.StartsWith($executionRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){
    return $artifactRunRoot+$full.Substring($executionRoot.Length)
  }
  return $full
}
try {
  $lease=Enter-HostExecutionLease -Role SIMION -Stage accelerator_pa_prepare -RunId $RunId
  $failureStage='freeze_inputs'
  $frozenContract=Copy-VerifiedRunInput -Source $contract -Destination (Join-Path $inputDir 'simion_candidate_two_zone.json')
  $frozenBuilder=Copy-VerifiedRunInput -Source (Join-Path $PSScriptRoot 'build_component_pa.lua') -Destination (Join-Path $inputDir 'build_component_pa.lua')
  $frozenNativeTest=Copy-VerifiedRunInput -Source (Join-Path $projectRoot 'tests\simion\test_accelerator_native_geometry.lua') -Destination (Join-Path $inputDir 'test_accelerator_native_geometry.lua')
  $frozenStandaloneExporter=Copy-VerifiedRunInput -Source (Join-Path $repoRoot 'common\simion\export_standalone_pa.lua') -Destination (Join-Path $inputDir 'export_standalone_pa.lua')
  $frozenZeroBaseExporter=Copy-VerifiedRunInput -Source (Join-Path $repoRoot 'common\simion\export_fast_adjusted_standalone_pa.lua') -Destination (Join-Path $inputDir 'export_fast_adjusted_standalone_pa.lua')
  $frozenBasisMeasurement=Copy-VerifiedRunInput -Source (Join-Path $repoRoot 'common\simion\measure_pa_basis_voltage.lua') -Destination (Join-Path $inputDir 'measure_pa_basis_voltage.lua')
  $gem=Join-Path $solverDir 'mrtof_accelerator.gem'
  Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.split_candidate_geometry','--contract',$frozenContract,'--component','accelerator','--output',$gem)|Out-Null
  $samples=Join-Path $inputDir 'accelerator_geometry_samples.csv'
  Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.tests.simion.test_accelerator_geometry_samples','--contract',$frozenContract,'--output',$samples)|Out-Null

  $identityPath=Join-Path $resultDir 'pa_family_cache_identity.json'
  $probeText=Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_pa_family_cache',
    '--action','probe','--cache-root',$cacheRoot,'--contract',$frozenContract,'--component','accelerator',
    '--gem',$gem,'--simion-executable',$simion,'--simion-release','SIMION 2020','--run-simion-directory',$solverDir)
  $probe=$probeText|ConvertFrom-Json -Depth 30
  Write-RunJson -Path $identityPath -Depth 30 -Value $probe.identity
  $cacheDisposition=[string]$probe.disposition
  if($cacheDisposition-eq'corrupt'){throw "Accelerator PA cache is corrupt: $($probe.detail)"}
  $mesh=@($probe.identity.mesh.mm_per_gu|ForEach-Object{[double]$_})
  $span=@($probe.identity.grid_phase.pa_span_mm|ForEach-Object{[double]$_})
  [int64]$nodes=1
  for($axis=0;$axis-lt 3;$axis++){$nodes*=[int64]([math]::Round($span[$axis]/$mesh[$axis])+1)}
  [int64]$familyBytes=$nodes*8*11
  # The immutable accelerator payload contains the eleven native family arrays,
  # a zero-voltage standalone base, and nine standalone response arrays.  A
  # miss temporarily holds both the private build and its cache publication;
  # a hit needs no multi-gigabyte run-local family materialization.
  [int64]$standaloneBankBytes=$nodes*8*10
  [int64]$requiredBytes=if($cacheDisposition-eq'hit'){0}else{2*($familyBytes+$standaloneBankBytes)}
  $startupProtectedCacheKeys=if($cacheDisposition-eq'hit'){@([string]$probe.cache_key)}else{@()}
  $failureStage='capacity_preflight'
  $capacityStartup=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -RequiredHeadroomBytes $requiredBytes -ProtectedPaths (@($package.artifact_run_dir)+$(if($recoverySourceRun){@($recoverySourceRun)}else{@()})) `
    -ProtectedCacheKeys $startupProtectedCacheKeys
  $capacityStartupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $capacityStartupPath -Depth 14 -Value $capacityStartup

  if($cacheDisposition-eq'hit'){
    # A hit is already an immutable, manifest-bound generation.  Do not copy
    # or open its native family members; downstream consumers select only the
    # standalone bank declared by standalone_response_contract.
    $publication=$probe
  } else {
    $failureStage='build_pa_family'
    $temporaryFamily=Join-Path ([IO.Path]::GetTempPath()) ('mrtof_accelerator_pa_family_'+[guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $temporaryFamily|Out-Null
    if($recoverySourceRun){
      $failureStage='verify_recovery_source_family'
      $recoveryManifestPath=Join-Path $recoverySourceRun 'run_manifest.json'
      & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $recoveryManifestPath `
        --require-status success --require-project $projectId --require-mode accelerator_pa_family_build
      if($LASTEXITCODE-ne0){throw 'Accelerator recovery-source run manifest verification failed.'}
      $recoveryManifest=Get-Content -LiteralPath $recoveryManifestPath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 40
      $recoveryIdentityPath=Join-Path $recoverySourceRun 'results\pa_family_cache_identity.json'
      Assert-ManifestOutputIdentity -Manifest $recoveryManifest -Path $recoveryIdentityPath -Label 'recovery cache identity'
      $recoveryIdentity=Get-Content -LiteralPath $recoveryIdentityPath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 40
      foreach($field in @('geometry','gem','basis_namespace','mesh','grid_phase','surface','simion_identity')){
        $old=($recoveryIdentity.$field|ConvertTo-Json -Depth 30 -Compress)
        $current=($probe.identity.$field|ConvertTo-Json -Depth 30 -Compress)
        if($old-ne$current){throw "Recovery-source numerical identity differs at $field."}
      }
      foreach($field in @('mode','convergence_override','solutions')){
        if(($recoveryIdentity.refine_policy.$field|ConvertTo-Json -Compress)-ne($probe.identity.refine_policy.$field|ConvertTo-Json -Compress)){
          throw "Recovery-source refine policy differs at $field."
        }
      }
      foreach($field in @('build_component_pa_lua_sha256','build_component_basis_lua_sha256')){
        if([string]$recoveryIdentity.builder_identity.$field-ne[string]$probe.identity.builder_identity.$field){
          throw "Recovery-source builder identity differs at $field."
        }
      }
      $sourceGem=Join-Path $recoverySourceRun 'simion\mrtof_accelerator.gem'
      if((Get-FileHash -LiteralPath $sourceGem -Algorithm SHA256).Hash-ne(Get-FileHash -LiteralPath $gem -Algorithm SHA256).Hash){
        throw 'Recovery-source GEM differs from the current canonical accelerator GEM.'
      }
      $nativeNames=@('mrtof_accelerator.pa#','mrtof_accelerator.pa0')+@(1..9|ForEach-Object{"mrtof_accelerator.pa$_"})
      foreach($name in @('mrtof_accelerator.gem')+$nativeNames){
        $source=Join-Path $recoverySourceRun "simion\$name"
        Assert-ManifestOutputIdentity -Manifest $recoveryManifest -Path $source -Label "recovery native member $name"
        Copy-VerifiedRunInput -Source $source -Destination (Join-Path $temporaryFamily $name)|Out-Null
      }
      $frozenRecoveryManifest=Copy-VerifiedRunInput -Source $recoveryManifestPath -Destination (Join-Path $inputDir 'recovery_source_run_manifest.json')
      $frozenRecoveryIdentity=Copy-VerifiedRunInput -Source $recoveryIdentityPath -Destination (Join-Path $inputDir 'recovery_source_cache_identity.json')
      $recoveryUsed=$true
      $cacheDisposition='recovered_source_publish_pending'
    } else {
      Copy-VerifiedRunInput -Source $gem -Destination (Join-Path $temporaryFamily 'mrtof_accelerator.gem')|Out-Null
    }
    $raw=Join-Path $temporaryFamily 'mrtof_accelerator.pa#'
    if(-not$recoverySourceRun){
      $lease=Update-HostResourceStage -Lease $lease -Stage pa_refine `
        -Budget (Get-HostResourceBudget -Role SIMION -Stage pa_refine) -RetainedMemoryBytes 0
      try {
        Invoke-SimionStage -Stage 'build_accelerator_family' -Arguments @(
          '--nogui','--noprompt','lua',$frozenBuilder,$gem,$raw,
          ([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$mesh[0])),
          ([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$mesh[1])),
          ([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$mesh[2])),
          '1,2,3,4,5,6,7,8,9','1','1','9'
        )
      } finally {
        $lease=Update-HostResourceStage -Lease $lease -Stage accelerator_pa_prepare `
          -Budget (Get-HostResourceBudget -Role SIMION -Stage accelerator_pa_prepare) -RetainedMemoryBytes 0
      }
    }
    $failureStage='native_geometry'
    Invoke-SimionStage -Stage 'native_geometry' -Arguments @('--nogui','--noprompt','lua',$frozenNativeTest,$raw,$samples)
    $standalone=[object]$probe.standalone_response_contract
    if($null-eq$standalone -or @($standalone.responses).Count-ne 9){throw 'Accelerator standalone response contract is incomplete.'}
    $controller=Join-Path $temporaryFamily 'mrtof_accelerator.pa0'
    $base=Join-Path $temporaryFamily ([string]$standalone.base_filename)
    $baseReceipt=Join-Path $temporaryFamily ([string]$standalone.base_export_receipt_filename)
    $zeroVoltageArguments=@($standalone.zero_base_electrode_voltages_v|ForEach-Object{
      ([int]$_.electrode_id).ToString([Globalization.CultureInfo]::InvariantCulture)+'='+
        ([double]$_.voltage_v).ToString('R',[Globalization.CultureInfo]::InvariantCulture)
    })
    $failureStage='export_zero_standalone_base'
    Invoke-SimionStage -Stage 'export_zero_standalone_base' -Arguments (@(
      '--nogui','--noprompt','lua',$frozenZeroBaseExporter,$controller,$base,$baseReceipt
    )+$zeroVoltageArguments)
    foreach($response in @($standalone.responses)){
      $identifier=[int]$response.electrode_id
      $familyMember=Join-Path $temporaryFamily ([string]$response.family_member_filename)
      $standaloneResponse=Join-Path $temporaryFamily ([string]$response.standalone_response_filename)
      $normalizationReceipt=Join-Path $temporaryFamily ([string]$response.normalization_receipt_filename)
      $failureStage="export_standalone_response_$identifier"
      Invoke-SimionStage -Stage ("export_standalone_response_{0:D2}"-f$identifier) -Arguments @(
        '--nogui','--noprompt','lua',$frozenStandaloneExporter,$familyMember,$standaloneResponse
      )
      $failureStage="measure_standalone_response_$identifier"
      Invoke-SimionStage -Stage ("measure_standalone_response_{0:D2}"-f$identifier) -Arguments @(
        '--nogui','--noprompt','lua',$frozenBasisMeasurement,$standaloneResponse,$raw,
        ([string]$identifier),$normalizationReceipt
      )
    }
    $failureStage='verify_private_family_stability'
    $stabilityReceiptPath=Join-Path $resultDir 'private_family_stability.json'
    $stabilityText=Invoke-ProjectPython -Arguments @('-m','common.simion.cache_generation',
      '--directory',$temporaryFamily,'--cache-key',([string]$probe.cache_key),'--require-stable-inventory')
    $stability=$stabilityText|ConvertFrom-Json -Depth 30
    Write-RunJson -Path $stabilityReceiptPath -Depth 30 -Value ([ordered]@{
      schema_version=1;role='mrtof_accelerator_private_pa_family_stability';status='success'
      verification='two_consecutive_full_byte_inventories_before_cache_publication_v1'
      file_count=@($stability.files).Count;payload_sha256=[string]$stability.payload_sha256
    })
    $failureStage='publish_cache'
    $publishText=Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_pa_family_cache',
      '--action','publish','--cache-root',$cacheRoot,'--contract',$frozenContract,'--component','accelerator',
      '--gem',$gem,'--simion-executable',$simion,'--simion-release','SIMION 2020','--run-simion-directory',$temporaryFamily)
    $publication=$publishText|ConvertFrom-Json -Depth 30
    $cacheDisposition=[string]$publication.disposition
  }
  $publicationPath=Join-Path $resultDir 'pa_family_cache_result.json'
  Write-RunJson -Path $publicationPath -Depth 30 -Value $publication
  $lease=Update-HostResourceStage -Lease $lease -Stage accelerator_pa_postprocess `
    -Budget (Get-HostResourceBudget -Role SIMION -Stage accelerator_pa_postprocess) -RetainedMemoryBytes 0
  $summaryValue=[ordered]@{
    schema_version=1;role='mrtof_accelerator_pa_family';status='success'
    qualification='native_geometry_and_pa_family_only__flight_and_focus_recalibration_pending'
    topology='gridded_open_repeller_and_gridded_open_rear_ground_boundary'
    mesh_mm_per_gu=$mesh;grid_shape=@($span|ForEach-Object{0})
    cache_disposition=$cacheDisposition;cache_key=[string]$publication.cache_key
    cache_generation_directory=[string]$publication.generation_directory
    standalone_response_contract=$publication.standalone_response_contract
    reason='The contract-derived accelerator family is available and its return apertures passed native-node sampling. This does not prove ion transmission, time focus, or detector arrival.'
  }
  $summaryValue.grid_shape=@(
    [int]([math]::Round($span[0]/$mesh[0])+1),
    [int]([math]::Round($span[1]/$mesh[1])+1),
    [int]([math]::Round($span[2]/$mesh[2])+1)
  )
  Write-RunJson -Path $summary -Depth 20 -Value $summaryValue
  $config=Get-Content -Raw -LiteralPath $runConfig|ConvertFrom-Json -AsHashtable
  $config.inputs=[ordered]@{
    baseline_contract=ConvertTo-ArtifactRunPath $frozenContract
    canonical_gem=ConvertTo-ArtifactRunPath $gem
    builder=ConvertTo-ArtifactRunPath $frozenBuilder
    native_geometry_test=ConvertTo-ArtifactRunPath $frozenNativeTest
    native_samples=ConvertTo-ArtifactRunPath $samples
    cache_identity=ConvertTo-ArtifactRunPath $identityPath
    standalone_response_exporter=ConvertTo-ArtifactRunPath $frozenStandaloneExporter
    zero_base_exporter=ConvertTo-ArtifactRunPath $frozenZeroBaseExporter
    basis_normalization_measurement=ConvertTo-ArtifactRunPath $frozenBasisMeasurement
  }
  if($null-ne$frozenRecoveryManifest){
    $config.inputs.recovery_source_run_manifest=ConvertTo-ArtifactRunPath $frozenRecoveryManifest
    $config.inputs.recovery_source_cache_identity=ConvertTo-ArtifactRunPath $frozenRecoveryIdentity
  }
  $config.parameters=[ordered]@{component='accelerator';mesh_mm_per_gu=$mesh;grid_shape=$summaryValue.grid_shape;basis_ids=1..9;cache_key=[string]$publication.cache_key;standalone_response_contract=$publication.standalone_response_contract;native_family_source=if($recoveryUsed){'verified_immutable_prior_run_copy'}elseif($cacheDisposition-eq'hit'){'content_addressed_cache_hit'}else{'native_refine'}}
  Write-RunJson -Path $runConfig -Depth 30 -Value $config
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $failureStage='capacity_terminal'
  [int64]$runArtifactBytes=[int64](Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File|Measure-Object Length -Sum).Sum
  [int64]$publishedCacheBytes=0
  if($cacheDisposition-eq'published'){
    $generationDirectory=[IO.Path]::GetFullPath([string]$publication.generation_directory)
    $generationManifestPath=Join-Path $generationDirectory 'cache_manifest.json'
    $generationManifest=Get-Content -Raw -LiteralPath $generationManifestPath|ConvertFrom-Json -Depth 30
    if([string]$generationManifest.cache_key-ne[string]$publication.cache_key -or
       [string]$generationManifest.generation_sha256-ne[string]$publication.generation_sha256){
      throw 'Published accelerator cache inventory differs from its publication receipt.'
    }
    [int64]$payloadBytes=[int64](@($generationManifest.files)|Measure-Object -Property bytes -Sum).Sum
    [int64]$generationManifestBytes=[int64](Get-Item -LiteralPath $generationManifestPath).Length
    $cacheKeyDirectory=Split-Path -Parent (Split-Path -Parent $generationDirectory)
    $generationPointerPath=Join-Path $cacheKeyDirectory 'current_generation.json'
    [int64]$generationPointerBytes=[int64](Get-Item -LiteralPath $generationPointerPath).Length
    $publishedCacheBytes=$payloadBytes+$generationManifestBytes+$generationPointerBytes
  }
  [int64]$maximum=$runArtifactBytes+$publishedCacheBytes
  $capacityTerminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -ProtectedPaths @($package.artifact_run_dir) -ProtectedCacheKeys @([string]$publication.cache_key) `
    -KnownMeasuredBytes ([int64]$capacityStartup.measured_after_bytes) -MaximumNewArtifactBytes $maximum
  $capacityTerminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json'
  Write-RunJson -Path $capacityTerminalPath -Depth 14 -Value $capacityTerminal
  $outputs=@($summary,$identityPath,$publicationPath,$gem,$samples,$capacityStartupPath,$capacityTerminalPath,$retention)
  if($null-ne$stabilityReceiptPath){$outputs+=$stabilityReceiptPath}
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success `
    -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
  $terminalized=$true;$hostOutcome='success'
  Write-Host "MRTOF_ACCELERATOR_PA_FAMILY=PASS RUN_ID=$RunId CACHE=$cacheDisposition"
} catch {
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
    -SummaryRole 'mrtof_accelerator_pa_family' -Reason $_.Exception.Message -Software @('SIMION 2020','Python 3.11') -Status failed -FailureStage $failureStage;$terminalized=$true}
  throw
} finally {
  if($null-ne$temporaryFamily -and(Test-Path -LiteralPath $temporaryFamily -PathType Container)){
    Remove-GateTemporaryDirectory -Path $temporaryFamily -ExpectedNamePrefix 'mrtof_accelerator_pa_family_'
  }
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $hostOutcome -RunId $RunId}
  Remove-RunPackageExecutionAlias -Package $package
}
