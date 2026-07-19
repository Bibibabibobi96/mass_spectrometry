param(
  [string]$ManifestPath = '',
  [string]$EntryId = '',
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
if ($manifest.schema_version -notin @(1,2)) { throw "Unsupported SIMION stable-entry schema: $($manifest.schema_version)" }
$artifactWorkspace = Join-Path $workspaceRoot ('artifacts\projects\oa_tof\' + $manifest.artifact_workspace_relative.Replace('/','\'))
$runtimeVerifier = Join-Path $PSScriptRoot 'verify_iob_runtime_contract.ps1'

$entries = @($manifest.entries)
if ($EntryId) {
  $entries = @($entries | Where-Object id -eq $EntryId)
  if ($entries.Count -ne 1) { throw "Stable-entry manifest does not contain exactly one entry named $EntryId." }
}
foreach ($entry in $entries) {
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
    if ($asset.role -eq 'sha256_manifest') {
      $familyRoot = Split-Path -Parent $path
      $listed = @(Import-Csv -LiteralPath $path)
      $runtimeTemps = @(Get-ChildItem -LiteralPath $familyRoot -File -Filter 'trj*.tmp')
      if ($runtimeTemps.Count) {
        Write-Warning "$($entry.id): ignoring $($runtimeTemps.Count) SIMION runtime trajectory temp file(s); delete them before packaging."
      }
      $actual = @(Get-ChildItem -LiteralPath $familyRoot -File | Where-Object {
        $_.Name -notin @((Split-Path -Leaf $path),'run_manifest.json') -and $_.Name -notlike 'trj*.tmp'
      })
      if ($listed.Count -ne $actual.Count) {
        throw "$($entry.id): delivery file-count mismatch: manifest=$($listed.Count) actual=$($actual.Count)"
      }
      foreach ($row in $listed) {
        $familyFile = Join-Path $familyRoot $row.file
        if (-not (Test-Path -LiteralPath $familyFile -PathType Leaf)) {
          throw "$($entry.id): delivery manifest file missing: $familyFile"
        }
        $familyItem = Get-Item -LiteralPath $familyFile
        $familyHash = (Get-FileHash -LiteralPath $familyFile -Algorithm SHA256).Hash
        if ($familyItem.Length -ne [int64]$row.bytes -or $familyHash -ne $row.sha256) {
          throw "$($entry.id): delivery manifest mismatch: $familyFile"
        }
      }
    }
    if ($asset.role -eq 'iob') { $iobPath = $path }
  }
  if (-not $iobPath) { throw "$($entry.id): manifest has no IOB asset" }
  & $runtimeVerifier -IobPath $iobPath -ExpectedTrajectoryQuality ([int]$entry.trajectory_quality) -ExpectedInstances ([int]$entry.expected_instances) -SimionExe $SimionExe
  Write-Output ("STABLE_ENTRY_{0}=PASS" -f $entry.id)
}
Write-Output 'SIMION_STABLE_ENTRY_STATUS=PASS'
