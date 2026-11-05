"""Repository-only single-way bridge; canonical implementation: msplatform.backends.simion.standalone_pa_response_set."""
from msplatform.backends.simion import standalone_pa_response_set as _core

if __name__ == "__main__":
    raise SystemExit(_core.main())
else:
    import sys
    sys.modules[__name__] = _core
