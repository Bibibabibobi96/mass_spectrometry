import importlib.util
from pathlib import Path
import unittest

import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[2] / "analysis" / "compare_rf_continuous_shield_n100.py"
SPEC = importlib.util.spec_from_file_location("compare_rf_continuous_shield_n100", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC); assert SPEC.loader is not None; SPEC.loader.exec_module(MODULE)


def events(statuses: list[str]) -> pd.DataFrame:
    count=len(statuses)
    return pd.DataFrame({"particle_id":range(1,count+1),"status":statuses,"global_time_us":[1.0]*count,"rf_phase_rad":[0.0]*count,"x_mm":[0.0]*count,"y_mm":[0.0]*count,"vx_m_s":[0.0]*count,"vy_m_s":[0.0]*count,"vz_m_s":[1.0]*count,"kinetic_energy_eV":[2.0]*count,"radial_position_mm":[1.0]*count,"divergence_angle_deg":[1.0]*count})


class CompareShieldN100Tests(unittest.TestCase):
    def test_classification_change_fails(self) -> None:
        _, summary=MODULE.compare(events(["transmitted","lost"]),events(["transmitted","transmitted"]))
        self.assertEqual(summary["classification_change_count"],1)
        self.assertEqual(summary["acceptance_decision"],"FAIL")

    def test_identical_classification_remains_unresolved(self) -> None:
        _, summary=MODULE.compare(events(["transmitted"]),events(["transmitted"]))
        self.assertEqual(summary["acceptance_decision"],"UNRESOLVED")
        self.assertEqual(summary["paired_rf_phase_difference_rms_rad_common_transmitted"],0.0)


if __name__ == "__main__": unittest.main()
