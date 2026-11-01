"""Official image tools behind immutable ownership and fresh authorization.

No network runs on import. Default policy forbids external writes. Tools with
opaque output schemas require explicit evidence-backed response contracts.
"""
import copy
import hashlib
import math
import logging
import re
from contextlib import nullcontext

from backend.tasks.ports import DownloadArtifact
from .contracts import ResponseContracts, ToolCatalog, validate
from .errors import GenerationError
from .media import inspect_image
from .project_coordination import project_mutation
from .types import (AuthorizedMCP, GenerationPolicy, ProjectBinding, RecipeBinding,
                    VerifiedReference, digest, opaque, owner, safe_receipt, same_owner)

RECIPES = {'mj_style', 'image25_style', 'image2_asset', 'image25_asset', 'nano_refine', 'storyboard_image', 'image25_storyboard'}
DELIVERY_FIELDS = ('operationId', 'projectId', 'status', 'files', 'fileUrl', 'fileMime',
                   'fileNodeId', 'fileOutputIndex')
RESERVED = {'model', 'provider', 'modeType', 'scene', 'prompt', 'imageList', 'videoList',
            'audioList', 'mixedList', 'imageListOrder', 'videoListOrder', 'audioListOrder',
            'mixedListOrder', 'source_node_keys', 'generateTypes', 'checkpointId'}


class GenerationAdapter:
    def __init__(self, *, journal, submission_bridge, project_resolver, references,
                 media_transfer, recipes, catalog=None, responses=None, reference_route=None,
                 policy=None):
        self.journal, self.bridge = journal, submission_bridge
        self.projects, self.references, self.media = project_resolver, references, media_transfer
        self.recipes = copy.deepcopy(recipes)
        self.catalog = catalog or ToolCatalog.bundled()
        self.responses = responses or ResponseContracts()
        self.reference_route = reference_route
        self.policy = policy or GenerationPolicy()

    def bind(self, *, ownership, authorize):
        if not callable(authorize):
            raise GenerationError('PROVIDER_AUTHORIZATION_REQUIRED')
        return BoundImageClient(self, owner(ownership), authorize)


