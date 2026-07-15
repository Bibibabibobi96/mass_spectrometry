param(
  [Parameter(Mandatory = $true)]
  [string]$IobPath,
  [int]$ExpectedTrajectoryQuality = 8,
  [int]$ExpectedInstances = 4,
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$iob = (Resolve-Path -LiteralPath $IobPath).Path
$verifier = Join-Path $PSScriptRoot 'verify_iob_runtime_contract.lua'
$runId = [Guid]::NewGuid().ToString('N')
$report = Join-Path $env:TEMP ("oatof_simion_iob_runtime_contract_{0}.txt" -f $runId)
$programReport = Join-Path $env:TEMP ("oatof_simion_program_load_contract_{0}.txt" -f $runId)
$oldIob = $env:OATOF_SIMION_IOB_PATH
$oldReport = $env:OATOF_SIMION_IOB_REPORT
$oldQuality = $env:OATOF_SIMION_EXPECTED_QUALITY
$oldInstances = $env:OATOF_SIMION_EXPECTED_INSTANCES
$oldProgramReport = $env:OATOF_SIMION_PROGRAM_LOAD_REPORT
try {
  $env:OATOF_SIMION_IOB_PATH = $iob
  $env:OATOF_SIMION_IOB_REPORT = $report
  $env:OATOF_SIMION_EXPECTED_QUALITY = [string]$ExpectedTrajectoryQuality
  $env:OATOF_SIMION_EXPECTED_INSTANCES = [string]$ExpectedInstances
  $env:OATOF_SIMION_PROGRAM_LOAD_REPORT = $programReport
  & $SimionExe --nogui lua $verifier
  if ($LASTEXITCODE -ne 0) {
    throw "SIMION IOB runtime verification failed with exit code $LASTEXITCODE"
  }
  if (-not (Select-String -LiteralPath $report -Pattern '^STATUS=PASS$' -Quiet)) {
    throw 'SIMION IOB runtime report did not pass.'
  }
  Get-Content -LiteralPath $report -Encoding UTF8
}
finally {
  $env:OATOF_SIMION_IOB_PATH = $oldIob
  $env:OATOF_SIMION_IOB_REPORT = $oldReport
  $env:OATOF_SIMION_EXPECTED_QUALITY = $oldQuality
  $env:OATOF_SIMION_EXPECTED_INSTANCES = $oldInstances
  $env:OATOF_SIMION_PROGRAM_LOAD_REPORT = $oldProgramReport
}
