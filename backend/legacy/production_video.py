"""Four durable LibTV video jobs. A submitted job is recovered, never resubmitted."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib, json, shutil, subprocess, uuid
from production_actions import ActionError, atomic_json
from datetime import datetime, timezone
from production_revision import selected_references

def now(): return datetime.now(timezone.utc).isoformat()
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def node_data(result): return result.get('data', result.get('node', {}).get('data', {}))
def probe(path):
    return json.loads(subprocess.check_output(['/opt/homebrew/bin/ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)]))

def check_preflight(data, refs):
    p=data.get('params',{}); s=p.get('settings',{})
    if p.get('model')!='Seedance 2.5' or p.get('modeType')!='mixed2video' or p.get('count')!=1:
        raise ActionError('视频模型或参考模式未正确写入，未提交生成。')
    if any(str(s.get(k))!=v for k,v in {'ratio':'9:16','resolution':'720p','duration':'15','enableSound':'on'}.items()):
        raise ActionError('视频画幅、分辨率、时长或声音设置不匹配，未提交生成。')
    videos=p.get('videoList',[]); images=p.get('imageList',[])
    if len(videos)!=1 or abs(float(videos[0].get('durationSec',0))-15)>.1:
        raise ActionError('必须接入覆盖全段的 15 秒白模视频。')
    got={x.get('nodeId') for x in videos+images}
    if got!={x['nodeKey'] for x in refs}:
        raise ActionError('参考连线不完整，未提交生成。')
    return {'model':p['model'],'modeType':p['modeType'],'count':1,'settings':s,
            'videoReferences':len(videos),'imageReferences':len(images),'whiteDuration':videos[0]['durationSec']}

def selected_boards(state):
    selection=state.get('boardSelection')
    if state.get('runId')=='gift-hears-thoughts-60s':
        if not selection or selection.get('sourceRevision')!=state.get('sourceRevision') or selection.get('status')!='passed':
            raise ActionError('当前白模的逐镜三选一与剧本审核尚未通过。',409)
        out=[]
        for sh in state['shots']:
            chosen=selection.get('shots',{}).get(sh['id'],{})
            item=next((t for t in state['storyboards'] if t['id']==chosen.get('taskId')),None)
            if not item or item.get('humanReview')!='approved' or item.get('contentSha256')!=chosen.get('sha256') or chosen.get('blockers'):
                raise ActionError(sh['id']+' 的已选分镜缺失、版本已变化或仍有错误。',409)
            if len(chosen.get('candidateReviews',[]))<3:
                raise ActionError(sh['id']+' 尚未完成三个候选的对照审查。',409)
            out.append(item)
        return out
    out=[]
    for sh in state['shots']:
        items=[t for t in state['storyboards'] if t.get('characterId')==sh['id'].lower()]
        if not items or items[-1].get('humanReview')!='approved':
            raise ActionError('请先选用全部最新分镜。',409)
        out.append(items[-1])
    return out

def run_batch(owner):
    state=owner.state(); previs=state['operations'].get('previs',{})
    if previs.get('status')!='completed' or state['previsNeedsRebuild']:
        raise ActionError('请先导出当前动作版本的 60 秒白模。',409)
    boards=selected_boards(state)
    with owner.execution.lock:
        manifest=owner.execution.read()
    cards={t['characterId']:t for t in manifest['tasks'] if t.get('batchId')=='death-exception-cards-v1' and t.get('generated') and t.get('humanReview')=='approved'}
    if owner.config.get('characterTaskIds'):
        byid={t['id']:t for t in manifest['tasks']}
        cards={key:byid[tid] for key,tid in owner.config['characterTaskIds'].items() if byid[tid].get('humanReview')=='approved'}
    if state.get('revision',1)>=2:
        current=[t for t in manifest['tasks'] if t.get('batchId')=='death-exception-ye-style-v2' and t.get('generated') and t.get('phase')=='refine' and t.get('humanReview')=='approved']
        if not current:raise ActionError('叶宇新版精修角色卡尚未选用，不能回退到旧造型生成视频。',409)
        cards['ye']=current[-1]
    if set(cards)!={'ye','feng','shi'}:raise ActionError('角色卡尚未选齐。',409)
    provider=owner.execution.libtv
    account=provider.call('account','info').get('activeAccount',{}).get('accountId')
    if str(account)!=str(manifest.get('generationSettings',{}).get('accountId')):
        raise ActionError('当前 LibTV 账号与工作台连接不一致。',409)
    schema=provider.call('model','star-video2.5')['schema']
    if 'mixed2video' not in schema['properties']['modeType']['items']:raise ActionError('当前模型未提供全能参考。')
    plan=json.loads((owner.folder/('video-plan-v2.json' if state.get('revision',1)>=2 else 'video-plan.json')).read_text())
    reference_assets=selected_references(state) if state.get('revision',1)>=2 else {}
    for key,tid in plan.get('referenceTaskIds',{}).items():
        t=next((x for x in manifest['tasks'] if x['id']==tid and x.get('humanReview')=='approved'),None)
        if not t:raise ActionError('场景或道具参考尚未选用。',409)
        reference_assets[key]=t
    if not plan.get('readyForVideo',True):
        raise ActionError('新版镜头参考仍在审查，尚未开放视频提交。',409)
    jobs=state['videoJobs']
    if not jobs:
        jobs=[]
        for i,clip in enumerate(plan['clips']):
            white=owner.folder/previs['segments'][i]; white_probe=probe(white)
            if abs(float(white_probe['format']['duration'])-15)>.1:raise ActionError('白模分段时长错误。')
            refs=[{'name':'白模全段15秒','type':'video','file':str(white.resolve()),'sha256':digest(white),'use':'motion'}]
            for key in clip['characters']:
                t=cards[key];path=owner.root/t['file']
                refs.append({'name':t['catalog']['entityName']+'角色卡','type':'image','file':str(path.resolve()),'sha256':digest(path),'use':key})
            for shid in clip['shots']:
                t=next(t for t in boards if t['characterId']==shid.lower());path=owner.root/t['file']
                refs.append({'name':shid+'分镜美术','type':'image','file':str(path.resolve()),'sha256':digest(path),'use':shid})
            for refid in clip.get('referenceIds',[]):
                t=reference_assets[refid];path=owner.root/t['file']
                refs.append({'name':t['catalog']['entityName'],'type':'image','file':str(path.resolve()),'sha256':digest(path),'use':refid})
            jobs.append({'id':'film-'+uuid.uuid4().hex,'title':clip['title'],'index':i,'status':'queued','message':'待准备参考',
                         'createdAt':now(),'sourceRevision':previs['sourceRevision'],'references':refs,'clip':clip,
                         'revision':state.get('revision',1),'planSnapshot':plan,
                         'model':'Seedance 2.5','resolution':'720p','ratio':'9:16','duration':15,'costCredits':None,
                         'costStatus':'尚未取得本任务积分凭证','submittedCount':0,'accountId':account})
        owner.change(lambda s:s.update(videoJobs=jobs))
    # A retry only visits existing jobs. submitStartedAt permanently protects paid calls.
    def one(job):
        jid=job['id']
        def update(**fields):
            job.update(fields)
            owner.change(lambda s:next(j for j in s['videoJobs'] if j['id']==jid).update(fields))
        try:
            if job['status']=='completed':return
            if job.get('sourceRevision')!=previs['sourceRevision']:raise ActionError('白模已更新，旧任务需单独核对，未重复生成。')
            for ref in job['references']:
                if digest(ref['file'])!=ref['sha256']:raise ActionError('参考文件已变更，未提交旧任务。')
            update(status='preparing',message='上传完整白模与本段人物、分镜参考')
            if not job.get('projectId'):
                name='大师兄60秒 · '+job['title']+' · '+jid
                listed=provider.call('project','list','--name',jid[-8:])
                matches=[p for p in listed.get('projectMetaList',[]) if p.get('name')==name]
                if len(matches)>1:raise ActionError('存在多个同名画布，请核对原任务。')
                project=matches[0] if matches else provider.call('project','create',name)
                pid=project.get('uuid') or project.get('projectUuid')
                if not pid:
                    listed=provider.call('project','list','--name',jid[-8:])
                    matches=[p for p in listed.get('projectMetaList',[]) if p.get('name')==name]
                    pid=matches[0].get('uuid') if len(matches)==1 else None
                if not pid:raise ActionError('画布编号未返回；没有提交生成。')
                update(projectId=pid,projectUrl='https://www.liblib.tv/canvas?projectId='+pid)
            pid=job['projectId'];refs=list(job.get('uploadedReferences',[]))
            for i,ref in enumerate(job['references']):
                if i<len(refs):continue
                uploaded=provider.call('upload',ref['name'],'-p',pid,'-t',ref['type'],'-f',ref['file'],timeout=180)
                key=uploaded.get('nodeKey')
                if not key:raise ActionError('参考上传未返回节点，未提交生成。')
                refs.append({**ref,'nodeKey':key});update(uploadedReferences=refs)
            contract=job.get('planSnapshot',plan)
            reftext='\n'.join('{{Node '+r['nodeKey']+'}}：'+r['name']+('，动作、镜位、剪切时间基准。' if r['type']=='video' else '，按名称绑定身份、镜头或指定文字效果；不得把整张参考排版当作镜头。') for r in refs)
            prompt=contract['visualContract']+'\n\n参考定义：\n'+reftext+'\n\n'+job['clip']['direction']+'\n\n'+contract['soundContract']
            if not job.get('nodeKey'):
                args=['node','--x','850','--y','100','create','成片-'+jid,'-p',pid,'-t','video','--prompt',prompt,
                      '-s','model=Seedance 2.5','-s','modeType=mixed2video','-s','count=1',
                      '-s','ratio=9:16','-s','resolution=720p','-s','duration=15','-s','enableSound=on',
                      '-s','searchEnabled=0','-s','autoCompliance=1']
                for r in refs:args+=['--left',r['nodeKey']]
                node=provider.call(*args);key=node.get('nodeKey') or node.get('newNodeKey')
                if not key:raise ActionError('视频节点编号未返回；没有提交生成。')
                update(nodeKey=key,effectivePrompt=prompt)
            key=job['nodeKey']
            if job.get('submitStartedAt'):
                update(message='仅核对原任务结果，不重新提交')
                provider.recover_result(pid,key)
            else:
                preflight=check_preflight(node_data(provider.call('node',key,'-p',pid)),refs)
                update(preflight=preflight,status='running',message='Seedance 2.5 生成中 · 完整15秒白模已提交',submitStartedAt=now(),submittedCount=1)
                provider.run(pid,key)
                update(generationCompletedAt=now())
            update(status='downloading',message='正在下载并核验视频')
            folder=provider.runtime/'downloads'/jid;folder.mkdir(parents=True,exist_ok=True)
            result=provider.call('download','-n',key,'-p',pid,'--watermark','false','-o',folder,timeout=180,plain=True)
            paths=[Path(x.strip()).resolve() for x in result.splitlines() if x.strip()]
            if len(paths)!=1 or not paths[0].is_relative_to(folder.resolve()) or not paths[0].is_file():raise ActionError('视频下载结果需核对；原生成已保留。')
            p=probe(paths[0]);v=next(x for x in p['streams'] if x['codec_type']=='video');a=[x for x in p['streams'] if x['codec_type']=='audio']
            duration=float(p['format']['duration'])
            if abs(duration-15)>.2 or v['width']!=720 or v['height']!=1280:raise ActionError('视频时长或尺寸不符合15秒720p竖版；原结果已保留。')
            target=owner.folder/'media'/('clip-'+str(job['index']+1).zfill(2)+'-'+jid[-8:]+'.mp4')
            shutil.copy2(paths[0],target)
            update(status='completed',message='已生成 · 待成片审片',file='media/'+target.name,completedAt=now(),
                   actualDuration=duration,width=v['width'],height=v['height'],hasAudio=bool(a),sha256=digest(target))
        except Exception as exc:
            message=exc.message if isinstance(exc,ActionError) else '上游操作未完成；保留原画布，恢复时不会重复扣分。'
            update(status='needs_attention',message=message,errorType=type(exc).__name__)
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(one,jobs))
    current=owner.read()['videoJobs']
    if not all(j['status']=='completed' for j in current):raise ActionError('部分视频需要核对，可恢复原任务；已成功的视频保留。',409)
    return {'count':4,'message':'4段视频已生成，等待审片与字幕合成'}
