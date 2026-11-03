import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('download_site', ROOT / 'scripts/build_download_site.py')
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)


def manifests():
    result = []
    for product, version in [('AssetLab', '0.3.0-preview.5'), ('ManjuWorkbench', '0.1.1-dev.1')]:
        rows = []
        for platform, suffix in [('windows-x64', 'x64.exe'), ('macos-arm64', 'macOS-arm64.pkg')]:
            row = {'platform': platform, 'bytes': 1000000, 'sha256': 'a' * 64}
            name = f'{product}-Setup-{version}-{suffix}'
            row['url' if product == 'AssetLab' else 'file'] = 'downloads/' + name if product == 'AssetLab' else name
            rows.append(row)
        result.append({'product': product, 'version': version, 'publishedDate': '2026-11-02', 'installers': rows})
    return result


class DownloadSiteTest(unittest.TestCase):
    def test_content_refresh_preserves_actual_download_version_and_manifest(self):
        public, legacy = manifests()
        original = json.dumps([public, legacy], sort_keys=True)
        fields = site.published_fields(public, legacy)
        self.assertEqual('0.3.0-preview.5', fields['VERSION'])
        self.assertEqual('AssetLab-Setup-0.3.0-preview.5-x64.exe', fields['FILE'])
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            site.render_site(fields, out)
            metadata = json.loads((out / 'site-content.json').read_text())
            self.assertEqual(site.APP_VERSION, metadata['sourceVersion'])
            self.assertEqual(public['version'], metadata['desktopVersion'])
            self.assertFalse((out / 'release.json').exists())
            self.assertFalse((out / 'downloads').exists())
            html = (out / 'index.html').read_text()
            self.assertNotIn('{{', html)
            self.assertIn('Lovart', html)
            self.assertIn('尚未接入', html)
            for name in ('style.css', 'release.js', 'stage.js', 'logo.svg'):
                digest = hashlib.sha256((out / 'assets' / name).read_bytes()).hexdigest()[:16]
                self.assertIn('assets/' + name + '?v=' + digest, html)
            self.assertNotIn('↗', html)
            self.assertTrue((out / 'assets/brands/kk-director.svg').is_file())
            # The preloaded picture and both rendering paths share one light asset.
            self.assertIn('href="assets/kk-director-hero.webp" type="image/webp"', html)
            hero = (out / 'assets/kk-director-hero.webp').read_bytes()
            self.assertEqual(hero[8:12], b'WEBP')
            self.assertLess(len(hero), 350000)
            self.assertNotIn('<image href="assets/kk-director-hero.png"', html)
            for name in ['style.css', 'release.js', 'stage.js', 'story-contact.png', 'brands/libtv.svg', 'brands/lovart.svg', 'brands/apple.svg', 'logo.svg', 'kk-director-hero.png', 'production-flow.png']:
                self.assertTrue((out / 'assets' / name).is_file())
        self.assertEqual(original, json.dumps([public, legacy], sort_keys=True))

    def test_content_refresh_refuses_untrusted_download_locations(self):
        for value in ['https://untrusted.invalid/installer.exe', '../installer.exe', 'downloads/wrong-version.exe']:
            public, legacy = manifests()
            public['installers'][0]['url'] = value
            with self.assertRaises(ValueError):
                site.published_fields(public, legacy)

    def test_content_refresh_requires_integrity_metadata_for_each_platform(self):
        for key, value in [('sha256', 'missing'), ('bytes', 0)]:
            public, legacy = manifests()
            public['installers'][1][key] = value
            with self.assertRaises(ValueError):
                site.published_fields(public, legacy)
