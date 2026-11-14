"""Query selected canonical SFI geometry; never infer a conductor voltage."""
from __future__ import annotations
import math
from collections.abc import Mapping, Sequence
from msplatform.contracts.rigid_transform import FramedPosition, RigidTransform


def oa_witness_extent(shape: Mapping) -> list[tuple[float, float]]:
    """Return the existing OA bounds, including degenerate axes."""
    kind = shape['kind']
    if kind == 'difference':
        return oa_witness_extent(shape['base'])
    if kind == 'union':
        extents = [oa_witness_extent(part) for part in shape['parts']]
        return [(min(e[a][0] for e in extents), max(e[a][1] for e in extents)) for a in range(3)]
    center = shape['center_mm']
    size = shape['size_mm'] if kind == 'box' else [2*shape['radius_mm'], 2*shape['radius_mm'], shape['height_mm']]
    return [(c-s/2, c+s/2) for c, s in zip(center, size, strict=True)]


def _radial_square(point: Sequence[float], x: float, y: float) -> float:
    return (point[0]-x)**2 + (point[1]-y)**2


def oa_witness_contains(shape: Mapping, point: Sequence[float], *, boundary: bool = False) -> bool:
    """Preserve OA's existing closed-tool and zero-extent comparisons exactly."""
    kind = shape['kind']
    if kind == 'difference':
        return oa_witness_contains(shape['base'], point, boundary=boundary) and not any(
            oa_witness_contains(tool, point, boundary=True) for tool in shape['tools'])
    if kind == 'union':
        return any(oa_witness_contains(part, point, boundary=boundary) for part in shape['parts'])
    bounds = oa_witness_extent(shape)
    if not all((math.isclose(p, lo, rel_tol=0., abs_tol=32*math.ulp(max(1., abs(lo)))) if lo == hi
                else lo <= p <= hi if boundary else lo < p < hi)
               for p, (lo, hi) in zip(point, bounds, strict=True)):
        return False
    if kind == 'box':
        return True
    x, y, _ = shape['center_mm']
    radius2 = _radial_square(point, x, y)
    return radius2 <= shape['radius_mm']**2 if boundary else radius2 < shape['radius_mm']**2


def shape_relation(shape: Mapping, point: Sequence[float]) -> str:
    """Classify one point as interior, boundary, outside, or unsupported.

    Boundary includes ideal sheets and Boolean cut faces. This low-level query
    compares supplied local numeric values exactly; query_members adds a
    conservative floating-operation bound after inverse pose transformation.
    """
    if len(point) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in point):
        raise ValueError('point must contain three finite coordinates')
    kind = shape.get('kind')
    if kind in {'union', 'difference'}:
        if kind == 'union':
            parts = shape.get('parts')
            if not isinstance(parts, (list, tuple)) or not parts:
                raise ValueError('union requires parts')
            relations = [shape_relation(part, point) for part in parts]
            if 'unsupported' in relations: return 'unsupported'
            if 'interior' in relations: return 'interior'
            return 'boundary' if 'boundary' in relations else 'outside'
        base = shape_relation(shape['base'], point)
        tools = shape.get('tools')
        if not isinstance(tools, (list, tuple)) or not tools:
            raise ValueError('difference requires tools')
        relations = [shape_relation(part, point) for part in tools]
        if base == 'unsupported' or 'unsupported' in relations: return 'unsupported'
        if base == 'outside' or 'interior' in relations: return 'outside'
        if base == 'boundary' or 'boundary' in relations: return 'boundary'
        return 'interior'
    if kind in {'box', 'cylinder'}:
        center = shape['center_mm']
        sizes = shape['size_mm'] if kind == 'box' else (shape['radius_mm'], shape['height_mm'])
        if (len(center) != 3 or (kind == 'box' and len(sizes) != 3)
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in (*center, *sizes))
                or any(v < 0 for v in sizes) or (kind == 'cylinder' and shape['radius_mm'] == 0)):
            raise ValueError('invalid canonical box or cylinder')
        # Reuse the same bounds and radial tests as the existing OA consumer.
        closed = oa_witness_contains(shape, point, boundary=True)
        if not closed: return 'outside'
        if any(lo == hi for lo, hi in oa_witness_extent(shape)): return 'boundary'
        return 'interior' if oa_witness_contains(shape, point) else 'boundary'
    if kind in {'rod', 'annulus'}:
        if kind == 'rod' and 'radius_mm' not in shape: return 'unsupported'
        x, y = shape['center_xy_mm']; zlo, zhi = shape['z_min_mm'], shape['z_max_mm']
        outer = shape['radius_mm'] if kind == 'rod' else shape['outer_radius_mm']
        inner = 0 if kind == 'rod' else shape['inner_radius_mm']
        if (not all(type(v) in (int, float) and math.isfinite(v) for v in (x,y,zlo,zhi,inner,outer))
                or zlo > zhi or not 0 <= inner < outer):
            raise ValueError('invalid canonical circular member')
        radius2 = _radial_square(point, x, y)
        if point[2] < zlo or point[2] > zhi or radius2 > outer**2 or radius2 < inner**2: return 'outside'
        if point[2] in (zlo,zhi) or radius2 == outer**2 or (inner > 0 and radius2 == inner**2): return 'boundary'
        return 'interior'
    return 'unsupported'


