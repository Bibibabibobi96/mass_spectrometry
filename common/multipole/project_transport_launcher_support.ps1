Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-MultipoleProjectFinite3dTransport {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('comsol', 'simion')]
    [string]$Solver,
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,
    [Parameter(Mandatory = $true)]
    [string]$RuntimeProfileId,
    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,
    [string]$EvidenceContractPath = '',
    [string]$RunId = '',
    [ValidateSet('compact', 'qualification', 'solver_review')]
    [string]$RetentionClass = 'compact',
    [string]$RetentionReason = '',
    [string]$PythonExe = '',
    [string]$ReferenceComsolRunId = '',
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
      & $python -m common.multipole.runtime_profile --repo-root $RepoRoot `
        --project-id $ProjectId --runtime-profile-id $RuntimeProfileId `
        --output $resolutionPath
    } finally {
      Pop-Location
    }
    if ($LASTEXITCODE -ne 0) {
      throw "Multipole runtime profile resolution failed for '$ProjectId'."
    }

    $profile = Get-Content -LiteralPath $resolutionPath -Raw -Encoding UTF8 |
      ConvertFrom-Json
    $numerics = $profile.solver_numerics.$Solver.values
    $arguments = @{
      ProjectId = $ProjectId
      RuntimeProfileId = $RuntimeProfileId
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
      $arguments.MeshAutoLevel = [int]$numerics.mesh.global_auto_level
      if ($null -ne $numerics.mesh.working_region_maximum_element_size_mm) {
        $arguments.WorkingRegionMaximumElementSizeMm = [double](
          $numerics.mesh.working_region_maximum_element_size_mm
        )
      }
      $numericsProfileId = [string]$profile.solver_numerics.comsol.profile_id
      if ($numericsProfileId -like '*_mesh_build') {
        if ($RuntimeProfileId -notlike '*_mesh_build') {
          throw 'A mesh-build numerics profile requires a mesh-build runtime identity.'
        }
        $arguments.StopStage = 'mesh_build'
      }
      $commonEntry = 'common\multipole\run_finite_3d_transport.ps1'
    } else {
      $arguments.ReferenceComsolRunId = $ReferenceComsolRunId
      $arguments.CellMm = [double]$numerics.cell_mm
      $arguments.TrajectoryQuality = [int]$numerics.trajectory_quality
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
