"""Focused regressions for documentation navigation and frozen history boundaries."""

from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from common.documentation_links import anchors, inspect_repository, is_history, links, main, migrated_history, table_diagnostics


class DocumentationPathTransportTests(unittest.TestCase):
    def test_path_file_preserves_unicode_and_the_complete_history_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            path_file = Path(directory) / 'paths.json'
            paths = [f'projects/example/{index:04d}_' + 'x' * 90 + '.py' for index in range(500)]
            paths.append('docs/history/末尾 with spaces.md')
            report = {'errors': [], 'diagnostics': [], 'inventory': []}
            with io.TextIOWrapper(io.BytesIO(), encoding='utf-8') as output, redirect_stdout(output):
                for selected in (paths, [], ['docs/history/one.md']):
                    with self.subTest(count=len(selected)):
                        path_file.write_text(json.dumps(selected, ensure_ascii=False), encoding='utf-8-sig')
                        before = path_file.read_bytes()
                        with patch('common.documentation_links.inspect_repository', return_value=report) as inspect:
                            self.assertEqual(main(['--root', directory, '--changed-paths-file', str(path_file)]), 0)
                        self.assertEqual(inspect.call_args.kwargs['changed_paths'], set(selected))
                        self.assertFalse(inspect.call_args.kwargs['audit_history'])
                        self.assertEqual(path_file.read_bytes(), before)
                with patch('common.documentation_links.inspect_repository', return_value=report) as inspect:
                    self.assertEqual(main(['--changed-path', 'a.md', '--changed-path', 'b.md']), 0)
                self.assertEqual(inspect.call_args.kwargs['changed_paths'], {'a.md', 'b.md'})

    def test_invalid_path_files_and_conflicting_inputs_fail_before_inspection(self):
        with tempfile.TemporaryDirectory() as directory:
            path_file = Path(directory) / 'paths.json'
            cases = ['{', 'null', '{}', '[1]', '[""]', '["   "]']
            with io.TextIOWrapper(io.BytesIO(), encoding='utf-8') as output, redirect_stdout(output), redirect_stderr(io.StringIO()):
                with patch('common.documentation_links.inspect_repository', side_effect=AssertionError('invalid input reached inspection')):
                    for content in cases:
                        with self.subTest(content=content):
                            path_file.write_text(content, encoding='utf-8')
                            with self.assertRaises(SystemExit) as error:
                                main(['--changed-paths-file', str(path_file)])
                            self.assertEqual(error.exception.code, 2)
                    path_file.unlink()
                    for arguments in ([ '--changed-paths-file', str(path_file)],
                                      ['--changed-path', 'README.md', '--changed-paths-file', str(path_file)]):
                        with self.subTest(arguments=arguments), self.assertRaises(SystemExit) as error:
                            main(arguments)
                        self.assertEqual(error.exception.code, 2)

    @unittest.skipUnless(os.name == 'nt', 'Windows process command-line boundary')
    def test_public_gate_transports_long_selection_and_preserves_failures_and_cleanup(self):
        with tempfile.TemporaryDirectory(prefix='doc_transport_') as directory:
            root = Path(directory)
            common = root / 'common'
            common.mkdir()
            for name in ('verify_documentation.ps1', 'documentation_links.py'):
                shutil.copyfile(Path(__file__).with_name(name), common / name)
            (root / 'projects').mkdir()
            (root / 'docs/history').mkdir(parents=True)
            (root / 'temp').mkdir()
            (root / 'README.md').write_text('# Entry\n[Docs](docs/README.md)\n[Agents](AGENTS.md)\n', encoding='utf-8')
            for name in ('AGENTS.md', 'CLAUDE.md'):
                (root / name).write_text('# Entry\n', encoding='utf-8')
            authorities = ('REPOSITORY_ARCHITECTURE', 'LIFECYCLE', 'OPERATIONS', 'DEVELOPMENT_STANDARDS',
                           'PLOTTING_STANDARDS', 'COMPONENT_CONNECTION_ARCHITECTURE', 'VISION', 'ROADMAP')
            (root / 'docs/README.md').write_text('\n'.join(f'[{name}]({name}.md)' for name in authorities), encoding='utf-8')
            for name in authorities:
                (root / f'docs/{name}.md').write_text('[Root](../README.md)\n[Agents](../AGENTS.md)\n', encoding='utf-8')
            selected = root / 'docs/history/末尾 with spaces.md'
            selected.write_text('DOC_STATUS: ARCHIVED_READ_ONLY\n', encoding='utf-8')
            (root / 'docs/history/unrelated.md').write_text('# No archive banner\n', encoding='utf-8')
            (root / 'docs/AUDITS.md').write_text('history/末尾 with spaces.md\n', encoding='utf-8')
            subprocess.run(['git', 'init', '--quiet'], cwd=root, check=True, capture_output=True, timeout=30)
            paths = [f'projects/example/{index:04d}_' + 'x' * 90 + '.py' for index in range(500)]
            paths.append(selected.relative_to(root).as_posix())
            self.assertGreater(len(subprocess.list2cmdline([value for path in paths for value in ('--changed-path', path)])), 32767)
            (root / 'paths.json').write_text(json.dumps(paths, ensure_ascii=False), encoding='utf-8')
            driver = root / 'driver.ps1'
            driver.write_text(r'''
param($PythonExe)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$paths=@(Get-Content -LiteralPath (Join-Path $PSScriptRoot 'paths.json') -Raw -Encoding utf8|ConvertFrom-Json)
$results=@()
foreach($case in @('valid','selected_history_invalid','active_link_invalid')){
 if($case-eq'selected_history_invalid'){'invalid'|Set-Content -LiteralPath (Join-Path $PSScriptRoot 'docs/history/末尾 with spaces.md') -Encoding utf8}
 if($case-eq'active_link_invalid'){
  'DOC_STATUS: ARCHIVED_READ_ONLY'|Set-Content -LiteralPath (Join-Path $PSScriptRoot 'docs/history/末尾 with spaces.md') -Encoding utf8
  '[bad](missing.md)'|Add-Content -LiteralPath (Join-Path $PSScriptRoot 'README.md') -Encoding utf8
 }
 try{& (Join-Path $PSScriptRoot 'common/verify_documentation.ps1') -StructureOnly -PythonExe $PythonExe -ChangedPath $paths;$ok=$true;$message=''}
 catch{$ok=$false;$message=$_.Exception.Message}
 $results+=@{case=$case;ok=$ok;error=$message}
}
'DOC_CASE_RESULTS='+($results|ConvertTo-Json -Compress)
''', encoding='utf-8')
            result = subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-File', str(driver), sys.executable],
                cwd=root, env={**os.environ, 'TEMP': str(root / 'temp'), 'TMP': str(root / 'temp')},
                capture_output=True, text=True, encoding='utf-8', timeout=60, check=True)
            line = next(line for line in result.stdout.splitlines() if line.startswith('DOC_CASE_RESULTS='))
            observed = json.loads(line.removeprefix('DOC_CASE_RESULTS='))
            self.assertEqual([row['ok'] for row in observed], [True, False, False], result.stdout + result.stderr)
            self.assertTrue(all('Documentation gate failed' in row['error'] for row in observed[1:]))
            self.assertEqual(list((root / 'temp').iterdir()), [])


