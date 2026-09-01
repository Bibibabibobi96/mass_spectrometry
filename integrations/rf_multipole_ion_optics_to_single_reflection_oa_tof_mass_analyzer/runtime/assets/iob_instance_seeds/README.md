# SIMION IOB instance seeds

This directory contains the canonical GUI-created SIMION Workbench templates
for the three, five, and seven PA instance counts currently required by the
single-flight runtime.  Each template deliberately loads the same local
`iob_seed_placeholder.pa0`; the IOB builders replace every instance with the
runtime PA paths before simulation.

Current runtime uses:

- `three_instance_seed.iob` for the pre-pulse handoff chain;
- `five_instance_seed.iob` for the post-pulse handoff chain;
- `seven_instance_seed.iob` for the full-flight chain.

Do not create empty slots to reserve future topology: the builders require
contiguous, fully-replaced instance slots.  The placeholder PA is the only
companion file required by these templates; GEM and Fly2 exports are
intentionally excluded.
