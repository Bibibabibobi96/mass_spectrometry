"""Energy-per-charge projection for explicit field samples and particle states."""
from __future__ import annotations

from typing import Any, Mapping, Sequence


def sampled_event_energy(points: Sequence[Mapping[str, Any]], samples: Mapping[str, Mapping[str, float]]) -> tuple[list[dict], float]:
    """Calculate K/q + measured phi and differences from the first observation."""
    if not points or set(samples) != {point['sample_id'] for point in points}:
        raise ValueError('actual event field population does not close')
    ledger = [dict(point, **samples[point['sample_id']],
        k_over_q_plus_phi_v=point['kinetic_energy_per_charge_ev']+samples[point['sample_id']]['phi_v'])
        for point in points]
    baseline = ledger[0]['k_over_q_plus_phi_v']
    for row in ledger:
        row['delta_h_from_source_centroid_v'] = row['k_over_q_plus_phi_v']-baseline
    return ledger, baseline
