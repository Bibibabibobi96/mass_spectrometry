"""Backend-owned native field verifier and cache-identity regression tests."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from msplatform.backends.simion.compiler import compile_geometry
from msplatform.backends.simion.field_identity import working_point_member_id
from msplatform.backends.simion.native_plans import (
    operating_member_identity, plan_legacy_solve_fields, plan_operating_member,
)
from msplatform.backends.simion.resources import native_resource_path
from tests.workflows.single_reflection.test_single_reflection_geometry import (
    candidate_300mm_fixture, multipole_source, scientific_inputs,
)

ROOT = Path(__file__).resolve().parents[3]
LUA = Path(shutil.which("lua") or shutil.which("lua5.1") or "C:/Program Files/SIMION-2020/lua.exe")
TOOL = dict(
    simion_identity=dict(release="SIMION 2020", executable_bytes=123, executable_sha256="A" * 64),
    builder_identity=dict(operating_builder="B" * 64, exporter="C" * 64),
)


def current_field_plan(root: Path, *, project="octupole", local=False, fine=False) -> dict:
    """Compile actual providers and return the current native field plan."""
    source = multipole_source(project)
    oatof = candidate_300mm_fixture()
    sources = {} if local else {"multipole": source}
    options, _ = scientific_inputs({"multipole": source}, oatof, root / "providers", local=local)
    if fine:
        parent = options["numerical_domains"]["parent"]
        repeller = oatof["accelerator_topology"]["planes_global_z_mm"]["repeller"]
        options["numerical_domains"]["entrance_refinement"] = dict(
            cell_mm_xyz=dict(x=.15, y=.125, z=.05),
            pa_bounds_mm=dict(parent["pa_bounds_mm"], y_min=-21.5, y_max=21.5,
                              z_min=repeller - 20., z_max=repeller + 24.),
            guard_cells=2,
        )
    for domain in options["numerical_domains"].values():
        domain["refine_convergence_v"] = dict(
            carrier_off=.1, pulse_delta=.3, **({} if local else {"rf_reference": .2}))
    components = {"oatof": oatof, **sources}
    compiled = compile_geometry(
        dict(composition_plan=options["composition_plan"], components_resolved=components),
        numerics=dict(
            frontend_domains={name: {key: value for key, value in domain.items() if key != "refine_convergence_v"}
                              for name, domain in options["numerical_domains"].items()},
            geometry_build=oatof["simion_geometry_build"], detector_marker=oatof["simion_detector_marker"],
            electrode_group_native_ids=options["electrode_bindings"],
        ),
    )
    drive = dict(pulse_voltage_policy_id="all_accelerator_electrodes_zero_before_pulse_v1")
    if not local:
        drive["rf_reference_voltage_v"] = 10000.
    return plan_legacy_solve_fields(
        compiled, components, drive=drive,
        numerics=dict(boundary_policy="native_zero_neumann", frontend_domains=options["numerical_domains"]),
    )


def member_audit(plan: dict, root: Path, member_id: str, *, fine=False):
    """Use the current native planner's actual audit transport, without native I/O."""
    parent = None
    if fine:
        point = next(point for point in plan["field_design"]["working_points"]
                     if working_point_member_id(point) == member_id)
        parent = dict(cache_key="D" * 64, record=dict(
            kind=point["kind"], path=str(root / "payload" / ("frontend." + member_id + ".pa")),
            bytes=100, sha256="E" * 64,
            **({"working_point_id": point["working_point_id"]} if "working_point_id" in point else {}),
        ))
    stage, identity = plan_operating_member(
        plan, domain_id="entrance_refinement" if fine else "parent", member_id=member_id,
        tool_identity=TOOL, raw_geometry_record=None, raw_geometry_path=root / "raw.pa#",
        working_directory=root / "work", payload_directory=root / "payload",
        resource_paths=dict(
            operating_builder=native_resource_path("build_dirichlet_patch_operating_pa.lua"),
            exporter=native_resource_path("export_detached_standalone_pa.lua"),
            verifier=native_resource_path("audit_frontend_working_fields.lua"),
        ),
        published_parent=parent,
    )
    text = stage.materializations[str(root / "work" / "audit.tsv")]
    return text, identity


