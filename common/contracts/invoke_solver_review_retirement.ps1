[CmdletBinding(SupportsShouldProcess)]
param(
  [Parameter(Mandatory)][string]$ArtifactRoot,
  [Parameter(Mandatory)][string]$RepositoryRoot,
  [Parameter(Mandatory)][string]$TargetRun,
  [Parameter(Mandatory)][string]$ReplacementRun,
  [Parameter(Mandatory)][string]$CompatibilityAssertion,
  [string[]]$CompatibilityInputRoles=@(),
  [string[]]$CompatibilityInputRoleMaps=@(),
  [switch]$Apply
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\host_execution_lease.ps1')
$python = Join-Path $RepositoryRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { $python = 'python' }
$arguments = @('-m','common.contracts.solver_review_retirement','--artifact-root',$ArtifactRoot,
  '--repository-root',$RepositoryRoot,'--target-run',$TargetRun,'--replacement-run',$ReplacementRun,
  '--compatibility-assertion',$CompatibilityAssertion)
if ($CompatibilityInputRoles.Count -eq 0 -and $CompatibilityInputRoleMaps.Count -eq 0) {
  throw 'At least one compatibility input role or role mapping is required.'
}
foreach ($role in $CompatibilityInputRoles) { $arguments += @('--compatibility-input-role',$role) }
foreach ($mapping in $CompatibilityInputRoleMaps) { $arguments += @('--compatibility-input-role-map',$mapping) }
if (-not $Apply) { & $python @arguments; exit $LASTEXITCODE }
if (-not $PSCmdlet.ShouldProcess($TargetRun, "retire governed solver_review heavy payload")) { return }
$lease = Enter-HostExecutionLease -Role GATE -Stage artifact_retirement -RunId ([IO.Path]::GetFileName($TargetRun))
try {
  & $python @arguments --apply
  if ($LASTEXITCODE -ne 0) { throw "solver_review retirement failed with exit code $LASTEXITCODE" }
} finally {
  Exit-HostExecutionLease -Lease $lease
}
