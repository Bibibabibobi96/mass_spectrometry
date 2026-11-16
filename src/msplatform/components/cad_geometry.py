"""Optional canonical physical-solid CAD projection shared by consumers."""
from __future__ import annotations
import math
from msplatform.contracts.rigid_transform import RigidTransform


def _finite(values):
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in values): raise ValueError('CAD dimensions must be finite')


def _validate_shape(spec, *, surface=False):
    kind=spec.get('kind')
    if kind in {'union','intersection'}:
        if not spec.get('parts'): raise ValueError('empty physical union')
        for part in spec['parts']: _validate_shape(part,surface=surface)
    elif kind=='difference':
        _validate_shape(spec['base'],surface=surface)
        if not spec['tools']: raise ValueError('empty Boolean tool list')
        for tool in spec['tools']: _validate_shape(tool,surface=surface)
    elif kind=='revolved_profile':
        points=spec.get('points_zr_mm',())
        if len(points)<3 or any(len(point)!=2 for point in points): raise ValueError('revolved profile requires z/r pairs')
        _finite([value for point in points for value in point])
        if any(point[1]<0 for point in points): raise ValueError('revolved profile radius cannot be negative')
        area=sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(points,(*points[1:],points[0]),strict=True))
        if area==0: raise ValueError('revolved profile must enclose a nonzero section')
    elif kind in {'ip_box','ip_cylinder_x','ip_convex_polyhedron'}:
        from msplatform.components.dual_pressure_rectilinear_ion_processor.convex_geometry import shape_bounds
        lo, hi = shape_bounds(dict(shape=kind[3:], **{k:v for k,v in spec.items() if k != 'kind'}))
        if any(a >= b for a,b in zip(lo,hi,strict=True)):
            raise ValueError('IP CAD physical solid must have strictly positive extents')
    elif kind=='extruded_yz_polygon':
        x, points=spec['x'],spec['polygon_yz_mm']
        if len(x)!=2 or len(points)<3 or any(len(p)!=2 for p in points):raise ValueError('MR polygon extrusion requires x bounds and yz vertices')
        _finite([*x,*[v for p in points for v in p]])
        if x[0]>=x[1] or sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(points,(*points[1:],points[0]),strict=True))==0:
            raise ValueError('MR polygon extrusion requires nonzero physical span and area')
    elif kind=='box':
        _finite([*spec['center_mm'],*spec['size_mm']])
        if len(spec['center_mm'])!=3 or len(spec['size_mm'])!=3 or any(v<0 or (v==0 and not surface) for v in spec['size_mm']): raise ValueError('invalid box dimensions')
    elif kind=='cylinder':
        _finite([*spec['center_mm'],spec['radius_mm'],spec['height_mm']])
        if len(spec['center_mm'])!=3 or spec['radius_mm']<=0 or spec['height_mm']<0 or (spec['height_mm']==0 and not surface): raise ValueError('invalid cylinder dimensions')
    elif kind in {'rod','annulus'}:
        _finite([*spec['center_xy_mm'],spec['z_min_mm'],spec['z_max_mm']])
        if len(spec['center_xy_mm'])!=2 or spec['z_max_mm']<spec['z_min_mm'] or (spec['z_max_mm']==spec['z_min_mm'] and not surface): raise ValueError('invalid physical axial interval')
        if kind=='annulus':
            _finite([spec['inner_radius_mm'],spec['outer_radius_mm']])
            if not 0<=spec['inner_radius_mm']<spec['outer_radius_mm']: raise ValueError('invalid annulus radii')
        elif 'radius_mm' in spec:
            _finite([spec['radius_mm']])
            if spec['radius_mm']<=0: raise ValueError('invalid rod radius')
        else:
            _finite([spec[k] for k in ('semi_major_axis_mm','semi_minor_axis_mm','major_axis_angle_rad')])
            if not 0<spec['semi_minor_axis_mm']<=spec['semi_major_axis_mm']: raise ValueError('invalid ellipse axes')
    else: raise ValueError('unknown physical primitive')


