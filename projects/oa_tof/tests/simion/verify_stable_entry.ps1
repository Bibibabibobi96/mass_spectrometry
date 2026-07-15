param(
  [string]$ManifestPath = '',
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$workspaceRoot = Split-Path -Parent $repoRoot
if (-not $ManifestPath) {
  $ManifestPath = Join-Path $projectRoot 'config\simion_stable_entry.json'
}
$manifestFile = (Resolve-Path -LiteralPath $ManifestPath).Path
$manifest = Get-Content -LiteralPath $manifestFile -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.schema_version -ne 1) { throw "Unsupported SIMION stable-entry schema: $($manifest.schema_version)" }
$artifactWorkspace = Join-Path $workspaceRoot ('artifacts\projects\oa_tof\' + $manifest.artifact_workspace_relative.Replace('/','\'))
$runtimeVerifier = Join-Path $PSScriptRoot 'verify_iob_runtime_contract.ps1'

foreach ($entry in $manifest.entries) {
  $iobPath = $null
  foreach ($asset in $entry.assets) {
    $path = Join-Path $artifactWorkspace $asset.relative_path.Replace('/','\')
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
      throw "$($entry.id): missing $($asset.role): $path"
    }
    $item = Get-Item -LiteralPath $path
    if ($item.Length -ne [int64]$asset.bytes) {
      throw "$($entry.id): byte count mismatch for $($asset.role): actual=$($item.Length) expected=$($asset.bytes)"
    }
    $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
    if ($hash -ne $asset.sha256) {
      throw "$($entry.id): SHA-256 mismatch for $($asset.role): actual=$hash expected=$($asset.sha256)"
    }
    if ($asset.role -eq 'iob') { $iobPath = $path }
  }
  if (-not $iobPath) { throw "$($entry.id): manifest has no IOB asset" }
  & $runtimeVerifier -IobPath $iobPath -ExpectedTrajectoryQuality ([int]$entry.trajectory_quality) -ExpectedInstances ([int]$entry.expected_instances) -SimionExe $SimionExe
  Write-Output ("STABLE_ENTRY_{0}=PASS" -f $entry.id)
}
Write-Output 'SIMION_STABLE_ENTRY_STATUS=PASS'
