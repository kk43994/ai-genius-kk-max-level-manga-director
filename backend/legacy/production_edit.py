"""Build and render an editable, source-linked 60 second film from reviewed jobs."""
from pathlib import Path
import hashlib, html, json, re, shutil, subprocess
from production_actions import ActionError, atomic_json
from production_video import probe, digest

def project(owner):
    name='dashixiong-gift-final' if owner.run_id=='gift-hears-thoughts-60s' else 'dashixiong-death-final'
    return owner.workspace/'videos'/name

def film_slug(owner):
    return '御空赴约-赠礼惊心' if owner.run_id=='gift-hears-thoughts-60s' else '她的死期'
def revision(folder):
    h=hashlib.sha256()
    for name in ['index.html','compositions/captions.html','compositions/readouts.html','edit.json']:
        h.update((folder/name).read_bytes())
    return h.hexdigest()[:12]

def prepare_edit(owner):
    state=owner.read();jobs=sorted(state['videoJobs'],key=lambda j:j['index'])
    if len(jobs)!=4 or not all(j['status']=='completed' and j.get('review',{}).get('accepted') and j['review'].get('sha256')==j.get('sha256') for j in jobs):
        raise ActionError('请先审看并选用 4 段视频。',409)
    edit=json.loads((owner.folder/'edit.json').read_text())
    if edit.get('captionReview')!='verified':raise ActionError('字幕尚未按实际对白核对。',409)
    folder=project(owner);folder.mkdir(parents=True,exist_ok=True);(folder/'compositions').mkdir(exist_ok=True)
    for name in ('package.json','AGENTS.md'):
        if not (folder/name).exists():shutil.copy2(owner.project/name,folder/name)
    assets=folder/'assets';assets.mkdir(exist_ok=True);(assets/'fonts').mkdir(exist_ok=True)
    shutil.copyfile('/System/Library/Fonts/STHeiti Medium.ttc',assets/'fonts/Heiti.ttc')
    sources=[];tags=[]
    for i,j in enumerate(jobs):
        src=owner.folder/j['file']
        if digest(src)!=j['sha256']:raise ActionError('视频文件已变化，请重新审片。')
        if not j.get('hasAudio'):raise ActionError('视频缺少声音，请先补齐对白与音效。')
        name=f'clip-{i+1:02d}.mp4';shutil.copy2(src,assets/name)
        poster=owner.folder/'media'/f'clip-{i+1:02d}-poster.jpg'
        owner.command(['/opt/homebrew/bin/ffmpeg','-y','-ss','2','-i',src,'-frames:v','1','-q:v','2',poster],f'poster-{i+1}.log')
        sources.append({'id':j['id'],'source':j['file'],'asset':'assets/'+name,'sha256':j['sha256'],'start':i*15,'duration':15,'model':j['model']})
        owner.change(lambda s:next(x for x in s['videoJobs'] if x['id']==j['id']).update(poster='media/'+poster.name))
        tags.append(f'<video id="part-{i+1}" class="clip footage" src="assets/{name}" data-start="{i*15}" data-duration="15" data-media-start="0" data-has-audio="true" data-track-index="0" data-volume="1" playsinline preload="auto"></video>')
    atomic_json(folder/'edit.json',edit);atomic_json(folder/'sources.json',sources)
    root='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=720,height=1280"><title>她的死期，竟然看不见</title><script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script><style>*{box-sizing:border-box;margin:0;padding:0}html,body{width:720px;height:1280px;overflow:hidden;background:#10151d}#root{position:relative;width:720px;height:1280px;overflow:hidden}.clip{position:absolute;inset:0}.footage{width:720px;height:1280px;object-fit:contain}.overlay{pointer-events:none;background:transparent;z-index:20}</style></head><body><div id="root" data-composition-id="death-final" data-start="0" data-duration="60" data-width="720" data-height="1280" data-fps="24">'''+''.join(tags)+'''<div id="readouts" class="clip overlay" data-composition-id="readouts" data-composition-src="compositions/readouts.html" data-start="0" data-duration="60" data-track-index="1" data-track-kind="graphics"></div><div id="captions" class="clip overlay" data-composition-id="captions" data-composition-src="compositions/captions.html" data-start="0" data-duration="60" data-track-index="2" data-track-kind="captions"></div></div><script>const tl=gsap.timeline({paused:true});tl.to({time:0},{time:60,duration:60,ease:'none'},0);window.__timelines=window.__timelines||{};window.__timelines['death-final']=tl;</script></body></html>'''
    root=root.replace('她的死期，竟然看不见',html.escape(owner.config['title'])).replace('death-final',folder.name)
    # Optional reviewed dialogue, music and foley stay separate and editable.
    if edit.get('replaceNativeAudio'):
        root=root.replace('data-has-audio="true"', 'muted')
    audio_tags=[]
    for i,track in enumerate(edit.get('audioTracks',[])):
        src=Path(track['source']);start=float(track['start']);duration=float(track['duration'])
        if not src.is_file() or digest(src)!=track['sha256']:raise ActionError('声音素材已变化，请重新审听。')
        if not 0<=start<60 or duration<=0 or start+duration>60.01:raise ActionError('声音时间超出成片。')
        name=f'audio-{i:02d}'+src.suffix;shutil.copy2(src,assets/name)
        attrs={'id':track['id'],'class':'clip','src':'assets/'+name,'data-start':start,'data-duration':duration,'data-media-start':track.get('mediaStart',0),'data-volume':track.get('volume',1),'data-fade-in':track.get('fadeIn',0),'data-fade-out':track.get('fadeOut',0),'data-track-index':track.get('trackIndex',3),'data-track-kind':'audio'}
        if track.get('automation'):attrs['data-automation']=json.dumps(track['automation'],ensure_ascii=False,separators=(',',':'))
        if track.get('fxChain'):attrs['data-fx-chain']=json.dumps(track['fxChain'],ensure_ascii=False,separators=(',',':'))
        audio_tags.append('<audio '+ ' '.join(k+'="'+html.escape(str(v),quote=True)+'"' for k,v in attrs.items())+'></audio>')
    root=root.replace('</div><script>const tl=', ''.join(audio_tags)+'</div><script>const tl=',1)
    (folder/'index.html').write_text(root)
    captions=[]
    for i,c in enumerate(edit['captions']):
        if not 0<=c['start']<c['end']<=60:raise ActionError('字幕时间超出成片。')
        captions.append(f'<div id="caption-{i:02d}" class="clip caption" data-start="{c["start"]}" data-duration="{c["end"]-c["start"]:.3f}"><span>{html.escape(c["text"])}</span></div>')
    caption_doc='''<template><style>@font-face{font-family:FilmHeiti;src:url('assets/fonts/Heiti.ttc')}#root{position:relative;width:720px;height:1280px;background:transparent;font-family:FilmHeiti,sans-serif}.caption{position:absolute;left:64px;top:1060px;width:592px;height:70px;text-align:center;display:flex;align-items:center;justify-content:center}.caption span{font-size:32px;line-height:1.4;font-weight:500;color:#fff;padding:5px 12px;background:rgba(10,17,24,.46);border-radius:4px;text-shadow:0 2px 3px #000;white-space:nowrap}</style><div id="root">'''+''.join(captions)+'''</div><script>const tl=gsap.timeline({paused:true});tl.to({time:0},{time:60,duration:60,ease:'none'});window.__timelines=window.__timelines||{};window.__timelines.captions=tl;</script></template>'''
    if edit.get('captionStyle',{}).get('background')=='none':
        caption_doc=caption_doc.replace('background:rgba(10,17,24,.46);border-radius:4px;text-shadow:0 2px 3px #000;', 'background:transparent;border-radius:0;-webkit-text-stroke:1px rgba(0,0,0,.85);paint-order:stroke fill;text-shadow:0 1px 2px rgba(0,0,0,.7);')
    if edit.get('captionStyle',{}).get('fontFamily')=='SimHei':
        shutil.copyfile('/Applications/Microsoft Word.app/Contents/Resources/DFonts/SimHei.ttf',assets/'fonts/SimHei.ttf')
        caption_doc=caption_doc.replace('FilmHeiti','FilmSimHei').replace("url('assets/fonts/Heiti.ttc')","url('assets/fonts/SimHei.ttf') format('truetype');font-weight:400;font-style:normal;font-display:block").replace('font-weight:500','font-weight:400')
    (folder/'compositions/captions.html').write_text(caption_doc.replace('<div id="root">','<div id="root" data-composition-id="captions" data-width="720" data-height="1280" data-duration="60">'))
    hud=[]
    for i,c in enumerate(edit['readouts']):
        hud.append(f'<div id="readout-{i}" class="clip panel" data-start="{c["start"]}" data-duration="{c["end"]-c["start"]:.3f}" style="top:{c["y"]}px;left:{c["x"]}px"><div class="panel-inner"><small>{html.escape(c["name"])}</small><strong>{html.escape(c["value"])}</strong><span>{html.escape(c.get("detail",""))}</span></div></div>')
    hud_doc='''<template><style>@font-face{font-family:FilmHeiti;src:url('assets/fonts/Heiti.ttc')}#root{position:relative;width:720px;height:1280px;background:transparent;font-family:FilmHeiti,sans-serif}.panel{position:absolute;width:270px;height:154px}.panel-inner{border-left:2px solid #ead2a2;background:rgba(18,28,35,.78);padding:13px 18px;color:#fff2d6}.panel small{display:block;font-size:23px;letter-spacing:3px}.panel strong{display:block;font-size:40px;font-weight:500;line-height:1.35}.panel span{display:block;font-size:19px;color:#ece4d4}</style><div id="root">'''+''.join(hud)+'''</div><script>const tl=gsap.timeline({paused:true});'''+''.join(f"tl.fromTo('#readout-{i} .panel-inner',{{opacity:0,y:5}},{{opacity:1,y:0,duration:.18,ease:'power2.out'}},{c['start']});" for i,c in enumerate(edit['readouts']))+'''window.__timelines=window.__timelines||{};window.__timelines.readouts=tl;</script></template>'''
    (folder/'compositions/readouts.html').write_text(hud_doc.replace('<div id="root">','<div id="root" data-composition-id="readouts" data-width="720" data-height="1280" data-duration="60">'))
    def stamp(sec):
        ms=round(sec*1000);return f'{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}'
    srt='\n\n'.join(f'{i+1}\n{stamp(c["start"])} --> {stamp(c["end"])}\n{c["text"]}' for i,c in enumerate(edit['captions']))+'\n'
    (owner.folder/'media'/(film_slug(owner)+'-字幕.srt')).write_text(srt)
    owner.command(['npx','--yes','hyperframes@0.8.185','check','--samples','12','--json'],'final-check.json',folder)
    owner.command(['npx','--yes','hyperframes@0.8.185','preview','--background'],'final-preview.log',folder)
    log=(owner.folder/'final-preview.log').read_text();urls=re.findall(r'https?://(?:localhost|127\.0\.0\.1):\d+[^\s\x1b]*',log)
    return {'project':str(folder),'revision':revision(folder),'previewUrl':urls[0].rstrip('/') if urls else None,'message':'剪辑与字幕已准备，可预览后导出'}

