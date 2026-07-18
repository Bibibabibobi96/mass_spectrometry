[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$errors = New-Object System.Collections.Generic.List[string]
$markdownFiles = @(Get-ChildItem -LiteralPath $repoRoot -Recurse -File -Filter '*.md' |
    Where-Object { $_.FullName -notmatch '[\\/](\.git|artifacts|\.venv)[\\/]' } |
    Sort-Object FullName)
$utf8 = New-Object System.Text.UTF8Encoding($false, $true)
$comsolApiPath = Join-Path $repoRoot 'docs\COMSOL_API.md'

function Add-DocError {
    param([string]$Message)
    $errors.Add($Message)
}

foreach ($file in $markdownFiles) {
    $lines = @(Get-Content -LiteralPath $file.FullName -Encoding UTF8)
    $relative = $file.FullName.Substring($repoRoot.Length + 1)
    $h1Count = 0
    $previousLevel = 0
    $inFence = $false

    foreach ($line in $lines) {
        if ($line -match '^\s*(```|~~~)') {
            $inFence = -not $inFence
            continue
        }
        if ($inFence) { continue }
        if ($line -match '^(#{1,6})\s+\S') {
            $level = $Matches[1].Length
            if ($level -eq 1) { $h1Count++ }
            if ($previousLevel -gt 0 -and $level -gt ($previousLevel + 1)) {
                Add-DocError "$relative`: heading jumps H$previousLevel -> H$level ('$line')"
            }
            $previousLevel = $level
        }
    }
    if ($h1Count -ne 1) {
        Add-DocError "$relative`: expected exactly one H1, found $h1Count"
    }

    $raw = [System.IO.File]::ReadAllText($file.FullName, $utf8)
    $matches = [regex]::Matches($raw, '!?(?:\[[^\]]*\])\((?<target>[^)]+)\)')
    foreach ($match in $matches) {
        $target = $match.Groups['target'].Value.Trim().Trim('<', '>')
        if ($target -match '^(?:https?://|mailto:|app://|#)' -or [string]::IsNullOrWhiteSpace($target)) {
            continue
        }
        $pathPart = ($target -split '#', 2)[0]
        $pathPart = [uri]::UnescapeDataString($pathPart)
        $resolved = Join-Path -Path $file.DirectoryName -ChildPath $pathPart
        if (-not (Test-Path -LiteralPath $resolved)) {
            Add-DocError "$relative`: broken relative link '$target'"
        }
    }
}

if (-not (Test-Path -LiteralPath $comsolApiPath -PathType Leaf)) {
    Add-DocError 'missing docs/COMSOL_API.md'
}
else {
    $apiInfo = Get-Item -LiteralPath $comsolApiPath
    $apiRaw = [System.IO.File]::ReadAllText($comsolApiPath, $utf8)
    if ($apiInfo.Length -gt 30000) {
        Add-DocError "docs/COMSOL_API.md: $($apiInfo.Length) bytes exceeds the 30000-byte focused-reference limit"
    }
    if ($apiRaw -match '(?m)^#{2,6}\s+\d+(?:\.\d+)*(?:\.|\s)') {
        Add-DocError 'docs/COMSOL_API.md: numbered headings are forbidden; use stable semantic headings'
    }
    if ($apiRaw -match '(?i)oa[-_ ]?tof|rf_quadrupole|wehnelt_electron_gun|electron_impact_ion_source') {
        Add-DocError 'docs/COMSOL_API.md: project-specific names belong in project documentation'
    }
}

$activeTextFiles = @(Get-ChildItem -LiteralPath $repoRoot -Recurse -File |
    Where-Object {
        $_.FullName -notmatch '[\\/](\.git|artifacts|\.venv|history|legacy)[\\/]' -and
        $_.Extension -in @('.md', '.m', '.py', '.ps1', '.lua')
    })
foreach ($file in $activeTextFiles) {
    $raw = [System.IO.File]::ReadAllText($file.FullName, $utf8)
    if ($raw -match '(?i)COMSOL_(?:API|DEBUGGING)\.md[^\r\n]{0,80}§\s*\d') {
        $relative = $file.FullName.Substring($repoRoot.Length + 1)
        Add-DocError "$relative`: root COMSOL references must use semantic headings, not numeric sections"
    }
}

$historyFiles = @(Get-ChildItem -LiteralPath (Join-Path $repoRoot 'projects') -Recurse -File -Filter '*.md' |
    Where-Object { $_.FullName -match '[\\/]docs[\\/]history[\\/]' })
foreach ($file in $historyFiles) {
    $hasArchiveBanner = Select-String -LiteralPath $file.FullName -SimpleMatch 'DOC_STATUS: ARCHIVED_READ_ONLY' `
        -Encoding UTF8 -Quiet
    if (-not $hasArchiveBanner) {
        $relative = $file.FullName.Substring($repoRoot.Length + 1)
        Add-DocError "$relative`: missing read-only archive banner"
    }
}

foreach ($required in @('AGENTS.md', 'README.md', 'CLAUDE.md')) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $required) -PathType Leaf)) {
        Add-DocError "missing repository authority entry: $required"
    }
}

$projectDirs = @(Get-ChildItem -LiteralPath (Join-Path $repoRoot 'projects') -Directory)
foreach ($projectDir in $projectDirs) {
    $projectState = Join-Path $projectDir.FullName 'docs\PROJECT.md'
    if (Test-Path -LiteralPath $projectState -PathType Leaf) {
        $projectReadme = Join-Path $projectDir.FullName 'README.md'
        if (-not (Test-Path -LiteralPath $projectReadme -PathType Leaf)) {
            Add-DocError "$($projectDir.Name): docs/PROJECT.md exists without project README.md"
        }
        elseif ([System.IO.File]::ReadAllText($projectReadme, $utf8) -notmatch 'docs/PROJECT\.md') {
            Add-DocError "$($projectDir.Name): README.md does not route to docs/PROJECT.md"
        }
    }
}

if ($errors.Count -gt 0) {
    $errors | ForEach-Object { Write-Error $_ }
    throw "Documentation gate failed with $($errors.Count) error(s)."
}

[pscustomobject]@{
    MarkdownFiles = $markdownFiles.Count
    HistoryArchives = $historyFiles.Count
    AuthorityEntries = 3
    ComsolReferenceBytes = if (Test-Path -LiteralPath $comsolApiPath) { (Get-Item $comsolApiPath).Length } else { 0 }
    STATUS = 'PASS'
} | Format-List
