Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-OaTofFormalAssetsReadable {
  param([Parameter(Mandatory)][string]$ProjectRoot)
  $contractPath = Join-Path $ProjectRoot 'config\project.json'
  $contract = Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($contract.lifecycle_status -eq 'formal_revalidation_pending') {
    throw 'FORMAL_REVALIDATION_REQUIRED: Formal assets are unavailable until vNext revalidation completes.'
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
  & $PythonExe -m projects.single_reflection_oa_tof_mass_analyzer.analysis.stage_formal_simion_runtime `
    --artifact-root $artifactFull --destination $destinationFull --receipt $Receipt |
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
