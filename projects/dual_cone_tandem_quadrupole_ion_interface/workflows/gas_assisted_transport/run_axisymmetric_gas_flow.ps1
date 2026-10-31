[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$RunId,
  [string]$PythonExe='',
  [string]$ResolvedInputsPath=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectId='dual_cone_tandem_quadrupole_ion_interface'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot=(Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'axisymmetric_gas_flow_screening' `
  -Software @('COMSOL Multiphysics 6.4','MATLAB R2025b','Python 3.11') `
  -RetentionContractEnabled -RetentionClass compact -UseShortExecutionPath `
  -CapacityLedgerLifecycleEnabled
$failureStage='freeze_inputs'
$terminalized=$false
$resourceLease=$null
$capacitySession=$null
$environmentNames=@('DUAL_CONE_GAS_FLOW_OUTPUT_DIR','DUAL_CONE_PROJECT_ROOT','SIMULATION_PYTHON_EXE')
$savedEnvironment=Save-RunEnvironment -Names $environmentNames
try{
  $env:SIMULATION_PYTHON_EXE=$python
  $resourceLease=Enter-HostResourceStage -Role COMSOL -Stage prepare `
    -Budget (Get-HostResourceBudget -Profile unknown) -RunId $RunId
  $failureStage='capacity_startup'
  # Workflow remaining peak commitment: conservative 1 GiB upper bound over the
  # largest historical terminal payload; this is scheduling metadata, not physics.
  $capacitySession=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') `
    -RunDirectory $package.artifact_run_dir -CommittedNewBytes 1073741824 `
    -ProtectedPaths @($package.artifact_run_dir) -Owner "dual-cone-gas-flow:$RunId"
  $capacityStartupPath=Join-Path $package.result_dir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $capacityStartupPath -Value $capacitySession -Depth 14
  $failureStage='freeze_inputs'
  $compiledInputs=$null
  if($ResolvedInputsPath){
    $compiledInputs=Get-Content -LiteralPath $ResolvedInputsPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable -Depth 100
    if($compiledInputs.role-ne'compiled_execution_inputs'-or$compiledInputs.project_id-ne$projectId){throw 'Compiled gas-flow input identity differs.'}
  }
  $frozen=[ordered]@{}
  $sourceFiles=[ordered]@{
    geometry_baseline='config\baseline.json'
    resolved_geometry='config\resolved_geometry.json'
    gas_flow_science='config\gas_flow_science.json'
    comsol_solver_numerics='config\comsol_solver_numerics.json'
    matlab_model_builder='comsol\build_and_solve_axisymmetric_gas_flow.m'
    matlab_task='comsol\run_axisymmetric_gas_flow.m'
  }
  $schedulerFiles=[ordered]@{
    powershell_preflight='common\require_powershell7.ps1'
    host_resource_support='common\host_execution_lease.ps1'
    host_resource_scheduler='common\host_resource_scheduler.py'
    host_resource_policy='common\host_resource_policy.json'
    resource_budget_support='common\resource_budget_support.ps1'
    comsol_launcher='common\comsol\run_comsol_r2025b.ps1'
    comsol_bootstrap='common\comsol\livelink_r2025b\comsolstartup.m'
    comsol_failure_classifier='common\comsol\livelink_failure_classification.ps1'
    comsol_environment_preflight='common\comsol\livelink_environment.ps1'
    comsol_launcher_resolver='common\comsol\resolve_comsol_64.ps1'
  }
  foreach($key in $sourceFiles.Keys){
    $source=Join-Path $projectRoot $sourceFiles[$key]
    if($null-ne$compiledInputs-and$key-in@('geometry_baseline','resolved_geometry','gas_flow_science','comsol_solver_numerics')){
      $records=@($compiledInputs.files|Where-Object{$_.name-eq$key})
      if($records.Count-ne1){throw "Compiled gas-flow input is missing or ambiguous: $key; recompile with the current execution profile."}
      $source=Join-Path $compiledInputs.root ([string]$records[0].relative_path)
    }
    $destination=Join-Path (Join-Path $package.input_dir 'project_snapshot') $sourceFiles[$key]
    $frozen[$key]=Copy-VerifiedRunInput -Source $source -Destination $destination
  }
  $geometrySnapshotRoot=Join-Path $package.input_dir 'project_snapshot'
  $geometryCodeFiles=[ordered]@{
    geometry_resolver='projects/dual_cone_tandem_quadrupole_ion_interface/analysis/resolve_geometry.py'
    geometry_resolver_package='projects/dual_cone_tandem_quadrupole_ion_interface/analysis/__init__.py'
    round_rod_geometry='projects/rf_multipole_ion_optics/core/round_rod_geometry.py'
    round_rod_package='projects/rf_multipole_ion_optics/core/__init__.py'
  }
  foreach($key in $geometryCodeFiles.Keys){
    $frozen[$key]=Copy-VerifiedRunInput -Source (Join-Path $repoRoot $geometryCodeFiles[$key]) `
      -Destination (Join-Path $geometrySnapshotRoot $geometryCodeFiles[$key])
  }
  $failureStage='geometry_input_freshness'
  $geometryCheck=@'
import importlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
resolver = importlib.import_module('projects.dual_cone_tandem_quadrupole_ion_interface.analysis.resolve_geometry')
def owned_origins():
    result = {}
    for name, module in tuple(sys.modules.items()):
        if name not in ('common', 'projects') and not name.startswith(('common.', 'projects.')):
            continue
        file = getattr(module, '__file__', None)
        paths = [file] if file else list(getattr(module, '__path__', ()))
        if not paths or any(not pathlib.Path(path).resolve().is_relative_to(root) for path in paths):
            raise RuntimeError(f'geometry admission imported outside its frozen snapshot: {name}: {paths}')
        result[name] = [str(pathlib.Path(path).resolve()) for path in paths]
    return result
owned_origins()
sys.argv = ['resolve_geometry', '--baseline', sys.argv[2], '--check', sys.argv[3]]
resolver.main()
numpy = sys.modules['numpy']
print('DUAL_GEOMETRY_ENVIRONMENT=' + json.dumps(dict(
    python_executable=sys.executable, owned_modules=owned_origins(),
    numpy=dict(version=numpy.__version__, module_path=numpy.__file__))))
'@
  $geometryValidationOutput=@(& $python -I -B -c $geometryCheck $geometrySnapshotRoot `
    $frozen.geometry_baseline $frozen.resolved_geometry)
  if($LASTEXITCODE-ne 0){throw 'Frozen dual-cone baseline and resolved geometry differ.'}
  $geometryValidationOutput | ForEach-Object {Write-Output $_}
  $geometryEnvironmentLine=@($geometryValidationOutput | Where-Object {$_ -like 'DUAL_GEOMETRY_ENVIRONMENT=*'})
  if($geometryEnvironmentLine.Count-ne1){throw 'Frozen dual-cone geometry environment evidence is missing.'}
  $geometryValidationEnvironment=([string]$geometryEnvironmentLine[0]).Substring('DUAL_GEOMETRY_ENVIRONMENT='.Length)|ConvertFrom-Json
  foreach($key in $schedulerFiles.Keys){
    $source=Join-Path $repoRoot $schedulerFiles[$key]
    $destination=Join-Path (Join-Path $package.input_dir 'repository_snapshot') $schedulerFiles[$key]
    $frozen[$key]=Copy-VerifiedRunInput -Source $source -Destination $destination
  }
  $configuration=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
  $configuration.inputs=[ordered]@{}
  $configuration.input_identity=[ordered]@{}
  foreach($key in $sourceFiles.Keys){
    $configuration.inputs[$key]=Join-Path $package.artifact_run_dir ("inputs\project_snapshot\"+$sourceFiles[$key])
    $configuration.input_identity[$key]=[ordered]@{
      path=$configuration.inputs[$key]
      sha256=Get-RunFileSha256 -Path $frozen[$key]
    }
  }
  foreach($key in $schedulerFiles.Keys){
    $configuration.inputs[$key]=Join-Path $package.artifact_run_dir ("inputs\repository_snapshot\"+$schedulerFiles[$key])
    $configuration.input_identity[$key]=[ordered]@{
      path=$configuration.inputs[$key]
      sha256=Get-RunFileSha256 -Path $frozen[$key]
    }
  }
  foreach($key in $geometryCodeFiles.Keys){
    $configuration.inputs[$key]=Join-Path $package.artifact_run_dir ("inputs/project_snapshot/"+$geometryCodeFiles[$key])
    $configuration.input_identity[$key]=[ordered]@{
      path=$configuration.inputs[$key]
      sha256=Get-RunFileSha256 -Path $frozen[$key]
    }
  }
  $configuration.parameters=[ordered]@{
    geometry_validation_environment=$geometryValidationEnvironment
    lifecycle_stage='prepared_for_comsol_solve'
    evidence_scope='axisymmetric_empty_enclosure_qualitative_prototype'
    gas_species='N2';upstream_pressure_pa=101325;rear_pressure_pa=400
  }
  Write-RunJson -Path $package.run_config -Value $configuration -Depth 12
  $failureStage='comsol_axisymmetric_gas_flow'
  $env:DUAL_CONE_GAS_FLOW_OUTPUT_DIR=$package.result_dir
  $env:DUAL_CONE_PROJECT_ROOT=Join-Path $package.input_dir 'project_snapshot'
  Exit-HostResourceStage -Lease $resourceLease
  $resourceLease=$null
  & $frozen.comsol_launcher `
    -TaskScript $frozen.matlab_task -ReportPath (Join-Path $package.log_dir 'comsol_bootstrap_report.txt') `
    -RunId $RunId
  if($LASTEXITCODE-ne 0){throw 'COMSOL gas-flow launcher failed.'}
  $resourceLease=Enter-HostResourceStage -Role COMSOL -Stage postprocess `
    -Budget (Get-HostResourceBudget -Role COMSOL -Stage postprocess) -RunId $RunId
  $field=Join-Path $package.result_dir 'gas_field_rz.csv'
  $metadata=Join-Path $package.result_dir 'gas_field_metadata.json'
  $model=Join-Path $package.result_dir 'axisymmetric_gas_flow.mph'
  $taskReport=Join-Path $package.result_dir 'comsol_run_report.txt'
  foreach($path in @($field,$metadata,$model,$taskReport)){
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "COMSOL output is missing: $path"}
  }
  $failureStage='independent_gas_field_validation'
  $validation=Join-Path $package.result_dir 'gas_field_validation.json'
  & $python -m projects.dual_cone_tandem_quadrupole_ion_interface.analysis.validate_gas_field `
    --csv $field --metadata $metadata --science $frozen.gas_flow_science `
    --numerics $frozen.comsol_solver_numerics --geometry $frozen.resolved_geometry `
    --output $validation
  if($LASTEXITCODE-ne 0){throw 'Independent gas-field validation failed.'}
  $fieldMetadata=Get-Content -LiteralPath $metadata -Raw|ConvertFrom-Json
  Write-RunJson -Path $package.summary -Value ([ordered]@{
    schema_version=1;role='dual_cone_axisymmetric_gas_flow_summary';status='success'
    evidence_scope='axisymmetric_empty_enclosure_qualitative_prototype'
    rear_pressure_pa=400;gas_species='N2';field_metadata=$fieldMetadata
  }) -Depth 14
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot `
    -RunConfig $package.run_config
  $capacityTerminal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -Session $capacitySession -RemainingCommittedNewBytes 0
  $capacitySession=$capacityTerminal.session
  $capacityTerminalPath=Join-Path $package.result_dir 'artifact_capacity_gate_terminal.json'
  Write-RunJson -Path $capacityTerminalPath -Value $capacityTerminal -Depth 14
  $outputs=@($package.summary,$field,$metadata,$taskReport,$validation,$retention,$capacityStartupPath,$capacityTerminalPath,(Join-Path $package.log_dir 'comsol_bootstrap_report.txt'))
  if(Test-Path -LiteralPath $model -PathType Leaf){$outputs+=$model}
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config `
    -Status success -Software @('COMSOL Multiphysics 6.4','MATLAB R2025b','Python 3.11') `
    -Outputs $outputs
  $terminalized=$true
  Invoke-HostExecutionCompletionNotification -Outcome success -RunId $RunId
  Write-Output "DUAL_CONE_GAS_FLOW=PASS RUN=$($package.artifact_run_dir)"
}catch{
  if($null-eq$resourceLease-and$failureStage-eq'comsol_axisymmetric_gas_flow'){
    $resourceLease=Enter-HostResourceStage -Role COMSOL -Stage postprocess `
      -Budget (Get-HostResourceBudget -Role COMSOL -Stage postprocess) -RunId $RunId
  }
  if(-not$terminalized){
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config `
      -Summary $package.summary -SummaryRole 'dual_cone_axisymmetric_gas_flow_summary' `
      -Reason $_.Exception.Message -FailureStage $failureStage `
      -Software @('COMSOL Multiphysics 6.4','MATLAB R2025b','Python 3.11')
    $terminalized=$true
    Invoke-HostExecutionCompletionNotification -Outcome failed -RunId $RunId
  }
  throw
}finally{
  try{
    Restore-RunEnvironment -Names $environmentNames -Snapshot $savedEnvironment
    if($null-ne$resourceLease){Exit-HostResourceStage -Lease $resourceLease}
    Remove-RunPackageExecutionAlias -Package $package
  }finally{
    if($null-ne$capacitySession){
      $null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
        -Session $capacitySession
    }
  }
}
