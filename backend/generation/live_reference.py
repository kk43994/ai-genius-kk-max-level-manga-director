"""Reference edges verified through actual create_node/read_project responses."""
import copy
import re

from .errors import GenerationError
from .types import opaque, digest
from .project_coordination import project_mutation


class LiveReferenceRoute:
    tools = ('create_node', 'read_project', 'update_node')

    def preflight(self, catalog, responses, policy):
        for name in self.tools: catalog.tool(name)

    def _snapshot(self, client, receipt, record, inputs):
        body = client._call('read_project', {'projectId':receipt['projectId'], 'view':'nodes'})
        nodes = [n for n in body.get('nodes', []) if n.get('id') == receipt['nodeId']]
        if body.get('projectId') != receipt['projectId'] or len(nodes) != 1 or nodes[0].get('type') != 'image':
            raise GenerationError('PROVIDER_RECEIPT_MISMATCH', receipt=receipt)
        data = nodes[0].get('data', {})
        params = data.get('params', {})
        if (params.get('model') != record['prepared']['modelKey'] or params.get('prompt') != record['spec']['prompt']
                or data.get('taskInfo', {}).get('taskId')):
            raise GenerationError('SOURCE_CHANGED', receipt=receipt)
        # The server stores creative controls in nested settings. Validate only
        # requested fields, never copy server-owned media lists back into params.
        for key, value in record['params'].items():
            current = params.get(key, params.get('settings', {}).get(key, params.get('advancedSettings', {}).get(key)))
            if current != value: raise GenerationError('SOURCE_CHANGED', receipt=receipt)
        incoming = [e.get('source') for e in body.get('edges', []) if e.get('target') == receipt['nodeId']]
        images = [r.get('nodeId') for r in params.get('imageList', [])]
        if sorted(incoming) != sorted(inputs) or images != inputs:
            raise GenerationError('SOURCE_CHANGED', receipt=receipt)
        revision = body.get('revision', {}).get('token')
        if not isinstance(revision, str) or not re.fullmatch(r'sha256-[a-f0-9]{64}', revision):
            raise GenerationError('PROVIDER_PROTOCOL_ERROR', receipt=receipt)
        return revision

    def _accepted(self, client, local_task, receipt, body):
        client._observe(local_task, 'update_node_generation', body)
        # Documented top-level task_id must be a media receipt. A cop_ canvas
        # operation is never promoted to a generated image.
        tid = body.get('task_id')
        if (not isinstance(tid, str) or tid.startswith('cop_')
                or body.get('projectId', receipt['projectId']) != receipt['projectId']):
            raise GenerationError('SUBMISSION_UNKNOWN', receipt=receipt)
        receipt = client._checkpoint(local_task, {**receipt, 'taskId':opaque(tid)})
        result = {'status':'queued', 'providerReceipt':receipt}
        client._finish(local_task, 'generation', result)
        return result

    def submit(self, client, local_task, record, uploaded, key):
        project = record['prepared']['providerReceipt']['projectId']
        # Resolve stable local reference IDs to the exact uploaded official nodes.
        # Never guess Image/Mixed indices from the prompt text.
        record = copy.deepcopy(record)
        nodes = {r['revisionId']:r['nodeId'] for r in uploaded}
        def mention(match):
            node = nodes.get(match.group(1))
            if not node: raise GenerationError('SOURCE_CHANGED')
            return '{{Node '+node+'}}'
        if record['spec']['recipe'] == 'storyboard_image':
            record['spec']['prompt'] = re.sub(r'\{\{reference:([A-Za-z0-9_-]+)\}\}', mention, record['spec']['prompt'])
        args = {'name':record['spec']['recipe']+' · '+local_task[-8:], 'nodeType':'image',
                'idempotencyKey':key+':node', 'projectId':project, 'model':record['prepared']['modelKey'],
                'prompt':record['spec']['prompt'], 'params':record['params'],
                'left':[r['nodeId'] for r in uploaded], 'run':False}
        client.a.catalog.request('create_node', args)
        cached = client._claim(local_task, 'reference_node', args)
        if cached is None:
            client.a.bridge.check(local_task, client._owner, record['prepared']['requestHash'], key)
            body = client._call('create_node', args)
            client._observe(local_task, 'create_reference_node', body)
            node = body.get('plan', {}).get('nodeId')
            if (body.get('projectId') != project or body.get('status') != 'completed'
                    or body.get('operationResult', {}).get('subjectNodeId') != node):
                raise GenerationError('PROVIDER_RECEIPT_MISMATCH')
            cached = {'projectId':project, 'nodeId':opaque(node)}
            client._checkpoint(local_task, cached)
            client._finish(local_task, 'reference_node', cached)
        receipt = client._checkpoint(local_task, cached)
        # Revalidate references and billing owner before reading the exact graph
        # revision used for the charged mutation.
        client._sources(record['sources'],record['spec']['sourceRevisionIds'],record['spec']['recipe'])
        if client._project(record['spec']['projectId']) != project:
            raise GenerationError('OWNERSHIP_MISMATCH', receipt=receipt)
        with project_mutation(client._owner, project):
            revision = self._snapshot(client, receipt, record, args['left'])
            run = {'node':receipt['nodeId'], 'projectId':project, 'idempotencyKey':key,
                   'model':args['model'], 'prompt':args['prompt'], 'params':args['params'],
                   'leftEnsure':args['left'], 'expectedRevision':revision, 'run':True}
            client.a.catalog.request('update_node', run)
            with client.a.journal.edit(client._owner, local_task) as state:
                state['originalReferenceRun'] = copy.deepcopy(run)
            done = client._claim(local_task, 'generation', run)
            if done is not None: return done
            client.a.bridge.check(local_task, client._owner, record['prepared']['requestHash'], key)
            try:
                return self._accepted(client, local_task, receipt, client._call('update_node', run))
            except GenerationError as exc:
                if exc.code == 'PROVIDER_SNAPSHOT_REVISION_MISMATCH':
                    self._prove_rejection(client, local_task, receipt, run)
                if exc.provider_receipt is None: exc.provider_receipt = receipt
                raise

    def recover_task(self, client, local_task, record, receipt):
        # Official update_node documents same-arguments/same-key recovery. Never
        # reconstruct a run from the node's current prompt or create a new key.
        with client.a.journal.edit(client._owner, local_task) as state:
            original = copy.deepcopy(state.get('originalReferenceRun'))
            attempt = copy.deepcopy(state['steps'].get('generation'))
        if (not original or not attempt or not attempt.get('attempted') or attempt.get('hash') != digest(original)
                or original.get('node') != receipt.get('nodeId') or original.get('projectId') != receipt.get('projectId')):
            raise GenerationError('ORIGINAL_RECEIPT_REQUIRED', receipt=receipt)
        if not client.a.policy.allow_external_writes: raise GenerationError('GENERATION_DISABLED')
        with project_mutation(client._owner, receipt['projectId']):
            try:
                return self._accepted(client, local_task, receipt, client._call('update_node', original))['providerReceipt']
            except GenerationError as exc:
                if exc.code == 'PROVIDER_SNAPSHOT_REVISION_MISMATCH':
                    self._prove_rejection(client, local_task, receipt, original)
                raise

    def _prove_rejection(self, client, local_task, receipt, original):
        # Only an exact rejection of the immutable original call reaches here.
        # Fresh graph evidence must still show that same node, prompt, model,
        # parameters and references, with no task. Never change/replay its key.
        record = {'prepared':{'modelKey':original['model']},
                  'spec':{'prompt':original['prompt']}, 'params':original['params']}
        revision = self._snapshot(client, receipt, record, original['leftEnsure'])
        with client.a.journal.edit(client._owner, local_task) as state:
            state['generationRejection'] = {'code':'SNAPSHOT_REVISION_MISMATCH',
                'originalHash':digest(original), 'verifiedRevision':revision, 'generationSubmitted':False}
        raise GenerationError('REFERENCE_PREFLIGHT_REJECTED', receipt=receipt)
