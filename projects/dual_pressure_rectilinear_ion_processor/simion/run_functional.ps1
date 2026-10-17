[CmdletBinding()]
param([Parameter(Mandatory)][string]$RunId,[string]$SimionExe='',[string]$NativeFieldRun='',
 [string]$ConfigurationDirectory='',
 [ValidateSet('functional','exploration')][string]$SourceProfile='functional')
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
function Enter-IonProcessorNativeFlightGuards {
 param($ResolvedModel,$Pa0Record,$Context,[switch]$FreshBuild)
 # The frozen electrode namespace is the authority for numbered responses;
 # controller/geometry/surface names follow the same native controller root.
 $controller=[IO.Path]::GetFullPath($Pa0Record.path)
 $prefix=$controller.Substring(0,$controller.Length-1)
 $paths=@(($prefix+'#'),$controller)+@($ResolvedModel.native_projection.electrode_ids|ForEach-Object{$prefix+[string]$_})+@($prefix+'-surf')
 try {
  if($FreshBuild){
   # Only this run's newly built writable family: all Refine/IOB producers
   # have exited. Commit their delayed pages before persistent-byte identity.
   # Never flush or open an immutable external source for writing.
   foreach($path in $paths){
    $buildStream=$null
    try {
     $buildStream=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
     $buildStream.Flush($true)
    } finally {if($null-ne$buildStream){$buildStream.Dispose()}}
   }
  }
  foreach($path in $paths){
   $stream=$null
   try {
    $stream=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    $bytes=$stream.Length
    $sha=Get-ImmutablePaSourceVerificationSha256 -Stream $stream -Length $bytes
   } finally {if($null-ne$stream){$stream.Dispose()}}
   if($path-eq$controller-and($bytes-ne$Pa0Record.bytes-or$sha-ne$Pa0Record.sha256)){throw 'Native controller identity changed before flight'}
   $entry=[pscustomobject]@{path=$path;bytes=$bytes;before_sha256=$sha;after_sha256=$null;owns_guard=$false;guard_acquired=$false;verified=$false;error=$null}
   $Context.records.Add($entry)
   $guard=Protect-ImmutablePaSource -Source $path -ExpectedBytes $bytes -ExpectedSha256 $sha
   $entry.owns_guard=-not$guard.already_protected;$entry.guard_acquired=$true
  }
  $Context.status='protected'
 } catch {$Context.error=$_.Exception.Message;throw}
}
function Complete-IonProcessorNativeFlightGuards {
 param($Context,[string]$VerificationPath)
 $errors=[Collections.Generic.List[string]]::new()
 if($Context.status-ne'protected'){$errors.Add('native family guard acquisition incomplete: '+$Context.error)}
 try {
  foreach($entry in $Context.records){
   if(-not$entry.guard_acquired){continue}
   try {
    $stream=$global:MassSpectrometryImmutablePaSourceGuards[[IO.Path]::GetFullPath($entry.path)].stream
    $entry.after_sha256=Get-ImmutablePaSourceVerificationSha256 -Stream $stream -Length $entry.bytes
    if($entry.after_sha256-ne$entry.before_sha256){throw 'Native family identity changed during flight'}
    $entry.verified=$true
   } catch {$entry.error=$_.Exception.Message;$errors.Add($entry.path+': '+$entry.error)}
  }
  $Context.status=$(if($errors.Count){'failed'}else{'verified'})
  Write-RunJson -Path $VerificationPath -Value @{schema_version=1;role='native_flight_family_identity';status=$Context.status;hash_policy='public_immutable_source_verification_no_buffered_fallback';records=@($Context.records.ToArray());errors=@($errors.ToArray())}
 } finally {
  foreach($entry in $Context.records){if($entry.owns_guard){Unprotect-ImmutablePaSource -Source $entry.path|Out-Null}}
 }
 if($errors.Count){throw ($errors -join '; ')}
}
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$repoRoot=(Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
. (Join-Path $repoRoot 'common/require_powershell7.ps1')
. (Join-Path $repoRoot 'common/contracts/run_artifact_support.ps1')
. (Join-Path $repoRoot 'common/multipole/resource_budget_support.ps1')
. (Join-Path $repoRoot 'common/simion/short_pa_path_support.ps1')
$python=Join-Path $repoRoot '.venv/Scripts/python.exe'
if(-not $SimionExe){$SimionExe=Join-Path $env:ProgramFiles 'SIMION-2020/simion.exe'}
if(-not(Test-Path -LiteralPath $SimionExe)){throw 'SIMION 2020 executable missing'}
$profile=(Get-Content (Join-Path $projectRoot 'config/execution_profiles.json') -Raw|ConvertFrom-Json).profiles[0]
$configurationRoot=if($ConfigurationDirectory){(Resolve-Path -LiteralPath $ConfigurationDirectory).Path}else{Join-Path $projectRoot 'config'}
if($profile.retain_batch_trajectories-isnot[bool]){throw 'Execution profile retain_batch_trajectories must be boolean'}
if($profile.native_field_query_memory_bytes-isnot[long]-and$profile.native_field_query_memory_bytes-isnot[int]){throw 'Native query memory declaration must be integer bytes'}
if($profile.native_field_query_memory_bytes-le0){throw 'Native query memory declaration must be positive'}
$retainBatchTrajectories=[int]$profile.retain_batch_trajectories
$committedNewBytes=[long]$profile.committed_new_bytes
if($NativeFieldRun){
 $sourceFile=$(if($SourceProfile-eq'exploration'){'source_exploration.json'}else{'source.json'})
 $count=(Get-Content (Join-Path $configurationRoot $sourceFile) -Raw|ConvertFrom-Json).particle_count
 $committedNewBytes=[long][Math]::Max(2GB,([long]$count*50MB+256MB))
}
$artifacts=Join-Path $workspaceRoot 'artifacts'
$projectArtifacts=Join-Path $artifacts 'projects/dual_pressure_rectilinear_ion_processor'
$capacity=$null;$package=$null;$lease=$null;$finished=$false;$runSucceeded=$false
$savedPythonPath=$env:PYTHONPATH;$env:PYTHONPATH=$repoRoot
Push-Location $repoRoot
try {
 $protected=@($configurationRoot);if($NativeFieldRun){$NativeFieldRun=(Resolve-Path -LiteralPath $NativeFieldRun).Path;$protected+=@($NativeFieldRun)}
 $capacity=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifacts -RunDirectory (Join-Path $projectArtifacts "runs/$RunId") -CommittedNewBytes $committedNewBytes -ProtectedPaths $protected
 $package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $projectArtifacts -RunId $RunId -Project dual_pressure_rectilinear_ion_processor -Mode native_electrode_functional -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass $profile.retention_class -RetentionReason $profile.retention_reason -CapacityLedgerLifecycleEnabled -AdditionalDirectories @('simion')
 $run=$package.run_dir;$solver=Join-Path $run 'simion'
 $prepareArguments=@('-m','projects.dual_pressure_rectilinear_ion_processor.analysis.functional','prepare','--run',$run,'--simion-dir',(Split-Path -Parent $SimionExe),'--source-profile',$SourceProfile)
 if($ConfigurationDirectory){$prepareArguments+=@('--configuration-directory',$configurationRoot)}
 if($NativeFieldRun){$prepareArguments+=@('--native-field-run',$NativeFieldRun)}
 & $python @prepareArguments
 if($LASTEXITCODE-ne0){throw 'Input preparation failed'}
 Copy-VerifiedRunInput (Join-Path $projectRoot 'config/execution_profiles.json') (Join-Path $package.input_dir 'execution_profiles.json')|Out-Null
 $profile.limits.transient_run_directory_bytes=$committedNewBytes
 $config=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
 $config.inputs.execution_profiles=Join-Path $package.input_dir 'execution_profiles.json'
 Write-RunJson -Path $package.run_config -Value $config
 $lease=Enter-HostExecutionLease -Role SIMION -Stage prepare
 $numerics=Get-Content (Join-Path $package.input_dir 'numerics.json') -Raw|ConvertFrom-Json
 $commands=@(
  @{name='gem';stage='prepare';arguments=@('--nogui','--noprompt','gem2pa','processor.gem','processor.pa#')},
  @{name='refine';stage='pa_refine';arguments=@('--nogui','--noprompt','refine',"--convergence=$($numerics.refine_convergence_v)",'processor.pa#')},
  @{name='workbench';stage='prepare';arguments=@('--nogui','--noprompt','lua',(Join-Path $solver 'build_workbench.lua'))},
  @{name='potential_audit';stage='prepare';arguments=@('--nogui','--noprompt','lua',(Join-Path $solver 'probe_native_field.lua'))}
 )
 if($NativeFieldRun){$commands=@($commands|Where-Object{$_.name-notin@('gem','refine')})}
 Copy-VerifiedRunInput (Join-Path $solver 'runtime.lua') (Join-Path $solver 'processor.lua')|Out-Null
 foreach($command in $commands){
  $stageBudget=Get-HostResourceBudget -Role SIMION -Stage $command.stage
  if($command.name-eq'potential_audit'){$stageBudget.memory_bytes=[long]$profile.native_field_query_memory_bytes}
  $lease=Update-HostResourceStage -Lease $lease -Stage $command.stage -Budget $stageBudget -RetainedMemoryBytes 0
  Write-Output "ION_PROCESSOR_STAGE=$($command.name) RUN=$RunId"
  $result=Invoke-ResourceBudgetedProcess -Limits $profile.limits -RunDir $run -UsagePath (Join-Path $package.result_dir "$($command.name)_resource_usage.json") -FilePath $SimionExe -ArgumentList $command.arguments -WorkingDirectory $solver -RedirectStandardOutput (Join-Path $package.log_dir "$($command.name).log") -RedirectStandardError (Join-Path $package.log_dir "$($command.name).stderr.log")
  if($result.exit_code-ne0){throw "SIMION $($command.name) failed: $($result.exit_code)"}
 }
 # Public dispatch controls every native particle flight. Use only the frozen
 # Python closure, and keep the original heavy permission through all workers.
 $nativeFlightGuardContext=$null
 $env:PYTHONPATH=Join-Path $run 'inputs/code'
 Push-Location $run
 try {
  function Invoke-PreparedPython {
   param([string[]]$Arguments)
   & $python @Arguments | Out-Host
   if($LASTEXITCODE-ne0){throw "Prepared Python boundary failed: $($Arguments -join ' ')"}
  }
  Invoke-PreparedPython -Arguments @('-m','projects.dual_pressure_rectilinear_ion_processor.analysis.functional','prepare-dispatch','--run',$run)
  $iobPreparation=Get-Content (Join-Path $run 'inputs/batch_iob_preparation.json') -Raw|ConvertFrom-Json
  if($iobPreparation.requires_vendor_templates){
   $paRecord=$iobPreparation.native_pa0_record
   $guard=Protect-ImmutablePaSource -Source $paRecord.path -ExpectedBytes $paRecord.bytes -ExpectedSha256 $paRecord.sha256
   try {
    $build=Invoke-ResourceBudgetedProcess -Limits $profile.limits -RunDir $run -UsagePath (Join-Path $package.result_dir 'batch_iob_template_resource_usage.json') -FilePath $SimionExe -ArgumentList @('--nogui','--noprompt','lua',$iobPreparation.script) -WorkingDirectory $solver -RedirectStandardOutput (Join-Path $package.log_dir 'batch_iob_templates.log') -RedirectStandardError (Join-Path $package.log_dir 'batch_iob_templates.stderr.log')
    if($build.exit_code-ne0){throw 'Native batch IOB template preparation failed'}
    $stream=$global:MassSpectrometryImmutablePaSourceGuards[[IO.Path]::GetFullPath($paRecord.path)].stream
    if((Get-ImmutablePaSourceVerificationSha256 -Stream $stream -Length $paRecord.bytes)-ne$paRecord.sha256){throw 'Native source PA0 changed during template preparation'}
   } finally {if(-not$guard.already_protected){Unprotect-ImmutablePaSource -Source $paRecord.path|Out-Null}}
  }
  if(-not$NativeFieldRun){
   $nativeFlightGuardContext=@{records=[Collections.Generic.List[object]]::new();status='acquiring';error=$null}
   $resolvedModel=Get-Content (Join-Path $run 'inputs/resolved_model.json') -Raw|ConvertFrom-Json
   Enter-IonProcessorNativeFlightGuards -ResolvedModel $resolvedModel -Pa0Record $iobPreparation.native_pa0_record -Context $nativeFlightGuardContext -FreshBuild:(-not [bool]$NativeFieldRun)
  }
  $requestPath=Join-Path $run 'inputs/simion_dispatch_request.json'
  $profilesPath=Join-Path $run 'results/simion_resource_profiles.json'
  $dispatchPath=Join-Path $run 'results/simion_repository_dispatch_plan.json'
  $batchPlanPath=Join-Path $run 'results/simion_execution_batch_plan.json'
  $usagePath=Join-Path $run 'results/simion_batch_resource_usage.json'
  Invoke-PreparedPython -Arguments @('-m','common.simion.resource_profile','discover','--runs-root',(Join-Path $projectArtifacts 'runs'),'--output',$profilesPath)
  Invoke-PreparedPython -Arguments @('-m','common.simion.resource_scheduler','--request',$requestPath,'--profiles',$profilesPath,'--output',$dispatchPath)
  Invoke-PreparedPython -Arguments @('-m','common.simion.particle_batching','--from-dispatch-plan',$dispatchPath,'--output',$batchPlanPath)
  Invoke-PreparedPython -Arguments @('-m','projects.dual_pressure_rectilinear_ion_processor.analysis.functional','materialize-batches','--run',$run,'--batch-plan',$batchPlanPath)
  function New-IonProcessorProcessSpecification {
   param($Batch)
   $folder=Join-Path $run ('simion_batch_{0:D4}'-f[int]$Batch.index)
   return [pscustomobject]@{
    name=('ion_processor_batch_{0:D4}'-f[int]$Batch.index);scheduler_batch=$Batch
    file_path=$SimionExe;working_directory=$folder;environment=@{}
    stdout=(Join-Path $package.log_dir ('flight_batch_{0:D4}.log'-f[int]$Batch.index))
    stderr=(Join-Path $package.log_dir ('flight_batch_{0:D4}.stderr.log'-f[int]$Batch.index))
    argument_list=[string[]]@('--nogui','--noprompt','fly','--trajectory-quality',"$($numerics.trajectory_quality)",'--particles','processor.fly2','--programs','1','--retain-trajectories',"$retainBatchTrajectories",'processor.iob')
   }
  }
  $dispatch=Get-Content $dispatchPath -Raw|ConvertFrom-Json
  $initial=Get-Content $batchPlanPath -Raw|ConvertFrom-Json
  $unknown=$dispatch.estimation.kind-eq'formal_first_batch_observation'
  $existingRecords=@();$formalIndex=$null
  $lease=Update-HostResourceStage -Lease $lease -Stage flight -Budget (Get-HostResourceBudget -Role SIMION -Stage flight) -RetainedMemoryBytes 0
  try {
   if($unknown){
    $first=$initial.batches[0];$formalIndex=[int]$first.index
    $formal=Start-ObservedFormalProcess -DispatchPlanPath $dispatchPath -ProcessSpecification (New-IonProcessorProcessSpecification $first)
    $existingRecords=@($formal.process_record)
    if($formal.resource_budget_exceeded-or($formal.process_record.completed-and(-not$formal.completed_naturally-or[int]$formal.exit_code-ne0))){throw 'Formal-first native batch did not continue or complete safely'}
    $adaptive=@('-m','common.simion.resource_scheduler','--request',$requestPath,'--profiles',$profilesPath,'--output',$dispatchPath,'--observed-formal-peak-bytes',"$($formal.observed_peak_process_tree_working_set_bytes)",'--observed-formal-cpu-percent',"$($formal.observed_process_cpu_percent)",'--observed-background-cpu-percent',"$($formal.observed_background_cpu_percent)",'--available-memory-bytes',"$($formal.available_memory_bytes)",'--total-physical-memory-bytes',"$($formal.total_physical_memory_bytes)")
    if($formal.process_record.completed){$adaptive+='--first-batch-completed'}
    Invoke-PreparedPython -Arguments $adaptive
    Invoke-PreparedPython -Arguments @('-m','common.simion.particle_batching','--from-dispatch-plan',$dispatchPath,'--output',$batchPlanPath)
    Invoke-PreparedPython -Arguments @('-m','projects.dual_pressure_rectilinear_ion_processor.analysis.functional','materialize-batches','--run',$run,'--batch-plan',$batchPlanPath)
   }
   $final=Get-Content $batchPlanPath -Raw|ConvertFrom-Json
   $pending=@($final.batches|Where-Object{$null-eq$formalIndex-or[int]$_.index-ne$formalIndex}|ForEach-Object{New-IonProcessorProcessSpecification $_})
   $wave=Invoke-ResourceBudgetedProcesses -DispatchPlanPath $dispatchPath -RunDir $run -UsagePath $usagePath -ProcessSpecifications $pending -ExistingProcessRecords $existingRecords
   if($wave.resource_budget_exceeded-or@($wave.processes|Where-Object{[int]$_.exit_code-ne0}).Count){throw 'Native particle dispatch failed or exceeded public resources'}
  } catch {
   foreach($record in $existingRecords){if($record.active-and-not$record.process.HasExited){Stop-ManagedSolverProcesses -ProcessIds @([int]$record.root_process_id)}}
   throw
  }
  Complete-ResourceUsage -RunDir $run -UsagePath $usagePath|Out-Null
  if($unknown){Invoke-PreparedPython -Arguments @('-m','common.simion.resource_profile','publish','--run-id',$RunId,'--resource-usage',$usagePath,'--resource-usage-relative-path','results/simion_batch_resource_usage.json','--dispatch-plan',$dispatchPath,'--dispatch-plan-relative-path','results/simion_repository_dispatch_plan.json','--output',(Join-Path $run 'results/simion_resource_profile.json'))}
  Invoke-PreparedPython -Arguments @('-m','projects.dual_pressure_rectilinear_ion_processor.analysis.functional','merge-batches','--run',$run,'--batch-plan',$batchPlanPath)
 } finally {
  try {
   if($null-ne$nativeFlightGuardContext){Complete-IonProcessorNativeFlightGuards -Context $nativeFlightGuardContext -VerificationPath (Join-Path $run 'results/native_flight_family_verification.json')}
  } finally {Pop-Location;$env:PYTHONPATH=$repoRoot}
 }
 $lease=Update-HostResourceStage -Lease $lease -Stage postprocess -Budget (Get-HostResourceBudget -Role SIMION -Stage postprocess) -RetainedMemoryBytes 0
 # Run the prepared source closure from the run directory so an editable repo
 # cannot shadow it through Python's current-directory import precedence.
 $env:PYTHONPATH=Join-Path $run 'inputs/code'
 Push-Location $run
 try {
  & $python -m projects.dual_pressure_rectilinear_ion_processor.analysis.functional analyze --run $run
  $analysisExit=$LASTEXITCODE
 } finally {Pop-Location;$env:PYTHONPATH=$repoRoot}
 if($analysisExit-ne0-and-not(Test-Path -LiteralPath $package.summary)){throw 'Analysis did not publish measured summary'}
 $summary=Get-Content $package.summary -Raw|ConvertFrom-Json
 if($summary.role-ne'ion_processor_functional_summary'){throw 'Missing physical summary'}
 $finished=$true
 $runSucceeded=$analysisExit-eq0
 Write-Output "ION_PROCESSOR_RESULT=$($summary.status) RUN=$run"
 if($analysisExit-ne0){throw 'Analysis or required diagnostics incomplete; see frozen summary and logs'}
} catch {
 if($null-ne$package-and-not$finished){Write-RunJson -Path $package.summary -Value @{schema_version=1;role='ion_processor_failed_run';status='failed';reason=$_.Exception.Message}}
 throw
} finally {
 if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $(if($runSucceeded){'success'}else{'failed'}) -RunId $RunId}
 try {
  if($null-ne$package){
   $null=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
   $status=$(if($runSucceeded){'success'}else{'failed'})
   # Public Python API avoids Windows argv overflow with many worker outputs.
   & $python -m projects.dual_pressure_rectilinear_ion_processor.analysis.functional publish-manifest --run $package.run_dir --status $status
   if($LASTEXITCODE-ne0){throw 'Native run manifest publication failed'}
   & $python -m common.contracts.verify_run_manifest (Join-Path $package.run_dir 'run_manifest.json') --require-status $status --require-project dual_pressure_rectilinear_ion_processor
   if($LASTEXITCODE-ne0){throw 'Native run manifest verification failed'}
  }
  if($null-ne$capacity){Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity|Out-Null;$capacity=$null}
  if($null-ne$package){
   & $python -m common.contracts.run_capacity_lifecycle --action seal-stopped-payload --artifact-root $artifacts --run-config $package.run_config --owner dual_pressure_rectilinear_ion_processor --confirm-writing-stopped --retention-reason 'Retain native field, IOB and complete functional evidence for GUI replay'
   if($LASTEXITCODE-ne0){throw 'Native field payload sealing failed'}
  }
 } finally {
  if($null-ne$capacity){Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity|Out-Null}
  $env:PYTHONPATH=$savedPythonPath
  Pop-Location
 }
}
