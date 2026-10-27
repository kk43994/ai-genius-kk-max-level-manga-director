#!/usr/bin/env python3
"""Build two clearly-labelled synthetic releases for local browser inspection."""
import argparse
import json
from pathlib import Path
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from deploy import release


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',required=True);p.add_argument('--public-base-path',default='/asset-lab/');a=p.parse_args()
    directory=Path(a.directory).resolve()
    if directory.exists():p.error('Use a new empty demo directory')
    source=directory/'source';(source/'public').mkdir(parents=True)
    repo=Path(__file__).resolve().parents[1]
    shutil.copyfile(repo/'deploy/examples/demo.html',source/'public/index.html')
    shutil.copytree(repo/'frontend/updates',source/'public/updates')
    for number,build in [(0,'demo-first'),(1,'demo-second')]:
        manifest={'schemaVersion':1,'product':'asset-lab-customer','channel':'preview','version':f'0.1.{number}-preview.1','buildId':build,'publishedAt':release.now(),
                  'apiVersion':1,'dataSchemaVersion':1,'minCompatibleClient':'0.1.0-preview.1','releaseNotes':['仅供本地合成验收。','检查草稿保存、任务保护与显式刷新。'],'reloadRequired':True,'entryUrl':a.public_base_path,'integrity':{'algorithm':'sha256','value':None}}
        spec={'schemaVersion':1,'sourceDir':str(source),'include':{'public':'public'},'buildCommand':['node','--check','public/updates/version-checker.mjs'],
              'testCommand':['node','--test',str(repo/'tests/releases/version.test.mjs')],'release':manifest,'origin':'http://127.0.0.1','basePath':a.public_base_path}
        specfile=directory/(build+'.json');specfile.write_text(json.dumps(spec));output=directory/(build+'.tar.gz')
        result=release.build_bundle(specfile,output)
        if number==0:
            release.install(argparse.Namespace(root=str(directory/'runtime'),data_root=str(directory/'data'),channel='preview',origin='http://127.0.0.1',base_path=a.public_base_path,
                        bundle=str(output),sha256=result['sha256'],allow_stable=False,hooks=None))
    print(json.dumps({'directory':str(directory),'runtime':str(directory/'runtime'),'publicBasePath':a.public_base_path,'nextBundle':str(directory/'demo-second.tar.gz')},indent=2))

if __name__=='__main__':main()
