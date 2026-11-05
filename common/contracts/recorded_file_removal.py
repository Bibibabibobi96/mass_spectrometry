"""Repository bridge to exact installed removals/atomic writes; retire by P4."""
from msplatform.execution import recorded_file_removal as _core

write_json_atomic = _core.write_json_atomic
remove_recorded_files = _core.remove_recorded_files


def __getattr__(name):
    return getattr(_core, name)
