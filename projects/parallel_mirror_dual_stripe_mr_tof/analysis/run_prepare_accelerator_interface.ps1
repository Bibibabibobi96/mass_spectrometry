[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$ReferenceMrRunPath,
  [ValidateSet('orthogonal_accelerator','dual_pressure_rectilinear_ion_processor')]
  [string]$AcceleratorProvider='orthogonal_accelerator',
  [string]$IonProcessorRunPath='',
  [switch]$FinalizeJointWorkbench,
  [string]$PreparedInterfaceRunPath='',
  [string]$JointFieldRunPath='',
  [string]$ContractPath='',
  [string]$SimionExe='',
  [string]$RunId='',
  [string]$LuaExe='',
  [string]$PythonExe=''
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
function New-AcceleratorInterfaceRunId {
  param([Parameter(Mandatory)][string]$Provider)
  $slug=if($Provider-eq'orthogonal_accelerator'){'oa'}else{'ip'}
  return (Get-Date -Format 'yyyyMMdd_HHmmss')+'__analysis__python__mrtof-accelerator-interface-'+$slug+'-'+[guid]::NewGuid().ToString('N').Substring(0,8)
}
$projectId='parallel_mirror_dual_stripe_mr_tof'
$software=@('Python 3.11')
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
. (Join-Path $repoRoot 'common/contracts/run_artifact_support.ps1')
$python=if($PythonExe){(Resolve-Path -LiteralPath $PythonExe).Path}else{Join-Path $repoRoot '.venv/Scripts/python.exe'}
$reference=(Resolve-Path -LiteralPath $ReferenceMrRunPath).Path
if($AcceleratorProvider-eq'dual_pressure_rectilinear_ion_processor'-and-not$IonProcessorRunPath){
  throw 'Ion processor selection requires an explicit source run.'
}
if($FinalizeJointWorkbench-and($AcceleratorProvider-ne'dual_pressure_rectilinear_ion_processor'-or-not$PreparedInterfaceRunPath-or-not$JointFieldRunPath)){
  throw 'Joint workbench finalization requires explicit IP provider, design and new field runs.'
}
if(-not$FinalizeJointWorkbench-and($PreparedInterfaceRunPath-or$JointFieldRunPath)){throw 'Design/field run arguments require FinalizeJointWorkbench.'}
if($ContractPath-and-not$FinalizeJointWorkbench){throw 'ContractPath requires FinalizeJointWorkbench.'}
$executionContract=if($ContractPath){(Resolve-Path -LiteralPath $ContractPath).Path}else{''}
$designRun=if($PreparedInterfaceRunPath){(Resolve-Path -LiteralPath $PreparedInterfaceRunPath).Path}else{''}
$fieldRun=if($JointFieldRunPath){(Resolve-Path -LiteralPath $JointFieldRunPath).Path}else{''}
$sourceRun=if($IonProcessorRunPath){(Resolve-Path -LiteralPath $IonProcessorRunPath).Path}else{''}
if($AcceleratorProvider-eq'dual_pressure_rectilinear_ion_processor'){
  if(-not$LuaExe){$LuaExe=Join-Path $env:ProgramFiles 'SIMION-2020/lua.exe'}
  $LuaExe=(Resolve-Path -LiteralPath $LuaExe).Path
  $software+=@('Plain Lua (SIMION 2020 bundled interpreter; no solver)')
}
if($FinalizeJointWorkbench){
  if(-not$SimionExe){$SimionExe=Join-Path $env:ProgramFiles 'SIMION-2020/simion.exe'}
  $SimionExe=(Resolve-Path -LiteralPath $SimionExe).Path
  $software+=@('SIMION 2020 IOB assembly only; no Refine or Fly')
}
if(-not$RunId){$RunId=New-AcceleratorInterfaceRunId -Provider $AcceleratorProvider}
$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspaceRoot "artifacts/projects/$projectId") `
  -RunId $RunId -Project $projectId -Mode accelerator_interface_preparation `
  -Software $software -RetentionContractEnabled -RetentionClass compact -CapacityLedgerLifecycleEnabled