def render_final(owner):
    state=owner.read();prepared=state['operations'].get('edit',{});folder=project(owner)
    if prepared.get('status')!='completed' or prepared.get('revision')!=revision(folder):raise ActionError('剪辑已变化，请重新准备预览。',409)
    rev=prepared['revision'];out=owner.folder/'media'/('大师兄-'+film_slug(owner)+'-60秒-9x16-720p-'+rev+'.mp4')
    owner.command(['npx','--yes','hyperframes@0.8.185','render','--quality','delivery','--fps','24','--output',out],'final-render.log',folder)
    p=probe(out);v=next(x for x in p['streams'] if x['codec_type']=='video');audio=any(x['codec_type']=='audio' for x in p['streams'])
    if abs(float(p['format']['duration'])-60)>.15 or [v['width'],v['height']]!=[720,1280] or not audio:raise ActionError('成片时长、尺寸或声音未通过核验。')
    result={'file':'media/'+out.name,'duration':float(p['format']['duration']),'width':720,'height':1280,'hasAudio':True,'sha256':digest(out),'revision':rev,'subtitleFile':'media/'+film_slug(owner)+'-字幕.srt'}
    run=json.loads((owner.folder/'run.json').read_text());run.update(status='rendered_awaiting_final_review',final=result,videoSubmissionCount=sum(j.get('submittedCount',0) for j in state['videoJobs']));atomic_json(owner.folder/'run.json',run)
    return result
