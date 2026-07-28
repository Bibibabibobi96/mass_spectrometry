Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-RfConfigInputPath {
    param(
        [Parameter(Mandatory = $true)]$RunConfig,
        [Parameter(Mandatory = $true)][string]$Value
    )
    if ([IO.Path]::IsPathRooted($Value)) {
        return [IO.Path]::GetFullPath($Value)
    }
    return [IO.Path]::GetFullPath((Join-Path ([string]$RunConfig.project_root) $Value))
}

function Assert-RfTransportParticleTableIdentity {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)]$ComsolRunConfig,
        [Parameter(Mandatory = $true)]$SimionRunConfig,
        [Parameter(Mandatory = $true)][string]$ComsolBindingOutput,
        [Parameter(Mandatory = $true)][string]$SimionBindingOutput,
        [string]$ExplicitIon11Path = ''
    )

    if ($ComsolRunConfig.role -ne 'rf_quadrupole_comsol_run_config' -or
        $SimionRunConfig.role -ne 'rf_quadrupole_simion_run_config') {
        throw 'Particle identity accepts only interface transport run-config roles.'
    }
    if ($ComsolRunConfig.mode -ne 'transport_interface_readiness' -or
        $SimionRunConfig.mode -ne 'transport_interface_readiness') {
        throw 'Particle identity accepts only transport_interface_readiness runs.'
    }

    $specifications = @(
        [pscustomobject]@{
            Solver='COMSOL'; Config=$ComsolRunConfig; Representation='ion11'
            Output=$ComsolBindingOutput
        },
        [pscustomobject]@{
            Solver='SIMION'; Config=$SimionRunConfig; Representation='canonical10'
            Output=$SimionBindingOutput
        }
    )
    $bindings = @{}
    foreach ($specification in $specifications) {
        $config = $specification.Config
        foreach ($requiredInput in @(
            'particle_table','consumed_particle_table','source_ion11',
            'source_canonical10','particle_bundle_metadata',
            'particle_source_family','particle_source_distribution'
        )) {
            if (-not $config.inputs.PSObject.Properties[$requiredInput]) {
                throw "$($specification.Solver) run config lacks $requiredInput."
            }
        }
        $consumed = Resolve-RfConfigInputPath $config ([string]$config.inputs.particle_table)
        $declaredConsumed = Resolve-RfConfigInputPath $config ([string]$config.inputs.consumed_particle_table)
        if ($consumed -ne $declaredConsumed) {
            throw "$($specification.Solver) particle_table is not its declared consumed file."
        }
        $arguments = @(
            '-m','projects.rf_quadrupole_ion_optics.analysis.validate_paired_particle_source_binding',
            '--bundle-metadata',(Resolve-RfConfigInputPath $config ([string]$config.inputs.particle_bundle_metadata)),
            '--source-family',(Resolve-RfConfigInputPath $config ([string]$config.inputs.particle_source_family)),
            '--distribution',(Resolve-RfConfigInputPath $config ([string]$config.inputs.particle_source_distribution)),
            '--resolved-design',(Resolve-RfConfigInputPath $config ([string]$config.inputs.resolved_design)),
            '--operating-point',([string]$config.operating_point),
            '--particle-count',([int]$config.particles),
            '--consumed-representation',$specification.Representation,
            '--expected-consumed',$consumed,
            '--output',$specification.Output
        )
        Push-Location $RepoRoot
        try {
            $validationOutput = & $Python @arguments
            if ($LASTEXITCODE -ne 0) {
                throw "$($specification.Solver) paired particle binding validation failed."
            }
            Write-Verbose ($validationOutput -join [Environment]::NewLine)
        }
        finally { Pop-Location }
        $binding = Get-Content -LiteralPath $specification.Output -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($binding.representation_equivalence -ne 'PASS' -or
            $binding.representation -ne $specification.Representation) {
            throw "$($specification.Solver) paired representation equivalence is invalid."
        }
        foreach ($field in @(
            'source_sample_family_sha256','source_family_sha256',
            'distribution_sha256','latent_sha256','coordinate_mapping_version',
            'operating_point_id','particle_count','representation',
            'consumed_sha256','ion11_sha256','canonical10_sha256',
            'representation_equivalence'
        )) {
            if (-not $config.provenance.PSObject.Properties[$field] -or
                [string]$config.provenance.$field -ne [string]$binding.$field) {
                throw "$($specification.Solver) run provenance differs from recomputed $field."
            }
        }
        foreach ($parentField in @(
            'n1000_parent','ion11_n1000_parent','canonical10_n1000_parent'
        )) {
            if (($config.provenance.$parentField | ConvertTo-Json -Depth 8 -Compress) -ne
                ($binding.$parentField | ConvertTo-Json -Depth 8 -Compress)) {
                throw "$($specification.Solver) $parentField identity differs."
            }
        }
        $bindings[$specification.Solver] = $binding
    }

    $commonFields = @(
        'bundle_metadata_sha256','source_sample_family_sha256',
        'source_family_sha256','distribution_sha256','latent_sha256',
        'coordinate_mapping_version','operating_point_id','particle_count',
        'ion11_sha256','canonical10_sha256','representation_equivalence'
    )
    foreach ($field in $commonFields) {
        if ([string]$bindings.COMSOL.$field -ne [string]$bindings.SIMION.$field) {
            throw "COMSOL and SIMION paired source identity differs at $field."
        }
    }
    foreach ($parentField in @('ion11_n1000_parent','canonical10_n1000_parent')) {
        if (($bindings.COMSOL.$parentField | ConvertTo-Json -Depth 8 -Compress) -ne
            ($bindings.SIMION.$parentField | ConvertTo-Json -Depth 8 -Compress)) {
            throw "COMSOL and SIMION $parentField identity differs."
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($ExplicitIon11Path)) {
        $explicitHash = (Get-FileHash -LiteralPath ([IO.Path]::GetFullPath($ExplicitIon11Path)) -Algorithm SHA256).Hash
        if ($explicitHash -ne [string]$bindings.COMSOL.ion11_sha256) {
            throw 'Explicit ION11 table differs from the paired source binding.'
        }
    }
    [pscustomobject]@{
        comsol_consumed_path = [string]$bindings.COMSOL.consumed_path
        simion_consumed_path = [string]$bindings.SIMION.consumed_path
        ion11_path = [string]$bindings.COMSOL.ion11_path
        canonical10_path = [string]$bindings.SIMION.canonical10_path
        source_sample_family_sha256 = [string]$bindings.COMSOL.source_sample_family_sha256
        latent_sha256 = [string]$bindings.COMSOL.latent_sha256
        coordinate_mapping_version = [string]$bindings.COMSOL.coordinate_mapping_version
        particle_count = [int]$bindings.COMSOL.particle_count
        ion11_sha256 = [string]$bindings.COMSOL.ion11_sha256
        canonical10_sha256 = [string]$bindings.COMSOL.canonical10_sha256
        ion11_n1000_parent = $bindings.COMSOL.ion11_n1000_parent
        canonical10_n1000_parent = $bindings.COMSOL.canonical10_n1000_parent
    }
}
