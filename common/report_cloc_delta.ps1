[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$Base,
  [string]$Current='WORKTREE',
  [string]$ClocExe='cloc',
  [string]$RepoRoot=(Split-Path -Parent $PSScriptRoot)
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'require_powershell7.ps1')

$codeExtensions=@(
  '.py','.m','.ps1','.lua','.gem','.fly2',
  '.json','.toml','.yml','.yaml',
  '.c','.h','.cc','.cpp','.cxx','.hpp',
  '.cs','.java','.js','.jsx','.ts','.tsx',
  '.go','.rs','.rb','.php','.swift','.kt','.kts',
  '.sh','.bash','.zsh','.bat','.cmd'
)
$excludedComponents=@(
  '.git','.venv','artifacts','generated','vendor','vendors',
  'third_party','third-party','thirdparty','run','runs'
)
$filterDescription=(
  "extensions=$($codeExtensions -join ',');" +
  "excluded_components=$($excludedComponents -join ',');" +
  'excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|' +
  'artifacts/projects/<project>/(archive|scratch)/**;' +
  'production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named);' +
  'tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|*Test.m|*.Tests.*;' +
  'unclassified=other_code_below_test_or_tests_path;' +
  'worktree_source=git_tracked_plus_nonignored_untracked'
)

function Invoke-GitText {
  param([Parameter(Mandatory)][string[]]$Arguments)
  $output=@(& git -C $RepoRoot @Arguments)
  if($LASTEXITCODE-ne 0){throw "git failed: git $($Arguments -join ' ')"}
  return @($output)
}

function Resolve-Commit {
  param([Parameter(Mandatory)][string]$Reference)
  $resolved=@(Invoke-GitText @('rev-parse','--verify',"$Reference`^{commit}"))
  if($resolved.Count-ne 1 -or $resolved[0]-notmatch '\A[0-9a-fA-F]{40,64}\z'){
    throw "Could not resolve commit: $Reference"
  }
  return $resolved[0].ToLowerInvariant()
}

