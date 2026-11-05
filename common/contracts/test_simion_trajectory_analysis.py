"""Manifest-bound software data fixtures; no native trajectory evidence claimed."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from msplatform.assembly.handoff import HandoffMother
from msplatform.backends.simion.source import project_source_states
from msplatform.backends.simion.trajectory_analysis import analyze_published_trajectory
from msplatform.contracts.clock import ClockIdentity
from msplatform.execution.artifact_reader import open_artifact
from msplatform.execution.manifest_records import file_record
from msplatform.execution.terminal_publication import publish_terminal_state
from common.contracts.test_handoff import state


class PublishedTrajectoryAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        example = Path(__file__).resolve().parents[2] / "src/msplatform/examples"
        self.contract = json.loads((example / "instrument_clock_authority_v1.json").read_text())
        self.contract["clock_epoch_id"] = "epoch"
        (self.root / "instrument_epoch_v1.json").write_bytes((example / "instrument_epoch_v1.json").read_bytes())
        self.clock = ClockIdentity("epoch", self.contract["authority"]["sha256"])
        self.write("clock_authority.json", self.contract)
        self.clock_records = dict(clock_authority=file_record(self.root / "clock_authority.json"),
                                  instrument_epoch=file_record(self.root / "instrument_epoch_v1.json"))
        records = {pid: state(pid) for pid in (7, 99, 123, 201)}
        self.mother = HandoffMother(records, [dict(particle_id=pid, terminal_reason="unknown") for pid in records])
        self.states = [state(pid) for pid in (7, 99, 123)]
        _, self.provenance = project_source_states(self.states, mother=self.mother, clock=self.clock,
            state_kind="time_snapshot", clock_records=self.clock_records)
        self.collection = dict(schema_version=1, role="simion_tracking_collection", native_complete=True,
            native_calls=3, clock_epoch_id="epoch", model_identity_sha256="B" * 64,
            original_mother={key: copy.deepcopy(self.provenance[key]) for key in
                ("mother_particle_ids", "mother_records", "mother_fates", "clock_authority_sha256", "clock_records")},
            census={"terminal_taxonomy": {"classification_is_mutually_exclusive_and_exhaustive": True,
                "particle_outcomes": [dict(particle_id=pid, category="detector_crossing") for pid in (7, 99, 123)]}},
            canonical_events=[dict(particle_id=pid, event="detector_crossing", instrument_time_us=t)
                              for pid, t in zip((7, 99, 123), (21., 22., 24.))])
        self.selection = dict(schema_version=1, particle_ids=[7, 99, 123],
            observation=dict(kind="canonical_event", event="detector_crossing"),
            unexecuted_fate_label_field="terminal_reason")
        self.method = dict(schema_version=1, kind="time_peak", settings=None,
            time_reference=dict(clock_epoch_id="epoch", authority_sha256=self.clock.authority_sha256,
                                instrument_time_us=20.))

    def write(self, name, value):
        (self.root / name).write_text(json.dumps(value), encoding="utf-8")

    def opened(self):
        self.write("source_provenance.json", self.provenance)
        self.write("canonical_source_states.json", self.states)
        self.collection["source_provenance_record"] = file_record(self.root / "source_provenance.json")
        self.write("collection.json", self.collection)
        data = dict(collection=file_record(self.root / "collection.json"),
            source_provenance=file_record(self.root / "source_provenance.json"),
            canonical_source_states=file_record(self.root / "canonical_source_states.json"), **self.clock_records)
        manifest = dict(schema_version=2, role="simulation_run_manifest", status="failed",
            inputs={}, outputs=list(data.values()), products={"trajectory": dict(schema_version=1,
                kind="trajectory_result", status="complete", metadata=dict(backend="simion", clock={"clock_epoch_id": "epoch",
                "authority_sha256": self.clock.authority_sha256}, model_identity_sha256="B" * 64), data=data)})
        run = self.root / ("published_" + str(len(list(self.root.glob("published_*")))))
        run.mkdir()
        publish_terminal_state(run, {"status": "failed"}, manifest)
        return open_artifact(dict(manifest=file_record(run / "run_manifest.json"), product_id="trajectory"),
                             expected_kind="trajectory_result")

    def test_real_manifest_bound_data_no_tools_writes_or_producer_status_rewrite(self):
        source = self.opened()
        before = {path.name: path.read_bytes() for path in self.root.iterdir() if path.is_file()}
        with patch("subprocess.Popen", side_effect=AssertionError("tool")), \
             patch.object(Path, "write_text", side_effect=AssertionError("write")), \
             patch.object(Path, "mkdir", side_effect=AssertionError("mkdir")):
            result = analyze_published_trajectory(source, selection=self.selection, method=self.method)
        self.assertEqual(result["status"], "analysis_completed")
        self.assertAlmostEqual(result["peak_metrics"]["mean_tof_us"], 7 / 3)
        self.assertEqual(result["producer"]["status"], "failed")
        self.assertEqual(result["census"]["counts"], {"detector_crossing": 3, "unknown": 1})
        self.assertEqual(result["original_mother"]["mother_fates"], list(self.mother.fates))
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.root.iterdir() if path.is_file()})
        self.assertEqual(result["scientific_qualification"], "not_granted")

    def test_public_analyze_opens_exact_product_and_remains_read_only_without_tools(self):
        from msplatform import api
        source = self.opened()
        before = copy.deepcopy((self.selection, self.method))
        with patch("subprocess.Popen", side_effect=AssertionError("analysis started a tool")), \
             patch.object(Path, "write_text", side_effect=AssertionError("analysis wrote a file")), \
             patch.object(Path, "mkdir", side_effect=AssertionError("analysis created workspace")):
            direct = api.analyze(source, selection=self.selection, method=self.method)
            reopened = api.analyze(source.reference, selection=self.selection, method=self.method)
        self.assertEqual(direct, reopened)
        self.assertEqual(direct["status"], "analysis_completed")
        self.assertEqual(direct["producer"]["status"], "failed")
        self.assertEqual(direct["selected_particle_ids"], [7, 99, 123])
        self.assertEqual((self.selection, self.method), before)

    def test_opaque_fate_without_declared_field_is_insufficient_not_loss(self):
        self.selection["unexecuted_fate_label_field"] = None
        result = analyze_published_trajectory(self.opened(), selection=self.selection, method=self.method)
        self.assertEqual(result["status"], "insufficient_classification")
        self.assertEqual(result["unresolved_classification_particle_ids"], [201])
        self.assertIsNone(result["peak_metrics"])

    def test_zero_handoff_no_fly_complete_claim_and_original_fates(self):
        self.states = []
        _, self.provenance = project_source_states([], mother=self.mother, clock=self.clock,
            state_kind="time_snapshot", clock_records=self.clock_records)
        self.collection.update(native_complete=None, native_calls=0, execution_status="not_requested_zero_handoff",
                               canonical_events=[])
        self.collection["original_mother"] = {key: copy.deepcopy(self.provenance[key]) for key in self.collection["original_mother"]}
        self.selection["particle_ids"] = []
        result = analyze_published_trajectory(self.opened(), selection=self.selection, method=self.method)
        self.assertEqual(result["status"], "insufficient_observations")
        self.assertEqual(result["census"]["counts"], {"unknown": 4})

    def test_plane_occurrence_brackets_and_incomplete_are_retained(self):
        self.collection["plane_observations"] = dict(status="incomplete", incomplete=[{"reason": "declared_record_cap"}],
            unlocalized_boundary_returns=[], rows=[dict(particle_id=pid, instrument_time_us=t,
                observation_id="exit", direction="outward", occurrence=1, step_start_instrument_time_us=t-1,
                step_end_instrument_time_us=t+1) for pid, t in zip((7, 99, 123), (21., 22., 24.))])
        self.selection["observation"] = dict(kind="plane_observation", observation_id="exit", direction="outward", occurrence=2)
        result = analyze_published_trajectory(self.opened(), selection=self.selection, method=self.method)
        self.assertEqual(result["status"], "insufficient_observations")
        self.assertEqual(result["selection_evidence"], self.collection["plane_observations"])
        self.assertEqual(result["missing_observation_particle_ids"], [7, 99, 123])

    def test_bad_mother_clock_and_unknown_versions_fail_closed(self):
        for case in ("mother", "clock", "version"):
            with self.subTest(case=case):
                collection = copy.deepcopy(self.collection)
                selection = copy.deepcopy(self.selection)
                method = copy.deepcopy(self.method)
                if case == "mother": self.collection["original_mother"]["mother_records"].pop()
                elif case == "clock": method["time_reference"]["authority_sha256"] = "C" * 64
                else: selection["schema_version"] = 2
                with self.assertRaises(ValueError):
                    analyze_published_trajectory(self.opened(), selection=selection, method=method)
                self.collection = collection

    def test_opened_member_tampering_is_reverified_not_silently_reanalysed(self):
        source = self.opened()
        self.write("collection.json", {"tampered": True})
        with self.assertRaises((ValueError, AssertionError)):
            analyze_published_trajectory(source, selection=self.selection, method=self.method)
