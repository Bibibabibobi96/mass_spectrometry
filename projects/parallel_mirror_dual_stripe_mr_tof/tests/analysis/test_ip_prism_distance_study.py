"""Frozen measured-source and local numerical contracts; no vendor process."""
from __future__ import annotations

import copy
import csv
import shutil
import json
from pathlib import Path
import sys
import struct
import tempfile
import types
import unittest
from unittest.mock import patch

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ip_prism_distance_study import (
    lua_literal, read_source, validate_contract, validate_contour_contract, validate_replay_contract, prepare_replay_package, analyze_replay_package,
    prepare, prepare_recorded_analysis, validate_fields, main, _contour_source_tables, _contour_geometry_and_voltage, _freeze_recorded_contour_source, _freeze_completed_field_source,
)
from common.contracts.write_run_manifest import file_record
from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_ip_prism_local_geometry import fixture

MODULE = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.ip_prism_distance_study"


class DistanceContractTests(unittest.TestCase):
    def setUp(self):
        self.contract=dict(schema_version=1,role="ip_prism_distance_experiment",
                           references={k:{} for k in ("geometry","voltages","component_particle_state","source_census","native_timing")},
                           distances_mm=[52.828,10,15,20],numerics=dict(box_mm=[0,-105,-120,16,-25,25],pitch_mm=[.1,.2,.1],
                           convergence_v=1e-5,maximum_step_us=.001,sample_interval_us=.002,maximum_flight_us=10,
                           trajectory_quality=8,probe_step_mm=.1),observation_planes=[dict(name="p1_exit",z_mm=-98)],
                           committed_new_bytes=1000,limits={},claim="local fixed measured states",official_sources=[])

    def test_physical_controls_are_explicit(self):
        validate_contract(self.contract)
        invalid=copy.deepcopy(self.contract)
        del invalid["numerics"]["maximum_step_us"]
        with self.assertRaisesRegex(ValueError,"complete local numerical"):
            validate_contract(invalid)
        invalid=copy.deepcopy(self.contract)
        invalid["distances_mm"]=[10,10]
        with self.assertRaisesRegex(ValueError,"distinct positive"):
            validate_contract(invalid)

    def test_lua_projection_rejects_nonfinite(self):
        self.assertIn('["vz"]=-40',lua_literal({"vz":-40,"frame":"MR"}))
        with self.assertRaises(ValueError):
            lua_literal(float("nan"))

    def test_measured_source_keeps_missing_mother_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=dict(particle_id=1,instrument_time_us=7500.7,mass_amu=524,charge_state=1,
                        position_x_mm=.1,position_y_mm=-55,position_z_mm=0,
                        velocity_x_m_s=20,velocity_y_m_s=10,velocity_z_m_s=-40000)
            census=[dict(particle_id=1,transfer_status="transferred"),dict(particle_id=2,transfer_status="not_transferred")]
            for name,rows in (("source",[source]),("census",census)):
                with (root/f"{name}.csv").open("w",newline="") as stream:
                    writer=csv.DictWriter(stream,fieldnames=rows[0].keys());writer.writeheader();writer.writerows(rows)
            actual,mother=read_source(root/"source.csv",root/"census.csv")
            self.assertEqual((len(actual),len(mother)),(1,2))
            source["velocity_z_m_s"]=40000
            with (root/"source.csv").open("w",newline="") as stream:
                writer=csv.DictWriter(stream,fieldnames=source.keys());writer.writeheader();writer.writerow(source)
            with self.assertRaisesRegex(ValueError,"negative z"):
                read_source(root/"source.csv",root/"census.csv")


