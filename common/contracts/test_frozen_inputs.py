"""Raw-byte freezing and failure boundaries, without solver payloads."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from msplatform.execution.inputs import enumerate_python_sources, freeze_file, python_import_roots
from msplatform.execution.retention import file_record


class FrozenInputTests(unittest.TestCase):
    def test_explicit_owned_staging_overwrite_and_original_default(self):
        import stat
        with tempfile.TemporaryDirectory() as directory:
            source, target = (Path(directory) / name for name in ('source', 'target'))
            source.write_bytes(b'original\r\nraw')
            target.write_bytes(b'old')
            target.chmod(target.stat().st_mode & ~stat.S_IWRITE)
            try:
                with self.assertRaises(FileExistsError):
                    freeze_file(source, target)
                self.assertEqual(target.read_bytes(), b'old')
                actual = freeze_file(source, target, overwrite_existing=True)
                self.assertEqual(target.read_bytes(), source.read_bytes())
                self.assertEqual(actual['sha256'], file_record(source)['sha256'])
                with self.assertRaises(FileNotFoundError):
                    freeze_file(source.with_name('missing'), target, overwrite_existing=True)
                self.assertEqual(target.read_bytes(), source.read_bytes())
            finally:
                target.chmod(target.stat().st_mode | stat.S_IWRITE)

    def test_single_package_aggregate_preserves_order_identity_and_rejects_source_change(self):
        from msplatform.execution.inputs import freeze_python_package
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, copied = root / 'source', root / 'copied'
            source.mkdir()
            (source / 'first.py').write_bytes(b'first = 1\r\n')
            (source / 'second.py').write_bytes(b'second = 2\n')
            actual = freeze_python_package(source, copied, relative_paths=['second.py', 'first.py'])
            self.assertEqual(actual['schema_version'], 1)
            self.assertEqual(actual['code_root'], str(copied))
            self.assertEqual([row['relative_path'] for row in actual['files']], ['second.py', 'first.py'])
            self.assertEqual(actual['package_roots'], [str(copied)])
            self.assertEqual(actual['files'][0]['sha256'], file_record(source / 'second.py')['sha256'].upper())
            self.assertEqual((copied / 'first.py').read_bytes(), (source / 'first.py').read_bytes())
            with self.assertRaisesRegex(ValueError, 'duplicated'):
                freeze_python_package(source, copied, relative_paths=['first.py', 'FIRST.py'])
            with self.assertRaisesRegex(ValueError, 'not relative'):
                freeze_python_package(source, copied, relative_paths=['../escape.py'])
            original_copy = __import__('shutil').copyfile
            def change_after_copy(incoming, outgoing):
                result = original_copy(incoming, outgoing)
                incoming.write_bytes(b'second = 3\n')
                return result
            with patch('msplatform.execution.inputs.shutil.copyfile', side_effect=change_after_copy):
                with self.assertRaisesRegex(AssertionError, 'SHA-256 changed'):
                    freeze_python_package(source, root / 'changed', relative_paths=['second.py'])

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

            with patch("msplatform.execution.inputs.shutil.copyfile", side_effect=changing_copy):
                with self.assertRaisesRegex(AssertionError, "frozen input SHA-256 changed"):
                    freeze_file(source, target)


    def test_large_input_requires_explicit_classifier_at_both_identity_boundaries(self):
        from msplatform.execution.inputs import freeze_file as installed_freeze_file
        with tempfile.TemporaryDirectory() as directory:
            source, target = (Path(directory)/name for name in ("inert.bin", "copy.bin"))
            source.write_bytes(b"INERT_NOT_NATIVE!" * (1024 * 1024))
            if os.name == "nt":
                with self.assertRaisesRegex(ValueError, "explicit retention classifier"):
                    installed_freeze_file(source, target)
                self.assertFalse(target.exists())
            if os.name == "nt":
                classifier = lambda path, **kwargs: "required_evidence"
                with patch("msplatform.execution.inputs.file_record", wraps=__import__(
                        "msplatform.io.manifest_records", fromlist=["file_record"]).file_record) as recorded:
                    frozen = freeze_file(source, target, retention_classifier=classifier)
                self.assertIs(recorded.call_args.kwargs["retention_classifier"], classifier)
                self.assertEqual(source.read_bytes(), target.read_bytes())
                self.assertNotIn("retention_role", frozen)
                with self.assertRaises(FileExistsError):
                    freeze_file(source, target, retention_classifier=classifier)
                target.unlink()
                def corrupt_copy(incoming, outgoing):
                    outgoing.write_bytes(b"X" + incoming.read_bytes()[1:])
                with patch("msplatform.execution.inputs.shutil.copyfile", side_effect=corrupt_copy):
                    with self.assertRaisesRegex(AssertionError, "SHA-256 changed"):
                        freeze_file(source, target, retention_classifier=classifier)

class PythonPackageSelectionTests(unittest.TestCase):
    def test_import_root_bootstrap_does_not_import_scientific_or_lifecycle_packages(self):
        root = Path(__file__).resolve().parents[2]
        code = ('import sys;from pathlib import Path;root=Path(sys.argv[1]);sys.path[:0]=[str(root/"src"),str(root)];'
                'from msplatform.execution.inputs import python_import_roots;'
                'import msplatform.execution.inputs as selector;'
                'assert Path(selector.__file__).resolve().is_relative_to(root/"src");'
                'assert "msplatform.execution.owner" not in sys.modules;'
                'assert "common.contracts.write_run_manifest" not in sys.modules;'
                'assert python_import_roots(Path(sys.argv[1]))[0]==str(Path(sys.argv[1])/"src")')
        result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(root)], cwd=root,
                                capture_output=True, text=True, check=False, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_src_package_resources_are_explicit_and_imports_stay_in_the_frozen_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            author, frozen = root / 'author', root / 'frozen'
            files = {'src/msplatform/__init__.py': '',
                     'src/msplatform/entry.py': 'from pathlib import Path\nVALUE=Path(__file__).with_name("schema.schema.json").read_text()\n',
                     'src/msplatform/schema.schema.json': '{"fixture":42}',
                     'src/msplatform/unrequested.json': '{}',
                     'src/msplatform/tests/forbidden.schema.json': '{}'}
            for relative, content in files.items():
                target = author / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding='utf-8')
            selection = dict(package_roots=['src/msplatform'], provider_root='src/msplatform')
            plain = enumerate_python_sources(author, **selection)
            self.assertFalse(any(name.endswith('.json') for name in plain))
            selected = enumerate_python_sources(author, **selection, resource_suffixes=['.schema.json'])
            self.assertEqual(set(selected) - set(plain), {'src/msplatform/schema.schema.json'})
            for relative in selected:
                destination = frozen / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                freeze_file(author / relative, destination)
            author.rename(root / 'author-unavailable')
            roots = python_import_roots(frozen)
            self.assertEqual(roots, [str(frozen / 'src'), str(frozen)])
            code = ('import json,pathlib,sys;sys.path[:0]=json.loads(sys.argv[1]);'
                    'import msplatform.entry as entry;assert entry.VALUE==\'{"fixture":42}\';'
                    'assert pathlib.Path(entry.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[2]));'
                    'print("FROZEN_SRC_RESOURCE=PASS")')
            import json
            result = subprocess.run([sys.executable, '-I', '-B', '-c', code, json.dumps(roots), str(frozen)],
                                    cwd=root, capture_output=True, text=True, check=False, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            (frozen / 'src/msplatform/schema.schema.json').unlink()
            result = subprocess.run([sys.executable, '-I', '-B', '-c', code, json.dumps(roots), str(frozen)],
                                    cwd=root, capture_output=True, text=True, check=False, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('FileNotFoundError', result.stderr)

    def test_resource_suffixes_reject_unknown_or_ambiguous_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'pkg').mkdir()
            (root / 'pkg/entry.py').write_text('', encoding='utf-8')
            for suffixes in ('json', ['json'], ['.'], ['../json'], ['.json', '.json'], [True]):
                with self.subTest(suffixes=suffixes), self.assertRaises(ValueError):
                    enumerate_python_sources(root, package_roots=['pkg'], resource_suffixes=suffixes)
            self.assertEqual(python_import_roots(root), [str(root)])
            (root / 'src').write_text('not a directory', encoding='utf-8')
            with self.assertRaises(ValueError):
                python_import_roots(root)

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
