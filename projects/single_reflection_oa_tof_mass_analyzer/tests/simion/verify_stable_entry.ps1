param(
  [string]$ManifestPath = '',
  [string]$EntryId = '',
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [switch]$SkipRuntime
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$workspaceRoot = Split-Path -Parent $repoRoot
. (Join-Path $projectRoot 'oatof_lifecycle_preflight.ps1')
if (-not $ManifestPath) {
  $ManifestPath = Join-Path $projectRoot 'config\simion_stable_entry.json'
}

function Assert-ExactProperties([object]$Value, [string[]]$Expected, [string]$Label) {
  $difference = @(Compare-Object @($Expected | Sort-Object) @($Value.PSObject.Properties.Name | Sort-Object))
  if ($difference.Count) { throw "$Label fields differ from the stable-entry contract." }
}

function Assert-FileRecord([string]$Root, [object]$Record, [string]$Label, [string]$PathProperty = 'path') {
  Assert-ExactProperties $Record @($PathProperty, 'bytes', 'sha256') $Label
  $relative = [string]$Record.$PathProperty
  if ([IO.Path]::IsPathRooted($relative) -or $relative -match '(^|[\/\\])\.\.([\/\\]|$)') {
    throw "$Label has an unsafe relative path: $relative"
  }
  $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\')
  $path = [IO.Path]::GetFullPath((Join-Path $rootFull $relative.Replace('/', '\')))
  if (-not $path.StartsWith("$rootFull\", [StringComparison]::OrdinalIgnoreCase)) {
    throw "$Label resolves outside its manifest root: $relative"
  }
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
    throw "$Label is missing: $path"
  }
  $item = Get-Item -LiteralPath $path
  $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
  if ($item.Length -ne [int64]$Record.bytes -or $hash -ne [string]$Record.sha256) { throw "$Label identity differs: $path" }
  return $path
}

$stablePath = (Resolve-Path -LiteralPath $ManifestPath).Path
$stable = Get-Content -LiteralPath $stablePath -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-ExactProperties $stable @('schema_version', 'frozen_on', 'role', 'artifact_workspace_relative', 'entries') 'SIMION stable entry'
if ($stable.schema_version -ne 2 -or
    $stable.artifact_workspace_relative -ne 'formal' -or
    @($stable.entries).Count -ne 1) {
  throw 'SIMION stable-entry identity differs.'
}
$entry = @($stable.entries)[0]
Assert-ExactProperties $entry @('id', 'manifests', 'required_assets', 'gui_requirements') 'SIMION stable-entry record'
if ($EntryId -and $entry.id -ne $EntryId) { throw "Stable-entry manifest does not contain exactly one entry named $EntryId." }
Assert-ExactProperties $entry.manifests @('formal_asset_manifest', 'simion_delivery_manifest') 'SIMION stable-entry manifest bindings'
Assert-ExactProperties $entry.gui_requirements @('expected_instances', 'trajectory_quality', 'program_enabled', 'data_recording_enabled') 'SIMION stable-entry GUI requirements'
if ([int]$entry.gui_requirements.expected_instances -ne 4 -or
    [int]$entry.gui_requirements.trajectory_quality -ne 8 -or
    $entry.gui_requirements.program_enabled -ne $true -or
    $entry.gui_requirements.data_recording_enabled -ne $true) {
  throw 'SIMION stable-entry GUI requirements differ.'
}

$expectedRoles = [ordered]@{
  iob = 'simion_iob'
  con = 'simion_con'
  program = 'simion_program'
  fly2 = 'simion_fly2'
  ion = 'shared_particle_table'
}
Assert-ExactProperties $entry.required_assets @($expectedRoles.Keys) 'SIMION required assets'
foreach ($expected in $expectedRoles.GetEnumerator()) {
  if ($entry.required_assets.($expected.Key) -ne $expected.Value) {
    throw "SIMION stable entry requires one $($expected.Key) role bound to $($expected.Value)."
  }
}

$formalRoot = Join-Path $workspaceRoot ('artifacts\projects\single_reflection_oa_tof_mass_analyzer\' + $stable.artifact_workspace_relative.Replace('/', '\'))
$formalManifestPath = Assert-FileRecord $formalRoot `
  $entry.manifests.formal_asset_manifest 'Formal asset manifest binding' 'relative_path'
$formalManifest = Get-Content -LiteralPath $formalManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($formalManifest.schema_version -ne 1 -or
    $formalManifest.role -ne 'formal_asset_manifest' -or
    $formalManifest.project -ne 'single_reflection_oa_tof_mass_analyzer') {
  throw 'Formal asset manifest identity differs.'
}

$deliveryPath = Assert-FileRecord $formalRoot `
  $entry.manifests.simion_delivery_manifest 'SIMION delivery manifest binding' 'relative_path'
$deliveryAsset = $formalManifest.assets.PSObject.Properties['simion_delivery_manifest'].Value
if ($null -eq $deliveryAsset -or
    $deliveryAsset.path -ne $entry.manifests.simion_delivery_manifest.relative_path -or
    [int64]$deliveryAsset.bytes -ne [int64]$entry.manifests.simion_delivery_manifest.bytes -or
    $deliveryAsset.sha256 -ne $entry.manifests.simion_delivery_manifest.sha256) {
  throw 'SIMION delivery manifest binding differs from the Formal asset manifest.'
}
$delivery = Get-Content -LiteralPath $deliveryPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($delivery.schema_version -ne 1 -or
    $delivery.role -ne 'oa_tof_simion_formal_delivery_manifest' -or
    $delivery.project -ne $formalManifest.project -or
    $delivery.release_id -ne $formalManifest.release_id -or
    $delivery.status -ne 'success') {
  throw 'SIMION delivery manifest identity differs.'
}

$simionRoot = Split-Path -Parent $deliveryPath
$deliveryByPath = @{}
foreach ($property in $delivery.assets.PSObject.Properties) {
  $record = $property.Value
  Assert-ExactProperties $record @('path', 'bytes', 'sha256') "SIMION delivery asset $($property.Name)"
  if ($deliveryByPath.ContainsKey([string]$record.path)) {
    throw "SIMION delivery manifest repeats path: $($record.path)"
  }
  $deliveryByPath[[string]$record.path] = $record
}

$shaAsset = $formalManifest.assets.PSObject.Properties['simion_sha256_manifest'].Value
if ($null -eq $shaAsset) {
  throw 'Formal asset manifest lacks the SIMION SHA-256 manifest role.'
}
$shaPath = Assert-FileRecord $formalRoot $shaAsset 'SIMION SHA-256 manifest'
$listed = @(Import-Csv -LiteralPath $shaPath)
if ($listed.Count -ne $deliveryByPath.Count) {
  throw "SIMION manifest file counts differ: delivery=$($deliveryByPath.Count) sha=$($listed.Count)"
}
$listedPaths = @{}
foreach ($row in $listed) {
  Assert-ExactProperties $row @('file', 'bytes', 'sha256') 'SIMION SHA-256 row'
  if ($listedPaths.ContainsKey([string]$row.file)) {
    throw "SIMION SHA-256 manifest repeats path: $($row.file)"
  }
  $listedPaths[[string]$row.file] = $true
  $null = Assert-FileRecord $simionRoot $row "SIMION SHA-256 asset $($row.file)" 'file'
  $deliveryRecord = $deliveryByPath[[string]$row.file]
  if ($null -eq $deliveryRecord -or
      [int64]$deliveryRecord.bytes -ne [int64]$row.bytes -or
      $deliveryRecord.sha256 -ne $row.sha256) {
    throw "SIMION delivery/SHA manifest identity differs: $($row.file)"
  }
}
$actual = @(Get-ChildItem -LiteralPath $simionRoot -File | Where-Object {
  $_.Name -notin @((Split-Path -Leaf $deliveryPath), (Split-Path -Leaf $shaPath)) -and
  $_.Name -notlike 'trj*.tmp'
})
if ($actual.Count -ne $listed.Count) {
  throw "SIMION delivery file count differs: actual=$($actual.Count) manifest=$($listed.Count)"
}

$iobPath = $null
foreach ($required in $expectedRoles.GetEnumerator()) {
  $formalRecord = $formalManifest.assets.PSObject.Properties[
    [string]$required.Value
  ].Value
  if ($null -eq $formalRecord) {
    throw "Formal asset manifest lacks required role: $($required.Value)"
  }
  $formalPath = Assert-FileRecord $formalRoot $formalRecord `
    "Formal SIMION $($required.Key) asset"
  $relative = [IO.Path]::GetRelativePath($simionRoot, $formalPath).Replace('\', '/')
  $deliveryRecord = $deliveryByPath[$relative]
  if ($null -eq $deliveryRecord -or
      [int64]$deliveryRecord.bytes -ne [int64]$formalRecord.bytes -or
      $deliveryRecord.sha256 -ne $formalRecord.sha256) {
    throw "Formal/delivery manifest identity differs for SIMION $($required.Key)."
  }
  if ($required.Key -eq 'iob') {
    $iobPath = $formalPath
  }
}

$runtimeVerifier = Join-Path $projectRoot 'simion\workbench\verify_iob_runtime_contract.ps1'
if (-not $SkipRuntime) {
  $runtimeTaskId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__simion__stable-entry-runtime'
  $runtimeRoot = Join-Path $artifactRoot "scratch\$runtimeTaskId"
  $runtimeRoot = New-OaTofFormalSimionRuntime -ProjectRoot $projectRoot `
    -ArtifactRoot $artifactRoot -PythonExe (Join-Path $repoRoot '.venv\Scripts\python.exe') `
    -Destination $runtimeRoot -Receipt (Join-Path $runtimeRoot 'runtime_receipt.json')
  try {
    & $runtimeVerifier -IobPath (Join-Path $runtimeRoot (Split-Path -Leaf $iobPath)) `
      -ExpectedTrajectoryQuality ([int]$entry.gui_requirements.trajectory_quality) `
      -ExpectedInstances ([int]$entry.gui_requirements.expected_instances) `
      -SimionExe $SimionExe
  } finally {
    Remove-OaTofFormalSimionRuntime -ArtifactRoot $artifactRoot -RuntimeRoot $runtimeRoot
  }
}
Write-Output ("STABLE_ENTRY_{0}=PASS" -f $entry.id)
Write-Output 'SIMION_STABLE_ENTRY_STATUS=PASS'
