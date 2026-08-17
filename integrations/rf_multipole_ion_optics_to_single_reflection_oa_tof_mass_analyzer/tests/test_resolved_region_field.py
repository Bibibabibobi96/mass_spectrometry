from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest

from common.contracts.machine_contracts import validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.resolved_region_field import (
    FULL_ID,
    THREE_ZONE_PROFILE_ID,
    THREE_ZONE_TOPOLOGY_ID,
    build_resolved_region_field_contract,
    resolved_region_field_hook_lua,
    validate_resolved_region_field_contract,
)


ROOT = Path(__file__).resolve().parents[3]
GEOMETRY = ROOT / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json"
SIMION = Path(r"C:\Program Files\SIMION-2020\simion.exe")


class ResolvedRegionFieldTests(unittest.TestCase):
    THREE_ZONE_TOPOLOGY = {
        "topology_id": THREE_ZONE_TOPOLOGY_ID,
        "planes_global_z_mm": {
            "repeller": -20.0,
            "intermediate1": -16.75,
            "intermediate2": -11.65,
            "exit": 0.25,
        },
        "potentials_v": {
            "repeller": 2000.0,
            "intermediate1": 1750.0,
            "intermediate2": 1450.0,
            "exit": 0.0,
        },
    }

    def _build(self, profile_id: str) -> dict:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "resolved.json"
            return build_resolved_region_field_contract(GEOMETRY, output, profile_id)

    def _build_three_zone(self) -> dict:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "resolved.json"
            return build_resolved_region_field_contract(
                GEOMETRY,
                output,
                THREE_ZONE_PROFILE_ID,
                accelerator_topology=self.THREE_ZONE_TOPOLOGY,
            )

    def test_rr_ri_ir_ii_are_one_five_region_contract(self) -> None:
        expected = {
            "accelerator_real_pa": ("real_pa_field", "real_pa_field"),
            "accelerator_ideal_stage1_real_stage2": ("analytic_ideal_field", "real_pa_field"),
            "accelerator_real_stage1_ideal_stage2": ("real_pa_field", "analytic_ideal_field"),
            "accelerator_ideal_stage1_stage2_real_reflectron": ("analytic_ideal_field", "analytic_ideal_field"),
        }
        for profile_id, accelerator in expected.items():
            contract = self._build(profile_id)
            modes = contract["semantic"]["region_modes"]
            self.assertEqual(tuple(modes.values())[:2], accelerator)
            self.assertEqual(tuple(modes.values())[2:], ("real_pa_field",) * 3)
            validate_schema(contract, "rf_oatof_resolved_region_field_contract.schema.json")

    def test_full_ideal_has_no_real_pa_region_or_blending(self) -> None:
        contract = self._build(FULL_ID)
        self.assertNotIn("real_pa_field", contract["semantic"]["region_modes"].values())
        self.assertFalse(contract["semantic"]["real_pa_field_blending_allowed"])
        lua = resolved_region_field_hook_lua(contract)
        self.assertNotIn("bore", lua.lower())
        self.assertIn("analytic_field", contract["semantic"]["effective_domain"]["transverse"])
        self.assertIn("error('particle escaped resolved region-field", lua)

    def test_bore_fallback_or_real_pa_blending_fails_closed(self) -> None:
        contract = self._build(FULL_ID)
        invalid = copy.deepcopy(contract)
        invalid["semantic"]["effective_domain"]["transverse"] = "bore_fallback_to_real_pa"
        from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.resolved_region_field import semantic_sha256
        invalid["semantic_sha256"] = semantic_sha256(invalid["semantic"])
        with self.assertRaisesRegex(ValueError, "cannot silently fall back"):
            validate_resolved_region_field_contract(invalid)
        invalid = copy.deepcopy(contract)
        invalid["semantic"]["real_pa_field_blending_allowed"] = True
        invalid["semantic_sha256"] = semantic_sha256(invalid["semantic"])
        with self.assertRaisesRegex(ValueError, "prohibit real-PA blending"):
            validate_resolved_region_field_contract(invalid)

    def test_semantic_sha_is_path_free_and_stable(self) -> None:
        one = self._build(FULL_ID)
        two = self._build(FULL_ID)
        self.assertEqual(one["semantic_sha256"], two["semantic_sha256"])
        self.assertFalse(any(key == "path" for key in one["semantic"]))

    def test_legacy_v1_output_is_byte_and_semantic_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "resolved.json"
            contract = build_resolved_region_field_contract(
                GEOMETRY, output, "accelerator_real_pa"
            )
            file_digest = hashlib.sha256(output.read_bytes()).hexdigest().upper()
        self.assertEqual(contract["schema_version"], 1)
        self.assertEqual(
            file_digest,
            "B566449C2F889CC0BB7A9ECC839E2A08A1288A89781F82FD3E550E56A957E270",
        )
        self.assertEqual(
            contract["semantic_sha256"],
            "B5217121AB655B773B24F359AEA18C527FEF7ECD1DF2B0E06D225E23868F1976",
        )

    def test_three_zone_v2_uses_explicit_new_electrode_and_region_identity(self) -> None:
        contract = self._build_three_zone()
        self.assertEqual(contract["schema_version"], 2)
        semantic = contract["semantic"]
        self.assertEqual(
            set(semantic["accelerator_topology"]["planes_global_z_mm"]),
            {"repeller", "intermediate1", "intermediate2", "exit"},
        )
        self.assertEqual(
            tuple(semantic["region_modes"]),
            (
                "accelerator_zone1",
                "accelerator_zone2",
                "accelerator_zone3",
                "drift",
                "reflectron_stage1",
                "reflectron_stage2",
            ),
        )
        self.assertNotIn("grid2", semantic["planes_mm"])
        self.assertNotIn("accelerator_stage2", semantic["region_modes"])
        validate_schema(contract, "rf_oatof_resolved_region_field_contract.schema.json")
        lua = resolved_region_field_hook_lua(contract)
        self.assertIn("_intermediate1", lua)
        self.assertIn("_intermediate2", lua)
        self.assertNotIn("grid1", lua)
        self.assertNotIn("grid2", lua)

    def test_three_zone_topology_is_explicit_and_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "resolved.json"
            with self.assertRaisesRegex(ValueError, "requires accelerator_topology"):
                build_resolved_region_field_contract(
                    GEOMETRY, output, THREE_ZONE_PROFILE_ID
                )
            invalid = copy.deepcopy(self.THREE_ZONE_TOPOLOGY)
            invalid["planes_global_z_mm"]["grid2"] = invalid["planes_global_z_mm"].pop(
                "exit"
            )
            with self.assertRaisesRegex(ValueError, "exactly"):
                build_resolved_region_field_contract(
                    GEOMETRY,
                    output,
                    THREE_ZONE_PROFILE_ID,
                    accelerator_topology=invalid,
                )
            invalid = copy.deepcopy(self.THREE_ZONE_TOPOLOGY)
            invalid["potentials_v"]["intermediate2"] = 1800.0
            with self.assertRaisesRegex(ValueError, "decrease strictly"):
                build_resolved_region_field_contract(
                    GEOMETRY,
                    output,
                    THREE_ZONE_PROFILE_ID,
                    accelerator_topology=invalid,
                )
        invalid_contract = copy.deepcopy(self._build_three_zone())
        invalid_contract["semantic"]["fields_V_per_mm"]["accelerator_zone3"] *= -1
        from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.resolved_region_field import semantic_sha256
        invalid_contract["semantic_sha256"] = semantic_sha256(
            invalid_contract["semantic"]
        )
        with self.assertRaisesRegex(ValueError, "field sign or magnitude differs"):
            validate_resolved_region_field_contract(invalid_contract)

    @unittest.skipUnless(SIMION.is_file(), "official SIMION Lua CLI unavailable")
    def test_callback_neutral_override_preserves_real_region_base_write_set(self) -> None:
        real_hook = resolved_region_field_hook_lua(self._build("accelerator_real_pa"))
        ideal_hook = resolved_region_field_hook_lua(
            self._build("accelerator_ideal_stage1_real_stage2"), prefix="ideal"
        )
        for source in (real_hook, ideal_hook):
            for forbidden in ("segment.", "simion.wb", "adj_elect", "ion_time_of_flight"):
                self.assertNotIn(forbidden, source)
        script = f"""
local real=(function()\n{real_hook}\nend)()
local ideal=(function()\n{ideal_hook}\nend)()
local base={{replace_all=false,dvoltsx_gu=7}}
local common={{z_mm=-18,instance_id=3,instance_dx_mm=0.25,
  instance_dz_mm=0.05,instance_scale=1,pulse_active=true}}
assert(real.apply(base,common)==base,'real-PA region changed project base result')
local inactive={{z_mm=-18,instance_id=3,instance_dx_mm=0.25,
  instance_dz_mm=0.05,instance_scale=1,pulse_active=false}}
assert(ideal.apply(base,inactive)==base,'inactive override changed project base result')
local changed=ideal.apply(base,common)
assert(changed~=base and changed.replace_all==true,
  'analytic region did not replace the base write set')
assert(changed.dvoltsx_gu==0 and changed.dvoltsy_gu==0 and
  type(changed.dvoltsz_gu)=='number','analytic accelerator write set is incomplete')
print('RESOLVED_REGION_FIELD_HOOK=PASS')
"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "test_region_hook.lua"
            path.write_text(script, encoding="utf-8", newline="\n")
            result = subprocess.run(
                [str(SIMION), "--nogui", "--noprompt", "lua", str(path)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("RESOLVED_REGION_FIELD_HOOK=PASS", result.stdout)

    @unittest.skipUnless(SIMION.is_file(), "official SIMION Lua CLI unavailable")
    def test_three_zone_lua_boundaries_and_field_sign_fail_closed(self) -> None:
        hook = resolved_region_field_hook_lua(self._build_three_zone(), prefix="three")
        script = f"""
