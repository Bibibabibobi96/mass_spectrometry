from __future__ import annotations

import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]


class MassFilterSimionContractTests(unittest.TestCase):
    def test_lua_applies_dc_and_rf_as_one_differential_voltage(self) -> None:
        wrapper = (PROJECT_ROOT / "simion" / "programs" / "quad_transport.lua").read_text(encoding="utf-8")
        self.assertIn("MULTIPOLE_SIMION_SHARED_PROGRAM_LUA", wrapper)
        lua = (REPO_ROOT / "common" / "multipole" / "simion_transport.lua").read_text(encoding="utf-8")
        self.assertIn("local differential = transport_dc_amplitude_v + rf", lua)
        self.assertIn("adj_elect01 = transport_axis_voltage_v + differential", lua)
        self.assertIn("adj_elect02 = transport_axis_voltage_v - differential", lua)

    def test_mass_filter_has_a_dedicated_fixed_purpose_runner(self) -> None:
        runner_path = PROJECT_ROOT / "tests" / "simion" / "run_mass_filter_candidate.ps1"
        runner = runner_path.read_text(encoding="utf-8")
        parameter_block = runner[: runner.index("Set-StrictMode")]

        self.assertIn("[Parameter(Mandatory = $true)]", parameter_block)
        self.assertIn("[string]$SourceIonPath", parameter_block)
        for forbidden_parameter in (
            "$Mode",
            "$ParticleTablePath",
            "$ParticleBundleMetadataPath",
            "$OperatingPoint",
            "$SourceAxialOffsetMm",
        ):
            self.assertNotIn(forbidden_parameter, parameter_block)
        self.assertIn("$modeName = 'mass_filter_reference'", runner)
        self.assertIn("role = 'rf_quadrupole_simion_mass_filter_run_config'", runner)
        self.assertIn("resolved_design_mass_filter.json", runner)

    def test_mass_runner_uses_one_paired_ion11_analysis_pipeline(self) -> None:
        runner = (
            PROJECT_ROOT / "tests" / "simion" / "run_mass_filter_candidate.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("analysis.generate_mass_scan_particle_table", runner)
        self.assertIn("analysis.render_ion11_simion_source", runner)
        self.assertIn("analysis.analyze_simion_mass_scan", runner)
        self.assertIn("--source-format ion11", runner)
        self.assertIn("$numericalMode.numerics.simion_rf_steps_per_period", runner)
        self.assertIn("$resolved.static_electrodes_V", runner)
        self.assertNotIn("$resolved.mode", runner)
        self.assertEqual(
            runner.count("$massResponseCsv = Join-Path $resultDir 'mass-response__simion.csv'"),
            1,
        )
        self.assertIn("mass_response = 'results/mass-response__simion.csv'", runner)

    def test_physical_failure_is_not_an_execution_failure(self) -> None:
        runner = (
            PROJECT_ROOT / "tests" / "simion" / "run_mass_filter_candidate.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("$physicalDecision = [string]$massMetrics.status", runner)
        self.assertIn("status = 'success'", runner)
        self.assertIn("physical_decision = $physicalDecision", runner)
        self.assertIn("Write-VerifiedRunManifest", runner)
        self.assertIn("Complete-FailedRun", runner)
        self.assertIn("analyzer exit/status mismatch", runner)

    def test_mass_filter_voltage_contract_is_unambiguous(self) -> None:
        mode = json.loads(
            (PROJECT_ROOT / "config" / "modes" / "mass_filter_reference.json").read_text(encoding="utf-8")
        )
        self.assertAlmostEqual(mode["rf"]["dc_amplitude_V_per_group"], 22.763014939677756)
        self.assertAlmostEqual(mode["rf"]["axis_common_mode_offset_V"], -8.0)
        self.assertEqual(mode["solver_screen"]["particles_per_mass"], 100)


if __name__ == "__main__":
    unittest.main()