def _roundoff_near_surface(shape: Mapping, point: Sequence[float], error: Sequence[float]) -> bool:
    """Conservatively retain points close to arithmetic surfaces as ambiguous.

    The caller supplies per-axis inverse-transform roundoff bounds. Additional
    ULP terms cover the bounded primitive offset, extent and radial operations;
    they express floating-point uncertainty, not an adjustable physical margin.
    """
    kind = shape['kind']
    if kind == 'difference':
        return _roundoff_near_surface(shape['base'], point, error) or any(
            _roundoff_near_surface(tool, point, error) for tool in shape['tools'])
    if kind == 'union':
        return any(_roundoff_near_surface(part, point, error) for part in shape['parts'])
    if kind == 'box':
        bounds = oa_witness_extent(shape)
        margin = [error[i] + 8*math.ulp(max(1., abs(point[i]), abs(lo), abs(hi)))
                  for i, (lo, hi) in enumerate(bounds)]
        if any(point[i] < lo-margin[i] or point[i] > hi+margin[i]
               for i, (lo, hi) in enumerate(bounds)):
            return False
        return any(abs(point[i]-lo) <= margin[i] or abs(point[i]-hi) <= margin[i]
                   for i, (lo, hi) in enumerate(bounds))
    if kind == 'cylinder':
        x, y, z = shape['center_mm']; radius = shape['radius_mm']
        lo, hi = z-shape['height_mm']/2, z+shape['height_mm']/2
        inner = 0
    else:
        x, y = shape['center_xy_mm']; lo, hi = shape['z_min_mm'], shape['z_max_mm']
        radius = shape['radius_mm'] if kind == 'rod' else shape['outer_radius_mm']
        inner = 0 if kind == 'rod' else shape['inner_radius_mm']
    radial = math.hypot(point[0]-x, point[1]-y)
    radial_error = error[0]+error[1]+16*math.ulp(max(1.,abs(x),abs(y),abs(point[0]),abs(point[1]),radius))
    axial_error = error[2]+8*math.ulp(max(1.,abs(point[2]),abs(lo),abs(hi)))
    if point[2] < lo-axial_error or point[2] > hi+axial_error or radial > radius+radial_error:
        return False
    if inner > 0 and radial < inner-radial_error:
        return False
    return (abs(radial-radius) <= radial_error or (inner > 0 and abs(radial-inner) <= radial_error)
            or abs(point[2]-lo) <= axial_error or abs(point[2]-hi) <= axial_error)


def query_members(members: Sequence[Mapping], point: Sequence[float], *, frame_id: str) -> dict:
    """Classify canonical members in their supplied assembly frame and pose.

    An unsupported shape is not treated as empty. Distinct simultaneously
    interior electrode groups are a conflict; boundary contacts stay ambiguous.
    """
    if not isinstance(frame_id, str) or not frame_id:
        raise ValueError('explicit assembly frame is required')
    position = FramedPosition(frame_id, tuple(point))
    inside, boundary, unsupported = set(), set(), []
    for member in members:
        transform = RigidTransform.from_contract(member['transform'])
        local = transform.inverse().transform_position(position)
        relation = shape_relation(member['shape'], local.coordinates_mm)
        if relation != 'unsupported':
            # Bound the inverse rotation/translation arithmetic conservatively.
            # Each output coordinate has two three-term dot products; 64 ULPs
            # also cover their additions/subtractions and stored-pose rounding.
            error = [64*math.ulp(max(1., abs(local.coordinates_mm[i]),
                sum(abs(transform.rotation[j][i]*position.coordinates_mm[j]) +
                    abs(transform.rotation[j][i]*transform.translation_mm[j]) for j in range(3))))
                for i in range(3)]
            # RigidTransform accepts near-orthogonal R and uses transpose as
            # inverse. Bound its systematic error from E = R.T*R - I:
            # ||(I+E)^-1 u-u||_inf <= ||E||_inf*||u||_inf/(1-||E||_inf).
            rotation = transform.rotation
            defect = max(sum(abs(math.fsum(rotation[k][i]*rotation[k][j] for k in range(3))
                                 - (1. if i == j else 0.)) for j in range(3)) for i in range(3))
            defect_bound = defect + 64*math.ulp(1.)
            if not math.isfinite(defect_bound) or defect_bound >= 1.:
                raise ValueError('pose inverse uncertainty cannot be bounded')
            magnitude = max(abs(value) + error[i] for i, value in enumerate(local.coordinates_mm))
            pose_error = defect_bound*magnitude/(1.-defect_bound)
            error = [bound + pose_error + 8*math.ulp(max(1., pose_error)) for bound in error]
            if _roundoff_near_surface(member['shape'], local.coordinates_mm, error):
                relation = 'boundary'
        key = (member['instance_id'], member['electrode_group_id'])
        if relation == 'interior': inside.add(key)
        elif relation == 'boundary': boundary.add(key)
        elif relation == 'unsupported': unsupported.append(member['member_id'])
    if len(inside) > 1: raise ValueError('point lies inside different electrode groups')
    if unsupported: return {'status':'unsupported','members':sorted(unsupported)}
    if boundary: return {'status':'boundary','groups':sorted(inside | boundary)}
    if inside: return {'status':'interior','group':next(iter(inside))}
    return {'status':'outside'}
