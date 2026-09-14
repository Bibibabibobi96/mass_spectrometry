"""Focused regressions for documentation navigation and frozen history boundaries."""

from pathlib import Path
import subprocess
import tempfile
import unittest

from common.documentation_links import anchors, inspect_repository, is_history, links, table_diagnostics


class MarkdownNavigationTests(unittest.TestCase):
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
            result = inspect_repository(root)
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
            result = inspect_repository(root)
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
            result = inspect_repository(root)
            self.assertEqual(len(result['errors']), 1)

    def test_external_artifacts_are_optional_and_scratch_is_reported(self):
        with tempfile.TemporaryDirectory(prefix='documentation_gate_test_') as directory:
            root = Path(directory) / 'repo'
            root.mkdir()
            subprocess.run(['git', 'init', '--quiet', str(root)], check=True, cwd=root, timeout=30)
            (root / 'README.md').write_text('# Entry\n[evidence](../artifacts/projects/p/scratch/x/report.json)', encoding='utf-8')
            result = inspect_repository(root)
            self.assertFalse(result['errors'])
            self.assertTrue(any('scratch evidence' in message for message in result['diagnostics']))

    def test_windows_path_examples_and_explicit_html_fragment(self):
        with tempfile.TemporaryDirectory(prefix='documentation_gate_test_') as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '--quiet', str(root)], check=True, cwd=root, timeout=30)
            (root / 'README.md').write_text('# Entry\n<a id="固定入口"></a>\n[here](#固定入口)\n[local](C:\\Users\\example\\file.md)\n`C:\\Users\\example`\n````md\n[missing](absent.md)\n```\n````', encoding='utf-8')
            self.assertFalse(inspect_repository(root)['errors'])


if __name__ == '__main__':
    unittest.main()
