#!/usr/bin/env python3
"""Retrieve bounded, source-addressable project knowledge without external calls."""
import argparse
import json
import re
from pathlib import Path
from check_update_history import load_updates, check_indexes

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('query',nargs='?',default='')
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--limit',type=int,default=3)
    parser.add_argument('--updates',action='store_true',help='Search individual upgrades, or list the latest records')
    parser.add_argument('--version',help='Filter upgrade records by their actual source version')
    args=parser.parse_args()
    index=json.loads((ROOT/'docs/rag/index.json').read_text())
    updates=load_updates(ROOT)
    entries=[] if args.updates else list(index['entries'])
    entries.extend({'id':'update-'+r['id'],'file':r['file'],'keywords':[r['title'],r['version'],r['date'][:10],*r['commits']],
                    'status':r['releaseState'],'version':r['version'],'date':r['date']} for r in updates
                   if not args.version or r['version']==args.version)
    if len({e['id'] for e in entries})!=len(entries) or len({e['file'] for e in entries})!=len(entries):
        raise SystemExit('Duplicate knowledge source ID or path')
    hits=[]
    for entry in entries:
        path=(ROOT/entry['file']).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise SystemExit('Invalid knowledge source: '+entry['file'])
        content=path.read_text();words=set(re.findall(r'[A-Za-z0-9_-]+|[\u4e00-\u9fff]+',args.query.lower()))
        score=sum(5 for term in entry['keywords'] if term.lower() in args.query.lower())
        score+=sum(content.lower().count(term) for term in words)
        if score or (args.updates and not args.query):hits.append({'id':entry['id'],'source':entry['file'],'version':entry.get('version',index['version']),
            'status':entry['status'],'score':score,'date':entry.get('date',''),'content':content[:7000]})
    if args.check:
        check_indexes(ROOT,updates)
        application=(ROOT/'local_client/__init__.py').read_text()
        version=re.search(r'^APP_VERSION\s*=\s*[\"\']([^\"\']+)',application,re.M)
        if not version or version[1]!=index['version']:
            raise SystemExit('Knowledge version does not match APP_VERSION')
        if index['version'] not in (ROOT/'CHANGELOG.md').read_text() or not (ROOT/'docs/versions'/f"{index['version']}.md").is_file():
            raise SystemExit('Missing matching changelog or version record')
        print(json.dumps({'valid':True,'version':index['version'],'sources':len(index['entries']),'updateRecords':len(updates),'applicationVersionMatches':True}));return
    hits.sort(key=lambda hit:(hit['date'],hit['id']),reverse=True)
    if args.query:hits.sort(key=lambda hit:-hit['score'])
    print(json.dumps({'query':args.query,'retrieval':'local-keyword','matches':hits[:max(1,min(args.limit,20 if args.updates else 5))]},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
