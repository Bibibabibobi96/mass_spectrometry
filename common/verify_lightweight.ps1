[CmdletBinding()]
param(
    [string]$PythonExe = '',
    [string[]]$ChangedPath = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

& (Join-Path $PSScriptRoot 'verify_changed.ps1') -PythonExe $PythonExe -ChangedPath $ChangedPath
if ($LASTEXITCODE -ne 0) {
    throw "Changed-scope gate failed with exit code $LASTEXITCODE."
}
