"""Synthetic installers only; no real download, installation or process exit."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from local_client.updater import DesktopUpdater, FEED, installer_record, version_key
from local_client.install_update import main as install_helper
from local_client import launch


class DesktopUpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.binary = b'synthetic installer, never executed'
        self.manifest = {'product': 'AssetLab', 'version': '0.3.0-preview.5', 'channel': 'preview',
            'installers': [{'platform': 'macos-arm64', 'url': 'downloads/AssetLab-test.pkg',
                            'bytes': len(self.binary), 'sha256': hashlib.sha256(self.binary).hexdigest()}]}
        self.calls = []
        self.updater = DesktopUpdater(self.root, '0.3.0-preview.4', target='macos-arm64', reader=self.reader)

    def reader(self, url, limit, sink=None):
        self.calls.append(url)
        if sink:
            sink.write(self.binary)
            return len(self.binary)
        self.assertEqual(url, FEED)
        return json.dumps(self.manifest).encode()

    def test_newer_download_is_verified_reused_and_source_run_cannot_install(self):
        sentinel = self.root / 'project.txt'; sentinel.write_text('keep')
        self.updater._check()
        self.assertEqual(self.updater.snapshot()['status'], 'ready')
        self.assertFalse(self.updater.snapshot()['canInstall'])
        self.updater._check()
        self.assertEqual(len(self.calls), 3)  # two manifests, one binary
        self.assertEqual(sentinel.read_text(), 'keep')
        with patch('subprocess.Popen') as launch, self.assertRaises(ValueError):
            self.updater.install()
        launch.assert_not_called()

    def test_old_or_equal_releases_never_download_or_downgrade(self):
        for version in ('0.2.3-preview.1', '0.3.0-preview.4'):
            self.manifest['version'] = version
            self.updater._check()
            self.assertEqual(self.updater.snapshot()['status'], 'current')
        self.assertEqual(self.calls, [FEED, FEED])
        self.assertGreater(version_key('0.3.0'), version_key('0.3.0-rc.99'))

    def test_unsafe_source_wrong_product_and_wrong_platform_fail_closed(self):
        for url in ('https://evil.test/update.pkg', '//evil.test/update.pkg', 'downloads/../evil.pkg',
                    'downloads/thing.pkg?token=bad', 'downloads/%2e%2e/thing.pkg', 'downloads/thing.exe'):
            manifest = copy.deepcopy(self.manifest); manifest['installers'][0]['url'] = url
            with self.subTest(url=url), self.assertRaises(ValueError):
                installer_record(manifest, 'macos-arm64')
        self.manifest['product'] = 'ManjuWorkbench'
        self.updater._check()
        self.assertEqual(self.updater.snapshot()['status'], 'error')
        self.assertEqual(self.calls, [FEED])

    def test_tampered_download_is_removed_and_never_installable(self):
        self.manifest['installers'][0]['sha256'] = '0' * 64
        self.updater._check()
        self.assertEqual(self.updater.snapshot()['status'], 'error')
        self.assertFalse(list((self.root / 'updates').glob('*.part')))
        self.assertFalse(list((self.root / 'updates').glob('*.pkg')))

    def test_install_rechecks_bytes_and_starts_only_detached_helper(self):
        self.updater.packaged = True
        self.updater._check()
        self.updater.path.write_bytes(b'tampered')
        with patch('subprocess.Popen') as launch, self.assertRaises(ValueError):
            self.updater.install()
        launch.assert_not_called()
        self.updater.path.write_bytes(self.binary)
        with patch('subprocess.Popen') as launch:
            self.updater.install()
        self.assertIn('--install-update-helper', launch.call_args.args[0])
        self.assertEqual(self.updater.snapshot()['status'], 'installing')

    def test_disabling_auto_update_persists_and_helper_waits_for_exit(self):
        self.updater.set_enabled(False)
        other = DesktopUpdater(self.root, '0.3.0-preview.4', target='macos-arm64', reader=self.reader)
        self.assertFalse(other.snapshot()['enabled'])
        self.updater._check()
        row = self.updater.row
        args = ['1234', str(self.updater.path), row['sha256'], str(row['bytes']), row['version'], 'macos-arm64']
        with patch('local_client.install_update.wait_for_exit', return_value=False), patch('subprocess.run') as run:
            self.assertEqual(install_helper(args), 3)
        run.assert_not_called()

    def test_packaged_entry_enables_user_confirmed_images_without_a_cli_flag(self):
        for packaged in (False, True):
            with self.subTest(packaged=packaged), patch.object(launch.sys, 'frozen', packaged, create=True), \
                    patch.object(launch.sys, 'argv', ['launcher', '--instance', str(self.root), '--no-browser']), \
                    patch.object(launch, 'SERVER', self.root / 'server'), patch.object(launch, 'run', return_value=0) as run:
                self.assertEqual(launch.main(), 0)
                self.assertEqual(run.call_args.kwargs['enable_images'], packaged)
