from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
EXPORTER = ROOT / "export_detached_standalone_pa.lua"
SIMION = Path(os.environ.get("SIMION_EXE", r"C:\Program Files\SIMION-2020\simion.exe"))
SOLVER_AUTHORIZED = os.environ.get("SIMION_SOLVER_TEST_AUTHORIZED") == "1"


class DetachedStandaloneStaticTest(unittest.TestCase):
    def test_contract_uses_new_object_and_rejects_native_responses(self) -> None:
        source = EXPORTER.read_text(encoding="utf-8")
        self.assertIn("simion.pas:open()", source)
        self.assertIn("output_pa:copy(source_pa)", source)
        self.assertIn("if output_pa.copy then", source)
        self.assertNotIn("pcall", source)
        self.assertIn("native PA-family response members are forbidden", source)
        self.assertIn("output must use the standalone .pa suffix", source)
        self.assertIn("surface=none is required", source)
        self.assertNotIn(":refine", source)
        self.assertNotIn("source_pa:save(output)", source)


BUILD_SOURCE = r"""
local root = assert(arg[1])
local sep = package.config:sub(1, 1)
local source = root .. sep .. 'source.pa0'
simion.pas:close()
local pa = assert(simion.pas:open())
pa:size(5, 4, 3)
pa.symmetry = '3dplanar'
pa.dx_mm, pa.dy_mm, pa.dz_mm = 0.5, 1.0, 2.0
for x, y, z in pa:points() do
  pa:point(x, y, z, x + 10*y + 100*z, x == 0 or x == 4)
end
pa:save(source)
pa:close()
print('DETACHED_SOURCE_BUILD=PASS')
"""


CHECK_OUTPUT = r"""
local output = assert(arg[1])
simion.pas:close()
local reopened = assert(simion.pas:open(output))
assert(#simion.pas == 1, 'detached output associated another PA')
assert(reopened.nx == 5 and reopened.ny == 4 and reopened.nz == 3)
assert(reopened.dx_mm == 0.5 and reopened.dy_mm == 1.0 and reopened.dz_mm == 2.0)
for x, y, z in reopened:points() do
  local potential, electrode = reopened:point(x, y, z)
  assert(potential == x + 10*y + 100*z, 'detached potential differs')
  assert(electrode == (x == 0 or x == 4), 'detached electrode flag differs')
end
reopened:close()
print('DETACHED_STANDALONE_REAL=PASS')
"""


@unittest.skipUnless(
    SIMION.is_file() and SOLVER_AUTHORIZED,
    "real SIMION regression requires the public host lease and explicit authorization",
)
class DetachedStandaloneAuthorizedTest(unittest.TestCase):
    def test_real_detachment_reopens_without_siblings(self) -> None:
        with tempfile.TemporaryDirectory(prefix="simion_detached_pa_") as temporary:
            root = Path(temporary)
            builder = root / "build.lua"
            checker = root / "check.lua"
            builder.write_text(BUILD_SOURCE, encoding="utf-8")
            checker.write_text(CHECK_OUTPUT, encoding="utf-8")
            command = [str(SIMION), "--nogui", "--noprompt", "lua"]
            built = subprocess.run(
                [*command, str(builder), str(root)],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=ROOT,
                timeout=60,
            )
            self.assertIn("DETACHED_SOURCE_BUILD=PASS", built.stdout)
            exported = subprocess.run(
                [*command, str(EXPORTER), str(root / "source.pa0"), str(root / "output.pa")],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=ROOT,
                timeout=60,
            )
            self.assertIn("DETACHED_STANDALONE_PA_EXPORT=PASS", exported.stdout)
            checked = subprocess.run(
                [*command, str(checker), str(root / "output.pa")],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=ROOT,
                timeout=60,
            )
            self.assertIn("DETACHED_STANDALONE_REAL=PASS", checked.stdout)
            self.assertEqual(
                sorted(path.name for path in root.iterdir()),
                ["build.lua", "check.lua", "output.pa", "source.pa0"],
            )


if __name__ == "__main__":
    unittest.main()
