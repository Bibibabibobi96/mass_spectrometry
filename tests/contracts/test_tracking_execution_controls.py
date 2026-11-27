"""Engineering controls are explicit and participate only where applicable."""
import unittest
from unittest.mock import patch

from msplatform.workflows.native_tracing import _trace_cache_key
from msplatform.workflows.tracing import run_recipe


class TrackingExecutionControlsTests(unittest.TestCase):
    def test_partition_and_recovery_change_trace_key_but_dispatch_does_not(self):
        base = dict(field_key="field", particles={"rows": []}, propagation={}, observations={}, numerics={},
                    recipe={"gas_environment": {"status": "vacuum"}, "gas_data": {}, "resource_snapshots": {}},
                    implementation={})
        original = _trace_cache_key(**base)
        self.assertEqual(original, _trace_cache_key(**base, tracking_execution={"dispatch_profiles": [{"name": "a"}]}))
        first = _trace_cache_key(**base, tracking_execution={"unit_size": 2, "dispatch_profiles": [{"name": "a"}]})
        second = _trace_cache_key(**base, tracking_execution={"unit_size": 2, "dispatch_profiles": [{"name": "b"}]})
        self.assertEqual(first, second)
        self.assertNotEqual(first, original)
        gas_changed = dict(base)
        gas_changed["recipe"] = {"gas_environment": {"status": "hs1"},
                                 "gas_data": {"seed": 41}, "resource_snapshots": {}}
        self.assertNotEqual(first, _trace_cache_key(**gas_changed, tracking_execution={"unit_size": 2}))
        previous = {"path": "C:/source/run_manifest.json", "bytes": 12, "sha256": "A" * 64}
        self.assertNotEqual(first, _trace_cache_key(**base, tracking_execution={"unit_size": 2, "recovery_reference": previous}))

    def test_focus_source_location_is_not_scientific_identity(self):
        from copy import deepcopy
        base = dict(field_key="field", particles={"rows": []}, propagation={},
                    observations={"oa_focus_authority": {"campaign": {"path": "first", "bytes": 10, "sha256": "A" * 64},
                                  "component_contract": {"path": "one", "bytes": 20, "sha256": "B" * 64}}},
                    numerics={}, recipe={"gas_environment": {"status": "vacuum"}, "gas_data": {}, "resource_snapshots": {}},
                    implementation={})
        changed = deepcopy(base)
        changed["observations"]["oa_focus_authority"]["campaign"]["path"] = "second"
        changed["observations"]["oa_focus_authority"]["component_contract"]["path"] = "two"
        self.assertEqual(_trace_cache_key(**base), _trace_cache_key(**changed))
        changed["observations"]["oa_focus_authority"]["campaign"]["sha256"] = "C" * 64
        self.assertNotEqual(_trace_cache_key(**base), _trace_cache_key(**changed))

    def test_reference_recipe_rejects_controls(self):
        class Reference:
            def to_dict(self):
                return {"schema_version": 3}
        with patch("msplatform.workflows.tracing.load_recipe", return_value=Reference()):
            with self.assertRaisesRegex(ValueError, "native SIMION"):
                run_recipe("unused", artifact_root="unused", tracking_execution={"unit_size": 2})
