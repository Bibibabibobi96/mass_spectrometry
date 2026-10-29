[CmdletBinding(DefaultParameterSetName='IsotropicCell')]
param(
  [Parameter(Mandatory=$true)][string]$ProjectId,
  [Parameter(Mandatory=$true)][string]$RuntimeProfileId,
  [Parameter(Mandatory=$true)][string]$DesignProfileId,
  [string]$ParticleSourcePath='',
  [Parameter(Mandatory=$true)][string]$EngineeringBudgetPath,
  [string]$ResolvedRuntimeProfilePath='',
  [string]$EvidenceContractPath='',
  [string]$RunId='',
  [string]$ReferenceComsolRunId='',
  [Parameter(ParameterSetName='IsotropicCell')]
  [ValidateScript({[double]::IsFinite($_) -and $_ -gt 0})][double]$CellMm=0.4,
  [Parameter(Mandatory=$true,ParameterSetName='AnisotropicCell')]
  [ValidateScript({[double]::IsFinite($_) -and $_ -gt 0})][double]$CellMmX,
  [Parameter(Mandatory=$true,ParameterSetName='AnisotropicCell')]
  [ValidateScript({[double]::IsFinite($_) -and $_ -gt 0})][double]$CellMmY,
  [Parameter(Mandatory=$true,ParameterSetName='AnisotropicCell')]
  [ValidateScript({[double]::IsFinite($_) -and $_ -gt 0})][double]$CellMmZ,
  [string]$SimionExe='',
  [string]$PythonExe='',
  [ValidateRange(4,2147483647)][int]$RfStepsPerPeriod=80,
  [ValidateRange(0,2147483647)][int]$TrajectoryQuality=10,
  [ValidateScript({[double]::IsFinite($_) -and $_ -gt 0})][double]$MaximumTimeUs=80.0,
  [ValidateSet('primary_and_zero_axial_control','primary_and_rf_off_energy_control','primary_only')]
  [string]$CaseSet='primary_and_zero_axial_control',
  [ValidateSet('compact','qualification','solver_review')][string]$RetentionClass='solver_review',
  [string]$RetentionReason='Producer-owned fractional field/IOB and complete batch evidence retained for explicit stage reuse.',
  [string]$SourceFamilyPath='',
  [string]$OperatingPointId='',
  [string]$ContinuationPredecessorManifestPath='',
  [string]$NativeFieldRunPath='',
  [string]$ResultPath=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$entryScriptHash=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash
$runTimer=[Diagnostics.Stopwatch]::StartNew();$phaseTimings=[ordered]@{};$phaseName='prepare';$phaseBoundary=0.0
function Set-RfRunPhase([string]$Next){
  $now=$runTimer.Elapsed.TotalSeconds
  if(-not$phaseTimings.Contains($phaseName)){$phaseTimings[$phaseName]=0.0}
  $phaseTimings[$phaseName]+=$now-$phaseBoundary
  $script:phaseBoundary=$now
  if($Next){$script:phaseName=$Next}
}
$resolvedCellMmX=if($PSCmdlet.ParameterSetName-eq'AnisotropicCell'){$CellMmX}else{$CellMm}
$resolvedCellMmY=if($PSCmdlet.ParameterSetName-eq'AnisotropicCell'){$CellMmY}else{$CellMm}
$resolvedCellMmZ=if($PSCmdlet.ParameterSetName-eq'AnisotropicCell'){$CellMmZ}else{$CellMm}
if($CaseSet-eq'primary_only'-and-not[string]::IsNullOrWhiteSpace($EvidenceContractPath)){
  throw 'Primary-only SIMION runs cannot consume a paired-case evidence contract.'
}

function Get-SimionPaGridAudit {
  param(
    [Parameter(Mandatory=$true)][string]$GemPath,
    $MaximumPaGridPoints=$null
  )
  $gemText=Get-Content -LiteralPath $GemPath -Raw -Encoding ASCII
  $matches=[regex]::Matches(
    $gemText,
    '(?m)^\s*pa_define\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,'
  )
  if($matches.Count-ne 1){
    throw 'SIMION GEM must contain exactly one parseable pa_define grid.'
  }
  $nx=[int64]::Parse($matches[0].Groups[1].Value)
  $ny=[int64]::Parse($matches[0].Groups[2].Value)
  $nz=[int64]::Parse($matches[0].Groups[3].Value)
  $gridPoints=[decimal]$nx*[decimal]$ny*[decimal]$nz
  $maximum=if($null-eq$MaximumPaGridPoints){$null}else{[decimal]$MaximumPaGridPoints}
  $status=if($null-eq$maximum){'NOT_CONFIGURED'}elseif($gridPoints-le$maximum){'PASS'}else{'FAIL'}
  return [ordered]@{
    schema_version=1
    role='multipole_simion_pa_grid_audit'
    nx=$nx
    ny=$ny
    nz=$nz
    grid_points=$gridPoints
    maximum_pa_grid_points=$maximum
    status=$status
  }
}

$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $PSScriptRoot 'simion_execution.ps1')
. (Join-Path $PSScriptRoot 'simion_field_checkpoint_support.ps1')
$particleSourceInput=if($ParticleSourcePath){(Resolve-Path -LiteralPath $ParticleSourcePath).Path}else{$null}
$engineeringBudgetInput=(Resolve-Path -LiteralPath $EngineeringBudgetPath).Path
$engineeringBudgetAuthority=Get-Content -LiteralPath $engineeringBudgetInput -Raw -Encoding UTF8|ConvertFrom-Json
$resolvedRuntimeInput=$null
$resolvedRuntimeDocument=$null
$resolvedRuntimeInputSha=$null
$hasReleaseSpec=$false
$executionBatching=$null
$writerCompletionUnknown=$false
$nativeOperations=[Collections.ArrayList]::new()
$retainedFormalBatchOutputs=@{}
$resourceIdentityWasUnknown=$false
# Repository scheduling is the default for this independent-particle runner.
# A runtime profile may constrain resource identity, but cannot opt out.
$automaticDispatch=[pscustomobject]@{kind='automatic';field_kind='rf';independent_particles=$true}
if(-not[string]::IsNullOrWhiteSpace($ResolvedRuntimeProfilePath)){
  $resolvedRuntimeInput=(Resolve-Path -LiteralPath $ResolvedRuntimeProfilePath).Path
  $resolvedRuntimeInputSha=(Get-FileHash -LiteralPath $resolvedRuntimeInput -Algorithm SHA256).Hash
  $resolvedRuntimeDocument=Get-Content -LiteralPath $resolvedRuntimeInput -Raw -Encoding UTF8|ConvertFrom-Json
  $hasReleaseSpec=$resolvedRuntimeDocument.particle_source.PSObject.Properties.Name-contains'release_spec'
  if([int]$resolvedRuntimeDocument.schema_version-ne 1-or
    [string]$resolvedRuntimeDocument.role-ne'multipole_resolved_runtime_profile'-or
    [string]$resolvedRuntimeDocument.project_id-ne$ProjectId-or
    [string]$resolvedRuntimeDocument.runtime_profile_id-ne$RuntimeProfileId-or
    [string]$resolvedRuntimeDocument.design_profile_id-ne$DesignProfileId-or
    ($hasReleaseSpec-and$null-ne$particleSourceInput)-or
    (-not$hasReleaseSpec-and[string]$resolvedRuntimeDocument.particle_source.path-ne$particleSourceInput)-or
    [string]$resolvedRuntimeDocument.engineering_budget.path-ne$engineeringBudgetInput
  ){throw 'Resolved runtime-profile snapshot identity differs from runner arguments.'}
  if($resolvedRuntimeDocument.PSObject.Properties.Name-contains'simion_dispatch'){
    $declaredDispatch=$resolvedRuntimeDocument.simion_dispatch
    if([string]$declaredDispatch.kind-ne'automatic'-or
      [string]$declaredDispatch.field_kind-notin@('rf','electrostatic')-or
      [bool]$declaredDispatch.independent_particles-ne$true
    ){throw 'Resolved SIMION dispatch is invalid.'}
    if([string]$declaredDispatch.field_kind-ne'rf'){
      throw 'This RF multipole runner only accepts rf resource identity.'
    }
  }
}
if(-not$hasReleaseSpec-and$null-eq$particleSourceInput){throw 'Canonical CSV source path is required for this runtime profile.'}
if($hasReleaseSpec-and($SourceFamilyPath-or$OperatingPointId-or
  ($resolvedRuntimeDocument.PSObject.Properties.Name-contains'particle_source_derivation')-or
  ($resolvedRuntimeDocument.PSObject.Properties.Name-contains'particle_source_phase_derivation'))){
  throw 'Release spec cannot be combined with another source authority or transform.'
}
$campaignSelection=$null
if([string]$engineeringBudgetAuthority.role-eq'multipole_transport_experiment_campaign'){
  if($null-eq$resolvedRuntimeDocument-or
    -not($resolvedRuntimeDocument.PSObject.Properties.Name-contains'campaign')
  ){throw 'Campaign transport requires the resolved runtime-profile snapshot.'}
  $campaignSelection=$resolvedRuntimeDocument.campaign
  if([string]$campaignSelection.path-ne$engineeringBudgetInput-or
    [string]$campaignSelection.experiment_id-ne$RuntimeProfileId-or
    [string]$campaignSelection.sha256-ne(
      Get-FileHash -LiteralPath $engineeringBudgetInput -Algorithm SHA256
    ).Hash
  ){throw 'Campaign authority differs from the resolved runtime-profile snapshot.'}
}
$hasSourceFamily=-not[string]::IsNullOrWhiteSpace($SourceFamilyPath)
$hasOperatingPoint=-not[string]::IsNullOrWhiteSpace($OperatingPointId)
if($hasSourceFamily-ne$hasOperatingPoint){
  throw 'SourceFamilyPath and OperatingPointId must be supplied together.'
}
$sourceFamilyInput=if($hasSourceFamily){(Resolve-Path -LiteralPath $SourceFamilyPath).Path}else{$null}
$registryPreflight=Get-Content -LiteralPath (Join-Path $repoRoot 'config\project_registry.json') -Raw -Encoding UTF8|ConvertFrom-Json
$projectMatches=@($registryPreflight.projects|Where-Object{[string]$_.project_id-eq$ProjectId})
if($projectMatches.Count-ne 1){throw "ProjectId is not unique in the canonical project registry: $ProjectId"}
$simion=if($SimionExe){[IO.Path]::GetFullPath($SimionExe)}else{Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
if([string]::IsNullOrWhiteSpace($RunId)){
  $RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+"__sim__simion__$($ProjectId.Replace('_','-'))-$($DesignProfileId.Replace('_','-'))__resolved-l3"
}
$budgetPreflight=Join-Path ([IO.Path]::GetTempPath()) ("multipole_budget_{0}.json"-f[guid]::NewGuid())
try{
  Push-Location $repoRoot
  try{
    $budgetArguments=@('-m','projects.rf_multipole_ion_optics.runtime.resource_budget',
      '--repo-root',$repoRoot,'--budget',$engineeringBudgetInput,
      '--project-id',$ProjectId,'--solver','simion',
      '--runtime-profile-id',$RuntimeProfileId,
      '--design-profile-id',$DesignProfileId,
      '--retention-class',$RetentionClass,'--output',$budgetPreflight)
    if($particleSourceInput){$budgetArguments+=@('--particle-source',$particleSourceInput)}
    $budgetArguments+=@('--run-id',$RunId)
    & $python @budgetArguments
  }finally{Pop-Location}
  if($LASTEXITCODE-ne 0){throw 'SIMION resource-budget preflight failed.'}
  $resolvedBudgetPreflight=Get-Content -LiteralPath $budgetPreflight -Raw -Encoding UTF8|ConvertFrom-Json
  if($hasReleaseSpec-and(
    ($resolvedBudgetPreflight.particle_source|ConvertTo-Json -Depth 20 -Compress)-cne
    ($resolvedRuntimeDocument.particle_source|ConvertTo-Json -Depth 20 -Compress))){
    throw 'Budget source authority differs from the selected runtime profile.'
  }
  $authorizedNumerics=$resolvedBudgetPreflight.solver_numerics
  $authorizedCell=$authorizedNumerics.cell_mm_xyz
  if($null-eq$authorizedCell){
    throw 'Authorized SIMION numerics omit canonical cell_mm_xyz.'
  }
  if(-not[string]::IsNullOrWhiteSpace([string]$resolvedBudgetPreflight.authorized_run_id)-and
    [string]$resolvedBudgetPreflight.authorized_run_id-cne$RunId){
    throw 'RunId differs from the authorized resource-budget scope.'
  }
  if([double]$authorizedCell.x-ne$resolvedCellMmX-or
    [double]$authorizedCell.y-ne$resolvedCellMmY-or
    [double]$authorizedCell.z-ne$resolvedCellMmZ-or
    [int]$authorizedNumerics.trajectory_quality-ne$TrajectoryQuality-or
    [int]$authorizedNumerics.trajectory.rf_steps_per_period-ne$RfStepsPerPeriod-or
    [double]$authorizedNumerics.trajectory.maximum_global_time_us-ne$MaximumTimeUs){
    throw 'SIMION numerical arguments differ from the authorized runtime profile.'
  }
}finally{
  Remove-Item -LiteralPath $budgetPreflight -Force -ErrorAction SilentlyContinue
}
if(-not(Test-Path -LiteralPath $simion -PathType Leaf)){
  throw "SIMION executable is missing: $simion"
}
$hostRuntimeSourcePaths=@(
  'common/host_execution_lease.ps1','common/host_resource_scheduler.py',
  'common/host_resource_policy.json','common/require_powershell7.ps1','common/resource_budget_support.ps1')
$analysisSourcePaths=@('common/analysis/particle_census.py')
$executionCapacityPaths=Get-RunPackageCopiedSourcePaths -RepoRoot $repoRoot `
  -SourceRelativeDirectories @('common/contracts','common/simion','common/ion_release','projects/rf_multipole_ion_optics/core','projects/rf_multipole_ion_optics/runtime','projects/rf_multipole_ion_optics/analysis','projects/rf_multipole_ion_optics/config','projects/rf_multipole_ion_optics/comsol','projects/rf_multipole_ion_optics/simion') `
  -Extensions @('.py','.json','.ps1','.lua')
$executionCapacityPaths+=@(($hostRuntimeSourcePaths+$analysisSourcePaths)|ForEach-Object{"inputs/code/$_"})
$continuationCapacity=$null;$continuationGuards=[Collections.ArrayList]::new();$continuationPredecessor=$null;$continuationChain=@()
$projectRuns=[IO.Path]::GetFullPath((Join-Path $workspaceRoot "artifacts\projects\$ProjectId\runs"))
$prefix=$projectRuns.TrimEnd([IO.Path]::DirectorySeparatorChar)+[IO.Path]::DirectorySeparatorChar
if(-not$ResultPath){$ResultPath=Join-Path $workspaceRoot "artifacts\projects\$ProjectId\scratch\workflow_results\$RunId\result.json"}
$ResultPath=[IO.Path]::GetFullPath($ResultPath)
$targetRun=[IO.Path]::GetFullPath((Join-Path $projectRuns $RunId)).TrimEnd('\')+'\'
if($ResultPath.StartsWith($targetRun,[StringComparison]::OrdinalIgnoreCase)){throw 'Workflow Result must be outside the owner run.'}
if(Test-Path -LiteralPath $ResultPath){throw 'Workflow Result already exists; choose a new run and Result path.'}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ResultPath)|Out-Null
if($ContinuationPredecessorManifestPath){
  $ContinuationPredecessorManifestPath=(Resolve-Path -LiteralPath $ContinuationPredecessorManifestPath).Path
  if([IO.Path]::GetFileName($ContinuationPredecessorManifestPath)-cne'run_manifest.json'){
    throw 'Continuation requires an explicit predecessor run manifest.'
  }
  $continuationPredecessor=Split-Path -Parent $ContinuationPredecessorManifestPath
  if(-not[IO.Path]::GetFullPath($continuationPredecessor).StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)-or
     [IO.Path]::GetFileName($continuationPredecessor)-ceq$RunId){throw 'Continuation requires a distinct same-project predecessor.'}
  Push-Location $repoRoot
  try{$chainJson=& $python -m projects.rf_multipole_ion_optics.runtime.simion_batch_continuation --predecessor $continuationPredecessor --project $ProjectId
    if($LASTEXITCODE-ne0){throw 'RF continuation ancestry is invalid.'}}
  finally{Pop-Location}
  $continuationChain=@(($chainJson-join"`n")|ConvertFrom-Json)
  foreach($ancestor in $continuationChain){
    if(-not[IO.Path]::GetFullPath([string]$ancestor).StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){
      throw 'RF continuation ancestry escapes the project run root.'
    }
  }
}
$continuationCapacity=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -RunDirectory (Join-Path $projectRuns $RunId) `
  -CommittedNewBytes ([int64]$resolvedBudgetPreflight.limits.transient_run_directory_bytes) -ProtectedPaths $continuationChain `
  -Owner ("run-artifact-workflow:{0}:{1}"-f$ProjectId,$RunId)
