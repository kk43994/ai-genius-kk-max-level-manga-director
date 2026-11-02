"""Customer asset workflow. No provider/CLI/network calls or background workers.

All state is tenant-scoped by the injected repository; generation belongs to
TaskService. Read operations never recover, submit, or write business state.
"""
import copy
import hashlib
import io
import json
import re
import uuid
import warnings
import zipfile
from datetime import datetime, timezone

from .errors import WorkflowError, conflict, invalid, missing, public_input, tenant, value
from .intake import ANALYSIS, decode_script

STAGES = {'mj_style': 'style', 'image25_style': 'style', 'image2_asset': 'asset', 'image25_asset': 'asset', 'nano_refine': 'refine', 'storyboard_image': 'storyboard', 'image25_storyboard': 'storyboard'}
CATEGORIES = {'character': '角色', 'scene': '场景', 'prop': '道具', 'effect': '异象', 'shot': '分镜'}
OWNER_FIELDS = ('provider', 'providerAccountId', 'providerIssuer', 'providerSubject', 'spaceId', 'spaceKind',
                'boundAt', 'accountLabelAtCreation', 'spaceNameAtCreation')
REQUIRED_OWNER = ('tenantId', 'providerAccountId', 'spaceId')
# Older releases persisted dependency invalidity in status. It is a cache of
# the dependency check, not a revocation of the stored human review.
DEPENDENCY_STALE_REASON = '原文、清单、风格或参考版本已改变，需要重新制作和审核。'
MIMES = {'PNG': ('image/png', '.png'), 'JPEG': ('image/jpeg', '.jpg'), 'WEBP': ('image/webp', '.webp')}
REFINE_PROMPT = ('对原始 Image2 资产进行保真清噪与纹理清理。保持人物身份、服装纹样、发冠、毛领、'
                 '道具结构、构图、光向和视图数量一致。精修宁可变化很小，也不要重绘或丢失结构。')


def now():
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix):
    return prefix + '_' + uuid.uuid4().hex


def text_field(data, key, limit, default='', required=False):
    result = data.get(key, default)
    if not isinstance(result, str) or len(result) > limit or '\x00' in result:
        invalid('字段格式或长度不正确：' + key)
    result = result.strip()
    if required and not result:
        invalid('请填写：' + key)
    return result


def expected(data, version):
    candidate = data.get('expectedVersion')
    if type(candidate) is not int or candidate != version:
        conflict('记录已更新，请重新读取后再保存。未覆盖你的修改。')


def owner_key(owner):
    return tuple(owner.get(k) for k in REQUIRED_OWNER)


def inspect_image(raw):
    if not isinstance(raw, bytes) or not raw or len(raw) > 40 * 1024 * 1024:
        invalid('返回图片为空或超过 40 MiB。')
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        raise WorkflowError('IMAGE_VALIDATION_UNAVAILABLE', '图片校验服务未就绪，尚未入库。', 503) from None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as im:
                if im.format not in MIMES or getattr(im, 'n_frames', 1) != 1:
                    invalid('仅接收单帧 PNG、JPEG 或 WebP 图片。')
                width, height, kind = im.width, im.height, im.format
                if width * height > 40_000_000:
                    invalid('图片像素过大。')
                im.verify()
            with Image.open(io.BytesIO(raw)) as im:
                im.load()
    except (OSError, SyntaxError, ValueError, UnidentifiedImageError,
            Image.DecompressionBombWarning, Image.DecompressionBombError):
        invalid('返回文件不是可完整解码的图片。')
    return dict(mime=MIMES[kind][0], extension=MIMES[kind][1], width=width,
                height=height, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))


