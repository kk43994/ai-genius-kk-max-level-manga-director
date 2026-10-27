#!/usr/bin/env python3
"""Build data-free public/server trees for deploy/release.py's signed inventory."""
import argparse
import shutil
from pathlib import Path

from customer_entry import entry_html

ROOT = Path(__file__).resolve().parents[1]


def build(output, base, api):
    if output.resolve().parent != ROOT or output.name != '.build':
        raise ValueError('Build destination must be this clone\'s .build directory')
    if output.is_symlink():
        raise ValueError('Build destination cannot be a symlink')
    from sys import path
    path.insert(0,str(ROOT))
    from backend.app import normalize_path
    base = normalize_path(base, trailing=True); api = normalize_path(api or base + 'api/v1')
    if output.exists(): shutil.rmtree(output)
    public, server = output / 'public', output / 'server'
    public.mkdir(parents=True); server.mkdir()
    for source in sorted((ROOT/'frontend').rglob('*')):
        if source.is_symlink(): raise ValueError('Frontend cannot contain symlinks')
        if source.is_file() and source.suffix in {'.html','.js','.mjs','.css','.svg','.png','.jpg','.webp','.ico','.woff2'}:
            dest=public/source.relative_to(ROOT/'frontend');dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
    shutil.copytree(ROOT/'scripts/browser',public/'_app')
    html=entry_html((public/'asset-lab.html').read_text(),{'publicBasePath':base,'apiBase':api,'apiVersion':1,'mode':'customer-preview'})
    (public/'index.html').write_text(html)
    # Every document entry must use the same immutable build stamp added later.
    (public/'asset-lab.html').unlink()
    for source in sorted((ROOT/'backend').rglob('*.py')):
        if 'legacy' in source.relative_to(ROOT).parts: continue
        if source.is_symlink(): raise ValueError('Backend cannot contain symlinks')
        dest=server/source.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
    # ToolCatalog.bundled reads this public schema at runtime; Python-only copies fail startup.
    for relative in ('backend/generation/contracts/libtv-tools-public-2026-10-27.json',):
        source=ROOT/relative
        if source.is_symlink():raise ValueError('Runtime schema cannot be a symlink')
        dest=server/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
    (server/'scripts').mkdir()
    for name in ('customer_entry.py','init_local_instance.py'):
        shutil.copyfile(ROOT/'scripts'/name,server/'scripts'/name)
    shutil.copyfile(ROOT/'requirements.txt',server/'requirements.txt')
    return {'public':str(public),'server':str(server),'publicBasePath':base,'apiBase':api}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-base-path',default='/asset-lab/')
    parser.add_argument('--api-base')
    args=parser.parse_args()
    import json
    print(json.dumps(build(ROOT/'.build',args.public_base_path,args.api_base)))


if __name__=='__main__': main()
