"""Test-only installed workspace lifetime; no child processes are started."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from common.contracts import test_installed_scientific_core as installed


class InstalledWorkspaceRetentionTests(unittest.TestCase):
    def test_success_removes_only_completed_owned_workspace(self):
        with tempfile.TemporaryDirectory() as parent:
            owned=Path(parent)/'owned';owned.mkdir();(owned/'installed-helper').write_text('fixture',encoding='utf8')
            with patch.object(installed.tempfile,'mkdtemp',return_value=str(owned)):
                with installed.retained_installed_workspace() as path:
                    self.assertEqual(path,owned)
                    self.assertTrue((path/'installed-helper').is_file())
            self.assertFalse(owned.exists())

    def test_failure_and_timeout_keep_tree_and_original_exception(self):
        for error in (RuntimeError('unknown writer fixture'), subprocess.TimeoutExpired(['inert-child'], 1)):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as parent:
                owned=Path(parent)/'owned';owned.mkdir();sentinel=owned/'installed-helper';sentinel.write_text('fixture',encoding='utf8')
                with patch.object(installed.tempfile,'mkdtemp',return_value=str(owned)), patch.object(installed.shutil,'rmtree',wraps=installed.shutil.rmtree) as remove:
                    with self.assertRaises(type(error)) as caught:
                        with installed.retained_installed_workspace(): raise error
                    self.assertIs(caught.exception,error)
                    remove.assert_not_called()
                self.assertEqual(sentinel.read_text(encoding='utf8'),'fixture')
