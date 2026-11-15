"""Validate producer-owned fractional-surface state against its native grid."""
from collections.abc import Mapping
import math


def validate_native_surface_state(state: Mapping, *, grid: Mapping, surface_present: bool) -> str:
    """Return the proven mode; callers still verify file records and native reads."""
    fields={'schema_version','mode','grid','pitch','scanned_nodes','offset_nodes'}
    if not isinstance(state,Mapping) or set(state)!=fields or type(state['schema_version']) is not int or state['schema_version']!=1:
        raise ValueError('invalid native fractional surface state')
    if not isinstance(grid,Mapping) or set(grid)!={'nx','ny','nz','dx_mm','dy_mm','dz_mm'} or type(surface_present) is not bool:
        raise ValueError('explicit native surface grid and presence required')
    dims=[grid['n'+a] for a in 'xyz'];pitch=[grid['d'+a+'_mm'] for a in 'xyz']
    if (any(type(value) is not int or value<=0 for value in dims)
            or any(type(value) not in (int,float) or not math.isfinite(value) or value<=0 for value in pitch)
            or not isinstance(state['grid'],list) or any(type(value) is not int for value in state['grid'])
            or not isinstance(state['pitch'],list) or any(type(value) not in (int,float) for value in state['pitch'])
            or state['grid']!=dims or state['pitch']!=pitch):
        raise ValueError('native fractional surface state/grid differs')
    if state['mode']=='empty':
        if (surface_present or type(state['scanned_nodes']) is not int
                or state['scanned_nodes']!=math.prod(dims)
                or type(state['offset_nodes']) is not int or state['offset_nodes']!=0):
            raise ValueError('empty fractional surface proof differs')
    elif state['mode']=='present':
        if not surface_present or state['scanned_nodes'] is not None or state['offset_nodes'] is not None:
            raise ValueError('present fractional surface proof differs')
    else:
        raise ValueError('unsupported fractional surface state')
    return state['mode']
