"""Repository-only single-way bridge; canonical implementation: msplatform.execution.cache_generation."""
from msplatform.execution import cache_generation as _core

if __name__ == "__main__":
    raise SystemExit(_core._main())
else:
    import sys
    sys.modules[__name__] = _core
