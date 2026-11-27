"""Three charged particle kinds through the public reference and cold reader."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from msplatform.physics import CONSTANTS, ELECTRON_CONSTANTS
from msplatform.recipes import load_recipe
from msplatform.results.particle_data import read_particle_data
from msplatform.storage import ArtifactStore
from msplatform.workflows.tracing import run_recipe


class ReferenceSpeciesTests(unittest.TestCase):
    def test_three_species_independent_uniform_e_oracle_and_cold_read(self):
        original = Path("recipes/reference/uniform_e.toml").read_text(encoding="utf-8")
        replacement = f'''[[species]]
species_id = "positive_ion"
species_kind = "ion"
mass_u = 100.0
charge_state = 1

[[species]]
species_id = "negative_ion"
species_kind = "ion"
mass_u = 100.0
charge_state = -1

[[species]]
species_id = "electron"
species_kind = "electron"
mass_kg = {ELECTRON_CONSTANTS["mass_kg"]!r}
charge_state = -1

'''
        start = original.index("[[species]]")
        end = original.index("[numerics]")
        particles = "".join(f'''[[initial_states]]
particle_id = {pid}
species_id = "{name}"
position_m = [0.0, 0.0, 0.0]
velocity_m_s = [0.0, 0.0, 0.0]
time_s = 0.0
weight = {weight}

''' for pid, name, weight in ((1, "positive_ion", 2.0), (2, "negative_ion", 0.5), (3, "electron", 4.0)))
        text = original[:start] + replacement + particles + original[end:]
        text = text.replace("[2000.0, 0.0, 0.0]", "[1.0, 0.0, 0.0]")
        text = text.replace("end_time_s = 0.000001", "end_time_s = 1e-9")
        text = text.replace("max_step_s = 1e-8", "max_step_s = 1e-10")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recipe = root / "three.toml"
            recipe.write_text(text, encoding="utf-8")
            resolved = load_recipe(recipe).to_dict()
            output = run_recipe(recipe, artifact_root=root / "store")
            data = read_particle_data(ArtifactStore(root / "store").inspect_run(output["run_id"]))
            self.assertEqual(data["metadata"]["species"], resolved["species"])
            self.assertEqual([row["weight"] for row in data["initial_states"]], [2.0, 0.5, 4.0])
            self.assertEqual([row["species_kind"] for row in data["metadata"]["species"]], ["ion", "ion", "electron"])
            for initial, terminal in zip(data["initial_states"], data["terminal_states"], strict=True):
                t = terminal["time_s"]
                acceleration = initial["charge_state"] * CONSTANTS["elementary_charge_c"] / initial["mass_kg"]
                np.testing.assert_allclose(terminal["velocity_m_s"], [acceleration * t, 0., 0.], rtol=1e-10, atol=1e-10)
                np.testing.assert_allclose(terminal["position_m"], [0.5 * acceleration * t * t, 0., 0.], rtol=1e-10, atol=1e-16)
            self.assertEqual(data["initial_states"][2]["mass_kg"], ELECTRON_CONSTANTS["mass_kg"])

    def test_electron_identity_is_not_inferred_from_negative_charge(self):
        from msplatform.contracts.species import validate_species
        base = {"species_id": "electron", "species_kind": "electron", "mass_kg": ELECTRON_CONSTANTS["mass_kg"],
                "charge_state": -1, "charge_c": -CONSTANTS["elementary_charge_c"]}
        validate_species(base)
        for bad in ({**base, "charge_state": -2, "charge_c": -2 * CONSTANTS["elementary_charge_c"]},
                    {**base, "mass_kg": 100 * CONSTANTS["atomic_mass_constant_kg"]},
                    {key: value for key, value in base.items() if key != "species_kind"}):
            with self.assertRaises(ValueError):
                validate_species(bad)
