"""Real public example field identity across the worker's persisted JSON boundary."""
import copy
import json
import unittest

from msplatform.backends.simion.model import require_prepared_model
from msplatform.backends.simion.native_plans import plan_solve_fields, operating_member_identity
from msplatform.backends.simion.pa_family_cache import canonical_pa_family_cache_key


class FieldTransportTests(unittest.TestCase):
    def test_public_example_native_labels_keep_exact_cache_key_after_worker_json_roundtrip(self):
        from tests.contracts.test_simion_field_action import public_case
        model, numerical, _, _ = public_case()
        require_prepared_model(model)
        numerical = copy.deepcopy(numerical)
        numerical.pop('downstream_convergence_v')
        plan = plan_solve_fields(model, numerics=numerical)
        transported = json.loads(json.dumps(plan))
        tool = dict(simion_identity=dict(release="SIMION 2020", executable_bytes=1, executable_sha256="A"*64),
                    builder_identity=dict(operating_builder="B"*64, exporter="C"*64))
        labels = set()
        for point in plan["field_design"]["working_points"]:
            labels.update(int(label) for label in point["electrode_voltages_v"])
            self.assertTrue(all(type(label) is str for label in point["electrode_voltages_v"]))
        self.assertGreaterEqual(max(labels), 25)
        self.assertIn(10, labels)
        for member in plan["ordered_members"]:
            # Fine members require a real parent generation; this pure identity
            # test exercises the selected example's parent members only.
            if member["domain_id"] != "parent":
                continue
            with self.subTest(member=member["member_id"]):
                before = operating_member_identity(plan, domain_id="parent", member_id=member["member_id"], tool_identity=tool)
                after = operating_member_identity(transported, domain_id="parent", member_id=member["member_id"], tool_identity=tool)
                self.assertEqual(before, after)
                self.assertEqual(canonical_pa_family_cache_key(before), canonical_pa_family_cache_key(after))
