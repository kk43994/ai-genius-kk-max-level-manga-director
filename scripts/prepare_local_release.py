#!/usr/bin/env python3
"""Build and verify an isolated loopback release. Never SSH or touch a live host."""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from deploy import release
from backend.storage import SCHEMA_VERSION


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version',default='0.1.0-preview.1')
    parser.add_argument('--port',type=int,default=8892)
    parser.add_argument('--base-path',default='/asset-lab/')
    args=parser.parse_args()
    if args.port in {8768,8870}:parser.error('Reserved port')
    source=hashlib.sha256()
    for folder in ('backend','frontend','scripts'):
        for path in sorted((ROOT/folder).rglob('*')):
            if path.is_file() and path.suffix in {'.py','.mjs','.js','.css','.html'} and 'legacy' not in path.parts:
                source.update(path.relative_to(ROOT).as_posix().encode());source.update(path.read_bytes())
    build_id='integration-'+source.hexdigest()[:16]
    work=ROOT.parent/'work/release-preview';work.mkdir(parents=True,exist_ok=True)
    bundle=work/(args.version+'--'+build_id+'.tar.gz')
    spec={'schemaVersion':1,'sourceDir':str(ROOT),
          'include':{'public':'.build/public','server':'.build/server'},
          'buildCommand':[sys.executable,'scripts/build_customer.py','--public-base-path',args.base_path],
          'testCommand':[sys.executable,'-m','unittest','discover','-s','tests/integration','-q'],
          'release':{'schemaVersion':1,'product':'asset-lab-customer','channel':'preview',
            'version':args.version,'buildId':build_id,'publishedAt':datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'apiVersion':1,'dataSchemaVersion':SCHEMA_VERSION,'minCompatibleClient':'0.1.0-preview.1',
            'releaseNotes':['客户版集成预览：项目、草稿、账号面板、任务归属及版本更新接线。','真实图片适配与公网授权仍须独立验收；收费提交和视频保持关闭。'],
            'reloadRequired':True,'entryUrl':args.base_path,'integrity':{'algorithm':'sha256','value':None}},
          'origin':f'http://127.0.0.1:{args.port}','basePath':args.base_path}
    spec_path=work/(args.version+'--'+build_id+'.build-spec.json');spec_path.write_text(json.dumps(spec,ensure_ascii=False,indent=2))
    release.build_bundle(spec_path,bundle)
    runtime=work/'runtime';candidate=runtime/'releases'/release.release_id(spec['release'])
    candidate.mkdir(parents=True,exist_ok=False)
    checksum=release.digest_file(bundle)
    release.extract_bundle(bundle,checksum,candidate)
    manifest=release.verify_directory(candidate,spec['origin'],args.base_path)
    # A local channel is reviewable metadata, not a public deployment.
    channel=runtime/'channels/preview';channel.mkdir(parents=True,exist_ok=True)
    release.atomic_link(channel/'current',candidate)
    report={'bundle':str(bundle),'sha256':checksum,'releaseDirectory':str(candidate),
            'releaseRoot':str(runtime),'verified':True,'sourceDigest':source.hexdigest(),
            'scope':'isolated loopback preview; not public deployment or official generation acceptance'}
    (work/'latest-local-build.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
