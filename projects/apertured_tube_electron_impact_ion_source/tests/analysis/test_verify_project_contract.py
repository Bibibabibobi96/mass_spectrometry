from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class VerifyProjectContractTests(unittest.TestCase):
    def test_resolves_python_before_changing_location(self) -> None:
        source = (PROJECT_ROOT / "verify_project.ps1").read_text(encoding="utf-8")

        resolve_index = source.index(
            "$PythonExe = (Resolve-Path -LiteralPath $PythonExe -ErrorAction Stop).Path"
        )
        push_location_index = source.index("Push-Location $projectRoot")

        self.assertLess(resolve_index, push_location_index)
