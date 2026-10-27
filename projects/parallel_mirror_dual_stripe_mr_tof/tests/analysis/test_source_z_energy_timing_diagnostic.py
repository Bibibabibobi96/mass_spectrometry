from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common.analysis.peak_metrics import AnalysisSettings
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import peak_time_metrics
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.bunch_source_and_schedule import (
    resolve_bunch_source_interval,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.source_z_energy_timing_diagnostic import (
    _association,
    _distribution,
    _time_plane_distribution,
    _controlled_fast_turn_history,
    _joint_initial_state_timing,
    _load_source_rows_from_paths,
    analyze_completed_source_z_energy_timing,
    analyze_controlled_aberration_first_batch,
    analyze_source_z_energy_timing,
    analyze_source_z_energy_timing_events,
    build_te1_reference_from_mirror_jacobian,
    compare_te1_diagnostics,
    materialize_scaled_te1_variation,
    materialize_te1_fine_probe,
    materialize_te1_variation_from_diagnostics,
    main,
)


PEAK_CONTRACT = json.loads((Path(__file__).resolve().parents[2] / "config/simion_candidate_two_zone.json").read_text(encoding="utf-8"))["peak_analysis"]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(path: Path) -> dict[str, object]:
    return {"path": str(path), "exists": True, "bytes": path.stat().st_size, "sha256": _sha(path)}


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _diagnostic(
    path: Path, slope: float, *, hit_count: int = 3, particle_count: int = 4,
    median: float = 800.0, fwhm: float | None = 0.01,
    source_identity: str = "a" * 64,
    controlled_detector_focus: dict[str, object] | None = None,
) -> Path:
    value = {
        "schema_version": 1,
        "role": "mrtof_source_z_energy_timing_diagnostic",
        "status": "candidate_diagnostic",
        "cohort": {
            "particle_count": particle_count,
            "detector_hit_count": hit_count,
        },
        "evidence": {"source_state_table": {"sha256": source_identity}},
        "terminal_plane_diagnostic": {"detector_plane": {"absolute_time": {
            **peak_time_metrics([median + i * .001 for i in range(hit_count)],
                                mass_th=524, analysis_contract=PEAK_CONTRACT, cohort_role="formal_volume"),
            "median": median,
            "mean": median,
            "method_id": "common_gaussian_kde_time_v2",
            "analysis_contract": PEAK_CONTRACT,
            "time_equivalent_resolution": None if fwhm is None else median / (2 * fwhm),
            "fwhm": fwhm,
            "initial_z_association": {
                "status": "descriptive_linear_association",
                "slope": slope,
                "slope_unit": "us/mm",
            },
        }}},
        "central_plane_focus_history": {"target_return_crossing": {
            "status": "observed",
            "reached_particle_count": hit_count,
            "focus_residual_us_per_mm": slope / 2.0,
            "absolute_time": {
                **peak_time_metrics([median - 20. + i * .001 for i in range(hit_count)],
                                    mass_th=524, analysis_contract=PEAK_CONTRACT, cohort_role="formal_volume"),
                "median": median - 20.0,
                "time_equivalent_resolution": None if fwhm is None else (median - 20.0) / (2 * fwhm),
                "fwhm": fwhm,
            },
        }},
    }
    if controlled_detector_focus is not None:
        value["controlled_detector_focus"] = controlled_detector_focus
    _write_json(path, value)
    return path


def _te1_reference(path: Path) -> Path:
    _write_json(path, {
        "schema_version": 1,
        "role": "mrtof_terminal_time_mirror_voltage_variation",
        "status": "screening_candidate_materialized",
        "qualification": "diagnostic_only__complete_3d_detector_response_pending",
        "mode": "TE1",
        "coordinate": 1.0,
        "base_mirror_voltages_v": [0.0, -10.0, -20.0, 30.0, 40.0],
        "target_mirror_voltages_v": [0.0, -9.0, -22.0, 33.0, 44.0],
        "voltage_delta_v": [1.0, -2.0, 3.0, 4.0],
    })
    return path


def _te1_gate_inputs(root: Path) -> tuple[Path, Path, Path]:
    period = root / "period.json"
    correction = root / "correction.json"
    contract = root / "contract.json"
    _write_json(period, {
        "simion_normalized_period_slopes_per_v": [0.0, 0.0, 0.0],
        "energy_centers_ev": [100.0, 200.0, 300.0],
    })
    _write_json(correction, {
        "updated_local_slope_jacobian_per_v2": [
            [1e-8, 0.0, 0.0, 0.0],
            [1e-8, 0.0, 0.0, 0.0],
            [1e-8, 0.0, 0.0, 0.0],
        ],
    })
    _write_json(contract, {
        "downstream_fixed_grid_workpoint_profile": {
            "jacobian_relative_step_tiers": {
                "coarse": 0.01, "medium": 0.0025, "fine": 0.0005,
            },
        },
        "mirror": {"theory_requirements": {
            "l0_acceptance_budget": {
                "minimum_mass_resolution": 100000,
                "mirror_time_width_fraction": 1.0,
            },
        }},
    })
    return period, correction, contract


def _fixture(
    root: Path,
    *,
    omit_event: tuple[str, int] | None = None,
    selected_parent_interval: tuple[int, int] | None = None,
    loss_terminal_code: int = -1,
    detector_hit_ids: set[int] | None = None,
    controlled_focus_pair: bool = False,
    controlled_slow_energy_pair: bool = False,
    inherited_combined_sentinels: bool = False,
) -> Path:
    if controlled_focus_pair and controlled_slow_energy_pair:
        raise ValueError("fixture accepts only one controlled triplet")
    detector_hit_ids = {1, 2, 3} if detector_hit_ids is None else detector_hit_ids
    source, run = root / "source", root / "run"
    source.mkdir()
    (run / "logs").mkdir(parents=True)
    (run / "results").mkdir()
    (run / "simion").mkdir()
    state = source / "bunch_source_states.csv"
    fields = [
        "particle_id", "tob_us", "mass_th", "charge_e", "kinetic_energy_ev",
        "x_mm", "y_mm", "z_mm", "direction_x", "direction_y", "direction_z",
    ]
    with state.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        source_count = 100 if selected_parent_interval is not None else 4
        for ion in range(1, source_count + 1):
            z_mm = {1: 0.0, 2: -0.5, 3: 0.5}.get(ion, float(ion - 1)) if controlled_focus_pair else ion - 1
            kinetic_energy_ev = (
                {1: 5.0, 2: 4.95, 3: 5.05}.get(ion, 5.0)
                if controlled_slow_energy_pair else 5.0
            )
            if controlled_slow_energy_pair and ion <= 3:
                z_mm = 0.0
            writer.writerow({
                "particle_id": ion, "tob_us": 0, "mass_th": 524, "charge_e": 1,
                "kinetic_energy_ev": kinetic_energy_ev,
                "x_mm": 0, "y_mm": -55, "z_mm": z_mm,
                "direction_x": 0, "direction_y": 1, "direction_z": 0,
            })
    fly2 = source / "bunch_source.fly2"
    fly2.write_text(
        "\n".join("standard_beam {" for _ in range(source_count)), encoding="utf-8"
    )
    receipt_source = source / "bunch_source_receipt.json"
    receipt = {
        "schema_version": 1, "role": "mrtof_deterministic_ideal_bunch_source",
        "status": "materialized", "sampling_method": "center_first_halton_position_energy_angle_v1",
        "clock_basis": "ion_time_of_flight_us_from_common_tob_zero_release",
        "species": {"mass_th": 524.0, "charge_e": 1}, "common_time_of_birth_us": 0.0,
        "source_profile_id": "test_source", "frame_id": "test_frame",
        "cohort_role": "controlled_diagnostic",
        "prefix_rule": "ordered_first_n_states_of_one_mother_cohort",
        "particle_count": source_count, "mother_particle_count": source_count,
        "expected_particle_ids": list(range(1, source_count + 1)),
        "expected_particle_ids_sha256": hashlib.sha256(
            json.dumps(list(range(1, source_count + 1)), separators=(",", ":")).encode()
        ).hexdigest(),
        "particle_states_sha256": "a" * 64,
        "nominal_center_state": {
            "mass_th": 524.0, "charge_e": 1, "kinetic_energy_ev": 5.0,
            "position_workbench_mm": [0.0, -55.0, 0.0],
            "direction_workbench": [0.0, 1.0, 0.0], "tob_us": 0.0,
        },
        "state_table": _record(state), "fly2": _record(fly2),
    }
    if controlled_focus_pair:
        receipt["controlled_focus_pair"] = {
            "coordinate": "z_mm", "negative_particle_id": 2,
            "positive_particle_id": 3, "coordinate_span_mm": 1.0,
            "fixed_variables": "position_x_y__kinetic_energy__direction__mass__charge__birth_time",
        }
    if controlled_slow_energy_pair:
        receipt["sampling_method"] = (
            "center_slow_energy_pair_then_halton_position_energy_angle_v1"
        )
        receipt["controlled_slow_energy_pair"] = {
            "coordinate": "release_slow_y_kinetic_energy_ev",
            "negative_particle_id": 2, "positive_particle_id": 3,
            "half_span_ev_per_charge": 0.05, "coordinate_span_ev": 0.1,
            "fixed_variables": "position__direction__mass__charge__birth_time",
        }
    if inherited_combined_sentinels:
        receipt["controlled_slow_energy_pair"] = {
            "coordinate": "release_slow_y_kinetic_energy_ev",
            "negative_particle_id": 4, "positive_particle_id": 5,
            "half_span_ev_per_charge": 0.05, "coordinate_span_ev": 0.1,
            "fixed_variables": "position__direction__mass__charge__birth_time",
        }
        receipt["controlled_transverse_x_pair"] = {
            "coordinate": "x_mm", "negative_particle_id": 6,
            "positive_particle_id": 7, "coordinate_span_mm": 0.2,
            "fixed_variables": (
                "position_y_z__kinetic_energy__direction__mass__charge__birth_time"
            ),
        }
    _write_json(receipt_source, receipt)
    source_config = source / "run_config.json"
    source_definition = source / "source_definition.json"
    _write_json(source_config, {"schema_version": 1, "role": "test_source_config"})
    _write_json(source_definition, {"role": "test_source_definition"})
    source_manifest = source / "run_manifest.json"
    _write_json(source_manifest, {
        "project": "parallel_mirror_dual_stripe_mr_tof",
        "mode": "deterministic_bunch_source_materialization", "status": "success",
        "run_config": _record(source_config),
        "inputs": {"source_definition": _record(source_definition)},
        "outputs": [_record(state), _record(fly2), _record(receipt_source)],
    })
    receipt_copy = run / "simion" / "bunch_source_receipt.json"
    receipt_copy.write_bytes(receipt_source.read_bytes())

    batch_records = []
    log_paths = []
    for batch_index, offset in enumerate((0, 2), start=1):
        log = run / "logs" / f"native_two_prism_flight__batch{batch_index:02d}.log"
        lines: list[str] = []
        for local_id in (1, 2):
            ion = local_id + offset

            def add(kind: str, line: str) -> None:
                if omit_event != (kind, ion):
                    lines.append(line)

            add(
                "accelerator_safe_exit",
                f"MRTOF_EVENT accelerator_safe_exit ion={local_id} t_us={1 + ion / 1000} "
                f"from_instance=2 to_instance=1 x_mm=0 y_mm=-53 z_mm=-6 "
                f"vx_mm_us=0 vy_mm_us=1.3 vz_mm_us={-40 - ion / 10}",
            )
            add(
                "central_plane_directional",
                f"MRTOF_EVENT central_plane_directional ion={local_id} n=51 direction_z=-1 "
                f"t_us={9.5 + 2 * (ion - 1) / 100} x_mm=0 y_mm=-20 "
                "vx_mm_us=0 vy_mm_us=-3 vz_mm_us=-40",
            )
            add(
                "target_k_phase_sample",
                f"MRTOF_EVENT target_k_phase_sample ion={local_id} k=25.5 half_cycles=51 "
                f"t_us={10 + (ion - 1) / 100} x_mm=0 y_mm=0 z_mm=-282 "
                "vx_mm_us=0 vy_mm_us=-1 vz_mm_us=0",
            )
            if ion not in detector_hit_ids:
                lines.append(
                    f"MRTOF_EVENT terminal ion={local_id} splat={loss_terminal_code} t_us=10.5 x_mm=0 y_mm=-8 z_mm=-97 "
                    "vx_mm_us=0 vy_mm_us=-1 vz_mm_us=40 turns=51 central_crossings=51"
                )
                continue
            add(
                "return_p2_entry",
                f"MRTOF_EVENT return_p2_entry ion={local_id} t_us={11 + 2 * (ion - 1) / 100} "
                "x_mm=0 y_mm=-8 z_mm=-26 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=40",
            )
            add(
                "return_p2_pass",
                f"MRTOF_EVENT return_p2_pass ion={local_id} t_us={12 + (ion - 1) / 100} "
                f"x_mm=0 y_mm={-11 + 0.2 * (ion - 1)} z_mm=26 vx_mm_us=0 "
                f"vy_mm_us=-3 vz_mm_us={40 + 0.1 * (ion - 1)}",
            )
            add(
                "return_positive_mirror_turn",
                f"MRTOF_EVENT return_positive_mirror_turn ion={local_id} "
                f"t_us={13 + 3 * (ion - 1) / 100} x_mm=0 y_mm=-32 "
                f"z_mm={280 + 0.5 * (ion - 1)} vx_mm_us=0 vy_mm_us=-3 vz_mm_us=0",
            )
            add(
                "terminal_detector_plane",
                f"MRTOF_EVENT detector_plane ion={local_id} direction_z=-1 "
                f"t_us={14 + 5 * (ion - 1) / 100} x_mm=0 y_mm=-48 z_mm=97 "
                "vx_mm_us=0 vy_mm_us=-3 "
                f"vz_mm_us={-40 - 0.1 * (ion - 1)}",
            )
            add(
                "detector",
                f"MRTOF_EVENT detector ion={local_id} direction_z=-1 "
                f"t_us={14 + 5 * (ion - 1) / 100} x_mm=0 y_mm=-48 z_mm=97",
            )
            lines.append(
                f"MRTOF_EVENT terminal ion={local_id} splat=1 "
                f"t_us={14 + 5 * (ion - 1) / 100} x_mm=0 y_mm=-48 z_mm=97 "
                "vx_mm_us=0 vy_mm_us=-3 vz_mm_us=-40 turns=51 central_crossings=51"
            )
        lines.append("status,Fly completed. 2 splats")
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        log_paths.append(log)
        batch_records.append({"path": str(log), "sha256": _sha(log), "offset": offset, "count": 2})
    batch_receipt = run / "results" / "batch_log_merge_receipt.json"
    _write_json(batch_receipt, {
        "schema_version": 1, "role": "mrtof_rebased_batch_log_merge", "status": "success",
        "particle_count": 4, "global_particle_ids": [1, 4], "all_batch_losses_retained": True,
        "batches": batch_records,
        "merged_log": {"path": str(run / "logs" / "native_two_prism_flight.log"), "sha256": "not-retained"},
    })
    observation = run / "results" / "two_prism_trial_observation.json"
    _write_json(observation, {"cohort_analysis": {
        "particle_mass_th": 524.0, "peak_analysis_contract": PEAK_CONTRACT,
        "cohort_role": "controlled_diagnostic",
        "event_integrity_passed": True, "expected_particle_count": 4,
        "observed_particle_ids": [1, 2, 3, 4],
        "electrode_collision_count": (
            (4 - len(detector_hit_ids)) if loss_terminal_code == -1 else 0
        ),
        "detector_hit_count": len(detector_hit_ids),
    }})
    run_config = run / "run_config.json"
    parameters: dict[str, object] = {}
    if selected_parent_interval is not None:
        selected = resolve_bunch_source_interval(
            receipt_path=receipt_copy,
            particle_id_min=selected_parent_interval[0],
            particle_id_max=selected_parent_interval[1],
        )
        parameters = {
            "source_selection": selected["source_cohort"]["selection"],
            "source_cohort": selected["source_cohort"],
        }
    _write_json(
        run_config,
        {"schema_version": 1, "role": "test_flight_config", "parameters": parameters,
         "inputs": {"bunch_source_receipt": str(receipt_copy),
                    "bunch_source_run_manifest": str(source_manifest)}},
    )
    manifest = run / "run_manifest.json"
    _write_json(manifest, {
        "project": "instrument_assembly",
        "mode": "oa_mr", "status": "success",
        "run_config": _record(run_config),
        "inputs": {
            "bunch_source_receipt": _record(receipt_copy),
            "bunch_source_run_manifest": _record(source_manifest),
            "batch_log_merge_receipt": _record(batch_receipt),
            "unused_solver_pa": {
                "path": str(run / "simion" / "later_replaced.pa"),
                "exists": True, "bytes": 1, "sha256": "0" * 64,
            },
        },
        "outputs": [_record(path) for path in log_paths] + [_record(observation)],
    })
    return run


def _first_batch_fixture(root: Path) -> tuple[Path, Path]:
    state = root / "bunch_source_states.csv"
    fields = [
        "particle_id", "tob_us", "mass_th", "charge_e", "kinetic_energy_ev",
        "x_mm", "y_mm", "z_mm", "direction_x", "direction_y", "direction_z",
    ]
    states: dict[int, dict[str, float]] = {}
    with state.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for ion in range(1, 14):
            values = {
                "particle_id": ion, "tob_us": 0.0, "mass_th": 524.0, "charge_e": 1,
                "kinetic_energy_ev": {4: 4.95, 5: 5.05}.get(ion, 5.0),
                "x_mm": {6: -0.1, 7: 0.1, 10: -0.5, 11: 0.5}.get(ion, 0.0),
                "y_mm": {8: -51.5, 9: -50.5}.get(ion, -51.0),
                "z_mm": {2: -0.1, 3: 0.1, 12: -0.5, 13: 0.5}.get(ion, 0.0),
                "direction_x": 0.0, "direction_y": 1.0, "direction_z": 0.0,
            }
            writer.writerow(values)
            states[ion] = values
    receipt = root / "bunch_source_receipt.json"
    _write_json(receipt, {
        "schema_version": 1,
        "role": "mrtof_deterministic_ideal_bunch_source",
        "status": "materialized",
        "state_table": {"path": str(state)},
        "controlled_focus_pair": {
            "coordinate": "z_mm", "negative_particle_id": 2,
            "positive_particle_id": 3, "coordinate_span_mm": 0.2,
        },
        "controlled_slow_energy_pair": {
            "coordinate": "release_slow_y_kinetic_energy_ev",
            "negative_particle_id": 4, "positive_particle_id": 5,
            "coordinate_span_ev": 0.1, "half_span_ev_per_charge": 0.05,
        },
        "controlled_transverse_x_pair": {
            "coordinate": "x_mm", "negative_particle_id": 6,
            "positive_particle_id": 7, "coordinate_span_mm": 0.2,
        },
        "controlled_position_pairs": [
            {"name": "local_z", "coordinate": "z_mm",
             "negative_particle_id": 2, "positive_particle_id": 3,
             "coordinate_span_mm": 0.2, "scope": "local"},
            {"name": "local_x", "coordinate": "x_mm",
             "negative_particle_id": 6, "positive_particle_id": 7,
             "coordinate_span_mm": 0.2, "scope": "local"},
            {"name": "envelope_y", "coordinate": "y_mm",
             "negative_particle_id": 8, "positive_particle_id": 9,
             "coordinate_span_mm": 1.0, "scope": "envelope"},
            {"name": "envelope_x", "coordinate": "x_mm",
             "negative_particle_id": 10, "positive_particle_id": 11,
             "coordinate_span_mm": 1.0, "scope": "envelope"},
            {"name": "envelope_z", "coordinate": "z_mm",
             "negative_particle_id": 12, "positive_particle_id": 13,
             "coordinate_span_mm": 1.0, "scope": "envelope"},
        ],
    })
    log = root / "native_two_prism_flight__batch01.log"
    lines: list[str] = []
    stages = (
        ("accelerator_safe_exit", 1.0, 0.1,
         " from_instance=3 to_instance=2 vx_mm_us=0 vy_mm_us=1 vz_mm_us=-40"),
        ("prism_pass", 4.0, 0.2, " n=1 vx_mm_us=0 vy_mm_us=2 vz_mm_us=-40"),
        ("prism_entry", 5.0, 0.3, " n=2 vx_mm_us=0 vy_mm_us=2 vz_mm_us=40"),
        ("prism_pass", 6.0, 0.4, " n=2 vx_mm_us=0 vy_mm_us=2 vz_mm_us=40"),
        ("p2_low_field_crossing", 7.0, 0.5,
         " vx_mm_us=0 vy_mm_us=1 vz_mm_us=40 inside_aperture=1 direction_ok=1"),
        ("target_k", 10.0, 0.6, " k=24.5 half_cycles=49"),
        ("return_p2_entry", 11.0, 0.7, " vx_mm_us=0 vy_mm_us=-1 vz_mm_us=40"),
        ("return_p2_pass", 12.0, 0.8, " vx_mm_us=0 vy_mm_us=-3 vz_mm_us=40"),
        ("return_positive_mirror_turn", 13.0, 0.9,
         " vx_mm_us=0 vy_mm_us=-3 vz_mm_us=0"),
        ("detector", 14.0, 1.0, " direction_z=-1"),
    )
    for ion in range(1, 11):
        values = states[ion]
        time_offset = (
            0.02 * values["z_mm"]
            + 0.5 * (values["kinetic_energy_ev"] - 5.0)
            + 0.075 * values["x_mm"] ** 2
        )
        for kind, base_time, response_factor, extra in stages:
            lines.append(
                f"MRTOF_EVENT {kind} ion={ion} "
                f"t_us={base_time + response_factor * time_offset} "
                f"x_mm={values['x_mm']} y_mm=-10 z_mm=0{extra}"
            )
        lines.append(
            f"MRTOF_EVENT terminal ion={ion} splat=1 t_us={14.0 + time_offset} "
            "x_mm=0 y_mm=-48 z_mm=97 vx_mm_us=0 vy_mm_us=-3 vz_mm_us=-40 "
            "turns=49 central_crossings=49"
        )
    lines.append("status,Fly completed. 10 splats")
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log, receipt


class SourceZEnergyTimingDiagnosticTests(unittest.TestCase):
    def test_multiple_slow_energy_responses_reuse_triplets_without_legacy_changes(self) -> None:
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import parse_events

        with tempfile.TemporaryDirectory() as directory:
            run = _fixture(Path(directory), detector_hit_ids={1, 2, 3, 4})
            base_events = [e for e in parse_events((run / "logs/native_two_prism_flight__batch01.log").read_text())
                           if e["ion"] == 1]
            observation = json.loads((run / "results/two_prism_trial_observation.json").read_text())
            cohort = observation["cohort_analysis"]
            cohort.update(expected_particle_count=7, observed_particle_ids=list(range(1, 8)),
                          detector_hit_count=7, electrode_collision_count=0)
            rows, events, pairs = {}, {}, []
            offsets = [0, -.1, .1, -.2, .2, -.3, .3]
            for ion, offset in enumerate(offsets, 1):
                rows[ion] = dict(tob_us=0., mass_th=524., charge_e=1., x_mm=0., y_mm=-55.,
                                 z_mm=32., direction_x=0., direction_y=1., direction_z=0.,
                                 kinetic_energy_ev=5. + offset)
                for event in base_events:
                    active = dict(event, ion=ion, t_us=event["t_us"] + offset * .1)
                    events.setdefault((event["kind"], ion), []).append(active)
            for index, span in enumerate([.1, .2, .3]):
                pairs.append(dict(coordinate="release_slow_y_kinetic_energy_ev",
                                  negative_particle_id=2 + 2 * index, positive_particle_id=3 + 2 * index,
                                  half_span_ev_per_charge=span, coordinate_span_ev=2 * span,
                                  fixed_variables="position__direction__mass__charge__birth_time"))
            kwargs = dict(source_rows=rows, events=events, cohort=cohort, source_evidence={},
                          log_evidence=[], completion_evidence={}, collision_loss_diagnostic={})
            baseline = analyze_source_z_energy_timing_events(**kwargs)
            result = analyze_source_z_energy_timing_events(**kwargs, controlled_slow_energy_pairs=pairs)
            responses = result.pop("controlled_slow_energy_responses")
            self.assertEqual(result, baseline)
            self.assertEqual([r["particle_ids"] for r in responses], [[2, 1, 3], [4, 1, 5], [6, 1, 7]])
            self.assertTrue(all(r["status"] == "observed" for r in responses))
            for response in responses:
                self.assertAlmostEqual(response["stage_time_response"]["detector"]
                                       ["dt_d_release_slow_energy_us_per_ev"], .1)
            damaged = [dict(pairs[0], coordinate_span_ev=.3)]
            with self.assertRaises(CandidateContractError):
                analyze_source_z_energy_timing_events(**kwargs, controlled_slow_energy_pairs=damaged)
            loss_events = {key: [dict(event) for event in values] for key, values in events.items()}
            loss_events.pop(("detector", 7))
            loss_events[("terminal", 7)][0]["splat"] = -1
            loss_cohort = dict(cohort, detector_hit_count=6, electrode_collision_count=1)
            lost = analyze_source_z_energy_timing_events(
                **dict(kwargs, events=loss_events, cohort=loss_cohort), controlled_slow_energy_pairs=pairs,
            )["controlled_slow_energy_responses"][2]
            self.assertEqual(lost["terminal_codes"], [1, 1, -1])
            self.assertEqual(lost["stage_time_response"]["detector"]["status"], "unavailable")
            self.assertEqual(lost["stage_time_response"]["detector"]["event_counts"], [1, 1, 0])

    def test_multi_energy_selection_keeps_only_complete_original_center_triplets(self) -> None:
        for interval, expected in [((1, 4), [2]), ((14, 17), [])]:
            with self.subTest(interval=interval), tempfile.TemporaryDirectory() as directory:
                run = _fixture(Path(directory), selected_parent_interval=interval)
                cfg_path = run / "run_config.json"
                cfg = json.loads(cfg_path.read_text())
                receipt_path = Path(cfg["inputs"]["bunch_source_receipt"])
                receipt = json.loads(receipt_path.read_text())
                receipt["controlled_slow_energy_pairs"] = [
                    dict(coordinate="release_slow_y_kinetic_energy_ev", negative_particle_id=n,
                         positive_particle_id=p, half_span_ev_per_charge=h, coordinate_span_ev=2*h,
                         fixed_variables="position__direction__mass__charge__birth_time")
                    for n, p, h in [(2, 3, .1), (4, 5, .2), (14, 15, .3)]
                ]
                _write_json(receipt_path, receipt)
                source_manifest_path = Path(cfg["inputs"]["bunch_source_run_manifest"])
                manifest = json.loads(source_manifest_path.read_text())
                for record in manifest["outputs"]:
                    if Path(record["path"]).name == "bunch_source_receipt.json":
                        original = Path(record["path"])
                        _write_json(original, receipt)
                        record.update(_record(original))
                _write_json(source_manifest_path, manifest)
                selected = resolve_bunch_source_interval(receipt_path=receipt_path,
                                                        particle_id_min=interval[0], particle_id_max=interval[1])
                cfg["parameters"]["source_selection"] = selected["source_cohort"]["selection"]
                cfg["parameters"]["source_cohort"] = selected["source_cohort"]
                _write_json(cfg_path, cfg)
                loaded = _load_source_rows_from_paths(receipt_path=receipt_path,
                    source_manifest_path=source_manifest_path, run_config_path=cfg_path, expected_count=4)
                self.assertEqual([p["negative_particle_id"] for p in loaded[-1]], expected)

    def test_comparison_consumes_mean_based_metric_and_rejects_mixed_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = _diagnostic(root / "baseline.json", .06)
            probe = _diagnostic(root / "probe.json", .03)
            focused = _diagnostic(root / "root.json", .001)
            value = json.loads(focused.read_text())
            timing = value["terminal_plane_diagnostic"]["detector_plane"]["absolute_time"]
            timing["mean"] = 900.
            timing["time_equivalent_resolution"] = 45000.
            _write_json(focused, value)
            kwargs = dict(baseline_path=baseline, probe_path=probe, root_path=focused, probe_coordinate=-1., root_coordinate=-2.)
            result = compare_te1_diagnostics(**kwargs)
            self.assertEqual(result["samples"][1]["mass_resolution_t_over_2fwhm"], 45000.)
            timing["analysis_contract"]["settings"]["bandwidth_multiplier"] = 2.
            timing["settings"] = AnalysisSettings(**timing["analysis_contract"]["settings"]).to_dict()
            timing["analysis_metadata"]["settings"] = timing["settings"]
            z0_timing = value["central_plane_focus_history"]["target_return_crossing"]["absolute_time"]
            z0_timing["analysis_contract"] = json.loads(json.dumps(timing["analysis_contract"]))
            z0_timing["settings"] = timing["settings"]
            z0_timing["analysis_metadata"]["settings"] = timing["settings"]
            _write_json(focused, value)
            with self.assertRaisesRegex(CandidateContractError, "identical frozen peak"):
                compare_te1_diagnostics(**kwargs)

    def test_auxiliary_histogram_span_is_distinct_from_direct_time_kde(self):
        values = [0.] * 4 + [8.] * 4
        result = _distribution(list(range(8)), values, value_unit="eV", slope_unit="eV/mm")
        self.assertNotIn("fwhm", result)
        self.assertEqual(result["histogram_half_height_bin_span"], 8.)
        self.assertEqual(result["histogram_analysis"]["unit"], "eV")
        self.assertFalse(result["histogram_analysis"]["detector_resolution_claim_allowed"])
        time = _time_plane_distribution([0., 1., 2.], [1., 1.1, 1.2], peak_context={
            "mass_th": 524, "analysis_contract": PEAK_CONTRACT, "cohort_role": "formal_volume",
        })
        self.assertNotIn("histogram_half_height_bin_span", time)
        self.assertGreater(time["fwhm"], 0.)
        self.assertEqual(time["method_id"], "common_gaussian_kde_time_v2")

    def test_z0_comparison_rejects_missing_old_unknown_mismatched_settings_and_clock(self):
        cases = ("missing_method", "missing_contract", "missing_metadata", "old", "unknown",
                 "mismatched_method", "result_settings", "contract_settings", "time_basis", "clock")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = _diagnostic(root / "baseline.json", .06)
            probe = _diagnostic(root / "probe.json", .03)
            for case in cases:
                focused = _diagnostic(root / "root.json", .001)
                value = json.loads(focused.read_text())
                timing = value["central_plane_focus_history"]["target_return_crossing"]["absolute_time"]
                if case.startswith("missing_"):
                    timing.pop({"missing_method": "method_id", "missing_contract": "analysis_contract",
                                "missing_metadata": "analysis_metadata"}[case])
                elif case in ("old", "unknown"):
                    method = "common_gaussian_kde_time_v1" if case == "old" else "unknown"
                    timing["method_id"] = method
                    timing["analysis_contract"]["method_id"] = method
                elif case == "mismatched_method":
                    timing["analysis_contract"]["method_id"] = "common_gaussian_kde_time_v1"
                elif case == "result_settings":
                    timing["settings"]["bandwidth_multiplier"] = 2.
                elif case == "contract_settings":
                    timing["analysis_contract"]["settings"]["bandwidth_multiplier"] = 2.
                    timing["settings"] = AnalysisSettings(**timing["analysis_contract"]["settings"]).to_dict()
                    timing["analysis_metadata"]["settings"] = timing["settings"]
                elif case == "time_basis":
                    timing["analysis_contract"]["time_basis"] = "particle_birth"
                else:
                    timing["analysis_metadata"]["time_reference"]["reference_time_us"] = 1.
                _write_json(focused, value)
                with self.subTest(case=case), self.assertRaises(CandidateContractError):
                    compare_te1_diagnostics(baseline_path=baseline, probe_path=probe, root_path=focused,
                                            probe_coordinate=-1., root_coordinate=-2.)

    def test_z0_comparison_consumes_current_producer_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = _diagnostic(root / "baseline.json", .06)
            probe = _diagnostic(root / "probe.json", .03)
            focused = _diagnostic(root / "root.json", .001)
            context = dict(mass_th=524, analysis_contract=PEAK_CONTRACT, cohort_role="formal_volume")
            for path in (baseline, focused):
                value = json.loads(path.read_text())
                for timing, center in ((value["terminal_plane_diagnostic"]["detector_plane"], 800.),
                                       (value["central_plane_focus_history"]["target_return_crossing"], 780.)):
                    timing["absolute_time"] = _time_plane_distribution(
                        [0., 1., 2.], [center - .01, center, center + .01], peak_context=context,
                    )
                _write_json(path, value)
            result = compare_te1_diagnostics(baseline_path=baseline, probe_path=probe, root_path=focused,
                                             probe_coordinate=-1., root_coordinate=-2.)
            self.assertEqual(result["root_vs_baseline"]["z0_mass_resolution_ratio"], 1.)
            self.assertGreater(result["samples"][1]["z0_mass_resolution_t_over_2fwhm"], 0.)

    def test_comparison_rejects_old_unknown_and_inconsistent_method_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = _diagnostic(root / "baseline.json", .06)
            probe = _diagnostic(root / "probe.json", .03)
            focused = _diagnostic(root / "root.json", .001)
            for method, contract_method in (("common_gaussian_kde_time_v1", "common_gaussian_kde_time_v1"),
                                            ("unknown", "unknown"),
                                            ("common_gaussian_kde_time_v2", "common_gaussian_kde_time_v1")):
                value = json.loads(focused.read_text())
                timing = value["terminal_plane_diagnostic"]["detector_plane"]["absolute_time"]
                timing["method_id"] = method
                timing["analysis_contract"]["method_id"] = contract_method
                _write_json(focused, value)
                with self.subTest(method=method, contract_method=contract_method), self.assertRaises(CandidateContractError):
                    compare_te1_diagnostics(baseline_path=baseline, probe_path=probe, root_path=focused,
                                            probe_coordinate=-1., root_coordinate=-2.)

    def test_first_batch_reports_controlled_z_energy_and_x_without_formal_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log, receipt = _first_batch_fixture(Path(directory))
            result = analyze_controlled_aberration_first_batch(
                first_batch_log=log, source_receipt_path=receipt,
            )
        self.assertTrue(result["partial_first_batch"])
        self.assertEqual(result["cohort"]["particle_count"], 10)
        self.assertEqual(result["cohort"]["detector_hit_count"], 10)
        self.assertEqual(
            result["formal_metrics"]["status"], "unavailable_until_complete_n100",
        )
        self.assertIsNone(result["formal_metrics"]["collection_rate"])
        self.assertAlmostEqual(
            result["controlled_z_response"]["dt_d_initial_z_us_per_mm"], 0.02,
        )
        self.assertAlmostEqual(
            result["controlled_slow_energy_response"]["stage_time_response"]
            ["detector"]["dt_d_release_slow_energy_us_per_ev"],
            0.5,
        )
        transverse = result["controlled_transverse_x_response"]["stage_time_response"][
            "detector"
        ]
        self.assertAlmostEqual(transverse["odd_dt_d_initial_x_us_per_mm"], 0.0)
        self.assertAlmostEqual(transverse["even_center_deviation_us"], 0.00075)
        stage_responses = result["controlled_stage_responses"]
        self.assertEqual(
            list(stage_responses["initial_z"]["stages"]),
            [
                "accelerator_safe_exit", "p1_target_pass", "p2_entry", "p2_pass",
                "p2_low_field_crossing", "target_k", "return_p2_entry",
                "return_p2_pass", "return_positive_mirror_turn", "detector",
            ],
        )
        self.assertEqual(
            list(result["controlled_position_responses"]),
            ["local_z", "local_x", "envelope_y"],
        )
        self.assertAlmostEqual(
            result["controlled_position_responses"]["envelope_y"]["stages"]
            ["detector"]["even_center_deviation_us"],
            0.0,
        )
        self.assertEqual(
            result["event_stage_semantics"]["p1_entry"]["status"],
            "not_available",
        )
        self.assertEqual(
            result["event_stage_semantics"]["stripe"]["status"],
            "not_reported",
        )
        detector_stage = stage_responses["initial_z"]["stages"]["detector"]
        self.assertAlmostEqual(detector_stage["first_order_time_response"], 0.02)
        self.assertAlmostEqual(
            detector_stage["increment_from_previous_stage"]
            ["first_order_time_response_delta"],
            0.002,
        )

    def test_first_batch_marks_duplicate_raw_p2_crossing_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log, receipt = _first_batch_fixture(Path(directory))
            text = log.read_text(encoding="utf-8")
            duplicate = next(
                line for line in text.splitlines()
                if line.startswith("MRTOF_EVENT p2_low_field_crossing ion=1 ")
            )
            log.write_text(
                text.replace(
                    "status,Fly completed. 10 splats",
                    duplicate + "\nstatus,Fly completed. 10 splats",
                ),
                encoding="utf-8",
            )
            result = analyze_controlled_aberration_first_batch(
                first_batch_log=log, source_receipt_path=receipt,
            )
        for response in result["controlled_stage_responses"].values():
            crossing = response["stages"]["p2_low_field_crossing"]
            self.assertEqual(crossing["status"], "unavailable")
            self.assertEqual(crossing["event_counts"], [1, 2, 1])

    def test_builds_fine_te1_reference_from_current_mirror_jacobian(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            point = root / "point.json"
            correction = root / "correction.json"
            contract = root / "contract.json"
            _write_json(point, {
                "mirror_voltages_v": [0.0, -100.0, -200.0, 300.0, 400.0],
            })
            _write_json(correction, {
                "updated_local_slope_jacobian_per_v2": [
                    [1.0, 0.0, 0.0, 0.0],
                    [0.0, 1.0, 0.0, 0.0],
                    [0.0, 0.0, 1.0, 0.0],
                ],
                "updated_fine_gamma_gradient_per_v": [0.0, 0.0, 0.0, 1.0],
            })
            _write_json(contract, {
                "downstream_fixed_grid_workpoint_profile": {
                    "jacobian_relative_step_tiers": {"fine": 0.0005},
                },
            })
            result = build_te1_reference_from_mirror_jacobian(
                mirror_point_path=point,
                mirror_correction_path=correction,
                contract_path=contract,
                output_path=root / "reference.json",
            )
        self.assertEqual(result["voltage_delta_v"], [-0.05, -0.05, -0.05, -0.0])
        self.assertEqual(result["derivation"]["relative_voltage_step"], 0.0005)

    def test_scales_measured_te1_direction_continuously(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "probe.json"
            result = materialize_scaled_te1_variation(
                reference_path=_te1_reference(root / "reference.json"),
                coordinate=-0.25,
                output_path=output,
            )
        self.assertEqual(result["coordinate"], -0.25)
        self.assertEqual(result["voltage_delta_v"], [-0.25, 0.5, -0.75, -1.0])
        self.assertEqual(
            result["target_mirror_voltages_v"], [0.0, -10.25, -19.5, 29.25, 39.0]
        )

    def test_fine_probe_is_relative_to_actual_nonzero_anchor_voltages(self) -> None:
        base = [0.0, -5920.61, -2612.98, 4190.46, 6029.16]
        direction = [0.26534181722826355, -1.3064907730209914,
                     0.8123479538407015, 0.7579824137295434]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = _te1_reference(root / "reference.json")
            reference_data = json.loads(reference.read_text())
            reference_data.update(base_mirror_voltages_v=base,
                                  voltage_delta_v=direction,
                                  target_mirror_voltages_v=[0.0, *(v + d for v, d in
                                      zip(base[1:], direction, strict=True))])
            _write_json(reference, reference_data)
            period, correction, contract = _te1_gate_inputs(root)
            for anchor in (0.0, -22.894154431673797, -25.0):
                with self.subTest(anchor=anchor):
                    result = materialize_te1_fine_probe(
                        reference_path=reference, baseline_coordinate=anchor,
                        output_path=root / "probe.json", mirror_period_path=period,
                        mirror_correction_path=correction, contract_path=contract,
                    )
                    current = [v + anchor * d for v, d in
                               zip(base[1:], direction, strict=True)]
                    expected_delta = -0.0005 / max(abs(d / v) for d, v in
                                                   zip(direction, current, strict=True))
                    self.assertAlmostEqual(result["coordinate"], anchor + expected_delta)
                    self.assertLess(result["coordinate"], anchor)
                    relative = [abs((target - start) / start) for target, start in
                                zip(result["target_mirror_voltages_v"][1:], current, strict=True)]
                    self.assertAlmostEqual(max(relative), 0.0005, places=14)
                    self.assertEqual(result["base_mirror_voltages_v"], base)

    def test_fine_probe_rejects_invalid_anchor_fraction_and_active_zero_voltage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = _te1_reference(root / "reference.json")
            period, correction, contract = _te1_gate_inputs(root)
            for anchor in (float("nan"), float("inf"), 10.0):
                with self.subTest(anchor=anchor), self.assertRaises(CandidateContractError):
                    materialize_te1_fine_probe(
                        reference_path=reference, baseline_coordinate=anchor,
                        output_path=root / "probe.json", mirror_period_path=period,
                        mirror_correction_path=correction, contract_path=contract,
                    )
            document = json.loads(contract.read_text())
            for fraction in (0.0, 1.0, float("nan")):
                document["downstream_fixed_grid_workpoint_profile"]["jacobian_relative_step_tiers"]["fine"] = fraction
                _write_json(contract, document)
                with self.subTest(fraction=fraction), self.assertRaises(CandidateContractError):
                    materialize_te1_fine_probe(
                        reference_path=reference, baseline_coordinate=0.0,
                        output_path=root / "probe.json", mirror_period_path=period,
                        mirror_correction_path=correction, contract_path=contract,
                    )

    def test_existing_cli_derives_fine_probe_or_keeps_explicit_absolute_coordinate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = _te1_reference(root / "reference.json")
            period, correction, contract = _te1_gate_inputs(root)
            output = root / "probe.json"
            arguments = ["diagnostic", "--te1-reference", str(reference),
                         "--mirror-period", str(period), "--mirror-correction", str(correction),
                         "--contract", str(contract), "--output", str(output)]
            with patch("sys.argv", [*arguments, "--baseline-coordinate", "-2"]):
                self.assertEqual(main(), 0)
            self.assertAlmostEqual(json.loads(output.read_text())["coordinate"], -2.004)
            with patch("sys.argv", [*arguments, "--te1-coordinate", "-2"]):
                self.assertEqual(main(), 0)
            self.assertEqual(json.loads(output.read_text())["coordinate"], -2.0)
            with patch("sys.argv", [*arguments, "--te1-coordinate", "-2",
                                    "--baseline-coordinate", "-2"]), self.assertRaises(SystemExit):
                main()

    def test_bare_mirror_prediction_is_advisory_for_terminal_te1(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            period, correction, contract = _te1_gate_inputs(root)
            result = materialize_scaled_te1_variation(
                reference_path=_te1_reference(root / "reference.json"),
                coordinate=10.0,
                output_path=root / "root.json",
                mirror_period_path=period,
                mirror_correction_path=correction,
                contract_path=contract,
            )
        self.assertEqual(result["status"], "screening_candidate_materialized")
        self.assertFalse(result["mirror_l0_gate_prediction"]["accepted"])
        self.assertEqual(
            result["qualification"],
            "bare_mirror_prediction_outside_old_zero_slope_budget__complete_system_response_required",
        )
        self.assertEqual(
            result["mirror_l0_gate_prediction"]["authority"],
            "advisory_local_bare_mirror_prediction__not_a_terminal_system_gate",
        )

    def test_compares_paired_te1_detector_metrics_without_filtering_losses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = _diagnostic(
                root / "baseline.json", 0.06, hit_count=80, particle_count=100,
                median=800.0, fwhm=0.02,
            )
            probe = _diagnostic(
                root / "probe.json", 0.03, hit_count=75, particle_count=100,
                median=801.0, fwhm=0.015,
            )
            focused = _diagnostic(
                root / "root.json", 0.001, hit_count=90, particle_count=100,
                median=802.0, fwhm=0.005,
            )
            result = compare_te1_diagnostics(
                baseline_path=baseline,
                probe_path=probe,
                root_path=focused,
                probe_coordinate=-1.0,
                root_coordinate=-2.0,
            )
        self.assertEqual([sample["detector_hit_count"] for sample in result["samples"]], [80, 90])
        self.assertEqual(
            [sample["label"] for sample in result["focus_response_samples"]],
            ["baseline", "probe", "root"],
        )
        self.assertEqual(result["qualification"], "paired_n100_candidate_diagnostic__not_formal")
        self.assertAlmostEqual(result["root_vs_baseline"]["collection_rate_delta"], 0.1)
        self.assertAlmostEqual(result["root_vs_baseline"]["fwhm_ratio"], 0.25)
        self.assertAlmostEqual(result["root_vs_baseline"]["mass_resolution_ratio"], 4.01)
        self.assertEqual(result["samples"][0]["z0_reached_particle_count"], 80)
        self.assertAlmostEqual(result["root_vs_baseline"]["z0_absolute_dt_dz_ratio"], 1.0 / 60.0)

    def test_te1_comparison_rejects_different_source_states(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = _diagnostic(root / "baseline.json", 0.06)
            probe = _diagnostic(root / "probe.json", 0.03)
            focused = _diagnostic(
                root / "root.json", 0.001, source_identity="b" * 64
            )
            with self.assertRaisesRegex(CandidateContractError, "same source states"):
                compare_te1_diagnostics(
                    baseline_path=baseline,
                    probe_path=probe,
                    root_path=focused,
                    probe_coordinate=-1.0,
                    root_coordinate=-2.0,
                )

    def test_te1_comparison_accepts_n100_n3_n100_and_keeps_probe_focus_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = _diagnostic(
                root / "baseline.json", 0.06, hit_count=80, particle_count=100,
                median=800.0, fwhm=0.02,
            )
            probe = _diagnostic(
                root / "probe.json", 0.03, hit_count=3, particle_count=3,
                median=801.0, fwhm=None, source_identity="b" * 64,
            )
            focused = _diagnostic(
                root / "root.json", 0.001, hit_count=90, particle_count=100,
                median=802.0, fwhm=0.005,
            )
            result = compare_te1_diagnostics(
                baseline_path=baseline, probe_path=probe, root_path=focused,
                probe_coordinate=-1.0, root_coordinate=-2.0,
            )
        self.assertEqual([sample["particle_count"] for sample in result["samples"]], [100] * 2)
        self.assertEqual(
            [sample["particle_count"] for sample in result["focus_response_samples"]],
            [100, 3, 100],
        )
        self.assertEqual(
            [sample["detector_dt_d_initial_z_us_per_mm"]
             for sample in result["focus_response_samples"]],
            [0.06, 0.03, 0.001],
        )
        self.assertEqual(result["samples"][1]["detector_hit_count"], 90)
        self.assertAlmostEqual(result["samples"][1]["mass_resolution_t_over_2fwhm"], 80200.0)
        self.assertEqual(
            result["probe_scope"],
            "controlled_focus_response_only__excluded_from_collection_and_fwhm",
        )

    def test_te1_comparison_projects_controlled_detector_three_point_diagnostic(self) -> None:
        controlled = {
            "status": "observed",
            "particle_ids": [2, 3],
            "initial_z_mm": [-0.1, 0.1],
            "detector_time_us": [800.01, 800.03],
            "three_point_particle_ids": [2, 1, 3],
            "three_point_initial_z_mm": [-0.1, 0.0, 0.1],
            "three_point_detector_time_us": [800.01, 800.0, 800.03],
            "center_detector_time_us": 800.0,
            "dt_d_initial_z_us_per_mm": 0.1,
            "second_order_center_deviation_us": 0.02,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = _diagnostic(
                root / "baseline.json", 0.1,
                controlled_detector_focus=controlled,
            )
            probe = _diagnostic(
                root / "probe.json", 0.1,
                controlled_detector_focus=controlled,
            )
            focused = _diagnostic(
                root / "root.json", 0.1,
                controlled_detector_focus=controlled,
            )
            result = compare_te1_diagnostics(
                baseline_path=baseline, probe_path=probe, root_path=focused,
                probe_coordinate=-1.0, root_coordinate=-2.0,
            )
        projected = result["focus_response_samples"][0]["controlled_detector_focus"]
        self.assertEqual(projected["three_point_particle_ids"], [2, 1, 3])
        self.assertEqual(projected["center_detector_time_us"], 800.0)
        self.assertEqual(projected["second_order_center_deviation_us"], 0.02)

    def test_te1_comparison_retains_collection_and_slope_when_fwhm_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = _diagnostic(
                root / "baseline.json", 0.06, hit_count=8, particle_count=100,
                median=800.0, fwhm=0.02,
            )
            probe = _diagnostic(
                root / "probe.json", 0.03, hit_count=7, particle_count=100,
                median=801.0, fwhm=None,
            )
            focused = _diagnostic(
                root / "root.json", 0.001, hit_count=7, particle_count=100,
                median=802.0, fwhm=None,
            )
            result = compare_te1_diagnostics(
                baseline_path=baseline,
                probe_path=probe,
                root_path=focused,
                probe_coordinate=-1.0,
                root_coordinate=-2.0,
            )
        self.assertEqual(result["samples"][1]["detector_tof_fwhm_us"], None)
        self.assertEqual(result["samples"][1]["mass_resolution_t_over_2fwhm"], None)
        self.assertAlmostEqual(result["root_vs_baseline"]["collection_rate_delta"], -0.01)
        self.assertAlmostEqual(result["root_vs_baseline"]["absolute_dt_dz_ratio"], 1.0 / 60.0)
        self.assertIsNone(result["root_vs_baseline"]["fwhm_ratio"])
        self.assertIsNone(result["root_vs_baseline"]["mass_resolution_ratio"])

    def test_two_diagnostics_materialize_continuous_te1_detector_plane_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = _diagnostic(root / "first.json", 0.03)
            second = _diagnostic(root / "second.json", -0.001)
            output = root / "variation.json"
            period, correction, contract = _te1_gate_inputs(root)
            result = materialize_te1_variation_from_diagnostics(
                reference_path=_te1_reference(root / "reference.json"),
                first_diagnostic_path=first,
                first_coordinate=0.0,
                second_diagnostic_path=second,
                second_coordinate=2.0,
                output_path=output,
                mirror_period_path=period,
                mirror_correction_path=correction,
                contract_path=contract,
            )
            persisted = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result, persisted)
        self.assertAlmostEqual(result["coordinate"], 60.0 / 31.0)
        self.assertFalse(result["detector_plane_root_fit"]["trust_region_clipped"])
        self.assertEqual(
            result["detector_plane_root_fit"]["method"],
            "two_point_continuous_secant_with_relative_voltage_trust_region",
        )
        self.assertEqual(
            [sample["detector_dt_d_initial_z_us_per_mm"] for sample in
             result["detector_plane_root_fit"]["samples"]],
            [0.03, -0.001],
        )

    def test_te1_root_clips_near_parallel_secant_to_one_percent_voltage_step(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = _diagnostic(root / "first.json", 0.03)
            second = _diagnostic(root / "second.json", 0.029)
            period, correction, contract = _te1_gate_inputs(root)
            result = materialize_te1_variation_from_diagnostics(
                reference_path=_te1_reference(root / "reference.json"),
                first_diagnostic_path=first,
                first_coordinate=0.0,
                second_diagnostic_path=second,
                second_coordinate=1.0,
                output_path=root / "variation.json",
                mirror_period_path=period,
                mirror_correction_path=correction,
                contract_path=contract,
            )
        fit = result["detector_plane_root_fit"]
        self.assertAlmostEqual(fit["unconstrained_coordinate"], 30.0)
        self.assertAlmostEqual(result["coordinate"], 1.09)
        self.assertAlmostEqual(fit["maximum_relative_voltage_step"], 0.01)
        current = [-9.0, -22.0, 33.0, 44.0]
        relative_steps = [
            abs((target - start) / start)
            for target, start in zip(result["target_mirror_voltages_v"][1:], current, strict=True)
        ]
        self.assertAlmostEqual(max(relative_steps), 0.01)
        self.assertTrue(fit["trust_region_clipped"])

    def test_te1_root_rejects_equal_coordinates_or_slopes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = _te1_reference(root / "reference.json")
            first = _diagnostic(root / "first.json", 0.03)
            second = _diagnostic(root / "second.json", 0.03)
            arguments = {
                "reference_path": reference,
                "first_diagnostic_path": first,
                "first_coordinate": 0.0,
                "second_diagnostic_path": second,
                "second_coordinate": 0.0,
                "output_path": root / "variation.json",
            }
            with self.assertRaisesRegex(CandidateContractError, "coordinates must differ"):
                materialize_te1_variation_from_diagnostics(**arguments)
            arguments["second_coordinate"] = 1.0
            with self.assertRaisesRegex(CandidateContractError, "slopes must differ"):
                materialize_te1_variation_from_diagnostics(**arguments)

    def test_te1_root_requires_physical_detector_plane_slope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = _diagnostic(root / "first.json", 0.03, hit_count=1)
            second = _diagnostic(root / "second.json", -0.01)
            with self.assertRaisesRegex(CandidateContractError, "at least two detector hits"):
                materialize_te1_variation_from_diagnostics(
                    reference_path=_te1_reference(root / "reference.json"),
                    first_diagnostic_path=first,
                    first_coordinate=0.0,
                    second_diagnostic_path=second,
                    second_coordinate=1.0,
                    output_path=root / "variation.json",
                )

    def test_contiguous_parent_interval_is_rebased_to_local_particle_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = analyze_source_z_energy_timing(
                _fixture(Path(directory), selected_parent_interval=(2, 5))
            )
        self.assertEqual(result["cohort"]["particle_count"], 4)
        self.assertAlmostEqual(
            result["stages"]["detector"]["absolute_time"]
            ["initial_z_association"]["slope"],
            0.05,
        )

    def test_z0_diagnostic_survives_one_detector_hit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = analyze_source_z_energy_timing(
                _fixture(Path(directory), detector_hit_ids={1})
            )
        self.assertEqual(result["cohort"]["detector_hit_count"], 1)
        self.assertEqual(result["terminal_plane_diagnostic"]["status"], "unavailable")
        self.assertEqual(
            result["central_plane_focus_history"]["target_return_crossing"]["status"],
            "observed",
        )

    def test_controlled_z_pair_reports_detector_focus_without_cohort_regression(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = analyze_source_z_energy_timing(
                _fixture(Path(directory), controlled_focus_pair=True)
            )
        controlled = result["controlled_detector_focus"]
        self.assertEqual(controlled["status"], "observed")
        self.assertEqual(controlled["particle_ids"], [2, 3])
        self.assertEqual(controlled["initial_z_mm"], [-0.5, 0.5])
        self.assertEqual(controlled["three_point_particle_ids"], [2, 1, 3])
        self.assertEqual(controlled["three_point_initial_z_mm"], [-0.5, 0.0, 0.5])
        self.assertEqual(controlled["detector_time_us"], [14.05, 14.1])
        self.assertEqual(controlled["center_detector_time_us"], 14.0)
        self.assertEqual(
            controlled["three_point_detector_time_us"], [14.05, 14.0, 14.1]
        )
        self.assertAlmostEqual(controlled["dt_d_initial_z_us_per_mm"], 0.05)
        self.assertAlmostEqual(controlled["second_order_center_deviation_us"], 0.075)
        z0 = result["central_plane_focus_history"]["target_return_crossing"][
            "controlled_z_only_focus"
        ]
        self.assertEqual(z0["status"], "observed")
        self.assertEqual(z0["particle_ids"], [2, 1, 3])
        self.assertEqual(z0["crossing_index"], 51)
        self.assertEqual(z0["direction_z"], -1)
        self.assertEqual(z0["initial_z_mm"], [-0.5, 0.0, 0.5])
        self.assertEqual(z0["coordinate_unit"], "mm")
        self.assertEqual(z0["time_unit"], "us")
        self.assertAlmostEqual(z0["dt_d_initial_z_us_per_mm"], 0.02)
        self.assertAlmostEqual(z0["second_order_center_deviation_us"], 0.03)
        self.assertEqual(
            z0["qualification"],
            "controlled_z_only_three_point_diagnostic_only__not_a_focus_gate",
        )

    def test_prefix_ignores_inherited_pairs_not_fully_selected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = analyze_source_z_energy_timing(
                _fixture(
                    Path(directory),
                    selected_parent_interval=(1, 4),
                    controlled_focus_pair=True,
                    inherited_combined_sentinels=True,
                )
            )
        self.assertEqual(result["controlled_detector_focus"]["status"], "observed")
        self.assertIsNone(result["controlled_slow_energy_response"])
        self.assertIsNone(result["controlled_transverse_x_response"])

    def test_controlled_z0_triplet_does_not_substitute_another_particle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = analyze_source_z_energy_timing(
                _fixture(
                    Path(directory), controlled_focus_pair=True,
                    omit_event=("central_plane_directional", 3),
                )
            )
        controlled = result["central_plane_focus_history"]["target_return_crossing"][
            "controlled_z_only_focus"
        ]
        self.assertEqual(controlled["status"], "unavailable")
        self.assertEqual(
            controlled["reason"],
            "controlled_triplet_not_observed_at_same_target_crossing",
        )
        self.assertEqual(controlled["particle_ids"], [2, 1, 3])

    def test_controlled_z_pair_reports_loss_instead_of_survivor_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = analyze_source_z_energy_timing(
                _fixture(
                    Path(directory), controlled_focus_pair=True,
                    detector_hit_ids={1, 2, 4},
                )
            )
        controlled = result["controlled_detector_focus"]
        self.assertEqual(controlled["status"], "unavailable")
        self.assertEqual(controlled["terminal_codes"], [1, -1])

    def test_controlled_slow_energy_triplet_reports_stage_and_detector_response(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = analyze_source_z_energy_timing(
                _fixture(Path(directory), controlled_slow_energy_pair=True)
            )
        controlled = result["controlled_slow_energy_response"]
        self.assertEqual(controlled["status"], "observed")
        self.assertEqual(controlled["particle_ids"], [2, 1, 3])
        self.assertEqual(controlled["release_slow_energy_ev"], [4.95, 5.0, 5.05])
        self.assertEqual(controlled["coordinate_unit"], "eV")
        self.assertEqual(controlled["time_unit"], "us")
        detector = controlled["stage_time_response"]["detector"]
        self.assertEqual(detector["times_us"], [14.05, 14.0, 14.1])
        self.assertAlmostEqual(
            detector["dt_d_release_slow_energy_us_per_ev"], 0.5,
        )
        self.assertAlmostEqual(
            detector["second_order_center_deviation_us"], 0.075,
        )
        accelerator_exit = controlled["stage_time_response"]["accelerator_safe_exit"]
        self.assertAlmostEqual(
            accelerator_exit["dt_d_release_slow_energy_us_per_ev"], 0.01,
        )
        self.assertAlmostEqual(
            accelerator_exit["second_order_center_deviation_us"], 0.0015,
        )
        self.assertEqual(
            controlled["qualification"],
            "controlled_slow_energy_three_point_diagnostic_only__not_a_resolution_gate",
        )

    def test_controlled_detector_triplet_is_unavailable_when_center_is_lost(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = analyze_source_z_energy_timing(
                _fixture(
                    Path(directory), controlled_focus_pair=True,
                    detector_hit_ids={2, 3, 4},
                )
            )
        controlled = result["controlled_detector_focus"]
        self.assertEqual(controlled["status"], "unavailable")
        self.assertEqual(controlled["particle_ids"], [2, 3])
        self.assertEqual(controlled["terminal_codes"], [1, 1])
        self.assertEqual(controlled["three_point_particle_ids"], [2, 1, 3])
        self.assertEqual(controlled["three_point_terminal_codes"], [1, -1, 1])

    def test_batch_run_retains_losses_and_reports_transfer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = analyze_source_z_energy_timing(_fixture(Path(directory)))
        self.assertEqual(result["cohort"]["particle_count"], 4)
        self.assertEqual(result["cohort"]["detector_hit_count"], 3)
        self.assertEqual(result["cohort"]["electrode_collision_count"], 1)
        self.assertTrue(result["cohort"]["all_terminal_particles_retained"])
        self.assertEqual(result["safe_exit"]["time"]["sample_count"], 4)
        self.assertEqual(result["stages"]["detector"]["absolute_time"]["sample_count"], 3)
        self.assertAlmostEqual(
            result["stages"]["detector"]["absolute_time"]["initial_z_association"]["slope"],
            0.05,
        )
        self.assertAlmostEqual(
            result["derived_transfer"]["fraction_of_detector_dt_dz_accumulated_after_target_k"],
            0.8,
        )
        self.assertAlmostEqual(
            result["state_dispersion"]["return_p2_pass_y"]["initial_z_association"]["slope"],
            0.2,
        )
        self.assertAlmostEqual(
            result["state_dispersion"]["return_positive_mirror_turn_depth"]
            ["initial_z_association"]["slope"],
            0.5,
        )
        self.assertGreater(
            result["safe_exit"]["axial_kinetic_energy"]["initial_z_association"]["pearson_r"],
            0.999,
        )
        self.assertEqual(result["event_coverage"]["target_k_phase_sample"], 4)
        terminal = result["terminal_plane_diagnostic"]
        self.assertEqual(terminal["detector_plane"]["z_mm"], 97.0)
        self.assertAlmostEqual(
            terminal["detector_plane"]["increment_from_positive_mirror_turn"]
            ["initial_z_association"]["slope"],
            0.02,
        )
        central = result["central_plane_focus_history"]
        self.assertEqual(central["status"], "observed")
        target_return = central["target_return_crossing"]
        self.assertEqual(target_return["crossing_index"], 51)
        self.assertEqual(target_return["reached_particle_count"], 4)
        self.assertEqual(target_return["fraction_of_source_cohort"], 1.0)
        self.assertEqual(
            target_return["scope"],
            "all_source_cohort_particles_reaching_this_z0_crossing__no_detector_hit_filter",
        )
        self.assertIsNone(
            target_return["absolute_time"]["mass_resolution_t_over_2fwhm"]
        )
        self.assertEqual(central["last_complete_crossing"]["crossing_index"], 51)
        self.assertEqual(central["last_complete_crossing"]["direction_z"], -1)
        self.assertAlmostEqual(
            central["last_complete_crossing"]["absolute_time"]
            ["initial_z_association"]["slope"],
            0.02,
        )

    def test_retains_programmatic_topology_rejection_as_a_loss_class(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = analyze_source_z_energy_timing(
                _fixture(Path(directory), loss_terminal_code=4)
            )
        self.assertEqual(result["cohort"]["electrode_collision_count"], 0)
        self.assertEqual(result["cohort"]["programmatic_topology_rejection_count"], 1)
        self.assertEqual(result["cohort"]["terminal_code_histogram"], {"1": 3, "4": 1})
        self.assertNotIn("loss_particle_ids_sha256", result["cohort"])

    def test_missing_downstream_event_for_detector_hit_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = _fixture(Path(directory), omit_event=("detector", 3))
            with self.assertRaisesRegex(CandidateContractError, "ion 3.*detector"):
                analyze_source_z_energy_timing(run)

    def test_missing_safe_exit_for_loss_also_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = _fixture(Path(directory), omit_event=("accelerator_safe_exit", 4))
            with self.assertRaisesRegex(CandidateContractError, "ion 4.*accelerator_safe_exit"):
                analyze_source_z_energy_timing(run)

    def test_missing_terminal_detector_plane_for_detector_hit_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = _fixture(Path(directory), omit_event=("terminal_detector_plane", 2))
            with self.assertRaisesRegex(CandidateContractError, "ion 2.*terminal detector_plane"):
                analyze_source_z_energy_timing(run)


class DescriptiveAssociationTests(unittest.TestCase):
    def test_two_samples_keep_slope_without_correlation(self) -> None:
        result = _association([-1.0, 1.0], [3.0, 7.0], "us/mm")
        self.assertEqual(result["status"], "descriptive_linear_association")
        self.assertEqual(result["slope"], 2.0)
        self.assertEqual(result["slope_unit"], "us/mm")
        self.assertIsNone(result["pearson_r"])
        self.assertIsNone(result["r_squared"])

    def test_invalid_vectors_still_fail_closed(self) -> None:
        for xs, ys in (([0.0, 1.0], [2.0]), ([0.0], [2.0]),
                       ([0.0, float("nan")], [2.0, 3.0])):
            with self.subTest(xs=xs, ys=ys):
                with self.assertRaises(CandidateContractError):
                    _association(xs, ys, "us/mm")


class AutomaticAberrationOutputTests(unittest.TestCase):
    def test_z_polynomial_fit_recovers_curvature_and_uses_all_source_states(self) -> None:
        states, events = {}, {}
        for ion in range(1, 121):
            y, z, energy, x = ion % 3, 32 + (ion % 7 - 3) / 10, 5 + ion % 11 / 10, ion % 5 / 10
            dz = z - 32
            states[ion] = {"y_mm": y, "z_mm": z, "x_mm": x,
                           "kinetic_energy_ev": energy, "tob_us": ion / 10,
                           "direction_x": 0, "direction_y": 1, "direction_z": 0}
            events[("detector", ion)] = [{"t_us": ion / 10 + 100 + 2*y - 3*dz + 4*energy + 5*x*x - 6*dz**2 + 7*dz**3}]
        hit_ids = list(states)[:-1]
        baseline = _joint_initial_state_timing(states, events, hit_ids)
        fitted = _joint_initial_state_timing(states, events, hit_ids, include_z_polynomial=True)
        origin = sum(state["z_mm"] for state in states.values()) / len(states)
        shift = origin - 32
        self.assertAlmostEqual(fitted["z_expansion_origin"]["z_mm"], origin)
        self.assertEqual(fitted["z_expansion_origin"]["source_particle_count"], 120)
        expected = (2, -3 - 12*shift + 21*shift**2, 4, 5, -6 + 21*shift, 7)
        for name, value in zip(fitted["predictors"], expected, strict=True):
            self.assertAlmostEqual(fitted["coefficients"][name]["value"], value, places=8)
        self.assertEqual(fitted["design_rank"], 7)
        self.assertAlmostEqual(fitted["r_squared"], 1)
        self.assertEqual(fitted["residual_degrees_of_freedom"], 112)
        self.assertNotIn("z_expansion_origin", baseline)
        self.assertEqual(baseline, _joint_initial_state_timing(states, events, hit_ids))

    def test_z_polynomial_missing_samples_and_invariants_are_unavailable(self) -> None:
        states = {ion: {"y_mm": 0, "z_mm": ion, "x_mm": 0,
                       "kinetic_energy_ev": 5, "tob_us": 0,
                       "direction_x": 0, "direction_y": 1, "direction_z": 0}
                  for ion in range(1, 9)}
        events = {("detector", ion): [{"t_us": ion}] for ion in states}
        for ids in ([], [1, 2], list(states)[:7]):
            result = _joint_initial_state_timing(states, events, ids, include_z_polynomial=True)
            self.assertEqual(result["reason"], "insufficient_residual_degrees_of_freedom")
        result = _joint_initial_state_timing(states, events, list(states), include_z_polynomial=True)
        self.assertEqual(result["reason"], "invariant_predictor")
        self.assertEqual(_joint_initial_state_timing({}, {}, [], include_z_polynomial=True)["status"], "unavailable")

    def test_joint_fit_recovers_partial_coefficients_and_birth_clock(self) -> None:
        states, events = {}, {}
        for ion in range(1, 25):
            y, z, energy, x = ion % 3, ion % 5, 5 + ion % 7 / 10, ion % 4 / 10
            states[ion] = {"y_mm": y, "z_mm": z, "x_mm": x,
                           "kinetic_energy_ev": energy, "tob_us": ion / 10,
                           "direction_x": 0, "direction_y": 2, "direction_z": 0}
            events[("detector", ion)] = [{"t_us": ion / 10 + 100 + 2*y - 3*z + 4*energy + 5*x*x}]
        fitted = _joint_initial_state_timing(states, events, list(states))
        self.assertEqual(fitted["status"], "observed")
        self.assertEqual(fitted["design_rank"], 5)
        for name, expected in zip(fitted["predictors"], (2, -3, 4, 5), strict=True):
            self.assertAlmostEqual(fitted["coefficients"][name]["value"], expected)
        self.assertAlmostEqual(fitted["r_squared"], 1)
        self.assertNotIn("fwhm", fitted)

    def test_joint_invariant_and_small_cohort_are_unavailable(self) -> None:
        states = {ion: {"y_mm": 0, "z_mm": ion, "x_mm": 0,
                       "kinetic_energy_ev": 5, "tob_us": 0,
                       "direction_x": 0, "direction_y": 1, "direction_z": 0}
                  for ion in range(1, 8)}
        events = {("detector", ion): [{"t_us": ion}] for ion in states}
        self.assertEqual(_joint_initial_state_timing(states, events, [1, 2])["status"], "unavailable")
        self.assertEqual(_joint_initial_state_timing(states, events, list(states))["reason"], "invariant_predictor")
        states[1]["direction_y"] = float("nan")
        with self.assertRaises(CandidateContractError):
            _joint_initial_state_timing(states, events, list(states))

    def test_fast_turn_controlled_slopes_and_even_increments(self) -> None:
        events = {}
        for ion, offset in ((2, -0.05), (1, 0), (3, 0.05)):
            events[("fast_turn", ion)] = [
                {"n": n, "z_mm": (-1)**n * 280, "t_us": n*10 + n*offset}
                for n in (1, 2)]
        for ion, x in ((4, -0.1), (1, 0), (5, 0.1)):
            if ion == 1:
                continue
            events[("fast_turn", ion)] = [
                {"n": n, "z_mm": (-1)**n * 280, "t_us": n*10 + 2*n*x*x}
                for n in (1, 2)]
        history = _controlled_fast_turn_history(
            events, {"particle_ids": [2, 1, 3], "release_slow_energy_span_ev": .1},
            {"particle_ids": [4, 1, 5], "initial_x_mm": [-.1, 0, .1]})
        slow = history["release_slow_energy"]["samples"]
        transverse = history["initial_x"]["samples"]
        self.assertAlmostEqual(slow[1]["dt_d_release_slow_energy_us_per_ev"], 2)
        self.assertAlmostEqual(slow[1]["increment_from_previous_turn"]["response_delta"], 1)
        self.assertAlmostEqual(transverse[1]["even_dt_per_initial_x_squared_us_per_mm2"], 4)
        self.assertAlmostEqual(transverse[1]["increment_from_previous_turn"]["even_center_deviation_delta_us"], .02)

    def test_fast_turn_missing_duplicate_and_wrong_side_do_not_pair(self) -> None:
        control = {"particle_ids": [2, 1, 3], "release_slow_energy_span_ev": .1}
        events = {("fast_turn", ion): [{"n": 1, "z_mm": -280, "t_us": 10}]
                  for ion in (1, 2, 3)}
        events[("fast_turn", 3)][0]["z_mm"] = 280
        history = _controlled_fast_turn_history(events, control, None)
        self.assertTrue(all(row["status"] == "unavailable" for row in history["release_slow_energy"]["samples"]))
        events[("fast_turn", 3)][0]["z_mm"] = -280
        events[("fast_turn", 2)] *= 2
        self.assertEqual(_controlled_fast_turn_history(events, control, None)["release_slow_energy"]["samples"][0]["event_counts"], [2, 1, 1])

    def test_fast_history_without_control_is_explicitly_unavailable(self) -> None:
        result = _controlled_fast_turn_history({}, None, None)
        self.assertEqual(result["release_slow_energy"]["reason"], "controlled_triplet_not_present")
        self.assertEqual(result["initial_x"]["status"], "unavailable")

    def test_complete_analyzer_preserves_hit_scope_and_existing_stage_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = analyze_source_z_energy_timing(_fixture(Path(tmp)))
        self.assertEqual(result["joint_initial_state_timing"]["particle_ids"], [1, 2, 3])
        self.assertEqual(result["joint_initial_state_timing"]["status"], "unavailable")
        self.assertIn("initial_z_association", result["stages"]["detector"]["absolute_time"])
        self.assertEqual(result["controlled_fast_turn_history"]["initial_x"]["status"], "unavailable")

    def test_preseal_same_core_matches_sealed_and_rejects_incomplete_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = _fixture(Path(tmp))
            sealed = analyze_source_z_energy_timing(run)
            arguments = {"run_config_path": run / "run_config.json",
                         "observation_path": run / "results/two_prism_trial_observation.json",
                         "batch_merge_receipt_path": run / "results/batch_log_merge_receipt.json"}
            completed = analyze_completed_source_z_energy_timing(**arguments)
            self.assertEqual({k: v for k, v in sealed.items() if k != "evidence"},
                             {k: v for k, v in completed.items() if k != "evidence"})
            self.assertNotIn("flight_run_manifest", completed["evidence"])
            receipt = json.loads(arguments["batch_merge_receipt_path"].read_text())
            receipt["all_batch_losses_retained"] = False
            _write_json(arguments["batch_merge_receipt_path"], receipt)
            with self.assertRaises(CandidateContractError):
                analyze_completed_source_z_energy_timing(**arguments)

    def test_preseal_rejects_modified_source_and_batch_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = _fixture(Path(tmp))
            arguments = {"run_config_path": run / "run_config.json",
                         "observation_path": run / "results/two_prism_trial_observation.json",
                         "batch_merge_receipt_path": run / "results/batch_log_merge_receipt.json"}
            batch = json.loads(arguments["batch_merge_receipt_path"].read_text())["batches"][0]
            Path(batch["path"]).write_text("changed log", encoding="utf-8")
            with self.assertRaises(CandidateContractError):
                analyze_completed_source_z_energy_timing(**arguments)
            config = json.loads(arguments["run_config_path"].read_text())
            Path(config["inputs"]["bunch_source_receipt"]).write_text("{}", encoding="utf-8")
            with self.assertRaises(CandidateContractError):
                analyze_completed_source_z_energy_timing(**arguments)


class DiagnosticRunnerResourcePolicyTests(unittest.TestCase):
    def test_capacity_threshold_has_no_warning_override(self) -> None:
        runner = Path(__file__).resolve().parents[2] / "analysis/run_source_z_energy_timing_diagnostic.ps1"
        self.assertNotIn("CapacityThresholdAction", runner.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
