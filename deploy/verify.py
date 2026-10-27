#!/usr/bin/env python3
"""Run local release-only verification and save a credential-free evidence record."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'deploy/evidence'

def source_hash():
    digest=hashlib.sha256()
    for directory in ['deploy','backend/releases','frontend/updates','tests/releases']:
        for p in sorted((ROOT/directory).rglob('*')):
            if not p.is_file() or 'evidence' in p.parts or '__pycache__' in p.parts or p.suffix not in ('.py','.js','.mjs','.json','.conf','.example'):continue
            digest.update(p.relative_to(ROOT).as_posix().encode()+b'\0'+p.read_bytes()+b'\0')
    return digest.hexdigest()

def main():
    OUT.mkdir(exist_ok=True)
    before=source_hash()
    results=[]
    for name,command in [('browser-logic',['node','--test','--test-reporter=tap','tests/releases/version.test.mjs']),
                         ('release-and-http',[sys.executable,'-m','unittest','discover','-s','tests/releases','-p','test_*.py','-v'])]:
        result=subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        (OUT/(name+'.log')).write_text(result.stdout)
        match=re.search(r'# tests (\d+)|Ran (\d+) tests',result.stdout)
        results.append({'name':name,'exitCode':result.returncode,'tests':int(next(x for x in match.groups() if x)) if match else None,'log':name+'.log'})
    report={'checkedAt':dt.datetime.now(dt.timezone.utc).isoformat(),'scope':'synthetic local fixtures; no provider calls, paid generation, remote writes or public deployment',
            'sourceSha256':before,'sourceUnchangedDuringVerification':before==source_hash(),'results':results,
            'allPassed':all(x['exitCode']==0 for x in results)}
    (OUT/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['allPassed'] and report['sourceUnchangedDuringVerification'] else 1

if __name__=='__main__':sys.exit(main())
