from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "simion/workbench/candidates/oatof_analyzer_component.lua"
LUA_TEST = Path(__file__).with_suffix(".lua")
SIMION_EXE = Path(r"C:\Program Files\SIMION-2020\simion.exe")


class OatofAnalyzerComponentTests(unittest.TestCase):
    @unittest.skipUnless(SIMION_EXE.is_file(), "official SIMION Lua CLI unavailable")
    def test_official_simion_lua_cli_executes_component_contract(self) -> None:
        result = subprocess.run(
            [
                str(SIMION_EXE),
                "--nogui",
                "--noprompt",
                "lua",
                str(LUA_TEST),
                str(COMPONENT),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OATOF_ANALYZER_COMPONENT_TEST=PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
