"""SYNTHETIC protocol fixtures. None of these response paths are official evidence."""
import copy
import hashlib
import io
from pathlib import Path

from PIL import Image
from backend.generation import (GenerationAdapter, AuthorizedMCP, GenerationPolicy, ProjectBinding,
                                RecipeBinding, ResponseContract, ResponseContracts, ToolCatalog,
                                StoreGenerationJournal, TaskSubmissionBridge, VerifiedReference)
from backend.generation.reference_route import ReferenceNodeRoute
from backend.sessions import SessionService
from backend.storage import Store
from backend.tasks.adapters import StoreTaskRepository
from backend.generation.types import digest


def png():
    buffer = io.BytesIO()
    Image.new('RGB', (16, 16), (20, 80, 120)).save(buffer, 'PNG')
    return buffer.getvalue()


def contracts():
    def contract(name, fields, states=None):
        return ResponseContract(name, {'type': 'object'}, fields,
                                evidence='SYNTHETIC TEST ONLY, not official evidence',
                                synthetic=True, states=states or {})
    direct = lambda *names: {n: (n,) for n in names}
    deliver = {**direct('operationId', 'projectId', 'status', 'files'),
               **{k: ('file', v) for k, v in [('fileUrl', 'url'), ('fileMime', 'mime'),
                       ('fileNodeId', 'node'), ('fileOutputIndex', 'index'), ('fileSha256', 'sha256')]}}
    return ResponseContracts([
        contract('get_model', {'model': ('inputContract', 'model'),
                               'parameterSchemas': ('inputContract', 'parameterSchemas')}),
        contract('project_info', direct('projectId', 'spaceId', 'spaceKind')),
        contract('upload_ticket', {**direct('parts', 'path', 'uploadId'),
                                   'partUrl': ('part', 'url'), 'partNumber': ('part', 'number')}),
        contract('upload_complete', {'fileRef': ('fileRef',)}),
        contract('create_node', direct('projectId', 'nodeId')),
        contract('read_node', direct('projectId', 'nodeId', 'nodeType', 'model', 'params', 'prompt', 'inputs', 'revision', 'taskId', 'persisted', 'taskRequestKey')),
        contract('update_node', direct('projectId', 'nodeId', 'taskId')),
        contract('task_status', direct('projectId', 'taskId', 'nodeId', 'status'),
                 {s: s for s in ['queued', 'running', 'completed', 'failed', 'cancelled', 'not_found']}),
        contract('prepare_project_delivery', deliver, {'done': 'completed'}),
        contract('get_web_operation_status', deliver, {'done': 'completed'}),
    ])


class FakeMCP:
    def __init__(self, fixture):
        self.f = fixture
        self.calls, self.failures, self.overrides = [], {}, {}
        self.nodes, self.operations = {}, {}
        self.hook = None
        self.model_schema = {'inputContract': {'model': 'synthetic-image-v1',
            'parameterSchemas': {'count': {'type': 'integer', 'minimum': 1, 'maximum': 4},
                                 'aspect': {'enum': ['16:9', '1:1']},
                                 'settings': {'type': 'object'}, 'strength': {'type': 'number', 'minimum': 0, 'maximum': 1}}}}

    def __call__(self, name, args):
        self.calls.append((name, copy.deepcopy(args)))
        if self.hook:
            self.hook(name, args)
        if name in self.failures:
            raise self.failures[name]
        if name in self.overrides:
            result = self.overrides[name]
            return {'structuredContent': copy.deepcopy(result)}
        if name == 'search_models':
            result = {'catalogue': ['synthetic-image-v1']}
        elif name == 'get_model':
            result = self.model_schema
        elif name == 'project_info':
            result = {'projectId': 'remote_project', 'spaceId': self.f.owner['spaceId'], 'spaceKind': 'personal'}
        elif name == 'generation_submit':
            result = {'task_id': 'provider_task'}
        elif name == 'upload_ticket':
            parts = (args['file_size'] + args['part_size'] - 1) // args['part_size']
            result = {'path': 'files/synthetic.png', 'uploadId': 'upload_test',
                      'parts': [{'number': n + 1, 'url': 'https://media.invalid/upload?test-signature=private'} for n in range(parts)]}
        elif name == 'upload_complete':
            result = {'fileRef': 'fileref_test'}
        elif name == 'upload_media':
            result = {'projectId': 'remote_project', 'status': 'completed', 'nodeId': 'reference_node'}
        elif name == 'create_node':
            self.nodes['image_node'] = {'projectId': 'remote_project', 'nodeId': 'image_node',
                'nodeType': 'image', 'model': args['model'], 'prompt': args['prompt'],
                'params': args['params'], 'inputs': args['left'], 'revision': 'sha256-' + 'a' * 64, 'taskId': None, 'persisted': True}
            result = {'projectId': 'remote_project', 'nodeId': 'image_node'}
        elif name == 'read_node':
            result = self.nodes[args['node']]
        elif name == 'update_node':
            self.nodes[args['node']]['taskId'] = 'provider_task'
            self.nodes[args['node']]['taskRequestKey'] = args['idempotencyKey']
            result = {'projectId': 'remote_project', 'nodeId': args['node'], 'taskId': 'provider_task'}
        elif name == 'task_status':
            result = {'projectId': 'remote_project', 'taskId': 'provider_task', 'nodeId': 'image_node', 'status': 'completed'}
        elif name == 'prepare_project_delivery':
            index = args['items'][0]['outputIndex']
            op = 'wop_' + format(index + 1, '064x')
            result = {'operationId': op, 'projectId': 'remote_project', 'status': 'done', 'files': [
                {'url': 'https://media.invalid/image?test-signature=private', 'mime': 'image/png',
                 'node': 'image_node', 'index': index, 'sha256': hashlib.sha256(self.f.raw).hexdigest()}]}
            self.operations[op] = copy.deepcopy(result)
        elif name == 'get_web_operation_status':
            result = self.operations[args['operationId']]
        else:
            raise AssertionError('Unexpected tool: ' + name)
        return {'structuredContent': copy.deepcopy(result), 'isError': False}


