[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$RunId,
  [string]$RequestPath='',
  [string]$ReleaseSpecPath='',
  [string]$RuntimeCheckpointPath='',
  [string]$SimionExe=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
if(-not$RequestPath){$RequestPath=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\config\accelerator_component_request_n100.json'}
if(-not$ReleaseSpecPath){$ReleaseSpecPath=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\config\accelerator_component_release_n100.json'}
$provider=Join-Path $repoRoot 'projects\orthogonal_accelerator\simion\run_component_focus_workflow.ps1'
foreach($path in @($provider,$RequestPath,$ReleaseSpecPath)){
  if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Required accelerator component input is missing: $path"}
}

$arguments=@{RunId=$RunId;RequestPath=(Resolve-Path -LiteralPath $RequestPath).Path;ReleaseSpecPath=(Resolve-Path -LiteralPath $ReleaseSpecPath).Path}
if($RuntimeCheckpointPath){$arguments.RuntimeCheckpointPath=(Resolve-Path -LiteralPath $RuntimeCheckpointPath).Path}
if($SimionExe){$arguments.SimionExe=$SimionExe}
& $provider @arguments
if($LASTEXITCODE-ne0){throw 'Provider-owned accelerator component workflow failed'}
