# Repository adapter only; installed host code requires explicit execution context.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$legacyRepo=Split-Path -Parent $PSScriptRoot
$legacyPython=if($env:SIMULATION_PYTHON_EXE){$env:SIMULATION_PYTHON_EXE}else{Join-Path $legacyRepo '.venv/Scripts/python.exe'}
$hostResource=Join-Path $legacyRepo 'src/msplatform/execution/resources/host_execution_lease.ps1'
if(-not(Test-Path -LiteralPath $hostResource -PathType Leaf)){throw 'Frozen execution host resource is unavailable.'}
$legacyHostContext=@{workspace=$legacyRepo;python_executable=$legacyPython;
  host_state_path=$(if($env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH){$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH}else{Join-Path (Split-Path -Parent $legacyRepo) 'artifacts/common/host_resources.sqlite3'});
  policy_path=(Join-Path $legacyRepo 'src/msplatform/execution/resources/host_resource_policy.json')}
. ([string]$hostResource) -HostContext $legacyHostContext
