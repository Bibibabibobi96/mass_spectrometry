"""Synthetic diagnostics contracts; no native solver or physical evidence is produced."""
from __future__ import annotations

import copy
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import numpy as np

from projects.dual_pressure_rectilinear_ion_processor.analysis import field_diagnostics as diagnostics
from projects.dual_pressure_rectilinear_ion_processor.analysis.functional import derive_native_timing, lua_literal
from projects.dual_pressure_rectilinear_ion_processor.analysis.native_geometry import native_projection


PROJECT = Path(__file__).resolve().parents[1]
REPOSITORY = PROJECT.parents[1]


def config_fixture() -> dict:
    """Read current sampling contract, without duplicating physical geometry."""
    return json.loads((PROJECT/"config/field_diagnostics.json").read_text(encoding="utf-8"))


def quadratic_rows() -> list[dict]:
    """An independently specified quadratic with known coefficients and fields."""
    return [dict(stage_id="fixture",section_id="fixture",sample_kind="cross_section",electrode=0,t_us=0,
                 x_mm=1,y_mm=float(y),z_mm=float(z),potential_v=float(7+2*y-3*z+4*y*y+5*y*z-6*z*z),
                 ex_v_per_mm=0,ey_v_per_mm=float(-2-8*y-5*z),ez_v_per_mm=float(3-5*y+12*z))
            for y in np.linspace(-.5,.5,11) for z in np.linspace(-.5,.5,11)]


