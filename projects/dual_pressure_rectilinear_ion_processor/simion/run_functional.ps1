[CmdletBinding()]
param([Parameter(Mandatory)][string]$RunId,[string]$SimionExe='',[string]$NativeFieldRun='',
 [ValidateSet('functional','exploration')][string]$SourceProfile='functional')
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$repoRoot=(Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
. (Join-Path $repoRoot 'common/require_powershell7.ps1')
. (Join-Path $repoRoot 'common/contracts/run_artifact_support.ps1')
. (Join-Path $repoRoot 'common/multipole/resource_budget_support.ps1')
$python=Join-Path $repoRoot '.venv/Scripts/python.exe'
if(-not $SimionExe){$SimionExe=Join-Path $env:ProgramFiles 'SIMION-2020/simion.exe'}
if(-not(Test-Path -LiteralPath $SimionExe)){throw 'SIMION 2020 executable missing'}
$profile=(Get-Content (Join-Path $projectRoot 'config/execution_profiles.json') -Raw|ConvertFrom-Json).profiles[0]
$committedNewBytes=[long]$profile.committed_new_bytes
if($NativeFieldRun){
 $sourceFile=$(if($SourceProfile-eq'exploration'){'source_exploration.json'}else{'source.json'})
 $count=(Get-Content (Join-Path $projectRoot "config/$sourceFile") -Raw|ConvertFrom-Json).particle_count
 $committedNewBytes=[long][Math]::Max(2GB,([long]$count*50MB+256MB))
}
$artifacts=Join-Path $workspaceRoot 'artifacts'
$projectArtifacts=Join-Path $artifacts 'projects/dual_pressure_rectilinear_ion_processor'
$capacity=$null;$package=$null;$lease=$null;$finished=$false;$runSucceeded=$false
$savedPythonPath=$env:PYTHONPATH;$env:PYTHONPATH=$repoRoot
Push-Location $repoRoot
try {
 $protected=@();if($NativeFieldRun){$NativeFieldRun=(Resolve-Path -LiteralPath $NativeFieldRun).Path;$protected=@($NativeFieldRun)}
 $capacity=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifacts -RunDirectory (Join-Path $projectArtifacts "runs/$RunId") -CommittedNewBytes $committedNewBytes -ProtectedPaths $protected
 $package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $projectArtifacts -RunId $RunId -Project dual_pressure_rectilinear_ion_processor -Mode native_electrode_functional -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass $profile.retention_class -RetentionReason $profile.retention_reason -CapacityLedgerLifecycleEnabled -AdditionalDirectories @('simion')
 $run=$package.run_dir;$solver=Join-Path $run 'simion'
 $prepareArguments=@('-m','projects.dual_pressure_rectilinear_ion_processor.analysis.functional','prepare','--run',$run,'--simion-dir',(Split-Path -Parent $SimionExe),'--source-profile',$SourceProfile)
 if($NativeFieldRun){$prepareArguments+=@('--native-field-run',$NativeFieldRun)}
 & $python @prepareArguments
 if($LASTEXITCODE-ne0){throw 'Input preparation failed'}
 Copy-VerifiedRunInput (Join-Path $projectRoot 'config/execution_profiles.json') (Join-Path $package.input_dir 'execution_profiles.json')|Out-Null
 $budget=Join-Path $package.input_dir 'resource_budget.json'
 $profile.limits.transient_run_directory_bytes=$committedNewBytes
 Write-RunJson -Path $budget -Value @{schema_version=1;limits=$profile.limits;committed_new_bytes=$committedNewBytes;capacity_basis=$(if($NativeFieldRun){'Verified external PA reference; max(2GiB,N*50MiB+256MiB) retained-trajectory forecast'}else{'Full native family plus retained trajectories; execution profile forecast'})}
 $config=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
 $config.inputs.execution_profiles=Join-Path $package.input_dir 'execution_profiles.json'
 $config.inputs.resource_budget=$budget
 Write-RunJson -Path $package.run_config -Value $config
 $lease=Enter-HostExecutionLease -Role SIMION -Stage prepare
 $numerics=Get-Content (Join-Path $package.input_dir 'numerics.json') -Raw|ConvertFrom-Json
 $commands=@(
  @{name='gem';stage='prepare';arguments=@('--nogui','--noprompt','gem2pa','processor.gem','processor.pa#')},
  @{name='refine';stage='pa_refine';arguments=@('--nogui','--noprompt','refine',"--convergence=$($numerics.refine_convergence_v)",'processor.pa#')},
  @{name='workbench';stage='prepare';arguments=@('--nogui','--noprompt','lua',(Join-Path $solver 'build_workbench.lua'))},
  @{name='potential_audit';stage='prepare';arguments=@('--nogui','--noprompt','lua',(Join-Path $solver 'probe_native_field.lua'))},
  @{name='flight';stage='flight';arguments=@('--nogui','--noprompt','fly','--trajectory-quality',"$($numerics.trajectory_quality)",'--particles','processor.fly2','--programs','1','--retain-trajectories','1','processor.iob')}
 )
 if($NativeFieldRun){$commands=@($commands|Where-Object{$_.name-notin@('gem','refine')})}
 Copy-VerifiedRunInput (Join-Path $solver 'runtime.lua') (Join-Path $solver 'processor.lua')|Out-Null
 foreach($command in $commands){
  $lease=Update-HostResourceStage -Lease $lease -Stage $command.stage -Budget (Get-HostResourceBudget -Role SIMION -Stage $command.stage) -RetainedMemoryBytes 0
  Write-Output "ION_PROCESSOR_STAGE=$($command.name) RUN=$RunId"
  $result=Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget -RunDir $run -UsagePath (Join-Path $package.result_dir "$($command.name)_resource_usage.json") -FilePath $SimionExe -ArgumentList $command.arguments -WorkingDirectory $solver -RedirectStandardOutput (Join-Path $package.log_dir "$($command.name).log") -RedirectStandardError (Join-Path $package.log_dir "$($command.name).stderr.log")
  if($result.exit_code-ne0){throw "SIMION $($command.name) failed: $($result.exit_code)"}
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
   $outputs=@(Get-ChildItem -LiteralPath $package.run_dir -Recurse -File|Where-Object{$_.Name-notin@('run_manifest.json','run_config.json')-and-not$_.Name.StartsWith('.')}|ForEach-Object{$_.FullName})
   $status=$(if($runSucceeded){'success'}else{'failed'})
   Write-RunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Status $status -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
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
