"""Pure public RF-OA joint geometry tests against versioned provider examples."""

import copy
import json
import unittest
from pathlib import Path

base = Path(__file__).resolve().parents[2]
from msplatform.assembly.factory import assemble
from msplatform.components.catalog import resolve_component
from msplatform.components.rf_multipole.electrode_topology import build_electrode_topology
from msplatform.components.orthogonal_accelerator.geometry_members import iter_geometry_members
from msplatform.backends.simion.rf_oa_compiler import compile_rf_oa_geometry


def check_variant(variant):
    example = json.loads((base / "src/msplatform/examples/rf_oatof_functional_v1.json").read_text(encoding="utf-8"))
    exoa = json.loads((base / "src/msplatform/examples/oa_two_three_geometric_v1.json").read_text(encoding="utf-8"))
    rf = resolve_component(example["component_requests"]["multipole"])
    oa = resolve_component(exoa["component_requests"][variant])
    recipe = copy.deepcopy(example["recipe"])
    r, o = recipe["instances"]
    r["transform"]["translation_mm"] = [-rf.assembly_interface["ports"]["mechanical_exit"]["center_mm"][2], 0, 0]
    o.update(instance_id="oa", project_id="orthogonal_accelerator")
    o["transform"]["from_frame_id"] = oa.assembly_interface["local_frame_id"]
    rot = [[1, 0, 0], [0, 1, 0], [0, 0, 1]] if variant == "three" else [[0, 1, 0], [-1, 0, 0], [0, 0, 1]]
    o["transform"]["rotation"] = rot
    center = oa.assembly_interface["ports"]["side_entry"]["center_mm"]
    o["transform"]["translation_mm"] = [-sum(rot[i][j] * center[j] for j in range(3)) for i in range(3)]
    recipe["connections"] = [
        dict(
            connection_id="rf_oa",
            upstream=dict(instance_id="multipole", port_id="mechanical_exit"),
            downstream=dict(instance_id="oa", port_id="side_entry"),
            gap_mm=0.0,
            coupling_mode="monolithic_joint_solve",
        )
    ]
    ass = assemble(recipe, {"multipole": rf, "oa": oa})
    rfg = [x["electrode_group_id"] for x in build_electrode_topology(rf.resolved_design)]
    oag = list(dict.fromkeys(x["electrode_group_id"] for x in iter_geometry_members(oa.resolved_design)))
    num = dict(
        parent_domain=dict(
            cell_mm_xyz=dict(x=0.1, y=0.1, z=0.1),
            pa_bounds_mm=dict(x_min=-110, x_max=110, y_min=-60, y_max=60, z_min=-100, z_max=100),
        ),
        boundary="grounded_pa_faces",
        representation="fractional_legacy_within",
        electrode_group_native_ids={
            "multipole": {x: i + 1 for i, x in enumerate(rfg)},
            "oa": {x: i + 101 for i, x in enumerate(oag)},
        },
    )
    result = compile_rf_oa_geometry(ass, numerics=num)
    samples = result.frontend_geometry["raw_physical_samples"]["parent"]
    members = iter_geometry_members(oa.resolved_design)
    assert {m["member_id"] for m in members} <= {s["label"] for s in samples if s.get("metal") is not False}
    from msplatform.backends.simion.oa_compiler import render_accelerator_body

    body = render_accelerator_body(
        oa.resolved_design,
        oa.assembly_interface["variant_id"],
        num["electrode_group_native_ids"]["oa"],
        dict(x=0.1, y=0.1, z=0.1),
    )
    assert "\n".join(body) in result.frontend_gems["parent"]
    from msplatform.backends.simion.rf_geometry import render_physical_gem

    rf_body = render_physical_gem(
        rf.resolved_design,
        dict(x=0.1, y=0.1, z=0.1),
        electrode_group_native_ids=num["electrode_group_native_ids"]["multipole"],
    )
    assert rf_body.rstrip() in result.frontend_gems["parent"]
    print(variant, len(result.frontend_gems["parent"]), len(samples))
    from msplatform.backends.simion import operations as ops

    public = ops.compile_geometry(ass, numerics=num)
    assert public.frontend_gems == result.frontend_gems
    from msplatform.components.catalog import _from_provider

    payload = json.loads(
        json.dumps(dict(plan=ass.composition_plan, resolved=ass.components_resolved, source=ass.components_source))
    )
    restored = {
        name: _from_provider(
            "rf_multipole" if name == "multipole" else "orthogonal_accelerator",
            payload["resolved"][name],
            payload["plan"]["components"][name],
            source_design=payload["source"][name],
        )
        for name in payload["source"]
    }
    roundtrip = ops.compile_geometry(assemble(recipe, restored), numerics=num)
    assert roundtrip.frontend_gems == result.frontend_gems
    bad = copy.deepcopy(num)
    bad["parent_domain"]["pa_bounds_mm"]["x_min"] = -5
    try:
        ops.compile_geometry(ass, numerics=bad)
    except ValueError:
        pass
    else:
        raise AssertionError("domain clipping accepted")
    bad = copy.deepcopy(num)
    bad["electrode_group_native_ids"]["oa"][oag[0]] = 1
    try:
        ops.compile_geometry(ass, numerics=bad)
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate native ID accepted")
    forged = copy.deepcopy(ass)
    if variant == "two":
        forged._components["oa"]._resolved_design["side_entry"]["physical_cutout_box_mm"][0] += 0.1
    else:
        forged._components["oa"]._resolved_design["geometry"]["numerical_port_width_mm"] += 0.1
    try:
        ops.compile_geometry(forged, numerics=num)
    except ValueError:
        pass
    else:
        raise AssertionError("forged component accepted")
    renum = copy.deepcopy(num)
    renum["electrode_group_native_ids"]["oa"] = {x: 201 + i for i, x in enumerate(reversed(oag))}
    changed = ops.compile_geometry(ass, numerics=renum)
    assert changed.frontend_geometry["electrode_bindings"]["oa"] == renum["electrode_group_native_ids"]["oa"]
    return result


