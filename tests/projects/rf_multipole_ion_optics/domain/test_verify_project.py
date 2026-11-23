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
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[4]
PROJECT = "src/msplatform/components/rf_multipole"
PWSH = shutil.which("pwsh")


@unittest.skipUnless(PWSH, "PowerShell 7 required")
class VerifyProjectTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rf_gate_behavior_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / PROJECT
        self.project.mkdir(parents=True)
        self.workflow_resources = self.root / "src/msplatform/workflows/resources"
        self.workflow_resources.mkdir(parents=True)
        shutil.copyfile(REPO / "src/msplatform/workflows/resources/verify_project.ps1", self.workflow_resources / "verify_project.ps1")
        self.test_root = self.root / "tests/projects/rf_multipole_ion_optics"
        particle_fixture = self.project / "variants/quadrupole/config"
        (particle_fixture / "particles").mkdir(parents=True)
        for relative in ("particles/official_fixed_100.ion", "particles/official_fixed_100_canonical.csv", "resolved_design_official.json"):
            shutil.copyfile(REPO / PROJECT / "variants/quadrupole/config" / relative, particle_fixture / relative)
        self.log = self.root / "python_calls.jsonl"
        # Python algorithms and host admission have their own owner tests. This
        # facade exercises the real PS driver, discovery and actual PS parser.
        module = "import json,os,sys\nfrom pathlib import Path\n"
        module += "with Path(os.environ['RF_GATE_CALLS']).open('a') as f: f.write(json.dumps(sys.argv)+'\\n')\n"
        module += "raise SystemExit(7 if os.environ.get('RF_GATE_FAIL') in sys.argv else 0)\n"
        for name in ("workflows/rf_publication", "analysis/sync_simion_geometry",
                     "analysis/generate_official_particle_table", "analysis/entry_aperture_l0",
                     "workflows/rf_mass_filter/theory", "workflows/rf_mass_filter/research"):
            target = self.root / "src/msplatform" / (name + ".py")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(module, encoding="utf-8")
            package = target.parent
            while package != self.root / "src":
                init = package / "__init__.py"
                init.touch()
                if package in (self.root / "src/msplatform", self.root / "src/msplatform/workflows"):
                    init.write_text(f"__path__.append({str(REPO / 'src/msplatform' / package.relative_to(self.root / 'src/msplatform'))!r})\n", encoding="utf-8")
                package = package.parent
        repository_tools = self.root / "tools/repository"
        repository_tools.mkdir(parents=True)
        (repository_tools / "gate_unittest.py").write_text(module, encoding="utf-8")
        resources = self.root / "src/msplatform/execution/resources"
        resources.mkdir(parents=True)
        for name in ("require_powershell7.ps1", "host_execution_lease.ps1", "host_resource_policy.json"):
            shutil.copyfile(REPO / "src/msplatform/execution/resources" / name, resources / name)
        for folder in ("analysis", "hexapole", "octupole"):
            tests = self.test_root / folder
            tests.mkdir(parents=True)
            (tests / "test_variant.py").write_text("# inert discovery fixture\n", encoding="utf-8")
        self.syntax = self.workflow_resources / "shared.ps1"
        self.syntax.write_text("$valid = 1\n", encoding="utf-8")

    def run_gate(self, *arguments, fail="", selected=None):
        env = dict(os.environ, RF_GATE_CALLS=str(self.log), RF_GATE_FAIL=fail,
                   PYTHONPATH=str(self.root) + os.pathsep + os.environ.get("PYTHONPATH", ""), PYTHONNOUSERSITE="1")
        entry = str(self.workflow_resources / "verify_project.ps1")
        command = [PWSH, "-NoProfile", "-File", entry, "-PythonExe", sys.executable, *arguments]
        if selected is not None:
            def quote(value):
                return "'" + str(value).replace("'", "''") + "'"
            script = "& " + quote(entry) + " -PythonExe " + quote(sys.executable)
            script += " " + " ".join(value if value.startswith("-") else quote(value) for value in arguments)
            script += " -SelectedTestModules @(" + ",".join(quote(value) for value in selected) + ")"
            command = [PWSH, "-NoProfile", "-Command", script]
        return subprocess.run(command, cwd=self.root,
                              env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)

    def test_partition_preflight_and_selected_workers_do_not_repeat_prerequisites(self):
        modules = [f"tests.projects.rf_multipole_ion_optics.{folder}.test_variant"
                   for folder in ("analysis", "new_area")]
        future = self.test_root / "new_area/test_variant.py"
        future.parent.mkdir()
        future.write_text("# unknown owner-root discovery fixture\n", encoding="utf-8")
        preflight = self.run_gate("-Level", "Static", "-StructuralVariant", "quadrupole",
                                  "-FreshnessPrevalidated", "-PowerShellSyntaxPrevalidated", "-PreflightOnly")
        self.assertEqual(preflight.returncode, 0, preflight.stdout + preflight.stderr)
        self.assertIn("PYTHON_TESTS=DEFERRED", preflight.stdout)
        for module in modules:
            worker = self.run_gate("-Level", "Static", "-StructuralVariant", "quadrupole",
                                   "-PreflightValidated", selected=[module])
            self.assertEqual(worker.returncode, 0, worker.stdout + worker.stderr)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        test_calls = [row[1:] for row in calls if row[0].endswith("gate_unittest.py")]
        self.assertEqual(test_calls, [[module] for module in modules])
        self.assertEqual(len(calls), 3, calls)  # One instrumented preflight command, two test workers.

    def test_partition_refuses_mixed_foreign_duplicate_and_failed_selected_tests(self):
        module = "tests.projects.rf_multipole_ion_optics.analysis.test_variant"
        cases = [(["-Level", "Core"], [module]),
                 (["-PreflightOnly"], [module]),
                 (["-ChangedTestModules", module], [module]),
                 (["-Level", "Static", "-PreflightValidated"], [module, module]),
                 (["-Level", "Static", "-PreflightValidated"], ["common.contracts.test_other"]),
                 (["-Level", "Static", "-PreflightValidated"], ["tests.projects.rf_multipole_ion_optics.hexapole.test_variant"])]
        for arguments, selected in cases:
            with self.subTest(arguments=arguments, selected=selected):
                result = self.run_gate("-StructuralVariant", "quadrupole", *arguments, selected=selected)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(self.log.exists(), "Rejected partition ran a Python check")
        failed = self.run_gate("-Level", "Static", "-StructuralVariant", "quadrupole",
                               "-PreflightValidated", selected=[module], fail=module)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("Python variant test partition failed", failed.stderr)
        self.assertNotIn("MULTIPOLE_TEST_PARTITION=PASS", failed.stdout)

    def test_changed_modules_still_augment_core_and_complete_static(self):
        extra = "tests.projects.rf_multipole_ion_optics.analysis.test_explicit_changed"
        for level in ("Core", "Static"):
            result = self.run_gate("-Level", level, "-StructuralVariant", "quadrupole",
                                   "-ChangedTestModules", extra)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        test_calls = [row[1:] for line in self.log.read_text().splitlines()
                      if (row := json.loads(line))[0].endswith("gate_unittest.py")]
        self.assertEqual(test_calls[0], [extra])
        self.assertCountEqual(test_calls[1], [extra, "tests.projects.rf_multipole_ion_optics.analysis.test_variant"])

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
            [f"tests.projects.rf_multipole_ion_optics.{folder}.test_variant"]
            for folder in ("analysis", "hexapole", "octupole")])
        freshness = results[0].stdout
        for variant in ("quadrupole", "hexapole", "octupole"):
            self.assertIn(f"VARIANT_PUBLICATION=PASS STRUCTURAL_VARIANT={variant}", freshness)
        for profile in ("official", "mass_filter"):
            self.assertIn(f"RESOLVED_DESIGN=PASS PROFILE={profile}", freshness)

    def test_official_and_interface_share_publication_and_reject_changed_bytes(self):
        from msplatform.workflows import rf_publication

        source_project = REPO / PROJECT
        profiles = rf_publication.profile_paths(source_project)
        self.assertEqual(profiles["official"], profiles["interface"])
        publication = self.root / "publication.json"
        selected = dict(profiles["official"], output=publication)
        expected = json.dumps(rf_publication.resolve(
            "official", project_root=source_project, repository_root=REPO, profiles=profiles
        ), indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        selected_profiles = dict(profiles, official=selected, interface=selected)
        for profile in ("official", "interface"):
            with self.subTest(profile=profile), patch.object(sys, "argv", ["rf_publication", "--profile", profile, "--check"]):
                publication.write_text(expected, encoding="utf-8", newline="\n")
                rf_publication.main(project_root=self.root, repository_root=REPO, profiles=selected_profiles)
                publication.write_text("{}\n", encoding="utf-8", newline="\n")
                with self.assertRaisesRegex(SystemExit, "STALE=publication.json"):
                    rf_publication.main(project_root=self.root, repository_root=REPO, profiles=selected_profiles)

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
                               fail="tests.projects.rf_multipole_ion_optics.hexapole.test_variant")
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("Python variant tests failed: hexapole", failed.stderr)
        self.assertNotIn("PROJECT_GATE=PASS", failed.stdout)


if __name__ == "__main__":
    unittest.main()
