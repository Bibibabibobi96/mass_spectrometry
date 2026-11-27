"""Real MR provider and local Assembly scope; no native field is assumed."""
import json
from pathlib import Path
import unittest

from msplatform.assembly.factory import assemble
from msplatform.components.catalog import resolve_component
from msplatform.components.geometry_members import assembly_geometry_members
from msplatform.particle_release.authoring import ReleaseRealization

ROOT = Path(__file__).resolve().parents[2]


class MrLocalAssemblyTests(unittest.TestCase):
    def test_real_geometry_and_explicit_software_workpoint_compile(self):
        # Pure geometry/model only; the zero workpoint is a software test input,
        # not an instrument field, refinement, native run or precision claim.
        from msplatform.backends.simion.operations import compile_geometry
        from msplatform.backends.simion.model import RF_PHYSICS, compile_prepared_model, require_prepared_model
        author = json.loads((ROOT / 'tests/contracts/test_support/ip_mr_current_requests.json').read_text(encoding='utf-8'))
        providers = {key: resolve_component(value) for key, value in author['component_requests'].items()}
        assembly = assemble(author['recipe'], providers, local_scope=dict(instance_ids=['mrtof'],
            research_scope='software witness discovery', boundary_assumptions='explicit sampled field'))
        fixture = json.loads((ROOT / 'tests/contracts/test_support/mr_local_witnesses.json').read_text(encoding='utf-8'))
        origin, pitch = fixture['domain']['minimum_mm'], fixture['pitch_mm']
        witnesses = [dict(instance_id='mrtof', electrode_group_id=name,
            gu=[round((point[i] - origin[i]) / pitch) for i in range(3)])
            for name, point in fixture['points_mm'].items()]
        numerics = dict(representation='neutral_world_collision', domain=fixture['domain'], pitch_mm=pitch,
            boundary=fixture['boundary'], metal_witnesses=witnesses, void_witnesses=[[0, 0, 0]])
        geometry = compile_geometry(assembly, numerics=numerics)
        self.assertEqual(geometry.frontend_geometry['role'], 'simion_neutral_world_collision_geometry')
        self.assertEqual(len(geometry.frontend_geometry['members']), 24)
        self.assertEqual(len(geometry.frontend_geometry['metal_witnesses']), 22)
        groups = {'mrtof': {name: dict(kind='static', voltage_v=0.) for name in fixture['points_mm']}}
        clock = json.loads((ROOT / 'src/msplatform/examples/oa_split_tof_native_small_v1.json').read_text(encoding='utf-8'))['release']['clock']
        clock['phase_reference_instrument_time_us'] = 0.
        model = compile_prepared_model(geometry, assembly.components_resolved,
                                       drive=dict(groups=groups, clock=clock), physics=RF_PHYSICS)
        document = require_prepared_model(model)
        self.assertEqual(document['field_status'], 'not_solved')
        self.assertEqual(document['source_status'], 'not_requested')
        self.assertEqual(len(document['native_drive_rows']), 22)

    def test_selected_mr_keeps_real_geometry_and_declared_boundary(self):
        fixture = json.loads((ROOT / 'tests/contracts/test_support/ip_mr_current_requests.json').read_text(encoding='utf-8'))
        providers = {key: resolve_component(value) for key, value in fixture['component_requests'].items()}
        assembly = assemble(fixture['recipe'], providers, local_scope=dict(instance_ids=['mrtof'],
            research_scope='local MR original-birth field study',
            boundary_assumptions='external field and independent local particle release are explicit'))
        scope = assembly.composition_plan['scope']
        self.assertEqual(scope['instance_ids'], ['mrtof'])
        self.assertEqual(scope['connection_ids'], [])
        self.assertEqual(scope['boundary_connection_ids'], ['ip_to_mr'])
        members = assembly_geometry_members(dict(composition_plan=assembly.composition_plan,
            components_resolved=assembly.components_resolved, components_source=assembly.components_source))
        self.assertEqual(len(members), 24)
        self.assertEqual({member['instance_id'] for member in members}, {'mrtof'})
        self.assertEqual(len({member['electrode_group_id'] for member in members}), 22)
        self.assertTrue(all(member['source_refs'] for member in members))
        # This is an explicitly authored local source, not a measured IP exit.
        request = json.loads((ROOT / 'src/msplatform/examples/oa_split_tof_native_small_v1.json').read_text(encoding='utf-8'))['release']
        request['source_component_id'] = 'mrtof'
        request['release_spec']['frame_id'] = assembly.composition_plan['components']['mrtof']['local_frame_id']
        release = ReleaseRealization(request)
        self.assertEqual([row['particle_id'] for row in release.rows], [1, 2, 3])
        self.assertTrue(all(row['state_event'] == 'source_birth' and row['source_component_id'] == 'mrtof'
                            and row['target_component_id'] == 'mrtof' and row['parent_particle_id'] is None
                            for row in release.rows))
