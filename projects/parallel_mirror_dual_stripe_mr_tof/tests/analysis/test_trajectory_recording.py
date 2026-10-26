"""Opt-in step observation and dense trajectory lifecycle tests; no field solve."""
from pathlib import Path
import json
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial import (
    extract_trajectory_samples,
    resolve_trajectory_recording,
)

PROJECT = Path(__file__).resolve().parents[2]


class TrajectoryRecordingTest(unittest.TestCase):
    def test_default_off_and_invalid_retention_rejected(self):
        self.assertIsNone(resolve_trajectory_recording({"simion": {}}))
        good = {"schema_version": 1, "mode": "every_step", "retention_class": "solver_review", "reason": "supplier trajectory review", "output_budget_bytes": 268435456}
        self.assertEqual(resolve_trajectory_recording({"simion": {"trajectory_recording": good}}), good)
        for changes in ({"mode": "interpolate"}, {"retention_class": "compact"}, {"reason": ""}, {"extra": 1}, {"output_budget_bytes": 0}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                resolve_trajectory_recording({"simion": {"trajectory_recording": good | changes}})

    def test_fixed_interval_contract_is_closed_and_positive(self):
        good = {"schema_version":1,"mode":"fixed_interval","interval_us":.1,
                "retention_class":"solver_review","reason":"cloud diagnosis","output_budget_bytes":2*1024**3}
        self.assertEqual(resolve_trajectory_recording({"simion":{"trajectory_recording":good}}),good)
        for interval in (0,-.1,True,float("nan"),float("inf"),".1"):
            with self.subTest(interval=interval),self.assertRaises(ValueError):
                resolve_trajectory_recording({"simion":{"trajectory_recording":good|{"interval_us":interval}}})
        for bad in (good|{"mode":"every_step"},{k:v for k,v in good.items() if k!="interval_us"}):
            with self.assertRaises(ValueError):resolve_trajectory_recording({"simion":{"trajectory_recording":bad}})

    def test_fixed_interval_preserves_short_loss_and_bounded_native_terminal_clock(self):
        policy={"schema_version":1,"mode":"fixed_interval","interval_us":.1,"retention_class":"solver_review","reason":"cloud diagnosis","output_budget_bytes":2*1024**3}
        row="MRTOF_TRAJECTORY ion=20 phase={phase} t_us={time} x_mm=1 y_mm=2 z_mm=3 vx_mm_us=4 vy_mm_us=5 vz_mm_us=6\n"
        with TemporaryDirectory() as temporary:
            root=Path(temporary);log=root/"raw.log";csv=root/"samples.csv";receipt=root/"receipt.json"
            for phases in ((("birth",7500.061),("terminal",7500.09)),
                           (("birth",7500.061),("step",7500.101),("step",7500.205),("terminal",7500.201))):
                log.write_text("".join(row.format(phase=p,time=t) for p,t in phases))
                result=extract_trajectory_samples(log_path=log,output_path=csv,receipt_path=receipt,recording_config=policy)
                self.assertEqual(result["sampling_mode"],"fixed_interval")
                self.assertEqual(result["sampling_interval_us"],.1)
                self.assertEqual(result["samples_per_particle"][20],len(phases))
                self.assertIn("7500.061",csv.read_text())
                with self.assertRaises(ValueError):extract_trajectory_samples(log_path=log,output_path=csv,receipt_path=receipt)
            self.assertEqual(result["terminal_clock_backsteps"][0]["ion"],20)
            for bad in (log.read_text().replace("t_us=7500.201","t_us=7500.01"),
                        log.read_text().replace("phase=terminal t_us=7500.201 x_mm=1","phase=terminal t_us=7500.201 x_mm=9")):
                log.write_text(bad)
                with self.assertRaises(ValueError):extract_trajectory_samples(log_path=log,output_path=csv,receipt_path=receipt,recording_config=policy)

    def test_fixed_interval_actual_lua_callbacks_keep_clock_identity_and_state(self):
        lua=shutil.which("lua") or "C:/Program Files/SIMION-2020/lua.exe"
        if not Path(lua).exists() and shutil.which(lua) is None:self.skipTest("plain Lua unavailable")
        source=(PROJECT/"simion/mrtof_candidate.lua").read_text()
        function=source[source.index("local trajectory_sample_buckets"):source.index("local static_field_adjust")]
        script="""local operating_point={trajectory_recording_enabled=true,trajectory_recording_mode='fixed_interval',trajectory_recording_interval_us=.1}
local function event_id() return ion_number==1 and 20 or 80 end
local function instrument_time_us() return 7500+ion_time_of_flight end
ion_px_mm=1;ion_py_mm=2;ion_pz_mm=3;ion_vx_mm=4;ion_vy_mm=5;ion_vz_mm=6
ion_time_step=.004;ion_splat=0
"""+function+"""
ion_number=1;ion_time_of_flight=.061;record_trajectory_sample('birth')
for _,t in ipairs({.065,.101,.15,.205}) do ion_time_of_flight=t;record_trajectory_sample('step') end
ion_time_of_flight=.201;record_trajectory_sample('terminal')
ion_number=2;ion_time_of_flight=.071;record_trajectory_sample('birth')
ion_time_of_flight=.075;record_trajectory_sample('step')
ion_time_of_flight=.09;record_trajectory_sample('terminal')
assert(ion_time_step==.004 and ion_time_of_flight==.09 and ion_splat==0)
assert(ion_px_mm==1 and ion_py_mm==2 and ion_pz_mm==3 and ion_vx_mm==4 and ion_vy_mm==5 and ion_vz_mm==6)
"""
        with TemporaryDirectory() as temporary:
            root=Path(temporary);program=root/"callback.lua";program.write_text(script)
            result=subprocess.run([lua,str(program)],cwd=PROJECT.parents[1],capture_output=True,text=True,encoding="utf-8",timeout=20)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            lines=result.stdout.splitlines()
            self.assertEqual(len(lines),6)
            self.assertEqual(sum("phase=step" in line for line in lines),2)
            log=root/"raw.log";log.write_text(result.stdout)
            policy={"schema_version":1,"mode":"fixed_interval","interval_us":.1,"retention_class":"solver_review","reason":"fixture","output_budget_bytes":1}
            receipt=extract_trajectory_samples(log_path=log,output_path=root/"samples.csv",receipt_path=root/"receipt.json",recording_config=policy)
            self.assertEqual(receipt["samples_per_particle"],{20:4,80:2})

    def test_extract_keeps_actual_states_and_rejects_truncation(self):
        line = "MRTOF_TRAJECTORY ion=7 phase={phase} t_us={time} x_mm=1 y_mm=2 z_mm=3 vx_mm_us=4 vy_mm_us=5 vz_mm_us=6\n"
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            log, csv, receipt = root / "raw.log", root / "trajectory_samples.csv", root / "receipt.json"
            good = "".join(line.format(phase=phase, time=time) for phase, time in (("birth", 0), ("step", .004), ("terminal", .004)))
            log.write_text(good, encoding="utf-8")
            result = extract_trajectory_samples(log_path=log, output_path=csv, receipt_path=receipt)
            self.assertEqual(result["samples_per_particle"], {7: 3})
            self.assertIn("7,step,0.004,1,2,3,4,5,6", csv.read_text())
            native_contact = "".join(line.format(phase=phase, time=time) for phase, time in (("birth", 0), ("step", .004), ("step", .008), ("terminal", .004)))
            log.write_text(native_contact, encoding="utf-8")
            native = extract_trajectory_samples(log_path=log, output_path=csv, receipt_path=receipt)
            self.assertEqual(native["terminal_clock_backsteps"], [{"ion": 7, "backstep_us": .004}])
            for bad in ("", good.splitlines(True)[1] + good, good.rsplit("MRTOF_TRAJECTORY", 1)[0], good.replace("t_us=0.004", "t_us=nan")):
                log.write_text(bad, encoding="utf-8")
                with self.assertRaises(ValueError):
                    extract_trajectory_samples(log_path=log, output_path=csv, receipt_path=receipt)

    def test_real_lua_observation_is_off_by_default_and_does_not_mutate_state(self):
        lua = shutil.which("lua") or "C:/Program Files/SIMION-2020/lua.exe"
        if not Path(lua).exists() and shutil.which(lua) is None:
            self.skipTest("plain Lua unavailable")
        source = (PROJECT / "simion/mrtof_candidate.lua").read_text(encoding="utf-8")
        function = source[source.index("local function record_trajectory_sample"):source.index("local static_field_adjust")]
        for hook in ("record_trajectory_sample('birth', birth_time_us)", "record_trajectory_sample('step')", "record_trajectory_sample('terminal')"):
            self.assertIn(hook, source)
        script = """local operating_point={}; local printed={}
local function event_id() return 7 end
local function instrument_time_us() return 12.5 end
local print=function(line) printed[#printed+1]=line end
ion_px_mm=1;ion_py_mm=2;ion_pz_mm=3;ion_vx_mm=4;ion_vy_mm=5;ion_vz_mm=6
ion_time_step=.004;ion_time_of_flight=12.5;ion_splat=0
""" + function + """
record_trajectory_sample('birth');assert(#printed==0)
operating_point.trajectory_recording_enabled=true
for _,phase in ipairs({'birth','step','terminal'}) do record_trajectory_sample(phase) end
assert(#printed==3 and printed[2]:find('phase=step'))
assert(ion_time_step==.004 and ion_time_of_flight==12.5 and ion_splat==0)
assert(ion_px_mm==1 and ion_py_mm==2 and ion_pz_mm==3 and ion_vx_mm==4 and ion_vy_mm==5 and ion_vz_mm==6)
"""
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "recording.lua"
            path.write_text(script, encoding="utf-8")
            result = subprocess.run([lua, str(path)], cwd=PROJECT.parents[1], capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_cli_and_runner_use_same_recording_authority(self):
        import sys
        with TemporaryDirectory() as temporary:
            contract = Path(temporary) / "contract.json"
            contract.write_text(json.dumps({"simion": {}}), encoding="utf-8")
            result = subprocess.run([sys.executable, "-m", "projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial", "recording-config", "--contract", str(contract)], cwd=PROJECT.parents[1], capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsNone(json.loads(result.stdout))
        runner = (PROJECT.parents[1] / "integrations/workflows/oa_mr/execute.ps1").read_text(encoding="utf-8")
        self.assertIn("-RetentionClass $trajectoryRetentionClass -RetentionReason $trajectoryRetentionReason", runner)
        self.assertIn("$manifestOutputs+=@($trajectorySamples,$trajectorySampleReceipt)", runner)
        self.assertIn("'extract-trajectory','--log',$rawLog", runner)
        self.assertIn("'seal-stopped-payload'", runner)
        self.assertIn("$committedNewBytes+=[int64]$trajectoryRecording.output_budget_bytes", runner)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_complete_entry_status_waits_for_payload_seal(self):
        runner = (PROJECT.parents[1] / "integrations/workflows/oa_mr/execute.ps1").read_text(encoding="utf-8")
        start = runner.rindex("  try{\n  if($trajectoryPayloadNeedsSeal){")
        block = runner[start:runner.rindex("\n}")]
        for fail in (False, True):
            with self.subTest(fail=fail):
                command = """$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$trajectoryPayloadNeedsSeal=$true;$deferredHostCompletionNotification=$true;$terminalStatus='success'
$artifactRoot='root';$package=@{artifact_run_dir='run'};$projectId='mr';$trajectoryRetentionReason='review'
$RunId='fixture';$observed=@{status='bunch_observed'};$hostOutcome='failed'
$calls=[Collections.Generic.List[string]]::new()
function Write-Host {param($Object);$calls.Add([string]$Object)}
function Invoke-HostExecutionCompletionNotification {param($Outcome,$RunId);$calls.Add('notify:'+ $Outcome)}
function Remove-RunPackageExecutionAlias {param($Package);$calls.Add('alias_removed')}
"""
                command += "function Invoke-ProjectPython {param($Arguments);$calls.Add('seal');"
                command += "throw 'seal fixture failure'" if fail else "return"
                command += "}\n$caught=$false;try{\n" + block + "\n}catch{$caught=$true}\n"
                command += "@{calls=@($calls);caught=$caught;outcome=$hostOutcome}|ConvertTo-Json -Compress"
                result = subprocess.run(["pwsh", "-NoProfile", "-Command", command], cwd=PROJECT.parents[1], capture_output=True, text=True, encoding="utf-8", timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                observed = json.loads(result.stdout)
                self.assertEqual(observed["calls"][0], "seal")
                self.assertEqual(observed["caught"], fail)
                self.assertEqual(observed["outcome"], "failed" if fail else "success")
                self.assertEqual(observed["calls"][-2], "notify:failed" if fail else "notify:success")
                self.assertEqual(observed["calls"][-1], "alias_removed")
                self.assertIn("TRIAL=FAIL" if fail else "TRIAL=PASS", observed["calls"][1])


if __name__ == "__main__":
    unittest.main()
