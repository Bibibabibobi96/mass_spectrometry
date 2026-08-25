from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPORTER = PROJECT_ROOT / "workflows/cross_solver_diagnostics/simion/export_total_axis_field.lua"


class ExportTotalAxisFieldProgramContractTests(unittest.TestCase):
    def test_initializes_frozen_program_before_sampling_total_field(self) -> None:
        text = EXPORTER.read_text(encoding="utf-8")
        self.assertIn("OATOF_TOTAL_AXIS_FIELD_PROGRAM", text)
        self.assertIn("OATOF_TOTAL_AXIS_FIELD_PULSE_TIME_US", text)
        self.assertIn("segment.initialize_run()", text)
        self.assertIn("ion_instance=3", text)
        self.assertIn("ion_instance=5", text)
        self.assertLess(text.index("segment.initialize_run()"), text.index("simion.wb:efield"))


if __name__ == "__main__":
    unittest.main()
