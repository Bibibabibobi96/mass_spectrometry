from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from common.ion_release.release import generate_release_states, materialize_release
from projects.orthogonal_accelerator.analysis.component_focus_analysis import ComponentFocusError, analyze

ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN = ROOT / "config" / "two_zone_component_focus_campaign.json"


class ComponentFocusAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        campaign = json.loads(CAMPAIGN.read_text(encoding="utf-8"))
        campaign["release_spec"]["particle_count"] = 3
        campaign["release_spec"]["mother_particle_count"] = 3
        self.campaign = self.root / "campaign.json"
        self.campaign.write_text(json.dumps(campaign), encoding="utf-8")
        self.state = self.root / "release.csv"
        self.receipt = self.root / "release.json"
        materialize_release(campaign["release_spec"], self.state, self.receipt)
        self.states = {
            state["particle_id"]: state
            for state in generate_release_states(campaign["release_spec"])
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_events(self, *, focus_z: float = 0.0) -> Path:
        rows = ["kind,ion,code,t_us,x_mm,y_mm,z_mm,vz_mm_us"]
        for particle_id, state in self.states.items():
            x, y, z = state["x_mm"], state["y_mm"], state["z_mm"]
            rows.extend((
                f"source,{particle_id},,0,{x},{y},{z},",
                f"focus,{particle_id},,0.1,0,0,{focus_z},-10",
                f"terminal,{particle_id},1,{particle_id},0,0,{focus_z},",
            ))
        path = self.root / "component_focus.events.csv"
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return path

    def test_accepts_complete_negative_z_full_population(self) -> None:
        result = analyze(self.write_events(), self.receipt, self.campaign)
        self.assertEqual(result["status"], "candidate_complete")
        self.assertEqual(result["focus_particle_count"], 3)
        self.assertEqual(result["loss_particle_count"], 0)
        self.assertEqual(result["transport_fraction"], 1.0)
        self.assertTrue(result["time_focus_assessment"]["passed"])

    def test_accepts_with_warning_when_the_longitudinal_time_spread_exceeds_target(self) -> None:
        events = self.write_events()
        events.write_text(events.read_text(encoding="utf-8").replace("focus,3,,0.1", "focus,3,,0.102"), encoding="utf-8")
        result = analyze(events, self.receipt, self.campaign)
        self.assertEqual(result["status"], "candidate_complete")
        self.assertIn("longitudinal_time_spread_exceeds_target", result["warnings"])
        self.assertFalse(result["time_focus_assessment"]["passed"])
        self.assertEqual(result["time_focus_assessment"]["exceedance_policy"], "warning")

    def test_reports_source_z_dominated_arrival_time_evidence(self) -> None:
        events = self.write_events()
        rewritten = []
        for line in events.read_text(encoding="utf-8").splitlines():
            fields = line.split(",")
            if fields[0] == "focus":
                fields[3] = str(0.1 + self.states[int(fields[1])]["z_mm"] * 0.001)
            rewritten.append(",".join(fields))
        events.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
        diagnostics = analyze(events, self.receipt, self.campaign)["arrival_time_diagnostics"]
        self.assertEqual(diagnostics["status"], "source_z_dominated")
        self.assertGreater(diagnostics["coordinate_associations"]["z_mm"]["pearson_r"], 0.99)
        self.assertEqual(diagnostics["edge_field_evidence"], "not_determined_from_arrival_coordinate_association")
        self.assertEqual(diagnostics["numerical_convergence"], "not_assessed_from_one_numerics_setting")

    def test_emits_matching_uniform_field_contrast_for_every_result(self) -> None:
        result = analyze(self.write_events(), self.receipt, self.campaign)
        contrast = result["ideal_field_contrast"]
        self.assertEqual(contrast["field_model"], "two_zone_piecewise_uniform_ideal_field_v1")
        self.assertTrue(contrast["same_release_and_runtime_voltages"])
        self.assertGreaterEqual(contrast["ideal_peak_to_peak_t_ns"], 0.0)
        self.assertIn(contrast["diagnosis"], {"native_finite_geometry_excess_supported", "no_material_native_finite_geometry_excess"})

    def test_rejects_focus_event_off_the_declared_plane(self) -> None:
        with self.assertRaisesRegex(ComponentFocusError, "declared focus plane"):
            analyze(self.write_events(focus_z=-0.2), self.receipt, self.campaign)

    def test_rejects_source_event_identity_mismatch(self) -> None:
        events = self.write_events()
        first = self.states[2]["x_mm"]
        events.write_text(events.read_text(encoding="utf-8").replace(f"source,2,,0,{first}", "source,2,,0,9"), encoding="utf-8")
        with self.assertRaisesRegex(ComponentFocusError, "differs from common release state"):
            analyze(events, self.receipt, self.campaign)

    def test_rejects_receipt_for_different_release_specification(self) -> None:
        campaign = json.loads(self.campaign.read_text(encoding="utf-8"))
        campaign["release_spec"]["particle_count"] = 2
        self.campaign.write_text(json.dumps(campaign), encoding="utf-8")
        with self.assertRaisesRegex(ComponentFocusError, "specification differs"):
            analyze(self.write_events(), self.receipt, self.campaign)

    def test_runner_binds_small_manifest_identities_without_payload_inventory(self) -> None:
        runner = (ROOT / "simion" / "run_component_focus_flight.ps1").read_text(encoding="utf-8")
        self.assertIn("pa_build_run_manifest_sha256", runner)
        self.assertIn("cache_manifest_sha256", runner)
        self.assertIn("orthogonal_accelerator_focus.pa0", runner)
        self.assertNotIn("Copy-Item -LiteralPath $controller", runner)
        self.assertIn("component_focus_input.fly2", runner)
        self.assertIn("fly --trajectory-quality $($c.numerics.trajectory_quality) --particles $fly --programs 1 --retain-trajectories 0 $iob", runner)
        self.assertIn("$events=Join-Path $solver 'component_focus.events.csv'", runner)
        self.assertIn("--events $events", runner)
        self.assertIn("$fly,$sourceStates,$iob,$events", runner)
        self.assertIn("Published PA span differs from provider plan", runner)
        self.assertIn("$originX=[double]$p.numerical_domain.iob_origin_mm[0]", runner)
        self.assertIn("$originY=[double]$p.numerical_domain.iob_origin_mm[1]+[double]$c.operating_point.instance_center_y_mm", runner)
        self.assertIn("$env:PYTHONPATH=$repoRoot", runner)
        self.assertIn("$env:PYTHONPATH=$previousPythonPath", runner)
        self.assertIn("$analysisResult.status-notin@('candidate_complete','candidate_incomplete')", runner)
        self.assertNotIn("throw 'Component focus acceptance incomplete'", runner)

    def test_lua_uses_one_persistent_csv_recorder_and_focus_terminal_sequence(self) -> None:
        program = (ROOT / "simion" / "component_focus.lua").read_text(encoding="utf-8")
        self.assertEqual(program.count("io.open("), 1)
        self.assertIn("event_file=assert(io.open('component_focus.events.csv','w')", program)
        self.assertIn("kind,ion,code,t_us,x_mm,y_mm,z_mm,vz_mm_us", program)
        source = program.index("emit_event('source'")
        focus = program.index("emit_event('focus'")
        capture = program.index("local function capture_focus")
        terminal = program.index("finalize_particle(particle,current,1)", capture)
        splat = program.index("ion_splat=1", capture)
        capture_call = program.index("capture_focus(ion_number,focus,current)", focus)
        self.assertLess(source, focus)
        self.assertLess(focus, capture_call)
        self.assertLess(capture, terminal)
        self.assertLess(terminal, splat)
        self.assertIn("function segment.terminate()", program)
        self.assertIn("finalize_particle(ion_number,current,focus_written[ion_number] and 1 or 2)", program)
        terminate = program[program.index("function segment.terminate()"):program.index("function segment.terminate_run()")]
        self.assertNotIn("ion_splat", terminate)
        self.assertIn("for particle=1,sim_ions_count do", program)
        self.assertIn("finalize_particle(particle,previous_state[particle],2)", program)
        self.assertIn("assert(sim_ions_count==point.particle_count", program)
        self.assertIn("local dt_to_plane=dz/(-current.vz)", program)
        self.assertIn("if dt_to_plane>0 and ion_time_step>dt_to_plane then ion_time_step=dt_to_plane end", program)
        self.assertIn("if math.abs(dz)<=point.focus_plane_tolerance_mm then record_focus(ion_number,current) end", program)
        self.assertIn("capture_focus(ion_number,focus,current)", program)
        tstep = program[program.index("function segment.tstep_adjust()"):program.index("function segment.initialize()")]
        self.assertNotIn("ion_splat", tstep)
        self.assertIn("authoritative source-states companion required", program)
        self.assertIn("ensure_source(ion_number,current)", program)
        self.assertNotIn("emit_event('source',ion_number,nil,current,nil)", program)

    def test_iob_builder_has_single_value_argument_helper_and_lua_regression(self) -> None:
        builder = (ROOT / "simion" / "build_component_focus_iob.lua").read_text(encoding="utf-8")
        regression = ROOT / "tests" / "simion" / "test_component_focus_iob_arguments.lua"
        self.assertIn("local function a(i,label)local v=assert(arg[i+o],label);return v end", builder)
        self.assertTrue(regression.is_file())
        self.assertIn("local ok,message=pcall(builder)", regression.read_text(encoding="utf-8"))



if __name__ == "__main__":
    unittest.main()
