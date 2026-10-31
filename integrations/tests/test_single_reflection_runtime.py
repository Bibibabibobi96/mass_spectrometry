"""Four-slot preparation tests use inert PA objects, never native field evidence."""
from __future__ import annotations

import json
import io
from contextlib import redirect_stdout
import csv
import copy
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from integrations.runtime.single_flight_source import lua_value as _lua_value
from integrations.tests.test_single_reflection_preparation import fixture, release_fixture, rename_author_instances
from integrations.tests.test_single_reflection_geometry import reframe_parent
from integrations.workflows.single_reflection_flight.prepare import prepare
from integrations.workflows.single_reflection_flight import downstream_fields, runtime
from integrations.workflows.single_reflection_flight.field_plan import frontend_field_identity
from integrations.workflows.single_reflection_flight.runtime import materialize_workbench, _SOURCES
from integrations.workflows.single_reflection_flight.pulse import resolve_phase_flight
from integrations.workflows.single_reflection_flight.runtime import _prepare_context, materialize_batches, prepare_dispatch
from common.simion.particle_batching import plan_single_wave_batches
from common.contracts.write_run_manifest import file_record
from common.simion.pa_family_cache import publish_pa_family_cache
from integrations.runtime.build_single_flight_program import (
    STANDALONE_DYNAMIC_FIELD_BANK_SCHEMA_VERSION, STANDALONE_DYNAMIC_FIELD_BANK_ROLE,
    STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION,
)
from integrations.runtime.single_flight_source import render_restart_fly2
from integrations.runtime.single_flight_frontend import instance_design_record, native_frontend_instances

ROOT = Path(__file__).resolve().parents[2]
LUA = Path("C:/Program Files/SIMION-2020/lua.exe")
BUILDER = ROOT / "integrations/workflows/single_reflection_flight/build_iob.lua"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8", newline="\n")


