"""Stable public API and CLI for canonical oa-TOF reference analysis."""

from __future__ import annotations

from projects.oa_tof.analysis.reference_analysis_core import (
    DEFAULT_DETECTOR_CENTER_X_MM,
    DEFAULT_DETECTOR_CENTER_Y_MM,
    analyze_comparison,
    analyze_simion_recording,
    analyze_single,
    audit_simion_recording,
    main,
    read_particle_table,
    verify_baselines,
)

__all__ = [
    "DEFAULT_DETECTOR_CENTER_X_MM",
    "DEFAULT_DETECTOR_CENTER_Y_MM",
    "analyze_comparison",
    "analyze_simion_recording",
    "analyze_single",
    "audit_simion_recording",
    "main",
    "read_particle_table",
    "verify_baselines",
]


if __name__ == "__main__":
    raise SystemExit(main())
