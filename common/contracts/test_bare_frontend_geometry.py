"""Canonical bare-guide/OA compiler with explicit profile and no checkout imports."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import sysconfig
import tempfile
import unittest

from integrations.tests.frontend_fixtures import canonical_frontend_fixture
from msplatform.backends.simion.bare_frontend_geometry import compile_frontend


class BareFrontendGeometryTests(unittest.TestCase):
    def test_explicit_two_zone_profile_required_and_science_unchanged(self):
        guide, connection, component = canonical_frontend_fixture()
        before = copy.deepcopy((guide,connection,component))
        gem, contract = compile_frontend(guide,connection,accelerator_component=component,
            cell_mm_xyz=dict(x=1.,y=1.,z=.1))
        self.assertEqual((guide,connection,component),before)
        self.assertEqual(contract["accelerator_component"]["geometry_profile"],component["geometry_profile"])
        self.assertIn("pa_define",gem)
        del component["geometry_profile"]
        with self.assertRaisesRegex(ValueError,"explicit canonical two-zone"):
            compile_frontend(guide,connection,accelerator_component=component,cell_mm_xyz=dict(x=1.,y=1.,z=.1))

    def test_cold_actual_compiler_never_imports_root_modules(self):
        guide, connection, component = canonical_frontend_fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"request.json"
            path.write_text(json.dumps([guide,connection,component]))
            root = Path(__file__).resolve().parents[2]
            code = """import sys,json
from pathlib import Path
sys.path[:0]=[sys.argv[1],sys.argv[2]]
from msplatform.backends.simion.bare_frontend_geometry import compile_frontend
up,connection,component=json.loads(Path(sys.argv[3]).read_text())
gem,contract=compile_frontend(up,connection,accelerator_component=component,cell_mm_xyz=dict(x=1.,y=1.,z=.1))
assert gem and contract['guide_contract']==up
assert not any(x.split('.')[0]in{'common','projects','integrations'}for x in sys.modules)
print('COLD_BARE_FRONTEND=PASS')
"""
            result=subprocess.run([sys.executable,'-I','-S','-c',code,str(root/'src'),sysconfig.get_path('purelib'),str(path)],cwd=directory,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('COLD_BARE_FRONTEND=PASS',result.stdout)
