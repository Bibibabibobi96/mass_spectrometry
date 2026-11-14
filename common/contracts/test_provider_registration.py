"""Real registered-provider Assembly to existing geometry projections; no CAD kernel."""
import copy
import unittest
from msplatform import assembly, components
from msplatform.backends.comsol.assembly_geometry import project_assembly_geometry
from msplatform.components.geometry_members import assembly_geometry_members
from msplatform.components.registry import ProviderDescriptor, provider_descriptor, register_provider
from common.contracts.test_support.registered_component import DESCRIPTOR, ensure_registered
from msplatform.contracts.machine_contracts import ContractError
from msplatform.exporters.step import _validate_shape

class RegisteredProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_registered()

    def test_actual_assembly_and_existing_projections(self):
        a=components.resolve_component({'provider_id':'toy_registered','design':{'width_mm':2}})
        b=components.resolve_component({'provider_id':'toy_registered','design':{'width_mm':3}})
        def pose(x):return dict(schema_version=1,role='rigid_transform',from_frame_id='toy_local',to_frame_id='world',rotation=[[1,0,0],[0,1,0],[0,0,1]],translation_mm=[x,0,0])
        recipe=dict(schema_version=1,role='assembly_recipe',integration_id='toy_integration',recipe_id='toy_recipe',assembly_frame_id='world',position_tolerance_mm=1e-6,angular_tolerance_rad=1e-6,
            instances=[dict(instance_id='second',project_id='toy_registered',transform=pose(10)),dict(instance_id='first',project_id='toy_registered',transform=pose(0))],connections=[])
        product=assembly.assemble(recipe,{'first':a,'second':b})
        snapshot=dict(composition_plan=product.composition_plan,components_resolved=product.components_resolved,components_source=product.components_source)
        members=assembly_geometry_members(snapshot)
        self.assertEqual([v['instance_id'] for v in members],['second','first'])
        self.assertEqual([v['shape']['parts'][0]['size_mm'][0] for v in members],[3,2])
        self.assertEqual([v['transform']['translation_mm'][0] for v in members],[10,0])
        self.assertEqual(len({(v['instance_id'],v['member_id']) for v in members}),2)
        for member in members:_validate_shape(member['shape'])
        from msplatform.capabilities import capabilities
        step=capabilities(dict(schema_version=1,operation='export_cad',arguments=dict(assembly=product,format='step',options=dict(representation='physical_solids',write_pcurves=True,precision_mode=0))))
        self.assertEqual(step['contract_status'],'accepted')
        projection=project_assembly_geometry(snapshot,outer_box_mm=dict(min=[-20,-20,-20],max=[20,20,20]))
        self.assertEqual(projection['members'],list(members));self.assertEqual(len(projection['electrode_groups']),2)
        # Rename both instances and reverse declaration order while retaining
        # each source width and world pose; compare scientific geometry, not IDs.
        renamed=copy.deepcopy(recipe)
        renamed['instances']=[dict(instance_id='renamed_first',project_id='toy_registered',transform=pose(0)),
                              dict(instance_id='renamed_second',project_id='toy_registered',transform=pose(10))]
        renamed_product=assembly.assemble(renamed,{'renamed_first':a,'renamed_second':b})
        renamed_snapshot=dict(composition_plan=renamed_product.composition_plan,
            components_resolved=renamed_product.components_resolved,components_source=renamed_product.components_source)
        from msplatform.backends.comsol.assembly_geometry import _world_bounds
        def physical(rows):
            return sorted((tuple(tuple(x) for x in _world_bounds(row)),row['electrode_group_id'],
                           row['representation_role'],row['shape']['parts'][0]['size_mm'][0]) for row in rows)
        self.assertEqual(physical(members),physical(assembly_geometry_members(renamed_snapshot)))
        invalid=copy.deepcopy(recipe)
        invalid['connections']=[dict(connection_id='bad_connection',upstream=dict(instance_id='first',port_id='missing'),
            downstream=dict(instance_id='second',port_id='out'),gap_mm=0,coupling_mode='state_handoff')]
        with self.assertRaises((ContractError,ValueError,KeyError)):
            assembly.assemble(invalid,{'first':a,'second':b})
        invalid['connections'][0]['upstream']['port_id']='out'
        with self.assertRaises((ContractError,ValueError)):
            assembly.assemble(invalid,{'first':a,'second':b})
        bad=copy.deepcopy(snapshot);bad['components_source']['first']['width_mm']=9
        with self.assertRaises(ContractError):assembly_geometry_members(bad)
        bad=copy.deepcopy(snapshot);bad['composition_plan']['recipe']['instances'][0]['transform']['from_frame_id']='wrong'
        with self.assertRaises((ContractError,ValueError)):assembly_geometry_members(bad)
        with self.assertRaises(ValueError):project_assembly_geometry(snapshot,outer_box_mm=dict(min=[0,-20,-20],max=[20,20,20]))
        bad_component=copy.deepcopy(a);bad_component._assembly_interface['ports']['out']['outward_normal']=[0,0,0]
        with self.assertRaises((ContractError,ValueError)):assembly.assemble(recipe,{'first':bad_component,'second':b})

    def test_registration_and_missing_provider_refusals(self):
        with self.assertRaises(ContractError):register_provider(DESCRIPTOR)
        with self.assertRaises(ContractError):provider_descriptor('not_registered')
        with self.assertRaises(ContractError):components.resolve_component({'provider_id':'toy_registered','design':{'width_mm':0}})
        with self.assertRaises(ContractError):ProviderDescriptor('bad','bad',None,lambda *a:None,lambda *a:None,('msplatform.components.bad',))
        for closure in (('',),('../bad',),('common.bad/path',),('common..bad',),('common.bad', 'common.bad')):
            with self.subTest(closure=closure),self.assertRaises(ContractError):
                ProviderDescriptor('bad','bad',lambda *a:None,lambda *a:None,lambda *a:None,closure)
        self.assertEqual(DESCRIPTOR.source_closure,('common.contracts.test_support.registered_component',))

    def test_provider_callbacks_cannot_mutate_authority(self):
        def mutating_resolve(source,profile):
            source['width_mm']=4
            return DESCRIPTOR.resolve(source,profile)
        register_provider(ProviderDescriptor('mutating_resolver','mutating_resolver',mutating_resolve,
            lambda *args:None,DESCRIPTOR.members,('common.contracts.test_support.registered_component',)))
        request={'provider_id':'mutating_resolver','design':{'width_mm':2}}
        before=copy.deepcopy(request)
        with self.assertRaisesRegex(ContractError,'mutated'):components.resolve_component(request)
        self.assertEqual(request,before)
        def resolve(source,profile):
            resolved,interface=DESCRIPTOR.resolve(source,profile);interface['project_id']='mutating_members'
            return resolved,interface
        def validate(source,resolved,interface):
            expected,canonical=resolve(source,interface.get('geometry_profile_id'))
            if (resolved,interface)!=(expected,canonical):raise ContractError('source mismatch')
        def members(resolved,interface):
            resolved['width_mm']=999
            return DESCRIPTOR.members(resolved,interface)
        register_provider(ProviderDescriptor('mutating_members','mutating_members',resolve,validate,members,
            ('common.contracts.test_support.registered_component',)))
        component=components.resolve_component({'provider_id':'mutating_members','design':{'width_mm':2}})
        pose=dict(schema_version=1,role='rigid_transform',from_frame_id='toy_local',to_frame_id='world',rotation=[[1,0,0],[0,1,0],[0,0,1]],translation_mm=[0,0,0])
        recipe=dict(schema_version=1,role='assembly_recipe',integration_id='toy_integration',recipe_id='toy_recipe',assembly_frame_id='world',position_tolerance_mm=1e-6,angular_tolerance_rad=1e-6,instances=[dict(instance_id='first',project_id='mutating_members',transform=pose)],connections=[])
        product=assembly.assemble(recipe,{'first':component})
        snapshot=dict(composition_plan=product.composition_plan,components_resolved=product.components_resolved,components_source=product.components_source)
        before=copy.deepcopy(snapshot)
        with self.assertRaisesRegex(ValueError,'mutated'):assembly_geometry_members(snapshot)
        self.assertEqual(snapshot,before)

    def test_real_geometry_consumers_refuse_unsupported_shape(self):
        def resolve(source,profile):
            design,interface=DESCRIPTOR.resolve(source,profile)
            interface['project_id']='unsupported_shape'
            return design,interface
        def validate(source,resolved,interface):
            if (resolved,interface)!=resolve(source,interface.get('geometry_profile_id')):
                raise ContractError('source mismatch')
        def members(resolved,interface):
            result=DESCRIPTOR.members(resolved,interface)
            result[0]['shape']={'kind':'unsupported_shape'}
            return result
        register_provider(ProviderDescriptor('unsupported_shape','unsupported_shape',resolve,validate,members,
            ('common.contracts.test_provider_registration',)))
        item=components.resolve_component({'provider_id':'unsupported_shape','design':{'width_mm':2}})
        pose=dict(schema_version=1,role='rigid_transform',from_frame_id='toy_local',to_frame_id='world',
            rotation=[[1,0,0],[0,1,0],[0,0,1]],translation_mm=[0,0,0])
        recipe=dict(schema_version=1,role='assembly_recipe',integration_id='toy_integration',recipe_id='toy_recipe',
            assembly_frame_id='world',position_tolerance_mm=1e-6,angular_tolerance_rad=1e-6,
            instances=[dict(instance_id='one',project_id='unsupported_shape',transform=pose)],connections=[])
        product=assembly.assemble(recipe,{'one':item})
        snapshot=dict(composition_plan=product.composition_plan,components_resolved=product.components_resolved,
                      components_source=product.components_source)
        with self.assertRaisesRegex(ValueError,'unsupported'):
            project_assembly_geometry(snapshot,outer_box_mm=dict(min=[-20,-20,-20],max=[20,20,20]))
        from msplatform.capabilities import capabilities
        result=capabilities(dict(schema_version=1,operation='export_cad',arguments=dict(assembly=product,format='step',
            options=dict(representation='physical_solids',write_pcurves=True,precision_mode=0))))
        self.assertEqual(result['contract_status'],'rejected')
