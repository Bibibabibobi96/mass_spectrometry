"""Real Store ownership for neutral scalar source closures; native leaves are inert."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from msplatform.backends.simion.neutral_sampled_field import protect_neutral_records
from msplatform.execution.capacity_ledger import initialize_capacity_ledger
from msplatform.execution.owner import standalone_native_store
from msplatform.results.artifacts import open_artifact
from msplatform.storage import ArtifactStore
from tests.contracts.test_support.sfi_scalar_owner_fixture import make_context, publish_fixture


class NeutralStoreSourceGuardTests(unittest.TestCase):
    def test_frozen_clock_retains_declared_relative_authority(self):
        from msplatform.execution.inputs import freeze_file
        from msplatform.io.clock_authority import validate_clock_authority
        from msplatform import examples
        source = Path(examples.__file__).parent
        contract = source / 'instrument_clock_authority_v1.json'
        epoch = source / 'instrument_epoch_v1.json'
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for original in (contract, epoch):
                freeze_file(original, root / original.name, retention_role='required_evidence')
            self.assertEqual(validate_clock_authority(root / contract.name, root)['clock_epoch_id'],
                             'instrument_clock_epoch_v1')

    def test_real_store_source_closure_and_unbound_or_tampered_refusal(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            context, budget, retention = make_context(root)
            artifact_root = context.workspace / 'artifacts'
            artifact_root.mkdir(parents=True)
            initialize_capacity_ledger(artifact_root, objects=[])
            store = ArtifactStore(root / 'store')
            with standalone_native_store(store, task_key='neutral-source-smoke', budget=128 * 1024**2):
                geometry = publish_fixture(context, budget, retention, name='geometry', kind='geometry_artifact',
                    data={'projection': {'x': 1}}, metadata={'scope': 'inert'})
                prepared = publish_fixture(context, budget, retention, name='prepared', kind='prepared_model',
                    data={'geometry_manifest': Path(geometry['manifest']['path']).read_bytes()},
                    metadata={'backend': 'comsol', 'scope': 'assembly_electrostatic_unsolved',
                              'geometry_source_reference': geometry})
                field = publish_fixture(context, budget, retention, name='source', kind='field_solution',
                    data={'prepared_manifest': Path(prepared['manifest']['path']).read_bytes()},
                    metadata={'backend': 'comsol', 'scope': 'single_stationary_workpoint',
                              'stationary_source': {'reference': prepared, 'kind': 'prepared_model'}})
                sample = publish_fixture(context, budget, retention, name='sample', kind='scalar_field_samples',
                    data={'projection': {'x': 2}}, metadata={'scope': 'assembly_world_scalar_samples',
                        'backend': 'comsol', 'field_solution_product_id': field['product_id']},
                    linked={'field_solution_manifest': field['manifest']})
                from tests.contracts.test_support.ip_mr_sampled_field_fixture import _fixture_geometry
                _, _, scientific_model = _fixture_geometry()
                bundle = publish_fixture(context, budget, retention, name='bundle', kind='field_bundle',
                    data={'compiled_model': scientific_model.document, 'sampled_basis': {'role': 'inert_fixture'}},
                    metadata={'backend': 'simion', 'field_status': 'available', 'source_status': 'not_requested',
                              'field_representation': 'neutral_sampled_basis_with_collision_geometry'})
                bundle_artifact = open_artifact(bundle, expected_kind='field_bundle')
                bundle_record = dict(bundle_artifact.data_records['compiled_model'],
                                     path=str(bundle_artifact.data_path('compiled_model')))
                protect_neutral_records(SimpleNamespace(context=context), [bundle], [bundle_record])
                artifact = open_artifact(sample, expected_kind='scalar_field_samples')
                record = dict(artifact.data_records['projection'], path=str(artifact.data_path('projection')))
                session = SimpleNamespace(context=context)
                protect_neutral_records(session, [sample, field, prepared, geometry], [record])
                with self.assertRaisesRegex(ValueError, 'not bound'):
                    protect_neutral_records(session, [sample, field, prepared, geometry], [dict(record, sha256='0' * 64)])
                foreign = root / 'unbound'
                foreign.write_text('x')
                with self.assertRaisesRegex(ValueError, 'not bound'):
                    protect_neutral_records(session, [sample, field, prepared, geometry], [dict(record, path=str(foreign))])


if __name__ == '__main__':
    unittest.main()
