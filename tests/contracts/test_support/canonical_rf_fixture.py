"""Canonical RF-only acceptance fixture, private software test."""
import copy,json
from pathlib import Path
from msplatform import assembly,components
from msplatform.components.geometry_members import assembly_geometry_members

REPO=Path(__file__).resolve().parents[3]

def make_assembly(names=('first','second'), reverse=False):
    example=json.loads((REPO/'src/msplatform/examples/rf_oatof_functional_v1.json').read_text(encoding='utf-8'))
    first=copy.deepcopy(example['component_requests']['multipole']);second=copy.deepcopy(first)
    second['design']['drive']['rf_amplitude_V_zero_to_peak_per_group']=100.0
    second['design']['geometry_mm']['rod_radius_ratio']=0.45
    parts={names[0]:components.resolve_component(first),names[1]:components.resolve_component(second)}
    def pose(z):
        return dict(schema_version=1,role='rigid_transform',from_frame_id='multipole.cartesian.z_axis.v1',to_frame_id='world',rotation=[[1,0,0],[0,1,0],[0,0,1]],translation_mm=[0,0,z])
    rows=[dict(instance_id=names[0],project_id='rf_multipole_ion_optics',transform=pose(0)),dict(instance_id=names[1],project_id='rf_multipole_ion_optics',transform=pose(80.6))]
    if reverse:rows.reverse()
    recipe=dict(schema_version=1,role='assembly_recipe',integration_id='canonical_rf_test',recipe_id='two_unlisted_rf',assembly_frame_id='world',position_tolerance_mm=1e-6,angular_tolerance_rad=1e-6,instances=rows,connections=[dict(connection_id='rf_join',upstream=dict(instance_id=names[0],port_id='mechanical_exit'),downstream=dict(instance_id=names[1],port_id='mechanical_entrance'),gap_mm=1.0,coupling_mode='monolithic_joint_solve')])
    obj=assembly.assemble(recipe,parts)
    snapshot=dict(composition_plan=obj.composition_plan,components_resolved=obj.components_resolved,components_source=obj.components_source)
    return obj,list(assembly_geometry_members(snapshot))


def compile_case(obj, members):
    from msplatform.backends.simion.operations import compile_geometry
    from msplatform.components.shape_query import query_members
    origin=[-15,-15,-5];groups={}
    for member in members:
        groups.setdefault((member['instance_id'],member['electrode_group_id']),member)
    witnesses=[]
    for (instance,group),member in groups.items():
        shape=member['shape'];z=(shape['z_min_mm']+shape['z_max_mm'])/2+member['transform']['translation_mm'][2]
        point=[round(shape['center_xy_mm'][0]),round(shape['center_xy_mm'][1]),round(z)]
        if query_members(members,point,frame_id='world') != {'status':'interior','group':(instance,group)}:
            raise ValueError('canonical group witness is not uniquely interior')
        witnesses.append(dict(instance_id=instance,electrode_group_id=group,gu=[int(point[i]-origin[i]) for i in range(3)]))
    numerics=dict(representation='neutral_world_collision',domain=dict(frame_id='world',minimum_mm=origin,maximum_mm=[15,15,170]),pitch_mm=1,boundary='native_zero_neumann',metal_witnesses=witnesses,void_witnesses=[[0,0,0]])
    return compile_geometry(obj,numerics=numerics),numerics


