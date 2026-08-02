$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

function Assert-MultipoleMeshBuildReport {
  param(
    [Parameter(Mandatory=$true)][string]$Path,
    [object]$MaximumMeshCells=$null
  )
  if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){
    throw 'COMSOL mesh-build report is missing.'
  }
  $content=Get-Content -LiteralPath $Path -Raw -Encoding UTF8
  foreach($token in @(
    'STOP_STAGE=mesh_build',
    'FIELD_PHYSICS_CREATED=0',
    'FIELD_STUDIES_CREATED=0',
    'FIELD_SOLUTIONS_CREATED=0',
    'PARTICLE_PHYSICS_CREATED=0',
    'PARTICLE_STUDIES_CREATED=0',
    'MESH_FEATURE_ROD_BOUNDARY_SIZE_PRESENT=1',
    'MESH_SWEPT_TETRAHEDRAL_OVERLAP_DOMAIN_COUNT=0',
    'MESH_VACUUM_UNCOVERED_DOMAIN_COUNT=0',
    'MESH_NONVACUUM_PARTITION_DOMAIN_COUNT=0',
    'MESH_VACUUM_VOLUME_STATUS=MEASURED',
    'MESH_BUILD_DIAGNOSTIC=PASS',
    'STATUS=PASS'
  )){
    if($content-notmatch("(?m)^$([regex]::Escape($token))\r?$")){
      throw "COMSOL mesh-build report is missing required terminal token: $token"
    }
  }
  foreach($name in @(
    'MESH_VACUUM_SELECTION_ENTITY_COUNT',
    'MESH_VACUUM_VOLUME_MM3',
    'MESH_VACUUM_MIN_QUALITY'
  )){
    $matches=[regex]::Matches(
      $content,
      "(?m)^$([regex]::Escape($name))=(?<value>[^\r\n]+)\r?$"
    )
    if($matches.Count-ne 1){
      throw "COMSOL mesh-build report must contain exactly one $name token."
    }
    $value=[double]0
    if(-not[double]::TryParse(
      $matches[0].Groups['value'].Value,
      [Globalization.NumberStyles]::Float,
      [Globalization.CultureInfo]::InvariantCulture,
      [ref]$value
    )-or[double]::IsNaN($value)-or[double]::IsInfinity($value)-or$value-le 0){
      throw "COMSOL mesh-build report has an invalid positive $name value."
    }
  }
  if($null-eq$MaximumMeshCells){return $null}
  return Assert-MultipoleMeshCellBudgetReport -Path $Path -MaximumMeshCells $MaximumMeshCells
}

function Assert-MultipoleMeshCellBudgetReport {
  param(
    [Parameter(Mandatory=$true)][string]$Path,
    [Parameter(Mandatory=$true)][int64]$MaximumMeshCells
  )
  if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){
    throw 'COMSOL report is missing for the mesh-cell budget check.'
  }
  $content=Get-Content -LiteralPath $Path -Raw -Encoding UTF8
  $matches=[regex]::Matches($content,'(?m)^MESH_GLOBAL_ELEMENTS=(?<value>[^\r\n]+)\r?$')
  if($matches.Count-ne 1){
    throw 'COMSOL report must contain exactly one MESH_GLOBAL_ELEMENTS token when maximum_mesh_cells is declared.'
  }
  $meshCells=[int64]0
  if(-not[int64]::TryParse(
    $matches[0].Groups['value'].Value,
    [Globalization.NumberStyles]::None,
    [Globalization.CultureInfo]::InvariantCulture,
    [ref]$meshCells
  )-or$meshCells-le 0){
    throw 'COMSOL report has an invalid positive-integer MESH_GLOBAL_ELEMENTS value.'
  }
  if($meshCells-gt[int64]$MaximumMeshCells){
    $failure=[InvalidOperationException]::new(
      "COMSOL mesh cell budget exceeded: MESH_GLOBAL_ELEMENTS=$meshCells maximum_mesh_cells=$MaximumMeshCells"
    )
    $failure.Data['limit_name']='maximum_mesh_cells'
    $failure.Data['measured_value']=$meshCells
    throw $failure
  }
  return $meshCells
}