class FieldDiagnosticsTests(unittest.TestCase):
    """Validate units, near-axis fits, true slot outlines and headless layout."""

    def transformed_config(self) -> dict:
        return {"coordinate_transform": json.loads((PROJECT/"config/coordinate_transform.json").read_text())}

    def test_project_samples_rotate_all_vectors_without_changing_scalars(self) -> None:
        row = {**quadratic_rows()[0], "x_mm":170, "y_mm":9.8, "z_mm":2,
               "ex_v_per_mm":2, "ey_v_per_mm":3, "ez_v_per_mm":4}
        original = copy.deepcopy(row)
        actual = diagnostics.project_field_rows([row], self.transformed_config())[0]
        self.assertEqual([actual[k] for k in ("x_mm","y_mm","z_mm")], [-2,170,0])
        self.assertEqual([actual[k] for k in ("ex_v_per_mm","ey_v_per_mm","ez_v_per_mm")], [-4,2,-3])
        self.assertEqual(actual["potential_v"], row["potential_v"])
        self.assertEqual(actual["t_us"], row["t_us"])
        self.assertEqual(row, original)

    def test_project_orthogonal_line_sorts_z_and_reverses_field(self) -> None:
        config = config_fixture(); config["stages"] = config["stages"][:1]
        config["_project_coordinates"] = True
        rows = [{**quadratic_rows()[0], "stage_id":config["stages"][0]["stage_id"],
                 "sample_kind":"orthogonal", "x_mm":170, "y_mm":y, "z_mm":0,
                 "ey_v_per_mm":y+1} for y in (0,1,2)]
        project = diagnostics.project_field_rows(rows, self.transformed_config())
        _, axes = diagnostics.build_line_figure(project, config, "orthogonal")
        np.testing.assert_allclose(axes[1].lines[0].get_xdata(), [7.8,8.8,9.8])
        np.testing.assert_allclose(axes[1].lines[0].get_ydata(), [-3,-2,-1])
        self.assertEqual(axes[1].get_xlabel(), "z (mm)")
        self.assertEqual(axes[1].get_ylabel(), "E_z (V/mm)")

    def test_project_sections_rotate_arrows_and_preserve_slot_subtraction(self) -> None:
        config = config_fixture(); config["sections"] = [{"section_id":"fixture","position_ref":"lp_center"}]
        config.update(_project_coordinates=True, _transform_config=self.transformed_config())
        rows = diagnostics.project_field_rows(quadratic_rows(), self.transformed_config())
        electrode={"electrode_id":5,"solids":[{"shape":"box","min_mm":[0,2,-1],"max_mm":[10,2.5,1]}],
                   "cutouts":[{"shape":"box","min_mm":[0,1.8,-.4],"max_mm":[10,2.7,.4]}]}
        _, axes = diagnostics.build_section_figure(rows,config,{"electrodes":[electrode]},"fixture",10)
        ax = axes[0]
        self.assertEqual(ax.get_xlabel(), "z (mm)")
        self.assertEqual(ax.get_ylabel(), "x (mm)")
        self.assertIn("y=1 mm",ax.get_title())
        self.assertEqual(len(ax.patches),2)
        np.testing.assert_allclose(sorted(p.get_x() for p in ax.patches),[7.3,7.3])
        np.testing.assert_allclose(sorted(p.get_y() for p in ax.patches),[-1,.4])
        lookup = {(r["z_mm"],r["x_mm"]):r for r in rows}
        ordered = [lookup[z,x] for x in sorted({r["x_mm"] for r in rows})[::config["quiver_stride"]]
                   for z in sorted({r["z_mm"] for r in rows})[::config["quiver_stride"]]]
        np.testing.assert_allclose(ax.collections[1].U,[r["ez_v_per_mm"] for r in ordered])
        np.testing.assert_allclose(ax.collections[1].V,[r["ex_v_per_mm"] for r in ordered])

    def test_config_rejects_invalid_sampling_and_stage_references(self) -> None:
        diagnostics.validate_field_diagnostics_config(config_fixture())
        for mutate in (lambda c:c.update(epsilon_us=float("nan")),
                       lambda c:c.update(quiver_stride=0),
                       lambda c:c["stages"][0].update(time_ref="unknown"),
                       lambda c:c["stages"].append(copy.deepcopy(c["stages"][0])),
                       lambda c:c.update(fit_radius_scale=2)):
            config=config_fixture();mutate(config)
            with self.assertRaises(ValueError):
                diagnostics.validate_field_diagnostics_config(config)

    def test_field_conversion_retains_electric_field_sign(self) -> None:
        np.testing.assert_allclose(diagnostics.field_gu_to_v_per_mm(np.array([1,-2,3]),.1),[10,-20,30])
        with self.assertRaises(ValueError):
            diagnostics.field_gu_to_v_per_mm(np.array([1]),0)

    def test_frozen_source_context_avoids_git_lookup_in_frozen_code_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="native_field_source_context_") as temporary:
            run=Path(temporary);(run/"inputs").mkdir()
            (run/"inputs/source_context.json").write_text(json.dumps({"git_sha":"a"*40,"worktree_dirty":True}),encoding="utf-8")
            with mock.patch.object(diagnostics.subprocess,"run",side_effect=AssertionError("Git must not be invoked")):
                context=diagnostics.source_context(run)
            self.assertEqual(context["origin"],"frozen_inputs_source_context")
            self.assertEqual(context["git_sha"],"a"*40)
            self.assertTrue(context["worktree_dirty"])
            self.assertTrue(context["available"])

    def test_unavailable_live_git_is_explicit_without_failing_export_context(self) -> None:
        with tempfile.TemporaryDirectory(prefix="native_field_no_git_") as temporary:
            result=subprocess.CompletedProcess([],128,stdout="",stderr="not a repository")
            with mock.patch.object(diagnostics.subprocess,"run",return_value=result) as invoke:
                context=diagnostics.source_context(Path(temporary))
            self.assertFalse(context["available"])
            self.assertIsNone(context["git_sha"])
            self.assertIsNone(context["worktree_dirty"])
            self.assertTrue(all(call.kwargs["check"] is False for call in invoke.call_args_list))

    def test_producer_identity_distinguishes_actual_missing_and_different_frozen_code(self) -> None:
        with tempfile.TemporaryDirectory(prefix="native_field_producer_identity_") as temporary:
            run=Path(temporary)
            identity=diagnostics.producer_identity(run)
            self.assertEqual(identity["actual_source_sha256"],diagnostics.PRODUCER_SOURCE_SHA256)
            self.assertIsNone(identity["matches_frozen"])
            frozen=run/identity["frozen_source_path"];frozen.parent.mkdir(parents=True)
            frozen.write_text("-- deliberately different inert frozen source\n",encoding="utf-8")
            self.assertFalse(diagnostics.producer_identity(run)["matches_frozen"])
            frozen.write_bytes(diagnostics.PRODUCER_SOURCE_PATH.read_bytes())
            self.assertTrue(diagnostics.producer_identity(run)["matches_frozen"])

    def test_quadratic_fit_recovers_common_mode_curvatures_and_mixed_term(self) -> None:
        result=diagnostics.fit_transverse_quadratic(quadratic_rows(),.5)
        for key,value in {"phi0_v":7,"linear_y_v_per_mm":2,"linear_z_v_per_mm":-3,
                          "curvature_yy_v_per_mm2":8,"mixed_yz_v_per_mm2":5,"curvature_zz_v_per_mm2":-12}.items():
            self.assertAlmostEqual(result[key],value,places=11)
        self.assertLess(result["residual_rms_v"],1e-11)
        with self.assertRaises(ValueError):
            diagnostics.fit_transverse_quadratic(quadratic_rows()[:5],.5)

    def test_metal_outlines_subtract_actual_slot(self) -> None:
        electrode={"solids":[{"shape":"box","min_mm":[0,2,-1],"max_mm":[10,2.5,1]}],
                   "cutouts":[{"shape":"box","min_mm":[4,1.8,-.4],"max_mm":[6,2.7,.4]}]}
        self.assertEqual(diagnostics.section_metal_rectangles(electrode,5),[(2,-1,2.5,-.4),(2,.4,2.5,1)])
        self.assertEqual(diagnostics.section_metal_rectangles(electrode,3),[(2,-1,2.5,1)])

    def test_section_layout_uses_shared_scale_labels_and_equal_aspect(self) -> None:
        config=config_fixture();config["stages"]=config["stages"][:1]
        config["sections"]=[{"section_id":"left","position_ref":"lp_center"},
                            {"section_id":"right","position_ref":"lp_center"}]
        rows=[{**row,"stage_id":config["stages"][0]["stage_id"],"section_id":section["section_id"]}
              for section in config["sections"] for row in quadratic_rows()]
        figure,axes=diagnostics.build_section_figure(rows,config,{"electrodes":[]},config["stages"][0]["stage_id"],10)
        self.assertEqual(len(figure.axes),3)
        self.assertEqual(axes[0].collections[0].get_clim(),(-10,10))
        self.assertIs(axes[0].collections[0].norm,axes[1].collections[0].norm)
        self.assertEqual(axes[0].get_ylabel(),"z (mm)")
        self.assertTrue(all(ax.get_xlabel()=="y (mm)" and ax.get_aspect()==1 for ax in axes))
        figure.canvas.draw()
        with tempfile.TemporaryDirectory(prefix="native_field_plot_fixture_") as temporary:
            path=Path(temporary)/"fixture.svg"
            figure.savefig(path,format="svg")
            self.assertGreater(path.stat().st_size,0)

    def test_transfer_detail_crops_stages_and_range_without_rebasing_values(self) -> None:
        config=config_fixture()
        rows=[]
        for stage,offset in (("capture_dc",-5),("transfer_dc",2),("preextract_dc",4000)):
            for x in (0,30,90,145,180):
                rows.append(dict(stage_id=stage,section_id="axis",sample_kind="axial",electrode=0,
                                 x_mm=x,potential_v=offset+.01*x,ex_v_per_mm=-.01))
        figure,axes=diagnostics.build_transfer_line_figure(rows,config,{"geometry":{"guide_length_mm":30,"hp_length_mm":100}})
        self.assertEqual(tuple(axes[0].get_xlim()),(30,145))
        self.assertEqual(len(axes[0].lines),2)
        np.testing.assert_allclose(axes[0].lines[0].get_ydata(),[-4.7,-4.1,-3.55])
        np.testing.assert_allclose(axes[0].lines[1].get_ydata(),[2.3,2.9,3.45])
        self.assertLess(axes[0].get_ylim()[1],10)
        self.assertIn("cropped",axes[0].get_title())
        self.assertEqual(axes[0].get_ylabel(),"Potential (V)")
        figure.canvas.draw()

    def test_actual_lua_probe_converts_units_and_keeps_post_pulse_audit(self) -> None:
        executable=os.environ.get("SIMION_LUA_EXE") or shutil.which("lua")
        if executable is None:
            path=Path(os.environ.get("ProgramFiles","C:/Program Files"))/"SIMION-2020/lua.exe"
            if path.is_file():executable=str(path)
        if executable is None:self.skipTest("Standalone Lua unavailable")
        config={name:json.loads((PROJECT/"config"/f"{name}.json").read_text(encoding="utf-8"))
                for name in ("baseline","numerics","native_operating_point")}
        config["native_projection"]=native_projection(config["baseline"],config["numerics"])
        config["native_timing"] = derive_native_timing(config["baseline"])
        d=config_fixture();d.update(section_grid_multiple=10,axial_grid_multiple=100,orthogonal_grid_multiple=10)
        config["field_diagnostics"]=d
        with tempfile.TemporaryDirectory(prefix="native_field_probe_fixture_") as temporary:
            folder=Path(temporary);config["native_field"]={"directory":str(folder)}
            for name in ("native_drive.lua","probe_native_field.lua"):
                shutil.copyfile(PROJECT/"simion"/name,folder/name)
            shutil.copyfile(REPOSITORY/"common/multipole/simion_rf_drive.lua",folder/"simion_rf_drive.lua")
            (folder/"frozen_config.lua").write_text("return "+lua_literal(config),encoding="utf-8")
            harness=r'''
local pa={}
local function amplitude(v) return v[1]+v[3]+v[5] end
function pa:potential_vc(x,y,z,v) return (x+2*y+3*z)*amplitude(v) end
function pa:field_vc(x,y,z,v) local a=amplitude(v);return -a,-2*a,-3*a end
function pa:electrode(...) assert(select('#',...)==3,'read-only electrode query expected');return false end
simion={pas={open=function(_,path) assert(path:match('processor%.pa0$'));return pa end}}
assert(loadfile(arg[1]))()
'''
            (folder/"fixture.lua").write_text(harness,encoding="utf-8")
            result=subprocess.run([executable,str(folder/"fixture.lua"),str(folder/"probe_native_field.lua")],
                                  cwd=folder,capture_output=True,text=True,encoding="utf-8",timeout=30,check=False)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            rows=diagnostics.read_field_samples(folder/"native_field_samples.csv",d)
            rf_row=next(row for row in rows if row["stage_id"]=="capture_rf_only_peak")
            expected_amplitude=3*config["baseline"]["electric"]["rf_peak_to_peak_v"]/2
            self.assertAlmostEqual(rf_row["ex_v_per_mm"],-expected_amplitude/config["numerics"]["native_grid_mm"])
            self.assertAlmostEqual(rf_row["ey_v_per_mm"],2*rf_row["ex_v_per_mm"])
            with (folder/"native_potential_audit.csv").open(encoding="utf-8") as handle:
                audit=list(csv.DictReader(handle))
            self.assertGreater(max(float(row["t_us"]) for row in audit),config["baseline"]["schedule"]["extraction_start_us"])
            self.assertEqual({float(row["t_us"]) for row in audit},
                             {float(format(time,".15g")) for time in (
                                 config["native_timing"]["primary_quench_us"]-d["epsilon_us"],
                                 config["native_timing"]["primary_quench_us"],
                                 config["native_timing"]["pulse_start_us"]+d["epsilon_us"])})
            middle = {row["t_us"] for row in rows if row["stage_id"] == "quench_total"}
            self.assertTrue(all(config["native_timing"]["primary_quench_us"] < time < config["native_timing"]["pulse_start_us"]
                                for time in middle))

    def test_export_metadata_binds_raw_native_config_and_figure_hashes(self) -> None:
        c={name:json.loads((PROJECT/"config"/f"{name}.json").read_text(encoding="utf-8"))
           for name in ("baseline","numerics")}
        d=config_fixture()
        d["stages"]=[stage for stage in d["stages"] if stage["component"]=="rf_only_peak"]
        c["field_diagnostics"]=d
        c["native_projection"]=native_projection(c["baseline"],c["numerics"])
        c["native_timing"] = derive_native_timing(c["baseline"])
        rows=[]
        for stage in d["stages"]:
            for section in d["sections"]:
                rows.extend({**row,"stage_id":stage["stage_id"],"section_id":section["section_id"]}
                            for row in quadratic_rows())
            for kind,section in (("axial","axis"),("orthogonal","lp_exit")):
                rows.extend({**row,"stage_id":stage["stage_id"],"section_id":section,"sample_kind":kind}
                            for row in quadratic_rows()[:3])
        with tempfile.TemporaryDirectory(prefix="native_field_export_fixture_") as temporary:
            run=Path(temporary)
            (run/"inputs").mkdir();(run/"simion").mkdir()
            c["native_field"]={"directory":str(run/"simion"),"role":"inert_synthetic_fixture_not_native_solver_output"}
            (run/"simion/processor.pa0").write_text("INERT TEST HASH TARGET; NOT A REAL PA\n",encoding="utf-8")
            (run/"inputs/resolved_model.json").write_text(json.dumps(c),encoding="utf-8")
            (run/"inputs/source_context.json").write_text(json.dumps({"git_sha":"b"*40,"worktree_dirty":False}),encoding="utf-8")
            with (run/"simion/native_field_samples.csv").open("w",encoding="utf-8",newline="") as handle:
                writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
            metadata=diagnostics.export_field_diagnostics(run)
            self.assertEqual(metadata["sample_count"],len(rows))
            self.assertEqual(metadata["native_timing"], c["native_timing"])
            self.assertEqual(len(metadata["fits"]),6)
            self.assertEqual(len(metadata["outputs"]),8)
            self.assertEqual(metadata["units"]["electric_field"],"V/mm")
            self.assertEqual(len(metadata["native_pa0_sha256"]),64)
            self.assertEqual(len(metadata["raw_samples_sha256"]),64)
            self.assertEqual(metadata["git_sha"],"b"*40)
            self.assertEqual(metadata["producer"]["actual_source_sha256"],diagnostics.PRODUCER_SOURCE_SHA256)
            self.assertIsNone(metadata["producer"]["matches_frozen"])
            self.assertEqual(metadata["symmetric_color_limits_v"][d["stages"][0]["stage_id"]],
                             metadata["symmetric_color_limits_v"][d["stages"][1]["stage_id"]])
            with self.assertRaises(FileExistsError):
                diagnostics.export_field_diagnostics(run)
            project_run=run/"project_frame_fixture"
            (project_run/"inputs").mkdir(parents=True);(project_run/"simion").mkdir()
            transformed={**c, **self.transformed_config()}
            transformed["native_field"]={"directory":str(project_run/"simion")}
            (project_run/"inputs/resolved_model.json").write_text(json.dumps(transformed),encoding="utf-8")
            for relative in ("inputs/source_context.json","simion/processor.pa0","simion/native_field_samples.csv"):
                shutil.copyfile(run/relative,project_run/relative)
            original=(project_run/"simion/native_field_samples.csv").read_bytes()
            project_metadata=diagnostics.export_field_diagnostics(project_run)
            self.assertEqual(len(project_metadata["outputs"]),9)
            self.assertEqual(project_metadata["raw_sample_frame_id"],c["baseline"]["clock"]["frame_id"])
            self.assertEqual(project_metadata["frame_id"],transformed["coordinate_transform"]["to_frame_id"])
            self.assertEqual(project_metadata["fit_coordinate_system"]["variables"],["local_y_mm","local_z_mm"])
            project_path=project_run/"results/native_field_samples_project.csv"
            with project_path.open(newline="") as stream:
                exported=list(csv.DictReader(stream))
            self.assertEqual(len(exported),len(rows))
            self.assertAlmostEqual(float(exported[0]["z_mm"]),9.8-rows[0]["y_mm"])
            self.assertAlmostEqual(float(exported[0]["ez_v_per_mm"]),-rows[0]["ey_v_per_mm"])
            self.assertEqual((project_run/"simion/native_field_samples.csv").read_bytes(),original)
            # A read-only derivative writes outside the source run. Both the
            # transformed CSV and figures must point to those actual outputs.
            outside=run/"external_field_figures"
            external_metadata=diagnostics.export_field_diagnostics(project_run,outside)
            self.assertEqual(len(external_metadata["outputs"]),9)
            for record in external_metadata["outputs"]:
                output_path=Path(record["path"])
                self.assertTrue(output_path.is_absolute())
                self.assertTrue(output_path.is_relative_to(outside))
                self.assertTrue(output_path.is_file())
            self.assertEqual((project_run/"simion/native_field_samples.csv").read_bytes(),original)
            record=next(record for record in project_metadata["outputs"] if record["path"].endswith(".csv"))
            self.assertEqual(record["sha256"],diagnostics.file_sha256(project_path))


if __name__=="__main__":
    unittest.main()
