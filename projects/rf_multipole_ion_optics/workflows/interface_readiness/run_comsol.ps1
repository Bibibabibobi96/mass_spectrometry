[CmdletBinding(DefaultParameterSetName="Run")]
param(
    [string]$RunId = '',
    [Parameter(Mandatory = $true,ParameterSetName="Run")][string]$ParticleTablePath,
    [Parameter(Mandatory = $true,ParameterSetName="Run")][string]$ParticleBundleMetadataPath,
    [Parameter(Mandatory = $true,ParameterSetName="Run")][string]$SourceFamilyPath,
    [Parameter(Mandatory = $true,ParameterSetName="Run")][string]$ParticleDistributionPath,
    [Parameter(Mandatory = $true,ParameterSetName="Run")][string]$SolverNumericsContractPath,
    [Parameter(Mandatory = $true,ParameterSetName="Run")][string]$SolverNumericsProfileId,
    [string]$NumericalExperimentId = '',
    [Parameter(Mandatory = $true,ParameterSetName="Run")][string]$OperatingPoint,
    [string]$PythonExe = '',
    [switch]$ReleaseConstructionGate,
    [Parameter(Mandatory,ParameterSetName='Run')][Parameter(Mandatory,ParameterSetName='Analyze')][string]$LimitsPath,
    [Parameter(Mandatory,ParameterSetName='Analyze')][switch]$AnalyzeOnly,
    [Parameter(Mandatory,ParameterSetName='Analyze')][string]$ParentManifestPath,
    [Parameter(ParameterSetName='Analyze')][string]$StoppedReceiptPath='',
    [ValidateRange(1,3)][int]$StartupAttempts=1,
    [string]$ResultPath='',
    [Parameter(Mandatory,ParameterSetName='Resume')][switch]$ResumeFinalization
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$repoRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$python = if ($PythonExe) {
    [IO.Path]::GetFullPath($PythonExe)
} else {
    Join-Path $repoRoot '.venv\Scripts\python.exe'
}
. (Join-Path $repoRoot 'common/contracts/run_artifact_workflow.ps1') -ResultPath $ResultPath -ResumeFinalization:$ResumeFinalization
if($ResumeFinalization){
    $allowed=@('ResumeFinalization','RunId','ResultPath','PythonExe')
    $ignored=@($PSBoundParameters.Keys|Where-Object{$_-notin$allowed})
    if($ignored.Count){throw ('ResumeFinalization does not accept new execution options: '+($ignored-join', '))}
    if(-not$ResultPath){throw 'ResumeFinalization requires the original ResultPath.'}
    $prior=Get-Content -LiteralPath $ResultPath -Raw -Encoding UTF8|ConvertFrom-Json
    if($prior.role-cne'run_artifact_workflow_result'){throw 'Recovery requires the original public workflow Result.'}
    $originalConfig=Get-Content (Join-Path $prior.run_directory 'run_config.json') -Raw -Encoding UTF8|ConvertFrom-Json
    if($originalConfig.project-cne'rf_multipole_ion_optics'-or$originalConfig.mode-notin@('transport_interface_readiness','transport_interface_postprocess')){throw 'Recovery Result belongs to another workflow.'}
    $originalRunId=Split-Path -Leaf ([string]$prior.run_directory)
    if($RunId-and$RunId-cne$originalRunId){throw 'Recovery RunId differs from original Result.'}
    $outcome=Invoke-RunArtifactWorkflow -RequestPath (Join-Path $prior.run_directory 'inputs/execution_request.json') -ResultPath $ResultPath -ResumeFinalization
    Write-Output "INTERFACE_WORKFLOW_RESULT=$ResultPath STATUS=$($outcome.status) STAGE=$($outcome.stage)"
    if($outcome.stage-ne'complete'){throw 'Finalization remains incomplete; inspect original Result.'}
    if($outcome.status-ne'success'){throw "Original execution terminal status=$($outcome.status)."}
    return
}
function Read-InterfaceExecutionLimits {
    param([string]$Path)
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){throw 'Interface execution LimitsPath is missing.'}
    $value=Get-Content -LiteralPath $Path -Raw -Encoding UTF8|ConvertFrom-Json
    foreach($name in @('wall_clock_seconds','transient_run_directory_bytes','process_tree_working_set_bytes','minimum_system_available_memory_bytes')){
        $member=$value.PSObject.Properties[$name]
        if($null-eq$member-or$member.Value-is[bool]-or$member.Value-isnot[ValueType]-or[double]$member.Value-le0-or[double]$member.Value-ne[math]::Truncate([double]$member.Value)){throw "Explicit Limits $name must be a positive integer."}
    }
    return $value
}
. (Join-Path $repoRoot 'common/paths/workspace_paths.ps1')
$pathContext=Resolve-WorkspacePaths -SourceRoot $repoRoot -Python $python
$artifactRoot=Join-Path ([string]$pathContext.artifact_root) 'projects/rf_multipole_ion_optics'
$Limits=Read-InterfaceExecutionLimits -Path $LimitsPath
$CommittedNewBytes=[long]$Limits.transient_run_directory_bytes
. (Join-Path $repoRoot 'common/host_execution_lease.ps1')
$ResourceBudgets=@{}
foreach($stage in @('prepare','solver','postprocess')){$ResourceBudgets[$stage]=(Get-HostResourceBudget -Role COMSOL -Stage $stage).Clone()}
$ResourceBudgets.solver.memory_bytes=[long]$Limits.process_tree_working_set_bytes
. (Join-Path $projectRoot 'runtime\comsol_solver_numerics.ps1')
. (Join-Path $projectRoot 'runtime\frozen_python_package.ps1')
$frozenPythonRelativePaths = @(
    'projects\rf_multipole_ion_optics\workflows\__init__.py',
    'projects\rf_multipole_ion_optics\workflows\interface_readiness\__init__.py',
    'projects\rf_multipole_ion_optics\workflows\interface_readiness\generate_particle_table.py',
    'projects\rf_multipole_ion_optics\workflows\interface_readiness\particle_source_policy.py',
    'projects\rf_multipole_ion_optics\analysis\paired_particle_source_bundle.py',
    'projects\rf_multipole_ion_optics\analysis\analyze_comsol_particle_state_metrics.py',
    'projects\rf_multipole_ion_optics\analysis\validate_release_construction_gate.py',
    'common\contracts\particle_physics.py',
    'common\contracts\particle_state.py',
    'common\contracts\particle_count_policy.py',
    'common\contracts\particle_count_policy.json',
    'common\contracts\file_identity.py',
    'common\ion_release\__init__.py',
    'common\ion_release\cylinder.py',
    'common\ion_release\mt19937_disk_cone_rf_phase.py',
    'common\ion_release\numpy_box_cone.py',
    'common\ion_release\numpy_ion11_box.py',
    'projects\rf_multipole_ion_optics\core\__init__.py',
    'projects\rf_multipole_ion_optics\core\interface_geometry.py',
    'projects\rf_multipole_ion_optics\runtime\particle_source_preflight.py'
)
$executionCapacityPaths = @('inputs/frozen_python_package.ps1') +
    (Get-FrozenPythonPackageExecutionPaths -RelativePaths $frozenPythonRelativePaths)


