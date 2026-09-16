from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from common.simion.native_fast_adjust_operating_pa_cache import (
    canonical_native_operating_pa_cache_key,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.native_operating_pa_family import (
    STATE_OUTPUT_SUFFIXES,
    BOUNDARY_MASK_POLICY_ID,
    export_receipt_path,
    operating_members,
    resolve_identity,
    verify_export_receipts,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.standalone_field_bank import (
    MODE_IDS,
)


class NativeOperatingPAFamilyAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.exporter = Path(self.temporary.name) / "export.lua"
        self.exporter.write_text("-- frozen exporter\n", encoding="utf-8")
        self.states = {
            state: {mode_id: float(mode_id + offset) for mode_id in MODE_IDS}
            for offset, state in enumerate(STATE_OUTPUT_SUFFIXES)
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_members_have_three_deterministic_complete_mode_tables(self) -> None:
        members = operating_members("accelerator_main", self.states)
        self.assertEqual(
            {member["output_name"] for member in members},
            {
                "accelerator_main.carrier_off.pa",
                "accelerator_main.pulse_delta.pa",
                "accelerator_main.rf_differential.pa",
            },
        )
        for member in members:
            self.assertEqual(
                [entry["electrode_id"] for entry in member["electrode_voltages_v"]],
                list(MODE_IDS),
            )

    def test_identity_binds_family_state_and_exporter(self) -> None:
        identity = resolve_identity(
            role="accelerator_main",
            source_family_role="simion_single_flight_accelerator_main_pa_cache",
            source_family_cache_key="a" * 64,
            controller_basename="accelerator_main.pa0",
            mode_states=self.states,
            exporter=self.exporter,
        )
        original = canonical_native_operating_pa_cache_key(identity)
        changed_states = deepcopy(self.states)
        changed_states["pulse_delta"][40] += 0.25
        changed = resolve_identity(
            role="accelerator_main",
            source_family_role="simion_single_flight_accelerator_main_pa_cache",
            source_family_cache_key="a" * 64,
            controller_basename="accelerator_main.pa0",
            mode_states=changed_states,
            exporter=self.exporter,
        )
        self.assertNotEqual(original, canonical_native_operating_pa_cache_key(changed))
        self.assertEqual(
            BOUNDARY_MASK_POLICY_ID, "physical_geometry_boundary_flags_v1"
        )

    def test_incomplete_or_extra_state_is_rejected(self) -> None:
        missing = deepcopy(self.states)
        del missing["carrier_off"][43]
        with self.assertRaisesRegex(ValueError, "36 through 43"):
            operating_members("frontend", missing)
        extra = deepcopy(self.states)
        extra["unexpected"] = {mode_id: 0.0 for mode_id in MODE_IDS}
        with self.assertRaisesRegex(ValueError, "exactly three"):
            operating_members("frontend", extra)

    def test_export_verification_binds_boundary_mask_receipts_and_output_hashes(self) -> None:
        identity = resolve_identity(
            role="accelerator_main",
            source_family_role="simion_single_flight_accelerator_main_pa_cache",
            source_family_cache_key="a" * 64,
            controller_basename="accelerator_main.pa0",
            mode_states=self.states,
            exporter=self.exporter,
        )
        root = Path(self.temporary.name)
        for member in identity["members"]:
            output = root / member["output_name"]
            output.write_bytes((output.name + "\n").encode())
            export_receipt_path(output).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "role": "simion_fast_adjusted_standalone_pa_export",
                        "policy_id": BOUNDARY_MASK_POLICY_ID,
                        "status": "pass",
                        "potential_operation": "unchanged_official_electrode_setter",
                        "source_controller_basename": "accelerator_main.pa0",
                        "physical_template_basename": "accelerator_main.pa#",
                        "output_basename": output.name,
                        "adjustable_electrode_count": len(MODE_IDS),
                        "boundary_points": 98,
                        "physical_boundary_flags": 14,
                        "cleared_synthetic_boundary_flags": 84,
                        "copy_mode": "native_copy",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
        verified = verify_export_receipts(identity, root)
        self.assertEqual(verified["boundary_mask_policy_id"], BOUNDARY_MASK_POLICY_ID)
        self.assertEqual(len(verified["records"]), 3)
        self.assertTrue(all(record["output_bytes"] > 0 for record in verified["records"]))
        receipt = export_receipt_path(root / identity["members"][0]["output_name"])
        changed = json.loads(receipt.read_text(encoding="utf-8"))
        changed["policy_id"] = "unsafe_policy"
        receipt.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "policy_id differs"):
            verify_export_receipts(identity, root)


if __name__ == "__main__":
    unittest.main()
