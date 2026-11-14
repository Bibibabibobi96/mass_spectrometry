"""Independent OA raw geometry over the existing provider-owned CSG."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from itertools import product
import math

from msplatform.assembly.resolve_assembly import compile_assembly_layout
from msplatform.components.orthogonal_accelerator.geometry_members import iter_geometry_members
from msplatform.components.shape_query import oa_witness_contains as _inside, oa_witness_extent as _extent
from msplatform.components.orthogonal_accelerator.two_zone_geometry import ShieldedRectangularEnclosure
from .bare_three_zone_component import render_bare_three_zone_electrode_body
from .compiler import CompiledSimionGeometry, _content_sha256
from .numerics import normalize_cell_mm_xyz
from .physical_samples import sample_node
from .rf_electrode_mapping import SIMION_MAX_ADJUSTABLE_ELECTRODE_ID
from .two_zone_candidate import ResolvedClosedTwoZoneElectrodes, render_closed_two_zone_electrode_body


def _samples(members, mapping, domain):
    """Require actual represented metal for every member, including ideal sheets."""
    origin, pitch, dimensions = (domain[k] for k in ('instance_origin_mm', 'cell_mm_xyz', 'dimensions'))
    samples = []
    for member in members:
        shape = member['shape']
        bounds = _extent(shape)
        # Split candidates at all actual CSG boundaries, rather than assuming
        # a midpoint lies in a hollow shield or ring.
        cuts = [set(pair) for pair in bounds]
        def collect(part):
            if part['kind'] == 'difference':
                collect(part['base'])
                for tool in part['tools']:
                    collect(tool)
            elif part['kind'] == 'union':
                for child in part['parts']:
                    collect(child)
            else:
                for axis, pair in enumerate(_extent(part)):
                    cuts[axis].update(v for v in pair if bounds[axis][0] <= v <= bounds[axis][1])
        collect(shape)
        candidates = []
        for axis in range(3):
            values = sorted(cuts[axis])
            candidates.append(values if len(values) == 1 else [(a+b)/2 for a,b in zip(values,values[1:])])
        for point in product(*candidates):
            gu, snapped = sample_node(point, [[1,0,0],[0,1,0],[0,0,1]], [0,0,0], origin, pitch, dimensions)
            if _inside(shape, snapped):
                samples.append(dict(label=member['member_id'], electrode_id=mapping[member['electrode_group_id']], gu=gu))
                break
        else:
            witness = _lattice_witness(shape, domain)
            if witness is None:
                raise ValueError('OA member has no actual represented metal/sheet node: '+member['member_id'])
            samples.append(dict(label=member['member_id'], electrode_id=mapping[member['electrode_group_id']], gu=witness))
    # A physical cavity witness must remain vacuum after rasterization. Do not
    # manufacture it by omitting a member from the occupancy check.
    bounds = [_extent(member['shape']) for member in members]
    center = [(min(b[a][0] for b in bounds)+max(b[a][1] for b in bounds))/2 for a in range(3)]
    for dz in (0., pitch['z'], -pitch['z'], 2*pitch['z'], -2*pitch['z']):
        point = [center[0],center[1],center[2]+dz]
        gu, snapped = sample_node(point, [[1,0,0],[0,1,0],[0,0,1]], [0,0,0], origin,pitch,dimensions)
        if not any(_inside(m['shape'],snapped,boundary=True) for m in members):
            samples.append(dict(label='physical_cavity',metal=False,gu=gu))
            return samples
    raise ValueError('OA geometry has no represented cavity witness')


def _lattice_witness(shape, domain):
    """Search actual OA lattice intervals, as for the existing RF axial solids.

    Boxes and z-axis cylinders have constant cross sections between their real
    axial boundaries. At each slab/ideal plane, scan the shorter XY lattice axis
    and derive the other-axis intervals from actual box/quadratic boundaries.
    CSG occupancy still decides every returned node, with no boundary relaxation.
    """
    origin, pitch, dims = (domain[k] for k in ('instance_origin_mm','cell_mm_xyz','dimensions'))
    leaves = []
    def collect(part):
        if part['kind']=='difference':
            collect(part['base'])
            for tool in part['tools']:
                collect(tool)
        elif part['kind']=='union':
            for child in part['parts']:
                collect(child)
        else:
            leaves.append(part)
    collect(shape)
    bounds = _extent(shape)
    def interval(lo,hi,axis):
        return max(0,math.floor((lo-origin[axis])/pitch[axis])+1), min(dims['n'+axis]-1,math.ceil((hi-origin[axis])/pitch[axis])-1)
    def candidates(cuts,axis):
        result = set()
        for point in cuts:
            index = int(math.floor((point-origin[axis])/pitch[axis]+.5))
            actual = origin[axis]+index*pitch[axis]
            if 0<=index<dims['n'+axis] and math.isclose(actual,point,rel_tol=0.,abs_tol=32*math.ulp(max(1.,abs(point)))):
                result.add(index)
        for lo,hi in zip(cuts,cuts[1:]):
            first,last = interval(lo,hi,axis)
            if first<=last:
                near = int(math.floor(((lo+hi)/2-origin[axis])/pitch[axis]+.5))
                result.update((first,last,min(last,max(first,near))))
        return sorted(result)
    zcuts = sorted({v for leaf in leaves for v in _extent(leaf)[2]
                    if bounds[2][0]<=v<=bounds[2][1]} | set(bounds[2]))
    ranges = [interval(*bounds[k],'xy'[k]) for k in range(2)]
    primary = min(range(2),key=lambda k:ranges[k][1]-ranges[k][0])
    secondary = 1-primary
    for iz in candidates(zcuts,'z'):
        z = origin['z']+iz*pitch['z']
        for i in range(ranges[primary][0],ranges[primary][1]+1):
            u = origin['xy'[primary]]+i*pitch['xy'[primary]]
            cuts = set(bounds[secondary])
            for leaf in leaves:
                extent = _extent(leaf)
                if not extent[2][0]<=z<=extent[2][1]:
                    continue
                if leaf['kind']=='box':
                    if extent[primary][0]<=u<=extent[primary][1]:
                        cuts.update(extent[secondary])
                else:
                    center = leaf['center_mm']
                    discriminant = leaf['radius_mm']**2-(u-center[primary])**2
                    if discriminant>=0:
                        half = math.sqrt(discriminant)
                        cuts.update((center[secondary]-half,center[secondary]+half))
            cuts = sorted(v for v in cuts if bounds[secondary][0]<=v<=bounds[secondary][1])
            for j in candidates(cuts,'xy'[secondary]):
                indices = [i,j,iz] if primary==0 else [j,i,iz]
                point = [origin[a]+indices[k]*pitch[a] for k,a in enumerate('xyz')]
                if _inside(shape,point):
                    return indices
    return None


def render_accelerator_body(
    design: dict, variant_id: str, mapping: Mapping[str, int], cell: Mapping[str, float]
) -> list[str]:
    """Render every canonical OA member using explicitly selected native IDs."""
    if variant_id == 'two_zone':
        ids = {15:mapping['grounded_shield'],22:mapping['repeller'],23:mapping['intermediate_grid_1'],24:mapping['exit_grid'],
               **{int(r['id']):mapping[f'ring_{i:04d}'] for i,r in enumerate(design['rings'],1)}}
        projection = ResolvedClosedTwoZoneElectrodes(ShieldedRectangularEnclosure(**design['enclosure']),
            design['local_exit_z_mm'],design['local_repeller_z_mm'],design['repeller_thickness_mm'],
            design['aperture_half_x_mm'],design['aperture_half_y_mm'],0.,tuple(design['grid_supports']),tuple(design['rings']),ids,(None if design['side_entry'] is None else dict(design['side_entry'], boolean_cut_padding_y_mm=cell['y'], boolean_transverse_expansion_mm=0.)))
        body = render_closed_two_zone_electrode_body(projection)
    else:
        ids = {1:mapping['grounded_shield'],2:mapping['repeller'],3:mapping['intermediate_grid_1'],
               4:mapping['intermediate_grid_2'],5:mapping['exit_grid'],
               **{eid:mapping[f'ring_{i:04d}'] for i,eid in enumerate(design['electrodes']['accelerator_ring_ids'],1)}}
        body = render_bare_three_zone_electrode_body(design,cell_mm_xyz=cell,local_electrode_ids=ids)
    return body


def compile_independent_accelerators(assembly, *, numerics):
    """Compile selected OA instances with explicit grids/bounds and no source/TOF."""
    plan = copy.deepcopy(assembly['composition_plan'])
    if plan != compile_assembly_layout(plan['recipe'],plan['components'],local_scope=plan.get('local_scope')):
        raise ValueError('independent OA plan differs from its canonical mechanical parent')
    selected = plan['scope']['instance_ids']
    components = assembly['components_resolved']
    if not selected or set(components) != set(selected) or any(
            plan['components'][name]['project_id'] != 'orthogonal_accelerator' for name in selected):
        raise ValueError('independent OA requires exactly the selected OA component snapshots')
    if not isinstance(numerics,Mapping) or 'component_domains' not in numerics or set(numerics)-{'component_domains','electrode_group_native_ids'}:
        raise ValueError('independent OA numerics require component_domains and optional electrode_group_native_ids')
    if set(numerics['component_domains']) != set(selected):
        raise ValueError('OA domains must cover exactly selected instances')
    requested = numerics.get('electrode_group_native_ids',{})
    if not isinstance(requested,Mapping) or set(requested)-set(selected):
        raise ValueError('OA native mappings name an unselected instance')
    gems, domains, bindings, identities, witnesses = {},{},{},{},{}
    for name in selected:
        design = components[name]
        members = iter_geometry_members(design)
        groups = list(dict.fromkeys(m['electrode_group_id'] for m in members))
        mapping = requested.get(name,dict(zip(groups,range(1,len(groups)+1),strict=True)))
        if (not isinstance(mapping,Mapping) or set(mapping)!=set(groups) or
                any(type(v) is not int or not 1<=v<=SIMION_MAX_ADJUSTABLE_ELECTRODE_ID for v in mapping.values()) or
                len(set(mapping.values()))!=len(mapping)):
            raise ValueError('OA native IDs must uniquely cover every scientific group')
        domain = numerics['component_domains'][name]
        if not isinstance(domain,Mapping) or set(domain)!={'cell_mm_xyz','pa_bounds_mm'}:
            raise ValueError('OA domain requires explicit cell_mm_xyz and pa_bounds_mm')
        cell = normalize_cell_mm_xyz(domain['cell_mm_xyz'])
        bounds = domain['pa_bounds_mm']
        if (not isinstance(bounds,Mapping) or set(bounds)!={a+s for a in 'xyz' for s in ('_min','_max')} or
                any(type(v) not in (int,float) or not math.isfinite(v) for v in bounds.values())):
            raise ValueError('OA PA bounds require six finite coordinates')
        dimensions = {}
        for a in 'xyz':
            n = (bounds[a+'_max']-bounds[a+'_min'])/cell[a]
            if n<=0 or not math.isclose(n,round(n),abs_tol=1e-9,rel_tol=0):
                raise ValueError('OA bounds must span positive whole grid intervals')
            dimensions['n'+a] = round(n)+1
        for member in members:
            for axis,(lo,hi) in zip('xyz',_extent(member['shape']),strict=True):
                if lo<bounds[axis+'_min'] or hi>bounds[axis+'_max']:
                    raise ValueError('OA PA bounds do not contain actual mechanics')
        origin = {a:bounds[a+'_min'] for a in 'xyz'}
        domains[name] = dict(dimensions=dimensions,cell_mm_xyz=cell,instance_origin_mm=origin,bounds_mm=dict(bounds))
        body = render_accelerator_body(design, plan['components'][name]['variant_id'], mapping, cell)
        header = f"pa_define({dimensions['nx']},{dimensions['ny']},{dimensions['nz']},planar,none,electrostatic,,{cell['x']:.12g},{cell['y']:.12g},{cell['z']:.12g},surface=fractional)"
        gems[name] = '\n'.join([header,f"locate({-origin['x']:.12g},{-origin['y']:.12g},{-origin['z']:.12g}) {{",*body,'}',''])
        witnesses[name] = _samples(members,mapping,domains[name])
        opening = design.get('side_entry') if plan['components'][name]['variant_id']=='two_zone' else design['port']
        if opening is not None:
            point = list(opening['center_mm'])
            gu, snapped = sample_node(point, [[1,0,0],[0,1,0],[0,0,1]], [0,0,0], origin,cell,dimensions)
            if any(_inside(member['shape'],snapped,boundary=True) for member in members):
                raise ValueError('OA side aperture has no represented vacuum node')
            witnesses[name].append(dict(label='physical_side_opening',metal=False,gu=gu))
        bindings[name] = dict(mapping)
        identities[name] = dict(resolved_content_sha256=_content_sha256(design),component_interface_sha256=_content_sha256(plan['components'][name]))
    frontend = dict(role='simion_independent_oa_geometry',composition_plan=plan,numerical_domains=domains,
                    electrode_bindings=bindings,raw_physical_samples=witnesses)
    return CompiledSimionGeometry(gems,frontend,(),identities,copy.deepcopy(dict(components)))
