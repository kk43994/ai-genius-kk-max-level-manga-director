"""Durable bounded image dispatch. Selection remains a separate transition."""
import copy
import hashlib
import io
import json
import os
import threading
import time
from datetime import datetime, timezone
from urllib import request, parse
from production_actions import atomic_json, target_data, ActionError, make_preview_job, make_job
from local_preview import render_preview
from providers.lovart import Lovart, ProviderError
from providers.libtv import LibTV


def now():
    return datetime.now(timezone.utc).isoformat()


class AssetRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_asset_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def check_asset_url(url):
    parsed = parse.urlparse(url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.port not in (None, 443) or not parsed.hostname.endswith('.lovart.ai')):
        raise ProviderError('结果下载地址不在已接入的 Lovart 图片域名中，请到 Lovart 查看原任务。')


def download_image(url):
    from PIL import Image
    check_asset_url(url)
    with request.build_opener(AssetRedirect()).open(url, timeout=45) as response:
        raw = response.read(30 * 1024 * 1024 + 1)
    if len(raw) > 30 * 1024 * 1024:
        raise ProviderError('结果图片超过 30 MB，请到 Lovart 下载原图。')
    with Image.open(io.BytesIO(raw)) as img:
        if img.width * img.height > 40000000:
            raise ProviderError('结果图片尺寸超过当前接收范围。')
        img.load()
        output = io.BytesIO()
        img.convert('RGB').save(output, 'PNG')
        return output.getvalue(), [img.width, img.height]


