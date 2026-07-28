[CmdletBinding()]
param(
  [ValidateSet(
    'no_acceleration_full_length',
    'no_acceleration_full_length_n100_spatial_refined',
    'no_acceleration_full_length_n100_temporal_refined',
    'segmented_rod_axial_acceleration',
    'segmented_rod_axial_acceleration_n100_spatial_refined',
    'segmented_rod_axial_acceleration_n100_temporal_refined',
    'exit_aperture_plate_acceleration',
    'exit_aperture_plate_acceleration_n100_spatial_refined',
    'exit_aperture_plate_acceleration_n100_temporal_refined',
    'no_acceleration_full_length_n1000',
    'segmented_rod_axial_acceleration_n1000',
    'exit_aperture_plate_acceleration_n1000',
    'baseline_finite_3d',
    'exit_aperture_plate_acceleration_reference'
  )]
  [string]$RuntimeProfileId = 'no_acceleration_full_length',
  [string]$EvidenceContractPath = '',
  [string]$RunId = '',
  [ValidateSet('compact','qualification','solver_review')][string]$RetentionClass = 'compact',
  [string]$RetentionReason = '',
  [string]$PythonExe = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
$resolutionPath = Join-Path ([IO.Path]::GetTempPath()) ("rfoct_runtime_{0}.json" -f [guid]::NewGuid())
try {
  Push-Location $repoRoot
  try {
    & $python -m common.multipole.runtime_profile --repo-root $repoRoot `
      --project-id rf_octupole_ion_optics --runtime-profile-id $RuntimeProfileId `
      --output $resolutionPath
  } finally { Pop-Location }
  if ($LASTEXITCODE -ne 0) { throw 'RF octupole runtime profile resolution failed.' }
  $profile = Get-Content -LiteralPath $resolutionPath -Raw -Encoding UTF8 | ConvertFrom-Json
  $numerics = $profile.solver_numerics.comsol.values
  $arguments = @{
    ProjectId = 'rf_octupole_ion_optics'
    RuntimeProfileId = $RuntimeProfileId
    DesignProfileId = [string]$profile.design_profile_id
    ParticleSourcePath = [string]$profile.particle_source.path
    EngineeringBudgetPath = [string]$profile.engineering_budget.path
    RunId = $RunId
    RetentionClass = $RetentionClass
    RetentionReason = $RetentionReason
    PythonExe = $python
    MeshAutoLevel = [int]$numerics.mesh.global_auto_level
    RfStepsPerPeriod = [int]$numerics.trajectory.rf_steps_per_period
    MaximumTimeUs = [double]$numerics.trajectory.maximum_global_time_us
  }
  if ($null -ne $numerics.mesh.working_region_maximum_element_size_mm) {
    $arguments.WorkingRegionMaximumElementSizeMm = [double]$numerics.mesh.working_region_maximum_element_size_mm
  }
  if ($EvidenceContractPath) { $arguments.EvidenceContractPath = $EvidenceContractPath }
  & (Join-Path $repoRoot 'common\multipole\run_finite_3d_transport.ps1') @arguments
  if ($LASTEXITCODE -ne 0) { throw 'RF octupole COMSOL transport failed.' }
} finally {
  Remove-Item -LiteralPath $resolutionPath -Force -ErrorAction SilentlyContinue
}
