"""Local LibTV image integration, based on observed public MCP responses.

Account IDs identify billing accounts, not canvas spaces. All writes retain the
original owner and idempotency arguments; unknown media receipts fail closed.
"""
import copy
import hashlib
import re

from backend.tasks.ports import DownloadArtifact
from .contracts import validate
from .errors import GenerationError
from .media import inspect_image
from .service import GenerationAdapter, BoundImageClient, RESERVED
from .types import ProjectBinding, digest, opaque, owner, same_owner, safe_receipt


def personal_account(body, ownership):
    user = body.get('user', {})
    accounts = body.get('accounts', {}).get('accounts', [])
    matches = [r for r in accounts if str(r.get('accountId')) == ownership['spaceId']]
    if (ownership['spaceKind'] != 'personal' or user.get('uuid') != ownership['providerSubject']
            or len(matches) != 1 or matches[0].get('accountType') != 1
            or matches[0].get('ownerUuid') != user.get('uuid')
            or body.get('activeAccountId') != matches[0].get('accountId')):
        raise GenerationError('OWNERSHIP_MISMATCH')
    return user


class PersonalProjects:
    def __init__(self, services, context):
        self.services, self.context = services, context

    def existing(self, client, local_project_id):
        return self.resolve(client,local_project_id,create=False)

    def resolve(self, client, local_project_id, *, create=True):
        ctx = self.context(client._owner)
        project = self.services.workflow.get_project(ctx, local_project_id)
        user = personal_account(client._call('account_user', {}), client._owner)
        key = 'gp_' + digest([client._owner['providerAccountId'], client._owner['spaceId'], local_project_id])
        store = self.services.storage
        with store.transaction(ctx) as tx:
            try:
                row = tx.get('generation.project_bindings', key)
            except Exception as exc:
                if getattr(exc, 'code', None) != 'NOT_FOUND': raise
                if not create: raise GenerationError('PROJECT_BINDING_REQUIRED') from None
                row = tx.create('generation.project_bindings', {
                    'ownership': copy.deepcopy(client._owner), 'localProjectId': local_project_id,
                    'createArguments': {'name': project['name'], 'teamId': 0, 'openInBrowser': False,
                                        'idempotencyKey': key},
                    'remoteProjectId': None, 'evidence': 'personal project intent persisted before creation'},
                    record_id=key, immutable_fields=('ownership', 'localProjectId', 'createArguments'))
        record = row['data']
        if not same_owner(record['ownership'], client._owner) or record['localProjectId'] != local_project_id:
            raise GenerationError('OWNERSHIP_MISMATCH')
        remote = record.get('remoteProjectId')
        if not remote:
            if not create: raise GenerationError('PROJECT_BINDING_REQUIRED')
            if not client.a.policy.allow_external_writes: raise GenerationError('PROJECT_BINDING_REQUIRED')
            # Exact persisted key recovers an interrupted idempotent creation.
            result = client._call('create_project', record['createArguments'])
            remote = opaque(result.get('projectId'))
            meta = result.get('project', {})
            if (result.get('teamId') != 0 or meta.get('uuid') != remote
                    or meta.get('ownerId') != user.get('id')
                    or meta.get('projectSpaceId') != result.get('spaceId')):
                raise GenerationError('OWNERSHIP_MISMATCH')
            with store.transaction(ctx) as tx:
                fresh = tx.get('generation.project_bindings', key)
                if fresh['data'].get('remoteProjectId') not in (None, remote):
                    raise GenerationError('OWNERSHIP_MISMATCH')
                tx.update('generation.project_bindings', key, {**fresh['data'], 'remoteProjectId': remote,
                    'canvasSpaceId': result['spaceId'], 'evidence': 'official create_project personal owner'},
                    expected_version=fresh['version'])
        body = client._call('project_info', {'project_id': remote})
        target = client._call('target_project', {'projectId': remote})
        meta = body.get('data', {}).get('projectMeta', {})
        if (body.get('projectId') != remote or meta.get('uuid') != remote or meta.get('ownerId') != user.get('id')
                or target.get('projectId') != remote or target.get('teamId') != 0
                or type(meta.get('projectSpaceId')) is not int or meta['projectSpaceId'] != target.get('spaceId')):
            raise GenerationError('OWNERSHIP_MISMATCH')
        return ProjectBinding(remote, client._owner, 'account_user + project_info owner + target_project canvas space', True)


