"""A geometry-checked material preview, not a final production renderer."""
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

LABELS={'main':'主视角','reverse':'反打','overhead':'正俯视','side':'侧面'}
PRESETS={'natural':'自然木石','warm':'暖阳木石','cool':'清冷青灰'}


def render_preview(root,job,progress,stopping):
    from PIL import Image
    source=root/'consistency-v2/scene.json'
    script=Path(__file__).resolve().parent/'consistency-v2/render_scene.py'
    scene=json.loads(source.read_text())
    expected=job['geometryRevision']['fingerprint']
    if scene['meshSha256']!=expected:
        raise ValueError('白模已更新，请基于当前白模重新制作预览。')
    folder=root/'generated'/job['id'];folder.mkdir(parents=True,exist_ok=True)
    snapshot=folder/'input-scene.json';snapshot.write_text(json.dumps(scene,ensure_ascii=False,indent=2))
    preset=job.get('materialPreset','warm')
    log=folder/'render.log'
    with log.open('w') as out:
        process=subprocess.Popen([sys.executable,str(script),'--output-dir',str(folder),'--source-scene',str(snapshot),'--expected-mesh',expected,'--preset',preset],stdout=out,stderr=subprocess.STDOUT)
        deadline=time.monotonic()+240
        count=-1
        while process.poll() is None:
            if stopping.is_set() or time.monotonic()>deadline:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait()
                raise ValueError('本地渲染已停止，可稍后重试。')
            done=sum((folder/(v+'-guide.png')).exists() for v in LABELS)
            if done!=count:
                progress(done);count=done
            stopping.wait(.5)
    if process.returncode:
        raise ValueError('本地渲染未完成；请检查白模版本和渲染日志。')
    metadata=json.loads((folder/'scene.json').read_text())
    if metadata['meshSha256']!=expected or metadata['cameras']!=scene['cameras']:
        raise ValueError('渲染结果的白模或机位不一致，未作为完成结果保存。')
    views=[]
    for view,label in LABELS.items():
        path=folder/(view+'-guide.png')
        with Image.open(path) as image:
            image.verify()
            if image.size!=(1536,864):raise ValueError('预览图画幅不符合16:9。')
        views.append({'view':view,'label':label,'file':str(path.relative_to(root)),'pixels':[1536,864],
                      'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    fingerprint=hashlib.sha256(json.dumps(views,sort_keys=True).encode()).hexdigest()
    return {'views':views,'contentSha256':fingerprint,'meshSha256':expected,'materialPreset':preset,
            'renderRecord':str((folder/'scene.json').relative_to(root)),'renderer':'local_shared_geometry',
            'qualityTier':'material_preview','externalCreditsUsed':0}
