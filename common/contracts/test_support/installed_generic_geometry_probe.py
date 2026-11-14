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
    print('INSTALLED_GENERIC_REGISTERED_GEOMETRY=PASS instances=2 renamed=1 capability_rejected=1 pure_compile=1',flush=True)
