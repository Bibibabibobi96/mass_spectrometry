"""Bounded neutral Assembly to legacy GEM; geometry only, never solve or Fly."""
from __future__ import annotations

import copy
import hashlib
import math
import re
from collections.abc import Mapping
from fractions import Fraction
from typing import Any

from msplatform.components.geometry_members import assembly_geometry_members
from msplatform.contracts.rigid_transform import RigidTransform
from .gem_primitives import centered_box3d, cylinder_z, format_number, grounded_pa_face_lines


def _vector(value: Any, name: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3 or any(type(x) not in (int, float) or not math.isfinite(x) for x in value):
        raise ValueError(name + ' requires three finite numbers')
    return [float(x) for x in value]


def _record_rounding(values: list[float], rounding: list[dict[str, Any]]) -> None:
    for value in values:
        text = format_number(value)
        if float(text) != value:
            rounding.append({'input': value, 'serialized': text})


def _world_primitive(shape: Mapping[str, Any], transform: RigidTransform, rounding: list[dict[str, Any]]) -> tuple[str, list[float], list[float]]:
    kind = shape.get('kind'); rotation = transform.rotation
    if kind == 'rod':
        if set(shape) != {'kind', 'center_xy_mm', 'z_min_mm', 'z_max_mm', 'radius_mm'}:
            raise ValueError('GEM supports only canonical round rods')
        center_xy = shape['center_xy_mm']; low = shape['z_min_mm']; high = shape['z_max_mm']
        if (not isinstance(center_xy, (list, tuple)) or len(center_xy) != 2
                or any(type(value) not in (int, float) or not math.isfinite(value)
                       for value in (*center_xy, low, high)) or high <= low):
            raise ValueError('GEM round rod requires finite center and positive axial extent')
        shape = dict(kind='cylinder', center_mm=[*center_xy, (low + high) / 2],
                     radius_mm=shape['radius_mm'], height_mm=high - low)
        kind = 'cylinder'
    if any(sum(abs(x) for x in row) != 1 or any(x not in (-1, 0, 1) for x in row) for row in rotation):
        raise ValueError('GEM pose requires a signed axis-permutation rotation')
    if kind == 'extruded_yz_polygon':
        from msplatform.components.shape_query import _canonical_polygon
        from .mr_geometry import _extrude_polygon_bands, _polygon_bands
        if set(shape) != {'kind', 'x', 'polygon_yz_mm'}:
            raise ValueError('GEM extruded polygon requires the canonical fields')
        bounds, vertices = _canonical_polygon(shape)
        if abs(rotation[0][0]) != 1:
            raise ValueError('GEM extruded yz polygon requires its x axis to remain world x')
        local_lo = [bounds[0], min(point[0] for point in vertices), min(point[1] for point in vertices)]
        local_hi = [bounds[1], max(point[0] for point in vertices), max(point[1] for point in vertices)]
        x = sorted(rotation[0][0] * value + transform.translation_mm[0] for value in shape['x'])
        polygon = [[sum(rotation[i][j] * point[j-1] for j in (1, 2))
                    + transform.translation_mm[i] for i in (1, 2)]
                   for point in shape['polygon_yz_mm']]
        lower = [min(rotation[i][j] * local_lo[j] + transform.translation_mm[i],
                     rotation[i][j] * local_hi[j] + transform.translation_mm[i])
                 for i in range(3) for j in range(3) if rotation[i][j]]
        upper = [max(rotation[i][j] * local_lo[j] + transform.translation_mm[i],
                     rotation[i][j] * local_hi[j] + transform.translation_mm[i])
                 for i in range(3) for j in range(3) if rotation[i][j]]
        _record_rounding(x + [value for point in polygon for value in point], rounding)
        bands = _polygon_bands(shape['polygon_yz_mm'])
        transformed_bands = [[[sum(rotation[i][j] * point[j-1] for j in (1, 2))
                               + transform.translation_mm[i] for i in (1, 2)]
                              for point in band] for band in bands]
        return ' '.join(term for band in transformed_bands
                        for term in _extrude_polygon_bands(x, band)), lower, upper
    if kind in {'ip_box', 'ip_cylinder_x'}:
        from msplatform.components.dual_pressure_rectilinear_ion_processor.convex_geometry import shape_bounds
        from .ip_geometry import _primitive
        local = {'shape': kind[3:], **{key: value for key, value in shape.items() if key != 'kind'}}
        local_lo, local_hi = shape_bounds(local)
        center = [(a+b)/2 for a,b in zip(local_lo,local_hi,strict=True)]
        size = [b-a for a,b in zip(local_lo,local_hi,strict=True)]
        if kind == 'ip_cylinder_x':
            center = [(local['x_min_mm']+local['x_max_mm'])/2,local['center_y_mm'],local['center_z_mm']]
            size = [local['x_max_mm']-local['x_min_mm'],2*local['radius_mm'],2*local['radius_mm']]
        if any(value <= 0 for value in size): raise ValueError('GEM physical primitive requires positive extents')
        world = [sum(rotation[i][j]*center[j] for j in range(3))+transform.translation_mm[i] for i in range(3)]
        span = [sum(abs(rotation[i][j])*size[j] for j in range(3)) for i in range(3)]
        lower=[];upper=[]
        for i in range(3):
            j=next(j for j in range(3) if rotation[i][j])
            endpoints=[rotation[i][j]*value+transform.translation_mm[i] for value in (local_lo[j],local_hi[j])]
            lower.append(min(endpoints));upper.append(max(endpoints))
        if kind == 'ip_box':
            _record_rounding(world+span, rounding)
            return _primitive(dict(shape='box',min_mm=lower,max_mm=upper)),lower,upper
        radius = local['radius_mm']; axis = next(i for i in range(3) if abs(rotation[i][0]) == 1)
        height = local_hi[0]-local_lo[0]
        if axis == 0:
            _record_rounding([lower[0],upper[0],world[1],world[2],radius], rounding)
            return _primitive(dict(shape='cylinder_x',x_min_mm=lower[0],x_max_mm=upper[0],
                center_y_mm=world[1],center_z_mm=world[2],radius_mm=radius)),lower,upper
        top = list(world); top[axis] += height/2
        _record_rounding(top+[radius,height], rounding)
        if axis == 2:
            return cylinder_z(top[0],top[1],top[2],radius,height),lower,upper
        primitive = ('locate(' + ','.join(format_number(v) for v in top) + ') { rotate_x(-90) { '
                     + cylinder_z(0.,0.,0.,radius,height) + ' } }')
        return primitive,lower,upper
    center = _vector(shape.get('center_mm'), 'primitive center')
    world = [sum(rotation[i][j]*center[j] for j in range(3))+transform.translation_mm[i] for i in range(3)]
    if kind == 'box':
        size = _vector(shape.get('size_mm'), 'box size')
        if any(x <= 0 for x in size): raise ValueError('GEM physical box requires positive extents')
        span = [sum(abs(rotation[i][j])*size[j] for j in range(3)) for i in range(3)]
        _record_rounding(world+span, rounding)
        return centered_box3d(*world, *span), [world[i]-span[i]/2 for i in range(3)], [world[i]+span[i]/2 for i in range(3)]
    if kind == 'cylinder':
        radius, height = shape.get('radius_mm'), shape.get('height_mm')
        if any(type(x) not in (int,float) or not math.isfinite(x) or x <= 0 for x in (radius,height)):
            raise ValueError('GEM physical cylinder requires positive finite radius and height')
        radius, height = float(radius), float(height)
        axis = next(i for i in range(3) if abs(rotation[i][2]) == 1)
        span = [2 * radius] * 3; span[axis] = height
        low = [world[i] - span[i] / 2 for i in range(3)]
        high = [world[i] + span[i] / 2 for i in range(3)]
        top = list(world); top[axis] += height / 2
        if axis == 2:
            _record_rounding([world[0], world[1], radius, height, top[2]], rounding)
            primitive = cylinder_z(top[0], top[1], top[2], radius, height)
        else:
            _record_rounding(top + [radius, height], rounding)
            rotate = 'rotate_y(90)' if axis == 0 else 'rotate_x(-90)'
            primitive = ('locate(' + ','.join(format_number(v) for v in top) + ') { '
                         + rotate + ' { ' + cylinder_z(0., 0., 0., radius, height) + ' } }')
        return primitive, low, high
    raise ValueError('unsupported GEM physical primitive: '+str(kind))


def _pieces(shape: Mapping[str, Any], transform: RigidTransform, rounding: list[dict[str, Any]]) -> list[tuple[str,list[str],list[float],list[float]]]:
    if not isinstance(shape,Mapping): raise ValueError('GEM member shape must be a mapping')
    kind=shape.get('kind')
    if kind=='union':
        parts=shape.get('parts')
        if not isinstance(parts,(list,tuple)) or not parts: raise ValueError('GEM union requires nonempty parts')
        return [piece for part in parts for piece in _pieces(part,transform,rounding)]
    if kind=='difference':
        base=shape.get('base');tools=shape.get('tools')
        if not isinstance(base,Mapping) or not isinstance(tools,(list,tuple)) or not tools:
            raise ValueError('GEM difference requires a base and tools')
        def flatten_tool(tool):
            if not isinstance(tool,Mapping): raise ValueError('GEM difference tool must be a shape')
            if tool.get('kind')=='union':
                parts=tool.get('parts')
                if not isinstance(parts,(list,tuple)) or not parts: raise ValueError('GEM union requires nonempty parts')
                return [term for part in parts for term in flatten_tool(part)]
            if tool.get('kind')=='difference': raise ValueError('nested difference tool is not supported by GEM')
            return [_world_primitive(tool,transform,rounding)[0]]
        cuts=[term for tool in tools for term in flatten_tool(tool)]
        pieces=_pieces(base,transform,rounding)
        return [(primitive,prior+cuts,lo,hi) for primitive,prior,lo,hi in pieces]
    primitive,lo,hi=_world_primitive(shape,transform,rounding)
    return [(primitive,[],lo,hi)]


def _serialized_primitive_bounds(primitive, *, exact=False):
    """Conservative bounds decoded from the renderer's exact emitted primitives."""
    num=r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'
    def bounds(values):
        if exact:
            return ([v[0] for v in values], [v[1] for v in values])
        return ([math.nextafter(float(v[0]),-math.inf) for v in values],
                [math.nextafter(float(v[1]),math.inf) for v in values])
    box=re.fullmatch(r'centered_box3D\(([^()]*)\)',primitive)
    if box:
        values=[Fraction(x) for x in box.group(1).split(',')]
        if len(values)!=6:raise ValueError('unrecognized serialized box')
        return bounds([(values[i]-values[i+3]/2,values[i]+values[i+3]/2) for i in range(3)])
    polygon=re.compile(r'extrude_yz\(('+num+r'),('+num+r')\) \{ polyline\(([^()]*)\) \}')
    matches=list(polygon.finditer(primitive))
    if matches and not polygon.sub('',primitive).strip():
        spans=[]
        for match in matches:
            x=[Fraction(match.group(1)),Fraction(match.group(2))]
            coords=[Fraction(v) for v in match.group(3).split(',')]
            if len(coords)<6 or len(coords)%2:raise ValueError('unrecognized serialized polygon')
            spans.append(((min(x),max(x)),(min(coords[::2]),max(coords[::2])),(min(coords[1::2]),max(coords[1::2]))))
        return bounds([(min(x[i][0] for x in spans),max(x[i][1] for x in spans)) for i in range(3)])
    locate=re.match(r'locate\(('+num+r'),('+num+r'),('+num+r')(,1,90)?\) \{ ',primitive)
    cylinder=re.search(r'cylinder\(0,0,0,('+num+r'),,('+num+r')\)',primitive)
    if locate and cylinder:
        rest=primitive[locate.end():]
        if locate.group(4): axis=0
        elif rest.startswith('rotate_y(90) { '):axis=0
        elif rest.startswith('rotate_x(-90) { '):axis=1
        else:axis=2
        # The accepted forms are exactly those emitted by _world_primitive.
        prefix=('rotate_y(90) { ' if axis==0 and not locate.group(4) else
                'rotate_x(-90) { ' if axis==1 else '')
        body='cylinder(0,0,0,'+cylinder.group(1)+',,'+cylinder.group(2)+')'
        expected=prefix+'locate(0,0,0) { '+body+' } } }' if prefix else body+' }'
        if rest!=expected:raise ValueError('unrecognized serialized cylinder')
        center=[Fraction(locate.group(i)) for i in (1,2,3)];radius=Fraction(cylinder.group(1));height=Fraction(cylinder.group(2))
        spans=[(center[i]-radius,center[i]+radius) for i in range(3)]
        spans[axis]=(center[axis]-height,center[axis])
        return bounds(spans)
    raise ValueError('unsupported serialized GEM primitive bounds')


def _serialized_polygon_member(member):
    """Reconstruct only the existing serialized polygon-band CSG in world coordinates."""
    from .mr_geometry import _polygon_bands
    transform=RigidTransform.from_contract(member['transform']);rotation=transform.rotation
    def number(value): return float(format_number(value))
    def convert(shape):
        kind=shape.get('kind')
        if kind=='union': return dict(kind='union',parts=[convert(x) for x in shape['parts']])
        if kind=='difference':return dict(kind='difference',base=convert(shape['base']),tools=[convert(x) for x in shape['tools']])
        if kind=='ip_box':
            primitive,_,_=_world_primitive(shape,transform,[])
            matched=re.fullmatch(r'centered_box3D\(([^()]*)\)',primitive)
            if not matched:raise ValueError('unrecognized serialized IP box')
            values=[float(v) for v in matched.group(1).split(',')]
            return dict(kind='box',center_mm=values[:3],size_mm=values[3:])
        if kind=='box':
            center=_vector(shape.get('center_mm'),'box center'); size=_vector(shape.get('size_mm'),'box size')
            if any(value<=0 for value in size):raise ValueError('serialized physical box requires positive extents')
            world=[sum(rotation[i][j]*center[j] for j in range(3))+transform.translation_mm[i] for i in range(3)]
            span=[sum(abs(rotation[i][j])*size[j] for j in range(3)) for i in range(3)]
            return dict(kind='box',center_mm=[number(v) for v in world],size_mm=[number(v) for v in span])
        if kind!='extruded_yz_polygon':raise ValueError('rounded CAD proof lacks supported serialized primitive')
        if abs(rotation[0][0]) != 1:raise ValueError('serialized polygon requires world-x extrusion')
        x=sorted(number(rotation[0][0]*v+transform.translation_mm[0]) for v in shape['x'])
        def world(q):return [sum(rotation[i][j]*q[j-1] for j in (1,2))+transform.translation_mm[i] for i in (1,2)]
        bands=[dict(kind='extruded_yz_polygon',x=x,polygon_yz_mm=[[number(v) for v in q] for q in second])
               for band in _polygon_bands(shape['polygon_yz_mm'])
               for second in _polygon_bands([world(q) for q in band])]
        return bands[0] if len(bands)==1 else dict(kind='union',parts=bands)
    identity=dict(schema_version=1,role='rigid_transform',from_frame_id='world',to_frame_id='world',
                  rotation=[[1,0,0],[0,1,0],[0,0,1]],translation_mm=[0,0,0])
    return dict(shape=convert(member['shape']),transform=identity)


def _serialized_member_solid(member):
    """Build the exact emitted CSG forms using the shared optional CAD adapter."""
    from msplatform.components.cad_geometry import placed_physical_solid, serialized_axis_cylinder
    transform=RigidTransform.from_contract(member['transform'])
    def convert(shape):
        kind=shape.get('kind')
        if kind=='union':
            parts=[convert(part) for part in shape['parts']]
            result=parts[0]
            for part in parts[1:]:result=result.fuse(part)
            return result
        if kind=='difference':
            result=convert(shape['base'])
            for tool in shape['tools']:result=result.cut(convert(tool))
            return result
        if kind in {'cylinder','ip_cylinder_x','rod'}:
            primitive,_,_=_world_primitive(shape,transform,[])
            lo,hi=_serialized_primitive_bounds(primitive,exact=True)
            axis=0 if ',1,90)' in primitive or 'rotate_y(90)' in primitive else 1 if 'rotate_x(-90)' in primitive else 2
            radius_match=re.search(r'cylinder\(0,0,0,([^,]+),,([^()]+)\)',primitive)
            if not radius_match:raise ValueError('unrecognized serialized cylinder')
            top=[float((lo[i]+hi[i])/2) for i in range(3)];top[axis]=float(hi[axis])
            return serialized_axis_cylinder(top,float(Fraction(radius_match.group(1))),
                                            float(Fraction(radius_match.group(2))),axis)
        return placed_physical_solid(_serialized_polygon_member(dict(shape=shape,transform=member['transform'])))
    solid=convert(member['shape'])
    if not solid.isValid() or not solid.Solids() or solid.Volume()<=0:
        raise ValueError('invalid serialized CAD physical member')
    return solid


def _polygon_contact_proof(first, second):
    """Prove a shared uncut polygon edge remains separating after GEM serialization."""
    from .mr_geometry import _polygon_bands
    from msplatform.components.shape_query import shape_relation
    if first['transform'] != second['transform']:
        return False
    transform = RigidTransform.from_contract(first['transform'])
    rotation = transform.rotation
    if abs(rotation[0][0]) != 1:
        return False
    bases = []
    for member in (first, second):
        shape = member['shape']
        base = shape.get('base') if shape.get('kind') == 'difference' else shape
        if base.get('kind') != 'extruded_yz_polygon':
            return False
        tools = shape.get('tools', []) if shape.get('kind') == 'difference' else []
        if any(tool.get('kind') != 'extruded_yz_polygon' for tool in tools):
            return False
        bases.append((base, tools, shape))
    if bases[0][0]['x'] != bases[1][0]['x']:
        return False
    x = bases[0][0]['x'][0]
    world_x = rotation[0][0]*x + transform.translation_mm[0]
    serialized_x = Fraction(format_number(world_x))
    for _, tools, _ in bases:
        for tool in tools:
            bounds = [Fraction(format_number(rotation[0][0]*v+transform.translation_mm[0])) for v in tool['x']]
            if min(bounds) <= serialized_x <= max(bounds):
                return False
    p1, p2 = (base['polygon_yz_mm'] for base, _, _ in bases)
    def rational(point, serialize):
        return tuple(Fraction(format_number(v)) if serialize else Fraction.from_float(float(v)) for v in point)
    def world(point):
        return [sum(rotation[i][j]*point[j-1] for j in (1,2))+transform.translation_mm[i] for i in (1,2)]
    def sides(edge, points):
        (a,b)=edge
        return [(b[0]-a[0])*(q[1]-a[1])-(b[1]-a[1])*(q[0]-a[0]) for q in points]
    for i, a in enumerate(p1):
        b = p1[(i+1)%len(p1)]
        if not any((a == p2[j] and b == p2[(j+1)%len(p2)]) or
                   (b == p2[j] and a == p2[(j+1)%len(p2)]) for j in range(len(p2))):
            continue
        point=[x,*a]
        if any(shape_relation(shape,point) != 'boundary' or
               any(shape_relation(tool,point) != 'outside' for tool in tools)
               for _,tools,shape in bases):
            continue
        edge=(rational(a,False),rational(b,False))
        first_side=sides(edge,[rational(q,False) for q in p1]);second_side=sides(edge,[rational(q,False) for q in p2])
        def opposite(left,right):
            return ((all(v>=0 for v in left) and any(v>0 for v in left) and all(v<=0 for v in right) and any(v<0 for v in right)) or
                    (all(v<=0 for v in left) and any(v<0 for v in left) and all(v>=0 for v in right) and any(v>0 for v in right)))
        if not opposite(first_side,second_side):
            continue
        edge=(rational(world(a),True),rational(world(b),True))
        band_points=[[rational(world(q),True) for band in _polygon_bands(poly) for q in band] for poly in (p1,p2)]
        if opposite(sides(edge,band_points[0]),sides(edge,band_points[1])):
            return True
    return False


def render_assembly_gem(assembly: Mapping[str, Any], *, domain: Mapping[str, Any], pitch_mm: float,
                        boundary: str) -> dict[str, Any]:
    """Render the actual source-validated provider members."""
    members = assembly_geometry_members(assembly)
    return _render_assembly_members_gem(assembly, members, domain=domain, pitch_mm=pitch_mm, boundary=boundary)


def _render_assembly_members_gem(assembly: Mapping[str, Any], members, *, domain: Mapping[str, Any],
                                 pitch_mm: float, boundary: str) -> dict[str, Any]:
    """Render a source-validated neutral Assembly, without a native process.

    Only signed-permutation boxes and cylinders are admitted. Distinct
    conductor AABBs must be strictly separated; ambiguous overlap is refused.
    """
    if not isinstance(domain,Mapping) or set(domain)!={'frame_id','minimum_mm','maximum_mm'}:
        raise ValueError('explicit GEM world domain requires minimum_mm and maximum_mm')
    if not isinstance(assembly,Mapping) or domain['frame_id'] != assembly.get('composition_plan',{}).get('recipe',{}).get('assembly_frame_id'):
        raise ValueError('GEM world domain frame differs from Assembly')
    lo=_vector(domain['minimum_mm'],'domain minimum'); hi=_vector(domain['maximum_mm'],'domain maximum')
    if type(pitch_mm) not in (int,float) or not math.isfinite(pitch_mm) or pitch_mm <= 0:
        raise ValueError('GEM pitch must be positive and finite')
    if boundary not in {'grounded_faces','native_zero_neumann'}: raise ValueError('explicit GEM boundary policy unsupported')
    pitch=float(pitch_mm);counts=[]
    for left,right in zip(lo,hi,strict=True):
        cells=(Fraction(str(right))-Fraction(str(left)))/Fraction(str(pitch))
        if cells.denominator!=1 or cells<2: raise ValueError('GEM domain must have at least three grid nodes and exact pitch alignment')
        counts.append(int(cells)+1)
    rounding: list[dict[str, Any]] = []
    _record_rounding(lo+hi+[-x for x in lo]+[pitch], rounding)
    represented_origin=[-Fraction(format_number(-value)) for value in lo]
    represented_pitch=Fraction(format_number(pitch))
    represented_max=[represented_origin[i]+(counts[i]-1)*represented_pitch for i in range(3)]

    if not members: raise ValueError('GEM requires at least one physical member')
    groups={};witness=[];all_boxes=[];solids={};serialized_solids={};pair_results={};contacts=set()
    for member_index,member in enumerate(members):
        if member['representation_role']!='physical_solid': raise ValueError('unsupported GEM representation: '+str(member['representation_role']))
        key=(member['instance_id'],member['electrode_group_id'])
        if any(not isinstance(x,str) or not x for x in key): raise ValueError('GEM physical member requires an explicit electrode group')
        transform=RigidTransform.from_contract(member['transform']);member_rounding=[]
        pieces=_pieces(member['shape'],transform,member_rounding);rounding.extend(member_rounding)
        for primitive,cuts,lower,upper in pieces:
            if any(lower[i]<=lo[i] or upper[i]>=hi[i] for i in range(3)):
                raise ValueError('GEM physical member is not strictly inside the world domain')
            exact_lower,exact_upper=_serialized_primitive_bounds(primitive,exact=True)
            if any(exact_lower[i]<=represented_origin[i] or exact_upper[i]>=represented_max[i] for i in range(3)):
                raise ValueError('serialized GEM physical member is not strictly inside the world domain')
            represented_lower=[math.nextafter(float(value),-math.inf) for value in exact_lower]
            represented_upper=[math.nextafter(float(value),math.inf) for value in exact_upper]
            for previous,previous_index,pl,pu,previous_rounding,rpl,rpu in all_boxes:
                source_overlap=all(lower[i]<=pu[i] and pl[i]<=upper[i] for i in range(3))
                represented_overlap=all(represented_lower[i]<=rpu[i] and rpl[i]<=represented_upper[i] for i in range(3))
                if previous!=key and (source_overlap or represented_overlap):
                    pair=(previous_index,member_index)
                    if pair not in pair_results:
                        proven_contact = _polygon_contact_proof(members[previous_index],member)
                        from msplatform.components.cad_geometry import placed_physical_solid, classify_solid_pair
                        for index in pair:
                            if index not in solids: solids[index]=placed_physical_solid(members[index])
                        pair_results[pair]=classify_solid_pair(solids[previous_index],solids[member_index],
                                                               proven_contact=proven_contact)
                        if pair_results[pair]=='separated':
                            for index in pair:
                                if index not in serialized_solids:
                                    serialized_solids[index]=_serialized_member_solid(members[index])
                            if classify_solid_pair(serialized_solids[previous_index],serialized_solids[member_index]) != 'separated':
                                raise ValueError('serialized GEM conductor separation is not proven')
                    if pair_results[pair]=='contact': contacts.add(tuple(sorted((previous,key))))
            all_boxes.append((key,member_index,lower,upper,member_rounding,represented_lower,represented_upper));groups.setdefault(key,[]).append((primitive,cuts))
        witness.append(dict(instance_id=key[0],electrode_group_id=key[1],member_id=member['member_id'],source_refs=copy.deepcopy(member['source_refs']),transform=copy.deepcopy(member['transform'])))
    ordered=sorted(groups);mapping=[dict(instance_id=a,electrode_group_id=b,native_id=i) for i,(a,b) in enumerate(ordered,1)]
    f=format_number
    lines=['; Neutral Assembly: physical solids; no solve or Fly.',f"pa_define({','.join(map(str,counts))},planar,none,electrostatic,,{f(pitch)},{f(pitch)},{f(pitch)},surface=fractional)",f"locate({','.join(f(-x) for x in lo)}) {{"]
    for row,key in zip(mapping,ordered,strict=True):
        lines.append('  e('+str(row['native_id'])+') {')
        for primitive,cuts in groups[key]:
            lines.append('    fill {');lines.append('      within { '+primitive+' }')
            lines.extend('      notin { '+cut+' }' for cut in cuts);lines.append('    }')
        lines.append('  }')
    if boundary=='grounded_faces':
        box={a+s:v for a,l,h in zip('xyz',lo,hi,strict=True) for s,v in (('_min',l),('_max',h))}
        for axis in range(3):
            for side in ('min', 'max'):
                lower, upper = list(lo), list(hi)
                lower[axis] = upper[axis] = box['xyz'[axis] + '_' + side]
                _record_rounding([(a+b)/2 for a,b in zip(lower,upper)] + [b-a for a,b in zip(lower,upper)], rounding)
        lines+=['  e(0) {',*grounded_pa_face_lines(box),'  }']
    lines+=['}',''];gem='\n'.join(lines)
    contact_rows=[dict(first=dict(instance_id=a[0],electrode_group_id=a[1]),second=dict(instance_id=b[0],electrode_group_id=b[1])) for a,b in sorted(contacts)]
    result=dict(role='neutral_assembly_gem',gem=gem,gem_sha256=hashlib.sha256(gem.encode('utf8')).hexdigest(),domain=copy.deepcopy(dict(domain)),pitch_mm=pitch,boundary=boundary,dimensions=counts,electrode_mapping=mapping,members=witness,serialization=dict(convention='existing_gem_primitives_12_significant_digits',rounded_values=rounding),scope='geometry_only_not_native_or_field_qualification')
    if contact_rows:result['contact_obligations']=contact_rows
    return result
