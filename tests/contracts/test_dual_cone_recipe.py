"""Pure dual-cone recipe admission, without native execution."""
import copy
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from msplatform import components
from msplatform.backends.simion.dual_cone_transport import SDS_FILES
from msplatform.recipes.dual_cone import (freeze_sds_resources,
                                        project_sds_numerics, resolve_sds_conditions, sds_resource_identities,
                                        validate_sds_physics, validate_sds_release, validate_sds_resources)


CONFIG = (Path(__file__).resolve().parents[2] / "src/msplatform/components"
          / "dual_cone_tandem_quadrupole/config")


class DualConeRecipeTests(unittest.TestCase):
    def setUp(self):
        self.environment = json.loads((CONFIG / "gas_environment.json").read_text(encoding="utf-8"))
        design = json.loads((CONFIG / "baseline.json").read_text(encoding="utf-8"))
        self.study = {"component_requests": {"dual_cone": {
            "provider_id": "dual_cone_tandem_quadrupole", "design": design}},
            "recipe": {"instances": [{"instance_id": "dual_cone"}]}}
        self.species = [{"species_kind": "ion", "charge_state": 1}]

    def test_author_and_selected_real_geometry_are_resolved(self):
        result = resolve_sds_conditions(self.study, self.environment, self.species)
        self.assertEqual(result["species_data"]["mass_amu"], 28.0134)
        self.assertEqual(result["outlet_pressure_pa"], self.environment["outlet_pressure_pa"])
        resolved = components.resolve_component(self.study["component_requests"]["dual_cone"])
        self.assertEqual(result["rear_start_z_mm"], resolved.resolved_design["geometry_mm"]
                         ["second_cone"]["aperture_reference_z_mm"])

    def test_explicit_numerics_project_exactly_to_original_native_contract(self):
        native = json.loads((CONFIG / "simion_solver_numerics.json").read_text(encoding="utf-8"))
        geometry = copy.deepcopy(native)
        trajectory = geometry.pop("trajectory")
        refine = geometry["pa"].pop("refine_policy")
        study = {"numerics": {"geometry": geometry, "fields": {"refine_policy": refine},
            "tracing": {"end_policy": {"maximum_particle_age_us": trajectory["maximum_time_us"]},
                "simion": {key: trajectory[key] for key in ("maximum_step_us", "trajectory_quality", "rf_steps_per_period", "random_seed")}}}}
        recording = {"mode": "actual_callback_samples", "sample_interval_us": trajectory["sample_interval_us"],
                     "end_time_us": trajectory["maximum_time_us"]}
        self.assertEqual(project_sds_numerics(study, recording), native)
        wrong = copy.deepcopy(study)
        wrong["numerics"]["geometry"]["pa"]["refine_policy"] = refine
        with self.assertRaises(ValueError):
            project_sds_numerics(wrong, recording)
        wrong = dict(recording, end_time_us=1.)
        with self.assertRaises(ValueError):
            project_sds_numerics(study, wrong)
        wrong = copy.deepcopy(study)
        del wrong["numerics"]["tracing"]["simion"]["random_seed"]
        with self.assertRaises(ValueError):
            project_sds_numerics(wrong, recording)

    def test_model_only_sds_physics_is_explicit(self):
        interface = json.loads((CONFIG / "gas_field_interface.json").read_text(encoding="utf-8"))
        source = json.loads((CONFIG / "ion_transport_science.json").read_text(encoding="utf-8"))
        study = {"physics": {"gas_field_interface": interface, "sds_collision_science": source["gas"]}}
        self.assertEqual(validate_sds_physics(study), (interface, source["gas"]))
        study["physics"]["sds_collision_science"]["collision_gas_mass_amu"] = 28.
        with self.assertRaises(ValueError):
            validate_sds_physics(study)

    def test_canonical_release_and_native_materializer_share_exact_sample(self):
        from msplatform.particle_release.authoring import sample_release
        from msplatform.particle_release.release import materialize_release

        spec = json.loads((CONFIG / "cylindrical_particle_source.json").read_text(encoding="utf-8"))
        spec["particle_count"] = spec["mother_particle_count"] = 3
        release = dict(schema_version=1, role="canonical_birth_source_request", release_spec=spec,
            clock=dict(clock_epoch_id="instrument_clock_epoch_v1", authority_sha256="6A035131B2BDBA6F7F20CBF6B6FD20EDAA5DCB3D7EC8EB7349F74F7AC35238A0"),
            instrument_origin_us=0., species_id="ion", source_component_id="dual_cone", relative_weights=None)
        selected = validate_sds_release(release)
        packet = sample_release(release).to_dict()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            materialize_release(selected, path / "source.csv", path / "receipt.json")
            with (path / "source.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
        for expected, actual in zip(packet["realization"]["generator_rows"], rows, strict=True):
            self.assertEqual(expected["particle_id"], int(actual["particle_id"]))
            for key in ("birth_time_s", "x_mm", "y_mm", "z_mm", "vx_m_s", "vy_m_s", "vz_m_s", "mass_amu"):
                self.assertEqual(expected[key], float(actual[key]))
            self.assertEqual(expected["charge_state"], int(actual["charge_state"]))
        invalid = copy.deepcopy(release)
        invalid["particle_ids"] = [7, 8, 9]
        with self.assertRaises(ValueError):
            validate_sds_release(invalid)

    def test_wrong_instance_and_unsupported_species_rejected(self):
        wrong = copy.deepcopy(self.study)
        wrong["recipe"]["instances"][0]["instance_id"] = "other"
        with self.assertRaises(ValueError):
            resolve_sds_conditions(wrong, self.environment, self.species)
        for species in ({"species_kind": "ion", "charge_state": -1},
                        {"species_kind": "electron", "charge_state": -1}, {}):
            with self.subTest(species=species), self.assertRaises(ValueError):
                resolve_sds_conditions(self.study, self.environment, [species])

    def test_resource_freeze_is_single_capture_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def record(name, payload):
                (root / name).write_bytes(payload)
                return {"path": name, "bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest().upper()}
            env = record("environment.json", b"environment")
            sources = {name: record(name, name.encode()) for name in SDS_FILES}
            names = ("science", "science_author", "numerics", "geometry", "environment", "species_data",
                     "constants_data", "transport_data", "field_csv", "field_metadata")
            records = {name: {"path": name} for name in names}
            manifest = {"schema_version": 2, "role": "simulation_run_manifest", "status": "success",
                        "inputs": records, "outputs": [], "products": {"gas_field": {
                            "schema_version": 1, "kind": "gas_field", "status": "complete", "metadata": {"backend": "comsol"},
                            "data": records}}}
            manifest_bytes = json.dumps(manifest).encode()
            manifest_record = record("manifest.json", manifest_bytes)
            request = {"environment_instance_id": "dual_cone", "environment_record": env,
                       "gas_field_reference": {"path": "manifest.json", "sha256": manifest_record["sha256"],
                                               "product_id": "gas_field"}, "sds_records": sources}
            request_bytes = json.dumps(request).encode()
            request_record = record("request.json", request_bytes)
            frozen = freeze_sds_resources(root / "request.json", request_record["sha256"])
            self.assertEqual(sds_resource_identities(frozen, request_record["sha256"])["mbmr.dat"],
                             {"bytes": sources["mbmr.dat"]["bytes"], "sha256": sources["mbmr.dat"]["sha256"]})
            (root / "environment.json").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "declared identity"):
                freeze_sds_resources(root / "request.json", request_record["sha256"])
            (root / "manifest.json").unlink()
            self.assertEqual(validate_sds_resources(frozen, request_record["sha256"]), request)
            forged = copy.deepcopy(frozen)
            forged["mbmr.dat"]["bytes_base64"] = "YQ=="
            with self.assertRaises(ValueError):
                validate_sds_resources(forged, request_record["sha256"])

    def test_public_recipe_load_and_frozen_validation(self):
        from msplatform.recipes import load_recipe, validate_recipe
        from tests.contracts.test_support.dual_cone_native_recipe import write_dual_cone_recipe_fixture

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            author = write_dual_cone_recipe_fixture(root)
            resolved = load_recipe(author).to_dict()
            self.assertEqual(resolved["gas_data"]["status"], "pending_guarded_cfd_admission")
            self.assertEqual(resolved["recording"]["mode"], "actual_callback_samples")
            (root / "environment.json").write_bytes(b"changed after capture")
            self.assertEqual(validate_recipe(resolved)["recipe_id"], resolved["recipe_id"])
            with self.assertRaisesRegex(ValueError, "declared identity"):
                load_recipe(author)


if __name__ == "__main__":
    unittest.main()
