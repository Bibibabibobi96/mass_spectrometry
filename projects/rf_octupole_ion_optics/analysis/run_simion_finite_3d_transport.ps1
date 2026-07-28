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
  [string]$PythonExe = '',
  [string]$ReferenceComsolRunId = '',
  [string]$SimionExe = ''
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
  $numerics = $profile.solver_numerics.simion.values
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
    ReferenceComsolRunId = $ReferenceComsolRunId
    CellMm = [double]$numerics.cell_mm
    RfStepsPerPeriod = [int]$numerics.trajectory.rf_steps_per_period
    TrajectoryQuality = [int]$numerics.trajectory_quality
    MaximumTimeUs = [double]$numerics.trajectory.maximum_global_time_us
  }
  if ($EvidenceContractPath) { $arguments.EvidenceContractPath = $EvidenceContractPath }
  if ($SimionExe) { $arguments.SimionExe = $SimionExe }
  & (Join-Path $repoRoot 'common\multipole\run_simion_finite_3d_transport.ps1') @arguments
  if ($LASTEXITCODE -ne 0) { throw 'RF octupole SIMION transport failed.' }
} finally {
  Remove-Item -LiteralPath $resolutionPath -Force -ErrorAction SilentlyContinue
}
