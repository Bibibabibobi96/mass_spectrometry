from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
INTEGRATION_ROOT = (
    REPO_ROOT
    / "integrations"
    / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
)


class ResolvedConnectionAuthorityTests(unittest.TestCase):
    def test_no_checked_in_project_local_resolved_connection_exists(self) -> None:
        names = {
            path.name
            for path in (PROJECT_ROOT / "config").glob("*resolved*connection*.json")
        }
        self.assertEqual(names, set())

    def test_active_code_does_not_import_retired_project_resolvers(self) -> None:
        active_paths = (
            PROJECT_ROOT / "analysis",
            INTEGRATION_ROOT / "runtime",
            INTEGRATION_ROOT / "stages",
            PROJECT_ROOT / "verify_project.ps1",
        )
        text_parts: list[str] = []
        for root in active_paths:
            if root.is_file():
                text_parts.append(root.read_text(encoding="utf-8"))
                continue
            for path in root.rglob("*"):
                if path.is_file() and path.suffix in {".py", ".ps1", ".m"}:
                    text_parts.append(path.read_text(encoding="utf-8"))
        combined = "\n".join(text_parts)
        for forbidden in (
            "resolve_s2_connector_case",
            "resolved_rf_to_oatof_s2_spatial_registration",
            "analysis.resolve_spatial_registration",
        ):
            self.assertNotIn(forbidden, combined)


if __name__ == "__main__":
    unittest.main()
