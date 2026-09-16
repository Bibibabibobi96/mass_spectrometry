from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
FAST_ADJUST_EXPORTER = ROOT / "export_fast_adjusted_standalone_pa.lua"
COMPOSER = ROOT / "compose_standalone_pa.lua"
DIRICHLET_OPERATING_PATCH = ROOT / "build_dirichlet_patch_operating_pa.lua"
SIMION = Path(os.environ.get("SIMION_EXE", r"C:\Program Files\SIMION-2020\simion.exe"))
SOLVER_AUTHORIZED = os.environ.get("SIMION_SOLVER_TEST_AUTHORIZED") == "1"


class StandalonePaToolStaticContractTest(unittest.TestCase):
    def test_dirichlet_operating_patch_accepts_solved_standalone_parent(self) -> None:
        source = DIRICHLET_OPERATING_PATCH.read_text(encoding="utf-8")
        self.assertIn("SOURCE_OPERATING_PA_OR_PA0", source)
        self.assertIn("source_path:match('%.pa0$') or source_path:match('%.pa$')", source)
        self.assertIn("source:potential_vc", source)
        self.assertIn("solved:refine()", source)

    def test_fast_adjust_export_contract_is_fail_closed_and_does_not_refine(self) -> None:
        source = FAST_ADJUST_EXPORTER.read_text(encoding="utf-8")
        self.assertIn("source_pa:fast_adjust(voltages)", source)
        self.assertIn("source_pa.electrode_numbers", source)
        self.assertIn("operating-point table is incomplete", source)
        self.assertIn("simion.pas:open()", source)
        self.assertIn("output_pa:copy(source_pa)", source)
        self.assertIn("if output_pa.copy then", source)
        self.assertIn("same-prefix physical geometry PA# is missing", source)
        self.assertIn('"policy_id":"physical_geometry_boundary_flags_v1"', source)
        self.assertIn("output_pa:electrode(ix, iy, iz, false)", source)
        self.assertIn("standalone export lost a physical boundary electrode", source)
        self.assertIn("disjoint standalone boundary traversal is incomplete", source)
        self.assertNotIn("for x, y, z in output_pa:points() do\n  local physical", source)
        self.assertNotIn("pcall", source)
        self.assertIn("output_pa.refined = true", source)
        self.assertIn("output_pa.refinable = false", source)
        self.assertIn("surface-enhanced PA families are unsupported", source)
        self.assertIn("standalone output already exists", source)
        self.assertNotIn(":refine", source)
        self.assertNotIn("source_pa:save(output)", source)

    def test_composer_uses_standalone_inputs_and_preserves_base_flags(self) -> None:
        source = COMPOSER.read_text(encoding="utf-8")
        self.assertIn("must use a standalone .pa or neutral .bin suffix", source)
        self.assertIn("neutral temporary name", source)
        self.assertIn("output_pa:copy(base_pa)", source)
        self.assertIn("output_pa:potential_add(x, y, z, delta)", source)
        self.assertIn("potential + delta, is_electrode", source)
        self.assertIn("for x, y, z in output_pa:points() do", source)
        self.assertIn("delta = delta + response.coefficient * response.pa:potential(x, y, z)", source)
        self.assertLess(
            source.index("for x, y, z in output_pa:points() do"),
            source.index("output_pa:potential_add(x, y, z, delta)"),
        )
        self.assertIn("response PA grid, symmetry, or potential type differs", source)
        self.assertIn("output_pa.refined = true", source)
        self.assertIn("output_pa.refinable = false", source)
        self.assertIn("surface=none is required", source)
        self.assertIn("standalone output already exists", source)
        self.assertNotIn(":refine", source)
        self.assertNotIn("assert(base_pa.refined", source)
        self.assertNotIn("assert(response.pa.refined", source)

    def test_real_solver_tests_are_explicitly_gated(self) -> None:
        source = Path(__file__).read_text(encoding="utf-8")
        self.assertIn('os.environ.get("SIMION_SOLVER_TEST_AUTHORIZED") == "1"', source)
        self.assertIn("@unittest.skipUnless", source)


