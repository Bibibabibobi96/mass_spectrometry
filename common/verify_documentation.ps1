[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$errors = New-Object System.Collections.Generic.List[string]
$markdownFiles = @(Get-ChildItem -LiteralPath $repoRoot -Recurse -File -Filter '*.md' |
    Where-Object { $_.FullName -notmatch '[\\/](\.git|artifacts|\.venv)[\\/]' } |
    Sort-Object FullName)
$utf8 = New-Object System.Text.UTF8Encoding($false, $true)

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
    STATUS = 'PASS'
} | Format-List
