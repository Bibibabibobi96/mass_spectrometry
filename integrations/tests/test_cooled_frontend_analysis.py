"""Synthetic protocol records exercise automatic cooled/OA analysis, not Fly.

The complete three-ID fixture deliberately contains one exit, one unresolved
native stop and one timeout. It must never be described as native physics or
as a replacement for the original N=100 scientific mother cohort.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from msplatform.contracts.particle_physics import AMU_KG, ELEMENTARY_CHARGE_C
from msplatform.execution.retention import file_record
from integrations.tests.test_local_frontend_analysis import (
    _TIMES, fixture, write_log,
)
from integrations.workflows.cooled_frontend.analyze import analyze_cooled_frontend
from msplatform.components.dual_pressure_rectilinear_ion_processor.cooled_buncher import build_cooled_buncher_contract
from projects.dual_pressure_rectilinear_ion_processor.tests.test_cooled_buncher import buncher_fixture, native_pose


def cooled_analysis_fixture(root: Path, *, pressure_scale: int, entrance_close_us: float = .5) -> tuple[Path, list[dict], dict]:
    """Extend the existing lawful-log fixture without changing its birth cohort."""
    log, events = fixture(root)
    shared = next(r for r in events if r["event"] == "local_shared_time" and r["particle_id"] == 11)
    shared.update(vx_mm_per_us=.2, vy_mm_per_us=.6, vz_mm_per_us=-2.)
    write_log(log, events)
    inputs = root/"inputs"
    model, guide, registration, request, ids = buncher_fixture()
    conditioner = build_cooled_buncher_contract(model, guide_contract=guide, native_to_assembly=native_pose(guide, registration),
                                               request=request, electrode_ids=ids)
    drive = dict(schema_version=1, role="synthetic_cooled_analysis_drive",
                 capture_voltages_v={name: 0. for name in ids},
                 closed_voltages_v={name: 1. for name in ids},
                 release_voltages_v={name: 2. for name in ids},
                 entrance_close_us=entrance_close_us, release_start_us=1.5)
    pulse_path = inputs/"common_pulse_decision.json"
    pulse_path.write_text(json.dumps(dict(role="synthetic_common_pulse_decision", actual_pulse_time_us=2.))+"\n", encoding="utf-8")
    experiment = dict(schema_version=1, role="rf_oatof_cooled_pressure_control", pressure_scale=pressure_scale,
                      common_pulse_decision=file_record(pulse_path))
    for name, document in (("conditioner_contract.json", conditioner), ("cooled_experiment.json", experiment),
                           ("cooled_drive.json", drive)):
        (inputs/name).write_text(json.dumps(document)+"\n", encoding="utf-8")
    return log, events, experiment


class CooledFrontendAnalysisTests(unittest.TestCase):
    def test_pressure_metadata_all_mother_losses_component_units_and_automatic_figures(self):
        for pressure in (0, 1):
            with self.subTest(pressure=pressure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                log, _, experiment = cooled_analysis_fixture(root, pressure_scale=pressure)
                source = root/"inputs/release_global.csv"
                before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (source, log)}
                result = analyze_cooled_frontend(root, [log], shared_times_us=_TIMES, pulse_time_us=2.)
                output = root/"results/local_frontend/extraction"
                document = json.loads((output/"cooling_evolution.json").read_text())
                self.assertEqual(document["pressure_scale"], pressure)
                self.assertEqual(document["mother_count"], 3)
                self.assertEqual(document["common_pulse_decision"], experiment["common_pulse_decision"])
                self.assertIn("instantaneous", document["interpretation"])
                self.assertEqual((result["mother_count"], result["exit_count"], result["loss_count"]), (3, 1, 2))
                terminal = pd.read_csv(output/"all_mother_terminal_census.csv")
                losses = pd.read_csv(output/"all_losses.csv")
                self.assertEqual(set(terminal.particle_id), {3, 11, 67})
                self.assertEqual(set(losses.particle_id), {11, 67})
                self.assertEqual(set(losses.terminal_class), {"native_stop_unresolved", "timeout"})
                self.assertTrue(losses.raw_line.str.startswith("TRACE:").all())
                by_time = {row["instrument_time_us"]: row for row in document["snapshots"]}
                row = by_time[.5]
                self.assertEqual(row["active_ids"], [3, 11])
                self.assertEqual(row["phase"], "closed")
                self.assertEqual(by_time[0.]["phase"], "capture")
                self.assertEqual(by_time[2.]["phase"], "released")
                self.assertNotIn(3., by_time)  # No propagation of ended particles.
                mass = 524*AMU_KG
                for axis, speeds in (("x", (100., 200.)), ("y", (1000., 600.)), ("z", (-10000., -2000.))):
                    expected = .5*mass*sum(v*v for v in speeds)/2/ELEMENTARY_CHARGE_C
                    self.assertAlmostEqual(row[f"mean_E{axis}_ev"], expected)
                self.assertAlmostEqual(row["sigma_vx_m_s"], 50.)
                self.assertAlmostEqual(row["sigma_vy_m_s"], 200.)
                self.assertAlmostEqual(row["sigma_vz_m_s"], 4000.)
                covariance = row["covariance_xyz_mm_velocity_m_s"]
                self.assertAlmostEqual(covariance[3][3], 2500.)
                self.assertAlmostEqual(covariance[4][4], 40000.)
                self.assertAlmostEqual(covariance[5][5], 16000000.)
                self.assertAlmostEqual(covariance[1][4], -400.)
                expected_phase = (2*math.pi*3.7e6*.5e-6)%(2*math.pi)
                self.assertAlmostEqual(row["rf_phase_rad"], expected_phase)
                outputs = set(result["output_paths"])
                for name in ("cooling_evolution.json", "cooling_evolution.csv", "cooling_evolution.png", "cooling_evolution.svg",
                             "shared_time_distributions.png", "shared_time_distributions.svg", "focus_recorded_focus.png"):
                    path = output/name
                    self.assertIn(str(path), outputs)
                    self.assertGreater(path.stat().st_size, 0)
                for path, digest in before.items():
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_exact_recorded_gate_boundary_does_not_shift_phase_on_csv_readback(self):
        boundary = .1+.2  # Binary64 value distinct from decimal 0.3.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log, events, _ = cooled_analysis_fixture(root, pressure_scale=1, entrance_close_us=boundary)
            for pid in (3, 11):
                row = copy.deepcopy(next(r for r in events if r["event"] == "local_aperture_pre" and r["particle_id"] == pid))
                row.update(event="local_shared_time", instrument_time_us=boundary, requested_time_us=boundary)
                events.append(row)
            write_log(log, events)
            analyze_cooled_frontend(root, [log], shared_times_us=sorted([*_TIMES, boundary]), pulse_time_us=2.)
            document = json.loads((root/"results/local_frontend/extraction/cooling_evolution.json").read_text())
            snapshot = next(row for row in document["snapshots"] if abs(row["instrument_time_us"]-boundary) < math.ulp(boundary)*2)
            self.assertEqual(snapshot["instrument_time_us"], boundary)
            self.assertEqual(snapshot["phase"], "closed")

    def test_zero_exit_result_keeps_all_losses_and_cooling_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log, events, _ = cooled_analysis_fixture(root, pressure_scale=0)
            events = [row for row in events if row["event"] != "local_accelerator_exit"]
            next(row for row in events if row["event"] == "accelerator_exit_stop")["event"] = "local_timeout"
            write_log(log, events)
            result = analyze_cooled_frontend(root, [log], shared_times_us=_TIMES, pulse_time_us=2.)
            self.assertEqual(result["exit_count"], 0)
            self.assertEqual(result["loss_count"], 3)
            output = root/"results/local_frontend/extraction"
            with (output/"all_losses.csv").open(newline="") as handle:
                self.assertEqual({int(row["particle_id"]) for row in csv.DictReader(handle)}, {3, 11, 67})
            document = json.loads((output/"cooling_evolution.json").read_text())
            self.assertEqual(document["mother_count"], 3)
            self.assertTrue(document["snapshots"])


class CoolingPopulationDiagnosticsTests(unittest.TestCase):
    def test_actual_cooled_freezer_delivers_helper_without_author_fallback(self):
        import shutil
        import subprocess
        import sys
        repo=Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/"inputs";output.mkdir()
            script=Path(directory)/"freeze.ps1"
            script.write_text("""param($Repo,$Output,$Python)
