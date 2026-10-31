"""Pure local-frontend compilation; fixtures never represent native results."""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.rigid_transform import RigidTransform
from common.contracts.canonical_clock_authority import validate_clock_authority
from common.contracts.write_run_manifest import file_record
from common.integration.resolve_assembly import compile_assembly_layout
from common.simion.pa_family_cache import CACHE_KEY_FIELDS, canonical_pa_family_cache_key
from common.ion_release.release import generate_release_states
from integrations.runtime.single_flight_source import SOURCE_COLUMNS
from integrations.tests.frontend_fixtures import canonical_frontend_fixture
from integrations.tests import test_local_frontend_field_support as field_support_tests
from integrations.workflows.local_frontend.prepare import (
    AUTOMATIC_PULSE_POLICY, RF_DELAY_PULSE_POLICY, _nominal_extraction_duration,
    extraction_shared_times, prepare_local_frontend, resolve_pulse_decision,
)
from projects.dual_pressure_rectilinear_ion_processor.analysis.native_geometry import native_projection
from projects.dual_pressure_rectilinear_ion_processor.analysis.guide_interface import export_guide_contract, export_guide_assembly_interface
from projects.orthogonal_accelerator.simion.two_zone_candidate import compile_closed_two_zone_accelerator
from projects.orthogonal_accelerator.analysis.assembly_interface import resolve_assembly_interface
from projects.orthogonal_accelerator.analysis.accelerator_time_focus import time_to_fixed_plane_s

REPO = Path(__file__).resolve().parents[2]


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
    clock_inputs = producer / "inputs"
    clock_inputs.mkdir()
    epoch = clock_inputs / "instrument_epoch.json"
    epoch.write_text(json.dumps({"instrument_time_us": baseline["clock"]["epoch_us"]}), encoding="utf-8-sig")
    clock = dict(schema_version=1, role="canonical_clock_authority", clock_epoch_id="ion_processor_epoch_zero_v1",
                 instrument_time_unit="us", canonical_time_basis="instrument_epoch_absolute_time",
                 authority=dict(path="inputs/instrument_epoch.json", sha256=file_record(epoch)["sha256"], field="instrument_time_us"),
                 solver_local_time_basis="elapsed_time_from_zero_us",
                 adapter_materialization="instrument_time_us_equals_authority_epoch_plus_solver_elapsed_once",
                 handoff_policy="preserve_instrument_time_us_and_clock_epoch_id", legacy_new_campaign_allowed=False)
    authority = clock_inputs / "clock_authority.json"
    authority.write_text(json.dumps(clock, indent=2), encoding="utf-8-sig")
    clock_records = {"inputs\\clock_authority.json": file_record(authority),
                     "inputs\\instrument_epoch.json": file_record(epoch)}
    manifest = producer / "run_manifest.json"
    manifest.write_text(json.dumps(dict(schema_version=1, role="simulation_run_manifest", status="success",
                                       project="dual_pressure_rectilinear_ion_processor", run_config=file_record(paths["run_config.json"]),
                                       inputs=records | clock_records, outputs=[])), encoding="utf-8")
    identities = {**records, "producer_manifest": file_record(manifest)}
    identities = {key: {k: (Path(v).relative_to(workspace).as_posix() if k == "path" else v)
                        for k, v in record.items() if k in {"path", "bytes", "sha256"}}
                  for key, record in identities.items()}
    _, connection, component = canonical_frontend_fixture()
    resolved = compile_closed_two_zone_accelerator(component["requirements"]).resolved_electrodes
    component["transform"] = dict(rotation=[[1, 0, 0], [0, 1, 0], [0, 0, 1]], translation_mm=[0, -50, 0])
    port = resolved.side_entry
    shift = [0, -50-resolved.enclosure.guard_half_y_mm-connection["connector"]["length_mm"]-29,
             port["center_mm"][2]-resolved.local_exit_z_mm]
    common_frame = "multipole_cartesian_z_axis_v1"
    guide = RigidTransform(common_frame, "mrtof_global_cartesian", [[0, -1, 0], [0, 0, 1], [-1, 0, 0]], shift)
    interface = resolve_assembly_interface(component["requirements"], geometry_profile_id=component["geometry_profile_id"])
    oa_pose = RigidTransform(interface["local_frame_id"], "mrtof_global_cartesian", **component.pop("transform"))
    recipe = dict(schema_version=1, role="assembly_recipe", integration_id="instrument_assembly", recipe_id="local_guide_oa",
                  assembly_frame_id="mrtof_global_cartesian", position_tolerance_mm=1e-9, angular_tolerance_rad=1e-12,
                  instances=[dict(instance_id="guide", project_id="dual_pressure_rectilinear_ion_processor", transform=guide.to_contract()),
                             dict(instance_id="accelerator", project_id="orthogonal_accelerator", transform=oa_pose.to_contract())],
                  connections=[dict(connection_id="guide_to_oa", upstream=dict(instance_id="guide",port_id="guide_exit"),
                                    downstream=dict(instance_id="accelerator",port_id="side_entry"), gap_mm=connection["connector"]["length_mm"], coupling_mode="monolithic_joint_solve")])
    request = dict(schema_version=3, role="instrument_assembly_local_frontend_request", source=identities, accelerator_component=component,
                   numerics=dict(cell_mm_xyz=dict(x=.5, y=.5, z=.1), refine_policy="official_defaults", maximum_step_us=.001,
                                 rf_steps_per_period=64, maximum_flight_us=200, trajectory_sample_interval_us=.01, trajectory_quality=8),
                   pulse=dict(policy_id="detector_blind_actual_occupancy_v1", seed=dict(method="source_ballistic_arrival_envelope_v1", candidate_steps_per_rf_period=8, envelope_padding_rf_periods=4)),
                   diagnostics=dict(policy_id="automatic_full_population_v1"))
    write_fixture_plan(workspace, request, recipe)
    path = workspace / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    return path, request


