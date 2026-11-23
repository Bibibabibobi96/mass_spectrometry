"""Connected registered components through the public sampled consumer chain."""
import copy
import os
import unittest
from unittest.mock import patch

from tests.contracts import test_generic_scalar_tracking_managed as managed
from tests.contracts.test_support import generic_scalar_renamed as fixture
from msplatform import assembly, components
from msplatform.backends.simion.operations import compile_geometry
from msplatform.contracts.machine_contracts import ContractError


@unittest.skipUnless(os.name == "nt", "Windows process guard required")
class ConnectedConsumerTests(unittest.TestCase):
    def test_registered_connected_parameter_through_public_chain(self):
        made = []

        def make_fixture(*args, **kwargs):
            case = fixture.GenericScalarTests(*args, **kwargs)
            case.connected_case = True
            made.append(case)
            return case

        parent = managed.GenericScalarTrackingManagedTests(methodName="runTest")
        self.addCleanup(parent.doCleanups)
        # Replace only the test fixture factory; public production dispatch remains real.
        with patch.object(managed.fixture, "GenericScalarTests", side_effect=make_fixture):
            parent.test_public_sampled_tracking()
        self.assertEqual(len(made), 1)
        case = made[0]
        recipe = case.assembly.composition_plan["recipe"]
        self.assertEqual([item["instance_id"] for item in recipe["instances"]], ["a_second", "z_first"])
        self.assertEqual(recipe["connections"][0]["gap_mm"], 2)
        self.assertEqual(case.assembly.components_resolved["a_second"]["width_mm"], 4)
        member = next(row for row in case.projection["members"] if row["instance_id"] == "a_second")
        self.assertEqual(member["shape"]["parts"][0]["size_mm"], [4, 4, 4])
        self.assertEqual(member["transform"]["translation_mm"], [0, 0, 5])

        first = components.resolve_component({"provider_id": "toy_registered", "design": {"width_mm": 2}})
        second = components.resolve_component({"provider_id": "toy_other", "design": {"width_mm": 4}})
        bad = copy.deepcopy(recipe)
        bad["connections"][0]["downstream"]["port_id"] = "missing"
        with self.assertRaisesRegex(ContractError, "omits mechanical port"):
            assembly.assemble(bad, {"z_first": first, "a_second": second})
        geometry = case.model.document["geometry"]["frontend_geometry"]
        numerics = dict(representation="neutral_world_collision", domain=geometry["domain"],
                        pitch_mm=geometry["pitch_mm"], boundary="grounded_faces",
                        metal_witnesses=geometry["metal_witnesses"], void_witnesses=geometry["void_witnesses"])
        with self.assertRaisesRegex(ValueError, "native_zero_neumann"):
            compile_geometry(case.assembly, numerics=numerics)
