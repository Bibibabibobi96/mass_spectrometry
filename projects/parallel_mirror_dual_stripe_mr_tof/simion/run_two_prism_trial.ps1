[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$GeometryReviewRunPath,
  [Parameter(Mandatory)][string]$MirrorRunPath,
  [Parameter(Mandatory)][string]$StripeRunPath,
  [Parameter(Mandatory)][string]$AcceleratorProviderReceiptPath,
  [string]$AcceleratorFamilyRunPath='',
  [Parameter(Mandatory)][double]$Prism1VoltageV,
  [Parameter(Mandatory)][double]$Prism2VoltageV,
  [Nullable[double]]$Stripe1VoltageV=$null,
  [Nullable[double]]$Stripe2VoltageV=$null,
  [string]$NativeCorridorBankRunPath='',
  [string]$NativeSystemRuntimeBundlePath='',
  [switch]$PulseAcceleratorUntilInitialExit,
  [switch]$AcceleratorSafeExitOnly,
  [string]$AcceleratorPulseSchedulePath='',
  [string]$MirrorVoltageVariationPath='',
  [string]$ContractPath='',
  [string]$BunchSourceReceiptPath='',
  [string]$BatchContinuationRunPath='',
  [int]$BunchParticleIdMin=0,
  [int]$BunchParticleIdMax=0,
  [string]$TrajectoryProfileId='',
  [double]$TrajectoryStepScale=1.0,
  [double]$AcceleratorSourceYOffsetMm=0.0,
  [Nullable[double]]$AcceleratorYAnchorMm=$null,
  [pscustomobject]$CapacityWorkflowSession=$null,
  [pscustomobject]$NativeCorridorRuntimeSession=$null,
  [string]$NativeRuntimeCheckpoint='',
  [pscustomobject]$InheritedHostResourceLease=$null,
  [switch]$RetainGuiWorkbench,
  [string]$RunId='',
  [string]$SimionExe='',
  [string]$PythonExe=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

function Copy-RequiredInput {
  param([string]$Source,[string]$Destination,[string]$Label)
  if(-not(Test-Path -LiteralPath $Source -PathType Leaf)){throw "$Label is missing: $Source"}
  Copy-VerifiedRunInput -Source $Source -Destination $Destination -VerificationAttempts 3
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
  param([string]$Stage,[string[]]$Arguments,[Parameter(Mandatory)]$ResourceLease,[bool]$RegisterHostProcess=$true)
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
  $logWriter=$null
  try{
    $logWriter=[IO.StreamWriter]::new((Join-Path $logDir "$Stage.log"),$false,[Text.UTF8Encoding]::new($false))
    $logWriter.AutoFlush=$true
    $streams=@(
      [pscustomobject]@{Reader=$process.StandardOutput;Pending=$process.StandardOutput.ReadLineAsync();Done=$false},
      [pscustomobject]@{Reader=$process.StandardError;Pending=$process.StandardError.ReadLineAsync();Done=$false}
    )
    $elapsed=[Diagnostics.Stopwatch]::StartNew()
    $nextHeartbeat=30.0
    $lastKeyEvent='process_started'
    $reportedError=$false
    $errorPattern='(?i)^\s*error,|Failed saving PA|Aborting PA updates'
    $importantPattern='(?i)^MRTOF_CANDIDATE:|^MRTOF_NATIVE_FAST_ADJUST (begin|complete)\b|^MRTOF_EVENT (turn|slow_turn|drift_phase_candidate|target_k|target_k_phase_sample|detector|terminal|splat|accelerator_safe_exit|accelerator_reentry)\b|status,Flying particles\.|Fly completed\.|\b(?:loading|loaded)\b.*\.pa|(?:^|[ _])(?:PASS|FAIL|ERROR|STOP)(?:\b|=)'
    Write-Host "SIMION_STAGE=START STAGE=$Stage PID=$($process.Id)"
    if($RegisterHostProcess-and-not$process.HasExited){
      try{Register-HostResourceProcess -Lease $ResourceLease -ProcessId $process.Id}
      catch{
        if(-not$process.HasExited-or-not$_.Exception.Message.Contains('registered process must be a live descendant')){throw}
        Write-Host "HOST_RESOURCE_PROCESS=COMPLETED_BEFORE_REGISTRATION STAGE=$Stage PID=$($process.Id)"
      }
    }elseif($RegisterHostProcess){
      Write-Host "HOST_RESOURCE_PROCESS=COMPLETED_BEFORE_REGISTRATION STAGE=$Stage PID=$($process.Id)"
    }
    # Both pipes always have an outstanding read.  Process completed lines on
    # this runspace; callbacks on .NET worker threads cannot safely run PS code.
    while(-not($streams[0].Done-and$streams[1].Done)-or-not$process.HasExited){
      $progressed=$false
      foreach($stream in $streams){
        if($stream.Done-or-not$stream.Pending.IsCompleted){continue}
        $line=$stream.Pending.GetAwaiter().GetResult()
        $progressed=$true
        if($null-eq$line){$stream.Done=$true;continue}
        $logWriter.WriteLine($line)
        if($line-match$errorPattern){$reportedError=$true}
        if($line-match$errorPattern-or$line-match$importantPattern){
          $lastKeyEvent=$line
          Write-Host $line
        }
        $stream.Pending=$stream.Reader.ReadLineAsync()
      }
      if($elapsed.Elapsed.TotalSeconds-ge$nextHeartbeat){
        $process.Refresh()
        $cpuSeconds=$process.TotalProcessorTime.TotalSeconds
        Write-Host ("SIMION_STAGE=RUNNING STAGE={0} ELAPSED_S={1:F1} CPU_S={2:F1} LAST_KEY_EVENT={3}" -f $Stage,$elapsed.Elapsed.TotalSeconds,$cpuSeconds,$lastKeyEvent)
        $nextHeartbeat=$elapsed.Elapsed.TotalSeconds+30.0
      }
      if(-not$progressed){Start-Sleep -Milliseconds 20}
    }
    $process.WaitForExit()
    Write-Host ("SIMION_STAGE=EXIT STAGE={0} EXIT_CODE={1} ELAPSED_S={2:F1}" -f $Stage,$process.ExitCode,$elapsed.Elapsed.TotalSeconds)
    if($process.ExitCode-ne 0){throw "SIMION stage failed: $Stage"}
    # SIMION can report a guarded PA save failure while returning exit zero.
    if($reportedError){
      throw "SIMION stage reported an error despite exit zero: $Stage"
    }
  }finally{if($null-ne$logWriter){$logWriter.Dispose()};$process.Dispose()}
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
function Get-ManifestOutputRecord {
  param(
    [Parameter(Mandatory)][string]$Path,
    [Parameter(Mandatory)]$Manifest,
    [Parameter(Mandatory)][string]$Label
  )
  $resolved=(Resolve-Path -LiteralPath $Path).Path
  $records=@($Manifest.outputs|Where-Object{
    [string]::Equals([IO.Path]::GetFullPath([string]$_.path),$resolved,[StringComparison]::OrdinalIgnoreCase)
  })
  if($records.Count-ne1){throw "$Label is not uniquely bound by its manifest: $resolved"}
  return $records[0]
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
if(-not[double]::IsFinite($AcceleratorSourceYOffsetMm)){throw 'AcceleratorSourceYOffsetMm must be finite.'}
if($PulseAcceleratorUntilInitialExit-and-not[string]::IsNullOrWhiteSpace($AcceleratorPulseSchedulePath)){throw 'PulseAcceleratorUntilInitialExit and AcceleratorPulseSchedulePath are mutually exclusive.'}
$acceleratorPulseRequested=[bool]$PulseAcceleratorUntilInitialExit-or-not[string]::IsNullOrWhiteSpace($AcceleratorPulseSchedulePath)
if (($null -eq $Stripe1VoltageV) -ne ($null -eq $Stripe2VoltageV)) { throw 'Stripe1VoltageV and Stripe2VoltageV must be supplied together.' }
if($null-ne$CapacityWorkflowSession-and[string]$CapacityWorkflowSession.status-ne'active'){
  throw 'Inherited capacity workflow session must be active.'
}
foreach($value in @($Stripe1VoltageV,$Stripe2VoltageV)){if($null-ne$value-and([double]::IsNaN($value)-or[double]::IsInfinity($value))){throw 'Stripe voltages must be finite'}}
if(-not[string]::IsNullOrWhiteSpace($AcceleratorFamilyRunPath)){
  throw 'AcceleratorFamilyRunPath is obsolete. Pulsed flights use one manifest-bound standalone operating PA and the in-program field gate.'
}
$geometryRun=(Resolve-Path -LiteralPath $GeometryReviewRunPath).Path
$mirrorRun=(Resolve-Path -LiteralPath $MirrorRunPath).Path
$stripeRun=(Resolve-Path -LiteralPath $StripeRunPath).Path
$acceleratorProviderReceipt=(Resolve-Path -LiteralPath $AcceleratorProviderReceiptPath).Path
$acceleratorRun=Split-Path -Parent (Split-Path -Parent $acceleratorProviderReceipt)
$acceleratorPulseSchedule=if([string]::IsNullOrWhiteSpace($AcceleratorPulseSchedulePath)){$null}else{(Resolve-Path -LiteralPath $AcceleratorPulseSchedulePath).Path}
$mirrorVoltageVariation=if([string]::IsNullOrWhiteSpace($MirrorVoltageVariationPath)){$null}else{(Resolve-Path -LiteralPath $MirrorVoltageVariationPath).Path}
$trajectoryContractInput=if([string]::IsNullOrWhiteSpace($ContractPath)){
  Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\config\simion_candidate_two_zone.json'
}else{(Resolve-Path -LiteralPath $ContractPath).Path}
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
    if($PulseAcceleratorUntilInitialExit){throw 'A frozen bunch interval diagnostic forbids per-particle exit-triggered accelerator pulsing.'}
  }
  if([math]::Abs([double]$bunchSourceContract.common_time_of_birth_us)-gt1e-15){throw 'N>1 managed batch dispatch requires common tob=0.'}
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
if([string]::IsNullOrWhiteSpace($NativeCorridorBankRunPath)){throw 'NativeCorridorBankRunPath is required for the native-only flight runner.'}
if([string]::IsNullOrWhiteSpace($NativeSystemRuntimeBundlePath)){throw 'NativeCorridorBankRunPath requires NativeSystemRuntimeBundlePath.'}
$nativeCorridorRun=(Resolve-Path -LiteralPath $NativeCorridorBankRunPath).Path
if($null-ne$NativeCorridorRuntimeSession-and-not[string]::IsNullOrWhiteSpace($NativeRuntimeCheckpoint)){
  throw 'Supply NativeCorridorRuntimeSession or NativeRuntimeCheckpoint, not both.'
}
$nativeRuntimeCheckpointPath=if([string]::IsNullOrWhiteSpace($NativeRuntimeCheckpoint)){$null}else{(Resolve-Path -LiteralPath $NativeRuntimeCheckpoint).Path}
$nativeRuntimeCheckpointOwner=if($null-eq$nativeRuntimeCheckpointPath){$null}else{Split-Path -Parent (Split-Path -Parent $nativeRuntimeCheckpointPath)}
if($null-ne$NativeCorridorRuntimeSession-and($null-eq$CapacityWorkflowSession-or
   [string]$NativeCorridorRuntimeSession.lease_id-ne[string]$CapacityWorkflowSession.lease_id)){
  throw 'Native runtime reuse requires the matching inherited capacity workflow session and native bank.'
}
if($null-ne$bunchSourceContract-and$null-eq$NativeCorridorRuntimeSession){
  throw 'Native N>1 batch dispatch requires a matching shared native runtime session.'
}
if($RetainGuiWorkbench-and$null-eq$NativeCorridorRuntimeSession){
  throw 'Retained GUI workbench requires the workflow shared native runtime checkpoint; standalone retention would duplicate the complete PA family.'
}
$acceleratorSimion=Join-Path $acceleratorRun 'simion'
$mirrorManifest=Join-Path $mirrorRun 'run_manifest.json'
$stripeManifest=Join-Path $stripeRun 'run_manifest.json'
$acceleratorManifest=Join-Path $acceleratorRun 'run_manifest.json'
$geometryReviewedContract=$trajectoryContractInput
foreach($manifest in @($mirrorManifest,$stripeManifest)){
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $manifest --require-status success
  if($LASTEXITCODE-ne 0){throw "Upstream run manifest is not verified success: $manifest"}
}
$acceleratorConsumerProjectionId='mrtof_accelerator_provider_receipt_v1'
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $acceleratorManifest --require-status success --require-project orthogonal_accelerator --require-mode component_focus_workflow `
  --consumer-projection-id $acceleratorConsumerProjectionId --consumed-output $acceleratorProviderReceipt
if($LASTEXITCODE-ne0){throw 'Provider accelerator workflow manifest is not verified success.'}
$providerAccelerator=Get-Content -Raw -LiteralPath $acceleratorProviderReceipt|ConvertFrom-Json -Depth 40
if([string]$providerAccelerator.role-ne'orthogonal_accelerator_mrtof_runtime_receipt'-or[string]$providerAccelerator.status-ne'published_standalone_response_bank'){
  throw 'AcceleratorProviderReceiptPath is not a published standalone-response provider receipt.'
}
foreach($record in @($providerAccelerator.provider_plan,$providerAccelerator.resolved_campaign)){
  # The manifest projection seals the provider receipt.  This runner consumes
  # only the provider plan and resolved campaign here; the standalone bank is
  # validated once by the shared runtime materializer.
  # paths and sizes without re-reading unrelated upstream evidence or hashing
  # the PA payload again.
  if($null-eq$record-or-not(Test-Path -LiteralPath ([string]$record.path) -PathType Leaf)){throw 'Provider receipt references a missing consumed input.'}
  $item=Get-Item -LiteralPath ([string]$record.path)
  if([int64]$item.Length-ne[int64]$record.bytes){throw 'Provider consumed input byte count differs from its declared receipt.'}
}
$nativeBankManifest=$null;$nativeBankPublicationPath=$null;$nativeBankGeneration=$null;$nativeBankCacheManifest=$null;$nativeBankKey=$null
$nativeSystemRuntimeBundle=$null;$nativeSystemRuntimePaths=$null;$nativeSystemRuntimeRecords=@{}
$nativeBankManifest=Join-Path $nativeCorridorRun 'run_manifest.json'
  $nativeBankPublicationPath=Join-Path $nativeCorridorRun 'results\pa_family_cache_publication.json'
  # The native consumer needs the sealed publication and its small cache
  # manifest.  Verifying every producer payload here would reread the entire
  # PA bank for every child despite the guarded runtime already establishing
  # the family identity once per workflow.
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $nativeBankManifest --require-status success --require-project $projectId --require-mode native_corridor_detached_response_bank `
    --consumer-projection-id mrtof_native_corridor_bank_consumer_v1 --consumed-output $nativeBankPublicationPath
  if($LASTEXITCODE-ne0){throw 'Native corridor bank run is not verified success.'}
  $nativeBankRunRecord=Get-Content -Raw -LiteralPath $nativeBankManifest|ConvertFrom-Json -Depth 40
  $null=Get-ManifestOutputRecord -Path $nativeBankPublicationPath -Manifest $nativeBankRunRecord -Label 'native bank publication'
  $nativeBankPublication=Get-Content -Raw -LiteralPath $nativeBankPublicationPath|ConvertFrom-Json -Depth 40
  if([string]$nativeBankPublication.status-ne'published'-or[string]$nativeBankPublication.action_required-ne'complete'){throw 'Native corridor bank publication is incomplete.'}
  $nativeBankGeneration=[IO.Path]::GetFullPath([string]$nativeBankPublication.generation_directory)
  $nativeBankKey=[string]$nativeBankPublication.cache_key
  $nativeBankCacheManifest=Join-Path $nativeBankGeneration 'cache_manifest.json'
  $nativeBankCache=Get-Content -Raw -LiteralPath $nativeBankCacheManifest|ConvertFrom-Json -Depth 60
  if([string]$nativeBankCache.cache_key-ne$nativeBankKey-or[string]$nativeBankCache.generation_sha256-ne[string]$nativeBankPublication.generation_sha256-or[string]$nativeBankCache.identity.geometry.component_role-ne'mrtof_native_corridor_detached_response_bank'){throw 'Native corridor bank generation identity differs from its publication.'}
  # Resolve the manifest-only system bundle before staging any IOB input.  The
  # identity receipt carries only the sealed bank identity; it never opens PA
  # payloads and is deleted immediately after the CLI has verified the bundle.
  $nativeSystemRuntimeBundle=(Resolve-Path -LiteralPath $NativeSystemRuntimeBundlePath).Path
  $identityPath=Join-Path ([IO.Path]::GetTempPath()) ('mrtof_native_system_identity_'+[guid]::NewGuid().ToString('N')+'.json')
  try{
    [IO.File]::WriteAllText($identityPath,(([ordered]@{schema_version=1;role='mrtof_private_native_corridor_family';status='prepared';run_id=$RunId;cache_key=$nativeBankKey;generation_sha256=[string]$nativeBankCache.generation_sha256;response_refine_performed=$false;controller_refine='solutions={0}';published_native_members_opened=$false}|ConvertTo-Json -Compress)),[Text.UTF8Encoding]::new($false))
    $nativeSystemRuntimePaths=((@(Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_system_runtime','resolve','--native-corridor-runtime-receipt',$identityPath,'--bundle',$nativeSystemRuntimeBundle))-join"`n")|ConvertFrom-Json -Depth 10)
  }finally{
    if(Test-Path -LiteralPath $identityPath){Remove-Item -LiteralPath $identityPath -Force}
  }
  $nativeSystemRuntimeBundleRecord=Get-Content -Raw -LiteralPath $nativeSystemRuntimeBundle|ConvertFrom-Json -Depth 20
  foreach($component in @($nativeSystemRuntimeBundleRecord.components)){
    $role=[string]$component.role
    $declaredPath=if($role-eq'accelerator'){[string]$component.provider_receipt_path}else{[string]$component.pa_path}
    if($role-notin@('global_fallback','accelerator','detector')-or
       -not[string]::Equals([IO.Path]::GetFullPath([string]$nativeSystemRuntimePaths.$role),[IO.Path]::GetFullPath($declaredPath),[StringComparison]::OrdinalIgnoreCase)){
      throw 'Native system runtime resolver returned an unbound component path.'
    }
    $nativeSystemRuntimeRecords[$role]=$component
  }
if($nativeSystemRuntimeRecords.Count-ne3){throw 'Native system runtime bundle lacks a required component identity.'}
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__sim__simion__two-prism-trial-n1'}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
. (Join-Path $repoRoot 'common\multipole\resource_budget_support.ps1')
. (Join-Path $repoRoot 'common\simion\short_pa_path_support.ps1')
. (Join-Path $PSScriptRoot 'native_corridor_runtime_support.ps1')
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'finite_3d_two_prism_voltage_trial' -Software @('SIMION 2020','Python 3.11') `
  -RetentionContractEnabled -RetentionClass compact `
  -CapacityLedgerLifecycleEnabled -AdditionalDirectories @('simion') -UseShortExecutionPath
$runDir=$package.run_dir;$resultDir=$package.result_dir;$logDir=$package.log_dir;$solverDir=Join-Path $runDir 'simion'
$artifactSolverDir=Join-Path ([string]$package.artifact_run_dir) 'simion'
$runConfig=$package.run_config;$summary=$package.summary;$artifactRoot=Join-Path $workspaceRoot 'artifacts'
$terminalized=$false;$failureStage='preflight';$resourceLease=$InheritedHostResourceLease;$ownsHostResourceLease=$null-eq$InheritedHostResourceLease;$hostOutcome='failed';$temporarySolverDir=$null;$temporaryAcceleratorRuntimeSession=$null
$capacitySession=$CapacityWorkflowSession;$ownsCapacitySession=$null-eq$CapacityWorkflowSession
$capacityProtectionRenewalPath=$null
$guiWorkbenchIob=$null;$guiWorkbenchReceipt=$null
$guiWorkbenchOutputs=@()
$batchRuntimeRoot=$null;$batchMergeReceipt=$null
$dispatchRequestPath=$null;$resourceProfilesPath=$null;$runtimeDispatchPlanPath=$null
$batchPlanPath=$null;$batchResourceUsagePath=$null;$resourceProfilePath=$null
$batchWaveResult=$null
$batchContinuationPlan=$null;$batchContinuationPlanPath=$null
$checkpointOutputs=[Collections.Generic.List[string]]::new()
$earlyAberrationReport=$null
$fixedMirrorStripeAuthority=$null;$fixedMirrorStripeAuthorityLocal=$null
$stripeOperatingProvenance=$null
$nativeRuntimeReceiptPath=$null;$nativeBankFrozenInputs=@();$nativeRuntime=$null
$guiWorkbenchDirectory=$null
$retainGuiWorkbenchFiles=$null-ne$NativeCorridorRuntimeSession
try{
  if($ownsCapacitySession){
    $failureStage='capacity_startup'
    $initialProtectedRuns=@($mirrorRun,$stripeRun,$acceleratorRun,$nativeCorridorRun,$nativeBankGeneration,$nativeRuntimeCheckpointOwner)
    $initialProtectedRuns=@($initialProtectedRuns|Where-Object{$null-ne$_}|Select-Object -Unique)
    $capacitySession=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
      -ArtifactRoot $artifactRoot -RunDirectory $package.artifact_run_dir `
      -CommittedNewBytes 26214400 -ProtectedPaths $initialProtectedRuns `
      -ProtectedCacheKeys @() -Owner "mrtof-two-prism-trial:$RunId"
  }
  if($null-ne$nativeRuntimeCheckpointPath){
    $checkpoint=Get-Content -LiteralPath $nativeRuntimeCheckpointPath -Raw|ConvertFrom-Json -AsHashtable
    $NativeCorridorRuntimeSession=[pscustomobject]@{
      lease_id=$capacitySession.lease_id;directory=[IO.Path]::GetFullPath([string]$checkpoint.directory)
      runtime=$null;resident_bytes=[int64]0;owner_run_directory=$nativeRuntimeCheckpointOwner
      owner_run_config=(Join-Path $nativeRuntimeCheckpointOwner 'run_config.json');checkpoint_path=$nativeRuntimeCheckpointPath
    }
  }
  $sourceAnalyzer=[string]$nativeSystemRuntimePaths.global_fallback
  $acceleratorProviderBinding=[string]$nativeSystemRuntimePaths.accelerator
  $sourceAccelerator=$null
  $sourceDetector=[string]$nativeSystemRuntimePaths.detector
  $globalFallbackRecord=$nativeSystemRuntimeRecords['global_fallback']
  $detectorRecord=$nativeSystemRuntimeRecords['detector']
  $stripeOperatingProvenance='native_corridor_frozen_response_bank'
  $globalFallbackAnalyzer=$sourceAnalyzer
  $reviewedContract=$geometryReviewedContract
  $trajectoryContractSource=$trajectoryContractInput
  $selectedContract=$trajectoryContractSource
  $acceleratorGeometryContract=$trajectoryContractSource
  $mirrorSummary=Join-Path $mirrorRun 'summary.json'
  $stripeSummary=Join-Path $stripeRun 'summary.json'
  $acceleratorReceipt=$acceleratorProviderReceipt
  $acceleratorProviderPlan=[string]$providerAccelerator.provider_plan.path
  $acceleratorResolvedCampaign=[string]$providerAccelerator.resolved_campaign.path
  $fixedMirrorStripeLoader=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\fixed_mirror_stripe_operating_point.py'
  $trialTool=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_simion_trial.py'
  $batchTool=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\mrtof_batch_flight.py'
  $programSource=Join-Path $PSScriptRoot 'mrtof_candidate.lua'
  $counterSource=Join-Path $PSScriptRoot 'mirror_cycle_counter.lua'
  $mapSource=Join-Path $PSScriptRoot 'candidate_voltage_map.lua'
  $launcherSource=Join-Path $PSScriptRoot 'run_iob_flight.lua'
  foreach($path in @($sourceAnalyzer,$sourceDetector,$reviewedContract,$selectedContract,$acceleratorGeometryContract,$trajectoryContractSource,$mirrorSummary,$stripeSummary,$acceleratorReceipt,$acceleratorProviderPlan,$acceleratorResolvedCampaign,$fixedMirrorStripeLoader,$trialTool,$batchTool,$programSource,$counterSource,$mapSource,$launcherSource)){
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Required native trial input is missing: $path"}
  }
  $stripeRunConfig=Get-Content -Raw -LiteralPath (Join-Path $stripeRun 'run_config.json')|ConvertFrom-Json -Depth 40
  if([string]$stripeRunConfig.mode-eq'dual_stripe_fixed_grid_native_downstream_seed'){
    $fixedMirrorStripeAuthority=Join-Path $resultDir 'fixed_mirror_stripe_downstream_authority.json'
    Invoke-ProjectPython -Arguments @(
      '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.fixed_mirror_stripe_operating_point',
      '--manifest',$stripeManifest,'--output',$fixedMirrorStripeAuthority
    )|Out-Host
    $authority=Get-Content -Raw -LiteralPath $fixedMirrorStripeAuthority|ConvertFrom-Json -Depth 30
    $mirrorManifestDocument=Get-Content -Raw -LiteralPath $mirrorManifest|ConvertFrom-Json -Depth 30
    $stripeManifestDocument=Get-Content -Raw -LiteralPath $stripeManifest|ConvertFrom-Json -Depth 30
    if($authority.status-ne'success'-or$authority.role-ne'mrtof_fixed_mirror_stripe_downstream_operating_authority'){
      throw 'Fixed mirror/Stripe downstream authority is invalid.'
    }
    if([string]$authority.source_fixed_grid_run_id-ne[string]$mirrorManifestDocument.run_id-or
       [string]$authority.source_stripe_run_id-ne[string]$stripeManifestDocument.run_id){
      throw 'MirrorRunPath or StripeRunPath differs from the fixed mirror/Stripe downstream authority.'
    }
  }
  if($null-ne$nativeRuntimeCheckpointPath){
    Open-NativeCorridorRuntimeCheckpoint -Session $NativeCorridorRuntimeSession `
      -CapacityWorkflowSession $capacitySession -BankGenerationDirectory $nativeBankGeneration `
      -CacheKey $nativeBankKey -GenerationSha256 ([string]$nativeBankCache.generation_sha256) `
      -Python $python -RepoRoot $repoRoot -SimionExe $simion
  }
  $failureStage='capacity_preflight'
  [int64]$requiredBytes=0
  foreach($path in @($reviewedContract,$selectedContract,$acceleratorGeometryContract,$trajectoryContractSource,$mirrorSummary,$stripeSummary,$acceleratorReceipt,$acceleratorProviderPlan,$acceleratorResolvedCampaign,$fixedMirrorStripeLoader,$trialTool,$batchTool,$programSource,$counterSource,$mapSource,$launcherSource)){$requiredBytes+=[int64](Get-Item -LiteralPath $path).Length}
  if($null-ne$fixedMirrorStripeAuthority){$requiredBytes+=[int64](Get-Item -LiteralPath $fixedMirrorStripeAuthority).Length}
  if($null-ne$mirrorVoltageVariation){$requiredBytes+=[int64](Get-Item -LiteralPath $mirrorVoltageVariation).Length}
  if($null-ne$bunchSourceReceipt){$requiredBytes+=[int64](Get-Item -LiteralPath $bunchSourceReceipt).Length}
  $nativeRawRecord=@($nativeBankCache.files|Where-Object{$_.name-eq'mrtof_analyzer_corridor.pa#'})
  if($nativeRawRecord.Count-ne1){throw 'Native corridor bank lacks its unique raw geometry record.'}
  [int64]$nativeFamilyPeakBytes=10*[int64]$nativeRawRecord[0].bytes
  if($null-ne$NativeCorridorRuntimeSession-and $null-ne$NativeCorridorRuntimeSession.PSObject.Properties['resident_bytes'] -and [int64]$NativeCorridorRuntimeSession.resident_bytes-gt0){$nativeFamilyPeakBytes=0}
  # All static components stay in their already verified read-only assets.
  # Only a missing native corridor family consumes new run capacity.
  $requiredBytes+=$nativeFamilyPeakBytes
  $protectedPaths=@($package.artifact_run_dir,$nativeCorridorRun,$nativeBankGeneration)
  $startupProtectedCacheKeys=@($nativeBankKey)
  [int64]$committedNewBytes=[math]::Max($requiredBytes,26214400)
  $failureStage=$(if($ownsCapacitySession){'capacity_scope_update'}else{'capacity_scope_inheritance'})
  [int64]$remainingCommitment=[math]::Max([int64]$capacitySession.committed_new_bytes,$committedNewBytes)
  $sessionUpdate=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession -ProtectedPaths $protectedPaths -ProtectedCacheKeys $startupProtectedCacheKeys -RemainingCommittedNewBytes $remainingCommitment
  $capacitySession=$sessionUpdate.session
  $startup=[pscustomobject]@{schema_version=1;role='artifact_workflow_capacity_session_startup';status='active';ownership=$(if($ownsCapacitySession){'owned__child_releases'}else{'inherited__child_must_not_release'});session=$capacitySession;renewal=$sessionUpdate.renewal;admission_gate=$sessionUpdate.admission_gate}
  $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json';Write-RunJson -Path $startupPath -Depth 14 -Value $startup
  $failureStage='freeze_small_inputs'
  $contract=Copy-RequiredInput $selectedContract (Join-Path $solverDir 'trajectory_contract.json') 'trajectory contract'
  $acceleratorGeometry=Copy-RequiredInput $acceleratorGeometryContract (Join-Path $solverDir 'accelerator_geometry_contract.json') 'accelerator geometry contract'
  $trajectoryContract=Copy-RequiredInput $trajectoryContractSource (Join-Path $solverDir 'trajectory_numerics_contract.json') 'trajectory numerics contract'
  if($null-ne$AcceleratorYAnchorMm){
    if(-not[double]::IsFinite([double]$AcceleratorYAnchorMm)){throw 'AcceleratorYAnchorMm must be finite.'}
    foreach($resolvedContractPath in @($contract,$acceleratorGeometry,$trajectoryContract)){
      $resolvedContract=Get-Content -LiteralPath $resolvedContractPath -Raw|ConvertFrom-Json -AsHashtable
      $resolvedContract.accelerator.focus_y_anchor.project_y_mm=[double]$AcceleratorYAnchorMm
      Write-RunJson -Path $resolvedContractPath -Depth 100 -Value $resolvedContract
    }
  }
  $reviewed=Copy-RequiredInput $reviewedContract (Join-Path $solverDir 'simion_prototype_contract.json') 'reviewed geometry contract'
  $mirrorLocal=Copy-RequiredInput $mirrorSummary (Join-Path $solverDir 'mirror_exact_k_summary.json') 'exact-K mirror summary'
  $stripeLocal=Copy-RequiredInput $stripeSummary (Join-Path $solverDir 'dual_stripe_exact_k_summary.json') 'exact-K Stripe summary'
  $fixedMirrorStripeAuthorityLocal=if($null-eq$fixedMirrorStripeAuthority){$null}else{Copy-RequiredInput $fixedMirrorStripeAuthority (Join-Path $solverDir 'fixed_mirror_stripe_downstream_authority.json') 'fixed mirror/Stripe downstream authority'}
  $mirrorVoltageVariationLocal=if($null-eq$mirrorVoltageVariation){$null}else{Copy-RequiredInput $mirrorVoltageVariation (Join-Path $solverDir 'terminal_time_mirror_voltage_variation.json') 'terminal-time mirror voltage variation'}
  $acceleratorPulseScheduleLocal=if($null-eq$acceleratorPulseSchedule){$null}else{Copy-RequiredInput $acceleratorPulseSchedule (Join-Path $solverDir 'accelerator_pulse_schedule.json') 'accelerator pulse schedule'}
  $acceleratorLocal=Copy-RequiredInput $acceleratorReceipt (Join-Path $solverDir 'accelerator_provider_runtime_receipt.json') 'accelerator provider receipt'
  $acceleratorProviderPlanLocal=Copy-RequiredInput $acceleratorProviderPlan (Join-Path $solverDir 'accelerator_provider_plan.json') 'accelerator provider plan'
  $acceleratorResolvedCampaignLocal=Copy-RequiredInput $acceleratorResolvedCampaign (Join-Path $solverDir 'accelerator_resolved_campaign.json') 'accelerator resolved campaign'
  $bunchSourceLocal=if($null-eq$bunchSourceReceipt){$null}else{Copy-RequiredInput $bunchSourceReceipt (Join-Path $solverDir 'bunch_source_receipt.json') 'bunch source receipt'}
  foreach($pair in @(@($nativeBankManifest,'native_corridor_bank_run_manifest.json'),@($nativeBankPublicationPath,'native_corridor_bank_publication.json'),@($nativeBankCacheManifest,'native_corridor_bank_cache_manifest.json'))){$nativeBankFrozenInputs+=Copy-RequiredInput -Source $pair[0] -Destination (Join-Path $solverDir $pair[1]) -Label $pair[1]}
  foreach($name in @('build_native_corridor_iob.lua','native_corridor_priority_contract.lua','native_corridor_runtime_support.ps1')){Copy-RequiredInput -Source (Join-Path $PSScriptRoot $name) -Destination (Join-Path $solverDir $name) -Label $name|Out-Null}
  foreach($name in @('native_fast_adjust_runtime_support.ps1','assemble_native_fast_adjust_family.lua')){Copy-RequiredInput -Source (Join-Path $repoRoot 'common\simion' $name) -Destination (Join-Path $solverDir $name) -Label $name|Out-Null}
  Copy-RequiredInput -Source (Join-Path $repoRoot 'common\simion\assets\iob_instance_seeds\4_instance_seed.iob') -Destination (Join-Path $solverDir '4_instance_seed.iob') -Label 'native four-instance seed'|Out-Null
  foreach($pair in @(@($programSource,'mrtof_three_component_candidate.lua'),@($counterSource,'mrtof_three_component_candidate.mirror_cycle_counter.lua'),@($mapSource,'mrtof_three_component_candidate.voltage_map.lua'),@($launcherSource,'run_iob_flight.lua'),@($trialTool,'two_prism_simion_trial.py'),@($batchTool,'mrtof_batch_flight.py'))){Copy-RequiredInput $pair[0] (Join-Path $solverDir $pair[1]) $pair[1]|Out-Null}
  $fly2Input=Join-Path $solverDir 'downstream_trial_source.input.fly2'
  $sidecar=Join-Path $solverDir 'mrtof_three_component_candidate.operating_point.lua'
  $trialReceipt=Join-Path $resultDir 'two_prism_trial_materialization.json'
  $failureStage='materialize_trial'
  $acceleratorInstance='3'
  $materializeArguments=@('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial','materialize',
    '--contract',$contract,'--accelerator-geometry-contract',$acceleratorGeometry,'--trajectory-contract',$trajectoryContract,'--reviewed-contract',$reviewed,'--mirror-summary',$mirrorLocal,'--stripe-summary',$stripeLocal,
    '--accelerator-receipt',$acceleratorLocal,'--prism-1-v',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$Prism1VoltageV)),
    '--accelerator-provider-plan',$acceleratorProviderPlanLocal,'--accelerator-resolved-campaign',$acceleratorResolvedCampaignLocal,
    '--prism-2-v',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$Prism2VoltageV)),
    '--workbench-accelerator-instance',$acceleratorInstance,
    '--fly2',$fly2Input,'--sidecar',$sidecar,'--receipt',$trialReceipt)
  # A frozen N>1 source stores positions in the resolved accelerator frame,
  # including its own centre.  The single-ion injection offset must not be
  # applied a second time to a frozen cohort.
  if($null-eq$bunchSourceLocal){$materializeArguments+=@('--source-y-offset-mm',(Format-InvariantNumber $AcceleratorSourceYOffsetMm))}
  if($null-ne$Stripe1VoltageV){
    $materializeArguments+=@('--stripe-1-v',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$Stripe1VoltageV)),
      '--stripe-2-v',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$Stripe2VoltageV)))
  }
  if($null-ne$fixedMirrorStripeAuthorityLocal){$materializeArguments+=@('--fixed-mirror-stripe-authority',$fixedMirrorStripeAuthorityLocal)}
  if($null-ne$mirrorVoltageVariationLocal){$materializeArguments+=@('--mirror-voltage-variation',$mirrorVoltageVariationLocal)}
  if($null-ne$bunchSourceLocal){$materializeArguments+=@('--bunch-source-receipt',$bunchSourceLocal)}
  if($bunchSelectionRequested){$materializeArguments+=@('--bunch-particle-id-min',([string]$BunchParticleIdMin),'--bunch-particle-id-max',([string]$BunchParticleIdMax))}
  if($TrajectoryStepScale-ne1){$materializeArguments+=@('--trajectory-step-scale',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$TrajectoryStepScale)))}
  if($PulseAcceleratorUntilInitialExit){$materializeArguments+='--pulse-accelerator-until-initial-exit'}
  if($AcceleratorSafeExitOnly){$materializeArguments+='--accelerator-safe-exit-only'}
  if($null-ne$acceleratorPulseScheduleLocal){$materializeArguments+=@('--accelerator-pulse-schedule',$acceleratorPulseScheduleLocal)}
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
  # IOB/Fly2/Lua companions are small reproducibility inputs, so every shared-
  # runtime workflow keeps them even under compact retention.  Static PA assets
  # are referenced through workflow-lifetime read guards, not projected into
  # each trial. A retained Workbench stores absolute paths and therefore must
  # be built directly below its governed run.
  $temporarySolverDir=if($retainGuiWorkbenchFiles){
    Join-Path $artifactSolverDir 'gui_workbench'
  }else{
    Join-Path ([IO.Path]::GetTempPath()) ('mrtof_downstream_'+[guid]::NewGuid().ToString('N'))
  }
  if($retainGuiWorkbenchFiles){$guiWorkbenchDirectory=$temporarySolverDir}
  New-Item -ItemType Directory -Path $temporarySolverDir|Out-Null
  # The seed IOB cannot be opened unless its four blank PA companions share
  # its directory.  They are structural placeholders only: copy one private
  # template and create three same-volume aliases instead of transporting or
  # hashing four identical payloads.
  $privateIobSeed=Join-Path $temporarySolverDir '4_instance_seed.iob'
  Copy-Item -LiteralPath (Join-Path $solverDir '4_instance_seed.iob') -Destination $privateIobSeed
  $privateSeedPlaceholder=Join-Path $temporarySolverDir 'iob_seed_placeholder_01.pa0'
  Copy-Item -LiteralPath (Join-Path $repoRoot 'common\simion\assets\iob_instance_seeds\iob_seed_placeholder_01.pa0') -Destination $privateSeedPlaceholder
  foreach($seedIndex in 2..4){
    $seedAlias=Join-Path $temporarySolverDir ('iob_seed_placeholder_{0:D2}.pa0'-f$seedIndex)
    $null=New-Item -ItemType HardLink -Path $seedAlias -Target $privateSeedPlaceholder
  }
  $temporaryAnalyzer=$globalFallbackAnalyzer
  $temporaryIob=Join-Path $temporarySolverDir 'mrtof_three_component_candidate.iob'
  $posePath=Join-Path $resultDir 'resolved_iob_pose.json'
  $poseCode="import json,sys; from pathlib import Path; from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import load_contract,mirror_power_supply_limits; from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_system_geometry import resolve_accelerator_iob_origin,resolve_static_iob_origins; reviewed=Path(sys.argv[1]); receipt=json.loads(Path(sys.argv[2]).read_text(encoding='utf-8')); active=load_contract(Path(sys.argv[3])); policy=active['accelerator']['detector_return_path']; limits=mirror_power_supply_limits(active); static=resolve_static_iob_origins(reviewed,inherited_detector_return_path=policy,inherited_dual_stripe_topology_contract=active,inherited_mirror_power_supply_limits_v=limits); plan=json.loads(Path(sys.argv[5]).read_text(encoding='utf-8')); domain=plan['numerical_domain']; origin=resolve_accelerator_iob_origin(active,plan); Path(sys.argv[4]).write_text(json.dumps({'origins_mm':{'analyzer':static['analyzer'],'accelerator':origin,'detector':static['detector']},'mesh_mm_per_gu':{'analyzer':active['simion']['component_mesh_mm_per_gu']['analyzer'],'accelerator':domain['mesh_mm_per_gu'],'detector':active['simion']['component_mesh_mm_per_gu']['detector']},'analyzer_geometry_authority':'reviewed_analyzer_contract','accelerator_geometry_authority':'oa_provider_plan__mr_configurable_clearance_gated_y_pose','detector_return_policy_authority':'current_trajectory_contract'},indent=2)+'\n',encoding='utf-8')"
  Invoke-ProjectPython -Arguments @('-c',$poseCode,$reviewed,$acceleratorLocal,$trajectoryContract,$posePath,$acceleratorProviderPlanLocal)
  $pose=Get-Content -LiteralPath $posePath -Raw -Encoding UTF8|ConvertFrom-Json
  # The native-system bundle already seals this source identity.  The guarded
  # first-use check below verifies it once for the enclosing workflow process;
  # do not reread the multi-GB PA merely to write this receipt.
  $voltageSourceHash=[string]$globalFallbackRecord.sha256
  $failureStage='prepare_native_corridor'
  if($ownsHostResourceLease){
    $resourceLease=Enter-HostResourceStage -Role SIMION -Stage 'mrtof_prepare' -Budget (Get-HostResourceBudget -Role SIMION -Stage 'mrtof_prepare') -RunId $RunId
  }
  $temporaryAnalyzerHash=$voltageSourceHash
  $voltageReceipt=Join-Path $resultDir 'native_corridor_voltage_binding_receipt.json'
  Write-RunJson -Path $voltageReceipt -Depth 14 -Value ([ordered]@{schema_version=1;role='mrtof_native_corridor_voltage_binding';status='success';method='native_corridor_private_fast_adjust_family';source_pa=$globalFallbackAnalyzer;source_sha256=$voltageSourceHash;temporary_output_sha256=$temporaryAnalyzerHash;electrode_voltages_v=@($trial.analyzer_electrode_voltages_v);refine_performed=$false;temporary_output_retained=$false})
  $failureStage='renew_native_corridor_protection'
  $cacheScopeUpdate=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession -ProtectedCacheKeys @($nativeBankKey) -ProtectedPaths @($nativeBankGeneration)
  $capacitySession=$cacheScopeUpdate.session
  $capacityProtectionRenewalPath=Join-Path $resultDir 'native_corridor_protection_renewal.json'
  Write-RunJson -Path $capacityProtectionRenewalPath -Depth 20 -Value ([ordered]@{schema_version=1;role='mrtof_native_corridor_protection_renewal';status='success';lease_id=$capacitySession.lease_id;lease_owner=$capacitySession.owner;lease_ttl_seconds=$capacitySession.lease_ttl_seconds;cache_key=$nativeBankKey;cache_keys=@($nativeBankKey);generation_directory=$nativeBankGeneration;renewal=$cacheScopeUpdate.renewal})
  # This builder saves the Workbench before Fast Adjust, and the flight entry
  # never saves it.  The static fallback and detector therefore remain clean
  # inputs.  Verify and hold each source once per enclosing workflow process;
  # nested N=1/TE1 trials reuse the same no-write/no-delete guards without
  # copying or rehashing either payload.
  $failureStage='protect_static_iob_pa_inputs'
  $null=Protect-ImmutablePaSource -Source $globalFallbackAnalyzer `
    -ExpectedBytes ([int64]$globalFallbackRecord.bytes) -ExpectedSha256 ([string]$globalFallbackRecord.sha256)
  $null=Protect-ImmutablePaSource -Source $sourceDetector `
    -ExpectedBytes ([int64]$detectorRecord.bytes) -ExpectedSha256 ([string]$detectorRecord.sha256)
  $iobAnalyzerInput=$globalFallbackAnalyzer
  # Flight initialization receives the private native Fast Adjust family below.
  # Its short execution alias is process-local; retained GUI workbenches bind
  # the same checkpoint's persistent controller path instead.
  $iobAcceleratorInput=$null
  $iobDetectorInput=$sourceDetector
  $failureStage='build_temporary_iob'
  $iobProgramPath=Join-Path $solverDir 'mrtof_three_component_candidate.lua'
  $iobFly2Path=$fly2Input
  $failureStage='prepare_native_corridor_runtime_family'
    if($null-ne$NativeCorridorRuntimeSession){
      $nativeRuntime=Get-NativeCorridorRuntimeFamily -Session $NativeCorridorRuntimeSession `
        -CapacityWorkflowSession $capacitySession -BankGenerationDirectory $nativeBankGeneration `
        -CacheKey $nativeBankKey -GenerationSha256 ([string]$nativeBankCache.generation_sha256) `
        -Python $python -RepoRoot $repoRoot -SimionExe $simion -ResourceLease $resourceLease -RunId $RunId
    }else{
    $nativeRuntime=New-NativeCorridorRuntimeFamily -BankGenerationDirectory $nativeBankGeneration `
      -CacheKey $nativeBankKey -GenerationSha256 ([string]$nativeBankCache.generation_sha256) `
      -DestinationDirectory (Join-Path $temporarySolverDir 'native_corridor') -Python $python -RepoRoot $repoRoot `
      -SimionExe $simion -ResourceLease $resourceLease -RunId $RunId
    }
    $resourceLease=$nativeRuntime.resource_lease
    # The receipt binds the durable checkpoint controller.  Do not embed the
    # disposable execution junction in an IOB that outlives materialization;
    # SIMION opens pa1..pa8 lazily during Fast Adjust.
    $nativeControllerForIob=[IO.Path]::GetFullPath([string]$nativeRuntime.receipt.controller_path)
    if(-not(Test-Path -LiteralPath $nativeControllerForIob -PathType Leaf)){
      throw 'Native runtime receipt controller is missing.'
    }
    $nativeRuntimeReceiptPath=Join-Path $resultDir 'native_corridor_runtime_family.json'
    Write-RunJson -Path $nativeRuntimeReceiptPath -Depth 40 -Value $nativeRuntime.receipt
    $failureStage='prepare_accelerator_runtime_family'
    $acceleratorSession=$NativeCorridorRuntimeSession
    if($null-eq$acceleratorSession){$temporaryAcceleratorRuntimeSession=[pscustomobject]@{};$acceleratorSession=$temporaryAcceleratorRuntimeSession}
    $acceleratorRuntime=Get-NativeAcceleratorRuntimeFamily -Session $acceleratorSession `
      -ProviderReceiptPath $acceleratorProviderBinding -Python $python -RepoRoot $repoRoot `
      -SimionExe $simion -ResourceLease $resourceLease -RunId $RunId
    $resourceLease=$acceleratorRuntime.resource_lease;$sourceAccelerator=[string]$acceleratorRuntime.controller_path
    $persistentAcceleratorController=if($null-ne$acceleratorRuntime.PSObject.Properties['persistent_controller_path']){[string]$acceleratorRuntime.persistent_controller_path}else{$sourceAccelerator}
    $iobAcceleratorInput=$sourceAccelerator
    $nativeOrigins=@(@($pose.origins_mm.analyzer),@($nativeBankCache.identity.grid_phase.origin_mm),@($pose.origins_mm.accelerator),@($pose.origins_mm.detector))
    $nativeOriginArguments=@();foreach($origin in $nativeOrigins){foreach($value in $origin){$nativeOriginArguments+=Format-InvariantNumber ([double]$value)}}
    $buildArguments=@('--nogui','--noprompt','lua',(Join-Path $solverDir 'build_native_corridor_iob.lua'),'--',
      $privateIobSeed,$iobAnalyzerInput,$nativeControllerForIob,$iobAcceleratorInput,$iobDetectorInput,
      $temporaryIob,$iobProgramPath,$iobFly2Path,$sidecar,(Join-Path $solverDir 'mrtof_three_component_candidate.voltage_map.lua'),
      (Join-Path $solverDir 'native_corridor_priority_contract.lua'))+$nativeOriginArguments
    $failureStage='build_temporary_iob'
  if(-not$isBunchFlight){
    Invoke-SimionStage -Stage 'build_temporary_iob' -Arguments $buildArguments -ResourceLease $resourceLease -RegisterHostProcess $ownsHostResourceLease
    $temporaryFly2=[IO.Path]::ChangeExtension($temporaryIob,'.fly2')
    if(-not(Test-RunFilesIdentical -Left $fly2Input -Right $temporaryFly2)){throw 'IOB companion Fly2 differs from the frozen downstream-trial source'}
    $failureStage='native_two_prism_flight'
    if($ownsHostResourceLease){
      $resourceLease=Update-HostResourceStage -Lease $resourceLease -Stage 'mrtof_flight' `
        -Budget (Get-HostResourceBudget -Role SIMION -Stage 'mrtof_flight') -RetainedMemoryBytes 0
    }
    Invoke-SimionStage -Stage 'native_two_prism_flight' -Arguments @('--nogui','--noprompt','lua',(Join-Path $solverDir 'run_iob_flight.lua'),$temporaryIob) -ResourceLease $resourceLease -RegisterHostProcess $ownsHostResourceLease
  }else{
    # SIMION's supported parallel Fly'm pattern is multiple independent
    # processes using one IOB and distinct particle files.  Build the common
    # read-only workbench once; the repository scheduler owns process count.
    Invoke-SimionStage -Stage 'build_temporary_iob' -Arguments $buildArguments -ResourceLease $resourceLease -RegisterHostProcess $ownsHostResourceLease
    $temporaryFly2=[IO.Path]::ChangeExtension($temporaryIob,'.fly2')
    if(-not(Test-RunFilesIdentical -Left $fly2Input -Right $temporaryFly2)){throw 'Shared IOB companion Fly2 differs from the frozen bunch source.'}
    $failureStage='plan_bunch_dispatch'
    $dispatchRequestPath=Join-Path $resultDir 'simion_dispatch_request.json'
    $resourceProfilesPath=Join-Path $resultDir 'simion_resource_profiles.json'
    $runtimeDispatchPlanPath=Join-Path $resultDir 'simion_repository_dispatch_plan.json'
    $batchPlanPath=Join-Path $resultDir 'simion_execution_batch_plan.json'
    $batchResourceUsagePath=Join-Path $logDir 'simion_batch_resource_usage.json'
    Invoke-ProjectPython -Arguments @('-m','common.simion.resource_profile','discover','--runs-root',(Join-Path $artifactRoot "projects\$projectId\runs"),'--output',$resourceProfilesPath)
    Write-RunJson -Path $dispatchRequestPath -Depth 10 -Value ([ordered]@{
      solver='SIMION';field_kind='electrostatic';particle_count=[int]$trial.source_particle_count;independent_particles=$true
      frontend_grid_profile_id=('mrtof_native_corridor_four_instance__bank_'+[string]$nativeBankCache.generation_sha256)
      oatof_numerical_profile_id=$null
      trajectory_quality_profile_id=[string]$trial.trajectory_profile.profile_id
      time_integration_profile_id='mrtof_candidate_adaptive_time_step'
      frontend_cell_mm_xyz=@($trial.nonaccelerator_mesh_mm_per_gu)
      accelerator_overlay_cell_mm_xyz=$null;reflectron_cell_mm=$null
      trajectory_quality=[double]$trial.trajectory_profile.trajectory_quality;rf_steps_per_period=$null
      accelerator_field_profile_id='mrtof_two_zone_standalone_operating_pa'
      frontend_pa0_sha256=[string]$nativeBankCache.generation_sha256
      accelerator_overlay_generation_sha256=[string]$providerAccelerator.pa_family.generation_sha256
      reflectron_pa0_sha256=[string]$nativeSystemRuntimeRecords['detector'].sha256
      case_input_sha256=[string]$trial.operating_point_lua_sha256
      workload_topology_id='mrtof_native_corridor_four_instance_two_prism_full_flight'
      field_loading_policy_id='shared_native_corridor_runtime__four_instances__no_refine'
    })
    Invoke-ProjectPython -Arguments @('-m','common.simion.resource_scheduler','--request',$dispatchRequestPath,'--profiles',$resourceProfilesPath,'--output',$runtimeDispatchPlanPath)
    Invoke-ProjectPython -Arguments @('-m','common.simion.particle_batching','--from-dispatch-plan',$runtimeDispatchPlanPath,'--output',$batchPlanPath)
    # Publish the immutable N>1 identity before any worker starts.  The common
    # continuation protocol then needs only the canonical batch plan and
    # naturally completed logs; it never revalidates or transports PA payloads.
    $checkpointConfig=Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    $checkpointInputs=[ordered]@{
      accelerator_provider_plan=$acceleratorProviderPlanLocal
      accelerator_resolved_campaign=$acceleratorResolvedCampaignLocal
      trial_materialization=$trialReceipt
      resolved_iob_pose=$posePath
      operating_point_lua=$sidecar
      frozen_source_fly2=$fly2Input
      iob_builder=Join-Path $solverDir 'build_native_corridor_iob.lua'
      iob_seed=Join-Path $solverDir '4_instance_seed.iob'
      native_corridor_priority_contract=Join-Path $solverDir 'native_corridor_priority_contract.lua'
      flight_program=Join-Path $solverDir 'mrtof_three_component_candidate.lua'
      mirror_cycle_counter=Join-Path $solverDir 'mrtof_three_component_candidate.mirror_cycle_counter.lua'
      voltage_map=Join-Path $solverDir 'mrtof_three_component_candidate.voltage_map.lua'
      flight_launcher=Join-Path $solverDir 'run_iob_flight.lua'
      native_corridor_bank_cache_manifest=Join-Path $solverDir 'native_corridor_bank_cache_manifest.json'
      native_system_runtime_bundle=$nativeSystemRuntimeBundle
    }
    $checkpointConfig.inputs=$checkpointInputs
    $checkpointConfig.parameters.execution_mode='mrtof_native_corridor_bunch'
    $checkpointConfig.parameters.particle_count=[int]$trial.source_particle_count
    $checkpointConfig.parameters.launched_particle_count=[int]$trial.source_particle_count
    $checkpointConfig.parameters.prism_voltages_v=@($Prism1VoltageV,$Prism2VoltageV)
    $checkpointConfig.parameters.stripe_biases_v=@($trial.stripe_biases_v)
    $checkpointConfig.parameters.accelerator_y_anchor_mm=if($null-eq$AcceleratorYAnchorMm){$null}else{[double]$AcceleratorYAnchorMm}
    $checkpointConfig.parameters.trajectory_profile=$trial.trajectory_profile
    Write-RunJson -Path $runConfig -Value $checkpointConfig

    if(-not[string]::IsNullOrWhiteSpace($BatchContinuationRunPath)){
      $continuationRoot=Join-Path $package.input_dir 'mrtof_batch_continuation'
      Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_continuation',
        '--predecessor-run-dir',(Resolve-Path -LiteralPath $BatchContinuationRunPath).Path,
        '--current-run-config',$runConfig,'--output-dir',$continuationRoot)
      $batchContinuationPlanPath=Join-Path $continuationRoot 'simion_batch_continuation_plan.json'
      $batchContinuationPlan=Get-Content -Raw -LiteralPath $batchContinuationPlanPath|ConvertFrom-Json
      if([int]$batchContinuationPlan.completed_particle_count+[int]$batchContinuationPlan.replay_particle_count-ne[int]$trial.source_particle_count){
        throw 'MR-TOF continuation plan differs from the frozen cohort.'
      }
      $batchPlanPath=[string]$batchContinuationPlan.batch_plan.path
      $checkpointConfig.inputs.simion_batch_continuation_plan=$batchContinuationPlanPath
      $checkpointConfig.inputs.simion_execution_batch_plan=$batchPlanPath
      $checkpointConfig.parameters.continuation_completed_particle_count=[int]$batchContinuationPlan.completed_particle_count
      $checkpointConfig.parameters.continuation_replay_particle_count=[int]$batchContinuationPlan.replay_particle_count
    }else{
      $checkpointConfig.inputs.simion_execution_batch_plan=$batchPlanPath
    }
    Write-RunJson -Path $runConfig -Value $checkpointConfig
    $batchRuntimeRoot=Join-Path ([IO.Path]::GetTempPath()) ('mrtof_batch_runtime_'+[guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $batchRuntimeRoot|Out-Null
    $batchRecords=@{}
    $earlyAberrationReport=Join-Path $resultDir 'controlled_aberration_first_batch.json'
    function New-MrtofBatchRecord {
      param([Parameter(Mandatory)]$PlannedBatch)
      $batchIndex=[int]$PlannedBatch.index;$batchCount=[int]$PlannedBatch.count
      $sourceParticleIdMin=if($bunchSelectionRequested){$BunchParticleIdMin}else{1}
      $batchParticleIdMin=$sourceParticleIdMin+[int]$PlannedBatch.particle_id_min-1
      $batchParticleIdMax=$sourceParticleIdMin+[int]$PlannedBatch.particle_id_max-1
      $batchOffset=$batchParticleIdMin-1
      $batchDir=Join-Path $batchRuntimeRoot ('batch_{0:D2}'-f$batchIndex)
      New-Item -ItemType Directory -Path $batchDir|Out-Null
      $batchFly2=Join-Path $batchDir 'mrtof_batch_source.fly2'
      # PowerShell includes every uncaptured pipeline value in a function's
      # return value.  Keep diagnostics visible without allowing them to turn
      # the structured batch record below into a heterogeneous array.
      Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight','materialize','--receipt',$bunchSourceLocal,'--particle-id-min',([string]$batchParticleIdMin),'--particle-id-max',([string]$batchParticleIdMax),'--output',$batchFly2) | Out-Host
      $batchIob=$temporaryIob
      return [pscustomobject]@{
        index=$batchIndex;count=$batchCount;offset=$batchOffset;runtime_dir=$batchDir;iob=$batchIob
        source_fly2=$batchFly2
        stdout=Join-Path $logDir ('native_two_prism_flight__batch{0:D2}.log'-f$batchIndex)
        stderr=Join-Path $logDir ('native_two_prism_flight__batch{0:D2}.stderr.log'-f$batchIndex)
        scheduler_batch=$PlannedBatch
      }
    }
    function Get-MrtofBatchProcessSpecification {
      param([Parameter(Mandatory)]$Record)
      return [pscustomobject]@{
        name=('mrtof_simion_batch_{0:D2}'-f$Record.index);scheduler_batch=$Record.scheduler_batch
        file_path=$simion;working_directory=$Record.runtime_dir;stdout=$Record.stdout;stderr=$Record.stderr;environment=@{}
        argument_list=[string[]]@('--nogui','--noprompt','lua',(Join-Path $solverDir 'run_iob_flight.lua'),$Record.iob,$Record.source_fly2)
      }
    }
    function Publish-MrtofFirstBatchAberration {
      param([Parameter(Mandatory)]$Record)
      $focusPair=$bunchSourceContract.PSObject.Properties['controlled_focus_pair']
      $energyPair=$bunchSourceContract.PSObject.Properties['controlled_slow_energy_pair']
      $transversePair=$bunchSourceContract.PSObject.Properties['controlled_transverse_x_pair']
      if($null-eq$bunchSourceContract-or$bunchSelectionRequested-or[int]$Record.scheduler_batch.particle_id_min-ne1-or
         [int]$Record.count-lt7-or$null-eq$focusPair-or$null-eq$focusPair.Value-or
         $null-eq$energyPair-or$null-eq$energyPair.Value-or
         $null-eq$transversePair-or$null-eq$transversePair.Value-or
         (Test-Path -LiteralPath $earlyAberrationReport -PathType Leaf)){return}
      Invoke-ProjectPython -Arguments @(
        '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.source_z_energy_timing_diagnostic',
        '--first-batch-log',$Record.stdout,'--source-receipt',$bunchSourceLocal,
        '--output',$earlyAberrationReport
      )
      [void]$checkpointOutputs.Add($earlyAberrationReport)
      Write-Host "MRTOF_CONTROLLED_ABERRATION_FIRST_BATCH=PASS PATH=$earlyAberrationReport"
    }
    $initialBatchPlan=Get-Content -Raw -LiteralPath $batchPlanPath|ConvertFrom-Json
    foreach($planned in @($initialBatchPlan.batches)){$batchRecords[[int]$planned.index]=New-MrtofBatchRecord -PlannedBatch $planned}
    if($null-ne$batchContinuationPlan){
      foreach($continuationBatch in @($batchContinuationPlan.batches)){
        if([int]$continuationBatch.completed_particle_count-eq0){continue}
        if([int]$continuationBatch.completed_particle_count-ne[int]$continuationBatch.count-or$null-eq$continuationBatch.imported_completed_trace){
          throw 'MR-TOF continuation accepts only whole completed batches.'
        }
        $batchRecords[[int]$continuationBatch.index].stdout=[string]$continuationBatch.imported_completed_trace.path
      }
    }
    foreach($path in @($dispatchRequestPath,$resourceProfilesPath,$runtimeDispatchPlanPath,$batchPlanPath,$batchContinuationPlanPath)){
      if($null-ne$path-and(Test-Path -LiteralPath $path -PathType Leaf)-and-not$checkpointOutputs.Contains($path)){[void]$checkpointOutputs.Add($path)}
    }
    if($null-ne$batchContinuationPlan){
      foreach($entry in @($batchContinuationPlan.batches)){
        if($null-ne$entry.imported_completed_trace){[void]$checkpointOutputs.Add([string]$entry.imported_completed_trace.path)}
      }
    }
    Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig `
      -Manifest (Join-Path $runDir 'run_manifest.json') -Status checkpoint `
      -Software @('SIMION 2020','Python 3.11') -Outputs @($checkpointOutputs)|Out-Null
    if($ownsHostResourceLease){
      $resourceLease=Update-HostResourceStage -Lease $resourceLease -Stage 'mrtof_flight' `
        -Budget (Get-HostResourceBudget -Role SIMION -Stage 'mrtof_flight') -RetainedMemoryBytes 0
    }
    $dispatch=Get-Content -Raw -LiteralPath $runtimeDispatchPlanPath|ConvertFrom-Json
    $resourceIdentityWasUnknown=[string]$dispatch.estimation.kind-eq'formal_first_batch_observation'
    $existingRecords=@()
    $replayBatchIndexes=@(
      if($null-eq$batchContinuationPlan){$initialBatchPlan.batches|ForEach-Object{[int]$_.index}}
      else{$batchContinuationPlan.batches|Where-Object{[int]$_.replay_particle_count-gt0}|ForEach-Object{[int]$_.index}}
    )
    $formalBatchIndex=$null
    if([string]$dispatch.estimation.kind-eq'formal_first_batch_observation'-and$replayBatchIndexes.Count-gt0){
      $formalBatchIndex=[int]$replayBatchIndexes[0]
      $firstSpec=Get-MrtofBatchProcessSpecification -Record $batchRecords[$formalBatchIndex]
      $formal=Start-ObservedFormalProcess -DispatchPlanPath $runtimeDispatchPlanPath -ProcessSpecification $firstSpec
      $firstBatchCompleted=[bool]$formal.process_record.completed
      if($formal.resource_budget_exceeded-or($firstBatchCompleted-and(-not$formal.completed_naturally-or[int]$formal.exit_code-ne0))){throw 'MR-TOF formal first batch did not complete or continue safely.'}
      $adaptiveArguments=@('-m','common.simion.resource_scheduler','--request',$dispatchRequestPath,'--profiles',$resourceProfilesPath,'--output',$runtimeDispatchPlanPath,'--observed-formal-peak-bytes',([string]$formal.observed_peak_process_tree_working_set_bytes),'--observed-formal-cpu-percent',([string]$formal.observed_process_cpu_percent),'--observed-background-cpu-percent',([string]$formal.observed_background_cpu_percent),'--available-memory-bytes',([string]$formal.available_memory_bytes),'--total-physical-memory-bytes',([string]$formal.total_physical_memory_bytes))
      if($firstBatchCompleted){$adaptiveArguments+='--first-batch-completed'}
      Invoke-ProjectPython -Arguments $adaptiveArguments
      $existingRecords=@($formal.process_record)
      if($firstBatchCompleted){Publish-MrtofFirstBatchAberration -Record $batchRecords[$formalBatchIndex]}
      if($null-eq$batchContinuationPlan){
        Invoke-ProjectPython -Arguments @('-m','common.simion.particle_batching','--from-dispatch-plan',$runtimeDispatchPlanPath,'--output',$batchPlanPath)
        $replanned=Get-Content -Raw -LiteralPath $batchPlanPath|ConvertFrom-Json
        foreach($planned in @($replanned.batches)){
          $plannedIndex=[int]$planned.index
          if($batchRecords.ContainsKey($plannedIndex)){
            $existing=$batchRecords[$plannedIndex]
            $plannedGlobalOffset=[int]$planned.simion_particle_id_offset
            if($bunchSelectionRequested){$plannedGlobalOffset+=$BunchParticleIdMin-1}
            if([int]$existing.count-ne[int]$planned.count-or[int]$existing.offset-ne$plannedGlobalOffset){throw 'Formal-first replan changed an already completed batch interval.'}
          }else{
            $batchRecords[$plannedIndex]=New-MrtofBatchRecord -PlannedBatch $planned
          }
        }
        # The formal observation starts from a one-batch provisional plan.
        # Once the repository scheduler expands it, every new interval must
        # enter this same wave; continuation plans already carry their own
        # frozen replay set and therefore do not use this branch.
        $replayBatchIndexes=@($replanned.batches|ForEach-Object{[int]$_.index})
      }
    }
    $finalBatchPlan=Get-Content -Raw -LiteralPath $batchPlanPath|ConvertFrom-Json
    $checkpointConfig=Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    $checkpointConfig.inputs.simion_execution_batch_plan=$batchPlanPath
    Write-RunJson -Path $runConfig -Value $checkpointConfig
    $checkpointAction={
      param($completedRecord)
      foreach($path in @([string]$completedRecord.specification.stdout,[string]$completedRecord.specification.stderr)){
        if(-not[string]::IsNullOrWhiteSpace($path)-and(Test-Path -LiteralPath $path -PathType Leaf)-and-not$checkpointOutputs.Contains($path)){[void]$checkpointOutputs.Add($path)}
      }
      $completedBatchIndex=[int]$completedRecord.specification.scheduler_batch.index
      if($batchRecords.ContainsKey($completedBatchIndex)){
        Publish-MrtofFirstBatchAberration -Record $batchRecords[$completedBatchIndex]
      }
      Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig `
        -Manifest (Join-Path $runDir 'run_manifest.json') -Status checkpoint `
        -Software @('SIMION 2020','Python 3.11') -Outputs @($checkpointOutputs)|Out-Null
    }
    Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig `
      -Manifest (Join-Path $runDir 'run_manifest.json') -Status checkpoint `
      -Software @('SIMION 2020','Python 3.11') -Outputs @($checkpointOutputs)|Out-Null
    $pendingSpecs=@($finalBatchPlan.batches|Where-Object{
      $index=[int]$_.index
      $replayBatchIndexes-contains$index-and($null-eq$formalBatchIndex-or$index-ne$formalBatchIndex)
    }|ForEach-Object{Get-MrtofBatchProcessSpecification -Record $batchRecords[[int]$_.index]})
    if($pendingSpecs.Count-eq0-and$existingRecords.Count-eq0){
      $batchWaveResult=[pscustomobject]@{resource_budget_exceeded=$false;processes=@()}
    }else{
      $batchWaveResult=Invoke-ResourceBudgetedProcesses -DispatchPlanPath $runtimeDispatchPlanPath -RunDir $runDir -UsagePath $batchResourceUsagePath -ProcessSpecifications $pendingSpecs -ExistingProcessRecords $existingRecords -OnProcessCompleted $checkpointAction
    }
    if($batchWaveResult.resource_budget_exceeded-or@($batchWaveResult.processes|Where-Object{[int]$_.exit_code-ne0}).Count-ne0){throw 'MR-TOF SIMION batch wave failed or exceeded the repository resource budget.'}
    if(Test-Path -LiteralPath $batchResourceUsagePath -PathType Leaf){Complete-ResourceUsage -RunDir $runDir -UsagePath $batchResourceUsagePath|Out-Null}
    if($resourceIdentityWasUnknown-and(Test-Path -LiteralPath $batchResourceUsagePath -PathType Leaf)){
      $resourceProfilePath=Join-Path $resultDir 'simion_resource_profile.json'
      Invoke-ProjectPython -Arguments @('-m','common.simion.resource_profile','publish','--run-id',$RunId,'--resource-usage',$batchResourceUsagePath,'--resource-usage-relative-path','logs/simion_batch_resource_usage.json','--dispatch-plan',$runtimeDispatchPlanPath,'--dispatch-plan-relative-path','results/simion_repository_dispatch_plan.json','--output',$resourceProfilePath)
    }
    $rawLog=Join-Path $logDir 'native_two_prism_flight.log';$batchMergeReceipt=Join-Path $resultDir 'batch_log_merge_receipt.json'
    $mergeParticleIdMin=if($bunchSelectionRequested){$BunchParticleIdMin}else{1}
    $mergeArgs=@('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight','merge','--particle-count',([string]$trial.source_particle_count),'--particle-id-min',([string]$mergeParticleIdMin),'--output',$rawLog,'--receipt',$batchMergeReceipt)
    foreach($planned in @($finalBatchPlan.batches)){$record=$batchRecords[[int]$planned.index];$mergeArgs+=@('--batch-log',$record.stdout,([string]$record.offset),([string]$record.count))}
    Invoke-ProjectPython -Arguments $mergeArgs
  }
  # Static component guards remain live through every worker.  Flight performs
  # no Workbench save, so no post-flight payload scan or copy is necessary.
  if($isBunchFlight-and$null-ne$batchRuntimeRoot){Remove-TemporarySolverDirectory -Path $batchRuntimeRoot;$batchRuntimeRoot=$null}
  # All SIMION workers are terminal here.  Post-processing is ordinary Python
  # over compact logs and must not reacquire or transition a heavy solver
  # reservation that the host scheduler may already have retired.
  $rawLog=Join-Path $logDir 'native_two_prism_flight.log';$observation=Join-Path $resultDir 'two_prism_trial_observation.json'
  $failureStage='analyze_trial'
  Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial','analyze','--log',$rawLog,'--trial-receipt',$trialReceipt,'--output',$observation)
  $observed=Get-Content -LiteralPath $observation -Raw -Encoding UTF8|ConvertFrom-Json
  $collectionGatePath=$null;$collectionGate=$null
  $isSafeExitOnly=([string]$trial.execution_scope-eq'accelerator_safe_exit_envelope_only')
  if($isBunchFlight-and-not$isSafeExitOnly){
    # Collection quality is a downstream admission decision.  The completed
    # flight remains a verified result even when its collection is below the
    # hard minimum, so no physical evidence is discarded here.
    $collectionGatePath=Join-Path $resultDir 'bunch_collection_gate.json'
    Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.bunch_collection_gate',
      '--observation',$observation,'--output',$collectionGatePath)
    $collectionGate=Get-Content -LiteralPath $collectionGatePath -Raw -Encoding UTF8|ConvertFrom-Json
  }
  $observedResiduals=if($null-ne$observed.PSObject.Properties['residuals']){$observed.residuals}else{$null}
  $observedExtraction=if($null-ne$observed.PSObject.Properties['extraction_diagnostic']){$observed.extraction_diagnostic}else{$null}
  $detectorHit=($null-ne$observedExtraction-and$observedExtraction.status-eq'detector_hit')
  $pulseClause=if($PulseAcceleratorUntilInitialExit){' The accelerator remained energized through the first exit and was then grounded using the measured single-centre exit event; this event-triggered schedule is not valid for a bunch.'}elseif($null-ne$acceleratorPulseSchedule){' The frozen source consumed one schema-2 global pulse-off schedule bound to the complete cohort safe-exit envelope.'}else{' The accelerator remained static.'}
  $summaryReason=if($bunchSelectionRequested){"The contiguous frozen source interval $BunchParticleIdMin..$BunchParticleIdMax was replayed as a diagnostic without filtering its outcomes."+$pulseClause+' Detection and collision evidence remain Candidate diagnostics.'}elseif($null-ne$bunchSourceContract){'The complete frozen N>1 cohort was flown without filtering losses.'+$pulseClause+' Detection, target-K, overtone and TOF statistics remain Candidate evidence.'}elseif($detectorHit){'The fixed reviewed geometry was flown once from the mirror-derived near-5-eV pre-acceleration state with unchanged static prism voltages.'+$pulseClause+' A natural non-retracing detector hit proves only the single-centre event chain; target-K closure remains independently required.'}else{'The fixed reviewed geometry was flown once from the mirror-derived near-5-eV pre-acceleration state with unchanged static prism voltages.'+$pulseClause+' No natural non-retracing detector hit was observed, so the prototype event chain remains open.'}
  $cohortAnalysis=if($null-ne$observed.PSObject.Properties['cohort_analysis']){$observed.cohort_analysis}else{$null}
  if($isSafeExitOnly){$summaryReason='The frozen source was flown only through the accelerator exit envelope. Detector collection, full return and resolving power are not evaluated.'}
  $dispatchSummary=$null
  if($isBunchFlight){
    $dispatchDocument=Get-Content -Raw -LiteralPath $runtimeDispatchPlanPath|ConvertFrom-Json
    $usageDocument=if(Test-Path -LiteralPath $batchResourceUsagePath -PathType Leaf){Get-Content -Raw -LiteralPath $batchResourceUsagePath|ConvertFrom-Json}else{$null}
    $peakActiveWorkers=if($null-eq$usageDocument){0}else{[int]$usageDocument.execution_wave.peak_concurrency}
    $cpuLimit=[int]$dispatchDocument.limits.cpu_capacity;$memoryLimit=[int]$dispatchDocument.limits.memory_capacity
    $bottleneck=if($cpuLimit-lt$memoryLimit){'cpu'}elseif($memoryLimit-lt$cpuLimit){'memory'}else{'cpu_and_memory_equal'}
    $dispatchSummary=[ordered]@{
      requested_particles=[int]$trial.source_particle_count
      planned_workers=[int]$dispatchDocument.limits.maximum_concurrency
      peak_active_workers=$peakActiveWorkers
      bottleneck=$bottleneck
      estimation_kind=[string]$dispatchDocument.estimation.kind
      execution_method='official_shared_iob__per_process_particles_override'
      parallelism_result=$(if($null-eq$usageDocument){'all_batches_recovered_without_simion'}elseif($peakActiveWorkers-gt1){'parallel_workers_observed'}elseif([int]$dispatchDocument.limits.maximum_concurrency-eq1){"planner_limited_by_$bottleneck"}else{'runtime_admission_remained_serial__inspect_resource_usage_pause_events'})
    }
  }
  $summaryQualification=if($null-ne$bunchSourceContract){'candidate_native_corridor_bunch__not_formal'}else{'single_center_native_corridor_trial__not_formal'}
  if($isSafeExitOnly){$summaryQualification='accelerator_exit_envelope_diagnostic__no_detector_performance_qualification'}
  $summaryValue=[ordered]@{schema_version=1;role='mrtof_finite_3d_two_prism_voltage_trial';status='success';qualification=$summaryQualification;source_particle_count=[int]$trial.source_particle_count;source_cohort=$trial.source_cohort;source_y_offset_from_accelerator_axis_mm=$trial.source_y_offset_from_accelerator_axis_mm;dispatch=$dispatchSummary;stripe_biases_v=@($trial.stripe_biases_v);prism_voltages_v=@($Prism1VoltageV,$Prism2VoltageV);stripe_operating_provenance=$stripeOperatingProvenance;response_regions=@();accelerator_pulse=$trial.accelerator_pulse;accelerator_pulse_diagnostic=$observed.accelerator_pulse_diagnostic;transport_status=$observed.status;cohort_analysis=$cohortAnalysis;collection_gate=$collectionGate;extraction_diagnostic=$observedExtraction;residuals=$observedResiduals;reason=$summaryReason}
  Write-RunJson -Path $summary -Depth 100 -Value $summaryValue
  $config=Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($retainGuiWorkbenchFiles){
    # SIMION writes replay caches beside the IOB. They are regenerated on
    # demand and are not part of the GUI-equivalent assembly.
    foreach($trajectoryCache in @(Get-ChildItem -LiteralPath $temporarySolverDir -File -Filter 'trj*.tmp')){
      [IO.File]::Delete($trajectoryCache.FullName)
    }
    $guiNativeController=[string]$nativeRuntime.controller_path
    if($null-ne$NativeCorridorRuntimeSession){
      # Flights use the short execution alias, but that alias is removed when
      # the workflow closes. The retained GUI package instead binds the same
      # persistent, read-only checkpoint family.
      $stableNativeController=Join-Path ([string]$NativeCorridorRuntimeSession.directory) 'mrtof_analyzer_corridor.pa0'
      if(-not(Test-Path -LiteralPath $stableNativeController -PathType Leaf)){throw 'Retained GUI workbench native checkpoint controller is missing.'}
      $guiNativeController=$stableNativeController
      $nativeRuntime.controller_path=$stableNativeController
    }
    # Reassemble only the tiny IOB against the same stable read-only component
    # paths. No PA is copied, refined, rebuilt, rewritten, or retained for GUI parity.
    $guiBuildArguments=@('--nogui','--noprompt','lua',(Join-Path $solverDir 'build_native_corridor_iob.lua'),'--',
      $privateIobSeed,$globalFallbackAnalyzer,$guiNativeController,$persistentAcceleratorController,$sourceDetector,
      $temporaryIob,$iobProgramPath,$iobFly2Path,$sidecar,(Join-Path $solverDir 'mrtof_three_component_candidate.voltage_map.lua'),
      (Join-Path $solverDir 'native_corridor_priority_contract.lua'))+$nativeOriginArguments
    Invoke-SimionStage -Stage 'rebind_retained_gui_iob' -Arguments $guiBuildArguments -ResourceLease $resourceLease -RegisterHostProcess $ownsHostResourceLease
    $retainedFly2=[IO.Path]::ChangeExtension($temporaryIob,'.fly2')
    if(-not(Test-RunFilesIdentical -Left $fly2Input -Right $retainedFly2)){throw 'Retained GUI IOB companion Fly2 differs after stable PA binding.'}
    $null=Remove-IobSeedPlaceholderCompanions -Directory $temporarySolverDir -Count 4
    $iobAnalyzerInput=$globalFallbackAnalyzer
    $iobAcceleratorInput=$persistentAcceleratorController
    $iobDetectorInput=$sourceDetector
    $guiWorkbenchIob=$temporaryIob
    $guiWorkbenchReceipt=Join-Path $resultDir 'gui_workbench_receipt.json'
    if([IO.Path]::GetFullPath($temporarySolverDir)-ne[IO.Path]::GetFullPath($guiWorkbenchDirectory)){
      throw 'Retained GUI workbench escaped its registered solver_review directory.'
    }
    # PA payloads have already been bound through the runtime and published
    # manifests.  Do not recursively enumerate or hash them again merely to
    # retain a GUI package; the receipt carries those existing identities.
    $guiWorkbenchOutputs=@(
      $privateIobSeed,
      $guiWorkbenchIob,
      [IO.Path]::ChangeExtension($guiWorkbenchIob,'.lua'),
      [IO.Path]::ChangeExtension($guiWorkbenchIob,'.fly2'),
      $guiWorkbenchIob.Replace('.iob','.priority.lua'),
      $guiWorkbenchIob.Replace('.iob','.operating_point.lua'),
      $guiWorkbenchIob.Replace('.iob','.voltage_map.lua'),
      $guiWorkbenchIob.Replace('.iob','.mirror_cycle_counter.lua'),
      $guiWorkbenchIob.Replace('.iob','.source_states.lua')
    )|Where-Object{Test-Path -LiteralPath $_ -PathType Leaf}|Select-Object -Unique
    $guiFiles=@($guiWorkbenchOutputs|ForEach-Object{$item=Get-Item -LiteralPath $_;[ordered]@{name=$item.Name;path=$item.FullName;bytes=[int64]$item.Length;sha256=(Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash}})
    $guiPaDependencies=@(
      [ordered]@{role='global_fallback';path=$iobAnalyzerInput;bytes=[int64](Get-Item -LiteralPath $iobAnalyzerInput).Length;source=$globalFallbackRecord},
      [ordered]@{role='accelerator';path=$iobAcceleratorInput;bytes=[int64](Get-Item -LiteralPath $iobAcceleratorInput).Length;source=$nativeSystemRuntimeRecords['accelerator']},
      [ordered]@{role='detector';path=$iobDetectorInput;bytes=[int64](Get-Item -LiteralPath $iobDetectorInput).Length;source=$detectorRecord},
      [ordered]@{role='native_corridor';directory=(Split-Path -Parent ([string]$nativeRuntime.controller_path));source_raw=$nativeRuntime.receipt.source_raw;source_responses=$nativeRuntime.receipt.source_responses}
    )
    Write-RunJson -Path $guiWorkbenchReceipt -Depth 14 -Value ([ordered]@{
      schema_version=1;role='simion_gui_review_workbench';status='success';qualification=$summaryQualification;
      directory=$guiWorkbenchDirectory;iob_path=$guiWorkbenchIob;iob_sha256=(Get-FileHash -LiteralPath $guiWorkbenchIob -Algorithm SHA256).Hash;
      global_operating_pa_path=$temporaryAnalyzer;global_operating_pa_sha256=$temporaryAnalyzerHash;
       source_accelerator_pa=$persistentAcceleratorController;accelerator_binding='manifest_bound_standalone_responses__shared_private_native_fast_adjust_family';source_detector_pa=$sourceDetector;files=$guiFiles;pa_dependencies=$guiPaDependencies
    })
    # The IOB stores the absolute paths passed to SIMION. Keeping this exact
    # directory in place is therefore part of the review artifact contract.
    $temporarySolverDir=$null
  }else{Remove-TemporarySolverDirectory -Path $temporarySolverDir;$temporarySolverDir=$null}
  $artifactResultDir=Join-Path ([string]$package.artifact_run_dir) 'results'
  # The builder copies every executable companion beside the output IOB.  A
  # retained GUI package therefore runs the nested copies, not their root-level
  # build inputs; compact artifacts keep the ordinary SIMION root layout.
  $flightArtifactRoot=if($retainGuiWorkbenchFiles){Join-Path $artifactSolverDir 'gui_workbench'}else{$artifactSolverDir}
  $config.inputs=[ordered]@{
    geometry_run_manifest=$nativeBankManifest
    mirror_run_manifest=$mirrorManifest
    stripe_run_manifest=$stripeManifest
    trajectory_contract=Join-Path $artifactSolverDir 'trajectory_contract.json'
    accelerator_geometry_contract=Join-Path $artifactSolverDir 'accelerator_geometry_contract.json'
    reviewed_geometry_contract=Join-Path $artifactSolverDir 'simion_prototype_contract.json'
    mirror_summary=Join-Path $artifactSolverDir 'mirror_exact_k_summary.json'
    stripe_summary=Join-Path $artifactSolverDir 'dual_stripe_exact_k_summary.json'
    fixed_mirror_stripe_downstream_authority=if($null-eq$fixedMirrorStripeAuthority){$null}else{Join-Path $artifactResultDir 'fixed_mirror_stripe_downstream_authority.json'}
    terminal_time_mirror_voltage_variation=if($null-eq$mirrorVoltageVariation){$null}else{Join-Path $artifactSolverDir 'terminal_time_mirror_voltage_variation.json'}
    accelerator_run_manifest=$acceleratorManifest
    accelerator_provider_receipt=Join-Path $artifactSolverDir 'accelerator_provider_runtime_receipt.json'
    accelerator_provider_plan=Join-Path $artifactSolverDir 'accelerator_provider_plan.json'
    accelerator_resolved_campaign=Join-Path $artifactSolverDir 'accelerator_resolved_campaign.json'
    accelerator_pulse_schedule=if($null-eq$acceleratorPulseScheduleLocal){$null}else{Join-Path $artifactSolverDir 'accelerator_pulse_schedule.json'}
    bunch_source_receipt=if($null-eq$bunchSourceReceipt){$null}else{Join-Path $artifactSolverDir 'bunch_source_receipt.json'}
    bunch_source_run_manifest=$bunchSourceManifest
    bunch_collection_gate=if($null-eq$collectionGatePath){$null}else{Join-Path $artifactResultDir 'bunch_collection_gate.json'}
    simion_dispatch_request=$dispatchRequestPath
    simion_resource_profiles=$resourceProfilesPath
    simion_repository_dispatch_plan=$runtimeDispatchPlanPath
    simion_execution_batch_plan=$batchPlanPath
    batch_log_merge_receipt=$batchMergeReceipt
    trajectory_numerics_contract=Join-Path $artifactSolverDir 'trajectory_numerics_contract.json'
    iob_builder=Join-Path $artifactSolverDir 'build_native_corridor_iob.lua'
    iob_seed=Join-Path $artifactSolverDir '4_instance_seed.iob'
    native_corridor_bank_run_manifest=Join-Path $artifactSolverDir 'native_corridor_bank_run_manifest.json'
    native_corridor_bank_publication=Join-Path $artifactSolverDir 'native_corridor_bank_publication.json'
    native_corridor_bank_cache_manifest=Join-Path $artifactSolverDir 'native_corridor_bank_cache_manifest.json'
    native_corridor_priority_contract=Join-Path $artifactSolverDir 'native_corridor_priority_contract.lua'
    native_corridor_runtime_support=Join-Path $artifactSolverDir 'native_corridor_runtime_support.ps1'
    native_corridor_assembler=Join-Path $artifactSolverDir 'assemble_native_fast_adjust_family.lua'
    native_corridor_runtime_receipt=$nativeRuntimeReceiptPath
    native_system_runtime_bundle=$nativeSystemRuntimeBundle
    native_system_runtime_components=$nativeSystemRuntimeRecords
    flight_program=Join-Path $flightArtifactRoot 'mrtof_three_component_candidate.lua'
    mirror_cycle_counter=Join-Path $flightArtifactRoot 'mrtof_three_component_candidate.mirror_cycle_counter.lua'
    voltage_map=Join-Path $flightArtifactRoot 'mrtof_three_component_candidate.voltage_map.lua'
    operating_point_lua=Join-Path $flightArtifactRoot 'mrtof_three_component_candidate.operating_point.lua'
    flight_launcher=Join-Path $artifactSolverDir 'run_iob_flight.lua'
    trial_materializer=Join-Path $artifactSolverDir 'two_prism_simion_trial.py'
    native_global_fallback_pa=$globalFallbackAnalyzer
    private_accelerator_controller_pa=$persistentAcceleratorController
    read_only_detector_pa=$sourceDetector
    trial_materialization=Join-Path $artifactResultDir 'two_prism_trial_materialization.json'
    resolved_iob_pose=Join-Path $artifactResultDir 'resolved_iob_pose.json'
    frozen_source_fly2=Join-Path $artifactSolverDir 'downstream_trial_source.input.fly2'
    simion_batch_continuation_plan=if($null-eq$batchContinuationPlanPath){$null}else{Join-Path ([string]$package.artifact_run_dir) 'inputs\mrtof_batch_continuation\simion_batch_continuation_plan.json'}
    gui_workbench_iob=$guiWorkbenchIob
    gui_workbench_receipt=$guiWorkbenchReceipt
    native_corridor_protection_renewal=$capacityProtectionRenewalPath
  }
  if(-not$config.Contains('provenance')){$config['provenance']=[ordered]@{}}
  $config['provenance']['upstream_manifest_verification']=[ordered]@{
    geometry=[ordered]@{
      scope='current_contract_plus_native_corridor_bank'
      manifest=$nativeBankManifest
      consumed_contract=$geometryReviewedContract
      unconsumed_records_not_asserted=$true
    }
    native_system_runtime=[ordered]@{
      bundle=$NativeSystemRuntimeBundlePath
      components=$nativeSystemRuntimeRecords
      unconsumed_records_not_asserted=$true
    }
    all_other_upstream_manifests='full'
  }
  $config.parameters.prism_1_voltage_v=$Prism1VoltageV;$config.parameters.prism_2_voltage_v=$Prism2VoltageV;$config.parameters.stripe_biases_v=@($trial.stripe_biases_v);$config.parameters.stripe_operating_provenance=$stripeOperatingProvenance;$config.parameters.source_particle_count=[int]$trial.source_particle_count;$config.parameters.source_cohort=$trial.source_cohort;$config.parameters.source_selection=$trial.source_selection;$config.parameters.source_y_offset_from_accelerator_axis_mm=$trial.source_y_offset_from_accelerator_axis_mm;$config.parameters.accelerator_y_anchor_mm=if($null-eq$AcceleratorYAnchorMm){$null}else{[double]$AcceleratorYAnchorMm};$config.parameters.simion_dispatch=$dispatchSummary;$config.parameters.flight_scope=if($isSafeExitOnly){'accelerator_safe_exit_envelope_only'}else{'complete_three_dimensional_static_return'};$config.parameters.execution_scope=[string]$trial.execution_scope;$config.parameters.accelerator_pulse=$trial.accelerator_pulse;$config.parameters.accelerator_field_mode=if($acceleratorPulseRequested){'manifest_bound_standalone_operating_pa__efield_gate_to_zero'}else{'manifest_bound_standalone_operating_pa__static'};$config.parameters.pa_binding_mode=if($null-ne$bunchSourceContract){'native_corridor_private_fast_adjust_family__four_instances__complete_bunch__no_refine'}else{'native_corridor_private_fast_adjust_family__four_instances__n1'};$config.parameters.trajectory_profile=$trial.trajectory_profile;$config.parameters.gui_workbench_retained=[bool]$retainGuiWorkbenchFiles
  if($isBunchFlight){$config.parameters.execution_mode='mrtof_native_corridor_bunch';$config.parameters.particle_count=[int]$trial.source_particle_count;$config.parameters.launched_particle_count=[int]$trial.source_particle_count}
  Write-RunJson -Path $runConfig -Value $config
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $failureStage='capacity_terminal'
  $protectedCacheKeys=@($nativeBankKey)
  $terminalCommitment=if($ownsCapacitySession){[int64]0}else{[int64]$capacitySession.committed_new_bytes}
  $terminal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -Session $capacitySession -ProtectedCacheKeys $protectedCacheKeys `
    -RemainingCommittedNewBytes $terminalCommitment
  $capacitySession=$terminal.session
  $terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  $manifestOutputs=@($summary,$observation,$trialReceipt,$voltageReceipt,$posePath,$startupPath,$terminalPath,$retention)
  if($null-ne$collectionGatePath){$manifestOutputs+=$collectionGatePath}
  if($null-ne$earlyAberrationReport-and(Test-Path -LiteralPath $earlyAberrationReport -PathType Leaf)){$manifestOutputs+=$earlyAberrationReport}
  if($null-ne$nativeRuntimeReceiptPath){$manifestOutputs+=$nativeRuntimeReceiptPath}
  if(Test-Path -LiteralPath $rawLog -PathType Leaf){$manifestOutputs+=$rawLog}
  if($null-ne$fixedMirrorStripeAuthority){$manifestOutputs+=$fixedMirrorStripeAuthority}
  foreach($path in @($dispatchRequestPath,$resourceProfilesPath,$runtimeDispatchPlanPath,$batchPlanPath,$batchResourceUsagePath,$batchMergeReceipt,$resourceProfilePath)){
    if($null-ne$path-and(Test-Path -LiteralPath $path -PathType Leaf)){$manifestOutputs+=$path}
  }
  if($isBunchFlight){foreach($record in @($batchRecords.Values)){foreach($path in @($record.stdout,$record.stderr)){if(Test-Path -LiteralPath $path -PathType Leaf){$manifestOutputs+=$path}}}}
  if($null-ne$capacityProtectionRenewalPath){$manifestOutputs+=$capacityProtectionRenewalPath}
  if($null-ne$guiWorkbenchReceipt){$manifestOutputs+=$guiWorkbenchReceipt}
  if($guiWorkbenchOutputs.Count){$manifestOutputs+=@($guiWorkbenchOutputs)}
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success -Software @('SIMION 2020','Python 3.11') -Outputs $manifestOutputs
  $terminalized=$true;$hostOutcome='success';Write-Host "MRTOF_TWO_PRISM_TRIAL=PASS RUN_ID=$RunId TRANSPORT=$($observed.status)"
}catch{
  $failureRecord=$_
  if(-not$terminalized){
    # SIMION trajectory replay caches are disposable even when the GUI IOB is
    # retained.  Remove them before compact failure publication so an
    # interrupted flight cannot strand the run in the capacity ledger.
    if($null-ne$temporarySolverDir-and(Test-Path -LiteralPath $temporarySolverDir -PathType Container)){
      foreach($trajectoryCache in @(Get-ChildItem -LiteralPath $temporarySolverDir -File -Filter 'trj*.tmp')){
        [IO.File]::Delete($trajectoryCache.FullName)
      }
    }
    $failureEvidence=@{
      invocation_position=[string]$failureRecord.InvocationInfo.PositionMessage
      script_stack_trace=[string]$failureRecord.ScriptStackTrace
    }
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_finite_3d_two_prism_voltage_trial' -Reason $failureRecord.Exception.Message -Software @('SIMION 2020','Python 3.11') -Status failed -FailureStage $failureStage -AdditionalSummaryProperties $failureEvidence
    $terminalized=$true
  }
  throw
}finally{
  if(-not$terminalized-and(Test-Path -LiteralPath $runConfig -PathType Leaf)){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_finite_3d_two_prism_voltage_trial' -Reason 'Runner stopped before terminal evidence publication.' -Software @('SIMION 2020','Python 3.11') -Status interrupted -FailureStage $failureStage;$hostOutcome='interrupted'}
  if($null-ne$temporaryAcceleratorRuntimeSession){Suspend-NativeCorridorRuntimeSession -Session $temporaryAcceleratorRuntimeSession}
  if($ownsHostResourceLease-and$null-ne$resourceLease){
    $topLevelLease=-not[bool]$resourceLease.inherited
    Exit-HostResourceStage -Lease $resourceLease
    if($topLevelLease){Invoke-HostExecutionCompletionNotification -Outcome $hostOutcome -RunId $RunId}
  }
  Remove-RunPackageExecutionAlias -Package $package
  if($null-ne$batchRuntimeRoot-and(Test-Path -LiteralPath $batchRuntimeRoot -PathType Container)){Remove-TemporarySolverDirectory -Path $batchRuntimeRoot}
  if($null-ne$temporarySolverDir-and-not$retainGuiWorkbenchFiles){Remove-TemporarySolverDirectory -Path $temporarySolverDir}
  if($ownsCapacitySession-and$null-ne$capacitySession){
    $null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession
  }
}
