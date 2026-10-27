"""Local production view and idempotent Nano actions; original image executor owns jobs."""
from pathlib import Path
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from urllib.parse import urlparse,unquote
from PIL import Image
import json,datetime,hashlib,threading,urllib.request,re,collections
N=Path('/Users/zhoukaihao/Documents/Codex/2026-10-22/w');O=N/'outputs/别让他知道-三分钟分镜';D=O/'视频制作V1'
R=Path('/Users/zhoukaihao/Documents/Codex/2026-10-17/files-mentioned-by-the-user-codex/outputs/dashixiong-image-test')
LOCK=threading.RLock();ORIGINS={'http://127.0.0.1:8768','http://localhost:8768','http://127.0.0.1:8773','http://localhost:8773'}
def read(p,default=None):return json.loads(p.read_text()) if p.exists() else (default if default is not None else {})
def save(p,x):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(x,ensure_ascii=False,indent=2));t.replace(p)
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def manifest():return read(R/'manifest.json')
def candidate(t):return {'id':t['id'],'label':t.get('characterId','').split('-')[-1].upper(),'image':'/candidate/'+t['id'],'shotId':t.get('characterId','').split('-')[0],'batchId':t.get('batchId'),'model':t.get('modelKey')}
def valid_task(t):return t.get('generated') and (t.get('batchId','').startswith('mindreader180-'))
def policy():return read(D/'generation-policy.json',{'variantsPerImage':1,'nanoVariantsPerImage':1,'mvpMode':True,'bulkGenerationEnabled':False,'repairRequiresReviewNote':True})
def passed(record):
 return bool(record) and record.get('review',{}).get('status')!='needs_repair' and (record.get('aiReview')=='pass' or record.get('humanReview')=='pass')
def original_candidates(sid,tasks):
 repairs=[dict(candidate(t),shotId=sid,repair=True) for t in tasks if t.get('batchId','').startswith('mindreader180-original-repair-') and t.get('characterId','').startswith(sid+'-')]
 source=read(O/'shot-selections.json').get(sid,{})
 lookup={'S37':'S17','S38':'S29'}.get(sid,sid)
 for batch in ['mindreader180-video-boards-v1','mindreader180-environment-samples-v2']:
  found=[t for t in tasks if t.get('batchId')==batch and t.get('characterId','').startswith(lookup+'-')]
  if found:return [dict(candidate(t),shotId=sid) for t in found]+repairs
 origin=next((t for t in tasks if t['id']==source.get('taskId')),None)
 if not origin:return repairs
 prefix=origin['characterId'].rsplit('-',1)[0]+'-'
 return [dict(candidate(t),shotId=sid) for t in tasks if t.get('batchId')==origin['batchId'] and t.get('characterId','').startswith(prefix)]+repairs
