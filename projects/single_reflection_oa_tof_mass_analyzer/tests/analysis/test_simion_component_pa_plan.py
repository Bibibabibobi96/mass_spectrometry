"""Software contracts for the governed component build boundary."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from projects.single_reflection_oa_tof_mass_analyzer.analysis.geometry_contract import derive_simion_geometry
from projects.single_reflection_oa_tof_mass_analyzer.analysis.simion_component_pa_plan import (
    compile_component_pa_plan, sum_component_commitments,
)


PROJECT = Path(__file__).resolve().parents[2]
REPO = PROJECT.parents[1]


class ComponentPaPlanTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="oatof_component_plan_")
        self.addCleanup(self.temporary.cleanup)
        self.executable = Path(self.temporary.name) / "simion.exe"
        self.executable.write_bytes(b"fixture executable identity only; never executed")
        self.contract = json.loads((PROJECT / "config/resolved_geometry.json").read_text(encoding="utf-8"))

    def plan(self, contract=None):
        return compile_component_pa_plan(
            contract or self.contract, repository_root=REPO, simion_exe=self.executable,
        )

    def test_only_supported_surface_none_components_publish_standalone(self):
        plan = self.plan()
        by_role = {item["role"]: item for item in plan["components"]}
        self.assertEqual({name for name, item in by_role.items() if item["cacheable"]},
                         {"accelerator", "reflectron"})
        for role in ("accelerator", "reflectron"):
            item = by_role[role]
            self.assertEqual(item["identity"]["surface"], "none")
            self.assertEqual(len(item["expected_files"]), len(item["response_ids"]) + 2)
            self.assertFalse(any(name.endswith(".pa0") for name in item["expected_files"]))
            self.assertTrue(all(not name.endswith(tuple(f".pa{n}" for n in item["response_ids"]))
                                for name in item["expected_files"]))
        for role in ("flight_tube", "detector"):
            self.assertEqual(by_role[role]["identity"]["surface"], "fractional")
            self.assertEqual(by_role[role]["expected_files"], [])
            self.assertIsNone(by_role[role]["cache_key"])
            self.assertGreater(by_role[role]["bytes"]["private_runtime"], 0)

    def test_operating_voltages_do_not_invalidate_geometry_response_basis(self):
        changed = deepcopy(self.contract)
        changed["electrodes_V"]["midgrid"] += 1
        before = [item["cache_key"] for item in self.plan()["components"]]
        after = [item["cache_key"] for item in self.plan(changed)["components"]]
        self.assertEqual(before, after)

    def test_execution_disk_reservation_does_not_change_field_identity(self):
        changed = deepcopy(self.contract)
        changed["artifact_capacity"] = {"comsol_bytes": 9 * 1024**3}
        self.assertEqual(self.plan(), self.plan(changed))

    def test_operating_values_are_provider_projection_outside_cache_identity(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.geometry_contract import resolve_physical_geometry
        physical = resolve_physical_geometry(self.contract)
        plan = {item["role"]: item for item in self.plan()["components"]}
        expected = physical["accelerator"]["electrical"]["operating_voltages_v"]
        self.assertEqual(list(plan["accelerator"]["operating_voltages_v"].values()),
                         [expected["repeller"], expected["grid1"], *expected["rings"],
                          expected["grid2"], expected["shield"]])
        self.assertEqual(plan["reflectron"]["operating_voltages_v"], {
            str(item["local_electrode_id"]): item["voltage_v"]
            for item in physical["simion"]["reflectron"]["electrodes"]
        })

    def test_radius_change_invalidates_reflectron_without_rebuilding_accelerator(self):
        changed = deepcopy(self.contract)
        changed["geometry_mm"]["flight_tube_r"] += 10
        changed["derived"] = derive_simion_geometry(
            geometry=changed["geometry_mm"], coordinate=changed["coordinate_convention"],
            build=changed["simion_geometry_build"], marker=changed["simion_detector_marker"],
            source=changed["particle_source"],
        )
        before = {item["role"]: item for item in self.plan()["components"]}
        after = {item["role"]: item for item in self.plan(changed)["components"]}
        self.assertEqual(before["accelerator"]["cache_key"], after["accelerator"]["cache_key"])
        self.assertNotEqual(before["reflectron"]["cache_key"], after["reflectron"]["cache_key"])
        self.assertGreater(after["reflectron"]["grid"]["dimensions"][1],
                           before["reflectron"]["grid"]["dimensions"][1])

    def test_capacity_deduplicates_only_publication_not_private_runtime(self):
        plan = self.plan()
        extra_runtime = plan["evidence_allowance_bytes"] + sum(
            item["bytes"]["private_runtime"] for item in plan["components"])
        self.assertEqual(sum_component_commitments([plan, plan]),
                         plan["committed_new_bytes"] + extra_runtime)
        changed = deepcopy(plan)
        changed["components"][0]["bytes"]["native_staging"] = -1
        with self.assertRaisesRegex(ValueError, "invalid bytes"):
            sum_component_commitments([changed])

    def test_dimensions_come_from_the_existing_provider_projection(self):
        plan = self.plan()
        instances = {item["name"].removesuffix(".pa0"): item
                     for item in self.contract["derived"]["simion_instances"]}
        for item in plan["components"]:
            self.assertEqual(item["grid"]["dimensions"],
                             [instances[item["stem"]][axis] for axis in ("nx", "ny", "nz")])


if __name__ == "__main__":
    unittest.main()
