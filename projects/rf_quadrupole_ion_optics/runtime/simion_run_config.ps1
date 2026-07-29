Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-VerifiedRfSimionWaveform {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]$ResolvedDesign
    )

    if ($null -eq $ResolvedDesign.drive) {
        throw 'Resolved design drive is missing.'
    }
    $waveformProperty = $ResolvedDesign.drive.PSObject.Properties['waveform']
    if ($null -eq $waveformProperty) {
        throw 'Resolved design drive.waveform is missing.'
    }
    $waveform = [string]$waveformProperty.Value
    if (@('sine','cosine') -cnotcontains $waveform) {
        throw "Resolved design drive.waveform must be exactly sine or cosine; received '$waveform'."
    }
    return $waveform
}

function Get-VerifiedRfSimionResolvedSha256 {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]$ResolvedDesign
    )

    $hashProperty = $ResolvedDesign.PSObject.Properties['resolved_sha256']
    if ($null -eq $hashProperty) {
        throw 'Resolved design resolved_sha256 is missing.'
    }
    $resolvedSha256 = [string]$hashProperty.Value
    if ($resolvedSha256 -cnotmatch '\A[0-9A-Fa-f]{64}\z') {
        throw 'Resolved design resolved_sha256 must contain exactly 64 hexadecimal characters.'
    }
    return $resolvedSha256
}

function Assert-RfSimionLuaConfigContract {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$LuaConfig,
        [Parameter(Mandatory = $true)][string]$SharedProgramPath
    )

    if (-not (Test-Path -LiteralPath $SharedProgramPath -PathType Leaf)) {
        throw "Shared SIMION program is missing: $SharedProgramPath"
    }
    $program = Get-Content -LiteralPath $SharedProgramPath -Raw -Encoding UTF8
    $required = @(
        [regex]::Matches(
            $program,
            'assert\s*\(\s*run_config\.([A-Za-z_][A-Za-z0-9_]*)'
        ) | ForEach-Object { $_.Groups[1].Value }
        'mode'
        'operating_point'
        'particle_state_csv'
        'trajectory_csv'
        'summary_json'
        'parent_resolved_design_sha256'
    ) | Sort-Object -Unique
    if ($required.Count -eq 0) {
        throw 'Shared SIMION program exposes no required run-config fields.'
    }
    $provided = @(
        [regex]::Matches(
            $LuaConfig,
            '(?m)(?:^|,)\s*([A-Za-z_][A-Za-z0-9_]*)\s*='
        ) | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
    )
    $missing = @($required | Where-Object { $_ -cnotin $provided })
    if ($missing.Count -gt 0) {
        throw "Generated SIMION run config lacks required fields: $($missing -join ', ')."
    }
}

function Assert-RfSimionEqualLength {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][double]$Actual,
        [Parameter(Mandatory = $true)][double]$Expected
    )
    if ([Math]::Abs($Actual - $Expected) -gt 1e-9) {
        throw "$Name mapping differs: actual=$Actual expected=$Expected."
    }
}

function Get-RfSimionRequiredProperty {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Property,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $member = $Object.PSObject.Properties[$Property]
    if ($null -eq $member -or $null -eq $member.Value) {
        throw "$Name is missing."
    }
    return $member.Value
}

function Get-RfSimionRequiredFiniteNumber {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Property,
        [Parameter(Mandatory = $true)][string]$Name,
        [switch]$Positive,
        [switch]$NonNegative
    )
    $raw = Get-RfSimionRequiredProperty -Object $Object -Property $Property -Name $Name
    try {
        $value = [double]$raw
    } catch {
        throw "$Name must be numeric."
    }
    if ([double]::IsNaN($value) -or [double]::IsInfinity($value)) {
        throw "$Name must be finite."
    }
    if ($Positive -and $value -le 0) {
        throw "$Name must be positive."
    }
    if ($NonNegative -and $value -lt 0) {
        throw "$Name must be non-negative."
    }
    return $value
}

