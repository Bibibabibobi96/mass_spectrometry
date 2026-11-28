"""Historical read-only exit validation using frozen witness bytes; no producer."""
import base64
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from msplatform.io.manifest_records import file_record
from msplatform.results.component_exit_history import read_verified_component_exit


class HistoricalComponentExitTests(unittest.TestCase):
    def test_measured_exit_centroid_source_producer_is_absent(self):
        import importlib.util
        from msplatform.workflows.mr_design import accelerator_interface as interface_prepare
        self.assertFalse(hasattr(interface_prepare, "bind_joint_workbench"))
        self.assertFalse(hasattr(interface_prepare, "finalize_interface"))
        from msplatform.analysis import recorded_joint_trial
        self.assertFalse(hasattr(recorded_joint_trial, 'prepare_trial'))
        self.assertFalse(hasattr(recorded_joint_trial, 'materialize_batch'))
        self.assertIsNone(importlib.util.find_spec('msplatform.workflows.prepared_joint'))

    def test_frozen_history_preserves_cohort_and_rejects_tamper(self):
        witness = Path(__file__).resolve().parents[1]/'components/multi_reflection_tof/fixtures/mr_measured_source_old_witness.json'
        artifacts = json.loads(witness.read_text(encoding='utf-8'))['stages']['population']['artifacts']
        with TemporaryDirectory() as directory:
            root = Path(directory); (root/'inputs').mkdir()
            for name in ('component_particle_state.csv', 'source_census.csv', 'upstream_clock_authority.json'):
                item = artifacts[name]; data = base64.b64decode(item['base64'], validate=True)
                self.assertEqual(hashlib.sha256(data).hexdigest(), item['sha256'].lower())
                (root/name).write_bytes(data)
            (root/'inputs/instrument_epoch.json').write_text('{"instrument_time_us": 0}\n', encoding='utf-8')
            edge = dict(connection_id='ip_to_mr', upstream=dict(instance_id='processor_a', port_id='extraction_exit'),
                downstream=dict(instance_id='analyzer_b', port_id='accelerator_entry'), coupling_mode='monolithic_joint_solve')
            plan = dict(scope=dict(instance_ids=['processor_a','analyzer_b'], connection_ids=['ip_to_mr']), recipe=dict(
                instances=[dict(instance_id='processor_a',project_id='dual_pressure_rectilinear_ion_processor'),
                           dict(instance_id='analyzer_b',project_id='parallel_mirror_dual_stripe_mr_tof')], connections=[edge]))
            matching = root/'matching.json'; matching.write_text(json.dumps({'composition_plan':plan}), encoding='utf-8')
            states, census = root/'component_particle_state.csv', root/'source_census.csv'
            clock, epoch = root/'upstream_clock_authority.json', root/'inputs/instrument_epoch.json'
            counts = dict(source=3, transferred=2, not_transferred=1)
            exported = dict(schema_version=2, role='ion_processor_component_exit_export', status='prepared',
                source_project='dual_pressure_rectilinear_ion_processor', source_instance_id='processor_a',
                target_instance_id='analyzer_b', clock_epoch_id='ion_processor_epoch_zero_v1', source_run=str(root),
                counts=counts, transferred_particle_ids=[1,7], not_transferred_particle_ids=[9],
                inputs={'inputs/clock_authority.json':file_record(clock), 'inputs/instrument_epoch.json':file_record(epoch)},
                outputs={'component_states':file_record(states), 'mother_census':file_record(census)})
            component = root/'component.json'; component.write_text(json.dumps(exported), encoding='utf-8')
            transform = dict(schema_version=1, role='rigid_transform', from_frame_id='mr_frame.v2', to_frame_id='mr_frame.v2',
                rotation=[[1,0,0],[0,1,0],[0,0,1]], translation_mm=[0,0,0])
            handoff = dict(schema_version=3,role='mrtof_ion_processor_handoff_preparation',status='prepared_only',
                solver_execution=False,inputs={'component_receipt':file_record(component)},
                outputs={'matching_request_resolved':file_record(matching), 'source_census':file_record(census),
                         'component_particle_state':file_record(states)}, connection=edge, rigid_transform=transform, counts=counts)
            receipt = root/'handoff.json'; receipt.write_text(json.dumps(handoff), encoding='utf-8')
            before = {path: path.read_bytes() for path in root.rglob('*') if path.is_file()}
            result = read_verified_component_exit(receipt)
            self.assertEqual([row['particle_id'] for row in result['table'].rows], [1,7])
            self.assertEqual(result['exported']['source_project'], 'dual_pressure_rectilinear_ion_processor')
            self.assertEqual({path: path.read_bytes() for path in before}, before)
            handoff['rigid_transform']['translation_mm'][0] = 1
            receipt.write_text(json.dumps(handoff), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'rigid registration'):
                read_verified_component_exit(receipt)
            receipt.write_bytes(before[receipt])
            states.write_bytes(states.read_bytes()+b'tamper')
            with self.assertRaisesRegex(ValueError, 'bytes/SHA'):
                read_verified_component_exit(receipt)


if __name__ == '__main__':
    unittest.main()