if($ContinuationPredecessorManifestPath){
  try{
    Protect-RfSimionContinuationEvidence -Chain $continuationChain -Guards $continuationGuards
    Push-Location $repoRoot
    try{$chainCheck=& $python -m projects.rf_multipole_ion_optics.runtime.simion_batch_continuation --predecessor $continuationPredecessor --project $ProjectId
      if($LASTEXITCODE-ne0-or(($chainCheck-join"`n")|ConvertFrom-Json|ConvertTo-Json -Compress)-cne($continuationChain|ConvertTo-Json -Compress)){throw 'RF continuation ancestry changed during admission.'}}
    finally{Pop-Location}
  }catch{
    $admissionFailure=$_
    foreach($stream in $continuationGuards){$stream.Dispose()}
    try{Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $continuationCapacity|Out-Null}
    catch{$admissionFailure.Exception.Data['capacity_release_error']=[string]$_}
    throw $admissionFailure
  }
}
try{$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$ProjectId") -RunId $RunId `
  -Project $ProjectId -Mode 'resolved_design_transport' -Software @('SIMION 2020','Python 3.11') `
  -RetentionContractEnabled -CapacityLedgerLifecycleEnabled `
  -RetentionClass $RetentionClass -RetentionReason $RetentionReason `
  -AdditionalDirectories @('simion') -UseShortExecutionPath `
  -ExpectedExecutionRelativePaths $executionCapacityPaths}