def state():
 m=manifest();base=read(O/'script-and-boards.json');sel=read(D/'board-selections.json');nano=read(D/'nano-selections.json');runs=read(D/'nano-runs.json',[])
 tasks=[t for t in m.get('tasks',[]) if valid_task(t)];byid={t['id']:t for t in tasks};boards=[]
 for s in base['shots']:
  sid=s['id'];chosen=sel.get(sid);clean=nano.get(sid);cc=original_candidates(sid,tasks)
  pending=[r for r in runs if sid in r['shotIds'] and r['sourceHashes'].get(sid)==(chosen or {}).get('sha256')]
  bids=[r['batchId'] for r in pending]
  nc=[candidate(t) for t in tasks if t.get('batchId') in bids and t.get('characterId','').startswith(sid+'-')]
  nj=[j for j in m.get('generationQueue',[]) if j.get('batchId') in bids and j.get('characterId','').startswith(sid+'-')]
  if clean and clean.get('sourceSha256')!=(chosen or {}).get('sha256'):clean=None
  boards.append({'id':sid,'title':s['title'],'start':s['start'],'end':s['end'],'speech':s['speech'],'action':s['action'],'camera':s['camera'],'candidates':sorted(cc,key=lambda x:x['label']),'selection':chosen,'image':('/media/视频制作V1/'+chosen['file']) if chosen else '/media/'+s['boardFile'],'nanoCandidates':sorted(nc,key=lambda x:x['label']),'nanoSelection':clean,'nanoImage':('/media/视频制作V1/'+clean['file']) if clean else None,'nanoStarted':bool(pending),'nanoCounts':dict(collections.Counter(j['status'] for j in nj))})
 jobs=[]
 for p in sorted((D/'jobs').glob('*.json')):
  j=read(p);jobs.append({k:j.get(k) for k in ['id','title','status','file','message','actualDuration','width','height','submitStartedAt','completedAt','review']})
 imagejobs=[j for j in m.get('generationQueue',[]) if (j.get('batchId')=='mindreader180-video-boards-v1' or j.get('batchId','').startswith('mindreader180-original-repair-'))]
 nanobids={r['batchId'] for r in runs};nanojobs=[j for j in m.get('generationQueue',[]) if j.get('batchId') in nanobids]
 caption=read(D/'caption-review.json');final=read(D/'delivery.json')
 count={'shots':40,'selected':len(sel),'reviewed':sum(passed(q) for q in sel.values()),'imageCandidates':len([t for t in tasks if t.get('batchId')=='mindreader180-video-boards-v1']),'imageJobs':dict(collections.Counter(j['status'] for j in imagejobs)),'nanoSelected':sum(bool(b['nanoSelection']) for b in boards),'nanoPassed':sum(passed(b['nanoSelection']) for b in boards),'nanoJobs':dict(collections.Counter(j['status'] for j in nanojobs)),'videoSubmitted':len([j for j in jobs if j.get('submitStartedAt')]),'videoDownloaded':len([j for j in jobs if j.get('file')]),'videoPassed':sum((j.get('review') or {}).get('status')=='pass' for j in jobs)}
 result={'id':'mindreader180','title':'别让他知道','targetSeconds':180,'aspectRatio':'9:16','model':'Seedance 2.5 · 1080p · 原生音轨','updatedAt':now(),'approval':read(D/'approval.json'),'counts':count,'boards':boards,'jobs':jobs,'plan':[{k:p[k] for k in ['id','title','start','end','shotIds']} for p in read(D/'video-plan.json')['segments']],'assets':{'characters':3,'scenes':4,'effects':3,'sceneVersion':'V2'},'caption':caption,'delivery':final,'mvp':read(D/'mvp.json'),'previs':read(O/'白模动画V2/status.json'),'policy':policy(),'repairRuns':read(D/'repair-runs.json',[]),'videoGate':'当前先完成180秒白模的动作、走位与运镜审核；成片生成已暂停。单张分镜 → Nano清理 → 提交意见针对性返修的规则保留。','jobRecords':[{'id':j['id'],'title':j.get('title'),'status':j['status'],'message':j.get('message'),'batchId':j.get('batchId')} for j in imagejobs+nanojobs]}
 return result
