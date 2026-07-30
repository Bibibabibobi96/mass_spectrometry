"""Tests for real-artifact paired downstream analysis."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from common.contracts.component_particle_state import write_component_particle_state_csv
from common.contracts.file_identity import file_sha256
from common.contracts.particle_physics import kinetic_energy_ev
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.paired_downstream_analysis import (
    INTEGRATION_ID,
    REQUEST_ROLE,
    DownstreamAnalysisError,
    _load_downstream,
    analyze_request,
    label_pareto_candidates,
)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "exists": True,
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def ref(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": file_sha256(path)}


def source_identity(runtime_path: Path, solver: str) -> dict[str, str]:
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    contract_path = Path(runtime["contracts"]["source_contract"]["path"])
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    branch = contract["source_branches"][solver]
    source = branch["source"]
    return {
        "source_branch_id": solver,
        "solver_id": solver,
        "run_id": source["run_id"],
        "project_id": branch["recorded_project_id"],
        "manifest_sha256": source["manifest"]["sha256"],
        "event_sha256": source["state"]["sha256"],
        "particle_source_sha256": source["particle_source"]["sha256"],
        "metadata_sha256": source["metadata"]["sha256"],
    }


def rewrite_terminal(
    branch: dict[str, Any],
    config_update: Any,
    manifest_update: Any | None = None,
) -> None:
    manifest_path = Path(branch["manifest"]["path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    run_config_path = Path(manifest["run_config"]["path"])
    run_config = json.loads(run_config_path.read_text(encoding="utf-8"))
    config_update(run_config)
    write_json(run_config_path, run_config)
    manifest["run_config"] = record(run_config_path)
    if manifest_update is not None:
        manifest_update(manifest)
    write_json(manifest_path, manifest)
    branch["manifest"] = ref(manifest_path)


def state_row(particle_id: int, offset: float = 0.0, species: str = "ion_100") -> dict[str, Any]:
    mass = 100.0
    velocity = (10.0 * particle_id + offset, 20.0 + particle_id, 1000.0 + particle_id)
    time = 36.0 + 0.01 * particle_id + offset
    return {
        "particle_id": particle_id,
        "parent_particle_id": None,
        "generation": 0,
        "species_id": species,
        "particle_weight": 1.0,
        "source_component_id": "rf_multipole",
        "target_component_id": "single_reflection_oatof",
        "state_event": "local_accelerator_exit",
        "frame_id": "oatof_global",
        "clock_epoch_id": "instrument_clock_epoch_v1",
        "instrument_time_us": time,
        "lineage_age_us": time,
        "particle_age_us": time,
        "last_component_elapsed_time_us": 1.0,
        "lineage_birth_time_us": 0.0,
        "particle_birth_time_us": 0.0,
        "mass_to_charge_Th": mass,
        "mass_amu": mass,
        "charge_state": 1,
        "position_x_mm": -67.0 + 0.01 * particle_id + offset,
        "position_y_mm": 0.02 * particle_id,
        "position_z_mm": -18.4,
        "velocity_x_m_s": velocity[0],
        "velocity_y_m_s": velocity[1],
        "velocity_z_m_s": velocity[2],
        "kinetic_energy_eV": kinetic_energy_ev(mass, *velocity),
        "phase_reference_id": None,
        "phase_rad": None,
    }


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.source_input = root / "mother_source.csv"
        write_csv(self.source_input, ["particle_id"], [{"particle_id": item} for item in range(1, 7)])
        self.request: dict[str, Any] = {
            "schema_version": 1,
            "role": REQUEST_ROLE,
            "integration_id": INTEGRATION_ID,
            "candidates": [],
        }

    def add_candidate(self, candidate_id: str, simion_offset: float = 0.02) -> None:
        candidate: dict[str, Any] = {"candidate_id": candidate_id}
        profile = f"profile_{candidate_id}"
        resolved = self.root / candidate_id / "resolved.json"
        runtime = self.root / candidate_id / "runtime.json"
        write_json(
            resolved,
            {
                "schema_version": 1,
                "role": "resolved_connection_do_not_edit",
                "selection": {"connection_profile_id": profile},
                "compatibility": {"status": "pass"},
                "port_geometry": {
                    "downstream": {
                        "coordinate_frame": {"frame_id": "oatof_global"},
                        "clock": {"origin_id": "instrument_clock_epoch_v1"},
                    }
                },
            },
        )
        upstream_project = "rf_quadrupole_ion_optics"
        source_branches: dict[str, Any] = {}
        source_paths: dict[str, tuple[Path, Path]] = {}
        source_identities: dict[str, dict[str, str]] = {}
        for solver in ("comsol", "simion"):
            run = self.root / candidate_id / solver
            run.mkdir(parents=True)
            source_state = run / "raw_source.csv"
            write_csv(
                source_state,
                ["particle_id", "event"],
                [
                    {"particle_id": item, "event": "handoff"}
                    for item in range(1, 7)
                ],
            )
            source_metadata = run / "source_metadata.json"
            write_json(
                source_metadata,
                {"schema_version": 1, "role": "particle_source_metadata"},
            )
            source_manifest = run / "source_manifest.json"
            write_json(
                source_manifest,
                {
                    "schema_version": 2,
                    "role": "simulation_run_manifest",
                    "status": "success",
                    "run_id": f"source_{solver}",
                    "project": upstream_project,
                    "inputs": {"particle_source": record(self.source_input)},
                    "outputs": [record(source_state)],
                },
            )
            source_record = {
                "run_id": f"source_{solver}",
                "particle_count": 6,
                "particle_source_manifest_input_role": "particle_source",
                "manifest": ref(source_manifest),
                "state": ref(source_state),
                "particle_source": ref(self.source_input),
                "metadata": ref(source_metadata),
            }
            source_branches[solver] = {
                "solver_id": solver,
                "recorded_project_id": upstream_project,
                "source": source_record,
            }
            source_paths[solver] = (source_manifest, source_state)
            source_identities[solver] = {
                "source_branch_id": solver,
                "solver_id": solver,
                "run_id": f"source_{solver}",
                "project_id": upstream_project,
                "manifest_sha256": file_sha256(source_manifest),
                "event_sha256": file_sha256(source_state),
                "particle_source_sha256": file_sha256(self.source_input),
                "metadata_sha256": file_sha256(source_metadata),
            }
        source_contract = self.root / candidate_id / "source_contract.json"
        write_json(
            source_contract,
            {
                "schema_version": 2,
                "role": "rf_multipole_oatof_source_contract",
                "upstream_project_id": upstream_project,
                "source_branches": source_branches,
            },
        )
        write_json(
            runtime,
            {
                "schema_version": 1,
                "role": "rf_multipole_oatof_runtime_binding",
                "integration_id": INTEGRATION_ID,
                "connection_profile_id": profile,
                "upstream_project_id": upstream_project,
                "contracts": {"source_contract": ref(source_contract)},
            },
        )
        for solver in ("comsol", "simion"):
            run = self.root / candidate_id / solver
            source_manifest, source_state = source_paths[solver]
            canonical = run / "inputs" / "canonical_local_accelerator_exit.csv"
            offset = simion_offset if solver == "simion" else 0.0
            write_component_particle_state_csv(
                canonical,
                [state_row(item, offset) for item in range(1, 7)],
            )
            row_map = run / "inputs" / "row_map.csv"
            map_fields = [
                "solver_row_index", "particle_id", "instrument_time_us",
                "lineage_age_us", "particle_age_us", "solver_birth_time_us",
                "azimuth_deg", "elevation_deg",
            ]
            write_csv(
                row_map,
                map_fields,
                [
                    {
                        "solver_row_index": item,
                        "particle_id": item,
                        "instrument_time_us": 36 + item / 100,
                        "lineage_age_us": 36 + item / 100,
                        "particle_age_us": 36 + item / 100,
                        "solver_birth_time_us": 36 + item / 100,
                        "azimuth_deg": 0,
                        "elevation_deg": 0,
                    }
                    for item in range(1, 7)
                ],
            )
            downstream = run / "results" / "simion_downstream_particles.csv"
            times = (70.00, 70.08, 70.18, 70.31, 70.47, "")
            downstream_rows = []
            for item in range(1, 7):
                hit = item <= 5
                downstream_rows.append(
                    {
                        "Ion": item, "MassAmu": 100, "ChargeState": 1,
                        "X0Mm": -67 + item / 100, "Y0Mm": item / 50, "Z0Mm": -18.4,
                        "TofUs": times[item - 1], "InstrumentTimeUs": (
                            float(times[item - 1]) + offset if hit else ""
                        ),
                        "XMm": 160.6 + item / 100 if hit else "",
                        "YMm": -18.4 + item / 100 if hit else "",
                        "RadiusMm": (2**0.5) * item / 100 if hit else "",
                        "Hit": str(hit).lower(),
                    }
                )
            down_fields = list(downstream_rows[0])
            write_csv(downstream, down_fields, downstream_rows)
            census = {
                "rf_exit": 6,
                "oatof_entry": 6,
                "active_at_pulse": 6,
                "local_accelerator_exit": 6,
                "detector_crossing": 5,
                "detector_hit": 5,
            }
            metrics = run / "results" / "analyzer_transport_metrics.json"
            summary = run / "summary.json"
            write_json(
                metrics,
                {
                    "schema_version": 1,
                    "role": "rf_to_oatof_analyzer_transport_function_audit",
                    "status": "PASS",
                    "census": census,
                    "frame_id": "oatof_global",
                    "clock_epoch_id": "instrument_clock_epoch_v1",
                },
            )
            write_json(
                summary,
                {
                    "schema_version": 1,
                    "role": "rf_to_oatof_analyzer_transport_summary",
                    "status": "success",
                    "census": census,
                },
            )
            run_config = run / "run_config.json"
            write_json(
                run_config,
                {
                    "schema_version": 2,
                    "run_id": f"terminal_{solver}",
                    "project": upstream_project,
                    "mode": "rf_to_oatof_analyzer_transport_n100",
                    "inputs": {
                        "canonical": str(canonical.resolve()),
                        "row_map": str(row_map.resolve()),
                        "runtime_binding": str(runtime.resolve()),
                        "resolved_connection": str(resolved.resolve()),
                    },
                    "upstream_source_identity": source_identities[solver],
                    "parameters": {"source_branch_id": solver},
                },
            )
            manifest = run / "run_manifest.json"
            write_json(
                manifest,
                {
                    "schema_version": 2,
                    "role": "simulation_run_manifest",
                    "status": "success",
                    "run_id": f"terminal_{solver}",
                    "project": upstream_project,
                    "mode": "rf_to_oatof_analyzer_transport_n100",
                    "run_config": record(run_config),
                    "inputs": {
                        "canonical": record(canonical),
                        "row_map": record(row_map),
                        "runtime_binding": record(runtime),
                        "resolved_connection": record(resolved),
                    },
                    "outputs": [record(downstream), record(metrics), record(summary)],
                },
            )
            candidate[solver] = {
                "manifest": ref(manifest),
                "canonical_local_exit": ref(canonical),
                "row_map": ref(row_map),
                "downstream_particles": ref(downstream),
                "metrics": ref(metrics),
                "summary": ref(summary),
                "resolved_connection": ref(resolved),
                "runtime_binding": ref(runtime),
                "source_manifest": ref(source_manifest),
                "source_state": ref(source_state),
                "source_input": ref(self.source_input),
            }
        self.request["candidates"].append(candidate)


class PairedAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_solver_rows_do_not_collide_with_noncontiguous_particle_ids(
        self,
    ) -> None:
        row_map = self.root / "row_map.csv"
        downstream = self.root / "downstream.csv"
        map_fields = [
            "solver_row_index",
            "particle_id",
            "instrument_time_us",
            "lineage_age_us",
            "particle_age_us",
            "solver_birth_time_us",
            "azimuth_deg",
            "elevation_deg",
        ]
        write_csv(
            row_map,
            map_fields,
            [
                {
                    "solver_row_index": solver_id,
                    "particle_id": particle_id,
                    "instrument_time_us": 1,
                    "lineage_age_us": 1,
                    "particle_age_us": 1,
                    "solver_birth_time_us": 1,
                    "azimuth_deg": 0,
                    "elevation_deg": 0,
                }
                for solver_id, particle_id in ((1, 1), (2, 2), (3, 3), (4, 5))
            ],
        )
        downstream_fields = [
            "Ion",
            "MassAmu",
            "ChargeState",
            "X0Mm",
            "Y0Mm",
            "Z0Mm",
            "TofUs",
            "InstrumentTimeUs",
            "XMm",
            "YMm",
            "RadiusMm",
            "Hit",
        ]
        write_csv(
            downstream,
            downstream_fields,
            [
                {
                    "Ion": solver_id,
                    "MassAmu": 100,
                    "ChargeState": 1,
                    "X0Mm": 0,
                    "Y0Mm": 0,
                    "Z0Mm": 0,
                    "TofUs": "",
                    "InstrumentTimeUs": "",
                    "XMm": "",
                    "YMm": "",
                    "RadiusMm": "",
                    "Hit": "false",
                }
                for solver_id in range(1, 5)
            ],
        )
        result = _load_downstream(
            row_map,
            downstream,
            {
                particle_id: {"mass_amu": 100.0, "charge_state": 1}
                for particle_id in (1, 2, 3, 5)
            },
            "noncontiguous",
        )
        self.assertEqual(set(result), {1, 2, 3, 5})

    def test_real_artifact_planes_and_pareto(self) -> None:
        fixture = Fixture(self.root)
        for name, offset in (("Q", 0.01), ("H", 0.02), ("O", 0.03)):
            fixture.add_candidate(name, offset)
        result = analyze_request(fixture.request, self.root)
        self.assertEqual(result["status"], "INCONCLUSIVE_DIAGNOSTIC_ONLY")
        self.assertFalse(result["qualification_decision_made"])
        candidate = result["candidates"][0]
        self.assertEqual(candidate["paired_diagnostics"]["observation_plane"], "local_accelerator_exit")
        self.assertEqual(candidate["branch_metrics"]["comsol"]["observation_plane"], "detector_plane")
        self.assertEqual(candidate["branch_metrics"]["comsol"]["detector_hit_count"], 5)
        self.assertEqual(candidate["paired_diagnostics"]["detector_velocity"]["status"], "not_observed")
        self.assertGreater(candidate["branch_metrics"]["comsol"]["mass_resolution"], 0)
        self.assertEqual(len(result["pareto_front_candidate_ids"]), 1)

    def test_forged_source_lineage_fails_closed(self) -> None:
        fixture = Fixture(self.root)
        fixture.add_candidate("Q")
        branch = fixture.request["candidates"][0]["simion"]
        path = Path(branch["source_manifest"]["path"])
        value = json.loads(path.read_text(encoding="utf-8"))
        value["outputs"][0]["sha256"] = "A" * 64
        write_json(path, value)
        branch["source_manifest"] = ref(path)
        with self.assertRaisesRegex(
            DownstreamAnalysisError, "source manifest identity differs"
        ):
            analyze_request(fixture.request, self.root)

    def test_branch_swap_fails_closed(self) -> None:
        fixture = Fixture(self.root)
        fixture.add_candidate("Q")
        branch = fixture.request["candidates"][0]["comsol"]
        runtime_path = Path(branch["runtime_binding"]["path"])

        def swap(config: dict[str, Any]) -> None:
            config["parameters"]["source_branch_id"] = "simion"
            config["upstream_source_identity"] = source_identity(
                runtime_path, "simion"
            )

        rewrite_terminal(branch, swap)
        with self.assertRaisesRegex(
            DownstreamAnalysisError, "terminal source branch/solver differs"
        ):
            analyze_request(fixture.request, self.root)

    def test_detached_resolved_connection_fails_closed(self) -> None:
        fixture = Fixture(self.root)
        fixture.add_candidate("Q")
        branch = fixture.request["candidates"][0]["simion"]
        original = Path(branch["resolved_connection"]["path"])
        detached = self.root / "detached_resolved.json"
        value = json.loads(original.read_text(encoding="utf-8"))
        value["selection"]["connection_profile_id"] = "detached_profile"
        write_json(detached, value)
        branch["resolved_connection"] = ref(detached)
        with self.assertRaisesRegex(
            DownstreamAnalysisError,
            "resolved_connection is not bound exactly once",
        ):
            analyze_request(fixture.request, self.root)

    def test_detached_self_consistent_source_fails_closed(self) -> None:
        fixture = Fixture(self.root)
        fixture.add_candidate("Q")
        branch = fixture.request["candidates"][0]["simion"]
        original_manifest = json.loads(
            Path(branch["source_manifest"]["path"]).read_text(encoding="utf-8")
        )
        detached_root = self.root / "detached_source"
        detached_state = detached_root / "state.csv"
        detached_input = detached_root / "mother.csv"
        write_csv(
            detached_state,
            ["particle_id", "event"],
            [{"particle_id": item, "event": "detached"} for item in range(1, 7)],
        )
        write_csv(
            detached_input,
            ["particle_id"],
            [{"particle_id": item} for item in range(10, 16)],
        )
        original_manifest["inputs"] = {
            "particle_source": record(detached_input)
        }
        original_manifest["outputs"] = [record(detached_state)]
        detached_manifest = detached_root / "manifest.json"
        write_json(detached_manifest, original_manifest)
        branch["source_manifest"] = ref(detached_manifest)
        branch["source_state"] = ref(detached_state)
        branch["source_input"] = ref(detached_input)
        with self.assertRaisesRegex(
            DownstreamAnalysisError, "source manifest identity differs"
        ):
            analyze_request(fixture.request, self.root)

    def test_wrong_terminal_mode_and_project_fail_closed(self) -> None:
        cases = {
            "mode": (
                lambda config: config.update({"mode": "wrong_mode"}),
                lambda manifest: manifest.update({"mode": "wrong_mode"}),
                "terminal manifest differs",
            ),
            "project": (
                lambda config: config.update({"project": "wrong_project"}),
                lambda manifest: manifest.update({"project": "wrong_project"}),
                "terminal mode/project differs",
            ),
        }
        for name, (config_update, manifest_update, message) in cases.items():
            with self.subTest(name=name):
                case_root = self.root / name
                fixture = Fixture(case_root)
                fixture.add_candidate("Q")
                branch = fixture.request["candidates"][0]["comsol"]
                rewrite_terminal(branch, config_update, manifest_update)
                with self.assertRaisesRegex(DownstreamAnalysisError, message):
                    analyze_request(fixture.request, case_root)

    def test_species_difference_fails_closed(self) -> None:
        fixture = Fixture(self.root)
        fixture.add_candidate("Q")
        branch = fixture.request["candidates"][0]["simion"]
        path = Path(branch["canonical_local_exit"]["path"])
        rows = [state_row(item, 0.02, "different" if item == 1 else "ion_100") for item in range(1, 7)]
        write_component_particle_state_csv(path, rows)
        branch["canonical_local_exit"] = ref(path)
        manifest_path = Path(branch["manifest"]["path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["inputs"]["canonical"] = record(path)
        write_json(manifest_path, manifest)
        branch["manifest"] = ref(manifest_path)
        with self.assertRaisesRegex(DownstreamAnalysisError, "species/lineage differs"):
            analyze_request(fixture.request, self.root)

    def test_binding_sha_mismatch_fails_closed(self) -> None:
        fixture = Fixture(self.root)
        fixture.add_candidate("Q")
        fixture.request["candidates"][0]["comsol"]["runtime_binding"]["sha256"] = "F" * 64
        with self.assertRaisesRegex(DownstreamAnalysisError, "runtime_binding SHA-256 differs"):
            analyze_request(fixture.request, self.root)

    def test_weightless_strict_pareto(self) -> None:
        base = {
            "worst_detector_hit_fraction": 1.0,
            "worst_mass_resolution": 1000.0,
            "worst_direct_fwhm_tof_ns": 1.0,
            "worst_landing_rms_radius_mm": 0.1,
            "detector_hit_symmetric_difference_count": 0.0,
            "local_exit_particle_symmetric_difference_count": 0.0,
            "paired_position_rms_distance_mm": 0.01,
            "paired_velocity_rms_distance_m_s": 1.0,
            "paired_time_rms_difference_us": 0.001,
            "paired_energy_rms_difference_eV": 0.01,
        }
        worse = {
            key: value - 0.1 if key in {"worst_detector_hit_fraction", "worst_mass_resolution"} else value + 0.1
            for key, value in base.items()
        }
        labels = label_pareto_candidates({"best": base, "worse": worse})
        self.assertEqual(labels["best"]["pareto_label"], "NONDOMINATED")
        self.assertEqual(labels["worse"]["pareto_label"], "DOMINATED")


if __name__ == "__main__":
    unittest.main()
