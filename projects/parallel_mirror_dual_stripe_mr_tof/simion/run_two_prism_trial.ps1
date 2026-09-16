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
  [string]$LocalWorkbenchRunPath='',
  [switch]$PulseAcceleratorUntilInitialExit,
  [switch]$BootstrapGlobalOperatingPa,
  [string]$AcceleratorPulseSchedulePath='',
  [string]$BunchSourceReceiptPath='',
  [int]$BunchParticleIdMin=0,
  [int]$BunchParticleIdMax=0,
  [switch]$RetainGuiWorkbench,
  [string]$TrajectoryProfileId='',
  [double]$TrajectoryStepScale=1.0,
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
function Format-InvariantNumber {
  param([Parameter(Mandatory)][double]$Value)
  [string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$Value)
}
function Invoke-ProjectPython {
  param([string[]]$Arguments)
  Push-Location -LiteralPath $repoRoot;$saved=$env:PYTHONPATH
  try{$env:PYTHONPATH=$repoRoot;& $python @Arguments;if($LASTEXITCODE-ne 0){throw "Python stage failed: $($Arguments -join ' ')"}}
  finally{$env:PYTHONPATH=$saved;Pop-Location}
}
function Invoke-SimionStage {
  param([string]$Stage,[string[]]$Arguments,[Parameter(Mandatory)]$ResourceLease)
  $start=[Diagnostics.ProcessStartInfo]::new()
  $start.FileName=$simion
  $start.WorkingDirectory=$solverDir
  $start.UseShellExecute=$false
  $start.CreateNoWindow=$true
  $start.RedirectStandardOutput=$true
  $start.RedirectStandardError=$true
  $start.StandardOutputEncoding=[Text.UTF8Encoding]::new($false)
  $start.StandardErrorEncoding=[Text.UTF8Encoding]::new($false)
  foreach($argument in $Arguments){$start.ArgumentList.Add($argument)}
  $process=[Diagnostics.Process]::Start($start)
  try{
    $standardOutput=$process.StandardOutput.ReadToEndAsync()
    $standardError=$process.StandardError.ReadToEndAsync()
    if(-not$process.HasExited){
      try{Register-HostResourceProcess -Lease $ResourceLease -ProcessId $process.Id}
      catch{
        if(-not$process.HasExited-or-not$_.Exception.Message.Contains('registered process must be a live descendant')){throw}
        Write-Host "HOST_RESOURCE_PROCESS=COMPLETED_BEFORE_REGISTRATION STAGE=$Stage PID=$($process.Id)"
      }
    }else{
      Write-Host "HOST_RESOURCE_PROCESS=COMPLETED_BEFORE_REGISTRATION STAGE=$Stage PID=$($process.Id)"
    }
    $process.WaitForExit()
    $text=$standardOutput.GetAwaiter().GetResult()+$standardError.GetAwaiter().GetResult()
    [IO.File]::WriteAllText((Join-Path $logDir "$Stage.log"),$text,[Text.UTF8Encoding]::new($false))
    if($text){Write-Host $text.TrimEnd()}
    if($process.ExitCode-ne 0){throw "SIMION stage failed: $Stage"}
  }finally{$process.Dispose()}
}
function Remove-TemporarySolverDirectory {
  param([string]$Path)
  if([string]::IsNullOrWhiteSpace($Path)-or-not(Test-Path -LiteralPath $Path)){return}
  $resolved=[IO.Path]::GetFullPath($Path)
  $temporaryRoot=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([IO.Path]::DirectorySeparatorChar)+[IO.Path]::DirectorySeparatorChar
  if(-not$resolved.StartsWith($temporaryRoot,[StringComparison]::OrdinalIgnoreCase)){throw "Refusing to remove non-temporary solver directory: $resolved"}
  for($attempt=1;$attempt-le8;$attempt++){
    try{
      Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction Stop
      return
    }catch{
      if($attempt-eq8){throw}
      # SIMION may release its final mapped PA handle shortly after the child
      # process exits.  Retry only this verified temporary directory; never
      # widen the deletion target or hide a persistent cleanup failure.
      [GC]::Collect()
      [GC]::WaitForPendingFinalizers()
      Start-Sleep -Milliseconds (250*$attempt)
    }
  }
}
function Assert-FrozenWorkbenchOutput {
  param(
    [Parameter(Mandatory)][string]$Path,
    [Parameter(Mandatory)][string]$WorkbenchRoot,
    [Parameter(Mandatory)]$Manifest,
    [Parameter(Mandatory)][string]$Label
  )
  $resolved=(Resolve-Path -LiteralPath $Path).Path
  $rootPrefix=[IO.Path]::GetFullPath($WorkbenchRoot).TrimEnd([IO.Path]::DirectorySeparatorChar)+[IO.Path]::DirectorySeparatorChar
  if(-not$resolved.StartsWith($rootPrefix,[StringComparison]::OrdinalIgnoreCase)){
    throw "$Label escapes the frozen local workbench: $resolved"
  }
  $records=@($Manifest.outputs|Where-Object{[string]::Equals([IO.Path]::GetFullPath([string]$_.path),$resolved,[StringComparison]::OrdinalIgnoreCase)})
  if($records.Count-ne 1){throw "$Label is not uniquely bound by the verified local-workbench manifest: $resolved"}
}
function Assert-FrozenStandaloneWorkbenchOutput {
  param(
    [Parameter(Mandatory)][string]$Path,
    [Parameter(Mandatory)][string]$WorkbenchRoot,
    [Parameter(Mandatory)]$Manifest,
    [Parameter(Mandatory)][string]$Label
  )
  if([IO.Path]::GetFileName($Path)-notmatch '\.pa$'){
    throw "$Label must be a true standalone .pa, not a PA-family member: $Path"
  }
  Assert-FrozenWorkbenchOutput -Path $Path -WorkbenchRoot $WorkbenchRoot -Manifest $Manifest -Label $Label
}
$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$simion=if($SimionExe){[IO.Path]::GetFullPath($SimionExe)}else{Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
if(-not(Test-Path -LiteralPath $python -PathType Leaf)){throw "Python executable is missing: $python"}
if(-not(Test-Path -LiteralPath $simion -PathType Leaf)){throw "SIMION executable is missing: $simion"}
foreach($value in @($Prism1VoltageV,$Prism2VoltageV)){if([double]::IsNaN($value)-or[double]::IsInfinity($value)){throw 'Prism voltages must be finite'}}
if([double]::IsNaN($TrajectoryStepScale)-or[double]::IsInfinity($TrajectoryStepScale)-or$TrajectoryStepScale-le0-or$TrajectoryStepScale-gt1){throw 'TrajectoryStepScale must be in (0,1].'}
if($PulseAcceleratorUntilInitialExit-and-not[string]::IsNullOrWhiteSpace($AcceleratorPulseSchedulePath)){throw 'PulseAcceleratorUntilInitialExit and AcceleratorPulseSchedulePath are mutually exclusive.'}
$acceleratorPulseRequested=[bool]$PulseAcceleratorUntilInitialExit-or-not[string]::IsNullOrWhiteSpace($AcceleratorPulseSchedulePath)
if (($null -eq $Stripe1VoltageV) -ne ($null -eq $Stripe2VoltageV)) { throw 'Stripe1VoltageV and Stripe2VoltageV must be supplied together.' }
foreach($value in @($Stripe1VoltageV,$Stripe2VoltageV)){if($null-ne$value-and([double]::IsNaN($value)-or[double]::IsInfinity($value))){throw 'Stripe voltages must be finite'}}
if($PulseAcceleratorUntilInitialExit-and[string]::IsNullOrWhiteSpace($LocalWorkbenchRunPath)-and-not$BootstrapGlobalOperatingPa){throw 'Initial-exit-triggered accelerator pulsing without a local workbench requires explicit BootstrapGlobalOperatingPa authorization.'}
if(-not[string]::IsNullOrWhiteSpace($AcceleratorFamilyRunPath)){
  throw 'AcceleratorFamilyRunPath is obsolete. Pulsed flights use one manifest-bound standalone operating PA and the in-program field gate.'
}
$geometryRun=(Resolve-Path -LiteralPath $GeometryReviewRunPath).Path
$mirrorRun=(Resolve-Path -LiteralPath $MirrorRunPath).Path
$stripeRun=(Resolve-Path -LiteralPath $StripeRunPath).Path
$acceleratorRun=(Resolve-Path -LiteralPath $AcceleratorRunPath).Path
$acceleratorPulseSchedule=if([string]::IsNullOrWhiteSpace($AcceleratorPulseSchedulePath)){$null}else{(Resolve-Path -LiteralPath $AcceleratorPulseSchedulePath).Path}
$bunchSourceReceipt=if([string]::IsNullOrWhiteSpace($BunchSourceReceiptPath)){$null}else{(Resolve-Path -LiteralPath $BunchSourceReceiptPath).Path}
$bunchSourceContract=$null;$bunchSourceManifest=$null
$bunchSelectionRequested=$BunchParticleIdMin-ne0-or$BunchParticleIdMax-ne0
if(($BunchParticleIdMin-eq0)-ne($BunchParticleIdMax-eq0)){throw 'BunchParticleIdMin and BunchParticleIdMax must be supplied together.'}
if($bunchSelectionRequested-and$null-eq$bunchSourceReceipt){throw 'A bunch particle interval requires BunchSourceReceiptPath.'}
if($null-ne$bunchSourceReceipt){
  $bunchSourceContract=Get-Content -Raw -LiteralPath $bunchSourceReceipt|ConvertFrom-Json -Depth 30
  if($bunchSourceContract.role-ne'mrtof_deterministic_ideal_bunch_source'-or$bunchSourceContract.status-ne'materialized'){
    throw 'BunchSourceReceiptPath is not a materialized MR-TOF deterministic bunch receipt.'
  }
  if([int]$bunchSourceContract.particle_count-le 1){throw 'BunchSourceReceiptPath must declare N>1.'}
  if($bunchSelectionRequested){
    if($BunchParticleIdMin-lt1-or$BunchParticleIdMax-lt$BunchParticleIdMin-or$BunchParticleIdMax-gt[int]$bunchSourceContract.particle_count){
      throw 'The bunch diagnostic interval must contain one or more contiguous IDs inside the frozen source cohort.'
    }
    if($acceleratorPulseRequested){throw 'A frozen bunch interval diagnostic requires the static accelerator mode.'}
  }
  if([math]::Abs([double]$bunchSourceContract.common_time_of_birth_us)-gt1e-15){throw 'N>1 managed batch dispatch requires common tob=0.'}
  if($RetainGuiWorkbench){throw 'N>1 managed batch flights do not publish one misleading GUI workbench.'}
  $bunchSourceRun=Split-Path -Parent (Split-Path -Parent $bunchSourceReceipt)
  $bunchSourceManifest=Join-Path $bunchSourceRun 'run_manifest.json'
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $bunchSourceManifest --require-status success --require-project $projectId
  if($LASTEXITCODE-ne0){throw 'Bunch source run manifest is not verified success.'}
  $bunchManifestDocument=Get-Content -Raw -LiteralPath $bunchSourceManifest|ConvertFrom-Json -Depth 40
  foreach($binding in @(
    @($bunchSourceReceipt,$null),
    @([string]$bunchSourceContract.state_table.path,[string]$bunchSourceContract.state_table.sha256),
    @([string]$bunchSourceContract.fly2.path,[string]$bunchSourceContract.fly2.sha256)
  )){
    $resolvedBinding=(Resolve-Path -LiteralPath ([string]$binding[0])).Path
    $matches=@($bunchManifestDocument.outputs|Where-Object{[string]::Equals([IO.Path]::GetFullPath([string]$_.path),$resolvedBinding,[StringComparison]::OrdinalIgnoreCase)})
    if($matches.Count-ne1){throw "Bunch receipt/state/Fly2 is not uniquely bound by its source manifest: $resolvedBinding"}
    if($null-ne$binding[1]-and-not[string]::Equals([string]$matches[0].sha256,[string]$binding[1],[StringComparison]::OrdinalIgnoreCase)){
      throw "Bunch source manifest hash differs from the receipt: $resolvedBinding"
    }
  }
  if($PulseAcceleratorUntilInitialExit){throw 'N>1 forbids initial_exit_triggered_single_center.'}
  if($null-ne$acceleratorPulseSchedule){
    $scheduleContract=Get-Content -Raw -LiteralPath $acceleratorPulseSchedule|ConvertFrom-Json -Depth 30
    if([int]$scheduleContract.schema_version-ne 2-or$scheduleContract.mode-ne'fixed_global_time'){
      throw 'N>1 requires either a static accelerator pilot or a schema-2 fixed_global_time schedule.'
    }
  }
}
$localWorkbenchRun=if([string]::IsNullOrWhiteSpace($LocalWorkbenchRunPath)){$null}else{(Resolve-Path -LiteralPath $LocalWorkbenchRunPath).Path}
$geometrySimion=Join-Path $geometryRun 'simion'
$acceleratorSimion=Join-Path $acceleratorRun 'simion'
$geometryManifest=Join-Path $geometryRun 'run_manifest.json'
$mirrorManifest=Join-Path $mirrorRun 'run_manifest.json'
$stripeManifest=Join-Path $stripeRun 'run_manifest.json'
$acceleratorManifest=Join-Path $acceleratorRun 'run_manifest.json'
$localWorkbenchManifest=if($null-eq$localWorkbenchRun){$null}else{Join-Path $localWorkbenchRun 'run_manifest.json'}
$geometryReviewedContract=Join-Path $geometrySimion 'simion_prototype_contract.json'
$geometryConsumerProjectionId='mrtof_two_prism_geometry_contract_v1'
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $geometryManifest `
  --require-status success --require-project $projectId --require-mode three_component_candidate_iob_assembly `
  --consumer-projection-id $geometryConsumerProjectionId `
  --consumed-input resolved_prototype_contract $geometryReviewedContract
if($LASTEXITCODE-ne 0){throw "Consumed geometry-contract projection is not verified success: $geometryManifest"}
foreach($manifest in @($mirrorManifest,$stripeManifest,$acceleratorManifest,$localWorkbenchManifest)){
  if($null-eq$manifest){continue}
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $manifest --require-status success
  if($LASTEXITCODE-ne 0){throw "Upstream run manifest is not verified success: $manifest"}
}
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__sim__simion__two-prism-trial-n1'}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
. (Join-Path $repoRoot 'common\multipole\resource_budget_support.ps1')
. (Join-Path $repoRoot 'common\simion\short_pa_path_support.ps1')
. (Join-Path $PSScriptRoot 'analyzer_local_family_support.ps1')
$retentionClass=if($RetainGuiWorkbench){'solver_review'}else{'compact'}
$retentionReason=if($RetainGuiWorkbench){'User-requested SIMION GUI review package retaining the exact flown IOB and its one manifest-bound standalone operating PA set.'}else{''}
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'finite_3d_two_prism_voltage_trial' -Software @('SIMION 2020','Python 3.11') `
  -RetentionContractEnabled -RetentionClass $retentionClass -RetentionReason $retentionReason `
  -AdditionalDirectories @('simion') -UseShortExecutionPath
$runDir=$package.run_dir;$resultDir=$package.result_dir;$logDir=$package.log_dir;$solverDir=Join-Path $runDir 'simion'
$artifactSolverDir=Join-Path ([string]$package.artifact_run_dir) 'simion'
$runConfig=$package.run_config;$summary=$package.summary;$artifactRoot=Join-Path $workspaceRoot 'artifacts'
$terminalized=$false;$failureStage='preflight';$resourceLease=$null;$hostOutcome='failed';$temporarySolverDir=$null;$basisLinkDir=$null;$iobInputCopyDir=$null
$operatingCacheKey=$null;$operatingCacheGeneration=$null;$operatingCacheIdentityPath=$null
$guiWorkbenchIob=$null;$guiWorkbenchReceipt=$null
$guiWorkbenchOutputs=@()
$batchBundleReceiptPath=$null
$batchRuntimeRoot=$null;$batchPaCopyDirectories=@();$batchMergeReceipt=$null
$dispatchRequestPath=$null;$resourceProfilesPath=$null;$runtimeDispatchPlanPath=$null
$batchPlanPath=$null;$batchResourceUsagePath=$null;$resourceProfilePath=$null
$batchCapacityReceipts=@();$batchWaveResult=$null
$earlyOperatingCacheProbe=$null;$earlyOperatingCacheHit=$false;$earlyChangedIndexCount=0
try{
  $sourceAnalyzer=Join-Path $geometrySimion 'mrtof_analyzer.pa0'
  $acceleratorConfig=Get-Content -Raw -LiteralPath (Join-Path $acceleratorRun 'run_config.json')|ConvertFrom-Json -Depth 40
  $declaredStandaloneAccelerator=if($null-ne$acceleratorConfig.inputs.PSObject.Properties['standalone_accelerator_pa']){[string]$acceleratorConfig.inputs.standalone_accelerator_pa}else{''}
  $sourceAccelerator=if(-not[string]::IsNullOrWhiteSpace($declaredStandaloneAccelerator)){$declaredStandaloneAccelerator}else{Join-Path $acceleratorSimion 'mrtof_accelerator.pa0'}
  $sourceDetector=Join-Path $geometrySimion 'mrtof_detector.pa#'
  $localWorkbenchConfig=$null;$localFamilies=@();$localBaseMaterialization=$null;$temporaryLocalPaths=@();$localWorkbenchOperatingPaths=@()
  $localCacheSentinelPaths=@();$localCacheSentinelHashes=@()
  if($null-ne$localWorkbenchRun){
    $localWorkbenchConfig=Get-Content -Raw -LiteralPath (Join-Path $localWorkbenchRun 'run_config.json')|ConvertFrom-Json -Depth 40
    $localWorkbenchManifestRecord=Get-Content -Raw -LiteralPath $localWorkbenchManifest|ConvertFrom-Json -Depth 40
    if($localWorkbenchConfig.mode-ne'analyzer_local_replacement_workbench'){throw 'LocalWorkbenchRunPath is not a local replacement workbench.'}
    $sourceAnalyzer=[string]$localWorkbenchConfig.inputs.global_analyzer_pa
    if([string]::IsNullOrWhiteSpace($sourceAnalyzer)){throw 'Local workbench must publish inputs.global_analyzer_pa as a detached standalone PA.'}
    $sourceAccelerator=[string]$localWorkbenchConfig.inputs.accelerator_pa
    $sourceDetector=[string]$localWorkbenchConfig.inputs.detector_pa
    if([string]::IsNullOrWhiteSpace($sourceAccelerator)-or[string]::IsNullOrWhiteSpace($sourceDetector)){
      throw 'Local workbench must publish standalone accelerator_pa and detector_pa inputs.'
    }
    $workbenchOperatingManifest=[string]$localWorkbenchConfig.inputs.operating_run_manifest
    if([string]::IsNullOrWhiteSpace($workbenchOperatingManifest)-or-not(Test-Path -LiteralPath $workbenchOperatingManifest -PathType Leaf)){
      throw 'Local workbench lacks its verified operating-run provenance.'
    }
    & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $workbenchOperatingManifest --require-status success --require-project $projectId
    if($LASTEXITCODE-ne 0){throw 'Local-workbench operating-run manifest verification failed.'}
    $workbenchOperatingConfig=Get-Content -Raw -LiteralPath (Join-Path (Split-Path -Parent $workbenchOperatingManifest) 'run_config.json')|ConvertFrom-Json -Depth 40
    $expectedUpstreamManifests=[ordered]@{
      geometry_run_manifest=$geometryManifest
      mirror_run_manifest=$mirrorManifest
      stripe_run_manifest=$stripeManifest
      accelerator_run_manifest=$acceleratorManifest
    }
    foreach($entry in $expectedUpstreamManifests.GetEnumerator()){
      $declared=[string]$workbenchOperatingConfig.inputs.($entry.Key)
      if([string]::IsNullOrWhiteSpace($declared) -or
          -not (Test-Path -LiteralPath $declared -PathType Leaf) -or
          -not (Test-RunFilesIdentical -Left $declared -Right ([string]$entry.Value))){
        throw "Local-workbench operating provenance differs for $($entry.Key)."
      }
    }
    $localWorkbenchOperatingPaths=@($localWorkbenchConfig.inputs.local_operating_pas|ForEach-Object{[string]$_})
    if($localWorkbenchOperatingPaths.Count-ne 5){throw 'Local workbench must publish exactly five inputs.local_operating_pas.'}
    $declaredWorkbenchPaths=@($sourceAnalyzer)+$localWorkbenchOperatingPaths+@($sourceAccelerator,$sourceDetector)
    for($index=0;$index-lt$declaredWorkbenchPaths.Count;$index++){
      Assert-FrozenStandaloneWorkbenchOutput -Path $declaredWorkbenchPaths[$index] -WorkbenchRoot $localWorkbenchRun -Manifest $localWorkbenchManifestRecord -Label ("local workbench PA {0}"-f$index)
    }
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
  if($null-eq$localWorkbenchRun-and-not$BootstrapGlobalOperatingPa){
    throw 'Current two-prism trials require a verified standalone local workbench or explicit BootstrapGlobalOperatingPa authorization.'
  }
  $reuseFrozenWorkbenchAnalyzer=$null-ne$localWorkbenchRun
  $workbenchAnalyzer=$sourceAnalyzer
  $reviewedContract=$geometryReviewedContract
  $selectedContract=Join-Path $acceleratorSimion 'accelerator_focus_voltage_trial.json'
  $trajectoryContractSource=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\config\simion_candidate_two_zone.json'
  $mirrorSummary=Join-Path $mirrorRun 'summary.json'
  $stripeSummary=Join-Path $stripeRun 'summary.json'
  $acceleratorReceipt=Join-Path $acceleratorRun 'results\accelerator_focus_voltage_trial_receipt.json'
  $trialTool=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_simion_trial.py'
  $batchTool=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\mrtof_batch_flight.py'
  $voltageizerSource=Join-Path $PSScriptRoot 'voltageize_analyzer_pa0.lua'
  $iobBuilderSource=Join-Path $PSScriptRoot 'build_three_component_iob.lua'
  $localIobBuilderSource=Join-Path $PSScriptRoot 'build_local_refinement_iob.lua'
  $localIobInspectorSource=Join-Path $PSScriptRoot 'inspect_local_refinement_iob.lua'
  $standaloneComposerSource=Join-Path $repoRoot 'common\simion\compose_standalone_pa.lua'
  $iobSeedSource=Join-Path $repoRoot 'common\simion\assets\iob_instance_seeds\3_instance_seed.iob'
  $localIobSeedSource=Join-Path $repoRoot 'common\simion\assets\iob_instance_seeds\8_instance_seed.iob'
  $placeholderSources=@(1..8|ForEach-Object{Join-Path $repoRoot ('common\simion\assets\iob_instance_seeds\iob_seed_placeholder_{0:D2}.pa0'-f$_)})
  $programSource=Join-Path $PSScriptRoot 'mrtof_candidate.lua'
  $counterSource=Join-Path $PSScriptRoot 'mirror_cycle_counter.lua'
  $mapSource=Join-Path $PSScriptRoot 'candidate_voltage_map.lua'
  $launcherSource=Join-Path $PSScriptRoot 'run_iob_flight.lua'
  foreach($path in @($sourceAnalyzer,$sourceAccelerator,$sourceDetector,$reviewedContract,$selectedContract,$trajectoryContractSource,$mirrorSummary,$stripeSummary,$acceleratorReceipt,$trialTool,$batchTool,$voltageizerSource,$iobBuilderSource,$localIobBuilderSource,$localIobInspectorSource,$standaloneComposerSource,$iobSeedSource,$localIobSeedSource,$placeholderSources,$programSource,$counterSource,$mapSource,$launcherSource)){
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Required P1/P2 trial input is missing: $path"}
  }
  $failureStage='capacity_preflight'
  [int64]$requiredBytes=0;[int64]$transientBytes=0
  foreach($path in @($reviewedContract,$selectedContract,$trajectoryContractSource,$mirrorSummary,$stripeSummary,$acceleratorReceipt,$trialTool,$batchTool,$voltageizerSource,$iobBuilderSource,$localIobBuilderSource,$localIobInspectorSource,$standaloneComposerSource,$iobSeedSource,$localIobSeedSource,$placeholderSources,$programSource,$counterSource,$mapSource,$launcherSource)){$requiredBytes+=[int64](Get-Item -LiteralPath $path).Length}
  if($null-ne$bunchSourceReceipt){$requiredBytes+=[int64](Get-Item -LiteralPath $bunchSourceReceipt).Length}
  # RequiredHeadroomBytes governs retained artifact growth. Temporary solver
  # PAs instead raise the physical-free-space floor and are deleted before a
  # compact run is terminalized. This matches the repository integration
  # runner's separation of artifact quota from transient staging capacity.
  if(-not$reuseFrozenWorkbenchAnalyzer){
    $analyzerOperatingBytes=[int64](Get-Item -LiteralPath $sourceAnalyzer).Length
    if($RetainGuiWorkbench){$requiredBytes+=$analyzerOperatingBytes}else{$transientBytes+=$analyzerOperatingBytes}
  }
  if($null-ne$localWorkbenchRun){
    [int64]$localOperatingBytes=0;[int64]$largestLocalOperatingBytes=0
    for($familyIndex=0;$familyIndex-lt$localFamilies.Count;$familyIndex++){
      $baseOperatingBytes=[int64](Get-Item -LiteralPath $localWorkbenchOperatingPaths[$familyIndex]).Length
      $localOperatingBytes+=$baseOperatingBytes
      $largestLocalOperatingBytes=[math]::Max($largestLocalOperatingBytes,$baseOperatingBytes)
    }
    if($earlyChangedIndexCount-eq 0){
      # The baseline local PAs are only projected into the IOB set below.
    }elseif($earlyOperatingCacheHit){
      if($RetainGuiWorkbench){$requiredBytes+=$localOperatingBytes}else{$transientBytes+=$localOperatingBytes}
    }else{
      # Each perturbation retains five temporary outputs. Per region, SIMION
      # combines one detached standalone baseline with only the response for
      # each changed voltage. Runtime never opens a native `.paN` member.
      [int64]$perRegionProjectionBytes=(1+$earlyChangedIndexCount)*$largestLocalOperatingBytes
      if($RetainGuiWorkbench){
        $requiredBytes+=$localOperatingBytes
        $transientBytes+=$perRegionProjectionBytes
      }else{
        $transientBytes+=$localOperatingBytes+$perRegionProjectionBytes
      }
    }
  }
  # Every PA bound into a newly-built IOB is first projected to a private
  # standalone input. Account for those copies only after all local PA sizes
  # are known; required/transient budgets were initialized immediately above.
  [int64]$iobProjectionBytes=[int64](Get-Item -LiteralPath $sourceAnalyzer).Length+
    [int64](Get-Item -LiteralPath $sourceDetector).Length
  if(-not$acceleratorPulseRequested){$iobProjectionBytes+=[int64](Get-Item -LiteralPath $sourceAccelerator).Length}
  if($null-ne$localWorkbenchRun-and($earlyChangedIndexCount-eq0-or-not$RetainGuiWorkbench)){$iobProjectionBytes+=$localOperatingBytes}
  if($RetainGuiWorkbench){$requiredBytes+=$iobProjectionBytes}else{$transientBytes+=$iobProjectionBytes}
  $protectedPaths=@($package.artifact_run_dir)
  if($null-ne$localWorkbenchRun){$protectedPaths+=@($localWorkbenchRun);if(-not$earlyOperatingCacheHit){$protectedPaths+=@($localFamilies.generation_directory)}}
  $startupProtectedCacheKeys=if($null-eq$localWorkbenchRun){@()}else{@($localFamilies.cache_key)}
  if($earlyOperatingCacheHit){$startupProtectedCacheKeys+=@($operatingCacheKey)}
  $startupProtectedCacheKeys=@($startupProtectedCacheKeys|Select-Object -Unique)
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
  $bunchSourceLocal=if($null-eq$bunchSourceReceipt){$null}else{Copy-RequiredInput $bunchSourceReceipt (Join-Path $solverDir 'bunch_source_receipt.json') 'bunch source receipt'}
  foreach($pair in @(
    @($programSource,'mrtof_three_component_candidate.lua'),@($counterSource,'mrtof_three_component_candidate.mirror_cycle_counter.lua'),
    @($mapSource,'mrtof_three_component_candidate.voltage_map.lua'),@($launcherSource,'run_iob_flight.lua'),
    @($iobBuilderSource,'build_three_component_iob.lua'),@($localIobBuilderSource,'build_local_refinement_iob.lua'),
    @($localIobInspectorSource,'inspect_local_refinement_iob.lua'),
    @($standaloneComposerSource,'compose_standalone_pa.lua'),
    @($iobSeedSource,'3_instance_seed.iob'),@($localIobSeedSource,'8_instance_seed.iob'),
    @($placeholderSources[0],'iob_seed_placeholder_01.pa0'),@($placeholderSources[1],'iob_seed_placeholder_02.pa0'),
    @($placeholderSources[2],'iob_seed_placeholder_03.pa0'),@($placeholderSources[3],'iob_seed_placeholder_04.pa0'),
    @($placeholderSources[4],'iob_seed_placeholder_05.pa0'),@($placeholderSources[5],'iob_seed_placeholder_06.pa0'),
    @($placeholderSources[6],'iob_seed_placeholder_07.pa0'),@($placeholderSources[7],'iob_seed_placeholder_08.pa0'),
    @($voltageizerSource,'voltageize_analyzer_pa0.lua'),
    @($trialTool,'two_prism_simion_trial.py'),@($batchTool,'mrtof_batch_flight.py'))){
    Copy-RequiredInput $pair[0] (Join-Path $solverDir $pair[1]) $pair[1]|Out-Null
  }
  $fly2Input=Join-Path $solverDir 'downstream_trial_source.input.fly2'
  $sidecar=Join-Path $solverDir 'mrtof_three_component_candidate.operating_point.lua'
  $trialReceipt=Join-Path $resultDir 'two_prism_trial_materialization.json'
  $failureStage='materialize_trial'
  $workbenchAcceleratorInstance=if($reuseFrozenWorkbenchAnalyzer){'7'}else{'2'}
  $materializeArguments=@('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial','materialize',
    '--contract',$contract,'--trajectory-contract',$trajectoryContract,'--reviewed-contract',$reviewed,'--mirror-summary',$mirrorLocal,'--stripe-summary',$stripeLocal,
    '--accelerator-receipt',$acceleratorLocal,'--prism-1-v',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$Prism1VoltageV)),
    '--prism-2-v',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$Prism2VoltageV)),
    '--workbench-accelerator-instance',$workbenchAcceleratorInstance,
    '--fly2',$fly2Input,'--sidecar',$sidecar,'--receipt',$trialReceipt)
  if($null-ne$Stripe1VoltageV){
    $materializeArguments+=@('--stripe-1-v',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$Stripe1VoltageV)),
      '--stripe-2-v',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$Stripe2VoltageV)))
  }
  if($null-ne$bunchSourceLocal){$materializeArguments+=@('--bunch-source-receipt',$bunchSourceLocal)}
  if($bunchSelectionRequested){$materializeArguments+=@('--bunch-particle-id-min',([string]$BunchParticleIdMin),'--bunch-particle-id-max',([string]$BunchParticleIdMax))}
  if($TrajectoryStepScale-ne1){$materializeArguments+=@('--trajectory-step-scale',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$TrajectoryStepScale)))}
  if($PulseAcceleratorUntilInitialExit){$materializeArguments+='--pulse-accelerator-until-initial-exit'}
  if($null-ne$acceleratorPulseSchedule){$materializeArguments+=@('--accelerator-pulse-schedule',$acceleratorPulseSchedule)}
  if(-not[string]::IsNullOrWhiteSpace($TrajectoryProfileId)){$materializeArguments+=@('--trajectory-profile-id',$TrajectoryProfileId)}
  Invoke-ProjectPython -Arguments $materializeArguments
  $trial=Get-Content -LiteralPath $trialReceipt -Raw -Encoding UTF8|ConvertFrom-Json
  $isBunchFlight=$null-ne$bunchSourceContract
  if($null-ne$bunchSourceContract){
    $expectedTrialCount=if($bunchSelectionRequested){$BunchParticleIdMax-$BunchParticleIdMin+1}else{[int]$bunchSourceContract.particle_count}
    $expectedTrialIds=if($bunchSelectionRequested){@($BunchParticleIdMin..$BunchParticleIdMax)}else{@($bunchSourceContract.expected_particle_ids)}
    if([int]$trial.source_particle_count-ne$expectedTrialCount){throw 'Materialized trial particle count differs from the requested frozen bunch interval.'}
    if(@(Compare-Object @($trial.source_expected_particle_ids) $expectedTrialIds).Count-ne0){throw 'Materialized trial particle IDs differ from the requested frozen bunch interval.'}
    if($bunchSelectionRequested-and($null-eq$trial.source_selection-or[int]$trial.source_selection.particle_id_min-ne$BunchParticleIdMin-or[int]$trial.source_selection.particle_id_max-ne$BunchParticleIdMax)){
      throw 'Materialized trial source-selection receipt differs from the requested frozen bunch interval.'
    }
    if($bunchSelectionRequested-and-not[string]::Equals([string]$trial.fly2_sha256,[string]$trial.source_selection.fly2_sha256,[StringComparison]::OrdinalIgnoreCase)){
      throw 'Materialized trial Fly2 identity differs from its frozen source-selection receipt.'
    }
    if(-not$bunchSelectionRequested-and-not[string]::Equals([string]$trial.fly2_sha256,[string]$bunchSourceContract.fly2.sha256,[StringComparison]::OrdinalIgnoreCase)){
      throw 'Materialized trial Fly2 identity differs from the complete frozen bunch receipt.'
    }
  }
  $temporarySolverDir=if($RetainGuiWorkbench){Join-Path $artifactSolverDir 'gui_workbench'}else{Join-Path ([IO.Path]::GetTempPath()) ('mrtof_downstream_'+[guid]::NewGuid().ToString('N'))}
  New-Item -ItemType Directory -Path $temporarySolverDir|Out-Null
  $temporaryAnalyzer=if($reuseFrozenWorkbenchAnalyzer){$workbenchAnalyzer}else{Join-Path $temporarySolverDir 'analyzer_operating.pa0'}
  $temporaryIob=Join-Path $temporarySolverDir 'mrtof_three_component_candidate.iob'
  $posePath=Join-Path $resultDir 'resolved_iob_pose.json'
  $poseCode="import json,sys; from pathlib import Path; from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import load_contract; from projects.parallel_mirror_dual_stripe_mr_tof.analysis.split_candidate_geometry import resolve_split_iob_origins; p=Path(sys.argv[1]); active=load_contract(Path(sys.argv[2])); c=json.loads(p.read_text(encoding='utf-8')); policy=active['accelerator']['detector_return_path']; Path(sys.argv[3]).write_text(json.dumps({'origins_mm':resolve_split_iob_origins(p,inherited_detector_return_path=policy,inherited_dual_stripe_topology_contract=active),'mesh_mm_per_gu':c['simion']['component_mesh_mm_per_gu'],'detector_return_policy_authority':'current_trajectory_contract'},indent=2)+'\n',encoding='utf-8')"
  Invoke-ProjectPython -Arguments @('-c',$poseCode,$reviewed,$trajectoryContract,$posePath)
  $pose=Get-Content -LiteralPath $posePath -Raw -Encoding UTF8|ConvertFrom-Json
  $originArguments=@()
  foreach($name in @('analyzer','accelerator','detector')){foreach($value in @($pose.origins_mm.$name)){$originArguments+=[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$value)}}
  $upstreamPaths=@($sourceAnalyzer,$sourceAccelerator,$sourceDetector)
  if($null-ne$acceleratorPulseSchedule){$upstreamPaths+=@($acceleratorPulseSchedule)}
  if($reuseFrozenWorkbenchAnalyzer){$upstreamPaths+=@($workbenchAnalyzer)}
  $upstreamHashes=@($upstreamPaths|ForEach-Object{(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash})
  $voltageSourceHash=if($reuseFrozenWorkbenchAnalyzer){
    (Get-FileHash -LiteralPath $workbenchAnalyzer -Algorithm SHA256).Hash
  }else{
    (Get-FileHash -LiteralPath $sourceAnalyzer -Algorithm SHA256).Hash
  }
  $failureStage='prepare_operating_analyzer'
  $resourceLease=Enter-HostResourceStage -Role SIMION -Stage 'mrtof_prepare' `
    -Budget (Get-HostResourceBudget -Role SIMION -Stage 'mrtof_prepare') -RunId $RunId
  $voltageReceipt=Join-Path $resultDir 'temporary_analyzer_voltageization_receipt.json'
  $localAdjustmentReceipts=@();$localOperatingCacheReceipt=$null
  if(-not$reuseFrozenWorkbenchAnalyzer){
    $failureStage='bootstrap_global_operating_analyzer'
    $sourceFamilyDirectory=Split-Path -Parent $sourceAnalyzer
    $sourceFamilyStem=[IO.Path]::GetFileNameWithoutExtension($sourceAnalyzer)
    $sourceFamilyMembers=@(Get-ChildItem -LiteralPath $sourceFamilyDirectory -File|Where-Object{$_.Name-match("^"+[regex]::Escape($sourceFamilyStem)+"\.pa(?:#|[0-9]+)$")}|Sort-Object Name)
    if($sourceFamilyMembers.Count-lt 2){throw 'Bootstrap analyzer source is not a native PA family.'}
    $sourceFamilyGuards=@()
    try{
      foreach($member in $sourceFamilyMembers){
        $sourceFamilyGuards+=[IO.File]::Open($member.FullName,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
      }
      $voltageArguments=@('--nogui','--noprompt','lua',(Join-Path $solverDir 'voltageize_analyzer_pa0.lua'),$sourceAnalyzer,$temporaryAnalyzer)
      foreach($value in @($trial.analyzer_electrode_voltages_v)){
        $voltageArguments+=[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$value)
      }
      Invoke-SimionStage -Stage 'voltageize_temporary_analyzer' -Arguments $voltageArguments -ResourceLease $resourceLease
    }finally{
      foreach($guard in $sourceFamilyGuards){$guard.Dispose()}
    }
    if(-not(Test-Path -LiteralPath $temporaryAnalyzer -PathType Leaf)){throw 'Bootstrap voltageization did not create a standalone operating analyzer PA.'}
  }
  $temporaryAnalyzerHash=(Get-FileHash -LiteralPath $temporaryAnalyzer -Algorithm SHA256).Hash
  if($null-ne$localWorkbenchRun){
    $failureStage='adjust_local_operating_replacements'
    $baseDownstream=@([double]$localBaseMaterialization.stripe_biases_v[0],[double]$localBaseMaterialization.stripe_biases_v[1],[double]$localBaseMaterialization.prism_voltages_v[0],[double]$localBaseMaterialization.prism_voltages_v[1])
    $targetDownstream=@([double]$trial.stripe_biases_v[0],[double]$trial.stripe_biases_v[1],[double]$trial.prism_voltages_v[0],[double]$trial.prism_voltages_v[1])
    $deltaVoltages=@();$changedIndices=@();for($index=0;$index-lt 4;$index++){$delta=[double]$targetDownstream[$index]-[double]$baseDownstream[$index];$deltaVoltages+=$delta;if([math]::Abs($delta)-gt 1e-15){$changedIndices+=$index}}
    $localNames=@('local_negative_mirror.pa','local_negative_bridge.pa','local_central.pa','local_positive_bridge.pa','local_positive_mirror.pa')
    $projectedLocalNames=@(1..5|ForEach-Object{"iob_input_local_$_.pa"})
    $temporaryLocalPaths=@()
    if($changedIndices.Count-eq 0){
      $temporaryLocalPaths=@($localWorkbenchOperatingPaths)
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
        for($index=0;$index-lt$localNames.Count;$index++){
          $materialized=Join-Path $temporarySolverDir $localNames[$index]
          if($RetainGuiWorkbench){
            $projected=Join-Path $temporarySolverDir $projectedLocalNames[$index]
            Move-Item -LiteralPath $materialized -Destination $projected
            $temporaryLocalPaths+=$projected
          }else{$temporaryLocalPaths+=$materialized}
        }
        $localOperatingCacheReceipt=[ordered]@{disposition='hit';cache_key=$operatingCacheKey;generation_directory=$operatingCacheGeneration;outputs=@($localNames);refine_performed=$false}
      }elseif($cacheProbe.disposition-eq'miss'){
        $requiredResponseIds=@($changedIndices|ForEach-Object{5+[int]$_})
        foreach($family in $localFamilies){
          $subset=Resolve-AnalyzerLocalStandaloneResponseSubset -Family $family -ResponseIds $requiredResponseIds -CacheRoot $operatingCacheRoot
          $localCacheSentinelPaths+=@($subset.responses|ForEach-Object{[string]$_.path})
        }
        $localCacheSentinelHashes=@($localCacheSentinelPaths|ForEach-Object{(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash})
        $basisVoltage=[double]$localWorkbenchConfig.parameters.basis_voltage_v
        if([double]::IsNaN($basisVoltage)-or[double]::IsInfinity($basisVoltage)-or$basisVoltage-eq 0){throw 'Local workbench basis voltage must be finite and nonzero.'}
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
          $privateOperatingBase=New-ShortPaCopy -Source $localWorkbenchOperatingPaths[$index] -Destination (Join-Path $basisLinkDir 'base.pa')
          $temporaryLocal=Join-Path $temporarySolverDir $(if($RetainGuiWorkbench){$projectedLocalNames[$index]}else{$localNames[$index]})
          $compositionArguments=@('--nogui','--noprompt','lua',(Join-Path $solverDir 'compose_standalone_pa.lua'),$privateOperatingBase,$temporaryLocal)
          for($responseOffset=0;$responseOffset-lt$changedIndices.Count;$responseOffset++){
            $changedIndex=[int]$changedIndices[$responseOffset]
            $coefficient=[double]$deltaVoltages[$changedIndex]/$basisVoltage
            $compositionArguments+=("{0},{1}"-f$privateBasisPaths[$responseOffset],[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$coefficient))
          }
          Invoke-SimionStage -Stage ("compose_local_{0}"-f$family.label) -Arguments $compositionArguments -ResourceLease $resourceLease
          $temporaryLocalPaths+=$temporaryLocal
          $localAdjustmentReceipts+=[ordered]@{region=$family.region;source_cache_generation=$family.generation_directory;basis_projection='standalone_linear_response_composition';native_family_member_opened=$false;basis_voltage_v=$basisVoltage;downstream_voltage_deltas_v=@($deltaVoltages);temporary_output_sha256=(Get-FileHash -LiteralPath $temporaryLocal -Algorithm SHA256).Hash;refine_performed=$false}
          Remove-ShortPaCopyDirectory -Path $basisLinkDir
          $basisLinkDir=$null
        }
        $localOperatingCacheReceipt=[ordered]@{disposition='transient_miss_not_published';cache_key=$operatingCacheKey;generation_directory=$null;outputs=@($(if($RetainGuiWorkbench){$projectedLocalNames}else{$localNames}));refine_performed=$false}
      }else{throw "Local operating PA cache is corrupt: $($cacheProbe.detail)"}
    }
  }
  $voltageMethod=if($reuseFrozenWorkbenchAnalyzer){
    'verified_frozen_workbench_global_standalone_plus_local_response_composition'
  }elseif($null-eq$localWorkbenchRun){
    'SIMION_PA_object_fast_adjust_save_as'
  }elseif($null-ne$localOperatingCacheReceipt-and$localOperatingCacheReceipt.disposition-eq'transient_miss_not_published'){
    'global_fast_adjust_plus_transient_local_basis_deltas'
  }elseif($null-ne$localOperatingCacheReceipt){
    'global_fast_adjust_plus_content_addressed_local_operating_pa'
  }elseif($localAdjustmentReceipts.Count-eq 0){
    'global_fast_adjust_plus_reused_local_baseline_pa'
  }else{
    'global_fast_adjust_plus_nonzero_local_basis_deltas'
  }
  Write-RunJson -Path $voltageReceipt -Depth 14 -Value ([ordered]@{
    schema_version=1
    role='mrtof_temporary_analyzer_voltageization'
    status='success'
    method=$voltageMethod
    source_pa=$workbenchAnalyzer
    source_sha256=$voltageSourceHash
    temporary_output_sha256=$temporaryAnalyzerHash
    electrode_voltages_v=@($trial.analyzer_electrode_voltages_v)
    local_operating_cache=$localOperatingCacheReceipt
    local_adjustments=$localAdjustmentReceipts
    source_standalone_read_only=[bool]$reuseFrozenWorkbenchAnalyzer
    bootstrap_global_family_read_only=[bool](-not$reuseFrozenWorkbenchAnalyzer)
    refine_performed=$false
    temporary_output_retained=[bool]$RetainGuiWorkbench
  })
  # Never expose a frozen workbench/cache PA directly to SIMION.  IOB loading
  # can write a PA after the command appears to finish.  Compact runs therefore
  # use verified disposable short-name copies; GUI-review runs retain private
  # run-local copies and never bind the upstream files into their IOB.
  # Extend the integrity snapshot after the local operating PA set has been
  # resolved. This covers both frozen zero-delta workbench inputs and newly
  # materialized/adjusted private standalone PAs through IOB build and flight.
  foreach($path in $temporaryLocalPaths){
    $upstreamPaths+=$path
    $upstreamHashes+=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
  }
  $failureStage='project_iob_pa_inputs'
  $iobProjectionRoot=if($RetainGuiWorkbench){$temporarySolverDir}else{$artifactSolverDir}
  if(-not$RetainGuiWorkbench){
    $iobInputCopyDir=Join-Path ([IO.Path]::GetTempPath()) ('simion_pa_links_'+[guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $iobInputCopyDir|Out-Null
    $iobProjectionRoot=$iobInputCopyDir
  }
  function Copy-IobPaInput {
    param([Parameter(Mandatory)][string]$Source,[Parameter(Mandatory)][string]$Name)
    $destination=Join-Path $iobProjectionRoot $Name
    if([IO.Path]::GetFullPath($Source).Equals([IO.Path]::GetFullPath($destination),[StringComparison]::OrdinalIgnoreCase)){return $destination}
    if($RetainGuiWorkbench){
      return Copy-VerifiedRunInput -Source $Source -Destination $destination -VerificationAttempts 3
    }
    return New-ShortPaCopy -Source $Source -Destination $destination
  }
  if($isBunchFlight){
    $iobAnalyzerInput=$temporaryAnalyzer;$iobAcceleratorInput=$sourceAccelerator;$iobDetectorInput=$sourceDetector
    $iobLocalInputs=@($temporaryLocalPaths)
  }else{
    $iobAnalyzerInput=Copy-IobPaInput -Source $temporaryAnalyzer -Name 'iob_input_analyzer.pa'
    $iobAcceleratorInput=Copy-IobPaInput -Source $sourceAccelerator -Name 'iob_input_accelerator.pa'
    $iobDetectorInput=Copy-IobPaInput -Source $sourceDetector -Name 'iob_input_detector.pa'
    $iobLocalInputs=@()
  }
  if(-not$isBunchFlight-and$temporaryLocalPaths.Count-gt 0){
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
    $declaredWorkbenchIob=[string]$localWorkbenchConfig.inputs.operating_iob
    if([string]::IsNullOrWhiteSpace($declaredWorkbenchIob)){
      throw 'Local workbench must publish inputs.operating_iob so its companion sidecar basename is unambiguous.'
    }
    Assert-FrozenWorkbenchOutput -Path $declaredWorkbenchIob -WorkbenchRoot $localWorkbenchRun -Manifest $localWorkbenchManifestRecord -Label 'local workbench operating IOB'
    $declaredWorkbenchIobBase=Join-Path ([IO.Path]::GetDirectoryName($declaredWorkbenchIob)) ([IO.Path]::GetFileNameWithoutExtension($declaredWorkbenchIob))
    $localConfigSource="$declaredWorkbenchIobBase.local_refinement.lua"
    Assert-FrozenWorkbenchOutput -Path $localConfigSource -WorkbenchRoot $localWorkbenchRun -Manifest $localWorkbenchManifestRecord -Label 'local workbench refinement sidecar'
    $localConfig=Copy-RequiredInput $localConfigSource (Join-Path $solverDir 'local_trial_refinement.lua') 'local replacement sidecar'
    $iobLocalConfig=if($RetainGuiWorkbench){Join-Path $artifactSolverDir 'local_trial_refinement.lua'}else{$localConfig}
    $localOrigins=@();$localOrigins+=,@($pose.origins_mm.analyzer)
    foreach($family in $localFamilies){$localOrigins+=,@($family.contract.patch_origin_project_mm)}
    $localOrigins+=,@($pose.origins_mm.accelerator);$localOrigins+=,@($pose.origins_mm.detector)
    $localOriginArguments=@();foreach($origin in $localOrigins){foreach($value in $origin){$localOriginArguments+=[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$value)}}
    $buildArguments=@('--nogui','--noprompt','lua',(Join-Path $solverDir 'build_local_refinement_iob.lua'),'--',(Join-Path $solverDir '8_instance_seed.iob'),$iobAnalyzerInput)+$iobLocalInputs+@($iobAcceleratorInput,$iobDetectorInput,$temporaryIob,$iobProgramPath,$iobFly2Path,$iobLocalConfig)+$localOriginArguments
  }
  if(-not$isBunchFlight){
    Invoke-SimionStage -Stage 'build_temporary_iob' -Arguments $buildArguments -ResourceLease $resourceLease
    $temporaryFly2=[IO.Path]::ChangeExtension($temporaryIob,'.fly2')
    if(-not(Test-RunFilesIdentical -Left $fly2Input -Right $temporaryFly2)){throw 'IOB companion Fly2 differs from the frozen downstream-trial source'}
    $failureStage='native_two_prism_flight'
    $resourceLease=Update-HostResourceStage -Lease $resourceLease -Stage 'mrtof_flight' `
      -Budget (Get-HostResourceBudget -Role SIMION -Stage 'mrtof_flight') -RetainedMemoryBytes 0
    Invoke-SimionStage -Stage 'native_two_prism_flight' -Arguments @('--nogui','--noprompt','lua',(Join-Path $solverDir 'run_iob_flight.lua'),$temporaryIob) -ResourceLease $resourceLease
  }else{
    $failureStage='plan_bunch_dispatch'
    $dispatchRequestPath=Join-Path $resultDir 'simion_dispatch_request.json'
    $resourceProfilesPath=Join-Path $resultDir 'simion_resource_profiles.json'
    $runtimeDispatchPlanPath=Join-Path $resultDir 'simion_repository_dispatch_plan.json'
    $batchPlanPath=Join-Path $resultDir 'simion_execution_batch_plan.json'
    $batchResourceUsagePath=Join-Path $logDir 'simion_batch_resource_usage.json'
    Invoke-ProjectPython -Arguments @('-m','common.simion.resource_profile','discover','--runs-root',(Join-Path $artifactRoot "projects\$projectId\runs"),'--output',$resourceProfilesPath)
    Write-RunJson -Path $dispatchRequestPath -Depth 10 -Value ([ordered]@{
      solver='SIMION';field_kind='electrostatic';particle_count=[int]$trial.source_particle_count;independent_particles=$true
      frontend_grid_profile_id='mrtof_analyzer_global_plus_five_local_patches'
      oatof_numerical_profile_id=$null
      trajectory_quality_profile_id=[string]$trial.trajectory_profile.profile_id
      time_integration_profile_id='mrtof_candidate_adaptive_time_step'
      frontend_cell_mm_xyz=$(if($null-ne$localWorkbenchConfig){@($localWorkbenchConfig.parameters.local_mesh_mm_per_gu)}else{@($trial.nonaccelerator_mesh_mm_per_gu)})
      accelerator_overlay_cell_mm_xyz=$null;reflectron_cell_mm=$null
      trajectory_quality=[double]$trial.trajectory_profile.trajectory_quality;rf_steps_per_period=$null
      accelerator_field_profile_id='mrtof_two_zone_standalone_operating_pa'
      frontend_pa0_sha256=$temporaryAnalyzerHash
      accelerator_overlay_pa0_sha256=(Get-FileHash -LiteralPath $sourceAccelerator -Algorithm SHA256).Hash
      reflectron_pa0_sha256=(Get-FileHash -LiteralPath $sourceDetector -Algorithm SHA256).Hash
      case_input_sha256=[string]$trial.operating_point_lua_sha256
      workload_topology_id='mrtof_local_refinement_8_instance_two_prism_full_flight'
      field_loading_policy_id='private_standalone_pa_copies_per_parallel_batch__no_refine'
    })
    Invoke-ProjectPython -Arguments @('-m','common.simion.resource_scheduler','--request',$dispatchRequestPath,'--profiles',$resourceProfilesPath,'--output',$runtimeDispatchPlanPath)
    Invoke-ProjectPython -Arguments @('-m','common.simion.particle_batching','--from-dispatch-plan',$runtimeDispatchPlanPath,'--output',$batchPlanPath)
    $batchRuntimeRoot=Join-Path ([IO.Path]::GetTempPath()) ('mrtof_batch_runtime_'+[guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $batchRuntimeRoot|Out-Null
    [int64]$perBatchPrivatePaBytes=[int64](Get-Item -LiteralPath $temporaryAnalyzer).Length+[int64](Get-Item -LiteralPath $sourceAccelerator).Length+[int64](Get-Item -LiteralPath $sourceDetector).Length
    foreach($path in $temporaryLocalPaths){$perBatchPrivatePaBytes+=[int64](Get-Item -LiteralPath $path).Length}
    function Assert-MrtofBatchTransientCapacity {
      param([Parameter(Mandatory)][int]$BatchCount,[Parameter(Mandatory)][string]$Label)
      [int64]$privateBytes=$perBatchPrivatePaBytes*$BatchCount
      $check=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
        -MinimumFreeGiB ([double]([int64](500GB)+$privateBytes)/1GB) -RequiredHeadroomBytes 0 `
        -ProtectedPaths $protectedPaths -ProtectedCacheKeys $startupProtectedCacheKeys
      $path=Join-Path $resultDir ("artifact_capacity_gate_batch_{0}.json"-f$Label)
      Write-RunJson -Path $path -Depth 14 -Value $check
      $script:batchCapacityReceipts+=@($path)
    }
    $batchRecords=@{}
    $batchTemplateRecord=$null
    $batchBundleReceiptPath=Join-Path $resultDir 'batch_iob_bundle_portability_receipt.json'
    $batchBundleReceipt=$null
    function New-MrtofBatchRecord {
      param([Parameter(Mandatory)]$PlannedBatch)
      $batchIndex=[int]$PlannedBatch.index;$batchCount=[int]$PlannedBatch.count
      $sourceParticleIdMin=if($bunchSelectionRequested){$BunchParticleIdMin}else{1}
      $batchParticleIdMin=$sourceParticleIdMin+[int]$PlannedBatch.particle_id_min-1
      $batchParticleIdMax=$sourceParticleIdMin+[int]$PlannedBatch.particle_id_max-1
      $batchOffset=$batchParticleIdMin-1
      $batchDir=Join-Path $batchRuntimeRoot ('batch_{0:D2}'-f$batchIndex)
      $batchPaDir=$batchDir
      New-Item -ItemType Directory -Path $batchDir|Out-Null
      # Every New-ShortPaCopy below registers a source guard that deliberately
      # prevents its operating PA from being written or deleted.  Record the
      # owning batch directory immediately so the post-flight cleanup releases
      # those guards before removing either the batch tree or the upstream
      # temporary operating-PA directory.
      $script:batchPaCopyDirectories+=@($batchPaDir)
      $batchFly2=Join-Path $batchDir 'mrtof_batch_source.fly2'
      # PowerShell includes every uncaptured pipeline value in a function's
      # return value.  Keep diagnostics visible without allowing them to turn
      # the structured batch record below into a heterogeneous array.
      Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight','materialize','--receipt',$bunchSourceLocal,'--particle-id-min',([string]$batchParticleIdMin),'--particle-id-max',([string]$batchParticleIdMax),'--output',$batchFly2) | Out-Host
      # Keep the projected standalone names identical to the established IOB
      # builder contract.  The private directory supplies batch isolation; a
      # new generic filename would be rejected as an ambiguous PA binding.
      $batchAnalyzer=New-ShortPaCopy -Source $temporaryAnalyzer -Destination (Join-Path $batchPaDir 'iob_input_analyzer.pa') -MarkDestinationReadOnly
      $batchAccelerator=New-ShortPaCopy -Source $sourceAccelerator -Destination (Join-Path $batchPaDir 'iob_input_accelerator.pa') -MarkDestinationReadOnly
      $batchDetector=New-ShortPaCopy -Source $sourceDetector -Destination (Join-Path $batchPaDir 'iob_input_detector.pa') -MarkDestinationReadOnly
      $batchLocals=@()
      if($temporaryLocalPaths.Count-gt0){foreach($localIndex in 0..($temporaryLocalPaths.Count-1)){
        $batchLocals+=New-ShortPaCopy -Source $temporaryLocalPaths[$localIndex] -Destination (Join-Path $batchPaDir ('iob_input_local_{0}.pa'-f($localIndex+1))) -MarkDestinationReadOnly
      }}
      $batchIob=Join-Path $batchDir 'mrtof_batch.iob'
      if($null-eq$localWorkbenchRun){
        $batchBuild=@('--nogui','--noprompt','lua',(Join-Path $solverDir 'build_three_component_iob.lua'),'--',(Join-Path $solverDir '3_instance_seed.iob'),$batchAnalyzer,$batchAccelerator,$batchDetector,$batchIob,$iobProgramPath,$batchFly2)+$originArguments+@('read_only_voltageized')
        Invoke-SimionStage -Stage ('build_batch_iob_{0:D2}'-f$batchIndex) -Arguments $batchBuild -ResourceLease $resourceLease | Out-Host
      }
      $batchCompanion=[IO.Path]::ChangeExtension($batchIob,'.fly2')
      if($null-eq$localWorkbenchRun-and-not(Test-RunFilesIdentical -Left $batchFly2 -Right $batchCompanion)){throw "Batch $batchIndex IOB companion Fly2 differs from its planned source slice."}
      $paPaths=@($batchAnalyzer)+$batchLocals+@($batchAccelerator,$batchDetector)
      $batchPrefix=[IO.Path]::GetFullPath($batchDir).TrimEnd([IO.Path]::DirectorySeparatorChar)+[IO.Path]::DirectorySeparatorChar
      foreach($paPath in $paPaths){
        if(-not[IO.Path]::GetFullPath([string]$paPath).StartsWith($batchPrefix,[StringComparison]::OrdinalIgnoreCase)){throw "Batch $batchIndex PA escapes its private bundle."}
      }
      $paIdentities=@($paPaths|ForEach-Object{Get-ShortPaCopyIdentity -Path $_})
      if(@($paIdentities|Where-Object{-not$_.destination_read_only}).Count-ne0){throw "Batch $batchIndex has a writable private PA before IOB assembly."}
      return [pscustomobject]@{
        index=$batchIndex;count=$batchCount;offset=$batchOffset;runtime_dir=$batchDir;iob=$batchIob
        source_fly2=$batchFly2;companion_fly2=$batchCompanion;pa_paths=$paPaths
        pa_hashes_before=@($paIdentities.sha256)
        companion_hashes_before=@()
        stdout=Join-Path $logDir ('native_two_prism_flight__batch{0:D2}.log'-f$batchIndex)
        stderr=Join-Path $logDir ('native_two_prism_flight__batch{0:D2}.stderr.log'-f$batchIndex)
        scheduler_batch=$PlannedBatch
      }
    }
    function Copy-MrtofBatchTemplateToRecord {
      param([Parameter(Mandatory)]$Template,[Parameter(Mandatory)]$Record)
      $companionSuffixes=@('.iob','.lua','.operating_point.lua','.voltage_map.lua','.mirror_cycle_counter.lua','.local_refinement.lua')
      foreach($suffix in $companionSuffixes){
        $source=Join-Path $Template.runtime_dir ('mrtof_batch'+$suffix)
        $target=Join-Path $Record.runtime_dir ('mrtof_batch'+$suffix)
        Copy-Item -LiteralPath $source -Destination $target -Force
        if(-not(Test-RunFilesIdentical -Left $source -Right $target)){throw "Batch $($Record.index) copied companion differs from template: $suffix"}
      }
      $Record.companion_hashes_before=@($companionSuffixes|Where-Object{$_-ne'.iob'}|ForEach-Object{
        (Get-FileHash -LiteralPath (Join-Path $Record.runtime_dir ('mrtof_batch'+$_)) -Algorithm SHA256).Hash
      })
      Copy-Item -LiteralPath $Record.source_fly2 -Destination $Record.companion_fly2 -Force
      if(-not(Test-RunFilesIdentical -Left $Record.source_fly2 -Right $Record.companion_fly2)){throw "Batch $($Record.index) companion Fly2 differs from its planned source slice."}
    }
    function Initialize-MrtofBatchTemplate {
      param([Parameter(Mandatory)][object[]]$Records)
      if($null-eq$localWorkbenchRun-or$Records.Count-eq0){return}
      $ordered=@($Records|Sort-Object index)
      $template=$ordered[0]
      $templateBuild=@('--nogui','--noprompt','lua',(Join-Path $solverDir 'build_local_refinement_iob.lua'),'--',(Join-Path $solverDir '8_instance_seed.iob'),$template.pa_paths[0])+@($template.pa_paths[1..5])+@($template.pa_paths[6],$template.pa_paths[7],$template.iob,$iobProgramPath,$template.source_fly2,$iobLocalConfig)+$localOriginArguments
      Invoke-SimionStage -Stage 'build_batch_iob_template_once' -Arguments $templateBuild -ResourceLease $resourceLease | Out-Host
      for($index=0;$index-lt$template.pa_paths.Count;$index++){
        $identity=Get-ShortPaCopyIdentity -Path $template.pa_paths[$index]
        if(-not$identity.destination_read_only-or$identity.sha256-ne[string]$template.pa_hashes_before[$index]){throw 'Template IOB assembly lost a private standalone PA read-only attribute.'}
      }
      if(-not(Test-RunFilesIdentical -Left $template.source_fly2 -Right $template.companion_fly2)){throw 'Template IOB companion Fly2 differs from its planned source slice.'}
      foreach($record in @($ordered|Select-Object -Skip 1)){Copy-MrtofBatchTemplateToRecord -Template $template -Record $record}
      $iobHash=(Get-FileHash -LiteralPath $template.iob -Algorithm SHA256).Hash
      $companionSuffixes=@('.lua','.operating_point.lua','.voltage_map.lua','.mirror_cycle_counter.lua','.local_refinement.lua')
      $members=@()
      foreach($record in $ordered){
        if((Get-FileHash -LiteralPath $record.iob -Algorithm SHA256).Hash-ne$iobHash){throw "Batch $($record.index) IOB differs from the one assembled template."}
        $record.companion_hashes_before=@($companionSuffixes|ForEach-Object{(Get-FileHash -LiteralPath (Join-Path $record.runtime_dir ('mrtof_batch'+$_)) -Algorithm SHA256).Hash})
        $members+=,[ordered]@{
          index=[int]$record.index;iob_sha256=$iobHash
          fly2_sha256=(Get-FileHash -LiteralPath $record.companion_fly2 -Algorithm SHA256).Hash
          pa_names=@($record.pa_paths|ForEach-Object{Split-Path $_ -Leaf})
          pa_hashes_before=@($record.pa_hashes_before)
          companion_sha256=@($record.companion_hashes_before)
        }
      }
      $script:batchTemplateRecord=$template
      $script:batchBundleReceipt=[ordered]@{
        schema_version=1;role='mrtof_batch_iob_bundle_portability';status='prepared';template_builder_invocations=1
        batch_count=$ordered.Count;iob_sha256=$iobHash;template_directory_hidden_during_clone_reload=$false
        relocated_inspection_report=$null;relocated_inspection_report_sha256=$null
        instance_basename_order=@('iob_input_analyzer.pa','iob_input_local_1.pa','iob_input_local_2.pa','iob_input_local_3.pa','iob_input_local_4.pa','iob_input_local_5.pa','iob_input_accelerator.pa','iob_input_detector.pa')
        instance_origins_project_mm=@($localOrigins);members=$members
        pa_isolation='eight_private_read_only_standalone_pas_per_batch'
        pa_immutability_proof='copy_sha256_verified_once__read_only_during_iob_portability__parent_held_no_write_handles_during_flight'
        fly2_isolation='one_distinct_sibling_companion_per_batch'
      }
      Write-RunJson -Path $batchBundleReceiptPath -Depth 20 -Value $script:batchBundleReceipt
    }
    function Assert-MrtofBatchClonePortability {
      param([Parameter(Mandatory)][object[]]$Records)
      if($null-eq$localWorkbenchRun-or$Records.Count-lt2){return}
      if($batchBundleReceipt.template_directory_hidden_during_clone_reload){throw 'Batch clone portability inspection was requested more than once.'}
      $ordered=@($Records|Sort-Object index)
      $template=$batchTemplateRecord
      if($null-eq$template){throw 'Batch clone portability inspection requires an initialized IOB template.'}
      $iobHash=[string]$batchBundleReceipt.iob_sha256
      $companionSuffixes=@('.lua','.operating_point.lua','.voltage_map.lua','.mirror_cycle_counter.lua','.local_refinement.lua')
      $members=@()
      foreach($record in $ordered){
        if(-not(Test-Path -LiteralPath $record.iob -PathType Leaf)){throw "Batch $($record.index) copied IOB is missing before portability inspection."}
        if((Get-FileHash -LiteralPath $record.iob -Algorithm SHA256).Hash-ne$iobHash){throw "Batch $($record.index) IOB differs from the one assembled template."}
        $record.companion_hashes_before=@($companionSuffixes|ForEach-Object{(Get-FileHash -LiteralPath (Join-Path $record.runtime_dir ('mrtof_batch'+$_)) -Algorithm SHA256).Hash})
        $members+=,[ordered]@{
          index=[int]$record.index;iob_sha256=$iobHash
          fly2_sha256=(Get-FileHash -LiteralPath $record.companion_fly2 -Algorithm SHA256).Hash
          pa_names=@($record.pa_paths|ForEach-Object{Split-Path $_ -Leaf});pa_hashes_before=@($record.pa_hashes_before)
          companion_sha256=@($record.companion_hashes_before)
        }
      }
      if(@($members.fly2_sha256|Select-Object -Unique).Count-ne$members.Count){throw 'Distinct batch intervals unexpectedly materialized identical Fly2 companions.'}
      $clone=@($ordered|Where-Object{[int]$_.index-ne[int]$template.index})[0]
      if($null-eq$clone){throw 'Batch clone portability inspection requires a non-template clone.'}
      $hidden=$template.runtime_dir+'.portability_hidden_'+[guid]::NewGuid().ToString('N')
      Move-Item -LiteralPath $template.runtime_dir -Destination $hidden
      try{
        $inspectionArguments=@()
        for($index=0;$index-lt8;$index++){
          foreach($value in @($localOrigins[$index])){$inspectionArguments+=Format-InvariantNumber ([double]$value)}
          $mesh=if($index-eq0){@($pose.mesh_mm_per_gu.analyzer)}elseif($index-le5){@($localFamilies[$index-1].contract.identity.mesh.mm_per_gu)}elseif($index-eq6){@($pose.mesh_mm_per_gu.accelerator)}else{@($pose.mesh_mm_per_gu.detector)}
          foreach($value in $mesh){$inspectionArguments+=Format-InvariantNumber ([double]$value)}
        }
        $inspectionReport=Join-Path $resultDir 'batch_iob_relocated_structure.txt'
        Invoke-SimionStage -Stage 'inspect_batch_iob_without_template_directory' -Arguments (@('--nogui','--noprompt','lua',(Join-Path $solverDir 'inspect_local_refinement_iob.lua'),'--',$clone.iob,$inspectionReport)+$inspectionArguments) -ResourceLease $resourceLease | Out-Host
      }finally{Move-Item -LiteralPath $hidden -Destination $template.runtime_dir}
      if(-not(Test-Path -LiteralPath $inspectionReport -PathType Leaf)){throw 'Relocated batch IOB inspection report is missing.'}
      for($index=0;$index-lt$clone.pa_paths.Count;$index++){
        $identity=Get-ShortPaCopyIdentity -Path $clone.pa_paths[$index]
        if(-not$identity.destination_read_only-or$identity.sha256-ne[string]$clone.pa_hashes_before[$index]){throw 'Relocated IOB inspection lost a clone private standalone PA read-only attribute.'}
      }
      $batchBundleReceipt.batch_count=$ordered.Count
      $batchBundleReceipt.members=$members
      $batchBundleReceipt.template_directory_hidden_during_clone_reload=$true
      $batchBundleReceipt.relocated_inspection_report=$inspectionReport
      $batchBundleReceipt.relocated_inspection_report_sha256=(Get-FileHash -LiteralPath $inspectionReport -Algorithm SHA256).Hash
      Write-RunJson -Path $batchBundleReceiptPath -Depth 20 -Value $batchBundleReceipt
    }
    function Get-MrtofBatchProcessSpecification {
      param([Parameter(Mandatory)]$Record)
      return [pscustomobject]@{
        name=('mrtof_simion_batch_{0:D2}'-f$Record.index);scheduler_batch=$Record.scheduler_batch
        file_path=$simion;working_directory=$Record.runtime_dir;stdout=$Record.stdout;stderr=$Record.stderr;environment=@{}
        argument_list=[string[]]@('--nogui','--noprompt','lua',(Join-Path $solverDir 'run_iob_flight.lua'),$Record.iob)
      }
    }
    $initialBatchPlan=Get-Content -Raw -LiteralPath $batchPlanPath|ConvertFrom-Json
    Assert-MrtofBatchTransientCapacity -BatchCount ([int]$initialBatchPlan.batch_count) -Label 'initial_dispatch'
    foreach($planned in @($initialBatchPlan.batches)){$batchRecords[[int]$planned.index]=New-MrtofBatchRecord -PlannedBatch $planned}
    Initialize-MrtofBatchTemplate -Records @($batchRecords.Values)
    $resourceLease=Update-HostResourceStage -Lease $resourceLease -Stage 'mrtof_flight' `
      -Budget (Get-HostResourceBudget -Role SIMION -Stage 'mrtof_flight') -RetainedMemoryBytes 0
    $dispatch=Get-Content -Raw -LiteralPath $runtimeDispatchPlanPath|ConvertFrom-Json
    $resourceIdentityWasUnknown=[string]$dispatch.estimation.kind-eq'formal_first_batch_observation'
    $existingRecords=@()
    if([string]$dispatch.estimation.kind-eq'formal_first_batch_observation'){
      $firstSpec=Get-MrtofBatchProcessSpecification -Record $batchRecords[1]
      $formal=Start-ObservedFormalProcess -DispatchPlanPath $runtimeDispatchPlanPath -ProcessSpecification $firstSpec -WaitForNaturalCompletionAfterObservation
      if($formal.resource_budget_exceeded-or-not$formal.completed_naturally-or[int]$formal.exit_code-ne0){throw 'MR-TOF formal first batch did not complete safely.'}
      Invoke-ProjectPython -Arguments @('-m','common.simion.resource_scheduler','--request',$dispatchRequestPath,'--profiles',$resourceProfilesPath,'--output',$runtimeDispatchPlanPath,'--observed-formal-peak-bytes',([string]$formal.observed_peak_process_tree_working_set_bytes),'--observed-formal-cpu-percent',([string]$formal.observed_process_cpu_percent),'--observed-background-cpu-percent',([string]$formal.observed_background_cpu_percent),'--available-memory-bytes',([string]$formal.available_memory_bytes),'--total-physical-memory-bytes',([string]$formal.total_physical_memory_bytes),'--first-batch-completed')
      Invoke-ProjectPython -Arguments @('-m','common.simion.particle_batching','--from-dispatch-plan',$runtimeDispatchPlanPath,'--output',$batchPlanPath)
      $existingRecords=@($formal.process_record)
      $replanned=Get-Content -Raw -LiteralPath $batchPlanPath|ConvertFrom-Json
      Assert-MrtofBatchTransientCapacity -BatchCount ([int]$replanned.batch_count) -Label 'formal_replan'
      foreach($planned in @($replanned.batches)){
        $plannedIndex=[int]$planned.index
        if($batchRecords.ContainsKey($plannedIndex)){
          $existing=$batchRecords[$plannedIndex]
          $plannedGlobalOffset=[int]$planned.simion_particle_id_offset
          if($bunchSelectionRequested){$plannedGlobalOffset+=$BunchParticleIdMin-1}
          if([int]$existing.count-ne[int]$planned.count-or[int]$existing.offset-ne$plannedGlobalOffset){throw 'Formal-first replan changed an already completed batch interval.'}
        }else{
          $batchRecords[$plannedIndex]=New-MrtofBatchRecord -PlannedBatch $planned
          if($null-ne$localWorkbenchRun){Copy-MrtofBatchTemplateToRecord -Template $batchTemplateRecord -Record $batchRecords[$plannedIndex]}
        }
      }
    }
    # Formal-first dispatch may initially create only the template batch and
    # add clones during replan.  Inspect the first actual clone exactly here:
    # after every final-plan bundle exists and before any pending flight starts.
    Assert-MrtofBatchClonePortability -Records @($batchRecords.Values)
    foreach($record in @($batchRecords.Values)){
      foreach($paPath in @($record.pa_paths)){
        $identity=Protect-ShortPaCopyDestination -Path $paPath
        if(-not$identity.destination_write_guarded){throw "Batch $($record.index) private PA write guard was not established before flight."}
      }
    }
    $finalBatchPlan=Get-Content -Raw -LiteralPath $batchPlanPath|ConvertFrom-Json
    $pendingSpecs=@($finalBatchPlan.batches|Where-Object{[int]$_.index-ne1-or$existingRecords.Count-eq0}|ForEach-Object{Get-MrtofBatchProcessSpecification -Record $batchRecords[[int]$_.index]})
    $batchWaveResult=Invoke-ResourceBudgetedProcesses -DispatchPlanPath $runtimeDispatchPlanPath -RunDir $runDir -UsagePath $batchResourceUsagePath -ProcessSpecifications $pendingSpecs -ExistingProcessRecords $existingRecords
    if($batchWaveResult.resource_budget_exceeded-or@($batchWaveResult.processes|Where-Object{[int]$_.exit_code-ne0}).Count-ne0){throw 'MR-TOF SIMION batch wave failed or exceeded the repository resource budget.'}
    Complete-ResourceUsage -RunDir $runDir -UsagePath $batchResourceUsagePath|Out-Null
    if($null-ne$localWorkbenchRun){
      foreach($record in @($batchRecords.Values)){
        $after=@($record.pa_paths|ForEach-Object{
          $identity=Get-ShortPaCopyIdentity -Path $_
          if(-not$identity.destination_write_guarded){throw "Batch $($record.index) private PA lost its no-write guard."}
          $identity.sha256
        })
        for($hashIndex=0;$hashIndex-lt$after.Count;$hashIndex++){
          if([string]$record.pa_hashes_before[$hashIndex]-ne[string]$after[$hashIndex]){throw "Batch $($record.index) flight changed its private standalone PA set."}
        }
        if((Get-FileHash -LiteralPath $record.iob -Algorithm SHA256).Hash-ne[string]$batchBundleReceipt.iob_sha256){throw "Batch $($record.index) flight changed its copied IOB."}
        $suffixes=@('.lua','.operating_point.lua','.voltage_map.lua','.mirror_cycle_counter.lua','.local_refinement.lua')
        $companionAfter=@($suffixes|ForEach-Object{(Get-FileHash -LiteralPath (Join-Path $record.runtime_dir ('mrtof_batch'+$_)) -Algorithm SHA256).Hash})
        if($record.companion_hashes_before.Count-eq0){$record.companion_hashes_before=$companionAfter}
        if(@(Compare-Object @($record.companion_hashes_before) $companionAfter).Count-ne0){throw "Batch $($record.index) flight changed its invariant companion set."}
        $member=@($batchBundleReceipt.members|Where-Object{[int]$_.index-eq[int]$record.index})
        if($member.Count-eq0){
          $newIobHash=(Get-FileHash -LiteralPath $record.iob -Algorithm SHA256).Hash
          if($newIobHash-ne[string]$batchBundleReceipt.iob_sha256){throw "Batch $($record.index) copied IOB differs from the template."}
          $newCompanionHashes=@($suffixes|ForEach-Object{(Get-FileHash -LiteralPath (Join-Path $record.runtime_dir ('mrtof_batch'+$_)) -Algorithm SHA256).Hash})
          if(@(Compare-Object @($batchBundleReceipt.members[0].companion_sha256) $newCompanionHashes).Count-ne0){throw "Batch $($record.index) companion set differs from the template."}
          $batchBundleReceipt.members+=,[ordered]@{
            index=[int]$record.index;iob_sha256=$newIobHash
            fly2_sha256=(Get-FileHash -LiteralPath $record.companion_fly2 -Algorithm SHA256).Hash
            pa_names=@($record.pa_paths|ForEach-Object{Split-Path $_ -Leaf});pa_hashes_before=@($record.pa_hashes_before)
            companion_sha256=$newCompanionHashes;pa_hashes_after=$after
          }
        }else{$member[0].pa_hashes_after=$after}
      }
      $batchBundleReceipt.status='success';$batchBundleReceipt.batch_count=@($batchBundleReceipt.members).Count;$batchBundleReceipt.all_private_pa_hashes_unchanged=$true
      Write-RunJson -Path $batchBundleReceiptPath -Depth 20 -Value $batchBundleReceipt
    }
    if($resourceIdentityWasUnknown){
      $resourceProfilePath=Join-Path $resultDir 'simion_resource_profile.json'
      Invoke-ProjectPython -Arguments @('-m','common.simion.resource_profile','publish','--run-id',$RunId,'--resource-usage',$batchResourceUsagePath,'--resource-usage-relative-path','logs/simion_batch_resource_usage.json','--dispatch-plan',$runtimeDispatchPlanPath,'--dispatch-plan-relative-path','results/simion_repository_dispatch_plan.json','--output',$resourceProfilePath)
    }
    $rawLog=Join-Path $logDir 'native_two_prism_flight.log';$batchMergeReceipt=Join-Path $resultDir 'batch_log_merge_receipt.json'
    $mergeParticleIdMin=if($bunchSelectionRequested){$BunchParticleIdMin}else{1}
    $mergeArgs=@('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight','merge','--particle-count',([string]$trial.source_particle_count),'--particle-id-min',([string]$mergeParticleIdMin),'--output',$rawLog,'--receipt',$batchMergeReceipt)
    foreach($planned in @($finalBatchPlan.batches)){$record=$batchRecords[[int]$planned.index];$mergeArgs+=@('--batch-log',$record.stdout,([string]$record.offset),([string]$record.count))}
    Invoke-ProjectPython -Arguments $mergeArgs
  }
  if(@(Compare-Object $upstreamHashes @($upstreamPaths|ForEach-Object{(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash})).Count-ne 0){throw 'Read-only IOB build or flight changed an upstream PA'}
  if($localCacheSentinelPaths.Count-and@(Compare-Object $localCacheSentinelHashes @($localCacheSentinelPaths|ForEach-Object{(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash})).Count-ne 0){throw 'IOB build or SIMION flight changed immutable local PA-family bookkeeping'}
  if(@(Compare-Object $upstreamHashes @($upstreamPaths|ForEach-Object{(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash})).Count-ne 0){throw 'Runtime Fast Adjust changed an upstream PA'}
  if($localCacheSentinelPaths.Count-and@(Compare-Object $localCacheSentinelHashes @($localCacheSentinelPaths|ForEach-Object{(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash})).Count-ne 0){throw 'SIMION flight changed immutable local PA-family bookkeeping'}
  if($localCacheSentinelPaths.Count){
    foreach($family in $localFamilies){
      Resolve-AnalyzerLocalStandaloneResponseSubset -Family $family -ResponseIds $requiredResponseIds -CacheRoot (Join-Path $artifactRoot 'common\simion\pa_family_cache')|Out-Null
    }
  }
  if($isBunchFlight){
    foreach($path in @($batchPaCopyDirectories)){
      Remove-ShortPaCopiesUnderDirectory -Path $path -ExpectedNamePrefix 'batch_'
    }
    $batchPaCopyDirectories=@()
    if($null-ne$batchRuntimeRoot){Remove-TemporarySolverDirectory -Path $batchRuntimeRoot;$batchRuntimeRoot=$null}
  }
  $resourceLease=Update-HostResourceStage -Lease $resourceLease -Stage 'mrtof_postprocess' `
    -Budget (Get-HostResourceBudget -Role SIMION -Stage 'mrtof_postprocess') -RetainedMemoryBytes 0
  if($null-ne$iobInputCopyDir){Remove-ShortPaCopyDirectory -Path $iobInputCopyDir;$iobInputCopyDir=$null}
  $rawLog=Join-Path $logDir 'native_two_prism_flight.log';$observation=Join-Path $resultDir 'two_prism_trial_observation.json'
  $failureStage='analyze_trial'
  Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial','analyze','--log',$rawLog,'--trial-receipt',$trialReceipt,'--output',$observation)
  $observed=Get-Content -LiteralPath $observation -Raw -Encoding UTF8|ConvertFrom-Json
  $observedResiduals=if($null-ne$observed.PSObject.Properties['residuals']){$observed.residuals}else{$null}
  $observedExtraction=if($null-ne$observed.PSObject.Properties['extraction_diagnostic']){$observed.extraction_diagnostic}else{$null}
  $detectorHit=($null-ne$observedExtraction-and$observedExtraction.status-eq'detector_hit')
  $pulseClause=if($PulseAcceleratorUntilInitialExit){' The accelerator remained energized through the first exit and was then grounded using the measured single-centre exit event; this event-triggered schedule is not valid for a bunch.'}elseif($null-ne$acceleratorPulseSchedule){' The frozen source consumed one schema-2 global pulse-off schedule bound to the complete cohort safe-exit envelope.'}else{' The accelerator remained static.'}
  $summaryReason=if($bunchSelectionRequested){"The contiguous frozen source interval $BunchParticleIdMin..$BunchParticleIdMax was replayed as a diagnostic without filtering its outcomes."+$pulseClause+' Detection and collision evidence remain Candidate diagnostics.'}elseif($null-ne$bunchSourceContract){'The complete frozen N>1 cohort was flown without filtering losses.'+$pulseClause+' Detection, target-K, overtone and TOF statistics remain Candidate evidence.'}elseif($detectorHit){'The fixed reviewed geometry was flown once from the physical 5-eV pre-acceleration state with unchanged static prism voltages.'+$pulseClause+' A natural non-retracing detector hit proves only the single-centre event chain; target-K closure remains independently required.'}else{'The fixed reviewed geometry was flown once from the physical 5-eV pre-acceleration state with unchanged static prism voltages.'+$pulseClause+' No natural non-retracing detector hit was observed, so the prototype event chain remains open.'}
  $cohortAnalysis=if($null-ne$observed.PSObject.Properties['cohort_analysis']){$observed.cohort_analysis}else{$null}
  $dispatchSummary=$null
  if($isBunchFlight){
    $dispatchDocument=Get-Content -Raw -LiteralPath $runtimeDispatchPlanPath|ConvertFrom-Json
    $usageDocument=Get-Content -Raw -LiteralPath $batchResourceUsagePath|ConvertFrom-Json
    $cpuLimit=[int]$dispatchDocument.limits.cpu_capacity;$memoryLimit=[int]$dispatchDocument.limits.memory_capacity
    $bottleneck=if($cpuLimit-lt$memoryLimit){'cpu'}elseif($memoryLimit-lt$cpuLimit){'memory'}else{'cpu_and_memory_equal'}
    $dispatchSummary=[ordered]@{
      requested_particles=[int]$trial.source_particle_count
      planned_workers=[int]$dispatchDocument.limits.maximum_concurrency
      peak_active_workers=[int]$usageDocument.execution_wave.peak_concurrency
      bottleneck=$bottleneck
      estimation_kind=[string]$dispatchDocument.estimation.kind
      parallelism_result=$(if([int]$usageDocument.execution_wave.peak_concurrency-gt1){'parallel_workers_observed'}elseif([int]$dispatchDocument.limits.maximum_concurrency-eq1){"planner_limited_by_$bottleneck"}else{'runtime_admission_remained_serial__inspect_resource_usage_pause_events'})
    }
  }
  $summaryQualification=if($bunchSelectionRequested){'candidate_bunch_selection_diagnostic__not_formal'}elseif($null-ne$bunchSourceContract){'candidate_bunch__not_formal'}else{'single_center_trial__not_an_operating_point'}
  $summaryValue=[ordered]@{schema_version=1;role='mrtof_finite_3d_two_prism_voltage_trial';status='success';qualification=$summaryQualification;source_particle_count=[int]$trial.source_particle_count;source_cohort=$trial.source_cohort;dispatch=$dispatchSummary;stripe_biases_v=@($trial.stripe_biases_v);prism_voltages_v=@($Prism1VoltageV,$Prism2VoltageV);accelerator_pulse=$trial.accelerator_pulse;accelerator_pulse_diagnostic=$observed.accelerator_pulse_diagnostic;transport_status=$observed.status;cohort_analysis=$cohortAnalysis;extraction_diagnostic=$observedExtraction;residuals=$observedResiduals;reason=$summaryReason}
  Write-RunJson -Path $summary -Value $summaryValue
  $config=Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($RetainGuiWorkbench){
    $guiWorkbenchIob=$temporaryIob
    $guiWorkbenchReceipt=Join-Path $resultDir 'gui_workbench_receipt.json'
    $guiWorkbenchOutputs=@(Get-ChildItem -LiteralPath $temporarySolverDir -File|Sort-Object Name|ForEach-Object{$_.FullName})
    $guiFiles=@($guiWorkbenchOutputs|ForEach-Object{$item=Get-Item -LiteralPath $_;[ordered]@{name=$item.Name;path=$item.FullName;bytes=[int64]$item.Length;sha256=(Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash}})
    Write-RunJson -Path $guiWorkbenchReceipt -Depth 14 -Value ([ordered]@{
      schema_version=1;role='simion_gui_review_workbench';status='success';qualification=$summaryQualification;
      iob_path=$guiWorkbenchIob;iob_sha256=(Get-FileHash -LiteralPath $guiWorkbenchIob -Algorithm SHA256).Hash;
      global_operating_pa_path=$temporaryAnalyzer;global_operating_pa_sha256=$temporaryAnalyzerHash;
      local_operating_cache_key=$operatingCacheKey;local_operating_cache_generation=$operatingCacheGeneration;
      source_accelerator_pa=$sourceAccelerator;accelerator_binding='manifest_bound_standalone_operating_pa__field_gate_only';source_detector_pa=$sourceDetector;files=$guiFiles
    })
    # The IOB stores the absolute paths passed to SIMION. Keeping this exact
    # directory in place is therefore part of the review artifact contract.
    $temporarySolverDir=$null
  }else{Remove-TemporarySolverDirectory -Path $temporarySolverDir;$temporarySolverDir=$null}
  $artifactResultDir=Join-Path ([string]$package.artifact_run_dir) 'results'
  # The builder copies every executable companion beside the output IOB.  A
  # retained GUI package therefore runs the nested copies, not their root-level
  # build inputs; compact artifacts keep the ordinary SIMION root layout.
  $flightArtifactRoot=if($RetainGuiWorkbench){Join-Path $artifactSolverDir 'gui_workbench'}else{$artifactSolverDir}
  $config.inputs=[ordered]@{
    geometry_run_manifest=$geometryManifest
    mirror_run_manifest=$mirrorManifest
    stripe_run_manifest=$stripeManifest
    accelerator_run_manifest=$acceleratorManifest
    accelerator_family_run_manifest=$null
    accelerator_pulse_schedule=$acceleratorPulseSchedule
    bunch_source_receipt=if($null-eq$bunchSourceReceipt){$null}else{Join-Path $artifactSolverDir 'bunch_source_receipt.json'}
    bunch_source_run_manifest=$bunchSourceManifest
    simion_dispatch_request=$dispatchRequestPath
    simion_resource_profiles=$resourceProfilesPath
    simion_repository_dispatch_plan=$runtimeDispatchPlanPath
    simion_execution_batch_plan=$batchPlanPath
    batch_log_merge_receipt=$batchMergeReceipt
    batch_iob_bundle_portability_receipt=if($null-eq$batchBundleReceiptPath){$null}else{Join-Path $artifactResultDir 'batch_iob_bundle_portability_receipt.json'}
    local_workbench_run_manifest=$localWorkbenchManifest
    trajectory_numerics_contract=Join-Path $artifactSolverDir 'trajectory_numerics_contract.json'
    iob_builder=if($reuseFrozenWorkbenchAnalyzer){Join-Path $artifactSolverDir 'build_local_refinement_iob.lua'}else{Join-Path $artifactSolverDir 'build_three_component_iob.lua'}
    iob_seed=if($reuseFrozenWorkbenchAnalyzer){Join-Path $artifactSolverDir '8_instance_seed.iob'}else{Join-Path $artifactSolverDir '3_instance_seed.iob'}
    local_refinement_sidecar=if(-not$reuseFrozenWorkbenchAnalyzer){$null}elseif($RetainGuiWorkbench){Join-Path $flightArtifactRoot 'mrtof_three_component_candidate.local_refinement.lua'}else{Join-Path $artifactSolverDir 'local_trial_refinement.lua'}
    flight_program=Join-Path $flightArtifactRoot 'mrtof_three_component_candidate.lua'
    mirror_cycle_counter=Join-Path $flightArtifactRoot 'mrtof_three_component_candidate.mirror_cycle_counter.lua'
    voltage_map=Join-Path $flightArtifactRoot 'mrtof_three_component_candidate.voltage_map.lua'
    flight_launcher=Join-Path $artifactSolverDir 'run_iob_flight.lua'
    trial_materializer=Join-Path $artifactSolverDir 'two_prism_simion_trial.py'
    analyzer_voltageizer=if($reuseFrozenWorkbenchAnalyzer){$null}else{Join-Path $artifactSolverDir 'voltageize_analyzer_pa0.lua'}
    basis_adjuster=Join-Path $artifactSolverDir 'compose_standalone_pa.lua'
    basis_voltage_measurement=$null
    read_only_analyzer_pa=$workbenchAnalyzer
    read_only_accelerator_pa=$sourceAccelerator
    read_only_accelerator_family=$null
    writable_accelerator_family_materialization=$null
    read_only_detector_pa=$sourceDetector
    trial_materialization=Join-Path $artifactResultDir 'two_prism_trial_materialization.json'
    frozen_source_fly2=Join-Path $artifactSolverDir 'downstream_trial_source.input.fly2'
    local_operating_pa_cache_identity=if($null-eq$operatingCacheIdentityPath){$null}else{Join-Path $artifactResultDir 'local_operating_pa_cache_identity.json'}
    gui_workbench_iob=$guiWorkbenchIob
    gui_workbench_receipt=$guiWorkbenchReceipt
  }
  if(-not$config.Contains('provenance')){$config['provenance']=[ordered]@{}}
  $config['provenance']['upstream_manifest_verification']=[ordered]@{
    geometry=[ordered]@{
      scope='consumer_projection'
      projection_id=$geometryConsumerProjectionId
      manifest=$geometryManifest
      consumed_inputs=@([ordered]@{name='resolved_prototype_contract';path=$geometryReviewedContract})
      unconsumed_records_not_asserted=$true
    }
    all_other_upstream_manifests='full'
  }
  $config.parameters.prism_1_voltage_v=$Prism1VoltageV;$config.parameters.prism_2_voltage_v=$Prism2VoltageV;$config.parameters.stripe_biases_v=@($trial.stripe_biases_v);$config.parameters.source_particle_count=[int]$trial.source_particle_count;$config.parameters.source_cohort=$trial.source_cohort;$config.parameters.source_selection=$trial.source_selection;$config.parameters.simion_dispatch=$dispatchSummary;$config.parameters.flight_scope='complete_three_dimensional_static_return';$config.parameters.accelerator_pulse=$trial.accelerator_pulse;$config.parameters.accelerator_field_mode=if($acceleratorPulseRequested){'manifest_bound_standalone_operating_pa__efield_gate_to_zero'}else{'manifest_bound_standalone_operating_pa__static'};$config.parameters.bootstrap_global_operating_pa=[bool]$BootstrapGlobalOperatingPa;$config.parameters.pa_binding_mode=if($null-eq$localWorkbenchRun){'read_only_global_family_to_private_standalone_bootstrap__no_refine'}elseif($null-ne$localOperatingCacheReceipt-and$localOperatingCacheReceipt.disposition-eq'transient_miss_not_published'){'frozen_global_standalone_plus_transient_local_response_deltas__no_refine'}elseif($null-ne$localOperatingCacheReceipt){'frozen_global_standalone_plus_content_addressed_local_operating_pa'}elseif($localAdjustmentReceipts.Count-eq 0){'frozen_global_and_local_standalone_baseline'}else{'frozen_global_standalone_plus_local_response_deltas__no_refine'};$config.parameters.local_extraction_field_handoff=$null;$config.parameters.trajectory_profile=$trial.trajectory_profile;$config.parameters.gui_workbench_retained=[bool]$RetainGuiWorkbench;Write-RunJson -Path $runConfig -Value $config
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $failureStage='capacity_terminal';$maximum=[int64](Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File|Measure-Object Length -Sum).Sum
  $protectedCacheKeys=if($null-eq$localWorkbenchRun){@()}else{@($localFamilies.cache_key)};if($null-ne$operatingCacheGeneration){$protectedCacheKeys+=$operatingCacheKey}
  $terminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -ProtectedPaths @($package.artifact_run_dir) -ProtectedCacheKeys $protectedCacheKeys `
    -KnownMeasuredBytes ([int64]$startup.measured_after_bytes) -MaximumNewArtifactBytes $maximum
  $terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  $manifestOutputs=@($summary,$rawLog,$observation,$trialReceipt,$voltageReceipt,$posePath,$startupPath,$terminalPath,$retention)
  foreach($path in @($dispatchRequestPath,$resourceProfilesPath,$runtimeDispatchPlanPath,$batchPlanPath,$batchResourceUsagePath,$batchMergeReceipt,$resourceProfilePath)+@($batchCapacityReceipts)){if($null-ne$path-and(Test-Path -LiteralPath $path -PathType Leaf)){$manifestOutputs+=$path}}
  if($null-ne$batchBundleReceiptPath-and(Test-Path -LiteralPath $batchBundleReceiptPath -PathType Leaf)){$manifestOutputs+=$batchBundleReceiptPath}
  $batchRelocatedInspectionReport=Join-Path $resultDir 'batch_iob_relocated_structure.txt'
  if(Test-Path -LiteralPath $batchRelocatedInspectionReport -PathType Leaf){$manifestOutputs+=$batchRelocatedInspectionReport}
  if($isBunchFlight){foreach($record in @($batchRecords.Values)){foreach($path in @($record.stdout,$record.stderr)){if(Test-Path -LiteralPath $path -PathType Leaf){$manifestOutputs+=$path}}}}
  if($null-ne$operatingCacheIdentityPath){$manifestOutputs+=$operatingCacheIdentityPath}
  if($null-ne$guiWorkbenchReceipt){$manifestOutputs+=$guiWorkbenchReceipt}
  if($guiWorkbenchOutputs.Count){$manifestOutputs+=@($guiWorkbenchOutputs)}
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success -Software @('SIMION 2020','Python 3.11') -Outputs $manifestOutputs
  $terminalized=$true;$hostOutcome='success';Write-Host "MRTOF_TWO_PRISM_TRIAL=PASS RUN_ID=$RunId TRANSPORT=$($observed.status)"
}catch{
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_finite_3d_two_prism_voltage_trial' -Reason $_.Exception.Message -Software @('SIMION 2020','Python 3.11') -Status failed -FailureStage $failureStage;$terminalized=$true};throw
}finally{
  if(-not$terminalized-and(Test-Path -LiteralPath $runConfig -PathType Leaf)){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_finite_3d_two_prism_voltage_trial' -Reason 'Runner stopped before terminal evidence publication.' -Software @('SIMION 2020','Python 3.11') -Status interrupted -FailureStage $failureStage;$hostOutcome='interrupted'}
  if($null-ne$resourceLease){
    $topLevelLease=-not[bool]$resourceLease.inherited
    Exit-HostResourceStage -Lease $resourceLease
    if($topLevelLease){Invoke-HostExecutionCompletionNotification -Outcome $hostOutcome -RunId $RunId}
  }
  Remove-RunPackageExecutionAlias -Package $package
  if($null-ne$iobInputCopyDir){Remove-ShortPaCopyDirectory -Path $iobInputCopyDir}
  if($null-ne$basisLinkDir){Remove-ShortPaCopyDirectory -Path $basisLinkDir}
  foreach($path in @($batchPaCopyDirectories)){
    if(Test-Path -LiteralPath $path -PathType Container){
      Remove-ShortPaCopiesUnderDirectory -Path $path -ExpectedNamePrefix 'batch_'
    }
  }
  if($null-ne$batchRuntimeRoot-and(Test-Path -LiteralPath $batchRuntimeRoot -PathType Container)){Remove-TemporarySolverDirectory -Path $batchRuntimeRoot}
  if($null-ne$temporarySolverDir-and-not$RetainGuiWorkbench){Remove-TemporarySolverDirectory -Path $temporarySolverDir}
}