catch{$packageFailure=$_;foreach($stream in $continuationGuards){$stream.Dispose()};if($null-ne$continuationCapacity){try{Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $continuationCapacity|Out-Null}catch{$packageFailure.Exception.Data['capacity_release_error']=[string]$_}};throw $packageFailure}
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir
$logDir=$package.log_dir;$solverDir=Join-Path $runDir 'simion'
$physicalRunDir=$package.artifact_run_dir
$ownerContext=$null;$hostReleased=$false;$hostReleaseState=@{released=$false;completion=$null;unknown=$false};$deferFinalization=$false
$fieldCheckpointGuard=$null;$fieldCheckpointOutputs=@();$layoutInspectionRequired=$false;$flightIobPath=Join-Path $physicalRunDir 'simion/quad_monolithic.iob'
$runConfig=$package.run_config;$summary=$package.summary;$manifestRepoRoot=$repoRoot
$resourceBudgetExceeded=$false
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
$hostExecutionOutcome='failed'
$simionRunFailure=$null
try{$hostExecutionLease=Enter-HostResourceStage -Role SIMION -Stage prepare -RunId $RunId `
  -Budget (Get-HostResourceBudget -Role SIMION -Stage prepare)}
catch{$leaseFailure=$_;foreach($stream in $continuationGuards){$stream.Dispose()};if($null-ne$continuationCapacity){try{Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $continuationCapacity|Out-Null}catch{$leaseFailure.Exception.Data['capacity_release_error']=[string]$_}};throw $leaseFailure}


try{
  $codeRoot=Join-Path $inputDir 'code'
  foreach($area in @('common/contracts','common/simion','common/ion_release','projects/rf_multipole_ion_optics/core','projects/rf_multipole_ion_optics/runtime','projects/rf_multipole_ion_optics/analysis','projects/rf_multipole_ion_optics/config','projects/rf_multipole_ion_optics/comsol','projects/rf_multipole_ion_optics/simion')){
    $sourceRoot=Join-Path $repoRoot $area;$destinationRoot=Join-Path $codeRoot $area
    Get-ChildItem -LiteralPath $sourceRoot -Recurse -File|Where-Object{
      $_.Extension -in @('.py','.json','.ps1','.lua')
    }|ForEach-Object{
      $relative=$_.FullName.Substring($sourceRoot.Length).TrimStart('\')
      $destination=Join-Path $destinationRoot $relative
      New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination)|Out-Null
      Copy-Item -LiteralPath $_.FullName -Destination $destination
    }
  }
  foreach($relative in @($hostRuntimeSourcePaths+$analysisSourcePaths)){
    Copy-VerifiedRunInput -Source (Join-Path $repoRoot $relative) `
      -Destination (Join-Path $codeRoot $relative)|Out-Null
  }
  $codeInventory=Join-Path $inputDir 'code_inventory.json'
  $resolvedCodeRoot=(Resolve-Path -LiteralPath $codeRoot).Path
  $inventory=@(Get-ChildItem -LiteralPath $codeRoot -Recurse -File|Sort-Object FullName|ForEach-Object{
    [ordered]@{path=[IO.Path]::GetRelativePath($resolvedCodeRoot,$_.FullName).Replace('\','/');sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}
  })
  [ordered]@{schema_version=1;role='frozen_code_inventory';files=$inventory}|
    ConvertTo-Json -Depth 5|Set-Content -LiteralPath $codeInventory -Encoding UTF8
  $ownerSource=Join-Path $physicalRunDir 'inputs/code/projects/rf_multipole_ion_optics/runtime/run_simion_finite_3d_transport.ps1'
  $ownerRecord=Get-Item -LiteralPath $ownerSource
  $ownerInventory=@($inventory|Where-Object{$_.path-ceq'projects/rf_multipole_ion_optics/runtime/run_simion_finite_3d_transport.ps1'})
  if($ownerInventory.Count-ne1-or$ownerInventory[0].sha256-ine$entryScriptHash){throw 'Frozen PowerShell owner differs from the launched source.'}
  . (Join-Path $codeRoot 'common/contracts/run_artifact_workflow.ps1') -ResultPath $ResultPath -ResumeFinalization
  $ownerContext=Initialize-RunArtifactPowerShellOwner -Python $python -RepoRoot $repoRoot -Package $package `
    -CapacitySession $continuationCapacity -ResultPath $ResultPath -EntrypointPath $ownerSource `
    -EntrypointRecord @{path=$ownerSource;exists=$true;bytes=[long]$ownerRecord.Length;sha256=$entryScriptHash} `
    -CommitmentInputPaths @($engineeringBudgetInput) -Software @('SIMION 2020','Python 3.11')
  $workflowRequestPath=$ownerContext.request_path
  $workflowRequest=Get-Content -LiteralPath $workflowRequestPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $manifestRepoRoot=$codeRoot
  . (Join-Path $codeRoot 'projects\rf_multipole_ion_optics\runtime\simion_layout_template_support.ps1')
  . (Join-Path $codeRoot 'projects\rf_multipole_ion_optics\runtime\simion_execution.ps1')
  . (Join-Path $codeRoot 'projects\rf_multipole_ion_optics\runtime\simion_field_checkpoint_support.ps1')

  $templateDir=Join-Path $inputDir 'simion_layout_template'
  $templateRegistryFrozen=Join-Path $codeRoot 'projects\rf_multipole_ion_optics\config\simion_layout_template.json'
  $template=Resolve-MultipoleSimionLayoutTemplate -Python $python `
    -RepositoryRoot $repoRoot -TemplateDirectory $templateDir `
    -RegistryPath $templateRegistryFrozen -ModuleRoot $codeRoot
  $templateResolution=$template.resolution
  $templateProfile=$template.profile
  $templateRegistryInput=$template.registry
  $templateRegistrationManifest=$template.registration_manifest
  $templateIob=$template.iob
  $templateCon=$template.con
  $templateSeedPa=$template.placeholder_pa0

  $profileResolution=Join-Path $inputDir 'design_profile_resolution.json'
  $resolvedRuntimeProfile=$null
  if($resolvedRuntimeInput){
    if((Get-FileHash -LiteralPath $resolvedRuntimeInput -Algorithm SHA256).Hash-ne$resolvedRuntimeInputSha){
      throw 'Resolved runtime-profile snapshot changed before it was frozen.'
    }
    $resolvedRuntimeProfile=Copy-VerifiedRunInput -Source $resolvedRuntimeInput `
      -Destination (Join-Path $inputDir 'resolved_runtime_profile.json')
    if($campaignSelection-and
      (Get-FileHash -LiteralPath $engineeringBudgetInput -Algorithm SHA256).Hash-ne
        [string]$campaignSelection.sha256
    ){throw 'Campaign authority changed before it was frozen.'}
  }
  $engineeringBudget=Join-Path $inputDir 'engineering_budget.json'
  $engineeringBudget=Copy-VerifiedRunInput -Source $engineeringBudgetInput `
    -Destination $engineeringBudget
  if($campaignSelection-and
    (Get-FileHash -LiteralPath $engineeringBudget -Algorithm SHA256).Hash-ne
      [string]$campaignSelection.sha256
  ){throw 'Frozen campaign authority differs from the resolved runtime-profile snapshot.'}
  Push-Location $codeRoot
  try{
    $env:PYTHONPATH=$codeRoot
    & $python -m projects.rf_multipole_ion_optics.runtime.design_profile --repo-root $repoRoot --project-id $ProjectId `
      --design-profile-id $DesignProfileId --output $profileResolution
    if($LASTEXITCODE-ne 0){throw 'Governed design profile resolution failed.'}
  }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
  $profile=Get-Content -LiteralPath $profileResolution -Raw -Encoding UTF8|ConvertFrom-Json
  $identity=$profile.profile.identity
  $registry=Join-Path $inputDir 'project_registry.json';$descriptor=Join-Path $inputDir 'project.json'
  $profiles=Join-Path $inputDir 'design_profiles.json';$request=Join-Path $inputDir 'multipole_design_request.json'
  $variables=Join-Path $inputDir 'design_variables.json';$envelope=Join-Path $inputDir 'optimization_envelope.json'
  $modeRegistry=$null;$modeId=$null
  Copy-Item -LiteralPath $profile.registry_path -Destination $registry
  Copy-Item -LiteralPath $profile.descriptor_path -Destination $descriptor
  Copy-Item -LiteralPath $profile.profiles_path -Destination $profiles
  Copy-Item -LiteralPath $profile.paths.design_request -Destination $request
  Copy-Item -LiteralPath $profile.paths.design_variables -Destination $variables
  Copy-Item -LiteralPath $profile.paths.optimization_envelope -Destination $envelope
  if($profile.profile.PSObject.Properties.Name-contains'mode_id'){
    $modeId=[string]$profile.profile.mode_id
    if(-not($profile.paths.PSObject.Properties.Name-contains'operating_mode_registry')){
      throw 'Typed design profile is missing its resolved operating-mode registry path.'
    }
    $modeRegistry=Join-Path $inputDir 'operating_modes.json'
    Copy-Item -LiteralPath $profile.paths.operating_mode_registry -Destination $modeRegistry
  }
  $resolved=Join-Path $inputDir 'multipole_resolved_design.json'
  if($resolvedRuntimeDocument){
    $snapshotDesign=$resolvedRuntimeDocument.design_profile_resolution.resolved_design
    if($null-eq$snapshotDesign){
      throw 'Resolved runtime-profile snapshot omits its resolved design.'
    }
    $snapshotDesign|ConvertTo-Json -Depth 100|Set-Content -LiteralPath $resolved -Encoding UTF8
    Push-Location $codeRoot
    try{
      $env:PYTHONPATH=$codeRoot
      & $python -m projects.rf_multipole_ion_optics.analysis.verify_resolved_design $resolved
      if($LASTEXITCODE-ne 0){throw 'Resolved runtime-profile design identity is invalid.'}
    }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
  }else{
    Push-Location $codeRoot
    try{
      $env:PYTHONPATH=$codeRoot
      $compileArguments=@('-m','projects.rf_multipole_ion_optics.core.compile_design_request',
        '--request',$request,'--design-variables',$variables,
        '--optimization-envelope',$envelope,'--output',$resolved,
        '--provenance-root',$inputDir,'--project-id',$ProjectId,
        '--radial-order-n',([string][int]$identity.radial_order_n),
        '--electrode-count',([string][int]$identity.electrode_count))
      if($modeRegistry){
        $compileArguments+=@('--operating-mode-registry',$modeRegistry,'--mode-id',$modeId)
      }
      & $python @compileArguments
      if($LASTEXITCODE-ne 0){throw 'Governed multipole design compilation failed.'}
    }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
  }
  $design=Get-Content -LiteralPath $resolved -Raw -Encoding UTF8|ConvertFrom-Json
  $resolvedHash=[string]$design.resolved_sha256
  if($resolvedRuntimeDocument-and $resolvedHash-ne
    [string]$resolvedRuntimeDocument.design_profile_resolution.resolved_design.resolved_sha256
  ){throw 'Frozen resolved design differs from the resolved runtime snapshot.'}
  $candidateRequest=$null
  if($resolvedRuntimeDocument-and
    $resolvedRuntimeDocument.design_profile_resolution.PSObject.Properties.Name-contains'candidate_request'){
    $candidateRequest=Join-Path $inputDir 'multipole_candidate_design_request.json'
    $resolvedRuntimeDocument.design_profile_resolution.candidate_request|
      ConvertTo-Json -Depth 100|Set-Content -LiteralPath $candidateRequest -Encoding UTF8
    if([string]$design.request.sha256-ne
      [string]$resolvedRuntimeDocument.design_profile_resolution.candidate_request_sha256
    ){throw 'Candidate design request identity differs from the frozen resolved design.'}
  }
  $particleSource=Join-Path $inputDir 'particle_source.csv'
  $volumeSnapshotReceipt=$null
  $releaseSpec=$null;$releaseReceipt=$null
  if($hasReleaseSpec){
    $releaseSpecIdentity=$null
    $releaseSpec=Copy-VerifiedRunInput -Source ([string]$resolvedRuntimeDocument.particle_source.release_spec.path) `
      -Destination (Join-Path $inputDir 'particle_source_release_spec.json') -VerifiedIdentity ([ref]$releaseSpecIdentity)
    if([string]$releaseSpecIdentity.sha256-cne[string]$resolvedRuntimeDocument.particle_source.release_spec.sha256-or
      [long]$releaseSpecIdentity.bytes-ne[long]$resolvedRuntimeDocument.particle_source.release_spec.bytes){
      throw 'Frozen release spec differs from the selected source authority.'
    }
    $releaseReceipt=Join-Path $inputDir 'particle_source_release_receipt.json'
  }
  $phaseDerivationMetadata=$null
  $phaseAuthoritySource=$null
  $phaseReferenceSource=$null
  $sourceEnergyOverride=$null
  # A physical source-volume snapshot is already a frozen simultaneous state.
  # Re-serializing it through the planar phase matcher changes its bytes and
  # invalidates the receipt despite unchanged physics.
  $hasVolumeSnapshotReceipt=($resolvedRuntimeDocument-and
    $resolvedRuntimeDocument.particle_source.PSObject.Properties.Name-contains'volume_snapshot_receipt')
  $sourceDerivationProperty=if(-not$hasVolumeSnapshotReceipt-and$resolvedRuntimeDocument-and
    $resolvedRuntimeDocument.PSObject.Properties.Name-contains'particle_source_derivation'){
    'particle_source_derivation'
  }elseif(-not$hasVolumeSnapshotReceipt-and$resolvedRuntimeDocument-and
    $resolvedRuntimeDocument.PSObject.Properties.Name-contains'particle_source_phase_derivation'){
    'particle_source_phase_derivation'
  }else{$null}
  if($sourceDerivationProperty){
    $phaseBinding=$resolvedRuntimeDocument.$sourceDerivationProperty
    $phaseAuthoritySource=Join-Path $inputDir 'particle_source_authority.csv'
    $phaseReferenceSource=Join-Path $inputDir 'particle_source_n1000_reference.csv'
    Copy-VerifiedRunInput -Source ([string]$phaseBinding.authority_source.path) `
      -Destination $phaseAuthoritySource|Out-Null
    Copy-VerifiedRunInput -Source ([string]$phaseBinding.n1000_reference_source.path) `
      -Destination $phaseReferenceSource|Out-Null
    if((Get-FileHash -LiteralPath $phaseAuthoritySource -Algorithm SHA256).Hash-ne
      [string]$phaseBinding.authority_source.sha256-or
      (Get-FileHash -LiteralPath $phaseReferenceSource -Algorithm SHA256).Hash-ne
      [string]$phaseBinding.n1000_reference_source.sha256
    ){throw 'Frozen phase-matched source authorities differ from the runtime snapshot.'}
    $phaseDerivationMetadata=Join-Path $inputDir 'particle_source_phase_derivation.json'
    Push-Location $codeRoot
    try{
      $env:PYTHONPATH=$codeRoot
      $phaseArguments=@('-m','projects.rf_multipole_ion_optics.runtime.phase_matched_particle_source',
        '--source',$phaseAuthoritySource,
        '--baseline-frequency-hz',([string]$phaseBinding.baseline_frequency_Hz),
        '--candidate-frequency-hz',([string]$phaseBinding.candidate_frequency_Hz),
        '--output-csv',$particleSource,'--output-metadata',$phaseDerivationMetadata)
      if([int]$phaseBinding.authority_particle_count-eq 100){
        $phaseArguments+=@('--n1000-reference',$phaseReferenceSource)
      }
      if($phaseBinding.PSObject.Properties.Name-contains'target_kinetic_energy_eV'){
        $sourceEnergyOverride=[double]$phaseBinding.target_kinetic_energy_eV
        $phaseArguments+=@('--target-kinetic-energy-ev',([string]$sourceEnergyOverride))
      }
      & $python @phaseArguments
      if($LASTEXITCODE-ne 0){throw 'Phase-matched canonical source derivation failed.'}
    }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
  }elseif(-not$hasReleaseSpec){
    Copy-Item -LiteralPath $particleSourceInput -Destination $particleSource
  }
  if($hasVolumeSnapshotReceipt){
    $volumeBinding=$resolvedRuntimeDocument.particle_source.volume_snapshot_receipt
    if($null-eq$volumeBinding-or
      -not($volumeBinding.PSObject.Properties.Name-contains'path')-or
      -not($volumeBinding.PSObject.Properties.Name-contains'sha256')){
      throw 'Resolved volume-source receipt binding is invalid.'
    }
    $volumeSourcePath=(Resolve-Path -LiteralPath ([string]$volumeBinding.path)).Path
    if((Get-FileHash -LiteralPath $volumeSourcePath -Algorithm SHA256).Hash-ne
      [string]$volumeBinding.sha256){
      throw 'Resolved volume-source receipt differs from its frozen hash.'
    }
    $volumeSnapshotReceipt=Join-Path $inputDir 'particle_source_volume_snapshot_receipt.json'
    Copy-Item -LiteralPath $volumeSourcePath -Destination $volumeSnapshotReceipt
  }
  $sourceFamily=$null;$sourceFamilySha=$null
  if($sourceFamilyInput){
    $sourceFamily=Join-Path $inputDir 'particle_source_family.json'
    Copy-Item -LiteralPath $sourceFamilyInput -Destination $sourceFamily
    $sourceFamilySha=(Get-FileHash -LiteralPath $sourceFamily -Algorithm SHA256).Hash
  }
  $sourceMetadata=Join-Path $inputDir 'particle_source_metadata.json'
  Push-Location $codeRoot
  try{
    $env:PYTHONPATH=$codeRoot
    $preflightArguments=@('-m','projects.rf_multipole_ion_optics.runtime.particle_source_preflight',
      '--source',$particleSource,'--resolved-design',$resolved,'--output',$sourceMetadata)
    if($sourceFamily){
      $preflightArguments+=@('--source-family',$sourceFamily,
        '--operating-point',$OperatingPointId,
        '--expected-source-family-sha256',$sourceFamilySha)
    }
    if($null-ne$sourceEnergyOverride){
      $preflightArguments+=@('--expected-kinetic-energy-ev',([string]$sourceEnergyOverride))
    }
    if($volumeSnapshotReceipt){
      $preflightArguments+=@('--volume-snapshot-receipt',$volumeSnapshotReceipt)
    }
    if($hasReleaseSpec){
      $preflightArguments+=@('--release-spec',$releaseSpec,'--release-receipt',$releaseReceipt,'--materialize-release')
    }
    & $python @preflightArguments
    if($LASTEXITCODE-ne 0){throw 'Canonical particle source preflight failed.'}
  }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
  $sourceMeta=Get-Content -LiteralPath $sourceMetadata -Raw -Encoding UTF8|ConvertFrom-Json
  if($hasReleaseSpec-and[int]$sourceMeta.particle_count-ne[int]$resolvedRuntimeDocument.particle_source.particle_count){
    throw 'Materialized source population differs from the authorized release spec.'
  }
  if($sourceFamily){
    $binding=$sourceMeta.operating_point_binding
    if($null-eq$binding -or
      [string]$binding.operating_point_id-ne$OperatingPointId -or
      [string]$binding.source_family_sha256-ne$sourceFamilySha
    ){throw 'Canonical particle source operating-point binding differs from the frozen runner input.'}
  }elseif($null-ne$sourceMeta.operating_point_binding){
    throw 'Canonical particle source reported an unexpected operating-point binding.'
  }
  $referenceComsolManifest=$null;$referenceComsolManifestSha=$null;$referenceComsolSourceRunId=$null
  if(-not[string]::IsNullOrWhiteSpace($ReferenceComsolRunId)){
    Push-Location $codeRoot
    try{
      $env:PYTHONPATH=$codeRoot
      $referenceIdValidation=& $python -m common.contracts.artifact_naming run $ReferenceComsolRunId
      if($LASTEXITCODE-ne 0 -or -not($referenceIdValidation-match '^ARTIFACT_ID=PASS ')){
        throw "Invalid ReferenceComsolRunId: $ReferenceComsolRunId"
      }
      $projectRunsRoot=[IO.Path]::GetFullPath((Join-Path $workspaceRoot "artifacts\projects\$ProjectId\runs"))
      $referenceRunDir=[IO.Path]::GetFullPath((Join-Path $projectRunsRoot $ReferenceComsolRunId))
      if(-not $referenceRunDir.StartsWith(
        $projectRunsRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase
      )){throw "Reference COMSOL run escapes the same-project artifact root: $ReferenceComsolRunId"}
      $referenceManifestOriginal=Join-Path $referenceRunDir 'run_manifest.json'
      if(-not(Test-Path -LiteralPath $referenceManifestOriginal -PathType Leaf)){
        throw "Reference COMSOL run manifest is missing: $referenceManifestOriginal"
      }
      & $python -m common.contracts.verify_run_manifest $referenceManifestOriginal `
        --require-status success --require-local-run-config `
        --require-run-id $ReferenceComsolRunId --require-project $ProjectId `
        --require-mode resolved_design_transport --require-design-profile-id $DesignProfileId `
        --require-parent-resolved-design-sha256 $resolvedHash `
        --require-particle-source-sha256 ([string]$sourceMeta.source_sha256)|Out-Null
      if($LASTEXITCODE-ne 0){throw "Reference COMSOL run verification failed: $ReferenceComsolRunId"}
    }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
    $referenceComsolManifest=Join-Path $inputDir 'reference_comsol_run_manifest.json'
    Copy-Item -LiteralPath $referenceManifestOriginal -Destination $referenceComsolManifest
    $referenceComsolManifestSha=(Get-FileHash -LiteralPath $referenceComsolManifest -Algorithm SHA256).Hash
    $referenceComsolSourceRunId=$ReferenceComsolRunId
  }
  $numerics=Join-Path $inputDir 'solver_numerics.json'
  $solverNumericsDocument=[ordered]@{schema_version=2;role='multipole_simion_solver_numerics';
    cell_mm_xyz=[ordered]@{x=$resolvedCellMmX;y=$resolvedCellMmY;z=$resolvedCellMmZ};
    trajectory_quality=$TrajectoryQuality;
    trajectory=[ordered]@{rf_steps_per_period=$RfStepsPerPeriod;maximum_global_time_us=$MaximumTimeUs}}
  $solverNumericsDocument|
    ConvertTo-Json -Depth 5|Set-Content -LiteralPath $numerics -Encoding UTF8
  $evidence=$null
  if(-not[string]::IsNullOrWhiteSpace($EvidenceContractPath)){
    $evidence=Join-Path $inputDir 'evidence_contract.json'
    Copy-Item -LiteralPath ([IO.Path]::GetFullPath($EvidenceContractPath)) -Destination $evidence
  }

  $gem=Join-Path $solverDir 'quad_monolithic.gem';$fly2=Join-Path $solverDir 'quad_monolithic.fly2'
  $states=Join-Path $inputDir 'source_states.lua'
  Push-Location $codeRoot
  try{
    $env:PYTHONPATH=$codeRoot
    $batchPlan=Join-Path $inputDir 'simion_execution_batch_plan.json'
    $dispatchPlan=$null
    if($null-ne$automaticDispatch){
      $dispatchRequest=Join-Path $inputDir 'simion_dispatch_request.json'
      $dispatchPlan=Join-Path $inputDir 'simion_repository_dispatch_plan.json'
      $resourceProfiles=Join-Path $inputDir 'simion_resource_profiles.json'
      $dispatchRequestDocument=[ordered]@{solver='SIMION';field_kind=[string]$automaticDispatch.field_kind;
        particle_count=[int]$sourceMeta.particle_count;independent_particles=$true;
        trajectory_quality_profile_id=("tqual_{0}"-f$TrajectoryQuality);
        time_integration_profile_id=$RuntimeProfileId;
        rf_steps_per_period=$(if([string]$automaticDispatch.field_kind-eq'rf'){$RfStepsPerPeriod}else{$null})}
      $dispatchRequestDocument|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $dispatchRequest -Encoding UTF8
      $projectRunsRoot=Join-Path $workspaceRoot "artifacts\projects\$ProjectId\runs"
      & $python -m common.simion.resource_profile discover --runs-root $projectRunsRoot --output $resourceProfiles
      if($LASTEXITCODE-ne 0){throw 'SIMION resource profile discovery failed.'}
      & $python -m common.simion.resource_scheduler --request $dispatchRequest `
        --profiles $resourceProfiles --output $dispatchPlan
      if($LASTEXITCODE-ne 0){throw 'SIMION repository dispatch planning failed.'}
      $dispatchPlanDocument=Get-Content -LiteralPath $dispatchPlan -Raw -Encoding UTF8|ConvertFrom-Json
      if([string]$dispatchPlanDocument.role-ne'simion_repository_dispatch_plan'-or
        [int]$dispatchPlanDocument.particle_count-ne[int]$sourceMeta.particle_count-or
        @($dispatchPlanDocument.waves).Count-ne1-or
        [int]$dispatchPlanDocument.waves[0].batch_count-lt1
      ){throw 'SIMION repository dispatch plan differs from the canonical source.'}
      $executionBatching=[pscustomobject]@{dispatch='single_wave_parallel';
        batch_count=[int]$dispatchPlanDocument.waves[0].batch_count}
    }
    if($null-ne$dispatchPlan){
      & $python -m common.simion.particle_batching --from-dispatch-plan $dispatchPlan --output $batchPlan
    }else{
      $declaredBatchCount=if($null-ne$executionBatching){[int]$executionBatching.batch_count}else{1}
      & $python -m common.simion.particle_batching --particle-count ([string]$sourceMeta.particle_count) `
        --batch-count ([string]$declaredBatchCount) --output $batchPlan
    }
    if($LASTEXITCODE-ne 0){throw 'SIMION shared single-wave batch planning failed.'}
    $batchPlanDocument=Get-Content -LiteralPath $batchPlan -Raw -Encoding UTF8|ConvertFrom-Json
    if([string]$batchPlanDocument.dispatch-ne'single_wave_parallel'-or
        [int]$batchPlanDocument.particle_count-ne[int]$sourceMeta.particle_count){
      throw 'SIMION shared single-wave batch plan differs from the canonical source.'
    }
    & $python -m projects.rf_multipole_ion_optics.simion.simion_geometry --resolved-design $resolved `
      --cell-mm-x $resolvedCellMmX --cell-mm-y $resolvedCellMmY `
      --cell-mm-z $resolvedCellMmZ --output $gem
    if($LASTEXITCODE-ne 0){throw 'SIMION GEM projection failed.'}
    $sourceProjectionArguments=@('-m','projects.rf_multipole_ion_optics.runtime.simion_particle_source',
      '--particles',$particleSource,'--resolved-design',$resolved,
      '--fly2',$fly2,'--source-states-lua',$states)
    if($sourceFamily){
      $sourceProjectionArguments+=@('--source-family',$sourceFamily,
        '--operating-point',$OperatingPointId,
        '--expected-source-family-sha256',$sourceFamilySha)
    }
    if($null-ne$sourceEnergyOverride){
      $sourceProjectionArguments+=@('--expected-kinetic-energy-ev',([string]$sourceEnergyOverride))
    }
    if($volumeSnapshotReceipt){
      $sourceProjectionArguments+=@('--volume-snapshot-receipt',$volumeSnapshotReceipt)
    }
    if($hasReleaseSpec){$sourceProjectionArguments+=@('--release-spec',$releaseSpec,'--release-receipt',$releaseReceipt)}
    & $python @sourceProjectionArguments
    if($LASTEXITCODE-ne 0){throw 'SIMION particle projection failed.'}
    function Set-SimionBatchesFromPlan {
      param([Parameter(Mandatory)]$Plan)
      if([string]$Plan.dispatch-ne'single_wave_parallel'){
        throw 'SIMION execution batching dispatch is not supported.'
      }
      $updatedBatches=@()
      foreach($plannedBatch in @($Plan.batches)){
        $batchIndex=[int]$plannedBatch.index;$first=[int]$plannedBatch.particle_id_min;$last=[int]$plannedBatch.particle_id_max
        if(@($Plan.batches).Count-eq 1-and$first-eq 1-and
          $last-eq[int]$sourceMeta.particle_count){
          $updatedBatches+=[pscustomobject]@{index=1;particle_id_min=$first;particle_id_max=$last;
            simion_particle_id_offset=[int]$plannedBatch.simion_particle_id_offset;fly2=$fly2;states=$states}
        }else{
          $batchFly2=Join-Path $solverDir ("quad_monolithic_batch_{0:D2}.fly2" -f $batchIndex)
          $batchStates=Join-Path $inputDir ("source_states_batch_{0:D2}.lua" -f $batchIndex)
          $batchArguments=@($sourceProjectionArguments)+@('--particle-id-min',[string]$first,
            '--particle-id-max',[string]$last,'--simion-particle-id-offset',[string]$plannedBatch.simion_particle_id_offset)
          $replaceFly=[array]::IndexOf($batchArguments,'--fly2');$replaceStates=[array]::IndexOf($batchArguments,'--source-states-lua')
          $batchArguments[$replaceFly+1]=$batchFly2;$batchArguments[$replaceStates+1]=$batchStates
          # The projection CLI reports a diagnostic line on stdout.  This
          # function returns only the final case summary to its caller.
          & $python @batchArguments | Out-Null
          if($LASTEXITCODE-ne 0){throw "SIMION particle batch projection failed: $batchIndex"}
          $updatedBatches+=[pscustomobject]@{index=$batchIndex;particle_id_min=$first;
            particle_id_max=$last;simion_particle_id_offset=[int]$plannedBatch.simion_particle_id_offset;
            fly2=$batchFly2;states=$batchStates}
        }
      }
      $script:simionBatches=@($updatedBatches)
    }
    Set-SimionBatchesFromPlan -Plan $batchPlanDocument
    $resourceCalibrationRequired=($null-ne$dispatchPlan-and
      [string]$dispatchPlanDocument.estimation.kind-eq'formal_first_batch_observation')
    $resourceIdentityWasUnknown=$resourceCalibrationRequired
  }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
  $maximumPaGridPoints=if(
    $resolvedBudgetPreflight.limits.PSObject.Properties.Name-contains'maximum_pa_grid_points'
  ){[int64]$resolvedBudgetPreflight.limits.maximum_pa_grid_points}else{$null}
  $gridAudit=Join-Path $inputDir 'simion_grid_audit.json'
  $gridAuditDocument=Get-SimionPaGridAudit -GemPath $gem `
    -MaximumPaGridPoints $maximumPaGridPoints
  $gridAuditDocument|ConvertTo-Json -Depth 4|
    Set-Content -LiteralPath $gridAudit -Encoding UTF8
  if($gridAuditDocument.status-eq'FAIL'){
    throw "SIMION PA grid point budget exceeded: $($gridAuditDocument.grid_points) > $maximumPaGridPoints"
  }
  Copy-VerifiedRunInput `
    -Source (Join-Path $codeRoot 'projects\rf_multipole_ion_optics\simion\simion_transport.lua') `
    -Destination (Join-Path $solverDir 'multipole_runtime_program.lua')|Out-Null
  $rfDriveKernelLua=Join-Path $inputDir 'multipole_rf_drive_kernel.lua'
  Copy-VerifiedRunInput `
    -Source (Join-Path $codeRoot 'common\simion\rf_drive.lua') `
    -Destination $rfDriveKernelLua|Out-Null

  $exitPreparationCode=@'
import json,sys
from pathlib import Path
from projects.rf_multipole_ion_optics.core.component_port import prepare_exit_observation_inputs
run,resolved=map(Path,sys.argv[1:3])
print(json.dumps(prepare_exit_observation_inputs(run,json.loads(resolved.read_text(encoding='utf-8-sig')),design_profile_id=sys.argv[3],cell_z_mm=float(sys.argv[4])),allow_nan=False))
'@
  Push-Location $codeRoot
  try{
    $env:PYTHONPATH=$codeRoot
    $exitObservation=(& $python -B -c $exitPreparationCode $runDir $resolved $DesignProfileId ([string]$resolvedCellMmZ))|ConvertFrom-Json
    if($LASTEXITCODE-ne0){throw 'Multipole mechanical interface/clock preparation failed.'}
  }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
  $mechanicalExitEnabled=[bool]$exitObservation.mechanical_exit_enabled
  $drive=$design.drive;$geometry=$design.geometry_mm;$enclosure=$geometry.enclosure
  $static=$design.static_electrodes_V
  $axialTopology=[string]$design.axial_drive.topology
  $segmented=($axialTopology-eq'segmented_rod_axial_acceleration')
  $segmentedRodGeometry=($null-ne$design.segmentation.segmented_rod_array)
  $rectangular=([string]$enclosure.model-eq'rectangular_reference_enclosure_v1')
  if($rectangular){
    $interfaces=$design.interfaces_mm
    $handoffPlaneMm=[double]$interfaces.exit.handoff_plane_z_mm
    $censusPlaneMm=[double]$interfaces.exit.census_plane_z_mm
    $censusRadius=[double]$enclosure.physical_detector_radius_mm
    $origin=0;$zShift=0
    $workingRadius=[double]$enclosure.working_region_radius_mm
    $backwardEscape=[double]$enclosure.vacuum_z_min_mm
  }else{
    $domain=$geometry.numerical_domain;$observations=$geometry.observations
    $handoffPlaneMm=[double]$observations.handoff_plane_z_mm
    $censusPlaneMm=[double]$observations.census_plane_z_mm
    $censusRadius=[double]$observations.acceptance_radius_mm
    $origin=[double]$domain.radius_mm;$zShift=-[double]$domain.z_min_mm
    $workingRadius=[double]$domain.working_region_radius_mm
    $backwardEscape=[double]$domain.z_min_mm
  }
  $electrodesById=[ordered]@{}
  $rodSources=if($segmentedRodGeometry){@($design.segmentation.segmented_rod_array.electrodes)}else{
    @($geometry.rod_array.rods|ForEach-Object{
      [pscustomobject]@{electrode_id=[int]$_.electrode_group;electrode_group=[int]$_.electrode_group;
        common_mode_V=[double]$drive.common_mode_offset_V}
    })
  }
  foreach($electrode in $rodSources){
    $electrodeId=[int]$electrode.electrode_id
    $candidate=[pscustomobject]@{electrode_id=$electrodeId;
      electrode_group=[int]$electrode.electrode_group;common_mode_V=[double]$electrode.common_mode_V}
    if($electrodesById.Contains($electrodeId)){
      $existing=$electrodesById[[object]$electrodeId]
      if($existing.electrode_group-ne$candidate.electrode_group-or
        $existing.common_mode_V-ne$candidate.common_mode_V){
        throw "RF electrode $electrodeId has inconsistent group or common-mode voltage."
      }
    }else{$electrodesById.Add($electrodeId,$candidate)}
  }
  $entries=@($electrodesById.Values|Sort-Object electrode_id|ForEach-Object{
    "{electrode_id=$([int]$_.electrode_id),electrode_group=$([int]$_.electrode_group),common_mode_v=$([double]$_.common_mode_V)}"
  })
  $rodLua="rod_electrodes={$($entries-join',')},"
  $paBasisElectrodeIds=@($electrodesById.Keys|ForEach-Object{[int]$_})
  $groundElectrodeId=[int](($paBasisElectrodeIds|Measure-Object -Maximum).Maximum)+1
  $staticRows=@(if($rectangular){
    @([pscustomobject]@{electrode_id=$groundElectrodeId;potential_v=[double]$static.entrance_aperture_plate_and_connector_V},
      [pscustomobject]@{electrode_id=$groundElectrodeId+1;potential_v=[double]$static.exit_outer_enclosure_and_connector_V},
      [pscustomobject]@{electrode_id=$groundElectrodeId+2;potential_v=[double]$static.physical_detector_V})
  }elseif(@($geometry.enclosure_layout.bodies).Count-gt0){
    @([pscustomobject]@{electrode_id=$groundElectrodeId;potential_v=[double]$static.ground_V})
  })
  $staticEntries=@($staticRows|ForEach-Object{"{electrode_id=$($_.electrode_id),potential_v=$($_.potential_v)}"})
  $staticLua="static_electrodes={$($staticEntries-join',')},"
  $paBasisElectrodeIds+=@($staticRows|ForEach-Object{[int]$_.electrode_id})
  $normalizedGem=(Get-Content -LiteralPath $gem -Encoding ASCII|Where-Object{
    $_-notmatch'^; parent_resolved_sha256='
  })-join"`n"
  $paSurfaceMatches=[regex]::Matches($normalizedGem,'\bsurface=(fractional|none)\b')
  if($paSurfaceMatches.Count-ne 1){throw 'SIMION GEM must declare exactly one PA surface mode.'}
  $paSurface=[string]$paSurfaceMatches[0].Groups[1].Value
  $normalizedGemPath=Join-Path $inputDir 'quad_monolithic.normalized_for_pa_cache.gem'
  Set-Content -LiteralPath $normalizedGemPath -Value $normalizedGem -Encoding ASCII -NoNewline
  $normalizedGemSha=(Get-FileHash -LiteralPath $normalizedGemPath -Algorithm SHA256).Hash
  $paBasisIdentity=[ordered]@{
    geometry=[ordered]@{project_id=$ProjectId;resolved_design_sha256=$resolvedHash}
    gem=[ordered]@{normalized_sha256=$normalizedGemSha}
    basis_namespace=[ordered]@{name='multipole_quad_monolithic_pa_basis';project_id=$ProjectId}
    mesh=[ordered]@{cell_mm_xyz=@($resolvedCellMmX,$resolvedCellMmY,$resolvedCellMmZ);
      pa_grid_xyz=@($gridAuditDocument.nx,$gridAuditDocument.ny,$gridAuditDocument.nz)}
    grid_phase=[ordered]@{normalized_gem_sha256=$normalizedGemSha}
    surface=$paSurface
    simion_identity=[ordered]@{executable_sha256=(Get-FileHash -LiteralPath $simion -Algorithm SHA256).Hash}
    refine_policy=[ordered]@{arguments=@('--nogui','--noprompt','refine','quad_monolithic.pa#')}
    builder_identity=[ordered]@{runner_sha256=$entryScriptHash}
  }
  $paBasisIdentityPath=Join-Path $inputDir 'simion_pa_basis_cache_identity.json'
  $paBasisIdentity|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $paBasisIdentityPath -Encoding UTF8
  if($resolvedRuntimeDocument-and$resolvedRuntimeDocument.PSObject.Properties.Name-contains'simion_pa_basis_policy'){
    throw 'SIMION_PA_BASIS_POLICY_UNSUPPORTED: current fractional families cannot use the surface=none standalone cache protocol. Preserve the original surface; use an explicit -NativeFieldRunPath producer checkpoint instead. No cache require_existing policy is silently replaced.'
  }
  $provenance=[ordered]@{parent_resolved_design_sha256=$resolvedHash;particle_source_sha256=$sourceMeta.source_sha256;
    source_family_sha256=$sourceFamilySha;operating_point_id=$(if($sourceFamily){$OperatingPointId}else{$null});
    particle_source_operating_point_binding=$sourceMeta.operating_point_binding;
    simion_layout_template=[ordered]@{
      template_id=[string]$templateProfile.template_id
      provider_project_id=[string]$templateProfile.provider_project_id
      registration_run_id=[string]$templateProfile.registration_run_id
      registry_sha256=[string]$templateProfile.registry_sha256
      registration_manifest_sha256=[string]$templateProfile.run_manifest.sha256
      iob_sha256=[string]$templateProfile.bundle.iob.sha256
      con_sha256=[string]$templateProfile.bundle.con.sha256
    }
    simion_pa_basis=[ordered]@{
      representation='producer_owned_fractional_checkpoint'
      action=$(if($NativeFieldRunPath-or$continuationPredecessor){'explicit_field_reuse'}else{'independent_refine'})
    }}
  if($resolvedRuntimeProfile){
    $provenance.resolved_runtime_profile_sha256=(
      Get-FileHash -LiteralPath $resolvedRuntimeProfile -Algorithm SHA256
    ).Hash
  }
  if($campaignSelection){
    $provenance.runtime_selection_kind='campaign_experiment'
    $provenance.campaign_id=[string]$campaignSelection.campaign_id
    $provenance.experiment_id=[string]$campaignSelection.experiment_id
    $provenance.campaign_sha256=[string]$campaignSelection.sha256
    if($campaignSelection.PSObject.Properties.Name-contains'experiment_row_sha256'){
      $provenance.campaign_experiment_row_sha256=[string]$campaignSelection.experiment_row_sha256
    }
  }else{
    $provenance.runtime_selection_kind='runtime_profile'
  }
  if($phaseDerivationMetadata){
    $phaseMetadata=Get-Content -LiteralPath $phaseDerivationMetadata -Raw -Encoding UTF8|ConvertFrom-Json
    $provenance.particle_source_authority_sha256=[string]$phaseMetadata.baseline_source_sha256
    $provenance.particle_source_phase_derivation_sha256=(
      Get-FileHash -LiteralPath $phaseDerivationMetadata -Algorithm SHA256
    ).Hash
    $provenance.particle_source_phase_matched=$true
    if($null-ne$sourceEnergyOverride){
      $provenance.particle_source_target_kinetic_energy_eV=$sourceEnergyOverride
      $provenance.particle_source_direction_and_birth_time_preserved=$true
    }
  }
  # This frozen projection is the sole source for the case Lua's physical
  # values. Output paths remain per-run and do not define Fly identity.
  $flyPhysics=[ordered]@{schema_version=1;role='multipole_simion_fly_physics';
    trajectory_quality=$TrajectoryQuality;rf_steps_per_period=$RfStepsPerPeriod;
    waveform=[string]$drive.waveform;rf_peak_v=[double]$drive.rf_amplitude_V_zero_to_peak_per_group;
    dc_amplitude_v=[double]$drive.dc_amplitude_V_per_group;frequency_hz=[double]$drive.frequency_Hz;phase_rad=[double]$drive.phase_rad;
    rod_lua=$rodLua;static_lua=$staticLua;maximum_time_us=$MaximumTimeUs;trajectory_plane_step_mm=$resolvedCellMmZ;
    rod_z_min_mm=[double]$geometry.rod_z_min;rod_z_max_mm=[double]$geometry.rod_z_max;
    handoff_plane_mm=$handoffPlaneMm;census_plane_mm=$censusPlaneMm;census_radius_mm=$censusRadius;
    radial_escape_radius_mm=$workingRadius;origin_x_mm=$zShift;origin_y_mm=(-$origin);origin_z_mm=$origin;
    backward_escape_plane_mm=$backwardEscape;mechanical_exit_enabled=$mechanicalExitEnabled;
    axial_axis='x';
    gem2pa_args=@('--nogui','--noprompt','gem2pa','quad_monolithic.gem','quad_monolithic.pa#');
    refine_args=@('--nogui','--noprompt','refine','quad_monolithic.pa#');
    iob_args=@('--nogui','--noprompt','lua','build_simion_runtime_iob.lua','quad_monolithic.iob','multipole_runtime_program.lua','quad_monolithic.fly2');
    fly_args=@('--nogui','--noprompt','fly','--remove-pas=3','--trajectory-quality',[string]$TrajectoryQuality,'--programs','1','--retain-trajectories','0','--adjustable',"transport_rf_steps_per_period=$RfStepsPerPeriod");
    mechanical_exit_plane_mm=$(if($mechanicalExitEnabled){$exitObservation.mechanical_exit_z_mm}else{$null});
    mechanical_exit_guard_mm=$(if($mechanicalExitEnabled){$exitObservation.numerical_guard_z_mm}else{$null});
    mechanical_exit_aperture_radius_lua=$(if($mechanicalExitEnabled-and$null-ne$exitObservation.aperture_radius_mm){[Convert]::ToString([double]$exitObservation.aperture_radius_mm,[Globalization.CultureInfo]::InvariantCulture)}else{'nil'});
    cases=[ordered]@{rf_on=[ordered]@{rf=1;axial=0};zero_rf_control=[ordered]@{rf=0;axial=0};
      axial_acceleration_rf_on=[ordered]@{rf=1;axial=1};zero_axial_drop_rf_on=[ordered]@{rf=1;axial=0};axial_acceleration_rf_off=[ordered]@{rf=0;axial=1}}}
  $flyPhysicsPath=Join-Path $inputDir 'simion_fly_physics.json'
  Write-RunJson -Path $flyPhysicsPath -Value $flyPhysics -Depth 12
  $runInputs=[ordered]@{project_registry=$registry;project_descriptor=$descriptor;design_profiles=$profiles;
    execution_request=$workflowRequestPath;
    engineering_budget=$engineeringBudget;
    design_profile_resolution=$profileResolution;design_request=$request;design_variables=$variables;
    optimization_envelope=$envelope;operating_mode_registry=$modeRegistry;
    multipole_resolved_design=$resolved;particle_source=$particleSource;
    particle_source_metadata=$sourceMetadata;particle_source_family=$sourceFamily;
    particle_source_release_spec=$releaseSpec;particle_source_release_receipt=$releaseReceipt;
    solver_numerics=$numerics;simion_grid_audit=$gridAudit;code_inventory=$codeInventory;
    simion_pa_basis_identity=$paBasisIdentityPath;
    simion_fly_physics=$flyPhysicsPath;
    simion_execution_batch_plan=$batchPlan;
    evidence_contract=$evidence;simion_gem=$gem;simion_fly2=$fly2;simion_source_states=$states;
    simion_rf_drive_kernel=$rfDriveKernelLua;
    clock_authority=(Join-Path $inputDir 'clock_authority.json');instrument_epoch=(Join-Path $inputDir 'instrument_epoch.json');
    resolved_runtime_profile=$resolvedRuntimeProfile;
    simion_layout_template_resolution=$templateResolution;
    simion_layout_template_registry=$templateRegistryInput;
    simion_layout_registration_manifest=$templateRegistrationManifest;
    simion_layout_template_iob=$templateIob;simion_layout_template_con=$templateCon;
    simion_layout_template_placeholder_pa0=$templateSeedPa}
  if($mechanicalExitEnabled){
    $runInputs.mechanical_exit_interface=Join-Path $inputDir 'mechanical_exit_interface.json'
    $runInputs.mechanical_exit_observation=Join-Path $inputDir 'mechanical_exit_observation.json'
  }
  if($dispatchPlan){$runInputs.simion_repository_dispatch_plan=$dispatchPlan}
  if($candidateRequest){$runInputs.candidate_design_request=$candidateRequest}
  if($phaseDerivationMetadata){
    $runInputs.particle_source_authority=$phaseAuthoritySource
    $runInputs.particle_source_n1000_reference=$phaseReferenceSource
    $runInputs.particle_source_phase_derivation=$phaseDerivationMetadata
  }
  if($referenceComsolManifest){
    $provenance.reference_comsol_run_manifest_sha256=$referenceComsolManifestSha
    $provenance.reference_comsol_source_run_id=$referenceComsolSourceRunId
    $runInputs.reference_comsol_run_manifest=$referenceComsolManifest
  }
  foreach($key in @($runInputs.Keys)){
    $value=$runInputs[$key]
    if($value-is[string]-and$value.StartsWith($runDir.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)){
      $runInputs[$key]=Join-Path $physicalRunDir ([IO.Path]::GetRelativePath($runDir,$value))
    }
  }
  $initialLifecycle=(Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8|ConvertFrom-Json).capacity_ledger_lifecycle
  [ordered]@{schema_version=2;role='multipole_resolved_simion_run_config';run_id=$RunId;project=$ProjectId;
    mode='resolved_design_transport';project_root=$profile.project_root;
    artifact_retention=[ordered]@{policy_version=1;class=$RetentionClass;
      reason=$(if($RetentionClass-eq'compact'){$null}else{$RetentionReason})};
    capacity_ledger_lifecycle=$initialLifecycle;provenance=$provenance;inputs=$runInputs;
    parameters=[ordered]@{model_level='L3';runtime_profile_id=$RuntimeProfileId;design_profile_id=$DesignProfileId;
      experiment_id=$(if($campaignSelection){[string]$campaignSelection.experiment_id}else{$null});
      case_set=$CaseSet;
      operating_mode_id=$modeId;
      operating_point_id=$(if($sourceFamily){$OperatingPointId}else{$null});
      reference_comsol_run_id=$ReferenceComsolRunId};
    formal_gate_passed=$false}|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $runConfig -Encoding UTF8

  $continuationUnits=@{};$continuationAllReuse=$false;$continuationLargestMissing=0
  if($continuationPredecessor){
    $continuationCases=if($segmented){
      @('axial_acceleration_rf_on')+$(if($CaseSet-eq'primary_and_zero_axial_control'){@('zero_axial_drop_rf_on')}elseif($CaseSet-eq'primary_and_rf_off_energy_control'){@('axial_acceleration_rf_off')}else{@()})
    }else{@('rf_on')+$(if($CaseSet-ne'primary_only'){@('zero_rf_control')}else{@()})}
    $planArguments=@('-m','projects.rf_multipole_ion_optics.runtime.simion_batch_continuation',
      '--predecessor',$continuationPredecessor,'--project',$ProjectId,'--run-dir',$runDir,'--retention',$RetentionClass)
    foreach($case in $continuationCases){$planArguments+=@('--case',$case)}
    if($mechanicalExitEnabled){$planArguments+='--mechanical'}
    Push-Location $codeRoot
    try{
      $env:PYTHONPATH=$codeRoot
      $planned=& $python @planArguments
      if($LASTEXITCODE-ne0){throw 'RF continuation planning failed.'}
      $continuation=($planned-join"`n")|ConvertFrom-Json
      Write-RunJson -Path $batchPlan -Value $continuation.batch_plan -Depth 12
      Set-SimionBatchesFromPlan -Plan $continuation.batch_plan
    }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
    foreach($unit in $continuation.replay.units){if($unit.action-eq'reuse'){$continuationUnits[[string]$unit.key]=$unit}}
    foreach($unit in $continuation.replay.units|Where-Object{$_.action-eq'replay'}){
      if([string]$unit.key-notmatch'\.batch_(\d+)$'){throw 'RF continuation unit key is invalid.'}
      $index=[int]$Matches[1]
      $plannedBatch=@($simionBatches|Where-Object{[int]$_.index-eq$index})
      if($plannedBatch.Count-ne1){throw 'RF continuation unit is outside the frozen partition.'}
      $count=[int]$plannedBatch[0].particle_id_max-[int]$plannedBatch[0].particle_id_min+1
      $continuationLargestMissing=[Math]::Max($continuationLargestMissing,$count)
    }
    $continuationAllReuse=([int]$continuation.replay.replay_unit_count-eq0)
    if($continuationAllReuse){$resourceIdentityWasUnknown=$false}
    # Preserve the original partition. An unknown resource identity still
    # observes the first missing formal batch before dispatching the rest.
    $configDocument=Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    $configDocument.inputs.continuation_predecessor_manifest=$ContinuationPredecessorManifestPath
    $configDocument.inputs.continuation_plan=Join-Path $physicalRunDir 'inputs/simion_whole_unit_replay_plan.json'
    $configDocument.parameters.continuation_predecessor=$continuationPredecessor
    Write-RunJson -Path $runConfig -Value $configDocument -Depth 12
  }

  $resourceUsage=Join-Path $resultDir 'resource_usage.json'
  function Invoke-SimionStep([string]$name,[string[]]$arguments,[hashtable]$Environment=@{}){
    $stdout=Join-Path $logDir "simion_stdout__$name.txt";$stderr=Join-Path $logDir "simion_stderr__$name.txt"
    try{
      $step=Invoke-ResourceBudgetedProcess -Limits $resolvedBudgetPreflight.limits `
        -RunDir $runDir -UsagePath $resourceUsage -FilePath $simion -WorkingDirectory $solverDir `
        -ArgumentList $arguments -RedirectStandardOutput $stdout -RedirectStandardError $stderr -Environment $Environment
    }catch{
      # The direct process helper only confirms its root after an observation
      # error; it cannot attest that every descendant has stopped.
      if($_.Exception.Data.Contains('observed_process_exit_confirmed')){
        $_.Exception.Data['simion_wave_writer_completion_confirmed']=$false
      }
      throw
    }
    if($step.resource_budget_exceeded){
      $failure=[InvalidOperationException]::new("SIMION $name resource budget exceeded; descendant completion is unconfirmed.")
      $failure.Data['simion_wave_writer_completion_confirmed']=$false
      $script:resourceBudgetExceeded=$true
      throw $failure
    }
    [void]$nativeOperations.Add([ordered]@{operation_id=$name;observation=@{exit_confirmed=$true;returncode=[int]$step.exit_code;
      process_id=[int]$step.root_process_id;process_started_at_utc_ticks=[long]$step.root_process_started_at_utc_ticks};resource_release_id='simion'})
    if($step.exit_code-ne 0){throw "SIMION $name failed with exit code $($step.exit_code)."}
  }
  Set-RfRunPhase 'field_and_layout'
  if(-not$continuationAllReuse){
  $fieldIdentityPath=Join-Path $physicalRunDir 'inputs/simion_field_identity.json'
  $fieldIdentity=New-RfSimionFieldIdentity -GemPath $gem -SimionExe $simion `
    -Grid @($gridAuditDocument.nx,$gridAuditDocument.ny,$gridAuditDocument.nz) `
    -CellMm @($resolvedCellMmX,$resolvedCellMmY,$resolvedCellMmZ) -ResponseIds @($paBasisElectrodeIds|Sort-Object -Unique) `
    -Gem2PaArguments @($flyPhysics.gem2pa_args) -RefineArguments @($flyPhysics.refine_args)
  Write-RunJson -Path $fieldIdentityPath -Value $fieldIdentity -Depth 12
  $fieldConfig=Get-Content -LiteralPath $runConfig -Raw|ConvertFrom-Json -AsHashtable
  $fieldConfig.inputs.simion_field_identity=$fieldIdentityPath
  Write-RunJson -Path $runConfig -Value $fieldConfig -Depth 20
  $fieldSource=if($NativeFieldRunPath){$NativeFieldRunPath}else{$continuationPredecessor}
  $fieldPlan=$null
  if($fieldSource){
    $fieldPlan=Read-RfSimionFieldCheckpoint -SourceRunPath $fieldSource -IdentityPath $fieldIdentityPath `
      -ProgramSourcePath (Join-Path $solverDir 'multipole_runtime_program.lua') -Python $python -RepoRoot $codeRoot `
      -TemplateIobPath $templateIob -TemplateConPath $templateCon
    $continuationCapacity=(Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
      -Session $continuationCapacity -ProtectedPaths @($fieldPlan.protected_paths)).session
    $workflowRequest.capacity.protected_paths=@((@($continuationChain)+@($fieldPlan.protected_paths))|Select-Object -Unique)
    Write-RunJson -Atomic -Path $workflowRequestPath -Value $workflowRequest -Depth 64
    $fieldCheckpointGuard=Protect-RfSimionFieldCheckpoint -Checkpoint $fieldPlan -ExistingProtectedRuns $continuationChain
    $fieldConfig.inputs.simion_field_checkpoint=[string]$fieldPlan.checkpoint_path
    $fieldConfig.inputs.simion_field_producer_manifest=[string]$fieldPlan.producer_manifest
    Write-RunJson -Path $runConfig -Value $fieldConfig -Depth 20
    $flightIobPath=[string]$fieldPlan.iob_path
    Write-Output "MULTIPOLE_SIMION_FIELD=REUSE PRODUCER=$($fieldPlan.producer_manifest) REFINE=0"
  }else{
    Invoke-SimionStep 'gem2pa' @($flyPhysics.gem2pa_args)
    $hostExecutionLease=Update-HostResourceStage -Lease $hostExecutionLease -Stage pa_refine `
      -Budget (Get-HostResourceBudget -Role SIMION -Stage pa_refine) -RetainedMemoryBytes 0
    try {
      Invoke-SimionStep 'refine' @($flyPhysics.refine_args)
    } finally {
      # The metered process has exited before releasing the refine permission.
      # The facade refuses downgrade if any owned solver descendants remain.
      $hostExecutionLease=Update-HostResourceStage -Lease $hostExecutionLease -Stage prepare `
        -Budget (Get-HostResourceBudget -Role SIMION -Stage prepare) -RetainedMemoryBytes 0
    }
    if($RetentionClass-ne'compact'){
      $checkpoint=Write-RfSimionFieldCheckpoint -RunDirectory $physicalRunDir -IdentityPath $fieldIdentityPath `
        -IobPath (Join-Path $physicalRunDir 'simion/quad_monolithic.iob') -NativeOperations $nativeOperations -Python $python -RepoRoot $codeRoot
      $fieldCheckpointOutputs+=@($checkpoint.output_paths)
    }
  }
  if($null-eq$fieldPlan-or$fieldPlan.requires_iob_rebind){
  Copy-Item -LiteralPath $templateIob -Destination (Join-Path $solverDir 'quad_monolithic.iob')
  Copy-Item -LiteralPath $templateCon -Destination (Join-Path $solverDir 'quad_monolithic.con')
  Copy-VerifiedRunInput `
    -Source (Join-Path $codeRoot 'projects\rf_multipole_ion_optics\simion\build_simion_runtime_iob.lua') `
    -Destination (Join-Path $solverDir 'build_simion_runtime_iob.lua')|Out-Null
  $controller=if($null-ne$fieldPlan){[string]$fieldPlan.controller_path}else{Join-Path $physicalRunDir 'simion/quad_monolithic.pa0'}
  $flightIobPath=Join-Path $physicalRunDir 'simion/quad_monolithic.iob'
  $iobBuildArguments=@($flyPhysics.iob_args)
  # wb.save resolves PA references relative to its destination. Use the
  # permanent destination, never the short execution alias as its base.
  $iobBuildArguments[4]=$flightIobPath
  $layoutSeed=$null
  if($null-ne$fieldPlan){
    $layoutSeed=New-RfSimionLayoutSeedCompanion -IobPath $flightIobPath -SeedPaPath $templateSeedPa
  }
  Invoke-SimionStep 'build_runtime_iob' ($iobBuildArguments+@($controller))
  if($null-ne$layoutSeed){
    $buildFact=@($nativeOperations|Where-Object{$_.operation_id-eq'build_runtime_iob'})[-1]
    Remove-RfSimionLayoutSeedCompanion -Companion $layoutSeed -BuildObservation $buildFact.observation
  }
  $layoutInspectionRequired=$true
  Start-Sleep -Milliseconds 500
  }
  }
  Set-RfRunPhase 'flight_and_case_analysis'

  # Each stopped worker writes a small completion receipt. The existing owner
  # binds those receipts and their retained outputs in one terminal manifest.
  $checkpointOutputs=[Collections.ArrayList]::new()
  $batchCompletionReceipts=[Collections.ArrayList]::new()
  $retainedTrajectoryOutputs=[Collections.ArrayList]::new()
  $caseRunsNative=@{}

  function Invoke-TransportCase([string]$name,[int]$rfScale,[int]$axialScale){
    $caseState=Join-Path $resultDir "particle_states__$name.csv"
    $caseTrajectory=Join-Path $resultDir "trajectory_samples__$name.csv"
    $caseMechanical=Join-Path $resultDir "mechanical_exit_states__$name.csv"
    $caseSummary=Join-Path $resultDir "simion_summary__$name.json"
    # The registered Workbench transform maps GEM +z to flight +x.  Axial
    # sampling and the census-marker threshold must therefore use GEM dz.
    $casePhysics=$flyPhysics.cases[$name]
    if($null-eq$casePhysics-or[int]$casePhysics.rf-ne$rfScale-or[int]$casePhysics.axial-ne$axialScale){
      throw "SIMION $name case differs from frozen Fly physics."
    }
    function New-TransportBatchRuns {
    $runs=@()
    foreach($batch in $simionBatches){
      $suffix=("batch_{0:D2}" -f [int]$batch.index)
      $batchState=if($simionBatches.Count-eq 1){$caseState}else{Join-Path $resultDir "particle_states__$name`__$suffix.csv"}
      $batchMechanical=if($simionBatches.Count-eq 1){$caseMechanical}else{Join-Path $resultDir "mechanical_exit_states__$name`__$suffix.csv"}
      $mechanicalLua=if($flyPhysics.mechanical_exit_enabled){"mechanical_exit_csv=[[$batchMechanical]],mechanical_exit_plane_mm=$($flyPhysics.mechanical_exit_plane_mm),mechanical_exit_aperture_radius_mm=$($flyPhysics.mechanical_exit_aperture_radius_lua),mechanical_exit_guard_mm=$($flyPhysics.mechanical_exit_guard_mm),"}else{''}
      $batchTrajectory=if($simionBatches.Count-eq 1){$caseTrajectory}else{Join-Path $resultDir "trajectory_samples__$name`__$suffix.csv"}
      $batchSummary=if($simionBatches.Count-eq 1){$caseSummary}else{Join-Path $resultDir "simion_summary__$name`__$suffix.json"}
      $unitKey="{0}.batch_{1:D2}"-f$name,[int]$batch.index
      if($continuationUnits.ContainsKey($unitKey)){
        $artifacts=@($continuationUnits[$unitKey].terminal_outputs|ForEach-Object{[string]$_.path})
        $stateMatch=@($artifacts|Where-Object{[IO.Path]::GetFileName($_)-ceq[IO.Path]::GetFileName($batchState)})
        $summaryMatch=@($artifacts|Where-Object{[IO.Path]::GetFileName($_)-ceq[IO.Path]::GetFileName($batchSummary)})
        if($stateMatch.Count-ne1-or$summaryMatch.Count-ne1){throw "RF reused batch $unitKey lacks state or summary."}
        $batchState=$stateMatch[0];$batchSummary=$summaryMatch[0]
        if($mechanicalExitEnabled){
          $matches=@($artifacts|Where-Object{[IO.Path]::GetFileName($_)-ceq[IO.Path]::GetFileName($batchMechanical)})
          if($matches.Count-ne1){throw "RF reused batch $unitKey lacks mechanical exit."};$batchMechanical=$matches[0]
        }
        if($RetentionClass-ne'compact'){
          $matches=@($artifacts|Where-Object{[IO.Path]::GetFileName($_)-ceq[IO.Path]::GetFileName($batchTrajectory)})
          if($matches.Count-ne1){throw "RF reused batch $unitKey lacks trajectory."};$batchTrajectory=$matches[0]
        }
      }
      $luaConfig=if($simionBatches.Count-eq 1){Join-Path $inputDir "simion_config__$name.lua"}else{Join-Path $inputDir "simion_config__$name`__$suffix.lua"}
      @"
return {iob=[[$flightIobPath]], fly2=[[$($batch.fly2)]], source_states=dofile([[$($batch.states)]]),
trajectory_csv=[[$batchTrajectory]], particle_state_csv=[[$batchState]], summary_json=[[$batchSummary]],
$mechanicalLua
mode="resolved_design_transport", operating_point="$name", parent_resolved_design_sha256="$resolvedHash",
trajectory_quality=$($flyPhysics.trajectory_quality), rf_steps_per_period=$($flyPhysics.rf_steps_per_period), waveform="$($flyPhysics.waveform)",
rf_peak_v=$($flyPhysics.rf_peak_v), rf_scale=$($casePhysics.rf), axial_scale=$($casePhysics.axial),
dc_amplitude_v=$($flyPhysics.dc_amplitude_v), frequency_hz=$($flyPhysics.frequency_hz), phase_rad=$($flyPhysics.phase_rad),
$($flyPhysics.rod_lua) $($flyPhysics.static_lua)
maximum_time_us=$($flyPhysics.maximum_time_us), trajectory_plane_step_mm=$($flyPhysics.trajectory_plane_step_mm),
rod_z_min_mm=$($flyPhysics.rod_z_min_mm), rod_z_max_mm=$($flyPhysics.rod_z_max_mm),
rod_exit_plane_mm=$($flyPhysics.rod_z_max_mm), handoff_plane_mm=$($flyPhysics.handoff_plane_mm),
    census_plane_mm=$($flyPhysics.census_plane_mm),
census_radius_mm=$($flyPhysics.census_radius_mm), radial_escape_radius_mm=$($flyPhysics.radial_escape_radius_mm),
axial_axis="$($flyPhysics.axial_axis)", origin_x_mm=$($flyPhysics.origin_x_mm), origin_y_mm=$($flyPhysics.origin_y_mm),
origin_z_mm=$($flyPhysics.origin_z_mm), backward_escape_plane_mm=$($flyPhysics.backward_escape_plane_mm)}
"@|Set-Content -LiteralPath $luaConfig -Encoding ASCII
      $runs+=[pscustomobject]@{batch=$batch;state=$batchState;trajectory=$batchTrajectory;
        summary=$batchSummary;mechanical=$batchMechanical;lua_config=$luaConfig;fly2=[string]$batch.fly2}
    }
    return $runs
    }
    $batchRuns=@(New-TransportBatchRuns)
    if($script:layoutInspectionRequired){
      # Inspect with the actual first case configuration: loading the real
      # Program requires its complete source, drive and coordinate contract.
      $inspectionConfig=Join-Path $inputDir 'simion_iob_inspection.lua'
      @"
local config=dofile([[$($batchRuns[0].lua_config)]])
config.expected_pa_nx=$($gridAuditDocument.nx);config.expected_pa_ny=$($gridAuditDocument.ny);config.expected_pa_nz=$($gridAuditDocument.nz)
config.expected_pa_cell_mm_x=$resolvedCellMmX;config.expected_pa_cell_mm_y=$resolvedCellMmY;config.expected_pa_cell_mm_z=$resolvedCellMmZ
return config
"@|Set-Content -LiteralPath $inspectionConfig -Encoding ASCII
      $inspector=Join-Path $codeRoot 'projects/rf_multipole_ion_optics/simion/workbench/inspect_builtin_quad_reference.lua'
      Invoke-SimionStep 'inspect_runtime_iob' @('--nogui','--noprompt','lua',$inspector) @{
        MULTIPOLE_SIMION_RUN_CONFIG_LUA=$inspectionConfig;MULTIPOLE_SIMION_RF_DRIVE_KERNEL_LUA=$rfDriveKernelLua;
        RFQUAD_SIMION_REFERENCE_IOB=$flightIobPath;RFQUAD_SIMION_REFERENCE_REPORT=(Join-Path $resultDir 'simion_iob_inspection.txt')}
      if($null-eq$fieldPlan-and$RetentionClass-ne'compact'){
        $checkpoint=Write-RfSimionFieldCheckpoint -RunDirectory $physicalRunDir -IdentityPath $fieldIdentityPath `
          -IobPath $flightIobPath -NativeOperations $nativeOperations -Python $python -RepoRoot $codeRoot
        $script:fieldCheckpointOutputs+=@($checkpoint.output_paths)
      }
      $script:layoutInspectionRequired=$false
    }
    $caseRunsNative[$name]=(@($batchRuns|Where-Object{-not$continuationUnits.ContainsKey(("{0}.batch_{1:D2}"-f$name,[int]$_.batch.index))}).Count-gt0)
    $batchState=[pscustomobject]@{runs=$batchRuns}
    $firstSpecification=$null;$replanAction=$null
    $flyArguments=@($flyPhysics.fly_args)+@($flightIobPath)
    $pendingRuns=@($batchRuns|Where-Object{-not$continuationUnits.ContainsKey(("{0}.batch_{1:D2}"-f$name,[int]$_.batch.index))})
    if($script:resourceCalibrationRequired-and$pendingRuns.Count-gt0){
      if(-not$continuationPredecessor-and$batchRuns.Count-ne 1){throw 'Unknown resource identity must start from one formal SIMION batch.'}
      $firstRun=@($pendingRuns|Sort-Object -Descending -Property @{Expression={[int]$_.batch.particle_id_max-[int]$_.batch.particle_id_min+1}})[0]
      $firstSpecification=[pscustomobject]@{
        name="fly__$name`__batch_$($firstRun.batch.index)";file_path=$simion
        argument_list=($flyArguments[0..5]+@('--particles',$firstRun.fly2)+$flyArguments[6..($flyArguments.Count-1)])
        working_directory=$solverDir
        stdout=(Join-Path $logDir "simion_stdout__fly__$name`__batch_$($firstRun.batch.index).txt")
        stderr=(Join-Path $logDir "simion_stderr__fly__$name`__batch_$($firstRun.batch.index).txt")
        environment=@{MULTIPOLE_SIMION_RUN_CONFIG_LUA=$firstRun.lua_config;MULTIPOLE_SIMION_RF_DRIVE_KERNEL_LUA=$rfDriveKernelLua}
        scheduler_batch=[pscustomobject]@{index=[int]$firstRun.batch.index;total_batches='OBSERVATION_ONLY';particle_id_min=[int]$firstRun.batch.particle_id_min;particle_id_max=[int]$firstRun.batch.particle_id_max;count=([int]$firstRun.batch.particle_id_max-[int]$firstRun.batch.particle_id_min+1)}
      }
      $replan={
      param($formalObservation)
      if([int64]$formalObservation.observed_peak_process_tree_working_set_bytes-lt1){
        throw "SIMION $name first formal batch did not produce a usable resource observation."
      }
      Push-Location $codeRoot
      try{
        $env:PYTHONPATH=$codeRoot
        $replanArguments=@('-m','common.simion.resource_scheduler','--request',$dispatchRequest,
          '--profiles',$resourceProfiles,'--output',$dispatchPlan,
          '--available-memory-bytes',([string]$formalObservation.available_memory_bytes),
          '--total-physical-memory-bytes',([string]$formalObservation.total_physical_memory_bytes),
          '--observed-formal-peak-bytes',([string]$formalObservation.observed_peak_process_tree_working_set_bytes),
          '--observed-formal-cpu-percent',([string]$formalObservation.observed_process_cpu_percent),
          '--observed-background-cpu-percent',([string]$formalObservation.observed_background_cpu_percent))
        if($formalObservation.completed_naturally){$replanArguments+='--first-batch-completed'}
        & $python @replanArguments
        if($LASTEXITCODE-ne 0){throw 'SIMION formal-first dispatch replanning failed.'}
        $updatedDispatch=Get-Content -LiteralPath $dispatchPlan -Raw -Encoding UTF8|ConvertFrom-Json
        if([string]$updatedDispatch.estimation.kind-ne'observed_formal_batch'-or
          @($updatedDispatch.waves).Count-ne1-or[int]$updatedDispatch.waves[0].batch_count-lt1){
          throw 'SIMION formal-first dispatch plan is invalid.'
        }
        if($continuationPredecessor-and
          ([int]$firstRun.batch.particle_id_max-[int]$firstRun.batch.particle_id_min+1)-lt$continuationLargestMissing){
          # A later case contains a larger missing unit than this observation.
          # Keep admission conservative until that unit has completed.
          $updatedDispatch.limits.maximum_concurrency=1
          Write-RunJson -Path $dispatchPlan -Value $updatedDispatch -Depth 20
        }
        if(-not$continuationPredecessor){
          & $python -m common.simion.particle_batching --from-dispatch-plan $dispatchPlan `
            --output $batchPlan | Out-Null
          if($LASTEXITCODE-ne 0){throw 'SIMION formal-first particle batch planning failed.'}
          $updatedBatchPlan=Get-Content -LiteralPath $batchPlan -Raw -Encoding UTF8|ConvertFrom-Json
          Set-SimionBatchesFromPlan -Plan $updatedBatchPlan
          $script:batchPlanDocument=$updatedBatchPlan
        }
        $script:dispatchPlanDocument=$updatedDispatch
        $script:executionBatching=[pscustomobject]@{dispatch='single_wave_parallel';
          batch_count=$(if($continuationPredecessor){[int]$batchRuns.Count}else{[int]$updatedDispatch.waves[0].batch_count})}
        $script:resourceCalibrationRequired=$false
        if($continuationPredecessor){$script:resourceIdentityWasUnknown=$false}
        $formalObservation.process_record.specification.scheduler_batch=[pscustomobject]@{index=[int]$firstRun.batch.index;total_batches=[int]$batchRuns.Count;particle_id_min=[int]$firstRun.batch.particle_id_min;particle_id_max=[int]$firstRun.batch.particle_id_max;count=([int]$firstRun.batch.particle_id_max-[int]$firstRun.batch.particle_id_min+1)}
        # The first formal worker began before the replan, when the run had a
        # single unsuffixed output name.  Keep that completed-or-live output
        # identity so the replanned multi-batch phase can publish it as
        # canonical batch_01 before merging.  The first worker is formal work,
        # not a disposable resource probe.
        if(-not$continuationPredecessor){$script:retainedFormalBatchOutputs[$name]=[pscustomobject]@{
          state=$firstRun.state;trajectory=$firstRun.trajectory
          summary=$firstRun.summary;mechanical=$firstRun.mechanical
        }}
      }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
      }
      $replanAction=$replan
    }
    # Keep each case's receipt independent: a control has no primary first worker.
    # The canonical path remains the primary observation consumed by the publisher.
    $resourceUsage=if($name-eq$primaryName){Join-Path $resultDir 'resource_usage.json'}else{
      Join-Path $resultDir "resource_usage__$name.json"
    }
    if($null-ne$firstSpecification){$script:resourceObservationUsage=$resourceUsage}
    if($null-eq$dispatchPlan-and$batchRuns.Count-eq 1-and$null-eq$firstSpecification){
      $env:MULTIPOLE_SIMION_RUN_CONFIG_LUA=$batchRuns[0].lua_config
      $env:MULTIPOLE_SIMION_RF_DRIVE_KERNEL_LUA=$rfDriveKernelLua
      try{Invoke-SimionStep "fly__$name" ($flyArguments[0..5]+@('--particles',$batchRuns[0].fly2)+$flyArguments[6..($flyArguments.Count-1)])}
      finally{Remove-Item Env:MULTIPOLE_SIMION_RUN_CONFIG_LUA -ErrorAction SilentlyContinue;Remove-Item Env:MULTIPOLE_SIMION_RF_DRIVE_KERNEL_LUA -ErrorAction SilentlyContinue}
    }else{
      $prepareRemaining={
      param($formal)
      if($null-ne$formal-and-not$continuationPredecessor){$batchState.runs=@(New-TransportBatchRuns)}
      $specifications=@($batchState.runs|Where-Object{-not$continuationUnits.ContainsKey(("{0}.batch_{1:D2}"-f$name,[int]$_.batch.index))}|ForEach-Object{
        [pscustomobject]@{name="fly__$name`__batch_$($_.batch.index)";file_path=$simion;
          argument_list=($flyArguments[0..5]+@('--particles',$_.fly2)+$flyArguments[6..($flyArguments.Count-1)]);
          working_directory=$solverDir;stdout=(Join-Path $logDir "simion_stdout__fly__$name`__batch_$($_.batch.index).txt");
          stderr=(Join-Path $logDir "simion_stderr__fly__$name`__batch_$($_.batch.index).txt");
          environment=@{MULTIPOLE_SIMION_RUN_CONFIG_LUA=$_.lua_config;MULTIPOLE_SIMION_RF_DRIVE_KERNEL_LUA=$rfDriveKernelLua}
          scheduler_batch=[pscustomobject]@{index=[int]$_.batch.index;total_batches=[int]$batchState.runs.Count;particle_id_min=[int]$_.batch.particle_id_min;particle_id_max=[int]$_.batch.particle_id_max;count=([int]$_.batch.particle_id_max-[int]$_.batch.particle_id_min+1)}}
      })
      if($null-ne$formal){
        $specifications=@($specifications|Where-Object{[int]$_.scheduler_batch.index-ne[int]$formal.process_record.specification.scheduler_batch.index})
      }
      [pscustomobject]@{pending=$specifications;batch_runs=$batchState.runs}
      }
      $checkpointAction={
        param($completedRecord)
          $index=[int]$completedRecord.specification.scheduler_batch.index
          if($null-eq$completedRecord.exit_code){throw "SIMION $name batch $index exit is unconfirmed."}
          [void]$nativeOperations.Add([ordered]@{operation_id="fly__$name`__batch_$index";observation=@{exit_confirmed=$true;returncode=[int]$completedRecord.exit_code;
            process_id=[int]$completedRecord.root_process_id;process_started_at_utc_ticks=[long]$completedRecord.root_process_started_at_utc_ticks};resource_release_id='simion'})
          if([int]$completedRecord.exit_code-ne0){return}
          $matches=@($batchState.runs|Where-Object{[int]$_.batch.index-eq$index})
          if($matches.Count-ne1){throw "SIMION $name completed batch index is ambiguous: $index"}
          $completedBatch=$matches[0]
          # The formally observed first batch initially used unqualified case
          # paths. Replanning changes only filenames, not the first interval.
          if($index-eq1-and$script:retainedFormalBatchOutputs.ContainsKey($name)){
            $retained=$script:retainedFormalBatchOutputs[$name]
            foreach($kind in @('state','summary')+$(if($mechanicalExitEnabled){@('mechanical')}else{@()})+$(if($RetentionClass-ne'compact'){@('trajectory')}else{@()})){
              if([string]$retained.$kind-cne[string]$completedBatch.$kind){
                Copy-Item -LiteralPath ([string]$retained.$kind) -Destination ([string]$completedBatch.$kind)
              }
            }
          }
          $check=@('-m','projects.rf_multipole_ion_optics.runtime.simion_batch_completion',
            '--stdout',[string]$completedRecord.specification.stdout,'--state',[string]$completedBatch.state,
            '--summary',[string]$completedBatch.summary,'--particle-count',[string]$completedRecord.specification.scheduler_batch.count)
          if($mechanicalExitEnabled){$check+=@('--mechanical',[string]$completedBatch.mechanical)}
          if($RetentionClass-ne'compact'-and-not(Test-Path -LiteralPath $completedBatch.trajectory -PathType Leaf)){
            throw "SIMION $name batch $index lacks the retained trajectory required by $RetentionClass."
          }
          Push-Location $codeRoot
          try{$env:PYTHONPATH=$codeRoot;& $python @check | Out-Null;if($LASTEXITCODE-ne0){throw "SIMION $name batch $index completion is invalid."}}
          finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
          if($RetentionClass-ne'compact'-and-not$retainedTrajectoryOutputs.Contains([string]$completedBatch.trajectory)){
            [void]$retainedTrajectoryOutputs.Add([string]$completedBatch.trajectory)
          }
          foreach($path in @([string]$completedRecord.specification.stdout,[string]$completedBatch.state,[string]$completedBatch.summary)+$(if($mechanicalExitEnabled){@([string]$completedBatch.mechanical)}else{@()})){
            if(-not$checkpointOutputs.Contains($path)){[void]$checkpointOutputs.Add($path)}
          }
          $receipt=Join-Path $resultDir ("simion_batch_completion__{0}__batch_{1:D2}.json"-f$name,$index)
          $receiptOutputs=@(@([string]$completedRecord.specification.stdout,[string]$completedBatch.state,[string]$completedBatch.summary)+$(if($mechanicalExitEnabled){@([string]$completedBatch.mechanical)}else{@()})+$(if($RetentionClass-ne'compact'){@([string]$completedBatch.trajectory)}else{@()})|ForEach-Object{
            $relative=[IO.Path]::GetRelativePath($runDir,$_).Replace('\','/')
            if($relative-eq'..'-or$relative.StartsWith('../')-or[IO.Path]::IsPathRooted($relative)){
              throw 'SIMION completed batch output escapes its owner run.'
            }
            $relative
          })
          Write-RunJson -Atomic -Path $receipt -Value ([ordered]@{
            schema_version=1;role='multipole_simion_completed_batch';case=$name;batch_index=$index
            particle_id_min=[int]$completedBatch.batch.particle_id_min
            particle_id_max=[int]$completedBatch.batch.particle_id_max
            particle_count=[int]$completedRecord.specification.scheduler_batch.count
            retention_class=$RetentionClass;outputs=$receiptOutputs
          })
          if(-not$batchCompletionReceipts.Contains($receipt)){[void]$batchCompletionReceipts.Add($receipt)}
      }
      $wave=Invoke-SimionBatchPhase -DispatchPlanPath $dispatchPlan `
        -RunDir $runDir -UsagePath $resourceUsage -PrepareRemaining $prepareRemaining `
        -FirstSpecification $firstSpecification -Replan $replanAction -OnProcessCompleted $checkpointAction
      $batchRuns=@($wave.prepared.batch_runs)
      $failed=@($wave.processes|Where-Object{$_.exit_code-ne 0})
      if($wave.resource_budget_exceeded-or$failed.Count-ne 0){
        if($wave.resource_budget_exceeded){$script:resourceBudgetExceeded=$true}
        $reason=if($wave.resource_budget_exceeded){"SIMION $name batch wave resource budget exceeded."}else{"SIMION $name batch wave failed: $($failed.name -join ',')"}
        throw $reason
      }
    }
    if($batchRuns.Count-gt 1-or($continuationPredecessor-and-not$caseRunsNative[$name])){
      if($script:retainedFormalBatchOutputs.ContainsKey($name)){
        $retained=$script:retainedFormalBatchOutputs[$name]
        $firstBatch=$batchRuns[0]
        foreach($kind in @('state','summary')){
          $source=[string]$retained.$kind
          $destination=[string]$firstBatch.$kind
          if(-not(Test-Path -LiteralPath $source)){throw "SIMION $name retained first formal $kind output is missing."}
          Move-Item -LiteralPath $source -Destination $destination -Force
        }
        if($mechanicalExitEnabled){
          Move-Item -LiteralPath ([string]$retained.mechanical) -Destination ([string]$firstBatch.mechanical) -Force
        }
        $trajectorySource=[string]$retained.trajectory
        if(Test-Path -LiteralPath $trajectorySource){
          Move-Item -LiteralPath $trajectorySource -Destination ([string]$firstBatch.trajectory) -Force
        }
        $null=$script:retainedFormalBatchOutputs.Remove($name)
      }
      Push-Location $codeRoot
      try{
        $env:PYTHONPATH=$codeRoot
        foreach($merge in @(
          @{output=$caseState;property='state';required=$true},
          @{output=$caseTrajectory;property='trajectory';required=$false},
          @{output=$caseMechanical;property='mechanical';required=$mechanicalExitEnabled}
        )){
          if($continuationPredecessor-and$RetentionClass-eq'compact'-and$merge.property-eq'trajectory'){continue}
          $existingBatchPaths=@($batchRuns|ForEach-Object{
            $path=[string]$_.($merge.property)
            if(Test-Path -LiteralPath $path){$path}
          })
          if ($existingBatchPaths.Count -eq 0 -and -not [bool]$merge.required) { continue }
          if ($existingBatchPaths.Count -ne $batchRuns.Count) {
            throw "SIMION $name shared $($merge.property) CSV is incomplete across batches."
          }
          $mergeArguments=@('-m','common.simion.particle_batching','--merge-rebase-csv','--output',$merge.output)
          foreach($batchRun in $batchRuns){
            $mergeArguments+=@('--batch-csv',[string]$batchRun.($merge.property),[string]$batchRun.batch.simion_particle_id_offset)
          }
          # Keep merger diagnostics from becoming extra function return
          # values; only the parsed aggregate summary is returned below.
          & $python @mergeArguments | Out-Null
          if($LASTEXITCODE-ne 0){throw "SIMION $name shared particle CSV merge failed."}
        }
      }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
      Push-Location $codeRoot
      try{
        $env:PYTHONPATH=$codeRoot
        $summaryMergeArguments=@('-m','common.simion.particle_batching','--merge-summaries',
          '--batch-plan',$batchPlan,'--output',$caseSummary)
        foreach($batchRun in $batchRuns){$summaryMergeArguments+=@('--batch-summary',[string]$batchRun.summary)}
        # The shared Python merger may emit diagnostics on stdout.  Keep that
        # process output out of this function's return value: callers expect
        # precisely the parsed aggregate summary object below.
        & $python @summaryMergeArguments | Out-Null
        if($LASTEXITCODE-ne 0){throw "SIMION $name shared summary merge failed."}
      }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
    }
    $stateReport=Join-Path $resultDir "particle_state_contract__$name.json"
    Push-Location $codeRoot
    try{
      $env:PYTHONPATH=$codeRoot
      & $python -m common.contracts.particle_state --state $caseState --particles $particleSource `
        --source-format canonical --frequency-hz $drive.frequency_Hz --phase-rad $drive.phase_rad `
        --rod-exit-mm $geometry.rod_z_max --handoff-mm $handoffPlaneMm `
        --solver 'SIMION 2020' --output $stateReport|Out-Null
      if($LASTEXITCODE-ne 0){throw "SIMION $name particle-state contract failed."}
    }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
    if($mechanicalExitEnabled){
      $mechanicalValidation=@'
import json,sys
from pathlib import Path
from projects.rf_multipole_ion_optics.core.component_port import validate_exit_observations
state,source,plan,output=map(Path,sys.argv[1:])
report=validate_exit_observations(state,source,json.loads(plan.read_text(encoding='utf-8-sig')))
output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
'@
      Push-Location $codeRoot
      try{
        $env:PYTHONPATH=$codeRoot
        & $python -B -c $mechanicalValidation $caseMechanical $particleSource `
          (Join-Path $inputDir 'mechanical_exit_observation.json') (Join-Path $resultDir "mechanical_exit_census__$name.json")
        if($LASTEXITCODE-ne0){throw "SIMION $name real mechanical exit/cohort validation failed."}
      }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
    }
    return Get-Content -LiteralPath $caseSummary -Raw -Encoding UTF8|ConvertFrom-Json
  }

  # All cases share one heavy flight stage; internal workers do not acquire grants.
  if(-not$continuationAllReuse){
    $hostExecutionLease=Update-HostResourceStage -Lease $hostExecutionLease -Stage flight `
      -Budget (Get-HostResourceBudget -Role SIMION -Stage flight) -RetainedMemoryBytes 0
  }
  $control=$null;$controlName=$null
  if($segmented){
    $primaryName='axial_acceleration_rf_on';$controlName='zero_axial_drop_rf_on'
    $primary=Invoke-TransportCase $primaryName 1 1
    if($CaseSet-eq'primary_and_zero_axial_control'){
      $control=Invoke-TransportCase $controlName 1 0
      $metrics=Join-Path $resultDir 'axial_acceleration_metrics.json'
      Push-Location $codeRoot
      try{
        $env:PYTHONPATH=$codeRoot
        & $python -m projects.rf_multipole_ion_optics.analysis.analyze_simion_axial_acceleration `
          --accelerated-state (Join-Path $resultDir "particle_states__$primaryName.csv") `
          --control-state (Join-Path $resultDir "particle_states__$controlName.csv") `
          --resolved-contract $resolved --output $metrics
        if($LASTEXITCODE-ne 0){throw 'SIMION axial-drive metrics analysis failed.'}
      }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
    }elseif($CaseSet-eq'primary_and_rf_off_energy_control'){
      $controlName='axial_acceleration_rf_off'
      $control=Invoke-TransportCase $controlName 0 1
      $metrics=Join-Path $resultDir 'rf_off_energy_control_metrics.json'
      Push-Location $codeRoot
      try{
        $env:PYTHONPATH=$codeRoot
        & $python -m projects.rf_multipole_ion_optics.analysis.analyze_simion_transport_metrics --metric-kind rf_off_energy_control `
          --project-id $ProjectId --parent-resolved-design-sha256 $resolvedHash --case-set $CaseSet `
          --primary-case-id $primaryName --primary-summary (Join-Path $resultDir "simion_summary__$primaryName.json") `
          --primary-state (Join-Path $resultDir "particle_states__$primaryName.csv") `
          --control-case-id $controlName --control-summary (Join-Path $resultDir "simion_summary__$controlName.json") `
          --control-state (Join-Path $resultDir "particle_states__$controlName.csv") --output $metrics
        if($LASTEXITCODE-ne 0){throw 'SIMION RF-off transport metrics analysis failed.'}
      }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
    }else{
      $metrics=Join-Path $resultDir 'primary_transport_metrics.json'
      Push-Location $codeRoot
      try{
        $env:PYTHONPATH=$codeRoot
        & $python -m projects.rf_multipole_ion_optics.analysis.analyze_simion_transport_metrics --metric-kind primary `
          --project-id $ProjectId --parent-resolved-design-sha256 $resolvedHash --case-set $CaseSet `
          --primary-case-id $primaryName --primary-summary (Join-Path $resultDir "simion_summary__$primaryName.json") `
          --primary-state (Join-Path $resultDir "particle_states__$primaryName.csv") --output $metrics
        if($LASTEXITCODE-ne 0){throw 'SIMION primary transport metrics analysis failed.'}
      }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
    }
  }else{
    $primaryName='rf_on';$controlName='zero_rf_control'
    $primary=Invoke-TransportCase $primaryName 1 0
    $metrics=Join-Path $resultDir 'finite_3d_transport_metrics.json'
    if($CaseSet-in @('primary_and_zero_axial_control','primary_and_rf_off_energy_control')){
      $control=Invoke-TransportCase $controlName 0 0
      Push-Location $codeRoot
      try{
        $env:PYTHONPATH=$codeRoot
        & $python -m projects.rf_multipole_ion_optics.analysis.analyze_simion_transport_metrics --metric-kind base_paired `
          --project-id $ProjectId --parent-resolved-design-sha256 $resolvedHash --case-set $CaseSet `
          --primary-case-id $primaryName --primary-summary (Join-Path $resultDir "simion_summary__$primaryName.json") `
          --control-case-id $controlName --control-summary (Join-Path $resultDir "simion_summary__$controlName.json") `
          --output $metrics
        if($LASTEXITCODE-ne 0){throw 'SIMION paired transport metrics analysis failed.'}
      }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
    }else{
      Push-Location $codeRoot
      try{
        $env:PYTHONPATH=$codeRoot
        & $python -m projects.rf_multipole_ion_optics.analysis.analyze_simion_transport_metrics --metric-kind base_primary `
          --project-id $ProjectId --parent-resolved-design-sha256 $resolvedHash --case-set $CaseSet `
          --primary-case-id $primaryName --primary-summary (Join-Path $resultDir "simion_summary__$primaryName.json") --output $metrics
        if($LASTEXITCODE-ne 0){throw 'SIMION primary transport metrics analysis failed.'}
      }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
    }
  }
  # Flight workers have joined; publication returns to the ordinary light stage.
  Set-RfRunPhase 'diagnostics'
  $hostExecutionLease=Update-HostResourceStage -Lease $hostExecutionLease -Stage postprocess `
    -Budget (Get-HostResourceBudget -Role SIMION -Stage postprocess) -RetainedMemoryBytes 0
  $exitStatePlot=Join-Path $resultDir 'exit_state_diagnostics.png'
  $exitStatePlotManifest=Join-Path $resultDir 'exit_state_diagnostics.json'
  $primaryState=Join-Path $resultDir "particle_states__$primaryName.csv"
  Push-Location $codeRoot
  try{
    $env:PYTHONPATH=$codeRoot
    $exitStatePlotLabel=$ProjectId.Replace('_',' ')
    & $python -m projects.rf_multipole_ion_optics.analysis.exit_state_plot `
      --series "$exitStatePlotLabel=$primaryState=$RunId" `
      --output $exitStatePlot --manifest $exitStatePlotManifest `
      --title "$exitStatePlotLabel exit-state diagnostic" `
      --purpose 'Regular single-run multipole exit-state diagnostic' `
      --repo-root $repoRoot
    if($LASTEXITCODE-ne 0){throw 'SIMION exit-state diagnostic plot failed.'}
  }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
  $scientificStatus='success';$qualification='UNQUALIFIED';$scientificChecks=@{}
  $evaluation=Join-Path $resultDir 'evidence_evaluation.json'
  if($evidence){
    Push-Location $codeRoot
    try{
      $env:PYTHONPATH=$codeRoot
      & $python -m projects.rf_multipole_ion_optics.analysis.evaluate_transport_evidence --metrics $metrics --evidence $evidence `
        --project-id $ProjectId --design-profile-id $DesignProfileId --output $evaluation
      $evidenceExit=$LASTEXITCODE
    }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
    if($evidenceExit-notin@(0,1)){throw 'SIMION evidence evaluation failed before a scientific decision.'}
    $validateEvaluation=@'
import json,sys
from pathlib import Path
from common.contracts.machine_contracts import validate_schema
result=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))
validate_schema(result,'multipole_evidence_evaluation.schema.json')
expected='PASS' if all(result['checks'].values()) else 'FAIL'
if (result['project_id']!=sys.argv[2] or result['design_profile_id']!=sys.argv[3]
        or result['status']!=expected or int(sys.argv[4])!=(0 if expected=='PASS' else 1)):
    raise ValueError('evidence result identity/checks/exit status differ')
print(json.dumps(result,allow_nan=False))
'@
    Push-Location $codeRoot
    try{
      $env:PYTHONPATH=$codeRoot
      $validated=& $python -B -c $validateEvaluation $evaluation $ProjectId $DesignProfileId $evidenceExit
      if($LASTEXITCODE-ne0){throw 'SIMION evidence result contract is invalid.'}
      $decision=$validated|ConvertFrom-Json -AsHashtable
    }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
    $qualification=[string]$decision.status
    $scientificChecks=$decision.checks
    if($qualification-eq'FAIL'){$scientificStatus='failed'}
  }
  # Invoke-TransportCase performs several external lifecycle operations.  Its
  # pipeline value is not a stable summary interface under StrictMode; use the
  # already merged, contract-checked case summaries as the sole source here.
  $primaryCaseSummary=Get-Content -LiteralPath (Join-Path $resultDir "simion_summary__$primaryName.json") `
    -Raw -Encoding UTF8|ConvertFrom-Json
  if($primaryCaseSummary.PSObject.Properties.Match('transmission').Count-ne 1){
    throw 'Primary SIMION case did not produce a transmission.'
  }
  $primaryTransmission=[double]$primaryCaseSummary.transmission
  $controlTransmission=$null
  if($CaseSet-ne'primary_only'){
    $controlCaseSummary=Get-Content -LiteralPath (Join-Path $resultDir "simion_summary__$controlName.json") `
      -Raw -Encoding UTF8|ConvertFrom-Json
    if($controlCaseSummary.PSObject.Properties.Match('transmission').Count-ne 1){
      throw 'Paired SIMION case set did not produce a control transmission.'
    }
    $controlTransmission=[double]$controlCaseSummary.transmission
  }
  Set-RfRunPhase 'finalization'
  $summaryDocument=[ordered]@{schema_version=1;role='multipole_simion_finite_3d_transport_summary';status=$scientificStatus;run_id=$RunId;
    native_execution_complete=$true;checks=$scientificChecks;
    qualification_status=$qualification;project_id=$ProjectId;design_profile_id=$DesignProfileId;
    parent_resolved_design_sha256=$resolvedHash;primary_transmission=$primaryTransmission;
    case_set=$CaseSet;
    control_transmission=$controlTransmission;
    model_level='L3';formal_gate_passed=$false;execution_status='completed';data_validity='valid';
    scientific_result=$qualification;failure_stage=$null;failure_reason=$null;recovery_action='none';
    phase_timings_seconds=$phaseTimings;elapsed_before_finalization_seconds=$runTimer.Elapsed.TotalSeconds;
    continuation_predecessor=$(if($continuationPredecessor){$continuationPredecessor}else{$null});
    reused_fly_batches=$(if($continuationPredecessor){[int]$continuation.replay.reusable_unit_count}else{0});
    scheduled_fly_batches=$(if($continuationPredecessor){[int]$continuation.replay.replay_unit_count}else{$null})}
  $resourceProfile=$null
  $caseResourceUsage=[ordered]@{}
  if($caseRunsNative[$primaryName]){
    $caseResourceUsage[$primaryName]=$resourceUsage
  }
  if($null-ne$control-and$caseRunsNative[$controlName]){
    $controlResourceUsage=Join-Path $resultDir "resource_usage__$controlName.json"
    $caseResourceUsage[$controlName]=$controlResourceUsage
  }
  $resourceItems=@($caseResourceUsage.Keys|ForEach-Object{@{case_name=[string]$_;path=(Convert-WorkflowOwnerPath $ownerContext $caseResourceUsage[$_])}})
  $profileRequest=$null
  if($null-ne$dispatchPlan-and$resourceIdentityWasUnknown){
    $resourceProfile=Join-Path $resultDir 'simion_resource_profile.json'
    $profileRequest=@{usage_path=(Convert-WorkflowOwnerPath $ownerContext $resourceObservationUsage);dispatch_plan=(Convert-WorkflowOwnerPath $ownerContext $dispatchPlan);output=(Convert-WorkflowOwnerPath $ownerContext $resourceProfile)}
  }
  $outputs=@($summary,$metrics,$resourceUsage,$exitStatePlot,$exitStatePlotManifest,
    (Join-Path $solverDir 'quad_monolithic.pa0'),
    (Join-Path $solverDir 'quad_monolithic.iob'),
    (Join-Path $solverDir 'quad_monolithic.con'),$gem,$fly2,
    (Join-Path $resultDir "simion_summary__$primaryName.json"),
    (Join-Path $resultDir "particle_states__$primaryName.csv"),
    (Join-Path $resultDir "trajectory_samples__$primaryName.csv"),
    (Join-Path $resultDir "particle_state_contract__$primaryName.json"))
  $outputs+=@($caseResourceUsage.Values|Where-Object{$_-ne$resourceUsage})
  $outputs+=@($checkpointOutputs)
  $outputs+=@($fieldCheckpointOutputs|Select-Object -Unique)
  $outputs+=@($batchCompletionReceipts)
  $outputs+=@($retainedTrajectoryOutputs)
  if($null-ne$control){
    $outputs+=@(
      (Join-Path $resultDir "simion_summary__$controlName.json"),
      (Join-Path $resultDir "particle_states__$controlName.csv"),
      (Join-Path $resultDir "trajectory_samples__$controlName.csv"),
      (Join-Path $resultDir "particle_state_contract__$controlName.json")
    )
  }
  if($mechanicalExitEnabled){$outputs+=@(Get-ChildItem -LiteralPath $resultDir -File -Filter 'mechanical_exit*'|Select-Object -ExpandProperty FullName)}
  $outputs+=@(Get-ChildItem -LiteralPath $logDir -Recurse -File|Select-Object -ExpandProperty FullName)
  if(Test-Path -LiteralPath $evaluation){$outputs+=$evaluation}
  $outputs=@($outputs|Where-Object{Test-Path -LiteralPath $_ -PathType Leaf})
  if($resourceProfile){$outputs+=$resourceProfile}
  $requiredPaths=@($metrics,$primaryState,(Join-Path $resultDir "simion_summary__$primaryName.json"),$exitStatePlot,$exitStatePlotManifest)
  if($null-ne$control){$requiredPaths+=@((Join-Path $resultDir "particle_states__$controlName.csv"),(Join-Path $resultDir "simion_summary__$controlName.json"))}
  if(Test-Path -LiteralPath $evaluation){$requiredPaths+=$evaluation}
  $writerCompletion=Get-RfSimionStoppedWriterCompletion -HostLease $hostExecutionLease -NativeOperations $nativeOperations -State $hostReleaseState
  $hostReleased=$hostReleaseState.released
  $ownerOutputs=@($outputs|ForEach-Object{Convert-WorkflowOwnerPath $ownerContext $_}|Where-Object{
    $_.StartsWith($physicalRunDir.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)
  }|Select-Object -Unique)
  $deferFinalization=$true
  $null=Complete-RunArtifactPowerShellOwner -Context $ownerContext -Status $scientificStatus -Summary $summaryDocument `
    -OutputPaths $ownerOutputs -RequiredOutputPaths $requiredPaths -WriterCompletion $writerCompletion -WritersStopped $true `
    -ResourceUsagePaths $resourceItems -ResourceProfile $profileRequest -OriginalFailure $null
  $deferFinalization=$false;$continuationCapacity=$null
  Write-Output "MULTIPOLE_SIMION_WORKFLOW_RESULT=$ResultPath"
  $hostExecutionOutcome=$scientificStatus
  $resultMarker=if($scientificStatus-eq'success'){'PASS'}else{'FAIL'}
  Write-Output "MULTIPOLE_SIMION_RESOLVED=$resultMarker PROJECT=$ProjectId PROFILE=$DesignProfileId RUN_ID=$RunId PARENT_SHA256=$resolvedHash QUALIFICATION=$qualification"
}catch{
  $simionRunFailure=$_
  $hostExecutionOutcome=if($resourceBudgetExceeded){'interrupted'}else{'failed'}
  Set-RfRunPhase ''
  $failureData=$simionRunFailure.Exception.Data
  $waveWriterUnknown=($failureData.Contains('simion_wave_writer_completion_confirmed')-and
    -not[bool]$failureData['simion_wave_writer_completion_confirmed'])-or
    $failureData.Contains('simion_wave_drain_error')
  if($failureData.Contains('simion_first_batch_drain_error')-or
    [bool]$failureData['simion_first_batch_writer_unknown']-or$waveWriterUnknown-or
    [bool]$failureData['rf_host_release_unconfirmed']){
    $script:writerCompletionUnknown=$true
    try {
      Write-RunJson -Path $summary -Value @{schema_version=1;role='multipole_simion_finite_3d_transport_summary';status='writer_completion_unknown';reason=$simionRunFailure.Exception.Message;drain_error=$(if($failureData.Contains('simion_wave_drain_error')){[string]$failureData['simion_wave_drain_error']}else{[string]$failureData['simion_first_batch_drain_error']})}
      Write-RunJson -Atomic -Path $ResultPath -Depth 12 -Value @{schema_version=1;role='run_artifact_workflow_result';status='failed';
        execution_status='writer_completion_unknown';data_validity='unknown';scientific_result='NOT_EVALUATED';failure_stage=$phaseName;
        failure_reason=$simionRunFailure.Exception.Message;recovery_action=$(if([bool]$failureData['rf_host_release_unconfirmed']){'inspect_host_release'}else{'inspect_writer_completion'});result_path=$ResultPath;
        run_directory=$physicalRunDir;phase_timings_seconds=$phaseTimings;total_elapsed_seconds=$runTimer.Elapsed.TotalSeconds}
    } catch { $simionRunFailure.Exception.Data['writer_unknown_result_error']=[string]$_ }
    throw $simionRunFailure
  }
  if($null-ne$ownerContext-and$ownerContext.completion_written){throw $simionRunFailure}
  try{
    $failureDetails=@{}
    if($simionRunFailure.Exception.Data['simion_additional_checkpoint_error']){
      $failureDetails.additional_checkpoint_error=[string]$simionRunFailure.Exception.Data['simion_additional_checkpoint_error']
    }
    $ownerReady=$null-ne(Get-Variable workflowRequestPath -ErrorAction SilentlyContinue)-and(Test-Path -LiteralPath $workflowRequestPath)
    if($ownerReady){
      $currentConfig=Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
      $ownerReady=$currentConfig.inputs-is[Collections.IDictionary]-and$currentConfig.inputs.Contains('execution_request')-and
        $currentConfig.inputs.execution_request-ceq$workflowRequestPath
    }
    if($ownerReady){
      $failedSummary=[ordered]@{schema_version=1;role='multipole_simion_finite_3d_transport_summary';status=$hostExecutionOutcome;run_id=$RunId;
        execution_status='failed';data_validity='unknown';scientific_result='NOT_EVALUATED';failure_stage=$phaseName;
        failure_reason=$simionRunFailure.Exception.Message;recovery_action='use_explicit_predecessor_new_run';
        phase_timings_seconds=$phaseTimings;elapsed_before_finalization_seconds=$runTimer.Elapsed.TotalSeconds}
      foreach($key in $failureDetails.Keys){$failedSummary[$key]=$failureDetails[$key]}
      $failureOutputs=@(foreach($directory in @($resultDir,$logDir,$solverDir)){
        if(Test-Path -LiteralPath $directory){Get-ChildItem -LiteralPath $directory -Recurse -File|Select-Object -ExpandProperty FullName}
      })
      $failureUsage=@(Get-ChildItem -LiteralPath $resultDir -File -Filter 'resource_usage*.json'|ForEach-Object{
        @{case_name=$_.BaseName;path=(Convert-WorkflowOwnerPath $ownerContext $_.FullName)}
      })
      $writerCompletion=Get-RfSimionStoppedWriterCompletion -HostLease $hostExecutionLease -NativeOperations $nativeOperations -State $hostReleaseState
  $hostReleased=$hostReleaseState.released
      $deferFinalization=$true
      $null=Complete-RunArtifactPowerShellOwner -Context $ownerContext -Status $hostExecutionOutcome -Summary $failedSummary `
        -OutputPaths $failureOutputs -WriterCompletion $writerCompletion -WritersStopped $true `
        -ResourceUsagePaths $failureUsage -OriginalFailure $simionRunFailure
      $deferFinalization=$false;$continuationCapacity=$null
      Write-Output "MULTIPOLE_SIMION_WORKFLOW_RESULT=$ResultPath"
    }else{
      Complete-FailedRun -Python $python -RepoRoot $manifestRepoRoot -RunConfig $runConfig -Summary $summary `
        -SummaryRole 'multipole_simion_finite_3d_transport_summary' -Reason $simionRunFailure.Exception.Message `
        -Software @('SIMION 2020','Python 3.11') -Status $hostExecutionOutcome -AdditionalSummaryProperties $failureDetails
      Write-RunJson -Atomic -Path $ResultPath -Depth 12 -Value @{schema_version=1;role='run_artifact_workflow_result';status=$hostExecutionOutcome;
        execution_status='failed';data_validity='unknown';scientific_result='NOT_EVALUATED';failure_stage=$phaseName;
        failure_reason=$simionRunFailure.Exception.Message;recovery_action='inspect_failure';result_path=$ResultPath;
        run_directory=$physicalRunDir;phase_timings_seconds=$phaseTimings;total_elapsed_seconds=$runTimer.Elapsed.TotalSeconds}
    }
  }catch{
    $closureFailure=$_
    $simionRunFailure.Exception.Data['failure_closure_error']=$closureFailure.Exception.Message
    if($closureFailure.Exception.Data['rf_host_release_unconfirmed']){
      $script:deferFinalization=$true
      $hostReleaseState.unknown=$true
      $simionRunFailure.Exception.Data['host_release_error']=$closureFailure.Exception.Message
      $blockedSummary=@{execution_status='host_release_unconfirmed';failure_stage='host_release';failure_reason=$closureFailure.Exception.Message;
        recovery_action='inspect_host_release';secondary_errors=@($closureFailure.Exception.Message);
        phase_timings_seconds=$phaseTimings;total_elapsed_seconds=$runTimer.Elapsed.TotalSeconds}
      try{
        $null=Complete-RunArtifactPowerShellOwner -Context $ownerContext -Status failed -Summary $blockedSummary `
          -WriterCompletion @{operations=@($nativeOperations);resource_releases=@()} -WritersStopped $false -OriginalFailure $simionRunFailure
      }catch{
        if($_.Exception.Message-notmatch'native writer completion is unknown'){
          $simionRunFailure.Exception.Data['host_unknown_result_error']=[string]$_
        }
      }
    }
    Write-Warning "SIMION failure closure also failed: $($closureFailure.Exception.Message)"
  }
  throw $simionRunFailure
}finally{
  if(-not$script:writerCompletionUnknown-and-not$hostReleaseState.unknown){
  try { Remove-RunPackageExecutionAlias -Package $package } catch {
    Write-Warning "Could not remove short execution alias after SIMION run: $($_.Exception.Message)"
  }
  try{if(-not$hostReleased){Exit-HostExecutionLease -Lease $hostExecutionLease -Outcome $hostExecutionOutcome -RunId $RunId}}
  catch{
    if($null-eq$simionRunFailure){throw}
    $simionRunFailure.Exception.Data['host_release_error']=$_.Exception.Message
    Write-Warning "SIMION host cleanup also failed: $($_.Exception.Message)"
  }
  foreach($stream in $continuationGuards){$stream.Dispose()}
  if($null-ne$fieldCheckpointGuard){
    try{Close-RfSimionFieldCheckpointGuard -Context $fieldCheckpointGuard}
    catch{if($null-eq$simionRunFailure){throw};$simionRunFailure.Exception.Data['field_guard_cleanup_error']=[string]$_}
  }
  if($null-ne$continuationCapacity-and-not$deferFinalization){
    try{Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $continuationCapacity|Out-Null}
    catch{if($null-eq$simionRunFailure){throw};$simionRunFailure.Exception.Data['capacity_release_error']=[string]$_}
  }
  }
}
# Preserve the public launcher's scientific-failure signal after releasing the grant.
if($hostExecutionOutcome-eq'failed'){exit 1}