class ContourPreparationTests(unittest.TestCase):
    def contract(self):
        numerical = DistanceContractTests()
        numerical.setUp()
        old = numerical.contract
        return dict(schema_version=6, electrode_collision_model="canonical_lens_first_contact", role="ip_prism_contour_focus_experiment",field_sources={"B_field":{"action":"build"}},
                    references={"geometry": {}, "voltages": {}},
                    source_registration=dict(translation_mm=[0, -225, 0], from_frame_id="IP-world", to_frame_id="test_frame"),
                    cases=[dict(case_id="B", label="B formed", source_run="source_B", distance_mm=10,
                                pitch_mm=[.1, .2, .2], maximum_step_us=.001, field_case_id="B_field", physical_aperture=None, lens_elements=[]),
                           dict(case_id="B_half_dt", label="B half step", source_run="source_B", distance_mm=10,
                                pitch_mm=[.1, .2, .2], maximum_step_us=.0005, field_case_id="B_field", physical_aperture=None, lens_elements=[])],
                    numerics=old["numerics"], observation_planes=old["observation_planes"],
                    aperture_comparison=dict(plane_names=["p1_exit"], half_widths_mm=[.1, .2], center_x_mm=0,
                                             center_y_mm=-55, slit_x_half_width_mm=None, reference_case_id="B", frame="reference_normal"),
                    plain_lua_executable="lua.exe", committed_new_bytes=1000, claim="local actual-field comparison",
                    official_sources=[])

    def test_explicit_contour_contract_and_invalid_fields(self):
        contract = self.contract()
        validate_contour_contract(contract)
        self.assertNotIn("limits", contract)
        for update in (lambda c: c.update(extra="unknown"),
                       lambda c: c.update(schema_version=1),
                       lambda c: c.update(schema_version=2, limits={}),
                       lambda c: c.update(schema_version=3),
                       lambda c: c.update(schema_version=4),
                       lambda c: c.update(field_sources={}),
                       lambda c: c.update(field_sources={"B_field":{"action":"reuse","source_run":"relative","source_field_case_id":"B"}}),
                       lambda c: c.update(limits={}),
                       lambda c: c["cases"][0].pop("physical_aperture"),
                       lambda c: c["cases"][0].update(physical_aperture=True),
                       lambda c: c["cases"][0].pop("lens_elements"),
                       lambda c: c["cases"][0].update(lens_elements=None),
                       lambda c: c["cases"][0].update(lens_elements=[True]),
                       lambda c: c["source_registration"]["translation_mm"].__setitem__(2, 1),
                       lambda c: c["cases"][1].update(case_id="B"),
                       lambda c: c["cases"][0].update(pitch_mm=[.1, float("nan"), .2]),
                       lambda c: c["aperture_comparison"].update(plane_names=["unrecorded"]),
                       lambda c: c["aperture_comparison"].update(frame="implicit"),
                       lambda c: c["aperture_comparison"].update(reference_case_id="missing")):
            invalid = copy.deepcopy(contract)
            update(invalid)
            with self.assertRaises(ValueError):
                validate_contour_contract(invalid)

    def test_recorded_v2_author_is_readonly_and_not_an_active_prepare_contract(self):
        contract=dict(self.contract(), schema_version=2, limits={"transient_run_directory_bytes":1000})
        contract.pop("field_sources"); contract.pop("electrode_collision_model")
        for row in contract["cases"]:
            row.pop("lens_elements")
        validate_contour_contract(contract, recorded_author=True)
        with self.assertRaises(ValueError):
            validate_contour_contract(contract)
        del contract["limits"]
        with self.assertRaises(ValueError):
            validate_contour_contract(contract, recorded_author=True)
        third=self.contract();third["schema_version"]=3;third.pop("field_sources"); third.pop("electrode_collision_model")
        for row in third["cases"]:
            row.pop("lens_elements")
        validate_contour_contract(third,recorded_author=True)
        with self.assertRaises(ValueError):
            validate_contour_contract(third)

    def test_explicit_collision_model_and_recorded_v5(self):
        for model in ("native_pa", "canonical_lens_first_contact"):
            contract = self.contract()
            contract["electrode_collision_model"] = model
            validate_contour_contract(contract)
        for model in (None, "nearest_node", ""):
            contract = self.contract()
            contract["electrode_collision_model"] = model
            with self.assertRaises(ValueError):
                validate_contour_contract(contract)
        old = self.contract()
        old["schema_version"] = 5
        old.pop("electrode_collision_model")
        validate_contour_contract(old, recorded_author=True)
        with self.assertRaises(ValueError):
            validate_contour_contract(old)

    def test_recorded_v4_is_readonly_and_retains_original_fields(self):
        fourth = self.contract()
        fourth["schema_version"] = 4
        fourth.pop("electrode_collision_model")
        for row in fourth["cases"]:
            row.pop("lens_elements")
        validate_contour_contract(fourth, recorded_author=True)
        with self.assertRaises(ValueError):
            validate_contour_contract(fourth)

    def source_case(self, path):
        path.mkdir()
        (path/"simion").mkdir()
        rows = [dict(event="source", particle_id=1, reason="birth", t_us=0, x_mm=0, y_mm=170, z_mm=0,
                     vx_mm_us=.1, vy_mm_us=.2, vz_mm_us=-40),
                dict(event="extraction_exit", particle_id=1, reason="acceptance_surface", t_us=7500.7,
                     x_mm=.1, y_mm=170, z_mm=0, vx_mm_us=.1, vy_mm_us=.2, vz_mm_us=-40),
                dict(event="terminal", particle_id=1, reason="acceptance_surface", t_us=7500.7,
                     x_mm=.1, y_mm=170, z_mm=0, vx_mm_us=.1, vy_mm_us=.2, vz_mm_us=-40),
                dict(event="terminal", particle_id=2, reason="solver_stop", t_us=10,
                     x_mm=0, y_mm=1, z_mm=1, vx_mm_us=0, vy_mm_us=0, vz_mm_us=0)]
        with (path/"simion/events.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
        model = dict(coordinate_transform=dict(to_frame_id="IP-world"), baseline=dict(clock=dict(epoch_us=100)),
                     source=dict(species=dict(mass_amu=524, charge_state=1)), native_timing=dict(pulse_start_us=7500.2))
        return dict(run=str(path), config=model, sources={1: rows[0], 2: rows[-1]}, exits={1: rows[1]},
                    terminals={1: rows[2], 2: rows[3]}, source_records=[dict(path=str(path/"simion/events.csv"), sha256="ABC")])

    def test_recorded_tables_keep_failed_mother_identity_clock_and_velocity(self):
        with tempfile.TemporaryDirectory() as directory:
            case = self.source_case(Path(directory)/"source")
            source, census = _contour_source_tables(case, self.contract()["source_registration"])
            self.assertEqual(source[0]["position_y_mm"], -55)
            self.assertEqual(source[0]["instrument_time_us"], 7600.7)
            self.assertEqual(source[0]["velocity_z_m_s"], -40000)
            self.assertEqual(census[1]["transfer_status"], "not_transferred")
            self.assertEqual(census[1]["terminal_reason"], "solver_stop")
            self.assertEqual(census[1]["raw_line_number"], 5)
            self.assertEqual(len(census[1]["raw_line_sha256"]), 64)

    def test_prepare_materializes_case_specific_sources_and_shared_field_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root/"run";run.mkdir();(run/"inputs").mkdir()
            (run/"run_config.json").write_text(json.dumps(dict(inputs={}, parameters={})))
            contract = self.contract()
            source_run = root/"native"
            case = self.source_case(source_run)
            for row in contract["cases"]:
                row["source_run"] = str(source_run)
            cp = root/"contract.json";cp.write_text(json.dumps(contract))
            geometry = fixture()
            gf = root/"geometry.json";gf.write_text(json.dumps(geometry))
            vf = root/"voltages.json";vf.write_text(json.dumps(dict(analyzer_electrode_voltages_v=list(range(25)))))
            mock_diagnostics = types.ModuleType("projects.parallel_mirror_dual_stripe_mr_tof.analysis.ip_prism_focus_diagnostics")
            mock_diagnostics.analyze_focus_study = lambda _: {}
            projection = dict(values_v15=list(range(15)), source_native_drive=dict(sha256="schedule"))
            with patch.dict(sys.modules, {mock_diagnostics.__name__: mock_diagnostics}), \
                 patch(MODULE+".freeze_references", return_value=dict(geometry=gf, voltages=vf)), \
                 patch(MODULE+"._freeze_recorded_contour_source", return_value=case) as loader, \
                 patch(MODULE+"._contour_geometry_and_voltage", return_value=(geometry, projection)), \
                 patch(MODULE+".load_particle_count_policy", return_value=dict(functional_check_count=2)), \
                 patch(MODULE+".freeze_code"):
                result = prepare(run, cp)
                self.assertEqual(loader.call_count, 1)
                physical = copy.deepcopy(contract)
                plate = dict(frame_id="test_frame", shape="circle", center_mm=[0, -55, -45],
                             normal=[0, 0, -1], thickness_mm=.4, outer_half_widths_mm=[3, 1],
                             voltage_v=0, connection="prism_ground_shield", radius_mm=.3)
                physical["cases"][1].update(case_id="B_circle", field_case_id="B_circle_field", physical_aperture=plate)
                slit = copy.deepcopy(physical["cases"][1])
                slit.update(case_id="B_slit", field_case_id="B_slit_field")
                slit["physical_aperture"].update(shape="y_slit", half_widths_mm=[.8, .3])
                slit["physical_aperture"].pop("radius_mm")
                physical["cases"].append(slit)
                physical["field_sources"]={r["field_case_id"]:{"action":"build"} for r in physical["cases"]}
                cp.write_text(json.dumps(physical))
                physical_run=root/"physical_run";physical_run.mkdir();(physical_run/"inputs").mkdir()
                (physical_run/"run_config.json").write_text(json.dumps(dict(inputs={}, parameters={})))
                plates=prepare(physical_run,cp)
                self.assertEqual(len(plates["build_cases"]),3)
                self.assertEqual(len({row["field_path"] for row in plates["cases"]}),3)
                for row in plates["cases"][1:]:
                    saved=json.loads((Path(row["directory"])/"geometry.json").read_text())
                    self.assertEqual(saved["geometry"]["aperture_electrodes"][0]["specification"],row["physical_aperture"])
                    self.assertIn("namespace=physical_aperture",(Path(row["directory"])/"field.gem").read_text())
                    self.assertEqual(Path(row["source_csv"]).read_bytes(),Path(plates["cases"][0]["source_csv"]).read_bytes())
                heterogeneous=copy.deepcopy(contract)
                fine=copy.deepcopy(heterogeneous["cases"][0])
                fine.update(case_id="B_fine",field_case_id="B_fine_field",pitch_mm=[.05,.1,.1])
                heterogeneous["cases"].append(fine)
                heterogeneous["field_sources"]={r["field_case_id"]:{"action":"build"} for r in heterogeneous["cases"]}
                cp.write_text(json.dumps(heterogeneous))
                mixed_run=root/"mixed_run";mixed_run.mkdir();(mixed_run/"inputs").mkdir()
                (mixed_run/"run_config.json").write_text(json.dumps(dict(inputs={},parameters={})))
                mixed=prepare(mixed_run,cp)
                self.assertNotIn("limits",mixed)
                self.assertEqual([c["case_id"] for c in mixed["cases"]],["B","B_half_dt","B_fine"])
                self.assertEqual(mixed["build_cases"][0]["case_id"],"B_fine")
                self.assertEqual(mixed["flight_cases"][0]["case_id"],"B_fine")
                self.assertGreater(mixed["flight_cases"][0]["field_node_count"],mixed["flight_cases"][-1]["field_node_count"])
                self.assertEqual(mixed["dispatch_policy"]["first_formal_observation"],"wait_for_natural_completion")
                mixed_request=json.loads((mixed_run/"inputs/simion_dispatch_request.json").read_text())
                self.assertEqual(mixed_request["frontend_cell_mm_xyz"],[.05,.1,.1])
                lens_contract = copy.deepcopy(contract)
                for row in lens_contract["cases"]:
                    row["distance_mm"] = 52.828
                lens_case = lens_contract["cases"][1]
                lens_case["field_case_id"] = "B_quadrupole_field"
                lens_case["lens_elements"] = [dict(name="Q1", frame_id="test_frame", center_mm=[0, -55, -13],
                    length_mm=5, inscribed_radius_mm=1.4, rod_radius_mm=.2, voltage_v=1)]
                lens_contract["field_sources"] = {r["field_case_id"]: {"action": "build"} for r in lens_contract["cases"]}
                cp.write_text(json.dumps(lens_contract))
                lens_run=root/"lens_run";lens_run.mkdir();(lens_run/"inputs").mkdir()
                (lens_run/"run_config.json").write_text(json.dumps(dict(inputs={}, parameters={})))
                lens_result = prepare(lens_run, cp)
                self.assertEqual(len(lens_result["field_owners"]), 2)
                no_lens, with_lens = lens_result["cases"]
                self.assertEqual(Path(no_lens["source_csv"]).read_bytes(), Path(with_lens["source_csv"]).read_bytes())
                rod_geometry = json.loads((Path(with_lens["directory"])/"geometry.json").read_text())
                self.assertEqual(len(rod_geometry["geometry"]["lens_electrodes"]), 4)
                self.assertEqual(rod_geometry["geometry"]["lens_electrodes"][0]["specification"], lens_case["lens_elements"][0])
                lens_case["field_case_id"] = lens_contract["cases"][0]["field_case_id"]
                lens_contract["field_sources"].pop("B_quadrupole_field")
                cp.write_text(json.dumps(lens_contract))
                bad_lens=root/"bad_lens";bad_lens.mkdir();(bad_lens/"inputs").mkdir()
                (bad_lens/"run_config.json").write_text(json.dumps(dict(inputs={}, parameters={})))
                with self.assertRaisesRegex(ValueError, "shared field_case_id"):
                    prepare(bad_lens, cp)
                conflicting = root/"conflicting_run";conflicting.mkdir();(conflicting/"inputs").mkdir()
                (conflicting/"run_config.json").write_text(json.dumps(dict(inputs={}, parameters={})))
                contract["cases"][1]["pitch_mm"] = [.2, .2, .2]
                cp.write_text(json.dumps(contract))
                with self.assertRaisesRegex(ValueError, "shared field_case_id"):
                    prepare(conflicting, cp)
            self.assertEqual(result["role"], "resolved_ip_prism_contour_focus_study")
            first, second = result["cases"]
            self.assertEqual((first["source_count"], first["mother_count"]), (1, 2))
            self.assertEqual(second["maximum_step_us"], .0005)
            self.assertEqual(first["field_case_id"], second["field_case_id"])
            self.assertEqual(first["field_path"], second["field_path"])
            self.assertEqual(result["build_cases"], [first])
            lua_config=(Path(second["directory"])/"case_config.lua").read_text()
            self.assertIn('["field_path"]=',lua_config)
            self.assertEqual((Path(first["directory"])/"field.gem").read_bytes(), (Path(second["directory"])/"field.gem").read_bytes())
            self.assertTrue(Path(first["source_census_csv"]).is_file())
            states = json.loads((Path(first["directory"])/"source_states.json").read_text())
            self.assertEqual(states[0]["vz_mm_us"], -40)
            self.assertEqual(states[0]["t_us"], 7600.7)
            self.assertAlmostEqual(states[0]["z_mm"], -42.828)
            request = json.loads((run/"inputs/simion_dispatch_request.json").read_text())
            self.assertEqual(request["work_item_count"], 2)
            self.assertEqual(request["workload_topology_id"],"shared_ordinary_static_local_field_fly_only")
            build=json.loads((run/"inputs/simion_build_dispatch_request.json").read_text())
            self.assertEqual(build["work_item_count"],1)
            self.assertEqual(build["workload_topology_id"],"one_local_static_refine_per_unique_field")
            self.assertNotEqual(build["field_loading_policy_id"],request["field_loading_policy_id"])

    def test_current_voltage_schedule_mismatch_fails_before_plain_lua(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory);source_inputs=root/"inputs";(source_inputs/"simion").mkdir(parents=True)
            (source_inputs/"simion/native_drive.lua").write_text("old")
            current = root/"projects/dual_pressure_rectilinear_ion_processor/simion/native_drive.lua"
            current.parent.mkdir(parents=True);current.write_text("changed")
            case = dict(config=dict(coordinate_transform=dict(from_frame_id="native", to_frame_id="IP-world"),
                                    native_projection=dict(frame_id="native")))
            with patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_flight_preparation.project_provider_voltages") as projection:
                with self.assertRaisesRegex(ValueError, "schedule differs"):
                    _contour_geometry_and_voltage(case, self.contract()["source_registration"], fixture(), source_inputs, root/"lua.exe", root)
                projection.assert_not_called()

    def test_current_waveforms_mismatch_fails_before_plain_lua(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); inputs = root/'inputs'; (inputs/'simion').mkdir(parents=True)
            native = root/'projects/dual_pressure_rectilinear_ion_processor/simion/native_drive.lua'
            native.parent.mkdir(parents=True); native.write_text('return {}')
            (inputs/'simion/native_drive.lua').write_text('return {}')
            (root/'common/simion').mkdir(parents=True)
            (root/'common/simion/voltage_waveforms.lua').write_text('return {changed=true}')
            (inputs/'simion/voltage_waveforms.lua').write_text('return {producer=731}')
            case = dict(config=dict(coordinate_transform=dict(from_frame_id='native',to_frame_id='IP-world'),
                native_projection=dict(frame_id='native')))
            helper = 'projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_flight_preparation.project_provider_voltages'
            with patch(helper) as projection, self.assertRaisesRegex(ValueError, 'voltage_waveforms'):
                _contour_geometry_and_voltage(case, self.contract()['source_registration'], fixture(), inputs, root/'lua.exe', root)
            projection.assert_not_called()

    def test_failed_source_freezes_verified_small_projection_without_relabeling(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/"native";source.mkdir();(source/"inputs").mkdir();(source/"simion").mkdir()
            (source/"inputs/resolved_model.json").write_text("{}")
            (source/"simion/native_drive.lua").write_text("return {}")
            (source/"simion/voltage_waveforms.lua").write_text("return {producer=731}")
            waveform=file_record(source/"simion/voltage_waveforms.lua")
            record=file_record(source/"inputs/resolved_model.json")
            schedule=file_record(source/"simion/native_drive.lua")
            manifest=dict(status="failed",role="simulation_run_manifest",run_id=source.name,
                          project="dual_pressure_rectilinear_ion_processor",inputs={"model":record},outputs=[schedule,waveform])
            (source/"run_manifest.json").write_text(json.dumps(manifest))
            original=(source/"run_manifest.json").read_bytes()
            case=dict(source_records=[record], terminals={1: {}, 2: {}})
            loader="projects.dual_pressure_rectilinear_ion_processor.analysis.extraction_phase_space_comparison.load_recorded_case"
            with patch(loader, return_value=case) as measured:
                result=_freeze_recorded_contour_source(source, "B", root/"frozen")
            measured.assert_called_once_with(source, "B", allow_failed=True)
            self.assertIs(result,case)
            binding=json.loads((root/"frozen/consumption_binding.json").read_text())
            self.assertEqual(binding["producer_status"],"failed")
            self.assertEqual(binding["physical_terminal_count"],2)
            self.assertEqual(binding["source_manifest"]["sha256"],binding["producer_manifest"]["sha256"])
            self.assertEqual((source/"run_manifest.json").read_bytes(),original)
            self.assertEqual((root/"frozen/inputs/resolved_model.json").read_bytes(),b"{}")
            self.assertEqual(binding["records"][-2]["frozen"]["sha256"],schedule["sha256"])
            with patch(loader, return_value=case):
                # The schedule may be an input instead of an output; ownership remains IP.
                manifest["inputs"]["drive"]=schedule;manifest["inputs"]["waveforms"]=waveform;manifest["outputs"]=[]
                (source/"run_manifest.json").write_text(json.dumps(manifest))
                _freeze_recorded_contour_source(source,"B",root/"input_bound")
                (source/"simion/native_drive.lua").write_text("return []")
                with self.assertRaisesRegex(AssertionError,"SHA-256 changed"):
                    _freeze_recorded_contour_source(source,"B",root/"tampered")
                (source/"simion/native_drive.lua").unlink()
                with self.assertRaisesRegex(AssertionError,"is missing"):
                    _freeze_recorded_contour_source(source,"B",root/"missing_payload")
                manifest["inputs"].pop("drive")
                (source/"run_manifest.json").write_text(json.dumps(manifest))
                with self.assertRaisesRegex(ValueError,"not manifest-bound"):
                    _freeze_recorded_contour_source(source,"B",root/"unbound")

    def test_validate_fields_cli_runs_mesh_only_after_successful_contour_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory);(run/"inputs").mkdir()
            resolved=run/"inputs/resolved_study.json"
            resolved.write_text(json.dumps(dict(role="resolved_ip_prism_contour_focus_study")))
            arguments=["study","validate-fields","--run",str(run)]
            mesh="projects.parallel_mirror_dual_stripe_mr_tof.analysis.ip_prism_mesh_diagnostics.export_mesh_diagnostics"
            theory="projects.parallel_mirror_dual_stripe_mr_tof.analysis.ip_prism_field_theory.export_field_theory"
            with patch.object(sys,"argv",arguments), patch(MODULE+".validate_fields") as validate,patch(mesh) as export,patch(theory) as predict:
                order=[];validate.side_effect=lambda _:order.append("validate");export.side_effect=lambda _:order.append("mesh");predict.side_effect=lambda _:order.append("theory")
                main()
                self.assertEqual(order,["validate","mesh","theory"])
                export.assert_called_once_with(run)
                predict.assert_called_once_with(run)
            with patch.object(sys,"argv",arguments),patch(MODULE+".validate_fields",side_effect=ValueError("bad PA")),patch(mesh) as export,patch(theory) as predict:
                with self.assertRaisesRegex(ValueError,"bad PA"):
                    main()
                export.assert_not_called()
                predict.assert_not_called()
            with patch.object(sys,"argv",arguments),patch(MODULE+".validate_fields"),patch(mesh,side_effect=ValueError("bad topology")),patch(theory) as predict:
                with self.assertRaisesRegex(ValueError,"bad topology"):
                    main()
                predict.assert_not_called()
            resolved.write_text(json.dumps(dict(role="resolved_ip_prism_distance_study")))
            with patch.object(sys,"argv",arguments),patch(MODULE+".validate_fields"),patch(mesh) as export:
                main()
                export.assert_not_called()

    def test_voltage_projection_reuses_native_schedule_and_exact_convex_pose(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);inputs=root/"inputs";(inputs/"simion").mkdir(parents=True)
            native=root/"projects/dual_pressure_rectilinear_ion_processor/simion/native_drive.lua"
            native.parent.mkdir(parents=True);native.write_text("return {}")
            (inputs/"simion/native_drive.lua").write_text("return {}")
            (root/"common/simion").mkdir(parents=True)
            (root/"common/simion/voltage_waveforms.lua").write_text("return {}")
            (inputs/"simion/voltage_waveforms.lua").write_text("return {}")
            dependency=root/"projects/parallel_mirror_dual_stripe_mr_tof/config/ion_processor_dependency.json"
            dependency.parent.mkdir(parents=True);dependency.write_text("{}")
            shape=dict(shape="convex_polyhedron", vertices_mm=[[0,0,0],[2,0,0],[0,3,0],[0,0,4]])
            model=dict(coordinate_transform=dict(from_frame_id="native",to_frame_id="IP-world",
                       rotation=[[0,0,-1],[1,0,0],[0,-1,0]],translation_mm=[0,0,9.8]),
                       native_projection=dict(frame_id="native",electrodes=[dict(electrode_id=11,solids=[shape],cutouts=[])]),
                       source=dict(species=dict(mass_amu=524,charge_state=1)),native_operating_point=dict(lift_v=4480))
            case=dict(config=model,exits={1:dict(vz_mm_us=-40)})
            projection=dict(values_v15=list(range(15)),evaluated_native_operating_point=model["native_operating_point"])
            helper="projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_flight_preparation.project_provider_voltages"
            with patch(helper,return_value=projection) as native_projection:
                geometry,actual=_contour_geometry_and_voltage(case,self.contract()["source_registration"],fixture(),inputs,root/"lua.exe",root)
            arguments=native_projection.call_args.args
            self.assertEqual(arguments[1]["policies"]["energy_adjustment"],"preserve_measured_workpoint")
            self.assertGreater(arguments[1]["target"]["axial_energy_per_charge_v"],4000)
            self.assertIs(actual,projection)
            moved=geometry["ion_processor_electrodes"][0]["solids"][0]
            self.assertEqual(moved["shape"],"convex_polyhedron")
            self.assertEqual(moved["vertices_mm"],[[0,-225,9.8],[0,-223,9.8],[0,-225,6.800000000000001],[-4,-225,9.8]])
            self.assertEqual(shape["vertices_mm"][0],[0,0,0])

    def test_all_new_field_nodes_and_grid_checked_before_flight(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory);(run/"inputs").mkdir();folder=run/"case";folder.mkdir()
            path=folder/"field.pa"
            case=dict(case_id="B",field_case_id="B_field",field_path=str(path),directory=str(folder))
            (run/"inputs/resolved_study.json").write_text(json.dumps(dict(cases=[case,case],build_cases=[case])))
            checks=dict(grid_dimensions=[3,2,2],pitch_mm=[.1,.2,.1],boundary_mode="grounded_five_faces_x_mirror")
            (folder/"geometry.json").write_text(json.dumps(dict(geometry_checks=checks)))
            header=struct.pack('<iidiiiiddd',-2,1,100,3,2,2,1,.1,.2,.1)
            path.write_bytes(header+struct.pack('<12d',*range(12)))
            valid=validate_fields(run)
            self.assertEqual(len(valid["fields"]),1)
            self.assertEqual(valid["fields"][0]["validated_nodes"],12)
            self.assertFalse(valid["fields"][0]["full_pa_hash_performed"])
            for bad in (float("nan"),301.):
                path.write_bytes(header+struct.pack('<12d',*([0]*11+[bad])))
                with self.subTest(bad=bad),self.assertRaises(ValueError):
                    validate_fields(run)
                failed=json.loads((run/"results/pa_payload_validation.json").read_text())
                self.assertEqual(failed["status"],"FAIL")
                self.assertEqual(failed["failed_field_path"],str(path))
            path.write_bytes(header+struct.pack('<12d',*range(12)))
            checks["pitch_mm"][2]=.2
            (folder/"geometry.json").write_text(json.dumps(dict(geometry_checks=checks)))
            with self.assertRaisesRegex(ValueError,"grid or x-mirror"):
                validate_fields(run)


class RecordedContourAnalysisTests(unittest.TestCase):
    def _failed_native_source(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis import test_ip_prism_local_diagnostics as f
        fixture=f.LocalPrismDiagnosticsTests("test_empty_statistics_do_not_invent_fwhm")
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        source=fixture.run;folder=source/"simion/case_01";folder.parent.mkdir()
        shutil.move(str(source/"case_current"),folder)
        for name in ("axis_field.csv","geometry.json","source_occupancy.csv"):
            (folder/name).write_text("small bound evidence")
        case=dict(fixture.contract["cases"][0],directory=str(folder),source_count=2,mother_count=3,mass_u=524.,
                  source_run="original-IP",source_csv=str(source/"inputs/component_particle_state.csv"),
                  source_census_csv=str(source/"inputs/source_census.csv"))
        resolved=dict(role="resolved_ip_prism_contour_focus_study",cases=[case],
                      contract=dict(observation_planes=[dict(name=n,z_mm=z) for n,z in
                                          (("p1_near",-52.828),("p1_far",-82.),("p1_exit",-98.))]))
        (source/"inputs/resolved_study.json").write_text(json.dumps(resolved))
        projection=source/"inputs/native_sources/source_01/provider_voltage_projection.json"
        projection.parent.mkdir(parents=True);projection.write_text("{}")
        (source/"results").mkdir();(source/"logs").mkdir()
        (source/"summary.json").write_text(json.dumps(dict(role="ip_prism_distance_study_summary",status="failed",stage="automatic_local_diagnostics")))
        (source/"results/simion_batch_resource_usage.json").write_text(json.dumps(dict(role="multipole_resource_usage",status="completed",failure_class=None,execution_wave=dict(process_count=1))))
        (source/"logs/fly_batch_0001.log").write_text("IP_PRISM_CASE=PASS current stage=fly\n")
        (source/"run_config.json").write_text(json.dumps(dict(project="parallel_mirror_dual_stripe_mr_tof",run_id=source.name,inputs={})))
        case.update(directory="simion/case_01",source_csv="inputs/component_particle_state.csv",source_census_csv="inputs/source_census.csv")
        (source/"inputs/resolved_study.json").write_text(json.dumps(resolved))
        self._seal_failed_fixture(source)
        destination=source/"new_analysis";destination.mkdir();(destination/"inputs").mkdir()
        (destination/"run_config.json").write_text(json.dumps(dict(inputs={},parameters={})))
        return source,destination

    def _seal_failed_fixture(self, source):
        paths=[p for folder in (source/"inputs",source/"simion",source/"results",source/"logs")
               for p in folder.rglob("*") if p.is_file()]+[source/"summary.json"]
        manifest=dict(project="parallel_mirror_dual_stripe_mr_tof",run_id=source.name,status="failed",
                      run_config=file_record(source/"run_config.json"),inputs={},outputs=[file_record(p) for p in paths])
        (source/"run_manifest.json").write_text(json.dumps(manifest))

    def test_complete_failed_native_stage_is_consumed_without_pa_or_dense_sample_parse(self):
        source,destination=self._failed_native_source()
        loader="projects.parallel_mirror_dual_stripe_mr_tof.analysis.ip_prism_local_diagnostics._load_rows"
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ip_prism_local_diagnostics as local
        original=local._load_rows
        def small_rows(path,**kwargs):
            self.assertNotEqual(Path(path).name,"samples.csv")
            return original(path,**kwargs)
        with patch(MODULE+".freeze_code"),patch(loader,side_effect=small_rows):
            prepare_recorded_analysis(destination,source)
        receipt=json.loads((destination/"inputs/recorded_source_binding.json").read_text())
        self.assertEqual(receipt["stage_qualification"]["producer_status"],"failed")
        self.assertEqual(receipt["stage_qualification"]["cohort_closure"][0]["terminal_count"],2)
        self.assertEqual(json.loads((source/"run_manifest.json").read_text())["status"],"failed")
        rebound=json.loads((destination/"inputs/resolved_study.json").read_text())
        self.assertEqual(rebound["cases"][0]["directory"],str(source/"simion/case_01"))
        self.assertEqual((destination/"inputs/native_resolved_study.json").read_bytes(),(source/"inputs/resolved_study.json").read_bytes())
        self.assertFalse(any(p.suffix==".pa" for p in destination.rglob("*")))

    def test_failed_native_stage_rejects_incomplete_or_changed_evidence(self):
        for fault in ("stage","usage","marker","terminal","source","tamper","project"):
            with self.subTest(fault=fault):
                source,destination=self._failed_native_source()
                if fault=="stage":
                    (source/"summary.json").write_text(json.dumps(dict(role="ip_prism_distance_study_summary",status="failed",stage="native_fly")))
                elif fault=="usage":
                    (source/"results/simion_batch_resource_usage.json").write_text(json.dumps(dict(status="process_failed",failure_class="native",execution_wave=dict(process_count=1))))
                elif fault=="marker":
                    (source/"logs/fly_batch_0001.log").write_text("IP_PRISM_CASE=PASS missing stage=fly\n")
                elif fault in {"terminal","source"}:
                    path=source/("simion/case_01/events.csv" if fault=="terminal" else "inputs/component_particle_state.csv")
                    lines=path.read_text().splitlines()
                    lines=[line for line in lines if not line.startswith("terminal,1,")] if fault=="terminal" else lines[:-1]
                    path.write_text("\n".join(lines)+"\n")
                elif fault=="project":
                    config=json.loads((source/"run_config.json").read_text());config["project"]="wrong"
                    (source/"run_config.json").write_text(json.dumps(config))
                if fault!="tamper":self._seal_failed_fixture(source)
                else:(source/"logs/fly_batch_0001.log").write_text("changed unbound bytes")
                with patch(MODULE+".freeze_code"),self.assertRaises((ValueError,AssertionError)):
                    prepare_recorded_analysis(destination,source)

    def test_recorded_inputs_are_bound_without_pa_or_refly(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/"producer";folder=source/"simion/case_01"
            folder.mkdir(parents=True);(source/"inputs").mkdir()
            paths=[]
            for name in ("events.csv","samples.csv","axis_field.csv","geometry.json","source_occupancy.csv"):
                path=folder/name;path.write_text("unchanged actual evidence\n");paths.append(path)
            for name in ("source.csv","census.csv"):
                path=source/"inputs"/name;path.write_text("original complete cohort\n");paths.append(path)
            cohort=paths[-2]
            projection=source/"inputs/native_sources/source_01/provider_voltage_projection.json"
            projection.parent.mkdir(parents=True);projection.write_text("{}")
            paths.append(projection)
            case=dict(case_id="B",source_run="original-IP-producer",directory=str(folder),source_csv=str(cohort),source_census_csv=str(paths[-2]),
                      field_path=str(folder/"absent-field.pa"))
            study=source/"inputs/resolved_study.json"
            native_contract=dict(ContourPreparationTests().contract(), schema_version=2,
                                 limits={"transient_run_directory_bytes":34359738368,
                                         "transient_run_directory_sample_interval_seconds":30})
            native_contract.pop("field_sources"); native_contract.pop("electrode_collision_model")
            for row in native_contract["cases"]:
                row.pop("lens_elements")
            study.write_text(json.dumps(dict(role="resolved_ip_prism_contour_focus_study",cases=[case],contract=native_contract)))
            paths.append(study)
            config=source/"run_config.json";config.write_text(json.dumps(dict(inputs={})))
            manifest=dict(project="parallel_mirror_dual_stripe_mr_tof",status="success",run_config=file_record(config),
                          inputs={"cohort":file_record(paths[-3])},outputs=[file_record(p) for p in paths])
            (source/"run_manifest.json").write_text(json.dumps(manifest))
            destination=root/"analysis";destination.mkdir();(destination/"inputs").mkdir()
            (destination/"run_config.json").write_text(json.dumps(dict(inputs={},parameters={})))
            with patch(MODULE+".freeze_code"):
                prepare_recorded_analysis(destination,source)
            result=json.loads((destination/"run_config.json").read_text())
            self.assertEqual(result["parameters"]["workflow"],"ip_prism_contour_recorded_analysis")
            self.assertFalse(result["parameters"]["new_solver_execution"])
            self.assertTrue(set(map(str,paths))<=set(result["inputs"].values()))
            self.assertNotIn(case["field_path"],result["inputs"].values())
            self.assertEqual((destination/"inputs/resolved_study.json").read_bytes(),study.read_bytes())
            selection=copy.deepcopy(native_contract)
            selection["aperture_comparison"]["frame"]="global_z"
            selected=root/"selected";selected.mkdir();(selected/"inputs").mkdir()
            (selected/"run_config.json").write_text(json.dumps(dict(inputs={},parameters={})))
            author=root/"selection.json";author.write_text(json.dumps(selection))
            with patch(MODULE+".freeze_code"):
                prepare_recorded_analysis(selected,source,author)
            derived=json.loads((selected/"inputs/resolved_study.json").read_text())
            self.assertEqual(derived["contract"]["aperture_comparison"]["frame"],"global_z")
            self.assertEqual((selected/"inputs/native_resolved_study.json").read_bytes(),study.read_bytes())
            self.assertEqual(derived["cases"],[case])
            selection["numerics"]["maximum_step_us"]*=2
            author.write_text(json.dumps(selection))
            with patch(MODULE+".freeze_code"),self.assertRaisesRegex(ValueError,"physical/numerical inputs"):
                prepare_recorded_analysis(selected,source,author)
            selection=copy.deepcopy(native_contract)
            selection["cases"][0]["source_run"]="different-native-source"
            author.write_text(json.dumps(selection))
            with patch(MODULE+".freeze_code"),self.assertRaisesRegex(ValueError,"physical/numerical inputs"):
                prepare_recorded_analysis(selected,source,author)
            selection=copy.deepcopy(native_contract)
            selection["limits"]["transient_run_directory_bytes"]+=1
            author.write_text(json.dumps(selection))
            with patch(MODULE+".freeze_code"),self.assertRaisesRegex(ValueError,"physical/numerical inputs"):
                prepare_recorded_analysis(selected,source,author)
            cohort.write_text("changed actual cohort\n")
            with patch(MODULE+".freeze_code"),self.assertRaises(AssertionError):
                prepare_recorded_analysis(destination,source)


class CompletedFieldReuseTests(unittest.TestCase):
    def producer(self, root):
        owner=root/"failed_field_producer";folder=owner/"simion/case_01"
        folder.mkdir(parents=True);(owner/"inputs").mkdir()
        geometry=dict(geometry={},geometry_checks=dict(grid_dimensions=[3,2,2],pitch_mm=[.1,.2,.2],
                      convergence_v=1e-5,nominal_y_mm=0,boundary_mode="grounded_five_faces_x_mirror"),
                      delta_z_mm=0,exit_z_mm=0,gap_mm=1)
        (folder/"geometry.json").write_text(json.dumps(geometry))
        (folder/"field.gem").write_text("; small contract fixture field\n",newline="\n")
        path=folder/"field.pa"
        path.write_bytes(struct.pack('<iidiiiiddd',-2,1,100,3,2,2,1,.1,.2,.2)+struct.pack('<12d',*range(12)))
        (folder/"field.pa-surf").write_bytes(b"surface fixture")
        case=dict(case_id="source_case",field_case_id="source_field",directory=str(folder),field_path=str(path))
        identity=dict(gem_sha256=file_record(folder/"field.gem")["sha256"],convergence_v=1e-5,source_native_drive_sha256="schedule")
        (owner/"inputs/resolved_study.json").write_text(json.dumps(dict(role="resolved_ip_prism_contour_focus_study",
             cases=[case],build_cases=[case],field_cases={"source_field":identity})))
        validate_fields(owner)
        (owner/"run_config.json").write_text(json.dumps(dict(inputs={})))
        self.refresh(owner)
        return owner,geometry,identity

    def refresh(self, owner):
        manifest=dict(project="parallel_mirror_dual_stripe_mr_tof",status="failed",run_config=file_record(owner/"run_config.json"),inputs={},
                      outputs=[file_record(p) for p in owner.rglob("*") if p.is_file() and p.name not in {"run_config.json","run_manifest.json"}])
        (owner/"run_manifest.json").write_text(json.dumps(manifest))

    def test_failed_producer_complete_field_is_consumable_without_relabeling(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);owner,_,identity=self.producer(root)
            before={str(p):p.read_bytes() for p in owner.rglob("*") if p.is_file()}
            result=_freeze_completed_field_source(owner,"source_field",root/"frozen")
            self.assertEqual(result["producer_status"],"failed")
            self.assertEqual(result["field_identity"],identity)
            self.assertEqual(len(result["inventory"]),2)
            self.assertEqual(before,{str(p):p.read_bytes() for p in owner.rglob("*") if p.is_file()})

    def test_incomplete_validation_missing_or_changed_payload_rejected(self):
        for mode in ("incomplete","missing","drift","unbound_surface"):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);owner,_,_=self.producer(root)
                path=owner/"simion/case_01/field.pa"
                if mode=="incomplete":
                    report=owner/"results/pa_payload_validation.json";value=json.loads(report.read_text())
                    value["fields"][0]["finite_nodes"]-=1;report.write_text(json.dumps(value));self.refresh(owner)
                elif mode=="missing":path.unlink()
                elif mode=="drift":path.write_bytes(b"X"+path.read_bytes()[1:])
                else:
                    m=json.loads((owner/"run_manifest.json").read_text());m["outputs"]=[r for r in m["outputs"] if not r["path"].endswith("-surf")]
                    (owner/"run_manifest.json").write_text(json.dumps(m))
                if mode=="drift":
                    source=_freeze_completed_field_source(owner,"source_field",root/"frozen")
                    from common.simion.cache_generation import materialize_direct_inventory
                    with self.assertRaisesRegex(RuntimeError,"differs"):
                        materialize_direct_inventory(path.parent,root/"copy",source["inventory"])
                else:
                    with self.assertRaises((ValueError,AssertionError)):
                        _freeze_completed_field_source(owner,"source_field",root/"frozen")

    def test_all_reuse_deduplicates_shared_field_and_still_validates_complete_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);owner,geometry,_=self.producer(root)
            contract=ContourPreparationTests().contract();contract["committed_new_bytes"]=100_000_000
            contract["field_sources"]={"B_field":dict(action="reuse",source_run=str(owner),source_field_case_id="source_field")}
            run=root/"new";(run/"inputs").mkdir(parents=True);(run/"run_config.json").write_text(json.dumps(dict(inputs={})))
            cp=root/"contract.json";cp.write_text(json.dumps(contract))
            case=ContourPreparationTests().source_case(root/"native")
            geometry["gem"]=(owner/"simion/case_01/field.gem").read_text()
            gf=root/"geometry.json";gf.write_text("{}")
            vf=root/"voltage.json";vf.write_text(json.dumps(dict(analyzer_electrode_voltages_v=list(range(20)))))
            projection=dict(values_v15=list(range(15)),source_native_drive=dict(sha256="schedule"))
            with patch(MODULE+".freeze_references",return_value=dict(geometry=gf,voltages=vf)), \
                 patch(MODULE+"._freeze_recorded_contour_source",return_value=case), \
                 patch(MODULE+"._contour_geometry_and_voltage",return_value=({},projection)), \
                 patch(MODULE+".prepare_geometry",side_effect=lambda *a,**k:copy.deepcopy(geometry)), \
                 patch(MODULE+".load_particle_count_policy",return_value=dict(functional_check_count=2)), \
                 patch(MODULE+".freeze_code"):
                result=prepare(run,cp)
            self.assertEqual(result["build_cases"],[])
            self.assertEqual(len(result["field_owners"]),1)
            self.assertEqual(len(result["cases"]),2)
            self.assertEqual(result["cases"][0]["field_path"],result["cases"][1]["field_path"])
            self.assertFalse((run/"inputs/simion_build_dispatch_request.json").exists())
            receipt=json.loads((run/"results/field_reuse_materialization.json").read_text())
            self.assertEqual(len(receipt["fields"]),1)
            validated=validate_fields(run)
            self.assertEqual(len(validated["fields"]),1)
            self.assertEqual(validated["fields"][0]["validated_nodes"],12)
            # Changing a compiled field's voltage/GEM identity is not a legal reuse.
            other=root/"mismatch";(other/"inputs").mkdir(parents=True);(other/"run_config.json").write_text(json.dumps(dict(inputs={})))
            geometry["gem"]+="; changed voltage\n"
            with patch(MODULE+".freeze_references",return_value=dict(geometry=gf,voltages=vf)), \
                 patch(MODULE+"._freeze_recorded_contour_source",return_value=case), \
                 patch(MODULE+"._contour_geometry_and_voltage",return_value=({},projection)), \
                 patch(MODULE+".prepare_geometry",side_effect=lambda *a,**k:copy.deepcopy(geometry)), \
                 patch(MODULE+".load_particle_count_policy",return_value=dict(functional_check_count=2)), \
                 patch(MODULE+".freeze_code"),self.assertRaisesRegex(ValueError,"geometry, voltage, grid or convergence"):
                prepare(other,cp)


class ReplayPackageTests(unittest.TestCase):
    def fixture(self, root):
        source=root/"producer";folder=source/"simion/case_01";folder.mkdir(parents=True)
        inputs=source/"inputs";inputs.mkdir()
        cohort=inputs/"source.csv";census=inputs/"census.csv"
        cohort.write_text("particle_id,instrument_time_us,mass_amu,charge_state,position_x_mm,position_y_mm,position_z_mm,velocity_x_m_s,velocity_y_m_s,velocity_z_m_s\n1,20,524,1,0,0,0,0,0,-40000\n")
        census.write_text("particle_id,transfer_status\n"+"".join(f"{i},{'transferred' if i==1 else 'not_transferred'}\n" for i in range(1,101)))
        state=dict(particle_id=1,mass_amu=524.,charge_state=1,t_us=20.,x_mm=0.,y_mm=0.,z_mm=10.,vx_mm_us=0.,vy_mm_us=0.,vz_mm_us=-40.)
        (folder/"source_states.json").write_text(json.dumps([state]))
        (folder/"geometry.json").write_text(json.dumps(dict(geometry_checks=dict(nominal_y_mm=0,grid_dimensions=[5,5,5]))))
        (folder/"case_config.lua").write_text("return {}\n")
        (folder/"local.fly2").write_text("particles { standard_beam { n=1 } }\n")
        (folder/"field.pa").write_bytes(b"immutable ordinary field")
        (folder/"field.pa-surf").write_bytes(b"immutable surface")
        projection=inputs/"native_sources/source_01/provider_voltage_projection.json"
        projection.parent.mkdir(parents=True);projection.write_text("{}")
        case=dict(case_id="B",source_run="IP-original",directory=str(folder),script=str(folder/"old.lua"),
                  source_csv=str(cohort),source_census_csv=str(census),field_path=str(folder/"field.pa"),
                  source_count=1,mother_count=100,delta_z_mm=10,exit_z_mm=10,distance_mm=15,source_epoch_us=20,
                  pitch_mm=[.1,.1,.1],maximum_step_us=.01,field_case_id="B-field")
        numerics=ContourPreparationTests().contract()["numerics"]
        (inputs/"resolved_study.json").write_text(json.dumps(dict(role="resolved_ip_prism_contour_focus_study",cases=[case],numerics=numerics,
              contract=dict(schema_version=5, observation_planes=[dict(name="p1_exit",z_mm=-60)]))))
        (source/"summary.json").write_text(json.dumps(dict(status="success")))
        config=source/"run_config.json";config.write_text(json.dumps(dict(inputs={})))
        manifest=dict(project="parallel_mirror_dual_stripe_mr_tof",status="success",run_config=file_record(config),inputs={},
                      outputs=[file_record(p) for p in source.rglob("*") if p.is_file() and p!=config])
        (source/"run_manifest.json").write_text(json.dumps(manifest))
        run=root/"delivery";(run/"inputs").mkdir(parents=True)
        (run/"run_config.json").write_text(json.dumps(dict(inputs={},parameters={})))
        author=dict(schema_version=1,role="ip_prism_local_replay_package",cases=[dict(source_run=str(source),case_id="B")],
                    frontend=dict(schema_version=1,role="ip_prism_local_frontend",trajectory_image_control=0),
                    committed_new_bytes=100_000_000,scope="Private local GUI delivery; no Refine/Fly")
        contract=root/"replay.json";contract.write_text(json.dumps(author))
        return source,folder,run,contract,author

    def test_private_manifest_bound_fields_and_companions_preserve_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            source,folder,run,contract,author=self.fixture(Path(temporary))
            before={str(p):p.read_bytes() for p in source.rglob("*") if p.is_file()}
            with patch(MODULE+".freeze_code"):
                result=prepare(run,contract)
            case=result["cases"][0];private=Path(case["field_path"])
            self.assertEqual(result["role"],"resolved_ip_prism_local_replay_package")
            self.assertNotIn("limits",result)
            self.assertEqual(case["field_node_count"],125)
            self.assertEqual(private.read_bytes(),(folder/"field.pa").read_bytes())
            self.assertEqual(Path(str(private)+"-surf").read_bytes(),(folder/"field.pa-surf").read_bytes())
            self.assertNotEqual(private.stat().st_ino,(folder/"field.pa").stat().st_ino)
            self.assertEqual((private.parent.parent/"local.fly2").read_bytes(),(folder/"local.fly2").read_bytes())
            self.assertIn('trajectory_image_control', (private.parent.parent/"case_config.lua").read_text())
            self.assertEqual(before,{str(p):p.read_bytes() for p in source.rglob("*") if p.is_file()})
            self.assertFalse(result["fly_executed"]);self.assertFalse(result["refine_executed"])
            request=json.loads((run/"inputs/simion_dispatch_request.json").read_text())
            self.assertEqual(request["workload_topology_id"],"private_local_workbench_assembly_only")
            private.write_bytes(b"private mutable change")
            self.assertEqual((folder/"field.pa").read_bytes(),b"immutable ordinary field")

    def test_payload_tamper_and_unbound_surface_fail_closed(self):
        for mode in ("tamper","unbound"):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as temporary:
                source,folder,run,contract,_=self.fixture(Path(temporary))
                if mode=="tamper":
                    original=(folder/"field.pa").read_bytes()
                    (folder/"field.pa").write_bytes(b"X"+original[1:])
                else:
                    manifest=json.loads((source/"run_manifest.json").read_text())
                    manifest["outputs"]=[r for r in manifest["outputs"] if not r["path"].endswith("-surf")]
                    (source/"run_manifest.json").write_text(json.dumps(manifest))
                with patch(MODULE+".freeze_code"),self.assertRaises((ValueError,RuntimeError)):
                    prepare_replay_package(run,contract)

    def test_schema_and_measured_capacity_fail_before_payload_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            _,_,run,contract,author=self.fixture(Path(temporary))
            with self.assertRaises(ValueError):
                validate_replay_contract(dict(author,limits={}))
            for key,value in (("frontend",{}),("cases",author["cases"]*2),("committed_new_bytes",True)):
                invalid=dict(author,**{key:value})
                with self.subTest(key=key),self.assertRaises(ValueError):validate_replay_contract(invalid)
            author["committed_new_bytes"]=1;contract.write_text(json.dumps(author))
            with patch(MODULE+".freeze_code"),patch("common.simion.cache_generation.materialize_direct_inventory") as copy_payload:
                with self.assertRaisesRegex(ValueError,"capacity commitment"):
                    prepare_replay_package(run,contract)
                copy_payload.assert_not_called()

    def test_multiple_successful_producers_are_selected_explicitly(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            _,_,run,contract,author=self.fixture(root/"one")
            second,_,_,_,_=self.fixture(root/"two")
            study=second/"inputs/resolved_study.json"
            value=json.loads(study.read_text());value["cases"][0]["case_id"]="C";study.write_text(json.dumps(value))
            manifest=json.loads((second/"run_manifest.json").read_text())
            manifest["outputs"]=[file_record(Path(r["path"])) for r in manifest["outputs"]]
            (second/"run_manifest.json").write_text(json.dumps(manifest))
            author["cases"].append(dict(source_run=str(second),case_id="C"));contract.write_text(json.dumps(author))
            with patch(MODULE+".freeze_code"):
                result=prepare_replay_package(run,contract)
            self.assertEqual([c["case_id"] for c in result["cases"]],["B","C"])
            self.assertEqual(len({c["field_path"] for c in result["cases"]}),2)
            binding=json.loads((run/"inputs/replay_source_binding.json").read_text())
            self.assertEqual(len({c["source_run"] for c in binding["sources"]}),2)

    def _qualified_failed_fixture(self, root):
        source,folder,run,contract,author=self.fixture(root)
        study=source/"inputs/resolved_study.json";resolved=json.loads(study.read_text())
        resolved["cases"][0]["mass_u"]=524.
        study.write_text(json.dumps(resolved))
        fields=["event","particle_id","reason","t_us","x_mm","y_mm","z_mm","vx_mm_us","vy_mm_us","vz_mm_us","potential_v"]
        with (folder/"events.csv").open("w",newline="") as stream:
            writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
            for event,reason,t,z in (("birth","release",20.,10.),("plane","p1_exit",21.75,-60.),("terminal","reached_exit",21.75,-60.)):
                writer.writerow(dict(event=event,particle_id=1,reason=reason,t_us=t,x_mm=0.,y_mm=0.,z_mm=z,
                                     vx_mm_us=0.,vy_mm_us=0.,vz_mm_us=-40.,potential_v=0.))
        (source/"results").mkdir();(source/"logs").mkdir()
        (source/"summary.json").write_text(json.dumps(dict(role="ip_prism_distance_study_summary",status="failed",stage="automatic_local_diagnostics")))
        (source/"results/simion_batch_resource_usage.json").write_text(json.dumps(dict(role="multipole_resource_usage",status="completed",failure_class=None,execution_wave=dict(process_count=1))))
        (source/"logs/fly_batch_0001.log").write_text("IP_PRISM_CASE=PASS B stage=fly\n")
        (source/"run_config.json").write_text(json.dumps(dict(project="parallel_mirror_dual_stripe_mr_tof",run_id=source.name,inputs={})))
        self._reseal_failed_replay(source)
        return source,folder,run,contract,author

    def _reseal_failed_replay(self, source):
        config=source/"run_config.json"
        paths=[p for p in source.rglob("*") if p.is_file() and p.name not in {"run_manifest.json","run_config.json"}]
        manifest=dict(project="parallel_mirror_dual_stripe_mr_tof",run_id=source.name,status="failed",run_config=file_record(config),
                      inputs={},outputs=[file_record(p) for p in paths])
        (source/"run_manifest.json").write_text(json.dumps(manifest))

    def test_completed_failed_native_replay_keeps_asset_owner_and_stage_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            source,folder,run,contract,_=self._qualified_failed_fixture(Path(temporary))
            before={str(p):p.read_bytes() for p in source.rglob("*") if p.is_file()}
            with patch(MODULE+".freeze_code"):
                result=prepare_replay_package(run,contract)
            binding=json.loads((run/"inputs/replay_source_binding.json").read_text())["sources"][0]
            self.assertEqual(binding["source_run"],str(source))
            self.assertEqual(binding["producer_status"],"failed")
            self.assertEqual(binding["stage_qualification"]["failed_stage"],"automatic_local_diagnostics")
            self.assertEqual(binding["stage_qualification"]["cohort_closure"][0]["mother_count"],100)
            self.assertEqual(Path(result["cases"][0]["field_path"]).read_bytes(),(folder/"field.pa").read_bytes())
            self.assertFalse(result["refine_executed"]);self.assertFalse(result["fly_executed"])
            self.assertEqual(before,{str(p):p.read_bytes() for p in source.rglob("*") if p.is_file()})

    def test_replay_reuses_native_qualification_and_rejects_incomplete_failed_stage(self):
        for fault in ("stage","marker","resource","closure","unbound"):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as temporary:
                source,folder,run,contract,_=self._qualified_failed_fixture(Path(temporary))
                if fault=="stage":
                    path=source/"summary.json";value=json.loads(path.read_text());value["stage"]="local_fixed_cohort_flight";path.write_text(json.dumps(value))
                elif fault=="marker":(source/"logs/fly_batch_0001.log").write_text("IP_PRISM_CASE=PASS missing stage=fly\n")
                elif fault=="resource":
                    path=source/"results/simion_batch_resource_usage.json";value=json.loads(path.read_text());value["failure_class"]="failed";path.write_text(json.dumps(value))
                elif fault=="closure":
                    path=folder/"events.csv";path.write_text("\n".join(path.read_text().splitlines()[:-1])+"\n")
                self._reseal_failed_replay(source)
                if fault=="unbound":
                    path=source/"run_manifest.json";value=json.loads(path.read_text());value["outputs"]=[r for r in value["outputs"] if r["path"]!=str(folder/"events.csv")];path.write_text(json.dumps(value))
                with patch(MODULE+".freeze_code"),patch("common.simion.cache_generation.materialize_direct_inventory") as copy_payload:
                    with self.assertRaises((ValueError,AssertionError)):prepare_replay_package(run,contract)
                    copy_payload.assert_not_called()

    def test_failed_producer_is_not_a_gui_delivery_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            source,_,run,contract,_=self.fixture(Path(temporary))
            path=source/"run_manifest.json";manifest=json.loads(path.read_text());manifest["status"]="failed";path.write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                prepare_replay_package(run,contract)

    def test_assembly_receipt_requires_preserved_companions_and_vacuum_census(self):
        with tempfile.TemporaryDirectory() as temporary:
            _,_,run,contract,_=self.fixture(Path(temporary))
            with patch(MODULE+".freeze_code"):
                resolved=prepare_replay_package(run,contract)
            folder=Path(resolved["cases"][0]["directory"])
            (folder/"local.iob").write_bytes(b"vendor assembly test placeholder")
            (folder/"source_occupancy.csv").write_text("particle_id,electrode\n1,0\n")
            (folder/"axis_field.csv").write_text("z_mm,potential_v\n0,0\n")
            result=analyze_replay_package(run)
            self.assertEqual(result["default_replay_verification"],"pending")
            (folder/"source_occupancy.csv").write_text("particle_id,electrode\n1,1\n")
            with self.assertRaisesRegex(ValueError,"occupancy"):
                analyze_replay_package(run)
            (folder/"local.fly2").write_text("overwritten vendor stub")
            with self.assertRaises(AssertionError):
                analyze_replay_package(run)


if __name__=="__main__":
    unittest.main()
