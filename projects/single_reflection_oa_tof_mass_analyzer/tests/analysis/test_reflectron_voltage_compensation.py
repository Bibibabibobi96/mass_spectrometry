from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from projects.single_reflection_oa_tof_mass_analyzer.analysis.optimize_reflectron_ring_voltages import (
    render_lua_profile,
)
from projects.single_reflection_oa_tof_mass_analyzer.workflows.reflectron_voltage_compensation.run_compensation import (
    _split_ions,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ReflectronVoltageCompensationTests(unittest.TestCase):
    def test_profile_renderer_freezes_counts_and_ring_voltages(self) -> None:
        profile = render_lua_profile(
            {
                "schema_version": 1,
                "stage1_count": 2,
                "stage2_count": 2,
                "stage1_ring_voltages_V": [100.0, 200.0],
                "stage2_ring_voltages_V": [300.0, 400.0],
            }
        )
        self.assertIn("stage1_count = 2", profile)
        self.assertIn("stage1_ring_voltages_V = {100, 200}", profile)
        self.assertIn("stage2_ring_voltages_V = {300, 400}", profile)

    def test_n1000_source_is_partitioned_without_loss_or_duplication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.ion"
            source.write_text("\n".join(f"ion-{index}" for index in range(1000)) + "\n")
            batches = _split_ions(source, root / "batches", 5)
            self.assertEqual([batch["count"] for batch in batches], [200] * 5)
            self.assertEqual([batch["offset"] for batch in batches], [0, 200, 400, 600, 800])
            combined = []
            for batch in batches:
                combined.extend(batch["ion"].read_text().splitlines())
            self.assertEqual(combined, source.read_text().splitlines())

    def test_simion_program_requires_process_local_enabled_profile(self) -> None:
        program = (
            PROJECT_ROOT / "simion" / "workbench" / "formal" / "oatof_ideal_grounded.lua"
        ).read_text(encoding="utf-8")
        self.assertIn("OATOF_REFLECTRON_VOLTAGE_COMPENSATION", program)
        self.assertIn("voltage compensation enabled but profile file is missing", program)
        self.assertIn("voltage profile must be monotone inside fixed endpoints", program)

    def test_reflectron_builder_warns_but_does_not_reject_off_grid_edges(self) -> None:
        builder = (
            PROJECT_ROOT / "simion" / "reflectron" / "build_reflectron_variant.lua"
        ).read_text(encoding="utf-8")
        self.assertIn("reflectron_geometry_edge_not_on_grid_node", builder)
        self.assertIn("policy=warn_and_continue", builder)
        self.assertIn("surface=none action=continue", builder)
        self.assertNotIn("fractional_surface=enabled", builder)


if __name__ == "__main__":
    unittest.main()
