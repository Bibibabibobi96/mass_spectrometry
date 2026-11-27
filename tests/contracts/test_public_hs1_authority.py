"""The public HS1 request carries geometry and frozen sources, not gas state."""
import json
import tempfile
import unittest
from pathlib import Path

from msplatform.workflows.native_tracing import _hs1_request


class PublicHs1AuthorityTests(unittest.TestCase):
    def test_request_uses_only_explicit_domains_and_frozen_sources(self):
        domain = {"minimum_mm": [0, 0, 0], "maximum_mm": [1, 1, 1],
                  "lower_closed": [True, True, True], "upper_closed": [True, True, True]}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = {"bath_domain": domain, "outer_domain": domain, "numerics": {},
                       "environment_instance_id": "ip", "environment_record": {}, "vendor_record": {}}
            (root / "hs1_request.json").write_text(json.dumps(request), encoding="utf-8")
            (root / "hs1_environment.json").write_text("{}", encoding="utf-8")
            (root / "hs1_vendor.lua").write_text("-- fixture", encoding="utf-8")
            value = _hs1_request({"gas_environment": {"status": "hs1"}}, root)
            self.assertIn("outer_domain", value)
            self.assertNotIn("outer", value)
            self.assertEqual(value["environment_instance_id"], "ip")
            self.assertEqual(value["environment_record"]["path"], str(root / "hs1_environment.json"))


if __name__ == "__main__":
    unittest.main()