def select_frame(payload,nano=False):
 sid=payload.get('shotId');assert re.fullmatch(r'S\d{2}',sid or ''),'镜号不正确'
 taskid=payload.get('taskId');m=manifest();t=next((t for t in m['tasks'] if t['id']==taskid and valid_task(t)),None);assert t,'候选尚未成功返回'
 ss=read(D/'board-selections.json');actor=payload.get('actor','operator');review=payload.get('reviewNote','')
 if nano:
  assert t.get('characterId','').startswith(sid+'-'),'候选与镜号不一致'
  assert sid in ss,'请先选择原分镜'
  run=next((r for r in read(D/'nano-runs.json',[]) if r['batchId']==t.get('batchId')),None)
  assert run and run['sourceHashes'].get(sid)==ss[sid].get('sha256'),'原分镜已变化，请对当前版本洗图'
  target=D/'nano-boards'/f'{sid}.png';target.parent.mkdir(exist_ok=True)
  import shutil;shutil.copy2(R/t['file'],target)
  ns=read(D/'nano-selections.json');ns[sid]={'taskId':taskid,'file':str(target.relative_to(D)),'sourceSha256':ss[sid]['sha256'],'sha256':sha(target),'selectedAt':now(),'selectedBy':actor,'candidate':t['characterId'].split('-')[-1].upper(),'aiReview':'pass' if actor=='assistant' and review else 'pending','reviewNote':review};save(D/'nano-selections.json',ns)
 else:
  assert taskid in [c['id'] for c in original_candidates(sid,[q for q in m['tasks'] if valid_task(q)])],'不是当前分镜的候选版本'
  target=D/'boards'/f'{sid}.png';import shutil;shutil.copy2(R/t['file'],target)
  old=ss.get(sid);history=(old or {}).get('history',[])
  if old and old.get('taskId')!=taskid:history.append({k:v for k,v in old.items() if k!='history'})
  ss[sid]={'taskId':taskid,'file':str(target.relative_to(D)),'sha256':sha(target),'selectedAt':now(),'selectedBy':actor,'candidate':t['characterId'].split('-')[-1].upper(),'aiReview':'pass' if actor=='assistant' and review else 'pending','reviewNote':review,'history':history};save(D/'board-selections.json',ss)
 return {'ok':True,'shotId':sid}
def start_nano(payload):
 ss=read(D/'board-selections.json');ids=payload.get('shotIds') or list(ss)
 assert isinstance(ids,list) and 0<len(ids)<=40,'请选择1到40镜'
 assert not policy().get('mvpMode') or len(ids)==1,'MVP阶段每次只处理当前一镜'
 assert all(x in ss for x in ids),'请先完成分镜选用'
 assert all(passed(ss[x]) for x in ids),'请先审核当前原分镜'
 runs=read(D/'nano-runs.json',[]);chosen=[];hashes={}
 for sid in ids:
  assert re.fullmatch(r'S\d{2}',sid),'镜号不正确'
  source=D/ss[sid]['file'];h=sha(source)
  if ss[sid].get('sha256')!=h:ss[sid]['sha256']=h
  hashes[sid]=h
  if any(r['sourceHashes'].get(sid)==h for r in runs):continue
  chosen.append(sid)
 save(D/'board-selections.json',ss)
 if not chosen:return {'ok':True,'reused':True,'message':'这些分镜已有对应Nano任务，未重复提交'}
 signature=hashlib.sha256(json.dumps({s:hashes[s] for s in sorted(chosen)},sort_keys=True).encode()).hexdigest()[:12];bid='mindreader180-board-nano-'+signature
 refs=R/'reference-inputs/mindreader180-board-nano';refs.mkdir(exist_ok=True);items=[]
 for sid in chosen:
  rf=refs/(sid+'-'+hashes[sid][:10]+'.jpg');Image.open(D/ss[sid]['file']).convert('RGB').save(rf,quality=95,subsampling=0);assert rf.stat().st_size<20*1024*1024
  items.append({'id':sid+'-v1','name':sid,'title':sid+'·Nano保真洗图','entityId':'mindreader180-nano-'+sid,'entityName':sid,'category':'shot','kind':'storyboard-cleanup','phase':'refine','ratio':'9:16','modelKey':'nebula-2.1','generationCount':1,'modelSettings':{'resolution':'4K'},'references':[str(rf.relative_to(R))],'prompt':'对这张已经选定的9:16电影CG分镜做保真清噪与纹理清理。原图的完整构图、裁切、相机机位、人物身份年龄五官、肤色发型服装、表情视线、身体姿势、左右手与五指结构、接触关系、人数、神祇数量、道具和建筑地标均保持原样。只减少噪点、脏色、锯齿及纹理碎裂；保留真实皮肤、毛发、布料、木石微纹理，树冠保留自然枝叶疏密和透光。景深与主光方向不变。原图的单一时刻和动作不变。一张完整竖幅，图内保持纯画面。'})
 batch={'id':bid,'title':'三分钟分镜·Nano保真清理','maxConcurrentImages':1,'reviewPolicy':'每镜只生成一张，审核有问题后附意见针对性返修；通过后才允许对应视频','outputRequirements':'一张完整9:16无文字分镜，保留原图全部人物与构图','instruction':'只清理噪点和纹理，不重新设计分镜。','characters':items}
 save(R/'batches'/(bid+'.json'),batch);save(D/'prompts'/(bid+'.json'),batch)
 record={'batchId':bid,'shotIds':chosen,'sourceHashes':{s:hashes[s] for s in chosen},'createdAt':now(),'status':'prepared','candidateCount':1}
 runs.append(record);save(D/'nano-runs.json',runs)
 req=urllib.request.Request('http://127.0.0.1:8768/api/image-batches',data=json.dumps({'batchId':bid}).encode(),headers={'Content-Type':'application/json','Origin':'http://127.0.0.1:8768'})
 try:
  result=json.load(urllib.request.urlopen(req,timeout=60));record.update(status='submitted',jobIds=result['batch']['jobIds'],submittedAt=now());save(D/'nano-runs.json',runs)
 except Exception:
  record.update(status='submission_unknown',message='已保留批次，需核对原任务，不自动重发');save(D/'nano-runs.json',runs);raise
 return {'ok':True,'batchId':bid,'shotCount':len(chosen),'jobCount':len(items)}