def _shape(cq, spec):
    kind=spec['kind']
    if kind in {'union','intersection'}:
        parts=[_shape(cq,p) for p in spec['parts']]
        if not parts: raise ValueError('empty physical union')
        result=parts[0]
        for part in parts[1:]: result=result.fuse(part) if kind=='union' else result.intersect(part)
        return result
    if kind=='difference':
        result=_shape(cq,spec['base'])
        for tool in spec['tools']: result=result.cut(_shape(cq,tool))
        return result
    if kind=='revolved_profile':
        _validate_shape(spec)
        # CadQuery workplane-local x/y are radial r / axial z on the XZ plane.
        return cq.Workplane('XZ').polyline([(r,z) for z,r in spec['points_zr_mm']]).close().revolve(360,(0,0),(0,1)).val()
    if kind.startswith('ip_'):
        _validate_shape(spec)
        if kind == 'ip_box':
            lo, hi = spec['min_mm'], spec['max_mm']
            center = [(a+b)/2 for a,b in zip(lo,hi,strict=True)]
            size = [b-a for a,b in zip(lo,hi,strict=True)]
            return cq.Workplane('XY').box(*size).val().translate(tuple(center))
        if kind == 'ip_cylinder_x':
            return cq.Solid.makeCylinder(spec['radius_mm'], spec['x_max_mm']-spec['x_min_mm'],
                (spec['x_min_mm'],spec['center_y_mm'],spec['center_z_mm']), (1,0,0))
        if kind == 'ip_convex_polyhedron':
            from msplatform.components.dual_pressure_rectilinear_ion_processor.convex_geometry import _convex_hull
            import numpy as np
            hull = _convex_hull(dict(shape='convex_polyhedron',vertices_mm=spec['vertices_mm']))
            faces = []
            for indices, plane in zip(hull.simplices, hull.equations, strict=True):
                points = hull.points[indices]
                if np.dot(np.cross(points[1]-points[0],points[2]-points[0]),plane[:3]) < 0:
                    points = points[[0,2,1]]
                wire = cq.Wire.makePolygon([tuple(float(v) for v in point) for point in points],close=True)
                faces.append(cq.Face.makeFromWires(wire))
            shell = cq.Shell.makeShell(faces)
            if not shell.isValid() or not shell.wrapped.Closed():
                raise ValueError('IP convex hull did not form a valid closed CAD shell')
            solid = cq.Solid.makeSolid(shell)
            if not solid.isValid() or not solid.Solids() or solid.Volume() <= 0:
                raise ValueError('IP convex hull did not form a valid CAD solid')
            return solid
        raise ValueError('unsupported IP physical CAD shape: '+kind)
    if kind=='extruded_yz_polygon':
        _validate_shape(spec)
        return cq.Workplane('YZ').polyline([tuple(p) for p in spec['polygon_yz_mm']]).close().extrude(spec['x'][1]-spec['x'][0]).val().translate((spec['x'][0],0,0))
    if kind=='box':
        center,size=spec['center_mm'],spec['size_mm'];_finite([*center,*size])
        if min(size)<=0: raise ValueError('physical CAD box must have positive spans')
        return cq.Workplane('XY').box(*size).val().translate(tuple(center))
    if kind=='cylinder':
        x,y,z=spec['center_mm'];r,h=spec['radius_mm'],spec['height_mm'];_finite([x,y,z,r,h])
        if min(r,h)<=0: raise ValueError('physical CAD cylinder must have positive dimensions')
        return cq.Workplane('XY').circle(r).extrude(h).val().translate((x,y,z-h/2))
    if kind in {'rod','annulus'}:
        x,y=spec['center_xy_mm'];lo,hi=spec['z_min_mm'],spec['z_max_mm'];_finite([x,y,lo,hi])
        if hi<=lo: raise ValueError('physical CAD axial interval must be positive')
        work=cq.Workplane('XY')
        angle=0.
        if kind=='annulus':
            inner,outer=spec['inner_radius_mm'],spec['outer_radius_mm'];_finite([inner,outer])
            if not 0<=inner<outer: raise ValueError('invalid annulus radii')
            work=work.circle(outer)
            if inner>0: work=work.circle(inner)
        elif 'radius_mm' in spec:
            r=spec['radius_mm'];_finite([r])
            if r<=0: raise ValueError('rod radius must be positive')
            work=work.circle(r)
        else:
            a,b,angle=(spec[k] for k in ('semi_major_axis_mm','semi_minor_axis_mm','major_axis_angle_rad'));_finite([a,b,angle])
            if not 0<b<=a: raise ValueError('invalid ellipse axes')
            work=work.ellipse(a,b)
        result=work.extrude(hi-lo).val()
        if angle: result=result.rotate((0,0,0),(0,0,1),math.degrees(angle))
        return result.translate((x,y,lo))
    raise ValueError('unsupported physical CAD shape: '+str(kind))


