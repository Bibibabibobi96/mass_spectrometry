"""RF–IP actual Lua callback and SI adapter with inert host doubles, not native Fly."""
import copy
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from msplatform.backends.simion.terminal_evidence import append_terminal_recorder
from msplatform.backends.simion.tracking_collection import collect_tracking_logs
from msplatform.backends.simion.tracking_execution import _publish_split_particle_data
from msplatform.io.manifest_records import file_record
from msplatform.results.particle_data import read_particle_data
from tests.contracts.test_support.species import fixture_ion_species_from_amu


class RfIpParticleDataTests(unittest.TestCase):
    @unittest.skipUnless(Path('C:/Program Files/SIMION-2020/lua.exe').is_file(), 'standalone Lua unavailable')
    def test_actual_callbacks_collector_and_si_cold_read(self):
        prefix = r'''
segment={};local rf_committed_observations=true;local rf_static_operating=true
local rf_trajectory_quality=8;local rf_grouped=0;local rf_step_cap_us=.1
local rf_initial_velocities={{1,0,0}};local single_flight_time_origin_us={0}
local single_flight_absolute_deadline_us={5};local rf_observation_times={0,1}
function single_flight_source_row_index() return 1 end
function single_flight_canonical_particle_id() return 7 end
function single_flight_instrument_time_us() return ion_time_of_flight end
function single_flight_restore_source_velocity(_) end
ion_number=1;ion_run=1;ion_instance=1;ion_time_of_birth=0;ion_time_of_flight=0;ion_time_step=.1;sim_grouped=0
ion_px_mm=0;ion_py_mm=0;ion_pz_mm=0;ion_vx_mm=1;ion_vy_mm=0;ion_vz_mm=0
ion_mass=100;ion_charge=1;ion_splat=0
'''
        suffix = r'''
segment.initialize_run();segment.initialize()
ion_time_of_flight=.5;ion_px_mm=.5;segment.other_actions()
ion_time_of_flight=1.5;ion_px_mm=1.5;segment.other_actions()
ion_time_of_flight=2;ion_px_mm=2;segment.terminate()
print('status,Fly completed. 1 splats')
'''
        runtime = Path('src/msplatform/backends/simion/resources/rf_tracking.lua').read_text(encoding='utf-8')
        recorder = Path('src/msplatform/backends/simion/resources/native_terminal_recording.lua').read_text(encoding='utf-8')
        program = append_terminal_recorder(prefix+runtime, recorder_source=recorder, native_run='fixture-unit')+suffix
        source = dict(particle_id=7,species_id='ion',parent_particle_id=None,generation=0,particle_weight=1.,
            instrument_time_us=0.,particle_birth_time_us=0.,mass_amu=100.,charge_state=1,
            position_x_mm=0.,position_y_mm=0.,position_z_mm=0.,
            velocity_x_m_s=1000.,velocity_y_m_s=0.,velocity_z_m_s=0.)
        provenance = dict(state_kind='source_birth',execution_particle_ids=[7],mother_particle_ids=[7],
            mother_records=[dict(particle_id=7,particle_birth_time_us=0.)],mother_fates=[],
            clock_authority_sha256='a'*64,clock_records={})
        batch = dict(source_row_range=[1,1],expected_particle_ids=[7],build_metadata=dict(
            source_clock=dict(original_birth_times_us=[0.],absolute_deadlines_us=[5.]),
            plane_observations=[],propagation_stop=None,consumed_plane_events=[],
            terminal_evidence=dict(schema_version=1,native_run='fixture-unit')))
        flight = dict(tracking_kind='rf_ip',original_birth_si=True,grouped=0,observation_times_us=[0.,1.])
        with TemporaryDirectory() as directory:
            root=Path(directory); script=root/'callbacks.lua'; script.write_text(program,encoding='utf-8')
            completed=subprocess.run(['C:/Program Files/SIMION-2020/lua.exe',str(script)],cwd=root,
                capture_output=True,text=True,timeout=30,check=False)
            self.assertEqual(completed.returncode,0,completed.stdout+completed.stderr)
            log=root/'callbacks.log'; log.write_text(completed.stdout,encoding='utf-8')
            def collect(prov=provenance):
                return collect_tracking_logs([log],source_rows={7:source},source_provenance=prov,
                    flight=flight,batches=[batch])
            collection=collect()
            self.assertTrue(collection['native_complete'] and collection['observation_complete'])
            self.assertEqual([(row['instrument_time_us'],row['x_mm']) for row in collection['native_shared_states']],[(0.,0.),(1.,1.)])
            self.assertEqual(collection['terminal_evidence']['status'],'recorded_v1')
            # A validated unit is a subset, never a complete-mother product.
            whole=copy.deepcopy(provenance)
            whole['mother_particle_ids']=[7,8];whole['execution_particle_ids']=[7,8]
            whole['mother_records'].append(dict(particle_id=8,particle_birth_time_us=0.))
            unit=collect_tracking_logs([log],source_rows={7:source},source_provenance=whole,
                flight=flight,batches=[batch],cohort_scope='partition')
            self.assertFalse(unit['native_complete'])
            self.assertEqual(unit['census']['mother_particle_ids'],[7,8])
            from msplatform.backends.simion.tracking_units import _validate_completed_unit
            receipt=root/'inert_process.json'
            receipt.write_text(json.dumps(dict(observation=dict(exit_code=0,resource_budget_exceeded=False,
                root_process_id=1,root_process_started_at_utc_ticks=1),
                host_release=dict(error=None,inherited=False,token='fixture',
                    result=dict(status='released',token='fixture')))),encoding='utf-8')
            unit_row=dict(stdout_record=file_record(log),process_record=file_record(receipt),build_metadata=batch['build_metadata'])
            unit_spec=dict(source_row_range=[1,1],expected_particle_ids=[7])
            plan_for_unit=dict(rows=[source,dict(source,particle_id=8)],native_source_rows=[{},{}],
                source_provenance=whole,flight=flight,propagation={'consumed_plane_events':[]})
            checked=_validate_completed_unit(unit_row,plan_for_unit,unit_spec)
            self.assertFalse(checked['native_complete'])
            self.assertEqual(checked['census']['mother_particle_ids'],[7,8])
            with self.assertRaisesRegex(ValueError,'original birth cohort'):
                collect(whole)
            foreign=copy.deepcopy(whole);foreign['execution_particle_ids']=[8,9];foreign['mother_particle_ids']=[8,9]
            foreign['mother_records']=[dict(particle_id=8,particle_birth_time_us=0.),dict(particle_id=9,particle_birth_time_us=0.)]
            with self.assertRaises(ValueError):
                collect_tracking_logs([log],source_rows={7:source},source_provenance=foreign,
                    flight=flight,batches=[batch],cohort_scope='partition')
            bad=copy.deepcopy(provenance);bad['mother_particle_ids']=[7,8]
            with self.assertRaisesRegex(ValueError,'original birth cohort'):
                collect(bad)
            bad_lines=[]
            for line in completed.stdout.splitlines():
                if line.startswith('RF_NATIVE_STATE_V1: '):
                    row=json.loads(line.split(': ',1)[1])
                    if row['event']=='shared' and row['reason']=='actual_birth':
                        row['x_mm']=.25
                        line='RF_NATIVE_STATE_V1: '+json.dumps(row)
                bad_lines.append(line)
            log.write_text('\n'.join(bad_lines)+'\n',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'actual birth observation differs'):
                collect()
            log.write_text(completed.stdout+'RF_OBSERVATION_INCOMPLETE_V1: ion=1 particle_id=7 reason=terminal_before_retained_history\n',encoding='utf-8')
            incomplete=collect()
            self.assertFalse(incomplete['observation_complete'])
            self.assertEqual(incomplete['native_shared_states'],[])
            log.write_text(completed.stdout,encoding='utf-8')
            binary=root/'inert.exe';binary.write_bytes(b'NOT_SIMION')
            binary_record=file_record(binary,'solver_native_binary');identity={k:binary_record[k] for k in ('bytes','sha256')}
            session=SimpleNamespace(result_dir=root,context=SimpleNamespace(tools={'simion':str(binary)}),
                declare_file=lambda path,role:path,canonical_path=lambda path:path)
            plan=dict(expected_operation_ids=['track_fly'],rows=[source],species=fixture_ion_species_from_amu([source]),
                flight=flight,observations=dict(plane_observations=[],observation_times_us=[0.,1.]))
            clock=dict(clock_epoch_id='epoch',authority_sha256='a'*64)
            with patch('msplatform.backends.simion.tracking_execution.windows_binary_version',return_value='inert-fixture'):
                result,_=_publish_split_particle_data(session,plan,collection,dict(native_frame_id='world'),
                    dict(drive=dict(clock=clock)),identity,{})
            data=read_particle_data(root/'particle_data')
            self.assertEqual([row['particle_id'] for row in data['initial_states']],[7])
            self.assertEqual(data['terminal_states'][0]['physical_outcome'],'unknown')
            self.assertEqual(data['trajectories']['time_s'].tolist(),[0.,1e-6])
            self.assertEqual(data['trajectories']['position_m'][:,0].tolist(),[0.,.001])
            self.assertEqual(result.data_integrity['detector_observation']['status'],'not_requested')


if __name__=='__main__':
    unittest.main()