class PowerShellHistoryScopeTests(unittest.TestCase):
    """Exercise the production history block on small isolated directories."""

    @classmethod
    def setUpClass(cls):
        source = Path(__file__).with_name('verify_documentation.ps1').read_text(encoding='utf-8')
        start = source.index('$historyFiles = ')
        end = source.index("foreach ($required in @('AGENTS.md'", start)
        cls.script = (
            "$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest\n"
            "$repoRoot=$env:DOC_HISTORY_TEST_ROOT\n"
            "$utf8=[Text.UTF8Encoding]::new($false,$true)\n"
            "$errors=[Collections.Generic.List[string]]::new()\n"
            "$AuditHistory=$true;$ChangedPath=@()\n"
            "function Add-DocError { param([string]$Message) $errors.Add($Message) }\n"
            + source[start:end]
            + "\nConvertTo-Json -InputObject @($errors) -Compress\n"
        )

    def check_history(self, root):
        result = subprocess.run(
            ['pwsh', '-NoProfile', '-NonInteractive', '-Command', self.script],
            cwd=root,
            env={**os.environ, 'DOC_HISTORY_TEST_ROOT': str(root)},
            check=True, capture_output=True, text=True, encoding='utf-8', timeout=30,
        )
        return json.loads(result.stdout)

    def test_changed_history_does_not_audit_unrelated_archive(self):
        with tempfile.TemporaryDirectory(prefix='documentation_history_test_') as directory:
            root = self.prepare_root(directory)
            history = root / 'docs/history'
            (history / 'selected.md').write_text('DOC_STATUS: ARCHIVED_READ_ONLY\n', encoding='utf-8')
            (history / 'unrelated.md').write_text('not a frozen banner\n', encoding='utf-8')
            (root / 'docs/AUDITS.md').write_text('history/selected.md\n', encoding='utf-8')
            script = self.script.replace('$AuditHistory=$true;$ChangedPath=@()',
                                        "$AuditHistory=$false;$ChangedPath=@('docs/history/selected.md')")
            result = subprocess.run(['pwsh','-NoProfile','-Command',script], cwd=root,
                env={**os.environ,'DOC_HISTORY_TEST_ROOT':str(root)}, capture_output=True,
                text=True, check=True, timeout=30)
            self.assertEqual(json.loads(result.stdout), [])

    def test_markdown_discovery_inside_artifacts_checkout(self):
        source = Path(__file__).with_name('verify_documentation.ps1').read_text(encoding='utf-8')
        discovery = source[source.index('$markdownFiles = '):source.index('$utf8 = ')]
        with tempfile.TemporaryDirectory(prefix='documentation_gate_test_') as directory:
            root = Path(directory) / 'artifacts' / 'scratch' / 'repo'
            (root / 'artifacts').mkdir(parents=True)
            (root / 'README.md').write_text('# Active\n', encoding='utf-8')
            (root / 'artifacts/ignored.md').write_text('# Generated\n', encoding='utf-8')
            script = "$repoRoot=$env:DOC_HISTORY_TEST_ROOT\n" + discovery + '\n$markdownFiles.Count'
            result = subprocess.run(
                ['pwsh', '-NoProfile', '-NonInteractive', '-Command', script],
                env={**os.environ, 'DOC_HISTORY_TEST_ROOT': str(root)}, cwd=root,
                check=True, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.stdout.strip(), '1')

    def prepare_root(self, directory):
        root = Path(directory)
        (root / 'docs/history').mkdir(parents=True)
        (root / 'projects').mkdir()
        (root / 'integrations/docs/history').mkdir(parents=True)
        return root

    def test_root_and_existing_history_scopes_share_checks(self):
        with tempfile.TemporaryDirectory(prefix='documentation_history_test_') as directory:
            root = self.prepare_root(directory)
            scopes = (
                ('docs/history', 'docs/AUDITS.md', 'history/'),
                ('integrations/docs/history', 'integrations/docs/history/README.md', ''),
                ('projects/p/docs/history', 'projects/p/docs/history/README.md', ''),
            )
            for history, index, prefix in scopes:
                folder = root / history
                folder.mkdir(parents=True, exist_ok=True)
                (folder / 'snapshot.md').write_text('DOC_STATUS: ARCHIVED_READ_ONLY\n', encoding='utf-8')
                (root / index).write_text(prefix + 'snapshot.md\n', encoding='utf-8')
            self.assertEqual(self.check_history(root), [])
            for _, index, prefix in scopes:
                with self.subTest(index=index):
                    (root / index).write_text('', encoding='utf-8')
                    errors = self.check_history(root)
                    self.assertEqual(len(errors), 1)
                    self.assertIn(f"does not index '{prefix}snapshot.md'", errors[0])
                    (root / index).write_text(prefix + 'snapshot.md\n', encoding='utf-8')

    def test_root_integration_history_rejects_missing_banner_index_and_loose_payload(self):
        with tempfile.TemporaryDirectory(prefix='documentation_history_test_') as directory:
            root = self.prepare_root(directory)
            history = root / 'integrations/docs/history'
            (history / 'snapshot.md').write_text('# Snapshot\n', encoding='utf-8')
            (history / 'loose.json').write_text('{}\n', encoding='utf-8')
            errors = self.check_history(root)
            self.assertEqual(len(errors), 3)
            self.assertTrue(any('missing read-only archive banner' in item for item in errors))
            self.assertTrue(any("integrations/docs/history/README.md does not index 'snapshot.md'" in item for item in errors))
            self.assertTrue(any('history payload must be inside a same-name manifest directory' in item for item in errors))

    def test_retired_project_exemption_cannot_hide_other_history_payloads(self):
        with tempfile.TemporaryDirectory(prefix='documentation_history_test_') as directory:
            root = self.prepare_root(directory)
            for scope in ('docs/history', 'integrations/docs/history'):
                target = root / scope / 'retired_projects/old'
                target.mkdir(parents=True)
                (target / 'unregistered.json').write_text('{}', encoding='utf-8')
            errors = self.check_history(root)
            self.assertEqual(len(errors), 2)
            self.assertTrue(all('payload directory has no same-name flat Markdown manifest' in message for message in errors))


