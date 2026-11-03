"""Provider voltage publication matches the existing analyzer Python plan."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_electrical import (
    linear_ring_electrode_voltages, resolve_accelerator_electrical_design,
)
from projects.single_reflection_oa_tof_mass_analyzer.tests.analysis.test_assembly_interface import candidate_300mm_fixture

PROJECT = Path(__file__).resolve().parents[2]


def two_zone_fixture():
    return json.loads((PROJECT / "config/resolved_geometry.json").read_text(encoding="utf-8"))


def three_zone_fixture():
    resolved = candidate_300mm_fixture()
    resolved["electrodes_V"] = dict(repeller=2140.,grid1=1860.,intermediate2=372.96685170832035,
                                   grid2=0.,shield=0.)
    return resolved


class AcceleratorElectricalTests(unittest.TestCase):
    def test_two_zone_original_python_plan_golden_and_no_source_authority(self):
        resolved = two_zone_fixture()
        before = copy.deepcopy(resolved)
        design = resolve_accelerator_electrical_design(resolved,variant_id="two_zone_square", schema_version=1)
        self.assertEqual(resolved,before)
        self.assertEqual(design["frame_id"],"oatof_global")
        self.assertEqual(design["operating_voltages_v"],dict(repeller=2240.,grid1=1760.,grid2=0.,
            shield=0.,rings=[1466.6666666666665,1173.3333333333333,880.,586.6666666666665,293.33333333333326]))
        self.assertEqual(design["planes_z_mm"],dict(repeller=-19.92918680341103,
            grid1=-16.92918680341103,grid2=-.12918680341102995))
        self.assertNotIn("intermediate2",design["operating_voltages_v"])
        self.assertNotIn("off_voltages_v",design)
        resolved["particle_source"] = {"this_source_is_not_a_voltage_authority":float("nan")}
        self.assertEqual(resolve_accelerator_electrical_design(resolved,variant_id="two_zone_square", schema_version=1),design)

    def test_three_zone_300mm_twenty_actual_ring_positions_original_plan_golden(self):
        resolved = three_zone_fixture()
        before = copy.deepcopy(resolved)
        design=resolve_accelerator_electrical_design(resolved,variant_id="three_zone_square", schema_version=1)
        self.assertEqual(resolved,before)
        self.assertEqual(design["ring_z_mm"],resolved["rings"]["accelerator_placement"]["ring_z_mm"])
        # Captured from the pre-extraction _accelerator_plan on this independent
        # 7/56.1/236.9-mm fixture; exact arithmetic parity, not rounded targets.
        self.assertEqual(design["operating_voltages_v"]["rings"],[1562.5933703416636,1265.1867406833285,
            967.7801110249919,670.373481366657,351.0276251372427,329.088398566165,307.14917199508733,
            285.2099454240097,263.270718852932,241.33149228185434,219.39226571077668,197.453039139699,
            175.5138125686214,153.57458599754372,131.63535942646607,109.69613285538833,87.75690628431067,
            65.81767971323308,43.878453142155365,21.93922657107771])
        for semantic,native in (("repeller","repeller"),("grid1","intermediate1"),
                               ("intermediate2","intermediate2"),("grid2","exit")):
            self.assertEqual(design["operating_voltages_v"][semantic],resolved["accelerator_topology"]["potentials_v"][native])
        voltages=design["operating_voltages_v"]["rings"]
        self.assertTrue(all(a>b for a,b in zip(voltages,voltages[1:])))
        self.assertTrue(all(v>372.96685170832035 for v in voltages[:4]))
        self.assertTrue(all(0<v<372.96685170832035 for v in voltages[4:]))

    def test_legacy_divider_accepts_explicit_nonzero_exit_and_shared_plane(self):
        self.assertEqual(linear_ring_electrode_voltages([10,20],[10,12,20],[100,50]),[100.,90.,50.])
        self.assertEqual(linear_ring_electrode_voltages([-2,0,8],[-1,0,4],[300,100,-100]),[200.,100.,0.])
        self.assertEqual(linear_ring_electrode_voltages([0,1],[.5],[7,7]),[7.])

    def test_missing_nonfinite_or_conflicting_physics_fails_clearly(self):
        for field,value in (("grid1",float("nan")),("shield",1.),("intermediate2",200.)):
            with self.subTest(field=field):
                resolved=three_zone_fixture()
                resolved["electrodes_V"][field]=value
                with self.assertRaises(ValueError):
                    resolve_accelerator_electrical_design(resolved,variant_id="three_zone_square", schema_version=1)
        resolved=three_zone_fixture()
        resolved["electrodes_V"].pop("intermediate2")
        with self.assertRaisesRegex(ValueError,"incomplete"):
            resolve_accelerator_electrical_design(resolved,variant_id="three_zone_square", schema_version=1)
        with self.assertRaisesRegex(ValueError,"topology conflicts"):
            resolve_accelerator_electrical_design(two_zone_fixture(),variant_id="three_zone_square", schema_version=1)
        with self.assertRaisesRegex(ValueError,"unsupported"):
            resolve_accelerator_electrical_design(two_zone_fixture(),variant_id="unpublished", schema_version=1)

    def test_invalid_divider_never_extrapolates_or_reorders_rings(self):
        for planes,rings,values in (([0,1],[-.01],[10,0]),([0,1],[1.01],[10,0]),
                ([0,0],[0],[10,0]),([1,0],[.5],[10,0]),([0,1],[.6,.5],[10,0]),
                ([0,1],[.5,.5],[10,0]),([0,1],[.5],[10]),([0],[0],[1]),
                ([0,1],[float("nan")],[10,0]),([0,float("inf")],[.5],[10,0]),
                ([0,1],[.5],[True,0]),([0,1],[.5],[10,float("inf")])):
            with self.subTest(planes=planes,rings=rings,values=values),self.assertRaises(ValueError):
                linear_ring_electrode_voltages(planes,rings,values)


    def test_current_v2_roles_are_exact_source_version_mapping_without_new_divider(self):
        resolved = three_zone_fixture()
        old = resolve_accelerator_electrical_design(resolved, variant_id="three_zone_square", schema_version=1)
        current = resolve_accelerator_electrical_design(resolved, variant_id="three_zone_square")
        names = {"repeller": "repeller", "grid1": "intermediate_grid_1",
                 "intermediate2": "intermediate_grid_2", "grid2": "exit_grid"}
        self.assertEqual(current["schema_version"], 2)
        self.assertEqual(current["planes_z_mm"], {names[key]: value for key, value in old["planes_z_mm"].items()})
        self.assertEqual(current["operating_voltages_v"],
                         {names.get(key, key): value for key, value in old["operating_voltages_v"].items()})
        self.assertNotEqual(current["operating_voltages_v"]["intermediate_grid_1"],
                            current["operating_voltages_v"]["intermediate_grid_2"])
        self.assertEqual(set(current["operating_voltages_v"]),
                         {"repeller", "intermediate_grid_1", "intermediate_grid_2", "exit_grid", "rings", "shield"})
        self.assertEqual(current["ring_z_mm"], old["ring_z_mm"])
        for version in (0, 3, True, 2.0):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, "schema_version"):
                resolve_accelerator_electrical_design(resolved, variant_id="three_zone_square", schema_version=version)


if __name__ == "__main__":
    unittest.main()
