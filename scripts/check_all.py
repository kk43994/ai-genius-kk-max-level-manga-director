#!/usr/bin/env python3
"""Run pure module/integration suites in separate processes to avoid import collisions."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path);args=parser.parse_args()
    report={'observedAt':datetime.now(timezone.utc).isoformat(),'scope':'Actual local storage/HTTP and synthetic provider contracts; no paid requests, real credentials or remote deployment',
            'suites':[],'paidSubmissionAttempted':False,'realAuthorizationAttempted':False}
    commands=[(name,[sys.executable,'-m','unittest','discover','-s','tests/'+name,'-q']) for name in ('storage','auth','spaces','tasks','workflow','releases','integration')]
    commands.append(('frontend-models',['node','--test','tests/ui/api-client.test.mjs','tests/accounts-ui/state.test.mjs','tests/accounts-ui/owner-state.test.mjs','tests/workflow/test_model.mjs','tests/releases/version.test.mjs','tests/integration/drafts.test.mjs','tests/integration/session-boundary.test.mjs']))
    for name,command in commands:
        result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=90)
        output=result.stdout+result.stderr
        count=re.search(r'Ran (\d+) tests',output) or re.search(r'tests (\d+)',output)
        report['suites'].append({'suite':name,'exitCode':result.returncode,'tests':int(count[1]) if count else None,'output':output})
        print(f'{name}: exit={result.returncode}, tests={count[1] if count else "unknown"}',flush=True)
        if result.returncode:print(output,flush=True)
    report['success']=all(item['exitCode']==0 for item in report['suites'])
    report['testsRun']=sum(item['tests'] or 0 for item in report['suites'])
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return 0 if report['success'] else 1


if __name__=='__main__':raise SystemExit(main())
