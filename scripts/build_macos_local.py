#!/usr/bin/env python3
"""Build the Apple Silicon application and PKG desktop installer."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

from build_customer import build

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from local_client import APP_VERSION, APP_SHORT_VERSION, APP_BUNDLE_VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    if sys.platform != 'darwin' or os.uname().machine != 'arm64':
        raise RuntimeError('Build on an Apple Silicon Mac')
    build(ROOT/'.build', '/asset-lab/', '/asset-lab/api/v1')
    work = ROOT/'work/macos-package'
    work.mkdir(parents=True,exist_ok=True)
    spec = work/'AssetLabServer.spec'
    spec.write_text(f'''
from PyInstaller.utils.hooks import collect_submodules, collect_data_files
hidden = collect_submodules('backend', filter=lambda name: not name.startswith('backend.legacy'))
a = Analysis([{str(ROOT/'local_client/mac_entry.py')!r}], pathex=[{str(ROOT)!r}],
    binaries=[], datas=[({str(ROOT/'.build/public')!r},'frontend'),
    ({str(ROOT/'backend/generation/contracts')!r},'backend/generation/contracts')]
    + collect_data_files('certifi') + collect_data_files('jsonschema_specifications'),
    hiddenimports=hidden+['scripts.customer_entry'], excludes=['backend.legacy','tkinter'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz,a.scripts,[],exclude_binaries=True,name='AssetLabServer',debug=False,
    bootloader_ignore_signals=False,strip=False,upx=False,console=True,target_arch='arm64',codesign_identity=None)
coll = COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='AssetLabServer')
''')
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--distpath',str(work/'frozen'),
                    '--workpath',str(work/'analysis'),str(spec)],cwd=ROOT,check=True)
    payload = work/'payload'
    if payload.exists(): shutil.rmtree(payload)
    app = payload/'Applications/资产实验室.app'
    contents = app/'Contents'
    (contents/'MacOS').mkdir(parents=True)
    (contents/'Resources').mkdir()
    shutil.copytree(work/'frozen/AssetLabServer',contents/'Resources/runtime',symlinks=True)
    shutil.copyfile(ROOT/'local_client/asset-lab.icns',contents/'Resources/AssetLab.icns')
    subprocess.run(['clang','-fobjc-arc','-arch','arm64','-mmacosx-version-min=11.0','-framework','Cocoa',
                    str(ROOT/'local_client/mac_launcher.m'),'-o',str(contents/'MacOS/AssetLab')],check=True)
    info={'CFBundleName':'资产实验室','CFBundleDisplayName':'资产实验室','CFBundleExecutable':'AssetLab',
          'CFBundleIdentifier':'best.kk666.assetlab','CFBundleIconFile':'AssetLab.icns','CFBundlePackageType':'APPL',
          'CFBundleShortVersionString':APP_SHORT_VERSION,'CFBundleVersion':APP_BUNDLE_VERSION,'LSMinimumSystemVersion':'11.0',
          'LSUIElement':True,'NSHighResolutionCapable':True,'NSHumanReadableCopyright':'温州氪客科技有限公司'}
    (contents/'Info.plist').write_bytes(plistlib.dumps(info))
    (contents/'Resources/build-provenance.json').write_text(json.dumps({'product':'AssetLab','version':APP_VERSION,
        'sourceCommit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'customerDataIncluded':False,'uiTheme':'studio-neutral-dark','generationEnabledByDefault':False},indent=2),encoding='utf-8')
    license_root=Path(sys.base_prefix)/'licenses'
    if license_root.is_dir():shutil.copytree(license_root,contents/'Resources/licenses')
    subprocess.run(['codesign','--force','--deep','--sign','-',str(app)],check=True)
    subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)
    scripts=work/'installer-scripts';scripts.mkdir(exist_ok=True)
    shutil.copyfile(ROOT/'local_client/macos-postinstall',scripts/'postinstall')
    (scripts/'postinstall').chmod(0o755)
    component=work/'components.plist'
    subprocess.run(['pkgbuild','--analyze','--root',str(payload),str(component)],check=True)
    rows=plistlib.loads(component.read_bytes())
    for row in rows:
        row['BundleIsRelocatable']=False
        row['BundleIsVersionChecked']=True
        row['BundleOverwriteAction']='upgrade'
    component.write_bytes(plistlib.dumps(rows))
    args.output.mkdir(parents=True,exist_ok=True)
    target=args.output/f'AssetLab-Setup-{APP_VERSION}-macOS-arm64.pkg'
    subprocess.run(['pkgbuild','--root',str(payload),'--component-plist',str(component),'--scripts',str(scripts),
                    '--identifier','best.kk666.assetlab','--version',APP_BUNDLE_VERSION,'--install-location','/',
                    '--ownership','recommended',str(target)],check=True)
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix('.pkg.sha256').write_text(digest+'  '+target.name+'\n')
    print(json.dumps({'installer':str(target),'app':str(app),'bytes':target.stat().st_size,'sha256':digest,
                      'platform':'macOS-arm64','applicationSignature':'ad-hoc','developerIDSigned':False,
                      'notarized':False,'installerExecuted':False},ensure_ascii=False))


if __name__=='__main__':main()
