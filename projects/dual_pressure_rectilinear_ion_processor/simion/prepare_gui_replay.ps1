[CmdletBinding()]
param(
 [Parameter(Mandatory)][string]$RunId,
 [Parameter(Mandatory)][string]$BaselineRun,
 [ValidateSet(1,2)][int]$RepeatFlyCount=1,
 [string]$PythonExe=''
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$repoRoot=(Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
. (Join-Path $repoRoot 'common/require_powershell7.ps1')
. (Join-Path $repoRoot 'common/contracts/run_artifact_support.ps1')
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
 & $PythonExe -m common.contracts.verify_run_manifest $sourceManifest --require-status $manifest.status --require-project dual_pressure_rectilinear_ion_processor --require-local-run-config
 if($LASTEXITCODE-ne0){throw 'Baseline manifest integrity verification failed'}
 $profileRegistry=Get-Content -LiteralPath (Join-Path $sourceRun 'inputs/execution_profiles.json') -Raw -Encoding UTF8|ConvertFrom-Json
 $profiles=@($profileRegistry.profiles|Where-Object{$_.profile_id-eq'native_functional'})
 if($profiles.Count-ne1){throw 'Baseline must freeze exactly one native_functional execution profile'}
 $profile=$profiles[0]
 if($profile.retention_class-ne'solver_review'){throw 'GUI native evidence requires baseline solver_review retention'}
 $baselineModel=Get-Content (Join-Path $sourceRun 'inputs/resolved_model.json') -Raw|ConvertFrom-Json
 $nativeDirectory=$baselineModel.native_field.directory
 $familyBytes=[long]0
 foreach($suffix in @('#')+@(0..15|ForEach-Object{"$_"})+@('-surf')){
  $familyBytes+=(Get-Item -LiteralPath (Join-Path $nativeDirectory "processor.pa$suffix")).Length
 }
 # Clone the entire PA family. r07 measured 344MB/N10 for one Fly and 714MB
 # for two runs in one Fly'm; snapshots add two CSVs per repeat.
 $guiCommitted=[long]($familyBytes+[Math]::Max(512MB,([long]$baselineModel.source.particle_count*42MB*$RepeatFlyCount+128MB)))
 $capacity=Enter-ArtifactWorkflowCapacitySession -Python $PythonExe -RepoRoot $repoRoot -ArtifactRoot $artifacts -RunDirectory (Join-Path $projectArtifacts "runs/$RunId") -CommittedNewBytes $guiCommitted -ProtectedPaths @($sourceRun)
 $package=New-RunPackage -Python $PythonExe -RepoRoot $repoRoot -ArtifactRoot $projectArtifacts -RunId $RunId -Project dual_pressure_rectilinear_ion_processor -Mode native_gui_replay -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass solver_review -RetentionReason 'Retain native field and independent GUI replay evidence for manual Fly comparison' -CapacityLedgerLifecycleEnabled -AdditionalDirectories @('simion')
 & $PythonExe -m projects.dual_pressure_rectilinear_ion_processor.analysis.functional prepare-replay --run $package.run_dir --baseline-run $sourceRun --repeat-fly-count $RepeatFlyCount
 if($LASTEXITCODE-ne0){throw 'GUI replay input preparation failed'}
 $guiBudget=Join-Path $package.input_dir 'gui_execution_budget.json'
 Write-RunJson -Path $guiBudget -Value @{schema_version=1;committed_new_bytes=$guiCommitted;native_family_bytes=$familyBytes;basis='Full independent native family + max(512MiB,N*42MiB*FlyCount+128MiB margin), based on measured r07 one/two-Fly retained trajectory and CSV bytes; later sessions reserve only remaining growth'}
 $budgetPath=Join-Path $package.input_dir 'resource_budget.json'
 $budget=Get-Content $budgetPath -Raw|ConvertFrom-Json -AsHashtable
 $budget.limits.transient_run_directory_bytes=$guiCommitted
 Write-RunJson -Path $budgetPath -Value $budget
 $runConfig=Get-Content $package.run_config -Raw|ConvertFrom-Json -AsHashtable
 $runConfig.inputs.gui_execution_budget=$guiBudget
 Write-RunJson -Path $package.run_config -Value $runConfig
 $planPath=Join-Path $package.input_dir 'gui_replay_plan.json'
 if(-not(Test-Path -LiteralPath $planPath -PathType Leaf)){throw 'GUI replay preparation did not publish its frozen plan'}
 Write-RunJson -Path $package.summary -Value @{schema_version=1;role='ion_processor_gui_replay_summary';status='gui_replay_prepared';baseline_run=$sourceRun;gui_fly_completed=$false;trajectory_equivalence_verified=$false;next_action='Build the independent workbench serially, open it in SIMION, manually Fly, then finalize-replay and compare'}
 $outputs=@(Get-ChildItem -LiteralPath $package.run_dir -Recurse -File|Where-Object{$_.Name-notin@('run_manifest.json','run_config.json')-and-not$_.Name.StartsWith('.')}|ForEach-Object{$_.FullName})
 Write-VerifiedRunManifest -Python $PythonExe -RepoRoot $repoRoot -RunConfig $package.run_config -Status checkpoint -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
 $prepared=$true
 Write-Output "GUI_REPLAY=PREPARED RUN=$($package.run_dir) PLAN=$planPath"
 Write-Output 'NEXT=Build simion/build_gui_workbench.lua in the serial SIMION queue; open the resulting GUI IOB and manually Fly with retained trajectories.'
 Write-Output 'FINALIZE=Use functional finalize-replay after manual Fly; compare against the frozen baseline before publishing a terminal manifest.'
} catch {
 if($null-ne$package-and-not$prepared){Complete-FailedRun -Python $PythonExe -RepoRoot $repoRoot -RunConfig $package.run_config -Summary $package.summary -SummaryRole ion_processor_gui_replay_failed -Reason $_.Exception.Message -Software @('SIMION 2020','Python 3.11')}
 throw
} finally {
 if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $(if($prepared){'success'}else{'failed'}) -RunId $RunId}
 if($null-ne$capacity){Exit-ArtifactWorkflowCapacitySession -Python $PythonExe -RepoRoot $repoRoot -Session $capacity|Out-Null}
 $env:PYTHONPATH=$savedPythonPath
 Pop-Location
}
