"""Package the isolated development workbench for Windows and Apple Silicon."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
from build_manju_public import prepare

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from manju_client import APP_VERSION, APP_NAME

def record(target,platform):
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(target.suffix+'.sha256').write_text(digest+'  '+target.name+'\n')
    return {'file':target.name,'platform':platform,'bytes':target.stat().st_size,'sha256':digest,
            'signed':False,'installerExecuted':False}

def windows(build,output):
    stage=ROOT/'work/manju-windows/ManjuWorkbench'
    if stage.exists():shutil.rmtree(stage)
    stage.mkdir(parents=True)
    # This payload was downloaded and verified by build_windows_local.py.
    source=ROOT/'work/windows-package/AssetLab'
    inventory=json.loads((source/'files-sha256.json').read_text())
    for path,digest in inventory.items():
        if path.startswith('runtime/'):
            assert hashlib.sha256((source/path).read_bytes()).hexdigest()==digest
    shutil.copytree(source/'runtime',stage/'runtime')
    for folder in ('public','server'):shutil.copytree(build/folder,stage/folder)
    (stage/'build-provenance.json').write_text(json.dumps({'product':'ManjuWorkbench','version':APP_VERSION,
        'sourceCommit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'customerDataIncluded':False,'automaticUpdates':False,'generationEnabled':False},indent=2))
    manifest={p.relative_to(stage).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in stage.rglob('*') if p.is_file()}
    (stage/'files-sha256.json').write_text(json.dumps(manifest,indent=2))
    nsi=(ROOT/'local_client/installer.nsi').read_text()
    nsi=nsi.replace('资产实验室',APP_NAME).replace('AssetLab','ManjuWorkbenchDev').replace('0.2.1.1','0.1.0.1')
    nsi=nsi.replace('Local\\ManjuWorkbenchDev.Workbench','Local\\ManjuWorkbench.Dev')
    nsi=nsi.replace('server/local_client/asset-lab.ico','server/manju_client/manju.ico')
    nsi=nsi.replace('server\\local_client\\launch.py','server\\manju_client\\launch.py')
    nsi=nsi.replace('server\\local_client\\asset-lab.ico','server\\manju_client\\manju.ico')
    nsi=nsi.replace('首次使用，点击“授权 LibTV”连接自己的账号。','进入后可选择剧本与资产、场景建模、人物白模或导演预演。')
    nsi=nsi.replace('当前为连接体验版，图像和视频生成暂未开放。','开发中测试版：部分模块尚未打通，图像、视频生成与自动更新暂未开放。')
    nsi=nsi.replace('连接自己的账号','试用现有功能').replace('开始连接你的账号','开始试用工作台')
    script=stage.parent/'installer.nsi';script.write_text(nsi)
    target=output/f'ManjuWorkbench-Setup-{APP_VERSION}-x64.exe'
    subprocess.run(['makensis','-V2',f'-DSTAGEDIR={stage}',f'-DOUTFILE={target}',f'-DAPPVERSION={APP_VERSION}',str(script)],check=True)
    return record(target,'windows-x64')

def mac(build,output):
    if sys.platform!='darwin' or os.uname().machine!='arm64':raise RuntimeError('Build on Apple Silicon')
    work=ROOT/'work/manju-macos';work.mkdir(parents=True,exist_ok=True)
    spec=work/'ManjuServer.spec'
    spec.write_text(f'''
from PyInstaller.utils.hooks import collect_submodules, collect_data_files
a=Analysis([{str(ROOT/'manju_client/mac_entry.py')!r}],pathex=[{str(ROOT)!r}],binaries=[],
 datas=[({str(build/'public')!r},'frontend'),({str(ROOT/'backend/generation/contracts/libtv-tools-public-2026-10-27.json')!r},'backend/generation/contracts')]+collect_data_files('certifi')+collect_data_files('jsonschema_specifications'),
 hiddenimports=collect_submodules('backend',filter=lambda n:not n.startswith('backend.legacy'))+['scripts.customer_entry'],excludes=['backend.legacy','tkinter'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='ManjuWorkbenchServer',debug=False,console=True,target_arch='arm64')
coll=COLLECT(exe,a.binaries,a.datas,name='ManjuWorkbenchServer')
''')
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--distpath',str(work/'frozen'),'--workpath',str(work/'analysis'),str(spec)],cwd=ROOT,check=True)
    payload=work/'payload'
    if payload.exists():shutil.rmtree(payload)
    app=payload/'Applications'/f'{APP_NAME}.app';contents=app/'Contents'
    (contents/'MacOS').mkdir(parents=True);(contents/'Resources').mkdir()
    shutil.copytree(work/'frozen/ManjuWorkbenchServer',contents/'Resources/runtime',symlinks=True)
    shutil.copyfile(ROOT/'manju_client/manju.icns',contents/'Resources/ManjuWorkbench.icns')
    native=work/'launcher.m';native.write_text((ROOT/'local_client/mac_launcher.m').read_text().replace('AssetLab','ManjuWorkbench').replace('资产实验室',APP_NAME))
    subprocess.run(['clang','-fobjc-arc','-arch','arm64','-mmacosx-version-min=11.0','-framework','Cocoa',str(native),'-o',str(contents/'MacOS/ManjuWorkbench')],check=True)
    info={'CFBundleName':APP_NAME,'CFBundleDisplayName':APP_NAME,'CFBundleExecutable':'ManjuWorkbench',
          'CFBundleIdentifier':'best.kk666.manju.dev','CFBundleIconFile':'ManjuWorkbench.icns','CFBundlePackageType':'APPL',
          'CFBundleShortVersionString':'0.1.0','CFBundleVersion':'0.1.0.1','LSMinimumSystemVersion':'11.0',
          'LSUIElement':True,'NSHighResolutionCapable':True,'NSHumanReadableCopyright':'温州氪客科技有限公司'}
    (contents/'Info.plist').write_bytes(plistlib.dumps(info))
    licenses=Path(sys.base_prefix)/'licenses'
    if licenses.exists():shutil.copytree(licenses,contents/'Resources/licenses')
    subprocess.run(['codesign','--force','--deep','--sign','-',str(app)],check=True)
    subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)
    scripts=work/'scripts';scripts.mkdir(exist_ok=True)
    post=scripts/'postinstall';post.write_text((ROOT/'local_client/macos-postinstall').read_text().replace('资产实验室',APP_NAME));post.chmod(0o755)
    component=work/'components.plist';subprocess.run(['pkgbuild','--analyze','--root',str(payload),str(component)],check=True)
    rows=plistlib.loads(component.read_bytes())
    for row in rows:row.update(BundleIsRelocatable=False,BundleIsVersionChecked=True,BundleOverwriteAction='upgrade')
    component.write_bytes(plistlib.dumps(rows))
    target=output/f'ManjuWorkbench-Setup-{APP_VERSION}-macOS-arm64.pkg'
    subprocess.run(['pkgbuild','--root',str(payload),'--component-plist',str(component),'--scripts',str(scripts),
        '--identifier','best.kk666.manju.dev','--version','0.1.0','--install-location','/','--ownership','recommended',str(target)],check=True)
    return record(target,'macos-arm64')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--platform',choices=['windows','mac','both'],default='both')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    build=prepare();results=[]
    if args.platform in ('windows','both'):results.append(windows(build,args.output))
    if args.platform in ('mac','both'):results.append(mac(build,args.output))
    report={'product':'ManjuWorkbench','version':APP_VERSION,'channel':'development','installers':results,
        'automaticUpdates':False,'paidGeneration':False,'macNotarized':False}
    (args.output/'manju-release.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))

if __name__=='__main__':main()
