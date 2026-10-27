#!/usr/bin/env python3
"""Render the public download page from the exact installer being published."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from local_client import APP_VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer', type=Path, required=True)
    parser.add_argument('--mac-installer', type=Path, required=True)
    parser.add_argument('--mac-verification', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    name = f'AssetLab-Setup-{APP_VERSION}-x64.exe'
    if args.installer.name != name:
        raise ValueError('Installer version does not match source')
    digest = hashlib.sha256(args.installer.read_bytes()).hexdigest()
    if args.installer.with_suffix('.exe.sha256').read_text().split()[0] != digest:
        raise ValueError('Installer checksum mismatch')
    mac_name = f'AssetLab-Setup-{APP_VERSION}-macOS-arm64.pkg'
    if args.mac_installer.name != mac_name:
        raise ValueError('Mac installer version does not match source')
    mac_digest = hashlib.sha256(args.mac_installer.read_bytes()).hexdigest()
    if args.mac_installer.with_suffix('.pkg.sha256').read_text().split()[0] != mac_digest:
        raise ValueError('Mac installer checksum mismatch')
    verification = json.loads(args.mac_verification.read_text())
    if (verification.get('version') != APP_VERSION or not verification.get('packagedLaunchPassed')
            or verification.get('installerSha256') != mac_digest):
        raise ValueError('Mac packaged launch has not been verified for this version')
    source = ROOT / 'local_client/website'
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out/'assets').mkdir(exist_ok=True)
    (out/'downloads').mkdir(exist_ok=True)
    fields = {'VERSION': APP_VERSION, 'FILE': name, 'SIZE': f'{args.installer.stat().st_size / 1_000_000:.1f}',
              'DATE': '2026.10.27', 'SHA': digest, 'MAC_FILE': mac_name, 'MAC_SHA': mac_digest,
              'MAC_SIZE': f'{args.mac_installer.stat().st_size / 1_000_000:.1f}',
              'MAC_STATUS': 'Mac 应用已通过独立启动与重复打开验证，系统安装流程仍待验收。'}
    html = (source/'index.template.html').read_text()
    for key, value in fields.items():
        html = html.replace('{{'+key+'}}', value)
    if '{{' in html:
        raise ValueError('Unresolved page template field')
    (out/'index.html').write_text(html)
    for file in ('style.css', 'release.js', 'logo.svg'):
        shutil.copyfile(source/file, out/'assets'/file)
    shutil.copyfile(args.installer, out/'downloads'/name)
    shutil.copyfile(args.installer.with_suffix('.exe.sha256'), out/'downloads'/(name+'.sha256'))
    shutil.copyfile(args.mac_installer, out/'downloads'/mac_name)
    shutil.copyfile(args.mac_installer.with_suffix('.pkg.sha256'), out/'downloads'/(mac_name+'.sha256'))
    manifest = {'product':'AssetLab', 'version':APP_VERSION, 'channel':'preview', 'publishedDate':'2026-10-27',
                'installers':[{'url':'downloads/'+name, 'bytes':args.installer.stat().st_size, 'sha256':digest,
                               'platform':'windows-x64', 'signed':False},
                              {'url':'downloads/'+mac_name, 'bytes':args.mac_installer.stat().st_size,
                               'sha256':mac_digest, 'platform':'macos-arm64',
                               'developerIDSigned':False, 'notarized':False}],
                'macPackagedLaunchVerified':True, 'macInstallerExecuted':False,
                'windowsInstallVerified':False, 'automaticUpdates':False}
    (out/'release.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    notes = f'''资产实验室 {APP_VERSION} · 连接体验版
发布日期：2026 年 10 月 27 日

提供 Mac（Apple 芯片）与 Windows（x64）安装程序，安装时自动创建桌面快捷方式。
Mac 安装到“应用程序”；Windows 另提供开始菜单入口。
双击桌面“资产实验室”图标，自动启动本机工作台并打开浏览器。
点击“授权 LibTV”，在官方页面登录并允许，完成后自动连接账号，读取个人及团队空间。
项目和账号连接保存在本机，正常退出后可再次打开。卸载程序保留这些资料。

安装步骤
1. 下载电脑对应的安装版，打开安装程序。
2. 按系统提示安装，完成后从桌面打开工作台。
3. 以后双击桌面图标即可使用。首次使用请连接自己的 LibTV 账号。

当前版本范围
仅开放账号连接与空间选择，图像、视频生成和自动安装更新暂未开放。
真实官方只读授权与重启恢复已在开发机验证；Mac 独立应用启动、重复打开和资料保留已验证。
Mac 系统安装流程及 Windows 安装、快捷方式和权限保护仍待实机验收。
Mac 版适用于 Apple 芯片（M 系列）和 macOS 11 及以上，暂不提供 Intel Mac 版。
Windows 版适用于 64 位 Windows 10 / 11。
Windows 安装包尚未代码签名，Mac 安装包未完成 Developer ID 签名与 Apple 公证。
如系统阻止安装，请联系交付人员核对来源，不要关闭系统安全防护。

版本与下载地址：https://kk666.best/asset-lab/
Mac SHA-256：{mac_digest}
Windows SHA-256：{digest}
'''
    (out/'release-notes.txt').write_text(notes,encoding='utf-8-sig')
    print(json.dumps({'site':str(out),'installers':[name,mac_name],'version':APP_VERSION},ensure_ascii=False))


if __name__ == '__main__':
    main()