class WorkflowService:
    """repository.transaction(ctx) yields a tenant-only state and blob interface.

    See repository.py for the central-store adapter; no HTTP endpoint may call
    record_output with client-owned task dictionaries or arbitrary file paths.
    """

    def __init__(self, repository, tasks=None, *, api_base='/api/v1'):
        if (not isinstance(api_base, str) or not api_base.startswith('/') or api_base.startswith('//')
                or re.search(r'[?#\\\s]', api_base) or any(p in ('.', '..') for p in api_base.split('/'))
                or re.search(r'%2e|%2f|%5c', api_base, re.I)):
            raise ValueError('api_base must be an explicit same-origin path')
        self.repository, self.tasks, self.api_base = repository, tasks, api_base.rstrip('/')

    def capabilities(self):
        analysis = self.analysis.capabilities() if getattr(self, 'analysis', None) else copy.deepcopy(ANALYSIS)
        return {'scriptAnalysis': analysis['configured'], 'persistentProjects': True,
                'localScriptExtraction': False, 'quickStart': True,
                'videoGeneration': False, 'analysis': analysis}

    def _project(self, tx, project_id):
        if not isinstance(project_id, str):
            missing()
        project = tx.state['projects'].get(project_id)
        if not project:
            missing()
        return project

    def _asset(self, tx, asset_id):
        if not isinstance(asset_id, str):
            missing()
        asset = tx.state['assets'].get(asset_id)
        if not asset:
            missing()
        self._project(tx, asset['projectId'])
        return asset

    def _revision(self, tx, revision_id):
        if not isinstance(revision_id, str):
            missing()
        revision = tx.state['revisions'].get(revision_id)
        if not revision:
            missing()
        self._asset(tx, revision['assetId'])
        return revision

    def _entity(self, project, entity_id):
        entity = next((e for e in project['plan']['entities'] if e['id'] == entity_id), None)
        if not entity:
            missing()
        return entity

    def _valid(self, tx, revision, require_approved=False, seen=None):
        dependency_stale = (revision['status'] == 'stale'
                            and revision.get('staleReason') == DEPENDENCY_STALE_REASON)
        if (revision['status'] != 'ready' and not dependency_stale
                or require_approved and revision['review'] != 'approved'):
            return False
        seen = set() if seen is None else set(seen)
        if revision['id'] in seen:
            return False
        seen.add(revision['id'])
        project = self._project(tx, revision['projectId'])
        if revision.get('referenceOnly'):
            return revision['stage']=='reference' and not revision['sourceRevisionIds']
        entity = next((e for e in project['plan']['entities'] if e['id'] == revision['entityId']), None)
        applicable_version = (revision.get('applicability') or {}).get('entityVersion', revision['entityVersion']) if revision['stage'] == 'storyboard' else revision['entityVersion']
        if (not entity or entity['version'] != applicable_version
                or project['plan']['styleVersion'] != revision['styleVersion']):
            return False
        if revision.get('artDirectionVersion'):
            direction = project.get('artDirection') or {}
            style_source = tx.state['revisions'].get(direction.get('revisionId'))
            if (revision['artDirectionVersion'] != direction.get('version', 0) or not style_source
                    or not self._valid(tx, style_source, True, seen)):
                return False
            for item in direction.get('samples', {}).values():
                r = tx.state['revisions'].get(item['revisionId'])
                if not r or r['sha256'] != item['sha256'] or not self._valid(tx, r, True, seen):
                    return False
        for index, source_id in enumerate(revision['sourceRevisionIds']):
            source = tx.state['revisions'].get(source_id)
            if not source or not self._valid(tx, source, True, seen):
                return False
            if revision['stage'] == 'asset' and index == 0:
                from .production_lineage import image2_source_allowed
                if not image2_source_allowed(tx, project, revision['entityId'], source):
                    return False
        return True

    def _reconfirmation(self, tx, revision):
        """An old shot can be re-adopted only when its references remain valid.

        This offers a human decision; it never rewrites the generation snapshot.
        """
        if revision['stage'] != 'storyboard' or self._valid(tx, revision):
            return None
        project = self._project(tx, revision['projectId'])
        entity = next((e for e in project['plan']['entities'] if e['id'] == revision['entityId']), None)
        if not entity or entity['category'] != 'shot':
            return None
        trial = {**revision, 'applicability': {'entityVersion': entity['version']}}
        if not self._valid(tx, trial):
            return None
        return {'entityVersion': entity['version'],
                'message': f"这张图按第 {revision['entityVersion']} 版镜头方案生成，当前方案为第 {entity['version']} 版。人物、场景和风格参考仍有效，确认画面仍适用后可以沿用。"}

    def _public_revision(self, tx, revision):
        result = {k: copy.deepcopy(v) for k, v in revision.items()
                  if k not in ('blobId', 'tenantId', 'extension', 'outputKey')}
        result['ownership'] = {k: revision['ownership'].get(k) for k in OWNER_FIELDS}
        result['status'] = 'ready' if self._valid(tx, revision) else 'stale'
        if result['status'] == 'ready':
            result.pop('staleReason', None)
        elif reconfirmation := self._reconfirmation(tx, revision):
            result['reconfirmation'] = reconfirmation
        result['contentUrl'] = f"{self.api_base}/assets/{revision['assetId']}/content?revisionId={revision['id']}"
        result['thumbnailUrl'] = f"{self.api_base}/assets/{revision['assetId']}/thumbnail?revisionId={revision['id']}"
        return result

    def _public_project(self, project):
        return {k: copy.deepcopy(v) for k, v in project.items() if k not in ('tenantId', 'plan')}

    def create_project(self, ctx, payload):
        public_input(payload, {'name', 'description'})
        project = dict(id=new_id('prj'), tenantId=tenant(ctx), name=text_field(payload, 'name', 120, required=True),
                       description=text_field(payload, 'description', 4000), version=1, createdAt=now(), updatedAt=now(),
                       scriptIds=[], status='active', plan={'version': 0, 'entities': [], 'stylePrompt': '', 'styleVersion': 1})
        with self.repository.transaction(ctx, write=True) as tx:
            tx.state['projects'][project['id']] = project
        return self._public_project(project)

    def list_projects(self, ctx):
        with self.repository.transaction(ctx) as tx:
            return {'items': [self._public_project(p) for p in sorted(tx.state['projects'].values(),
                    key=lambda p: p['createdAt'], reverse=True)], 'nextCursor': None}

    def get_project(self, ctx, project_id):
        with self.repository.transaction(ctx) as tx:
            from .art_direction import describe
            project = self._project(tx, project_id)
            from .art_studies import describe as studies
            return {**self._public_project(project), 'artDirection': describe(self, tx, project), 'artStudies':studies(project), 'promptRecipes':copy.deepcopy(project.get('promptRecipes',[])), 'promptRecipeVersion':project.get('promptRecipeVersion',0)}

    def confirm_art_direction(self, ctx, project_id, payload):
        from .art_direction import confirm
        return confirm(self, ctx, project_id, payload)

    def update_project(self, ctx, project_id, payload):
        public_input(payload, {'name', 'description', 'expectedVersion'})
        with self.repository.transaction(ctx, write=True) as tx:
            project = self._project(tx, project_id)
            expected(payload, project['version'])
            for field, limit in (('name', 120), ('description', 4000)):
                if field in payload:
                    project[field] = text_field(payload, field, limit, required=field == 'name')
            project.update(version=project['version'] + 1, updatedAt=now())
            return self._public_project(project)

    def import_script(self, ctx, project_id, payload):
        # Check existence before parsing an expensive, user-supplied archive.
        self.get_project(ctx, project_id)
        record, raw = decode_script(payload)
        with self.repository.transaction(ctx, write=True) as tx:
            project = self._project(tx, project_id)
            prior = next((tx.state['scripts'][sid] for sid in project['scriptIds']
                          if tx.state['scripts'][sid]['sourceRevision'] == record['sourceRevision']), None)
            if prior:
                return {'script': self._public_script(prior), 'duplicate': True}
            record.update(id=new_id('scr'), projectId=project_id, version=1, importedAt=now(),
                          analysisStatus='not_started', analysis=copy.deepcopy(ANALYSIS), blobId=tx.put_blob(raw))
            tx.state['scripts'][record['id']] = record
            project['scriptIds'].append(record['id'])
            project.update(version=project['version'] + 1, updatedAt=now())
            return {'script': self._public_script(record), 'duplicate': False}

    def _public_script(self, record):
        return {k: copy.deepcopy(v) for k, v in record.items() if k != 'blobId'}

    def get_script(self, ctx, project_id, script_id):
        with self.repository.transaction(ctx) as tx:
            project = self._project(tx, project_id)
            if script_id not in project['scriptIds']:
                missing()
            return self._public_script(tx.state['scripts'][script_id])

    def get_plan(self, ctx, project_id):
        with self.repository.transaction(ctx) as tx:
            return copy.deepcopy(self._project(tx, project_id)['plan'])

    def save_plan(self, ctx, project_id, payload, *, needs_review=False):
        public_input(payload, {'expectedVersion', 'entities', 'stylePrompt'})
        entities = payload.get('entities')
        if not isinstance(entities, list) or len(entities) > 300:
            invalid('资产清单最多包含 300 项。')
        style = text_field(payload, 'stylePrompt', 10000)
        with self.repository.transaction(ctx, write=True) as tx:
            project = self._project(tx, project_id)
            previous = project['plan']
            expected(payload, previous['version'])
            seen, clean = set(), []
            previous_entities = {e['id']: e for e in previous['entities']}
            for raw in entities:
                public_input(raw, {'id', 'category', 'name', 'description', 'origin', 'quote', 'scriptId', 'version', 'variant'})
                identity = raw.get('id') or new_id('ent')
                if not isinstance(identity, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', identity) or identity in seen:
                    invalid('资产编号无效或重复。')
                seen.add(identity)
                if not isinstance(raw.get('category'), str) or raw['category'] not in CATEGORIES or raw.get('origin', 'manual') not in ('manual', 'script'):
                    invalid('资产类别或来源不正确。')
                entity = dict(id=identity, category=raw['category'], name=text_field(raw, 'name', 120, required=True),
                              description=text_field(raw, 'description', 4000), variant=text_field(raw, 'variant', 100),
                              origin=raw.get('origin', 'manual'), quote=text_field(raw, 'quote', 4000),
                              scriptId=raw.get('scriptId'), version=1)
                if entity['origin'] == 'script':
                    script = tx.state['scripts'].get(entity['scriptId']) if isinstance(entity['scriptId'], str) else None
                    if not script or script['projectId'] != project_id:
                        invalid('原文条目必须关联本项目已导入的剧本。')
                    if not entity['quote'] or entity['quote'] not in script['text']:
                        invalid('原文依据无法在剧本中找到，请标为手工补充或核对引用。')
                    entity['sourceRevision'] = script['sourceRevision']
                else:
                    entity.update(scriptId=None, quote='')
                old = previous_entities.get(identity)
                if old:
                    fields = ('category', 'name', 'description', 'variant', 'origin', 'quote', 'scriptId', 'sourceRevision')
                    entity['version'] = old['version'] + int(any(old.get(k) != entity.get(k) for k in fields))
                # Existing archived identity may not be silently resurrected as version 1.
                asset = next((a for a in tx.state['assets'].values()
                              if a['projectId'] == project_id and a['entityId'] == identity), None)
                if asset and not old:
                    entity['version'] = asset['entityVersion'] + 1
                if not asset:
                    asset = dict(id=new_id('ast'), projectId=project_id, entityId=identity,
                                 version=1, createdAt=now(), revisionIds=[])
                    tx.state['assets'][asset['id']] = asset
                if asset.get('entityVersion') != entity['version']:
                    asset['version'] += int('entityVersion' in asset)
                asset.update(name=entity['name'], category=entity['category'], active=True, entityVersion=entity['version'])
                clean.append(entity)
            for asset in tx.state['assets'].values():
                if asset['projectId'] == project_id and not asset.get('referenceOnly') and asset['entityId'] not in seen and asset['active']:
                    asset.update(active=False, version=asset['version'] + 1)
            project['plan'] = dict(version=previous['version'] + 1, entities=clean, stylePrompt=style,
                                   styleVersion=previous['styleVersion'] + int(style != previous['stylePrompt']), updatedAt=now())
            if needs_review:
                project['plan']['needsReview'] = True
            project.update(version=project['version'] + 1, updatedAt=now())
            self._invalidate(tx, project_id)
            return copy.deepcopy(project['plan'])

    def _invalidate(self, tx, project_id):
        for revision in tx.state['revisions'].values():
            if revision['projectId'] == project_id and revision['status'] == 'ready' and not self._valid(tx, revision):
                revision['status'] = 'stale'
                revision['staleReason'] = DEPENDENCY_STALE_REASON

    def _source(self, tx, project_id, entity_id, revision_id, owner, cross_entity=False):
        source = self._revision(tx, revision_id)
        if source['projectId'] != project_id or (not cross_entity and source['entityId'] != entity_id):
            invalid('参考图须来自本项目的同一资产档案。')
        if owner_key(source['ownership']) != owner_key(owner):
            raise WorkflowError('OWNERSHIP_MISMATCH', '参考素材属于其他账号或空间，不能隐式混用。', 409)
        if not self._valid(tx, source, True):
            conflict('参考素材尚未审核通过或已失效，请先人工确认当前版本。')
        return source

    def build_spec(self, ctx, payload, ownership):
        """TaskService calls this with server-resolved immutable ownership.

        It must call this again immediately before submission to close races
        against plan edits/reviews; returned workflowSnapshot joins its digest.
        """
        public_input(payload, {'projectId', 'entityId', 'recipe', 'prompt', 'sourceRevisionIds',
                               'settings', 'repairOfRevisionId', 'modelId'})
        if ownership.get('tenantId') != tenant(ctx) or any(not ownership.get(k) for k in REQUIRED_OWNER):
            raise WorkflowError('OWNERSHIP_MISMATCH', '任务归属不完整。', 409)
        recipe = payload.get('recipe')
        if recipe == 'script_analysis':
            raise WorkflowError('ANALYSIS_UNAVAILABLE', ANALYSIS['message'], 503)
        if not isinstance(recipe, str) or recipe not in STAGES:
            raise WorkflowError('GENERATION_DISABLED', '仅开放资产图片流程；最终视频生成保持暂停。', 403)
        settings = payload.get('settings', {})
        from backend.generation.service import RESERVED
        if not isinstance(settings, dict) or any(k in RESERVED for k in settings):
            invalid('图片参数包含未支持的字段。')
        try:
            settings_text = json.dumps(settings, ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError):
            invalid('图片参数格式不正确。')
        if len(settings_text) > 20000:
            invalid('图片参数格式不正确。')
        if 'count' in settings and (type(settings['count']) is not int or not 1 <= settings['count'] <= 4):
            invalid('候选数量须为 1 至 4。')
        prompt = text_field(payload, 'prompt', 20000, required=recipe != 'nano_refine')
        refs = payload.get('sourceRevisionIds', [])
        if not isinstance(refs, list) or len(refs) > 20 or any(not isinstance(i, str) for i in refs) or len(set(refs)) != len(refs):
            invalid('每个阶段请选择一张已审核的参考图。')
        with self.repository.transaction(ctx) as tx:
            project = self._project(tx, payload.get('projectId'))
            if project['plan'].get('needsReview'):
                raise WorkflowError('PLAN_REVIEW_REQUIRED', '请先核对并确认自动拆出的资产清单。', 409)
            entity = self._entity(project, payload.get('entityId'))
            from .art_direction import apply
            from .art_studies import describe as study_entities
            exploratory = recipe in ('mj_style','image25_style') and entity['id'] in {r['entityId'] for r in study_entities(project).values()}
            prompt, direction_version = (prompt, 0) if exploratory else apply(self, tx, project, prompt, ownership, recipe)
            from .production_lineage import members
            if recipe not in ('mj_style','image25_style') and entity['id'] in members(tx, project) and not direction_version:
                raise WorkflowError('STYLE_REVIEW_REQUIRED', '请先确认本剧风格，再制作主多视图和剧情状态。', 409)
            if recipe in ('storyboard_image','image25_storyboard'):
                if entity['category'] != 'shot' or not refs:
                    invalid('分镜图片需要镜头档案和已审核的物料参考图。')
                for rid in refs:
                    source = self._source(tx, project['id'], entity['id'], rid, ownership, cross_entity=True)
                    from .art_direction import is_style_reference
                    if source['stage'] not in ('asset', 'refine', 'reference') and not is_style_reference(project, source):
                        invalid('分镜引用须为已审核的 Image2 或 Nano 物料图。')
                return dict(projectId=project['id'], entityId=entity['id'], recipe=recipe, prompt=prompt,
                            settings=copy.deepcopy(settings), sourceRevisionIds=refs,
                            workflowSnapshot={'entityVersion': entity['version'], 'styleVersion': project['plan']['styleVersion'],
                                              'artDirectionVersion': direction_version, 'sourceHashes': {rid:self._revision(tx,rid)['sha256'] for rid in refs}})
            repair = None
            if payload.get('repairOfRevisionId'):
                repair = self._revision(tx, payload['repairOfRevisionId'])
                if (repair['projectId'] != project['id'] or repair['entityId'] != entity['id']
                        or repair['stage'] != STAGES[recipe] or owner_key(repair['ownership']) != owner_key(ownership)):
                    raise WorkflowError('OWNERSHIP_MISMATCH', '返修目标与当前资产或账号不一致。', 409)
                if repair['review'] != 'changes_requested' or not repair.get('reviewNote'):
                    invalid('请先对目标图片填写返修意见。')
                refs = list(repair['sourceRevisionIds'])
                prompt = (prompt or repair['prompt']) + '\n返修意见：' + repair['reviewNote']
            stage = STAGES[recipe]
            source = None
            from .production_lineage import character_state, scene_state
            if stage == 'style' and (character_state(tx, project, entity['id']) or scene_state(tx, project, entity['id'])):
                invalid('请先制作人物或场景主形象；剧情状态须参考已确认的主多视图。')
            primary_count = 0 if stage == 'style' else 1
            for rid in refs[primary_count:]:
                self._source(tx, project['id'], entity['id'], rid, ownership, cross_entity=True)
            if stage != 'style':
                if not refs:
                    invalid('请先选择上一阶段已人工审核通过的图片。')
                candidate = self._revision(tx, refs[0])
                # Nano repairs ALWAYS resolve to the original Image2 bytes.
                if stage == 'refine' and candidate['stage'] == 'refine':
                    if candidate['projectId'] != project['id'] or candidate['entityId'] != entity['id']:
                        invalid('精修来源与当前档案不一致。')
                    if owner_key(candidate['ownership']) != owner_key(ownership):
                        raise WorkflowError('OWNERSHIP_MISMATCH', '精修来源属于其他账号或空间。', 409)
                    original_id = candidate.get('refineSourceRevisionId')
                    candidate = self._revision(tx, original_id)
                from .production_lineage import image2_source_allowed
                shared_style = stage == 'asset' and image2_source_allowed(tx, project, entity['id'], candidate)
                if stage == 'asset' and not shared_style:
                    invalid('请先生成并确认同一角色的人物主多视图，再派生剧情状态；主多视图使用已选人物风格形象。')
                source = self._source(tx, project['id'], entity['id'], candidate['id'], ownership, cross_entity=shared_style)
                if stage == 'asset' and not shared_style or stage == 'refine' and source['stage'] != 'asset':
                    invalid('人物剧情状态需要已确认的人物主多视图；主多视图需要已选人物风格形象；Nano 需要原始 Image2 图。')
                refs = [source['id'], *refs[1:]]
            if stage == 'refine':
                prompt = REFINE_PROMPT + ('\n补充要求：' + prompt if prompt else '')
            return dict(projectId=project['id'], entityId=entity['id'], recipe=recipe, prompt=prompt,
                        settings=copy.deepcopy(settings), sourceRevisionIds=refs,
                        refineSourceRevisionId=source['id'] if stage == 'refine' else None,
                        repairOfRevisionId=repair['id'] if repair else None,
                        workflowSnapshot={'entityVersion': entity['version'], 'styleVersion': project['plan']['styleVersion'],
                                          'artDirectionVersion': direction_version, 'sourceHashes': {rid: self._revision(tx, rid)['sha256'] for rid in refs}})

    def prepare(self, ctx, payload, expectedSelectionRevision, idempotencyKey):
        if self.tasks is None:
            raise WorkflowError('TASK_SERVICE_UNAVAILABLE', '任务服务尚未接入；已保存的档案可继续编辑。', 503)
        # TaskService resolves the owner then calls build_spec; never resolve it from browser data here.
        return self.tasks.prepare(ctx, payload, expectedSelectionRevision, idempotencyKey)

    def get_revision(self, ctx, revision_id, ownership=None, require_approved=True):
        with self.repository.transaction(ctx) as tx:
            revision = self._revision(tx, revision_id)
            if ownership is not None and owner_key(ownership) != owner_key(revision['ownership']):
                raise WorkflowError('OWNERSHIP_MISMATCH', '素材与任务所属账号或空间不同。', 409)
            if require_approved and not self._valid(tx, revision, True):
                conflict('素材尚未审核通过或已失效。')
            return self._public_revision(tx, revision)

    def record_output(self, ctx, task, raw, output_key='0'):
        """Internal, trusted TaskService callback after provider bytes download.

        The caller passes its persisted task, never a browser body. All external
        URLs, receipts, credentials and filesystem paths are deliberately absent.
        """
        ownership = task.get('ownership', {})
        if ownership.get('tenantId') != tenant(ctx) or any(not ownership.get(k) for k in REQUIRED_OWNER):
            raise WorkflowError('OWNERSHIP_MISMATCH', '输出任务归属不完整。', 409)
        recipe = task.get('recipe')
        if recipe not in STAGES or task.get('status') not in ('downloading', 'completed'):
            invalid('任务尚未进入图片收取阶段。')
        if not isinstance(task.get('id'), str) or not isinstance(output_key, str) or len(output_key) > 100:
            invalid('输出标识无效。')
        metadata = inspect_image(raw)
        with self.repository.transaction(ctx, write=True) as tx:
            project = self._project(tx, task.get('projectId'))
            entity = self._entity(project, task.get('entityId'))
            # Retries preserve the original review and bytes instead of creating duplicate outputs.
            prior = next((r for r in tx.state['revisions'].values()
                          if r['taskId'] == task['id'] and r['outputKey'] == output_key), None)
            if prior:
                if prior['sha256'] != metadata['sha256'] or owner_key(prior['ownership']) != owner_key(ownership):
                    conflict('同一任务输出发生变化，已阻止覆盖已存版本。')
                return self._public_revision(tx, prior)
            snapshot = task.get('workflowSnapshot') or task.get('spec', {}).get('workflowSnapshot')
            if not isinstance(snapshot, dict) or not {'entityVersion', 'styleVersion', 'sourceHashes'} <= snapshot.keys():
                invalid('任务缺少准备时的工作流版本快照。')
            refs = task.get('sourceRevisionIds', [])
            if not isinstance(refs, list) or len(refs)>20 or (recipe not in ('mj_style','image25_style') and not refs):
                invalid('任务参考链不完整。')
            for index, source_id in enumerate(refs):
                source = self._revision(tx, source_id)
                from .production_lineage import same_state_family
                shared_style = recipe in ('image2_asset','image25_asset') and same_state_family(tx, project, entity['id'], source['entityId'])
                supplemental = recipe in ('mj_style','image25_style') or index>0
                if (source['projectId'] != project['id'] or (not supplemental and recipe not in ('storyboard_image','image25_storyboard') and not shared_style and source['entityId'] != entity['id'])
                        or owner_key(source['ownership']) != owner_key(ownership)
                        or snapshot['sourceHashes'].get(source_id) != source['sha256']
                        or source['stage'] not in (('style','asset','refine','reference') if supplemental else ('asset','refine','reference') if recipe in ('storyboard_image','image25_storyboard') else ('style','asset') if recipe in ('image2_asset','image25_asset') else ('asset',))):
                    conflict('任务参考链与准备记录不一致。')
            asset = next(a for a in tx.state['assets'].values()
                         if a['projectId'] == project['id'] and a['entityId'] == entity['id'])
            revision = dict(id=new_id('rev'), assetId=asset['id'], projectId=project['id'], entityId=entity['id'],
                            tenantId=tenant(ctx), ownership={k: ownership.get(k) for k in (*REQUIRED_OWNER, *OWNER_FIELDS)},
                            stage=STAGES[recipe], recipe=recipe, taskId=task['id'], outputKey=output_key,
                            sourceRevisionIds=list(refs), refineSourceRevisionId=refs[0] if recipe == 'nano_refine' else None,
                            entityVersion=snapshot['entityVersion'], styleVersion=snapshot['styleVersion'],
                            prompt=task.get('prompt', ''), settings=copy.deepcopy(task.get('settings', {})),
                            modelLabel=task.get('modelLabel'), review='pending', reviewNote='', reviewHistory=[],
                            status='ready', createdAt=now(), blobId=tx.put_blob(raw), **metadata)
            if recipe not in ('mj_style','image25_style') and snapshot.get('artDirectionVersion'):
                revision['artDirectionVersion'] = snapshot['artDirectionVersion']
            tx.state['revisions'][revision['id']] = revision
            asset['revisionIds'].append(revision['id'])
            asset['version'] += 1
            self._invalidate(tx, project['id'])
            return self._public_revision(tx, revision)

    def review(self, ctx, asset_id, payload):
        public_input(payload, {'revisionId', 'sha256', 'decision', 'note', 'expectedVersion',
                               'confirmCurrentBasis', 'expectedEntityVersion'})
        decision = payload.get('decision')
        if decision not in ('approved', 'changes_requested'):
            invalid('请选择保留此版或退回修改。')
        note = text_field(payload, 'note', 2000)
        if decision == 'changes_requested' and len(note) < 4:
            invalid('请填写至少 4 个字的具体返修意见。')
        with self.repository.transaction(ctx, write=True) as tx:
            asset = self._asset(tx, asset_id)
            expected(payload, asset['version'])
            revision = self._revision(tx, payload.get('revisionId'))
            if revision['assetId'] != asset_id:
                missing()
            if payload.get('sha256') != revision['sha256'] or hashlib.sha256(tx.get_blob(revision['blobId'])).hexdigest() != revision['sha256']:
                conflict('画面文件与审核版本不一致，未记录审核。')
            if not self._valid(tx, revision):
                reconfirmation = self._reconfirmation(tx, revision)
                if (decision != 'approved' or payload.get('confirmCurrentBasis') is not True
                        or not reconfirmation or payload.get('expectedEntityVersion') != reconfirmation['entityVersion']):
                    conflict('当前镜头方案已变化，请先查看旧图并确认是否仍适用；人物或风格参考失效时需重新制作。')
                revision['applicability'] = {'entityVersion': reconfirmation['entityVersion'], 'confirmedAt': now(),
                                           'note': note, 'sha256': revision['sha256']}
            if decision == 'approved':
                for rid in asset['revisionIds']:
                    other = tx.state['revisions'][rid]
                    if (rid != revision['id'] and other['stage'] == revision['stage'] and other['review'] == 'approved'
                            and owner_key(other['ownership']) == owner_key(revision['ownership'])):
                        other['review'] = 'superseded'
            revision.update(review=decision, reviewNote=note)
            revision['reviewHistory'].append({'id': new_id('review'), 'decision': decision, 'note': note,
                                             'sha256': revision['sha256'], 'at': now(),
                                             **({'applicability': copy.deepcopy(revision['applicability'])} if payload.get('confirmCurrentBasis') is True else {})})
            asset['version'] += 1
            self._invalidate(tx, asset['projectId'])
            return {'assetVersion': asset['version'], 'revision': self._public_revision(tx, revision)}

    def list_assets(self, ctx, project_id):
        with self.repository.transaction(ctx) as tx:
            self._project(tx, project_id)
            items = []
            for asset in tx.state['assets'].values():
                if asset['projectId'] != project_id:
                    continue
                item = copy.deepcopy(asset)
                item['revisions'] = [self._public_revision(tx, tx.state['revisions'][rid]) for rid in asset['revisionIds']]
                items.append(item)
            return {'items': items, 'nextCursor': None, 'coverage': self._coverage(tx, project_id)}

    def _coverage(self, tx, project_id):
        project = self._project(tx, project_id)
        from .production_coverage import coverage
        production = coverage(self, tx, project)
        if production is not None:
            return production
        rows = []
        for entity in project['plan']['entities']:
            revisions = [r for r in tx.state['revisions'].values() if r['projectId'] == project_id
                         and r['entityId'] == entity['id'] and self._valid(tx, r, True)]
            stages = {stage: any(r['stage'] == stage for r in revisions) for stage in (('storyboard',) if entity['category']=='shot' else ('style','asset','refine'))}
            rows.append(dict(entityId=entity['id'], name=entity['name'], category=entity['category'],
                             stages=stages, ready=all(stages[stage] for stage in (('storyboard',) if entity['category']=='shot' else ('style','asset')))))
        ready = sum(row['ready'] for row in rows)
        return dict(total=len(rows), ready=ready, complete=bool(rows) and ready == len(rows),
                    entities=rows, missing=[r for r in rows if not r['ready']])

    def content(self, ctx, asset_id, revision_id, thumbnail=False):
        with self.repository.transaction(ctx) as tx:
            asset = self._asset(tx, asset_id)
            if revision_id not in asset['revisionIds']:
                missing()
            revision = self._revision(tx, revision_id)
            raw = tx.get_blob(revision['blobId'])
            if hashlib.sha256(raw).hexdigest() != revision['sha256']:
                conflict('素材文件校验未通过。')
            mime = revision['mime']
        if thumbnail:
            from PIL import Image
            with Image.open(io.BytesIO(raw)) as im:
                im.thumbnail((720, 720))
                out = io.BytesIO()
                im.convert('RGB').save(out, format='JPEG', quality=85)
                raw, mime = out.getvalue(), 'image/jpeg'
        return raw, mime

    def export(self, ctx, project_id):
        """Read-only ZIP snapshot; current approved revisions only; no raw source script, secrets or paths."""
        with self.repository.transaction(ctx) as tx:
            project = self._project(tx, project_id)
            coverage = self._coverage(tx, project_id)
            allowed = set(coverage['exportRevisionIds']) if coverage.get('scope') == 'production' else None
            chosen = [r for r in tx.state['revisions'].values()
                      if r['projectId'] == project_id and not r.get('referenceOnly') and self._valid(tx, r, True)
                      and (allowed is None or r['id'] in allowed)]
            if not chosen:
                conflict('当前项目还没有人工审核通过的有效资产。')
            # Bound memory and prevent a tenant export from exhausting the web process.
            if len(chosen) > 900 or sum(r['bytes'] for r in chosen) > 60 * 1024 * 1024:
                invalid('资产包过大，请将项目拆分后下载。')
            manifest = dict(schemaVersion=1, projectId=project_id, projectName=project['name'], exportedAt=now(),
                            planVersion=project['plan']['version'], coverage=coverage, assets=[])
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
                for i, revision in enumerate(sorted(chosen, key=lambda r: (r['entityId'], r['stage'], r['id'])), 1):
                    raw = tx.get_blob(revision['blobId'])
                    if hashlib.sha256(raw).hexdigest() != revision['sha256']:
                        conflict('素材文件已改变，未生成交付包。')
                    entity = self._entity(project, revision['entityId'])
                    title = re.sub(r'[^\w\u4e00-\u9fff-]', '_', entity['name'])[:60] or 'asset'
                    filename = f"{CATEGORIES[entity['category']]}/{i:03d}-{title}-{revision['stage']}-{revision['id'][-8:]}{revision['extension']}"
                    archive.writestr(filename, raw)
                    manifest['assets'].append(dict(file=filename, assetId=revision['assetId'], revisionId=revision['id'],
                        entityId=entity['id'], category=entity['category'], name=entity['name'], stage=revision['stage'],
                        sha256=revision['sha256'], mime=revision['mime'], width=revision['width'], height=revision['height'],
                        sourceRevisionIds=revision['sourceRevisionIds'], refineSourceRevisionId=revision['refineSourceRevisionId'],
                        # Owner IDs retain provenance; no subject, receipt, token, URL, local path or raw task dict.
                        ownership={k: revision['ownership'].get(k) for k in ('provider', 'providerAccountId', 'spaceId', 'spaceKind')},
                        review={'decision': 'approved', 'at': revision['reviewHistory'][-1]['at']},
                        **({'applicability': copy.deepcopy(revision['applicability']),
                            'generatedEntityVersion': revision['entityVersion']} if revision.get('applicability') else {})))
                archive.writestr('资产清单.json', json.dumps(manifest, ensure_ascii=False, indent=2))
            return buffer.getvalue(), manifest

    def validate_task_inputs(self, ctx, spec, ownership):
        """TaskService InputValidator port, including a mandatory version snapshot.

        The task module must retain workflowSnapshot in task.inputs/inputHash,
        then compare it during submit/recover. Do not silently drop this field.
        """
        prepared = self.build_spec(ctx, spec, ownership)
        if prepared['workflowSnapshot'].get('artDirectionVersion'):
            project = self.get_project(ctx, spec['projectId'])
            direction = project['artDirection']
            from .art_direction import contains_direction
            if not contains_direction(spec.get('prompt', ''), direction):
                conflict('请沿用当前本剧美术规范重新准备任务。')
        if prepared['sourceRevisionIds'] != spec.get('sourceRevisionIds', []):
            conflict('Nano 任务必须明确引用原始 Image2 版本，请重新准备。')
        with self.repository.transaction(ctx) as tx:
            sources = []
            for index, identity in enumerate(prepared['sourceRevisionIds']):
                from .production_lineage import image2_source_allowed
                project = self._project(tx, spec['projectId'])
                candidate = self._revision(tx, identity)
                shared_style = spec['recipe'] in ('image2_asset','image25_asset') and image2_source_allowed(tx, project, spec['entityId'], candidate)
                source = self._source(tx, spec['projectId'], spec['entityId'], identity, ownership, cross_entity=spec['recipe'] in ('storyboard_image','image25_storyboard','mj_style','image25_style') or index>0 or shared_style)
                if hashlib.sha256(tx.get_blob(source['blobId'])).hexdigest() != source['sha256']:
                    conflict('参考文件校验未通过。')
                sources.append(dict(revisionId=identity, ownership=copy.deepcopy(source['ownership']),
                                    review=source['review'], stale=False, sha256=source['sha256']))
            return {'projectTenantId': tenant(ctx), 'spec': copy.deepcopy(spec), 'sources': sources,
                    'workflowSnapshot': prepared['workflowSnapshot']}

    def archive(self, ctx, project_id, payload):
        public_input(payload, {'expectedVersion'})
        # Snapshot and record are in a single tenant transaction; nested export
        # would deadlock some stores, so build the snapshot before CAS-checking.
        raw, manifest = self.export(ctx, project_id)
        with self.repository.transaction(ctx, write=True) as tx:
            project = self._project(tx, project_id)
            expected(payload, project['version'])
            current = self._coverage(tx, project_id)
            if not current['complete']:
                conflict('尚有未完成审核的档案，请完成所有阶段后确认归档。可先下载已通过的部分资产。')
            if manifest['planVersion'] != project['plan']['version']:
                conflict('资产清单已变化，请重新确认归档。')
            if manifest['coverage'].get('scopeVersion') != current.get('scopeVersion'):
                conflict('制作方案已变化，请重新核对交付范围。')
            allowed = set(current['exportRevisionIds']) if current.get('scope') == 'production' else None
            current_ids = sorted(r['id'] for r in tx.state['revisions'].values()
                                 if r['projectId'] == project_id and self._valid(tx, r, True)
                                 and (allowed is None or r['id'] in allowed))
            if current_ids != sorted(r['revisionId'] for r in manifest['assets']):
                conflict('审核结果已变化，请重新确认归档。')
            record = dict(id=new_id('bundle'), projectId=project_id, createdAt=now(),
                          sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), coverage=current,
                          planVersion=project['plan']['version'], revisionIds=current_ids,
                          assetCount=len(manifest['assets']), blobId=tx.put_blob(raw))
            tx.state['bundles'][record['id']] = record
            project.update(version=project['version'] + 1, updatedAt=now(), lastBundleId=record['id'])
            return {k: copy.deepcopy(v) for k, v in record.items() if k != 'blobId'}

    def list_bundles(self, ctx, project_id):
        with self.repository.transaction(ctx) as tx:
            self._project(tx, project_id)
            return {'items': [{k: copy.deepcopy(v) for k, v in r.items() if k != 'blobId'}
                              for r in tx.state['bundles'].values() if r['projectId'] == project_id], 'nextCursor': None}

    def bundle_content(self, ctx, project_id, bundle_id):
        with self.repository.transaction(ctx) as tx:
            self._project(tx, project_id)
            record = tx.state['bundles'].get(bundle_id)
            if not record or record['projectId'] != project_id:
                missing()
            raw = tx.get_blob(record['blobId'])
            if hashlib.sha256(raw).hexdigest() != record['sha256']:
                conflict('归档文件校验未通过。')
            return raw
