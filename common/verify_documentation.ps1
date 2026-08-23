[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
& (Join-Path $PSScriptRoot 'verify_repository_hygiene.ps1')
$errors = New-Object System.Collections.Generic.List[string]
$markdownFiles = @(Get-ChildItem -LiteralPath $repoRoot -Recurse -File -Filter '*.md' |
    Where-Object { $_.FullName -notmatch '[\\/](\.git|artifacts|\.venv)[\\/]' } |
    Sort-Object FullName)
$utf8 = New-Object System.Text.UTF8Encoding($false, $true)
$comsolApiPath = Join-Path $repoRoot 'docs\COMSOL_API.md'
$visionPath = Join-Path $repoRoot 'docs\VISION.md'
$roadmapPath = Join-Path $repoRoot 'docs\ROADMAP.md'
$rootReadmePath = Join-Path $repoRoot 'README.md'

function Add-DocError {
    param([string]$Message)
    $errors.Add($Message)
}

foreach ($file in $markdownFiles) {
    $lines = @(Get-Content -LiteralPath $file.FullName -Encoding UTF8)
    $relative = $file.FullName.Substring($repoRoot.Length + 1)
    $relativeGit = $relative -replace '\\', '/'
    $requiresGithubMathFence = $relativeGit -in @(
        'projects/single_reflection_oa_tof_mass_analyzer/docs/theory/oaaccelerator_time_focus.md',
        'projects/single_reflection_oa_tof_mass_analyzer/docs/theory/dual_stage_reflectron.md',
        'projects/single_reflection_oa_tof_mass_analyzer/docs/theory/oatof_oaaccelerator_coupling.md',
        'projects/single_reflection_oa_tof_mass_analyzer/docs/theory/z_vz_linear_phase_space_coupling.md'
    )
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

    $fenceMarker = $null
    $fenceInfo = ''
    $inMathFence = $false
    $inDollarDisplayMath = $false
    $githubMathFenceCount = 0
    $lineNumber = 0
    $bareLatexPattern = '\\(?:mathrm|frac|sqrt|tau|Delta|operatorname|left|right|begin|end|text|ell|' +
        'partial|alpha|beta|rho|eta|equiv|propto|int|sum|mu|sigma|omega|cdot|times|pm|approx|' +
        'ne|qquad|quad|bar|mathbf)|[A-Za-z0-9)\]]_\{|\^\{'
    foreach ($line in $lines) {
        $lineNumber++
        if ($null -ne $fenceMarker) {
            if ($line.Trim() -ceq $fenceMarker) {
                $fenceMarker = $null
                $fenceInfo = ''
                $inMathFence = $false
            }
            continue
        }

        if ($line -match '^\s*(?<marker>```|~~~)(?<info>.*)$') {
            $fenceMarker = $Matches['marker']
            $fenceInfo = $Matches['info'].Trim()
            $inMathFence = $fenceInfo -ceq 'math'
            if ($inMathFence -and $fenceMarker -cne '```') {
                Add-DocError "$relative`:$lineNumber`: GitHub math fences must use three backticks"
            }
            if ($inMathFence) { $githubMathFenceCount++ }
            continue
        }

        if ($line.Trim() -ceq '$$') {
            if ($requiresGithubMathFence) {
                Add-DocError "$relative`:$lineNumber`: display math must use a GitHub math fence; dollar display delimiters are forbidden"
            }
            $inDollarDisplayMath = -not $inDollarDisplayMath
            continue
        }
        if ($line -match '\$\$') {
            Add-DocError "$relative`:$lineNumber`: display-math dollar delimiter must be on its own line"
            continue
        }
        if ($inDollarDisplayMath) { continue }

        $withoutCode = [regex]::Replace($line, '`[^`]*`', '')
        $inlineParts = [regex]::Split($withoutCode, '(?<!\\)\$')
        if ((($inlineParts.Count - 1) % 2) -ne 0) {
            Add-DocError "$relative`:$lineNumber`: unclosed inline-math dollar delimiter"
            continue
        }
        $outsideMath = New-Object System.Text.StringBuilder
        for ($partIndex = 0; $partIndex -lt $inlineParts.Count; $partIndex += 2) {
            [void]$outsideMath.Append($inlineParts[$partIndex])
        }
        if ($outsideMath.ToString() -match $bareLatexPattern) {
            Add-DocError "$relative`:$lineNumber`: LaTeX expression appears outside dollar delimiters"
        }
    }
    if ($null -ne $fenceMarker) {
        if ($inMathFence) {
            Add-DocError "$relative`: unclosed GitHub math fence"
        }
        else {
            Add-DocError "$relative`: unclosed fenced code block ($fenceMarker$fenceInfo)"
        }
    }
    if ($inDollarDisplayMath) {
        Add-DocError "$relative`: unclosed display-math dollar delimiter"
    }
    if ($requiresGithubMathFence -and $githubMathFenceCount -eq 0) {
        Add-DocError "$relative`: expected at least one GitHub math fence"
    }

    $raw = [System.IO.File]::ReadAllText($file.FullName, $utf8)
    if ($relativeGit -eq 'projects/single_reflection_oa_tof_mass_analyzer/docs/theory/oaaccelerator_time_focus.md' -and
        $raw -notmatch '(?m)^```math\r?\nW_\{2\}\(x\)=W\(x\)-V_G=E_\{A1\}\(g_1-x\)\.\r?\n```$') {
        Add-DocError "$relative`: the W_2(x) reference equation must remain in a rendered display-math block"
    }
    if ($relativeGit -eq 'projects/single_reflection_oa_tof_mass_analyzer/docs/theory/oaaccelerator_time_focus.md' -and
        $raw -notmatch '(?s)```math\r?\n\\widetilde V_R = V_R-V_X,.*?\r?\n```') {
        Add-DocError "$relative`: the widetilde voltage reference equations must remain in rendered display math"
    }
    if ($relativeGit -eq 'projects/single_reflection_oa_tof_mass_analyzer/docs/theory/dual_stage_reflectron.md' -and
        $raw -notmatch '\$ℓ_1\$、\$ℓ_2\$') {
        Add-DocError "$relative`: reflectron stage lengths must remain inline math, not code or plain text"
    }
    if ($relativeGit -eq 'projects/single_reflection_oa_tof_mass_analyzer/docs/theory/oatof_oaaccelerator_coupling.md' -and
        $raw -notmatch '(?m)^E_\{A1\}=\\frac\{V_R-V_G\}\{g_1\},$') {
        Add-DocError "$relative`: the E_A1 reference equation must remain in rendered display math"
    }
    if ($relativeGit -eq 'projects/single_reflection_oa_tof_mass_analyzer/docs/theory/z_vz_linear_phase_space_coupling.md' -and
        $raw -notmatch '(?s)```math\r?\n\\chi\(x\)=[^\r\n]*\r?\n\\mathcal W\(x\)=[^\r\n]*\r?\n.*?```') {
        Add-DocError "$relative`: the chi(x)/mathcal W(x) reference equations must remain in a rendered display-math block"
    }
    if ($relativeGit -eq 'projects/single_reflection_oa_tof_mass_analyzer/docs/PROJECT.md') {
        if ($raw -notmatch '(?m)^t_\{\\mathrm\{TOF\}\}=t_\{\\mathrm\{detector\}\}-t_\{\\mathrm\{pulse,effective\}\}\.$') {
            Add-DocError "$relative`: the authoritative oa-TOF pulse-relative clock equation is missing"
        }
        if ($raw -notmatch 'instrument_clock_peak_is_resolution_claim=false') {
            Add-DocError "$relative`: the absolute instrument clock resolution-claim prohibition is missing"
        }
    }
    $matches = [regex]::Matches($raw, '!?(?:\[[^\]]*\])\((?<target>[^)]+)\)')
    foreach ($match in $matches) {
        $target = $match.Groups['target'].Value.Trim().Trim('<', '>')
        if ($target -match '^(?:https?://|mailto:|app://|#)' -or [string]::IsNullOrWhiteSpace($target)) {
            continue
        }
        $pathPart = ($target -split '#', 2)[0]
        $anchorPart = if ($target -match '#') { ($target -split '#', 2)[1] } else { '' }
        $pathPart = [uri]::UnescapeDataString($pathPart)
        $resolved = Join-Path -Path $file.DirectoryName -ChildPath $pathPart
        if (-not (Test-Path -LiteralPath $resolved)) {
            Add-DocError "$relative`: broken relative link '$target'"
        }
        elseif (-not [string]::IsNullOrWhiteSpace($anchorPart) -and
                $anchorPart -match '^[A-Za-z0-9][A-Za-z0-9_-]*$') {
            $headingAnchors = @()
            foreach ($heading in @(Get-Content -LiteralPath $resolved -Encoding UTF8 |
                    Where-Object { $_ -match '^#{1,6}\s+(.+?)\s*$' })) {
                $headingText = ([regex]::Match($heading, '^#{1,6}\s+(.+?)\s*$')).Groups[1].Value
                $slug = $headingText.ToLowerInvariant() -replace '[^a-z0-9\s_-]', '' -replace '\s+', '-'
                $headingAnchors += $slug.Trim('-')
            }
            if ($anchorPart.ToLowerInvariant() -notin $headingAnchors) {
                Add-DocError "$relative`: broken Markdown anchor '$target'"
            }
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

$strategyDocs = @(
    @{
        Path = $visionPath
        Label = 'docs/VISION.md'
        Headings = @('## 使命', '## 目标闭环', '## 核心能力', '## 正式交付定义', '## 边界与非承诺')
    },
    @{
        Path = $roadmapPath
        Label = 'docs/ROADMAP.md'
        Headings = @('## 规划原则', '## 设计族与未来项目', '## 阶段一：需求与项目注册',
            '## 阶段二：OA-TOF性能驱动闭环', '## 阶段三：多极杆功能设计',
            '## 阶段四：离子源与电子枪自动化', '## 阶段五：部件集成与仪器级优化',
            '## 阶段六：受控自然语言自治')
    }
)
foreach ($strategyDoc in $strategyDocs) {
    if (-not (Test-Path -LiteralPath $strategyDoc.Path -PathType Leaf)) {
        Add-DocError "missing $($strategyDoc.Label)"
        continue
    }
    $strategyLines = @(Get-Content -LiteralPath $strategyDoc.Path -Encoding UTF8)
    foreach ($heading in $strategyDoc.Headings) {
        if (@($strategyLines | Where-Object { $_ -ceq $heading }).Count -ne 1) {
            Add-DocError "$($strategyDoc.Label): expected exactly one heading '$heading'"
        }
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

$historyFiles = New-Object System.Collections.Generic.List[System.IO.FileInfo]
$historyScopes = @(
    [pscustomobject]@{
        Directory = Get-Item -LiteralPath (Join-Path $repoRoot 'docs\history')
        IndexPath = Join-Path $repoRoot 'docs\AUDITS.md'
        IndexLabel = 'docs/AUDITS.md'
        IndexPrefix = 'history/'
    }
) + @(Get-ChildItem -LiteralPath (Join-Path $repoRoot 'projects') -Directory | ForEach-Object {
    $candidate = Join-Path $_.FullName 'docs\history'
    if (-not (Test-Path -LiteralPath $candidate -PathType Container)) { return }
    $projectPath = $_.FullName
    [pscustomobject]@{
        Directory = Get-Item -LiteralPath $candidate
        IndexPath = Join-Path $projectPath 'README.md'
        IndexLabel = "$($_.Name)/README.md"
        IndexPrefix = 'docs/history/'
    }
}) + @(Get-ChildItem -LiteralPath (Join-Path $repoRoot 'integrations') -Directory | ForEach-Object {
    $candidate = Join-Path $_.FullName 'docs\history'
    if (-not (Test-Path -LiteralPath $candidate -PathType Container)) { return }
    $integrationPath = $_.FullName
    [pscustomobject]@{
        Directory = Get-Item -LiteralPath $candidate
        IndexPath = Join-Path $integrationPath 'docs\HISTORY.md'
        IndexLabel = "$($_.Name)/docs/HISTORY.md"
        IndexPrefix = 'history/'
    }
})
foreach ($historyScope in $historyScopes) {
    $historyDir = $historyScope.Directory
    $indexRaw = if (Test-Path -LiteralPath $historyScope.IndexPath -PathType Leaf) {
        [System.IO.File]::ReadAllText($historyScope.IndexPath, $utf8)
    } else { '' }
    $flatMarkdown = @(Get-ChildItem -LiteralPath $historyDir.FullName -File -Filter '*.md')
    foreach ($file in $flatMarkdown) {
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
        $relative = $payloadFile.FullName.Substring($repoRoot.Length + 1)
        Add-DocError "$relative`: history payload must be inside a same-name manifest directory"
    }

    foreach ($payloadDir in @(Get-ChildItem -LiteralPath $historyDir.FullName -Directory)) {
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

foreach ($required in @('AGENTS.md', 'README.md', 'CLAUDE.md')) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $required) -PathType Leaf)) {
        Add-DocError "missing repository authority entry: $required"
    }
}

$requiredRootReadmeHeadings = @(
    '## 如何使用仓库',
    '## 固定阅读顺序',
    '## 知识权威与写入路由',
    '### 文档权威和冲突优先级',
    '### 新知识写入表',
    '### 跨项目知识提升条件',
    '## 总体目录与项目边界',
    '## 参数权威与单向派生',
    '## 语言职责',
    '## 产物与运行生命周期',
    '### Git / artifacts 边界',
    '### artifacts 目录职责',
    '### artifact标识与文件命名',
    '### run_config / summary / manifest',
    '### success / failed / interrupted / superseded',
    '### 故障调查状态转换',
    '### history 冻结条件',
    '### 保留与清理策略',
    '## 脚本生命周期',
    '### 新代码分类与一次性实现清理',
    '## GUI 与 CAD 门禁',
    '## 通用验证口径',
    '## 工具链与执行入口',
    '## Git 规则',
    '## 任务完成定义'
)
$rootReadmeLines = @(Get-Content -LiteralPath $rootReadmePath -Encoding UTF8)
$rootReadmeRaw = [System.IO.File]::ReadAllText($rootReadmePath, $utf8)
foreach ($strategyLink in @('docs/VISION.md', 'docs/ROADMAP.md')) {
    if ($rootReadmeRaw -notmatch [regex]::Escape($strategyLink)) {
        Add-DocError "README.md: missing strategy-document route '$strategyLink'"
    }
}
$lastHeadingIndex = -1
foreach ($heading in $requiredRootReadmeHeadings) {
    $headingIndices = @(for ($index = 0; $index -lt $rootReadmeLines.Count; $index++) {
        if ($rootReadmeLines[$index] -ceq $heading) { $index }
    })
    if ($headingIndices.Count -ne 1) {
        Add-DocError "README.md: expected exactly one required heading '$heading', found $($headingIndices.Count)"
        continue
    }
    if ($headingIndices[0] -le $lastHeadingIndex) {
        Add-DocError "README.md: required heading is out of order: '$heading'"
    }
    $lastHeadingIndex = $headingIndices[0]
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
    if ($projectReadmeRaw -match '(?m)^##\s+当前(?:状态|结论|进展)') {
        Add-DocError "$($projectDir.Name): current-state sections belong in docs/PROJECT.md, not README.md"
    }

    $softwareDocNames = @('COMSOL.md', 'SIMION.md', 'CAD.md')
    foreach ($softwareDocName in $softwareDocNames) {
        $softwareDocPath = Join-Path $projectDir.FullName (Join-Path 'docs' $softwareDocName)
        if (-not (Test-Path -LiteralPath $softwareDocPath -PathType Leaf)) { continue }
        $softwareDocRaw = [System.IO.File]::ReadAllText($softwareDocPath, $utf8)
        if ($softwareDocRaw -notmatch '\]\(PROJECT\.md(?:#[^)]*)?\)') {
            Add-DocError "$($projectDir.Name)/docs/$softwareDocName`: software document does not return to PROJECT.md"
        }
        foreach ($siblingName in @($softwareDocNames | Where-Object { $_ -ne $softwareDocName })) {
            if ($softwareDocRaw -match ('\]\([^)]*' + [regex]::Escape($siblingName) + '(?:#[^)]*)?\)')) {
                Add-DocError "$($projectDir.Name)/docs/$softwareDocName`: forbidden lateral link to $siblingName"
            }
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
