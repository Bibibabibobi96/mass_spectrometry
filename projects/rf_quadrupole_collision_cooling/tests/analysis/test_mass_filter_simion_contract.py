from __future__ import annotations

import json
import math
import re
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
        self.assertIn("$numericalContract.baseline_rf_steps_per_period", runner)
        self.assertIn("New-RfSimionCoreRunConfig", runner)
        self.assertIn("ConvertTo-RfSimionLuaConfig", runner)
        self.assertIn("Invoke-RfSimionCoreRun", runner)
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

    def test_shared_geometry_drive_and_solver_numerics_have_one_authority(self) -> None:
        config = PROJECT_ROOT / "config"
        mode = json.loads(
            (config / "modes" / "mass_filter_reference.json").read_text(
                encoding="utf-8"
            )
        )
        mass = json.loads(
            (config / "resolved_design_mass_filter.json").read_text(encoding="utf-8")
        )
        official = json.loads(
            (config / "resolved_design_official.json").read_text(encoding="utf-8")
        )
        interface = json.loads(
            (config / "interface_contract.json").read_text(encoding="utf-8")
        )
        baseline = json.loads((config / "baseline.json").read_text(encoding="utf-8"))
        numerics = json.loads(
            (config / "simion_solver_numerics.json").read_text(encoding="utf-8")
        )
        self.assertEqual(mass["geometry_mm"], official["geometry_mm"])
        self.assertEqual(mass["interfaces_mm"], official["interfaces_mm"])
        drive_pairs = (
            ("frequency_Hz", "frequency_Hz"),
            ("amplitude_V_zero_to_peak_per_group", "rf_amplitude_V_zero_to_peak_per_group"),
            ("dc_amplitude_V_per_group", "dc_amplitude_V_per_group"),
            ("axis_common_mode_offset_V", "common_mode_offset_V"),
        )
        for mode_key, resolved_key in drive_pairs:
            self.assertEqual(mode["rf"][mode_key], mass["drive"][resolved_key])
        self.assertAlmostEqual(
            math.radians(mode["rf"]["phase_deg"]), mass["drive"]["phase_rad"]
        )
        static_pairs = (
            ("entrance_plate", "entrance_plate_and_connector"),
            ("exit_enclosure", "exit_enclosure_and_connector"),
            ("detector", "detector"),
        )
        for mode_key, resolved_key in static_pairs:
            self.assertEqual(
                mode["static_electrodes_V"][mode_key],
                mass["static_electrodes_V"][resolved_key],
            )
        self.assertEqual(
            baseline["geometry_mm"]["simion_cell_mm"], numerics["simion_cell_mm"]
        )
        gem = (
            PROJECT_ROOT / "simion" / "geometry" / "quad_monolithic.gem"
        ).read_text(encoding="utf-8")
        mmgu = float(re.search(r"local mmgu = ([0-9.]+)", gem).group(1))
        self.assertEqual(mmgu, numerics["simion_cell_mm"])
        self.assertAlmostEqual(
            interface["planes"]["source"]["z_mm"],
            official["interfaces_mm"]["entrance"]["particle_plane_z_mm"],
        )
        self.assertEqual(
            interface["planes"]["rod_exit"]["z_mm"],
            official["geometry_mm"]["rod_z_max"],
        )
        self.assertEqual(
            interface["planes"]["handoff"]["z_mm"],
            official["geometry_mm"]["enclosure"]["exit_front_wall_end_z_mm"],
        )
        self.assertEqual(
            interface["planes"]["acceptance_detector"]["z_mm"],
            official["interfaces_mm"]["exit"]["particle_plane_z_mm"],
        )


if __name__ == "__main__":
    unittest.main()