function Assert-MultipoleFieldSolveReport {
  param([Parameter(Mandatory=$true)][string]$Path)
  if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){
    throw 'COMSOL field-solve report is missing.'
  }
  $content=Get-Content -LiteralPath $Path -Raw -Encoding UTF8
  foreach($token in @(
    'CHECKPOINT=STATIONARY_FIELDS_COMPLETE',
    'STOP_STAGE=field_solve',
    'PARTICLE_PHYSICS_CREATED=0',
    'PARTICLE_STUDIES_CREATED=0',
    'FIELD_SOLVE_DIAGNOSTIC=PASS',
    'STATUS=PASS'
  )){
    if($content-notmatch("(?m)^$([regex]::Escape($token))\r?$")){
      throw "COMSOL field-solve report is missing required terminal token: $token"
    }
  }
  $backendMatches=[regex]::Matches(
    $content,'(?m)^STATIONARY_LINEAR_SOLVER_BACKEND=(?<value>[^\r\n]+)\r?$'
  )
  if($backendMatches.Count-ne 1-or
    $backendMatches[0].Groups['value'].Value-notin@('MUMPS','PARDISO','CG_AMG')){
    throw 'COMSOL field-solve report has an invalid stationary solver backend.'
  }
  $orderMatches=[regex]::Matches(
    $content,'(?m)^ELECTRIC_POTENTIAL_ELEMENT_ORDER=(?<value>[^\r\n]+)\r?$'
  )
  if($orderMatches.Count-ne 1-or
    $orderMatches[0].Groups['value'].Value-notin@('LINEAR','QUADRATIC')){
    throw 'COMSOL field-solve report has an invalid electric-potential element order.'
  }
  $configurationTokens=[ordered]@{}
  foreach($name in @(
    'STATIONARY_CONTROL',
    'STATIONARY_RELATIVE_TOLERANCE',
    'STATIONARY_FULLY_COUPLED_LINEAR_SOLVER',
    'STATIONARY_MAX_LINEAR_ITERATIONS',
    'STATIONARY_LINEAR_ERROR_CHECK',
    'STATIONARY_CONVERGENCE_LOG'
  )){
    $matches=[regex]::Matches(
      $content,
      "(?m)^$([regex]::Escape($name))=(?<value>[^\r\n]+)\r?$"
    )
    if($matches.Count-ne 1){
      throw "COMSOL field-solve report must contain exactly one $name token."
    }
    $configurationTokens[$name]=$matches[0].Groups['value'].Value
  }
  $actualBackend=$backendMatches[0].Groups['value'].Value
  if($actualBackend-eq'CG_AMG'){
    $stationaryTolerance=[double]0
    $maximumLinearIterations=[int64]0
    if($configurationTokens.STATIONARY_CONTROL-ne'USER'-or
      -not[double]::TryParse(
        $configurationTokens.STATIONARY_RELATIVE_TOLERANCE,
        [Globalization.NumberStyles]::Float,
        [Globalization.CultureInfo]::InvariantCulture,
        [ref]$stationaryTolerance
      )-or[double]::IsNaN($stationaryTolerance)-or
      [double]::IsInfinity($stationaryTolerance)-or
      $stationaryTolerance-le 0-or$stationaryTolerance-ge 1-or
      -not[int64]::TryParse(
        $configurationTokens.STATIONARY_MAX_LINEAR_ITERATIONS,
        [ref]$maximumLinearIterations
      )-or$maximumLinearIterations-lt 1){
      throw 'COMSOL field-solve report has invalid governed CG-AMG convergence control.'
    }
    if($configurationTokens.STATIONARY_FULLY_COUPLED_LINEAR_SOLVER-ne'I1'-or
      $configurationTokens.STATIONARY_LINEAR_ERROR_CHECK-ne'ON'-or
      $configurationTokens.STATIONARY_CONVERGENCE_LOG-ne'DETAILED'){
      throw 'COMSOL field-solve report has invalid governed CG-AMG configuration.'
    }
    $linearErrorCheck='on'
  }else{
    if($configurationTokens.STATIONARY_CONTROL-ne'NOT_APPLICABLE'-or
      $configurationTokens.STATIONARY_RELATIVE_TOLERANCE-ne'NOT_APPLICABLE'-or
      $configurationTokens.STATIONARY_FULLY_COUPLED_LINEAR_SOLVER-ne'DDEF'-or
      $configurationTokens.STATIONARY_MAX_LINEAR_ITERATIONS-ne'NOT_APPLICABLE'-or
      $configurationTokens.STATIONARY_LINEAR_ERROR_CHECK-ne'NOT_APPLICABLE'-or
      $configurationTokens.STATIONARY_CONVERGENCE_LOG-ne'NOT_APPLICABLE'){
      throw 'COMSOL field-solve report has invalid governed direct-solver configuration.'
    }
    $stationaryTolerance=$null
    $maximumLinearIterations=$null
    $linearErrorCheck=$null
  }
  $counts=[ordered]@{}
  foreach($name in @(
    'FIELD_PHYSICS_CREATED',
    'FIELD_STUDIES_CREATED',
    'FIELD_SOLUTIONS_CREATED'
  )){
    $matches=[regex]::Matches(
      $content,
      "(?m)^$([regex]::Escape($name))=(?<value>[^\r\n]+)\r?$"
    )
    $value=[int64]0
    if($matches.Count-ne 1-or
      -not[int64]::TryParse($matches[0].Groups['value'].Value,[ref]$value)-or
      $value-le 0){
      throw "COMSOL field-solve report has an invalid positive $name value."
    }
    $counts[$name]=$value
  }
  $dofMatches=[regex]::Matches(
    $content,
    '(?m)^(?<name>DIFFERENTIAL_FIELD_DOF|STATIC_FIELD_DOF|STATIONARY_FIELD_DOF)=(?<value>[^\r\n]+)\r?$'
  )
  $dofs=[ordered]@{}
  foreach($match in $dofMatches){
    $value=[int64]0
    $name=$match.Groups['name'].Value
    if($dofs.Contains($name)-or
      -not[int64]::TryParse($match.Groups['value'].Value,[ref]$value)-or
      $value-le 0){
      throw "COMSOL field-solve report has an invalid positive $name value."
    }
    $dofs[$name]=$value
  }
  $stationaryOnly=$dofs.Count-eq 1-and$dofs.Contains('STATIONARY_FIELD_DOF')
  $pairedFields=$dofs.Count-eq 2-and
    $dofs.Contains('DIFFERENTIAL_FIELD_DOF')-and$dofs.Contains('STATIC_FIELD_DOF')
  if(-not($stationaryOnly-or$pairedFields)){
    throw 'COMSOL field-solve report has an incomplete field-DOF identity.'
  }
  $expectedFieldCounts=if($stationaryOnly){
    [ordered]@{
      FIELD_PHYSICS_CREATED=[int64]2
      FIELD_STUDIES_CREATED=[int64]1
      FIELD_SOLUTIONS_CREATED=[int64]1
    }
  }else{
    [ordered]@{
      FIELD_PHYSICS_CREATED=[int64]1
      FIELD_STUDIES_CREATED=[int64]2
      FIELD_SOLUTIONS_CREATED=[int64]2
    }
  }
  foreach($name in $counts.Keys){
    if($counts[$name]-ne$expectedFieldCounts[$name]){
      throw "COMSOL field-solve report has an invalid exact $name value."
    }
  }
  $solverEvidence=[ordered]@{}
  $fieldPrefixes=if($stationaryOnly){@('STATIONARY_FIELD')}else{
    @('DIFFERENTIAL_FIELD','STATIC_FIELD')
  }
  foreach($prefix in $fieldPrefixes){
    $iterationMatches=[regex]::Matches(
      $content,
      "(?m)^$([regex]::Escape($prefix))_ITERATIONS=(?<value>[^\r\n]+)\r?$"
    )
    $residualMatches=[regex]::Matches(
      $content,
      "(?m)^$([regex]::Escape($prefix))_FINAL_RESIDUAL=(?<value>[^\r\n]+)\r?$"
    )
    $sourceMatches=[regex]::Matches(
      $content,
      "(?m)^$([regex]::Escape($prefix))_SOLVER_EVIDENCE_SOURCE=(?<value>[^\r\n]+)\r?$"
    )
    if($iterationMatches.Count-ne 1-or$residualMatches.Count-ne 1-or$sourceMatches.Count-ne 1){
      throw "COMSOL field-solve report has incomplete $prefix iterative evidence."
    }
    $iteration=$null
    $iterationText=$iterationMatches[0].Groups['value'].Value
    if($iterationText-ne'UNKNOWN'){
      $parsedIteration=[int64]0
      if(-not[int64]::TryParse($iterationText,[ref]$parsedIteration)-or$parsedIteration-lt 0){
        throw "COMSOL field-solve report has an invalid $prefix iteration count."
      }
      $iteration=$parsedIteration
    }
    $residual=$null
    $residualText=$residualMatches[0].Groups['value'].Value
    if($residualText-ne'UNKNOWN'){
      $parsedResidual=[double]0
      if(-not[double]::TryParse(
        $residualText,
        [Globalization.NumberStyles]::Float,
        [Globalization.CultureInfo]::InvariantCulture,
        [ref]$parsedResidual
      )-or[double]::IsNaN($parsedResidual)-or
        [double]::IsInfinity($parsedResidual)-or$parsedResidual-lt 0){
        throw "COMSOL field-solve report has an invalid $prefix final residual."
      }
      $residual=$parsedResidual
    }
    $evidenceSource=$sourceMatches[0].Groups['value'].Value
    if($evidenceSource-notin@(
      'NOT_APPLICABLE_DIRECT_SOLVER',
      'UNAVAILABLE_FROM_COMSOL_PROGRESS_LOG',
      'COMSOL_PROGRESS_LINIT_LINRES'
    )){
      throw "COMSOL field-solve report has an invalid $prefix solver-evidence source."
    }
    if($backendMatches[0].Groups['value'].Value-in@('MUMPS','PARDISO')-and
      ($null-ne$iteration-or$null-ne$residual-or
        $evidenceSource-ne'NOT_APPLICABLE_DIRECT_SOLVER')){
      throw "COMSOL direct field solve reported contradictory $prefix iterative evidence."
    }
    if($backendMatches[0].Groups['value'].Value-eq'CG_AMG'){
      $completeProgressEvidence=$evidenceSource-eq'COMSOL_PROGRESS_LINIT_LINRES'-and
        $null-ne$iteration-and$iteration-gt 0-and$null-ne$residual
      if(-not$completeProgressEvidence){
        throw "COMSOL CG-AMG field solve lacks positive $prefix LinIt/LinRes evidence."
      }
    }
    $solverEvidence[$prefix.ToLowerInvariant()]=[ordered]@{
      dof=$dofs["${prefix}_DOF"]
      iteration_count=$iteration
      final_residual=$residual
      evidence_source=$evidenceSource.ToLowerInvariant()
    }
  }
  return [ordered]@{
    stationary_linear_solver_backend=$backendMatches[0].Groups['value'].Value.ToLowerInvariant()
    electric_potential_element_order=$orderMatches[0].Groups['value'].Value.ToLowerInvariant()
    field_physics_created=$counts.FIELD_PHYSICS_CREATED
    field_studies_created=$counts.FIELD_STUDIES_CREATED
    field_solutions_created=$counts.FIELD_SOLUTIONS_CREATED
    field_dof=$dofs
    field_solver_evidence=$solverEvidence
    stationary_solver_configuration=[ordered]@{
      control=$configurationTokens.STATIONARY_CONTROL.ToLowerInvariant()
      relative_tolerance=$stationaryTolerance
      fully_coupled_linear_solver=(
        $configurationTokens.STATIONARY_FULLY_COUPLED_LINEAR_SOLVER.ToLowerInvariant()
      )
      maximum_linear_iterations=$maximumLinearIterations
      linear_error_check=$linearErrorCheck
      convergence_log=$configurationTokens.STATIONARY_CONVERGENCE_LOG.ToLowerInvariant()
    }
  }
}

