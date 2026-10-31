"""Synthetic admission contracts only; no solver flight or physical claims."""
from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from common.contracts.component_particle_state import write_component_particle_state_csv
from common.contracts.file_identity import file_sha256
from common.contracts.particle_physics import kinetic_energy_ev, mass_to_charge_th
from common.contracts.write_run_manifest import file_record
from projects.dual_pressure_rectilinear_ion_processor.analysis.upstream_admission import (
    FATE_COLUMNS, frozen_release_states, load_injected_source, release_states,
)
from projects.dual_pressure_rectilinear_ion_processor.analysis import functional, batching
from projects.dual_pressure_rectilinear_ion_processor.tests.test_functional import HS1_SOURCE_FIXTURE

PROJECT = Path(__file__).resolve().parents[1]


class AdmissionTests(unittest.TestCase):
    def test_source_protection_projection_includes_clock_and_producer_owner(self):
        from projects.dual_pressure_rectilinear_ion_processor.analysis.upstream_admission import injected_source_protection_paths
        paths = injected_source_protection_paths(self.inputs / "injected_source.json")
        self.assertIn(self.inputs.resolve(), paths)
        self.assertIn(self.producer.resolve(), paths)
        consumer = self.run / "changed_authority_consumer"
        for folder in ("inputs", "simion", "results", "logs"):
            (consumer / folder).mkdir(parents=True)
        vendor = self.run / "inert_vendor_protection_fixture"
        (vendor / "examples/collision_hs1").mkdir(parents=True)
        (vendor / "examples/collision_hs1/collision_hs1.lua").write_text(HS1_SOURCE_FIXTURE)
        functional.write_json(consumer / "run_config.json", dict(inputs={}))
        with self.assertRaisesRegex(ValueError, "protection authorities changed"):
            functional.prepare(consumer, PROJECT, vendor, injected_source=self.inputs / "injected_source.json",
                               protected_injected_paths=paths[:-1])
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        self.inputs = self.run / "inputs"
        self.inputs.mkdir()
        self.write("instrument_epoch.json", dict(instrument_time_us=0.))
        self.clock = dict(schema_version=1, role="canonical_clock_authority",
            clock_epoch_id="instrument_clock_epoch_v1", instrument_time_unit="us",
            canonical_time_basis="instrument_epoch_absolute_time",
            authority=dict(path="inputs/instrument_epoch.json", sha256=file_sha256(self.inputs/"instrument_epoch.json"),
                           field="instrument_time_us"), solver_local_time_basis="elapsed_time_from_zero_us",
            adapter_materialization="instrument_time_us_equals_authority_epoch_plus_solver_elapsed_once",
            handoff_policy="preserve_instrument_time_us_and_clock_epoch_id", legacy_new_campaign_allowed=False)
        self.write("clock_authority.json", self.clock)
        self.producer = self.run / "producer"
        self.producer.mkdir()
        self.producer_summary = dict(schema_version=1, role="multipole_simion_finite_3d_transport_summary",
            status="success", project_id="rf_octupole_ion_optics", design_profile_id="fixture",
            qualification_status="UNQUALIFIED")
        (self.producer / "run_config.json").write_text(json.dumps(dict(project="rf_octupole_ion_optics")))
        self.publish_producer()
        self.census = dict(schema_version=1, role="multipole_mechanical_exit_census", status="PASS",
            mother_count=3, exit_count=2, non_exit_count=1, mother_particle_ids=[2, 9, 42],
            exit_particle_ids=[2, 42], non_exit_particle_ids=[9],
            terminal_reasons={"2": "acceptance_surface", "9": "solver_stop", "42": "acceptance_surface"})
        self.write("mother_census.json", self.census)
        with (self.inputs/"mother_fates.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=FATE_COLUMNS)
            writer.writeheader()
            writer.writerows(dict(particle_id=pid, particle_birth_time_us=.5, mass_amu=100., charge_state=1,
                terminal_instrument_time_us=50., terminal_reason=self.census["terminal_reasons"][str(pid)])
                for pid in (2, 9, 42))
        self.rows = [dict(particle_id=pid, parent_particle_id="", generation=0, species_id="reference_100da_ion",
            particle_weight=1, source_component_id="multipole", target_component_id="ion_processor",
            state_event="mechanical_exit", frame_id="dual_pressure_ion_processor_local_v1",
            clock_epoch_id=self.clock["clock_epoch_id"], instrument_time_us=43.+pid/100,
            lineage_age_us=42.5+pid/100, particle_age_us=42.5+pid/100,
            last_component_elapsed_time_us=42.5+pid/100, lineage_birth_time_us=.5,
            particle_birth_time_us=.5, mass_to_charge_Th=mass_to_charge_th(100., 1), mass_amu=100., charge_state=1,
            position_x_mm=0., position_y_mm=.1, position_z_mm=-.2,
            velocity_x_m_s=2000., velocity_y_m_s=10., velocity_z_m_s=-20.,
            kinetic_energy_eV=kinetic_energy_ev(100., 2000., 10., -20.), phase_reference_id="", phase_rad="")
            for pid in (2, 42)]
        write_component_particle_state_csv(self.inputs/"source_states.csv", self.rows)
        self.contract = dict(schema_version=1, role="ip_injected_source",
            frame_id="dual_pressure_ion_processor_local_v1", target_component_id="ion_processor",
            producer_case_id="rf_on", **{key: file_record(self.inputs/name) for key, name in (
                ("clock_authority", "clock_authority.json"), ("source_states", "source_states.csv"),
                ("mother_census", "mother_census.json"), ("mother_fates", "mother_fates.csv"),
                ("producer_manifest", "producer_manifest.json"))})
        self.publish()

    def publish_producer(self):
        summary = self.producer / "summary.json"
        summary.write_text(json.dumps(self.producer_summary), encoding="utf-8")
        self.write("producer_manifest.json", dict(status=self.producer_summary["status"],
            project="rf_octupole_ion_optics", run_config=file_record(self.producer / "run_config.json"),
            outputs=[file_record(summary)] + [
                file_record(path) for path in (self.producer / "results").glob("*.json")]))
        if hasattr(self, "contract"):
            self.refresh("producer_manifest", "producer_manifest.json")

    def test_scientific_failed_source_is_distinct_from_generic_or_incomplete_failure(self):
        checks = {"minimum_primary_transmission": False}
        self.producer_summary.update(status="failed", native_execution_complete=True,
                                     qualification_status="FAIL", checks=checks)
        (self.producer / "results").mkdir()
        evaluation = self.producer / "results/evidence_evaluation.json"
        evaluation.write_text(json.dumps(dict(schema_version=1, role="multipole_transport_evidence_evaluation",
            status="FAIL", project_id="rf_octupole_ion_optics", design_profile_id="fixture",
            evaluation="rf_vs_zero_rf", checks=checks)), encoding="utf-8")
        self.publish_producer()
        admission = self.load()
        self.assertEqual(admission["producer_result"]["source_scientific_status"], "failed")
        self.assertEqual(admission["producer_result"]["checks"], checks)
        self.assertEqual([row["particle_id"] for row in admission["rows"]], [2, 42])
        self.assertEqual(admission["census"]["non_exit_particle_ids"], [9])
        self.producer_summary["native_execution_complete"] = False
        self.publish_producer()
        with self.assertRaisesRegex(ValueError, "completion|complete"):
            self.load()
        self.producer_summary = dict(schema_version=1, role="multipole_simion_finite_3d_transport_summary",
                                     status="failed", reason="solver error")
        self.publish_producer()
        with self.assertRaises(ValueError):
            self.load()

    def write(self, name, value):
        (self.inputs/name).write_text(json.dumps(value), encoding="utf-8")

    def publish(self):
        self.write("injected_source.json", self.contract)

    def refresh(self, key, name):
        self.contract[key] = file_record(self.inputs/name)
        self.publish()

    def load(self):
        return load_injected_source(self.inputs/"injected_source.json")

    def test_admission_reads_canonical_csv_once_with_typed_states(self):
        source = self.inputs/"source_states.csv"
        open_file, reads = Path.open, []

        def track(path, *args, **kwargs):
            if path == source and (not args or args[0] == "r"):
                reads.append(path)
            return open_file(path, *args, **kwargs)

        with patch.object(Path, "open", track):
            admission = self.load()
        self.assertEqual(len(reads), 1)
        self.assertIs(type(admission["rows"][0]["particle_id"]), int)
        self.assertIs(type(admission["rows"][0]["instrument_time_us"]), float)
        self.assertIsNone(admission["rows"][0]["phase_reference_id"])
        self.assertEqual(admission["census"], self.census)

    def test_sparse_ids_species_original_birth_and_absolute_arrival_are_retained(self):
        admission = self.load()
        states = release_states(admission)
        self.assertEqual([r["particle_id"] for r in states], [2, 42])
        self.assertEqual(admission["census"]["non_exit_particle_ids"], [9])
        self.assertEqual(admission["clock"], self.clock)
        self.assertEqual(states[0]["mass_amu"], 100)
        self.assertEqual(states[0]["birth_time_s"], .5e-6)
        self.assertEqual(states[0]["arrival_time_us"], 43.02)
        self.assertEqual((states[0]["x_mm"], states[0]["vx_m_s"]), (0, 2000))

    def test_relative_weights_follow_original_ids_without_changing_native_states(self):
        original = release_states(self.load())
        for weights in ({2: 1., 42: 1.}, {2: 3.5, 42: 3.5}, {2: .125, 42: 8.}):
            with self.subTest(weights=weights):
                rows = [dict(row, particle_weight=weights[row["particle_id"]])
                        for row in reversed(self.rows)]
                write_component_particle_state_csv(self.inputs/"source_states.csv", rows)
                self.refresh("source_states", "source_states.csv")
                before = file_record(self.inputs/"source_states.csv")
                states = release_states(self.load())
                self.assertEqual({r["particle_id"]: r["particle_weight"] for r in states}, weights)
                self.assertEqual([{k: v for k, v in r.items() if k != "particle_weight"} for r in states],
                                 [{k: v for k, v in r.items() if k != "particle_weight"} for r in original])
                self.assertEqual(file_record(self.inputs/"source_states.csv"), before)

    def test_missing_injected_weight_or_original_id_is_not_replaced(self):
        path = self.inputs/"source_states.csv"
        rows = [dict(row, particle_weight="") for row in self.rows]
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        self.refresh("source_states", "source_states.csv")
        with self.assertRaises(ValueError):
            self.load()
        write_component_particle_state_csv(path, self.rows[:1])
        self.refresh("source_states", "source_states.csv")
        with self.assertRaisesRegex(ValueError, "cohort"):
            self.load()

    def test_recipe_instance_ids_survive_freezing_and_target_mismatch_is_rejected(self):
        original = release_states(self.load())
        self.rows = [dict(row,source_component_id="guide_a",target_component_id="processor_b") for row in self.rows]
        write_component_particle_state_csv(self.inputs/"source_states.csv", self.rows)
        self.contract["target_component_id"] = "processor_b"
        self.refresh("source_states", "source_states.csv")
        self.assertEqual(release_states(self.load()), original)
        consumer, _ = self.prepare_consumer()
        frozen = load_injected_source(consumer/"inputs/injected_source.json")
        self.assertEqual(frozen["contract"]["target_component_id"], "processor_b")
        self.assertTrue(all(row["source_component_id"] == "guide_a" and row["target_component_id"] == "processor_b"
                            for row in frozen["rows"]))
        self.assertEqual(release_states(frozen), original)
        self.contract["target_component_id"] = "another_processor"
        self.publish()
        with self.assertRaisesRegex(ValueError, "identity/frame/clock/mechanical exit"):
            self.load()

    def test_internal_handoff_and_wrong_frame_are_refused(self):
        for key, value in (("state_event", "handoff"), ("frame_id", "wrong_frame")):
            rows = [dict(row, **{key: value}) for row in self.rows]
            write_component_particle_state_csv(self.inputs/"source_states.csv", rows)
            self.refresh("source_states", "source_states.csv")
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "mechanical exit"):
                self.load()

    def test_no_survivors_is_explicit_empty_admission_with_full_fate(self):
        self.census.update(exit_count=0, non_exit_count=3, exit_particle_ids=[], non_exit_particle_ids=[2, 9, 42])
        self.write("mother_census.json", self.census)
        self.refresh("mother_census", "mother_census.json")
        self.contract["source_states"] = None
        self.publish()
        admission = self.load()
        self.assertEqual(release_states(admission), [])
        self.assertEqual(set(admission["mother_fates"]), {2, 9, 42})

    def test_content_tampering_and_missing_mother_are_rejected(self):
        path = self.inputs/"mother_fates.csv"
        original = path.read_text()
        path.write_text(original.replace("100.0", "524.0"))
        with self.assertRaises(AssertionError):
            self.load()
        path.write_text("\n".join(original.splitlines()[:-1])+"\n")
        self.refresh("mother_fates", "mother_fates.csv")
        with self.assertRaisesRegex(ValueError, "every mother ID"):
            self.load()

    def test_known_mother_weights_must_match_transferred_states(self):
        path = self.inputs/"mother_fates.csv"
        with path.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        for row in rows:
            row["particle_weight"] = "2" if row["particle_id"] == "2" else "1"
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=FATE_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        self.refresh("mother_fates", "mother_fates.csv")
        with self.assertRaisesRegex(ValueError, "identity/frame/clock/mechanical exit"):
            self.load()

    def test_published_handoff_uses_public_reference_and_freezes_its_authority(self):
        result = self.load()["producer_result"]
        root = self.run/"preparation"
        output = root/"results/multipole_ip"
        output.mkdir(parents=True)
        source = output/"ip_injected_source.json"
        source.write_text(json.dumps(self.contract), encoding="utf-8")
        receipt_path = output/"preparation_receipt.json"
        receipt_path.write_text(json.dumps(dict(role="multipole_ip_preparation", status="success",
            source=dict(manifest=self.contract["producer_manifest"]), injected_source=file_record(source),
            producer_result=result)), encoding="utf-8")
        (root/"run_manifest.json").write_text(json.dumps(dict(run_id=root.name, project="instrument_assembly",
            mode="multipole_ip_preparation", status="success", inputs={},
            outputs=[file_record(source), file_record(receipt_path)])), encoding="utf-8")
        with patch("projects.rf_multipole_ion_optics.core.component_port.load_transport_producer_result",
                   side_effect=AssertionError("private producer reader must not run")):
            admission = load_injected_source(source)
            self.assertEqual(admission["producer_result"], result)
            destination = self.run/"frozen"
            (destination/"inputs").mkdir(parents=True)
            from projects.dual_pressure_rectilinear_ion_processor.analysis.upstream_admission import freeze_injected_source
            freeze_injected_source(admission, destination)
            frozen = load_injected_source(destination/"inputs/injected_source.json")
            self.assertEqual(frozen["producer_result"], result)
            from common.contracts.write_run_manifest import TERMINAL_JOURNAL_NAME
            journal = root/TERMINAL_JOURNAL_NAME
            journal.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "terminal publication is incomplete"):
                load_injected_source(destination/"inputs/injected_source.json")
            journal.unlink()
            receipt_path.write_text("{}", encoding="utf-8")
            with self.assertRaises(AssertionError):
                load_injected_source(destination/"inputs/injected_source.json")

    def test_in_progress_production_handoff_is_rejected(self):
        root = self.run/"in_progress"
        output = root/"results/multipole_ip"
        output.mkdir(parents=True)
        (root/"run_config.json").write_text(json.dumps(dict(mode="multipole_ip_preparation")), encoding="utf-8")
        source = output/"ip_injected_source.json"
        source.write_text(json.dumps(self.contract), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not completed terminal publication"):
            load_injected_source(source)

    def test_species_cannot_be_replaced_by_ip_default(self):
        rows = [dict(row, mass_amu=524., mass_to_charge_Th=mass_to_charge_th(524., 1),
                     kinetic_energy_eV=kinetic_energy_ev(524., 2000., 10., -20.)) for row in self.rows]
        write_component_particle_state_csv(self.inputs/"source_states.csv", rows)
        self.refresh("source_states", "source_states.csv")
        with self.assertRaisesRegex(ValueError, "identity"):
            self.load()

    def prepare_consumer(self):
        consumer = self.run/"consumer"
        for folder in ("inputs", "simion", "results", "logs"):
            (consumer/folder).mkdir(parents=True)
        vendor = self.run/"inert_vendor_fixture"
        (vendor/"examples/collision_hs1").mkdir(parents=True)
        (vendor/"examples/collision_hs1/collision_hs1.lua").write_text(HS1_SOURCE_FIXTURE)
        functional.write_json(consumer/"run_config.json", dict(inputs={}))
        with patch.object(functional.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="fixture")):
            functional.prepare(consumer, PROJECT, vendor, injected_source=self.inputs/"injected_source.json")
        return consumer, functional.read_json(consumer/"inputs/resolved_model.json")

    def test_real_prepare_freezes_actual_source_clock_and_batch_identity(self):
        weights = {2: .125, 42: 8.}
        self.rows = [dict(row, particle_weight=weights[row["particle_id"]]) for row in reversed(self.rows)]
        write_component_particle_state_csv(self.inputs/"source_states.csv", self.rows)
        self.refresh("source_states", "source_states.csv")
        consumer, config = self.prepare_consumer()
        clock_schema = consumer / "inputs/code/common/contracts/schemas/canonical_clock_authority.schema.json"
        self.assertEqual(clock_schema.read_bytes(),
                         (PROJECT.parents[1] / "common/contracts/schemas/canonical_clock_authority.schema.json").read_bytes())
        self.assertIn(str(clock_schema), functional.read_json(consumer / "run_config.json")["inputs"].values())
        self.assertEqual({row["particle_id"]: row["particle_weight"]
                          for row in frozen_release_states(consumer, config)}, weights)
        self.assertEqual(config["source_profile"], "upstream")
        self.assertEqual(config["source"]["particle_count"], 2)
        self.assertEqual(config["source"]["mother_particle_count"], 3)
        self.assertEqual(config["source"]["species"], dict(mass_amu=100, charge_state=1))
        self.assertEqual((consumer/"inputs/clock_authority.json").read_bytes(), (self.inputs/"clock_authority.json").read_bytes())
        self.assertIn("tob = 43.02", (consumer/"simion/processor.fly2").read_text())
        self.assertFalse((consumer/"inputs/release.csv").exists())
        self.assertEqual(load_injected_source(consumer/"inputs/injected_source.json")["census"], self.census)
        config["native_field"]["source_manifest"] = "inert_existing_field_manifest"
        functional.write_json(consumer/"inputs/resolved_model.json", config)
        (consumer/"simion/processor.iob").write_bytes(b"inert native workbench fixture")
        (consumer/"simion/processor.lua").write_text("-- inert copied program")
        functional.write_json(consumer/"inputs/runtime_profiles.json", functional.read_json(PROJECT/"config/runtime_profiles.json"))
        batch = dict(index=1, particle_id_min=1, particle_id_max=2, simion_particle_id_offset=0, count=2)
        plan = consumer/"inputs/batch_plan.json"
        functional.write_json(plan, dict(particle_count=2, batches=[batch]))
        batching.materialize_batches(consumer, plan)
        worker = consumer/"simion_batch_0001"
        self.assertEqual(functional.read_json(worker/"batch_input.json")["source_global_ids"], [2, 42])
        self.assertIn('["global_particle_ids"]={2,42}', (worker/"frozen_config.lua").read_text())
        self.assertIn("tob = 43.42", (worker/"processor.fly2").read_text())

    def test_empty_admission_prepares_and_analyzes_without_flight_or_resampling(self):
        self.census.update(exit_count=0, non_exit_count=3, exit_particle_ids=[], non_exit_particle_ids=[2, 9, 42])
        self.write("mother_census.json", self.census)
        self.refresh("mother_census", "mother_census.json")
        self.contract["source_states"] = None
        self.publish()
        consumer, config = self.prepare_consumer()
        self.assertEqual(config["source"]["particle_count"], 0)
        with patch.object(functional, "generate_release_states", side_effect=AssertionError("must not resample")):
            summary = functional.analyze(consumer)
        self.assertEqual(summary["status"], "success")
        self.assertFalse(summary["solver_executed"])
        self.assertEqual(summary["mother_particle_count"], 3)
        config_path = consumer/"run_config.json"
        run_config = json.loads(config_path.read_text(encoding="utf-8"))
        run_config.update(run_id=consumer.name, project="dual_pressure_rectilinear_ion_processor", mode="native_electrode_functional")
        config_path.write_text(json.dumps(run_config), encoding="utf-8")
        manifest = dict(status="success", project=run_config["project"], run_id=consumer.name,
            mode=run_config["mode"], run_config=file_record(config_path),
            inputs={p.name: file_record(p) for p in (consumer/"inputs").iterdir() if p.is_file()},
            outputs=[file_record(consumer/"summary.json")])
        (consumer/"run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        from projects.dual_pressure_rectilinear_ion_processor.analysis.component_exit import export_component_exit
        output = self.run/"zero_exit_export"
        receipt = export_component_exit(consumer, output, source_instance_id="ip", target_instance_id="mr")
        self.assertEqual(receipt["status"], "zero_exit")
        self.assertEqual(receipt["not_transferred_particle_ids"], [2, 9, 42])
        self.assertEqual(receipt["producer_result"]["functional_status"], "upstream_empty")
        with (output/"source_census.csv").open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual([row["terminal_reason"] for row in rows], ["acceptance_surface", "solver_stop", "acceptance_surface"])

    def test_analyzer_uses_actual_arrival_birth_species_and_conditional_population(self):
        consumer, config = self.prepare_consumer()
        sources = release_states(self.load())
        events = []
        for source in sources:
            position = functional.to_project_position(config, [source[f"{a}_mm"] for a in "xyz"])
            velocity = functional.to_project_vector(config, [source[f"v{a}_m_s"]/1000 for a in "xyz"])
            row = dict(particle_id=source["particle_id"], event="source", reason="none",
                t_us=source["arrival_time_us"], **dict(zip(("x_mm", "y_mm", "z_mm"), position)),
                **dict(zip(("vx_mm_us", "vy_mm_us", "vz_mm_us"), velocity)))
            events.extend([row, dict(row, event="terminal", reason="solver_stop", t_us=row["t_us"]+.1)])
        batching._csv(consumer/"simion/events.csv", list(events[0]), events)
        with patch.object(functional, "generate_release_states", side_effect=AssertionError("must not resample")), \
                patch("projects.dual_pressure_rectilinear_ion_processor.analysis.diagnostics.export_diagnostics"), \
                patch("projects.dual_pressure_rectilinear_ion_processor.analysis.field_diagnostics.export_field_diagnostics"), \
                patch("projects.dual_pressure_rectilinear_ion_processor.analysis.extraction_force_budget.export_force_budget"):
            summary = functional.analyze(consumer)
        self.assertEqual(summary["status"], "failed")  # Both prescribed stops fail physical capture.
        self.assertEqual(summary["actual_particle_count"], 2)
        self.assertEqual(summary["mother_particle_count"], 3)
        _, canonical = batching._rows(consumer/"results/particle_state.csv")
        self.assertAlmostEqual(float(canonical[0]["time_us"]), 43.02)
        self.assertAlmostEqual(float(canonical[0]["elapsed_time_us"]), 42.52)
        self.assertAlmostEqual(float(canonical[0]["kinetic_energy_eV"]), self.rows[0]["kinetic_energy_eV"])