class MarkdownNavigationTests(unittest.TestCase):
    def test_staged_history_rename_requires_unchanged_head_bytes(self):
        with tempfile.TemporaryDirectory(prefix='documentation_gate_test_') as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '--quiet', str(root)], check=True, cwd=root, timeout=30)
            original = root / 'integrations/old/docs/history/snapshot.md'
            original.parent.mkdir(parents=True)
            content = b'# Frozen\nDOC_STATUS: ARCHIVED_READ_ONLY\n[old](../retired.md)\n'
            original.write_bytes(content)
            (root / '.gitattributes').write_text('* -text\n', encoding='utf-8')
            subprocess.run(['git', '-C', str(root), 'add', '.'], check=True, cwd=root, timeout=30)
            subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                            'commit', '--quiet', '-m', 'Freeze history'], check=True, cwd=root, timeout=30)
            moved = root / 'integrations/docs/history/snapshot.md'
            moved.parent.mkdir(parents=True)
            original.rename(moved)
            subprocess.run(['git', '-C', str(root), 'add', '-A'], check=True, cwd=root, timeout=30)
            self.assertEqual(migrated_history(root), ({moved.relative_to(root).as_posix()}, []))
            self.assertFalse(inspect_repository(root, audit_history=True, show_review=True)['errors'])
            moved.write_bytes(content + b'changed\n')
            verified, errors = migrated_history(root)
            self.assertFalse(verified)
            self.assertIn('differs from its HEAD source bytes', errors[0])
            self.assertTrue(inspect_repository(root, audit_history=True, show_review=True)['errors'])

    def test_staged_active_document_move_does_not_gain_history_exemption(self):
        with tempfile.TemporaryDirectory(prefix='documentation_gate_test_') as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '--quiet', str(root)], check=True, cwd=root, timeout=30)
            original = root / 'guide.md'
            original.write_bytes(b'# Guide\n[bad](missing.md)\n')
            (root / '.gitattributes').write_text('* -text\n', encoding='utf-8')
            subprocess.run(['git', '-C', str(root), 'add', '.'], check=True, cwd=root, timeout=30)
            subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                            'commit', '--quiet', '-m', 'Add guide'], check=True, cwd=root, timeout=30)
            moved = root / 'docs/history/snapshot.md'
            moved.parent.mkdir(parents=True)
            original.rename(moved)
            subprocess.run(['git', '-C', str(root), 'add', '-A'], check=True, cwd=root, timeout=30)
            self.assertEqual(migrated_history(root), (set(), []))
            self.assertTrue(inspect_repository(root, audit_history=True, show_review=True)['errors'])

    def test_retired_project_move_requires_exact_git_bytes_and_complete_inventory(self):
        with tempfile.TemporaryDirectory(prefix='documentation_gate_test_') as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '--quiet', str(root)], check=True, cwd=root, timeout=30)
            original = root / 'projects/old/docs/history/snapshot.md'
            original.parent.mkdir(parents=True)
            content = b'# Frozen\n[original context](../old.md)\n'
            original.write_bytes(content)
            (root / '.gitattributes').write_text('* -text\n', encoding='utf-8')
            subprocess.run(['git', '-C', str(root), 'add', '.'], check=True, cwd=root, timeout=30)
            subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '--quiet', '-m', 'Freeze source'], check=True, cwd=root, timeout=30)
            commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True, cwd=root, timeout=30).strip()
            archive = root / 'projects/new/docs/history/retired_projects'
            moved = archive / 'old/docs/history/snapshot.md'
            moved.parent.mkdir(parents=True)
            moved.write_bytes(content)
            manifest = {'schema_version': 1, 'source_commit': commit, 'entries': [{
                'source_path': 'projects/old/docs/history/snapshot.md',
                'archive_path': 'old/docs/history/snapshot.md',
                'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest(),
            }]}
            (archive / 'migration_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            verified, errors = migrated_history(root)
            self.assertFalse(errors)
            self.assertEqual(verified, {moved.relative_to(root).as_posix()})
            self.assertFalse(inspect_repository(root, audit_history=True, show_review=True)['errors'])
            moved.write_bytes(content + b'changed')
            self.assertIn('frozen bytes/source mismatch', migrated_history(root)[1][0])
            moved.write_bytes(content)
            (archive / 'unlisted.json').write_text('{}', encoding='utf-8')
            self.assertIn('unlisted or missing', migrated_history(root)[1][0])
            (archive / 'unlisted.json').unlink()
            manifest['entries'][0]['source_path'] = 'projects/old/docs/history/absent.md'
            (archive / 'migration_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            self.assertIn('invalid original path mapping', migrated_history(root)[1][0])

    def test_incomplete_validation_matrix_reports_exact_rows(self):
        text = '# Evidence\n\n| Item | Requirement |\n|---|---|\n| Source |\n| Statistics |\n| Mass | Three points |\n'
        self.assertEqual(table_diagnostics(text), [
            (5, 'table row has 1 cells; header has 2; review missing/extra content'),
            (6, 'table row has 1 cells; header has 2; review missing/extra content'),
        ])

    def test_empty_cells_extra_cells_and_mismatched_delimiter_are_reviewed(self):
        text = '| Item | |\n|---|\n| Source |   |\n| Mass | Three | Extra |\n'
        result = table_diagnostics(text)
        self.assertEqual([number for number, _ in result], [2, 1, 3, 4])
        self.assertIn('empty cells at columns 2', result[1][1])
        self.assertIn('empty cells at columns 2', result[2][1])

    def test_valid_table_pipes_code_and_nonapplicable_cells(self):
        text = (
            '| Item | Requirement |\n|:---|---:|\n'
            '| `x|y` | ``a`|b`` |\n'
            '| a\\|b | Not applicable |\n'
            '| `--flag` | [Source](source.md) |\n\n'
            'Item | Requirement\n- | -\n'
            'a\\\\ | b\n'
            'value | N/A\n'
        )
        self.assertFalse(table_diagnostics(text))

    def test_table_examples_in_fences_comments_and_indented_code_are_ignored(self):
        invalid = '| Item | Requirement |\n|---|---|\n| Source |\n'
        text = '```md\n' + invalid + '```\n<!--\n' + invalid + '-->\n'
        text += ''.join('    ' + line + '\n' for line in invalid.splitlines())
        self.assertFalse(table_diagnostics(text))

    def test_table_review_excludes_history_and_preserves_nonblocking_status(self):
        with tempfile.TemporaryDirectory(prefix='documentation_gate_test_') as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '--quiet', str(root)], check=True, cwd=root, timeout=30)
            text = '# Evidence\n| Item | Requirement |\n|---|---|\n| Source | |\n'
            (root / 'README.md').write_text(text, encoding='utf-8')
            history = root / 'docs/history'
            history.mkdir(parents=True)
            (history / 'frozen.md').write_text(text, encoding='utf-8')
            result = inspect_repository(root, audit_history=True, show_review=True)
            self.assertFalse(result['errors'])
            self.assertEqual(len(result['diagnostics']), 1)
            self.assertIn('README.md:4: table has empty cells', result['diagnostics'][0])
            self.assertEqual(result['inventory'][0]['characters'], len(text))

    def test_unicode_duplicate_and_explicit_anchors(self):
        text = '# 入口\n## 长 PA 输入路径\n## 长 PA 输入路径\n## `config` 与 **输入**\n<a id="manual"></a>'
        self.assertEqual(anchors(text), {'入口', '长-pa-输入路径', '长-pa-输入路径-1', 'config-与-输入', 'manual'})

    def test_duplicate_suffix_collision_and_html_anchor(self):
        text = '# Topic\n## Topic\n## Topic-1\n## Topic\n<a name="中文锚点"></a>\n````html\n<a id="example"></a>\n````'
        self.assertEqual(anchors(text), {'topic', 'topic-1', 'topic-1-1', 'topic-2', '中文锚点'})

    def test_fences_inline_code_and_indented_examples_are_not_links(self):
        text = '# 标题\n````md\n```\n[bad](missing.md)\n````\n`[bad](missing.md)`\n    [bad](missing.md)\n[good](ok.md)'
        self.assertEqual(links(text), [(8, 'ok.md')])

    def test_inline_and_reference_links(self):
        text = '[one](<a b.md#标题> "Title")\n[two][KEY]\n[key][]\n[key]\n[key]: other.md#段落\n[paren](path(a).md)'
        self.assertEqual([target for _, target in links(text)], ['a b.md#标题', 'other.md#段落', 'other.md#段落', 'other.md#段落', 'path(a).md'])

    def test_image_references_and_escaped_link_examples(self):
        text = '![plot][IMAGE]\n![image][]\n![image]\n[image]: plots/beam.png\n\\[sample](missing.md)\n\\[image]\n'
        self.assertEqual([target for _, target in links(text)], ['plots/beam.png'] * 3)

    def test_history_boundary_is_not_any_directory_named_history(self):
        self.assertTrue(is_history(Path('projects/p/docs/history/retired_campaigns/INDEX.md')))
        self.assertTrue(is_history(Path('docs/history/snapshot.md')))
        self.assertFalse(is_history(Path('common/history/README.md')))
        self.assertFalse(is_history(Path('docs/history_notes.md')))
        self.assertFalse(is_history(Path('projects/p/docs/history/README.md')))
        self.assertFalse(is_history(Path('docs/history/README.md')))

    def test_committed_history_entry_index_remains_active(self):
        with tempfile.TemporaryDirectory(prefix='documentation_gate_test_') as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '--quiet', str(root)], check=True, cwd=root, timeout=30)
            history = root / 'docs/history'
            history.mkdir(parents=True)
            (history / 'README.md').write_text('# Index\n[bad](missing.md)\n', encoding='utf-8')
            subprocess.run(['git', '-C', str(root), 'add', '.'], check=True, cwd=root, timeout=30)
            subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '--quiet', '-m', 'Add index'], check=True, cwd=root, timeout=30)
            result = inspect_repository(root, audit_history=True, show_review=True)
            self.assertEqual(len(result['errors']), 1)
            self.assertEqual(result['inventory'][0]['kind'], 'entry')

    def test_fragment_and_missing_link_fail_but_history_is_diagnostic(self):
        with tempfile.TemporaryDirectory(prefix='documentation_gate_test_') as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '--quiet', str(root)], check=True, cwd=root, timeout=30)
            (root / 'README.md').write_text('# 入口\n[ok](#入口)\n[bad](#失效)\n[missing](absent.md)\n[other](other.md#%E6%A0%87%E9%A2%98)\n', encoding='utf-8')
            (root / 'other.md').write_text('# 标题\n', encoding='utf-8')
            history = root / 'docs/history/retired_campaigns'
            history.mkdir(parents=True)
            (history / 'INDEX.md').write_text('# Frozen\n[old](gone.md)\n', encoding='utf-8')
            subprocess.run(['git', '-C', str(root), 'add', 'docs/history'], check=True, cwd=root, timeout=30)
            subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '--quiet', '-m', 'Freeze test fixture'], check=True, cwd=root, timeout=30)
            result = inspect_repository(root, audit_history=True, show_review=True)
            self.assertEqual(len(result['errors']), 2)
            self.assertTrue(any('gone.md' in message for message in result['diagnostics']))
            self.assertEqual(len(result['inventory']), 3)
            self.assertFalse(any('no incoming' in message for message in result['diagnostics']))

    def test_new_history_links_must_be_complete(self):
        with tempfile.TemporaryDirectory(prefix='documentation_gate_test_') as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '--quiet', str(root)], check=True, cwd=root, timeout=30)
            history = root / 'docs/history'
            history.mkdir(parents=True)
            (history / 'new.md').write_text('# New archive\n[bad](missing.json)', encoding='utf-8')
            result = inspect_repository(root, audit_history=True, show_review=True)
            self.assertEqual(len(result['errors']), 1)

    def test_external_artifacts_are_optional_and_scratch_is_reported(self):
        with tempfile.TemporaryDirectory(prefix='documentation_gate_test_') as directory:
            root = Path(directory) / 'repo'
            root.mkdir()
            subprocess.run(['git', 'init', '--quiet', str(root)], check=True, cwd=root, timeout=30)
            (root / 'README.md').write_text('# Entry\n[evidence](../artifacts/projects/p/scratch/x/report.json)', encoding='utf-8')
            result = inspect_repository(root, audit_history=True, show_review=True)
            self.assertFalse(result['errors'])
            self.assertTrue(any('scratch evidence' in message for message in result['diagnostics']))

    def test_checkout_under_scratch_does_not_taint_internal_links(self):
        with tempfile.TemporaryDirectory(prefix='documentation_gate_test_') as directory:
            root = Path(directory) / 'scratch' / 'repo'
            root.mkdir(parents=True)
            subprocess.run(['git', 'init', '--quiet', str(root)], check=True, cwd=root, timeout=30)
            (root / 'README.md').write_text('# Entry\n[guide](guide.md)\n', encoding='utf-8')
            (root / 'guide.md').write_text('# Guide\n', encoding='utf-8')
            result = inspect_repository(root, audit_history=True, show_review=True)
            self.assertFalse(result['errors'])
            self.assertFalse(any('scratch evidence' in message for message in result['diagnostics']))

    def test_windows_path_examples_and_explicit_html_fragment(self):
        with tempfile.TemporaryDirectory(prefix='documentation_gate_test_') as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '--quiet', str(root)], check=True, cwd=root, timeout=30)
            (root / 'README.md').write_text('# Entry\n<a id="固定入口"></a>\n[here](#固定入口)\n[local](C:\\Users\\example\\file.md)\n`C:\\Users\\example`\n````md\n[missing](absent.md)\n```\n````', encoding='utf-8')
            self.assertFalse(inspect_repository(root, audit_history=True, show_review=True)['errors'])




class DocumentationRoutineCostTests(unittest.TestCase):
    def test_routine_links_do_not_authenticate_frozen_migrations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['git','init','--quiet',str(root)], cwd=root, check=True,
                           capture_output=True, timeout=30)
            (root/'README.md').write_text('# Active\n', encoding='utf-8')
            with patch('common.documentation_links.migrated_history', side_effect=AssertionError('unexpected provenance audit')):
                report = inspect_repository(root)
            self.assertEqual(report['errors'], [])
            self.assertEqual(report['diagnostics'], [])


if __name__ == '__main__':
    unittest.main()