function Assert-MultipoleFieldPreregistration {
  param(
    [Parameter(Mandatory=$true)][string]$Path,
    [Parameter(Mandatory=$true)][string]$RepoRoot,
    [Parameter(Mandatory=$true)][string]$ProjectId,
    [Parameter(Mandatory=$true)][string]$RunId,
    [Parameter(Mandatory=$true)][string]$RuntimeProfileId,
    [Parameter(Mandatory=$true)][string]$DesignProfileId,
    [Parameter(Mandatory=$true)][string]$ParticleSourceProfileId,
    [Parameter(Mandatory=$true)][string]$SolverNumericsProfileId,
    [Parameter(Mandatory=$true)][string]$RetentionClass,
    [Parameter(Mandatory=$true)][string]$ExpectedResolvedSha256,
    [Parameter(Mandatory=$true)][string]$EngineeringBudgetPath
  )
  if([string]::IsNullOrWhiteSpace($Path)-or
    -not(Test-Path -LiteralPath $Path -PathType Leaf)){
    throw 'COMSOL field-solve runtime requires an existing preregistration evidence contract.'
  }
  $document=Get-Content -LiteralPath $Path -Raw -Encoding UTF8|ConvertFrom-Json
  if([int64]$document.schema_version-ne 2-or
    [string]$document.role-ne'multipole_comsol_field_solver_isolation_preregistration'-or
    [string]$document.status-ne'authorized_not_run'-or
    [string]$document.project_id-ne$ProjectId-or
    $document.preregistered_before_run-ne$true){
    throw 'COMSOL field-solve preregistration identity or status is invalid.'
  }
  $authorization=$document.authorization
  if([int64]$authorization.maximum_commercial_run_count-ne 1-or
    [int64]$authorization.automatic_retry_count-ne 0-or
    [string]$authorization.planned_run_id-ne$RunId-or
    [string]$authorization.runtime_profile_id-ne$RuntimeProfileId-or
    [string]$authorization.design_profile_id-ne$DesignProfileId-or
    [string]$authorization.particle_source_profile_id-ne$ParticleSourceProfileId-or
    [string]$authorization.comsol_solver_numerics_profile_id-ne$SolverNumericsProfileId-or
    [string]$authorization.stop_stage-ne'field_solve'-or
    [string]$authorization.retention_class-ne$RetentionClass){
    throw 'COMSOL field-solve invocation differs from its preregistered authorization.'
  }
  $frozen=$document.frozen_identity
  if([string]$frozen.expected_run_parent_resolved_design_sha256-ne$ExpectedResolvedSha256){
    throw 'COMSOL field-solve preregistration resolved-design identity differs.'
  }
  $projectRoot=Join-Path $RepoRoot "projects\$ProjectId"
  $authorities=[ordered]@{
    runtime_profiles_sha256=Join-Path $projectRoot 'config\runtime_profiles.json'
    comsol_solver_numerics_sha256=Join-Path $projectRoot 'config\comsol_solver_numerics.json'
    engineering_budget_sha256=$EngineeringBudgetPath
    particle_source_profiles_sha256=Join-Path $projectRoot 'config\particle_source_profiles.json'
    design_profiles_sha256=Join-Path $projectRoot 'config\design_profiles.json'
  }
  foreach($field in $authorities.Keys){
    $actual=(Get-FileHash -Algorithm SHA256 -LiteralPath $authorities[$field]).Hash
    if([string]$frozen.$field-ne$actual){
      throw "COMSOL field-solve preregistration authority hash differs: $field"
    }
  }
  $implementationFiles=@($document.frozen_implementation.files)
  $requiredImplementationPaths=@(
    'common/multipole/run_finite_3d_transport.ps1',
    'common/multipole/finite_3d_transport_preflight.ps1',
    'common/multipole/solve_finite_3d_transport.m',
    'common/multipole/configure_comsol_segment_hybrid_mesh.m',
    'common/multipole/export_comsol_stationary_field_samples.m',
    'common/multipole/stationary_field_sampling.py'
  )
  if($implementationFiles.Count-ne$requiredImplementationPaths.Count){
    throw 'COMSOL field-solve preregistration implementation inventory differs.'
  }
  $declaredImplementationPaths=@(
    $implementationFiles|ForEach-Object{[string]$_.path}
  )
  if((@($declaredImplementationPaths|Sort-Object)-join',')-ne
    (@($requiredImplementationPaths|Sort-Object)-join',')){
    throw 'COMSOL field-solve preregistration implementation paths differ.'
  }
  $repoPrefix=[IO.Path]::GetFullPath($RepoRoot).TrimEnd('\')+'\'
  foreach($entry in $implementationFiles){
    $implementationPath=[IO.Path]::GetFullPath(
      (Join-Path $RepoRoot ([string]$entry.path))
    )
    if(-not$implementationPath.StartsWith(
        $repoPrefix,[StringComparison]::OrdinalIgnoreCase
      )-or-not(Test-Path -LiteralPath $implementationPath -PathType Leaf)){
      throw 'COMSOL field-solve preregistration implementation path is invalid.'
    }
    $actual=(Get-FileHash -Algorithm SHA256 -LiteralPath $implementationPath).Hash
    if([string]$entry.sha256-ne$actual){
      throw "COMSOL field-solve preregistration implementation hash differs: $($entry.path)"
    }
  }
  $sampling=$document.field_sampling
  if([string]$sampling.role-ne'multipole_stationary_field_sampling'-or
    [int64]$sampling.expected_point_count-lt 1-or
    [int64]$sampling.expected_row_count-ne 2*[int64]$sampling.expected_point_count-or
    (@($sampling.field_cases)-join',')-ne'differential,static'){
    throw 'COMSOL field-solve preregistration sampling contract is invalid.'
  }
  $samplingPlanPath=[IO.Path]::GetFullPath(
    (Join-Path $RepoRoot ([string]$sampling.plan_path))
  )
  if(-not$samplingPlanPath.StartsWith(
      $repoPrefix,[StringComparison]::OrdinalIgnoreCase
    )-or-not(Test-Path -LiteralPath $samplingPlanPath -PathType Leaf)){
    throw 'COMSOL field-solve preregistration sampling-plan path is invalid.'
  }
  $samplingPlanHash=(Get-FileHash -Algorithm SHA256 -LiteralPath $samplingPlanPath).Hash
  if([string]$sampling.plan_sha256-ne$samplingPlanHash){
    throw 'COMSOL field-solve preregistration sampling-plan hash differs.'
  }
  if($document.PSObject.Properties.Name-notcontains'required_report'){
    throw 'COMSOL field-solve preregistration omits required_report.'
  }
  $requiredReport=$document.required_report
  if($requiredReport.PSObject.Properties.Name-notcontains'tokens'-or
    $requiredReport.PSObject.Properties.Name-notcontains'forbidden_checkpoints'){
    throw 'COMSOL field-solve preregistration required_report fields differ.'
  }
  $requiredTokens=@($requiredReport.tokens|ForEach-Object{[string]$_})
  $forbiddenCheckpoints=@(
    $requiredReport.forbidden_checkpoints|ForEach-Object{[string]$_}
  )
  if($requiredTokens.Count-lt 1-or$forbiddenCheckpoints.Count-lt 1-or
    @($requiredTokens|Where-Object{[string]::IsNullOrWhiteSpace($_)}).Count-gt 0-or
    @($forbiddenCheckpoints|Where-Object{[string]::IsNullOrWhiteSpace($_)}).Count-gt 0-or
    @($requiredTokens|Sort-Object -Unique).Count-ne$requiredTokens.Count-or
    @($forbiddenCheckpoints|Sort-Object -Unique).Count-ne$forbiddenCheckpoints.Count){
    throw 'COMSOL field-solve preregistration required_report values are invalid.'
  }
  foreach($token in @(
      'CHECKPOINT=MESH_COMPLETE',
      'CHECKPOINT=STATIONARY_FIELDS_COMPLETE',
      'CHECKPOINT=STATIONARY_FIELD_SAMPLES_COMPLETE',
      'STOP_STAGE=field_solve',
      'PARTICLE_PHYSICS_CREATED=0',
      'PARTICLE_STUDIES_CREATED=0',
      'FIELD_SOLVE_DIAGNOSTIC=PASS',
      'STATUS=PASS'
    )){
    if($requiredTokens-notcontains$token){
      throw "COMSOL field-solve preregistration required_report omits core token: $token"
    }
  }
  foreach($checkpoint in @(
      'PRIMARY_PARTICLE_CASE_COMPLETE',
      'CONTROL_PARTICLE_CASE_COMPLETE'
    )){
    if($forbiddenCheckpoints-notcontains$checkpoint){
      throw "COMSOL field-solve preregistration required_report omits forbidden checkpoint: $checkpoint"
    }
  }
  return $document
}
