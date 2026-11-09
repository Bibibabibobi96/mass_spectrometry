"""Pure independent-work counts and contiguous ordinal transport intervals.

These existing integer projections neither load resource policy nor admit work.
"""
from __future__ import annotations

def _balanced_lane_loads(total: int, lane_count: int) -> list[int]:
    """Split positive independent-particle work as evenly as possible."""
    if total < 0 or lane_count < 1:
        raise ValueError("balanced lane inputs are invalid")
    quotient, remainder = divmod(total, lane_count)
    return [quotient + (1 if index < remainder else 0) for index in range(lane_count)]


def _batches_from_counts(
    counts: list[int], first_count: int = 0, unit: str = "particles"
) -> list[dict[str, int]]:
    """Publish contiguous canonical particle or work-item ranges."""
    batches: list[dict[str, int]] = []
    next_particle_id = first_count + 1
    range_prefix = "particle" if unit == "particles" else "work_item"
    for index, count in enumerate(counts, start=1):
        batches.append({
            "index": index,
            "count": count,
            f"{range_prefix}_id_min": next_particle_id,
            f"{range_prefix}_id_max": next_particle_id + count - 1,
            **({"simion_particle_id_offset": next_particle_id - 1}
               if unit == "particles" else {}),
        })
        next_particle_id += count
    return batches
