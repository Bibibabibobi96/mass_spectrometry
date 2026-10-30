[CmdletBinding()]
param(
    [switch]$StructureOnly,
    [string]$PythonExe = '',
    [switch]$AuditHistory,
    [string[]]$ChangedPath=@()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
# StructureOnly is read-only and does not acquire a host lease.
$hostExecutionLease = $null
if (-not $StructureOnly) {
    . (Join-Path $PSScriptRoot 'host_execution_lease.ps1')
    $hostExecutionLease = Enter-HostExecutionLease -Role GATE
}
try {
if (-not $PythonExe) {
    $venvPython = Join-Path $repoRoot '.venv/Scripts/python.exe'
    $PythonExe = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { (Get-Command python -ErrorAction Stop).Source }
}
$pythonVersion = (& $PythonExe -c 'import sys; print(str(sys.version_info.major) + "." + str(sys.version_info.minor))').Trim()
if ($pythonVersion -ne '3.11') { throw "Documentation gate requires Python 3.11, found $pythonVersion" }
$errors = New-Object System.Collections.Generic.List[string]
$markdownFiles = @(Get-ChildItem -LiteralPath $repoRoot -Recurse -File -Filter '*.md' |
    Where-Object { $_.FullName.Substring($repoRoot.Length + 1) -notmatch '(^|[\\/])(\.git|artifacts|\.venv)[\\/]' } |
    Sort-Object FullName)
$utf8 = New-Object System.Text.UTF8Encoding($false, $true)
$rootReadmePath = Join-Path $repoRoot 'README.md'
function Add-DocError {
    param([string]$Message)
    $errors.Add($Message)
}

$linkArguments=@((Join-Path $PSScriptRoot 'documentation_links.py'),'--root',$repoRoot)
if($AuditHistory){$linkArguments+='--audit-history'}
foreach($path in $ChangedPath){$linkArguments+=@('--changed-path',$path)}
& $PythonExe @linkArguments
if($LASTEXITCODE-ne0){Add-DocError 'Markdown links/anchors failed; see per-file diagnostics above'}

$historyFiles = New-Object System.Collections.Generic.List[System.IO.FileInfo]
if($AuditHistory -or $ChangedPath.Count){
$historyScopes = @(
    [pscustomobject]@{
        Directory = Get-Item -LiteralPath (Join-Path $repoRoot 'docs\history')
        IndexPath = Join-Path $repoRoot 'docs\AUDITS.md'
        IndexLabel = 'docs/AUDITS.md'
        IndexPrefix = 'history/'
    }
    if (Test-Path -LiteralPath (Join-Path $repoRoot 'integrations\docs\history') -PathType Container) {
        [pscustomobject]@{
            Directory = Get-Item -LiteralPath (Join-Path $repoRoot 'integrations\docs\history')
            IndexPath = Join-Path $repoRoot 'integrations\docs\history\README.md'
            IndexLabel = 'integrations/docs/history/README.md'
            IndexPrefix = ''
        }
    }
) + @(Get-ChildItem -LiteralPath (Join-Path $repoRoot 'projects') -Directory | ForEach-Object {
    $candidate = Join-Path $_.FullName 'docs\history'
    if (-not (Test-Path -LiteralPath $candidate -PathType Container)) { return }
    $projectPath = $_.FullName
    [pscustomobject]@{
        Directory = Get-Item -LiteralPath $candidate
        IndexPath = Join-Path $candidate 'README.md'
        IndexLabel = "$($_.Name)/docs/history/README.md"
        IndexPrefix = ''
    }
})
foreach ($historyScope in $historyScopes) {
    $historyDir = $historyScope.Directory
    $historyPrefix=[IO.Path]::GetRelativePath($repoRoot,$historyDir.FullName).Replace('\','/')+'/'
    $selectedHistory=@($ChangedPath|ForEach-Object{$_.Replace('\','/')}|Where-Object{$_.StartsWith($historyPrefix)})
    if(-not$AuditHistory-and-not$selectedHistory.Count){continue}
    $indexRaw = if (Test-Path -LiteralPath $historyScope.IndexPath -PathType Leaf) {
        [System.IO.File]::ReadAllText($historyScope.IndexPath, $utf8)
    } else { '' }
    $flatMarkdown = @(Get-ChildItem -LiteralPath $historyDir.FullName -File -Filter '*.md' |
        Where-Object { $_.Name -ne 'README.md' })
    foreach ($file in $flatMarkdown) {
        if(-not$AuditHistory-and([IO.Path]::GetRelativePath($repoRoot,$file.FullName).Replace('\','/')-notin$selectedHistory)){continue}
        $historyFiles.Add($file)
        $hasArchiveBanner = Select-String -LiteralPath $file.FullName -SimpleMatch `
            'DOC_STATUS: ARCHIVED_READ_ONLY' -Encoding UTF8 -Quiet
        if (-not $hasArchiveBanner) {
            $relative = $file.FullName.Substring($repoRoot.Length + 1)
            Add-DocError "$relative`: missing read-only archive banner"
        }
        $historyEntry = $historyScope.IndexPrefix + $file.Name
        if ($indexRaw -notmatch [regex]::Escape($historyEntry)) {
            $relative = $file.FullName.Substring($repoRoot.Length + 1)
            Add-DocError "$relative`: $($historyScope.IndexLabel) does not index '$historyEntry'"
        }
    }

    $rootPayloadFiles = @(Get-ChildItem -LiteralPath $historyDir.FullName -File |
        Where-Object { $_.Extension -ne '.md' })
    foreach ($payloadFile in $rootPayloadFiles) {
        if(-not$AuditHistory-and([IO.Path]::GetRelativePath($repoRoot,$payloadFile.FullName).Replace('\','/')-notin$selectedHistory)){continue}
        $relative = $payloadFile.FullName.Substring($repoRoot.Length + 1)
        Add-DocError "$relative`: history payload must be inside a same-name manifest directory"
    }

    # Retired project packages are verified against fixed Git source bytes by
    # documentation_links.py. Their nested paths preserve original identities.
    # Retired campaign archives are byte-preserved machine records whose
    # dedicated archive indexes own their path-to-SHA mappings.  They are not
    # publication payload sets and therefore do not use the Markdown manifest
    # convention enforced below.
    $historyRelative = [IO.Path]::GetRelativePath($repoRoot, $historyDir.FullName).Replace('\', '/')
    foreach ($payloadDir in @(Get-ChildItem -LiteralPath $historyDir.FullName -Directory |
        Where-Object { $_.Name -ne 'retired_campaigns' })) {
        if ($payloadDir.Name -eq 'retired_projects' -and
            $historyRelative -match '^projects/[^/]+/docs/history$') { continue }
        if(-not$AuditHistory-and-not@($selectedHistory|Where-Object{$_.StartsWith($historyPrefix+$payloadDir.Name+'/')-or$_-eq($historyPrefix+$payloadDir.Name+'.md')}).Count){continue}
        $manifestPath = Join-Path $historyDir.FullName ($payloadDir.Name + '.md')
        if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
            $relative = $payloadDir.FullName.Substring($repoRoot.Length + 1)
            Add-DocError "$relative`: payload directory has no same-name flat Markdown manifest"
            continue
        }
        $manifestRaw = [System.IO.File]::ReadAllText($manifestPath, $utf8)
        # Large immutable payload sets may use a machine-readable JSON
        # migration manifest instead of duplicating 100+ links in Markdown.
        # Its entries and hashes are still checked below as part of the same
        # flat manifest directory.
        $machineManifestRaw = ($manifestRaw + "`n" + (
            @(
                Get-ChildItem -LiteralPath $payloadDir.FullName -Recurse -File |
                    Where-Object { $_.Name -match '(^INDEX\.md$|manifest.*\.json$)' } |
                    ForEach-Object { [System.IO.File]::ReadAllText($_.FullName, $utf8) }
            ) -join "`n"))
        $checksumPath = Join-Path $payloadDir.FullName 'SHA256SUMS.txt'
        $checksumRaw = if (Test-Path -LiteralPath $checksumPath -PathType Leaf) {
            [System.IO.File]::ReadAllText($checksumPath, $utf8)
        } else { '' }
        foreach ($payloadFile in @(Get-ChildItem -LiteralPath $payloadDir.FullName -Recurse -File)) {
            $relative = $payloadFile.FullName.Substring($repoRoot.Length + 1)
            $relativeGit = $relative -replace '\\', '/'
            $textAttribute = & git -C $repoRoot check-attr text -- $relativeGit
            if ($LASTEXITCODE -ne 0 -or $textAttribute -notmatch ': text: unset$') {
                Add-DocError "$relative`: frozen history payload must be marked -text in .gitattributes"
            }
            # A nested payload collection may retain its immutable INDEX.md
            # migration map.  It is evidence metadata, not a current document;
            # all other Markdown and all runtime caches remain forbidden.
            $isPayloadIndex = $payloadFile.Name -eq 'INDEX.md'
            if ((($payloadFile.Extension -eq '.md') -and -not $isPayloadIndex) -or
                $payloadFile.Extension -eq '.pyc' -or
                $payloadFile.FullName -match '[\\/]__pycache__[\\/]') {
                Add-DocError "$relative`: forbidden Markdown or runtime cache in history payload"
            }
            if ($isPayloadIndex) { continue }
            $payloadRelative = [IO.Path]::GetRelativePath(
                $payloadDir.FullName, $payloadFile.FullName
            ).Replace('\', '/')
            $payloadEntry = $payloadDir.Name + '/' + $payloadRelative
            $checksumLinksPayload = $checksumRaw -match ('(?im)(?:\s|\*)+' + [regex]::Escape($payloadFile.Name) + '\s*$')
            if ($payloadFile.Name -notin @('SHA256SUMS.txt') -and
                $payloadFile.Name -notmatch 'manifest' -and -not $checksumLinksPayload -and
                $machineManifestRaw -notmatch [regex]::Escape($payloadEntry) -and
                $machineManifestRaw -notmatch [regex]::Escape($payloadFile.Name)) {
                Add-DocError "$relative`: same-name manifest does not link payload '$payloadEntry'"
            }
            if ($payloadFile.Name -ne 'SHA256SUMS.txt' -and
                $payloadFile.Name -notmatch 'manifest') {
                $actualHash = (Get-FileHash -LiteralPath $payloadFile.FullName -Algorithm SHA256).Hash
                $checksumPattern = '(?im)^' + [regex]::Escape($actualHash) + '\s+\*?' +
                    [regex]::Escape($payloadFile.Name) + '\s*$'
                if ($machineManifestRaw -notmatch [regex]::Escape($actualHash) -and
                    $checksumRaw -notmatch $checksumPattern) {
                    Add-DocError "$relative`: SHA-256 is absent or stale in manifest/checksum list"
                }
            }
        }
    }
}

}

foreach ($required in @('AGENTS.md', 'README.md', 'CLAUDE.md')) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $required) -PathType Leaf)) {
        Add-DocError "missing repository authority entry: $required"
    }
}

$rootReadmeRaw = [System.IO.File]::ReadAllText($rootReadmePath, $utf8)
$documentationIndexPath = Join-Path $repoRoot 'docs/README.md'
$navigationRaw = $rootReadmeRaw
if (Test-Path -LiteralPath $documentationIndexPath -PathType Leaf) {
    $navigationRaw += "`n" + [System.IO.File]::ReadAllText($documentationIndexPath, $utf8)
}
$indexRoutes = @('docs/README.md', 'AGENTS.md')
foreach ($route in $indexRoutes) {
    if ($rootReadmeRaw -notmatch [regex]::Escape($route)) {
        Add-DocError "README.md: missing primary route '$route'"
    }
}
$authorityRoutes = @(
    'docs/REPOSITORY_ARCHITECTURE.md', 'docs/LIFECYCLE.md', 'docs/OPERATIONS.md',
    'docs/DEVELOPMENT_STANDARDS.md', 'docs/PLOTTING_STANDARDS.md', 'docs/COMPONENT_CONNECTION_ARCHITECTURE.md',
    'docs/VISION.md', 'docs/ROADMAP.md', 'AGENTS.md'
)
foreach ($route in $authorityRoutes) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $route) -PathType Leaf)) {
        Add-DocError "missing authority document '$route'"
    }
    $navigationRoute = if ($route.StartsWith('docs/')) { $route.Substring(5) } else { $route }
    if ($navigationRaw -notmatch [regex]::Escape($navigationRoute)) {
        Add-DocError "README.md/docs/README.md: missing authority route '$route'"
    }
}
# Check responsibility boundaries by routes, not a fixed heading count or prose order.
foreach ($name in @('REPOSITORY_ARCHITECTURE', 'LIFECYCLE', 'OPERATIONS')) {
    $authorityPath = Join-Path $repoRoot "docs/$name.md"
    if (-not (Test-Path -LiteralPath $authorityPath -PathType Leaf)) { continue }
    $authorityRaw = [System.IO.File]::ReadAllText($authorityPath, $utf8)
    foreach ($route in @('../README.md', '../AGENTS.md')) {
        if ($authorityRaw -notmatch [regex]::Escape($route)) {
            Add-DocError "docs/$name.md: missing responsibility-boundary route '$route'"
        }
    }
}

$projectDirs = @(Get-ChildItem -LiteralPath (Join-Path $repoRoot 'projects') -Directory)
foreach ($projectDir in $projectDirs) {
    $projectState = Join-Path $projectDir.FullName 'docs\PROJECT.md'
    $projectReadme = Join-Path $projectDir.FullName 'README.md'
    if (-not (Test-Path -LiteralPath $projectReadme -PathType Leaf)) {
        Add-DocError "$($projectDir.Name): missing project README.md"
        continue
    }
    if (-not (Test-Path -LiteralPath $projectState -PathType Leaf)) {
        Add-DocError "$($projectDir.Name): missing docs/PROJECT.md current-state authority"
        continue
    }
    $projectReadmeRaw = [System.IO.File]::ReadAllText($projectReadme, $utf8)
    if ($projectReadmeRaw -notmatch 'docs/PROJECT\.md') {
        Add-DocError "$($projectDir.Name): README.md does not route to docs/PROJECT.md"
    }
    if ($projectReadmeRaw -notmatch '\.\./\.\./README\.md') {
        Add-DocError "$($projectDir.Name): README.md does not route to the repository README authority"
    }

}

if ($errors.Count -gt 0) {
    $errors | ForEach-Object { Write-Error $_ -ErrorAction Continue }
    throw "Documentation gate failed with $($errors.Count) error(s)."
}

[pscustomobject]@{
    MarkdownFiles = $markdownFiles.Count
    HistoryArchives = $historyFiles.Count
    AuthorityEntries = $authorityRoutes.Count
    Mode = if ($StructureOnly) { 'StructureOnly' } else { 'Full' }
    STATUS = 'PASS'
} | Format-List
} finally {
    if (-not $StructureOnly) { Exit-HostExecutionLease -Lease $hostExecutionLease }
}
