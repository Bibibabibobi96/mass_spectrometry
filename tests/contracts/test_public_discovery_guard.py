"""Published discovery pilots stay protected through the selected owner."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from msplatform.backends.simion import operations
from msplatform.contracts.machine_contracts import ContractError


class PublicDiscoveryGuardTests(unittest.TestCase):
    def test_selected_pilot_is_guarded_until_owner_returns(self):
        context = SimpleNamespace(workspace=Path('C:/fixture'))
        pilot = {'manifest': {'path': 'pilot'}, 'product_id': 'trajectory'}
        observations = {'pulse_discovery': {'phase': 'selected', 'author': {}, 'pilot': pilot}}
        active = []
        store = object()
        @contextmanager
        def guard(reference, *, expected_kind, expected_artifact_root, artifact_store):
            self.assertEqual(reference, pilot)
            self.assertEqual(expected_kind, 'trajectory_result')
            self.assertEqual(expected_artifact_root, context.workspace/'artifacts')
            self.assertIs(artifact_store, store)
            active.append(True)
            try:
                yield object()
            finally:
                active.pop()
        def action(*args, **kwargs):
            self.assertTrue(active)
            self.assertEqual(kwargs['observations'], observations)
            return 'complete'
        with patch('msplatform.execution.owner.current_managed_native_store', return_value={'store': store}), \
             patch('msplatform.execution.native_source_guard.guard_native_source', guard), \
             patch('msplatform.backends.simion.operations._track', side_effect=action):
            self.assertEqual(operations.track({}, {}, propagation={}, observations=observations,
                                              numerics={}, context=context), 'complete')
        self.assertEqual(active, [])
        with patch('msplatform.execution.owner.current_managed_native_store', return_value=None):
            with self.assertRaisesRegex(ContractError, 'managed native Store'):
                operations.track({}, {}, propagation={}, observations=observations, numerics={}, context=context)
