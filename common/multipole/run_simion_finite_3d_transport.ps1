[CmdletBinding(DefaultParameterSetName='IsotropicCell')]
param(
  [Parameter(Mandatory=$true)][string]$ProjectId,
  [Parameter(Mandatory=$true)][string]$RuntimeProfileId,
  [Parameter(Mandatory=$true)][string]$DesignProfileId,
  [Parameter(Mandatory=$true)][string]$ParticleSourcePath,
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
  [ValidateSet('compact','qualification','solver_review')][string]$RetentionClass='compact',
  [string]$RetentionReason='',
  [string]$SourceFamilyPath='',
  [string]$OperatingPointId=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
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

function Get-TextSha256 {
  param([Parameter(Mandatory=$true)][string]$Text)
  $bytes=[Text.Encoding]::UTF8.GetBytes($Text)
  return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes))
}

function Get-VerifiedPaBasisFiles {
  param(
    [Parameter(Mandatory=$true)][string]$ManifestPath,
    [Parameter(Mandatory=$true)][string]$ExpectedFingerprint
  )
  $manifest=Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8|ConvertFrom-Json
  if([int]$manifest.schema_version-ne 1-or
    [string]$manifest.role-ne'multipole_simion_pa_basis_cache'-or
    [string]$manifest.fingerprint_sha256-ne$ExpectedFingerprint-or
    $null-eq$manifest.files
  ){throw 'SIMION PA-basis cache manifest identity differs.'}
  $root=Split-Path -Parent ([IO.Path]::GetFullPath($ManifestPath))
  $verified=@()
  foreach($record in @($manifest.files)){
    $name=[string]$record.name
    if($name-notmatch'^quad_monolithic\.pa(?:#|-surf|\d+)$'){
      throw "SIMION PA-basis cache filename is invalid: $name"
    }
    $path=[IO.Path]::GetFullPath((Join-Path $root $name))
    if(-not $path.StartsWith($root+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)-or
      -not(Test-Path -LiteralPath $path -PathType Leaf)-or
      (Get-Item -LiteralPath $path).Length-ne[int64]$record.bytes-or
      (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash-ne[string]$record.sha256
    ){throw "SIMION PA-basis cache file identity differs: $name"}
    $verified+=[pscustomobject]@{name=$name;path=$path}
  }
  if($verified.Count-lt 3){throw 'SIMION PA-basis cache is incomplete.'}
  return $verified
}

$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\multipole\resource_budget_support.ps1')
$particleSourceInput=(Resolve-Path -LiteralPath $ParticleSourcePath).Path
$engineeringBudgetInput=(Resolve-Path -LiteralPath $EngineeringBudgetPath).Path
$engineeringBudgetAuthority=Get-Content -LiteralPath $engineeringBudgetInput -Raw -Encoding UTF8|ConvertFrom-Json
$resolvedRuntimeInput=$null
$resolvedRuntimeDocument=$null
$resolvedRuntimeInputSha=$null
$executionBatching=$null
$existingFormalProcessRecords=@()
$retainedFormalBatchOutputs=@{}
$resourceIdentityWasUnknown=$false
# Repository scheduling is the default for this independent-particle runner.
# A runtime profile may constrain resource identity, but cannot opt out.
$automaticDispatch=[pscustomobject]@{kind='automatic';field_kind='rf';independent_particles=$true}
if(-not[string]::IsNullOrWhiteSpace($ResolvedRuntimeProfilePath)){
  $resolvedRuntimeInput=(Resolve-Path -LiteralPath $ResolvedRuntimeProfilePath).Path
  $resolvedRuntimeInputSha=(Get-FileHash -LiteralPath $resolvedRuntimeInput -Algorithm SHA256).Hash
  $resolvedRuntimeDocument=Get-Content -LiteralPath $resolvedRuntimeInput -Raw -Encoding UTF8|ConvertFrom-Json
  if([int]$resolvedRuntimeDocument.schema_version-ne 1-or
    [string]$resolvedRuntimeDocument.role-ne'multipole_resolved_runtime_profile'-or
    [string]$resolvedRuntimeDocument.project_id-ne$ProjectId-or
    [string]$resolvedRuntimeDocument.runtime_profile_id-ne$RuntimeProfileId-or
    [string]$resolvedRuntimeDocument.design_profile_id-ne$DesignProfileId-or
    [string]$resolvedRuntimeDocument.particle_source.path-ne$particleSourceInput-or
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
    $budgetArguments=@('-m','common.multipole.resource_budget',
      '--repo-root',$repoRoot,'--budget',$engineeringBudgetInput,
      '--project-id',$ProjectId,'--solver','simion',
      '--runtime-profile-id',$RuntimeProfileId,
      '--design-profile-id',$DesignProfileId,
      '--particle-source',$particleSourceInput,
      '--retention-class',$RetentionClass,'--output',$budgetPreflight)
    $budgetArguments+=@('--run-id',$RunId)
    & $python @budgetArguments
  }finally{Pop-Location}
  if($LASTEXITCODE-ne 0){throw 'SIMION resource-budget preflight failed.'}
  $resolvedBudgetPreflight=Get-Content -LiteralPath $budgetPreflight -Raw -Encoding UTF8|ConvertFrom-Json
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
}catch{
  Remove-Item -LiteralPath $budgetPreflight -Force -ErrorAction SilentlyContinue
  throw
}
if(-not(Test-Path -LiteralPath $simion -PathType Leaf)){
  Remove-Item -LiteralPath $budgetPreflight -Force -ErrorAction SilentlyContinue
  throw "SIMION executable is missing: $simion"
}
$executionCapacityPaths=Get-RunPackageCopiedSourcePaths -RepoRoot $repoRoot `
  -SourceRelativeDirectories @('common/contracts','common/multipole','common/simion') `
  -Extensions @('.py','.json','.ps1','.lua')
$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$ProjectId") -RunId $RunId `
  -Project $ProjectId -Mode 'resolved_design_transport' -Software @('SIMION 2020','Python 3.11') `
  -RetentionContractEnabled `
  -RetentionClass $RetentionClass -RetentionReason $RetentionReason `
  -AdditionalDirectories @('simion') -UseShortExecutionPath `
  -ExpectedExecutionRelativePaths $executionCapacityPaths
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir
$logDir=$package.log_dir;$solverDir=Join-Path $runDir 'simion'
$runConfig=$package.run_config;$summary=$package.summary;$manifestRepoRoot=$repoRoot
$resourceBudgetExceeded=$false
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
$hostExecutionOutcome='failed'
$hostExecutionLease=Enter-HostExecutionLease -Role SIMION -RunId $RunId

try{
  $codeRoot=Join-Path $inputDir 'code'
  foreach($area in @('contracts','multipole','simion')){
    $sourceRoot=Join-Path $repoRoot "common\$area";$destinationRoot=Join-Path $codeRoot "common\$area"
    Get-ChildItem -LiteralPath $sourceRoot -Recurse -File|Where-Object{
      $_.Extension -in @('.py','.json','.ps1','.lua')
    }|ForEach-Object{
      $relative=$_.FullName.Substring($sourceRoot.Length).TrimStart('\')
      $destination=Join-Path $destinationRoot $relative
      New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination)|Out-Null
      Copy-Item -LiteralPath $_.FullName -Destination $destination
    }
  }
  $codeInventory=Join-Path $inputDir 'code_inventory.json'
  $inventory=@(Get-ChildItem -LiteralPath $codeRoot -Recurse -File|Sort-Object FullName|ForEach-Object{
    [ordered]@{path=$_.FullName.Substring($codeRoot.Length+1).Replace('\','/');sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}
  })
  [ordered]@{schema_version=1;role='frozen_code_inventory';files=$inventory}|
    ConvertTo-Json -Depth 5|Set-Content -LiteralPath $codeInventory -Encoding UTF8
  $manifestRepoRoot=$codeRoot
  . (Join-Path $codeRoot 'common\multipole\simion_layout_template_support.ps1')

  $templateDir=Join-Path $inputDir 'simion_layout_template'
  $templateRegistryFrozen=Join-Path $codeRoot 'common\multipole\simion_layout_template.json'
  $template=Resolve-MultipoleSimionLayoutTemplate -Python $python `
    -RepositoryRoot $repoRoot -TemplateDirectory $templateDir `
    -RegistryPath $templateRegistryFrozen -ModuleRoot $codeRoot
  $templateResolution=$template.resolution
  $templateProfile=$template.profile
  $templateRegistryInput=$template.registry
  $templateRegistrationManifest=$template.registration_manifest
  $templateIob=$template.iob
  $templateCon=$template.con

  $profileResolution=Join-Path $inputDir 'design_profile_resolution.json'
  $resolvedRuntimeProfile=$null
  $terminalRegistry=$null
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
    if($resolvedRuntimeDocument.PSObject.Properties.Name-contains'downstream_terminal_profile'){
      $terminalBinding=$resolvedRuntimeDocument.downstream_terminal_profile
      $terminalRegistrySource=(Resolve-Path -LiteralPath ([string]$terminalBinding.registry_path)).Path
      if((Get-FileHash -LiteralPath $terminalRegistrySource -Algorithm SHA256).Hash-ne
        [string]$terminalBinding.registry_sha256
      ){throw 'Downstream-terminal registry changed before it was frozen.'}
      $terminalRegistry=Copy-VerifiedRunInput -Source $terminalRegistrySource `
        -Destination (Join-Path $inputDir 'downstream_terminal_profiles.json')
    }
  }
  $engineeringBudget=Join-Path $inputDir 'engineering_budget.json'
  $resolvedResourceBudget=Join-Path $inputDir 'resolved_resource_budget.json'
  $engineeringBudget=Copy-VerifiedRunInput -Source $engineeringBudgetInput `
    -Destination $engineeringBudget
  if($campaignSelection-and
    (Get-FileHash -LiteralPath $engineeringBudget -Algorithm SHA256).Hash-ne
      [string]$campaignSelection.sha256
  ){throw 'Frozen campaign authority differs from the resolved runtime-profile snapshot.'}
  Move-Item -LiteralPath $budgetPreflight -Destination $resolvedResourceBudget
  Push-Location $codeRoot
  try{
    $env:PYTHONPATH=$codeRoot
    & $python -m common.multipole.design_profile --repo-root $repoRoot --project-id $ProjectId `
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
  $compileRequest=$request;$compileVariables=$variables;$compileEnvelope=$envelope
  $compileModeRegistry=$modeRegistry;$compileProvenanceRoot=$inputDir
  if($terminalRegistry){
    $authorityRoot=Join-Path $inputDir 'authority_repo'
    function Copy-FrozenAuthorityPath([string]$source,[string]$frozenSource){
      $relative=[IO.Path]::GetRelativePath($repoRoot,[IO.Path]::GetFullPath($source))
      if($relative -eq '..' -or $relative.StartsWith(('..'+[IO.Path]::DirectorySeparatorChar))){
        throw "Terminal authority path escapes the repository: $source"
      }
      $destination=Join-Path $authorityRoot $relative
      New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination)|Out-Null
      Copy-Item -LiteralPath $frozenSource -Destination $destination
      return $destination
    }
    $compileRequest=Copy-FrozenAuthorityPath ([string]$profile.paths.design_request) $request
    $compileVariables=Copy-FrozenAuthorityPath ([string]$profile.paths.design_variables) $variables
    $compileEnvelope=Copy-FrozenAuthorityPath ([string]$profile.paths.optimization_envelope) $envelope
    if($modeRegistry){
      $compileModeRegistry=Copy-FrozenAuthorityPath `
        ([string]$profile.paths.operating_mode_registry) $modeRegistry
    }
    $compileProvenanceRoot=$authorityRoot
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
      & $python -m common.multipole.verify_resolved_design $resolved
      if($LASTEXITCODE-ne 0){throw 'Resolved runtime-profile design identity is invalid.'}
    }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
  }else{
    $baseResolved=if($terminalRegistry){
      Join-Path $inputDir 'multipole_base_resolved_design.json'
    }else{$resolved}
    Push-Location $codeRoot
    try{
      $env:PYTHONPATH=$codeRoot
      $compileArguments=@('-m','common.multipole.compile_design_request',
        '--request',$compileRequest,'--design-variables',$compileVariables,
        '--optimization-envelope',$compileEnvelope,'--output',$baseResolved,
        '--provenance-root',$compileProvenanceRoot,'--project-id',$ProjectId,
        '--radial-order-n',([string][int]$identity.radial_order_n),
        '--electrode-count',([string][int]$identity.electrode_count))
      if($modeRegistry){
        $compileArguments+=@('--operating-mode-registry',$compileModeRegistry,'--mode-id',$modeId)
      }
      & $python @compileArguments
      if($LASTEXITCODE-ne 0){throw 'Governed multipole design compilation failed.'}
      if($terminalRegistry){
        & $python -m common.multipole.downstream_terminal `
          --resolved-design $baseResolved --terminal-registry $terminalRegistry `
          --terminal-profile-id ([string]$resolvedRuntimeDocument.downstream_terminal_profile.terminal_profile_id) `
          --output $resolved
        if($LASTEXITCODE-ne 0){throw 'Downstream-terminal composition failed.'}
      }
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
      $phaseArguments=@('-m','common.multipole.phase_matched_particle_source',
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
  }else{
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
    $preflightArguments=@('-m','common.multipole.particle_source_preflight',
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
    & $python @preflightArguments
    if($LASTEXITCODE-ne 0){throw 'Canonical particle source preflight failed.'}
  }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
  $sourceMeta=Get-Content -LiteralPath $sourceMetadata -Raw -Encoding UTF8|ConvertFrom-Json
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
      $request=[ordered]@{solver='SIMION';field_kind=[string]$automaticDispatch.field_kind;
        particle_count=[int]$sourceMeta.particle_count;independent_particles=$true;
        trajectory_quality_profile_id=("tqual_{0}"-f$TrajectoryQuality);
        time_integration_profile_id=$RuntimeProfileId;
        rf_steps_per_period=$(if([string]$automaticDispatch.field_kind-eq'rf'){$RfStepsPerPeriod}else{$null})}
      $request|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $dispatchRequest -Encoding UTF8
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
    & $python -m common.multipole.simion_geometry --resolved-design $resolved `
      --cell-mm-x $resolvedCellMmX --cell-mm-y $resolvedCellMmY `
      --cell-mm-z $resolvedCellMmZ --output $gem
    if($LASTEXITCODE-ne 0){throw 'SIMION GEM projection failed.'}
    $sourceProjectionArguments=@('-m','common.multipole.simion_particle_source',
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
  $normalizedGem=(Get-Content -LiteralPath $gem -Encoding ASCII|Where-Object{
    $_-notmatch'^; parent_resolved_sha256='
  })-join"`n"
  $paBasisIdentity=[ordered]@{
    schema_version=1
    role='multipole_simion_pa_basis_identity'
    project_id=$ProjectId
    normalized_gem_sha256=(Get-TextSha256 $normalizedGem)
    simion_executable_sha256=(Get-FileHash -LiteralPath $simion -Algorithm SHA256).Hash
    refine_arguments=@('--nogui','--noprompt','refine','quad_monolithic.pa#')
  }
  $paBasisFingerprint=Get-TextSha256 ($paBasisIdentity|ConvertTo-Json -Depth 5 -Compress)
  $paBasisCacheRoot=[IO.Path]::GetFullPath((
    Join-Path $workspaceRoot "artifacts\projects\$ProjectId\cache\simion_pa_basis"
  ))
  $paBasisCacheDir=Join-Path $paBasisCacheRoot $paBasisFingerprint
  $paBasisCacheManifest=Join-Path $paBasisCacheDir 'manifest.json'
  $paBasisCacheManifestInput=$null
  $paBasisReuseAuthorized=($resolvedRuntimeDocument-and
    $resolvedRuntimeDocument.PSObject.Properties.Name-contains'simion_pa_basis_policy'-and
    [string]$resolvedRuntimeDocument.simion_pa_basis_policy.kind-eq'content_addressed_geometry_basis'-and
    [string]$resolvedRuntimeDocument.simion_pa_basis_policy.reuse_scope-eq'same_project_same_fingerprint')
  $paBasisRequireExisting=($paBasisReuseAuthorized-and
    $resolvedRuntimeDocument.simion_pa_basis_policy.PSObject.Properties.Name-contains'require_existing'-and
    $resolvedRuntimeDocument.simion_pa_basis_policy.require_existing-eq$true)
  $paBasisReuse=$false
  $paBasisFiles=@()
  if($paBasisReuseAuthorized-and(Test-Path -LiteralPath $paBasisCacheManifest -PathType Leaf)){
    try{
      $paBasisFiles=@(Get-VerifiedPaBasisFiles -ManifestPath $paBasisCacheManifest `
        -ExpectedFingerprint $paBasisFingerprint)
      $paBasisCacheManifestInput=Copy-VerifiedRunInput -Source $paBasisCacheManifest `
        -Destination (Join-Path $inputDir 'simion_pa_basis_cache_manifest.json')
      $paBasisReuse=$true
    }catch{
      if($paBasisRequireExisting){throw}
      # A verified cache is disposable only after its own file-integrity gate
      # fails.  Remove this exact content-addressed key, never its cache root.
      Write-Warning "SIMION PA-basis cache is corrupt and will be rebuilt: $paBasisFingerprint"
      Remove-Item -LiteralPath $paBasisCacheDir -Recurse -Force
      $paBasisFiles=@();$paBasisCacheManifestInput=$null;$paBasisReuse=$false
    }
  }
  if($paBasisRequireExisting -and -not $paBasisReuse){
    throw "SIMION_PA_BASIS_CACHE_REQUIRED: source-model comparison requires an existing verified PA basis for fingerprint $paBasisFingerprint."
  }
  $publishedPaBasisManifest=$null
  Copy-Item -LiteralPath $templateIob -Destination (Join-Path $solverDir 'quad_monolithic.iob')
  Copy-Item -LiteralPath $templateCon -Destination (Join-Path $solverDir 'quad_monolithic.con')
  Copy-VerifiedRunInput `
    -Source (Join-Path $codeRoot 'common\multipole\simion_transport.lua') `
    -Destination (Join-Path $solverDir 'multipole_runtime_program.lua')|Out-Null
  $rfDriveKernelLua=Join-Path $inputDir 'multipole_rf_drive_kernel.lua'
  Copy-VerifiedRunInput `
    -Source (Join-Path $codeRoot 'common\multipole\simion_rf_drive.lua') `
    -Destination $rfDriveKernelLua|Out-Null

  $drive=$design.drive;$geometry=$design.geometry_mm;$enclosure=$geometry.enclosure
  $static=$design.static_electrodes_V
  $interfaces=$design.interfaces_mm
  $axialTopology=[string]$design.axial_drive.topology
  $segmented=($axialTopology-eq'segmented_rod_axial_acceleration')
  $segmentedRodGeometry=($null-ne$design.segmentation.segmented_rod_array)
  $exitAperturePlateStep=($axialTopology-eq'exit_aperture_plate_potential_step')
  # A connector-owned terminal remains serialized in the integration binding
  # but is not part of a standalone multipole PA or handoff plane.
  $hasDownstreamTerminal=(($design.PSObject.Properties.Name-contains'downstream_terminal') -and
    $design.downstream_terminal.upstream_terminal_electrode_present -eq $true)
  $handoffPlaneMm=if($hasDownstreamTerminal){
    [double]$design.downstream_terminal.surface_plane_z_mm
  }else{[double]$interfaces.exit.handoff_plane_z_mm}
  $censusPlaneMm=if($hasDownstreamTerminal){
    $handoffPlaneMm+[double]$design.downstream_terminal.electrode_thickness_mm
  }else{[double]$interfaces.exit.census_plane_z_mm}
  $censusRadius=if($enclosure.PSObject.Properties.Name-contains'physical_detector_radius_mm'){
    [double]$enclosure.physical_detector_radius_mm
  }else{[double]$interfaces.exit.aperture_radius_mm}
  $rectangular=([string]$enclosure.model-eq'rectangular_reference_enclosure_v1')
  $origin=if($rectangular){0}else{[double]$enclosure.shield_outer_radius_mm}
  $zShift=if($rectangular){0}else{-[double]$enclosure.vacuum_z_min_mm}
  if($rectangular){
    $entranceVoltage=[double]$static.entrance_aperture_plate_and_connector_V
    $exitVoltage=[double]$static.exit_outer_enclosure_and_connector_V
    $physicalDetectorVoltage=[double]$static.physical_detector_V
  }else{
    $entranceVoltage=[double]$static.shield_entrance_outer_endcap_aperture_plate_connector_V
    $exitVoltage=[double]$static.exit_outer_endcap_aperture_plate_connector_V
    $physicalDetectorVoltage=$exitVoltage
  }
  $segmentedLua='';$groundElectrodeId=3;$outputElectrodeId=4
  $entranceReferenceElectrodeId=0;$entranceReferenceVoltage=$entranceVoltage
  $entrancePlateElectrodeId=0;$entrancePlateVoltage=$entranceVoltage
  $physicalDetectorElectrodeId=if($rectangular){5}else{4}
  if($hasDownstreamTerminal){
    $axialDc=$design.axial_dc
    $entries=@($axialDc.rod_electrodes|ForEach-Object{
      $rodId=[int]$_.electrode_id
      $rodGroup=if($rodId%2-eq 1){1}else{2}
      if($segmentedRodGeometry){
        $segmentMatch=@($design.segmentation.segmented_rod_array.electrodes|Where-Object{
          [int]$_.electrode_id-eq$rodId
        })
        $rodGroups=@($segmentMatch|ForEach-Object{[int]$_.electrode_group}|Select-Object -Unique)
        if($segmentMatch.Count -eq 0 -or $rodGroups.Count -ne 1){
          throw "Axial-DC rod electrode group is missing or inconsistent: $rodId"
        }
        $rodGroup=[int]$rodGroups[0]
      }
      "{electrode_id=$rodId,electrode_group=$rodGroup,common_mode_v=$([double]$_.potential_V)}"
    })
    $segmentedLua="segmented_rod_electrodes={$($entries -join ',')},"
    $maxRodElectrode=($axialDc.rod_electrodes|Measure-Object -Property electrode_id -Maximum).Maximum
    $groundElectrodeId=[int]$maxRodElectrode+1
    $outputElectrodeId=$groundElectrodeId+1
    $physicalDetectorElectrodeId=$outputElectrodeId+1
    $entranceReferenceElectrodeId=$physicalDetectorElectrodeId+1
    $entrancePlateElectrodeId=$entranceReferenceElectrodeId+1
    $entranceVoltage=[double]$axialDc.upstream_shield_potential_V
    $entranceReferenceVoltage=[double]$axialDc.entrance_reference_sleeve.potential_V
    $entrancePlateVoltage=[double]$axialDc.entrance_plate_potential_V
    $exitVoltage=[double]$axialDc.terminal_electrode_potential_V
    $physicalDetectorVoltage=$exitVoltage
  }elseif($segmentedRodGeometry){
    $segments=$design.segmentation.segmented_rod_array
    # One PA electrode may consist of several physical rods in the same
    # segment.  The RF kernel receives electrode voltages, not rod geometry;
    # collapse such identical electrode records while rejecting any ambiguous
    # group or common-mode assignment.
    $electrodesById=[ordered]@{}
    foreach($electrode in @($segments.electrodes)){
      $electrodeId=[int]$electrode.electrode_id
      $candidate=[pscustomobject]@{
        electrode_id=$electrodeId
        electrode_group=[int]$electrode.electrode_group
        common_mode_V=[double]$electrode.common_mode_V
      }
      if($electrodesById.Contains($electrodeId)){
        # OrderedDictionary's untyped numeric indexer means “ordinal slot”,
        # not the physical PA electrode ID.  Force the object-key overload.
        $existing=$electrodesById[[object]$electrodeId]
        if($existing.electrode_group-ne$candidate.electrode_group -or
          $existing.common_mode_V-ne$candidate.common_mode_V){
          throw "Segmented RF electrode $electrodeId has inconsistent group or common-mode voltage."
        }
        continue
      }
      $electrodesById.Add($electrodeId,$candidate)
    }
    $entries=@($electrodesById.Values|Sort-Object electrode_id|ForEach-Object{
      "{electrode_id=$([int]$_.electrode_id),electrode_group=$([int]$_.electrode_group),common_mode_v=$([double]$_.common_mode_V)}"
    })
    $segmentedLua="segmented_rod_electrodes={$($entries -join ',')},"
    $groundElectrodeId=2*[int]$segments.segment_count+1;$outputElectrodeId=$groundElectrodeId+1
    $physicalDetectorElectrodeId=$outputElectrodeId+1
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
      fingerprint_sha256=$paBasisFingerprint
      authorized=$paBasisReuseAuthorized
      action=$(if(-not$paBasisReuseAuthorized){'independent_refine'}elseif($paBasisReuse){'reuse'}elseif($paBasisRequireExisting){'required_reuse'}else{'publish'})
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
  $runInputs=[ordered]@{project_registry=$registry;project_descriptor=$descriptor;design_profiles=$profiles;
    engineering_budget=$engineeringBudget;resolved_resource_budget=$resolvedResourceBudget;
    design_profile_resolution=$profileResolution;design_request=$request;design_variables=$variables;
    optimization_envelope=$envelope;operating_mode_registry=$modeRegistry;
    multipole_resolved_design=$resolved;particle_source=$particleSource;
    particle_source_metadata=$sourceMetadata;particle_source_family=$sourceFamily;
    solver_numerics=$numerics;simion_grid_audit=$gridAudit;code_inventory=$codeInventory;
    simion_execution_batch_plan=$batchPlan;
    evidence_contract=$evidence;simion_gem=$gem;simion_fly2=$fly2;
    simion_rf_drive_kernel=$rfDriveKernelLua;
    resolved_runtime_profile=$resolvedRuntimeProfile;
    simion_layout_template_resolution=$templateResolution;
    simion_layout_template_registry=$templateRegistryInput;
    simion_layout_registration_manifest=$templateRegistrationManifest;
    simion_layout_template_iob=$templateIob;simion_layout_template_con=$templateCon}
  if($terminalRegistry){$runInputs.downstream_terminal_profiles=$terminalRegistry}
  if($paBasisCacheManifestInput){
    $runInputs.simion_pa_basis_cache_manifest=$paBasisCacheManifestInput
  }
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
  [ordered]@{schema_version=2;role='multipole_resolved_simion_run_config';run_id=$RunId;project=$ProjectId;
    mode='resolved_design_transport';project_root=$profile.project_root;
    artifact_retention=[ordered]@{policy_version=1;class=$RetentionClass;
      reason=$(if($RetentionClass-eq'compact'){$null}else{$RetentionReason})};
    provenance=$provenance;inputs=$runInputs;
    parameters=[ordered]@{model_level='L3';runtime_profile_id=$RuntimeProfileId;design_profile_id=$DesignProfileId;
      experiment_id=$(if($campaignSelection){[string]$campaignSelection.experiment_id}else{$null});
      case_set=$CaseSet;
      operating_mode_id=$modeId;
      operating_point_id=$(if($sourceFamily){$OperatingPointId}else{$null});
      reference_comsol_run_id=$ReferenceComsolRunId};
    formal_gate_passed=$false}|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $runConfig -Encoding UTF8

  $resourceUsage=Join-Path $resultDir 'resource_usage.json'
  function Invoke-SimionStep([string]$name,[string[]]$arguments){
    $stdout=Join-Path $logDir "simion_stdout__$name.txt";$stderr=Join-Path $logDir "simion_stderr__$name.txt"
    $step=Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $resolvedResourceBudget `
      -RunDir $runDir -UsagePath $resourceUsage -FilePath $simion -WorkingDirectory $solverDir `
      -ArgumentList $arguments -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    if($step.resource_budget_exceeded){
      $script:resourceBudgetExceeded=$true
      throw "SIMION $name resource budget exceeded."
    }
    if($step.exit_code-ne 0){throw "SIMION $name failed with exit code $($step.exit_code)."}
  }
  if($paBasisReuse){
    foreach($basisFile in $paBasisFiles){
      $destination=Join-Path $solverDir $basisFile.name
      # SIMION's --remove-pas can mutate or remove the solver copy.  A hard
      # link would therefore corrupt the content-addressed cache itself.
      Copy-Item -LiteralPath $basisFile.path -Destination $destination
    }
    Write-Output "MULTIPOLE_SIMION_PA_BASIS=REUSE FINGERPRINT=$paBasisFingerprint"
  }else{
    Invoke-SimionStep 'gem2pa' @('--nogui','--noprompt','gem2pa','quad_monolithic.gem','quad_monolithic.pa#')
    Invoke-SimionStep 'refine' @('--nogui','--noprompt','refine','quad_monolithic.pa#')
    if($paBasisReuseAuthorized){
    New-Item -ItemType Directory -Force -Path $paBasisCacheRoot|Out-Null
    $staging=Join-Path $paBasisCacheRoot ('.staging_'+$paBasisFingerprint+'_'+[guid]::NewGuid())
    New-Item -ItemType Directory -Path $staging|Out-Null
    try{
      $records=@()
      foreach($source in @(Get-ChildItem -LiteralPath $solverDir -File|Where-Object{
        $_.Name-match'^quad_monolithic\.pa(?:#|-surf|\d+)$'
      }|Sort-Object Name)){
        $destination=Join-Path $staging $source.Name
        # The cache must be physically independent before fly is allowed to
        # apply --remove-pas to its solver-local PA family.
        Copy-Item -LiteralPath $source.FullName -Destination $destination
        $records+=[ordered]@{name=$source.Name;bytes=$source.Length;
          sha256=(Get-FileHash -LiteralPath $source.FullName -Algorithm SHA256).Hash}
      }
      if($records.Count-lt 3){throw 'Refined SIMION PA basis is incomplete.'}
      $stagingManifest=Join-Path $staging 'manifest.json'
      [ordered]@{schema_version=1;role='multipole_simion_pa_basis_cache';
        fingerprint_sha256=$paBasisFingerprint;provider_run_id=$RunId;
        identity=$paBasisIdentity;files=$records}|ConvertTo-Json -Depth 8|
        Set-Content -LiteralPath $stagingManifest -Encoding UTF8
      if(Test-Path -LiteralPath $paBasisCacheDir){
        throw "SIMION PA-basis cache destination appeared during publication: $paBasisCacheDir"
      }
      Move-Item -LiteralPath $staging -Destination $paBasisCacheDir
      $publishedPaBasisManifest=$paBasisCacheManifest
      Get-VerifiedPaBasisFiles -ManifestPath $publishedPaBasisManifest `
        -ExpectedFingerprint $paBasisFingerprint|Out-Null
      Write-Output "MULTIPOLE_SIMION_PA_BASIS=PUBLISH FINGERPRINT=$paBasisFingerprint"
    }catch{
      $resolvedStaging=[IO.Path]::GetFullPath($staging)
      if($resolvedStaging.StartsWith(
        $paBasisCacheRoot+[IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
      )){Remove-Item -LiteralPath $resolvedStaging -Recurse -Force -ErrorAction SilentlyContinue}
      throw
    }
    }
  }
  Copy-VerifiedRunInput `
    -Source (Join-Path $codeRoot 'common\multipole\build_simion_runtime_iob.lua') `
    -Destination (Join-Path $solverDir 'build_simion_runtime_iob.lua')|Out-Null
  Invoke-SimionStep 'build_runtime_iob' @(
    '--nogui','--noprompt','lua','build_simion_runtime_iob.lua',
    'quad_monolithic.iob','multipole_runtime_program.lua','quad_monolithic.fly2')
  Start-Sleep -Milliseconds 500

  function Invoke-TransportCase([string]$name,[int]$rfScale,[int]$axialScale){
    $caseState=Join-Path $resultDir "particle_states__$name.csv"
    $caseTrajectory=Join-Path $resultDir "trajectory_samples__$name.csv"
    $caseSummary=Join-Path $resultDir "simion_summary__$name.json"
    # The registered Workbench transform maps GEM +z to flight +x.  Axial
    # sampling and the census-marker threshold must therefore use GEM dz.
    $surfaceToleranceMm=[Math]::Max(1e-6*$resolvedCellMmZ,1e-9)
    $handoffApertureLua=if($hasDownstreamTerminal){
      $terminalAperture=$design.downstream_terminal.aperture
      if([string]$terminalAperture.shape -eq 'rectangular'){
        "handoff_aperture={shape=`"rectangular`",width_mm=$([double]$terminalAperture.width_mm),height_mm=$([double]$terminalAperture.height_mm)},"
      }elseif([string]$terminalAperture.shape -eq 'circular'){
        "handoff_aperture={shape=`"circular`",radius_mm=$([double]$terminalAperture.radius_mm)},"
      }else{throw 'Resolved downstream terminal aperture shape is unsupported.'}
    }else{''}
    $batchRuns=@()
    foreach($batch in $simionBatches){
      $suffix=("batch_{0:D2}" -f [int]$batch.index)
      $batchState=if($simionBatches.Count-eq 1){$caseState}else{Join-Path $resultDir "particle_states__$name`__$suffix.csv"}
      $batchTrajectory=if($simionBatches.Count-eq 1){$caseTrajectory}else{Join-Path $resultDir "trajectory_samples__$name`__$suffix.csv"}
      $batchSummary=if($simionBatches.Count-eq 1){$caseSummary}else{Join-Path $resultDir "simion_summary__$name`__$suffix.json"}
      $luaConfig=if($simionBatches.Count-eq 1){Join-Path $inputDir "simion_config__$name.lua"}else{Join-Path $inputDir "simion_config__$name`__$suffix.lua"}
      @"
return {iob=[[$(Join-Path $solverDir 'quad_monolithic.iob')]], fly2=[[$($batch.fly2)]], source_states=dofile([[$($batch.states)]]),
trajectory_csv=[[$batchTrajectory]], particle_state_csv=[[$batchState]], summary_json=[[$batchSummary]],
mode="resolved_design_transport", operating_point="$name", parent_resolved_design_sha256="$resolvedHash",
trajectory_quality=$TrajectoryQuality, rf_steps_per_period=$RfStepsPerPeriod, waveform="$($drive.waveform)",
rf_peak_v=$($drive.rf_amplitude_V_zero_to_peak_per_group), rf_scale=$rfScale, axial_scale=$axialScale,
scale_static_boundaries=$($exitAperturePlateStep.ToString().ToLowerInvariant()),
dc_amplitude_v=$($drive.dc_amplitude_V_per_group), frequency_hz=$($drive.frequency_Hz), phase_rad=$($drive.phase_rad),
axis_voltage_v=$($drive.common_mode_offset_V), entrance_voltage_v=$entranceVoltage,
exit_voltage_v=$exitVoltage, physical_detector_voltage_v=$physicalDetectorVoltage,
has_electrode_4=true, has_electrode_5=$($rectangular.ToString().ToLowerInvariant()),
$segmentedLua ground_electrode_id=$groundElectrodeId, ground_reference_v=$entranceVoltage,
output_electrode_id=$outputElectrodeId, output_reference_v=$exitVoltage,
physical_detector_electrode_id=$physicalDetectorElectrodeId,
entrance_reference_electrode_id=$entranceReferenceElectrodeId,
entrance_reference_v=$entranceReferenceVoltage,
entrance_plate_electrode_id=$entrancePlateElectrodeId,
entrance_plate_v=$entrancePlateVoltage,
maximum_time_us=$MaximumTimeUs, trajectory_plane_step_mm=$resolvedCellMmZ,
rod_z_min_mm=$($geometry.rod_z_min), rod_z_max_mm=$($geometry.rod_z_max),
rod_exit_plane_mm=$($geometry.rod_z_max), handoff_plane_mm=$handoffPlaneMm,
    census_plane_mm=$censusPlaneMm, $handoffApertureLua
    numerical_census_marker_threshold_mm=$($censusPlaneMm-2*$resolvedCellMmZ-$surfaceToleranceMm),
census_radius_mm=$censusRadius, radial_escape_radius_mm=$($enclosure.working_region_radius_mm),
numerical_census_marker_is_handoff=false, axial_axis="x", origin_x_mm=$zShift, origin_y_mm=$(-$origin),
origin_z_mm=$origin, backward_escape_plane_mm=$($enclosure.vacuum_z_min_mm)}
"@|Set-Content -LiteralPath $luaConfig -Encoding ASCII
      $batchRuns+=[pscustomobject]@{batch=$batch;state=$batchState;trajectory=$batchTrajectory;
        summary=$batchSummary;lua_config=$luaConfig;fly2=[string]$batch.fly2}
    }
    $flyArguments=@('--nogui','--noprompt','fly','--remove-pas=3','--trajectory-quality',
      [string]$TrajectoryQuality,'--programs','1','--retain-trajectories','0','--adjustable',
      "transport_rf_steps_per_period=$RfStepsPerPeriod",(Join-Path $solverDir 'quad_monolithic.iob'))
    if($script:resourceCalibrationRequired){
      if($batchRuns.Count-ne 1){throw 'Unknown resource identity must start from one formal SIMION batch.'}
      $firstSpecification=[pscustomobject]@{
        name="fly__$name`__batch_1";file_path=$simion
        argument_list=($flyArguments[0..5]+@('--particles',$batchRuns[0].fly2)+$flyArguments[6..($flyArguments.Count-1)])
        working_directory=$solverDir
        stdout=(Join-Path $logDir "simion_stdout__fly__$name`__batch_1.txt")
        stderr=(Join-Path $logDir "simion_stderr__fly__$name`__batch_1.txt")
        environment=@{MULTIPOLE_SIMION_RUN_CONFIG_LUA=$batchRuns[0].lua_config;MULTIPOLE_SIMION_RF_DRIVE_KERNEL_LUA=$rfDriveKernelLua}
        scheduler_batch=[pscustomobject]@{index=[int]$batchRuns[0].batch.index;total_batches='OBSERVATION_ONLY';particle_id_min=[int]$batchRuns[0].batch.particle_id_min;particle_id_max=[int]$batchRuns[0].batch.particle_id_max;count=([int]$batchRuns[0].batch.particle_id_max-[int]$batchRuns[0].batch.particle_id_min+1)}
      }
      $formalObservation=Start-ObservedFormalProcess -DispatchPlanPath $dispatchPlan `
        -ProcessSpecification $firstSpecification
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
        & $python -m common.simion.particle_batching --from-dispatch-plan $dispatchPlan `
          --output $batchPlan | Out-Null
        if($LASTEXITCODE-ne 0){throw 'SIMION formal-first particle batch planning failed.'}
        $updatedBatchPlan=Get-Content -LiteralPath $batchPlan -Raw -Encoding UTF8|ConvertFrom-Json
        Set-SimionBatchesFromPlan -Plan $updatedBatchPlan
        $script:dispatchPlanDocument=$updatedDispatch
        $script:batchPlanDocument=$updatedBatchPlan
        $script:executionBatching=[pscustomobject]@{dispatch='single_wave_parallel';
          batch_count=[int]$updatedDispatch.waves[0].batch_count}
        $script:resourceCalibrationRequired=$false
        $formalObservation.process_record.specification.scheduler_batch=[pscustomobject]@{index=[int]$batchRuns[0].batch.index;total_batches=[int]$batchRuns.Count;particle_id_min=[int]$batchRuns[0].batch.particle_id_min;particle_id_max=[int]$batchRuns[0].batch.particle_id_max;count=([int]$batchRuns[0].batch.particle_id_max-[int]$batchRuns[0].batch.particle_id_min+1)}
        $script:existingFormalProcessRecords=@($formalObservation.process_record)
        # The first formal worker began before the replan, when the run had a
        # single unsuffixed output name.  Keep that completed-or-live output
        # identity so the recursive, multi-batch invocation can publish it as
        # canonical batch_01 before merging.  The first worker is formal work,
        # not a disposable resource probe.
        $script:retainedFormalBatchOutputs[$name]=[pscustomobject]@{
          state=$batchRuns[0].state;trajectory=$batchRuns[0].trajectory
          summary=$batchRuns[0].summary
        }
      }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
      return Invoke-TransportCase $name $rfScale $axialScale
    }
    if($batchRuns.Count-eq 1-and$script:existingFormalProcessRecords.Count-eq 0){
      $env:MULTIPOLE_SIMION_RUN_CONFIG_LUA=$batchRuns[0].lua_config
      $env:MULTIPOLE_SIMION_RF_DRIVE_KERNEL_LUA=$rfDriveKernelLua
      try{Invoke-SimionStep "fly__$name" ($flyArguments[0..5]+@('--particles',$batchRuns[0].fly2)+$flyArguments[6..($flyArguments.Count-1)])}
      finally{Remove-Item Env:MULTIPOLE_SIMION_RUN_CONFIG_LUA -ErrorAction SilentlyContinue;Remove-Item Env:MULTIPOLE_SIMION_RF_DRIVE_KERNEL_LUA -ErrorAction SilentlyContinue}
    }else{
      $specifications=@($batchRuns|ForEach-Object{
        [pscustomobject]@{name="fly__$name`__batch_$($_.batch.index)";file_path=$simion;
          argument_list=($flyArguments[0..5]+@('--particles',$_.fly2)+$flyArguments[6..($flyArguments.Count-1)]);
          working_directory=$solverDir;stdout=(Join-Path $logDir "simion_stdout__fly__$name`__batch_$($_.batch.index).txt");
          stderr=(Join-Path $logDir "simion_stderr__fly__$name`__batch_$($_.batch.index).txt");
          environment=@{MULTIPOLE_SIMION_RUN_CONFIG_LUA=$_.lua_config;MULTIPOLE_SIMION_RF_DRIVE_KERNEL_LUA=$rfDriveKernelLua}
          scheduler_batch=[pscustomobject]@{index=[int]$_.batch.index;total_batches=[int]$batchRuns.Count;particle_id_min=[int]$_.batch.particle_id_min;particle_id_max=[int]$_.batch.particle_id_max;count=([int]$_.batch.particle_id_max-[int]$_.batch.particle_id_min+1)}}
      })
      if($script:existingFormalProcessRecords.Count-gt 0){
        $specifications=@($specifications|Select-Object -Skip 1)
      }
      $wave=Invoke-ResourceBudgetedProcesses -DispatchPlanPath $dispatchPlan `
        -RunDir $runDir -UsagePath $resourceUsage `
        -ProcessSpecifications $specifications `
        -ExistingProcessRecords $script:existingFormalProcessRecords
      if($wave.resource_budget_exceeded){$script:resourceBudgetExceeded=$true;throw "SIMION $name batch wave resource budget exceeded."}
      $failed=@($wave.processes|Where-Object{$_.exit_code-ne 0})
      if($failed.Count-ne 0){throw "SIMION $name batch wave failed: $($failed.name -join ',')"}
    }
    if($batchRuns.Count-gt 1){
      if($script:retainedFormalBatchOutputs.ContainsKey($name)){
        $retained=$script:retainedFormalBatchOutputs[$name]
        $firstBatch=$batchRuns[0]
        foreach($kind in @('state','summary')){
          $source=[string]$retained.$kind
          $destination=[string]$firstBatch.$kind
          if(-not(Test-Path -LiteralPath $source)){throw "SIMION $name retained first formal $kind output is missing."}
          Move-Item -LiteralPath $source -Destination $destination -Force
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
          @{output=$caseTrajectory;property='trajectory';required=$false}
        )){
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
    return Get-Content -LiteralPath $caseSummary -Raw -Encoding UTF8|ConvertFrom-Json
  }

  $control=$null;$controlName=$null
  if($segmented -or $exitAperturePlateStep){
    if($exitAperturePlateStep){
      $primaryName='exit_aperture_plate_acceleration_rf_on';$controlName='zero_exit_aperture_plate_drop_rf_on'
    }else{
      $primaryName='axial_acceleration_rf_on';$controlName='zero_axial_drop_rf_on'
    }
    $primary=Invoke-TransportCase $primaryName 1 1
    if($CaseSet-eq'primary_and_zero_axial_control'){
      $control=Invoke-TransportCase $controlName 1 0
      $metrics=Join-Path $resultDir $(if($exitAperturePlateStep){'exit_aperture_plate_acceleration_metrics.json'}else{'axial_acceleration_metrics.json'})
      Push-Location $codeRoot
      try{
        $env:PYTHONPATH=$codeRoot
        & $python -m common.multipole.analyze_simion_axial_acceleration `
          --accelerated-state (Join-Path $resultDir "particle_states__$primaryName.csv") `
          --control-state (Join-Path $resultDir "particle_states__$controlName.csv") `
          --resolved-contract $resolved --output $metrics
        if($LASTEXITCODE-ne 0){throw 'SIMION axial-drive metrics analysis failed.'}
      }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
    }elseif($CaseSet-eq'primary_and_rf_off_energy_control'){
      $controlName=$(if($exitAperturePlateStep){'exit_aperture_plate_acceleration_rf_off'}else{'axial_acceleration_rf_off'})
      $control=Invoke-TransportCase $controlName 0 1
      $metrics=Join-Path $resultDir 'rf_off_energy_control_metrics.json'
      Push-Location $codeRoot
      try{
        $env:PYTHONPATH=$codeRoot
        & $python -m common.multipole.analyze_simion_transport_metrics --metric-kind rf_off_energy_control `
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
        & $python -m common.multipole.analyze_simion_transport_metrics --metric-kind primary `
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
        & $python -m common.multipole.analyze_simion_transport_metrics --metric-kind base_paired `
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
        & $python -m common.multipole.analyze_simion_transport_metrics --metric-kind base_primary `
          --project-id $ProjectId --parent-resolved-design-sha256 $resolvedHash --case-set $CaseSet `
          --primary-case-id $primaryName --primary-summary (Join-Path $resultDir "simion_summary__$primaryName.json") --output $metrics
        if($LASTEXITCODE-ne 0){throw 'SIMION primary transport metrics analysis failed.'}
      }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
    }
  }
  $exitStatePlot=Join-Path $resultDir 'exit_state_diagnostics.png'
  $exitStatePlotManifest=Join-Path $resultDir 'exit_state_diagnostics.json'
  $primaryState=Join-Path $resultDir "particle_states__$primaryName.csv"
  Push-Location $codeRoot
  try{
    $env:PYTHONPATH=$codeRoot
    $exitStatePlotLabel=$ProjectId.Replace('_',' ')
    & $python -m common.multipole.exit_state_plot `
      --series "$exitStatePlotLabel=$primaryState=$RunId" `
      --output $exitStatePlot --manifest $exitStatePlotManifest `
      --title "$exitStatePlotLabel exit-state diagnostic" `
      --purpose 'Regular single-run multipole exit-state diagnostic' `
      --repo-root $repoRoot
    if($LASTEXITCODE-ne 0){throw 'SIMION exit-state diagnostic plot failed.'}
  }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
  $qualification='UNQUALIFIED';$evaluation=Join-Path $resultDir 'evidence_evaluation.json'
  if($evidence){
    Push-Location $codeRoot
    try{
      $env:PYTHONPATH=$codeRoot
      & $python -m common.multipole.evaluate_transport_evidence --metrics $metrics --evidence $evidence `
        --project-id $ProjectId --design-profile-id $DesignProfileId --output $evaluation
      $evidenceExit=$LASTEXITCODE
    }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
    if($evidenceExit-ne 0){throw 'SIMION evidence contract gate failed.'}
    $qualification='PASS'
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
  [ordered]@{schema_version=1;role='multipole_simion_finite_3d_transport_summary';status='success';
    qualification_status=$qualification;project_id=$ProjectId;design_profile_id=$DesignProfileId;
    parent_resolved_design_sha256=$resolvedHash;primary_transmission=$primaryTransmission;
    case_set=$CaseSet;
    control_transmission=$controlTransmission;
    model_level='L3';formal_gate_passed=$false}|
    ConvertTo-Json -Depth 5|Set-Content -LiteralPath $summary -Encoding UTF8
  $retentionActions=Apply-RunArtifactRetention -Python $python -RepoRoot $manifestRepoRoot `
    -RunConfig $runConfig
  if(-not(Complete-ResourceUsage -ResolvedBudgetPath $resolvedResourceBudget `
    -RunDir $runDir -UsagePath $resourceUsage)){
    $resourceBudgetExceeded=$true
    throw 'SIMION compact final retained-byte budget exceeded.'
  }
  $resourceProfile=$null
  if($null-ne$dispatchPlan-and$resourceIdentityWasUnknown){
    $resourceProfile=Join-Path $resultDir 'simion_resource_profile.json'
    Push-Location $codeRoot
    try{
      $env:PYTHONPATH=$codeRoot
      & $python -m common.simion.resource_profile publish --run-id $RunId `
        --resource-usage $resourceUsage --dispatch-plan $dispatchPlan --output $resourceProfile
      $resourceProfileExit=$LASTEXITCODE
    }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
    if($resourceProfileExit-ne 0){throw 'SIMION resource profile publication failed.'}
  }
  $outputs=@($summary,$metrics,$resourceUsage,$exitStatePlot,$exitStatePlotManifest,
    (Join-Path $solverDir 'quad_monolithic.pa0'),
    (Join-Path $solverDir 'quad_monolithic.iob'),
    (Join-Path $solverDir 'quad_monolithic.con'),$gem,$fly2,
    (Join-Path $resultDir "simion_summary__$primaryName.json"),
    (Join-Path $resultDir "particle_states__$primaryName.csv"),
    (Join-Path $resultDir "trajectory_samples__$primaryName.csv"),
    (Join-Path $resultDir "particle_state_contract__$primaryName.json"))
  if($null-ne$control){
    $outputs+=@(
      (Join-Path $resultDir "simion_summary__$controlName.json"),
      (Join-Path $resultDir "particle_states__$controlName.csv"),
      (Join-Path $resultDir "trajectory_samples__$controlName.csv"),
      (Join-Path $resultDir "particle_state_contract__$controlName.json")
    )
  }
  $outputs+=@(Get-ChildItem -LiteralPath $logDir -Recurse -File|Select-Object -ExpandProperty FullName)
  if(Test-Path -LiteralPath $evaluation){$outputs+=$evaluation}
  if($resourceProfile){$outputs+=$resourceProfile}
  if($publishedPaBasisManifest){$outputs+=$publishedPaBasisManifest}
  $outputs=@($outputs|Where-Object{Test-Path -LiteralPath $_ -PathType Leaf})
  $outputs+=$retentionActions
  Write-VerifiedRunManifest -Python $python -RepoRoot $manifestRepoRoot -RunConfig $runConfig `
    -Status success -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
  $hostExecutionOutcome='success'
  Write-Output "MULTIPOLE_SIMION_RESOLVED=PASS PROJECT=$ProjectId PROFILE=$DesignProfileId RUN_ID=$RunId PARENT_SHA256=$resolvedHash QUALIFICATION=$qualification"
}catch{
  $hostExecutionOutcome=if($resourceBudgetExceeded){'interrupted'}else{'failed'}
  Complete-FailedRun -Python $python -RepoRoot $manifestRepoRoot -RunConfig $runConfig -Summary $summary `
    -SummaryRole 'multipole_simion_finite_3d_transport_summary' -Reason $_.Exception.Message `
    -Software @('SIMION 2020','Python 3.11') `
    -Status $(if($resourceBudgetExceeded){'interrupted'}else{'failed'}) `
    -FailureClass $(if($resourceBudgetExceeded){'resource_budget_exceeded'}else{''}) `
    -ResourceUsagePath $(if($null-ne(Get-Variable resourceUsage -ErrorAction SilentlyContinue)){$resourceUsage}else{''})
  throw
}finally{
  Remove-Item -LiteralPath $budgetPreflight -Force -ErrorAction SilentlyContinue
  try { Remove-RunPackageExecutionAlias -Package $package } catch {
    Write-Warning "Could not remove short execution alias after SIMION run: $($_.Exception.Message)"
  }
  Exit-HostExecutionLease -Lease $hostExecutionLease -Outcome $hostExecutionOutcome -RunId $RunId
}
