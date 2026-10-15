from __future__ import annotations

import copy
import contextlib
import io
import json
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import (
    ideal_sheet_projection, load_binding, validate_voltages,
    _resolve_voltage_responses, validate_response_candidate, compile_sampling_request,
    compile_composition_plan, _load_materialized_response, _load_export,
    main as binding_main,
    _load_native_level, native_numerics_match, resolve_native_refine_numerics,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial import (
    _scalar_field_lua_fields, _scalar_refinement_windows_lua,
)


REPO_ROOT = Path(__file__).resolve().parents[4]


class RecordLookupScopeTest(unittest.TestCase):
    def test_nested_load_indexes_manifest_once_and_rechecks_asset_size(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis import static_field_binding as module
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset, manifest = root/'asset.json', root/'run_manifest.json'
            asset.write_text('{}')
            record = dict(path=str(asset), bytes=2, sha256='sealed')
            manifest.write_text(json.dumps(dict(status='success', outputs=[record])))

            @module._within_record_lookup
            def inner():
                return module._record(manifest, asset)

            @module._within_record_lookup
            def outer():
                first = inner()
                self.assertEqual(inner(), first)
                first['sha256'] = 'caller modification'
                self.assertEqual(inner()['sha256'], 'sealed')
                asset.write_text('changed')
                with self.assertRaisesRegex(ValueError, 'changed size'):
                    inner()

            with patch.object(module, '_read', wraps=module._read) as read:
                outer()
            self.assertEqual(read.call_count, 1)
            self.assertIsNone(module._record_indexes.get())

    def test_next_load_reads_changed_manifest_and_failed_load_releases_scope(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis import static_field_binding as module
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset, manifest = root/'asset.json', root/'run_manifest.json'
            asset.write_text('{}')
            record = dict(path=str(asset), bytes=2, sha256='first')
            def seal(status='success'):
                manifest.write_text(json.dumps(dict(status=status, outputs=[record])))
            read = module._within_record_lookup(lambda: module._record(manifest, asset))
            seal()
            self.assertEqual(read()['sha256'], 'first')
            record['sha256'] = 'second'
            seal()
            self.assertEqual(read()['sha256'], 'second')
            seal('failed')
            with self.assertRaisesRegex(ValueError, 'successful'):
                read()
            self.assertIsNone(module._record_indexes.get())
            seal()
            self.assertEqual(read()['sha256'], 'second')

    def test_conflicting_duplicate_seals_are_rejected_after_indexing(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis import static_field_binding as module
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset, manifest = root/'asset.json', root/'run_manifest.json'
            asset.write_text('{}')
            record = dict(path=str(asset), bytes=2, sha256='first')
            manifest.write_text(json.dumps(dict(status='success', outputs=[record],
                inputs=dict(alias={**record, 'sha256': 'conflicting'}))))
            read = module._within_record_lookup(lambda: module._record(manifest, asset))
            with self.assertRaisesRegex(ValueError, 'unique sealed record'):
                read()


class NativeAxisMaterializationTest(unittest.TestCase):
    """Real tiny ordinary PA blocks; no SIMION or PA-sized fixture allocations."""

    def test_center_storage_view_roundtrip_and_composition_preserve_collision(self):
        import numpy as np
        from dataclasses import replace
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.standalone_pa_composition import read_pa_header, HEADER
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider, base = self.setup_bank(root, nested=True)
            contract = copy.deepcopy(self.contract)
            contract['simion']['numerical_profiles']['native_static_field']['consumer_view'] = {
                'kind': 'x_symmetry_plane', 'stored_x_nodes': 5}
            self.contract_path = root/'view_contract.json'
            self.contract_path.write_text(json.dumps(contract))

            def view(source_path, name):
                raw = json.loads(Path(source_path).read_text())
                request = dict(schema_version=1, role=provider.ROLE,
                    source_binding_path=str(self.base_path), source_field_manifest=raw['parent']['manifest'],
                    consumer_view_source_path=str(source_path), numerical_contract_path=str(self.contract_path))
                plan = provider.compile_request(request)
                self.assertEqual(plan['operation'], 'crop_view')
                run = root/name
                (run/'inputs').mkdir(parents=True); (run/'results').mkdir()
                for key, path in plan['inputs'].items():
                    (run/'inputs'/f'{key}.json').write_bytes(Path(path).read_bytes())
                provider.prepare_run(plan, run)
                # Tiny synthetic storage-crop fixture, not a SIMION qualification.
                for label, spec in plan['levels'].items():
                    source = Path(spec['consumer_view_source']['pa_path'])
                    header = read_pa_header(source)
                    values = np.frombuffer(source.read_bytes()[HEADER.size:], dtype='<f8').reshape(header.nz, header.ny, header.nx)
                    output = run/'simion'/label/('c0_static.pa' if label == 'parent' else 'c0_local.pa')
                    output.write_bytes(replace(header, nx=5).pack()+values[:, :, :5].tobytes())
                    Path(str(output)+'-surf').write_bytes(Path(spec['consumer_view_source']['surface_path']).read_bytes())
                    Path(spec['consumer_view_receipt_path']).write_text(json.dumps(dict(status='PASS',
                        full_dimensions=[header.nx, header.ny, header.nz],
                        consumer_dimensions=[5, header.ny, header.nz], refine_after_crop=False)))
                descriptor = provider.binding_spec(plan, run)
                self.assertEqual(descriptor['instances'], raw['instances'])
                output = run/'results'/('response_basis.json' if plan['response_basis'] else 'field_binding.json')
                output.write_text(json.dumps(descriptor))
                records = [dict(path=str(p.resolve()), bytes=p.stat().st_size,
                    sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in run.rglob('*') if p.is_file()]
                (run/'run_manifest.json').write_text(json.dumps(dict(status='success', outputs=records)))
                return output

            base_view = view(self.base_path, 'base_view')
            loaded = load_binding(base_view)
            self.assertEqual(loaded['grid']['dimensions'][0], 5)
            self.bases = {axis: str(view(path, axis+'_view')) for axis, path in self.bases.items()}
            target = dict(p1=0., p2=0., s1=0., s2=0.)
            target['s1'] += .1
            composed, _ = self.materialize(root, provider, base_view, target, 'composed_view')
            result = load_binding(composed)
            self.assertEqual(result['consumer_view']['kind'], 'x_symmetry_plane')
            self.assertEqual(result['instances'][0]['pa_path'], base['instances'][0]['pa_path'])

    def seal(self, descriptor, extra=()):
        for level in (descriptor["parent"], *descriptor["refinement_windows"]):
            owner = Path(level["manifest"])
            paths = [p for p in owner.parent.iterdir() if p.is_file() and p != owner]
            paths.extend(Path(p) for p in extra)
            records = {str(p.resolve()): dict(path=str(p.resolve()), bytes=p.stat().st_size,
                       sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths}
            owner.write_text(json.dumps(dict(status="success", outputs=list(records.values()))))

    def nest(self, descriptor):
        """Keep source priority child/child/E while boundary ancestry is E first."""
        parent = descriptor['refinement_windows'][0]
        children = []
        for index in range(2):
            child = copy.deepcopy(parent)
            directory = Path(parent['pa_path']).parent.parent/('branch_'+str(index)); directory.mkdir()
            for key in ('pa_path','surface_path','voltage_authority_path','geometry_authority_path','numerical_plan_path'):
                original = Path(parent[key]); target = directory/original.name
                target.write_bytes(original.read_bytes()); child[key] = str(target)
            child.update(manifest=str(directory/'run_manifest.json'), name='branch_'+str(index),
                         parent_manifest=parent['manifest'],
                         active_box_mm=[[-4,4],[-3,3],[0,3] if not index else [-3,0]])
            path=Path(child['numerical_plan_path']); plan=json.loads(path.read_text())
            plan.update(parent_manifest=parent['manifest'],parent_pa=parent['pa_path']);path.write_text(json.dumps(plan))
            children.append(child)
        descriptor['refinement_windows']=[*children,parent]

    def setup_bank(self, root, *, nested=False):
        import numpy as np
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.standalone_pa_composition import PaHeader
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis import native_static_field_provider as provider
        base_dir = root/"base"; base_dir.mkdir()
        base = NativeStaticBindingTest().fixture(base_dir)
        base["instances"][0]["origin_mm"] = base["parent"]["grid"]["origin_mm"]
        self.contract = {"simion": {"numerical_profiles": {
            "grid_generation": {"spacing_quantum_mm": .01},
            "native_static_field": {"refine": {"convergence_v": 1e-5},
                "target_layout": {"parent": {"pitch_mm": [.5,1,1]}, "windows": [{"pitch_mm": [.5,1,1]}]}}}}}
        self.contract_path = root/"numerical_contract.json"
        if nested:
            self.contract['simion']['numerical_profiles']['native_static_field']['target_layout']['windows'] *= 3
        self.contract_path.write_text(json.dumps(self.contract))
        header = PaHeader(-2, 1, 100000., 11, 11, 11, 1, .5, 1, 1)
        for level in (base["parent"], *base["refinement_windows"]):
            authority = json.loads(Path(level["voltage_authority_path"]).read_text())
            authority["component_voltages_v"] = [{"component_namespace": "accelerator", "component_electrode_id": 1, "voltage_v": 4000.}]
            Path(level["voltage_authority_path"]).write_text(json.dumps(authority))
            path = Path(level["numerical_plan_path"]); plan = json.loads(path.read_text())
            plan.update(refine_stopping="contract_convergence", convergence_v=1e-5,
                        numerical_contract_path=str(self.contract_path), resource_limits={"automatic_retry_count": 0})
            path.write_text(json.dumps(plan))
            Path(level["pa_path"]).write_bytes(header.pack()+np.full(header.node_count, 5., dtype='<f8').tobytes())
        if nested:
            self.nest(base)
        self.seal(base, [self.contract_path])
        base_path = root/"base_binding.json"; base_path.write_text(json.dumps(base))
        self.base_path = base_path
        bases = {}
        for axis, potential in (("s1", 10000.), ("s2", 5000.)):
            directory = root/axis; directory.mkdir()
            descriptor = NativeStaticBindingTest().fixture(directory)
            descriptor["instances"][0]["origin_mm"] = descriptor["parent"]["grid"]["origin_mm"]
            for level in (descriptor["parent"], *descriptor["refinement_windows"]):
                Path(level["voltage_authority_path"]).write_text(json.dumps(provider._pure_axis_authority(authority, axis)))
                path = Path(level["numerical_plan_path"]); value = json.loads(path.read_text())
                value.update(refine_stopping="contract_convergence", convergence_v=1e-5, numerical_contract_path=str(self.contract_path))
                path.write_text(json.dumps(value))
                Path(level["pa_path"]).write_bytes(header.pack()+np.full(header.node_count, potential, dtype='<f8').tobytes())
            descriptor["instances"][1:] = copy.deepcopy(base["instances"][1:])
            if nested:
                self.nest(descriptor)
            frozen_source = directory/"source_binding.json"; frozen_source.write_bytes(base_path.read_bytes())
            source_authority = directory/"source_authority.json"; source_authority.write_text(json.dumps(authority))
            descriptor.update(role="mrtof_native_static_field_response_basis", fly_authorized=False,
                response_basis={"axis": axis, "normalization_v": 10000., "physical_electrode_ids": list(provider.PS_GROUPS[axis])},
                source_binding_path=str(frozen_source), source_authority_path=str(source_authority))
            path = directory/"response_basis.json"; path.write_text(json.dumps(descriptor))
            self.seal(descriptor, [self.contract_path, frozen_source, source_authority, path])
            bases[axis] = str(path)
        self.bases = bases
        return provider, base

    def materialize(self, root, provider, source_path, target, name, *, mirror_target=None):
        source = load_binding(source_path)
        request = dict(schema_version=1, role=provider.ROLE,
            source_binding_path=str(source_path), source_field_manifest=source["manifest"],
            numerical_contract_path=str(self.contract_path), response_basis_paths=self.bases,
            candidate_voltages_v=target)
        if mirror_target is None:
            plan = provider.compile_request(request)
        else:
            # Isolate the composition boundary, not the already tested mirror
            # proposal compiler. The loaded result independently rechecks U.
            from projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider import candidate_authority
            authority = candidate_authority(source["authority"], target, mirror_voltages_v=mirror_target)
            with patch.object(provider, "derive_candidate_authority", return_value=(authority, {})):
                plan = provider.compile_request(request)
        run = root/name; (run/"inputs").mkdir(parents=True); (run/"results").mkdir()
        (run/"inputs/numerical_contract.json").write_bytes(self.contract_path.read_bytes())
        provider.prepare_run(plan, run)
        provider.compose_run(plan, run)
        descriptor = provider.binding_spec(plan, run)
        path = run/"results/field_binding.json"; path.write_text(json.dumps(descriptor))
        records = [dict(path=str(p.resolve()), bytes=p.stat().st_size,
                   sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in run.rglob('*') if p.is_file()]
        (run/"run_manifest.json").write_text(json.dumps(dict(status="success", outputs=records)))
        return path, plan

    def test_pure_response_mirror_reuse_roundtrip_and_real_composition(self):
        """Publish tiny new mirrors with old pure parent/E; no vendor solve."""
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import load_native_response_basis
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider, base = self.setup_bank(root, nested=True)
            source_path = Path(self.bases["s1"])
            old = json.loads(source_path.read_text())
            old["response_basis"].update(
                excitation_semantics="pure axis response; all other analyzer/component potentials zero",
                combination_semantics="base PA plus (target axis minus base axis)/normalization_v times this PA")
            for level in [old["parent"], *old["refinement_windows"]]:
                path = Path(level["numerical_plan_path"])
                value = json.loads(path.read_text())
                value.update(resource_budget={"estimated_memory_bytes": 123}, resource_limits={"automatic_retry_count": 0})
                path.write_text(json.dumps(value))
            source_path.write_text(json.dumps(old))
            self.seal(old, [self.contract_path, source_path, old["source_binding_path"], old["source_authority_path"]])
            request = dict(schema_version=1, role=provider.ROLE, response_axis="s1",
                source_binding_path=str(source_path), source_field_manifest=old["parent"]["manifest"],
                numerical_contract_path=str(self.contract_path), reuse_source_levels=["parent", "window_2"])
            with patch.object(provider, "build_static_c0_gem", return_value=("fixture", {})):
                plan = provider.compile_request(request)
            run = root/"extended"
            (run/"inputs").mkdir(parents=True); (run/"results").mkdir()
            for key, path in plan["inputs"].items():
                (run/"inputs"/(key+Path(path).suffix)).write_bytes(Path(path).read_bytes())
            provider.prepare_run(plan, run)
            for index in (0, 1):
                target = run/"simion"/f"window_{index}"/"c0_local.pa"
                target.write_bytes(Path(old["refinement_windows"][index]["pa_path"]).read_bytes())
                Path(str(target)+"-surf").write_bytes(Path(old["refinement_windows"][index]["surface_path"]).read_bytes())
            descriptor = provider.binding_spec(plan, run)
            path = run/"results/response_basis.json"
            path.write_text(json.dumps(descriptor))
            records = [dict(path=str(p.resolve()), bytes=p.stat().st_size,
                sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in run.rglob('*') if p.is_file()]
            (run/"run_manifest.json").write_text(json.dumps(dict(status="success", outputs=records)))
            loaded = load_native_response_basis(path, load_binding(self.base_path))
            self.assertEqual(loaded["sources"]["scalar_pa"], old["parent"]["pa_path"])
            self.assertEqual(loaded["refinement_windows"][2]["sources"]["scalar_pa"], old["refinement_windows"][2]["pa_path"])
            self.bases = {"s1": str(path)}
            composed, _ = self.materialize(root, provider, self.base_path,
                dict(p1=0., p2=0., s1=.1, s2=0.), "composed_reused_response")
            self.assertEqual(load_binding(composed)["authority"]["analyzer_electrode_voltages_v"][10:12], [.1, .1])

    def add_pure_basis(self, root, provider, base, axis, potential, *, reference=None, electrode_flags=False):
        """Add a tiny sealed pure field with identical geometry and PA flags."""
        import numpy as np
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.standalone_pa_composition import PaHeader
        directory = root/axis; directory.mkdir()
        descriptor = NativeStaticBindingTest().fixture(directory)
        descriptor["instances"][0]["origin_mm"] = descriptor["parent"]["grid"]["origin_mm"]
        authority = json.loads(Path(base["parent"]["voltage_authority_path"]).read_text())
        basis = (provider._te1_basis_metadata(reference) if axis == "te1" else
                 dict(axis=axis, normalization_v=10000., physical_electrode_ids=list(provider.PS_GROUPS[axis])))
        header = PaHeader(-2, 1, 100000., 11, 11, 11, 1, .5, 1, 1)
        for level in (descriptor["parent"], *descriptor["refinement_windows"]):
            Path(level["voltage_authority_path"]).write_text(json.dumps(provider._response_authority(authority, basis)))
            path = Path(level["numerical_plan_path"]); plan = json.loads(path.read_text())
            plan.update(refine_stopping="contract_convergence", convergence_v=1e-5,
                        numerical_contract_path=str(self.contract_path))
            path.write_text(json.dumps(plan))
            values = np.full(header.node_count, potential, dtype='<f8')
            if electrode_flags:
                values[0] += 2*header.max_voltage
            Path(level["pa_path"]).write_bytes(header.pack()+values.tobytes())
        descriptor["instances"][1:] = copy.deepcopy(base["instances"][1:])
        frozen_source = directory/"source_binding.json"; frozen_source.write_bytes(self.base_path.read_bytes())
        frozen_authority = directory/"source_authority.json"; frozen_authority.write_text(json.dumps(authority))
        descriptor.update(role="mrtof_native_static_field_response_basis", fly_authorized=False,
            response_basis=basis, source_binding_path=str(frozen_source), source_authority_path=str(frozen_authority))
        extras = [self.contract_path, frozen_source, frozen_authority]
        if reference is not None:
            frozen_reference = directory/"te1_reference.json"; frozen_reference.write_bytes(reference.read_bytes())
            descriptor["direction_reference_path"] = str(frozen_reference)
            extras.append(frozen_reference)
        path = directory/"response_basis.json"; path.write_text(json.dumps(descriptor))
        self.seal(descriptor, [*extras, path])
        self.bases[axis] = str(path)
        return descriptor

    def test_five_responses_compose_actual_nonzero_mirror_anchor_and_roundtrip_flags(self):
        import numpy as np
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.standalone_pa_composition import HEADER, read_pa_header
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_native_static_field_provider import NativeStaticProviderTest
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); provider, base = self.setup_bank(root)
            fixture = NativeStaticProviderTest(); fixture.root = root
            reference = fixture.te1_reference()
            data = json.loads(reference.read_text()); direction = data["voltage_delta_v"]
            c0 = -22.894154431673797
            mirror = [0., *[v+c0*d for v,d in zip(data["base_mirror_voltages_v"][1:], direction, strict=True)]]
            authority = json.loads(Path(base["parent"]["voltage_authority_path"]).read_text())
            authority["analyzer_electrode_voltages_v"][:10] = mirror*2
            # Define fixtures before use; all arrays carry the same true electrode bit.
            for descriptor in [base, *[json.loads(Path(p).read_text()) for p in self.bases.values()]]:
                for level in (descriptor["parent"], *descriptor["refinement_windows"]):
                    if descriptor is base:
                        Path(level["voltage_authority_path"]).write_text(json.dumps(authority))
                    pa = Path(level["pa_path"]); payload = pa.read_bytes()
                    values = np.frombuffer(payload[HEADER.size:], dtype='<f8').copy(); values[0] += 200000.
                    pa.write_bytes(payload[:HEADER.size]+values.tobytes())
                if descriptor is not base:
                    Path(descriptor["source_authority_path"]).write_text(json.dumps(authority))
                    extras = [self.contract_path, descriptor["source_binding_path"], descriptor["source_authority_path"], self.bases[descriptor["response_basis"]["axis"]]]
                else:
                    extras = [self.contract_path]
                self.seal(descriptor, extras)
            self.add_pure_basis(root, provider, base, "p1", 1000., electrode_flags=True)
            self.add_pure_basis(root, provider, base, "p2", -2000., electrode_flags=True)
            self.add_pure_basis(root, provider, base, "te1", 2000., reference=reference, electrode_flags=True)
            target = dict(p1=1., p2=-2., s1=-3., s2=4.)
            for name, delta in (("fine", -.988552922784), ("reverse", .988552922784), ("zero", 0.)):
                updated = [0., *[v+delta*d for v,d in zip(mirror[1:], direction, strict=True)]]
                path, plan = self.materialize(root, provider, self.base_path, target, name, mirror_target=updated)
                resolved = load_binding(path)
                coefficient = delta*max(abs(d) for d in direction)/10000.
                self.assertAlmostEqual(plan["coefficients"]["te1"], coefficient, places=15)
                self.assertEqual(len(plan["coefficients"]), 5)
                self.assertEqual(resolved["authority"]["analyzer_electrode_voltages_v"][:10], updated*2)
                self.assertEqual(resolved["authority"]["component_voltages_v"], authority["component_voltages_v"])
                header = read_pa_header(Path(resolved["sources"]["scalar_pa"]))
                values = np.frombuffer(Path(resolved["sources"]["scalar_pa"]).read_bytes()[HEADER.size:], dtype='<f8').copy()
                self.assertTrue(values[0] > header.max_voltage)
                self.assertTrue(np.all(values[1:] < header.max_voltage))
                values[0] -= 2*header.max_voltage
                np.testing.assert_allclose(values, 4.5+coefficient*2000., atol=1e-9, rtol=0)
                self.assertFalse(resolved["refine_performed"])

    def test_te1_basis_loader_rejects_direction_provenance_or_pure_voltage_contamination(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import load_native_response_basis
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_native_static_field_provider import NativeStaticProviderTest
        for mutation in ("direction", "normalization", "e_cover", "background", "geometry", "stopping"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); provider, base = self.setup_bank(root)
                fixture = NativeStaticProviderTest(); fixture.root = root
                descriptor = self.add_pure_basis(root, provider, base, "te1", 2000., reference=fixture.te1_reference())
                path = Path(self.bases["te1"])
                if mutation == "direction":
                    descriptor["response_basis"]["direction_v_per_coordinate"][0] *= 2
                elif mutation == "normalization":
                    descriptor["response_basis"]["normalization_v"] = 0
                elif mutation in ("e_cover", "background"):
                    for level in (descriptor["parent"], *descriptor["refinement_windows"]):
                        authority_path = Path(level["voltage_authority_path"])
                        value = json.loads(authority_path.read_text())
                        if mutation == "e_cover": value["analyzer_electrode_voltages_v"][4] = 0
                        else: value["component_voltages_v"][0]["voltage_v"] = 1
                        authority_path.write_text(json.dumps(value))
                else:
                    for level in (descriptor["parent"], *descriptor["refinement_windows"]):
                        changed = Path(level["geometry_authority_path"] if mutation == "geometry" else level["numerical_plan_path"])
                        value = json.loads(changed.read_text())
                        if mutation == "geometry": value["changed"] = True
                        else: value["convergence_v"] = 1e-6
                        changed.write_text(json.dumps(value))
                path.write_text(json.dumps(descriptor))
                self.seal(descriptor, [self.contract_path, path, descriptor["source_binding_path"],
                                      descriptor["source_authority_path"], descriptor["direction_reference_path"]])
                with self.assertRaises(ValueError):
                    load_native_response_basis(path, load_binding(self.base_path))

    def test_te1_composition_rejects_off_direction_target_and_recomputes_loaded_coefficient(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_native_static_field_provider import NativeStaticProviderTest
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); provider, base = self.setup_bank(root)
            fixture = NativeStaticProviderTest(); fixture.root = root
            self.add_pure_basis(root, provider, base, "te1", 2000., reference=fixture.te1_reference())
            target = dict(s1=0.,s2=0.,p1=0.,p2=0.)
            mirror = provider._te1_excitation(json.loads(Path(self.bases["te1"]).read_text())["response_basis"])
            mirror = [v*.0001 for v in mirror]
            bad = mirror.copy(); bad[1] += .01
            with self.assertRaisesRegex(ValueError, "incompatible"):
                self.materialize(root, provider, self.base_path, target, "bad", mirror_target=bad)
            path, plan = self.materialize(root, provider, self.base_path, target, "valid", mirror_target=mirror)
            resolved = load_binding(path)
            self.assertAlmostEqual(plan["coefficients"]["te1"], .0001)
            descriptor = json.loads(path.read_text())
            del descriptor["materialization"]["target_mirror_voltages_v"]
            path.write_text(json.dumps(descriptor))
            # Re-seal all small evidence: a valid byte identity cannot replace
            # the mandatory physical TE1 target authority.
            plan_path = Path(plan["materialization"]["plan_path"])
            document = json.loads(plan_path.read_text())
            document["materialization"] = descriptor["materialization"]
            plan_path.write_text(json.dumps(document))
            run = path.parent.parent
            records = [dict(path=str(p.resolve()),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                       for p in run.rglob('*') if p.is_file() and p.name != "run_manifest.json"]
            (run/"run_manifest.json").write_text(json.dumps(dict(status="success",outputs=records)))
            self.assertEqual(resolved["authority"]["analyzer_electrode_voltages_v"][:10], mirror*2)
            with self.assertRaisesRegex(ValueError, "TE1 target mirror authority"):
                load_binding(path)

    def test_two_candidates_use_fixed_bank_offset_and_native_roundtrip(self):
        import numpy as np
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.standalone_pa_composition import HEADER
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); provider, _ = self.setup_bank(root)
            first, plan = self.materialize(root, provider, self.base_path, dict(s1=1.,s2=-2.,p1=0.,p2=0.), "first")
            resolved = load_binding(first)
            self.assertEqual(resolved["mode"], "native_static_pa")
            self.assertFalse(resolved["refine_performed"])
            self.assertEqual(plan["operation"], "compose")
            self.assertEqual(plan["coefficients"], dict(s1=.0001,s2=-.0002))
            self.assertFalse(list(first.parent.parent.rglob('*.gem')))
            with Path(resolved["sources"]["scalar_pa"]).open('rb') as stream:
                stream.seek(HEADER.size); self.assertTrue(np.all(np.fromfile(stream,dtype='<f8') == 5.))
            second, next_plan = self.materialize(root, provider, first, dict(s1=2.,s2=-2.,p1=0.,p2=0.), "second")
            self.assertEqual(next_plan["combination_base_binding"], plan["combination_base_binding"])
            self.assertEqual(next_plan["coefficients"]["s1"], .0002)
            self.assertTrue(all(x["composition"]["base_pa"].startswith(str(root/"base")) for x in next_plan["levels"].values()))
            self.assertNotIn(str(first.parent.parent), next_plan["protected_paths"])
            self.assertEqual(load_binding(second)["authority"]["analyzer_electrode_voltages_v"][10], 2.)

    def mirror_offset(self, root):
        """Clone a tiny sealed ordinary solve, not the immutable response inputs."""
        import numpy as np
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.standalone_pa_composition import HEADER
        descriptor = copy.deepcopy(json.loads(self.base_path.read_text()))
        levels = [descriptor['parent'], *descriptor['refinement_windows']]
        paths = {}
        for index, level in enumerate(levels):
            directory = root / f'offset_level_{index}'
            directory.mkdir()
            paths[level['manifest']] = str(directory / 'run_manifest.json')
            for key in ('pa_path', 'surface_path', 'voltage_authority_path',
                        'geometry_authority_path', 'numerical_plan_path'):
                old = Path(level[key]); new = directory / old.name
                new.write_bytes(old.read_bytes()); paths[str(old)] = str(new); level[key] = str(new)
            level['manifest'] = str(directory / 'run_manifest.json')
        for level in levels:
            authority = json.loads(Path(level['voltage_authority_path']).read_text())
            authority['analyzer_electrode_voltages_v'][1] = 10.
            authority['analyzer_electrode_voltages_v'][6] = 10.
            Path(level['voltage_authority_path']).write_text(json.dumps(authority))
            path = Path(level['numerical_plan_path']); plan = json.loads(path.read_text())
            for key in ('parent_manifest', 'parent_pa'):
                if key in plan:
                    plan[key] = paths[plan[key]]
            path.write_text(json.dumps(plan))
            if 'parent_manifest' in level:
                level['parent_manifest'] = paths[level['parent_manifest']]
            pa = Path(level['pa_path']); payload = pa.read_bytes()
            pa.write_bytes(payload[:HEADER.size] + np.full((len(payload)-HEADER.size)//8, 9., dtype='<f8').tobytes())
        descriptor['instances'][0].update(manifest=levels[0]['manifest'], pa_path=levels[0]['pa_path'])
        result = root / 'offset_binding.json'; result.write_text(json.dumps(descriptor))
        self.seal(descriptor, [self.contract_path, result])
        return result, descriptor

    def test_new_mirror_offset_reuses_old_pure_axes_and_never_accumulates_candidates(self):
        import numpy as np
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.standalone_pa_composition import HEADER
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); provider, _ = self.setup_bank(root)
            offset, _ = self.mirror_offset(root)
            source_before = {Path(v): Path(v).read_bytes() for v in self.bases.values()}
            first, plan = self.materialize(root, provider, offset, dict(s1=1., s2=0., p1=0., p2=0.), 'new_first')
            second, later = self.materialize(root, provider, first, dict(s1=2., s2=0., p1=0., p2=0.), 'new_second')
            self.assertEqual(plan['combination_base_binding'], str(offset))
            self.assertEqual(later['combination_base_binding'], str(offset))
            self.assertEqual(later['coefficients']['s1'], .0002)
            self.assertEqual(load_binding(second)['authority']['analyzer_electrode_voltages_v'][1], 10.)
            for path, expected in ((first, 10.), (second, 11.)):
                resolved = load_binding(path)
                with Path(resolved['sources']['scalar_pa']).open('rb') as stream:
                    stream.seek(HEADER.size)
                    np.testing.assert_array_equal(np.fromfile(stream, dtype='<f8'), expected)
            self.assertEqual({p: p.read_bytes() for p in source_before}, source_before)

    def test_new_offset_fixed_components_operator_or_failed_owner_are_rejected(self):
        for mutation in ('components', 'geometry', 'failed'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); provider, _ = self.setup_bank(root)
                offset, descriptor = self.mirror_offset(root)
                if mutation == 'failed':
                    owner = Path(descriptor['parent']['manifest']); data = json.loads(owner.read_text())
                    data['status'] = 'failed'; owner.write_text(json.dumps(data))
                else:
                    for level in (descriptor['parent'], *descriptor['refinement_windows']):
                        path = Path(level['voltage_authority_path'] if mutation == 'components' else level['geometry_authority_path'])
                        data = json.loads(path.read_text())
                        if mutation == 'components':
                            data['component_voltages_v'][0]['voltage_v'] += 1.
                        else:
                            data['changed'] = True
                        path.write_text(json.dumps(data))
                    self.seal(descriptor, [self.contract_path, offset])
                with self.assertRaises((ValueError, AssertionError)):
                    self.materialize(root, provider, offset, dict(s1=1., s2=0., p1=0., p2=0.), 'rejected')

    def test_basis_wrong_axis_background_operator_and_failed_sources_reject(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import load_native_response_basis
        for mutation in ("normalization", "fly", "background", "geometry", "grid", "numerics", "parent", "fixed_mirror", "failed"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root=Path(directory); provider, _=self.setup_bank(root)
                path=Path(self.bases['s1']); value=json.loads(path.read_text())
                if mutation == 'normalization': value['response_basis']['normalization_v']=1
                elif mutation == 'fly': value['fly_authorized']=True
                elif mutation == 'background':
                    for level in (value['parent'], *value['refinement_windows']):
                        a=Path(level['voltage_authority_path']); data=json.loads(a.read_text()); data['component_voltages_v'][0]['voltage_v']=1; a.write_text(json.dumps(data))
                elif mutation == 'geometry':
                    for level in (value['parent'], *value['refinement_windows']):
                        a=Path(level['geometry_authority_path']); data=json.loads(a.read_text()); data['changed']=True; a.write_text(json.dumps(data))
                elif mutation == 'grid':
                    value['parent']['grid']['pitch_mm']=[1,1,1]
                elif mutation == 'numerics':
                    a=Path(value['parent']['numerical_plan_path']); data=json.loads(a.read_text()); data['convergence_v']=1e-7; a.write_text(json.dumps(data))
                elif mutation == 'parent':
                    level=value['refinement_windows'][0]; a=Path(level['numerical_plan_path']); data=json.loads(a.read_text()); data.update(parent_manifest=level['manifest'],parent_pa=level['pa_path']); a.write_text(json.dumps(data));level['parent_manifest']=level['manifest']
                elif mutation == 'fixed_mirror':
                    a=Path(value['source_authority_path']); data=json.loads(a.read_text()); data['analyzer_electrode_voltages_v'][0]=1; a.write_text(json.dumps(data))
                path.write_text(json.dumps(value)); self.seal(value,[self.contract_path,path,Path(value['source_authority_path']),Path(value['source_binding_path'])])
                if mutation == 'failed':
                    owner=Path(value['parent']['manifest']); data=json.loads(owner.read_text()); data['status']='failed'; owner.write_text(json.dumps(data))
                with self.assertRaises((ValueError, AssertionError)):
                    load_native_response_basis(path, load_binding(self.base_path))

    def test_three_windows_compose_in_parent_order_but_route_in_source_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);provider,_=self.setup_bank(root,nested=True)
            path,plan=self.materialize(root,provider,self.base_path,dict(s1=1.,s2=0.,p1=0.,p2=0.),'nested')
            self.assertEqual(plan['execution_order'],['parent','window_2','window_0','window_1'])
            actual=load_binding(path)
            self.assertEqual([w['name'] for w in actual['refinement_windows']],['branch_0','branch_1','local'])
            for child in actual['refinement_windows'][:2]:
                numerical=json.loads(Path(child['numerical_plan_path']).read_text())
                self.assertEqual(numerical['parent_pa'],actual['refinement_windows'][2]['sources']['scalar_pa'])
                self.assertEqual(numerical['parent_manifest'],actual['manifest'])

    def test_run_local_materialized_descriptor_copy_preserves_sealed_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); provider, _ = self.setup_bank(root)
            path, _ = self.materialize(root, provider, self.base_path,
                                      dict(s1=1., s2=0., p1=0., p2=0.), "target")
            copied = root / "trial/simion/static_field_binding.json"
            copied.parent.mkdir(parents=True)
            copied.write_bytes(path.read_bytes())
            self.assertEqual(load_binding(copied), load_binding(path))
            # Same-size, semantically identical JSON must still fail byte identity.
            copied.write_bytes(copied.read_bytes().replace(b" ", b"\t", 1))
            with self.assertRaisesRegex(AssertionError, "materialized_binding_copy SHA-256"):
                load_binding(copied)

    def test_run_local_descriptor_copy_cannot_replace_missing_or_changed_owner_seal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); provider, _ = self.setup_bank(root)
            path, _ = self.materialize(root, provider, self.base_path,
                                      dict(s1=1., s2=0., p1=0., p2=0.), "target")
            copied = root / "trial/simion/static_field_binding.json"
            copied.parent.mkdir(parents=True)
            original = path.read_bytes()
            copied.write_bytes(original)
            path.write_bytes(original.replace(b" ", b"\t", 1))
            with self.assertRaisesRegex(AssertionError, "materialized_binding SHA-256"):
                load_binding(copied)
            path.write_bytes(original)
            owner = path.parent.parent / "run_manifest.json"
            manifest = json.loads(owner.read_text())
            manifest["outputs"] = [r for r in manifest["outputs"] if r["path"] != str(path.resolve())]
            owner.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "unique sealed record"):
                load_binding(copied)

    def test_missing_axis_and_tampered_receipt_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); provider,_=self.setup_bank(root)
            source=load_binding(self.base_path)
            with self.assertRaisesRegex(ValueError,'without a pure response'):
                provider.compile_request(dict(schema_version=1,role=provider.ROLE,source_binding_path=str(self.base_path),
                    source_field_manifest=source['manifest'],numerical_contract_path=str(self.contract_path),
                    response_basis_paths=self.bases,candidate_voltages_v=dict(s1=0.,s2=0.,p1=1.,p2=0.)))
            path,plan=self.materialize(root,provider,self.base_path,dict(s1=1.,s2=0.,p1=0.,p2=0.),'target')
            receipt=Path(plan['materialization']['receipts']['parent']); data=json.loads(receipt.read_text()); data['responses'][0]['coefficient']=.1; receipt.write_text(json.dumps(data))
            owner=path.parent.parent/'run_manifest.json'; seal=json.loads(owner.read_text())
            for record in seal['outputs']:
                if record['path']==str(receipt):record.update(bytes=receipt.stat().st_size,sha256=hashlib.sha256(receipt.read_bytes()).hexdigest())
            owner.write_text(json.dumps(seal))
            with self.assertRaisesRegex(ValueError,'receipt differs'):
                load_binding(path)


class NativeStaticBindingTest(unittest.TestCase):
    def test_contract_stopping_loads_and_matches_all_levels_without_weakening_guards(self):
        for mutation in (None, "local_default", "value", "unsealed", "digest", "extra"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                descriptor = self.fixture(root)
                contract_path = root / "numerical_contract.json"
                contract = {"simion": {"numerical_profiles": {"native_static_field": {
                    "refine": {"convergence_v": 1e-5}}}}}
                contract_path.write_text(json.dumps(contract))
                expected = resolve_native_refine_numerics(contract)
                for index, level in enumerate((descriptor["parent"], *descriptor["refinement_windows"])):
                    plan_path = Path(level["numerical_plan_path"])
                    plan = json.loads(plan_path.read_text())
                    if mutation != "local_default" or not index:
                        plan.update(expected, numerical_contract_path=str(contract_path))
                    if mutation == "value" and index:
                        plan["convergence_v"] = 1e-7
                    if mutation == "extra" and index:
                        plan["options"] = {"convergence": 1e-5}
                    plan_path.write_text(json.dumps(plan))
                    manifest_path = Path(level["manifest"])
                    manifest = json.loads(manifest_path.read_text())
                    for record in manifest["outputs"]:
                        if record["path"] == str(plan_path):
                            record["bytes"] = plan_path.stat().st_size
                    if mutation != "unsealed":
                        manifest["outputs"].append({"path": str(contract_path),
                            "bytes": contract_path.stat().st_size,
                            "sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest()})
                    manifest_path.write_text(json.dumps(manifest))
                if mutation == "digest":
                    contract_path.write_text(contract_path.read_text().replace("1e-05", "1e-07"))
                path = root / "binding.json"
                path.write_text(json.dumps(descriptor))
                if mutation in ("value", "unsealed", "extra"):
                    with self.assertRaises(ValueError):
                        load_binding(path)
                elif mutation == "digest":
                    with self.assertRaises(AssertionError):
                        load_binding(path)
                else:
                    binding = load_binding(path)
                    self.assertEqual(native_numerics_match(binding, contract_path), mutation is None)
                    self.assertEqual(binding["native_solver_numerics"]["convergence_v"], 1e-5)

    def test_native_level_surface_null_requires_sealed_non_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'logs').mkdir()
            def record(path, value):
                path.write_text(json.dumps(value), encoding='utf-8')
                return dict(path=str(path), bytes=path.stat().st_size,
                            sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            grid = dict(origin_mm=[0, 0, 0], pitch_mm=[.25]*3, dimensions=[5]*3, symmetry='x')
            plan = dict(box_mm=[0, 0, 0, 1, 1, 1], pitch_mm=grid['pitch_mm'],
                        dimensions=grid['dimensions'], mirror_axes=['x'], surface='fractional',
                        ordinary_static_pa=True)
            pa = root / 'field.pa'
            records = [record(pa, {}), record(root/'voltage.json', {}),
                       record(root/'geometry.json', {}), record(root/'plan.json', plan),
                       record(root/'logs/gem2pa.log', {'exit_code': 0})]
            summary = dict(status='success', refine_completed=True, failure_stage=None,
                           surface_before_builder=dict(exists=False, bytes=None),
                           surface_after_builder=dict(exists=False, bytes=None),
                           stage_seconds=dict(gem2pa_seconds=1), native_outputs=[dict(name=pa.name)])
            manifest = root/'run_manifest.json'
            def seal(value, status='success', extra=()):
                row = record(root/'summary.json', value)
                manifest.write_text(json.dumps(dict(status=status, outputs=[*records, row, *extra])), encoding='utf-8')
            spec = dict(manifest=str(manifest), pa_path=str(pa), surface_path=None,
                        voltage_authority_path=str(root/'voltage.json'),
                        geometry_authority_path=str(root/'geometry.json'),
                        numerical_plan_path=str(root/'plan.json'), grid=grid)
            seal(summary)
            resolved = _load_native_level(spec)
            self.assertIsNone(resolved['sources']['surface'])
            self.assertIsNone(resolved['records']['surface'])
            manifest.write_text(json.dumps(dict(status='success', outputs=records)), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'unique sealed record'):
                _load_native_level(spec)
            for key, value in (('refine_completed', False), ('status', 'failed'),
                               ('surface_before_builder', dict(exists=True, bytes=12)),
                               ('surface_after_builder', dict(exists=True, bytes=12))):
                with self.subTest(key=key):
                    bad = copy.deepcopy(summary); bad[key] = value; seal(bad)
                    with self.assertRaisesRegex(ValueError, 'non-generation evidence'):
                        _load_native_level(spec)
            seal(summary, status='failed')
            with self.assertRaisesRegex(ValueError, 'successful'):
                _load_native_level(spec)
            sidecar = root/'field.pa-surf'
            sidecar_record = record(sidecar, {})
            seal(summary, extra=[sidecar_record])
            sidecar.unlink()
            with self.assertRaisesRegex(ValueError, 'sealed surface record'):
                _load_native_level(spec)
            spec['surface_path'] = str(sidecar)
            with self.assertRaisesRegex(ValueError, 'missing or changed size'):
                _load_native_level(spec)
            seal(summary)
            spec['surface_path'] = None
            (root/'summary.json').write_text('{}', encoding='utf-8')
            with self.assertRaises((ValueError, AssertionError)):
                _load_native_level(spec)

    def test_crop_surface_null_preserves_original_compile_and_retained_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, derived = root/'source', root/'crop'
            for folder in (source/'logs', source/'inputs', derived/'results'):
                folder.mkdir(parents=True)
            def record(path, value):
                path.write_text(json.dumps(value), encoding='utf-8')
                return dict(path=str(path), bytes=path.stat().st_size,
                            sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            source_pa, pa = source/'field.pa', derived/'field.pa'
            source_manifest, manifest = source/'run_manifest.json', derived/'run_manifest.json'
            plan = dict(box_mm=[0, 0, 0, 1, 1, 1], pitch_mm=[.25]*3,
                        dimensions=[5]*3, mirror_axes=['x'], surface='fractional', ordinary_static_pa=True)
            plan.update(frozen_input=str(source/'voltage.json'), resolved_geometry=str(source/'geometry.json'))
            source_records = [record(source_pa, {}), record(source/'inputs/plan.json', plan),
                              record(source/'logs/gem2pa.log', {'exit_code': 0}),
                              record(source/'inputs/frozen_input.json', {}),
                              record(source/'inputs/resolved_geometry.json', {})]
            original_authority_records = [record(source/'voltage.json', {}), record(source/'geometry.json', {})]
            source_summary = dict(status='success', refine_completed=True, failure_stage=None,
                                  surface_before_builder=dict(exists=False, bytes=None),
                                  surface_after_builder=dict(exists=False, bytes=None),
                                  stage_seconds=dict(gem2pa_seconds=1), native_outputs=[dict(name=source_pa.name)])
            def seal_source(extra=()):
                rows = [*source_records, record(source/'summary.json', source_summary), *extra]
                source_manifest.write_text(json.dumps(dict(status='success', outputs=rows)), encoding='utf-8')
            seal_source()
            receipt_path, plan_path = derived/'results/crop_receipt.json', derived/'results/consumer_plan.json'
            consumer_plan = copy.deepcopy(plan)
            consumer_plan.update(box_mm=[0, 0, 0, .5, 1, 1], dimensions=[3, 5, 5])
            crop = dict(receipt_path=str(receipt_path), source_manifest=str(source_manifest),
                        source_pa=str(source_pa), full_dimensions=[5]*3,
                        consumer_dimensions=[3, 5, 5], refine_after_crop=False)
            consumer_plan['crop'] = crop
            sample = dict(before=[7, True], after=[7, True], reloaded=[7, True])
            receipt = dict(crop, status='PASS', output_pa=str(pa), retained_sample_count=2,
                           retained_node_samples=[sample], signed_vc_field_samples=[sample])
            summary = dict(status='success', failure_stage=None, refine_performed=False, crop_completed=True,
                           surface_before_crop=dict(exists=False, bytes=None),
                           surface_after_crop=dict(exists=False, bytes=None))
            base_records = [record(pa, {}), record(derived/'voltage.json', {}), record(derived/'geometry.json', {})]
            def seal():
                source_seal = dict(path=str(source_manifest), bytes=source_manifest.stat().st_size,
                                   sha256=hashlib.sha256(source_manifest.read_bytes()).hexdigest())
                rows = [*base_records, source_seal, source_records[0], *original_authority_records,
                        record(plan_path, consumer_plan),
                        record(receipt_path, receipt), record(derived/'summary.json', summary)]
                manifest.write_text(json.dumps(dict(status='success', outputs=rows)), encoding='utf-8')
            spec = dict(manifest=str(manifest), pa_path=str(pa), surface_path=None,
                        voltage_authority_path=str(derived/'voltage.json'),
                        geometry_authority_path=str(derived/'geometry.json'), numerical_plan_path=str(plan_path),
                        grid=dict(origin_mm=[0]*3, pitch_mm=[.25]*3, dimensions=[3, 5, 5], symmetry='x'))
            seal()
            self.assertIsNone(_load_native_level(spec)['records']['surface'])
            for key, value in (('status', 'FAIL'), ('output_pa', str(source_pa)),
                               ('refine_after_crop', True), ('retained_sample_count', 3),
                               ('signed_vc_field_samples', [dict(before=[1], after=[2], reloaded=[2])])):
                with self.subTest(key=key):
                    original = receipt[key]; receipt[key] = value; seal()
                    with self.assertRaises(ValueError):
                        _load_native_level(spec)
                    receipt[key] = original
            summary['refine_performed'] = True; seal()
            with self.assertRaises(ValueError):
                _load_native_level(spec)
            summary['refine_performed'] = False
            source_summary['refine_completed'] = False; seal_source(); seal()
            with self.assertRaisesRegex(ValueError, 'original solved grid'):
                _load_native_level(spec)
            source_summary['refine_completed'] = True
            sidecar = source/'field.pa-surf'
            sidecar_record = record(sidecar, {}); sidecar.unlink()
            seal_source([sidecar_record]); seal()
            with self.assertRaisesRegex(ValueError, 'sealed surface record'):
                _load_native_level(spec)
            seal_source(); seal()
            receipt_path.write_text('{}', encoding='utf-8')
            with self.assertRaises((ValueError, AssertionError)):
                _load_native_level(spec)
            # Earlier official cropped J assets have a real surface and only
            # their own frozen authority copies, not ancestor external records.
            sidecar = derived/'field.pa-surf'
            base_records.append(record(sidecar, {}))
            original_authority_records.clear()
            spec['surface_path'] = str(sidecar)
            seal()
            self.assertEqual(_load_native_level(spec)['sources']['surface'], str(sidecar.resolve()))
            sidecar.unlink()
            with self.assertRaisesRegex(ValueError, 'missing or changed size'):
                _load_native_level(spec)

    def test_native_factories_reuse_matching_open_pa_container_userdata(self):
        lua = Path(os.environ.get("ProgramFiles", "C:/Program Files"))/"SIMION-2020/lua.exe"
        if not lua.is_file():
            self.skipTest("standalone vendor Lua unavailable")
        adapter = REPO_ROOT/"projects/parallel_mirror_dual_stripe_mr_tof/simion/scalar_field_adapter.lua"
        fixture = r'''
local opens=0;local items={}
local function make_pa(path)
 local pa={path=path,symmetry='3dplanar[x]',nx=11,ny=11,nz=11,dx_mm=.5,dy_mm=1,dz_mm=2}
 function pa:potential()return 7 end
 function pa:potential_vc()return 7 end
 function pa:inside_vc()return true end
 function pa:field_vc()return 2,4,6 end
 function pa:save()error('reuse must not save')end
 function pa:close()error('reuse must not close owned PA')end
 function pa:electrode()error('reuse must not mutate')end
 return pa
end
local container=newproxy(true);local mt=getmetatable(container)
mt.__len=function()return #items end
mt.__index=function(_,key)
 if key=='open' then
  return function(_,path)opens=opens+1;local pa=make_pa(path);items[#items+1]=pa;return pa end
 end
 return items[key]
end
assert(type(container)=='userdata' and not pcall(ipairs,container))
simion={pas=container,early_access=function()end,experimental={make_efield_adjust=function(f)return f end}}
local function level(path)
 return {mode='native_static_pa',scalar_pa=path,origin_mm={0,-5,-10},pitch_mm={.5,1,2},
 dimensions={11,11,11},symmetry='x'}
end
local apply=assert(loadfile(arg[1]))()
local b=level('C:/frozen/base.pa');local w=level('C:/frozen/window.pa')
w.name='window';w.active_box_mm={{-3,3},{-2,2},{-4,4}};b.refinement_windows={w}
local first=apply(b,'raw_sample');assert(opens==2)
local second=apply(b,'raw_sample');assert(opens==2,'second factory must not open base/windows again')
for _,p in ipairs({{-2,0,0},{0,0,0},{2,0,0},{1,3,0}}) do
 local a={first(unpack(p))};local c={second(unpack(p))}
 assert(a[1]==7 and a[2]==4 and a[3]==4 and a[4]==3)
 for i=1,4 do assert(a[i]==c[i]) end
end
for _,change in ipairs({'path','pitch','dimension','symmetry'}) do
 local stale=make_pa('C:/frozen/base.pa')
 if change=='path' then stale.path='C:/other/base.pa' end
 if change=='pitch' then stale.dy_mm=.25 end
 if change=='dimension' then stale.nz=12 end
 if change=='symmetry' then stale.symmetry='3dplanar' end
 items={stale};local before=opens
 apply(level('C:/frozen/base.pa'),'raw_sample')(1,0,0)
 assert(opens==before+1,change..' stale PA must not be reused')
end
items={make_pa([[c:\frozen\base.pa]])};local before=opens
apply(level('C:/frozen/base.pa'),'raw_sample')(1,0,0)
assert(opens==before,'normalized actual path may reuse')
print('NATIVE_EXISTING_PA_REUSE_PASS')
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/"fixture.lua"
            source.write_text(fixture, encoding="utf-8")
            result = subprocess.run([str(lua), str(source), str(adapter)], cwd=REPO_ROOT,
                                    capture_output=True, text=True, timeout=10, check=True)
            self.assertIn("NATIVE_EXISTING_PA_REUSE_PASS", result.stdout)
            self.assertIn("workbench_reused=false existing_pa_reused=true", result.stdout)

    def test_native_shadowed_windows_do_not_open_and_keep_first_match_samples(self):
        lua = Path(os.environ.get("ProgramFiles", "C:/Program Files"))/"SIMION-2020/lua.exe"
        if not lua.is_file():
            self.skipTest("standalone vendor Lua unavailable")
        adapter = REPO_ROOT/"projects/parallel_mirror_dual_stripe_mr_tof/simion/scalar_field_adapter.lua"
        fixture = r'''
local opens={}
simion={pas={},early_access=function()end,experimental={make_efield_adjust=function(f)return f end}}
function simion.pas:open(path)
 opens[path]=(opens[path] or 0)+1
 local value=path=='fine' and 20 or path=='partial' and 30 or path=='scalar' and 40 or 2
 local pa={symmetry=(path=='scalar' or path=='mask') and '3dplanar' or '3dplanar[x]',
 nx=21,ny=21,nz=21,dx_mm=1,dy_mm=1,dz_mm=1}
 function pa:potential()return path=='mask' and 1 or value end
 function pa:inside_vc()return true end
 function pa:field_vc(x)return x<0 and -value or value,2*value,3*value end
 function pa:potential_vc()return value end
 function pa:save()error('no save')end
 return pa
end
simion.experimental.field_array=function(t)
 return {efield=function()return 40,80,120 end}
end
local function level(path,box,mode)
 return {mode=mode or 'native_static_pa',scalar_pa=path,valid_pa='mask',origin_mm={0,-10,-10},
 pitch_mm={1,1,1},dimensions={21,21,21},symmetry='x',name=path,active_box_mm=box,
 ideal_sheet_projection={}}
end
local apply=assert(loadfile(arg[1]))()
local fine=level('fine',{{-3,3},{-3,3},{-3,3}})
local hidden=level('hidden',{{-3,3},{-3,3},{-3,3}})
local partial=level('partial',{{-4,4},{-2,2},{-2,2}})
local b=level('base');b.refinement_windows={fine,hidden,partial}
local sample=apply(b,'raw_sample')
assert(opens.fine==1 and opens.hidden==nil and opens.partial==1)
for _,point in ipairs({{-3,-3,-3},{0,0,0},{3,3,3},{-4,0,0},{4,0,0},{5,0,0}}) do
 local x,y,z=unpack(point)
 local value=math.abs(x)<=3 and 20 or math.abs(x)<=4 and 30 or 2
 local v,ex,ey,ez=sample(x,y,z)
 assert(v==value and ex==(x<0 and -value or value) and ey==2*value and ez==3*value,
  'inclusive first-match values differ')
end
-- Removing the unreachable window is exactly the old first-match result.
local before=opens.hidden
b.refinement_windows={fine,partial}
local reference=apply(b,'raw_sample')
for _,p in ipairs({{-3,0,0},{3,3,3},{4,0,0},{5,0,0}}) do
 local actual={sample(unpack(p))};local expected={reference(unpack(p))}
 for i=1,4 do assert(actual[i]==expected[i]) end
end
assert(opens.hidden==before and b.refinement_windows[1]==fine)
-- No union of earlier boxes is eligible.
local left=level('left',{{-3,0},{-3,3},{-3,3}})
local right=level('right',{{0,3},{-3,3},{-3,3}})
local union=level('union',{{-3,3},{-3,3},{-3,3}})
b.refinement_windows={left,right,union};apply(b)
assert(opens.union==1)
-- Non-native scalar/mask windows retain the existing load path, even covered.
local scalar=level('scalar',{{1,2},{-2,2},{-2,2}},'comsol_static_scalar_v')
b.refinement_windows={fine,scalar};apply(b)
assert(opens.scalar==1 and opens.mask==1)
-- A malformed or halo-invalid hidden box cannot bypass validation.
for _,box in ipairs({{{-3,3},{0,0},{-2,2}},{{-3,3},{-math.huge,2},{-2,2}},
 {{-3,3},{-3,3},{-3,3}}}) do
 local invalid=level('invalid',box)
 if box[2][1]==-3 then invalid.dimensions={3,3,3} end
 b.refinement_windows={fine,invalid}
 assert(not pcall(apply,b) and opens.invalid==nil)
end
print('NATIVE_SHADOWED_WINDOWS_PASS')
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/"fixture.lua"
            source.write_text(fixture, encoding="utf-8")
            result = subprocess.run([str(lua), str(source), str(adapter)], cwd=REPO_ROOT,
                                    capture_output=True, text=True, timeout=10, check=True)
            self.assertIn("NATIVE_SHADOWED_WINDOWS_PASS", result.stdout)
            self.assertIn("skip_shadowed=true name=hidden covered_by=fine", result.stdout)

    def test_native_parent_reuses_only_matching_workbench_pa_without_mutation(self):
        lua = Path(os.environ.get("ProgramFiles", "C:/Program Files"))/"SIMION-2020/lua.exe"
        if not lua.is_file():
            self.skipTest("standalone vendor Lua unavailable")
        adapter = REPO_ROOT/"projects/parallel_mirror_dual_stripe_mr_tof/simion/scalar_field_adapter.lua"
        fixture = r'''
local opens=0;local support_reads=0;local unknown=false;local bad_field=false
simion={pas={},wb={instances={}},early_access=function()end,
 experimental={make_efield_adjust=function(f)return f end}}
local function make_pa()
 local pa={path='C:/frozen/parent.pa',filename='parent.pa',symmetry='3dplanar[x]',nx=11,ny=11,nz=11,
 dx_mm=.5,dy_mm=1,dz_mm=2}
 function pa:potential()support_reads=support_reads+1;return unknown and 0/0 or 2 end
 function pa:inside_vc()return true end
 function pa:field_vc()return bad_field and 0/0 or 2,4,6 end
 function pa:potential_vc()return 2 end
 function pa:save()error('shared PA save forbidden')end
 function pa:electrode()error('shared PA mutation forbidden')end
 function pa:fast_adjust()error('shared PA adjustment forbidden')end
 return pa
end
function simion.pas:open(path)opens=opens+1;return make_pa()end
local binding={mode='native_static_pa',scalar_pa=[[c:\frozen\parent.pa]],origin_mm={0,-5,-10},
 pitch_mm={.5,1,2},dimensions={11,11,11},symmetry='x'}
local apply=assert(loadfile(arg[1]))()
local function instance_list(items)
 local container=newproxy(true)
 local mt=getmetatable(container)
 mt.__len=function()return #items end
 mt.__index=function(_,index)return items[index] end
 assert(type(container)=='userdata' and not pcall(ipairs,container),
  'fixture must reproduce table-only ipairs failure')
 return container
end
for _,change in ipairs({'match','path','dimension','pitch','symmetry','absent'}) do
 local pa=make_pa()
 if change=='path' then pa.path='C:/other/parent.pa' end
 if change=='dimension' then pa.ny=12 end
 if change=='pitch' then pa.dy_mm=.25 end
 if change=='symmetry' then pa.symmetry='3dplanar' end
 simion.wb.instances=instance_list(change=='absent' and {} or {{pa=pa}})
 local before=opens
 local sample=apply(binding,'raw_sample')
 assert(opens-before==(change=='match' and 0 or 1),change..' open count')
 local v,ex,ey,ez=sample(1,0,0)
 assert(v==2 and ex==4 and ey==4 and ez==3,'reuse/open field units must be identical')
end
local sample=apply(binding,'raw_sample')
sample(1.1,0,0);local checked=support_reads
sample(1.2,0,0);assert(support_reads==checked,'same support must not rescan')
sample(-1.2,0,0);assert(support_reads==checked,'mirrored support shares the checked box')
bad_field=true;assert(not pcall(sample,1.2,0,0),'same box must still check returned field');bad_field=false
unknown=true;assert(not pcall(sample,1.6,0,0),'new invalid box must fail')
unknown=false;local failed_reads=support_reads
sample(1.6,0,0);assert(support_reads>failed_reads,'failed box must not be cached')
local new_checked=support_reads
sample(1.7,0,0);assert(support_reads==new_checked,'successful new box must be cached')
assert(not pcall(sample,6,0,0),'cached support must not bypass boundary checks')
print('NATIVE_PARENT_REUSE_PASS')
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/"fixture.lua"
            source.write_text(fixture, encoding="utf-8")
            result = subprocess.run([str(lua), str(source), str(adapter)], cwd=REPO_ROOT,
                                    capture_output=True, text=True, timeout=10, check=True)
            self.assertIn("NATIVE_PARENT_REUSE_PASS", result.stdout)

    def test_native_lua_routes_mirrored_axis_and_never_falls_back_on_invalid_local_support(self):
        lua = Path(os.environ.get("ProgramFiles", "C:/Program Files"))/"SIMION-2020/lua.exe"
        if not lua.is_file(): self.skipTest("standalone vendor Lua unavailable")
        adapter = REPO_ROOT/"projects/parallel_mirror_dual_stripe_mr_tof/simion/scalar_field_adapter.lua"
        fixture = r'''
local unknown=false;local opens=0
simion={pas={},early_access=function()end,experimental={make_efield_adjust=function(f)return f end}}
function simion.pas:open(path)
 opens=opens+1;local value=path=='local' and 20 or 2
 local pa={symmetry='3dplanar[x]',nx=11,ny=11,nz=11,dx_mm=.5,dy_mm=1,dz_mm=2}
 function pa:potential(i,j,k) assert(i>=0);return unknown and path=='local' and 0/0 or value end
 function pa:inside_vc()return true end
 function pa:field_vc(x,y,z)return x<0 and -value or value,2*value,3*value end
 function pa:potential_vc()return value end
 function pa:save()error('native consumer must not save')end
 return pa
end
local function level(path)
 return {mode='native_static_pa',scalar_pa=path,origin_mm={0,-5,-10},pitch_mm={.5,1,2},
 dimensions={11,11,11},symmetry='x'}
end
local b=level('parent');local w=level('local');w.name='local';w.active_box_mm={{-3,3},{-2,2},{-4,4}}
b.refinement_windows={w};local apply=assert(loadfile(arg[1]))()
local fly=apply(b);assert(opens==2)
local ex,ey,ez=fly(-1,0,0);assert(ex==-40 and ey==40 and ez==30)
ex,ey,ez=fly(0,0,0);assert(ex==40,'mirror plane support allowed without forcing Ex zero')
ex,ey,ez=fly(1,3,0);assert(ex==4 and ey==4 and ez==3,'outside active routes father')
local raw=apply(b,'raw_sample');local v,rx,ry,rz=raw(-1,0,0)
assert(v==20 and rx==-40 and ry==40 and rz==30,'same raw signature and axis units')
unknown=true;assert(not pcall(fly,2,0,0),'new invalid local support must fail, not father fallback')
unknown=false;assert(not pcall(raw,5,0,0),'outer support halo fails')
print('NATIVE_STATIC_QUERY_PASS')
'''
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"fixture.lua";path.write_text(fixture,encoding="utf-8")
            result=subprocess.run([str(lua),str(path),str(adapter)],cwd=REPO_ROOT,capture_output=True,text=True,timeout=10,check=True)
            self.assertIn("NATIVE_STATIC_QUERY_PASS",result.stdout)

    def fixture(self, root):
        authority = {"analyzer_electrode_voltages_v": [0.0]*20,
                     "assembly": {"accelerator_iob_origin_mm": [0,0,0], "detector": {"box": {}},
                       "accelerator_resolved_electrodes": {"local_to_pa_translation_mm": [0,0,0],
                         "grounded_enclosure": {"outer_box_mm": {"z_min_mm": 0}},
                         "repeller": {"solid_box_mm": {"z_min_mm": 1}}, "grid_supports": [], "rings": []}}}
        geometry = {"detector": {"box": {}}}
        levels = []
        for name in ("parent", "local"):
            directory = root/name
            directory.mkdir()
            grid = {"origin_mm": [0,-5,-5], "pitch_mm": [0.5,1,1], "dimensions": [11,11,11], "symmetry": "x"}
            plan = {"box_mm": [0,-5,-5,5,5,5], "pitch_mm": grid["pitch_mm"], "dimensions": grid["dimensions"],
                    "mirror_axes": ["x"], "surface": "fractional", "ordinary_static_pa": True}
            if levels:
                plan.update(parent_manifest=levels[0]["manifest"], parent_pa=levels[0]["pa_path"],
                            boundary_mode="x_mirror_five_faces")
            else:
                plan["boundary_mode"] = "grounded_enclosure"
            files = {"field.pa": b"pa", "field.pa-surf": b"surf", "authority.json": json.dumps(authority).encode(),
                     "geometry.json": json.dumps(geometry).encode(), "plan.json": json.dumps(plan).encode()}
            for filename, content in files.items():
                (directory/filename).write_bytes(content)
            records = [{"path": str(directory/f), "bytes": len(content), "sha256": "sealed"}
                       for f, content in files.items()]
            manifest = directory/"run_manifest.json"
            manifest.write_text(json.dumps({"status": "success", "outputs": records}))
            levels.append(dict(manifest=str(manifest), pa_path=str(directory/"field.pa"),
                               surface_path=str(directory/"field.pa-surf"), voltage_authority_path=str(directory/"authority.json"),
                               geometry_authority_path=str(directory/"geometry.json"), numerical_plan_path=str(directory/"plan.json"), grid=grid))
        local = dict(levels[1], name="local", parent_manifest=levels[0]["manifest"],
                     active_box_mm=[[-4,4],[-3,3],[-3,3]])
        instances = [dict(role=role, manifest=levels[0]["manifest"], pa_path=levels[0]["pa_path"], origin_mm=[0,0,0])
                     for role in ("global_fallback", "native_corridor", "accelerator", "detector")]
        return dict(schema_version=1, role="mrtof_native_static_field_binding", parent=levels[0],
                    refinement_windows=[local], instances=instances)

    def test_native_resolves_sealed_authority_and_serializes_mirror_without_comsol_mask(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); descriptor = self.fixture(root)
            path = root/"binding.json"; path.write_text(json.dumps(descriptor))
            binding = load_binding(path)
            self.assertEqual(binding["mode"], "native_static_pa")
            self.assertEqual(len(binding["instances"]), 4)
            self.assertNotIn("valid_pa", binding["sources"])
            self.assertEqual(binding["native_solver_numerics"]["refine_stopping"], "installed_default")
            self.assertEqual(binding["native_solver_numerics"]["boundary_mode"], "grounded_enclosure")
            self.assertEqual(binding["refinement_windows"][0]["native_solver_numerics"]["boundary_mode"],
                             "x_mirror_five_faces")
            text = _scalar_field_lua_fields(binding) + _scalar_refinement_windows_lua(binding["refinement_windows"])
            self.assertIn("native_static_pa", text)
            self.assertNotIn("valid_pa", text)

    def test_direct_parent_allows_same_field_aliases_with_distinct_active_boxes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            descriptor = self.fixture(root)
            alias = copy.deepcopy(descriptor["refinement_windows"][0])
            alias.update(name="alias", active_box_mm=[[-2, 2], [-1, 1], [-1, 1]])
            descriptor["refinement_windows"].insert(0, alias)
            path = root / "binding.json"
            path.write_text(json.dumps(descriptor))
            result = load_binding(path)
            self.assertEqual([window["name"] for window in result["refinement_windows"]], ["alias", "local"])
            self.assertEqual(result["refinement_windows"][0]["sources"], result["refinement_windows"][1]["sources"])

    def test_nested_native_boundary_source_preserves_priority_and_rejects_invalid_ancestry(self):
        for mutation in (None, "self", "cycle", "outside", "source_pa", "voltage", "geometry", "halo"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                descriptor = self.fixture(root)
                source = descriptor["refinement_windows"][0]
                fine_root = root / "fine"
                fine_root.mkdir()
                fine = copy.deepcopy(source)
                fine.update(name="fine", parent_manifest=source["manifest"])
                for key in ("manifest", "pa_path", "surface_path", "voltage_authority_path",
                            "geometry_authority_path", "numerical_plan_path"):
                    original = Path(fine[key])
                    fine[key] = str(fine_root / original.name)
                    Path(fine[key]).write_bytes(original.read_bytes())
                fine["grid"].update(pitch_mm=[.25, .5, .5], dimensions=[21, 21, 21])
                plan = json.loads(Path(fine["numerical_plan_path"]).read_text())
                plan.update(parent_manifest=source["manifest"], parent_pa=source["pa_path"],
                            pitch_mm=fine["grid"]["pitch_mm"], dimensions=fine["grid"]["dimensions"])

                def write_record(level, key, value):
                    path = Path(level[key])
                    path.write_text(json.dumps(value))
                    manifest = Path(level["manifest"])
                    records = json.loads(manifest.read_text())
                    for record in records["outputs"]:
                        target = manifest.parent / Path(record["path"]).name
                        record.update(path=str(target), bytes=target.stat().st_size)
                    manifest.write_text(json.dumps(records))

                if mutation == "self":
                    fine["parent_manifest"] = fine["manifest"]
                    plan.update(parent_manifest=fine["manifest"], parent_pa=fine["pa_path"])
                elif mutation == "cycle":
                    source["parent_manifest"] = fine["manifest"]
                    parent_plan = json.loads(Path(source["numerical_plan_path"]).read_text())
                    parent_plan.update(parent_manifest=fine["manifest"], parent_pa=fine["pa_path"])
                    write_record(source, "numerical_plan_path", parent_plan)
                elif mutation == "outside":
                    plan["box_mm"][3] = 6
                    fine["grid"]["dimensions"][0] = 25
                    plan["dimensions"][0] = 25
                elif mutation == "source_pa":
                    plan["parent_pa"] = descriptor["parent"]["pa_path"]
                elif mutation == "halo":
                    fine["active_box_mm"][0] = [-5, 5]
                write_record(fine, "numerical_plan_path", plan)
                if mutation in ("voltage", "geometry"):
                    key = "voltage_authority_path" if mutation == "voltage" else "geometry_authority_path"
                    value = json.loads(Path(fine[key]).read_text())
                    if mutation == "voltage":
                        value["analyzer_electrode_voltages_v"][10] = 1
                    else:
                        value["detector"]["box"] = {"different": True}
                    write_record(fine, key, value)
                alias = copy.deepcopy(source)
                alias.update(name="source_alias", active_box_mm=[[-2, 2], [-1, 1], [-1, 1]])
                descriptor["refinement_windows"] = [fine, source, alias]
                path = root / "binding.json"
                path.write_text(json.dumps(descriptor))
                if mutation is not None:
                    with self.assertRaises(ValueError):
                        load_binding(path)
                else:
                    result = load_binding(path)
                    self.assertEqual([window["name"] for window in result["refinement_windows"]],
                                     ["fine", "local", "source_alias"])
                    self.assertEqual(result["native_solver_numerics"]["boundary_mode"], "grounded_enclosure")
                    self.assertEqual(result["refinement_windows"][0]["native_solver_numerics"]["boundary_mode"],
                                     "x_mirror_five_faces")

    def test_native_rejects_unsealed_or_conflicting_physical_and_numerical_inputs(self):
        for mutation in ("pitch", "voltage", "geometry", "halo", "surface", "parent", "convergence", "collision", "parent_boundary"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); d = self.fixture(root); local = d["refinement_windows"][0]
                if mutation == "pitch": local["grid"]["pitch_mm"][1] = 0.5
                elif mutation == "halo": local["active_box_mm"][0] = [-5,5]
                elif mutation == "surface": Path(local["surface_path"]).unlink()
                elif mutation == "parent": local["parent_manifest"] = str(root/"other.json")
                elif mutation == "collision": d["instances"][0]["origin_mm"] = [float("nan"),0,0]
                elif mutation == "parent_boundary":
                    p = Path(d["parent"]["numerical_plan_path"]); value = json.loads(p.read_text())
                    value["boundary_mode"] = "x_mirror_five_faces"; p.write_text(json.dumps(value))
                    manifest = Path(d["parent"]["manifest"]); records = json.loads(manifest.read_text())
                    for record in records["outputs"]:
                        if record["path"] == str(p): record["bytes"] = p.stat().st_size
                    manifest.write_text(json.dumps(records))
                else:
                    key = {"voltage": "voltage_authority_path", "geometry": "geometry_authority_path",
                           "convergence": "numerical_plan_path"}[mutation]
                    p = Path(local[key]); value = json.loads(p.read_text())
                    if mutation == "voltage": value["analyzer_electrode_voltages_v"][10] = 1
                    elif mutation == "geometry": value["detector"]["box"] = {"different": True}
                    else: value["convergence"] = 0.01
                    p.write_text(json.dumps(value))
                    manifest = Path(local["manifest"]); records = json.loads(manifest.read_text())
                    for record in records["outputs"]:
                        if record["path"] == str(p): record["bytes"] = p.stat().st_size
                    manifest.write_text(json.dumps(records))
                path = root/"binding.json"; path.write_text(json.dumps(d))
                with self.assertRaises(ValueError): load_binding(path)


class NativeCollisionReferenceTest(unittest.TestCase):
    def fixture(self, root):
        native = NativeStaticBindingTest().fixture(root)
        for level in (native["parent"], native["refinement_windows"][0]):
            authority_path = Path(level["voltage_authority_path"])
            authority = json.loads(authority_path.read_text())
            authority["assembly"]["accelerator_resolved_electrodes"]["grid_supports"] = [
                dict(frame_outer_box_mm={"z_min_mm": z}, component_electrode_id=identifier,
                     ideal_sheet_mm=dict(x_min_mm=-1, x_max_mm=1, y_min_mm=-1, y_max_mm=1, z_mm=z))
                for identifier, z in ((101, 0), (102, 1))]
            authority_path.write_text(json.dumps(authority))
            manifest_path = Path(level["manifest"])
            manifest = json.loads(manifest_path.read_text())
            for record in manifest["outputs"]:
                if record["path"] == str(authority_path):
                    record["bytes"] = authority_path.stat().st_size
            manifest_path.write_text(json.dumps(manifest))
        source = root / "native_binding.json"
        source.write_text(json.dumps(native))
        owner = root / "native_manifest.json"
        owner.write_text(json.dumps({"status": "success", "outputs": [{
            "path": str(source), "bytes": source.stat().st_size,
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]}))
        export = dict(
            authority=json.loads(Path(native["parent"]["voltage_authority_path"]).read_text()),
            geometry=json.loads(Path(native["parent"]["geometry_authority_path"]).read_text()),
            grid=dict(origin_mm=[-5, -5, -5], pitch_mm=[.25]*3, dimensions=[41]*3),
            sources={"scalar_pa": "comsol.pa", "valid_pa": "comsol_valid.pa"},
            records={}, mode="scalar_potential")
        descriptor = dict(schema_version=1, role="mrtof_static_comsol_field_binding",
                          export_manifest="export_manifest.json",
                          native_collision_binding=dict(path=str(source), manifest=str(owner)))
        path = root / "scalar_binding.json"
        return path, descriptor, native, export

    def test_inherits_only_collision_instances_and_real_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            path, descriptor, native, export = self.fixture(Path(directory))
            path.write_text(json.dumps(descriptor))
            with patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding._load_export",
                       return_value=export):
                result = load_binding(path)
            self.assertEqual([i["role"] for i in result["instances"]],
                             [i["role"] for i in native["instances"]])
            self.assertEqual([i["origin_mm"] for i in result["instances"]], [[0, 0, 0]]*4)
            self.assertEqual(result["sources"], export["sources"])
            self.assertEqual(result["grid"], export["grid"])
            self.assertEqual(result["mode"], "scalar_potential")
            self.assertNotIn("refinement_windows", result)
            self.assertNotIn("assembly_receipt_path", result)
            self.assertEqual(result["collision_binding_kind"], "sealed_native_instances")
            self.assertEqual(result["assembly_manifest"], descriptor["native_collision_binding"]["manifest"])
            self.assertEqual(result["collision_manifest"], native["instances"][1]["manifest"])
            self.assertEqual(result["ideal_sheet_projection"],
                             ideal_sheet_projection(export["authority"]["assembly"], export["grid"]))
            self.assertEqual([sheet["component_electrode_id"] for sheet in result["ideal_sheet_projection"]],
                             [101, 102])

    def test_rejects_mismatch_unsealed_and_changed_pose(self):
        for mutation in ("geometry", "voltage", "pose", "failed", "tampered", "mixed", "kind"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                path, descriptor, native, export = self.fixture(Path(directory))
                reference = descriptor["native_collision_binding"]
                if mutation == "geometry":
                    export["geometry"]["extra"] = True
                elif mutation == "voltage":
                    export["authority"]["analyzer_electrode_voltages_v"][19] = 1
                elif mutation == "pose":
                    export["authority"]["assembly"]["accelerator_iob_origin_mm"][1] = 1
                elif mutation == "failed":
                    owner = Path(reference["manifest"])
                    value = json.loads(owner.read_text()); value["status"] = "failed"
                    owner.write_text(json.dumps(value))
                elif mutation == "tampered":
                    source = Path(reference["path"])
                    value = source.read_text().replace('"origin_mm": [0, 0, 0]', '"origin_mm": [1, 0, 0]', 1)
                    source.write_text(value)
                elif mutation == "mixed":
                    descriptor["assembly_manifest"] = "legacy.json"
                else:
                    reference["unexpected"] = True
                path.write_text(json.dumps(descriptor))
                with patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding._load_export",
                           return_value=export), self.assertRaises((ValueError, AssertionError)):
                    load_binding(path)


class StaticFieldSamplingTest(unittest.TestCase):
    def test_zero_weight_terms_do_not_open_assets_and_keep_raw_and_flight_sum(self):
        lua = Path(os.environ.get("ProgramFiles", "C:/Program Files"))/"SIMION-2020/lua.exe"
        if not lua.is_file():
            self.skipTest("standalone vendor Lua unavailable")
        adapter = REPO_ROOT/"projects/parallel_mirror_dual_stripe_mr_tof/simion/scalar_field_adapter.lua"
        fixture = r'''
local opened=0;local assets={}
for name,value in pairs({a=2,b=4,mask=1}) do
 local pa={symmetry='3dplanar',nx=9,ny=9,nz=9,dx_mm=1,dy_mm=1,dz_mm=1}
 function pa:potential() return value end
 function pa:potential_vc() return value end
 assets[name]=pa
end
simion={pas={},early_access=function() end,experimental={}}
function simion.pas:open(path) opened=opened+1;return assert(assets[path],'zero term opened: '..path) end
function simion.experimental.field_array(t)
 return {efield=function() local v=t.V:potential();return v,2*v,3*v end}
end
function simion.experimental.make_efield_adjust(f) return f end
local apply=assert(loadfile(arg[1]))()
local function term(name,weight)
 return {coefficient=weight,scalar_pa=name,valid_pa='mask',origin_mm={0,0,0},
  pitch_mm={1,1,1},ideal_sheet_projection={}}
end
local binding={response_terms={term('a',-.5),term('never_open',0),term('b',1.5)}}
local fly=apply(binding);assert(opened==3)
local ex,ey,ez=fly(3,3,3);assert(ex==5 and ey==10 and ez==15)
local raw=apply(binding,'raw_sample');assert(opened==6)
local v,rx,ry,rz=raw(3,3,3);assert(v==5 and rx==ex and ry==ey and rz==ez)
for _,t in ipairs(binding.response_terms) do t.coefficient=0 end
local zero=apply(binding);local zero_raw=apply(binding,'raw_sample');assert(opened==6)
local zx,zy,zz=zero(3,3,3);assert(zx==0 and zy==0 and zz==0)
local zv,zrx,zry,zrz=zero_raw(3,3,3);assert(zv==0 and zrx==0 and zry==0 and zrz==0)
binding.response_terms[2].response_terms={}
assert(not pcall(apply,binding));assert(opened==6)
binding.response_terms[2].response_terms=nil;binding.response_terms[2].coefficient=0/0
assert(not pcall(apply,binding));assert(opened==6)
print('ZERO_WEIGHT_QUERY_PASS')
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/"fixture.lua"
            source.write_text(fixture, encoding="utf-8")
            completed = subprocess.run([str(lua), str(source), str(adapter)], cwd=REPO_ROOT, capture_output=True,
                                       text=True, timeout=10, check=True)
            self.assertIn("ZERO_WEIGHT_QUERY_PASS", completed.stdout)

    def test_combination_opens_each_scalar_but_only_one_mask_per_ordered_level(self):
        lua = Path(os.environ.get("ProgramFiles", "C:/Program Files"))/"SIMION-2020/lua.exe"
        if not lua.is_file():
            self.skipTest("standalone vendor Lua unavailable")
        adapter = REPO_ROOT/"projects/parallel_mirror_dual_stripe_mr_tof/simion/scalar_field_adapter.lua"
        fixture = r'''
local opens={};local reads={};local values={a=2,b=4,c=8,aw=20,bw=40,cw=80}
local unknown=false;local nonfinite=nil;local mask_reads=0
simion={pas={},early_access=function() end,experimental={}}
function simion.pas:open(path)
 opens[path]=(opens[path] or 0)+1
 local mask=string.find(path,'mask',1,true)~=nil
 assert(mask or values[path],'unexpected scalar')
 local pa={symmetry='3dplanar',nx=11,ny=11,nz=11,dx_mm=1,dy_mm=1,dz_mm=1}
 function pa:potential()
  reads[path]=(reads[path] or 0)+1
  if mask then mask_reads=mask_reads+1;return unknown and 0 or 1 end
  return nonfinite==path and 0/0 or values[path]
 end
 function pa:potential_vc() return self:potential() end
 return pa
end
function simion.experimental.field_array(t)
 return {efield=function() local v=t.V:potential();return v,2*v,3*v end}
end
function simion.experimental.make_efield_adjust(f) return f end
local apply=assert(loadfile(arg[1]))()
local function level(name,mask)
 return {scalar_pa=name,valid_pa=mask,origin_mm={0,0,0},pitch_mm={1,1,1},ideal_sheet_projection={}}
end
local function term(name,weight)
 local t=level(name,name..'_mask');t.coefficient=weight
 local w=level(name..'w',name..'_window_mask')
 w.name='first';w.active_box_mm={{3,5},{3,5},{3,5}}
 t.refinement_windows={w};return t
end
local binding={response_terms={term('a',-.5),term('b',1),term('c',.5)}}
local fly=apply(binding)
for name in pairs(values) do assert(opens[name]==1,'scalar must load independently: '..name) end
assert(opens.a_mask==1 and opens.a_window_mask==1)
assert(not opens.b_mask and not opens.c_mask and not opens.b_window_mask and not opens.c_window_mask)
local x,y,z=fly(6,6,6);assert(x==7 and y==14 and z==21)
assert(mask_reads==27,'one common support mask, not three')
for _,name in ipairs({'a','b','c'}) do assert(reads[name]==28,'each V keeps all finite checks and E query') end
x,y,z=fly(3,3,3);assert(x==70 and y==140 and z==210,'inclusive window boundary')
assert(mask_reads==54,'next query must recheck window support')
local raw=apply(binding,'raw_sample')
local v,rx,ry,rz=raw(3,3,3);assert(v==70 and rx==x and ry==y and rz==z)
assert(mask_reads==81,'raw query checks support once too')
for _,name in ipairs({'aw','bw','cw'}) do assert(reads[name]==57,'raw keeps each E and potential query') end
assert(opens.a_mask==2 and opens.a_window_mask==2,'sharing must stay within one load')
unknown=true;assert(not pcall(fly,3,3,3));assert(not pcall(raw,6,6,6));unknown=false
for _,name in ipairs({'b','c'}) do nonfinite=name;assert(not pcall(fly,6,6,6)) end
for _,name in ipairs({'bw','cw'}) do nonfinite=name;assert(not pcall(raw,3,3,3)) end
nonfinite=nil
assert(not pcall(fly,0,0,0),'outside support remains failure')
-- Different routes must check their own mask and cannot borrow a window box.
binding.response_terms[2].refinement_windows[1].active_box_mm={{4,5},{4,5},{4,5}}
local mixed=apply(binding);local before=mask_reads
x,y,z=mixed(3,3,3);assert(x==34 and y==68 and z==102)
assert(mask_reads-before==81,'window/base/window each require their own support')
unknown=true;assert(not pcall(mixed,3,3,3))
print('SHARED_MASK_QUERY_PASS')
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/"fixture.lua"
            source.write_text(fixture, encoding="utf-8")
            completed = subprocess.run([str(lua), str(source), str(adapter)], cwd=REPO_ROOT, capture_output=True,
                                       text=True, timeout=10, check=True)
            self.assertIn("SHARED_MASK_QUERY_PASS", completed.stdout)

    def test_existing_cli_compiles_sampling_and_rejects_partial_options(self):
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding"
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            samples, request, output = (directory/name for name in ("samples.csv", "request.lua", "fields.csv"))
            samples.write_text("name,x_mm,y_mm,z_mm\npoint,1,1,2\n", encoding="utf-8")
            argv = ["static_field_binding", "--binding", "direct.json", "--compare-binding", "combo.json",
                    "--samples", str(samples), "--sampling-request", str(request),
                    "--comparison-output", str(output)]
            with patch("sys.argv", argv), patch(module+".load_binding", side_effect=self.fields()) as loader:
                with contextlib.redirect_stdout(io.StringIO()):
                    binding_main()
                self.assertEqual(loader.call_count, 2)
            self.assertIn("response_terms", request.read_text(encoding="utf-8"))
            self.assertFalse(output.exists())  # Compilation cannot query fields or produce measured output.
            with patch("sys.argv", argv[:5]), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    binding_main()
                self.assertEqual(raised.exception.code, 2)

    def fields(self):
        base = {"sources": {"scalar_pa": "direct", "valid_pa": "mask"},
                "grid": {"origin_mm": [0, 0, 0], "pitch_mm": [.25, .125, .5]},
                "ideal_sheet_projection": []}
        def window(name):
            return dict(copy.deepcopy(base), name=name,
                        active_box_mm=[[.9, 1.1], [.9, 1.1], [1.9, 2.1]],
                        sources={"scalar_pa": name, "valid_pa": "mask"})
        direct = dict(copy.deepcopy(base), refinement_windows=[window("direct_window"), window("ignored")])
        combined = copy.deepcopy(base)
        combined["response_terms"] = [
            dict(coefficient=coefficient, binding=dict(copy.deepcopy(base),
                sources={"scalar_pa": name, "valid_pa": "mask"},
                refinement_windows=[window(name+"_window"), window("ignored")]))
            for name, coefficient in (("base", -1), ("s1", .5), ("s2", 1.5))]
        return direct, combined

    def test_sampling_request_rejects_invalid_caller_csv(self):
        direct, combined = self.fields()
        for text in ("name,x_mm,y_mm\na,1,2\n", "name,x_mm,y_mm,z_mm\n",
                     "name,x_mm,y_mm,z_mm\na,nan,1,2\n",
                     "name,x_mm,y_mm,z_mm\na,1,1,2\na,2,1,2\n",
                     'name,x_mm,y_mm,z_mm\n"a,b",1,1,2\n'):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as directory:
                samples = Path(directory)/"samples.csv"
                samples.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    compile_sampling_request(direct, combined, samples, Path(directory)/"fields.csv")

    def test_raw_sampling_matches_flight_routes_affine_weights_and_common_metrics(self):
        from common.simion.field_comparison import read_field_comparison_csv, compute_field_residual_metrics
        lua = Path(os.environ.get("ProgramFiles", "C:/Program Files"))/"SIMION-2020/lua.exe"
        if not lua.is_file():
            self.skipTest("standalone vendor Lua unavailable")
        sampler = REPO_ROOT/"projects/parallel_mirror_dual_stripe_mr_tof/simion/compare_static_fields_at_samples.lua"
        fixture = r'''
local assets={};local unknown=arg[3]=='unknown'
for name,value in pairs({direct=4.5,base=1,s1=2,s2=3,direct_window=9,
 base_window=2,s1_window=4,s2_window=6,ignored=100,mask=1}) do
 local pa={symmetry='3dplanar',nx=17,ny=17,nz=17,dx_mm=.25,dy_mm=.125,dz_mm=.5}
 function pa:potential() if name=='mask' then return unknown and 0 or 1 else return value end end
 function pa:potential_vc(x,y,z) return value+x+2*y+3*z end
 function pa:save() error('must not save') end
 assets[name]=pa
end
simion={pas={},early_access=function() end,experimental={}}
function simion.pas:open(path) return assert(assets[path]) end
function simion.experimental.field_array(t)
 return {efield=function(x,y,z) return t.V:potential()+x,2*y,3*z end}
end
function simion.experimental.make_efield_adjust(f) return f end
local request=assert(loadfile(arg[2]))()
local apply=assert(loadfile(request.adapter))()
if not unknown then
 local fly=apply(request.b);local raw=apply(request.b,'raw_sample')
 for _,point in ipairs(request.samples) do
  local ex,ey,ez=fly(unpack(point.position_mm));local v,rx,ry,rz=raw(unpack(point.position_mm))
  assert(ex==rx and ey==ry and ez==rz and v==v)
 end
end
local sampler=arg[1];arg={arg[2]};dofile(sampler)
'''
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            samples, output, request, source = (directory/name for name in
                                               ("samples.csv", "fields.csv", "request.lua", "fixture.lua"))
            samples.write_text("name,x_mm,y_mm,z_mm\nbase,1.5,1,2\nwindow,1,1,2\n", encoding="utf-8")
            request.write_text(compile_sampling_request(*self.fields(), samples, output), encoding="utf-8")
            source.write_text(fixture, encoding="utf-8")
            command = [str(lua), str(source), str(sampler), str(request)]
            completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, timeout=10, check=True)
            self.assertIn("STATIC_FIELD_SAMPLE_COMPARISON=PASS samples=2", completed.stdout)
            rows = read_field_comparison_csv(output, finite_columns=("potential_a_V", "potential_b_V"))
            self.assertEqual(rows[0].numeric["potential_a_V"], 38.5)
            self.assertEqual(rows[1].numeric["potential_a_V"], 41)
            self.assertEqual(compute_field_residual_metrics(rows)["delta_field_max_V_per_mm"], 0)
            self.assertEqual(compute_field_residual_metrics(rows)["delta_potential_max_abs_V"], 0)
            failed = subprocess.run([*command, "unknown"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("V_SUPPORT_UNKNOWN", failed.stderr)
            self.assertNotIn("STATIC_FIELD_SAMPLE_COMPARISON=PASS", failed.stdout)


class SealedExportSourcesTest(unittest.TestCase):
    def test_external_assets_require_complete_role_paths_and_sealed_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            filenames = {"voltage_authority": "frozen_input.json", "geometry_authority": "resolved_geometry.json",
                         "scalar_pa": "field_v.pa", "valid_pa": "field_valid.pa", "export_result": "result.json"}
            sources = {}
            for role, filename in filenames.items():
                folder = root / role
                folder.mkdir()
                target = folder / filename
                content = {"status": "success", "field_units": "V", "pitch_mm": [.25, .125, .25]} if role == "export_result" else {}
                target.write_text(json.dumps(content), encoding="utf-8")
                sources[role] = str(target)
            manifest = root / "run_manifest.json"
            manifest.write_text(json.dumps({"status": "success", "outputs": [], "inputs": {
                role: {"path": value, "bytes": Path(value).stat().st_size, "sha256": "sealed-not-rehashed"}
                for role, value in sources.items()}}), encoding="utf-8")
            result = _load_export(manifest, sources)
            self.assertEqual(result["sources"], sources)
            self.assertEqual(result["records"]["scalar_pa"]["sha256"], "sealed-not-rehashed")
            original_manifest = manifest.read_text(encoding="utf-8")
            external_manifest = root / "provider" / "run_manifest.json"
            external_manifest.parent.mkdir()
            external_manifest.write_text(original_manifest, encoding="utf-8")
            projection = json.loads(original_manifest)
            for role in ("scalar_pa", "valid_pa"):
                del projection["inputs"][role]
            projection["inputs"]["export_provider_manifest"] = {
                "path": str(external_manifest), "bytes": external_manifest.stat().st_size, "sha256": "provider-sealed"}
            manifest.write_text(json.dumps(projection), encoding="utf-8")
            descriptors = {**sources, **{role: {"path": str(Path(sources[role]).relative_to(root)),
                                               "manifest": str(external_manifest.relative_to(root))}
                                        for role in ("scalar_pa", "valid_pa")}}
            self.assertEqual(_load_export(manifest, descriptors)["sources"], sources)
            for spec in ({"path": sources["scalar_pa"]}, {**descriptors["scalar_pa"], "extra": 1},
                         {"path": sources["scalar_pa"], "manifest": None}):
                with self.subTest(spec=spec), self.assertRaisesRegex(ValueError, "descriptor requires"):
                    _load_export(manifest, {**descriptors, "scalar_pa": spec})
            unsealed_owner = root / "unsealed_manifest.json"
            unsealed_owner.write_text(original_manifest, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unique sealed record"):
                _load_export(manifest, {**descriptors, "scalar_pa": {
                    "path": sources["scalar_pa"], "manifest": str(unsealed_owner)}})
            bad_owner = json.loads(original_manifest)
            for failure in ("status", "unsealed_asset"):
                altered = copy.deepcopy(bad_owner)
                if failure == "status":
                    altered["status"] = "failed"
                else:
                    del altered["inputs"]["scalar_pa"]
                external_manifest.write_text(json.dumps(altered), encoding="utf-8")
                projection["inputs"]["export_provider_manifest"]["bytes"] = external_manifest.stat().st_size
                manifest.write_text(json.dumps(projection), encoding="utf-8")
                with self.subTest(failure=failure), self.assertRaises(ValueError):
                    _load_export(manifest, descriptors)
            external_manifest.write_text(original_manifest, encoding="utf-8")
            projection["inputs"]["export_provider_manifest"]["bytes"] = external_manifest.stat().st_size
            manifest.write_text(json.dumps(projection), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "five named export"):
                _load_export(manifest, {**descriptors, "scalar_pa": {
                    **descriptors["scalar_pa"], "path": sources["valid_pa"]}})
            manifest.write_text(original_manifest, encoding="utf-8")
            relative = {role: str(Path(value).relative_to(root)) for role, value in sources.items()}
            self.assertEqual(_load_export(manifest, relative)["sources"], sources)
            swapped = {**sources, "scalar_pa": sources["valid_pa"], "valid_pa": sources["scalar_pa"]}
            for invalid in ({k: v for k, v in sources.items() if k != "valid_pa"},
                            {**sources, "extra": sources["scalar_pa"]}, swapped,
                            {**sources, "scalar_pa": None}):
                with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "five named export"):
                    _load_export(manifest, invalid)
            unsealed = root / "unsealed" / "field_v.pa"
            unsealed.parent.mkdir()
            unsealed.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unique sealed record"):
                _load_export(manifest, {**sources, "scalar_pa": str(unsealed)})
            Path(sources["valid_pa"]).write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed size"):
                _load_export(manifest, sources)


class RefinementWindowTest(unittest.TestCase):
    def load_fixture(self, windows: object, *, mismatch: str = "", local_grid: dict | None = None,
                     external_sources: bool = False) -> dict:
        """Resolve small mocked sealed metadata; only collision-file existence uses disk."""
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding"
        assembly = {"accelerator_iob_origin_mm": [0, 0, 0], "detector": {"box": {}},
                    "accelerator_resolved_electrodes": {
                        "local_to_pa_translation_mm": [0, 0, 0],
                        "grounded_enclosure": {"outer_box_mm": {"z_min_mm": -1}},
                        "repeller": {"solid_box_mm": {"z_min_mm": 0}}, "rings": [],
                        "grid_supports": [{"component_electrode_id": 23,
                            "frame_outer_box_mm": {"z_min_mm": 1}, "ideal_sheet_mm": {
                                "x_min_mm": .3, "x_max_mm": 1.1,
                                "y_min_mm": .3, "y_max_mm": .7, "z_mm": 1.5}}]}}
        authority = {"assembly": assembly, "analyzer_electrode_voltages_v": [10]}
        geometry = {"detector": {"box": {}}}
        grid = {"status": "success", "field_units": "V", "origin_mm": [0, 0, 0],
                "dimensions": [9, 9, 9], "pitch_mm": [.25, .125, .5]}
        author = {"schema_version": 1, "role": "mrtof_static_comsol_field_binding",
                  "export_manifest": "base/run_manifest.json", "assembly_manifest": "assembly/run_manifest.json",
                  "collision_manifest": "collision/run_manifest.json", "refinement_windows": windows}
        local_authority, local_geometry = copy.deepcopy(authority), copy.deepcopy(geometry)
        if mismatch == "voltage":
            local_authority["analyzer_electrode_voltages_v"] = [11]
        if mismatch == "geometry":
            local_geometry["detector"]["box"] = {"changed": True}
        data = {"binding.json": author, "base/inputs/frozen_input.json": authority,
                "base/inputs/resolved_geometry.json": geometry, "base/inputs/result.json": grid,
                "fine/inputs/frozen_input.json": local_authority,
                "fine/inputs/resolved_geometry.json": local_geometry,
                "fine/inputs/result.json": local_grid if local_grid is not None else grid,
                "collision/inputs/plan.json": {"collision_mask": {"origin_mm": [0, 0, 0]}},
                "collision/inputs/candidate_resolved_geometry.json": geometry,
                "assembly/results/resolved_iob_pose.json": {"origins_mm": {
                    role: [0, 0, 0] for role in ("analyzer", "accelerator", "detector")}}}
        if external_sources:
            filenames = {"voltage_authority": "frozen_input.json", "geometry_authority": "resolved_geometry.json",
                         "scalar_pa": "field_v.pa", "valid_pa": "field_valid.pa", "export_result": "result.json"}
            for entry, source_root in [(author, "base"), *[(w, "fine") for w in windows]]:
                entry["export_sources"] = {role: f"../borrowed-{source_root}/{filename}"
                                           for role, filename in filenames.items()}
                for role in ("scalar_pa", "valid_pa"):
                    entry["export_sources"][role] = {"path": entry["export_sources"][role],
                                                     "manifest": "../provider/run_manifest.json"}
                for role in ("voltage_authority", "geometry_authority", "export_result"):
                    data[f"{source_root}/../borrowed-{source_root}/{filenames[role]}"] = data[f"{source_root}/inputs/{filenames[role]}"]
        with tempfile.TemporaryDirectory() as directory:
            pa = Path(directory) / "fixture.pa0"
            pa.write_bytes(b"fixture")
            data["assembly/results/gui_workbench_receipt.json"] = {"pa_dependencies": [
                {"role": role, "path": str(pa), "bytes": 7, "source": {"sha256": "fixture"}}
                for role in ("global_fallback", "accelerator", "detector")]}
            with patch(module + "._read", side_effect=lambda path: copy.deepcopy(data[path.as_posix()])), \
                    patch(module + "._record", return_value={"bytes": 7, "sha256": "fixture"}):
                return load_binding(Path("binding.json"))

    def window(self, name: str = "slow") -> dict:
        return {"name": name, "export_manifest": "fine/run_manifest.json",
                "active_box_mm": [[.5, 1], [.25, .5], [1, 2]]}

    def test_ordered_windows_resolve_shared_physics_and_inherited_records(self) -> None:
        binding = self.load_fixture([self.window("first"), self.window("second")])
        self.assertEqual([w["name"] for w in binding["refinement_windows"]], ["first", "second"])
        for window in binding["refinement_windows"]:
            self.assertEqual(window["active_box_mm"], [[.5, 1], [.25, .5], [1, 2]])
            self.assertEqual(window["grid"]["pitch_mm"], [.25, .125, .5])
            self.assertEqual(len(window["sources"]), 5)
            self.assertEqual(len(window["records"]), 5)
            self.assertEqual(window["ideal_sheet_projection"][0]["k"], 3)
        self.assertEqual(self.load_fixture([])["refinement_windows"], [])

    def test_window_physics_mismatch_is_rejected(self) -> None:
        for mismatch in ("voltage", "geometry"):
            with self.subTest(mismatch=mismatch), self.assertRaisesRegex(ValueError, "differs from base"):
                self.load_fixture([self.window()], mismatch=mismatch)

    def test_ordinary_and_window_external_sources_keep_physics_checks(self) -> None:
        binding = self.load_fixture([self.window()], external_sources=True)
        self.assertIn("borrowed-base", binding["sources"]["scalar_pa"])
        self.assertIn("borrowed-fine", binding["refinement_windows"][0]["sources"]["valid_pa"])
        with self.assertRaisesRegex(ValueError, "differs from base"):
            self.load_fixture([self.window()], external_sources=True, mismatch="geometry")

    def test_window_halo_and_author_format_are_strict(self) -> None:
        for axis in range(3):
            for endpoint in (0, 1):
                window = self.window()
                window["active_box_mm"][axis][endpoint] = (0 if endpoint == 0 else (8*[.25,.125,.5][axis]))
                with self.subTest(axis=axis, endpoint=endpoint), self.assertRaisesRegex(ValueError, "halo"):
                    self.load_fixture([window])
        bad_windows = [None, {}, "slow", [self.window(), self.window()],
                       [{**self.window(), "extra": 1}], [{**self.window(), "name": ""}],
                       [{**self.window(), "active_box_mm": [[.5, .5], [.25, .5], [1, 2]]}],
                       [{**self.window(), "active_box_mm": [[.5, float("nan")], [.25, .5], [1, 2]]}]]
        for windows in bad_windows:
            with self.subTest(windows=windows), self.assertRaises(ValueError):
                self.load_fixture(windows)

    def test_nonintersecting_sheet_does_not_require_local_z_alignment(self) -> None:
        # z=1.5 is not aligned at dz=.4, but the window's y range misses the OA sheet.
        grid = {"status": "success", "field_units": "V", "origin_mm": [0, 2, 0],
                "dimensions": [9, 9, 9], "pitch_mm": [.25, .125, .4]}
        window = self.window()
        window["active_box_mm"] = [[.5, 1], [2.25, 2.5], [.8, 1.2]]
        binding = self.load_fixture([window], local_grid=grid)
        self.assertEqual(binding["refinement_windows"][0]["ideal_sheet_projection"], [])
        grid["origin_mm"] = [0, 0, 0]
        window["active_box_mm"][1] = [.25, .5]
        with self.assertRaisesRegex(ValueError, "snapping is forbidden"):
            self.load_fixture([window], local_grid=grid)

    def test_vendor_lua_routes_inclusive_boxes_in_order_without_unknown_fallback(self) -> None:
        lua = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "SIMION-2020/lua.exe"
        if not lua.is_file():
            self.skipTest("standalone vendor Lua unavailable; no commercial execution")
        adapter = Path(__file__).resolve().parents[2] / "simion/scalar_field_adapter.lua"
        fixture = r'''
local calls={base=0,first=0,second=0};local unknown=false;local assets={}
for _,name in ipairs({'base','first','second'}) do
 local fine=name~='base'
 local pa={name=name,symmetry='3dplanar',nx=fine and 9 or 12,ny=fine and 9 or 12,nz=fine and 9 or 12,
  dx_mm=fine and .25 or 1,dy_mm=fine and .125 or 1,dz_mm=fine and .5 or 1}
 function pa:potential() return 2 end
 function pa:save() error('PA save forbidden') end
 local mask={symmetry=pa.symmetry,nx=pa.nx,ny=pa.ny,nz=pa.nz,dx_mm=pa.dx_mm,dy_mm=pa.dy_mm,dz_mm=pa.dz_mm}
 function mask:potential() return (name=='first' and unknown) and 0 or 1 end
 assets[name]=pa;assets[name..'_mask']=mask
end
simion={early_access=function() end,pas={},experimental={}}
function simion.pas:open(path) return assert(assets[path]) end
function simion.experimental.field_array(t)
 assert(t.type=='V' and t.antimirror=='')
 return {efield=function(x,y,z)
  calls[t.V.name]=calls[t.V.name]+1
  if t.V.name=='base' then return 1,2,3 elseif t.V.name=='first' then return 11,12,13 else return 21,22,23 end
 end}
end
function simion.experimental.make_efield_adjust(f) return f end
local function window(name,box)
 return {name=name,scalar_pa=name,valid_pa=name..'_mask',origin_mm={0,0,0},
  pitch_mm={.25,.125,.5},ideal_sheet_projection={},active_box_mm=box}
end
local first=window('first',{{.5,1},{.25,.5},{1,2}})
local second=window('second',{{.75,1.5},{.375,.75},{1.5,3}})
local binding={scalar_pa='base',valid_pa='base_mask',origin_mm={-4,-4,-4},pitch_mm={1,1,1},ideal_sheet_projection={}}
local apply=assert(loadfile(arg[1]))()
local plain=apply(binding);assert(plain(.5,.25,1)==1)
binding.refinement_windows={};assert(apply(binding)(.5,.25,1)==1)
binding.refinement_windows={first,second};local field=apply(binding)
local function check(f,x,y,z,expected)
 local ex,ey,ez=f(x,y,z);assert(ex==expected and ey==expected+1 and ez==expected+2)
end
check(field,.5,.25,1,11);check(field,1,.5,2,11) -- inclusive min/max corners
check(field,.875,.4375,1.75,11) -- ordered overlap
check(field,1.25,.625,2.5,21);check(field,1.8,.8,3.2,1)
binding.refinement_windows={second,first};check(apply(binding),.875,.4375,1.75,21)
local baseBefore,secondBefore=calls.base,calls.second
unknown=true
local ok,err=pcall(field,.875,.4375,1.75)
assert(not ok and tostring(err):find('V_SUPPORT_UNKNOWN',1,true))
assert(calls.base==baseBefore and calls.second==secondBefore,'unknown window fell back')
unknown=false;first.active_box_mm[1][1]=.1
ok,err=pcall(apply,binding);assert(not ok and tostring(err):find('support halo',1,true))
print('ORDERED_LOCAL_FIELD_FIXTURE_PASS')
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "windows_fixture.lua"
            source.write_text(fixture, encoding="utf-8")
            completed = subprocess.run([str(lua), str(source), str(adapter)], cwd=REPO_ROOT,
                                       capture_output=True, text=True, timeout=10, check=True)
            self.assertIn("ORDERED_LOCAL_FIELD_FIXTURE_PASS", completed.stdout)

    def test_generated_scalar_transport_drives_native_window_routing(self) -> None:
        lua = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "SIMION-2020/lua.exe"
        if not lua.is_file():
            self.skipTest("standalone vendor Lua unavailable; no commercial execution")
        adapter = Path(__file__).resolve().parents[2] / "simion/scalar_field_adapter.lua"
        base = {"sources": {"scalar_pa": "base V.pa", "valid_pa": "base mask.pa"},
                "grid": {"origin_mm": [-4, -4, -4], "pitch_mm": [1, 1, 1]},
                "ideal_sheet_projection": []}
        first = {"name": "first", "sources": {"scalar_pa": "first V.pa", "valid_pa": "first mask.pa"},
                 "grid": {"origin_mm": [0, 0, 0], "pitch_mm": [.25, .125, .5]},
                 "ideal_sheet_projection": [], "active_box_mm": [[.5, 1], [.25, .5], [1, 2]]}
        second = {"name": "second", "sources": {"scalar_pa": "second V.pa", "valid_pa": "second mask.pa"},
                  "grid": {"origin_mm": [-.125, -.25, -.5], "pitch_mm": [.125, .25, .25]},
                  "ideal_sheet_projection": [], "active_box_mm": [[.75, 1.5], [.375, .75], [1.5, 3]]}
        # These are the actual production serializers, not a handwritten Lua binding.
        generated = "local plain_binding={" + _scalar_field_lua_fields(base) + "}\n"
        generated += "local ordered_binding={" + _scalar_field_lua_fields(base) + ",refinement_windows=" \
            + _scalar_refinement_windows_lua([first, second]) + "}\n"
        generated += "local reversed_binding={" + _scalar_field_lua_fields(base) + ",refinement_windows=" \
            + _scalar_refinement_windows_lua([second, first]) + "}\n"
        fixture = r'''
local unknown=false;local calls={base=0,first=0,second=0};local assets={}
local specs={base={12,12,12,1,1,1},first={9,9,9,.25,.125,.5},second={17,9,17,.125,.25,.25}}
for name,s in pairs(specs) do
 local pa={name=name,symmetry='3dplanar',nx=s[1],ny=s[2],nz=s[3],dx_mm=s[4],dy_mm=s[5],dz_mm=s[6]}
 function pa:potential() return 2 end
 function pa:save() error('PA save forbidden') end
 local mask={symmetry=pa.symmetry,nx=pa.nx,ny=pa.ny,nz=pa.nz,dx_mm=pa.dx_mm,dy_mm=pa.dy_mm,dz_mm=pa.dz_mm}
 function mask:potential() return (name=='first' and unknown) and 0 or 1 end
 assets[name..' V.pa']=pa;assets[name..' mask.pa']=mask
end
simion={early_access=function() end,pas={},experimental={}}
function simion.pas:open(path) return assert(assets[path],'transported PA path differs') end
function simion.experimental.field_array(t)
 assert(t.type=='V' and t.antimirror=='')
 return {efield=function(x,y,z)
  calls[t.V.name]=calls[t.V.name]+1
  -- Different origins/pitches survive transport; FA receives physical local mm.
  if t.V.name=='base' then assert(x>=4 and y>=4 and z>=4);return 1,2,3
  elseif t.V.name=='first' then assert(x>=.5 and x<=1 and y>=.25 and y<=.5 and z>=1 and z<=2);return 11,12,13
  else assert(x>=.875 and x<=1.625 and y>=.625 and y<=1 and z>=2 and z<=3.5);return 21,22,23 end
 end}
end
function simion.experimental.make_efield_adjust(f) return f end
local apply=assert(loadfile(arg[1]))()
'''
        fixture += generated
        fixture += r'''
assert(ordered_binding.refinement_windows[1].name=='first' and ordered_binding.refinement_windows[2].name=='second')
assert(ordered_binding.refinement_windows[1].pitch_mm[2]==.125 and ordered_binding.refinement_windows[2].pitch_mm[2]==.25)
local function check(f,x,y,z,value)
 local ex,ey,ez=f(x,y,z);assert(ex==value and ey==value+1 and ez==value+2)
end
check(apply(plain_binding),.875,.4375,1.75,1)
local field=apply(ordered_binding)
check(field,.5,.25,1,11);check(field,1,.5,2,11) -- inclusive first-window corners
check(field,.875,.4375,1.75,11) -- overlap goes to the first serialized window
check(field,1.5,.75,3,21) -- inclusive second-window maximum with its own halo
check(field,1.8,.8,3.2,1)
check(apply(reversed_binding),.875,.4375,1.75,21)
local beforeBase,beforeSecond=calls.base,calls.second
unknown=true
local ok,err=pcall(field,.875,.4375,1.75)
assert(not ok and tostring(err):find('V_SUPPORT_UNKNOWN',1,true))
assert(calls.base==beforeBase and calls.second==beforeSecond,'serialized window silently fell back')
print('GENERATED_SCALAR_TRANSPORT_FIXTURE_PASS')
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "generated_transport_fixture.lua"
            source.write_text(fixture, encoding="utf-8")
            completed = subprocess.run([str(lua), str(source), str(adapter)], cwd=REPO_ROOT,
                                       capture_output=True, text=True, timeout=10, check=True)
            self.assertIn("GENERATED_SCALAR_TRANSPORT_FIXTURE_PASS", completed.stdout)


class VoltageResponseBindingTest(unittest.TestCase):
    def fixture(self):
        values = [0.] * 20
        values[10:14] = [-27., -27., 54., 54.]
        values[15:17] = [190., -190.]
        base = {"geometry": {"shape": "fixed"}, "authority": {"analyzer_electrode_voltages_v": values, "assembly": {"oa": "fixed"}},
                "grid": {"origin_mm": [0, 0, 0], "pitch_mm": [.25, .125, .25], "dimensions": [9, 9, 9]},
                "sources": {"scalar_pa": "base", "valid_pa": "mask"},
                "records": {"valid_pa": {"bytes": 10, "sha256": "valid"}},
                "ideal_sheet_projection": [], "fixture_family": {"mesh": "mesh3", "solver": "fixed"}}
        base["refinement_windows"] = [dict(copy.deepcopy(base), name="slow", active_box_mm=[[.5, 1]] * 3)]
        samples = {}
        for name, ids in (("s1", (10, 11)), ("s2", (12, 13))):
            sample = copy.deepcopy(base)
            for electrode in ids:
                sample["authority"]["analyzer_electrode_voltages_v"][electrode] += .1
            samples[name] = sample
        author = dict(copy.deepcopy(base), baseline_binding="base.json",
                      voltage_responses={name: {"binding": name} for name in samples},
                      target_stripe_voltages_v=[-26.95, 54.2])
        return author, samples

    def resolve(self, author, samples):
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis"
        with patch(module + ".static_field_binding.load_binding", side_effect=lambda path, **kw: copy.deepcopy(samples[str(path)])), \
                patch(module + ".downstream_fixed_grid_workpoint._static_binding_problem",
                      side_effect=lambda component, *args: component["fixture_family"]):
            return _resolve_voltage_responses(author, Path("combined.json"))

    def test_actual_s_voltages_derive_weights_and_target_authority(self):
        author, samples = self.fixture()
        resolved = self.resolve(author, samples)
        self.assertEqual(resolved["representation"], "exploratory_affine_s_responses")
        self.assertFalse(resolved["gui_field_queries_equivalent"])
        self.assertAlmostEqual(resolved["response_weight_l1_norm"], 4.)
        self.assertEqual([term["binding_path"] for term in resolved["response_terms"]], ["base.json", "s1", "s2"])
        for term, expected in zip(resolved["response_terms"], (-1.5, .5, 2.), strict=True):
            self.assertAlmostEqual(term["coefficient"], expected)
        self.assertEqual(resolved["authority"]["analyzer_electrode_voltages_v"][10:14], [-26.95]*2 + [54.2]*2)
        self.assertEqual(resolved["response_terms"][0]["binding"]["authority"]["analyzer_electrode_voltages_v"][10], -27.)

    def ps_fixture(self):
        author, samples = self.fixture()
        author["schema_version"] = 2
        author.pop("target_stripe_voltages_v")
        author["target_ps_voltages_v"] = dict(s1=-26.95, s2=54.2, p1=190., p2=-190.)
        return author, samples

    def test_ps_s_only_keeps_undeclared_p_voltages(self):
        author, samples = self.ps_fixture()
        resolved = self.resolve(author, samples)
        self.assertEqual(resolved["representation"], "exploratory_affine_ps_responses")
        self.assertEqual(resolved["authority"]["analyzer_electrode_voltages_v"][15:17], [190., -190.])
        author["target_ps_voltages_v"]["p2"] = -189.
        with self.assertRaisesRegex(ValueError, "without a declared response"):
            self.resolve(author, samples)

    def cross_anchor_fixture(self):
        author, samples = self.ps_fixture()
        old = copy.deepcopy(samples["s1"])
        old["authority"] = copy.deepcopy(author["authority"])
        samples["old.json"] = old
        # A new, directly solved P/S point is not the old response origin.
        author["authority"]["analyzer_electrode_voltages_v"][10:14] = [-28., -28., 55., 55.]
        author["authority"]["analyzer_electrode_voltages_v"][15:17] = [189., -189.]
        author["target_ps_voltages_v"] = dict(s1=-27.95, s2=55.2, p1=189., p2=-189.)
        for spec in author["voltage_responses"].values():
            spec["baseline_binding"] = "old.json"
        return author, samples

    def test_cross_anchor_uses_real_origin_steps_and_deduplicates_shared_origin(self):
        author, samples = self.cross_anchor_fixture()
        original = copy.deepcopy(samples)
        resolved = self.resolve(copy.deepcopy(author), samples)
        terms = {term["binding_path"]: term for term in resolved["response_terms"]}
        self.assertEqual(set(terms), {"base.json", "old.json", "s1", "s2"})
        for name, expected in (("base.json", 1), ("old.json", -2.5), ("s1", .5), ("s2", 2)):
            self.assertAlmostEqual(terms[name]["coefficient"], expected)
        self.assertAlmostEqual(resolved["response_weight_l1_norm"], 6.)
        # A linear field with contributions from all four axes: new + increments.
        values = {"base.json": 90., "old.json": 100., "s1": 103., "s2": 105.}
        self.assertAlmostEqual(sum(t["coefficient"] * values[n] for n, t in terms.items()), 101.5)
        self.assertEqual(resolved["authority"]["analyzer_electrode_voltages_v"][10:17],
                         [-27.95, -27.95, 55.2, 55.2, 0., 189., -189.])
        self.assertEqual(terms["old.json"]["binding"]["authority"], original["old.json"]["authority"])
        self.assertEqual(samples, original)

    def test_cross_anchor_rejects_origin_or_probe_fixed_inputs_family_and_support(self):
        for role in ("old.json", "s1"):
            for change in ("mirror", "oa", "mesh", "grid", "mask", "window_mask", "window"):
                author, samples = self.cross_anchor_fixture()
                sample = samples[role]
                if change == "mirror":
                    sample["authority"]["analyzer_electrode_voltages_v"][0] += 1
                elif change == "oa":
                    sample["authority"]["assembly"]["oa"] = "different"
                elif change == "mesh":
                    sample["fixture_family"]["mesh"] = "different"
                elif change == "grid":
                    sample["grid"]["origin_mm"][0] += .125
                elif change in ("mask", "window_mask"):
                    level = sample if change == "mask" else sample["refinement_windows"][0]
                    level["records"]["valid_pa"]["sha256"] = "different"
                else:
                    sample["refinement_windows"][0]["active_box_mm"][0][0] += .125
                with self.subTest(role=role, change=change), self.assertRaises(ValueError):
                    self.resolve(author, samples)
        author, samples = self.cross_anchor_fixture()
        samples["s1"]["authority"]["analyzer_electrode_voltages_v"][16] += .1
        with self.assertRaisesRegex(ValueError, "exactly its named PS axis"):
            self.resolve(author, samples)

    def test_explicit_same_anchor_matches_default_and_zero_terms_cancel(self):
        author, samples = self.ps_fixture()
        original = self.resolve(copy.deepcopy(author), samples)
        samples["base.json"] = copy.deepcopy(original["response_terms"][0]["binding"])
        explicit = copy.deepcopy(author)
        for spec in explicit["voltage_responses"].values():
            spec["baseline_binding"] = "base.json"
        self.assertEqual(self.resolve(explicit, samples)["response_terms"], original["response_terms"])
        author, samples = self.cross_anchor_fixture()
        author["target_ps_voltages_v"].update(s1=-28., s2=55.)
        resolved = self.resolve(author, samples)
        self.assertEqual([(t["binding_path"], t["coefficient"]) for t in resolved["response_terms"]],
                         [("base.json", 1.), ("s1", 0.)])
        author, samples = self.cross_anchor_fixture()
        samples["s1"]["authority"]["analyzer_electrode_voltages_v"][10:12] = [-26.75] * 2
        samples["s2"]["authority"]["analyzer_electrode_voltages_v"][12:14] = [54.25] * 2
        author["target_ps_voltages_v"].update(s1=-27.875, s2=54.875)  # Exactly cancel.
        resolved = self.resolve(author, samples)
        self.assertNotIn("old.json", [t["binding_path"] for t in resolved["response_terms"]])

    def test_cross_anchor_rejects_more_than_five_actual_terms(self):
        author, samples = self.cross_anchor_fixture()
        for axis, index in (("p1", 15), ("p2", 16)):
            origin = copy.deepcopy(samples["old.json"])
            origin["authority"]["analyzer_electrode_voltages_v"][index] += 10
            probe = copy.deepcopy(origin)
            probe["authority"]["analyzer_electrode_voltages_v"][index] += 1
            samples[axis+"_origin"] = origin
            samples[axis] = probe
            author["voltage_responses"][axis] = dict(binding=axis, baseline_binding=axis+"_origin")
            author["target_ps_voltages_v"][axis] += .5
        with self.assertRaisesRegex(ValueError, "more than five"):
            self.resolve(author, samples)

    def test_cross_anchor_zero_increment_serializer_keeps_existing_consumer_contract(self):
        lua = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "SIMION-2020/lua.exe"
        if not lua.is_file():
            self.skipTest("standalone vendor Lua unavailable")
        author, samples = self.cross_anchor_fixture()
        author["target_ps_voltages_v"].update(s1=-28., s2=55.)
        resolved = self.resolve(author, samples)
        for term in resolved["response_terms"]:
            term["binding"]["refinement_windows"] = []
        generated = "local binding={" + _scalar_field_lua_fields(resolved) + "}\n"
        fixture = r'''
local opens=0
local pa={symmetry='3dplanar',nx=9,ny=9,nz=9,dx_mm=.25,dy_mm=.125,dz_mm=.25}
function pa:potential() return 2 end
function pa:potential_vc() return 2 end
local mask={symmetry=pa.symmetry,nx=9,ny=9,nz=9,dx_mm=.25,dy_mm=.125,dz_mm=.25}
function mask:potential() return 1 end
simion={pas={},experimental={},early_access=function() end}
function simion.pas:open(path) opens=opens+1;if path=='base' then return pa end;assert(path=='mask');return mask end
function simion.experimental.field_array(t) return {efield=function() return 2,4,6 end} end
function simion.experimental.make_efield_adjust(f) return f end
local apply=assert(loadfile(arg[1]))()
'''+generated+r'''
assert(#binding.response_terms==2 and binding.response_terms[2].coefficient==0)
local field=apply(binding)
local ex,ey,ez=field(.5,.375,.5);assert(ex==2 and ey==4 and ez==6)
assert(opens==2,'only nonzero term scalar and mask open')
print('CROSS_ANCHOR_ZERO_SERIALIZER_PASS')
'''
        adapter = REPO_ROOT / "projects/parallel_mirror_dual_stripe_mr_tof/simion/scalar_field_adapter.lua"
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.lua"
            source.write_text(fixture, encoding="utf-8")
            result = subprocess.run([str(lua), str(source), str(adapter)], cwd=REPO_ROOT,
                                    capture_output=True, text=True, timeout=10, check=True)
            self.assertIn("CROSS_ANCHOR_ZERO_SERIALIZER_PASS", result.stdout)

    def test_response_origin_spec_rejects_empty_nested_or_unknown_fields(self):
        for value in (None, "", 4):
            author, samples = self.ps_fixture()
            author["voltage_responses"]["s1"]["baseline_binding"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.resolve(author, samples)
        author, samples = self.ps_fixture()
        author["voltage_responses"]["s1"]["unknown"] = "old.json"
        with self.assertRaises(ValueError):
            self.resolve(author, samples)

    def test_ps_p1_response_synchronizes_authority_and_rejects_wrong_axis_or_support(self):
        author, samples = self.ps_fixture()
        samples["p1"] = copy.deepcopy(author)
        samples["p1"]["authority"]["analyzer_electrode_voltages_v"][15] += 2.
        author["voltage_responses"]["p1"] = {"binding": "p1"}
        author["target_ps_voltages_v"]["p1"] = 191.
        resolved = self.resolve(copy.deepcopy(author), samples)
        self.assertEqual(resolved["authority"]["analyzer_electrode_voltages_v"],
                         [0.]*10 + [-26.95]*2 + [54.2]*2 + [0., 191., -190., 0., 0., 0.])
        self.assertAlmostEqual(resolved["response_terms"][-1]["coefficient"], .5)
        for change in ("mirror", "p2", "mask", "window"):
            bad = copy.deepcopy(samples)
            if change in ("mirror", "p2"):
                bad["p1"]["authority"]["analyzer_electrode_voltages_v"][0 if change == "mirror" else 16] += 1.
            elif change == "mask":
                bad["p1"]["records"]["valid_pa"]["sha256"] = "changed"
            else:
                bad["p1"]["refinement_windows"][0]["active_box_mm"][0][0] = .6
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.resolve(copy.deepcopy(author), bad)

    def test_ps_version_two_loader_does_not_accept_legacy_target_format(self):
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding"
        descriptor = dict(schema_version=2, role="mrtof_static_comsol_field_binding",
                          baseline_binding="base.json", voltage_responses={"s1": {"binding": "s1.json"}},
                          target_stripe_voltages_v=[-27., 54.])
        with patch(module + "._read", return_value=descriptor):
            with self.assertRaisesRegex(ValueError, "complete PS target format"):
                load_binding(Path("author.json"))

    def test_response_geometry_content_matches_despite_different_sealed_json_sha(self):
        author, samples = self.fixture()
        author["fixture_family"]["geometry_sha256"] = "baseline-raw-json"
        for sample in samples.values():
            sample["fixture_family"]["geometry_sha256"] = "provider-raw-json"
        resolved = self.resolve(copy.deepcopy(author), samples)
        self.assertEqual(resolved["response_family"]["geometry_sha256"], "baseline-raw-json")
        samples["s2"]["geometry"]["shape"] = "changed"
        with self.assertRaisesRegex(ValueError, "geometry/mesh"):
            self.resolve(author, samples)

    def test_response_stop_values_can_differ_without_erasing_actual_sources(self):
        author, samples = self.ps_fixture()
        numerics = dict(study_stol=1e-9, stationary_stol=1e-9, linear_solver="CG",
                        loweramg="on", potential_order="2")
        author["fixture_family"]["solver_numerics"] = copy.deepcopy(numerics)
        for sample in samples.values():
            sample["fixture_family"]["solver_numerics"] = copy.deepcopy(numerics)
        samples["s2"]["fixture_family"]["solver_numerics"].update(
            study_stol=1e-11, stationary_stol=1e-11)
        original = copy.deepcopy(samples)
        resolved = self.resolve(copy.deepcopy(author), samples)
        self.assertEqual(samples, original)
        self.assertEqual(resolved["response_family"]["solver_numerics"], numerics)
        self.assertEqual(resolved["response_terms"][2]["binding"]["fixture_family"]["solver_numerics"]["study_stol"], 1e-11)
        for key, changed in (("linear_solver", "GMRES"), ("loweramg", "off"),
                             ("potential_order", "1"), ("rhob", 200)):
            bad = copy.deepcopy(samples)
            bad["s2"]["fixture_family"]["solver_numerics"][key] = changed
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "solver/boundary family"):
                self.resolve(copy.deepcopy(author), bad)

    def test_candidate_response_checks_provider_family_geometry_support_and_full_authority(self):
        author, samples = self.fixture()
        binding = self.resolve(author, samples)
        source = copy.deepcopy(binding["response_terms"][0]["binding"])
        source["fixture_family"]["geometry_sha256"] = "different-serialization"
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis"

        def check(candidate, provider_source):
            with patch(module + ".corridor_field_provider.derive_candidate_authority", return_value=(
                    binding["authority"], {})), \
                    patch(module + ".static_field_binding.load_binding", return_value=provider_source), \
                    patch(module + ".downstream_fixed_grid_workpoint._static_binding_problem",
                          side_effect=lambda component, *args: component["fixture_family"]):
                validate_response_candidate(candidate, {"source_binding_path": "source.json"})

        check(binding, source)
        binding["response_family"]["solver_numerics"] = {
            "study_stol": 1e-9, "stationary_stol": 1e-9, "linear_solver": "CG"}
        source["fixture_family"]["solver_numerics"] = {
            "study_stol": 1e-11, "stationary_stol": 1e-11, "linear_solver": "CG"}
        check(binding, source)
        source["fixture_family"]["solver_numerics"]["linear_solver"] = "GMRES"
        with self.assertRaisesRegex(ValueError, "scientific field family"):
            check(binding, source)
        source["fixture_family"]["solver_numerics"]["linear_solver"] = "CG"
        materialized = copy.deepcopy(binding)
        materialized["representation"] = "exploratory_materialized_affine_s_responses"
        materialized.pop("response_terms")
        check(materialized, source)
        materialized["representation"] = "exploratory_materialized_affine_ps_responses"
        check(materialized, source)
        for change in ("geometry", "mesh", "grid", "mask", "window", "authority"):
            candidate, provider_source = copy.deepcopy(binding), copy.deepcopy(source)
            if change == "geometry":
                provider_source["geometry"]["shape"] = "different"
            elif change == "mesh":
                provider_source["fixture_family"]["mesh"] = "different"
            elif change == "grid":
                provider_source["grid"]["pitch_mm"][0] = .5
            elif change == "mask":
                provider_source["records"]["valid_pa"]["sha256"] = "different"
            elif change == "window":
                provider_source["refinement_windows"][0]["active_box_mm"][0][0] = .75
            else:
                candidate["authority"]["analyzer_electrode_voltages_v"][15] += 1.
            with self.subTest(change=change), self.assertRaises(ValueError):
                check(candidate, provider_source)

    def test_response_candidate_needs_scalar_authority_not_unused_model_metadata(self):
        author, samples = self.ps_fixture()
        binding = self.resolve(author, samples)
        source = copy.deepcopy(binding["response_terms"][0]["binding"])
        request = dict(schema_version=1, role="mrtof_same_mesh_field_provider_request",
                       source_binding_path="source.json", candidate_voltages_v=author["target_ps_voltages_v"])
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis"
        # No source_field_manifest, model_path, dataset_readback, or solve budget.
        with patch(module + ".static_field_binding.load_binding", return_value=source), \
                patch(module + ".corridor_field_provider.compile_request",
                      side_effect=AssertionError("Must not prepare a new field solve")), \
                patch(module + ".downstream_fixed_grid_workpoint._static_binding_problem",
                      side_effect=lambda component, *args: component["fixture_family"]):
            validate_response_candidate(binding, request)
            for changes in (dict(role="wrong"), dict(schema_version=2),
                            dict(candidate_voltages_v=dict(s1=0, s2=0, p1=0)),
                            dict(candidate_voltages_v={**request["candidate_voltages_v"], "s1": float("nan")})):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    validate_response_candidate(binding, {**request, **changes})
            bad = copy.deepcopy(binding)
            bad["authority"]["analyzer_electrode_voltages_v"][0] += 1
            with self.assertRaisesRegex(ValueError, "complete candidate"):
                validate_response_candidate(bad, request)
            # Mirror requests cannot silently bypass their reference contract.
            with self.assertRaises((KeyError, ValueError)):
                validate_response_candidate(binding, {**request, "mirror_voltage_variation_path": "variation.json"})

    def test_response_family_fixed_voltages_grid_windows_masks_must_match(self):
        for change in ("p", "mirror", "oa", "mesh", "solver", "grid", "window", "mask", "window_mask", "zero_step"):
            author, samples = self.fixture()
            sample = samples["s1"]
            if change in ("p", "mirror"):
                sample["authority"]["analyzer_electrode_voltages_v"][15 if change == "p" else 0] += 1
            elif change == "oa":
                sample["authority"]["assembly"]["oa"] = "changed"
            elif change in ("mesh", "solver"):
                sample["fixture_family"][change] = "changed"
            elif change == "grid":
                sample["grid"]["pitch_mm"][0] = .125
            elif change == "window":
                sample["refinement_windows"][0]["active_box_mm"][0][0] = .6
            elif change in ("mask", "window_mask"):
                target = sample if change == "mask" else sample["refinement_windows"][0]
                target["records"]["valid_pa"]["sha256"] = "changed"
            else:
                sample["authority"]["analyzer_electrode_voltages_v"][10:12] = [-27., -27.]
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.resolve(author, samples)

    def test_nested_and_self_bindings_are_rejected_before_asset_loading(self):
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding"
        author = {"schema_version": 1, "role": "mrtof_static_comsol_field_binding",
                  "baseline_binding": "self.json", "voltage_responses": {}}
        with patch(module + "._read", return_value=author):
            with self.assertRaisesRegex(ValueError, "nested"):
                load_binding(Path("self.json"))

    def test_existing_binding_cli_loader_resolves_baseline_before_responses(self):
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding"
        descriptor = {"schema_version": 1, "role": "mrtof_static_comsol_field_binding",
                      "baseline_binding": "base.json", "voltage_responses": {},
                      "target_stripe_voltages_v": [-27., 54.]}
        with patch(module + "._read", return_value=descriptor), \
                patch(module + ".load_binding", side_effect=lambda path, **kwargs: {"plain": str(path)}), \
                patch(module + "._resolve_voltage_responses", side_effect=lambda resolved, path: resolved):
            # Retain the actual implementation while intercepting its recursive plain load.
            resolved = load_binding(Path("combined.json"))
        self.assertEqual(resolved["plain"], "base.json")
        self.assertEqual(resolved["baseline_binding"], "base.json")

    def test_generated_response_transport_uses_native_mocked_queries_without_saving(self):
        lua = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "SIMION-2020/lua.exe"
        if not lua.is_file():
            self.skipTest("standalone vendor Lua unavailable")
        adapter = Path(__file__).resolve().parents[2] / "simion/scalar_field_adapter.lua"
        base = {"sources": {"scalar_pa": "base", "valid_pa": "mask"},
                "grid": {"origin_mm": [0, 0, 0], "pitch_mm": [1, 1, 1]}, "ideal_sheet_projection": []}
        binding = copy.deepcopy(base)
        binding["response_terms"] = [dict(coefficient=weight, binding={**copy.deepcopy(base),
            "sources": {"scalar_pa": name, "valid_pa": "mask"}}) for name, weight in
            (("base", -1.5), ("s1", .5), ("s2", 2.))]
        for term in binding["response_terms"]:
            name = term["binding"]["sources"]["scalar_pa"]
            term["binding"]["refinement_windows"] = [dict(copy.deepcopy(base), name="slow",
                active_box_mm=[[1.5, 2.5]] * 3,
                sources={"scalar_pa": name+"_window", "valid_pa": "mask"})]
        generated = "local binding={" + _scalar_field_lua_fields(binding) + "}\n"
        four = copy.deepcopy(binding)
        p1 = copy.deepcopy(four["response_terms"][1])
        p1["coefficient"] = .25
        p1["binding"]["sources"]["scalar_pa"] = "p1"
        p1["binding"]["refinement_windows"][0]["sources"]["scalar_pa"] = "p1_window"
        four["response_terms"].append(p1)
        generated += "local four={" + _scalar_field_lua_fields(four) + "}\n"
        fixture = r'''
local unknown=false;local assets={}
for i,name in ipairs({'base','s1','s2','base_window','s1_window','s2_window','mask','p1','p1_window'}) do
 local pa={symmetry='3dplanar',nx=9,ny=9,nz=9,dx_mm=1,dy_mm=1,dz_mm=1}
 function pa:potential() if name=='mask' then return unknown and 0 or 1 else return i end end
 function pa:potential_vc() return self:potential() end
 function pa:save() error('no save') end
 assets[name]=pa
end
simion={pas={},early_access=function() end,experimental={}}
function simion.pas:open(path) return assert(assets[path]) end
function simion.experimental.field_array(t)
 return {efield=function() local v=t.V:potential();return v,2*v,3*v end}
end
function simion.experimental.make_efield_adjust(f) return f end
local apply=assert(loadfile(arg[1]))()
'''+generated+r'''
local f=apply(binding);local ex,ey,ez=f(3,3,3)
assert(ex==5.5 and ey==11 and ez==16.5)
local wx,wy,wz=f(2,2,2);assert(wx==8.5 and wy==17 and wz==25.5)
local ps=apply(four);local px,py,pz=ps(3,3,3)
assert(px==7.5 and py==15 and pz==22.5)
local qx,qy,qz=ps(2,2,2);assert(qx==10.75 and qy==21.5 and qz==32.25)
local raw=apply(four,'raw_sample');local v,rx,ry,rz=raw(3,3,3)
assert(v==7.5 and rx==px and ry==py and rz==pz)
unknown=true;local ok,err=pcall(f,3,3,3)
assert(not ok and tostring(err):find('V_SUPPORT_UNKNOWN',1,true))
local pok,perr=pcall(ps,3,3,3)
assert(not pok and tostring(perr):find('V_SUPPORT_UNKNOWN',1,true))
print('AFFINE_RESPONSE_FIXTURE_PASS')
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "response.lua"
            source.write_text(fixture, encoding="utf-8")
            completed = subprocess.run([str(lua), str(source), str(adapter)], cwd=REPO_ROOT, capture_output=True,
                                       text=True, timeout=10, check=True)
            self.assertIn("AFFINE_RESPONSE_FIXTURE_PASS", completed.stdout)


class MaterializedResponseBindingTest(unittest.TestCase):
    def test_existing_binding_cli_writes_composition_plan_and_rejects_partial_options(self):
        with tempfile.TemporaryDirectory() as directory:
            binding, source, run, _ = self.fixture(Path(directory))
            output = run / "inputs/composition_plan.json"
            arguments = ["binding", "--binding", str(source), "--composition-plan", str(output),
                         "--composition-output-directory", str(run / "results")]
            with patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding.load_binding", return_value=binding), \
                    patch("sys.argv", arguments), contextlib.redirect_stdout(io.StringIO()):
                binding_main()
            self.assertEqual(json.loads(output.read_text())["role"], "mrtof_fixed_scalar_composition_plan")
            with patch("sys.argv", arguments[:-2]), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    binding_main()

    def fixture(self, root, *, ps=False):
        from common.simion.operating_pa_cache import file_content_identity
        author, samples = VoltageResponseBindingTest().fixture()
        binding = VoltageResponseBindingTest().resolve(author, samples)
        if ps:
            binding["representation"] = "exploratory_affine_ps_responses"
            term = copy.deepcopy(binding["response_terms"][0])
            term.update(binding_path="p1.json", coefficient=.25)
            binding["response_terms"].append(term)
            binding["response_terms"][0]["coefficient"] -= .25
            binding["authority"]["analyzer_electrode_voltages_v"][15] = 191.
            binding["response_weight_l1_norm"] = 4.5
        for index, term in enumerate(binding["response_terms"]):
            for level_index, level in enumerate([term["binding"], *term["binding"].get("refinement_windows", [])]):
                path = root / f"source-{index}-{level_index}.pa"
                path.write_bytes(b"scalar-V")
                level["sources"]["scalar_pa"] = str(path)
                level["records"]["scalar_pa"] = file_content_identity(path)
        source = root / "response.json"
        source.write_text(json.dumps({"role": "mrtof_static_comsol_field_binding"}), encoding="utf-8")
        run = root / "run"
        (run / "inputs").mkdir(parents=True)
        outputs = run / "results"
        outputs.mkdir()
        plan = compile_composition_plan(binding, source, outputs)
        return binding, source, run, plan

    def publish_fixture(self, run, plan):
        from common.contracts.write_run_manifest import file_record
        plan_path = run / "inputs/composition_plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        files = [plan_path]
        for command in plan["commands"]:
            output = Path(command["argv"][2])
            output.write_bytes(b"composed")
            files.append(output)
        manifest = run / "run_manifest.json"
        manifest.write_text(json.dumps({"status": "success", "outputs": [file_record(p) for p in files]}))
        return manifest

    def test_plan_uses_public_identity_and_exact_affine_coefficients_without_pa_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            binding, source, run, plan = self.fixture(Path(directory))
            self.assertEqual(plan["operating_pa_identity"]["role"], "simion_standalone_operating_pa_group")
            self.assertEqual(len(plan["commands"]), 2)
            command = plan["commands"][0]
            coefficients = [float(entry.rsplit(",", 1)[1]) for entry in command["argv"][3:]]
            self.assertEqual(coefficients, [-2.5, .5, 2.])
            self.assertEqual(plan["authority"], binding["authority"])
            self.assertEqual(plan["response_weight_l1_norm"], 4.)
            with patch("common.simion.operating_pa_cache.file_sha256", return_value="A" * 64) as digest:
                compile_composition_plan(binding, source, run / "results")
            self.assertTrue(all(Path(call.args[0]).suffix != ".pa" for call in digest.call_args_list))
            protected = source.parent / "field_v.pa"
            protected.write_bytes(b"scalar-V")
            binding["response_terms"][0]["binding"]["sources"]["scalar_pa"] = str(protected)
            with self.assertRaisesRegex(ValueError, "overwrite"):
                compile_composition_plan(binding, source, protected.parent)

    def test_four_term_plan_and_sealed_ps_load_preserve_authority_and_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            binding, source, run, plan = self.fixture(Path(directory), ps=True)
            self.assertEqual([float(x.rsplit(',', 1)[1]) for x in plan["commands"][0]["argv"][3:]],
                             [-2.75, .5, 2., .25])
            self.assertEqual([x["coordinate"] for x in plan["operating_pa_identity"]["members"][0]["responses"]],
                             ["whole_point_A_correction_scale", "whole_point_B_scale", "whole_point_C_scale", "whole_point_D_scale"])
            manifest = self.publish_fixture(run, plan)
            descriptor = {"response_binding": str(source), "materialization_manifest": str(manifest)}
            module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding"
            with patch(module + ".load_binding", return_value=binding):
                result = _load_materialized_response(descriptor)
            self.assertEqual(result["representation"], "exploratory_materialized_affine_ps_responses")
            self.assertEqual(result["authority"], binding["authority"])
            self.assertEqual(result["response_family"], binding["response_family"])
            self.assertEqual(len(result["composition_sources"]), 4)
            self.assertNotIn("response_terms", result)
            self.assertEqual(result["records"]["valid_pa"], binding["records"]["valid_pa"])
            self.assertEqual(result["refinement_windows"][0]["active_box_mm"], binding["refinement_windows"][0]["active_box_mm"])
            for change in ("coefficient", "authority"):
                bad = copy.deepcopy(binding)
                if change == "coefficient":
                    bad["response_terms"][3]["coefficient"] += .1
                else:
                    bad["authority"]["analyzer_electrode_voltages_v"][15] += .1
                with self.subTest(change=change), patch(module + ".load_binding", return_value=bad):
                    with self.assertRaises(ValueError):
                        _load_materialized_response(descriptor)

    def test_public_composer_four_input_loop_runs_in_native_lua_with_tiny_mock_pas(self):
        lua = Path(os.environ.get("ProgramFiles", "C:/Program Files"))/"SIMION-2020/lua.exe"
        if not lua.is_file():
            self.skipTest("standalone vendor Lua unavailable")
        composer = REPO_ROOT/"common/simion/compose_standalone_pa.lua"
        fixture = r'''
local root,composer=arg[1],arg[2]
local values={['a.pa']=2,['b.pa']=4,['c.pa']=8,['d.pa']=16}
local function pa(value)
 local p={nx=3,ny=3,nz=3,symmetry='3dplanar',dx_mm=1,dy_mm=1,dz_mm=1,potential_type='electric',v=value,e=true}
 function p:size() end
 function p:copy(other) self.v,self.e=other.v,other.e end
 function p:close() end
 function p:points() local done=false;return function() if not done then done=true;return 1,1,1 end end end
 function p:potential() return self.v end
 function p:potential_add(x,y,z,v) self.v=self.v+v end
 function p:save(path)
  assert(self.v==18.5 and self.e and self.refined and not self.refinable)
  local f=assert(io.open(path,'wb'));f:write('tiny_mock_output');f:close()
 end
 return p
end
simion={pas={}}
function simion.pas:close() end
function simion.pas:open(path) if path==nil then return pa(0) end;return pa(assert(values[path:match('[^/\\]+$')])) end
arg={root..'/a.pa',root..'/out.pa',root..'/a.pa,-2.75',root..'/b.pa,0.5',root..'/c.pa,2',root..'/d.pa,0.25'}
assert(loadfile(composer))()
print('FOUR_TERM_PUBLIC_COMPOSER_PASS')
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("a.pa", "b.pa", "c.pa", "d.pa"):
                (root/name).write_bytes(b"tiny_mock_input")
            script = root/"fixture.lua"
            script.write_text(fixture, encoding="utf-8")
            result = subprocess.run([str(lua), str(script), str(root), str(composer)], cwd=REPO_ROOT,
                                    capture_output=True, text=True, timeout=10, check=True)
            self.assertIn("FOUR_TERM_PUBLIC_COMPOSER_PASS", result.stdout)
            self.assertIn("responses=4", result.stdout)

    def test_successful_materialization_loads_one_v_and_preserves_support_and_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            binding, source, run, plan = self.fixture(Path(directory))
            manifest = self.publish_fixture(run, plan)
            original = copy.deepcopy(binding)
            descriptor = {"response_binding": str(source), "materialization_manifest": str(manifest)}
            with patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding.load_binding", return_value=binding):
                result = _load_materialized_response(descriptor)
            self.assertEqual(binding, original)
            self.assertNotIn("response_terms", result)
            self.assertEqual(result["authority"], original["authority"])
            self.assertEqual(result["response_weight_l1_norm"], 4.)
            self.assertFalse(result["gui_field_queries_equivalent"])
            for actual, prior in zip([result, *result["refinement_windows"]],
                                     [original, *original["refinement_windows"]], strict=True):
                for key in ("grid", "ideal_sheet_projection"):
                    self.assertEqual(actual[key], prior[key])
                self.assertEqual(actual["sources"]["valid_pa"], prior["sources"]["valid_pa"])
                self.assertEqual(actual["records"]["valid_pa"], prior["records"]["valid_pa"])
            self.assertEqual(result["refinement_windows"][0]["active_box_mm"], original["refinement_windows"][0]["active_box_mm"])
            self.assertNotIn("response_terms", _scalar_field_lua_fields(result))

    def test_materialization_rejects_unsealed_mismatched_or_wrong_size_output(self):
        for problem in ("failed", "source", "authority", "size", "command", "support", "coefficient"):
            with self.subTest(problem=problem), tempfile.TemporaryDirectory() as directory:
                binding, source, run, plan = self.fixture(Path(directory))
                if problem == "authority":
                    plan["authority"] = copy.deepcopy(plan["authority"])
                    plan["authority"]["analyzer_electrode_voltages_v"][0] += 1
                if problem == "command":
                    plan["commands"][0]["argv"][-1] = "wrong.pa,1"
                if problem == "support":
                    plan["commands"][0]["support"]["valid_mask"]["sha256"] = "different"
                if problem == "coefficient":
                    plan["operating_pa_identity"]["members"][0]["responses"][0]["applied_voltage_delta_v"] += .1
                manifest = self.publish_fixture(run, plan)
                if problem == "failed":
                    data = json.loads(manifest.read_text()); data["status"] = "failed"
                    manifest.write_text(json.dumps(data))
                elif problem == "source":
                    source.write_text('{"changed": true}')
                elif problem == "size":
                    Path(plan["commands"][0]["argv"][2]).write_bytes(b"wrong-size")
                with patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding.load_binding", return_value=binding):
                    with self.assertRaises(ValueError):
                        _load_materialized_response({"response_binding": str(source), "materialization_manifest": str(manifest)})

    def test_sealed_materialization_keeps_generator_provenance_after_comment_only_change(self):
        with tempfile.TemporaryDirectory() as directory:
            binding, source, run, plan = self.fixture(Path(directory))
            plan["operating_pa_identity"]["synthesis"]["implementation_sha256"] = "A" * 64
            manifest = self.publish_fixture(run, plan)
            with patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding.load_binding", return_value=binding):
                result = _load_materialized_response({"response_binding": str(source), "materialization_manifest": str(manifest)})
            self.assertEqual(result["materialization_synthesis"]["implementation_sha256"], "A" * 64)
            self.assertEqual(result["materialization_synthesis"], plan["operating_pa_identity"]["synthesis"])
            self.assertEqual(result["authority"], binding["authority"])


class StaticFieldVoltageTest(unittest.TestCase):
    def test_anisotropic_sheet_projection_uses_each_axis_spacing(self) -> None:
        assembly = {"accelerator_iob_origin_mm": [0, 0, 0],
                    "accelerator_resolved_electrodes": {
                        "local_to_pa_translation_mm": [0, 0, 0],
                        "grid_supports": [{"component_electrode_id": 23, "ideal_sheet_mm": {
                            "x_min_mm": .3, "x_max_mm": 1.1,
                            "y_min_mm": .3, "y_max_mm": .7, "z_mm": 1.5}}]}}
        grid = {"origin_mm": [0, 0, 0], "pitch_mm": [.25, .125, .5],
                "dimensions": [9, 9, 9]}
        sheet, = ideal_sheet_projection(assembly, grid)
        self.assertEqual((sheet["i_min"], sheet["i_max"], sheet["j_min"], sheet["j_max"], sheet["k"]),
                         (2, 4, 3, 5, 3))
        assembly["accelerator_resolved_electrodes"]["grid_supports"][0]["ideal_sheet_mm"]["z_mm"] = 1.25
        with self.assertRaisesRegex(ValueError, "snapping is forbidden"):
            ideal_sheet_projection(assembly, grid)

    def test_export_binding_rejects_missing_scalar_and_invalid_pitch(self) -> None:
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding"
        bad = [None, .25, [], [.25], [.25, .25], [.25] * 4,
               [.25, 0, .25], [.25, -.125, .25], [.25, float("nan"), .25],
               [.25, float("inf"), .25], [.25, True, .25], [.25, ".125", .25]]
        assembly = {"accelerator_iob_origin_mm": [0, 0, 0],
                    "accelerator_resolved_electrodes": {
                        "local_to_pa_translation_mm": [0, 0, 0], "grid_supports": []}}
        for pitch in bad:
            grid = {"status": "success", "field_units": "V", "origin_mm": [0, 0, 0],
                    "dimensions": [9, 9, 9]}
            if pitch is not None:
                grid["pitch_mm"] = pitch
            with self.subTest(pitch=pitch):
                with self.assertRaisesRegex(ValueError, "pitch_mm"):
                    ideal_sheet_projection(assembly, grid)
                author = {"schema_version": 1, "role": "mrtof_static_comsol_field_binding",
                          "export_manifest": "export/run_manifest.json"}
                with patch(module + "._read", side_effect=[author, {}, {}, grid]), \
                        patch(module + "._record", return_value={}):
                    with self.assertRaisesRegex(ValueError, "pitch_mm"):
                        load_binding(Path("binding.json"))

    def test_lua_anisotropic_headers_and_axis_support_fail_closed(self) -> None:
        lua = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "SIMION-2020/lua.exe"
        if not lua.is_file():
            self.skipTest("standalone vendor Lua unavailable; no commercial execution")
        adapter = Path(__file__).resolve().parents[2] / "simion/scalar_field_adapter.lua"
        fixture = r'''
local calls={};local unknown=false;local nonfinite=false;local faCalls=0;local opens=0
local pa={symmetry='3dplanar',nx=9,ny=9,nz=9,dx_mm=.25,dy_mm=.125,dz_mm=.5}
function pa:potential(i,j,k)
 if nonfinite then return 0/0 end
 return 3*i*self.dx_mm-7*j*self.dy_mm+11*k*self.dz_mm+2
end
function pa:save() error('PA save forbidden') end
local mask={symmetry='3dplanar',nx=9,ny=9,nz=9,dx_mm=.25,dy_mm=.125,dz_mm=.5}
function mask:potential(i,j,k)
 calls[i..':'..j..':'..k]=true
 return (unknown and i==1 and j==2 and k==3) and 0 or 1
end
simion={early_access=function() end,pas={},experimental={}}
function simion.pas:open(path)
 opens=opens+1;if path=='V' then return pa else assert(path=='mask');return mask end
end
function simion.experimental.field_array(t)
 assert(t.V==pa and t.type=='V' and t.antimirror=='')
 return {efield=function(x,y,z)
  faCalls=faCalls+1
  assert(math.abs(x-.575)<1e-14 and math.abs(y-.425)<1e-14 and math.abs(z-2.25)<1e-14)
  return -3,7,-11
 end}
end
function simion.experimental.make_efield_adjust(f) return f end
local apply=assert(loadfile(arg[1]))()
local binding={scalar_pa='V',valid_pa='mask',pitch_mm={.25,.125,.5},origin_mm={10,20,30},
 ideal_sheet_projection={}}
local field=apply(binding)
local ex,ey,ez=field(10.575,20.425,32.25);assert(ex==-3 and ey==7 and ez==-11)
local n=0;for _ in pairs(calls) do n=n+1 end;assert(n==64)
for k=3,6 do for j=2,5 do for i=1,4 do assert(calls[i..':'..j..':'..k]) end end end
local function fails(f,text)
 local ok,err=pcall(f);assert(not ok and (not text or tostring(err):find(text,1,true)),tostring(err))
end
for a,key in ipairs({'dx_mm','dy_mm','dz_mm'}) do
 local original=pa[key];pa[key]=original*2
 fails(function() apply(binding) end,'scalar pitch differs');pa[key]=original
 original=mask[key];mask[key]=original*2
 fails(function() apply(binding) end,'mask pitch differs');mask[key]=original
end
local before=opens
for _,pitch in ipairs({.25,{}, {.25}, {.25,.125}, {.25,.125,.5,1},
 {.25,0,.5},{.25,-.125,.5},{.25,0/0,.5},{.25,math.huge,.5},{.25,true,.5},{.25,'.125',.5}}) do
 binding.pitch_mm=pitch;fails(function() apply(binding) end)
end
binding.pitch_mm=nil;fails(function() apply(binding) end,'pitch_mm')
assert(opens==before,'invalid pitch must fail before PA open')
binding.pitch_mm={.25,.125,.5}
local count=faCalls
fails(function() field(10.575,20.0625,32.25) end,'V_SUPPORT_BOX_OUTSIDE')
unknown=true;fails(function() field(10.575,20.425,32.25) end,'V_SUPPORT_UNKNOWN');unknown=false
nonfinite=true;fails(function() field(10.575,20.425,32.25) end,'V_SUPPORT_NONFINITE')
assert(faCalls==count,'invalid support must not reach field_array')
print('ANISOTROPIC_ADAPTER_FIXTURE_PASS')
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "anisotropic_fixture.lua"
            source.write_text(fixture, encoding="utf-8")
            completed = subprocess.run([str(lua), str(source), str(adapter)], cwd=REPO_ROOT,
                                       capture_output=True, text=True, timeout=10, check=True)
            self.assertIn("ANISOTROPIC_ADAPTER_FIXTURE_PASS", completed.stdout)

    def test_load_binding_consumes_current_three_axis_export(self) -> None:
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding"
        assembly = {"accelerator_iob_origin_mm": [0, 0, 0], "detector": {"box": {}},
                    "accelerator_resolved_electrodes": {
                        "local_to_pa_translation_mm": [0, 0, 0],
                        "grounded_enclosure": {"outer_box_mm": {"z_min_mm": -1}},
                        "repeller": {"solid_box_mm": {"z_min_mm": 0}},
                        "grid_supports": [{"component_electrode_id": 23,
                            "frame_outer_box_mm": {"z_min_mm": 1}, "ideal_sheet_mm": {
                                "x_min_mm": .3, "x_max_mm": 1.1,
                                "y_min_mm": .3, "y_max_mm": .7, "z_mm": 1.5}}],
                        "rings": []}}
        authority = {"assembly": assembly}
        geometry = {"detector": {"box": {}}}
        author = {"schema_version": 1, "role": "mrtof_static_comsol_field_binding",
                  "export_manifest": "export/run_manifest.json",
                  "assembly_manifest": "assembly/run_manifest.json",
                  "collision_manifest": "collision/run_manifest.json"}
        pose = {"origins_mm": {role: [0, 0, 0] for role in ("analyzer", "accelerator", "detector")}}
        with tempfile.TemporaryDirectory() as directory:
            pa = Path(directory) / "fixture.pa0"
            pa.write_bytes(b"fixture")
            gui = {"pa_dependencies": [{"role": role, "path": str(pa), "bytes": 7,
                                        "source": {"sha256": "fixture"}}
                                       for role in ("global_fallback", "accelerator", "detector")]}
            for pitch in ([.25, .125, .5], [.25, .25, .25]):
                grid = {"status": "success", "field_units": "V", "origin_mm": [0, 0, 0],
                        "dimensions": [9, 9, 9], "pitch_mm": pitch}
                with self.subTest(pitch=pitch), patch(module + "._record", return_value={}), \
                        patch(module + "._read", side_effect=[copy.deepcopy(author), authority,
                            geometry, grid, pose, gui, {"collision_mask": {"origin_mm": [0, 0, 0]}}, geometry]):
                    binding = load_binding(Path("binding.json"))
                    self.assertEqual(binding["grid"]["pitch_mm"], pitch)
                    self.assertEqual(binding["ideal_sheet_projection"][0]["k"], int(1.5 / pitch[2]))
                    self.assertEqual(len(binding["instances"]), 4)

    def test_sheet_projection_uses_frozen_pose_and_clips_aperture(self) -> None:
        assembly = {"accelerator_iob_origin_mm": [0, -72.25, -6],
                    "accelerator_resolved_electrodes": {
                        "local_to_pa_translation_mm": [0, 17.25, 6],
                        "grid_supports": [{"component_electrode_id": i, "ideal_sheet_mm": {
                            "x_min_mm": -12.5, "x_max_mm": 12.5,
                            "y_min_mm": -13, "y_max_mm": 13, "z_mm": z}}
                            for i, z in ((23, 30), (24, 0))]}}
        grid = {"origin_mm": [-2.5, -147, -290], "pitch_mm": [.25, .25, .25],
                "dimensions": [21, 2441, 2321]}
        sheets = ideal_sheet_projection(assembly, grid)
        self.assertEqual([s["global_box_mm"] for s in sheets],
                         [[-12.5, 12.5, -68, -42, 30], [-12.5, 12.5, -68, -42, 0]])
        self.assertEqual([s["k"] for s in sheets], [1280, 1160])
        self.assertEqual([(s["i_min"], s["i_max"], s["j_min"], s["j_max"]) for s in sheets],
                         [(0, 20, 316, 420)] * 2)
        assembly["accelerator_resolved_electrodes"]["grid_supports"][0]["ideal_sheet_mm"]["z_mm"] += .01
        with self.assertRaisesRegex(ValueError, "snapping is forbidden"):
            ideal_sheet_projection(assembly, grid)

    def test_lua_sheet_marker_preserves_potential_and_skips_invalid_mask(self) -> None:
        lua = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "SIMION-2020/lua.exe"
        if not lua.is_file():
            self.skipTest("standalone vendor Lua unavailable; no commercial execution")
        adapter = Path(__file__).resolve().parents[2] / "simion/scalar_field_adapter.lua"
        fixture = r'''
local marks={};local potentialCalls=0
local pa={symmetry='3dplanar',nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1,debug_max_voltage=1000}
function pa:potential(i,j,k)
 potentialCalls=potentialCalls+1
 return i+10*j+100*k+(marks[i..':'..j..':'..k] and 1e-13 or 0)
end
function pa:electrode(i,j,k,value) assert(value==true);marks[i..':'..j..':'..k]=true end
function pa:save() error('PA save forbidden') end
local mask={symmetry='3dplanar',nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1}
function mask:potential(i,j,k) return (i==1 and j==1 and k==1) and 0 or 1 end
simion={early_access=function() end,pas={},experimental={}}
function simion.pas:open(path) if path=='V' then return pa else assert(path=='mask');return mask end end
function simion.experimental.field_array(t) assert(t.V==pa);return {efield=function() return 0,0,0 end} end
function simion.experimental.make_efield_adjust(f) return f end
local apply=assert(loadfile(arg[1]))()
apply{scalar_pa='V',valid_pa='mask',pitch_mm={1,1,1},origin_mm={0,0,0},
 ideal_sheet_projection={{i_min=0,i_max=2,j_min=0,j_max=2,k=1}}}
assert(not marks['1:1:1'],'invalid node marked')
local n=0;for _ in pairs(marks) do n=n+1 end;assert(n==8)
assert(potentialCalls==16,'raw potential must be read before/after eight markers')
print('SHEET_MARKER_FIXTURE_PASS')
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "marker_fixture.lua"
            source.write_text(fixture, encoding="utf-8")
            completed = subprocess.run([str(lua), str(source), str(adapter)],
                                       cwd=REPO_ROOT, capture_output=True, text=True, timeout=10, check=True)
            self.assertIn("SHEET_MARKER_FIXTURE_PASS", completed.stdout)

    def test_static_runner_has_no_capacity_warning_override(self) -> None:
        runner = Path(__file__).resolve().parents[2] / "simion" / "run_two_prism_trial.ps1"
        self.assertNotIn("CapacityThresholdAction", runner.read_text(encoding="utf-8"))

    def setUp(self) -> None:
        self.oa = [0.0, 10.0, 5.0, 0.0, 2.0]
        self.analyzer = [0.0] * 20
        self.analyzer[15:17] = [190.0, -190.0]
        def electrode(physical: int, local: int) -> dict:
            return {"component_electrode_id": physical, "local_pa_electrode_id": local}
        self.binding = {"authority": {
            "analyzer_electrode_voltages_v": self.analyzer[:],
            "assembly": {"accelerator_resolved_electrodes": {
                "grounded_enclosure": electrode(15, 1), "repeller": electrode(22, 2),
                "grid_supports": [electrode(23, 3), electrode(24, 4)],
                "rings": [electrode(26, 5)],
            }},
            "component_voltages_v": [
                {"component_namespace": "accelerator", "component_electrode_id": i,
                 "voltage_v": v} for i, v in zip([15, 22, 23, 24, 26], self.oa)
            ] + [{"component_namespace": "detector", "component_electrode_id": 25, "voltage_v": 0}],
        }}

    def test_exact_static_point_passes(self) -> None:
        validate_voltages(self.binding, self.analyzer, self.oa, pulse_requested=False)

    def test_pulse_is_not_a_static_field(self) -> None:
        with self.assertRaisesRegex(ValueError, "pulse"):
            validate_voltages(self.binding, self.analyzer, self.oa, pulse_requested=True)

    def test_prism_change_requires_new_field(self) -> None:
        changed = self.analyzer[:]
        changed[15] += 0.01
        with self.assertRaisesRegex(ValueError, "analyzer"):
            validate_voltages(self.binding, changed, self.oa, pulse_requested=False)

    def test_component_namespace_is_not_mr_id(self) -> None:
        changed = self.oa[:]
        changed[3] = 1.0
        with self.assertRaisesRegex(ValueError, "OA"):
            validate_voltages(self.binding, self.analyzer, changed, pulse_requested=False)

    def test_detector_voltage_is_checked(self) -> None:
        changed = copy.deepcopy(self.binding)
        changed["authority"]["component_voltages_v"][-1]["voltage_v"] = 1.0
        with self.assertRaisesRegex(ValueError, "detector"):
            validate_voltages(changed, self.analyzer, self.oa, pulse_requested=False)


if __name__ == "__main__":
    unittest.main()
