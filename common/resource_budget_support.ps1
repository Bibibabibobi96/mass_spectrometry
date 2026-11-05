# Remaining SIMION dispatch orchestration consumes the single installed process owner.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if(-not(Get-Command Assert-HostResourceHeavyStage -ErrorAction SilentlyContinue)){
  . (Join-Path $PSScriptRoot 'host_execution_lease.ps1')
}
$processResource=Join-Path (Split-Path -Parent $PSScriptRoot) 'src/msplatform/execution/resources/resource_process_support.ps1'
if(-not(Test-Path -LiteralPath $processResource -PathType Leaf)){throw 'Frozen execution process resource is unavailable.'}
. ([string]$processResource)

# Remaining legacy callers consume the sole installed dispatch implementation.
. (Join-Path (Split-Path -Parent $processResource) 'simion_dispatch_support.ps1')
