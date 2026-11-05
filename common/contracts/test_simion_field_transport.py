"""Real public example field identity across the worker's persisted JSON boundary."""
import copy
from importlib.resources import files
import json
from pathlib import Path
import unittest

from msplatform import api
from msplatform.backends.simion.model import compile_prepared_model, project_resolved_drive, require_prepared_model
from msplatform.backends.simion.native_plans import plan_solve_fields, operating_member_identity
from msplatform.backends.simion.pa_family_cache import canonical_pa_family_cache_key
from msplatform.execution.clock_authority import validate_clock_authority


class FieldTransportTests(unittest.TestCase):
    def test_public_example_native_labels_keep_exact_cache_key_after_worker_json_roundtrip(self):
        case = api.load_example("rf_oatof_functional_v1")
        components = {name:api.resolve_component(request) for name,request in case.component_requests.items()}
        assembly = api.compile_assembly(case.recipe, components)
        compiled = api.compile_geometry(assembly, backend="simion", numerics=case.geometry_numerics)
        selected = {name:compiled.components_resolved[name]
                    for name in compiled.frontend_geometry["composition_plan"]["scope"]["instance_ids"]}
        root = Path(str(files("msplatform.examples")))
        authority = validate_clock_authority(root/"instrument_clock_authority_v1.json", root)
        clock = dict(clock_epoch_id=authority["clock_epoch_id"], authority_sha256=authority["authority_sha256"],
                     **case.drive["clock"])
        drive = project_resolved_drive(compiled, selected, pulse=case.drive["pulse"], clock=clock)
        model = compile_prepared_model(compiled, selected, drive=drive, physics=case.physics)
        require_prepared_model(model)
        domains = copy.deepcopy(case.geometry_numerics["frontend_domains"])
        for domain in domains.values():
            domain["refine_convergence_v"] = dict(carrier_off=.001, rf_reference=.001, pulse_delta=.001)
        plan = plan_solve_fields(model, numerics=dict(frontend_domains=domains, rf_reference_voltage_v=10000.))
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
