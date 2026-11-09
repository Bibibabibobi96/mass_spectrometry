"""Published same-field event comparison uses genuine software manifests only."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common.contracts import test_simion_trajectory_analysis as analysis_fixtures
from msplatform.backends.simion.trajectory_comparison import compare_published_trajectories
from msplatform.results.artifacts import open_artifact
from msplatform.io.manifest_records import file_record
from msplatform.execution.terminal_publication import publish_terminal_state


class PublishedTrajectoryComparisonTests(unittest.TestCase):
    def setUp(self):
        self.fixtures = []
        for _ in range(2):
            fixture = analysis_fixtures.PublishedTrajectoryAnalysisTests()
            fixture.setUp()
            self.addCleanup(fixture.doCleanups)
            self.fixtures.append(fixture)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.field_manifest = Path(self.temp.name) / "field_manifest.json"
        self.field_manifest.write_text('{"role":"software_field_identity_fixture"}', encoding="utf-8")
        self.field = dict(manifest=file_record(self.field_manifest), product_id="fields")
        self.selection = copy.deepcopy(self.fixtures[0].selection)
        self.method = dict(schema_version=1, kind="event_time_position")

    def opened(self, fixture, *, field=None, changes=None):
        collection = copy.deepcopy(fixture.collection)
        provenance = copy.deepcopy(fixture.provenance)
        states = copy.deepcopy(fixture.states)
        for row in collection["canonical_events"]:
            row.update(x_mm=1., y_mm=2., z_mm=3.)
        if changes is not None:
            changes(collection, provenance, states)
        fixture.write("source_provenance.json", provenance)
        fixture.write("canonical_source_states.json", states)
        collection["source_provenance_record"] = file_record(fixture.root / "source_provenance.json")
        collection["field_reference"] = copy.deepcopy(field or self.field)
        fixture.write("field_reference.json", collection["field_reference"])
        fixture.write("collection.json", collection)
        data = {key: file_record(fixture.root / name) for key, name in
                [("collection", "collection.json"), ("source_provenance", "source_provenance.json"),
                 ("canonical_source_states", "canonical_source_states.json"), ("field_reference", "field_reference.json")]}
        data.update(fixture.clock_records)
        manifest = dict(schema_version=2, role="simulation_run_manifest", status="failed", inputs={},
            outputs=list(data.values()), products={"trajectory":dict(schema_version=1, kind="trajectory_result",
                status="complete", metadata=dict(backend="simion", clock=dict(clock_epoch_id="epoch",
                    authority_sha256=fixture.clock.authority_sha256), model_identity_sha256="B"*64), data=data)})
        run = fixture.root / ("compare_" + str(len(list(fixture.root.glob("compare_*")))))
        run.mkdir()
        publish_terminal_state(run,{"status":"failed"},manifest)
        return open_artifact(dict(manifest=file_record(run / "run_manifest.json"),product_id="trajectory"),
                             expected_kind="trajectory_result")

    def test_actual_manifest_differences_no_tools_writes_and_different_run_clock_paths(self):
        left = self.opened(self.fixtures[0])
        def change(collection, provenance, states):
            for row in collection["canonical_events"]:
                row["instrument_time_us"] += 2.
                row["x_mm"] += 3.
                row["y_mm"] += 4.
        right = self.opened(self.fixtures[1],changes=change)
        with patch("subprocess.Popen", side_effect=AssertionError("tool")), \
             patch.object(Path,"mkdir",side_effect=AssertionError("mkdir")), \
             patch.object(Path,"write_text",side_effect=AssertionError("write")):
            result = compare_published_trajectories(left,right,selection=self.selection,method=self.method)
        self.assertEqual(result["status"],"comparison_completed")
        self.assertEqual(result["matched_particle_ids"],[7,99,123])
        for pair in result["pairs"]:
            self.assertEqual(pair["right_minus_left"]["instrument_time_us"],2.)
            self.assertEqual(pair["right_minus_left"]["position_components_mm"],[3.,4.,0.])
            self.assertEqual(pair["right_minus_left"]["position_norm_mm"],5.)
        self.assertEqual(result["producers"]["left"]["status"],"failed")
        self.assertEqual(result["coverage"]["left"]["denominator_count"],4)
        self.assertIn("velocity",result["unavailable_quantities"])
        self.assertEqual(result["scientific_qualification"],"not_granted")

    def test_missing_selected_event_is_retained_and_never_terminal_state_substitution(self):
        left = self.opened(self.fixtures[0])
        def change(collection, provenance, states):
            collection["canonical_events"].pop()
        right = self.opened(self.fixtures[1],changes=change)
        result = compare_published_trajectories(left,right,selection=self.selection,method=self.method)
        self.assertEqual(result["status"],"insufficient_observations")
        self.assertEqual(result["missing_observation_particle_ids"]["right"],[123])
        self.assertEqual(result["coverage"]["right"]["denominator_count"],4)

    def test_different_field_model_frame_or_mother_lineage_reject(self):
        left = self.opened(self.fixtures[0])
        for case in ("field", "model", "clock", "frame", "lineage"):
            with self.subTest(case=case):
                field = None
                if case == "field":
                    path = Path(self.temp.name) / "other_field.json"
                    path.write_text('{"different":true}',encoding="utf-8")
                    field = dict(manifest=file_record(path),product_id="fields")
                def change(collection, provenance, states):
                    if case == "model":collection["model_identity_sha256"]="C"*64
                    elif case == "clock":provenance["clock_authority_sha256"]="C"*64
                    elif case == "frame":
                        for row in states:row["frame_id"]="other_world"
                        provenance["target_frame_id"]="other_world"
                    elif case == "lineage":
                        for row in provenance["mother_records"]:row["generation"]=1
                        collection["original_mother"]["mother_records"]=copy.deepcopy(provenance["mother_records"])
                right = self.opened(self.fixtures[1],field=field,changes=change)
                with self.assertRaises(ValueError):
                    compare_published_trajectories(left,right,selection=self.selection,method=self.method)

    def test_opaque_unclassified_and_zero_execution_remain_unavailable(self):
        left = self.opened(self.fixtures[0])
        selection = dict(self.selection,unexecuted_fate_label_field=None)
        result = compare_published_trajectories(left,left,selection=selection,method=self.method)
        self.assertEqual(result["status"],"insufficient_classification")
        def zero(collection, provenance, states):
            states.clear();provenance.update(execution_particle_ids=[],particle_count=0,target_frame_id=None)
            collection.update(native_complete=None,native_calls=0,execution_status="not_requested_zero_handoff",canonical_events=[])
        right = self.opened(self.fixtures[1],changes=zero)
        result = compare_published_trajectories(left,right,selection=self.selection,method=self.method)
        self.assertEqual(result["status"],"insufficient_observations")
        self.assertEqual(result["pairs"],[])
        self.assertEqual(result["coverage"]["right"]["denominator_count"],4)

    def test_plane_identity_duplicate_and_unknown_contract_reject(self):
        left = self.opened(self.fixtures[0])
        for case in ("plane", "duplicate"):
            def change(collection, provenance, states):
                if case == "plane":collection["canonical_events"][0]["observation_id"]="exit"
                else:collection["canonical_events"].append(copy.deepcopy(collection["canonical_events"][0]))
            right = self.opened(self.fixtures[1],changes=change)
            with self.subTest(case=case),self.assertRaises(ValueError):
                compare_published_trajectories(left,right,selection=self.selection,method=self.method)
        with self.assertRaises(ValueError):
            compare_published_trajectories(left,left,selection=self.selection,method=dict(schema_version=2,kind="event_time_position"))
