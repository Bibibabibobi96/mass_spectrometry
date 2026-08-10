Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Copy-RfOatofFormalPaSet {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$FormalDir,
    [Parameter(Mandatory)][string]$Destination
  )

  $inventory = Import-Csv -LiteralPath (Join-Path $FormalDir 'SHA256SUMS.csv')
  $pattern = '^(oatof_ideal_grounded\.(iob|con)|(flight_tube_ground|reflectron|accelerator|detector_ground)\.pa(-surf|#|\d+))$'
  $records = @($inventory | Where-Object { $_.file -match $pattern })
  if (@($records | Where-Object { $_.file -eq 'oatof_ideal_grounded.iob' }).Count -ne 1) {
    throw 'Formal oaTOF inventory has no unique IOB.'
  }
  foreach ($record in $records) {
    $source = Join-Path $FormalDir ([string]$record.file)
    if (-not (Test-Path -LiteralPath $source -PathType Leaf) -or
        (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne
        ([string]$record.sha256).ToUpperInvariant()) {
      throw "Formal oaTOF asset identity differs: $($record.file)"
    }
    $target = Join-Path $Destination ([string]$record.file)
    if ([string]$record.file -match '\.pa(-surf|#|\d+)$') {
      try {
        New-Item -ItemType HardLink -Path $target -Target $source -ErrorAction Stop | Out-Null
      } catch {
        Copy-Item -LiteralPath $source -Destination $target
      }
    } else {
      Copy-Item -LiteralPath $source -Destination $target
    }
  }
}
