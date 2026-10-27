"""Persist actual model renders and create a geometry-locked refinement batch."""
import base64, hashlib, io, json, math
from PIL import Image
from production_actions import ActionError, atomic_json
from character_batches import start_batch

SCENES={'residence-gate':'府邸门口','residence-hall':'府邸正堂','grand-hall':'万宗大殿','summit':'峰顶草地','rescue':'施救现场','arena':'演武场','mountain-path':'琳琅峰山道'}
VIEWS={'main':'主视角','reverse':'反打','overhead':'俯视','side':'侧面'}
def source_revision(root):
    folder=root.parent/'dashixiong-scene-studio';h=hashlib.sha256()
    for n in ('scenes.js','geometry.js','catalog.js','material-library.js','app.js'):
        h.update(n.encode());h.update((folder/n).read_bytes())
    for p in sorted((folder/'textures').glob('*')):h.update(p.name.encode());h.update(p.read_bytes())
    return h.hexdigest()[:16]

def save_frame(execution,payload):
    sid=payload.get('sceneId');view=payload.get('view');mode=payload.get('mode')
    if sid not in SCENES or view not in VIEWS or mode not in ('clay','material'):raise ActionError('场景或视角无效')
    revision=source_revision(execution.root)
    if payload.get('sourceRevision')!=revision:raise ActionError('场景材质已变化，请刷新再导出。',409)
    geometry=payload.get('geometry');camera=payload.get('camera');light=payload.get('lighting')
    if not isinstance(geometry,dict) or not isinstance(camera,dict) or not isinstance(light,dict):raise ActionError('缺少模型、机位或灯光记录')
    def finite(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
    for k in ('position','target','up'):
        if not isinstance(camera.get(k),list) or len(camera[k])!=3 or not all(finite(v) for v in camera[k]):raise ActionError('机位无效')
    if not finite(camera.get('fov')) or not 5<=camera['fov']<=140:raise ActionError('焦距无效')
    raw=payload.get('image','')
    try:
        if not isinstance(raw,str) or not raw.startswith('data:image/png;base64,') or len(raw)>8*1024*1024:raise ValueError()
        data=base64.b64decode(raw.split(',',1)[1],validate=True);im=Image.open(io.BytesIO(data));im.verify()
        if im.size!=(1536,864):raise ValueError()
    except Exception:raise ActionError('场景参考必须为1536×864 PNG')
    scene_hash=hashlib.sha256((revision+json.dumps([geometry,light],sort_keys=True,ensure_ascii=False,allow_nan=False)).encode()).hexdigest()[:16]
    sha=hashlib.sha256(data).hexdigest();folder=execution.root/'references/scene-models'/sid/scene_hash;folder.mkdir(parents=True,exist_ok=True)
    relative=f'references/scene-models/{sid}/{scene_hash}/{view}-{mode}-{sha[:8]}.png';path=execution.root/relative
    with execution.lock:
        if not path.exists():path.write_bytes(data)
        mf=folder/'manifest.json';pack=json.loads(mf.read_text()) if mf.exists() else {'schema':'scene-model-reference/1','sceneId':sid,'name':SCENES[sid],'sourceRevision':revision,'sceneRevision':scene_hash,'geometry':geometry,'lighting':light,'frames':[]}
        entry={'view':view,'mode':mode,'file':relative,'sha256':sha,'camera':camera,'roofVisible':payload.get('roofVisible'),'materials':payload.get('materials',[])}
        pack['frames']=[x for x in pack['frames'] if (x['view'],x['mode'])!=(view,mode)]+[entry];atomic_json(mf,pack)
        atomic_json(execution.root/'references/scene-models'/sid/'latest.json',{'manifest':str(mf.relative_to(execution.root)),'sceneRevision':scene_hash})
        m=execution.read();tid=f'scene-model-{sid}-{view}-{mode}-{sha[:12]}'
        if not any(t['id']==tid for t in m['tasks']):
            m['tasks'].append({'id':tid,'title':SCENES[sid]+' · '+VIEWS[view]+' · '+('白模' if mode=='clay' else '材质渲染'),'file':relative,'contentSha256':sha,'ratio':'16:9','entity':'scene','generated':True,'phase':'model-render','humanReview':'pending','sceneRevision':scene_hash,'catalog':{'seriesId':'dashixiong','seriesTitle':'别惹大师兄','category':'scene','entityId':sid,'entityName':SCENES[sid],'kind':'white-model' if mode=='clay' else 'material-render','variant':VIEWS[view],'version':1}});execution.write(m)
    return {'ok':True,'sceneId':sid,'sceneRevision':scene_hash,'count':len(pack['frames']),'manifest':str(mf.relative_to(execution.root))}

def generate(execution,payload):
    sid=payload.get('sceneId')
    if sid not in SCENES:raise ActionError('场景无效')
    latest=execution.root/'references/scene-models'/sid/'latest.json'
    if not latest.exists():raise ActionError('请先输出同一模型的四视图。')
    info=json.loads(latest.read_text());pack=json.loads((execution.root/info['manifest']).read_text())
    if pack['sourceRevision']!=source_revision(execution.root) or payload.get('sceneRevision')!=pack['sceneRevision']:raise ActionError('参考版本已变化，请重新输出四视图。',409)
    frames={(x['view'],x['mode']):x for x in pack['frames']}
    if set(frames)!={(v,m) for v in VIEWS for m in ('clay','material')}:raise ActionError('白模和彩色渲染需各四张。')
    batchid=f'scene-{sid}-{pack["sceneRevision"]}';chars=[]
    for view,label in VIEWS.items():
        white=frames[view,'clay'];color=frames[view,'material']
        prompt=f'对输入的{SCENES[sid]}三维模型渲染做材质精修。第一张为{label}白模，第二张为完全相同机位的材质渲染。严格保持第一张的摄影机透视、轮廓、建筑与家具位置、数量、遮挡和所有空间关系。按第二张的既定材质配色与受光方向提升精致3D国漫CG质感：旧木纹、青石颗粒、青灰瓦、灰白抹灰墙、古铜金属。只提高表面细节与柔和真实反射，不能重设计建筑，不能增加或移走椅子门窗柱子树木，不能换机位，不出现人物、字样、水印。只输出单张16:9全景。'
        if not color['roofVisible']:prompt+=' 屋顶按参考隐藏以展示内部空间，不补回遮挡屋顶。'
        chars.append({'id':view,'name':SCENES[sid]+' '+label,'entityId':sid,'entityName':SCENES[sid],'category':'scene','kind':'scene-render','variant':label+' / '+pack['sceneRevision'],'phase':'asset','modelKey':'lib-image-2.5-s','ratio':'16:9','generationCount':1,'references':[white['file'],color['file']],'prompt':prompt,'pipelineRecipe':{'id':batchid+'-'+view,'variant':label+' / '+pack['sceneRevision'],'models':{'asset':'lib-image-2.5-s','refine':'nebula-2.1'},'assetView':view,'refinePrompt':'严格保持本场景图的机位、建筑结构、所有物体位置数量、色彩与光照，只修复材质噪点和边缘。禁止改变任何构图和空间，不加人物或文字。'}})
    atomic_json(execution.root/'batches'/f'{batchid}.json',{'id':batchid,'title':SCENES[sid]+' · 模型四视图','outputRequirements':'四个独立任务，各一张16:9，不拼图。严格保持每个输入白模的空间结构。','instruction':'以对应白模为几何依据，以对应三维材质图为材质与光照依据。','reviewPolicy':'AI代审测试','characters':chars,'sceneRevision':pack['sceneRevision']})
    return start_batch(execution,{'batchId':batchid})
