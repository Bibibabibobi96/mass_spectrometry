from __future__ import annotations

import copy
import csv
import json
import tempfile
from pathlib import Path
import unittest

from common.contracts.machine_contracts import ContractError
from projects.rf_multipole_ion_optics.core.component_port import (build_exit_component_port, build_assembly_interface, prepare_exit_observation_inputs, validate_exit_observations)
from projects.rf_multipole_ion_optics.core.interface_geometry import through_entrance_geometry, through_shield_geometry
from common.contracts.particle_state import PARTICLE_STATE_COLUMNS
from projects.rf_multipole_ion_optics.tests.domain.test_compile_design_request import design_request, identity
from projects.rf_multipole_ion_optics.core.compile_design_request import compile_design_request
from projects.rf_multipole_ion_optics.simion.simion_geometry import physical_electrode_view, render_physical_gem


class MultipoleComponentPortTests(unittest.TestCase):
    def test_complete_native_namespace_for_each_through_provider_and_rod_topology(self):
        for variant in ('quadrupole', 'hexapole', 'octupole'):
            for model in ('cylindrical_grounded_shield_through_exit_v1',
                          'cylindrical_grounded_shield_through_entrance_exit_v1'):
                for segmented in (False, True):
                    with self.subTest(variant=variant, model=model, segmented=segmented):
                        segmentation = dict(strategy='uniform',segment_count=4,intersegment_gap_mm=.5,
                            entrance_common_mode_V=0.,exit_common_mode_V=-3.,output_reference_V=-3.) if segmented else None
                        request = design_request("octupole",segmentation=segmentation)
                        request['identity'] = identity(variant)
                        request['geometry_mm']['enclosure'].update(model=model,vacuum_z_max_mm=90.)
                        request['geometry_mm']['exit_interface']['connector_length_mm'] = 0.
                        resolved = compile_design_request(request,expected_identity=request['identity'])
                        original = copy.deepcopy(resolved)
                        body = render_physical_gem(resolved,.1)
                        interface = build_assembly_interface(resolved,geometry_profile_id='through_provider')
                        electrodes = interface['component_electrodes']
                        self.assertEqual(electrodes,[dict(component_electrode_id=row['native_electrode_id'],
                            role=row['scientific_id']) for row in physical_electrode_view(resolved)])
                        self.assertEqual(len(electrodes),10 if segmented else 3)
                        self.assertEqual(len({row['component_electrode_id'] for row in electrodes}),len(electrodes))
                        self.assertTrue(all(set(row)=={'component_electrode_id','role'} for row in electrodes))
                        self.assertEqual(resolved,original)
                        self.assertEqual(render_physical_gem(resolved,.1),body)

    def test_instances_keep_provider_native_ids_without_copying_independent_drives(self):
        interfaces, providers = [], []
        for frequency, phase in ((1.1e6,0.),(1.21e6,1.5707963267948966)):
            request = design_request("octupole")
            request['geometry_mm']['enclosure'].update(model='cylindrical_grounded_shield_through_exit_v1',vacuum_z_max_mm=90.)
            request['geometry_mm']['exit_interface']['connector_length_mm'] = 0.
            request['drive'].update(frequency_Hz=frequency,phase_rad=phase)
            provider = compile_design_request(request,expected_identity=request['identity'])
            providers.append(provider)
            interfaces.append(build_assembly_interface(provider,geometry_profile_id='through_provider'))
        self.assertEqual(interfaces[0],interfaces[1])
        self.assertNotEqual(providers[0]['drive'],providers[1]['drive'])
        self.assertEqual([row['component_electrode_id'] for row in interfaces[0]['component_electrodes']],[1,2,3])

    def through_design(self):
        request = design_request("octupole")
        request["geometry_mm"]["enclosure"].update(model="cylindrical_grounded_shield_through_exit_v1", vacuum_z_max_mm=90.)
        request["geometry_mm"]["exit_interface"]["connector_length_mm"] = 0.
        return compile_design_request(request, expected_identity=request["identity"])

    def through_entrance_exit_design(self):
        request = design_request("octupole")
        request["geometry_mm"]["enclosure"].update(
            model="cylindrical_grounded_shield_through_entrance_exit_v1",
            vacuum_z_max_mm=90.,
        )
        request["geometry_mm"]["exit_interface"]["connector_length_mm"] = 0.
        return compile_design_request(request, expected_identity=request["identity"])

    def test_real_exit_is_distinct_from_historical_handoff_and_closed_is_rejected(self):
        resolved = self.through_design()
        interface = build_assembly_interface(resolved, geometry_profile_id="through_exit")
        real = interface["ports"]["mechanical_exit"]
        self.assertEqual(interface["local_frame_id"], resolved["coordinate"]["coordinate_id"])
        self.assertEqual(real["center_mm"], [0., 0., 89.])
        self.assertEqual(real["cross_section"], dict(shape="circle", radius_mm=resolved["interfaces_mm"]["exit"]["aperture_radius_mm"]))
        request = design_request("octupole")
        closed = compile_design_request(request, expected_identity=request["identity"])
        with self.assertRaisesRegex(ContractError, "explicit through-exit"):
            build_assembly_interface(closed, geometry_profile_id="closed")

    def test_explicit_dual_through_model_publishes_both_outer_faces(self):
        old = build_assembly_interface(
            self.through_design(), geometry_profile_id="through_exit"
        )
        resolved = self.through_entrance_exit_design()
        interface = build_assembly_interface(
            resolved, geometry_profile_id="through_entrance_exit"
        )
        self.assertEqual(interface["variant_id"], "cylindrical_through_entrance_exit")
        self.assertEqual(interface["ports"]["mechanical_exit"], old["ports"]["mechanical_exit"])
        entrance = interface["ports"]["mechanical_entrance"]
        self.assertEqual(entrance["outward_normal"], [0, 0, -1])
        self.assertEqual(
            entrance["center_mm"],
            [0., 0., resolved["geometry_mm"]["enclosure"]
             ["entrance_outer_endcap_upstream_face_z_mm"]],
        )
        self.assertEqual(
            entrance["cross_section"],
            dict(shape="circle", radius_mm=resolved["interfaces_mm"]["entrance"]["aperture_radius_mm"]),
        )
        self.assertNotIn("mechanical_entrance", old["ports"])
        with self.assertRaisesRegex(ContractError, "through-entrance-exit"):
            through_entrance_geometry(self.through_design())

    def test_dual_through_side_shell_uses_outer_endcaps_not_numerical_guard(self):
        old = self.through_design()
        dual = self.through_entrance_exit_design()
        dual["geometry_mm"]["enclosure"]["vacuum_z_min_mm"] = -100.
        dual["geometry_mm"]["enclosure"]["vacuum_z_max_mm"] = 200.
        self.assertEqual(
            through_shield_geometry(old),
            dict(z_min_mm=2., z_max_mm=89.),
        )
        self.assertEqual(
            through_shield_geometry(dual),
            dict(z_min_mm=2., z_max_mm=89.),
        )

    def test_clock_freeze_binds_original_epoch_not_first_particle_birth(self):
        from common.contracts.canonical_clock_authority import validate_clock_authority
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory); (run/"inputs").mkdir()
            result = prepare_exit_observation_inputs(run, self.through_design(), design_profile_id="through_exit", cell_z_mm=.3)
            self.assertEqual(result["mechanical_exit_z_mm"], 89.)
            self.assertEqual(result["numerical_guard_z_mm"], 89.3)
            self.assertEqual(json.loads((run/"inputs/instrument_epoch.json").read_text()), dict(instrument_time_us=0.))
            self.assertEqual(validate_clock_authority(run/"inputs/clock_authority.json", run)["clock_epoch_id"], "instrument_clock_epoch_v1")
            with self.assertRaisesRegex(ContractError, "overwrite"):
                prepare_exit_observation_inputs(run, self.through_design(), design_profile_id="through_exit", cell_z_mm=.3)

    def test_exit_observations_require_complete_mother_and_actual_plane(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root/"source.csv"; state = root/"states.csv"
            source.write_text("particle_id,birth_time_s\n1,0.000001\n2,0.000002\n")
            def event(particle, kind, time, axial):
                row = {key: 0. for key in PARTICLE_STATE_COLUMNS}
                row.update(particle_id=particle, event=kind, status="transmitted" if kind=="mechanical_exit" else "lost",
                    terminal_reason="none" if kind=="mechanical_exit" else "unknown", time_us=time,
                    elapsed_time_us=time-particle, axial_z_mm=axial, velocity_axial_m_s=1000.)
                return row
            rows = [event(1,"mechanical_exit_step_before",4.5,88.5), event(1,"mechanical_exit_step_after",5.5,89.5),
                    event(1,"mechanical_exit",5.,89.), event(1,"terminal",6.,89.3), event(2,"terminal",4.,20.)]
            def write():
                with state.open("w", newline="") as handle:
                    writer=csv.DictWriter(handle, fieldnames=PARTICLE_STATE_COLUMNS); writer.writeheader();writer.writerows(rows)
            write(); plan=dict(mechanical_exit_z_mm=89., aperture_radius_mm=1.)
            result=validate_exit_observations(state,source,plan)
            self.assertEqual((result["mother_count"],result["exit_particle_ids"],result["non_exit_particle_ids"]),(2,[1],[2]))
            from common.simion.particle_batching import merge_rebased_particle_csvs
            batches=[]
            for particle in (1, 2):
                batch=root/f"batch_{particle}.csv"
                with batch.open("w", newline="") as handle:
                    writer=csv.DictWriter(handle, fieldnames=PARTICLE_STATE_COLUMNS);writer.writeheader()
                    writer.writerows(dict(row, particle_id=1) for row in rows if row["particle_id"]==particle)
                batches.append((batch, particle-1))
            merged=root/"merged.csv"
            merge_rebased_particle_csvs(batches,merged)
            self.assertEqual(validate_exit_observations(merged,source,plan),result)
            rows.pop();write()
            with self.assertRaisesRegex(ContractError,"complete mother"):
                validate_exit_observations(state,source,plan)
            rows.append(event(2,"terminal",4.,20.));rows[2]["axial_z_mm"]=86.;write()
            with self.assertRaisesRegex(ContractError,"real plane"):
                validate_exit_observations(state,source,plan)
            rows[2]["axial_z_mm"]=89.; rows[2]["velocity_axial_m_s"]=500.;write()
            with self.assertRaisesRegex(ContractError,"native bracket interpolation"):
                validate_exit_observations(state,source,plan)
            rows[2]["velocity_axial_m_s"]=1000.; rows.pop(0); write()
            with self.assertRaisesRegex(ContractError,"actual native step bracket"):
                validate_exit_observations(state,source,plan)

    def test_builds_port_from_resolved_design(self) -> None:
        request = design_request()
        resolved = compile_design_request(request, expected_identity=request["identity"])
        port = build_exit_component_port(
            resolved,
            design_profile_id="quadrupole_no_acceleration_full_length",
            authority_path=(
                "artifacts/projects/rf_multipole_ion_optics/runs/"
                "20260803_000000__sim__simion__fixture/inputs/"
                "multipole_resolved_design.json"
            ),
            authority_sha256="A" * 64,
        )
        self.assertEqual(port["project_id"], "rf_multipole_ion_optics")
        self.assertEqual(
            port["mating_surface"]["center_mm"][2],
            resolved["interfaces_mm"]["exit"]["handoff_plane_z_mm"],
        )
        self.assertEqual(
            port["profile_scope"]["scope_id"], "quadrupole_no_acceleration_full_length"
        )

    def test_rejects_stale_resolved_design(self) -> None:
        request = design_request()
        resolved = compile_design_request(request, expected_identity=request["identity"])
        stale = copy.deepcopy(resolved)
        stale["interfaces_mm"]["exit"]["handoff_plane_z_mm"] += 1.0
        with self.assertRaisesRegex(ContractError, "hash is stale"):
            build_exit_component_port(
                stale,
                design_profile_id="quadrupole_no_acceleration_full_length",
                authority_path=(
                    "artifacts/projects/rf_multipole_ion_optics/runs/"
                    "20260803_000000__sim__simion__fixture/inputs/"
                    "multipole_resolved_design.json"
                ),
                authority_sha256="A" * 64,
            )


if __name__ == "__main__":
    unittest.main()
