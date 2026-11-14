"""Provider-derived scientific electrode drives, independent of any backend."""

from collections.abc import Iterable

from msplatform.contracts.electrode_sources import physical_voltage_value


def _rf_common_dc(resolved: dict, source: dict) -> tuple[float, float]:
    return (physical_voltage_value(resolved, source['common_mode_pointer']),
            physical_voltage_value(resolved, source['dc_amplitude_pointer']))


def scientific_multipole_drive(resolved: dict) -> dict[str, dict]:
    """Project the provider's real physical RF/DC sources, without flight numerics."""
    from msplatform.components.rf_multipole.electrode_topology import build_electrode_topology

    result = {}
    for row in build_electrode_topology(resolved):
        source = row['voltage_source']
        if source['kind'] == 'static':
            value = dict(kind='static', voltage_v=physical_voltage_value(resolved, source['pointer']))
        else:
            drive = resolved['drive']
            polarity = 1 if source['rf_group'] == 1 else -1
            common, dc = _rf_common_dc(resolved, source)
            value = dict(kind='rf', common_mode_v=common,
                dc_v=polarity * dc, polarity=polarity,
                waveform=drive['waveform'], frequency_hz=drive['frequency_Hz'], phase_rad=drive['phase_rad'],
                rf_amplitude_v=drive['rf_amplitude_V_zero_to_peak_per_group'])
        result[row['electrode_group_id']] = value
    return result


def multipole_voltage_rows(
    resolved: dict, rows: Iterable[tuple[int, dict]],
) -> tuple[dict[int, float], dict[int, int]]:
    """Apply the one existing common/DC/polarity calculation in its original order."""
    carrier, groups = {}, {}
    for solver, source in rows:
        if source['kind'] == 'static':
            carrier[solver] = physical_voltage_value(resolved, source['pointer'])
        elif source['kind'] == 'rf_drive':
            common, dc = _rf_common_dc(resolved, source)
            group = source['rf_group']
            carrier[solver] = common + (dc if group == 1 else -dc)
            groups[solver] = group
        else:
            raise ValueError('physical electrode voltage source kind is unsupported')
    return carrier, groups
