[CmdletBinding()]
param(
  [string]$SimionExe='',
  [Parameter(Mandatory)][string]$RepoRoot,
  [Parameter(Mandatory)][string]$GemPath,
  [Parameter(Mandatory)][string]$PhysicalPaPath,
  [Parameter(Mandatory)][string]$GroupedPaPath,
  [Parameter(Mandatory)][string]$OutputPaPath,
  [Parameter(Mandatory)][string]$ParentHalfMillimeterPaPath,
  [Parameter(Mandatory)][string]$PatchOriginCsv,
  [Parameter(Mandatory)][string]$LocalVoltagesCsv,
  [Parameter(Mandatory)][string]$ElectrodeMappingCsv,
  [Parameter(Mandatory)][string]$ReceiptPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if([string]::IsNullOrWhiteSpace($SimionExe)){$SimionExe=[string]$env:MRTOF_SIMION_EXE}
if([string]::IsNullOrWhiteSpace($SimionExe)){throw 'SIMION executable was not supplied to the fixed-mirror worker.'}

function Invoke-WorkerSimion {
  param([Parameter(Mandatory)][string]$Stage,[Parameter(Mandatory)][string[]]$Arguments)
  & $SimionExe @Arguments
  if($LASTEXITCODE-ne0){throw "SIMION fixed-mirror worker stage failed: $Stage"}
}

$remapper=Join-Path $RepoRoot 'common\simion\remap_pa_electrode_ids.lua'
$dirichletBuilder=Join-Path $RepoRoot 'common\simion\build_dirichlet_patch_operating_pa.lua'
$outputDirectory=Split-Path -Parent ([IO.Path]::GetFullPath($OutputPaPath))
$receiptDirectory=Split-Path -Parent ([IO.Path]::GetFullPath($ReceiptPath))
New-Item -ItemType Directory -Path $outputDirectory -Force|Out-Null
New-Item -ItemType Directory -Path $receiptDirectory -Force|Out-Null

try{
  Invoke-WorkerSimion -Stage 'compile' -Arguments @('--nogui','--noprompt','gem2pa',$GemPath,$PhysicalPaPath)
  Invoke-WorkerSimion -Stage 'remap' -Arguments @('--nogui','--noprompt','lua',$remapper,$PhysicalPaPath,$GroupedPaPath,$ElectrodeMappingCsv)
  if(Test-Path -LiteralPath $PhysicalPaPath -PathType Leaf){Remove-Item -LiteralPath $PhysicalPaPath -Force}
  Invoke-WorkerSimion -Stage 'solve' -Arguments @('--nogui','--noprompt','lua',$dirichletBuilder,$GroupedPaPath,$OutputPaPath,$ParentHalfMillimeterPaPath,$PatchOriginCsv,$PatchOriginCsv,$LocalVoltagesCsv)
  if(Test-Path -LiteralPath $GroupedPaPath -PathType Leaf){Remove-Item -LiteralPath $GroupedPaPath -Force}
  if(-not(Test-Path -LiteralPath $OutputPaPath -PathType Leaf)){throw 'Fixed-mirror worker did not produce its operating PA0.'}
  $receipt=[ordered]@{
    schema_version=1;role='mrtof_fixed_dirichlet_mirror_worker';status='success'
    output_pa0=[IO.Path]::GetFullPath($OutputPaPath)
    output_sha256=(Get-FileHash -LiteralPath $OutputPaPath -Algorithm SHA256).Hash
    intermediate_files_deleted=$true
  }
  [IO.File]::WriteAllText($ReceiptPath,($receipt|ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false))
}catch{
  $failure=[ordered]@{schema_version=1;role='mrtof_fixed_dirichlet_mirror_worker';status='failed';reason=$_.Exception.Message}
  [IO.File]::WriteAllText($ReceiptPath,($failure|ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false))
  throw
}
