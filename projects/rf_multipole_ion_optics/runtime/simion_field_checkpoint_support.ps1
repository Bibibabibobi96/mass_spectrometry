Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '..\..\..\common\contracts\run_artifact_support.ps1')
. (Join-Path $PSScriptRoot '..\..\..\common\simion\short_pa_path_support.ps1')

function New-RfSimionFieldIdentity {
    param([Parameter(Mandatory)][string]$GemPath,[Parameter(Mandatory)][string]$SimionExe,
          [Parameter(Mandatory)][int[]]$Grid,[Parameter(Mandatory)][double[]]$CellMm,
          [Parameter(Mandatory)][int[]]$ResponseIds,[string[]]$GemIncludePaths=@(),
          [Parameter(Mandatory)][string[]]$Gem2PaArguments,[Parameter(Mandatory)][string[]]$RefineArguments)
    # The generated GEM contains all native geometry and grid inputs. Remove
    # only its known resolved-document provenance line, never native statements.
    function Read-RfFieldGemText([string]$Path){
        return (Get-Content -LiteralPath $Path -Encoding ASCII|Where-Object{$_-notmatch'^; (?:parent_resolved_sha256=|resolved_design_sha256=|Generated from .*; do not edit\.$)'})-join"`n"
    }
    function Convert-RfFieldGemDigest([string]$Text){
        $sha=[Security.Cryptography.SHA256]::Create()
        try{return [Convert]::ToHexString($sha.ComputeHash([Text.Encoding]::ASCII.GetBytes($Text)))}finally{$sha.Dispose()}
    }
    $gem=Read-RfFieldGemText $GemPath
    $surface=[regex]::Matches($gem,'\bsurface=(fractional|none)\b')
    if($surface.Count-ne1-or$surface[0].Groups[1].Value-ne'fractional'){throw 'RF field checkpoint requires the existing fractional surface.'}
    if($Grid.Count-ne3-or$CellMm.Count-ne3-or@($Grid|Where-Object{$_-lt1}).Count-or@($CellMm|Where-Object{-not[double]::IsFinite($_)-or$_-le0}).Count){throw 'RF field grid/cell identity differs.'}
    $gemSha=Convert-RfFieldGemDigest $gem
    $includes=[ordered]@{}
    foreach($path in $GemIncludePaths){$name=[IO.Path]::GetFileName($path);if($includes.Contains($name)){throw 'Duplicate RF GEM include.'};$includes[$name]=Convert-RfFieldGemDigest (Read-RfFieldGemText $path)}
    $declared=@([regex]::Matches($gem,'\binclude\s*\(\s*([^\)]+)\)')|ForEach-Object{$_.Groups[1].Value.Trim().Trim('"').Trim("'")}|Sort-Object -Unique)
    if(($declared-join'|')-cne(@($includes.Keys|Sort-Object)-join'|')){throw 'RF field identity must bind every declared GEM include.'}
    return [ordered]@{schema_version=1;role='multipole_simion_field_identity';gem_sha256=$gemSha;
        gem_includes=$includes;grid=@($Grid);cell_mm=@($CellMm);surface='fractional';response_ids=@($ResponseIds|Sort-Object -Unique);
        simion_executable_sha256=(Get-FileHash -LiteralPath $SimionExe -Algorithm SHA256).Hash;
        gem2pa_arguments=@($Gem2PaArguments);refine_arguments=@($RefineArguments)}
}

function Write-RfSimionFieldCheckpoint {
    param([Parameter(Mandatory)][string]$RunDirectory,[Parameter(Mandatory)][string]$IdentityPath,
          [Parameter(Mandatory)][string]$IobPath,[Parameter(Mandatory)]$NativeOperations,
          [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$RepoRoot)
    $result=Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
        $OutputEncoding=[Text.UTF8Encoding]::new($false)
        $output=(ConvertTo-Json -InputObject @($NativeOperations|ForEach-Object{$_}) -Depth 30 -Compress)|& $Python -m projects.rf_multipole_ion_optics.runtime.simion_field_checkpoint write --run $RunDirectory --identity $IdentityPath --iob $IobPath
        if($LASTEXITCODE-ne0){throw 'RF field checkpoint native completion or inventory is invalid.'}
        ($output-join"`n")|ConvertFrom-Json -Depth 50
    }
    # Only the original producer changes attributes, after native construction
    # has exited. A child never changes original family/IOB bytes or attributes.
    foreach($path in $result.output_paths|Where-Object{$_-ne$result.checkpoint_path}){
        $item=Get-Item -LiteralPath $path
        if(-not$item.IsReadOnly){
            $stream=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
            try{$stream.Flush($true)}finally{$stream.Dispose()}
            $item.IsReadOnly=$true
        }
    }
    return $result
}

