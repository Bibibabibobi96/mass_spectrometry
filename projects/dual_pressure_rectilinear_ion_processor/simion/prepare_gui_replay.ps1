[CmdletBinding()]
param(
 [Parameter(Mandatory)][string]$RunId,
 [Parameter(Mandatory)][string]$BaselineRun,
 [ValidateSet(1,2)][int]$RepeatFlyCount=1,
 [string]$PythonExe='',
 [string]$SimionExe=''
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$repoRoot=(Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
. (Join-Path $repoRoot 'common/require_powershell7.ps1')
. (Join-Path $repoRoot 'common/contracts/run_artifact_support.ps1')
. (Join-Path $repoRoot 'common/resource_budget_support.ps1')
if(-not $PythonExe){$PythonExe=Join-Path $repoRoot '.venv/Scripts/python.exe'}
$sourceRun=(Resolve-Path -LiteralPath $BaselineRun).Path
$sourceManifest=Join-Path $sourceRun 'run_manifest.json'
if(-not(Test-Path -LiteralPath $sourceManifest -PathType Leaf)){throw 'Explicit baseline manifest is missing'}
$manifest=Get-Content -LiteralPath $sourceManifest -Raw -Encoding UTF8|ConvertFrom-Json
if($manifest.project-ne'dual_pressure_rectilinear_ion_processor'-or$manifest.status-notin@('success','failed')){
 throw 'GUI replay requires a terminal run of this project; failed physical acceptance is allowed only with complete solver evidence'
}
$artifacts=Join-Path $workspaceRoot 'artifacts'
$projectArtifacts=Join-Path $artifacts 'projects/dual_pressure_rectilinear_ion_processor'
$capacity=$null;$package=$null;$lease=$null;$prepared=$false
$savedPythonPath=$env:PYTHONPATH;$env:PYTHONPATH=$repoRoot
Push-Location $repoRoot
try {
 $lease=Enter-HostExecutionLease -Role GATE -Stage prepare
 & $PythonExe -c 'import sys; from pathlib import Path; from projects.dual_pressure_rectilinear_ion_processor.analysis.gui_replay import validate_baseline_for_private_gui; validate_baseline_for_private_gui(Path(sys.argv[1]))' $sourceRun
 if($LASTEXITCODE-ne0){throw 'Baseline lightweight consumer projection or retirement verification failed'}
 $profileRegistry=Get-Content -LiteralPath (Join-Path $sourceRun 'inputs/execution_profiles.json') -Raw -Encoding UTF8|ConvertFrom-Json
 $profiles=@($profileRegistry.profiles|Where-Object{$_.profile_id-eq'native_functional'})
 if($profiles.Count-ne1){throw 'Baseline must freeze exactly one native_functional execution profile'}
 $profile=$profiles[0]
 if(($profile.native_field_query_memory_bytes-isnot[long]-and$profile.native_field_query_memory_bytes-isnot[int])-or$profile.native_field_query_memory_bytes-le0){throw 'Native query memory declaration must be positive integer bytes'}
 if($profile.retention_class-ne'solver_review'){throw 'GUI native evidence requires baseline solver_review retention'}
 # This reservation covers preparation only; no Fly/trajectory growth is included.
 $guiForecast=$(if($profile.PSObject.Properties.Name-contains'gui_preparation_committed_new_bytes'){$profile.gui_preparation_committed_new_bytes}else{$profile.committed_new_bytes})
 if($guiForecast-is[bool]-or$guiForecast-isnot[valuetype]-or[long]$guiForecast-le0){throw 'Baseline profile GUI preparation forecast must be a positive byte budget'}
 $guiCommitted=[long]$guiForecast
 if(-not$SimionExe){$SimionExe=Join-Path $env:ProgramFiles 'SIMION-2020/simion.exe'}
 if(-not(Test-Path -LiteralPath $SimionExe -PathType Leaf)){throw 'SIMION executable missing for private GUI field build'}
 $capacity=Enter-ArtifactWorkflowCapacitySession -Python $PythonExe -RepoRoot $repoRoot -ArtifactRoot $artifacts -RunDirectory (Join-Path $projectArtifacts "runs/$RunId") -CommittedNewBytes $guiCommitted -ProtectedPaths @($sourceRun)
 $package=New-RunPackage -Python $PythonExe -RepoRoot $repoRoot -ArtifactRoot $projectArtifacts -RunId $RunId -Project dual_pressure_rectilinear_ion_processor -Mode native_gui_replay -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass solver_review -RetentionReason 'Retain new private native field and IOB for user Load/Fly; trajectory comparison unverified' -CapacityLedgerLifecycleEnabled -AdditionalDirectories @('simion')
 & $PythonExe -m projects.dual_pressure_rectilinear_ion_processor.analysis.functional prepare-replay --run $package.run_dir --baseline-run $sourceRun --repeat-fly-count $RepeatFlyCount
 if($LASTEXITCODE-ne0){throw 'GUI replay input preparation failed'}
 $guiBudget=Join-Path $package.input_dir 'gui_execution_budget.json'
 Write-RunJson -Path $guiBudget -Value @{schema_version=1;committed_new_bytes=$guiCommitted;basis='Baseline frozen native_functional GUI preparation forecast (legacy: full functional forecast); private fractional field, logs and IOB only';user_fly_trajectory_growth_reserved=$false;user_fly_notice='Manual Fly can create multi-GiB retained trajectories beyond this preparation reservation'}
 $limits=$profile.limits.PSObject.Copy()
 $limits.transient_run_directory_bytes=$guiCommitted
 $runConfig=Get-Content $package.run_config -Raw|ConvertFrom-Json -AsHashtable
 $runConfig.inputs.gui_execution_budget=$guiBudget
 Write-RunJson -Path $package.run_config -Value $runConfig
 Exit-HostExecutionLease -Lease $lease -Outcome success -RunId $RunId
 $lease=$null
 $lease=Enter-HostExecutionLease -Role SIMION -Stage prepare
 $solver=Join-Path $package.run_dir 'simion'
 $numerics=Get-Content (Join-Path $package.input_dir 'numerics.json') -Raw|ConvertFrom-Json
 $commands=@(
  @{name='gem';stage='prepare';arguments=@('--nogui','--noprompt','gem2pa','processor.gem','processor.pa#')},
  @{name='refine';stage='pa_refine';arguments=@('--nogui','--noprompt','refine',"--convergence=$($numerics.refine_convergence_v)",'processor.pa#')},
  @{name='workbench';stage='prepare';arguments=@('--nogui','--noprompt','lua',(Join-Path $solver 'build_gui_workbench.lua'))}
 )
 if(Test-Path (Join-Path $solver 'probe_native_field.lua')){
  $commands+=@{name='potential_audit';stage='prepare';arguments=@('--nogui','--noprompt','lua',(Join-Path $solver 'probe_native_field.lua'))}
 }
 foreach($command in $commands){
  $stageBudget=Get-HostResourceBudget -Role SIMION -Stage $command.stage
  if($command.name-eq'potential_audit'){$stageBudget.memory_bytes=[long]$profile.native_field_query_memory_bytes}
  $lease=Update-HostResourceStage -Lease $lease -Stage $command.stage -Budget $stageBudget -RetainedMemoryBytes 0
  $result=Invoke-ResourceBudgetedProcess -Limits $limits -RunDir $package.run_dir -UsagePath (Join-Path $package.result_dir "$($command.name)_resource_usage.json") -FilePath $SimionExe -ArgumentList $command.arguments -WorkingDirectory $solver -RedirectStandardOutput (Join-Path $package.log_dir "$($command.name).log") -RedirectStandardError (Join-Path $package.log_dir "$($command.name).stderr.log")
  if($result.exit_code-ne0){throw "Private GUI preparation stage failed: $($command.name)"}
 }
 & $PythonExe -c 'import sys; from pathlib import Path; from projects.dual_pressure_rectilinear_ion_processor.analysis.gui_replay import record_prepared_native_family; record_prepared_native_family(Path(sys.argv[1]))' $package.run_dir
 if($LASTEXITCODE-ne0){throw 'Private GUI native identity publication failed'}
 $planPath=Join-Path $package.input_dir 'gui_replay_plan.json'
 if(-not(Test-Path -LiteralPath $planPath -PathType Leaf)){throw 'GUI replay preparation did not publish its frozen plan'}
 Write-RunJson -Path $package.summary -Value @{schema_version=1;role='ion_processor_gui_replay_summary';status='gui_replay_prepared';baseline_run=$sourceRun;field_construction='new_private_refine_from_frozen_GEM';gui_fly_completed=$false;trajectory_equivalence_verified=$false;next_action='User loads the prepared processor.iob and manually Fly; preparation did not execute Fly';user_fly_trajectory_growth_reserved=$false}
 $prepared=$true
 Write-Output "GUI_REPLAY=PREPARED RUN=$($package.run_dir) PLAN=$planPath"
 Write-Output 'NEXT=User Load simion/processor.iob and Fly; no automatic Fly or visual review was performed.'
 Write-Output "CAPACITY=$guiCommitted bytes from baseline profile covers preparation only; retained trajectories from user Fly may add multi-GiB."
} catch {
 if($null-ne$package-and-not$prepared){Write-RunJson -Path $package.summary -Value @{schema_version=1;role='ion_processor_gui_replay_failed';status='failed';reason=$_.Exception.Message;gui_fly_completed=$false}}
 throw
} finally {
 if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $(if($prepared){'success'}else{'failed'}) -RunId $RunId}
 try {
  if($null-ne$package){
   $null=Apply-RunArtifactRetention -Python $PythonExe -RepoRoot $repoRoot -RunConfig $package.run_config
   $outputs=@(Get-ChildItem -LiteralPath $package.run_dir -Recurse -File|Where-Object{$_.Name-notin@('run_manifest.json','run_config.json')-and-not$_.Name.StartsWith('.')}|ForEach-Object{$_.FullName})
   $status=$(if($prepared){'checkpoint'}else{'failed'})
   Write-RunManifest -Python $PythonExe -RepoRoot $repoRoot -RunConfig $package.run_config -Status $status -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
   & $PythonExe -m common.contracts.verify_run_manifest (Join-Path $package.run_dir 'run_manifest.json') --require-status $status --require-project dual_pressure_rectilinear_ion_processor
   if($LASTEXITCODE-ne0){throw 'Private GUI manifest verification failed'}
  }
  if($null-ne$capacity){Exit-ArtifactWorkflowCapacitySession -Python $PythonExe -RepoRoot $repoRoot -Session $capacity|Out-Null;$capacity=$null}
  if($null-ne$package){
   & $PythonExe -m common.contracts.run_capacity_lifecycle --action seal-stopped-payload --artifact-root $artifacts --run-config $package.run_config --owner dual_pressure_rectilinear_ion_processor --confirm-writing-stopped --retention-reason 'New private fractional field and IOB prepared for user Load/Fly'
   if($LASTEXITCODE-ne0){throw 'Private GUI payload sealing failed'}
  }
 } finally {
  if($null-ne$capacity){Exit-ArtifactWorkflowCapacitySession -Python $PythonExe -RepoRoot $repoRoot -Session $capacity|Out-Null}
  $env:PYTHONPATH=$savedPythonPath
  Pop-Location
 }
}
