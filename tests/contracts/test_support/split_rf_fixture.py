"""Real RF/OA/TOF split fixture projected from the frozen legacy example."""
import copy
from msplatform import assembly, components, examples
from msplatform.backends import simion
from msplatform.backends.simion.model import compile_prepared_model, PHYSICS
from msplatform.components.single_reflection_oa_tof.accelerator_geometry import resolve_accelerator_geometry, apply_side_opening, resolve_oa_provider
from msplatform.components.single_reflection_tof.legacy_projection import project_legacy_downstream
from msplatform.components.single_reflection_tof.geometry import resolve_downstream_geometry
from msplatform.backends.simion.electrode_contract import scientific_multipole_drive

def split_case(clock, pulse):
    case = examples.load_example('rf_oatof_functional_v1')
    rf = components.resolve_component(case.component_requests['multipole'])
    old = components.resolve_component(case.component_requests['oatof'])
    olddesign = old.resolved_design
    projection = apply_side_opening(resolve_accelerator_geometry(olddesign, variant_id='three_zone_square'), side_opening=olddesign['mechanical_side_opening'])
    source = resolve_oa_provider(olddesign, projection=projection, geometry_profile_id=None)['source']
    oa = components.resolve_component({'provider_id':'orthogonal_accelerator','design':{'instrument_geometry':source}})
    tof = components.resolve_component({'provider_id':'single_reflection_tof','design':project_legacy_downstream(olddesign)})
    def instance(name, component):
        return {'instance_id':name,'project_id':component.assembly_interface['project_id'], 'transform':{'schema_version':1,'role':'rigid_transform','from_frame_id':component.assembly_interface['local_frame_id'],'to_frame_id':'oatof_global','rotation':[[1,0,0],[0,1,0],[0,0,1]],'translation_mm':[0,0,0]}}
    recipe=copy.deepcopy(case.recipe);recipe['schema_version']=2
    recipe['instances'][1]=instance('oa',oa);recipe['instances'].append(instance('tof',tof))
    recipe['connections'][0]['downstream']['instance_id']='oa'
    recipe['containments']=[{'relation_id':'oa_inside_tof','container_instance_id':'tof','contained_instance_id':'oa','domain_id':'flight_tube_cavity','coupling_mode':'monolithic_joint_solve'}]
    joined=assembly.assemble(recipe,{'multipole':rf,'oa':oa,'tof':tof})
    numerics=copy.deepcopy(case.geometry_numerics);numerics['geometry_build']['detector']['max_mib']=128.
    compiled=simion.compile_geometry(joined,numerics=numerics)
    from msplatform.components.single_reflection_oa_tof.electrode_topology import build_electrode_topology
    from msplatform.contracts.electrode_sources import physical_voltage_value
    topology=build_electrode_topology(olddesign,projection=projection)
    voltages={row['electrode_group_id']:physical_voltage_value(topology,row['voltage_source']['pointer']) for row in topology['groups']}
    maps=compiled.frontend_geometry['electrode_bindings']
    oa_groups={name:({'kind':'static','voltage_v':voltages['common_ground']} if name=='grounded_shield' else {'kind':'pulse','off_voltage_v':0.,'on_voltage_v':voltages['accelerator_'+name]}) for name in maps['oa']}
    d=tof.resolved_design
    physical=resolve_downstream_geometry(d['geometry_mm'],d['coordinate_convention'],d['rings'],d['electrodes_v'])
    tof_groups={('common_ground' if row['grounded'] else row['role']):{'kind':'static','voltage_v':row['operating_voltage_v']} for row in physical['electrodes']}
    drive={'groups':{'multipole':scientific_multipole_drive(rf.resolved_design,maps['multipole']),'oa':oa_groups,'tof':tof_groups},'clock':clock,'pulse':pulse}
    model=compile_prepared_model(compiled,joined.components_resolved,drive=drive,physics=PHYSICS)
    return case,recipe,compiled,model
