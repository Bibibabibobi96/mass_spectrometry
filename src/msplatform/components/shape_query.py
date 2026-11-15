"""Query selected canonical SFI geometry; never infer a conductor voltage."""
from __future__ import annotations
import math
import copy
import json
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



def polygon_membership(point: tuple[float, float], polygon: list[list[float]]) -> tuple[bool, float]:
    y, z = point
    inside = False
    distance = math.inf
    for start, end in zip(polygon, polygon[1:] + polygon[:1]):
        y0, z0 = float(start[0]), float(start[1])
        y1, z1 = float(end[0]), float(end[1])
        dy, dz = y1 - y0, z1 - z0
        scale = dy * dy + dz * dz
        along = 0.0 if scale == 0.0 else max(0.0, min(1.0, ((y - y0) * dy + (z - z0) * dz) / scale))
        distance = min(distance, math.hypot(y - (y0 + along * dy), z - (z0 + along * dz)))
        if (z0 > z) != (z1 > z):
            crossing_y = y0 + (z - z0) * dy / dz
            if y < crossing_y:
                inside = not inside
    return inside, distance



def _canonical_box_bounds(shape: Mapping) -> list[tuple[float, float]]:
    if set(shape) != {'kind', 'min_mm', 'max_mm'}:
        raise ValueError('invalid canonical IP box fields')
    lo, hi = shape['min_mm'], shape['max_mm']
    if (not isinstance(lo, (list, tuple)) or not isinstance(hi, (list, tuple))
            or len(lo) != 3 or len(hi) != 3
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in (*lo, *hi))
            or any(a > b for a, b in zip(lo, hi, strict=True))):
        raise ValueError('invalid canonical IP box bounds')
    return list(zip(lo, hi, strict=True))



def _ip_x_cylinder_as_rod(shape: Mapping) -> dict:
    keys={'kind','x_min_mm','x_max_mm','center_y_mm','center_z_mm','radius_mm'}
    if set(shape)!=keys: raise ValueError('invalid canonical IP cylinder fields')
    values=[shape[k] for k in ('x_min_mm','x_max_mm','center_y_mm','center_z_mm','radius_mm')]
    if (any(type(v) not in (int,float) or not math.isfinite(v) for v in values)
            or values[0]>values[1] or values[4]<=0): raise ValueError('invalid canonical IP cylinder bounds')
    return {'kind':'rod','center_xy_mm':[values[2],values[3]],'z_min_mm':values[0],
            'z_max_mm':values[1],'radius_mm':values[4]}

def _canonical_polygon(shape: Mapping) -> tuple[Sequence[float], list[list[float]]]:
    if set(shape) != {'kind', 'x', 'polygon_yz_mm'}:
        raise ValueError('invalid canonical extrusion fields')
    bounds, points = shape['x'], shape['polygon_yz_mm']
    if (not isinstance(bounds, (list, tuple)) or len(bounds) != 2
            or any(type(v) not in (int,float) or not math.isfinite(v) for v in bounds)
            or bounds[0] >= bounds[1] or not isinstance(points, (list, tuple)) or len(points) < 3
            or any(not isinstance(p,(list,tuple)) or len(p)!=2 or
                any(type(v) not in (int,float) or not math.isfinite(v) for v in p) for p in points)):
        raise ValueError('invalid canonical extrusion bounds or vertices')
    points = [list(p) for p in points]
    edges = list(zip(points, points[1:] + points[:1], strict=True))
    if any(a == b for a,b in edges): raise ValueError('degenerate polygon edge')
    area = sum(a[0]*b[1]-b[0]*a[1] for a,b in edges)
    if not math.isfinite(area) or area == 0: raise ValueError('degenerate polygon area')
    def cross(a,b,c): return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    def on(a,b,c): return min(a[0],b[0])<=c[0]<=max(a[0],b[0]) and min(a[1],b[1])<=c[1]<=max(a[1],b[1])
    for i,(a,b) in enumerate(edges):
        for j in range(i+1,len(edges)):
            if j == i+1 or (i==0 and j==len(edges)-1): continue
            c,d=edges[j];v=(cross(a,b,c),cross(a,b,d),cross(c,d,a),cross(c,d,b))
            if (any(not math.isfinite(x) for x in v) or
                (v[0]*v[1]<0 and v[2]*v[3]<0) or
                (v[0]==0 and on(a,b,c)) or (v[1]==0 and on(a,b,d)) or
                (v[2]==0 and on(c,d,a)) or (v[3]==0 and on(c,d,b))):
                raise ValueError('self-intersecting polygon')
    return bounds, points

