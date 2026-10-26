"""Execute the production pure Lua kernel against independent analytic vectors.

No SIMION process, PA or trajectory integrator is involved. Straight segment
intersections do not certify curved solver-step trajectories.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


KERNEL = Path(__file__).resolve().parents[2] / "simion/ip_prism_lens_contact.lua"
LUA = shutil.which("lua") or "C:/Program Files/SIMION-2020/lua.exe"
HARNESS = r'''
local kernel=assert(dofile(arg[1]))
local function rod(id,a,b,r)
 return {namespace='quadrupole_lens',electrode_id=id,
  solids={{shape='cylinder3d',endpoints_mm={a,b},radius_mm=r}}}
end
local function check(rods,a,b,t,id,face)
 local actual,actual_id,actual_face=kernel.first_contact(rods,a,b)
 if t==nil then assert(actual==nil,'unexpected contact '..tostring(actual));return end
 assert(math.abs(actual-t)<=2e-12,'fraction '..tostring(actual)..' expected '..tostring(t))
 assert(actual_id==id,'rod ID mismatch')
 assert(actual_face==face,'face '..tostring(actual_face)..' expected '..tostring(face))
end
local z=rod(4,{0,0,-1},{0,0,1},1)
SCENARIO
print('FINITE_ROD_CONTACT=PASS')
'''


@unittest.skipUnless(Path(LUA).is_file(), "Plain Lua interpreter required; never launches SIMION")
class FiniteRodContactTests(unittest.TestCase):
    """Independent expected intersections; no Python geometry implementation."""

    def run_vector(self, scenario: str) -> None:
        """Run one analytic scenario using a new plain Lua process."""
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "contact_test.lua"
            script.write_text(HARNESS.replace("SCENARIO", scenario), encoding="utf-8")
            result = subprocess.run(
                [LUA, str(script), str(KERNEL)], capture_output=True, text=True,
                check=False, cwd=directory, timeout=20,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("FINITE_ROD_CONTACT=PASS", result.stdout)

    def test_swept_side_both_endpoints_outside(self) -> None:
        self.run_vector("check({z},{-2,0,0},{2,0,0},.25,4,'side')")

    def test_caps_axial_parallel_and_reversed_axis(self) -> None:
        self.run_vector("""
check({z},{0,0,-3},{0,0,3},1/3,4,'cap_start')
check({z},{0,0,3},{0,0,-3},1/3,4,'cap_end')
check({z},{2,0,-3},{2,0,3},nil)
local reverse=rod(7,{0,0,1},{0,0,-1},1)
check({reverse},{0,0,-3},{0,0,3},1/3,7,'cap_end')
""")

    def test_tangent_endpoint_and_cap_rim(self) -> None:
        self.run_vector("""
check({z},{-2,1,0},{2,1,0},.5,4,'side')
check({z},{-2,0,0},{-1,0,0},1,4,'side')
check({z},{1,0,-2},{1,0,0},.5,4,'cap_start')
check({z},{-2,1+1e-8,0},{2,1+1e-8,0},nil)
""")

    def test_initial_inside_boundary_and_zero_segment(self) -> None:
        self.run_vector("""
check({z},{0,0,0},{2,0,0},0,4,'initial_inside')
check({z},{0,0,-1},{0,0,-2},0,4,'cap_start')
check({z},{1,0,0},{2,0,0},0,4,'side')
check({z},{0,0,0},{0,0,0},0,4,'initial_inside')
check({z},{2,0,0},{2,0,0},nil)
check({},{0,0,0},{0,0,0},nil)
""")

    def test_arbitrary_axis_and_negative_world_rod(self) -> None:
        self.run_vector("""
local x=rod(9,{-3,2,4},{-1,2,4},.5)
check({x},{-4,2,4},{0,2,4},.25,9,'cap_start')
check({x},{-2,0,4},{-2,4,4},.375,9,'side')
local diagonal=rod(10,{0,0,0},{2,2,2},.25)
check({diagonal},{-1,-1,-1},{3,3,3},.25,10,'cap_start')
""")

    def test_earliest_and_deterministic_coincident_rods(self) -> None:
        self.run_vector("""
local later=rod(1,{3,0,-1},{3,0,1},1)
check({later,z},{-2,0,0},{5,0,0},1/7,4,'side')
local same=rod(2,{0,0,-1},{0,0,1},1)
check({z,same},{-2,0,0},{2,0,0},.25,2,'side')
check({same,z},{-2,0,0},{2,0,0},.25,2,'side')
""")

    def test_actual_id3_interior_and_cap_semantics(self) -> None:
        self.run_vector("""
local q2=rod(1007,{0,-53.4,-31.5},{0,-53.4,-28.5},.2)
local actual={.012733738608599223,-53.570183130323812,-31.426238625456513}
check({q2},actual,actual,0,1007,'initial_inside')
-- The radial-only slab gap is negative at this cap point, but actual first
-- contact is the cap itself: no claimed negative penetration depth.
check({q2},{0,-53.55,-32},{0,-53.55,-31},.5,1007,'cap_start')
check({q2},{0,-53.55,-31.5},{0,-53.55,-31.5},0,1007,'cap_start')
""")

    def test_near_parallel_long_segment_and_no_radius_padding(self) -> None:
        self.run_vector("""
check({z},{1+1e-9,0,-2},{1+1e-9,0,2},nil)
check({z},{0,0,-1000000},{0,0,1000000},.4999995,4,'cap_start')
check({z},{1.0001,0,-2},{1.0001+1e-15,0,2},nil)
""")

    def test_invalid_numeric_and_degenerate_geometry(self) -> None:
        self.run_vector("""
assert(not pcall(kernel.first_contact,{z},{0/0,0,0},{1,0,0}))
assert(not pcall(kernel.first_contact,{rod(1,{0,0,0},{0,0,0},1)},{0,0,0},{1,0,0}))
assert(not pcall(kernel.first_contact,{rod(1,{0,0,0},{0,0,1},-1)},{0,0,0},{1,0,0}))
""")


if __name__ == "__main__":
    unittest.main()
