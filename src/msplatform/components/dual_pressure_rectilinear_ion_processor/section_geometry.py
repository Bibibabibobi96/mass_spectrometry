"""Exact IP native-to-project plane sections and electrode cutout geometry.

Coordinates are mm; views retain the existing fixed IP/project axis mapping.
This pure geometry boundary neither renders figures nor reads run data.
"""
import math

def world_bounds(shape, origin_z_mm: float):
    from msplatform.components.dual_pressure_rectilinear_ion_processor.convex_geometry import shape_bounds
    a, b = shape_bounds(shape)
    return ([-b[2], a[0], origin_z_mm - b[1]], [-a[2], b[0], origin_z_mm - a[1]])


def section(shape, view, value, origin_z_mm: float):
    """Exact plane intersection; rectangles, circles or ordered world polygons."""
    h, v, f = {'long': (1, 2, 0), 'top': (1, 0, 2), 'cross': (0, 2, 1)}[view]
    if shape['shape'] == 'convex_polyhedron':
        from msplatform.components.dual_pressure_rectilinear_ion_processor.convex_geometry import convex_section
        axis, local_value = {'long': (2, -value), 'top': (1, origin_z_mm-value), 'cross': (0, value)}[view]
        vertices = convex_section(shape, axis, local_value)
        if vertices is None or len(vertices) < 3:
            return None
        world = [(-p[2], p[0], origin_z_mm-p[1]) for p in vertices]
        return ('polygon', tuple((p[h], p[v]) for p in world))
    if shape['shape'] == 'box':
        a, b = world_bounds(shape, origin_z_mm)
        if not a[f] <= value <= b[f]:
            return None
        return ('rect', (a[h], a[v], b[h], b[v]))
    assert shape['shape'] == 'cylinder_x'
    cx, cz = (-shape['center_z_mm'], origin_z_mm - shape['center_y_mm'])
    r = shape['radius_mm']
    if view == 'cross':
        if shape['x_min_mm'] <= value <= shape['x_max_mm']:
            return ('circle', (cx, cz, r))
        return None
    delta = value - (cz if view == 'top' else cx)
    if abs(delta) >= r:
        return None
    half = math.sqrt(r * r - delta * delta)
    center = cx if view == 'top' else cz
    return ('rect', (shape['x_min_mm'], center - half, shape['x_max_mm'], center + half))


def subtract(rect, cut):
    a, b, c, d = rect
    e, f, g, h = cut
    x0, y0, x1, y1 = (max(a, e), max(b, f), min(c, g), min(d, h))
    if x0 >= x1 or y0 >= y1:
        return [rect]
    return [r for r in [(a, b, x0, d), (x1, b, c, d), (x0, b, x1, y0), (x0, y1, x1, d)] if r[2] > r[0] and r[3] > r[1]]


def _polygon_vertices(item):
    if item[0] == 'polygon':
        return list(item[1])
    if item[0] != 'rect':
        raise ValueError('Circular apertures require curved Boolean section support')
    a, b, c, d = item[1]
    return [(a,b),(c,b),(c,d),(a,d)]


def _polygon_area(vertices):
    return sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(vertices,vertices[1:]+vertices[:1]))/2


def _half_plane(vertices, a, b, inside):
    """Clip one convex polygon against an oriented closed half-plane."""
    result = []
    if not vertices:
        return result
    def distance(p):
        return (b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])
    for previous, current in zip(vertices[-1:]+vertices[:-1],vertices):
        d0, d1 = distance(previous), distance(current)
        keep0, keep1 = (d0 >= 0, d1 >= 0) if inside else (d0 <= 0, d1 <= 0)
        if keep0 != keep1:
            fraction = d0/(d0-d1)
            result.append(tuple(p+fraction*(q-p) for p,q in zip(previous,current)))
        if keep1:
            result.append(tuple(current))
    unique = []
    for point in result:
        if not unique or point != unique[-1]:
            unique.append(point)
    if len(unique)>1 and unique[0] == unique[-1]:
        unique.pop()
    return unique if len(unique)>=3 and abs(_polygon_area(unique))>0 else []


def _subtract_polygon(vertices, cut):
    """Partition a convex polygon minus a convex cut into disjoint polygons."""
    if _polygon_area(cut)<0:
        cut = list(reversed(cut))
    result, remaining = [], vertices
    for a,b in zip(cut,cut[1:]+cut[:1]):
        outside = _half_plane(remaining,a,b,False)
        if outside:
            result.append(outside)
        remaining = _half_plane(remaining,a,b,True)
        if not remaining:
            break
    return result


def section_centroid(kind, shape):
    """Return a section annotation point without substituting its bounding box."""
    if kind == 'circle':
        return tuple(shape[:2])
    if kind == 'rect':
        return ((shape[0]+shape[2])/2,(shape[1]+shape[3])/2)
    vertices = list(shape)
    area = _polygon_area(vertices)
    factors = [a[0]*b[1]-b[0]*a[1] for a,b in zip(vertices,vertices[1:]+vertices[:1])]
    return tuple(sum((a[k]+b[k])*f for a,b,f in zip(vertices,vertices[1:]+vertices[:1],factors))/(6*area) for k in (0,1))


def parts(electrode, view, value, origin_z_mm: float):
    cuts = [section(s, view, value, origin_z_mm) for s in electrode['cutouts']]
    result = []
    for solid in electrode['solids']:
        item = section(solid, view, value, origin_z_mm)
        if item is None:
            continue
        if item[0] == 'circle':
            assert not any(cuts)
            result.append(item)
            continue
        if item[0] == 'polygon' or any(c and c[0] == 'polygon' for c in cuts):
            polygons = [_polygon_vertices(item)]
            for cut in cuts:
                if cut is not None:
                    polygons = [piece for polygon in polygons for piece in _subtract_polygon(polygon,_polygon_vertices(cut))]
            result.extend(('polygon',tuple(p)) for p in polygons)
            continue
        rects = [item[1]]
        for cut in cuts:
            if cut is None:
                continue
            assert cut[0] == 'rect', 'Circular transverse aperture requires explicit polygon Boolean support'
            rects = [p for r in rects for p in subtract(r, cut[1])]
        result.extend((('rect', r) for r in rects))
    return result
