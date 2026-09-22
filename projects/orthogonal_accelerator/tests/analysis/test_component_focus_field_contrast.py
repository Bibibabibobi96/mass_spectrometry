from __future__ import annotations
import json, tempfile, unittest
from pathlib import Path
from projects.orthogonal_accelerator.analysis.component_focus_field_contrast import reduce
class FieldContrastTests(unittest.TestCase):
 def test_identifies_zone2_when_its_idealization_has_larger_reduction(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp); paths=[]
   for i,value in enumerate((8.,7.,2.,1.)):
    p=root/f'{i}.json';p.write_text(json.dumps({'focus_metrics':{'peak_to_peak_t_ns':value}}));paths.append(p)
   result=reduce(*paths)
   self.assertEqual(result['dominant_finite_field_region'],'zone2_finite_field')
   self.assertEqual(result['recommended_next_geometry_action'],'increase_zone2_ring_count_before_expanding_y_or_mesh')
if __name__=='__main__':unittest.main()
