Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-MultipoleProjectFinite3dTransport {
  [CmdletBinding(DefaultParameterSetName = 'RuntimeProfile')]
  param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('comsol', 'simion')]
    [string]$Solver,
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,
    [Parameter(ParameterSetName = 'RuntimeProfile')]
    [string]$RuntimeProfileId,
    [Parameter(Mandatory = $true, ParameterSetName = 'CampaignExperiment')]
    [string]$CampaignPath,
    [Parameter(Mandatory = $true, ParameterSetName = 'CampaignExperiment')]
    [string]$ExperimentId,
    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,
    [string]$EvidenceContractPath = '',
    [string]$RunId = '',
    [ValidateSet('compact', 'qualification', 'solver_review')]
    [string]$RetentionClass = 'compact',
    [string]$RetentionReason = '',
    [string]$PythonExe = '',
    [string]$ReferenceComsolRunId = '',
    [ValidateSet('primary_and_zero_axial_control', 'primary_and_rf_off_energy_control', 'primary_only')]
    [string]$CaseSet = 'primary_and_zero_axial_control',
    [string]$SimionExe = '',
    [string]$ContinuationPredecessorManifestPath = '',
    [string]$NativeFieldRunPath = '',
    [string]$ResultPath = '',
    [string]$ResolvedRuntimeProfilePath = ''
  )

  if ($Solver -ne 'simion' -and ($ContinuationPredecessorManifestPath -or $NativeFieldRunPath)) {
    throw 'SIMION continuation is not supported by the COMSOL transport entry.'
  }

  $python = if ($PythonExe) {
    [IO.Path]::GetFullPath($PythonExe)
  } else {
    Join-Path $RepoRoot '.venv\Scripts\python.exe'
  }
  $resolutionPath = Join-Path ([IO.Path]::GetTempPath()) (
    "multipole_runtime_{0}_{1}.json" -f $ProjectId, [guid]::NewGuid()
  )

  try {
    if($ResolvedRuntimeProfilePath){
      Copy-Item -LiteralPath $ResolvedRuntimeProfilePath -Destination $resolutionPath
    }else{
    Push-Location $RepoRoot
    try {
      if ($PSCmdlet.ParameterSetName -eq 'CampaignExperiment') {
        $selectionArguments = @(
          '--campaign-path', $CampaignPath,
          '--experiment-id', $ExperimentId
        )
      } else {
        $selectionArguments = @('--runtime-profile-id', $RuntimeProfileId)
      }
      & $python -m projects.rf_multipole_ion_optics.runtime.runtime_profile --repo-root $RepoRoot `
        --project-id $ProjectId @selectionArguments --output $resolutionPath
    } finally {
      Pop-Location
    }
    if ($LASTEXITCODE -ne 0) {
      throw "Multipole runtime profile resolution failed for '$ProjectId'."
    }

    }
    $profile = Get-Content -LiteralPath $resolutionPath -Raw -Encoding UTF8 |
      ConvertFrom-Json
    if([string]$profile.role-ne'multipole_resolved_runtime_profile'-or[string]$profile.project_id-ne$ProjectId){throw 'Compiled runtime identity differs from the requested project.'}
    $resolvedRuntimeProfileId = [string]$profile.runtime_profile_id
    if($RuntimeProfileId-and$RuntimeProfileId-cne$resolvedRuntimeProfileId){throw 'Compiled runtime selection differs.'}
    if ($PSCmdlet.ParameterSetName -eq 'CampaignExperiment') {
      $authorizedRunId = [string](
        $profile.engineering_budget.inline_contract.pilot_authorization.scope.authorized_run_id
      )
      if ([string]::IsNullOrWhiteSpace($authorizedRunId)) {
        throw "Campaign experiment '$ExperimentId' omits authorized_run_id."
      }
      if ($RunId -and $RunId -cne $authorizedRunId) {
        throw "RunId differs from campaign experiment '$ExperimentId'."
      }
      $RunId = $authorizedRunId
      if ($PSBoundParameters.ContainsKey('RetentionClass') -and $RetentionClass -cne [string]$profile.retention_class) {
        throw 'RetentionClass differs from the declared campaign experiment.'
      }
      $RetentionClass = [string]$profile.retention_class
      if ($RetentionClass -ne 'compact' -and [string]::IsNullOrWhiteSpace($RetentionReason)) {
        # The campaign explicitly selected this retention class. Preserve its
        # frozen identity and claim scope as the existing policy's explanation.
        $RetentionReason = "Declared campaign retention ($RetentionClass): $($profile.campaign.campaign_id) / $($profile.campaign.experiment_id). $($profile.engineering_budget.inline_contract.claim_limit)"
      }
    }
    $numerics = $profile.solver_numerics.$Solver.values
    $stopStage = [string]$profile.stop_stage
    $arguments = @{
      ProjectId = $ProjectId
      RuntimeProfileId = $resolvedRuntimeProfileId
      DesignProfileId = [string]$profile.design_profile_id
      EngineeringBudgetPath = [string]$profile.engineering_budget.path
      RunId = $RunId
      ResolvedRuntimeProfilePath = $resolutionPath
      RetentionClass = $RetentionClass
      RetentionReason = $RetentionReason
      PythonExe = $python
      RfStepsPerPeriod = [int]$numerics.trajectory.rf_steps_per_period
      MaximumTimeUs = [double]$numerics.trajectory.maximum_global_time_us
    }
    if ($ResultPath) {$arguments.ResultPath = $ResultPath}
    if ($profile.particle_source.PSObject.Properties.Name -contains 'release_spec') {
      if ($Solver -ne 'simion') { throw 'Release-spec materialization is currently implemented for SIMION only.' }
    } else {
      $arguments.ParticleSourcePath = [string]$profile.particle_source.path
    }
    if ($EvidenceContractPath) {
      $arguments.EvidenceContractPath = $EvidenceContractPath
    }

    if ($Solver -eq 'comsol') {
      $arguments.StopStage = $stopStage
      $arguments.MeshAutoLevel = [int]$numerics.mesh.global_auto_level
      if($numerics.mesh.PSObject.Properties.Name -contains 'minimum_element_size_mm'){
        $arguments.MinimumElementSizeMm=[double]$numerics.mesh.minimum_element_size_mm
      }
      if ($null -ne $numerics.mesh.working_region_maximum_element_size_mm) {
        $arguments.WorkingRegionMaximumElementSizeMm = [double](
          $numerics.mesh.working_region_maximum_element_size_mm
        )
      }
      $commonEntry = 'projects\rf_multipole_ion_optics\runtime\run_finite_3d_transport.ps1'
    } else {
      if ($stopStage -ne 'transport') {
        throw "SIMION transport does not support stop stage '$stopStage'."
      }
      $arguments.ReferenceComsolRunId = $ReferenceComsolRunId
      $arguments.CellMmX = [double]$numerics.cell_mm_xyz.x
      $arguments.CellMmY = [double]$numerics.cell_mm_xyz.y
      $arguments.CellMmZ = [double]$numerics.cell_mm_xyz.z
      $arguments.TrajectoryQuality = [int]$numerics.trajectory_quality
      $arguments.CaseSet = if ($PSCmdlet.ParameterSetName -eq 'CampaignExperiment' -and -not [string]::IsNullOrWhiteSpace([string]$profile.case_set)) {
        [string]$profile.case_set
      } else {
        $CaseSet
      }
      $arguments.ResolvedRuntimeProfilePath = $resolutionPath
      if ($ContinuationPredecessorManifestPath) {
        $arguments.ContinuationPredecessorManifestPath = $ContinuationPredecessorManifestPath
      }
      if ($NativeFieldRunPath) {$arguments.NativeFieldRunPath = $NativeFieldRunPath}
      if ($SimionExe) {
        $arguments.SimionExe = $SimionExe
      }
      $commonEntry = 'projects\rf_multipole_ion_optics\runtime\run_simion_finite_3d_transport.ps1'
    }

    & (Join-Path $RepoRoot $commonEntry) @arguments
    if ($LASTEXITCODE -ne 0) {
      throw "Multipole $Solver transport failed for '$ProjectId'."
    }
  } finally {
    Remove-Item -LiteralPath $resolutionPath -Force -ErrorAction SilentlyContinue
  }
}
