"""Contour-only identity, complete losses and headless comparison regressions."""
from __future__ import annotations

import copy
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from matplotlib import pyplot as plt
import numpy as np

from common.contracts.write_run_manifest import file_record
from projects.dual_pressure_rectilinear_ion_processor.analysis import geometry_comparison as geometry
from projects.dual_pressure_rectilinear_ion_processor.analysis import extraction_phase_space_comparison as recorded


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def projection_fixture() -> dict:
    """Small complete LP CSG fixture, independent of artifacts and solver output."""
    def box(x0,x1,y0,y1,z0,z1):
        return dict(shape="box",min_mm=[x0,y0,z0],max_mm=[x1,y1,z1])
    electrodes=[]
    for eid,y0,y1 in ((5,2,2.5),(6,-2.5,-2),(7,.4,1),(8,-1,-.4)):
        electrodes.append(dict(electrode_id=eid,name=f"fixture E{eid}",solids=[box(130.5,191,y0,y1,-2.5,2.5)],cutouts=[]))
    for eid,start,stop,inner,outer in ((10,132,189.5,2,2.2),(11,168.75,171.25,1.4,1.6)):
        electrodes.append(dict(electrode_id=eid,name=f"fixture E{eid}",
            solids=[box(start,stop,-.15,.15,inner,outer),box(start,stop,-.15,.15,-outer,-inner)],cutouts=[]))
    electrodes.append(dict(electrode_id=14,name="fixture shield",solids=[box(130.5,191,-3.5,3.5,-3.5,3.5)],
        cutouts=[box(130.5,191,-3,3,-3,3)]))
    return dict(grid_mm=.1,electrodes=electrodes)


def source_fixture(run: Path, mode: str, *, status: str = "success", exits: tuple[int, ...] = (1, 2)) -> None:
    config = dict(source=dict(particle_count=3, species=dict(mass_amu=524)),
                  baseline=dict(geometry=dict(lp_length_mm=61.5,lp_center_mm=170), electric=dict(lift_v=4480.)),
                  numerics=dict(native_grid_mm=.1), coordinate_transform=dict(to_frame_id="fixture_world",translation_mm=[0,0,9.8]),
                  native_operating_point=dict(lift_v=4480.), native_timing=dict(pulse_start_us=1.),
                  diagnostics=dict(snapshots=[dict(label="source"), dict(label="pre")], max_extraction_bracket_us=.02),
                  field_diagnostics={}, acceptance={}, native_projection=projection_fixture(), numerical_boundaries={})
    if mode != "flat":
        config["baseline"]["electrode_contours"] = dict(schema_version=1, mode=mode)
    write_json(run/"inputs/resolved_model.json", config)
    write_json(run/"inputs/diagnostics.json", config["diagnostics"])
    write_json(run/"summary.json", dict(role="ion_processor_functional_summary", status=status))
    write_json(run/"run_config.json", dict(project=recorded.PROJECT))
    events, snapshots, samples = [], [], []
    for pid in (1, 2, 3):
        state = dict(particle_id=pid, t_us=0., x_mm=pid/10, y_mm=pid/5, z_mm=10., vx_mm_us=pid/100,
                     vy_mm_us=pid/200, vz_mm_us=-1.)
        events.append(dict(event="source", reason="source", **state))
        snapshots.append(dict(snapshot="pre", status="alive", reason="none", **{**state, "t_us": 1.}))
        if pid in exits:
            events.append(dict(event="extraction_exit", reason="acceptance_surface", **{**state, "t_us": 2.+pid*.001, "z_mm": 0.}))
        events.append(dict(event="terminal", reason="acceptance_surface" if pid in exits else "solver_stop",
                           **{**state, "t_us": 2.+pid*.001, "z_mm": 0. if pid in exits else 6.}))
        for time, z in ((1.1, 10.), (1.11, 5.), (1.12, 0.)):
            samples.append({**state, "t_us": time, "z_mm": z})
    write_csv(run/"simion/events.csv", events)
    write_csv(run/"simion/samples.csv", samples)
    write_csv(run/"results/diagnostic_snapshots.csv", snapshots)
    write_csv(run/"results/diagnostic_losses.csv", [dict(particle_id=3, reason="solver_stop")])
    (run/"simion/runtime.lua").write_text("-- fixture runtime\n", encoding="utf-8")
    files = [p for p in run.rglob("*") if p.is_file() and p.name != "run_manifest.json"]
    write_json(run/"run_manifest.json", dict(project=recorded.PROJECT, run_id=run.name, status=status,
               run_config=file_record(run/"run_config.json"), inputs={}, outputs=[file_record(p) for p in files if p.name != "run_config.json"]))


class GeometryComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="ip_geometry_test_")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.completed = patch.object(recorded, "require_completed_terminal_publication")
        self.completed.start()
        self.addCleanup(self.completed.stop)

    def cases(self, *, include_parabolic: bool = False) -> tuple[list[dict], dict]:
        cases, cells = [], []
        modes = ["flat", "formed_extraction", "formed_extraction_continuous_aux"]
        if include_parabolic:
            modes.append(geometry.PARABOLIC_MODE)
        for index, mode in enumerate(modes):
            run = self.root/f"case_{index}"
            source_fixture(run, mode)
            label = f"Case {index}"
            cases.append(recorded.load_recorded_case(run, label, include_samples=True))
            cells.append(dict(label=label, run=str(run), run_id=run.name, contour_mode=mode))
        study = dict(schema_version=1, role="ion_processor_geometry_control_study", particle_count=3,
                     cells=cells, extraction_planes_z_mm=[9.5, 7.3, 6.3, 5., 0.])
        return cases, study

    def current_study(self, cases, old):
        study = copy.deepcopy(old)
        study.update(schema_version=2, reference_case_id="reference")
        reference = cases[0]["config"]["baseline"]
        for index, (case, cell) in enumerate(zip(cases, study["cells"], strict=True)):
            cell.update(case_id="reference" if index == 0 else f"design_{index}", configuration_changes=[])
            contour = case["config"]["baseline"].get("electrode_contours")
            before = dict(exists=True, value=reference["electrode_contours"]) if "electrode_contours" in reference else dict(exists=False)
            after = dict(exists=True, value=contour) if contour is not None else dict(exists=False)
            if before != after:
                cell["configuration_changes"].append(dict(path="/baseline/electrode_contours", before=before, after=after))
        return study

    def design_cases(self):
        cases, old = self.cases()
        for case in cases:
            case["config"]["baseline"]["electrode_contours"] = dict(mode=geometry.PARABOLIC_MODE)
            case["config"]["native_operating_point"].update(lp_outer_relative_v=5, lp_inner_relative_v=-1)
        for cell in old["cells"]:
            cell["contour_mode"] = geometry.PARABOLIC_MODE
        study = self.current_study(cases, old)
        changes = study["cells"][1]["configuration_changes"]
        for key, before, after in (("lp_outer_relative_v",5,4),("lp_inner_relative_v",-1,-1.1)):
            cases[1]["config"]["native_operating_point"][key] = after
            changes.append(dict(path=f"/native_operating_point/{key}", before=dict(exists=True,value=before), after=dict(exists=True,value=after)))
        bounds = [132,208]
        cases[2]["config"]["baseline"]["electrode_contours"]["outer_axial_bounds_mm"] = bounds
        study["cells"][2]["configuration_changes"] = [dict(path="/baseline/electrode_contours/outer_axial_bounds_mm",before=dict(exists=False),after=dict(exists=True,value=bounds))]
        return cases, study

    def test_active_same_mode_voltage_and_absent_contour_field_are_exactly_declared(self):
        cases, study = self.design_cases()
        with patch.object(geometry,"native_projection",return_value=projection_fixture()), patch.object(geometry,"validate_numerical_boundaries"):
            geometry.validate_geometry_cases(cases,study)
            for mutation in ("undeclared","wrong_before","duplicate","ancestor","source","numerics"):
                bad, contract = copy.deepcopy(cases), copy.deepcopy(study)
                if mutation == "undeclared": contract["cells"][1]["configuration_changes"].pop()
                elif mutation == "wrong_before": contract["cells"][1]["configuration_changes"][0]["before"]["value"] = 6
                elif mutation == "duplicate": contract["cells"][1]["configuration_changes"] *= 2
                elif mutation == "ancestor":
                    contract["cells"][2]["configuration_changes"].insert(0,dict(path="/baseline/electrode_contours",before=dict(exists=True,value=cases[0]["config"]["baseline"]["electrode_contours"]),after=dict(exists=True,value=cases[2]["config"]["baseline"]["electrode_contours"])))
                elif mutation == "source": bad[1]["states"][0]["vx_mm_us"] += 1
                elif mutation == "numerics": bad[1]["config"]["numerics"]["native_grid_mm"] *= 2
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    geometry.validate_geometry_cases(bad,contract)

    def test_historical_author_is_explicitly_readonly(self):
        cases, study = self.cases()
        with self.assertRaisesRegex(ValueError,"unsupported"):
            geometry.validate_geometry_cases(cases,study)
        parent=self.root/"old_active"
        write_json(parent/"inputs/study.json",study)
        write_json(parent/"run_config.json",dict(project=recorded.PROJECT,inputs=dict(study_contract="inputs/study.json")))
        with self.assertRaisesRegex(ValueError,"unsupported"):
            geometry.analyze_geometry_study(parent)

    def test_full_mother_and_common_exits_are_independent_of_own_exit_counts(self):
        cases, study = self.design_cases()
        study["particle_count"] = 100
        for case, count in zip(cases, (96,97,34), strict=True):
            original = {stage: next(r for r in case["states"] if r["stage"] == stage) for stage in case["stages"]}
            case["sources"] = {pid:dict(particle_id=pid) for pid in range(1,101)}
            case["terminals"] = copy.deepcopy(case["sources"])
            case["exits"] = {pid:dict(particle_id=pid) for pid in range(1,count+1)}
            case["states"] = [dict(original[stage],particle_id=pid,
                status=("extracted" if pid <= count else "lost") if stage == "exit_z0" else "alive")
                for stage in case["stages"] for pid in range(1,101)]
        with patch.object(geometry,"native_projection",return_value=projection_fixture()), patch.object(geometry,"validate_numerical_boundaries"):
            geometry.validate_geometry_cases(cases,study)
            statistics, _, common = recorded.prepare_statistics(cases)
            geometry.extend_statistics(cases,statistics,common)
            self.assertEqual(common,list(range(1,35)))
            self.assertEqual([r["observed_count"] for r in statistics if r["cohort"] == "own_extracted_ids" and r["stage"] == "exit_z0"],[96,97,34])
            self.assertTrue(all(r["source_count"] == 100 for r in statistics))
            cases[2]["terminals"].pop(100)
            with self.assertRaisesRegex(ValueError,"complete mother"):
                geometry.validate_geometry_cases(cases,study)

    def test_execution_difference_evidence_binds_runtime_and_preserves_failed_status(self):
        cases, _ = self.cases()
        old = dict(downstream_exit_x_mm=192.75,classification="numerical_observation_not_metal")
        cases[0]["config"]["numerical_boundaries"] = old
        cases[1]["config"]["numerical_boundaries"] = dict(old,schema_version=2,role="native_numerical_observation_boundaries",upstream_exit_x_mm=-1.9)
        source=Path(cases[1]["run"])
        manifest=json.loads((source/"run_manifest.json").read_text())
        manifest["status"]="failed"
        write_json(source/"run_manifest.json",manifest)
        rows=geometry.comparison_execution_evidence(cases)
        self.assertEqual(rows[1]["source_run_status"],"failed")
        self.assertNotEqual(rows[0]["numerical_boundaries"],rows[1]["numerical_boundaries"])
        self.assertEqual(rows[0]["runtime"]["sha256"],file_record(Path(cases[0]["run"])/"simion/runtime.lua")["sha256"])
        (source/"simion/runtime.lua").write_text("-- changed\n",encoding="utf-8")
        with self.assertRaises(AssertionError):
            geometry.comparison_execution_evidence(cases)

    def test_declared_changes_reject_ambiguous_absence_and_protected_invariants(self):
        reference = dict(native_operating_point=dict(v=5), baseline=dict(electrode_contours=dict(mode="D")))
        valid = dict(path="/native_operating_point/v",before=dict(exists=True,value=5),after=dict(exists=True,value=4))
        for change in (
            dict(valid, before=dict(exists=False,value=5)),
            dict(valid, after=dict(exists=True)),
            dict(valid, before=dict(exists=1,value=5)),
            dict(valid, path="/source/particle_count"),
            dict(valid, path="/native_operating_point/missing/child"),
            dict(valid, path="/native_operating_point/bad~escape"),
            dict(valid, after=dict(exists=True,value=float("nan"))),
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                geometry._declared_configuration(reference,[change])
        removed = geometry._declared_configuration(reference,[dict(valid,after=dict(exists=False))])
        self.assertNotIn("v",removed["native_operating_point"])
        self.assertEqual(reference["native_operating_point"]["v"],5)

    def test_reference_case_can_be_last_without_changing_comparison_semantics(self):
        cases, study = self.design_cases()
        cases.reverse();study["cells"].reverse()
        with patch.object(geometry,"native_projection",return_value=projection_fixture()), patch.object(geometry,"validate_numerical_boundaries"):
            geometry.validate_geometry_cases(cases,study)

    def test_fourth_parabolic_geometry_is_optional_unique_and_renders(self) -> None:
        cases, study = self.cases(include_parabolic=True)
        with patch.object(geometry, "native_projection", return_value=projection_fixture()), patch.object(geometry, "validate_numerical_boundaries", return_value=None):
            geometry.validate_geometry_cases(cases, study, recorded_author=True)
            duplicate = copy.deepcopy(study)
            duplicate["cells"][3]["contour_mode"] = "formed_extraction_continuous_aux"
            with self.assertRaisesRegex(ValueError, "unique parabolic"):
                geometry.validate_geometry_cases(cases, duplicate, recorded_author=True)
        spatial = [{**c, "states": recorded.prepare_spatial_crossings(c, study["extraction_planes_z_mm"]),
                    "stages": [f"z_{z:g}_mm" for z in study["extraction_planes_z_mm"]]} for c in cases]
        statistics, _, common = recorded.prepare_statistics(spatial)
        geometry.extend_statistics(spatial, statistics, common)
        figures, metadata = geometry.build_geometry_figures(cases, statistics, study["extraction_planes_z_mm"], common)
        self.assertEqual(len(figures["geometry_exit_phase_space"].axes), 12)
        self.assertEqual(figures["geometry_plane_evolution"].axes[0].lines[3].get_linestyle(), "-.")
        self.assertIsNone(figures["geometry_plane_evolution"].axes[0].get_legend())

        self.assertEqual(len(figures["geometry_plane_evolution"].legends),1)
        self.assertIsNone(figures["geometry_plane_evolution"]._suptitle)
        legend_title=figures["geometry_plane_evolution"].legends[0].get_title().get_text()
        self.assertEqual(legend_title.count("Extraction plane evolution"),1)
        self.assertEqual(legend_title.splitlines()[0],"Extraction plane evolution")
        self.assertIn("common_extracted_ids",legend_title.splitlines()[1])
        self.assertEqual(len(metadata["histogram_bins"]), 4)
        for figure in figures.values():
            plt.close(figure)

    def test_recorded_boundary_validation_is_explicit_and_errors_propagate(self) -> None:
        cases, study = self.cases()
        with patch.object(geometry, "native_projection", return_value=projection_fixture()), \
             patch.object(geometry, "validate_numerical_boundaries") as validator:
            geometry.validate_geometry_cases(cases, study, recorded_author=True)
            self.assertEqual(validator.call_count, len(cases))
            for call, case in zip(validator.call_args_list, cases, strict=True):
                self.assertEqual(call.args, (case["config"]["numerical_boundaries"], case["config"]["native_projection"]))
                self.assertEqual(call.kwargs, dict(recorded=True))
            validator.side_effect = ValueError("numerical boundaries differ from authority")
            with self.assertRaisesRegex(ValueError, "numerical boundaries"):
                geometry.validate_geometry_cases(cases, study, recorded_author=True)

    def test_failed_run_opt_in_requires_physical_summary_and_full_terminal_census(self) -> None:
        run = self.root/"failed"
        source_fixture(run, "flat", status="failed")
        with self.assertRaisesRegex(ValueError, "identity or status"):
            recorded.load_recorded_case(run, "failed")
        case = recorded.load_recorded_case(run, "failed", allow_failed=True)
        self.assertEqual(len(case["terminals"]), 3)
        self.assertTrue(any(Path(r["path"]).name == "summary.json" for r in case["source_records"]))
        write_json(run/"summary.json", dict(role="ion_processor_failed_run"))
        manifest = json.loads((run/"run_manifest.json").read_text())
        manifest["outputs"] = [file_record(Path(r["path"])) if Path(r["path"]).name == "summary.json" else r for r in manifest["outputs"]]
        write_json(run/"run_manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "measured physical summary"):
            recorded.load_recorded_case(run, "failed", allow_failed=True)

    def test_failed_run_missing_terminal_cannot_be_accepted(self) -> None:
        run = self.root/"incomplete"
        source_fixture(run, "flat", status="failed")
        with (run/"simion/events.csv").open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        write_csv(run/"simion/events.csv", [r for r in rows if not (r["event"] == "terminal" and r["particle_id"] == "3")])
        manifest = json.loads((run/"run_manifest.json").read_text())
        manifest["outputs"] = [file_record(Path(r["path"])) if Path(r["path"]).name == "events.csv" else r for r in manifest["outputs"]]
        write_json(run/"run_manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "census differs"):
            recorded.load_recorded_case(run, "failed", allow_failed=True)

    def test_contour_only_contract_rejects_voltage_or_birth_change(self) -> None:
        cases, study = self.cases()
        with patch.object(geometry, "native_projection", return_value=projection_fixture()), patch.object(geometry, "validate_numerical_boundaries", return_value=None):
            geometry.validate_geometry_cases(cases, study, recorded_author=True)
            changed = copy.deepcopy(cases)
            changed[1]["config"]["baseline"]["electric"]["lift_v"] += 1
            with self.assertRaisesRegex(ValueError, "undeclared"):
                geometry.validate_geometry_cases(changed, study, recorded_author=True)
            changed = copy.deepcopy(cases)
            changed[1]["states"][0]["vx_mm_us"] += .001
            with self.assertRaisesRegex(ValueError, "birth states differ"):
                geometry.validate_geometry_cases(changed, study, recorded_author=True)

    def test_empty_common_is_explicit_and_retains_empty_cohort_metrics(self) -> None:
        cases, _ = self.cases()
        cases[1]["exits"] = {}
        with self.assertRaisesRegex(ValueError, "no common"):
            recorded.prepare_statistics(cases)
        stats, _, common = recorded.prepare_statistics(cases, allow_empty_common=True)
        geometry.extend_statistics(cases, stats, common)
        self.assertEqual(common, [])
        self.assertTrue(all(r["sigma_t_ns"] is None and r["cohort_count"] == 0 for r in stats if r["cohort"] == "common_extracted_ids"))
        self.assertTrue(any(r["source_count"] == 3 for r in stats))

    def test_population_time_width_and_y_emittance_use_all_tails(self) -> None:
        cases, _ = self.cases()
        stats, _, common = recorded.prepare_statistics(cases)
        geometry.extend_statistics(cases, stats, common)
        exit_stat = next(r for r in stats if r["stage"] == "exit_z0" and r["cohort"] == "own_extracted_ids")
        self.assertAlmostEqual(exit_stat["sigma_t_ns"], .5)
        self.assertAlmostEqual(exit_stat["sigma_y_mm"], .1)
        self.assertGreaterEqual(exit_stat["rms_emittance_y_theta_mm_mrad"], 0)

    def test_raw_loss_line_is_exact_and_every_mother_is_indexed(self) -> None:
        cases, _ = self.cases()
        census, losses = geometry.loss_evidence(cases)
        self.assertEqual(len(census), 9)
        self.assertEqual(len(losses), 3)
        loss = losses[0]
        raw = Path(loss["source_events"]).read_bytes().splitlines(keepends=True)[loss["raw_line_number"]-1]
        self.assertEqual(loss["raw_line_sha256"], hashlib.sha256(raw).hexdigest().upper())
        self.assertEqual(loss["raw_terminal_line"], raw.decode().rstrip("\r\n"))

    def test_force_reanalysis_is_bound_and_writes_only_into_new_owner(self) -> None:
        cases,_=self.cases()
        case=cases[0];case["config"]["extraction_force_audit"]={"schema_version":1}
        source=Path(case["run"])
        manifest=json.loads((source/"run_manifest.json").read_text())
        output=self.root/"new_analysis"
        with self.assertRaisesRegex(ValueError,"manifest bound"):
            geometry.export_recorded_force_budgets([case],output)
        for name in ("extraction_steps.csv","extraction_impulses.csv"):
            path=source/"simion"/name
            path.write_text("fixture raw input\n",encoding="utf-8")
            manifest["outputs"].append(file_record(path))
        write_json(source/"run_manifest.json",manifest)
        before={p.relative_to(source):p.read_bytes() for p in source.rglob('*') if p.is_file()}
        target="projects.dual_pressure_rectilinear_ion_processor.analysis.extraction_force_budget.export_force_budget"
        with patch(target,return_value={"available_particle_count":2}) as export:
            result=geometry.export_recorded_force_budgets([case],output)
            export.assert_called_once_with(source,output_directory=output/"recovered_force_budget_00")
        self.assertEqual(result[0]["status"],"recovered_in_new_analysis_run")
        after={p.relative_to(source):p.read_bytes() for p in source.rglob('*') if p.is_file()}
        self.assertEqual(before,after)

    def test_full_export_uses_shared_axes_bins_and_preserves_losses(self) -> None:
        cases, study = self.cases()
        study["time_focus_diagnostics"] = dict(drift_lengths_mm=[0.,1.])
        study["aperture_acceptance"] = dict(drift_lengths_mm=[0.,1.], aperture_radii_mm=[.1,1.],center_x_mm=0.,center_y_mm=0.)
        study = self.current_study(cases, study)
        parent = self.root/"comparison"
        write_json(parent/"inputs/study_contract.json", study)
        write_json(parent/"run_config.json", dict(project=recorded.PROJECT, inputs=dict(study_contract="inputs/study_contract.json")))
        with patch.object(geometry, "native_projection", return_value=projection_fixture()), patch.object(geometry, "validate_numerical_boundaries", return_value=None):
            result = geometry.analyze_geometry_study(parent)
        self.assertEqual(result["loss_records"], 3)
        output = parent/"results/geometry_comparison"
        self.assertEqual(len(list(output.glob("*.png"))), 8)
        self.assertEqual(len(list(output.glob("*.svg"))), 8)
        self.assertTrue((output/"time_focus_reference_plane_predictions.csv").is_file())
        self.assertTrue((output/"aperture_acceptance_particle_rows.csv").is_file())
        focus = json.loads((output/"beam_focus_diagnostics.json").read_text())
        self.assertEqual(focus["common_ids"], [1, 2])
        self.assertTrue(all(row["cohort_membership_constant"] for row in focus["sampled_minima"]
                            if row["cohort"] == "common_extracted_ids"))
        self.assertEqual(len(result["sampled_envelope_minima"]), 27)
        metadata = json.loads((output/"figure_manifest.json").read_text())
        for edges in metadata["histogram_bins"].values():
            self.assertEqual(len(edges), 21)
            self.assertTrue(np.all(np.diff(edges) > 0))
        spatial = [{**c, "states": recorded.prepare_spatial_crossings(c, study["extraction_planes_z_mm"]),
                    "stages": [f"z_{z:g}_mm" for z in study["extraction_planes_z_mm"]]} for c in cases]
        stats, _, common = recorded.prepare_statistics(spatial)
        geometry.extend_statistics(spatial, stats, common)
        figures, _ = geometry.build_geometry_figures(cases, stats, study["extraction_planes_z_mm"], common)
        phase = figures["geometry_exit_phase_space"]
        for column in range(3):
            for row in range(1, 3):
                self.assertEqual(phase.axes[column].get_xlim(), phase.axes[row*3+column].get_xlim())
                self.assertEqual(phase.axes[column].get_ylim(), phase.axes[row*3+column].get_ylim())
        for figure in figures.values():
            plt.close(figure)
        with self.assertRaises(FileExistsError):
            with patch.object(geometry, "native_projection", return_value=projection_fixture()), patch.object(geometry, "validate_numerical_boundaries", return_value=None):
                geometry.analyze_geometry_study(parent)

    def test_actual_polygon_sections_and_auxiliary_crops_render_for_three_and_four_cases(self) -> None:
        from matplotlib.patches import Polygon
        for count in (3,4):
            cases,_=self.cases(include_parabolic=count==4)
            electrode=next(e for e in cases[-1]["config"]["native_projection"]["electrodes"] if e["electrode_id"]==11)
            electrode["solids"][0]=dict(shape="convex_polyhedron",vertices_mm=[
                [x,y,z] for x in (168.75,171.25) for y,z in ((-.15,1.4),(.15,1.4),(0,1.6))])
            figures,metadata=geometry.build_electrode_comparison_figures(cases)
            cross=figures["geometry_main_sections"]
            self.assertEqual(len(cross.axes),count)
            self.assertTrue(any(isinstance(p,Polygon) for p in cross.axes[-1].patches))
            self.assertEqual(metadata["planes"][-1]["equatorial_z_mm"],9.8)
            self.assertLess(metadata["inner_y_limits_mm"][1]-metadata["inner_y_limits_mm"][0],3)
            self.assertGreater(metadata["outer_y_limits_mm"][1]-metadata["outer_y_limits_mm"][0],57)
            for ax in figures["geometry_auxiliary_profiles"].axes[1::2]:
                electrode_labels=[text for text in ax.texts if text.get_text().startswith("E")]
                self.assertTrue(all(text.get_text() in {"E10","E11"} for text in electrode_labels))
                if len(electrode_labels)==2:
                    self.assertNotEqual(electrode_labels[0].get_position()[1],electrode_labels[1].get_position()[1])
            for figure in figures.values():
                figure.canvas.draw();plt.close(figure)


if __name__ == "__main__":
    unittest.main()
