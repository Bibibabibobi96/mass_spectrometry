"""Raw-byte freezing and failure boundaries, without solver payloads."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.frozen_inputs import enumerate_python_sources, freeze_file
from common.contracts.write_run_manifest import file_record


class FrozenInputTests(unittest.TestCase):
    def test_freezes_original_bytes_and_returns_destination_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, target = (Path(directory)/name for name in ("source.json", "copy.json"))
            source.write_bytes(b'{"line":"raw"}\r\n')
            expected = file_record(source)
            frozen = freeze_file(source, target)
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertEqual(frozen, {**expected, "path": str(target.resolve()),
                                     "source_path": str(source.resolve())})
            with self.assertRaises(FileExistsError):
                freeze_file(source, target)
            self.assertEqual(target.read_bytes(), source.read_bytes())

    def test_missing_source_leaves_no_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, target = (Path(directory)/name for name in ("missing", "copy"))
            with self.assertRaises(FileNotFoundError):
                freeze_file(source, target)
            self.assertFalse(target.exists())

    def test_rejects_changed_bytes_during_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, target = (Path(directory)/name for name in ("source", "copy"))
            source.write_bytes(b"original")

            def changing_copy(incoming: Path, outgoing: Path) -> None:
                incoming.write_bytes(b"modified")
                outgoing.write_bytes(incoming.read_bytes())

            with patch("common.contracts.frozen_inputs.shutil.copyfile", side_effect=changing_copy):
                with self.assertRaisesRegex(AssertionError, "frozen input SHA-256 changed"):
                    freeze_file(source, target)


class PythonPackageSelectionTests(unittest.TestCase):
    def test_package_enumerates_new_modules_and_initializers_but_not_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = ["provider/__init__.py", "provider/pkg/__init__.py", "provider/pkg/entry.py",
                     "provider/pkg/new_module.py", "provider/pkg/nested/module.py",
                     "provider/pkg/tests/test_entry.py", "provider/pkg/test_support/helper.py",
                     "provider/pkg/assets/not_source.py", "provider/pkg/history/old.py",
                     "provider/pkg/generated/out.py", "provider/pkg/test_shape.py", "provider/pkg/shape_test.py",
                     "provider/pkg/__pycache__/entry.py", "provider/pkg/native.pa0", "provider/pkg/schema.json"]
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("never imported", encoding="utf-8")
            actual = enumerate_python_sources(root, package_roots=["provider/pkg"], provider_root="provider")
            self.assertEqual(actual, sorted(names[:5]))

    def test_namespace_and_explicit_modules_share_parent_initializer_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "provider/namespace").mkdir(parents=True)
            for name in ["__init__.py", "namespace/a.py", "namespace/b.py"]:
                (root / "provider" / name).write_text("VALUE = 1", encoding="utf-8")
            self.assertEqual(enumerate_python_sources(root, module_paths=["provider/namespace/b.py",
                "provider/namespace/a.py"], provider_root="provider"),
                ["provider/__init__.py", "provider/namespace/a.py", "provider/namespace/b.py"])

    def test_invalid_or_overlapping_author_selections_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "provider/pkg/sub").mkdir(parents=True)
            (root / "provider/pkg/entry.py").write_text("VALUE = 1", encoding="utf-8")
            (root / "provider/pkg/sub/module.py").write_text("VALUE = 2", encoding="utf-8")
            cases = [dict(), dict(package_roots=["provider/missing"]),
                     dict(package_roots=["provider/pkg", "provider/pkg"]),
                     dict(package_roots=["provider/pkg", "provider/pkg/sub"]),
                     dict(package_roots=["provider/pkg"], module_paths=["provider/pkg/entry.py"]),
                     dict(module_paths=["provider/pkg/entry.py", "provider/pkg/entry.py"]),
                     dict(package_roots=[str(root / "provider/pkg")]),
                     dict(package_roots=["provider/../provider/pkg"]),
                     dict(package_roots=["provider/pkg/tests"]),
                     dict(package_roots="provider/pkg")]
            for arguments in cases:
                with self.subTest(arguments=arguments), self.assertRaises((ValueError, FileNotFoundError)):
                    enumerate_python_sources(root, **arguments)

    def test_provider_does_not_silently_omit_existing_external_ancestor_initializer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "provider/pkg").mkdir(parents=True)
            (root / "provider/__init__.py").write_text("VALUE = 1", encoding="utf-8")
            (root / "provider/pkg/entry.py").write_text("VALUE = 2", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "escapes its declared provider"):
                enumerate_python_sources(root, package_roots=["provider/pkg"], provider_root="provider/pkg")

    def test_real_frozen_import_runs_new_package_module_after_author_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            author, frozen = root / "author", root / "frozen"
            (author / "provider/pkg").mkdir(parents=True)
            (author / "provider/pkg/entry.py").write_text("from .new_module import VALUE\nassert VALUE == 42\n", encoding="utf-8")
            # Adding this imported module requires no change to the package declaration.
            (author / "provider/pkg/new_module.py").write_text("VALUE = 42\n", encoding="utf-8")
            paths = enumerate_python_sources(author, package_roots=["provider/pkg"], provider_root="provider")
            for relative in paths:
                destination = frozen / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                freeze_file(author / relative, destination)
            author.rename(root / "author-unavailable")
            code = "import pathlib,sys;sys.path.insert(0,sys.argv[1]);import provider.pkg.entry as entry;assert pathlib.Path(entry.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve());print('FROZEN_NEW_MODULE=PASS')"
            result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(frozen)],
                                    cwd=root, capture_output=True, text=True, check=False, timeout=None)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("FROZEN_NEW_MODULE=PASS", result.stdout)

    def test_directory_link_cannot_escape_source_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider, external = root / "author/provider", root / "external"
            provider.mkdir(parents=True)
            external.mkdir()
            (external / "hidden.py").write_text("not imported", encoding="utf-8")
            if os.name == "nt":
                linked = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(provider / "linked"),
                                         str(external)], cwd=root, capture_output=True, text=True, check=False, timeout=None)
                self.assertEqual(linked.returncode, 0, linked.stdout + linked.stderr)
            else:
                (provider / "linked").symlink_to(external, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "escapes its declared provider"):
                enumerate_python_sources(root / "author", package_roots=["provider"])


if __name__ == "__main__":
    unittest.main()
