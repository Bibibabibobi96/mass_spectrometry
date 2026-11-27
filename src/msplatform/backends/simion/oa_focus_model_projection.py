"""Canonical OA focus model projection and exact revalidation from frozen inputs."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any, Mapping
from msplatform import assembly, components
from msplatform.backends.simion.operations import compile_geometry
from msplatform.backends.simion.model import RF_PHYSICS, compile_prepared_model
from msplatform.backends.simion.oa_focus_plan import derive_campaign
from msplatform.io.file_identity import canonical_json_sha256


def build_focus_model(campaign: Mapping[str, Any], *, component_contract: Mapping[str, Any],
                      campaign_record: Mapping[str, Any], contract_record: Mapping[str, Any],
                      geometry_profile: Mapping[str, Any], mesh_mm_per_gu: list[float],
                      clock: Mapping[str, Any]) -> dict[str, Any]:
    """Build the only projection from caller-held exact frozen source records."""
    campaign=dict(campaign);record=dict(campaign_record);contract_record=dict(contract_record)
    if component_contract['geometry_profiles'].get(campaign['geometry_profile_id'])!=dict(geometry_profile):
        raise ValueError('focus geometry profile differs from the selected component authority')
    plan=derive_campaign(campaign,campaign_path=Path(record['path']),geometry_profile=geometry_profile,mesh_mm_per_gu=mesh_mm_per_gu)
    domain=plan['numerical_domain'];exit_local=domain['local_exit_z_mm']
    offset=campaign['operating_point']['focus_plane_offset_from_exit_mm']
    if not math.isclose(domain['focus_plane_local_z_mm']-exit_local,offset,rel_tol=0.,abs_tol=1e-9):
        raise ValueError('focus author plane differs from its compiled plan')
    profile_id=campaign['geometry_profile_id']
    request=dict(provider_id='orthogonal_accelerator',geometry_profile_id=profile_id,
                 design=dict(requirements=plan['requirements'],geometry_profile=dict(geometry_profile)))
    part=components.resolve_component(request)
    if part.resolved_design['side_entry'] is not None:
        raise ValueError('closed focus geometry must not acquire a side entry')
    frame='orthogonal_accelerator_exit_origin_v1'
    recipe=dict(schema_version=1,role='assembly_recipe',integration_id='instrument_assembly',recipe_id='oa_focus',
        assembly_frame_id=frame,position_tolerance_mm=1e-9,angular_tolerance_rad=1e-12,
        instances=[dict(instance_id='oa',project_id='orthogonal_accelerator',transform=dict(schema_version=1,
            role='rigid_transform',from_frame_id=frame,to_frame_id=frame,
            rotation=[[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]],
            translation_mm=[0.,float(campaign['operating_point']['instance_center_y_mm']),0.]))],connections=[])
    instrument=assembly.assemble(recipe,{'oa':part})
    grid=dict(schema_version=1,role='oa_focus_native_grid_authority',surface='none',
        mirror_axes=list(domain['mirror_axes']),physical_span_mm=list(domain['span_mm']),
        stored_span_mm=list(domain['stored_span_mm']),mesh_mm_per_gu=list(domain['mesh_mm_per_gu']),
        dimensions=[round(length/step)+1 for length,step in zip(domain['stored_span_mm'],domain['mesh_mm_per_gu'],strict=True)],
        component_frame_origin_mm=[domain['iob_origin_mm'][0],domain['iob_origin_mm'][1],domain['iob_origin_mm'][2]-exit_local],
        gem_sha256=hashlib.sha256(plan['gem'].encode('utf8')).hexdigest().upper())
    origin=grid['component_frame_origin_mm'];span=grid['stored_span_mm']
    grid['component_domain']=dict(cell_mm_xyz=dict(zip('xyz',grid['mesh_mm_per_gu'],strict=True)),
        pa_bounds_mm={axis+suffix:origin[index]+(span[index] if suffix=='_max' else 0.)
            for index,axis in enumerate('xyz') for suffix in ('_min','_max')},symmetry='mirror_x',surface='none')
    numerics=dict(component_domains={'oa':grid['component_domain']})
    compiled=compile_geometry(instrument,numerics=numerics)
    groups=compiled.frontend_geometry['electrode_bindings']['oa']
    ordered=['grounded_shield','repeller','intermediate_grid_1','exit_grid',
             *(f'ring_{index:04d}' for index in range(1,plan['layout']['ring_count']+1))]
    voltages=campaign['operating_point']['electrode_voltages_v']
    if set(groups)!=set(ordered) or len(voltages)!=len(ordered):
        raise ValueError('focus electrode roles or voltage count differ')
    drive=dict(groups={'oa':{name:dict(kind='static',voltage_v=voltage)
                             for name,voltage in zip(ordered,voltages,strict=True)}},clock=dict(clock))
    model=compile_prepared_model(compiled,instrument.components_resolved,drive=drive,physics=RF_PHYSICS)
    observations=dict(schema_version=1,role='oa_focus_plane_authority',frame_id=frame,component_id='oa',
        exit_z_mm=0.,focus_z_mm=float(offset),direction='negative_z',campaign=record,
        campaign_content_sha256=canonical_json_sha256(campaign),
        component_contract=contract_record,
        geometry_profile_sha256=canonical_json_sha256(dict(geometry_profile)),
        geometry_profile=dict(geometry_profile),mesh_mm_per_gu=list(mesh_mm_per_gu),clock=dict(clock),
        focus_native_grid=grid,
        model_sha256=canonical_json_sha256(model.document))
    return dict(model=model,focus_plan=plan,observations=observations,campaign=record,
                component_requests={'oa':request},recipe=recipe,geometry_numerics=numerics,
                drive=drive,physics=dict(RF_PHYSICS),release_spec=campaign['release_spec'],
                field_identity='mirrored_surface_none_focus_model_not_yet_verified_controller')


def validate_focus_authority(authority: Mapping[str, Any], *, campaign: Mapping[str, Any],
                             component_contract: Mapping[str, Any], model_document: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute the exact projection; caller holds and verifies both source records.

    A digest or a caller-authored authority alone is never authentication.
    """
    if not isinstance(authority,Mapping):
        raise ValueError('explicit focus authority is required')
    try:
        projected=build_focus_model(campaign,component_contract=component_contract,
            campaign_record=authority['campaign'],contract_record=authority['component_contract'],
            geometry_profile=authority['geometry_profile'],mesh_mm_per_gu=authority['mesh_mm_per_gu'],clock=authority['clock'])
    except (KeyError,TypeError) as error:
        raise ValueError('focus authority lacks its original projection inputs') from error
    if projected['observations']!=dict(authority) or projected['model'].document!=dict(model_document):
        raise ValueError('focus authority or actual compiled model differs from frozen author')
    return projected['observations']


