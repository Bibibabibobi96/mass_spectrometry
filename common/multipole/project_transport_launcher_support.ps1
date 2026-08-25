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
    [Parameter(Mandatory = $true, ParameterSetName = 'RuntimeProfile')]
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
    [string]$SimionExe = ''
  )

  $python = if ($PythonExe) {
    [IO.Path]::GetFullPath($PythonExe)
  } else {
    Join-Path $RepoRoot '.venv\Scripts\python.exe'
  }
  $resolutionPath = Join-Path ([IO.Path]::GetTempPath()) (
    "multipole_runtime_{0}_{1}.json" -f $ProjectId, [guid]::NewGuid()
  )

  try {
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
      & $python -m common.multipole.runtime_profile --repo-root $RepoRoot `
        --project-id $ProjectId @selectionArguments --output $resolutionPath
    } finally {
      Pop-Location
    }
    if ($LASTEXITCODE -ne 0) {
      throw "Multipole runtime profile resolution failed for '$ProjectId'."
    }

    $profile = Get-Content -LiteralPath $resolutionPath -Raw -Encoding UTF8 |
      ConvertFrom-Json
    $resolvedRuntimeProfileId = [string]$profile.runtime_profile_id
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
    }
    $numerics = $profile.solver_numerics.$Solver.values
    $stopStage = [string]$profile.stop_stage
    $arguments = @{
      ProjectId = $ProjectId
      RuntimeProfileId = $resolvedRuntimeProfileId
      DesignProfileId = [string]$profile.design_profile_id
      ParticleSourcePath = [string]$profile.particle_source.path
      EngineeringBudgetPath = [string]$profile.engineering_budget.path
      RunId = $RunId
      RetentionClass = $RetentionClass
      RetentionReason = $RetentionReason
      PythonExe = $python
      RfStepsPerPeriod = [int]$numerics.trajectory.rf_steps_per_period
      MaximumTimeUs = [double]$numerics.trajectory.maximum_global_time_us
    }
    if ($EvidenceContractPath) {
      $arguments.EvidenceContractPath = $EvidenceContractPath
    }

    if ($Solver -eq 'comsol') {
      $arguments.StopStage = $stopStage
      $arguments.MeshAutoLevel = [int]$numerics.mesh.global_auto_level
      if ($null -ne $numerics.mesh.working_region_maximum_element_size_mm) {
        $arguments.WorkingRegionMaximumElementSizeMm = [double](
          $numerics.mesh.working_region_maximum_element_size_mm
        )
      }
      $commonEntry = 'common\multipole\run_finite_3d_transport.ps1'
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
      if ($SimionExe) {
        $arguments.SimionExe = $SimionExe
      }
      $commonEntry = 'common\multipole\run_simion_finite_3d_transport.ps1'
    }

    & (Join-Path $RepoRoot $commonEntry) @arguments
    if ($LASTEXITCODE -ne 0) {
      throw "Multipole $Solver transport failed for '$ProjectId'."
    }
  } finally {
    Remove-Item -LiteralPath $resolutionPath -Force -ErrorAction SilentlyContinue
  }
}
