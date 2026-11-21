[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$SimionExe,
  [Parameter(Mandatory)][string]$GemPath,
  [Parameter(Mandatory)][string]$OutputPaPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

$simion=(Resolve-Path -LiteralPath $SimionExe).Path
$gem=(Resolve-Path -LiteralPath $GemPath).Path
$output=[IO.Path]::GetFullPath($OutputPaPath)
& $simion --nogui --noprompt gem2pa $gem $output
if($LASTEXITCODE-ne0){throw "SIMION gem2pa failed: $gem"}
if(-not(Test-Path -LiteralPath $output -PathType Leaf)){throw "SIMION gem2pa produced no PA: $output"}
Write-Host "SIMION_GEM2PA=PASS OUTPUT=$output"
