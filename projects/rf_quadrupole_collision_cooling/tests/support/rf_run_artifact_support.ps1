Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')

Set-Alias -Name New-RfRunPackage -Value New-RunPackage
Set-Alias -Name Write-RfJson -Value Write-RunJson
Set-Alias -Name Write-RfRunManifest -Value Write-RunManifest
Set-Alias -Name Save-RfEnvironment -Value Save-RunEnvironment
Set-Alias -Name Restore-RfEnvironment -Value Restore-RunEnvironment
Set-Alias -Name Copy-RfFrozenDependency -Value Copy-FrozenDependency
Set-Alias -Name Complete-RfFailedRun -Value Complete-FailedRun
