[CmdletBinding()]
param([Parameter(Mandatory)][string]$RunId,[Parameter(Mandatory)][string]$ArmPath)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'execute_retrace_arm.ps1') -RunId $RunId -ArmPath $ArmPath
if ($LASTEXITCODE -ne 0) { throw 'COMSOL pre-pulse retrace arm failed.' }
