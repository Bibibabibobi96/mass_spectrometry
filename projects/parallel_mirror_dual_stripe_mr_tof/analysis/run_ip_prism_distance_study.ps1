[CmdletBinding()]
param(
 [Parameter(Mandatory)][string]$RunId,
 [Parameter(Mandatory)][string]$ContractPath,
 [string]$SimionExe=''
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
. (Join-Path $repoRoot 'common/require_powershell7.ps1')
. (Join-Path $repoRoot 'common/contracts/run_artifact_support.ps1')
. (Join-Path $repoRoot 'common/multipole/resource_budget_support.ps1')
$python=Join-Path $repoRoot '.venv/Scripts/python.exe'
$module='projects.parallel_mirror_dual_stripe_mr_tof.analysis.ip_prism_distance_study'
$projectId='parallel_mirror_dual_stripe_mr_tof'
$artifactRoot=Join-Path (Split-Path -Parent $repoRoot) 'artifacts'
$projectArtifacts=Join-Path $artifactRoot "projects/$projectId"
$contract=(Resolve-Path -LiteralPath $ContractPath).Path
$author=Get-Content -LiteralPath $contract -Raw|ConvertFrom-Json
if($author.role-eq'ip_prism_recorded_aperture_comparison'){
 throw 'Recorded aperture comparison is analysis-only: use the existing Python prepare/analyze operations in a new analysis run, not the native simulation runner.'
}
if(-not $SimionExe){$SimionExe=Join-Path $env:ProgramFiles 'SIMION-2020/simion.exe'}
$SimionExe=(Resolve-Path -LiteralPath $SimionExe).Path
$commitment=[long]$author.committed_new_bytes
if($commitment-le0){throw 'Study requires a positive predeclared committed_new_bytes.'}

function Invoke-StudyPython {
 param([string[]]$Arguments)
 & $python @Arguments|Out-Host
 if($LASTEXITCODE-ne0){throw "IP/Prism study Python failed: $($Arguments -join ' ')"}
}
function New-StudyProcessSpecification {
 param($Batch,[ValidateSet('combined','build','fly','assemble')][string]$Phase='combined')
 $phaseCases=if($Phase-eq'build'){@($study.build_cases)}elseif($Phase-eq'fly'){@($study.flight_cases)}elseif($Phase-eq'assemble'){@($study.assembly_cases)}else{@($study.cases)}
 $first=[int]$Batch.work_item_id_min;$last=[int]$Batch.work_item_id_max
 if($first-lt1-or$last-lt$first-or$last-gt$phaseCases.Count-or[int]$Batch.count-ne($last-$first+1)){
  throw 'Public work-item interval does not cover declared study cases.'
 }
 $directory=Join-Path $run ('simion_{0}_batch_{1:D4}'-f$Phase,[int]$Batch.index)
 $null=New-Item -ItemType Directory -Path $directory -Force
 $scriptPath=Join-Path $directory 'run_batch.lua'
 $lines=[Collections.Generic.List[string]]::new()
 $lines.Add('-- Ordered complete cases from the repository work-item dispatch plan.')
 for($index=$first;$index-le$last;$index++){
  $script=[IO.Path]::GetFullPath([string]$phaseCases[$index-1].script)
  if(-not(Test-Path -LiteralPath $script -PathType Leaf)){throw "Missing frozen case script: $script"}
  $escaped=$script.Replace('\','/').Replace('"','\"')
  if($Phase-eq'combined'){$lines.Add('dofile("'+$escaped+'")')}
  else{$lines.Add('assert(loadfile("'+$escaped+'"))("'+$Phase+'")')}
 }
 [IO.File]::WriteAllText($scriptPath,($lines-join "`n")+"`n",[Text.UTF8Encoding]::new($false))
 $scheduled=[pscustomobject]@{index=[int]$Batch.index;execution_unit='independent_work_items';work_item_id_min=$first;work_item_id_max=$last;count=[int]$Batch.count}
 return [pscustomobject]@{
  name=('ip_prism_{0}_batch_{1:D4}'-f$Phase,[int]$Batch.index);scheduler_batch=$scheduled
  file_path=$SimionExe;working_directory=$directory;environment=@{}
  stdout=(Join-Path $package.log_dir ('{0}_batch_{1:D4}.log'-f$Phase,[int]$Batch.index))
  stderr=(Join-Path $package.log_dir ('{0}_batch_{1:D4}.stderr.log'-f$Phase,[int]$Batch.index))
  argument_list=[string[]]@('--nogui','--noprompt','lua',$scriptPath)
 }
}

function Invoke-StudyDispatchPhase {
 param([Parameter(Mandatory)][ValidateSet('combined','build','fly','assemble')][string]$Phase)
 $build=$Phase-eq'build'
 $request=Join-Path $package.input_dir $(if($build){'simion_build_dispatch_request.json'}else{'simion_dispatch_request.json'})
 $prefix=if($build){'simion_build'}else{'simion'}
 $profiles=Join-Path $package.result_dir ($prefix+'_resource_profiles.json')
 $dispatch=Join-Path $package.result_dir ($prefix+'_repository_dispatch_plan.json')
 $usage=Join-Path $package.result_dir ($prefix+'_batch_resource_usage.json')
 Invoke-StudyPython -Arguments @('-m','common.simion.resource_profile','discover','--runs-root',(Join-Path $projectArtifacts 'runs'),'--output',$profiles)
 Invoke-StudyPython -Arguments @('-m','common.simion.resource_scheduler','--request',$request,'--profiles',$profiles,'--output',$dispatch)
 $plan=Get-Content -LiteralPath $dispatch -Raw|ConvertFrom-Json -Depth 40
 $expected=if($build){$study.build_cases.Count}else{$study.cases.Count}
 if($plan.dispatch_unit-ne'independent_work_items'-or[int]$plan.work_item_count-ne$expected){throw 'Dispatch identity differs from complete phase work items.'}
 $formalIndex=$null
 $script:existing=@()
 if($plan.estimation.kind-eq'formal_first_batch_observation'){
  $first=$plan.waves[0].batches[0];$formalIndex=[int]$first.index
  $completeObservation=$Phase-ne'combined'
  if($completeObservation-and$study.dispatch_policy.first_formal_observation-ne'wait_for_natural_completion'){
   throw 'Prepared contour dispatch must observe the complete largest-field formal case.'
  }
  $formal=Start-ObservedFormalProcess -DispatchPlanPath $dispatch -ProcessSpecification (New-StudyProcessSpecification $first $Phase) `
   -WaitForNaturalCompletionAfterObservation:$completeObservation
  $script:existing=@($formal.process_record)
  if($formal.resource_budget_exceeded-or($formal.process_record.completed-and(-not$formal.completed_naturally-or[int]$formal.exit_code-ne0))){throw "Formal first local $Phase work item failed."}
  $adaptive=@('-m','common.simion.resource_scheduler','--request',$request,'--profiles',$profiles,'--output',$dispatch,
   '--observed-formal-peak-bytes',"$($formal.observed_peak_process_tree_working_set_bytes)",
   '--observed-formal-cpu-percent',"$($formal.observed_process_cpu_percent)",
   '--observed-background-cpu-percent',"$($formal.observed_background_cpu_percent)",
   '--available-memory-bytes',"$($formal.available_memory_bytes)",
   '--total-physical-memory-bytes',"$($formal.total_physical_memory_bytes)")
  if($formal.process_record.completed){$adaptive+='--first-batch-completed'}
  Invoke-StudyPython -Arguments $adaptive
  $plan=Get-Content -LiteralPath $dispatch -Raw|ConvertFrom-Json -Depth 40
 }
 $pending=@($plan.waves|ForEach-Object{$_.batches}|Where-Object{$null-eq$formalIndex-or[int]$_.index-ne$formalIndex}|ForEach-Object{New-StudyProcessSpecification $_ $Phase})
 $wave=Invoke-ResourceBudgetedProcesses -DispatchPlanPath $dispatch -RunDir $run -UsagePath $usage -ProcessSpecifications $pending -ExistingProcessRecords $script:existing
 if($wave.resource_budget_exceeded-or@($wave.processes|Where-Object{[int]$_.exit_code-ne0}).Count){throw "Local $Phase dispatch failed; original logs retained."}
 Complete-ResourceUsage -RunDir $run -UsagePath $usage|Out-Null
 $script:existing=@()
}
$capacity=$null;$package=$null;$lease=$null;$succeeded=$false;$stage='capacity_startup'
$existing=@();$savedPythonPath=$env:PYTHONPATH;$frozenLocation=$false
$env:PYTHONPATH=$repoRoot
Push-Location $repoRoot
try {
 $protected=@($contract)
 if($author.role-eq'ip_prism_local_replay_package'){$protected+=@($author.cases|ForEach-Object{[IO.Path]::GetFullPath([string]$_.source_run)})}
 if($author.role-eq'ip_prism_contour_focus_experiment'){
  $protected+=@($author.field_sources.PSObject.Properties.Value|Where-Object{$_.action-eq'reuse'}|ForEach-Object{[IO.Path]::GetFullPath([string]$_.source_run)})
 }
 $capacity=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunDirectory (Join-Path $projectArtifacts "runs/$RunId") -CommittedNewBytes $commitment -ProtectedPaths $protected
 $package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $projectArtifacts -RunId $RunId `
  -Project $projectId -Mode ip_prism_distance_study -Software @('SIMION 2020','Python 3.11') `
  -RetentionContractEnabled -RetentionClass solver_review -RetentionReason 'Retain local IP/Prism fields, all mother-cohort losses and phase-space diagnostics; no full analyzer flight' -CapacityLedgerLifecycleEnabled
 $run=[string]$package.run_dir
 Copy-VerifiedRunInput $PSCommandPath (Join-Path $package.input_dir 'run_ip_prism_distance_study.ps1')|Out-Null
 $stage='prepare_local_study'
 Invoke-StudyPython -Arguments @('-m',$module,'prepare','--run',$run,'--contract',$contract)
 $study=Get-Content -LiteralPath (Join-Path $package.input_dir 'resolved_study.json') -Raw|ConvertFrom-Json -Depth 60
 if([long]$study.committed_new_bytes-ne$commitment){throw 'Prepared study changed the declared capacity commitment.'}
 $configuration=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
 foreach($file in Get-ChildItem -LiteralPath $package.input_dir -Recurse -File){$configuration.inputs[$file.FullName]=$file.FullName}
 Write-RunJson -Path $package.run_config -Depth 60 -Value $configuration
 $frozenCode=Join-Path $package.input_dir 'code'
 if(-not(Test-Path -LiteralPath $frozenCode -PathType Container)){throw 'Study preparation did not freeze its Python source closure.'}
 # Current-directory imports otherwise shadow PYTHONPATH, even when the source
 # closure has been frozen. All execution and analysis consume the run closure.
 $env:PYTHONPATH=$frozenCode
 Push-Location $run
 $frozenLocation=$true
 # Unique fields are refined once. Fly-only work items then share their
 # ordinary PA without saving it; the public scheduler learns each phase.
 $lease=Enter-HostExecutionLease -Role SIMION -Stage pa_refine
 if($study.role-eq'resolved_ip_prism_local_replay_package'){
  $stage='private_local_workbench_assembly_no_refine_no_fly'
  Invoke-StudyDispatchPhase -Phase assemble
 }elseif($study.role-eq'resolved_ip_prism_contour_focus_study'){
  $stage='local_unique_field_build'
  if($study.build_cases.Count-gt0){Invoke-StudyDispatchPhase -Phase build}
  $lease=Update-HostResourceStage -Lease $lease -Stage postprocess -Budget (Get-HostResourceBudget -Role SIMION -Stage postprocess) -RetainedMemoryBytes 0
  $stage='native_field_payload_validation'
  Invoke-StudyPython -Arguments @('-m',$module,'validate-fields','--run',$run)
  $lease=Update-HostResourceStage -Lease $lease -Stage flight -Budget (Get-HostResourceBudget -Role SIMION -Stage flight) -RetainedMemoryBytes 0
  $stage='local_fixed_cohort_flight'
  Invoke-StudyDispatchPhase -Phase fly
 }else{
  $stage='local_native_field_and_flight'
  Invoke-StudyDispatchPhase -Phase combined
 }
 $lease=Update-HostResourceStage -Lease $lease -Stage postprocess -Budget (Get-HostResourceBudget -Role SIMION -Stage postprocess) -RetainedMemoryBytes 0
 $stage='automatic_local_diagnostics'
 Invoke-StudyPython -Arguments @('-m',$module,'analyze','--run',$run)
 $succeeded=$true
 Write-Output "IP_PRISM_DISTANCE_STUDY=PASS RUN=$run GUI=False FULL_ANALYZER=False"
} catch {
 # A parent-stage failure does not make an already admitted solver unsafe.
 # Stop launching new work by leaving the dispatch path, then retain its natural terminal evidence.
 foreach($record in @($existing)){
  if($record.active-and-not$record.process.HasExited){
   Write-Warning "IP/Prism formal worker $($record.root_process_id) has not reported a native failure; awaiting natural completion."
   $record.process.WaitForExit()
  }
 }
 if($null-ne$package){Write-RunJson -Path $package.summary -Value @{schema_version=1;role='ip_prism_distance_study_summary';status='failed';stage=$stage;reason=$_.Exception.Message;gui_executed=$false;full_analyzer_flight_executed=$false}}
 throw
} finally {
 try {
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $(if($succeeded){'success'}else{'failed'}) -RunId $RunId;$lease=$null}
  if($null-ne$package){
   $null=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
   Invoke-StudyPython -Arguments @('-m',$module,'publish-manifest','--run',$run,'--status',$(if($succeeded){'success'}else{'failed'}))
   Invoke-StudyPython -Arguments @('-m','common.contracts.verify_run_manifest',(Join-Path $run 'run_manifest.json'),'--require-status',$(if($succeeded){'success'}else{'failed'}),'--require-project',$projectId)
  }
  if($null-ne$capacity){Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity|Out-Null;$capacity=$null}
  if($null-ne$package){Invoke-StudyPython -Arguments @('-m','common.contracts.run_capacity_lifecycle','--action','seal-stopped-payload','--artifact-root',$artifactRoot,'--run-config',$package.run_config,'--owner',$projectId,'--confirm-writing-stopped','--retention-reason','Retain local case fields and complete diagnostics for reproducibility')}
 } finally {
  if($null-ne$capacity){Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity|Out-Null}
  $env:PYTHONPATH=$savedPythonPath
  if($frozenLocation){Pop-Location}
  Pop-Location
 }
}
