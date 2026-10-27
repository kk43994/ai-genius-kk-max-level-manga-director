"""Durable planning contracts. Saving a plan never submits a paid generation."""
from pathlib import Path
import json, math, hashlib, copy
from datetime import datetime, timezone
from production_actions import ActionError, atomic_json

PROJECTS={'probe-divine-body','death-exception-60s','gift-hears-thoughts-60s'}
def contract_path(root,project):
    if project not in PROJECTS:raise ActionError('未知镜头工程')
    return root.parent/'dashixiong-scene-studio/production'/project/'shot-contracts.json'
def state(owner,project='death-exception-60s'):
    path=contract_path(owner.root,project)
    data=json.loads(path.read_text()) if path.exists() else {'revision':0,'shots':[],'repairs':[]}
    if project==getattr(owner,'run_id','death-exception-60s'):data['currentSourceRevision']=owner.source_revision()
    data['stale']=bool(data.get('sourceRevision') and data.get('currentSourceRevision') and data['sourceRevision']!=data['currentSourceRevision'])
    return data

def validate_shots(shots,expected=None):
    if not isinstance(shots,list) or not 1<=len(shots)<=100:raise ActionError('镜头数据缺失')
    ids=[]
    for sh in shots:
        if not isinstance(sh,dict) or sh.get('schema')!='manju-shot-contract/1':raise ActionError('镜头数据版本不支持')
        sid=sh.get('id');ids.append(sid)
        if not isinstance(sid,str) or len(sid)>50:raise ActionError('镜号无效')
        if not all(isinstance(sh.get(k),(int,float)) and math.isfinite(sh[k]) for k in ('start','end')) or sh['end']<=sh['start']:raise ActionError('镜头时长无效')
        if sh.get('aspect') not in ['9:16','16:9','21:9']:raise ActionError('画幅无效')
        samples=sh.get('samples',[])
        if not 3<=len(samples)<=150:raise ActionError('每镜至少需要起点、过程、落点的实际预演采样')
        times=[]
        for sample in samples:
            t=sample.get('t');times.append(t)
            if not isinstance(t,(int,float)) or not math.isfinite(t) or not sh['start']<=t<=sh['end']:raise ActionError('采样时间无效')
            camera=sample.get('camera',{})
            for key in ['p','target']:
                a=camera.get(key)
                if not isinstance(a,list) or len(a)!=3 or not all(isinstance(n,(int,float)) and math.isfinite(n) for n in a):raise ActionError('机位坐标无效')
            if not isinstance(camera.get('lens'),(int,float)) or not 5<=camera['lens']<=300:raise ActionError('焦距无效')
            for actor in sample.get('actors',[]):
                if not isinstance(actor.get('yaw'),(int,float)) or not math.isfinite(actor['yaw']):raise ActionError('人物朝向无效')
        if times!=sorted(set(times)):raise ActionError('采样时刻重复或未排序')
        if abs(times[0]-sh['start'])>.04 or abs(times[-1]-sh['end'])>.04:raise ActionError('采样未覆盖镜头首尾')
    if len(ids)!=len(set(ids)):raise ActionError('镜号重复')
    if expected:
        if set(ids)!={s['id'] for s in expected}:raise ActionError('需要完整的 12 镜计划')
        byid={s['id']:s for s in expected}
        if any((s['start'],s['end'])!=(byid[s['id']]['start'],byid[s['id']]['end']) for s in shots):raise ActionError('镜头时段与当前成片计划不一致')


