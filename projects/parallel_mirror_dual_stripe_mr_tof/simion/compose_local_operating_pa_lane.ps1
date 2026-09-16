[CmdletBinding()]
param([Parameter(Mandatory)][string]$PlanPath)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

$plan=Get-Content -Raw -LiteralPath $PlanPath|ConvertFrom-Json -Depth 20
foreach($name in @('simion_exe','solver_dir','short_pa_support','compose_lua','output_pa','responses')){
  if($null-eq$plan.PSObject.Properties[$name]){throw "Composition lane plan lacks $name."}
}
. ([string]$plan.short_pa_support)
$privateDirectory=Join-Path ([IO.Path]::GetTempPath()) ('simion_pa_links_'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $privateDirectory|Out-Null
$detachedBase=$null
try {
  $responsePaths=@()
  for($index=0;$index-lt@($plan.responses).Count;$index++){
    $response=$plan.responses[$index]
    $responsePaths+=New-ShortPaCopy -Source ([string]$response.source) -Destination (Join-Path $privateDirectory ("r{0}.bin"-f($index+1)))
  }
  if([string]$plan.base_mode-eq'first_response'){
    if($responsePaths.Count-eq0){throw 'First-response composition lane has no response.'}
    $privateBase=$responsePaths[0]
  }elseif([string]$plan.base_mode-eq'standalone'){
    $privateBase=New-ShortPaCopy -Source ([string]$plan.base_source) -Destination (Join-Path $privateDirectory 'base.bin')
  }elseif([string]$plan.base_mode-eq'legacy_family'){
    $privateLegacy=New-ShortPaCopy -Source ([string]$plan.base_source) -Destination (Join-Path $privateDirectory 'legacy.pa0')
    $detachedBase=Join-Path $privateDirectory 'base.bin'
    Push-Location -LiteralPath ([string]$plan.solver_dir)
    try {
      & ([string]$plan.simion_exe) '--nogui' '--noprompt' 'lua' ([string]$plan.export_lua) $privateLegacy $detachedBase
      if($LASTEXITCODE-ne0){throw 'Legacy local PA detachment failed inside composition lane.'}
    } finally {Pop-Location}
    $privateBase=$detachedBase
  }else{throw "Unsupported composition lane base mode: $($plan.base_mode)"}
  $arguments=@('--nogui','--noprompt','lua',([string]$plan.compose_lua),$privateBase,([string]$plan.output_pa))
  for($index=0;$index-lt$responsePaths.Count;$index++){
    $coefficient=[string]$plan.responses[$index].coefficient
    $arguments+=("{0},{1}"-f$responsePaths[$index],$coefficient)
  }
  Push-Location -LiteralPath ([string]$plan.solver_dir)
  try {
    & ([string]$plan.simion_exe) @arguments
    if($LASTEXITCODE-ne0){throw 'Standalone local PA composition failed inside parallel lane.'}
  } finally {Pop-Location}
  Write-Host "LOCAL_OPERATING_PA_LANE=PASS LABEL=$($plan.label) OUTPUT=$($plan.output_pa)"
} catch {
  if(Test-Path -LiteralPath ([string]$plan.output_pa) -PathType Leaf){Remove-Item -LiteralPath ([string]$plan.output_pa) -Force}
  throw
} finally {
  if($null-ne$detachedBase-and(Test-Path -LiteralPath $detachedBase -PathType Leaf)){Remove-Item -LiteralPath $detachedBase -Force}
  Remove-ShortPaCopyDirectory -Path $privateDirectory
}
