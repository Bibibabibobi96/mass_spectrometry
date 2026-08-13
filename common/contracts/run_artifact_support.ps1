Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'require_powershell7.ps1')

function Write-RunJson {
  [CmdletBinding()]
  param([Parameter(Mandatory)][object]$Value,[Parameter(Mandatory)][string]$Path,[int]$Depth=8)
  $Value | ConvertTo-Json -Depth $Depth | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Write-RunManifest {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$RunConfig,
    [Parameter(Mandatory)][ValidateSet('success','failed','interrupted','superseded')][string]$Status,
    [string[]]$Software=@(),
    [string]$Manifest='',
    [string[]]$Outputs=@(),
    [switch]$PassThru
  )
  $arguments=@((Join-Path $RepoRoot 'common\contracts\write_run_manifest.py'),'--run-config',$RunConfig,'--status',$Status)
  if(-not[string]::IsNullOrWhiteSpace($Manifest)){$arguments+=@('--manifest',$Manifest)}
  foreach($item in $Software){$arguments+=@('--software',$item)}
  foreach($item in $Outputs){$arguments+=@('--output',$item)}
  $writerOutput=& $Python @arguments
  if($LASTEXITCODE-ne 0){throw "Run manifest failed for status $Status."}
  if($PassThru){$writerOutput}
}