def write_fixture_plan(workspace, request, recipe=None):
    """Publish the fixture's actual provider interfaces and refresh its file record."""
    path = workspace / "parent_composition_plan.json"
    if recipe is None:
        recipe = json.loads(Path(request["composition_plan"]["path"]).read_text())["recipe"]
    model = json.loads((workspace / request["source"]["resolved_model"]["path"]).read_text())
    guide = export_guide_contract(model, {k: request["source"][k] for k in ("resolved_model", "source_spec", "release_csv")})
    component = request["accelerator_component"]
    edge = recipe["connections"][0]
    components = {edge["upstream"]["instance_id"]: export_guide_assembly_interface(guide),
                  edge["downstream"]["instance_id"]: resolve_assembly_interface(component["requirements"], geometry_profile_id=component["geometry_profile_id"])}
    plan = compile_assembly_layout(recipe, components)
    path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    request["composition_plan"] = file_record(path)
    return plan


def renamed_frontend_recipe(recipe):
    """Rename both connection instances and reverse author declaration order."""
    names = {recipe["connections"][0]["upstream"]["instance_id"]: "source_a",
             recipe["connections"][0]["downstream"]["instance_id"]: "oa_b"}
    for item in recipe["instances"]:
        item["instance_id"] = names[item["instance_id"]]
    recipe["instances"].reverse()
    for endpoint in ("upstream", "downstream"):
        route = recipe["connections"][0][endpoint]
        route["instance_id"] = names[route["instance_id"]]


class LocalFrontendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.path, self.request = fixture(self.workspace)
        self.recipe = json.loads(Path(self.request["composition_plan"]["path"]).read_text())["recipe"]

    def prepare(self, output=None):
        write_fixture_plan(self.workspace, self.request, self.recipe)
        self.path.write_text(json.dumps(self.request), encoding="utf-8")
        return prepare_local_frontend(self.path, output, self.workspace, run_id="20261022_120000__test__python__local-frontend" if output else None)

    def cache_key(self):
        physical = self.prepare()["cache_physical_inputs"]
        # Explicit synthetic executable identity tests only the public key
        # projection; it is never used to publish or consume a native field.
        identity = {name: physical[name] for name in CACHE_KEY_FIELDS if name not in {"simion_identity", "builder_identity"}}
        identity["simion_identity"] = {"test_fixture": "no_native_execution"}
        identity["builder_identity"] = {"test_fixture": "no_native_execution"}
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

    def test_real_frozen_geometry_keeps_native_cache_fingerprint(self):
        from common.contracts.file_identity import canonical_json_sha256

        original = REPO.parent / "artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20261021_190350__sim__simion__local-bare-guide-oa/inputs/local_frontend_pa_cache_identity.json"
        if not original.is_file():
            self.skipTest("original native N=100 field identity is not available in this checkout")
        baseline = json.loads(original.read_text(encoding="utf-8-sig"))
        prepared = prepare_local_frontend(REPO / "integrations/config/experiments/guide_oa_three_zone_functional.json",
                                          None, REPO.parent)
        physical = prepared["cache_physical_inputs"]
        fields = ("geometry", "gem", "basis_namespace", "mesh", "grid_phase", "surface", "refine_policy")
        # Plain numeric equality misses 0 versus 0.0; compare the actual
        # serialized field-key factors, without reading or hashing native PAs.
        self.assertEqual(canonical_json_sha256({key: physical[key] for key in fields}),
                         canonical_json_sha256({key: baseline[key] for key in fields}))

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
        original_recipe = copy.deepcopy(self.recipe)
        for mode in ("hole", "pose", "grid", "rod"):
            self.request = copy.deepcopy(original)
            self.recipe = copy.deepcopy(original_recipe)
            with self.subTest(mode=mode):
                if mode == "hole":
                    self.request["accelerator_component"]["requirements"]["side_entry"]["half_width_x_mm"] = 1.25
                elif mode == "pose":
                    for instance in self.recipe["instances"]:
                        instance["transform"]["translation_mm"][0] += 1
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
        self.assertEqual(json.loads((output / "inputs/numerics.json").read_text())["trajectory_quality"], 8)
        self.assertFalse((output / "inputs/source_clock.json").exists())
        manifest = self.workspace / self.request["source"]["producer_manifest"]["path"]
        for name in ("clock_authority.json", "instrument_epoch.json"):
            self.assertEqual((output / "inputs" / name).read_bytes(), (manifest.parent / "inputs" / name).read_bytes())
        identity = json.loads((output / "inputs/source_identity.json").read_text())
        self.assertEqual(validate_clock_authority(output / "inputs/clock_authority.json", output)["clock_epoch_id"],
                         identity["clock_epoch_id"])

    def test_producer_clock_missing_drift_and_epoch_conflicts_fail_before_writing(self):
        for defect in ("missing_authority_record", "missing_epoch_record", "missing_file", "authority_drift", "epoch_drift",
                       "manifest_epoch_drift", "wrong_authority_target", "absolute_authority_target", "model_epoch_conflict", "nonzero_epoch"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                request_path, request = fixture(workspace)
                manifest_path = workspace / request["source"]["producer_manifest"]["path"]
                manifest = json.loads(manifest_path.read_text())
                authority = manifest_path.parent / "inputs/clock_authority.json"
                epoch = manifest_path.parent / "inputs/instrument_epoch.json"
                if defect.startswith("missing_") and defect.endswith("_record"):
                    name = "clock_authority" if defect == "missing_authority_record" else "instrument_epoch"
                    del manifest["inputs"][f"inputs\\{name}.json"]
                elif defect == "missing_file":
                    epoch.unlink()
                elif defect == "authority_drift":
                    authority.write_bytes(authority.read_bytes() + b" ")
                elif defect == "epoch_drift":
                    epoch.write_text('{"instrument_time_us": 2}', encoding="utf-8")
                elif defect == "manifest_epoch_drift":
                    manifest["inputs"]["inputs\\instrument_epoch.json"]["sha256"] = "0" * 64
                elif defect in {"wrong_authority_target", "absolute_authority_target"}:
                    other = epoch.with_name("other_epoch.json")
                    other.write_bytes(epoch.read_bytes())
                    clock = json.loads(authority.read_text(encoding="utf-8-sig"))
                    clock["authority"]["path"] = (str(epoch) if defect == "absolute_authority_target" else "inputs/other_epoch.json")
                    authority.write_text(json.dumps(clock), encoding="utf-8")
                    manifest["inputs"]["inputs\\clock_authority.json"] = file_record(authority)
                else:
                    model_path = workspace / request["source"]["resolved_model"]["path"]
                    model = json.loads(model_path.read_text())
                    model["baseline"]["clock"]["epoch_us"] = 2
                    model_path.write_text(json.dumps(model), encoding="utf-8")
                    manifest["inputs"]["resolved_model"] = file_record(model_path)
                    request["source"]["resolved_model"].update({key: manifest["inputs"]["resolved_model"][key] for key in ("bytes", "sha256")})
                    if defect == "nonzero_epoch":
                        epoch.write_text('{"instrument_time_us": 2}', encoding="utf-8")
                        clock = json.loads(authority.read_text(encoding="utf-8-sig"))
                        clock["authority"]["sha256"] = file_record(epoch)["sha256"]
                        authority.write_text(json.dumps(clock), encoding="utf-8")
                        manifest["inputs"].update({"inputs\\clock_authority.json": file_record(authority),
                                                   "inputs\\instrument_epoch.json": file_record(epoch)})
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                record = file_record(manifest_path)
                request["source"]["producer_manifest"].update({key: record[key] for key in ("bytes", "sha256")})
                request_path.write_text(json.dumps(request), encoding="utf-8")
                output = workspace / "rejected"
                with self.assertRaises((ValueError, AssertionError)):
                    prepare_local_frontend(request_path, output, workspace, run_id="20261022_120000__test__python__clock-reject")
                self.assertFalse((output / "inputs/frontend.gem").exists())

    def test_prepared_identity_binds_run_to_actual_plan_without_duplicate_components(self):
        output = self.workspace / "identity_run"
        self.prepare(output)
        identity = json.loads((output / "inputs/integration_identity.json").read_text())
        plan_bytes = (output / "inputs/composition_plan.json").read_bytes()
        self.assertEqual(identity["integration_id"], "instrument_assembly")
        self.assertEqual(identity["workflow_id"], "local_frontend")
        self.assertEqual(identity["run_id"], "20261022_120000__test__python__local-frontend")
        self.assertEqual(identity["composition_plan"]["sha256"], hashlib.sha256(plan_bytes).hexdigest().upper())
        self.assertEqual(identity["composition_plan"]["path"], "composition_plan.json")
        self.assertEqual({i["instance_id"] for i in json.loads(plan_bytes)["recipe"]["instances"]}, {"guide", "accelerator"})

    def test_missing_run_identity_or_wrong_assembly_owner_fails_before_writes(self):
        output = self.workspace / "invalid_identity"
        for run_id in (None, "invalid"):
            with self.subTest(run_id=run_id), self.assertRaises(ValueError):
                prepare_local_frontend(self.path, output, self.workspace, run_id=run_id)
            self.assertFalse((output / "inputs/frontend.gem").exists())
        self.recipe["integration_id"] = "wrong_owner"
        with self.assertRaisesRegex(ValueError, "instrument_assembly"):
            self.prepare(output)
        self.assertFalse((output / "inputs/frontend.gem").exists())

    def test_pulse_is_prediction_and_all_arrivals_are_in_declared_envelope(self):
        result = self.prepare()
        pulse = result["pulse_plan"]
        self.assertLess(pulse["candidate_start_us"], pulse["predicted_arrival_min_us"])
        self.assertGreater(pulse["candidate_stop_us"], pulse["predicted_arrival_max_us"])
        self.assertIn("not_actual", pulse["scope"])
        self.assertAlmostEqual(pulse["candidate_step_us"], pulse["rf_period_us"] / 8)

    def test_source_identity_is_read_once_per_consumption_and_freeze_boundary(self):
        from common.contracts import write_run_manifest as records
        from common.contracts import canonical_clock_authority as clock_contract
        output = self.workspace / "single_identity_read"
        with (patch.object(records, "file_sha256", wraps=records.file_sha256) as digest,
              patch.object(clock_contract, "file_sha256", wraps=clock_contract.file_sha256) as clock_digest):
            self.prepare(output)
        hashed = [Path(call.args[0]).resolve() for call in digest.call_args_list]
        for source_name, filename in (("producer_manifest", "producer_manifest.json"),
                                      ("resolved_model", "resolved_model.json"),
                                      ("source_spec", "source_spec.json"), ("release_csv", "release_raw.csv")):
            self.assertEqual(hashed.count((self.workspace / self.request["source"][source_name]["path"]).resolve()), 1)
            self.assertEqual(hashed.count((output / "inputs" / filename).resolve()), 1)
        producer = (self.workspace / self.request["source"]["producer_manifest"]["path"]).parent
        epoch = (producer / "inputs/instrument_epoch.json").resolve()
        self.assertEqual([Path(call.args[0]).resolve() for call in clock_digest.call_args_list], [epoch])
        self.assertEqual(hashed.count(epoch), 0)
        self.assertEqual(hashed.count((producer / "inputs/clock_authority.json").resolve()), 1)
        for name in ("clock_authority.json", "instrument_epoch.json"):
            self.assertEqual(hashed.count((output / "inputs" / name).resolve()), 1)
        self.assertEqual(json.loads((output / "inputs/request.json").read_text()), self.request)

    def test_changed_frozen_copy_is_rejected(self):
        release = (self.workspace / self.request["source"]["release_csv"]["path"]).resolve()
        copy_file = shutil.copyfile
        def changed_copy(source, target):
            result = copy_file(source, target)
            if Path(source).resolve() == release:
                Path(target).write_bytes(Path(target).read_bytes() + b"\n")
            return result
        with patch.object(shutil, "copyfile", side_effect=changed_copy):
            with self.assertRaisesRegex(AssertionError, "frozen release_raw.csv byte count changed"):
                self.prepare(self.workspace / "changed_copy")

    def test_recipe_instance_names_and_order_do_not_change_physics(self):
        original_dir, renamed_dir = self.workspace / "original_instances", self.workspace / "renamed_instances"
        original = self.prepare(original_dir)
        renamed_frontend_recipe(self.recipe)
        renamed = self.prepare(renamed_dir)
        self.assertEqual({row["instance_id"] for row in renamed["assembly_plan"]["recipe"]["instances"]},
                         {"source_a", "oa_b"})
        for key in ("frontend_contract", "guide_contract", "registration", "pulse_plan", "cache_physical_inputs"):
            self.assertEqual(original[key], renamed[key], key)
        for name in ("frontend.gem", "frontend.pa+", "release_raw.csv", "release_global.csv",
                     "on_voltages.json", "off_voltages.json", "clock_authority.json", "instrument_epoch.json"):
            self.assertEqual((original_dir / "inputs" / name).read_bytes(),
                             (renamed_dir / "inputs" / name).read_bytes(), name)

    def test_recipe_wrong_provider_or_connection_fails_before_outputs(self):
        original = copy.deepcopy(self.request)
        original_recipe = copy.deepcopy(self.recipe)
        for defect in ("provider", "unknown_endpoint", "same_endpoint", "port", "coupling", "extra_instance"):
            with self.subTest(defect=defect):
                self.request = copy.deepcopy(original)
                self.recipe = copy.deepcopy(original_recipe)
                renamed_frontend_recipe(self.recipe)
                recipe = self.recipe
                edge = recipe["connections"][0]
                if defect == "provider":
                    recipe["instances"][0]["project_id"] = "dual_pressure_rectilinear_ion_processor"
                elif defect == "unknown_endpoint":
                    edge["upstream"]["instance_id"] = "absent"
                elif defect == "same_endpoint":
                    edge["downstream"]["instance_id"] = edge["upstream"]["instance_id"]
                elif defect == "port":
                    edge["upstream"]["port_id"] = "exit_gate_outer_face"
                elif defect == "coupling":
                    edge["coupling_mode"] = "state_handoff"
                else:
                    recipe["instances"].append(dict(recipe["instances"][0], instance_id="extra"))
                output = self.workspace / defect
                with self.assertRaises(ValueError):
                    self.prepare(output)
                self.assertFalse((output / "inputs/frontend.gem").exists())

    def test_recipe_translation_moves_geometry_and_every_source_once(self):
        original_dir, shifted_dir = self.workspace / "original_pose", self.workspace / "shifted_pose"
        original = self.prepare(original_dir)
        for instance in self.recipe["instances"]:
            instance["transform"]["translation_mm"][0] += 1
        shifted = self.prepare(shifted_dir)
        check = shifted["assembly_plan"]["connection_checks"][0]
        self.assertEqual(check["upstream_center_mm"], [1., -68., 32.])
        self.assertEqual(check["downstream_center_mm"], [1., -67., 32.])
        self.assertEqual(check["gap_mm"], 1.)
        self.assertEqual(shifted["frontend_contract"]["guide_exit_center_mm"], dict(x=1., y=-68., z=32.))
        self.assertEqual(shifted["frontend_contract"]["source_exit_center_mm"], dict(x=1., y=-67., z=32.))
        gem = (shifted_dir / "inputs/frontend.gem").read_text()
        self.assertIn("locate(1,-50,-6)", gem)
        self.assertNotEqual(gem, (original_dir / "inputs/frontend.gem").read_text())
        self.assertEqual(json.loads((shifted_dir / "inputs/composition_plan.json").read_text()), shifted["assembly_plan"])
        def rows(directory):
            with (directory / "inputs/release_global.csv").open(newline="", encoding="utf-8") as handle:
                return list(csv.DictReader(handle))
        first, second = rows(original_dir), rows(shifted_dir)
        self.assertEqual(len(first), 100)
        for before, after in zip(first, second, strict=True):
            self.assertAlmostEqual(float(after["position_x_mm"]), float(before["position_x_mm"]) + 1, places=12)
            self.assertEqual({k: v for k, v in before.items() if k != "position_x_mm"},
                             {k: v for k, v in after.items() if k != "position_x_mm"})
        self.assertEqual(original["pulse_plan"], shifted["pulse_plan"])

    def test_parent_growth_preserves_selected_gem_field_source_and_clock(self):
        baseline_dir = self.workspace / "parent_two"
        baseline = self.prepare(baseline_dir)
        parent = json.loads(Path(self.request["composition_plan"]["path"]).read_text())
        for count in (3, 4):
            recipe, components = copy.deepcopy(parent["recipe"]), copy.deepcopy(parent["components"])
            for index in range(count - 2):
                extra = copy.deepcopy(recipe["instances"][0])
                extra["instance_id"] = f"spare_{index}"
                extra["transform"]["translation_mm"][0] += 1000 * (index + 1)
                recipe["instances"].append(extra)
                components[extra["instance_id"]] = copy.deepcopy(components["guide"])
            recipe["instances"].reverse()
            grown = compile_assembly_layout(recipe, components)
            grown["input_files"] = {key: dict(path="unavailable_" + key + ".json", sha256="A" * 64)
                                    for key in ("recipe", "components")}
            path = self.workspace / "parent_composition_plan.json"
            path.write_text(json.dumps(grown), encoding="utf-8")
            self.request["composition_plan"] = file_record(path)
            self.request["local_scope"] = dict(instance_ids=["guide", "accelerator"],
                research_scope="existing guide to OA transport",
                boundary_assumptions="unselected bodies do not participate in this local field")
            self.path.write_text(json.dumps(self.request), encoding="utf-8")
            output = self.workspace / f"parent_{count}_local"
            result = prepare_local_frontend(self.path, output, self.workspace,
                                           run_id="20261022_120000__test__python__parent-growth")
            for key in ("frontend_contract", "guide_contract", "registration", "pulse_plan", "cache_physical_inputs"):
                self.assertEqual(result[key], baseline[key], key)
            for name in ("frontend.gem", "frontend.pa+", "release_raw.csv", "release_global.csv", "on_voltages.json",
                         "off_voltages.json", "clock_authority.json", "instrument_epoch.json"):
                self.assertEqual((output / "inputs" / name).read_bytes(), (baseline_dir / "inputs" / name).read_bytes(), name)
            self.assertEqual(len(json.loads((output / "inputs/parent_composition_plan.json").read_text())["recipe"]["instances"]), count)
            self.assertEqual(result["input_records"]["composition_plan"]["path"], str(output / "inputs/parent_composition_plan.json"))
            del self.request["local_scope"]
            self.path.write_text(json.dumps(self.request), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "selected scope requires"):
                prepare_local_frontend(self.path, None, self.workspace)

    def test_frozen_parent_interface_and_identity_are_not_reconstructed_away(self):
        path = Path(self.request["composition_plan"]["path"])
        parent = json.loads(path.read_text())
        parent["components"]["accelerator"]["geometry_profile_id"] = "different_published_design"
        parent = compile_assembly_layout(parent["recipe"], parent["components"])
        path.write_text(json.dumps(parent), encoding="utf-8")
        self.request["composition_plan"] = file_record(path)
        self.path.write_text(json.dumps(self.request), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "provider interface differs"):
            prepare_local_frontend(self.path, None, self.workspace)
        path.write_text(path.read_text() + "\n", encoding="utf-8")
        with self.assertRaises(AssertionError):
            prepare_local_frontend(self.path, self.workspace / "bad_parent",
                                   self.workspace, run_id="20261022_120000__test__python__bad-parent")

    def test_parent_consumption_reads_and_verifies_only_the_frozen_copy(self):
        from common.contracts import write_run_manifest as records
        from integrations.workflows.local_frontend import prepare as compiler
        output = self.workspace / "frozen_parent_only"
        original = Path(self.request["composition_plan"]["path"]).resolve()
        frozen = output / "inputs/parent_composition_plan.json"
        with (patch.object(records, "file_sha256", wraps=records.file_sha256) as digest,
              patch.object(compiler, "_load", wraps=compiler._load) as read):
            prepare_local_frontend(self.path, output, self.workspace,
                                   run_id="20261022_120000__test__python__frozen-parent")
        hashed = [Path(call.args[0]).resolve() for call in digest.call_args_list]
        loaded = [Path(call.args[0]).resolve() for call in read.call_args_list]
        self.assertNotIn(original, hashed)
        self.assertNotIn(original, loaded)
        self.assertEqual(hashed.count(frozen.resolve()), 1)
        self.assertEqual(loaded.count(frozen.resolve()), 1)

    def test_retired_inline_schema_is_rejected(self):
        self.request["schema_version"] = 2
        self.request["assembly_recipe"] = self.recipe
        del self.request["composition_plan"]
        self.path.write_text(json.dumps(self.request), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "request fields differ"):
            prepare_local_frontend(self.path, None, self.workspace)

    def test_duplicate_placement_and_bad_electrode_binding_fail_before_writes(self):
        original = copy.deepcopy(self.request)
        original_recipe = copy.deepcopy(self.recipe)
        for defect in ("second_transform", "missing_electrode", "duplicate_electrode", "wall_midplane"):
            with self.subTest(defect=defect):
                self.request = copy.deepcopy(original)
                self.recipe = copy.deepcopy(original_recipe)
                component = self.request["accelerator_component"]
                if defect == "second_transform":
                    component["transform"] = self.recipe["instances"][1]["transform"]
                elif defect == "missing_electrode":
                    component["local_electrode_ids"].pop("22")
                elif defect == "duplicate_electrode":
                    component["local_electrode_ids"]["22"] = component["local_electrode_ids"]["23"]
                else:
                    self.recipe["instances"][0]["transform"]["translation_mm"][1] += .5
                output = self.workspace / defect
                with self.assertRaises(ValueError):
                    self.prepare(output)
                self.assertFalse((output / "inputs/frontend.gem").exists())

    def test_rf_delay_preserves_full_births_discovery_and_actual_public_cache_identity(self):
        auto_dir, delay_dir = self.workspace / "automatic", self.workspace / "delayed"
        automatic = self.prepare(auto_dir)
        self.request["pulse"].update(policy_id=RF_DELAY_PULSE_POLICY, delay_rf_periods=25)
        delayed = self.prepare(delay_dir)
        expected_plan = dict(automatic["pulse_plan"], policy_id=RF_DELAY_PULSE_POLICY, delay_rf_periods=25)
        self.assertEqual(delayed["pulse_plan"], expected_plan)
        self.assertNotIn("delay_rf_periods", automatic["pulse_plan"])
        for name in ("release_raw.csv", "release_global.csv", "clock_authority.json", "instrument_epoch.json",
                     "frontend.gem", "frontend.pa+", "frontend_contract.json", "on_voltages.json", "off_voltages.json"):
            self.assertEqual((auto_dir / "inputs" / name).read_bytes(), (delay_dir / "inputs" / name).read_bytes(), name)
        self.assertEqual(delayed["particle_count"], 100)
        # Execute the actual public plan body; Python's identity is a synthetic
        # executable stand-in. No PA or vendor process is created or consumed.
        helper = field_support_tests.LocalFrontendFieldSupportTests()
        runtime = field_support_tests.RUNTIME
        auto_plan = helper.embedded("planCode", [auto_dir / "inputs", sys.executable, runtime])
        delay_plan = helper.embedded("planCode", [delay_dir / "inputs", sys.executable, runtime])
        self.assertEqual(auto_plan["identity"], delay_plan["identity"])
        self.assertEqual(canonical_pa_family_cache_key(auto_plan["identity"]),
                         canonical_pa_family_cache_key(delay_plan["identity"]))

    def test_rf_delay_author_contract_rejects_nonintegers_or_missing_extra_fields_before_writes(self):
        original = copy.deepcopy(self.request["pulse"])
        for value in (None, True, -1, 1.5, "25", float("inf")):
            with self.subTest(delay=value):
                self.request["pulse"] = dict(original, policy_id=RF_DELAY_PULSE_POLICY, delay_rf_periods=value)
                output = self.workspace / "invalid_delay"
                with self.assertRaises(ValueError):
                    self.prepare(output)
                self.assertFalse((output / "inputs/frontend.gem").exists())
        for pulse in (dict(original, policy_id=RF_DELAY_PULSE_POLICY),
                      dict(original, delay_rf_periods=25),
                      dict(original, policy_id=RF_DELAY_PULSE_POLICY, delay_rf_periods=25, actual_pulse_time_us=34)):
            self.request["pulse"] = pulse
            with self.assertRaises(ValueError):
                self.prepare(self.workspace / "invalid_delay")
        self.assertFalse((self.workspace / "invalid_delay/inputs/frontend.gem").exists())

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
            local_electrode_ids={"1": 9, "2": 10, "3": 11, "4": 15, "5": 14, "6": 12, "7": 13},
            electrode_voltages_v={"1": 0., "2": 4400., "3": 4000., "4": 2000., "5": 0., "6": 3000., "7": 1000.})
        instances = self.recipe["instances"]
        instances[0]["transform"]["translation_mm"] = [5., -100., 32.]
        instances[1]["transform"] = RigidTransform("sectioned_accelerator_cartesian", "mrtof_global_cartesian", [[0,1,0],[1,0,0],[0,0,-1]], [3.,-50.,34.]).to_contract()
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
                       lambda r: self.recipe["instances"][0]["transform"].update(from_frame_id="wrong_provider_frame")):
            original = copy.deepcopy(self.request)
            change(self.request)
            output = self.workspace / "never_created"
            with self.assertRaises(ValueError):
                self.prepare(output)
            self.assertFalse((output / "inputs/frontend.gem").exists())
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
        for mode in ("unbound", "failed", "identity", "nonfinite"):
            with self.subTest(mode=mode):
                value = copy.deepcopy(baseline)
                if mode == "unbound":
                    del value["inputs"]["release_csv"]
                elif mode == "failed":
                    value["status"] = "failed"
                elif mode == "identity":
                    value["inputs"]["release_csv"]["sha256"] = "0" * 64
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
            actual = list(csv.DictReader(handle))
        self.assertEqual([float(row["instrument_time_us"]) for row in actual],
                         [float(row["birth_time_s"])*1e6 for row in rows])
        self.assertEqual([int(row["particle_id"]) for row in actual], list(range(1, 101)))
        identity = json.loads((output / "inputs/source_identity.json").read_text())
        self.assertEqual(identity["native_clock_projection"]["native_fly2_tob_us"], 0)
        self.assertTrue(identity["native_clock_projection"]["program_birth_time_restore_required"])