def write_audit_harness(root: Path, audit_text: str) -> Path:
    """Build a bounded PA double from the actual current audit specification."""
    samples, voltages = [], []
    grid = None
    for line in audit_text.splitlines():
        row = line.split("\t")
        if row[0] == "grid":
            grid = row[1:]
        elif row[0] == "physical":
            samples.append("['" + ",".join(row[3:]) + "']=" + row[2])
        elif row[0] == "voltages":
            voltages.append("['" + row[1] + "']={" + row[2] + "}")
    assert grid is not None and samples and voltages
    harness = root / "audit.lua"
    harness.write_text(
        "local ids={" + ",".join(samples) + "}\nlocal volts={" + ",".join(voltages) + "}\n" + r'''
local helper,spec,report,fault=arg[1],arg[2],arg[3],arg[4]
local active=0
simion={pas={}}
function simion.pas:close() assert(active==0) end
function simion.pas:open(path)
 active=active+1;assert(active==1,'audit must not retain multiple fields')
 local kind=path:match('frontend[^/\\]*%.([^%.]+)%.pa$')
 local pa={potential_type='electric',nx=NX,ny=NY,nz=NZ,dx_mm=DX,dy_mm=DY,dz_mm=DZ}
 if fault=='grid' and kind then pa.nx=pa.nx+1 end
 function pa:point(x,y,z)
  local id=assert(ids[x..','..y..','..z])
  local value=kind and volts[kind][id] or id
  if fault=='roundoff' and kind then value=value+1e-12 end
  if fault=='id' and not kind then value=value+1 end
  if fault=='voltage' and kind then value=value+1 end
  if fault=='nonfinite' and kind then value=0/0 end
  return value,not(fault=='mask' and kind)
 end
 function pa:close() active=active-1 end
 return pa
end
arg={spec,report};dofile(helper);assert(active==0)
'''.replace("NX", grid[0]).replace("NY", grid[1]).replace("NZ", grid[2])
        .replace("DX", grid[3]).replace("DY", grid[4]).replace("DZ", grid[5]),
        encoding="utf-8", newline="\n")
    return harness


