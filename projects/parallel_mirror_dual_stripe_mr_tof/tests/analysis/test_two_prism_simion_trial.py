from __future__ import annotations

import hashlib
import json
import copy
from contextlib import nullcontext
import math
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from common.simion.native_completion import parse_fly_completed_line


def mock_recorded_scientific_events(events):
    # Algorithm fixtures provide event rows, while completion and provenance
    # still come from their real small native-log bytes.
    def read(log_path, **_):
        data = log_path.read_bytes()
        completed = [value for line in data.decode("utf-8-sig").splitlines()
                     if (value := parse_fly_completed_line(line)) is not None]
        return events, completed, hashlib.sha256(data).hexdigest()
    return patch(
        "projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis.read_scientific_events",
        side_effect=read,
    )


from projects.parallel_mirror_dual_stripe_mr_tof.analysis import two_prism_simion_trial
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.bunch_source_and_schedule import (
    materialize_bunch_source,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import parse_events
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial import (
    _accelerator_energy_binding,
    _accelerator_geometric_exit_reference,
    _accelerator_geometric_exit_validation,
    _accelerator_ring_voltages,
    _apply_terminal_mirror_variation,
    _apply_trajectory_step_scale,
    _accelerator_safe_exit_observation,
    _bunch_center_workpoint_validation,
    _bunch_center_stripe_stage_validation,
    _first_slow_turn_signature,
    _bunch_center_prism_handoff_validation,
    _load_frozen_accelerator_pulse_schedule,
    _mirror_regions,
    _resolve_trial_geometry,
    _fixed_mirror_stripe_source_state,
    _seed_theory_provenance,
    _schema5_native_source_state,
    _source_transverse_reference,
    _single_center_source_state,
    _single_center_source_fly2,
    _p2_handoff_targets,
    _provider_exit_energy_contract,
    _static_return_diagnostic,
    _termination_diagnostic,
    analyze_trial,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_stripe_shape_adapter import (
    native_stripe_geometry_projection_sha256,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


class TwoPrismSimionTrialTest(unittest.TestCase):
    def test_collision_projection_preserves_optional_ip_detector_and_legacy_geometry(self):
        keys = ("mirror_electrodes", "mirror_slot", "mirror_inner_shield_slot", "mirror_ground_shields",
                "mirror_e_closures", "stripe_electrodes", "stripe_slot", "central_ground_electrodes",
                "central_ground_slots", "prism_electrodes", "prism_ground_shields")
        geometry = {key: [] for key in keys}
        legacy = two_prism_simion_trial._collision_geometry_projection(geometry)
        self.assertNotIn("ion_processor_electrodes", legacy)
        self.assertNotIn("detector", legacy)
        geometry.update(ion_processor_electrodes=[dict(name="lp_pull", electrode_id=5, solids=[], cutouts=[])],
                        detector=dict(id=25, box=[-25, -87, 95, 25, -37, 97]))
        projected = two_prism_simion_trial._collision_geometry_projection(geometry)
        self.assertEqual(projected["detector"], geometry["detector"])
        self.assertEqual(projected["ion_processor_electrodes"], geometry["ion_processor_electrodes"])
        projected["detector"]["box"][0] = -99
        projected["ion_processor_electrodes"][0]["solids"].append({})
        self.assertEqual(geometry["detector"]["box"][0], -25)
        self.assertEqual(geometry["ion_processor_electrodes"][0]["solids"], [])

    def test_retired_single_center_schedule_command_is_rejected(self) -> None:
        with patch("sys.argv", ["two_prism_simion_trial", "freeze-pulse-schedule"]), patch("sys.stderr"):
            with self.assertRaises(SystemExit) as caught:
                two_prism_simion_trial.main()
        self.assertEqual(caught.exception.code, 2)

    def _materialize_static_stripe_fixture(self, root, *, mode="comsol_static_scalar_v",
                                          override=None, scale=1., mismatch=None, trajectory_anchor=None,
                                          bank_recipes="default", author_groups=None, parent_plan=None):
        """Exercise the real materializer with small inputs, without solver assets."""
        project = Path(__file__).resolve().parents[2]
        contract = json.loads((project / "config/simion_candidate_two_zone.json").read_text(encoding="utf-8"))
        contract["simion"]["nonaccelerator_scale"] = scale
        if author_groups is not None:
            contract["simion"]["native_corridor"]["response_voltage_groups"] = author_groups
        mirrors, endpoints = [0., -5900., -2500., 4100., 6000.], [100., 80., 0.]
        values = [v * scale for v in mirrors * 2 + [-27., -27., 0., 0., 0., 190., -186., 0., 0., 0.]]
        oa = {"grounded_enclosure": {"component_electrode_id": 1, "local_pa_electrode_id": 1},
              "repeller": {"component_electrode_id": 2, "local_pa_electrode_id": 2},
              "grid_supports": [{"component_electrode_id": i, "local_pa_electrode_id": i} for i in (3, 4)],
              "rings": []}
        binding = dict(mode=mode, authority=dict(analyzer_electrode_voltages_v=values,
                       assembly={"accelerator_resolved_electrodes": oa},
                       component_voltages_v=[dict(component_namespace="accelerator", component_electrode_id=i,
                                                  voltage_v=v) for i, v in enumerate([0., *endpoints], 1)]),
                       sources={}, records={}, grid={}, geometry={}, instances=[{"origin_mm": [-9., -8., -7.]}, {"pa_path": "collision.pa"},
                       {"origin_mm": [0., 0., 0.]}, {"origin_mm": [11., 12., 13.]}], refinement_windows=[], accelerator_front_z_mm=0.,
                       manifest="native_manifest.json", native_solver_numerics={})
        p1 = 190.
        if mismatch == "prism": p1 += 1.
        elif mismatch == "mirror": values[1] += 1.
        elif mismatch == "oa": endpoints[0] += 1.
        paths = {}
        for name, data in {"contract": contract, "mirror": {}, "stripe": {}, "fixed": {},
                           "accelerator": {"role": "orthogonal_accelerator_mrtof_runtime_receipt", "status": "published_standalone_response_bank", "mrtof_projection": {"endpoint_voltages_v": endpoints, "geometry": {"acceleration_direction": "-z", "release_position_in_gap_1_mm": 0.0, "repeller_to_exit_mm": 32.0, "aperture_height_y_mm": 10.0}, "target_axial_energy_per_charge_v": 4372.0}},
                           "provider": {"numerical_domain": {"mesh_mm_per_gu": [.1, .2, .3]}},
                           "composition": {}, "campaign": {}}.items():
            paths[name] = root / f"{name}.json"
            paths[name].write_text(json.dumps(data), encoding="utf-8")
        bank_path = None
        if mode is None and bank_recipes is not None:
            if bank_recipes == "default":
                bank_recipes = [dict(local_id=i, physical_ids=group) for i, group in enumerate(
                    [[2, 7], [3, 8], [4, 9], [5, 10], [11, 12], [13, 14], [16], [17]], 1)]
            bank_path = root / "native_corridor_bank_cache_manifest.json"
            bank_path.write_text(json.dumps(dict(identity=dict(basis_namespace=dict(
                response_recipe=dict(response_recipes=bank_recipes))))), encoding="utf-8")
        trajectory = copy.deepcopy(contract)
        if trajectory_anchor is not None:
            trajectory["accelerator"]["focus_y_anchor"]["project_y_mm"] = trajectory_anchor
        paths["trajectory"] = root / "trajectory.json"
        paths["trajectory"].write_text(json.dumps(trajectory), encoding="utf-8")
        resolved = dict(detector={"box": [-1., -60., -40., 1., -50., -30.]},
                        two_prism_low_field_reference_section={
                            "qualification": "candidate_reference_section__not_a_zero_field_claim",
                            "reference_plane_project_z_mm": 33.,
                            "transit_aperture_project_mm": {"x_mm": [-1., 1.], "y_mm": [-10., 10.]}})
        seed = {"stripe_biases_v": [-20., 50.]}
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial"
        if parent_plan is not None:
            from projects.orthogonal_accelerator.analysis.component_focus_pa_plan import derive
            paths["provider"].write_text(json.dumps(derive(
                project.parent / "orthogonal_accelerator/config/two_zone_component_focus_campaign.json")))
            paths["composition"].write_text(json.dumps(parent_plan))
        geometry_context = (nullcontext() if parent_plan is not None else
                            patch(module + "._resolve_trial_geometry", return_value=resolved))
        origin_context = (nullcontext() if parent_plan is not None else
                          patch(module + ".resolve_accelerator_iob_origin", return_value=[0., 0., 0.]))
        pose_context = (nullcontext() if parent_plan is not None else
                        patch(module + ".resolve_oa_mr_direct_pose", return_value={"exit_project_mm": (0., 0., 0.)}))
        with patch(module + ".load_contract", side_effect=lambda path, **k: json.loads(path.read_text(encoding="utf-8"))), \
             patch(module + "._fixed_mirror_stripe_source_state", return_value=(seed, 5., 4372., mirrors, None)), \
             patch(module + "._p2_handoff_targets", return_value=(0., .1, .001)), \
             patch(module + "._accelerator_energy_binding", return_value=dict(applied_net_gain_parameter_v=4372.,
                   target_axial_energy_per_charge_v=4372., finite_3d_gain_correction_v=0.)), \
             patch(module + "._provider_exit_energy_contract", return_value={"targets_per_charge_v": {"Ey": 5.0}}), \
             patch(module + "._accelerator_ring_voltages", return_value=[]), \
             patch(module + ".load_binding", return_value=binding) as loader, \
             geometry_context as geometry_resolver, origin_context as oa_resolver, pose_context, \
             patch(module + ".resolve_converging_prism_target", return_value={} if mode else None), \
             patch(module + "._mirror_regions", return_value={"negative": [-300., -100.], "positive": [100., 300.]}), \
             patch(module + "._accelerator_geometric_exit_reference", autospec=True, return_value=None) as exit_reference, \
             patch(module + "._scalar_field_lua_fields", return_value=""), \
             patch(module + "._collision_geometry_projection", return_value={}):
            result = two_prism_simion_trial.materialize_trial(
                contract_path=paths["contract"], accelerator_geometry_contract_path=paths["contract"],
                trajectory_contract_path=paths["trajectory"], reviewed_contract_path=paths["contract"],
                mirror_summary_path=paths["mirror"], stripe_summary_path=paths["stripe"],
                fixed_mirror_stripe_authority_path=paths["fixed"], accelerator_receipt_path=paths["accelerator"],
                prism_1_v=p1, prism_2_v=-186., stripe_biases_override_v=override,
                runtime_fast_adjust_enable=False, pulse_accelerator_until_initial_exit=False,
                accelerator_safe_exit_only=False, accelerator_pulse_schedule_path=None, trajectory_profile_id=None,
                fly2_path=root / "source.fly2", sidecar_path=root / "operating.lua", receipt_path=root / "trial.json",
                accelerator_provider_plan_path=paths["provider"], composition_plan_path=paths["composition"],
                accelerator_resolved_campaign_path=paths["campaign"],
                field_binding_path=root / "binding.json" if mode else None,
                native_corridor_cache_manifest_path=bank_path)
            self.assertEqual(loader.call_count, 1 if mode else 0)
            if parent_plan is None:
                self.assertEqual(oa_resolver.call_count, 2 if mode is None and trajectory_anchor is not None else 1)
                self.assertEqual(exit_reference.call_args.kwargs["validated_provider_origin"], [0., 0., 0.])
                self.assertEqual(exit_reference.call_args.kwargs["direct_pose"], {"exit_project_mm": (0., 0., 0.)})
                self.assertEqual(geometry_resolver.call_count, 2 if mode is None and trajectory_anchor is not None else 1)
                self.assertEqual(geometry_resolver.call_args_list[0].args[2], contract)
                if mode is None and trajectory_anchor is not None:
                    self.assertEqual(geometry_resolver.call_args_list[1].args, (contract, trajectory, trajectory))
        return result, (root / "operating.lua").read_text(encoding="utf-8")

    def test_whole_parent_motion_preserves_materialized_local_controls(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_simion_candidate_reference import reframe_oa_mr_plan
        project = Path(__file__).resolve().parents[2]
        parent = json.loads((project.parent.parent / "integrations/config/recipes/oa_mr_two_zone_gap30_plan.json").read_text())
        original = json.dumps(parent, sort_keys=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = None
            for plan in (parent, reframe_oa_mr_plan(parent, ((1, 0, 0), (0, 1, 0), (0, 0, 1))),
                         reframe_oa_mr_plan(parent, ((0, -1, 0), (1, 0, 0), (0, 0, 1)))):
                before = json.dumps(plan, sort_keys=True)
                result, _ = self._materialize_static_stripe_fixture(root, mode=None, parent_plan=plan)
                controls = ((root / "source.fly2").read_bytes(), (root / "operating.lua").read_bytes(),
                            result["resolved_iob_pose"], result["source_position_project_mm"],
                            result["source_direction_project"], result["source_time_of_birth_us"], result["source_clock_basis"])
                if reference is None:
                    reference = controls
                else:
                    self.assertEqual(controls, reference)
                self.assertEqual(json.dumps(plan, sort_keys=True), before)
        self.assertEqual(json.dumps(parent, sort_keys=True), original)

    def test_native_priority_follows_frozen_bank_channels_and_binds_actual_files(self):
        recipes = [dict(local_id=i, physical_ids=group) for i, group in enumerate(
            [[3, 8], [2, 7], [4, 9], [5, 10], [11, 12], [13, 14], [16], [17]], 1)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, _ = self._materialize_static_stripe_fixture(root, mode=None, bank_recipes=recipes[::-1])
            priority = root / "native_corridor_priority_contract.lua"
            text = priority.read_text(encoding="utf-8")
            self.assertIn("corridor_voltage_groups = { { 3, 8 }, { 2, 7 }, { 4, 9 }, { 5, 10 }, "
                          "{ 11, 12 }, { 13, 14 }, { 16 }, { 17 } }", text)
            for record, path in ((result["native_corridor_priority_contract"], priority),
                                 (result["inputs"]["native_corridor_cache_manifest"],
                                  root / "native_corridor_bank_cache_manifest.json")):
                self.assertEqual(record, dict(path=str(path.resolve()), bytes=path.stat().st_size,
                                              sha256=hashlib.sha256(path.read_bytes()).hexdigest()))

    def test_native_priority_does_not_consume_author_or_trajectory_groups(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            left, right = Path(first), Path(second)
            self._materialize_static_stripe_fixture(left, mode=None)
            self._materialize_static_stripe_fixture(right, mode=None, author_groups=[[20]] * 8)
            self.assertEqual((left / "native_corridor_priority_contract.lua").read_bytes(),
                             (right / "native_corridor_priority_contract.lua").read_bytes())

    def test_native_priority_rejects_missing_or_ambiguous_bank_before_outputs(self):
        valid = [dict(local_id=i, physical_ids=[i]) for i in range(1, 9)]
        invalid = [None, valid[:-1]]
        for field, value in (("local_id", 2), ("local_id", 0), ("local_id", True),
                             ("physical_ids", []), ("physical_ids", [1, 1]),
                             ("physical_ids", [2]), ("physical_ids", [21]),
                             ("physical_ids", [True])):
            recipes = copy.deepcopy(valid)
            recipes[0][field] = value
            invalid.append(recipes)
        for recipes in invalid:
            with self.subTest(recipes=recipes), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with self.assertRaises(CandidateContractError):
                    self._materialize_static_stripe_fixture(root, mode=None, bank_recipes=recipes)
                for name in ("source.fly2", "operating.lua", "trial.json", "native_corridor_priority_contract.lua"):
                    self.assertFalse((root / name).exists(), name)

    def test_static_priority_has_only_roles_and_no_unused_bank(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, _ = self._materialize_static_stripe_fixture(root)
            text = (root / "native_corridor_priority_contract.lua").read_text(encoding="utf-8")
            self.assertNotIn("corridor_voltage_groups", text)
            self.assertEqual(text.count("priority_number ="), 4)
            self.assertNotIn("native_corridor_cache_manifest", result["inputs"])

    def test_materialized_iob_pose_preserves_native_and_static_authorities(self):
        for mode in (None, "native_static_pa", "comsol_static_scalar_v"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                result, _ = self._materialize_static_stripe_fixture(Path(directory), mode=mode)
                pose = result["resolved_iob_pose"]
                self.assertEqual(pose["origins_mm"]["accelerator"], [0., 0., 0.])
                self.assertEqual(pose["mesh_mm_per_gu"]["accelerator"], [.1, .2, .3])
                self.assertEqual(pose["analyzer_geometry_authority"],
                                 mode + "_frozen_resolved_geometry" if mode else "reviewed_analyzer_contract")
                if mode:
                    self.assertEqual(pose["origins_mm"]["analyzer"], [-9., -8., -7.])
                    self.assertEqual(pose["origins_mm"]["detector"], [11., 12., 13.])
                else:
                    c = json.loads((Path(directory) / "contract.json").read_text())
                    spans = c["simion"]
                    self.assertEqual(pose["origins_mm"]["analyzer"], spans["analyzer_pa_origin_mm"])
                    self.assertEqual(pose["origins_mm"]["detector"],
                                     [v - spans["detector_pa_span_mm"][i] / 2 for i, v in enumerate([0., -55., -35.])])
        with tempfile.TemporaryDirectory() as directory:
            self._materialize_static_stripe_fixture(Path(directory), mode=None, trajectory_anchor=-51.)

    def test_static_stripe_default_and_explicit_match_use_field_before_clean_phase(self):
        for mode in ("comsol_static_scalar_v", "native_static_pa"):
            for scale in (1., 2.):
                for override in (None, (-27., 0.)):
                    with self.subTest(mode=mode, scale=scale, override=override), tempfile.TemporaryDirectory() as directory:
                        result, lua = self._materialize_static_stripe_fixture(Path(directory), mode=mode,
                                                                             override=override, scale=scale)
                        self.assertEqual(result["stripe_biases_v"], [-27., 0.])
                        self.assertEqual(result["analyzer_electrode_voltages_v"][10:14], [-27. * scale] * 2 + [0.] * 2)
                        self.assertIn("stripe_biases_v = { -27, 0 }", lua)
                        self.assertEqual(result["seed_theory_provenance"]["seed_stripe_biases_v"], [-20., 50.])

    def test_static_stripe_explicit_mismatch_and_other_voltage_mismatches_still_fail(self):
        for mode in ("comsol_static_scalar_v", "native_static_pa"):
            for mismatch, override in ((None, (-26., 0.)), ("prism", None), ("mirror", None), ("oa", None)):
                with self.subTest(mode=mode, mismatch=mismatch), tempfile.TemporaryDirectory() as directory:
                    with self.assertRaisesRegex(ValueError, "voltages differ"):
                        self._materialize_static_stripe_fixture(Path(directory), mode=mode,
                                                               override=override, mismatch=mismatch)

    def test_adjustable_flight_without_field_binding_keeps_seed_stripes(self):
        with tempfile.TemporaryDirectory() as directory:
            result, lua = self._materialize_static_stripe_fixture(Path(directory), mode=None)
            self.assertEqual(result["analyzer_electrode_voltages_v"],
                             [0., -5900., -2500., 4100., 6000.] * 2
                             + [-20., -20., 50., 50., 0., 190., -186., 0., 0., 0.])
            self.assertEqual(result["stripe_biases_v"], [-20., 50.])
            self.assertIn("stripe_biases_v = { -20, 50 }", lua)

    def test_converging_clean_phase_energy_uses_actual_state_and_source_authority(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_dual_stripe_l0_math import converging_prism_fixture
        _, _, target = converging_prism_fixture()
        trial = {"prism_handoff_target": target, "stripe_biases_v": [-27.36410265968425, 0.],
                 "particle_mass_th": 524., "charge_state": 1,
                 "source_center_state": {"mass_th": 524., "charge_e": 1}}
        events = [{"kind": "pre_origin_positive_mirror_turn", "ion": 1, "t_us": 1.},
                  {"kind": "central_plane_directional", "ion": 1, "n": 1, "direction_z": -1,
                   "t_us": 2., "x_mm": 0., "y_mm": 9.29765627041, "z_mm": 0.,
                   "vx_mm_us": 0., "vy_mm_us": 1.32963441921, "vz_mm_us": -40.1278924103}]
        observe = two_prism_simion_trial._converging_prism_energy_observation
        result = observe(events, trial)
        self.assertAlmostEqual(result[two_prism_simion_trial.CONVERGING_PRISM_ENERGY_RESIDUAL], -.36835835613722345)
        self.assertEqual(result["first_clean_phase_state"]["position_mm"], [0., 9.29765627041, 0.])
        changed = copy.deepcopy(trial)
        changed["stripe_biases_v"][0] -= 1.
        self.assertNotEqual(observe(events, changed)["design_potential_delta_v"], result["design_potential_delta_v"])
        for kind in ("missing_plane", "missing_z", "wrong_z", "duplicate", "order", "dirty", "charge", "mass", "s2"):
            bad_events, bad_trial = copy.deepcopy(events), copy.deepcopy(trial)
            if kind == "missing_plane": bad_events.pop()
            elif kind == "missing_z": bad_events[-1].pop("z_mm")
            elif kind == "wrong_z": bad_events[-1]["z_mm"] = 10.
            elif kind == "duplicate": bad_events.append(copy.deepcopy(bad_events[-1]))
            elif kind == "order": bad_events[-1]["t_us"] = .5
            elif kind == "dirty": bad_events[-1]["y_mm"] = 0.
            elif kind == "charge": bad_trial["charge_state"] = -1
            elif kind == "mass": bad_trial["source_center_state"]["mass_th"] = 523.
            else: bad_trial["stripe_biases_v"][1] = 1.
            with self.subTest(kind=kind), self.assertRaises(CandidateContractError):
                observe(bad_events, bad_trial)

    def test_shared_clean_action_keeps_nonzero_x_and_is_not_physical_potential(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_dual_stripe_l0_math import converging_prism_fixture
        _,_,target=converging_prism_fixture()
        state=dict(position_mm=[.03,9.29765627041,0.],velocity_mm_per_us=[.019,1.32963441921,-40.1278924103])
        original=copy.deepcopy(state)
        result=two_prism_simion_trial.clean_phase_effective_slow_action(state=state,mass_amu=524,charge_state=1,
            target=target,stripe_1_voltage_v=-27.36410265968425)
        self.assertEqual(state,original)
        self.assertNotIn("physical_potential_v",result)
        self.assertIn("design_effective_potential_delta_v",result)
        self.assertAlmostEqual(result[two_prism_simion_trial.CONVERGING_PRISM_ENERGY_RESIDUAL],-.36835835613722345)

    def test_launcher_preloads_overlay_occupancy_without_refine_save_or_duplicate_open(self) -> None:
        lua = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "SIMION-2020/lua.exe"
        if not lua.is_file():
            self.skipTest("plain vendor Lua unavailable; no commercial execution")
        launcher = Path(__file__).resolve().parents[2] / "simion/run_iob_flight.lua"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            iob = root/"joint.iob"
            for suffix in ("lua","fly2"):
                iob.with_suffix('.'+suffix).write_text('')
            iob.with_suffix('.operating_point.lua').write_text("return {accelerator_provider='dual_pressure_rectilinear_ion_processor',"
                "field_assembly_verified=true,static_field={collision_pa_path='C:/frozen/collision.pa',"
                "collision_geometry_pa_paths={'C:/ip/ip_collision.pa','C:/detector/detector.pa',"
                "'c:/IP/ip_collision.pa','c:/FROZEN/collision.pa'},"
                "collision_overlay={schema_version=1,role='mrtof_analyzer_collision_overlay',pa_path='C:/patch/patch.pa'}}}")
            harness = root/"fixture.lua"
            harness.write_text(r'''
local launcher,iob,mode=unpack(arg)
local function forbidden() error('occupancy may not be refined, saved, closed or discarded') end
local coarse={path='c:\\FROZEN\\collision.pa',refinable=true,refined=false,save=forbidden,refine=forbidden}
local patch={path='C:/patch/patch.pa',refinable=true,refined=false,save=forbidden,refine=forbidden}
local ip={path='C:/ip/ip_collision.pa',refinable=true,refined=false,save=forbidden,refine=forbidden}
local detector={path='C:/detector/detector.pa',refinable=true,refined=false,save=forbidden,refine=forbidden}
local unrelated={path='C:/different/patch.pa',refinable=true}
local inventory={coarse,unrelated}
if mode~='cold' then inventory[#inventory+1]=patch end
if mode=='all_warm' then inventory[#inventory+1]=ip;inventory[#inventory+1]=detector end
if mode=='ambiguous' then inventory[#inventory+1]={path='c:\\PATCH\\patch.pa'} end
local opens,commands=0,0
function inventory:open(path)
  opens=opens+1
  for _,pa in ipairs({patch,ip,detector}) do
    if path==pa.path then self[#self+1]=pa;return pa end
  end
  error('coarse and duplicate paths must be reused by full normalized path')
end
inventory.close=forbidden
simion={pas=inventory,command=function(command)
  commands=commands+1
  assert(command:match('--remove%-pas=0'))
  assert(not coarse.refinable and not patch.refinable)
  assert(not ip.refinable and not detector.refinable)
  assert(not coarse.refined and not patch.refined and not ip.refined and not detector.refined and unrelated.refinable)
  assert(#inventory==5,'each carrier must occur once in resident inventory')
end}
arg={iob};local ok,err=pcall(assert(loadfile(launcher)))
if mode=='ambiguous' then
  assert(not ok and err:match('ambiguous collision PA inventory') and commands==0 and opens==0)
else
  local expected_opens=mode=='cold' and 3 or (mode=='warm' and 2 or 0)
  assert(ok,err);assert(commands==1 and opens==expected_opens)
end
print('OVERLAY_COLLISION_PRELOAD_PASS')
''')
            for mode in ('cold','warm','all_warm','ambiguous'):
                with self.subTest(mode=mode):
                    actual = subprocess.run([str(lua),str(harness),str(launcher),str(iob),mode],
                                            cwd=root,capture_output=True,text=True,timeout=30)
                    self.assertEqual(actual.returncode,0,actual.stdout+actual.stderr)
                    self.assertIn('OVERLAY_COLLISION_PRELOAD_PASS',actual.stdout)

    def test_launcher_preloads_only_static_ordinary_collision_without_saving(self) -> None:
        lua = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "SIMION-2020/lua.exe"
        if not lua.is_file():
            self.skipTest("standalone vendor Lua unavailable; no commercial execution")
        launcher = Path(__file__).resolve().parents[2] / "simion/run_iob_flight.lua"
        fixture = r'''
local launcher, iob, expected = arg[1], arg[2], arg[3]
local calls,commands = 0,0
local collision='C:/frozen/collision.pa'
-- SIMION2020 Help: filename is basename; path is the full normalized path.
local pa = {filename='collision.pa',path=collision,refinable=true,refined=false}
local inventory={}
local other={filename='collision.pa',path='C:/different/collision.pa',refinable=true,refined=false}
if expected=='warm' then
 pa.path='c:\\FROZEN\\collision.pa';inventory[1]=pa
elseif expected=='same_basename' then inventory[1]=other
elseif expected=='ambiguous' then
 inventory[1]=pa;inventory[2]={filename='collision.pa',path='c:/FROZEN/collision.pa',refinable=true}
end
inventory.open=function(self,path)
  assert(path==collision);calls=calls+1;self[#self+1]=pa;return pa
end
inventory.close=function() error('Must not discard warmed PA inventory') end
simion = {pas=inventory,command=function(command)
  commands=commands+1
  assert(command:match('--retain%-trajectories=0'))
  local ordinary=expected=='ordinary' or expected=='warm' or expected=='same_basename'
  assert((command:match('--remove%-pas=0')~=nil)==ordinary)
  if ordinary then
   local matching=0
   for i=1,#inventory do
    if inventory[i].path:gsub('\\','/'):lower()==collision:lower() then matching=matching+1 end
   end
   assert(matching==1,'Multiple matching filenames in PA list')
  end
end}
arg={iob}
local ok,err=pcall(assert(loadfile(launcher)))
if expected=='ambiguous' then
 assert(not ok and err:match('ambiguous collision PA inventory'))
 assert(calls==0 and commands==0,'Ambiguity must fail before opening or Fly')
 print('COLLISION_PRELOAD_PASS');return
end
assert(ok,err)
assert(calls==((expected=='ordinary' or expected=='same_basename') and 1 or 0))
assert(commands==1)
assert(pa.refined==false)
local active=expected=='ordinary' or expected=='warm' or expected=='same_basename'
assert(pa.refinable==not active)
assert(other.refinable==true,'Same basename in another directory was modified')
print('COLLISION_PRELOAD_PASS')
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness = root / "fixture.lua"
            harness.write_text(fixture, encoding="utf-8")
            iob = root / "trial.iob"
            for extension in ("lua", "fly2"):
                iob.with_suffix("." + extension).write_text("", encoding="utf-8")
            for name, operating in (
                ("ordinary", "return {static_field={collision_pa_path='C:/frozen/collision.pa'}}"),
                ("warm", "return {static_field={collision_pa_path='C:/frozen/collision.pa'}}"),
                ("same_basename", "return {static_field={collision_pa_path='C:/frozen/collision.pa'}}"),
                ("ambiguous", "return {static_field={collision_pa_path='C:/frozen/collision.pa'}}"),
                ("legacy", "return {static_field={collision_pa_path='frozen collision.pa0'}}"),
                ("native", "return {}"),
            ):
                with self.subTest(name=name):
                    iob.with_suffix(".operating_point.lua").write_text(operating, encoding="utf-8")
                    result = subprocess.run([str(lua), str(harness), str(launcher), str(iob), name],
                                            cwd=root,
                                            capture_output=True, text=True, timeout=10, check=True)
                    self.assertIn("COLLISION_PRELOAD_PASS", result.stdout)
                    if name in {"warm", "same_basename", "ambiguous"}:
                        self.assertIn("filename=collision.pa path=", result.stdout)
                    if name == "warm":
                        self.assertIn("exact_match=true", result.stdout)
                        self.assertIn("existing_pa_reused=true", result.stdout)
                    elif name == "same_basename":
                        self.assertIn("path=C:/different/collision.pa exact_match=false", result.stdout)
                        self.assertIn("existing_pa_reused=false", result.stdout)

    def test_launcher_load_workbench_preserves_preload_without_flying_or_saving(self):
        lua = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "SIMION-2020/lua.exe"
        if not lua.is_file():
            self.skipTest("plain vendor Lua unavailable; no commercial execution")
        launcher = Path(__file__).resolve().parents[2] / "simion/run_iob_flight.lua"
        fixture = r'''
local launcher,iob,mode,override=unpack(arg)
local function forbidden() error('load-workbench must not Fly, Refine, save or discard PAs') end
local collision={path='C:/frozen/collision.pa',refinable=true,refine=forbidden,save=forbidden}
local ip={path='C:/frozen/ip.pa',refinable=true,refine=forbidden,save=forbidden}
local detector={path='C:/frozen/detector.pa',refinable=true,refine=forbidden,save=forbidden}
local unrelated={path='C:/other/collision.pa',refinable=true}
local inventory={unrelated}
if mode=='warm' then inventory[#inventory+1]=collision end
if mode=='ambiguous' then inventory[#inventory+1]=collision;inventory[#inventory+1]=collision end
local opens,loads,particles=0,0,0
function inventory:open(path)
  opens=opens+1
  for _,pa in ipairs({collision,ip,detector}) do
    if pa.path==path then self[#self+1]=pa;return pa end
  end
  error('unexpected PA path: '..path)
end
inventory.close=forbidden
local wb={save=forbidden}
function wb:load(path)
  assert(path==iob and not collision.refinable and unrelated.refinable)
  loads=loads+1
  if mode=='ip' then assert(not ip.refinable and not detector.refinable) end
  if mode=='lost_flag' then collision.refinable=true end
  if mode=='replaced' then inventory[#inventory]={path=collision.path,refinable=false} end
end
function wb:load_particles(path)
  assert(path==(override=='yes' and iob..'.explicit.fly2' or iob:gsub('%.iob$','.fly2')))
  particles=particles+1
end
simion={pas=inventory,wb=wb,command=forbidden}
arg={iob,override=='yes' and iob..'.explicit.fly2' or nil,'load-workbench'}
local ok,err=pcall(assert(loadfile(launcher)))
if mode=='ambiguous' then
  assert(not ok and err:match('ambiguous collision PA inventory') and loads==0 and opens==0)
elseif mode=='lost_flag' or mode=='replaced' then
  assert(not ok and err:match('Workbench load replaced its protected collision PA'))
else
  assert(ok,err);assert(loads==1 and particles==1)
  assert(opens==(mode=='warm' and 0 or (mode=='ip' and 3 or 1)))
end
print('WORKBENCH_LOAD_PRELOAD_PASS')
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            iob = root / 'joint.iob'
            for suffix in ('.lua', '.fly2', '.iob.explicit.fly2'):
                (root / ('joint' + suffix)).write_text('', encoding='utf-8')
            harness = root / 'load_fixture.lua'
            harness.write_text(fixture, encoding='utf-8')
            for mode in ('oa', 'ip', 'warm', 'ambiguous', 'lost_flag', 'replaced'):
                extra = ",collision_geometry_pa_paths={'C:/frozen/ip.pa','C:/frozen/detector.pa'}" if mode == 'ip' else ''
                iob.with_suffix('.operating_point.lua').write_text(
                    "return {static_field={collision_pa_path='C:/frozen/collision.pa'" + extra + '}}', encoding='utf-8')
                for override in ('yes', 'no'):
                    with self.subTest(mode=mode, override=override):
                        actual = subprocess.run([str(lua), str(harness), str(launcher), str(iob), mode, override],
                                                cwd=root, capture_output=True, text=True, timeout=10)
                        self.assertEqual(actual.returncode, 0, actual.stdout + actual.stderr)
                        self.assertIn('WORKBENCH_LOAD_PRELOAD_PASS', actual.stdout)

    def test_center_view_validates_actual_source_not_particle_count(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial import _validate_center_view_source
        _validate_center_view_source(None, None)
        def state(x, dx):
            return dict(position_workbench_mm=[x, 1., 2.], direction_workbench=[dx, 1., 0.])
        _validate_center_view_source(None, {'states': [state(0., 0.), state(0., 0.)]})
        for states in ([state(.01, 0.)], [state(0., .01)], []):
            with self.assertRaisesRegex(ValueError, 'x=0 and vx=0'):
                _validate_center_view_source(None, {'states': states})

    def test_static_voltage_record_canonicalizes_consumed_authority_after_validation(self):
        actual = [0.] * 20
        actual[15] = 189.86254642087434
        binding = {"authority": {"analyzer_electrode_voltages_v": actual,
                   "assembly": {"accelerator_resolved_electrodes": {
                       "grounded_enclosure": {"component_electrode_id": 1, "local_pa_electrode_id": 1},
                       "repeller": {"component_electrode_id": 2, "local_pa_electrode_id": 2},
                       "grid_supports": [], "rings": []}},
                   "component_voltages_v": [
                       {"component_namespace": "accelerator", "component_electrode_id": 1, "voltage_v": 0.},
                       {"component_namespace": "accelerator", "component_electrode_id": 2, "voltage_v": 100.}]}}
        requested = list(actual)
        requested[15] = 189.862546420874
        consume = two_prism_simion_trial._static_consumed_analyzer_voltages
        result = consume(binding, requested, [0., 100.], pulse_requested=False)
        self.assertEqual(result, actual)
        self.assertIsNot(result, actual)
        self.assertNotEqual(requested[15], result[15])
        requested[15] += 2e-9
        with self.assertRaisesRegex(ValueError, "voltages differ"):
            consume(binding, requested, [0., 100.], pulse_requested=False)

    def test_static_field_receipt_and_lua_preserve_native_grid_and_solver(self) -> None:
        binding = {
            "mode": "native_static_pa", "manifest": "native/manifest.json",
            "sources": {"scalar_pa": "native/static.pa", "surface": "native/static.pa-surf"},
            "records": {"scalar_pa": {"bytes": 100}, "surface": {"bytes": 20}},
            "grid": {"origin_mm": [0, -100, -325], "pitch_mm": [.25, .2, .2],
                     "dimensions": [91, 2451, 3251]},
            "refinement_windows": [],
            "native_solver_numerics": {"solver": "SIMION2020", "refine_stopping": "contract_convergence",
                                       "convergence_v": 1e-5, "surface": "fractional",
                                       "boundary_mode": "grounded_enclosure"},
        }
        before = copy.deepcopy(binding)
        receipt = two_prism_simion_trial._static_field_receipt(binding, Path("binding.json"))
        self.assertEqual(receipt["mode"], "native_static_pa")
        self.assertEqual(receipt["grid"], binding["grid"])
        self.assertEqual(receipt["manifest"], binding["manifest"])
        self.assertEqual(receipt["native_solver_numerics"], binding["native_solver_numerics"])
        self.assertIsNot(receipt["native_solver_numerics"], binding["native_solver_numerics"])
        self.assertEqual(json.loads(json.dumps(receipt))["native_solver_numerics"]["convergence_v"], 1e-5)
        self.assertNotIn("export_manifest", receipt)
        lua = two_prism_simion_trial._scalar_field_lua_fields(binding)
        self.assertIn("mode = 'native_static_pa'", lua)
        self.assertIn("dimensions = { 91, 2451, 3251 }", lua)
        self.assertNotIn("valid_pa", lua)
        self.assertEqual(binding, before)
        ordinary = {**binding, "mode": "comsol_static_scalar_v"}
        ordinary.pop("manifest")
        self.assertEqual(two_prism_simion_trial._static_field_receipt(ordinary, Path("ordinary.json"))["mode"],
                         "comsol_static_scalar_v")
        self.assertNotIn("native_solver_numerics",
                         two_prism_simion_trial._static_field_receipt(ordinary, Path("ordinary.json")))

    def test_seed_theory_qualification_tracks_actual_mirror_and_stripe_values(self) -> None:
        seed_mirror = (0.0, -5900.0, -2600.0, 4200.0, 6000.0)
        seed_stripe = (-27.0, 54.0)
        for actual_mirror, actual_stripe, changed in (
            (list(seed_mirror), list(seed_stripe), (False, False)),
            ([0.0, -5901.0, -2600.0, 4200.0, 6000.0], list(seed_stripe), (True, False)),
            (list(seed_mirror), [-27.1, 54.2], (False, True)),
        ):
            with self.subTest(changed=changed):
                before = (actual_mirror.copy(), actual_stripe.copy())
                provenance = _seed_theory_provenance(
                    seed_mirror, seed_stripe, actual_mirror, actual_stripe,
                )
                self.assertEqual(provenance["seed_authority_scope"],
                                 "historical_mirror_stripe_initializer_only")
                self.assertEqual(provenance["seed_mirror_voltages_v"], list(seed_mirror))
                self.assertEqual(provenance["seed_stripe_biases_v"], list(seed_stripe))
                self.assertEqual((provenance["mirror_changed_from_seed"],
                                  provenance["stripe_changed_from_seed"]), changed)
                self.assertEqual(provenance["actual_theory_qualification"],
                    "not_rederived_after_mirror_or_stripe_change" if any(changed) else
                    "seed_initializer_theory_only__finite_3d_and_numerical_qualification_pending")
                self.assertEqual((actual_mirror, actual_stripe), before)
                self.assertNotIn("predicted_period_ratio", provenance)

    def test_formal_volume_transverse_reference_does_not_invent_a_center(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            table = Path(directory) / "source.csv"
            table.write_text(
                "particle_id,mass_th,kinetic_energy_ev,x_mm,direction_x\n"
                "1,524,5,0.25,0\n2,524,5,-0.25,0\n",
                encoding="utf-8",
            )
            formal = _source_transverse_reference(
                bunch_source={"state_table": {"path": str(table)}},
                bunch_selection=None,
                mass_th=524.0,
                charge_state=1,
                slow_energy_per_charge_v=5.0,
            )
            self.assertIsNone(formal["center_particle_id"])
            self.assertIsNone(formal["center_x_mm"])
            self.assertEqual(formal["mean_x_mm"], 0.0)

    def test_transverse_reference_uses_declared_center_particle_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            table = Path(directory) / "source.csv"
            table.write_text(
                "particle_id,mass_th,kinetic_energy_ev,x_mm,direction_x\n"
                "1,524,5,0.25,0\n7,524,5,-0.1,0\n",
                encoding="utf-8",
            )
            controlled = _source_transverse_reference(
                bunch_source={
                    "state_table": {"path": str(table)},
                    "center_particle_state": {"particle_id": 7},
                },
                bunch_selection=None,
                mass_th=524.0,
                charge_state=1,
                slow_energy_per_charge_v=5.0,
            )
            self.assertEqual(controlled["center_particle_id"], 7)
            self.assertEqual(controlled["center_x_mm"], -0.1)

    def test_provider_exit_energy_contract_projects_three_targets_and_tolerances(self) -> None:
        projection = {
            "target_axial_energy_per_charge_v": 4000.0,
            "accepted_release": {"slow_energy_center_per_charge_v": 5.0},
            "provider_exit_energy_acceptance": {
                "passed": True,
                "target_axial_energy_per_charge_v": 4000.0,
                "tolerances": {
                    "maximum_exit_transverse_energy_error_per_charge_v": 0.01,
                    "maximum_exit_slow_energy_error_per_charge_v": 0.02,
                    "maximum_exit_axial_energy_error_per_charge_v": 0.03,
                    "maximum_exit_transverse_velocity_bias_mm_per_us": 0.0001,
                },
                "center_particle": {
                    "source_transverse_energy_per_charge_v": 0.0,
                    "source_slow_energy_per_charge_v": 5.0,
                    "expected_exit_axial_energy_per_charge_v": 4000.0,
                },
            },
        }
        contract = _provider_exit_energy_contract(projection)
        self.assertEqual(contract["targets_per_charge_v"], {"Ex": 0.0, "Ey": 5.0, "Ez": 4000.0})
        self.assertEqual(
            contract["absolute_tolerances_per_charge_v"],
            {"Ex": 0.01, "Ey": 0.02, "Ez": 0.03},
        )
        self.assertEqual(
            contract["maximum_exit_transverse_velocity_bias_mm_per_us"], 0.0001,
        )

    def test_geometric_exit_validation_uses_all_declared_particles(self) -> None:
        mass = 524.0
        component = two_prism_simion_trial._component_energy_per_charge_v
        expected = {
            "Ex": component(mass, 1.0, 0.0),
            "Ey": component(mass, 1.0, 1000.0),
            "Ez": component(mass, 1.0, -10000.0),
        }
        reference = {
            "expected_particle_ids": [1, 2],
            "exit_plane_project_z_mm": 0.0,
            "exit_plane_tolerance_mm": 0.1,
            "absolute_tolerances_per_charge_v": {"Ex": 0.05, "Ey": 0.05, "Ez": 0.05},
            "particle_rows": [
                {"particle_id": particle_id,
                 "expected_exit_component_energy_per_charge_v": expected}
                for particle_id in (1, 2)
            ],
        }
        events = [
            {"kind": "accelerator_geometric_exit", "ion": 1, "t_us": 1.0,
             "x_mm": 0.0, "y_mm": -55.0, "z_mm": 0.0,
             "vx_mm_us": 0.0, "vy_mm_us": 1.0, "vz_mm_us": -10.0},
            {"kind": "accelerator_geometric_exit", "ion": 2, "t_us": 1.1,
             "x_mm": 0.1, "y_mm": -55.1, "z_mm": 0.0,
             "vx_mm_us": 0.0, "vy_mm_us": 1.0, "vz_mm_us": -11.0},
        ]
        result = _accelerator_geometric_exit_validation(
            events=events, reference=reference, expected_particle_ids=[1, 2],
            mass_th=mass, charge_state=1.0,
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["observed_particle_count"], 2)
        self.assertEqual(result["out_of_tolerance_particle_ids"]["Ez"], [2])
        self.assertFalse(result["passed"])
        events[1]["vz_mm_us"] = -10.0
        passed = _accelerator_geometric_exit_validation(
            events=events, reference=reference, expected_particle_ids=[1, 2],
            mass_th=mass, charge_state=1.0,
        )
        self.assertEqual(passed["status"], "passed")
        self.assertTrue(passed["passed"])

    def test_geometric_exit_reference_uses_provider_exit_origin_coordinates(self) -> None:
        provider_plan = {
            "numerical_domain": {"local_exit_z_mm": 6.0},
            "requirements": {"placement": {"global_exit_z_mm": 0.0}},
            "layout": {
                "geometry_profile_id": "closed_two_zone_compact_mr_axial_r3_gap1_4mm",
            },
        }
        campaign = {
            "role": "orthogonal_accelerator_component_focus_campaign",
            "geometry_profile_id": "closed_two_zone_compact_mr_axial_r3_gap1_4mm",
            "release_spec": {
                "frame_id": "orthogonal_accelerator_exit_origin_v1",
                "species": {"mass_amu": 524.0, "charge_state": 1},
            },
            "operating_point": {
                "electrode_voltages_v": [0.0, 4749.0, 3995.0, 0.0],
                "finite_3d_gain_correction_v": 0.0,
            },
            "acceptance": {
                "focus_plane_tolerance_mm": 0.1,
                "maximum_exit_transverse_energy_error_per_charge_v": 0.05,
                "maximum_exit_slow_energy_error_per_charge_v": 0.05,
                "maximum_exit_axial_energy_error_per_charge_v": 0.05,
            },
        }
        selection = {
            "particle_ids": [7],
            "states": [{
                "mass_th": 524.0, "charge_e": 1, "kinetic_energy_ev": 5.3,
                "position_workbench_mm": [0.2, -56.35182899425077, 32.0],
                "direction_workbench": [0.0, 1.0, 0.0],
            }],
        }
        with patch.object(two_prism_simion_trial, "resolve_accelerator_iob_origin", return_value=(0.0, -72.25, -6.0)), \
             patch.object(two_prism_simion_trial, "resolve_oa_mr_direct_pose", return_value={"exit_project_mm": (0.0, -55.0, 0.0)}):
            result = _accelerator_geometric_exit_reference(
                contract={}, provider_plan=provider_plan, resolved_campaign=campaign,
                bunch_source=None, bunch_selection=selection, mass_th=524.0,
                charge_state=1, slow_energy_per_charge_v=5.3,
                source_origin_project_mm=(0.0, -55.0, 32.0), composition_plan={}, local_scope=None,
                direct_pose={"exit_project_mm": (0.0, -55.0, 0.0)},
            )
        row = result["particle_rows"][0]
        self.assertEqual(result["source_frame_origin_project_mm"], [0.0, -55.0, 0.0])
        self.assertAlmostEqual(row["source_position_provider_mm"][1], -1.35182899425077)
        self.assertEqual(row["source_position_provider_mm"][2], 32.0)
        self.assertEqual(result["expected_particle_ids"], [7])
        from projects.orthogonal_accelerator.analysis.component_focus_pa_plan import derive
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_system_geometry import resolve_oa_mr_direct_pose
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_simion_candidate_reference import reframe_oa_mr_plan
        project = Path(__file__).resolve().parents[2]
        actual_provider = derive(project.parent / "orthogonal_accelerator/config/two_zone_component_focus_campaign.json")
        actual_contract = two_prism_simion_trial.load_contract(project / "config/simion_candidate_two_zone.json")
        parent = json.loads((project.parent.parent / "integrations/config/recipes/oa_mr_two_zone_gap30_plan.json").read_text())
        original_states = copy.deepcopy(selection)
        for plan in (parent, reframe_oa_mr_plan(parent, ((1, 0, 0), (0, 1, 0), (0, 0, 1))),
                     reframe_oa_mr_plan(parent, ((0, -1, 0), (1, 0, 0), (0, 0, 1)))):
            before = json.dumps(plan, sort_keys=True)
            direct = resolve_oa_mr_direct_pose(actual_provider, plan)
            actual = _accelerator_geometric_exit_reference(
                contract=actual_contract, provider_plan=actual_provider, resolved_campaign=campaign,
                bunch_source=None, bunch_selection=selection, mass_th=524., charge_state=1,
                slow_energy_per_charge_v=5.3, source_origin_project_mm=(0., -55., 32.),
                composition_plan=plan, local_scope=None, direct_pose=direct)
            self.assertEqual(json.dumps(actual, sort_keys=True), json.dumps(result, sort_keys=True))
            self.assertEqual(selection, original_states)
            self.assertEqual(json.dumps(plan, sort_keys=True), before)
        self.assertGreater(
            row["expected_exit_component_energy_per_charge_v"]["Ez"], 0.0,
        )

        # Static-field placement already passed the same provider/contract resolver.
        with patch.object(two_prism_simion_trial, "resolve_accelerator_iob_origin",
                          side_effect=AssertionError("duplicate OA pose resolution")), \
             patch.object(two_prism_simion_trial, "resolve_oa_mr_direct_pose", return_value={"exit_project_mm": (0.0, -55.0, 0.0)}):
            reused = _accelerator_geometric_exit_reference(
                contract={}, provider_plan=provider_plan, resolved_campaign=campaign,
                bunch_source=None, bunch_selection=selection, mass_th=524.0,
                charge_state=1, slow_energy_per_charge_v=5.3,
                source_origin_project_mm=(0.0, -55.0, 32.0), composition_plan={}, local_scope=None,
                direct_pose={"exit_project_mm": (0.0, -55.0, 0.0)},
                validated_provider_origin=(0.0, -72.25, -6.0),
            )
            self.assertEqual(reused, result)
            with self.assertRaisesRegex(CandidateContractError, "exit-plane mapping differs"):
                _accelerator_geometric_exit_reference(
                    contract={}, provider_plan=provider_plan, resolved_campaign=campaign,
                    bunch_source=None, bunch_selection=selection, mass_th=524.0,
                    charge_state=1, slow_energy_per_charge_v=5.3,
                    source_origin_project_mm=(0.0, -55.0, 32.0), composition_plan={}, local_scope=None,
                    direct_pose={"exit_project_mm": (0.0, -55.0, 0.0)},
                    validated_provider_origin=(0.0, -72.25, -5.0),
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            states = [
                {
                    "particle_id": particle_id, "tob_us": 0.0,
                    "mass_th": 524.0, "charge_e": 1,
                    "kinetic_energy_ev": 5.3,
                    "position_workbench_mm": [
                        0.1 * particle_id, -55.0 - 0.1 * particle_id, 32.0,
                    ],
                    "direction_workbench": [0.0, 1.0, 0.0],
                }
                for particle_id in range(1, 101)
            ]
            receipt_path = root / "receipt.json"
            receipt = materialize_bunch_source(
                states=states, mother_particle_count=100,
                source_profile_id="test", frame_id="mrtof_workbench",
                state_table_path=root / "states.csv", fly2_path=root / "source.fly2",
                receipt_path=receipt_path, cohort_role="formal_volume",
            )
            typed_selection = two_prism_simion_trial.resolve_bunch_source_interval(
                receipt_path=receipt_path, particle_id_min=1, particle_id_max=100,
            )
            with patch.object(two_prism_simion_trial, "resolve_accelerator_iob_origin", return_value=(0.0, -72.25, -6.0)), \
                 patch.object(two_prism_simion_trial, "resolve_oa_mr_direct_pose", return_value={"exit_project_mm": (0.0, -55.0, 0.0)}):
                full = _accelerator_geometric_exit_reference(
                    contract={}, provider_plan=provider_plan,
                    resolved_campaign=campaign, bunch_source=receipt,
                    bunch_selection=typed_selection, mass_th=524.0,
                    charge_state=1, slow_energy_per_charge_v=5.3,
                    source_origin_project_mm=(0.0, -55.0, 32.0), composition_plan={}, local_scope=None,
                    direct_pose={"exit_project_mm": (0.0, -55.0, 0.0)},
                )
            self.assertEqual(full["expected_particle_ids"], list(range(1, 101)))
            self.assertAlmostEqual(
                full["particle_rows"][0]["source_position_provider_mm"][1], -0.1,
            )

    def test_short_exit_analysis_failure_returns_nonzero(self) -> None:
        observed = {
            "execution_scope": "accelerator_safe_exit_envelope_only",
            "status": "accelerator_geometric_exit_invalid",
        }
        with (
            patch.object(two_prism_simion_trial, "analyze_trial", return_value=observed),
            patch("sys.argv", [
                "two_prism_simion_trial.py", "analyze",
                "--log", "flight.log", "--trial-receipt", "trial.json",
                "--output", "observation.json",
            ]),
        ):
            self.assertEqual(two_prism_simion_trial.main(), 1)

    def test_short_exit_scope_rejects_energy_residual_without_detector_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mass = 100.0
            component = two_prism_simion_trial._component_energy_per_charge_v
            expected = {
                "Ex": component(mass, 1.0, 0.0),
                "Ey": component(mass, 1.0, 1000.0),
                "Ez": component(mass, 1.0, -10000.0),
            }
            reference = {
                "expected_particle_ids": [1, 2],
                "exit_plane_project_z_mm": 0.0,
                "exit_plane_tolerance_mm": 0.1,
                "absolute_tolerances_per_charge_v": {
                    "Ex": 0.05, "Ey": 0.05, "Ez": 0.05,
                },
                "particle_rows": [
                    {"particle_id": particle_id,
                     "expected_exit_component_energy_per_charge_v": expected}
                    for particle_id in (1, 2)
                ],
            }
            trial = root / "trial.json"
            trial.write_text(json.dumps({
                "prism_switch": None,
                "prism_voltages_v": [177.0, -179.0],
                "source_particle_count": 2,
                "source_cohort": {"role": "formal_volume"},
                "source_expected_particle_ids": [1, 2],
                "selected_axial_energy_per_charge_v": 4000.0,
                "particle_mass_th": mass,
                "charge_state": 1,
                "target_drift_period_ratio": 25.5,
                "accelerator_pulse": {"mode": "static"},
                "execution_scope": "accelerator_safe_exit_envelope_only",
                "accelerator_geometric_exit_reference": reference,
            }), encoding="utf-8")
            log = root / "flight.log"
            log.write_text("status,Fly completed. 2 splats\n", encoding="utf-8")
            events = [
                {"kind": "accelerator_geometric_exit", "ion": 1, "t_us": 1.0,
                 "x_mm": 0.0, "y_mm": -55.0, "z_mm": 0.0,
                 "vx_mm_us": 0.0, "vy_mm_us": 1.0, "vz_mm_us": -10.0},
                {"kind": "accelerator_geometric_exit", "ion": 2, "t_us": 1.1,
                 "x_mm": 0.1, "y_mm": -55.1, "z_mm": 0.0,
                 "vx_mm_us": 0.0, "vy_mm_us": 1.0, "vz_mm_us": -11.0},
            ]
            cohort = {
                "event_integrity_passed": True,
                "particle_terminal_count": 2,
                "splat_code_histogram": {"5": 2},
                "all_losses_retained": True,
                "detection_rate": 0.0,
                "peak_analysis": {"status": "unavailable"},
                "target_k_handoff_histogram_half_height_bin_span_us": .1,
                "target_k_handoff_histogram_analysis": {"status": "computed"},
            }
            with (
                mock_recorded_scientific_events(events),
                patch.object(two_prism_simion_trial, "summarize_events", return_value=cohort),
            ):
                result = analyze_trial(
                    log_path=log, trial_receipt_path=trial,
                    output_path=root / "observation.json",
                )
            self.assertEqual(result["status"], "accelerator_geometric_exit_invalid")
            self.assertEqual(
                result["qualification"],
                "accelerator_geometric_exit_envelope_rejected",
            )
            self.assertFalse(result["accelerator_geometric_exit_validation"]["passed"])
            self.assertIsNone(result["cohort_analysis"]["detection_rate"])
            self.assertNotIn("target_k_handoff_tof_fwhm_us", result["cohort_analysis"])
            self.assertIsNone(result["cohort_analysis"]["target_k_handoff_histogram_half_height_bin_span_us"])
            self.assertEqual(result["cohort_analysis"]["target_k_handoff_histogram_analysis"]["status"],
                             "not_applicable__accelerator_geometric_exit_scope")
            self.assertEqual(
                result["cohort_analysis"]["peak_analysis"]["status"],
                "not_applicable__accelerator_geometric_exit_scope",
            )

    def test_provider_ring_vector_follows_profile_count(self) -> None:
        for ring_count in (9, 10, 15):
            voltages = [float(index) for index in range(ring_count)]
            self.assertEqual(
                _accelerator_ring_voltages(
                    {"ring_voltages_v": voltages}, {"ring_count": ring_count},
                ),
                voltages,
            )
        with self.assertRaisesRegex(CandidateContractError, "profile ring count"):
            _accelerator_ring_voltages(
                {"ring_voltages_v": [1.0] * 9}, {"ring_count": 10},
            )

    def test_runtime_fast_adjust_uses_profile_sized_accelerator_vector(self) -> None:
        source = (
            Path(__file__).resolve().parents[2] / "simion" / "mrtof_candidate.lua"
        ).read_text(encoding="utf-8")
        self.assertIn("for local_id = 1,#values.accelerator do", source)
        self.assertNotIn("for local_id = 1,9 do", source)

    def test_first_slow_signature_uses_observed_half_cycle_not_later_zero_count(self):
        def event(kind, time, **values):
            return dict(kind=kind, ion=1, t_us=time, **values)
        events = [
            event("fast_turn", 376.788833721, n=24, vy_mm_us=.0913865473007),
            event("slow_turn", 382.323150744, n=1, y_mm=364.434982803, z_mm=73.1161034471),
            event("central_plane_directional", 384.150780616, n=25, direction_z=-1),
            event("fast_turn", 391.512619791, n=25, vy_mm_us=.00467067481175),
            event("slow_turn", 396.913639187, n=1, y_mm=365.225620767, z_mm=-78.5060071164),
            event("central_plane_directional", 398.874459585, n=26, direction_z=1),
            event("fast_turn", 406.236412222, n=26, vy_mm_us=-.0807654235719),
        ]
        old = _first_slow_turn_signature(events, events[1])
        new_events = [
            event("fast_turn", 391.514142497, n=25, vy_mm_us=.0190441613963),
            events[4],
            event("central_plane_directional", 398.87600478, n=26, direction_z=1),
            event("fast_turn", 406.238005895, n=26, vy_mm_us=-.0616823620562),
        ]
        new = _first_slow_turn_signature(new_events, events[4])
        self.assertEqual(old["phase_key"], {"fast_turn_numbers": [24, 25],
                         "direction_z": -1, "sampled_vy_signs": [1, 1]})
        self.assertEqual(new["phase_key"], {"fast_turn_numbers": [25, 26],
                         "direction_z": 1, "sampled_vy_signs": [1, -1]})
        self.assertEqual(old["first_slow_turn"], events[1])
        extra = events + [event("slow_turn", 410., n=8)]
        self.assertEqual(_first_slow_turn_signature(extra, events[1]), old)
        self.assertEqual(_first_slow_turn_signature(events[:2], events[1])["status"], "unknown")

    def test_bunch_center_particle_reuses_the_four_workpoint_residuals(self) -> None:
        def state(kind: str, time: float, y: float, z: float, vy: float, vz: float, **extra):
            return {
                "kind": kind, "ion": 1, "t_us": time,
                "x_mm": 0.0, "y_mm": y, "z_mm": z,
                "vx_mm_us": 0.0, "vy_mm_us": vy, "vz_mm_us": vz,
                **extra,
            }

        events = [
            state("prism_pass", 1.0, -40.0, -101.0, 1.0, -2.0, n=1),
            state("pre_injection_mirror_turn", 2.0, -30.0, -280.0, 1.0, 0.0),
            state("prism_pass", 3.0, -10.0, 97.0, 1.0, 2.0, n=2),
            state("p2_low_field_reference", 3.25, -1.0, 33.0, 1.0, 2.0),
            state("pre_origin_positive_mirror_turn", 3.5, 0.02, 280.0, 1.0, 0.0),
            state("drift_phase_origin", 4.0, 0.0, 0.0, 1.0, -2.0),
            state("slow_turn", 10.0, 340.03, 0.0, 0.0, 0.0, n=1),
            state("target_k_phase_sample", 20.0, -0.04, -280.0, -1.0, 0.0, k=25.5),
        ]
        trial = {
            "source_center_state": {
                "particle_id": 1, "tob_us": 0.0, "mass_th": 524.0,
                "charge_e": 1, "kinetic_energy_ev": 5.0,
                "position_workbench_mm": [0.0, -55.0, 32.0],
                "direction_workbench": [0.0, 1.0, 0.0],
            },
            "target_positive_mirror_turn_y_mm": 0.0,
            "target_low_field_tangent_ratio_vy_over_vz": 0.5,
            "target_slow_turn_y_mm": 340.0,
            "target_drift_period_ratio": 25.5,
        }
        result = _bunch_center_workpoint_validation(events, trial)
        self.assertEqual(result["status"], "observed")
        self.assertEqual(result["particle_id"], 1)
        self.assertAlmostEqual(result["residuals"]["P1_P2_positive_mirror_turn_y_mm"], 0.02)
        self.assertAlmostEqual(result["residuals"]["P1_P2_P2_shield_low_field_signed_vy_over_vz"], 0.0)
        self.assertAlmostEqual(result["residuals"]["Stripe_slow_turn_y_minus_L_mm"], 0.03)
        self.assertAlmostEqual(result["residuals"]["Stripe_target_phase_y_minus_origin_mm"], -0.04)
        self.assertAlmostEqual(
            result["physical_acceptance_residuals"][
                "P1_P2_P2_shield_low_field_angle_degrees"
            ],
            0.0,
        )
        stage = _bunch_center_prism_handoff_validation(events, trial)
        self.assertEqual(stage["status"], "observed")
        self.assertEqual(stage["particle_id"], 1)
        self.assertEqual(stage["p2_low_field_reference_state"]["position_mm"], (0.0, -1.0, 33.0))
        self.assertEqual(stage["positive_mirror_turn_state"]["velocity_mm_per_us"], (0.0, 1.0, 0.0))
        self.assertEqual(stage["residuals"], {
            name: value for name, value in result["residuals"].items() if name.startswith("P1_P2_")
        })

        collision = {"kind": "terminal", "ion": 1, "t_us": 21.0, "code": -1}
        downstream_loss = events + [dict(collision, kind="splat"), collision]
        self.assertEqual(_bunch_center_prism_handoff_validation(downstream_loss, trial), stage)
        self.assertEqual(_bunch_center_workpoint_validation(downstream_loss, trial)["status"], "incomplete")
        stripe_stage = _bunch_center_stripe_stage_validation(downstream_loss, trial)
        self.assertEqual(stripe_stage["status"], "observed")
        self.assertEqual(stripe_stage["residuals"], result["residuals"])
        self.assertFalse(stripe_stage["full_workpoint_qualified"])
        coordinate_marker = state("drift_coordinate_return", 19., 0., -200., -1., -2.,
                                  k_before=25., fractional_k=25.4)
        marked = events[:-1] + [coordinate_marker] + events[-1:]
        measured = _bunch_center_stripe_stage_validation(marked, trial)
        self.assertEqual(measured["status"], "observed")
        self.assertEqual(measured["residuals"], result["residuals"])
        self.assertFalse(measured["full_workpoint_qualified"])
        # A measured IP probe can reverse its small slow velocity before P1.
        # Preserve the old OA n=1 gate while measuring the first post-origin
        # root in the explicit 3D measured-source path.
        probe_events=[dict(events[6],t_us=.5,n=1,y_mm=-55.)]+copy.deepcopy(events)
        probe_events[7]["n"]=2
        for event in probe_events:
            event["x_mm"]=.031
            event["vx_mm_us"]=.019
        probe_trial=dict(trial,source_projection="measured_exit_centroid")
        probe_source=two_prism_simion_trial.ProjectPhaseSpaceState((.031,-55.,0.),(.019,.013,-40.))
        self.assertEqual(_bunch_center_stripe_stage_validation(probe_events,trial)["status"],"incomplete")
        probe_stage=_bunch_center_stripe_stage_validation(probe_events,probe_trial,source_state=probe_source)
        self.assertEqual(probe_stage["status"],"observed")
        self.assertAlmostEqual(probe_stage["residuals"]["Stripe_slow_turn_y_minus_L_mm"],.03)
        self.assertEqual(probe_events[0]["y_mm"],-55.)
        variants = [
            events[:-1], events + [dict(events[-1], t_us=22.)],
            events[:6] + [dict(collision, t_us=9.)] + events[6:],
            events[:6] + [dict(events[6], t_us=21.)] + events[7:],
            events[:6] + [dict(events[6], n=2)] + events[7:],
            events[:6] + [dict(collision, kind="nonmirror_reversal", t_us=9.)] + events[6:],
            events[:-1] + [state("return_p2_entry", 19., 0., 101., -1., -2.)] + events[-1:],
        ]
        for invalid in variants:
            with self.subTest(invalid_stage=invalid):
                self.assertEqual(_bunch_center_stripe_stage_validation(invalid, trial)["status"], "incomplete")
        downstream_duplicate_turn = downstream_loss + [dict(events[4], t_us=22.0)]
        self.assertEqual(
            _bunch_center_prism_handoff_validation(downstream_duplicate_turn, trial)["status"],
            "incomplete",
        )
        before_turn_loss = events[:4] + [dict(collision, t_us=3.4)] + events[4:]
        self.assertEqual(
            _bunch_center_prism_handoff_validation(before_turn_loss, trial)["status"], "incomplete",
        )
        for index in range(5):
            with self.subTest(missing_event=index):
                missing = events[:index] + events[index + 1:]
                self.assertEqual(_bunch_center_prism_handoff_validation(missing, trial)["status"], "incomplete")
            with self.subTest(duplicate_event=index):
                duplicate = events[:index] + [events[index]] + events[index:]
                self.assertEqual(_bunch_center_prism_handoff_validation(duplicate, trial)["status"], "incomplete")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trial.update({
                "prism_switch": None, "prism_voltages_v": [177.0, -179.0],
                "source_particle_count": 1, "source_cohort": {"role": "controlled_diagnostic"},
                "source_cohort_role": "controlled_diagnostic", "source_expected_particle_ids": [1],
                "source_selection": {"role": "contiguous_frozen_source_diagnostic_selection"},
                "selected_axial_energy_per_charge_v": 4000.0,
                "particle_mass_th": 524.0, "charge_state": 1,
                "accelerator_pulse": {"mode": "static"},
            })
            receipt = root / "trial.json"
            receipt.write_text(json.dumps(trial), encoding="utf-8")
            log = root / "flight.log"
            log.write_text("status,Fly completed. 1 splats\n", encoding="utf-8")
            cohort = {
                "event_integrity_passed": True, "particle_terminal_count": 1,
                "splat_code_histogram": {"-1": 1}, "all_losses_retained": True,
                "detection_rate": 0.0, "peak_analysis": {"status": "unavailable"},
            }
            with (
                mock_recorded_scientific_events(downstream_loss),
                patch.object(two_prism_simion_trial, "summarize_events", return_value=cohort),
            ):
                published = analyze_trial(
                    log_path=log, trial_receipt_path=receipt, output_path=root / "observation.json",
                )
            self.assertEqual(published["center_particle_prism_handoff_validation"], stage)
            self.assertEqual(published["status"], "selected_center_observation_incomplete")
            self.assertTrue(published["termination_diagnostic"]["physical_collision"])
            self.assertFalse(published["static_return_diagnostic"]["event_contract_ok"])

    def test_mirror_regions_projects_the_single_resolved_geometry(self) -> None:
        resolved = {
            "mirror_ground_shields": [{"box": [0, 0, -9, 1, 1, -8]}],
            "mirror_electrodes": [
                {"box": [0, 0, -7, 1, 1, -6]},
                {"box": [0, 0, 6, 1, 1, 7]},
            ],
            "mirror_e_closures": [{"box": [0, 0, 8, 1, 1, 9]}],
        }
        self.assertEqual(
            _mirror_regions(resolved),
            {"negative": [-9, -6], "positive": [6, 9]},
        )

    def test_cli_uses_only_the_declared_workbench_accelerator_instance(self) -> None:
        source = Path(two_prism_simion_trial.__file__).read_text(encoding="utf-8")
        self.assertIn("accelerator_instance=args.workbench_accelerator_instance", source)
        self.assertNotIn("accelerator_instance=args.accelerator_instance", source)

    def test_provider_pose_comes_only_from_the_frozen_composition_plan(self) -> None:
        source = Path(two_prism_simion_trial.__file__).read_text(encoding="utf-8")
        self.assertIn("direct_pose = resolve_oa_mr_direct_pose(provider_plan, composition_plan", source)
        self.assertIn('exit_project = direct_pose[\"exit_project_mm\"]', source)
        self.assertNotIn("derive_two_zone_placement", source)

    def test_terminal_mirror_variation_is_authority_bound_and_envelope_checked(self) -> None:
        contract_path = Path(__file__).resolve().parents[2] / "config" / "simion_candidate_two_zone.json"
        contract = two_prism_simion_trial.load_contract(contract_path)
        base = [0.0, -5920.610006, -2612.981546, 4190.462801, 6029.159820]
        variation = {
            "schema_version": 1,
            "role": "mrtof_terminal_time_mirror_voltage_variation",
            "status": "screening_candidate_materialized",
            "qualification": "diagnostic_only__complete_3d_detector_response_pending",
            "mode": "TE1",
            "coordinate": 1,
            "base_mirror_voltages_v": base,
            "target_mirror_voltages_v": [0.0, base[1] + 2, base[2] - 10, base[3] + 6, base[4] + 5],
            "voltage_delta_v": [2.0, -10.0, 6.0, 5.0],
            "source_seed": {"sha256": "a" * 64},
        }
        target, identity = _apply_terminal_mirror_variation(
            variation=variation, base_voltages=base, contract=contract,
            axial_energy_v=4372.010347796,
        )
        self.assertEqual(target, variation["target_mirror_voltages_v"])
        self.assertEqual(identity["mode"], "TE1")
        advisory = copy.deepcopy(variation)
        advisory["qualification"] = (
            "bare_mirror_prediction_outside_old_zero_slope_budget__complete_system_response_required"
        )
        advisory_target, _ = _apply_terminal_mirror_variation(
            variation=advisory, base_voltages=base, contract=contract,
            axial_energy_v=4372.010347796,
        )
        self.assertEqual(advisory_target, variation["target_mirror_voltages_v"])
        invalid = copy.deepcopy(variation)
        invalid["base_mirror_voltages_v"][1] += 1
        with self.assertRaisesRegex(CandidateContractError, "not bound"):
            _apply_terminal_mirror_variation(
                variation=invalid, base_voltages=base, contract=contract,
                axial_energy_v=4372.010347796,
            )

    def test_active_screening_default_is_four_ns_and_scales_from_its_contract(self) -> None:
        contract_path = Path(__file__).resolve().parents[2] / "config/simion_candidate_two_zone.json"
        numerics = json.loads(contract_path.read_text(encoding="utf-8"))["simion"]
        self.assertEqual(numerics["default_trajectory_profile_id"], "center_screening")
        base = dict(numerics["trajectory_profiles"]["center_screening"], profile_id="center_screening")
        self.assertEqual(base["maximum_step_us"], 0.004)
        self.assertEqual(base["trajectory_quality"], 8)
        self.assertIs(_apply_trajectory_step_scale(base, 1.0), base)
        for scale, maximum in ((0.5, 0.002), (2.0, 0.008)):
            scaled = _apply_trajectory_step_scale(base, scale)
            self.assertEqual(scaled["maximum_step_us"], maximum)
            self.assertEqual(scaled["base_maximum_step_us"], 0.004)
            self.assertEqual(scaled["step_scale"], scale)
        self.assertEqual(numerics["trajectory_profiles"]["center_refined"]["maximum_step_us"], 0.0002)
        self.assertEqual(numerics["trajectory_profiles"]["center_precision"]["maximum_step_us"], 0.00002)

    def test_trajectory_step_scale_derives_0p001_from_screening_profile(self) -> None:
        base = {
            "profile_id": "center_screening", "trajectory_quality": 8,
            "maximum_step_us": 0.002, "purpose": "screening",
        }
        scaled = _apply_trajectory_step_scale(base, 0.5)
        self.assertEqual(scaled["maximum_step_us"], 0.001)
        self.assertEqual(scaled["base_profile_id"], "center_screening")
        self.assertEqual(base["maximum_step_us"], 0.002)
        self.assertIs(_apply_trajectory_step_scale(base, 1.0), base)
        for scale in (2.0, 4.0):
            coarse = _apply_trajectory_step_scale(base, scale)
            self.assertEqual(coarse["maximum_step_us"], 0.002 * scale)
            self.assertEqual(coarse["base_maximum_step_us"], 0.002)
            self.assertEqual(coarse["step_scale"], scale)
            self.assertEqual(coarse["trajectory_quality"], 8)
            self.assertIn("numerical step scaling", coarse["purpose"])
        for invalid in (0.0, -1.0, float("nan"), float("inf")):
            with self.assertRaises(CandidateContractError):
                _apply_trajectory_step_scale(base, invalid)
        with self.assertRaises(CandidateContractError):
            _apply_trajectory_step_scale({**base, "maximum_step_us": 1e308}, 2.0)

    def test_accelerator_energy_binding_distinguishes_command_from_target(self) -> None:
        target = 4198.824969860909
        correction = 0.7536110122964601
        binding = _accelerator_energy_binding({
            "energy_per_charge_v": target + correction,
            "target_axial_energy_per_charge_v": target,
            "finite_3d_gain_correction_v": correction,
        }, target)
        self.assertEqual(binding["target_axial_energy_per_charge_v"], target)
        self.assertEqual(binding["finite_3d_gain_correction_v"], correction)
        self.assertAlmostEqual(
            binding["applied_net_gain_parameter_v"], target + correction,
        )

    def test_accelerator_energy_binding_fails_closed_on_wrong_target_or_identity(self) -> None:
        target = 4198.824969860909
        correction = 0.7536110122964601
        valid = {
            "energy_per_charge_v": target + correction,
            "target_axial_energy_per_charge_v": target,
            "finite_3d_gain_correction_v": correction,
        }
        with self.assertRaisesRegex(
            CandidateContractError, "target axial energy and analyser",
        ):
            _accelerator_energy_binding(
                {**valid, "target_axial_energy_per_charge_v": target - 1.0}, target,
            )
        with self.assertRaisesRegex(
            CandidateContractError, "finite-3D correction.*inconsistent",
        ):
            _accelerator_energy_binding(
                {**valid, "finite_3d_gain_correction_v": correction + 0.1}, target,
            )

    def test_trial_geometry_keeps_reviewed_conductors_and_current_event_authority(self) -> None:
        reviewed = {
            "identity": "reviewed-physical-geometry",
            "accelerator": {"reviewed_conductor": "retained"},
        }
        current = {"identity": "current-topology-and-observation-authority"}
        accelerator = {
            "accelerator": {
                "component_source_cylinder": {"radius_mm": 0.1, "height_mm": 2.0},
                "focus_y_anchor": {"project_y_mm": -45.0},
                "unused_provider_field": "not-forwarded",
            },
        }
        expected = {"resolved": True}
        with patch.object(
            two_prism_simion_trial, "resolve_geometry", return_value=expected,
        ) as resolver:
            self.assertIs(_resolve_trial_geometry(reviewed, current, accelerator), expected)
        forwarded = resolver.call_args.args[0]
        self.assertEqual(forwarded["identity"], "reviewed-physical-geometry")
        self.assertEqual(forwarded["accelerator"]["reviewed_conductor"], "retained")
        self.assertEqual(
            forwarded["accelerator"]["component_source_cylinder"],
            accelerator["accelerator"]["component_source_cylinder"],
        )
        self.assertEqual(
            forwarded["accelerator"]["focus_y_anchor"],
            accelerator["accelerator"]["focus_y_anchor"],
        )
        self.assertNotIn("unused_provider_field", forwarded["accelerator"])
        self.assertNotIn("component_source_cylinder", reviewed["accelerator"])
        self.assertEqual(
            resolver.call_args.kwargs,
            {"inherited_dual_stripe_topology_contract": current, "accelerator_assembly": None},
        )

    def test_trial_geometry_forwards_frozen_oa_assembly_to_real_p1_extension(self) -> None:
        path = Path(__file__).resolve().parents[2] / "config/simion_candidate_two_zone.json"
        contract = json.loads(path.read_text(encoding="utf-8"))
        contract["prisms"]["ground_shields"][0]["extension_to_accelerator_exit"] = {"clearance_mm": 1.0}
        original = copy.deepcopy(contract)
        assembly = {
            "accelerator_resolved_electrodes": {
                "acceleration_direction": "-z", "local_to_pa_translation_mm": [0., 0., 0.],
                "grid_supports": [{"component_electrode_id": 4, "frame_outer_box_mm": {"z_min_mm": 0.}}],
            },
            "accelerator_iob_origin_mm": [0., 0., 0.],
        }
        with self.assertRaisesRegex(CandidateContractError, "frozen accelerator assembly"):
            _resolve_trial_geometry(contract, contract, contract)
        result = _resolve_trial_geometry(contract, contract, contract, accelerator_assembly=assembly)
        shield = result["prism_ground_shields"][0]
        extension = shield["extension_to_accelerator_exit"]
        self.assertEqual(extension["resolved_end_z_mm"], -1.0)
        self.assertEqual(extension["exit_support_downstream_z_mm"], 0.0)
        self.assertEqual(extension["added_length_mm"], 29.0)
        self.assertEqual(contract, original)
        invalid = copy.deepcopy(assembly)
        invalid["accelerator_resolved_electrodes"]["acceleration_direction"] = "+z"
        with self.assertRaisesRegex(CandidateContractError, "resolved OA exit support/assembly"):
            _resolve_trial_geometry(contract, contract, contract, accelerator_assembly=invalid)

    @staticmethod
    def _analyze_with_handoff_events(
        *, log: Path, receipt: Path, output: Path,
    ) -> dict[str, object]:
        """Insert the P2 low-field section into compact downstream fixtures."""
        events = parse_events(log.read_text(encoding="utf-8"))
        p2_index = next(
            index for index, event in enumerate(events)
            if event["kind"] == "prism_pass" and event.get("n") == 2
        )
        events.insert(p2_index + 1, {
            "kind": "p2_low_field_reference",
            "ion": 1,
            "t_us": 3.25,
            "x_mm": 0.0,
            "y_mm": -1.0,
            "z_mm": 33.0,
            "vx_mm_us": 0.0,
            "vy_mm_us": 1.0,
            "vz_mm_us": 2.0,
        })
        with mock_recorded_scientific_events(events):
            return analyze_trial(
                log_path=log, trial_receipt_path=receipt, output_path=output,
            )

    @staticmethod
    def _single_center_source_fields() -> dict[str, object]:
        return {
            "source_slow_kinetic_energy_per_charge_v": 5.0,
            "source_direction_project": [0.0, 1.0, 0.0],
            "source_particle_count": 1,
            "source_time_of_birth_us": 0.0,
        }

    @staticmethod
    def _schema5_source_fixture() -> tuple[dict[str, object], dict[str, object]]:
        contract: dict[str, object] = {
            "nominal": {"energy_per_charge_v": 4000.0},
            "accelerator_energy_contract": {
                "net_gain_reference_center_per_charge_v": 4000.0,
                "net_gain_center_search_half_range_per_charge_v": 500.0,
            },
            "prism_transport": {
                "energy_partition": {"drift_kinetic_energy_ev": 5.0},
            },
            "dual_stripe": {
                "theory_profile": {
                    "set_1": {"curve": [[0.0, 4.0], [340.0, 3.0]]},
                    "set_2": {"curve": [[0.0, 2.0], [340.0, 1.0]]},
                },
            },
            "dual_stripe_l0": {
                "coordinate_mapping": {
                    "origin_project_y_mm": 0.0,
                    "theory_positive_project_y_sign": 1,
                },
                "theory_function_coordinate_registration": {
                    "function_y_zero_project_y_mm": 0.0,
                    "active_theory_curve_domain_project_y_mm": [0.0, 390.0],
                },
                "manufactured_design_abs_drift_length_L_mm": 340.0,
            },
        }
        geometry_identity = (
            "canonical_json_sha256:"
            f"{native_stripe_geometry_projection_sha256(contract)}"
        )
        shape_root = {
            "geometry_input_identity_source": geometry_identity,
            "kappa_1": 1.48896973866,
        }
        biases = [-25.3180924893, 50.3596877998]
        summary: dict[str, object] = {
            "schema_version": 5,
            "role": "mrtof_dual_stripe_exact_k_downstream_operating_seed",
            "status": "native_shape_source_energy_inverse_and_stripe_on_exact_k_complete",
            "selected_exact_k_operating_point": {
                "axial_energy_per_charge_v": 4000.0,
                "kappa_1": shape_root["kappa_1"],
            },
            "native_stripe_spatial_shape_root": shape_root,
            "selected_seed": {
                "nominal_kappa_1": shape_root["kappa_1"],
                "nominal_injection_angle_degrees": 1.2,
                "stripe_biases_v": biases,
                "native_spatial_return_materialization": {
                    "shape_root": dict(shape_root),
                    "axial_energy_per_charge_v": 4000.0,
                    "source_slow_energy_per_charge_v": 5.0,
                    # This is intentionally different: it is a derived turn
                    # diagnostic, never the released source energy authority.
                    "turning_pseudopotential_v": 4.955863026,
                    "stripe_biases_v": list(biases),
                },
            },
        }
        return summary, contract

    def test_handoff_targets_come_from_frozen_seed_and_registration(self) -> None:
        summary, contract = self._schema5_source_fixture()
        seed = summary["selected_seed"]
        target_y, angle_degrees, tangent_ratio = _p2_handoff_targets(seed, contract)
        self.assertEqual(target_y, 0.0)
        self.assertEqual(angle_degrees, 1.2)
        self.assertAlmostEqual(tangent_ratio, math.tan(math.radians(1.2)))

        invalid = copy.deepcopy(seed)
        invalid["nominal_injection_angle_degrees"] = 0.0
        with self.assertRaisesRegex(CandidateContractError, "finite positive"):
            _p2_handoff_targets(invalid, contract)

    def test_schema5_native_source_uses_fixed_source_energy_not_turning_energy(self) -> None:
        summary, contract = self._schema5_source_fixture()
        seed, source_energy = _schema5_native_source_state(summary, contract, 4000.0)
        self.assertEqual(source_energy, 5.0)
        self.assertEqual(
            seed["native_spatial_return_materialization"]["turning_pseudopotential_v"],
            4.955863026,
        )

        fly2 = _single_center_source_fly2(
            mass_th=100.0,
            charge_state=-2,
            source_slow_energy_per_charge_v=source_energy,
            focus_y_mm=-55.0,
            release_z_mm=50.0,
        )
        self.assertIn("ke = 10,", fly2)
        self.assertIn("charge = -2,", fly2)
        self.assertIn("direction = vector(0, 1, 0),", fly2)
        self.assertNotIn("4.955863026", fly2)

    def test_fixed_mirror_stripe_authority_selects_near_five_ev_source(self) -> None:
        _, contract = self._schema5_source_fixture()
        axial = 4372.010347796059
        slow = 4.961131691875478
        target_k = 25.5
        biases = [-25.223218746120438, 50.18222992863684]
        voltages = [0.0, -4799.0, 3811.0, 4998.0, 7931.0]
        materialized = {
            "axial_energy_per_charge_v": axial,
            "source_slow_energy_per_charge_v": slow,
            "stripe_biases_v": list(biases),
        }
        seed = {
            "selected_axial_energy_per_charge_v": axial,
            "selected_exact_K_slow_energy_per_charge_v": slow,
            "target_drift_period_ratio": target_k,
            "predicted_continuous_oscillation_count": target_k,
            "nominal_injection_angle_degrees": math.degrees(math.atan(math.sqrt(slow / axial))),
            "stripe_biases_v": list(biases),
            "native_spatial_return_materialization": materialized,
        }
        stripe = {
            "schema_version": 3,
            "role": "mrtof_dual_stripe_paper_theory_instance_specific_operating_seed_family",
            "status": "fixed_grid_native_mirror_exact_K_slow_energy_and_spatial_return_inverse_complete",
            "selected_seed": seed,
        }
        mirror = {
            "schema_version": 1,
            "role": "mrtof_mirror_turn_fixed_grid_validation",
            "status": "success",
        }
        authority = {
            "schema_version": 1,
            "role": "mrtof_fixed_mirror_stripe_downstream_operating_authority",
            "status": "success",
            "axial_energy_per_charge_v": axial,
            "slow_energy_per_charge_v": slow,
            "target_period_ratio": target_k,
            "predicted_period_ratio": target_k,
            "mirror_voltages_v": list(voltages),
            "stripe_biases_v": list(biases),
        }
        selected = _fixed_mirror_stripe_source_state(
            authority, mirror, stripe, contract,
        )
        self.assertIs(selected[0], seed)
        self.assertEqual(selected[1:], (slow, axial, voltages, target_k))
        invalid = copy.deepcopy(authority)
        invalid["slow_energy_per_charge_v"] = 5.0
        with self.assertRaisesRegex(CandidateContractError, "differs from its source summary"):
            _fixed_mirror_stripe_source_state(invalid, mirror, stripe, contract)

    def test_schema5_native_source_accepts_selected_exact_k_energy_within_search_envelope(self) -> None:
        summary, contract = self._schema5_source_fixture()
        selected = 4198.824969860909
        summary["selected_exact_k_operating_point"]["axial_energy_per_charge_v"] = selected
        summary["selected_seed"]["native_spatial_return_materialization"][
            "axial_energy_per_charge_v"
        ] = selected
        _, source_energy = _schema5_native_source_state(summary, contract, selected)
        self.assertEqual(source_energy, 5.0)

        with self.assertRaisesRegex(CandidateContractError, "outside the contract search envelope"):
            _schema5_native_source_state(summary, contract, 4500.0000001)

    def test_single_center_source_state_uses_energy_mass_charge_and_direction(self) -> None:
        trial = {
            **self._single_center_source_fields(),
            "source_position_project_mm": [0.0, -55.0, 50.0],
            "particle_mass_th": 524.0,
            "charge_state": 2,
        }
        state, published = _single_center_source_state(trial)
        self.assertEqual(state.position_mm, (0.0, -55.0, 50.0))
        self.assertAlmostEqual(published["kinetic_energy_ev"], 10.0)
        self.assertAlmostEqual(published["kinetic_energy_per_charge_v"], 5.0)
        self.assertEqual(published["direction_project"], [0.0, 1.0, 0.0])
        self.assertGreater(state.velocity_mm_per_us[1], 0.0)
        self.assertNotEqual(state.velocity_mm_per_us, (0.0, 1.0, 0.0))
        for missing in (
            "source_slow_kinetic_energy_per_charge_v",
            "source_direction_project",
            "particle_mass_th",
            "charge_state",
        ):
            invalid = dict(trial)
            del invalid[missing]
            with self.subTest(missing=missing):
                with self.assertRaises(CandidateContractError):
                    _single_center_source_state(invalid)
        with self.assertRaisesRegex(CandidateContractError, "Fly2 \+project-y"):
            _single_center_source_state({
                **trial,
                "source_direction_project": [0.0, 0.0, -1.0],
            })

    def test_schema5_native_source_rejects_missing_or_inconsistent_identity(self) -> None:
        cases = []
        summary, contract = self._schema5_source_fixture()
        summary["schema_version"] = 4
        cases.append((summary, contract, "schema-5"))

        summary, contract = self._schema5_source_fixture()
        materialized = summary["selected_seed"]["native_spatial_return_materialization"]
        del materialized["source_slow_energy_per_charge_v"]
        cases.append((summary, contract, "source slow energy"))

        summary, contract = self._schema5_source_fixture()
        summary["selected_seed"]["native_spatial_return_materialization"][
            "source_slow_energy_per_charge_v"
        ] = 6.0
        cases.append((summary, contract, "fixed source contract"))

        summary, contract = self._schema5_source_fixture()
        summary["selected_seed"]["native_spatial_return_materialization"][
            "axial_energy_per_charge_v"
        ] = 3999.0
        cases.append((summary, contract, "selected energies differ"))

        summary, contract = self._schema5_source_fixture()
        summary["selected_seed"]["native_spatial_return_materialization"]["shape_root"] = {
            "geometry_input_identity_source": "canonical_json_sha256:other-shape",
            "kappa_1": 1.48896973866,
        }
        cases.append((summary, contract, "shape identity"))

        summary, contract = self._schema5_source_fixture()
        summary["native_stripe_spatial_shape_root"][
            "geometry_input_identity_source"
        ] = "canonical_json_sha256:jointly-forged-shape"
        summary["selected_seed"]["native_spatial_return_materialization"]["shape_root"][
            "geometry_input_identity_source"
        ] = "canonical_json_sha256:jointly-forged-shape"
        cases.append((summary, contract, "shape identity"))

        summary, contract = self._schema5_source_fixture()
        changed_contract = copy.deepcopy(contract)
        changed_contract["dual_stripe"]["theory_profile"]["set_1"]["curve"][1][1] = 3.25
        cases.append((summary, changed_contract, "shape identity"))

        summary, contract = self._schema5_source_fixture()
        summary["selected_seed"]["native_spatial_return_materialization"][
            "stripe_biases_v"
        ][0] += 0.1
        cases.append((summary, contract, "shape identity"))

        summary, contract = self._schema5_source_fixture()
        del contract["prism_transport"]["energy_partition"]
        cases.append((summary, contract, "energy authorities"))

        for invalid_summary, invalid_contract, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(CandidateContractError, message):
                    _schema5_native_source_state(
                        invalid_summary, invalid_contract, 4000.0,
                    )

    def test_frozen_accelerator_schedule_requires_clock_and_source_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.json"
            schedule = {
                "schema_version": 1,
                "role": "mrtof_accelerator_global_pulse_schedule",
                "status": "frozen",
                "mode": "fixed_global_time",
                "time_basis": "ion_time_of_flight_us_from_common_tob_zero_release",
                "pulse_off_time_us": 1.867,
                "source": {
                    "center_run_id": "run",
                    "run_manifest_sha256": "a",
                    "trial_receipt_sha256": "b",
                    "observation_sha256": "c",
                    "source_fly2_sha256": "d",
                    "accelerator_receipt_sha256": "e",
                    "source_particle_count": 1,
                },
                "after_state": {
                    "accelerator_electrode_ids": list(range(1, 10)),
                    "voltage_v": 0.0,
                },
            }
            path.write_text(json.dumps(schedule), encoding="utf-8")
            self.assertEqual(
                _load_frozen_accelerator_pulse_schedule(path)["pulse_off_time_us"],
                1.867,
            )
            schedule["source"].pop("source_fly2_sha256")
            path.write_text(json.dumps(schedule), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "source identity"):
                _load_frozen_accelerator_pulse_schedule(path)

    def test_complete_bunch_schedule_identity_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.json"
            schedule = {
                "schema_version": 2,
                "role": "mrtof_accelerator_global_pulse_schedule",
                "status": "frozen",
                "mode": "fixed_global_time",
                "time_basis": "ion_time_of_flight_us_from_common_tob_zero_release",
                "pulse_off_time_us": 1.9,
                "source_cohort": {"particle_states_sha256": "a" * 64},
                "solver_problem_identity": {"canonical_sha256": "b" * 64},
                "safe_exit_definition": {"event_count": 100},
                "after_state": {
                    "accelerator_electrode_ids": list(range(1, 10)),
                    "voltage_v": 0.0,
                },
            }
            path.write_text(json.dumps(schedule), encoding="utf-8")
            self.assertEqual(
                _load_frozen_accelerator_pulse_schedule(path)["schema_version"], 2
            )
            del schedule["solver_problem_identity"]
            path.write_text(json.dumps(schedule), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "bunch pulse schedule"):
                _load_frozen_accelerator_pulse_schedule(path)


    def test_static_return_requires_unique_ordered_negative_z_detector_hit(self) -> None:
        kinds = (
            "drift_phase_return", "return_p2_entry", "return_p2_pass",
            "return_positive_mirror_turn",
        )
        events = [
            {"kind": kind, "ion": 1, "fractional_k": 24.99, "t_us": float(index),
             "z_mm": 280.0 if kind == "return_positive_mirror_turn" else 0.0,
             "vz_mm_us": (1.0 if kind in ("return_p2_entry", "return_p2_pass")
                            else 0.0)}
            for index, kind in enumerate(kinds, 1)
        ] + [
            {"kind": "detector", "ion": 1, "direction_z": -1, "z_mm": 95.0, "t_us": 7.0},
            {"kind": "splat", "ion": 1, "code": 1, "t_us": 7.0},
            {"kind": "terminal", "ion": 1, "splat": 1, "t_us": 7.0},
        ]
        result = _static_return_diagnostic(events, 25)
        self.assertEqual(result["status"], "detector_hit")
        self.assertTrue(result["event_contract_ok"])
        self.assertAlmostEqual(result["fractional_k_minus_target"], -0.01)
        events.insert(1, {"kind": "drift_phase_candidate", "ion": 1, "k": 26, "t_us": 1.5})
        self.assertTrue(_static_return_diagnostic(events, 25)["event_contract_ok"])
        next(event for event in events if event["kind"] == "return_p2_pass")["t_us"] = 0.5
        self.assertIn("static_return_events_out_of_order",
                      _static_return_diagnostic(events, 25)["errors"])

    def test_static_return_rejects_accelerator_reentry(self) -> None:
        kinds = (
            "drift_phase_return", "return_p2_entry", "return_p2_pass",
            "return_positive_mirror_turn",
        )
        events = [
            {"kind": kind, "ion": 1, "fractional_k": 25.0, "t_us": float(index),
             "z_mm": 280.0 if kind == "return_positive_mirror_turn" else 0.0,
             "vz_mm_us": (1.0 if kind in ("return_p2_entry", "return_p2_pass")
                            else 0.0)}
            for index, kind in enumerate(kinds, 1)
        ] + [
            {"kind": "accelerator_reentry", "ion": 1, "t_us": 6.5},
            {"kind": "detector", "ion": 1, "direction_z": -1, "z_mm": 95.0, "t_us": 7.0},
            {"kind": "splat", "ion": 1, "code": 1, "t_us": 7.0},
            {"kind": "terminal", "ion": 1, "splat": 1, "t_us": 7.0},
        ]
        result = _static_return_diagnostic(events, 25)
        self.assertFalse(result["event_contract_ok"])
        self.assertIn("accelerator_reentry_after_safe_exit_forbidden", result["errors"])

    def test_static_return_rejects_legacy_return_through_p1(self) -> None:
        kinds = (
            "drift_phase_return", "return_p2_entry", "return_p2_pass",
            "return_positive_mirror_turn",
        )
        events = [
            {"kind": kind, "ion": 1, "fractional_k": 25.5, "t_us": float(index),
             "z_mm": 280.0 if kind == "return_positive_mirror_turn" else 0.0,
             "vz_mm_us": (1.0 if kind in ("return_p2_entry", "return_p2_pass")
                            else 0.0)}
            for index, kind in enumerate(kinds, 1)
        ] + [
            {"kind": "return_p1_pass", "ion": 1, "t_us": 6.0,
             "x_mm": 0.0, "y_mm": 0.0, "z_mm": 0.0,
             "vx_mm_us": 0.0, "vy_mm_us": -1.0, "vz_mm_us": -1.0},
            {"kind": "detector", "ion": 1, "direction_z": -1,
             "z_mm": 95.0, "t_us": 7.0},
            {"kind": "splat", "ion": 1, "code": 1, "t_us": 7.0},
            {"kind": "terminal", "ion": 1, "splat": 1, "t_us": 7.0},
        ]
        result = _static_return_diagnostic(events, 25.5)
        self.assertFalse(result["event_contract_ok"])
        self.assertIn(
            "return_p1_forbidden__p1_is_injection_only", result["errors"]
        )

    def test_code_four_is_programmatic_topology_rejection_not_collision(self) -> None:
        events = parse_events(
            "MRTOF_EVENT splat ion=1 code=4 "
            "termination_kind=programmatic_topology_rejection "
            "physical_collision=0 reason=return_central_phase_direction_mismatch "
            "t_us=20 x_mm=0 y_mm=0 z_mm=159.88 turns=49 central_crossings=49\n"
            "MRTOF_EVENT terminal ion=1 splat=4 t_us=20 x_mm=0 y_mm=0 "
            "z_mm=159.88 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=47 "
            "turns=49 central_crossings=49\n"
        )
        diagnostic = _termination_diagnostic(events)
        self.assertEqual(diagnostic["kind"], "programmatic_topology_rejection")
        self.assertFalse(diagnostic["physical_collision"])
        self.assertTrue(diagnostic["explicit_semantics"])
        self.assertEqual(
            diagnostic["reason"], "return_central_phase_direction_mismatch"
        )

    def test_switched_trial_receipt_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_voltages_v": [177.0, -179.0],
                "source_position_project_mm": [0.0, -55.0, 0.0],
                "target_positive_mirror_turn_y_mm": 0.0,
                "target_low_field_tangent_ratio_vy_over_vz": 0.5,
                "particle_mass_th": 524.0,
                "charge_state": 1,
                "flight_scope": "complete_three_dimensional_static_return",
                "prism_switch": {"enabled": True},
            }), encoding="utf-8")
            log = root / "flight.log"
            log.write_text("", encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "forbids all P1/P2"):
                analyze_trial(log_path=log, trial_receipt_path=receipt,
                              output_path=root / "observation.json")

    def test_switch_event_in_static_log_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_voltages_v": [177.0, -179.0],
                "target_drift_period_ratio": 25.5,
                "target_half_oscillation_count": 51,
                "prism_switch": None,
            }), encoding="utf-8")
            log = root / "flight.log"
            log.write_text(
                "MRTOF_EVENT prism_voltage_switch ion=1 electrode=17 "
                "t_us=10 from_v=-179 to_v=-140\n", encoding="utf-8",
            )
            with self.assertRaisesRegex(CandidateContractError, "forbidden P1/P2"):
                analyze_trial(log_path=log, trial_receipt_path=receipt,
                              output_path=root / "observation.json")

    def test_single_center_accelerator_pulse_requires_one_initial_exit_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_voltages_v": [177.0, -179.0],
                "source_position_project_mm": [0.0, -55.0, -60.0],
                **self._single_center_source_fields(),
                "target_positive_mirror_turn_y_mm": 0.0,
                "target_low_field_tangent_ratio_vy_over_vz": 0.5,
                "particle_mass_th": 524.0,
                "charge_state": 1,
                "target_drift_period_ratio": 25.5,
                "target_half_oscillation_count": 51,
                "flight_scope": "complete_three_dimensional_static_return",
                "prism_switch": None,
                "accelerator_pulse": {
                    "mode": "initial_exit_triggered_single_center",
                    "qualification": "single_center_only",
                },
                "accelerator_instance": 3,
            }), encoding="utf-8")
            log = root / "flight.log"
            log.write_text("", encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "exactly one pulse-off"):
                analyze_trial(log_path=log, trial_receipt_path=receipt,
                              output_path=root / "missing.json")
            safe_exit_only = json.loads(receipt.read_text(encoding="utf-8"))
            safe_exit_only["execution_scope"] = "accelerator_safe_exit_envelope_only"
            receipt.write_text(json.dumps(safe_exit_only), encoding="utf-8")
            result = analyze_trial(
                log_path=log,
                trial_receipt_path=receipt,
                output_path=root / "safe-exit-only.json",
            )
            self.assertEqual(
                result["accelerator_pulse_diagnostic"]["pulse_off_event_count"], 0
            )
            safe_exit_only["execution_scope"] = "complete_three_dimensional_static_return"
            receipt.write_text(json.dumps(safe_exit_only), encoding="utf-8")
            log.write_text(
                "MRTOF_EVENT accelerator_pulse_off ion=1 t_us=1.86 "
                "from_instance=3 to_instance=1 x_mm=0 y_mm=-55 z_mm=-5.7\n",
                encoding="utf-8",
            )
            result = analyze_trial(log_path=log, trial_receipt_path=receipt,
                                   output_path=root / "observed.json")
            self.assertEqual(
                result["accelerator_pulse_diagnostic"]["pulse_off_event_count"], 1
            )

    def test_fixed_global_accelerator_pulse_requires_the_frozen_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_switch": None,
                "prism_voltages_v": [10.0, -10.0],
                "source_position_project_mm": [0.0, -55.0, 50.0],
                **self._single_center_source_fields(),
                "target_positive_mirror_turn_y_mm": 0.0,
                "target_low_field_tangent_ratio_vy_over_vz": 0.5,
                "particle_mass_th": 524.0,
                "charge_state": 1,
                "target_drift_period_ratio": 25.5,
                "target_half_oscillation_count": 51,
                "flight_scope": "complete_three_dimensional_static_return",
                "accelerator_pulse": {
                    "mode": "fixed_global_time",
                    "pulse_off_time_us": 1.86736875912,
                    "qualification": "frozen_global_time_single_center_diagnostic__bunch_qualification_pending",
                },
            }), encoding="utf-8")
            log = root / "flight.log"
            event = (
                "MRTOF_EVENT accelerator_global_pulse_applied ion=1 "
                "t_us=1.86736875912 scheduled_t_us=1.86736875912 instance=4 "
                "x_mm=0 y_mm=-55 z_mm=-5.7 trigger=fixed_global_time\n"
            )
            log.write_text(event, encoding="utf-8")
            result = analyze_trial(
                log_path=log, trial_receipt_path=receipt,
                output_path=root / "observed.json",
            )
            self.assertEqual(
                result["accelerator_pulse_diagnostic"]["mode"], "fixed_global_time"
            )
            self.assertEqual(
                result["accelerator_pulse_diagnostic"]["fixed_global_pulse_validation"]["particle_count"],
                1,
            )
            log.write_text(event.replace("1.86736875912 ", "1.88 ", 1), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "common pulse boundary"):
                analyze_trial(
                    log_path=log, trial_receipt_path=receipt,
                    output_path=root / "mismatch.json",
                )

    def test_fixed_global_accelerator_pulse_requires_one_event_per_particle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_switch": None,
                "prism_voltages_v": [10.0, -10.0],
                "source_position_project_mm": [0.0, -55.0, 50.0],
                **self._single_center_source_fields(),
                "source_particle_count": 2,
                "source_cohort": {"role": "test_selection"},
                "source_expected_particle_ids": [1, 2],
                "selected_axial_energy_per_charge_v": 4000.0,
                "target_positive_mirror_turn_y_mm": 0.0,
                "target_low_field_tangent_ratio_vy_over_vz": 0.5,
                "particle_mass_th": 524.0,
                "charge_state": 1,
                "target_drift_period_ratio": 25.5,
                "target_half_oscillation_count": 51,
                "flight_scope": "complete_three_dimensional_static_return",
                "accelerator_pulse": {
                    "mode": "fixed_global_time",
                    "pulse_off_time_us": 1.82574136731,
                    "qualification": "complete_bunch_safe_exit_schedule__numerical_convergence_pending",
                },
            }), encoding="utf-8")
            event = (
                "MRTOF_EVENT accelerator_global_pulse_applied ion={ion} "
                "t_us=1.82574136731 scheduled_t_us=1.82574136731 instance=4 "
                "x_mm=0 y_mm=-52.8 z_mm=-5.8 trigger=fixed_global_time\n"
            )
            log = root / "flight.log"
            log.write_text(event.format(ion=1) + event.format(ion=2), encoding="utf-8")
            result = analyze_trial(
                log_path=log, trial_receipt_path=receipt,
                output_path=root / "observed.json",
            )
            validation = result["accelerator_pulse_diagnostic"]["fixed_global_pulse_validation"]
            self.assertEqual(validation["particle_count"], 2)
            self.assertEqual(validation["event_count"], 2)
            log.write_text(event.format(ion=1), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "particle 2 must have exactly one"):
                analyze_trial(
                    log_path=log, trial_receipt_path=receipt,
                    output_path=root / "missing.json",
                )

    def test_bunch_analysis_preserves_a_contiguous_global_id_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_switch": None,
                "prism_voltages_v": [177.0, -179.0],
                "source_particle_count": 2,
                "source_cohort": {"role": "frozen_selection"},
                "source_expected_particle_ids": [97, 98],
                "source_selection": {"particle_id_min": 97, "particle_id_max": 98},
                "selected_axial_energy_per_charge_v": 4000.0,
                "source_slow_kinetic_energy_per_charge_v": 5.0,
                "accelerator_target_axial_energy_per_charge_v": 4000.0,
                "accelerator_exit_energy_contract": {
                    "targets_per_charge_v": {"Ex": 0.0, "Ey": 5.0, "Ez": 4000.0},
                    "absolute_tolerances_per_charge_v": {"Ex": 0.01, "Ey": 0.02, "Ez": 0.03},
                },
                "particle_mass_th": 100.0,
                "charge_state": 1,
                "target_drift_period_ratio": 25.5,
                "accelerator_pulse": {"mode": "static"},
            }), encoding="utf-8")
            log = root / "flight.log"
            log.write_text("status,Fly completed. 2 splats\n", encoding="utf-8")
            cohort = {
                "event_integrity_passed": True,
                "particle_terminal_count": 2,
                "splat_code_histogram": {"1": 1, "-1": 1},
                "all_losses_retained": True,
                "detection_rate": 0.5,
                "target_k_fraction": 0.5,
                "overtone_histogram": {"25": 2},
                "detector_tof_us": [100.0],
                "detector_tof_fwhm_us": None,
                "mass_resolution_t_over_2fwhm": None,
            }
            safe_exits = [
                {"kind": "accelerator_safe_exit", "ion": ion} for ion in (97, 98)
            ]
            with mock_recorded_scientific_events(safe_exits), \
                    patch.object(two_prism_simion_trial, "summarize_events", return_value=cohort) as summarize:
                result = analyze_trial(
                    log_path=log, trial_receipt_path=receipt,
                    output_path=root / "observation.json",
                )
            self.assertEqual(result["status"], "bunch_observed")
            self.assertTrue(result["cohort_analysis"]["accelerator_safe_exit_complete"])
            self.assertEqual(result["cohort_analysis"]["detection_rate"], 0.5)
            self.assertEqual(result["qualification"], "candidate_bunch_selection_diagnostic__not_formal")
            self.assertEqual(summarize.call_args.kwargs["expected_particle_ids"], (97, 98))
            self.assertEqual(summarize.call_args.args[2], 2)
            self.assertEqual(summarize.call_args.kwargs["charge_e"], 1.0)
            self.assertEqual(
                summarize.call_args.kwargs["theoretical_transverse_energy_per_charge_v"], 0.0,
            )
            self.assertEqual(
                summarize.call_args.kwargs["theoretical_release_slow_energy_per_charge_v"], 5.0,
            )
            self.assertEqual(
                summarize.call_args.kwargs["theoretical_axial_energy_per_charge_v"], 4000.0,
            )
            self.assertEqual(
                summarize.call_args.kwargs["transverse_energy_tolerance_per_charge_v"], 0.01,
            )
            self.assertEqual(
                summarize.call_args.kwargs["slow_energy_tolerance_per_charge_v"], 0.02,
            )
            self.assertEqual(
                summarize.call_args.kwargs["axial_energy_tolerance_per_charge_v"], 0.03,
            )

    def test_one_particle_frozen_selection_uses_bunch_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_switch": None,
                "prism_voltages_v": [177.0, -179.0],
                "source_particle_count": 1,
                "source_cohort": {"role": "frozen_selection"},
                "source_expected_particle_ids": [1],
                "source_selection": {"particle_id_min": 1, "particle_id_max": 1},
                "selected_axial_energy_per_charge_v": 4000.0,
                "particle_mass_th": 524.0,
                "target_drift_period_ratio": 25.5,
                "accelerator_pulse": {"mode": "static"},
            }), encoding="utf-8")
            log = root / "flight.log"
            log.write_text("status,Fly completed. 1 splats\n", encoding="utf-8")
            cohort = {
                "event_integrity_passed": True,
                "particle_terminal_count": 1,
                "splat_code_histogram": {"1": 1},
                "all_losses_retained": True,
            }
            safe_exit = [{"kind": "accelerator_safe_exit", "ion": 1}]
            with mock_recorded_scientific_events(safe_exit), \
                    patch.object(two_prism_simion_trial, "summarize_events", return_value=cohort) as summarize:
                result = analyze_trial(
                    log_path=log,
                    trial_receipt_path=receipt,
                    output_path=root / "observation.json",
                )
            self.assertEqual(result["status"], "bunch_observed")
            self.assertIsNone(result["source_release_state"])
            summarize.assert_called_once()
            self.assertEqual(summarize.call_args.kwargs["expected_particle_ids"], (1,))

    def test_controlled_cohort_publishes_canonical_release_without_assuming_id1_center(self) -> None:
        center = {
            "particle_id": 1, "position_workbench_mm": [0.0, -56.0, 32.0],
            "direction_workbench": [0.0, 1.0, 0.0], "kinetic_energy_ev": 5.374,
            "mass_th": 524.0, "charge_e": 1, "tob_us": 0.125,
        }
        for frozen_center in (center, None):
            with self.subTest(controlled=frozen_center is not None), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                trial = {
                    "prism_voltages_v": [177.0, -179.0], "source_particle_count": 1,
                    "source_cohort": {"role": "controlled_diagnostic" if frozen_center else "formal_volume"},
                    "source_expected_particle_ids": [1], "source_center_state": frozen_center,
                    "selected_axial_energy_per_charge_v": 4000.0, "particle_mass_th": 524.0,
                    "target_drift_period_ratio": 24.5, "accelerator_pulse": {"mode": "static"},
                    "execution_scope": "accelerator_safe_exit_envelope_only",
                }
                receipt = root / "trial.json"
                receipt.write_text(json.dumps(trial), encoding="utf-8")
                log = root / "flight.log"
                log.write_text("status,Fly completed. 1 splats\n", encoding="utf-8")
                with mock_recorded_scientific_events([]), \
                        patch.object(two_prism_simion_trial, "summarize_events", return_value={
                            "event_integrity_passed": True, "particle_terminal_count": 1,
                            "splat_code_histogram": {"1": 1}, "all_losses_retained": True,
                        }):
                    result = analyze_trial(log_path=log, trial_receipt_path=receipt, output_path=root / "observation.json")
                source = result["source_release_state"]
                if frozen_center is None:
                    self.assertIsNone(source)
                else:
                    self.assertEqual(source["position_mm"], center["position_workbench_mm"])
                    self.assertEqual(source["direction_project"], [0.0, 1.0, 0.0])
                    self.assertEqual(source["particle_mass_th"], 524.0)
                    self.assertEqual(source["charge_state"], 1)
                    self.assertEqual(source["time_us"], 0.125)
                    self.assertAlmostEqual(source["kinetic_energy_ev"], 5.374)
                    self.assertGreater(source["velocity_mm_per_us"][1], 0.0)

    def test_complete_trial_reports_L_and_fractional_K_residuals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_voltages_v": [177.0, -180.0],
                "source_position_project_mm": [0.0, -55.0, 0.0],
                **self._single_center_source_fields(),
                "target_positive_mirror_turn_y_mm": 0.0,
                "target_low_field_tangent_ratio_vy_over_vz": 0.5,
                "target_slow_turn_y_mm": 340.0,
                "target_drift_period_ratio": 25.5,
                "target_half_oscillation_count": 51,
                "particle_mass_th": 524.0,
                "charge_state": 1,
                "flight_scope": "complete_three_dimensional_static_return",
            }), encoding="utf-8")
            log = root / "flight.log"
            log.write_text("\n".join([
                "MRTOF_EVENT prism_pass ion=1 n=1 t_us=1 x_mm=0 y_mm=-40 z_mm=-101 vx_mm_us=0 vy_mm_us=1 vz_mm_us=-2",
                "MRTOF_EVENT pre_injection_mirror_turn ion=1 t_us=2 x_mm=0 y_mm=-30 z_mm=-280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT prism_pass ion=1 n=2 t_us=3 x_mm=0 y_mm=-10 z_mm=97 vx_mm_us=0 vy_mm_us=1 vz_mm_us=2",
                "MRTOF_EVENT pre_origin_positive_mirror_turn ion=1 t_us=3.5 x_mm=0 y_mm=0 z_mm=280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT drift_phase_origin ion=1 t_us=4 x_mm=0 y_mm=0 z_mm=0 vx_mm_us=0 vy_mm_us=1.358049167 vz_mm_us=-2",
                "MRTOF_EVENT slow_turn ion=1 n=1 t_us=10 x_mm=0 y_mm=258.75 z_mm=0",
                "MRTOF_EVENT drift_coordinate_return ion=1 k_before=19 fractional_k=19.014 phase_crossing_t_us=20 phase_crossing_y_mm=0.5 phase_time_residual_us=0.4 phase_period_us=30 t_us=20.4 x_mm=0 y_mm=0 z_mm=280 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=-2",
                "MRTOF_EVENT terminal ion=1 splat=-1 t_us=21 x_mm=0 y_mm=-1 z_mm=0 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=-2 turns=38 central_crossings=38",
            ]) + "\n", encoding="utf-8")
            output = root / "observation.json"
            result = self._analyze_with_handoff_events(
                log=log, receipt=receipt, output=output,
            )
            self.assertEqual(result["status"], "full_drift_observed", result)
            self.assertEqual(result["residuals"]["P1_P2_positive_mirror_turn_y_mm"], 0.0)
            self.assertEqual(
                result["residuals"]["P1_P2_P2_shield_low_field_signed_vy_over_vz"], 0.0
            )
            self.assertEqual(
                result["p2_low_field_reference_state"]["velocity_mm_per_us"],
                (0.0, 1.0, 2.0),
            )
            self.assertAlmostEqual(result["residuals"]["Stripe_slow_turn_y_minus_L_mm"], -81.25)
            self.assertAlmostEqual(result["residuals"]["Stripe_fractional_K_minus_target"], -6.486)
            self.assertAlmostEqual(
                result["residuals"]["Stripe_preceding_phase_y_minus_origin_mm"], 0.5
            )
            self.assertNotIn("Stripe_target_phase_y_minus_origin_mm", result["residuals"])

    def test_coordinate_return_before_target_phase_is_reported_without_fabricating_sample(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_voltages_v": [190.6, -191.94],
                "source_position_project_mm": [0.0, -55.0, 0.0],
                **self._single_center_source_fields(),
                "target_positive_mirror_turn_y_mm": 0.0,
                "target_low_field_tangent_ratio_vy_over_vz": 0.5,
                "target_slow_turn_y_mm": 340.0,
                "target_drift_period_ratio": 25.5,
                "target_half_oscillation_count": 51,
                "particle_mass_th": 524.0,
                "charge_state": 1,
                "flight_scope": "complete_three_dimensional_static_return",
            }), encoding="utf-8")
            log = root / "flight.log"
            log.write_text("\n".join([
                "MRTOF_EVENT prism_pass ion=1 n=1 t_us=1 x_mm=0 y_mm=-40 z_mm=-101 vx_mm_us=0 vy_mm_us=1 vz_mm_us=-2",
                "MRTOF_EVENT pre_injection_mirror_turn ion=1 t_us=2 x_mm=0 y_mm=-30 z_mm=-280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT prism_pass ion=1 n=2 t_us=3 x_mm=0 y_mm=-10 z_mm=97 vx_mm_us=0 vy_mm_us=1 vz_mm_us=2",
                "MRTOF_EVENT pre_origin_positive_mirror_turn ion=1 t_us=3.5 x_mm=0 y_mm=0 z_mm=280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT drift_phase_origin ion=1 t_us=4 x_mm=0 y_mm=0 z_mm=280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT slow_turn ion=1 n=1 t_us=10 x_mm=0 y_mm=338 z_mm=0",
                "MRTOF_EVENT drift_coordinate_return ion=1 k_before=25 fractional_k=25 t_us=20 x_mm=0 y_mm=0 z_mm=101 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=-40",
                "MRTOF_EVENT terminal ion=1 splat=-1 t_us=21 x_mm=0 y_mm=-0.15 z_mm=97 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=-40 turns=50 central_crossings=50",
            ]) + "\n", encoding="utf-8")
            result = self._analyze_with_handoff_events(
                log=log, receipt=receipt, output=root / "observation.json",
            )
            self.assertEqual(result["status"], "full_drift_observed", result)
            self.assertEqual(result["fractional_k"], 25.0)
            self.assertEqual(result["target_phase_y_mm"], None)
            self.assertEqual(
                result["return_topology"], "coordinate_return_before_target_phase"
            )
            self.assertEqual(result["residuals"]["Stripe_fractional_K_minus_target"], -0.5)
            self.assertNotIn("Stripe_target_phase_y_minus_origin_mm", result["residuals"])

    def test_coordinate_return_preserves_later_observed_target_phase_sample(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_voltages_v": [190.6, -191.94],
                "source_position_project_mm": [0.0, -55.0, 0.0],
                **self._single_center_source_fields(),
                "target_positive_mirror_turn_y_mm": 0.0,
                "target_low_field_tangent_ratio_vy_over_vz": 0.5,
                "target_slow_turn_y_mm": 340.0,
                "target_drift_period_ratio": 25.5,
                "target_half_oscillation_count": 51,
                "particle_mass_th": 524.0,
                "charge_state": 1,
                "flight_scope": "complete_three_dimensional_static_return",
            }), encoding="utf-8")
            log = root / "flight.log"
            log.write_text("\n".join([
                "MRTOF_EVENT prism_pass ion=1 n=1 t_us=1 x_mm=0 y_mm=-40 z_mm=-101 vx_mm_us=0 vy_mm_us=1 vz_mm_us=-2",
                "MRTOF_EVENT pre_injection_mirror_turn ion=1 t_us=2 x_mm=0 y_mm=-30 z_mm=-280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT prism_pass ion=1 n=2 t_us=3 x_mm=0 y_mm=-10 z_mm=97 vx_mm_us=0 vy_mm_us=1 vz_mm_us=2",
                "MRTOF_EVENT pre_origin_positive_mirror_turn ion=1 t_us=3.5 x_mm=0 y_mm=0 z_mm=280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT drift_phase_origin ion=1 t_us=4 x_mm=0 y_mm=0 z_mm=280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT slow_turn ion=1 n=1 t_us=10 x_mm=0 y_mm=340.2 z_mm=0",
                "MRTOF_EVENT drift_coordinate_return ion=1 k_before=25 fractional_k=25.4 phase_crossing_t_us=100 phase_crossing_y_mm=6 phase_time_residual_us=12 phase_period_us=30 t_us=112 x_mm=0 y_mm=0 z_mm=-160 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=-40",
                "MRTOF_EVENT target_k_phase_sample ion=1 k=25.5 half_cycles=51 t_us=115 x_mm=0 y_mm=-4.5 z_mm=-280 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=0",
                "MRTOF_EVENT drift_phase_return ion=1 k=25.5 half_cycles=51 slow_coordinate_residual_mm=-4.5 t_us=115 x_mm=0 y_mm=-4.5 z_mm=-280 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=0",
                "MRTOF_EVENT terminal ion=1 splat=1 t_us=120 x_mm=0 y_mm=-53 z_mm=97 vx_mm_us=0 vy_mm_us=-3 vz_mm_us=-40 turns=51 central_crossings=51",
            ]) + "\n", encoding="utf-8")
            result = self._analyze_with_handoff_events(
                log=log, receipt=receipt, output=root / "observation.json",
            )
            self.assertEqual(result["return_topology"], "coordinate_return_before_target_phase")
            self.assertEqual(result["target_phase_y_mm"], -4.5)
            self.assertEqual(
                result["residuals"]["Stripe_target_phase_y_minus_origin_mm"], -4.5
            )

    def test_old_coordinate_return_log_recovers_continuous_k_from_same_side_turns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_voltages_v": [190.6, -191.94],
                "source_position_project_mm": [0.0, -55.0, 0.0],
                **self._single_center_source_fields(),
                "target_positive_mirror_turn_y_mm": 0.0,
                "target_low_field_tangent_ratio_vy_over_vz": 0.5,
                "target_slow_turn_y_mm": 340.0,
                "target_drift_period_ratio": 25.5,
                "target_half_oscillation_count": 51,
                "particle_mass_th": 524.0,
                "charge_state": 1,
                "flight_scope": "complete_three_dimensional_static_return",
            }), encoding="utf-8")
            log = root / "flight.log"
            log.write_text("\n".join([
                "MRTOF_EVENT prism_pass ion=1 n=1 t_us=1 x_mm=0 y_mm=-40 z_mm=-101 vx_mm_us=0 vy_mm_us=1 vz_mm_us=-2",
                "MRTOF_EVENT pre_injection_mirror_turn ion=1 t_us=2 x_mm=0 y_mm=-30 z_mm=-280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT prism_pass ion=1 n=2 t_us=3 x_mm=0 y_mm=-10 z_mm=97 vx_mm_us=0 vy_mm_us=1 vz_mm_us=2",
                "MRTOF_EVENT pre_origin_positive_mirror_turn ion=1 t_us=3.5 x_mm=0 y_mm=0 z_mm=280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT drift_phase_origin ion=1 t_us=4 x_mm=0 y_mm=0 z_mm=280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT slow_turn ion=1 n=1 t_us=10 x_mm=0 y_mm=338 z_mm=0",
                "MRTOF_EVENT drift_phase_candidate ion=1 k=24 half_cycles=48 t_us=70 x_mm=0 y_mm=20 z_mm=280 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=0",
                "MRTOF_EVENT drift_phase_candidate ion=1 k=24.5 half_cycles=49 t_us=85 x_mm=0 y_mm=15 z_mm=-280 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=0",
                "MRTOF_EVENT drift_phase_candidate ion=1 k=25 half_cycles=50 t_us=100 x_mm=0 y_mm=6 z_mm=280 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=0",
                "MRTOF_EVENT drift_coordinate_return ion=1 k_before=25 fractional_k=25 t_us=109 x_mm=0 y_mm=0 z_mm=101 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=-40",
                "MRTOF_EVENT terminal ion=1 splat=-1 t_us=110 x_mm=0 y_mm=-0.15 z_mm=97 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=-40 turns=50 central_crossings=50",
            ]) + "\n", encoding="utf-8")
            result = self._analyze_with_handoff_events(
                log=log, receipt=receipt, output=root / "observation.json",
            )
            self.assertAlmostEqual(result["fractional_k"], 25.3)
            self.assertIsNone(result["target_phase_y_mm"])
            self.assertEqual(result["preceding_phase_y_mm"], 6.0)
            self.assertEqual(
                result["return_topology"], "coordinate_return_before_target_phase"
            )
            self.assertAlmostEqual(
                result["residuals"]["Stripe_preceding_phase_y_minus_origin_mm"], 6.0
            )
            self.assertNotIn("Stripe_target_phase_y_minus_origin_mm", result["residuals"])

    def test_exact_target_k_phase_return_is_full_drift_and_reports_static_detector(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_voltages_v": [177.0, -180.0],
                "source_position_project_mm": [0.0, -55.0, 0.0],
                **self._single_center_source_fields(),
                "target_positive_mirror_turn_y_mm": 0.0,
                "target_low_field_tangent_ratio_vy_over_vz": 0.5,
                "target_slow_turn_y_mm": 340.0,
                "target_drift_period_ratio": 25.5,
                "target_half_oscillation_count": 51,
                "particle_mass_th": 524.0,
                "charge_state": 1,
                "flight_scope": "complete_three_dimensional_static_return",
                "prism_switch": None,
            }), encoding="utf-8")
            return_p2 = "x_mm=0 y_mm=0 z_mm=0 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=1"
            detector_state = "x_mm=0 y_mm=0 z_mm=0 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=-1"
            target_turn = "x_mm=0 y_mm=0 z_mm=-280 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=0"
            positive_turn = "x_mm=0 y_mm=0 z_mm=280 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=0"
            log = root / "flight.log"
            log.write_text("\n".join([
                "MRTOF_EVENT accelerator_safe_exit ion=1 t_us=0.5 from_instance=3 to_instance=1 x_mm=0 y_mm=-55 z_mm=40 vx_mm_us=0 vy_mm_us=0.043 vz_mm_us=-39",
                "MRTOF_EVENT prism_entry ion=1 n=1 t_us=0.75 x_mm=0 y_mm=-45 z_mm=-90 vx_mm_us=0 vy_mm_us=0.05 vz_mm_us=-38",
                "MRTOF_EVENT prism_pass ion=1 n=1 t_us=1 x_mm=0 y_mm=-40 z_mm=-101 vx_mm_us=0 vy_mm_us=1 vz_mm_us=-2",
                "MRTOF_EVENT pre_injection_mirror_turn ion=1 t_us=2 x_mm=0 y_mm=-30 z_mm=-280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT prism_pass ion=1 n=2 t_us=3 x_mm=0 y_mm=-10 z_mm=97 vx_mm_us=0 vy_mm_us=1 vz_mm_us=2",
                "MRTOF_EVENT pre_origin_positive_mirror_turn ion=1 t_us=3.5 x_mm=0 y_mm=0 z_mm=280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT drift_phase_origin ion=1 t_us=4 x_mm=0 y_mm=0 z_mm=0 vx_mm_us=0 vy_mm_us=1.358049167 vz_mm_us=-2",
                "MRTOF_EVENT slow_turn ion=1 n=1 t_us=10 x_mm=0 y_mm=340 z_mm=0",
                "MRTOF_EVENT drift_phase_candidate ion=1 k=25.5 half_cycles=51 t_us=20 " + target_turn,
                "MRTOF_EVENT target_k_phase_sample ion=1 k=25.5 half_cycles=51 t_us=20 " + target_turn,
                "MRTOF_EVENT drift_coordinate_return ion=1 k_before=25.5 fractional_k=25.5 "
                "phase_crossing_t_us=20 phase_crossing_y_mm=0 phase_time_residual_us=0 "
                "phase_period_us=1 t_us=20 " + target_turn,
                "MRTOF_EVENT drift_phase_return ion=1 k=25.5 half_cycles=51 t_us=20 " + target_turn,
                "MRTOF_EVENT target_k ion=1 k=25.5 half_cycles=51 t_us=20 x_mm=0 y_mm=0 z_mm=0",
                "MRTOF_EVENT return_p2_entry ion=1 t_us=21 " + return_p2,
                "MRTOF_EVENT return_p2_pass ion=1 t_us=22 " + return_p2,
                "MRTOF_EVENT return_positive_mirror_turn ion=1 t_us=23 " + positive_turn,
                "MRTOF_EVENT detector_plane ion=1 direction_z=-1 t_us=26 " + detector_state,
                "MRTOF_EVENT detector ion=1 direction_z=-1 t_us=26 x_mm=0 y_mm=-50 z_mm=95",
                "MRTOF_EVENT splat ion=1 code=1 t_us=26 x_mm=0 y_mm=-50 z_mm=95 turns=50 central_crossings=50",
                "MRTOF_EVENT terminal ion=1 splat=1 t_us=26 x_mm=0 y_mm=-50 z_mm=95 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=-1 turns=50 central_crossings=50",
            ]) + "\n", encoding="utf-8")
            result = self._analyze_with_handoff_events(
                log=log, receipt=receipt, output=root / "observation.json",
            )
            self.assertEqual(result["status"], "full_drift_observed", result)
            self.assertEqual(result["fractional_k"], 25.5)
            self.assertEqual(result["return_topology"], "exact_target_k_phase_return")
            self.assertEqual(result["residuals"]["Stripe_fractional_K_minus_target"], 0.0)
            self.assertEqual(result["residuals"]["Stripe_target_phase_y_minus_origin_mm"], 0.0)
            source = result["source_release_state"]
            self.assertAlmostEqual(source["kinetic_energy_per_charge_v"], 5.0)
            self.assertEqual(source["direction_project"], [0.0, 1.0, 0.0])
            self.assertNotEqual(source["velocity_mm_per_us"], [0.0, 1.0, 0.0])
            safe_exit = result["accelerator_safe_exit_observation"]
            self.assertEqual(safe_exit["status"], "observed")
            self.assertEqual(
                safe_exit["p1_ordering"], "verified_safe_exit_before_P1_entry"
            )
            self.assertEqual(safe_exit["state"]["velocity_mm_per_us"], [0.0, 0.043, -39.0])
            self.assertEqual(safe_exit["input_log"]["sha256"], hashlib.sha256(log.read_bytes()).hexdigest())
            self.assertEqual(
                safe_exit["trial_identity"]["sha256"], hashlib.sha256(receipt.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                result["static_return_diagnostic"]["status"], "detector_hit",
                result["static_return_diagnostic"],
            )
            self.assertEqual(result["extraction_diagnostic"]["status"], "detector_hit")

    def test_complete_trial_fails_closed_without_return(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_voltages_v": [177.0, -180.0],
                "source_position_project_mm": [0.0, -55.0, 0.0],
                **self._single_center_source_fields(),
                "target_positive_mirror_turn_y_mm": 0.0,
                "target_low_field_tangent_ratio_vy_over_vz": 0.5,
                "target_slow_turn_y_mm": 340.0,
                "target_drift_period_ratio": 25.5,
                "target_half_oscillation_count": 51,
                "particle_mass_th": 524.0,
                "charge_state": 1,
                "flight_scope": "complete_three_dimensional_static_return",
            }), encoding="utf-8")
            log = root / "flight.log"
            log.write_text("\n".join([
                "MRTOF_EVENT prism_pass ion=1 n=1 t_us=1 x_mm=0 y_mm=-40 z_mm=-101 vx_mm_us=0 vy_mm_us=1 vz_mm_us=-2",
                "MRTOF_EVENT pre_injection_mirror_turn ion=1 t_us=2 x_mm=0 y_mm=-30 z_mm=-280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT prism_pass ion=1 n=2 t_us=3 x_mm=0 y_mm=-10 z_mm=97 vx_mm_us=0 vy_mm_us=1 vz_mm_us=2",
                "MRTOF_EVENT pre_origin_positive_mirror_turn ion=1 t_us=3.5 x_mm=0 y_mm=0 z_mm=280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT drift_phase_origin ion=1 t_us=4 x_mm=0 y_mm=0 z_mm=0 vx_mm_us=0 vy_mm_us=1.358049167 vz_mm_us=-2",
                "MRTOF_EVENT terminal ion=1 splat=-1 t_us=5 x_mm=0 y_mm=1 z_mm=0 vx_mm_us=0 vy_mm_us=1 vz_mm_us=-2 turns=0 central_crossings=0",
            ]) + "\n", encoding="utf-8")
            result = analyze_trial(
                log_path=log,
                trial_receipt_path=receipt,
                output_path=root / "observation.json",
            )
            self.assertEqual(
                result["status"],
                "p2_low_field_and_positive_mirror_turn_incomplete",
                result,
            )
            self.assertIn("low-field", result["incomplete_reason"])
            self.assertNotIn(
                "Stripe_fractional_K_minus_target", result.get("residuals", {})
            )
            self.assertEqual(
                result["accelerator_safe_exit_observation"]["status"], "not_observed"
            )

    def test_accelerator_safe_exit_rejects_duplicates_nonfinite_and_wrong_direction(self) -> None:
        trial = {
            "particle_mass_th": 524.0,
            "charge_state": 1,
            "source_time_of_birth_us": 0.0,
        }
        base = {
            "kind": "accelerator_safe_exit", "ion": 1, "t_us": 0.5,
            "from_instance": 3, "to_instance": 1,
            "x_mm": 0.0, "y_mm": -55.0, "z_mm": 40.0,
            "vx_mm_us": 0.0, "vy_mm_us": 0.04, "vz_mm_us": -39.0,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "flight.log"
            receipt = root / "trial.json"
            log.write_text("event bytes\n", encoding="utf-8")
            receipt.write_text("{}\n", encoding="utf-8")
            duplicate = _accelerator_safe_exit_observation(
                [base, dict(base)], trial, log_path=log, trial_receipt_path=receipt,
            )
            self.assertEqual(duplicate["status"], "invalid")
            self.assertIsNone(duplicate["state"])
            nonfinite_event = dict(base, x_mm=float("nan"))
            nonfinite = _accelerator_safe_exit_observation(
                [nonfinite_event], trial, log_path=log, trial_receipt_path=receipt,
            )
            self.assertEqual(nonfinite["status"], "invalid")
            self.assertIsNone(nonfinite["state"])
            wrong_direction = _accelerator_safe_exit_observation(
                [dict(base, vz_mm_us=39.0)], trial,
                log_path=log, trial_receipt_path=receipt,
            )
            self.assertEqual(wrong_direction["status"], "invalid")
            self.assertIn(
                "accelerator_safe_exit_must_travel_toward_negative_project_z",
                wrong_direction["errors"],
            )
            invalid_instance = _accelerator_safe_exit_observation(
                [dict(base, from_instance=1)], trial,
                log_path=log, trial_receipt_path=receipt,
            )
            self.assertEqual(invalid_instance["status"], "invalid")
            pass_only = _accelerator_safe_exit_observation(
                [base, {
                    "kind": "prism_pass", "ion": 1, "n": 1, "t_us": 0.8,
                    "x_mm": 0.0, "y_mm": -40.0, "z_mm": -101.0,
                    "vx_mm_us": 0.0, "vy_mm_us": 0.05, "vz_mm_us": -38.0,
                }],
                trial, log_path=log, trial_receipt_path=receipt,
            )
            self.assertEqual(pass_only["status"], "observed")
            self.assertEqual(
                pass_only["p1_ordering"],
                "before_P1_pass_only__P1_entry_not_observed",
            )
            native_exit = _accelerator_safe_exit_observation(
                [dict(base, from_instance=3, to_instance=2)],
                {**trial, "accelerator_instance": 3},
                log_path=log, trial_receipt_path=receipt,
            )
            self.assertEqual(native_exit["status"], "observed")
            self.assertEqual(native_exit["state"]["from_instance"], 3)
            biased_exit = _accelerator_safe_exit_observation(
                [dict(base, vx_mm_us=0.001)],
                {
                    **trial,
                    "source_transverse_reference": {
                        "center_x_mm": 0.0,
                        "center_vx_mm_per_us": 0.0,
                    },
                    "accelerator_exit_energy_contract": {
                        "maximum_exit_transverse_velocity_bias_mm_per_us": 0.0001,
                    },
                },
                log_path=log, trial_receipt_path=receipt,
            )
            self.assertEqual(biased_exit["status"], "invalid")
            self.assertFalse(biased_exit["signed_transverse_bias"]["passed"])
            pass_before_exit = _accelerator_safe_exit_observation(
                [{
                    "kind": "prism_pass", "ion": 1, "n": 1, "t_us": 0.4,
                    "x_mm": 0.0, "y_mm": -40.0, "z_mm": -101.0,
                    "vx_mm_us": 0.0, "vy_mm_us": 0.05, "vz_mm_us": -38.0,
                }, base],
                trial, log_path=log, trial_receipt_path=receipt,
            )
            self.assertEqual(pass_before_exit["status"], "invalid")
            self.assertIn(
                "accelerator_safe_exit_does_not_precede_P1_pass",
                pass_before_exit["errors"],
            )
            before_release = _accelerator_safe_exit_observation(
                [base], {**trial, "source_time_of_birth_us": 0.6},
                log_path=log, trial_receipt_path=receipt,
            )
            self.assertEqual(before_release["status"], "invalid")
            self.assertIn(
                "accelerator_safe_exit_cannot_precede_source_release",
                before_release["errors"],
            )
            wrong_order = _accelerator_safe_exit_observation(
                [base, {
                    "kind": "prism_entry", "ion": 1, "n": 1, "t_us": 0.4,
                    "x_mm": 0.0, "y_mm": -45.0, "z_mm": -90.0,
                    "vx_mm_us": 0.0, "vy_mm_us": 0.05, "vz_mm_us": -38.0,
                }],
                trial, log_path=log, trial_receipt_path=receipt,
            )
            self.assertEqual(wrong_order["status"], "invalid")
            self.assertIn("accelerator_safe_exit_does_not_precede_P1", wrong_order["errors"])


if __name__ == "__main__":
    unittest.main()
