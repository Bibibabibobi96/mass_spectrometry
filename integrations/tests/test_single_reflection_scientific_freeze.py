"""Actual declaration freezer and isolated current-provider preparation closure."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from integrations.tests.test_single_reflection_preparation import fixture, scientific_preparation_fixture

ROOT = Path(__file__).resolve().parents[2]
MODULE = "integrations.workflows.single_reflection_flight.prepare"

# Only the snapshot root bootstraps the stdlib-only public root resolver. All
# scientific imports and the actual -m entry then use its declared root order.
_ISOLATED_MODULE = r"""
import json,runpy,sys
from pathlib import Path
snapshot,argvfile=map(lambda p:Path(p).resolve(),sys.argv[1:])
sys.path.insert(0,str(snapshot))
from common.contracts.frozen_inputs import python_import_roots
import common.contracts.frozen_inputs as roots_module
assert Path(roots_module.__file__).resolve().is_relative_to(snapshot)
sys.path.pop(0)
sys.path[:0]=python_import_roots(snapshot)
arguments=json.loads(argvfile.read_text(encoding='utf-8'))
assert arguments[:2]==['-m','integrations.workflows.single_reflection_flight.prepare']
sys.argv=[arguments[1],*arguments[2:]]
try:
 runpy.run_module(arguments[1],run_name='__main__',alter_sys=True)
except SystemExit as completed:
 if completed.code not in (None,0):raise
version=json.loads(Path(arguments[arguments.index('--request')+1]).read_text())['schema_version']
required=(
 'msplatform.backends.simion.tof_electrode_mapping',
 'msplatform.components.single_reflection_oa_tof.electrode_topology',
 'msplatform.components.single_reflection_oa_tof.geometry_contract',
 'msplatform.components.rf_multipole.electrode_topology',
 'msplatform.backends.simion.rf_electrode_mapping',
 'msplatform.assembly.resolve_assembly',
)
if version==9:
 required=tuple(name for name in required if name != 'msplatform.backends.simion.tof_electrode_mapping')
 assert 'msplatform.backends.simion.tof_electrode_mapping' not in sys.modules
assert all(name in sys.modules for name in required), required
origins={}
for name,module in list(sys.modules.items()):
 if name.split('.')[0] not in ('common','projects','integrations','msplatform'):continue
 origin=getattr(module,'__file__',None)
 if origin:
  path=Path(origin).resolve()
  assert path.is_relative_to(snapshot),(name,str(path))
  if name.startswith('msplatform.'):
   assert path.is_relative_to(snapshot/'src'),(name,str(path))
  origins[name]=str(path)
print('SNAPSHOT_ORIGINS_JSON='+json.dumps(origins,ensure_ascii=False))
"""


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
class SingleReflectionScientificFreezeTests(unittest.TestCase):
    def test_actual_snapshot_current_prepare_and_missing_closure_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix="科学 snapshot detached ") as directory:
            root = Path(directory)
            authoring = root / "physical inputs 非源码"
            authoring.mkdir()
            request, _, _ = scientific_preparation_fixture(authoring, recorded_birth=True)
            legacy_root = root / "legacy physical inputs"
            legacy_root.mkdir()
            legacy_request, _, _ = fixture(legacy_root)
            original_inputs = {path: path.read_bytes() for path in authoring.rglob("*") if path.is_file()}
            self.assertFalse(root.is_relative_to(ROOT))
            frozen_inputs = root / "frozen inputs 空格"
            script = root / "freeze.ps1"
            script.write_text("""
param($Python,$Repo,$Output)
. (Join-Path $Repo 'integrations/runtime/dependencies.ps1')
$frozen=Freeze-ConsumerDependencies -Python $Python -RepoRoot $Repo `
 -ContractPath (Join-Path $Repo 'integrations/config/runtime_dependencies.json') `
 -InputDir $Output -OwnerId instrument_assembly -ConsumerId single_reflection_flight