local three=(function()\n{hook}\nend)()
local base={{replace_all=false,dvoltsx_gu=7}}
local function state(z) return {{z_mm=z,instance_id=3,instance_dx_mm=0.25,
  instance_dz_mm=0.05,instance_scale=1,pulse_active=true}} end
local zone1=three.apply(base,state(-19.9))
local zone2=three.apply(base,state(-16.75))
local zone3=three.apply(base,state(-11.65))
assert(zone1.dvoltsz_gu<0 and zone2.dvoltsz_gu<0 and zone3.dvoltsz_gu<0,
  'positive-ion accelerating field derivative sign differs')
assert(math.abs(zone1.dvoltsz_gu+3.8461538461538)<1e-12,
  'zone1 boundary selected the wrong field')
assert(math.abs(zone2.dvoltsz_gu+2.9411764705882)<1e-12,
  'intermediate1 boundary did not select zone2')
assert(math.abs(zone3.dvoltsz_gu+6.0924369747899)<1e-12,
  'intermediate2 boundary did not select zone3')
assert(three.apply(base,state(0.25))==base,'exit boundary did not select drift')
local ok=pcall(function() three.apply(base,state(-20.01)) end)
assert(not ok,'out-of-domain trajectory did not fail closed')
print('THREE_ZONE_REGION_FIELD_HOOK=PASS')
"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "test_three_zone_region_hook.lua"
            path.write_text(script, encoding="utf-8", newline="\n")
            result = subprocess.run(
                [str(SIMION), "--nogui", "--noprompt", "lua", str(path)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("THREE_ZONE_REGION_FIELD_HOOK=PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
