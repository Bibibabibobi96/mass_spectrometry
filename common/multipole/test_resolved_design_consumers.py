from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from common.multipole.analyze_round_rod_screen import analyze
from common.multipole.compile_design_request import (
    compile_governed_design_request_file,
)
from common.multipole.design_profile import resolve_design_profile
from common.multipole.simion_geometry import render_gem


ROOT = Path(__file__).parents[2]
MULTIPOLE = ROOT / "common" / "multipole"


class ResolvedDesignConsumerContractTest(unittest.TestCase):
    def test_family_gate_uses_quadrupole_official_publication_only(self) -> None:
        source = (MULTIPOLE / "verify_family_foundation.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("resolved_design_official.json", source)
        for legacy in (
            "resolved_geometry.json",
            "resolved_interface_readiness.json",
            "resolved_mass_filter.json",
        ):
            self.assertNotIn(legacy, source)

    def test_both_l3_runners_have_one_governed_physical_authority(self) -> None:
        forbidden = (
            "ProjectRoot",
            "ResolvedDesignPath",
            "ParticleMassAmu",
            "Adapter",
            "FieldScreenRunId",
            "AxialAccelerationContractPath",
            "EntranceConnectorLengthMm",
            "ExitConnectorLengthMm",
            "EndplateAcceleration",
            "MinimumRfTransmission",
            "MinimumImprovementOverZeroRf",
        )
        for name in (
            "run_finite_3d_transport.ps1",
            "run_simion_finite_3d_transport.ps1",
        ):
            source = (MULTIPOLE / name).read_text(encoding="utf-8")
            self.assertIn("ProjectId", source)
            self.assertIn("DesignProfileId", source)
            self.assertIn("common.multipole.compile_design_request", source)
            self.assertIn("parent_resolved_design_sha256", source)
            self.assertIn("code_inventory.json", source)
            self.assertNotIn("common\\__init__.py", source)
            for token in forbidden:
                self.assertNotIn(token, source)

    def test_simion_projection_preserves_resolved_parent_geometry_and_interfaces(self) -> None:
        profile = resolve_design_profile(
            ROOT, "rf_hexapole_ion_guide", "baseline_finite_3d"
        )
        resolved = compile_governed_design_request_file(
            profile["paths"]["design_request"],
            profile["paths"]["design_variables"],
            profile["paths"]["optimization_envelope"],
            expected_identity=profile["profile"]["identity"],
            provenance_root=ROOT,
        )
        gem = render_gem(resolved, 0.2)
        self.assertIn(f"parent_resolved_sha256={resolved['resolved_sha256']}", gem)
        for rod in resolved["segmentation"]["segmented_rod_array"]["electrodes"]:
            self.assertIn(
                f"cylinder({rod['center_x_mm']:.12g},{rod['center_y_mm']:.12g},",
                gem,
            )
        self.assertIn(
            f",{resolved['interfaces_mm']['entrance']['aperture_radius_mm']:.12g},,",
            gem,
        )

    def test_comsol_and_simion_consume_all_canonical_drive_fields(self) -> None:
        comsol = (MULTIPOLE / "solve_finite_3d_transport.m").read_text(encoding="utf-8")
        simion = (MULTIPOLE / "run_simion_finite_3d_transport.ps1").read_text(
            encoding="utf-8"
        )
        for field in (
            "waveform",
            "rf_amplitude_V_zero_to_peak_per_group",
            "dc_amplitude_V_per_group",
            "common_mode_offset_V",
            "frequency_Hz",
            "phase_rad",
        ):
            self.assertIn(field, comsol)
            self.assertIn(field, simion)
        lua = (MULTIPOLE / "simion_transport.lua").read_text(encoding="utf-8")
        self.assertIn("math.sin(angle)", lua)
        self.assertIn("math.cos(angle)", lua)
        self.assertIn("ion_time_of_flight * omega + phase", lua)

    def test_static_boundary_voltages_are_canonical_and_solver_shared(self) -> None:
        resolved = (
            ROOT
            / "projects/rf_quadrupole_collision_cooling/config/resolved_design_mass_filter.json"
        )
        document = json.loads(resolved.read_text(encoding="utf-8"))
        self.assertEqual(
            document["static_electrodes_V"],
            {
                "role": "rectangular_reference_static_electrodes",
                "entrance_plate_and_connector": 0.0,
                "exit_enclosure_and_connector": -100.0,
                "detector": -1500.0,
            },
        )
        comsol = (MULTIPOLE / "solve_finite_3d_transport.m").read_text(encoding="utf-8")
        simion = (MULTIPOLE / "run_simion_finite_3d_transport.ps1").read_text(
            encoding="utf-8"
        )
        for field in (
            "entrance_plate_and_connector",
            "exit_enclosure_and_connector",
            "detector",
        ):
            self.assertIn(field, comsol)
            self.assertIn(field, simion)

    def test_l2_reports_scores_but_cannot_select_geometry(self) -> None:
        radial_order = 2
        rows = []
        for ratio in (0.9, 1.1):
            for index in range(64):
                theta = 2 * math.pi * index / 64
                rows.append(
                    {
                        "rod_radius_ratio": str(ratio),
                        "sample_radius_mm": "2",
                        "theta_rad": str(theta),
                        "potential_V": str(math.cos(radial_order * theta)),
                    }
                )
        contract = {
            "project_id": "fixture",
            "multipole": {"radial_order_n": radial_order},
            "geometry_mm": {"inscribed_radius_r0": 4},
            "selection": {
                "minimum_adjacent_surface_gap_mm": 0,
                "minimum_main_boundary_amplitude_fraction_of_drive": 0,
                "maximum_cross_radius_absolute_harmonic_spread": 1,
            },
            "field_solve": {"rod_voltage_zero_to_peak_V": 1},
            "claim_limit": "metrics only",
        }
        result = analyze(rows, contract)
        self.assertEqual(result["status"], "METRICS_ONLY")
        self.assertEqual(len(result["candidates"]), 2)
        self.assertNotIn("selected_candidate", result)
        for candidate in result["candidates"]:
            self.assertNotIn("rod_radius_mm", candidate)
            self.assertIn("parasitic_harmonic_score", candidate)

    def test_l2_runner_compiles_one_governed_profile_and_never_selects_geometry(self) -> None:
        runner = (MULTIPOLE / "run_round_rod_field_screen.ps1").read_text(
            encoding="utf-8"
        )
        solver = (MULTIPOLE / "solve_round_rod_field_screen.m").read_text(
            encoding="utf-8"
        )
        for token in (
            "ProjectId",
            "DesignProfileId",
            "common.multipole.design_profile",
            "common.multipole.compile_design_request",
            "multipole_resolved_design",
            "parent_resolved_design_sha256",
        ):
            self.assertIn(token, runner)
        for legacy in (
            "ProjectRoot",
            "resolve_family_operating_contract",
            "family_operating_contract",
            "selected_candidate",
            "MULTIPOLE_BASELINE",
            "MULTIPOLE_FAMILY_OPERATING",
        ):
            self.assertNotIn(legacy, runner)
            self.assertNotIn(legacy, solver)
        self.assertIn("MULTIPOLE_RESOLVED_DESIGN", solver)
        self.assertIn("multipole_resolved_design_do_not_edit", solver)

    def test_run_config_manifest_parent_hash_is_explicit(self) -> None:
        for name in (
            "run_finite_3d_transport.ps1",
            "run_simion_finite_3d_transport.ps1",
        ):
            source = (MULTIPOLE / name).read_text(encoding="utf-8")
            self.assertIn("[string]$PythonExe", source)
            self.assertIn("New-RunPackage -Python $python", source)
            self.assertIn("provenance=[ordered]@{parent_resolved_design_sha256=$resolvedHash", source)
            self.assertIn("Write-VerifiedRunManifest", source)
            self.assertEqual(source.count("Complete-FailedRun"), 1)
        comsol = (MULTIPOLE / "run_finite_3d_transport.ps1").read_text(
            encoding="utf-8"
        )
        for output in (
            "$primaryState",
            "$controlState",
            "$primaryTrajectories",
            "$controlTrajectories",
            "$pairedMetrics",
        ):
            self.assertIn(output, comsol)
        self.assertIn("common.multipole.analyze_simion_axial_acceleration", comsol)
        self.assertIn("--metrics $evidenceMetrics", comsol)
        matlab = (MULTIPOLE / "solve_finite_3d_transport.m").read_text(
            encoding="utf-8"
        )
        for evidence_field in (
            "'accelerated_transmission'",
            "'mean_energy_gain_eV'",
            "'absolute_mean_output_energy_error_eV'",
        ):
            self.assertNotIn(evidence_field, matlab)


if __name__ == "__main__":
    unittest.main()
