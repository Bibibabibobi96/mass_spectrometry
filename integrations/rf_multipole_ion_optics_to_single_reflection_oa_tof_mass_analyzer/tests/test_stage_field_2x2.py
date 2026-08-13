import unittest
import numpy as np
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.analyze_stage_field_2x2 import effect_vectors

class StageField2x2Tests(unittest.TestCase):
    def test_high_minus_low_effects_and_interaction_scale(self):
        values = {"RR": np.array([1.0]), "IR": np.array([3.0]), "RI": np.array([5.0]), "II": np.array([11.0])}
        effects = effect_vectors(values)
        self.assertEqual(effects["stage1_ideal_main"].item(), 4.0)
        self.assertEqual(effects["stage2_ideal_main"].item(), 6.0)
        self.assertEqual(effects["stage1_stage2_interaction"].item(), 2.0)
