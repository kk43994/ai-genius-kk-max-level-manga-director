#!/usr/bin/env python3
"""Retrieve bounded, source-addressable project knowledge without external calls."""
import argparse
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('query',nargs='?',default='')
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--limit',type=int,default=3)
    args=parser.parse_args()
    index=json.loads((ROOT/'docs/rag/index.json').read_text())
    hits=[]
    for entry in index['entries']:
        path=(ROOT/entry['file']).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise SystemExit('Invalid knowledge source: '+entry['file'])
        content=path.read_text();words=set(re.findall(r'[A-Za-z0-9_-]+|[\u4e00-\u9fff]+',args.query.lower()))
        score=sum(5 for term in entry['keywords'] if term.lower() in args.query.lower())
        score+=sum(content.lower().count(term) for term in words)
        if score:hits.append({'id':entry['id'],'source':entry['file'],'version':index['version'],
            'status':entry['status'],'score':score,'content':content[:7000]})
    if args.check:
        print(json.dumps({'valid':True,'version':index['version'],'sources':len(index['entries'])}));return
    hits.sort(key=lambda hit:(-hit['score'],hit['id']))
    print(json.dumps({'query':args.query,'retrieval':'local-keyword','matches':hits[:max(1,min(args.limit,5))]},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
