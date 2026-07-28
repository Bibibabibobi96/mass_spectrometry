import importlib.util
from pathlib import Path
import unittest
import numpy as np
import pandas as pd

PATH=Path(__file__).resolve().parents[2]/"analysis"/"compare_rf_hybrid_mesh.py";SPEC=importlib.util.spec_from_file_location("compare_rf_hybrid_mesh",PATH);MODULE=importlib.util.module_from_spec(SPEC);assert SPEC.loader is not None;SPEC.loader.exec_module(MODULE)

def table(scale=1.0):
    rows=[]
    for z in (9.799,9.801,81.399,81.401):
        for radius in (1.0,2.0,3.0,3.6):
            for theta in np.arange(4)*np.pi/2:rows.append({"sample_z_mm":z,"sample_radius_mm":radius,"theta_rad":theta,"Ex_V_per_m":scale*np.cos(theta),"Ey_V_per_m":-scale*np.sin(theta),"Ez_V_per_m":0.0})
    return pd.DataFrame(rows)

class HybridComparisonTests(unittest.TestCase):
    def test_passes_identical_tables(self):
        contract={"field_sampling":{"hard_field_convergence_radius_max_mm":3.0},"acceptance":{"maximum_relative_vector_rms_last_two_end_meshes_r_le_3_mm":1e-3,"maximum_relative_vector_rms_at_partition_pairs_r_le_3_mm":1e-3}}
        self.assertEqual(MODULE.compare(table(),table(),contract)["status"],"PASS")
    def test_rejects_unconverged_pair(self):
        contract={"field_sampling":{"hard_field_convergence_radius_max_mm":3.0},"acceptance":{"maximum_relative_vector_rms_last_two_end_meshes_r_le_3_mm":1e-3,"maximum_relative_vector_rms_at_partition_pairs_r_le_3_mm":1e-3}}
        self.assertEqual(MODULE.compare(table(1.01),table(),contract)["status"],"FAIL")

if __name__=="__main__":unittest.main()
