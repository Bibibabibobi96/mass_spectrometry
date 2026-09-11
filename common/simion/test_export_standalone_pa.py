from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


SIMION = Path(os.environ.get("SIMION_EXE", r"C:\Program Files\SIMION-2020\simion.exe"))
SOLVER_AUTHORIZED = os.environ.get("SIMION_SOLVER_TEST_AUTHORIZED") == "1"
EXPORTER = Path(__file__).with_name("export_standalone_pa.lua")


BUILD_LUA = r"""
local directory = assert(arg[1], 'temporary directory required')
local separator = package.config:sub(1, 1)
simion.pas:close()
local pa = assert(simion.pas:open(), 'cannot create toy PA family')
pa:size(7, 7, 7)
pa.symmetry = '3dplanar'
pa.dx_mm, pa.dy_mm, pa.dz_mm = 0.5, 0.75, 1.25
pa.refinable = true
for x, y, z in pa:points() do
  if x == 0 then
    pa:point(x, y, z, 1, true)
  elseif x == 6 then
    pa:point(x, y, z, 2, true)
  else
    pa:point(x, y, z, 0, false)
  end
end
pa.filename = directory .. separator .. 'toy.pa#'
pa:save()
pa:refine {}
pa:close()
print('TOY_PA_FAMILY=PASS')
"""


INSPECT_LUA = r"""
local path = assert(arg[1], 'PA path required')
local require_standalone = arg[2] == 'standalone'
local resave = arg[3] == 'resave'
simion.pas:close()
local pa = assert(simion.pas:open(path), 'cannot open PA')
if require_standalone then
  assert(#simion.pas == 1, 'standalone open unexpectedly associated another PA')
end
print(string.format('META nx=%d ny=%d nz=%d symmetry=%s dx=%.17g dy=%.17g dz=%.17g type=%s refined=%s',
  pa.nx, pa.ny, pa.nz, pa.symmetry, pa.dx_mm, pa.dy_mm, pa.dz_mm,
  pa.potential_type, tostring(pa.refined)))
for x, y, z in pa:points() do
  local potential, is_electrode = pa:point(x, y, z)
  print(string.format('POINT %d %d %d %.17g %s',
    x, y, z, potential, tostring(is_electrode)))
end
for _, p in ipairs {{1.25, 2.25, 3.125}, {2.1, 1.5, 2.75}} do
  local potential = pa:potential_vc(p[1], p[2], p[3])
  local ex, ey, ez = pa:field_vc(p[1], p[2], p[3])
  print(string.format('SAMPLE %.17g %.17g %.17g %.17g', potential, ex, ey, ez))
end
if resave then
  pa:save()
  pa:close()
  pa = assert(simion.pas:open(path), 'cannot reopen standalone PA')
  assert(#simion.pas == 1, 'standalone reopen unexpectedly associated another PA')
end
pa:close()
print('PA_INSPECT=PASS')
"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _family_hashes(directory: Path) -> dict[str, str]:
    return {
        path.name: _sha256(path)
        for path in sorted(directory.glob("toy.pa*"))
        if path.is_file()
    }


def _evidence(stdout: str) -> list[str]:
    return [
        line
        for line in stdout.splitlines()
        if line.startswith(("META ", "POINT ", "SAMPLE "))
    ]


@unittest.skipUnless(
    SIMION.is_file() and SOLVER_AUTHORIZED,
    "real SIMION regression requires the public host lease and explicit authorization",
)
class StandalonePaExportTest(unittest.TestCase):
    def _run(self, *arguments: Path | str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(SIMION), "--nogui", "--noprompt", "lua", *(str(x) for x in arguments)],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=EXPORTER.parent,
            timeout=60,
        )

    def test_exports_detached_surface_none_response(self) -> None:
        with tempfile.TemporaryDirectory(prefix="simion_standalone_export_") as temporary:
            root = Path(temporary)
            family = root / "private_family"
            output = root / "isolated_output"
            family.mkdir()
            output.mkdir()
            builder = root / "build.lua"
            inspector = root / "inspect.lua"
            builder.write_text(BUILD_LUA, encoding="utf-8")
            inspector.write_text(INSPECT_LUA, encoding="utf-8")

            self.assertIn("TOY_PA_FAMILY=PASS", self._run(builder, family).stdout)
            source = family / "toy.pa1"
            self.assertTrue(source.is_file())
            family_before = _family_hashes(family)
            self.assertGreaterEqual(len(family_before), 3)
            source_evidence = _evidence(self._run(inspector, source).stdout)

            standalone = output / "response.pa"
            exported = self._run(EXPORTER, source, standalone)
            self.assertIn("STANDALONE_PA_EXPORT=PASS", exported.stdout)
            self.assertIn("copy_mode=native_copy", exported.stdout)
            self.assertEqual([path.name for path in output.iterdir()], ["response.pa"])

            first = self._run(inspector, standalone, "standalone")
            self.assertEqual(_evidence(first.stdout), source_evidence)
            self._run(inspector, standalone, "standalone", "resave")
            self.assertEqual([path.name for path in output.iterdir()], ["response.pa"])

            output_hash = _sha256(standalone)
            self.assertEqual(_family_hashes(family), family_before)
            time.sleep(1.25)
            self.assertEqual(_family_hashes(family), family_before)
            self.assertEqual(_sha256(standalone), output_hash)

    def test_rejects_surface_enhanced_family_before_open(self) -> None:
        with tempfile.TemporaryDirectory(prefix="simion_standalone_surface_reject_") as temporary:
            root = Path(temporary)
            source = root / "toy.pa1"
            source.write_bytes(b"not opened")
            (root / "toy.pa-surf").write_bytes(b"surface metadata")
            output = root / "response.pa"
            completed = subprocess.run(
                [str(SIMION), "--nogui", "--noprompt", "lua", str(EXPORTER), str(source), str(output)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=EXPORTER.parent,
                timeout=30,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("surface-enhanced PA families are unsupported", completed.stdout + completed.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
