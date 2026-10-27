"""Build a clean local development workbench from audited prototype modules."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
from build_customer import build

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from manju_client import APP_VERSION

def prepare():
    build(ROOT/'.build','/workbench/','/workbench/api/v1')
    output=ROOT/'work/manju-build'
    if output.exists():shutil.rmtree(output)
    shutil.copytree(ROOT/'.build',output)
    public=output/'public'
    (public/'index.html').rename(public/'asset-workflow.html')
    html=(public/'asset-workflow.html').read_text()
    html=html.replace('资产实验室 · 创作工作台','漫剧工作台 · 剧本与资产')
    html=html.replace('href="#workspace-main"', 'href="asset-workflow.html#workspace-main"')
    html=html.replace('</body>','<a href="/workbench/" style="position:fixed;right:16px;bottom:50px;z-index:1000;background:#fff;color:#333;border:1px solid #aaa;padding:9px 12px;border-radius:6px;font-size:12px">← 漫剧工作台首页</a></body>')
    (public/'asset-workflow.html').write_text(html)
    shutil.copytree(ROOT/'manju_client/studio',public/'studio')
    for name in ('index.html','manju.css','manju.js'):
        shutil.copyfile(ROOT/'manju_client'/name,public/name)
    files={p.relative_to(public).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
           for p in sorted((public/'studio').rglob('*')) if p.is_file()}
    for name in ('index.html','manju.css','manju.js'):
        files[name]=hashlib.sha256((public/name).read_bytes()).hexdigest()
    (public/'studio-inventory.json').write_text(json.dumps({'version':APP_VERSION,'files':files},indent=2)+'\n')
    for package in ('local_client','manju_client'):
        folder=output/'server'/package;folder.mkdir()
        for name in ('__init__.py','launch.py'):
            shutil.copyfile(ROOT/package/name,folder/name)
    shutil.copyfile(ROOT/'manju_client/manju.ico',output/'server/manju_client/manju.ico')
    return output

if __name__=='__main__':print(prepare())
