"""Local-only workbench with durable image execution and explicit readiness."""
import argparse, json, os, re, threading, uuid
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from zoneinfo import ZoneInfo
from production_actions import process_action,ActionError,atomic_json
from execution import Execution
from script_intake import list_scripts, read_script, import_script, start_analysis
from character_batches import start_batch
from production_run import ProductionRun
import cinematic_contracts
import scene_references
from workflow_protocol import Workflow
from providers.lovart import ProviderError

LOCK=threading.Lock()
def save_settings(root,payload):
    ratio=payload.get('aspectRatio')
    if ratio not in ['16:9','9:16','21:9',None]:raise ActionError('请选择横版、竖版或电影版。')
    with LOCK:
        m=json.loads((root/'manifest.json').read_text());current=m.get('delivery',{'version':0,'aspectRatio':None})
        if payload.get('expectedVersion')!=current['version']:raise ActionError('项目设置已变化，请刷新后再试。',409)
        m['delivery']={'version':current['version']+1,'aspectRatio':ratio,'videoEnabled':False}
        atomic_json(root/'manifest.json',m)
    return {'ok':True,'delivery':m['delivery']}
class ReviewError(Exception):
    def __init__(self,message,status=400):self.message=message;self.status=status

def save_review(root,payload):
    if not isinstance(payload,dict):raise ReviewError('审核内容格式不正确')
    if payload.get('target')!='white-model':raise ReviewError('暂不支持此审核对象')
    decision=payload.get('decision')
    if decision not in ['approved','changes_requested']:raise ReviewError('请选择审核结果')
    notes=payload.get('notes','')
    if not isinstance(notes,str) or len(notes)>4000:raise ReviewError('意见请控制在4000字以内')
    notes=notes.strip()
    if decision=='changes_requested' and len(notes)<2:raise ReviewError('请说明需要修改的位置或内容')
    viewed=payload.get('viewedViews',[])
    if not isinstance(viewed,list) or any(not isinstance(x,str) for x in viewed):raise ReviewError('查看记录格式不正确')
    with LOCK:
        path=root/'manifest.json';m=json.loads(path.read_text());w=m['whiteModelReview']
        if payload.get('sceneVersion')!=w['sceneVersion'] or payload.get('meshSha256')!=w['meshSha256'] or payload.get('expectedReviewId')!=w.get('lastReviewId'):
            raise ReviewError('场景或审核记录刚刚更新，请刷新后重新检查',409)
        allowed={v['view'] for v in w['views']}
        if decision=='approved' and set(viewed)!=allowed:raise ReviewError('请先查看并勾选全部四个角度')
        now=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat();rid='review-'+uuid.uuid4().hex
        record={'id':rid,'submittedAt':now,'target':'white-model','sceneVersion':w['sceneVersion'],'meshSha256':w['meshSha256'],'decision':decision,'notes':notes,'viewedViews':sorted(set(viewed)&allowed),'source':'local_review_web_form','previousReviewId':w.get('lastReviewId')}
        folder=root/'reviews';folder.mkdir(exist_ok=True)
        (folder/(rid+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2))
        w.update(status=decision,humanApproval=decision=='approved',lastReviewId=rid,reviewedAt=now,reviewNote=notes)
        m['scenePipeline'][1]['status']=decision
        m['pipeline'][2]['state']='布局已确认' if decision=='approved' else '需要修改 / 意见已记录'
        m['pipeline'][3]['state']='待制作' if decision=='approved' else '等待布局重新确认'
        m['phase']='白模布局已确认 · 统一材质尚未制作' if decision=='approved' else '白模布局需要修改 · 等待调整'
        temp=path.with_suffix('.json.tmp');temp.write_text(json.dumps(m,ensure_ascii=False,indent=2));os.replace(temp,path)
        review_file=root/'consistency-v2/white-model-review.json'
        temp=review_file.with_suffix('.json.tmp');temp.write_text(json.dumps(w,ensure_ascii=False,indent=2));os.replace(temp,review_file)
        return {'ok':True,'review':record,'status':w['status'],'generationStarted':False}

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,data_root,execution,**kwargs):self.data_root=data_root;self.execution=execution;super().__init__(*args,**kwargs)
    def end_headers(self):
        self.send_header('Cache-Control','no-cache')
        self.send_header('X-Content-Type-Options','nosniff')
        super().end_headers()
    def reply(self,code,body):
        raw=json.dumps(body,ensure_ascii=False).encode();self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def send_head(self):
        self.byte_range=None
        path=Path(self.translate_path(self.path))
        if path.suffix.lower() not in {'.mp4','.webm','.mp3','.wav','.m4a'} or not path.is_file():
            return super().send_head()
        # WebKit media seeking requires byte-range responses, including its 0-1 probe.
        stream=path.open('rb');size=os.fstat(stream.fileno()).st_size
        start,end=0,size-1;requested=self.headers.get('Range') if self.command=='GET' else None
        if requested and not self.headers.get('If-Range'):
            match=re.fullmatch(r'bytes=(\d*)-(\d*)',requested.strip())
            if match and any(match.groups()):
                left,right=match.groups()
                if left:start=int(left);end=min(int(right),size-1) if right else size-1
                else:start=max(0,size-int(right))
                if size==0 or start>=size or start>end:
                    stream.close();self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.send_header('Content-Length','0');self.end_headers();return None
                self.byte_range=(start,end)
        self.send_response(206 if self.byte_range else 200)
        self.send_header('Content-Type',self.guess_type(str(path)))
        self.send_header('Accept-Ranges','bytes')
        self.send_header('Content-Length',str(end-start+1))
        self.send_header('Last-Modified',self.date_time_string(os.fstat(stream.fileno()).st_mtime))
        if self.byte_range:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.end_headers();stream.seek(start);return stream
    def copyfile(self,source,outputfile):
        if not getattr(self,'byte_range',None):return super().copyfile(source,outputfile)
        remaining=self.byte_range[1]-self.byte_range[0]+1
        try:
            while remaining>0:
                block=source.read(min(256*1024,remaining))
                if not block:break
                outputfile.write(block);remaining-=len(block)
        except (BrokenPipeError,ConnectionResetError):pass
    def do_POST(self):
        workflow_routes=['/api/workflow/'+r for r in ('prepare','submit','recover','review','plan','bundle','open-bundle')]
        if self.path not in workflow_routes+['/api/scene-reference/frame','/api/scene-reference/generate','/api/cinematic/frame','/api/cinematic/save','/api/cinematic/repair','/api/production/action','/api/image-batches','/api/character-batches','/api/scripts/import','/api/scripts/analyze','/api/reviews','/api/choices','/api/draws','/api/previews','/api/project/settings','/api/execution/connect','/api/execution/retry','/api/execution/login','/api/execution/model','/api/execution/test-image']:return self.reply(404,{'error':'接口不存在'})
        host=self.headers.get('Host','');origin=self.headers.get('Origin','')
        parsed=urlparse(origin)
        if parsed.scheme!='http' or parsed.netloc!=host or parsed.hostname not in ['127.0.0.1','localhost']:
            return self.reply(403,{'error':'只接受本机审查页面的提交'})
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.reply(415,{'error':'需要JSON审核内容'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            limit=8*1024*1024 if self.path=='/api/scene-reference/frame' else 12*1024*1024 if self.path=='/api/scripts/import' else 2*1024*1024 if self.path in ('/api/cinematic/save','/api/cinematic/frame') else 256*1024 if self.path in workflow_routes else 32768
            if not 0<length<=limit:raise ReviewError('提交内容过大或为空')
            payload=json.loads(self.rfile.read(length))
            if not isinstance(payload,dict):raise ReviewError('请求格式不正确')
            if self.path in workflow_routes:result=self.execution.workflow.handle(self.path.rsplit('/',1)[1],payload)
            elif self.path=='/api/scene-reference/frame':result=scene_references.save_frame(self.execution,payload)
            elif self.path=='/api/scene-reference/generate':result=scene_references.generate(self.execution,payload)
            elif self.path=='/api/cinematic/save':result=cinematic_contracts.save(self.execution.production,payload)
            elif self.path=='/api/cinematic/frame':result=cinematic_contracts.save_frame(self.execution.production,payload)
            elif self.path=='/api/cinematic/repair':result=cinematic_contracts.repair(self.execution.production,payload)
            elif self.path=='/api/production/action':result=self.execution.production.start(payload)
            elif self.path in ('/api/character-batches','/api/image-batches'):result=start_batch(self.execution,payload)
            elif self.path=='/api/scripts/import':result=import_script(self.data_root,payload,LOCK)
            elif self.path=='/api/scripts/analyze':result=start_analysis(self.data_root,payload)
            elif self.path=='/api/execution/connect':result=self.execution.connect(payload)
            elif self.path=='/api/execution/login':result=self.execution.login()
            elif self.path=='/api/execution/model':result=self.execution.set_model(payload)
            elif self.path=='/api/execution/test-image':result=self.execution.test_image()
            elif self.path=='/api/execution/retry':result=self.execution.retry(payload.get('jobId'))
            elif self.path=='/api/project/settings':result=save_settings(self.data_root,payload)
            else:
                result=save_review(self.data_root,payload) if self.path=='/api/reviews' else process_action(self.data_root,payload,'choose' if self.path=='/api/choices' else 'preview' if self.path=='/api/previews' else 'draw',LOCK)
                self.execution.wake()
            self.reply(200,result)
        except (ReviewError,ActionError) as e:self.reply(e.status,{'error':e.message})
        except ProviderError as e:self.reply(502,{'error':str(e)})
        except (ValueError,UnicodeDecodeError):self.reply(400,{'error':'审核内容格式不正确'})
        except Exception as e:
            print('Review storage error:',type(e).__name__,flush=True)
            self.reply(500,{'error':'审核记录未能保存，请保留意见后重试'})

    def do_GET(self):
        parsed=urlparse('http://'+self.headers.get('Host',''))
        if parsed.hostname not in ['127.0.0.1','localhost']:return self.reply(403,{'error':'仅允许本机访问'})
        route=urlparse(self.path)
        if route.path=='/api/workflow/state':return self.reply(200,self.execution.workflow.state())
        if route.path in ('/api/workflow/thumbnail','/api/workflow/export'):
            try:
                query=parse_qs(route.query)
                if route.path.endswith('thumbnail'):
                    raw=self.execution.workflow.thumbnail(query.get('id',[''])[0]);mime='image/jpeg'
                else:
                    raw=self.execution.workflow.export(query.get('scope',[''])[0]);mime='application/zip'
                self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)))
                if mime=='application/zip':self.send_header('Content-Disposition','attachment; filename="asset-lab-approved.zip"')
                self.end_headers();self.wfile.write(raw);return
            except ActionError as e:return self.reply(e.status,{'error':e.message})
        if self.path=='/api/scene-reference/version':return self.reply(200,{'sourceRevision':scene_references.source_revision(self.execution.root)})
        if self.path.startswith('/api/cinematic?project='):
            try:return self.reply(200,cinematic_contracts.state(self.execution.production,self.path.split('=',1)[1]))
            except ActionError as e:return self.reply(e.status,{'error':e.message})
        if self.path=='/api/production':return self.reply(200,self.execution.production.state())
        if self.path=='/api/execution':return self.reply(200,self.execution.state())
        if self.path=='/api/scripts':return self.reply(200,list_scripts(self.data_root))
        if self.path.startswith('/api/scripts/'):
            try:return self.reply(200,read_script(self.data_root,self.path.removeprefix('/api/scripts/')))
            except ActionError as e:return self.reply(e.status,{'error':e.message})
        return super().do_GET()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8768);p.add_argument('--serve-root',type=Path);p.add_argument('--data-root',type=Path);a=p.parse_args()
    here=Path(__file__).resolve().parent;workspace=here.parents[1]
    data_root=(a.data_root or here).resolve();serve_root=(a.serve_root or workspace/'work').resolve()
    execution=Execution(data_root,LOCK)
    execution.production=ProductionRun(execution)
    execution.workflow=Workflow(execution)
    server=ThreadingHTTPServer(('127.0.0.1',a.port),partial(Handler,directory=str(serve_root),data_root=data_root,execution=execution))
    execution.start()
    from mindreader_workflow import start_embedded
    workflow_service=start_embedded()
    print(f'Local preview with review storage: http://127.0.0.1:{a.port}/dashixiong-image-test/index.html',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        if workflow_service:workflow_service.shutdown();workflow_service.server_close()
        execution.stopping.set();execution.wake();server.server_close()
        if execution.worker:execution.worker.join(timeout=7)
