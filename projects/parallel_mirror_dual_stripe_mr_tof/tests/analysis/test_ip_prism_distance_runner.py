"""Exercise native case-batch preparation without invoking SIMION or leases."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


RUNNER = Path(__file__).resolve().parents[2] / "analysis/run_ip_prism_distance_study.ps1"
LUA = shutil.which("lua") or "C:/Program Files/SIMION-2020/lua.exe"


@unittest.skipUnless(Path(LUA).is_file(), "Plain Lua interpreter required; never launches SIMION")
class NativeStageBehaviorTests(unittest.TestCase):
    """Run the actual Lua case driver against inert vendor-interface stubs."""

    def invoke(self, stage: str, count: int = 1) -> str:
        with tempfile.TemporaryDirectory(prefix="ip_native_stage_") as directory:
            root = Path(directory)
            driver = root / "run_case.lua"
            shutil.copyfile(RUNNER.parents[1] / "simion/run_ip_prism_local_case.lua", driver)
            (root/"local.lua").write_text("-- complete program fixture\n", encoding="utf-8")
            (root/"local.fly2").write_text("particles { standard_beam {n=1} }\n", encoding="utf-8")
            (root / "case_config.lua").write_text(
                'return {case_id="test",box_mm={0,-2,-2,2,2,2},pitch_mm={.1,.2,.1},'
                'convergence_v=1e-5,workbench_seed_path="seed",source={},exit_z_mm=0,'
                'observation_planes={{name="p1_exit",z_mm=-.1}},probe_step_mm=.1,'
                'nominal_y_mm=0,trajectory_quality=8}\n', encoding="utf-8")
            harness = root / "harness.lua"
            harness.write_text(r'''
local driver,stage=arg[1],arg[2]
local calls={gem=0,refine=0,save=0,fly=0,wbload=0,wbsave=0}
local wb
local pa={path='seed.pa'}
function pa:load(path) self.path=path end
function pa:refine(_) calls.refine=calls.refine+1 end
function pa:save(_) calls.save=calls.save+1 end
function pa:close()
 assert(#wb.instances==0 or wb.instances[1].pa~=self,'PA cannot be unloaded when used by workbench')
end
function pa:electrode(...) return false end
function pa:potential_vc(...) return 0 end
function pa:field_vc(...) return 0,0,0 end
local instance={pa=pa}
function instance:_debug_update_size() end
function instance:pa_to_wb_coords(x,y,z) return self.x+x*.1,self.y+y*.2,self.z+z*.1 end
wb={instances={instance}}
function wb:load(_) calls.wbload=calls.wbload+1;self.instances={instance} end
function wb:load_particles(_) end
function wb:save(path)
 assert(#self.instances==1,'cannot save the cleared post-Fly Workbench')
 calls.wbsave=calls.wbsave+1
 for _,extension in ipairs({'.lua','.fly2'}) do
  local f=assert(io.open(path:gsub('%.iob$',extension),'wb'));f:write('-- truncated GUI stub');f:close()
 end
end
simion={pas={pa},wb=wb}
function simion.pas:close() self[1]=nil;wb.instances={} end
function simion.pas:open(path) pa.path=path return pa end
function simion.command(command)
 if command:match('^gem2pa ') then calls.gem=calls.gem+1
 elseif command:match('^fly ') then calls.fly=calls.fly+1;wb.instances={};wb.path=nil
 else error('unexpected command: '..command) end
end
for index=1,tonumber(arg[3]) do assert(loadfile(driver))(stage) end
print(string.format('COUNTS=%d,%d,%d,%d,%d,%d',calls.gem,calls.refine,calls.save,calls.fly,calls.wbload,calls.wbsave))
''', encoding="utf-8")
            result = subprocess.run([LUA, str(harness), str(driver), stage, str(count)], cwd=root,
                                    capture_output=True, text=True, check=True, timeout=30)
            self.assertEqual((root/"local.lua").read_text(), "-- complete program fixture\n")
            self.assertEqual((root/"local.fly2").read_text(), "particles { standard_beam {n=1} }\n")
            return result.stdout.strip().splitlines()[-1]

    def test_build_refines_and_reloads_without_fly(self) -> None:
        self.assertEqual(self.invoke("build"), "COUNTS=1,1,1,0,2,1")

    def test_fly_only_loads_field_without_refine_or_pa_save(self) -> None:
        self.assertEqual(self.invoke("fly"), "COUNTS=0,0,0,1,2,1")

    def test_combined_preserves_one_refine_one_fly(self) -> None:
        self.assertEqual(self.invoke("combined"), "COUNTS=1,1,1,1,2,1")

    def test_grouped_cases_release_existing_workbench_references(self) -> None:
        for stage, expected in (("build","COUNTS=2,2,2,0,4,2"),("fly","COUNTS=0,0,0,2,4,2")):
            with self.subTest(stage=stage):
                self.assertEqual(self.invoke(stage,2),expected)

    def test_assemble_neither_builds_nor_flies_and_preserves_companions(self) -> None:
        self.assertEqual(self.invoke("assemble"), "COUNTS=0,0,0,0,2,1")

    def test_program_run_initialization_quality_and_explicit_gui_view_policy(self) -> None:
        # Reuse the strict real-Lua callback fixture, not a permissive global stub.
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis import test_ip_prism_local_callbacks as callbacks

        fixture = callbacks.LocalCallbackPermissionsTests()
        for gui, expected in ((False, 3), (True, 0)):
            with self.subTest(gui=gui):
                _, _, output = fixture.execute("native", gui=gui)
                self.assertIn(f"RUN_SETTINGS=PASS Q=8 image={expected}", output)


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell Core 7 is required")
class DistanceRunnerTests(unittest.TestCase):
    """Execute the actual isolated PowerShell preparation function via its AST."""

    def invoke(self, first: int, last: int, count: int, *, missing: bool = False, phase: str = "combined") -> dict:
        with tempfile.TemporaryDirectory(prefix="ip_prism_runner_") as directory:
            root = Path(directory)
            cases = []
            for index in range(4):
                case = root / f"case_{index + 1}"
                case.mkdir()
                script = case / "run_case.lua"
                if not missing or index != last - 1:
                    script.write_text("-- frozen test case\n", encoding="utf-8")
                cases.append({"case_id": f"case_{index + 1}", "script": str(script)})
            fixture = root / "fixture.json"
            fixture.write_text(json.dumps({"cases": cases,"build_cases":[cases[0],cases[2]],
                                           "flight_cases":[cases[2],cases[3],cases[0],cases[1]],
                                           "assembly_cases":[cases[3],cases[2],cases[1],cases[0]]}), encoding="utf-8")
            source = r'''
param($Runner,$Root,$Fixture,$First,$Last,$Count,$Phase)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors.Message -join '; ')}
$function=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name-eq'New-StudyProcessSpecification'},$true)
. ([scriptblock]::Create($function.Extent.Text))
$run=$Root;$SimionExe='not-launched-simion.exe';$package=[pscustomobject]@{log_dir=$Root}
$study=Get-Content -LiteralPath $Fixture -Raw|ConvertFrom-Json
try {
 $spec=New-StudyProcessSpecification ([pscustomobject]@{index=2;work_item_id_min=[int]$First;work_item_id_max=[int]$Last;count=[int]$Count}) -Phase $Phase
 $text=Get-Content -LiteralPath $spec.argument_list[-1] -Raw
 @{status='success';spec=$spec;wrapper=$text}|ConvertTo-Json -Depth 10 -Compress
} catch {@{status='failed';message=$_.Exception.Message}|ConvertTo-Json -Compress}
'''
            harness = root / "harness.ps1"
            harness.write_text(source, encoding="utf-8")
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(harness), str(RUNNER), str(root),
                 str(fixture), str(first), str(last), str(count), phase],
                cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30, check=True,
            )
            return json.loads(result.stdout)

    def test_single_formal_case_keeps_exact_work_item(self) -> None:
        result = self.invoke(1, 1, 1)
        self.assertEqual(result["status"], "success")
        spec = result["spec"]
        self.assertEqual(spec["scheduler_batch"]["count"], 1)
        self.assertEqual(spec["scheduler_batch"]["execution_unit"], "independent_work_items")
        self.assertEqual(spec["argument_list"][:3], ["--nogui", "--noprompt", "lua"])
        self.assertEqual(result["wrapper"].count("dofile("), 1)
        self.assertIn("case_1/run_case.lua", result["wrapper"])

    def test_grouped_tail_runs_each_case_once_in_plan_order(self) -> None:
        result = self.invoke(2, 4, 3)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["wrapper"].count("dofile("), 3)
        self.assertNotIn("case_1/", result["wrapper"])
        self.assertLess(result["wrapper"].index("case_2/"), result["wrapper"].index("case_3/"))
        self.assertLess(result["wrapper"].index("case_3/"), result["wrapper"].index("case_4/"))
        self.assertEqual(result["spec"]["scheduler_batch"]["count"], 3)

    def test_wrong_interval_count_fails_before_solver(self) -> None:
        self.assertEqual(self.invoke(2, 4, 2)["status"], "failed")

    def test_outside_study_interval_fails_before_solver(self) -> None:
        for interval in ((0, 1, 2), (3, 2, 0), (1, 5, 5)):
            with self.subTest(interval=interval):
                self.assertEqual(self.invoke(*interval)["status"], "failed")

    def test_missing_frozen_case_script_fails_before_solver(self) -> None:
        result = self.invoke(2, 4, 3, missing=True)
        self.assertEqual(result["status"], "failed")
        self.assertIn("Missing frozen case script", result["message"])

    def test_build_phase_schedules_only_unique_field_owners(self) -> None:
        result=self.invoke(1,2,2,phase="build")
        self.assertEqual(result["status"],"success")
        self.assertIn(')("build")',result["wrapper"])
        self.assertIn("case_1/run_case.lua",result["wrapper"])
        self.assertIn("case_3/run_case.lua",result["wrapper"])
        self.assertNotIn("case_2/run_case.lua",result["wrapper"])
        self.assertEqual(self.invoke(1,3,3,phase="build")["status"],"failed")

    def test_fly_phase_keeps_all_source_and_step_cases(self) -> None:
        result=self.invoke(1,4,4,phase="fly")
        self.assertEqual(result["status"],"success")
        self.assertEqual(result["wrapper"].count(')("fly")'),4)
        self.assertIn("case_2/run_case.lua",result["wrapper"])
        self.assertLess(result["wrapper"].index("case_3/run_case.lua"),result["wrapper"].index("case_1/run_case.lua"))

    def test_private_delivery_assembles_each_case_without_build_or_fly(self) -> None:
        result=self.invoke(1,4,4,phase="assemble")
        self.assertEqual(result["status"],"success")
        self.assertEqual(result["wrapper"].count(')("assemble")'),4)
        self.assertNotIn(')("build")',result["wrapper"])
        self.assertNotIn(')("fly")',result["wrapper"])
        self.assertLess(result["wrapper"].index("case_4/run_case.lua"),result["wrapper"].index("case_1/run_case.lua"))


if __name__ == "__main__":
    unittest.main()
