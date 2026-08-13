import unittest
from pathlib import Path

class AcceleratorDzConvergenceTests(unittest.TestCase):
    def test_analysis_declares_paired_threshold_and_secondary_peak_rule(self):
        text=(Path(__file__).parents[1]/"analysis"/"analyze_accelerator_dz_convergence.py").read_text(encoding="utf-8")
        self.assertIn("0.03378871363500548",text)
        self.assertIn("paired_sigma_pass",text)
        self.assertIn("do not determine convergence alone",text)
