<#
.SYNOPSIS
Prepare an OA/IP interface, or execute its supported joint workflow branches.
.DESCRIPTION
Continuous instrument tracing uses the public SimulationRecipe entrypoint.
Historical prepared handoff workbenches do not authorize a new flight.
Sources, automatic stages, complete examples and field limits:
docs/ASSEMBLY.md (simulation path selection).
#>
[CmdletBinding()]
param(
  [string]$ReferenceMrRunPath='',
  [ValidateSet('orthogonal_accelerator','ion_processor')]
  [string]$AcceleratorProvider='orthogonal_accelerator',
  [string]$RunId='',
  [string]$PythonExe='',
  [string]$RepoRoot=''
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
function New-AcceleratorInterfaceRunId {
  param([Parameter(Mandatory)][string]$Provider)
  $slug=if($Provider-eq'orthogonal_accelerator'){'oa'}else{'ip'}
  return (Get-Date -Format 'yyyyMMdd_HHmmss')+'__analysis__python__accelerator-interface-'+$slug+'-'+[guid]::NewGuid().ToString('N').Substring(0,8)
}
$projectId='instrument_assembly'
$software=@('Python 3.11')
$researchRootExplicit=[bool]$RepoRoot
$repoRoot=if($RepoRoot){(Resolve-Path -LiteralPath $RepoRoot).Path}else{(Get-Location).Path}
$workspaceRoot=if($researchRootExplicit){Split-Path -Parent $repoRoot}else{$repoRoot}
if($PythonExe){$PythonExe=(Resolve-Path -LiteralPath $PythonExe).Path}
$packageRoot=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$sourceRoot=Split-Path -Parent $packageRoot
$executionResources=Join-Path $packageRoot 'execution/resources'
$script:pythonRoot=$sourceRoot
. (Join-Path $executionResources 'require_powershell7.ps1')
. (Join-Path $executionResources 'dependencies.ps1')
. (Join-Path $executionResources 'run_artifact_support.ps1')
$python=if($PythonExe){$PythonExe}elseif($env:SIMULATION_PYTHON_EXE){$env:SIMULATION_PYTHON_EXE}else{throw 'Explicit PythonExe or SIMULATION_PYTHON_EXE is required'}
$packageRootText=& $python -I -B -c 'from pathlib import Path;import msplatform;print(Path(msplatform.__file__).resolve().parent)'
if($LASTEXITCODE-ne0-or[string]::IsNullOrWhiteSpace([string]$packageRootText)){throw 'Installed msplatform package is unavailable.'}
$selectedPackageRoot=(Resolve-Path -LiteralPath ([string]$packageRootText).Trim()).Path
if(-not$researchRootExplicit-and-not[string]::Equals($selectedPackageRoot,[IO.Path]::GetFullPath($packageRoot),[StringComparison]::OrdinalIgnoreCase)){throw 'Selected Python msplatform package differs from the entry package.'}
. (Join-Path $executionResources 'workspace_paths.ps1')
$pathContext=Resolve-WorkspacePaths -SourceRoot $repoRoot -Python $python
$artifactRoot=[string]$pathContext.artifact_root
$assemblyArtifactRoot=Resolve-RunArtifactRoot -ArtifactRoot $artifactRoot -OwnerKind assembly -OwnerId $projectId -Python $python
$mrArtifactRoot=Resolve-RunArtifactRoot -ArtifactRoot $artifactRoot -OwnerKind component -OwnerId multi_reflection_tof -Python $python
$ipArtifactRoot=Resolve-RunArtifactRoot -ArtifactRoot $artifactRoot -OwnerKind component -OwnerId ion_processor -Python $python
$pathEnvironment=@{MASS_SPECTROMETRY_ARTIFACT_ROOT=$artifactRoot;
  MASS_SPECTROMETRY_EXECUTION_ROOT=[string]$pathContext.execution_root;
  MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=[string]$pathContext.host_resource_state_path}
$hostContextJson=@{workspace=$workspaceRoot;python_executable=$python;
  host_state_path=[string]$pathContext.host_resource_state_path;
  policy_path=(Join-Path $executionResources 'host_resource_policy.json')}|ConvertTo-Json -Compress
if(-not$ReferenceMrRunPath){throw 'ReferenceMrRunPath is required for interface preparation.'}
$reference=(Resolve-Path -LiteralPath $ReferenceMrRunPath).Path
if(-not$RunId){$RunId=New-AcceleratorInterfaceRunId -Provider $AcceleratorProvider}
$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot $assemblyArtifactRoot `
  -RunId $RunId -Project $projectId -Mode accelerator_interface_preparation `
  -Software $software -RetentionContractEnabled -RetentionClass compact -CapacityLedgerLifecycleEnabled -PathContext $pathContext
$terminalized=$false
$capacitySession=$null
$lease=$null
$paGuards=[Collections.Generic.List[IO.FileStream]]::new()
$extraOutputs=@()
$stage='capacity_startup'
try{
  # One frozen PA template plus up to five temporary hard-linked companions
  # count toward the logical-file peak; no field PA or samples are copied.
  $parents=@($reference)
  $sourceRecords=Invoke-RunToolRootContext -RepoRoot $sourceRoot -Environment $pathEnvironment -Operation {
    & $python -B -c 'import json,sys;from pathlib import Path;from msplatform.execution.retention import file_record;print(json.dumps([dict(manifest_record=file_record(Path(p)/"run_manifest.json"),protected_paths=[p]) for p in json.loads(sys.argv[1])]))' ($parents|ConvertTo-Json -Compress -AsArray)
    if($LASTEXITCODE-ne0){throw 'Interface source manifest binding failed.'}
  }
  $sourceReferences=@(($sourceRecords-join"`n")|ConvertFrom-Json -AsHashtable)
  $capacitySession=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot ($artifactRoot) -RunDirectory $package.artifact_run_dir `
    -CommittedNewBytes 134217728 -ProtectedPaths @($package.artifact_run_dir) -SourceReferences $sourceReferences -Owner "instrument-assembly-accelerator-interface:$RunId"
  $startup=Join-Path $package.result_dir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $startup -Depth 14 -Value $capacitySession
  $stage='freeze_executable_dependencies'
  $dependencyPath=Join-Path $packageRoot 'workflows/config/runtime_dependencies.json'
  $frozen=Freeze-ConsumerDependencies -Python $Python -RepoRoot $repoRoot -CorePackageRoot $packageRoot -ContractPath $dependencyPath -InputDir $package.input_dir -OwnerId $projectId -ConsumerId accelerator_interface
  $script:pythonRoot=[string]$frozen.execution_root
  $configuration=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
  $configuration.inputs=[ordered]@{code_inventory=$frozen.code_inventory_path;dependency_contract=$frozen.dependency_contract_path}
  foreach($identity in $frozen.identities){$configuration.inputs[$identity.frozen_input_name]=$identity.snapshot_path}
  Write-RunJson -Path $package.run_config -Depth 50 -Value $configuration
  $stage='prepare_only'
  $lease=Enter-HostExecutionLease -Role GATE
  $arguments=@('-m','msplatform.workflows.accelerator_interface.prepare',
    '--provider',$AcceleratorProvider,'--reference-mr-run',$reference,'--run-directory',$package.artifact_run_dir)
  $log=Join-Path $package.log_dir 'prepare_accelerator_interface.log'
  Invoke-RunToolRootContext -RepoRoot $script:pythonRoot -Environment $pathEnvironment -Operation {
    & $python -B @arguments 2>&1|Tee-Object -FilePath $log
    if($LASTEXITCODE-ne0){throw "Accelerator interface preparation failed; Python source error is retained in $log"}
  }
  Exit-HostExecutionLease -Lease $lease
  $lease=$null
  $receipt=Get-Content -LiteralPath (Join-Path $package.result_dir 'accelerator_interface_preparation.json') -Raw|ConvertFrom-Json -AsHashtable
  $configuration=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
  foreach($key in $receipt.inputs.Keys){$configuration.inputs[$key]=$receipt.inputs[$key].path}
  $configuration.parameters=[ordered]@{
    accelerator_provider=$AcceleratorProvider
    reference_mr_run=$reference
    solver_execution='none'
    qualification='interface_preparation_only_not_joint_simulation'
  }
  Write-RunJson -Path $package.run_config -Depth 50 -Value $configuration
  Write-RunJson -Path $package.summary -Depth 30 -Value ([ordered]@{
    schema_version=1;role='mrtof_accelerator_interface_run_summary';status='success'
    qualification='interface_preparation_only_not_joint_simulation';preparation=$receipt
  })
  $stage='terminal_publication'
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
  $terminal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -Session $capacitySession -RemainingCommittedNewBytes 0
  $capacitySession=$terminal.session
  Write-RunJson -Path (Join-Path $package.result_dir 'artifact_capacity_gate_terminal.json') -Depth 14 -Value $terminal
  $outputs=@(Get-ChildItem -LiteralPath $package.result_dir -Recurse -File|ForEach-Object{$_.FullName})
  $outputs+=@($package.summary,$log,$retention)+$extraOutputs
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config `
    -Status success -Software $software -Outputs $outputs -DeferCapacityFinalization
  $terminalized=$true
  $stage='capacity_finalization'
  Invoke-RunCapacityLifecycleAdapter -Python $python -RepoRoot $repoRoot `
    -Action finalize-ready -ArtifactRoot ($artifactRoot) -RunConfig $package.run_config|Out-Null
  Write-Output "ACCELERATOR_PREPARATION=PASS PROVIDER=$AcceleratorProvider RUN_ID=$RunId SOLVER_EXECUTED=False"
}catch{
  if($terminalized){
    Write-Warning 'Scientific summary and verified manifest retained; capacity handoff failed and requires public owner recovery.'
  }else{
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Summary $package.summary `
      -SummaryRole mrtof_accelerator_interface_run_summary -Reason $_.Exception.Message `
      -Software $software -Status failed -FailureStage $stage
    $terminalized=$true
  }
  throw
}finally{
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease}
  foreach($guard in $paGuards){$guard.Dispose()}
  if($null-ne$capacitySession){$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession}
}