@unittest.skipUnless(LUA.is_file(), "plain Lua interpreter unavailable")
class NativeFieldVerifierTests(unittest.TestCase):
    def check_audit(self, plan: dict, root: Path, *, fine=False) -> None:
        for point in plan["field_design"]["working_points"]:
            member_id = working_point_member_id(point)
            audit_text, _ = member_audit(plan, root, member_id, fine=fine)
            spec = root / "spec.tsv"
            spec.write_text(audit_text, encoding="utf-8", newline="\n")
            harness = write_audit_harness(root, audit_text)
            for fault in ("none", "roundoff", "id", "voltage", "mask", "grid", "nonfinite"):
                result = subprocess.run(
                    [str(LUA), str(harness), str(native_resource_path("audit_frontend_working_fields.lua")),
                     str(spec), str(root / "audit.json"), fault],
                    cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
                with self.subTest(member=member_id, fault=fault):
                    self.assertEqual(result.returncode == 0, fault in ("none", "roundoff"), result.stderr)
            report = json.loads((root / "audit.json").read_text(encoding="utf-8"))
            self.assertEqual(report["physical_samples"],
                             len(plan["field_design"]["domains"][-1 if fine else 0]["physical_samples"]))

    def test_actual_lua_audit_rejects_wrong_ids_voltages_masks_grids_and_nonfinite(self):
        for project in ("quadrupole", "hexapole", "octupole"):
            with self.subTest(project=project), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.check_audit(current_field_plan(root, project=project), root)

    def test_fine_lua_audit_accepts_actual_subset_and_requires_same_member_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.check_audit(current_field_plan(root, fine=True), root, fine=True)

    def test_local_lua_audit_uses_sparse_real_ids_without_zero_rf_member(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.check_audit(current_field_plan(root, local=True), root)


class NativeFieldCacheIdentityTests(unittest.TestCase):
    def test_voltage_convergence_mesh_and_boundary_changes_affect_actual_member_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = current_field_plan(Path(directory))
            original = operating_member_identity(
                plan, domain_id="parent", member_id="rf_reference", tool_identity=TOOL)
            for change in ("voltage", "convergence", "mesh", "grid", "boundary", "gem"):
                changed = copy.deepcopy(plan)
                design = changed["field_design"]
                if change == "voltage":
                    key = next(iter(design["working_points"][1]["electrode_voltages_v"]))
                    design["working_points"][1]["electrode_voltages_v"][key] += 1
                elif change == "convergence":
                    design["domains"][0]["refine_convergence_v"]["rf_reference"] *= 2
                elif change == "mesh":
                    design["domains"][0]["cell_mm_xyz"]["x"] *= 2
                elif change == "grid":
                    design["domains"][0]["dimensions"]["nx"] += 1
                elif change == "boundary":
                    design["domains"][0]["boundary_policy"] = "zero_dirichlet"
                else:
                    design["domains"][0]["gem_sha256"] = "F" * 64
                with self.subTest(change=change):
                    actual = operating_member_identity(
                        changed, domain_id="parent", member_id="rf_reference", tool_identity=TOOL)
                    self.assertNotEqual(actual, original)
            with self.assertRaisesRegex(ValueError, "parent solve cannot depend"):
                operating_member_identity(
                    plan, domain_id="parent", member_id="rf_reference", tool_identity=TOOL,
                    published_parent=dict(record=dict(kind="rf_reference")))

    def test_fine_identity_selects_only_the_matching_published_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = current_field_plan(root, fine=True)
            parents = {}
            for point in plan["field_design"]["working_points"]:
                member_id = working_point_member_id(point)
                parents[member_id] = dict(cache_key="A" * 64, record=dict(
                    kind=point["kind"], path=str(root / (member_id + ".pa")), bytes=100, sha256="B" * 64,
                    **({"working_point_id": point["working_point_id"]} if "working_point_id" in point else {}),
                ))
            identities = {}
            for member_id, parent in parents.items():
                identities[member_id] = operating_member_identity(
                    plan, domain_id="entrance_refinement", member_id=member_id,
                    tool_identity=TOOL, published_parent=parent)
                boundary = identities[member_id]["boundary_policy"]
                self.assertEqual(len(boundary["parent_working_points"]), 1)
                self.assertEqual(boundary["parent_working_points"][0]["name"], member_id + ".pa")
            changed = copy.deepcopy(parents["rf_reference"])
            changed["record"]["sha256"] = "C" * 64
            rf = operating_member_identity(
                plan, domain_id="entrance_refinement", member_id="rf_reference",
                tool_identity=TOOL, published_parent=changed)
            self.assertNotEqual(rf, identities["rf_reference"])
            self.assertEqual(
                operating_member_identity(plan, domain_id="entrance_refinement", member_id="carrier_off",
                                          tool_identity=TOOL, published_parent=parents["carrier_off"]),
                identities["carrier_off"])
            self.assertEqual(
                operating_member_identity(plan, domain_id="entrance_refinement", member_id="pulse_delta",
                                          tool_identity=TOOL, published_parent=parents["pulse_delta"]),
                identities["pulse_delta"])
            with self.assertRaisesRegex(ValueError, "same-member"):
                operating_member_identity(
                    plan, domain_id="entrance_refinement", member_id="rf_reference",
                    tool_identity=TOOL, published_parent=parents["carrier_off"])


if __name__ == "__main__":
    unittest.main()
