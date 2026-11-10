"""Project gates delegate duplicate checks without claiming their result."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]
RUFF_PROJECTS = (
    "apertured_tube_electron_impact_ion_source",
    "transverse_helical_filament_wehnelt_electron_gun",
    "dual_cone_tandem_quadrupole_ion_interface",
)
OA = "orthogonal_accelerator"
MR = "parallel_mirror_dual_stripe_mr_tof"
PWSH = shutil.which("pwsh")


@unittest.skipUnless(PWSH, "PowerShell 7 required")
class ProjectGatePrevalidationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="project_gate_delegate_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.log = self.root / "calls.jsonl"
        common = self.root / "common"
        common.mkdir()
        shutil.copyfile(REPO / "common/require_powershell7.ps1", common / "require_powershell7.ps1")
        # Admission is outside this fixture's responsibility. Actual project
        # dispatch, Python exits and PowerShell parsing remain real processes.
        (common / "host_execution_lease.ps1").write_text(
            "function Enter-HostExecutionLease { param($Role) return @{} }\n"
            "function Exit-HostExecutionLease { param($Lease) }\n", encoding="utf-8")
        module = "import json,os,sys\nfrom pathlib import Path\n"
        module += "name=Path(__file__).stem\n"
        module += "with Path(os.environ['GATE_CALLS']).open('a') as f: f.write(json.dumps([name,*sys.argv[1:]])+'\\n')\n"
        module += "code=(7 if name=='gate_unittest' else 9) if os.environ.get('GATE_FAIL')==name else 0\n"
        module += "if code: print('GATE_FIXTURE_EXIT='+str(code), file=sys.stderr)\nraise SystemExit(code)\n"
        for name in ("ruff.py", "common/gate_unittest.py",
                     "common/contracts/build_project_registry.py"):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(module, encoding="utf-8")
        for project in (*RUFF_PROJECTS, OA, MR):
            target = self.root / "projects" / project
            target.mkdir(parents=True)
            source = (REPO / "projects" / project / "verify_project.ps1").read_text(encoding="utf-8")
            (target / "verify_project.ps1").write_text(source, encoding="utf-8")
            for resolver in ("resolve_contract", "resolve_geometry"):
                path = target / "analysis" / (resolver + ".py")
                path.parent.mkdir(exist_ok=True)
                path.write_text(module, encoding="utf-8")
            required = re.search(r"\$requiredProjectFiles = @\((.*?)\n    \)", source, re.S)
            if required:
                for relative in re.findall(r"'([^']+)'", required[1]):
                    path = target / relative.replace("\\", "/")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("# inert authority fixture\n", encoding="utf-8")
            required_core = re.search(r"\$requiredCoreFiles = @\((.*?)\n    \)", source, re.S)
            if required_core:
                for relative in re.findall(r"'([^']+)'", required_core[1]):
                    path = self.root / relative.replace("\\", "/")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("# inert canonical authority fixture\n", encoding="utf-8")
            for relative in ("config/baseline.json", "config/numerical_modes.json",
                             "config/resolved_model.json", "config/resolved_geometry.json"):
                authority = REPO / "projects" / project / relative
                if authority.is_file():
                    (target / relative).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(authority, target / relative)
        (self.root/"lua_probe.ps1").write_text("exit 0\n", encoding="utf-8")
        lua = self.root / "projects" / MR / "tests/simion"
        lua.mkdir(parents=True)
        for name in ("test_candidate_plane_events.lua", "test_candidate_voltage_map.lua",
                     "test_mirror_cycle_counter.lua"):
            (lua / name).write_text("-- inert plain-Lua dispatch fixture\n", encoding="utf-8")

    def run_gate(self, project, *arguments, fail="", automatic_lua=False, lua_directory=None, lua_temporary=None):
        if project == OA and not automatic_lua:
            arguments = (*arguments, "-LuaExe", str(self.root/"lua_probe.ps1"))
        return subprocess.run(
            [PWSH, "-NoProfile", "-File", str(self.root / "projects" / project / "verify_project.ps1"),
             "-PythonExe", sys.executable, *arguments], cwd=self.root,
            env=dict(os.environ, GATE_CALLS=str(self.log), GATE_FAIL=fail,
                     ProgramFiles=str(self.root / "no_vendor"), PYTHONPATH=str(self.root),
                     TEMP=str(lua_temporary) if lua_temporary else os.environ.get("TEMP", ""),
                     PATH=(str(lua_directory) + os.pathsep + os.environ.get("PATH", "")) if lua_directory else os.environ.get("PATH", "")),
            capture_output=True, text=True, encoding="utf-8", timeout=30)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_project_ruff_default_and_parent_delegation_keep_exact_scope(self):
        for project in RUFF_PROJECTS:
            with self.subTest(project=project):
                self.log.unlink(missing_ok=True)
                direct = self.run_gate(project)
                self.assertEqual(direct.returncode, 0, direct.stdout + direct.stderr)
                ruff = [row for row in self.calls() if row[0] == "ruff"]
                expected_ruff = [f"src/msplatform/components/{project}"]
                if project == RUFF_PROJECTS[2]:
                    expected_ruff += ["src/msplatform/backends/simion/dual_cone_geometry.py",
                                      f"projects/{project}/analysis", f"projects/{project}/simion"]
                expected_ruff.append(f"projects/{project}/tests" +
                                     ("" if project == RUFF_PROJECTS[2] else "/analysis"))
                self.assertEqual(ruff, [["ruff", "check", *expected_ruff]])
                self.log.unlink()
                delegated = self.run_gate(project, "-RuffHandledByParent", fail="ruff")
                self.assertEqual(delegated.returncode, 0, delegated.stdout + delegated.stderr)
                self.assertIn("RUFF=HANDLED_BY_PARENT", delegated.stdout)
                self.assertFalse(any(row[0] == "ruff" for row in self.calls()))
                self.assertTrue(any(row[0] == "gate_unittest" for row in self.calls()))
                failed = self.run_gate(project, fail="ruff")
                self.assertNotEqual(failed.returncode, 0)
                self.assertIn("Ruff checks failed", failed.stderr)

    def test_all_four_wrappers_use_public_runner_and_propagate_exit_seven(self):
        for project in (*RUFF_PROJECTS, OA):
            with self.subTest(project=project):
                self.log.unlink(missing_ok=True)
                direct = self.run_gate(project)
                self.assertEqual(direct.returncode, 0, direct.stdout+direct.stderr)
                calls = [row for row in self.calls() if row[0] == "gate_unittest"]
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][1], "discover")
                start = calls[0].index("-s")+1
                expected = self.root/"projects"/project/"tests"
                if project != RUFF_PROJECTS[2]:
                    expected = expected/"analysis"
                selected = Path(calls[0][start])
                self.assertEqual((selected if selected.is_absolute() else self.root/selected).resolve(), expected.resolve())
                self.log.unlink()
                failed = self.run_gate(project, fail="gate_unittest")
                self.assertNotEqual(failed.returncode, 0)
                self.assertIn("GATE_FIXTURE_EXIT=7", failed.stderr)
                self.assertNotIn("PROJECT_GATE=PASS", failed.stdout)
                self.assertFalse(any(row[0] == "ruff" for row in self.calls()))

    def test_mr_registry_default_skip_and_failure_preserve_real_preflight(self):
        direct = self.run_gate(MR, "-PreflightOnly")
        self.assertEqual(direct.returncode, 0, direct.stdout + direct.stderr)
        self.assertEqual(sum(row[0] == "build_project_registry" for row in self.calls()), 1)
        self.log.unlink()
        delegated = self.run_gate(MR, "-PreflightOnly", "-RegistryPrevalidated", fail="build_project_registry")
        self.assertEqual(delegated.returncode, 0, delegated.stdout + delegated.stderr)
        self.assertIn("PROJECT_REGISTRY=PREVALIDATED", delegated.stdout)
        self.assertFalse(any(row[0] == "build_project_registry" for row in self.calls()))
        failed = self.run_gate(MR, "-PreflightOnly", fail="build_project_registry")
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("registration is stale or invalid", failed.stderr)
        (self.root / "projects" / MR / "bad.ps1").write_text("function incomplete {\n", encoding="utf-8")
        syntax = self.run_gate(MR, "-PreflightOnly", "-RegistryPrevalidated")
        self.assertNotEqual(syntax.returncode, 0)
        self.assertIn("PowerShell syntax gate failed", syntax.stderr)


    def test_actual_plain_lua_scripts_use_path_and_keep_explicit_authority_and_failure(self):
        lua = Path(shutil.which("lua") or shutil.which("lua5.1") or
                   "C:/Program Files/SIMION-2020/lua.exe")
        self.assertTrue(lua.is_file(), "standalone Lua software-test dependency required")
        print("PROJECT_GATE_SOFTWARE_LUA=" + str(lua.resolve()))
        resources = [
            *(f"projects/{MR}/tests/simion/{name}" for name in (
                "test_candidate_plane_events.lua", "test_candidate_voltage_map.lua", "test_mirror_cycle_counter.lua")),
            *(f"projects/{MR}/simion/{name}" for name in (
                "mrtof_candidate.lua", "candidate_voltage_map.lua", "mirror_cycle_counter.lua")),
            "src/msplatform/backends/simion/resources/scientific_event_csv.lua",
            "src/msplatform/backends/simion/resources/voltage_waveforms.lua",
            f"projects/{OA}/tests/simion/test_required_parameters.lua",
            f"projects/{OA}/tests/simion/test_component_focus_callbacks.lua",
            f"projects/{OA}/simion/build_two_zone_pa.lua",
            f"projects/{OA}/simion/two_zone_accelerator.gem",
            f"projects/{OA}/simion/component_focus.lua",
        ]
        for relative in resources:
            source, target = REPO / relative, self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            self.assertEqual(target.read_bytes(), source.read_bytes())
        lua_temporary = self.root / "private_lua_outputs"
        lua_temporary.mkdir()
        for project in (MR, OA):
            args = ("-PreflightOnly", "-RegistryPrevalidated") if project == MR else ()
            with self.subTest(project=project, case="path"):
                result = self.run_gate(project, *args, automatic_lua=True, lua_directory=lua.parent, lua_temporary=lua_temporary)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                if project == MR:
                    for marker in ("CANDIDATE_PLANE_EVENTS=PASS", "CANDIDATE_VOLTAGE_MAP=PASS",
                                   "PASS mirror_cycle_counter:"):
                        self.assertIn(marker, result.stdout)
                    self.assertNotIn("MRTOF_PLAIN_LUA=SKIP", result.stdout)
                else:
                    self.assertIn("ACCELERATOR_REQUIRED_PARAMETERS=PASS cases=26", result.stdout)
                    if not (lua.parent / "examples/test_plane/testplanelib.lua").is_file():
                        self.assertIn("ACCELERATOR_COMPONENT_FOCUS_CALLBACKS=SKIP REASON=official_test_plane_library_unavailable", result.stdout)
            with self.subTest(project=project, case="explicit"):
                explicit = self.run_gate(project, *args, "-LuaExe", str(lua),
                                         automatic_lua=True, lua_directory=lua.parent, lua_temporary=lua_temporary)
                self.assertEqual(explicit.returncode, 0, explicit.stdout + explicit.stderr)
            with self.subTest(project=project, case="missing_explicit"):
                missing = self.run_gate(project, *args, "-LuaExe", str(self.root / "missing-lua.exe"),
                                        automatic_lua=True, lua_directory=lua.parent, lua_temporary=lua_temporary)
                self.assertNotEqual(missing.returncode, 0)
                self.assertIn("Explicit Lua executable is missing", missing.stderr)
                self.assertNotIn("PROJECT_GATE=PASS", missing.stdout)
            dependency = self.root / (f"projects/{MR}/simion/candidate_voltage_map.lua" if project == MR
                                      else f"projects/{OA}/simion/two_zone_accelerator.gem")
            payload = dependency.read_bytes()
            dependency.unlink()
            try:
                with self.subTest(project=project, case="actual_script_nonzero"):
                    failed = self.run_gate(project, *args, automatic_lua=True, lua_directory=lua.parent, lua_temporary=lua_temporary)
                    self.assertNotEqual(failed.returncode, 0)
                    self.assertIn("plain-Lua regression failed" if project == MR else
                                  "Lua parameter-contract regression failed", failed.stderr)
                    self.assertNotIn("PROJECT_GATE=PASS", failed.stdout)
            finally:
                dependency.write_bytes(payload)
            self.assertEqual(dependency.read_bytes(), payload)
            self.assertEqual(list(lua_temporary.iterdir()), [])



if __name__ == "__main__":
    unittest.main()
