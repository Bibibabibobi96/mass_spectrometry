"""Installed public generic geometry compilation with an explicit test provider."""
import copy
import importlib.util
import sys
import sysconfig
from pathlib import Path


def run(root):
    from msplatform import assembly, components
    from msplatform.backends import simion
    from msplatform.backends.simion import generic_geometry
    import msplatform.capabilities as capability_module
    import msplatform.components.geometry_members as geometry_members_module
    from msplatform.capabilities import capabilities
    from msplatform.components.geometry_members import assembly_geometry_members
    purelib=Path(sysconfig.get_paths()['purelib']).resolve()
    for module in (assembly,components,simion,generic_geometry,capability_module,geometry_members_module):
        assert Path(module.__file__).resolve().is_relative_to(purelib),module.__file__
    provider=Path(root)/'installed_registered_component.py'
    spec=importlib.util.spec_from_file_location('installed_registered_component',provider)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    module.ensure_registered()
    a=components.resolve_component({'provider_id':'toy_registered','design':{'width_mm':2}})
    b=components.resolve_component({'provider_id':'toy_registered','design':{'width_mm':3}})
    def pose(x):return dict(schema_version=1,role='rigid_transform',from_frame_id='toy_local',to_frame_id='world',rotation=[[1,0,0],[0,1,0],[0,0,1]],translation_mm=[x,0,0])
    recipe=dict(schema_version=1,role='assembly_recipe',integration_id='unlisted_fixture',recipe_id='two_instances',assembly_frame_id='world',position_tolerance_mm=1e-6,angular_tolerance_rad=1e-6,instances=[dict(instance_id='second',project_id='toy_registered',transform=pose(10)),dict(instance_id='first',project_id='toy_registered',transform=pose(0))],connections=[])
    product=assembly.assemble(recipe,{'first':a,'second':b})
    numerics=dict(representation='neutral_world_collision',domain=dict(frame_id='world',minimum_mm=[-20,-20,-20],maximum_mm=[20,20,20]),pitch_mm=1,boundary='native_zero_neumann',metal_witnesses=[dict(instance_id='first',electrode_group_id='body',gu=[20,20,20]),dict(instance_id='second',electrode_group_id='body',gu=[30,20,20])],void_witnesses=[[0,0,0]])
    compiled=simion.compile_geometry(product,numerics=numerics)
    assert len(compiled.frontend_geometry['physical_samples'])==3
    renamed=copy.deepcopy(recipe);renamed['instances']=[dict(instance_id='alpha',project_id='toy_registered',transform=pose(0)),dict(instance_id='beta',project_id='toy_registered',transform=pose(10))]
    second=assembly.assemble(renamed,{'alpha':a,'beta':b})
    renamed_numerics=copy.deepcopy(numerics);renamed_numerics['metal_witnesses'][0]['instance_id']='alpha';renamed_numerics['metal_witnesses'][1]['instance_id']='beta'
    renamed_compiled=simion.compile_geometry(second,numerics=renamed_numerics)
    assert len(renamed_compiled.frontend_geometry['physical_samples'])==3
    def geometry(assembly_value):
        snapshot=dict(composition_plan=assembly_value.composition_plan,components_resolved=assembly_value.components_resolved,components_source=assembly_value.components_source)
        return sorted((tuple(row['shape']['parts'][0]['size_mm']),tuple(row['transform']['translation_mm'])) for row in assembly_geometry_members(snapshot))
    assert geometry(product)==geometry(second)
    bad=copy.deepcopy(numerics);bad['boundary']='grounded_faces'
    capability=capabilities(dict(schema_version=1,operation='compile_geometry',arguments=dict(assembly=product,numerics=bad)))
    assert capability['contract_status']=='rejected',capability
    # Exercise the installed static scientific and tracking planners; no solver or Fly.
    from msplatform import examples, ion_release
    from msplatform.backends.simion import model, field_execution, tracking_execution, rf_tracking_program
    from msplatform.backends.simion.resources import native_resource_path
    from msplatform.io.manifest_records import file_record
    from importlib.resources import files
    for selected_module in (model,field_execution,tracking_execution,rf_tracking_program,examples,ion_release):
        assert Path(selected_module.__file__).resolve().is_relative_to(purelib), selected_module.__file__
    for name in ('model_drive.lua','rf_drive.lua','rf_tracking.lua'):
        assert native_resource_path(name).resolve().is_relative_to(purelib), name
    release=copy.deepcopy(examples.load_example('rf_oatof_functional_v1').release)
    release['source_component_id']='first'
    release['release_spec']['frame_id']='toy_local'
    release['release_spec']['particle_count']=release['release_spec']['mother_particle_count']=2
    release['particle_ids']=release['particle_ids'][:2]
    packet=ion_release.sample_release(release).to_dict()
    clock=dict(packet['clock'],phase_reference_instrument_time_us=0.)
    drive=dict(clock=clock,groups={'first':{'body':dict(kind='static',voltage_v=1.25)},
                                  'second':{'body':dict(kind='static',voltage_v=0.)}})
    prepared=model.compile_prepared_model(compiled,product.components_resolved,drive=drive,physics=model.RF_PHYSICS)
    doc=model.require_prepared_model(prepared)
    assert doc['field_status']=='not_solved' and doc['drive']==drive
    mapped={(row['instance_id'],row['electrode_group_id']):row['native_targets'][0]['electrode_id'] for row in doc['native_drive_rows']}
    assert mapped=={(row['instance_id'],row['electrode_group_id']):row['native_id'] for row in compiled.frontend_geometry['electrode_mapping']}
    graph=field_execution.plan_fields_execution(prepared,numerics=dict(refine_policy='vendor_default'))
    assert graph['expected_operation_ids']==['materialize_geometry','refine_world','audit_fields']
    epoch=Path(str(files('msplatform.examples').joinpath('instrument_epoch_v1.json')))
    authority=Path(str(files('msplatform.examples').joinpath('instrument_clock_authority_v1.json')))
    assert epoch.resolve().is_relative_to(purelib) and authority.resolve().is_relative_to(purelib)
    clocks={'instrument_epoch':file_record(epoch),'clock_authority':file_record(authority)}
    propagation=dict(schema_version=1,scope='continuous_assembly',end_policy=dict(maximum_particle_age_us=200.),
        consumed_plane_events=[],stop=None,dynamics=dict(kinematics='nonrelativistic',collisions='none',space_charge='none'))
    tracking_numerics=dict(maximum_step_us=.01,trajectory_quality=5,grouped=0)
    options=dict(particles=packet,clock_records=clocks,propagation=propagation,
                 observations=dict(plane_observations=[]),numerics=tracking_numerics)
    tracking=tracking_execution.plan_tracking_execution(prepared,**options)
    assert tracking['flight']['tracking_kind']=='static_world' and len(tracking['rows'])==2
    controls=rf_tracking_program.render_rf_controls(prepared,tracking,assets={},native_sources={})
    assert 'function segment.fast_adjust()' in controls['program'] and '1.25' in controls['program']
    outside=copy.deepcopy(packet)
    outside['rows'][0]['position_x_mm']=1000.
    try: tracking_execution.plan_tracking_execution(prepared,**dict(options,particles=outside))
    except ValueError as exc: assert 'outside' in str(exc),exc
    else: raise AssertionError('outside-domain original birth was accepted')
    print('INSTALLED_GENERIC_STATIC_PLANNING=PASS groups=2 births=2 outside_refused=1 native=none',flush=True)
    print('INSTALLED_GENERIC_REGISTERED_GEOMETRY=PASS instances=2 renamed=1 capability_rejected=1 pure_compile=1',flush=True)