function Write-VerifiedRunManifest {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$RunConfig,
    [Parameter(Mandatory)][ValidateSet('success','failed','interrupted','superseded')][string]$Status,
    [string[]]$Software=@(),
    [string]$Manifest='',
    [string[]]$Outputs=@()
  )
  if([string]::IsNullOrWhiteSpace($Manifest)){
    $Manifest=Join-Path (Split-Path -Parent $RunConfig) 'run_manifest.json'
  }
  $manifestDirectory=Split-Path -Parent $Manifest
  $manifestName=[IO.Path]::GetFileNameWithoutExtension($Manifest)
  $manifestExtension=[IO.Path]::GetExtension($Manifest)
  $candidateManifest=Join-Path $manifestDirectory `
    ('.{0}.{1}.candidate{2}'-f$manifestName,[guid]::NewGuid().ToString('N'),$manifestExtension)
  try{
    Write-RunManifest -Python $Python -RepoRoot $RepoRoot -RunConfig $RunConfig `
      -Status $Status -Software $Software -Manifest $candidateManifest -Outputs $Outputs -PassThru
    & $Python (Join-Path $RepoRoot 'common\contracts\verify_run_manifest.py') `
      $candidateManifest --require-status $Status
    if($LASTEXITCODE-ne 0){throw "Could not verify $Status run manifest."}
    Move-Item -LiteralPath $candidateManifest -Destination $Manifest -Force
  }catch{
    throw "Could not publish verified $Status run manifest: $($_.Exception.Message)"
  }finally{
    Remove-Item -LiteralPath $candidateManifest -Force -ErrorAction SilentlyContinue
  }
}

function Write-TerminalRunRecord {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RunDir,
    [Parameter(Mandatory)][ValidateSet('failed','interrupted')][string]$Status,
    [Parameter(Mandatory)][string]$Reason,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$SummaryRole,
    [string[]]$Software=@()
  )
  $config=Join-Path $RunDir 'run_config.json'
  $summary=Join-Path $RunDir 'summary.json'
  Write-RunJson -Path $summary -Depth 4 -Value ([ordered]@{
    schema_version=1;role=$SummaryRole;status=$Status;reason=$Reason
  })
  Write-VerifiedRunManifest -Python $Python -RepoRoot $RepoRoot -RunConfig $config `
    -Manifest (Join-Path $RunDir 'run_manifest.json') -Status $Status `
    -Software $Software -Outputs @($summary)
}

function Initialize-RunRecord {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RunDir,
    [Parameter(Mandatory)][string]$RunId,
    [Parameter(Mandatory)][string]$Project,
    [Parameter(Mandatory)][string]$Mode,
    [Parameter(Mandatory)][string]$ProjectRoot,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$ProvisionalSummaryRole,
    [Parameter(Mandatory)][string]$TerminalSummaryRole,
    [string[]]$Software=@()
  )
  $config=Join-Path $RunDir 'run_config.json'
  $summary=Join-Path $RunDir 'summary.json'
  Write-RunJson -Path $config -Depth 5 -Value ([ordered]@{
    schema_version=1;run_id=$RunId;project=$Project;mode=$Mode
    project_root=$ProjectRoot;formal_gate_passed=$false;inputs=[ordered]@{}
  })
  Write-RunJson -Path $summary -Depth 4 -Value ([ordered]@{
    schema_version=1;role=$ProvisionalSummaryRole;status='interrupted'
    reason='Run package initialized; terminal status was not recorded.'
  })
  Write-TerminalRunRecord -RunDir $RunDir -Status interrupted `
    -Reason 'Run package initialized.' -RepoRoot $RepoRoot -Python $Python `
    -SummaryRole $TerminalSummaryRole -Software $Software
}

function New-RunPackage {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$ArtifactRoot,
    [Parameter(Mandatory)][string]$RunId,
    [Parameter(Mandatory)][string]$Project,
    [Parameter(Mandatory)][string]$Mode,
    [Parameter(Mandatory)][string[]]$Software,
    [switch]$RetentionContractEnabled,
    [ValidateSet('compact','qualification','solver_review')][string]$RetentionClass='compact',
    [string]$RetentionReason='',
    [string[]]$AdditionalDirectories=@()
  )
  if($RetentionContractEnabled-and$RetentionClass-ne'compact'-and[string]::IsNullOrWhiteSpace($RetentionReason)){
    throw "RetentionReason is required for artifact retention class $RetentionClass."
  }
  if($RetentionContractEnabled-and$RetentionClass-eq'compact'-and-not[string]::IsNullOrWhiteSpace($RetentionReason)){
    throw 'RetentionReason must be empty for compact artifact retention.'
  }
  if(-not$RetentionContractEnabled-and(
      $RetentionClass-ne'compact'-or-not[string]::IsNullOrWhiteSpace($RetentionReason))){
    throw 'RetentionContractEnabled is required when selecting run artifact retention.'
  }
  $python=[IO.Path]::GetFullPath($Python)
  if(-not(Test-Path -LiteralPath $python -PathType Leaf)){throw "Run Python environment is missing: $python"}
  $pythonVersion=(& $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
  if($LASTEXITCODE-ne 0 -or $pythonVersion-ne '3.11'){
    throw "Run package requires Python 3.11, found $pythonVersion at $python"
  }
  $validation=& $python (Join-Path $RepoRoot 'common\contracts\artifact_naming.py') run $RunId
  if($LASTEXITCODE-ne 0 -or -not($validation-match '^ARTIFACT_ID=PASS ')){throw "Invalid run_id: $RunId"}
  $runDir=Join-Path $ArtifactRoot "runs\$RunId"
  if(Test-Path -LiteralPath $runDir){throw "Run already exists: $runDir"}
  $package=[ordered]@{
    python=$python;run_dir=$runDir;input_dir=(Join-Path $runDir 'inputs');result_dir=(Join-Path $runDir 'results');
    log_dir=(Join-Path $runDir 'logs');run_config=(Join-Path $runDir 'run_config.json');summary=(Join-Path $runDir 'summary.json')
  }
  $directories=@($package.input_dir,$package.result_dir,$package.log_dir)
  foreach($relative in $AdditionalDirectories){$directories+=Join-Path $runDir $relative}
  New-Item -ItemType Directory -Force -Path $directories|Out-Null
  $initialConfig=[ordered]@{
    schema_version=$(if($RetentionContractEnabled){2}else{1});
    run_id=$RunId;project=$Project;mode=$Mode;project_root=$RepoRoot;inputs=[ordered]@{};
    parameters=[ordered]@{lifecycle_stage='run_package_initialized'};formal_gate_passed=$false
  }
  if($RetentionContractEnabled){
    $initialConfig.artifact_retention=[ordered]@{policy_version=1;class=$RetentionClass;
      reason=$(if($RetentionClass-eq'compact'){$null}else{$RetentionReason})}
  }
  Write-RunJson -Path $package.run_config -Value $initialConfig
  Write-RunJson -Path $package.summary -Value ([ordered]@{
    schema_version=1;role='run_package_initialization_summary';status='interrupted';
    reason='Run package initialized; task-specific inputs are not frozen yet.'
  })
  $null=Write-VerifiedRunManifest -Python $python -RepoRoot $RepoRoot -RunConfig $package.run_config `
    -Status interrupted -Software $Software -Outputs @($package.summary)
  return [pscustomobject]$package
}

