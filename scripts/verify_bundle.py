#!/usr/bin/env python3
"""Verify a committed source ZIP, then run its extracted HTTP service in isolation."""
import argparse
import hashlib
import http.client
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def verify(bundle):
    checksum=hashlib.sha256(bundle.read_bytes()).hexdigest()
    sidecar=bundle.with_suffix(bundle.suffix+'.sha256').read_text().split()[0]
    if checksum!=sidecar:raise ValueError('Archive checksum mismatch')
    with tempfile.TemporaryDirectory(dir=ROOT.parent/'work',prefix='verify-bundle-') as temporary:
        temp=Path(temporary)
        with zipfile.ZipFile(bundle) as archive:
            if archive.testzip():raise ValueError('ZIP CRC failed')
            if len(archive.namelist())!=len(set(archive.namelist())):raise ValueError('Duplicate ZIP entries')
            for info in archive.infolist():
                path=PurePosixPath(info.filename)
                if path.is_absolute() or '..' in path.parts or path.parts[0]!='asset-lab-customer':raise ValueError('Unsafe ZIP member')
                if (info.external_attr>>16)&0o170000 not in {0o100000,0}:raise ValueError('Non-regular ZIP member')
            manifest=json.loads(archive.read('asset-lab-customer/BUNDLE-MANIFEST.json'))
            for file in manifest['files']:
                if hashlib.sha256(archive.read('asset-lab-customer/'+file['path'])).hexdigest()!=file['sha256']:raise ValueError('File digest mismatch')
            archive.extractall(temp)
        source=temp/'asset-lab-customer';instance=temp/'instance'
        for required in ('backend/app.py','backend/integration_drafts.py','frontend/api-client.js','scripts/browser/bootstrap.mjs',
                         'scripts/build_customer.py','deploy/release.py','deploy/ssh-release.py',
                         'deploy/config/asset-lab-customer-preview.service.example','release-manifest.example.json'):
            if not (source/required).is_file():raise ValueError('Missing runtime/deployment file: '+required)
        if (source/'backend/legacy').exists():raise ValueError('Legacy engines included')
        subprocess.run([sys.executable,'scripts/init_local_instance.py','--directory',str(instance)],cwd=source,
                       capture_output=True,check=True,timeout=10)
        process=None
        def start(port=0):
            nonlocal process
            command=[sys.executable,'-m','backend.app','--port',str(port),'--public-base-path','/asset-lab/',
                '--data-dir',str(instance/'data'),'--secret-key-file',str(instance/'secrets/storage.key')]
            process=subprocess.Popen(command,cwd=source,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            first=process.stdout.readline().strip()
            if not first.startswith('Customer integration preview: '):raise ValueError('Extracted service failed to start')
            return urlsplit(first.split(': ',1)[1]).port
        def stop():
            nonlocal process
            if process is not None:
                process.terminate();process.communicate(timeout=10);process=None
        def request(path,method='GET',cookie=None,csrf=None,body=None):
            connection=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
            headers={}
            if cookie:headers['Cookie']=cookie
            if csrf:headers['X-CSRF-Token']=csrf
            if csrf:headers['X-Asset-Lab-Session']=session['session']['id']
            if method!='GET':headers['Origin']=f'http://127.0.0.1:{port}'
            if body is not None:headers['Content-Type']='application/json';body=json.dumps(body)
            connection.request(method,path,body,headers);response=connection.getresponse();raw=response.read()
            result=response.status,dict(response.getheaders()),json.loads(raw) if 'json' in response.getheader('Content-Type','') else raw
            connection.close();return result
        try:
            port=start();prefix='/asset-lab/api/v1'
            if request('/asset-lab/')[0]!=200:raise ValueError('Packaged HTML unavailable')
            if request('/asset-lab/_app/bootstrap.mjs')[0]!=200:raise ValueError('Packaged bootstrap unavailable')
            if request('/api/v1/session')[0]!=404:raise ValueError('Subpath leaked root API')
            status,headers,value=request(prefix+'/session');assert status==200
            cookie=headers['Set-Cookie'].split(';',1)[0];session=value['data'];csrf=session['csrfToken']
            status,_,value=request(prefix+'/projects','POST',cookie,csrf,{'name':'解包运行验收合成项目'})
            assert status==200;project=value['data']['id']
            content={'workflow':{'new-project':{'name':'解包重启草稿'}},'accountSelection':None}
            status,_,value=request(prefix+'/drafts/browser','PUT',cookie,csrf,{'expectedVersion':0,'content':content});assert status==200 and value['data']['saved']
            stop();port=start(port)
            assert request(prefix+'/projects/'+project,cookie=cookie)[0]==200
            assert request(prefix+'/drafts/browser',cookie=cookie)[2]['data']['content']==content
            assert request(prefix+'/session',cookie=cookie)[2]['data']['tenant']==session['tenant']
            assert request(prefix+'/provider-accounts/authorize','POST',cookie,csrf,{'provider':'libtv'})[0]==503
            assert request(prefix+'/tasks/synthetic/submit','POST',cookie,csrf,{})[0]==403
            assert request(prefix+'/ready')[2]['data']['customerReady'] is False
        finally:stop()
    return {'verified':True,'sourceCommit':manifest['sourceCommit'],'sha256':checksum,'files':len(manifest['files']),
            'zipCRC':True,'perFileSHA256':True,'extractedServiceStarted':True,'sessionProjectDraftRestart':True,
            'rootApiIsolated':True,'paidSubmissionBlocked':True,'officialAuthorizationAttempted':False,
            'publicDeployment':False,'scope':'Extracted source package with synthetic data and actual local HTTP/SQLite'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('bundle',type=Path);parser.add_argument('--output',type=Path);args=parser.parse_args()
    result=verify(args.bundle)
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