def review_frame(payload):
 sid=payload.get('shotId');kind=payload.get('kind');verdict=payload.get('verdict');note=str(payload.get('note','')).strip()
 assert kind in ['original','nano'] and verdict in ['pass','needs_repair'],'请选择审核对象和结论'
 assert re.fullmatch(r'S\d{2}',sid or ''),'镜号不正确'
 if verdict=='needs_repair':assert 4<=len(note)<=1600,'请填写具体问题和期望修正，至少4个字'
 path=D/('nano-selections.json' if kind=='nano' else 'board-selections.json');records=read(path);taskid=payload.get('taskId')
 if taskid and records.get(sid,{}).get('taskId')!=taskid:
  select_frame({'shotId':sid,'taskId':taskid},nano=kind=='nano');records=read(path)
 rec=records.get(sid);assert rec,'先选择要审核的画面'
 assert sha(D/rec['file'])==rec['sha256'],'画面文件已变化，请刷新后重新审核'
 if kind=='nano':assert rec['sourceSha256']==read(D/'board-selections.json').get(sid,{}).get('sha256'),'原分镜已变化，需要重新洗图'
 actor='assistant' if payload.get('actor')=='assistant' else 'operator'
 review={'status':verdict,'note':note or '人工审核通过','by':actor,'at':now(),'sha256':rec['sha256'],'taskId':rec.get('taskId')}
 rec['review']=review;rec['reviewNote']=review['note'];rec['aiReview' if actor=='assistant' else 'humanReview']=verdict
 if verdict=='needs_repair':rec['aiReview']='needs_repair';rec['humanReview']='needs_repair'
 else:rec['aiReview' if actor=='operator' else 'humanReview']='pending' if rec.get('aiReview' if actor=='operator' else 'humanReview')=='needs_repair' else rec.get('aiReview' if actor=='operator' else 'humanReview','pending')
 save(path,records);history=read(D/'reviews.json',[]);history.append(dict(review,shotId=sid,kind=kind));save(D/'reviews.json',history)
 return {'ok':True,'shotId':sid,'message':'审核通过，已记录当前版本' if verdict=='pass' else '已记录问题，等待针对性返修'}
