"""Explicit ion registry for software-only particle-result fixtures."""
from msplatform.contracts.species import validate_species
from msplatform.contracts.particle_physics import AMU_KG, ELEMENTARY_CHARGE_C


def fixture_ion_species(rows):
    records = {}
    for row in rows:
        species = validate_species({"species_id": row["species_id"], "species_kind": "ion",
                                    "mass_kg": row["mass_kg"], "charge_state": row["charge_state"],
                                    "charge_c": row["charge_c"]})
        previous = records.setdefault(species["species_id"], species)
        if previous != species:
            raise ValueError("fixture repeats a species ID with different physical properties")
    return list(records.values())


def fixture_ion_species_from_amu(rows):
    return fixture_ion_species([{"species_id": row["species_id"],
        "mass_kg": row["mass_amu"] * AMU_KG, "charge_state": row["charge_state"],
        "charge_c": row["charge_state"] * ELEMENTARY_CHARGE_C} for row in rows])
