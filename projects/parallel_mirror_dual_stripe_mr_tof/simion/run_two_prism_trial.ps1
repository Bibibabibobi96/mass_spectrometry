[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$GeometryReviewRunPath,
  [Parameter(Mandatory)][string]$MirrorRunPath,
  [Parameter(Mandatory)][string]$StripeRunPath,
  [Parameter(Mandatory)][string]$AcceleratorRunPath,
  [string]$AcceleratorFamilyRunPath='',
  [Parameter(Mandatory)][double]$Prism1VoltageV,
  [Parameter(Mandatory)][double]$Prism2VoltageV,
  [Nullable[double]]$Stripe1VoltageV=$null,
  [Nullable[double]]$Stripe2VoltageV=$null,
  [Nullable[double]]$Prism2ExtractionVoltageV=$null,
  [Nullable[double]]$Prism1ExtractionVoltageV=$null,
  [Nullable[double]]$PrismSwitchTimeUs=$null,
  [string]$ReferenceTransportRunPath='',
  [string]$LocalWorkbenchRunPath='',
  [switch]$ContinueMainDrift,
  [switch]$ConstrainXSymmetryPlane,
  [switch]$PulseAcceleratorUntilInitialExit,
  [string]$AcceleratorPulseSchedulePath='',
  [switch]$RetainGuiWorkbench,
  [string]$TrajectoryProfileId='',
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
  Push-Location -LiteralPath $repoRoot;$saved=$env:PYTHONPATH
  try{$env:PYTHONPATH=$repoRoot;& $python @Arguments;if($LASTEXITCODE-ne 0){throw "Python stage failed: $($Arguments -join ' ')"}}
  finally{$env:PYTHONPATH=$saved;Pop-Location}
}
function Invoke-SimionStage {
  param([string]$Stage,[string[]]$Arguments)
  Push-Location -LiteralPath $solverDir
  try{& $simion @Arguments 2>&1|Tee-Object -FilePath (Join-Path $logDir "$Stage.log");if($LASTEXITCODE-ne 0){throw "SIMION stage failed: $Stage"}}
  finally{Pop-Location}
}
function Remove-TemporarySolverDirectory {
  param([string]$Path)
  if([string]::IsNullOrWhiteSpace($Path)-or-not(Test-Path -LiteralPath $Path)){return}
  $resolved=[IO.Path]::GetFullPath($Path)
  $temporaryRoot=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([IO.Path]::DirectorySeparatorChar)+[IO.Path]::DirectorySeparatorChar
  if(-not$resolved.StartsWith($temporaryRoot,[StringComparison]::OrdinalIgnoreCase)){throw "Refusing to remove non-temporary solver directory: $resolved"}
  Remove-Item -LiteralPath $resolved -Recurse -Force
}
$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$simion=if($SimionExe){[IO.Path]::GetFullPath($SimionExe)}else{Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
if(-not(Test-Path -LiteralPath $python -PathType Leaf)){throw "Python executable is missing: $python"}
if(-not(Test-Path -LiteralPath $simion -PathType Leaf)){throw "SIMION executable is missing: $simion"}
foreach($value in @($Prism1VoltageV,$Prism2VoltageV)){if([double]::IsNaN($value)-or[double]::IsInfinity($value)){throw 'Prism voltages must be finite'}}
if($PulseAcceleratorUntilInitialExit-and-not[string]::IsNullOrWhiteSpace($AcceleratorPulseSchedulePath)){throw 'PulseAcceleratorUntilInitialExit and AcceleratorPulseSchedulePath are mutually exclusive.'}
$acceleratorPulseRequested=[bool]$PulseAcceleratorUntilInitialExit-or-not[string]::IsNullOrWhiteSpace($AcceleratorPulseSchedulePath)
if (($null -eq $Stripe1VoltageV) -ne ($null -eq $Stripe2VoltageV)) { throw 'Stripe1VoltageV and Stripe2VoltageV must be supplied together.' }
if($null-ne$Prism2ExtractionVoltageV-and[string]::IsNullOrWhiteSpace($ReferenceTransportRunPath)){throw 'Prism extraction requires ReferenceTransportRunPath.'}
if($null-eq$Prism2ExtractionVoltageV-and-not[string]::IsNullOrWhiteSpace($ReferenceTransportRunPath)){throw 'ReferenceTransportRunPath is only valid for prism extraction.'}
foreach($value in @($Stripe1VoltageV,$Stripe2VoltageV)){if($null-ne$value-and([double]::IsNaN($value)-or[double]::IsInfinity($value))){throw 'Stripe voltages must be finite'}}
foreach($value in @($Prism1ExtractionVoltageV,$Prism2ExtractionVoltageV,$PrismSwitchTimeUs)){if($null-ne$value-and([double]::IsNaN($value)-or[double]::IsInfinity($value))){throw 'Prism switching parameters must be finite'}}
if($null-ne$Prism1ExtractionVoltageV-and$null-eq$Prism2ExtractionVoltageV){throw 'Prism1ExtractionVoltageV requires a P2 extraction switch.'}
if($null-ne$PrismSwitchTimeUs-and$PrismSwitchTimeUs-le 0){throw 'PrismSwitchTimeUs must be positive.'}
if($null-ne$Prism2ExtractionVoltageV-or$null-ne$Prism1ExtractionVoltageV-or$null-ne$PrismSwitchTimeUs){
  throw 'P1/P2 voltage switching is superseded for this MR-TOF: extraction must use the unchanged static prism voltages and the reciprocal P2-to-P1 return path.'
}
if($acceleratorPulseRequested-and-not$ContinueMainDrift){throw 'Accelerator pulsing requires ContinueMainDrift.'}
if($PulseAcceleratorUntilInitialExit-and[string]::IsNullOrWhiteSpace($LocalWorkbenchRunPath)){throw 'Initial-exit-triggered accelerator pulsing requires LocalWorkbenchRunPath for exact instance tracking.'}
if($acceleratorPulseRequested-and[string]::IsNullOrWhiteSpace($AcceleratorFamilyRunPath)){throw 'Accelerator pulsing requires AcceleratorFamilyRunPath for a complete writable family materialization.'}
$geometryRun=(Resolve-Path -LiteralPath $GeometryReviewRunPath).Path
$mirrorRun=(Resolve-Path -LiteralPath $MirrorRunPath).Path
$stripeRun=(Resolve-Path -LiteralPath $StripeRunPath).Path
$acceleratorRun=(Resolve-Path -LiteralPath $AcceleratorRunPath).Path
$acceleratorPulseSchedule=if([string]::IsNullOrWhiteSpace($AcceleratorPulseSchedulePath)){$null}else{(Resolve-Path -LiteralPath $AcceleratorPulseSchedulePath).Path}
$acceleratorFamilyRun=if([string]::IsNullOrWhiteSpace($AcceleratorFamilyRunPath)){$null}else{(Resolve-Path -LiteralPath $AcceleratorFamilyRunPath).Path}
$referenceRun=if([string]::IsNullOrWhiteSpace($ReferenceTransportRunPath)){$null}else{(Resolve-Path -LiteralPath $ReferenceTransportRunPath).Path}
$localWorkbenchRun=if([string]::IsNullOrWhiteSpace($LocalWorkbenchRunPath)){$null}else{(Resolve-Path -LiteralPath $LocalWorkbenchRunPath).Path}
$geometrySimion=Join-Path $geometryRun 'simion'
$acceleratorSimion=Join-Path $acceleratorRun 'simion'
$acceleratorFamilySimion=if($null-eq$acceleratorFamilyRun){$null}else{Join-Path $acceleratorFamilyRun 'simion'}
$geometryManifest=Join-Path $geometryRun 'run_manifest.json'
$mirrorManifest=Join-Path $mirrorRun 'run_manifest.json'
$stripeManifest=Join-Path $stripeRun 'run_manifest.json'
$acceleratorManifest=Join-Path $acceleratorRun 'run_manifest.json'
$acceleratorFamilyManifest=if($null-eq$acceleratorFamilyRun){$null}else{Join-Path $acceleratorFamilyRun 'run_manifest.json'}
$referenceManifest=if($null-eq$referenceRun){$null}else{Join-Path $referenceRun 'run_manifest.json'}
$localWorkbenchManifest=if($null-eq$localWorkbenchRun){$null}else{Join-Path $localWorkbenchRun 'run_manifest.json'}
foreach($manifest in @($geometryManifest,$mirrorManifest,$stripeManifest,$acceleratorManifest,$acceleratorFamilyManifest,$referenceManifest,$localWorkbenchManifest)){
  if($null-eq$manifest){continue}
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $manifest --require-status success
  if($LASTEXITCODE-ne 0){throw "Upstream run manifest is not verified success: $manifest"}
}
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__sim__simion__two-prism-trial-n1'}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
. (Join-Path $repoRoot 'common\simion\short_pa_path_support.ps1')
. (Join-Path $PSScriptRoot 'analyzer_local_family_support.ps1')
$retentionClass=if($RetainGuiWorkbench){'solver_review'}else{'compact'}
$retentionReason=if($RetainGuiWorkbench){'User-requested SIMION GUI review package retaining the exact flown IOB and its run-private operating PA0 files.'}else{''}
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'finite_3d_two_prism_voltage_trial' -Software @('SIMION 2020','Python 3.11') `
  -RetentionContractEnabled -RetentionClass $retentionClass -RetentionReason $retentionReason `
  -AdditionalDirectories @('simion') -UseShortExecutionPath
$runDir=$package.run_dir;$resultDir=$package.result_dir;$logDir=$package.log_dir;$solverDir=Join-Path $runDir 'simion'
$artifactSolverDir=Join-Path ([string]$package.artifact_run_dir) 'simion'
$runConfig=$package.run_config;$summary=$package.summary;$artifactRoot=Join-Path $workspaceRoot 'artifacts'
$terminalized=$false;$failureStage='preflight';$lease=$null;$hostOutcome='failed';$temporarySolverDir=$null;$basisLinkDir=$null;$iobInputCopyDir=$null
$operatingCacheKey=$null;$operatingCacheGeneration=$null;$operatingCacheIdentityPath=$null
$guiWorkbenchIob=$null;$guiWorkbenchReceipt=$null
$acceleratorFamilyReceipt=$null
$earlyOperatingCacheProbe=$null;$earlyOperatingCacheHit=$false;$earlyChangedIndexCount=0
try{
  $sourceAnalyzer=Join-Path $geometrySimion 'mrtof_analyzer.pa0'
  $sourceAccelerator=Join-Path $acceleratorSimion 'mrtof_accelerator.pa0'
  $sourceDetector=Join-Path $geometrySimion 'mrtof_detector.pa#'
  $acceleratorFamilySources=@()
  $localWorkbenchConfig=$null;$localFamilies=@();$localBaseMaterialization=$null;$temporaryLocalPaths=@()
  $localCacheSentinelPaths=@();$localCacheSentinelHashes=@()
  if($null-ne$localWorkbenchRun){
    $localWorkbenchConfig=Get-Content -Raw -LiteralPath (Join-Path $localWorkbenchRun 'run_config.json')|ConvertFrom-Json -Depth 40
    if($localWorkbenchConfig.mode-ne'analyzer_local_replacement_workbench'){throw 'LocalWorkbenchRunPath is not a local replacement workbench.'}
    $sourceAnalyzer=[string]$localWorkbenchConfig.inputs.global_analyzer_pa0
    $localBaseMaterialization=Get-Content -Raw -LiteralPath (Join-Path $localWorkbenchRun 'inputs\two_prism_trial_materialization.json')|ConvertFrom-Json -Depth 30
    $familySpecs=@(
      @('mirror_turn_negative','negative_mirror'),@('stripe_mirror_bridge_negative','negative_bridge'),
      @('central_transport','central'),@('stripe_mirror_bridge_positive','positive_bridge'),
      @('mirror_turn_positive','positive_mirror')
    )
    [double]$localScale=$localWorkbenchConfig.parameters.local_mesh_mm_per_gu[0]
    for($familyIndex=0;$familyIndex-lt$familySpecs.Count;$familyIndex++){
      $familyRun=Split-Path -Parent ([string]$localWorkbenchConfig.inputs.local_family_manifests[$familyIndex])
      $family=Get-VerifiedAnalyzerLocalFamily -SourceRunPath $familyRun -ExpectedRegion $familySpecs[$familyIndex][0] -ExpectedScale $localScale -Label $familySpecs[$familyIndex][1] -PythonExe $python -RepoRoot $repoRoot
      $localFamilies+=$family
    }
    if($null-ne$Stripe1VoltageV){
      $earlyTarget=@([double]$Stripe1VoltageV,[double]$Stripe2VoltageV,[double]$Prism1VoltageV,[double]$Prism2VoltageV)
      $earlyBase=@([double]$localBaseMaterialization.stripe_biases_v[0],[double]$localBaseMaterialization.stripe_biases_v[1],[double]$localBaseMaterialization.prism_voltages_v[0],[double]$localBaseMaterialization.prism_voltages_v[1])
      $earlyChangedIndexCount=@(0..3|Where-Object{[math]::Abs($earlyTarget[$_]-$earlyBase[$_])-gt 1e-15}).Count
      if($earlyChangedIndexCount-gt 0){
        $operatingCacheIdentityPath=Join-Path $resultDir 'local_operating_pa_cache_identity.json'
        $earlyTargetText=(@($earlyTarget|ForEach-Object{[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$_)})-join',')
        $earlyOperatingCacheProbe=(@(Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.local_operating_pa_cache',
          '--action','probe','--local-workbench-run',$localWorkbenchRun,("--target-voltages-v={0}"-f$earlyTargetText),
          '--cache-root',(Join-Path $artifactRoot 'common\simion\pa_family_cache'),'--identity-output',$operatingCacheIdentityPath))-join"`n")|ConvertFrom-Json
        $operatingCacheKey=[string]$earlyOperatingCacheProbe.cache_key
        $earlyOperatingCacheHit=$earlyOperatingCacheProbe.disposition-eq'hit'
        if($earlyOperatingCacheProbe.disposition-eq'corrupt'){throw "Local operating PA cache is corrupt: $($earlyOperatingCacheProbe.detail)"}
      }
    }
  }
  if($acceleratorPulseRequested){
    $acceleratorFamilySources=@(
      (Join-Path $acceleratorFamilySimion 'mrtof_accelerator.pa#'),
      (Join-Path $acceleratorFamilySimion 'mrtof_accelerator.pa0')
    )+@(1..9|ForEach-Object{Join-Path $acceleratorFamilySimion ("mrtof_accelerator.pa{0}"-f$_)})
  }
  $reuseFrozenWorkbenchAnalyzer=($null-ne$localWorkbenchRun-and$earlyChangedIndexCount-eq 0-and-not$RetainGuiWorkbench)
  $workbenchAnalyzer=if($reuseFrozenWorkbenchAnalyzer){Join-Path $localWorkbenchRun 'simion\mrtof_analyzer.pa0'}else{$null}
  if($reuseFrozenWorkbenchAnalyzer-and-not(Test-Path -LiteralPath $workbenchAnalyzer -PathType Leaf)){
    throw "Frozen local workbench analyser is missing: $workbenchAnalyzer"
  }
  $reviewedContract=Join-Path $geometrySimion 'simion_prototype_contract.json'
  $selectedContract=Join-Path $acceleratorSimion 'accelerator_focus_voltage_trial.json'
  $trajectoryContractSource=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\config\simion_candidate_two_zone.json'
  $mirrorSummary=Join-Path $mirrorRun 'summary.json'
  $stripeSummary=Join-Path $stripeRun 'summary.json'
  $acceleratorReceipt=Join-Path $acceleratorRun 'results\accelerator_focus_voltage_trial_receipt.json'
  $referenceReceiptSource=if($null-eq$referenceRun){$null}else{Join-Path $referenceRun 'results\two_prism_trial_materialization.json'}
  $referenceLogSource=if($null-eq$referenceRun){$null}else{Join-Path $referenceRun 'logs\native_two_prism_flight.log'}
  $trialTool=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_simion_trial.py'
  $voltageizerSource=Join-Path $PSScriptRoot 'voltageize_analyzer_pa0.lua'
  $iobBuilderSource=Join-Path $PSScriptRoot 'build_three_component_iob.lua'
  $localIobBuilderSource=Join-Path $PSScriptRoot 'build_local_refinement_iob.lua'
  $basisAdjusterSource=Join-Path $repoRoot 'common\simion\adjust_operating_pa_from_basis.lua'
  $basisVoltageSource=Join-Path $repoRoot 'common\simion\measure_pa_basis_voltage.lua'
  $iobSeedSource=Join-Path $repoRoot 'common\simion\assets\iob_instance_seeds\3_instance_seed.iob'
  $localIobSeedSource=Join-Path $repoRoot 'common\simion\assets\iob_instance_seeds\8_instance_seed.iob'
  $placeholderSources=@(1..8|ForEach-Object{Join-Path $repoRoot ('common\simion\assets\iob_instance_seeds\iob_seed_placeholder_{0:D2}.pa0'-f$_)})
  $programSource=Join-Path $PSScriptRoot 'mrtof_candidate.lua'
  $counterSource=Join-Path $PSScriptRoot 'mirror_cycle_counter.lua'
  $mapSource=Join-Path $PSScriptRoot 'candidate_voltage_map.lua'
  $launcherSource=Join-Path $PSScriptRoot 'run_iob_flight.lua'
  foreach($path in @($sourceAnalyzer,$sourceAccelerator,$sourceDetector,$acceleratorFamilySources,$reviewedContract,$selectedContract,$trajectoryContractSource,$mirrorSummary,$stripeSummary,$acceleratorReceipt,$trialTool,$voltageizerSource,$iobBuilderSource,$localIobBuilderSource,$basisAdjusterSource,$basisVoltageSource,$iobSeedSource,$localIobSeedSource,$placeholderSources,$programSource,$counterSource,$mapSource,$launcherSource)){
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Required P1/P2 trial input is missing: $path"}
  }
  $failureStage='capacity_preflight'
  [int64]$requiredBytes=0;[int64]$transientBytes=0
  foreach($path in @($reviewedContract,$selectedContract,$trajectoryContractSource,$mirrorSummary,$stripeSummary,$acceleratorReceipt,$trialTool,$voltageizerSource,$iobBuilderSource,$localIobBuilderSource,$basisAdjusterSource,$basisVoltageSource,$iobSeedSource,$localIobSeedSource,$placeholderSources,$programSource,$counterSource,$mapSource,$launcherSource)){$requiredBytes+=[int64](Get-Item -LiteralPath $path).Length}
  # RequiredHeadroomBytes governs retained artifact growth. Temporary solver
  # PA0s instead raise the physical-free-space floor and are deleted before a
  # compact run is terminalized. This matches the repository integration
  # runner's separation of artifact quota from transient staging capacity.
  if(-not$reuseFrozenWorkbenchAnalyzer){
    $analyzerOperatingBytes=[int64](Get-Item -LiteralPath $sourceAnalyzer).Length
    if($RetainGuiWorkbench){$requiredBytes+=$analyzerOperatingBytes}else{$transientBytes+=$analyzerOperatingBytes}
  }
  if($null-ne$localWorkbenchRun){
    $capacityLocalNames=@('local_negative_mirror.pa0','local_negative_bridge.pa0','local_central.pa0','local_positive_bridge.pa0','local_positive_mirror.pa0')
    [int64]$localOperatingBytes=0;[int64]$largestLocalOperatingBytes=0
    for($familyIndex=0;$familyIndex-lt$localFamilies.Count;$familyIndex++){
      $baseOperatingBytes=[int64](Get-Item -LiteralPath (Join-Path $localWorkbenchRun "simion\$($capacityLocalNames[$familyIndex])")).Length
      $localOperatingBytes+=$baseOperatingBytes
      $largestLocalOperatingBytes=[math]::Max($largestLocalOperatingBytes,$baseOperatingBytes)
    }
    if($reuseFrozenWorkbenchAnalyzer){
      # The matching compact centre trial references all six already-frozen
      # workbench PA0s and writes none of them into this run.
    }elseif($earlyOperatingCacheHit){
      if($RetainGuiWorkbench){$requiredBytes+=$localOperatingBytes}else{$transientBytes+=$localOperatingBytes}
    }else{
      # Each perturbation retains five temporary outputs.  Per region, SIMION
      # also needs one private operating base plus one independently constructed
      # standalone response for every changed voltage.  Runtime never opens a
      # native `.paN` family member.
      [int64]$perRegionProjectionBytes=(1+$earlyChangedIndexCount)*$largestLocalOperatingBytes
      if($RetainGuiWorkbench){
        $requiredBytes+=2*$localOperatingBytes
        $transientBytes+=$perRegionProjectionBytes
      }else{
        $transientBytes+=$localOperatingBytes+$perRegionProjectionBytes
      }
    }
  }
  if($acceleratorPulseRequested){
    [int64]$acceleratorFamilyBytes=0
    foreach($path in $acceleratorFamilySources){$acceleratorFamilyBytes+=[int64](Get-Item -LiteralPath $path).Length}
    if($RetainGuiWorkbench){$requiredBytes+=$acceleratorFamilyBytes}else{$transientBytes+=$acceleratorFamilyBytes}
  }
  # Every PA bound into a newly-built IOB is first projected to a private
  # standalone input. Account for those copies only after all local PA sizes
  # are known; required/transient budgets were initialized immediately above.
  [int64]$iobProjectionBytes=[int64](Get-Item -LiteralPath $sourceAnalyzer).Length+
    [int64](Get-Item -LiteralPath $sourceDetector).Length
  if(-not$acceleratorPulseRequested){$iobProjectionBytes+=[int64](Get-Item -LiteralPath $sourceAccelerator).Length}
  if($null-ne$localWorkbenchRun){$iobProjectionBytes+=$localOperatingBytes}
  if($RetainGuiWorkbench){$requiredBytes+=$iobProjectionBytes}else{$transientBytes+=$iobProjectionBytes}
  $protectedPaths=@($package.artifact_run_dir)
  if($null-ne$localWorkbenchRun){$protectedPaths+=@($localWorkbenchRun);if(-not$earlyOperatingCacheHit){$protectedPaths+=@($localFamilies.generation_directory)}}
  $startupProtectedCacheKeys=if($earlyOperatingCacheHit){@($operatingCacheKey)}else{@($localFamilies.cache_key)}
  $minimumFreeGiB=([double]([int64](500GB)+$requiredBytes+$transientBytes)/1GB)
  $startup=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -MinimumFreeGiB $minimumFreeGiB `
    -RequiredHeadroomBytes $requiredBytes -ProtectedPaths $protectedPaths `
    -ProtectedCacheKeys $startupProtectedCacheKeys
  $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json';Write-RunJson -Path $startupPath -Depth 14 -Value $startup
  $failureStage='freeze_small_inputs'
  $contract=Copy-RequiredInput $selectedContract (Join-Path $solverDir 'accelerator_focus_voltage_trial.json') 'selected-energy contract'
  $trajectoryContract=Copy-RequiredInput $trajectoryContractSource (Join-Path $solverDir 'trajectory_numerics_contract.json') 'trajectory numerics contract'
  $reviewed=Copy-RequiredInput $reviewedContract (Join-Path $solverDir 'simion_prototype_contract.json') 'reviewed geometry contract'
  $mirrorLocal=Copy-RequiredInput $mirrorSummary (Join-Path $solverDir 'mirror_exact_k_summary.json') 'exact-K mirror summary'
  $stripeLocal=Copy-RequiredInput $stripeSummary (Join-Path $solverDir 'dual_stripe_exact_k_summary.json') 'exact-K Stripe summary'
  $acceleratorLocal=Copy-RequiredInput $acceleratorReceipt (Join-Path $solverDir 'accelerator_focus_voltage_trial_receipt.json') 'accelerator voltage receipt'
  $referenceLocal=$null;$referenceLogLocal=$null
  if($null-ne$referenceRun){
    $referenceLocal=Copy-RequiredInput $referenceReceiptSource (Join-Path $solverDir 'reference_transport_materialization.json') 'reference transport receipt'
    $referenceLogLocal=Copy-RequiredInput $referenceLogSource (Join-Path $logDir 'reference_transport.log') 'reference transport log'
  }
  foreach($pair in @(
    @($programSource,'mrtof_three_component_candidate.lua'),@($counterSource,'mrtof_three_component_candidate.mirror_cycle_counter.lua'),
    @($mapSource,'mrtof_three_component_candidate.voltage_map.lua'),@($launcherSource,'run_iob_flight.lua'),
    @($iobBuilderSource,'build_three_component_iob.lua'),@($localIobBuilderSource,'build_local_refinement_iob.lua'),
    @($basisAdjusterSource,'adjust_operating_pa_from_basis.lua'),@($basisVoltageSource,'measure_pa_basis_voltage.lua'),
    @($iobSeedSource,'3_instance_seed.iob'),@($localIobSeedSource,'8_instance_seed.iob'),
    @($placeholderSources[0],'iob_seed_placeholder_01.pa0'),@($placeholderSources[1],'iob_seed_placeholder_02.pa0'),
    @($placeholderSources[2],'iob_seed_placeholder_03.pa0'),@($placeholderSources[3],'iob_seed_placeholder_04.pa0'),
    @($placeholderSources[4],'iob_seed_placeholder_05.pa0'),@($placeholderSources[5],'iob_seed_placeholder_06.pa0'),
    @($placeholderSources[6],'iob_seed_placeholder_07.pa0'),@($placeholderSources[7],'iob_seed_placeholder_08.pa0'),
    @($voltageizerSource,'voltageize_analyzer_pa0.lua'),
    @($trialTool,'two_prism_simion_trial.py'))){
    Copy-RequiredInput $pair[0] (Join-Path $solverDir $pair[1]) $pair[1]|Out-Null
  }
  $fly2Input=Join-Path $solverDir 'downstream_trial_source.input.fly2'
  $sidecar=Join-Path $solverDir 'mrtof_three_component_candidate.operating_point.lua'
  $trialReceipt=Join-Path $resultDir 'two_prism_trial_materialization.json'
  $failureStage='materialize_trial'
  $materializeArguments=@('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial','materialize',
    '--contract',$contract,'--trajectory-contract',$trajectoryContract,'--reviewed-contract',$reviewed,'--mirror-summary',$mirrorLocal,'--stripe-summary',$stripeLocal,
    '--accelerator-receipt',$acceleratorLocal,'--prism-1-v',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$Prism1VoltageV)),
    '--prism-2-v',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$Prism2VoltageV)),
    '--fly2',$fly2Input,'--sidecar',$sidecar,'--receipt',$trialReceipt)
  if($null-ne$Stripe1VoltageV){
    $materializeArguments+=@('--stripe-1-v',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$Stripe1VoltageV)),
      '--stripe-2-v',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$Stripe2VoltageV)))
  }
  if($ContinueMainDrift){$materializeArguments+='--continue-main-drift'}
  if($PulseAcceleratorUntilInitialExit){$materializeArguments+='--pulse-accelerator-until-initial-exit'}
  if($null-ne$acceleratorPulseSchedule){$materializeArguments+=@('--accelerator-pulse-schedule',$acceleratorPulseSchedule)}
  if($null-ne$Prism2ExtractionVoltageV){
    $materializeArguments+=@('--prism-2-extraction-v',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$Prism2ExtractionVoltageV)),
      '--reference-transport-receipt',$referenceLocal,'--reference-transport-log',$referenceLogLocal)
    if($null-ne$PrismSwitchTimeUs){$materializeArguments+=@('--prism-switch-time-us',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$PrismSwitchTimeUs)))}
    if($null-ne$Prism1ExtractionVoltageV){$materializeArguments+=@('--prism-1-extraction-v',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$Prism1ExtractionVoltageV)))}
  }
  if($ConstrainXSymmetryPlane){$materializeArguments+='--constrain-x-symmetry-plane'}
  if(-not[string]::IsNullOrWhiteSpace($TrajectoryProfileId)){$materializeArguments+=@('--trajectory-profile-id',$TrajectoryProfileId)}
  Invoke-ProjectPython -Arguments $materializeArguments
  $trial=Get-Content -LiteralPath $trialReceipt -Raw -Encoding UTF8|ConvertFrom-Json
  $temporarySolverDir=if($RetainGuiWorkbench){Join-Path $artifactSolverDir 'gui_workbench'}else{Join-Path ([IO.Path]::GetTempPath()) ('mrtof_downstream_'+[guid]::NewGuid().ToString('N'))}
  New-Item -ItemType Directory -Path $temporarySolverDir|Out-Null
  $temporaryAcceleratorFamily=@()
  if($acceleratorPulseRequested){
    $failureStage='materialize_writable_accelerator_family'
    $acceleratorFamilyMembers=@()
    foreach($sourceFamilyMember in $acceleratorFamilySources){
      $destinationFamilyMember=Join-Path $temporarySolverDir ([IO.Path]::GetFileName($sourceFamilyMember))
      Copy-VerifiedRunInput -Source $sourceFamilyMember -Destination $destinationFamilyMember -VerificationAttempts 3|Out-Null
      $temporaryAcceleratorFamily+=$destinationFamilyMember
      $sourceMemberHash=(Get-FileHash -LiteralPath $sourceFamilyMember -Algorithm SHA256).Hash
      $destinationMemberHash=(Get-FileHash -LiteralPath $destinationFamilyMember -Algorithm SHA256).Hash
      if($sourceMemberHash-ne$destinationMemberHash){throw "Writable accelerator family copy differs from source: $sourceFamilyMember"}
      $acceleratorFamilyMembers+=[ordered]@{name=[IO.Path]::GetFileName($sourceFamilyMember);source_path=$sourceFamilyMember;source_sha256=$sourceMemberHash;run_local_initial_sha256=$destinationMemberHash;bytes=[int64](Get-Item -LiteralPath $sourceFamilyMember).Length}
    }
    $acceleratorFamilyReceipt=Join-Path $resultDir 'writable_accelerator_family_materialization.json'
    Write-RunJson -Path $acceleratorFamilyReceipt -Depth 8 -Value ([ordered]@{
      schema_version=1;role='mrtof_run_local_writable_accelerator_pa_family';status='success';
      purpose=if($PulseAcceleratorUntilInitialExit){'single_center_initial_exit_triggered_pulse'}else{'frozen_global_time_accelerator_pulse'};refine_performed=$false;
      source_accelerator_family_run_manifest=$acceleratorFamilyManifest;source_family_read_only=$true;
      run_local_family_disposable=(-not[bool]$RetainGuiWorkbench);members=$acceleratorFamilyMembers
    })
  }
  $temporaryAnalyzer=if($reuseFrozenWorkbenchAnalyzer){$workbenchAnalyzer}else{Join-Path $temporarySolverDir 'mrtof_analyzer.pa0'}
  $temporaryIob=Join-Path $temporarySolverDir 'mrtof_three_component_candidate.iob'
  $temporaryP2Basis=$null;$temporaryP1Basis=$null
  $posePath=Join-Path $resultDir 'resolved_iob_pose.json'
  $poseCode="import json,sys; from pathlib import Path; from projects.parallel_mirror_dual_stripe_mr_tof.analysis.split_candidate_geometry import resolve_split_iob_origins; p=Path(sys.argv[1]); c=json.loads(p.read_text(encoding='utf-8')); Path(sys.argv[2]).write_text(json.dumps({'origins_mm':resolve_split_iob_origins(p),'mesh_mm_per_gu':c['simion']['component_mesh_mm_per_gu']},indent=2)+'\n',encoding='utf-8')"
  Invoke-ProjectPython -Arguments @('-c',$poseCode,$reviewed,$posePath)
  $pose=Get-Content -LiteralPath $posePath -Raw -Encoding UTF8|ConvertFrom-Json
  $originArguments=@()
  foreach($name in @('analyzer','accelerator','detector')){foreach($value in @($pose.origins_mm.$name)){$originArguments+=[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$value)}}
  $upstreamPaths=@($sourceAnalyzer,$sourceAccelerator,$sourceDetector,$acceleratorFamilySources)
  if($null-ne$acceleratorPulseSchedule){$upstreamPaths+=@($acceleratorPulseSchedule)}
  if($reuseFrozenWorkbenchAnalyzer){$upstreamPaths+=@($workbenchAnalyzer)}
  $upstreamHashes=@($upstreamPaths|ForEach-Object{(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash})
  $voltageSourceHash=if($reuseFrozenWorkbenchAnalyzer){
    (Get-FileHash -LiteralPath $workbenchAnalyzer -Algorithm SHA256).Hash
  }else{
    (Get-FileHash -LiteralPath $sourceAnalyzer -Algorithm SHA256).Hash
  }
  if($null-ne$Prism2ExtractionVoltageV){
    $sourceP2Basis=[IO.Path]::ChangeExtension($sourceAnalyzer,'.pa17')
    $temporaryP2Basis=[IO.Path]::ChangeExtension($temporaryAnalyzer,'.pa17')
    Copy-RequiredInput $sourceP2Basis $temporaryP2Basis 'P2 electrode-17 basis array'|Out-Null
    if($null-ne$Prism1ExtractionVoltageV){
      $sourceP1Basis=[IO.Path]::ChangeExtension($sourceAnalyzer,'.pa16')
      $temporaryP1Basis=[IO.Path]::ChangeExtension($temporaryAnalyzer,'.pa16')
      Copy-RequiredInput $sourceP1Basis $temporaryP1Basis 'P1 electrode-16 basis array'|Out-Null
    }
  }
  $failureStage='prepare_operating_analyzer';$lease=Enter-HostExecutionLease -Role SIMION -RunId $RunId
  if(-not$reuseFrozenWorkbenchAnalyzer){
    $voltageArguments=@('--nogui','--noprompt','lua',(Join-Path $solverDir 'voltageize_analyzer_pa0.lua'),$sourceAnalyzer,$temporaryAnalyzer)+@($trial.analyzer_electrode_voltages_v|ForEach-Object{[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$_)})
    Invoke-SimionStage -Stage 'voltageize_temporary_analyzer' -Arguments $voltageArguments
  }
  $temporaryAnalyzerHash=(Get-FileHash -LiteralPath $temporaryAnalyzer -Algorithm SHA256).Hash
  $voltageReceipt=Join-Path $resultDir 'temporary_analyzer_voltageization_receipt.json'
  $localAdjustmentReceipts=@();$localOperatingCacheReceipt=$null
  if($null-ne$localWorkbenchRun){
    $failureStage='adjust_local_operating_replacements'
    $baseDownstream=@([double]$localBaseMaterialization.stripe_biases_v[0],[double]$localBaseMaterialization.stripe_biases_v[1],[double]$localBaseMaterialization.prism_voltages_v[0],[double]$localBaseMaterialization.prism_voltages_v[1])
    $targetDownstream=@([double]$trial.stripe_biases_v[0],[double]$trial.stripe_biases_v[1],[double]$trial.prism_voltages_v[0],[double]$trial.prism_voltages_v[1])
    $deltaVoltages=@();$changedIndices=@();for($index=0;$index-lt 4;$index++){$delta=[double]$targetDownstream[$index]-[double]$baseDownstream[$index];$deltaVoltages+=$delta;if([math]::Abs($delta)-gt 1e-15){$changedIndices+=$index}}
    $localNames=@('local_negative_mirror.pa0','local_negative_bridge.pa0','local_central.pa0','local_positive_bridge.pa0','local_positive_mirror.pa0')
    $temporaryLocalPaths=@()
    if($changedIndices.Count-eq 0){
      for($index=0;$index-lt$localFamilies.Count;$index++){$temporaryLocalPaths+=Join-Path $localWorkbenchRun "simion\$($localNames[$index])"}
    }else{
      $operatingCacheRoot=Join-Path $artifactRoot 'common\simion\pa_family_cache'
      $operatingCacheIdentityPath=Join-Path $resultDir 'local_operating_pa_cache_identity.json'
      $targetVoltageText=(@($targetDownstream|ForEach-Object{[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$_)})-join',')
      $cacheProbe=if($null-ne$earlyOperatingCacheProbe){$earlyOperatingCacheProbe}else{(@(Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.local_operating_pa_cache',
        '--action','probe','--local-workbench-run',$localWorkbenchRun,("--target-voltages-v={0}"-f$targetVoltageText),
        '--cache-root',$operatingCacheRoot,'--identity-output',$operatingCacheIdentityPath))-join"`n")|ConvertFrom-Json}
      $operatingCacheKey=[string]$cacheProbe.cache_key
      if($cacheProbe.disposition-eq'hit'){
        $cacheMaterialization=(@(Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.local_operating_pa_cache',
          '--action','materialize','--identity-input',$operatingCacheIdentityPath,
          '--cache-root',$operatingCacheRoot,'--destination-directory',$temporarySolverDir))-join"`n")|ConvertFrom-Json
        $operatingCacheGeneration=[string]$cacheMaterialization.generation_directory
        foreach($name in $localNames){$temporaryLocalPaths+=Join-Path $temporarySolverDir $name}
        $localOperatingCacheReceipt=[ordered]@{disposition='hit';cache_key=$operatingCacheKey;generation_directory=$operatingCacheGeneration;outputs=@($localNames);refine_performed=$false}
      }elseif($cacheProbe.disposition-eq'miss'){
        foreach($family in $localFamilies){
          Resolve-AnalyzerLocalFamilyCacheGeneration -Family $family -PythonExe $python -RepoRoot $repoRoot -CacheRoot $operatingCacheRoot|Out-Null
          Assert-AnalyzerLocalFamilyCacheReadOnly -Family $family
          $localCacheSentinelPaths+=Join-Path $family.generation_directory ("{0}.pa#"-f([string]$family.contract.family_prefix))
        }
        $localCacheSentinelHashes=@($localCacheSentinelPaths|ForEach-Object{(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash})
        $normalizationCsv=Join-Path $resultDir 'global_basis_voltage.csv'
        Invoke-SimionStage -Stage 'measure_global_basis_voltage' -Arguments @('--nogui','--noprompt','lua',(Join-Path $solverDir 'measure_pa_basis_voltage.lua'),[IO.Path]::ChangeExtension($sourceAnalyzer,'.pa2'),[IO.Path]::ChangeExtension($sourceAnalyzer,'.pa#'),2,$normalizationCsv)
        $basisVoltage=[double](Import-Csv -LiteralPath $normalizationCsv).basis_voltage_V
        $basisText=(@($changedIndices|ForEach-Object{[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$basisVoltage)})-join',')
        $deltaText=(@($changedIndices|ForEach-Object{[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$deltaVoltages[$_])})-join',')
        for($index=0;$index-lt$localFamilies.Count;$index++){
          $family=$localFamilies[$index]
          # The cache publishes true standalone response PAs during family
          # construction.  Only short ordinary copies of those `.pa` files are
          # exposed to this runtime; native `.paN` members remain unopened.
          $basisLinkDir=Join-Path ([IO.Path]::GetTempPath()) ('simion_pa_links_'+[guid]::NewGuid().ToString('N'))
          New-Item -ItemType Directory -Path $basisLinkDir|Out-Null
          $privateBasisPaths=@()
          foreach($changedIndex in $changedIndices){
            $responseId=5+$changedIndex
            $recipes=@($family.contract.response_recipes|Where-Object{[int]$_.local_id-eq$responseId})
            if($recipes.Count-ne 1){throw "Local PA family must declare exactly one standalone response recipe for electrode $responseId"}
            $responseSource=Join-Path $family.generation_directory ([string]$recipes[0].standalone_response_filename)
            $privateBasisPaths+=New-ShortPaCopy -Source $responseSource -Destination (Join-Path $basisLinkDir ("r{0}.pa"-f$responseId))
          }
          $basisPaths=($privateBasisPaths-join'|')
          $privateOperatingBase=Join-Path $temporarySolverDir ("family{0}_operating_base.pa0"-f($index+1))
          Copy-VerifiedRunInput -Source (Join-Path $localWorkbenchRun "simion\$($localNames[$index])") -Destination $privateOperatingBase -VerificationAttempts 3|Out-Null
          $temporaryLocal=Join-Path $temporarySolverDir $localNames[$index]
          Invoke-SimionStage -Stage ("adjust_local_{0}"-f$family.label) -Arguments @('--nogui','--noprompt','lua',(Join-Path $solverDir 'adjust_operating_pa_from_basis.lua'),$privateOperatingBase,$temporaryLocal,$basisPaths,$basisText,$deltaText)
          $temporaryLocalPaths+=$temporaryLocal
          $localAdjustmentReceipts+=[ordered]@{region=$family.region;source_cache_generation=$family.generation_directory;basis_projection='independently_constructed_standalone_response';native_family_member_opened=$false;basis_voltage_v=$basisVoltage;downstream_voltage_deltas_v=@($deltaVoltages);temporary_output_sha256=(Get-FileHash -LiteralPath $temporaryLocal -Algorithm SHA256).Hash;refine_performed=$false}
          Remove-ShortPaCopyDirectory -Path $basisLinkDir
          $basisLinkDir=$null
          # The private base cannot affect later regions or publication.
          foreach($scratchPath in @($privateOperatingBase)){
            if(Test-Path -LiteralPath $scratchPath -PathType Leaf){Remove-Item -LiteralPath $scratchPath -Force}
          }
        }
        if($RetainGuiWorkbench){
          $cachePublication=(@(Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.local_operating_pa_cache',
            '--action','publish','--identity-input',$operatingCacheIdentityPath,
            '--cache-root',$operatingCacheRoot,'--source-directory',$temporarySolverDir))-join"`n")|ConvertFrom-Json
          $operatingCacheGeneration=[string]$cachePublication.generation_directory
          $localOperatingCacheReceipt=[ordered]@{disposition=[string]$cachePublication.disposition;cache_key=$operatingCacheKey;generation_directory=$operatingCacheGeneration;outputs=@($localNames);refine_performed=$false}
        }else{
          $localOperatingCacheReceipt=[ordered]@{disposition='transient_miss_not_published';cache_key=$operatingCacheKey;generation_directory=$null;outputs=@($localNames);refine_performed=$false}
        }
      }else{throw "Local operating PA cache is corrupt: $($cacheProbe.detail)"}
    }
  }
  $voltageMethod=if($reuseFrozenWorkbenchAnalyzer){
    'verified_frozen_workbench_global_and_local_pa0_reuse'
  }elseif($null-eq$localWorkbenchRun){
    'SIMION_PA_object_fast_adjust_save_as'
  }elseif($null-ne$localOperatingCacheReceipt-and$localOperatingCacheReceipt.disposition-eq'transient_miss_not_published'){
    'global_fast_adjust_plus_transient_local_basis_deltas'
  }elseif($null-ne$localOperatingCacheReceipt){
    'global_fast_adjust_plus_content_addressed_local_operating_pa0'
  }elseif($localAdjustmentReceipts.Count-eq 0){
    'global_fast_adjust_plus_reused_local_baseline_pa0'
  }else{
    'global_fast_adjust_plus_nonzero_local_basis_deltas'
  }
  Write-RunJson -Path $voltageReceipt -Depth 14 -Value ([ordered]@{
    schema_version=1
    role='mrtof_temporary_analyzer_voltageization'
    status='success'
    method=$voltageMethod
    source_pa0=if($reuseFrozenWorkbenchAnalyzer){$workbenchAnalyzer}else{$sourceAnalyzer}
    source_sha256=$voltageSourceHash
    temporary_output_sha256=$temporaryAnalyzerHash
    electrode_voltages_v=@($trial.analyzer_electrode_voltages_v)
    local_operating_cache=$localOperatingCacheReceipt
    local_adjustments=$localAdjustmentReceipts
    source_family_read_only=$true
    refine_performed=$false
    temporary_output_retained=[bool]$RetainGuiWorkbench
  })
  # Never expose a frozen workbench/cache PA directly to SIMION.  IOB loading
  # can write a PA after the command appears to finish.  Compact runs therefore
  # use verified disposable short-name copies; GUI-review runs retain private
  # run-local copies and never bind the upstream files into their IOB.
  # Extend the integrity snapshot after the local operating PA set has been
  # resolved. This covers both frozen zero-delta workbench inputs and newly
  # materialized/adjusted private PA0s through IOB build and flight.
  foreach($path in $temporaryLocalPaths){
    $upstreamPaths+=$path
    $upstreamHashes+=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
  }
  $failureStage='project_iob_pa_inputs'
  $iobProjectionRoot=$artifactSolverDir
  if(-not$RetainGuiWorkbench){
    $iobInputCopyDir=Join-Path ([IO.Path]::GetTempPath()) ('simion_pa_links_'+[guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $iobInputCopyDir|Out-Null
    $iobProjectionRoot=$iobInputCopyDir
  }
  function Copy-IobPaInput {
    param([Parameter(Mandatory)][string]$Source,[Parameter(Mandatory)][string]$Name)
    $destination=Join-Path $iobProjectionRoot $Name
    if($RetainGuiWorkbench){
      return Copy-VerifiedRunInput -Source $Source -Destination $destination -VerificationAttempts 3
    }
    return New-ShortPaCopy -Source $Source -Destination $destination
  }
  $iobAnalyzerInput=Copy-IobPaInput -Source $temporaryAnalyzer -Name 'iob_input_analyzer.pa'
  $iobAcceleratorInput=if($acceleratorPulseRequested){
    Join-Path $temporarySolverDir 'mrtof_accelerator.pa0'
  }else{
    Copy-IobPaInput -Source $sourceAccelerator -Name 'iob_input_accelerator.pa'
  }
  $iobDetectorInput=Copy-IobPaInput -Source $sourceDetector -Name 'iob_input_detector.pa'
  $iobLocalInputs=@()
  if($temporaryLocalPaths.Count-gt 0){
    foreach($index in 0..($temporaryLocalPaths.Count-1)){
      $iobLocalInputs+=Copy-IobPaInput -Source $temporaryLocalPaths[$index] -Name ("iob_input_local_{0}.pa"-f($index+1))
    }
  }
  $failureStage='build_temporary_iob'
  $iobProgramPath=if($RetainGuiWorkbench){Join-Path $artifactSolverDir 'mrtof_three_component_candidate.lua'}else{Join-Path $solverDir 'mrtof_three_component_candidate.lua'}
  $iobFly2Path=if($RetainGuiWorkbench){Join-Path $artifactSolverDir 'downstream_trial_source.input.fly2'}else{$fly2Input}
  if($null-eq$localWorkbenchRun){
    $buildArguments=@('--nogui','--noprompt','lua',(Join-Path $solverDir 'build_three_component_iob.lua'),'--',
      (Join-Path $solverDir '3_instance_seed.iob'),$iobAnalyzerInput,$iobAcceleratorInput,$iobDetectorInput,$temporaryIob,
      $iobProgramPath,$iobFly2Path)+$originArguments+@('read_only_voltageized')
  }else{
    $localConfigSource=Join-Path $localWorkbenchRun 'simion\mrtof_local_replacement.local_refinement.lua'
    $localConfig=Copy-RequiredInput $localConfigSource (Join-Path $solverDir 'local_trial_refinement.lua') 'local replacement sidecar'
    $iobLocalConfig=if($RetainGuiWorkbench){Join-Path $artifactSolverDir 'local_trial_refinement.lua'}else{$localConfig}
    $localOrigins=@();$localOrigins+=,@($pose.origins_mm.analyzer)
    foreach($family in $localFamilies){$localOrigins+=,@($family.contract.patch_origin_project_mm)}
    $localOrigins+=,@($pose.origins_mm.accelerator);$localOrigins+=,@($pose.origins_mm.detector)
    $localOriginArguments=@();foreach($origin in $localOrigins){foreach($value in $origin){$localOriginArguments+=[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$value)}}
    $buildArguments=@('--nogui','--noprompt','lua',(Join-Path $solverDir 'build_local_refinement_iob.lua'),'--',(Join-Path $solverDir '8_instance_seed.iob'),$iobAnalyzerInput)+$iobLocalInputs+@($iobAcceleratorInput,$iobDetectorInput,$temporaryIob,$iobProgramPath,$iobFly2Path,$iobLocalConfig)+$localOriginArguments
  }
  Invoke-SimionStage -Stage 'build_temporary_iob' -Arguments $buildArguments
  $temporaryFly2=[IO.Path]::ChangeExtension($temporaryIob,'.fly2')
  if(-not(Test-RunFilesIdentical -Left $fly2Input -Right $temporaryFly2)){throw 'IOB companion Fly2 differs from the frozen downstream-trial source'}
  if(@(Compare-Object $upstreamHashes @($upstreamPaths|ForEach-Object{(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash})).Count-ne 0){throw 'Read-only IOB build changed an upstream PA'}
  if($localCacheSentinelPaths.Count-and@(Compare-Object $localCacheSentinelHashes @($localCacheSentinelPaths|ForEach-Object{(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash})).Count-ne 0){throw 'Temporary IOB build changed an immutable local PA cache sentinel'}
  $failureStage='native_two_prism_flight'
  Invoke-SimionStage -Stage 'native_two_prism_flight' -Arguments @('--nogui','--noprompt','lua',(Join-Path $solverDir 'run_iob_flight.lua'),$temporaryIob)
  if(@(Compare-Object $upstreamHashes @($upstreamPaths|ForEach-Object{(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash})).Count-ne 0){throw 'Runtime Fast Adjust changed an upstream PA'}
  if($localCacheSentinelPaths.Count-and@(Compare-Object $localCacheSentinelHashes @($localCacheSentinelPaths|ForEach-Object{(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash})).Count-ne 0){throw 'SIMION flight changed immutable local PA-family bookkeeping'}
  if($localCacheSentinelPaths.Count){foreach($family in $localFamilies){Resolve-AnalyzerLocalFamilyCacheGeneration -Family $family -PythonExe $python -RepoRoot $repoRoot -CacheRoot (Join-Path $artifactRoot 'common\simion\pa_family_cache')|Out-Null}}
  if($null-ne$iobInputCopyDir){Remove-ShortPaCopyDirectory -Path $iobInputCopyDir;$iobInputCopyDir=$null}
  $rawLog=Join-Path $logDir 'native_two_prism_flight.log';$observation=Join-Path $resultDir 'two_prism_trial_observation.json'
  $failureStage='analyze_trial'
  Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial','analyze','--log',$rawLog,'--trial-receipt',$trialReceipt,'--output',$observation)
  $observed=Get-Content -LiteralPath $observation -Raw -Encoding UTF8|ConvertFrom-Json
  $observedResiduals=if($null-ne$observed.PSObject.Properties['residuals']){$observed.residuals}else{$null}
  $observedExtraction=if($null-ne$observed.PSObject.Properties['extraction_diagnostic']){$observed.extraction_diagnostic}else{$null}
  $detectorHit=($null-ne$observedExtraction-and$observedExtraction.status-eq'detector_hit')
  $pulseClause=if($PulseAcceleratorUntilInitialExit){' The accelerator remained energized through the first exit and was then grounded using the measured single-centre exit event; this event-triggered schedule is not valid for a bunch.'}elseif($null-ne$acceleratorPulseSchedule){' The single centre ion consumed one separately frozen global pulse-off schedule. Bunch qualification remains pending a frozen multi-particle source and a schedule derived from that cohort safe-exit envelope.'}else{' The accelerator remained static.'}
  $summaryReason=if($detectorHit){'The fixed reviewed geometry was flown once from the physical 5-eV pre-acceleration state with unchanged static prism voltages.'+$pulseClause+' A natural reciprocal detector hit proves only the single-centre event chain; target-K closure remains independently required.'}else{'The fixed reviewed geometry was flown once from the physical 5-eV pre-acceleration state with unchanged static prism voltages.'+$pulseClause+' No natural reciprocal detector hit was observed, so the prototype event chain remains open.'}
  $summaryValue=[ordered]@{schema_version=1;role='mrtof_finite_3d_two_prism_voltage_trial';status='success';qualification='single_center_trial__not_an_operating_point';stripe_biases_v=@($trial.stripe_biases_v);prism_voltages_v=@($Prism1VoltageV,$Prism2VoltageV);accelerator_pulse=$trial.accelerator_pulse;accelerator_pulse_diagnostic=$observed.accelerator_pulse_diagnostic;transport_status=$observed.status;extraction_diagnostic=$observedExtraction;residuals=$observedResiduals;reason=$summaryReason}
  Write-RunJson -Path $summary -Value $summaryValue
  $config=Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($RetainGuiWorkbench){
    $guiWorkbenchIob=$temporaryIob
    $guiWorkbenchReceipt=Join-Path $resultDir 'gui_workbench_receipt.json'
    $guiFiles=@(Get-ChildItem -LiteralPath $temporarySolverDir -File|Sort-Object Name|ForEach-Object{[ordered]@{name=$_.Name;bytes=[int64]$_.Length}})
    Write-RunJson -Path $guiWorkbenchReceipt -Depth 14 -Value ([ordered]@{
      schema_version=1;role='simion_gui_review_workbench';status='success';qualification='single_center_trial__not_an_operating_point';
      iob_path=$guiWorkbenchIob;iob_sha256=(Get-FileHash -LiteralPath $guiWorkbenchIob -Algorithm SHA256).Hash;
      global_operating_pa0_path=$temporaryAnalyzer;global_operating_pa0_sha256=$temporaryAnalyzerHash;
      local_operating_cache_key=$operatingCacheKey;local_operating_cache_generation=$operatingCacheGeneration;
      source_accelerator_pa0=$sourceAccelerator;source_detector_pa=$sourceDetector;files=$guiFiles
    })
    # The IOB stores the absolute paths passed to SIMION. Keeping this exact
    # directory in place is therefore part of the review artifact contract.
    $temporarySolverDir=$null
  }else{Remove-TemporarySolverDirectory -Path $temporarySolverDir;$temporarySolverDir=$null}
  $config.inputs=[ordered]@{
    geometry_run_manifest=$geometryManifest
    mirror_run_manifest=$mirrorManifest
    stripe_run_manifest=$stripeManifest
    accelerator_run_manifest=$acceleratorManifest
    accelerator_family_run_manifest=$acceleratorFamilyManifest
    accelerator_pulse_schedule=$acceleratorPulseSchedule
    reference_transport_run_manifest=$referenceManifest
    local_workbench_run_manifest=$localWorkbenchManifest
    trajectory_numerics_contract=$trajectoryContract
    iob_builder=if($null-eq$localWorkbenchRun){Join-Path $solverDir 'build_three_component_iob.lua'}else{Join-Path $solverDir 'build_local_refinement_iob.lua'}
    iob_seed=if($null-eq$localWorkbenchRun){Join-Path $solverDir '3_instance_seed.iob'}else{Join-Path $solverDir '8_instance_seed.iob'}
    local_refinement_sidecar=if($null-eq$localWorkbenchRun){$null}else{$localConfig}
    flight_program=Join-Path $solverDir 'mrtof_three_component_candidate.lua'
    mirror_cycle_counter=Join-Path $solverDir 'mrtof_three_component_candidate.mirror_cycle_counter.lua'
    voltage_map=Join-Path $solverDir 'mrtof_three_component_candidate.voltage_map.lua'
    flight_launcher=Join-Path $solverDir 'run_iob_flight.lua'
    trial_materializer=Join-Path $solverDir 'two_prism_simion_trial.py'
    analyzer_voltageizer=Join-Path $solverDir 'voltageize_analyzer_pa0.lua'
    basis_adjuster=if($null-eq$localWorkbenchRun){$null}else{Join-Path $solverDir 'adjust_operating_pa_from_basis.lua'}
    basis_voltage_measurement=if($null-eq$localWorkbenchRun){$null}else{Join-Path $solverDir 'measure_pa_basis_voltage.lua'}
    read_only_analyzer_pa0=if($reuseFrozenWorkbenchAnalyzer){$workbenchAnalyzer}else{$sourceAnalyzer}
    read_only_accelerator_pa0=$sourceAccelerator
    read_only_accelerator_family=if($acceleratorPulseRequested){@($acceleratorFamilySources)}else{$null}
    writable_accelerator_family_materialization=$acceleratorFamilyReceipt
    read_only_detector_pa=$sourceDetector
    trial_materialization=$trialReceipt
    frozen_source_fly2=$fly2Input
    local_operating_pa_cache_identity=$operatingCacheIdentityPath
    gui_workbench_iob=$guiWorkbenchIob
    gui_workbench_receipt=$guiWorkbenchReceipt
  }
  $config.parameters.prism_1_voltage_v=$Prism1VoltageV;$config.parameters.prism_2_voltage_v=$Prism2VoltageV;$config.parameters.stripe_biases_v=@($trial.stripe_biases_v);$config.parameters.continue_main_drift=[bool]$ContinueMainDrift;$config.parameters.accelerator_pulse=$trial.accelerator_pulse;$config.parameters.pa_binding_mode=if($null-eq$localWorkbenchRun){'temporary_voltageized_analyzer__immutable_family'}elseif($null-ne$localOperatingCacheReceipt-and$localOperatingCacheReceipt.disposition-eq'transient_miss_not_published'){'global_fast_adjust_plus_transient_local_basis_deltas__no_refine'}elseif($null-ne$localOperatingCacheReceipt){'global_fast_adjust_plus_content_addressed_local_operating_pa0'}elseif($localAdjustmentReceipts.Count-eq 0){'global_fast_adjust_plus_reused_local_baseline_pa0'}else{'global_fast_adjust_plus_nonzero_local_basis_deltas__no_refine'};$config.parameters.local_extraction_field_handoff=$null;$config.parameters.constrain_x_symmetry_plane=[bool]$ConstrainXSymmetryPlane;$config.parameters.trajectory_profile=$trial.trajectory_profile;$config.parameters.prism_switch=$trial.prism_switch;$config.parameters.gui_workbench_retained=[bool]$RetainGuiWorkbench;Write-RunJson -Path $runConfig -Value $config
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $failureStage='capacity_terminal';$maximum=[int64](Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File|Measure-Object Length -Sum).Sum
  $protectedCacheKeys=@($localFamilies.cache_key);if($null-ne$operatingCacheGeneration){$protectedCacheKeys+=$operatingCacheKey}
  $terminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -ProtectedPaths @($package.artifact_run_dir) -ProtectedCacheKeys $protectedCacheKeys `
    -KnownMeasuredBytes ([int64]$startup.measured_after_bytes) -MaximumNewArtifactBytes $maximum
  $terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  $manifestOutputs=@($summary,$rawLog,$observation,$trialReceipt,$voltageReceipt,$posePath,$startupPath,$terminalPath,$retention)
  if($null-ne$acceleratorFamilyReceipt){$manifestOutputs+=$acceleratorFamilyReceipt}
  if($null-ne$operatingCacheIdentityPath){$manifestOutputs+=$operatingCacheIdentityPath}
  if($null-ne$guiWorkbenchReceipt){$manifestOutputs+=@($guiWorkbenchReceipt,$guiWorkbenchIob)}
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success -Software @('SIMION 2020','Python 3.11') -Outputs $manifestOutputs
  $terminalized=$true;$hostOutcome='success';Write-Host "MRTOF_TWO_PRISM_TRIAL=PASS RUN_ID=$RunId TRANSPORT=$($observed.status)"
}catch{
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_finite_3d_two_prism_voltage_trial' -Reason $_.Exception.Message -Software @('SIMION 2020','Python 3.11') -Status failed -FailureStage $failureStage;$terminalized=$true};throw
}finally{
  if(-not$terminalized-and(Test-Path -LiteralPath $runConfig -PathType Leaf)){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_finite_3d_two_prism_voltage_trial' -Reason 'Runner stopped before terminal evidence publication.' -Software @('SIMION 2020','Python 3.11') -Status interrupted -FailureStage $failureStage;$hostOutcome='interrupted'}
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $hostOutcome -RunId $RunId};Remove-RunPackageExecutionAlias -Package $package
  if($null-ne$iobInputCopyDir){Remove-ShortPaCopyDirectory -Path $iobInputCopyDir}
  if($null-ne$basisLinkDir){Remove-ShortPaCopyDirectory -Path $basisLinkDir}
  if($null-ne$temporarySolverDir){Remove-TemporarySolverDirectory -Path $temporarySolverDir}
}