function Test-IncludedPath {
  param([Parameter(Mandatory)][string]$RelativePath)
  $normalized=$RelativePath.Replace('\','/')
  $components=@($normalized.Split('/',[StringSplitOptions]::RemoveEmptyEntries))
  $lowerComponents=@($components|ForEach-Object{$_.ToLowerInvariant()})
  for($index=0;$index-lt($lowerComponents.Count-1);$index++){
    if($lowerComponents[$index]-eq'docs' -and $lowerComponents[$index+1]-eq'history'){
      return $false
    }
  }
  if($lowerComponents.Count-gt 0 -and $lowerComponents[0]-eq'scratch'){
    return $false
  }
  if(
    $lowerComponents.Count-gt 3 -and
    $lowerComponents[0]-eq'artifacts' -and
    $lowerComponents[1]-eq'projects' -and
    $lowerComponents[3]-in @('archive','scratch')
  ){
    return $false
  }
  foreach($component in $components){
    if($component.ToLowerInvariant()-in $excludedComponents){return $false}
  }
  return ([IO.Path]::GetExtension($normalized).ToLowerInvariant()-in $codeExtensions)
}

function Get-ExecutionProfileEntrypoints {
  param([Parameter(Mandatory)][string]$Root)
  $rootPath=[IO.Path]::GetFullPath($Root).TrimEnd('\','/')
  $entrypoints=[Collections.Generic.HashSet[string]]::new(
    [StringComparer]::OrdinalIgnoreCase
  )
  foreach($profilePath in @(
    Get-ChildItem -LiteralPath $rootPath -Recurse -File -Filter 'execution_profiles.json'
  )){
    $profileRelative=$profilePath.FullName.Substring($rootPath.Length).
      TrimStart('\','/')
    if(-not(Test-IncludedPath $profileRelative)){continue}
    $document=Get-Content -LiteralPath $profilePath.FullName -Raw -Encoding UTF8 |
      ConvertFrom-Json
    $projectRoot=Split-Path -Parent (Split-Path -Parent $profilePath.FullName)
    foreach($profile in @($document.profiles)){
      foreach($step in @($profile.steps)){
        if($null-eq$step -or [string]::IsNullOrWhiteSpace([string]$step.entrypoint)){continue}
        $full=[IO.Path]::GetFullPath((Join-Path $projectRoot ([string]$step.entrypoint)))
        if($full.StartsWith($rootPath+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){
          $relative=$full.Substring($rootPath.Length).TrimStart('\','/').Replace('\','/')
          $null=$entrypoints.Add($relative)
        }
      }
    }
  }
  Write-Output -NoEnumerate $entrypoints
}

function Get-PathClassification {
  param(
    [Parameter(Mandatory)][string]$RelativePath,
    [Parameter(Mandatory)][AllowEmptyCollection()]
    [Collections.Generic.HashSet[string]]$ActiveEntrypoints
  )
  $normalized=$RelativePath.Replace('\','/')
  $components=@($normalized.Split('/',[StringSplitOptions]::RemoveEmptyEntries))
  $name=[IO.Path]::GetFileName($normalized)
  $extension=[IO.Path]::GetExtension($name).ToLowerInvariant()
  if($ActiveEntrypoints.Contains($normalized)){
    return [pscustomobject]@{category='production';reason='execution_profile_entrypoint'}
  }
  if($extension-eq'.ps1' -and $name-match '(?i)^(?:run_|verify_)'){
    return [pscustomobject]@{category='production';reason='active_powershell_entrypoint'}
  }
  if(@($components|Where-Object{
    $_.ToLowerInvariant()-in @('fixture','fixtures','test_support','testing_support')
  }).Count-gt 0){
    return [pscustomobject]@{category='tests';reason='test_support_path'}
  }
  if(
    ($extension-in @('.py','.ps1','.m','.lua') -and $name-match '(?i)^test_') -or
    ($extension-eq'.py' -and $name-match '(?i)_test\.py$') -or
    ($extension-eq'.m' -and $name-match 'Test\.m$') -or
    $name-match '(?i)\.Tests\.[^.]+$'
  ){
    return [pscustomobject]@{category='tests';reason='test_filename'}
  }
  $inTests=@($components|Where-Object{$_.ToLowerInvariant()-in @('test','tests')}).Count-gt 0
  if($inTests -and @($components|Where-Object{$_.ToLowerInvariant()-eq'support'}).Count-gt 0){
    return [pscustomobject]@{category='production';reason='tests_support_mechanism'}
  }
  if($inTests){
    return [pscustomobject]@{category='unclassified';reason='tests_path_without_stable_rule'}
  }
  return [pscustomobject]@{category='production';reason='non_test_source'}
}

function New-CommitSnapshot {
  param(
    [Parameter(Mandatory)][string]$Commit,
    [Parameter(Mandatory)][string]$Destination,
    [Parameter(Mandatory)][string]$ArchivePath
  )
  & git -C $RepoRoot archive --format=tar "--output=$ArchivePath" $Commit
  if($LASTEXITCODE-ne 0){throw "Could not archive commit: $Commit"}
  & tar -xf $ArchivePath -C $Destination
  if($LASTEXITCODE-ne 0){throw "Could not extract commit snapshot: $Commit"}
}

function Get-SnapshotFiles {
  param(
    [Parameter(Mandatory)][string]$Root,
    [string[]]$RelativePaths=@()
  )
  if($RelativePaths.Count-eq 0){
    $RelativePaths=@(
      Get-ChildItem -LiteralPath $Root -Recurse -File |
        ForEach-Object{$_.FullName.Substring($Root.Length).TrimStart('\','/')}
    )
  }
  $activeEntrypoints=Get-ExecutionProfileEntrypoints -Root $Root
  $records=[Collections.Generic.List[object]]::new()
  foreach($relative in $RelativePaths){
    if(-not(Test-IncludedPath $relative)){continue}
    $full=[IO.Path]::GetFullPath((Join-Path $Root $relative))
    if(-not(Test-Path -LiteralPath $full -PathType Leaf)){continue}
    $classification=Get-PathClassification -RelativePath $relative `
      -ActiveEntrypoints $activeEntrypoints
    $records.Add([pscustomobject]@{
      relative=$relative.Replace('\','/')
      full=$full
      category=$classification.category
      reason=$classification.reason
    })
  }
  return @($records)
}

function Invoke-ClocText {
  param(
    [Parameter(Mandatory)][string[]]$Arguments
  )
  $filePath=$ClocExe
  $argumentsToRun=@($Arguments)
  if([IO.Path]::GetExtension($filePath)-ieq'.ps1'){
    $output=(& $ClocExe @argumentsToRun|Out-String)
    return [pscustomobject]@{
      exit_code=$LASTEXITCODE
      stdout=$output
      stderr=''
    }
  }
  $startInfo=[Diagnostics.ProcessStartInfo]::new()
  $startInfo.FileName=$filePath
  $startInfo.UseShellExecute=$false
  $startInfo.CreateNoWindow=$true
  $startInfo.RedirectStandardOutput=$true
  $startInfo.RedirectStandardError=$true
  if($startInfo.PSObject.Properties.Name-contains'ArgumentList'){
    foreach($argument in $argumentsToRun){[void]$startInfo.ArgumentList.Add($argument)}
  }else{
    $startInfo.Arguments=(($argumentsToRun|ForEach-Object{
      '"'+([string]$_).Replace('"','\"')+'"'
    })-join' ')
  }
  $process=[Diagnostics.Process]::Start($startInfo)
  if($null-eq$process){throw "Could not start cloc: $ClocExe"}
  $stdoutTask=$process.StandardOutput.ReadToEndAsync()
  $stderrTask=$process.StandardError.ReadToEndAsync()
  $process.WaitForExit()
  return [pscustomobject]@{
    exit_code=$process.ExitCode
    stdout=$stdoutTask.GetAwaiter().GetResult()
    stderr=$stderrTask.GetAwaiter().GetResult()
  }
}

function Invoke-ClocSummary {
  param(
    [Parameter(Mandatory)][AllowEmptyCollection()][object[]]$Records,
    [Parameter(Mandatory)][string]$ListPath
  )
  if($Records.Count-eq 0){return @{}}
  @($Records|ForEach-Object{$_.full})|Set-Content -LiteralPath $ListPath -Encoding UTF8
  $result=Invoke-ClocText @('--json','--quiet',"--list-file=$ListPath")
  if($result.exit_code-ne 0){throw "cloc failed for list: $ListPath $($result.stderr.Trim())"}
  $raw=$result.stdout
  try{$document=$raw|ConvertFrom-Json -AsHashtable}catch{throw 'cloc returned invalid JSON.'}
  $summary=@{}
  foreach($language in $document.Keys){
    if($language-in @('header','SUM')){continue}
    $item=$document[$language]
    $summary[$language]=[ordered]@{
      files=[int]$item.nFiles
      blank=[int]$item.blank
      comment=[int]$item.comment
      code=[int]$item.code
    }
  }
  return $summary
}

function Write-DeltaSection {
  param(
    [Parameter(Mandatory)][string]$Category,
    [Parameter(Mandatory)][hashtable]$Baseline,
    [Parameter(Mandatory)][hashtable]$Result
  )
  Write-Output "CATEGORY=$Category"
  $languages=@($Baseline.Keys+$Result.Keys|Sort-Object -Unique)
  $baseSum=@{files=0;blank=0;comment=0;code=0}
  $resultSum=@{files=0;blank=0;comment=0;code=0}
  foreach($language in $languages){
    $before=$(if($Baseline.ContainsKey($language)){$Baseline[$language]}else{@{files=0;blank=0;comment=0;code=0}})
    $after=$(if($Result.ContainsKey($language)){$Result[$language]}else{@{files=0;blank=0;comment=0;code=0}})
    foreach($metric in @('files','blank','comment','code')){
      $baseSum[$metric]+=[int]$before[$metric]
      $resultSum[$metric]+=[int]$after[$metric]
    }
    Write-Output (
      "LANGUAGE=$language " +
      "BASE_FILES=$($before.files) RESULT_FILES=$($after.files) DELTA_FILES=$([int]$after.files-[int]$before.files) " +
      "BASE_BLANK=$($before.blank) RESULT_BLANK=$($after.blank) DELTA_BLANK=$([int]$after.blank-[int]$before.blank) " +
      "BASE_COMMENT=$($before.comment) RESULT_COMMENT=$($after.comment) DELTA_COMMENT=$([int]$after.comment-[int]$before.comment) " +
      "BASE_CODE=$($before.code) RESULT_CODE=$($after.code) DELTA_CODE=$([int]$after.code-[int]$before.code)"
    )
  }
  Write-Output (
    "LANGUAGE=SUM " +
    "BASE_FILES=$($baseSum.files) RESULT_FILES=$($resultSum.files) DELTA_FILES=$($resultSum.files-$baseSum.files) " +
    "BASE_BLANK=$($baseSum.blank) RESULT_BLANK=$($resultSum.blank) DELTA_BLANK=$($resultSum.blank-$baseSum.blank) " +
    "BASE_COMMENT=$($baseSum.comment) RESULT_COMMENT=$($resultSum.comment) DELTA_COMMENT=$($resultSum.comment-$baseSum.comment) " +
    "BASE_CODE=$($baseSum.code) RESULT_CODE=$($resultSum.code) DELTA_CODE=$($resultSum.code-$baseSum.code)"
  )
}

$repoPath=[IO.Path]::GetFullPath($RepoRoot)
if(-not(Test-Path -LiteralPath (Join-Path $repoPath '.git'))){throw "Not a Git worktree: $repoPath"}
$clocCommand=Get-Command $ClocExe -ErrorAction SilentlyContinue
if($null-eq$clocCommand -and $ClocExe-eq'cloc'){
  $originalPath=$env:PATH
  try{
    $env:PATH=@(
      [Environment]::GetEnvironmentVariable('Path','User'),
      [Environment]::GetEnvironmentVariable('Path','Machine')
    )-join[IO.Path]::PathSeparator
    $clocCommand=Get-Command cloc -ErrorAction SilentlyContinue
  }finally{
    $env:PATH=$originalPath
  }
}
if($null-eq$clocCommand){
  throw "CLOC_UNAVAILABLE: '$ClocExe' was not found. Install/authorize cloc; no fallback counter is permitted."
}
$ClocExe=$clocCommand.Source
$versionResult=Invoke-ClocText @('--version')
$clocVersion=$versionResult.stdout.Trim()
if($versionResult.exit_code-ne 0 -or [string]::IsNullOrWhiteSpace($clocVersion)){
  throw "CLOC_UNAVAILABLE: '$ClocExe --version' failed."
}

$baseSha=Resolve-Commit $Base
$temporaryRoot=Join-Path ([IO.Path]::GetTempPath()) ("cloc_delta_"+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporaryRoot|Out-Null
try{
  $baseRoot=Join-Path $temporaryRoot 'base'
  New-Item -ItemType Directory -Path $baseRoot|Out-Null
  New-CommitSnapshot -Commit $baseSha -Destination $baseRoot `
    -ArchivePath (Join-Path $temporaryRoot 'base.tar')
  $baseRecords=Get-SnapshotFiles -Root $baseRoot

  if($Current-eq'WORKTREE'){
    $headSha=Resolve-Commit HEAD
    $currentLabel="WORKTREE(head=$headSha)"
    $paths=@(Invoke-GitText @('ls-files','--cached','--others','--exclude-standard'))
    $currentRecords=Get-SnapshotFiles -Root $repoPath -RelativePaths $paths
  }else{
    $currentSha=Resolve-Commit $Current
    $currentLabel=$currentSha
    $currentRoot=Join-Path $temporaryRoot 'current'
    New-Item -ItemType Directory -Path $currentRoot|Out-Null
    New-CommitSnapshot -Commit $currentSha -Destination $currentRoot `
      -ArchivePath (Join-Path $temporaryRoot 'current.tar')
    $currentRecords=Get-SnapshotFiles -Root $currentRoot
  }

  $summaries=@{}
  foreach($category in @('total','production','tests','unclassified')){
    $baseSelection=$(if($category-eq'total'){$baseRecords}else{@($baseRecords|Where-Object{$_.category-eq$category})})
    $currentSelection=$(if($category-eq'total'){$currentRecords}else{@($currentRecords|Where-Object{$_.category-eq$category})})
    $summaries["base_$category"]=Invoke-ClocSummary -Records @($baseSelection) `
      -ListPath (Join-Path $temporaryRoot "base_$category.txt")
    $summaries["current_$category"]=Invoke-ClocSummary -Records @($currentSelection) `
      -ListPath (Join-Path $temporaryRoot "current_$category.txt")
  }

  Write-Output 'CLOC_DELTA=PASS'
  Write-Output "BASELINE=$baseSha"
  Write-Output "RESULT=$currentLabel"
  Write-Output "CLOC_VERSION=$clocVersion"
  Write-Output "FILTER=$filterDescription"
  foreach($snapshot in @(
    [pscustomobject]@{name='baseline';records=$baseRecords},
    [pscustomobject]@{name='result';records=$currentRecords}
  )){
    foreach($group in @($snapshot.records|Group-Object category,reason|Sort-Object Name)){
      $sample=$group.Group[0]
      Write-Output (
        "CLASSIFICATION_DETAIL SNAPSHOT=$($snapshot.name) " +
        "CATEGORY=$($sample.category) REASON=$($sample.reason) FILES=$($group.Count)"
      )
    }
    foreach($record in @($snapshot.records|Where-Object{$_.category-eq'unclassified'})){
      Write-Output (
        "CLASSIFICATION_WARNING SNAPSHOT=$($snapshot.name) " +
        "PATH=$($record.relative) REASON=$($record.reason)"
      )
    }
  }
  foreach($category in @('total','production','tests','unclassified')){
    Write-DeltaSection -Category $category -Baseline $summaries["base_$category"] `
      -Result $summaries["current_$category"]
  }
}finally{
  if(Test-Path -LiteralPath $temporaryRoot){
    Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
  }
}
