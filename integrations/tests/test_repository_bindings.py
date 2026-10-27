"""Current port publication preserves provider inputs and frozen history."""

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
            path.write_text(json.dumps(value) + "\n", encoding="utf-8", newline="\n")
            return path
        provider = save("projects/provider/resolved.json", dict(geometry_mm=[1, 2, 3]))
        port = save(_PORT, dict(authority=dict(source_contract="projects/provider/resolved.json", source_sha256="0" * 64)))
        historical = save("integrations/docs/history/frozen.json", dict(sha256="0" * 64))
        return provider, port, historical

    def test_refreshes_only_port_without_writing_provider_or_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider, port, historical = self.fixture(root)
            unchanged = {p: p.read_bytes() for p in (provider, historical)}
            self.assertEqual(set(compile_publications(root)), {port})
            self.assertEqual(write_publications(root), [port])
            self.assertEqual(json.loads(port.read_text())["authority"]["source_sha256"], repository_text_sha256(provider))
            self.assertEqual({p: p.read_bytes() for p in unchanged}, unchanged)
            self.assertEqual(publication_differences(root), [])
            self.assertEqual(write_publications(root), [])

    def test_changed_provider_updates_port_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider, port, _ = self.fixture(root)
            write_publications(root)
            provider.write_text('{"geometry_mm":[4,5,6]}\n', encoding="utf-8", newline="\n")
            self.assertEqual(publication_differences(root), [port])


if __name__ == "__main__":
    unittest.main()
