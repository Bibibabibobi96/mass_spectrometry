[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$hostExecutionLease = $null
$hostExecutionLeaseSupport = Join-Path $PSScriptRoot 'host_execution_lease.ps1'
if (Test-Path -LiteralPath $hostExecutionLeaseSupport -PathType Leaf) {
  . $hostExecutionLeaseSupport
  $hostExecutionLease = Enter-HostExecutionLease -Role GATE
}
try {
$errors = [Collections.Generic.List[string]]::new()

$tracked = @(& git -C $repoRoot ls-files)
if ($LASTEXITCODE -ne 0) { throw 'git ls-files failed.' }
$sharedIobSeedPrefix = 'common/simion/assets/iob_instance_seeds/'
$sharedIobSeedFiles = @(
  '1_instance_seed.iob','2_instance_seed.iob','3_instance_seed.iob',
  '6_instance_seed.iob',
  '7_instance_seed.iob','8_instance_seed.iob','9_instance_seed.iob',
  '10_instance_seed.iob',
  'iob_seed_placeholder_01.pa0','iob_seed_placeholder_02.pa0',
  'iob_seed_placeholder_03.pa0','iob_seed_placeholder_04.pa0',
  'iob_seed_placeholder_05.pa0','iob_seed_placeholder_06.pa0',
  'iob_seed_placeholder_07.pa0','iob_seed_placeholder_08.pa0',
  'iob_seed_placeholder_09.pa0','iob_seed_placeholder_10.pa0'
) | ForEach-Object { "$sharedIobSeedPrefix$_" }
$installedStructuralSeeds = @{
  'src/msplatform/backends/simion/resources/4_instance_seed.iob' = @{ Bytes = 20940; Sha256 = '437d67349bccc25b63da2befe79b5c1b78448a150c768277515e6a2adf5f6daa' }
  'src/msplatform/backends/simion/resources/5_instance_seed.iob' = @{ Bytes = 20968; Sha256 = 'b881934c94008d2b3404595d08607e599e63ca712857453d10772a310362f606' }
}
foreach ($path in $tracked) {
  $normalized = $path.Replace('\','/')
  $isSharedIobSeed = $normalized -in $sharedIobSeedFiles
  if ($installedStructuralSeeds.ContainsKey($normalized)) {
    $expected = $installedStructuralSeeds[$normalized]
    $actual = Get-Item -LiteralPath (Join-Path $repoRoot $normalized)
    $actualHash = (Get-FileHash -LiteralPath $actual.FullName -Algorithm SHA256).Hash
    $isSharedIobSeed = $actual.Length -eq $expected.Bytes -and $actualHash -eq $expected.Sha256
    if (-not $isSharedIobSeed) { $errors.Add("registered structural template identity differs: $path") }
  }
  if ($normalized -match '(^|/)artifacts/' -or
      ((-not $isSharedIobSeed) -and
       $normalized -match '(?i)\.(mph|iob|pa(?:\d+|#)?|sldprt|sldasm|step|stp|dmp|log)$')) {
    $errors.Add("generated/binary artifact is tracked by Git: $path")
  }
}

if ($errors.Count -gt 0) {
  $errors | ForEach-Object { Write-Error $_ }
  throw "Repository hygiene gate failed with $($errors.Count) error(s)."
}
Write-Output "REPOSITORY_HYGIENE=PASS TRACKED_FILES=$($tracked.Count)"
} finally {
  if ($null -ne $hostExecutionLease) {
    Exit-HostExecutionLease -Lease $hostExecutionLease
  }
}
