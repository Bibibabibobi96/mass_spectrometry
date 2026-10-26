"""Synthetic census/interpolation and headless rendering, not physical evidence."""
from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from matplotlib import pyplot as plt

from projects.dual_pressure_rectilinear_ion_processor.analysis.diagnostics import (
    build_figures, census, export_diagnostics, prepare_data, state_at,
    pulse_timing_context, validate_diagnostics_config,
    project_geometry, cooling_statistics,
)
from projects.dual_pressure_rectilinear_ion_processor.analysis.coordinates import to_project_position, to_project_vector


class DiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ion_processor_diagnostics_")
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        for sub in ("inputs", "simion", "results"):
            (self.run/sub).mkdir()
        c = {"source_profile": "exploration", "source": {"species": {"mass_amu":524}},
             "baseline": {"electric":{"rf_frequency_hz":3700000,"rf_quench_delay_cycles":.5},"clock":{"epoch_us":0,"frame_id":"test_local"},"schedule":{"capture_end_us":1,"transfer_end_us":2,"extraction_start_us":3,"terminal_us":4}},
             "native_projection":{"electrodes":[{"electrode_id":1,"name":"test_electrode","solids":[{"shape":"box","min_mm":[0,-1,-1],"max_mm":[4,-.8,1]}],"cutouts":[]}]}}
        contract={"schema_version":1,"role":"ion_processor_diagnostics","max_ordinary_bracket_us":1.05,"max_extraction_bracket_us":.025,"evolution_interval_us":.5,"png_dpi":180,
                  "snapshots":[{"label":"capture","anchor":"capture_end_us","offset_us":0},{"label":"transfer","anchor":"transfer_end_us","offset_us":0},{"label":"pre_extraction","anchor":"extraction_start_us","offset_us":0}],"stage_labels":["capture","transfer","pre_extraction"]}
        for name,value in (("resolved_model",c),("diagnostics",contract)):
            (self.run/f"inputs/{name}.json").write_text(json.dumps(value),encoding="utf-8")
        columns=["particle_id","t_us","x_mm","y_mm","z_mm","vx_mm_us","vy_mm_us","vz_mm_us"]
        def state(p,t):
            return dict(zip(columns,[p,t,t,0,0,1,0,0]))
        events=[]
        for p,birth,end,reason in ((1,0,4,"acceptance_surface"),(2,0,1.5,"electrode"),(3,.5,4,"timeout")):
            events.extend([{**state(p,birth),"event":"source","reason":"none"},{**state(p,end),"event":"terminal","reason":reason}])
        samples=[state(1,1),state(1,2),state(2,1),state(3,1)]
        self.write_csv(self.run/"simion/events.csv",events,[*columns,"event","reason"])
        self.write_csv(self.run/"simion/samples.csv",samples,columns)
        canonical=[dict(particle_id=r["particle_id"],event=r["event"],status="alive" if r["event"]=="source" else "lost") for r in events]
        self.write_csv(self.run/"results/particle_state.csv",canonical,["particle_id","event","status"])

    @staticmethod
    def write_csv(path,rows,columns):
        with path.open("w",encoding="utf-8",newline="") as stream:
            writer=csv.DictWriter(stream,fieldnames=columns);writer.writeheader();writer.writerows(rows)

    def test_interpolation_limits_and_loss_not_alive(self) -> None:
        data=prepare_data(self.run)
        middle=state_at(data,1,.5)
        self.assertEqual(middle["status"],"alive")
        self.assertEqual(middle["x_mm"],.5)
        self.assertEqual(middle["bracket_gap_us"],1)
        self.assertEqual(state_at(data,1,3)["status"],"unknown")
        self.assertEqual(state_at(data,2,2)["status"],"lost")
        self.assertEqual(state_at(data,2,2)["x_mm"],1.5)
        self.assertEqual(state_at(data,2,2)["electrode_id"],"unknown")
        self.assertEqual(state_at(data,3,0)["status"],"notborn")
        self.assertEqual(state_at(data,1,4)["status"],"extracted")

    def test_injected_initial_state_means_admission_not_a_new_birth(self) -> None:
        path = self.run/"inputs/resolved_model.json"
        config = json.loads(path.read_text())
        config["injected_source"] = dict(mother_particle_count=4)
        path.write_text(json.dumps(config))
        data = prepare_data(self.run)
        self.assertEqual(state_at(data, 3, 0)["status"], "not_admitted")
        self.assertEqual(state_at(data, 3, 0)["reason"], "not_yet_entered_IP")
        count, _ = census(data, 0)
        self.assertEqual(count["not_admitted"], 1)
        self.assertNotIn("notborn", count)
        snapshots = []
        evolution = []
        for label, time in data["snapshots"]:
            count, states = census(data, time)
            evolution.append(count)
            snapshots.extend(dict(snapshot=label, **state) for state in states)
        cooling = cooling_statistics(data, snapshots)
        self.assertIn("same_ids_at_admission", cooling["stages"]["transfer"])
        figures = build_figures(data, snapshots, evolution)
        try:
            energy = figures["cooling_stage_energy"]
            self.assertIn("IP admission", energy.axes[0].get_title())
            labels = [line.get_label() for axis in energy.axes for line in axis.lines]
            self.assertIn("same IDs at IP admission", labels)
            self.assertNotIn("same IDs at birth", labels)
        finally:
            for figure in figures.values():
                plt.close(figure)

    def test_cooling_distributions_preserve_loss_and_unknown_cohorts(self) -> None:
        data=prepare_data(self.run)
        snapshots=[]
        for label,time in data["snapshots"]:
            _,states=census(data,time)
            snapshots.extend(dict(snapshot=label,**state) for state in states)
        result=cooling_statistics(data,snapshots)
        self.assertEqual(result["source_count"],3)
        self.assertEqual(result["source"]["total"]["count"],3)
        transfer=result["stages"]["transfer"]
        self.assertEqual(transfer["census"]["lost"],1)
        self.assertEqual(transfer["census"]["unknown"],1)
        self.assertEqual(transfer["alive_particle_ids"],[1])
        self.assertEqual(transfer["same_ids_at_birth"]["total"]["count"],1)
        self.assertEqual(transfer["alive"]["x"]["mean_ev"],transfer["alive"]["total"]["mean_ev"])
        self.assertEqual(transfer["alive"]["y"]["mean_ev"],0)
        self.assertIsNone(result["stages"]["pre_extraction"]["alive"]["total"]["mean_ev"])

    def test_world_axes_and_geometry_are_rotated_together(self) -> None:
        """A rotated source changes positions/vectors, not membership or energy."""
        path=self.run/"inputs/resolved_model.json"
        config=json.loads(path.read_text())
        config["coordinate_transform"]=dict(schema_version=1,role="rigid_transform",from_frame_id="test_local",to_frame_id="test_world",rotation=[[0,0,-1],[1,0,0],[0,-1,0]],translation_mm=[0,0,9.8])
        path.write_text(json.dumps(config),encoding="utf-8")
        for name in ("events.csv","samples.csv"):
            file=self.run/"simion"/name
            with file.open(newline="") as stream:
                reader=csv.DictReader(stream);fields=reader.fieldnames;rows=list(reader)
            for row in rows:
                position=to_project_position(config,[float(row[k]) for k in ("x_mm","y_mm","z_mm")])
                velocity=to_project_vector(config,[float(row[k]) for k in ("vx_mm_us","vy_mm_us","vz_mm_us")])
                row.update(zip(("x_mm","y_mm","z_mm"),position))
                row.update(zip(("vx_mm_us","vy_mm_us","vz_mm_us"),velocity))
            self.write_csv(file,rows,fields)
        data=prepare_data(self.run)
        point=state_at(data,1,.5)
        self.assertEqual((point["x_mm"],point["y_mm"],point["z_mm"]),(0,.5,9.8))
        self.assertEqual((point["vx_mm_us"],point["vy_mm_us"],point["vz_mm_us"]),(0,1,0))
        count,_=census(data,1)
        self.assertEqual(count["sigma_axis"],"y")
        self.assertNotIn("sigma_x_mm",count)
        box=project_geometry(config)["electrodes"][0]["solids"][0]
        self.assertEqual(box["min_mm"],[-1,0,10.600000000000001])
        snapshots=[];evolution=[]
        for label,time in data["snapshots"]:
            row,states=census(data,time);evolution.append(row)
            snapshots.extend(dict(snapshot=label,**state) for state in states)
        figures=build_figures(data,snapshots,evolution)
        self.assertEqual(figures["timed_clouds"].axes[0].get_xlabel(),"y (mm)")
        self.assertEqual(figures["timed_clouds"].axes[0].get_ylabel(),"z (mm)")
        self.assertIn("vy (m/s)",[ax.get_ylabel() for ax in figures["stage_phase_space"].axes])
        for figure in figures.values():
            plt.close(figure)

    def test_preflight_contract_and_quench_pulse_distinction(self) -> None:
        contract=json.loads((self.run/"inputs/diagnostics.json").read_text(encoding="utf-8"))
        validate_diagnostics_config(contract)
        for mutation in (
            lambda d:d.update(max_extraction_bracket_us=0),
            lambda d:d.update(max_ordinary_bracket_us=True),
            lambda d:d["snapshots"][0].update(anchor="invented"),
            lambda d:d["snapshots"][0].update(offset_us=float("nan")),
            lambda d:d.update(stage_labels=["missing_stage"]),
        ):
            invalid=copy.deepcopy(contract);mutation(invalid)
            with self.assertRaises(ValueError):
                validate_diagnostics_config(invalid)
        data=prepare_data(self.run)
        context=pulse_timing_context(data)
        self.assertEqual(context["quench_start_us"],3)
        self.assertAlmostEqual(context["pulse_start_us"],3+0.5/3.7)
        self.assertLess(3.1,context["pulse_start_us"])
        self.assertIn("snapshot offsets reference quench start",context["meaning"])
        self.assertEqual(context["timing_policy"], "legacy_requested_quench")

    def test_frozen_actual_timing_drives_context_and_named_snapshot_anchors(self) -> None:
        c=json.loads((self.run/"inputs/resolved_model.json").read_text(encoding="utf-8"))
        c["native_timing"]=dict(primary_quench_us=3.05,pulse_start_us=3.2,requested_quench_us=3,
                                policy="frozen_fixture_not_recomputed")
        (self.run/"inputs/resolved_model.json").write_text(json.dumps(c),encoding="utf-8")
        contract=json.loads((self.run/"inputs/diagnostics.json").read_text(encoding="utf-8"))
        contract["snapshots"][-1].update(anchor="primary_quench_us", offset_us=.01)
        contract["snapshots"].append(dict(label="pulse",anchor="pulse_start_us",offset_us=.02))
        (self.run/"inputs/diagnostics.json").write_text(json.dumps(contract),encoding="utf-8")
        data=prepare_data(self.run)
        context=pulse_timing_context(data)
        self.assertEqual(context["quench_start_us"],3.05)
        self.assertEqual(context["pulse_start_us"],3.2)
        self.assertAlmostEqual(dict(data["snapshots"])["pre_extraction"],3.06)
        self.assertAlmostEqual(dict(data["snapshots"])["pulse"],3.22)

    def test_census_closes_with_unknown(self) -> None:
        data=prepare_data(self.run)
        for time in (0,.5,1,1.25,2,3,4):
            row,states=census(data,time)
            self.assertEqual(sum(row[k] for k in ("alive","extracted","lost","notborn","unknown")),3)
            self.assertEqual(len(states),3)
        row,_=census(data,3)
        self.assertGreater(row["unknown"],0)
        self.assertEqual(row["lost"],1)

    def test_extraction_bracket_boundary(self) -> None:
        data=prepare_data(self.run)
        data["tracks"][1]=[{**data["sources"][1],"t_us":3},{**data["sources"][1],"t_us":3.02,"x_mm":2}]
        data["times"][1]=[3,3.02]
        self.assertEqual(state_at(data,1,3.01)["status"],"alive")
        data["tracks"][1][1]["t_us"]=3.03
        data["times"][1]=[3,3.03]
        self.assertEqual(state_at(data,1,3.01)["status"],"unknown")

    def test_render_and_provenance_without_physics_claim(self) -> None:
        data=prepare_data(self.run)
        snapshots=[];evolution=[]
        for label,time in data["snapshots"]:
            row,states=census(data,time);evolution.append(row)
            snapshots.extend(dict(snapshot=label,**state) for state in states)
        figures=build_figures(data,snapshots,evolution)
        self.assertEqual(len(figures),6)
        labels=[axis.get_ylabel() for axis in figures["stage_phase_space"].axes]
        self.assertIn("vx (m/s)",labels)
        self.assertTrue(any("test_electrode" in label for _,label in zip(*figures["trajectory_geometry"].axes[0].get_legend_handles_labels())))
        for figure in figures.values():
            plt.close(figure)
        (self.run/"inputs/source_context.json").write_text(json.dumps({"git_sha":"frozen-test-sha","worktree_porcelain":"M frozen_file.py"}),encoding="utf-8")
        # The legacy fixture validates census/statistical panels, not full native
        # CSG section geometry. Mandatory producer wiring has its own test.
        def sections(run,out):
            template=(out/"stage_phase_space.metadata.json").read_text(encoding="utf-8")
            for role in ("structure_sections","timed_clouds_sections","extraction_clouds_sections"):
                for ext in ("png","svg","metadata.json"):
                    (out/f"{role}.{ext}").write_text(template,encoding="utf-8")
        def packet(run,out):
            template=(out/"stage_phase_space.metadata.json").read_text(encoding="utf-8")
            for ext in ("png","svg","metadata.json"):
                (out/f"post_extraction_packet.{ext}").write_text(template,encoding="utf-8")
            (out/"post_extraction_statistics.json").write_text('{"packet_status":"synthetic"}',encoding="utf-8")
            for name in ("plane","common_time"):
                (out/f"post_extraction_{name}_states.csv").write_text("particle_id\n",encoding="utf-8")
            return {"packet_status":"synthetic"}
        module="projects.dual_pressure_rectilinear_ion_processor.analysis.diagnostics"
        with patch(module+".export_sections",side_effect=sections),patch(module+".export_post_extraction",side_effect=packet):
            result=export_diagnostics(self.run)
        self.assertEqual(result["source_particle_count"],3)
        self.assertEqual(result["loss_count"],2)
        for role in result["figure_roles"]:
            self.assertTrue((self.run/f"results/{role}.png").is_file())
            self.assertTrue((self.run/f"results/{role}.svg").is_file())
            metadata=json.loads((self.run/f"results/{role}.metadata.json").read_text())
            self.assertEqual(metadata["source_particle_count"],3)
            self.assertFalse(metadata["numerical_or_GUI_qualification"])
            self.assertEqual(metadata["git"]["sha"],"frozen-test-sha")
            self.assertEqual(metadata["git"]["source"],"frozen inputs/source_context.json")
            self.assertIn("not every integration step",metadata["display_claim"])

    def test_long_apparatus_views_keep_physical_transverse_limits(self) -> None:
        data=prepare_data(self.run)
        data["config"]["baseline"]["geometry"]={"guide_length_mm":30,"hp_length_mm":100,"lp_length_mm":80,"lp_center_mm":170,"extraction_slit_length_mm":8}
        data["config"]["baseline"]["native_geometry"]={"domain_min_y_mm":-4,"domain_max_y_mm":10}
        snapshots=[];evolution=[]
        for label,time in data["snapshots"]:
            row,states=census(data,time);evolution.append(row)
            snapshots.extend(dict(snapshot=label,**state) for state in states)
        row,_=census(data,1)
        self.assertEqual(row["alive"],3)
        self.assertEqual(row["lp_alive_count"],0)
        self.assertIsNone(row["lp_sigma_x_mm"])
        figures=build_figures(data,snapshots,evolution)
        self.assertIn("all alive",figures["stage_phase_space"].axes[0].get_title())
        self.assertIn("LP=0",figures["stage_phase_space"].axes[0].get_title())
        axis=figures["timed_clouds"].axes[0]
        self.assertEqual(axis.get_aspect(),"auto")
        self.assertEqual(tuple(axis.get_xlim()),(-5,215))
        self.assertLess(axis.get_ylim()[1]-axis.get_ylim()[0],16)
        self.assertFalse(axis.get_legend())
        self.assertTrue(figures["timed_clouds"].legends)
        local=figures["extraction_local_clouds"].axes[0]
        self.assertEqual(tuple(local.get_xlim()),(166,174))
        self.assertIn("outside zoom",local.get_title())
        self.assertIn("quench start",figures["population_evolution"].axes[-1].get_xlabel())
        self.assertIn("full source denominator",figures["cooling_stage_energy"]._suptitle.get_text())
        for figure in figures.values():
            plt.close(figure)

    def test_hp_retained_particle_not_hidden_by_lp_conditioned_sigma(self) -> None:
        data=prepare_data(self.run)
        data["config"]["baseline"]["geometry"]={"guide_length_mm":30,"hp_length_mm":100,"lp_length_mm":80}
        for particle,x in ((1,119),(2,169.4),(3,170.6)):
            for row in data["tracks"][particle]:
                if row["t_us"]==1:
                    row["x_mm"]=x
        row,_=census(data,1)
        self.assertEqual(row["alive"],3)
        self.assertEqual(row["lp_alive_count"],2)
        self.assertAlmostEqual(row["lp_sigma_x_mm"],.6)
        self.assertGreater(row["sigma_x_mm"],20)

    def test_nonfinite_or_unknown_particle_rejected(self) -> None:
        path=self.run/"simion/samples.csv"
        text=path.read_text(encoding="utf-8")
        path.write_text(text.replace("1,1,1,", "1,1,nan,"),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"nonfinite"):
            prepare_data(self.run)


if __name__=="__main__":
    unittest.main()
