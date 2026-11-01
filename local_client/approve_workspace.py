"""Trusted local operator approval for one browser-requested workspace switch.

This command requires OS access to the same protected instance and an explicit
request and target project. It never prints session cookies or provider secrets.
"""
import argparse
import json
from pathlib import Path

from backend.app import Config, create_app


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instance',required=True,type=Path)
    parser.add_argument('--port',type=int,default=18874)
    parser.add_argument('--request',required=True)
    parser.add_argument('--project',required=True)
    args=parser.parse_args()
    instance=args.instance.resolve()
    if not (instance/'data/state.sqlite3').is_file():
        parser.error('An existing local workspace instance is required')
    app=create_app(Config(instance/'data',port=args.port,public_base_path='/asset-lab/',
        secret_key_file=instance/'secrets/storage.key',local_client=True))
    value=app.services.local_workspace.approve_from_local_operator(args.request,args.project)
    print(json.dumps({'status':value['status'],'projectName':value['projectName']},ensure_ascii=False))


if __name__=='__main__':main()
