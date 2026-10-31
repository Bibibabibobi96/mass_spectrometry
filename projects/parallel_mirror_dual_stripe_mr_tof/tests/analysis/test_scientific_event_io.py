"""Structured scientific output and explicit legacy adapters; no solver required."""
import csv
import hashlib
import json
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from common.simion import scientific_event_io as io
from common.paths import workspace_paths
from projects.parallel_mirror_dual_stripe_mr_tof.analysis import simion_event_analysis as mr
from projects.parallel_mirror_dual_stripe_mr_tof.analysis import mrtof_batch_flight as merger
from projects.parallel_mirror_dual_stripe_mr_tof.analysis import mrtof_batch_continuation as continuation
from projects.parallel_mirror_dual_stripe_mr_tof.analysis import prepared_joint_trial as prepared
from projects.parallel_mirror_dual_stripe_mr_tof.analysis import source_z_energy_timing_diagnostic as source_z
from projects.parallel_mirror_dual_stripe_mr_tof.analysis import bunch_source_and_schedule as pilot
ROOT=Path(__file__).resolve().parents[4]

class ScientificEventIoTests(unittest.TestCase):

    def test_materialize_cli_parses_only_source_slice_arguments(self):
        from contextlib import redirect_stdout
        from io import StringIO
        import sys
        output = StringIO()
        arguments = ["mrtof_batch_flight", "materialize", "--receipt", "source.json",
                     "--particle-id-min", "11", "--particle-id-max", "45", "--output", "batch.fly2"]
        with patch.object(sys, "argv", arguments), patch.object(merger, "materialize_batch_fly2", autospec=True,
                return_value={"count": 35}) as materialize, redirect_stdout(output):
            self.assertEqual(merger.main(), 0)
        materialize.assert_called_once_with(receipt_path=Path("source.json"), particle_id_min=11,
                                           particle_id_max=45, output_path=Path("batch.fly2"))
        self.assertEqual(json.loads(output.getvalue()), {"count": 35})

    def test_merge_cli_preserves_explicit_science_declaration_and_legacy_absence(self):
        from contextlib import redirect_stdout
        from io import StringIO
        import sys
        declaration = {"events_path": "events.csv", "trajectory_path": "trajectory.csv",
                       "events_record": {"path": "events.csv", "bytes": 12, "sha256": "A" * 64}}
        for supplied in (None, declaration):
            with self.subTest(declaration=supplied):
                arguments = ["mrtof_batch_flight", "merge", "--particle-count", "2",
                             "--particle-id-min", "11", "--batch-log", "native.log", "10", "2",
                             "--output", "merged.log", "--receipt", "merge.json"]
                if supplied is not None:
                    arguments += ["--batch-scientific-output", json.dumps(supplied)]
                with patch.object(sys, "argv", arguments), patch.object(merger, "merge_rebased_event_logs",
                        autospec=True) as merge, redirect_stdout(StringIO()):
                    self.assertEqual(merger.main(), 0)
                merge.assert_called_once_with(batches=[(Path("native.log"), 10, 2)], particle_count=2,
                    particle_id_min=11, output_path=Path("merged.log"), receipt_path=Path("merge.json"),
                    scientific_event_outputs=[declaration] if supplied is not None else None)

    def test_actual_mr_emitter_keeps_underscored_event_kind_and_requires_locator(self):
        import subprocess
        lua = Path('C:/Program Files/SIMION-2020/lua.exe')
        if not lua.is_file():
            self.skipTest('Lua runtime unavailable')
        source = (ROOT / 'projects/parallel_mirror_dual_stripe_mr_tof/simion/mrtof_candidate.lua').read_text(encoding='utf-8')
        block = source[source.index('-- The frozen sidecar'):source.index('-- Official SIMION initialize/other_actions/terminate')]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            events = root / 'events.csv'
            script = root / 'record.lua'
            point = '{csv_writer_path=' + json.dumps((ROOT / 'common/simion/scientific_event_csv.lua').as_posix()) + ',events_path=' + json.dumps(events.as_posix()) + ',environment_required=false}'
            script.write_text('local operating_point={scientific_event_output=' + point + '}\n' + block + "\ninitialize_scientific_output();record_scientific('fast_turn',{ion='45',n=1,t_us=7});scientific_events:close()", encoding='utf-8')
            result = subprocess.run([str(lua), str(script)], cwd=script.parent, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            rows = list(io.iter_csv_rows(events, ('kind', 'ion', 't_us')))
            self.assertEqual((rows[0]['kind'], rows[0]['ion'], rows[0]['t_us']), ('fast_turn', '45', '7'))
            script.write_text('local operating_point={scientific_event_output={csv_writer_path=' + json.dumps((ROOT / 'common/simion/scientific_event_csv.lua').as_posix()) + ",environment_required=true,events_environment_variable='MRTOF_TEST_UNSET_REQUIRED_LOCATOR',trajectory_environment_variable='MRTOF_TEST_UNSET_TRAJECTORY_LOCATOR'}}\n" + block + '\ninitialize_scientific_output()', encoding='utf-8')
            result = subprocess.run([str(lua), str(script)], cwd=script.parent, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('batch scientific event locator is required', result.stderr)

    def test_actual_trajectory_callback_preserves_large_sparse_ids_and_sampling(self):
        import subprocess
        lua=Path('C:/Program Files/SIMION-2020/lua.exe')
        if not lua.is_file():
            self.skipTest('Lua runtime unavailable')
        source=(ROOT/'projects/parallel_mirror_dual_stripe_mr_tof/simion/mrtof_candidate.lua').read_text(encoding='utf-8')
        block=source[source.index('-- The frozen sidecar'):source.index('local static_field_adjust')]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            events=root/'events.csv'
            trajectory=root/'trajectory.csv'
            script=root/'callback.lua'
            point=dict(csv_writer_path=(ROOT/'common/simion/scientific_event_csv.lua').as_posix(),events_path=events.as_posix(),trajectory_path=trajectory.as_posix())
            declaration='{'+','.join(key+'='+json.dumps(value) for key,value in point.items())+'}'
            setup='local operating_point={trajectory_recording_enabled=true,trajectory_recording_mode="fixed_interval",trajectory_recording_interval_us=1,scientific_event_output='+declaration+'}\n'
            setup+='ion_number=7;ion_px_mm=0.12345678901234566;ion_py_mm=2;ion_pz_mm=3;ion_vx_mm=4;ion_vy_mm=5;ion_vz_mm=6;ion_time_of_flight=0\nlocal source_id=1000000000000\nlocal function event_id() return source_id end\nlocal function instrument_time_us() return ion_time_of_flight end\n'
            calls='initialize_scientific_output();record_trajectory_sample("initialize");ion_time_of_flight=0.5;record_trajectory_sample("step");ion_time_of_flight=1.25;record_trajectory_sample("step");record_trajectory_sample("terminal");source_id=1000000000045;ion_number=9;record_trajectory_sample("step");scientific_events:close();scientific_trajectory:close()'
            script.write_text(setup+block+'\n'+calls,encoding='utf-8')
            result=subprocess.run([str(lua),str(script)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            rows=list(io.iter_csv_rows(trajectory,('ion','phase','t_us','x_mm')))
            self.assertEqual([row['ion'] for row in rows],['1000000000000']*3+['1000000000045'])
            self.assertEqual([row['phase'] for row in rows],['initialize','step','terminal','step'])
            self.assertEqual([float(row['t_us']) for row in rows],[0,1.25,1.25,1.25])
            self.assertEqual(float(rows[0]['x_mm']),0.12345678901234566)

    def test_stopping_callback_does_not_record_an_unaccepted_trial_step(self):
        import subprocess
        lua = Path('C:/Program Files/SIMION-2020/lua.exe')
        if not lua.is_file():
            self.skipTest('Lua runtime unavailable')
        source = (ROOT/'projects/parallel_mirror_dual_stripe_mr_tof/simion/mrtof_candidate.lua').read_text(encoding='utf-8')
        callbacks = source[source.index('function segment.other_actions()'):source.index('function segment.terminate_run()')]
        setup = r"""
segment={}
local events,samples={},{}
local accelerator_pulse_mode='initial_exit_triggered_single_center'
local accelerator_pulse_complete,accelerator_safe_exit_observed={},{}
local selected_instances={[1]=2}
local solver_birth_times={}
local full_path_timeout_us=0.02
local splat_codes,splat_event_emitted,turns,crossings,detector_native_contacts={},{},{},{},{}
local function accelerator_instance_number() return 3 end
local function maximum_instance_number() return 4 end
local function instrument_time_us() return ion_time_of_flight end
local function event_id() return ion_number end
local function scientific_particle_id(value) return tostring(value) end
local function record_scientific(kind,row) row.kind=kind;events[#events+1]=row end
local function record_trajectory_sample(phase) samples[#samples+1]={phase=phase,t_us=ion_time_of_flight} end
ion_number=1;ion_instance=2;ion_splat=0;ion_volts=0
ion_time_of_flight=0.02;ion_px_mm=5.02;ion_py_mm=5;ion_pz_mm=5
ion_vx_mm=1;ion_vy_mm=0;ion_vz_mm=0
"""
        calls = r"""
segment.other_actions()
assert(ion_splat==2 and splat_codes[1]==2, 'physical timeout decision changed')
assert(#events==1 and events[1].kind=='splat' and events[1].t_us==0.02)
assert(#samples==0, 'unaccepted stopping trial step was recorded')
-- Native2020 observation: terminate reports the preceding accepted state.
ion_time_of_flight=0.018;ion_px_mm=5.018
segment.terminate()
assert(#samples==1 and samples[1].phase=='terminal' and samples[1].t_us==0.018)
assert(#events==2 and events[2].kind=='terminal' and events[2].t_us==0.018 and events[2].splat=='2')
"""
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory)/'termination.lua'
            script.write_text(setup+callbacks+calls, encoding='utf-8')
            result = subprocess.run([str(lua),str(script)], cwd=script.parent, capture_output=True,
                                    text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_structured_merger_preserves_sparse_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batches = []
            declarations = []
            for index, particle in enumerate((11, 45)):
                log = root / f'{index}.log'
                log.write_text('status,Fly completed. 1 splats\n')
                events = root / f'{index}.csv'
                row = dict(kind='terminal', ion=particle, splat=0, instance=1, volts=0, t_us=7, x_mm=0, y_mm=0, z_mm=0, vx_mm_us=0, vy_mm_us=0, vz_mm_us=1, turns=0, central_crossings=0)
                with events.open('w', newline='') as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(row))
                    writer.writeheader()
                    writer.writerow(row)
                batches.append((log, 0, 1))
                declarations.append(dict(events_path=str(events)))
            result = merger._merge_structured_batches(batches=batches, declarations=declarations, particle_count=2, particle_id_min=1, output_path=root / 'merged.log', receipt_path=root / 'merge.json', batch_original_ids=[[11], [45]])
            events, finished, _ = mr.read_scientific_events(root / 'merged.log', scientific_event_output=result['scientific_event_output'])
            self.assertEqual([int(row['ion']) for row in events], [11, 45])
            self.assertEqual(finished[0].splats, 2)
            self.assertNotIn('MRTOF_EVENT', (root / 'merged.log').read_text())

    def test_actual_pilot_schedule_consumes_explicit_csv_and_keeps_legacy(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis import test_bunch_source_and_schedule as fixture
        calls = []

        def consume(**arguments):
            legacy = pilot.freeze_bunch_pulse_schedule_from_files(**arguments)
            trial_path = arguments['pilot_trial_receipt_path']
            trial = json.loads(trial_path.read_text())
            log = arguments['pilot_log_path']
            rows = mr.parse_events(log.read_text())
            events = log.with_suffix('.csv')
            with events.open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            trial['scientific_event_output'] = {'events_path': str(events)}
            trial_path.write_text(json.dumps(trial))
            log.write_text('pilot progress only\n')
            actual = pilot.freeze_bunch_pulse_schedule_from_files(**arguments)
            for key in ('inputs',):
                legacy.pop(key, None)
                actual.pop(key, None)
            self.assertEqual(actual, legacy)
            events.unlink()
            with self.assertRaises(FileNotFoundError):
                pilot.freeze_bunch_pulse_schedule_from_files(**arguments)
            calls.append(True)
            return actual
        with patch.object(fixture, 'freeze_bunch_pulse_schedule_from_files', consume):
            result = unittest.TestResult()
            fixture.BunchSourceAndScheduleTest('test_file_schedule_binds_complete_cohort_and_solver_problem').run(result)
            self.assertEqual(result.errors + result.failures, [])
        self.assertEqual(calls, [True])

    def test_source_z_and_prepared_equivalence_consume_declared_outputs(self):
        from common.contracts.write_run_manifest import file_record
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / 'legacy.log'
            log = root / 'native.log'
            events = root / 'events.csv'
            trajectory = root / 'trajectory.csv'
            text = 'MRTOF_EVENT terminal ion=1 splat=0 instance=1 volts=0 t_us=7 x_mm=0 y_mm=0 z_mm=0 vx_mm_us=0 vy_mm_us=0 vz_mm_us=1 turns=0 central_crossings=0\nMRTOF_TRAJECTORY ion=1 phase=terminal t_us=7 x_mm=0 y_mm=0 z_mm=0 vx_mm_us=0 vy_mm_us=0 vz_mm_us=1\nstatus,Fly completed. 1 splats\n'
            legacy.write_text(text)
            log.write_text('status,Fly completed. 1 splats\n')
            rows = mr.parse_events(text)
            with events.open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            trajectory.write_text('ion,phase,t_us,x_mm,y_mm,z_mm,vx_mm_us,vy_mm_us,vz_mm_us\n1,terminal,7,0,0,0,0,0,1\n')
            declaration = dict(events_path=str(events), trajectory_path=str(trajectory))
            self.assertEqual(source_z._load_selected_events([(legacy, 10, 1)])[0], source_z._load_selected_events([(log, 10, 1, declaration)])[0])
            manifest = root / 'manifest.json'
            manifest.write_text('{}')
            preparation = root / 'preparation.json'
            preparation.write_text(json.dumps(dict(trajectory_equivalence_reference=dict(reference_log=file_record(legacy), reference_manifest=file_record(manifest), original_particle_ids=[1]))))
            receipt = root / 'receipt.json'
            receipt.write_text(json.dumps(dict(scientific_event_output=declaration)))
            result = prepared.compare_trajectory_representation(preparation, log, root / 'comparison.json', scientific_event_receipt=receipt)
            self.assertEqual(result['status'], 'pass')
            trajectory.write_text(trajectory.read_text().replace('1,terminal,7,', '1,terminal,8,'))
            with self.assertRaisesRegex(ValueError, 'differs'):
                prepared.compare_trajectory_representation(preparation, log, root / 'changed.json', scientific_event_receipt=receipt)
            events.unlink()
            with self.assertRaises(FileNotFoundError):
                source_z._load_selected_events([(log, 10, 1, declaration)])

    def test_measured_merge_reads_each_science_once_and_bound_recovery_rejects_damage(self):
        from common.contracts.write_run_manifest import file_record
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preparation = dict(expected_particle_ids=[11, 45], mother_particle_count=100, solver_epoch_instrument_time_us=7)
            prep = root / 'preparation.json'
            prep.write_text(json.dumps(preparation))
            batches = []
            for ion in (11, 45):
                folder = root / str(ion)
                folder.mkdir()
                log = folder / 'native.log'
                log.write_text('status,Fly completed. 1 splats\n')
                events = folder / 'events.csv'
                row = mr.parse_events(f'MRTOF_EVENT terminal ion={ion} splat=0 instance=1 volts=0 t_us=7 x_mm=0 y_mm=0 z_mm=0 vx_mm_us=0 vy_mm_us=0 vz_mm_us=1 turns=0 central_crossings=0\n')[0]
                with events.open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=list(row))
                    writer.writeheader()
                    writer.writerow(row)
                fly = folder / 'joint.fly2'
                fly.write_text('frozen source representation')
                batch = dict(schema_version=1, role='mrtof_measured_source_batch', original_particle_ids=[ion], count=1, solver_epoch_instrument_time_us=7, outputs=dict(source=file_record(fly)), scientific_event_output=dict(events_path=str(events)))
                receipt = folder / 'batch_receipt.json'
                receipt.write_text(json.dumps(batch))
                batches.append((log, receipt))
            with patch.object(merger, 'read_scientific_events', wraps=mr.read_scientific_events) as read:
                result = merger.merge_measured_event_logs(batches=batches, preparation_path=prep, output_path=root / 'merged.log', receipt_path=root / 'merge.json')
                self.assertEqual(read.call_count, 2)
            self.assertEqual(result['original_particle_ids'], [11, 45])
            log, receipt = batches[0]
            declaration = json.loads(receipt.read_text())['scientific_event_output']
            events = Path(declaration['events_path'])
            manifest = dict(inputs={}, outputs=[file_record(events)])
            bound = continuation._bound_scientific_output(declaration, manifest, root)
            self.assertIsNotNone(bound)
            merger.validate_measured_batch_terminal(log_path=log, batch_receipt_path=receipt, preparation=preparation, scientific_event_output=bound)
            events.write_text(events.read_text() + '\n')
            with self.assertRaises(ValueError):
                merger.validate_measured_batch_terminal(log_path=log, batch_receipt_path=receipt, preparation=preparation, scientific_event_output=bound)
            events.unlink()
            self.assertIsNone(continuation._bound_scientific_output(declaration, manifest, root))

    def test_actual_oa_batch_locator_is_frozen_before_dispatch(self):
        import subprocess
        import shutil
        pwsh = shutil.which('pwsh')
        if not pwsh:
            self.skipTest('PowerShell 7 unavailable')
        code = "param($Owner,$Root,$Repo)\n$ErrorActionPreference='Stop';Set-StrictMode -Version Latest\n. (Join-Path $Repo 'common/paths/workspace_paths.ps1')\n$python='@@PYTHON@@'\n$ast=[Management.Automation.Language.Parser]::ParseFile($Owner,[ref]$null,[ref]$null)\nforeach($name in @('New-MrtofBatchRecord','Get-MrtofBatchProcessSpecification')){\n $node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true)\n . ([scriptblock]::Create($node.Extent.Text))\n}\n$batchRuntimeRoot=Join-Path $Root workers;$resultDir=Join-Path $Root results;$logDir=Join-Path $Root logs\nNew-Item -ItemType Directory -Path $batchRuntimeRoot,$resultDir,$logDir|Out-Null\n$bunchSelectionRequested=$false;$bunchSourceLocal='source-receipt';$temporaryIob='shared-readonly.iob';$simion='inert';$solverDir=$Root\n$package=@{artifact_run_dir=(Join-Path $Root 'governed_run');run_dir=(Join-Path $Root 'execution_alias')};$config=@{parameters=@{}};$trial=@{trajectory_recording=$true};$runConfig=Join-Path $Root run_config.json\nfunction Invoke-ProjectPython {param($Arguments)}\nfunction Write-RunJson {param($Path,$Value,$Depth) [IO.File]::WriteAllText($Path,($Value|ConvertTo-Json -Depth 100))}\n$a=New-MrtofBatchRecord -PlannedBatch @{index=1;count=2;particle_id_min=1;particle_id_max=2}\n$b=New-MrtofBatchRecord -PlannedBatch @{index=2;count=3;particle_id_min=3;particle_id_max=5}\n$x=Get-MrtofBatchProcessSpecification -Record $a;$y=Get-MrtofBatchProcessSpecification -Record $b\n$frozen=Get-Content $runConfig -Raw|ConvertFrom-Json -AsHashtable\nif($x.environment.MRTOF_SCIENTIFIC_EVENTS_PATH-eq$y.environment.MRTOF_SCIENTIFIC_EVENTS_PATH){throw 'shared writer path'}\nif(-not$x.environment.MRTOF_SCIENTIFIC_EVENTS_PATH.StartsWith($package.run_dir)){throw 'native locator was not projected'}\nforeach($record in @($a,$b)){\n $declared=$frozen.parameters.scientific_event_outputs[[string]$record.index]\n if($declared.events_path-ne$record.scientific_event_output.events_path){throw 'dispatch differs from frozen locator'}\n if(-not$declared.events_path.StartsWith([IO.Path]::GetFullPath((Join-Path $package.artifact_run_dir 'results'))+[IO.Path]::DirectorySeparatorChar)){throw 'writer escaped private root'}\n}\n'PRIVATE_BATCH_LOCATORS=PASS'\n"
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'batch.ps1'
            script.write_text(code.replace('@@PYTHON@@', sys.executable.replace("'", "''")), encoding='utf-8')
            result = subprocess.run([pwsh, '-NoProfile', '-File', str(script), str(ROOT / 'integrations/workflows/oa_mr/execute.ps1'), directory, str(Path(workspace_paths.__file__).resolve().parents[2])], cwd=script.parent, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PRIVATE_BATCH_LOCATORS=PASS', result.stdout)

    def test_recovery_identity_keeps_physical_sidecar_and_separates_io_locators(self):
        from common.contracts.write_run_manifest import file_record
        with tempfile.TemporaryDirectory() as directory:
            identities = []
            for name in ('parent', 'child'):
                root = Path(directory) / name
                root.mkdir()
                for filename in ('point.lua', 'priority.lua', 'writer.lua', 'binding.json'):
                    (root / filename).write_text('same frozen content')
                locator = root / 'locator.lua'
                locator.write_text('return {events_path=' + repr(str(root / 'events.csv')) + '}')
                trial = dict(schema_version=1, role='mrtof_finite_3d_two_prism_voltage_trial', status='materialized', source_particle_count=2, source_expected_particle_ids=[1, 2], source_time_of_birth_us=0, source_clock_basis='instrument', source_cohort={}, resolved_iob_pose={}, trajectory_profile={}, inputs={}, native_corridor_priority_contract=file_record(root / 'priority.lua'), field_binding=dict(path=str(root / 'binding.json'), mode='native_static_pa'), operating_point_lua_sha256=file_record(root / 'point.lua')['sha256'], scientific_event_output=dict(events_path=str(root / 'events.csv'), trajectory_path=None, csv_writer_path=str(root / 'writer.lua'), environment_required=True), scientific_event_locator=file_record(locator), scientific_csv_writer=file_record(root / 'writer.lua'))
                config = dict(inputs=dict(operating_point_lua=str(root / 'point.lua'), scientific_event_locator=str(locator), scientific_csv_writer=str(root / 'writer.lua'), native_corridor_priority_contract=str(root / 'priority.lua'), static_field_binding=str(root / 'binding.json')))
                hashes = {key: file_record(Path(value))['sha256'].upper() for key, value in config['inputs'].items()}
                identities.append(continuation._trial_execution_identity(trial, config, hashes))
            self.assertEqual(*identities)
            trial['operating_point_lua_sha256'] = 'changed physical sidecar'
            self.assertNotEqual(identities[0], continuation._trial_execution_identity(trial, config, hashes))
            trial['scientific_event_output']['events_path'] = str(Path(directory) / 'escaped.csv')
            with self.assertRaises(ValueError):
                continuation._trial_execution_identity(trial, config, hashes)

    def test_retained_gui_projection_keeps_flight_input_and_relocates_observation(self):
        import subprocess
        import shutil
        pwsh = shutil.which('pwsh')
        lua = Path('C:/Program Files/SIMION-2020/lua.exe')
        if not pwsh or not lua.is_file():
            self.skipTest('PowerShell/Lua unavailable')
        source = (ROOT / 'integrations/workflows/oa_mr/execute.ps1').read_text(encoding='utf-8')
        start = source.index('    $guiOperating=$guiWorkbenchIob.Replace(')
        block = source[start:source.index('    $guiWorkbenchReceipt=', start)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gui = root / 'gui'
            gui.mkdir()
            flight = root / 'flight.lua'
            flight.write_text('unchanged flight input')
            point = gui / 'case.operating_point.lua'
            point.write_text("local p=debug.getinfo(1,'S').source:sub(2);local s=assert(loadfile(p:gsub('%.lua$','.obs.lua')))();return {voltage=123,trajectory_recording_enabled=true,scientific_event_output=s}")
            point.with_suffix('.obs.lua').write_text('return {environment_required=true}')
            script = root / 'gui.ps1'
            script.write_text("param($Root,$Writer)\n$ErrorActionPreference='Stop';Set-StrictMode -Version Latest\n$temporarySolverDir=Join-Path $Root gui;$guiWorkbenchIob=Join-Path $temporarySolverDir case.iob;$sidecar=Join-Path $Root flight.lua\n$trial=@{scientific_event_output=@{csv_writer_path=$Writer}}\nfunction Copy-RequiredInput {param($Source,$Destination,$Label) Copy-Item -LiteralPath $Source -Destination $Destination}\n" + block)
            result = subprocess.run([pwsh, '-NoProfile', '-File', str(script), str(root), str(ROOT / 'common/simion/scientific_event_csv.lua')], cwd=script.parent, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(flight.read_text(), 'unchanged flight input')
            for folder in (gui, root / 'relocated'):
                if folder != gui:
                    shutil.copytree(gui, folder)
                actual = folder / point.name
                code = 'local t=assert(loadfile(arg[1]))();assert(t.voltage==123 and t.scientific_event_output.environment_required==false);print(t.scientific_event_output.events_path);print(t.scientific_event_output.csv_writer_path)'
                check = root / 'check.lua'
                check.write_text(code)
                result = subprocess.run([str(lua), str(check), str(actual)], cwd=check.parent, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                paths = result.stdout.splitlines()
                self.assertEqual(Path(paths[0]).resolve().parent, folder.resolve())
                self.assertTrue(Path(paths[1]).is_file())

    def test_mr_declared_csv_preserves_legacy_types_and_refuses_bad_data(self):
        text = 'MRTOF_EVENT terminal ion=11 splat=0 instance=1 volts=0 t_us=7 x_mm=0 y_mm=0 z_mm=0 vx_mm_us=0 vy_mm_us=0 vz_mm_us=1 turns=0 central_crossings=0\nstatus,Fly completed. 1 splats\n'
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'native.log'
            log.write_text(text)
            original = mr.parse_events(text)
            eventfile = Path(directory) / 'events.csv'
            with eventfile.open('w', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=list(original[0]))
                writer.writeheader()
                writer.writerows(original)
            events, complete, digest = mr.read_scientific_events(log, scientific_event_output=dict(events_path=str(eventfile)))
            self.assertEqual(events, original)
            self.assertEqual(complete[0].splats, 1)
            self.assertEqual(digest, hashlib.sha256(log.read_bytes()).hexdigest())
            self.assertEqual(mr.read_scientific_events(log)[0], original)
            eventfile.unlink()
            with self.assertRaises(FileNotFoundError):
                mr.read_scientific_events(log, scientific_event_output=dict(events_path=str(eventfile)))
            eventfile.write_text('kind,ion\nterminal,11\n')
            with self.assertRaises(ValueError):
                mr.read_scientific_events(log, scientific_event_output=dict(events_path=str(eventfile)))

    def test_actual_typed_emitter_keeps_integer_ids_and_mixed_precision(self):
        import subprocess
        lua = Path('C:/Program Files/SIMION-2020/lua.exe')
        if not lua.is_file():
            self.skipTest('Lua runtime unavailable')
        source = (ROOT / 'projects/parallel_mirror_dual_stripe_mr_tof/simion/mrtof_candidate.lua').read_text(encoding='utf-8')
        block = source[source.index('-- The frozen sidecar'):source.index('-- Official SIMION initialize/other_actions/terminate')]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            events, trajectory = root / 'events.csv', root / 'trajectory.csv'
            point = dict(csv_writer_path=(ROOT / 'common/simion/scientific_event_csv.lua').as_posix(),
                         events_path=events.as_posix(), trajectory_path=trajectory.as_posix(), environment_required=False)
            declaration = '{' + ','.join(key+'='+('false' if value is False else json.dumps(value)) for key,value in point.items()) + '}'
            script = root / 'record.lua'
            code = 'local operating_point={trajectory_recording_enabled=true,scientific_event_output='+declaration+'}\n'+block+"""
initialize_scientific_output()
local value=1.2345678901234567
for _,bad in ipairs({0,-1,1.5,math.huge,0/0,9007199254740992}) do
 assert(not pcall(scientific_particle_id,bad),'invalid scientific ID accepted')
end
record_scientific('detector_plane',{ion=scientific_particle_id(1000000000007),direction_z=-1,t_us=value},
 {raw_t_us=string.format('%.17g',value),native_splat=-1,localization='detector_contact_projection'})
record_scientific(nil,{ion='1000000000007',phase='step',t_us=value,x_mm=0,y_mm=0,z_mm=0,vx_mm_us=0,vy_mm_us=0,vz_mm_us=-1})
scientific_events:close();scientific_trajectory:close()
"""
            script.write_text(code, encoding='utf-8')
            result = subprocess.run([str(lua), str(script)], cwd=script.parent, capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            row = list(io.iter_csv_rows(events, ('kind','ion','t_us','raw_t_us')))[0]
            self.assertEqual(row['ion'], '1000000000007')
            self.assertEqual(row['t_us'], '1.23456789012')
            self.assertEqual(row['raw_t_us'], '1.2345678901234567')
            sample = list(io.iter_csv_rows(trajectory, ('ion','t_us')))[0]
            self.assertEqual(sample['t_us'], '1.2345678901234567')
            script.write_text('local operating_point={}\n'+block, encoding='utf-8')
            refused = subprocess.run([str(lua), str(script)], cwd=script.parent, capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn('frozen scientific event output required', refused.stderr)

    def test_actual_public_freezer_carries_reader_writer_for_real_consumers(self):
        import shutil
        import subprocess
        pwsh = shutil.which('pwsh')
        if not pwsh:
            self.skipTest('PowerShell 7 unavailable')
        for consumer in ('prepared_joint', 'oa_mr', 'accelerator_interface'):
            with self.subTest(consumer=consumer), tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                script = output / 'freeze.ps1'
                script.write_text("param($Repo,$Output,$Consumer)\n$ErrorActionPreference='Stop'\n. (Join-Path $Repo 'integrations/runtime/dependencies.ps1')\n$null=Freeze-ConsumerDependencies -RepoRoot $Repo -ContractPath (Join-Path $Repo 'integrations/config/runtime_dependencies.json') -InputDir $Output -OwnerId instrument_assembly -ConsumerId $Consumer\n", encoding='utf-8')
                result = subprocess.run([pwsh, '-NoProfile', '-File', str(script), str(ROOT), str(output), consumer],
                    cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=120)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                snapshot = output / 'runtime_snapshot'
                for relative in ('common/simion/scientific_event_csv.lua', 'common/simion/scientific_event_io.py'):
                    self.assertEqual((snapshot / relative).read_bytes(), (ROOT / relative).read_bytes())
                check = "import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from common.simion import scientific_event_io;assert Path(scientific_event_io.__file__).is_relative_to(Path(sys.argv[1]));print('FROZEN_EVENT_READER=PASS')"
                imported = subprocess.run([sys.executable, '-I', '-B', '-c', check, str(snapshot)],
                    cwd=output, capture_output=True, text=True, encoding='utf-8', timeout=30)
                self.assertEqual(imported.returncode, 0, imported.stdout+imported.stderr)
                self.assertIn('FROZEN_EVENT_READER=PASS', imported.stdout)

    def test_declared_csv_recovery_scans_native_log_once_and_keeps_breadcrumb(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log, events = root / 'native.log', root / 'events.csv'
            log.write_text('status,Fly completed. 1 splats\nIOB_FLIGHT: PASS iob=fixture.iob\n', encoding='utf-8')
            row = dict(kind='terminal', ion=1, splat=0, instance=1, volts=0, t_us=1,
                       x_mm=0,y_mm=0,z_mm=0,vx_mm_us=0,vy_mm_us=0,vz_mm_us=0,turns=0,central_crossings=0)
            with events.open('w', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(row))
                writer.writeheader();writer.writerow(row)
            original = Path.open
            with patch.object(Path, 'open', autospec=True, side_effect=original) as opened:
                self.assertTrue(continuation._complete_oa_batch(log, 1, dict(events_path=str(events))))
            self.assertEqual(sum(Path(call.args[0]) == log for call in opened.call_args_list), 1)
            log.write_text('status,Fly completed. 1 splats\n', encoding='utf-8')
            self.assertFalse(continuation._complete_oa_batch(log, 1, dict(events_path=str(events))))