$terminalized=$false
$capacitySession=$null
$lease=$null
$paGuards=[Collections.Generic.List[IO.FileStream]]::new()
$extraOutputs=@()
$stage='capacity_startup'
try{
  # Small frozen JSON/CSV plus producer/receiver source; no PA or samples copy.
  $protected=@($package.artifact_run_dir,$reference)
  if($sourceRun){$protected+=@($sourceRun)}
  if($designRun){$protected+=@($designRun)}
  if($fieldRun){$protected+=@($fieldRun)}
  $capacitySession=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -RunDirectory $package.artifact_run_dir `
    -CommittedNewBytes 16777216 -ProtectedPaths $protected -Owner "mrtof-accelerator-interface:$RunId"
  $startup=Join-Path $package.result_dir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $startup -Depth 14 -Value $capacitySession
  $stage='prepare_only'
  $lease=Enter-HostExecutionLease -Role GATE
  $arguments=@('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepare_accelerator_interface',
    '--provider',$AcceleratorProvider,'--reference-mr-run',$reference,'--run-directory',$package.artifact_run_dir)
  if($sourceRun){$arguments+=@('--source-run',$sourceRun)}
  if($LuaExe){$arguments+=@('--lua-executable',$LuaExe)}
  if($FinalizeJointWorkbench){$arguments+=@('--finalize-joint-workbench','--prepared-interface-run',$designRun,'--joint-field-run',$fieldRun)}
  if($executionContract){$arguments+=@('--contract',$executionContract)}
  $log=Join-Path $package.log_dir 'prepare_accelerator_interface.log'
  Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
    & $python @arguments 2>&1|Tee-Object -FilePath $log
    if($LASTEXITCODE-ne0){throw 'Selected accelerator interface preparation failed.'}
  }
  Exit-HostExecutionLease -Lease $lease
  $lease=$null
  $receipt=Get-Content -LiteralPath (Join-Path $package.result_dir 'accelerator_interface_preparation.json') -Raw|ConvertFrom-Json -AsHashtable
  if($FinalizeJointWorkbench){
    $stage='iob_assembly_no_fly'
    $joint=$receipt.joint_workbench_binding
    $build=$joint.workbench_build_contract
    $audit=$joint.interface_field_audit
    # Reuse the static-trial read/no-write/no-delete payload guard policy. The
    # builder saves only IOB and small companions, never dirty PA arrays.
    $guardPaths=@($build.paths)+@($joint.guard_paths)+@($audit.guard_paths)
    foreach($path in @($guardPaths|Select-Object -Unique)){
      $paGuards.Add([IO.File]::Open([string]$path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read))
      $surface=[string]$path+'-surf'
      if(Test-Path -LiteralPath $surface -PathType Leaf){$paGuards.Add([IO.File]::Open($surface,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read))}
    }
    $lease=Enter-HostExecutionLease -Role SIMION -Stage preparation
    $buildLog=Join-Path $package.log_dir 'joint_workbench_assembly.log'
    $extraOutputs+=@($buildLog)
    $builder=Join-Path $package.result_dir 'joint_workbench/runtime/build_workbench.lua'
    $request=Join-Path $package.result_dir 'joint_workbench/runtime/workbench_build.lua'
    Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
      & $SimionExe --nogui --noprompt lua $builder -- --measured-source $request 2>&1|Tee-Object -FilePath $buildLog
      if($LASTEXITCODE-ne0){throw 'Joint workbench IOB assembly failed; no joint flight was attempted.'}
    }
    $buildText=Get-Content -LiteralPath $buildLog -Raw
    $declaredInstances=@($build.paths).Count
    if($declaredInstances-notin@(4,5)){throw 'Verified IP workbench requires four or five collision instances.'}
    if($buildText-notmatch("MRTOF_NATIVE_CORRIDOR_IOB_BUILD=PASS instances="+$declaredInstances+' static_measured_source=true')-or
       $buildText-match'(?im)(error:|error,|failed to save|cannot save|unable to save)'){
      throw 'Joint workbench builder did not prove the declared role count, clean save/reload and priority probes.'
    }
    if(-not(Test-Path -LiteralPath $build.output -PathType Leaf)){throw 'Joint IOB missing after successful assembly.'}
    $stage='interface_energy_field_audit_no_fly'
    $auditLog=Join-Path $package.log_dir 'interface_energy_field_audit.log'
    $extraOutputs+=@($auditLog)
    # A new vendor process loads only source basis + proven highest-priority IP
    # fine level. It does not inherit the builder's large PA collection.
    Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
      & $SimionExe --nogui --noprompt lua $audit.program -- $audit.lua_request 2>&1|Tee-Object -FilePath $auditLog
      if($LASTEXITCODE-ne0){throw 'Read-only interface field audit failed.'}
    }
    if((Get-Content -LiteralPath $auditLog -Raw)-notmatch'MRTOF_INTERFACE_FIELD_AUDIT=PASS'){
      throw 'Interface field audit did not close all measured crossings and centroid.'
    }
    Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
      & $python -c 'import sys,runpy;from pathlib import Path;p=Path(sys.argv[1]);runpy.run_path(str(p/"joint_flight_preparation.py"))["summarize_interface_field_audit"](p)' (Split-Path -Parent $audit.raw_output)
      if($LASTEXITCODE-ne0){throw 'Interface energy/field ledger reduction failed.'}
    }
    $joint.interface_field_audit.status='reported_no_energy_acceptance'
    Exit-HostExecutionLease -Lease $lease
    $lease=$null
    foreach($guard in $paGuards){$guard.Dispose()};$paGuards.Clear()
    $joint.status='iob_built_no_joint_flight'
    $joint.vendor_program_executed=$true
    $joint.iob_path=$build.output
    $joint.joint_simulation_executed=$false
    $receipt.status='workbench_ready_no_joint_flight'
    Write-Output 'JOINT_WORKBENCH_READINESS=CONFIGURATION_AND_FIELD_IDENTITY ENERGY_TARGET_ACCEPTANCE=not_declared SIX_DIMENSIONAL_MATCH_QUALIFIED=False TIME_FOCUS_QUALIFIED=False JOINT_FLY=False GUI=False'
    Write-RunJson -Path (Join-Path $package.result_dir 'joint_workbench/joint_binding_receipt.json') -Depth 40 -Value $joint
    Write-RunJson -Path (Join-Path $package.result_dir 'accelerator_interface_preparation.json') -Depth 40 -Value $receipt
  }
  $configuration=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
  $configuration.inputs=$receipt.inputs
  $configuration.parameters=[ordered]@{
    accelerator_provider=$AcceleratorProvider
    source_run=$sourceRun
    reference_mr_run=$reference
    finalize_joint_workbench=[bool]$FinalizeJointWorkbench
    prepared_design_run=$designRun
    new_joint_field_run=$fieldRun
    solver_execution='none'
    qualification='interface_preparation_only_not_joint_simulation'
  }
  Write-RunJson -Path $package.run_config -Value $configuration
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
    -Status success -Software $software -Outputs $outputs
  $terminalized=$true
  Write-Output "ACCELERATOR_PREPARATION=PASS PROVIDER=$AcceleratorProvider RUN_ID=$RunId SOLVER_EXECUTED=False"
}catch{
  if(-not$terminalized){
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
