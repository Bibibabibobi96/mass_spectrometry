"""Managed MP/IP preparation keeps the actual owner and source protection."""
import dataclasses
import json
from pathlib import Path
import unittest

from common.contracts import test_execution_runtime as owners
from integrations.tests import test_multipole_ip_prepare as fixtures
from msplatform.io.manifest_records import file_record
from msplatform.workflows.multipole_ip.prepare import prepare_managed


class ManagedMultipoleIPTests(unittest.TestCase):
    def test_failed_receiver_is_published_failed_without_changing_original_sources(self):
        fixture, context, root = self._fixture()
        manifest_path = fixture.receiver / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = "failed"
        fixtures.write_json(manifest_path, manifest)
        fixture.request["receiver"]["manifest"] = file_record(manifest_path)
        fixtures.write_json(fixture.request_path, fixture.request)
        before = {path: file_record(path) for run in (fixture.source, fixture.receiver)
                  for path in run.rglob("*") if path.is_file()}
        run_id = "20261109_120001__analysis__python__mpip-managed-failed"
        with self.assertRaisesRegex(ValueError, "receiver geometry"):
            prepare_managed(fixture.request_path, context=context, run_id=run_id)
        run = root / "projects/instrument_assembly/runs" / run_id
        published = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(published["status"], "failed")
        self.assertFalse((run / "results/multipole_ip/ip_injected_source.json").exists())
        for path, record in before.items():
            self.assertEqual(file_record(path), record)

    def _fixture(self):
        fixture = fixtures.MultipoleIPPreparationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        helper = owners.NormalOwnerTests()
        context = helper._context(fixture.root)
        policy = fixture.root / "capacity.json"
        fixtures.write_json(policy, helper._policy())
        stage_policy = fixture.root / "stages.json"
        fixtures.write_json(stage_policy, dict(schema_version=1, role="execution_stage_policy", stages={
            "prepare_multipole_ip": dict(limits=dict(wall_clock_seconds=600,
                transient_run_directory_bytes=16777216, process_tree_working_set_bytes=1073741824,
                minimum_system_available_memory_bytes=1048576, compact_final_retained_bytes=16777216,
                automatic_retry_count=0), artifact_retention={"policy_version": 1, "class": "compact", "reason": None})}))
        context = dataclasses.replace(context, capacity_policy_path=policy, stage_policy_path=stage_policy)
        root = context.workspace / "artifacts"
        for name, project, run_id in (("source", "rf_multipole_ion_optics", "source_run"),
                                     ("receiver", "dual_pressure_rectilinear_ion_processor", "receiver_run")):
            old = getattr(fixture, name)
            target = root / "projects" / project / "runs" / run_id
            target.parent.mkdir(parents=True)
            old.rename(target)
            setattr(fixture, name, target)
            selection = fixture.publish_manifest(target, project, run_id)
            config_path = target / "run_config.json"
            config = json.loads(config_path.read_text())
            config["mode"] = "fixture"
            fixtures.write_json(config_path, config)
            manifest_path = target / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest.update(role="simulation_run_manifest", mode="fixture", run_config=file_record(config_path))
            fixtures.write_json(manifest_path, manifest)
            selection["manifest"] = file_record(manifest_path)
            if name == "source":
                selection["case_id"] = "rf_on"
            fixture.request[name] = selection
        from msplatform.execution.capacity_ledger import initialize_capacity_ledger
        initialize_capacity_ledger(root, objects=[dict(path=str(run.relative_to(root)),
            **{"class": "light_evidence"}, bytes=sum(p.stat().st_size for p in run.rglob("*") if p.is_file()),
            status="ready", owner="explicit legacy fixture") for run in (fixture.source, fixture.receiver)])
        fixtures.write_json(fixture.request_path, fixture.request)
        return fixture, context, root

    def test_managed_preparation_publishes_real_states_and_preserves_sources(self):
        fixture, context, root = self._fixture()
        before = {path: file_record(path) for run in (fixture.source, fixture.receiver)
                  for path in run.rglob("*") if path.is_file()}
        result = prepare_managed(fixture.request_path, context=context,
            run_id="20261109_120000__analysis__python__mpip-managed")
        self.assertEqual(result["status"], "success")
        run = Path(result["manifest"]["path"]).parent
        receipt = json.loads((run / "results/multipole_ip/preparation_receipt.json").read_text())
        self.assertEqual((receipt["mother_count"], receipt["exit_count"]), (2, 1))
        self.assertEqual(receipt["execution_scope"], "prepare_only_no_solver")
        for path, record in before.items():
            self.assertEqual(file_record(path), record)
        states = (run / "results/multipole_ip/source_states.csv").read_text()
        self.assertIn("particle_birth_time_us", states)
        self.assertTrue((run / "inputs/parent_composition_plan.json").is_file())