class RfOaCompilerTests(unittest.TestCase):
    def test_three_zone_full_geometry_public_and_guards(self):
        check_variant("three")

    def test_two_zone_full_geometry_public_and_guards(self):
        check_variant("two")


class RfOaOwnerPlanTests(unittest.TestCase):
    def test_public_build_uses_actual_one_parent_owner(self):
        import tempfile
        from types import SimpleNamespace
        from unittest.mock import patch
        from msplatform.backends.simion import operations
        from msplatform.backends.simion.native_plans import plan_geometry_build
        from msplatform.backends.simion.resources import STRUCTURAL_SEEDS

        compiled = check_variant("three")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            size, sha = STRUCTURAL_SEEDS[1]
            seed = dict(path=str(root / "seed.iob"), bytes=size, sha256=sha)
            plan = plan_geometry_build(
                compiled,
                run_directory=root,
                seed_record=seed,
                native_path_resource=root / "inputs/native_sources/native_run_path.lua",
            )
            self.assertEqual(
                [o["operation_id"] for o in plan.operations], ["geometry_parent", "build_geometry", "verify_geometry"]
            )
            self.assertIn("RF_OA_GEOMETRY_IOB=PASS", plan.operations[1]["success_marker"])
            self.assertIn("rf_oa_geometry_iob_build", plan.materializations[str(root / "inputs/geometry_iob.lua")])
            self.assertTrue(any(path.endswith("parent_surface.csv") for path in plan.declared_outputs))
            context = SimpleNamespace(tools={"simion": Path(__file__).resolve()}, execution_root=root)
            stage = dict(limits={"transient_run_directory_bytes": 1}, artifact_retention={})
            with (
                patch("msplatform.execution.stage_policy.read_stage_policy", return_value=(stage, {})),
                patch("msplatform.execution.owner.run_managed_stage", return_value={"manifest": {}}) as owner,
                patch("msplatform.results.artifacts.open_artifact", return_value="OPENED"),
            ):
                self.assertEqual(operations.build_geometry(compiled, context=context), "OPENED")
            request = owner.call_args.kwargs
            self.assertEqual(
                request["expected_operation_ids"], ("geometry_parent", "build_geometry", "verify_geometry")
            )
            self.assertEqual(Path(request["action"].keywords["seed_record"]["path"]).name, "1_instance_seed.iob")
            self.assertEqual(
                request["payload"]["compiled_geometry"]["frontend_geometry"]["role"], "simion_rf_oa_geometry"
            )

    def test_actual_owner_materializes_plan_with_inert_process(self):
        import tempfile
        from types import SimpleNamespace
        from msplatform.backends.simion.geometry_execution import execute_geometry
        from msplatform.backends.simion.native_plans import plan_geometry_build
        from msplatform.backends.simion.resources import structural_seed_path
        from msplatform.io.manifest_records import file_record, verify_record

        compiled = check_variant("two")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            seed = file_record(structural_seed_path(1), "required_evidence")
            plan = plan_geometry_build(
                compiled,
                run_directory=root,
                seed_record=seed,
                native_path_resource=root / "inputs/native_sources/native_run_path.lua",
            )

            class Session:
                run_dir = artifact_run_dir = root
                input_dir, log_dir = root / "inputs", root / "logs"
                context = SimpleNamespace(tools={"simion": Path(__file__).resolve()})
                expected_operation_ids = tuple(row["operation_id"] for row in plan.operations)
                calls = []

                def canonical_path(self, path):
                    return Path(path).resolve()

                def declare_file(self, path, role):
                    pass

                def add_input(self, name, record):
                    verify_record(name, record)

                def run_process(self, operation_id, **options):
                    self.calls.append(operation_id)
                    operation = plan.operations[len(self.calls) - 1]
                    self.log_dir.mkdir(parents=True, exist_ok=True)
                    (self.log_dir / f"operation_{len(self.calls):04d}.stdout.log").write_text(
                        operation["success_marker"]
                    )
                    for path in operation["outputs"]:
                        Path(path).write_bytes(b"INERT TEST OUTPUT")

            session = Session()
            result = execute_geometry(session, compiled=compiled, seed_record=seed, limits={})
            self.assertEqual(session.calls, list(session.expected_operation_ids))
            from msplatform.backends.simion.geometry_execution import native_resource_path

            for name in (
                "gem2pa_geometry.lua",
                "build_frontend_geometry.lua",
                "build_geometry_iob.lua",
                "iob_core.lua",
            ):
                self.assertEqual(
                    (root / "inputs/native_sources" / name).read_bytes(), native_resource_path(name).read_bytes()
                )
            product = result["manifest_extra_fields"]["products"]["geometry"]
            self.assertEqual(product["metadata"]["field_status"], "not_solved")
            self.assertEqual(product["metadata"]["source_status"], "not_requested")
            self.assertEqual(product["metadata"]["sampled_particles"], 0)
            self.assertEqual(set(product["metadata"]["native_assets"]), {"parent"})
            for record in product["data"].values():
                verify_record("inert geometry product", record)
