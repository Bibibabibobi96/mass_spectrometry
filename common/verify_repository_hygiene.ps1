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




  'iob_seed_placeholder_01.pa0','iob_seed_placeholder_02.pa0',
  'iob_seed_placeholder_03.pa0','iob_seed_placeholder_04.pa0',
  'iob_seed_placeholder_05.pa0','iob_seed_placeholder_06.pa0',
  'iob_seed_placeholder_07.pa0','iob_seed_placeholder_08.pa0',
  'iob_seed_placeholder_09.pa0','iob_seed_placeholder_10.pa0'
) | ForEach-Object { "$sharedIobSeedPrefix$_" }
$installedStructuralSeeds = @{
  'src/msplatform/backends/simion/resources/1_instance_seed.iob' = @{ Bytes = 20856; Sha256 = '0b34d1277d4c65f62972e01a82d03705d1691113cbe87c52082d17abdf577917' }
  'src/msplatform/backends/simion/resources/2_instance_seed.iob' = @{ Bytes = 20884; Sha256 = '5a2ef00fd0b490f072af42ca7a23a944115e0f9e700f4a4355489d2a7c9dedb1' }
  'src/msplatform/backends/simion/resources/3_instance_seed.iob' = @{ Bytes = 20912; Sha256 = '358e4f0c9d2a5bac62bd366c4d9bed84e0f015021b51792c8eba0e2a75ae3321' }
  'src/msplatform/backends/simion/resources/4_instance_seed.iob' = @{ Bytes = 20940; Sha256 = '437d67349bccc25b63da2befe79b5c1b78448a150c768277515e6a2adf5f6daa' }
  'src/msplatform/backends/simion/resources/5_instance_seed.iob' = @{ Bytes = 20968; Sha256 = 'b881934c94008d2b3404595d08607e599e63ca712857453d10772a310362f606' }
  'src/msplatform/backends/simion/resources/6_instance_seed.iob' = @{ Bytes = 20996; Sha256 = '82ed6a52a260fea44e1598870da3638559f7a12a9cd5ebad73e0f0e94308a99c' }
  'src/msplatform/backends/simion/resources/7_instance_seed.iob' = @{ Bytes = 21024; Sha256 = '18183ab67963a4925d448df08858c1d9bc5f50a9fa15c7c1955a6bb418777564' }
  'src/msplatform/backends/simion/resources/8_instance_seed.iob' = @{ Bytes = 21052; Sha256 = 'aee23381e55ccf5239fc01ac4ead362b92329c1308d7a8ade82f4eaf38b98082' }
  'src/msplatform/backends/simion/resources/9_instance_seed.iob' = @{ Bytes = 21080; Sha256 = 'd36ea7190a390dc050267f3ab06787f5ab59716e2f25efd042ba8cb5a82d890f' }
  'src/msplatform/backends/simion/resources/10_instance_seed.iob' = @{ Bytes = 21108; Sha256 = '765203159b90480d2e8723c77f6b01af736ecb96245eab4d95a5042c53276e78' }
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
