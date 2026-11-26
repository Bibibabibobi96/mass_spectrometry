"""Split OFF/ON scalar identity and workpoint admission without native execution."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from msplatform import assembly, components
from msplatform.backends import simion
from msplatform.backends.comsol.assembly_geometry import project_assembly_geometry
from msplatform.backends.simion.model import compile_prepared_model
from msplatform.backends.simion.split_scalar_binding import _workpoints, resolve_split_scalar_basis
from msplatform.backends.simion.scalar_sample_binding import _co_resident_sources
from msplatform.execution.terminal_publication import publish_terminal_state
from msplatform.io.manifest_records import file_record
from msplatform.recipes import load_recipe
from msplatform.results.artifacts import open_artifact
from tests.contracts import test_sfi_scalar_binding as fixtures


class SplitScalarBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.helper = fixtures.SfiScalarAdmissionTests()
        self.helper.root = Path(self.tmp.name)
        root = Path(__file__).resolve().parents[2] / "src/msplatform/examples"
        result = load_recipe(root / "oa_split_tof_native_small_v1.toml").to_dict()
        study = result["study"]["document"]
        parts = {k: components.resolve_component(v) for k, v in study["component_requests"].items()}
        instrument = assembly.assemble(study["recipe"], parts)
        compiled = simion.compile_geometry(instrument, numerics=study["numerics"]["geometry"])
        drive = copy.deepcopy(study["drive"])
        drive.pop("clock_authority")
        drive["clock"].update(study["release"]["clock"])
        self.model = compile_prepared_model(compiled, instrument.components_resolved, drive=drive, physics=study["physics"])
        self.helper.snapshot = dict(composition_plan=instrument.composition_plan,
                                    components_resolved=instrument.components_resolved,
                                    components_source=instrument.components_source)
        self.helper.projection = project_assembly_geometry(self.helper.snapshot,
            outer_box_mm={"min": [-1000, -1000, -1000], "max": [1000, 1000, 1000]})
        self.geometry = self.helper.make_geometry()
        self.vectors = _workpoints(drive)
        self.samples = {"off": "off", "on": "on"}
        self.requests = {name: {"group_voltages": [dict(instance_id=i, electrode_group_id=g, voltage_v=v)
                          for (i, g), v in vector.items()], "relative_permittivity": 1.,
                          "exterior": {"kind": "potential", "voltage_v": 0.},
                          "mesh": {"global_automatic_level": 9}, "study": {"kind": "stationary"}}
                         for name, vector in self.vectors.items()}
        self.grid = {"frame_id": "oatof_global", "origin_mm": [-1000]*3,
                     "pitch_mm": [1000]*3, "dimensions": [3]*3}

    def resolve(self):
        def verify(name, projection, *, check_workpoint, **kwargs):
            self.assertEqual(projection, self.helper.projection)
            check_workpoint(self.requests[name])
            return {"grid": copy.deepcopy(self.grid), "reference": name,
                    "field_solution_reference": {"manifest": {"bytes": 1, "sha256": "0"*64}}}
        with patch("msplatform.backends.simion.split_scalar_binding.verify_scalar_sample", side_effect=verify):
            return resolve_split_scalar_basis(model=self.model, geometry_artifact=self.geometry, samples=self.samples)

    def test_active_support_policy_requires_equipotential_v2(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from msplatform.backends.simion import scalar_sample_binding as binding
        self.helper.vectors=self.vectors
        reference=self.helper.make_sample('off')
        original = open_artifact(reference, expected_kind='scalar_field_samples')
        records = original.data_records
        authority = {'schema_version':1, 'role':'assembly_scalar_conductor_support',
                     **{key:records[key] for key in ('grid','projection','request','field_solution_manifest')}}
        support = self.helper.root/'support-v2.json'; support.write_text(json.dumps(authority),encoding='utf8')
        records['conductor_support'] = file_record(support)
        metadata = dict(original.metadata, conductor_support_policy='equipotential_dirichlet_solid_interiors_v2')
        locations = dict(original.data_locations, conductor_support=support)
        item = SimpleNamespace(metadata=metadata, producer=original.producer, reference=original.reference,
            product_id=original.product_id, manifest_location=original.manifest_location, data_records=records,
            data_locations=locations, data_path=lambda name:locations[name])
        with patch.object(binding,'open_artifact',return_value=item):
            result = binding.verify_scalar_sample({}, self.helper.projection, check_workpoint=lambda _:None)
            self.assertEqual(result['records']['conductor_support']['sha256'],records['conductor_support']['sha256'])
            metadata['conductor_support_policy']='unique_dirichlet_solid_interiors'
            with self.assertRaisesRegex(ValueError,'unsupported conductor support policy'):
                binding.verify_scalar_sample({}, self.helper.projection, check_workpoint=lambda _:None)

    def test_two_actual_workpoints_and_physical_geometry(self):
        result = self.resolve()
        self.assertEqual(set(result["bases"]), {"off", "on"})
        self.assertEqual(result["composition"], "off_plus_pulse_times_on_minus_off")
        self.assertEqual(result["clock"], self.model.document["drive"]["clock"])
        self.assertTrue(any(self.vectors["off"][key] != self.vectors["on"][key] for key in self.vectors["off"]))

    def test_rejects_wrong_workpoint_operator_and_world_coverage(self):
        for mutate in (
            lambda: self.requests["on"]["group_voltages"][0].__setitem__("voltage_v", 123.),
            lambda: self.requests["on"]["mesh"].__setitem__("global_automatic_level", 8),
            lambda: self.requests["off"]["exterior"].__setitem__("voltage_v", 1.),
            lambda: self.grid["origin_mm"].__setitem__(0, -999),
        ):
            with self.subTest(mutate=mutate):
                before = copy.deepcopy((self.requests, self.grid))
                mutate()
                with self.assertRaises(ValueError):
                    self.resolve()
                self.requests, self.grid = before

    def test_rejects_forged_geometry_source(self):
        snapshot = copy.deepcopy(self.helper.snapshot)
        snapshot["components_source"]["tof"]["geometry_mm"]["detector_radius"] += 1
        self.geometry = self.helper.publish("forged", "geometry_artifact", {"projection": self.helper.projection},
            {"backend": "comsol", "scope": "geometry_only", "native_reopen_verified": True},
            {"execution_request": {"role": "run_artifact_workflow_request", "payload": {
                "action": "build_comsol_geometry", "assembly": snapshot, "projection": self.helper.projection}}})
        with self.assertRaises(ValueError):
            self.resolve()

    def test_co_resident_cold_readback_requires_both_bound_workpoints(self):
        root = self.helper.root / "co"
        root.mkdir()
        off = dict(fixtures.SOLUTION)
        on = dict(fixtures.SOLUTION, study_tag="std2", solution_tag="sol2", dataset_tag="dset2", dataset_solution="sol2")
        keys = ["oa/repeller"]
        report = dict(operation="reopen", compute_calls=0, mesh_identity="mesh1", mesh_element_count=10,
                      maximum_mesh_elements=20, model_path=str(root / "model.json"), vacuum_domains=[1],
                      group_keys=keys, off_voltages_v=[0.], on_voltages_v=[2140.], off_solution=off, on_solution=on)
        records = {}
        def store(name, value):
            path = root / (name + ".json")
            path.write_text(json.dumps(value), encoding="utf-8")
            record = file_record(path)
            records[name] = record
            return record
        common = {key: store(key, report if key == "reopen_pulse_basis" else
                      dict(report, operation="compute", compute_calls=2) if key == "solve_pulse_basis" else {"identity": key})
                  for key in ("model", "projection", "descriptor", "geometry_validation", "reopen_geometry", "solve_pulse_basis", "reopen_pulse_basis")}
        products = {}
        for name, solution, value in (("background", off, 0.), ("on", on, 2140.)):
            request = store(name + "_request", {"group_voltages": [{"instance_id": "oa", "electrode_group_id": "repeller", "voltage_v": value}]})
            reopen = store(name + "_reopen", {"co_resident_workpoint": name, "solution": solution})
            products[name] = dict(schema_version=1, kind="field_solution", status="complete",
                metadata=dict(backend="comsol", scope="co_resident_stationary_workpoint", field_status="solved",
                              native_reopen_verified=True, co_resident_workpoint=name, solution=solution),
                data={**common, "request": request, "reopen_solution": reopen})
        manifest = dict(schema_version=2, role="simulation_run_manifest", run_id="co", project="instrument_assembly",
                        mode="test_only", status="success", inputs={}, outputs=list(records.values()), products=products)
        publish_terminal_state(root, {"status": "success"}, manifest)
        record = file_record(root / "run_manifest.json")
        self.assertEqual(_co_resident_sources(record, "on")["metadata"]["solution"], on)
        forged = copy.deepcopy(manifest)
        forged['products']['on']['metadata']['solution']['dataset_tag'] = 'dset1'
        other = self.helper.root / 'forged_co'
        other.mkdir()
        publish_terminal_state(other, {'status': 'success'}, forged)
        with self.assertRaises(ValueError):
            _co_resident_sources(file_record(other / 'run_manifest.json'), 'background')
        # A forged second solution tag must not pass even if the selected OFF exists.
        report["on_solution"]["dataset_tag"] = "dset1"
        (root / "reopen_pulse_basis.json").write_text(json.dumps(report), encoding="utf-8")
        with self.assertRaises((ValueError, AssertionError)):
            _co_resident_sources(record, "background")


if __name__ == "__main__":
    unittest.main()