def sample_fixture(context, budget, retention, obj, members, groups):
    """Publish inert, full-domain test samples using the existing SFI fixture publisher."""
    import struct
    from tests.contracts.test_sfi_scalar_binding import SfiScalarAdmissionTests, SOLUTION
    from tests.contracts.test_support.sfi_scalar_owner_fixture import publish_fixture
    from msplatform.backends.comsol.assembly_geometry import project_assembly_geometry
    from msplatform.backends.comsol.assembly_electrostatic_model import validate_request
    from msplatform.backends.simion.standalone_pa_composition import PaHeader
    from msplatform.results.artifacts import open_artifact
    snap=dict(composition_plan=obj.composition_plan,components_resolved=obj.components_resolved,components_source=obj.components_source)
    projection=project_assembly_geometry(snap,outer_box_mm={'min':[-20,-20,-10],'max':[20,20,175]})
    fixture=SfiScalarAdmissionTests(methodName='runTest');fixture.projection=projection;fixture.snapshot=snap
    fixture.publish=lambda name,kind,data,metadata,inputs=None,linked=None: publish_fixture(context,budget,retention,name=name,kind=kind,data=data,metadata=metadata,inputs=inputs,linked=linked)
    geometry=fixture.make_geometry();keys=sorted((i,g) for i,rows in groups.items() for g in rows)
    values={(i,g):groups[i][g]['polarity']*groups[i][g]['rf_amplitude_v'] for i,g in keys}
    request=validate_request(projection,dict(group_voltages=[dict(instance_id=i,electrode_group_id=g,voltage_v=values[(i,g)]) for i,g in keys],relative_permittivity=1.,exterior={'kind':'potential','voltage_v':0.},mesh={'global_automatic_level':9,'electrode_hmax_mm':5.},study={'kind':'stationary'}))
    grid=dict(frame_id='world',origin_mm=[-15.,-15.,-5.],pitch_mm=[1.,1.,1.],dimensions=[31,31,176],block_points=4096,study_tag='std1',solution_tag='sol1',dataset_tag='dset1',point_count=31*31*176,maximum_mm=[15.,15.,170.],coordinate_sanity_mm=1e-6)
    prepared=fixture.publish('canonical-prepared','prepared_model',{'geometry_manifest':geometry['manifest']},
        {'backend':'comsol','scope':'assembly_electrostatic_unsolved','geometry_source_reference':geometry})
    data={'projection':projection,'request':request,'geometry_validation':{'position_mm':1e-6},'reopen_geometry':{'vacuum_domains':[1]},'reopen_solution':{'solution':SOLUTION},'model':b'inert model, never opened as MPH'}
    solution=fixture.publish('canonical-solution','field_solution',data,{'backend':'comsol','scope':'single_stationary_workpoint','field_status':'solved','native_reopen_verified':True,'solution':SOLUTION,'stationary_source':{'reference':prepared,'kind':'prepared_model'}},linked={'prepared_manifest':prepared['manifest']})
    source=open_artifact(solution,expected_kind='field_solution')
    report=dict(status='success',scope='assembly_world_scalar_samples',field_qualification=False,compute_calls=0,filled_conductor_count=0,coordinate_mapping='world_identity',model_path=str(source.data_path('model')),vacuum_domains=[1],fem_valid=grid['point_count'],invalid_count=0,solution_readback=SOLUTION,coordinate_witness={'status':'insufficient','index':0,'requested_mm':[],'actual_mm':[],'geometry_length_unit':'mm'},**grid)
    header=PaHeader(-2,1,10000.,31,31,176,1<<28,1.,1.,1.).pack();count=grid['point_count']
    sampled={'projection':projection,'grid':grid,'request':request,'reopen_solution':{'solution':SOLUTION},'geometry_validation':{'position_mm':1e-6},'reopen_geometry':{'vacuum_domains':[1]},'report':report,'field_v':header+bytes(count*8),'field_valid':header+struct.pack('<d',1.)*count}
    ref=fixture.publish('canonical-sample','scalar_field_samples',sampled,{'backend':'comsol','scope':'assembly_world_scalar_samples','field_status':'sampled','frame_id':'world'},linked={'field_solution_manifest':solution['manifest'],'field_solution_model':source.data_records['model']})
    pivot=next(key for key in keys if values[key]!=0)
    weights=[dict(instance_id=i,electrode_group_id=g,weight=(1.0/values[pivot] if (i,g)==pivot else 0.)) for i,g in keys]
    return geometry,{'canonical':dict(reference=ref,request=request,weights=weights)}