def _cad_precision_profile():
    from OCP.Precision import Precision
    approximation,confusion=Precision.Approximation_s(),Precision.Confusion_s()
    if approximation!=1e-6 or confusion!=1e-7:
        raise RuntimeError('OCCT precision differs from the predeclared millimetre CAD profile')
    return dict(profile_id='physical_solids_occt_approximation_v1', length_error_bound_mm=1e-6,
                occt_approximation=approximation, occt_confusion=confusion)


def _member_location(cq, transform):
    t = RigidTransform.from_contract(transform)
    r = t.rotation
    return cq.Location(cq.Plane(origin=t.translation_mm, xDir=(r[0][0],r[1][0],r[2][0]),
                               normal=(r[0][2],r[1][2],r[2][2])))




def placed_physical_solid(member):
    """Project one canonical member; optional CAD is loaded only on demand."""
    try:
        import cadquery as cq
    except ImportError as error:
        raise RuntimeError('ambiguous conductor separation requires optional cad-step') from error
    _cad_precision_profile()
    _validate_shape(member['shape'])
    solid = _shape(cq, member['shape']).moved(_member_location(cq, member['transform']))
    if not solid.isValid() or not solid.Solids() or solid.Volume() <= 0:
        raise ValueError('invalid canonical CAD physical member')
    return solid


def classify_solid_pair(first, second, *, proven_contact=False):
    """Prove separation or topological contact; unresolved cases fail closed."""
    profile = _cad_precision_profile()
    distance = first.distance(second)
    if not math.isfinite(distance) or distance < 0:
        raise ValueError('invalid CAD separation distance')
    if distance > 2 * profile['length_error_bound_mm']:
        return 'separated'
    if distance != 0:
        raise ValueError('ambiguous CAD separation within precision profile')
    common = first.intersect(second)
    if common.wrapped.IsNull() or not common.isValid():
        raise ValueError('CAD contact topology is unavailable or invalid')
    volume = common.Volume()
    if not math.isfinite(volume) or volume > 0:
        raise ValueError('independent conductor solids overlap')
    if volume != 0 or not proven_contact:
        raise ValueError('CAD zero-volume contact topology is unproved')
    return 'contact'


def serialized_axis_cylinder(top, radius, height, axis):
    """Project an emitted SIMION cylinder along its existing world axis."""
    try:
        import cadquery as cq
    except ImportError as error:
        raise RuntimeError('ambiguous conductor separation requires optional cad-step') from error
    _cad_precision_profile()
    if axis not in (0, 1, 2) or radius <= 0 or height <= 0:
        raise ValueError('invalid serialized cylinder')
    direction = tuple(-1 if index == axis else 0 for index in range(3))
    solid = cq.Solid.makeCylinder(radius, height, tuple(top), direction)
    if not solid.isValid() or not solid.Solids() or solid.Volume() <= 0:
        raise ValueError('invalid serialized CAD cylinder')
    return solid
