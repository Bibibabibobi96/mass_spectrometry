# Shared SIMION IOB instance seeds

This directory contains the canonical GUI-created SIMION Workbench templates
for one through ten PA instance counts.  Every new SIMION Workbench in this
repository must derive from the matching seed; do not make or retain empty
slots to reserve a future topology.  Each template deliberately loads the same local
`iob_seed_placeholder.pa0`; the IOB builders replace every instance with the
runtime PA paths before simulation.

Current runtime uses:

- `three_instance_seed.iob` for the pre-pulse handoff chain;
- `five_instance_seed.iob` for the post-pulse handoff chain;
- `seven_instance_seed.iob` for the full-flight chain.

The builders require contiguous, fully-replaced instance slots.  The
placeholder PA is the only companion file required by these templates; GEM
and Fly2 exports are intentionally excluded.  Do not edit these seeds during
a run: copy the selected seed into the run directory and save the derived IOB
under the run artifact path.
