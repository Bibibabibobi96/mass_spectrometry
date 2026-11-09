"""Particle population cardinality without study qualification policy."""

def validate_positive_particle_count(count: int) -> int:
    """Return a physically usable trajectory count without imposing a study size."""
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("particle count must be a positive integer")
    return count