$frozen.execution_root
""", encoding="utf-8")
            frozen = subprocess.run(
                [shutil.which("pwsh"), "-NoProfile", "-File", str(script),
                 sys.executable, str(ROOT), str(frozen_inputs)],
                cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=120, check=False,
            )
            self.assertEqual(frozen.returncode, 0, frozen.stdout + frozen.stderr)
            snapshot = frozen_inputs / "runtime_snapshot"
            self.assertFalse(snapshot.is_relative_to(ROOT))
            inventory = json.loads((frozen_inputs / "code_inventory.json").read_text(encoding="utf-8-sig"))
            rows = inventory["dependencies"]
            source_paths = [row["source_repo_path"] for row in rows]
            self.assertEqual(len(source_paths), len(set(source_paths)))
            schemas = {path.relative_to(ROOT).as_posix()
                       for path in (ROOT / "src/msplatform/contracts/schemas").glob("*.schema.json")}
            self.assertEqual(set(path for path in source_paths if path.startswith("src/msplatform/contracts/schemas/")), schemas)
            for relative in schemas:
                self.assertEqual((snapshot / relative).read_bytes(), (ROOT / relative).read_bytes())
            for version in ("schema.json", "schema_v10.json"):
                relative = "integrations/workflows/single_reflection_flight/" + version
                self.assertIn(relative, source_paths)
                self.assertEqual((snapshot / relative).read_bytes(), (ROOT / relative).read_bytes())
            backend = snapshot / "src/msplatform/backends/simion/tof_electrode_mapping.py"
            self.assertTrue(backend.is_file())
            required_sources = (
                "src/msplatform/backends/simion/tof_electrode_mapping.py",
                "src/msplatform/components/single_reflection_oa_tof/electrode_topology.py",
                "src/msplatform/components/single_reflection_oa_tof/geometry_contract.py",
                "src/msplatform/components/rf_multipole/electrode_topology.py",
                "src/msplatform/backends/simion/rf_electrode_mapping.py",
                "src/msplatform/assembly/resolve_assembly.py",
            )
            for relative in required_sources:
                self.assertIn(relative, source_paths)
                self.assertEqual((snapshot / relative).read_bytes(), (ROOT / relative).read_bytes())
            self.assertFalse((snapshot / "integrations/tests").exists())
            outside = root / "outside working directory 树外"
            outside.mkdir()

            def invoke(name, selected_request=request):
                run = root / name
                (run / "inputs").mkdir(parents=True)
                argvfile = root / (name + " argv.json")
                argvfile.write_text(json.dumps(["-m", MODULE, "--request", str(selected_request),
                                                "--run", str(run)], ensure_ascii=False), encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, "-X", "utf8", "-I", "-B", "-c", _ISOLATED_MODULE,
                     str(snapshot), str(argvfile)], cwd=outside,
                    capture_output=True, text=True, encoding="utf-8", timeout=60, check=False,
                )
                return result, run

            complete, run = invoke("new10 complete")
            self.assertEqual(complete.returncode, 0, complete.stdout + complete.stderr)
            lines = complete.stdout.splitlines()
            result = json.loads(next(line for line in lines if line.startswith('{')))
            self.assertEqual(result["particle_count"], 100)
            self.assertEqual(result["stage"], "geometry_preparation_only")
            origins = json.loads(next(line.split("=", 1)[1] for line in lines
                                      if line.startswith("SNAPSHOT_ORIGINS_JSON=")))
            for origin in origins.values():
                self.assertTrue(Path(origin).is_relative_to(snapshot), origin)
            self.assertEqual(json.loads((run / "inputs/request.json").read_text())["schema_version"], 10)
            self.assertTrue((run / "inputs/projected_source.csv").is_file())
            saved = backend.read_bytes()
            try:
                backend.unlink()
                rejected, badrun = invoke("new10 missing backend")
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn("msplatform.backends.simion.tof_electrode_mapping", rejected.stderr)
                self.assertFalse((badrun / "inputs/projected_source.csv").exists())
                legacy, legacy_run = invoke("legacy9 without new backend", legacy_request)
                self.assertEqual(legacy.returncode, 0, legacy.stdout + legacy.stderr)
                self.assertEqual(json.loads((legacy_run / "inputs/request.json").read_text())["schema_version"], 9)
                self.assertTrue((legacy_run / "inputs/projected_source.csv").is_file())
            finally:
                backend.write_bytes(saved)
            resource = snapshot / "src/msplatform/contracts/schemas/component_geometry_interface_v3.schema.json"
            saved = resource.read_bytes()
            try:
                resource.unlink()
                rejected, badrun = invoke("new10 missing component3")
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn("component_geometry_interface_v3.schema.json", rejected.stderr)
                self.assertFalse((badrun / "inputs/projected_source.csv").exists())
            finally:
                resource.write_bytes(saved)
            for path, original in original_inputs.items():
                self.assertEqual(path.read_bytes(), original, str(path))