class PulseDecisionTests(unittest.TestCase):
    def fixture(self, *, policy=RF_DELAY_PULSE_POLICY, delay=25):
        plan = dict(policy_id=policy, rf_period_us=1e6 / 3.7e6, source_birth_time_range_us=[0., 0.])
        if policy == RF_DELAY_PULSE_POLICY:
            plan["delay_rf_periods"] = delay
        recommended = 27.793500142888146
        actual = recommended if policy == AUTOMATIC_PULSE_POLICY else recommended + delay * plan["rf_period_us"]
        candidate = dict(candidate_time_us=actual, pulse_eligible_count=2, eligible_ids=[2, 100], unsupported_ids=[])
        selection = dict(status="selected", selected_time_us=recommended,
                         selection_uses_future_terminal_outcome=False, candidates=[candidate])
        return dict(pulse_plan=plan, numerics=dict(maximum_flight_us=200.)), selection, actual

    def test_delay_uses_one_formula_and_preserves_automatic_float_bits(self):
        for policy in (AUTOMATIC_PULSE_POLICY, RF_DELAY_PULSE_POLICY):
            with self.subTest(policy=policy):
                prepared, selection, actual = self.fixture(policy=policy)
                before = copy.deepcopy(selection)
                decision = resolve_pulse_decision(prepared, selection)
                self.assertEqual(decision["actual_pulse_time_us"].hex(), actual.hex())
                self.assertEqual(decision["recommendation_time_us"], selection["selected_time_us"])
                self.assertEqual(decision["recommendation_policy_id"], AUTOMATIC_PULSE_POLICY)
                self.assertEqual(decision["applied_policy_id"], policy)
                self.assertEqual(decision["status"], "ready")
                self.assertTrue(decision["same_rf_phase_by_integer_cycles"])
                self.assertFalse(decision["source_population_changed"])
                self.assertEqual(selection, before)

    def test_record_matching_never_snaps_actual_time_and_unsupported_target_stops(self):
        prepared, selection, actual = self.fixture()
        candidate = selection["candidates"][0]
        candidate["candidate_time_us"] = actual + 32 * math.ulp(actual)
        result = resolve_pulse_decision(prepared, selection)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["actual_pulse_time_us"], actual)
        self.assertEqual(result["target_occupancy"]["candidate_minus_actual_us"], 32 * math.ulp(actual))
        self.assertFalse(result["target_occupancy"]["exact_time_match"])
        candidate["unsupported_ids"] = [16]
        self.assertEqual(resolve_pulse_decision(prepared, selection)["status"], "target_snapshot_unsupported")
        candidate["candidate_time_us"] = actual + 33 * math.ulp(actual)
        self.assertEqual(resolve_pulse_decision(prepared, selection)["status"], "target_snapshot_missing")
        # A fully supported but empty occupancy is evidence, not a reason to
        # reselect a more successful time or discard any original source ID.
        candidate.update(candidate_time_us=actual, eligible_ids=[], pulse_eligible_count=0, unsupported_ids=[])
        self.assertEqual(resolve_pulse_decision(prepared, selection)["status"], "ready")
        selection["candidates"].append(copy.deepcopy(candidate))
        with self.assertRaisesRegex(ValueError, "multiple recorded"):
            resolve_pulse_decision(prepared, selection)

    def test_invalid_horizon_recommendation_or_occupancy_is_rejected(self):
        for mode in ("late", "future_outcome", "no_recommendation", "nonfinite", "bad_count", "overlap", "noninteger"):
            with self.subTest(mode=mode):
                prepared, selection, _ = self.fixture()
                if mode == "late":
                    prepared["numerics"]["maximum_flight_us"] = 30.
                elif mode == "future_outcome":
                    selection["selection_uses_future_terminal_outcome"] = True
                elif mode == "no_recommendation":
                    selection["status"] = "no_eligible_actual_candidate"
                elif mode == "nonfinite":
                    selection["selected_time_us"] = float("nan")
                elif mode == "bad_count":
                    selection["candidates"][0]["pulse_eligible_count"] = 3
                elif mode == "overlap":
                    selection["candidates"][0]["unsupported_ids"] = [2]
                else:
                    prepared["pulse_plan"]["delay_rf_periods"] = True
                with self.assertRaises(ValueError):
                    resolve_pulse_decision(prepared, selection)


if __name__ == "__main__":
    unittest.main()
