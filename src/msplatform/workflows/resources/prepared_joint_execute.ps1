[CmdletBinding(DefaultParameterSetName='Analysis')]
param(
  [Parameter(Mandatory,ParameterSetName='Analysis')][string]$AnalyzeRunPath,
  [Parameter(Mandatory,ParameterSetName='Analysis')][string]$ContractPath,
  [Parameter(Mandatory,ParameterSetName='Resume')][switch]$ResumeFinalization,
  [string]$ResultPath='',
  [string]$RunId='',
  [string]$PythonExe='',
  [string]$RepoRoot=''
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$researchRootExplicit=[bool]$RepoRoot
$repoRoot=if($RepoRoot){(Resolve-Path -LiteralPath $RepoRoot).Path}else{(Get-Location).Path}
$packageRoot=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $PSScriptRoot '../../execution/resources/require_powershell7.ps1')
$projectId='instrument_assembly'
$workspaceRoot=if($researchRootExplicit){Split-Path -Parent $repoRoot}else{$repoRoot}
$packageParent=Split-Path -Parent $packageRoot
$script:pythonRoot=$packageParent
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}elseif($env:SIMULATION_PYTHON_EXE){[IO.Path]::GetFullPath($env:SIMULATION_PYTHON_EXE)}else{throw 'Explicit PythonExe or SIMULATION_PYTHON_EXE is required'}
if(-not(Test-Path -LiteralPath $python -PathType Leaf)){throw "Python executable is missing: $python"}
$packageRootText=& $python -I -B -c 'from pathlib import Path;import msplatform;print(Path(msplatform.__file__).resolve().parent)'
if($LASTEXITCODE-ne0-or[string]::IsNullOrWhiteSpace([string]$packageRootText)){throw 'Installed msplatform package is unavailable.'}
$selectedPackageRoot=(Resolve-Path -LiteralPath ([string]$packageRootText).Trim()).Path
if(-not$researchRootExplicit-and-not[string]::Equals($selectedPackageRoot,[IO.Path]::GetFullPath($packageRoot),[StringComparison]::OrdinalIgnoreCase)){throw 'Selected Python msplatform package differs from the entry package.'}
$executionResources=Join-Path $packageRoot 'execution/resources'
. (Join-Path $executionResources 'workspace_paths.ps1')
$pathContext=Resolve-WorkspacePaths -SourceRoot $repoRoot -Python $python
$projectArtifacts=Resolve-RunArtifactRoot -ArtifactRoot ([string]$pathContext.artifact_root) -OwnerKind assembly -OwnerId $projectId -Python $python
$hostContext=@{workspace=$workspaceRoot;python_executable=$python;host_state_path=[string]$pathContext.host_resource_state_path;policy_path=(Join-Path $executionResources 'host_resource_policy.json')}
. (Join-Path $executionResources 'host_execution_lease.ps1') -HostContext $hostContext
. (Join-Path $PSScriptRoot 'run_artifact_workflow.ps1') -ResultPath $ResultPath -ResumeFinalization:$ResumeFinalization
if($ResumeFinalization){
  if(-not$RunId){throw 'Finalization recovery requires the existing RunId.'}
  if(-not$ResultPath){$ResultPath=Join-Path $projectArtifacts "scratch/workflow_results/$RunId/result.json"}
  $recoveryRun=Join-Path $projectArtifacts "runs/$RunId"
  if(Test-Path -LiteralPath $ResultPath -PathType Leaf){
    $transport=Get-Content -LiteralPath $ResultPath -Raw|ConvertFrom-Json -AsHashtable
    if($transport.role-ne'run_artifact_workflow_result'-or(Split-Path -Leaf ([string]$transport.run_directory))-cne$RunId){throw 'Prepared-joint recovery Result identity differs.'}
    $recoveryRun=[string]$transport.run_directory
  }
  $result=Invoke-RunArtifactWorkflow -RequestPath (Join-Path $recoveryRun 'inputs/execution_request.json') -ResultPath $ResultPath -ResumeFinalization
  Write-Output $result
  if($result.status-ne'success'){throw 'Prepared-joint finalization remains incomplete; inspect Result recovery action.'}
  return
}
$script:preparedPackage=$null
function Invoke-ProjectPython {
  param([string[]]$Arguments,$FrozenPackage=$null)
  $authorRoot=$repoRoot
  $root=$script:pythonRoot;$environment=@{}
  if($null-ne$script:preparedPackage){
    $execution=Get-RunNativeExecutionContext -Package $script:preparedPackage -Paths @($root) -Tool Python
    $root=[string]$execution.projected_paths[0];$environment=$execution.environment
  }
  Invoke-RunToolRootContext -RepoRoot $root -Environment $environment -Operation {
    if($null-eq$FrozenPackage){
      & $python -B @Arguments
      if($LASTEXITCODE-ne0){throw "Python stage failed: $($Arguments -join ' ')"}
    }else{
      if($Arguments.Count-lt3-or$Arguments[0]-cne'-m'){throw 'Frozen prepared-joint invocation requires a module and arguments.'}
      $files=@(foreach($identity in @($FrozenPackage.identities)+@($FrozenPackage.dependency_contract_identity)){
        $relative=[IO.Path]::GetRelativePath([string]$FrozenPackage.execution_root,[string]$identity.snapshot_path)
        if([IO.Path]::IsPathRooted($relative)-or$relative-eq'..'-or$relative.StartsWith('..'+[IO.Path]::DirectorySeparatorChar)){throw 'Frozen dependency is outside the selected execution root.'}
        [pscustomobject]@{path=(Join-Path $root $relative);relative_path=$relative.Replace('\','/');sha256=([string]$identity.sha256).ToUpperInvariant()}
      })
      $roots=@(foreach($packageRoot in $FrozenPackage.import_roots){
        $relative=[IO.Path]::GetRelativePath([string]$FrozenPackage.execution_root,[string]$packageRoot)
        if([IO.Path]::IsPathRooted($relative)-or$relative-eq'..'-or$relative.StartsWith('..'+[IO.Path]::DirectorySeparatorChar)){throw 'Frozen import root escapes the selected execution root.'}
        if($relative-eq'.'){$root}else{Join-Path $root $relative}
      })
      $view=[pscustomobject]@{code_root=$root;package_roots=$roots;files=$files}
      $helperRelative='src/msplatform/execution/resources/frozen_python_package.ps1'
      $helper=@($files|Where-Object{$_.relative_path-ceq$helperRelative})
      if($helper.Count-ne1-or-not(Test-Path -LiteralPath $helper[0].path -PathType Leaf)-or
          (Get-FileHash -LiteralPath $helper[0].path -Algorithm SHA256).Hash-cne$helper[0].sha256){throw 'Frozen Python executor identity differs.'}
      . $helper[0].path
      try{
        $result=Invoke-IsolatedFrozenPythonModule -Python $python -Package $view -Module $Arguments[1] -Arguments @($Arguments[2..($Arguments.Count-1)]) -WorkingDirectory $root -ForbiddenRoots @($authorRoot)
        if($result.module_stdout){Write-Output $result.module_stdout}
      }catch{
        if($_.Exception.Data.Contains('exit_code')){
          $failure=[InvalidOperationException]::new("Python stage failed: $($Arguments -join ' ')",$_.Exception)
          $failure.Data['exit_code']=[int]$_.Exception.Data['exit_code']
          throw $failure
        }
        throw
      }
    }
  }
}

function Get-PreparedJointSourceReferences {
  param([string[]]$RunDirectories)
  # These are explicit run authorities from the request or verified trial,
  # never inferred ancestors of an arbitrary external file.
  $code='import json,sys;from pathlib import Path;from msplatform.execution.retention import file_record;print(json.dumps([dict(manifest_record=file_record(Path(p)/"run_manifest.json"),protected_paths=[p],protected_cache_keys=[]) for p in json.loads(sys.argv[1])]))'
  $json=(@(Invoke-ProjectPython -Arguments @('-c',$code,(ConvertTo-Json -InputObject @($RunDirectories|Where-Object{$_}|Select-Object -Unique) -Compress)))-join"`n")
  return @($json|ConvertFrom-Json -AsHashtable -Depth 100)
}

function Invoke-PreparedJointAnalysis {
  . (Join-Path $executionResources 'run_artifact_support.ps1')
  . (Join-Path $executionResources 'dependencies.ps1')
  $source=(Resolve-Path -LiteralPath $AnalyzeRunPath).Path
  $contract=(Resolve-Path -LiteralPath $ContractPath).Path
  $recording=(@(Invoke-ProjectPython -Arguments @('-m','msplatform.contracts.trajectory_recording','--contract',$contract))-join"`n")|ConvertFrom-Json
  if($null-eq$recording){throw 'Joint analysis requires the original retained-observation budget.'}
  $analysisRunId=if($RunId){$RunId}else{(Get-Date -Format 'yyyyMMdd_HHmmss')+'__analysis__python__ip-mr-joint-'+[guid]::NewGuid().ToString('N').Substring(0,8)}
  $package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $projectArtifacts `
    -RunId $analysisRunId -Project $projectId -Mode prepared_joint_analysis -Software @('Python 3.11') `
    -RetentionContractEnabled -RetentionClass solver_review -RetentionReason $recording.reason -CapacityLedgerLifecycleEnabled -PathContext $pathContext
  $script:preparedPackage=$package
  $runDir=[string]$package.artifact_run_dir
  $inputDir=Join-Path $runDir 'inputs'
  $analysisTimer=[Diagnostics.Stopwatch]::StartNew()
  $owner=$null;$capacity=$null;$failure=$null;$stage='capacity_startup'
  try {
    $capacity=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -ArtifactRoot ([string]$pathContext.artifact_root) `
      -RunDirectory $runDir -CommittedNewBytes ([int64]$recording.output_budget_bytes) -ProtectedPaths @($runDir) `
      -SourceReferences @(Get-PreparedJointSourceReferences -RunDirectories @($source)) -Owner "run-artifact-workflow:${projectId}:$analysisRunId"
    $stage='freeze_executable_dependencies'
    $dependencyPath=Join-Path $packageRoot 'workflows/config/runtime_dependencies.json'
    $frozen=Freeze-ConsumerDependencies -Python $Python -RepoRoot $repoRoot -CorePackageRoot $packageRoot -ContractPath $dependencyPath -InputDir $inputDir -OwnerId $projectId -ConsumerId prepared_joint
    $script:pythonRoot=[string]$frozen.execution_root
    $entryIdentity=@($frozen.identities|Where-Object{$_.source_repo_path-ceq'src/msplatform/workflows/resources/prepared_joint_execute.ps1'})
    $frozenEntryRecord=if($entryIdentity.Count-eq1){@{path=$entryIdentity[0].snapshot_path;exists=$true;bytes=[long](Get-Item -LiteralPath $entryIdentity[0].snapshot_path).Length;sha256=$entryIdentity[0].sha256}}else{$null}
    $configuration=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
    $configuration.inputs=[ordered]@{code_inventory=$frozen.code_inventory_path;dependency_contract=$frozen.dependency_contract_path}
    foreach($identity in $frozen.identities){$configuration.inputs[$identity.frozen_input_name]=$identity.snapshot_path}
    Write-RunJson -Path $package.run_config -Depth 50 -Value $configuration
    $frozenAnalysisContract=Copy-VerifiedRunInput -Source $contract -Destination (Join-Path $inputDir 'analysis_contract.json')
    $owner=Initialize-RunArtifactPowerShellOwner -Python $python -RepoRoot $repoRoot -Package $package -CapacitySession $capacity `
      -ResultPath $ResultPath -EntrypointPath (Join-Path $script:pythonRoot 'src/msplatform/workflows/resources/prepared_joint_execute.ps1') -EntrypointRecord $frozenEntryRecord `
      -CommitmentInputPaths @($frozenAnalysisContract) -Software @('Python 3.11')
    $configuration=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
    $stage='admit_completed_native_source'
    $selection=(@(Invoke-ProjectPython -FrozenPackage $frozen -Arguments @('-m','msplatform.workflows.prepared_joint.analysis_inputs','--source-run',$source,'--contract',[string]$frozenAnalysisContract,'--output-inputs',$inputDir))-join"`n")|ConvertFrom-Json -Depth 50
    if(($selection.recording|ConvertTo-Json -Compress)-cne($recording|ConvertTo-Json -Compress)){throw 'Analysis observation budget changed during input freezing.'}
    $configuration.inputs.source_manifest=$selection.source_manifest
    $configuration.inputs.analysis_contract=$selection.analysis_contract
    $configuration.inputs.source_preparation=$selection.preparation
    $configuration.inputs.source_merge_receipt=$selection.merge_receipt
    $configuration.parameters=[ordered]@{source_run=$source;mother_particle_count=$selection.mother_particle_count;launched_particle_count=$selection.launched_particle_count;native_flight_executed=$false;qualification='post_hoc_analysis_only'}
    Write-RunJson -Path $package.run_config -Depth 50 -Value $configuration
    $renewal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity `
      -ProtectedPaths @($runDir) -SourceReferences @(Get-PreparedJointSourceReferences -RunDirectories @($selection.protected_paths)) -RemainingCommittedNewBytes ([int64]$recording.output_budget_bytes)
    $capacity=$renewal.session
    $stage='joint_diagnostics'
    Invoke-ProjectPython -FrozenPackage $frozen -Arguments @('-m','msplatform.workflows.historical_joint_analysis','analyze-joint',
      '--preparation',[string]$selection.preparation,'--log',[string]$selection.merged_log,'--output',(Join-Path $package.result_dir 'diagnostics'),'--analysis-contract',[string]$selection.analysis_contract)
  }catch{$failure=$_}
  $status=if($null-eq$failure){'success'}else{'failed'}
  $summary=[ordered]@{native_path_preparation=$package.native_path_preparation;schema_version=1;role='prepared_joint_analysis_summary';status=$status;source_run=$source;native_flight_executed=$false;qualification='post_hoc_analysis_only';elapsed_before_finalization_seconds=$analysisTimer.Elapsed.TotalSeconds}
  if($null-ne$failure){$summary.reason=$failure.Exception.Message;$summary.failure_stage=$stage}
  if($null-eq$owner){
    if($null-ne$capacity){$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity}
    if($null-ne$failure){throw $failure};throw 'Analysis finalization owner was not initialized.'
  }
  $outputs=@(Get-ChildItem -LiteralPath $package.result_dir -Recurse -File|ForEach-Object{$_.FullName})
  $ownerResult=Complete-RunArtifactPowerShellOwner -Context $owner -Status $status -Summary $summary -OutputPaths $outputs `
    -WritersStopped $true -WriterCompletion @{operations=@();resource_releases=@()} -OriginalFailure $failure
  if($null-ne$failure){throw $failure}
  if($ownerResult.status-ne'success'){throw 'Prepared-joint analysis finalization is incomplete; use ResumeFinalization.'}
  Write-Output "PREPARED_JOINT_ANALYSIS=PASS RUN_ID=$analysisRunId NATIVE_FLY=False"
}
if($PSCmdlet.ParameterSetName-eq'Analysis'){
  . (Join-Path $executionResources 'host_execution_lease.ps1') -HostContext $hostContext
  $analysisLease=Enter-HostExecutionLease -StatePath $pathContext.host_resource_state_path -Role GATE -Stage unclassified -RunId $RunId
  $analysisOkay=$false
  try{Invoke-PreparedJointAnalysis;$analysisOkay=$true}
  finally{Exit-HostExecutionLease -Lease $analysisLease -Outcome $(if($analysisOkay){'success'}else{'failed'}) -RunId $RunId}
}
