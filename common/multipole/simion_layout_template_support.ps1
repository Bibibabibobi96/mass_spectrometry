Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-MultipoleSimionLayoutTemplate {
    <#
    .SYNOPSIS
    Resolves one registered SIMION layout and freezes its complete input closure.

    The caller owns the run package. This function only resolves the approved
    structure-only registration and copies its registry, manifest, IOB and CON
    into the caller's already-created input directory.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$TemplateDirectory,
        [string]$RegistryPath = '',
        [string]$ModuleRoot = ''
    )

    if ($null -eq (Get-Command -Name Copy-VerifiedRunInput -ErrorAction SilentlyContinue)) {
        throw 'Resolve-MultipoleSimionLayoutTemplate requires Copy-VerifiedRunInput from run_artifact_support.ps1.'
    }
    $templateDir = [IO.Path]::GetFullPath($TemplateDirectory)
    New-Item -ItemType Directory -Path $templateDir -Force | Out-Null
    $resolutionPath = Join-Path $templateDir 'resolution.json'
    $moduleRootPath = if ([string]::IsNullOrWhiteSpace($ModuleRoot)) {
        [IO.Path]::GetFullPath($RepositoryRoot)
    } else {
        [IO.Path]::GetFullPath($ModuleRoot)
    }
    $arguments = @(
        '-m', 'common.multipole.simion_layout_template',
        '--repo-root', [IO.Path]::GetFullPath($RepositoryRoot),
        '--output', $resolutionPath
    )
    if (-not [string]::IsNullOrWhiteSpace($RegistryPath)) {
        $arguments += @('--registry', [IO.Path]::GetFullPath($RegistryPath))
    }
    Push-Location $moduleRootPath
    $previousPythonPath = $env:PYTHONPATH
    try {
        if ($moduleRootPath -ne [IO.Path]::GetFullPath($RepositoryRoot)) {
            $env:PYTHONPATH = $moduleRootPath
        }
        & $Python @arguments | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw 'Approved shared SIMION layout template resolution failed.'
        }
    } finally {
        if ($null -eq $previousPythonPath) {
            Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        } else {
            $env:PYTHONPATH = $previousPythonPath
        }
        Pop-Location
    }
    $profile = Get-Content -LiteralPath $resolutionPath -Raw -Encoding UTF8 |
        ConvertFrom-Json
    return [ordered]@{
        resolution = $resolutionPath
        profile = $profile
        registry = Copy-VerifiedRunInput -Source $profile.registry_path `
            -Destination (Join-Path $templateDir 'simion_layout_template.json')
        registration_manifest = Copy-VerifiedRunInput -Source $profile.run_manifest.path `
            -Destination (Join-Path $templateDir 'registration_run_manifest.json')
        iob = Copy-VerifiedRunInput -Source $profile.bundle.iob.path `
            -Destination (Join-Path $templateDir 'quad_monolithic.iob')
        con = Copy-VerifiedRunInput -Source $profile.bundle.con.path `
            -Destination (Join-Path $templateDir 'quad_monolithic.con')
    }
}
