Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

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
  try{
    Write-RunManifest -Python $Python -RepoRoot $RepoRoot -RunConfig $RunConfig `
      -Status $Status -Software $Software -Manifest $Manifest -Outputs $Outputs -PassThru
  }catch{
    throw "Could not write $Status run manifest."
  }
  & $Python (Join-Path $RepoRoot 'common\contracts\verify_run_manifest.py') `
    $Manifest --require-status $Status
  if($LASTEXITCODE-ne 0){throw "Could not verify $Status run manifest."}
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
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$ArtifactRoot,
    [Parameter(Mandatory)][string]$RunId,
    [Parameter(Mandatory)][string]$Project,
    [Parameter(Mandatory)][string]$Mode,
    [Parameter(Mandatory)][string[]]$Software,
    [string[]]$AdditionalDirectories=@()
  )
  $python=Join-Path $RepoRoot '.venv\Scripts\python.exe'
  if(-not(Test-Path -LiteralPath $python -PathType Leaf)){throw "Run Python environment is missing: $python"}
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
  Write-RunJson -Path $package.run_config -Value ([ordered]@{
    schema_version=1;run_id=$RunId;project=$Project;mode=$Mode;project_root=$RepoRoot;inputs=[ordered]@{};
    parameters=[ordered]@{lifecycle_stage='run_package_initialized'};formal_gate_passed=$false
  })
  Write-RunJson -Path $package.summary -Value ([ordered]@{
    schema_version=1;role='run_package_initialization_summary';status='interrupted';
    reason='Run package initialized; task-specific inputs are not frozen yet.'
  })
  Write-RunManifest -Python $python -RepoRoot $RepoRoot -RunConfig $package.run_config -Status interrupted -Software $Software
  return [pscustomobject]$package
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

function Complete-FailedRun {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$RunConfig,[Parameter(Mandatory)][string]$Summary,
    [Parameter(Mandatory)][string]$SummaryRole,[Parameter(Mandatory)][string]$Reason,
    [Parameter(Mandatory)][string[]]$Software
  )
  $document=Get-Content -LiteralPath $RunConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if(-not $document.Contains('inputs')){$document.inputs=[ordered]@{}}
  $known=@($document.inputs.Values|ForEach-Object{if($_ -is [string]){[IO.Path]::GetFullPath($_)}})
  $inputDir=Join-Path (Split-Path -Parent $RunConfig) 'inputs';$index=0
  if(Test-Path -LiteralPath $inputDir -PathType Container){foreach($file in Get-ChildItem -LiteralPath $inputDir -File|Sort-Object Name){
    if($known-notcontains$file.FullName){$index+=1;$document.inputs[("recovered_input_{0:D3}"-f$index)]=$file.FullName}
  }}
  Write-RunJson -Path $RunConfig -Value $document
  Write-RunJson -Path $Summary -Value ([ordered]@{schema_version=1;role=$SummaryRole;status='failed';reason=$Reason})
  Write-RunManifest -Python $Python -RepoRoot $RepoRoot -RunConfig $RunConfig -Status failed -Software $Software
}
