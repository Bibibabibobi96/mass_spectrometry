"""Single-direction bridge to the neutral canonical transfer-state contract.

Legacy RF/IP/MR/integration transfer-state consumers and frozen CLI inventories
migrate to msplatform.contracts.particle_state; remove this bridge by P4.
The separate common.contracts.particle_state RF event protocol is unchanged.
"""
import sys
from msplatform.contracts import particle_state as _core

if __name__ == "__main__":
    _core.main()
else:
    sys.modules[__name__] = _core
