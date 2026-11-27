Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-OaTofFormalAssetsReadable {
  param([Parameter(Mandatory)][string]$ProjectRoot)
  $contractPath = Join-Path $ProjectRoot 'config\project.json'
  $contract = Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($contract.schema_version -eq 1) {
    if ($contract.lifecycle_status -eq 'formal_revalidation_pending') {
      throw 'FORMAL_REVALIDATION_REQUIRED: Formal assets are unavailable until vNext revalidation completes.'
    }
  } elseif ($contract.schema_version -eq 2) {
    if ($contract.project_id -ne 'single_reflection_oa_tof_mass_analyzer' -or
        $contract.asset_references.identity_contract -ne 'config/formal_assets.json') {
      throw 'ASSET_IDENTITY_REQUIRED: Project asset identity reference differs.'
    }
  } else {
    throw 'Unsupported project descriptor version.'
  }
}

function New-OaTofFormalSimionRuntime {
  param(
    [Parameter(Mandatory)][string]$ProjectRoot,
    [Parameter(Mandatory)][string]$ArtifactRoot,
    [Parameter(Mandatory)][string]$PythonExe,
    [Parameter(Mandatory)][string]$Destination,
    [Parameter(Mandatory)][string]$Receipt
  )
  $artifactFull = [IO.Path]::GetFullPath($ArtifactRoot).TrimEnd('\')
  $scratchFull = [IO.Path]::GetFullPath((Join-Path $artifactFull 'scratch')).TrimEnd('\')
  $destinationFull = [IO.Path]::GetFullPath($Destination)
  if (-not $destinationFull.StartsWith("$scratchFull\", [StringComparison]::OrdinalIgnoreCase)) {
    throw "Formal SIMION runtime must remain under project scratch: $destinationFull"
  }
  & $PythonExe -m msplatform.backends.simion.runtime_materialization `
    --artifact-root $artifactFull --destination $destinationFull --receipt $Receipt --project-id 'single_reflection_oa_tof_mass_analyzer' |
    ForEach-Object { Write-Host $_ }
  if ($LASTEXITCODE -ne 0) { throw 'Formal SIMION runtime staging failed.' }
  return $destinationFull
}

function Remove-OaTofFormalSimionRuntime {
  param(
    [Parameter(Mandatory)][string]$ArtifactRoot,
    [Parameter(Mandatory)][string]$RuntimeRoot
  )
  $scratchFull = [IO.Path]::GetFullPath((Join-Path $ArtifactRoot 'scratch')).TrimEnd('\')
  $runtimeFull = [IO.Path]::GetFullPath($RuntimeRoot)
  if (-not $runtimeFull.StartsWith("$scratchFull\", [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to remove runtime outside project scratch: $runtimeFull"
  }
  if (Test-Path -LiteralPath $runtimeFull) {
    Remove-Item -LiteralPath $runtimeFull -Recurse -Force
  }
}
