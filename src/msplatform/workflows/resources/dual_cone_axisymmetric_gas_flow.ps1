[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$RunId,
  [Parameter(Mandatory=$true)][string]$PythonExe,
  [Parameter(Mandatory=$true)][string]$ResolvedInputsPath,
  [Parameter(Mandatory=$true)][string]$DeploymentPath,
  [Parameter(Mandatory=$true)][string]$Workspace,
  [Parameter(Mandatory=$true)][string]$EngineeringProfile
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if($PSVersionTable.PSEdition-ne'Core'-or$PSVersionTable.PSVersion.Major-lt7){throw 'PowerShell Core 7 is required.'}
# Research/profile transport only. Installed Python owns all execution and inputs.
& $PythonExe -I -B -m msplatform.backends.comsol.gas_flow `
  --compiled-inputs $ResolvedInputsPath --deployment $DeploymentPath `
  --workspace $Workspace --engineering-profile $EngineeringProfile --run-id $RunId
if($LASTEXITCODE-ne0){throw "Installed gas-flow operation failed with exit code $LASTEXITCODE."}