function Apply-RunArtifactRetention {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$RunConfig
  )
  $output=& $Python (Join-Path $RepoRoot 'common\contracts\artifact_retention.py') `
    apply --run-config $RunConfig
  if($LASTEXITCODE-ne 0){throw 'Run artifact retention failed.'}
  Write-Verbose ($output -join [Environment]::NewLine)
  return Join-Path (Split-Path -Parent $RunConfig) 'retention_actions.json'
}

function Save-RunEnvironment {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string[]]$Names)
  $snapshot=@{};foreach($name in $Names){$snapshot[$name]=[Environment]::GetEnvironmentVariable($name)};return $snapshot
}

function Restore-RunEnvironment {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string[]]$Names,[Parameter(Mandatory)][hashtable]$Snapshot)
  foreach($name in $Names){[Environment]::SetEnvironmentVariable($name,$Snapshot[$name])}
}

function Copy-FrozenDependency {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RepoRoot,[Parameter(Mandatory)][string]$InputDir,
    [Parameter(Mandatory)][pscustomobject]$Dependency
  )
  $providerRoot=[IO.Path]::GetFullPath((Join-Path $RepoRoot (Join-Path 'projects' ([string]$Dependency.provider_project))))
  $source=[IO.Path]::GetFullPath((Join-Path $RepoRoot ([string]$Dependency.source_repo_path)))
  if(-not $source.StartsWith($providerRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){
    throw "Dependency $($Dependency.id) escapes provider project $($Dependency.provider_project)."
  }
  if(-not(Test-Path -LiteralPath $source -PathType Leaf)){throw "Dependency $($Dependency.id) is missing: $source"}
  $destination=Join-Path $InputDir ([string]$Dependency.frozen_filename);Copy-Item -LiteralPath $source -Destination $destination
  $hash=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
  if($hash-ne(Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash){throw "Dependency changed while frozen: $source"}
  return [pscustomobject]@{id=[string]$Dependency.id;provider_project=[string]$Dependency.provider_project;
    source_repo_path=[string]$Dependency.source_repo_path;frozen_input_name=[string]$Dependency.run_input_name;
    frozen_path=$destination;sha256=$hash}
}

function Copy-VerifiedRunInput {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Source,
    [Parameter(Mandatory)][string]$Destination
  )
  $sourcePath=[IO.Path]::GetFullPath($Source);$destinationPath=[IO.Path]::GetFullPath($Destination)
  if(-not(Test-Path -LiteralPath $sourcePath -PathType Leaf)){throw "Run input is missing: $sourcePath"}
  $parent=Split-Path -Parent $destinationPath
  if(-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Path $parent -Force|Out-Null}
  Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Force
  $sourceHash=(Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash
  if($sourceHash-cne(Get-FileHash -LiteralPath $destinationPath -Algorithm SHA256).Hash){
    throw "Run input changed while frozen: $sourcePath"
  }
  return $destinationPath
}

function Write-RunDirectoryChecksumInventory {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Directory,
    [Parameter(Mandatory)][string]$OutputPath,
    [string[]]$ExcludedPatterns=@()
  )
  $outputName=[IO.Path]::GetFileName($OutputPath)
  $records=Get-ChildItem -LiteralPath $Directory -File|Where-Object{
    $name=$_.Name
    if($name-eq$outputName){return $false}
    foreach($pattern in $ExcludedPatterns){if($name-like$pattern){return $false}}
    return $true
  }|Sort-Object Name|ForEach-Object{
    [pscustomobject]@{file=$_.Name;bytes=$_.Length;sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}
  }
  $records|Export-Csv -LiteralPath $OutputPath -NoTypeInformation -Encoding UTF8
}

function Get-RunFileSha256 {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$Path)
  $fullPath=[IO.Path]::GetFullPath($Path)
  if(-not(Test-Path -LiteralPath $fullPath -PathType Leaf)){throw "Run file is missing: $fullPath"}
  return (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash
}

function Complete-FailedRun {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$RunConfig,[Parameter(Mandatory)][string]$Summary,
    [Parameter(Mandatory)][string]$SummaryRole,[Parameter(Mandatory)][string]$Reason,
    [Parameter(Mandatory)][string[]]$Software,
    [ValidateSet('failed','interrupted')][string]$Status='failed',
    [string]$FailureClass='',
    [int]$SummarySchemaVersion=1,
    [string]$FailureStage='',
    [Nullable[bool]]$ThresholdResultEligible=$null,
    [string[]]$AdditionalOutputs=@(),
    [string]$ResourceUsagePath=''
  )
  $document=Get-Content -LiteralPath $RunConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if(-not $document.Contains('inputs')){$document.inputs=[ordered]@{}}
  $known=@($document.inputs.Values|ForEach-Object{if($_ -is [string]){[IO.Path]::GetFullPath($_)}})
  $runDir=Split-Path -Parent $RunConfig
  $inputDir=Join-Path $runDir 'inputs';$index=0
  if(Test-Path -LiteralPath $inputDir -PathType Container){foreach($file in Get-ChildItem -LiteralPath $inputDir -Recurse -File|Sort-Object FullName){
    if($known-notcontains$file.FullName){$index+=1;$document.inputs[("recovered_input_{0:D3}"-f$index)]=$file.FullName}
  }}
  Write-RunJson -Path $RunConfig -Value $document
  $summaryDocument=[ordered]@{
    schema_version=$SummarySchemaVersion;role=$SummaryRole;status=$Status;reason=$Reason
  }
  if(-not[string]::IsNullOrWhiteSpace($FailureClass)){
    $summaryDocument.failure_class=$FailureClass
  }
  if(-not[string]::IsNullOrWhiteSpace($FailureStage)){
    $summaryDocument.failure_stage=$FailureStage
  }
  if($null-ne$ThresholdResultEligible){
    $summaryDocument.threshold_result_eligible=[bool]$ThresholdResultEligible
  }
  Write-RunJson -Path $Summary -Value $summaryDocument
  $retentionActions=$null
  if([int]$document.schema_version-eq 2){
    $retentionActions=Apply-RunArtifactRetention -Python $Python -RepoRoot $RepoRoot -RunConfig $RunConfig
  }
  if(-not[string]::IsNullOrWhiteSpace($ResourceUsagePath)-and
    (Test-Path -LiteralPath $ResourceUsagePath -PathType Leaf)){
    $usage=Get-Content -LiteralPath $ResourceUsagePath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    if([string]$usage.status-eq'running'){
      $usage.status=$Status
    }
    if(-not[string]::IsNullOrWhiteSpace($FailureClass)){
      $usage.failure_class=$FailureClass
    }
    $finalBytes=[int64](Get-ChildItem -LiteralPath $runDir -Recurse -File|
      Measure-Object -Property Length -Sum).Sum
    $usage.final_retained_bytes=$finalBytes
    if([int64]$usage.peak_run_directory_bytes-lt$finalBytes){
      $usage.peak_run_directory_bytes=$finalBytes
    }
    if($finalBytes-gt[int64]$usage.limits.compact_final_retained_bytes){
      $usage.status='resource_budget_exceeded'
      $usage.failure_class='resource_budget_exceeded'
      $usage.limit_name='compact_final_retained_bytes'
      $Status='interrupted'
      Write-RunJson -Path $Summary -Value ([ordered]@{
        schema_version=1;role=$SummaryRole;status='interrupted';reason='Compact final retained-byte budget exceeded.'
        failure_class='resource_budget_exceeded'
      })
    }
    Write-RunJson -Path $ResourceUsagePath -Value $usage
    $AdditionalOutputs+=@($ResourceUsagePath)
  }
  $outputs=@($Summary)+@($AdditionalOutputs|Where-Object{
    -not[string]::IsNullOrWhiteSpace($_)-and(Test-Path -LiteralPath $_ -PathType Leaf)
  })
  if($retentionActions){$outputs+=$retentionActions}
  foreach($relative in @('results','logs','simion')){
    $directory=Join-Path $runDir $relative
    if(Test-Path -LiteralPath $directory -PathType Container){
      $outputs+=@(Get-ChildItem -LiteralPath $directory -Recurse -File|Sort-Object FullName|Select-Object -ExpandProperty FullName)
    }
  }
  Write-VerifiedRunManifest -Python $Python -RepoRoot $RepoRoot -RunConfig $RunConfig `
    -Status $Status -Software $Software -Outputs @($outputs|Select-Object -Unique)
}
