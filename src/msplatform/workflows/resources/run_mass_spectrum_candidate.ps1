[CmdletBinding(DefaultParameterSetName='Run')]
param(
  [string]$RunId = ((Get-Date -Format 'yyyyMMdd_HHmmss') + '__sim__cross__mass-spectrum__five-mass'),
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [Parameter(ParameterSetName='Run')][Alias('Resume')][switch]$ResumeAfterComsol,
  [Parameter(ParameterSetName='Run')][Parameter(ParameterSetName='Analyze')][string]$SourceRunPath,
  [Parameter(Mandatory,ParameterSetName='Analyze')][switch]$ReanalyzeOnly,
  [string]$SourceStoppedReceiptPath='',
  [Parameter(Mandatory,ParameterSetName='Analyze')][ValidateRange(1,[long]::MaxValue)][long]$AnalysisNewBytes,
  [string]$ResultPath='',
  [Parameter(Mandatory,ParameterSetName='ResumeFinalization')][switch]$ResumeFinalization,
  [string]$PythonExe='',
  [Parameter(Mandatory=$true)][string]$Workspace,
  [Parameter(Mandatory=$true,ParameterSetName='Run')][string]$ArtifactRootPath,
  [Parameter(Mandatory=$true,ParameterSetName='Run')][string]$ScienceRoot,
  [string]$ExecutionEnvironment='',
  [string]$EngineeringProfile=''
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$Workspace=(Resolve-Path -LiteralPath $Workspace).Path
$python=if($PythonExe){(Resolve-Path -LiteralPath $PythonExe).Path}elseif($env:SIMULATION_PYTHON_EXE){
  (Resolve-Path -LiteralPath $env:SIMULATION_PYTHON_EXE).Path}else{throw 'Explicit PythonExe or SIMULATION_PYTHON_EXE is required.'}
$packageRoot=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ExecutionEnvironment=if($ExecutionEnvironment){$ExecutionEnvironment}else{$env:MASS_SPECTRUM_EXECUTION_ENVIRONMENT}
$EngineeringProfile=if($EngineeringProfile){$EngineeringProfile}else{$env:MASS_SPECTRUM_ENGINEERING_PROFILE}
if(-not$ExecutionEnvironment-or-not$EngineeringProfile){throw 'Select an explicit execution environment and engineering profile.'}
$module='msplatform.workflows.single_reflection_mass_spectrum_study'
$common=@('--run-id',$RunId,'--workspace',$Workspace,'--execution-environment',$ExecutionEnvironment,
  '--engineering-profile',$EngineeringProfile)
if($ResumeFinalization){
  if(-not$PSBoundParameters.ContainsKey('RunId')){throw 'ResumeFinalization requires the original analysis RunId.'}
  $arguments=@($module,'resume-finalization')+$common
  if($ResultPath){$arguments+=@('--result-path',$ResultPath)}
  $success='MASS_SPECTRUM_FINALIZATION=PASS'
}else{
  $projectRoot=if($ScienceRoot){(Resolve-Path -LiteralPath $ScienceRoot).Path}else{''}
  . (Join-Path $packageRoot 'execution/resources/workspace_paths.ps1')
  $artifactProject=if($ArtifactRootPath){Resolve-RunArtifactRoot -ArtifactRoot ($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ArtifactRootPath)) -OwnerKind component -OwnerId single_reflection_oa_tof_mass_analyzer -Python $python}else{''}
  if($ReanalyzeOnly){
    $action='analyze';$success='MASS_SPECTRUM_ANALYSIS=PASS'
  }else{
    $action=if($ResumeAfterComsol){'resume'}else{'run'}
    $success='MASS_SPECTRUM_CANDIDATE=PASS'
  }
  $arguments=@($module,$action)+$common
  if(-not$ReanalyzeOnly){
    $arguments+=@(
      '--mode-config',(Join-Path $projectRoot 'config/modes/mass_spectrum.json'),
      '--resolved-geometry',(Join-Path $projectRoot 'config/resolved_geometry.json'),
      '--particle-count-policy',(Join-Path $packageRoot 'contracts/particle_count_policy.json'),
      '--formal-mph',(Join-Path $artifactProject 'formal/comsol/single_reflection_oa_tof_mass_analyzer__model.mph'),
      '--formal-asset-manifest',(Join-Path $artifactProject 'formal/asset_manifest.json'),
      '--simion-executable',$SimionExe,'--artifact-project-root',$artifactProject,
      '--project-config',(Join-Path $projectRoot 'config/project.json'),
      '--formal-assets',(Join-Path $projectRoot 'config/formal_assets.json'),
      '--baseline',(Join-Path $projectRoot 'config/baseline.json'),
      '--formal-mode',(Join-Path $projectRoot 'config/modes/formal.json'),
      '--solver-numerics',(Join-Path $projectRoot 'config/formal_solver_numerics.json'))
  }
  if($SourceRunPath){$arguments+=@('--source-run',$SourceRunPath)}
  if($SourceStoppedReceiptPath){$arguments+=@('--stopped-receipt',$SourceStoppedReceiptPath)}
  if($ReanalyzeOnly){$arguments+=@('--analysis-new-bytes',[string]$AnalysisNewBytes)}
}
& $python -I -B -c "from msplatform.workflows.single_reflection_mass_spectrum_study import main; main()" @($arguments | Select-Object -Skip 1)
if($LASTEXITCODE-ne0){throw "Mass-spectrum installed workflow failed with exit code $LASTEXITCODE."}
Write-Output ($success+' RUN_ID='+$RunId)
