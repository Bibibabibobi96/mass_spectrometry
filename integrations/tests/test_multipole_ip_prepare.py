"""Solver-free handoff behavior using explicit native-step fixture observations."""
from __future__ import annotations

import copy
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from common.contracts.particle_state import PARTICLE_STATE_COLUMNS
from common.contracts.write_run_manifest import file_record
from projects.rf_multipole_ion_optics.core.compile_design_request import compile_design_request
from projects.rf_multipole_ion_optics.core.component_port import prepare_exit_observation_inputs, validate_exit_observations
from projects.rf_multipole_ion_optics.tests.domain.test_compile_design_request import design_request
from common.integration.resolve_assembly import compile_assembly_layout, derive_assembly_scope
from common.contracts.rigid_transform import RigidTransform
from projects.dual_pressure_rectilinear_ion_processor.analysis.assembly_interface import resolve_assembly_interface
from projects.dual_pressure_rectilinear_ion_processor.analysis.native_geometry import native_projection
from integrations.workflows.multipole_ip.prepare import FRAME, prepare
from projects.dual_pressure_rectilinear_ion_processor.analysis.upstream_admission import load_injected_source

REPO = Path(__file__).resolve().parents[2]


def write_json(path, value):
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def write_csv(path, rows, columns):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class MultipoleIPPreparationTests(unittest.TestCase):
    def test_current_three_component_parent_derives_both_scopes_without_repositioning(self):
        parent = json.loads((REPO / 'integrations/config/recipes/multipole_ip_mr_y_minus55_plan.json').read_text())
        self.assertEqual(parent, derive_assembly_scope(parent))
        self.assertEqual(set(parent['components']), {'multipole', 'ion_processor', 'mrtof'})
        self.assertEqual(set(parent['components']['ion_processor']['ports']), {'guide_inlet', 'extraction_exit'})
        for ids in (['multipole', 'ion_processor'], ['ion_processor', 'mrtof']):
            local = derive_assembly_scope(parent, local_scope=dict(instance_ids=ids,
                research_scope='explicit segment of the frozen instrument',
                boundary_assumptions='omitted components are not included in this segment field'))
            self.assertEqual(local['recipe'], parent['recipe'])
            self.assertEqual(local['components'], parent['components'])
            self.assertEqual(len(local['scope']['connection_ids']), 1)
            self.assertEqual(len(local['scope']['boundary_connection_ids']), 1)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source, self.receiver, self.run = [self.root / name for name in ("source", "receiver", "assembly")]
        for run in (self.source, self.receiver, self.run):
            (run / "inputs").mkdir(parents=True)
            (run / "results").mkdir()
        request = design_request("octupole")
        request["geometry_mm"]["numerical_domain"].update(z_max_mm=90.)
        resolved = compile_design_request(request, expected_identity=request["identity"])
        write_json(self.source / "inputs/multipole_resolved_design.json", resolved)
        self.observation = prepare_exit_observation_inputs(self.source, resolved, design_profile_id="fixture", cell_z_mm=.3)
        self.originals = [dict(particle_id=pid, birth_time_s=pid * 1e-7, mass_amu=100., charge_state=1) for pid in (2, 9)]
        write_csv(self.source / "inputs/particle_source.csv", self.originals, list(self.originals[0]))
        def event(pid, kind, time, axial):
            row = dict.fromkeys(PARTICLE_STATE_COLUMNS, 0.)
            row.update(particle_id=pid, event=kind, time_us=time, elapsed_time_us=time-pid*.1,
                axial_z_mm=axial, transverse_x_mm=.4, transverse_y_mm=-.3,
                velocity_axial_m_s=2000., velocity_x_m_s=30., velocity_y_m_s=-20.,
                status="transmitted" if kind == "mechanical_exit" else "lost",
                terminal_reason="none" if kind == "mechanical_exit" else "unknown")
            return row
        exit_z = self.observation["mechanical_exit_z_mm"]
        self.events = [event(2, "mechanical_exit_step_before", 42., exit_z-1.),
                       event(2, "mechanical_exit_step_after", 44., exit_z+1.),
                       event(2, "mechanical_exit", 43., exit_z), event(2, "terminal", 44.2, exit_z+.3),
                       event(9, "terminal", 20., 30.)]
        self.state = self.source / "results/mechanical_exit_states__rf_on.csv"
        self.census = self.source / "results/mechanical_exit_census__rf_on.json"
        self.publish_events()
        model = {name: json.loads((REPO / "projects/dual_pressure_rectilinear_ion_processor/config" / f"{name}.json").read_text())
                 for name in ("baseline", "numerics")}
        write_json(self.receiver / "inputs/resolved_model.json", model)
        self.source_summary = dict(schema_version=1, role="multipole_simion_finite_3d_transport_summary",
            status="success", project_id="rf_multipole_ion_optics", design_profile_id="fixture",
            qualification_status="UNQUALIFIED")
        write_json(self.source / "summary.json", self.source_summary)
        self.source_selection = self.publish_manifest(self.source, "rf_multipole_ion_optics", "source_run")
        self.source_selection["case_id"] = "rf_on"
        receiver_selection = self.publish_manifest(self.receiver, "dual_pressure_rectilinear_ion_processor", "receiver_run")
        def pose(frame, rotation, translation):
            return dict(schema_version=1, role="rigid_transform", from_frame_id=frame, to_frame_id=FRAME,
                        rotation=rotation, translation_mm=translation)
        recipe=dict(
                schema_version=1, role="assembly_recipe", integration_id="instrument_assembly", recipe_id="fixture",
                assembly_frame_id=FRAME, position_tolerance_mm=1e-9, angular_tolerance_rad=1e-9,
                instances=[dict(instance_id="multipole", project_id="rf_multipole_ion_optics",
                    transform=pose(resolved["coordinate"]["coordinate_id"], [[0,0,1],[1,0,0],[0,1,0]], [-exit_z,0.,0.])),
                    dict(instance_id="ion_processor", project_id="dual_pressure_rectilinear_ion_processor",
                    transform=pose(FRAME, [[1,0,0],[0,1,0],[0,0,1]], [0.,0.,0.]))],
                connections=[dict(connection_id="inlet", upstream=dict(instance_id="multipole", port_id="mechanical_exit"),
                    downstream=dict(instance_id="ion_processor", port_id="guide_inlet"), gap_mm=0., coupling_mode="state_handoff")])
        self.parent=compile_assembly_layout(recipe,dict(
            multipole=json.loads((self.source/'inputs/mechanical_exit_interface.json').read_text()),
            ion_processor=resolve_assembly_interface(native_projection(model['baseline'],model['numerics']))))
        self.parent_path=self.root/'parent_plan.json'
        self.request = dict(schema_version=2, role="multipole_ip_preparation_request", source=self.source_selection,
            receiver=receiver_selection,species_id='octupole_100da',particle_weight=1.)
        self.write_parent()
        self.request_path = self.root / "request.json"

    def publish_events(self):
        write_csv(self.state, self.events, PARTICLE_STATE_COLUMNS)
        census = validate_exit_observations(self.state, self.source / "inputs/particle_source.csv", self.observation)
        write_json(self.census, census)

    def publish_manifest(self, run, project, run_id):
        write_json(run / "run_config.json", dict(project=project, run_id=run_id))
        summary_path = run / "summary.json"
        status = json.loads(summary_path.read_text())["status"] if summary_path.exists() else "success"
        manifest = dict(schema_version=2, project=project, run_id=run_id, status=status,
            run_config=file_record(run / "run_config.json"),
            inputs={p.name: file_record(p) for p in (run / "inputs").iterdir()},
            outputs=[file_record(p) for p in (run / "results").iterdir()]
                    + ([file_record(summary_path)] if summary_path.exists() else []))
        path = run / "run_manifest.json"
        write_json(path, manifest)
        return dict(manifest=file_record(path), project_id=project, run_id=run_id)

    def refresh_source(self):
        self.source_selection.update(self.publish_manifest(self.source, "rf_multipole_ion_optics", "source_run"))

    def execute(self):
        self.write_parent()
        write_json(self.request_path, self.request)
        return prepare(self.request_path, self.run)

    def write_parent(self):
        write_json(self.parent_path,self.parent)
        self.request['composition_plan']=file_record(self.parent_path)

    def rename_instances(self):
        recipe = self.parent['recipe']
        ids = {"multipole": "guide_a", "ion_processor": "processor_b"}
        for instance in recipe["instances"]:
            instance["instance_id"] = ids[instance["instance_id"]]
        for endpoint in ("upstream", "downstream"):
            recipe["connections"][0][endpoint]["instance_id"] = ids[recipe["connections"][0][endpoint]["instance_id"]]
        recipe["instances"].reverse()
        components={ids[key]:value for key,value in self.parent['components'].items()}
        self.parent=compile_assembly_layout(recipe,components)

    def test_recipe_instance_rename_changes_only_route_identity(self):
        self.execute()
        original_run = self.run
        original = load_injected_source(original_run / "results/multipole_ip/ip_injected_source.json")
        self.rename_instances()
        self.run = self.root / "renamed_assembly"
        (self.run / "inputs").mkdir(parents=True)
        self.execute()
        renamed = load_injected_source(self.run / "results/multipole_ip/ip_injected_source.json")
        self.assertEqual(renamed["contract"]["target_component_id"], "processor_b")
        row = dict(renamed["rows"][0])
        self.assertEqual(row.pop("source_component_id"), "guide_a")
        self.assertEqual(row.pop("target_component_id"), "processor_b")
        self.assertEqual(row, {key:value for key,value in original["rows"][0].items()
                               if key not in {"source_component_id", "target_component_id"}})
        self.assertEqual(renamed["mother_fates"], original["mother_fates"])
        self.assertEqual(renamed["census"], original["census"])
        for relative in ("inputs/clock_authority.json", "inputs/instrument_epoch.json",
                         "results/multipole_ip/mother_fates.csv", "results/multipole_ip/mother_census.json"):
            self.assertEqual((self.run / relative).read_bytes(), (original_run / relative).read_bytes())
        plan = json.loads((self.run / "results/multipole_ip/composition_plan.json").read_text())
        self.assertEqual(set(plan["components"]), {"guide_a", "processor_b"})
        self.assertEqual(plan["recipe"]["connections"], self.parent['recipe']["connections"])

    def test_one_pose_preserves_sparse_ids_species_birth_arrival_and_unknown_terminal(self):
        receipt = self.execute()
        admission = load_injected_source(self.run / "results/multipole_ip/ip_injected_source.json")
        self.assertEqual((receipt["mother_count"], receipt["exit_count"]), (2, 1))
        row = admission["rows"][0]
        self.assertEqual((row["particle_id"], row["mass_amu"], row["charge_state"]), (2, 100., 1))
        self.assertEqual(row["particle_birth_time_us"], self.originals[0]["birth_time_s"] * 1e6)
        self.assertEqual(row["instrument_time_us"], 43.)
        self.assertEqual([row[f"position_{a}_mm"] for a in "xyz"], [0., .4, -.3])
        self.assertEqual([row[f"velocity_{a}_m_s"] for a in "xyz"], [2000., 30., -20.])
        self.assertGreater(row["kinetic_energy_eV"], 0.)  # raw interpolation fixture energy is deliberately zero
        self.assertIsNone(row["phase_reference_id"])
        self.assertEqual(admission["mother_fates"][2]["terminal_reason"], "unknown")
        self.assertEqual(admission["census"]["non_exit_particle_ids"], [9])
        for name in ("clock_authority", "instrument_epoch"):
            self.assertEqual((self.run / f"inputs/{name}.json").read_bytes(), (self.source / f"inputs/{name}.json").read_bytes())

    def test_parent_growth_preserves_local_states_mother_and_clock(self):
        self.execute()
        baseline=self.run
        parent=copy.deepcopy(self.parent)
        selected=['multipole','ion_processor']
        for count in (3,4):
            recipe,components=copy.deepcopy(parent['recipe']),copy.deepcopy(parent['components'])
            for index in range(count-2):
                extra=copy.deepcopy(recipe['instances'][0])
                extra['instance_id']=f'spare_{index}'
                extra['transform']['translation_mm'][1]+=1000.*(index+1)
                recipe['instances'].append(extra)
                components[extra['instance_id']]=copy.deepcopy(components['multipole'])
            recipe['instances'].reverse()
            self.parent=compile_assembly_layout(recipe,components)
            self.request['local_scope']=dict(instance_ids=selected,research_scope='existing MP to IP handoff',
                boundary_assumptions='unselected instruments do not propagate or change the recorded states')
            self.run=self.root/f'local_{count}'
            (self.run/'inputs').mkdir(parents=True)
            self.execute()
            for relative in ('inputs/clock_authority.json','inputs/instrument_epoch.json',
                             'results/multipole_ip/source_states.csv','results/multipole_ip/mother_fates.csv',
                             'results/multipole_ip/mother_census.json'):
                self.assertEqual((self.run/relative).read_bytes(),(baseline/relative).read_bytes())
            frozen=json.loads((self.run/'inputs/parent_composition_plan.json').read_text())
            self.assertEqual(len(frozen['recipe']['instances']),count)
            derived=json.loads((self.run/'results/multipole_ip/composition_plan.json').read_text())
            self.assertEqual(set(derived['scope']['instance_ids']),set(selected))
            self.run=self.root/f'unsupported_full_{count}'
            (self.run/'inputs').mkdir(parents=True)
            del self.request['local_scope']
            with self.assertRaisesRegex(ValueError,'exactly one selected real multipole and IP'):
                self.execute()

    def test_global_parent_pose_preserves_ip_local_states_and_frozen_layout(self):
        self.execute()
        baseline = self.run
        original = copy.deepcopy(self.parent)
        registration = RigidTransform(FRAME, "instrument_global",
            ((0., -1., 0.), (0., 0., -1.), (1., 0., 0.)), (120., -225., 10.))
        for local in (False, True):
            with self.subTest(local=local):
                recipe = copy.deepcopy(original['recipe'])
                components = copy.deepcopy(original['components'])
                recipe['assembly_frame_id'] = registration.to_frame_id
                for instance in recipe['instances']:
                    instance['transform'] = RigidTransform.from_contract(instance['transform']).then(registration).to_contract()
                if local:
                    extra = copy.deepcopy(recipe['instances'][0])
                    extra['instance_id'] = 'unselected_guide'
                    extra['transform']['translation_mm'][0] += 1000.
                    recipe['instances'].append(extra)
                    components['unselected_guide'] = copy.deepcopy(components['multipole'])
                    self.request['local_scope'] = dict(instance_ids=['multipole', 'ion_processor'],
                        research_scope='IP-local injection from a global parent',
                        boundary_assumptions='unselected guide is outside the state handoff calculation')
                self.parent = compile_assembly_layout(recipe, components)
                self.run = self.root / f'global_parent_{local}'
                (self.run / 'inputs').mkdir(parents=True)
                self.execute()
                for relative in ('inputs/clock_authority.json', 'inputs/instrument_epoch.json',
                                 'results/multipole_ip/source_states.csv', 'results/multipole_ip/mother_fates.csv',
                                 'results/multipole_ip/mother_census.json'):
                    self.assertEqual((self.run / relative).read_bytes(), (baseline / relative).read_bytes())
                frozen = json.loads((self.run / 'inputs/parent_composition_plan.json').read_text())
                self.assertEqual(frozen, self.parent)
                derived = json.loads((self.run / 'results/multipole_ip/composition_plan.json').read_text())
                self.assertEqual(derived['recipe'], recipe)
                self.assertEqual(derived['scope']['kind'], 'local' if local else 'full')

    def test_parent_sources_are_embedded_and_selected_interface_must_match(self):
        self.parent['components']['ion_processor']['geometry_profile_id']='frozen_receiver'
        self.parent['input_files']={key:dict(path='unavailable_'+key+'.json',sha256='A'*64)
                                   for key in ('recipe','components')}
        self.execute()
        self.run=self.root/'wrong_interface'
        (self.run/'inputs').mkdir(parents=True)
        self.parent['components']['ion_processor']['ports']['guide_inlet']['cross_section']['inscribed_radius_mm']+=.1
        # The edited physical interface remains a valid complete parent layout;
        # the current receiver publication must nevertheless reject it.
        self.parent=compile_assembly_layout(self.parent['recipe'],self.parent['components'])
        with self.assertRaisesRegex(ValueError,'provider interface differs'):
            self.execute()

    def publish_scientific_failure(self):
        checks = dict(minimum_primary_transmission=False, minimum_transmission_improvement=True)
        self.source_summary.update(status="failed", native_execution_complete=True,
                                   qualification_status="FAIL", checks=checks)
        write_json(self.source / "summary.json", self.source_summary)
        write_json(self.source / "results/evidence_evaluation.json", dict(
            schema_version=1, role="multipole_transport_evidence_evaluation", status="FAIL",
            project_id="rf_multipole_ion_optics", design_profile_id="fixture",
            evaluation="rf_vs_zero_rf", checks=checks))
        self.refresh_source()
        return checks

    def test_complete_scientific_failure_preserves_actual_partial_exit_and_qualification(self):
        checks = self.publish_scientific_failure()
        receipt = self.execute()
        admission = load_injected_source(self.run / "results/multipole_ip/ip_injected_source.json")
        self.assertEqual((receipt["mother_count"], receipt["exit_count"]), (2, 1))
        self.assertEqual(receipt["producer_result"], admission["producer_result"])
        self.assertEqual(receipt["producer_result"]["source_scientific_status"], "failed")
        self.assertEqual(receipt["producer_result"]["checks"], checks)
        self.assertEqual(receipt["producer_result"]["qualification_status"], "FAIL")
        self.assertEqual([row["particle_id"] for row in admission["rows"]], [2])
        self.assertEqual(admission["census"]["non_exit_particle_ids"], [9])
        self.assertEqual(json.loads((self.source / "summary.json").read_text()), self.source_summary)

    def test_old_or_incomplete_failed_result_and_wrong_evaluation_are_rejected(self):
        checks = dict(minimum_primary_transmission=False)
        valid = dict(self.source_summary, status="failed", native_execution_complete=True,
                     qualification_status="FAIL", checks=checks)
        evaluation = dict(schema_version=1, role="multipole_transport_evidence_evaluation",
            status="FAIL", project_id="rf_multipole_ion_optics", design_profile_id="fixture",
            evaluation="rf_vs_zero_rf", checks=checks)
        for scenario in ("generic_failed", "incomplete", "check_drift", "nonboolean_checks", "wrong_evaluation"):
            with self.subTest(scenario=scenario):
                summary, decision = copy.deepcopy(valid), copy.deepcopy(evaluation)
                if scenario == "generic_failed":
                    summary = dict(schema_version=1, role=valid["role"], status="failed", reason="solver failed")
                elif scenario == "incomplete":
                    summary["native_execution_complete"] = False
                elif scenario == "check_drift":
                    summary["checks"] = {"minimum_primary_transmission": True}
                elif scenario == "nonboolean_checks":
                    summary["checks"] = {"minimum_primary_transmission": 0}
                else:
                    decision["project_id"] = "wrong"
                write_json(self.source / "summary.json", summary)
                write_json(self.source / "results/evidence_evaluation.json", decision)
                self.refresh_source()
                with self.assertRaises(ValueError):
                    self.execute()
                self.assertFalse((self.run / "results/multipole_ip").exists())

    def test_zero_exit_preserves_fates_and_null_record_without_empty_canonical_table(self):
        self.rename_instances()
        self.events = [row for row in self.events if row["event"] == "terminal"]
        self.publish_events(); self.refresh_source()
        self.execute()
        admission = load_injected_source(self.run / "results/multipole_ip/ip_injected_source.json")
        self.assertEqual(admission["rows"], [])
        self.assertIsNone(admission["contract"]["source_states"])
        self.assertEqual(admission["contract"]["target_component_id"], "processor_b")
        self.assertFalse((self.run / "results/multipole_ip/source_states.csv").exists())
        self.assertEqual(set(admission["mother_fates"]), {2, 9})

    def test_open_rod_envelope_does_not_clip_actual_exit_states(self):
        for row in self.events:
            if row["particle_id"] == 2:
                row["transverse_x_mm"] = 2.5
        self.publish_events(); self.refresh_source()
        self.execute()
        admission = load_injected_source(self.run / "results/multipole_ip/ip_injected_source.json")
        self.assertEqual(admission["rows"][0]["position_y_mm"], 2.5)

    def test_positive_gap_and_receiver_motion_rejected_before_outputs(self):
        original = copy.deepcopy((self.request,self.parent))
        for modification in ("gap", "receiver"):
            self.request,self.parent = copy.deepcopy(original)
            if modification == "gap":
                self.parent['recipe']["connections"][0]["gap_mm"] = 1.
            else:
                for instance in self.parent['recipe']["instances"]:
                    instance["transform"]["translation_mm"][1] += 1.
            with self.subTest(modification=modification), self.assertRaises(ValueError):
                self.execute()
            self.assertFalse((self.run / "results/multipole_ip").exists())

    def test_wrong_topology_provider_port_or_coupling_rejected_before_outputs(self):
        original = copy.deepcopy((self.request,self.parent))
        for change in ("extra_instance", "extra_edge", "same_instance", "unknown_instance", "wrong_provider",
                       "upstream_port", "downstream_port", "coupling"):
            with self.subTest(change=change):
                self.request,self.parent = copy.deepcopy(original)
                self.rename_instances()
                recipe = self.parent['recipe']
                edge = recipe["connections"][0]
                if change == "extra_instance":
                    recipe["instances"].append(dict(recipe["instances"][0], instance_id="unused"))
                elif change == "extra_edge":
                    recipe["connections"].append(dict(edge, connection_id="extra"))
                elif change == "same_instance":
                    edge["downstream"]["instance_id"] = edge["upstream"]["instance_id"]
                elif change == "unknown_instance":
                    edge["upstream"]["instance_id"] = "absent"
                elif change == "wrong_provider":
                    recipe["instances"][0]["project_id"] = "rf_multipole_ion_optics"
                elif change == "upstream_port":
                    edge["upstream"]["port_id"] = "guide_inlet"
                elif change == "downstream_port":
                    edge["downstream"]["port_id"] = "mechanical_exit"
                else:
                    edge["coupling_mode"] = "monolithic_joint_solve"
                with self.assertRaises(ValueError):
                    self.execute()
                self.assertFalse((self.run / "results/multipole_ip").exists())

    def test_wrong_producer_identity_and_unfinished_publication_rejected(self):
        self.request["source"]["run_id"] = "wrong"
        with self.assertRaisesRegex(ValueError, "identity"):
            self.execute()
        self.request["source"]["run_id"] = "source_run"
        from common.contracts.write_run_manifest import TERMINAL_JOURNAL_NAME
        (self.source / TERMINAL_JOURNAL_NAME).write_text("{}")
        with self.assertRaisesRegex(ValueError, "publication is incomplete"):
            self.execute()

    def test_tampered_consumed_input_rejected_without_hashing_unconsumed_payload(self):
        manifest = json.loads((self.source / "run_manifest.json").read_text())
        manifest["outputs"].append(dict(path=str(self.source / "absent_large.pa0"), bytes=999999999, sha256="A"*64))
        write_json(self.source / "run_manifest.json", manifest)
        self.source_selection["manifest"] = file_record(self.source / "run_manifest.json")
        self.execute()  # irrelevant large payload is never opened
        (self.source / "inputs/particle_source.csv").write_text("tampered")
        with self.assertRaises(AssertionError):
            self.execute()

    def test_old_handoff_wrong_frame_or_time_is_not_admitted(self):
        original_events = copy.deepcopy(self.events)
        for change in ("handoff", "clock", "frame"):
            self.events = copy.deepcopy(original_events)
            if change == "handoff":
                self.events[2]["event"] = "handoff"
            elif change == "clock":
                self.events[2]["elapsed_time_us"] += 1
            else:
                observation = dict(self.observation, frame_id="wrong_frame")
                write_json(self.source / "inputs/mechanical_exit_observation.json", observation)
            write_csv(self.state, self.events, PARTICLE_STATE_COLUMNS)
            self.refresh_source()
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.execute()
            self.assertFalse((self.run / "results/multipole_ip").exists())

    def test_real_freezer_runs_preparation_and_admission_without_repository(self):
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 is unavailable")
        self.publish_scientific_failure()
        self.rename_instances()
        self.write_parent()
        write_json(self.request_path, self.request)
        inventory = REPO / "integrations/config/runtime_dependencies.json"
        script = f"""
. '{REPO / 'integrations/runtime/dependencies.ps1'}'
$null=Freeze-ConsumerDependencies -RepoRoot '{REPO}' -ContractPath '{inventory}' -InputDir '{self.run / 'inputs'}' -OwnerId instrument_assembly -ConsumerId multipole_ip
"""
        frozen = subprocess.run([pwsh, "-NoProfile", "-Command", script], cwd=REPO,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(frozen.returncode, 0, frozen.stdout + frozen.stderr)
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        statement = (
            "from pathlib import Path; from integrations.workflows.multipole_ip import prepare; "
            "from projects.dual_pressure_rectilinear_ion_processor.analysis.upstream_admission import load_injected_source; "
            "assert Path(prepare.__file__).is_relative_to(Path.cwd()); "
            f"prepare.prepare(Path({str(self.request_path)!r}),Path({str(self.run)!r})); "
            f"a=load_injected_source(Path({str(self.run / 'results/multipole_ip/ip_injected_source.json')!r})); "
            "assert len(a['rows'])==1 and a['rows'][0]['particle_id']==2; "
            "assert a['rows'][0]['source_component_id']=='guide_a'; "
            "assert a['rows'][0]['target_component_id']==a['contract']['target_component_id']=='processor_b'; "
            "assert [a['rows'][0]['position_'+v+'_mm'] for v in 'xyz']==[0.,.4,-.3]; "
            "assert [a['rows'][0]['velocity_'+v+'_m_s'] for v in 'xyz']==[2000.,30.,-20.]; "
            "assert a['producer_result']['source_scientific_status']=='failed'; "
            "assert a['producer_result']['checks']['minimum_primary_transmission'] is False; "
            "print('DETACHED_PREPARATION=PASS')")
        completed = subprocess.run([sys.executable, "-B", "-s", "-c", statement],
            cwd=self.run / "inputs/runtime_snapshot", env=environment,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("DETACHED_PREPARATION=PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()
