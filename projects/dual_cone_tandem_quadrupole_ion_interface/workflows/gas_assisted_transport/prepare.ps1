[CmdletBinding()]
param(
 [Parameter(Mandatory=$true)][string]$OutputDir,
 [Parameter(Mandatory=$true)][ValidateSet('c0_gem_smoke','gas_assisted_transport')][string]$Mode,
 [Parameter(Mandatory=$true)][string]$PythonExe,
 [Parameter(Mandatory=$true)][string]$ResolvedGeometry,
 [Parameter(Mandatory=$true)][string]$Numerics,
 [Parameter(Mandatory=$true)][string]$TransportScience,
 [Parameter(Mandatory=$true)][string]$GasInterface,
 [Parameter(Mandatory=$true)][string]$GasScience,
 [Parameter(Mandatory=$true)][string]$SourceSpec,
 [string]$GasFieldManifest='', [string]$GasFieldReference='',
 [string]$CollisionSdsDirectory='', [string]$SimionExe=''
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if($PSVersionTable.PSEdition-ne'Core'-or$PSVersionTable.PSVersion.Major-lt7){throw 'PowerShell Core 7 is required.'}
$arguments=@('-I','-B','-m','msplatform.backends.simion.dual_cone_transport',
 '--output-dir',[IO.Path]::GetFullPath($OutputDir),'--mode',$Mode,
 '--resolved',[IO.Path]::GetFullPath($ResolvedGeometry),'--numerics',[IO.Path]::GetFullPath($Numerics),
 '--science',[IO.Path]::GetFullPath($TransportScience),'--interface',[IO.Path]::GetFullPath($GasInterface),
 '--gas-science',[IO.Path]::GetFullPath($GasScience),'--source-spec',[IO.Path]::GetFullPath($SourceSpec))
foreach($pair in @(@('--gas-field-manifest',$GasFieldManifest),@('--gas-field-reference',$GasFieldReference),
 @('--collision-sds-dir',$CollisionSdsDirectory),@('--simion-exe',$SimionExe))){
 if(-not[string]::IsNullOrWhiteSpace($pair[1])){$arguments+=@($pair[0],[IO.Path]::GetFullPath($pair[1]))}
}
& $PythonExe @arguments
if($LASTEXITCODE-ne 0){throw 'Dual-cone installed input preparation failed.'}
