from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import ValidationError

import copy
from common.integration.resolve_assembly import compile_assembly_layout, derive_assembly_scope
from common.contracts.component_particle_state import write_component_particle_state_csv
from common.contracts.file_identity import file_sha256
from common.contracts.particle_physics import kinetic_energy_ev
from common.contracts.rigid_transform import RigidTransform
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff import prepare_handoff, resolve_ip_mr_connection, resolve_matching_request


def handoff_plan(recipe):
    """Frozen mechanical provider fixture; no solver or external run dependency."""
    baseline = json.loads((Path(__file__).parents[4] / 'integrations/config/recipes/ip_mr_y_minus55_plan.json').read_text())
    by_project = {value['project_id']: value for value in baseline['components'].values()}
    components = {}
    for item in recipe['instances']:
        interface = copy.deepcopy(by_project[item['project_id']])
        interface['local_frame_id'] = item['transform']['from_frame_id']
        components[item['instance_id']] = interface
    return compile_assembly_layout(recipe, components)


class IonProcessorHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.receipt_path = self.root / "component_exit_receipt.json"
        self.trajectory = self.root / "trajectory.json"
        self.provider = self.root / "provider.json"
        self.request = self.root / "request.json"
        self.output = self.root / "prepared"
        self.recipe_path = self.root / "recipe.json"
        recipe = json.loads((Path(__file__).parents[4] / "integrations/config/recipes/ip_mr_y_minus55_plan.json").read_text())["recipe"]
        recipe["assembly_frame_id"] = "mr_frame.v2"
        for instance in recipe["instances"]:
            instance["transform"]["to_frame_id"] = "mr_frame.v2"
            instance["transform"]["from_frame_id"] = "ip.native" if instance["instance_id"] == "ip_exit_shield" else "mr_frame.v2"
        self.recipe = recipe
        self._write(self.recipe_path, recipe)
        self.model = self.root / "resolved_model.json"
        self._write(self.model, dict(coordinate_transform=dict(
            schema_version=1, role="rigid_transform", from_frame_id="ip.native", to_frame_id="ip_frame.v2",
            rotation=[[0,0,-1],[1,0,0],[0,-1,0]], translation_mm=[0,0,9.8])))
        project = Path(__file__).parents[2]
        request = json.loads((project / "config/ion_processor_matching_request.json").read_text())
        request["composition_plan"] = {"path": "recipe.json"}
        self._write(self.request, request)
        self._write(self.trajectory, {
            "coordinate_system": {"frame_id": "mr_frame.v2"},
            "accelerator": {"focus_y_anchor": {"project_y_mm": -55}},
            "accelerator_energy_contract": {"net_gain_reference_center_per_charge_v": 4000},
        })
        self._write(self.provider, {"mrtof_projection": {"target_axial_energy_per_charge_v": 4372.010347796}})
        self.rows = [self._row(1), self._row(7)]
        self.source = self.root / "source.csv"
        write_component_particle_state_csv(self.source, self.rows)
        self.census = self.root / "census.csv"
        self.census.write_text("particle_id,transfer_status,terminal_reason,instrument_time_us,particle_birth_time_us,particle_age_us\n1,transferred,downstream_domain_exit,7500.6,0,7500.6\n7,transferred,downstream_domain_exit,7500.7,0,7500.7\n9,not_transferred,solver_stop,21,0,21\n", encoding="utf-8", newline="\n")
        self.receipt = {
            "schema_version": 2, "role": "ion_processor_component_exit_export",
            "source_instance_id": "ip_exit_shield", "target_instance_id": "mr_entry_frame",
            "source_project": "dual_pressure_rectilinear_ion_processor", "status": "prepared",
            "frame_id": "ip_frame.v2", "clock_epoch_id": "ion_processor_epoch_zero_v1",
            "inputs": {"inputs/resolved_model.json": self._identity(self.model)},
            "counts": {"source": 3, "transferred": 2, "not_transferred": 1},
            "transferred_particle_ids": [1, 7], "lost_particle_ids": [9],
            "observation_surface": {"center_mm": [0, 170, 0], "normal": [0, 0, -1]},
            "outputs": {"component_states": self._identity(self.source), "mother_census": self._identity(self.census)},
        }
        self._write(self.receipt_path, self.receipt)

    @staticmethod
    def _write(path: Path, value: dict) -> None:
        path.write_text(json.dumps(value) + "\n", encoding="utf-8")

    @staticmethod
    def _identity(path: Path) -> dict:
        return {"path": str(path), "bytes": path.stat().st_size, "sha256": file_sha256(path)}

    def _row(self, particle_id: int) -> dict:
        velocity = [50.0, 100.0, -37800.0]
        time = 7500.5 + particle_id / 100
        return {
            "particle_id": particle_id, "parent_particle_id": "", "generation": 0,
            "species_id": "ion_524_q1", "particle_weight": 1,
            "source_component_id": self.recipe["connections"][0]["upstream"]["instance_id"],
            "target_component_id": self.recipe["connections"][0]["downstream"]["instance_id"], "state_event": "extraction_exit",
            "frame_id": "ip_frame.v2", "clock_epoch_id": "ion_processor_epoch_zero_v1",
            "instrument_time_us": time, "lineage_age_us": time, "particle_age_us": time,
            "last_component_elapsed_time_us": time, "lineage_birth_time_us": 0,
            "particle_birth_time_us": 0, "mass_to_charge_Th": 524, "mass_amu": 524, "charge_state": 1,
            "position_x_mm": 0.02, "position_y_mm": 170.1, "position_z_mm": -0.01,
            "velocity_x_m_s": velocity[0], "velocity_y_m_s": velocity[1], "velocity_z_m_s": velocity[2],
            "kinetic_energy_eV": kinetic_energy_ev(524, *velocity),
            "phase_reference_id": "source_rf.v1", "phase_rad": 1.25,
        }

    def rename_instances(self, source_id="processor_a", target_id="analyzer_b") -> None:
        for instance, name in zip(self.recipe["instances"], (source_id, target_id)):
            instance["instance_id"] = name
        edge = self.recipe["connections"][0]
        edge["upstream"]["instance_id"], edge["downstream"]["instance_id"] = source_id, target_id
        self.receipt.update(source_instance_id=source_id, target_instance_id=target_id)
        for row in self.rows:
            row.update(source_component_id=source_id, target_component_id=target_id)
        write_component_particle_state_csv(self.source, self.rows)
        self.receipt["outputs"]["component_states"] = self._identity(self.source)
        self._write(self.recipe_path, self.recipe)
        self._write(self.receipt_path, self.receipt)

    def test_whole_parent_motion_preserves_measured_states_mother_and_clock(self):
        self._prepare()
        expected = {name: (self.output / name).read_bytes() for name in ("component_particle_state.csv", "source_census.csv")}
        original_recipe = copy.deepcopy(self.recipe)
        original_source = self.source.read_bytes()
        original_census = self.census.read_bytes()
        for index, rotation in enumerate(([[1,0,0],[0,1,0],[0,0,1]], [[0,-1,0],[1,0,0],[0,0,1]])):
            self.recipe = copy.deepcopy(original_recipe)
            movement = RigidTransform.from_contract(dict(schema_version=1, role="rigid_transform",
                from_frame_id=self.recipe["assembly_frame_id"], to_frame_id="instrument.assembly",
                rotation=rotation, translation_mm=[32,-16,8]))
            self.recipe["assembly_frame_id"] = movement.to_frame_id
            for item in self.recipe["instances"]:
                item["transform"] = RigidTransform.from_contract(item["transform"]).then(movement).to_contract()
            self.output = self.root / f"moved_{index}"
            self._prepare()
            for name, content in expected.items():
                self.assertEqual((self.output / name).read_bytes(), content)
            self.assertEqual(self.source.read_bytes(), original_source)
            self.assertEqual(self.census.read_bytes(), original_census)

    def test_wrong_local_mr_frame_is_rejected_before_handoff_output(self):
        self.recipe["instances"][1]["transform"]["from_frame_id"] = "another.mr.local"
        with self.assertRaisesRegex(ValueError, "MR local source frame"):
            self._prepare()
        self.assertFalse(self.output.exists())

    def test_matching_reads_canonical_states_once(self) -> None:
        open_file, reads = Path.open, []

        def track(path, *args, **kwargs):
            if path == self.source and (not args or args[0] == "r"):
                reads.append(path)
            return open_file(path, *args, **kwargs)

        with patch.object(Path, "open", track):
            self._prepare()
        self.assertEqual(len(reads), 1)

    def test_renamed_instances_preserve_the_same_state_and_pose(self) -> None:
        self.rename_instances()
        report = self._prepare()
        self.assertEqual(report["schema_version"], 3)
        self.assertEqual(report["connection"], self.recipe["connections"][0])
        with (self.output / "component_particle_state.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual({row["source_component_id"] for row in rows}, {"processor_a"})
        self.assertEqual({row["target_component_id"] for row in rows}, {"analyzer_b"})
        self.assertAlmostEqual(float(rows[0]["position_y_mm"]), -54.9)
        self.assertEqual([int(row["particle_id"]) for row in rows], [1, 7])

    def test_wrong_connection_or_row_identity_has_no_output(self) -> None:
        import copy
        original = copy.deepcopy(self.recipe)
        for scenario in ("source", "target", "provider", "port", "coupling", "duplicate"):
            with self.subTest(scenario=scenario):
                self.recipe = copy.deepcopy(original)
                edge = self.recipe["connections"][0]
                if scenario == "source":
                    edge["upstream"]["instance_id"] = "absent"
                elif scenario == "target":
                    edge["downstream"]["instance_id"] = edge["upstream"]["instance_id"]
                elif scenario == "provider":
                    self.recipe["instances"][0]["project_id"] = "orthogonal_accelerator"
                elif scenario == "port":
                    edge["upstream"]["port_id"] = "guide_inlet"
                elif scenario == "coupling":
                    edge["coupling_mode"] = "state_handoff"
                else:
                    self.recipe["instances"][1]["instance_id"] = self.recipe["instances"][0]["instance_id"]
                with self.assertRaises((ValueError, KeyError)):
                    self._prepare()
                self.assertFalse(self.output.exists())
        self.recipe = original
        self.rows[0]["source_component_id"] = "another_processor"
        write_component_particle_state_csv(self.source, self.rows)
        self.receipt["outputs"]["component_states"] = self._identity(self.source)
        self._write(self.receipt_path, self.receipt)
        with self.assertRaisesRegex(ValueError, "instances differ"):
            self._prepare()
        self.assertFalse(self.output.exists())

    def test_old_or_missing_component_binding_is_explicitly_unsupported(self) -> None:
        for scenario in ("version", "source", "target", "provider"):
            with self.subTest(scenario=scenario):
                receipt = dict(self.receipt)
                if scenario == "version":
                    receipt["schema_version"] = 1
                elif scenario == "provider":
                    receipt["source_project"] = "orthogonal_accelerator"
                else:
                    receipt.pop(scenario + "_instance_id")
                self._write(self.receipt_path, receipt)
                with self.assertRaisesRegex(ValueError, "Unsupported.*binding"):
                    self._prepare()
                self.assertFalse(self.output.exists())

    def _prepare(self, output=None) -> dict:
        parent = handoff_plan(self.recipe)
        self._write(self.recipe_path, parent)
        plan = derive_assembly_scope(parent, local_scope=json.loads(self.request.read_text()).get('local_scope'))
        matching = resolve_matching_request(self.receipt_path, self.trajectory, self.provider, self.request, self.recipe_path,
            composition_plan=plan, connection=resolve_ip_mr_connection(plan))
        return prepare_handoff(matching, plan, output or self.output)

    def test_growing_parent_preserves_selected_handoff_states_and_complete_census(self):
        request = json.loads(self.request.read_text())
        request['local_scope'] = dict(instance_ids=['ip_exit_shield', 'mr_entry_frame'],
            research_scope='IP/MR state handoff', boundary_assumptions='Explicitly exclude additional upstream devices')
        self._write(self.request, request)
        reference = None
        for count in (2, 3, 4):
            if count > 2:
                instance = copy.deepcopy(self.recipe['instances'][0])
                instance['instance_id'] = f'extra_{count}'
                instance['transform']['translation_mm'][1] -= 1000 * count
                self.recipe['instances'].append(instance)
            output = self.root / f'prepared_{count}'
            self._prepare(output)
            actual = tuple((output/name).read_bytes() for name in ('component_particle_state.csv', 'source_census.csv'))
            if reference is None:
                reference = actual
            self.assertEqual(actual, reference)

    def test_preserves_full_state_clock_identity_and_complete_census(self) -> None:
        report = self._prepare()
        self.assertFalse(report["solver_execution"])
        self.assertEqual(report["counts"]["source"], 3)
        self.assertEqual((self.output / "source_census.csv").read_bytes(), self.census.read_bytes())
        with (self.output / "component_particle_state.csv").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([int(row["particle_id"]) for row in rows], [1, 7])
        self.assertAlmostEqual(float(rows[0]["position_y_mm"]), -54.9)
        for original, row in zip(self.rows, rows):
            for field in ("instrument_time_us", "kinetic_energy_eV", "phase_rad", "velocity_x_m_s", "velocity_y_m_s", "velocity_z_m_s"):
                self.assertEqual(float(row[field]), original[field])
            self.assertEqual(row["clock_epoch_id"], original["clock_epoch_id"])
            self.assertEqual(row["frame_id"], "mr_frame.v2")
        resolved = json.loads((self.output / "matching_request_resolved.json").read_text())
        self.assertEqual(resolved["target"]["axial_energy_per_charge_v"], 4372.010347796)
        self.assertEqual(resolved["target"]["anchor_y_mm"], -55)
        self.assertEqual(resolved["mirror_nominal_energy_reference"]["net_gain_reference_center_per_charge_v"], 4000)
        self.assertFalse(resolved["old_oa_field_valid_for_replacement"])

    def test_rejects_source_tampering_before_output_creation(self) -> None:
        self.source.write_text(self.source.read_text() + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self._prepare()
        self.assertFalse(self.output.exists())

    def test_preserve_workpoint_policy_survives_resolution_without_changing_target(self) -> None:
        request = json.loads(self.request.read_text())
        request["policies"]["energy_adjustment"] = "preserve_measured_workpoint"
        self._write(self.request, request)
        self._prepare()
        resolved = json.loads((self.output / "matching_request_resolved.json").read_text())
        self.assertEqual(resolved["policies"], request["policies"])
        self.assertEqual(resolved["target"]["axial_energy_per_charge_v"], 4372.010347796)

    def test_rejects_unknown_energy_adjustment_policy(self) -> None:
        request = json.loads(self.request.read_text())
        request["policies"]["energy_adjustment"] = "unknown"
        self._write(self.request, request)
        with self.assertRaises(ValidationError):
            self._prepare()
        self.assertFalse(self.output.exists())

    def test_rejects_opposite_direction(self) -> None:
        self.rows[0]["velocity_z_m_s"] *= -1
        write_component_particle_state_csv(self.source, self.rows)
        self.receipt["outputs"]["component_states"] = self._identity(self.source)
        self._write(self.receipt_path, self.receipt)
        with self.assertRaisesRegex(ValueError, "negative z"):
            self._prepare()

    def test_rejects_incomplete_mother_identity(self) -> None:
        self.receipt["lost_particle_ids"] = [8]
        self._write(self.receipt_path, self.receipt)
        with self.assertRaisesRegex(ValueError, "do not close"):
            self._prepare()

    def test_refuses_overwrite(self) -> None:
        self._prepare()
        with self.assertRaisesRegex(ValueError, "overwrite"):
            self._prepare()

    def test_observation_center_does_not_move_the_explicit_pose(self):
        self.receipt["observation_surface"]["center_mm"] = [17, 900, -31]
        self._write(self.receipt_path, self.receipt)
        report = self._prepare()
        self.assertEqual(report["rigid_transform"]["translation_mm"], [0, -225, 0])

    def test_complete_velocity_representation_is_rotated_once(self):
        model = json.loads(self.model.read_text())
        # A different producer representation, with the same native extraction direction.
        model["coordinate_transform"]["rotation"] = [[0,0,1],[-1,0,0],[0,-1,0]]
        self._write(self.model, model)
        self.receipt["inputs"]["inputs/resolved_model.json"] = self._identity(self.model)
        self._write(self.receipt_path, self.receipt)
        self._prepare()
        with (self.output / "component_particle_state.csv").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([float(rows[0][f"velocity_{a}_m_s"]) for a in "xyz"], [-50,-100,-37800])
        self.assertEqual([float(rows[0][f"position_{a}_mm"]) for a in "xy"], [-.02,-395.1])

    def test_old_schema_and_wrong_provider_frame_fail_before_output(self):
        request = json.loads(self.request.read_text())
        request["schema_version"] = 1
        self._write(self.request, request)
        with self.assertRaises(ValidationError):
            self._prepare()
        request["schema_version"] = 3
        self._write(self.request, request)
        model = json.loads(self.model.read_text())
        model["coordinate_transform"]["to_frame_id"] = "wrong.frame"
        self._write(self.model, model)
        self.receipt["inputs"]["inputs/resolved_model.json"] = self._identity(self.model)
        self._write(self.receipt_path, self.receipt)
        with self.assertRaisesRegex(ValueError, "exported state frame"):
            self._prepare()
        self.assertFalse(self.output.exists())

    def test_request_cannot_authorize_execution(self) -> None:
        request = json.loads(self.request.read_text())
        request["policies"]["execution"] = "run"
        self._write(self.request, request)
        with self.assertRaises(ValidationError):
            self._prepare()
