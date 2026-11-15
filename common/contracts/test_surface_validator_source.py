"""Actual geometry owner refuses an unbound validator before native planning."""
import tempfile, unittest
from pathlib import Path
from msplatform.backends.simion.compiler import CompiledSimionGeometry
from msplatform.backends.simion.geometry_execution import execute_geometry
from msplatform.io.manifest_records import file_record

class SurfaceValidatorSourceTests(unittest.TestCase):
 def test_missing_or_foreign_validator_refused_before_session(self):
  geometry=object.__new__(CompiledSimionGeometry)
  object.__setattr__(geometry,'frontend_geometry',{'role':'simion_ip_mr_complete_geometry'})
  with tempfile.TemporaryDirectory() as d:
   seed=Path(d)/'seed';seed.write_bytes(b'inert-seed');record=file_record(seed,'required_evidence')
   for validator in (None,record):
    with self.subTest(validator=validator),self.assertRaisesRegex(ValueError,'surface validator source differs'):
     execute_geometry(None,compiled=geometry,seed_record=record,limits={},surface_validator_record=validator)