def _shape_relation(shape: Mapping, point: Sequence[float], *, _polygons=None) -> str:
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
            relations = [_shape_relation(part, point, _polygons=_polygons) for part in parts]
            if 'unsupported' in relations: return 'unsupported'
            if 'interior' in relations: return 'interior'
            return 'boundary' if 'boundary' in relations else 'outside'
        base = _shape_relation(shape['base'], point, _polygons=_polygons)
        tools = shape.get('tools')
        if not isinstance(tools, (list, tuple)) or not tools:
            raise ValueError('difference requires tools')
        relations = [_shape_relation(part, point, _polygons=_polygons) for part in tools]
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
    if kind == 'ip_cylinder_x':
        return _shape_relation(_ip_x_cylinder_as_rod(shape), (point[1],point[2],point[0]), _polygons=_polygons)
    if kind == 'ip_box':
        bounds = _canonical_box_bounds(shape)
        if any(point[i] < lo or point[i] > hi for i, (lo, hi) in enumerate(bounds)): return 'outside'
        return 'boundary' if any(point[i] in (lo, hi) for i, (lo, hi) in enumerate(bounds)) else 'interior'
    if kind == 'extruded_yz_polygon':
        if _polygons is None:
            bounds, vertices = _canonical_polygon(shape)
        else:
            bounds, vertices, extrema, vertex_scale = _polygons[id(shape)]
            scale = max(1., vertex_scale, *(abs(v) for v in point), *(abs(v) for v in bounds))
            slack = 64*math.ulp(scale)
            if (point[1] < extrema[0]-slack or point[1] > extrema[1]+slack or
                    point[2] < extrema[2]-slack or point[2] > extrema[3]+slack):
                return 'outside'
        if point[0] < bounds[0] or point[0] > bounds[1]: return 'outside'
        inside, distance = polygon_membership((point[1], point[2]), vertices)
        if distance == 0: return 'boundary'
        if not inside: return 'outside'
        return 'boundary' if point[0] in bounds else 'interior'
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


def _roundoff_near_surface(shape: Mapping, point: Sequence[float], error: Sequence[float], *, _polygons=None) -> bool:
    """Conservatively retain points close to arithmetic surfaces as ambiguous.

    The caller supplies per-axis inverse-transform roundoff bounds. Additional
    ULP terms cover the bounded primitive offset, extent and radial operations;
    they express floating-point uncertainty, not an adjustable physical margin.
    """
    kind = shape['kind']
    if kind == 'difference':
        return _roundoff_near_surface(shape['base'], point, error, _polygons=_polygons) or any(
            _roundoff_near_surface(tool, point, error, _polygons=_polygons) for tool in shape['tools'])
    if kind == 'union':
        return any(_roundoff_near_surface(part, point, error, _polygons=_polygons) for part in shape['parts'])
    if kind == 'ip_cylinder_x':
        return _roundoff_near_surface(_ip_x_cylinder_as_rod(shape), (point[1],point[2],point[0]), (error[1],error[2],error[0]), _polygons=_polygons)
    if kind in {'box', 'ip_box'}:
        bounds = oa_witness_extent(shape) if kind == 'box' else _canonical_box_bounds(shape)
        margin = [error[i] + 8*math.ulp(max(1., abs(point[i]), abs(lo), abs(hi)))
                  for i, (lo, hi) in enumerate(bounds)]
        if any(point[i] < lo-margin[i] or point[i] > hi+margin[i]
               for i, (lo, hi) in enumerate(bounds)):
            return False
        return any(abs(point[i]-lo) <= margin[i] or abs(point[i]-hi) <= margin[i]
                   for i, (lo, hi) in enumerate(bounds))
    if kind == 'extruded_yz_polygon':
        if _polygons is None:
            bounds, vertices = _canonical_polygon(shape)
            scale = max(1., *(abs(v) for v in point), *(abs(v) for p in vertices for v in p), *(abs(v) for v in bounds))
        else:
            bounds, vertices, extrema, vertex_scale = _polygons[id(shape)]
            scale = max(1., *(abs(v) for v in point), vertex_scale, *(abs(v) for v in bounds))
        # Bounds cover inverse-pose error and floating arithmetic in the shared edge-distance calculation.
        slack = 64*math.ulp(scale)
        xerror = error[0] + slack
        if point[0] < bounds[0]-xerror or point[0] > bounds[1]+xerror: return False
        planar_error = math.hypot(error[1],error[2]) + slack
        if _polygons is not None:
            margin = planar_error + 8*math.ulp(scale)
            if (point[1] < extrema[0]-margin or point[1] > extrema[1]+margin or
                    point[2] < extrema[2]-margin or point[2] > extrema[3]+margin):
                return False
        inside, distance = polygon_membership((point[1],point[2]), vertices)
        if distance <= planar_error: return True
        return inside and (abs(point[0]-bounds[0])<=xerror or abs(point[0]-bounds[1])<=xerror)
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