. (Join-Path $Repo 'integrations/runtime/dependencies.ps1')
Freeze-ConsumerDependencies -Python $Python -RepoRoot $Repo -ContractPath (Join-Path $Repo 'integrations/config/runtime_dependencies.json') -InputDir $Output -OwnerId instrument_assembly -ConsumerId cooled_frontend | Out-Null
""",encoding="utf-8")
            self.assertIsNotNone(shutil.which("pwsh"))
            frozen=subprocess.run([shutil.which("pwsh"),"-NoProfile","-File",str(script),str(repo),str(output),sys.executable],
                cwd=repo,capture_output=True,text=True,encoding="utf-8",timeout=90)
            self.assertEqual(frozen.returncode,0,frozen.stdout+frozen.stderr)
            snapshot=output/"runtime_snapshot"
            target=snapshot/"src/msplatform/analysis/cooling_diagnostics.py"
            self.assertEqual(target.read_bytes(),(repo/"src/msplatform/analysis/cooling_diagnostics.py").read_bytes())
            code="""import sys,json
from pathlib import Path
root=Path.cwd();sys.path[:0]=[str(root/'src'),str(root)]
from msplatform.analysis import cooling_diagnostics as m
assert Path(m.__file__).resolve().is_relative_to(root)
print(json.dumps(m.velocity_population_diagnostics([[100.,0.,0.]],mass_amu=100.,charge_state=1,
 reference_velocity_m_s=(100.,0.,0.),relative_weights=None,frame_id='lab',sample_kind='time_snapshot',reference_label='explicit nominal bath')))
