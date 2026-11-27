"""Admission of SDS recording semantics, without a native solver."""
from copy import deepcopy
from decimal import Decimal
import unittest

from msplatform.recipes.native import CONSTANTS, _options


class SdsOptionsTests(unittest.TestCase):
    def test_callback_samples_are_explicit_and_not_exact_observation_times(self):
        options = {"schema_version": 2, "label": "sds", "constants_version": CONSTANTS["version"],
                   "gas_environment": {"status": "sds", "path": "sds.json", "sha256": "A" * 64},
                   "field_source": {"kind": "simion_native"}, "particle_tracer": "simion",
                   "field_assembly_strategy": "native_domain_composition",
                   "particle_field_coupling": "external_given_field",
                   "recording": {"mode": "actual_callback_samples", "sample_interval_us": Decimal("0.5"),
                                 "end_time_us": Decimal("10")}}
        _options(options)
        exact = deepcopy(options)
        exact["recording"] = {"mode": "observation_times", "observation_times_us": [0, 1]}
        with self.assertRaisesRegex(ValueError, "actual callback"):
            _options(exact)
        vacuum = deepcopy(options)
        vacuum["gas_environment"] = {"status": "vacuum"}
        with self.assertRaisesRegex(ValueError, "SIMION SDS"):
            _options(vacuum)
        invalid = deepcopy(options)
        invalid["recording"]["sample_interval_us"] = Decimal("0")
        with self.assertRaisesRegex(ValueError, "sample_interval_us"):
            _options(invalid)


    def test_materializes_only_verified_frozen_inputs(self):
        import tempfile
        from pathlib import Path
        from msplatform.recipes import load_recipe
        from msplatform.workflows.native_tracing import _materialize_sds_inputs
        from tests.contracts.test_support.dual_cone_native_recipe import write_dual_cone_recipe_fixture

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            recipe = load_recipe(write_dual_cone_recipe_fixture(root / "author")).to_dict()
            result = _materialize_sds_inputs(recipe, root / "frozen")
            self.assertEqual(set(result["identities"]), {path.name for path in result["sds_dir"].iterdir()})
            self.assertTrue(result["source_path"].is_file())
            self.assertTrue(result["numerics_path"].is_file())
            self.assertTrue(result["environment_bytes"])
            recipe["resource_snapshots"]["sds"]["sds_environment.json"]["sha256"] = "0" * 64
            with self.assertRaises(ValueError):
                _materialize_sds_inputs(recipe, root / "tampered")
            self.assertFalse((root / "tampered").exists())


    def test_sds_planning_requires_explicit_source_frame_registration(self):
        import tempfile
        from pathlib import Path
        from msplatform.recipes import load_recipe
        from msplatform.workflows.native_tracing import _assembly
        from msplatform.workflows.native_tracing import compile_sds_inputs
        from tests.contracts.test_support.dual_cone_native_recipe import write_dual_cone_recipe_fixture

        with tempfile.TemporaryDirectory() as temporary:
            recipe = load_recipe(write_dual_cone_recipe_fixture(Path(temporary))).to_dict()
            instrument = _assembly(recipe)
            recipe["study"]["document"]["model_input_sources"].pop("source_to_device", None)
            with self.assertRaisesRegex(ValueError, "source.*transform"):
                compile_sds_inputs(recipe, instrument)
            # Synthetic frame identity demonstrates contract routing only; it is not measured registration.
            recipe["study"]["document"]["model_input_sources"]["source_to_device"] = {
                "schema_version": 1, "role": "rigid_transform", "from_frame_id": "multipole_cartesian_z_axis_v1",
                "to_frame_id": "dual_cone_interface_local", "rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                "translation_mm": [0, 0, 0]}
            result = compile_sds_inputs(recipe, instrument)
            self.assertEqual(result["source_frame_id"], "dual_cone_interface_local")


    def test_sds_stage_orchestration_uses_guarded_gas_and_all_four_existing_owners(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from msplatform.recipes import load_recipe
        from msplatform.workflows.native_tracing import _assembly, _materialize_sds_inputs, _run_sds_stages
        from tests.contracts.test_support.dual_cone_native_recipe import write_dual_cone_recipe_fixture

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            recipe = load_recipe(write_dual_cone_recipe_fixture(root / "author")).to_dict()
            recipe["study"]["document"]["model_input_sources"]["source_to_device"] = {
                "schema_version": 1, "role": "rigid_transform", "from_frame_id": "multipole_cartesian_z_axis_v1",
                "to_frame_id": "dual_cone_interface_local", "rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                "translation_mm": [0, 0, 0]}
            inputs = _materialize_sds_inputs(recipe, root / "frozen")
            gas = SimpleNamespace(reference={"manifest": {"sha256": "A" * 64}, "product_id": "gas_field"})
            context = SimpleNamespace(workspace=root)
            values = [object(), object(), object(), object()]
            calls = []
            def reference(store, stack, key, produce, **kwargs):
                calls.append(kwargs["kind"])
                return produce(), {"asset_id": None, "task_key": key}
            with patch("msplatform.workflows.native_tracing._native_reference", side_effect=reference), \
                    patch("msplatform.backends.simion.dual_cone_transport.admit_sds_gas_field",
                          return_value=(None, None, None, SimpleNamespace(to_dict=lambda: {"typed": True}))), \
                    patch("msplatform.backends.simion.dual_cone_stages.build_geometry", return_value=values[0]), \
                    patch("msplatform.backends.simion.dual_cone_stages.prepare_model", return_value=values[1]), \
                    patch("msplatform.backends.simion.dual_cone_stages.solve_fields", return_value=values[2]), \
                    patch("msplatform.backends.simion.dual_cone_stages.track_fields", return_value=values[3]) as track:
                result, receipts = _run_sds_stages(recipe, _assembly(recipe), inputs, gas, store=None, stack=None,
                    context=context, claims=[], calls=[], account=lambda _: None, invoke=lambda action: action(),
                    implementation={"scope": "inert fixture"}, clock_authority_reference={})
                changed = deepcopy(recipe)
                changed["recording"]["sample_interval_us"] *= 2
                _, changed_receipts = _run_sds_stages(changed, _assembly(changed), inputs, gas, store=None, stack=None,
                    context=context, claims=[], calls=[], account=lambda _: None, invoke=lambda action: action(),
                    implementation={"scope": "inert fixture"}, clock_authority_reference={})
            self.assertIs(result, values[3])
            self.assertEqual(calls, ["geometry_artifact", "prepared_model", "field_bundle", "trajectory_result"] * 2)
            for name in ("geometry", "model", "fields"):
                self.assertEqual(receipts[name]["task_key"], changed_receipts[name]["task_key"])
            self.assertNotEqual(receipts["track"]["task_key"], changed_receipts["track"]["task_key"])
            self.assertEqual(set(receipts), {"geometry", "model", "fields", "track"})
            self.assertEqual(track.call_args.kwargs["expected_gas_environment"], {"typed": True})
            self.assertEqual(track.call_args.kwargs["gas_field_reference"], gas.reference)


    def test_sds_publishes_and_cold_reads_through_actual_store_with_inert_trajectory(self):
        from contextlib import contextmanager
        import sys
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        import numpy as np
        from msplatform.physics import CONSTANTS as PHYSICAL
        from msplatform.recipes import load_recipe
        from msplatform.results.model import TraceResult
        from msplatform.results.detector_observation import detector_observation
        from msplatform.results.particle_data import write_particle_data
        from msplatform.storage import ArtifactStore
        from msplatform.workflows.native_tracing import _execute_sds, _realizations, _particle_document
        from msplatform.workflows.tracing import inspect_results
        from tests.contracts.test_support.dual_cone_native_recipe import write_dual_cone_recipe_fixture

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            author = write_dual_cone_recipe_fixture(root / "author")
            recipe = load_recipe(author).to_dict()
            recipe["study"]["document"]["model_input_sources"]["source_to_device"] = {
                "schema_version": 1, "role": "rigid_transform", "from_frame_id": "multipole_cartesian_z_axis_v1",
                "to_frame_id": "dual_cone_interface_local", "rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                "translation_mm": [0, 0, 0]}
            packet = _particle_document(_realizations(recipe["study"]["document"]["release"])[0])
            initial, terminal = [], []
            for row in packet["rows"]:
                position = [row["position_" + axis + "_mm"] / 1000 for axis in "xyz"]
                velocity = [row["velocity_" + axis + "_m_s"] for axis in "xyz"]
                initial.append(dict(particle_id=row["particle_id"], species_id=row["species_id"], position_m=position,
                    velocity_m_s=velocity, time_s=0., mass_kg=row["mass_amu"] * PHYSICAL["atomic_mass_constant_kg"],
                    charge_state=row["charge_state"], charge_c=row["charge_state"] * PHYSICAL["elementary_charge_c"],
                    weight=1., parent_particle_id=None, lineage_status="primary_birth"))
                terminal.append(dict(particle_id=row["particle_id"], species_id=row["species_id"], position_m=position,
                    velocity_m_s=velocity, time_s=0., physical_outcome="unknown", stop_reason="time_limit", component_id=None,
                    electrode_id=None, surface_id=None, attribution_method="unavailable", attribution_status="unavailable",
                    started=True, backend_version="inert", native_termination_code=None, native_entity_id=None, detail=None))
            arrays = dict(particle_id=np.empty(0, dtype="int64"), time_s=np.empty(0),
                          position_m=np.empty((0, 3)), velocity_m_s=np.empty((0, 3)))
            data = TraceResult(initial, terminal, [], arrays, "succeeded",
                               dict(status="complete", detector_observation=detector_observation("not_requested", [row["particle_id"] for row in initial], reason="not requested")))
            trajectory_dir = root / "trajectory"
            trajectory_dir.mkdir()
            write_particle_data(trajectory_dir, data, metadata={"schema_version": 2, "initial_state_basis": "native_birth_verified",
                "frame_id": "dual_cone_interface_local", "clock": {"basis": "experiment_relative", "unit": "s", **packet["clock"]},
                "species": recipe["species"]})
            trajectory = SimpleNamespace(data_path=lambda key: trajectory_dir / "execution.json")
            gas = SimpleNamespace(reference={"manifest": {"path": str(root / "gas"), "sha256": "A" * 64}, "product_id": "gas_field"})
            @contextmanager
            def guarded(*args, **kwargs):
                yield gas
            workspace = root / "workspace"
            workspace.mkdir()
            context = SimpleNamespace(workspace=workspace, tools={"simion": Path(sys.executable)})
            store = ArtifactStore(root / "store")
            run_id, work = store.begin_run()
            (work / "author.toml").write_bytes(author.read_bytes())
            with patch("msplatform.execution.native_source_guard.guard_native_source", guarded), \
                    patch("msplatform.workflows.native_tracing._native_owner_evidence", return_value={"kind": "inert"}), \
                    patch("msplatform.workflows.native_tracing._run_sds_stages", return_value=(trajectory, {})):
                with store.run_writer(run_id), store.reserve(100_000_000) as reservation:
                    store.mark_running(run_id)
                    _execute_sds(store, recipe, context, run_id, work, reservation, None, 100_000_000)
            self.assertEqual(inspect_results(run_id, artifact_root=store.root)["run_state"]["execution_status"], "succeeded")


    def test_sds_compilation_preflight_does_not_claim_unread_cfd(self):
        import tempfile
        from pathlib import Path
        from msplatform.recipes import load_recipe
        from msplatform.workflows.native_tracing import _assembly, _preflight_sds
        from tests.contracts.test_support.dual_cone_native_recipe import write_dual_cone_recipe_fixture

        with tempfile.TemporaryDirectory() as temporary:
            recipe = load_recipe(write_dual_cone_recipe_fixture(Path(temporary))).to_dict()
            report = _preflight_sds(recipe, _assembly(recipe), context=None, artifact_store=None)
            self.assertEqual(report["gas_source_admission"], "not_checked_without_context")
            self.assertFalse(report["native_verified"])
            self.assertIsNone(report["host_available"])


    def test_sds_identity_ignores_only_request_location(self):
        import tempfile
        from pathlib import Path
        from msplatform.recipes import load_recipe
        from tests.contracts.test_support.dual_cone_native_recipe import write_dual_cone_recipe_fixture

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            author = write_dual_cone_recipe_fixture(root)
            original = load_recipe(author).to_dict()
            (root / "renamed.json").write_bytes((root / "sds_request.json").read_bytes())
            other = root / "other.toml"
            other.write_text(author.read_text(encoding="utf-8").replace('path = "sds_request.json"',
                             'path = "renamed.json"'), encoding="utf-8")
            self.assertEqual(load_recipe(other).to_dict()["recipe_id"], original["recipe_id"])


if __name__ == "__main__":
    unittest.main()
