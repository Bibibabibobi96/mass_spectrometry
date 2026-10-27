"""IP source-weight binding and actual public beam-consumer regressions."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common.analysis import beam_focus_diagnostics as beam
from common.contracts.component_particle_state import write_component_particle_state_csv
from common.contracts.particle_physics import kinetic_energy_ev
from common.contracts.write_run_manifest import file_record
from projects.dual_pressure_rectilinear_ion_processor.analysis import extraction_phase_space_comparison as recorded
from projects.dual_pressure_rectilinear_ion_processor.analysis import geometry_comparison
from projects.dual_pressure_rectilinear_ion_processor.tests.test_geometry_comparison import source_fixture, write_json, write_csv


class RecordedBeamBindingTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix="ip_beam_binding_")
        self.addCleanup(temporary.cleanup)
        self.run=Path(temporary.name)/"recorded"
        source_fixture(self.run,"flat")
        completed=patch.object(recorded,"require_completed_terminal_publication")
        completed.start();self.addCleanup(completed.stop)

    def seal(self):
        path=self.run/"run_manifest.json"
        manifest=json.loads(path.read_text())
        manifest["outputs"]=[file_record(p) for p in self.run.rglob("*")
                             if p.is_file() and p.name not in {"run_manifest.json","run_config.json"}]
        write_json(path,manifest)

    def injected(self):
        config_path=self.run/"inputs/resolved_model.json"
        config=json.loads(config_path.read_text());config["injected_source"]={"particle_ids":[1,2,3]}
        write_json(config_path,config)
        rows=[]
        for pid,weight in ((3,8.),(1,.125),(2,2.)):
            rows.append(dict(particle_id=pid,parent_particle_id="",generation=0,species_id="ion",
                particle_weight=weight,source_component_id="upstream",target_component_id="ip",
                state_event="mechanical_exit",frame_id="fixture_world",clock_epoch_id="fixture_epoch",
                instrument_time_us=0.,lineage_age_us=0.,particle_age_us=0.,last_component_elapsed_time_us=0.,
                lineage_birth_time_us=0.,particle_birth_time_us=0.,mass_to_charge_Th=524.,mass_amu=524.,charge_state=1,
                position_x_mm=pid/10,position_y_mm=pid/5,position_z_mm=10.,
                velocity_x_m_s=1000.,velocity_y_m_s=0.,velocity_z_m_s=0.,
                kinetic_energy_eV=kinetic_energy_ev(524.,1000.,0.,0.),phase_reference_id="",phase_rad=""))
        write_component_particle_state_csv(self.run/"inputs/injected_states.csv",rows)
        self.seal()
        return rows

    def test_native_equal_source_and_real_geometry_consume_public_module(self):
        case=recorded.load_recorded_case(self.run,"Native",include_samples=True)
        self.assertEqual(case["particle_weights"],{1:1.,2:1.,3:1.})
        self.assertIs(geometry_comparison.beam_focus_diagnostics,beam)
        case["states"]=recorded.prepare_spatial_crossings(case,[5.,0.])
        result=geometry_comparison.beam_focus_diagnostics.prepare_focus_diagnostics([case],[5.,0.],[1,2])
        row=next(r for r in result["plane_statistics"] if r["plane_z_mm"]==0. and r["cohort"]=="common_extracted_ids")
        self.assertEqual(row["weight_sum"],2.)
        self.assertEqual(row["effective_sample_count"],2.)

    def test_injected_weights_are_read_once_bound_and_preserve_lost_source_id(self):
        self.injected()
        with patch.object(recorded,"load_component_particle_state_csv",wraps=recorded.load_component_particle_state_csv) as loader:
            case=recorded.load_recorded_case(self.run,"Injected",include_samples=True)
        loader.assert_called_once_with(self.run/"inputs/injected_states.csv")
        self.assertEqual(case["particle_weights"],{3:8.,1:.125,2:2.})
        self.assertNotIn(3,case["exits"])
        self.assertIn(str(self.run/"inputs/injected_states.csv"),[r["path"] for r in case["source_records"]])
        case["states"]=recorded.prepare_spatial_crossings(case,[5.,0.])
        result=beam.prepare_focus_diagnostics([case],[5.,0.],[1,2])
        row=next(r for r in result["plane_statistics"] if r["plane_z_mm"]==0. and r["cohort"]=="common_extracted_ids")
        self.assertEqual(row["available_ids"],[1,2])
        self.assertEqual(row["weight_sum"],2.125)
        self.assertAlmostEqual(row["mean_x_mm"],(.125*.1+2*.2)/2.125)

    def test_missing_bound_source_or_hash_drift_is_rejected(self):
        self.injected();manifest_path=self.run/"run_manifest.json"
        manifest=json.loads(manifest_path.read_text())
        manifest["outputs"]=[r for r in manifest["outputs"] if not r["path"].endswith("injected_states.csv")]
        write_json(manifest_path,manifest)
        with self.assertRaisesRegex(ValueError,"manifest-bound.*injected_states"):
            recorded.load_recorded_case(self.run,"Missing")
        self.seal()
        with (self.run/"inputs/injected_states.csv").open("a") as stream:stream.write("\n")
        with self.assertRaisesRegex(AssertionError,"byte count changed"):
            recorded.load_recorded_case(self.run,"Changed")

    def test_injected_id_coverage_and_missing_weight_fail_closed(self):
        rows=self.injected()
        for invalid in (rows[:-1],rows+[rows[0]],
                        [{k:v for k,v in row.items() if k!="particle_weight"} for row in rows]):
            write_csv(self.run/"inputs/injected_states.csv",invalid);self.seal()
            with self.assertRaises(ValueError):
                recorded.load_recorded_case(self.run,"Invalid")


if __name__=="__main__":
    unittest.main()
