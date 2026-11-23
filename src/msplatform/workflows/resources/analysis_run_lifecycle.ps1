Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-PortableManifestRecord {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][Collections.IDictionary]$Record
    )
    foreach ($field in @('path','bytes','sha256')) {
        if (-not $Record.Contains($field)) {
            throw "$Name record lacks $field."
        }
    }
    $path = [IO.Path]::GetFullPath([string]$Record.path)
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "$Name is missing: $path"
    }
    if ((Get-Item -LiteralPath $path).Length -ne [int64]$Record.bytes) {
        throw "$Name byte count differs: $path"
    }
    if ((Get-RunFileSha256 $path) -cne ([string]$Record.sha256).ToUpperInvariant()) {
        throw "$Name SHA-256 differs: $path"
    }
    return $path
}

function Copy-PortableRunManifestClosure {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$SourceManifest,
        [Parameter(Mandatory)][string]$Destination,
        [Parameter(Mandatory)][string[]]$RequiredInputRoles,
        [Parameter(Mandatory)][Collections.IDictionary]$RequiredOutputRoles,
        [string]$BundleMetadataInputRole = ''
    )
    $manifest = Get-Content -LiteralPath $SourceManifest -Raw -Encoding UTF8 |
        ConvertFrom-Json -AsHashtable
    if ($manifest.status -ne 'success') {
        throw "Portable source manifest is not successful: $SourceManifest"
    }
    $configSource = Assert-PortableManifestRecord `
        -Name 'run config' -Record $manifest.run_config
    $config = Get-Content -LiteralPath $configSource -Raw -Encoding UTF8 |
        ConvertFrom-Json -AsHashtable
    foreach ($field in @('run_id','project','mode')) {
        if ($manifest[$field] -ne $config[$field]) {
            throw "Source manifest and run config $field differ."
        }
    }
    if ($RequiredInputRoles.Count -ne @($RequiredInputRoles | Sort-Object -Unique).Count) {
        throw 'Required input roles contain duplicates.'
    }
    if (-not [string]::IsNullOrWhiteSpace($BundleMetadataInputRole) -and
        $BundleMetadataInputRole -notin $RequiredInputRoles) {
        throw 'Bundle metadata role is not a required input role.'
    }

    $inputRoot = Join-Path $Destination 'manifest_inputs'
    $outputRoot = Join-Path $Destination 'outputs'
    New-Item -ItemType Directory -Path $inputRoot,$outputRoot -Force |
        Out-Null
    $sourceIdentityPath = Join-Path $Destination 'source_run_identity.json'
    $sourceIdentity = [ordered]@{
        schema_version = 1
        role = 'portable_source_run_identity'
        source_manifest = [ordered]@{
            schema_version = $manifest.schema_version
            role = $manifest.role
            bytes = (Get-Item -LiteralPath $SourceManifest).Length
            sha256 = Get-RunFileSha256 $SourceManifest
        }
        run = [ordered]@{
            run_id = $manifest.run_id
            project = $manifest.project
            mode = $manifest.mode
            status = $manifest.status
        }
        run_config = [ordered]@{
            schema_version = $config.schema_version
            role = $config.role
            workflow_id = if ($config.Contains('workflow_id')) {
                [string]$config.workflow_id
            } else {
                ''
            }
        }
    }
    Write-RunJson -Path $sourceIdentityPath -Depth 8 -Value $sourceIdentity
    $sourceTargets = [Collections.Generic.Dictionary[string,string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )

    if (-not [string]::IsNullOrWhiteSpace($BundleMetadataInputRole)) {
        if (-not $manifest.inputs.Contains($BundleMetadataInputRole)) {
            throw "Required bundle input role is missing: $BundleMetadataInputRole"
        }
        $bundleRecord = $manifest.inputs[$BundleMetadataInputRole]
        $bundleSource = Assert-PortableManifestRecord `
            -Name "manifest input $BundleMetadataInputRole" -Record $bundleRecord
        $bundleRoot = Join-Path $inputRoot $BundleMetadataInputRole
        $bundleTarget = Join-Path $bundleRoot ([IO.Path]::GetFileName($bundleSource))
        Copy-VerifiedRunInput -Source $bundleSource -Destination $bundleTarget |
            Out-Null
        $sourceTargets[$bundleSource] = $bundleTarget
        $bundle = Get-Content -LiteralPath $bundleSource -Raw -Encoding UTF8 |
            ConvertFrom-Json -AsHashtable
        if ($bundle.artifacts -isnot [Collections.IList] -or
            $bundle.artifacts.Count -eq 0) {
            throw 'Required bundle metadata has no artifact inventory.'
        }
        $bundleSources = [Collections.Generic.HashSet[string]]::new(
            [StringComparer]::OrdinalIgnoreCase
        )
        $bundleRelatives = [Collections.Generic.HashSet[string]]::new(
            [StringComparer]::OrdinalIgnoreCase
        )
        $bundleTargets = [Collections.Generic.HashSet[string]]::new(
            [StringComparer]::OrdinalIgnoreCase
        )
        foreach ($artifact in $bundle.artifacts) {
            $relative = [string]$artifact.relative_path
            $relativePath = [IO.Path]::GetFullPath((Join-Path $bundleRoot $relative))
            $bundlePrefix = [IO.Path]::GetFullPath($bundleRoot) +
                [IO.Path]::DirectorySeparatorChar
            if ([IO.Path]::IsPathRooted($relative) -or
                -not $relativePath.StartsWith(
                    $bundlePrefix,
                    [StringComparison]::OrdinalIgnoreCase
                )) {
                throw "Bundle artifact path escapes its root: $relative"
            }
            $source = [IO.Path]::GetFullPath(
                (Join-Path (Split-Path -Parent $bundleSource) $relative)
            )
            if (-not $bundleRelatives.Add($relative) -or
                -not $bundleSources.Add($source) -or
                -not $bundleTargets.Add($relativePath)) {
                throw "Bundle artifact inventory contains a duplicate: $relative"
            }
            if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
                throw "Required bundle artifact is missing: $source"
            }
            if ((Get-RunFileSha256 $source) -cne
                ([string]$artifact.sha256).ToUpperInvariant()) {
                throw "Required bundle artifact SHA-256 differs: $source"
            }
            Copy-VerifiedRunInput -Source $source -Destination $relativePath |
                Out-Null
            $sourceTargets[$source] = $relativePath
        }
    }

    $selectedInputs = [ordered]@{}
    $selectedConfigInputs = [ordered]@{}
    foreach ($role in $RequiredInputRoles) {
        if (-not $manifest.inputs.Contains($role) -or
            -not $config.inputs.Contains($role)) {
            throw "Required input role is missing: $role"
        }
        $record = $manifest.inputs[$role]
        $source = Assert-PortableManifestRecord `
            -Name "manifest input $role" -Record $record
        if ($sourceTargets.ContainsKey($source)) {
            $target = $sourceTargets[$source]
        } else {
            $target = Join-Path (Join-Path $inputRoot $role) `
                ([IO.Path]::GetFileName($source))
            Copy-VerifiedRunInput -Source $source -Destination $target |
                Out-Null
            $sourceTargets[$source] = $target
        }
        $record.path = $target
        $selectedInputs[$role] = $record
        $selectedConfigInputs[$role] = $target
    }
    $manifest.inputs = $selectedInputs
    $config.inputs = $selectedConfigInputs
    if ($config.Contains('frozen_python')) {
        $frozen = $config.frozen_python
        if (-not $frozen.Contains('package') -or
            -not $frozen.Contains('execution') -or
            -not $frozen.package.Contains('files') -or
            -not $frozen.execution.Contains('frozen_modules') -or
            -not $frozen.execution.Contains('third_party')) {
            throw 'Frozen Python identity cannot be made portable.'
        }
        $portableFiles = @(
            foreach ($entry in $frozen.package.files) {
                [ordered]@{
                    relative_path = [string]$entry.relative_path
                    sha256 = ([string]$entry.sha256).ToUpperInvariant()
                }
            }
        )
        $portableModules = @(
            foreach ($entry in $frozen.execution.frozen_modules) {
                [ordered]@{name = [string]$entry.name}
            }
        )
        $portableThirdParty = @(
            foreach ($entry in $frozen.execution.third_party) {
                [ordered]@{
                    name = [string]$entry.name
                    version = [string]$entry.version
                }
            }
        )
        $config.frozen_python = [ordered]@{
            package = [ordered]@{files = $portableFiles}
            execution = [ordered]@{
                module = [string]$frozen.execution.module
                frozen_modules = $portableModules
                third_party = $portableThirdParty
            }
        }
    }
    $portableContext = Join-Path $Destination 'portable_context'
    foreach ($key in @($config.Keys)) {
        if ($key -eq 'project_root' -or
            $key -match '(?i)(?:_path|_dir)$') {
            $safeName = ([string]$key -replace '[^A-Za-z0-9_.-]+','_')
            $config[$key] = Join-Path $portableContext $safeName
        }
    }

    $selectedOutputs = [Collections.Generic.List[object]]::new()
    $outputRolePaths = [ordered]@{}
    $closureOutputRoles = [ordered]@{}
    $outputNames = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    foreach ($role in $RequiredOutputRoles.Keys) {
        $filename = [string]$RequiredOutputRoles[$role]
        if ([IO.Path]::GetFileName($filename) -cne $filename -or
            -not $outputNames.Add($filename)) {
            throw "Required output role has an invalid or duplicate filename: $role"
        }
        $matches = @($manifest.outputs | Where-Object {
            [IO.Path]::GetFileName([string]$_.path) -ieq $filename
        })
        if ($matches.Count -ne 1) {
            throw "Required output role $role must resolve exactly once: $filename"
        }
        $record = $matches[0]
        $source = Assert-PortableManifestRecord `
            -Name "manifest output $role" -Record $record
        $target = Join-Path $outputRoot $filename
        Copy-VerifiedRunInput -Source $source -Destination $target |
            Out-Null
        $record.path = $target
        $selectedOutputs.Add($record)
        $outputRolePaths[$role] = $target
        $closureOutputRoles[$role] = $filename
    }
    $manifest.outputs = @($selectedOutputs)
    $manifest.portable_closure = [ordered]@{
        source_run_identity = [ordered]@{
            path = $sourceIdentityPath
            bytes = (Get-Item -LiteralPath $sourceIdentityPath).Length
            sha256 = Get-RunFileSha256 $sourceIdentityPath
        }
        required_input_roles = @($RequiredInputRoles)
        required_output_roles = $closureOutputRoles
    }

    $configPath = Join-Path $Destination 'run_config.json'
    Write-RunJson -Path $configPath -Depth 20 -Value $config
    $manifest.run_config.path = $configPath
    $manifest.run_config.bytes = (Get-Item -LiteralPath $configPath).Length
    $manifest.run_config.sha256 = Get-RunFileSha256 $configPath
    $manifestPath = Join-Path $Destination 'run_manifest.json'
    Write-RunJson -Path $manifestPath -Depth 20 -Value $manifest
    [pscustomobject]@{
        manifest = $manifestPath
        config = $configPath
        output_roles = $outputRolePaths
        files = @(
            Get-ChildItem -LiteralPath $Destination -Recurse -File |
                Sort-Object FullName |
                Select-Object -ExpandProperty FullName
        )
    }
}

function Add-RunInputClosure {
    [CmdletBinding()]
    param([Parameter(Mandatory)][Collections.IDictionary]$Inputs,[Parameter(Mandatory)][string]$Prefix,
        [Parameter(Mandatory)][string[]]$Files)
    $index=0;foreach($path in $Files){$index++;$Inputs["${Prefix}_$('{0:D3}'-f$index)"]=$path}
}
