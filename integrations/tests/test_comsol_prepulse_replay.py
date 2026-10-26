from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from integrations.analysis.build_comsol_prepulse_replay import build_comsol_prepulse_replay
from integrations.runtime.single_flight_source import select_timed_pre_pulse_states


INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
REPO = INTEGRATION_ROOT.parent


class ComsolPrePulseReplayTests(unittest.TestCase):
    def test_cartesian_export_without_decision_preserves_complete_timed_population(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            collection,geometry,release,metadata,_=self._write_source(root)
            original=json.loads(collection.read_text())['canonical_events']
            template=next(row for row in original if row['event']=='pre_pulse_state')
            rows=[dict(template,particle_id=i,event='source_release',instrument_time_us=42.+i/1000)
                  for i in range(1,101)]
            rows.extend(dict(template,particle_id=i) for i in range(1,101))
            collection.write_text(json.dumps(self._collection_document(rows)),encoding='utf-8')
            result=build_comsol_prepulse_replay(collection,geometry,release,metadata,mass_amu=100,charge_state=1)
            with release.open() as handle:output=list(csv.DictReader(handle))
            self.assertEqual([int(row['particle_id']) for row in output],list(range(1,101)))
            self.assertEqual(result['selection_basis'],'all_recorded_timed_pre_pulse_states')
            self.assertEqual(result['selection']['mother_particle_ids'],list(range(1,101)))
            self.assertEqual(result['selection']['original_birth_times_us'],{i:42.+i/1000 for i in range(1,101)})
            self.assertEqual(result['clock_epoch_id'],'instrument-test-epoch')
            self.assertEqual(result['selection']['pulse_time_us'],45.5)
            self.assertNotIn('pulse_decision_path',result['inputs'])
            self.assertNotIn('pulse_decision_sha256',result['inputs'])
            for target in output:
                self.assertEqual(float(target['mass_amu']),100.)
                self.assertEqual(int(target['charge_state']),1)
                for axis in 'xyz':
                    self.assertEqual(float(target[f'{axis}_mm']),template[f'{axis}_mm'])
                    self.assertEqual(float(target[f'v{axis}_m_per_s']),template[f'v{axis}_mm_per_us']*1000)

    def test_actual_110745_cartesian_cli_exports_all_original_100_states_without_decision(self):
        run=REPO.parent/'artifacts/projects/instrument_assembly/runs/20261025_110745__sim__simion__single-reflection-flight'
        collection=run/'results/single_reflection/baseline/collection.json'
        geometry=run/'inputs/components/oatof/resolved_design.json'
        species_path=run/'inputs/particle_source_metadata.json'
        if not all(path.is_file() for path in (collection,geometry,species_path)):
            self.skipTest('optional frozen110745 source inputs are not installed')
        actual=json.loads(collection.read_text(encoding='utf-8-sig'))
        selected=select_timed_pre_pulse_states(actual)
        species=json.loads(species_path.read_text(encoding='utf-8-sig'))
        self.assertEqual((species['mass_amu'],species['charge_state']),(100.,1))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);release=root/'release.csv';metadata=root/'metadata.json'
            result=subprocess.run([sys.executable,'-B','-m','integrations.analysis.build_comsol_prepulse_replay',
                '--collection',str(collection),'--geometry',str(geometry),'--release-output',str(release),
                '--metadata-output',str(metadata),'--mass-amu',str(species['mass_amu']),
                '--charge-state',str(species['charge_state'])],cwd=REPO,capture_output=True,text=True,
                encoding='utf-8',timeout=30,check=False)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('PARTICLES=100',result.stdout)
            document=json.loads(metadata.read_text())
            with release.open() as handle:output=list(csv.DictReader(handle))
            self.assertEqual([int(row['particle_id']) for row in output],list(range(1,101)))
            self.assertEqual(document['selection']['mother_particles'],100)
            self.assertEqual(document['clock_epoch_id'],selected['clock_epoch_id'])
            self.assertEqual(document['selection']['pulse_time_us'],selected['pulse_time_us'])
            self.assertEqual(document['selection']['original_birth_times_us'],
                             {str(k):v for k,v in selected['original_birth_times_us'].items()})
            self.assertEqual(document['selection_basis'],'all_recorded_timed_pre_pulse_states')
            self.assertNotIn('pulse_decision_sha256',document['inputs'])
            for target,source in zip(output,selected['selected_rows'],strict=True):
                for axis in 'xyz':
                    self.assertEqual(float(target[f'{axis}_mm']),source[f'{axis}_mm'])
                    self.assertEqual(float(target[f'v{axis}_m_per_s']),source[f'v{axis}_mm_per_us']*1000)

    def test_actual_explicit_timed_collection_consumes_all_recorded_states_without_decision(self):
        path=REPO.parent/'artifacts/projects/instrument_assembly/runs/20261025_110745__sim__simion__single-reflection-flight/results/single_reflection/baseline/collection.json'
        if not path.is_file():self.skipTest('optional frozen 110745 collection is not installed')
        collection=json.loads(path.read_text(encoding='utf-8-sig'))
        result=select_timed_pre_pulse_states(collection)
        actual=[row for row in collection['canonical_events'] if row['event']=='pre_pulse_state']
        self.assertEqual(len(result['selected_rows']),100)
        self.assertEqual(len(result['mother_particle_ids']),100)
        self.assertEqual(result['selected_rows'],actual)
        self.assertEqual(result['clock_epoch_id'],collection['clock_epoch_id'])
        self.assertEqual(result['selection_basis'],'all_recorded_timed_pre_pulse_states')

    @staticmethod
    def _collection_document(rows: list[dict[str, object]], pulse_time_us: float = 45.5) -> dict[str, object]:
        return {
            "schema_version": 1,
            "role": "single_reflection_complete_mother_collection",
            "phase": "full_instrument",
            "native_complete": True,
            "clock_epoch_id": "instrument-test-epoch",
            "flight": {"pulse": {"mode": "timed", "time_us": pulse_time_us}},
            "canonical_events": rows,
        }

    def _write_source(self, root: Path) -> tuple[Path, Path, Path, Path, Path]:
        collection = root / "collection.json"
        geometry = root / "geometry.json"
        release = root / "release.csv"
        metadata = root / "metadata.json"
        pulse_decision = root / "pulse_decision.json"
        collection.write_text(json.dumps(self._collection_document([
            dict(particle_id=7, event="source_release", instrument_time_us=42., x_mm=-69., y_mm=.1, z_mm=-65.5,
                 vx_mm_per_us=4.392, vy_mm_per_us=0., vz_mm_per_us=0., kinetic_energy_eV=9.99616396028),
            dict(particle_id=8, event="source_release", instrument_time_us=42., x_mm=-69., y_mm=.2, z_mm=-65.4,
                 vx_mm_per_us=4.392, vy_mm_per_us=0., vz_mm_per_us=0., kinetic_energy_eV=9.99616396028),
            dict(particle_id=7, event="pre_pulse_state", instrument_time_us=45.5, x_mm=-69., y_mm=.1, z_mm=-65.5,
                 vx_mm_per_us=4.392, vy_mm_per_us=0., vz_mm_per_us=0., kinetic_energy_eV=9.99616396028),
            dict(particle_id=8, event="pre_pulse_state", instrument_time_us=45.5, x_mm=-69., y_mm=.2, z_mm=-65.4,
                 vx_mm_per_us=4.392, vy_mm_per_us=0., vz_mm_per_us=0., kinetic_energy_eV=9.99616396028),
        ])), encoding="utf-8")
        geometry.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "role": "oa_tof_resolved_contract_do_not_edit",
                    "geometry_mm": {
                        "accelerator_repeller_z": -67.0,
                        "accelerator_grid1_z": -64.0,
                    },
                }
            ),
            encoding="utf-8",
        )
        pulse_decision.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "role": "single_reflection_actual_occupancy_pulse_decision",
                    "status": "success",
                    "selection_uses_future_terminal_outcome": False,
                    "actual_pulse_time_us": 45.5,
                    "selection": {
                        "status": "selected",
                        "selected_time_us": 45.5,
                        "execution_cohort_count": 2,
                        "selected": {"eligible_ids": [7]},
                    },
                }
            ),
            encoding="utf-8",
        )
        build_comsol_prepulse_replay(
            collection,
            geometry,
            release,
            metadata,
            mass_amu=100,
            charge_state=1,
            pulse_decision_path=pulse_decision,
        )
        return collection, geometry, release, metadata, pulse_decision

    def test_shared_selector_preserves_decision_order_births_and_state_time(self) -> None:
        collection = self._collection_document([
            dict(particle_id=7, event="source_release", instrument_time_us=42., x_mm=-69., y_mm=.1, z_mm=-65.5,
                 vx_mm_per_us=4.392, vy_mm_per_us=0., vz_mm_per_us=0., kinetic_energy_eV=9.99616396028),
            dict(particle_id=8, event="source_release", instrument_time_us=42.25, x_mm=-69., y_mm=.2, z_mm=-65.4,
                 vx_mm_per_us=4.392, vy_mm_per_us=0., vz_mm_per_us=0., kinetic_energy_eV=9.99616396028),
            dict(particle_id=7, event="pre_pulse_state", instrument_time_us=45.5, x_mm=-69., y_mm=.1, z_mm=-65.5,
                 vx_mm_per_us=4.392, vy_mm_per_us=0., vz_mm_per_us=0., kinetic_energy_eV=9.99616396028),
            dict(particle_id=8, event="pre_pulse_state", instrument_time_us=45.5, x_mm=-69., y_mm=.2, z_mm=-65.4,
                 vx_mm_per_us=4.392, vy_mm_per_us=0., vz_mm_per_us=0., kinetic_energy_eV=9.99616396028),
        ])
        decision = {
            "schema_version": 2,
            "role": "single_reflection_actual_occupancy_pulse_decision",
            "status": "success",
            "selection_uses_future_terminal_outcome": False,
            "actual_pulse_time_us": 45.5,
            "selection": {
                "status": "selected",
                "selected_time_us": 45.5,
                "execution_cohort_count": 2,
                "selected": {"eligible_ids": [8, 7]},
            },
        }
        result = select_timed_pre_pulse_states(collection, decision)
        self.assertEqual(result["selected_particle_ids"], [8, 7])
        self.assertEqual(
            [row["particle_id"] for row in result["selected_rows"]], [8, 7]
        )
        self.assertEqual(result["mother_particle_ids"], [7, 8])
        self.assertEqual(result["original_birth_times_us"], {7: 42.0, 8: 42.25})
        self.assertEqual(result["pulse_time_us"], 45.5)
        recorded=select_timed_pre_pulse_states(collection)
        self.assertEqual(recorded['selected_particle_ids'],[7,8])
        self.assertEqual(recorded['original_birth_times_us'],result['original_birth_times_us'])
        self.assertEqual(recorded['selection_basis'],'all_recorded_timed_pre_pulse_states')
        with_terminal=json.loads(json.dumps(collection))
        with_terminal['canonical_events'].append({**collection['canonical_events'][2], 'event':'lost'})
        self.assertEqual(select_timed_pre_pulse_states(with_terminal)['selected_rows'],recorded['selected_rows'])
        for bad in ('missing_states','duplicate_state','missing_birth','different_time','fake_decision'):
            with self.subTest(no_decision=bad):
                invalid=json.loads(json.dumps(collection))
                if bad=='missing_states':
                    invalid['canonical_events']=[row for row in invalid['canonical_events'] if row['event']!='pre_pulse_state']
                elif bad=='duplicate_state':
                    invalid['canonical_events'].append(invalid['canonical_events'][2].copy())
                elif bad=='missing_birth':
                    invalid['canonical_events'].pop(0)
                elif bad=='different_time':
                    invalid['canonical_events'][2]['instrument_time_us']+=1
                with self.assertRaises(ValueError):
                    select_timed_pre_pulse_states(invalid,{} if bad=='fake_decision' else None)
        for name, change in {
            "old_schema": lambda document: document.update(schema_version=1),
            "wrong_execution_count": lambda document: document["selection"].update(execution_cohort_count=100),
            "missing_execution_count": lambda document: document["selection"].pop("execution_cohort_count"),
        }.items():
            with self.subTest(name=name):
                invalid = json.loads(json.dumps(decision))
                change(invalid)
                with self.assertRaises(ValueError):
                    select_timed_pre_pulse_states(collection, invalid)

    def test_cartesian_release_preserves_global_velocity_and_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, _, release, metadata, _ = self._write_source(Path(directory))
            with release.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["particle_id"], "7")
            self.assertEqual(
                [float(rows[0][name]) for name in ("x_mm", "y_mm", "z_mm")],
                [-69, 0.1, -65.5],
            )
            self.assertEqual(float(rows[0]["vx_m_per_s"]), 4392.0)
            self.assertEqual(float(rows[0]["vy_m_per_s"]), 0.0)
            self.assertEqual(float(rows[0]["vz_m_per_s"]), 0.0)
            self.assertNotIn("azimuth_deg", rows[0])
            document = json.loads(metadata.read_text(encoding="utf-8"))
            self.assertEqual(document["coordinate_frame"], "shared_global_cartesian")
            self.assertEqual(document["selection"]["particle_ids"], [7])
            self.assertEqual(document["selection"]["mother_particle_ids"], [7, 8])
            self.assertLess(document["maximum_velocity_serialization_error_m_per_s"], 1e-6)

    def test_public_cli_consumes_frozen_collection_not_a_checkpoint_csv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            collection, geometry, _, _, pulse_decision = self._write_source(root)
            release = root / "cli.release.csv"
            metadata = root / "cli.metadata.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(INTEGRATION_ROOT / "analysis" / "build_comsol_prepulse_replay.py"),
                    "--collection", str(collection), "--geometry", str(geometry),
                    "--release-output", str(release), "--metadata-output", str(metadata),
                    "--mass-amu", "100", "--charge-state", "1",
                    "--pulse-decision", str(pulse_decision),
                ],
                cwd=REPO,
                env={**os.environ, "PYTHONPATH": str(REPO), "PYTHONNOUSERSITE": "1"},
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("COMSOL_PREPULSE_REPLAY_INPUT=PASS PARTICLES=1", completed.stdout)
            self.assertEqual(json.loads(metadata.read_text())["selection"]["particle_ids"], [7])

            pwsh = shutil.which("pwsh")
            if not pwsh:
                self.skipTest("PowerShell 7 is unavailable")
            frozen_inputs = root / "frozen_inputs"
            freeze_script = root / "freeze.ps1"
            freeze_script.write_text(
                """param($Repo,$Destination)
. (Join-Path $Repo 'integrations/runtime/dependencies.ps1')
$null=Freeze-ConsumerDependencies -RepoRoot $Repo -ContractPath (Join-Path $Repo 'integrations/config/runtime_dependencies.json') -InputDir $Destination -OwnerId instrument_assembly -ConsumerId paired_accelerator_pulse
""",
                encoding="utf-8",
            )
            frozen = subprocess.run(
                [pwsh, "-NoProfile", "-File", str(freeze_script), str(REPO), str(frozen_inputs)],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
            )
            self.assertEqual(frozen.returncode, 0, frozen.stdout + frozen.stderr)
            snapshot = frozen_inputs / "runtime_snapshot"
            self.assertTrue((snapshot / "integrations/analysis/build_comsol_prepulse_replay.py").is_file())
            replay = subprocess.run(
                [
                    sys.executable, "-B", "-s", "-m",
                    "integrations.analysis.build_comsol_prepulse_replay",
                    "--collection", str(collection), "--geometry", str(geometry),
                    "--release-output", str(root / "snapshot.release.csv"),
                    "--metadata-output", str(root / "snapshot.metadata.json"),
                    "--mass-amu", "100", "--charge-state", "1",
                    "--pulse-decision", str(pulse_decision),
                ],
                cwd=snapshot,
                env={**os.environ, "PYTHONPATH": "", "PYTHONNOUSERSITE": "1"},
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
            )
            self.assertEqual(replay.returncode, 0, replay.stdout + replay.stderr)
            self.assertIn("COMSOL_PREPULSE_REPLAY_INPUT=PASS PARTICLES=1", replay.stdout)

    def test_collection_retains_clock_identity_and_rejects_clock_drift(self) -> None:
        for mutation in ("missing_epoch", "native_time_drift"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                collection, geometry, release, metadata, decision = self._write_source(root)
                self.assertEqual(json.loads(metadata.read_text())["clock_epoch_id"], "instrument-test-epoch")
                document = json.loads(collection.read_text())
                if mutation == "missing_epoch":
                    document.pop("clock_epoch_id")
                else:
                    for row in document["canonical_events"]:
                        if row["event"] == "pre_pulse_state" and row["particle_id"] == 7:
                            row["instrument_time_us"] += 1e-8
                collection.write_text(json.dumps(document))
                with self.assertRaises(ValueError):
                    build_comsol_prepulse_replay(collection, geometry, release, metadata,
                        mass_amu=100, charge_state=1, pulse_decision_path=decision)

    def test_canonical_winner_event_fails_closed_without_mother_or_one_clock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, geometry, _, _, pulse_decision = self._write_source(root)
            header = (
                "particle_id,event,instrument_time_us,x_mm,y_mm,z_mm,"
                "vx_mm_per_us,vy_mm_per_us,vz_mm_per_us,kinetic_energy_eV\n"
            )
            cases = {
                "missing_mother": "7,pre_pulse_state,45.5,-69,0,-65.5,4.392,0,0,9.99616396028\n",
                "unknown_selected": (
                    "7,source_release,42,-69,0,-65.5,4.392,0,0,9.99616396028\n"
                    "8,source_release,42,-69,0,-65.5,4.392,0,0,9.99616396028\n"
                    "8,pre_pulse_state,45.5,-69,0,-65.5,4.392,0,0,9.99616396028\n"
                ),
                "split_clock": (
                    "7,source_release,42,-69,0,-65.5,4.392,0,0,9.99616396028\n"
                    "7,pre_pulse_state,45.5,-69,0,-65.5,4.392,0,0,9.99616396028\n"
                    "8,source_release,42,-69,0,-65.5,4.392,0,0,9.99616396028\n"
                    "8,pre_pulse_state,45.6,-69,0,-65.5,4.392,0,0,9.99616396028\n"
                ),
            }
            expected = {
                "missing_mother": "source_release",
                "unknown_selected": "lacks a selected timed source pre-pulse particle",
                "split_clock": "share one pulse time",
            }
            for name, rows in cases.items():
                with self.subTest(name=name):
                    if name == "split_clock":
                        pulse_decision.write_text(
                            json.dumps(
                                {
                                    "schema_version": 2,
                                    "role": "single_reflection_actual_occupancy_pulse_decision",
                                    "status": "success",
                                    "selection_uses_future_terminal_outcome": False,
                                    "actual_pulse_time_us": 45.5,
                                    "selection": {
                                        "status": "selected",
                                        "selected_time_us": 45.5,
                                        "execution_cohort_count": 2,
                                        "selected": {"eligible_ids": [7, 8]},
                                    },
                                }
                            ),
                            encoding="utf-8",
                        )
                    collection = root / f"{name}.json"
                    collection.write_text(
                        json.dumps(self._collection_document(list(csv.DictReader((header + rows).splitlines())))),
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(ValueError, expected[name]):
                        build_comsol_prepulse_replay(
                            collection,
                            geometry,
                            root / f"{name}.release.csv",
                            root / f"{name}.metadata.json",
                            mass_amu=100,
                            charge_state=1,
                            pulse_decision_path=pulse_decision,
                        )

    def test_rejects_particle_outside_stage1(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            collection = root / "collection.json"
            collection.write_text(json.dumps(self._collection_document([
                dict(particle_id=1, event="source_release", instrument_time_us=0., x_mm=-69., y_mm=0., z_mm=-63.,
                     vx_mm_per_us=4.392, vy_mm_per_us=0., vz_mm_per_us=0., kinetic_energy_eV=9.99616396028),
                dict(particle_id=1, event="pre_pulse_state", instrument_time_us=1., x_mm=-69., y_mm=0., z_mm=-63.,
                     vx_mm_per_us=4.392, vy_mm_per_us=0., vz_mm_per_us=0., kinetic_energy_eV=9.99616396028),
            ], pulse_time_us=1.)), encoding="utf-8")
            geometry = root / "geometry.json"
            geometry.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "role": "oa_tof_resolved_contract_do_not_edit",
                        "geometry_mm": {
                            "accelerator_repeller_z": -67,
                            "accelerator_grid1_z": -64,
                        },
                    }
                ),
                encoding="utf-8",
            )
            decision = root / "pulse_decision.json"
            decision.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "role": "single_reflection_actual_occupancy_pulse_decision",
                        "status": "success",
                        "selection_uses_future_terminal_outcome": False,
                        "actual_pulse_time_us": 1,
                        "selection": {
                            "status": "selected",
                            "selected_time_us": 1,
                            "execution_cohort_count": 1,
                            "selected": {"eligible_ids": [1]},
                        },
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "outside accelerator stage 1"):
                build_comsol_prepulse_replay(
                    collection,
                    geometry,
                    root / "out.csv",
                    root / "metadata.json",
                    mass_amu=100,
                    charge_state=1,
                    pulse_decision_path=decision,
                )


if __name__ == "__main__":
    unittest.main()
