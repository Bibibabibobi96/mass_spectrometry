"""Current publication compiler preserves scientific inputs and history."""

import json
from pathlib import Path
import tempfile
import unittest

from common.contracts.file_identity import repository_text_sha256
from integrations.runtime.refresh_repository_bindings import (
    _PORT, compile_publications, publication_differences, write_publications,
)


class RepositoryBindingsTests(unittest.TestCase):
    def fixture(self, root):
        root = root.resolve()
        def save(name, value):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")
            return path
        save("integrations/registry.json", dict(integrations=[dict(integration_id="instrument_assembly",
            downstream_terminal_profile_registry="integrations/config/terminals.json")]))
        catalog = save("integrations/config/terminals.json", dict(integration_id="instrument_assembly",
            profiles=[dict(terminal_profile_id="actual_terminal", potential_v=0)]))
        provider = save("projects/provider/resolved.json", dict(geometry_mm=[1, 2, 3]))
        port = save(_PORT, dict(authority=dict(source_contract="projects/provider/resolved.json", source_sha256="0" * 64)))
        campaign = save("common/multipole/campaigns/actual.json", dict(
            downstream_terminal_profile=dict(integration_id="instrument_assembly",
                terminal_profile_id="actual_terminal", registry_sha256="0" * 64), science=dict(voltage=123)))
        historical = save("integrations/retired/docs/history/frozen.json", dict(path="projects/provider/resolved.json", sha256="0" * 64))
        return catalog, provider, port, campaign, historical

    def test_refreshes_only_current_bindings_without_writing_provider_or_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog, provider, port, campaign, historical = self.fixture(root)
            unchanged = {p: p.read_bytes() for p in (catalog, provider, historical)}
            before = json.loads(campaign.read_text(encoding="utf-8"))
            self.assertEqual(set(compile_publications(root)), {port, campaign})
            self.assertEqual(set(write_publications(root)), {port, campaign})
            after = json.loads(campaign.read_text(encoding="utf-8"))
            before["downstream_terminal_profile"]["registry_sha256"] = repository_text_sha256(catalog)
            self.assertEqual(after, before)
            self.assertEqual(json.loads(port.read_text())["authority"]["source_sha256"], repository_text_sha256(provider))
            self.assertEqual({p: p.read_bytes() for p in unchanged}, unchanged)
            self.assertEqual(publication_differences(root), [])
            self.assertEqual(write_publications(root), [])

    def test_changed_provider_updates_only_port_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, provider, port, _, _ = self.fixture(root)
            write_publications(root)
            provider.write_text('{"geometry_mm":[4,5,6]}\n', encoding="utf-8", newline="\n")
            self.assertEqual(publication_differences(root), [port])

    def test_rejects_unknown_terminal_owner_without_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, _, campaign, _ = self.fixture(root)
            document = json.loads(campaign.read_text())
            document["downstream_terminal_profile"]["integration_id"] = "retired_family"
            campaign.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "terminal campaign owner differs"):
                compile_publications(root)


if __name__ == "__main__":
    unittest.main()
