"""RF owner gate reuses only explicitly completed same-round prerequisites."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[4]
PROJECT = "projects/rf_multipole_ion_optics"
PWSH = shutil.which("pwsh")


@unittest.skipUnless(PWSH, "PowerShell 7 required")
class VerifyProjectTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rf_gate_behavior_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / PROJECT
        self.project.mkdir(parents=True)
        shutil.copyfile(REPO / PROJECT / "verify_project.ps1", self.project / "verify_project.ps1")
        self.log = self.root / "python_calls.jsonl"
        # Python algorithms and host admission have their own owner tests. This
        # facade exercises the real PS driver, discovery and actual PS parser.
        module = "import json,os,sys\nfrom pathlib import Path\n"
        module += "with Path(os.environ['RF_GATE_CALLS']).open('a') as f: f.write(json.dumps(sys.argv)+'\\n')\n"
        module += "raise SystemExit(7 if os.environ.get('RF_GATE_FAIL') in sys.argv else 0)\n"
        for name in ("analysis/resolve_contract", "analysis/sync_simion_geometry",
                     "analysis/generate_official_particle_table", "analysis/entry_aperture_l0",
                     "workflows/mass_filter_reference/theory", "workflows/mass_filter_reference/run_finite_length"):
            target = self.project / (name + ".py")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(module, encoding="utf-8")
        common = self.root / "common"
        common.mkdir()
        (common / "gate_unittest.py").write_text(module, encoding="utf-8")
        for folder in ("analysis", "hexapole", "octupole"):
            tests = self.project / "tests" / folder
            tests.mkdir(parents=True)
            (tests / "test_variant.py").write_text("# inert discovery fixture\n", encoding="utf-8")
        self.syntax = self.project / "shared.ps1"
        self.syntax.write_text("$valid = 1\n", encoding="utf-8")

    def run_gate(self, *arguments, fail=""):
        env = dict(os.environ, RF_GATE_CALLS=str(self.log), RF_GATE_FAIL=fail,
                   PYTHONPATH=str(self.root), PYTHONNOUSERSITE="1")
        return subprocess.run([PWSH, "-NoProfile", "-File", str(self.project / "verify_project.ps1"),
                               "-PythonExe", sys.executable, *arguments], cwd=self.root,
                              env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)

    def test_same_round_parses_once_and_keeps_each_variant_test_command(self):
        results = [self.run_gate("-Level", "Freshness")]
        self.assertEqual(results[0].returncode, 0, results[0].stdout + results[0].stderr)
        for variant in ("quadrupole", "hexapole", "octupole"):
            result = self.run_gate("-Level", "Static", "-StructuralVariant", variant,
                                   "-FreshnessPrevalidated", "-PowerShellSyntaxPrevalidated")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            results.append(result)
        output = "\n".join(row.stdout for row in results)
        self.assertEqual(output.count("MULTIPOLE_POWERSHELL_SYNTAX=PASS FILES=2"), 1)
        self.assertEqual(output.count("MULTIPOLE_POWERSHELL_SYNTAX=PREVALIDATED"), 3)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        test_calls = [row for row in calls if row[0].endswith("gate_unittest.py")]
        self.assertEqual(len(test_calls), 3)
        self.assertEqual([row[1:] for row in test_calls], [
            [f"projects.rf_multipole_ion_optics.tests.{folder}.test_variant"]
            for folder in ("analysis", "hexapole", "octupole")])

    def test_standalone_static_and_legacy_freshness_flag_still_parse(self):
        for arguments in ((), ("-FreshnessPrevalidated",)):
            result = self.run_gate("-Level", "Static", "-StructuralVariant", "hexapole", *arguments)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.count("MULTIPOLE_POWERSHELL_SYNTAX=PASS FILES=2"), 1)

    def test_unsupported_qualification_rejects_before_software_checks(self):
        result = self.run_gate('-Level', 'Formal', '-StructuralVariant', 'hexapole')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('FORMAL_UNQUALIFIED STRUCTURAL_VARIANT=hexapole', result.stderr)
        self.assertFalse(self.log.exists(), 'Unsupported qualification ran Python software checks')
        self.assertNotIn('MULTIPOLE_POWERSHELL_SYNTAX=', result.stdout)

    def test_missing_prerequisite_syntax_and_variant_failure_propagate(self):
        missing = self.run_gate("-Level", "Static", "-PowerShellSyntaxPrevalidated")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("requires FreshnessPrevalidated", missing.stderr)
        self.assertFalse(self.log.exists())
        self.syntax.write_text("function broken {\n", encoding="utf-8")
        syntax = self.run_gate("-Level", "Freshness")
        self.assertNotEqual(syntax.returncode, 0)
        self.assertIn("PowerShell syntax gate failed", syntax.stderr)
        self.assertNotIn("PROJECT_GATE=PASS", syntax.stdout)
        core = self.run_gate("-Level", "Core", "-StructuralVariant", "hexapole",
                             "-FreshnessPrevalidated")
        self.assertEqual(core.returncode, 0, core.stdout + core.stderr)
        self.assertNotIn("MULTIPOLE_POWERSHELL_SYNTAX=", core.stdout)
        self.syntax.write_text("$valid = 1\n", encoding="utf-8")
        failed = self.run_gate("-Level", "Static", "-StructuralVariant", "hexapole",
                               "-FreshnessPrevalidated", "-PowerShellSyntaxPrevalidated",
                               fail="projects.rf_multipole_ion_optics.tests.hexapole.test_variant")
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("Python variant tests failed: hexapole", failed.stderr)
        self.assertNotIn("PROJECT_GATE=PASS", failed.stdout)


if __name__ == "__main__":
    unittest.main()
