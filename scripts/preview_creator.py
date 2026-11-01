#!/usr/bin/env python3
"""Loopback-only disposable UI preview. Synthetic data, no provider submission."""
import argparse
import io
import json
import sys
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlsplit, parse_qs
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests/analysis')]
from test_production import ProductionTests
from backend.workflow.errors import WorkflowError

fixture=ProductionTests();fixture.setUp()
w,ctx=fixture.workflow,fixture.ctx
w.tasks=fixture.services.tasks
job=fixture.finish()
candidate=fixture.production.candidate(ctx,job['id'])
candidate['entities'].append({'id':'legacy_demo_bookstore','category':'scene','name':'书店','description':'以前制作的场景档案','origin':'manual'})
w.save_plan(ctx,fixture.project['id'],{k:candidate[k] for k in ('expectedVersion','entities','stylePrompt')})
for i,entity in enumerate(w.get_plan(ctx,fixture.project['id'])['entities']):
    for version in range(2):
        picture=Image.new('RGB',(600,600),('#ddd7cb','#c7d2db')[version]);draw=ImageDraw.Draw(picture)
        draw.rounded_rectangle((135,150,465,500),radius=30,fill=('#7b91a1','#997969','#778f75','#a29471')[i%4])
        draw.ellipse((230,55,370,195),fill='#e1bfa8');draw.text((20,20),f'SYNTHETIC / {entity["category"]} / {version+1}',fill='#303030')
        raw=io.BytesIO();picture.save(raw,format='PNG')
        spec=w.build_spec(ctx,{'projectId':fixture.project['id'],'entityId':entity['id'],'recipe':'mj_style','prompt':'仅用于 UI 验收的合成素材','sourceRevisionIds':[],'settings':{}},fixture.owner)
        revision=w.record_output(ctx,{**spec,'id':f'demo-{i}-{version}','status':'downloading','ownership':fixture.owner},raw.getvalue())
        if version==0:
            asset=next(a for a in w.list_assets(ctx,fixture.project['id'])['items'] if a['id']==revision['assetId'])
            w.review(ctx,asset['id'],{'revisionId':revision['id'],'sha256':revision['sha256'],'decision':'approved','note':'合成测试预置选择','expectedVersion':asset['version']})
            spec=w.build_spec(ctx,{'projectId':fixture.project['id'],'entityId':entity['id'],'recipe':'image2_asset','prompt':'合成规范资产占位图','sourceRevisionIds':[revision['id']],'settings':{}},fixture.owner)
            generated=w.record_output(ctx,{**spec,'id':f'demo-asset-{i}','status':'downloading','ownership':fixture.owner},raw.getvalue())
            asset=next(a for a in w.list_assets(ctx,fixture.project['id'])['items'] if a['id']==revision['assetId'])
            w.review(ctx,asset['id'],{'revisionId':generated['id'],'sha256':generated['sha256'],'decision':'approved','note':'合成测试预置选择','expectedVersion':asset['version']})

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT),**kwargs)
    def log_message(self,*args):pass
    def answer(self,value,status=200,mime='application/json'):
        raw=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        path=urlsplit(self.path)
        if path.path=='/':return self.answer((ROOT/'tests/workflow/creator-preview.html').read_bytes(),mime='text/html; charset=utf-8')
        if path.path=='/demo-init':return self.answer({'session':{'tenant':{'id':ctx.tenantId},'selection':{**fixture.selected,**{k:v for k,v in fixture.owner.items() if k!='tenantId'}},'features':{'imageGeneration':False}}})
        if path.path.startswith('/demo-api'):return self.dispatch('GET',path.path[9:],parse_qs(path.query),{})
        if not path.path.startswith(('/frontend/','/tests/workflow/creator-preview.mjs')):return self.answer({'message':'Not found'},404)
        return super().do_GET()
    def do_POST(self):self.write_request('POST')
    def do_PUT(self):self.write_request('PUT')
    def write_request(self,method):
        try:body=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
        except Exception:return self.answer({'message':'Invalid request'},400)
        path=urlsplit(self.path).path
        if not path.startswith('/demo-api/'):return self.answer({'message':'Not found'},404)
        self.dispatch(method,path[9:],{},body)
    def dispatch(self,method,path,query,body):
        try:
            parts=path.strip('/').split('/');pid=fixture.project['id']
            if path=='/workflow/capabilities':return self.answer({'scriptAnalysis':True,'analysis':{'models':[{'id':'synthetic','name':'合成测试模型'}],'defaultModelId':'synthetic'}})
            if path=='/projects':return self.answer(w.list_projects(ctx))
            if path=='/tasks':return self.answer({'items':[]})
            if parts[0]=='projects' and parts[1]==pid:
                if len(parts)==2:return self.answer(w.get_project(ctx,pid))
                kind=parts[-1]
                if kind=='plan':return self.answer(w.save_plan(ctx,pid,body) if method=='PUT' else w.get_plan(ctx,pid))
                if kind=='assets':return self.answer(w.list_assets(ctx,pid))
                if kind=='prompts':return self.answer({'items':[]})
                if kind=='bundles':return self.answer(w.archive(ctx,pid,body) if method=='POST' else w.list_bundles(ctx,pid))
                if kind=='export':return self.answer(w.export(ctx,pid)[0],mime='application/zip')
                if len(parts)==5 and parts[2]=='bundles' and kind=='content':return self.answer(w.bundle_content(ctx,pid,parts[3]),mime='application/zip')
                if kind=='art-direction':return self.answer(w.confirm_art_direction(ctx,pid,body))
                if kind=='analysis':return self.answer({'analysis':fixture.analysis})
                if kind=='production':return self.answer({'analysis':fixture.production.get(ctx,job['id'])})
                if parts[2]=='scripts':return self.answer(w.get_script(ctx,pid,parts[3]))
            if parts[0]=='production-jobs' and parts[1]==job['id']:
                if parts[-1]=='review':return self.answer(fixture.production.save_review(ctx,job['id'],body))
                if parts[-1]=='bindings':return self.answer(fixture.production.save_binding(ctx,job['id'],body))
                if parts[-1]=='references':return self.answer(fixture.production.reference_packet(ctx,job['id'],parts[-2]))
            if parts[0]=='assets':
                if parts[-1]=='reviews':return self.answer(w.review(ctx,parts[1],body))
                if parts[-1] in ('thumbnail','content'):
                    raw,mime=w.content(ctx,parts[1],query.get('revisionId',[''])[0],thumbnail=parts[-1]=='thumbnail');return self.answer(raw,mime=mime)
            return self.answer({'message':'演示实例不执行生成、授权或付费任务。','code':'DEMO_DISABLED'},403)
        except Exception as error:return self.answer({'message':str(error),'code':getattr(error,'code','PREVIEW_ERROR')},getattr(error,'status',400))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=18884);args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'Synthetic creator preview: http://127.0.0.1:{args.port}/',flush=True)
    try:server.serve_forever()
    finally:server.server_close();fixture.doCleanups()