class LiveGenerationAdapter(GenerationAdapter):
    def bind(self, *, ownership, authorize):
        if not callable(authorize): raise GenerationError('PROVIDER_AUTHORIZATION_REQUIRED')
        return LiveImageClient(self, owner(ownership), authorize)


class LiveImageClient(BoundImageClient):
    def _model(self, spec):
        binding = self.a.recipes.get(spec.get('recipe'))
        if not binding: raise GenerationError('MODEL_BINDING_REQUIRED')
        requested = spec.get('modelId', binding.model)
        contract = self.get_model(requested).get('inputContract', {})
        schema = contract.get('parameterSchemas', {}).get('generate')
        # get_model resolves an exact official display name or key. Historical
        # ID bindings retain their equality check; selected display names resolve
        # to the returned key and the full contract is pinned before submission.
        if (('modelId' not in spec and ' ' not in binding.model and contract.get('model') != binding.model)
                or contract.get('modality') != 'image' or not isinstance(schema, dict)):
            raise GenerationError('MODEL_CONTRACT_UNVERIFIED')
        model_key = opaque(contract.get('model'))
        settings = spec.get('settings', {})
        if not isinstance(settings, dict) or any(k in RESERVED for k in settings):
            raise GenerationError('INPUT_INVALID')
        params = copy.deepcopy(settings)
        params.setdefault('count', 1)
        validate(schema, params)
        count = params['count']
        if type(count) is not int or not 1 <= count <= self.a.policy.max_outputs:
            raise GenerationError('INPUT_INVALID')
        prompt = spec.get('prompt')
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 50000:
            raise GenerationError('INPUT_INVALID')
        return model_key, params, count, digest({'inputContract': contract, 'controls': dict(binding.controls),
                                                    'tool': self.a.catalog.fingerprint('generation_submit')})

    def _upload_contracts(self):
        for name in ('upload_ticket','upload_complete','upload_media'):
            self.a.catalog.tool(name)
        self.a.media.preflight()

    def _upload(self, task_id, project_id, ref, key, request_hash):
        part_size = 5 * 1024 * 1024
        suffix = {'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp'}[ref.mime]
        name = ref.sha256 + suffix
        step = 'upload_' + ref.sha256
        cached = self._claim(task_id, step, {'revision':ref.revision_id,'sha256':ref.sha256,'project':project_id})
        if cached is not None: return cached
        self.a.bridge.check(task_id, self._owner, request_hash, key)
        ticket = self._call('upload_ticket', {'file_name':name,'file_size':len(ref.content),
                    'sha1_hex':hashlib.sha1(ref.content).hexdigest(),'part_size':part_size,'projectId':project_id})
        self._observe(task_id, 'upload_ticket', ticket)
        parts, path, upload = ticket.get('parts'), ticket.get('path'), ticket.get('uploadId')
        if (not isinstance(parts,list) or len(parts) != (len(ref.content)+part_size-1)//part_size
                or not isinstance(path,str) or not re.fullmatch(r'[A-Za-z0-9_./-]{1,2048}',path)
                or '..' in path.split('/')): raise GenerationError('PROVIDER_PROTOCOL_ERROR')
        upload = opaque(upload)
        for index, part in enumerate(parts):
            if part.get('partNumber') != index+1 or part.get('method') != 'PUT':
                raise GenerationError('PROVIDER_PROTOCOL_ERROR')
            self.a.bridge.check(task_id, self._owner, request_hash, key)
            self._authorize_scopes({'libtv:media:write'})
            self.a.media.put(part.get('url'),ref.content[index*part_size:(index+1)*part_size])
        complete = self._call('upload_complete', {'path':path,'upload_id':upload})
        self._observe(task_id, 'upload_complete', complete)
        file_ref = complete.get('file_ref')
        # upload_complete returns a signed opaque handle longer than ordinary IDs.
        # It is passed only to the official attach tool, and never journaled/logged.
        if not isinstance(file_ref,str) or not re.fullmatch(r'[A-Za-z0-9._~:-]{1,16384}',file_ref):
            raise GenerationError('PROVIDER_PROTOCOL_ERROR')
        self.a.bridge.check(task_id, self._owner, request_hash, key)
        # The same reference can feed many generated assets. Canvas names must
        # distinguish the consuming task, while this task's retry stays stable.
        attach_name = 'ref_' + task_id + '_' + ref.sha256[:16]
        attach = self._call('upload_media', {'name':attach_name,'idempotencyKey':key+':'+ref.sha256[:32],
                         'projectId':project_id,'fileRef':file_ref,'mediaType':'image'})
        self._observe(task_id, 'upload_media', attach)
        if attach.get('projectId') != project_id: raise GenerationError('PROVIDER_RECEIPT_MISMATCH')
        if attach.get('status') != 'completed': raise GenerationError('UPLOAD_UNCONFIRMED')
        result = {'nodeId':opaque(attach.get('nodeId')),'revisionId':ref.revision_id,'sha256':ref.sha256}
        self._finish(task_id, step, result)
        return result

    def _write_readiness(self):
        # Input schemas are discovered before spending. Unexpected response
        # formats preserve the original receipt and stop; never invent success.
        self._preflight_tools(['generation_submit', 'task_status', 'prepare_project_delivery', 'get_web_operation_status'])
        self.a.media.preflight()
        personal_account(self._call('account_user', {}), self._owner)

    def _observe(self, local_task, name, body):
        def shape(value, key=''):
            if isinstance(value, dict): return {k: shape(v, k) for k, v in value.items()}
            if isinstance(value, list): return [shape(v, key) for v in value[:4]]
            if key in {'status', 'state', 'taskKind', 'kind', 'type', 'phase', 'delivery'} and isinstance(value, (str, int, bool)):
                return value if not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value) else 'str'
            return type(value).__name__
        with self.a.journal.edit(self._owner, local_task) as state:
            state.setdefault('observedResponseShapes', {})[name] = shape(body)

    def _upload_stopped_before_generation(self, local_task):
        # Every charged call is preceded by a durable generation claim. Only a
        # journal consisting entirely of unfinished uploads proves no paid run.
        with self.a.journal.edit(self._owner, local_task) as state:
            steps = copy.deepcopy(state.get('steps', {}))
            if state.get('originalReferenceRun'):
                return False
        return bool(steps and all(re.fullmatch(r'upload_[a-f0-9]{64}', name) for name in steps)
                    and all(row.get('attempted') is True for row in steps.values())
                    and any(not row.get('done') for row in steps.values()))

    def lookup(self, receipt, *, local_task_id=None):
        receipt = safe_receipt(receipt)
        local_task = self.a.bridge.task_for_receipt(self._owner, receipt, **({'local_task_id':local_task_id} if local_task_id is not None else {}))
        record = self._record(local_task)
        if receipt.get('projectId') != self._project(record['spec']['projectId']):
            raise GenerationError('OWNERSHIP_MISMATCH')
        if not receipt.get('taskId'):
            if not receipt.get('nodeId') and self._upload_stopped_before_generation(local_task):
                return {'status':'failed', 'providerReceipt':receipt,
                        'failureStage':'reference_upload', 'generationSubmitted':False}
            if not receipt.get('nodeId') or self.a.reference_route is None:
                raise GenerationError('ORIGINAL_RECEIPT_REQUIRED', receipt=receipt)
            receipt = self.a.reference_route.recover_task(self, local_task, record, receipt)
        body = self._call('task_status', {'project_id': receipt['projectId'], 'task_id': receipt['taskId']})
        self._observe(local_task, 'task_status', body)
        # Current Task SOT omits owner. Live personal-account/project ownership
        # was checked above; the exact task -> node -> resources binding is
        # checked below. Never accept a conflicting owner when one is supplied.
        if (body.get('schema_version') != 1 or body.get('task_id') != receipt['taskId']
                or ('owner' in body and (not isinstance(body['owner'], dict)
                    or body['owner'].get('user_uuid') != self._owner['providerSubject']))):
            raise GenerationError('PROVIDER_RECEIPT_MISMATCH', receipt=receipt)
        if body.get('outcome') in ('FAILED', 'CANCELLED', 'CANCELED'):
            return {'status': 'failed' if body['outcome'] == 'FAILED' else 'cancelled',
                    'providerReceipt': receipt}
        if body.get('readiness') != 'TERMINAL_READY' or body.get('outcome') != 'SUCCEEDED':
            raise GenerationError('DELIVERY_UNCONFIRMED', receipt=receipt)
        if body.get('result_kind') != 'media':
            raise GenerationError('PROVIDER_RECEIPT_MISMATCH', receipt=receipt)
        artifacts = body.get('artifacts', [])
        if (not isinstance(artifacts, list) or len(artifacts) != record['prepared']['count']
                or any(not isinstance(a, dict) or a.get('kind') != 'image' for a in artifacts)
                or len({a.get('resource_id') for a in artifacts}) != len(artifacts)):
            raise GenerationError('OUTPUT_INVALID', receipt=receipt)
        nodes = {a.get('node_key') for a in artifacts}
        if len(nodes) != 1: raise GenerationError('PROVIDER_RECEIPT_MISMATCH', receipt=receipt)
        node_id = opaque(nodes.pop())
        if receipt.get('nodeId') not in (None, node_id):
            raise GenerationError('PROVIDER_RECEIPT_MISMATCH', receipt=receipt)
        node = self._call('read_node', {'projectId':receipt['projectId'], 'node':node_id})
        self._observe(local_task, 'completed_read_node', node)
        data = node.get('node', {}).get('data', {})
        resources = [a['resource_id'] for a in artifacts]
        if (node.get('projectId') != receipt['projectId'] or node.get('nodeId') != node_id
                or node.get('node', {}).get('id') != node_id
                or node.get('node', {}).get('type') != 'image'
                or data.get('taskInfo', {}).get('taskId') != receipt['taskId']
                or data.get('resourceIds') != resources):
            raise GenerationError('PROVIDER_RECEIPT_MISMATCH', receipt=receipt)
        receipt = self._checkpoint(local_task, {**receipt, 'nodeId':node_id})
        return {'status':'completed', 'providerReceipt':receipt}

    def download(self, receipt):
        current = self.lookup(receipt)
        receipt = current['providerReceipt']
        if current['status'] != 'completed' or not receipt.get('nodeId'):
            raise GenerationError('DELIVERY_UNCONFIRMED', receipt=receipt)
        local_task = self.a.bridge.task_for_receipt(self._owner, receipt)
        record = self._record(local_task)
        if not self.a.policy.allow_external_writes: raise GenerationError('GENERATION_DISABLED')
        artifacts = []
        for index in range(record['prepared']['count']):
            args = {'items':[{'kind':'media','nodeId':receipt['nodeId'],'outputIndex':index}],
                    'idempotencyKey':'delivery_'+local_task+'_'+str(index),
                    'projectId':receipt['projectId'], 'watermark':'keep'}
            step = 'delivery_'+str(index)
            cached = self._claim(local_task, step, args)
            if cached is None:
                body = self._call('prepare_project_delivery', args)
                self._observe(local_task, 'prepare_project_delivery', body)
                if (body.get('projectId') != receipt['projectId'] or body.get('status') != 'ready'
                        or body.get('fileCount') != 1 or len(body.get('files', [])) != 1):
                    raise GenerationError('DELIVERY_UNCONFIRMED', receipt=receipt)
                file = body['files'][0]
                operations = body.get('operationIds', [])
                op = file.get('derivation', {}).get('operationId')
                if (file.get('nodeId') != receipt['nodeId'] or file.get('outputIndex') != index
                        or not isinstance(op, str) or not re.fullmatch(r'wop_[a-f0-9]{64}', op)
                        or operations != [op] or not isinstance(file.get('sourceIdentity'), str)):
                    raise GenerationError('PROVIDER_RECEIPT_MISMATCH', receipt=receipt)
                cached = {'operationId':op, 'sourceHash':digest(file['sourceIdentity']),
                          'nodeId':receipt['nodeId'], 'outputIndex':index, 'mime':file['mime']}
                self._finish(local_task, step, cached)
            else:
                body = self._call('get_web_operation_status', {'operationId':cached['operationId'],
                                                               'projectId':receipt['projectId']})
                if (body.get('projectId') != receipt['projectId'] or body.get('operationId') != cached['operationId']
                        or body.get('status') != 'completed' or body.get('operation') != 'prepare_delivery_item'):
                    raise GenerationError('DELIVERY_UNCONFIRMED', receipt=receipt)
                file = body.get('result', {})
                if digest(file.get('sourceIdentity')) != cached['sourceHash'] or file.get('mime') != cached['mime']:
                    raise GenerationError('PROVIDER_RECEIPT_MISMATCH', receipt=receipt)
            raw = self.a.media.get(file.get('url'), mime=cached['mime'], max_bytes=self.a.policy.max_image_bytes,
                                   max_pixels=self.a.policy.max_pixels)
            checksum, _ = inspect_image(raw, cached['mime'], max_bytes=self.a.policy.max_image_bytes,
                                        max_pixels=self.a.policy.max_pixels)
            artifacts.append(DownloadArtifact(content=raw, mime=cached['mime'], sha256=checksum))
        return artifacts