class WorkbenchMaterializationTests(unittest.TestCase):
    def test_parent_reference_keeps_native_program_instances_particles_and_clock(self):
        results = []
        original = copy.deepcopy(self.geometry)
        for change in ({}, dict(translation=(0.,64.,0.)),
                       dict(rotation=((0.,-1.,0.),(1.,0.,0.),(0.,0.,1.)))):
            geometry = copy.deepcopy(original)
            if change:
                geometry['composition_plan'] = reframe_parent(original['composition_plan'], **change)
            path = Path(self.preparation['outputs']['frontend_geometry']['path'])
            write_json(path, geometry)
            self.preparation['outputs']['frontend_geometry'] = file_record(path)
            context = _prepare_context(self.preparation, self.field_receipt, file_record(self.downstream_path),
                self.run, snapshot_root=self.snapshot, flight=self.flight)
            program, metadata, instances = runtime.compile_case_controls(context, context['source'])
            results.append((program, metadata, instances, render_restart_fly2(context['source']),
                context['flight'], context['source']))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0], results[2])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.addCleanup(self.make_writable)
        request, self.run, _ = fixture(self.root)
        self.preparation = prepare(request, self.run)
        write_json(self.run / "run_config.json", dict(project="instrument_assembly"))
        self.geometry = json.loads((self.run / "inputs/frontend_geometry.json").read_text())
        self.flight = dict(pulse=dict(mode="timed", time_us=10., width_us=3.), maximum_flight_us=200.,
                           maximum_step_us=.001, trajectory_quality=17, rf_steps_per_period=80)
        self.publish_fields()
        # An explicit external producer is valid. It does not force a rebuild
        # when only this consumer's source changes. No solver runs in this test.
        self.producer = self.root / "field_producer"
        self.producer.mkdir()
        assets = []
        for role in ("flight_tube", "reflectron", "detector"):
            names = [role + ".pa"] if role == "reflectron" else [role + suffix for suffix in (".pa#", ".pa0", ".pa1", ".pa-surf")]
            family = []
            for name in names:
                path = self.producer / name
                path.write_bytes(b"INERT_PRODUCER_PAYLOAD_NOT_NATIVE_EVIDENCE")
                family.append(file_record(path))
            carrier = family[0] if role == "reflectron" else family[1]
            assets.append(dict(role=role, carrier_record=carrier,
                representation="standalone_voltageized_static_pa" if role == "reflectron" else "run_private_native_static_family",
                family_records=[] if role == "reflectron" else family))
        producer_geometry = self.producer / "frozen_oatof.json"
        shutil.copyfile(instance_design_record(self.preparation, native_frontend_instances(self.geometry['composition_plan'])[1])["path"], producer_geometry)
        self.downstream = dict(schema_version=1, role="single_reflection_downstream_field_preparation",
            status="success", native_family_origin="generated_in_producer_run", run_directory=str(self.producer),
            oatof_resolved_record=file_record(producer_geometry), assets=assets)
        self.downstream_path = self.producer / "field_receipt.json"
        write_json(self.downstream_path, self.downstream)
        self.snapshot = self.root / "snapshot"
        for name in [*_SOURCES.values(), "integrations/workflows/single_reflection_flight/build_iob.lua"]:
            target = self.snapshot / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        seed = self.snapshot / "common/simion/assets/iob_instance_seeds"
        seed.mkdir(parents=True)
        for name in ["4_instance_seed.iob", "5_instance_seed.iob", *(f"iob_seed_placeholder_{i:02d}.pa0" for i in range(1, 6))]:
            (seed / name).write_bytes(b"INERT_SEED_RESOURCE__NOT_NATIVE_EVIDENCE")

    def publish_fields(self):
        """Create explicit inert publisher records, never native field evidence."""
        design = json.loads((self.run / "inputs/frontend_field_design.json").read_text())
        self.field_directory = self.run / "simion/frontend_fields"
        self.field_directory.mkdir(parents=True, exist_ok=True)
        domains, dynamic, parent_fields = [], [], {}
        for index, domain in enumerate(design["domains"], 1):
            name = domain["domain_id"]
            prefix = "frontend" if name == "parent" else "frontend_entrance_refinement"
            records = []
            for point in design["working_points"]:
                kind = point.get("working_point_id") or point["kind"]
                identity = dict(frontend_field_identity(design, name, member_id=kind,
                    parent_fields=parent_fields if name != "parent" else None),
                    simion_identity={"pure_test": True},
                    builder_identity={"operating_builder": "pure_test", "exporter": "pure_test"})
                identity_path = self.run / "inputs" / (name+"_"+kind+"_field_identity.json")
                write_json(identity_path, identity)
                payload = self.root / "payload" / name / kind
                payload.mkdir(parents=True, exist_ok=True)
                path = payload / f"{prefix}.{kind}.pa"
                if path.exists(): path.chmod(stat.S_IREAD | stat.S_IWRITE)
                path.write_bytes(b"INERT_PA_NOT_NATIVE_EVIDENCE")
                path.chmod(stat.S_IREAD)
                publication = publish_pa_family_cache(self.root / "cache", identity, payload, [path.name], recovery_policy="none")
                audit = self.run / "inputs" / (name+"_"+kind+"_audit.json")
                write_json(audit, dict(status="pass", fixture="inert_not_native_evidence"))
                record = dict(file_record(publication.generation_directory/path.name), kind=point["kind"], read_only=True,
                    cache_key=publication.manifest["cache_key"], generation_directory=str(publication.generation_directory),
                    cache_identity_record=file_record(identity_path), cache_filenames=[path.name],
                    source_schema_version=3, audit_record=file_record(audit), refine_performed=False)
                if point.get("working_point_id"): record["working_point_id"] = point["working_point_id"]
                records.append(record)
                if name == "parent":
                    parent_fields[kind] = dict(cache_key=record["cache_key"], record=record)
            dynamic.append(dict(role="coarse_frontend" if name=="parent" else name, instance_index=index,
                carrier_pa_basename=f"{prefix}.carrier_off.pa",
                **(dict(pulse_delta_pa_basename=f"{prefix}.pulse_delta.pa")
                   if any(point['kind']=='pulse_delta' for point in design['working_points']) else {}),
                **(dict(rf_differential_pa_basenames=[f"{prefix}.rf_reference.pa"],rf_reference_voltage_v=design["rf_reference_voltage_v"])
                   if "rf_reference_voltage_v" in design else {})))
            domains.append(dict(domain_id=name,working_points=records))
        bank_path = self.field_directory / "bank.json"
        write_json(bank_path,dict(schema_version=STANDALONE_DYNAMIC_FIELD_BANK_SCHEMA_VERSION,role=STANDALONE_DYNAMIC_FIELD_BANK_ROLE,
            runtime_representation=STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION,dynamic_roles=dynamic))
        self.field_stage=dict(schema_version=3,role="single_reflection_frontend_working_fields",status="success",
            domains=domains,field_bank_record=file_record(bank_path),
            **(dict(rf_reference_voltage_v=design["rf_reference_voltage_v"]) if "rf_reference_voltage_v" in design else {}))
        self.field_receipt=self.run / "inputs/frontend_field_receipt.json"
        write_json(self.field_receipt,self.field_stage)

    def make_writable(self):
        for path in self.root.rglob("*"):
            if path.is_file():
                path.chmod(stat.S_IREAD | stat.S_IWRITE)

    def materialize(self, **kwargs):
        return materialize_workbench(self.preparation, self.field_receipt, file_record(self.downstream_path),
            self.run, snapshot_root=self.snapshot, flight=kwargs.pop("flight", self.flight), **kwargs)

    def test_control_compilation_creates_no_native_working_files(self):
        context = _prepare_context(self.preparation, self.field_receipt, file_record(self.downstream_path),
                                   self.run, snapshot_root=self.snapshot, flight=self.flight)
        before = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        program, metadata, instances = runtime.compile_case_controls(context, context["source"])
        after = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        case = self.materialize()
        self.assertEqual(program, Path(case["outputs"]["program"]["path"]).read_text())
        self.assertEqual(metadata, case["build_metadata"])
        self.assertEqual(len(instances), len(case["instance_roles"]))

    def check_batches(self, expected_ids):
        prepared = prepare_dispatch(self.preparation,self.field_receipt,file_record(self.downstream_path),
            self.run,snapshot_root=self.snapshot,flight=self.flight,phase="full_instrument")
        self.assertEqual(json.loads(Path(prepared["dispatch_request_path"]).read_text())["particle_count"],len(expected_ids))
        context = _prepare_context(self.preparation,self.field_receipt,file_record(self.downstream_path),
            self.run,snapshot_root=self.snapshot,flight=self.flight)
        source_bytes = Path(context["records"]["projected_source"]["path"]).read_bytes()
        plan = plan_single_wave_batches(len(expected_ids), 2)
        with patch("integrations.workflows.single_reflection_flight.runtime._frontend_fields",
                   side_effect=AssertionError("field verification repeated per batch")):
            result = materialize_batches(self.run,"full_instrument",plan,context=context)
            repeated = materialize_batches(self.run,"full_instrument",plan,context=context)
        self.assertEqual(result,repeated)
        self.assertIsNone(result["gui_case"])
        self.assertNotIn("flight", result["inputs"])
        self.assertFalse(list((self.run / "simion").rglob("flight.json")))
        self.assertTrue(all(case["flight"] == result["flight"] for case in result["batches"]))
        self.assertEqual([pid for case in result["batches"] for pid in case["expected_particle_ids"]],expected_ids)
        for case in result["batches"]:
            low,high=case["source_row_range"]
            self.assertEqual(Path(case["outputs"]["particles"]["path"]).read_text(),
                             render_restart_fly2(context["source"][low-1:high]))
            program=Path(case["outputs"]["program"]["path"]).read_text()
            for native, canonical in enumerate(expected_ids[low-1:high],1):
                self.assertTrue(f"[{native}]={canonical}" in program)
            self.assertEqual(case["merge_offset"],0)
            self.assertEqual(case["simion_particle_id_offset"],0)
        self.assertEqual(Path(context["records"]["projected_source"]["path"]).read_bytes(),source_bytes)
        self.assertFalse(list((self.run/"simion/full_instrument").rglob("*.pa")))
        self.assertFalse(list(self.run.rglob("*workbench_context*")))

    def test_full_batches_slice_original_rows_and_share_validated_fields(self):
        self.check_batches(list(range(1,101)))

    def test_restart_batches_preserve_noncontiguous_source_order(self):
        source_path=Path(self.preparation["outputs"]["projected_source"]["path"])
        with source_path.open(newline="") as stream:
            rows=list(csv.DictReader(stream))
        with source_path.open("w",newline="") as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows([rows[7],rows[6]])
        provenance_path=Path(self.preparation["outputs"]["source_provenance"]["path"])
        provenance=json.loads(provenance_path.read_text())
        provenance.update(source_kind="recorded_pre_pulse_state",particle_count=2,continued_particle_count=2,
                          continued_particle_ids=[8,7],original_mother_particle_ids=list(range(1,101)))
        write_json(provenance_path,provenance)
        self.preparation["outputs"]["projected_source"]=file_record(source_path)
        self.preparation["outputs"]["source_provenance"]=file_record(provenance_path)
        self.preparation["particle_count"]=2
        self.check_batches([8,7])

    def test_frozen_downstream_source_resolves_expired_transport_alias_without_pa_copy(self):
        """The terminal manifest, rather than a retired junction, locates all nine PA members."""
        alias = self.root / "retired_transport_alias"
        canonical_records = []
        receipt = copy.deepcopy(self.downstream)
        receipt["run_directory"] = str(alias)
        for asset in receipt["assets"]:
            records = asset["family_records"] or [asset["carrier_record"]]
            for record in records:
                canonical = Path(record["path"])
                canonical_records.append(file_record(canonical))
                record["path"] = str(alias / canonical.name)
            carrier = asset["carrier_record"]
            carrier["path"] = str(alias / Path(carrier["path"]).name)
        frozen_receipt = self.run / "inputs/downstream_field_source_receipt.json"
        write_json(frozen_receipt, receipt)
        terminal_manifest = self.run / "inputs/downstream_field_source_manifest.json"
        write_json(terminal_manifest, dict(role="simulation_run_manifest", status="failed",
                                           outputs=canonical_records))
        self.preparation["input_records"]["downstream_fields"] = {
            **file_record(frozen_receipt), "source_path": str(alias / "field_receipt.json")}
        self.preparation["input_records"]["downstream_fields_manifest"] = {
            **file_record(terminal_manifest), "source_path": str(self.producer / "run_manifest.json")}
        with patch.object(runtime, "file_record", side_effect=AssertionError("PA source must not be rehashed")), \
                patch.object(runtime.shutil, "copyfile", side_effect=AssertionError("PA source must not be copied")):
            carriers, _, guards = downstream_fields.load_downstream_fields(
                self.preparation["input_records"]["downstream_fields"],
                instance_design_record(self.preparation, native_frontend_instances(self.geometry['composition_plan'])[1]),
                self.preparation["input_records"]["downstream_fields_manifest"])
        self.assertEqual(set(carriers), {"flight_tube", "reflectron", "detector"})
        self.assertEqual(len(guards), 9)
        self.assertFalse(alias.exists())
        self.assertTrue(all(Path(row["path"]).is_relative_to(self.producer) for row in guards))
        for mutation in ("missing_payload", "wrong_identity", "outside_transport_root"):
            with self.subTest(mutation=mutation):
                edited = copy.deepcopy(receipt)
                if mutation == "missing_payload":
                    write_json(terminal_manifest, dict(role="simulation_run_manifest", status="failed", outputs=[]))
                elif mutation == "wrong_identity":
                    edited["assets"][0]["family_records"][0]["sha256"] = "0" * 64
                    write_json(terminal_manifest, dict(role="simulation_run_manifest", status="failed",
                                                       outputs=canonical_records))
                else:
                    edited["assets"][0]["family_records"][0]["path"] = str(self.root / "outside.pa0")
                    write_json(terminal_manifest, dict(role="simulation_run_manifest", status="failed",
                                                       outputs=canonical_records))
                write_json(frozen_receipt, edited)
                source = {**file_record(frozen_receipt), "source_path": str(alias / "field_receipt.json")}
                manifest = {**file_record(terminal_manifest), "source_path": str(self.producer / "run_manifest.json")}
                with self.assertRaises(ValueError):
                    downstream_fields.load_downstream_fields(source, instance_design_record(self.preparation, native_frontend_instances(self.geometry['composition_plan'])[1]), manifest)

    @unittest.skipUnless(os.name == "nt", "Windows execution junction semantics")
    def test_workbench_uses_absolute_execution_paths_without_internal_junctions(self):
        canonical = self.run
        alias = self.root / "execution_alias"
        created = subprocess.run(["cmd", "/c", "mklink", "/J", str(alias), str(canonical)],
                                 cwd=self.root, timeout=30, capture_output=True, text=True, check=False)
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        try:
            self.run = alias
            result = self.materialize()
            spec = Path(result["outputs"]["build_spec"]["path"]).read_text(encoding="utf-8")
            self.assertIn('path="' + (alias / "simion/iob_fields/frontend.carrier_off.pa").as_posix() + '"', spec)
            self.assertNotIn('path="../', spec)
            workbench = alias / "simion/full_instrument"
            self.assertFalse((workbench / "frontend_fields").exists())
            self.assertFalse((workbench / "downstream_fields").exists())
        finally:
            self.run = canonical
            os.rmdir(alias)

    def test_common_frontend_responses_stay_direct_and_only_iob_carriers_are_copied(self):
        """Common fields own science; persistent IOB slots use transport copies."""
        producer_fields = Path(self.field_stage["domains"][0]["working_points"][0]["generation_directory"])
        result = self.materialize()
        frontend_guards = result["pa_guard_records"][:3]
        self.assertEqual({record["path"] for record in frontend_guards},
                         {record["path"] for record in self.field_stage["domains"][0]["working_points"]})
        copies = result["iob_pa_copies"]
        self.assertEqual({row["role"] for row in copies}, {"accelerator", "flight_tube", "reflectron", "detector"})
        self.assertTrue(Path(next(row for row in copies if row["role"] == "accelerator")["source_record"]["path"])
                        .is_relative_to(producer_fields))
        self.assertFalse(any(Path(row["destination"]).exists() for row in copies))
        self.assertFalse(any(row["source_record"].get("kind") in {"rf_reference", "pulse_delta"} for row in copies))
        program = Path(result["outputs"]["program"]["path"]).read_text()
        self.assertNotIn('response_directory=', program)
        for record in self.field_stage["domains"][0]["working_points"][1:]:
            self.assertIn(Path(record["path"]).as_posix(), program)
        build = Path(result["outputs"]["build_spec"]["path"]).read_text()
        for row in copies:
            self.assertIn(Path(row["destination"]).as_posix(), build)
        self.assertEqual(result["iob_pa_guard_records"][:len(result["pa_guard_records"])], result["pa_guard_records"])

    def test_private_frontend_duplicate_cannot_replace_common_member(self):
        record = self.field_stage["domains"][0]["working_points"][0]
        duplicate = self.run / "simion/frontend_working_fields" / Path(record["path"]).name
        duplicate.parent.mkdir(parents=True)
        duplicate.write_bytes(Path(record["path"]).read_bytes())
        duplicate.chmod(stat.S_IREAD)
        record["path"] = str(duplicate)
        write_json(self.field_receipt, self.field_stage)
        with self.assertRaisesRegex(ValueError, "canonical common generation"):
            self.materialize()

    def test_common_metadata_binding_does_not_hash_pa_payload(self):
        with patch("common.simion.pa_family_cache.file_sha256", side_effect=AssertionError("PA payload read")):
            result = self.materialize()
        self.assertTrue(all(Path(record["path"]).is_relative_to(self.root / "cache")
                            for record in result["pa_guard_records"][:3]))

    def invoke_runtime(self, *arguments):
        output = io.StringIO()
        argv = ["runtime", "--preparation", str(self.root / "preparation.json"),
                "--run", str(self.run), "--snapshot-root", str(self.snapshot), *map(str, arguments)]
        with patch.object(sys, "argv", argv), redirect_stdout(output):
            self.assertEqual(runtime.main(), 0)
        return json.loads(output.getvalue())

    def test_cli_checks_without_materializing_then_validates_design_once(self):
        request_path = Path(self.preparation["input_records"]["request"]["path"])
        request = json.loads(request_path.read_text())
        publication = self.root / "publication.json"
        write_json(publication, dict(receipt_record=file_record(self.downstream_path)))

        def freeze_flight(flight):
            request["flight"] = flight
            write_json(request_path, request)
            self.preparation["input_records"]["request"] = file_record(request_path)
            write_json(self.root / "preparation.json", self.preparation)

        freeze_flight(self.flight)
        before = {path for path in self.run.rglob("*") if path.is_file()}
        self.assertTrue(self.invoke_runtime("--check-flight")["flight_validated"])
        self.assertEqual(before, {path for path in self.run.rglob("*") if path.is_file()})
        freeze_flight({**self.flight, "maximum_step_us": 0})
        with self.assertRaises(ValueError):
            self.invoke_runtime("--field-receipt", self.field_receipt, "--downstream-publication", publication)
        self.assertFalse((self.run / "simion/full_instrument").exists())
        freeze_flight(self.flight)
        with patch.object(downstream_fields, "verify_record", wraps=downstream_fields.verify_record) as verified:
            result = self.invoke_runtime("--field-receipt", self.field_receipt, "--downstream-publication", publication)
        design_path = self.preparation["outputs"]["frontend_field_design"]["path"]
        self.assertEqual(sum(call.args[1].get("path") == design_path for call in verified.call_args_list), 1)
        self.assertEqual(result["particle_count"], self.preparation["particle_count"])
        self.assertTrue(Path(result["outputs"]["particles"]["path"]).is_file())

    def test_controls_bind_iob_once_and_reject_wrong_path_or_changed_bytes(self):
        workbench = self.materialize()
        iob = Path(workbench["iob_path"])
        iob.write_bytes(b"INERT_IOB_NOT_NATIVE_EVIDENCE")
        receipt_path = self.root / "workbench.json"
        write_json(receipt_path, workbench)
        with patch.object(runtime, "file_record", wraps=runtime.file_record) as recorded:
            first = self.invoke_runtime("--verify-controls", receipt_path)
        recorded.assert_called_once_with(iob)
        workbench["outputs"]["iob"] = first["iob_record"]
        write_json(receipt_path, workbench)
        with patch.object(runtime, "file_record", side_effect=AssertionError("unnecessary second IOB hash")), \
                patch.object(downstream_fields, "verify_record", wraps=downstream_fields.verify_record) as verified:
            repeated = self.invoke_runtime("--verify-controls", receipt_path)
        self.assertEqual(repeated["iob_record"], first["iob_record"])
        self.assertEqual(sum(call.args[1].get("path") == str(iob) for call in verified.call_args_list), 1)
        other = self.root / "other.iob"
        other.write_bytes(iob.read_bytes())
        workbench["outputs"]["iob"] = file_record(other)
        write_json(receipt_path, workbench)
        with self.assertRaisesRegex(ValueError, "workbench path"):
            self.invoke_runtime("--verify-controls", receipt_path)
        workbench["outputs"]["iob"] = first["iob_record"]
        write_json(receipt_path, workbench)
        iob.write_bytes(b"ALTERED_IOB")
        with self.assertRaises(AssertionError):
            self.invoke_runtime("--verify-controls", receipt_path)

    def test_full_source_encoded_once_and_external_published_fields_are_not_copied(self):
        original = (self.run / "inputs/projected_source.csv").read_bytes()
        with (self.run / "inputs/projected_source.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        result = self.materialize()
        self.assertEqual(result["particle_count"], 100)
        self.assertFalse(result["source_transform_applied"])
        self.assertFalse(result["fly_ready"])
        self.assertNotIn("explicit_pulse_and_flight_numerics", result["pending_validation"])
        self.assertEqual(result["flight"], self.flight)
        self.assertNotIn("flight", result["inputs"])
        self.assertEqual(list((self.run / "simion").rglob("flight.json")), [])
        self.assertEqual((self.run / "inputs/projected_source.csv").read_bytes(), original)
        self.assertEqual(Path(result["outputs"]["particles"]["path"]).read_text(), render_restart_fly2(rows))
        program = Path(result["outputs"]["program"]["path"]).read_text()
        velocities=[[float(row[f"velocity_{axis}_m_s"])/1000 for axis in "xyz"] for row in rows]
        self.assertIn("local single_flight_source_velocity_mm_per_us="+_lua_value(velocities),program)
        self.assertIn("rf_steps_per_period=80", program)
        self.assertIn("adjustable trajectory_quality=17", program)
        self.assertIn("adjustable handoff_pulse_time_us=10", program)
        self.assertIn("adjustable handoff_pulse_width_us=3", program)
        self.assertIn("[100]=100", program)
        self.assertEqual(result["instance_roles"], dict(flight_tube=1, reflectron=2, accelerator=3, detector=4))
        self.assertEqual(len(result["pa_guard_records"]), 12)
        self.assertEqual(len(list((self.run / "simion/full_instrument").rglob("*.pa"))), 0)
        self.assertEqual(len(result["seed_records"]), 5)
        self.assertIn("rf_reference_voltage_v", program)
        self.assertIn("/spec.rf_reference_voltage_v", program)
        for role, values in result["build_metadata"]["provider_placements"].items():
            self.assertTrue(all(isinstance(v, (float, int)) for v in values.values()), role)

    def test_two_published_domains_create_five_slots_without_source_or_pa_copy(self):
        folder = self.root / "fine"
        folder.mkdir()
        request,self.run,_ = fixture(folder,entrance_refinement=True)
        self.preparation = prepare(request,self.run)
        write_json(self.run/"run_config.json",dict(project="instrument_assembly"))
        self.geometry=json.loads((self.run/"inputs/frontend_geometry.json").read_text())
        self.publish_fields()
        original=(self.run/"inputs/projected_source.csv").read_bytes()
        result=self.materialize()
        self.assertEqual(result["particle_count"],100)
        self.assertEqual(len(result["pa_guard_records"]),15)
        self.assertEqual(len(result["seed_records"]),6)
        self.assertEqual(result["instance_roles"]["entrance_refinement"],5)
        self.assertEqual({row["role"] for row in result["iob_pa_copies"]},
                         {"flight_tube", "reflectron", "accelerator", "detector", "entrance_refinement"})
        frontend_copies = [row for row in result["iob_pa_copies"]
                           if row["role"] in {"accelerator", "entrance_refinement"}]
        self.assertTrue(all(row["source_record"]["kind"] == "carrier_off" for row in frontend_copies))
        self.assertTrue(all(Path(row["source_record"]["path"]).is_relative_to(self.root / "cache")
                            for row in frontend_copies))
        self.assertTrue(any(Path(r["path"]).name=="5_instance_seed.iob" for r in result["seed_records"]))
        self.assertEqual((self.run/"inputs/projected_source.csv").read_bytes(),original)
        spec=Path(result["outputs"]["build_spec"]["path"]).read_text()
        self.assertIn('native_priority_occupancy_probes',spec)
        self.assertIn('entrance_refinement:repeller_metal',spec)
        self.assertGreater(result['native_priority_occupancy_expected_counts']['checked_points'],0)
        self.assertIn('entrance_refinement',spec)
        self.assertIn('frontend_entrance_refinement.carrier_off.pa',spec)
        responses = [row for domain in self.field_stage["domains"] for row in domain["working_points"]
                     if row["kind"] != "carrier_off"]
        self.assertEqual(len(responses), 4)
        for response in responses:
            self.assertIn(Path(response["path"]).as_posix(), spec)
            self.assertFalse(any(row["source_record"]["path"] == response["path"] for row in result["iob_pa_copies"]))
        self.assertFalse(result["fly_ready"])

    def test_renamed_full_and_local_recipe_materializes_same_physical_roles(self):
        for local in (False,True):
            with self.subTest(local=local):
                folder=self.root/('renamed_local' if local else 'renamed_full')
                folder.mkdir()
                path,self.run,author,_=release_fixture(folder,local=local)
                rename_author_instances(path,author)
                self.preparation=prepare(path,self.run)
                write_json(self.run/'run_config.json',dict(project='instrument_assembly'))
                self.geometry=json.loads((self.run/'inputs/frontend_geometry.json').read_text())
                self.publish_fields()
                flight={key:value for key,value in self.flight.items() if not local or key!='rf_steps_per_period'}
                source=(self.run/'inputs/projected_source.csv').read_bytes()
                result=self.materialize(flight=flight)
                self.assertEqual(result['particle_count'],100)
                self.assertEqual(result['instance_roles'],dict(flight_tube=1,reflectron=2,accelerator=3,detector=4))
                self.assertEqual(len(result['pa_guard_records']),11 if local else 12)
                self.assertEqual((self.run/'inputs/projected_source.csv').read_bytes(),source)
                provenance=json.loads((self.run/'inputs/source_provenance.json').read_text())
                self.assertEqual(provenance['source_instance_id'],'tof_b')
                self.assertEqual(result['clock_epoch_id'],provenance['clock_epoch_id'])
                self.assertFalse(result['fly_ready'])

    def test_local_oatof_complete_source_uses_two_fields_and_same_four_roles(self):
        folder=self.root/"local_oatof"
        folder.mkdir()
        request,self.run,_,_=release_fixture(folder,local=True)
        self.preparation=prepare(request,self.run)
        write_json(self.run/"run_config.json",dict(project="instrument_assembly"))
        self.geometry=json.loads((self.run/"inputs/frontend_geometry.json").read_text())
        self.publish_fields()
        flight={key:value for key,value in self.flight.items() if key!="rf_steps_per_period"}
        original=(self.run/"inputs/projected_source.csv").read_bytes()
        result=self.materialize(flight=flight)
        self.assertEqual(result["particle_count"],100)
        self.assertEqual(len(result["pa_guard_records"]),11)
        self.assertEqual(result["instance_roles"],dict(flight_tube=1,reflectron=2,accelerator=3,detector=4))
        self.assertEqual(result["build_metadata"]["physical_rod_piece_count"],0)
        self.assertEqual(result["build_metadata"]["physical_frontend_topology_id"],"three_zone_frontend_contract_derived_v1")
        self.assertEqual((self.run/"inputs/projected_source.csv").read_bytes(),original)
        self.assertEqual(result["flight"],flight)
        program=Path(result["outputs"]["program"]["path"]).read_text()
        self.assertNotIn("single_flight_rf_kernel",program)
        self.assertNotIn("adjustable single_flight_rf_peak_v",program)
        self.assertNotIn("frontend.rf_reference.pa",program)
        self.assertEqual(result["clock_epoch_id"],json.loads((self.run/"inputs/source_provenance.json").read_text())["clock_epoch_id"])
        with (self.run/"inputs/projected_source.csv").open(newline="") as stream: rows=list(csv.DictReader(stream))
        velocities=[[float(row[f"velocity_{axis}_m_s"])/1000 for axis in "xyz"] for row in rows]
        self.assertIn("local single_flight_source_velocity_mm_per_us="+_lua_value(velocities),program)
        self.assertEqual({float(row["mass_amu"]) for row in rows},{524.})
        self.assertEqual({float(row["instrument_time_us"]) for row in rows},{42.125})
        self.assertFalse(result["fly_ready"])

    def test_missing_refinement_receipt_or_parent_identity_rejected_before_materialization(self):
        folder = self.root / "fine_missing"
        folder.mkdir()
        request,self.run,_=fixture(folder,entrance_refinement=True)
        self.preparation=prepare(request,self.run)
        write_json(self.run/"run_config.json",dict(project="instrument_assembly"))
        self.geometry=json.loads((self.run/"inputs/frontend_geometry.json").read_text())
        self.publish_fields()
        original=copy.deepcopy(self.field_stage)
        for case in ("missing_domain","parent_identity","missing_field"):
            stage=copy.deepcopy(original)
            if case=="missing_domain": stage["domains"].pop()
            elif case=="parent_identity": stage["domains"][0]["working_points"][0]["cache_key"]="0"*64
            else: stage["domains"][1]["working_points"].pop()
            write_json(self.field_receipt,stage)
            with self.subTest(case=case),self.assertRaises(ValueError): self.materialize()
            self.assertFalse((self.run/"simion/full_instrument").exists())

    def test_downstream_wrong_provider_cache_origin_or_missing_surface_rejected_before_output(self):
        for field in ("provider", "cache", "surface"):
            with self.subTest(field=field):
                value = json.loads(json.dumps(self.downstream))
                if field == "provider":
                    value["oatof_resolved_record"]["sha256"] = "0" * 64
                elif field == "cache":
                    value["native_family_origin"] = "copied_from_published_cache"
                else:
                    value["assets"][0]["family_records"].pop()
                write_json(self.downstream_path, value)
                with self.assertRaises(ValueError):
                    self.materialize()
                self.assertFalse((self.run / "simion/full_instrument").exists())

    def test_frontend_physical_identity_drift_and_missing_publication_fail(self):
        original_key = self.field_stage["domains"][0]["working_points"][0]["cache_key"]
        self.field_stage["domains"][0]["working_points"][0]["cache_key"] = "0" * 64
        write_json(self.field_receipt, self.field_stage)
        with self.assertRaisesRegex(ValueError, "prepared domain/parent/GEM"):
            self.materialize()
        self.field_stage["domains"][0]["working_points"][0]["cache_key"] = original_key
        write_json(self.field_receipt, self.field_stage)
        self.downstream_path.unlink()
        with self.assertRaises((AssertionError, ValueError)):
            self.materialize()
        self.assertFalse((self.run / "simion/full_instrument").exists())

    def test_frontend_old_role_reference_and_kind_drift_are_rejected(self):
        original = json.loads(json.dumps(self.field_stage))
        for mutation in ("old_role", "reference", "old_kind"):
            with self.subTest(mutation=mutation):
                stage = json.loads(json.dumps(original))
                if mutation == "old_role": stage["role"] = "rf_oatof_local_frontend_field_stage"
                elif mutation == "reference": stage["rf_reference_voltage_v"] *= 2
                else: stage["domains"][0]["working_points"][1]["kind"] = "rf_differential_unit"
                write_json(self.field_receipt, stage)
                with self.assertRaises(ValueError):
                    self.materialize()
                self.assertFalse((self.run / "simion/full_instrument").exists())

    def test_frozen_source_drift_and_missing_snapshot_module_have_no_repo_fallback(self):
        frozen = self.run / "inputs/projected_source.csv"
        original = frozen.read_bytes()
        frozen.write_bytes(original + b"\n")
        with self.assertRaises(AssertionError):
            self.materialize()
        frozen.write_bytes(original)
        (self.snapshot / _SOURCES["pulse_hook_source"]).unlink()
        with self.assertRaises(FileNotFoundError):
            self.materialize()
        self.assertFalse((self.run / "simion/full_instrument").exists())

    def discovery_inputs(self):
        folder = self.root / "discovery_author"
        folder.mkdir()
        request, self.run, _ = fixture(folder)
        author = {**self.flight,"pulse":dict(mode="discover",width_us=.25,candidate_times_us=[-2.,.5,3.])}
        value = json.loads(request.read_text())
        value["flight"] = author
        write_json(request,value)
        self.preparation = prepare(request,self.run)
        write_json(self.run/"run_config.json",dict(project="instrument_assembly"))
        self.geometry = json.loads((self.run/"inputs/frontend_geometry.json").read_text())
        self.publish_fields()
        return author

    def decision(self, author):
        collection = dict(phase="discovery",native_complete=True,
            request_record=self.preparation['input_records']['request'],
            geometry_record=self.preparation['outputs']['frontend_geometry'],
            field_design_record=self.preparation['outputs']['frontend_field_design'],
            source_record=self.preparation['outputs']['projected_source'],
            clock_epoch_id=json.loads((self.run/'inputs/source_provenance.json').read_text())['clock_epoch_id'],
            flight=resolve_phase_flight(author,phase='discovery'))
        collection_path=self.run/'results/discovery/collection.json'
        write_json(collection_path,collection)
        decision=dict(schema_version=2,role='single_reflection_actual_occupancy_pulse_decision',status='success',
            input_records=dict(collection=file_record(collection_path),request=self.preparation['input_records']['request'],
                               frontend_geometry=self.preparation['outputs']['frontend_geometry']),
            candidate_times_us=author['pulse']['candidate_times_us'],pulse_width_us=author['pulse']['width_us'],
            actual_pulse_time_us=.5,selection=dict(status='selected',selected_time_us=.5),
            selection_uses_future_terminal_outcome=False)
        decision_path=self.run/'results/discovery/pulse_decision.json'
        write_json(decision_path,decision)
        return decision_path,decision

    def test_discovery_and_selected_workbench_share_source_fields_and_keep_controls(self):
        author=self.discovery_inputs()
        original=(self.run/'inputs/projected_source.csv').read_bytes()
        discovery=self.materialize(flight=author,phase='discovery')
        before={name:Path(record['path']).read_bytes() for name,record in discovery['outputs'].items()}
        decision_path,decision=self.decision(author)
        timed=self.materialize(flight=author,pulse_decision_record=file_record(decision_path))
        self.assertEqual(discovery['phase'],'discovery')
        self.assertEqual(timed['phase'],'full_instrument')
        self.assertEqual(discovery['pa_guard_records'],timed['pa_guard_records'])
        self.assertEqual(Path(discovery['outputs']['particles']['path']).read_bytes(),Path(timed['outputs']['particles']['path']).read_bytes())
        self.assertEqual((self.run/'inputs/projected_source.csv').read_bytes(),original)
        self.assertEqual(discovery['source_record'],timed['source_record'])
        for name,data in before.items():self.assertEqual(Path(discovery['outputs'][name]['path']).read_bytes(),data)
        self.assertEqual(discovery['flight'],resolve_phase_flight(author,phase='discovery'))
        actual=timed['flight']
        self.assertEqual(actual['pulse'],dict(mode='timed',time_us=.5,width_us=.25))
        self.assertNotIn('observation_times_us',actual)
        self.assertEqual(timed['inputs']['pulse_decision'],file_record(decision_path))
        self.assertFalse(timed['fly_ready'])
        with self.assertRaisesRegex(ValueError,'overwrite'):self.materialize(flight=author,phase='discovery')

    def test_discovery_successor_rejects_missing_negative_or_misbound_decision(self):
        author=self.discovery_inputs()
        with self.assertRaises(ValueError):self.materialize(flight=author)
        decision_path,decision=self.decision(author)
        for key,value in [('status','no_supported_candidate'),('actual_pulse_time_us',True),('pulse_width_us',1.),
                          ('selection_uses_future_terminal_outcome',True)]:
            bad=copy.deepcopy(decision);bad[key]=value;write_json(decision_path,bad)
            with self.subTest(key=key),self.assertRaises(ValueError):
                self.materialize(flight=author,pulse_decision_record=file_record(decision_path))
        bad=copy.deepcopy(decision);bad['input_records']['request']['sha256']='0'*64;write_json(decision_path,bad)
        with self.assertRaisesRegex(ValueError,'request differs'):
            self.materialize(flight=author,pulse_decision_record=file_record(decision_path))
        collection_path=Path(decision['input_records']['collection']['path'])
        collection=json.loads(collection_path.read_text());collection['native_complete']=False;write_json(collection_path,collection)
        decision['input_records']['collection']=file_record(collection_path);write_json(decision_path,decision)
        with self.assertRaisesRegex(ValueError,'complete actual discovery'):
            self.materialize(flight=author,pulse_decision_record=file_record(decision_path))
        self.assertFalse((self.run/'simion/full_instrument').exists())
        with self.assertRaises(ValueError):resolve_phase_flight(self.flight,phase='discovery')
        local={k:v for k,v in author.items() if k!='rf_steps_per_period'}
        self.assertNotIn('rf_steps_per_period',resolve_phase_flight(local,phase='discovery',requires_rf=False))

    def test_held_off_flight_is_frozen_without_fictitious_timing(self):
        flight = {**self.flight,"pulse":{"mode":"held_off"}}
        result = self.materialize(flight=flight)
        self.assertEqual(result["flight"],flight)
        program = Path(result["outputs"]["program"]["path"]).read_text()
        self.assertNotIn("handoff_pulse_time_us",program)
        self.assertNotIn("instrument_time_us=%.12g tof_since_pulse_us=",program)
        self.assertFalse(result["fly_ready"])

    def test_missing_or_invalid_flight_fails_before_any_workbench_artifact(self):
        with self.assertRaises(ValueError): self.materialize(flight=None)
        for key in self.flight:
            for value in (None, True, float("nan")):
                with self.subTest(key=key, value=value):
                    flight = dict(self.flight)
                    if value is None: flight.pop(key)
                    else: flight[key] = value
                    with self.assertRaises(ValueError): self.materialize(flight=flight)
                    self.assertFalse((self.run / "simion/full_instrument").exists())

    def test_held_off_compiles_without_pulse_payload_but_keeps_all_carrier_slots(self):
        case=self.root/'held_off_case';case.mkdir()
        request,self.run,document=fixture(case)
        document['flight']={**self.flight,'pulse':{'mode':'held_off'}}
        write_json(request,document)
        self.preparation=prepare(request,self.run)
        write_json(self.run/'run_config.json',dict(project='instrument_assembly'))
        self.geometry=json.loads((self.run/'inputs/frontend_geometry.json').read_text())
        self.publish_fields()
        context=_prepare_context(self.preparation,self.field_receipt,file_record(self.downstream_path),self.run,
                                 snapshot_root=self.snapshot,flight=document['flight'])
        self.assertNotIn('pulse_delta',context['fields']['parent'])
        self.assertNotIn('pulse_delta_pa_basename',context['dynamic']['dynamic_roles'][0])
        program,metadata,instances=runtime.compile_case_controls(context,context['source'])
        self.assertEqual(len(instances),4)
        self.assertEqual(len(metadata['rf_instance_order']),1)
        self.assertNotIn('frontend.pulse_delta.pa',program)
        self.assertIn('local handoff_pulse_mode=2',program)


class NativePriorityOccupancyProbeTests(unittest.TestCase):
    def setUp(self):
        self.geometry = dict(accelerator_projection=dict(negative_x_face_mm=1., shield_wall_mm=2.,
            port_center_y_mm=3., port_center_z_mm=2., numerical_port_width_mm=2., numerical_port_height_mm=2.))
        self.design = dict(surface="none", domains=[
            dict(domain_id="parent", instance_origin_mm=dict(x=0., y=0., z=0.),
                 cell_mm_xyz=dict(x=1., y=2., z=1.),
                 dimensions=dict(nx=11, ny=6, nz=11),
                 bounds_mm=dict(x_min=0., x_max=10., y_min=0., y_max=10., z_min=0., z_max=10.),
                 physical_samples=[dict(label="repeller_metal", kind="endpoint", electrode_id=12, gu=[3, 2, 2]),
                                   dict(label="ring_metal", kind="ring", electrode_id=16, gu=[3, 4, 7])]),
            dict(domain_id="entrance_refinement", instance_origin_mm=dict(x=0., y=2., z=0.),
                 cell_mm_xyz=dict(x=.5, y=.5, z=.5),
                 dimensions=dict(nx=21, ny=13, nz=11),
                 bounds_mm=dict(x_min=0., x_max=10., y_min=2., y_max=8., z_min=0., z_max=5.),
                 active_bounds_mm=dict(x_min=.5, x_max=9.5, y_min=2.5, y_max=7.5, z_min=.5, z_max=4.5),
                 physical_samples=[dict(label="repeller_metal", kind="endpoint", electrode_id=12, gu=[6, 2, 4])])])

    def test_frozen_named_samples_preserve_identity_and_numerical_transition_basis(self):
        probes = {row['label']: row for row in runtime.native_priority_occupancy_probes(self.geometry, self.design)}
        self.assertEqual(probes['parent:repeller_metal']['point_mm'], [3., 4., 2.])
        self.assertEqual(probes['parent:repeller_metal']['expected_instance'], 5)
        self.assertEqual(probes['parent:ring_metal']['expected_instance'], 3)
        fine = probes['entrance_refinement:repeller_metal']
        self.assertEqual(fine['point_mm'], [3., 3., 2.])
        self.assertEqual(fine['basis']['electrode_id'], 12)
        self.assertNotIn('expected_electrode', fine)
        self.assertTrue(fine['expected_adjacent_metal_cell'])
        self.assertTrue(fine['expected_node_electrode'])
        self.assertEqual(probes['fine_y_min_inside']['point_mm'], [5., 2.5, 2.5])
        self.assertEqual(probes['fine_y_min_outside']['point_mm'], [5., 1., 2.5])
        self.assertEqual(probes['fine_y_min_outside']['expected_instance'], 3)
        self.assertEqual(probes['fine_z_max_inside']['expected_instance'], 5)
        opening = probes['provider_side_opening_center']
        self.assertEqual(opening['point_mm'], [2., 3., 2.])
        self.assertNotIn('expected_electrode', opening)

    def test_ideal_sheets_keep_source_node_checks_and_boundary_world_queries_are_observations(self):
        parent, fine = self.design['domains']
        parent['physical_samples'] += [
            dict(label='ideal_grid', kind='ideal_sheet', electrode_id=13, gu=[3, 2, 3]),
            dict(label='exit_sheet', kind='ideal_sheet', electrode_id=15, gu=[3, 2, 10]),
            dict(label='fine_face_metal', kind='ring', electrode_id=17, gu=[3, 1, 2])]
        fine['physical_samples'].append(dict(label='outer_metal', kind='ground', electrode_id=11, gu=[0, 2, 4]))
        before = copy.deepcopy(self.design)
        probes = {row['label']: row for row in runtime.native_priority_occupancy_probes(self.geometry, self.design)}
        sheet = probes['parent:ideal_grid']
        self.assertNotIn('expected_electrode', sheet)
        self.assertNotIn('expected_adjacent_metal_cell', sheet)
        self.assertEqual(sheet['expected_instance'], 5)
        self.assertTrue(sheet['expected_node_electrode'])
        self.assertEqual(sheet['basis']['sample_kind'], 'ideal_sheet')
        for label in ('parent:exit_sheet', 'parent:fine_face_metal', 'entrance_refinement:outer_metal'):
            with self.subTest(label=label):
                probe = probes[label]
                self.assertTrue(probe['expected_node_electrode'])
                self.assertNotIn('expected_instance', probe)
                self.assertNotIn('expected_electrode', probe)
                self.assertEqual(probe['basis']['world_query_scope'], 'numerical_boundary_observation')
        self.assertEqual(len([row for row in probes.values() if row.get('expected_node_electrode')]), 7)
        self.assertEqual(self.design, before)

    def test_parent_volume_uses_active_coverage_but_raw_instance_query_keeps_raw_bounds(self):
        parent, fine = self.design['domains']
        for y, masked in ((4., True), (2., False), (2.5, False), (8., False)):
            with self.subTest(y=y):
                parent['cell_mm_xyz']['y'] = .5
                parent['dimensions']['ny'] = 21
                parent['physical_samples'][0]['gu'][1] = y / .5
                probes = {row['label']: row for row in runtime.native_priority_occupancy_probes(self.geometry, self.design)}
                probe = probes['parent:repeller_metal']
                self.assertEqual('expected_adjacent_metal_cell' not in probe, masked)
                if y == 2.5:
                    self.assertEqual(probe['expected_instance'], 5)
        parent['physical_samples'][0]['gu'][1] = 8
        for field, value in (('label', 'other'), ('kind', 'ideal_sheet'), ('electrode_id', 99)):
            changed = copy.deepcopy(self.design)
            changed['domains'][1]['physical_samples'][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'lacks its fine physical sample'):
                runtime.native_priority_occupancy_probes(self.geometry, changed)
        fine['physical_samples'] = []
        with self.assertRaisesRegex(ValueError, 'lacks its fine physical sample'):
            runtime.native_priority_occupancy_probes(self.geometry, self.design)

    def test_fractional_surface_requires_its_own_volume_contract(self):
        self.design['surface'] = 'fractional'
        with self.assertRaisesRegex(ValueError, 'surface=none'):
            runtime.native_priority_occupancy_probes(self.geometry, self.design)

    def test_terminal_cell_neighbors_remain_observations_without_object_attribution(self):
        terminal = dict(particle_id=77, instance=5., x_mm=3., y_mm=3., z_mm=2., instrument_time_us=9.)
        original = dict(terminal)
        probes = runtime.native_priority_occupancy_probes(self.geometry, self.design, terminal_observations=[terminal])
        terminal_probes = [row for row in probes if row['label'].startswith('terminal_')]
        self.assertEqual(len(terminal_probes), 7)
        self.assertEqual(terminal_probes[0]['point_mm'], [3., 3., 2.])
        self.assertEqual(terminal_probes[1]['point_mm'], [2.5, 3., 2.])
        self.assertEqual(terminal_probes[-1]['point_mm'], [3., 3., 2.5])
        for row in terminal_probes:
            self.assertNotIn('expected_electrode', row)
            self.assertNotIn('expected_instance', row)
            self.assertNotIn('expected_node_electrode', row)
            self.assertEqual(row['basis']['particle_id'], 77)
        self.assertEqual(terminal, original)


@unittest.skipUnless(LUA.is_file(), "plain Lua interpreter unavailable")
class FourSlotIobTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        request, run, _ = fixture(self.root)
        prepare(request, run)
        self.geometry = json.loads((run / "inputs/frontend_geometry.json").read_text())
        self.interface_oatof = json.loads((run / "inputs/components/oatof/resolved_design.json").read_text())
        self.rows = []
        domains = {"flight_tube" if r["role"] == "flight_tube_shield" else r["role"]: r
                   for r in self.geometry["downstream_pa_instances"]}
        for index, role in enumerate(("flight_tube", "reflectron", "accelerator", "detector"), 1):
            if role == "accelerator":
                grid = dict(self.geometry["numerical_domains"]["parent"]["dimensions"])
                grid.update({f"d{a}_mm": self.geometry["numerical_domains"]["parent"]["cell_mm_xyz"][a] for a in "xyz"})
                placement = {f"{a}_mm": self.geometry["numerical_domains"]["parent"]["instance_origin_mm"][a] for a in "xyz"}
                placement["az_deg"] = 0.
            else:
                row = domains[role]
                grid = {key: row[key] for key in ("nx", "ny", "nz")}
                numerical = row["grid_numerics"]
                pitches = ([numerical["cell_xy_mm"], numerical["cell_xy_mm"], numerical["cell_z_mm"]]
                           if role == "detector" else
                           [numerical["cell_axial_mm"], numerical["cell_radial_mm"], numerical["cell_radial_mm"]])
                grid.update(dict(zip(("dx_mm", "dy_mm", "dz_mm"), pitches, strict=True)))
                placement = {key: row[key] for key in ("x_mm", "y_mm", "z_mm", "az_deg")}
            placement.update(el_deg=0., rt_deg=0., scale=1.)
            self.rows.append(dict(role=role, instance_index=index, priority_number=index, path=(self.root / (role + ".pa")).as_posix(),
                                  grid=grid, placement=placement))
        self.output = self.root / "instrument.iob"
        self.program = self.output.with_suffix(".lua")
        self.particles = self.output.with_suffix(".fly2")
        self.program.write_bytes(b"EXACT_PREPARED_PROGRAM\n")
        self.particles.write_bytes(b"EXACT_PROJECTED_PARTICLES\n")

    def invoke(self, mode="success"):
        responses = [dict(domain="parent" if row["role"] == "accelerator" else row["role"],
                          kind=kind, path=(self.root / (row["role"] + "." + kind + ".pa")).as_posix(), grid=row["grid"])
                     for row in self.rows if row["role"] in {"accelerator", "entrance_refinement"}
                     for kind in ("rf_reference", "pulse_delta")]
        spec = dict(schema_version=1, role="single_reflection_iob_build", instances=self.rows,
                    response_fields=responses,
                    interface_field_probes=runtime.interface_field_probes(self.geometry, self.interface_oatof),
                    native_priority_occupancy_probes=[
                        dict(label="known_metal", point_mm=[0., 0., 0.], expected_instance=3, expected_electrode=True,
                             expected_node_electrode=True, expected_adjacent_metal_cell=True, basis=dict(kind='resolved_physical_sample',
                                 domain_id='parent', sample_kind='endpoint', gu=[7, 8, 9])),
                        dict(label="known_vacuum", point_mm=[1., 0., 0.], expected_instance=3, expected_electrode=False),
                        dict(label="terminal_observation", point_mm=[2., 0., 0.])],
                    seed_iob=(self.root / f"{len(self.rows)}_instance_seed.iob").as_posix(), output_iob=self.output.as_posix())
        first_probe = spec['native_priority_occupancy_probes'][0]
        if mode in {'verify_source_fine', 'verify_crop_fine_layer'}:
            first_probe['basis']['domain_id'] = 'entrance_refinement'
        if mode in {'verify_source_sheet', 'verify_source_sheet_missing'}:
            first_probe['basis']['sample_kind'] = 'ideal_sheet'
            first_probe['expected_electrode'] = False
            first_probe.pop('expected_adjacent_metal_cell')
        if mode in {'verify_source_boundary', 'verify_source_boundary_missing'}:
            first_probe.pop('expected_instance')
            first_probe.pop('expected_electrode')
            first_probe['basis']['world_query_scope'] = 'numerical_boundary_observation'
        if mode == 'verify_crop_fine_layer':
            first_probe['expected_instance'] = 5
        if mode.startswith('verify_crop_'):
            # Exact 3x3x3 flag patterns observed in native 132337, with the
            # original world queries retained; different metal IDs are allowed.
            second = mode == 'verify_crop_e44'
            first_probe.update(point_mm=[-193.36362184380704 if second else -277.86362184380704,
                                         15.5 if second else 12.5, -18.429186803411028])
            first_probe.pop('expected_electrode')
            first_probe['basis']['gu'] = [3 if second else 2, 2, 2]
            g = first_probe['basis']['gu']
            spec['fixture_nodes'] = {}
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        metal = dx <= 0
                        if mode in {'verify_crop_layer', 'verify_crop_fine_layer'}:
                            metal = dx == 0
                        if mode == 'verify_crop_node_missing' and (dx,dy,dz) == (0,0,0):
                            metal = False
                        value = (10 if second and dx == -1 else 44 if second else 9) if metal else 0
                        spec['fixture_nodes'][f'n_{g[0]+dx}_{g[1]+dy}_{g[2]+dz}'] = [value, metal]
        if mode == 'verify_missing_probes':
            spec.pop('native_priority_occupancy_probes')
        if mode == 'verify_missing_interfaces':
            spec.pop('interface_field_probes')
        if mode in {'verify_interface_endpoint_roundoff', 'verify_interface_outside'}:
            # Exact frozen 093627 endpoint arithmetic: 1 ULP above nz-1.
            self.rows[2]['placement']['z_mm'] = -41.929186803411028
            self.rows[2]['grid'].update(nz=3201, dz_mm=.1)
            for point in spec['interface_field_probes'][0]['points_mm']:
                point[2] = 278.07081319658903 + (1e-6 if mode.endswith('outside') else 0.)
        spec_path = self.root / "build_spec.lua"
        spec_path.write_text("return " + _lua_value(spec) + "\n", encoding="utf-8")
        mock = self.root / "mock.lua"
        mock.write_text("""local spec=dofile(arg[1])
local builder,mode=arg[2],arg[3]
local calls=0
simion={wb={instances={}},pas={}}
local reference_closed=false
local response_active=false
local response_closed=0
local probe_calls=0
function simion.wb:find_at(x,y,z)
 assert(calls==1 and reference_closed,'native points must query the independently reopened IOB')
 probe_calls=probe_calls+1
 local probe=assert(spec.native_priority_occupancy_probes[probe_calls])
 assert(x==probe.point_mm[1] and y==probe.point_mm[2] and z==probe.point_mm[3],'probe coordinates changed')
 if mode=='verify_outside' and probe_calls==2 then return end
 local electrode=probe_calls==1
 local instance=probe_calls==3 and 5 or 3
 if (mode=='verify_priority' or mode=='verify_crop_priority') and probe_calls==1 then instance=2 end
 if mode:match('^verify_crop_') and probe_calls==1 then electrode=false end
 if mode=='verify_crop_fine_layer' and probe_calls==1 then instance=5 end
 if mode=='verify_electrode' and probe_calls==2 then electrode=true end
 if mode=='verify_numeric_electrode' and probe_calls==1 then electrode=1 end
 if mode=='verify_observed_metal' and probe_calls==3 then electrode=true end
 if mode:match('^verify_source_') and probe_calls==1 then electrode=false;instance=2 end
 if mode=='verify_source_node_missing' and probe_calls==1 then electrode=true;instance=3 end
 if (mode=='verify_source_sheet' or mode=='verify_source_sheet_missing') and probe_calls==1 then electrode=false;instance=3 end
 if (mode=='verify_source_boundary' or mode=='verify_source_boundary_missing') and probe_calls==1 then electrode=false;instance=1 end
 return electrode,instance,nil
end
function simion.pas:open(...)
 if select('#',...)==1 then
  assert(mode:match('^verify') and calls==0,'responses must load before the saved IOB')
  assert(not response_active,'responses must not coexist in memory')
  local path=...
  if mode=='verify_response_missing' then error('inert response path missing: '..path) end
  local row=assert(spec.response_fields[response_closed+1])
  assert(row.path==path,'actual response path changed')
  local pa={}
  for key,value in pairs(row.grid) do pa[key]=value end
  function pa:point() return 0,true end
  function pa:potential_vc(x,y,z)
   if mode=='verify_interface_endpoint_roundoff' or mode=='verify_interface_outside' then
    assert(z<=self.nz-1,'fixture z outside PA')
   end
   return mode=='verify_interface_response' and 1 or 0
  end
  function pa:inside_vc() return true end
  function pa:field_vc() return 0,0,17 end
  if mode=='verify_response_grid' then pa.dx_mm=pa.dx_mm*2 end
  response_active=true
  function pa:close() assert(response_active);response_active=false;response_closed=response_closed+1 end
  return pa
 end
 assert(select('#',...)==0,'path reference must be unloaded')
 local values={}
 local reference={}
 function reference:close() reference_closed=true end
 function reference:load() error('path comparison cannot load PA bytes') end
 return setmetatable(reference,{
  __newindex=function(_,key,value)
   assert(key=='path')
   local parts={}
   for part in value:gsub('\\\\','/'):gmatch('[^/]+') do
    if part=='..' then assert(#parts>0);table.remove(parts)
    elseif part~='.' then parts[#parts+1]=part end
   end
   values.path=(value:sub(1,1)=='/' and '/' or '')..table.concat(parts,'/')
  end,
  __index=values,
 })
end
function simion.command(command)
 calls=calls+1
 local verifying=mode:match('^verify')~=nil
 if verifying then assert(not response_active and response_closed==#spec.response_fields,'responses were not all closed') end
 assert(command=='"'..(verifying and spec.output_iob or spec.seed_iob)..'"','wrong workbench input')
 for index,row in ipairs(spec.instances) do
  local pa={}
  function pa:load()
   assert(self.filename==row.path,'wrong PA source')
   for k,v in pairs(row.grid) do self[k]=v end
   if mode=='wrong_grid' and index==2 then self.nx=self.nx+1 end
  end
  simion.wb.instances[index]={pa=pa,_debug_update_size=function() end}
  if verifying then
   pa.path=row.path;pa.filename=row.path:match('[^/]+$')
   if mode=='verify_dot_path' then
    pa.path=row.path:gsub('/([^/]+)$','/extra/.././%1')
   end
   for k,v in pairs(row.grid) do pa[k]=v end
   local item=simion.wb.instances[index];local p=row.placement
   item.x,item.y,item.z=p.x_mm,p.y_mm,p.z_mm
   item.az,item.el,item.rt,item.scale=p.az_deg,p.el_deg,p.rt_deg,p.scale
   function pa:point(x,y,z)
    if z==1000 or index==2 then return 0,mode~='verify_interface_metal' end
    assert(index==((mode=='verify_source_fine' or mode=='verify_crop_fine_layer') and 5 or 3),'wrong physical-sample source instance')
    local probe=spec.native_priority_occupancy_probes[1]
    if spec.fixture_nodes then
     local value=assert(spec.fixture_nodes['n_'..x..'_'..y..'_'..z],'fixture queried beyond observed neighborhood')
     return value[1],value[2]
    end
    assert(x>=6 and x<=8 and y>=7 and y<=9 and z>=8 and z<=10,'source neighborhood changed')
    return 4372.125,not (mode=='verify_source_node_missing' or mode=='verify_source_sheet_missing' or mode=='verify_source_boundary_missing')
   end
   function item:wb_to_pa_coords(x,y,z)
    if z~=0 then return 1000,1000,1000 end
    if spec.fixture_nodes then return unpack(spec.native_priority_occupancy_probes[1].basis.gu) end
    assert(x==0 and y==0 and z==0,'diagnostic world point moved')
    return .25,-1.5,2.75
   end
   function item:pa_to_wb_coords(x,y,z)
    if spec.fixture_nodes then return unpack(spec.native_priority_occupancy_probes[1].point_mm) end
    assert(x==7 and y==8 and z==9,'diagnostic source node moved')
    return 17.125,18.25,19.5
   end
   function item:inside_wc(x,y,z)
    if spec.fixture_nodes then return true end
    assert(x==0 and y==0 and z==0,'inside query moved')
    return mode=='verify_source_parent'
   end
   function pa:load() error('verify cannot reload or replace a PA') end
   function pa:potential_vc() return mode=='verify_interface_potential' and 1 or 0 end
   function pa:inside_vc() return true end
   function pa:field_vc()
    if mode=='verify_interface_nonfinite' then return 0/0,0,0 end
    return index==2 and 2.5 or 0,0,index==3 and 23 or 0
   end
   function item:pa_to_wb_orient(x,y,z) if index==2 then return -z,y,x end return x,y,z end
   if index==5 and mode=='verify_fine_grid' then pa.nx=pa.nx+1 end
   if index==2 then
    if mode=='verify_grid' then pa.nx=pa.nx+1 end
    if mode=='verify_pose' then item.x=item.x+1 end
    if mode=='verify_path' then pa.path='C:/other.pa' end
    if mode=='verify_same_basename' then pa.path='C:/other/'..row.path:match('[^/]+$') end
   end
  end
 end
 if mode=='wrong_slots' then simion.wb.instances[#spec.instances+1]={} end
end
function simion.wb:load_particles(path)
 assert(path==spec.output_iob:gsub('%.iob$','.fly2'))
end
function simion.wb:save(path)
 assert(path==spec.output_iob and calls==1)
 for index,row in ipairs(spec.instances) do
  local item=self.instances[index];local p=row.placement
  assert(item.pa.filename==row.path)
  assert(item.x==p.x_mm and item.y==p.y_mm and item.z==p.z_mm)
  assert(item.az==p.az_deg and item.el==p.el_deg and item.rt==p.rt_deg and item.scale==p.scale)
  assert(item.nz_use==nil,'cylindrical PA must not acquire planar extrusion')
 end
 for _,extension in ipairs({'.lua','.fly2'}) do
  local f=assert(io.open(path:gsub('%.iob$',extension),'wb'));f:write('SEED_OVERWRITE');f:close()
 end
 if mode=='save_failure' then error('inert save failure') end
 local f=assert(io.open(path,'wb'));f:write('INERT_IOB_NOT_NATIVE');f:close()
end
arg={arg[1],mode:match('^verify') and 'verify' or nil}
dofile(builder)
if mode:match('^verify') then assert(reference_closed,'temporary path reference was not closed') end
""", encoding="utf-8", newline="\n")
        return subprocess.run([str(LUA), str(mock), str(spec_path), str(BUILDER), mode],
                              cwd=self.root, capture_output=True, text=True, timeout=20)
    def test_four_physical_slots_keep_provider_pose_and_prepared_companions(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("INSTANCES=4", result.stdout)
        self.assertEqual(self.program.read_bytes(), b"EXACT_PREPARED_PROGRAM\n")
        self.assertEqual(self.particles.read_bytes(), b"EXACT_PROJECTED_PARTICLES\n")

    def test_fifth_numerical_domain_uses_public_seed_and_reopens_exact_grid(self):
        fine = copy.deepcopy(self.rows[2])
        fine.update(role="entrance_refinement",instance_index=5,priority_number=5,
                    path=(self.root / "frontend_entrance_refinement.carrier_off.pa").as_posix())
        # Inert IOB API fixture: same envelope, finer cells; no native field claim.
        for axis in "xyz":
            fine["grid"]["n"+axis] = 2*fine["grid"]["n"+axis]-1
            fine["grid"]["d"+axis+"_mm"] /= 2
        self.rows.append(fine)
        result = self.invoke()
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn("INSTANCES=5",result.stdout)
        reopened = self.invoke("verify_success")
        self.assertEqual(reopened.returncode,0,reopened.stdout+reopened.stderr)
        self.assertIn("entrance_refinement FLY=False",reopened.stdout)
        wrong = self.invoke("verify_fine_grid")
        self.assertNotEqual(wrong.returncode,0)
        self.assertIn("saved PA grid differs: entrance_refinement",wrong.stdout+wrong.stderr)
        self.assertEqual(self.program.read_bytes(),b"EXACT_PREPARED_PROGRAM\n")
        self.assertEqual(self.particles.read_bytes(),b"EXACT_PROJECTED_PARTICLES\n")

    def test_failed_physical_sample_records_native_source_node_without_accepting_mismatch(self):
        fine = copy.deepcopy(self.rows[2])
        fine.update(role='entrance_refinement', instance_index=5, priority_number=5,
                    path=(self.root / 'fine.carrier_off.pa').as_posix())
        self.rows.append(fine)
        for mode, instance, inside in (('verify_source_parent', 3, 'true'),
                                       ('verify_source_fine', 5, 'false')):
            with self.subTest(mode=mode):
                result = self.invoke(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('native priority/occupancy point mismatch: known_metal', result.stderr)
                self.assertNotIn('NATIVE_PRIORITY_OCCUPANCY=PASS', result.stdout)
                self.assertEqual(result.stdout.count('SINGLE_REFLECTION_NATIVE_POINT '), 3)
                self.assertEqual(result.stdout.count('SINGLE_REFLECTION_NATIVE_SOURCE_NODE '), 1)
                self.assertIn(f'source_instance={instance} gu_x=7 gu_y=8 gu_z=9', result.stdout)
                self.assertIn('node_voltage_v=4372.125 node_electrode=true', result.stdout)
                self.assertIn('world_to_pa_x_gu=0.25 world_to_pa_y_gu=-1.5 world_to_pa_z_gu=2.75', result.stdout)
                self.assertIn('node_world_x_mm=17.125 node_world_y_mm=18.25 node_world_z_mm=19.5', result.stdout)
                self.assertIn(f'inside_source={inside} selected_instance=2', result.stdout)
                self.assertIn('terminal_observation', result.stdout)
                self.assertFalse(self.output.exists())
                self.assertEqual(self.program.read_bytes(), b'EXACT_PREPARED_PROGRAM\n')
                self.assertEqual(self.particles.read_bytes(), b'EXACT_PROJECTED_PARTICLES\n')

    def test_integer_nodes_remain_required_for_metal_ideal_sheets_and_boundary_observations(self):
        for mode, accepted in (('verify_source_node_missing', False),
                               ('verify_source_sheet', True), ('verify_source_sheet_missing', False),
                               ('verify_source_boundary', True), ('verify_source_boundary_missing', False)):
            with self.subTest(mode=mode):
                result = self.invoke(mode)
                self.assertEqual(result.returncode == 0, accepted, result.stdout + result.stderr)
                line = next(row for row in result.stdout.splitlines()
                            if row.startswith('SINGLE_REFLECTION_NATIVE_POINT label="known_metal"'))
                self.assertIn(f'source_node_electrode={str(accepted).lower()} expected_node_electrode=true', line)
                self.assertIn('check=' + ('pass' if accepted else 'failed'), line)
                if 'boundary' in mode:
                    self.assertIn('electric_instance=1', line)
                    self.assertIn('expected_electrode=nil expected_instance=nil', line)
                if accepted:
                    self.assertIn('NATIVE_PRIORITY_OCCUPANCY=PASS CHECKED=2 OBSERVED=1', result.stdout)
                    self.assertNotIn('SINGLE_REFLECTION_NATIVE_SOURCE_NODE', result.stdout)
                else:
                    self.assertIn('native priority/occupancy point mismatch: known_metal', result.stderr)
                    self.assertNotIn('NATIVE_PRIORITY_OCCUPANCY=PASS', result.stdout)
                self.assertEqual(result.stdout.count('SINGLE_REFLECTION_NATIVE_POINT '), 3)
                self.assertFalse(self.output.exists())

    def test_recorded_crop_nodes_require_adjacent_volume_without_moving_world_queries(self):
        for mode in ('verify_crop_e9','verify_crop_e44','verify_crop_layer',
                     'verify_crop_node_missing','verify_crop_priority'):
            with self.subTest(mode=mode):
                result = self.invoke(mode)
                accepted = mode in {'verify_crop_e9','verify_crop_e44'}
                self.assertEqual(result.returncode == 0, accepted, result.stdout + result.stderr)
                line = next(row for row in result.stdout.splitlines()
                            if row.startswith('SINGLE_REFLECTION_NATIVE_POINT label="known_metal"'))
                self.assertIn('electrode=false', line)
                self.assertIn('expected_electrode=nil', line)
                self.assertIn('adjacent_metal_cells=' + ('4' if accepted or mode == 'verify_crop_priority' else '0'), line)
                self.assertIn('check=' + ('pass' if accepted else 'failed'), line)
                if accepted:
                    self.assertIn('SINGLE_REFLECTION_IOB_REOPEN=PASS',result.stdout)
                else:
                    self.assertIn('native priority/occupancy point mismatch',result.stderr)
                self.assertFalse(self.output.exists())

    def test_fine_nonideal_metal_cannot_use_an_isolated_node_sheet_as_volume(self):
        fine = copy.deepcopy(self.rows[2])
        fine.update(role='entrance_refinement', instance_index=5, priority_number=5,
                    path=(self.root / 'fine.carrier_off.pa').as_posix())
        self.rows.append(fine)
        result = self.invoke('verify_crop_fine_layer')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('source_instance=5', result.stdout)
        self.assertIn('adjacent_metal_cells=0', result.stdout)
        self.assertIn('native priority/occupancy point mismatch', result.stderr)

    def test_wrong_grid_or_seed_slot_count_fails_before_iob_save(self):
        for mode in ("wrong_grid", "wrong_slots"):
            with self.subTest(mode=mode):
                result = self.invoke(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.output.exists())

    def test_failed_iob_save_restores_exact_program_and_particles(self):
        result = self.invoke("save_failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("inert save failure", result.stderr)
        self.assertEqual(self.program.read_bytes(), b"EXACT_PREPARED_PROGRAM\n")
        self.assertEqual(self.particles.read_bytes(), b"EXACT_PROJECTED_PARTICLES\n")

    def test_independent_reopen_verifies_saved_slots_without_mutating_pa_or_controls(self):
        for mode in ('verify','verify_dot_path','verify_grid','verify_pose','verify_path','verify_same_basename'):
            with self.subTest(mode=mode):
                result=self.invoke(mode)
                self.assertEqual(result.returncode==0,mode in {'verify','verify_dot_path'},result.stdout+result.stderr)
                if mode in {'verify','verify_dot_path'}:
                    self.assertIn('SINGLE_REFLECTION_IOB_REOPEN=PASS',result.stdout)
                self.assertEqual(self.program.read_bytes(),b'EXACT_PREPARED_PROGRAM\n')
                self.assertEqual(self.particles.read_bytes(),b'EXACT_PROJECTED_PARTICLES\n')
                self.assertFalse(self.output.exists(), 'read-only verify must never save a workbench')

    def test_response_paths_load_sequentially_and_grid_or_missing_path_fails_before_iob(self):
        for mode in ('verify_success', 'verify_response_grid', 'verify_response_missing'):
            with self.subTest(mode=mode):
                result = self.invoke(mode)
                self.assertEqual(result.returncode == 0, mode == 'verify_success', result.stdout + result.stderr)
                if mode == 'verify_success':
                    self.assertEqual(result.stdout.count('SINGLE_REFLECTION_RESPONSE_PATH_GRID=PASS'), 2)
                else:
                    self.assertNotIn('SINGLE_REFLECTION_IOB_REOPEN=PASS', result.stdout)
                    self.assertIn('response grid differs' if mode.endswith('grid') else 'response path missing',
                                  result.stdout + result.stderr)
                self.assertFalse(self.output.exists())

    def test_actual_point_api_checks_priority_and_occupancy_but_never_invents_terminal_expectations(self):
        for mode in ('verify_success', 'verify_observed_metal', 'verify_priority', 'verify_electrode', 'verify_numeric_electrode', 'verify_outside', 'verify_missing_probes'):
            with self.subTest(mode=mode):
                result = self.invoke(mode)
                accepted = mode in {'verify_success', 'verify_observed_metal'}
                self.assertEqual(result.returncode == 0, accepted, result.stdout + result.stderr)
                if accepted:
                    self.assertIn('NATIVE_PRIORITY_OCCUPANCY=PASS CHECKED=2 OBSERVED=1 SCOPE=declared_points_only', result.stdout)
                elif mode != 'verify_missing_probes':
                    self.assertEqual(result.stdout.count('SINGLE_REFLECTION_NATIVE_POINT'), 3)
                    self.assertIn('terminal_observation', result.stdout)
                    self.assertIn('native priority/occupancy point mismatch', result.stderr)
                    self.assertNotIn('SINGLE_REFLECTION_IOB_REOPEN=PASS', result.stdout)
                self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
