"""Compile explicit neutral physical members into one collision-only world PA."""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from msplatform.components.geometry_members import assembly_geometry_members
from msplatform.components.shape_query import query_members
from .assembly_geometry import render_assembly_gem
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
    rendered = render_assembly_gem(snapshot, domain=numerics['domain'], pitch_mm=numerics['pitch_mm'], boundary=numerics['boundary'])
    members = assembly_geometry_members(snapshot)
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
    identities = {}
    for name in snapshot['composition_plan']['scope']['instance_ids']:
        value = {'source': snapshot['components_source'][name], 'resolved': snapshot['components_resolved'][name],
                 'interface': snapshot['composition_plan']['components'][name]}
        identities[name] = {'content_sha256': hashlib.sha256(json.dumps(value, sort_keys=True,
            separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()}
    return CompiledSimionGeometry(frontend_gems={'world': rendered['gem']}, frontend_geometry=geometry,
        downstream_specs=(), provider_content_identities=identities, components_resolved=snapshot['components_resolved'])
