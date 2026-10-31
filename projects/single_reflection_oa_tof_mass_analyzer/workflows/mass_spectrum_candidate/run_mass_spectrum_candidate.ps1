[CmdletBinding(DefaultParameterSetName='Run')]
param(
  [string]$RunId = ((Get-Date -Format 'yyyyMMdd_HHmmss') + '__sim__cross__mass-spectrum__five-mass'),
  [Parameter(ParameterSetName='Run')][string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [Parameter(ParameterSetName='Run')][Alias('Resume')][switch]$ResumeAfterComsol,
  [Parameter(Mandatory,ParameterSetName='Analyze')][switch]$ReanalyzeOnly,
  [Parameter(Mandatory,ParameterSetName='Analyze')][string]$SourceRunPath,
  [Parameter(ParameterSetName='Analyze')][string]$SourceStoppedReceiptPath='',
  [Parameter(Mandatory,ParameterSetName='Analyze')][ValidateRange(1,[long]::MaxValue)][long]$AnalysisNewBytes,
  [Parameter(ParameterSetName='Analyze')][Parameter(ParameterSetName='Resume')][string]$ResultPath='',
  [Parameter(Mandatory,ParameterSetName='Resume')][switch]$ResumeFinalization,
  [Parameter(ParameterSetName='Analyze')][Parameter(ParameterSetName='Resume')][string]$PythonExe=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# Reanalysis consumes only a sealed parent's sufficient scientific records.
# Its own run/Result never replaces that parent's publication.
if($ReanalyzeOnly-or$ResumeFinalization){
  $analysisProject='single_reflection_oa_tof_mass_analyzer'
  $analysisRepo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../../..'))
  $analysisPython=if($PythonExe){(Resolve-Path -LiteralPath $PythonExe).Path}elseif($env:SIMULATION_PYTHON_EXE){
    (Resolve-Path -LiteralPath $env:SIMULATION_PYTHON_EXE).Path
  }else{Join-Path $analysisRepo '.venv/Scripts/python.exe'}
  . (Join-Path $analysisRepo 'common/paths/workspace_paths.ps1')
  . (Join-Path $analysisRepo 'common/contracts/run_artifact_workflow.ps1') -ResultPath $ResultPath -ResumeFinalization:$ResumeFinalization
  if($ResumeFinalization){
    if(-not$PSBoundParameters.ContainsKey('RunId')){throw 'ResumeFinalization requires the original analysis RunId.'}
    if(-not$ResultPath){
      $analysisPaths=Resolve-WorkspacePaths -SourceRoot $analysisRepo -Python $analysisPython
      $ResultPath=Join-Path $analysisPaths.artifact_root ('projects/'+$analysisProject+'/scratch/workflow_results/'+$RunId+'/result.json')
    }
    $priorAnalysis=Get-Content -LiteralPath $ResultPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    if($priorAnalysis.role-cne'run_artifact_workflow_result'-or-not$priorAnalysis.run_directory-or
       -not[IO.Path]::IsPathFullyQualified([string]$priorAnalysis.run_directory)-or
       (Split-Path -Leaf ([string]$priorAnalysis.run_directory))-cne$RunId){throw 'Mass-spectrum Result RunId differs.'}
    $analysisRequest=Join-Path $priorAnalysis.run_directory 'inputs/execution_request.json'
    $analysisRequestValue=Get-Content -LiteralPath $analysisRequest -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    if($analysisRequestValue.package.project-cne$analysisProject-or$analysisRequestValue.package.run_id-cne$RunId-or
       $analysisRequestValue.package.mode-cne'mass_spectrum_analysis'){throw 'Mass-spectrum Result owner differs.'}
    $analysisOutcome=Invoke-RunArtifactWorkflow -RequestPath $analysisRequest -ResultPath $ResultPath -ResumeFinalization
    if(-not$analysisOutcome.terminal_published){throw 'Mass-spectrum finalization remains incomplete.'}
    return
  }
  if(-not$PSBoundParameters.ContainsKey('RunId')){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__analysis__python__mass-spectrum'}
  $analysisPaths=Resolve-WorkspacePaths -SourceRoot $analysisRepo -Python $analysisPython
  $analysisRoot=Join-Path $analysisPaths.artifact_root ('projects/'+$analysisProject)
  $analysisRun=Join-Path $analysisRoot ('runs/'+$RunId)
  $analysisSource=(Resolve-Path -LiteralPath $SourceRunPath).Path
  if([IO.Path]::GetFullPath($analysisRun)-ieq$analysisSource-or(Split-Path -Leaf $analysisSource)-ceq$RunId){throw 'Reanalysis requires a distinct new RunId.'}
  $analysisNames=@('SIMULATION_PYTHON_EXE','PYTHONDONTWRITEBYTECODE','MASS_SPECTROMETRY_ARTIFACT_ROOT','MASS_SPECTROMETRY_EXECUTION_ROOT','MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH')
  $analysisSaved=Save-RunEnvironment -Names $analysisNames
  $analysisTimer=[Diagnostics.Stopwatch]::StartNew()
  $analysisCapacity=$null;$analysisPackage=$null;$analysisOwner=$null;$analysisLease=$null;$analysisReader=$null
  $analysisFailure=$null;$analysisCloseFailure=$null;$analysisStopped=$true;$analysisReleaseAttempted=$false
  $analysisOperations=[Collections.Generic.List[object]]::new();$analysisReleases=[Collections.Generic.List[object]]::new()
  $analysisPhase='source_admission';$analysisPrepareSeconds=0.0;$analysisStarted=0.0;$analysisUsage=$null
  $analysisModule='projects.single_reflection_oa_tof_mass_analyzer.analysis.mass_spectrum_reanalysis'
  try{
    $env:SIMULATION_PYTHON_EXE=$analysisPython;$env:PYTHONDONTWRITEBYTECODE='1'
    $env:MASS_SPECTROMETRY_ARTIFACT_ROOT=$analysisPaths.artifact_root
    $env:MASS_SPECTROMETRY_EXECUTION_ROOT=$analysisPaths.execution_root
    $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=$analysisPaths.host_resource_state_path
    $analysisReader=Enter-RunTerminalConsumptionGuard -RunDirectory $analysisSource
    $selectionArguments=@('-B','-m',$analysisModule,'select','--source',$analysisSource,'--artifact-root',$analysisPaths.artifact_root)
    if($SourceStoppedReceiptPath){$selectionArguments+=@('--stopped-receipt',$SourceStoppedReceiptPath)}
    $selectionText=Invoke-RunToolRootContext -RepoRoot $analysisRepo -Operation {
      & $analysisPython @selectionArguments
      if($LASTEXITCODE-ne0){throw 'Mass-spectrum parent records or stopped-owner evidence are insufficient; see the source admission error.'}
    }
    $analysisSelection=($selectionText-join"`n")|ConvertFrom-Json -AsHashtable -Depth 100
    $analysisReferences=@{manifest_record=$analysisSelection.manifest_record;protected_paths=@($analysisSource)}
    if($analysisSelection.stopped_receipt_record){$analysisReferences.stopped_receipt_record=$analysisSelection.stopped_receipt_record}
    $analysisCapacity=Enter-ArtifactWorkflowCapacitySession -Python $analysisPython -RepoRoot $analysisRepo -ArtifactRoot $analysisPaths.artifact_root `
      -RunDirectory $analysisRun -CommittedNewBytes $AnalysisNewBytes -Owner ('run-artifact-workflow:'+ $analysisProject+':'+$RunId) `
      -SourceReferences @($analysisReferences)
    $analysisPackage=New-RunPackage -Python $analysisPython -RepoRoot $analysisRepo -ArtifactRoot $analysisRoot -PathContext $analysisPaths `
      -RunId $RunId -Project $analysisProject -Mode mass_spectrum_analysis -Software @('Python 3.11') `
      -RetentionContractEnabled -CapacityLedgerLifecycleEnabled
    $analysisPhase='prepare'
    $selectionPath=Join-Path $analysisPackage.input_dir 'source_selection.json'
    Write-RunJson -Path $selectionPath -Value $analysisSelection -Depth 100
    $analysisBudgetPath=Join-Path $analysisPackage.input_dir 'analysis_commitment.json'
    Write-RunJson -Path $analysisBudgetPath -Value @{committed_new_bytes=$AnalysisNewBytes;authority='explicit AnalysisNewBytes';
      host_budget=(Get-HostResourceBudget -Role GATE -Stage postprocess);referenced_csv_native_new_bytes=0;
      scope='frozen analysis code and small authority, plots, metadata and public closeout; no native payload copies'} -Depth 20
    $analysisEntry=Join-Path $analysisPackage.input_dir 'run_mass_spectrum_candidate.ps1'
    $null=Copy-VerifiedRunInput -Source $PSCommandPath -Destination $analysisEntry
    $analysisOwner=Initialize-RunArtifactPowerShellOwner -Python $analysisPython -RepoRoot $analysisRepo -Package $analysisPackage `
      -CapacitySession $analysisCapacity -ResultPath $ResultPath -EntrypointPath $analysisEntry -CommitmentInputPaths @($analysisBudgetPath,$selectionPath) -Software @('Python 3.11')
    Write-Host "MASS_SPECTRUM_RESULT=$($analysisOwner.result_path)"
    $analysisCode=Join-Path $analysisPackage.input_dir 'code'
    $frozenText=Invoke-RunToolRootContext -RepoRoot $analysisRepo -Operation {
      & $analysisPython -B -m $analysisModule freeze --repo $analysisRepo --destination $analysisCode --selection $selectionPath
      if($LASTEXITCODE-ne0){throw 'Mass-spectrum analysis closure preparation failed.'}
    }
    $analysisInventory=Join-Path $analysisPackage.input_dir 'code_inventory.json'
    Write-RunJson -Path $analysisInventory -Value (($frozenText-join"`n")|ConvertFrom-Json -AsHashtable -Depth 100) -Depth 100
    $analysisConfig=Get-Content -LiteralPath $analysisPackage.run_config -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    $analysisConfig.inputs.source_selection=$selectionPath;$analysisConfig.inputs.code_inventory=$analysisInventory
    $analysisConfig.inputs.mode_config=Join-Path $analysisPackage.input_dir 'mass_spectrum.json'
    $analysisConfig.inputs.resolved_geometry=Join-Path $analysisCode ('projects/'+$analysisProject+'/config/resolved_geometry.json')
    $analysisConfig.parameters=@{reanalyze_only=$true;source_run_id=$analysisSelection.run_id;solver_native_calls=0;pa_materializations=0}
    $analysisConfig.provenance=@{parent_manifest_record=$analysisSelection.manifest_record;original_execution=$analysisSelection.execution;
      particle_source_provenance=$analysisSelection.particle_source_provenance;consumed_exports=$analysisSelection.exports}
    Write-RunJson -Atomic -Path $analysisPackage.run_config -Value $analysisConfig -Depth 100
    $analysisPrepareSeconds=$analysisTimer.Elapsed.TotalSeconds;$analysisStarted=$analysisPrepareSeconds;$analysisPhase='analysis'
    $analysisLease=Enter-HostResourceStage -StatePath $analysisPaths.host_resource_state_path -Role GATE -Stage postprocess -RunId $RunId `
      -Budget (Get-HostResourceBudget -Role GATE -Stage postprocess)
    $analysisUsage=Join-Path $analysisPackage.result_dir 'analysis_resource_usage.json'
    $analysisStdout=Join-Path $analysisPackage.log_dir 'analysis.stdout.log'
    $analysisStderr=Join-Path $analysisPackage.log_dir 'analysis.stderr.log'
    # CPython supports the persistent frozen import root. Windows process cwd
    # and this run's actual files use the existing package execution view.
    $analysisNative=Get-RunNativeExecutionContext -Package $analysisPackage -Tool 'mass-spectrum Python analysis' `
      -Paths @($selectionPath,$analysisPackage.result_dir,$analysisStdout,$analysisStderr,$analysisPackage.artifact_run_dir)
    $analysisEnvironment=@{};foreach($name in $analysisNative.environment.Keys){$analysisEnvironment[$name]=$analysisNative.environment[$name]}
    $analysisEnvironment.PYTHONDONTWRITEBYTECODE='1'
    $analysisLaunch='import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module("'+$analysisModule+'",run_name="__main__")'
    $analysisArgs=@('-I','-B','-c',$analysisLaunch,$analysisCode,'analyze','--selection',$analysisNative.projected_paths[0],'--code-root',$analysisCode,'--output',$analysisNative.projected_paths[1])
    $analysisArgs=@($analysisArgs|ForEach-Object{'"'+([string]$_).Replace('"','\"')+'"'})
    $analysisStopped=$false
    try{
      $analysisProcess=Invoke-ResourceBudgetedProcess -Limits $null -RunDir $analysisRun -UsagePath $analysisUsage -FilePath $analysisPython `
        -ArgumentList $analysisArgs -WorkingDirectory $analysisNative.projected_paths[4] -Environment $analysisEnvironment `
        -RedirectStandardOutput $analysisNative.projected_paths[2] -RedirectStandardError $analysisNative.projected_paths[3]
      $analysisStopped=$true
      $analysisObservation=@{exit_confirmed=$true;returncode=[int]$analysisProcess.exit_code;process_id=[int]$analysisProcess.root_process_id;process_started_at_utc_ticks=[long]$analysisProcess.root_process_started_at_utc_ticks}
      $analysisOperations.Add(@{operation_id='python-analysis';observation=$analysisObservation;resource_release_id='analysis'})
      if($analysisProcess.resource_budget_exceeded-or$analysisProcess.exit_code-ne0){
        $analysisDiagnostic=(Get-Content -LiteralPath (Join-Path $analysisPackage.log_dir 'analysis.stderr.log') -Tail 8)-join[Environment]::NewLine
        throw ('Candidate mass-spectrum reanalysis failed: '+$analysisDiagnostic)
      }
    }catch{
      $analysisData=$_.Exception.Data
      if($analysisData.Contains('observed_process_exit_confirmed')-and[bool]$analysisData['observed_process_exit_confirmed']-and
         $analysisData.Contains('observed_process_returncode')-and$null-ne$analysisData['observed_process_returncode']-and
         $analysisData.Contains('observed_process_id')-and$analysisData.Contains('observed_process_started_at_utc_ticks')){
        $analysisStopped=$true
        $analysisOperations.Add(@{operation_id='python-analysis';resource_release_id='analysis';observation=@{
          exit_confirmed=$true;returncode=[int]$analysisData['observed_process_returncode'];process_id=[int]$analysisData['observed_process_id'];
          process_started_at_utc_ticks=[long]$analysisData['observed_process_started_at_utc_ticks']}})
      }
      throw
    }
  }catch{$analysisFailure=$_}finally{
    try{
      if($analysisOwner){
        if($analysisStopped-and$null-ne$analysisLease){
          $analysisReleaseAttempted=$true
          $analysisRelease=Exit-HostResourceStage -Lease $analysisLease -PassThru
          if($analysisOperations.Count){Add-RunArtifactResourceRelease -ResourceReleases $analysisReleases -ReleaseId analysis -Receipt @{host_release=@{
            inherited=[bool]$analysisLease.inherited;token=[string]$analysisLease.token;result=$analysisRelease;error=$null}}}
          $analysisLease=$null
        }
        $analysisSummary=@{role='oa_tof_candidate_mass_spectrum_analysis';execution_status=$(if($analysisFailure){'failed'}else{'completed'});
          data_validity=$(if($analysisFailure){'incomplete'}else{'valid'});scientific_result=$(if($analysisFailure){'NOT_EVALUATED'}else{'candidate_diagnostic'});
          formal_gate_passed=$false;resolution_claim_allowed=$false;solver_native_calls=0;pa_materializations=0;
          source_run_directory=$analysisSource;result_path=$analysisOwner.result_path;analysis_metrics_path=(Join-Path $analysisPackage.result_dir 'mass_spectrum_metrics.json');
          failure_stage=$(if($analysisFailure){$analysisPhase}else{$null});failure_reason=$(if($analysisFailure){$analysisFailure.Exception.Message}else{$null});
          recovery_action=$(if(-not$analysisStopped){'inspect_writer_completion'}elseif($analysisFailure){'repair_analysis_and_create_new_analysis_child'}else{'none'});
          phase_timings_seconds=@{prepare=$(if($analysisStarted-gt0){$analysisPrepareSeconds}else{$analysisTimer.Elapsed.TotalSeconds});analysis=$(if($analysisStarted-gt0){$analysisTimer.Elapsed.TotalSeconds-$analysisStarted}else{0.0})};total_elapsed_seconds=$analysisTimer.Elapsed.TotalSeconds}
        $analysisOutputs=@(Get-ChildItem -LiteralPath $analysisPackage.result_dir -File|ForEach-Object FullName)
        $analysisRequired=@();if(-not$analysisFailure){$analysisRequired=@('mass_spectrum_particles.csv','mass_spectrum_summary.csv','mass_peak_shape_comparison.csv','mass_spectrum_metrics.json','mass_spectrum_comparison.png','mass_detector_landing_comparison.png'|ForEach-Object{Join-Path $analysisPackage.result_dir $_})}
        $analysisOutcome=Complete-RunArtifactPowerShellOwner -Context $analysisOwner -Status $(if($analysisFailure){'failed'}else{'success'}) `
          -Summary $analysisSummary -OutputPaths $analysisOutputs -RequiredOutputPaths $analysisRequired `
          -WriterCompletion @{operations=@($analysisOperations.ToArray());resource_releases=@($analysisReleases.ToArray())} -WritersStopped $analysisStopped -OriginalFailure $analysisFailure
        if(-not$analysisOutcome.terminal_published){throw 'Mass-spectrum analysis finalization remains incomplete.'}
        $analysisCapacity=$null
      }
    }catch{
      $analysisCloseFailure=$_
      if($analysisOwner-and-not$analysisOwner.completion_written){
        $retainedAnalysis=Get-Content -LiteralPath $analysisOwner.result_path -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
        $primaryAnalysis=if($analysisFailure){$analysisFailure}else{$analysisCloseFailure}
        $retainedAnalysis.exception=@{type=$primaryAnalysis.Exception.GetType().FullName;message=$primaryAnalysis.Exception.Message;notes=@()}
        $retainedAnalysis.secondary_errors=@(if($analysisFailure){$analysisCloseFailure.Exception.Message})
        $retainedAnalysis.status='failed';$retainedAnalysis.execution_status='finalization_failed'
        $retainedAnalysis.failure_stage=if($analysisReleaseAttempted-and$null-ne$analysisLease){'host_release'}else{'finalization'}
        $retainedAnalysis.failure_reason=$analysisCloseFailure.Exception.Message
        $retainedAnalysis.recovery_action=if($retainedAnalysis.failure_stage-eq'host_release'){'inspect_release_without_refly'}else{'inspect_finalization_evidence'}
        $retainedAnalysis.resume_action=$retainedAnalysis.recovery_action
        $retainedAnalysis.writers_confirmed=$analysisStopped
        $retainedAnalysis.terminal_published=$false;$retainedAnalysis.capacity_finalized=$false;$retainedAnalysis.lease_released=$false
        Write-RunJson -Atomic -Path $analysisOwner.result_path -Value $retainedAnalysis -Depth 64
      }
    }finally{
      try{
        if(-not$analysisOwner){
          if($analysisCapacity){$null=Exit-ArtifactWorkflowCapacitySession -Python $analysisPython -RepoRoot $analysisRepo -Session $analysisCapacity}
          if($analysisPackage){Remove-RunPackageExecutionAlias -Package $analysisPackage}
        }
        if($analysisStopped-and$null-ne$analysisLease-and-not$analysisReleaseAttempted){$null=Exit-HostResourceStage -Lease $analysisLease -PassThru}
        if($analysisStopped-and$analysisReader){$analysisReader.Dispose()}
      }catch{if($analysisFailure){$analysisFailure.Exception.Data['analysis_cleanup_error']=$_.Exception.Message}else{$analysisCloseFailure=$_}}
      finally{Restore-RunEnvironment -Names $analysisNames -Snapshot $analysisSaved}
    }
  }
  if($analysisFailure){if($analysisCloseFailure){$analysisFailure.Exception.Data['analysis_finalization_error']=$analysisCloseFailure.Exception.Message};throw $analysisFailure}
  if($analysisCloseFailure){throw $analysisCloseFailure}
  return
}


$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$python = if ($env:SIMULATION_PYTHON_EXE) { (Resolve-Path -LiteralPath $env:SIMULATION_PYTHON_EXE).Path }
  else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
. (Join-Path $repoRoot 'common/contracts/run_artifact_support.ps1')
. (Join-Path $repoRoot 'common/paths/workspace_paths.ps1')
$pathContext = Resolve-WorkspacePaths -SourceRoot $repoRoot -Python $python
$artifactRoot = Join-Path $pathContext.artifact_root 'projects/single_reflection_oa_tof_mass_analyzer'
$runDir = Join-Path $artifactRoot "runs\$RunId"
$resumeExisting = [bool]$ResumeAfterComsol
if ($resumeExisting) {
  $frozenConfigPath = Join-Path $runDir 'run_config.json'
  if (-not (Test-Path -LiteralPath $frozenConfigPath -PathType Leaf)) { throw "Resume requires the original run config: $frozenConfigPath" }
  $frozenConfig = Get-Content -LiteralPath $frozenConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
  if (-not $frozenConfig.ContainsKey('paths')) {
    throw 'Resume lacks frozen path context. ACTION=use_original_frozen_entry_or_create_new_run_with_verified_inputs'
  }
  if (@('run_id','project','mode','capacity_ledger_lifecycle' | Where-Object { -not $frozenConfig.ContainsKey($_) }).Count -or
      $frozenConfig.capacity_ledger_lifecycle -isnot [Collections.IDictionary] -or
      -not $frozenConfig.capacity_ledger_lifecycle.Contains('artifact_root')) {
    throw 'Resume lacks frozen run/capacity identity. ACTION=use_original_frozen_entry_or_create_new_run_with_verified_inputs'
  }
  $pathContext = Resolve-WorkspacePaths -SourceRoot $repoRoot -Python $python -FrozenContext $frozenConfig.paths
  $frozenArtifactRoot = Join-Path $pathContext.artifact_root 'projects/single_reflection_oa_tof_mass_analyzer'
  $frozenRun = [IO.Path]::GetFullPath((Join-Path $frozenArtifactRoot "runs\$RunId"))
  if (-not $frozenRun.Equals([IO.Path]::GetFullPath($runDir),[StringComparison]::OrdinalIgnoreCase) -or
      $frozenConfig.run_id -cne $RunId -or $frozenConfig.project -cne 'single_reflection_oa_tof_mass_analyzer' -or
      $frozenConfig.mode -cne 'mass_spectrum_candidate' -or
      [IO.Path]::GetFullPath([string]$frozenConfig.capacity_ledger_lifecycle.artifact_root) -ine $pathContext.artifact_root) {
    throw 'Resume frozen run/root/capacity identity differs.'
  }
  $artifactRoot = $frozenArtifactRoot
}
$environmentNames = @('SIMULATION_PYTHON_EXE','MASS_SPECTROMETRY_ARTIFACT_ROOT','MASS_SPECTROMETRY_EXECUTION_ROOT','MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH')
$environmentSnapshot = Save-RunEnvironment -Names $environmentNames
$hostRole = 'SIMION'
$hostExecutionLease = $null
try {
$env:SIMULATION_PYTHON_EXE = $python
$env:MASS_SPECTROMETRY_ARTIFACT_ROOT = [string]$pathContext.artifact_root
$env:MASS_SPECTROMETRY_EXECUTION_ROOT = [string]$pathContext.execution_root
$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH = [string]$pathContext.host_resource_state_path
$hostExecutionLease = Enter-HostExecutionLease -Role $hostRole -Stage prepare -StatePath $pathContext.host_resource_state_path
. (Join-Path $projectRoot 'oatof_lifecycle_preflight.ps1')
Assert-OaTofFormalAssetsReadable -ProjectRoot $projectRoot
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $RunId" }
if ($resumeExisting) {
  $inputDir = Join-Path $runDir 'inputs'
  $resultDir = Join-Path $runDir 'results'
  $logDir = Join-Path $runDir 'logs'
  if (-not (Test-Path -LiteralPath $runDir -PathType Container) -or
      -not (Test-Path -LiteralPath $resultDir -PathType Container)) {
    throw "Resume requires the existing run and result directories: $RunId"
  }
  $ionDir = Get-Item -LiteralPath (Join-Path $runDir 'ions')
  $comsolDir = Get-Item -LiteralPath (Join-Path $runDir 'comsol')
  if (-not (Test-Path -LiteralPath $inputDir -PathType Container)) {
    throw "Resume requires the existing frozen input directory: $inputDir"
  }
  $existingLifecycle = Get-Content -LiteralPath (Join-Path $runDir 'run_config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($null -eq $existingLifecycle.artifact_retention -or
      $null -eq $existingLifecycle.capacity_ledger_lifecycle -or
      -not [bool]$existingLifecycle.capacity_ledger_lifecycle.enabled) {
    throw 'Resume requires an existing governed retention and capacity-ledger lifecycle.'
  }
} else {
  if ((Test-Path -LiteralPath $runDir) -or (Test-Path -LiteralPath $resultDir)) {
    throw "Candidate mass-spectrum run already exists: $RunId"
  }
  . (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
  $package = New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -RunId $RunId -Project 'single_reflection_oa_tof_mass_analyzer' -Mode 'mass_spectrum_candidate' `
    -Software @('COMSOL 6.4','SIMION 2020','Python 3.11') -RetentionContractEnabled `
    -RetentionClass solver_review -RetentionReason 'Candidate mass-spectrum solver evidence requires review.' `
    -CapacityLedgerLifecycleEnabled -AdditionalDirectories @('ions','comsol') -PathContext $pathContext
  $runDir = $package.artifact_run_dir
  $inputDir = $package.input_dir
  $resultDir = $package.result_dir
  $logDir = $package.log_dir
  $ionDir = Get-Item -LiteralPath (Join-Path $runDir 'ions')
  $comsolDir = Get-Item -LiteralPath (Join-Path $runDir 'comsol')
}
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$lifecycleConfig = Get-Content -LiteralPath (Join-Path $runDir 'run_config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$executionAlias = $null
$runtimeAlias = $null
$runtimeRoot = $null
$runRecordComplete = $false
trap {
  if ($null -ne $runtimeAlias) {
    try { Remove-RunExecutionAlias -ExecutionAlias $runtimeAlias.execution_alias -TargetDirectory $runtimeRoot }
    catch { Write-Warning "Could not remove short formal-runtime alias: $($_.Exception.Message)" }
  }
  if ($null -ne $runtimeRoot) {
    try { Remove-OaTofFormalSimionRuntime -ArtifactRoot $artifactRoot -RuntimeRoot $runtimeRoot }
    catch { Write-Warning "Could not remove formal SIMION runtime: $($_.Exception.Message)" }
  }
  if ($null -ne $executionAlias) {
    try { Remove-RunExecutionAlias -ExecutionAlias $executionAlias.execution_alias -TargetDirectory $runDir }
    catch { Write-Warning "Could not remove short mass-spectrum execution alias: $($_.Exception.Message)" }
  }
  if (-not $runRecordComplete) {
    Write-TerminalRunRecord -RunDir $runDir -Status failed `
      -Reason $_.Exception.Message -RepoRoot $repoRoot -Python $python `
      -SummaryRole 'oa_tof_terminal_run_summary'
  }
  exit 1
}

$liveModePath = Join-Path $projectRoot 'config\modes\mass_spectrum.json'
$liveParticleCountPolicyPath = Join-Path $repoRoot 'common\contracts\particle_count_policy.json'
$modePath = Join-Path $inputDir 'mass_spectrum.json'
$resolvedPath = Join-Path $inputDir 'resolved_geometry.json'
$particleCountPolicyPath = Join-Path $inputDir 'particle_count_policy.json'
$geometryFrozenInputs = [ordered]@{}
if ($resumeExisting) {
  $resolvedPath = [IO.Path]::GetFullPath([string]$existingLifecycle.inputs.resolved_geometry)
  $frozenInputPrefix = [IO.Path]::GetFullPath($inputDir).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
  if (-not $resolvedPath.StartsWith($frozenInputPrefix,[StringComparison]::OrdinalIgnoreCase)) {
    throw 'Recorded geometry must remain within this run frozen inputs.'
  }
  foreach ($entry in $existingLifecycle.inputs.PSObject.Properties) {
    if ($entry.Name.StartsWith('geometry_freshness_')) {$geometryFrozenInputs[$entry.Name] = [string]$entry.Value}
  }
  foreach ($frozenInput in @($modePath,$resolvedPath,$particleCountPolicyPath)) {
    if (-not (Test-Path -LiteralPath $frozenInput -PathType Leaf)) {
      throw "Resume frozen input is absent: $frozenInput"
    }
  }
} else {
  Copy-Item -LiteralPath $liveModePath -Destination $modePath
  $geometrySnapshotRoot = Join-Path $inputDir 'geometry_freshness_snapshot'
  $geometrySources = [ordered]@{
    geometry_freshness_resolver = 'projects/single_reflection_oa_tof_mass_analyzer/analysis/resolve_geometry.py'
    geometry_freshness_contract = 'projects/single_reflection_oa_tof_mass_analyzer/analysis/geometry_contract.py'
    geometry_freshness_file_identity = 'common/contracts/file_identity.py'
    geometry_freshness_machine_contracts = 'common/contracts/machine_contracts.py'
    geometry_freshness_aperture = 'common/simion/aperture.py'
    geometry_freshness_simion_package = 'common/simion/__init__.py'
    geometry_freshness_grounded_shield = 'projects/rf_multipole_ion_optics/core/grounded_shield.py'
    geometry_freshness_rf_package = 'projects/rf_multipole_ion_optics/core/__init__.py'
    geometry_freshness_baseline = 'projects/single_reflection_oa_tof_mass_analyzer/config/baseline.json'
    geometry_freshness_science = 'projects/single_reflection_oa_tof_mass_analyzer/config/modes/formal.json'
    geometry_freshness_numerics = 'projects/single_reflection_oa_tof_mass_analyzer/config/formal_solver_numerics.json'
    geometry_freshness_published = 'projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json'
  }
  foreach ($entry in $geometrySources.GetEnumerator()) {
    $geometryFrozenInputs[$entry.Key] = Copy-VerifiedRunInput `
      -Source (Join-Path $repoRoot $entry.Value) -Destination (Join-Path $geometrySnapshotRoot $entry.Value)
  }
  $resolvedPath = $geometryFrozenInputs.geometry_freshness_published
  $geometryRunConfigPath = Join-Path $runDir 'run_config.json'
  $geometryRunConfig = Get-Content -LiteralPath $geometryRunConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
  $geometryRunConfig.inputs = [ordered]@{mode_config=$modePath;resolved_geometry=$resolvedPath}
  foreach ($entry in $geometryFrozenInputs.GetEnumerator()) {$geometryRunConfig.inputs[$entry.Key]=$entry.Value}
  $geometryRunConfig.parameters = [ordered]@{lifecycle_stage='geometry_input_freshness'}
  Write-RunJson -Path $geometryRunConfigPath -Value $geometryRunConfig -Depth 12
  $geometryCheck = "import runpy,sys;sys.path.insert(0,sys.argv[1]);sys.argv=['resolve_geometry','--check'];runpy.run_module('projects.single_reflection_oa_tof_mass_analyzer.analysis.resolve_geometry',run_name='__main__')"
  & $python -I -B -c $geometryCheck $geometrySnapshotRoot
  if ($LASTEXITCODE -ne 0) {throw 'Frozen mass-spectrum geometry input freshness failed.'}
  Copy-Item -LiteralPath $liveParticleCountPolicyPath -Destination $particleCountPolicyPath
}
$mode = Get-Content -LiteralPath $modePath -Raw | ConvertFrom-Json
if ([int]$mode.schema_version -ne 1 -or
    [string]$mode.role -cne 'oa_tof_candidate_mass_spectrum_mode' -or
    [string]$mode.mode -cne 'mass_spectrum_candidate') {
  throw 'Mass-spectrum mode identity is invalid.'
}
$formalMph = Join-Path $artifactRoot 'formal\comsol\single_reflection_oa_tof_mass_analyzer__model.mph'
$formalSimion = Join-Path $artifactRoot 'formal\simion'
$formalIob = Join-Path $formalSimion 'oatof_ideal_grounded.iob'
$ionGenerator = Join-Path $projectRoot 'simion\workbench\generate_comsol_consistent_ions.ps1'
$simionAnalyzer = Join-Path $projectRoot 'simion\workbench\analyze_ideal_field_log.ps1'
$requiredPaths = @($modePath,$resolvedPath,$formalMph,$formalIob,$python,$ionGenerator,
  $simionAnalyzer,$particleCountPolicyPath)
$requiredPaths += $SimionExe
foreach ($path in $requiredPaths) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required input is absent: $path" }
}
$particleCountPolicy = Get-Content -LiteralPath $particleCountPolicyPath -Raw -Encoding UTF8 |
  ConvertFrom-Json
$runConfigPath = Join-Path $runDir 'run_config.json'
$preflightRunConfig = Get-Content -LiteralPath $runConfigPath -Raw -Encoding UTF8 |
  ConvertFrom-Json -AsHashtable
$preflightRunConfig.inputs = [ordered]@{
  mode_config = $modePath
  resolved_geometry = $resolvedPath
  particle_count_policy = $particleCountPolicyPath
}
foreach ($entry in $geometryFrozenInputs.GetEnumerator()) {$preflightRunConfig.inputs[$entry.Key] = $entry.Value}
$preflightRunConfig.particle_source_preflight = @()
$preflightRunConfig.parameters = [ordered]@{
  lifecycle_stage = 'particle_source_preflight'
}
Write-RunJson -Path $runConfigPath -Depth 12 -Value $preflightRunConfig
Write-TerminalRunRecord -RunDir $runDir -Status interrupted `
  -Reason 'Frozen mode, resolved geometry, and particle-count policy are bound.' `
  -RepoRoot $repoRoot -Python $python -SummaryRole 'oa_tof_terminal_run_summary'
$statisticalParticleCount = [int]$particleCountPolicy.statistical_count
& $python -m common.contracts.particle_count_policy --count $statisticalParticleCount
if ($LASTEXITCODE -ne 0) { throw 'Repository statistical particle-count policy is invalid.' }
foreach ($species in $mode.species) {
  & $python -m common.contracts.particle_count_policy --count ([int]$species.particle_count)
  if ($LASTEXITCODE -ne 0) {
    throw "Mass-spectrum species $($species.species_id) has no named standard particle-count contract."
  }
}

$contract = Get-Content -LiteralPath $resolvedPath -Raw | ConvertFrom-Json
$source = $contract.particle_source
$individualIonPaths = [Collections.Generic.List[string]]::new()
$parentIonPaths = [Collections.Generic.List[string]]::new()
$sourceValidationPaths = [Collections.Generic.List[string]]::new()
$sourceProvenance = [Collections.Generic.List[object]]::new()
$totalParticles = 0
foreach ($species in $mode.species) {
  $particleCount = [int]$species.particle_count
  $ionPath = Join-Path $ionDir ("{0}.ion" -f $species.species_id)
  $parentIonPath = Join-Path $ionDir ("{0}__n1000_parent.ion" -f $species.species_id)
  $sourceValidationPath = Join-Path $logDir `
    ("{0}__n1000_parent_validation.json" -f $species.species_id)
  $ionGenerationParameters = @{
    N = $statisticalParticleCount
    MassAmu = [double]$species.mass_amu
    Charge = [int]$species.charge_state
    EnergyMeanEv = [double]$mode.particle_source.initial_energy_mean_ev
    EnergyStdEv = [double]$mode.particle_source.initial_energy_sigma_ev
    HalfWidthXmm = [double]$source.size_x_mm/2
    HalfWidthYmm = [double]$source.size_y_mm/2
    HalfWidthZmm = [double]$source.size_z_mm/2
    CenterXmm = [double]$source.center_x_mm
    CenterYmm = [double]$source.center_y_mm
    CenterZmm = [double]$source.center_z_mm
    Seed = [int]$mode.particle_source.shared_seed
    Output = $parentIonPath
  }
  if ($resumeExisting) {
    foreach ($resumeInput in @($ionPath,$parentIonPath)) {
      if (-not (Test-Path -LiteralPath $resumeInput -PathType Leaf)) {
        throw "Resume input is absent: $resumeInput"
      }
    }
    if (@(Get-Content -LiteralPath $ionPath).Count -ne $particleCount) {
      throw "Resume ION row count is incorrect: $ionPath"
    }
    if (@(Get-Content -LiteralPath $parentIonPath).Count -ne $statisticalParticleCount) {
      throw "Resume N=1000 parent ION row count is incorrect: $parentIonPath"
    }
  } else {
    & $ionGenerator @ionGenerationParameters | Out-Null
    $parentLines = @(Get-Content -LiteralPath $parentIonPath -Encoding ASCII)
    if ($parentLines.Count -ne $statisticalParticleCount) {
      throw "Generated N=1000 parent ION row count is incorrect: $parentIonPath"
    }
    Set-Content -LiteralPath $ionPath -Value @($parentLines | Select-Object -First $particleCount) `
      -Encoding ASCII
  }
  $preflightRecord = [ordered]@{
    species_id = [string]$species.species_id
    status = 'pending_deterministic_parent_validation'
    consumed_source_path = $ionPath
    consumed_source_sha256 = (Get-FileHash -LiteralPath $ionPath -Algorithm SHA256).Hash
    parent_source_path = $parentIonPath
    parent_source_sha256 = (Get-FileHash -LiteralPath $parentIonPath -Algorithm SHA256).Hash
    validation_report_path = $sourceValidationPath
    particle_count = $particleCount
    parent_particle_count = $statisticalParticleCount
    mass_amu = [double]$species.mass_amu
    charge = [int]$species.charge_state
    energy_mean_ev = [double]$mode.particle_source.initial_energy_mean_ev
    energy_std_ev = [double]$mode.particle_source.initial_energy_sigma_ev
    half_width_xyz_mm = @(
      [double]$source.size_x_mm/2,
      [double]$source.size_y_mm/2,
      [double]$source.size_z_mm/2
    )
    center_xyz_mm = @(
      [double]$source.center_x_mm,
      [double]$source.center_y_mm,
      [double]$source.center_z_mm
    )
    seed = [int]$mode.particle_source.shared_seed
  }
  $preflightRunConfig.inputs["particle_source_$($species.species_id)"] = $ionPath
  $preflightRunConfig.inputs["particle_source_parent_$($species.species_id)"] = `
    $parentIonPath
  $preflightRunConfig.particle_source_preflight += $preflightRecord
  Write-RunJson -Path $runConfigPath -Depth 12 -Value $preflightRunConfig
  Write-TerminalRunRecord -RunDir $runDir -Status interrupted `
    -Reason "Deterministic parent validation pending for $($species.species_id)." `
    -RepoRoot $repoRoot -Python $python -SummaryRole 'oa_tof_terminal_run_summary'
  & $ionGenerator @ionGenerationParameters -ValidateExisting `
    -ValidationReport $sourceValidationPath | Out-Null
  if ($LASTEXITCODE -ne 0 -or
      -not (Test-Path -LiteralPath $sourceValidationPath -PathType Leaf)) {
    throw "Deterministic N=1000 parent validation failed: $parentIonPath"
  }
  if ($particleCount -eq [int]$particleCountPolicy.functional_check_count) {
    & $python -m common.contracts.particle_count_policy `
      --prefix-n100 $ionPath --prefix-n1000 $parentIonPath
    if ($LASTEXITCODE -ne 0) {
      throw "N=100 source is not the validated prefix of its N=1000 parent: $ionPath"
    }
  } elseif ($particleCount -eq $statisticalParticleCount) {
    $sourceSha = (Get-FileHash -LiteralPath $ionPath -Algorithm SHA256).Hash
    $parentSha = (Get-FileHash -LiteralPath $parentIonPath -Algorithm SHA256).Hash
    if ($sourceSha -cne $parentSha) {
      throw "N=1000 species source differs from its generated parent: $ionPath"
    }
  } else {
    throw "Mass-spectrum particle count lacks a named source policy: $particleCount"
  }
  $validation = Get-Content -LiteralPath $sourceValidationPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
  $validation | Add-Member -NotePropertyName species_id `
    -NotePropertyValue ([string]$species.species_id)
  $validation | Add-Member -NotePropertyName consumed_source_path `
    -NotePropertyValue $ionPath
  $validation | Add-Member -NotePropertyName consumed_source_sha256 `
    -NotePropertyValue ((Get-FileHash -LiteralPath $ionPath -Algorithm SHA256).Hash)
  $individualIonPaths.Add($ionPath)
  $parentIonPaths.Add($parentIonPath)
  $sourceValidationPaths.Add($sourceValidationPath)
  $sourceProvenance.Add($validation)
  $totalParticles += $particleCount
}
$combinedIon = Join-Path $ionDir 'wide_mz_combined.ion'
$combinedLines = [Collections.Generic.List[string]]::new()
foreach ($path in $individualIonPaths) {
  foreach ($line in Get-Content -LiteralPath $path) { $combinedLines.Add($line) }
}
if (-not $resumeExisting) {
  Set-Content -LiteralPath $combinedIon -Value $combinedLines -Encoding ASCII
} elseif (-not (Test-Path -LiteralPath $combinedIon -PathType Leaf)) {
  throw "Resume combined ION is absent: $combinedIon"
}
if ($combinedLines.Count -ne $totalParticles) { throw 'Combined ION row count is incorrect.' }

$simionLog = Join-Path $logDir 'simion_stdout.log'
$simionStderr = Join-Path $logDir 'simion_stderr.log'
$simionCsv = Join-Path $resultDir 'simion_particles.csv'
$simionSummary = Join-Path $resultDir 'simion_summary.json'
foreach ($species in $mode.species) {
  $speciesId = [string]$species.species_id
  $ionPath = Join-Path $ionDir "$speciesId.ion"
  $csvPath = Join-Path $comsolDir "$speciesId.csv"
  $reportPath = Join-Path $logDir "$speciesId.report.txt"
  $expected = "DETECTED={0}/{0}" -f [int]$species.particle_count
  if ($resumeExisting) {
    $complete = (Test-Path -LiteralPath $csvPath -PathType Leaf) -and
      (Test-Path -LiteralPath $reportPath -PathType Leaf) -and
      (Select-String -LiteralPath $reportPath -Pattern ("^" + [regex]::Escape($expected) + '$') -Quiet)
    if ($complete) { continue }
    if (Test-Path -LiteralPath $reportPath -PathType Leaf) {
      $failedReport = $reportPath + '.failed.' + (Get-Date -Format 'yyyyMMdd_HHmmss')
      Move-Item -LiteralPath $reportPath -Destination $failedReport
    }
  }
  $old = @{}
  $variables = @{
    OATOF_SOURCE_MODEL_PATH=$formalMph
    OATOF_ION_TABLE=$ionPath
    OATOF_COMSOL_OUTPUT_CSV=$csvPath
    OATOF_RUNTIME_DIR=$comsolDir
    OATOF_RESULTS_DIR=$resultDir
    OATOF_ACCELERATOR_HMAX_MM='1'
    OATOF_REUSE_EXISTING_FIELD='1'
    OATOF_FINE_TSTEP_NS='0.2'
    OATOF_DRIFT_TSTEP_NS='50'
    OATOF_SEGMENTED_OUTPUT='1'
    OATOF_USE_PARTICLE_STOP_TIME='0'
    OATOF_CLEAR_PARTICLE_SOLUTION_DATA='0'
    OATOF_APPLY_PARTICLE_PROPERTIES='1'
  }
  try {
    foreach ($entry in $variables.GetEnumerator()) {
      $old[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key,'Process')
      [Environment]::SetEnvironmentVariable($entry.Key,$entry.Value,'Process')
    }
    # Standalone orchestration yields to the child lifecycle; inherited grants stay owned by the parent.
    if ($null -ne $hostExecutionLease -and -not $hostExecutionLease.inherited) {
      Exit-HostExecutionLease -Lease $hostExecutionLease
      $hostExecutionLease = $null
    }
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') `
      -TaskScript (Join-Path $projectRoot 'comsol\run_fixed_particle_retrace.m') `
      -ReportPath $reportPath
    if ($null -eq $hostExecutionLease) {
      $hostExecutionLease = Enter-HostExecutionLease -Role $hostRole -Stage prepare
    }
  } finally {
    foreach ($entry in $variables.GetEnumerator()) {
      [Environment]::SetEnvironmentVariable($entry.Key,$old[$entry.Key],'Process')
    }
  }
  if (-not (Select-String -LiteralPath $reportPath -Pattern ("^" + [regex]::Escape($expected) + '$') -Quiet)) {
    throw "COMSOL $speciesId did not report $expected."
  }
}

# Run the inexpensive mixed-species SIMION side only after all five COMSOL
# batches succeed, so a COMSOL failure does not create a misleading half-run.
$referenceMassAmu = [double]$contract.validation_target.mass_amu
Push-Location -LiteralPath $repoRoot
try {
  $simionMaxTofUs = [double](& $python -m projects.single_reflection_oa_tof_mass_analyzer.analysis.solver_diagnostics `
    mass-spectrum-max-tof --mode $modePath --reference-mass-amu $referenceMassAmu)
  if ($LASTEXITCODE -ne 0) { throw 'Mass-spectrum maximum TOF calculation failed.' }
} finally {
  Pop-Location
}
  $runtimeTaskId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__simion__mass-spectrum-runtime'
  $runtimeRoot = Join-Path $artifactRoot "scratch\$runtimeTaskId"
  $runtimeReceipt = Join-Path $inputDir 'formal_simion_runtime_receipt.json'
  $runtimeRoot = New-OaTofFormalSimionRuntime -ProjectRoot $projectRoot `
    -ArtifactRoot $artifactRoot -PythonExe $python -Destination $runtimeRoot `
    -Receipt $runtimeReceipt
  $executionAlias = New-RunExecutionAlias -TargetDirectory $runDir -ExecutionRoot $pathContext.execution_root `
    -ExpectedExecutionRelativePaths @('ions\wide_mz_combined.ion')
  $runtimeAlias = New-RunExecutionAlias -TargetDirectory $runtimeRoot -ExecutionRoot $pathContext.execution_root `
    -ExpectedExecutionRelativePaths @('oatof_ideal_grounded.iob')
  $runtimeIob = Join-Path $runtimeAlias.execution_alias 'oatof_ideal_grounded.iob'
  $executionIon = Join-Path $executionAlias.execution_alias 'ions\wide_mz_combined.ion'
  $executionLog = Join-Path $executionAlias.execution_alias 'logs\simion_stdout.log'
  $executionStderr = Join-Path $executionAlias.execution_alias 'logs\simion_stderr.log'
  try {
    $hostExecutionLease = Update-HostResourceStage -Lease $hostExecutionLease -Stage flight `
      -Budget (Get-HostResourceBudget -Role $hostRole -Stage flight) -RetainedMemoryBytes 0
    $process = Start-Process -FilePath $SimionExe -WorkingDirectory $runtimeAlias.execution_alias `
      -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $executionLog `
      -RedirectStandardError $executionStderr -ArgumentList @(
        '--default-num-particles',[string]$totalParticles,'--nogui','fly',
        '--trajectory-quality','8','--retain-trajectories','0','--particles',$executionIon,
        '--programs','1','--adjustable','trajectory_quality=8','--adjustable',
        'trajectory_log_enable=1','--adjustable',
        ("diagnostic_max_tof_us={0}" -f $simionMaxTofUs),$runtimeIob)
    $hostExecutionLease = Update-HostResourceStage -Lease $hostExecutionLease -Stage postprocess `
      -Budget (Get-HostResourceBudget -Role $hostRole -Stage postprocess) -RetainedMemoryBytes 0
    if ($process.ExitCode -ne 0) { throw "SIMION mixed-species fly failed: $simionStderr" }
  } finally {
    if ($null -ne $runtimeAlias) {
      Remove-RunExecutionAlias -ExecutionAlias $runtimeAlias.execution_alias -TargetDirectory $runtimeRoot
      $runtimeAlias = $null
    }
    Remove-OaTofFormalSimionRuntime -ArtifactRoot $artifactRoot -RuntimeRoot $runtimeRoot
    $runtimeRoot = $null
    if ($null -ne $executionAlias) {
      Remove-RunExecutionAlias -ExecutionAlias $executionAlias.execution_alias -TargetDirectory $runDir
      $executionAlias = $null
    }
  }
  $summary = & $simionAnalyzer -Log $simionLog -IonFile $combinedIon `
    -Mode 'mass_spectrum_candidate' -Distribution 'five_species_shared_source' `
    -ParticleCsv $simionCsv
  $summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $simionSummary -Encoding UTF8

if ([int]$summary.Hit -ne $totalParticles) {
  throw "SIMION detected $($summary.Hit)/$totalParticles mixed-species ions."
}

& $python -m projects.single_reflection_oa_tof_mass_analyzer.analysis.mass_spectrum `
  --mode-config $modePath --comsol-dir $comsolDir --simion-csv $simionCsv --output $resultDir
if ($LASTEXITCODE -ne 0) { throw 'Candidate mass-spectrum analysis failed.' }

$runInputs = [ordered]@{
  mode_config = $modePath
  particle_count_policy = $particleCountPolicyPath
  resolved_geometry = $resolvedPath
  formal_comsol_mph = $formalMph
  formal_simion_iob = $formalIob
  formal_simion_runtime_receipt = Join-Path $inputDir 'formal_simion_runtime_receipt.json'
}
foreach ($entry in $geometryFrozenInputs.GetEnumerator()) {$runInputs[$entry.Key] = $entry.Value}
$runConfig = Get-Content -LiteralPath $runConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
$scientificConfig = [ordered]@{
  role = 'oa_tof_mass_spectrum_run_config'
  formal_gate_passed = $false
  inputs = $runInputs
  species = $mode.species
  particle_source_provenance = @($sourceProvenance)
  execution = [ordered]@{
    simion = 'one mixed-species fly'
    comsol = 'one particle-tracing solve per species; formal electrostatic solution reused'
    resumed_after_comsol = [bool]$ResumeAfterComsol
    reanalyze_only = $false
    particle_count_contract = 'repository_standard_with_n100_prefix_of_n1000'
    simion_max_tof_us = $simionMaxTofUs
  }
}
foreach ($entry in $scientificConfig.GetEnumerator()) { $runConfig[$entry.Key] = $entry.Value }
Write-RunJson -Path $runConfigPath -Value $runConfig -Depth 100
$summaryPath = Join-Path $runDir 'summary.json'
$summaryRecord = Get-Content -LiteralPath (Join-Path $resultDir 'mass_spectrum_metrics.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$summaryRecord | Add-Member -NotePropertyName status -NotePropertyValue 'success' -Force
$summaryRecord | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
$manifestPath = Join-Path $runDir 'run_manifest.json'
$outputs = @($combinedIon,$simionCsv,$simionSummary,$summaryPath)
$outputs += @($individualIonPaths)
$outputs += @($parentIonPaths)
$outputs += @($sourceValidationPaths)
$outputs += @($mode.species | ForEach-Object {
  Join-Path $comsolDir ("{0}.csv" -f $_.species_id)
})
$optionalEvidence = @($simionLog,$simionStderr)
$optionalEvidence += @($mode.species | ForEach-Object {
  Join-Path $logDir ("{0}.report.txt" -f $_.species_id)
})
$optionalEvidence += @(Get-ChildItem -LiteralPath $comsolDir -File -Filter '*_selected_release_from_data_file.txt' |
  ForEach-Object { $_.FullName })
$optionalEvidence += @(Get-ChildItem -LiteralPath $comsolDir -Recurse -File -Filter 'hs_err_pid*.log' |
  ForEach-Object { $_.FullName })
$outputs += @($optionalEvidence | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf })
$outputs += @(
  (Join-Path $resultDir 'mass_spectrum_particles.csv'),
  (Join-Path $resultDir 'mass_spectrum_summary.csv'),
  (Join-Path $resultDir 'mass_peak_shape_comparison.csv'),
  (Join-Path $resultDir 'mass_spectrum_metrics.json'),
  (Join-Path $resultDir 'mass_spectrum_comparison.png'),
  (Join-Path $resultDir 'mass_detector_landing_comparison.png')
)
$manifestArgs = @(
  (Join-Path $repoRoot 'common\contracts\write_run_manifest.py'),
  '--run-config',$runConfigPath,'--manifest',$manifestPath,'--status','success',
  '--software','SIMION 2020','--software','COMSOL 6.4 via MATLAB R2025b'
)
foreach ($output in $outputs) { $manifestArgs += @('--output',$output) }
& $python @manifestArgs
if ($LASTEXITCODE -ne 0) { throw 'Run manifest creation failed.' }
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $manifestPath
if ($LASTEXITCODE -ne 0) { throw 'Run manifest verification failed.' }
$runRecordComplete = $true
Write-Output "MASS_SPECTRUM_CANDIDATE=PASS RUN_ID=$RunId PARTICLES=$totalParticles"

} finally {
  try { if ($null -ne $hostExecutionLease) { Exit-HostExecutionLease -Lease $hostExecutionLease } }
  finally { Restore-RunEnvironment -Names $environmentNames -Snapshot $environmentSnapshot }
}
