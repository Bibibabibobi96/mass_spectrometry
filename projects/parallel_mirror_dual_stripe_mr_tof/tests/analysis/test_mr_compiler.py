"""Pure real-provider OA–MR geometry serialization and authority checks."""

import unittest
from pathlib import Path


class CompleteMRGeometryTest(unittest.TestCase):
    def test_complete_real_provider_geometry_and_refusals(self):
        import msplatform

        r = Path(msplatform.__file__).resolve().parents[2]
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_mr_provider_trial_transport import (
            _plans,
        )
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.test_support.mr_geometry_inputs import (
            geometry_authority,
        )
        from msplatform.components.catalog import resolve_component
        from msplatform.assembly.factory import assemble
        from msplatform.backends.simion.mr_compiler import compile_complete_mr_geometry

        _, plan, contract = _plans()
        a = geometry_authority(contract)
        o = resolve_component(
            {
                "provider_id": "orthogonal_accelerator",
                "design": {
                    "requirements": a["accelerator_requirements"],
                    "geometry_profile": a["geometry_profile"],
                },
                "geometry_profile_id": a["geometry_profile_id"],
            }
        )
        m = resolve_component(
            {
                "provider_id": "parallel_mirror_dual_stripe_mr_tof",
                "design": {
                    "contract": contract,
                    "accelerator_requirements": a["accelerator_requirements"],
                    "geometry_profile": a["geometry_profile"],
                },
                "geometry_profile_id": a["geometry_profile_id"],
            }
        )
        cs = {
            k: (o if v["project_id"] == "orthogonal_accelerator" else m)
            for k, v in plan["components"].items()
        }
        ass = assemble(plan["recipe"], cs)
        d = {
            "cell_mm_xyz": dict.fromkeys("xyz", 0.1),
            "pa_bounds_mm": {
                a + s: (-1000.0 if s == "_min" else 1000.0)
                for a in "xyz"
                for s in ("_min", "_max")
            },
        }
        g = compile_complete_mr_geometry(
            ass, numerics={"domains": dict.fromkeys(("oa", "analyzer", "detector"), d)}
        )
        import copy
        from msplatform.backends.simion.mr_geometry import _analyzer_geometry_lines
        from msplatform.backends.simion.mr_compiler import _require_contained

        mr_id = next(
            k
            for k, v in plan["components"].items()
            if v["project_id"] == "parallel_mirror_dual_stripe_mr_tof"
        )
        oa_id = next(
            k
            for k, v in plan["components"].items()
            if v["project_id"] == "orthogonal_accelerator"
        )
        meta = g.frontend_geometry
        assert (
            meta["source_status"] == "not_requested"
            and meta["field_status"] == "not_solved"
        )
        assert set(meta["physical_members"]) == {oa_id, mr_id}
        assert all("shape" in member for member in meta["physical_members"][mr_id])
        assert meta["asset_poses"][oa_id] == next(
            x["transform"]
            for x in plan["recipe"]["instances"]
            if x["instance_id"] == oa_id
        )
        assert meta["asset_poses"][mr_id + "_analyzer"] == next(
            x["transform"]
            for x in plan["recipe"]["instances"]
            if x["instance_id"] == mr_id
        )
        names = [
            x["electrode_group_id"]
            for x in plan["components"][mr_id]["component_electrodes"]
        ]
        permutation = dict(zip(names, reversed(range(1, len(names) + 1)), strict=True))
        witnesses = meta["raw_physical_samples"]
        self.assertEqual(
            set(witnesses), {oa_id, mr_id + "_analyzer", mr_id + "_detector"}
        )
        for asset in witnesses:
            self.assertTrue(
                any(sample.get("metal") is False for sample in witnesses[asset])
            )
            self.assertTrue(
                any(
                    sample.get("metal") is not False and sample["electrode_id"] > 0
                    for sample in witnesses[asset]
                )
            )
        for asset in (mr_id + "_analyzer", mr_id + "_detector"):
            vacuum = next(
                item for item in witnesses[asset] if item.get("metal") is False
            )
            dimensions = meta["numerical_domains"][asset]["dimensions"]
            self.assertTrue(
                all(
                    0 < vacuum["gu"][i] < dimensions["n" + axis] - 1
                    for i, axis in enumerate("xyz")
                )
            )
        self.assertIn(
            "remaining members and native namespace unverified",
            meta["raw_witness_scope"]["analyzer"],
        )
        from msplatform.backends.simion.mr_compiler import (
            _mr_samples,
            _detector_samples,
        )

        analyzer_samples = _mr_samples(
            ass.components_resolved[mr_id],
            permutation,
            meta["numerical_domains"][mr_id + "_analyzer"],
            meta["physical_members"][mr_id][:-1],
        )
        self.assertEqual(
            analyzer_samples[0]["electrode_id"], permutation["positive_mirror_layer_1"]
        )
        self.assertEqual(
            analyzer_samples[0]["gu"], witnesses[mr_id + "_analyzer"][0]["gu"]
        )
        unusable = copy.deepcopy(meta["numerical_domains"][mr_id + "_detector"])
        unusable["instance_origin_mm"] = dict.fromkeys("xyz", 1000000.0)
        unusable["cell_mm_xyz"] = dict.fromkeys("xyz", 1000000.0)
        unusable["dimensions"] = dict.fromkeys(("nx", "ny", "nz"), 2)
        with self.assertRaises(ValueError):
            _detector_samples(ass.components_resolved[mr_id]["detector"], 1, unusable)
        body = _analyzer_geometry_lines(
            ass.components_resolved[mr_id], native_group_ids=permutation
        )
        assert body and body != _analyzer_geometry_lines(ass.components_resolved[mr_id])
        try:
            _analyzer_geometry_lines(
                ass.components_resolved[mr_id], native_group_ids={names[0]: 1}
            )
        except ValueError:
            pass
        else:
            raise AssertionError("incomplete native mapping accepted")
        bad = copy.deepcopy(meta["numerical_domains"][mr_id + "_analyzer"])
        bad["bounds_mm"]["x_max"] = -1001
        try:
            _require_contained(meta["physical_members"][mr_id][:-1], bad)
        except ValueError:
            pass
        else:
            raise AssertionError("cropped physical member accepted")
        assert (
            Path(__file__).parent / "fixtures/mr_legacy_analyzer.gem.txt"
        ).read_text(encoding="utf-8").splitlines() == _analyzer_geometry_lines(
            ass.components_resolved[mr_id]
        )
        import re

        original_body = (
            (Path(__file__).parent / "fixtures/mr_legacy_analyzer.gem.txt")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        assert all(
            f"e({permutation[name]})" in "\n".join(body)
            for name in names
            if name
            != next(
                x["electrode_group_id"]
                for x in plan["components"][mr_id]["component_electrodes"]
                if x["role"] == "detector"
            )
        )
        duplicate = permutation.copy()
        duplicate[names[0]] = duplicate[names[1]]
        try:
            _analyzer_geometry_lines(
                ass.components_resolved[mr_id], native_group_ids=duplicate
            )
        except ValueError:
            pass
        else:
            raise AssertionError("duplicate native IDs accepted")

        def physical_tokens(lines):
            return re.findall(
                r"(?:box3D|polyline|notin_inside|within)\s*(?:\([^\n]*?\))?",
                "\n".join(lines),
            )

        assert physical_tokens(body) == physical_tokens(original_body)
        assert meta["electrode_group_roles"][mr_id] == {
            row["electrode_group_id"]: row["role"]
            for row in plan["components"][mr_id]["component_electrodes"]
        }

        def flatten_electrode_wrappers(lines):
            text = re.sub(r";[^\n]*", "", "\n".join(lines))
            pos = 0
            content = []
            for_match = re.compile(r"e\(\d+\)\s*\{")
            while True:
                match = for_match.search(text, pos)
                if match is None:
                    break
                depth = 1
                i = match.end()
                while depth:
                    if text[i] == "{":
                        depth += 1
                    elif text[i] == "}":
                        depth -= 1
                    i += 1
                content.append(text[match.end() : i - 1])
                pos = i
            return re.sub(r"\s+", "", "".join(content))

        assert flatten_electrode_wrappers(original_body) == flatten_electrode_wrappers(
            body
        )
        changed = copy.deepcopy(ass.components_resolved[mr_id])
        changed["stripe_electrodes"][0]["x"][0] -= 0.25
        assert flatten_electrode_wrappers(
            _analyzer_geometry_lines(changed, native_group_ids=permutation)
        ) != flatten_electrode_wrappers(body)
        changed_cutout = copy.deepcopy(ass.components_resolved[mr_id])
        changed_cutout["mirror_inner_shield_slot"][0] -= 0.25
        self.assertNotEqual(
            flatten_electrode_wrappers(
                _analyzer_geometry_lines(changed_cutout, native_group_ids=permutation)
            ),
            flatten_electrode_wrappers(body),
        )
        self.assertEqual(
            meta["physical_cutouts"][mr_id]["mirror_inner_shield_slot"],
            ass.components_resolved[mr_id]["mirror_inner_shield_slot"],
        )
        import json
        from msplatform.backends.simion.oa_focus_plan import derive
        from projects.orthogonal_accelerator.analysis.two_zone_geometry import (
            load_geometry_profile,
        )

        campaign = (
            r
            / "projects/orthogonal_accelerator/config/two_zone_component_focus_campaign.json"
        )
        profile_id = json.loads(campaign.read_text(encoding="utf-8"))[
            "geometry_profile_id"
        ]
        provider = derive(
            campaign,
            geometry_profile=load_geometry_profile(profile_id),
            mesh_mm_per_gu=[0.25, 0.25, 0.1],
        )
        old_oa = resolve_component(
            {
                "provider_id": "orthogonal_accelerator",
                "design": {
                    "requirements": provider["requirements"],
                    "geometry_profile": a["geometry_profile"],
                },
                "geometry_profile_id": a["geometry_profile_id"],
            }
        )
        old_components = {k: (old_oa if k == oa_id else m) for k in cs}
        old_ass = assemble(plan["recipe"], old_components)
        try:
            compile_complete_mr_geometry(
                old_ass,
                numerics={"domains": dict.fromkeys(("oa", "analyzer", "detector"), d)},
            )
        except ValueError as exc:
            assert (
                str(exc)
                == "selected canonical OA mechanics differ from MR matching authority"
            )
        else:
            raise AssertionError("actual differing OA fixture was accepted")
        from msplatform.contracts.machine_contracts import ContractError

        bad = copy.deepcopy(ass)
        bad._components[mr_id]._resolved_design["stripe_electrodes"][0]["x"][0] -= 0.25
        with self.assertRaises(ContractError):
            compile_complete_mr_geometry(
                bad,
                numerics={"domains": dict.fromkeys(("oa", "analyzer", "detector"), d)},
            )
        bad = copy.deepcopy(ass)
        bad._components[mr_id]._source_design["contract"]["dual_stripe"][
            "physical_electrode_count"
        ] += 1
        with self.assertRaisesRegex(
            ValueError, "dual stripe requires four physical electrodes"
        ):
            compile_complete_mr_geometry(
                bad,
                numerics={"domains": dict.fromkeys(("oa", "analyzer", "detector"), d)},
            )
        bad = copy.deepcopy(ass)
        bad._composition_plan["components"][mr_id]["component_electrodes"][0][
            "electrode_group_id"
        ] = "tampered"
        with self.assertRaises(ContractError):
            compile_complete_mr_geometry(
                bad,
                numerics={"domains": dict.fromkeys(("oa", "analyzer", "detector"), d)},
            )
