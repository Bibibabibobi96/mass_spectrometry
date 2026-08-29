"""Prevent active SIMION code from overriding the official Refine default."""

from __future__ import annotations

from pathlib import Path
import re
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_CONVERGENCE_OVERRIDE = re.compile(
    r"\brefine\b[^\r\n]*(?:--?convergence|\bconvergence\s*=)",
    re.IGNORECASE,
)
FORBIDDEN_INITIALIZER_OVERRIDE = re.compile(
    r"(?:initialize_fast_adjust_pa_basis\.lua|\bbasisinitializer\b)[^\r\n]*(?:,\s*['\"]?[0-9])",
    re.IGNORECASE,
)
SKIPPED_PATH_PARTS = {"archive", "history", ".git", ".venv"}


class SimionRefinePolicyTests(unittest.TestCase):
    """Active Lua and PowerShell refine calls may not set a convergence value."""

    def test_active_simion_refine_calls_use_the_official_default(self) -> None:
        violations: list[str] = []
        this_file = Path(__file__).resolve()
        for suffix in ("*.lua", "*.ps1"):
            for path in REPOSITORY_ROOT.rglob(suffix):
                if path.resolve() == this_file or set(path.parts).intersection(
                    SKIPPED_PATH_PARTS
                ):
                    continue
                for line_number, line in enumerate(
                    path.read_text(encoding="utf-8", errors="replace").splitlines(),
                    start=1,
                ):
                    if (
                        FORBIDDEN_CONVERGENCE_OVERRIDE.search(line)
                        or FORBIDDEN_INITIALIZER_OVERRIDE.search(line)
                    ):
                        violations.append(f"{path.relative_to(REPOSITORY_ROOT)}:{line_number}")
        self.assertEqual(violations, [], "custom SIMION Refine convergence is prohibited")


if __name__ == "__main__":
    unittest.main()
