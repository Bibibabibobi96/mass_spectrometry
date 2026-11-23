from __future__ import annotations

import unittest
from pathlib import Path

from msplatform.workflows.rf_design_profiles import resolve_design_profile


PROJECT_ROOT = Path(__file__).resolve().parents[4] / "src" / "msplatform" / "components" / "rf_multipole"
REPO_ROOT = PROJECT_ROOT.parents[3]
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
        evaluator = (
            REPO_ROOT / "src/msplatform/workflows/rf_transport_comparison.py"
        ).read_text(encoding="utf-8")
        runner = (
            REPO_ROOT / "src/msplatform/workflows/resources/compare_cross_solver.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("transport_no_collision", evaluator)
        self.assertIn("transport_interface_readiness", evaluator)
        self.assertIn("ValidateSet('transport_no_collision','transport_interface_readiness')", runner)
        self.assertIn("mode contract", evaluator)
        lifecycle = (
            REPO_ROOT
            / "src/msplatform/workflows/resources/cross_solver_analysis_lifecycle.ps1"
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
            REPO_ROOT
            / "src/msplatform/workflows/rf_mass_filter/response_comparison.py",
            REPO_ROOT / "src/msplatform/analysis" / "compare_rf_input_energy.py",
        )
        for path in managed:
            source = path.read_text(encoding="utf-8")
            self.assertIn('format="png"', source, path.name)
            self.assertIn("dpi=", source, path.name)
            self.assertIn("figsize=", source, path.name)
        for path in managed:
            if path.name in {
                "response_comparison.py",
                "compare_rf_input_energy.py",
            }:
                continue
            source = path.read_text(encoding="utf-8")
            self.assertIn("frame_id", source, path.name)
            self.assertIn("clock_epoch_id", source, path.name)

    def test_named_profiles_resolve_from_canonical_project_identity(self) -> None:
        for profile_id in (
            "official_transport",
            "interface_readiness",
            "mass_filter_reference",
            "explicit_axial_reference",
        ):
            resolved = resolve_design_profile(
                REPO_ROOT,
                "rf_multipole_ion_optics",
                ('quadrupole_' + profile_id),
            )
            self.assertEqual(
                resolved["profile"]["identity"]["electrode_count"], 4
            )

    def test_legacy_contract_modules_no_longer_compute_device_geometry(self) -> None:
        for path in (
            REPO_ROOT / "src/msplatform/workflows/rf_publication.py",
            REPO_ROOT / "src/msplatform/components/rf_multipole/resolved_design_access.py",
        ):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("build_round_rod_array", source)
            self.assertNotIn("build_axial_interface_layout", source)
            self.assertNotIn("diagnostic_planes", source)

    def test_runtime_consumers_do_not_read_legacy_resolved_schema(self) -> None:
        forbidden = (
            "variants/quadrupole/config/resolved_geometry.json",
            "variants/quadrupole/config/resolved_interface_readiness.json",
            "variants/quadrupole/config/resolved_mass_filter.json",
            "rod_array_mm",
            "interface_layout_mm",
            "resolved.mode",
            "rf.mode.rf",
        )
        runtime_roots = (
            REPO_ROOT / "src/msplatform/analysis",
            REPO_ROOT / "src/msplatform/backends/comsol/matlab",
            REPO_ROOT / "src/msplatform/workflows",
            REPO_ROOT / "tests/components/rf_multipole_ion_optics",
        )
        for root in runtime_roots:
            for path in root.rglob("*"):
                if (not path.is_file() or "tests" in path.relative_to(REPO_ROOT).parts
                        or path.suffix.lower() not in {".m", ".py", ".ps1", ".lua"}):
                    continue
                source = path.read_text(encoding="utf-8-sig")
                for token in forbidden:
                    self.assertNotIn(token, source, str(path.relative_to(REPO_ROOT)))

    def test_solver_builders_read_governed_physical_fields_directly(self) -> None:
        matlab = (
            REPO_ROOT / "src/msplatform/backends/comsol/matlab/solve_deterministic_rf_quadrupole_particles.m"
        ).read_text(encoding="utf-8")
        simion = (
            REPO_ROOT / "src/msplatform/workflows/resources/run_simion.ps1"
        ).read_text(encoding="utf-8")
        simion_core = (
            REPO_ROOT / "src/msplatform/workflows/resources/simion_run_config.ps1"
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
