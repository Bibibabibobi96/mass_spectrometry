Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:RfComsolNumericsIdentity = [ordered]@{
    schema_version=1;role='rf_quadrupole_comsol_solver_numerics'
    contract_id='rf_quadrupole.comsol_solver_numerics.v1'
    status='current_candidate_solver_numerics';current=$true
    logical_sha256='49DB3951BCFD42FAE6C78917D86ABC218AC5F4C1543D74FC1A4B0AC564EBBA2D'
}

function Get-RfComsolRequiredProperty {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Property,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $member = $Object.PSObject.Properties[$Property]
    if ($null -eq $member -or $null -eq $member.Value) {
        throw "$Name is missing."
    }
    if ($member.Value -is [Array]) {
        Write-Output -NoEnumerate $member.Value
    } else {
        return $member.Value
    }
}

function Get-RfComsolRequiredFiniteNumber {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Property,
        [Parameter(Mandatory = $true)][string]$Name,
        [switch]$Positive,
        [switch]$Integer
    )
    $raw = Get-RfComsolRequiredProperty -Object $Object -Property $Property -Name $Name
    $jsonNumberTypes = @(
        [byte],[sbyte],[int16],[uint16],[int32],[uint32],[int64],[uint64],
        [single],[double],[decimal]
    )
    if ($raw -is [bool] -or $raw.GetType() -notin $jsonNumberTypes) {
        throw "$Name must be a JSON number."
    }
    $value = [double]$raw
    if ([double]::IsNaN($value) -or [double]::IsInfinity($value)) {
        throw "$Name must be finite."
    }
    if ($Positive -and $value -le 0) {
        throw "$Name must be positive."
    }
    if ($Integer -and $value -ne [math]::Truncate($value)) {
        throw "$Name must be an integer."
    }
    return $value
}

function ConvertTo-RfComsolCanonicalValue {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)]$Value)
    if ($null -eq $Value) {
        throw 'COMSOL solver-numerics contract must not contain null.'
    }
    if ($Value -is [Collections.IDictionary]) {
        $result = [ordered]@{}
        foreach ($key in @($Value.Keys | Sort-Object)) {
            $result[[string]$key] = ConvertTo-RfComsolCanonicalValue -Value $Value[$key]
        }
        return $result
    }
    if ($Value -is [pscustomobject]) {
        $result = [ordered]@{}
        foreach ($property in @($Value.PSObject.Properties | Sort-Object Name)) {
            $result[$property.Name] = ConvertTo-RfComsolCanonicalValue -Value $property.Value
        }
        return $result
    }
    if ($Value -is [Collections.IEnumerable] -and $Value -isnot [string]) {
        return @($Value | ForEach-Object {
            ConvertTo-RfComsolCanonicalValue -Value $_
        })
    }
    if ($Value -is [double] -or $Value -is [single] -or $Value -is [decimal]) {
        $number = [double]$Value
        if ([double]::IsNaN($number) -or [double]::IsInfinity($number)) {
            throw 'COMSOL solver-numerics contract must contain only finite numbers.'
        }
    }
    return $Value
}

function Get-RfComsolLogicalSha256 {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)]$Contract)
    $payload = [ordered]@{}
    foreach ($property in @($Contract.PSObject.Properties)) {
        if ($property.Name -cne 'logical_sha256') {
            $payload[$property.Name] = $property.Value
        }
    }
    $canonical = ConvertTo-RfComsolCanonicalValue -Value $payload
    $json = $canonical | ConvertTo-Json -Depth 32 -Compress
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($json)
    $hash = [Security.Cryptography.SHA256]::Create()
    try {
        return [Convert]::ToHexString($hash.ComputeHash($bytes))
    } finally {
        $hash.Dispose()
    }
}

function Read-RfComsolSolverNumericsContract {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$ContractPath)
    $fullPath = [IO.Path]::GetFullPath($ContractPath)
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        throw "COMSOL solver-numerics contract is missing: $fullPath"
    }
    try {
        $contract = Get-Content -LiteralPath $fullPath -Raw -Encoding UTF8 |
            ConvertFrom-Json
    } catch {
        throw "COMSOL solver-numerics contract is not valid JSON: $fullPath"
    }
    foreach ($name in $script:RfComsolNumericsIdentity.Keys) {
        $actual = Get-RfComsolRequiredProperty -Object $contract -Property $name `
            -Name "COMSOL solver-numerics $name"
        $expected = $script:RfComsolNumericsIdentity[$name]
        if ($expected -is [bool]) {
            if ($actual -isnot [bool] -or [bool]$actual -ne [bool]$expected) {
                throw "COMSOL solver-numerics $name is invalid."
            }
        } elseif ([string]$actual -cne [string]$expected) {
            throw "COMSOL solver-numerics $name is invalid."
        }
    }
    $embeddedHash = [string](Get-RfComsolRequiredProperty -Object $contract `
        -Property 'logical_sha256' -Name 'COMSOL solver-numerics logical_sha256')
    if ($embeddedHash -cnotmatch '\A[0-9A-F]{64}\z') {
        throw 'COMSOL solver-numerics logical_sha256 must be 64 uppercase hexadecimal characters.'
    }
    $logicalHash = Get-RfComsolLogicalSha256 -Contract $contract
    if ($embeddedHash -cne $logicalHash) {
        throw 'COMSOL solver-numerics logical_sha256 differs from the recomputed logical contract hash.'
    }
    return [pscustomobject]@{path=$fullPath;document=$contract;logical_sha256=$logicalHash}
}

