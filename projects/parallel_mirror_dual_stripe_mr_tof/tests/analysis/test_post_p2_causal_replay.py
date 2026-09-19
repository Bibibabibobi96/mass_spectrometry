from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.post_p2_causal_replay import (
    _record,
    analyze_replay_log,
    extract_replay_rows,
    render_replay_fly2,
    render_replay_operating_point,
    resolve_immutable_operating_bundle,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


PROJECT = Path(__file__).resolve().parents[2]


def event(kind: str, ion: int, **fields):
    return {"kind": kind, "ion": ion, **fields}


class PostP2CausalReplayTests(unittest.TestCase):
    def test_extract_and_render_paired_cases(self):
        events = {}
        for ion, vz, detector_time in ((1, 40.0, 15.0), (3, 42.0, 16.0)):
            events[("return_p2_pass", ion)] = [event(
                "return_p2_pass", ion, t_us=1.0, x_mm=0.1 * ion, y_mm=-12,
                z_mm=42, vx_mm_us=0.2, vy_mm_us=-3, vz_mm_us=vz,
            )]
            events[("return_positive_mirror_turn", ion)] = [event(
                "return_positive_mirror_turn", ion, t_us=10.0, z_mm=282,
            )]
            events[("detector", ion)] = [event("detector", ion, t_us=detector_time)]
            events[("terminal", ion)] = [event("terminal", ion, splat=1)]
        rows = extract_replay_rows(
            events=events,
            source_rows={1: {"z_mm": -0.1}, 2: {"z_mm": 0}, 3: {"z_mm": 0.1}},
            particle_count=3,
        )
        self.assertEqual([row["replay_particle_id"] for row in rows], [1, 2])
        self.assertEqual([row["source_particle_id"] for row in rows], [1, 3])
        self.assertEqual([row["reference_turn_to_detector_us"] for row in rows], [5, 6])
        original = render_replay_fly2(rows, mass_th=524, charge_e=1, case="original")
        dechirped = render_replay_fly2(
            rows, mass_th=524, charge_e=1, case="vz_dechirp", dechirped_vz_mm_us=41,
        )
        self.assertEqual(original.count("standard_beam {"), 2)
        self.assertEqual(dechirped.count("standard_beam {"), 2)
        self.assertIn("color = 1", original)
        self.assertIn("color = 2", original)
        self.assertNotEqual(original, dechirped)
        # Positions and transverse velocity directions remain paired; only vz/KE change.
        self.assertIn("position = vector(0.10000000000000001,-12,42)", dechirped)

    def test_operating_point_requires_reviewed_terminal_plane(self):
        trial = {
            "detector_box_mm": [-25, -87, 95, 25, -37, 97],
            "trajectory_profile": {"trajectory_quality": 8, "maximum_step_us": 0.002},
            "patch_interface_planes_project": [
                {"name": "mirror_min", "region": "mirror_turn_positive", "axis": "z",
                 "face": "z_min", "coordinate_mm": 97},
                {"name": "mirror_max", "region": "mirror_turn_positive", "axis": "z",
                 "face": "z_max", "coordinate_mm": 330},
                {"name": "handoff_positive_bridge_to_mirror__z_plane", "region": "local_handoff",
                 "axis": "z", "face": "z_plane", "coordinate_mm": 105,
                 "u_min_mm": -20, "u_max_mm": 20, "v_min_mm": -147, "v_max_mm": 463},
            ],
        }
        rendered = render_replay_operating_point(trial)
        self.assertIn("z_mm=105", rendered)
        self.assertIn("replay_branch='mechanical_detector'", rendered)
        self.assertIn("accelerator_field_state='grounded_after_frozen_pulse'", rendered)
        self.assertIn("transparent_planes_z_mm={97,72,26,0}", rendered)
        self.assertIn("post_p2_timeout_us=20", rendered)
        trial["patch_interface_planes_project"][-1]["coordinate_mm"] = 104
        with self.assertRaisesRegex(CandidateContractError, "z=105"):
            render_replay_operating_point(trial)

    def test_analysis_retains_collision_and_per_particle_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            states = root / "states.csv"
            with states.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=(
                    "replay_particle_id", "source_particle_id", "reference_turn_to_detector_us",
                    "t_us",
                ))
                writer.writeheader()
                writer.writerow({"replay_particle_id": 1, "source_particle_id": 11,
                                 "reference_turn_to_detector_us": 5.0})
                writer.writerow({"replay_particle_id": 2, "source_particle_id": 19,
                                 "reference_turn_to_detector_us": 5.2})
            receipt = root / "receipt.json"
            receipt.write_text(json.dumps({
                "role": "mrtof_post_p2_conditional_causal_replay_source",
                "conditional_particle_count": 2,
                "reference_states": _record(states),
            }), encoding="utf-8")
            log = root / "flight.log"
            log.write_text("\n".join((
                "MRTOF_EVENT return_positive_mirror_turn ion=1 t_us=1 x_mm=0 y_mm=0 z_mm=282 vx_mm_us=0 vy_mm_us=0 vz_mm_us=0",
                "MRTOF_EVENT detector ion=1 direction_z=-1 t_us=6.001 x_mm=0 y_mm=0 z_mm=97",
                "MRTOF_EVENT splat ion=1 code=1 t_us=6.001 x_mm=0 y_mm=0 z_mm=97 turns=1 central_crossings=0",
                "MRTOF_EVENT terminal ion=1 splat=1 t_us=6.001 x_mm=0 y_mm=0 z_mm=97 vx_mm_us=0 vy_mm_us=0 vz_mm_us=-1 turns=1 central_crossings=0",
                "MRTOF_EVENT splat ion=2 code=-1 t_us=2 x_mm=0 y_mm=0 z_mm=200 turns=0 central_crossings=0",
                "MRTOF_EVENT terminal ion=2 splat=-1 t_us=2 x_mm=0 y_mm=0 z_mm=200 vx_mm_us=0 vy_mm_us=0 vz_mm_us=1 turns=0 central_crossings=0",
                "status,Fly completed. 2 splats",
            )) + "\n", encoding="utf-8")
            result = analyze_replay_log(receipt_path=receipt, case="original", log_path=log)
            self.assertEqual(result["detector_hit_count"], 1)
            self.assertEqual(result["electrode_collision_count"], 1)
            self.assertTrue(result["all_conditional_particles_retained"])
            self.assertEqual(result["peak_filtering"], "none")
            self.assertAlmostEqual(
                result["baseline_per_particle_comparison"][0]["difference_us"], 0.001,
            )
            self.assertIsNone(result["baseline_per_particle_comparison"][1]["difference_us"])

    def test_transparent_branch_reports_each_real_crossing_and_early_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            states = root / "states.csv"
            with states.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=(
                    "replay_particle_id", "source_particle_id", "reference_turn_to_detector_us",
                    "t_us",
                ))
                writer.writeheader()
                writer.writerows((
                    {"replay_particle_id": 1, "source_particle_id": 11,
                     "reference_turn_to_detector_us": 5, "t_us": 100},
                    {"replay_particle_id": 2, "source_particle_id": 19,
                     "reference_turn_to_detector_us": 5.2, "t_us": 101},
                ))
            receipt = root / "receipt.json"
            receipt.write_text(json.dumps({
                "role": "mrtof_post_p2_conditional_causal_replay_source",
                "conditional_particle_count": 2, "reference_states": _record(states),
            }), encoding="utf-8")
            lines = []
            for label, time, z in (("detector_z97", 5, 97), ("handoff_z72", 6, 72),
                                   ("p2_near_z26", 7, 26), ("focus_z0", 8, 0)):
                lines.append(
                    f"MRTOF_EVENT replay_plane ion=1 label={label} direction_z=-1 t_us={time} "
                    f"x_mm=0 y_mm=0 z_mm={z} vx_mm_us=0 vy_mm_us=0 vz_mm_us=-1"
                )
            lines.extend((
                "MRTOF_EVENT splat ion=1 code=3 t_us=8 x_mm=0 y_mm=0 z_mm=0 turns=1 central_crossings=0",
                "MRTOF_EVENT terminal ion=1 splat=3 t_us=8 x_mm=0 y_mm=0 z_mm=0 vx_mm_us=0 vy_mm_us=0 vz_mm_us=-1 turns=1 central_crossings=0",
                "MRTOF_EVENT replay_plane ion=2 label=detector_z97 direction_z=-1 t_us=5 x_mm=0 y_mm=0 z_mm=97 vx_mm_us=0 vy_mm_us=0 vz_mm_us=-1",
                "MRTOF_EVENT terminal ion=2 splat=-1 t_us=5.5 x_mm=0 y_mm=0 z_mm=80 vx_mm_us=0 vy_mm_us=0 vz_mm_us=-1 turns=1 central_crossings=0",
                "status,Fly completed. 2 splats",
            ))
            log = root / "transparent.log"
            log.write_text("\n".join(lines) + "\n", encoding="utf-8")
            result = analyze_replay_log(
                receipt_path=receipt, case="original", branch="transparent_planes", log_path=log,
            )
            self.assertEqual(result["other_terminal_count"], 1)
            self.assertEqual(result["electrode_collision_count"], 1)
            self.assertEqual(
                result["transparent_plane_crossings"]["focus_z0"]["missing_particle_ids"], [2],
            )
            self.assertEqual(
                result["transparent_plane_crossings"]["detector_z97"]["crossing_count"], 2,
            )

    def test_resolves_only_manifest_bound_fixed_operating_pas(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workbench = root / "workbench"
            workbench.mkdir()
            (workbench / "run_config.json").write_text(json.dumps({
                "parameters": {"fixed_operating_pa": True, "local_mesh_mm_per_gu": [0.25] * 3},
            }), encoding="utf-8")
            names = ["analyzer.pa", *_LOCAL_NAMES_FOR_TEST(), "accelerator.pa", "detector.pa"]
            pa_paths = []
            for index, name in enumerate(names):
                path = workbench / name
                path.write_bytes(f"pa-{index}".encode())
                pa_paths.append(path)
            wb_manifest_path = workbench / "run_manifest.json"
            template_iob = workbench / "mrtof_complete_fixed_0p25mm_gui_review.iob"
            template_iob.write_bytes(b"iob")
            wb_manifest_path.write_text(json.dumps({
                "status": "success", "outputs": [
                    *[_record(path) for path in pa_paths], _record(template_iob),
                ],
            }), encoding="utf-8")
            auxiliaries = {}
            for name in ("builder", "seed", "local", "trial", "voltage", "counter", "launcher"):
                path = root / name
                path.write_text(name, encoding="utf-8")
                auxiliaries[name] = path
            hashes = [item["sha256"].upper() for item in map(_record, pa_paths)]
            portability = root / "portability.json"
            portability.write_text(json.dumps({
                "status": "success", "all_private_pa_hashes_unchanged": True,
                "instance_origins_project_mm": [[0, 0, 0]] * 8,
                "members": [{"pa_hashes_before": hashes, "pa_hashes_after": hashes}],
            }), encoding="utf-8")
            inputs = {
                "local_workbench_run_manifest": _record(wb_manifest_path),
                "read_only_analyzer_pa": _record(pa_paths[0]),
                "read_only_accelerator_pa": _record(pa_paths[-2]),
                "read_only_detector_pa": _record(pa_paths[-1]),
                "iob_builder": _record(auxiliaries["builder"]),
                "iob_seed": _record(auxiliaries["seed"]),
                "local_refinement_sidecar": _record(auxiliaries["local"]),
                "trial_materialization": _record(auxiliaries["trial"]),
                "batch_iob_bundle_portability_receipt": _record(portability),
                "voltage_map": _record(auxiliaries["voltage"]),
                "mirror_cycle_counter": _record(auxiliaries["counter"]),
                "flight_launcher": _record(auxiliaries["launcher"]),
            }
            result = resolve_immutable_operating_bundle(
                run_dir=root, manifest={"inputs": inputs},
            )
            self.assertEqual(len(result["pa_paths"]), 8)
            self.assertEqual(result["assembly_mode"],
                             "rebuild_iob_from_manifest_bound_seed_and_exact_immutable_pa_bytes__no_refine")
            pa_paths[3].unlink()
            with self.assertRaises(CandidateContractError):
                resolve_immutable_operating_bundle(run_dir=root, manifest={"inputs": inputs})

    def test_thin_lua_is_post_p2_only_and_retains_terminal_outcomes(self):
        source = (PROJECT / "simion" / "post_p2_causal_replay.lua").read_text(encoding="utf-8")
        self.assertIn("stage[ion_number],turn_count", source)
        self.assertIn("'awaiting_positive_turn'", source)
        self.assertIn("return_positive_mirror_turn", source)
        self.assertIn("handoff_positive_bridge_to_mirror__z_plane", source)
        self.assertIn("MRTOF_EVENT terminal", source)
        self.assertIn("splat_codes[ion_number]=2", source)
        self.assertIn("transparent_detector and ion_instance == 8", source)
        self.assertIn("MRTOF_EVENT replay_plane", source)
        self.assertIn("programmatic_plane_completion", source)
        self.assertIn("if ion_instance == 7 then", source)
        self.assertIn("ion_dvoltsx_gu,ion_dvoltsy_gu,ion_dvoltsz_gu = 0,0,0", source)
        self.assertNotIn("target_half_oscillation_count", source)
        self.assertNotIn("mirror_cycle_counter", source)
        self.assertNotIn("fast_adjust", source)


def _LOCAL_NAMES_FOR_TEST():
    return [
        "local_negative_mirror.pa0", "local_negative_bridge.pa0", "local_central.pa0",
        "local_positive_bridge.pa0", "local_positive_mirror.pa0",
    ]


if __name__ == "__main__":
    unittest.main()