def save(owner,payload):
    project=payload.get('projectId');path=contract_path(owner.root,project)
    with owner.lock:
        old=state(owner,project)
        if payload.get('expectedRevision')!=old['revision']:raise ActionError('计划已变化，请重新载入再保存。',409)
        shots=copy.deepcopy(payload.get('shots'))
        expected=json.loads((owner.folder/'shots.json').read_text()) if project==getattr(owner,'run_id','death-exception-60s') else None
        validate_shots(shots,expected)
        source=payload.get('sourceRevision')
        if project==getattr(owner,'run_id','death-exception-60s') and source!=owner.source_revision():raise ActionError('白模源文件已更新，请重新读取预演。',409)
        # References are validated from the library, never from the client status label.
        with owner.execution.lock:m=owner.execution.read()
        tasks={t['id']:t for t in m['tasks']}
        for sh in shots:
            for ref in sh.get('references',[]):
                t=tasks.get(ref.get('id'))
                if not t or t.get('humanReview')!='approved':raise ActionError('只允许锁定已选用的参考素材。',409)
                file=(owner.root/t['file']).resolve()
                if not file.is_relative_to(owner.root.resolve()) or not file.is_file():raise ActionError('参考素材路径无效')
                sha=hashlib.sha256(file.read_bytes()).hexdigest()
                if ref.get('sha256')!=sha:raise ActionError('参考图已变化，请重新绑定。',409)
                ref.update(status='approved',file=t['file'],sha256=sha)
            sh['visualReview']={'status':'pending','reviewer':'ai','policy':'delegated-test-review'}
        new={'schema':'manju-director-package/1','projectId':project,'revision':old['revision']+1,'sourceRevision':source,'shots':shots,'repairs':old.get('repairs',[]),'updatedAt':datetime.now(timezone.utc).isoformat(),'reviewPolicy':{'mode':'ai-delegated','humanGate':False,'reason':'user_requested_test_phase'},'generationStarted':False}
        path.parent.mkdir(parents=True,exist_ok=True)
        (path.parent/'contract-history').mkdir(exist_ok=True)
        if old['revision']:atomic_json(path.parent/'contract-history'/f"r{old['revision']:04d}.json",old)
        atomic_json(path,new)
        return {'ok':True,**new}

def repair(owner,payload):
    project=payload.get('projectId');path=contract_path(owner.root,project)
    with owner.lock:
        data=state(owner,project)
        if payload.get('expectedRevision')!=data['revision']:raise ActionError('计划已变化，请刷新。',409)
        shot=next((s for s in data['shots'] if s['id']==payload.get('shotId')),None)
        note=payload.get('problem','').strip()
        if not shot or len(note)<2 or len(note)>2000:raise ActionError('请选择镜头并填写具体问题')
        entry={'shotId':shot['id'],'baseHash':shot['geometryHash'],'problem':note,'keep':['其他镜头','已锁定人物身份与服装','环境布局'],'references':shot.get('references',[]),'at':datetime.now(timezone.utc).isoformat(),'status':'planned','generationStarted':False}
        data.setdefault('repairs',[]).append(entry);data['revision']+=1;atomic_json(path,data)
        return {'ok':True,'repair':entry,'revision':data['revision']}


def save_frame(owner,payload):
    import base64,io,re
    from PIL import Image
    project=payload.get('projectId');contract_path(owner.root,project)
    if project!=owner.run_id or payload.get('sourceRevision')!=owner.source_revision():raise ActionError('白模已变化，请重新提取。',409)
    sid=payload.get('shotId');index=payload.get('index');t=payload.get('time')
    shots=json.loads((owner.folder/'shots.json').read_text())
    shot=next((x for x in shots if x['id']==sid),None)
    if not shot or index not in (0,1,2) or not isinstance(t,(int,float)) or not shot['start']<=t<=shot['end']:raise ActionError('参考帧镜号或时刻无效')
    raw=payload.get('image','')
    if not isinstance(raw,str) or not raw.startswith('data:image/png;base64,') or len(raw)>2*1024*1024:raise ActionError('参考帧格式无效')
    try:
        data=base64.b64decode(raw.split(',',1)[1],validate=True)
        im=Image.open(io.BytesIO(data));im.verify()
        if im.size!=(720,1280):raise ValueError()
    except Exception:raise ActionError('参考帧必须为720×1280 PNG')
    sha=hashlib.sha256(data).hexdigest();revision=owner.source_revision()
    relative=f'references/{project}/{revision}/{sid}-{index}-{sha[:8]}.png'
    path=owner.root/relative;path.parent.mkdir(parents=True,exist_ok=True)
    with owner.lock:
        if not path.exists():path.write_bytes(data)
        mf=owner.folder/'frame-manifest.json'
        frames=json.loads(mf.read_text()) if mf.exists() else {'frames':[]}
        if frames.get('sourceRevision')!=revision:frames={'frames':[]}
        entry={'shotId':sid,'index':index,'time':t,'file':relative,'sha256':sha}
        frames['frames']=[f for f in frames['frames'] if (f['shotId'],f['index'])!=(sid,index)]+[entry]
        frames.update(sourceRevision=revision,projectId=project)
        atomic_json(mf,frames)
    return {'ok':True,**entry}
