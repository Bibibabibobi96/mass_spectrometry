"""Pure source projection tests; no SIMION process or external artifact needed."""
from __future__ import annotations

import csv
import copy
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import unittest
from unittest.mock import patch

from common.contracts.canonical_clock_authority import validate_clock_authority
from common.contracts.component_particle_state import write_component_particle_state_csv
from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis import measured_component_source as source_module
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.measured_component_source import (
    materialize_measured_source, materialize_measured_source_slice, materialize_centroid_probe,
    author_measured_centroid_prism_target,
)
from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis import test_ion_processor_handoff as fixtures


class MeasuredCentroidTargetTests(unittest.TestCase):
    @staticmethod
    def evidence():
        from common.contracts.particle_physics import speed_m_s_from_kinetic_energy_ev, kinetic_energy_ev
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_dual_stripe_l0_math import converging_prism_fixture
        contract, _, reference = converging_prism_fixture()
        record = lambda name: dict(path="C:/synthetic-unit-evidence/"+name+".json",bytes=1,sha256="ab"*32)
        records={name:record(name) for name in ("event_field_audit","audit_request","controller_projection",
                                               "source_receipt","trajectory_contract","design_target")}
        canonical, binding=record("canonical"),record("binding")
        mass,charge=524.,1
        h=4364.5339559932+5.
        def point(name,event,time,position,axes,phi):
            velocity=[speed_m_s_from_kinetic_energy_ev(mass,e) for e in axes]
            velocity[2]*=-1
            kinetic=kinetic_energy_ev(mass,*velocity)
            query=dict(sample_id=name,event=event,instrument_time_us=time,position_mm=position,
                       velocity_m_s=velocity,kinetic_energy_per_charge_ev=kinetic)
            return query,dict(query,phi_v=phi,k_over_q_plus_phi_v=kinetic+phi)
        birth,birth_row=point("source_centroid","source_centroid",100.,[.01,-55.,0.],[2.,.1,4364.5339559932-2.1],5.)
        clean,clean_row=point("event_000001","central_plane_directional",101.,[.03,9.29765627041,0.],
                              [3.,2.,h-11.-3.-2.],11.)
        source=dict(role="mrtof_measured_exit_centroid_probe_source",counts=dict(source=1,transferred=1,not_transferred=0),
            mass_amu=mass,charge_state=charge,centroid_kinetic_energy_eV=birth["kinetic_energy_per_charge_ev"],
            mean_particle_kinetic_energy_eV=4364.822522004543,solver_epoch_instrument_time_us=100.,
            outputs=dict(component_particle_state=canonical))
        request=dict(schema_version=1,role="mrtof_actual_probe_event_field_audit_request",mass_amu=mass,charge_state=charge,
            inputs=dict(source_receipt=records["source_receipt"],canonical_source=canonical,projection=records["controller_projection"],candidate_binding=binding),
            points=[birth,clean])
        audit=dict(schema_version=1,role="mrtof_actual_probe_event_energy_field_audit",status="reported",
            potential_authority="actual_materialized_scalar_native_PA__scalar_adapter_raw_sample",
            inputs=dict(request=records["audit_request"]),samples=[birth_row,clean_row],source_centroid_h_over_q_v=h)
        values=[0.]*20;values[10:12]=[-27.36410265968425]*2
        projection=dict(role="mrtof_measured_exit_centroid_controller_projection",inputs=dict(source_receipt=records["source_receipt"]),field_authority_projection=dict(
            role="mrtof_measured_centroid_live_field_projection",binding_record=binding,analyzer_electrode_voltages_v=values))
        design=dict(schema_version=1,role="mrtof_measured_centroid_closure_target_authority",prism_handoff_target=reference,
            inputs=dict(interface_energy_field_audit=record("old-audit"),trajectory_contract=records["trajectory_contract"],mother_source_receipt=record("mother")),
            target_slow_turn_y_mm=360.,target_k=24.5,target_positive_mirror_turn_y_mm=0.,target_low_field_tangent_ratio_vy_over_vz=.03506096645)
        return dict(event_field_audit=audit,audit_request=request,controller_projection=projection,source_receipt=source,
                    trajectory_contract=contract,design_target=design,stripe_1_voltage_v=values[10],input_records=records)

    def test_partition_uses_actual_phi_and_ex_not_unclosed_ky_or_oa_energy(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_l0 import converging_design_potential_delta_v
        evidence=self.evidence();before=copy.deepcopy(evidence)
        result=author_measured_centroid_prism_target(**evidence)
        target=result["target_authority"];model=target["prism_handoff_target"];ledger=result["authoring_ledger"]
        self.assertEqual(evidence,before)
        self.assertAlmostEqual(ledger["source_h_over_q_v"],4369.5339559932)
        self.assertAlmostEqual(ledger["available_clean_yz_energy_ev_per_q"],4355.5339559932)
        self.assertNotEqual(model["axial_energy_per_charge_v"],before["design_target"]["prism_handoff_target"]["axial_energy_per_charge_v"])
        self.assertNotEqual(model["axial_energy_per_charge_v"],ledger["source_h_over_q_v"])
        self.assertNotAlmostEqual(model["clean_reference_slow_energy_per_charge_v"],2.)
        self.assertAlmostEqual(model["axial_energy_per_charge_v"]+model["clean_reference_slow_energy_per_charge_v"],4355.5339559932)
        psi=converging_design_potential_delta_v(model,evidence["stripe_1_voltage_v"],9.29765627041)
        self.assertAlmostEqual(model["clean_reference_slow_energy_per_charge_v"]+psi,model["slow_energy_reference_per_charge_v"],places=9)
        self.assertEqual(target["source_energy_ledger"]["mean_particle_kinetic_energy_ev_per_q"],4364.822522004543)
        self.assertEqual((target["target_slow_turn_y_mm"],target["target_k"]),(360.,24.5))
        self.assertEqual(model["angle_tolerance_degrees"],.01)
        self.assertNotEqual(model["energy_tolerance_per_charge_v"],before["design_target"]["prism_handoff_target"]["energy_tolerance_per_charge_v"])
        angle=math.asin(math.sqrt(model["clean_reference_slow_energy_per_charge_v"]/model["total_energy_reference_per_charge_v"]))
        self.assertAlmostEqual(ledger["clean_target_angle_degrees"],math.degrees(angle))
        self.assertFalse(result["physical_matching_qualified"])

    def test_invalid_or_incomplete_actual_ledger_fails_closed(self):
        for scenario in ("nan_phi","missing_phi","missing_ex_state","charge","wrong_binding","wrong_source","bad_K","bad_H","no_clean","no_partition","bad_geometry"):
            with self.subTest(scenario=scenario):
                evidence=self.evidence();audit=evidence["event_field_audit"]
                if scenario=="nan_phi": audit["samples"][1]["phi_v"]=math.nan
                elif scenario=="missing_phi": del audit["samples"][1]["phi_v"]
                elif scenario=="missing_ex_state": audit["samples"][1]["velocity_m_s"]=audit["samples"][1]["velocity_m_s"][1:]
                elif scenario=="charge": evidence["source_receipt"]["charge_state"]=0
                elif scenario=="wrong_binding": evidence["controller_projection"]["field_authority_projection"]["binding_record"]=dict(bytes=1,sha256="cd"*32)
                elif scenario=="wrong_source": evidence["source_receipt"]["outputs"]["component_particle_state"]=dict(bytes=2,sha256="cd"*32)
                elif scenario=="bad_K": audit["samples"][0]["kinetic_energy_per_charge_ev"]+=1
                elif scenario=="bad_H": audit["samples"][1]["k_over_q_plus_phi_v"]+=1
                elif scenario=="no_clean": audit["samples"][1]["event"]="other"
                elif scenario=="no_partition": evidence["design_target"]["prism_handoff_target"]["slow_energy_reference_per_charge_v"]=10000.
                else: evidence["design_target"]["prism_handoff_target"]["single_mirror_angle_degrees"]*=2
                with self.assertRaises(ValueError):
                    author_measured_centroid_prism_target(**evidence)


class MeasuredComponentSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = fixtures.IonProcessorHandoffTests("test_preserves_full_state_clock_identity_and_complete_census")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.output = self.root / "source_prepared"
        # A frozen source clock, owned by the original producer run.
        self.epoch = self.root / "inputs/instrument_epoch.json"
        self.epoch.parent.mkdir()
        self._write(self.epoch, {"instrument_time_us": 0})
        self.clock = self.root / "inputs/clock_authority.json"
        self._write(self.clock, {
            "schema_version": 1, "role": "canonical_clock_authority",
            "clock_epoch_id": "ion_processor_epoch_zero_v1", "instrument_time_unit": "us",
            "canonical_time_basis": "instrument_epoch_absolute_time",
            "authority": {"path": "inputs/instrument_epoch.json", "field": "instrument_time_us", "sha256": file_sha256(self.epoch)},
            "solver_local_time_basis": "elapsed_time_from_zero_us",
            "adapter_materialization": "instrument_time_us_equals_authority_epoch_plus_solver_elapsed_once",
            "handoff_policy": "preserve_instrument_time_us_and_clock_epoch_id", "legacy_new_campaign_allowed": False,
        })
        self.fixture.receipt["source_run"] = str(self.root)
        self.fixture.receipt["inputs"] = {"inputs/resolved_model.json": self._identity(self.fixture.model),
                                          "inputs/clock_authority.json": self._identity(self.clock),
                                          "inputs/instrument_epoch.json": self._identity(self.epoch)}
        self._write(self.fixture.receipt_path, self.fixture.receipt)
        self.fixture.rename_instances()
        self.fixture._prepare()
        self.handoff = self.fixture.output / "handoff_receipt.json"

    @staticmethod
    def _write(path: Path, value: dict) -> None:
        path.write_text(json.dumps(value) + "\n", encoding="utf-8")

    @staticmethod
    def _identity(path: Path) -> dict:
        return {"path": str(path), "bytes": path.stat().st_size, "sha256": file_sha256(path)}

    def test_old_or_missing_handoff_connection_is_explicitly_unsupported(self) -> None:
        original = json.loads(self.handoff.read_text())
        for scenario in ("version", "connection"):
            with self.subTest(scenario=scenario):
                changed = dict(original)
                if scenario == "version":
                    changed["schema_version"] = 1
                else:
                    changed.pop("connection")
                self._write(self.handoff, changed)
                with self.assertRaisesRegex(ValueError, "Unsupported|instances differ"):
                    self._materialize()
                self.assertFalse(self.output.exists())
        self._write(self.handoff, original)

    def _materialize(self) -> dict:
        return materialize_measured_source(self.handoff, self.output)

    def _refresh_handoff_output(self, key: str, path: Path) -> None:
        receipt = json.loads(self.handoff.read_text())
        receipt["outputs"][key] = self._identity(path)
        self._write(self.handoff, receipt)

    def test_centroid_is_separate_probe_and_keeps_full_mother_provenance(self) -> None:
        import math
        from common.contracts.particle_physics import kinetic_energy_ev
        original = self._materialize()
        with (self.output / "component_particle_state.csv").open() as handle:
            varied = list(csv.DictReader(handle))
        for row in varied:
            row["position_z_mm"] = 0.0
        varied[0]["velocity_x_m_s"] = "321"
        varied[0]["kinetic_energy_eV"] = kinetic_energy_ev(float(varied[0]["mass_amu"]), *(float(varied[0][f"velocity_{a}_m_s"]) for a in "xyz"))
        write_component_particle_state_csv(self.output / "component_particle_state.csv", varied)
        original["outputs"]["component_particle_state"] = self._identity(self.output / "component_particle_state.csv")
        self._write(self.output / "source_receipt.json", original)
        original_bytes = (self.output / "component_particle_state.csv").read_bytes()
        probe = self.root / "centroid"
        receipt = materialize_centroid_probe(self.output, probe)
        with (self.output / "component_particle_state.csv").open() as handle:
            mother = list(csv.DictReader(handle))
        with (probe / "component_particle_state.csv").open() as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["state_event"], "constructed_measured_exit_centroid")
        self.assertEqual(receipt["counts"], dict(source=1, transferred=1, not_transferred=0))
        self.assertEqual(receipt["mother_counts"], original["counts"])
        for key in ["instrument_time_us", *[f"position_{a}_mm" for a in "xyz"], *[f"velocity_{a}_m_s" for a in "xyz"]]:
            self.assertEqual(float(row[key]), math.fsum(float(r[key]) for r in mother)/len(mother))
        expected = kinetic_energy_ev(float(row["mass_amu"]), *(float(row[f"velocity_{a}_m_s"]) for a in "xyz"))
        self.assertEqual(float(row["kinetic_energy_eV"]), expected)
        self.assertAlmostEqual(sum(receipt["centroid_axis_energy_eV"].values()), expected)
        self.assertLess(expected, receipt["mean_particle_kinetic_energy_eV"])
        self.assertEqual((probe / "mother_component_particle_state.csv").read_bytes(), original_bytes)
        self.assertEqual((self.output / "component_particle_state.csv").read_bytes(), original_bytes)
        batch = materialize_measured_source_slice(probe, self.root / "probe_batch", 1, 1)
        self.assertEqual(batch["source_cohort"], "constructed_measured_exit_centroid_probe")
        self.assertEqual(batch["original_particle_ids"], [1])

    def test_scheduler_slice_keeps_full_epoch_and_original_id(self) -> None:
        full = self._materialize()
        output = self.root / "batch"
        result = materialize_measured_source_slice(self.output, output, 2, 2)
        self.assertEqual(result["original_particle_ids"], [7])
        self.assertEqual(result["solver_epoch_instrument_time_us"], full["solver_epoch_instrument_time_us"])
        with (output / "ordinal_source_map.csv").open(newline="") as handle:
            row = next(csv.DictReader(handle))
        self.assertEqual(int(row["simion_ordinal"]), 1)
        self.assertEqual(int(row["particle_id"]), 7)
        self.assertGreater(float(row["solver_birth_time_us"]), 0)
        self.assertEqual((output / "source_census.csv").read_bytes(),
                         (self.output / "source_census.csv").read_bytes())
        self.assertEqual((output / "component_particle_state.csv").read_bytes(),
                         (self.output / "component_particle_state.csv").read_bytes())
        (self.output / "source_states.lua").write_text("return {}", encoding="utf-8")
        with self.assertRaises(ValueError):
            materialize_measured_source_slice(self.output, self.root / "tampered_batch", 1, 1)

    def test_materialization_reuses_typed_rows_clock_binding_and_one_projection(self) -> None:
        # Captured from the same fixture before removing duplicate work.
        expected = {
            "source_states.lua": "2cc8ad12f0afc127714dc30a0d560d0d194843a32fad071e4df989d7aedbffb3",
            "source_runtime.lua": "251daa47d2fe1aa219c1bc6c24a5f2e464f3db4335298507ade475fb072a4343",
            "source_projection.lua": "ef16c44767b92aa33665833cef907793d9a89b26db51d7d0bc35e5bdac4ac281",
            "source_census.csv": "ae48592bfdaa6502969b09de70a5cc593b688660dea88f3d0299728009aff5df",
            "ordinal_source_map.csv": "4a31bf63cce2bb5f4f3d58e112fc2b241e41dcad6c0426a779cee5f2fd53062c",
        }
        with patch.object(source_module, "_project_rows", wraps=source_module._project_rows) as project, \
                patch.object(source_module, "load_component_particle_state_csv", wraps=source_module.load_component_particle_state_csv) as read_rows, \
                patch.object(source_module, "_bound", wraps=source_module._bound) as bind, \
                patch.object(source_module, "file_sha256", wraps=source_module.file_sha256) as digest:
            report = self._materialize()
        self.assertEqual(project.call_count, 1)
        canonical = self.fixture.output / "component_particle_state.csv"
        self.assertEqual(sum(Path(call.args[0]).resolve() == canonical.resolve() for call in read_rows.call_args_list), 1)
        for path in (self.clock, self.epoch):
            self.assertEqual(sum(Path(call.args[0]["path"]).resolve() == path.resolve() for call in bind.call_args_list), 1)
        self.assertEqual(sum(Path(call.args[0]).resolve() == self.clock.resolve() for call in digest.call_args_list), 1)
        self.assertEqual(report["inputs"]["upstream_clock"], self._identity(self.clock))
        self.assertEqual(report["counts"], {"source": 3, "transferred": 2, "not_transferred": 1})
        self.assertEqual(report["birth_offsets_us"], [0.0, 0.05999999999949068])
        for name, sha in expected.items():
            self.assertEqual(file_sha256(self.output / name), sha.upper(), name)
        self.assertEqual((self.output / "component_particle_state.csv").read_bytes(), canonical.read_bytes())

    def test_irregular_ids_birth_offsets_and_exact_six_dimensions(self) -> None:
        report = self._materialize()
        self.assertEqual(report["counts"], {"source": 3, "transferred": 2, "not_transferred": 1})
        self.assertFalse(report["solver_execution"])
        self.assertTrue(report["source_materialization_ready"])
        self.assertEqual((self.output / "component_particle_state.csv").read_bytes(),
                         (self.fixture.output / "component_particle_state.csv").read_bytes())
        self.assertEqual((self.output / "source_census.csv").read_bytes(), self.fixture.census.read_bytes())
        with (self.output / "ordinal_source_map.csv").open(newline="") as handle:
            mapping = list(csv.DictReader(handle))
        self.assertEqual([int(row["particle_id"]) for row in mapping], [1, 7])
        self.assertEqual([int(row["simion_ordinal"]) for row in mapping], [1, 2])
        self.assertEqual(float(mapping[0]["solver_birth_time_us"]), 0)
        self.assertGreater(float(mapping[1]["solver_birth_time_us"]), 0)
        for original, mapped in zip(self.fixture.rows, mapping):
            self.assertEqual(float(mapped["instrument_time_us"]), original["instrument_time_us"])
            self.assertEqual(report["solver_epoch_instrument_time_us"] + float(mapped["solver_birth_time_us"]), original["instrument_time_us"])
        companion = (self.output / "source_states.lua").read_text()
        blocks = re.findall(r"\[(\d+)\]=\{([^}]+)\}", companion)
        self.assertEqual(len(blocks), 2)
        for (_, values), original in zip(blocks, self.fixture.rows):
            state = {key: float(value) for key, value in (item.split("=") for item in values.split(","))}
            for axis in "xyz":
                self.assertEqual(state[f"v{axis}"], original[f"velocity_{axis}_m_s"] / 1000)
            self.assertEqual(state["x"], original["position_x_mm"])
            self.assertEqual(state["y"], original["position_y_mm"] - 225)
            self.assertEqual(state["z"], original["position_z_mm"])
        self.assertIn("direction = vector(0.05,0.1,-37.8)", (self.output / "source.fly2").read_text())
        self.assertEqual(validate_clock_authority(self.output / "clock_authority.json", self.output)["status"], "PASS")

    def test_tampered_import_fails_before_output(self) -> None:
        path = self.fixture.output / "component_particle_state.csv"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self._materialize()
        self.assertFalse(self.output.exists())

    def test_runtime_initialize_obeys_read_only_engine_tof_and_fly2_birth_offsets(self) -> None:
        lua = shutil.which("lua")
        if lua is None:
            installed = Path("C:/Program Files/SIMION-2020/lua.exe")
            lua = str(installed) if installed.exists() else None
        if lua is None:
            self.skipTest("plain Lua interpreter unavailable; no solver fallback")
        report = self._materialize()
        times = [float(value) for value in re.findall(r"tob = ([^,]+),", (self.output / "source.fly2").read_text())]
        self.assertEqual(times, report["birth_offsets_us"])
        self.assertEqual(times[0], 0)
        self.assertGreater(times[1], 0)
        script = self.root / "read_only_tof_fixture.lua"
        script.write_text(r'''
local directory=assert(arg[1])
local chunk=assert(loadfile(directory..'/source_runtime.lua'))
local pure_environment=setmetatable({}, {
  __index=function(_,key)
    assert(not key:match('^ion_'),'pure module read a SIMION reserved variable: '..key)
    return _G[key]
  end,
  __newindex=function(_,key) error('pure module wrote global '..key) end})
setfenv(chunk,pure_environment)
local runtime=chunk().load(directory)
local point=assert(loadfile(directory..'/source_projection.lua'))()
local beams
local fly=assert(loadfile(directory..'/source.fly2'))
setfenv(fly,{particles=function(value) beams=value end,
  standard_beam=function(value) return value end,vector=function(...) return {...} end})
fly()
local states=assert(loadfile(directory..'/source_states.lua'))()
assert(#beams==#point.mapping,'FLY2 population differs from ordinal map')
for ordinal,mapping in ipairs(point.mapping) do
  local engine_t=mapping.solver_birth_time_us -- FLY2-owned clock in the native callback.
  local state=runtime.initialize(ordinal)
  assert(state.t==mapping.solver_birth_time_us)
  assert(state.mass==mapping.mass_amu and state.charge==mapping.charge_state)
  assert(runtime.instrument_time_us(engine_t)==mapping.instrument_time_us)
  assert(runtime.source_id(ordinal)==mapping.particle_id)
  local beam=beams[ordinal]
  assert(beam.n==1 and beam.tob==state.t and beam.mass==state.mass and beam.charge==state.charge)
  assert(beam.ke==states[ordinal].ke)
  for axis,index in pairs({x=1,y=2,z=3}) do
    assert(beam.position[index]==state[axis],'FLY2 position differs from exact state')
    assert(beam.direction[index]==state['v'..axis],'FLY2 velocity differs from exact state')
  end
end
print('READ_ONLY_TOF=PASS')
''', encoding="utf-8", newline="\n")
        result = subprocess.run([lua, str(script), str(self.output)], cwd=self.root,
                                capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("READ_ONLY_TOF=PASS", result.stdout)

    def test_rehashed_numeric_lexemes_are_equal_but_string_identity_is_not(self) -> None:
        path = self.fixture.output / "component_particle_state.csv"
        with path.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        rows[0]["mass_amu"] = format(float(rows[0]["mass_amu"]), ".3f")
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader(); writer.writerows(rows)
        self._refresh_handoff_output("component_particle_state", path)
        before = path.read_bytes()
        self._materialize()
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual((self.output / "component_particle_state.csv").read_bytes(), before)
        rows[0]["species_id"] += ".0"
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader(); writer.writerows(rows)
        self._refresh_handoff_output("component_particle_state", path)
        with self.assertRaisesRegex(ValueError, "6D/identity/clock"):
            materialize_measured_source(self.handoff, self.root / "different_identity")

    def test_rehashed_velocity_change_still_rejected_against_producer(self) -> None:
        path = self.fixture.output / "component_particle_state.csv"
        rows = self.fixture.rows
        rows[0]["velocity_x_m_s"] += 10
        text = path.read_text().replace(",50.0,", ",60.0,")
        path.write_text(text, encoding="utf-8")
        self._refresh_handoff_output("component_particle_state", path)
        with self.assertRaisesRegex(ValueError, "6D/identity/clock"):
            self._materialize()

    def test_rehashed_clock_epoch_change_is_rejected(self) -> None:
        path = self.fixture.output / "component_particle_state.csv"
        path.write_text(path.read_text().replace("ion_processor_epoch_zero_v1", "other_epoch"), encoding="utf-8")
        self._refresh_handoff_output("component_particle_state", path)
        with self.assertRaisesRegex(ValueError, "6D/identity/clock"):
            self._materialize()

    def test_incomplete_mother_census_rejected(self) -> None:
        path = self.fixture.output / "source_census.csv"
        path.write_text("\n".join(path.read_text().splitlines()[:-1]) + "\n", encoding="utf-8")
        self._refresh_handoff_output("source_census", path)
        with self.assertRaisesRegex(ValueError, "mother census"):
            self._materialize()

    def test_upstream_authority_tamper_rejected(self) -> None:
        self._write(self.epoch, {"instrument_time_us": 100})
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self._materialize()

    def test_invalid_direction_even_if_all_receipts_rehashed(self) -> None:
        rows = self.fixture.rows
        rows[0]["velocity_z_m_s"] *= -1
        write_component_particle_state_csv(self.fixture.source, rows)
        self.fixture.receipt["outputs"]["component_states"] = self._identity(self.fixture.source)
        self._write(self.fixture.receipt_path, self.fixture.receipt)
        import_rows = [dict(row, frame_id="mr_frame.v2", position_y_mm=row["position_y_mm"]-225) for row in rows]
        path = self.fixture.output / "component_particle_state.csv"
        write_component_particle_state_csv(path, import_rows)
        receipt = json.loads(self.handoff.read_text())
        receipt["inputs"]["component_receipt"] = self._identity(self.fixture.receipt_path)
        receipt["outputs"]["component_particle_state"] = self._identity(path)
        self._write(self.handoff, receipt)
        with self.assertRaisesRegex(ValueError, "negative z"):
            self._materialize()

    def test_refuses_overwrite(self) -> None:
        self._materialize()
        with self.assertRaises(FileExistsError):
            self._materialize()


if __name__ == "__main__":
    unittest.main()