function Invoke-InterfaceComsolTask {
    param([string]$Task,[string]$Report,[string]$Stage,[Collections.IDictionary]$State)
    $nativePaths=@($Task,$Report,$package.run_config)
    $guiEnvironment=@('RFQUAD_COMSOL_MODEL_PATH','RFQUAD_SOLVER_RAW_METADATA_PATH','RFQUAD_GUI_RUN_ROOT','RFQUAD_GUI_OBSERVATION_ROOT')
    if($Stage-eq'gui'){
        foreach($name in $guiEnvironment){
            $value=[Environment]::GetEnvironmentVariable($name,'Process')
            if([string]::IsNullOrWhiteSpace($value)){throw "GUI native path is missing: $name"}
            $nativePaths+=$value
        }
        $raw=Get-Content -LiteralPath $env:RFQUAD_SOLVER_RAW_METADATA_PATH -Raw -Encoding UTF8|ConvertFrom-Json
        foreach($entry in $raw.release_files){
            if([string]$entry.relative_path-notmatch'^runtime[/\\]particle_[0-9]+[.]txt$'){throw 'GUI release relative role path is invalid.'}
            $nativePaths+=Join-Path $env:RFQUAD_GUI_RUN_ROOT ([string]$entry.relative_path)
        }
    }
    $nativeContext=Get-RunNativeExecutionContext -Package $package -Paths $nativePaths -Tool COMSOL
    foreach($name in $nativeContext.environment.Keys){[Environment]::SetEnvironmentVariable($name,[string]$nativeContext.environment[$name],'Process')}
    $Task=$nativeContext.projected_paths[0];$Report=$nativeContext.projected_paths[1]
    $env:RFQUAD_RUN_CONFIG=$nativeContext.projected_paths[2]
    if($Stage-eq'gui'){
        for($index=0;$index-lt$guiEnvironment.Count;$index++){
            [Environment]::SetEnvironmentVariable($guiEnvironment[$index],[string]$nativeContext.projected_paths[3+$index],'Process')
        }
    }
    $receipt=Join-Path $logDir ($Stage+'_completion.json')
    $usage=Join-Path $logDir ($Stage+'_usage.json')
    $call=@{stage=$Stage;receipt=$receipt;usage=$usage;wrapper_returned=$false}
    if($State.calls.Count-eq0){$State.prepare_seconds=$State.timer.Elapsed.TotalSeconds}
    $State.calls.Add($call);$callTimer=[Diagnostics.Stopwatch]::StartNew()
    try{
        & (Join-Path $repoRoot 'common/comsol/run_comsol_r2025b.ps1') -TaskScript $Task -ReportPath $Report `
          -StartupAttempts $StartupAttempts -Limits $Limits -ResourceBudgets $ResourceBudgets `
          -RunId $RunId -RunDir $package.artifact_run_dir -UsagePath $usage -CompletionPath $receipt
        $call.wrapper_returned=$true
        if($LASTEXITCODE-ne0){throw "COMSOL $Stage launcher failed."}
    }catch{$call.wrapper_error=$_.Exception.Message;throw}
    finally{$call.elapsed_seconds=$callTimer.Elapsed.TotalSeconds}
}
function Read-InterfaceGuiParityReport {
    param([string]$Path,[long[]]$ExpectedParticleIds,[Parameter(Mandatory)][string]$ObservationRoot,
      [int]$ExpectedHits=-1,[bool]$RequireAcceptance=$true)
    $jsonPath=Join-Path $ObservationRoot 'gui_verification.json'
    if(-not(Test-Path -LiteralPath $jsonPath -PathType Leaf)){
        if((Test-Path -LiteralPath (Join-Path $ObservationRoot 'gui_observations_saved.mat') -PathType Leaf)-and
           (Test-Path -LiteralPath (Join-Path $ObservationRoot 'gui_observations_computed.mat') -PathType Leaf)){
            throw 'GUI diagnostic JSON is missing; retained MAT observations can be loaded and compared by compare_rf_gui_observations without COMSOL. Repair analysis in a new owner; do not repeat Compute.'
        }
        throw 'GUI post-Compute observations are missing; inspect its native completion and declared artifacts. A saved pre-GUI model cannot recreate the missing recomputed states; obtain them only through an explicitly requested new GUI action.'
    }
    $value=Get-Content -LiteralPath $jsonPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable -Depth 64
    if($value.role-cne'rf_interface_gui_parity'-or$value.status-notin@('PASS','FAIL')-or
       $value.source_binding_verified-isnot[bool]-or-not$value.source_binding_verified-or
       $value.gui_operation_completed-isnot[bool]-or-not$value.gui_operation_completed-or
       $value.original_acceptance_verified-isnot[bool]-or
       $value.observed_state_parity_verified-isnot[bool]-or$value.observed_state_parity_verified-or
       $value.numerical_equivalence_status-cne'NOT_EVALUATED'-or
       $value.native_birth_echo_unavailable_saved_observation-isnot[bool]-or$value.scientific_result-cne'NOT_EVALUATED'){
        throw 'GUI operation/source binding, echo availability or numerical qualification scope is unconfirmed.'
    }
    $ids=@($value.particle_ids)
    if($ids.Count-ne$ExpectedParticleIds.Count-or$value.particles-ne$ids.Count-or
       @($ids|Select-Object -Unique).Count-ne$ids.Count-or
       (($ids|Sort-Object)-join',')-cne(($ExpectedParticleIds|Sort-Object)-join',')-or
       @($value.terminal_outcomes).Count-ne$ids.Count){throw 'GUI report does not cover the complete original mother population.'}
    $acceptance=$value.original_acceptance
    if($acceptance.particles-ne$ids.Count-or$acceptance.expected_particles-ne$ids.Count-or
       $acceptance.hits-isnot[ValueType]-or$acceptance.expected_hits-isnot[ValueType]-or
       $acceptance.hits-lt0-or$acceptance.hits-gt$ids.Count-or$acceptance.hits-ne[math]::Truncate($acceptance.hits)-or
       $acceptance.expected_hits-lt0-or$acceptance.expected_hits-gt$ids.Count-or$acceptance.expected_hits-ne[math]::Truncate($acceptance.expected_hits)-or
       ($ExpectedHits-ge0-and$acceptance.expected_hits-ne$ExpectedHits)-or
       $value.original_acceptance_verified-ne($acceptance.hits-eq$acceptance.expected_hits)-or
       ($value.status-eq'PASS')-ne$value.original_acceptance_verified){throw 'GUI original count/hit acceptance is contradictory.'}
    foreach($name in @('common_stored_time_count','compared_finite_state_count','active_mask_difference_count','terminal_observation_difference_count','project_outcome_difference_count')){
        if($value[$name]-isnot[ValueType]-or$value[$name]-is[bool]-or$value[$name]-lt0-or
           [double]::IsNaN([double]$value[$name])-or[double]::IsInfinity([double]$value[$name])-or
           $value[$name]-ne[math]::Truncate($value[$name])){throw 'GUI diagnostic count is invalid.'}
    }
    foreach($name in @('maximum_position_error_mm','maximum_velocity_error_m_s','rms_position_component_error_mm','rms_velocity_component_error_m_s')){
        $errorValue=$value[$name]
        if($value.compared_finite_state_count-eq0-and($null-eq$errorValue-or($errorValue-is[Array]-and$errorValue.Count-eq0))){continue}
        if($errorValue-isnot[ValueType]-or$errorValue-is[bool]-or[double]::IsNaN([double]$errorValue)-or
           [double]::IsInfinity([double]$errorValue)-or$errorValue-lt0){throw 'GUI observed-state diagnostic is invalid.'}
    }
    if((@($value.snapshot_files)-join',')-cne'gui_observations_saved.mat,gui_observations_computed.mat'){throw 'GUI snapshot roles differ.'}
    foreach($name in $value.snapshot_files){
        $file=Join-Path $ObservationRoot $name
        if(-not(Test-Path -LiteralPath $file -PathType Leaf)-or(Get-Item $file).Length-le0){throw 'GUI original observations are missing; no zero-Compute analysis is possible.'}
    }
    if($RequireAcceptance-and-not$value.original_acceptance_verified){throw 'GUI original count/hit acceptance failed; preserve FAIL and observations, do not rerun Compute for analysis.'}
    return $value
}
function Complete-InterfaceOwner {
    param([string]$Status,[Collections.IDictionary]$Summary,[string[]]$Outputs=@(),$Failure=$null)
    $operations=[Collections.Generic.List[object]]::new();$releases=[Collections.Generic.List[object]]::new()
    $usage=@();$confirmed=$false
    try{
        if($ownerState.writer_unknown){throw 'Analysis writer completion is unknown.'}
        foreach($call in $ownerState.calls){
            $receipt=Get-Content -LiteralPath $call.receipt -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
            if($receipt.role-cne'comsol_launcher_completion'-or$receipt.run_id-cne$RunId){throw 'Actual launcher receipt identity differs.'}
            $id=if([bool]$receipt.host_release.inherited){[string]$receipt.host_release.token}else{'interface-'+$call.stage}
            Add-RunArtifactResourceRelease -ResourceReleases $releases -ReleaseId $id -Receipt $receipt
            foreach($operation in $receipt.operations){$operations.Add(@{operation_id=($call.stage+'-'+$operation.operation_id);observation=$operation.observation;resource_release_id=$id})}
            if(Test-Path -LiteralPath $call.usage -PathType Leaf){$usage+=@{case_name=$call.stage;path=$call.usage}}
        }
        if($ownerState.Contains('analysis_operations')-and$ownerState.analysis_operations.Count){
            # Invoke-ResourceBudgetedProcess supplied actual Python PID/start/exit.
            # Unknown completion never reaches this release boundary.
            $released=Exit-HostResourceStage -Lease $lease -PassThru
            $hostReceipt=@{host_release=@{inherited=[bool]$lease.inherited;token=[string]$lease.token;result=$released;error=$null}}
            $id=if($lease.inherited){[string]$lease.token}else{'postprocess'}
            Add-RunArtifactResourceRelease -ResourceReleases $releases -ReleaseId $id -Receipt $hostReceipt
            foreach($operation in $ownerState.analysis_operations){$operation.resource_release_id=$id;$operations.Add($operation)}
            $ownerState.analysis_release=$hostReceipt
            foreach($item in $ownerState.analysis_usage){if(Test-Path $item.path -PathType Leaf){$usage+=$item}}
        }
        $completion=@{operations=@($operations.ToArray());resource_releases=@($releases.ToArray())}
        Assert-WorkflowWriterCompletion $completion -PowerShellOwner;$confirmed=$true
    }catch{
        $ownerState.writer_unknown=$true
        $Summary.secondary_errors=@($_.Exception.Message);$Summary.recovery_action='inspect_writer_completion'
        $Summary.execution_status='writer_completion_unknown'
        if($null-ne$Failure){$Failure.Exception.Data['writer_completion_error']=[string]$_}
    }
    if($confirmed){
        # Only stopped-writer completion canonicalizes declared reusable bindings.
        # Keep actual execution observations unchanged as historical facts.
        $configPath=Join-Path $ownerContext.run_directory 'run_config.json'
        $persistentConfig=Get-Content -LiteralPath $configPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
        foreach($name in @('run_dir','results_dir','comsol_dir','runtime_dir','logs_dir')){
            if($persistentConfig.Contains($name)){$persistentConfig[$name]=Convert-WorkflowOwnerPath $ownerContext ([string]$persistentConfig[$name])}
        }
        foreach($name in @($persistentConfig.inputs.Keys)){
            if($persistentConfig.inputs[$name]-is[string]-and[IO.Path]::IsPathFullyQualified($persistentConfig.inputs[$name])){
                $persistentConfig.inputs[$name]=Convert-WorkflowOwnerPath $ownerContext $persistentConfig.inputs[$name]
            }
        }
        if($persistentConfig.Contains('frozen_python')-and$persistentConfig.frozen_python.Contains('package')){
            $frozen=$persistentConfig.frozen_python.package
            $frozen.code_root=Convert-WorkflowOwnerPath $ownerContext ([string]$frozen.code_root)
            $frozen.package_roots=@($frozen.package_roots|ForEach-Object{Convert-WorkflowOwnerPath $ownerContext ([string]$_)})
            foreach($file in $frozen.files){$file.path=Convert-WorkflowOwnerPath $ownerContext ([string]$file.path)}
        }
        Write-RunJson -Atomic -Path $configPath -Value $persistentConfig -Depth 64
    }
    $Summary.native_wrapper_calls=@($ownerState.calls.ToArray())
    $Summary.completed_computations=@()
    foreach($call in $ownerState.calls){
        if($call.stage-eq'native'-and$call.wrapper_returned-and-not$call.Contains('wrapper_error')){
            $metadataPath=Join-Path $ownerContext.run_directory 'results/solver_raw_metadata.json'
            $savedModel=Join-Path $ownerContext.run_directory 'comsol/rf_multipole_ion_optics__model.mph'
            if((Test-Path $metadataPath -PathType Leaf)-and(Test-Path $savedModel -PathType Leaf)){
                $metadata=Get-Content $metadataPath -Raw -Encoding UTF8|ConvertFrom-Json
                if($metadata.raw_solution_persisted){$Summary.completed_computations+=@{stage='native_transport';model_path=$savedModel;raw_metadata_path=$metadataPath;gui_verified=(@($ownerState.calls|Where-Object{$_.stage-eq'gui'-and$_.wrapper_returned-and-not$_.Contains('wrapper_error')}).Count-gt0)}}
            }
        }
    }
    if($Summary.Contains('failure_stage')){$Summary.execution_failure_stage=$Summary.failure_stage}
    if($ownerState.calls.Count-eq0-and-not$ownerState.Contains('analysis_operations')){$ownerState.prepare_seconds=$ownerState.timer.Elapsed.TotalSeconds}
    $timings=@{prepare=$ownerState.prepare_seconds};[double]$nativeSeconds=0
    foreach($call in $ownerState.calls){$timings[$call.stage]=$call.elapsed_seconds;$nativeSeconds+=$call.elapsed_seconds}
    $timings.analysis_and_validation=[math]::Max(0,$ownerState.timer.Elapsed.TotalSeconds-$ownerState.prepare_seconds-$nativeSeconds)
    $Summary.phase_timings_seconds=$timings
    $Summary.total_elapsed_seconds=$ownerState.timer.Elapsed.TotalSeconds
    $ownerState.finalization_started=$true
    $actual=@($Outputs|Where-Object{Test-Path -LiteralPath $_ -PathType Leaf})
    # Native solutions follow the declared solver_review policy; SIMION trace
    # PreservePaths is not a native-model retention exception.
    if($confirmed){Write-RunJson -Atomic -Path (Join-Path $ownerContext.run_directory 'summary.json') -Value $Summary -Depth 64}
    $outcome=Complete-RunArtifactPowerShellOwner -Context $ownerContext -Status $Status -Summary $Summary `
      -OutputPaths $actual -WriterCompletion $(if($confirmed){$completion}else{@{operations=@();resource_releases=@()}}) `
      -WritersStopped $confirmed -OriginalFailure $Failure -ResourceUsagePaths $usage
    if($outcome.stage-ne'complete'){throw 'Interface finalization incomplete; resume original Result.'}
    Write-Output "INTERFACE_WORKFLOW_RESULT=$($ownerContext.result_path)"
}
function Invoke-InterfacePostprocessChild {
    # SourceReferences validates the stopped checkpoint and obtains the existing
    # shared source protection before any native-stage dependency is consumed.
    $parent=(Resolve-Path -LiteralPath $ParentManifestPath).Path
    $parentRoot=Split-Path -Parent $parent
    if((Split-Path -Leaf $parent)-cne'run_manifest.json'){throw 'ParentManifestPath must name the original manifest.'}
    $references=@(@{manifest_record=(New-WorkflowOwnerFileRecord $parent)})
    if($StoppedReceiptPath){$references[0].stopped_receipt_record=New-WorkflowOwnerFileRecord (Resolve-Path -LiteralPath $StoppedReceiptPath).Path}
    if(-not$RunId){$RunId=(Get-Date -Format yyyyMMdd_HHmmss)+'__analysis__python__rf-interface'}
    $package=$null;$capacity=$null;$ownerContext=$null;$phase='source_admission';$lease=$null
    $ownerState=@{calls=[Collections.Generic.List[object]]::new();writer_unknown=$false;finalization_started=$false;prepare_seconds=0.;timer=[Diagnostics.Stopwatch]::StartNew();analysis_operations=@();analysis_release=$null;analysis_usage=@()}
    $names=@('SIMULATION_PYTHON_EXE','MASS_SPECTROMETRY_ARTIFACT_ROOT','MASS_SPECTROMETRY_EXECUTION_ROOT','MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH')
    $saved=Save-RunEnvironment -Names $names
    try{
        $env:SIMULATION_PYTHON_EXE=$python
        $env:MASS_SPECTROMETRY_ARTIFACT_ROOT=[string]$pathContext.artifact_root
        $env:MASS_SPECTROMETRY_EXECUTION_ROOT=[string]$pathContext.execution_root
        $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=[string]$pathContext.host_resource_state_path
        $childRoot=Join-Path $artifactRoot ('runs/'+$RunId)
        $capacity=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -ArtifactRoot $pathContext.artifact_root `
          -RunDirectory $childRoot -CommittedNewBytes $CommittedNewBytes -ProtectedPaths @($childRoot) `
          -SourceReferences $references -Owner ('run-artifact-workflow:rf_multipole_ion_optics:'+$RunId)
        $package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -PathContext $pathContext `
          -RunId $RunId -Project rf_multipole_ion_optics -Mode transport_interface_postprocess -Software @('Python 3.11') `
          -RetentionContractEnabled -RetentionClass compact -CapacityLedgerLifecycleEnabled
        $entry=Join-Path $package.input_dir 'run_comsol.ps1';$null=Copy-VerifiedRunInput -Source $PSCommandPath -Destination $entry
        $limitsFrozen=Join-Path $package.input_dir 'postprocess_limits.json';$null=Copy-VerifiedRunInput -Source $LimitsPath -Destination $limitsFrozen
        $budget=$ResourceBudgets.postprocess.Clone();$budget.memory_bytes=[long]$Limits.process_tree_working_set_bytes
        $budgetPath=Join-Path $package.input_dir 'postprocess_host_budget.json';Write-RunJson -Path $budgetPath -Value $budget
        $ownerContext=Initialize-RunArtifactPowerShellOwner -Python $python -RepoRoot $repoRoot -Package $package -CapacitySession $capacity `
          -ResultPath $ResultPath -EntrypointPath $entry -CommitmentInputPaths @($limitsFrozen,$budgetPath) -Software @('Python 3.11')
        $phase='completed_native_stage_validation'
        $config=Get-Content (Join-Path $parentRoot 'run_config.json') -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
        if($config.project-cne'rf_multipole_ion_optics'-or$config.mode-cne'transport_interface_readiness'-or
          $config.parameters.execution_stage-cne'full_particle_transport'){throw 'Parent has no interface native transport stage.'}
        $nativeReceipt=Join-Path $parentRoot 'logs/native_completion.json'
        $receipt=Get-Content $nativeReceipt -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
        if($receipt.role-cne'comsol_launcher_completion'-or$receipt.run_id-cne(Split-Path -Leaf $parentRoot)){throw 'Parent native completion identity differs.'}
        $releases=[Collections.Generic.List[object]]::new()
        $releaseId=if($receipt.host_release.inherited){$receipt.host_release.token}else{'parent-native'}
        Add-RunArtifactResourceRelease -ResourceReleases $releases -ReleaseId $releaseId -Receipt $receipt
        $operations=@($receipt.operations|ForEach-Object{@{operation_id=$_.operation_id;observation=$_.observation;resource_release_id=$releaseId}})
        Assert-WorkflowWriterCompletion @{operations=$operations;resource_releases=@($releases.ToArray())} -PowerShellOwner
        if(-not$operations.Count-or@($operations|Where-Object{$_.observation.returncode-ne0}).Count){throw 'Parent native launcher has no successful completed operation.'}
        $metadata=Join-Path $parentRoot 'results/solver_raw_metadata.json'
        $state=Join-Path $parentRoot 'results/particle_state.csv'
        $mapping=Join-Path $parentRoot 'results/release_source_mapping.json'
        $model=Join-Path $parentRoot 'comsol/rf_multipole_ion_optics__model.mph'
        $nativeReport=Join-Path $parentRoot 'logs/comsol_bootstrap_report.txt'
        foreach($file in @($metadata,$state,$mapping,$model,$nativeReport,$config.inputs.particle_table,$config.inputs.interface_contract,$config.inputs.resolved_design)){
            if(-not(Test-WorkflowPathWithin $file $parentRoot)-or-not(Test-Path $file -PathType Leaf)){throw 'Frozen completed-stage dependency is missing or outside parent.'}
        }
        if(-not(Select-String -LiteralPath $nativeReport -Pattern '^STATUS=PASS\s*$' -Quiet)){throw 'Parent native task did not report PASS.'}
        $raw=Get-Content $metadata -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
        $nativeMap=Get-Content $mapping -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
        if($raw.role-cne'rf_quadrupole_comsol_raw_solver_metadata'-or$raw.raw_solution_persisted-isnot[bool]-or-not$raw.raw_solution_persisted){throw 'Parent has no persisted native solution fact.'}
        if($nativeMap.native_scope-cne'complete_cohort'){throw 'Parent mapping is not the complete original cohort.'}
        foreach($key in @('native_order','source_ids','source_birth_s','source_weights','source_initial_position_mm','source_initial_velocity_m_s')){
            if(-not$nativeMap.Contains($key)-or-not$raw.Contains($key)-or
              (ConvertTo-Json -InputObject $nativeMap[$key] -Compress -Depth 8)-cne(ConvertTo-Json -InputObject $raw[$key] -Compress -Depth 8)){throw "Saved native/source mapping differs: $key"}
        }
        $design=Get-Content $config.inputs.resolved_design -Raw -Encoding UTF8|ConvertFrom-Json
        $phase='freeze_analysis'
        $frozen=New-FrozenPythonPackage -SourceRoot $repoRoot -CodeRoot (Join-Path $package.input_dir 'code') -RelativePaths $frozenPythonRelativePaths
        Assert-FrozenPythonPackage $frozen
        $child=Get-Content $package.run_config -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
        $child.inputs.native_execution_limits=$limitsFrozen;$child.inputs.native_host_budgets=$budgetPath
        $child.provenance=@{source_references=$references;referenced_state=$state;parent_request_completed=$false;gui_requested=$false;new_solve_calls=0;
          completed_native_stage=@{receipt=(New-WorkflowOwnerFileRecord $nativeReceipt);metadata=(New-WorkflowOwnerFileRecord $metadata);source_mapping=(New-WorkflowOwnerFileRecord $mapping);native_report=(New-WorkflowOwnerFileRecord $nativeReport);model_path=$model}}
        $child.frozen_python=@{package=$frozen}
        Write-RunJson -Atomic -Path $package.run_config -Value $child -Depth 64
        $phase='postprocess';$ownerState.prepare_seconds=$ownerState.timer.Elapsed.TotalSeconds
        $summary=Join-Path $package.result_dir 'solver_summary.json';$contract=Join-Path $package.result_dir 'particle_state_contract.json'
        $origin=Join-Path $package.result_dir 'analysis_module_origins.json'
        $usage=Join-Path $package.result_dir 'postprocess_resource_usage.json';$ownerState.analysis_usage=@(@{case_name='postprocess';path=$usage})
        $lease=Enter-HostResourceStage -StatePath $pathContext.host_resource_state_path -Role COMSOL -Stage postprocess -RunId $RunId -Budget $budget
        # One existing managed Python process runs the two real module CLIs from
        # the frozen closure. This is not a new process/registry implementation.
        $code=@'
import importlib.util,json,pathlib,runpy,sys
root=pathlib.Path(sys.argv[1]).resolve()
metadata,state,summary,particles,contract,frequency,phase,report,origins=sys.argv[2:]
modules=['projects.rf_multipole_ion_optics.analysis.analyze_comsol_particle_state_metrics','common.contracts.particle_state','common.contracts.particle_physics']
paths={name:str(pathlib.Path(importlib.util.find_spec(name).origin).resolve()) for name in modules}
if any(not pathlib.Path(path).is_relative_to(root) for path in paths.values()): raise RuntimeError('analysis escaped frozen source')
pathlib.Path(origins).write_text(json.dumps(paths,indent=2)+'\n',encoding='utf-8')
from common.contracts.particle_state import ion11_sources
raw=json.loads(pathlib.Path(metadata).read_text(encoding='utf-8-sig'))
source_ids=sorted(ion11_sources(pathlib.Path(particles),float(raw['source_axial_offset_mm'])))
if raw['source_ids'] != source_ids or sorted(raw['native_order']) != source_ids: raise ValueError('native mapping does not close frozen source cohort')
if any(len(raw[key]) != len(source_ids) for key in ('source_birth_s','source_weights','source_initial_position_mm','source_initial_velocity_m_s')): raise ValueError('native mapping field length differs from source cohort')
sys.argv=['metrics','--raw-metadata',metadata,'--particle-state',state,'--output',summary]
runpy.run_module(modules[0],run_name='__main__')
sys.argv=['state','--state',state,'--particles',particles,'--source-format','ion11','--contract',contract,'--axial-offset-mm',str(raw['source_axial_offset_mm']),'--frequency-hz',frequency,'--phase-rad',phase,'--solver','COMSOL','--output',report]
runpy.run_module(modules[1],run_name='__main__')
'@
        $arguments=@('-B','-c',$code,$frozen.code_root,$metadata,$state,$summary,$config.inputs.particle_table,$config.inputs.interface_contract,[string]$design.drive.frequency_Hz,[string]$design.drive.phase_rad,$contract,$origin)
        $quoted=@($arguments|ForEach-Object{'"'+([string]$_).Replace('"','\"')+'"'})
        try{
            $observed=Invoke-ResourceBudgetedProcess -Limits $Limits -RunDir $package.artifact_run_dir -UsagePath $usage -FilePath $python `
              -ArgumentList $quoted -WorkingDirectory $frozen.code_root -Environment @{PYTHONPATH=$frozen.code_root;PYTHONNOUSERSITE='1';PYTHONDONTWRITEBYTECODE='1'} `
              -RedirectStandardOutput (Join-Path $package.log_dir 'postprocess.stdout.log') -RedirectStandardError (Join-Path $package.log_dir 'postprocess.stderr.log')
            if($observed.root_process_id-le0-or$observed.root_process_started_at_utc_ticks-le0){$ownerState.writer_unknown=$true;throw 'Managed analysis process identity is unknown.'}
            $ownerState.analysis_operations=@(@{operation_id='interface-python-postprocess';resource_release_id='postprocess';observation=@{exit_confirmed=$true;returncode=[int]$observed.exit_code;process_id=[int]$observed.root_process_id;process_started_at_utc_ticks=[long]$observed.root_process_started_at_utc_ticks}})
        }catch{
            $data=$_.Exception.Data
            if($data.Contains('observed_process_exit_confirmed')-and[bool]$data['observed_process_exit_confirmed']-and$data.Contains('observed_process_id')-and$data.Contains('observed_process_started_at_utc_ticks')-and$data.Contains('observed_process_returncode')-and$null-ne$data['observed_process_returncode']-and[long]$data['observed_process_id']-gt0-and[long]$data['observed_process_started_at_utc_ticks']-gt0){
                $ownerState.analysis_operations=@(@{operation_id='interface-python-postprocess';resource_release_id='postprocess';observation=@{exit_confirmed=$true;returncode=[int]$data['observed_process_returncode'];process_id=[int]$data['observed_process_id'];process_started_at_utc_ticks=[long]$data['observed_process_started_at_utc_ticks']}})
            }else{$ownerState.writer_unknown=$true}
            throw
        }
        if($observed.exit_code-ne0-or$observed.resource_budget_exceeded){throw ('Frozen postprocess failed with exit '+$observed.exit_code+'; stderr='+ (Join-Path $package.log_dir 'postprocess.stderr.log')+'; usage='+$usage)}
        $result=@{role='rf_interface_postprocess_summary';execution_status='completed';data_validity='valid';scientific_result='NOT_EVALUATED';gui_verified=$false;parent_request_completed=$false;native_calls=0;new_solve_calls=0;recovery_action='GUI Compute remains a separate requested native solve; not performed by AnalyzeOnly.'}
        $guiEvidence=Join-Path $parentRoot 'results/gui_verification.json'
        if(Test-Path -LiteralPath $guiEvidence -PathType Leaf){
            $phase='saved_gui_report_analysis'
            $guiReceiptPath=Join-Path $parentRoot 'logs/gui_completion.json'
            $guiReceipt=Get-Content $guiReceiptPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
            if($guiReceipt.role-cne'comsol_launcher_completion'-or$guiReceipt.run_id-cne$config.run_id){throw 'Saved GUI native completion identity differs.'}
            $guiReleases=[Collections.Generic.List[object]]::new();$guiReleaseId=if($guiReceipt.host_release.inherited){[string]$guiReceipt.host_release.token}else{'saved-gui'}
            Add-RunArtifactResourceRelease -ResourceReleases $guiReleases -ReleaseId $guiReleaseId -Receipt $guiReceipt
            $guiWriter=@{operations=@($guiReceipt.operations|ForEach-Object{@{operation_id=$_.operation_id;observation=$_.observation;resource_release_id=$guiReleaseId}});resource_releases=@($guiReleases.ToArray())}
            Assert-WorkflowWriterCompletion $guiWriter -PowerShellOwner
            if($guiWriter.operations.Count-ne1){throw 'Saved GUI actual operation count is unconfirmed.'}
            $parentNativeSummary=Get-Content (Join-Path $parentRoot 'results/solver_summary.json') -Raw -Encoding UTF8|ConvertFrom-Json
            $savedGui=Read-InterfaceGuiParityReport -Path (Join-Path $parentRoot 'logs/comsol_gui_compute_report.txt') -ExpectedParticleIds @($raw.source_ids) -ObservationRoot (Join-Path $parentRoot 'results') -ExpectedHits ([int]$parentNativeSummary.hits) -RequireAcceptance $false
            $result.gui_verification=$savedGui;$result.gui_verified=$savedGui.original_acceptance_verified
            $result.parent_gui_launcher_returncode=[int]$guiWriter.operations[0].observation.returncode
            $result.recovery_action='Existing GUI Compute observations re-read; original count/hit PASS or FAIL preserved, numerical equivalence NOT_EVALUATED.'
        }
        Complete-InterfaceOwner -Status success -Summary $result -Outputs @($summary,$contract,$origin,$usage)
    }catch{
        $failure=$_
        if($phase-notin@('postprocess','saved_gui_report_analysis')){$ownerState.prepare_seconds=$ownerState.timer.Elapsed.TotalSeconds}
        if($ownerContext-and-not$ownerState.finalization_started){
            try{Complete-InterfaceOwner -Status failed -Summary @{role='rf_interface_postprocess_summary';execution_status='failed';data_validity='unknown';scientific_result='NOT_EVALUATED';gui_verified=$false;parent_request_completed=$false;native_calls=0;new_solve_calls=0;failure_stage=$phase;failure_reason=$failure.Exception.Message;recovery_action='repair_postprocess_and_create_new_analysis_child'} -Outputs @((Get-ChildItem -LiteralPath $package.result_dir,$package.log_dir -File|ForEach-Object FullName)) -Failure $failure}catch{$failure.Exception.Data['failure_closure_error']=[string]$_}
        }elseif(-not$ownerContext-and$capacity){
            # No native/analysis process was admitted before Initialize. Preserve
            # the primary bootstrap error even if releasing this lease fails.
            try{$null=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity -RemainingCommittedNewBytes 0;$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity}catch{$failure.Exception.Data['bootstrap_release_error']=[string]$_}
        }
        throw $failure
    }finally{Restore-RunEnvironment -Names $names -Snapshot $saved}
}

if($AnalyzeOnly){
    $allowed=@('AnalyzeOnly','ParentManifestPath','StoppedReceiptPath','LimitsPath','RunId','ResultPath','PythonExe')
    $ignored=@($PSBoundParameters.Keys|Where-Object{$_-notin$allowed})
    if($ignored.Count){throw ('AnalyzeOnly consumes parent frozen scientific inputs; new options are not accepted: '+($ignored-join', '))}
    Invoke-InterfacePostprocessChild
    return
}
$ownerContext=$null;$capacity=$null
$ownerState=@{calls=[Collections.Generic.List[object]]::new();writer_unknown=$false;finalization_started=$false;prepare_seconds=0.;timer=[Diagnostics.Stopwatch]::StartNew()}

$workflowId = 'transport_interface_readiness'
$software = @('COMSOL 6.4','MATLAB R2025b','Python 3.11')
if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = if($ReleaseConstructionGate){
        (Get-Date -Format 'yyyyMMdd_HHmmss') +
            '__test__comsol__rf-release-construction__n100'
    }else{
        (Get-Date -Format 'yyyyMMdd_HHmmss') +
            '__sim__comsol__rf-transport__interface-readiness'
    }
}
$package = New-RunPackage -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot $artifactRoot -PathContext $pathContext -RunId $RunId `
    -Project 'rf_multipole_ion_optics' -Mode $workflowId `
    -Software $software -RetentionContractEnabled -RetentionClass solver_review -RetentionReason 'Retain completed native solution and GUI observations for review and zero-Compute analysis recovery.' -CapacityLedgerLifecycleEnabled `
    -AdditionalDirectories @('comsol','runtime') -UseShortExecutionPath `
    -ExpectedExecutionRelativePaths $executionCapacityPaths
$runDir,$inputDir,$resultDir,$logDir = $package.run_dir,$package.input_dir,
    $package.result_dir,$package.log_dir
$candidateDir,$runtimeDir = (Join-Path $runDir 'comsol'),(Join-Path $runDir 'runtime')
$bootstrapReport = Join-Path $logDir 'comsol_bootstrap_report.txt'
$guiVerifyReport = Join-Path $logDir 'comsol_gui_compute_report.txt'
$stateContractReport = Join-Path $resultDir 'particle_state_contract.json'
$releaseGateBreadcrumbs = Join-Path $logDir 'release_construction_breadcrumbs.jsonl'
$releaseGateResult = Join-Path $resultDir 'release_construction_gate.json'
$releaseGateValidation = Join-Path $resultDir `
    'release_construction_gate_validation.json'
$releaseGateModel = Join-Path $candidateDir `
    'rf_multipole_ion_optics__release-construction-gate.mph'
$summaryRole = if ($ReleaseConstructionGate) {
    'rf_release_construction_gate_summary'
} else {
    'rf_quadrupole_transport_summary'
}
$environmentNames = @('SIMULATION_PYTHON_EXE','MASS_SPECTROMETRY_ARTIFACT_ROOT','MASS_SPECTROMETRY_EXECUTION_ROOT','MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH','MASS_SPECTROMETRY_RUN_DIRECTORY','MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY','RFQUAD_RUN_CONFIG','RFQUAD_COMSOL_MODEL_PATH','RFQUAD_SOLVER_RAW_METADATA_PATH','RFQUAD_GUI_RUN_ROOT','RFQUAD_GUI_OBSERVATION_ROOT',
    'RFQUAD_EXPECTED_PARTICLES','RFQUAD_EXPECTED_HITS',
    'RFQUAD_EXPECTED_RF_PEAK_V','RFQUAD_EXPECTED_FREQUENCY_HZ')
$environmentSnapshot = Save-RunEnvironment -Names $environmentNames
$failureStage = 'freeze_inputs'

try {
    $env:SIMULATION_PYTHON_EXE=$python
    $env:MASS_SPECTROMETRY_ARTIFACT_ROOT=[string]$package.path_context.artifact_root
    $env:MASS_SPECTROMETRY_EXECUTION_ROOT=[string]$package.path_context.execution_root
    $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=[string]$package.path_context.host_resource_state_path
    $authority=Join-Path $inputDir 'native_execution_limits.json'
    $null=Copy-VerifiedRunInput -Source $LimitsPath -Destination $authority
    # Consume the verified frozen bytes, not an earlier mutable caller snapshot.
    $Limits=Read-InterfaceExecutionLimits -Path $authority
    $CommittedNewBytes=[long]$Limits.transient_run_directory_bytes
    $ResourceBudgets.solver.memory_bytes=[long]$Limits.process_tree_working_set_bytes
    $hostAuthority=Join-Path $inputDir 'native_host_budgets.json'
    Write-RunJson -Path $hostAuthority -Value $ResourceBudgets -Depth 32
    $entry=Join-Path $inputDir 'interface_owner.ps1'
    $null=Copy-VerifiedRunInput -Source $PSCommandPath -Destination $entry
    $capacity=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -ArtifactRoot ([string]$pathContext.artifact_root) -RunDirectory $package.artifact_run_dir -CommittedNewBytes $CommittedNewBytes -ProtectedPaths @($package.artifact_run_dir) -Owner ('run-artifact-workflow:rf_multipole_ion_optics:'+$RunId)
    $ownerContext=Initialize-RunArtifactPowerShellOwner -Python $python -RepoRoot $repoRoot -Package $package -CapacitySession $capacity -ResultPath $ResultPath -EntrypointPath $entry -CommitmentInputPaths @($authority,$hostAuthority) -Software $software
    $packageOwnedConfig=Get-Content -LiteralPath $package.run_config -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    $officialNumerics = Join-Path $projectRoot 'variants\quadrupole\config\comsol_solver_numerics.json'
    $liveParticleTable = [IO.Path]::GetFullPath($ParticleTablePath)
    $liveBundleMetadata = [IO.Path]::GetFullPath($ParticleBundleMetadataPath)
    $liveSourceFamily = [IO.Path]::GetFullPath($SourceFamilyPath)
    $liveDistribution = [IO.Path]::GetFullPath($ParticleDistributionPath)
    $liveNumerics = if ([IO.Path]::IsPathRooted($SolverNumericsContractPath)) {
        [IO.Path]::GetFullPath($SolverNumericsContractPath)
    } else {
        [IO.Path]::GetFullPath((Join-Path $repoRoot $SolverNumericsContractPath))
    }
    $frozenNumerics = Copy-VerifiedRunInput -Source $officialNumerics `
        -Destination (Join-Path $inputDir 'comsol_solver_numerics.json')
    $numericsCompilation = Compile-RfComsolSolverNumerics `
        -OfficialContractPath $frozenNumerics `
        -RequestedContractPath $liveNumerics `
        -ProfileId $SolverNumericsProfileId `
        -ExperimentAuthorizationId $NumericalExperimentId
    $compiledNumerics = $numericsCompilation.compiled
    foreach ($source in @($liveParticleTable,$liveBundleMetadata,
        $liveSourceFamily,$liveDistribution)) {
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Required interface input is missing: $source"
        }
    }

    $frozenPythonSupport = Copy-VerifiedRunInput `
        -Source (Join-Path $projectRoot 'runtime\frozen_python_package.ps1') `
        -Destination (Join-Path $inputDir 'frozen_python_package.ps1')
    . $frozenPythonSupport
    $publishedDesignFreshness = New-RfPublishedDesignFreshnessPackage `
        -Python $python -SourceRoot $repoRoot `
        -SnapshotRoot (Join-Path $inputDir 'published_design_snapshot') -Profile interface
    $frozenResolved = $publishedDesignFreshness.resolved_path
    $publishedDesignFreshnessPath = Join-Path $inputDir 'published_design_freshness.json'
    Write-RunJson -Path $publishedDesignFreshnessPath -Value $publishedDesignFreshness -Depth 16
    $frozenScientificMode = Copy-VerifiedRunInput `
        -Source (Join-Path $projectRoot 'config\modes\quadrupole_transport_interface_readiness.json') `
        -Destination (Join-Path $inputDir 'transport_interface_readiness.json')
    $frozenInterface = Copy-VerifiedRunInput `
        -Source (Join-Path $projectRoot 'variants\quadrupole\config\interface_contract.json') `
        -Destination (Join-Path $inputDir 'interface_contract.json')
    $frozenSourceFamily = Copy-VerifiedRunInput -Source $liveSourceFamily `
        -Destination (Join-Path $inputDir 'particle_source_family.json')
    $frozenDistribution = Copy-VerifiedRunInput -Source $liveDistribution `
        -Destination (Join-Path $inputDir 'particle_source_distribution.json')
    $frozenMatlabRelativePaths=@(
        'common/comsol/create_multipole_round_rods.m',
        'common/comsol/configure_comsol_mesh.m',
        'common/comsol/add_comsol_size_feature.m',
        'common/comsol/read_comsol_mesh_size_controls.m',
        'projects/rf_multipole_ion_optics/load_rf_quadrupole_contract.m',
        'projects/rf_multipole_ion_optics/comsol/solve_deterministic_rf_quadrupole_particles.m',
        'projects/rf_multipole_ion_optics/comsol/compare_rf_gui_observations.m',
        'projects/rf_multipole_ion_optics/comsol/classify_finite_particle_terminal.m',
        'projects/rf_multipole_ion_optics/comsol/visit_rf_particle_windows.m',
        'projects/rf_multipole_ion_optics/comsol/extract_rf_particle_records.m',
        'projects/rf_multipole_ion_optics/comsol/plan_rf_exact_birth_releases.m',
        'projects/rf_multipole_ion_optics/comsol/prepare_interface_readiness_run.m',
        'projects/rf_multipole_ion_optics/workflows/interface_readiness/comsol/run_nocollision_candidate.m',
        'projects/rf_multipole_ion_optics/workflows/interface_readiness/comsol/verify_nocollision_comsol.m',
        'projects/rf_multipole_ion_optics/comsol/interface_readiness/run_release_construction_gate.m'
    )
    $frozenCodeRoot = Join-Path $inputDir 'code'
    $frozenPythonPackage = New-FrozenPythonPackage `
        -SourceRoot $repoRoot -CodeRoot $frozenCodeRoot -RelativePaths @($frozenPythonRelativePaths+$frozenMatlabRelativePaths)
    $frozenParticlePolicy = Get-FrozenPythonPackageFile `
        -Package $frozenPythonPackage -RelativePath `
        'projects/rf_multipole_ion_optics/workflows/interface_readiness/particle_source_policy.py'
    $frozenParticleGenerator = Get-FrozenPythonPackageFile `
        -Package $frozenPythonPackage -RelativePath `
        'projects/rf_multipole_ion_optics/workflows/interface_readiness/generate_particle_table.py'
    $frozenBundleMechanism = Get-FrozenPythonPackageFile `
        -Package $frozenPythonPackage -RelativePath `
        'projects/rf_multipole_ion_optics/analysis/paired_particle_source_bundle.py'
    $frozenReleaseGateValidator = Get-FrozenPythonPackageFile `
        -Package $frozenPythonPackage -RelativePath `
        'projects/rf_multipole_ion_optics/analysis/validate_release_construction_gate.py'

    $bundleDocument = Get-Content -LiteralPath $liveBundleMetadata -Raw -Encoding UTF8 |
        ConvertFrom-Json
    $bundleArtifacts = Get-RfComsolRequiredProperty -Object $bundleDocument `
        -Property 'artifacts' -Name 'paired particle bundle artifacts'
    if ($bundleArtifacts.Count -eq 0) {throw 'Paired particle bundle artifacts must not be empty.'}
    $liveBundleRoot = [IO.Path]::GetFullPath((Split-Path -Parent $liveBundleMetadata))
    $frozenBundleRoot = Join-Path $inputDir 'paired_bundle'
    New-Item -ItemType Directory -Path $frozenBundleRoot -Force | Out-Null
    $frozenBundleMetadata = Copy-VerifiedRunInput -Source $liveBundleMetadata `
        -Destination (Join-Path $frozenBundleRoot 'paired_particle_bundle.json')
    $bundleInputPaths = [ordered]@{}
    $bundleIndex = 0
    foreach ($entry in $bundleArtifacts) {
        $relativePath=[string](Get-RfComsolRequiredProperty -Object $entry `
            -Property 'relative_path' -Name 'paired particle artifact relative_path')
        $sourceArtifact = [IO.Path]::GetFullPath((Join-Path $liveBundleRoot $relativePath))
        if (-not $sourceArtifact.StartsWith($liveBundleRoot+
            [IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) {
            throw "Paired particle artifact escapes its bundle root: $relativePath"
        }
        $frozenArtifact = Copy-VerifiedRunInput -Source $sourceArtifact `
            -Destination (Join-Path $frozenBundleRoot $relativePath)
        $bundleIndex += 1
        $bundleInputPaths[("bundle_artifact_{0:D3}" -f $bundleIndex)] = $frozenArtifact
    }
    $frozenPythonExecution = Invoke-IsolatedFrozenPythonModule `
        -Python $python -Package $frozenPythonPackage `
        -Module `
        'projects.rf_multipole_ion_optics.workflows.interface_readiness.generate_particle_table' `
        -Arguments @(
            '--source-family',$frozenSourceFamily,
            '--distribution',$frozenDistribution,
            '--resolved-design',$frozenResolved,
            '--validate-bundle',$frozenBundleMetadata
        ) -DistributionNames @('numpy') -RequiredModuleNames @(
            'projects.rf_multipole_ion_optics.workflows',
            'projects.rf_multipole_ion_optics.workflows.interface_readiness',
            'projects.rf_multipole_ion_optics.workflows.interface_readiness.generate_particle_table',
            'projects.rf_multipole_ion_optics.workflows.interface_readiness.particle_source_policy',
            'projects.rf_multipole_ion_optics.analysis.paired_particle_source_bundle',
            'common.contracts.particle_physics',
        'common.contracts.particle_count_policy',
        'common.contracts.file_identity',
        'common.ion_release',
        'common.ion_release.numpy_ion11_box',
        'projects.rf_multipole_ion_optics.core',
            'projects.rf_multipole_ion_optics.core.interface_geometry',
            'projects.rf_multipole_ion_optics.runtime.particle_source_preflight'
        ) -ForbiddenRoots @($repoRoot,$projectRoot)

    $ionEntry = @($bundleArtifacts | Where-Object {
        $_.operating_point_id -eq $OperatingPoint -and
        [IO.Path]::GetFullPath((Join-Path $liveBundleRoot ([string]$_.relative_path))) -eq
            $liveParticleTable -and
        $_.representation -eq 'ion11'
    })
    if ($ionEntry.Count-ne 1){throw 'Explicit particle table is not one unique ION11 bundle artifact.'}
    $expectedParticles = [int]$ionEntry[0].particle_count
    $canonicalEntry = @($bundleArtifacts | Where-Object {
        $_.operating_point_id -eq $OperatingPoint -and
        [int]$_.particle_count -eq $expectedParticles -and
        $_.representation -eq 'canonical10'
    })
    if ($canonicalEntry.Count-ne 1){throw 'The paired canonical10 bundle artifact is not unique.'}
    $particleTable = Join-Path $frozenBundleRoot ([string]$ionEntry[0].relative_path)
    $frozenCanonicalPath = Join-Path $frozenBundleRoot `
        ([string]$canonicalEntry[0].relative_path)
    $actualParticleCount = @(
        Get-Content -LiteralPath $particleTable -Encoding UTF8 |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    ).Count
    if ($actualParticleCount-ne$expectedParticles){throw 'Frozen ION11 row count differs from metadata.'}
    if($ReleaseConstructionGate -and $expectedParticles-ne 100){
        throw 'Release-construction gate requires exactly N=100.'}

    $mode = Get-Content -LiteralPath $frozenScientificMode -Raw -Encoding UTF8 |
        ConvertFrom-Json
    if([string]$mode.mode-cne$workflowId -or
       [string]$mode.physics.collision_model-cne'none' -or
       [bool]$mode.physics.mass_filter_dc -or [bool]$mode.physics.space_charge){
        throw 'Frozen interface scientific mode is not RF-only no-collision transport.'
    }
    if ($mode.numerics.PSObject.Properties['maximum_time_us'] -or
        $mode.numerics.PSObject.Properties['comsol_rf_steps_per_period'] -or
        $mode.numerics.PSObject.Properties['comsol_mesh_auto_level']) {
        throw 'Scientific mode must not contain COMSOL solver numerics.'
    }
    $minimumParticles = [int](Get-RfComsolRequiredFiniteNumber `
        -Object $mode.numerics -Property 'minimum_diagnostic_particles' `
        -Name 'interface minimum_diagnostic_particles' -Positive -Integer)
    $minimumTransmission = Get-RfComsolRequiredFiniteNumber `
        -Object $mode.candidate_acceptance_targets -Property 'minimum_transmission' `
        -Name 'interface minimum_transmission'
    $maximumRadiusFraction = Get-RfComsolRequiredFiniteNumber `
        -Object $mode.candidate_acceptance_targets `
        -Property 'maximum_allowed_radius_fraction_r0' `
        -Name 'interface maximum_allowed_radius_fraction_r0' -Positive
    if($minimumTransmission-lt 0 -or $minimumTransmission-gt 1){
        throw 'Interface minimum_transmission must be in [0, 1].'}
    $resolved = Get-Content -LiteralPath $frozenResolved -Raw -Encoding UTF8 |
        ConvertFrom-Json
    if ([double]$resolved.drive.dc_amplitude_V_per_group -ne 0 -or
        [double]$resolved.drive.common_mode_offset_V -ne 0 -or
        [double]$resolved.static_electrodes_V.entrance_aperture_plate_and_connector_V -ne 0 -or
        [double]$resolved.static_electrodes_V.exit_outer_enclosure_and_connector_V -ne 0 -or
        [double]$resolved.static_electrodes_V.physical_detector_V -ne 0) {
        throw 'Interface resolved design is not RF-only.'
    }

    $sourceBinding = Join-Path $inputDir 'particle_source_binding.json'
    $bindingArguments = @(
        '-m','projects.rf_multipole_ion_optics.analysis.validate_paired_particle_source_binding',
        '--bundle-metadata',$frozenBundleMetadata,
        '--source-family',$frozenSourceFamily,
        '--distribution',$frozenDistribution,
        '--resolved-design',$frozenResolved,
        '--operating-point',$OperatingPoint,
        '--particle-count',$expectedParticles,
        '--consumed-representation','ion11',
        '--expected-consumed',$particleTable,
        '--output',$sourceBinding
    )
    Push-Location $repoRoot
    try {
        & $python @bindingArguments
        if($LASTEXITCODE-ne 0){throw 'Frozen paired particle source bundle binding failed.'}
    } finally {
        Pop-Location
    }
    $bindingDocument = Get-Content -LiteralPath $sourceBinding -Raw -Encoding UTF8 |
        ConvertFrom-Json
    $compiledScientificSpec = [ordered]@{
        role='rf_quadrupole_comsol_interface_scientific_spec';workflow_id=$workflowId
        claim = 'RF-only no-collision interface transport and canonical state export'
        collision_model='none';mass_filter_dc=$false;space_charge=$false
        source_axial_offset_mm=0.0;minimum_transmission=[double]$minimumTransmission
        maximum_allowed_radius_fraction_r0=[double]$maximumRadiusFraction
        resolved_design_sha256=Get-RunFileSha256 -Path $frozenResolved
        interface_contract_sha256=Get-RunFileSha256 -Path $frozenInterface
        scientific_mode_sha256=Get-RunFileSha256 -Path $frozenScientificMode
    }
    $runConfig = [ordered]@{
        schema_version=$packageOwnedConfig.schema_version;role='rf_quadrupole_comsol_run_config';run_id=$RunId
        project='rf_multipole_ion_optics';workflow_id=$workflowId
        mode=$workflowId;project_root=$repoRoot
        inputs = [ordered]@{
            published_design_freshness=$publishedDesignFreshnessPath;resolved_design=$frozenResolved;scientific_mode=$frozenScientificMode
            interface_contract=$frozenInterface;comsol_solver_numerics=$frozenNumerics
            particle_table=$particleTable
            consumed_particle_table=$particleTable
            source_ion11=$particleTable
            source_canonical10=$frozenCanonicalPath
            particle_bundle_metadata=$frozenBundleMetadata;particle_source_binding=$sourceBinding
            particle_source_family=$frozenSourceFamily
            particle_source_distribution=$frozenDistribution
            particle_source_policy=$frozenParticlePolicy
            particle_source_generator=$frozenParticleGenerator
            paired_particle_source_mechanism=$frozenBundleMechanism
            release_construction_gate_validator=$frozenReleaseGateValidator
            frozen_python_package_support=$frozenPythonSupport
        }
        frozen_python=[ordered]@{
            package=$frozenPythonPackage
            execution=$frozenPythonExecution
        }
        compiled_scientific_spec=$compiledScientificSpec
        compiled_solver_numerics=$compiledNumerics
        solver_numerics_contract_id=$compiledNumerics.authority.contract_id
        solver_numerics_contract_logical_sha256=$compiledNumerics.authority.logical_sha256
        solver_numerics_profile_id=$compiledNumerics.selection.profile_id
        numerical_experiment_id=$compiledNumerics.selection.numerical_experiment_id
        operating_point=$OperatingPoint;particles=$expectedParticles
        comsol_rf_steps_per_period=$compiledNumerics.trajectory.rf_steps_per_period
        comsol_mesh_auto_level=$compiledNumerics.mesh.global_auto_level
        maximum_time_us=$compiledNumerics.trajectory.maximum_time_us
        output_policy=[ordered]@{save_model=$true;write_detailed_outputs=$true}
        results_dir=$resultDir;comsol_dir=$candidateDir;logs_dir=$logDir
        runtime_dir=$runtimeDir;run_dir=$runDir;formal_gate_passed=$false
        parameters=[ordered]@{
            lifecycle_stage='inputs_frozen_and_validated'
            execution_stage=if($ReleaseConstructionGate){
                'release_construction_gate'
            }else{
                'full_particle_transport'
            }
        }
        provenance = [ordered]@{
            solver_numerics_sha256=Get-RunFileSha256 -Path $frozenNumerics
            source_sample_family_sha256=[string]$bindingDocument.source_sample_family_sha256
            source_family_sha256=[string]$bindingDocument.source_family_sha256
            distribution_sha256=[string]$bindingDocument.distribution_sha256
            latent_sha256=[string]$bindingDocument.latent_sha256
            coordinate_mapping_version=[string]$bindingDocument.coordinate_mapping_version
            representation_equivalence=[string]$bindingDocument.representation_equivalence
            operating_point_id=$OperatingPoint;particle_count=$expectedParticles
            representation='ion11';consumed_sha256=[string]$bindingDocument.consumed_sha256
            particle_source_sha256=[string]$bindingDocument.consumed_sha256
            ion11_sha256=[string]$bindingDocument.ion11_sha256
            canonical10_sha256=[string]$bindingDocument.canonical10_sha256
            n1000_parent=$bindingDocument.n1000_parent
            ion11_n1000_parent=$bindingDocument.ion11_n1000_parent
            canonical10_n1000_parent=$bindingDocument.canonical10_n1000_parent
        }
    }
    foreach ($key in $bundleInputPaths.Keys) {
        $runConfig.inputs[$key] = $bundleInputPaths[$key]
    }
    $frozenCodeIndex = 0
    foreach ($entry in $frozenPythonPackage.files) {
        $frozenCodeIndex += 1
        $runConfig.inputs[("frozen_python_code_{0:D3}" -f $frozenCodeIndex)] = `
            [string]$entry.path
    }
    foreach($key in $packageOwnedConfig.Keys){if(-not$runConfig.Contains($key)){$runConfig[$key]=$packageOwnedConfig[$key]}}
    $runConfig.inputs.execution_request=$ownerContext.request_path
    $runConfig.inputs.native_execution_limits=$authority
    $runConfig.inputs.native_host_budgets=$hostAuthority
    $runConfig.parameters.startup_attempts=$StartupAttempts
    Write-RunJson -Value $runConfig -Path $package.run_config
    Write-RunJson -Path $package.summary -Value ([ordered]@{
        schema_version=1;role=$summaryRole;status='interrupted'
        failure_stage='commercial_execution_not_started';threshold_result_eligible=$false
        reason='Frozen inputs and COMSOL numerics passed preflight.'
    })

    $failureStage = if($ReleaseConstructionGate){
        'comsol_release_construction_gate'
    }else{
        'comsol_model_build'
    }
    $env:RFQUAD_RUN_CONFIG = $package.run_config
    $taskScript = if($ReleaseConstructionGate){
        Join-Path $frozenCodeRoot `
            'projects/rf_multipole_ion_optics/comsol/interface_readiness/run_release_construction_gate.m'
    }else{
        Join-Path $frozenCodeRoot 'projects/rf_multipole_ion_optics/workflows/interface_readiness/comsol/run_nocollision_candidate.m'
    }
    Invoke-InterfaceComsolTask -Task $taskScript -Report $bootstrapReport -Stage native -State $ownerState
    [Environment]::SetEnvironmentVariable('RFQUAD_RUN_CONFIG',$null)

    if($ReleaseConstructionGate){
        $failureStage = 'release_construction_gate_contract'
        foreach($expected in @(
            $releaseGateBreadcrumbs,
            $releaseGateResult,
            $releaseGateModel,
            $bootstrapReport
        )){
            if(-not(Test-Path -LiteralPath $expected -PathType Leaf)){
                throw "Release-construction gate output is missing: $expected"}
        }
        $gateResult=Get-Content -LiteralPath $releaseGateResult -Raw -Encoding UTF8 |
            ConvertFrom-Json
        $breadcrumbLines=@(
            Get-Content -LiteralPath $releaseGateBreadcrumbs -Encoding UTF8 |
                Where-Object{-not[string]::IsNullOrWhiteSpace($_)}
        )
        $releaseFiles=@(
            Get-ChildItem -LiteralPath $runtimeDir -File -Filter 'particle_*.txt' |
                Sort-Object Name
        )
        $groupCount=[int]$gateResult.release_tag_count
        if($groupCount-lt 1 -or $groupCount-gt 100){throw 'Invalid grouped release count.'}
        $expectedReleaseNames=@(
            1..$groupCount|ForEach-Object{'particle_{0:D3}.txt'-f$_}
        )
        $releaseNameDifference=@(
            Compare-Object -ReferenceObject $expectedReleaseNames `
                -DifferenceObject ([string[]]$releaseFiles.Name) -CaseSensitive
        )
        if([int]$gateResult.schema_version-ne 2 -or [string]$gateResult.status-cne'success' -or
           [string]$gateResult.role-cne'rf_release_construction_gate_result' -or
           [int]$gateResult.particles-ne 100 -or
           [int]$gateResult.release_tag_count-ne $groupCount -or
           [int]$gateResult.release_file_count-ne $groupCount -or
           [int]$gateResult.birth_time_count-ne 100 -or
           [int]$gateResult.unique_birth_time_count-ne $groupCount -or
           [int]$gateResult.unique_release_time_expression_count-ne $groupCount -or
           [int]$gateResult.breadcrumb_count-ne ($groupCount*10) -or
           [string]$gateResult.first_release_tag-cne'rel001' -or
           [string]$gateResult.last_release_tag-cne('rel{0:D3}'-f$groupCount) -or
           -not [bool]$gateResult.stationary_study_present -or
           -not [bool]$gateResult.stationary_solver_present -or
           [bool]$gateResult.electric_force_present -or
           [bool]$gateResult.particle_study_present -or
           [bool]$gateResult.particle_solver_present){
            throw 'Release-construction gate result violates the fixed N=100 contract.'}
        if(-not [string]::Equals(
            [string]$gateResult.particle_table_sha256,
            [string]$runConfig.provenance.particle_source_sha256,
            [StringComparison]::OrdinalIgnoreCase)){
            throw 'Release-construction gate particle-table SHA-256 differs from the frozen binding.'}
        if($releaseFiles.Count-ne $groupCount -or $releaseNameDifference.Count-ne 0){
            throw 'Release-construction gate did not preserve particle_001..particle_100.'}
        if($breadcrumbLines.Count-ne ($groupCount*10)){
            throw 'Release-construction gate did not preserve all 1000 durable breadcrumbs.'}
        $gateValidationExecution=Invoke-IsolatedFrozenPythonModule `
            -Python $python -Package $frozenPythonPackage `
            -Module `
            'projects.rf_multipole_ion_optics.analysis.validate_release_construction_gate' `
            -Arguments @(
                '--run-config',$package.run_config,
                '--particle-table',$particleTable,
                '--breadcrumbs',$releaseGateBreadcrumbs,
                '--result',$releaseGateResult,
                '--runtime-dir',$runtimeDir,
                '--output',$releaseGateValidation
            ) -DistributionNames @() -RequiredModuleNames @(
                'projects.rf_multipole_ion_optics.analysis.validate_release_construction_gate'
            ) -ForbiddenRoots @($repoRoot,$projectRoot)
        if(-not(Test-Path -LiteralPath $releaseGateValidation -PathType Leaf)){
            throw 'Frozen release-construction validator did not create its report.'}
        $gateValidation=Get-Content -LiteralPath $releaseGateValidation `
            -Raw -Encoding UTF8|ConvertFrom-Json
        if([string]$gateValidation.status-cne'success' -or
           [int]$gateValidation.particles-ne 100 -or
           [int]$gateValidation.release_files-ne $groupCount -or
           [int]$gateValidation.release_time_expressions-ne $groupCount -or
           [int]$gateValidation.breadcrumbs-ne ($groupCount*10)){
            throw 'Frozen release-construction validator did not close Gate A artifacts.'}
        Write-RunJson -Path $package.summary -Value ([ordered]@{
            schema_version=1;role=$summaryRole;status='success'
            workflow_id=$workflowId;execution_stage='release_construction_gate'
            particles=100;release_tags=$groupCount;release_files=$groupCount
            unique_birth_times=$gateResult.unique_birth_time_count;unique_release_time_expressions=$gateResult.unique_release_time_expression_count
            particle_study_present=$false;particle_solver_present=$false
            threshold_result_eligible=$false
            result='results/release_construction_gate.json'
        })
        $runConfig.parameters.lifecycle_stage='complete'
        $runConfig.frozen_python.release_construction_gate_validation=`
            $gateValidationExecution
        Write-RunJson -Value $runConfig -Path $package.run_config
        $outputs=@($releaseGateModel,$releaseGateResult,$releaseGateBreadcrumbs,
            $releaseGateValidation,$bootstrapReport,$package.summary)
        $outputs+=@($releaseFiles|Select-Object -ExpandProperty FullName)
        $publicSummary=Get-Content $package.summary -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
        $publicSummary.execution_status='completed';$publicSummary.data_validity='valid';$publicSummary.scientific_result='NOT_EVALUATED'
        Complete-InterfaceOwner -Status success -Summary $publicSummary -Outputs $outputs
        "STATUS=PASS RUN_ID=$RunId EXECUTION_STAGE=release_construction_gate RELEASE_TAGS=$groupCount"
        return
    }

    $modelPath=Join-Path $candidateDir 'rf_multipole_ion_optics__model.mph'
    $summaryPath=Join-Path $resultDir 'solver_summary.json'
    $rawMetadataPath=Join-Path $resultDir 'solver_raw_metadata.json'
    $trajectoryPath,$particleStatePath,$rawPhaseSpacePath =
        (Join-Path $resultDir 'trajectory_samples.csv'),
        (Join-Path $resultDir 'particle_state.csv'),(Join-Path $resultDir 'particle_raw.csv')
    foreach ($expected in @(
        $modelPath,
        $rawMetadataPath,
        $trajectoryPath,
        $particleStatePath,
        $rawPhaseSpacePath,
        $bootstrapReport
    )) {
        if(-not(Test-Path -LiteralPath $expected -PathType Leaf)){
            throw "COMSOL interface output is missing: $expected"}
    }
    $failureStage = 'python_particle_state_metrics'
    $metricsExecution=Invoke-IsolatedFrozenPythonModule -Python $python -Package $frozenPythonPackage `
        -Module 'projects.rf_multipole_ion_optics.analysis.analyze_comsol_particle_state_metrics' `
        -Arguments @('--raw-metadata',$rawMetadataPath,'--particle-state',$particleStatePath,'--output',$summaryPath) `
        -RequiredModuleNames @('projects.rf_multipole_ion_optics.analysis.analyze_comsol_particle_state_metrics') -ForbiddenRoots @($repoRoot)
    $runConfig.frozen_python.metrics_analysis=$metricsExecution
    Write-RunJson -Value $runConfig -Path $package.run_config
    if(-not(Test-Path -LiteralPath $summaryPath -PathType Leaf)){
        throw 'Python COMSOL particle-state metrics did not create solver_summary.json.'}
    $solverSummary = Get-Content -LiteralPath $summaryPath -Raw -Encoding UTF8 |
        ConvertFrom-Json

    $failureStage = 'comsol_gui_compute_verification'
    $env:RFQUAD_GUI_RUN_ROOT = [string]$package.artifact_run_dir
    $env:RFQUAD_GUI_OBSERVATION_ROOT=Join-Path $package.artifact_run_dir 'results'
    $env:RFQUAD_COMSOL_MODEL_PATH = Join-Path $env:RFQUAD_GUI_RUN_ROOT 'comsol/rf_multipole_ion_optics__model.mph'
    $env:RFQUAD_SOLVER_RAW_METADATA_PATH = Join-Path $env:RFQUAD_GUI_RUN_ROOT 'results/solver_raw_metadata.json'
    $env:RFQUAD_EXPECTED_PARTICLES = [string]$expectedParticles
    $env:RFQUAD_EXPECTED_HITS = [string]$solverSummary.hits
    $env:RFQUAD_EXPECTED_RF_PEAK_V = [string]$resolved.drive.rf_amplitude_V_zero_to_peak_per_group
    $env:RFQUAD_EXPECTED_FREQUENCY_HZ = [string]$resolved.drive.frequency_Hz
    Invoke-InterfaceComsolTask -Task (Join-Path $frozenCodeRoot 'projects/rf_multipole_ion_optics/workflows/interface_readiness/comsol/verify_nocollision_comsol.m') -Report $guiVerifyReport -Stage gui -State $ownerState
    $failureStage='comsol_gui_observed_parity_report'
    $guiParity=Read-InterfaceGuiParityReport -Path $guiVerifyReport -ExpectedParticleIds @($solverSummary.source_ids) -ObservationRoot (Join-Path $package.artifact_run_dir 'results') -ExpectedHits ([int]$solverSummary.hits)
    foreach ($name in $environmentNames | Where-Object {
        $_ -ne 'RFQUAD_RUN_CONFIG'
    }) {
        [Environment]::SetEnvironmentVariable($name,$null)
    }

    $failureStage = 'particle_state_contract'
    $stateContractExecution=Invoke-IsolatedFrozenPythonModule -Python $python -Package $frozenPythonPackage `
        -Module 'common.contracts.particle_state' `
        -Arguments @('--state',$particleStatePath,'--particles',$particleTable,'--source-format','ion11',
            '--contract',$frozenInterface,'--axial-offset-mm','0','--frequency-hz',([string]$resolved.drive.frequency_Hz),
            '--phase-rad',([string]$resolved.drive.phase_rad),'--solver','COMSOL','--output',$stateContractReport) `
        -RequiredModuleNames @('common.contracts.particle_state','common.contracts.particle_physics') -ForbiddenRoots @($repoRoot)
    $runConfig.frozen_python.particle_state_contract=$stateContractExecution
    Write-RunJson -Value $runConfig -Path $package.run_config

    $failureStage = 'success_manifest'
    Write-RunJson -Path $package.summary -Value ([ordered]@{
        schema_version=1;role='rf_quadrupole_transport_summary';status='success'
        workflow_id=$workflowId;particles=$expectedParticles;hits=$solverSummary.hits
        transmission=$solverSummary.transmission
        mean_output_energy_eV=$solverSummary.mean_output_energy_eV
        solver_summary='results/solver_summary.json'
    })
    $runConfig.parameters.lifecycle_stage = 'complete'
    Write-RunJson -Value $runConfig -Path $package.run_config
    $outputs = @((Join-Path $resultDir 'gui_verification.json'),(Join-Path $resultDir 'gui_source_binding.json'),(Join-Path $resultDir 'gui_observations_saved.mat'),(Join-Path $resultDir 'gui_observations_computed.mat'),(Join-Path $resultDir 'release_source_mapping.json'),$modelPath,$rawMetadataPath,$summaryPath,$trajectoryPath,$particleStatePath,
        $rawPhaseSpacePath,$bootstrapReport,$guiVerifyReport,$stateContractReport,
        $package.summary)
    $publicSummary=Get-Content $package.summary -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    $publicSummary.execution_status='completed';$publicSummary.data_validity='valid';$publicSummary.scientific_result='NOT_EVALUATED'
    $publicSummary.gui_verification=$guiParity
    Complete-InterfaceOwner -Status success -Summary $publicSummary -Outputs $outputs
    "STATUS=PASS RUN_ID=$RunId HITS=$($solverSummary.hits) TRANSMISSION=$($solverSummary.transmission)"
} catch {
    $interfaceFailure = $_
    $failureReason = "$failureStage`: $($_.Exception.Message)"
    if($ownerContext-and-not$ownerContext.completion_written-and-not$ownerState.finalization_started){
        try{
            $failed=@{role=$summaryRole;execution_status='failed';data_validity='unknown';scientific_result='NOT_EVALUATED';failure_stage=$failureStage;failure_reason=$failureReason;recovery_action='inspect_failure'}
            $failedOutputs=@(Get-ChildItem -LiteralPath $resultDir,$candidateDir,$logDir -File -ErrorAction SilentlyContinue|ForEach-Object FullName)
            Complete-InterfaceOwner -Status failed -Summary $failed -Outputs $failedOutputs -Failure $interfaceFailure
        }catch{$interfaceFailure.Exception.Data['failure_closure_error']=[string]$_;Write-Warning "Interface failure closure: $($_.Exception.Message)"}
    }
    throw $interfaceFailure
} finally {
    Restore-RunEnvironment -Names $environmentNames -Snapshot $environmentSnapshot
    # The common owner owns retention, capacity release, alias removal and sealing.
    # An uninitialized owner retains any active admission for explicit inspection.
    if(-not$ownerContext-and$capacity){Write-Warning 'Public owner initialization failed; inspect retained capacity session before cleanup.'}
}
