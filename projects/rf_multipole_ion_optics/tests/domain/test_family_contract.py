from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from projects.rf_multipole_ion_optics.core.family_contract import (
    VoltageDrive,
    electrode_group_voltages,
    from_high_order_baseline,
    from_high_order_resolved_design,
    l1_l2_transport_contract_from_resolved_design,
    from_quadrupole_contract,
    load_family_contract,
)
from projects.rf_multipole_ion_optics.runtime.design_profile import resolve_design_profile
from projects.rf_multipole_ion_optics.core.mass_response import aggregate_response, evaluate_functional_contrast, load_terminal_statuses
from projects.rf_multipole_ion_optics.core.ideal_transport import source_particles
from projects.rf_multipole_ion_optics.core.paired_mass_scan import build_paired_ion_rows


REPO_ROOT = Path(__file__).parents[4]
SUPPORT_PATH = (
    REPO_ROOT / "projects/rf_multipole_ion_optics/runtime/project_transport_launcher_support.ps1"
)
SIMION_RUNNER = REPO_ROOT / "projects/rf_multipole_ion_optics/runtime/run_simion_finite_3d_transport.ps1"
SIMION_PROGRAM = REPO_ROOT / "projects/rf_multipole_ion_optics/simion/simion_transport.lua"
PROJECTS = tuple(
    ("rf_multipole_ion_optics", "workflows/no_collision_transport", f"{variant}_{profile}")
    for variant, profile in (
        ("quadrupole", "no_acceleration_full_length"),
        ("hexapole", "segmented_rod_axial_acceleration"),
        ("octupole", "no_acceleration_full_length"),
    )
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class MultipoleFamilyContractTests(unittest.TestCase):
    def test_machine_contract_text_bytes_are_cross_platform_stable(self) -> None:
        attributes = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
        lines = attributes.splitlines()
        for extension in (
            "json",
            "csv",
            "py",
            "ps1",
            "m",
            "lua",
            "gem",
            "toml",
            "yaml",
            "yml",
            "txt",
            "md",
        ):
            with self.subTest(extension=extension):
                self.assertIn(f"*.{extension} text eol=lf", lines)


    def test_all_three_variants_close_over_one_frozen_rf_drive_kernel(self) -> None:
        support = SUPPORT_PATH.read_text(encoding="utf-8-sig")
        runner = SIMION_RUNNER.read_text(encoding="utf-8-sig")
        program = SIMION_PROGRAM.read_text(encoding="utf-8")

        self.assertEqual(
            support.count("projects\\rf_multipole_ion_optics\\runtime\\run_simion_finite_3d_transport.ps1"),
            1,
        )
        self.assertIn("common\\simion\\rf_drive.lua", runner)
        self.assertIn("Copy-VerifiedRunInput", runner)
        self.assertIn("multipole_rf_drive_kernel.lua", runner)
        self.assertIn("simion_rf_drive_kernel=$rfDriveKernelLua", runner)
        self.assertIn(
            "$env:MULTIPOLE_SIMION_RF_DRIVE_KERNEL_LUA=$rfDriveKernelLua",
            runner,
        )
        self.assertIn(
            "os.getenv('MULTIPOLE_SIMION_RF_DRIVE_KERNEL_LUA')",
            program,
        )
        self.assertNotIn("common/simion/rf_drive.lua", program)

        for project_id, entry_directory, _ in PROJECTS:
            entry_root = REPO_ROOT / "projects" / project_id / entry_directory
            launcher_name = "run_simion.ps1"
            launcher = (entry_root / launcher_name).read_text(encoding="utf-8-sig")
            self.assertIn("project_transport_launcher_support.ps1", launcher)
            self.assertNotIn("simion_rf_drive.lua", launcher)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")

    def test_high_order_n100_source_is_n1000_prefix(self) -> None:
        resolved = resolve_design_profile(
            REPO_ROOT, "rf_multipole_ion_optics", "hexapole_no_acceleration_full_length"
        )["resolved_design"]
        projection = l1_l2_transport_contract_from_resolved_design(resolved)
        statistical = copy.deepcopy(projection)
        statistical["particle_source"]["count"] = 1000
        self.assertEqual(source_particles(projection), source_particles(statistical)[:100])
        self.assertEqual(
            from_high_order_baseline(projection),
            from_high_order_resolved_design(resolved),
        )

    def test_obsolete_family_schema_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "family.json"
            path.write_text('{"schema_version": 1, "role": "rf_multipole_family_contract"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "schema or role differs"):
                load_family_contract(path)

    def test_three_structural_variants_share_one_project_and_family_identity(self) -> None:
        hexapole = from_high_order_resolved_design(
            resolve_design_profile(
                REPO_ROOT, "rf_multipole_ion_optics", "hexapole_no_acceleration_full_length"
            )["resolved_design"]
        )
        octupole = from_high_order_resolved_design(
            resolve_design_profile(
                REPO_ROOT, "rf_multipole_ion_optics", "octupole_no_acceleration_full_length"
            )["resolved_design"]
        )
        quad_root = REPO_ROOT / "projects/rf_multipole_ion_optics/variants/quadrupole/config"
        quadrupole = from_quadrupole_contract(
            load_json(quad_root / "baseline.json"),
            load_json(REPO_ROOT / "projects/rf_multipole_ion_optics/config/modes/quadrupole_mass_filter_reference.json"),
        )
        self.assertEqual(
            {hexapole.identity.family_id, octupole.identity.family_id, quadrupole.identity.family_id},
            {"rf_multipole_ion_optics"},
        )
        self.assertEqual(
            [quadrupole.identity.radial_order_n, hexapole.identity.radial_order_n, octupole.identity.radial_order_n],
            [2, 3, 4],
        )
        self.assertEqual({hexapole.geometry.r0_mm, octupole.geometry.r0_mm, quadrupole.geometry.r0_mm}, {4.0})

    def test_rf_dc_group_voltage_semantics_are_shared(self) -> None:
        root = REPO_ROOT / "projects/rf_multipole_ion_optics/variants/quadrupole/config"
        operating = from_quadrupole_contract(
            load_json(root / "baseline.json"), load_json(REPO_ROOT / "projects/rf_multipole_ion_optics/config/modes/quadrupole_mass_filter_reference.json")
        )
        positive, negative = electrode_group_voltages(operating.voltage, 0.0)
        self.assertAlmostEqual(positive, 14.763014939677756)
        self.assertAlmostEqual(negative, -30.763014939677756)
        self.assertAlmostEqual(positive - negative, 45.52602987935551)

    def test_interface_mode_requires_and_records_explicit_rf_binding(self) -> None:
        root = REPO_ROOT / "projects/rf_multipole_ion_optics/variants/quadrupole/config"
        baseline = load_json(root / "baseline.json")
        mode = load_json(REPO_ROOT / "projects/rf_multipole_ion_optics/config/modes/quadrupole_transport_interface_readiness.json")
        with self.assertRaisesRegex(ValueError, "explicit per-run RF amplitude"):
            from_quadrupole_contract(baseline, mode)
        operating = from_quadrupole_contract(baseline, mode, rf_amplitude_v_per_group=140.0)
        self.assertEqual(operating.voltage.rf_amplitude_v_per_group, 140.0)
        self.assertEqual(operating.voltage.frequency_hz, 1.1e6)
        self.assertEqual(operating.voltage.dc_amplitude_v_per_group, 0.0)

    def test_explicit_run_binding_overrides_embedded_rf_values(self) -> None:
        root = REPO_ROOT / "projects/rf_multipole_ion_optics/variants/quadrupole/config"
        operating = from_quadrupole_contract(
            load_json(root / "baseline.json"),
            load_json(REPO_ROOT / "projects/rf_multipole_ion_optics/config/modes/quadrupole_transport_no_collision.json"),
            rf_amplitude_v_per_group=141.0,
            frequency_hz=1.2e6,
        )
        self.assertEqual(operating.voltage.rf_amplitude_v_per_group, 141.0)
        self.assertEqual(operating.voltage.frequency_hz, 1.2e6)

    def test_waveform_phase_dc_and_common_mode_are_all_executed(self) -> None:
        drive = VoltageDrive("cosine", 10.0, 2.0, -3.0, 1.0, 0.0)
        self.assertEqual(electrode_group_voltages(drive, 0.0), (9.0, -15.0))
        solver = (REPO_ROOT / "projects/rf_multipole_ion_optics/comsol/solve_finite_3d_transport.m").read_text(
            encoding="utf-8"
        )
        for token in ("V_dc", "V_axis", "phi_rf", "rf.waveform", "Vdiff", "Vstatic"):
            self.assertIn(token, solver)







class MultipoleMassResponseTests(unittest.TestCase):
    def test_paired_rows_change_only_mass(self) -> None:
        source = [["0", "100", "1", "0", "0.1", "0.2", "0", "0", "2", "1", "3"]]
        rows = build_paired_ion_rows(source, [90.0, 100.0, 110.0])
        self.assertEqual([float(row[1]) for row in rows], [90.0, 100.0, 110.0])
        self.assertEqual(rows[0][2:], rows[1][2:])

    def test_generic_functional_contrast(self) -> None:
        response = aggregate_response(
            {1: 90.0, 2: 100.0, 3: 110.0},
            {1: "lost", 2: "transmitted", 3: "lost"},
        )
        metrics = evaluate_functional_contrast(response, 100.0, {
            "minimum_center_transmission": 0.8,
            "maximum_endpoint_transmission": 0.2,
            "minimum_center_to_endpoint_contrast": 0.6,
        })
        self.assertEqual(metrics["status"], "PASS")

    def test_unknown_terminal_status_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "particle_state.csv"
            fixture.write_text("particle_id,event,status\n1,terminal,unknown\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown terminal status"):
                load_terminal_statuses(fixture)


if __name__ == "__main__":
    unittest.main()