class BoundImageClient:
    def __init__(self, adapter, ownership, authorize):
        self.a, self._owner, self._authorize = adapter, copy.deepcopy(ownership), authorize

    def __repr__(self):
        return '<BoundImageClient immutable-owner; credentials not accepted>'

    def _authorize_scopes(self, scopes):
        try:
            permit = self._authorize(frozenset(scopes))
        except Exception as exc:
            if getattr(exc, 'code', None) in {'PROVIDER_SCOPE_UNAVAILABLE', 'PROVIDER_SCOPE_REQUIRED'}:
                raise GenerationError('PROVIDER_SCOPE_REQUIRED', required_scopes=scopes) from None
            raise GenerationError('PROVIDER_AUTHORIZATION_REQUIRED') from None
        if not isinstance(permit, AuthorizedMCP) or not same_owner(permit.ownership, self._owner):
            raise GenerationError('OWNERSHIP_MISMATCH')
        missing = frozenset(scopes) - permit.granted_scopes
        if missing:
            raise GenerationError('PROVIDER_SCOPE_REQUIRED', required_scopes=missing)
        return permit

    def _preflight_tools(self, names):
        scopes = set()
        for name in names:
            scopes.update(self.a.catalog.scopes(name))
        self._authorize_scopes(scopes)

    def _call(self, name, arguments):
        self.a.catalog.request(name, arguments)
        permit = self._authorize_scopes(self.a.catalog.scopes(name))
        try:
            project = arguments.get('projectId', arguments.get('project_id'))
            mutation = name in {'create_node', 'update_node', 'upload_media', 'generation_submit', 'prepare_project_delivery'}
            with project_mutation(self._owner, project) if mutation and project else nullcontext():
                result = permit.call_tool(name, copy.deepcopy(arguments))
        except GenerationError:
            raise
        except Exception as exc:
            code = getattr(exc, 'code', None)
            known = {'PROVIDER_PROTOCOL_ERROR','PROVIDER_UNAVAILABLE','PROVIDER_RESPONSE_TOO_LARGE',
                     'PROVIDER_ACCOUNT_READ_UNAVAILABLE',
                     'PROVIDER_SCOPE_UNAVAILABLE','PROVIDER_AUTHORIZATION_REQUIRED','PROVIDER_SCOPE_REQUIRED',
                     'OWNERSHIP_MISMATCH','PROVIDER_NODE_NAME_CONFLICT','PROVIDER_SNAPSHOT_REVISION_MISMATCH'}
            logging.getLogger(__name__).error('Official tool failed: tool=%s code=%s',
                name, code if code in known else 'UNCLASSIFIED')
            if code == 'PROVIDER_SCOPE_UNAVAILABLE':
                raise GenerationError('PROVIDER_SCOPE_REQUIRED', required_scopes=self.a.catalog.scopes(name)) from None
            if code in {'PROVIDER_AUTHORIZATION_REQUIRED', 'PROVIDER_SCOPE_REQUIRED', 'OWNERSHIP_MISMATCH', 'PROVIDER_SNAPSHOT_REVISION_MISMATCH', 'PROVIDER_ACCOUNT_READ_UNAVAILABLE'}:
                raise GenerationError(code) from None
            raise GenerationError('PROVIDER_UNAVAILABLE') from None
        return self.a.catalog.response(name, result)

    def list_models(self, spaceId=None):
        if spaceId is not None and spaceId != self._owner['spaceId']:
            raise GenerationError('OWNERSHIP_MISMATCH')
        # Exact public arguments. Preserve unknown catalogue shape instead of guessing a list path.
        return self._call('search_models', {'action': 'search', 'nodeType': 'image'})

    def get_model(self, model):
        if not isinstance(model, str) or not model.strip() or model != model.strip():
            raise GenerationError('INPUT_INVALID')
        return self._call('get_model', {'model': model})

    def _project(self, local_project):
        resolver = getattr(self.a.projects, 'resolve', None)
        binding = resolver(self, local_project) if resolver else self.a.projects(self._owner, local_project)
        if (not isinstance(binding, ProjectBinding) or not binding.verified or not binding.evidence):
            raise GenerationError('PROJECT_BINDING_REQUIRED')
        if not same_owner(binding.ownership, self._owner):
            raise GenerationError('OWNERSHIP_MISMATCH')
        return opaque(binding.project_id)

    def _sources(self, snapshots, ids, recipe):
        if (not isinstance(snapshots, list) or not isinstance(ids, list)
                or any(not isinstance(x, str) for x in ids)
                or any(not isinstance(x, dict) for x in snapshots)
                or len(ids) != len(set(ids)) or [x.get('revisionId') for x in snapshots] != ids):
            raise GenerationError('SOURCE_CHANGED')
        if (recipe in {'nano_refine', 'image2_asset', 'image25_asset'} and len(ids) != 1
                or recipe in {'mj_style','image25_style'} and ids
                or recipe in {'storyboard_image','image25_storyboard'} and not 1 <= len(ids) <= 20):
            raise GenerationError('SOURCE_REVIEW_REQUIRED')
        results = []
        for snap in snapshots:
            # TaskService persists owner + revision + byte hash only. Review is
            # re-read authoritatively below, not inferred from optional hints.
            if (not same_owner(snap.get('ownership'), self._owner)
                    or 'review' in snap and snap['review'] != 'approved' or snap.get('stale')):
                raise GenerationError('SOURCE_REVIEW_REQUIRED')
            ref = self.a.references.read(self._owner, snap)
            if (not isinstance(ref, VerifiedReference) or not same_owner(ref.ownership, self._owner)
                    or ref.revision_id != snap['revisionId'] or ref.sha256 != snap['sha256']
                    or not ref.approved or ref.stale
                    or ref.stage not in (('asset','refine') if recipe in {'storyboard_image','image25_storyboard'} else ('style','asset') if recipe in {'image2_asset','image25_asset'} else ('asset',))):
                raise GenerationError('SOURCE_CHANGED')
            inspect_image(ref.content, ref.mime, max_bytes=self.a.policy.max_image_bytes,
                          max_pixels=self.a.policy.max_pixels, sha256=ref.sha256)
            results.append(ref)
        return results

    def _model(self, spec):
        recipe = spec.get('recipe')
        if recipe not in RECIPES:
            raise GenerationError('VIDEO_OR_AUDIO_DISABLED')
        binding = self.a.recipes.get(recipe)
        if not isinstance(binding, RecipeBinding) or not binding.model or not binding.evidence:
            raise GenerationError('MODEL_BINDING_REQUIRED')
        mapping = self.a.responses.require('get_model', self.a.policy, ('model', 'parameterSchemas'))
        model = self.get_model(binding.model)
        # Names are public, but their complete shape still requires an audited mapping.
        # Never convert legacy CLI/private model metadata into a guessed MCP contract.
        try:
            contract = {'model': mapping.read(model, 'model'),
                        'parameterSchemas': mapping.read(model, 'parameterSchemas')}
        except GenerationError as exc:
            if exc.code == 'PROVIDER_PROTOCOL_ERROR':
                raise GenerationError('MODEL_CONTRACT_UNVERIFIED') from None
            raise
        if not isinstance(contract['model'], str) or not isinstance(contract['parameterSchemas'], dict):
            raise GenerationError('MODEL_CONTRACT_UNVERIFIED')
        model_key = opaque(contract['model'])
        schemas, params = contract['parameterSchemas'], {}
        settings = spec.get('settings', {})
        if not isinstance(settings, dict):
            raise GenerationError('INPUT_INVALID')
        for key, value in settings.items():
            target = binding.controls.get(key, key)
            if target in params or target in RESERVED or target not in schemas and target != 'count':
                raise GenerationError('INPUT_INVALID')
            params[target] = value
        params.setdefault('count', 1)  # Official generation_submit says exact count, default 1.
        count = params['count']
        if type(count) is not int or not 1 <= count <= self.a.policy.max_outputs:
            raise GenerationError('INPUT_INVALID')
        for key, value in params.items():
            if key in schemas:
                validate(schemas[key], value)
        prompt = spec.get('prompt')
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 50000:
            raise GenerationError('INPUT_INVALID')
        request = {'model': model_key, 'prompt': prompt, 'params': params}
        # Also validates nested forbidden media/provider control fields.
        self.a.catalog.request('generation_submit', {'project_id': 'validation_only',
                    'idempotency_key': 'validation_only', 'kind': 'image', 'request': request})
        schema_hash = digest({'inputContract': contract, 'controls': dict(binding.controls),
                             'tool': self.a.catalog.fingerprint('generation_submit')})
        return model_key, params, count, schema_hash

    def prepare(self, payload):
        if not isinstance(payload, dict) or any(k not in payload for k in
                ('projectId', 'entityId', 'recipe', 'prompt', 'sourceRevisionIds', 'settings')):
            raise GenerationError('INPUT_INVALID')
        if not same_owner(payload.get('ownership'), self._owner):
            raise GenerationError('OWNERSHIP_MISMATCH')
        spec = {k: copy.deepcopy(payload[k]) for k in ('projectId', 'entityId', 'recipe', 'prompt', 'sourceRevisionIds', 'settings')}
        task_id, request_hash = opaque(payload.get('localTaskId')), payload.get('requestHash')
        if not isinstance(request_hash, str) or not re.fullmatch('[a-f0-9]{64}', request_hash):
            raise GenerationError('INPUT_INVALID')
        self._preflight_tools(['get_model'])
        project_id = self._project(spec['projectId'])
        refs = self._sources(payload.get('sources'), spec['sourceRevisionIds'], spec['recipe'])
        if refs:
            if self.a.reference_route is None:
                raise GenerationError('REFERENCE_ROUTE_SCHEMA_REQUIRED', missing='create_node/update_node/read_node')
            self.a.reference_route.preflight(self.a.catalog, self.a.responses, self.a.policy)
            self._upload_contracts()
        model_key, params, count, schema_hash = self._model(spec)
        prepared = dict(modelKey=model_key, schemaHash=schema_hash, requestHash=request_hash,
                        count=count, cost={'state': 'unknown', 'amount': None, 'unit': None},
                        providerReceipt={'projectId': project_id})
        record = dict(spec=spec, prepared=prepared, params=params, sources=copy.deepcopy(payload['sources']))
        with self.a.journal.edit(self._owner, task_id) as state:
            if state.get('record') and state['record'] != record:
                raise GenerationError('IDEMPOTENCY_CONFLICT')
            state['record'] = record
        return copy.deepcopy(prepared)

    def _record(self, task_id):
        with self.a.journal.edit(self._owner, task_id) as state:
            record = copy.deepcopy(state.get('record'))
        if not record:
            raise GenerationError('ORIGINAL_RECEIPT_REQUIRED')
        return record

    def _claim(self, task_id, step, request):
        with self.a.journal.edit(self._owner, task_id) as state:
            previous = state['steps'].get(step)
            fingerprint = digest(request)
            if previous:
                if previous['hash'] != fingerprint:
                    raise GenerationError('IDEMPOTENCY_CONFLICT')
                if previous.get('done'):
                    return copy.deepcopy(previous['result'])
                raise GenerationError('OPERATION_UNKNOWN')
            state['steps'][step] = {'hash': fingerprint, 'attempted': True, 'done': False}
        return None

    def _finish(self, task_id, step, safe_result):
        # Caller passes only allowlisted IDs/states, never raw responses or signed URLs.
        with self.a.journal.edit(self._owner, task_id) as state:
            state['steps'][step].update(done=True, result=copy.deepcopy(safe_result))

    def _checkpoint(self, task_id, receipt):
        receipt = safe_receipt(receipt)
        self.a.bridge.checkpoint(task_id, self._owner, receipt)
        return receipt

    def _upload_contracts(self):
        return (self.a.responses.require('upload_ticket', self.a.policy,
                                        ('parts', 'path', 'uploadId', 'partUrl', 'partNumber')),
                self.a.responses.require('upload_complete', self.a.policy, ('fileRef',)))

    def _write_readiness(self):
        # Do not pay for a task when its recovery/export contracts are already absent.
        self.a.responses.require('task_status', self.a.policy, ('taskId', 'projectId', 'nodeId', 'status'))
        for tool in ('prepare_project_delivery', 'get_web_operation_status'):
            self.a.responses.require(tool, self.a.policy, DELIVERY_FIELDS)
        self._preflight_tools(['task_status', 'prepare_project_delivery', 'get_web_operation_status'])
        self._authorize_scopes({'libtv:task:write'})
        check = getattr(self.a.media, 'preflight', None)
        if not callable(check):
            raise GenerationError('TRANSFER_HOST_UNVERIFIED')
        check()

    def submit(self, prepared, idempotencyKey):
        if not same_owner(prepared.get('ownership'), self._owner):
            raise GenerationError('OWNERSHIP_MISMATCH')
        if not self.a.policy.allow_external_writes:
            raise GenerationError('GENERATION_DISABLED')
        task_id = opaque(prepared.get('localTaskId'))
        record = self._record(task_id)
        expected = record['prepared']
        if (prepared.get('spec') != record['spec'] or prepared.get('sources') != record['sources']
                or any(prepared.get(k) != v for k, v in expected.items())):
            raise GenerationError('IDEMPOTENCY_CONFLICT')
        self.a.bridge.check(task_id, self._owner, expected['requestHash'], idempotencyKey)
        self._write_readiness()
        project_id = self._project(record['spec']['projectId'])
        if project_id != expected['providerReceipt']['projectId']:
            raise GenerationError('OWNERSHIP_MISMATCH')
        refs = self._sources(record['sources'], record['spec']['sourceRevisionIds'], record['spec']['recipe'])
        model, params, count, schema_hash = self._model(record['spec'])
        if (model, params, count, schema_hash) != (expected['modelKey'], record['params'], expected['count'], expected['schemaHash']):
            raise GenerationError('SOURCE_CHANGED')
        ref = self._checkpoint(task_id, {'projectId': project_id})
        try:
            if refs:
                if self.a.reference_route is None:
                    raise GenerationError('REFERENCE_ROUTE_SCHEMA_REQUIRED')
                self.a.reference_route.preflight(self.a.catalog, self.a.responses, self.a.policy)
                self._preflight_tools(['upload_ticket', 'upload_complete', 'upload_media',
                                      *self.a.reference_route.tools])
                uploaded = [self._upload(task_id, project_id, item, idempotencyKey, expected['requestHash']) for item in refs]
                # Route implementation must checkpoint its node before the charged run.
                return self.a.reference_route.submit(self, task_id, record, uploaded, idempotencyKey)
            args = {'project_id': project_id, 'idempotency_key': idempotencyKey, 'kind': 'image',
                    'request': {'model': model, 'prompt': record['spec']['prompt'], 'params': params}}
            self._preflight_tools(['generation_submit'])
            self.a.catalog.request('generation_submit', args)
            cached = self._claim(task_id, 'generation', args)
            if cached is not None:
                return cached
            self.a.bridge.check(task_id, self._owner, expected['requestHash'], idempotencyKey)
            result = self._call('generation_submit', args)
            # task_id is explicitly documented by the official tool, unlike arbitrary status paths.
            tid = opaque(result.get('task_id'))
            if tid.startswith('cop_'):
                raise GenerationError('PROVIDER_PROTOCOL_ERROR')
            ref = self._checkpoint(task_id, {'projectId': project_id, 'taskId': tid})
            # queued is the local accepted Task SOT state; no claim of completed generation.
            normalized = {'status': 'queued', 'providerReceipt': ref}
            self._finish(task_id, 'generation', normalized)
            return normalized
        except GenerationError as exc:
            if exc.provider_receipt is None:
                exc.provider_receipt = ref
            raise

    def _upload(self, task_id, project_id, ref, key, request_hash):
        ticket_contract, complete_contract = self._upload_contracts()
        part_size = 5 * 1024 * 1024
        suffix = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}[ref.mime]
        name = ref.sha256 + suffix
        args = {'file_name': name, 'file_size': len(ref.content),
                'sha1_hex': hashlib.sha1(ref.content).hexdigest(), 'part_size': part_size,
                'projectId': project_id}
        step = 'upload_' + ref.sha256
        cached = self._claim(task_id, step, {'revision': ref.revision_id, 'sha256': ref.sha256, 'project': project_id})
        if cached is not None:
            return cached
        self.a.bridge.check(task_id, self._owner, request_hash, key)
        ticket = self._call('upload_ticket', args)
        parts = ticket_contract.read(ticket, 'parts')
        remote_path = ticket_contract.read(ticket, 'path')
        upload_id = opaque(ticket_contract.read(ticket, 'uploadId'))
        if (not isinstance(remote_path, str) or not re.fullmatch(r'[A-Za-z0-9_./-]{1,2048}', remote_path)
                or '..' in remote_path.split('/') or not isinstance(parts, list)
                or len(parts) != math.ceil(len(ref.content) / part_size)):
            raise GenerationError('PROVIDER_PROTOCOL_ERROR')
        for index, part in enumerate(parts):
            if ticket_contract.leaf({'part': part}, 'partNumber') != index + 1:
                raise GenerationError('PROVIDER_PROTOCOL_ERROR')
            url = ticket_contract.leaf({'part': part}, 'partUrl')
            self._authorize_scopes(self.a.catalog.scopes('upload_ticket'))
            self.a.bridge.check(task_id, self._owner, request_hash, key)
            self.a.media.put(url, ref.content[index * part_size:(index + 1) * part_size])
        self.a.bridge.check(task_id, self._owner, request_hash, key)
        complete = self._call('upload_complete', {'path': remote_path, 'upload_id': upload_id})
        file_ref = opaque(complete_contract.read(complete, 'fileRef'))
        # Preserve known upload IDs before attachment; do not persist signed upload URLs.
        with self.a.journal.edit(self._owner, task_id) as state:
            state['steps'][step]['fileRef'] = file_ref
        self.a.bridge.check(task_id, self._owner, request_hash, key)
        attach = self._call('upload_media', {'name': name, 'idempotencyKey': key + ':' + ref.sha256[:32],
                            'projectId': project_id, 'fileRef': file_ref, 'mediaType': 'image'})
        if attach.get('projectId') != project_id:
            raise GenerationError('PROVIDER_RECEIPT_MISMATCH')
        if attach.get('status') != 'completed':
            raise GenerationError('UPLOAD_UNCONFIRMED')
        normalized = {'nodeId': opaque(attach.get('nodeId')), 'fileRef': file_ref,
                      'revisionId': ref.revision_id, 'sha256': ref.sha256}
        self._finish(task_id, step, normalized)
        return normalized

    def lookup(self, receipt, *, local_task_id=None):
        self._preflight_tools(['task_status'])
        receipt = safe_receipt(receipt)
        task_id = self.a.bridge.task_for_receipt(self._owner, receipt, **({'local_task_id':local_task_id} if local_task_id is not None else {}))
        record = self._record(task_id)
        if receipt.get('projectId') != self._project(record['spec']['projectId']):
            raise GenerationError('OWNERSHIP_MISMATCH')
        if not receipt.get('taskId'):
            if not receipt.get('nodeId') or self.a.reference_route is None:
                raise GenerationError('ORIGINAL_RECEIPT_REQUIRED', receipt=receipt)
            receipt = self.a.reference_route.recover_task(self, task_id, record, receipt)
        if receipt['taskId'].startswith('cop_'):
            raise GenerationError('PROVIDER_PROTOCOL_ERROR', receipt=receipt)
        contract = self.a.responses.require('task_status', self.a.policy, ('taskId', 'projectId', 'status'))
        body = self._call('task_status', {'project_id': receipt['projectId'], 'task_id': receipt['taskId']})
        if contract.read(body, 'taskId') != receipt['taskId'] or contract.read(body, 'projectId') != receipt['projectId']:
            raise GenerationError('PROVIDER_RECEIPT_MISMATCH', receipt=receipt)
        status = contract.states.get(contract.read(body, 'status'), 'unknown')
        if status not in {'queued', 'running', 'completed', 'failed', 'cancelled', 'not_found', 'unknown'}:
            raise GenerationError('PROVIDER_PROTOCOL_ERROR')
        new = dict(receipt)
        if 'nodeId' in contract.fields:
            node = contract.read(body, 'nodeId')
            if node is not None:
                new['nodeId'] = opaque(node)
        self._checkpoint(task_id, new)
        return {'status': status, 'providerReceipt': new}

    def download(self, receipt):
        current = self.lookup(receipt)
        receipt = current['providerReceipt']
        if current['status'] != 'completed' or not receipt.get('nodeId'):
            raise GenerationError('DELIVERY_UNCONFIRMED', receipt=receipt)
        task_id = self.a.bridge.task_for_receipt(self._owner, receipt)
        record = self._record(task_id)
        delivery_contract = self.a.responses.require('prepare_project_delivery', self.a.policy, DELIVERY_FIELDS)
        recovery_contract = self.a.responses.require('get_web_operation_status', self.a.policy, DELIVERY_FIELDS)
        self._preflight_tools(['prepare_project_delivery', 'get_web_operation_status'])
        if not self.a.policy.allow_external_writes:
            raise GenerationError('GENERATION_DISABLED')
        # The official description specifies one durable watermark operation per item.
        # One-item requests avoid inventing a batch-to-operation mapping.
        artifacts = []
        for index in range(record['prepared']['count']):
            args = {'items': [{'kind': 'media', 'nodeId': receipt['nodeId'], 'outputIndex': index}],
                    'idempotencyKey': 'delivery_' + task_id + '_' + str(index),
                    'projectId': receipt['projectId'], 'watermark': 'keep'}
            self.a.catalog.request('prepare_project_delivery', args)
            step = 'delivery_' + str(index)
            cached = self._claim(task_id, step, args)
            contract = delivery_contract if cached is None else recovery_contract
            if cached is None:
                body = self._call('prepare_project_delivery', args)
            else:
                body = self._call('get_web_operation_status', {'operationId': cached['operationId'],
                                                               'projectId': receipt['projectId']})
            operation = contract.read(body, 'operationId')
            if (not isinstance(operation, str) or not re.fullmatch('wop_[a-f0-9]{64}', operation)
                    or contract.read(body, 'projectId') != receipt['projectId']
                    or cached is not None and operation != cached['operationId']):
                raise GenerationError('PROVIDER_RECEIPT_MISMATCH', receipt=receipt)
            if cached is None:
                self._finish(task_id, step, {'operationId': operation})
            if contract.states.get(contract.read(body, 'status')) != 'completed':
                raise GenerationError('DELIVERY_UNCONFIRMED', receipt=receipt)
            files = contract.read(body, 'files')
            if not isinstance(files, list) or len(files) != 1:
                raise GenerationError('OUTPUT_INVALID')
            item = {'file': files[0]}
            if (contract.leaf(item, 'fileNodeId') != receipt['nodeId']
                    or contract.leaf(item, 'fileOutputIndex') != index):
                raise GenerationError('PROVIDER_RECEIPT_MISMATCH', receipt=receipt)
            url = contract.leaf(item, 'fileUrl')
            mime = contract.leaf(item, 'fileMime')
            checksum = contract.leaf(item, 'fileSha256') if 'fileSha256' in contract.fields else None
            self._authorize_scopes(self.a.catalog.scopes('prepare_project_delivery'))
            content = self.a.media.get(url, mime=mime, sha256=checksum,
                                      max_bytes=self.a.policy.max_image_bytes, max_pixels=self.a.policy.max_pixels)
            # Recheck even for injected transfers; a fake/buggy transport cannot bypass image QA.
            inspect_image(content, mime, sha256=checksum, max_bytes=self.a.policy.max_image_bytes,
                          max_pixels=self.a.policy.max_pixels)
            artifacts.append(DownloadArtifact(content=content, mime=mime, sha256=checksum))
        return artifacts
