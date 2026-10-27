"""Local film pipeline: durable UI actions, original jobs preserved on failure."""
from pathlib import Path
import json, threading, subprocess, shutil, hashlib
from datetime import datetime, timezone
from production_actions import ActionError, atomic_json
from character_batches import start_batch
from production_revision import begin_revision, reference_state, REFERENCE_BATCH

NOW=lambda:datetime.now(timezone.utc).isoformat()
RUN_ID='death-exception-60s'
class ProductionRun:
 def __init__(self, execution):
  self.execution=execution;self.root=execution.root;self.workspace=self.root.parents[1]
  active=json.loads((self.root/'production-active.json').read_text()) if (self.root/'production-active.json').exists() else {'runId':RUN_ID,'projectDir':'dashixiong-death-exception'}
  if active['runId'] not in ('death-exception-60s','gift-hears-thoughts-60s'):raise ValueError('Unknown production')
  self.run_id=active['runId']
  self.folder=self.root.parent/'dashixiong-scene-studio/production'/self.run_id
  self.project=self.workspace/'videos'/active['projectDir']
  self.config=json.loads((self.folder/'run.json').read_text())
  self.path=self.folder/'execution.json';self.lock=threading.RLock();self.workers={}
  if not self.path.exists():atomic_json(self.path,{'runId':self.run_id,'operations':{},'videoJobs':[]})
 def read(self):return json.loads(self.path.read_text())
 def change(self,fn):
  with self.lock:
   s=self.read();fn(s);s['updatedAt']=NOW();atomic_json(self.path,s);return s
 def source_revision(self):
  names=['render.js','shots.js','scene/director/rigged-actor.js','scene/director/motion-library.js','scene/director/natural-performance.js','scene/models/motions/quaternius-standard.json']
  h=hashlib.sha256()
  if (self.project/'performance.js').exists():names.append('performance.js')
  for name in ['scene/scenes.js','scene/geometry.js','scene/catalog.js','scene/material-library.js']:
   if (self.project/name).exists():names.append(name)
  for name in names:h.update(name.encode());h.update((self.project/name).read_bytes())
  return h.hexdigest()[:12]
 def state(self):
  with self.lock:s=self.read()
  run=json.loads((self.folder/'run.json').read_text());shots=json.loads((self.folder/'shots.json').read_text())
  with self.execution.lock:m=self.execution.read()
  s['previsNeedsRebuild']=s.get('operations',{}).get('previs',{}).get('sourceRevision')!=self.source_revision()
  s['run']={k:run.get(k) for k in ('title','duration','aspectRatio','resolution','model','status','id','previsUrl','episode')};s['shots']=shots
  s['characters']=[{'id':t['id'],'name':t['catalog']['entityName'],'file':t['file'],'status':t.get('humanReview')} for t in m['tasks'] if t.get('batchId')=='death-exception-cards-v1' and t.get('generated')]
  if self.config.get('characterTaskIds'):
   byid={t['id']:t for t in m['tasks']};s['characters']=[{'id':byid[tid]['id'],'name':byid[tid]['catalog']['entityName'],'file':byid[tid]['file'],'status':byid[tid].get('humanReview')} for tid in self.config['characterTaskIds'].values()]
  if s.get('revision',1)>=2:
   candidates=[t for t in m['tasks'] if t.get('batchId')=='death-exception-ye-style-v2' and t.get('generated') and t.get('phase') in ('asset','refine')]
   approved=[t for t in candidates if t.get('humanReview')=='approved']
   for c in s['characters']:
    if c['name']=='叶宇':
     t=(approved or candidates or [None])[-1]
     c.update(status='approved' if approved else 'changes_requested',needsRefinement=not approved or approved[-1].get('phase')!='refine')
     if t:c.update(id=t['id'],file=t['file'])
  s['storyboards']=[t for t in m['tasks'] if t.get('batchId','').startswith(self.config.get('boardPrefix','death-exception-boards-')) and t.get('generated')]
  s['imageJobs']=[{k:j.get(k) for k in ('id','title','status','error','executionState','resultTaskId','batchId')} for j in m.get('generationQueue',[]) if j.get('batchId','').startswith(self.config.get('boardPrefix','death-exception-boards-'))]
  plan_path=self.folder/('video-plan-v2.json' if s.get('revision',1)>=2 else 'video-plan.json')
  s['videoPlanReady']=json.loads(plan_path.read_text()).get('readyForVideo',True)
  if self.run_id==RUN_ID:s.update(reference_state(self,m))
  s['sourceRevision']=self.source_revision()
  selection=self.folder/'board-selection.json'
  s['boardSelection']=json.loads(selection.read_text()) if selection.exists() else None
  return s
 def start(self,payload):
  action=payload.get('action')
  if action=='begin-revision':return begin_revision(self,payload)
  if action=='reference-pack':
   if self.read().get('revision',1)<2:raise ActionError('请先创建修订版。',409)
   batch=start_batch(self.execution,{'batchId':REFERENCE_BATCH})
   self.change(lambda s:s['operations'].update(references={'status':'submitted','at':NOW(),'batchId':REFERENCE_BATCH}))
   return batch
  if action=='review-final':
   with self.lock:
    s=self.read();final=s['operations'].get('assemble',{})
    if final.get('status')!='completed' or payload.get('sha256')!=final.get('sha256'):raise ActionError('成片版本已变化，请重新查看。',409)
    final['review']={'accepted':True,'reviewedAt':NOW(),'sha256':final['sha256']};atomic_json(self.path,s)
    run=json.loads((self.folder/'run.json').read_text());run.update(status='completed',final=final);atomic_json(self.folder/'run.json',run)
   return {'ok':True}
  if action=='review-video':
   with self.lock:
    s=self.read();job=next((j for j in s['videoJobs'] if j['id']==payload.get('jobId')),None)
    if not job or job.get('status')!='completed' or payload.get('sha256')!=job.get('sha256'):raise ActionError('视频版本已变化，请重新查看。',409)
    job['review']={'accepted':True,'reviewedAt':NOW(),'reviewer':'workbench','sha256':job['sha256']};atomic_json(self.path,s)
   return {'ok':True}
  if action in ('storyboards','repair-storyboards','repair-direction'):
   batch=start_batch(self.execution,{'batchId':self.config['boardBatch'] if action=='storyboards' and self.config.get('boardBatch') else {'storyboards':'death-exception-boards-v1','repair-storyboards':'death-exception-boards-v2','repair-direction':'death-exception-boards-v3'}[action]})
   self.change(lambda s:s['operations'].update(storyboards={'status':'submitted','at':NOW(),'batchId':batch['batch']['id']}))
   return batch
  if action not in ('previs','videos','edit','assemble'):raise ActionError('未知制作步骤。')
  with self.lock:
   s=self.read();old=s['operations'].get(action,{})
   if action in self.workers or old.get('status')=='running':return {'ok':True,'alreadyStarted':True}
   if old.get('status')=='completed' and (action!='previs' or old.get('sourceRevision')==self.source_revision()):return {'ok':True,'alreadyStarted':True}
   method=getattr(self,'do_'+action,None)
   if method is None:raise ActionError('该步骤尚未准备好。',409)
   if action=='previs' and not all(x['status']=='approved' for x in self.state()['characters']):raise ActionError('请先选用角色卡。',409)
   if action=='previs' and old.get('status')=='completed':s.setdefault('previsHistory',[]).append(old)
   s['operations'][action]={'status':'running','startedAt':NOW(),'message':'已开始'};atomic_json(self.path,s)
   worker=threading.Thread(target=self.execute,args=(action,method),daemon=True);self.workers[action]=worker;worker.start()
  return {'ok':True,'started':action}
 def execute(self,action,method):
  try:
   result=method();self.change(lambda s:s['operations'][action].update(status='completed',completedAt=NOW(),**(result or {})))
  except Exception as e:
   message=e.message if isinstance(e,ActionError) else '执行未完成，日志已保存；没有自动重复扣分。'
   self.change(lambda s:s['operations'][action].update(status='failed',error=message,failedAt=NOW()))
   with (self.folder/(action+'-error.log')).open('a') as f:f.write(type(e).__name__+'\n')
  finally:
   with self.lock:self.workers.pop(action,None)
 def command(self,args,log,cwd=None):
  with (self.folder/log).open('w') as f:r=subprocess.run(list(map(str,args)),cwd=cwd or self.project,stdout=f,stderr=subprocess.STDOUT)
  if r.returncode:raise ActionError('本地制作步骤失败，请检查 '+log,500)
 def do_videos(self):
  from production_video import run_batch
  return run_batch(self)
 def do_edit(self):
  from production_edit import prepare_edit
  return prepare_edit(self)
 def do_assemble(self):
  from production_edit import render_final
  return render_final(self)
 def do_previs(self):
  media=self.folder/'media';media.mkdir(exist_ok=True)
  revision=self.source_revision();master=f'white-master-{revision}.mp4';segments=[f'white-{revision}-{i+1:02d}.mp4' for i in range(4)]
  self.command(['npx','--yes','hyperframes@0.8.185','check','--samples','7','--timeout','30000','--json'],'previs-check.json')
  self.command(['npx','--yes','hyperframes@0.8.185','render','--quality','looks','--fps','24','--output',media/master],'previs-render.log')
  probe=json.loads(subprocess.check_output(['/opt/homebrew/bin/ffprobe','-v','error','-show_streams','-show_format','-of','json',str(media/master)]))
  if abs(float(probe['format']['duration'])-60)>.1:raise ActionError('白模时长不符合60秒。')
  for i in range(4):
   self.command(['/opt/homebrew/bin/ffmpeg','-y','-ss',str(i*15),'-i',media/master,'-t','15','-an','-c:v','libx264','-crf','19','-pix_fmt','yuv420p','-movflags','+faststart',media/segments[i]],f'white-split-{i+1}.log')
  if revision!=self.source_revision():raise ActionError('白模动作在导出期间发生变更，请重新导出当前版本。',409)
  return {'file':'media/'+master,'duration':60,'width':720,'height':1280,'sourceRevision':revision,'segments':['media/'+s for s in segments]}
