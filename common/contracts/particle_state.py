"""One-way compatibility exports for the deployed RF event-table protocol.

RF/IP event consumers and frozen CLI inventories migrate to their named RF
protocol/source adapter; remove this compatibility surface by P4. Neutral
transfer states are msplatform.contracts.particle_state, a different contract.
"""
from projects.rf_multipole_ion_optics.analysis.rf_event_table_validation import (
    PARTICLE_STATE_COLUMNS as PARTICLE_STATE_COLUMNS,
    ENUMS as ENUMS,
    validate_rf_event_table as validate_particle_state,
    main as main,
)
from projects.rf_multipole_ion_optics.simion.ion11_source_adapter import (
    AMU_KG as AMU_KG, E_CHARGE_C as E_CHARGE_C, kinetic_energy_ev as kinetic_energy_ev,
    read_ion11_source_states as ion11_sources,
    read_canonical_rf_source_expectations as canonical_sources,
)

__all__ = [
    "PARTICLE_STATE_COLUMNS", "ENUMS", "validate_particle_state", "main",
    "AMU_KG", "E_CHARGE_C", "kinetic_energy_ev", "ion11_sources", "canonical_sources",
]

if __name__ == "__main__":
    main()
