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


def standalone_rf_samples(design: dict, mapping: dict, domain: dict) -> list[dict]:
    """Find represented nodes in the actual local RF solids, not a pitch proxy.

    Axial solids are separable. Cross sections search the shorter lattice axis;
    each other-axis interval is obtained from the real quadratic boundary.
    """
    from msplatform.components.rf_multipole.electrode_topology import build_electrode_topology
    from msplatform.components.rf_multipole.round_rod_geometry import points_inside_rods
    import numpy as np

    origin, pitch, dims = (domain[k] for k in ('instance_origin_mm', 'cell_mm_xyz', 'dimensions'))
    def interval(lo, hi, axis):
        return max(0, math.floor((lo-origin[axis])/pitch[axis])+1), min(dims['n'+axis]-1, math.ceil((hi-origin[axis])/pitch[axis])-1)
    def nearest(lo, hi, axis, point):
        if lo > hi:
            raise ValueError('physical body has no represented interior metal node')
        return min(hi, max(lo, int(math.floor((point-origin[axis])/pitch[axis]+.5))))
    samples, solids = [], []
    for group in build_electrode_topology(design):
        for pointer in group['member_refs']:
            body = design
            for token in pointer.split('/')[1:]:
                body = body[int(token)] if isinstance(body, list) else body[token]
            annulus = group['electrode_group_id'] == 'grounded_shell'
            cx, cy = (0., 0.) if annulus else (body['center_x_mm'], body['center_y_mm'])
            if annulus:
                a = b = body['outer_radius_mm']; theta = 0.
            elif 'radius_mm' in body:
                a = b = body['radius_mm']; theta = 0.
            else:
                a, b, theta = (body[k] for k in ('semi_major_axis_mm', 'semi_minor_axis_mm', 'major_axis_angle_rad'))
            c, t = math.cos(theta), math.sin(theta)
            A, B, C = c*c/(a*a)+t*t/(b*b), c*t*(1/(a*a)-1/(b*b)), t*t/(a*a)+c*c/(b*b)
            zlo, zhi = interval(body['z_min_mm'], body['z_max_mm'], 'z')
            iz = nearest(zlo, zhi, 'z', (body['z_min_mm']+body['z_max_mm'])/2)
            extents = [math.sqrt(a*a*c*c+b*b*t*t), math.sqrt(a*a*t*t+b*b*c*c)]
            ranges = [interval(center-extent, center+extent, axis) for center,extent,axis in zip((cx,cy),extents,'xy')]
            primary = min(range(2), key=lambda k: ranges[k][1]-ranges[k][0])
            secondary = 1-primary
            found = None
            for i in range(ranges[primary][0], ranges[primary][1]+1):
                u = origin['xy'[primary]]+i*pitch['xy'[primary]]-(cx,cy)[primary]
                aa, cc = (C,A) if primary == 0 else (A,C)
                disc = B*B*u*u-aa*(cc*u*u-1)
                if disc <= 0:
                    continue
                lo, hi = (-B*u-math.sqrt(disc))/aa, (-B*u+math.sqrt(disc))/aa
                jlo,jhi = interval(lo+(cx,cy)[secondary],hi+(cx,cy)[secondary],'xy'[secondary])
                candidates = [jlo,jhi]
                if jlo<=jhi:
                    candidates.append(nearest(jlo,jhi,'xy'[secondary],(lo+hi)/2+(cx,cy)[secondary]))
                for j in candidates:
                    if not jlo<=j<=jhi:
                        continue
                    v=origin['xy'[secondary]]+j*pitch['xy'[secondary]]-(cx,cy)[secondary]
                    if annulus and not body['inner_radius_mm']**2 < u*u+v*v < body['outer_radius_mm']**2:
                        continue
                    xy = [u+cx,v+cy] if primary == 0 else [v+cx,u+cy]
                    if not annulus and not points_inside_rods(np.array([xy]), {'rods':[body]}, include_boundary=False)[0]:
                        continue
                    found = [i,j,iz] if primary==0 else [j,i,iz]
                    break
                if found is not None:
                    break
            if found is None:
                raise ValueError('physical body has no represented interior metal node: '+pointer)
            samples.append(dict(label=pointer, electrode_id=mapping[group['electrode_group_id']], gu=found, metal=True))
            solids.append((body,annulus,A,B,C,cx,cy))
    vacuum,_=sample_node([0.,0.,(domain['bounds_mm']['z_min']+domain['bounds_mm']['z_max'])/2],
        [[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]],[0.,0.,0.],origin,pitch,dims)
    point=[origin[axis]+vacuum[k]*pitch[axis] for k,axis in enumerate('xyz')]
    for body,annulus,A,B,C,cx,cy in solids:
        x,y=point[0]-cx,point[1]-cy
        cross_section_metal = (A*x*x+2*B*x*y+C*y*y<=1 and x*x+y*y>=body['inner_radius_mm']**2
                               if annulus else bool(points_inside_rods(np.array([point[:2]]), {'rods':[body]})[0]))
        if body['z_min_mm']<=point[2]<=body['z_max_mm'] and cross_section_metal:
            raise ValueError('beam-axis vacuum witness is not represented outside actual metal')
    samples.append(dict(label='beam_axis_vacuum',gu=vacuum,metal=False))
    return samples
