"""Joint public geometry routing and source-free owner plans."""
from __future__ import annotations

import copy
import unittest
import tempfile
from types import SimpleNamespace
from pathlib import Path

from integrations.tests.test_ip_compiler import IpCompilerTests
from msplatform.backends.simion import operations
from msplatform.backends.simion.native_plans import plan_geometry_build
from msplatform.backends.simion.resources import STRUCTURAL_SEEDS


class JointGeometryPlanTests(unittest.TestCase):
    def setUp(self):
        fixture = IpCompilerTests()
        fixture.setUp()
        self.fixture = fixture
        self.compiled = operations.compile_geometry(fixture.assembly, numerics=fixture.numerics)
        self.root = (Path.cwd() / "inert-joint-geometry-plan").resolve()
        size, sha = STRUCTURAL_SEEDS[1]
        self.seed = dict(path=str(self.root / "seed.iob"), bytes=size, sha256=sha)

    def plan(self, compiled):
        return plan_geometry_build(compiled, run_directory=self.root, seed_record=self.seed,
                                   native_path_resource=self.root / "native_run_path.lua")

    def test_public_compile_and_actual_owner_plan_have_real_one_slot_assets(self):
        self.assertEqual(self.compiled.frontend_geometry["role"], "simion_rf_ip_geometry")
        self.assertEqual(set(self.compiled.frontend_gems), {"parent"})
        samples = self.compiled.frontend_geometry["raw_physical_samples"]["parent"]
        expected = {v for m in self.compiled.frontend_geometry["electrode_bindings"].values() for v in m.values()}
        self.assertEqual({r["electrode_id"] for r in samples if r.get("electrode_id", 0) > 0}, expected)
        self.assertTrue(any(r.get("metal") is False for r in samples))
        self.assertEqual([r["label"] for r in samples if r.get("electrode_id") == 0], ["declared_grounded_pa_face"])
        plan = self.plan(self.compiled)
        self.assertEqual([o["operation_id"] for o in plan.operations], ["geometry_parent", "build_geometry", "verify_geometry"])
        spec = plan.materializations[str(self.root / "inputs/geometry_iob.lua")]
        self.assertIn("rf_ip_geometry_iob_build", spec)
        self.assertIn("1_instance_seed.iob", spec)
        self.assertIn("RF_IP_GEOMETRY_IOB=PASS", plan.operations[1]["success_marker"])
        self.assertTrue(any(path.endswith("parent.pa-surf") for path in plan.declared_outputs))
        self.assertTrue(any(path.endswith("parent_surface.csv") for path in plan.declared_outputs))

    def test_public_build_uses_existing_one_slot_owner(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            context = SimpleNamespace(tools={"simion": Path(__file__).resolve()}, execution_root=Path(directory))
            stage = dict(limits={"transient_run_directory_bytes":1}, artifact_retention={})
            with patch("msplatform.execution.stage_policy.read_stage_policy",return_value=(stage,{})), \
                 patch("msplatform.execution.owner.run_managed_stage",return_value={"manifest":{}}) as owner, \
                 patch("msplatform.results.artifacts.open_artifact",return_value="OPENED"):
                self.assertEqual(operations.build_geometry(self.compiled,context=context),"OPENED")
            request = owner.call_args.kwargs
            self.assertEqual(request["expected_operation_ids"],("geometry_parent","build_geometry","verify_geometry"))
            self.assertEqual(Path(request["action"].keywords["seed_record"]["path"]).name,"1_instance_seed.iob")
            self.assertEqual(request["payload"]["compiled_geometry"]["frontend_geometry"]["role"],"simion_rf_ip_geometry")

    def test_actual_geometry_owner_materializes_declared_assets_with_inert_process(self):
        from msplatform.backends.simion.geometry_execution import execute_geometry
        from msplatform.backends.simion.resources import structural_seed_path
        from msplatform.io.manifest_records import file_record, verify_record

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            seed = file_record(structural_seed_path(1), "required_evidence")
            plan = plan_geometry_build(self.compiled, run_directory=root, seed_record=seed,
                native_path_resource=root / "inputs/native_sources/native_run_path.lua")
            class Session:
                run_dir = artifact_run_dir = root
                input_dir, log_dir = root / "inputs", root / "logs"
                context = SimpleNamespace(tools={"simion": Path(__file__).resolve()})
                expected_operation_ids = tuple(row["operation_id"] for row in plan.operations)
                calls = []
                def canonical_path(self, path): return Path(path).resolve()
                def declare_file(self, path, role): pass
                def add_input(self, name, record): verify_record(name, record)
                def run_process(self, operation_id, **options):
                    self.calls.append(operation_id)
                    operation = plan.operations[len(self.calls)-1]
                    self.log_dir.mkdir(parents=True,exist_ok=True)
                    (self.log_dir / f"operation_{len(self.calls):04d}.stdout.log").write_text(operation["success_marker"])
                    for path in operation["outputs"]: Path(path).write_bytes(b"INERT TEST OUTPUT")
            session = Session()
            result = execute_geometry(session, compiled=self.compiled, seed_record=seed, limits={})
            self.assertEqual(session.calls, list(session.expected_operation_ids))
            product = result["manifest_extra_fields"]["products"]["geometry"]
            self.assertEqual(product["metadata"]["field_status"], "not_solved")
            self.assertEqual(product["metadata"]["source_status"], "not_requested")
            self.assertEqual(product["metadata"]["sampled_particles"], 0)
            self.assertEqual(set(product["metadata"]["native_assets"]), {"parent"})
            for record in product["data"].values(): verify_record("inert geometry product", record)

    def test_missing_and_undeclared_samples_are_refused(self):
        for change in (lambda rows: rows.clear(),
                       lambda rows: rows.append(dict(label="invented", gu=[1,1,1], electrode_id=999, metal=True)),
                       lambda rows: rows.append(dict(label="bad_zero", gu=[0,0,0], electrode_id=0, metal=True))):
            with self.subTest(change=change):
                value = copy.deepcopy(self.compiled)
                change(value.frontend_geometry["raw_physical_samples"]["parent"])
                with self.assertRaises(ValueError):
                    self.plan(value)


class OaMrJointPlanTests(unittest.TestCase):
    def test_actual_three_asset_public_geometry_and_owner_plan(self):
        from msplatform.assembly.factory import assemble
        from msplatform.components.catalog import resolve_component
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_mr_provider_trial_transport import _plans
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.test_support.mr_geometry_inputs import geometry_authority

        _, plan, contract = _plans()
        authority = geometry_authority(contract)
        oa = resolve_component(dict(provider_id="orthogonal_accelerator", geometry_profile_id=authority["geometry_profile_id"],
            design=dict(requirements=authority["accelerator_requirements"], geometry_profile=authority["geometry_profile"])))
        mr = resolve_component(dict(provider_id="parallel_mirror_dual_stripe_mr_tof", geometry_profile_id=authority["geometry_profile_id"],
            design=dict(contract=contract, accelerator_requirements=authority["accelerator_requirements"], geometry_profile=authority["geometry_profile"])))
        components = {name: oa if row["project_id"] == "orthogonal_accelerator" else mr for name,row in plan["components"].items()}
        assembly = assemble(plan["recipe"], components)
        domain = dict(cell_mm_xyz=dict.fromkeys("xyz", .1), pa_bounds_mm={a+s: (-1000. if s=="_min" else 1000.) for a in "xyz" for s in ("_min","_max")})
        compiled = operations.compile_geometry(assembly, numerics=dict(domains=dict.fromkeys(("oa","analyzer","detector"), domain)))
        self.assertEqual(compiled.frontend_geometry["role"], "simion_oa_mr_complete_geometry")
        self.assertEqual(len(compiled.frontend_gems), 3)
        self.assertEqual(set(compiled.frontend_gems), set(compiled.frontend_geometry["raw_physical_samples"]))
        root = (Path.cwd()/"inert-oa-mr-plan").resolve()
        size, sha = STRUCTURAL_SEEDS[3]
        seed = dict(path=str(root/"seed.iob"), bytes=size, sha256=sha)
        native_plan = plan_geometry_build(compiled, run_directory=root, seed_record=seed, native_path_resource=root/"native_run_path.lua")
        self.assertEqual(len(native_plan.operations), 5)
        spec = native_plan.materializations[str(root/"inputs/geometry_iob.lua")]
        self.assertIn("oa_mr_geometry_iob_build", spec)
        self.assertIn("3_instance_seed.iob", spec)
        for asset in compiled.frontend_gems:
            self.assertTrue(any(asset+".pa#" in path for path in native_plan.declared_outputs))
            self.assertTrue(any(asset+"_surface.csv" in path for path in native_plan.declared_outputs))
        invalid=copy.deepcopy(compiled)
        del invalid.frontend_geometry["raw_physical_samples"][next(iter(compiled.frontend_gems))]
        with self.assertRaisesRegex(ValueError,"samples"):
            plan_geometry_build(invalid, run_directory=root, seed_record=seed, native_path_resource=root/"native_run_path.lua")

if __name__ == "__main__":
    unittest.main()
