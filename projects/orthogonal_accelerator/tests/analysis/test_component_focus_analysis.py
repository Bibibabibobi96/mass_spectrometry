from __future__ import annotations

import json
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common.contracts.particle_physics import kinetic_energy_ev, speed_m_s_from_kinetic_energy_ev
from common.ion_release.release import generate_release_states, materialize_release
from projects.orthogonal_accelerator.analysis.accelerator_time_focus import time_to_fixed_plane_s
from projects.orthogonal_accelerator.analysis.component_focus_analysis import ComponentFocusError, _ideal_two_zone_contrast, analyze

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
        rows = ["kind,ion,code,t_us,x_mm,y_mm,z_mm,vx_mm_us,vy_mm_us,vz_mm_us"]
        voltages = json.loads(self.campaign.read_text(encoding="utf-8"))["operating_point"]["electrode_voltages_v"]
        target = voltages[1] - (voltages[1] - voltages[2]) * 0.5
        for particle_id, state in self.states.items():
            x, y, z = state["x_mm"], state["y_mm"], state["z_mm"]
            source_axial = kinetic_energy_ev(100.0, 0.0, 0.0, state["vz_m_s"])
            particle_target = target + (voltages[1] - voltages[2]) * (state["z_mm"] - 32.0) / 4.0
            exit_vz = -speed_m_s_from_kinetic_energy_ev(100.0, particle_target + source_axial) / 1000.0
            exit_vy = state["vy_m_s"] / 1000.0
            rows.extend((
                f"source,{particle_id},,0,{x},{y},{z},{state['vx_m_s']/1000.0},{exit_vy},{state['vz_m_s']/1000.0}",
                f"exit,{particle_id},,0.1,0,0,0,0,{exit_vy},{exit_vz}",
                f"focus,{particle_id},,0.1,0,0,{focus_z},0,{exit_vy},{exit_vz}",
                f"terminal,{particle_id},1,{particle_id},0,0,{focus_z},0,{exit_vy},{exit_vz}",
            ))
        path = self.root / "component_focus.events.csv"
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return path

    def test_accepts_complete_negative_z_full_population(self) -> None:
        result = analyze(self.write_events(), self.receipt, self.campaign)
        self.assertEqual(result["status"], "candidate_complete")
        self.assertEqual(result["focus_particle_count"], 3)
        self.assertEqual(result["loss_particle_count"], 0)
        self.assertEqual(result["not_reached_focus_particle_count"], 0)
        self.assertEqual(result["not_reached_focus_particle_ids"], [])
        self.assertEqual(result["release_mother_particle_count"], 3)
        self.assertEqual(result["transport_fraction_denominator_semantics"], "this_run_released_cohort")
        self.assertEqual(result["transport_fraction"], 1.0)
        self.assertTrue(result["time_focus_assessment"]["passed"])
        self.assertTrue(result["exit_energy_assessment"]["passed"])
        self.assertEqual(result["hard_gate"], {"complete_transport_passed": True, "exit_slow_energy_passed": True, "exit_axial_energy_passed": True, "exit_transverse_energy_passed": True, "exit_transverse_velocity_bias_passed": True})

    def test_signed_transverse_velocity_bias_is_a_hard_gate(self) -> None:
        events = self.write_events()
        lines = events.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            fields = line.split(",")
            if fields[0] in {"exit", "focus"}:
                fields[7] = "0.001"
                lines[index] = ",".join(fields)
        events.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = analyze(events, self.receipt, self.campaign)
        self.assertEqual(result["status"], "candidate_incomplete")
        self.assertFalse(result["hard_gate"]["exit_transverse_velocity_bias_passed"])
        self.assertAlmostEqual(
            result["exit_energy_assessment"]["cohort"]["mean_delta_vx_mm_per_us"],
            0.001,
        )

    def test_exit_energy_failure_is_a_hard_gate(self) -> None:
        events = self.write_events()
        lines = events.read_text(encoding="utf-8").splitlines()
        fields = lines[2].split(",")
        fields[8] = "1"
        lines[2] = ",".join(fields)
        focus = lines[3].split(",")
        focus[8] = "1"
        lines[3] = ",".join(focus)
        events.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = analyze(events, self.receipt, self.campaign)
        self.assertEqual(result["status"], "candidate_incomplete")
        self.assertFalse(result["hard_gate"]["exit_slow_energy_passed"])

    def test_accepts_with_warning_when_the_longitudinal_time_spread_exceeds_target(self) -> None:
        events = self.write_events()
        events.write_text(events.read_text(encoding="utf-8").replace("focus,3,,0.1", "focus,3,,0.102").replace("exit,3,,0.1", "exit,3,,0.102"), encoding="utf-8")
        result = analyze(events, self.receipt, self.campaign)
        self.assertEqual(result["status"], "candidate_complete")
        self.assertIn("longitudinal_time_spread_exceeds_target", result["warnings"])
        self.assertFalse(result["time_focus_assessment"]["passed"])
        self.assertEqual(result["time_focus_assessment"]["exceedance_policy"], "warning")
        self.assertEqual(result["ideal_field_contrast"]["diagnosis"], "observed_comparison_cause_unassessed")

    def test_reports_source_z_dominated_arrival_time_evidence(self) -> None:
        events = self.write_events()
        rewritten = []
        for line in events.read_text(encoding="utf-8").splitlines():
            fields = line.split(",")
            if fields[0] in {"exit", "focus"}:
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
        self.assertEqual(contrast["diagnosis"], "observed_comparison_cause_unassessed")
        self.assertEqual(contrast["paired_particle_ids"], [1, 2, 3])
        self.assertEqual(contrast["ideal_propagation_failure_count"], 0)
        self.assertTrue(contrast["width_comparison_available"])

    def test_ideal_contrast_uses_same_observation_plane_source_velocity_and_species(self) -> None:
        campaign = json.loads(self.campaign.read_text(encoding="utf-8"))
        voltages = campaign["operating_point"]["electrode_voltages_v"]
        voltages[1:4] = [4748.232329423991, 3994.2379835760084, 0.0]
        sources = {index: {"z_mm": z, "vz_m_s": 0.0, "t_us": 5.0}
                   for index, z in enumerate((31.6, 32.0, 32.4), 1)}
        expected_spreads = {0.0: 0.316801278, -10.0: 1.940745494}
        for offset, expected in expected_spreads.items():
            with self.subTest(offset=offset):
                campaign["operating_point"]["focus_plane_offset_from_exit_mm"] = offset
                hits = {particle: (state, {"t_us": 5.0 + time_to_fixed_plane_s(
                    voltages[1], voltages[2], 4.0, 30.0, 34.0-state["z_mm"],
                    0.0, -offset, 100.0)*1e6}) for particle, state in sources.items()}
                result = _ideal_two_zone_contrast(hits, campaign)
                self.assertAlmostEqual(result["ideal_peak_to_peak_t_ns"], expected, places=7)
                self.assertEqual(result["observation_plane_offset_from_exit_mm"], offset)
                self.assertEqual(result["diagnosis"], "observed_comparison_cause_unassessed")
                self.assertAlmostEqual(result["paired_time_difference_ns"]["rms"], 0.0)
        campaign["release_spec"]["species"].update(mass_amu=150.0, charge_state=2)
        sources[1]["vz_m_s"], sources[3]["vz_m_s"] = 125.0, -200.0
        arrivals = [time_to_fixed_plane_s(voltages[1], voltages[2], 4.0, 30.0,
                    34.0-state["z_mm"], -state["vz_m_s"], 10.0, 75.0, exit_v=0.0)*1e9
                    for state in sources.values()]
        hits = {particle: (state, {"t_us": 5.0 + arrival / 1000.0})
                for (particle, state), arrival in zip(sources.items(), arrivals, strict=True)}
        result = _ideal_two_zone_contrast(hits, campaign)
        self.assertAlmostEqual(result["native_minus_ideal_peak_to_peak_t_ns"], 0.0, places=12)
        self.assertAlmostEqual(result["paired_time_difference_ns"]["rms"], 0.0, places=9)

    def retain_focus_ids(self, particle_ids: set[int]) -> Path:
        events = self.write_events()
        with events.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fields, rows = reader.fieldnames, list(reader)
        with events.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(row for row in rows if row["kind"] != "focus" or int(row["ion"]) in particle_ids)
        return events

    def test_partial_hits_compare_only_the_same_ids_without_changing_mother_denominator(self) -> None:
        result = analyze(self.retain_focus_ids({1, 3}), self.receipt, self.campaign)
        contrast = result["ideal_field_contrast"]
        self.assertEqual((result["particle_count"], result["focus_particle_count"], result["loss_particle_count"]), (3, 2, 1))
        self.assertEqual(result["transport_fraction"], 2 / 3)
        self.assertEqual(result["not_reached_focus_particle_count"], 1)
        self.assertEqual(result["not_reached_focus_particle_ids"], [2])
        self.assertIn("not_physical_loss", result["loss_particle_count_semantics"])
        self.assertFalse(result["hard_gate"]["complete_transport_passed"])
        self.assertEqual(contrast["requested_particle_ids"], [1, 3])
        self.assertEqual(contrast["paired_particle_ids"], [1, 3])
        full = analyze(self.write_events(), self.receipt, self.campaign)["ideal_field_contrast"]
        self.assertNotAlmostEqual(contrast["ideal_peak_to_peak_t_ns"], full["ideal_peak_to_peak_t_ns"], places=6)

    def test_zero_and_single_hit_have_no_width_or_cause_conclusion(self) -> None:
        for ids, status in ((set(), "unavailable_no_focus_hits"), ({3}, "single_pair_no_width_conclusion")):
            with self.subTest(ids=ids):
                result = analyze(self.retain_focus_ids(ids), self.receipt, self.campaign)
                contrast = result["ideal_field_contrast"]
                self.assertEqual(contrast["status"], status)
                self.assertEqual(contrast["paired_particle_count"], len(ids))
                self.assertEqual(contrast["diagnosis"], "not_assessable")
                self.assertFalse(contrast["width_comparison_available"])
                self.assertIsNone(contrast["ideal_peak_to_peak_t_ns"])
                self.assertIsNone(contrast["native_peak_to_peak_t_ns"])
                self.assertIsNone(result["focus_metrics"]["peak_to_peak_t_ns"])
                self.assertIsNone(contrast["paired_time_difference_ns"]["peak_to_peak"])
                self.assertEqual(result["status"], "candidate_incomplete")

    def test_ideal_propagation_failure_is_counted_without_silent_cohort_reduction(self) -> None:
        real = time_to_fixed_plane_s
        calls = 0
        def propagate(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError("test-only no ideal crossing")
            return real(*args, **kwargs)
        with patch("projects.orthogonal_accelerator.analysis.component_focus_analysis.time_to_fixed_plane_s", side_effect=propagate):
            result = analyze(self.write_events(), self.receipt, self.campaign)
        contrast = result["ideal_field_contrast"]
        self.assertEqual(contrast["status"], "incomplete_ideal_propagation")
        self.assertEqual(contrast["requested_particle_count"], 3)
        self.assertEqual(contrast["paired_particle_ids"], [1, 3])
        self.assertEqual(contrast["ideal_failure_particle_ids"], [2])
        self.assertEqual(contrast["ideal_propagation_failure_count"], 1)
        self.assertEqual(contrast["particle_pairs"][1]["ideal_error"], "test-only no ideal crossing")
        self.assertFalse(contrast["width_comparison_available"])
        self.assertIsNone(contrast["native_minus_ideal_peak_to_peak_t_ns"])
        self.assertEqual(result["focus_particle_count"], 3)
        self.assertTrue(result["hard_gate"]["complete_transport_passed"])

    def test_source_clock_matches_release_and_pairing_preserves_absolute_arrivals(self) -> None:
        campaign = json.loads(self.campaign.read_text(encoding="utf-8"))
        campaign["release_spec"]["common_time_of_birth_s"] = 7e-6
        self.campaign.write_text(json.dumps(campaign), encoding="utf-8")
        materialize_release(campaign["release_spec"], self.state, self.receipt)
        events = self.write_events()
        with self.assertRaisesRegex(ComponentFocusError, "clock differs"):
            analyze(events, self.receipt, self.campaign)
        with events.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            row["t_us"] = str(float(row["t_us"]) + 7.0)
        with events.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
        result = analyze(events, self.receipt, self.campaign)
        pairs = result["ideal_field_contrast"]["particle_pairs"]
        self.assertTrue(all(row["source_t_us"] == 7.0 and row["ideal_arrival_t_us"] > 7.0 for row in pairs))
        self.assertTrue(all(row["native_arrival_t_us"] == 7.1 for row in pairs))

    def test_rejects_focus_event_off_the_declared_plane(self) -> None:
        with self.assertRaises(ComponentFocusError):
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
        self.assertIn("[Parameter(Mandatory)][string]$RuntimeControllerPath", runner)
        self.assertIn("$controller=(Resolve-Path -LiteralPath $RuntimeControllerPath).Path", runner)
        self.assertIn("$expectedRuntimeNames=@(0..$electrodeCount", runner)
        self.assertIn("Flight refuses a controller inside the published cache generation", runner)
        self.assertIn("Private runtime family inventory differs from the provider electrode namespace", runner)
        self.assertNotIn("Get-FileHash (Join-Path $runtimeDirectory", runner)
        self.assertNotIn("Get-FileHash $controller", runner)
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

    def test_iob_builder_has_single_value_argument_helper_and_lua_regression(self) -> None:
        builder = (ROOT / "simion" / "build_component_focus_iob.lua").read_text(encoding="utf-8")
        regression = ROOT / "tests" / "simion" / "test_component_focus_iob_arguments.lua"
        self.assertIn("local function a(i,label)local v=assert(arg[i+o],label);return v end", builder)
        self.assertTrue(regression.is_file())
        self.assertIn("local ok,message=pcall(builder)", regression.read_text(encoding="utf-8"))



if __name__ == "__main__":
    unittest.main()
