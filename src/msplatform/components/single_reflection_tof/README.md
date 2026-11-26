# Single-reflection TOF

This provider owns the downstream flight shield, reflectron electrodes and detector.
It accepts only explicit version 1 downstream geometry, coordinates, ring counts and
voltages; OA, particle sources and pulse drives are separate Assembly inputs.
`legacy_projection.project_legacy_downstream` extracts those fields from an explicitly
frozen legacy resolved instrument. The caller verifies that source and provenance first.
The cylinder returned as `flight_tube_cavity` is an enclosure envelope, not a claim
of obstacle-free vacuum, correct field coupling or collision-free geometry.
Start with the repository [README](../../../../README.md), then read the current
status and retained historical overlap in [PROJECT](docs/PROJECT.md).
