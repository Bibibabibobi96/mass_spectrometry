"""Regression tests for the device-neutral SIMION PA-family cache."""
from __future__ import annotations

import json
import hashlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import common.simion.cache_generation as cache_generation
import common.simion.pa_family_cache as pa_family_cache
import common.simion.standalone_pa_response_set as response_set
from common.contracts import capacity_ledger, capacity_protection, reconcile_artifact_capacity

from common.simion.pa_family_cache import (
    CacheDisposition,
    PAFamilyCacheError,
    advance_pa_family_cache_transaction,
    canonical_pa_family_cache_key,
    ensure_pa_family_cache,
    materialize_pa_family_cache,
    migrate_current_pa_family_cache,
    main,
    pa_family_inventory,
    probe_pa_family_cache,
    publish_pa_family_cache,
    repair_pa_family_cache_generation,
    approve_pa_family_cache_retirement,
    release_pa_family_cache_retirement_pin,
    rollback_pa_family_cache_publication,
    validate_pa_family_cache_generation,
    validate_pa_family_cache_subset,
    validate_pa_family_cache_subset_with_repair,
)


def identity() -> dict[str, object]:
    return {
        "geometry": {"resolved_sha256": "A" * 64},
        "gem": {"sha256": "B" * 64},
        "basis_namespace": {"ids": [0, 1, 2]},
        "mesh": {"mm_per_gu": [1, 1, 1]},
        "grid_phase": {"origin_mm": [0, 0, 0]},
        "surface": "none",
        "simion_identity": {"release": "2020"},
        "refine_policy": {"iterations": 1000},
        "builder_identity": {"sha256": "C" * 64},
    }


def working_field_identity() -> dict[str, object]:
    """Small numerical fixture, independent of any instrument electrode layout."""
    result = identity()
    del result["basis_namespace"]
    del result["refine_policy"]
    result.update(
        boundary_policy="native_zero_neumann",
        rf_reference_voltage_v=10000.0,
        working_points=[
            {"kind": kind, "electrode_voltages_v": voltages, "refine_convergence_v": 0.001}
            for kind, voltages in (
                ("carrier_off", {"1": 3.0, "2": 3.0}),
                ("rf_reference", {"1": 10000.0, "2": -10000.0}),
                ("pulse_delta", {"1": 0.0, "2": 1500.0}),
            )
        ],
    )
    return result


class PAFamilyCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "field.pa#").write_bytes(b"raw")
        (self.source / "field.pa0").write_bytes(b"zero")
        (self.source / "field.pa1").write_bytes(b"one")
        self.names = ("field.pa#", "field.pa0", "field.pa1")
        self.cache = self.root / "cache"
        self.artifact_owner = "pa-family-cache-test"
        self.producer_run_config = self.root / "run_config.json"
        self.producer_run_config.write_text(
            json.dumps({"run_id": "fixture-pa-producer", "project": "fixture"}),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _response_receipt_fixture(self, *, scratch_sources=False, producer_run_config=None):
        exporter = self.root / "export.lua"
        exporter.write_text("-- fixture exporter", encoding="utf-8")
        names = (("field.response1.pa", "responses.json") if scratch_sources else
                 ("field.pa#", "field.pa1", "field.response1.pa", "responses.json"))
        spec = {
            "schema_version": 2, "source_location": "build_scratch" if scratch_sources else "payload",
            "receipt_name": "responses.json", "exporter_path": str(exporter),
            "exports": [{"response_id": 1, "source_name": "field.pa1", "standalone_name": "field.response1.pa"}],
        }
        first = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner,
            response_receipt=spec, producer_run_config=producer_run_config)
        self.assertEqual(set(first.missing_files), (set(names) - {"responses.json"}) | ({"field.pa1"} if scratch_sources else set()))
        for name in first.missing_files:
            if name in names:
                (first.build_directory / name).write_bytes(name.encode("ascii"))
        if scratch_sources:
            (first.scratch_directory / "field.pa1").write_bytes(b"native-source")
            (first.scratch_directory / "field.pa#").write_bytes(b"raw-build-only")
            (first.scratch_directory / "field.pa0").write_bytes(b"controller-build-only")
        return first, names, spec

    def _empty_failed_transaction(self, *, prepared=False):
        artifacts, cache = self._artifact_cache()
        first = advance_pa_family_cache_transaction(
            cache, identity(), self.names, owner=self.artifact_owner,
            producer_run_config=self.producer_run_config,
        )
        self._land_transaction_members(first, self.names)
        sealed = advance_pa_family_cache_transaction(cache, identity(), self.names, owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        path = first.transaction_directory / "transaction.json"
        document = json.loads(path.read_text())
        if prepared:
            document["verification"] = self._verification_evidence(sealed)
            document["status"] = "prepared"
        document["last_error"] = "fixture publication failure"
        pa_family_cache._write_transaction(path, document)
        for item in first.build_directory.iterdir():
            item.chmod(stat.S_IWRITE)
            item.unlink()
        # The old ledger deliberately still claims the former payload bytes.
        producer = self.root / "producer"
        producer.mkdir()
        summary = producer / "summary.json"
        summary.write_text(json.dumps({"status": "failed", "reason": first.cache_key}))
        outputs = [{"path": str(summary), "bytes": summary.stat().st_size,
                    "sha256": pa_family_cache.file_sha256(summary)}]
        if prepared:
            record = document["verification"]
            output = Path(record["verification_output_path"])
            outputs.append({"path": str(output), "bytes": output.stat().st_size,
                            "sha256": record["verification_output_sha256"]})
            summary.write_text(json.dumps({"status": "failed", "reason": "other key"}))
            outputs[0].update(bytes=summary.stat().st_size, sha256=pa_family_cache.file_sha256(summary))
        manifest = producer / "run_manifest.json"
        manifest.write_text(json.dumps({"role": "simulation_run_manifest", "status": "failed", "outputs": outputs}))
        request = {"schema_version": 1, "cache_key": first.cache_key, "owner": document["owner"],
                   "transaction_sha256": pa_family_cache.file_sha256(path),
                   "inventory_sha256": document["inventory_sha256"],
                   "failed_producer_manifest_path": str(manifest),
                   "failed_producer_manifest_sha256": pa_family_cache.file_sha256(manifest),
                   "reason": "payload_absent_failed_transaction_abandoned"}
        return artifacts, cache, first, document, request

    def test_abandon_empty_transaction_preserves_failure_and_reconciles_without_deletion(self):
        for prepared in (False, True):
            with self.subTest(prepared=prepared), tempfile.TemporaryDirectory() as temporary:
                old_root = self.root
                self.root = Path(temporary)
                artifacts, cache, first, prior, request = self._empty_failed_transaction(prepared=prepared)
                result = advance_pa_family_cache_transaction(cache, identity(), self.names, abandon_empty_transaction=request)
                self.assertEqual(result.status, "retired")
                path = first.transaction_directory / "transaction.json"
                retained = json.loads(path.read_text())
                self.assertEqual(retained["verification"], prior["verification"])
                self.assertEqual(retained["last_error"], prior["last_error"])
                self.assertEqual(retained["abandonment"]["prior_transaction"], prior)
                self.assertEqual(retained["abandonment"]["physical_bytes_removed"], 0)
                entry = self._ledger_entry(artifacts, first.cache_key)
                self.assertEqual((entry["class"], entry["bytes"]), ("light_evidence", path.stat().st_size))
                before = path.read_bytes()
                advance_pa_family_cache_transaction(cache, identity(), self.names, abandon_empty_transaction=request)
                self.assertEqual(before, path.read_bytes())
                with self.assertRaisesRegex(PAFamilyCacheError, "retained failure evidence"):
                    advance_pa_family_cache_transaction(cache, identity(), self.names, owner=self.artifact_owner, producer_run_config=self.producer_run_config)
                self.root = old_root

    def test_abandon_empty_transaction_replays_owner_commit_after_ledger_failure(self):
        artifacts, cache, first, _, request = self._empty_failed_transaction(prepared=True)
        with patch.object(capacity_ledger, "write_json_atomic", side_effect=OSError("fixture ledger interruption")):
            with self.assertRaisesRegex(OSError, "interruption"):
                advance_pa_family_cache_transaction(cache, identity(), self.names, abandon_empty_transaction=request)
        self.assertEqual(json.loads((first.transaction_directory / "transaction.json").read_text())["status"], "retired")
        self.assertEqual(self._ledger_entry(artifacts, first.cache_key)["status"], "writing")
        advance_pa_family_cache_transaction(cache, identity(), self.names, abandon_empty_transaction=request)
        self.assertEqual(self._ledger_entry(artifacts, first.cache_key)["class"], "light_evidence")

    def test_abandon_empty_transaction_rejects_payload_owner_drift_and_live_protection(self):
        artifacts, cache, first, _, request = self._empty_failed_transaction()
        path = first.transaction_directory / "transaction.json"
        original = path.read_bytes()
        for field, value in (("owner", "another-owner"), ("inventory_sha256", "0" * 64),
                             ("transaction_sha256", "0" * 64)):
            with self.subTest(field=field), self.assertRaises(PAFamilyCacheError):
                advance_pa_family_cache_transaction(cache, identity(), self.names, abandon_empty_transaction={**request, field: value})
        unexpected = first.build_directory / "unexpected.pa"
        unexpected.write_bytes(b"preserve")
        with self.assertRaisesRegex(PAFamilyCacheError, "empty payload"):
            advance_pa_family_cache_transaction(cache, identity(), self.names, abandon_empty_transaction=request)
        self.assertEqual(unexpected.read_bytes(), b"preserve")
        unexpected.unlink()
        capacity_protection.create_capacity_protection_lease(
            artifacts, lease_id="active-consumer", owner="fixture", ttl_seconds=600,
            protected_cache_keys=[first.cache_key],
        )
        with self.assertRaisesRegex(ValueError, "active capacity protection lease"):
            advance_pa_family_cache_transaction(cache, identity(), self.names, abandon_empty_transaction=request)
        self.assertEqual(original, path.read_bytes())

    def test_abandon_empty_transaction_rejects_pin_consumer_publication_and_failed_producer_drift(self):
        artifacts, cache, first, _, request = self._empty_failed_transaction()
        path = first.transaction_directory / "transaction.json"
        original = path.read_bytes()
        entry = self._ledger_entry(artifacts, first.cache_key)
        capacity_ledger.record_capacity_object(
            artifacts, path=first.transaction_directory, object_class="rebuildable_payload", bytes_count=entry["bytes"],
            status="writing", owner=entry["owner"], recovery_reason=entry["recovery_reason"],
            review_deadline=entry["review_deadline"], pin=True, pin_reason="fixture pin",
        )
        with self.assertRaisesRegex(ValueError, "unpinned"):
            advance_pa_family_cache_transaction(cache, identity(), self.names, abandon_empty_transaction=request)
        capacity_ledger.record_capacity_object(
            artifacts, path=first.transaction_directory, object_class="rebuildable_payload", bytes_count=entry["bytes"],
            status="writing", owner=entry["owner"], recovery_reason=entry["recovery_reason"],
            review_deadline=entry["review_deadline"],
        )
        consumer = artifacts / "another-run"
        consumer.mkdir()
        capacity_ledger.record_capacity_object(
            artifacts, path=consumer, object_class="rebuildable_payload", bytes_count=0,
            status="writing", owner="another", recovery_reason="uses PA", review_deadline="2026-09-27",
            consumers=[first.transaction_directory],
        )
        with self.assertRaisesRegex(ValueError, "referenced"):
            advance_pa_family_cache_transaction(cache, identity(), self.names, abandon_empty_transaction=request)
        capacity_ledger.record_capacity_object(artifacts, path=consumer, object_class="light_evidence", bytes_count=0, status="ready", owner="another")
        (cache / first.cache_key).mkdir()
        with self.assertRaisesRegex(PAFamilyCacheError, "publication root"):
            advance_pa_family_cache_transaction(cache, identity(), self.names, abandon_empty_transaction=request)
        (cache / first.cache_key).rmdir()
        manifest = Path(request["failed_producer_manifest_path"])
        manifest.write_text("{}")
        with self.assertRaisesRegex(PAFamilyCacheError, "manifest identity"):
            advance_pa_family_cache_transaction(cache, identity(), self.names, abandon_empty_transaction=request)
        self.assertEqual(original, path.read_bytes())

    def test_abandon_empty_transaction_cli_uses_existing_advance(self):
        _, cache, _, _, request = self._empty_failed_transaction()
        identity_path = self.root / "identity.json"
        identity_path.write_text(json.dumps(identity()))
        request_path = self.root / "abandon.json"
        request_path.write_text(json.dumps(request))
        output = StringIO()
        with redirect_stdout(output):
            main(["--action", "advance-transaction", "--cache-root", str(cache),
                  "--identity", str(identity_path), "--filenames", ",".join(self.names),
                  "--abandon-empty-transaction", str(request_path)])
        self.assertEqual(json.loads(output.getvalue())["status"], "retired")

    def test_cancel_unpublished_transaction_removes_only_staged_payload_and_replays(self):
        artifacts, cache = self._artifact_cache()
        first = advance_pa_family_cache_transaction(
            cache, identity(), self.names, owner=self.artifact_owner,
            producer_run_config=self.producer_run_config,
        )
        payload = first.build_directory / "field.pa0"
        payload.write_bytes(b"unpublished-payload")
        transaction_path = first.transaction_directory / "transaction.json"
        document = json.loads(transaction_path.read_text())
        request = {
            "schema_version": 2, "cache_key": first.cache_key, "owner": document["owner"],
            "transaction_sha256": pa_family_cache.file_sha256(transaction_path),
            "inventory_sha256": document["inventory_sha256"],
            "reason": "explicit_user_cancelled_unpublished_transaction",
        }
        result = advance_pa_family_cache_transaction(
            cache, identity(), self.names, cancel_unpublished_transaction=request,
        )
        self.assertEqual(result.status, "retired")
        self.assertFalse(payload.exists())
        retained = json.loads(transaction_path.read_text())
        self.assertEqual(retained["abandonment"]["producer_evidence"], "missing")
        self.assertEqual(retained["abandonment"]["physical_bytes_removed"], len(b"unpublished-payload"))
        self.assertEqual(retained["abandonment"]["status"], "complete")
        self.assertEqual(self._ledger_entry(artifacts, first.cache_key)["class"], "light_evidence")
        before = transaction_path.read_bytes()
        advance_pa_family_cache_transaction(cache, identity(), self.names, cancel_unpublished_transaction=request)
        self.assertEqual(before, transaction_path.read_bytes())

    def test_cancel_unpublished_transaction_rejects_protected_or_unapproved_content(self):
        artifacts, cache = self._artifact_cache()
        first = advance_pa_family_cache_transaction(
            cache, identity(), self.names, owner=self.artifact_owner,
            producer_run_config=self.producer_run_config,
        )
        payload = first.build_directory / "field.pa0"
        payload.write_bytes(b"unpublished-payload")
        transaction_path = first.transaction_directory / "transaction.json"
        document = json.loads(transaction_path.read_text())
        request = {
            "schema_version": 2, "cache_key": first.cache_key, "owner": document["owner"],
            "transaction_sha256": pa_family_cache.file_sha256(transaction_path),
            "inventory_sha256": document["inventory_sha256"],
            "reason": "explicit_user_cancelled_unpublished_transaction",
        }
        capacity_protection.create_capacity_protection_lease(
            artifacts, lease_id="cancel-protected", owner="fixture", ttl_seconds=600,
            protected_cache_keys=[first.cache_key],
        )
        with self.assertRaisesRegex(ValueError, "active capacity protection lease"):
            advance_pa_family_cache_transaction(cache, identity(), self.names, cancel_unpublished_transaction=request)
        self.assertTrue(payload.exists())

    def test_scratch_sources_are_recorded_once_then_retired_from_new_generation(self):
        first, names, spec = self._response_receipt_fixture(scratch_sources=True)
        source = first.scratch_directory / "field.pa1"
        source_sha = pa_family_cache.file_sha256(source)
        with patch.object(cache_generation, "file_sha256", wraps=cache_generation.file_sha256) as hashed:
            sealed = advance_pa_family_cache_transaction(
                self.cache, identity(), names, owner=self.artifact_owner, response_receipt=spec)
        self.assertCountEqual([Path(call.args[0]).name for call in hashed.call_args_list],
                              [*names, "field.pa1"])
        receipt = json.loads((first.build_directory / "responses.json").read_text())
        self.assertEqual(receipt["schema_version"], 2)
        self.assertEqual(receipt["responses"][0]["source"]["sha256"], source_sha)
        self.assertTrue(first.scratch_directory.exists())
        with patch.object(cache_generation, "file_sha256", side_effect=AssertionError("repeated PA scan")):
            replay = advance_pa_family_cache_transaction(self.cache, identity(), names,
                owner=self.artifact_owner, response_receipt=spec)
        self.assertEqual(replay.inventory_sha256, sealed.inventory_sha256)
        published = advance_pa_family_cache_transaction(self.cache, identity(), names,
            response_receipt=spec, verification_evidence=self._verification_evidence(sealed), recovery_policy="none")
        self.assertFalse(first.scratch_directory.exists())
        self.assertEqual({path.name for path in published.generation_directory.iterdir() if path.suffix != ".json"},
                         {"field.response1.pa"})
        manifest = json.loads((published.generation_directory / "cache_manifest.json").read_text())
        self.assertEqual({row["name"] for row in manifest["files"]}, set(names))
        selected = response_set.select_standalone_pa_records(published.generation_directory, manifest, "responses.json")
        self.assertEqual([row.name for row in selected], ["field.response1.pa"])

    def test_missing_scratch_source_keeps_build_and_avoids_premature_identity_reads(self):
        first, names, spec = self._response_receipt_fixture(scratch_sources=True)
        (first.scratch_directory / "field.pa1").unlink()
        with patch.object(cache_generation, "file_sha256", side_effect=AssertionError("premature PA scan")):
            waiting = advance_pa_family_cache_transaction(self.cache, identity(), names,
                owner=self.artifact_owner, response_receipt=spec)
        self.assertEqual(waiting.missing_files, ("field.pa1",))
        self.assertTrue((first.scratch_directory / "field.pa#").is_file())
        self.assertFalse((first.build_directory / "responses.json").exists())

    def test_interrupted_scratch_receipt_keeps_sources_until_inventory_is_saved(self):
        first, names, spec = self._response_receipt_fixture(scratch_sources=True)
        writer = pa_family_cache.write_standalone_pa_response_set
        def interrupted(*args, **kwargs):
            writer(*args, **kwargs)
            raise OSError("interrupted receipt")
        with patch.object(pa_family_cache, "write_standalone_pa_response_set", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "interrupted receipt"):
                advance_pa_family_cache_transaction(self.cache, identity(), names,
                    owner=self.artifact_owner, response_receipt=spec)
        self.assertTrue((first.scratch_directory / "field.pa1").is_file())
        document = json.loads((first.transaction_directory / "transaction.json").read_text())
        self.assertEqual(document["files"], [])
        sealed = advance_pa_family_cache_transaction(self.cache, identity(), names,
            owner=self.artifact_owner, response_receipt=spec)
        self.assertEqual(sealed.action_required, "verify")
        self.assertTrue(first.scratch_directory.exists())

    def test_cleanup_interruption_reuses_saved_inventory_without_source_reads(self):
        first, names, spec = self._response_receipt_fixture(scratch_sources=True)
        sealed = advance_pa_family_cache_transaction(self.cache, identity(), names,
            owner=self.artifact_owner, response_receipt=spec)
        evidence = self._verification_evidence(sealed)
        with patch.object(pa_family_cache, "_remove_tree_writable", side_effect=OSError("cleanup interrupted")):
            with self.assertRaisesRegex(OSError, "cleanup interrupted"):
                advance_pa_family_cache_transaction(self.cache, identity(), names,
                    owner=self.artifact_owner, verification_evidence=evidence)
        self.assertTrue(first.scratch_directory.exists())
        document = json.loads((first.transaction_directory / "transaction.json").read_text())
        self.assertEqual({row["name"] for row in document["files"]}, set(names))
        self.assertEqual(document["status"], "prepared")
        self.assertEqual(document["verification"], evidence)
        with patch.object(cache_generation, "file_sha256", side_effect=AssertionError("repeated PA scan")):
            published = advance_pa_family_cache_transaction(self.cache, identity(), names,
                owner=self.artifact_owner, recovery_policy="none")
        self.assertEqual(published.action_required, "complete")
        self.assertFalse(first.scratch_directory.exists())

    def test_response_receipt_seal_hashes_data_once_and_replays_without_data_reads(self):
        first, names, spec = self._response_receipt_fixture()
        with (patch.object(cache_generation, "file_sha256", wraps=cache_generation.file_sha256) as hashed,
              patch.object(response_set, "file_sha256", wraps=response_set.file_sha256) as receipt_hashed):
            sealed = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, response_receipt=spec)
        self.assertEqual(sealed.action_required, "verify")
        calls = [Path(call.args[0]).name for call in hashed.call_args_list]
        self.assertCountEqual(calls, names)
        self.assertEqual([Path(call.args[0]).name for call in receipt_hashed.call_args_list], ["export.lua"])
        document = json.loads((first.transaction_directory / "transaction.json").read_text())
        indexed = {item["name"]: item for item in document["files"]}
        receipt = json.loads((first.build_directory / "responses.json").read_text())
        self.assertEqual(receipt["responses"][0]["source"], indexed["field.pa1"])
        self.assertEqual(receipt["responses"][0]["standalone"], indexed["field.response1.pa"])
        with patch.object(cache_generation, "file_sha256", side_effect=AssertionError("repeated PA scan")):
            replay = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, response_receipt=spec)
            self.assertEqual(replay.inventory_sha256, sealed.inventory_sha256)
            # A saved recipe is also resumed by ordinary advance.
            replay = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, producer_run_config=self.producer_run_config)
            self.assertEqual(replay.inventory_sha256, sealed.inventory_sha256)

    def test_response_receipt_waits_for_data_without_hashing_or_writing_receipt(self):
        first, names, spec = self._response_receipt_fixture()
        (first.build_directory / "field.pa1").unlink()
        with patch.object(cache_generation, "file_sha256", side_effect=AssertionError("premature PA scan")):
            waiting = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, response_receipt=spec)
        self.assertEqual(waiting.missing_files, ("field.pa1",))
        self.assertFalse((first.build_directory / "responses.json").exists())

    def test_response_receipt_failure_is_unsealed_and_replays_owner_receipt(self):
        first, names, spec = self._response_receipt_fixture()
        real_writer = pa_family_cache.write_standalone_pa_response_set

        def interrupted(*args, **kwargs):
            real_writer(*args, **kwargs)
            raise OSError("interrupted after receipt write")

        with patch.object(pa_family_cache, "write_standalone_pa_response_set", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "interrupted"):
                advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, response_receipt=spec)
        document = json.loads((first.transaction_directory / "transaction.json").read_text())
        self.assertEqual(document["files"], [])
        self.assertEqual(document["status"], "building")
        self.assertIsNone(document["verification"])
        self.assertFalse((self.cache / first.cache_key / "current_generation.json").exists())
        sealed = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, response_receipt=spec)
        self.assertEqual(sealed.action_required, "verify")
        published = advance_pa_family_cache_transaction(
            self.cache, identity(), names, response_receipt=spec,
            verification_evidence=self._verification_evidence(sealed), recovery_policy="none",
        )
        self.assertEqual(published.status, "published")

    def test_response_receipt_rejects_changed_recipe_and_external_pa_hashes(self):
        first, names, spec = self._response_receipt_fixture()
        changed = dict(spec, exporter_path=str(self.root / "other.lua"))
        with self.assertRaisesRegex(PAFamilyCacheError, "recipe differs"):
            advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, response_receipt=changed)
        with self.assertRaisesRegex(PAFamilyCacheError, "specification fields"):
            advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, response_receipt=dict(spec, files=[]))
        with self.assertRaisesRegex(PAFamilyCacheError, "exports are invalid"):
            malformed = dict(spec, exports=[dict(spec["exports"][0], sha256="A" * 64)])
            advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, response_receipt=malformed)
        self.assertFalse((first.build_directory / "responses.json").exists())

    def test_response_receipt_rejects_old_recipe_and_wrong_source_location(self):
        _, names, spec = self._response_receipt_fixture()
        for changed in (dict(spec, schema_version=1), dict(spec, source_location="scratch")):
            with self.subTest(changed=changed), self.assertRaisesRegex(PAFamilyCacheError, "specification fields"):
                advance_pa_family_cache_transaction(self.cache, identity(), names,
                    owner=self.artifact_owner, response_receipt=changed)
        with self.assertRaisesRegex(PAFamilyCacheError, "outside the family"):
            advance_pa_family_cache_transaction(self.cache, identity(), names,
                owner=self.artifact_owner, response_receipt=dict(spec, source_location="build_scratch"))

    def test_v1_published_recipe_supports_public_pin_and_selector_without_rewriting(self):
        _, self.cache = self._artifact_cache()
        first, names, spec = self._response_receipt_fixture(producer_run_config=self.producer_run_config)
        writer = pa_family_cache.write_standalone_pa_response_set

        def legacy_receipt(*args, **kwargs):
            receipt = writer(*args, **kwargs)
            receipt["schema_version"] = 1
            Path(args[3]).write_text(json.dumps(receipt), encoding="utf-8")
            return receipt

        # Construct a historical payload with the original v1 byte semantics.
        with patch.object(pa_family_cache, "write_standalone_pa_response_set", side_effect=legacy_receipt):
            sealed = advance_pa_family_cache_transaction(self.cache, identity(), names,
                owner=self.artifact_owner, response_receipt=spec)
        published = advance_pa_family_cache_transaction(self.cache, identity(), names,
            owner=self.artifact_owner, verification_evidence=self._verification_evidence(sealed))
        advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner,
            published_pin_reason="fixture retained v1 bank", published_pin_generation_sha256=published.generation_sha256)
        transaction_path = first.transaction_directory / "transaction.json"
        document = json.loads(transaction_path.read_text())
        document["response_receipt"] = dict(spec, schema_version=1)
        del document["response_receipt"]["source_location"]
        pa_family_cache._write_transaction(transaction_path, document)
        paths = [transaction_path, *(published.generation_directory / name for name in (*names, "cache_manifest.json"))]
        before = {path: path.read_bytes() for path in paths}
        manifest = validate_pa_family_cache_generation(published.generation_directory,
            expected_cache_key=published.cache_key, expected_filenames=names,
            verify_payload=False, require_publication_pin=True)
        selected = response_set.select_standalone_pa_records(published.generation_directory,
            manifest, "responses.json", expected_response_ids=(1,))
        self.assertEqual([record.response_id for record in selected], [1])
        self.assertEqual(before, {path: path.read_bytes() for path in paths})

    def test_v1_unsealed_recipe_resumes_original_owner_and_writes_v2_receipt(self):
        _, self.cache = self._artifact_cache()
        first, names, spec = self._response_receipt_fixture(producer_run_config=self.producer_run_config)
        path = first.transaction_directory / "transaction.json"
        document = json.loads(path.read_text())
        legacy_spec = dict(spec, schema_version=1)
        del legacy_spec["source_location"]
        document["response_receipt"] = legacy_spec
        pa_family_cache._write_transaction(path, document)
        missing = first.build_directory / "field.pa1"
        missing.unlink()
        before = path.read_bytes()
        with self.assertRaises(PAFamilyCacheError):
            advance_pa_family_cache_transaction(self.cache, identity(), names, owner="not-the-producer")
        self.assertEqual(path.read_bytes(), before)
        waiting = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner)
        self.assertEqual(waiting.action_required, "build")
        self.assertEqual(waiting.missing_files, ("field.pa1",))
        missing.write_bytes(b"native rebuilt by original owner")
        sealed = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner)
        self.assertEqual(sealed.action_required, "verify")
        self.assertEqual(json.loads((first.build_directory / "responses.json").read_text())["schema_version"], 2)
        published = advance_pa_family_cache_transaction(self.cache, identity(), names,
            owner=self.artifact_owner, verification_evidence=self._verification_evidence(sealed))
        self.assertEqual(published.status, "published")
        self.assertEqual(json.loads(path.read_text())["response_receipt"], legacy_spec)
        self.assertEqual(json.loads((published.generation_directory / "responses.json").read_text())["schema_version"], 2)

    def test_saved_recipe_v1_is_strict_and_new_recipe_requires_v2(self):
        first, names, spec = self._response_receipt_fixture()
        path = first.transaction_directory / "transaction.json"
        document = json.loads(path.read_text())
        legacy_spec = dict(spec, schema_version=1)
        del legacy_spec["source_location"]
        with self.assertRaisesRegex(PAFamilyCacheError, "require schema_version 2"):
            advance_pa_family_cache_transaction(self.root / "new-cache", identity(), names,
                owner=self.artifact_owner, response_receipt=legacy_spec)
        self.assertFalse((self.root / "new-cache").exists())
        bad_specs = [dict(legacy_spec, schema_version=value) for value in (True, 1.0, "1", 0, 3)]
        bad_specs.extend((dict(legacy_spec, source_location="payload"), dict(legacy_spec, files=[]),
            dict(legacy_spec, exports=[dict(legacy_spec["exports"][0], source_name="other.pa1")])))
        for bad_spec in bad_specs:
            with self.subTest(spec=bad_spec):
                document["response_receipt"] = bad_spec
                pa_family_cache._write_transaction(path, document)
                before = path.read_bytes()
                with self.assertRaises(PAFamilyCacheError):
                    advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner)
                self.assertEqual(path.read_bytes(), before)

    def test_response_receipt_cli_seals_single_inventory(self):
        first, names, spec = self._response_receipt_fixture()
        spec_path = self.root / "recipe.json"
        identity_path = self.root / "identity.json"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        identity_path.write_text(json.dumps(identity()), encoding="utf-8")
        output = StringIO()
        with redirect_stdout(output):
            main(["--action", "advance-transaction", "--cache-root", str(self.cache),
                  "--identity", str(identity_path), "--filenames", ",".join(names),
                  "--response-receipt", str(spec_path)])
        self.assertEqual(json.loads(output.getvalue())["action_required"], "verify")
        self.assertTrue((first.build_directory / "responses.json").exists())

    def _artifact_cache(self, *, initialize_ledger: bool = True) -> tuple[Path, Path]:
        artifacts = self.root / "artifacts"
        artifacts.mkdir()
        producer_directory = (
            artifacts / "projects" / "fixture" / "runs"
            / "20260923_120000__test__simion__pa-producer__n1"
        )
        producer_directory.mkdir(parents=True)
        self.producer_run_config = producer_directory / "run_config.json"
        self.producer_run_config.write_text(json.dumps({
            "schema_version": 2,
            "run_id": producer_directory.name,
            "project": "fixture",
            "capacity_ledger_lifecycle": {
                "schema_version": 1,
                "enabled": True,
                "artifact_root": str(artifacts.resolve()),
                "light_evidence_budget_bytes": 1,
            },
        }), encoding="utf-8")
        if initialize_ledger:
            capacity_ledger.initialize_capacity_ledger(artifacts, objects=[])
            capacity_ledger.record_capacity_object(
                artifacts, path=producer_directory, object_class="rebuildable_payload",
                bytes_count=self.producer_run_config.stat().st_size, status="writing",
                owner=self.artifact_owner, recovery_reason="fixture producer is active",
                recovery_task="fixture owner closes producer", review_deadline="2026-10-01",
                recovery_evidence_paths=(self.producer_run_config,),
            )
        return artifacts, artifacts / "common" / "simion" / "pa_family_cache"

    def _producer_handoff_fixture(self, *, complete=False, sealed=False, prepared=False, retention_class="solver_review"):
        from common.contracts.frozen_inputs import freeze_file
        from common.contracts.run_capacity_lifecycle import seal_checkpoint
        from common.contracts.write_run_manifest import build_run_manifest

        artifacts, cache = self._artifact_cache()
        predecessor = self.producer_run_config.parent
        config = json.loads(self.producer_run_config.read_text())
        config["artifact_retention"] = dict(policy_version=1, **{"class": retention_class},
            reason=None if retention_class == "compact" else "fixture review")
        self.producer_run_config.write_text(json.dumps(config), encoding="utf-8")
        manifest = predecessor / "run_manifest.json"
        manifest.write_text(json.dumps(build_run_manifest(self.producer_run_config, "checkpoint")), encoding="utf-8")
        # Initialization precedes the normal dependency closure written before construction.
        config["dependency_closure"] = {"fixture": "frozen actual builder inputs"}
        self.producer_run_config.write_text(json.dumps(config), encoding="utf-8")
        capacity_ledger.record_capacity_object(artifacts, path=predecessor, object_class="rebuildable_payload",
            bytes_count=self.producer_run_config.stat().st_size, status="writing", owner="fixture",
            recovery_reason="fixture producer stopped", review_deadline="2026-10-01")
        first = advance_pa_family_cache_transaction(cache, identity(), self.names,
            owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        late_input = predecessor / "inputs/late_dependency.json"
        late_input.parent.mkdir(exist_ok=True)
        late_input.write_text('{"fixture": "retained dependency"}', encoding="utf-8")
        config.setdefault("inputs", {})["recovered_input_001"] = str(late_input)
        self.producer_run_config.write_text(json.dumps(config), encoding="utf-8")
        # A raw scratch array is deliberately not a complete field or checkpoint.
        partial = first.scratch_directory / "working.pa0"
        partial.write_bytes(b"incomplete native scratch; not solver evidence")
        if complete or sealed or prepared:
            self._land_transaction_members(first, self.names)
        if sealed or prepared:
            inventory = advance_pa_family_cache_transaction(cache, identity(), self.names,
                owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        if prepared:
            original_mkdir = Path.mkdir

            def stop_generation(path, *args, **kwargs):
                if path == cache / first.cache_key / "generations":
                    raise OSError("fixture publication stopped")
                return original_mkdir(path, *args, **kwargs)

            with patch.object(Path, "mkdir", new=stop_generation):
                with self.assertRaisesRegex(OSError, "fixture publication stopped"):
                    advance_pa_family_cache_transaction(cache, identity(), self.names,
                        owner=self.artifact_owner, verification_evidence=self._verification_evidence(inventory))
            self.assertTrue((cache / first.cache_key / "recovery").is_dir())
        stopped = seal_checkpoint(artifacts, self.producer_run_config, owner="fixture", writing_stopped=True,
            retain_payload=True, retention_reason="fixture owner observed writer and children stopped")
        self.assertEqual(stopped["run_status"], "checkpoint")
        new_run = predecessor.with_name("20260923_130000__test__simion__pa-successor__n1")
        (new_run / "inputs").mkdir(parents=True)
        config = json.loads(self.producer_run_config.read_text())
        config["run_id"] = new_run.name
        successor = new_run / "run_config.json"
        successor.write_text(json.dumps(config), encoding="utf-8")
        capacity_ledger.record_capacity_object(artifacts, path=new_run, object_class="rebuildable_payload",
            bytes_count=successor.stat().st_size, status="writing", owner="fixture",
            recovery_reason="fixture successor is active", review_deadline="2026-10-01")
        seal_path = self.root / "public_seal_receipt.json"
        seal_path.write_text(json.dumps(stopped), encoding="utf-8")
        request = dict(schema_version=1,
            transaction_record=freeze_file(first.transaction_directory / "transaction.json", new_run / "inputs/prior_transaction.json"),
            predecessor_manifest=freeze_file(manifest, new_run / "inputs/predecessor_manifest.json"),
            stopped_receipt=freeze_file(seal_path, new_run / "inputs/public_seal_receipt.json"),
            capacity_lease_id="fixture-handoff-workflow", capacity_lease_owner="fixture-successor-workflow")
        capacity_protection.create_capacity_protection_lease(artifacts, lease_id=request["capacity_lease_id"],
            owner=request["capacity_lease_owner"], ttl_seconds=300,
            protected_cache_keys=[first.cache_key], protected_paths=[new_run, predecessor])
        return artifacts, cache, first, successor, request

    def test_prepared_publication_reuses_same_readonly_manifest_and_rejects_drift(self):
        for policy in ("xor", "none"):
            for drift in (False, True):
                with self.subTest(policy=policy, drift=drift):
                    fixture = PAFamilyCacheTest()
                    fixture.setUp()
                    try:
                        _, cache = fixture._artifact_cache()
                        first = advance_pa_family_cache_transaction(cache, identity(), fixture.names,
                            owner=fixture.artifact_owner, producer_run_config=fixture.producer_run_config, recovery_policy=policy)
                        fixture._land_transaction_members(first, fixture.names)
                        sealed = advance_pa_family_cache_transaction(cache, identity(), fixture.names,
                            owner=fixture.artifact_owner, recovery_policy=policy)
                        blocker = cache / first.cache_key / "generations"
                        blocker.parent.mkdir(exist_ok=True)
                        blocker.write_text("test-owned publication target conflict", encoding="utf-8")
                        with self.assertRaises(OSError):
                            advance_pa_family_cache_transaction(cache, identity(), fixture.names,
                                owner=fixture.artifact_owner, verification_evidence=fixture._verification_evidence(sealed),
                                recovery_policy=policy)
                        manifest = first.build_directory / "cache_manifest.json"
                        original = manifest.read_bytes()
                        self.assertFalse(manifest.stat().st_mode & stat.S_IWRITE)
                        with self.assertRaises(OSError):
                            advance_pa_family_cache_transaction(cache, identity(), fixture.names,
                                owner=fixture.artifact_owner, recovery_policy=policy)
                        self.assertEqual(manifest.read_bytes(), original)
                        blocker.unlink()
                        if drift:
                            manifest.chmod(stat.S_IWRITE)
                            document = json.loads(original)
                            document["fixture_drift"] = True
                            manifest.write_text(json.dumps(document), encoding="utf-8")
                            manifest.chmod(stat.S_IREAD)
                            changed = manifest.read_bytes()
                            with self.assertRaisesRegex(PAFamilyCacheError, "publication manifest differs"):
                                advance_pa_family_cache_transaction(cache, identity(), fixture.names,
                                    owner=fixture.artifact_owner, recovery_policy=policy)
                            self.assertEqual(manifest.read_bytes(), changed)
                            self.assertFalse((cache / first.cache_key / "current_generation.json").exists())
                        else:
                            published = advance_pa_family_cache_transaction(cache, identity(), fixture.names,
                                owner=fixture.artifact_owner, recovery_policy=policy)
                            self.assertEqual(published.action_required, "complete")
                            self.assertEqual((published.generation_directory / "cache_manifest.json").read_bytes(), original)
                    finally:
                        fixture.tearDown()

    def test_producer_handoff_keeps_partial_unpublished_and_preserves_provenance(self):
        artifacts, cache, first, successor, request = self._producer_handoff_fixture()
        transaction = first.transaction_directory / "transaction.json"
        prior = json.loads(transaction.read_text())
        partial = first.scratch_directory / "working.pa0"
        original_open = Path.open
        def reject_partial_read(path, *args, **kwargs):
            if path == partial:
                raise AssertionError("handoff read native scratch")
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", new=reject_partial_read):
            result = advance_pa_family_cache_transaction(cache, identity(), self.names, owner="successor-owner",
                producer_run_config=successor, producer_handoff=request)
        self.assertEqual(result.action_required, "build")
        self.assertEqual(result.missing_files, self.names)
        self.assertIsNone(result.generation_sha256)
        self.assertTrue(partial.is_file())
        changed = json.loads(transaction.read_text())
        self.assertEqual(changed["owner"], "successor-owner")
        self.assertEqual(changed["producer"]["run_config_path"], str(successor.resolve()))
        self.assertEqual(changed["producer_handoff"]["prior_owner"], prior["owner"])
        self.assertEqual(changed["producer_handoff"]["prior_producer"], prior["producer"])
        self.assertEqual(self._ledger_entry(artifacts, first.cache_key)["owner"], "successor-owner")
        self.assertEqual(json.loads(Path(request["predecessor_manifest"]["path"]).read_text())["status"], "checkpoint")
        incomplete = advance_pa_family_cache_transaction(cache, identity(), self.names, owner="successor-owner",
            verification_evidence=self._verification_evidence(result))
        self.assertEqual(incomplete.action_required, "build")
        self.assertIsNone(incomplete.generation_directory)
        self._land_transaction_members(result, self.names)
        sealed = advance_pa_family_cache_transaction(cache, identity(), self.names, owner="successor-owner")
        published = advance_pa_family_cache_transaction(cache, identity(), self.names, owner="successor-owner",
            verification_evidence=self._verification_evidence(sealed))
        self.assertEqual(published.action_required, "complete")
        final = pa_family_cache.load_pa_family_cache_transaction(cache, first.cache_key)
        self.assertEqual(final["producer_handoff"]["prior_producer"], prior["producer"])
        self.assertEqual(final["producer"]["run_config_path"], str(successor.resolve()))

    def test_producer_handoff_accepts_frozen_manifest_larger_than_one_mib(self):
        from common.contracts.frozen_inputs import freeze_file

        _, cache, first, successor, request = self._producer_handoff_fixture()
        manifest = Path(request["predecessor_manifest"]["path"])
        expected = json.loads(manifest.read_text(encoding="utf-8"))
        # Legal JSON formatting can exceed any arbitrary metadata size limit.
        source = self.root / "large_predecessor_manifest.json"
        source.write_text(json.dumps(expected) + "\n" * (1024 * 1024), encoding="utf-8")
        request["predecessor_manifest"] = freeze_file(source, successor.parent / "inputs/large_predecessor_manifest.json")
        self.assertGreater(request["predecessor_manifest"]["bytes"], 1024 * 1024)
        self.assertEqual(json.loads(source.read_text(encoding="utf-8")), expected)
        result = advance_pa_family_cache_transaction(cache, identity(), self.names, owner="successor-owner",
            producer_run_config=successor, producer_handoff=request)
        self.assertEqual(result.action_required, "build")
        self.assertEqual(result.missing_files, self.names)
        self.assertIsNone(result.generation_sha256)
        self.assertTrue((first.scratch_directory / "working.pa0").is_file())

    def test_producer_handoff_uses_stopped_config_and_rejects_later_drift(self):
        _, cache, first, successor, request = self._producer_handoff_fixture()
        manifest = self.producer_run_config.parent / "run_manifest.json"
        original_manifest = manifest.read_bytes()
        stopped = json.loads(Path(request["stopped_receipt"]["path"]).read_text(encoding="utf-8"))
        initialized = json.loads(original_manifest)["run_config"]
        self.assertNotEqual(initialized["sha256"], stopped["run_config"]["sha256"])
        transaction = first.transaction_directory / "transaction.json"
        original_transaction = transaction.read_bytes()
        self.assertNotEqual(json.loads(original_transaction)["producer"]["run_config_sha256"],
                            stopped["run_config"]["sha256"])
        original_config = self.producer_run_config.read_bytes()
        self.producer_run_config.write_bytes(original_config + b"\n")
        with self.assertRaisesRegex(AssertionError, "stopped run config byte count changed"):
            advance_pa_family_cache_transaction(cache, identity(), self.names, owner="successor-owner",
                producer_run_config=successor, producer_handoff=request)
        self.assertEqual(transaction.read_bytes(), original_transaction)
        self.producer_run_config.write_bytes(original_config)
        result = advance_pa_family_cache_transaction(cache, identity(), self.names, owner="successor-owner",
            producer_run_config=successor, producer_handoff=request)
        self.assertEqual(result.action_required, "build")
        self.assertEqual(manifest.read_bytes(), original_manifest)

    def test_producer_handoff_replays_after_ledger_failure_and_is_concurrently_idempotent(self):
        artifacts, cache, first, successor, request = self._producer_handoff_fixture()
        with patch.object(pa_family_cache, "_record_transaction_stage", side_effect=OSError("fixture ledger interruption")):
            with self.assertRaisesRegex(OSError, "ledger interruption"):
                advance_pa_family_cache_transaction(cache, identity(), self.names, owner="successor-owner",
                    producer_run_config=successor, producer_handoff=request)
        def advance():
            return advance_pa_family_cache_transaction(cache, identity(), self.names, owner="successor-owner",
                producer_run_config=successor, producer_handoff=request)
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: advance(), range(2)))
        self.assertEqual([result.action_required for result in results], ["build", "build"])
        document = pa_family_cache.load_pa_family_cache_transaction(cache, first.cache_key)
        self.assertEqual(document["producer_handoff"]["prior_owner"], self.artifact_owner)
        self.assertEqual(self._ledger_entry(artifacts, first.cache_key)["owner"], "successor-owner")
        self.assertEqual(advance_pa_family_cache_transaction(cache, identity(), self.names,
            owner="successor-owner").action_required, "build")
        with self.assertRaisesRegex(PAFamilyCacheError, "replay producer differs"):
            advance_pa_family_cache_transaction(cache, identity(), self.names, owner="another-owner",
                producer_run_config=successor, producer_handoff=request)

    def test_producer_handoff_rejects_active_prior_protection_and_wrong_bindings(self):
        artifacts, cache, first, successor, request = self._producer_handoff_fixture()
        transaction = first.transaction_directory / "transaction.json"
        before = transaction.read_bytes()
        for coverage in (dict(protected_cache_keys=[first.cache_key]),
                         dict(protected_paths=[self.producer_run_config.parent]),
                         dict(protected_paths=[first.transaction_directory])):
            with self.subTest(coverage=coverage):
                capacity_protection.create_capacity_protection_lease(artifacts, lease_id="fixture-prior-writer",
                    owner="fixture-prior-writer", ttl_seconds=300, **coverage)
                try:
                    with self.assertRaisesRegex(PAFamilyCacheError, "another active consumer"):
                        advance_pa_family_cache_transaction(cache, identity(), self.names, owner="successor-owner",
                            producer_run_config=successor, producer_handoff=request)
                finally:
                    capacity_protection.delete_capacity_protection_lease(artifacts, lease_id="fixture-prior-writer")
                self.assertEqual(transaction.read_bytes(), before)
        from common.contracts.write_run_manifest import file_record
        for name, field, value in (("transaction_record", "owner", "foreign-owner"),
                                   ("predecessor_manifest", "run_id", "foreign-run"),
                                   ("stopped_receipt", "action", "register_writing"),
                                   ("stopped_receipt", "run_config", {"path": str(successor),
                                                                         "sha256": "F" * 64})):
            with self.subTest(record=name):
                changed = json.loads(json.dumps(request))
                path = successor.parent / "inputs" / (name + "_wrong.json")
                content = json.loads(Path(request[name]["path"]).read_text())
                content[field] = value
                path.write_text(json.dumps(content), encoding="utf-8")
                changed[name] = file_record(path)
                with self.assertRaisesRegex(PAFamilyCacheError, "differs"):
                    advance_pa_family_cache_transaction(cache, identity(), self.names, owner="successor-owner",
                        producer_run_config=successor, producer_handoff=changed)
                self.assertEqual(transaction.read_bytes(), before)
        changed = dict(request, capacity_lease_owner="foreign-workflow")
        with self.assertRaisesRegex(PAFamilyCacheError, "workflow lease differs"):
            advance_pa_family_cache_transaction(cache, identity(), self.names, owner="successor-owner",
                producer_run_config=successor, producer_handoff=changed)
        self.assertEqual(transaction.read_bytes(), before)

    def test_producer_handoff_conflicting_concurrent_successors_commit_only_one_owner(self):
        from common.contracts.frozen_inputs import freeze_file
        artifacts, cache, first, successor, request = self._producer_handoff_fixture()
        other = successor.parent.with_name("20260923_140000__test__simion__pa-other-successor__n1")
        (other / "inputs").mkdir(parents=True)
        config = json.loads(successor.read_text())
        config["run_id"] = other.name
        other_config = other / "run_config.json"
        other_config.write_text(json.dumps(config), encoding="utf-8")
        capacity_ledger.record_capacity_object(artifacts, path=other, object_class="rebuildable_payload",
            bytes_count=other_config.stat().st_size, status="writing", owner="fixture",
            recovery_reason="fixture competing successor", review_deadline="2026-10-01")
        competing = dict(request)
        for name in ("transaction_record", "predecessor_manifest", "stopped_receipt"):
            competing[name] = freeze_file(Path(request[name]["path"]), other / "inputs" / (name + ".json"))
        capacity_protection.delete_capacity_protection_lease(artifacts, lease_id=request["capacity_lease_id"])
        capacity_protection.create_capacity_protection_lease(artifacts, lease_id=request["capacity_lease_id"],
            owner=request["capacity_lease_owner"], ttl_seconds=300,
            protected_cache_keys=[first.cache_key], protected_paths=[successor.parent, other])
        transaction = first.transaction_directory / "transaction.json"
        prior_bytes = transaction.read_bytes()
        prior = json.loads(prior_bytes)
        prior_ledger_entry = dict(self._ledger_entry(artifacts, first.cache_key))
        partial = first.scratch_directory / "working.pa0"
        partial_bytes = partial.read_bytes()
        self.assertNotIn("producer_handoff", prior)

        def active_lease_ids():
            return {lease["lease_id"] for lease in
                    capacity_protection.load_capacity_protection_leases(artifacts)["audit"]
                    if lease["status"] == "active"}

        workflow_leases = active_lease_ids()
        def advance(case):
            owner, producer, evidence = case
            try:
                result = advance_pa_family_cache_transaction(cache, identity(), self.names, owner=owner,
                    producer_run_config=producer, producer_handoff=evidence)
                return owner, result.action_required
            except PAFamilyCacheError as error:
                return owner, str(error)
        cases = (("successor-one", successor, request), ("successor-two", other_config, competing))
        # A real foreign reader deterministically rejects both contenders.
        # No owner/journal/payload may change merely because advance was tried.
        foreign_lease = "fixture-concurrent-foreign-reader"
        capacity_protection.create_capacity_protection_lease(artifacts, lease_id=foreign_lease,
            owner="fixture-foreign-reader", ttl_seconds=300, protected_cache_keys=[first.cache_key])
        try:
            with ThreadPoolExecutor(max_workers=2) as workers:
                blocked = list(workers.map(advance, cases))
            self.assertTrue(all("another active consumer" in result for _, result in blocked), blocked)
            self.assertEqual(transaction.read_bytes(), prior_bytes)
            self.assertEqual(self._ledger_entry(artifacts, first.cache_key), prior_ledger_entry)
            self.assertEqual(partial.read_bytes(), partial_bytes)
            self.assertEqual(active_lease_ids(), workflow_leases | {foreign_lease})
        finally:
            capacity_protection.delete_capacity_protection_lease(artifacts, lease_id=foreign_lease)
        self.assertEqual(active_lease_ids(), workflow_leases)

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(advance, cases))
        winners = [owner for owner, result in results if result == "build"]
        self.assertLessEqual(len(winners), 1, results)
        self.assertEqual(active_lease_ids(), workflow_leases)
        for _, result in results:
            if result != "build":
                self.assertTrue("frozen transaction differs" in result or "another active consumer" in result,
                                results)
        if not winners:
            # Waiting operations also hold cleanup protection. If that blocks
            # both, their completed calls must leave the prior owner intact;
            # one normal retry after those guards are gone must then succeed.
            self.assertEqual(transaction.read_bytes(), prior_bytes)
            self.assertEqual(self._ledger_entry(artifacts, first.cache_key), prior_ledger_entry)
            self.assertEqual(partial.read_bytes(), partial_bytes)
            self.assertEqual(advance(cases[0]), ("successor-one", "build"))
            winners = ["successor-one"]
        changed = pa_family_cache.load_pa_family_cache_transaction(cache, first.cache_key)
        self.assertEqual(changed["owner"], winners[0])
        self.assertEqual(self._ledger_entry(artifacts, first.cache_key)["owner"], winners[0])
        selected = next(case for case in cases if case[0] == winners[0])
        self.assertEqual(changed["producer"]["run_config_path"], str(selected[1].resolve()))
        self.assertEqual(changed["producer_handoff"], dict(request=selected[2], prior_owner=prior["owner"],
            prior_producer=prior["producer"], new_owner=winners[0], new_producer=changed["producer"]))
        self.assertEqual(partial.read_bytes(), partial_bytes)
        self.assertEqual(active_lease_ids(), workflow_leases)

    def test_producer_handoff_uses_existing_advance_cli_and_rejects_changed_identity(self):
        from common.contracts.write_run_manifest import file_record
        _, cache, first, successor, request = self._producer_handoff_fixture()
        transaction = first.transaction_directory / "transaction.json"
        before = transaction.read_bytes()
        other_identity = identity()
        other_identity["gem"] = {"sha256": "D" * 64}
        for selected_identity, filenames in ((other_identity, self.names), (identity(), ("foreign.pa",))):
            with self.subTest(identity=selected_identity, filenames=filenames):
                with self.assertRaises(PAFamilyCacheError):
                    advance_pa_family_cache_transaction(cache, selected_identity, filenames,
                        owner="successor-owner", producer_run_config=successor, producer_handoff=request)
                self.assertEqual(transaction.read_bytes(), before)
        outside = dict(request, transaction_record=file_record(transaction))
        with self.assertRaisesRegex(PAFamilyCacheError, "must be frozen run input"):
            advance_pa_family_cache_transaction(cache, identity(), self.names, owner="successor-owner",
                producer_run_config=successor, producer_handoff=outside)
        self.assertEqual(transaction.read_bytes(), before)
        identity_path = successor.parent / "inputs/identity.json"
        identity_path.write_text(json.dumps(identity()), encoding="utf-8")
        handoff = successor.parent / "inputs/handoff.json"
        handoff.write_text(json.dumps(request), encoding="utf-8")
        stdout = StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(["--action", "advance-transaction", "--cache-root", str(cache),
                "--identity", str(identity_path), "--filenames", ",".join(self.names),
                "--owner", "successor-owner", "--producer-run-config", str(successor),
                "--producer-handoff", str(handoff), "--recovery-policy", "none"]), 0)
        self.assertEqual(json.loads(stdout.getvalue())["action_required"], "build")
        self.assertIsNone(json.loads(stdout.getvalue())["generation_sha256"])

    def test_complete_producer_handoff_retains_sources_until_separate_verification(self):
        _, cache, first, successor, request = self._producer_handoff_fixture(complete=True)
        scratch = first.scratch_directory / "working.pa0"
        original_scratch = scratch.read_bytes()
        with patch.object(pa_family_cache, "_inventory_transaction_payload", side_effect=AssertionError("handoff sealed payload")), \
                patch.object(pa_family_cache, "_publish_transaction_payload", side_effect=AssertionError("handoff published payload")):
            handed = advance_pa_family_cache_transaction(cache, identity(), self.names, owner="successor-owner",
                producer_run_config=successor, producer_handoff=request)
        self.assertEqual(handed.action_required, "verify")
        self.assertEqual(handed.missing_files, ())
        self.assertIsNone(handed.inventory_sha256)
        self.assertIsNone(handed.generation_sha256)
        self.assertEqual(scratch.read_bytes(), original_scratch)
        sealed = advance_pa_family_cache_transaction(cache, identity(), self.names, owner="successor-owner")
        self.assertEqual(sealed.action_required, "verify")
        evidence = self._verification_evidence(sealed)
        with self.assertRaisesRegex(PAFamilyCacheError, "verification evidence identity differs"):
            advance_pa_family_cache_transaction(cache, identity(), self.names, owner="successor-owner",
                verification_evidence=dict(evidence, status="failed"))
        self.assertEqual(scratch.read_bytes(), original_scratch)
        self.assertIsNone(pa_family_cache.load_pa_family_cache_transaction(cache, first.cache_key)["generation_sha256"])
        published = advance_pa_family_cache_transaction(cache, identity(), self.names, owner="successor-owner",
            verification_evidence=evidence)
        self.assertEqual(published.action_required, "complete")
        self.assertFalse(first.scratch_directory.exists())

    def test_sealed_producer_handoff_preserves_inventory_and_requires_verification(self):
        _, cache, first, successor, request = self._producer_handoff_fixture(sealed=True)
        prior = pa_family_cache.load_pa_family_cache_transaction(cache, first.cache_key)
        with patch.object(pa_family_cache, "_inventory_transaction_payload", side_effect=AssertionError("repeated inventory")):
            handed = advance_pa_family_cache_transaction(cache, identity(), self.names, owner="successor-owner",
                producer_run_config=successor, producer_handoff=request)
            replay = advance_pa_family_cache_transaction(cache, identity(), self.names, owner="successor-owner")
        self.assertEqual(handed.action_required, "verify")
        self.assertEqual(replay.action_required, "verify")
        current = pa_family_cache.load_pa_family_cache_transaction(cache, first.cache_key)
        for field in ("files", "inventory_sha256", "verification", "generation_sha256"):
            self.assertEqual(current[field], prior[field])
        self.assertTrue(first.scratch_directory.exists())
        published = advance_pa_family_cache_transaction(cache, identity(), self.names, owner="successor-owner",
            verification_evidence=self._verification_evidence(handed))
        self.assertEqual(published.action_required, "complete")
        self.assertFalse(first.scratch_directory.exists())

    def test_prepared_producer_handoff_publishes_only_on_subsequent_advance(self):
        artifacts, cache, first, successor, request = self._producer_handoff_fixture(prepared=True)
        prior = pa_family_cache.load_pa_family_cache_transaction(cache, first.cache_key)
        self.assertEqual(prior["status"], "prepared")
        _, key_relative = capacity_ledger.capacity_object_path(artifacts, cache / first.cache_key)
        old_key = next(row for row in capacity_ledger.load_capacity_ledger(artifacts)["objects"]
                       if row["path"] == key_relative)
        self.assertEqual(old_key["owner"], self.artifact_owner)
        self.assertGreater(old_key["bytes"], 0)
        frozen = {name: Path(request[name]["path"]).read_bytes()
                  for name in ("transaction_record", "predecessor_manifest", "stopped_receipt")}
        with patch.object(pa_family_cache, "_publish_transaction_payload", side_effect=AssertionError("handoff published payload")):
            handed = advance_pa_family_cache_transaction(cache, identity(), self.names, owner="successor-owner",
                producer_run_config=successor, producer_handoff=request)
        self.assertEqual(handed.action_required, "verify")
        current = pa_family_cache.load_pa_family_cache_transaction(cache, first.cache_key)
        for field in ("files", "inventory_sha256", "verification", "generation_sha256"):
            self.assertEqual(current[field], prior[field])
        changed_key = next(row for row in capacity_ledger.load_capacity_ledger(artifacts)["objects"]
                           if row["path"] == key_relative)
        self.assertEqual(changed_key, dict(old_key, owner="successor-owner"))
        repeated = advance_pa_family_cache_transaction(cache, identity(), self.names, owner="successor-owner",
            producer_run_config=successor, producer_handoff=request)
        self.assertEqual(repeated.action_required, "verify")
        self.assertEqual(pa_family_cache.load_pa_family_cache_transaction(cache, first.cache_key), current)
        for name, original in frozen.items():
            self.assertEqual(Path(request[name]["path"]).read_bytes(), original)
        with patch.object(pa_family_cache, "_inventory_transaction_payload", side_effect=AssertionError("repeated inventory")):
            published = advance_pa_family_cache_transaction(cache, identity(), self.names, owner="successor-owner")
        self.assertEqual(published.action_required, "complete")

    def test_prepared_handoff_key_owner_write_failure_replays_committed_journal(self):
        for replay_request in (False, True):
            with self.subTest(replay_request=replay_request):
                fixture = PAFamilyCacheTest()
                fixture.setUp()
                try:
                    artifacts, cache, first, successor, request = fixture._producer_handoff_fixture(prepared=True)
                    key_root = cache / first.cache_key
                    _, relative = capacity_ledger.capacity_object_path(artifacts, key_root)
                    original_record = capacity_ledger.record_capacity_object

                    def fail_transfer(root, **kwargs):
                        if kwargs["path"] == key_root and kwargs["owner"] == "successor-owner":
                            raise OSError("fixture handoff key owner write")
                        return original_record(root, **kwargs)

                    with patch.object(capacity_ledger, "record_capacity_object", side_effect=fail_transfer):
                        with self.assertRaisesRegex(OSError, "handoff key owner write"):
                            advance_pa_family_cache_transaction(cache, identity(), fixture.names,
                                owner="successor-owner", producer_run_config=successor, producer_handoff=request)
                    committed = pa_family_cache.load_pa_family_cache_transaction(cache, first.cache_key)
                    self.assertEqual(committed["owner"], "successor-owner")
                    old_key = next(row for row in capacity_ledger.load_capacity_ledger(artifacts)["objects"]
                                   if row["path"] == relative)
                    self.assertEqual(old_key["owner"], fixture.artifact_owner)
                    options = dict(owner="successor-owner")
                    if replay_request:
                        result = advance_pa_family_cache_transaction(cache, identity(), fixture.names,
                            producer_run_config=successor, producer_handoff=request, **options)
                        self.assertEqual(result.action_required, "verify")
                    result = advance_pa_family_cache_transaction(cache, identity(), fixture.names, **options)
                    self.assertEqual(result.action_required, "complete")
                    key = next(row for row in capacity_ledger.load_capacity_ledger(artifacts)["objects"]
                               if row["path"] == relative)
                    self.assertEqual(key["owner"], "successor-owner")
                    self.assertEqual(key["status"], "ready")
                    self.assertEqual(key["bytes"], pa_family_cache._key_root_bytes(key_root))
                finally:
                    fixture.tearDown()

    def test_prepared_producer_handoff_rejects_changed_verification_before_owner_transfer(self):
        artifacts, cache, first, successor, request = self._producer_handoff_fixture(prepared=True)
        transaction = first.transaction_directory / "transaction.json"
        before = transaction.read_bytes()
        ledger_before = capacity_ledger.load_capacity_ledger(artifacts)
        evidence = json.loads(before)["verification"]
        Path(evidence["verification_output_path"]).write_text("changed fixture verification", encoding="utf-8")
        with self.assertRaisesRegex(PAFamilyCacheError, "verification_output_path identity differs"):
            advance_pa_family_cache_transaction(cache, identity(), self.names, owner="successor-owner",
                producer_run_config=successor, producer_handoff=request)
        self.assertEqual(transaction.read_bytes(), before)
        self.assertEqual(capacity_ledger.load_capacity_ledger(artifacts), ledger_before)

    def test_producer_handoff_rejects_compact_producer(self):
        _, cache, first, successor, request = self._producer_handoff_fixture(retention_class="compact")
        transaction = first.transaction_directory / "transaction.json"
        before = transaction.read_bytes()
        with self.assertRaisesRegex(PAFamilyCacheError, "predeclared retained-payload run"):
            advance_pa_family_cache_transaction(cache, identity(), self.names, owner="successor-owner",
                producer_run_config=successor, producer_handoff=request)
        self.assertEqual(transaction.read_bytes(), before)

    def test_producer_handoff_rejects_published_transaction(self):
        _, cache, first, successor, request = self._producer_handoff_fixture(sealed=True)
        sealed = advance_pa_family_cache_transaction(cache, identity(), self.names, owner=self.artifact_owner)
        advance_pa_family_cache_transaction(cache, identity(), self.names, owner=self.artifact_owner,
            verification_evidence=self._verification_evidence(sealed))
        transaction = first.transaction_directory / "transaction.json"
        before = transaction.read_bytes()
        with self.assertRaisesRegex(PAFamilyCacheError, "unpublished transaction"):
            advance_pa_family_cache_transaction(cache, identity(), self.names, owner="successor-owner",
                producer_run_config=successor, producer_handoff=request)
        self.assertEqual(transaction.read_bytes(), before)

    def test_producer_handoff_preserves_owners_of_existing_recovery_journals(self):
        # Produce the journals through their real APIs. They retain their old
        # owner authority even when their payload is otherwise complete.
        for kind in ("member_recovery", "retained_inventory_recovery", "publication_metadata_correction"):
            with self.subTest(journal=kind):
                self.cache = self.root / kind
                if kind == "member_recovery":
                    names, progress, request = self._sealed_mismatch_fixture()
                    progress = advance_pa_family_cache_transaction(self.cache, identity(), names,
                        owner=self.artifact_owner, member_recovery=request)
                elif kind == "retained_inventory_recovery":
                    names, progress, request, _ = self._retained_inventory_fixture()
                    progress = advance_pa_family_cache_transaction(self.cache, identity(), names,
                        owner=self.artifact_owner, retained_inventory_recovery=request)
                else:
                    names, progress, request, _ = self._published_correction_fixture()
                    progress = advance_pa_family_cache_transaction(self.cache, identity(), names,
                        owner=self.artifact_owner, publication_metadata_correction=request)
                transaction = progress.transaction_directory / "transaction.json"
                before = transaction.read_bytes()
                self.assertIn(kind, json.loads(before))
                with self.assertRaisesRegex(PAFamilyCacheError, "owner bound by a payload recovery journal"):
                    advance_pa_family_cache_transaction(self.cache, identity(), names, owner="successor-owner",
                        producer_run_config=self.producer_run_config, producer_handoff={})
                self.assertEqual(transaction.read_bytes(), before)

    def _ledger_entry(self, artifacts: Path, cache_key: str) -> dict[str, object]:
        ledger = capacity_ledger.load_capacity_ledger(artifacts)
        self.assertIsNotNone(ledger)
        matches = [
            item for item in ledger["objects"]
            if Path(item["path"]).name == cache_key
        ]
        published = [item for item in matches if item["class"] == "published_cache"]
        self.assertLessEqual(len(published), 1)
        if published:
            return published[0]
        key_roots = [
            item for item in matches
            if ".transactions" not in Path(item["path"]).parts
        ]
        if key_roots:
            self.assertEqual(len(key_roots), 1)
            return key_roots[0]
        self.assertEqual(len(matches), 1)
        return matches[0]

    def _verification_evidence(
        self, prepared: pa_family_cache.TransactionAdvance
    ) -> dict[str, object]:
        verifier = b"fixture SIMION verifier"
        output = b"MRTOF_NATIVE_CORRIDOR_FAMILY_VERIFY=PASS"
        verifier_path = self.root / "verify_family.lua"
        output_path = self.root / "verify_family.out"
        verifier_path.write_bytes(verifier)
        output_path.write_bytes(output)
        return {
            "schema_version": 1,
            "role": pa_family_cache.VERIFICATION_EVIDENCE_ROLE,
            "status": "pass",
            "cache_key": prepared.cache_key,
            "inventory_sha256": prepared.inventory_sha256,
            "solver_release": "SIMION 2020",
            "verifier_path": str(verifier_path),
            "verifier_sha256": hashlib.sha256(verifier).hexdigest().upper(),
            "verification_output_path": str(output_path),
            "verification_output_sha256": hashlib.sha256(output).hexdigest().upper(),
        }

    def _publish_governed_transaction(
        self, cache: Path, *, recovery_policy: str = "none"
    ) -> pa_family_cache.TransactionAdvance:
        """Publish fixture bytes only through the production transaction path."""
        building = advance_pa_family_cache_transaction(
            cache, identity(), self.names, owner=self.artifact_owner,
            producer_run_config=self.producer_run_config, recovery_policy=recovery_policy,
        )
        self._land_transaction_members(building, self.names)
        prepared = advance_pa_family_cache_transaction(
            cache, identity(), self.names, owner=self.artifact_owner, producer_run_config=self.producer_run_config, recovery_policy=recovery_policy
        )
        return advance_pa_family_cache_transaction(
            cache,
            identity(),
            self.names,
            verification_evidence=self._verification_evidence(prepared),
            owner=self.artifact_owner,
            recovery_policy=recovery_policy,
        )

    @staticmethod
    def _tree_bytes(root: Path) -> int:
        return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())

    def test_artifact_publication_requires_trusted_ledger_without_modifying_source(self) -> None:
        _, cache = self._artifact_cache(initialize_ledger=False)
        before = {name: (self.source / name).read_bytes() for name in self.names}
        with self.assertRaisesRegex(PAFamilyCacheError, "calibrated capacity ledger"):
            advance_pa_family_cache_transaction(cache, identity(), self.names, owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        self.assertEqual(
            before, {name: (self.source / name).read_bytes() for name in self.names}
        )
        self.assertFalse((cache / ".transactions").exists())

    def test_record_stage_only_accounts_stopped_payload_and_working_bytes_without_advancing(self) -> None:
        artifacts, cache = self._artifact_cache()
        args = dict(owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        first = advance_pa_family_cache_transaction(cache, identity(), self.names, **args)
        transaction = first.transaction_directory / "transaction.json"
        original = transaction.read_bytes()
        (first.build_directory / self.names[0]).write_bytes(b"INERT_PAYLOAD")
        (first.scratch_directory / "working.pa0").write_bytes(b"INERT_WORKING")
        expected = sum(p.stat().st_size for p in first.transaction_directory.rglob("*") if p.is_file())
        real_hash = pa_family_cache.file_sha256
        def hash_metadata(path):
            self.assertEqual(Path(path), self.producer_run_config)
            return real_hash(path)
        with patch.object(pa_family_cache, "file_sha256", side_effect=hash_metadata), \
             patch.object(pa_family_cache, "_inventory_transaction_payload", side_effect=AssertionError("no payload hash")), \
             patch.object(pa_family_cache, "_seal_generation_files", side_effect=AssertionError("no seal")), \
             patch.object(pa_family_cache, "_publish_transaction_payload", side_effect=AssertionError("no publish")):
            for _ in range(2):
                result = advance_pa_family_cache_transaction(cache, identity(), self.names, record_stage_only=True, **args)
                self.assertEqual((result.status, result.action_required), ("building", "build"))
                self.assertEqual(transaction.read_bytes(), original)
                ledger = capacity_ledger.load_capacity_ledger(artifacts)
                entry = next(r for r in ledger["objects"] if r["path"] == first.transaction_directory.relative_to(artifacts).as_posix())
                self.assertEqual(entry["bytes"], expected)
                self.assertEqual(entry["status"], "writing")
                self.assertIsNone(result.generation_directory)
        self.assertTrue((first.scratch_directory / "working.pa0").is_file())

    def test_record_stage_only_requires_existing_building_owner_and_producer(self) -> None:
        _, cache = self._artifact_cache()
        args = dict(owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        with self.assertRaisesRegex(PAFamilyCacheError, "existing"):
            advance_pa_family_cache_transaction(cache, identity(), self.names, record_stage_only=True, **args)
        self.assertFalse((cache / ".transactions").exists())
        first = advance_pa_family_cache_transaction(cache, identity(), self.names, **args)
        path = first.transaction_directory / "transaction.json"
        original = path.read_bytes()
        for changes in (dict(owner="another"), dict(producer_run_config=self.root/"another.json"),
                        dict(verification_evidence={}), dict(producer_handoff={})):
            with self.subTest(changes=changes), self.assertRaises(PAFamilyCacheError):
                advance_pa_family_cache_transaction(cache, identity(), self.names, record_stage_only=True, **{**args, **changes})
            self.assertEqual(path.read_bytes(), original)
        self._land_transaction_members(first, self.names)
        sealed = advance_pa_family_cache_transaction(cache, identity(), self.names, **args)
        advance_pa_family_cache_transaction(cache, identity(), self.names,
            verification_evidence=self._verification_evidence(sealed), **args)
        with self.assertRaisesRegex(PAFamilyCacheError, "same building"):
            advance_pa_family_cache_transaction(cache, identity(), self.names, record_stage_only=True, **args)

    def test_artifact_transaction_requires_explicit_owner_before_creating_payload(self) -> None:
        _, cache = self._artifact_cache()
        with self.assertRaisesRegex(PAFamilyCacheError, "requires an explicit nonempty owner"):
            advance_pa_family_cache_transaction(cache, identity(), self.names)
        self.assertFalse((cache / ".transactions").exists())
        with self.assertRaisesRegex(PAFamilyCacheError, "requires a producer run config"):
            advance_pa_family_cache_transaction(
                cache, identity(), self.names, owner=self.artifact_owner
            )

    def test_artifact_transaction_rejects_unregistered_or_external_producer_before_payload(self) -> None:
        artifacts, cache = self._artifact_cache()
        with self.assertRaisesRegex(PAFamilyCacheError, "direct governed runs"):
            advance_pa_family_cache_transaction(
                cache, identity(), self.names, owner=self.artifact_owner,
                producer_run_config=self.root / "run_config.json",
            )
        unregistered = artifacts / "projects" / "fixture" / "runs" / "20260923_120001__test__simion__unregistered__n1"
        unregistered.mkdir(parents=True)
        config = unregistered / "run_config.json"
        config.write_text(json.dumps({
            "capacity_ledger_lifecycle": {
                "schema_version": 1, "enabled": True,
                "artifact_root": str(artifacts.resolve()), "light_evidence_budget_bytes": 1,
            },
        }), encoding="utf-8")
        with self.assertRaisesRegex(PAFamilyCacheError, "not registered"):
            advance_pa_family_cache_transaction(
                cache, identity(), self.names, owner=self.artifact_owner,
                producer_run_config=config,
            )
        self.assertFalse((cache / ".transactions").exists())
        building = advance_pa_family_cache_transaction(
            cache, identity(), self.names, owner=self.artifact_owner,
            producer_run_config=self.producer_run_config,
        )
        self.assertEqual(building.action_required, "build")
        transaction = json.loads(
            (building.transaction_directory / "transaction.json").read_text(encoding="utf-8")
        )
        self.assertEqual(transaction["owner"], self.artifact_owner)
        self.assertEqual(
            transaction["producer"]["run_config_sha256"],
            pa_family_cache.file_sha256(self.producer_run_config),
        )

    def test_artifact_publish_hit_and_materialize_record_lifecycle_without_hashing_hit(self) -> None:
        artifacts, cache = self._artifact_cache()
        with patch.object(pa_family_cache.time, "time", return_value=100.0):
            published = self._publish_governed_transaction(cache)
        key_root = cache / published.cache_key
        ledger = capacity_ledger.load_capacity_ledger(artifacts)
        _, key_relative = capacity_ledger.capacity_object_path(
            artifacts, cache / published.cache_key
        )
        entry = next(
            item for item in ledger["objects"] if item["path"] == key_relative
        )
        self.assertEqual(entry["class"], "published_cache")
        self.assertEqual(entry["status"], "ready")
        self.assertEqual(entry["identity"], published.generation_sha256)
        self.assertEqual(entry["bytes"], self._tree_bytes(key_root))
        self.assertNotIn("last_used_epoch", entry)

        with patch.object(
            pa_family_cache,
            "file_sha256",
            side_effect=AssertionError("healthy hit must not hash PA payloads"),
        ), patch.object(pa_family_cache.time, "time", return_value=101.0):
            hit = probe_pa_family_cache(
                cache, identity(), expected_filenames=self.names
            )
        self.assertIs(hit.disposition, CacheDisposition.HIT)
        self.assertEqual(
            self._ledger_entry(artifacts, published.cache_key)["last_used_epoch"],
            101.0,
        )

        capacity_protection.create_capacity_protection_lease(
            artifacts,
            lease_id="fixture-consumer",
            owner="pa-family-cache-test",
            ttl_seconds=300,
            protected_cache_keys=[published.cache_key],
        )
        lease_root = artifacts / "common" / "capacity_protection_leases"
        before_leases = sorted(path.name for path in lease_root.glob("*.json"))
        with patch.object(pa_family_cache.time, "time", return_value=102.0):
            materialize_pa_family_cache(
                published.generation_directory,
                self.root / "consumer" / "simion",
                expected_filenames=self.names,
                capacity_lease_id="fixture-consumer",
                capacity_lease_owner="pa-family-cache-test",
            )
        self.assertEqual(
            before_leases, sorted(path.name for path in lease_root.glob("*.json"))
        )
        self.assertEqual(
            self._ledger_entry(artifacts, published.cache_key)["last_used_epoch"],
            102.0,
        )
        with self.assertRaisesRegex(ValueError, "active capacity protection lease"):
            capacity_ledger.mark_retirement_pending(
                artifacts, path=key_root
            )
        capacity_protection.delete_capacity_protection_lease(
            artifacts, lease_id="fixture-consumer"
        )

    def test_artifact_materialization_requires_matching_active_consumer_lease(self) -> None:
        artifacts, cache = self._artifact_cache()
        published = self._publish_governed_transaction(cache)
        with self.assertRaisesRegex(PAFamilyCacheError, "requires an active protection lease id"):
            materialize_pa_family_cache(published.generation_directory, self.root / "missing-lease")
        capacity_protection.create_capacity_protection_lease(
            artifacts,
            lease_id="fixture-consumer-binding",
            owner="fixture-owner",
            ttl_seconds=300,
            protected_cache_keys=[published.cache_key],
        )
        with self.assertRaisesRegex(PAFamilyCacheError, "protection lease is absent"):
            materialize_pa_family_cache(
                published.generation_directory,
                self.root / "wrong-owner",
                capacity_lease_id="fixture-consumer-binding",
                capacity_lease_owner="different-owner",
            )
        materialized = materialize_pa_family_cache(
            published.generation_directory,
            self.root / "bound-consumer",
            capacity_lease_id="fixture-consumer-binding",
            capacity_lease_owner="fixture-owner",
        )
        self.assertEqual(materialized.source_generation_directory, published.generation_directory.resolve())

    def test_artifact_materialization_rejects_retired_transaction_before_copy(self) -> None:
        artifacts, cache = self._artifact_cache()
        published = self._publish_governed_transaction(cache)
        capacity_protection.create_capacity_protection_lease(
            artifacts,
            lease_id="fixture-retired-consumer",
            owner="fixture-owner",
            ttl_seconds=300,
            protected_cache_keys=[published.cache_key],
        )
        transaction_path = published.transaction_directory / "transaction.json"
        transaction = json.loads(transaction_path.read_text(encoding="utf-8"))
        transaction["status"] = "retired"
        transaction["retirement"] = {"id": "A" * 64, "generation": published.generation_sha256}
        pa_family_cache._write_transaction(transaction_path, transaction)
        destination = self.root / "retired-consumer"
        with self.assertRaisesRegex(PAFamilyCacheError, "not the active published generation"):
            materialize_pa_family_cache(
                published.generation_directory,
                destination,
                capacity_lease_id="fixture-retired-consumer",
                capacity_lease_owner="fixture-owner",
            )
        self.assertFalse(destination.exists())

    def test_legacy_unbound_published_cache_cannot_consume_or_retire(self) -> None:
        artifacts, cache = self._artifact_cache()
        published = self._publish_governed_transaction(cache)
        capacity_protection.create_capacity_protection_lease(
            artifacts,
            lease_id="fixture-legacy-consumer",
            owner="fixture-owner",
            ttl_seconds=300,
            protected_cache_keys=[published.cache_key],
        )
        transaction_path = published.transaction_directory / "transaction.json"
        transaction_path.unlink()
        ledger_path = capacity_ledger.resolve_ledger_path(artifacts)
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        key_relative = capacity_ledger.capacity_object_path(
            artifacts, cache / published.cache_key
        )[1]
        entry = next(item for item in ledger["objects"] if item["path"] == key_relative)
        entry.pop("manager")
        ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
        with self.assertRaisesRegex(PAFamilyCacheError, "valid capacity ledger binding"):
            materialize_pa_family_cache(
                published.generation_directory,
                self.root / "legacy-unbound-consumer",
                capacity_lease_id="fixture-legacy-consumer",
                capacity_lease_owner="fixture-owner",
            )
        with self.assertRaisesRegex(PAFamilyCacheError, "transaction"):
            approve_pa_family_cache_retirement(
                cache, published.cache_key, published.generation_sha256
            )

    def test_artifact_hit_does_not_overwrite_concurrent_writing_state(self) -> None:
        artifacts, cache = self._artifact_cache()
        published = self._publish_governed_transaction(cache)
        key_root = cache / published.cache_key
        next_generation = "D" * 64
        capacity_ledger.record_capacity_object(
            artifacts,
            path=key_root,
            object_class="published_cache",
            bytes_count=self._tree_bytes(key_root),
            status="writing",
            identity=next_generation,
            owner="test",
            recovery_reason="fixture_incomplete",
            review_deadline="2026-09-27",
        )

        hit = probe_pa_family_cache(cache, identity(), expected_filenames=self.names)

        self.assertIs(hit.disposition, CacheDisposition.HIT)
        ledger = capacity_ledger.load_capacity_ledger(artifacts)
        _, key_relative = capacity_ledger.capacity_object_path(
            artifacts, cache / published.cache_key
        )
        entry = next(
            item for item in ledger["objects"] if item["path"] == key_relative
        )
        self.assertEqual(entry["status"], "writing")
        self.assertEqual(entry["identity"], next_generation)
        self.assertNotIn("last_used_epoch", entry)

    def test_artifact_direct_publisher_is_rejected_before_writing(self) -> None:
        _, cache = self._artifact_cache()
        before = {name: (self.source / name).read_bytes() for name in self.names}
        with self.assertRaisesRegex(PAFamilyCacheError, "requires advance_pa_family_cache_transaction"):
            publish_pa_family_cache(cache, identity(), self.source, self.names)
        self.assertFalse(cache.exists())
        self.assertEqual(before, {name: (self.source / name).read_bytes() for name in self.names})

    def test_transaction_binds_caller_owner_and_rejects_owner_drift(self) -> None:
        first = advance_pa_family_cache_transaction(
            self.cache, identity(), self.names, owner="fixture-run-001"
        )
        document = json.loads(
            (first.transaction_directory / "transaction.json").read_text(encoding="utf-8")
        )
        self.assertEqual(document["owner"], "fixture-run-001")
        with self.assertRaisesRegex(PAFamilyCacheError, "owner differs"):
            advance_pa_family_cache_transaction(
                self.cache, identity(), self.names, owner="fixture-run-002"
            )

    def test_artifact_transaction_publication_is_idempotent(self) -> None:
        _, cache = self._artifact_cache()
        published = self._publish_governed_transaction(cache)
        repeated = advance_pa_family_cache_transaction(
            cache, identity(), self.names, recovery_policy="none"
        )
        self.assertEqual(repeated.status, "published")
        self.assertEqual(repeated.generation_sha256, published.generation_sha256)

    def test_artifact_rollback_without_predecessor_keeps_receipt_as_rebuildable(self) -> None:
        artifacts, cache = self._artifact_cache()
        published = self._publish_governed_transaction(cache)

        receipt = rollback_pa_family_cache_publication(
            cache,
            identity(),
            published.generation_sha256,
            expected_predecessor_generation_sha256=None,
            reason="fixture rejects initial publication",
        )

        key_root = cache / published.cache_key
        entry = self._ledger_entry(artifacts, published.cache_key)
        self.assertEqual(entry["class"], "rebuildable_payload")
        self.assertEqual(entry["status"], "ready")
        self.assertNotIn("identity", entry)
        self.assertEqual(entry["bytes"], self._tree_bytes(key_root))
        self.assertTrue(Path(receipt["receipt_path"]).is_file())
        self.assertFalse((key_root / pa_family_cache.POINTER_NAME).exists())

    def test_artifact_rollback_failure_preserves_actual_writing_bytes(self) -> None:
        artifacts, cache = self._artifact_cache()
        published = self._publish_governed_transaction(cache)
        original_write_json = pa_family_cache._write_json

        def fail_rollback_receipt(path: Path, document: dict[str, object]) -> None:
            if document.get("role") == "simion_pa_family_cache_publication_rollback":
                raise OSError("fixture rollback receipt failure")
            original_write_json(path, document)

        with patch.object(
            pa_family_cache, "_write_json", side_effect=fail_rollback_receipt
        ):
            with self.assertRaisesRegex(OSError, "fixture rollback receipt failure"):
                rollback_pa_family_cache_publication(
                    cache,
                    identity(),
                    published.generation_sha256,
                    expected_predecessor_generation_sha256=None,
                    reason="fixture receipt failure",
                )

        key_root = cache / published.cache_key
        entry = self._ledger_entry(artifacts, published.cache_key)
        self.assertEqual(entry["class"], "published_cache")
        self.assertEqual(entry["status"], "writing")
        self.assertEqual(entry["identity"], published.generation_sha256)
        self.assertEqual(entry["bytes"], self._tree_bytes(key_root))
        error = json.loads(
            (key_root / pa_family_cache.PUBLICATION_ERROR_NAME).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(error["operation"], "rollback")
        self.assertIn("fixture rollback receipt failure", error["error"])

    def test_key_covers_every_required_identity_dimension(self) -> None:
        original = canonical_pa_family_cache_key(identity())
        for field in identity():
            changed = identity()
            changed[field] = {"changed": field}
            self.assertNotEqual(original, canonical_pa_family_cache_key(changed), field)
        missing = identity()
        del missing["mesh"]
        with self.assertRaisesRegex(PAFamilyCacheError, "identity fields"):
            canonical_pa_family_cache_key(missing)

    def test_working_field_key_preserves_basis_key_and_canonical_order(self) -> None:
        self.assertEqual(canonical_pa_family_cache_key(identity()),
                         "1EF59CD98A3CCFFCD16F8178A20BE14D52A0505A76E8D36E29E3306E8EB84EB8")
        original = working_field_identity()
        reordered = dict(reversed(list(original.items())))
        reordered["working_points"] = [dict(reversed(list(point.items()))) for point in original["working_points"]]
        for point in reordered["working_points"]:
            point["electrode_voltages_v"] = dict(reversed(list(point["electrode_voltages_v"].items())))
        self.assertEqual(canonical_pa_family_cache_key(original), canonical_pa_family_cache_key(reordered))
        self.assertNotEqual(canonical_pa_family_cache_key(original), canonical_pa_family_cache_key(identity()))

    def test_working_field_key_covers_numerics_and_rejects_partial_or_mixed_identity(self) -> None:
        original = canonical_pa_family_cache_key(working_field_identity())
        mutations = (
            lambda d: d["working_points"][0]["electrode_voltages_v"].update({"1": 4.0}),
            lambda d: d["working_points"][1].update(refine_convergence_v=0.002),
            lambda d: d.update(rf_reference_voltage_v=5000.0),
            lambda d: d.update(boundary_policy="zero_dirichlet"),
        )
        for index, mutate in enumerate(mutations):
            changed = working_field_identity()
            mutate(changed)
            with self.subTest(change=index):
                self.assertNotEqual(original, canonical_pa_family_cache_key(changed))
        for make_identity in (identity, working_field_identity):
            for field in make_identity():
                incomplete = make_identity()
                del incomplete[field]
                with self.subTest(missing=field, identity=make_identity.__name__):
                    with self.assertRaisesRegex(PAFamilyCacheError, "identity fields"):
                        canonical_pa_family_cache_key(incomplete)
            for field in ("source", "pressure", "run_directory"):
                with self.subTest(extra=field, identity=make_identity.__name__):
                    with self.assertRaisesRegex(PAFamilyCacheError, "identity fields"):
                        canonical_pa_family_cache_key({**make_identity(), field: "not numerical authority"})
        for extra in ({"basis_namespace": {}}, {"refine_policy": {}}, identity()):
            with self.assertRaisesRegex(PAFamilyCacheError, "identity fields"):
                canonical_pa_family_cache_key({**working_field_identity(), **extra})
        for nonfinite in (float("inf"), float("nan")):
            invalid = working_field_identity()
            invalid["working_points"][0]["electrode_voltages_v"]["1"] = nonfinite
            with self.assertRaisesRegex(PAFamilyCacheError, "canonical finite JSON"):
                canonical_pa_family_cache_key(invalid)

    def test_no_rf_working_identity_has_no_reference_and_still_rejects_missing_rf_authority(self):
        without = working_field_identity()
        without['working_points'] = [row for row in without['working_points'] if row['kind'] != 'rf_reference']
        del without['rf_reference_voltage_v']
        key = canonical_pa_family_cache_key(without)
        self.assertEqual(key, canonical_pa_family_cache_key(dict(reversed(list(without.items())))))
        self.assertNotEqual(key, canonical_pa_family_cache_key(working_field_identity()))
        with self.assertRaisesRegex(PAFamilyCacheError, 'RF reference'):
            canonical_pa_family_cache_key({**without, 'rf_reference_voltage_v': None})
        invalid = working_field_identity()
        del invalid['rf_reference_voltage_v']
        with self.assertRaisesRegex(PAFamilyCacheError, 'RF reference'):
            canonical_pa_family_cache_key(invalid)
        for name in without:
            missing = dict(without)
            del missing[name]
            with self.subTest(missing=name), self.assertRaises(PAFamilyCacheError):
                canonical_pa_family_cache_key(missing)

    def test_no_rf_working_fields_use_the_same_governed_transaction(self):
        self.check_working_transaction(has_rf=False)

    def test_working_fields_use_governed_transaction_without_response_receipt(self) -> None:
        self.check_working_transaction(has_rf=True)

    def check_working_transaction(self, *, has_rf):
        artifacts, cache = self._artifact_cache()
        document = working_field_identity()
        if not has_rf:
            del document['rf_reference_voltage_v']
            document['working_points'] = [row for row in document['working_points'] if row['kind'] != 'rf_reference']
        names = tuple(row['kind']+'.pa' for row in document['working_points'])
        options = dict(owner=self.artifact_owner, producer_run_config=self.producer_run_config, recovery_policy="none")
        first = advance_pa_family_cache_transaction(cache, document, names, **options)
        self.assertEqual(first.action_required, "build")
        payloads = {name: b"INERT_TEST_NOT_PA:" + name.encode() for name in names}
        for name, payload in payloads.items():
            temporary = first.scratch_directory / name
            temporary.write_bytes(payload)
            temporary.replace(first.build_directory / name)
        (first.scratch_directory / "raw_build_only.pa#").write_bytes(b"INERT_BUILD_SCRATCH")
        prepared = advance_pa_family_cache_transaction(cache, document, names, **options)
        self.assertEqual(prepared.action_required, "verify")
        evidence = self._verification_evidence(prepared)
        with self.assertRaises(PAFamilyCacheError):
            advance_pa_family_cache_transaction(cache, document, names, **options,
                                                verification_evidence={**evidence, "inventory_sha256": "0" * 64})
        published = advance_pa_family_cache_transaction(cache, document, names, **options,
                                                       verification_evidence=evidence)
        self.assertEqual((published.status, published.action_required), ("published", "complete"))
        self.assertFalse(published.build_directory.exists())
        self.assertFalse(published.scratch_directory.exists())
        manifest = validate_pa_family_cache_generation(published.generation_directory, expected_filenames=names)
        self.assertEqual({row["name"] for row in manifest["files"]}, set(names))
        self.assertEqual(manifest["identity"], document)
        self.assertEqual(self._ledger_entry(artifacts, published.cache_key)["status"], "ready")
        transaction = json.loads((published.transaction_directory / "transaction.json").read_text())
        self.assertIsNone(transaction.get("response_receipt"))
        with patch.object(pa_family_cache, "file_sha256", side_effect=AssertionError("healthy hit must not hash PA")):
            probe = probe_pa_family_cache(cache, document, expected_filenames=names)
            replay = advance_pa_family_cache_transaction(cache, document, names, **options)
        self.assertEqual(probe.disposition, CacheDisposition.HIT)
        self.assertEqual(replay.generation_directory, published.generation_directory)
        destination = self.root / "three-field-consumer"
        with self.assertRaisesRegex(PAFamilyCacheError, "requires an active protection lease id"):
            materialize_pa_family_cache(published.generation_directory, destination, expected_filenames=names)
        self.assertFalse(destination.exists())
        capacity_protection.create_capacity_protection_lease(
            artifacts, lease_id="working-field-consumer", owner="fixture-consumer", ttl_seconds=300,
            protected_cache_keys=[published.cache_key])
        try:
            for name in names:
                self.assertFalse((published.generation_directory / name).stat().st_mode & stat.S_IWUSR)
            for target in (destination, self.root / "second-consumer"):
                materialized = materialize_pa_family_cache(published.generation_directory, target,
                    expected_filenames=names, capacity_lease_id="working-field-consumer", capacity_lease_owner="fixture-consumer")
                self.assertEqual(materialized.files, tuple(manifest["files"]))
                self.assertEqual({name: (target / name).read_bytes() for name in names}, payloads)
            with self.assertRaisesRegex(ValueError, "active capacity protection lease"):
                capacity_ledger.mark_retirement_pending(artifacts, path=cache / published.cache_key)
        finally:
            capacity_protection.delete_capacity_protection_lease(artifacts, lease_id="working-field-consumer")

    def test_publish_hit_validate_and_materialize_with_hashes(self) -> None:
        first = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        self.assertEqual(first.disposition, CacheDisposition.PUBLISHED)
        self.assertFalse((first.generation_directory / "field.pa1").stat().st_mode & stat.S_IWUSR)
        self.assertFalse((first.generation_directory / "cache_manifest.json").stat().st_mode & stat.S_IWUSR)
        self.assertEqual(probe_pa_family_cache(self.cache, identity(), expected_filenames=self.names).disposition, CacheDisposition.HIT)
        manifest = validate_pa_family_cache_generation(first.generation_directory, expected_filenames=self.names)
        self.assertEqual(manifest["files"], pa_family_inventory(self.source, self.names))
        second = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        self.assertEqual(second.disposition, CacheDisposition.HIT)
        local = materialize_pa_family_cache(first.generation_directory, self.root / "run" / "simion", expected_filenames=self.names)
        self.assertEqual(local.files, tuple(manifest["files"]))
        self.assertEqual(pa_family_inventory(local.destination_directory, self.names), manifest["files"])
        self.assertTrue((local.destination_directory / "field.pa1").stat().st_mode & stat.S_IWUSR)

    def _land_transaction_members(
        self,
        transaction: pa_family_cache.TransactionAdvance,
        names: tuple[str, ...],
    ) -> None:
        transaction.scratch_directory.mkdir(exist_ok=True)
        for name in names:
            temporary = transaction.scratch_directory / f"{name}.partial"
            temporary.write_bytes((self.source / name).read_bytes())
            temporary.replace(transaction.build_directory / name)

    def test_transaction_build_verify_publish_is_idempotent(self) -> None:
        first = advance_pa_family_cache_transaction(self.cache, identity(), self.names)
        key = canonical_pa_family_cache_key(identity())
        self.assertEqual(first.status, "building")
        self.assertEqual(first.action_required, "build")
        self.assertEqual(
            first.transaction_directory,
            self.cache / ".transactions" / key,
        )
        self.assertEqual(first.missing_files, self.names)

        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(self.cache, identity(), self.names)
        self.assertEqual(prepared.status, "building")
        self.assertEqual(prepared.action_required, "verify")
        self.assertIsNotNone(prepared.inventory_sha256)
        for name in self.names:
            self.assertFalse((prepared.build_directory / name).stat().st_mode & stat.S_IWUSR)

        published = advance_pa_family_cache_transaction(
            self.cache,
            identity(),
            self.names,
            verification_evidence=self._verification_evidence(prepared),
        )
        self.assertEqual(published.status, "published")
        self.assertEqual(published.action_required, "complete")
        self.assertFalse(published.build_directory.exists())
        self.assertFalse(published.scratch_directory.exists())
        self.assertIsNotNone(published.generation_directory)
        validate_pa_family_cache_generation(
            published.generation_directory,
            expected_filenames=self.names,
        )
        transaction = json.loads(
            (published.transaction_directory / "transaction.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(transaction["status"], "published")
        self.assertIsNotNone(transaction["verification"])
        self.assertFalse(
            any(
                path.name.endswith(".prepared_inventory.json")
                for path in published.transaction_directory.iterdir()
            )
        )

        repeated = advance_pa_family_cache_transaction(
            self.cache, identity(), self.names
        )
        self.assertEqual(repeated.status, "published")
        self.assertEqual(repeated.generation_sha256, published.generation_sha256)

    def test_transaction_partial_build_resumes_only_missing_members(self) -> None:
        first = advance_pa_family_cache_transaction(self.cache, identity(), self.names)
        self._land_transaction_members(first, (self.names[0],))
        partial = advance_pa_family_cache_transaction(self.cache, identity(), self.names)
        self.assertEqual(partial.action_required, "build")
        self.assertEqual(partial.missing_files, self.names[1:])
        self.assertTrue((partial.build_directory / self.names[0]).is_file())

        self._land_transaction_members(partial, self.names[1:])
        prepared = advance_pa_family_cache_transaction(self.cache, identity(), self.names)
        self.assertEqual(prepared.action_required, "verify")
        self.assertEqual(
            list(prepared.transaction_directory.glob("transaction.json")),
            [prepared.transaction_directory / "transaction.json"],
        )

    def _sealed_mismatch_fixture(self):
        names = (*self.names, "receipt.json")
        build = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        self._land_transaction_members(build, self.names)
        expected = {"name": self.names[1], "bytes": 4, "sha256": "A" * 64}
        (build.build_directory / "receipt.json").write_text(json.dumps({"source": expected}), encoding="utf-8")
        sealed = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        document = json.loads((sealed.transaction_directory / "transaction.json").read_text())
        records = {item["name"]: item for item in document["files"]}
        request = {
            "schema_version": 1, "role": "simion_pa_family_member_recovery",
            "cache_key": sealed.cache_key, "owner": document["owner"],
            "inventory_sha256": sealed.inventory_sha256, "receipt": records["receipt.json"],
            "members": [{"sealed": records[self.names[1]], "expected": expected, "receipt_record_path": ["source"]}],
        }
        return names, sealed, request

    def test_member_recovery_preserves_other_members_and_replays_without_rehash(self) -> None:
        names, sealed, request = self._sealed_mismatch_fixture()
        kept = {name: (sealed.build_directory / name).stat() for name in (self.names[0], self.names[2])}
        with patch.object(pa_family_cache, "inventory_named_files", side_effect=AssertionError("no PA rehash")):
            recovered = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, producer_run_config=self.producer_run_config, member_recovery=request)
        self.assertEqual(set(recovered.missing_files), {self.names[1], "receipt.json"})
        self.assertIsNone(recovered.inventory_sha256)
        for name, before in kept.items():
            after = (recovered.build_directory / name).stat()
            self.assertEqual((before.st_ino, before.st_size, before.st_mtime_ns), (after.st_ino, after.st_size, after.st_mtime_ns))
            self.assertFalse(after.st_mode & stat.S_IWRITE)
        self._land_transaction_members(recovered, (self.names[1],))
        repeated = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, producer_run_config=self.producer_run_config, member_recovery=request)
        self.assertEqual(repeated.missing_files, ("receipt.json",))
        (repeated.build_directory / "receipt.json").write_text("{}", encoding="utf-8")
        resealed = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        self.assertNotEqual(resealed.inventory_sha256, sealed.inventory_sha256)
        published = advance_pa_family_cache_transaction(
            self.cache, identity(), names, verification_evidence=self._verification_evidence(resealed), recovery_policy="none",
        )
        self.assertEqual(published.action_required, "complete")

    def _retained_inventory_fixture(self):
        names, sealed, recovery = self._sealed_mismatch_fixture()
        building = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, producer_run_config=self.producer_run_config, member_recovery=recovery)
        self._land_transaction_members(building, (self.names[1],))
        (building.build_directory / "receipt.json").write_text("{}", encoding="utf-8")
        retained = (self.names[0], self.names[2])
        real_inventory = pa_family_cache.inventory_named_files

        def stale_inventory(root, filenames, **options):
            return [{**record, "sha256": "D" * 64} if record["name"] in retained else record
                    for record in real_inventory(root, filenames, **options)]

        with patch.object(pa_family_cache, "inventory_named_files", side_effect=stale_inventory):
            sealed = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        document = json.loads((sealed.transaction_directory / "transaction.json").read_text())
        request = {"schema_version": 1, "cache_key": sealed.cache_key, "owner": document["owner"],
                   "inventory_sha256": sealed.inventory_sha256, "names": list(retained)}
        return names, sealed, request, document

    def _published_correction_fixture(self):
        names, sealed, request, _ = self._retained_inventory_fixture()
        request["names"] = [self.names[2]]
        sealed = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, retained_inventory_recovery=request)
        # Simulate a publication from the historical owner, before its retained-member gate.
        with patch.object(pa_family_cache, "_validate_retained_member_inventory"):
            published = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner,
                verification_evidence=self._verification_evidence(sealed), recovery_policy="none")
        document = json.loads((published.transaction_directory / "transaction.json").read_text())
        request = {"schema_version": 1, "cache_key": published.cache_key, "owner": document["owner"],
                   "generation_sha256": published.generation_sha256, "inventory_sha256": published.inventory_sha256,
                   "member_name": self.names[0], "sealed_sha256": "D" * 64,
                   "retained_sha256": next(item["sha256"] for item in document["member_recovery"]["files"] if item["name"] == self.names[0])}
        return names, published, request, document

    def test_publication_metadata_correction_moves_without_copy_and_preserves_evidence(self):
        names, old, request, original = self._published_correction_fixture()
        before = pa_family_cache._correction_metadata(old.generation_directory, names)
        with (patch.object(pa_family_cache, "snapshot_immutable_file", side_effect=AssertionError("no copy")),
              patch.object(pa_family_cache, "inventory_named_files", side_effect=AssertionError("no bank scan")),
              patch.object(pa_family_cache, "file_sha256_unbuffered", wraps=pa_family_cache.file_sha256_unbuffered) as hashed):
            result = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, publication_metadata_correction=request)
        self.assertEqual(hashed.call_count, 1)
        self.assertEqual(Path(hashed.call_args.args[0]).name, self.names[0])
        self.assertFalse(old.generation_directory.exists())
        self.assertEqual(before, pa_family_cache._correction_metadata(result.generation_directory, names))
        doc = json.loads((result.transaction_directory / "transaction.json").read_text())
        self.assertEqual(doc["verification"], original["verification"])
        self.assertEqual(doc["retained_inventory_recovery"], original["retained_inventory_recovery"])
        receipt = json.loads(result.publication_metadata_correction_receipt.read_text())
        self.assertTrue(receipt["no_solver_rerun"])
        self.assertEqual(receipt["corrected_inventory_sha256"], result.inventory_sha256)
        self.assertEqual(validate_pa_family_cache_generation(result.generation_directory)["predecessor_generation_sha256"], old.generation_sha256)
        with patch.object(pa_family_cache, "file_sha256_unbuffered", side_effect=AssertionError("no repeated PA hash")):
            replay = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, publication_metadata_correction=request)
            ordinary = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        self.assertEqual(replay, ordinary)

    def test_publication_metadata_correction_rejects_false_evidence_and_leaves_source(self):
        names, old, request, _ = self._published_correction_fixture()
        for field, value in (("owner", "other"), ("retained_sha256", "A" * 64), ("member_name", "../field.pa#")):
            with self.subTest(field=field), self.assertRaises((PAFamilyCacheError, ValueError)):
                advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, publication_metadata_correction={**request, field: value})
            self.assertTrue(old.generation_directory.is_dir())
            doc = json.loads((old.transaction_directory / "transaction.json").read_text())
            self.assertNotIn("publication_metadata_correction", doc)
        with patch.object(pa_family_cache, "file_sha256_unbuffered", return_value="F" * 64), self.assertRaisesRegex(PAFamilyCacheError, "unchanged retained"):
            advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, publication_metadata_correction=request)

    def test_publication_metadata_correction_rejects_changed_verification(self):
        names, old, request, original = self._published_correction_fixture()
        Path(original["verification"]["verification_output_path"]).write_text("changed")
        with self.assertRaisesRegex(PAFamilyCacheError, "verification_output_path"):
            advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, publication_metadata_correction=request)
        self.assertTrue(old.generation_directory.exists())

    def test_publication_metadata_correction_capacity_consumers_and_retirement(self):
        artifacts, self.cache = self._artifact_cache()
        names, old, request, _ = self._published_correction_fixture()
        capacity_protection.create_capacity_protection_lease(artifacts, lease_id="workflow", owner="fixture workflow",
            ttl_seconds=600, protected_cache_keys=[old.cache_key], committed_new_bytes=0)
        request.update(capacity_lease_id="workflow", capacity_lease_owner="fixture workflow")
        capacity_protection.create_capacity_protection_lease(artifacts, lease_id="other", owner="other consumer",
            ttl_seconds=600, protected_cache_keys=[old.cache_key], committed_new_bytes=0)
        with patch.object(pa_family_cache, "file_sha256_unbuffered", side_effect=AssertionError("early reject required")), self.assertRaisesRegex(PAFamilyCacheError, "another active consumer"):
            advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, publication_metadata_correction=request)
        self.assertNotIn("publication_metadata_correction", json.loads((old.transaction_directory / "transaction.json").read_text()))
        capacity_protection.delete_capacity_protection_lease(artifacts, lease_id="other")
        result = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, publication_metadata_correction=request)
        entries = [entry for entry in capacity_ledger.load_capacity_ledger(artifacts)["objects"] if entry["class"] == "published_cache"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["identity"], result.generation_sha256)
        self.assertEqual(entries[0]["bytes"], self._tree_bytes(self.cache / result.cache_key))
        capacity_protection.delete_capacity_protection_lease(artifacts, lease_id="workflow")
        retired = approve_pa_family_cache_retirement(self.cache, result.cache_key, result.generation_sha256)
        self.assertEqual(retired.status, "retired")
        pa_family_cache._load_transaction_by_key(result.transaction_directory / "transaction.json", result.cache_key)

    def test_publication_metadata_correction_preserves_pin(self):
        artifacts, self.cache = self._artifact_cache()
        names, old, request, document = self._published_correction_fixture()
        document["published_pin_reason"] = "fixture protected bank"
        pa_family_cache._write_transaction(old.transaction_directory / "transaction.json", document)
        result = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, publication_metadata_correction=request,
            published_pin_reason=document["published_pin_reason"])
        entry = next(entry for entry in capacity_ledger.load_capacity_ledger(artifacts)["objects"] if entry["class"] == "published_cache")
        self.assertTrue(entry["pin"])
        self.assertEqual(entry["pin_reason"], document["published_pin_reason"])
        self.assertEqual(entry["identity"], result.generation_sha256)

    def test_publication_metadata_correction_replays_each_directory_rename_boundary(self):
        for target in ("payload", "original_manifest.json", "successor", "current_generation.json", "receipt.json"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as folder:
                self.cache = Path(folder) / "cache"
                names, old, request, _ = self._published_correction_fixture()
                real_replace = pa_family_cache.os.replace
                fired = False
                def interrupt(source, destination):
                    nonlocal fired
                    real_replace(source, destination)
                    dest = Path(destination)
                    chosen = dest.name == target or (target == "successor" and dest.parent.name == "generations")
                    if chosen and not fired:
                        fired = True
                        raise OSError("injected interruption after rename")
                with patch.object(pa_family_cache.os, "replace", side_effect=interrupt), self.assertRaises(OSError):
                    advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, publication_metadata_correction=request)
                self.assertTrue(fired)
                self.assertEqual(probe_pa_family_cache(self.cache, identity()).disposition, CacheDisposition.CORRUPT)
                with patch.object(pa_family_cache, "file_sha256_unbuffered", side_effect=AssertionError("no repeated hash")):
                    done = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, producer_run_config=self.producer_run_config)
                self.assertEqual(done.action_required, "complete")
                validate_pa_family_cache_generation(done.generation_directory)

    def test_retained_inventory_recovery_changes_only_records_and_replays_without_reads(self):
        names, sealed, request, original = self._retained_inventory_fixture()
        before = {name: ((sealed.build_directory / name).read_bytes(), (sealed.build_directory / name).stat()) for name in names}
        with (patch.object(pa_family_cache, "inventory_named_files", side_effect=AssertionError("no bank scan")),
              patch.object(pa_family_cache, "snapshot_immutable_file", wraps=pa_family_cache.snapshot_immutable_file) as snapshot):
            result = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, retained_inventory_recovery=request)
        self.assertEqual(result.action_required, "verify")
        self.assertEqual([Path(call.args[0]).name for call in snapshot.call_args_list], sorted(request["names"]))
        self.assertNotEqual(result.inventory_sha256, sealed.inventory_sha256)
        document = json.loads((sealed.transaction_directory / "transaction.json").read_text())
        old = {item["name"]: item for item in original["member_recovery"]["files"]}
        for record in document["files"]:
            expected = old[record["name"]] if record["name"] in request["names"] else next(item for item in original["files"] if item["name"] == record["name"])
            self.assertEqual(record, expected)
        for name, (data, metadata) in before.items():
            path = sealed.build_directory / name
            self.assertEqual(path.read_bytes(), data)
            after = path.stat()
            self.assertEqual((after.st_ino, after.st_mtime_ns, after.st_mode), (metadata.st_ino, metadata.st_mtime_ns, metadata.st_mode))
        with patch.object(pa_family_cache, "snapshot_immutable_file", side_effect=AssertionError("no replay copy")):
            replay = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, retained_inventory_recovery=request)
        self.assertEqual(replay.inventory_sha256, result.inventory_sha256)
        published = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, verification_evidence=self._verification_evidence(result), recovery_policy="none")
        self.assertEqual(published.status, "published")

    def test_retained_inventory_recovery_snapshot_failure_does_not_partially_change_inventory(self):
        names, sealed, request, original = self._retained_inventory_fixture()
        real_snapshot = pa_family_cache.snapshot_immutable_file
        calls = 0

        def fail_second(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError("persistent mismatch")
            return real_snapshot(*args)

        with patch.object(pa_family_cache, "snapshot_immutable_file", side_effect=fail_second):
            with self.assertRaisesRegex(PAFamilyCacheError, "snapshot verification failed"):
                advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, retained_inventory_recovery=request)
        document = json.loads((sealed.transaction_directory / "transaction.json").read_text())
        self.assertEqual(document["files"], original["files"])
        self.assertEqual(document["inventory_sha256"], original["inventory_sha256"])
        self.assertNotIn("retained_inventory_recovery", document)
        self.assertEqual(document["status"], "building")
        self.assertIsNone(document["verification"])
        self.assertFalse((sealed.transaction_directory / "recovery-scratch").exists())

    def test_retained_raw_mismatch_blocks_verification_and_prepared_publication_without_reads(self):
        names, sealed, _, original = self._retained_inventory_fixture()
        old = {item["name"]: item for item in original["member_recovery"]["files"]}
        # A response receipt cannot bind the raw PA. Make raw the sole missed
        # inventory difference, as in the real recovered-bank failure.
        original["files"] = [old[item["name"]] if item["name"] == self.names[2] else item for item in original["files"]]
        original["inventory_sha256"] = pa_family_cache.canonical_json_sha256(original["files"])
        transaction_path = sealed.transaction_directory / "transaction.json"
        pa_family_cache._write_transaction(transaction_path, original)
        evidence = dict(self._verification_evidence(sealed), inventory_sha256=original["inventory_sha256"])
        with (patch.object(pa_family_cache, "inventory_named_files", side_effect=AssertionError("no PA scan")),
              patch.object(pa_family_cache, "snapshot_immutable_file", side_effect=AssertionError("no PA snapshot"))):
            with self.assertRaisesRegex(PAFamilyCacheError, r"retained member inventory.*field\.pa#"):
                advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, verification_evidence=evidence)
            rejected = json.loads(transaction_path.read_text())
            self.assertEqual(rejected["status"], "building")
            self.assertIsNone(rejected["verification"])
            # A crash-resumed older prepared transaction must pass the same gate.
            pa_family_cache._write_transaction(transaction_path, dict(original, status="prepared", verification=evidence))
            with self.assertRaisesRegex(PAFamilyCacheError, r"retained member inventory.*field\.pa#"):
                advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        self.assertFalse((self.cache / sealed.cache_key / "current_generation.json").exists())

    def test_new_build_after_retirement_does_not_inherit_prior_member_recovery_promise(self):
        _, sealed, _, document = self._retained_inventory_fixture()
        # Exercise the owner reset with no heavy payload; the retired build's
        # disposal must already have finished before this existing API runs.
        root = self.root / "retired-fixture"
        root.mkdir()
        path = root / "transaction.json"
        document["status"] = "retired"
        pa_family_cache._restart_retired_transaction(path, root, document, published_pin_reason=None)
        self.assertNotIn("member_recovery", document)
        self.assertEqual(document["files"], [])
        pa_family_cache._validate_retained_member_inventory(document)

    def test_retained_inventory_recovery_rejects_unbound_rebuilt_and_unchanged_members(self):
        names, sealed, request, original = self._retained_inventory_fixture()
        cases = [dict(request, owner="foreign"), dict(request, cache_key="F" * 64),
                 dict(request, inventory_sha256="F" * 64), dict(request, names=[self.names[1]]),
                 dict(request, names=["receipt.json"]), dict(request, names=["missing.pa"]),
                 dict(request, names=[self.names[0], self.names[0]]), dict(request, names=[]),
                 dict(request, records=[])]
        with patch.object(pa_family_cache, "snapshot_immutable_file", side_effect=AssertionError("invalid request copied PA")):
            for invalid in cases:
                with self.subTest(invalid=invalid), self.assertRaises(PAFamilyCacheError):
                    advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, retained_inventory_recovery=invalid)
        old = {item["name"]: item for item in original["member_recovery"]["files"]}
        unchanged = dict(original)
        unchanged["files"] = [old[item["name"]] if item["name"] == self.names[0] else item for item in original["files"]]
        unchanged["inventory_sha256"] = pa_family_cache.canonical_json_sha256(unchanged["files"])
        pa_family_cache._write_transaction(sealed.transaction_directory / "transaction.json", unchanged)
        with self.assertRaisesRegex(PAFamilyCacheError, "not a retained mismatch"):
            advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner,
                retained_inventory_recovery=dict(request, inventory_sha256=unchanged["inventory_sha256"]))

    def test_retained_inventory_recovery_requires_building_without_verification(self):
        names, sealed, request, original = self._retained_inventory_fixture()
        for status, verification, generation in (("prepared", None, None), ("published", None, None),
                                                ("building", {}, None), ("building", None, "F" * 64)):
            with self.subTest(status=status, verification=verification, generation=generation):
                document = dict(original, status=status, verification=verification, generation_sha256=generation)
                pa_family_cache._write_transaction(sealed.transaction_directory / "transaction.json", document)
                with self.assertRaisesRegex(PAFamilyCacheError, "requires building"):
                    advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, retained_inventory_recovery=request)
        pa_family_cache._write_transaction(sealed.transaction_directory / "transaction.json", original)
        with self.assertRaisesRegex(PAFamilyCacheError, "cannot accompany"):
            advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, retained_inventory_recovery=request, verification_evidence={})

    def test_retained_inventory_recovery_cli(self):
        names, sealed, request, _ = self._retained_inventory_fixture()
        request_path = self.root / "retained.json"
        identity_path = self.root / "identity.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        identity_path.write_text(json.dumps(identity()), encoding="utf-8")
        output = StringIO()
        with redirect_stdout(output):
            main(["--action", "advance-transaction", "--cache-root", str(self.cache),
                  "--identity", str(identity_path), "--filenames", ",".join(names),
                  "--retained-inventory-recovery", str(request_path)])
        result = json.loads(output.getvalue())
        self.assertEqual(result["action_required"], "verify")
        self.assertNotEqual(result["inventory_sha256"], sealed.inventory_sha256)

    def test_member_recovery_resumes_after_partial_deletion(self) -> None:
        names, sealed, request = self._sealed_mismatch_fixture()
        original_unlink = Path.unlink
        target = sealed.build_directory / "receipt.json"
        def interrupt_receipt(path, *args, **kwargs):
            if path == target:
                raise OSError("fixture deletion interruption")
            return original_unlink(path, *args, **kwargs)
        with patch.object(Path, "unlink", interrupt_receipt):
            with self.assertRaisesRegex(OSError, "deletion interruption"):
                advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, producer_run_config=self.producer_run_config, member_recovery=request)
        self.assertFalse((sealed.build_directory / self.names[1]).exists())
        document = json.loads((sealed.transaction_directory / "transaction.json").read_text())
        self.assertFalse(document["member_recovery"]["complete"])
        self.assertEqual(document["files"], [])
        recovered = advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        self.assertEqual(set(recovered.missing_files), {self.names[1], "receipt.json"})

    def test_member_recovery_rejects_unbound_or_healthy_members_before_deletion(self) -> None:
        names, sealed, request = self._sealed_mismatch_fixture()
        changes = [
            lambda value: value.update(owner="wrong owner"),
            lambda value: value.update(inventory_sha256="F" * 64),
            lambda value: value["members"][0].update(expected=value["members"][0]["sealed"]),
            lambda value: value["members"][0]["expected"].update(sha256="B" * 64),
            lambda value: value["members"][0]["sealed"].update(name="../outside.pa"),
            lambda value: value["members"].append(value["members"][0]),
            lambda value: value["receipt"].update(sha256="F" * 64),
        ]
        before = {path.name: path.read_bytes() for path in sealed.build_directory.iterdir()}
        for change in changes:
            invalid = json.loads(json.dumps(request))
            change(invalid)
            with self.subTest(request=invalid), self.assertRaises(ValueError):
                advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, producer_run_config=self.producer_run_config, member_recovery=invalid)
            self.assertEqual(before, {path.name: path.read_bytes() for path in sealed.build_directory.iterdir()})

    def test_member_recovery_rejects_verification_or_published_state(self) -> None:
        names, sealed, request = self._sealed_mismatch_fixture()
        evidence = self._verification_evidence(sealed)
        with self.assertRaisesRegex(PAFamilyCacheError, "cannot accompany"):
            advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, producer_run_config=self.producer_run_config, member_recovery=request, verification_evidence=evidence)
        transaction_path = sealed.transaction_directory / "transaction.json"
        document = json.loads(transaction_path.read_text())
        document["verification"] = evidence
        pa_family_cache._write_transaction(transaction_path, document)
        with self.assertRaisesRegex(PAFamilyCacheError, "requires building"):
            advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, producer_run_config=self.producer_run_config, member_recovery=request)
        document["status"] = "building"
        document["verification"] = None
        document["generation_sha256"] = "E" * 64
        pa_family_cache._write_transaction(transaction_path, document)
        with self.assertRaisesRegex(PAFamilyCacheError, "requires building"):
            advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, producer_run_config=self.producer_run_config, member_recovery=request)

        document["status"] = "prepared"
        document["generation_sha256"] = None
        pa_family_cache._write_transaction(transaction_path, document)
        with self.assertRaisesRegex(PAFamilyCacheError, "requires building"):
            advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, producer_run_config=self.producer_run_config, member_recovery=request)

    def test_member_recovery_cli_and_pending_request_conflict(self) -> None:
        names, sealed, request = self._sealed_mismatch_fixture()
        request_path = self.root / "member_recovery.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        identity_path = self.root / "identity.json"
        identity_path.write_text(json.dumps(identity()), encoding="utf-8")
        original_unlink = Path.unlink
        def interrupt_member(path, *args, **kwargs):
            if path == sealed.build_directory / self.names[1]:
                raise OSError("fixture before deletion")
            return original_unlink(path, *args, **kwargs)
        with patch.object(Path, "unlink", interrupt_member), self.assertRaisesRegex(OSError, "before deletion"):
            advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, producer_run_config=self.producer_run_config, member_recovery=request)
        conflicting = json.loads(json.dumps(request))
        conflicting["owner"] = "not owner"
        with self.assertRaisesRegex(PAFamilyCacheError, "pending request"):
            advance_pa_family_cache_transaction(self.cache, identity(), names, owner=self.artifact_owner, producer_run_config=self.producer_run_config, member_recovery=conflicting)
        self.assertTrue((sealed.build_directory / self.names[1]).exists())
        common = ["--cache-root", str(self.cache), "--identity", str(identity_path),
                  "--filenames", ",".join(names), "--member-recovery", str(request_path)]
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--action", "advance-transaction", *common]), 0)
        self.assertEqual(set(json.loads(output.getvalue())["missing_files"]), {self.names[1], "receipt.json"})

    def test_member_recovery_requires_existing_transaction_and_capacity_ledger(self) -> None:
        with self.assertRaisesRegex(PAFamilyCacheError, "existing transaction"):
            advance_pa_family_cache_transaction(self.cache, identity(), self.names, member_recovery={})
        _, cache = self._artifact_cache(initialize_ledger=False)
        with self.assertRaisesRegex(PAFamilyCacheError, "calibrated capacity ledger"):
            advance_pa_family_cache_transaction(cache, identity(), self.names, owner=self.artifact_owner, producer_run_config=self.producer_run_config, member_recovery={})

    def test_transaction_recovers_hard_kill_during_member_sealing(self) -> None:
        first = advance_pa_family_cache_transaction(self.cache, identity(), self.names)
        self._land_transaction_members(first, self.names)
        pa_family_cache._set_file_read_only(first.build_directory / self.names[0])
        prepared = advance_pa_family_cache_transaction(self.cache, identity(), self.names)
        self.assertEqual(prepared.action_required, "verify")
        self.assertIsNotNone(prepared.inventory_sha256)

    def test_transaction_pointer_failure_resumes_without_rebuild(self) -> None:
        first = advance_pa_family_cache_transaction(self.cache, identity(), self.names)
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(self.cache, identity(), self.names)
        evidence = self._verification_evidence(prepared)
        original = pa_family_cache._publish_pointer
        with patch.object(
            pa_family_cache,
            "_publish_pointer",
            side_effect=OSError("fixture pointer interruption"),
        ):
            with self.assertRaisesRegex(OSError, "pointer interruption"):
                advance_pa_family_cache_transaction(
                    self.cache,
                    identity(),
                    self.names,
                    verification_evidence=evidence,
                )
        transaction = json.loads(
            (prepared.transaction_directory / "transaction.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(transaction["status"], "published")
        self.assertIn("pointer interruption", transaction["last_error"])
        self.assertFalse(prepared.build_directory.exists())

        with patch.object(pa_family_cache, "_publish_pointer", wraps=original):
            resumed = advance_pa_family_cache_transaction(
                self.cache, identity(), self.names
            )
        self.assertEqual(resumed.status, "published")
        self.assertEqual(resumed.action_required, "complete")

    def test_competing_hit_hard_kill_after_duplicate_removal_resumes(self) -> None:
        first = advance_pa_family_cache_transaction(self.cache, identity(), self.names)
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(self.cache, identity(), self.names)
        publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        original_remove = pa_family_cache._remove_tree_writable

        def remove_then_crash(path: Path) -> None:
            original_remove(path)
            if Path(path) == prepared.build_directory:
                raise SystemExit("fixture crash after duplicate removal")

        with patch.object(
            pa_family_cache, "_remove_tree_writable", side_effect=remove_then_crash
        ):
            with self.assertRaisesRegex(SystemExit, "duplicate removal"):
                advance_pa_family_cache_transaction(
                    self.cache,
                    identity(),
                    self.names,
                    verification_evidence=self._verification_evidence(prepared),
                )
        transaction = json.loads(
            (prepared.transaction_directory / "transaction.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(transaction["status"], "prepared")
        self.assertIsNotNone(transaction["generation_sha256"])
        self.assertFalse(prepared.build_directory.exists())
        resumed = advance_pa_family_cache_transaction(
            self.cache, identity(), self.names
        )
        self.assertEqual(resumed.status, "published")
        self.assertEqual(resumed.action_required, "complete")

    def test_transaction_xor_stream_rejects_same_size_tamper(self) -> None:
        first = advance_pa_family_cache_transaction(self.cache, identity(), self.names)
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(self.cache, identity(), self.names)
        target = prepared.build_directory / self.names[1]
        pa_family_cache._set_file_writable(target)
        target.write_bytes(b"Z" * target.stat().st_size)
        pa_family_cache._set_file_read_only(target)
        with self.assertRaisesRegex(PAFamilyCacheError, "redundancy read differs"):
            advance_pa_family_cache_transaction(
                self.cache,
                identity(),
                self.names,
                verification_evidence=self._verification_evidence(prepared),
            )
        transaction = json.loads(
            (prepared.transaction_directory / "transaction.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(transaction["status"], "prepared")
        self.assertIsNotNone(transaction["last_error"])

    def test_transaction_xor_uses_parity_as_its_single_full_publish_read(self) -> None:
        first = advance_pa_family_cache_transaction(self.cache, identity(), self.names)
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(self.cache, identity(), self.names)
        with patch.object(
            pa_family_cache,
            "inventory_named_files",
            side_effect=AssertionError("xor transaction must not prehash again"),
        ):
            published = advance_pa_family_cache_transaction(
                self.cache,
                identity(),
                self.names,
                verification_evidence=self._verification_evidence(prepared),
            )
        self.assertEqual(published.status, "published")

    def test_transaction_seals_exclusive_payload_with_one_inventory(self) -> None:
        first = advance_pa_family_cache_transaction(self.cache, identity(), self.names)
        self._land_transaction_members(first, self.names)
        with patch.object(
            pa_family_cache,
            "inventory_named_files",
            wraps=pa_family_cache.inventory_named_files,
        ) as inventory, patch.object(
            pa_family_cache,
            "_flush_writable_source",
            wraps=pa_family_cache._flush_writable_source,
        ) as flushed:
            prepared = advance_pa_family_cache_transaction(
                self.cache, identity(), self.names
            )
        self.assertEqual(prepared.action_required, "verify")
        self.assertEqual(inventory.call_count, 1)
        payload_flushes = [
            call for call in flushed.call_args_list
            if Path(call.args[0]).parent == first.build_directory
        ]
        self.assertEqual(len(payload_flushes), len(self.names))

    def test_reconstructible_transaction_does_not_rehash_after_final_inventory(self) -> None:
        first = advance_pa_family_cache_transaction(
            self.cache, identity(), self.names, recovery_policy="none"
        )
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(
            self.cache, identity(), self.names, recovery_policy="none"
        )
        with patch.object(
            pa_family_cache,
            "inventory_named_files",
            side_effect=AssertionError("sealed reconstructible payload must not be rehashed"),
        ):
            published = advance_pa_family_cache_transaction(
                self.cache,
                identity(),
                self.names,
                verification_evidence=self._verification_evidence(prepared),
                recovery_policy="none",
            )
        self.assertEqual(published.status, "published")

    def test_reconstructible_transaction_rejects_length_change_after_inventory(self) -> None:
        first = advance_pa_family_cache_transaction(
            self.cache, identity(), self.names, recovery_policy="none"
        )
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(
            self.cache, identity(), self.names, recovery_policy="none"
        )
        target = prepared.build_directory / self.names[0]
        pa_family_cache._set_file_writable(target)
        target.write_bytes(target.read_bytes() + b"changed")
        pa_family_cache._set_file_read_only(target)
        with self.assertRaisesRegex(PAFamilyCacheError, "length differs"):
            advance_pa_family_cache_transaction(
                self.cache,
                identity(),
                self.names,
                verification_evidence=self._verification_evidence(prepared),
                recovery_policy="none",
            )

    def test_transaction_retry_cleans_only_its_deterministic_recovery_scratch(self) -> None:
        first = advance_pa_family_cache_transaction(self.cache, identity(), self.names)
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(self.cache, identity(), self.names)
        recovery = prepared.transaction_directory / "recovery-scratch"
        recovery.mkdir()
        (recovery / "hard-kill.partial").write_bytes(b"orphan")
        published = advance_pa_family_cache_transaction(
            self.cache,
            identity(),
            self.names,
            verification_evidence=self._verification_evidence(prepared),
        )
        self.assertEqual(published.status, "published")
        self.assertFalse(recovery.exists())

    def test_transaction_rejects_unowned_entries_without_deleting_them(self) -> None:
        first = advance_pa_family_cache_transaction(self.cache, identity(), self.names)
        unknown = first.transaction_directory / "other-token"
        unknown.mkdir()
        (unknown / "payload").write_bytes(b"do not delete")
        with self.assertRaisesRegex(PAFamilyCacheError, "unknown entries"):
            advance_pa_family_cache_transaction(self.cache, identity(), self.names)
        self.assertEqual((unknown / "payload").read_bytes(), b"do not delete")

    def test_same_key_concurrent_transaction_completion_is_one_generation(self) -> None:
        first = advance_pa_family_cache_transaction(self.cache, identity(), self.names)
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(self.cache, identity(), self.names)
        evidence = self._verification_evidence(prepared)

        def finish(_: int) -> pa_family_cache.TransactionAdvance:
            return advance_pa_family_cache_transaction(
                self.cache,
                identity(),
                self.names,
                verification_evidence=evidence,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(finish, range(2)))
        self.assertEqual({item.status for item in results}, {"published"})
        self.assertEqual(len({item.generation_sha256 for item in results}), 1)
        generations = (
            self.cache / prepared.cache_key / "generations"
        ).iterdir()
        self.assertEqual(len(list(generations)), 1)

    def test_transaction_publication_failure_accounts_landed_key_and_replays(self) -> None:
        artifacts, cache = self._artifact_cache()
        reason = "fixture retained publication"
        options = dict(owner=self.artifact_owner, published_pin_reason=reason)
        first = advance_pa_family_cache_transaction(
            cache, identity(), self.names, producer_run_config=self.producer_run_config, **options
        )
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(cache, identity(), self.names, **options)
        key_root = cache / first.cache_key
        _, key_relative = capacity_ledger.capacity_object_path(artifacts, key_root)
        _, stage_relative = capacity_ledger.capacity_object_path(artifacts, first.transaction_directory)
        original_mkdir = Path.mkdir
        original_replace = pa_family_cache.os.replace
        before_move = []
        failure = OSError("fixture generations mkdir failed after recovery move")

        def observe_replace(source, destination):
            if Path(source).name == "recovery-scratch":
                ledger = capacity_ledger.load_capacity_ledger(artifacts)
                before_move.append(next((dict(row) for row in ledger["objects"]
                                         if row["path"] == key_relative), None))
                leases = capacity_protection.load_capacity_protection_leases(artifacts)
                self.assertIn(first.cache_key.lower(), leases["protected_cache_keys"])
            return original_replace(source, destination)

        def fail_generations(path, *args, **kwargs):
            if path == key_root / "generations":
                raise failure
            return original_mkdir(path, *args, **kwargs)

        with patch.object(Path, "mkdir", new=fail_generations), patch.object(
            pa_family_cache.os, "replace", side_effect=observe_replace
        ):
            with self.assertRaises(OSError) as caught:
                advance_pa_family_cache_transaction(cache, identity(), self.names,
                    verification_evidence=self._verification_evidence(prepared), **options)
        self.assertIs(caught.exception, failure)
        self.assertEqual(len(before_move), 1)
        self.assertIsNotNone(before_move[0], "key range must precede recovery migration")
        self.assertEqual(before_move[0]["status"], "writing")
        self.assertEqual(before_move[0]["bytes"], 0)
        self.assertEqual(before_move[0]["owner"], self.artifact_owner)
        self.assertTrue(before_move[0]["pin"])
        ledger = capacity_ledger.load_capacity_ledger(artifacts)
        rows = {row["path"]: row for row in ledger["objects"]}
        measured = sum(path.stat().st_size for path in key_root.rglob("*") if path.is_file())
        self.assertGreater(measured, 0)
        self.assertEqual(rows[key_relative]["bytes"], measured)
        self.assertEqual(rows[key_relative]["status"], "writing")
        self.assertEqual(rows[key_relative]["pin_reason"], reason)
        self.assertEqual(rows[stage_relative]["bytes"], sum(
            path.stat().st_size for path in first.transaction_directory.rglob("*") if path.is_file()))
        self.assertEqual(ledger["resident_bytes"], sum(row["bytes"] for row in rows.values()
                                                    if row["status"] != "retired"))
        self.assertFalse((key_root / "current_generation.json").exists())
        original_write = pa_family_cache._write_transaction

        def reject_error_journal(path, document):
            if document["last_error"] is not None:
                raise OSError("fixture failure journal write")
            return original_write(path, document)

        with patch.object(Path, "mkdir", new=fail_generations), patch.object(
            pa_family_cache, "_write_transaction", side_effect=reject_error_journal
        ):
            with self.assertRaises(OSError) as caught:
                advance_pa_family_cache_transaction(cache, identity(), self.names, **options)
        self.assertIs(caught.exception, failure)
        self.assertTrue(any("fixture failure journal write" in note for note in failure.__notes__))
        rows = {row["path"]: row for row in capacity_ledger.load_capacity_ledger(artifacts)["objects"]}
        self.assertEqual(rows[stage_relative]["bytes"], pa_family_cache._key_root_bytes(first.transaction_directory))
        self.assertEqual(rows[key_relative]["bytes"], pa_family_cache._key_root_bytes(key_root))
        manifest_before = (prepared.build_directory / "cache_manifest.json").read_bytes()
        recovered = advance_pa_family_cache_transaction(cache, identity(), self.names, **options)
        self.assertEqual(recovered.status, "published")
        self.assertEqual((recovered.generation_directory / "cache_manifest.json").read_bytes(), manifest_before)
        stable = capacity_ledger.load_capacity_ledger(artifacts)
        repeated = advance_pa_family_cache_transaction(cache, identity(), self.names, **options)
        self.assertEqual(repeated.generation_sha256, recovered.generation_sha256)
        self.assertEqual(capacity_ledger.load_capacity_ledger(artifacts), stable)
        rows = {row["path"]: row for row in stable["objects"]}
        self.assertEqual(rows[key_relative]["status"], "ready")
        self.assertTrue(rows[key_relative]["pin"])
        self.assertEqual(rows[stage_relative]["status"], "retired")

    def test_transaction_publication_preserves_primary_error_when_key_accounting_fails(self) -> None:
        artifacts, cache = self._artifact_cache()
        options = dict(owner=self.artifact_owner)
        first = advance_pa_family_cache_transaction(cache, identity(), self.names,
            producer_run_config=self.producer_run_config, **options)
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(cache, identity(), self.names, **options)
        key_root = cache / first.cache_key
        original_mkdir = Path.mkdir
        original_record = capacity_ledger.record_capacity_object
        failure = OSError("fixture original generation failure")

        def fail_generations(path, *args, **kwargs):
            if path == key_root / "generations":
                raise failure
            return original_mkdir(path, *args, **kwargs)

        def fail_landed_key_record(root, **kwargs):
            if kwargs["path"] == key_root and (key_root / "recovery").exists():
                raise OSError("fixture capacity write failure")
            return original_record(root, **kwargs)

        with patch.object(Path, "mkdir", new=fail_generations), patch.object(
            capacity_ledger, "record_capacity_object", side_effect=fail_landed_key_record
        ):
            with self.assertRaises(OSError) as caught:
                advance_pa_family_cache_transaction(cache, identity(), self.names,
                    verification_evidence=self._verification_evidence(prepared), **options)
        self.assertIs(caught.exception, failure)
        self.assertTrue(any("key-root capacity accounting failed" in note
                            for note in caught.exception.__notes__))
        self.assertTrue(any("fixture capacity write failure" in note
                            for note in caught.exception.__notes__))
        failed = pa_family_cache.load_pa_family_cache_transaction(cache, first.cache_key)
        self.assertEqual(failed["status"], "prepared")
        self.assertIn("fixture original generation failure", failed["last_error"])
        self.assertFalse((key_root / "current_generation.json").exists())
        recovered = advance_pa_family_cache_transaction(cache, identity(), self.names, **options)
        self.assertEqual(recovered.status, "published")
        _, relative = capacity_ledger.capacity_object_path(artifacts, key_root)
        row = next(item for item in capacity_ledger.load_capacity_ledger(artifacts)["objects"]
                   if item["path"] == relative)
        self.assertEqual(row["bytes"], pa_family_cache._key_root_bytes(key_root))

    def test_transaction_pointer_write_failure_accounts_control_and_stage_bytes(self) -> None:
        artifacts, cache = self._artifact_cache()
        first = advance_pa_family_cache_transaction(cache, identity(), self.names,
            owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(cache, identity(), self.names)
        key_root = cache / first.cache_key
        original_replace = pa_family_cache.os.replace
        failure = OSError("fixture pointer rename after temporary write")

        def fail_pointer(source, destination):
            if Path(destination) == key_root / "current_generation.json":
                self.assertGreater(Path(source).stat().st_size, 0)
                raise failure
            return original_replace(source, destination)

        with patch.object(pa_family_cache.os, "replace", side_effect=fail_pointer):
            with self.assertRaises(OSError) as caught:
                advance_pa_family_cache_transaction(cache, identity(), self.names,
                    verification_evidence=self._verification_evidence(prepared))
        self.assertIs(caught.exception, failure)
        self.assertEqual(len(list(key_root.glob(".current_generation.json.*.tmp"))), 1)
        self.assertFalse((key_root / "current_generation.json").exists())
        _, key_relative = capacity_ledger.capacity_object_path(artifacts, key_root)
        _, stage_relative = capacity_ledger.capacity_object_path(artifacts, first.transaction_directory)
        ledger = capacity_ledger.load_capacity_ledger(artifacts)
        rows = {row["path"]: row for row in ledger["objects"]}
        self.assertEqual(rows[key_relative]["status"], "writing")
        self.assertEqual(rows[key_relative]["bytes"], pa_family_cache._key_root_bytes(key_root))
        self.assertEqual(rows[stage_relative]["status"], "writing")
        self.assertEqual(rows[stage_relative]["bytes"], pa_family_cache._key_root_bytes(first.transaction_directory))
        recovered = advance_pa_family_cache_transaction(cache, identity(), self.names)
        self.assertEqual(recovered.status, "published")
        stable = capacity_ledger.load_capacity_ledger(artifacts)
        pointer = key_root / "current_generation.json"
        pointer_before = pointer.read_bytes()
        temporaries = list(key_root.glob(".current_generation.json.*.tmp"))
        with patch.object(pa_family_cache.os, "replace", side_effect=fail_pointer):
            advance_pa_family_cache_transaction(cache, identity(), self.names)
        self.assertEqual(pointer.read_bytes(), pointer_before)
        self.assertEqual(list(key_root.glob(".current_generation.json.*.tmp")), temporaries)
        self.assertEqual(capacity_ledger.load_capacity_ledger(artifacts), stable)
        for changed in (b"{", json.dumps({"cache_key": "A" * 64,
                                          "generation_sha256": recovered.generation_sha256}).encode()):
            pointer.write_bytes(changed)
            advance_pa_family_cache_transaction(cache, identity(), self.names)
            self.assertEqual(pointer.read_bytes(), pointer_before)
        rows = {row["path"]: row for row in stable["objects"]}
        self.assertEqual(rows[key_relative]["status"], "ready")
        self.assertEqual(rows[key_relative]["bytes"], pa_family_cache._key_root_bytes(key_root))
        original_write = pa_family_cache._write_transaction

        def fail_completed_write(path, document):
            if document["last_error"] is None:
                raise OSError("fixture final transaction write")
            return original_write(path, document)

        with patch.object(pa_family_cache, "_write_transaction", side_effect=fail_completed_write):
            with self.assertRaisesRegex(OSError, "final transaction write"):
                advance_pa_family_cache_transaction(cache, identity(), self.names)
        self.assertEqual(capacity_ledger.load_capacity_ledger(artifacts), stable)

    def test_transaction_publication_requires_destination_registration_before_migration(self) -> None:
        artifacts, cache = self._artifact_cache()
        first = advance_pa_family_cache_transaction(cache, identity(), self.names,
            owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(cache, identity(), self.names)
        key_root = cache / first.cache_key
        original_record = capacity_ledger.record_capacity_object

        def reject_key(root, **kwargs):
            if kwargs["path"] == key_root:
                raise OSError("fixture destination registration unavailable")
            return original_record(root, **kwargs)

        with patch.object(capacity_ledger, "record_capacity_object", side_effect=reject_key):
            with self.assertRaisesRegex(PAFamilyCacheError, "cannot record PA cache writing"):
                advance_pa_family_cache_transaction(cache, identity(), self.names,
                    verification_evidence=self._verification_evidence(prepared))
        self.assertFalse(key_root.exists())
        self.assertTrue((first.transaction_directory / "recovery-scratch").is_dir())
        _, relative = capacity_ledger.capacity_object_path(artifacts, first.transaction_directory)
        row = next(item for item in capacity_ledger.load_capacity_ledger(artifacts)["objects"]
                   if item["path"] == relative)
        self.assertEqual(row["bytes"], pa_family_cache._key_root_bytes(first.transaction_directory))

    def test_transaction_publication_cannot_take_another_key_owner(self) -> None:
        artifacts, cache = self._artifact_cache()
        first = advance_pa_family_cache_transaction(cache, identity(), self.names,
            owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(cache, identity(), self.names)
        key_root = cache / first.cache_key
        other = capacity_ledger.record_capacity_object(artifacts, path=key_root,
            object_class="published_cache", bytes_count=0, status="writing", identity="A" * 64,
            owner="another producer", pin=True, pin_reason="other publication",
            recovery_reason="pa_cache_publication_incomplete", review_deadline="2026-10-01")
        with self.assertRaisesRegex(PAFamilyCacheError, "cannot record PA cache writing"):
            advance_pa_family_cache_transaction(cache, identity(), self.names,
                verification_evidence=self._verification_evidence(prepared))
        self.assertFalse(key_root.exists())
        row = next(item for item in capacity_ledger.load_capacity_ledger(artifacts)["objects"]
                   if item["path"] == other["path"])
        self.assertEqual(row, other)
        transaction = pa_family_cache.load_pa_family_cache_transaction(cache, first.cache_key)
        pinned = capacity_ledger.record_capacity_object(artifacts, path=key_root,
            object_class="published_cache", bytes_count=0, status="writing",
            identity=transaction["generation_sha256"], owner=self.artifact_owner,
            pin=True, pin_reason="independent retention pin",
            recovery_reason="pa_cache_publication_incomplete", review_deadline="2026-10-01")
        with self.assertRaisesRegex(PAFamilyCacheError, "cannot record PA cache writing"):
            advance_pa_family_cache_transaction(cache, identity(), self.names)
        self.assertFalse(key_root.exists())
        row = next(item for item in capacity_ledger.load_capacity_ledger(artifacts)["objects"]
                   if item["path"] == pinned["path"])
        self.assertEqual(row, pinned)

    def test_artifact_transaction_may_publish_unpinned_for_manager_retirement(self) -> None:
        artifacts, cache = self._artifact_cache()
        first = advance_pa_family_cache_transaction(cache, identity(), self.names, owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(cache, identity(), self.names, owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        published = advance_pa_family_cache_transaction(
            cache,
            identity(),
            self.names,
            verification_evidence=self._verification_evidence(prepared),
        )
        ledger = capacity_ledger.load_capacity_ledger(artifacts)
        _, relative = capacity_ledger.capacity_object_path(
            artifacts, cache / published.cache_key
        )
        entry = next(item for item in ledger["objects"] if item["path"] == relative)
        self.assertIs(entry["pin"], False)
        self.assertEqual(entry["manager"], "common.simion.pa_family_cache")

    def test_artifact_published_generation_pin_backfill_is_exact_and_idempotent(self) -> None:
        artifacts, cache = self._artifact_cache()
        first = advance_pa_family_cache_transaction(
            cache, identity(), self.names, owner=self.artifact_owner,
            producer_run_config=self.producer_run_config,
        )
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(
            cache, identity(), self.names, owner=self.artifact_owner,
        )
        published = advance_pa_family_cache_transaction(
            cache, identity(), self.names,
            verification_evidence=self._verification_evidence(prepared),
            owner=self.artifact_owner,
        )
        reason = "fixture GUI delivery depends on this generation"
        with patch.object(
            pa_family_cache,
            "_verify_payload_record",
            side_effect=AssertionError("pin must not read payload"),
        ):
            pinned = advance_pa_family_cache_transaction(
                cache, identity(), self.names, owner=self.artifact_owner,
                published_pin_reason=reason,
                published_pin_generation_sha256=published.generation_sha256,
            )
            repeated = advance_pa_family_cache_transaction(
                cache, identity(), self.names, owner=self.artifact_owner,
                published_pin_reason=reason,
                published_pin_generation_sha256=published.generation_sha256,
            )
        self.assertEqual(pinned.generation_sha256, published.generation_sha256)
        self.assertEqual(repeated.generation_sha256, published.generation_sha256)
        transaction = pa_family_cache.load_pa_family_cache_transaction(
            cache, published.cache_key
        )
        self.assertEqual(transaction["published_pin_reason"], reason)
        ledger = capacity_ledger.load_capacity_ledger(artifacts)
        _, key_relative = capacity_ledger.capacity_object_path(artifacts, cache / published.cache_key)
        entry = next(item for item in ledger["objects"] if item["path"] == key_relative)
        self.assertIs(entry["pin"], True)
        self.assertEqual(entry["pin_reason"], reason)

    def test_artifact_published_pin_backfill_replays_ledger_write_interruption(self) -> None:
        artifacts, cache = self._artifact_cache()
        first = advance_pa_family_cache_transaction(
            cache, identity(), self.names, owner=self.artifact_owner,
            producer_run_config=self.producer_run_config,
        )
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(
            cache, identity(), self.names, owner=self.artifact_owner,
        )
        published = advance_pa_family_cache_transaction(
            cache, identity(), self.names,
            verification_evidence=self._verification_evidence(prepared),
            owner=self.artifact_owner,
        )
        reason = "fixture GUI delivery survives ledger interruption"
        request = {
            "owner": self.artifact_owner,
            "published_pin_reason": reason,
            "published_pin_generation_sha256": published.generation_sha256,
        }
        with patch.object(
            pa_family_cache,
            "_record_artifact_cache_state",
            side_effect=OSError("fixture ledger interruption"),
        ):
            with self.assertRaisesRegex(OSError, "fixture ledger interruption"):
                advance_pa_family_cache_transaction(cache, identity(), self.names, **request)

        transaction = pa_family_cache.load_pa_family_cache_transaction(cache, published.cache_key)
        self.assertEqual(transaction["published_pin_reason"], reason)
        _, key_relative = capacity_ledger.capacity_object_path(artifacts, cache / published.cache_key)
        ledger = capacity_ledger.load_capacity_ledger(artifacts)
        entry = next(item for item in ledger["objects"] if item["path"] == key_relative)
        self.assertIs(entry["pin"], False)
        self.assertIsNone(entry.get("pin_reason"))

        with patch.object(
            pa_family_cache,
            "_verify_payload_record",
            side_effect=AssertionError("pin replay must not read payload"),
        ):
            replayed = advance_pa_family_cache_transaction(cache, identity(), self.names, **request)
        self.assertEqual(replayed.generation_sha256, published.generation_sha256)
        ledger = capacity_ledger.load_capacity_ledger(artifacts)
        entry = next(item for item in ledger["objects"] if item["path"] == key_relative)
        self.assertIs(entry["pin"], True)
        self.assertEqual(entry["pin_reason"], reason)

    def test_generation_publication_pin_validation_requires_matching_owner_records(self) -> None:
        _, cache = self._artifact_cache()
        first = advance_pa_family_cache_transaction(
            cache, identity(), self.names, owner=self.artifact_owner,
            producer_run_config=self.producer_run_config,
        )
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(
            cache, identity(), self.names, owner=self.artifact_owner,
        )
        published = advance_pa_family_cache_transaction(
            cache, identity(), self.names,
            verification_evidence=self._verification_evidence(prepared),
            owner=self.artifact_owner,
        )
        with patch.object(
            pa_family_cache,
            "_verify_payload_record",
            side_effect=AssertionError("publication pin validation must not read payload"),
        ):
            with self.assertRaisesRegex(PAFamilyCacheError, "publication pin binding"):
                validate_pa_family_cache_generation(
                    published.generation_directory,
                    expected_cache_key=published.cache_key,
                    expected_filenames=self.names,
                    verify_payload=False,
                    require_publication_pin=True,
                )

            reason = "fixture durable GUI delivery"
            advance_pa_family_cache_transaction(
                cache, identity(), self.names, owner=self.artifact_owner,
                published_pin_reason=reason,
                published_pin_generation_sha256=published.generation_sha256,
            )
            validated = validate_pa_family_cache_generation(
                published.generation_directory,
                expected_cache_key=published.cache_key,
                expected_filenames=self.names,
                verify_payload=False,
                require_publication_pin=True,
            )
        self.assertEqual(validated["generation_sha256"], published.generation_sha256)

        binding = pa_family_cache._artifact_ledger_binding(cache, published.cache_key, required=True)
        pa_family_cache._record_artifact_cache_state(
            binding,
            published.generation_sha256,
            "ready",
            published_pin_reason="different fixture reason",
        )
        with self.assertRaisesRegex(PAFamilyCacheError, "publication pin binding"):
            validate_pa_family_cache_generation(
                published.generation_directory,
                expected_cache_key=published.cache_key,
                expected_filenames=self.names,
                verify_payload=False,
                require_publication_pin=True,
            )

    def test_artifact_published_generation_pin_backfill_rejects_wrong_generation_or_owner(self) -> None:
        _, cache = self._artifact_cache()
        first = advance_pa_family_cache_transaction(
            cache, identity(), self.names, owner=self.artifact_owner,
            producer_run_config=self.producer_run_config,
        )
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(cache, identity(), self.names, owner=self.artifact_owner)
        published = advance_pa_family_cache_transaction(
            cache, identity(), self.names,
            verification_evidence=self._verification_evidence(prepared), owner=self.artifact_owner,
        )
        with self.assertRaisesRegex(PAFamilyCacheError, "published pin policy differs"):
            advance_pa_family_cache_transaction(
                cache, identity(), self.names, owner=self.artifact_owner,
                published_pin_reason="fixture pin", published_pin_generation_sha256="A" * 64,
            )
        with self.assertRaisesRegex(PAFamilyCacheError, "owner differs"):
            advance_pa_family_cache_transaction(
                cache, identity(), self.names, owner="other owner",
                published_pin_reason="fixture pin", published_pin_generation_sha256=published.generation_sha256,
            )

    def test_artifact_transaction_handoff_is_atomic(self) -> None:
        artifacts, cache = self._artifact_cache()
        reason = "fixture governed family"
        first = advance_pa_family_cache_transaction(
            cache, identity(), self.names, owner=self.artifact_owner, producer_run_config=self.producer_run_config,
            published_pin_reason=reason
        )
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(
            cache, identity(), self.names, owner=self.artifact_owner, producer_run_config=self.producer_run_config,
            published_pin_reason=reason
        )
        published = advance_pa_family_cache_transaction(
            cache,
            identity(),
            self.names,
            verification_evidence=self._verification_evidence(prepared),
            owner=self.artifact_owner,
            published_pin_reason=reason,
        )
        ledger = capacity_ledger.load_capacity_ledger(artifacts)
        self.assertIsNotNone(ledger)
        by_path = {entry["path"]: entry for entry in ledger["objects"]}
        _, transaction_relative = capacity_ledger.capacity_object_path(
            artifacts, published.transaction_directory
        )
        _, key_relative = capacity_ledger.capacity_object_path(
            artifacts, cache / published.cache_key
        )
        self.assertEqual(by_path[transaction_relative]["status"], "retired")
        self.assertEqual(by_path[key_relative]["status"], "ready")
        self.assertEqual(
            by_path[key_relative]["identity"],
            published.generation_sha256,
        )
        self.assertIs(by_path[key_relative]["pin"], True)
        self.assertEqual(by_path[key_relative]["pin_reason"], reason)
        maintenance = reconcile_artifact_capacity.plan(
            artifacts, target_bytes=0, minimum_free_bytes=0, execution_mode="maintenance")
        self.assertNotIn(str(cache / published.cache_key), [item["path"] for item in maintenance["planned"]])

    def test_artifact_transaction_owner_approves_exact_retirement_idempotently(self) -> None:
        artifacts, cache = self._artifact_cache()
        first = advance_pa_family_cache_transaction(cache, identity(), self.names, owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(cache, identity(), self.names, owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        published = advance_pa_family_cache_transaction(
            cache,
            identity(),
            self.names,
            verification_evidence=self._verification_evidence(prepared),
        )
        ledger = capacity_ledger.load_capacity_ledger(artifacts)
        _, key_relative = capacity_ledger.capacity_object_path(
            artifacts, cache / published.cache_key
        )
        entry = next(
            item for item in ledger["objects"] if item["path"] == key_relative
        )
        self.assertIs(entry["pin"], False)
        retired = approve_pa_family_cache_retirement(
            cache,
            published.cache_key,
            published.generation_sha256,
        )
        repeated = approve_pa_family_cache_retirement(
            cache,
            published.cache_key,
            published.generation_sha256,
        )
        self.assertEqual(retired.status, "retired")
        self.assertEqual(repeated.status, "retired")
        self.assertTrue(published.generation_directory.is_dir())
        ledger = capacity_ledger.load_capacity_ledger(artifacts)
        approved = next(
            item for item in ledger["objects"] if item["path"] == key_relative
        )
        self.assertEqual(approved["class"], "rebuildable_payload")
        self.assertEqual(approved["status"], "ready")
        self.assertIs(approved["pin"], False)
        self.assertEqual(
            approved["disposition"]["generation"], published.generation_sha256
        )
        self.assertIs(
            probe_pa_family_cache(cache, identity()).disposition,
            CacheDisposition.MISS,
        )

    def test_capacity_plan_retires_published_family_through_real_owner(self) -> None:
        artifacts, cache = self._artifact_cache()
        published = self._publish_governed_transaction(cache)
        expected_bytes = self._ledger_entry(artifacts, published.cache_key)["bytes"]
        planned = reconcile_artifact_capacity.plan(
            artifacts, target_bytes=0, minimum_free_bytes=0,
            execution_mode="maintenance",
        )
        candidate = next(
            item for item in planned["planned"]
            if item["operation"] == "request_retirement"
        )
        self.assertEqual(candidate["cache_key"], published.cache_key)
        self.assertEqual(candidate["cache_key"], candidate["cache_key"].upper())
        # Exercise the production owner interface, not a permissive approval mock.
        applied = reconcile_artifact_capacity.apply(planned)
        self.assertEqual(applied["failed"], [])
        self.assertEqual(applied["removed_bytes"], expected_bytes)
        self.assertFalse((cache / published.cache_key).exists())
        self.assertEqual(self._ledger_entry(artifacts, published.cache_key)["status"], "retired")
        transaction = json.loads(
            (published.transaction_directory / "transaction.json").read_text()
        )
        self.assertEqual(transaction["status"], "retired")

    def test_artifact_transaction_pin_blocks_manager_retirement(self) -> None:
        _, cache = self._artifact_cache()
        reason = "fixture native family; rebuild only on frozen identity change"
        first = advance_pa_family_cache_transaction(
            cache, identity(), self.names, owner=self.artifact_owner,
            producer_run_config=self.producer_run_config,
            published_pin_reason=reason
        )
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(
            cache, identity(), self.names, owner=self.artifact_owner,
            published_pin_reason=reason
        )
        published = advance_pa_family_cache_transaction(
            cache,
            identity(),
            self.names,
            verification_evidence=self._verification_evidence(prepared),
            owner=self.artifact_owner,
            published_pin_reason=reason,
        )
        with self.assertRaisesRegex(PAFamilyCacheError, "pinned.*cannot retire"):
            approve_pa_family_cache_retirement(
                cache, published.cache_key, published.generation_sha256
            )

    def test_owner_pin_release_requires_intent_and_reconciles_ledger(self) -> None:
        artifacts, cache = self._artifact_cache()
        reason = "fixture pinned until replacement"
        first = advance_pa_family_cache_transaction(
            cache, identity(), self.names, owner=self.artifact_owner, producer_run_config=self.producer_run_config, published_pin_reason=reason)
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(
            cache, identity(), self.names, owner=self.artifact_owner, producer_run_config=self.producer_run_config, published_pin_reason=reason)
        published = advance_pa_family_cache_transaction(
            cache, identity(), self.names, verification_evidence=self._verification_evidence(prepared),
            owner=self.artifact_owner, producer_run_config=self.producer_run_config, published_pin_reason=reason)
        replacement_path = artifacts / "replacement" / "run_manifest.json"
        replacement_path.parent.mkdir(parents=True)
        replacement_path.write_bytes(b"verified replacement")
        evidence = {
            "schema_version": 1, "role": "simion_pa_family_cache_replacement_evidence",
            "status": "verified", "cache_key": published.cache_key,
            "generation_sha256": "E" * 64, "source_path": "replacement/run_manifest.json",
            "source_sha256": pa_family_cache.file_sha256(replacement_path).upper(),
        }
        evidence_sha = pa_family_cache.canonical_json_sha256(evidence)
        intent = {
            "schema_version": 1, "role": "simion_pa_family_cache_retirement_intent",
            "status": "approved", "cache_key": published.cache_key,
            "generation_sha256": published.generation_sha256, "owner": self.artifact_owner,
            "replacement_generation_sha256": "E" * 64, "replacement_evidence_sha256": evidence_sha,
        }
        released = release_pa_family_cache_retirement_pin(
            cache, published.cache_key, published.generation_sha256, owner=self.artifact_owner,
            retirement_intent=intent, replacement_evidence=evidence)
        self.assertEqual(released.status, "published")
        ledger = capacity_ledger.load_capacity_ledger(artifacts)
        _, relative = capacity_ledger.capacity_object_path(artifacts, cache / published.cache_key)
        entry = next(item for item in ledger["objects"] if item["path"] == relative)
        self.assertIs(entry["pin"], False)
        transaction = json.loads((published.transaction_directory / "transaction.json").read_text())
        self.assertIsNone(transaction["published_pin_reason"])
        self.assertIn("pin_release", transaction)
        retired = approve_pa_family_cache_retirement(cache, published.cache_key, published.generation_sha256)
        self.assertEqual(retired.status, "retired")
        self.assertIs(probe_pa_family_cache(cache, identity()).disposition, CacheDisposition.MISS)

    def test_pa_audit_closes_legacy_transaction_container_after_all_records_close(self) -> None:
        artifacts, cache = self._artifact_cache()
        published = self._publish_governed_transaction(cache)
        approve_pa_family_cache_retirement(cache, published.cache_key, published.generation_sha256)
        container = cache / ".transactions"
        capacity_ledger.record_capacity_object(
            artifacts, path=container, object_class="rebuildable_payload",
            bytes_count=self._tree_bytes(container), status="writing", owner=self.artifact_owner,
            recovery_reason="pa_transaction_recovery_required",
            recovery_task="fixture closes aggregate transaction container",
            review_deadline="2026-10-01",
        )
        audit = pa_family_cache.audit_pa_transaction_maintenance(cache)
        self.assertEqual(audit["invalid_count"], 0)
        _, relative = capacity_ledger.capacity_object_path(artifacts, container)
        entry = next(item for item in capacity_ledger.load_capacity_ledger(artifacts)["objects"] if item["path"] == relative)
        self.assertEqual((entry["class"], entry["status"]), ("light_evidence", "ready"))

    def test_pa_audit_preserves_retired_parent_and_ready_transaction_children(self) -> None:
        artifacts, cache = self._artifact_cache()
        published = self._publish_governed_transaction(cache)
        approve_pa_family_cache_retirement(cache, published.cache_key, published.generation_sha256)
        container = cache / ".transactions"
        capacity_ledger.record_capacity_object(
            artifacts, path=container, object_class="rebuildable_payload",
            bytes_count=self._tree_bytes(container), status="ready",
            owner=self.artifact_owner,
        )
        capacity_ledger.retire_capacity_object(artifacts, path=container)
        capacity_ledger.record_capacity_object(
            artifacts, path=published.transaction_directory, object_class="light_evidence",
            bytes_count=self._tree_bytes(published.transaction_directory), status="ready",
            owner=self.artifact_owner,
        )
        before = capacity_ledger.load_capacity_ledger(artifacts)
        audit = pa_family_cache.audit_pa_transaction_maintenance(cache)
        self.assertEqual(audit["invalid_count"], 0)
        self.assertEqual(audit["checked_count"], 1)
        self.assertEqual(capacity_ledger.load_capacity_ledger(artifacts), before)
        self.assertTrue((published.transaction_directory / "transaction.json").is_file())

    def test_owner_pin_release_rejects_missing_or_mismatched_replacement_evidence(self) -> None:
        _, cache = self._artifact_cache()
        first = advance_pa_family_cache_transaction(
            cache, identity(), self.names, owner=self.artifact_owner, producer_run_config=self.producer_run_config, published_pin_reason="fixture pin")
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(
            cache, identity(), self.names, owner=self.artifact_owner, producer_run_config=self.producer_run_config, published_pin_reason="fixture pin")
        published = advance_pa_family_cache_transaction(
            cache, identity(), self.names, verification_evidence=self._verification_evidence(prepared),
            owner=self.artifact_owner, producer_run_config=self.producer_run_config, published_pin_reason="fixture pin")
        with self.assertRaisesRegex(PAFamilyCacheError, "replacement evidence"):
            release_pa_family_cache_retirement_pin(
                cache, published.cache_key, published.generation_sha256, owner=self.artifact_owner,
                retirement_intent={}, replacement_evidence={})

    def test_artifact_transaction_retirement_lease_blocks_without_state_change(self) -> None:
        artifacts, cache = self._artifact_cache()
        first = advance_pa_family_cache_transaction(cache, identity(), self.names, owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(cache, identity(), self.names, owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        published = advance_pa_family_cache_transaction(
            cache,
            identity(),
            self.names,
            verification_evidence=self._verification_evidence(prepared),
        )
        capacity_protection.create_capacity_protection_lease(
            artifacts,
            lease_id="fixture-active-pa-consumer",
            owner="pa-family-cache-test",
            ttl_seconds=300,
            protected_cache_keys=[published.cache_key],
        )
        with self.assertRaisesRegex(PAFamilyCacheError, "cannot approve"):
            approve_pa_family_cache_retirement(
                cache, published.cache_key, published.generation_sha256
            )
        transaction = json.loads(
            (published.transaction_directory / "transaction.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(transaction["status"], "published")
        self.assertTrue(published.generation_directory.is_dir())

    def test_artifact_transaction_retirement_resumes_after_ledger_write_failure(self) -> None:
        artifacts, cache = self._artifact_cache()
        first = advance_pa_family_cache_transaction(cache, identity(), self.names, owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(cache, identity(), self.names, owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        published = advance_pa_family_cache_transaction(
            cache,
            identity(),
            self.names,
            verification_evidence=self._verification_evidence(prepared),
        )
        with patch.object(
            capacity_ledger,
            "write_json_atomic",
            side_effect=OSError("fixture ledger write interruption"),
        ):
            with self.assertRaisesRegex(PAFamilyCacheError, "cannot approve"):
                approve_pa_family_cache_retirement(
                    cache, published.cache_key, published.generation_sha256
                )

        transaction_path = published.transaction_directory / "transaction.json"
        interrupted = json.loads(transaction_path.read_text(encoding="utf-8"))
        self.assertEqual(interrupted["status"], "retired")
        ledger = capacity_ledger.load_capacity_ledger(artifacts)
        _, key_relative = capacity_ledger.capacity_object_path(
            artifacts, cache / published.cache_key
        )
        approved = next(
            item for item in ledger["objects"] if item["path"] == key_relative
        )
        self.assertEqual(approved["class"], "published_cache")
        self.assertNotIn("disposition", approved)
        self.assertTrue(published.generation_directory.is_dir())

        resumed = approve_pa_family_cache_retirement(
            cache, published.cache_key, published.generation_sha256
        )
        self.assertEqual(resumed.status, "retired")
        self.assertTrue(published.generation_directory.is_dir())

    def test_artifact_transaction_retirement_resumes_after_owner_write_failure(self) -> None:
        artifacts, cache = self._artifact_cache()
        first = advance_pa_family_cache_transaction(cache, identity(), self.names, owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(cache, identity(), self.names, owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        published = advance_pa_family_cache_transaction(
            cache,
            identity(),
            self.names,
            verification_evidence=self._verification_evidence(prepared),
        )
        original_write = pa_family_cache._write_transaction

        def fail_retired_write(path: Path, document: dict[str, object]) -> None:
            if document["status"] == "retired":
                raise OSError("fixture owner transaction write interruption")
            original_write(path, document)

        with patch.object(
            pa_family_cache, "_write_transaction", side_effect=fail_retired_write
        ):
            with self.assertRaisesRegex(PAFamilyCacheError, "cannot approve"):
                approve_pa_family_cache_retirement(
                    cache, published.cache_key, published.generation_sha256
                )

        transaction = json.loads(
            (published.transaction_directory / "transaction.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(transaction["status"], "published")
        ledger = capacity_ledger.load_capacity_ledger(artifacts)
        _, key_relative = capacity_ledger.capacity_object_path(
            artifacts, cache / published.cache_key
        )
        entry = next(item for item in ledger["objects"] if item["path"] == key_relative)
        self.assertEqual(entry["class"], "published_cache")
        self.assertNotIn("disposition", entry)

        resumed = approve_pa_family_cache_retirement(
            cache, published.cache_key, published.generation_sha256
        )
        self.assertEqual(resumed.status, "retired")
        self.assertTrue(published.generation_directory.is_dir())

    def test_completed_retirement_starts_a_new_build_cycle(self) -> None:
        artifacts, cache = self._artifact_cache()
        first = advance_pa_family_cache_transaction(cache, identity(), self.names, owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        self._land_transaction_members(first, self.names)
        prepared = advance_pa_family_cache_transaction(cache, identity(), self.names, owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        published = advance_pa_family_cache_transaction(
            cache,
            identity(),
            self.names,
            verification_evidence=self._verification_evidence(prepared),
        )
        approve_pa_family_cache_retirement(
            cache, published.cache_key, published.generation_sha256
        )
        key_root = cache / published.cache_key
        transaction = json.loads(
            (published.transaction_directory / "transaction.json").read_text(
                encoding="utf-8"
            )
        )
        pending = capacity_ledger.begin_approved_disposition(
            artifacts,
            path=key_root,
            disposition_id=transaction["retirement"]["id"],
        )
        cache_generation._remove_tree_writable(key_root)
        capacity_ledger.finalize_retirement(
            artifacts,
            path=key_root,
            removed_bytes=pending["bytes"],
        )

        original_mkdir = Path.mkdir
        interrupted = False

        def interrupt_first_payload_mkdir(
            path: Path,
            mode: int = 0o777,
            parents: bool = False,
            exist_ok: bool = False,
        ) -> None:
            nonlocal interrupted
            if path == published.transaction_directory / "payload" and not interrupted:
                interrupted = True
                raise OSError("fixture kill after building transaction commit")
            original_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

        with patch.object(Path, "mkdir", new=interrupt_first_payload_mkdir):
            with self.assertRaisesRegex(OSError, "after building transaction commit"):
                advance_pa_family_cache_transaction(cache, identity(), self.names, owner=self.artifact_owner, producer_run_config=self.producer_run_config)
        interrupted_document = json.loads(
            (published.transaction_directory / "transaction.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(interrupted_document["status"], "building")

        restarted = advance_pa_family_cache_transaction(
            cache, identity(), self.names
        )
        self.assertEqual(restarted.status, "building")
        self.assertEqual(restarted.action_required, "build")
        self.assertEqual(restarted.missing_files, self.names)

    def test_rejected_new_publication_rolls_back_pointer_payload_and_recovery(self) -> None:
        published = publish_pa_family_cache(
            self.cache, identity(), self.source, self.names
        )
        self.assertIs(published.disposition, CacheDisposition.PUBLISHED)
        recovery = (
            published.generation_directory.parents[1]
            / "recovery"
            / published.generation_sha256
        )
        self.assertTrue(recovery.is_dir())

        receipt = rollback_pa_family_cache_publication(
            self.cache,
            identity(),
            published.generation_sha256,
            expected_predecessor_generation_sha256=None,
            reason="fixture postcondition mismatch",
        )

        self.assertTrue(receipt["current_pointer_removed"])
        self.assertTrue(receipt["rejected_generation_removed"])
        self.assertTrue(receipt["rejected_recovery_removed"])
        self.assertFalse(published.generation_directory.exists())
        self.assertFalse(recovery.exists())
        self.assertFalse(
            published.generation_directory.parents[1].joinpath("current_generation.json").exists()
        )
        self.assertTrue(Path(receipt["receipt_path"]).is_file())
        self.assertIs(
            probe_pa_family_cache(
                self.cache, identity(), expected_filenames=self.names
            ).disposition,
            CacheDisposition.MISS,
        )

    def test_v2_publication_has_bound_parity_and_repairs_one_member(self) -> None:
        published = publish_pa_family_cache(
            self.cache, identity(), self.source, self.names
        )
        self.assertEqual(published.manifest["schema_version"], 2)
        self.assertNotEqual(published.manifest["redundancy"]["groups"], [])
        recovery_root = (
            published.generation_directory.parents[1]
            / "recovery"
            / published.generation_sha256
        )
        self.assertTrue(recovery_root.is_dir())

        damaged = published.generation_directory / "field.pa1"
        damaged.chmod(damaged.stat().st_mode | stat.S_IWUSR)
        damaged.write_bytes(b"bad")
        with self.assertRaisesRegex(PAFamilyCacheError, "field.pa1"):
            validate_pa_family_cache_generation(published.generation_directory)

        repaired = repair_pa_family_cache_generation(
            published.generation_directory
        )
        self.assertTrue(repaired.current_pointer_advanced)
        self.assertEqual(repaired.repaired_member, "field.pa1")
        self.assertEqual(repaired.predecessor_directory, published.generation_directory)
        self.assertTrue(repaired.predecessor_directory.is_dir())
        self.assertNotEqual(repaired.generation_sha256, published.generation_sha256)
        self.assertTrue(repaired.receipt_path.is_file())
        self.assertEqual(
            validate_pa_family_cache_generation(
                repaired.generation_directory, expected_filenames=self.names
            )["generation_sha256"],
            repaired.generation_sha256,
        )
        self.assertEqual(
            (repaired.generation_directory / "field.pa1").read_bytes(), b"one"
        )
        repeated = repair_pa_family_cache_generation(published.generation_directory)
        self.assertEqual(repeated.generation_directory, repaired.generation_directory)
        self.assertFalse(repeated.current_pointer_advanced)
        self.assertTrue(repeated.receipt_path.is_file())

    def test_reconstructible_publication_omits_xor_but_keeps_atomic_hash_validation(self) -> None:
        published = publish_pa_family_cache(
            self.cache,
            identity(),
            self.source,
            self.names,
            recovery_policy="none",
        )
        self.assertEqual(
            published.manifest["redundancy"],
            {"algorithm": "none_reconstructible", "groups": []},
        )
        recovery_root = (
            published.generation_directory.parents[1]
            / "recovery"
            / published.generation_sha256
        )
        self.assertFalse(recovery_root.exists())
        self.assertEqual(
            validate_pa_family_cache_generation(
                published.generation_directory, expected_filenames=self.names
            )["files"],
            pa_family_inventory(self.source, self.names),
        )

    def test_ensure_repairs_one_member_and_returns_successor_hit(self) -> None:
        published = publish_pa_family_cache(
            self.cache, identity(), self.source, self.names
        )
        damaged = published.generation_directory / "field.pa1"
        damaged.chmod(damaged.stat().st_mode | stat.S_IWUSR)
        damaged.write_bytes(b"bad")

        ensured = ensure_pa_family_cache(
            self.cache, identity(), expected_filenames=self.names
        )

        self.assertEqual(ensured.disposition, CacheDisposition.HIT)
        self.assertIsNotNone(ensured.generation_directory)
        self.assertNotEqual(ensured.generation_directory, published.generation_directory)
        self.assertEqual(
            (ensured.generation_directory / "field.pa1").read_bytes(), b"one"
        )
        self.assertTrue(published.generation_directory.is_dir())

    def test_subset_validation_repairs_selected_member_and_reports_lineage(self) -> None:
        published = publish_pa_family_cache(
            self.cache, identity(), self.source, self.names
        )
        damaged = published.generation_directory / "field.pa1"
        damaged.chmod(damaged.stat().st_mode | stat.S_IWUSR)
        damaged.write_bytes(b"bad")

        validated = validate_pa_family_cache_subset_with_repair(
            published.generation_directory,
            ["field.pa1"],
            expected_cache_key=published.cache_key,
        )

        self.assertEqual(
            validated.predecessor_generation_directory,
            published.generation_directory,
        )
        self.assertIsNotNone(validated.repair_receipt_path)
        self.assertEqual(
            (validated.generation_directory / "field.pa1").read_bytes(), b"one"
        )
        self.assertEqual(
            validated.manifest["predecessor_generation_sha256"],
            published.generation_sha256,
        )

    def test_ensure_preserves_miss_and_fails_closed_without_generation(self) -> None:
        self.assertEqual(
            ensure_pa_family_cache(
                self.cache, identity(), expected_filenames=self.names
            ).disposition,
            CacheDisposition.MISS,
        )
        key_root = self.cache / canonical_pa_family_cache_key(identity())
        key_root.mkdir(parents=True)
        (key_root / "current_generation.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(PAFamilyCacheError, "cannot ensure PA cache"):
            ensure_pa_family_cache(
                self.cache, identity(), expected_filenames=self.names
            )

    def test_v2_parity_corruption_is_detected_and_never_repairs_payload(self) -> None:
        published = publish_pa_family_cache(
            self.cache, identity(), self.source, self.names
        )
        group = published.manifest["redundancy"]["groups"][0]
        parity = (
            published.generation_directory.parents[1]
            / "recovery"
            / published.generation_sha256
            / group["bundle"]
            / "payload.xor"
        )
        parity.chmod(parity.stat().st_mode | stat.S_IWUSR)
        parity.write_bytes(b"X" * parity.stat().st_size)
        with self.assertRaisesRegex(PAFamilyCacheError, "redundancy payload differs"):
            validate_pa_family_cache_generation(published.generation_directory)
        pointer = published.generation_directory.parents[1] / "current_generation.json"
        before = pointer.read_bytes()
        with self.assertRaisesRegex(PAFamilyCacheError, "redundancy payload differs"):
            repair_pa_family_cache_generation(published.generation_directory)
        self.assertEqual(pointer.read_bytes(), before)
        self.assertTrue(published.generation_directory.is_dir())

    def test_migrate_snapshots_valid_v1_to_distinct_v2_successor(self) -> None:
        key = canonical_pa_family_cache_key(identity())
        records = pa_family_inventory(self.source, self.names)
        legacy_manifest = pa_family_cache._manifest(key, identity(), records)
        legacy = self.cache / key / "generations" / legacy_manifest["generation_sha256"]
        legacy.mkdir(parents=True)
        for record in records:
            cache_generation.copy_verified_file(
                self.source / record["name"], legacy / record["name"]
            )
        (legacy / "cache_manifest.json").write_text(
            json.dumps(legacy_manifest, sort_keys=True), encoding="utf-8"
        )
        pa_family_cache._seal_generation_files(legacy, legacy_manifest)
        pa_family_cache._publish_pointer(
            legacy.parents[1], key, legacy_manifest["generation_sha256"]
        )

        migrated = migrate_current_pa_family_cache(
            self.cache, identity(), self.names
        )
        self.assertEqual(migrated.manifest["schema_version"], 2)
        self.assertNotEqual(migrated.generation_directory, legacy)
        self.assertEqual(
            migrated.manifest["predecessor_generation_sha256"], legacy.name
        )
        self.assertTrue(legacy.is_dir())
        self.assertEqual(
            json.loads(
                (legacy.parents[1] / "current_generation.json").read_text(
                    encoding="utf-8"
                )
            )["generation_sha256"],
            migrated.generation_sha256,
        )

    def test_materialization_copy_failure_removes_partial_destination_and_staging(self) -> None:
        """A real partial copy must leave neither consumer payload nor staging state."""

        published = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        source_manifest = validate_pa_family_cache_generation(
            published.generation_directory,
            expected_cache_key=published.cache_key,
            expected_filenames=self.names,
        )
        destination = self.root / "run" / "simion"
        real_snapshot = cache_generation.snapshot_immutable_file
        copy_count = 0

        def fail_third_copy(
            source: Path, target: Path, record: dict[str, object]
        ) -> dict[str, object]:
            nonlocal copy_count
            copy_count += 1
            if copy_count == 3:
                raise OSError("injected third copy failure")
            return real_snapshot(source, target, record)

        with patch.object(
            cache_generation, "snapshot_immutable_file", side_effect=fail_third_copy
        ):
            with self.assertRaisesRegex(RuntimeError, "copy failed: name=field.pa1"):
                materialize_pa_family_cache(
                    published.generation_directory,
                    destination,
                    expected_filenames=self.names,
                )

        self.assertEqual(copy_count, 3)
        self.assertFalse(destination.exists())
        self.assertEqual(
            list(destination.parent.glob(f".{destination.name}.staging-*")), []
        )
        self.assertEqual(
            validate_pa_family_cache_generation(
                published.generation_directory,
                expected_cache_key=published.cache_key,
                expected_filenames=self.names,
            ),
            source_manifest,
        )
        self.assertEqual(
            probe_pa_family_cache(
                self.cache, identity(), expected_filenames=self.names
            ).disposition,
            CacheDisposition.HIT,
        )

    def test_explicit_generation_never_follows_current_pointer_drift(self) -> None:
        """Pinned generation validation/materialization never substitutes current."""

        generation_a = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        alternate = self.root / "alternate"
        alternate.mkdir()
        for name in self.names:
            (alternate / name).write_bytes(f"alternate-{name}".encode("ascii"))
        alternate_records = pa_family_inventory(alternate, self.names)
        manifest_b = pa_family_cache._manifest(
            generation_a.cache_key, identity(), alternate_records
        )
        generation_b = (
            generation_a.generation_directory.parent / manifest_b["generation_sha256"]
        )
        generation_b.mkdir()
        for name in self.names:
            cache_generation.copy_verified_file(alternate / name, generation_b / name)
        (generation_b / "cache_manifest.json").write_text(
            json.dumps(manifest_b, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        pa_family_cache._seal_generation_files(generation_b, manifest_b)
        self.assertNotEqual(
            generation_a.generation_sha256, manifest_b["generation_sha256"]
        )
        self.assertEqual(
            validate_pa_family_cache_generation(
                generation_b,
                expected_cache_key=generation_a.cache_key,
                expected_filenames=self.names,
            ),
            manifest_b,
        )

        pointer = generation_a.generation_directory.parents[1] / "current_generation.json"
        pointer.write_text(
            json.dumps(
                {
                    "cache_key": generation_a.cache_key,
                    "generation_sha256": manifest_b["generation_sha256"],
                }
            ),
            encoding="utf-8",
        )
        current = probe_pa_family_cache(
            self.cache, identity(), expected_filenames=self.names
        )
        self.assertEqual(current.disposition, CacheDisposition.HIT)
        self.assertEqual(current.generation_directory, generation_b)

        pinned_destination = self.root / "pinned-a"
        pinned_a = validate_pa_family_cache_generation(
            generation_a.generation_directory,
            expected_cache_key=generation_a.cache_key,
            expected_filenames=self.names,
        )
        materialized = materialize_pa_family_cache(
            generation_a.generation_directory,
            pinned_destination,
            expected_filenames=self.names,
        )
        self.assertEqual(materialized.files, tuple(pinned_a["files"]))
        self.assertEqual(pa_family_inventory(pinned_destination, self.names), pinned_a["files"])
        self.assertNotEqual(materialized.files, tuple(manifest_b["files"]))

        corrupted_a = generation_a.generation_directory / "field.pa1"
        corrupted_a.chmod(corrupted_a.stat().st_mode | stat.S_IWUSR)
        corrupted_a.write_bytes(b"corrupt-a")
        with self.assertRaisesRegex(PAFamilyCacheError, "field.pa1"):
            validate_pa_family_cache_generation(
                generation_a.generation_directory,
                expected_cache_key=generation_a.cache_key,
                expected_filenames=self.names,
            )
        recovered_destination = self.root / "pinned-a-recovered"
        recovered_a = materialize_pa_family_cache(
            generation_a.generation_directory,
            recovered_destination,
            expected_filenames=self.names,
        )
        self.assertEqual(
            recovered_a.predecessor_generation_directory,
            generation_a.generation_directory,
        )
        self.assertIsNotNone(recovered_a.repair_receipt_path)
        self.assertEqual(
            validate_pa_family_cache_generation(
                recovered_a.source_generation_directory,
                expected_cache_key=generation_a.cache_key,
                expected_filenames=self.names,
            )["predecessor_generation_sha256"],
            generation_a.generation_sha256,
        )
        self.assertEqual(
            json.loads(pointer.read_text(encoding="utf-8"))["generation_sha256"],
            manifest_b["generation_sha256"],
        )
        self.assertEqual(
            (recovered_destination / "field.pa1").read_bytes(), b"one"
        )
        self.assertEqual(
            probe_pa_family_cache(
                self.cache, identity(), expected_filenames=self.names
            ).generation_directory,
            generation_b,
        )

    def test_missing_or_corrupt_generation_is_never_a_hit_or_overwritten(self) -> None:
        self.assertEqual(probe_pa_family_cache(self.cache, identity()).disposition, CacheDisposition.MISS)
        published = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        (published.generation_directory / "field.pa1").chmod(
            (published.generation_directory / "field.pa1").stat().st_mode | 0o200
        )
        (published.generation_directory / "field.pa1").write_bytes(b"changed")
        probe = probe_pa_family_cache(self.cache, identity(), expected_filenames=self.names)
        self.assertEqual(probe.disposition, CacheDisposition.CORRUPT)
        with self.assertRaisesRegex(PAFamilyCacheError, "refusing to overwrite corrupt"):
            publish_pa_family_cache(self.cache, identity(), self.source, self.names)

    def test_detached_subset_does_not_open_corrupt_unrequested_native_member(self) -> None:
        published = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        native = published.generation_directory / "field.pa1"
        native.chmod(native.stat().st_mode | stat.S_IWUSR)
        native.write_bytes(b"changed")
        manifest = validate_pa_family_cache_subset(
            published.generation_directory,
            ("field.pa#", "field.pa0"),
            expected_cache_key=published.cache_key,
        )
        self.assertEqual(manifest["generation_sha256"], published.generation_sha256)
        with self.assertRaisesRegex(PAFamilyCacheError, "field.pa1"):
            validate_pa_family_cache_subset(
                published.generation_directory,
                ("field.pa1",),
                expected_cache_key=published.cache_key,
            )

    def test_detached_subset_requires_manifest_membership(self) -> None:
        published = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        with self.assertRaisesRegex(PAFamilyCacheError, "absent from the generation manifest"):
            validate_pa_family_cache_subset(
                published.generation_directory,
                ("standalone.pa",),
                expected_cache_key=published.cache_key,
            )

    def test_transient_payload_read_requires_two_consecutive_manifest_matches(self) -> None:
        published = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        real_file_sha256 = cache_generation.file_sha256
        target_reads = 0

        def transient_digest(path: Path) -> str:
            nonlocal target_reads
            if Path(path).name == "field.pa1":
                target_reads += 1
                if target_reads == 1:
                    return "0" * 64
            return real_file_sha256(path)

        with patch.object(cache_generation, "file_sha256", side_effect=transient_digest):
            manifest = validate_pa_family_cache_generation(
                published.generation_directory, expected_filenames=self.names
            )
        self.assertEqual(manifest["generation_sha256"], published.generation_sha256)
        self.assertEqual(target_reads, 3)

    def test_subset_revalidates_when_repair_scan_finds_no_damage(self) -> None:
        published = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        real_validate = pa_family_cache.validate_pa_family_cache_subset
        calls = 0

        def transient_validation(*args: object, **kwargs: object) -> dict[str, object]:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise PAFamilyCacheError("transient payload view")
            return real_validate(*args, **kwargs)

        with patch.object(
            pa_family_cache,
            "validate_pa_family_cache_subset",
            side_effect=transient_validation,
        ), patch.object(
            pa_family_cache,
            "repair_pa_family_cache_generation",
            side_effect=PAFamilyCacheError(
                "PA cache parity repair requires exactly one damaged payload; observed=0"
            ),
        ):
            validated = validate_pa_family_cache_subset_with_repair(
                published.generation_directory,
                ("field.pa1",),
                expected_cache_key=published.cache_key,
            )

        self.assertEqual(calls, 2)
        self.assertEqual(validated.generation_directory, published.generation_directory)
        self.assertIsNone(validated.predecessor_generation_directory)
        self.assertIsNone(validated.repair_receipt_path)

    def test_publication_retries_transient_redundancy_member_view(self) -> None:
        real_create = pa_family_cache.create_xor_parity_bundle
        calls = 0

        def transient_members(*args: object, **kwargs: object) -> dict[str, object]:
            nonlocal calls
            calls += 1
            manifest = real_create(*args, **kwargs)
            if calls == 1:
                manifest = json.loads(json.dumps(manifest))
                manifest["members"][0]["sha256"] = "D" * 64
            return manifest

        with patch.object(
            pa_family_cache,
            "create_xor_parity_bundle",
            side_effect=transient_members,
        ), patch.object(
            pa_family_cache,
            "PAYLOAD_VERIFICATION_RETRY_DELAY_S",
            0,
        ):
            published = publish_pa_family_cache(
                self.cache, identity(), self.source, self.names
            )

        # The three-file fixture has two size groups: the first group is
        # retried once and the second succeeds on its first read.
        self.assertEqual(calls, 3)
        validate_pa_family_cache_generation(
            published.generation_directory,
            expected_cache_key=published.cache_key,
            expected_filenames=self.names,
        )

    @unittest.skipUnless(__import__("os").name == "nt", "Windows PA snapshot recovery")
    def test_large_payload_accepts_manifest_backed_unbuffered_snapshot(self) -> None:
        published = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        target = published.generation_directory / "field.pa1"
        expected = next(
            record for record in published.manifest["files"] if record["name"] == target.name
        )
        real_file_sha256 = cache_generation.file_sha256

        def stale_buffered_digest(path: Path) -> str:
            if Path(path) == target:
                return "D" * 64
            return real_file_sha256(path)

        with patch.object(
            cache_generation, "_WINDOWS_UNBUFFERED_COPY_THRESHOLD_BYTES", 0
        ), patch.object(
            cache_generation, "file_sha256", side_effect=stale_buffered_digest
        ):
            pa_family_cache._verify_payload_record(
                published.generation_directory, expected
            )

        self.assertEqual(target.stat().st_size, expected["bytes"])
        self.assertFalse(target.stat().st_mode & stat.S_IWUSR)

    @unittest.skipUnless(__import__("os").name == "nt", "Windows PA snapshot recovery")
    def test_large_payload_rejects_unbuffered_snapshot_not_matching_manifest(self) -> None:
        published = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        target = published.generation_directory / "field.pa1"
        expected = next(
            record for record in published.manifest["files"] if record["name"] == target.name
        )
        wrong = {**expected, "sha256": "E" * 64}

        with patch.object(
            cache_generation, "_WINDOWS_UNBUFFERED_COPY_THRESHOLD_BYTES", 0
        ), patch.object(cache_generation, "file_sha256", return_value="D" * 64), patch.object(
            cache_generation, "PAYLOAD_VERIFICATION_RETRY_DELAY_S", 0
        ):
            with self.assertRaisesRegex(PAFamilyCacheError, "payload differs"):
                pa_family_cache._verify_payload_record(
                    published.generation_directory, wrong
                )

    def test_persistent_payload_mismatch_reports_expected_and_observed_identity(self) -> None:
        published = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        target = published.generation_directory / "field.pa1"
        target.chmod(target.stat().st_mode | stat.S_IWUSR)
        target.write_bytes(b"changed")
        with self.assertRaises(PAFamilyCacheError) as caught:
            validate_pa_family_cache_generation(published.generation_directory)
        detail = str(caught.exception)
        self.assertIn("field.pa1", detail)
        self.assertIn("expected_bytes=3", detail)
        self.assertIn("expected_sha256=", detail)
        self.assertEqual(detail.count("attempt="), 3)

    def test_source_sidecars_are_excluded_but_missing_or_published_extra_payload_fails_closed(self) -> None:
        (self.source / "unregistered.pa2").write_bytes(b"extra")
        # Run-local source folders also contain GEM/IOB/Lua sidecars.  The
        # declared inventory, not ambient directory contents, selects a PA
        # family; the published generation itself remains exact-only.
        published = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        self.assertEqual(
            [record["name"] for record in published.manifest["files"]], list(self.names)
        )
        (published.generation_directory / "extra.txt").write_text("x", encoding="utf-8")
        with self.assertRaisesRegex(PAFamilyCacheError, "incomplete or has extra"):
            validate_pa_family_cache_generation(published.generation_directory)

    def test_pointer_identity_and_run_destination_preserves_sidecars_but_never_overwrites_pa(self) -> None:
        published = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        pointer = published.generation_directory.parents[1] / "current_generation.json"
        pointer.write_text(json.dumps({"cache_key": "D" * 64, "generation_sha256": published.generation_sha256}), encoding="utf-8")
        self.assertEqual(probe_pa_family_cache(self.cache, identity()).disposition, CacheDisposition.CORRUPT)
        destination = self.root / "existing"
        destination.mkdir()
        (destination / "input.gem").write_text("sidecar", encoding="utf-8")
        materialized = materialize_pa_family_cache(published.generation_directory, destination)
        self.assertEqual(materialized.destination_directory, destination.resolve())
        self.assertTrue((destination / "input.gem").is_file())
        with self.assertRaisesRegex(PAFamilyCacheError, "would overwrite"):
            materialize_pa_family_cache(published.generation_directory, destination)

    def test_publication_refuses_a_held_key_lock(self) -> None:
        key = canonical_pa_family_cache_key(identity())
        with pa_family_cache._protected_key_lock(self.cache, key, 0.0):
            with self.assertRaisesRegex(PAFamilyCacheError, "lock is held"):
                publish_pa_family_cache(
                    self.cache,
                    identity(),
                    self.source,
                    self.names,
                    lock_timeout_s=0.0,
                )

    def test_stale_lock_file_does_not_block_publication_resume(self) -> None:
        key = canonical_pa_family_cache_key(identity())
        lock = self.cache / ".locks" / f"{key}.lock"
        lock.parent.mkdir(parents=True)
        lock.write_text(json.dumps({"cache_key": key, "pid": 999999}), encoding="utf-8")
        published = publish_pa_family_cache(
            self.cache,
            identity(),
            self.source,
            self.names,
            lock_timeout_s=0.0,
            recovery_policy="none",
        )
        self.assertIs(published.disposition, CacheDisposition.PUBLISHED)

    def test_cli_advances_one_transaction_and_materializes(self) -> None:
        identity_path = self.root / "identity.json"
        identity_path.write_text(json.dumps(identity()), encoding="utf-8")
        common = [
            "--cache-root", str(self.cache),
            "--identity", str(identity_path),
            "--filenames", ",".join(self.names),
        ]
        stdout = StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(["--action", "probe", *common]), 0)
        self.assertEqual(json.loads(stdout.getvalue())["disposition"], "miss")

        stdout = StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(["--action", "advance-transaction", *common]), 0)
        building = json.loads(stdout.getvalue())
        self.assertEqual(building["action_required"], "build")
        build = Path(building["build_directory"])
        scratch = Path(building["scratch_directory"])
        scratch.mkdir(exist_ok=True)
        for name in self.names:
            temporary = scratch / f"{name}.partial"
            temporary.write_bytes((self.source / name).read_bytes())
            temporary.replace(build / name)

        stdout = StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(["--action", "advance-transaction", *common]), 0)
        prepared_document = json.loads(stdout.getvalue())
        self.assertEqual(prepared_document["action_required"], "verify")
        prepared = pa_family_cache.TransactionAdvance(
            cache_key=prepared_document["cache_key"],
            status=prepared_document["status"],
            action_required=prepared_document["action_required"],
            transaction_directory=Path(prepared_document["transaction_directory"]),
            build_directory=Path(prepared_document["build_directory"]),
            scratch_directory=Path(prepared_document["scratch_directory"]),
            inventory_sha256=prepared_document["inventory_sha256"],
        )
        evidence_path = self.root / "verification.json"
        evidence_path.write_text(
            json.dumps(self._verification_evidence(prepared)),
            encoding="utf-8",
        )
        stdout = StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(
                main(
                    [
                        "--action", "advance-transaction", *common,
                        "--verification-evidence", str(evidence_path),
                    ]
                ),
                0,
            )
        published = json.loads(stdout.getvalue())
        self.assertEqual(published["status"], "published")
        self.assertEqual(published["action_required"], "complete")

        destination = self.root / "run" / "simion"
        stdout = StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(
                main(
                    [
                        "--action", "materialize", *common,
                        "--destination-directory", str(destination),
                    ]
                ),
                0,
            )
        self.assertEqual(json.loads(stdout.getvalue())["disposition"], "materialized")
        self.assertEqual(
            pa_family_inventory(destination, self.names),
            pa_family_inventory(self.source, self.names),
        )


if __name__ == "__main__":
    unittest.main()