"""
            command=[sys.executable,"-I","-B","-c",code]
            def cold():
                return subprocess.run(command,cwd=snapshot,capture_output=True,text=True,encoding="utf-8",timeout=30)
            accepted=cold();self.assertEqual(accepted.returncode,0,accepted.stdout+accepted.stderr)
            self.assertEqual(json.loads(accepted.stdout)["mean_reference_relative_energy_ev"],0.)
            target.unlink()
            rejected=cold();self.assertNotEqual(rejected.returncode,0)
            self.assertIn("cooling_diagnostics",rejected.stderr)

    def test_diagnostic_mass_charge_groups_never_use_an_average_species_mass(self):
        from integrations.workflows.cooled_frontend.analyze import _population_diagnostics
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);_,_,experiment=cooled_analysis_fixture(root,pressure_scale=1)
            output=root/"pure-diagnostic";output.mkdir()
            source=pd.DataFrame([dict(particle_id=pid,mass_amu=mass,charge_state=charge,instrument_time_us=0.)
                for pid,mass,charge in ((1,100.,1),(7,100.,1),(101,524.,-1))]).set_index("particle_id")
            path=root/"explicit-selected-source.csv";source.to_csv(path)
            (output/"metadata.json").write_text(json.dumps(dict(source=file_record(path))))
            pd.DataFrame([dict(particle_id=pid,instrument_time_us=t,status="active")
                for t in (1.,2.) for pid in (1,7,101)]).to_csv(output/"all_shared_time_census.csv",index=False)
            pd.DataFrame([dict(particle_id=pid,terminal_class="exit" if pid==7 else "timeout")
                for pid in (1,7,101)]).to_csv(output/"all_mother_terminal_census.csv",index=False)
            states=pd.DataFrame([dict(particle_id=pid,requested_time_us=t,vx_mm_per_us=v,vy_mm_per_us=0.,vz_mm_per_us=0.)
                for t in (1.,2.) for pid,v in ((1,.09),(7,.11),(101,.2))])
            conditioner=json.loads((root/"inputs/conditioner_contract.json").read_text())
            doc=_population_diagnostics(output,states,source,conditioner,experiment,[1.,2.])
            groups=doc["declared_clocks"][0]["active_groups"]
            self.assertEqual([(g["mass_amu"],g["charge_state"],g["particle_ids"]) for g in groups],
                [(100.,1,[1,7]),(524.,-1,[101])])
            self.assertEqual(groups[0]["sample_count"],2)
            self.assertEqual(groups[1]["velocity_covariance_m2_s2"],[[0.]*3]*3)
            self.assertEqual(doc["consecutive_recorded_pairs"][0]["paired_particle_ids"],[1,7,101])
            integral_csv=source.astype({"charge_state":float})
            self.assertEqual(_population_diagnostics(output,states,integral_csv,conditioner,experiment,[1.,2.]),doc)
            for charge in (1.5, float("nan"), float("inf"), -float("inf"), 0.):
                invalid=source.astype({"charge_state":float})
                invalid.loc[7,"charge_state"]=charge
                with self.subTest(invalid_source_charge=charge),self.assertRaisesRegex(ValueError,"source mass/charge"):
                    _population_diagnostics(output,states,invalid,conditioner,experiment,[1.,2.])

    def test_complex_velocity_and_reference_reject_before_real_conversion(self):
        import numpy as np
        from msplatform.analysis.cooling_diagnostics import velocity_population_diagnostics
        args=dict(mass_amu=100.,charge_state=1,reference_velocity_m_s=np.array([0.,0.,0.]),relative_weights=None,
            frame_id="lab",sample_kind="time_snapshot",reference_label="explicit nominal reference")
        for selected in ("velocity","reference"):
            with self.subTest(complex_input=selected),self.assertRaisesRegex(ValueError,"real"):
                velocity=np.array([[1.+2j,0.,0.]]) if selected=="velocity" else np.array([[1.,0.,0.]])
                reference=np.array([0.+2j,0.,0.]) if selected=="reference" else args["reference_velocity_m_s"]
                velocity_population_diagnostics(velocity,**dict(args,reference_velocity_m_s=reference))

    def test_explicit_reference_weighting_and_velocity_tensor(self):
        import numpy as np
        from msplatform.analysis.cooling_diagnostics import velocity_population_diagnostics as describe
        from msplatform.contracts.particle_physics import BOLTZMANN_CONSTANT_J_K
        args=dict(mass_amu=100.,charge_state=-1,reference_velocity_m_s=(100.,0.,0.),relative_weights=None,
            frame_id="lab",sample_kind="time_snapshot",reference_label="explicit nominal reference")
        drift=describe(np.array([[100.,0.,0.],[100.,0.,0.]]),**args)
        self.assertGreater(drift["mean_laboratory_energy_ev"],0.)
        self.assertEqual(drift["mean_reference_relative_energy_ev"],0.)
        self.assertEqual(drift["effective_second_moment_tensor_k"],[[0.]*3]*3)
        pair=describe(np.array([[90.,0.,0.],[110.,0.,0.]]),**args)
        self.assertEqual(pair["mean_velocity_m_s"],[100.,0.,0.])
        self.assertEqual(pair["velocity_covariance_m2_s2"][0][0],100.)
        self.assertAlmostEqual(pair["effective_second_moment_tensor_k"][0][0],100.*AMU_KG*100./BOLTZMANN_CONSTANT_J_K)
        weighted=describe(np.array([[90.,0.,0.],[110.,0.,0.]]),**dict(args,relative_weights=np.array([1.,3.])))
        self.assertEqual(weighted["mean_velocity_m_s"],[105.,0.,0.])
        self.assertEqual(weighted["velocity_covariance_m2_s2"][0][0],75.)
        self.assertEqual(weighted["weighting"],"explicit_relative")
        self.assertIn("not equilibrium",pair["interpretation"])
        empty=describe(np.empty((0,3)),**args)
        self.assertEqual(empty["sample_count"],0)
        self.assertIsNone(empty["mean_laboratory_energy_ev"])
        self.assertIsNone(empty["effective_second_moment_tensor_k"])
        for changed in (dict(mass_amu=True),dict(charge_state=True),dict(reference_velocity_m_s=(float("nan"),0.,0.)),
                        dict(relative_weights=np.array([1.,0.])),dict(frame_id=""),dict(sample_kind="SDS microscopic temperature")):
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                describe(np.array([[90.,0.,0.],[110.,0.,0.]]),**dict(args,**changed))

    def test_declared_clocks_pairs_and_nominal_reference_preserve_empty_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);log,_,_=cooled_analysis_fixture(root,pressure_scale=0)
            result=analyze_cooled_frontend(root,[log],shared_times_us=_TIMES,pulse_time_us=2.)
            doc=json.loads(Path(result["cooling_population_diagnostics_record"]).read_text())
            self.assertEqual(doc["mother_particle_ids"],[3,11,67])
            source=pd.read_csv(root/"inputs/release_global.csv",float_precision="round_trip")
            self.assertEqual(doc["source_birth_times_us"],{str(int(row.particle_id)):row.instrument_time_us for row in source.itertuples()})
            self.assertEqual(doc["source_record"],file_record(root/"inputs/release_global.csv"))
            self.assertEqual(doc["instrument_time_units"],"us")
            self.assertEqual(doc["moment_method"],"population_moments_centered_columnwise_numpy_float64_ddof0")
            self.assertEqual([r["instrument_time_us"] for r in doc["declared_clocks"]],_TIMES)
            last=doc["declared_clocks"][-1]
            self.assertTrue(all(g["sample_count"]==0 for g in last["active_groups"]))
            self.assertFalse(doc["reference"]["actual_gas_sample"])
            self.assertEqual(doc["reference"]["kind"],"nominal_prescribed_bath")
            self.assertEqual(doc["reference"]["velocity_m_s"],[0.,0.,0.])
            self.assertEqual(doc["reference"]["source"],"selected_cooled_conditioner_gas")
            self.assertEqual(last["confirmed_oa_exit_selected"]["cohort_particle_ids"],[3])
            self.assertEqual(last["confirmed_oa_exit_selected"]["unobserved_particle_ids"],[3])
            self.assertEqual(doc["consecutive_recorded_pairs"][-1]["paired_particle_ids"],[])
            for pair in doc["consecutive_recorded_pairs"]:
                before=[pid for g in pair["before"] for pid in g["particle_ids"]]
                after=[pid for g in pair["after"] for pid in g["particle_ids"]]
                self.assertEqual(before,after)
                self.assertEqual(sorted(before),pair["paired_particle_ids"])
            legacy=json.loads((root/"results/local_frontend/extraction/cooling_evolution.json").read_text())
            self.assertNotIn(3.,[r["instrument_time_us"] for r in legacy["snapshots"]])
            self.assertIn("not proof of physical",doc["terminal_semantics"])


if __name__ == "__main__":
    unittest.main()