def _query_members(members: Sequence[Mapping], point: Sequence[float], *, frame_id: str, _polygons=None, _poses=None) -> dict:
    """Classify canonical members in their supplied assembly frame and pose.

    An unsupported shape is not treated as empty. Distinct simultaneously
    interior electrode groups are a conflict; boundary contacts stay ambiguous.
    """
    if not isinstance(frame_id, str) or not frame_id:
        raise ValueError('explicit assembly frame is required')
    position = FramedPosition(frame_id, tuple(point))
    inside, boundary, unsupported = set(), set(), []
    local_cache = {}
    for member in members:
        if _poses is None:
            transform = RigidTransform.from_contract(member['transform'])
            local = transform.inverse().transform_position(position)
            pose_key = None
        else:
            pose_key, transform, inverse, _ = _poses[id(member)]
            if pose_key not in local_cache:
                local_cache[pose_key] = [inverse.transform_position(position), None]
            local = local_cache[pose_key][0]
        relation = _shape_relation(member['shape'], local.coordinates_mm, _polygons=_polygons)
        if relation != 'unsupported':
            # Bound the inverse rotation/translation arithmetic conservatively.
            # Each output coordinate has two three-term dot products; 64 ULPs
            # also cover their additions/subtractions and stored-pose rounding.
            cached_error = None if _poses is None else local_cache[pose_key][1]
            if cached_error is None:
                error = [64*math.ulp(max(1., abs(local.coordinates_mm[i]),
                    sum(abs(transform.rotation[j][i]*position.coordinates_mm[j]) +
                        abs(transform.rotation[j][i]*transform.translation_mm[j]) for j in range(3))))
                    for i in range(3)]
                # RigidTransform accepts near-orthogonal R and uses transpose as
                # inverse. Bound its systematic error from E = R.T*R - I:
                # ||(I+E)^-1 u-u||_inf <= ||E||_inf*||u||_inf/(1-||E||_inf).
                if _poses is None:
                    rotation = transform.rotation
                    defect = max(sum(abs(math.fsum(rotation[k][i]*rotation[k][j] for k in range(3))
                                         - (1. if i == j else 0.)) for j in range(3)) for i in range(3))
                    defect_bound = defect + 64*math.ulp(1.)
                else:
                    defect_bound = _poses[id(member)][3]
                if not math.isfinite(defect_bound) or defect_bound >= 1.:
                    raise ValueError('pose inverse uncertainty cannot be bounded')
                magnitude = max(abs(value) + error[i] for i, value in enumerate(local.coordinates_mm))
                pose_error = defect_bound*magnitude/(1.-defect_bound)
                error = [bound + pose_error + 8*math.ulp(max(1., pose_error)) for bound in error]
                if _poses is not None:
                    local_cache[pose_key][1] = error
            else:
                error = cached_error
            if _roundoff_near_surface(member['shape'], local.coordinates_mm, error, _polygons=_polygons):
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


def prepare_member_query(members: Sequence[Mapping], *, frame_id: str):
    """Snapshot members and validate fixed polygons once for repeated queries."""
    if not isinstance(frame_id, str) or not frame_id:
        raise ValueError('explicit assembly frame is required')
    frozen = copy.deepcopy(members)
    polygons = {}
    poses = {}
    unique_poses = {}
    def prepare(shape):
        kind = shape.get('kind')
        if kind == 'extruded_yz_polygon':
            bounds, vertices = _canonical_polygon(shape)
            extrema = (min(p[0] for p in vertices), max(p[0] for p in vertices),
                       min(p[1] for p in vertices), max(p[1] for p in vertices))
            vertex_scale = max(abs(value) for p in vertices for value in p)
            polygons[id(shape)] = (bounds, vertices, extrema, vertex_scale)
        elif kind == 'union':
            for part in shape['parts']: prepare(part)
        elif kind == 'difference':
            prepare(shape['base'])
            for part in shape['tools']: prepare(part)
    for member in frozen:
        prepare(member['shape'])
        key = json.dumps(member['transform'], sort_keys=True, separators=(',', ':'), allow_nan=False)
        if key not in unique_poses:
            transform = RigidTransform.from_contract(member['transform'])
            rotation = transform.rotation
            defect = max(sum(abs(math.fsum(rotation[k][i]*rotation[k][j] for k in range(3))
                                 - (1. if i == j else 0.)) for j in range(3)) for i in range(3))
            unique_poses[key] = (key, transform, transform.inverse(), defect + 64*math.ulp(1.))
        poses[id(member)] = unique_poses[key]
    def query(point):
        return _query_members(frozen, point, frame_id=frame_id, _polygons=polygons, _poses=poses)
    return query


def shape_relation(shape: Mapping, point: Sequence[float]) -> str:
    return _shape_relation(shape, point)


def query_members(members: Sequence[Mapping], point: Sequence[float], *, frame_id: str) -> dict:
    return _query_members(members, point, frame_id=frame_id)
