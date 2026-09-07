"""Opt-in native regression: terminate callbacks inside and outside a PA.

Official API: https://simion.com/info/workbench_program_extensions.html
The installed help and examples/mfield_adjust/magnetic.lua date
sim_segment_global to 8.2EA-20170214. This test deliberately does NOT call
simion.early_access: the selected SIMION 2020 release must support it directly.
N=2 is a dedicated lifecycle fixture, not a Candidate statistical cohort.
All new files (<1 MiB total) belong to a TemporaryDirectory and are cleaned.
The repository one-instance seed and its companions are loaded read-only;
the sole instance is immediately rebound before saving only a temporary IOB.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from common.simion.particle_source import render_standard_beams


REPOSITORY = Path(__file__).resolve().parents[4]
SEED = REPOSITORY / "common/simion/assets/iob_instance_seeds/1_instance_seed.iob"
GEM = """pa_define(11,11,11,planar,none,electrostatic,,1,1,1,surface=none)
e(0) { box3D(8,0,0,10,10,10) }
"""
BUILDER = r"""local seed, pa_path, output = assert(arg[1]), assert(arg[2]), assert(arg[3])
local wb = assert(simion.wb)
wb:load(seed)
assert(#wb.instances == 1, 'expected the canonical one-instance seed')
local instance = wb.instances[1]
instance.pa:load(pa_path)
-- SIMION stores the basename when the PA lives in its current directory.
assert(instance.pa.filename == pa_path:match('[^/\\]+$'),
  'fixture PA filename did not replace seed PA: ' .. instance.pa.filename)
assert(instance.pa.nx == 11 and instance.pa.ny == 11 and instance.pa.nz == 11)
instance:_debug_update_size()
instance.x, instance.y, instance.z = 0, 0, 0
instance.az, instance.el, instance.rt, instance.scale = 0, 0, 0, 1
wb.bounds = {xl=-10, yl=-10, zl=-10, xr=20, yr=20, zr=20}
assert(output ~= seed and not output:find('iob_seed_placeholder', 1, true))
wb:save(output)
print('LIFECYCLE_FIXTURE_BUILD PASS')
"""
PROGRAM = """simion.workbench_program()
sim_segment_global = GLOBAL_VALUE
local terminals = 0
function segment.initialize()
  print(string.format('LIFECYCLE_START id=%d instance=%d', ion_number, ion_instance))
end
function segment.terminate()
  terminals = terminals + 1
  print(string.format('LIFECYCLE_TERMINAL id=%d instance=%d x=%.12g',
    ion_number, ion_instance, ion_px_mm))
end
function segment.terminate_run()
  print(string.format('LIFECYCLE_DONE ions=%d terminals=%d', sim_ions_count, terminals))
end
"""


@unittest.skipUnless(os.environ.get("SIMION_EXE"), "native SIMION executable not selected")
class NativeEventLifecycleTest(unittest.TestCase):
    """Use natural electrode and workbench-boundary termination, never fake events."""

    @classmethod
    def setUpClass(cls) -> None:
        if not os.environ.get("MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID"):
            raise RuntimeError("native lifecycle regression requires the host execution lease")
        cls.executable = Path(os.environ["SIMION_EXE"]).resolve(strict=True)

    def native(self, folder: Path, *arguments: str) -> str:
        result = subprocess.run(
            [str(self.executable), "--nogui", *arguments], cwd=folder,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=300, check=False,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        return output

    def test_global_segments_preserve_terminal_ids_outside_pa(self) -> None:
        # The first ion flies +x into a grounded slab; the second flies -x out
        # of the PA and then terminates at the larger Workbench boundary.
        beams = [dict(tob=0, mass=100, charge=1, x=5, y=5, z=5, ke=1,
                      az=az, el=0, cwf=1, color=1) for az in (0, 180)]
        cohort = render_standard_beams(beams).encode("utf-8")
        seed_digest = hashlib.sha256(SEED.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory(prefix="mrtof-native-event-test-") as temporary:
            folder = Path(temporary)
            gem, pa = folder / "lifecycle.gem", folder / "lifecycle.pa#"
            builder, particles = folder / "build.lua", folder / "source.fly2"
            gem.write_text(GEM, encoding="utf-8")
            builder.write_text(BUILDER, encoding="utf-8")
            particles.write_bytes(cohort)
            self.native(folder, "gem2pa", str(gem), str(pa))
            outcomes = {}
            for enabled in (0, 1):
                iob = folder / f"segments_{enabled}.iob"
                built = self.native(folder, "lua", str(builder), str(SEED), str(pa), str(iob))
                self.assertIn("LIFECYCLE_FIXTURE_BUILD PASS", built)
                # wb:save can write same-basename sidecars, so set the exact
                # controlled program after save; --particles selects one cohort.
                iob.with_suffix(".lua").write_text(
                    PROGRAM.replace("GLOBAL_VALUE", str(enabled)), encoding="utf-8")
                output = self.native(folder, "fly", "--retain-trajectories", "0",
                                     "--particles", str(particles), "--programs", "1", str(iob))
                self.assertEqual(re.findall(r"LIFECYCLE_START id=(\d+) instance=1", output),
                                 ["1", "2"], output)
                matches = re.findall(r"LIFECYCLE_TERMINAL id=(\d+) instance=(\d+) x=([^\s]+)", output)
                outcomes[enabled] = [(int(i), int(instance), float(x)) for i, instance, x in matches]
                self.assertEqual(re.findall(r"LIFECYCLE_DONE ions=(\d+) terminals=(\d+)", output),
                                 [("2", str(len(matches)))], output)
                self.assertEqual(particles.read_bytes(), cohort)
                print(f"SIMION_NATIVE_LIFECYCLE global={enabled} terminals={outcomes[enabled]}")
            self.assertEqual([row[0] for row in outcomes[0]], [1])
            self.assertEqual([row[0] for row in outcomes[1]], [1, 2])
            self.assertEqual(outcomes[0], outcomes[1][:1], "inside-PA control changed")
            self.assertEqual(outcomes[1][0][1], 1)
            self.assertGreaterEqual(outcomes[1][0][2], 7)
            self.assertEqual(outcomes[1][1][1], 0)
            self.assertLess(outcomes[1][1][2], 0)
            total_bytes = sum(path.stat().st_size for path in folder.rglob("*") if path.is_file())
            self.assertLess(total_bytes, 1024 * 1024, "lifecycle fixture exceeds 1 MiB budget")
            self.assertEqual(hashlib.sha256(SEED.read_bytes()).hexdigest(), seed_digest)
            print(f"SIMION_NATIVE_LIFECYCLE PASS fixture_bytes={total_bytes} "
                  f"cohort_sha256={hashlib.sha256(cohort).hexdigest()}")
        self.assertFalse(folder.exists(), "test-owned temporary files were not cleaned")


if __name__ == "__main__":
    unittest.main()
