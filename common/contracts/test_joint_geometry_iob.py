"""Actual joint-role IOB Lua using inert fake PA objects, no SIMION."""
from __future__ import annotations

import copy
from pathlib import Path
import subprocess
import tempfile
import unittest

from common.contracts.test_dual_cone_iob import HARNESS, LUA
from msplatform.backends.simion.resources import native_resource_path
from msplatform.backends.simion.source import lua_value


@unittest.skipUnless(LUA.is_file(), "plain Lua unavailable; no native fallback")
class JointGeometryIobTests(unittest.TestCase):
    def test_real_joint_roles_build_reopen_and_reject_wrong_slot_count(self):
        for role, count, marker in (("rf_ip_geometry_iob_build", 1, "RF_IP_GEOMETRY_IOB"),
                                    ("oa_mr_geometry_iob_build", 3, "OA_MR_GEOMETRY_IOB")):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                seed = root / "seed.iob"; seed.write_bytes(b"inert-seed")
                output = root / "instrument.iob"
                control = root / "empty.fly2"; control.write_text("particles{coordinates=0,}")
                rows = []
                for index in range(1, count + 1):
                    raw = root / f"body{index}.pa#";raw.write_bytes(b"inert-raw")
                    surface = root / f"body{index}.pa-surf";surface.write_bytes(b"inert-surface")
                    witness = root / f"body{index}.csv";witness.write_text("0,0,0,.25,nil,nil\n")
                    rows.append(dict(role=f"body{index}", instance_index=index, priority_number=index,
                        path=str(raw), fractional_surface=str(surface), surface_witnesses=str(witness), response_ids=[1],
                        grid=dict(nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1),
                        rotation=[[1,0,0],[0,1,0],[0,0,1]],
                        placement=dict(x_mm=0,y_mm=0,z_mm=0,az_deg=0,el_deg=0,rt_deg=0,scale=1),
                        physical_samples=[dict(gu=[0,0,0],metal=True,electrode_id=1),dict(gu=[1,0,0],metal=False)]))
                spec = dict(schema_version=1, role=role, instances=rows, seed_iob=str(seed), output_iob=str(output),
                            bootstrap_paths=[str(root/f"iob_seed_placeholder_{i:02d}.pa0") for i in range(1,count+1)],
                            empty_particle_control=str(control))
                request=root/"spec.lua"; script=root/"harness.lua"; native_path=root/"path.lua"
                native_path.write_text("return function(path)return path end")
                code=(HARNESS.replace("getmetatable(instances).__len=function()return 1 end", "getmetatable(instances).__len=function()return #spec.instances end")
                      .replace(" local row=spec.instances[1]\n local path=mode:match('^verify')and row.path or spec.bootstrap_paths[1]", " for i,row in ipairs(spec.instances) do\n local path=mode:match('^verify')and row.path or spec.bootstrap_paths[i]")
                      .replace(" slots[1]=item\nend", " slots[i]=item\n end\nend")
                      .replace("arg={arg[1],mode,arg[5]}", "local resources=arg[5];arg={arg[1],mode,arg[4]}")
                      .replace("arg[3]..'/iob_core.lua'", "resources..'/iob_core.lua'")
                      .replace("if mode=='build'or mode=='verify'then", "if failure=='direct' then assert(loadfile(resources..'/iob_core.lua'))()(spec,mode,function(path)return path end) elseif mode=='build'or mode=='verify'then"))
                script.write_text(code)
                resources=native_resource_path("iob_core.lua").parent
                def call(mode, value, failure="valid"):
                    request.write_text("return "+lua_value(value))
                    return subprocess.run([str(LUA),str(script),str(request),mode,failure,str(native_path),str(resources)],
                                          cwd=root,capture_output=True,text=True,timeout=30)
                built=call("build_geometry",spec)
                self.assertEqual(built.returncode,0,built.stderr);self.assertIn(marker+"=PASS",built.stdout)
                reopened=call("verify_geometry",spec)
                self.assertEqual(reopened.returncode,0,reopened.stderr);self.assertIn(marker+"_REOPEN=PASS",reopened.stdout)
                bad=copy.deepcopy(spec);bad["instances"] = bad["instances"][:-1]
                refused=call("verify_geometry",bad)
                self.assertNotEqual(refused.returncode,0)
                expected_count = ("RF–IP geometry requires one actual PA instance" if count == 1
                                  else "OA–MR geometry requires three actual PA instances")
                self.assertIn(expected_count, refused.stderr)
                expected_boundary = ("RF–IP tracking and fields workbench unsupported" if count == 1
                                     else "OA–MR geometry only; model and fields unsupported")
                unsupported_modes = ("build_fields", "build") if count == 1 else ("build_model", "build_fields", "build")
                for mode in unsupported_modes:
                    with self.subTest(role=role, unsupported_mode=mode):
                        unsupported = call(mode, spec, failure="direct")
                        self.assertNotEqual(unsupported.returncode, 0)
                        self.assertIn(expected_boundary, unsupported.stderr)


if __name__ == "__main__":
    unittest.main()
