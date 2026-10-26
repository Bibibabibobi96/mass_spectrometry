"""Solver-free component export identity, closure and unchanged-state tests."""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common.contracts.component_particle_state import validate_component_particle_state_csv
from common.contracts.component_particle_state import write_component_particle_state_csv
from common.contracts.particle_physics import kinetic_energy_ev, mass_to_charge_th
from common.contracts.write_run_manifest import file_record
from projects.dual_pressure_rectilinear_ion_processor.analysis.component_exit import (
    PROJECT, export_component_exit,
)


class ComponentExitTests(unittest.TestCase):
    """Synthetic frozen runs test adapters, without claiming physical flight."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.run = self.root / "20261016_121423__sim__simion__fixture"
        self.run.mkdir()
        (self.run / "inputs").mkdir()
        (self.run / "simion").mkdir()
        (self.run / "results").mkdir()
        self.output = self.root / "export"
        self.source = {"particle_count": 3, "species": {"mass_amu": 524, "charge_state": 1}}
        self.model = {
            "source": self.source,
            "baseline": {"clock": {"epoch_us": 100, "frame_id": "local"},
                         "geometry": {"lp_center_mm": 170, "extraction_end_y_mm": 9.8}},
            "coordinate_transform": {"schema_version": 1, "role": "rigid_transform", "from_frame_id": "local", "to_frame_id": "world",
                                     "rotation": [[0, 0, -1], [1, 0, 0], [0, -1, 0]], "translation_mm": [0, 0, 9.8]},
            "native_timing": {"primary_quench_us": 10},
            "numerics": {"collision_rng_policy": "per_global_particle_seed_v1"},
        }
        self._write_json("inputs/source.json", self.source)
        self._write_json("inputs/resolved_model.json", self.model)
        self._write_json("inputs/instrument_epoch.json", {"instrument_time_us": 100})
        self._write_json("inputs/clock_authority.json", {
            "schema_version": 1, "role": "canonical_clock_authority", "clock_epoch_id": "epoch",
            "instrument_time_unit": "us", "canonical_time_basis": "instrument_epoch_absolute_time",
            "authority": {"path": "inputs/instrument_epoch.json", "sha256": file_record(self.run / "inputs/instrument_epoch.json")["sha256"], "field": "instrument_time_us"},
            "solver_local_time_basis": "elapsed_time_from_zero_us",
            "adapter_materialization": "instrument_time_us_equals_authority_epoch_plus_solver_elapsed_once",
            "handoff_policy": "preserve_instrument_time_us_and_clock_epoch_id", "legacy_new_campaign_allowed": False,
        })
        self.releases = [dict(particle_id=particle_id, birth_time_s=birth * 1e-6, x_mm=1, y_mm=0, z_mm=0,
                              vx_m_s=1000, vy_m_s=0, vz_m_s=0, mass_amu=524, charge_state=1)
                         for particle_id, birth in ((2, 2), (9, 4), (20, 5))]
        self._write_csv("inputs/release.csv", self.releases)
        self._write_json("inputs/release_receipt.json", {
            "status": "materialized", "release_spec": self.source, "particle_count": 3,
            "state_table": file_record(self.run / "inputs/release.csv"), "source_spec": file_record(self.run / "inputs/source.json"),
        })
        self.events = []
        for release in self.releases:
            source = dict(event="source", particle_id=release["particle_id"], reason="none", t_us=release["birth_time_s"] * 1e6,
                          x_mm=0, y_mm=1, z_mm=9.8, vx_mm_us=0, vy_mm_us=1, vz_mm_us=0)
            self.events.append(source)
            terminal = dict(source, event="terminal", reason="solver_stop", t_us=8)
            if release["particle_id"] != 9:
                terminal.update(reason="acceptance_surface", t_us=12 + release["particle_id"] / 10, x_mm=.2, y_mm=170.1, z_mm=0,
                                vx_mm_us=.01, vy_mm_us=.02, vz_mm_us=-38)
                self.events.append(dict(terminal, event="extraction_exit"))
            self.events.append(terminal)
        self._write_csv("simion/events.csv", self.events)
        self.summary = {"role": "ion_processor_functional_summary", "status": "success",
                        "checks": {"capture_fraction": True, "extraction_fraction": True,
                                   "hp_cooling": True, "lp_compression": True,
                                   "extraction_energy": True, "lp_occupation": True},
                        "functional_status": "functional_pass",
                        "qualification": "synthetic_fixture_not_native_flight",
                        "actual_particle_count": 3, "frame_id": "world",
                        "terminal_reasons": {"acceptance_surface": 2, "solver_stop": 1},
                        "identity_validation": {"status": "PASS", "particles": 3},
                        "metrics": {"extraction_exit": {"count": 2}}}
        self._write_json("summary.json", self.summary)
        self._write_json("run_config.json", {"run_id": self.run.name, "project": PROJECT, "mode": "native_electrode_functional"})
        self._write_json("results/simion_batch_resource_usage.json", dict(
            schema_version=2, role="multipole_resource_usage", status="completed",
            failure_class=None, limit_name=None, execution_wave=dict(process_count=1)))
        self._write_json("results/batch_merge_receipt.json", dict(
            schema_version=1, role="ion_processor_batch_merge", particle_count=3, batch_count=1,
            all_ids_closed=True, rng_policy="per_global_particle_seed_v1"))
        self._seal()

    def _write_json(self, name: str, document: dict) -> None:
        (self.run / name).write_text(json.dumps(document) + "\n", encoding="utf-8")

    def _write_csv(self, name: str, rows: list[dict]) -> None:
        with (self.run / name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def _seal(self) -> None:
        self._write_json("run_manifest.json", {
            "schema_version": 2, "role": "simulation_run_manifest", "status": self.summary["status"], "project": PROJECT,
            "run_id": self.run.name, "mode": "native_electrode_functional",
            "run_config": file_record(self.run / "run_config.json"),
            "inputs": {path.name: file_record(path) for path in (self.run / "inputs").iterdir()},
            "outputs": [file_record(self.run / name) for name in ("simion/events.csv", "summary.json",
                "results/batch_merge_receipt.json", "results/simion_batch_resource_usage.json")],
        })

    def _negative_population(self) -> None:
        """Scale the existing inert fixture to a complete 100-mother/81-exit case."""
        source_event = dict(self.events[0])
        terminal_event = next(dict(row) for row in self.events if row["event"] == "extraction_exit")
        self.releases = [dict(self.releases[0], particle_id=pid, birth_time_s=pid*1e-6) for pid in range(1, 101)]
        self.events = []
        for release in self.releases:
            pid = release["particle_id"]
            self.events.append(dict(source_event, particle_id=pid, t_us=pid))
            terminal = dict(terminal_event, event="terminal", particle_id=pid, t_us=200+pid/10,
                            reason="acceptance_surface" if pid <= 81 else "solver_stop")
            if pid <= 81:
                self.events.append(dict(terminal, event="extraction_exit"))
            self.events.append(terminal)
        self.source["particle_count"] = 100
        self.summary.update(status="failed", actual_particle_count=100, functional_status="functional_incomplete",
                            terminal_reasons=dict(acceptance_surface=81, solver_stop=19),
                            identity_validation=dict(status="PASS", particles=100),
                            metrics=dict(extraction_exit=dict(count=81)))
        self.summary["checks"].update(capture_fraction=False, extraction_fraction=False)
        self._write_json("inputs/source.json", self.source)
        self._write_json("inputs/resolved_model.json", self.model)
        self._write_csv("inputs/release.csv", self.releases)
        self._write_json("inputs/release_receipt.json", dict(status="materialized", release_spec=self.source,
            particle_count=100, state_table=file_record(self.run/"inputs/release.csv"),
            source_spec=file_record(self.run/"inputs/source.json")))
        self._write_csv("simion/events.csv", self.events)
        self._write_json("summary.json", self.summary)
        self._write_json("results/simion_batch_resource_usage.json", dict(schema_version=2,
            role="multipole_resource_usage", status="completed", failure_class=None,
            limit_name=None, execution_wave=dict(process_count=11)))
        self._write_json("results/batch_merge_receipt.json", dict(schema_version=1,
            role="ion_processor_batch_merge", particle_count=100, batch_count=11,
            all_ids_closed=True, rng_policy="per_global_particle_seed_v1"))
        self._seal()

    def test_explicit_instances_do_not_select_a_downstream_project_or_change_state(self) -> None:
        first = export_component_exit(self.run, self.output,
            source_instance_id="processor_a", target_instance_id="analyzer_b")
        other = self.root / "another_connection"
        second = export_component_exit(self.run, other,
            source_instance_id="processor_c", target_instance_id="collector_d")
        self.assertEqual(first["schema_version"], 2)
        self.assertEqual(first["source_project"], PROJECT)
        self.assertEqual(second["source_project"], PROJECT)
        with (self.output / "component_particle_state.csv").open(newline="") as stream:
            a = list(csv.DictReader(stream))
        with (other / "component_particle_state.csv").open(newline="") as stream:
            b = list(csv.DictReader(stream))
        for left, right in zip(a, b):
            self.assertEqual(left.pop("source_component_id"), "processor_a")
            self.assertEqual(right.pop("source_component_id"), "processor_c")
            self.assertEqual(left.pop("target_component_id"), "analyzer_b")
            self.assertEqual(right.pop("target_component_id"), "collector_d")
            self.assertEqual(left, right)
        self.assertEqual(first["counts"], second["counts"])
        self.assertEqual((self.output / "source_census.csv").read_bytes(), (other / "source_census.csv").read_bytes())

    def test_missing_or_degenerate_instance_binding_has_no_output(self) -> None:
        with self.assertRaises(TypeError):
            export_component_exit(self.run, self.output)
        for source, target in (("", "receiver"), ("provider", ""), ("same", "same")):
            with self.subTest(source=source, target=target), self.assertRaisesRegex(ValueError, "explicit"):
                export_component_exit(self.run, self.output, source_instance_id=source, target_instance_id=target)
            self.assertFalse(self.output.exists())

    def test_complete_negative_native_exports_81_states_and_preserves_19_losses_and_failed_result(self) -> None:
        self._negative_population()
        before = file_record(self.run/"summary.json")
        receipt = export_component_exit(self.run, self.output, source_instance_id="processor_a", target_instance_id="analyzer_b")
        self.assertEqual(receipt["counts"], dict(source=100, transferred=81, not_transferred=19))
        self.assertEqual(receipt["transferred_particle_ids"], list(range(1, 82)))
        self.assertEqual(receipt["lost_particle_ids"], list(range(82, 101)))
        self.assertEqual(receipt["producer_result"], dict(source_scientific_status="failed",
            checks=self.summary["checks"], functional_status="functional_incomplete",
            qualification="synthetic_fixture_not_native_flight"))
        self.assertEqual(file_record(self.run/"summary.json"), before)
        self.assertEqual(len(self._read_output_rows("component_particle_state.csv")), 81)
        self.assertEqual(len(self._read_output_rows("source_census.csv")), 100)

    def _read_output_rows(self, name: str) -> list:
        with (self.output/name).open(encoding="utf-8", newline="") as stream:
            return list(csv.DictReader(stream))

    def test_negative_result_does_not_admit_incomplete_native_or_merge(self) -> None:
        self._negative_population()
        names = ("results/simion_batch_resource_usage.json", "results/batch_merge_receipt.json")
        originals = {name: json.loads((self.run/name).read_text()) for name in names}
        changes = [(names[0], dict(status="running")), (names[0], dict(status="process_failed")),
                   (names[0], dict(failure_class="native_error")),
                   (names[0], dict(execution_wave=dict(process_count=10))),
                   (names[1], dict(all_ids_closed=False)), (names[1], dict(particle_count=99)),
                   (names[1], dict(rng_policy="different_rng"))]
        for name, values in changes:
            with self.subTest(values=values):
                for reset, document in originals.items():
                    self._write_json(reset, document)
                self._write_json(name, {**originals[name], **values})
                self._seal()
                with self.assertRaisesRegex(ValueError, "native execution or batch merge"):
                    export_component_exit(self.run, self.output, source_instance_id="processor_a", target_instance_id="analyzer_b")
                self.assertFalse(self.output.exists())

    def test_native_receipt_identity_drift_is_rejected_before_output(self) -> None:
        self._negative_population()
        with (self.run/"results/batch_merge_receipt.json").open("a") as stream:
            stream.write(" ")
        with self.assertRaises(AssertionError):
            export_component_exit(self.run, self.output, source_instance_id="processor_a", target_instance_id="analyzer_b")
        self.assertFalse(self.output.exists())

    def test_error_summary_or_scientific_status_mismatch_is_rejected(self) -> None:
        self._negative_population()
        original = dict(self.summary)
        for values in (dict(role="ion_processor_failed_run"),
                       dict(checks={}), dict(status="success")):
            with self.subTest(values=values):
                self.summary = {**original, **values}
                self._write_json("summary.json", self.summary)
                self._seal()
                with self.assertRaises(ValueError):
                    export_component_exit(self.run, self.output, source_instance_id="processor_a", target_instance_id="analyzer_b")
                self.assertFalse(self.output.exists())
        self.summary = original
        self._write_json("summary.json", self.summary)
        self._seal()
        manifest = json.loads((self.run/"run_manifest.json").read_text())
        manifest["status"] = "success"
        self._write_json("run_manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "summary identity"):
            export_component_exit(self.run, self.output, source_instance_id="processor_a", target_instance_id="analyzer_b")

    def test_complete_negative_zero_exit_does_not_create_transfer_package(self) -> None:
        self._negative_population()
        events = [dict(row, reason="solver_stop") if row["event"] == "terminal" else row
                  for row in self.events if row["event"] != "extraction_exit"]
        self._write_csv("simion/events.csv", events)
        self.summary["metrics"]["extraction_exit"]["count"] = 0
        self.summary["terminal_reasons"] = dict(solver_stop=100)
        self._write_json("summary.json", self.summary)
        self._seal()
        with self.assertRaisesRegex(ValueError, "no transferable extraction states"):
            export_component_exit(self.run, self.output, source_instance_id="processor_a", target_instance_id="analyzer_b")
        self.assertFalse(self.output.exists())

    def test_preserves_noncontiguous_ids_complete_state_and_variable_absolute_clocks(self) -> None:
        receipt = export_component_exit(self.run, self.output, source_instance_id="processor_a", target_instance_id="analyzer_b")
        self.assertEqual(receipt["counts"], {"source": 3, "transferred": 2, "not_transferred": 1})
        self.assertEqual(receipt["transferred_particle_ids"], [2, 20])
        self.assertEqual(receipt["lost_particle_ids"], [9])
        self.assertEqual(receipt["observation_surface"]["semantics"], "recorded_stop_plane_not_physical_port")
        self.assertEqual(validate_component_particle_state_csv(self.output / "component_particle_state.csv")["status"], "PASS")
        with (self.output / "component_particle_state.csv").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([float(row["instrument_time_us"]) for row in rows], [112.2, 114])
        self.assertEqual([float(row["particle_birth_time_us"]) for row in rows], [102, 105])
        self.assertAlmostEqual(float(rows[0]["particle_age_us"]), 10.2)
        self.assertEqual(float(rows[0]["velocity_z_m_s"]), -38000)
        self.assertEqual(float(rows[0]["velocity_x_m_s"]), 10)
        self.assertEqual(rows[0]["phase_rad"], "")
        with (self.output / "source_census.csv").open(newline="") as handle:
            census = list(csv.DictReader(handle))
        self.assertEqual([row["particle_id"] for row in census], ["2", "9", "20"])
        self.assertEqual(census[1]["terminal_reason"], "solver_stop")

    def test_injected_export_preserves_birth_arrival_clock_and_upstream_losses(self) -> None:
        self.model["baseline"]["clock"]["epoch_us"] = 0
        self.model["injected_source"] = dict(particle_ids=[2, 9, 20], mother_particle_count=4)
        self._write_json("inputs/resolved_model.json", self.model)
        self._write_json("inputs/instrument_epoch.json", dict(instrument_time_us=0))
        clock = json.loads((self.run/"inputs/clock_authority.json").read_text())
        clock["clock_epoch_id"] = "instrument_clock_epoch_v1"
        clock["authority"]["sha256"] = file_record(self.run/"inputs/instrument_epoch.json")["sha256"]
        self._write_json("inputs/clock_authority.json", clock)
        rows = []
        for release in self.releases:
            birth = release["birth_time_s"]*1e6
            arrival = birth+1
            pid = release["particle_id"]
            rows.append(dict(particle_id=pid, parent_particle_id="", generation=0, species_id="upstream_ion",
                particle_weight=1, source_component_id="multipole", target_component_id="ion_processor",
                state_event="mechanical_exit", frame_id="local", clock_epoch_id=clock["clock_epoch_id"],
                instrument_time_us=arrival, lineage_age_us=1, particle_age_us=1, last_component_elapsed_time_us=1,
                lineage_birth_time_us=birth, particle_birth_time_us=birth, mass_to_charge_Th=mass_to_charge_th(524, 1),
                mass_amu=524, charge_state=1, position_x_mm=1, position_y_mm=0, position_z_mm=0,
                velocity_x_m_s=1000, velocity_y_m_s=0, velocity_z_m_s=0,
                kinetic_energy_eV=kinetic_energy_ev(524, 1000, 0, 0), phase_reference_id="", phase_rad=""))
            next(event for event in self.events if event["particle_id"] == pid and event["event"] == "source")["t_us"] = arrival
        write_component_particle_state_csv(self.run/"inputs/injected_states.csv", rows)
        self._write_csv("simion/events.csv", self.events)
        self._write_json("inputs/injected_source.json", dict(role="ip_injected_source"))
        self._write_json("inputs/upstream_mother_census.json", dict(mother_particle_ids=[2, 9, 20, 99]))
        self._write_csv("inputs/upstream_mother_fates.csv", [dict(particle_id=pid,
            particle_birth_time_us=.5, mass_amu=524, charge_state=1,
            terminal_instrument_time_us=1, terminal_reason="upstream_stop") for pid in (2, 9, 20, 99)])
        self._seal()
        receipt = export_component_exit(self.run, self.output, source_instance_id="processor_a", target_instance_id="analyzer_b")
        self.assertEqual(receipt["counts"], dict(source=4, transferred=2, not_transferred=2))
        self.assertEqual(receipt["lost_particle_ids"], [9, 99])
        with (self.output/"component_particle_state.csv").open(newline="") as stream:
            transferred = list(csv.DictReader(stream))
        self.assertEqual(float(transferred[0]["particle_birth_time_us"]), 2)
        self.assertAlmostEqual(float(transferred[0]["last_component_elapsed_time_us"]), 9.2)
        self.assertEqual(transferred[0]["clock_epoch_id"], clock["clock_epoch_id"])

    def test_reuses_verified_identities_with_absolute_receipt_paths(self) -> None:
        manifest = json.loads((self.run / "run_manifest.json").read_text())
        for record in [manifest["run_config"], *manifest["inputs"].values(), *manifest["outputs"]]:
            record["path"] = Path(record["path"]).relative_to(self.run).as_posix()
        self._write_json("run_manifest.json", manifest)
        with patch("projects.dual_pressure_rectilinear_ion_processor.analysis.component_exit.file_record", wraps=file_record) as recorder:
            receipt = export_component_exit(self.run, self.output, source_instance_id="processor_a", target_instance_id="analyzer_b")
        source_reads = [Path(call.args[0]) for call in recorder.call_args_list if self.run in Path(call.args[0]).parents]
        self.assertEqual(source_reads, [self.run / "run_manifest.json"])
        for name, record in receipt["inputs"].items():
            self.assertEqual(record, file_record(self.run / name))

    def test_receipt_wrong_path_or_identity_is_rejected_even_when_resealed(self) -> None:
        original = json.loads((self.run / "inputs/release_receipt.json").read_text())
        for role in ("state_table", "source_spec"):
            for change in ({"path": str(self.run / "summary.json")}, {"bytes": 0}, {"sha256": "0" * 64}):
                with self.subTest(role=role, change=change):
                    document = {**original, role: {**original[role], **change}}
                    self._write_json("inputs/release_receipt.json", document)
                    self._seal()
                    with self.assertRaisesRegex(ValueError, "release receipt .*identity differs"):
                        export_component_exit(self.run, self.output, source_instance_id="processor_a", target_instance_id="analyzer_b")
                    self.assertFalse(self.output.exists())

    def test_conflicting_manifest_roles_are_rejected(self) -> None:
        manifest = json.loads((self.run / "run_manifest.json").read_text())
        source = manifest["inputs"]["source.json"]
        manifest["outputs"].append({**source, "sha256": "0" * 64})
        self._write_json("run_manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "conflicting manifest identity"):
            export_component_exit(self.run, self.output, source_instance_id="processor_a", target_instance_id="analyzer_b")
        self.assertFalse(self.output.exists())

    def test_overwrite_is_refused_without_source_changes(self) -> None:
        source_identity = file_record(self.run / "simion/events.csv")
        export_component_exit(self.run, self.output, source_instance_id="processor_a", target_instance_id="analyzer_b")
        with self.assertRaises(FileExistsError):
            export_component_exit(self.run, self.output, source_instance_id="processor_a", target_instance_id="analyzer_b")
        self.assertEqual(source_identity, file_record(self.run / "simion/events.csv"))

    def test_manifest_identity_tamper_fails(self) -> None:
        with (self.run / "simion/events.csv").open("a") as handle:
            handle.write("\n")
        with self.assertRaises(AssertionError):
            export_component_exit(self.run, self.output, source_instance_id="processor_a", target_instance_id="analyzer_b")
        self.assertFalse(self.output.exists())

    def test_rejects_invalid_closure_state_and_species(self) -> None:
        original = [dict(row) for row in self.events]
        variants = []
        variants.append([row for row in original if not (row["particle_id"] == 9 and row["event"] == "terminal")])
        variants.append(original + [dict(original[0])])
        variants.append([dict(row, vz_mm_us=1) if row["particle_id"] == 2 and row["event"] in {"extraction_exit", "terminal"} else row for row in original])
        variants.append([dict(row, t_us=1) if row["particle_id"] == 9 and row["event"] == "terminal" else row for row in original])
        variants.append([dict(row, x_mm=.3) if row["particle_id"] == 2 and row["event"] == "terminal" else row for row in original])
        variants.append([dict(row, x_mm=float("nan")) if row["event"] == "source" else row for row in original])
        for index, events in enumerate(variants):
            with self.subTest(index=index):
                self._write_csv("simion/events.csv", events)
                self._seal()
                with self.assertRaises(ValueError):
                    export_component_exit(self.run, self.output, source_instance_id="processor_a", target_instance_id="analyzer_b")
                self.assertFalse(self.output.exists())

    def test_retired_source_uses_public_retirement_verifier(self) -> None:
        self._write_json("solver_review_retirement_receipt.json", {"test": "verification delegation only"})
        with patch("projects.dual_pressure_rectilinear_ion_processor.analysis.component_exit.verify_retirement", return_value={"status": "PASS"}) as verifier:
            receipt = export_component_exit(self.run, self.output, source_instance_id="processor_a", target_instance_id="analyzer_b")
        verifier.assert_called_once_with(self.run)
        self.assertIn("solver_review_retirement_receipt.json", receipt["inputs"])

    def test_invalid_species_fails_even_when_manifest_is_resealed(self) -> None:
        self.releases[0]["mass_amu"] = -1
        self._write_csv("inputs/release.csv", self.releases)
        receipt = json.loads((self.run / "inputs/release_receipt.json").read_text())
        receipt["state_table"] = file_record(self.run / "inputs/release.csv")
        self._write_json("inputs/release_receipt.json", receipt)
        self._seal()
        with self.assertRaisesRegex(ValueError, "species"):
            export_component_exit(self.run, self.output, source_instance_id="processor_a", target_instance_id="analyzer_b")


if __name__ == "__main__":
    unittest.main()