function Compile-RfComsolSolverNumerics {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$OfficialContractPath,
        [Parameter(Mandatory = $true)][string]$RequestedContractPath,
        [Parameter(Mandatory = $true)][string]$ProfileId,
        [string]$ExperimentAuthorizationId = ''
    )
    $official = Read-RfComsolSolverNumericsContract -ContractPath $OfficialContractPath
    $requested = Read-RfComsolSolverNumericsContract -ContractPath $RequestedContractPath
    if ($requested.logical_sha256 -cne $official.logical_sha256) {
        throw 'Requested COMSOL solver-numerics contract differs from repository authority.'
    }
    $contract = $official.document
    $selectionRules = @{
        baseline = @('production','')
        time_refined_160 = @(
            'registered_experiment','same_solver_numerical_convergence'
        )
    }
    if (-not $selectionRules.ContainsKey($ProfileId)) {
        throw "COMSOL solver-numerics profile is not registered: $ProfileId"
    }
    $rule = $selectionRules[$ProfileId]
    if ($ExperimentAuthorizationId -cne $rule[1]) {
        throw "COMSOL solver-numerics profile '$ProfileId' requires authorization '$($rule[1])'."
    }
    $null = Get-RfComsolRequiredProperty -Object $contract -Property 'profiles' `
        -Name 'COMSOL solver-numerics profiles'
    $profiles = @($contract.profiles)
    $selected = @($profiles | Where-Object { [string]$_.profile_id -ceq $ProfileId })
    if ($selected.Count -ne 1) {
        throw "COMSOL solver-numerics profile selection is not unique: $ProfileId"
    }
    $profile = $selected[0]
    $usage = [string](Get-RfComsolRequiredProperty -Object $profile -Property 'usage' `
        -Name "COMSOL solver-numerics profile '$ProfileId' usage")
    if ($usage -cne $rule[0]) {
        throw "COMSOL solver-numerics profile '$ProfileId' usage is invalid."
    }
    $mesh = Get-RfComsolRequiredProperty -Object $profile -Property 'mesh' `
        -Name "COMSOL solver-numerics profile '$ProfileId' mesh"
    $meshAutoLevel = Get-RfComsolRequiredFiniteNumber -Object $mesh `
        -Property 'global_auto_level' -Name 'COMSOL mesh global_auto_level' `
        -Positive -Integer
    if ($meshAutoLevel -gt 9) {
        throw 'COMSOL mesh global_auto_level must be in [1, 9].'
    }
    $hmaxEnabled = Get-RfComsolRequiredProperty -Object $mesh `
        -Property 'working_region_hmax_override_enabled' `
        -Name 'COMSOL mesh working_region_hmax_override_enabled'
    if ($hmaxEnabled -isnot [bool]) {
        throw 'COMSOL mesh working_region_hmax_override_enabled must be boolean.'
    }
    $compiledMesh=[ordered]@{global_auto_level=[int]$meshAutoLevel
        working_region_hmax_override_enabled=[bool]$hmaxEnabled}
    if ([bool]$hmaxEnabled) {
        $compiledMesh.working_region_hmax_mm = Get-RfComsolRequiredFiniteNumber -Object $mesh `
            -Property 'working_region_hmax_mm' `
            -Name 'COMSOL mesh working_region_hmax_mm' -Positive
    } elseif ($null -ne $mesh.PSObject.Properties['working_region_hmax_mm']) {
        throw 'COMSOL mesh working_region_hmax_mm must be absent when its override is disabled.'
    }
    $trajectory = Get-RfComsolRequiredProperty -Object $profile -Property 'trajectory' `
        -Name "COMSOL solver-numerics profile '$ProfileId' trajectory"
    $rfSteps = Get-RfComsolRequiredFiniteNumber -Object $trajectory `
        -Property 'rf_steps_per_period' -Name 'COMSOL trajectory rf_steps_per_period' `
        -Positive -Integer
    if ($rfSteps -lt 4 -or $rfSteps -gt 10000) {
        throw 'COMSOL trajectory rf_steps_per_period must be in [4, 10000].'
    }
    $maximumTimeUs = Get-RfComsolRequiredFiniteNumber -Object $trajectory `
        -Property 'maximum_time_us' -Name 'COMSOL trajectory maximum_time_us' -Positive
    $compiled = [ordered]@{
        schema_version=1;role='rf_quadrupole_compiled_comsol_solver_numerics'
        authority = [ordered]@{
            contract_id=[string]$contract.contract_id
            logical_sha256=[string]$official.logical_sha256
        }
        selection = [ordered]@{
            profile_id=[string]$ProfileId;usage=$usage
            numerical_experiment_id=[string]$ExperimentAuthorizationId
        }
        mesh=$compiledMesh
        trajectory = [ordered]@{
            rf_steps_per_period=[int]$rfSteps;maximum_time_us=[double]$maximumTimeUs
        }
    }
    return [pscustomobject]@{official_contract_path=$official.path
        requested_contract_path=$requested.path;compiled=$compiled}
}