class FakeMedia:
    def __init__(self, raw):
        self.raw, self.puts, self.gets = raw, [], []
    def preflight(self):
        pass
    def put(self, url, raw):
        self.puts.append((url, bytes(raw)))
    def get(self, url, **kwargs):
        self.gets.append(url)
        return self.raw


class Fixture:
    def __init__(self, root):
        self.root = Path(root)
        self.store = Store(self.root / 'data', encryption_key=b'G' * 32, release_root=self.root / 'release')
        self.ctx = SessionService(self.store, public_origin='https://test.invalid').create().context
        self.owner = {'tenantId': self.ctx.tenantId, 'provider': 'libtv', 'providerIssuer': 'https://official.invalid/',
                      'providerAccountId': 'synthetic_account', 'providerSubject': 'synthetic_subject',
                      'spaceId': 'synthetic_space', 'spaceKind': 'personal'}
        self.repository = StoreTaskRepository(self.store, selection_reader=lambda tx: {})
        self.journal = StoreGenerationJournal(self.store, self.ctx)
        self.bridge = TaskSubmissionBridge(self.repository, self.ctx)
        self.raw = png()
        self.media = FakeMedia(self.raw)
        self.transport = FakeMCP(self)
        self.scopes = frozenset({'libtv:account:read', 'libtv:project:read', 'libtv:project:write',
                                 'libtv:media:write', 'libtv:task:write', 'libtv:export:write'})
        self.auth_calls = []
        self.refs = {}
        class Reader:
            def read(reader, owner, snapshot):
                return self.refs[snapshot['revisionId']]
        self.references = Reader()
        self.adapter = GenerationAdapter(journal=self.journal, submission_bridge=self.bridge,
            project_resolver=lambda owner, project: ProjectBinding('remote_project', self.owner, 'synthetic', True),
            references=self.references, media_transfer=self.media,
            recipes={n: RecipeBinding('synthetic-image-v1', evidence='SYNTHETIC') for n in ['mj_style', 'image2_asset', 'nano_refine']},
            responses=contracts(), reference_route=ReferenceNodeRoute(),
            policy=GenerationPolicy(allow_external_writes=True, allow_synthetic_contracts=True))
        self.client = self.adapter.bind(ownership=self.owner, authorize=self.authorize)

    def authorize(self, scopes):
        self.auth_calls.append(scopes)
        return AuthorizedMCP(copy.deepcopy(self.owner), self.scopes, self.transport)

    def payload(self, recipe='mj_style', settings=None, with_reference=False):
        sources = []
        if with_reference:
            sha = hashlib.sha256(self.raw).hexdigest()
            self.refs['revision_one'] = VerifiedReference('revision_one', self.owner, self.raw, 'image/png', sha,
                                                         'asset' if recipe == 'nano_refine' else 'style', approved=True)
            sources = [{'revisionId': 'revision_one', 'sha256': sha, 'ownership': self.owner, 'review': 'approved', 'stale': False}]
        spec = {'projectId': 'local_project', 'entityId': 'local_entity', 'recipe': recipe, 'prompt': 'Synthetic test image',
                'sourceRevisionIds': [s['revisionId'] for s in sources], 'settings': settings or {}}
        return {**spec, 'ownership': copy.deepcopy(self.owner), 'localTaskId': 'task_synthetic',
                'requestHash': digest({'spec': spec, 'sources': sources}), 'sources': sources}

    def prepare(self, **kwargs):
        self.p = self.payload(**kwargs)
        self.prepared = self.client.prepare(self.p)
        self.spec = {k: self.p[k] for k in ['projectId', 'entityId', 'recipe', 'prompt', 'sourceRevisionIds', 'settings']}
        self.submission = {**self.prepared, 'spec': self.spec, 'sources': self.p['sources'],
                           'ownership': self.owner, 'localTaskId': self.p['localTaskId']}
        return self.prepared

    def confirm(self):
        task = {'id': self.p['localTaskId'], 'version': 1, 'ownership': copy.deepcopy(self.owner),
                **copy.deepcopy(self.spec), 'spec': copy.deepcopy(self.spec),
                'inputs': {'spec': self.spec, 'sources': self.p['sources']}, 'inputHash': self.p['requestHash'],
                'createdAt': '2026-01-01T00:00:00Z', 'status': 'submitting', 'submissionAttempted': True,
                'submissionKey': 'generation_' + self.p['localTaskId'], 'providerReceipt': self.prepared['providerReceipt']}
        with self.repository.transaction(self.ctx) as tx:
            tx.put_task(task, None)

    def submit(self):
        return self.client.submit(self.submission, 'generation_' + self.p['localTaskId'])

    def count(self, name):
        return sum(n == name for n, _ in self.transport.calls)

    def state(self):
        with self.journal.edit(self.owner, self.p['localTaskId']) as s:
            return copy.deepcopy(s)