def focus_model_facts(authority: Mapping[str, Any], *, campaign: Mapping[str, Any],
                      component_contract: Mapping[str, Any], model_document: Mapping[str, Any]) -> dict[str, Any]:
    """Project authenticated model/author facts without a PA receipt or new birth.

    The caller must hold the original author and component-contract file guards.
    The returned release spec is the original author, never a terminal state.
    """
    import copy
    validate_focus_authority(authority,campaign=campaign,component_contract=component_contract,
                             model_document=model_document)
    projected=build_focus_model(campaign,component_contract=component_contract,
        campaign_record=authority['campaign'],contract_record=authority['component_contract'],
        geometry_profile=authority['geometry_profile'],mesh_mm_per_gu=authority['mesh_mm_per_gu'],
        clock=authority['clock'])
    profile=authority['geometry_profile'];point=campaign['operating_point'];release=campaign['release_spec']
    gap1=float(profile['gap_1_mm']);gap2=float(profile['gap_2_mm'])
    release_from_repeller=gap1+gap2-float(release['geometry']['center_mm'][2])
    groups=model_document['drive']['groups']['oa']
    names=['repeller','intermediate_grid_1','exit_grid',
           *(f'ring_{index:04d}' for index in range(1,int(profile['ring_count'])+1))]
    if any(name not in groups or groups[name].get('kind')!='static' for name in names):
        raise ValueError('focus model lacks its explicit static electrode drive')
    voltages=[float(groups[name]['voltage_v']) for name in names]
    return dict(schema_version=1,role='oa_focus_authenticated_model_facts',
        campaign_sha256=authority['campaign']['sha256'],model_sha256=authority['model_sha256'],
        geometry=dict(acceleration_direction='-z',gap_1_mm=gap1,gap_2_mm=gap2,
            repeller_to_exit_mm=gap1+gap2,release_position_in_gap_1_mm=release_from_repeller,
            ring_count=int(profile['ring_count']),aperture_height_y_mm=float(profile['aperture_height_y_mm']),
            geometry_profile_id=campaign['geometry_profile_id']),
        assembly_recipe=copy.deepcopy(projected['recipe']),drive=copy.deepcopy(model_document['drive']),
        clock=copy.deepcopy(authority['clock']),release_spec=copy.deepcopy(release),
        endpoint_voltages_v=voltages[:3],ring_voltages_v=voltages[3:],
        instance_center_y_mm=float(point['instance_center_y_mm']))