class Execution:
    def __init__(self, root, lock, provider=None, downloader=download_image):
        self.root, self.lock, self.provider = root, lock, provider
        self.downloader = downloader
        self.signal = threading.Event()
        self.stopping = threading.Event()
        self.tick_lock = threading.Lock()
        self.active_jobs = {}
        self.verified = provider is not None
        self.last_error = None
        self.worker = None
        self.libtv = LibTV(root)
        self.recover()
        if provider is None and self.read().get('generationSettings', {}).get('provider') == 'libtv':
            try:
                self.connect({'provider': 'libtv'})
            except ActionError as exc:
                self.last_error = exc.message

    def read(self):
        return json.loads((self.root / 'manifest.json').read_text())

    def write(self, m):
        m['executionSchemaVersion'] = 1
        m['executionUpdatedAt'] = now()
        scene = next((j for j in reversed(m.get('generationQueue', [])) if j.get('stage') == 'scene-render'), None)
        if scene:
            for step in m.get('pipeline', []):
                if step['name'] == '材质与场景渲染':
                    step['state'] = scene.get('message', '正在检查执行条件')
            if scene['status'] == 'blocked':
                m['phase'] = '布局已选用 · 彩色场景缺少执行条件'
                for step in m.get('scenePipeline', []):
                    if step['step'] in ('模型细化与统一材质', '固定光照与相机渲染'):
                        step['status'] = 'blocked'
        preview=next((j for j in reversed(m.get('generationQueue',[])) if j.get('stage')=='scene-preview' and j['status'] not in ('cancelled','superseded')),None)
        if preview and not m.get('selectedMaterialPreview'):
            m['phase']='材质预览已出 · 等待挑选' if preview['status']=='succeeded' else '正在制作材质预览' if preview['status']=='running' else '材质预览待执行'
            for step in m.get('pipeline',[]):
                if step['name']=='材质与场景渲染':step['state']=preview.get('message',m['phase'])
        atomic_json(self.root / 'manifest.json', m)
        try:
            folder = self.root / 'draw-requests'; folder.mkdir(exist_ok=True)
            for job in m.get('generationQueue', []):
                atomic_json(folder / (job['id'] + '.json'), job)
        except OSError:
            pass  # Manifest remains the authoritative commit.

    def recover(self):
        with self.lock:
            m = self.read()
            changed = m.get('executionSchemaVersion') != 1
            if m.get('workflowVersion')==2 and m['whiteModelReview']['status']=='approved' and not any(j.get('stage')=='scene-preview' for j in m.get('generationQueue',[])):
                for job in m.get('generationQueue',[]):
                    if job.get('stage')=='scene-render' and job['status'] in ('queued','blocked') and not job.get('submissionAttempted'):
                        job.update(status='superseded',executionState='workflow_upgraded',message='流程已升级：先完成同模型材质预览，再制作正式场景。')
                make_preview_job(m,'white-model',now())
                changed=True
            for job in m.get('generationQueue', []):
                if job['status'] == 'running':
                    if job.get('provider') == 'libtv' and job.get('submissionAttempted'):
                        job.update(status='needs_attention', executionState='recover_original',
                                   message='本地服务已重启。请收取原任务结果，不会重复提交生成。')
                    elif job.get('threadId'):
                        job.update(status='queued', executionState='resume_polling', message='恢复查询原任务，不会重复生图。')
                    elif job.get('submissionAttempted'):
                        job.update(status='needs_attention', executionState='submission_unknown', generationStarted=None, message='提交结果不明，请在 Lovart 核对原任务，系统不会重复扣费重发。')
                    else:
                        job.update(status='queued', executionState='waiting_for_worker')
                    changed = True
            if changed:
                self.write(m)

    def start(self):
        self.worker = threading.Thread(target=self.loop, name='image-worker', daemon=True)
        self.worker.start()
        self.wake()

    def wake(self):
        self.signal.set()

    def state(self):
        settings = self.read().get('generationSettings', {})
        return {'connected': self.verified, 'provider': getattr(self.provider, 'name', 'libtv'), 'automatic': True,
                'sceneRendererConnected': False, 'localPreviewAvailable': True, 'videoEnabled': False,
                'credentialStorage': 'official_cli_local', 'error': self.last_error,
                'settings': settings, **self.libtv.public_info()}

    def connect(self, payload):
        if payload.get('provider') == 'libtv':
            try:
                self.libtv.check()
            except ProviderError as exc:
                self.verified, self.last_error = False, str(exc)
                raise ActionError(str(exc), 502) from None
            with self.lock:
                m = self.read()
                settings = m.setdefault('generationSettings', {})
                settings.update(provider='libtv', accountId=self.libtv.account.get('accountId'))
                if not any(x['modelKey'] == settings.get('imageModelKey') for x in self.libtv.models):
                    settings['imageModelKey'] = self.libtv.default_model
                settings.setdefault('downloadWatermark', False)
                self.write(m)
            self.provider, self.verified, self.last_error = self.libtv, True, None
            # Connecting is read-only at the provider. Old unassigned jobs remain blocked.
            return {'ok': True, **self.state()}
        ak, sk = payload.get('accessKey', ''), payload.get('secretKey', '')
        if not all(isinstance(x, str) and 5 <= len(x.strip()) <= 4096 and not any(c in x for c in '\r\n') for x in (ak, sk)):
            raise ActionError('请填写 Lovart 的 Access Key 和 Secret Key。')
        provider = Lovart(ak.strip(), sk.strip())
        try:
            provider.check()  # Read account mode; never change shared billing mode.
        except ProviderError as exc:
            raise ActionError(str(exc), 502) from None
        self.provider, self.verified, self.last_error = provider, True, None
        self.wake()
        return {'ok': True, **self.state()}

    def login(self):
        try:
            return {'ok': True, **self.libtv.start_login()}
        except ProviderError as exc:
            raise ActionError(str(exc), 400) from None

    def set_model(self, payload):
        if not self.verified or self.provider is not self.libtv:
            raise ActionError('请先验证 LibTV 连接。', 409)
        try:
            entry, _ = self.libtv.model(payload.get('modelKey'))
        except ProviderError as exc:
            raise ActionError(str(exc)) from None
        if not isinstance(payload.get('downloadWatermark', False), bool):
            raise ActionError('下载设置格式不正确。')
        with self.lock:
            m = self.read()
            if payload.get('phase')=='refine':
                m['generationSettings'].setdefault('pipelineModels',{})['refine']={'modelKey':entry['modelKey'],'alias':payload.get('alias',entry['modelName']),'confirmedAt':now(),'source':'user_confirmed_platform_alias'}
                self.write(m)
                return {'ok':True,'phase':'refine','modelKey':entry['modelKey']}
            m['generationSettings'].update(imageModelKey=entry['modelKey'],
                                            downloadWatermark=payload.get('downloadWatermark', False))
            self.write(m)
        return {'ok': True, **self.state()}

    def test_image(self):
        if not self.verified or self.provider is not self.libtv:
            raise ActionError('请先验证 LibTV 连接。', 409)
        with self.lock:
            m = self.read()
            source = next(t for t in m['tasks'] if t['id'] == 'lin-jingwen-reference-v2')
            if source.get('humanReview') != 'approved':
                raise ActionError('请先选定人物风格图。', 409)
            existing = next((j for j in m.get('generationQueue', []) if j.get('integrationTest')), None)
            if existing:
                return {'ok': True, 'job': existing, 'alreadyCreated': True}
            job, _ = make_job(m, source['id'], '', 'next-stage', now())
            job.update(integrationTest=True, title='林静雯 · LibTV 人物资产测试',
                       basePrompt=next(t['prompt'] for t in m['tasks'] if t['id'] == 'lin-jingwen-fourview-v2'))
            self.write(m)
        self.wake()
        return {'ok': True, 'job': job}

    def retry(self, job_id):
        with self.lock:
            m = self.read()
            job = next((j for j in m.get('generationQueue', []) if j['id'] == job_id), None)
            if not job:
                raise ActionError('找不到这个任务。', 404)
            if job['status'] in ('succeeded', 'running', 'queued'):
                return {'ok': True}
            if job.get('provider') == 'libtv' and job.get('submissionAttempted'):
                if not job.get('nodeKey'):
                    raise ActionError('缺少原生成节点编号，不能自动重发。', 409)
                job.update(status='queued', executionState='recover_original',
                           downloadWatermark=m.get('generationSettings', {}).get('downloadWatermark', False),
                           message='只查询和下载原任务，不重新生成。')
                self.write(m)
                self.wake()
                return {'ok': True}
            if job.get('submissionAttempted') and not job.get('threadId'):
                raise ActionError('原任务的提交结果不明，请先在 Lovart 核对，不能自动重复提交。', 409)
            if job.get('executionState') == 'upstream_confirmation':
                raise ActionError('上游需要额外确认，本轮仅做图片，请先在 Lovart 查看原因。', 409)
            job.update(status='queued', executionState='waiting_for_worker', message='正在重新检查执行条件。')
            self.write(m)
        self.wake()
        return {'ok': True}

    def update(self, job_id, **fields):
        with self.lock:
            m = self.read()
            job = next(j for j in m['generationQueue'] if j['id'] == job_id)
            job.update(fields, updatedAt=now())
            self.write(m)

    def readiness(self, job):
        if job.get('stage')=='scene-preview':
            try:
                import numpy
                from PIL import Image
            except ImportError:return 'local_dependencies_missing','本地预览需要图像运行环境，请使用已配置的 Python 启动服务。'
            return None
        if job.get('kind')=='final-render':return 'scene_renderer_missing','正式场景的模型细化与最终渲染尚未接入；材质预览已保留，可继续查看和换配色。'
        if job['sourceTarget'] == 'white-model' or job.get('stage') in ('scene-render','scene-layout'):
            return 'scene_renderer_missing', '缺少三维场景制作与渲染执行器。白模已选用；接入后才能统一材质并渲染四个角度。'
        if not self.verified:
            return 'provider_missing', '尚未连接图片服务，请打开“任务与连接”验证 LibTV。'
        if self.provider is self.libtv:
            if job.get('provider') != 'libtv':
                return 'provider_assignment_required', '历史任务未指定 LibTV；请从原图重新发起，旧任务不会自动扣分。'
            try:
                self.libtv.validate(job)
            except ProviderError as exc:
                return 'unsupported_image_task', str(exc)
        return None

    def tick(self, background=False):
        if not self.tick_lock.acquire(blocking=False):
            return
        try:
            selected = []
            with self.lock:
                m = self.read()
                changed = False
                limit = max(1, min(24, int(m.get('generationSettings', {}).get('maxConcurrentImages', 6))))
                capacity = max(0, limit - len(self.active_jobs)) if background else 1
                for job in m.get('generationQueue', []):
                    if len(selected) >= capacity:
                        break
                    if job['status'] not in ('queued', 'blocked'):
                        continue
                    try:
                        _, revision = target_data(m, job['sourceTarget'])
                        stale = revision != job['sourceRevision']
                    except ActionError:
                        stale = True
                    block = ('stale_input', '来源版本已变化，请基于当前版本重新发起。') if stale and not job.get('threadId') else self.readiness(job)
                    if block:
                        fields = {'status': 'blocked', 'executionState': block[0], 'message': block[1]}
                        if any(job.get(k) != v for k, v in fields.items()):
                            job.update(fields, updatedAt=now()); changed = True
                        continue
                    job.update(status='running', executionState='preparing', message='正在准备已选参考图。', updatedAt=now())
                    selected.append(copy.deepcopy(job)); changed = True
                if changed:
                    self.write(m)
            for job in selected:
                if background:
                    worker = threading.Thread(target=self.run_claimed, args=(job,), name=job['id'], daemon=True)
                    self.active_jobs[job['id']] = worker
                    worker.start()
                else:
                    self.run(job)
        finally:
            self.tick_lock.release()

    def run_claimed(self, job):
        try:
            self.run(job)
        except Exception:
            self.update(job['id'], status='needs_attention', executionState='execution_error',
                        message='任务未完成，请检查原任务；没有自动重复生成。')
        finally:
            with self.tick_lock:
                self.active_jobs.pop(job['id'], None)
            self.wake()

    def run(self, job):
        if job.get('stage')=='scene-preview':
            return self.run_preview(job)
        if job.get('provider') == 'libtv':
            return self.run_libtv(job)
        provider = self.provider
        jid = job['id']
        thread_id = job.get('threadId')
        attempted = bool(job.get('submissionAttempted'))
        try:
            if not thread_id:
                project_id = job.get('projectId') or provider.project(job)
                self.update(jid, projectId=project_id)
                attachments = []
                for name in job['inputs']:
                    path = (self.root / name).resolve()
                    if not path.is_relative_to(self.root.resolve()) or path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
                        raise ProviderError('这个任务的输入需要其他制作工具处理。')
                    attachments.append(provider.upload(path))
                # Persist before a potentially billable POST. An uncertain outcome is never retried automatically.
                with self.lock:
                    m = self.read()
                    _, revision = target_data(m, job['sourceTarget'])
                    live = next(j for j in m['generationQueue'] if j['id'] == jid)
                    if revision != job['sourceRevision']:
                        live.update(status='blocked', executionState='stale_input', message='准备期间来源版本已变化，未提交生图。')
                        self.write(m)
                        return
                    live.update(executionState='submitting', submissionAttempted=True, message='正在向 Lovart 提交生图请求。', updatedAt=now())
                    self.write(m)
                attempted = True
                thread_id = provider.submit(job, project_id, attachments)
                self.update(jid, threadId=thread_id, generationStarted=True, submittedAt=now())
            self.update(jid, executionState='generating', message='Lovart 正在生成图片，完成后会自动回到画布。')
            deadline = time.monotonic() + 1800
            done_seen = False
            while not self.stopping.is_set() and time.monotonic() < deadline:
                state = provider.status(thread_id).get('status')
                if state in ('pending_confirmation', 'abort'):
                    self.update(jid, status='needs_attention', executionState='upstream_confirmation' if state == 'pending_confirmation' else 'upstream_aborted', message='Lovart 需要额外确认，未自动同意。' if state == 'pending_confirmation' else 'Lovart 已停止任务，请查看原任务后处理。')
                    return
                if state == 'done' and done_seen:
                    result = provider.result(thread_id)
                    if result.get('pending_confirmation'):
                        self.update(jid, status='needs_attention', executionState='upstream_confirmation', message='Lovart 需要额外确认，未自动同意。')
                        return
                    self.finish(job, result)
                    return
                done_seen = state == 'done'
                self.stopping.wait(5)
            if not self.stopping.is_set():
                self.update(jid, status='needs_attention', executionState='poll_timeout', message='等待已超过 30 分钟。可继续查询原任务，不会重复生成。')
        except Exception as exc:
            message = str(exc) if isinstance(exc, ProviderError) else '执行或收图失败，请检查连接后继续原任务。'
            unknown = attempted and not thread_id
            self.update(jid, status='needs_attention' if unknown else 'failed', executionState='submission_unknown' if unknown else 'execution_error', generationStarted=None if unknown else bool(thread_id), message='提交结果不明，请在 Lovart 核对原任务；不会自动重发。' if unknown else message)

    def run_libtv(self, job):
        jid = job['id']
        attempted = bool(job.get('submissionAttempted'))
        try:
            if attempted:
                self.libtv.recover_result(job['projectId'], job['nodeKey'])
            else:
                self.update(jid, message='正在上传参考图、建立 LibTV 图片节点。')
                project, node = self.libtv.prepare(job, lambda **kw: self.update(jid, **kw))
                with self.lock:
                    m = self.read()
                    _, revision = target_data(m, job['sourceTarget'])
                    live = next(j for j in m['generationQueue'] if j['id'] == jid)
                    if revision != job['sourceRevision']:
                        live.update(status='blocked', executionState='stale_input', message='来源版本已变化，未提交生成。')
                        self.write(m)
                        return
                    live.update(submissionAttempted=True, executionState='generating', submittedAt=now(),
                                message='LibTV 正在生成。可以离开页面；完成后会自动收图。')
                    self.write(m)
                attempted = True
                result = self.libtv.run(project, node)
                # A terminal CLI return is required before download; raw replies stay out of public files.
                self.update(jid, generationStarted=True, upstreamCompletedAt=now(),
                            executionState='downloading', message='LibTV 已返回，正在下载和核验图片。')
            images = self.libtv.download_images(job) if hasattr(self.libtv, 'download_images') else [self.libtv.download(job)]
            with self.lock:
                current = copy.deepcopy(next(j for j in self.read()['generationQueue'] if j['id'] == jid))
            self.store_images(current, images, {
                'provider': 'libtv', 'modelKey': current['modelKey'], 'modelName': current.get('modelName'),
                'modelVendor': current.get('modelVendor'), 'projectUrl': current.get('projectUrl'),
                'nodeKey': current.get('nodeKey'), 'modelVerification': 'LibTV CLI 明确指定模型；已取回真实生成结果',
                'effectivePrompt': current.get('effectivePrompt')})
        except Exception as exc:
            message = str(exc) if isinstance(exc, ProviderError) else '收图尚未完成，请查看原画布；不会自动重复生成。'
            self.update(jid, status='needs_attention' if attempted else 'failed',
                        executionState='recover_original' if attempted else 'execution_error',
                        generationStarted=None if attempted else False, message=message)

    def run_preview(self,job):
        jid=job['id']
        try:
            self.update(jid,generationStarted=True,executionState='rendering_preview',message='正在给同一白模上色，准备四个机位。',progress={'completed':0,'total':4})
            result=render_preview(self.root,job,lambda done:self.update(jid,progress={'completed':done,'total':4},message=f'本地材质预览 · 已完成 {done}/4 个角度'),self.stopping)
            with self.lock:
                m=self.read();live=next(j for j in m['generationQueue'] if j['id']==jid)
                _,revision=target_data(m,job['sourceTarget']);_,geometry=target_data(m,'white-model')
                stale=revision!=job['sourceRevision'] or geometry!=job['geometryRevision']
                tid='result-'+jid
                if not any(t['id']==tid for t in m['tasks']):
                    m['tasks'].append({'id':tid,'title':job['title'],'file':result['views'][0]['file'],'phase':'material-preview',
                        'entity':'scene','ratio':'16:9','actualPixels':[1536,864],'humanReview':'pending','generated':True,
                        'jobId':jid,'sourceTarget':job['sourceTarget'],'sourceRevision':job['sourceRevision'],
                        'geometryRevision':job['geometryRevision'],'staleInput':stale,'prompt':job['basePrompt'],**result})
                live.update(status='succeeded',executionState='awaiting_selection',completedAt=now(),resultTaskId=tid,
                            progress={'completed':4,'total':4},message='四个角度已渲染，等待选择材质预览。')
                self.write(m)
        except Exception as exc:
            self.update(jid,status='failed',executionState='local_render_failed',message=str(exc) if isinstance(exc,ValueError) else '本地预览未完成，请检查白模和运行环境后重试。')

    def finish(self, job, result):
        artifacts = [a for item in result.get('items', []) if item.get('type') == 'generator'
                     for a in item.get('artifacts', [])]
        images = [a for a in artifacts if a.get('type') == 'image' and isinstance(a.get('content'), str)]
        if result.get('failures') or len(images) != 1 or any(a.get('type') != 'image' for a in artifacts):
            raise ProviderError('Lovart 返回结果未符合这次单张图片要求，请查看原任务；未自动采用。')
        data, pixels = self.downloader(images[0]['content'])
        self.store_image(job, data, pixels, {'modelVerification': 'Lovart Agent 模型偏好，实际模型尚未独立核实'})

    def store_image(self, job, data, pixels, metadata):
        return self.store_images(job, [(data, pixels)], metadata)

    def store_images(self, job, images, metadata):
        count = job.get('generationCount', 1)
        if len(images) != count:
            raise ProviderError('候选数量不符合任务要求，未登记为完成。')
        expected = job['outputs'][0]['ratio']
        a, b = map(int, expected.split(':'))
        for data, pixels in images:
            if pixels[1] <= 0 or abs(pixels[0] / pixels[1] - a / b) > .02:
                raise ProviderError('结果画幅不符合 ' + expected + '，请查看原任务；未自动入库。')
        folder = self.root / 'generated' / job['id']
        folder.mkdir(parents=True, exist_ok=True)
        paths = [folder / ('image.png' if count == 1 else f'image-{i+1:02d}.png') for i in range(count)]
        for path, (data, _) in zip(paths, images):
            if path.exists() and path.read_bytes() != data:
                raise ProviderError('重取结果与已保存候选不一致，保留原文件，请核对原任务。')
        for path, (data, _) in zip(paths, images):
            if not path.exists():
                temp = path.with_suffix('.tmp'); temp.write_bytes(data); os.replace(temp, path)
        with self.lock:
            m = self.read()
            live = next(j for j in m['generationQueue'] if j['id'] == job['id'])
            source, revision = target_data(m, job['sourceTarget'])
            stale = revision != job['sourceRevision']
            task_ids = []
            for i, (path, (data, pixels)) in enumerate(zip(paths, images)):
                task_id = 'result-' + job['id'] + (f'-{i+1:02d}' if count > 1 else '')
                task_ids.append(task_id)
                if any(t['id'] == task_id for t in m['tasks']):
                    continue
                m['tasks'].append({'id': task_id, 'title': job['title'] + (f' · 候选 {i+1}' if count > 1 else ' · 新版本'),
                    'file': str(path.relative_to(self.root)), 'phase': job.get('phase', source.get('phase', 'asset') if job['kind'] == 'reroll' else 'asset'),
                    'entity': source.get('entity', 'scene'), 'ratio': expected, 'actualPixels': pixels,
                    'humanReview': 'pending', 'generated': True, 'jobId': job['id'], 'sourceTarget': job['sourceTarget'],
                    'outputRequirements': job['outputRequirements'], 'prompt': job['basePrompt'], 'additionalPrompt': job['additionalPrompt'], 'sourceRevision': job['sourceRevision'],
                    'contentSha256': hashlib.sha256(data).hexdigest(), 'staleInput': stale, 'candidateIndex': i + 1,
                    **metadata, **{key: copy.deepcopy(job[key]) for key in ('catalog', 'batchId', 'characterId', 'pipelineRecipe', 'generationCount', 'modelSettings') if key in job}})
                if count > 1 and m['tasks'][-1].get('catalog'):
                    m['tasks'][-1]['catalog']['candidate'] = i + 1
            live.update(status='succeeded', executionState='awaiting_selection', completedAt=now(),
                        resultTaskId=task_ids[0], resultTaskIds=task_ids, generationStarted=True,
                        message=f'{count} 张候选已收回，请选择用这版或重抽。' if not stale else '生成期间来源发生变化，新图已保留，需重新核对。')
            self.write(m)

    def loop(self):
        while not self.stopping.is_set():
            try:
                self.tick(background=True)
            except Exception:
                self.last_error = '执行服务出现异常，请重新检查任务状态。'
            self.signal.wait(4)
            self.signal.clear()
