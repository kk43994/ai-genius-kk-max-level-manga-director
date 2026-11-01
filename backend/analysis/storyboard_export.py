"""Portable illustrated screenplay from saved, version-checked production state."""
import copy
import hashlib
import io
import json
import zipfile
from html import escape

from backend.workflow.errors import WorkflowError, conflict
from backend.workflow.service import now
from .production import MENTION, shot_entity_id


def export(service, ctx, identity):
    job = service.get(ctx, identity)
    if job['status'] != 'ready' or job['stale']:
        raise WorkflowError('PRODUCTION_NOT_READY', '请先核对并保存当前分镜脚本。', 409)
    workflow = service.services.workflow
    with workflow.repository.transaction(ctx) as tx:
        project = workflow._project(tx, job['projectId'])
        snapshot = tx.production[project['id']]
        row = snapshot.get('job')
        if (not row or row['id'] != identity or row['version'] != job['version']
                or (snapshot.get('review') or {}).get('version', 0) != job['reviewVersion']
                or (snapshot.get('edit') or {}).get('version', 0) != job['editVersion']):
            conflict('分镜脚本已变化，请刷新后重新下载。')
        coverage = workflow._coverage(tx, project['id'])
        if coverage.get('productionId') != identity or not coverage['entities']:
            conflict('当前制作方案尚未通过核对，不能导出分镜脚本。')
        allowed = set(coverage['exportRevisionIds'])
        revisions = {r['entityId']: r for r in tx.state['revisions'].values()
                     if r['id'] in allowed and r['stage'] == 'storyboard'}
        selected = [revisions.get(shot_entity_id(job['scriptId'], shot['id'])) for shot in job['result']['shots']]
        if sum(r['bytes'] for r in selected if r) > 120 * 1024 * 1024:
            raise WorkflowError('EXPORT_TOO_LARGE', '分镜图总量超过 120 MiB，请分集整理后导出。', 422)
        asset_names = {a['id']: a['name'] for a in job['result']['assets']}
        character_names = {c['id']: c['name'] for c in job['characters']}
        state_names = {(a['id'], s['id']): s['name'] for a in job['result']['assets'] for s in a['states']}
        scene_names = {s['id']: s.get('heading') or s.get('name') or s['id'] for s in row['data']['context']['analysis']['scenes']}
        dialogues = {d['id']: d for d in job['dialogues']}
        def prose(value):
            return escape(MENTION.sub(lambda m: asset_names[m.group(1)], str(value))).replace('\n', '<br>')
        def field(label, value):
            return f'<div class="field"><b>{escape(label)}</b><p>{prose(value)}</p></div>'
        script = tx.state['scripts'][job['scriptId']]
        manifest = {'schemaVersion': 1, 'kind': 'illustrated-storyboard', 'projectName': project['name'],
            'sourceFilename': script['filename'], 'sourceRevision': script['sourceRevision'],
            'productionId': identity, 'reviewVersion': job['reviewVersion'], 'editVersion': job['editVersion'],
            'exportedAt': now(), 'aspectRatio': job['result']['aspectRatio'],
            'complete': coverage['complete'], 'totalShots': len(selected),
            'illustratedShots': sum(r is not None for r in selected), 'shots': []}
        pages, buffer = [], io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for position, (shot, revision) in enumerate(zip(job['result']['shots'], selected), 1):
                record = {**copy.deepcopy(shot), 'position': position, 'image': None, 'dialogues': []}
                illustration = '<div class="missing">分镜图待生成或待审核</div>'
                if revision:
                    raw = tx.get_blob(revision['blobId'])
                    if hashlib.sha256(raw).hexdigest() != revision['sha256']:
                        conflict('分镜图片校验失败，请刷新后重新下载。')
                    filename = f"images/shot-{position:03d}{revision['extension']}"
                    archive.writestr(filename, raw)
                    record['image'] = {'file': filename, 'revisionId': revision['id'], 'sha256': revision['sha256']}
                    illustration = f'<img src="{filename}" alt="镜头 {position:03d} 已审核分镜图">'
                speech = []
                for did in shot['dialogueIds']:
                    d = dialogues[did]
                    speaker = character_names.get(d.get('speakerId'), d.get('speakerLabel') or '未署名')
                    record['dialogues'].append({**copy.deepcopy(d), 'speakerName': speaker})
                    speech.append(field(speaker + ' · ' + {'dialogue': '对白', 'inner_monologue': '内心独白', 'narration': '旁白', 'voiceover': '画外音', 'offscreen': '画外对白', 'system_voice': '系统音', 'unknown': '待确认类型'}.get(d['kind'], d['kind']), d['text']))
                refs = '、'.join(asset_names[r['assetId']] + ' · ' + state_names[(r['assetId'], r['stateId'])] for r in shot['references'])
                pages.append(f'<article><h2>镜头 {position:03d} · {prose(shot["purpose"])}</h2>'
                    f'<p class="meta">{prose(scene_names.get(shot["sceneId"], shot["sceneId"]))} · {shot["durationSeconds"]} 秒 · {prose(shot["framing"])}</p>'
                    f'<div class="layout"><figure>{illustration}<figcaption>{prose(refs)}</figcaption></figure><section>'
                    + field('动作', shot['beat']) + field('摄影机', shot['camera']) + field('人物表演', shot['performance'])
                    + '<h3>原文台词</h3>' + (''.join(speech) or '<p>无台词</p>')
                    + field('声音', shot['sound']) + field('首帧状态', shot['startState'])
                    + field('结束状态', shot['endState']) + field('连续性', '\n'.join(shot['continuity']))
                    + '</section></div></article>')
                manifest['shots'].append(record)
            title = escape(project['name'] + ' · 图文分镜脚本')
            document = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>body{{font:15px/1.6 system-ui,sans-serif;color:#202020;background:#eee;margin:0;padding:32px}}header,article{{max-width:1180px;background:white;margin:0 auto 24px;padding:32px}}h1,h2,h3,p{{margin:0 0 12px}}.meta,figcaption{{color:#666}}.layout{{display:grid;grid-template-columns:1fr 1fr;gap:28px}}figure{{margin:0}}img{{width:100%;max-height:760px;object-fit:contain}}.missing{{padding:100px 20px;text-align:center;background:#f3f3f3}}.field p{{white-space:normal}}b{{font-size:13px;color:#555}}@media(max-width:760px){{body{{padding:12px}}header,article{{padding:20px}}.layout{{grid-template-columns:1fr}}}}@media print{{@page{{size:A4 landscape;margin:12mm}}body{{padding:0;background:white;font-size:11px}}header,article{{padding:0}}article{{break-before:page}}img{{max-height:160mm}}h2{{font-size:19px}}}}</style>
<header><h1>{title}</h1><p>{manifest['totalShots']} 个镜头 · {manifest['illustratedShots']} 张已审核分镜图 · {prose(manifest['aspectRatio'])}</p><p>{'本次制作内容已完成审核' if manifest['complete'] else '制作中：本文件包含未完成项，空图不代表生成成功'}</p><p>解压后打开本文件查看图文，可使用浏览器打印保存为 PDF。图片与脚本版本对应关系保存在 storyboard.json。</p></header>{''.join(pages)}</html>'''
            archive.writestr('分镜脚本.html', document)
            archive.writestr('storyboard.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        return buffer.getvalue(), manifest
