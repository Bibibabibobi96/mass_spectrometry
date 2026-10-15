"""Run analytical potential/gradient contracts with standalone Lua, without SIMION."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]
REPOSITORY = PROJECT.parents[1]


def lua_literal(value: object) -> str:
    """Serialize the numeric/string baseline fixture to a Lua table expression."""
    if isinstance(value, dict):
        return "{" + ",".join(
            f"[{json.dumps(key)}]={lua_literal(item)}" for key, item in value.items()
        ) + "}"
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return repr(value)
    raise TypeError(f"Unsupported test fixture value: {type(value)}")


class FieldModelTests(unittest.TestCase):
    """Independent finite differences and physical sign/clock/bath checks."""

    def test_field_model_contract(self) -> None:
        """Compare exact gradients with scalar-potential differences at interfaces."""
        executable = os.environ.get("SIMION_LUA_EXE") or shutil.which("lua")
        if executable is None:
            installed = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "SIMION-2020/lua.exe"
            if installed.is_file():
                executable = str(installed)
        if executable is None:
            self.skipTest("Standalone Lua unavailable; set SIMION_LUA_EXE to run mathematical checks")
        baseline = json.loads((PROJECT / "config/baseline.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="ion_processor_field_test_") as temporary:
            fixture = Path(temporary) / "baseline.lua"
            fixture.write_text("return " + lua_literal(baseline) + "\n", encoding="utf-8")
            result = subprocess.run(
                [executable, str(PROJECT / "tests/test_field_model.lua"),
                 str(PROJECT / "simion/field_model.lua"), str(fixture),
                 str(REPOSITORY / "common/multipole/simion_rf_drive.lua")],
                cwd=REPOSITORY, capture_output=True, text=True, encoding="utf-8", timeout=30,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("FIELD_MODEL_TEST_PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
