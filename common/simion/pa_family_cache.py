"""Repository-only single-way bridge; canonical implementation: msplatform.backends.simion.pa_family_cache."""
from msplatform.backends.simion import pa_family_cache as _core

if __name__ == "__main__":
    raise SystemExit(_core.main())
else:
    import sys
    sys.modules[__name__] = _core
