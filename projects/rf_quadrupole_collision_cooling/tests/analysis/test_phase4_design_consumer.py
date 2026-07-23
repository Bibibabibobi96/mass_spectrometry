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
        analyzer = (
            PROJECT_ROOT / "analysis" / "compare_particle_state.py"
        ).read_text(encoding="utf-8")
        runner = (
            PROJECT_ROOT / "tests" / "cross_solver" / "verify_transport_candidate.ps1"
        ).read_text(encoding="utf-8")
        self.assertNotIn('resolved["mode"]', analyzer)
        self.assertIn("--regression-mode", analyzer)
        self.assertIn("regression_mode_sha256", analyzer)
        self.assertIn("transport_no_collision.json", runner)
        retired = (
            PROJECT_ROOT / "analysis" / "verify_cross_solver_transport.py"
        ).read_text(encoding="utf-8")
        self.assertIn("HISTORY_ONLY", retired)
        self.assertNotIn("cross_solver_transmission_absolute_tolerance", retired)

    def test_managed_plotters_bind_explicit_png_and_state_identity(self) -> None:
        managed = (
            "analyze_comsol_mass_scan.py",
            "analyze_s3_end_to_end.py",
            "compare_rf_input_energy.py",
            "plot_shared_pulse_geometry_snapshot.py",
        )
        for name in managed:
            source = (PROJECT_ROOT / "analysis" / name).read_text(encoding="utf-8")
            self.assertIn('format="png"', source, name)
            self.assertIn("dpi=", source, name)
            self.assertIn("figsize=", source, name)
        for name in managed:
            if name in {"analyze_comsol_mass_scan.py", "compare_rf_input_energy.py"}:
                continue
            source = (PROJECT_ROOT / "analysis" / name).read_text(encoding="utf-8")
            self.assertIn("frame_id", source, name)
            self.assertIn("clock_epoch_id", source, name)

    def test_named_profiles_resolve_from_canonical_project_identity(self) -> None:
        for profile_id in (
            "official_transport",
            "interface_readiness",
            "mass_filter_reference",
            "explicit_axial_reference",
            "endplate_acceleration_reference",
        ):
            resolved = resolve_design_profile(
                REPO_ROOT,
                "rf_quadrupole_collision_cooling",
                profile_id,
            )
            self.assertEqual(
                resolved["profile"]["identity"]["electrode_count"], 4
            )

    def test_wrappers_forward_no_physical_scalar_or_arbitrary_request_path(self) -> None:
        for name in (
            "run_finite_3d_transport.ps1",
            "run_simion_finite_3d_transport.ps1",
        ):
            source = (PROJECT_ROOT / "analysis" / name).read_text(encoding="utf-8")
            for forbidden in FORBIDDEN_RUNNER_TERMS:
                self.assertNotIn(forbidden, source)
            self.assertIn("DesignProfileId", source)
            self.assertIn("ParticleSourcePath", source)
            self.assertIn("explicit_axial_reference", source)
            self.assertIn("endplate_acceleration_reference", source)

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
        matlab = (PROJECT_ROOT / "comsol" / "ms_rf_quadrupole_no_collision.m").read_text(
            encoding="utf-8"
        )
        simion = (
            PROJECT_ROOT / "tests" / "simion" / "run_transport_candidate.ps1"
        ).read_text(encoding="utf-8")
        for source in (matlab, simion):
            self.assertIn("resolved.drive", source)
            self.assertIn("resolved.static_electrodes_V", source)
            self.assertIn("geometry_mm", source)
            self.assertNotIn("family_operating_contract", source)


if __name__ == "__main__":
    unittest.main()
