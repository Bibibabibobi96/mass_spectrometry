"""Software-only plan-3/5 trial transport using the existing trial fixture.

The underlying fixture mocks upstream voltage authority and exit-reference handling;
it does not execute a solver or establish physical-field qualification.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from msplatform.assembly.resolve_assembly import compile_assembly_layout
from msplatform.components.orthogonal_accelerator.assembly_interface import resolve_assembly_interface as oa_interface
from msplatform.components.parallel_mirror_dual_stripe_mr_tof.provider import resolve_component
from msplatform.backends.simion.oa_focus_plan import derive
from projects.orthogonal_accelerator.analysis.two_zone_geometry import load_geometry_profile
from projects.parallel_mirror_dual_stripe_mr_tof.analysis import two_prism_simion_trial as trial
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_system_geometry import resolve_oa_mr_direct_pose
from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis import test_two_prism_simion_trial as trial_fixture
from projects.parallel_mirror_dual_stripe_mr_tof.tests.test_support.mr_geometry_inputs import geometry_authority

REPO = Path(__file__).resolve().parents[4]
PROJECT = REPO / "projects/parallel_mirror_dual_stripe_mr_tof"


def _plans():
    contract = json.loads((PROJECT / "config/simion_candidate_two_zone.json").read_text(encoding="utf-8"))
    authority = geometry_authority(contract)
    campaign = REPO / "projects/orthogonal_accelerator/config/two_zone_component_focus_campaign.json"
    profile_id = json.loads(campaign.read_text(encoding="utf-8"))["geometry_profile_id"]
    provider = derive(campaign, geometry_profile=load_geometry_profile(profile_id), mesh_mm_per_gu=[.25, .25, .1])
    legacy = json.loads((REPO / "integrations/config/recipes/oa_mr_two_zone_gap30_plan.json").read_text(encoding="utf-8"))
    pose = resolve_oa_mr_direct_pose(provider, legacy)
    oa = oa_interface(provider["requirements"], geometry_profile_id=provider["layout"]["geometry_profile_id"],
                      geometry_profile=authority["geometry_profile"])
    design = {"contract": contract, "accelerator_requirements": authority["accelerator_requirements"],
              "geometry_profile": authority["geometry_profile"]}
    mr = resolve_component(design, geometry_profile_id=authority["geometry_profile_id"])["assembly_interface"]
    components = copy.deepcopy(legacy["components"])
    components[pose["oa_instance_id"]] = oa
    components[pose["mr_instance_id"]] = mr
    return legacy, compile_assembly_layout(legacy["recipe"], components), contract


class MRProviderTrialTransportTests(unittest.TestCase):
    def test_real_materializer_plan5_and_legacy_preserve_controls(self):
        legacy, current, contract = _plans()
        self.assertEqual((legacy["schema_version"], current["schema_version"]), (3, 5))
        originals = json.dumps([legacy, current, contract], sort_keys=True)
        fixture = trial_fixture.TwoPrismSimionTrialTest()
        outputs = []
        observed = []
        with tempfile.TemporaryDirectory(prefix="mr_trial_transport_") as directory:
            for index, plan in enumerate((legacy, current)):
                root = Path(directory) / str(index)
                root.mkdir()
                original_resolver = trial.resolve_accelerator_iob_origin
                with patch.object(trial, "resolve_accelerator_iob_origin", wraps=original_resolver) as placement:
                    result, operating = fixture._materialize_static_stripe_fixture(root, mode=None, parent_plan=plan)
                self.assertGreaterEqual(placement.call_count, 1)
                observed.append(placement.call_args_list[0].kwargs.get("mr_source_design"))
                outputs.append(((root / "source.fly2").read_bytes(), operating.encode("utf-8"),
                                result["resolved_iob_pose"], result["source_position_project_mm"]))
        self.assertIsNone(observed[0])
        self.assertEqual(observed[1]["contract"], contract)
        self.assertEqual(observed[1]["inherited_dual_stripe_topology_contract"], contract)
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(json.dumps([legacy, current, contract], sort_keys=True), originals)

    def test_plan5_materializer_rejects_stale_mr_component(self):
        _, current, _ = _plans()
        from msplatform.components.parallel_mirror_dual_stripe_mr_tof.candidate_contract import CandidateContractError
        mr = next(key for key, value in current["components"].items()
                  if value["project_id"] == "parallel_mirror_dual_stripe_mr_tof")
        bad = copy.deepcopy(current)
        bad["components"][mr]["component_electrodes"][0]["electrode_group_id"] = "stale_component"
        bad = compile_assembly_layout(bad["recipe"], bad["components"])
        with tempfile.TemporaryDirectory(prefix="mr_trial_stale_") as directory:
            with self.assertRaisesRegex(CandidateContractError, "interfaces differ"):
                trial_fixture.TwoPrismSimionTrialTest()._materialize_static_stripe_fixture(Path(directory), mode=None, parent_plan=bad)


if __name__ == "__main__":
    unittest.main()
