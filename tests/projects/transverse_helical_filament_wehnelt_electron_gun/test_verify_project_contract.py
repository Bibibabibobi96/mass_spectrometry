from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
VERIFIER = REPO_ROOT / "src/msplatform/workflows/resources/wehnelt_verify.ps1"


class VerifyProjectContractTests(unittest.TestCase):
    def test_resolves_python_before_changing_location(self) -> None:
        source = VERIFIER.read_text(encoding="utf-8")
        resolve_index = source.index(
            "$PythonExe = (Resolve-Path -LiteralPath $PythonExe -ErrorAction Stop).Path"
        )
        push_location_index = source.index("Push-Location $repoRoot")
        self.assertLess(resolve_index, push_location_index)

    def test_retired_tree_is_rejected(self) -> None:
        source = VERIFIER.read_text(encoding="utf-8")
        self.assertIn("projects/transverse_helical_filament_wehnelt_electron_gun", source)
        self.assertIn("Retired Wehnelt project tree remains active", source)
        self.assertIn("tests/projects/transverse_helical_filament_wehnelt_electron_gun", source)
