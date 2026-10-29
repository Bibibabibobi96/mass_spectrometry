"""Small, solver-free production provider contract regressions."""
from __future__ import annotations

import copy
import json
import hashlib
import struct
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from projects.parallel_mirror_dual_stripe_mr_tof.analysis import native_static_field_provider as p
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider import derive_candidate_authority
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_system_geometry import build_static_c0_gem
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import _record, load_binding
from common.contracts.verify_run_manifest import verify_record
from common.contracts.write_run_manifest import file_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.standalone_pa_composition import PaHeader


class NativeStaticProviderTest(unittest.TestCase):
    def overlay_fixture(self):
        self.source["accelerator_provider"] = p.IP_PROVIDER
        self.source["instances"][2]["role"] = "ion_processor_collision"
        for index, instance in enumerate(self.source["instances"][1:], 1):
            header = PaHeader(-2, 1, 100000, 21, 21, 21, 1, 1, 1, 1)
            Path(instance["pa_path"]).write_bytes(header.pack()+b"\0"*(header.node_count*8))
            instance["origin_mm"] = [0, -10 if index == 1 else 30*index, -10]
        p.write_json(self.root / "binding.json", {"schema_version": 1, "role": "mrtof_native_static_field_binding"})
        mock = patch.object(p, "_analyzer_geometry_lines", return_value=["e(1) { box(0,-1,-1,1,1,1) }"])
        mock.start()
        self.addCleanup(mock.stop)
        update = dict(box_mm=[0, -2, -2, 2, 2, 2], pitch_mm=[.5]*3, priority_probes=[
            dict(label="metal", point_mm=[.5, 0, 0], expected_electrode=True, expected_instance=5),
            dict(label="inside", point_mm=[.5, 1.9, 0], expected_electrode=False, expected_instance=5),
            dict(label="outside", point_mm=[.5, 2.1, 0], expected_electrode=False, expected_instance=2)])
        return dict(schema_version=1, role=p.ROLE, numerical_contract_path=str(self.contract_path),
                    source_binding_path=str(self.root/"binding.json"), source_field_manifest=self.source["manifest"],
                    collision_overlay_update=update)

    def test_real_native_input_guards_precede_validation_and_reject_missing_or_bad_headers(self):
        import shutil
        import subprocess
        import sys
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_static_field_binding import IonProcessorNativeBindingTest
        powershell = shutil.which("pwsh")
        if powershell is None:
            self.skipTest("PowerShell 7 required")
        fields = self.root / "actual_fields"
        fields.mkdir()
        helper = IonProcessorNativeBindingTest()
        descriptor, source_path, owner = helper.fixture(fields, detector_box=[0,0,0,1,1,1])
        for index, instance in enumerate(descriptor["instances"][1:]):
            header = PaHeader(-2,1,100000,*( [11,11,11] if index == 0 else [3,3,3]),1,1,1,1)
            Path(instance["pa_path"]).write_bytes(header.pack()+b"\0"*(header.node_count*8))
        helper.seal(fields, owner)
        run = self.root / "guarded_overlay"
        (run / "inputs").mkdir(parents=True)
        (run / "inputs/source_binding.json").write_bytes(source_path.read_bytes())
        patch_plan = dict(box_mm=[0,-1,-4,1,1,-2], priority_probes=[
            dict(point_mm=[.5,0,-3], expected_instance=5),
            dict(point_mm=[.5,.9,-3], expected_instance=5),
            dict(point_mm=[.5,1.1,-3], expected_instance=2)])
        plan = dict(operation="collision_overlay", analyzer_collision_patch_build=patch_plan)
        plan_path = run / "inputs/plan.json"
        p.write_json(plan_path, plan)
        original_open = Path.open
        def no_payload_open(path, *args, **kwargs):
            if path.name.endswith((".pa", ".pa-surf")):
                raise AssertionError("Native input selection read PA bytes before guards")
            return original_open(path, *args, **kwargs)
        # This is the real loader/owner chain, without the class's old source mocks.
        with patch.object(p, "load_binding", wraps=load_binding), patch.object(Path, "open", no_payload_open):
            actual_inputs = p.native_input_binding(plan, run)
        self.assertEqual(len(actual_inputs["instances"]), 3)
        runner = Path(__file__).resolve().parents[2] / "simion/run_native_static_field_provider.ps1"
        text = runner.read_text()
        start = text.index("    $nativeInputs=Invoke-RunToolRootContext")
        block = text[start:text.index("    foreach($name in @('frozen_input','resolved_geometry'))", start)]
        script = run / "guarded_native_inputs.ps1"
        script.write_text(r"""
param($python,$repo,$RunDirectory,$planPath)
$ErrorActionPreference='Stop';$isComposition=$false
$overlayGuards=[Collections.Generic.List[IDisposable]]::new()
$script:calls=0
function Invoke-RunToolRootContext {param($RepoRoot,$Operation)
 $script:calls++
 if($script:calls-eq2){
  if($overlayGuards.Count-lt3){throw 'Actual validation preceded payload guards'}
  foreach($stream in $overlayGuards){
   $blocked=$false
   try{$writer=[IO.File]::Open($stream.Name,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::None);$writer.Dispose()}catch [IO.IOException]{$blocked=$true}
   if(-not$blocked){throw 'Native header validation lacked a read guard'}
  }
 }
 $env:PYTHONPATH=$repo
 & $Operation
}
try {
""" + block + r"""
 'NATIVE_VENDOR_BOUNDARY_REACHED'
} finally {foreach($stream in $overlayGuards){$stream.Dispose()}}
""", encoding="utf-8")
        carrier = Path(descriptor["instances"][1]["pa_path"])
        original = carrier.read_bytes()
        for case in ("valid", "wrong_header", "missing"):
            if case == "wrong_header":
                carrier.write_bytes(b"BAD!"+original[4:])
                helper.seal(fields, owner)
            elif case == "missing":
                carrier.unlink()
            completed = subprocess.run([powershell,"-NoProfile","-File",str(script),sys.executable,
                str(Path(__file__).resolve().parents[4]),str(run),str(plan_path)],
                cwd=run,capture_output=True,text=True,encoding="utf-8",timeout=30,check=False)
            output = completed.stdout + completed.stderr
            with self.subTest(case=case):
                if case == "valid":
                    self.assertEqual(completed.returncode,0,output)
                    self.assertIn("NATIVE_VENDOR_BOUNDARY_REACHED",output)
                else:
                    self.assertNotEqual(completed.returncode,0,output)
                    self.assertNotIn("NATIVE_VENDOR_BOUNDARY_REACHED",output)
            carrier.write_bytes(original)
            helper.seal(fields, owner)

    def test_overlay_plan_and_prepare_do_not_read_pa_before_actual_validation(self):
        request = self.overlay_fixture()
        p.write_json(Path(request["source_field_manifest"]), dict(status="success", outputs=[]))
        original_open = Path.open
        def no_payload_open(path, *args, **kwargs):
            if path.suffix.lower() == ".pa" or path.name.endswith(".pa-surf"):
                raise AssertionError("PA opened before the native input guard")
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", no_payload_open):
            plan = p.compile_request(request)
            run = self.root / "metadata_prepare"
            (run / "inputs").mkdir(parents=True)
            for name, source in plan["inputs"].items():
                (run / "inputs" / (name+Path(source).suffix)).write_bytes(Path(source).read_bytes())
            p.prepare_run(plan, run)
        # Header-dependent coverage is checked at actual use, never skipped.
        carrier = Path(self.source["instances"][1]["pa_path"])
        raw = carrier.read_bytes()
        carrier.write_bytes(b"bad")
        with self.assertRaises(ValueError):
            p.verify_collision_overlay_support(self.source, plan["analyzer_collision_patch_build"])
        carrier.write_bytes(raw)
        p.verify_collision_overlay_support(self.source, plan["analyzer_collision_patch_build"])

    def test_collision_overlay_compiles_only_same_csg_occupancy_and_no_parent(self):
        request = self.overlay_fixture()
        original = copy.deepcopy(self.source)
        plan = p.compile_request(request)
        self.assertEqual(plan["operation"], "collision_overlay")
        self.assertEqual(plan["execution_order"], [])
        self.assertEqual(plan["levels"], {})
        self.assertEqual(plan["candidate_authority"], self.source["authority"])
        patch_plan = plan["analyzer_collision_patch_build"]
        self.assertEqual(patch_plan["dimensions"], [5, 9, 9])
        self.assertEqual(patch_plan["pa_bytes"], 56+8*5*9*9)
        self.assertFalse(patch_plan["refine_performed"])
        self.assertFalse(patch_plan["refinable"])
        self.assertIn(",planar,x,electric_,,", patch_plan["gem"])
        self.assertIn("e(1) { box", patch_plan["gem"])
        self.assertEqual(self.source, original)

    def test_collision_overlay_accepts_original_unit_grid_detector_without_broadening_composer(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.standalone_pa_composition import read_pa_header
        request = self.overlay_fixture()
        detector = Path(self.source["instances"][3]["pa_path"])
        detector.write_bytes(struct.pack("<iidiiii", -1, 1, 100000, 21, 21, 21, 1600)+b"\0"*(21**3*8))
        request["collision_overlay_update"]["pitch_mm"] = [1, 1, 1]
        plan = p.compile_request(request)
        self.assertEqual(plan["analyzer_collision_patch_build"]["pa_bytes"], 32+8*3*5*5)
        self.assertEqual(p.collision_pa_header(detector).dx_mm, 1)
        with self.assertRaisesRegex(ValueError, "mode -2"):
            read_pa_header(detector)

    def test_collision_overlay_rejects_source_changes_masking_and_invalid_numerics(self):
        request = self.overlay_fixture()
        for mutation in ("recursive", "ip_overlap", "quantum", "missing_probe", "far_probe", "voltage"):
            value = copy.deepcopy(request)
            source = copy.deepcopy(self.source)
            if mutation == "recursive":
                source["collision_overlay"] = {}
            elif mutation == "ip_overlap":
                source["instances"][2]["origin_mm"] = [0, 0, 0]
            elif mutation == "quantum":
                value["collision_overlay_update"]["pitch_mm"] = [.015]*3
            elif mutation == "missing_probe":
                value["collision_overlay_update"]["priority_probes"].pop()
            elif mutation == "far_probe":
                value["collision_overlay_update"]["priority_probes"][-1]["point_mm"][1] = 5
            else:
                value["candidate_voltages_v"] = request.get("candidate_voltages_v", {})
            with self.subTest(mutation=mutation), patch.object(p, "load_binding", return_value=source):
                if mutation == "ip_overlap":
                    plan = p.compile_request(value)
                    with self.assertRaises(ValueError):
                        p.verify_collision_overlay_support(source, plan["analyzer_collision_patch_build"])
                else:
                    with self.assertRaises(ValueError):
                        p.compile_request(value)

    def test_collision_overlay_loader_preserves_materialization_and_checks_all_new_assets(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis import static_field_binding as b
        request = self.overlay_fixture()
        source_path = Path(request["source_binding_path"])
        p.write_json(source_path, dict(schema_version=1, role="mrtof_native_static_field_binding", materialization={}))
        def record(path):
            return dict(path=str(path.resolve()), bytes=path.stat().st_size,
                        sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        source_owner = Path(request["source_field_manifest"])
        p.write_json(source_owner, dict(status="success", outputs=[dict(record(source_path), exists=True, retention_role="lightweight_optional")]))
        with patch.object(p, "_record", side_effect=_record):
            plan = p.compile_request(request)
        run = self.root / "overlay"
        (run / "inputs").mkdir(parents=True)
        (run / "results").mkdir()
        for name, path in plan["inputs"].items():
            (run / "inputs" / (name+Path(path).suffix)).write_bytes(Path(path).read_bytes())
        p.prepare_run(plan, run)
        patch_plan = plan["analyzer_collision_patch_build"]
        directory = run / "simion/analyzer_collision_patch"
        pa = directory / "analyzer_collision_patch.pa"
        header = PaHeader(-2, 1, 100000, *patch_plan["dimensions"], p.COLLISION_NOTREFINABLE_FLAG | 1, *patch_plan["pitch_mm"])
        pa.write_bytes(header.pack()+b"\0"*(header.node_count*8))
        Path(str(pa)+"-surf").write_bytes(b"fractional")
        path = run / "results/field_binding.json"
        p.write_json(path, p.binding_spec(plan, run))
        def seal():
            p.write_json(run/"run_manifest.json", dict(status="success", outputs=[
                record(item) for item in run.rglob("*") if item.is_file() and item.name != "run_manifest.json"]))
        seal()
        original = copy.deepcopy(self.source)
        with patch.object(b, "_load_native_materialized", return_value=self.source) as materialized:
            loaded = b.load_binding(path)
        self.assertEqual(loaded["instances"][:4], self.source["instances"])
        self.assertEqual(loaded["instances"][4]["role"], "analyzer_collision_patch")
        self.assertEqual(loaded["authority"], self.source["authority"])
        self.assertEqual(loaded["refinement_windows"], self.source["refinement_windows"])
        self.assertEqual(loaded["source_descriptor_path"], str((run/"inputs/source_binding.json").resolve()))
        self.assertEqual(materialized.call_args.args[1], run/"inputs/source_binding.json")
        self.assertEqual(self.source, original)
        for mutation in ("source_copy", "gem", "refine", "header", "refinable"):
            target = {"source_copy": run/"inputs/source_binding.json", "gem": directory/"analyzer_collision_patch.gem",
                      "refine": run/"inputs/analyzer_collision_patch_plan.json", "header": pa, "refinable": pa}[mutation]
            before = target.read_bytes()
            if mutation == "refine":
                value = p.read(target)
                value["refine_performed"] = True
                p.write_json(target, value)
            elif mutation in ("header", "refinable"):
                flag = p.COLLISION_NOTREFINABLE_FLAG if mutation == "header" else 1
                changed = PaHeader(-2, 1, 100000, *patch_plan["dimensions"], flag, *patch_plan["pitch_mm"])
                target.write_bytes(changed.pack()+before[56:])
            else:
                target.write_bytes(before.replace(b"CSG", b"BAD") if mutation == "gem" else before.replace(b"schema_version", b"schema_versioX"))
            # Even a fresh overlay owner seal cannot authorize changed source bytes,
            # a new CSG expression, a Refine or the wrong actual native grid.
            seal()
            with self.subTest(mutation=mutation), patch.object(b, "_load_native_materialized", return_value=self.source):
                if mutation in ("header", "refinable"):
                    # Metadata parsing consumes the sealed plan, not the PA.
                    b.load_binding(path)
                    actual = p.collision_pa_header(pa)
                    self.assertTrue(actual.raw_mirror & 7 != 1 or not actual.raw_mirror & p.COLLISION_NOTREFINABLE_FLAG)
                else:
                    with self.assertRaises((AssertionError, ValueError)):
                        b.load_binding(path)
            target.write_bytes(before)
            seal()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.contract_path = self.root / "numerical_contract.json"
        self.contract = {"simion": {"numerical_profiles": {"native_static_field": {
            "target_layout": {"parent": {"pitch_mm": [1, 1, 1]}, "windows": [{"pitch_mm": [1, 1, 1]}]},
            "refine": {"convergence_v": 1e-5}}, "grid_generation": {"spacing_quantum_mm": .01}}}}
        p.write_json(self.contract_path, self.contract)
        self.authority = {"analyzer_electrode_voltages_v": [0.0] * 20,
                          "component_voltages_v": [{"component_namespace": "accelerator", "component_electrode_id": 1, "voltage_v": 4000.0},
                                                   {"component_namespace": "detector", "component_electrode_id": 25, "voltage_v": 0.0}]}
        self.geometry = {"frozen": "geometry"}
        self.source = {"mode": "native_static_pa", "authority": self.authority,
                       "geometry": self.geometry, "instances": [], "refinement_windows": []}
        for label in ("parent", "window"):
            directory = self.root / label
            directory.mkdir()
            numerical = directory / "plan.json"
            p.write_json(numerical, {"box_mm": [0, -2, -2, 2, 2, 2], "pitch_mm": [1, 1, 1],
                                    "dimensions": [3, 5, 5], "mirror_axes": ["x"], "surface": "fractional",
                                    "resource_budget": {"estimated_memory_bytes": 123},
                                    "resource_limits": {"automatic_retry_count": 0},
                                    "committed_new_bytes": 6 * 1024**3})
            surface = directory / "static.pa-surf"
            surface.write_bytes(b"fractional")
            level = {"manifest": str(directory / "run_manifest.json"),
                     "native_solver_numerics": {"refine_stopping": "contract_convergence", "convergence_v": 1e-5},
                     "records": {"surface": file_record(surface)},
                     "sources": {"numerical_plan": str(numerical), "surface": str(surface),
                                 "scalar_pa": str(directory / "static.pa"),
                                 "geometry_authority": str(directory / "geometry.json"),
                                 "voltage_authority": str(directory / "voltage.json")}}
            if label == "parent":
                self.source.update(level)
            else:
                level.update(name="covered", active_box_mm=[[-1, 1], [-1, 1], [-1, 1]])
                self.source["refinement_windows"].append(level)
        self.source["instances"] = [
            {"role": role, "manifest": str(self.root / (role + ".json")),
             "pa_path": str(self.root / (role + ".pa")), "origin_mm": [0, 0, 0]}
            for role in ("global_fallback", "native_corridor", "accelerator", "detector")]
        wp = Path(self.source["refinement_windows"][0]["sources"]["numerical_plan"])
        value = p.read(wp)
        value.update(parent_manifest=self.source["manifest"], parent_pa=self.source["sources"]["scalar_pa"])
        p.write_json(wp, value)
        self.request = {"schema_version": 1, "role": p.ROLE, "run_id": "test_run",
                        "numerical_contract_path": str(self.contract_path),
                        "source_binding_path": str(self.root / "binding.json"),
                        "source_field_manifest": self.source["manifest"],
                        "candidate_voltages_v": {"p1": 1, "p2": -2, "s1": -27, "s2": 55}}
        for name, replacement in (("load_binding", lambda _: self.source),
                                  ("_record", lambda *_: {"path": "fixture", "bytes": 0, "sha256": "fixture"}),
                                  ("verify_record", lambda *_a, **_k: None),
                                  ("derive_candidate_authority", lambda *_: (self.authority, {})),
                                  ("build_static_c0_gem", lambda *_a, **_k: ("pa_define{}\n", {}))):
            mock = patch.object(p, name, side_effect=replacement)
            mock.start()
            self.addCleanup(mock.stop)

    def new_geometry(self):
        """Small frozen assembly; no PA, Refine, vendor call or fixture mutation."""
        for key in ("coordinate_system", "accelerator", "detector"):
            self.contract[key] = {"identity": key}
        p.write_json(self.contract_path, self.contract)
        self.geometry.update(frame_id="same_frame", detector={"id": 25, "box": [0, -1, -1, 1, 1, 1]},
                             mirror_electrodes=[{"box": [-1, -1, -1, 1, 1, 1]}],
                             mirror_ground_shields=[], mirror_e_closures=[])
        self.authority["assembly"] = {"detector": self.geometry["detector"]}
        collision = Path(self.source["instances"][1]["pa_path"])
        header = PaHeader(-2, 1, 100000, 3, 5, 5, 1, 1, 1, 1)
        collision.write_bytes(header.pack() + b"\0" * (header.node_count * 8))
        shapes = patch.object(p, "_analyzer_geometry_lines", return_value=["e(1) { box(0,-1,-1,1,1,1) }"])
        shapes.start()
        self.addCleanup(shapes.stop)
        updated = copy.deepcopy(self.geometry)
        updated["mirror_electrodes"][0].update(polygon_yz_mm=[[-1, -1], [1, -.9], [1, 1], [-1, .9]])
        updated["mirror_convergence_transform"] = {"angle_deg": .1}
        path = self.root / "geometry_contract.json"
        p.write_json(path, self.contract)
        self.request["geometry_contract_path"] = str(path)
        contract_mock = patch.object(p, "load_contract", side_effect=p.read)
        resolve_mock = patch.object(p, "resolve_geometry", return_value=updated)
        contract_mock.start()
        resolver = resolve_mock.start()
        self.addCleanup(contract_mock.stop)
        self.addCleanup(resolve_mock.stop)
        return updated, resolver

    def mirror_reuse_request(self):
        central = self.source["refinement_windows"][0]
        mirrors = []
        for index in (0, 1):
            mirror = copy.deepcopy(central)
            directory = self.root / f"mirror_{index}"
            directory.mkdir()
            plan_path = directory / "plan.json"
            numerical = p.read(Path(central["sources"]["numerical_plan"]))
            numerical.update(parent_manifest=central["manifest"], parent_pa=central["sources"]["scalar_pa"])
            p.write_json(plan_path, numerical)
            mirror.update(manifest=str(directory / "run_manifest.json"), name=f"mirror_{index}")
            mirror["sources"]["numerical_plan"] = str(plan_path)
            mirror["sources"]["scalar_pa"] = str(directory / "static.pa")
            mirrors.append(mirror)
        self.source["refinement_windows"] = [*mirrors, central]
        for level in [self.source, *self.source["refinement_windows"]]:
            numerical = p.read(Path(level["sources"]["numerical_plan"]))
            level["grid"] = dict(origin_mm=numerical["box_mm"][:3], pitch_mm=numerical["pitch_mm"],
                                 dimensions=numerical["dimensions"], symmetry="x")
        self.contract["simion"]["numerical_profiles"]["native_static_field"]["target_layout"]["windows"] = [
            {"pitch_mm": [1, 1, .5]}, {"pitch_mm": [1, 1, .5]}, {"pitch_mm": [1, 1, 1]}]
        p.write_json(self.contract_path, self.contract)
        self.request["reuse_source_levels"] = ["parent", "window_2"]
        return self.request

    def test_mirror_refinement_reuses_sealed_parent_and_central_without_pa_copy(self):
        request = self.mirror_reuse_request()
        plan = p.compile_request(request)
        self.assertEqual(plan["levels"]["parent"]["committed_new_bytes"], 0)
        self.assertEqual(plan["levels"]["window_2"]["committed_new_bytes"], 0)
        self.assertEqual(plan["levels"]["window_0"]["pitch_mm"], [1, 1, .5])
        run = self.root / "mirror_run"
        (run / "inputs").mkdir(parents=True)
        p.write_json(run / "inputs/numerical_contract.json", self.contract)
        p.prepare_run(plan, run)
        self.assertFalse((run / "simion/parent").exists())
        self.assertFalse((run / "simion/window_2").exists())
        original_central = self.source["refinement_windows"][2]
        mirror_plan = p.read(run / "inputs/window_0_plan.json")
        self.assertEqual(mirror_plan["parent_pa"], original_central["sources"]["scalar_pa"])
        binding = p.binding_spec(plan, run)
        self.assertEqual(binding["parent"]["pa_path"], self.source["sources"]["scalar_pa"])
        self.assertEqual(binding["refinement_windows"][2]["pa_path"], original_central["sources"]["scalar_pa"])
        self.assertEqual(binding["refinement_windows"][0]["parent_manifest"], original_central["manifest"])
        self.assertEqual(binding["instances"][1:], self.source["instances"][1:])

    def test_mirror_reuse_rejects_voltage_stopping_fixed_grid_or_new_geometry(self):
        request = self.mirror_reuse_request()
        with patch.object(p, "derive_candidate_authority", return_value=({**self.authority, "changed": True}, {})):
            with self.assertRaisesRegex(ValueError, "complete voltage"):
                p.compile_request(request)
        for label, change in (("parent", [1, 1, .5]), ("window_2", [1, 1, .5])):
            contract = copy.deepcopy(self.contract)
            layout = contract["simion"]["numerical_profiles"]["native_static_field"]["target_layout"]
            (layout["parent"] if label == "parent" else layout["windows"][2])["pitch_mm"] = change
            p.write_json(self.contract_path, contract)
            with self.assertRaisesRegex(ValueError, "reused level target"):
                p.compile_request(request)
        p.write_json(self.contract_path, self.contract)
        self.source["native_solver_numerics"]["convergence_v"] = 1e-6
        with self.assertRaisesRegex(ValueError, "stopping contract"):
            p.compile_request(request)
        self.source["native_solver_numerics"]["convergence_v"] = 1e-5
        with self.assertRaisesRegex(ValueError, "same-geometry"):
            p.compile_request({**request, "geometry_contract_path": str(self.contract_path)})

    def mirror_extension_request(self):
        request = self.mirror_reuse_request()
        layout = self.contract["simion"]["numerical_profiles"]["native_static_field"]["target_layout"]
        for index in (0, 1):
            mirror = self.source["refinement_windows"][index]
            path = Path(mirror["sources"]["numerical_plan"])
            plan = p.read(path)
            plan["box_mm"][4] = 1
            plan["dimensions"][1] = 4
            p.write_json(path, plan)
            mirror["grid"]["dimensions"][1] = 4
            mirror["active_box_mm"][1][1] = 0
            layout["windows"][index] = {"pitch_mm": [1, 1, 1], "box_mm": [0, -2, -2, 2, 2, 2]}
        p.write_json(self.contract_path, self.contract)
        return request

    def test_mirror_y_extension_preserves_guard_reused_layers_and_collision(self):
        request = self.mirror_extension_request()
        original = copy.deepcopy(self.source)
        plan = p.compile_request(request)
        for index in (0, 1):
            level = plan["levels"][f"window_{index}"]
            self.assertEqual(level["box_mm"], [0, -2, -2, 2, 2, 2])
            self.assertEqual(level["dimensions"], [3, 5, 5])
            self.assertEqual(level["active_box_mm"], [[-1, 1], [-1, 1], [-1, 1]])
            self.assertNotIn("reuse_source", level)
        for label in ("parent", "window_2"):
            self.assertEqual(plan["levels"][label]["committed_new_bytes"], 0)
        self.assertEqual(self.source, original)
        binding = p.binding_spec(plan, self.root / "extended")
        self.assertEqual(binding["instances"][1:], self.source["instances"][1:])

    def test_mirror_y_extension_rejects_other_axes_shrink_unaligned_and_outside_donor(self):
        request = self.mirror_extension_request()
        for axis, value in ((0, -1), (1, -3), (2, -3), (3, 3), (5, 3), (4, 0), (4, 1.5), (4, 3)):
            with self.subTest(axis=axis, value=value):
                contract = copy.deepcopy(self.contract)
                contract["simion"]["numerical_profiles"]["native_static_field"]["target_layout"]["windows"][0]["box_mm"][axis] = value
                p.write_json(self.contract_path, contract)
                with self.assertRaises(ValueError):
                    p.compile_request(request)

    def test_mirror_box_unchanged_is_compatible_and_prepare_rejects_tampered_box(self):
        request = self.mirror_extension_request()
        layout = self.contract["simion"]["numerical_profiles"]["native_static_field"]["target_layout"]
        for target in layout["windows"][:2]:
            target["box_mm"][4] = 1
        p.write_json(self.contract_path, self.contract)
        plan = p.compile_request(request)
        self.assertEqual(plan["levels"]["window_0"]["active_box_mm"][1][1], 0)
        run = self.root / "tampered"
        (run / "inputs").mkdir(parents=True)
        p.write_json(run / "inputs/numerical_contract.json", self.contract)
        plan["levels"]["window_0"]["box_mm"][4] = 2
        plan["levels"]["window_0"]["dimensions"][1] = 5
        with self.assertRaisesRegex(ValueError, "target layout"):
            p.prepare_run(plan, run)
        self.assertFalse(list(run.rglob("*.gem")))

    def test_mirror_box_override_rejects_reused_roles_and_response_routes(self):
        request = self.mirror_extension_request()
        for role in ("parent", "window_2"):
            contract = copy.deepcopy(self.contract)
            layout = contract["simion"]["numerical_profiles"]["native_static_field"]["target_layout"]
            (layout["parent"] if role == "parent" else layout["windows"][2])["box_mm"] = [0, -2, -2, 2, 2, 2]
            p.write_json(self.contract_path, contract)
            with self.assertRaisesRegex(ValueError, "only extend"):
                p.compile_request(request)
        p.write_json(self.contract_path, self.contract)
        for changes in ({"response_axis": "s1"}, {"response_basis_paths": {}},
                        {"reuse_source_levels": ["parent", "window_2", "window_2"]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                p.compile_request({**request, **changes})

    def test_pure_s1_extension_reuses_only_matching_pure_parent_and_central(self):
        request = self.mirror_extension_request()
        request.pop("candidate_voltages_v")
        request["response_axis"] = "s1"
        original_authority = copy.deepcopy(self.authority)
        self.source["authority"] = p._pure_axis_authority(original_authority, "s1")
        meta = dict(axis="s1", normalization_v=10000., physical_electrode_ids=[11, 12],
                    excitation_semantics="pure axis response; all other analyzer/component potentials zero",
                    combination_semantics="base PA plus (target axis minus base axis)/normalization_v times this PA")
        self.source.update(response_basis=meta, source_authority=original_authority,
                           source_binding_path=str(self.root / "ordinary.json"))
        p.write_json(Path(request["source_binding_path"]), dict(
            role="mrtof_native_static_field_response_basis", source_binding_path=self.source["source_binding_path"]))
        with patch.object(p, "load_native_response_basis", return_value=self.source):
            plan = p.compile_request(request)
            self.assertEqual(plan["source_authority"], original_authority)
            self.assertEqual(plan["candidate_authority"], self.source["authority"])
            self.assertEqual(plan["inputs"]["source_binding"], self.source["source_binding_path"])
            self.assertEqual(plan["inputs"]["source_response_basis"], request["source_binding_path"])
            for label in ("parent", "window_2"):
                self.assertEqual(plan["levels"][label]["committed_new_bytes"], 0)
            self.assertEqual(plan["levels"]["window_0"]["box_mm"][4], 2)
            for mutation in ("axis", "normalization", "background"):
                bad = copy.deepcopy(self.source)
                if mutation == "axis":
                    bad["response_basis"]["axis"] = "p1"
                elif mutation == "normalization":
                    bad["response_basis"]["normalization_v"] = 1
                else:
                    bad["authority"]["component_voltages_v"][0]["voltage_v"] = 1
                with self.subTest(mutation=mutation), patch.object(p, "load_native_response_basis", return_value=bad), self.assertRaises(ValueError):
                    p.compile_request(request)

    def test_new_geometry_direct_build_freezes_contract_and_same_collision_parent(self):
        updated, resolver = self.new_geometry()
        old = copy.deepcopy(self.source)
        plan = p.compile_request(self.request)
        self.assertEqual(plan["resolved_geometry"], updated)
        self.assertEqual(plan["operation"], "refine")
        self.assertEqual(plan["inputs"]["geometry_contract"], self.request["geometry_contract_path"])
        resolver.assert_called_once_with(self.contract, accelerator_assembly=self.authority["assembly"])
        self.assertEqual(self.source, old)
        run = self.root / "new_geometry_run"
        (run / "inputs").mkdir(parents=True)
        for name in ("numerical_contract", "geometry_contract"):
            p.write_json(run / "inputs" / (name + ".json"), self.contract)
        p.prepare_run(plan, run)
        self.assertEqual(p.read(run / "inputs/resolved_geometry.json"), updated)
        binding = p.binding_spec(plan, run)
        self.assertEqual(binding["instances"][0]["pa_path"], binding["parent"]["pa_path"])
        self.assertEqual(binding["instances"][2:], old["instances"][2:])
        self.assertEqual(binding["instances"][1]["pa_path"], str((run / "simion/collision/collision.pa").resolve()))
        self.assertEqual(plan["collision_build"]["pa_bytes"], 656)
        self.assertIn("no Refine or Fast Adjust", (run / "simion/collision/collision.gem").read_text())
        self.assertEqual(p.read(run / "inputs/collision_plan.json")["resolved_geometry"], str((run / "inputs/resolved_geometry.json").resolve()))
        for label in ("parent", "window"):
            numerical = p.read(run / "inputs" / (label + "_plan.json"))
            self.assertEqual(numerical["resolved_geometry"], str((run / "inputs/resolved_geometry.json").resolve()))
        self.assertEqual(p.read(run / "inputs/window_plan.json")["parent_pa"], binding["parent"]["pa_path"])
        self.assertFalse(list(run.rglob("*.pa")))

    def test_new_geometry_rejects_old_response_and_consumer_routes_before_loading(self):
        for key in ("response_axis", "response_basis_paths", "consumer_view_source_path"):
            with self.subTest(key=key), patch.object(p, "load_binding") as load:
                request = dict(self.request, geometry_contract_path="explicit.json", **{key: "old"})
                with self.assertRaisesRegex(ValueError, "direct build"):
                    p.compile_request(request)
                load.assert_not_called()

    def test_new_geometry_rejects_component_frame_and_parent_bounds_changes(self):
        updated, resolver = self.new_geometry()
        path = Path(self.request["geometry_contract_path"])
        for key in ("coordinate_system", "accelerator", "detector"):
            changed = copy.deepcopy(self.contract)
            changed[key] = {"identity": "different"}
            p.write_json(path, changed)
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "new assembly"):
                p.compile_request(self.request)
        p.write_json(path, self.contract)
        for key in ("frame_id", "prism_electrodes", "detector"):
            changed = copy.deepcopy(updated)
            changed[key] = "different"
            resolver.return_value = changed
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "only mirror solids"):
                p.compile_request(self.request)
        changed = copy.deepcopy(updated)
        changed["mirror_electrodes"][0]["box"][5] = 3
        resolver.return_value = changed
        with self.assertRaisesRegex(ValueError, "outside the grounded parent"):
            p.compile_request(self.request)

    def test_prepare_rejects_new_geometry_changed_after_compile(self):
        updated, resolver = self.new_geometry()
        plan = p.compile_request(self.request)
        run = self.root / "new_geometry_run"
        (run / "inputs").mkdir(parents=True)
        for name in ("numerical_contract", "geometry_contract"):
            p.write_json(run / "inputs" / (name + ".json"), self.contract)
        changed = copy.deepcopy(updated)
        changed["mirror_convergence_transform"]["angle_deg"] = .2
        resolver.return_value = changed
        with self.assertRaisesRegex(ValueError, "frozen geometry contract"):
            p.prepare_run(plan, run)
        self.assertFalse(list(run.rglob("*.gem")))

    def test_new_geometry_allows_only_mirror_derived_reference_bound(self):
        updated, resolver = self.new_geometry()
        reference = dict(reference_plane_project_z_mm=33, open_project_z_interval_mm=[26, 40],
                         derivation=dict(lower_boundary={"value_mm": 26},
                                         upper_boundary_candidates_mm={"mirror": 102}, selected_upper_boundary_mm=40))
        self.geometry["two_prism_low_field_reference_section"] = copy.deepcopy(reference)
        updated["two_prism_low_field_reference_section"] = copy.deepcopy(reference)
        updated["two_prism_low_field_reference_section"]["derivation"].update(
            upper_boundary_candidates_mm={"mirror": 101.9}, mirror_inner_face={"dz_dy": -.001})
        self.assertEqual(p.compile_request(self.request)["resolved_geometry"]["two_prism_low_field_reference_section"]
                         ["reference_plane_project_z_mm"], 33)
        changed = copy.deepcopy(updated)
        changed["two_prism_low_field_reference_section"]["reference_plane_project_z_mm"] = 34
        resolver.return_value = changed
        with self.assertRaisesRegex(ValueError, "observation plane"):
            p.compile_request(self.request)

    def test_composition_source_recovers_sealed_full_solve_without_old_pa(self):
        self.three_windows()
        for index, level in enumerate(self.source["refinement_windows"][:2]):
            path = Path(level["sources"]["numerical_plan"])
            consumer = p.read(path)
            ancestor = path.with_name("sealed_original_consumer.json")
            p.write_json(ancestor, consumer)
            composed = copy.deepcopy(consumer)
            composed.pop("crop")
            composed.pop("full_solve_plan_path")
            composed.update(source_solve_plan_path=str(ancestor), source_solve_manifest=level["manifest"])
            p.write_json(path, composed)
        plan = p.compile_request(self.request)
        self.assertEqual(plan["levels"]["window_0"]["box_mm"][3], 2)
        self.assertEqual(plan["levels"]["window_0"]["consumer_grid"]["box_mm"][3], 1.5)
        self.assertIn("window_0_solve_ancestor_1", plan["inputs"])
        ancestor = Path(plan["inputs"]["window_0_solve_ancestor_1"])
        changed = p.read(ancestor)
        changed["pitch_mm"][0] = .25
        p.write_json(ancestor, changed)
        with self.assertRaisesRegex(ValueError, "consumer grid differs"):
            p.compile_request(self.request)

    def test_compiles_new_u_both_levels_and_capacity_from_nodes(self):
        plan = p.compile_request(self.request)
        self.assertEqual(plan["run_id"], "test_run")
        self.assertEqual(plan["candidate_authority"], self.authority)
        self.assertEqual(plan["levels"]["parent"]["boundary_mode"], "grounded_enclosure")
        self.assertEqual(plan["levels"]["window"]["boundary_mode"], "x_mirror_five_faces")
        self.assertEqual(plan["levels"]["parent"]["capacity_basis"]["pa_node_bytes"], 656)
        self.assertLess(plan["committed_new_bytes"], 40 * 1024**2)
        self.assertEqual(plan["automatic_retry_count"], 0)
        self.assertFalse(plan["qualification_passed"])
        self.assertEqual(plan["refine_options"], {"convergence": 1e-5})
        self.assertEqual(plan["inputs"]["numerical_contract"], str(self.contract_path.resolve()))
        self.assertEqual(Path(plan["inputs"]["grid_validator"]).name, "native_corridor_plan.py")
        for level in plan["levels"].values():
            self.assertEqual(level["convergence_v"], 1e-5)
            self.assertEqual(level["refine_stopping"], "contract_convergence")

    def test_requires_explicit_finite_positive_numerical_contract(self):
        missing = dict(self.request)
        del missing["numerical_contract_path"]
        with self.assertRaisesRegex(ValueError, "numerical_contract_path"):
            p.compile_request(missing)
        for value in (None, True, 0, -1, float("inf"), float("nan")):
            with self.subTest(value=value):
                self.contract["simion"]["numerical_profiles"]["native_static_field"]["refine"]["convergence_v"] = value
                self.contract_path.write_text(json.dumps(self.contract))
                with self.assertRaisesRegex(ValueError, "finite and positive"):
                    p.compile_request(self.request)
        p.write_json(self.contract_path, {"simion": {}})
        with self.assertRaisesRegex(ValueError, "Refine profile"):
            p.compile_request(self.request)

    def test_explicit_skipped_point_is_compiled_frozen_and_tamper_rejected(self):
        self.contract["simion"]["numerical_profiles"]["native_static_field"]["refine"]["skipped_point"] = False
        p.write_json(self.contract_path, self.contract)
        plan = p.compile_request(self.request)
        self.assertEqual(plan["refine_options"], dict(convergence=1e-5, skipped_point=False))
        self.assertIs(plan["refine_skipped_point"], False)
        self.assertTrue(all(level["refine_skipped_point"] is False for level in plan["levels"].values()))
        run = self.root / "explicit_strategy"
        (run / "inputs").mkdir(parents=True)
        p.write_json(run / "inputs/numerical_contract.json", self.contract)
        p.prepare_run(plan, run)
        for label in plan["levels"]:
            self.assertIs(p.read(run / "inputs" / (label+"_plan.json"))["refine_skipped_point"], False)
        for label in (None, "parent", "window", "options"):
            altered = copy.deepcopy(plan)
            if label == "options":
                altered["refine_options"]["skipped_point"] = 0
            else:
                selected = altered if label is None else altered["levels"][label]
                selected["refine_skipped_point"] = True
            rejected = self.root / ("bad_strategy_"+str(label))
            (rejected / "inputs").mkdir(parents=True)
            p.write_json(rejected / "inputs/numerical_contract.json", self.contract)
            with self.subTest(label=label), self.assertRaisesRegex(ValueError, "stopping"):
                p.prepare_run(altered, rejected)
            self.assertFalse((rejected / "simion").exists())

    def test_explicit_skipped_point_disallows_old_default_pure_response(self):
        self.contract["simion"]["numerical_profiles"]["native_static_field"]["refine"]["skipped_point"] = False
        p.write_json(self.contract_path, self.contract)
        request = dict(self.request, response_axis="p1")
        request.pop("candidate_voltages_v")
        with self.assertRaisesRegex(ValueError, "numerical|numerics|stopping"):
            p.compile_request(request)

    def test_new_generation_rejects_legacy_pitch_without_rounding_or_mutating_source(self):
        path = Path(self.source["refinement_windows"][0]["sources"]["numerical_plan"])
        value = p.read(path)
        value.update(pitch_mm=[.125, 1, 1], dimensions=[17, 5, 5])
        self.contract["simion"]["numerical_profiles"]["native_static_field"]["target_layout"]["windows"][0]["pitch_mm"] = [.125, 1, 1]
        p.write_json(self.contract_path, self.contract)
        p.write_json(path, value)
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "spacing_quantum_mm"):
            p.compile_request(self.request)
        self.assertEqual(path.read_bytes(), before)

    def test_new_generation_preserves_valid_anisotropic_pitch(self):
        path = Path(self.source["refinement_windows"][0]["sources"]["numerical_plan"])
        value = p.read(path)
        value.update(pitch_mm=[.05, .1, .2], dimensions=[41, 41, 21])
        self.contract["simion"]["numerical_profiles"]["native_static_field"]["target_layout"]["windows"][0]["pitch_mm"] = [.05, .1, .2]
        p.write_json(self.contract_path, self.contract)
        p.write_json(path, value)
        plan = p.compile_request(self.request)
        self.assertEqual(plan["levels"]["window"]["pitch_mm"], [.05, .1, .2])
        self.assertEqual(plan["levels"]["window"]["box_mm"], value["box_mm"])
        self.assertEqual(plan["grid_generation"], {"spacing_quantum_mm": .01})

    def test_numerical_repository_contract_is_frozen_input_not_an_artifact_lease(self):
        plan = p.compile_request(self.request)
        self.assertEqual(plan["inputs"]["numerical_contract"], str(self.contract_path.resolve()))
        self.assertNotIn(str(self.contract_path.resolve()), plan["protected_paths"])
        self.assertIn(self.request["source_binding_path"], plan["protected_paths"])
        for level in (self.source, *self.source["refinement_windows"]):
            self.assertIn(str(Path(level["manifest"]).parent), plan["protected_paths"])
            for path in level["sources"].values():
                self.assertIn(path, plan["protected_paths"])
        for instance in self.source["instances"][1:]:
            self.assertIn(instance["manifest"], plan["protected_paths"])
            self.assertIn(instance["pa_path"], plan["protected_paths"])

    def test_reject_invalid_run_id_and_four_coordinate_contract(self):
        for change in ({"run_id": "../old"}, {"candidate_voltages_v": {"s1": 2}},
                       {"candidate_voltages_v": dict(self.request["candidate_voltages_v"], p1=float("nan"))},
                       {"candidate_voltages_v": dict(self.request["candidate_voltages_v"], p1=True)},
                       {"unrecognized": 1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                p.compile_request(dict(self.request, **change))

    def test_real_candidate_authority_maps_only_four_ps_groups(self):
        self.authority["analyzer_electrode_voltages_v"] = list(range(20))
        with patch.object(p, "derive_candidate_authority", side_effect=derive_candidate_authority):
            plan = p.compile_request(self.request)
        actual = plan["candidate_authority"]["analyzer_electrode_voltages_v"]
        for index, expected in ((10, -27), (11, -27), (12, 55), (13, 55), (15, 1), (16, -2)):
            self.assertEqual(actual[index], expected)
        for index in set(range(20)) - {10, 11, 12, 13, 15, 16}:
            self.assertEqual(actual[index], index)
        self.assertEqual(self.authority["analyzer_electrode_voltages_v"], list(range(20)))

    def test_reject_non_native_or_multiple_windows_or_wrong_manifest(self):
        self.source["mode"] = "comsol_static_scalar_v"
        with self.assertRaises(ValueError):
            p.compile_request(self.request)
        self.source["mode"] = "native_static_pa"
        self.source["refinement_windows"].append(copy.deepcopy(self.source["refinement_windows"][0]))
        with self.assertRaises(ValueError):
            p.compile_request(self.request)
        self.source["refinement_windows"].pop()
        with self.assertRaises(ValueError):
            p.compile_request(dict(self.request, source_field_manifest=str(self.root / "wrong.json")))

    def test_reject_source_retry_contract(self):
        path = Path(self.source["sources"]["numerical_plan"])
        value = p.read(path)
        value["resource_limits"]["automatic_retry_count"] = 1
        p.write_json(path, value)
        with self.assertRaises(ValueError):
            p.compile_request(self.request)

    def test_prepare_and_binding_keep_same_u_surface_and_collision_roles(self):
        plan = p.compile_request(self.request)
        run = self.root / "test_run"
        (run / "inputs").mkdir(parents=True)
        p.write_json(run / "inputs/numerical_contract.json", self.contract)
        p.prepare_run(plan, run)
        self.assertEqual(p.read(run / "inputs/frozen_input.json"), self.authority)
        self.assertEqual(p.read(run / "inputs/resolved_geometry.json"), self.geometry)
        window_plan = p.read(run / "inputs/window_plan.json")
        for label in ("parent", "window"):
            actual = p.read(run / "inputs" / (label + "_plan.json"))
            self.assertEqual(actual["numerical_contract_path"], str((run / "inputs/numerical_contract.json").resolve()))
            self.assertEqual(actual["convergence_v"], 1e-5)
        binding = p.binding_spec(plan, run)
        self.assertEqual(window_plan["parent_manifest"], binding["parent"]["manifest"])
        self.assertEqual(window_plan["parent_pa"], binding["parent"]["pa_path"])
        self.assertEqual(binding["instances"][1:], self.source["instances"][1:])
        self.assertEqual(binding["instances"][0]["pa_path"], binding["parent"]["pa_path"])
        self.assertEqual(binding["parent"]["surface_path"], binding["parent"]["pa_path"] + "-surf")
        self.assertEqual(binding["refinement_windows"][0]["active_box_mm"], plan["levels"]["window"]["active_box_mm"])
        self.assertFalse(list(run.rglob("*.pa")))
        json.dumps(binding, allow_nan=False)

    def test_prepare_rejects_contract_changed_after_compile_before_gem_emission(self):
        plan = p.compile_request(self.request)
        run = self.root / "test_run"
        (run / "inputs").mkdir(parents=True)
        changed = copy.deepcopy(self.contract)
        changed["simion"]["numerical_profiles"]["native_static_field"]["refine"]["convergence_v"] = 1e-7
        p.write_json(run / "inputs/numerical_contract.json", changed)
        with self.assertRaisesRegex(ValueError, "frozen numerical contract"):
            p.prepare_run(plan, run)
        self.assertFalse(list(run.rglob("*.gem")))

    def three_windows(self):
        """Build real-shaped child-before-E priority with sealed full/crop plans."""
        e = self.source["refinement_windows"][0]
        windows = []
        for index in range(2):
            child = copy.deepcopy(e)
            directory = self.root / f"mirror_{index}"
            directory.mkdir()
            child["manifest"] = str(directory / "run_manifest.json")
            child["name"] = f"mirror_{index}"
            child["sources"]["scalar_pa"] = str(directory / "static.pa")
            child["sources"]["numerical_plan"] = str(directory / "consumer_plan.json")
            full = p.read(Path(e["sources"]["numerical_plan"]))
            full.update(parent_manifest=e["manifest"], parent_pa=e["sources"]["scalar_pa"],
                        crop={"consumer_box_mm": [0, -2, -2, 1.5, 2, 2],
                              "consumer_dimensions": [4, 5, 5]},
                        pitch_mm=[.5, 1, 1], dimensions=[5, 5, 5])
            p.write_json(directory / "full_plan.json", full)
            consumer = copy.deepcopy(full)
            consumer.update(box_mm=full["crop"]["consumer_box_mm"],
                            dimensions=full["crop"]["consumer_dimensions"],
                            full_solve_plan_path=str(directory / "full_plan.json"))
            p.write_json(directory / "consumer_plan.json", consumer)
            windows.append(child)
        self.source["refinement_windows"] = [*windows, e]
        layout = self.contract["simion"]["numerical_profiles"]["native_static_field"]["target_layout"]
        layout["windows"] = [{"pitch_mm": [.5, 1, 1], "stored_xmax_mm": 1.5},
                             {"pitch_mm": [.5, 1, 1], "stored_xmax_mm": 1.5},
                             {"pitch_mm": [1, 1, 1]}]
        p.write_json(self.contract_path, self.contract)

    def test_three_level_dependencies_priority_fullsolve_and_capacity(self):
        self.three_windows()
        plan = p.compile_request(self.request)
        self.assertEqual(plan["window_labels"], ["window_0", "window_1", "window_2"])
        self.assertEqual(plan["execution_order"], ["parent", "window_2", "window_0", "window_1"])
        self.assertEqual(plan["levels"]["window_0"]["parent_label"], "window_2")
        self.assertEqual(plan["levels"]["window_2"]["parent_label"], "parent")
        mirror = plan["levels"]["window_0"]
        self.assertEqual(mirror["box_mm"][3], 2)
        self.assertEqual(mirror["dimensions"], [5, 5, 5])
        self.assertEqual(mirror["consumer_grid"]["dimensions"], [4, 5, 5])
        self.assertEqual(mirror["crop"]["width_grid"], [3, 4, 4])
        self.assertEqual(mirror["crop"]["expected_consumer_pa_bytes"], 856)
        self.assertLess(plan["committed_new_bytes"], sum(v["committed_new_bytes"] for v in plan["levels"].values()))
        run = self.root / "prepared"
        (run / "inputs").mkdir(parents=True)
        p.write_json(run / "inputs/numerical_contract.json", self.contract)
        p.prepare_run(plan, run)
        binding = p.binding_spec(plan, run)
        self.assertEqual([w["name"] for w in binding["refinement_windows"]], ["mirror_0", "mirror_1", "covered"])
        for label in plan["execution_order"]:
            actual = p.read(run / "inputs" / (label + "_plan.json"))
            self.assertEqual(actual["convergence_v"], 1e-5)
            self.assertEqual(p.read(Path(actual["frozen_input"])), self.authority)
        consumer = p.read(run / "inputs/window_0_consumer_plan.json")
        self.assertEqual(consumer["parent_pa"], str((run / "simion/window_2/c0_local.pa").resolve()))
        self.assertEqual(consumer["full_solve_plan_path"], str((run / "inputs/window_0_plan.json").resolve()))
        self.assertEqual(binding["refinement_windows"][0]["grid"]["dimensions"], [4, 5, 5])
        self.assertEqual(binding["instances"][1:], self.source["instances"][1:])
        self.assertFalse(list(run.rglob("*.pa")))

    def test_three_windows_reject_missing_or_consumer_in_place_of_full_plan(self):
        self.three_windows()
        path = Path(self.source["refinement_windows"][0]["sources"]["numerical_plan"])
        original = p.read(path)
        for replacement in (None, str(path)):
            with self.subTest(path=replacement):
                changed = dict(original, full_solve_plan_path=replacement)
                p.write_json(path, changed)
                with self.assertRaisesRegex(ValueError, "full.solve"):
                    p.compile_request(self.request)
        p.write_json(path, original)
        with patch.object(p, "verify_record", side_effect=ValueError("sealed full plan changed")):
            with self.assertRaisesRegex(ValueError, "sealed full plan"):
                p.compile_request(self.request)

    def test_three_windows_reject_unknown_parent_cycle_and_invalid_target(self):
        self.three_windows()
        path = Path(self.source["refinement_windows"][2]["sources"]["numerical_plan"])
        original = p.read(path)
        for parent_pa in (str(self.root / "unrelated.pa"), self.source["refinement_windows"][2]["sources"]["scalar_pa"]):
            p.write_json(path, dict(original, parent_pa=parent_pa))
            with self.assertRaisesRegex(ValueError, "declared distinct"):
                p.compile_request(self.request)
        p.write_json(path, original)
        layout = self.contract["simion"]["numerical_profiles"]["native_static_field"]["target_layout"]
        for target in ({}, {"pitch_mm": [.125, 1, 1]}, {"pitch_mm": [.5, 1, 1], "stored_xmax_mm": 1}):
            layout["windows"][0] = target
            p.write_json(self.contract_path, self.contract)
            with self.assertRaises(ValueError):
                p.compile_request(self.request)

    def test_prepare_rejects_changed_target_layout_before_gem(self):
        plan = p.compile_request(self.request)
        changed = copy.deepcopy(self.contract)
        changed["simion"]["numerical_profiles"]["native_static_field"]["target_layout"]["windows"][0]["pitch_mm"] = [.5, 1, 1]
        run = self.root / "changed_target"
        (run / "inputs").mkdir(parents=True)
        p.write_json(run / "inputs/numerical_contract.json", changed)
        with self.assertRaisesRegex(ValueError, "target layout"):
            p.prepare_run(plan, run)
        self.assertFalse(list(run.rglob("*.gem")))

    def test_actual_a162200_compiles_frozen_prepare_and_binding_without_pa_io(self):
        repo = Path(__file__).resolve().parents[4]
        artifact = repo.parent / "artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs"
        binding_path = artifact / "20261012_162200__analysis__simion__mrtof-integer-grid-a-binding/results/field_binding.json"
        if not binding_path.is_file():
            self.skipTest("external successful A binding unavailable")
        if not Path(p.read(binding_path)["parent"]["pa_path"]).is_file():
            self.skipTest("external A parent payload retired; small evidence remains")
        contract_path = repo / "projects/parallel_mirror_dual_stripe_mr_tof/config/simion_candidate_two_zone.json"
        with (patch.object(p, "load_binding", side_effect=load_binding),
              patch.object(p, "_record", side_effect=_record),
              patch.object(p, "verify_record", side_effect=verify_record),
              patch.object(p, "derive_candidate_authority", side_effect=derive_candidate_authority),
              patch.object(p, "build_static_c0_gem", side_effect=build_static_c0_gem)):
            source = load_binding(binding_path)
            values = source["authority"]["analyzer_electrode_voltages_v"]
            request = dict(self.request, source_binding_path=str(binding_path),
                           source_field_manifest=source["manifest"], numerical_contract_path=str(contract_path),
                           candidate_voltages_v=dict(s1=values[10], s2=values[12], p1=values[15], p2=values[16]))
            plan = p.compile_request(request)
            self.assertEqual(plan["candidate_authority"], source["authority"])
            self.assertEqual(plan["execution_order"], ["parent", "window_2", "window_0", "window_1"])
            self.assertEqual(plan["levels"]["window_2"]["dimensions"], [91, 1961, 6501])
            self.assertEqual(plan["levels"]["window_0"]["dimensions"], [51, 2076, 5851])
            run = self.root / "actual_a_pure_prepare"
            (run / "inputs").mkdir(parents=True)
            p.write_json(run / "inputs/numerical_contract.json", p.read(contract_path))
            p.prepare_run(plan, run)
            binding = p.binding_spec(plan, run)
            self.assertEqual([w["name"] for w in binding["refinement_windows"]],
                             [w["name"] for w in source["refinement_windows"]])
            self.assertEqual(binding["instances"][1:], plan["collision_instances"][1:])
            for index, label in enumerate(plan["window_labels"]):
                actual = p.read(Path(binding["refinement_windows"][index]["numerical_plan_path"]))
                parent_label = plan["levels"][label]["parent_label"]
                basename = "c0_static.pa" if parent_label == "parent" else "c0_local.pa"
                self.assertEqual(actual["parent_pa"], str((run / "simion" / parent_label / basename).resolve()))
                self.assertEqual(actual["convergence_v"], 1e-5)
                if index < 2:
                    full = p.read(Path(actual["full_solve_plan_path"]))
                    self.assertEqual(full["box_mm"][3], 2)
                    self.assertEqual(actual["box_mm"][3], 1.28)
                    self.assertEqual(actual["dimensions"], [33, 2076, 5851])
                    self.assertEqual(actual["crop"]["expected_consumer_pa_bytes"], 3206722520)
            self.assertFalse(list(run.rglob("*.pa")))

    def test_new_mirror_offset_uses_normal_refine_without_dropping_declared_bank(self):
        request = dict(self.request, response_basis_paths={'s1': 's1-basis.json', 's2': 's2-basis.json'})
        def basis(path, source):
            result = copy.deepcopy(source)
            result['descriptor_path'] = str(path)
            result['response_basis'] = {'axis': path.name.split('-')[0]}
            return result
        with patch.object(p, '_compile_composition', return_value=None), \
                patch.object(p, 'load_native_response_basis', side_effect=basis):
            plan = p.compile_request(request)
        self.assertEqual(plan['operation'], 'refine')
        self.assertIsNone(plan['response_basis'])
        self.assertEqual(plan['inputs']['response_s1'], 's1-basis.json')
        self.assertEqual(plan['inputs']['response_s2'], 's2-basis.json')
        self.assertIn('s1-basis.json', plan['protected_paths'])
        self.assertEqual(request['response_basis_paths'], {'s1': 's1-basis.json', 's2': 's2-basis.json'})

    def test_all_four_pure_axes_clear_fixed_background_and_preserve_source(self):
        self.three_windows()
        self.authority["analyzer_electrode_voltages_v"] = [float(i) for i in range(20)]
        before = copy.deepcopy(self.source)
        for axis, ids in p.PS_GROUPS.items():
            with self.subTest(axis=axis):
                request = {k: v for k, v in self.request.items() if k != "candidate_voltages_v"}
                request["response_axis"] = axis
                plan = p.compile_request(request)
                self.assertEqual(plan["source_authority"], self.authority)
                actual = plan["candidate_authority"]
                self.assertEqual(actual["analyzer_electrode_voltages_v"],
                                 [10000.0 if i+1 in ids else 0.0 for i in range(20)])
                self.assertTrue(all(item["voltage_v"] == 0 for item in actual["component_voltages_v"]))
                self.assertEqual(plan["resolved_geometry"], self.geometry)
                self.assertFalse(plan["fly_authorized"])
                self.assertEqual(plan["response_basis"]["normalization_v"], 10000)
                self.assertEqual(plan["execution_order"], ["parent", "window_2", "window_0", "window_1"])
                self.assertTrue(all(x["response_basis"] == plan["response_basis"] for x in plan["levels"].values()))
                run = self.root / ("basis_"+axis)
                (run / "inputs").mkdir(parents=True)
                p.write_json(run / "inputs/numerical_contract.json", self.contract)
                p.prepare_run(plan, run)
                self.assertEqual(p.read(run / "inputs/source_authority.json"), self.authority)
                self.assertEqual(p.read(run / "inputs/frozen_input.json"), actual)
                descriptor = p.binding_spec(plan, run)
                self.assertEqual(descriptor["role"], "mrtof_native_static_field_response_basis")
                descriptor_path = run / "response_basis.json"
                p.write_json(descriptor_path, descriptor)
                with self.assertRaisesRegex(ValueError, "unsupported"):
                    load_binding(descriptor_path)
                self.assertFalse(list(run.rglob("*.pa")))
        self.assertEqual(self.source, before)

    def te1_reference(self, direction=None):
        path = self.root / "te1_reference.json"
        direction = direction if direction is not None else [.26534181722826355,
            -1.3064907730209914, .8123479538407015, .7579824137295434]
        base = [0., -5920.610006092399, -2612.9815460419827, 4190.462801307053, 6029.159819776669]
        p.write_json(path, dict(schema_version=1, role="mrtof_terminal_time_mirror_voltage_variation",
            status="screening_candidate_materialized", mode="TE1", coordinate=1.,
            qualification="diagnostic_only__complete_3d_detector_response_pending",
            base_mirror_voltages_v=base, voltage_delta_v=direction,
            target_mirror_voltages_v=[0., *[v+d for v, d in zip(base[1:], direction, strict=True)]]))
        return path

    def test_te1_pure_direction_clears_background_and_covers_both_mirrors(self):
        self.three_windows()
        reference = self.te1_reference()
        request = {k:v for k,v in self.request.items() if k != "candidate_voltages_v"}
        request.update(response_axis="te1", te1_reference_path=str(reference))
        before = copy.deepcopy(self.source)
        plan = p.compile_request(request)
        basis = plan["response_basis"]
        excitation = p._te1_excitation(basis)
        self.assertEqual(max(abs(v) for v in excitation), 10000.)
        self.assertEqual(plan["candidate_authority"]["analyzer_electrode_voltages_v"], excitation*2+[0.]*10)
        self.assertTrue(all(v["voltage_v"] == 0 for v in plan["candidate_authority"]["component_voltages_v"]))
        self.assertEqual(basis["physical_electrode_ids"], [2,3,4,5,7,8,9,10])
        self.assertEqual(plan["execution_order"], ["parent", "window_2", "window_0", "window_1"])
        self.assertEqual(plan["inputs"]["te1_reference"], str(reference.resolve()))
        self.assertTrue(all(v["response_basis"] == basis for v in plan["levels"].values()))
        self.assertFalse(plan["fly_authorized"])
        run = self.root/"pure_te1"
        (run/"inputs").mkdir(parents=True)
        p.write_json(run/"inputs/numerical_contract.json", self.contract)
        (run/"inputs/te1_reference.json").write_bytes(reference.read_bytes())
        p.prepare_run(plan, run)
        descriptor = p.binding_spec(plan, run)
        self.assertEqual(descriptor["direction_reference_path"], str((run/"inputs/te1_reference.json").resolve()))
        self.assertEqual(self.source, before)
        self.assertFalse(list(run.rglob("*.pa")))

    def test_te1_coefficients_use_actual_nonzero_mirror_anchor_not_absolute_coordinate(self):
        reference = self.te1_reference()
        basis = p._te1_basis_metadata(reference)
        data = p.read(reference)
        direction = data["voltage_delta_v"]
        c0 = -22.894154431673797
        base = copy.deepcopy(self.authority)
        baseline = [0., *[v+c0*d for v,d in zip(data["base_mirror_voltages_v"][1:], direction, strict=True)]]
        base["analyzer_electrode_voltages_v"][:10] = baseline*2
        target_ps = {axis:0. for axis in p.PS_GROUPS}
        for delta in (0., -.988552922784, .988552922784):
            target = [0., *[v+delta*d for v,d in zip(baseline[1:], direction, strict=True)]]
            plan = p.compile_response_coefficients(base, target_ps, ["te1"],
                mirror_voltages_v=target, te1_basis=basis)
            self.assertAlmostEqual(plan["coefficients"]["te1"], delta*max(abs(d) for d in direction)/10000., places=15)
            self.assertEqual(plan["target_authority"]["analyzer_electrode_voltages_v"][:10], target*2)
        bad = target.copy(); bad[4] += .01
        with self.assertRaisesRegex(ValueError, "incompatible"):
            p.compile_response_coefficients(base, target_ps, ["te1"], mirror_voltages_v=bad, te1_basis=basis)
        for change in ({"normalization_v":0}, {"normalization_v":1},
                       {"direction_v_per_coordinate":[0.,0.,0.,0.]},
                       {"direction_v_per_coordinate":[1.,2.,3.,float("nan")]}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "normalization"):
                p._te1_excitation(dict(basis, **change))
        with self.assertRaises(ValueError):
            p._te1_basis_metadata(self.te1_reference([0.,0.,0.,0.]))

    def test_te1_reference_is_required_only_for_pure_te1_and_frozen_before_prepare(self):
        request = {k:v for k,v in self.request.items() if k != "candidate_voltages_v"}
        for change in ({"response_axis":"te1"}, {"response_axis":"s1", "te1_reference_path":"unused"},
                       {"response_axis":"te1", "te1_reference_path":"unused", "candidate_voltages_v":self.request["candidate_voltages_v"]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                p.compile_request(dict(request, **change))

    def test_te1_e_closure_ids_consume_the_same_paired_e_drive(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_candidate_geometry import _mirror_ground_shield_lines
        basis = p._te1_basis_metadata(self.te1_reference())
        authority = p._response_authority(self.authority, basis)
        geometry = dict(mirror_inner_shield_slot=[-2,0,-1,2,1,1], mirror_ground_shields=[],
                        mirror_e_closures=[dict(id=5,box=[-1,0,2,1,1,3]), dict(id=10,box=[-1,0,-3,1,1,-2])])
        lines = _mirror_ground_shield_lines(geometry)
        self.assertIn("  e(5) {", lines)
        self.assertIn("  e(10) {", lines)
        self.assertEqual(authority["analyzer_electrode_voltages_v"][4], authority["analyzer_electrode_voltages_v"][9])
        self.assertNotEqual(authority["analyzer_electrode_voltages_v"][4], 0.)

    def test_response_axis_rejects_workpoint_updates_and_changed_baseline_layout(self):
        request = {k: v for k, v in self.request.items() if k != "candidate_voltages_v"}
        for extra in ({"response_axis": None}, {"response_axis": "mirror"},
                      {"response_axis": "s1", "candidate_voltages_v": self.request["candidate_voltages_v"]},
                      {"response_axis": "s1", "mirror_voltage_variation_path": "unused"}):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, "response_axis"):
                p.compile_request(dict(request, **extra))
        layout = self.contract["simion"]["numerical_profiles"]["native_static_field"]["target_layout"]
        layout["windows"][0]["pitch_mm"] = [.5, 1, 1]
        p.write_json(self.contract_path, self.contract)
        with self.assertRaisesRegex(ValueError, "actual baseline"):
            p.compile_request(dict(request, response_axis="s1"))
        layout["windows"][0]["pitch_mm"] = [1, 1, 1]
        p.write_json(self.contract_path, self.contract)
        self.source["refinement_windows"][0]["native_solver_numerics"]["convergence_v"] = 1e-7
        with self.assertRaisesRegex(ValueError, "stopping contract"):
            p.compile_request(dict(request, response_axis="s1"))

    def test_prepare_rejects_contaminated_basis_or_fly_authorization(self):
        request = {k: v for k, v in self.request.items() if k != "candidate_voltages_v"}
        plan = p.compile_request(dict(request, response_axis="s1"))
        run = self.root / "bad_basis"
        (run / "inputs").mkdir(parents=True)
        p.write_json(run / "inputs/numerical_contract.json", self.contract)
        for change in ("background", "normalization", "fly"):
            bad = copy.deepcopy(plan)
            if change == "background":
                bad["candidate_authority"]["component_voltages_v"][0]["voltage_v"] = 1
            elif change == "normalization":
                bad["response_basis"]["normalization_v"] = 1
            else:
                bad["fly_authorized"] = True
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "pure response"):
                p.prepare_run(bad, run)
        self.assertFalse(list(run.rglob("*.gem")))

    def test_pure_response_coefficients_use_delta_over_normalization(self):
        base = copy.deepcopy(self.authority)
        for axis, ids in p.PS_GROUPS.items():
            for physical_id in ids:
                base["analyzer_electrode_voltages_v"][physical_id-1] = {"s1": -27., "s2": 55., "p1": 190., "p2": -190.}[axis]
        target = {"s1": -26., "s2": 53., "p1": 190., "p2": -190.}
        plan = p.compile_response_coefficients(base, target, ["s1", "s2"])
        self.assertEqual(plan["coefficients"], {"s1": .0001, "s2": -.0002})
        self.assertEqual(plan["target_authority"]["component_voltages_v"], base["component_voltages_v"])
        self.assertEqual(plan["target_authority"]["analyzer_electrode_voltages_v"][:10], base["analyzer_electrode_voltages_v"][:10])
        with self.assertRaisesRegex(ValueError, "without a pure response"):
            p.compile_response_coefficients(base, dict(target, p1=191), ["s1", "s2"])

    def test_actual_zero_voltage_bodies_and_all_unit_axis_geometry_are_retained(self):
        repo = Path(__file__).resolve().parents[4]
        binding_path = repo.parent / "artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261012_162200__analysis__simion__mrtof-integer-grid-a-binding/results/field_binding.json"
        if not binding_path.is_file():
            self.skipTest("external A geometry unavailable")
        if not Path(p.read(binding_path)["parent"]["pa_path"]).is_file():
            self.skipTest("external A parent payload retired; small evidence remains")
        source = load_binding(binding_path)
        original = p.read(Path(source["sources"]["numerical_plan"]))
        grid = {k: original[k] for k in ("box_mm", "pitch_mm", "dimensions", "mirror_axes", "surface")}
        base, _ = build_static_c0_gem(source["geometry"], source["authority"], grid, boundary_mode="grounded_enclosure")
        import re
        mask = lambda text: re.sub(r"\be\([^)]*\)", "e(PHYSICAL)", text)
        for axis, ids in p.PS_GROUPS.items():
            authority = p._pure_axis_authority(source["authority"], axis)
            gem, _ = build_static_c0_gem(source["geometry"], authority, grid, boundary_mode="grounded_enclosure")
            self.assertEqual(mask(gem), mask(base))
            self.assertEqual(gem.count("e(10000)"), len(ids))
            self.assertGreater(gem.count("e(0)"), 0)

    def test_composition_requires_explicit_nonempty_axis_map_and_no_basis_excitation(self):
        for paths in ({}, {"mirror": "x"}, {"s1": ""}, {"s1": None}):
            with self.subTest(paths=paths), self.assertRaisesRegex(ValueError, "response_basis_paths"):
                p.compile_request(dict(self.request, response_basis_paths=paths))
        request = {k:v for k,v in self.request.items() if k != "candidate_voltages_v"}
        with self.assertRaisesRegex(ValueError, "response_axis"):
            p.compile_request(dict(request, response_axis="s1", response_basis_paths={"s1": "x"}))



class IonProcessorResponseProviderTest(unittest.TestCase):
    """Five tiny sealed fields exercise real provider, composer and IP loader."""

    def test_ip_gem_preserves_fifteen_holey_bodies_with_pure_prism_excitation(self):
        geometry = {"detector": {"box": [-1,-1,4,1,1,5]},
                    "ion_processor_electrodes": [dict(electrode_id=i, solids=[
                        dict(shape="box", min_mm=[0,-1,-1], max_mm=[1,1,1])], cutouts=[
                        dict(shape="box", min_mm=[.2,-.5,-2], max_mm=[.8,.5,2])]) for i in range(1,16)]}
        source = dict(assembly={"accelerator_provider": p.IP_PROVIDER},
                      analyzer_electrode_voltages_v=[0.]*20,
                      component_voltages_v=[dict(component_namespace="ion_processor", component_electrode_id=i,
                                                voltage_v=4000.) for i in range(1,16)] + [
                          dict(component_namespace="detector", component_electrode_id=25, voltage_v=0.)])
        grid = dict(box_mm=[0,-2,-2,2,2,6], pitch_mm=[1,1,1], dimensions=[3,5,9])
        for axis, physical_id in (("p1",16),("p2",17)):
            with self.subTest(axis=axis), patch(
                "projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_assembly._analyzer_geometry_lines",
                return_value=[f"e({i}) {{ box3d(0,0,0,1,1,1) }}" for i in (16,17)]):
                gem, _ = p._static_gem(geometry, p._pure_axis_authority(source, axis), grid,
                                       boundary_mode="x_mirror_five_faces")
                self.assertEqual(gem.count("namespace=ion_processor id="),15)
                self.assertEqual(gem.count("notin_inside"),15)
                self.assertEqual(gem.count("e(10000)"),1)
                self.assertEqual(p._pure_axis_authority(source, axis)["analyzer_electrode_voltages_v"][physical_id-1],10000.)
                self.assertNotIn("4000",gem)

    def fixture(self, root):
        import shutil
        import struct
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_static_field_binding import IonProcessorNativeBindingTest
        geometry_lines = patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_assembly._analyzer_geometry_lines",
                               return_value=["e(16) { box3d(0,0,0,1,1,1) }", "e(17) { box3d(1,1,1,2,2,2) }"])
        geometry_lines.start()
        self.addCleanup(geometry_lines.stop)
        helper = IonProcessorNativeBindingTest()
        descriptor, path, owner = helper.fixture(root, detector_box=[-1, -1, -1, 1, 1, 1])
        contract = root / "contract.json"
        # Deliberately unrelated nominal OA grid: actual sealed source wins.
        p.write_json(contract, {"simion": {"numerical_profiles": {
            "native_static_field": {"refine": {"convergence_v": 1e-5},
                                    "target_layout": {"parent": {"pitch_mm": [1,1,1]}, "windows": []}},
            "grid_generation": {"spacing_quantum_mm": .01}}}})
        template = descriptor["refinement_windows"][0]
        for name in ("positive_integer_grid_a", "negative_integer_grid_a", "covered_local"):
            directory = root / name
            shutil.copytree(root / "local", directory)
            level = copy.deepcopy(template)
            for key in ("pa_path", "surface_path", "voltage_authority_path", "geometry_authority_path", "numerical_plan_path"):
                level[key] = str(directory / Path(level[key]).name)
            level["name"] = name
            descriptor["refinement_windows"].append(level)
        for level in (descriptor["parent"], *descriptor["refinement_windows"]):
            plan_path = Path(level["numerical_plan_path"])
            plan = p.read(plan_path)
            plan.update(numerical_contract_path=str(contract), **p.resolve_native_refine_numerics(p.read(contract)),
                        resource_budget={"cpu_cores": 1, "memory_bytes": 1024**3, "io_slots": 1},
                        resource_limits={"automatic_retry_count": 0})
            p.write_json(plan_path, plan)
            header = PaHeader(-2, 1, 100000, *plan["dimensions"], 1, *plan["pitch_mm"])
            # One conductor marker plus ordinary vacuum; fractional bytes remain identical.
            values = [200001.0] + [2.0] * (header.node_count - 1)
            Path(level["pa_path"]).write_bytes(header.pack() + struct.pack('<'+'d'*len(values), *values))
        # A nested local parent chain is distinct from field priority.
        covered = descriptor["refinement_windows"][-1]
        for level in descriptor["refinement_windows"][1:3]:
            plan_path = Path(level["numerical_plan_path"])
            plan = p.read(plan_path)
            plan.update(parent_pa=covered["pa_path"], parent_manifest=str(owner))
            p.write_json(plan_path, plan)
        path.write_text(json.dumps(descriptor), encoding="utf-8")
        helper.seal(root, owner)
        request = dict(schema_version=1, role=p.ROLE, run_id="test_ip_response",
                       source_binding_path=str(path), source_field_manifest=str(owner),
                       numerical_contract_path=str(contract))
        return helper, descriptor, path, owner, request

    def freeze(self, root, plan):
        import shutil
        (root / "inputs").mkdir(parents=True)
        (root / "results").mkdir()
        for key, source in plan["inputs"].items():
            shutil.copyfile(source, root / "inputs" / (key + Path(source).suffix))
        return p.prepare_run(plan, root)

    def publish(self, helper, root, plan):
        descriptor = p.binding_spec(plan, root)
        path = root / "results" / ("response_basis.json" if plan.get("response_basis") else "field_binding.json")
        p.write_json(path, descriptor)
        helper.seal(root, root / "run_manifest.json")
        return path

    def test_ip_axes_compose_preserves_full_operator_and_collision_geometry(self):
        import shutil
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import load_native_response_basis
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider import candidate_authority
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"; source.mkdir()
            helper, descriptor, path, _, request = self.fixture(source)
            baseline = load_binding(path)
            responses = {}
            for axis in p.PS_GROUPS:
                with self.subTest(axis=axis):
                    plan = p.compile_request(dict(request, response_axis=axis))
                    self.assertFalse(plan["fly_authorized"])
                    self.assertEqual(plan["candidate_authority"], p._pure_axis_authority(baseline["authority"], axis))
                    self.assertEqual(len(plan["levels"]), 5)
                    self.assertEqual([x["pitch_mm"] for x in plan["levels"].values()],
                                     [baseline["grid"]["pitch_mm"]] + [w["grid"]["pitch_mm"] for w in baseline["refinement_windows"]])
                    child = root / axis
                    self.freeze(child, plan)
                    # Tiny fake vendor materialization, not a field solve claim.
                    for label, original in zip(["parent", *plan["window_labels"]], [descriptor["parent"], *descriptor["refinement_windows"]], strict=True):
                        target = child / "simion" / label / ("c0_static.pa" if label == "parent" else "c0_local.pa")
                        shutil.copyfile(original["pa_path"], target)
                        shutil.copyfile(original["surface_path"], str(target)+'-surf')
                    response_path = self.publish(helper, child, plan)
                    resolved = load_native_response_basis(response_path, baseline)
                    self.assertEqual(resolved["response_basis"]["axis"], axis)
                    with self.assertRaises(ValueError):
                        load_binding(response_path)
                    authority_path = child / "inputs/frozen_input.json"
                    clean = p.read(authority_path)
                    bad = copy.deepcopy(clean)
                    bad["component_voltages_v"][0]["voltage_v"] = 1.
                    p.write_json(authority_path, bad)
                    helper.seal(child, child / "run_manifest.json")
                    with self.assertRaises(ValueError):
                        load_native_response_basis(response_path, baseline)
                    p.write_json(authority_path, clean)
                    helper.seal(child, child / "run_manifest.json")
                    responses[axis] = str(response_path)
            target = dict(s1=2, s2=3, p1=4, p2=-5)
            plan = p.compile_request(dict(request, candidate_voltages_v=target, response_basis_paths=responses))
            self.assertEqual(plan["operation"], "compose")
            self.assertEqual(plan["candidate_authority"], candidate_authority(baseline["authority"], target))
            output = root / "composed"
            self.freeze(output, plan)
            p.compose_run(plan, output)
            result = load_binding(self.publish(helper, output, plan))
            self.assertEqual(result["authority"]["component_voltages_v"], baseline["authority"]["component_voltages_v"])
            self.assertEqual(result["instances"][0]["pa_path"], result["sources"]["scalar_pa"])
            self.assertEqual(result["instances"][1:], baseline["instances"][1:])
            self.assertEqual(result["grid"], baseline["grid"])
            self.assertEqual([w["grid"] for w in result["refinement_windows"]], [w["grid"] for w in baseline["refinement_windows"]])
            self.assertFalse(result["refine_performed"])
            import struct
            data = Path(result["sources"]["scalar_pa"]).read_bytes()
            # Same affine V operation at a vacuum node; no numerical solver involved.
            self.assertAlmostEqual(struct.unpack_from('<d', data, 64)[0], 2.0008, places=12)

class IonProcessorFineExtensionTest(unittest.TestCase):
    """Real tiny PA/manifest fixtures; no vendor execution or physics qualification."""

    def fixture(self, root):
        helper, descriptor, _, owner, request = IonProcessorResponseProviderTest.fixture(self, root)
        parent = descriptor["parent"]
        parent["grid"]["origin_mm"][2] = -8
        parent["grid"]["dimensions"][2] += 3
        plan_path = Path(parent["numerical_plan_path"])
        plan = p.read(plan_path)
        plan["box_mm"][2] = -8
        plan["dimensions"] = parent["grid"]["dimensions"]
        p.write_json(plan_path, plan)
        header = PaHeader(-2, 1, 100000, *plan["dimensions"], 1, *plan["pitch_mm"])
        Path(parent["pa_path"]).write_bytes(header.pack() + b"\0" * (header.node_count*8))
        for i in (0, 1):
            descriptor["instances"][i]["origin_mm"] = copy.deepcopy(parent["grid"]["origin_mm"])
        descriptor["instances"][2]["origin_mm"] = copy.deepcopy(descriptor["refinement_windows"][0]["grid"]["origin_mm"])
        (root / "results").mkdir()
        path = root / "results/field_binding.json"
        p.write_json(path, descriptor)
        helper.seal(root, owner)
        request.update(source_binding_path=str(path), reuse_source_levels=["parent", "window_1", "window_2", "window_3"],
                       ion_processor_local_domain_update=dict(solve_z_min_mm=-7, active_z_min_mm=-5))
        return helper, descriptor, path, owner, request

    def materialize(self, root, plan, helper):
        IonProcessorResponseProviderTest.freeze(self, root, plan)
        fine = plan["levels"]["window_0"]
        header = PaHeader(-2, 1, 100000, *fine["dimensions"], 1, *fine["pitch_mm"])
        (root / "simion/window_0/c0_local.pa").write_bytes(header.pack() + b"\0"*(header.node_count*8))
        (root / "simion/window_0/c0_local.pa-surf").write_bytes(b"fractional")
        (root / "simion/ip_collision/ip_collision.pa").write_bytes(header.pack() + b"\0"*(header.node_count*8))
        return IonProcessorResponseProviderTest.publish(self, helper, root, plan)

    def test_extension_reuses_four_levels_strict_load_and_next_ordinary_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "source"; source.mkdir()
            helper, original, _, owner, request = self.fixture(source)
            plan = p.compile_request(request)
            self.assertEqual([k for k, v in plan["levels"].items() if "reuse_source" not in v], ["window_0"])
            self.assertNotIn("collision_build", plan)
            self.assertNotIn("detector_build", plan)
            self.assertEqual(plan["committed_new_bytes"], sum(plan["levels"][k]["committed_new_bytes"]
                for k in plan["levels"]) + plan["ip_collision_build"]["committed_new_bytes"])
            output = root / "extension"
            path = self.materialize(output, plan, helper)
            descriptor = p.read(path)
            self.assertEqual(descriptor["parent"], original["parent"])
            self.assertEqual(descriptor["refinement_windows"][1:], original["refinement_windows"][1:])
            self.assertEqual([descriptor["instances"][i] for i in (0, 1, 3)],
                             [original["instances"][i] for i in (0, 1, 3)])
            loaded = load_binding(path)
            self.assertEqual(loaded["manifest"], str(owner))
            self.assertEqual(loaded["descriptor_owner"], str(output / "run_manifest.json"))
            self.assertEqual(loaded["refinement_windows"][0]["grid"]["origin_mm"][2], -7)
            self.assertEqual(loaded["instances"][2]["manifest"], loaded["descriptor_owner"])
            self.assertFalse((output / "simion/parent").exists())
            next_request = dict(schema_version=1, role=p.ROLE, source_binding_path=str(path),
                source_field_manifest=loaded["descriptor_owner"], numerical_contract_path=request["numerical_contract_path"],
                candidate_voltages_v={"s1": 0., "s2": 0., "p1": 1., "p2": 0.})
            next_plan = p.compile_request(next_request)
            self.assertEqual(next_plan["levels"]["window_0"]["box_mm"][2], -7)
            self.assertEqual(next_plan["candidate_authority"]["component_voltages_v"], loaded["authority"]["component_voltages_v"])
            IonProcessorResponseProviderTest.freeze(self, root / "next", next_plan)

    def test_closed_extension_request_rejects_other_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            _, _, _, _, request = self.fixture(source)
            mutations = [dict(candidate_voltages_v={"s1": 0., "s2": 0., "p1": 1., "p2": 0.}),
                         dict(response_axis="p1"), dict(response_basis_paths={}), dict(geometry_contract_path="other"),
                         dict(consumer_view_source_path="other"), dict(reuse_source_levels=["parent"])]
            for change in mutations:
                with self.subTest(change=list(change)), self.assertRaises(ValueError):
                    p.compile_request(dict(request, **change))
            for update in [dict(solve_z_min_mm=-5, active_z_min_mm=-5),
                           dict(solve_z_min_mm=-7, active_z_min_mm=-3),
                           dict(solve_z_min_mm=-9, active_z_min_mm=-5),
                           dict(solve_z_min_mm=-7.1, active_z_min_mm=-5),
                           dict(solve_z_min_mm=-7, active_z_min_mm=-5, pitch_mm=[.5, 1, .5])]:
                with self.subTest(update=update), self.assertRaises(ValueError):
                    p.compile_request(dict(request, ion_processor_local_domain_update=update))

    def test_resealed_lineage_and_reused_field_tampering_are_rejected(self):
        for mutation in ("lineage", "route", "pitch", "parent", "voltage", "geometry", "reuse", "occupancy", "scalar_alias"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); source = root / "source"; source.mkdir()
                helper, _, _, _, request = self.fixture(source)
                plan = p.compile_request(request)
                output = root / "extension"; path = self.materialize(output, plan, helper)
                descriptor = p.read(path)
                fine = descriptor["refinement_windows"][0]
                if mutation == "lineage":
                    target = output / "inputs/ip_fine_domain_update.json"
                    value = p.read(target); value["update"]["solve_z_min_mm"] -= 1
                    p.write_json(target, value); descriptor["local_domain_update"] = helper.record(target)
                elif mutation == "route":
                    fine["active_box_mm"][0][0] += .5
                elif mutation in ("pitch", "parent"):
                    target = Path(fine["numerical_plan_path"]); value = p.read(target)
                    if mutation == "pitch":
                        fine["grid"]["pitch_mm"][2] = value["pitch_mm"][2] = .5
                    else:
                        value["parent_pa"] = fine["pa_path"]
                    p.write_json(target, value)
                elif mutation in ("voltage", "geometry"):
                    target = Path(fine["voltage_authority_path"] if mutation == "voltage" else fine["geometry_authority_path"])
                    value = p.read(target)
                    if mutation == "voltage":
                        value["analyzer_electrode_voltages_v"][15] += 1
                    else:
                        value["frame_id"] = "changed"
                    p.write_json(target, value)
                elif mutation == "reuse":
                    descriptor["refinement_windows"][1]["active_box_mm"][1][0] += .5
                elif mutation == "occupancy":
                    descriptor["instances"][2] = copy.deepcopy(descriptor["instances"][1])
                    descriptor["instances"][2]["role"] = "ion_processor_collision"
                else:
                    descriptor["instances"][2]["pa_path"] = fine["pa_path"]
                p.write_json(path, descriptor); helper.seal(output, output / "run_manifest.json")
                with self.assertRaises((ValueError, AssertionError)):
                    load_binding(path)


class IonProcessorFineResponseReuseTest(unittest.TestCase):
    """Same sealed operator reuse, with real tiny binary composition and strict loaders."""

    def full_fields(self, root, plan, helper):
        import struct
        IonProcessorResponseProviderTest.freeze(self, root, plan)
        source = load_binding(Path(plan["inputs"]["source_binding"]))
        surfaces = dict(zip(["parent", *plan["window_labels"]], [source, *source["refinement_windows"]], strict=True))
        for label, spec in plan["levels"].items():
            if "reuse_source" in spec:
                continue
            header = PaHeader(-2, 1, 100000, *spec["dimensions"], 1, *spec["pitch_mm"])
            directory = root / "simion" / label
            filename = "c0_static.pa" if label == "parent" else "c0_local.pa"
            raw = Path(surfaces[label]["sources"]["scalar_pa"]).read_bytes()[p.HEADER.size:]
            source_values = struct.unpack('<'+'d'*header.node_count, raw)
            values = [200001. if value > 100000 else 1. for value in source_values]
            (directory / filename).write_bytes(header.pack() + struct.pack('<'+'d'*len(values), *values))
            (directory / (filename + "-surf")).write_bytes(Path(surfaces[label]["sources"]["surface"]).read_bytes())
        return IonProcessorResponseProviderTest.publish(self, helper, root, plan)

    def chain(self, root):
        source = root / "source"; source.mkdir()
        helper, _, path, _, extension_request = IonProcessorFineExtensionTest.fixture(self, source)
        base_request = {k: v for k, v in extension_request.items()
                        if k not in {"ion_processor_local_domain_update", "reuse_source_levels"}}
        banks = {}
        for axis in ("p1", "p2"):
            plan = p.compile_request(dict(base_request, response_axis=axis))
            banks[axis] = self.full_fields(root / axis, plan, helper)
        candidate_request = dict(base_request, candidate_voltages_v={"s1": 0., "s2": 0., "p1": 342., "p2": 0.},
                                 response_basis_paths={k: str(v) for k, v in banks.items()})
        candidate_plan = p.compile_request(candidate_request)
        candidate = root / "candidate"
        IonProcessorResponseProviderTest.freeze(self, candidate, candidate_plan)
        p.compose_run(candidate_plan, candidate)
        candidate_path = IonProcessorResponseProviderTest.publish(self, helper, candidate, candidate_plan)
        extension_request.update(source_binding_path=str(candidate_path), source_field_manifest=str(candidate / "run_manifest.json"))
        extension_plan = p.compile_request(extension_request)
        extension = root / "extension"
        extension_path = IonProcessorFineExtensionTest.materialize(self, extension, extension_plan, helper)
        return helper, banks, extension_path, extension_request

    def test_two_axes_reuse_four_pure_fields_and_compose_against_extended_ordinary(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import load_native_response_basis
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper, banks, source_path, extension_request = self.chain(root)
            source = load_binding(source_path)
            new_banks = {}
            for axis in ("p1", "p2"):
                request = dict(schema_version=1, role=p.ROLE, response_axis=axis,
                    source_binding_path=str(source_path), source_field_manifest=source["descriptor_owner"],
                    numerical_contract_path=extension_request["numerical_contract_path"],
                    reuse_source_levels=["parent", "window_1", "window_2", "window_3"],
                    reuse_response_basis_path=str(banks[axis]))
                plan = p.compile_request(request)
                self.assertEqual([k for k,v in plan["levels"].items() if "reuse_source" not in v], ["window_0"])
                self.assertFalse(any(k.endswith("_build") for k in plan))
                self.assertFalse(plan["fly_authorized"])
                output = root / ("new_" + axis)
                new_path = self.full_fields(output, plan, helper)
                new_banks[axis] = str(new_path)
                pure = load_native_response_basis(new_path, source)
                self.assertEqual(pure["source_authority"], source["authority"])
                self.assertEqual(pure["instances"][1:], source["instances"][1:])
                self.assertEqual(p.read(new_path)["parent"], p.read(banks[axis])["parent"])
                self.assertFalse((output / "simion/parent").exists())
                with self.assertRaises(ValueError):
                    load_binding(new_path)
                for change in (dict(response_axis="s1"), dict(candidate_voltages_v={}),
                               dict(reuse_source_levels=["parent"]), dict(response_axis="p2" if axis=="p1" else "p1")):
                    with self.subTest(change=change), self.assertRaises(ValueError):
                        p.compile_request(dict(request, **change))
                profile_path = output / "inputs/ip_fine_response_reuse.json"
                fine_plan_path = output / "inputs/window_0_plan.json"
                snapshots = {f: f.read_bytes() for f in (new_path, profile_path, fine_plan_path)}
                for mutation in ("lineage_axis", "lineage_owner", "route", "parent", "fly"):
                    for f, content in snapshots.items():
                        f.write_bytes(content)
                    descriptor = p.read(new_path)
                    if mutation.startswith("lineage"):
                        profile = p.read(profile_path)
                        if mutation == "lineage_axis":
                            profile["axis"] = "p2" if axis == "p1" else "p1"
                        else:
                            profile["source_basis_manifest"]["sha256"] = "0"*64
                        p.write_json(profile_path, profile)
                        descriptor["response_level_reuse"] = helper.record(profile_path)
                    elif mutation == "route":
                        descriptor["refinement_windows"][0]["active_box_mm"][2][0] += .5
                    elif mutation == "parent":
                        fine_plan = p.read(fine_plan_path)
                        fine_plan["parent_pa"] = source["sources"]["scalar_pa"]
                        p.write_json(fine_plan_path, fine_plan)
                    else:
                        descriptor["fly_authorized"] = True
                    p.write_json(new_path, descriptor); helper.seal(output, output / "run_manifest.json")
                    with self.subTest(axis=axis, mutation=mutation), self.assertRaises((ValueError, AssertionError)):
                        load_native_response_basis(new_path, source)
                for f, content in snapshots.items():
                    f.write_bytes(content)
                helper.seal(output, output / "run_manifest.json")
            candidate_request = dict(schema_version=1, role=p.ROLE, source_binding_path=str(source_path),
                source_field_manifest=source["descriptor_owner"], numerical_contract_path=extension_request["numerical_contract_path"],
                candidate_voltages_v={"s1": 0., "s2": 0., "p1": 350., "p2": -5.}, response_basis_paths=new_banks)
            plan = p.compile_request(candidate_request)
            output = root / "new_candidate"
            IonProcessorResponseProviderTest.freeze(self, output, plan)
            p.compose_run(plan, output)
            path = IonProcessorResponseProviderTest.publish(self, helper, output, plan)
            self.assertEqual(load_binding(path)["refinement_windows"][0]["grid"], source["refinement_windows"][0]["grid"])


class RefinedPayloadPublicationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "results").mkdir()
        self.plan = dict(operation="refine", execution_order=["parent", "window_0"],
                         levels=dict(parent={}, window_0={}))
        self.header = PaHeader(-2, 1, 100., 2, 2, 2, 1, .1, .1, .1)
        for label in self.plan["execution_order"]:
            path = self.payload_path(label)
            path.parent.mkdir(parents=True)
            # Encoded negative electrode -50 V is raw150 with max_voltage100.
            path.write_bytes(self.header.pack() + struct.pack('<8d', 0., 1., -2., 150., 0., 2., -1., 0.))

    def payload_path(self, label):
        return self.root / "simion" / label / ("c0_static.pa" if label == "parent" else "c0_local.pa")

    def invoke_binding(self):
        with patch('sys.argv', ["provider", "--plan", str(self.root / "plan.json"),
                               "--run-directory", str(self.root), "--binding"]), patch.object(p, "read", return_value=self.plan):
            p.main()

    def test_binding_publication_records_complete_new_refine_validation(self):
        with patch.object(p, "binding_spec", return_value={"role": "fixture_binding"}):
            self.invoke_binding()
        receipt = json.loads((self.root / "results/pa_payload_validation.json").read_text())
        self.assertEqual(set(receipt["levels"]), {"parent", "window_0"})
        self.assertTrue(all(row["finite_nodes"] == row["expected_nodes"] == 8 for row in receipt["levels"].values()))
        self.assertTrue((self.root / "results/field_binding.json").is_file())

    def test_invalid_new_refine_blocks_binding_publication(self):
        for value in (float('nan'), float('inf'), -float('inf'), -101., 301.):
            with self.subTest(value=value):
                self.payload_path("window_0").write_bytes(self.header.pack() + struct.pack('<8d', *([0.]*7 + [value])))
                with patch.object(p, "binding_spec", side_effect=AssertionError('invalid PA reached publication')):
                    with self.assertRaisesRegex(ValueError, 'payload validation failed'):
                        self.invoke_binding()
                self.assertFalse((self.root / "results/field_binding.json").exists())
                self.assertFalse((self.root / "results/pa_payload_validation.json").exists())

    def test_reused_sealed_level_is_not_scanned(self):
        self.plan["levels"]["parent"]["reuse_source"] = {"pa_path": str(self.payload_path("parent"))}
        self.payload_path("parent").write_bytes(b"sealed source outside this new-output check")
        receipt = p.validate_refined_field_payloads(self.plan, self.root)
        self.assertEqual(receipt["reused_levels"], ["parent"])
        self.assertEqual(set(receipt["levels"]), {"window_0"})

    def test_composition_publication_does_not_rescan_validated_output(self):
        self.plan["operation"] = "compose"
        with patch.object(p, "validate_refined_field_payloads", side_effect=AssertionError('duplicate composition scan')):
            with patch.object(p, "binding_spec", return_value={"role": "fixture_binding"}):
                self.invoke_binding()
        self.assertFalse((self.root / "results/pa_payload_validation.json").exists())
        self.assertTrue((self.root / "results/field_binding.json").is_file())


class NativeProviderCloseoutTest(unittest.TestCase):
    """Execute the actual runner catch/finally, without entering a native stage."""

    def closeout_fixture(self, failure: str, *, primary_error: bool = True,
                         normal_release_index: int | None = None) -> dict:
        import shutil
        import subprocess
        import sys

        powershell = shutil.which("pwsh")
        if powershell is None:
            self.skipTest("PowerShell 7 required")
        repo = Path(__file__).resolve().parents[4]
        runner = repo / "projects/parallel_mirror_dual_stripe_mr_tof/simion/run_native_static_field_provider.ps1"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "closeout.ps1"
            script.write_text(r"""
param($Runner,$Root,$FailureMode,$python,$PrimaryError,$NormalReleaseIndex)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$outer=@($ast.EndBlock.Statements|Where-Object {$_-is[Management.Automation.Language.TryStatementAst]})
if($outer.Count-ne1){throw 'Expected one production terminal boundary'}
# Install only project-local functions; shared boundaries below are explicit seams.
foreach($fn in @($ast.EndBlock.Statements|Where-Object {$_-is[Management.Automation.Language.FunctionDefinitionAst]})){
 . ([scriptblock]::Create($fn.Extent.Text))
}
$script:events=[Collections.Generic.List[string]]::new()
$RunDirectory=$Root;$repo=$Root;$artifacts=$Root;$runId='fixture'
$pkg=@{run_config=(Join-Path $Root 'run_config.json');summary=(Join-Path $Root 'summary.json')}
$plan=@{execution_order=@('parent');project='parallel_mirror_dual_stripe_mr_tof'}
$software=@('software fixture');$reason='retained completed fixture'
$parentDone=$true;$windowDone=$true;$levelStatus=@{parent=@{completed=$true}}
$fieldBinding=$null;$responseBasis=$null;$watch=[Diagnostics.Stopwatch]::StartNew();$timings=@{}
$status='failed';$stage='parent_refine';$failure=$null;$failureRecord=$null
$lease=@{inherited=$false;token='owned'};$capacity=@{fixture=$true};$parentGuard=$null
$guard=[pscustomobject]@{}
$guard|Add-Member ScriptMethod Dispose {
 $script:events.Add('guard')
 if($FailureMode-eq'guard'){throw 'SECONDARY_GUARD'}
}
$overlayGuards=@($guard)
function Exit-HostResourceStage {param($Lease,[switch]$PassThru)
 $script:events.Add('host_release')
 if($FailureMode-eq'lease'){throw 'SECONDARY_RELEASE'}
 if($PassThru){@{status=$(if($FailureMode-eq'retained'){'retained'}else{'released'});token=$Lease.token}}
}
function Write-RunJson {param($Path,$Value,$Depth)
 $script:events.Add('summary');if($FailureMode-eq'publication'){throw 'SECONDARY_PUBLICATION'}
}
function Apply-RunArtifactRetention {$script:events.Add('retention')}
function Write-RunManifest {
 $script:events.Add('manifest')
 @{status=$status}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $Root 'run_manifest.json') -Encoding utf8
}
function Invoke-RunToolRootContext {param($RepoRoot,$Operation)
 $script:events.Add($(if($Operation.ToString().Contains('seal-stopped-payload')){'seal'}else{'verify'}))
}
function Exit-ArtifactWorkflowCapacitySession {$script:events.Add('capacity_release')}
function Remove-RunPackageExecutionAlias {$script:events.Add('alias')}
$catchText=($outer[0].CatchClauses|ForEach-Object {$_.Extent.Text})-join"`n"
$body=if($PrimaryError-eq'yes'){"throw [IO.IOException]::new('ORIGINAL_NATIVE_FAILURE')"}else{"`$status='success'"}
if($NormalReleaseIndex-ne'none'){
 $releaseCalls=@($outer[0].Body.FindAll({param($node)
  $node-is[Management.Automation.Language.CommandAst]-and
  $node.GetCommandName()-in@('Exit-HostResourceStage','Exit-NativeProviderHostStage')
 },$true))
 if($releaseCalls.Count-ne3){throw 'Expected all three normal production release sites'}
 $release=$releaseCalls[[int]$NormalReleaseIndex].Parent
 $statements=@($release.Parent.Statements)
 $clear=$statements[[array]::IndexOf($statements,$release)+1]
 if($clear.Extent.Text-ne'$lease=$null'){throw 'Expected lease clear after actual release'}
 $body=$release.Extent.Text+';'+$clear.Extent.Text+';$script:events.Add("normal_release_completed");$status="success"'
}
$code="try {"+$body+"} "+$catchText+" finally "+$outer[0].Finally.Extent.Text
$caught=$null
try{. ([scriptblock]::Create($code))}catch{$caught=$_}
$data=@{};if($null-ne$caught){foreach($key in $caught.Exception.Data.Keys){$data[[string]$key]=[string]$caught.Exception.Data[$key]}}
@{error=$(if($null-ne$caught){$caught.Exception.Message});type=$(if($null-ne$caught){$caught.Exception.GetType().FullName});data=$data;
 events=@($script:events)}|ConvertTo-Json -Depth 12 -Compress
""", encoding="utf-8")
            result = subprocess.run(
                [powershell, "-NoProfile", "-File", str(script), str(runner), str(root), failure, sys.executable,
                 "yes" if primary_error else "no",
                 "none" if normal_release_index is None else str(normal_release_index)],
                cwd=repo, check=False, capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(result.stdout)

    def test_terminal_cleanup_preserves_primary_error_and_finishes_safe_cleanup(self) -> None:
        for failure in ("guard", "lease", "publication"):
            with self.subTest(failure=failure):
                result = self.closeout_fixture(failure)
                self.assertEqual(result["error"], "ORIGINAL_NATIVE_FAILURE")
                self.assertEqual(result["type"], "System.IO.IOException")
                self.assertIn("SECONDARY_", str(result["data"]))
                if failure == "lease":
                    self.assertNotIn("manifest", result["events"])
                    self.assertNotIn("capacity_release", result["events"])
                    self.assertNotIn("alias", result["events"])
                else:
                    self.assertIn("capacity_release", result["events"])
                    self.assertIn("alias", result["events"])

    def test_retained_host_owner_does_not_publish_or_release_capacity(self) -> None:
        result = self.closeout_fixture("retained")
        self.assertEqual(result["error"], "ORIGINAL_NATIVE_FAILURE")
        for operation in ("summary", "retention", "manifest", "seal", "capacity_release", "alias"):
            self.assertNotIn(operation, result["events"])

    def test_cleanup_failure_without_primary_error_still_fails(self) -> None:
        for failure in ("guard", "lease", "publication"):
            with self.subTest(failure=failure):
                result = self.closeout_fixture(failure, primary_error=False)
                self.assertIn("SECONDARY_", result["error"])
                self.assertNotIn("ORIGINAL_NATIVE_FAILURE", result["error"])

    def test_normal_stage_release_keeps_lease_until_confirmed(self) -> None:
        for index in range(3):
            for failure in ("", "retained", "lease"):
                with self.subTest(release_site=index, failure=failure):
                    result = self.closeout_fixture(failure, primary_error=False, normal_release_index=index)
                    if not failure:
                        self.assertIsNone(result["error"])
                        self.assertEqual(result["events"].count("host_release"), 1)
                        self.assertIn("normal_release_completed", result["events"])
                        self.assertIn("seal", result["events"])
                        continue
                    self.assertIn("unconfirmed" if failure == "retained" else "SECONDARY_RELEASE", result["error"])
                    self.assertEqual(result["events"].count("host_release"), 2)
                    for operation in ("normal_release_completed", "guard", "summary", "retention",
                                      "manifest", "seal", "capacity_release", "alias"):
                        self.assertNotIn(operation, result["events"])

    def test_published_provider_seal_failure_uses_existing_cli_without_native_reentry(self) -> None:
        """Compose the actual terminal boundary with public seal-only recovery."""
        import shutil
        import subprocess
        import sys
        from common.contracts.capacity_ledger import initialize_capacity_ledger, load_capacity_ledger

        powershell = shutil.which("pwsh")
        if powershell is None:
            self.skipTest("PowerShell 7 required")
        repo = Path(__file__).resolve().parents[4]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_root = root / "artifacts"
            artifact_root.mkdir()
            initialize_capacity_ledger(artifact_root, objects=[])
            script = root / "terminal.ps1"
            script.write_text(r"""
param($repo,$python,$artifacts)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $repo 'common/contracts/run_artifact_support.ps1')
$runner=Join-Path $repo 'projects/parallel_mirror_dual_stripe_mr_tof/simion/run_native_static_field_provider.ps1'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($runner,[ref]$tokens,[ref]$errors)
$outer=@($ast.EndBlock.Statements|Where-Object {$_-is[Management.Automation.Language.TryStatementAst]})
if($errors.Count-or$outer.Count-ne1){throw 'Invalid production terminal boundary'}
$project='parallel_mirror_dual_stripe_mr_tof'
$runId='20261029_020000__test__python__provider-seal-fixture'
$reason='Production ordinary-static C0 parent/local fields retained for downstream native trajectory consumption.'
$software=@('Python 3.11','SIMION 2020')
$pkg=New-RunPackage -Python $python -RepoRoot $repo -ArtifactRoot (Join-Path $artifacts ('projects/'+$project)) `
 -RunId $runId -Project $project -Mode native_static_field_provider -Software $software `
 -RetentionContractEnabled -RetentionClass solver_review -RetentionReason $reason `
 -CapacityLedgerLifecycleEnabled -CapacityLedgerArtifactRoot $artifacts -AdditionalDirectories @('simion')
$RunDirectory=$pkg.artifact_run_dir
# Synthetic completed payload: this exercises publication, never a vendor or physical claim.
[IO.File]::WriteAllText((Join-Path $RunDirectory 'simion/field.pa'),'completed software fixture')
$plan=@{execution_order=@('parent');project=$project}
$status='success';$stage='binding_publication';$failure=$null;$failureRecord=$null
$parentDone=$true;$windowDone=$true;$levelStatus=@{parent=@{completed=$true}}
$fieldBinding=$null;$responseBasis=$null;$watch=[Diagnostics.Stopwatch]::StartNew();$timings=@{}
$lease=$null;$capacity=@{fixture=$true};$parentGuard=$null;$overlayGuards=@()
$script:nativeCalls=0;$script:capacityReleases=0;$script:aliases=0
function Invoke-ResourceBudgetedProcess {$script:nativeCalls++;throw 'Native reentry is forbidden'}
function Exit-ArtifactWorkflowCapacitySession {$script:capacityReleases++}
$originalAlias=${function:Remove-RunPackageExecutionAlias}
function Remove-RunPackageExecutionAlias {param($Package);$script:aliases++;& $originalAlias -Package $Package}
$originalRootContext=${function:Invoke-RunToolRootContext}
function Invoke-RunToolRootContext {param($RepoRoot,$Operation)
 if($Operation.ToString().Contains('seal-stopped-payload')){throw 'TEST_ONLY seal unavailable after publication'}
 & $originalRootContext -RepoRoot $RepoRoot -Operation $Operation
}
$caught=$null
try{. ([scriptblock]::Create($outer[0].Finally.Extent.Text.Trim().TrimStart('{').TrimEnd('}')))}catch{$caught=$_}
if($null-eq$caught-or$caught.Exception.Message-ne'TEST_ONLY seal unavailable after publication'){
 throw ('Unexpected closeout error: '+[string]$caught)
}
'RESULT='+(@{native_calls=$script:nativeCalls;capacity_releases=$script:capacityReleases;aliases=$script:aliases;
 run_directory=$RunDirectory;error=$caught.Exception.Message}|ConvertTo-Json -Compress)
""", encoding="utf-8")
            result = subprocess.run(
                [powershell, "-NoProfile", "-File", str(script), str(repo), sys.executable, str(artifact_root)],
                cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            outcome = json.loads(next(line[7:] for line in result.stdout.splitlines() if line.startswith("RESULT=")))
            self.assertEqual((outcome["native_calls"], outcome["capacity_releases"], outcome["aliases"]), (0, 1, 1))
            run = Path(outcome["run_directory"])
            self.assertEqual(load_capacity_ledger(artifact_root)["objects"][0]["status"], "writing")
            config = json.loads((run / "run_config.json").read_text(encoding="utf-8-sig"))
            before = {path.relative_to(run): path.read_bytes() for path in run.rglob("*") if path.is_file()}
            command = [sys.executable, "-B", "-m", "common.contracts.run_capacity_lifecycle",
                       "--action", "seal-stopped-payload", "--artifact-root", str(artifact_root),
                       "--run-config", str(run / "run_config.json"), "--owner", config["project"],
                       "--confirm-writing-stopped", "--retention-reason", config["artifact_retention"]["reason"]]
            ledger = None
            for _ in range(2):
                sealed = subprocess.run(command, cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
                self.assertEqual(sealed.returncode, 0, sealed.stdout + sealed.stderr)
                receipt = json.loads(sealed.stdout)
                self.assertEqual((receipt["action"], receipt["status"], receipt["run_status"]), ("seal_stopped_payload", "ready", "success"))
                self.assertTrue(receipt["ledger_entry"]["pin"])
                current = load_capacity_ledger(artifact_root)
                if ledger is not None:
                    self.assertEqual(current, ledger)
                ledger = current
                self.assertEqual(before, {path.relative_to(run): path.read_bytes() for path in run.rglob("*") if path.is_file()})
            verified = subprocess.run(
                [sys.executable, "-B", "-m", "common.contracts.verify_run_manifest", str(run / "run_manifest.json"), "--require-status", "success"],
                cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
            )
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)


if __name__ == "__main__":
    unittest.main()
