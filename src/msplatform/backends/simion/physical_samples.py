"""Physical electrode/raw-mask audit samples; not particle release sampling."""
from __future__ import annotations
import math

def sample_node(point: list, rotation: list, translation: list, origin: dict, pitch: dict,
                dimensions: dict) -> tuple[list[int], list[float]]:
    """Snap a sample only, then invert its single physical pose for body checks."""
    world = [sum(rotation[a][k]*point[k] for k in range(3))+translation[a] for a in range(3)]
    if not all(math.isfinite(value) for value in world):
        raise ValueError("nonfinite physical sample position")
    gu = [int(math.floor((world[a]-origin[axis])/pitch[axis]+.5)) for a,axis in enumerate('xyz')]
    if any(not 0 <= gu[a] < dimensions['n'+axis] for a,axis in enumerate('xyz')):
        raise ValueError("physical sample is outside declared PA bounds")
    snapped = [origin[axis]+gu[a]*pitch[axis] for a,axis in enumerate('xyz')]
    body = [sum(rotation[a][k]*(snapped[a]-translation[a]) for a in range(3)) for k in range(3)]
    return gu, body


def cylinder_sample(rod: dict, rotation: list, translation: list, origin: dict,
                    pitch: dict, dimensions: dict) -> list[int]:
    """Require the snapped point strictly inside this actual rod segment."""
    point = [rod['center_x_mm'], rod['center_y_mm'], (rod['z_min_mm']+rod['z_max_mm'])/2]
    gu, body = sample_node(point, rotation, translation, origin, pitch, dimensions)
    if (not rod['z_min_mm'] < body[2] < rod['z_max_mm'] or
            (body[0]-point[0])**2+(body[1]-point[1])**2 >= rod['radius_mm']**2):
        raise ValueError("rod sample not strictly inside its actual segment metal")
    return gu


def box_sample(box: dict, hole: dict | None, rotation: list, translation: list,
               origin: dict, pitch: dict, dimensions: dict, *,
               local_bounds_mm: dict | None = None) -> list[int] | None:
    """Sample original metal intersected with optional bounds in its local frame.

    Geometrically absent metal returns None. Intersecting metal without a legal
    grid node still fails the original metal/sheet checks; no body is moved.
    """
    bounds = {axis: (box[f'{axis}_min_mm'], box[f'{axis}_max_mm']) for axis in 'xyz'}
    if local_bounds_mm is not None:
        bounds = {axis: (max(lo, local_bounds_mm[axis+'_min']), min(hi, local_bounds_mm[axis+'_max']))
                  for axis, (lo, hi) in bounds.items()}
        if any(lo > hi or (lo == hi and box[axis+'_min_mm'] != box[axis+'_max_mm'])
               for axis, (lo, hi) in bounds.items()):
            return None
    point = [(lo+hi)/2 for lo, hi in bounds.values()]
    if hole:
        # Prefer the established positive-X face, then the other actual metal
        # slabs. A narrow numerical patch may contain only the opposite face.
        for axis, side in ((a, s) for a in 'xyz' for s in ('max', 'min')):
            lo, hi = bounds[axis]
            if side == 'max': lo = max(lo, hole[axis+'_max_mm'])
            else: hi = min(hi, hole[axis+'_min_mm'])
            if lo < hi:
                point['xyz'.index(axis)] = (lo+hi)/2
                break
        else:
            return None
    gu, body = sample_node(point, rotation, translation, origin, pitch, dimensions)
    for k, axis in enumerate('xyz'):
        lo, hi = box[f'{axis}_min_mm'], box[f'{axis}_max_mm']
        if lo == hi:
            if not math.isclose(body[k], lo, rel_tol=0, abs_tol=32*math.ulp(max(1., abs(lo)))):
                raise ValueError("ideal-sheet anchor not represented at declared PA node plane")
        elif not lo < body[k] < hi:
            raise ValueError("endpoint/ring anchor not strictly inside actual metal extent")
    if hole and all(hole[f'{axis}_min_mm'] <= body[k] <= hole[f'{axis}_max_mm'] for k,axis in enumerate('xyz')):
        raise ValueError("metal sample landed in aperture")
    if local_bounds_mm is not None:
        for index, (lo, hi) in enumerate(bounds.values()):
            tolerance = 32*math.ulp(max(1.,abs(lo),abs(hi)))
            if body[index] < lo-tolerance or body[index] > hi+tolerance:
                raise ValueError("metal sample has no represented node in local numerical bounds")
    return gu
