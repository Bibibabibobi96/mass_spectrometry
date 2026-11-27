"""Explicit fit sources are guarded and revalidated before owner admission."""
import base64
from contextlib import ExitStack, contextmanager
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from msplatform.workflows.native_tracing import _guard_compensation_sources


class CompensationRecipeGuardTests(unittest.TestCase):
    def test_public_field_operation_holds_both_sources_through_owner(self):
        from msplatform.backends.simion import operations
        from msplatform.contracts.machine_contracts import ContractError
        root = Path('C:/fixture')
        context = SimpleNamespace(workspace=root)
        model = {'manifest': {'path': 'model'}, 'product_id': 'model'}
        field = {'manifest': {'path': 'field'}, 'product_id': 'fields'}
        basis = {'reference': field, 'fit': {'fit': {'regularization': .1}}, 'regularization': .1}
        store = object()
        active = []
        @contextmanager
        def guard(reference, *, expected_kind, expected_artifact_root, artifact_store):
            self.assertIs(artifact_store, store)
            active.append(expected_kind)
            try:
                yield 'guarded-model' if expected_kind == 'prepared_model' else 'guarded-field'
            finally:
                active.remove(expected_kind)
        def action(selected, **kwargs):
            self.assertEqual(selected, 'guarded-model')
            self.assertEqual(set(active), {'prepared_model', 'field_bundle'})
            self.assertEqual(kwargs['compensated_basis'], basis)
            return 'complete-result'
        with patch('msplatform.execution.owner.current_managed_native_store', return_value={'store': store}), \
             patch('msplatform.execution.native_source_guard.guard_native_source', guard), \
             patch('msplatform.backends.simion.operations._solve_fields', side_effect=action):
            self.assertEqual(operations.solve_fields(model, numerics={}, context=context, compensated_basis=basis), 'complete-result')
            self.assertEqual(active, [])
            with self.assertRaisesRegex(ContractError, 'without other reuse'):
                operations.solve_fields(model, numerics={}, context=context, compensated_basis=basis, reuse_fields=field)
        with patch('msplatform.execution.owner.current_managed_native_store', return_value=None):
            with self.assertRaisesRegex(ContractError, 'managed native Store'):
                operations.solve_fields(model, numerics={}, context=context, compensated_basis=basis)

    def test_source_guards_outlive_recomputed_fit_and_exact_model_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            field_ref = {'manifest': {'path': str(root/'field.json'), 'bytes': 4, 'sha256': 'A'*64}, 'product_id': 'fields'}
            axis_ref = {'manifest': {'path': str(root/'axis.json'), 'bytes': 5, 'sha256': 'B'*64}, 'product_id': 'axis'}
            fit = {'fit': {'regularization': 0.1}, 'values': [1.0, 2.0]}
            original_doc = {'model_identity_sha256': 'ORIGINAL', 'geometry': {'frontend_geometry': {'tof_instance_id': 'tof'}}}
            original_model = SimpleNamespace(document=original_doc)
            model_path = root/'model.json'; model_path.write_text('{}', encoding='utf8')
            field = SimpleNamespace(reference=field_ref, data_path=lambda _: model_path)
            binding = {'field_reference': field_ref, 'model_identity_sha256': 'ORIGINAL',
                       'downstream_identity': {}, 'grid': {}, 'frame_id': 'world'}
            axis = SimpleNamespace(reference=axis_ref, metadata={'binding': binding})
            provenance = {'original_resolved_recipe': {'recipe_id': 'ORIGINAL_RECIPE'},
                'original_recipe_id': 'ORIGINAL_RECIPE', 'original_model_identity_sha256': 'ORIGINAL',
                'axis_samples_reference': axis_ref, 'original_field_reference': field_ref,
                'instance_id': 'tof', 'fit': fit}
            recipe = {'resource_snapshots': {'compensation_provenance.json':
                {'bytes_base64': base64.b64encode(json.dumps(provenance).encode()).decode()}}}
            active = []
            store = object()
            context = SimpleNamespace(workspace=root)
            @contextmanager
            def guard(reference, *, expected_kind, expected_artifact_root, artifact_store, asset_ids):
                self.assertIs(artifact_store, store)
                self.assertEqual(expected_artifact_root, root/'artifacts')
                active.append(expected_kind)
                asset_ids.add('axis-asset' if expected_kind == 'axis_response_samples' else 'field-asset')
                try:
                    yield axis if expected_kind == 'axis_response_samples' else field
                finally:
                    active.remove(expected_kind)
            with patch('msplatform.execution.native_source_guard.guard_native_source', guard), \
                 patch('msplatform.workflows.native_tracing.validate_recipe', side_effect=lambda value: value), \
                 patch('msplatform.workflows.native_tracing.compile_simion_model', return_value=original_model), \
                 patch('msplatform.backends.simion.artifacts.CompiledPreparedModel', return_value=original_model), \
                 patch('msplatform.backends.simion.reflectron_response_binding.fit_sampled_axis', return_value=fit), \
                 patch('msplatform.backends.simion.reflectron_response_binding.plan_compensated_reflectron') as plan, \
                 patch('msplatform.workflows.native_tracing._native_owner_evidence', return_value={'kind': 'protected_external_native_source'}):
                with ExitStack() as stack:
                    result = _guard_compensation_sources(recipe, stack=stack, context=context,
                                                         artifact_store=store, compensated_model=object())
                    self.assertEqual(set(active), {'axis_response_samples', 'field_bundle'})
                    self.assertEqual(result['declared']['fit'], fit)
                    self.assertEqual(result['source_asset_ids'], ['axis-asset', 'field-asset'])
                    plan.assert_called_once()
                self.assertEqual(active, [])
                provenance['fit'] = {'fit': {'regularization': 0.1}, 'values': [9.0, 2.0]}
                recipe['resource_snapshots']['compensation_provenance.json']['bytes_base64'] = base64.b64encode(json.dumps(provenance).encode()).decode()
                plan.reset_mock()
                with ExitStack() as stack, self.assertRaisesRegex(ValueError, 'fit differs'):
                    _guard_compensation_sources(recipe, stack=stack, context=context,
                                                artifact_store=store, compensated_model=object())
                self.assertEqual(active, [])
                plan.assert_not_called()