BUILD_FAMILY_LUA = r"""
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


CHECK_OPERATING_POINT_LUA = r"""
local path = assert(arg[1], 'standalone PA required')
local expected_left = assert(tonumber(arg[2]), 'left value required')
local expected_right = assert(tonumber(arg[3]), 'right value required')
simion.pas:close()
local pa = assert(simion.pas:open(path), 'cannot open standalone PA')
assert(#simion.pas == 1, 'output is not detached from a PA family')
local left, left_electrode = pa:point(0, 3, 3)
local right, right_electrode = pa:point(6, 3, 3)
local middle, middle_electrode = pa:point(3, 3, 3)
assert(math.abs(left - expected_left) < 1e-9 and left_electrode,
       'left electrode potential or flag differs')
assert(math.abs(right - expected_right) < 1e-9 and right_electrode,
       'right electrode potential or flag differs')
assert(not middle_electrode, 'base non-electrode flag was not preserved')
pa:close()
print(string.format('OPERATING_POINT=PASS middle=%.17g', middle))
"""


@unittest.skipUnless(
    SIMION.is_file() and SOLVER_AUTHORIZED,
    "real SIMION regression requires the public host lease and explicit authorization",
)
class StandalonePaToolAuthorizedSolverTest(unittest.TestCase):
    def _run(
        self, *arguments: Path | str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            [str(SIMION), "--nogui", "--noprompt", "lua", *(str(x) for x in arguments)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            cwd=ROOT,
        )
        if check and completed.returncode != 0:
            self.fail(
                "SIMION command failed "
                f"({completed.returncode}): {completed.args!r}\n"
                f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
            )
        return completed

    def test_complete_fast_adjust_export_and_standalone_composition(self) -> None:
        with tempfile.TemporaryDirectory(prefix="simion_standalone_tools_") as temporary:
            root = Path(temporary)
            builder = root / "build.lua"
            checker = root / "check.lua"
            builder.write_text(BUILD_FAMILY_LUA, encoding="utf-8")
            checker.write_text(CHECK_OPERATING_POINT_LUA, encoding="utf-8")
            self.assertIn("TOY_PA_FAMILY=PASS", self._run(builder, root).stdout)

            controller = root / "toy.pa0"
            base = root / "base.pa"
            response = root / "response.pa"
            composed = root / "composed.pa"
            base_receipt = root / "base.boundary_mask.json"
            response_receipt = root / "response.boundary_mask.json"
            exported = self._run(
                FAST_ADJUST_EXPORTER, controller, base, base_receipt, "1=3", "2=7"
            )
            self.assertIn("FAST_ADJUSTED_STANDALONE_PA=PASS", exported.stdout)
            self.assertIn(
                "FAST_ADJUSTED_STANDALONE_PA=PASS",
                self._run(
                    FAST_ADJUST_EXPORTER,
                    controller,
                    response,
                    response_receipt,
                    "1=1",
                    "2=0",
                ).stdout,
            )
            self.assertIn(
                '"policy_id":"physical_geometry_boundary_flags_v1"',
                base_receipt.read_text(encoding="utf-8"),
            )
            self.assertIn("OPERATING_POINT=PASS", self._run(checker, base, "3", "7").stdout)

            combined = self._run(COMPOSER, base, composed, f"{response},2")
            self.assertIn("STANDALONE_PA_COMPOSITION=PASS", combined.stdout)
            self.assertIn("OPERATING_POINT=PASS", self._run(checker, composed, "5", "7").stdout)

    def test_incomplete_fast_adjust_table_is_rejected_without_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="simion_standalone_incomplete_") as temporary:
            root = Path(temporary)
            builder = root / "build.lua"
            builder.write_text(BUILD_FAMILY_LUA, encoding="utf-8")
            self._run(builder, root)
            output = root / "must_not_exist.pa"
            completed = self._run(
                FAST_ADJUST_EXPORTER,
                root / "toy.pa0",
                output,
                root / "must_not_exist.boundary_mask.json",
                "1=3",
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(
                "operating-point table is incomplete",
                completed.stdout + completed.stderr,
            )
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
