"""Actual dual-cone callback evidence mapped to canonical SI, without Fly."""
import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from msplatform.backends.simion.dual_cone_particle_data import adapt_dual_cone_results
from msplatform.contracts.particle_physics import CONSTANTS
from msplatform.contracts.species import validate_species
from msplatform.results.particle_data import read_particle_data, write_particle_data


class DualConeParticleDataTests(unittest.TestCase):
    def test_inert_owner_writes_canonical_publication_from_actual_callback_rows(self):
        from msplatform.backends.simion.dual_cone_transport import source_placement
        from msplatform.backends.simion.dual_cone_transport_execution import _fly_and_collect_transport
        from msplatform.backends.simion.source import transform_source_rows

        config = Path(__file__).resolve().parents[2] / "src/msplatform/components/dual_cone_tandem_quadrupole/config"
        load = lambda name: json.loads((config / name).read_text(encoding="utf-8"))
        values = dict(resolved=load("resolved_geometry.json"), numerics=load("simion_solver_numerics.json"),
                      source_spec=load("cylindrical_particle_source.json"))
        species = validate_species(dict(species_id="ion", species_kind="ion", mass_kg=500 * CONSTANTS["atomic_mass_constant_kg"],
                                        charge_state=1, charge_c=CONSTANTS["elementary_charge_c"]))
        row = dict(particle_id=7, birth_time_s=0., x_mm=0., y_mm=0., z_mm=-1., vx_m_s=0., vy_m_s=0.,
                   vz_m_s=1., mass_amu=500., charge_state=1)
        world, _ = source_placement(values["resolved"], values["numerics"], values["source_spec"])
        projected = transform_source_rows([row], world)[0]
        coords = {axis + "_mm": float(projected["position_" + axis + "_mm"]) for axis in "xyz"}
        coords.update({"v" + axis + "_mm_per_us": float(projected["velocity_" + axis + "_m_s"]) / 1000 for axis in "xyz"})
        facts = dict(status="recorded_v1", particle_evidence=[dict(particle_id=7, raw=dict(status="recorded_v1", records=[
            dict(event="initialize", raw_tof_us=0., **coords), dict(event="terminate", raw_tof_us=2., **coords)]))])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepared = root / "prepared"
            (prepared / "input").mkdir(parents=True)
            (prepared / "results").mkdir()
            with (prepared / "input/cylindrical_particle_source.csv").open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(row))
                writer.writeheader()
                writer.writerow(row)
            class Session:
                result_dir = root / "result"
                context = type("Context", (), {"tools": {"simion": root / "inert-simion.exe"}})()
                def declare_file(self, path, role):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    return path
                def canonical_path(self, path):
                    return Path(path)
            session = Session()
            audit = root / "audit"
            audit.write_text("inert", encoding="utf-8")
            def inert_track(*args, **kwargs):
                final = dict(ion_number=7, time_us=2., splat=2, **coords)
                for path, rows in ((kwargs["final_state"], [final]),
                                   (prepared / "results/trajectory_samples.csv", [dict(ion_number=7, time_us=1., **coords)])):
                    with path.open("w", newline="", encoding="utf-8") as stream:
                        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                        writer.writeheader()
                        writer.writerows(rows)
                return {"terminal_evidence": facts}, []
            with patch("msplatform.backends.simion.dual_cone_transport_execution.track_transport", inert_track), \
                    patch("msplatform.execution.executable_identity.windows_binary_version", return_value="inert"):
                result = _fly_and_collect_transport(session, prepared=prepared, records={"preparation_receipt": {}},
                    plan={"source_count": 1}, values=values, iob=root / "x.iob", native_guards=[], solver=root,
                    audit=audit, limits={}, canonical_result=dict(species=species,
                        frame_id=world.to_frame_id, clock={"clock_epoch_id": "inert"}))
            self.assertIn("particle_data_execution_json", result["manifest_extra_fields"]["products"]["trajectory"]["data"])
            self.assertEqual(read_particle_data(session.result_dir / "particle_data")["initial_states"][0]["particle_id"], 7)

    def test_callback_si_coldread_and_missing_or_forged_rejection(self):
        species = validate_species(dict(species_id="ion", species_kind="ion", mass_kg=500 * CONSTANTS["atomic_mass_constant_kg"],
                       charge_state=1, charge_c=CONSTANTS["elementary_charge_c"]))
        coords = dict(x_mm=1., y_mm=2., z_mm=3., vx_mm_per_us=.1, vy_mm_per_us=.2, vz_mm_per_us=.3)
        source = [dict(particle_id=7, birth_time_s=0., mass_amu=500., charge_state=1, **coords)]
        final = [dict(ion_number=7, time_us=2., splat=2, **coords)]
        samples = [dict(ion_number=7, time_us=1., **coords)]
        evidence = dict(status="recorded_v1", particle_evidence=[dict(particle_id=7, raw=dict(
            status="recorded_v1", records=[dict(event="initialize", raw_tof_us=0., **coords),
                                         dict(event="terminate", raw_tof_us=2., **coords)]))])
        result = adapt_dual_cone_results(source, final, samples, evidence, species=species, backend_version="inert")
        self.assertEqual(result.initial_states[0]["position_m"], [.001, .002, .003])
        self.assertEqual(result.initial_states[0]["velocity_m_s"], [100., 200., 300.])
        self.assertEqual(result.terminal_states[0]["stop_reason"], "time_limit")
        with tempfile.TemporaryDirectory() as directory:
            metadata = dict(schema_version=2, initial_state_basis="native_birth_verified", frame_id="workbench",
                            clock={"clock_epoch_id": "test"}, species=[species])
            write_particle_data(Path(directory), result, metadata=metadata)
            self.assertEqual(read_particle_data(Path(directory))["initial_states"][0]["particle_id"], 7)
        bad = copy.deepcopy(evidence)
        bad["particle_evidence"][0]["raw"]["records"][0]["x_mm"] = 9.
        with self.assertRaisesRegex(ValueError, "initialize"):
            adapt_dual_cone_results(source, final, samples, bad, species=species, backend_version="inert")
        with self.assertRaises(ValueError):
            adapt_dual_cone_results(source, final, samples, {"status": "recorded_v1", "particle_evidence": []},
                                    species=species, backend_version="inert")
        lost = copy.deepcopy(final)
        lost[0]["splat"] = 3
        with self.assertRaisesRegex(ValueError, "support was lost"):
            adapt_dual_cone_results(source, lost, samples, evidence, species=species, backend_version="inert")
        outside = copy.deepcopy(samples)
        outside[0]["time_us"] = 3.
        with self.assertRaisesRegex(ValueError, "lifetime"):
            adapt_dual_cone_results(source, final, outside, evidence, species=species, backend_version="inert")


if __name__ == "__main__":
    unittest.main()
