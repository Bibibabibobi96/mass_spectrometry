from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_fixed_grid_workpoint import (
    RESIDUAL_NAMES,
    UNKNOWN_NAMES,
    _trial,
    _static_field_problem,
    _static_binding_problem,
    _native_static_binding_problem,
    _sealed_native_trial_binding,
    _center_source_projection,
    _trajectory_physics_identity,
    assert_trial_matches_jacobian,
    audit,
    resolve_numerics,
    resolve_active_stripe_axes,
    solve_linearized_step,
)
from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)

RUNNER = Path(__file__).resolve().parents[2] / "analysis" / "run_downstream_fixed_grid_workpoint.ps1"


class DownstreamFixedGridWorkpointTests(unittest.TestCase):
    def test_trajectory_anchor_numeric_representation_only_is_canonical(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "contract.json"
            contract = {"downstream_fixed_grid_workpoint_profile": {},
                        "accelerator": {"focus_y_anchor": {"project_y_mm": -55}},
                        "field": "same", "collision": "same", "maximum_step_us": .004}

            def identity(value):
                path.write_text(json.dumps(value), encoding="utf-8")
                sha = file_sha256(path)
                return _trajectory_physics_identity({"inputs": {"trajectory_numerics_contract": {
                    "path": str(path), "bytes": path.stat().st_size, "sha256": sha}}}, sha)

            baseline = identity(contract)
            same = copy.deepcopy(contract)
            same["accelerator"]["focus_y_anchor"]["project_y_mm"] = -55.0
            self.assertEqual(baseline, identity(same))
            for field, value in (("field", "other"), ("collision", "other"), ("maximum_step_us", .008)):
                changed = copy.deepcopy(contract)
                changed[field] = value
                self.assertNotEqual(baseline, identity(changed))
            changed = copy.deepcopy(contract)
            changed["accelerator"]["focus_y_anchor"]["project_y_mm"] = -54.0
            self.assertNotEqual(baseline, identity(changed))

    def test_center_storage_projection_preserves_original_problem_without_pa_reads(self):
        import hashlib
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_static_field_binding import NativeAxisMaterializationTest
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import load_binding
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bank = NativeAxisMaterializationTest()
            provider, descriptor = bank.setup_bank(root, nested=True)
            full = load_binding(bank.base_path)
            contract = copy.deepcopy(bank.contract)
            view = dict(kind='x_symmetry_plane', stored_x_nodes=5)
            contract['simion']['numerical_profiles']['native_static_field']['consumer_view'] = view
            contract_path = root/'view_contract.json'; contract_path.write_text(json.dumps(contract))
            plan = provider.compile_request(dict(schema_version=1, role=provider.ROLE,
                source_binding_path=str(bank.base_path), source_field_manifest=full['manifest'],
                consumer_view_source_path=str(bank.base_path), numerical_contract_path=str(contract_path)))
            run = root/'view'; (run/'inputs').mkdir(parents=True); (run/'results').mkdir()
            (run/'inputs/numerical_contract.json').write_text(json.dumps(contract))
            provider.prepare_run(plan, run)
            cropped = provider.binding_spec(plan, run)
            thin = copy.deepcopy(full); thin['consumer_view'] = view
            for level, spec, label in zip([thin, *thin['refinement_windows']],
                    [cropped['parent'], *cropped['refinement_windows']], ['parent', *plan['window_labels']], strict=True):
                original = copy.deepcopy(level['grid'])
                level.update(grid=spec['grid'], manifest=spec['manifest'])
                level['sources'].update(numerical_plan=spec['numerical_plan_path'], scalar_pa=spec['pa_path'])
                if label != 'parent':
                    level.update(active_box_mm=spec['active_box_mm'])
                Path(plan['levels'][label]['consumer_view_receipt_path']).write_text(json.dumps(dict(
                    status='PASS', refine_after_crop=False, full_dimensions=original['dimensions'],
                    consumer_dimensions=level['grid']['dimensions'])))
            records = [dict(path=str(p.resolve()), bytes=p.stat().st_size,
                sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in run.rglob('*') if p.is_file()]
            (run/'run_manifest.json').write_text(json.dumps(dict(status='success', outputs=records)))
            mat = dict(analyzer_electrode_voltages_v=full['authority']['analyzer_electrode_voltages_v'],
                stripe_biases_v=[0., 0.], prism_voltages_v=[0., 0.],
                source_position_project_mm=[0., -55., 0.], source_direction_project=[0., 1., 0.])
            expected = _native_static_binding_problem(full, mat)
            self.assertNotEqual(expected, _native_static_binding_problem(thin, mat))
            # Historical heavy PA payloads can be retired; only sealed small provenance is consumed.
            for level in [descriptor['parent'], *descriptor['refinement_windows']]:
                Path(level['pa_path']).unlink()
                Path(level['surface_path']).unlink()
            self.assertEqual(expected, _native_static_binding_problem(thin, mat, canonical_consumer_layout=True))
            from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_fixed_grid_workpoint import assert_native_provider_storage_resume
            previous_request = dict(schema_version=1, role=provider.ROLE, candidate_voltages_v={'s1': 0.},
                source_binding_path=str(bank.base_path), source_field_manifest=full['manifest'],
                numerical_contract_path=str(bank.contract_path), response_basis_paths={})
            current_request = dict(previous_request, source_binding_path='sealed_view.json',
                source_field_manifest=thin['manifest'], numerical_contract_path=str(contract_path))
            with patch('projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_fixed_grid_workpoint.load_binding', return_value=thin):
                assert_native_provider_storage_resume(previous_request, current_request)
                for change in ('candidate_voltages_v', 'mirror_contract_path', 'response_basis_paths'):
                    bad = dict(current_request); bad[change] = {'extra': 1.}
                    with self.assertRaises(ValueError):
                        assert_native_provider_storage_resume(previous_request, bad)
                bad = copy.deepcopy(thin); bad['authority']['analyzer_electrode_voltages_v'][10] = 1.
                with patch('projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_fixed_grid_workpoint.load_binding', return_value=bad):
                    with self.assertRaisesRegex(ValueError, 'voltage anchor'):
                        assert_native_provider_storage_resume(previous_request, current_request)
            composed = copy.deepcopy(thin)
            composed_dir = root/'composed_metadata'; composed_dir.mkdir()
            composed_manifest = composed_dir/'run_manifest.json'
            current_levels = [composed, *composed['refinement_windows']]
            old_ids = [(x['manifest'], x['sources']['scalar_pa']) for x in current_levels]
            for index, level in enumerate(current_levels):
                old_plan = Path(level['sources']['numerical_plan'])
                value = json.loads(old_plan.read_text())
                value.pop('consumer_view_source'); value.pop('consumer_view_receipt_path')
                receipt = composed_dir/f'{index}_receipt.json'; receipt.write_text(json.dumps(dict(status='PASS')))
                value.update(source_solve_manifest=level['manifest'], source_solve_plan_path=str(old_plan),
                             materialization_receipt_path=str(receipt))
                if index:
                    parent_index = old_ids.index((value['parent_manifest'], value['parent_pa']))
                    value.update(parent_manifest=str(composed_manifest), parent_pa=str(composed_dir/f'{parent_index}.pa'))
                target = composed_dir/f'{index}_plan.json'; target.write_text(json.dumps(value))
                level.update(manifest=str(composed_manifest))
                level['sources'].update(numerical_plan=str(target), scalar_pa=str(composed_dir/f'{index}.pa'))
            paths = [*composed_dir.iterdir(), run/'inputs/numerical_contract.json']
            composed_manifest.write_text(json.dumps(dict(status='success', outputs=[dict(path=str(p.resolve()),
                bytes=p.stat().st_size, sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths])))
            self.assertEqual(expected, _native_static_binding_problem(composed, mat, canonical_consumer_layout=True))
            for key in ('source_position_project_mm', 'source_direction_project'):
                changed = copy.deepcopy(mat); changed[key][0] = .01
                with self.assertRaisesRegex(ValueError, 'actual source'):
                    _native_static_binding_problem(thin, changed, canonical_consumer_layout=True)
            for change in ('pitch', 'stopping', 'window'):
                bad = copy.deepcopy(thin)
                if change == 'pitch':
                    bad['grid']['pitch_mm'][0] *= 2
                elif change == 'stopping':
                    bad['native_solver_numerics']['convergence_v'] *= .1
                else:
                    bad['refinement_windows'][0]['active_box_mm'][1][0] += .01
                with self.assertRaises(ValueError):
                    _native_static_binding_problem(bad, mat, canonical_consumer_layout=True)
            bad = copy.deepcopy(thin); bad['instances'][1]['record']['sha256'] = 'f'*64
            self.assertNotEqual(expected, _native_static_binding_problem(bad, mat, canonical_consumer_layout=True))
            changed_plan = Path(thin['refinement_windows'][0]['sources']['numerical_plan'])
            value = json.loads(changed_plan.read_text())
            value.update(parent_manifest=thin['manifest'], parent_pa=thin['sources']['scalar_pa'])
            changed_plan.write_text(json.dumps(value))
            for record in records:
                if record['path'] == str(changed_plan.resolve()):
                    record.update(bytes=changed_plan.stat().st_size,
                                  sha256=hashlib.sha256(changed_plan.read_bytes()).hexdigest())
            (run/'run_manifest.json').write_text(json.dumps(dict(status='success', outputs=records)))
            with self.assertRaisesRegex(ValueError, 'parent boundary ancestry'):
                _native_static_binding_problem(thin, mat, canonical_consumer_layout=True)

    def test_sealed_native_history_validates_actual_multiwindow_ancestry(self):
        """Historical projection validates small identities, not retired PA bytes."""
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial import _collision_geometry_projection
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_fixed_grid_workpoint"
        cases = (([3, 3, 0], None), ([0], None), ([3, 3, 0], "unknown"),
                 ([3, 3, 0], "missing"), ([1, 3, 0], "self"), ([2, 1, 0], "cycle"),
                 ([3, 3, 0], "manifest"), ([3, 3, 0], "authority"), ([3, 3, 0], "outside"))
        for parents, invalid in cases:
            with self.subTest(parents=parents, invalid=invalid), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                documents = {}
                def path(name):
                    return str(root / name)
                def record(name):
                    return dict(path=path(name), bytes=100, sha256="a" * 64)
                authority = dict(analyzer_electrode_voltages_v=[0.] * 20)
                geometry = {key: [] for key in ("mirror_electrodes", "mirror_slot", "mirror_inner_shield_slot",
                    "mirror_ground_shields", "mirror_e_closures", "stripe_electrodes", "stripe_slot",
                    "central_ground_electrodes", "central_ground_slots", "prism_electrodes", "prism_ground_shields")}
                grid = dict(origin_mm=[0, -2, -2], pitch_mm=[.5, 1., 1.], dimensions=[5, 5, 5], symmetry="x")
                specs, levels, plans, all_records = [], [], [], []
                for index in range(len(parents) + 1):
                    prefix = str(index)
                    records = {name: record(prefix + "-" + name) for name in (
                        "scalar_pa", "surface", "voltage_authority", "geometry_authority", "numerical_plan")}
                    sources = {key: value["path"] for key, value in records.items()}
                    plan = dict(box_mm=[0, -2, -2, 2, 2, 2], pitch_mm=grid["pitch_mm"], dimensions=grid["dimensions"],
                                boundary_mode="x_mirror_five_faces" if index else "grounded_enclosure")
                    spec = dict(manifest=path("owner.json"), grid=grid,
                        **{key: sources[name] for name, key in (("scalar_pa", "pa_path"), ("surface", "surface_path"),
                          ("voltage_authority", "voltage_authority_path"), ("geometry_authority", "geometry_authority_path"),
                          ("numerical_plan", "numerical_plan_path"))})
                    numerics = dict(solver="SIMION2020", refine_stopping="installed_default", surface="fractional",
                                    boundary_mode=plan["boundary_mode"])
                    level = dict(manifest=spec["manifest"], grid=grid, sources=sources, records=records,
                                 authority=authority, geometry=geometry, native_solver_numerics=numerics)
                    if index:
                        spec.update(name="window_" + prefix, active_box_mm=[-1.5, -1, -1, 1.5, 1, 1],
                                    parent_manifest=path("owner.json"))
                        level.update(name=spec["name"], active_box_mm=spec["active_box_mm"])
                        plan.update(parent_manifest=spec["parent_manifest"], parent_pa=path(str(parents[index-1]) + "-scalar_pa"))
                    documents[Path(sources["voltage_authority"])] = copy.deepcopy(authority)
                    documents[Path(sources["geometry_authority"])] = geometry
                    documents[Path(sources["numerical_plan"])] = plan
                    all_records.extend(records.values())
                    specs.append(spec); levels.append(level); plans.append(plan)
                if invalid == "unknown":
                    plans[1]["parent_pa"] = path("undeclared.pa")
                elif invalid == "missing":
                    plans[1].pop("parent_pa")
                elif invalid == "manifest":
                    plans[1]["parent_manifest"] = path("wrong-manifest.json")
                elif invalid == "authority":
                    documents[Path(specs[1]["voltage_authority_path"])]["analyzer_electrode_voltages_v"][0] = 1.
                elif invalid == "outside":
                    plans[1]["box_mm"][3] = 3.
                instances = [dict(role=role, manifest=path("owner.json"), pa_path=specs[0]["pa_path"], origin_mm=[0, 0, 0])
                    for role in ("global_fallback", "native_corridor", "accelerator", "detector")]
                descriptor = dict(schema_version=1, role="mrtof_native_static_field_binding", parent=specs[0],
                                  refinement_windows=specs[1:], instances=instances)
                documents[Path(path("binding.json"))] = descriptor
                documents[Path(path("owner.json"))] = dict(status="success", outputs=all_records)
                documents[Path(path("config.json"))] = dict(provenance=dict(upstream_manifest_verification=dict(
                    geometry=dict(instances=[dict(i, record=levels[0]["records"]["scalar_pa"]) for i in instances]))))
                manifest = dict(inputs=dict(static_field_binding=record("binding.json")), run_config=record("config.json"))
                field = dict(levels[0], path=path("binding.json"), refinement_windows=levels[1:])
                mat = dict(collision_geometry=_collision_geometry_projection(geometry))
                with patch(module + "._load_object", side_effect=lambda p: documents[Path(p)]), patch(module + ".verify_record"):
                    if invalid:
                        with self.assertRaises((CandidateContractError, KeyError)):
                            _sealed_native_trial_binding(field, manifest, mat)
                    else:
                        actual = _sealed_native_trial_binding(field, manifest, mat)
                        self.assertEqual(len(actual["refinement_windows"]), len(parents))
                        self.assertEqual(actual["authority"], authority)

    def test_native_window_stopping_is_part_of_the_fixed_problem(self):
        numerics = dict(solver="SIMION2020", refine_stopping="contract_convergence",
                        convergence_v=1e-5, surface="fractional", boundary_mode="grounded_enclosure")
        binding = dict(mode="native_static_pa", authority={"analyzer_electrode_voltages_v": [0.] * 20},
                       grid={}, native_solver_numerics=numerics, instances=[],
                       refinement_windows=[dict(name="local", grid={}, active_box_mm=[[-1, 1]] * 3,
                           native_solver_numerics={**numerics, "boundary_mode": "x_mirror_five_faces"})])
        mat = dict(analyzer_electrode_voltages_v=[0.] * 20, stripe_biases_v=[0., 0.], prism_voltages_v=[0., 0.])
        first = _native_static_binding_problem(binding, mat)
        changed = copy.deepcopy(binding)
        changed["refinement_windows"][0]["native_solver_numerics"]["convergence_v"] = 1e-7
        self.assertNotEqual(first, _native_static_binding_problem(changed, mat))
        self.assertEqual(first["refinement_windows"][0]["solver_numerics"]["convergence_v"], 1e-5)

    def test_native_static_ps_float_record_uses_existing_compatibility_only(self):
        numerics = dict(solver="SIMION2020", refine_stopping="contract_convergence",
                        convergence_v=1e-5, surface="fractional", boundary_mode="grounded_enclosure")
        values = [0.] * 20
        values[15] = 189.86254642087434
        binding = dict(mode="native_static_pa", authority={"analyzer_electrode_voltages_v": values},
                       grid={}, native_solver_numerics=numerics, instances=[], refinement_windows=[])
        mat = dict(analyzer_electrode_voltages_v=list(values), stripe_biases_v=[0., 0.],
                   prism_voltages_v=[values[15], 0.])
        expected = _native_static_binding_problem(binding, mat)
        mat["analyzer_electrode_voltages_v"][15] = mat["prism_voltages_v"][0] = 189.862546420874
        self.assertEqual(_native_static_binding_problem(binding, mat), expected)
        for electrode, delta in ((15, 2e-9), (1, 3.41e-13)):
            with self.subTest(electrode=electrode):
                changed = copy.deepcopy(mat)
                changed["analyzer_electrode_voltages_v"][electrode] += delta
                with self.assertRaisesRegex(ValueError, "full voltages"):
                    _native_static_binding_problem(binding, changed)
        mat["prism_voltages_v"][0] += 2e-9
        with self.assertRaisesRegex(ValueError, "P/S voltages"):
            _native_static_binding_problem(binding, mat)

    def test_strict_saved_rerun_projects_actual_after_and_original_mesh(self):
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_fixed_grid_workpoint"
        values = [0.] * 20
        values[10:14] = [-27., -27., 55., 55.]
        values[15:17] = [191., -190.]
        authority, geometry = {"analyzer_electrode_voltages_v": values}, {"shape": "fixed"}
        grid = dict(origin_mm=[0, 0, 0], pitch_mm=[.25, .125, .25], dimensions=[3, 3, 3])
        binding = dict(export_manifest="projection/run_manifest.json", authority=authority, geometry=geometry,
                       grid=grid, records={"geometry_authority": {"sha256": "sealed"}},
                       assembly_manifest="assembly", collision_manifest="collision")
        receipt = dict(stripe_biases_v=values[10:14:2], prism_voltages_v=values[15:17],
                       analyzer_electrode_voltages_v=values)
        before = dict(active_mesh_tag="mesh6", iterative_solver="cg", study_stol=2e-8,
                      stationary_stol=2e-8, study_usestol=True)
        after = {**before, "study_stol": 3e-12, "stationary_stol": 3e-12}
        original = dict(role="s2", frozen_input="strict/inputs/s2_frozen_input.json",
                        resolved_geometry="strict/inputs/s2_resolved_geometry.json",
                        manifest="strict/inputs/s2_manifest.json", mph="original/comsol/field.mph",
                        parameter_name="s2", parameter_value_v=55., expected_voltages_v=values)
        export = dict(role="once_only_read_only_strict_s2_scalar_export", source_run="strict",
                      source_mph="strict/comsol/strict.mph", parameter_name="s2", parameter_voltage_v=55.,
                      solnum=1, active_mesh_tag="mesh6", solution_tag="sol1", dataset_tag="dset1")
        data = {
            "projection/run_manifest.json": {"inputs": {
                "source_export_manifest": {"path": "export/run_manifest.json"},
                "source_model_manifest": {"path": "strict/run_manifest.json"}}},
            "export/run_manifest.json": {}, "strict/run_manifest.json": {},
            "export/inputs/diagnostic_plan.json": export,
            "strict/inputs/diagnostic_plan.json": dict(source_runs=[original], strict_study_stol=3e-12,
                solution_number=1, potential_order="2", solution_tag="sol1", dataset_tag="dset1",
                strict_mph_name="strict.mph"),
            "strict/results/result.json": dict(status="success", field_solved=True,
                active_mesh_tag="mesh6", tetrahedra=7),
            original["frozen_input"]: copy.deepcopy(authority), original["resolved_geometry"]: copy.deepcopy(geometry),
            "strict/results/authority_after.json": dict(voltages_v=values, parameter_names=["s2"],
                parameter_values_v=55., solution="sol1", dataset="dset1", solnum=1),
            "strict/results/solver_before.json": before, "strict/results/solver_after.json": after,
            original["manifest"]: {}, "original/inputs/diagnostic_plan.json": {
                "source_mph": "mesh/original.mph", "potential_order": "2",
                "parameter": {"name": "s2", "electrode_ids": [13, 14]}},
            "export/inputs/grid_authority.json": {"role": "grid_origin_only"},
        }
        plan = dict(candidate_authority=authority, active_mesh_tag="mesh6", export_grid=grid,
                    source_mph_record={"path": "mesh/original.mph"}, expected_tetrahedra=7,
                    source_dataset={"solution_tag": "sol1", "dataset_tag": "dset1"})
        with patch(module + "._load_object", side_effect=lambda p: copy.deepcopy(data[p.as_posix()])), \
             patch(module + "._record", side_effect=lambda owner, p: {"path": str(p), "bytes": 7}), \
             patch(module + ".compile_request", return_value=plan):
            diagnostic = {}
            family = _static_binding_problem(binding, receipt, "binding.json", diagnostic)
            self.assertEqual(family["solver_numerics"], after)
            self.assertEqual(diagnostic["solver_before"], before)
            self.assertEqual(family["source_mesh_record"]["path"], "mesh/original.mph")
            self.assertEqual(Path(diagnostic["actual_model_record"]["path"]), Path("strict/comsol/strict.mph"))
            changes = [("strict/results/solver_after.json", "iterative_solver", "gmres"),
                       ("strict/results/solver_after.json", "stationary_stol", 9e-12),
                       ("strict/results/authority_after.json", "solnum", 2),
                       ("strict/results/authority_after.json", "voltages_v", [0.] * 20),
                       ("strict/inputs/s2_resolved_geometry.json", "shape", "changed"),
                       ("strict/inputs/diagnostic_plan.json", "potential_order", "1"),
                       ("original/inputs/diagnostic_plan.json", "source_mph", "different.mph"),
                       ("export/inputs/diagnostic_plan.json", "source_mph", "old.mph")]
            for path, key, wrong in changes:
                previous = data[path][key]
                data[path][key] = wrong
                with self.subTest(path=path, key=key), self.assertRaises(CandidateContractError):
                    _static_binding_problem(binding, receipt, "binding.json")
                data[path][key] = previous

    def test_parameterized_projection_uses_real_solve_without_claiming_operator_equivalence(self):
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_fixed_grid_workpoint"
        values = [0.] * 20
        values[10:14] = [-26.79, -26.79, 54.61, 54.61]
        values[15:17] = [191., -190.]
        authority = {"analyzer_electrode_voltages_v": values}
        geometry = {"shape": "fixed"}
        solver = {"active_mesh_tag": "mesh6", "iterative_solver": "cg", "stationary_stol": 1e-9}
        grid = {"origin_mm": [0, 0, 0], "pitch_mm": [.25, .125, .25], "dimensions": [3, 3, 3],
                "dataset_tag": "dset1", "solution_tag": "sol1"}
        binding = {"export_manifest": "projection/run_manifest.json", "authority": authority,
                   "geometry": geometry, "grid": grid, "records": {"geometry_authority": {"sha256": "sealed"}},
                   "assembly_manifest": "assembly", "collision_manifest": "collision"}
        receipt = {"stripe_biases_v": [values[10], values[12]], "prism_voltages_v": values[15:17],
                   "analyzer_electrode_voltages_v": values}
        data = {
            "projection/run_manifest.json": {"inputs": {
                "source_export_manifest": {"path": "export/run_manifest.json"},
                "parameter_source_manifest": {"path": "actual/run_manifest.json"}}},
            "export/run_manifest.json": {}, "actual/run_manifest.json": {},
            "export/inputs/diagnostic_plan.json": {"source_run": "actual", "source_mph": "actual/field.mph",
                "active_mesh_tag": "mesh6", "dataset_tag": "dset1", "solution_tag": "sol1", "solnum": 1,
                "parameter_name": "s1", "parameter_voltage_v": values[10]},
            "actual/inputs/diagnostic_plan.json": {"parameter": {"name": "s1", "electrode_ids": [11, 12]},
                "source_mph": "mesh/original.mph", "potential_order": "2", "active_mesh_tag": "mesh6",
                "dataset_tag": "dset1", "solution_tag": "sol1"},
            "actual/results/result.json": {"status": "success", "field_solved": True,
                "active_mesh_tag": "mesh6", "tetrahedra": 7},
            "actual/inputs/frozen_input.json": copy.deepcopy(authority), "actual/inputs/resolved_geometry.json": copy.deepcopy(geometry),
            "actual/results/parameter_readback.json": {"name": "s1", "unit": "V", "parametric_active": True,
                "actual_voltages_v": values, "changed_physical_ids": [11, 12]},
            "actual/results/solved_parameter_readback.json": {"names": ["s1"], "values_v": values[10], "solnum": 1},
            "actual/results/solver_before.json": solver, "actual/results/solver_after.json": copy.deepcopy(solver),
            "export/inputs/grid_authority.json": {"role": "grid_origin_only"},
        }
        plan = {"candidate_authority": authority, "active_mesh_tag": "mesh6", "export_grid": grid,
                "source_mph_record": {"path": "mesh/original.mph"}, "expected_tetrahedra": 7,
                "source_dataset": {"dataset_tag": "dset1", "solution_tag": "sol1"}}
        with patch(module + "._load_object", side_effect=lambda p: copy.deepcopy(data[p.as_posix()])), \
             patch(module + "._record", side_effect=lambda owner, p: {"path": str(p), "bytes": 7}), \
             patch(module + ".compile_request", return_value=plan) as compile_plan:
            diagnostic = {}
            family = _static_binding_problem(binding, receipt, "binding.json", diagnostic)
            self.assertEqual(family["source_mesh_record"]["path"], "mesh/original.mph")
            self.assertEqual(Path(diagnostic["actual_model_record"]["path"]), Path("actual/field.mph"))
            self.assertIn("not_established", diagnostic["qualification"])
            self.assertNotIn("qualification", family)
            compile_plan.assert_called_with({"role": "grid_origin_only"})
            changes = [("actual/results/solved_parameter_readback.json", "solnum", 2),
                       ("actual/results/parameter_readback.json", "unit", "J"),
                       ("actual/inputs/resolved_geometry.json", "shape", "changed"),
                       ("actual/results/solver_after.json", "stationary_stol", 1e-3),
                       ("actual/inputs/diagnostic_plan.json", "active_mesh_tag", "mesh5"),
                       ("export/inputs/diagnostic_plan.json", "parameter_voltage_v", -100.),
                       ("export/inputs/diagnostic_plan.json", "dataset_tag", "dset2"),
                       ("actual/results/parameter_readback.json", "actual_voltages_v", [0.] * 20)]
            for path, key, wrong in changes:
                original = data[path][key]
                data[path][key] = wrong
                with self.subTest(path=path, key=key), self.assertRaises(CandidateContractError):
                    _static_binding_problem(binding, receipt, "binding.json")
                data[path][key] = original
            changed_grid = copy.deepcopy(binding)
            changed_grid["grid"]["pitch_mm"] = [.5, .125, .25]
            with self.assertRaisesRegex(CandidateContractError, "grid differs"):
                _static_binding_problem(changed_grid, receipt, "binding.json")

            # Actual stage015 source shape: one parameter, a declared full PS
            # target, and Study-controlled stopping tightened after the solve.
            source_values = list(values)
            source_values[10:14] = [-27., -27., 54., 54.]
            source_values[15:17] = [190., -191.]
            data["actual/inputs/source_authority.json"] = {"analyzer_electrode_voltages_v": source_values}
            # Grid authority still names the original workpoint, not this
            # multi-PS saved solution; its mesh origin must remain unchanged.
            plan["candidate_authority"] = copy.deepcopy(data["actual/inputs/source_authority.json"])
            data["actual/inputs/candidate_affine_binding.json"] = {"target_ps_voltages_v": {
                "s1": values[10], "s2": values[12], "p1": values[15], "p2": values[16]}}
            solve = data["actual/inputs/diagnostic_plan.json"]
            solve["qualification_candidate"] = {"binding": "frozen_candidate"}
            solve["strict_stopping"] = dict(study_stol=1e-11, study_usestol_unchanged=True,
                stationary_control_unchanged="stat", stationary_stol_not_explicitly_set=True)
            data["actual/results/parameter_readback.json"]["changed_physical_ids"] = [11, 12, 13, 14, 16, 17]
            solver.update(study_stol=1e-9, study_usestol=True, stationary_control="stat")
            after = {**solver, "study_stol": 1e-11, "stationary_stol": 1e-11}
            data["actual/results/solver_after.json"] = after
            diagnostic = {}
            family = _static_binding_problem(binding, receipt, "binding.json", diagnostic)
            self.assertEqual(family["solver_numerics"], after)
            self.assertEqual(diagnostic["actual_solver_numerics"], after)
            self.assertEqual(family["source_mesh_record"], plan["source_mph_record"])
            self.assertEqual(plan["candidate_authority"], data["actual/inputs/source_authority.json"])
            self.assertEqual(data["actual/results/solver_before.json"]["study_stol"], 1e-9)
            after["stationary_stol"] = 1e-9
            self.assertEqual(_static_binding_problem(binding, receipt, "binding.json")["solver_numerics"], after)
            after["stationary_stol"] = 1e-11
            changes = [("actual/results/parameter_readback.json", "changed_physical_ids", [11, 12]),
                       ("actual/results/parameter_readback.json", "changed_physical_ids", [1, 11, 12, 13, 14, 16, 17]),
                       ("actual/inputs/source_authority.json", "analyzer_electrode_voltages_v", [1.] * 20),
                       ("actual/inputs/candidate_affine_binding.json", "target_ps_voltages_v",
                        {"s1": -99., "s2": values[12], "p1": values[15], "p2": values[16]}),
                       ("actual/results/solver_after.json", "iterative_solver", "gmres"),
                       ("actual/results/solver_after.json", "stationary_stol", 1e-10),
                       ("actual/results/solver_after.json", "study_usestol", False)]
            for path, key, wrong in changes:
                previous = data[path][key]
                data[path][key] = wrong
                with self.subTest(path=path, key=key), self.assertRaises(CandidateContractError):
                    _static_binding_problem(binding, receipt, "binding.json")
                data[path][key] = previous
            solve["strict_stopping"]["study_stol"] = 1e-8
            with self.assertRaisesRegex(CandidateContractError, "stopping"):
                _static_binding_problem(binding, receipt, "binding.json")
            solve["strict_stopping"]["study_stol"] = 1e-11
            del solve["qualification_candidate"]
            with self.assertRaises(CandidateContractError):
                _static_binding_problem(binding, receipt, "binding.json")

    @staticmethod
    def _declared_center():
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial import (
            _bunch_center_source_state, _source_release_record,
        )
        materialization = {
            "source_cohort_role": "controlled_diagnostic",
            "source_selection": {"role": "contiguous_frozen_source_diagnostic_selection"},
            "source_expected_particle_ids": [1, 2, 3],
            "source_cohort": {"frame_id": "test_frame", "clock_basis": "test_clock"},
            "source_clock_basis": "test_clock",
            "source_center_state": {"particle_id": 1, "position_workbench_mm": [0., -56., 32.],
                                    "direction_workbench": [0., 1., 0.], "kinetic_energy_ev": 5.3,
                                    "mass_th": 524., "charge_e": 1, "tob_us": 0.},
        }
        state = _bunch_center_source_state(materialization)
        observation = {"source_release_state": _source_release_record(state, 524., 1, 0.)}
        return materialization, observation

    def test_selected_center_projection_ignores_only_queue_identity(self):
        mother, observation = self._declared_center()
        child = copy.deepcopy(mother)
        child["source_expected_particle_ids"] = [1]
        child["fly2_sha256"] = "different-queue"
        self.assertEqual(_center_source_projection(mother, observation),
                         _center_source_projection(child, observation))
        for field, value in (("frame_id", "other_frame"), ("clock_basis", "other_clock")):
            changed = copy.deepcopy(child)
            changed["source_cohort"][field] = value
            if field == "clock_basis":
                changed["source_clock_basis"] = value
            self.assertNotEqual(_center_source_projection(mother, observation),
                                _center_source_projection(changed, observation))

    def test_selected_center_projection_rejects_changed_release_state(self):
        materialization, observation = self._declared_center()
        for key, value in (("position_mm", [0., -55., 32.]), ("velocity_mm_per_us", [0., 2., 0.]),
                           ("particle_mass_th", 525.), ("charge_state", 2), ("time_us", 1.)):
            changed = copy.deepcopy(observation)
            changed["source_release_state"][key] = value
            with self.subTest(key=key), self.assertRaises(CandidateContractError):
                _center_source_projection(materialization, changed)
        changed = copy.deepcopy(materialization)
        changed["source_clock_basis"] = "other_clock"
        with self.assertRaises(CandidateContractError):
            _center_source_projection(changed, observation)

    def test_trial_center_projection_and_plain_queue_identity(self):
        baseline, _, _ = self._fixture()
        with tempfile.TemporaryDirectory() as temp:
            manifests = [self._write_trial(Path(temp)/name, baseline) for name in ('mother', 'child')]
            center, observation = self._declared_center()
            for index, manifest in enumerate(manifests):
                document = json.loads(manifest.read_text())
                for record in document['outputs'][:2]:
                    path = Path(record['path'])
                    value = json.loads(path.read_text())
                    if path.name.endswith('observation.json'):
                        value.update(observation)
                    else:
                        value.update(center)
                        value['fly2_sha256'] = f'queue-{index}'
                        value['inputs']['bunch_source_receipt_sha256'] = f'mother-{index}'
                        if index == 1:
                            value['source_expected_particle_ids'] = [1]
                    path.write_text(json.dumps(value), encoding='utf-8')
                    record.update(bytes=path.stat().st_size, sha256=file_sha256(path))
                manifest.write_text(json.dumps(document), encoding='utf-8')
            a, b = [_trial(path) for path in manifests]
            self.assertEqual(a['frozen_problem'], b['frozen_problem'])
            self.assertNotEqual(a['consumer_projection']['fly2_sha256'], b['consumer_projection']['fly2_sha256'])
            for manifest in manifests:
                document = json.loads(manifest.read_text())
                record = document['outputs'][1]
                path = Path(record['path'])
                value = json.loads(path.read_text())
                value['source_cohort_role'] = 'formal_volume'
                path.write_text(json.dumps(value), encoding='utf-8')
                record.update(bytes=path.stat().st_size, sha256=file_sha256(path))
                manifest.write_text(json.dumps(document), encoding='utf-8')
            a, b = [_trial(path) for path in manifests]
            self.assertNotEqual(a['frozen_problem'], b['frozen_problem'])

    def test_affine_field_retains_scientific_family_and_actual_voltage_authority(self):
        values = [0.] * 20
        values[10:14] = [-27.] * 2 + [54.] * 2
        values[15:17] = [190., -190.]
        binding = {"authority": {"analyzer_electrode_voltages_v": values}, "geometry": {"slot_mm": 4.},
                   "representation": "exploratory_affine_s_responses",
                   "response_family": {"source_mesh_record": "mesh3"},
                   "response_terms": [{"binding_path": name} for name in ("base", "s1", "s2")]}
        receipt = {"field_binding": {"mode": "comsol_static_scalar_v", "path": "combined.json"},
                   "analyzer_electrode_voltages_v": values.copy(), "stripe_biases_v": [-27., 54.],
                   "prism_voltages_v": [190., -190.]}
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_fixed_grid_workpoint"
        with patch(module + ".load_binding", return_value=binding):
            for representation in ("exploratory_affine_s_responses", "exploratory_affine_ps_responses",
                                   "exploratory_materialized_affine_ps_responses"):
                binding["representation"] = representation
                with self.subTest(representation=representation):
                    problem = _static_field_problem(receipt)
                    problem.pop("geometry_sha256")
                    self.assertEqual(problem, binding["response_family"])
                    bad = copy.deepcopy(receipt)
                    bad["prism_voltages_v"][0] += 1.
                    with self.assertRaises(CandidateContractError):
                        _static_field_problem(bad)

    def test_materialized_response_retains_family_and_checks_all_actual_voltages(self):
        values = [0.] * 20
        values[10:14] = [-27.] * 2 + [54.] * 2
        values[15:17] = [190., -190.]
        binding = {"representation": "exploratory_materialized_affine_s_responses", "geometry": {"slot_mm": 4.},
                   "authority": {"analyzer_electrode_voltages_v": values},
                   "response_family": {"source_mesh_record": "mesh3", "geometry": "frozen"},
                   "composition_sources": [{"binding_path": "base", "coefficient": 1.}]}
        receipt = {"field_binding": {"mode": "comsol_static_scalar_v", "path": "materialized.json"},
                   "analyzer_electrode_voltages_v": values.copy(), "stripe_biases_v": [-27., 54.],
                   "prism_voltages_v": [190., -190.]}
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_fixed_grid_workpoint"
        with patch(module + ".load_binding", return_value=binding), patch(module + "._static_binding_problem") as direct:
            problem = _static_field_problem(receipt)
            problem.pop("geometry_sha256")
            self.assertEqual(problem, binding["response_family"])
            direct.assert_not_called()
            for field, index in (("stripe_biases_v", 0), ("prism_voltages_v", 1),
                                 ("analyzer_electrode_voltages_v", 3)):
                bad = copy.deepcopy(receipt)
                bad[field][index] += 1.
                with self.subTest(field=field), self.assertRaises(CandidateContractError):
                    _static_field_problem(bad)

    def test_static_family_compares_geometry_content_not_export_json_bytes(self):
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_fixed_grid_workpoint"
        receipt = {"field_binding": {"mode": "comsol_static_scalar_v", "path": "field.json"}}
        geometry = {"slot_mm": 4., "origin_mm": [0., -55., 0.]}
        variants = [json.loads(json.dumps(geometry, indent=2)),
                    json.loads(json.dumps(geometry, sort_keys=True)), copy.deepcopy(geometry)]
        problems = []
        for index, resolved in enumerate(variants):
            family = {"geometry_sha256": f"sealed-bytes-{index}", "solver_numerics": {"mesh": "mesh6"}}
            with patch(module + ".load_binding", return_value={"geometry": resolved}), \
                 patch(module + "._static_binding_problem", return_value=family):
                problems.append(_static_field_problem(receipt))
        self.assertEqual(problems[0], problems[1])
        self.assertEqual(problems[0], problems[2])
        for changed in ({"slot_mm": 5., "origin_mm": [0., -55., 0.]}, geometry):
            family = {"geometry_sha256": "sealed-original", "solver_numerics": {"mesh": "mesh6"}}
            if changed == geometry:
                family["solver_numerics"]["mesh"] = "mesh5"
            with patch(module + ".load_binding", return_value={"geometry": changed}), \
                 patch(module + "._static_binding_problem", return_value=family):
                self.assertNotEqual(problems[0], _static_field_problem(receipt))

    def test_runner_uses_ledger_lifecycle_and_one_capacity_session(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "-CapacityLedgerLifecycleEnabled", "Enter-ArtifactWorkflowCapacitySession",
            "Update-ArtifactWorkflowCapacitySession", "Exit-ArtifactWorkflowCapacitySession",
        ):
            self.assertIn(token, source)
        self.assertNotIn("Invoke-ArtifactCapacityGate", source)

    @staticmethod
    def _fixture():
        base_v = np.array([-25.0, 50.0, 190.0, -190.0])
        base_r = np.array([0.15, 2.0e-4, 4.4, 0.65])
        jacobian = np.array([
            [0.01, 0.00, 0.20, 0.03],
            [0.00, 1.0e-5, 2.0e-4, -3.0e-4],
            [0.40, -0.10, 0.02, 0.01],
            [0.05, 0.20, 0.01, -0.02],
        ])
        frozen = {"target_k": 25.5}
        baseline = {"voltages_v": base_v.tolist(), "residual_vector": base_r.tolist(), "frozen_problem": frozen}
        perturbations = []
        for index in range(4):
            voltage = base_v.copy()
            voltage[index] += 0.1
            perturbations.append({
                "voltages_v": voltage.tolist(),
                "residual_vector": (base_r + 0.1 * jacobian[:, index]).tolist(),
                "frozen_problem": frozen,
            })
        return baseline, perturbations, jacobian

    def test_recovers_full_rank_step_and_applies_trust_limit(self) -> None:
        baseline, perturbations, jacobian = self._fixture()
        result = solve_linearized_step(
            baseline,
            perturbations,
            lower_bounds_v=[-100, 1, 1, -400],
            upper_bounds_v=[-1, 100, 400, -1],
            parameter_scales_v=[25, 50, 190, 190],
            residual_scales=[0.01, np.tan(np.deg2rad(0.01)), 1.0, 1.0],
            maximum_abs_step_v=[2, 2, 2, 2],
            relative_rank_tolerance=1e-10,
            compatibility_tolerance=1e-8,
        )
        np.testing.assert_allclose(result["physical_jacobian_rows"], jacobian, atol=1e-12)
        np.testing.assert_allclose(result["stencil_steps_v"], [0.1] * 4)
        self.assertNotIn("forward_steps_v", result)
        self.assertEqual(result["classification"]["status"], "square_exact")
        self.assertGreater(result["trust_scale"], 0.0)
        self.assertLessEqual(max(abs(value) for value in result["applied_correction_v"]), 2.0 + 1e-12)
        self.assertEqual(set(result["predicted_residuals"]), set(RESIDUAL_NAMES))

    def test_rejects_non_single_axis_perturbation(self) -> None:
        baseline, perturbations, _jacobian = self._fixture()
        perturbations[0]["voltages_v"][1] += 0.1
        with self.assertRaisesRegex(CandidateContractError, "change only"):
            solve_linearized_step(
                baseline,
                perturbations,
                lower_bounds_v=[-100, 1, 1, -400],
                upper_bounds_v=[-1, 100, 400, -1],
                parameter_scales_v=[25, 50, 190, 190],
                residual_scales=[1, 1, 1, 1],
                maximum_abs_step_v=[2, 2, 2, 2],
                relative_rank_tolerance=1e-10,
                compatibility_tolerance=1e-8,
            )

    def test_signed_columns_preserve_jacobian_direction(self) -> None:
        baseline, perturbations, jacobian = self._fixture()
        steps = [-0.1, 0.2, -0.3, 0.4]
        for index, step in enumerate(steps):
            voltages = np.array(baseline["voltages_v"])
            voltages[index] += step
            perturbations[index]["voltages_v"] = voltages.tolist()
            perturbations[index]["residual_vector"] = (
                np.array(baseline["residual_vector"]) + step * jacobian[:, index]
            ).tolist()
        result = solve_linearized_step(
            baseline, perturbations,
            lower_bounds_v=[-100, 1, 1, -400], upper_bounds_v=[-1, 100, 400, -1],
            parameter_scales_v=[25, 50, 190, 190], residual_scales=[1, 1, 1, 1],
            maximum_abs_step_v=[2, 2, 2, 2], relative_rank_tolerance=1e-10,
            compatibility_tolerance=1e-8,
        )
        np.testing.assert_allclose(result["physical_jacobian_rows"], jacobian, atol=1e-12)
        np.testing.assert_allclose(result["stencil_steps_v"], steps)
        self.assertNotIn("forward_steps_v", result)

    def test_rejects_zero_step(self) -> None:
        baseline, perturbations, _ = self._fixture()
        perturbations[0]["voltages_v"] = list(baseline["voltages_v"])
        with self.assertRaisesRegex(CandidateContractError, "nonzero step"):
            solve_linearized_step(
                baseline, perturbations,
                lower_bounds_v=[-100, 1, 1, -400], upper_bounds_v=[-1, 100, 400, -1],
                parameter_scales_v=[25, 50, 190, 190], residual_scales=[1, 1, 1, 1],
                maximum_abs_step_v=[2, 2, 2, 2], relative_rank_tolerance=1e-10,
                compatibility_tolerance=1e-8,
            )

    def test_rejects_changed_frozen_problem(self) -> None:
        baseline, perturbations, _jacobian = self._fixture()
        perturbations[3]["frozen_problem"] = {"target_k": 24.5}
        with self.assertRaisesRegex(CandidateContractError, "frozen physical problem"):
            solve_linearized_step(
                baseline,
                perturbations,
                lower_bounds_v=[-100, 1, 1, -400],
                upper_bounds_v=[-1, 100, 400, -1],
                parameter_scales_v=[25, 50, 190, 190],
                residual_scales=[1, 1, 1, 1],
                maximum_abs_step_v=[2, 2, 2, 2],
                relative_rank_tolerance=1e-10,
                compatibility_tolerance=1e-8,
            )

    @staticmethod
    def _contract():
        path = Path(__file__).resolve().parents[2] / "config" / "simion_candidate_two_zone.json"
        contract = json.loads(path.read_text(encoding="utf-8-sig"))
        contract["downstream_fixed_grid_workpoint_profile"]["active_stripe_axes"] = list(UNKNOWN_NAMES[:2])
        # Synthetic frozen trials below deliberately describe K=25.5.
        contract["nominal"]["target_drift_period_ratio"] = 25.5
        return contract

    @staticmethod
    def _write_trial(folder, trial):
        folder.mkdir()
        voltages = trial["voltages_v"]
        observation = {
            "status": "detected", "prism_voltages_v": voltages[2:],
            "residuals": dict(zip(RESIDUAL_NAMES, trial["residual_vector"])),
        }
        materialization = {
            "stripe_biases_v": voltages[:2], "prism_voltages_v": voltages[2:],
            "inputs": {
                "geometry_sha256": "same-geometry",
                "fixed_mirror_stripe_authority_sha256": "same-authority",
                "mirror_summary_sha256": "same-mirror",
                "reviewed_contract_sha256": "same-reviewed-contract",
                "stripe_summary_sha256": "same-stripe",
            },
            "target_drift_period_ratio": 25.5, "target_positive_mirror_turn_y_mm": 0.0,
            "target_low_field_tangent_ratio_vy_over_vz": 0.033,
            "target_slow_turn_y_mm": 340.0,
            "mirror_voltages_v": [0, -5900, -2600, 4200, 6030],
            "selected_axial_energy_per_charge_v": 4372.0,
            "source_slow_kinetic_energy_per_charge_v": 4.96,
            "fly2_sha256": "same-source", "drift_phase_contract": {"half_oscillations": 51},
            "nonaccelerator_mesh_mm_per_gu": [1, 1, 1],
        }
        def record(name, content):
            path = folder / name
            path.write_text(json.dumps(content), encoding="utf-8")
            return {"path": str(path), "exists": True, "bytes": path.stat().st_size, "sha256": file_sha256(path)}
        manifest = {
            "status": "success", "project": "parallel_mirror_dual_stripe_mr_tof",
            "mode": "finite_3d_two_prism_voltage_trial",
            "run_config": record("run_config.json", {"parameters": {}}),
            "outputs": [record("two_prism_trial_observation.json", observation),
                        record("two_prism_trial_materialization.json", materialization),
                        {"path": str(folder / "unused_corrupt.pa"), "exists": True, "bytes": 100, "sha256": "bad"}],
        }
        path = folder / "run_manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def test_sealed_trial_contract_projection_preserves_science_not_controller_policy(self):
        baseline, _, _ = self._fixture()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            def load(index, contract, *, reviewed=None, wrong_reviewed_hash=False,
                     tamper_reviewed=False, tamper_resolved=False):
                path = self._write_trial(root / str(index), baseline)
                manifest = json.loads(path.read_text(encoding="utf-8"))
                contract_path = path.parent / "resolved_contract.json"
                contract_path.write_text(json.dumps(contract), encoding="utf-8")
                digest = file_sha256(contract_path)
                record = dict(path=str(contract_path), exists=True,
                              bytes=contract_path.stat().st_size, sha256=digest)
                reviewed_path = contract_path
                reviewed_record = record
                if reviewed is not None:
                    reviewed_path = path.parent / "reviewed_contract.json"
                    reviewed_path.write_text(json.dumps(reviewed), encoding="utf-8")
                    reviewed_record = dict(path=str(reviewed_path), exists=True,
                                           bytes=reviewed_path.stat().st_size,
                                           sha256=file_sha256(reviewed_path))
                manifest["inputs"] = dict(trajectory_numerics_contract=record,
                                          reviewed_geometry_contract=reviewed_record)
                material_record = manifest["outputs"][1]
                material_path = Path(material_record["path"])
                material = json.loads(material_path.read_text(encoding="utf-8"))
                material["inputs"].update(contract_sha256=digest,
                                         accelerator_geometry_contract_sha256=digest,
                                         trajectory_contract_sha256=digest,
                                         reviewed_contract_sha256=("wrong" if wrong_reviewed_hash
                                                                  else reviewed_record["sha256"]))
                material_path.write_text(json.dumps(material), encoding="utf-8")
                material_record.update(bytes=material_path.stat().st_size,
                                       sha256=file_sha256(material_path))
                path.write_text(json.dumps(manifest), encoding="utf-8")
                if tamper_reviewed:
                    reviewed_path.write_bytes(reviewed_path.read_bytes().replace(b" ", b"\t", 1))
                if tamper_resolved:
                    contract_path.write_bytes(contract_path.read_bytes().replace(b" ", b"\t", 1))
                return _trial(path)

            original = self._contract()
            original["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"].pop(
                "advance_multiplier", None)
            original["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"].pop(
                "backtrack_multiplier", None)
            anchor = load(0, original)
            changed = copy.deepcopy(original)
            changed["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"].update(
                advance_multiplier=1.0, backtrack_multiplier=0.5)
            child = load(1, changed)
            self.assertEqual(anchor["frozen_problem"], child["frozen_problem"])
            self.assertNotEqual(file_sha256(root / "0" / "resolved_contract.json"),
                                file_sha256(root / "1" / "resolved_contract.json"))
            for index, section in enumerate(("source", "geometry", "targets", "trajectory"), 2):
                science_changed = copy.deepcopy(changed)
                science_changed[section] = {"changed_physics": index}
                self.assertNotEqual(anchor["frozen_problem"],
                                    load(index, science_changed)["frozen_problem"])
            with self.assertRaisesRegex(CandidateContractError, "identity differs"):
                load(6, changed, wrong_reviewed_hash=True)

            effective = copy.deepcopy(changed)
            effective["accelerator"]["focus_y_anchor"]["project_y_mm"] = -55.0
            reviewed_seed = copy.deepcopy(changed)
            reviewed_seed["accelerator"]["focus_y_anchor"]["project_y_mm"] = -50.0
            seed = load(7, effective, reviewed=reviewed_seed)
            child = load(8, effective, reviewed=effective)
            self.assertEqual(seed["frozen_problem"], child["frozen_problem"])
            moved = copy.deepcopy(effective)
            moved["accelerator"]["focus_y_anchor"]["project_y_mm"] = -54.0
            self.assertNotEqual(seed["frozen_problem"],
                                load(9, moved, reviewed=reviewed_seed)["frozen_problem"])
            other_reviewed_physics = copy.deepcopy(reviewed_seed)
            other_reviewed_physics["source"] = {"changed_physics": True}
            self.assertNotEqual(seed["frozen_problem"],
                                load(10, effective, reviewed=other_reviewed_physics)["frozen_problem"])
            with self.assertRaisesRegex(CandidateContractError, "identity differs"):
                load(11, effective, reviewed=reviewed_seed, wrong_reviewed_hash=True)
            for index, mutation in ((12, "tamper_reviewed"), (13, "tamper_resolved")):
                with self.subTest(mutation=mutation), self.assertRaisesRegex(AssertionError, "SHA-256"):
                    load(index, effective, reviewed=reviewed_seed, **{mutation: True})

    def test_contract_derives_energy_bounds_and_angle_scale(self):
        contract = self._contract()
        baseline, _, _ = self._fixture()
        baseline["frozen_problem"] = {
            "selected_axial_energy_per_charge_v": 4372.0,
            "targets": {"target_low_field_tangent_ratio_vy_over_vz": 0.033},
        }
        controls = resolve_numerics(contract, baseline)
        self.assertEqual(controls["lower_bounds_v"][0], -4372.0)
        self.assertLess(controls["upper_bounds_v"][1], 4272.0)
        self.assertEqual(controls["parameter_scales_v"], [25, 50, 190, 190])
        np.testing.assert_allclose(controls["maximum_abs_step_v"], [0.25, 0.5, 1.9, 1.9])
        self.assertAlmostEqual(controls["residual_scales"][1], 0.000174722, places=8)
        missing = copy.deepcopy(contract)
        del missing["downstream_fixed_grid_workpoint_profile"]["jacobian_relative_step_tiers"]
        with self.assertRaises(KeyError):
            resolve_numerics(missing, baseline)

    def test_single_stripe_numerics_fixed_zero_and_explicit_axis_contract(self):
        contract = self._contract()
        profile = contract["downstream_fixed_grid_workpoint_profile"]
        profile["active_stripe_axes"] = ["stripe_1_voltage_v"]
        baseline, _, _ = self._fixture()
        baseline["voltages_v"][1] = 0.0
        baseline["frozen_problem"] = {
            "selected_axial_energy_per_charge_v": 4372.0,
            "targets": {"target_low_field_tangent_ratio_vy_over_vz": 0.033},
        }
        result = resolve_numerics(contract, baseline)
        self.assertEqual(result["active_stripe_axes"], ["stripe_1_voltage_v"])
        self.assertEqual(result["lower_bounds_v"][1], 0.0)
        self.assertEqual(result["upper_bounds_v"][1], 0.0)
        baseline["voltages_v"][1] = 0.001
        with self.assertRaisesRegex(CandidateContractError, "inactive S2"):
            resolve_numerics(contract, baseline)
        for names in (None, [], ["s1"], ["stripe_2_voltage_v"], ["stripe_1_voltage_v"] * 2):
            with self.subTest(names=names), self.assertRaises(CandidateContractError):
                resolve_active_stripe_axes({"active_stripe_axes": names})

    def test_audit_reads_materialized_stripes_freezes_projection_and_ignores_unused_pa(self):
        baseline, perturbations, _ = self._fixture()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifests = [self._write_trial(root / str(index), value)
                         for index, value in enumerate((baseline, *perturbations))]
            contract_path = root / "contract.json"
            contract_path.write_text(json.dumps(self._contract()), encoding="utf-8")
            definition = {"schema_version": 1, "role": "mrtof_downstream_fixed_grid_workpoint_definition",
                          "contract": str(contract_path), "baseline_manifest": str(manifests[0]),
                          "perturbation_manifests": dict(zip(UNKNOWN_NAMES, map(str, manifests[1:])))}
            definition_path = root / "definition.json"
            definition_path.write_text(json.dumps(definition), encoding="utf-8")
            result = audit(definition_path, root / "frozen")
            self.assertEqual(result["target_drift_period_ratio"], 25.5)
            self.assertEqual(result["classification"]["status"], "square_exact")
            self.assertEqual(len(result["consumed_trials"]), 5)
            self.assertEqual(len(list((root / "frozen").rglob("*.json"))), 20)
            changed_contract = self._contract()
            changed_contract["nominal"]["target_drift_period_ratio"] = 24.5
            contract_path.write_text(json.dumps(changed_contract), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "target K"):
                audit(definition_path)
            definition["maximum_abs_step_v"] = [99]*4
            definition_path.write_text(json.dumps(definition), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "overrides"):
                audit(definition_path)

    def test_iteration_rejects_changed_source_offset_and_profile(self):
        baseline, _, _ = self._fixture()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = self._write_trial(root / "base", baseline)
            child = self._write_trial(root / "child", baseline)
            proposal = {"baseline_manifest": str(base), "consumed_trials": [
                {"manifest": str(base), "manifest_sha256": file_sha256(base)}]}
            assert_trial_matches_jacobian(proposal, child)
            original = json.loads(child.read_text())
            mat_path = child.parent / "two_prism_trial_materialization.json"
            original_mat = json.loads(mat_path.read_text())
            for key, value in (("source_position_project_mm", [0, -1.8, 0]),
                               ("trajectory_profile", {"maximum_step_us": 0.1})):
                mat_path.write_text(json.dumps({**original_mat, key: value}))
                doc = copy.deepcopy(original)
                doc["outputs"][1].update(bytes=mat_path.stat().st_size, sha256=file_sha256(mat_path))
                child.write_text(json.dumps(doc))
                with self.assertRaisesRegex(Exception, key):
                    assert_trial_matches_jacobian(proposal, child)

    def test_native_trial_requires_bound_receipt_and_freezes_bank_identity(self):
        baseline, _, _ = self._fixture()
        with tempfile.TemporaryDirectory() as temp:
            manifest_path = self._write_trial(Path(temp) / "trial", baseline)
            manifest = json.loads(manifest_path.read_text())
            config_path = manifest_path.parent / "run_config.json"
            config = json.loads(config_path.read_text())
            config["parameters"]["pa_binding_mode"] = "native_corridor_private_fast_adjust_family__four_instances__n1"
            config_path.write_text(json.dumps(config))
            manifest["run_config"].update(bytes=config_path.stat().st_size, sha256=file_sha256(config_path))
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(Exception, "mode and receipt disagree"):
                _trial(manifest_path)
            receipt = manifest_path.parent / "native_corridor_runtime_family.json"
            receipt.write_text(json.dumps({
                "schema_version": 1, "role": "mrtof_private_native_corridor_family", "status": "prepared",
                "cache_key": "a" * 64, "generation_sha256": "b" * 64,
                "response_refine_performed": False, "published_native_members_opened": False,
                "controller_refine": "solutions={0}",
            }))
            manifest["outputs"].append({"path": str(receipt), "exists": True,
                                        "bytes": receipt.stat().st_size, "sha256": file_sha256(receipt)})
            manifest_path.write_text(json.dumps(manifest))
            trial = _trial(manifest_path, Path(temp) / "frozen")
            self.assertEqual(trial["frozen_problem"]["native_bank_identity"]["cache_key"], "A" * 64)
            self.assertTrue((Path(temp) / "frozen" / receipt.name).is_file())
            receipt.write_text("{}")
            with self.assertRaises(Exception):
                _trial(manifest_path)

    def test_trial_rejects_consumed_output_corruption(self):
        baseline, _, _ = self._fixture()
        with tempfile.TemporaryDirectory() as temp:
            manifest = self._write_trial(Path(temp) / "trial", baseline)
            (manifest.parent / "two_prism_trial_observation.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "byte count"):
                _trial(manifest)

    def test_native_history_uses_bound_small_evidence_not_retired_payload(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import load_binding
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial import _collision_geometry_projection

        baseline, _, _ = self._fixture()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trial_path = self._write_trial(root / "trial", baseline)
            owner = root / "field"
            owner.mkdir()
            def record(path, content):
                path.write_text(json.dumps(content), encoding="utf-8")
                return dict(path=str(path), bytes=path.stat().st_size, sha256=file_sha256(path), exists=True)
            values = [0.] * 20
            values[10:14] = [-25., -25., 50., 50.]
            values[15:17] = [190., -190.]
            authority = {"analyzer_electrode_voltages_v": values}
            geometry = {key: [] for key in ("mirror_electrodes", "mirror_slot", "mirror_inner_shield_slot",
                "mirror_ground_shields", "mirror_e_closures", "stripe_electrodes", "stripe_slot",
                "central_ground_electrodes", "central_ground_slots", "prism_electrodes", "prism_ground_shields")}
            grid = dict(origin_mm=[0, -2, -2], pitch_mm=[.5, 1., 1.], dimensions=[5, 5, 5], symmetry="x")
            plan = dict(box_mm=[0, -2, -2, 2, 2, 2], pitch_mm=grid["pitch_mm"], dimensions=grid["dimensions"],
                        boundary_mode="grounded_enclosure")
            records = {name: record(owner / (name + ".json"), value) for name, value in (
                ("voltage_authority", authority), ("geometry_authority", geometry), ("numerical_plan", plan))}
            # The flight sealed these identities before their owner retired the PA.
            # No payload is needed, opened or recreated by historical analysis.
            for name, filename in (("scalar_pa", "field.pa"), ("surface", "field.pa-surf")):
                records[name] = dict(path=str(owner / filename), bytes=100, sha256="a" * 64, exists=True)
            owner_manifest = owner / "run_manifest.json"
            owner_manifest.write_text(json.dumps(dict(status="success", outputs=list(records.values()))), encoding="utf-8")
            sources = {name: item["path"] for name, item in records.items()}
            parent = dict(manifest=str(owner_manifest), grid=grid, **{key: sources[name] for name, key in (
                ("scalar_pa", "pa_path"), ("surface", "surface_path"), ("voltage_authority", "voltage_authority_path"),
                ("geometry_authority", "geometry_authority_path"), ("numerical_plan", "numerical_plan_path"))})
            instances = [dict(role=role, manifest=str(owner_manifest), pa_path=sources["scalar_pa"], origin_mm=[0, 0, 0])
                         for role in ("global_fallback", "native_corridor", "accelerator", "detector")]
            descriptor = dict(schema_version=1, role="mrtof_native_static_field_binding", parent=parent,
                              refinement_windows=[], instances=instances)
            binding_path = trial_path.parent / "static_field_binding.json"
            binding_record = record(binding_path, descriptor)
            materialization_path = trial_path.parent / "two_prism_trial_materialization.json"
            mat = json.loads(materialization_path.read_text())
            mat.update(analyzer_electrode_voltages_v=values, collision_geometry=_collision_geometry_projection(geometry), field_binding=dict(
                mode="native_static_pa", path=str(binding_path), manifest=str(owner_manifest), grid=grid,
                records=records, sources=sources, refinement_windows=[]))
            manifest = json.loads(trial_path.read_text())
            config = {"parameters": {}, "provenance": {"upstream_manifest_verification": {"geometry": {
                "instances": [dict(i, record=records["scalar_pa"]) for i in instances]}}}}
            manifest["run_config"] = record(trial_path.parent / "run_config.json", config)
            manifest["inputs"] = {"static_field_binding": binding_record}
            manifest["outputs"][1] = record(materialization_path, mat)
            trial_path.write_text(json.dumps(manifest), encoding="utf-8")
            original = _trial(trial_path)
            self.assertEqual(original["frozen_problem"]["static_field_problem"]["grid"], grid)
            # A current stopping policy remains analyzable from its sealed small
            # contract after PA retirement, and must match the flown readback.
            contract_path = owner / "numerical_contract.json"
            contract_record = record(contract_path, {"simion": {"numerical_profiles": {
                "native_static_field": {"refine": {"convergence_v": 1e-5}}}}})
            plan.update(numerical_contract_path=str(contract_path), refine_stopping="contract_convergence",
                        convergence_v=1e-5)
            records["numerical_plan"] = record(Path(sources["numerical_plan"]), plan)
            owner_manifest.write_text(json.dumps(dict(status="success", outputs=[
                *records.values(), contract_record])), encoding="utf-8")
            mat["field_binding"]["records"] = records
            mat["field_binding"]["native_solver_numerics"] = dict(solver="SIMION2020",
                refine_stopping="contract_convergence", convergence_v=1e-5,
                surface="fractional", boundary_mode="grounded_enclosure")
            manifest["outputs"][1] = record(materialization_path, mat)
            trial_path.write_text(json.dumps(manifest), encoding="utf-8")
            strict = _trial(trial_path)
            self.assertEqual(strict["frozen_problem"]["static_field_problem"]["solver_numerics"]["convergence_v"], 1e-5)
            mat["field_binding"]["native_solver_numerics"]["convergence_v"] = 1e-7
            manifest["outputs"][1] = record(materialization_path, mat)
            trial_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "parent stopping identity"):
                _trial(trial_path)
            for key in ("numerical_contract_path", "refine_stopping", "convergence_v"):
                plan.pop(key)
            records["numerical_plan"] = record(Path(sources["numerical_plan"]), plan)
            mat["field_binding"].pop("native_solver_numerics")
            manifest["outputs"][1] = record(materialization_path, mat)
            trial_path.write_text(json.dumps(manifest), encoding="utf-8")
            # A sealed absent sidecar remains analyzable after PA retirement;
            # absence is evidence, never a missing-record fallback.
            summary = dict(status="success", refine_completed=True, failure_stage=None,
                           surface_before_builder=dict(exists=False, bytes=None),
                           surface_after_builder=dict(exists=False, bytes=None),
                           stage_seconds=dict(gem2pa_seconds=1), native_outputs=[dict(name="field.pa")])
            (owner/"logs").mkdir()
            extra = [record(owner/"summary.json", summary), record(owner/"logs/gem2pa.log", {})]
            owner_manifest.write_text(json.dumps(dict(status="success", outputs=[
                *(r for n, r in records.items() if n != "surface"), *extra])), encoding="utf-8")
            parent["surface_path"] = None
            sources["surface"] = None
            surface_record = records["surface"]
            records["surface"] = None
            manifest["inputs"]["static_field_binding"] = record(binding_path, descriptor)
            manifest["outputs"][1] = record(materialization_path, mat)
            trial_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(_trial(trial_path)["frozen_problem"]["static_field_problem"]["grid"], grid)
            summary["refine_completed"] = False
            extra[0] = record(owner/"summary.json", summary)
            owner_manifest.write_text(json.dumps(dict(status="success", outputs=[
                *(r for n, r in records.items() if n != "surface"), *extra])), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-generation evidence"):
                _trial(trial_path)
            records["surface"] = surface_record
            sources["surface"] = surface_record["path"]
            parent["surface_path"] = sources["surface"]
            owner_manifest.write_text(json.dumps(dict(status="success", outputs=list(records.values()))), encoding="utf-8")
            manifest["inputs"]["static_field_binding"] = record(binding_path, descriptor)
            manifest["outputs"][1] = record(materialization_path, mat)
            trial_path.write_text(json.dumps(manifest), encoding="utf-8")
            bad_config = copy.deepcopy(config)
            bad_config["provenance"]["upstream_manifest_verification"]["geometry"]["instances"][1]["origin_mm"][1] = 1.
            manifest["run_config"] = record(trial_path.parent / "run_config.json", bad_config)
            trial_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "collision instances"):
                _trial(trial_path)
            manifest["run_config"] = record(trial_path.parent / "run_config.json", config)
            trial_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing or changed size"):
                load_binding(binding_path)
            # A binding not sealed by the flight is never trusted.
            manifest["inputs"] = {}
            trial_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "bound static field"):
                _trial(trial_path)
            manifest["inputs"] = {"static_field_binding": binding_record}
            trial_path.write_text(json.dumps(manifest), encoding="utf-8")
            authority_path = Path(sources["voltage_authority"])
            authority_path.write_text(json.dumps({"analyzer_electrode_voltages_v": [1.] * 20}), encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "voltage_authority"):
                _trial(trial_path)
            authority_path.write_text(json.dumps(authority), encoding="utf-8")
            binding_path.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "static_field_binding"):
                _trial(trial_path)
            binding_path.write_text(json.dumps(descriptor), encoding="utf-8")
            bad = copy.deepcopy(mat)
            bad["field_binding"]["grid"]["pitch_mm"][1] = .25
            manifest["outputs"][1] = record(materialization_path, bad)
            trial_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "grid or source"):
                _trial(trial_path)
            bad = copy.deepcopy(mat)
            bad["analyzer_electrode_voltages_v"][0] = 1.
            manifest["outputs"][1] = record(materialization_path, bad)
            trial_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "full voltages"):
                _trial(trial_path)

    def test_trial_rejects_inconsistent_observed_prism_voltage(self):
        baseline, _, _ = self._fixture()
        with tempfile.TemporaryDirectory() as temp:
            manifest_path = self._write_trial(Path(temp) / "trial", baseline)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            record = manifest["outputs"][0]
            path = Path(record["path"])
            observation = json.loads(path.read_text(encoding="utf-8"))
            observation["prism_voltages_v"][0] += 1.0
            path.write_text(json.dumps(observation), encoding="utf-8")
            record.update(bytes=path.stat().st_size, sha256=file_sha256(path))
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "observed prism"):
                _trial(manifest_path)

    def test_rank_deficiency_does_not_publish_proposal(self):
        baseline, perturbations, _ = self._fixture()
        perturbations[3]["residual_vector"] = baseline["residual_vector"]
        with self.assertRaisesRegex(CandidateContractError, "not square exact"):
            solve_linearized_step(
                baseline, perturbations, lower_bounds_v=[-100, 1, 100, -300],
                upper_bounds_v=[-1, 100, 300, -100], parameter_scales_v=[25, 50, 190, 190],
                residual_scales=[1, 1, 1, 1], maximum_abs_step_v=[2]*4,
                relative_rank_tolerance=1e-10, compatibility_tolerance=1e-8,
            )

    def test_transported_jacobian_rebases_current_real_baseline(self):
        baseline, perturbations, jacobian = self._fixture()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old_manifests = [self._write_trial(root / f"old_{index}", value)
                             for index, value in enumerate((baseline, *perturbations))]
            contract_path = root / "contract.json"
            contract_path.write_text(json.dumps(self._contract()), encoding="utf-8")
            original_definition = {
                "schema_version": 1,
                "role": "mrtof_downstream_fixed_grid_workpoint_definition",
                "contract": str(contract_path),
                "baseline_manifest": str(old_manifests[0]),
                "perturbation_manifests": dict(zip(UNKNOWN_NAMES, map(str, old_manifests[1:]))),
            }
            original_definition_path = root / "original_definition.json"
            original_definition_path.write_text(json.dumps(original_definition), encoding="utf-8")
            prior = audit(original_definition_path)
            prior_path = root / "downstream_fixed_grid_workpoint.json"
            prior_path.write_text(json.dumps(prior), encoding="utf-8")
            prior_record = {
                "path": str(prior_path), "exists": True, "bytes": prior_path.stat().st_size,
                "sha256": file_sha256(prior_path),
            }
            prior_manifest_path = root / "prior_run_manifest.json"
            prior_manifest_path.write_text(json.dumps({
                "status": "success", "project": "parallel_mirror_dual_stripe_mr_tof",
                "mode": "downstream_fixed_grid_workpoint", "outputs": [prior_record],
            }), encoding="utf-8")

            current_voltage = np.array([-25.2, 50.2, 196.0, -195.1])
            current_residual = np.array([-0.09, -6.0e-5, 1.5, 1.8])
            current_manifest = self._write_trial(root / "current", {
                "voltages_v": current_voltage.tolist(),
                "residual_vector": current_residual.tolist(),
            })
            transported_definition = {
                "schema_version": 1,
                "role": "mrtof_downstream_transported_jacobian_definition",
                "contract": str(contract_path),
                "baseline_manifest": str(current_manifest),
                "prior_workpoint_manifest": str(prior_manifest_path),
            }
            transported_path = root / "transported_definition.json"
            transported_path.write_text(json.dumps(transported_definition), encoding="utf-8")
            result = audit(transported_path, root / "frozen")
            expected_raw = np.linalg.solve(jacobian, -current_residual)
            np.testing.assert_allclose(result["unbounded_linear_correction_v"], expected_raw, atol=1e-12)
            np.testing.assert_allclose(
                result["proposed_voltages_v"],
                current_voltage + np.asarray(result["applied_correction_v"]),
                atol=1e-12,
            )
            self.assertLessEqual(max(map(abs, result["applied_correction_v"])), 2.0)
            self.assertEqual(result["status"], "transported_linearized_candidate_step")
            self.assertEqual(result["jacobian_use"], "transported_local_approximation")
            self.assertTrue(result["outside_source_trust_radius"])
            self.assertTrue(result["requires_real_center_flight_confirmation"])
            self.assertEqual(len(result["consumed_trials"]), 1)
            self.assertTrue((root / "frozen" / "prior_baseline" / "run_manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
