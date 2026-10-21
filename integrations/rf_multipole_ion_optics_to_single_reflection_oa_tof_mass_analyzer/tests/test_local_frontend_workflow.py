"""Pure local-frontend compilation; fixtures never represent native results."""
from __future__ import annotations

import copy
import csv
import json
import math
from pathlib import Path
import tempfile
import unittest

from common.contracts.rigid_transform import RigidTransform
from common.contracts.write_run_manifest import file_record
from common.simion.pa_family_cache import CACHE_KEY_FIELDS, canonical_pa_family_cache_key
from common.ion_release.release import generate_release_states
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source import SOURCE_COLUMNS
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.tests.test_single_flight_frontend import canonical_frontend_fixture
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.local_frontend.prepare import _nominal_extraction_duration, extraction_shared_times, prepare_local_frontend
from projects.dual_pressure_rectilinear_ion_processor.analysis.guide_interface import NATIVE_TO_MULTIPOLE_ROTATION
from projects.dual_pressure_rectilinear_ion_processor.analysis.native_geometry import native_projection
from projects.orthogonal_accelerator.simion.two_zone_candidate import compile_closed_two_zone_accelerator
from projects.orthogonal_accelerator.analysis.accelerator_time_focus import time_to_fixed_plane_s

REPO = Path(__file__).resolve().parents[3]


def fixture(workspace: Path) -> tuple[Path, dict]:
    producer = workspace / "artifacts/projects/dual_pressure_rectilinear_ion_processor/runs/pure_fixture"
    producer.mkdir(parents=True)
    config = REPO / "projects/dual_pressure_rectilinear_ion_processor/config"
    read = lambda name: json.loads((config / name).read_text(encoding="utf-8-sig"))
    baseline, source = read("baseline.json"), read("source.json")
    model = dict(baseline=baseline, source=source, native_projection=native_projection(baseline, read("numerics.json")),
                 native_operating_point=read("native_operating_point.json"))
    paths = {name: producer / name for name in ("resolved_model.json", "source_spec.json", "release.csv", "run_config.json")}
    for name, value in (("resolved_model.json", model), ("source_spec.json", source), ("run_config.json", {"fixture": True})):
        paths[name].write_text(json.dumps(value), encoding="utf-8")
    with paths["release.csv"].open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SOURCE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(generate_release_states(source))
    records = {name: file_record(paths[file]) for name, file in
               (("resolved_model", "resolved_model.json"), ("source_spec", "source_spec.json"), ("release_csv", "release.csv"))}
    manifest = producer / "run_manifest.json"
    manifest.write_text(json.dumps(dict(schema_version=1, role="simulation_run_manifest", status="success",
                                       project="dual_pressure_rectilinear_ion_processor", run_config=file_record(paths["run_config.json"]),
                                       inputs=records, outputs=[])), encoding="utf-8")
    identities = {**records, "producer_manifest": file_record(manifest)}
    identities = {key: {k: (Path(v).relative_to(workspace).as_posix() if k == "path" else v)
                        for k, v in record.items() if k in {"path", "bytes", "sha256"}}
                  for key, record in identities.items()}
    _, connection, component = canonical_frontend_fixture()
    resolved = compile_closed_two_zone_accelerator(component["requirements"]).resolved_electrodes
    component["transform"] = dict(rotation=[[1, 0, 0], [0, 1, 0], [0, 0, 1]], translation_mm=[0, -50, -resolved.local_exit_z_mm])
    port = resolved.side_entry
    shift = [0, -50-resolved.enclosure.guard_half_y_mm-connection["connector"]["length_mm"]-29,
             port["center_mm"][2]-resolved.local_exit_z_mm]
    native_frame = source["frame_id"]
    common_frame = "multipole_cartesian_z_axis_v1"
    guide = RigidTransform(common_frame, "mrtof_global_cartesian", [[0, -1, 0], [0, 0, 1], [-1, 0, 0]], shift)
    request = dict(schema_version=1, role="rf_oatof_local_frontend_request", output_frame_id="mrtof_global_cartesian", source=identities, accelerator_component=component,
                   registration=dict(source_to_common=RigidTransform(native_frame, common_frame, NATIVE_TO_MULTIPOLE_ROTATION, [0, 0, 0]).to_contract(),
                                     guide_to_solver=guide.to_contract()),
                   connection=dict(rod_end_to_side_wall_gap_mm=connection["connector"]["length_mm"]),
                   numerics=dict(cell_mm_xyz=dict(x=.5, y=.5, z=.1), refine_policy="official_defaults", maximum_step_us=.001,
                                 rf_steps_per_period=64, maximum_flight_us=200, trajectory_sample_interval_us=.01, trajectory_quality=8),
                   pulse=dict(policy_id="detector_blind_actual_occupancy_v1", seed=dict(method="source_ballistic_arrival_envelope_v1", candidate_steps_per_rf_period=8, envelope_padding_rf_periods=4)),
                   diagnostics=dict(policy_id="automatic_full_population_v1"))
    path = workspace / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    return path, request


class LocalFrontendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.path, self.request = fixture(self.workspace)

    def prepare(self, output=None):
        self.path.write_text(json.dumps(self.request), encoding="utf-8")
        return prepare_local_frontend(self.path, output, REPO, self.workspace)

    def cache_key(self):
        physical = self.prepare()["cache_physical_inputs"]
        # Explicit synthetic executable identity tests only the public key
        # projection; it is never used to publish or consume a native field.
        identity = {name: physical[name] for name in CACHE_KEY_FIELDS if name != "simion_identity"}
        identity["simion_identity"] = {"test_fixture": "no_native_execution"}
        return canonical_pa_family_cache_key(identity)

    def rebind_source_inputs(self):
        manifest = self.workspace / self.request["source"]["producer_manifest"]["path"]
        value = json.loads(manifest.read_text())
        for name in ("resolved_model", "source_spec", "release_csv"):
            path = self.workspace / self.request["source"][name]["path"]
            record = file_record(path)
            value["inputs"][name] = record
            self.request["source"][name].update(bytes=record["bytes"], sha256=record["sha256"])
        manifest.write_text(json.dumps(value), encoding="utf-8")
        record = file_record(manifest)
        self.request["source"]["producer_manifest"].update(bytes=record["bytes"], sha256=record["sha256"])

    def test_cache_basis_is_independent_of_linear_operating_voltages(self):
        baseline = self.cache_key()
        volts = self.request["accelerator_component"]["electrode_voltages_v"]
        self.request["accelerator_component"]["electrode_voltages_v"] = {key: value*1.1 for key, value in volts.items()}
        self.assertEqual(baseline, self.cache_key())

    def test_cache_basis_excludes_source_velocity_clock_and_rf_drive(self):
        baseline = self.cache_key()
        path = self.workspace / self.request["source"]["release_csv"]["path"]
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        rows[0]["vx_m_s"] = str(float(rows[0]["vx_m_s"])*1.1)
        for row in rows:
            row["birth_time_s"] = "0.000002"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=SOURCE_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        model_path = self.workspace / self.request["source"]["resolved_model"]["path"]
        model = json.loads(model_path.read_text())
        model["baseline"]["electric"]["rf_frequency_hz"] *= 1.1
        model["baseline"]["electric"]["guide_rf_peak_to_peak_v"] *= 1.1
        model_path.write_text(json.dumps(model), encoding="utf-8")
        self.rebind_source_inputs()
        self.assertEqual(baseline, self.cache_key())

    def test_cache_basis_changes_with_hole_pose_grid_and_rod_geometry(self):
        baseline = self.cache_key()
        original = copy.deepcopy(self.request)
        for mode in ("hole", "pose", "grid", "rod"):
            self.request = copy.deepcopy(original)
            with self.subTest(mode=mode):
                if mode == "hole":
                    self.request["accelerator_component"]["requirements"]["side_entry"]["half_width_x_mm"] = 1.25
                elif mode == "pose":
                    self.request["accelerator_component"]["transform"]["translation_mm"][0] += 1
                    self.request["registration"]["guide_to_solver"]["translation_mm"][0] += 1
                elif mode == "grid":
                    self.request["numerics"]["cell_mm_xyz"]["y"] = .25
                else:
                    path = self.workspace / self.request["source"]["resolved_model"]["path"]
                    model = json.loads(path.read_text())
                    model["baseline"]["native_geometry"]["guide_rod_radius_mm"] = .65
                    config = REPO / "projects/dual_pressure_rectilinear_ion_processor/config/numerics.json"
                    model["native_projection"] = native_projection(model["baseline"], json.loads(config.read_text()))
                    path.write_text(json.dumps(model), encoding="utf-8")
                    self.rebind_source_inputs()
                self.assertNotEqual(baseline, self.cache_key())

    def test_validate_is_read_only_and_preserves_all_source_states(self):
        before = {p.relative_to(self.workspace): p.read_bytes() for p in self.workspace.rglob("*") if p.is_file()}
        result = self.prepare()
        after = {p.relative_to(self.workspace): p.read_bytes() for p in self.workspace.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(result["particle_count"], 100)
        self.assertEqual(result["status"], "validated")
        self.assertEqual(result["registration"]["source_to_solver"]["rotation"], [[0, 0, -1], [1, 0, 0], [0, -1, 0]])
        self.assertNotIn("simion_identity", result["cache_physical_inputs"])

    def test_freeze_raw_identity_global_clock_and_real_exit_mapping(self):
        output = self.workspace / "owned_run"
        result = self.prepare(output)
        raw = output / "inputs/release_raw.csv"
        original = self.workspace / self.request["source"]["release_csv"]["path"]
        self.assertEqual(raw.read_bytes(), original.read_bytes())
        with (output / "inputs/release_global.csv").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([int(r["particle_id"]) for r in rows], list(range(1, 101)))
        self.assertEqual({float(r["instrument_time_us"]) for r in rows}, {0})
        transform = RigidTransform.from_contract(result["registration"]["observer_to_mr"])
        from common.contracts.rigid_transform import FramedPosition
        actual = transform.transform_position(FramedPosition(transform.from_frame_id, result["registration"]["oa_exit_center_solver_mm"]))
        self.assertEqual(actual.coordinates_mm, (0, -50, 0))
        self.assertIn("release_raw.csv", result["output_records"])
        self.assertIn("source.fly2", result["output_records"])
        self.assertEqual(json.loads((output / "inputs/numerics.json").read_text())["trajectory_quality"], 8)

    def test_pulse_is_prediction_and_all_arrivals_are_in_declared_envelope(self):
        result = self.prepare()
        pulse = result["pulse_plan"]
        self.assertLess(pulse["candidate_start_us"], pulse["predicted_arrival_min_us"])
        self.assertGreater(pulse["candidate_stop_us"], pulse["predicted_arrival_max_us"])
        self.assertIn("not_actual", pulse["scope"])
        self.assertAlmostEqual(pulse["candidate_step_us"], pulse["rf_period_us"] / 8)

    def test_automatic_shared_times_cover_full_horizon_and_ideal_exit(self):
        result = self.prepare()
        pulse = result["pulse_plan"]["predicted_centroid_axis_time_us"]
        times = extraction_shared_times(result, pulse)
        self.assertEqual(times, sorted(set(times)))
        self.assertEqual(times[0], 0)
        self.assertEqual(times[-1], 200)
        self.assertIn(pulse, times)
        self.assertIn(pulse+result["pulse_plan"]["predicted_nominal_extraction_duration_us"], times)
        self.assertIn(result["pulse_plan"]["predicted_guide_exit_time_range_us"][0], times)
        self.assertLess(len(times), 100)
        self.assertIn("display_schedule_only", result["pulse_plan"]["extraction_duration_scope"])

    def test_three_zone_duration_reuses_provider_oracle_and_collapses_at_equal_fields(self):
        frontend = dict(electrodes=dict(accelerator_repeller_id=10, accelerator_grid1_id=11,
                                        accelerator_intermediate2_id=12, accelerator_grid2_id=13),
                        accelerator_local_region=dict(accelerator_component=dict(variant_id="three_zone"),
                            planes=dict(repeller=34., grid1=30., intermediate2=15., exit=0.),
                            port=dict(center_mm=[0., -66.5, 32.]),
                            operating_voltages_v={"10": 4400., "11": 4000., "12": 2000., "13": 0.}))
        actual = _nominal_extraction_duration(frontend, dict(mass_amu=524., charge_state=1))
        expected = 1e6*time_to_fixed_plane_s(4400., 4000., 4., 30., 2., 0., 0., 524.)
        self.assertAlmostEqual(actual, expected, delta=32*math.ulp(expected))

    def test_explicit_three_zone_provider_keeps_full_source_and_actual_offset_axis(self):
        geometry = dict(cross_section="square", axis_x_mm=1., axis_y_mm=2., shield_center_z_mm=15.5,
                        shield_outer_width_mm=42., shield_inner_width_mm=40., shield_span_z_mm=37.,
                        negative_x_face_mm=-20., shield_wall_mm=1., shield_back_z_mm=-3.,
                        port_center_y_mm=2., port_center_z_mm=2., numerical_port_width_mm=3., numerical_port_height_mm=2.8,
                        electrode_width_mm=34., bore_width_mm=30., repeller_front_z_mm=0., repeller_thickness_mm=.5,
                        grid1_z_mm=4., intermediate2_z_mm=19., grid2_z_mm=34., ring_count=2,
                        ring_thickness_mm=.5, ring_z_mm=[11.5, 26.5])
        component = self.request["accelerator_component"]
        component.update(variant_id="three_zone", geometry_profile_id="explicit_synthetic_three_zone_fixture",
            requirements=dict(schema_version=1, role="orthogonal_accelerator_bare_three_zone_requirements",
                              variant_id="three_zone", geometry=geometry),
            transform=dict(rotation=[[0, 1, 0], [1, 0, 0], [0, 0, -1]], translation_mm=[3., -50., 34.]),
            local_electrode_ids={"1": 9, "2": 10, "3": 11, "4": 15, "5": 14, "6": 12, "7": 13},
            electrode_voltages_v={"1": 0., "2": 4400., "3": 4000., "4": 2000., "5": 0., "6": 3000., "7": 1000.})
        self.request["registration"]["guide_to_solver"]["translation_mm"] = [5., -100., 32.]
        result = self.prepare(self.workspace / "three_zone_fixture")
        self.assertEqual(result["particle_count"], 100)
        self.assertEqual(result["frontend_contract"]["pa_plus_solution_model"]["mode_count"], 6)
        self.assertEqual(result["registration"]["oa_exit_center_solver_mm"], [5., -49., 0.])
        self.assertEqual(result["pulse_plan"]["oa_axis_coordinate_mm"], -49.)
        self.assertEqual(result["pulse_plan"]["extraction_duration_provider_variant"], "three_zone")
        self.assertGreater(result["pulse_plan"]["predicted_nominal_extraction_duration_us"], 0)
        self.assertIn("geometry", result["cache_physical_inputs"]["geometry"]["canonical_electrodes"])
        baseline = self.cache_key()
        component["electrode_voltages_v"] = {key: 1.1*value for key, value in component["electrode_voltages_v"].items()}
        self.assertEqual(baseline, self.cache_key())

    def test_unknown_numerics_and_invalid_population_fail_before_writes(self):
        for change in (lambda r: r["numerics"].update(convergence_v=1e-5),
                       lambda r: r["numerics"].update(maximum_step_us=True),
                       lambda r: r["pulse"]["seed"].update(candidate_steps_per_rf_period=0),
                       lambda r: r["registration"]["source_to_common"].update(translation_mm=[1, 0, 0])):
            original = copy.deepcopy(self.request)
            change(self.request)
            output = self.workspace / "never_created"
            with self.assertRaises(ValueError):
                self.prepare(output)
            self.assertFalse(output.exists())
            self.request = original

    def test_tampered_release_and_unbound_manifest_input_rejected(self):
        original = self.workspace / self.request["source"]["release_csv"]["path"]
        original.write_text(original.read_text()+"\n", encoding="utf-8")
        with self.assertRaises(AssertionError):
            self.prepare()

    def test_workspace_escape_is_rejected(self):
        self.request["source"]["release_csv"]["path"] = "artifacts/../request.json"
        with self.assertRaises(ValueError):
            self.prepare()

    def test_trajectory_quality_is_required_positive_integer(self):
        for value in (None, True, 0, -1, 1.5, 501, float("inf")):
            with self.subTest(value=value):
                if value is None:
                    self.request["numerics"].pop("trajectory_quality", None)
                else:
                    self.request["numerics"]["trajectory_quality"] = value
                with self.assertRaises(ValueError):
                    self.prepare()

    def test_unbound_input_failed_producer_and_nonfinite_release_fail(self):
        source = self.workspace / self.request["source"]["release_csv"]["path"]
        manifest = self.workspace / self.request["source"]["producer_manifest"]["path"]
        baseline = json.loads(manifest.read_text())
        for mode in ("unbound", "failed", "nonfinite"):
            with self.subTest(mode=mode):
                value = copy.deepcopy(baseline)
                if mode == "unbound":
                    del value["inputs"]["release_csv"]
                elif mode == "failed":
                    value["status"] = "failed"
                else:
                    with source.open(newline="", encoding="utf-8") as handle:
                        rows = list(csv.DictReader(handle))
                    rows[0]["vx_m_s"] = "NaN"
                    with source.open("w", newline="", encoding="utf-8") as handle:
                        writer = csv.DictWriter(handle, fieldnames=SOURCE_COLUMNS)
                        writer.writeheader()
                        writer.writerows(rows)
                    value["inputs"]["release_csv"] = file_record(source)
                    record = file_record(source)
                    self.request["source"]["release_csv"].update(bytes=record["bytes"], sha256=record["sha256"])
                manifest.write_text(json.dumps(value), encoding="utf-8")
                record = file_record(manifest)
                self.request["source"]["producer_manifest"].update(bytes=record["bytes"], sha256=record["sha256"])
                with self.assertRaises(ValueError):
                    self.prepare()

    def test_absolute_nonzero_birth_clock_is_preserved(self):
        source = self.workspace / self.request["source"]["release_csv"]["path"]
        with source.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        rows[0]["birth_time_s"] = "0.000007"
        with source.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=SOURCE_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        record = file_record(source)
        self.request["source"]["release_csv"].update(bytes=record["bytes"], sha256=record["sha256"])
        manifest = self.workspace / self.request["source"]["producer_manifest"]["path"]
        value = json.loads(manifest.read_text())
        value["inputs"]["release_csv"] = record
        manifest.write_text(json.dumps(value), encoding="utf-8")
        record = file_record(manifest)
        self.request["source"]["producer_manifest"].update(bytes=record["bytes"], sha256=record["sha256"])
        output = self.workspace / "clock_fixture"
        result = self.prepare(output)
        self.assertEqual(result["pulse_plan"]["source_birth_time_range_us"], [0, 7])
        with (output / "inputs/release_global.csv").open(newline="") as handle:
            first = next(csv.DictReader(handle))
        self.assertEqual(float(first["instrument_time_us"]), 7)
        self.assertEqual(result["source_clock"]["native_fly2_tob_us"], 0)
        self.assertTrue(result["source_clock"]["program_birth_time_restore_required"])
        self.assertIn("tob = 0", (output / "inputs/source.fly2").read_text())


if __name__ == "__main__":
    unittest.main()
