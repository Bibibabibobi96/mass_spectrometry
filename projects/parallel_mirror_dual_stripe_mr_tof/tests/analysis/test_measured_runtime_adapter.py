"""Exercise the real MR callback core with measured source projection in plain Lua."""
from __future__ import annotations

from msplatform.backends.simion.resources import native_resource_path
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest

PROJECT = Path(__file__).resolve().parents[2]
REPO = PROJECT.parents[1]


class MeasuredRuntimeAdapterTest(unittest.TestCase):
    """Pure callbacks with FLY2-owned TOF and a read-only initialize clock."""

    def test_original_ids_clock_initialization_topology_and_timeout(self) -> None:
        lua = shutil.which("lua") or shutil.which("lua5.1")
        if lua is None:
            installed = Path("C:/Program Files/SIMION-2020/lua.exe")
            lua = str(installed) if installed.exists() else None
        if lua is None:
            self.skipTest("plain Lua interpreter unavailable; no solver fallback")
        runtime = native_resource_path("mrtof_measured_source_runtime.lua").read_text(encoding="utf-8")
        with TemporaryDirectory(prefix="mr-measured-runtime-") as temporary:
            root = Path(temporary)
            (root / "source_runtime.lua").write_text(runtime, encoding="utf-8")
            (root / "source_states.lua").write_text(
                "return {[1]={t=0,x=3,y=-5,z=0,vx=0,vy=1,vz=-1},"
                "[2]={t=.06,x=3,y=-5,z=0,vx=0,vy=1,vz=-1}}", encoding="utf-8")
            (root / "source_projection.lua").write_text(
                'return {epoch_us=7500.51,clock_epoch_id="ip_epoch",frame_id="mr_frame",mapping={'
                '{simion_ordinal=1,particle_id=7,mass_amu=524,charge_state=1,'
                'instrument_time_us=7500.51,solver_birth_time_us=0,particle_birth_time_us=0,lineage_birth_time_us=0},'
                '{simion_ordinal=2,particle_id=64,mass_amu=524,charge_state=1,'
                'instrument_time_us=7500.57,solver_birth_time_us=.06,particle_birth_time_us=0,lineage_birth_time_us=0}}}',
                encoding="utf-8")
            result = subprocess.run(
                [lua, str(PROJECT / "tests/simion/test_measured_runtime.lua"), str(REPO), str(root)],
                cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("MEASURED_RUNTIME=PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