def start_repair(payload):
 sid=payload.get('shotId');kind=payload.get('kind');note=str(payload.get('note','')).strip()
 assert kind in ['original','nano'],'请选择原分镜或Nano画面'
 assert 4<=len(note)<=1600,'请填写具体问题和期望修正，至少4个字'
 review_frame(dict(payload,verdict='needs_repair'))
 selections=read(D/('nano-selections.json' if kind=='nano' else 'board-selections.json'));rec=selections[sid];source=D/rec['file'];source_hash=sha(source)
 runs=read(D/'repair-runs.json',[]);signature=hashlib.sha256(json.dumps([sid,kind,source_hash,note],ensure_ascii=False).encode()).hexdigest()[:16]
 existing=next((r for r in runs if r['signature']==signature),None)
 if existing:return {'ok':True,'reused':True,'batchId':existing['batchId'],'message':'这张图的同一审核意见已提交，沿用原返修任务'}
 bid='mindreader180-'+kind+'-repair-'+signature;revision=1+sum(r['shotId']==sid and r['kind']==kind for r in runs)
 refs=R/'reference-inputs/mindreader180-repairs';refs.mkdir(exist_ok=True)
 rf=refs/(bid+'.jpg');Image.open(source).convert('RGB').save(rf,quality=95,subsampling=0)
 prompt='只修改这张完整9:16分镜中审核明确指出的问题。审核意见：'+note+'。修正发生在指定人物、部位或物体，不改变未指出的内容。保持人物身份、年龄、服装发型、原有场景固定结构、光向、镜头构图及剧情瞬间。画面不加文字或拼版，输出一张完整修订图。'
 if kind=='nano':prompt+='这是Nano保真返修；保留自然皮肤、毛发与衣料微纹理，只做上述必要修正和清噪。'
 item={'id':sid+'-r'+str(revision),'name':sid,'title':sid+'·'+('Nano' if kind=='nano' else '原分镜')+'意见返修 R'+str(revision),'entityId':'mindreader180-repair-'+sid,'entityName':sid,'category':'shot','kind':'targeted-repair','phase':'refine' if kind=='nano' else 'asset','ratio':'9:16','modelKey':'nebula-2.1' if kind=='nano' else 'lib-image-2.5-s','generationCount':1,'modelSettings':{'resolution':'4K'},'references':[str(rf.relative_to(R))],'prompt':prompt}
 batch={'id':bid,'title':item['title'],'maxConcurrentImages':1,'reviewPolicy':'按审核意见单张返修，复审通过后采用','outputRequirements':'一张9:16分镜，指定问题修正，其他内容保真','instruction':note,'characters':[item]}
 record={'batchId':bid,'signature':signature,'shotId':sid,'kind':kind,'revision':revision,'reviewNote':note,'sourceSha256':source_hash,'sourceTaskId':rec.get('taskId'),'candidateCount':1,'createdAt':now(),'status':'prepared'}
 runs.append(record);save(D/'repair-runs.json',runs);save(R/'batches'/(bid+'.json'),batch);save(D/'prompts'/(bid+'.json'),batch)
 if kind=='nano':
  nr=read(D/'nano-runs.json',[]);nr.append({'batchId':bid,'shotIds':[sid],'sourceHashes':{sid:read(D/'board-selections.json')[sid]['sha256']},'createdAt':now(),'status':'prepared','candidateCount':1,'purpose':'targeted_repair'});save(D/'nano-runs.json',nr)
 req=urllib.request.Request('http://127.0.0.1:8768/api/image-batches',data=json.dumps({'batchId':bid}).encode(),headers={'Content-Type':'application/json','Origin':'http://127.0.0.1:8768'})
 try:
  result=json.load(urllib.request.urlopen(req,timeout=60));record.update(status='submitted',jobIds=result['batch']['jobIds'],submittedAt=now());save(D/'repair-runs.json',runs)
 except Exception:
  record.update(status='submission_unknown',message='已保留返修记录，需核对原任务，不自动重新提交');save(D/'repair-runs.json',runs);raise
 return {'ok':True,'batchId':bid,'jobCount':1,'message':'审核意见已保存，已提交1张针对性返修；返回后需要复审'}
