from __future__ import annotations
import copy
import csv
import json
import tempfile
from pathlib import Path
import unittest
from common.contracts.machine_contracts import ContractError
from common.contracts.particle_state import PARTICLE_STATE_COLUMNS
from projects.rf_multipole_ion_optics.core.component_port import (
    build_assembly_interface,
    prepare_exit_observation_inputs,
    validate_exit_observations,
)
from projects.rf_multipole_ion_optics.tests.domain.test_compile_design_request import design_request
from projects.rf_multipole_ion_optics.core.compile_design_request import compile_design_request
from projects.rf_multipole_ion_optics.simion.simion_geometry import physical_electrode_view


class MultipoleComponentPortTests(unittest.TestCase):
    def resolved(self, shell=False):
        request = design_request("octupole")
        if shell:
            request["geometry_mm"]["enclosure"] = dict(
                model="cylindrical_grounded_shell",
                inner_radius_mm=20.0,
                wall_thickness_mm=1.0,
                z_min_mm=2.0,
                z_max_mm=89.0,
                endcaps=dict(exit=dict(aperture_radius_mm=3.5, thickness_mm=0.5)),
            )
            request["static_electrodes_V"] = dict(role="grounded_shell_static_electrodes", ground_V=0.0)
        return compile_design_request(request, expected_identity=request["identity"])

    def test_bare_and_shell_publish_actual_surfaces_and_electrodes(self):
        for shell in (False, True):
            resolved = self.resolved(shell)
            port = build_assembly_interface(resolved, geometry_profile_id="current")
            self.assertEqual(port["ports"]["mechanical_exit"]["center_mm"], [0.0, 0.0, 89.0 if shell else 85.0])
            self.assertEqual(
                port["component_electrodes"],
                [
                    dict(component_electrode_id=x["native_electrode_id"], role=x["scientific_id"])
                    for x in physical_electrode_view(resolved)
                ],
            )
            self.assertEqual(
                port["ports"]["mechanical_exit"]["cross_section"]["shape"], "circle" if shell else "open_rod_envelope"
            )

    def test_clock_guard_and_no_artificial_bare_aperture(self):
        from common.contracts.canonical_clock_authority import validate_clock_authority

        for shell in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                run = Path(directory)
                (run / "inputs").mkdir()
                plan = prepare_exit_observation_inputs(
                    run, self.resolved(shell), design_profile_id="current", cell_z_mm=0.3
                )
                self.assertEqual(plan["aperture_radius_mm"], 3.5 if shell else None)
                self.assertEqual(plan["mechanical_exit_z_mm"], 89.0 if shell else 85.0)
                self.assertAlmostEqual(plan["numerical_guard_z_mm"], 89.3 if shell else 87.3)
                self.assertEqual(
                    validate_clock_authority(run / "inputs/clock_authority.json", run)["clock_epoch_id"],
                    "instrument_clock_epoch_v1",
                )
                self.assertEqual(
                    json.loads((run / "inputs/instrument_epoch.json").read_text()), dict(instrument_time_us=0.0)
                )
                with self.assertRaisesRegex(ContractError, "overwrite"):
                    prepare_exit_observation_inputs(
                        run, self.resolved(shell), design_profile_id="current", cell_z_mm=0.3
                    )

    def test_stale_identity_is_rejected(self):
        resolved = copy.deepcopy(self.resolved())
        resolved["geometry_mm"]["observations"]["handoff_plane_z_mm"] += 0.1
        with self.assertRaisesRegex(ContractError, "hash is stale"):
            build_assembly_interface(resolved, geometry_profile_id="current")

    def test_exit_observations_require_complete_mother_and_actual_plane(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            state = root / "states.csv"
            source.write_text("particle_id,birth_time_s\n1,0.000001\n2,0.000002\n")

            def event(particle, kind, time, axial):
                row = {key: 0.0 for key in PARTICLE_STATE_COLUMNS}
                row.update(
                    particle_id=particle,
                    event=kind,
                    status="transmitted" if kind == "mechanical_exit" else "lost",
                    terminal_reason="none" if kind == "mechanical_exit" else "unknown",
                    time_us=time,
                    elapsed_time_us=time - particle,
                    axial_z_mm=axial,
                    velocity_axial_m_s=1000.0,
                )
                return row

            rows = [
                event(1, "mechanical_exit_step_before", 4.5, 88.5),
                event(1, "mechanical_exit_step_after", 5.5, 89.5),
                event(1, "mechanical_exit", 5.0, 89.0),
                event(1, "terminal", 6.0, 89.3),
                event(2, "terminal", 4.0, 20.0),
            ]

            def write():
                with state.open("w", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=PARTICLE_STATE_COLUMNS)
                    writer.writeheader()
                    writer.writerows(rows)

            write()
            plan = dict(mechanical_exit_z_mm=89.0, aperture_radius_mm=1.0)
            result = validate_exit_observations(state, source, plan)
            self.assertEqual(
                (result["mother_count"], result["exit_particle_ids"], result["non_exit_particle_ids"]), (2, [1], [2])
            )
            for row in rows:
                row["transverse_x_mm"] = 9.0
            write()
            with self.assertRaisesRegex(ContractError, "physical bore"):
                validate_exit_observations(state, source, plan)
            bare_plan = dict(plan, aperture_radius_mm=None)
            self.assertEqual(validate_exit_observations(state, source, bare_plan), result)
            for row in rows:
                row["transverse_x_mm"] = 0.0
            write()
            from common.simion.particle_batching import merge_rebased_particle_csvs

            batches = []
            for particle in (1, 2):
                batch = root / f"batch_{particle}.csv"
                with batch.open("w", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=PARTICLE_STATE_COLUMNS)
                    writer.writeheader()
                    writer.writerows(dict(row, particle_id=1) for row in rows if row["particle_id"] == particle)
                batches.append((batch, particle - 1))
            merged = root / "merged.csv"
            merge_rebased_particle_csvs(batches, merged)
            self.assertEqual(validate_exit_observations(merged, source, plan), result)
            rows.pop()
            write()
            with self.assertRaisesRegex(ContractError, "complete mother"):
                validate_exit_observations(state, source, plan)
            rows.append(event(2, "terminal", 4.0, 20.0))
            rows[2]["axial_z_mm"] = 86.0
            write()
            with self.assertRaisesRegex(ContractError, "real plane"):
                validate_exit_observations(state, source, plan)
            rows[2]["axial_z_mm"] = 89.0
            rows[2]["velocity_axial_m_s"] = 500.0
            write()
            with self.assertRaisesRegex(ContractError, "native bracket interpolation"):
                validate_exit_observations(state, source, plan)
            rows[2]["velocity_axial_m_s"] = 1000.0
            rows.pop(0)
            write()
            with self.assertRaisesRegex(ContractError, "actual native step bracket"):
                validate_exit_observations(state, source, plan)


if __name__ == "__main__":
    unittest.main()
