"""Legacy whole-unit import bridge; retire named consumers no later than P4."""
from msplatform.execution import recovery as _core

WholeUnitReplayUnit = _core.WholeUnitReplayUnit
build_whole_unit_replay_plan = _core.build_whole_unit_replay_plan


def __getattr__(name):
    return getattr(_core, name)
