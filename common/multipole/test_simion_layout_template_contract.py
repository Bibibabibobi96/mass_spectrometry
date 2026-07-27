from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
GEM = ROOT / "multipole_layout_placeholder.gem"
BUILDER = ROOT / "build_simion_layout_placeholder.ps1"
REGISTER = ROOT / "register_simion_layout_template.ps1"
INSPECTOR = ROOT / "inspect_simion_layout_template.lua"
RUNNER = ROOT / "run_simion_finite_3d_transport.ps1"
RUNTIME_BUILDER = ROOT / "build_simion_runtime_iob.lua"


class SimionLayoutTemplateContractTests(unittest.TestCase):
    def test_placeholder_is_small_and_nonphysical(self) -> None:
        source = GEM.read_text(encoding="ascii")
        self.assertIn("pa_define(5,5,5,planar,none,electrostatic,,1,1,1)", source)
        self.assertEqual(len(re.findall(r"(?m)^e\(\d+\)", source)), 1)
        for forbidden in ("139.81792", "1.1e6", "quadrupole geometry"):
            self.assertNotIn(forbidden, source.lower())

    def test_builder_only_prepares_gui_source(self) -> None:
        source = BUILDER.read_text(encoding="utf-8-sig")
        for token in (
            "multipole_layout_placeholder.gem",
            "quad_monolithic.pa0",
            "placeholder_manifest.json",
            "physical_model = $false",
            "--nogui --noprompt gem2pa",
        ):
            self.assertIn(token, source)
        for forbidden in ("quad_monolithic.iob", "refine", " fly "):
            self.assertNotIn(forbidden, source.lower())

    def test_registration_is_one_fail_closed_boundary(self) -> None:
        source = REGISTER.read_text(encoding="utf-8-sig")
        for token in (
            "ConfirmGuiCreatedAndReopened",
            "provider project scratch directory",
            "multipole_simion_layout_template_build",
            "write_run_manifest.py",
            "verify_run_manifest.py",
            "INSTANCE_COUNT=1",
            "PARTICLE_FLY_EXECUTED=false",
        ):
            self.assertIn(token, source)
        self.assertEqual(source.count("Start-Process -FilePath $SimionExe"), 1)
        for forbidden in ("--programs", " refine ", " fly "):
            self.assertNotIn(forbidden, source.lower())

    def test_inspector_checks_instance_transform_axes_and_local_pa(self) -> None:
        source = INSPECTOR.read_text(encoding="utf-8")
        for token in (
            "#simion.wb.instances == 1",
            "local expected_transform = {0, 0, 0, -90, 0, 180, 1}",
            "loaded PA path does not point to the run-local template bundle",
            "PA_X_IN_WB",
            "PA_Y_IN_WB",
            "PA_Z_IN_WB",
            "STATUS=PASS",
        ):
            self.assertIn(token, source)

    def test_runtime_builder_reuses_oa_save_and_restore_pattern(self) -> None:
        source = RUNTIME_BUILDER.read_text(encoding="utf-8")
        for token in (
            "instance.pa:load(pa_path)",
            "instance:_debug_update_size()",
            "wb:save(iob_path)",
            "write_file(program_output, program",
            "write_file(fly2_output, fly2",
        ):
            self.assertIn(token, source)

    def test_production_runner_has_one_bound_template_and_no_vendor_escape(self) -> None:
        runners = (
            RUNNER,
            ROOT.parents[1]
            / "projects/rf_quadrupole_collision_cooling/workflows"
            / "interface_readiness/run_simion.ps1",
            ROOT.parents[1]
            / "projects/rf_quadrupole_collision_cooling/workflows"
            / "mass_filter_reference/run_simion.ps1",
        )
        for runner in runners:
            with self.subTest(runner=runner):
                source = runner.read_text(encoding="utf-8-sig")
                self.assertIn("common.multipole.simion_layout_template", source)
                self.assertIn("registration_run_manifest.json", source)
                self.assertIn("quad_monolithic.con", source)
                self.assertNotIn("TemplateIob", source)
                self.assertNotIn("examples\\quad", source)


if __name__ == "__main__":
    unittest.main()
