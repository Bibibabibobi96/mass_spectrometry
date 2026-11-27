"""IP environment is derived from its frozen author and actual geometry."""
import copy
import json
from pathlib import Path
import unittest

from msplatform.components.ion_processor.gas_regions import resolve_ip_environment
from msplatform.contracts.gas import BoxDomain
from msplatform.contracts.gas_environment import GasEnvironment

CONFIG = Path(__file__).resolve().parents[2] / "src/msplatform/components/ion_processor/config"


class IpEnvironmentTests(unittest.TestCase):
    def test_author_resolves_actual_geometry_and_rejects_tampering(self):
        baseline, author = (json.loads((CONFIG / name).read_text(encoding="utf-8"))
                            for name in ("baseline.json", "gas_environment.json"))
        domain = BoxDomain((0, -10, -10), (211, 10, 10), (True,) * 3, (True,) * 3)
        env = resolve_ip_environment(author, baseline, domain=domain)
        field = env.fields[0]
        self.assertEqual(field.composition[0].species_id, "n2")
        self.assertEqual(field.composition[0].mass_amu, 28.0134)
        self.assertEqual([(r.domain.minimum_mm[0], r.domain.maximum_mm[0], r.state.pressure_pa)
                          for r in field.regions], [(30, 130, 1), (130, 211, 0.2)])
        self.assertEqual(GasEnvironment.from_dict(env.to_dict()), env)
        invalid = copy.deepcopy(author)
        invalid["regions"][0]["start_ref"] = "unrelated"
        with self.assertRaises(ValueError):
            resolve_ip_environment(invalid, baseline, domain=domain)
        invalid = copy.deepcopy(author)
        invalid["species_ref"]["version"] = "legacy"
        with self.assertRaises(ValueError):
            resolve_ip_environment(invalid, baseline, domain=domain)


if __name__ == "__main__":
    unittest.main()
