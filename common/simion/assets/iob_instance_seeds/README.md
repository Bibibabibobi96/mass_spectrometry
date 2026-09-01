# Shared SIMION IOB instance seeds

This directory contains the canonical GUI-created SIMION Workbench templates
for one through ten PA instance counts.  Every new SIMION Workbench in this
repository must derive from the matching numbered seed; do not make or retain
empty slots to reserve a future topology.  Slot *n* loads the distinct local
`iob_seed_placeholder_NN.pa0`.  This is essential: SIMION shares a PA object
when two Workbench instances reference the same filename, preventing the IOB
builder from independently replacing their runtime PA paths.

Current runtime uses:

- `3_instance_seed.iob` for the pre-pulse handoff chain;
- `5_instance_seed.iob` for the post-pulse handoff chain;
- `7_instance_seed.iob` for the full-flight chain.

The builders require contiguous, fully-replaced instance slots.  A seed is
always copied together with all ten placeholder PAs before its runtime IOB is
built; GEM and Fly2 exports are intentionally excluded.  Do not edit these
seeds during a run: copy the selected seed into the run directory and save the
derived IOB under the run artifact path.
