from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.materialize_pre_pulse_time_series import (
    materialize,
)


def _id_sha256(particle_ids: list[int]) -> str:
    payload = json.dumps(particle_ids, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def _cache_dispositions() -> dict[str, object]:
    return {
        "frontend": {
            "role": "simion_single_flight_frontend_pa_cache",
            "key": "1" * 64,
            "disposition": "cache_hit",
        },
        "full_coarse_bridge": {
            "role": "simion_single_flight_frontend_pa_cache",
            "key": "1" * 64,
            "disposition": "cache_hit",
        },
        "fine_upstream": {
            "role": "simion_single_flight_upstream_bridge_pa_cache",
            "key": "5" * 64,
            "disposition": "built_and_published",
        },
        "accelerator_main": {
            "role": "simion_single_flight_accelerator_main_pa_cache",
            "key": "6" * 64,
            "disposition": "built_and_published",
        },
        "accelerator_overlay": {
            "role": "simion_accelerator_overlay_pa_cache",
            "key": "2" * 64,
            "disposition": "built_and_published",
        },
        "accelerator_entrance_overlay": {
            "role": "simion_accelerator_entrance_overlay_pa_cache",
            "key": "3" * 64,
            "disposition": "built_and_published",
        },
        "accelerator_intermediate_overlay": {
            "role": "simion_accelerator_intermediate_overlay_pa_cache",
            "key": "4" * 64,
            "disposition": "built_and_published",
        },
        "flight_tube": {
            "role": "simion_oatof_flight_tube_pa_cache",
            "key": None,
            "disposition": "formal",
        },
        "reflectron": {
            "role": "simion_oatof_reflectron_pa_cache",
            "key": None,
            "disposition": "formal",
        },
    }


def _contract(
    particle_ids: list[int], sample_times: list[float], *, schema_version: int
) -> dict[str, object]:
    identities = {
        "campaign_id": "test_campaign",
        "experiment_id": "test_experiment",
        "experiment_row_sha256": "A" * 64,
        "connection_profile_id": "test_connection",
        "source_profile_id": "test_source",
        "resolved_source_contract_sha256": "B" * 64,
        "resolved_population_contract_sha256": "C" * 64,
        "mother_particle_source_sha256": "D" * 64,
        "ordered_particle_id_sha256": _id_sha256(particle_ids),
        "layout_profile_id": "test_layout",
        "architecture_generation_id": "test_architecture",
        "topology_id": "test_topology",
        "geometry_id": "test_geometry",
        "frontend_electrode_topology_id": "test_frontend_topology",
        "field_id": "test_field",
        "field_profile_id": "test_field_profile",
        "region_field_semantic_sha256": "E" * 64,
        "frontend_grid_profile_id": "test_grid",
        "field_overlay_id": "test_overlay",
        "oatof_numerical_profile_id": "test_numerics",
        "trajectory_quality_profile_id": "test_trajectory",
        "time_integration_profile_id": "test_time_integration",
        "spatial_window_profile_id": "layout_resolved_axial_provisional_xy2_v1",
    }
    if schema_version == 1:
        rf_time_grid = {
            "derivation": (
                "grid_origin_us + sample_index*period_us/rf_steps_per_period"
            ),
            "waveform": "sine",
            "frequency_hz": 1_000_000.0,
            "phase_rad": 0.0,
            "rf_steps_per_period": 1,
            "period_us": 1.0,
            "step_us": 1.0,
            "anchor_time_us": sample_times[0],
            "grid_origin_us": sample_times[0],
            "requested_relative_start_index": 0,
            "requested_relative_end_index": len(sample_times) - 1,
            "anchor_sample_index": 0,
            "start_index": 0,
            "end_index": len(sample_times) - 1,
            "sample_count": len(sample_times),
        }
    else:
        rf_time_grid = {
            "time_grid_profile_id": "test_time_grid",
            "derivation": (
                "ballistic_seed_time_us + "
                "relative_index*period_us/rf_steps_per_period"
            ),
            "waveform": "sine",
            "frequency_hz": 1_000_000.0,
            "phase_rad": 0.0,
            "rf_steps_per_period": 1,
            "period_us": 1.0,
            "step_us": 1.0,
            "ballistic_seed_time_us": sample_times[0],
            "grid_origin_us": sample_times[0],
            "requested_relative_start_index": 0,
            "requested_relative_end_index": len(sample_times) - 1,
            "ballistic_seed_sample_index": 0,
            "start_index": 0,
            "end_index": len(sample_times) - 1,
            "sample_count": len(sample_times),
        }
    contract: dict[str, object] = {
        "schema_version": schema_version,
        "role": "rf_oatof_pre_pulse_time_series_screening_contract",
        "mode": "real_pa_rf_pre_pulse_time_series",
        "active_scope": "pre_pulse_frontend_accelerator",
        "claim_limit": "FUNCTIONAL_ONLY",
        "identities": identities,
        "rf_time_grid": rf_time_grid,
        "sample_times_us": sample_times,
        "pulse_disabled": True,
        "terminate_at_window_end": True,
        "resolution_claim_allowed": False,
        "prohibited_outputs": [
            "detector_crossing",
            "resolution_metrics",
            "single_flight_spatial_six_panel",
        ],
    }
    if schema_version == 1:
        contract["pa_cache_keys"] = {
            "frontend": "1" * 64,
            "accelerator_overlay": "2" * 64,
            "flight_tube": None,
            "reflectron": None,
        }
    elif schema_version == 2:
        contract["pa_cache_roles"] = {
            "identity_source": "runner_materialized_verified_pa_cache_receipt",
            "required": ["frontend", "accelerator_overlay"],
            "prohibited": ["flight_tube", "reflectron"],
        }
    elif schema_version == 3:
        contract["pa_cache_roles"] = {
            "identity_source": "runner_materialized_verified_pa_cache_receipt",
            "required": [
                "frontend",
                "accelerator_entrance_overlay",
                "accelerator_intermediate_overlay",
            ],
            "prohibited": ["flight_tube", "reflectron"],
        }
    else:
        contract["pa_cache_roles"] = {
            "identity_source": "runner_materialized_verified_pa_cache_receipt",
            "required": [
                "full_coarse_bridge",
                "fine_upstream",
                "accelerator_main",
                "accelerator_intermediate2_overlay",
            ],
            "prohibited": ["flight_tube", "reflectron"],
        }
    return contract


def _trace(
    *,
    ion: int,
    particle_id: int,
    sample_index: int,
    time_us: float,
    status: str = "alive",
) -> str:
    return (
        "TRACE: pre_pulse_time_series_state "
        f"ion={ion} particle_id={particle_id} sample_index={sample_index} "
        f"instrument_time_us={time_us:.17g} "
        f"actual_instrument_time_us={time_us:.17g} "
        "x_mm=9.9999999999999998e-13 y_mm=-1 z_mm=0 "
        "vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0 "
        f"kinetic_energy_eV=10 survival_status={status}"
    )


def _terminal(*, ion: int, particle_id: int, reason: str = "window_complete") -> str:
    return (
        "TRACE: pre_pulse_screening_terminal "
        f"ion={ion} particle_id={particle_id} instrument_time_us=3 "
        "x_mm=0 y_mm=0 z_mm=0 vx_mm_per_us=1 vy_mm_per_us=0 vz_mm_per_us=0 "
        f"terminal_reason={reason}"
    )


def _write_fixture(
    root: Path,
    *,
    particle_ids: list[int],
    sample_times: list[float],
    log_groups: list[list[str]],
    schema_version: int = 2,
    row_map_ids: list[int] | None = None,
) -> dict[str, object]:
    run_dir = root / "run"
    inputs = run_dir / "inputs"
    logs = run_dir / "logs"
    results = run_dir / "results"
    for directory in (inputs, logs, results):
        directory.mkdir(parents=True, exist_ok=True)
    contract_path = inputs / "pre_pulse_time_series_screening_contract.json"
    contract_path.write_text(
        json.dumps(
            _contract(particle_ids, sample_times, schema_version=schema_version),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    row_map_path = inputs / "single_flight_particle_row_map.csv"
    with row_map_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["source_particle_id"])
        writer.writeheader()
        for particle_id in row_map_ids or particle_ids:
            writer.writerow({"source_particle_id": particle_id})
    stdout_paths = []
    for index, lines in enumerate(log_groups, 1):
        path = logs / f"simion__batch{index:02d}.stdout.log"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        stdout_paths.append(path)
    run_config_path = run_dir / "run_config.json"
    run_config_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "inputs": {
                    "pre_pulse_time_series_contract": str(contract_path),
                    "particle_row_map": str(row_map_path),
                },
                "parameters": {
                    "execution_mode": "real_pa_rf_pre_pulse_time_series",
                    "resolution_claim_allowed": False,
                    "particle_count": len(particle_ids),
                    "launched_particle_count": len(particle_ids),
                    "pa_cache_dispositions": _cache_dispositions(),
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "run_config": run_config_path,
        "contract_sha256": file_sha256(contract_path),
        "stdout_paths": stdout_paths,
        "states": results / "pre_pulse_time_series_states.csv",
        "receipt": results / "pre_pulse_time_series_screening_receipt.json",
        "summary": run_dir / "summary.json",
    }


def _materialize(paths: dict[str, object]):
    return materialize(
        stdout_paths=paths["stdout_paths"],
        run_config_path=paths["run_config"],
        expected_contract_sha256=paths["contract_sha256"],
        states_path=paths["states"],
        receipt_path=paths["receipt"],
        summary_path=paths["summary"],
    )


class PrePulseTimeSeriesMaterializationTests(unittest.TestCase):
    def test_terminal_census_retains_physical_loss_without_postselection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = _write_fixture(
                Path(directory), particle_ids=[1, 2, 3], sample_times=[1.0],
                log_groups=[[
                    _trace(ion=1, particle_id=1, sample_index=1, time_us=1.0),
                    _terminal(ion=1, particle_id=1),
                    _terminal(ion=2, particle_id=2, reason="splat"),
                    _terminal(ion=3, particle_id=3, reason="splat"),
                ]],
            )
            _materialize(paths)
            receipt = json.loads(paths["receipt"].read_text(encoding="utf-8"))
            self.assertEqual(receipt["terminal_census"]["window_complete"]["count"], 1)
            self.assertEqual(receipt["terminal_census"]["splat"]["count"], 2)

    def test_retained_inputs_are_used_after_short_execution_alias_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = _write_fixture(
                Path(directory), particle_ids=[1, 2, 3], sample_times=[1.0],
                log_groups=[[_trace(ion=i, particle_id=i, sample_index=1, time_us=1.0) for i in (1, 2, 3)]],
            )
            run_config = json.loads(paths["run_config"].read_text(encoding="utf-8"))
            run_config["inputs"]["pre_pulse_time_series_contract"] = str(
                Path(directory) / "deleted-short-alias" / "pre_pulse_time_series_screening_contract.json"
            )
            run_config["inputs"]["particle_row_map"] = str(
                Path(directory) / "deleted-short-alias" / "single_flight_particle_row_map.csv"
            )
            paths["run_config"].write_text(json.dumps(run_config), encoding="utf-8")
            result = _materialize(paths)
            self.assertEqual(result.state_row_count, 3)

    def test_schema_v1_cache_identity_is_case_stable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = _write_fixture(
                Path(directory), particle_ids=[1], sample_times=[1.0],
                log_groups=[[_trace(ion=1, particle_id=1, sample_index=1, time_us=1.0)]],
                schema_version=1,
            )
            run_config = json.loads(paths["run_config"].read_text(encoding="utf-8"))
            for role in ("frontend", "accelerator_overlay"):
                run_config["parameters"]["pa_cache_dispositions"][role]["key"] = (
                    run_config["parameters"]["pa_cache_dispositions"][role]["key"].lower()
                )
            paths["run_config"].write_text(json.dumps(run_config), encoding="utf-8")
            self.assertEqual(_materialize(paths).state_row_count, 1)

    def test_schema_v3_records_both_local_overlay_cache_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = _write_fixture(
                Path(directory),
                particle_ids=[1],
                sample_times=[1.0],
                log_groups=[[_trace(ion=1, particle_id=1, sample_index=1, time_us=1.0)]],
                schema_version=3,
            )
            _materialize(paths)
            receipt = json.loads(paths["receipt"].read_text(encoding="utf-8"))
            self.assertEqual(receipt["pa_cache_keys"], {
                "frontend": "1" * 64,
                "accelerator_entrance_overlay": "3" * 64,
                "accelerator_intermediate_overlay": "4" * 64,
                "flight_tube": None,
                "reflectron": None,
            })

    def test_schema_v3_rejects_missing_local_overlay_disposition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = _write_fixture(
                Path(directory),
                particle_ids=[1],
                sample_times=[1.0],
                log_groups=[[_trace(ion=1, particle_id=1, sample_index=1, time_us=1.0)]],
                schema_version=3,
            )
            run_config = json.loads(paths["run_config"].read_text(encoding="utf-8"))
            del run_config["parameters"]["pa_cache_dispositions"][
                "accelerator_intermediate_overlay"
            ]
            paths["run_config"].write_text(json.dumps(run_config), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "active PA cache disposition"):
                _materialize(paths)

    def test_schema_v4_records_all_domain_split_cache_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = _write_fixture(
                Path(directory), particle_ids=[1], sample_times=[1.0],
                log_groups=[[_trace(ion=1, particle_id=1, sample_index=1, time_us=1.0)]],
                schema_version=4,
            )
            run_config = json.loads(paths["run_config"].read_text(encoding="utf-8"))
            dispositions = run_config["parameters"]["pa_cache_dispositions"]
            dispositions["accelerator_intermediate2_overlay"] = {
                "role": "simion_accelerator_intermediate_overlay_pa_cache",
                "key": "4" * 64,
                "disposition": "built_and_published",
            }
            paths["run_config"].write_text(json.dumps(run_config), encoding="utf-8")
            _materialize(paths)
            receipt = json.loads(paths["receipt"].read_text(encoding="utf-8"))
            self.assertEqual(receipt["pa_cache_keys"], {
                "full_coarse_bridge": "1" * 64,
                "fine_upstream": "5" * 64,
                "accelerator_main": "6" * 64,
                "accelerator_intermediate2_overlay": "4" * 64,
                "flight_tube": None,
                "reflectron": None,
            })

    def test_n100_v1_v2_preserves_prefix_census_and_output_bytes(self) -> None:
        particle_ids = list(range(1, 101))
        sample_times = [1.0, 2.0, 3.0]
        lines = []
        for particle_id in particle_ids:
            prefix = 3 if particle_id <= 80 else 2 if particle_id <= 90 else 1 if particle_id <= 95 else 0
            for sample_index in range(1, prefix + 1):
                lines.append(
                    _trace(
                        ion=particle_id,
                        particle_id=particle_id,
                        sample_index=sample_index,
                        time_us=sample_times[sample_index - 1],
                    )
                )
        for schema_version in (1, 2):
            with self.subTest(schema_version=schema_version), tempfile.TemporaryDirectory() as directory:
                paths = _write_fixture(
                    Path(directory),
                    particle_ids=particle_ids,
                    sample_times=sample_times,
                    log_groups=[lines],
                    schema_version=schema_version,
                )
                result = _materialize(paths)
                first_hashes = {
                    name: file_sha256(paths[name])
                    for name in ("states", "receipt", "summary")
                }
                second = _materialize(paths)
                self.assertEqual(result.state_row_count, 265)
                self.assertEqual(second.state_row_count, 265)
                self.assertEqual(
                    first_hashes,
                    {
                        name: file_sha256(paths[name])
                        for name in ("states", "receipt", "summary")
                    },
                )
                states_bytes = paths["states"].read_bytes()
                self.assertFalse(states_bytes.startswith(b"\xef\xbb\xbf"))
                self.assertNotIn(b"\n", states_bytes.replace(b"\r\n", b""))
                self.assertIn(b'"1E-12","-1","0"', states_bytes)
                receipt_bytes = paths["receipt"].read_bytes()
                self.assertNotIn(b"\n", receipt_bytes.replace(b"\r\n", b""))
                receipt = json.loads(receipt_bytes)
                self.assertEqual(receipt["state_row_count"], 265)
                self.assertEqual(
                    [item["alive_count"] for item in receipt["sample_census"]],
                    [95, 90, 80],
                )
                self.assertEqual(
                    receipt["sample_census"][2]["missing_particle_ids"],
                    list(range(81, 101)),
                )
                self.assertEqual(
                    receipt["outputs"]["states"]["sha256"],
                    file_sha256(paths["states"]),
                )

    def test_n1000_five_batches_use_global_ids_and_local_ion_numbers(self) -> None:
        particle_ids = list(range(1, 1001))
        sample_times = [10.0, 11.0, 12.0]
        log_groups: list[list[str]] = []
        for batch_index in range(5):
            lines = []
            for local_ion in range(1, 201):
                particle_id = batch_index * 200 + local_ion
                prefix = 0 if particle_id % 10 == 0 else 2 if particle_id % 5 == 0 else 3
                for sample_index in range(1, prefix + 1):
                    lines.append(
                        _trace(
                            ion=local_ion,
                            particle_id=particle_id,
                            sample_index=sample_index,
                            time_us=sample_times[sample_index - 1],
                        )
                    )
            log_groups.append(lines)
        with tempfile.TemporaryDirectory() as directory:
            paths = _write_fixture(
                Path(directory),
                particle_ids=particle_ids,
                sample_times=sample_times,
                log_groups=log_groups,
            )
            result = _materialize(paths)
            receipt = json.loads(paths["receipt"].read_bytes())
            with paths["states"].open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(result.state_row_count, 2600)
        self.assertEqual(
            [item["alive_count"] for item in receipt["sample_census"]],
            [900, 900, 800],
        )
        ordered_keys = [
            (int(row["particle_id"]), int(row["sample_index"])) for row in rows
        ]
        observed_particle_ids = {particle_id for particle_id, _ in ordered_keys}
        self.assertEqual(ordered_keys, sorted(ordered_keys))
        self.assertNotIn(10, observed_particle_ids)
        self.assertNotIn(1000, observed_particle_ids)
        self.assertIn((201, 1), ordered_keys)

    def test_invalid_logs_and_particle_identity_fail_before_outputs(self) -> None:
        particle_ids = [1, 2, 3]
        sample_times = [1.0, 2.0, 3.0]
        valid_one = _trace(
            ion=1, particle_id=1, sample_index=1, time_us=1.0
        )
        cases = {
            "malformed": ["TRACE: pre_pulse_time_series_state broken"],
            "downstream": ["TRACE: detector_crossing ion=1"],
            "duplicate": [valid_one, valid_one],
            "unknown": [
                _trace(ion=99, particle_id=99, sample_index=1, time_us=1.0)
            ],
            "outside_grid": [
                _trace(ion=1, particle_id=1, sample_index=4, time_us=4.0)
            ],
            "time_mismatch": [
                _trace(ion=1, particle_id=1, sample_index=1, time_us=1.1)
            ],
            "actual_time_mismatch": [
                valid_one.replace(
                    "actual_instrument_time_us=1 ",
                    "actual_instrument_time_us=1.1 ",
                )
            ],
            "not_alive": [
                _trace(
                    ion=1,
                    particle_id=1,
                    sample_index=1,
                    time_us=1.0,
                    status="splat",
                )
            ],
            "gap_or_revival": [
                valid_one,
                _trace(ion=1, particle_id=1, sample_index=3, time_us=3.0),
            ],
        }
        for name, lines in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                paths = _write_fixture(
                    Path(directory),
                    particle_ids=particle_ids,
                    sample_times=sample_times,
                    log_groups=[lines],
                )
                with self.assertRaises(ContractError):
                    _materialize(paths)
                self.assertFalse(paths["states"].exists())
                self.assertFalse(paths["receipt"].exists())
                self.assertFalse(paths["summary"].exists())

        with tempfile.TemporaryDirectory() as directory:
            paths = _write_fixture(
                Path(directory),
                particle_ids=particle_ids,
                sample_times=sample_times,
                log_groups=[[valid_one]],
                row_map_ids=[1, 1, 3],
            )
            with self.assertRaisesRegex(ContractError, "particle identity"):
                _materialize(paths)

        with tempfile.TemporaryDirectory() as directory:
            paths = _write_fixture(
                Path(directory),
                particle_ids=particle_ids,
                sample_times=sample_times,
                log_groups=[[valid_one]],
            )
            paths["contract_sha256"] = "0" * 64
            with self.assertRaisesRegex(ContractError, "SHA-256"):
                _materialize(paths)


if __name__ == "__main__":
    unittest.main()