function New-RfSimionCoreRunConfig {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]$ResolvedDesign,
        [Parameter(Mandatory = $true)]$InterfaceContract,
        [Parameter(Mandatory = $true)]$SolverNumerics,
        [Parameter(Mandatory = $true)][int]$RfStepsPerPeriod,
        [Parameter(Mandatory = $true)][int]$TrajectoryQuality,
        [Parameter(Mandatory = $true)][string]$ModeName,
        [Parameter(Mandatory = $true)][string]$OperatingPoint,
        [Parameter(Mandatory = $true)][string]$IobPath,
        [Parameter(Mandatory = $true)][string]$Fly2Path,
        [Parameter(Mandatory = $true)][string]$SourceStatesLua,
        [Parameter(Mandatory = $true)][string]$ParticleStateCsv,
        [Parameter(Mandatory = $true)][string]$TrajectoryCsv,
        [Parameter(Mandatory = $true)][string]$SummaryJson
    )

    if ($RfStepsPerPeriod -le 0) {
        throw 'SIMION rf_steps_per_period must be positive.'
    }
    if ($TrajectoryQuality -le 0) {
        throw 'SIMION trajectory_quality must be positive.'
    }
    $numericsContractIdentity = Get-RfSimionRequiredProperty -Object $SolverNumerics `
        -Property 'role' -Name 'solver numerics role'
    if ($numericsContractIdentity -cne 'rf_quadrupole_simion_solver_numerics') {
        throw 'Solver numerics role must be rf_quadrupole_simion_solver_numerics.'
    }
    $numericsStatus = Get-RfSimionRequiredProperty -Object $SolverNumerics `
        -Property 'status' -Name 'solver numerics status'
    if ($numericsStatus -cne 'current_candidate_solver_numerics') {
        throw 'Solver numerics status is not current_candidate_solver_numerics.'
    }
    $allowedRfSteps = @(
        Get-RfSimionRequiredProperty -Object $SolverNumerics `
            -Property 'allowed_rf_steps_per_period' `
            -Name 'solver numerics allowed_rf_steps_per_period'
    )
    if ($allowedRfSteps.Count -eq 0 -or
        $RfStepsPerPeriod -notin @($allowedRfSteps | ForEach-Object { [int]$_ })) {
        throw 'SIMION rf_steps_per_period is not allowed by the solver numerics contract.'
    }
    $contractTrajectoryQuality = Get-RfSimionRequiredFiniteNumber `
        -Object $SolverNumerics -Property 'trajectory_quality' `
        -Name 'solver numerics trajectory_quality' -Positive
    if ($TrajectoryQuality -ne [int]$contractTrajectoryQuality) {
        throw 'SIMION trajectory_quality differs from the solver numerics contract.'
    }
    $maximumTimeUs = Get-RfSimionRequiredFiniteNumber -Object $SolverNumerics `
        -Property 'maximum_time_us' -Name 'solver numerics maximum_time_us' -Positive
    $waveform = Get-VerifiedRfSimionWaveform -ResolvedDesign $ResolvedDesign
    $parentResolvedDesignSha256 =
        Get-VerifiedRfSimionResolvedSha256 -ResolvedDesign $ResolvedDesign
    $simionCellMm = Get-RfSimionRequiredFiniteNumber -Object $SolverNumerics `
        -Property 'simion_cell_mm' -Name 'solver numerics simion_cell_mm' -Positive
    $geometry = Get-RfSimionRequiredProperty -Object $ResolvedDesign `
        -Property 'geometry_mm' -Name 'resolved design geometry_mm'
    $enclosure = Get-RfSimionRequiredProperty -Object $geometry `
        -Property 'enclosure' -Name 'resolved design geometry_mm.enclosure'
    $interfaces = Get-RfSimionRequiredProperty -Object $ResolvedDesign `
        -Property 'interfaces_mm' -Name 'resolved design interfaces_mm'
    $entranceInterface = Get-RfSimionRequiredProperty -Object $interfaces `
        -Property 'entrance' -Name 'resolved design interfaces_mm.entrance'
    $exitInterface = Get-RfSimionRequiredProperty -Object $interfaces `
        -Property 'exit' -Name 'resolved design interfaces_mm.exit'
    $planes = Get-RfSimionRequiredProperty -Object $InterfaceContract `
        -Property 'planes' -Name 'interface contract planes'
    $releasePlane = Get-RfSimionRequiredProperty -Object $planes `
        -Property 'release' -Name 'interface contract release plane'
    $rodExitPlane = Get-RfSimionRequiredProperty -Object $planes `
        -Property 'rod_exit' -Name 'interface contract rod-exit plane'
    $handoffPlane = Get-RfSimionRequiredProperty -Object $planes `
        -Property 'handoff' -Name 'interface contract handoff plane'
    $censusPlane = Get-RfSimionRequiredProperty -Object $planes `
        -Property 'census' -Name 'interface contract census plane'
    $releasePlaneMm = Get-RfSimionRequiredFiniteNumber -Object $releasePlane `
        -Property 'z_mm' -Name 'interface release plane z_mm'
    $rodExitPlaneMm = Get-RfSimionRequiredFiniteNumber -Object $rodExitPlane `
        -Property 'z_mm' -Name 'interface rod-exit plane z_mm' -Positive
    $handoffPlaneMm = Get-RfSimionRequiredFiniteNumber -Object $handoffPlane `
        -Property 'z_mm' -Name 'interface handoff plane z_mm' -Positive
    $censusPlaneMm = Get-RfSimionRequiredFiniteNumber -Object $censusPlane `
        -Property 'z_mm' -Name 'interface census plane z_mm' -Positive
    $resolvedReleasePlaneMm = Get-RfSimionRequiredFiniteNumber -Object $entranceInterface `
        -Property 'release_plane_z_mm' -Name 'resolved release plane'
    $resolvedCensusPlaneMm = Get-RfSimionRequiredFiniteNumber -Object $exitInterface `
        -Property 'census_plane_z_mm' -Name 'resolved census plane' -Positive
    $rodZMinMm = Get-RfSimionRequiredFiniteNumber -Object $geometry `
        -Property 'rod_z_min' -Name 'resolved rod_z_min' -NonNegative
    $rodZMaxMm = Get-RfSimionRequiredFiniteNumber -Object $geometry `
        -Property 'rod_z_max' -Name 'resolved rod_z_max' -Positive
    $handoffAuthorityMm = Get-RfSimionRequiredFiniteNumber -Object $enclosure `
        -Property 'exit_front_wall_end_z_mm' -Name 'resolved exit-front handoff plane' -Positive
    Assert-RfSimionEqualLength 'release plane' $releasePlaneMm $resolvedReleasePlaneMm
    Assert-RfSimionEqualLength 'rod-exit plane' $rodExitPlaneMm $rodZMaxMm
    Assert-RfSimionEqualLength 'handoff plane' $handoffPlaneMm $handoffAuthorityMm
    Assert-RfSimionEqualLength 'census plane' `
        $censusPlaneMm $resolvedCensusPlaneMm

    $drive = Get-RfSimionRequiredProperty -Object $ResolvedDesign `
        -Property 'drive' -Name 'resolved design drive'
    $staticElectrodes = Get-RfSimionRequiredProperty -Object $ResolvedDesign `
        -Property 'static_electrodes_V' -Name 'resolved design static_electrodes_V'
    $solverNumerics = Get-RfSimionRequiredProperty -Object $InterfaceContract `
        -Property 'solver_numerics' -Name 'interface contract solver_numerics'
    $terminalBackoffCells = Get-RfSimionRequiredFiniteNumber -Object $solverNumerics `
        -Property 'simion_terminal_surface_backoff_cells' `
        -Name 'interface SIMION terminal-surface backoff cells' -NonNegative
    $numericalCensusMarkerThresholdMm =
        $resolvedCensusPlaneMm - $terminalBackoffCells * $simionCellMm
    $outerHalfWidthMm = Get-RfSimionRequiredFiniteNumber -Object $enclosure `
        -Property 'outer_half_width_mm' -Name 'resolved enclosure outer_half_width_mm' -Positive
    $vacuumZMinMm = Get-RfSimionRequiredFiniteNumber -Object $enclosure `
        -Property 'vacuum_z_min_mm' -Name 'resolved enclosure vacuum_z_min_mm' -NonNegative
    $vacuumZMaxMm = Get-RfSimionRequiredFiniteNumber -Object $enclosure `
        -Property 'vacuum_z_max_mm' -Name 'resolved enclosure vacuum_z_max_mm' -Positive
    if ($vacuumZMaxMm -le $vacuumZMinMm) {
        throw 'Resolved enclosure vacuum z span must be positive.'
    }
    return [ordered]@{
        mode = $ModeName
        operating_point = $OperatingPoint
        iob = [IO.Path]::GetFullPath($IobPath)
        fly2 = [IO.Path]::GetFullPath($Fly2Path)
        source_states = [IO.Path]::GetFullPath($SourceStatesLua)
        particle_state_csv = [IO.Path]::GetFullPath($ParticleStateCsv)
        trajectory_csv = [IO.Path]::GetFullPath($TrajectoryCsv)
        summary_json = [IO.Path]::GetFullPath($SummaryJson)
        trajectory_quality = $TrajectoryQuality
        rf_steps_per_period = $RfStepsPerPeriod
        rf_peak_v = Get-RfSimionRequiredFiniteNumber -Object $drive `
            -Property 'rf_amplitude_V_zero_to_peak_per_group' -Name 'resolved RF amplitude' -Positive
        rf_scale = 1
        axial_scale = 0
        dc_amplitude_v = Get-RfSimionRequiredFiniteNumber -Object $drive `
            -Property 'dc_amplitude_V_per_group' -Name 'resolved DC amplitude' -NonNegative
        frequency_hz = Get-RfSimionRequiredFiniteNumber -Object $drive `
            -Property 'frequency_Hz' -Name 'resolved RF frequency' -Positive
        phase_deg = (Get-RfSimionRequiredFiniteNumber -Object $drive `
            -Property 'phase_rad' -Name 'resolved RF phase') * 180 / [Math]::PI
        waveform = $waveform
        axis_voltage_v = Get-RfSimionRequiredFiniteNumber -Object $drive `
            -Property 'common_mode_offset_V' -Name 'resolved common-mode voltage'
        entrance_voltage_v = Get-RfSimionRequiredFiniteNumber -Object $staticElectrodes `
            -Property 'entrance_aperture_plate_and_connector_V' -Name 'resolved entrance voltage'
        exit_voltage_v = Get-RfSimionRequiredFiniteNumber -Object $staticElectrodes `
            -Property 'exit_outer_enclosure_and_connector_V' -Name 'resolved exit voltage'
        physical_detector_voltage_v = Get-RfSimionRequiredFiniteNumber -Object $staticElectrodes `
            -Property 'physical_detector_V' -Name 'resolved physical detector voltage'
        ground_electrode_id = 0
        output_electrode_id = 0
        ground_reference_v = 0
        output_reference_v = 0
        maximum_time_us = $maximumTimeUs
        trajectory_plane_step_mm = $simionCellMm
        rod_z_min_mm = $rodZMinMm
        rod_z_max_mm = $rodZMaxMm
        rod_exit_plane_mm = $rodExitPlaneMm
        handoff_plane_mm = $handoffPlaneMm
        census_plane_mm = $censusPlaneMm
        numerical_census_marker_threshold_mm = $numericalCensusMarkerThresholdMm
        census_radius_mm = Get-RfSimionRequiredFiniteNumber -Object $enclosure `
            -Property 'physical_detector_radius_mm' -Name 'resolved census radius' -Positive
        radial_escape_radius_mm = $outerHalfWidthMm
        expected_pa_nx = [int][Math]::Round($outerHalfWidthMm / $simionCellMm) + 1
        expected_pa_ny = [int][Math]::Round($outerHalfWidthMm / $simionCellMm) + 1
        expected_pa_nz = [int][Math]::Round(
            ($vacuumZMaxMm - $vacuumZMinMm) / $simionCellMm
        ) + 1
        expected_pa_cell_mm = $simionCellMm
        parent_resolved_design_sha256 = $parentResolvedDesignSha256
    }
}

function ConvertTo-RfSimionLuaLongString {
    param([Parameter(Mandatory = $true)][string]$Value)
    if ($Value.Contains(']]')) {
        throw 'SIMION Lua string values may not contain ]].'
    }
    return "[[$Value]]"
}

function ConvertTo-RfSimionLuaConfig {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]$CoreConfig,
        [Parameter(Mandatory = $true)][string]$SharedProgramPath
    )

    $lines = [System.Collections.Generic.List[string]]::new()
    $lines.Add('return {')
    foreach ($entry in $CoreConfig.GetEnumerator()) {
        $name = [string]$entry.Key
        $value = $entry.Value
        if ($name -eq 'source_states') {
            $encoded = ConvertTo-RfSimionLuaLongString ([string]$value)
            $lines.Add("  source_states=dofile($encoded),")
        } elseif ($value -is [string]) {
            $lines.Add("  $name=$(ConvertTo-RfSimionLuaLongString $value),")
        } elseif ($value -is [bool]) {
            $lines.Add("  $name=$($value.ToString().ToLowerInvariant()),")
        } else {
            $formatted = [Convert]::ToString(
                $value,
                [Globalization.CultureInfo]::InvariantCulture
            )
            $lines.Add("  $name=$formatted,")
        }
    }
    $lines.Add('}')
    $luaConfig = $lines -join [Environment]::NewLine
    Assert-RfSimionLuaConfigContract -LuaConfig $luaConfig `
        -SharedProgramPath $SharedProgramPath
    return $luaConfig
}
