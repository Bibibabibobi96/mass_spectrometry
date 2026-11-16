"""Compile explicit neutral physical members into one collision-only world PA."""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from msplatform.components.geometry_members import assembly_geometry_members
from msplatform.components.shape_query import query_members
from .assembly_geometry import _render_assembly_members_gem
from .compiler import CompiledSimionGeometry


def compile_generic_collision_geometry(assembly: Any, *, numerics: Mapping[str, Any]) -> CompiledSimionGeometry:
    """Compile one source-validated world grid; no native operation or field solve."""
    required = {'representation', 'domain', 'pitch_mm', 'boundary', 'metal_witnesses', 'void_witnesses'}
    if not isinstance(numerics, Mapping) or set(numerics) != required or numerics['representation'] != 'neutral_world_collision':
        raise ValueError('generic collision numerics require explicit world domain, pitch, boundary and vacuum witness')
    if numerics['boundary'] != 'native_zero_neumann':
        raise ValueError('generic collision electrode scan currently supports native_zero_neumann only')
    snapshot = dict(composition_plan=copy.deepcopy(assembly.composition_plan),
                    components_resolved=copy.deepcopy(assembly.components_resolved),
                    components_source=copy.deepcopy(assembly.components_source))
    members = assembly_geometry_members(snapshot)
    return _compile_generic_from_members(snapshot, numerics=numerics, members=members)