function Read-RfSimionFieldCheckpoint {
    param([Parameter(Mandatory)][string]$SourceRunPath,[Parameter(Mandatory)][string]$IdentityPath,
          [Parameter(Mandatory)][string]$ProgramSourcePath,[Parameter(Mandatory)][string]$Python,
          [Parameter(Mandatory)][string]$RepoRoot,[Parameter(Mandatory)][string]$TemplateIobPath,
          [Parameter(Mandatory)][string]$TemplateConPath)
    return Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
        $output=& $Python -m projects.rf_multipole_ion_optics.runtime.simion_field_checkpoint read --run $SourceRunPath --identity $IdentityPath --program $ProgramSourcePath --template-iob $TemplateIobPath --template-con $TemplateConPath
        if($LASTEXITCODE-ne0){throw 'RF field checkpoint source identity is invalid.'}
        ($output-join"`n")|ConvertFrom-Json -Depth 50
    }
}

function Protect-RfSimionFieldCheckpoint {
    param([Parameter(Mandatory)]$Checkpoint,[string[]]$ExistingProtectedRuns=@())
    $context=[pscustomobject]@{streams=[Collections.Generic.List[IDisposable]]::new();pa_records=[Collections.Generic.List[object]]::new()}
    try{
        $producer=Split-Path -Parent ([string]$Checkpoint.producer_manifest)
        $already=@($ExistingProtectedRuns|ForEach-Object{[IO.Path]::GetFullPath($_)})
        if([IO.Path]::GetFullPath($producer)-notin$already){
            $context.streams.Add((Enter-RunTerminalConsumptionGuard -RunDirectory $producer))
            foreach($name in @('run_manifest.json','run_config.json')){
                $context.streams.Add([IO.File]::Open((Join-Path $producer $name),[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read))
            }
        }
        if((Get-FileHash -LiteralPath $Checkpoint.producer_manifest -Algorithm SHA256).Hash-ne$Checkpoint.producer_manifest_sha256){throw 'RF field source manifest changed before protection.'}
        foreach($record in @($Checkpoint.small_records)+@($Checkpoint.payload_records)){
            $path=[IO.Path]::GetFullPath([string]$record.path)
            if($path-match'\.pa(?:#|\d+|-surf)$'){
                $guard=Protect-ImmutablePaSource -Source $path -ExpectedBytes ([long]$record.bytes) -ExpectedSha256 ([string]$record.sha256)
                $context.pa_records.Add([pscustomobject]@{path=$path;owns_guard=(-not$guard.already_protected)})
            }else{
                $stream=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
                $context.streams.Add($stream)
                if($stream.Length-ne[long]$record.bytes-or(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash-ne[string]$record.sha256){throw "RF checkpoint companion changed before protection: $path"}
            }
        }
        return $context
    }catch{
        $originalFailure=$_
        try{Close-RfSimionFieldCheckpointGuard -Context $context}catch{$originalFailure.Exception.Data['field_guard_cleanup_error']=[string]$_}
        throw $originalFailure
    }
}

function Close-RfSimionFieldCheckpointGuard {
    param([Parameter(Mandatory)]$Context)
    $failures=[Collections.Generic.List[string]]::new()
    foreach($record in $Context.pa_records){if($record.owns_guard){try{Unprotect-ImmutablePaSource -Source $record.path|Out-Null}catch{$failures.Add([string]$_)}}}
    $Context.pa_records.Clear()
    for($index=$Context.streams.Count-1;$index-ge0;$index--){try{$Context.streams[$index].Dispose()}catch{$failures.Add([string]$_)}}
    $Context.streams.Clear()
    if($failures.Count){throw ($failures-join'; ')}
}
