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