def _compile_generic_from_members(snapshot, *, numerics, members):
    """Rebuild an explicit projection; caller must establish member authority."""
    from msplatform.assembly.resolve_assembly import compile_assembly_layout
    required = {'representation', 'domain', 'pitch_mm', 'boundary', 'metal_witnesses', 'void_witnesses'}
    if (not isinstance(numerics, Mapping) or set(numerics) != required
            or numerics['representation'] != 'neutral_world_collision'
            or numerics['boundary'] != 'native_zero_neumann'):
        raise ValueError('neutral member projection requires explicit supported world numerics')
    plan = snapshot['composition_plan']
    if compile_assembly_layout(plan['recipe'], plan['components'], local_scope=plan.get('local_scope')) != plan:
        raise ValueError('neutral source layout differs from its canonical plan')
    rendered = _render_assembly_members_gem(snapshot, members, domain=numerics['domain'],
                                            pitch_mm=numerics['pitch_mm'], boundary=numerics['boundary'])
    domain = rendered['domain']; pitch = rendered['pitch_mm']
    ids = {(row['instance_id'], row['electrode_group_id']): row['native_id'] for row in rendered['electrode_mapping']}
    def classify(gu):
        if not isinstance(gu, list) or len(gu) != 3 or any(type(x) is not int or x < 0 or x >= rendered['dimensions'][i] for i, x in enumerate(gu)):
            raise ValueError('witness must be an in-domain integer grid coordinate')
        position = [domain['minimum_mm'][i] + gu[i] * pitch for i in range(3)]
        return query_members(members, position, frame_id=domain['frame_id'])
    metal = numerics['metal_witnesses']; voids = numerics['void_witnesses']
    if not isinstance(metal, list) or not metal or not isinstance(voids, list) or not voids:
        raise ValueError('explicit canonical metal and void witness lists are required')
    rows = []; covered = set()
    for witness in metal:
        if not isinstance(witness, Mapping) or set(witness) != {'instance_id','electrode_group_id','gu'}:
            raise ValueError('metal witness requires explicit instance, group and grid coordinate')
        key = (witness['instance_id'],witness['electrode_group_id'])
        if key not in ids or classify(witness['gu']) != {'status':'interior','group':key}:
            raise ValueError('metal witness is not proven inside its canonical electrode group')
        covered.add(key)
        rows.append(dict(gu=list(witness['gu']),metal=True,electrode_id=ids[key],label='canonical_metal_'+str(ids[key])))
    if covered != set(ids):
        raise ValueError('metal witnesses must cover every canonical electrode group')
    for gu in voids:
        if classify(gu)['status'] != 'outside':
            raise ValueError('void witness is not proven outside all physical members')
        rows.append(dict(gu=list(gu),metal=False,label='canonical_void'))
    geometry = dict(role='simion_neutral_world_collision_geometry', source_snapshot=snapshot,
        domain=domain, pitch_mm=pitch, dimensions=rendered['dimensions'], boundary=rendered['boundary'],
        electrode_mapping=rendered['electrode_mapping'], members=rendered['members'],
        serialization=rendered['serialization'], metal_witnesses=copy.deepcopy(metal),
        void_witnesses=copy.deepcopy(voids), physical_samples=rows,
        electrode_witness_ids=[row['native_id'] for row in rendered['electrode_mapping']])
    if rendered.get('contact_obligations'):
        geometry['contact_obligations'] = rendered['contact_obligations']
    identities = {}
    for name in snapshot['composition_plan']['scope']['instance_ids']:
        value = {'source': snapshot['components_source'][name], 'resolved': snapshot['components_resolved'][name],
                 'interface': snapshot['composition_plan']['components'][name]}
        identities[name] = {'content_sha256': hashlib.sha256(json.dumps(value, sort_keys=True,
            separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()}
    return CompiledSimionGeometry(frontend_gems={'world': rendered['gem']}, frontend_geometry=geometry,
        downstream_specs=(), provider_content_identities=identities, components_resolved=snapshot['components_resolved'])


def _neutral_numerics(geometry):
    return dict(representation='neutral_world_collision', domain=geometry['domain'],
                pitch_mm=geometry['pitch_mm'], boundary=geometry['boundary'],
                metal_witnesses=geometry['metal_witnesses'], void_witnesses=geometry['void_witnesses'])


def seal_neutral_geometry_for_publication(compiled):
    """Revalidate caller input, then bind the actual complete provider member projection."""
    from dataclasses import replace
    from types import SimpleNamespace
    geometry = compiled.frontend_geometry
    if 'producer_validated_members' in geometry:
        raise ValueError('caller-supplied neutral producer projection is forbidden')
    snapshot = geometry['source_snapshot']
    rebuilt = compile_generic_collision_geometry(SimpleNamespace(**copy.deepcopy(snapshot)),
                                                  numerics=_neutral_numerics(geometry))
    if rebuilt != compiled:
        raise ValueError('neutral geometry differs from its canonical source before build')
    members = list(assembly_geometry_members(copy.deepcopy(snapshot)))
    if _compile_generic_from_members(copy.deepcopy(snapshot), numerics=_neutral_numerics(geometry),
                                     members=copy.deepcopy(members)) != compiled:
        raise ValueError('neutral producer members differ from its validated compiled geometry')
    return replace(compiled, frontend_geometry=dict(copy.deepcopy(geometry),
        producer_validated_members=dict(schema_version=1, members=members)))


def validate_published_neutral_geometry(compiled):
    """Verify a producer-sealed projection without loading provider callbacks."""
    from dataclasses import replace
    geometry = compiled.frontend_geometry
    proof = geometry.get('producer_validated_members')
    if (not isinstance(proof, Mapping) or set(proof) != {'schema_version', 'members'}
            or type(proof['schema_version']) is not int or proof['schema_version'] != 1
            or not isinstance(proof['members'], list) or not proof['members']):
        raise ValueError('published neutral member projection is missing or invalid')
    plain = copy.deepcopy(geometry)
    plain.pop('producer_validated_members')
    rebuilt = _compile_generic_from_members(copy.deepcopy(plain['source_snapshot']),
        numerics=_neutral_numerics(plain), members=copy.deepcopy(proof['members']))
    if rebuilt != replace(compiled, frontend_geometry=plain):
        raise ValueError('published neutral member projection differs from compiled geometry')


def compile_generic_multi_domain_geometry(assembly: Any, *, numerics: Mapping[str, Any]) -> CompiledSimionGeometry:
    """Compile complete disjoint instance domains."""
    if not isinstance(numerics, Mapping) or set(numerics) != {'representation', 'domains'} or numerics['representation'] != 'neutral_multi_domain_collision':
        raise ValueError('explicit multi-domain collision declaration required')
    entries = numerics['domains']
    if not isinstance(entries, list) or not entries:
        raise ValueError('at least one multi-domain collision declaration required')
    snapshot = dict(composition_plan=copy.deepcopy(assembly.composition_plan),
                    components_resolved=copy.deepcopy(assembly.components_resolved),
                    components_source=copy.deepcopy(assembly.components_source))
    members = assembly_geometry_members(snapshot)
    return _compile_multi_from_members(snapshot, numerics=numerics, members=members)


def _compile_multi_from_members(snapshot, *, numerics, members):
    from fractions import Fraction
    from itertools import combinations
    from .assembly_geometry import format_number
    if not isinstance(numerics, Mapping) or set(numerics) != {'representation', 'domains'} or numerics['representation'] != 'neutral_multi_domain_collision':
        raise ValueError('explicit multi-domain collision declaration required')
    entries = numerics['domains']
    if not isinstance(entries, list) or not entries:
        raise ValueError('at least one multi-domain collision declaration required')
    selected = snapshot['composition_plan']['scope']['instance_ids']
    for member in members:
        if member['representation_role'] != 'physical_solid':
            raise ValueError('unsupported GEM representation: '+str(member['representation_role']))
    required = {'domain_id', 'owner_instance_id', 'member_ids', 'domain', 'pitch_mm', 'boundary', 'metal_witnesses', 'void_witnesses'}
    if any(not isinstance(row, Mapping) or set(row) != required for row in entries):
        raise ValueError('each collision domain requires explicit complete membership, grid and witnesses')
    names = [row['domain_id'] for row in entries]
    if any(not isinstance(name, str) or not name for name in names) or len(set(names)) != len(names):
        raise ValueError('collision domain IDs must be nonempty and unique')
    canonical = [(row['instance_id'],row['member_id']) for row in members]
    if len(canonical)!=len(set(canonical)) or {instance for instance,_ in canonical}!=set(selected):
        raise ValueError('selected instances require unique canonical physical members')
    claimed=set();compiled = {}; projections = {}; bounds = {}
    for entry in sorted(entries, key=lambda row: row['domain_id']):
        name=entry['domain_id']; owner=entry['owner_instance_id']; declared=entry['member_ids']
        if owner not in selected or not isinstance(declared,list) or not declared or any(not isinstance(x,str) or not x for x in declared) or len(set(declared))!=len(declared):
            raise ValueError('collision domain requires a selected owner and unique nonempty member IDs')
        identities={(owner,member_id) for member_id in declared}
        if claimed & identities or not identities <= set(canonical):
            raise ValueError('collision members must be canonical and assigned exactly once')
        claimed.update(identities)
        owned=[row for row in members if (row['instance_id'],row['member_id']) in identities]
        member_ids=sorted(declared);groups={row['electrode_group_id'] for row in owned}
        if not isinstance(entry['metal_witnesses'], list) or any(not isinstance(row, Mapping) or row.get('instance_id') != owner for row in entry['metal_witnesses']):
            raise ValueError('domain metal witnesses must belong to its instance')
        declaration = {k: copy.deepcopy(entry[k]) for k in ('domain','pitch_mm','boundary','metal_witnesses','void_witnesses')}
        declaration['representation'] = 'neutral_world_collision'
        result = _compile_generic_from_members(snapshot, numerics=declaration, members=owned)
        geo = result.frontend_geometry; domain=geo['domain']; pitch=geo['pitch_mm']; counts=geo['dimensions']
        lo=domain['minimum_mm']; hi=domain['maximum_mm']
        rep_lo=[-Fraction(format_number(-x)) for x in lo]; rep_pitch=Fraction(format_number(pitch))
        rep_hi=[rep_lo[i]+(counts[i]-1)*rep_pitch for i in range(3)]
        bounds[name]=(lo,hi,rep_lo,rep_hi)
        compiled[name]=result.frontend_gems['world']
        projections[name]=dict(domain_id=name, owner_instance_id=owner, member_ids=member_ids, electrode_groups=sorted(groups), **copy.deepcopy(geo))
    if claimed != set(canonical):
        raise ValueError('collision domains must cover every canonical physical member exactly once')
    for (left, a), (right, b) in combinations(bounds.items(), 2):
        source_separate=any(a[1][i] < b[0][i] or b[1][i] < a[0][i] for i in range(3))
        represented_separate=any(a[3][i] < b[2][i] or b[3][i] < a[2][i] for i in range(3))
        if not source_separate or not represented_separate:
            raise ValueError('overlapping multi-domain collision boxes require unsupported priority proof: '+left+', '+right)
    # Every member belongs to its fully contained instance domain; disjoint boxes exclude foreign metal.
    first = result
    return CompiledSimionGeometry(frontend_gems=compiled,
        frontend_geometry=dict(role='simion_neutral_multi_domain_collision_geometry', schema_version=1,
                               source_snapshot=snapshot, domains=projections,
                               domain_order=sorted(names), priority_scope='disjoint_domains_only'),
        downstream_specs=(), provider_content_identities=first.provider_content_identities,
        components_resolved=copy.deepcopy(snapshot['components_resolved']))


def _multi_numerics(geometry):
    keys=('domain_id','owner_instance_id','member_ids','domain','pitch_mm','boundary','metal_witnesses','void_witnesses')
    return dict(representation='neutral_multi_domain_collision',
        domains=[{key:copy.deepcopy(geometry['domains'][name][key]) for key in keys} for name in geometry['domain_order']])


def seal_multi_domain_geometry_for_publication(compiled):
    """Revalidate all provider members before binding the published projection."""
    from dataclasses import replace
    from types import SimpleNamespace
    geometry=compiled.frontend_geometry
    if 'producer_validated_members' in geometry:
        raise ValueError('caller-supplied neutral producer projection is forbidden')
    snapshot=geometry['source_snapshot']; numerics=_multi_numerics(geometry)
    rebuilt=compile_generic_multi_domain_geometry(SimpleNamespace(**copy.deepcopy(snapshot)),numerics=numerics)
    members=list(assembly_geometry_members(copy.deepcopy(snapshot)))
    if rebuilt!=compiled or _compile_multi_from_members(copy.deepcopy(snapshot),numerics=numerics,members=copy.deepcopy(members))!=compiled:
        raise ValueError('multi-domain geometry differs from canonical source')
    return replace(compiled,frontend_geometry=dict(copy.deepcopy(geometry),producer_validated_members=dict(schema_version=1,members=members)))


def validate_published_multi_domain_geometry(compiled):
    """Rebuild the producer-bound projection without importing providers."""
    from dataclasses import replace
    geometry=compiled.frontend_geometry; proof=geometry.get('producer_validated_members')
    if (not isinstance(proof, Mapping) or set(proof)!={'schema_version','members'} or type(proof['schema_version']) is not int
            or proof['schema_version']!=1 or not isinstance(proof['members'],list) or not proof['members']):
        raise ValueError('published multi-domain member projection is missing or invalid')
    plain=copy.deepcopy(geometry);plain.pop('producer_validated_members')
    rebuilt=_compile_multi_from_members(copy.deepcopy(plain['source_snapshot']),numerics=_multi_numerics(plain),members=copy.deepcopy(proof['members']))
    if rebuilt!=replace(compiled,frontend_geometry=plain):
        raise ValueError('published multi-domain projection differs from compiled geometry')


def multi_domain_source_paths(compiled):
    """Resolve the canonical projection and registered-provider source closure."""
    from msplatform.execution.inputs import resolve_python_module_sources
    from msplatform.components.registry import project_descriptor
    from msplatform.components import cad_geometry, geometry_members, shape_query, registry
    from msplatform.assembly import resolve_assembly
    from . import generic_geometry, assembly_geometry, mr_geometry
    modules=(cad_geometry,geometry_members,shape_query,registry,resolve_assembly,generic_geometry,assembly_geometry,mr_geometry)
    paths={module.__name__:Path(module.__file__).resolve(strict=True) for module in modules}
    plan=compiled.frontend_geometry['source_snapshot']['composition_plan']
    for name in plan['scope']['instance_ids']:
        descriptor=project_descriptor(plan['components'][name]['project_id'])
        paths.update(resolve_python_module_sources(descriptor.source_closure))
    return paths