def recover_nano():
 bids={r['batchId'] for r in read(D/'nano-runs.json',[])};count=0
 for job in manifest().get('generationQueue',[]):
  if job.get('batchId') not in bids or job['status'] not in ['failed','needs_attention']:continue
  if not job.get('submissionAttempted'):continue
  if job.get('submissionAttempted') and not job.get('nodeKey'):continue
  req=urllib.request.Request('http://127.0.0.1:8768/api/execution/retry',data=json.dumps({'jobId':job['id']}).encode(),headers={'Content-Type':'application/json','Origin':'http://127.0.0.1:8768'})
  json.load(urllib.request.urlopen(req,timeout=15));count+=1
 return {'ok':True,'message':f'已恢复 {count} 条任务：已提交任务只查询原结果，未提交任务继续准备。'}
def start_video(payload):
 import subprocess
 assert policy().get('videoGenerationEnabled',True),'成片视频制作已暂停，请先完成白模动画'
 cid=payload.get('segmentId');plan=next((p for p in read(D/'video-plan.json')['segments'] if p['id']==cid),None)
 assert plan,'视频段不存在'
 assert not policy().get('mvpMode') or cid==policy().get('mvpSegment','C03'),'MVP阶段只生成当前验证段'
 assert read(D/'approval.json').get('confirmedStory'),'剧情尚未确认'
 originals=read(D/'board-selections.json');clean=read(D/'nano-selections.json')
 for sid in plan['shotIds']:
  assert passed(originals.get(sid)) and passed(clean.get(sid)),sid+'尚未通过分镜和Nano审核'
  assert originals[sid]['sha256']==clean[sid]['sourceSha256']==sha(D/originals[sid]['file']),sid+'原图版本已变化'
  assert clean[sid]['sha256']==sha(D/clean[sid]['file']),sid+'Nano版本已变化'
 path=D/'jobs'/(cid+'.json');job=read(path)
 if job:return {'ok':True,'reused':True,'message':'该段已有任务，继续核对原任务，不重复提交'}
 job={'id':cid,'title':plan['title'],'status':'queued','createdAt':now(),'plan':plan,'attempt':1,'purpose':'mvp','message':'MVP单段任务已准备，提交前再次核对分镜版本'};save(path,job)
 w=N/'work/mindreader-video';log=(w/(cid+'-runner.log')).open('a')
 try:subprocess.Popen(['/Users/zhoukaihao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3',str(w/'generate_video.py'),cid],cwd=N,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
 except Exception:
  job.update(status='needs_attention',message='启动未完成，尚未提交生成');save(path,job);raise
 finally:log.close()
 return {'ok':True,'message':cid+' 已启动单段MVP生成，原生音轨保留'}
class Handler(SimpleHTTPRequestHandler):
 def log_message(self,*args):pass
 def end_headers(self):
  origin=self.headers.get('Origin')
  if origin in ORIGINS:self.send_header('Access-Control-Allow-Origin',origin);self.send_header('Vary','Origin')
  self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');super().end_headers()
 def reply(self,code,obj):
  raw=json.dumps(obj,ensure_ascii=False).encode();self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 def do_OPTIONS(self):
  if self.headers.get('Origin') not in ORIGINS:return self.reply(403,{'error':'仅限本地工作台'})
  self.send_response(204);self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS');self.send_header('Access-Control-Allow-Headers','Content-Type');self.end_headers()
 def translate_path(self,path):
  part=unquote(urlparse(path).path)
  if part.startswith('/media/'):
   p=(O/part[7:]).resolve()
   if p.is_relative_to(O.resolve()) and p.suffix.lower() in ['.png','.jpg','.jpeg','.webp','.mp4','.json','.md','.srt','.ass','.html','.js']:return str(p)
  if part.startswith('/candidate/'):
   tid=part.removeprefix('/candidate/');t=next((t for t in manifest()['tasks'] if t['id']==tid and valid_task(t)),None)
   if t:
    p=(R/t['file']).resolve()
    if p.is_relative_to(R.resolve()):return str(p)
  return str(O/'__not_found__')
 def send_head(self):
  self.byte_range=None
  src=Path(self.translate_path(self.path))
  if src.suffix.lower()!='.mp4' or not src.is_file():return super().send_head()
  size=src.stat().st_size;start=0;end=size-1
  match=re.fullmatch(r'bytes=(\d*)-(\d*)',self.headers.get('Range',''))
  if match and any(match.groups()):
   left,right=match.groups()
   if left:start=int(left);end=min(int(right),size-1) if right else size-1
   else:start=max(0,size-int(right))
   if start>=size or start>end:
    self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.send_header('Content-Length','0');self.end_headers();return None
   self.byte_range=(start,end)
  stream=src.open('rb');stream.seek(start)
  self.send_response(206 if self.byte_range else 200);self.send_header('Content-Type','video/mp4');self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1))
  if self.byte_range:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
  self.end_headers();return stream
 def copyfile(self,source,outputfile):
  if not getattr(self,'byte_range',None):return super().copyfile(source,outputfile)
  remaining=self.byte_range[1]-self.byte_range[0]+1
  try:
   while remaining>0:
    block=source.read(min(256*1024,remaining))
    if not block:break
    outputfile.write(block);remaining-=len(block)
  except (BrokenPipeError,ConnectionResetError):pass
 def do_GET(self):
  if urlparse('http://'+self.headers.get('Host','')).hostname not in ['localhost','127.0.0.1']:return self.reply(403,{'error':'仅本地'})
  if self.path.split('?')[0]=='/api/state':
   try:return self.reply(200,state())
   except Exception as e:return self.reply(500,{'error':'制作记录读取失败','type':type(e).__name__})
  if urlparse(self.path).query=='preview=1':
   src=Path(self.translate_path(self.path))
   if src.is_file() and src.suffix.lower() in ['.png','.jpg','.jpeg','.webp']:
    folder=N/'work/mindreader-video/thumbnails';folder.mkdir(exist_ok=True)
    key=hashlib.sha256((str(src)+str(src.stat().st_mtime_ns)).encode()).hexdigest()[:24];target=folder/(key+'.jpg')
    with LOCK:
     if not target.exists():
      im=Image.open(src).convert('RGB');im.thumbnail((540,960));im.save(target,quality=90)
    raw=target.read_bytes();self.send_response(200);self.send_header('Content-Type','image/jpeg');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
  return super().do_GET()
 def do_POST(self):
  if self.headers.get('Origin') not in ORIGINS:return self.reply(403,{'error':'仅限本地工作台提交'})
  if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.reply(415,{'error':'需要JSON'})
  try:
   size=int(self.headers.get('Content-Length',0));assert 0<size<32768
   payload=json.loads(self.rfile.read(size))
   with LOCK:
    if self.path=='/api/select':result=select_frame(payload)
    elif self.path=='/api/select-nano':result=select_frame(payload,True)
    elif self.path=='/api/nano':result=start_nano(payload)
    elif self.path=='/api/recover-nano':result=recover_nano()
    elif self.path=='/api/review':result=review_frame(payload)
    elif self.path=='/api/repair':result=start_repair(payload)
    elif self.path=='/api/video':result=start_video(payload)
    else:return self.reply(404,{'error':'无此操作'})
   return self.reply(200,result)
  except AssertionError as e:return self.reply(409,{'error':str(e) or '请求不符合当前阶段'})
  except Exception as e:return self.reply(500,{'error':'操作未完成，已保留原记录','type':type(e).__name__})
def start_embedded():
 import errno
 try:server=ThreadingHTTPServer(('127.0.0.1',8773),Handler)
 except OSError as error:
  if error.errno==errno.EADDRINUSE:return None
  raise
 threading.Thread(target=server.serve_forever,name='mindreader-workflow',daemon=True).start()
 return server
if __name__=='__main__':
 print('Mindreader workflow ready on 127.0.0.1:8773',flush=True)
 ThreadingHTTPServer(('127.0.0.1',8773),Handler).serve_forever()
