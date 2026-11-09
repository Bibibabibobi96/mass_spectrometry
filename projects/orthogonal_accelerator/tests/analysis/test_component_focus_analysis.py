from __future__ import annotations

import json
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from msplatform.contracts.particle_physics import kinetic_energy_ev, speed_m_s_from_kinetic_energy_ev
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

    def test_actual_runner_freezes_public_csv_writer_companion(self) -> None:
        import subprocess
        repo = ROOT.parents[1]
        def quote(path):
            return "'" + str(path).replace("'", "''") + "'"
        script = """$ErrorActionPreference='Stop'
$repoRoot=REPO
$solver=DESTINATION
. (Join-Path $repoRoot 'common/contracts/run_artifact_support.ps1')
$source=Join-Path $repoRoot 'projects/orthogonal_accelerator/simion/run_component_focus_flight.ps1'
$tokens=$null;$errors=$null
$tree=[System.Management.Automation.Language.Parser]::ParseFile($source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Runner parse failed'}
$copies=@($tree.FindAll({param($node) $node -is [System.Management.Automation.Language.CommandAst] -and $node.GetCommandName() -eq 'Copy-VerifiedRunInput' -and $node.Extent.Text.Contains('src/msplatform/backends/simion/resources/scientific_event_csv.lua')},$true))
if($copies.Count -ne 1){throw 'Expected one actual writer freeze command'}
Invoke-Expression $copies[0].Extent.Text | Out-Null
""".replace('REPO', quote(repo)).replace('DESTINATION', quote(self.root))
        completed = subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-Command', script],
                                   cwd=self.root, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual((self.root / 'component_focus.scientific_event_csv.lua').read_bytes(),
                         (repo / 'src/msplatform/backends/simion/resources/scientific_event_csv.lua').read_bytes())

    def test_public_stream_reader_retains_header_contract_and_rejects_bad_rows(self) -> None:
        from msplatform.io.scientific_csv import iter_csv_rows
        from projects.orthogonal_accelerator.analysis import component_focus_analysis as focus
        events = self.write_events()
        with patch.object(focus, "iter_csv_rows", wraps=iter_csv_rows) as reader:
            result = focus._events(events)
        reader.assert_called_once_with(events, focus._CSV_FIELDS, exact_header=focus._CSV_FIELDS)
        self.assertEqual(set(result), set(self.states))
        header = ",".join(focus._CSV_FIELDS)
        for content in (header.replace("kind,ion", "ion,kind") + "\n",
                        header + "\nsource,2\n",
                        header + '\n"source,2\n'):
            events.write_text(content, encoding="utf-8")
            with self.assertRaises(ComponentFocusError):
                focus._events(events)

    def test_runner_binds_small_manifest_identities_without_payload_inventory(self) -> None:
        import hashlib
        import shutil
        import subprocess
        import sys

        if not shutil.which("pwsh"):
            self.skipTest("PowerShell 7 required")
        repo = ROOT.parents[1]
        family, generation = self.root / "parent", self.root / "generation"
        family.mkdir()
        generation.mkdir()
        parent_manifest, cache_manifest = family / "run_manifest.json", generation / "cache_manifest.json"
        parent_manifest.write_text('{"fixture":"small parent identity"}', encoding="utf-8")
        cache_manifest.write_text('{"fixture":"small cache identity"}', encoding="utf-8")
        controller = self.root / "private controller.pa0"
        controller.write_bytes(b"INERT_PRIVATE_PAYLOAD")
        events = self.write_events().replace(self.root / "events with spaces.csv")
        harness = self.root / "summary_and_analysis.ps1"
        harness.write_text(r"""param($Repo,$Root,$Python,$Events,$Receipt,$Campaign)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$source=Join-Path $Repo 'projects/orthogonal_accelerator/simion/run_component_focus_flight.ps1'
$ast=[Management.Automation.Language.Parser]::ParseFile($source,[ref]$null,[ref]$null)
$tables=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.HashtableAst]-and
 @($n.KeyValuePairs|Where-Object{$_.Item1-is[Management.Automation.Language.StringConstantExpressionAst]-and$_.Item1.Value-eq'pa_build_run_manifest_sha256'}).Count},$true))
if($tables.Count-ne1){throw 'Expected one component summary identity boundary'}
$pipeline=$tables[0];while($pipeline-isnot[Management.Automation.Language.PipelineAst]){$pipeline=$pipeline.Parent}
$analysisCalls=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.CommandAst]-and$n.GetCommandName()-eq'Invoke-FocusFrozenPython'-and
 @($n.CommandElements|Where-Object{$_-is[Management.Automation.Language.StringConstantExpressionAst]-and$_.Value-eq'projects.orthogonal_accelerator.analysis.component_focus_analysis'}).Count},$true))
if($analysisCalls.Count-ne1){throw 'Expected one actual frozen analysis call'}
$family=Join-Path $Root 'parent';$generation=Join-Path $Root 'generation';$controller=Join-Path $Root 'private controller.pa0'
$summary=Join-Path $Root 'summary.json';$analysis=Join-Path $Root 'analysis.json'
$releaseReceipt=$Receipt;$runCampaign=$Campaign
$focusPython=@{code_root=(Join-Path $Root 'frozen code');origins_path=(Join-Path $Root 'origins.json')}
$analysisResult=@{status='candidate_incomplete'};$result=@{cache_key='fixture-key';generation_sha256='fixture-generation'}
$script:hashes=[Collections.Generic.List[string]]::new()
function Get-FileHash {param($Path,$Algorithm)
 if($Path-notin@((Join-Path $family 'run_manifest.json'),(Join-Path $generation 'cache_manifest.json'))){throw 'Unexpected payload hash'}
 $script:hashes.Add($Path)
 Microsoft.PowerShell.Utility\Get-FileHash -LiteralPath $Path -Algorithm $Algorithm
}
function Get-ChildItem {throw 'Unexpected payload inventory'}
function Invoke-FocusFrozenPython {param($Python,$CodeRoot,$OriginsPath,$Module,[string[]]$Arguments)
 $script:observed=@{module=$Module;arguments=$Arguments;code_root=$CodeRoot;origins=$OriginsPath;python=$Python}
}
# Metadata length remains available, but any direct controller read must fail.
$guard=[IO.File]::Open($controller,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::None)
try {Invoke-Expression $pipeline.Extent.Text;Invoke-Expression $analysisCalls[0].Extent.Text}
finally {$guard.Dispose()}
@{hashes=@($script:hashes);analysis=$script:observed}|ConvertTo-Json -Depth 20 -Compress
""", encoding="utf-8")
        result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(harness), str(repo),
            str(self.root), sys.executable, str(events), str(self.receipt), str(self.campaign)],
            cwd=self.root, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        observed = json.loads(result.stdout)
        self.assertCountEqual(observed["hashes"], [str(parent_manifest), str(cache_manifest)])
        summary = json.loads((self.root / "summary.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(summary["pa_build_run_manifest_sha256"], hashlib.sha256(parent_manifest.read_bytes()).hexdigest().upper())
        self.assertEqual(summary["cache_manifest_sha256"], hashlib.sha256(cache_manifest.read_bytes()).hexdigest().upper())
        self.assertEqual(summary["runtime_controller_bytes"], controller.stat().st_size)
        self.assertEqual(summary["status"], "candidate_incomplete")
        arguments = observed["analysis"]["arguments"]
        self.assertEqual(arguments, ["--events", str(events), "--release-receipt", str(self.receipt),
                                    "--campaign", str(self.campaign), "--output", str(self.root / "analysis.json")])
        self.assertEqual(observed["analysis"]["code_root"], str(self.root / "frozen code"))
        self.assertEqual(observed["analysis"]["python"], sys.executable)
        actual = subprocess.run([sys.executable, "-m", observed["analysis"]["module"], *arguments],
            cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(actual.returncode, 0, actual.stdout + actual.stderr)
        self.assertEqual(json.loads((self.root / "analysis.json").read_text())["focus_particle_count"], 3)

    def test_iob_builder_has_single_value_argument_helper_and_lua_regression(self) -> None:
        builder = (ROOT / "simion" / "build_component_focus_iob.lua").read_text(encoding="utf-8")
        regression = ROOT / "tests" / "simion" / "test_component_focus_iob_arguments.lua"
        self.assertIn("local function a(i,label)local v=assert(arg[i+o],label);return v end", builder)
        self.assertTrue(regression.is_file())
        self.assertIn("local ok,message=pcall(builder)", regression.read_text(encoding="utf-8"))



if __name__ == "__main__":
    unittest.main()
