"""Resolve explicitly authored IP schedule authorities by component."""
from collections.abc import Mapping


def resolve_ip_schedule_authorities(drive, scheduled):
    """Resolve the declared schedule form against actual scheduled instances."""
    single = 'ip_schedule' in drive
    multiple = 'ip_schedules' in drive
    if single and multiple:
        raise ValueError('choose one IP schedule authority form')
    if single:
        if len(scheduled) != 1:
            raise ValueError('one explicit canonical IP schedule authority required')
        authorities = {next(iter(scheduled)): drive['ip_schedule']}
    elif multiple:
        if not isinstance(drive['ip_schedules'], Mapping) or set(drive['ip_schedules']) != scheduled or not scheduled:
            raise ValueError('IP schedule authorities differ from scheduled instances')
        authorities = drive['ip_schedules']
    elif scheduled:
        raise ValueError('explicit canonical IP schedule authority required')
    else:
        authorities = {}
    return authorities
