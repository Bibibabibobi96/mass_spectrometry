from __future__ import annotations

import unittest
from pathlib import Path

from common.multipole.design_profile import resolve_design_profile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
FORBIDDEN_RUNNER_TERMS = {
    "Adapter",
    "DesignRequestPath",
    "ResolvedDesignPath",
    "ParticleMassAmu",
    "FieldScreenRunId",
    "EntranceConnectorLengthMm",
    "ExitConnectorLengthMm",
    "AxialAcceleration",
    "EndplateAcceleration",
}


class Phase4DesignConsumerTests(unittest.TestCase):
    def test_cross_solver_comparison_separates_physical_and_numerical_authority(self) -> None:
        interface_analyzer = (
            PROJECT_ROOT / "workflows" / "interface_readiness" / "evaluate.py"
        ).read_text(encoding="utf-8")
        component_analyzer = (
            PROJECT_ROOT / "workflows" / "no_collision_transport" / "evaluate.py"
        ).read_text(encoding="utf-8")
        interface_runner = (
            PROJECT_ROOT
            / "workflows"
            / "interface_readiness"
            / "compare_cross_solver.ps1"
        ).read_text(encoding="utf-8")
        component_runner = (
            PROJECT_ROOT
            / "workflows"
            / "no_collision_transport"
            / "compare_cross_solver.ps1"
        ).read_text(encoding="utf-8")
        self.assertNotIn("transport_no_collision", interface_analyzer)
        self.assertNotIn("transport_interface_readiness", component_analyzer)
        self.assertIn("interface_readiness.evaluate", interface_runner)
        self.assertIn("no_collision_transport.evaluate", component_runner)
        self.assertNotIn("[string]$Mode", interface_runner)
        self.assertNotIn("[string]$Mode", component_runner)
        lifecycle = (
            PROJECT_ROOT
            / "runtime"
            / "cross_solver_analysis_lifecycle.ps1"
        ).read_text(encoding="utf-8").lower()
        for forbidden in (
            "transport_interface_readiness",
            "transport_no_collision",
            "minimum_transmission",
            "threshold",
            "rf_quadrupole_no_collision_cross_solver_result",
            "rf_quadrupole_interface_readiness_cross_solver_result",
        ):
            self.assertNotIn(forbidden, lifecycle)
    def test_managed_plotters_bind_explicit_png_and_state_identity(self) -> None:
        managed = (
            PROJECT_ROOT
            / "workflows"
            / "mass_filter_reference"
            / "evaluate_comparison.py",
            REPO_ROOT
            / "integrations"
            / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
            / "analysis"
            / "analyze_analyzer_transport.py",
            PROJECT_ROOT / "analysis" / "compare_rf_input_energy.py",
            REPO_ROOT
            / "integrations"
            / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
            / "analysis"
            / "plot_shared_pulse_geometry_snapshot.py",
        )
        for path in managed:
            source = path.read_text(encoding="utf-8")
            self.assertIn('format="png"', source, path.name)
            self.assertIn("dpi=", source, path.name)
            self.assertIn("figsize=", source, path.name)
        for path in managed:
            if path.name in {
                "evaluate_comparison.py",
                "compare_rf_input_energy.py",
            }:
                continue
            source = path.read_text(encoding="utf-8")
            self.assertIn("frame_id", source, path.name)
            self.assertIn("clock_epoch_id", source, path.name)
        analyzer = managed[1].read_text(encoding="utf-8")
        self.assertIn('geometry["geometry_mm"]["detector_radius"]', analyzer)
        self.assertNotIn('geometry["geometry_mm"]["physical_detector_radius"]', analyzer)

    def test_named_profiles_resolve_from_canonical_project_identity(self) -> None:
        for profile_id in (
            "official_transport",
            "interface_readiness",
            "mass_filter_reference",
            "explicit_axial_reference",
            "exit_aperture_plate_acceleration_reference",
        ):
            resolved = resolve_design_profile(
                REPO_ROOT,
                "rf_quadrupole_ion_optics",
                profile_id,
            )
            self.assertEqual(
                resolved["profile"]["identity"]["electrode_count"], 4
            )

    def test_no_collision_entries_fix_one_scientific_profile(self) -> None:
        workflow = PROJECT_ROOT / "workflows" / "no_collision_transport"
        for name in ("run_comsol.ps1", "run_simion.ps1"):
            source = (workflow / name).read_text(encoding="utf-8")
            for forbidden in FORBIDDEN_RUNNER_TERMS:
                self.assertNotIn(forbidden, source)
            self.assertIn("[string]$RuntimeProfileId", source)
            self.assertNotIn("[string]$ParticleSourcePath", source)
            self.assertIn(
                "common\\multipole\\project_transport_launcher_support.ps1",
                source,
            )
            self.assertIn("Invoke-MultipoleProjectFinite3dTransport", source)
            self.assertNotIn("[string]$DesignProfileId", source)
            self.assertNotIn("explicit_axial_reference", source)
            self.assertNotIn("exit_aperture_plate_acceleration_reference", source)

    def test_legacy_contract_modules_no_longer_compute_device_geometry(self) -> None:
        for name in ("resolve_contract.py", "rfquad_contract.py"):
            source = (PROJECT_ROOT / "analysis" / name).read_text(encoding="utf-8")
            self.assertNotIn("build_round_rod_array", source)
            self.assertNotIn("build_axial_interface_layout", source)
            self.assertNotIn("diagnostic_planes", source)

    def test_runtime_consumers_do_not_read_legacy_resolved_schema(self) -> None:
        forbidden = (
            "config/resolved_geometry.json",
            "config/resolved_interface_readiness.json",
            "config/resolved_mass_filter.json",
            "rod_array_mm",
            "interface_layout_mm",
            "resolved.mode",
            "rf.mode.rf",
        )
        runtime_roots = (
            PROJECT_ROOT / "analysis",
            PROJECT_ROOT / "comsol",
            PROJECT_ROOT / "workflows",
            PROJECT_ROOT / "tests" / "comsol",
            PROJECT_ROOT / "tests" / "simion",
        )
        for root in runtime_roots:
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in {
                    ".m", ".py", ".ps1", ".lua"
                }:
                    continue
                source = path.read_text(encoding="utf-8-sig")
                for token in forbidden:
                    self.assertNotIn(token, source, str(path.relative_to(PROJECT_ROOT)))

    def test_solver_builders_read_governed_physical_fields_directly(self) -> None:
        matlab = (
            PROJECT_ROOT
            / "comsol"
            / "solve_deterministic_rf_quadrupole_particles.m"
        ).read_text(encoding="utf-8")
        simion = (
            PROJECT_ROOT / "workflows" / "interface_readiness" / "run_simion.ps1"
        ).read_text(encoding="utf-8")
        simion_core = (
            PROJECT_ROOT / "runtime" / "simion_run_config.ps1"
        ).read_text(encoding="utf-8")
        for source in (matlab,):
            self.assertIn("resolved.drive", source)
            self.assertIn("resolved.static_electrodes_V", source)
            self.assertIn("geometry_mm", source)
            self.assertNotIn("family_operating_contract", source)
        for token in ("'drive'", "'static_electrodes_V'", "'geometry_mm'"):
            self.assertIn(token, simion_core)
        self.assertIn("-ResolvedDesign $resolved", simion)
        self.assertNotIn("family_operating_contract", simion_core)
        self.assertIn("New-RfSimionCoreRunConfig", simion)
        self.assertNotIn("family_operating_contract", simion)


if __name__ == "__main__":
    unittest.main()
