"""Official canvas reference route, enabled only with verified response mappings.

The bundled schemas prove these *inputs*. They do not prove response paths; no
production ResponseContract is shipped for create_node/read_node/update_node.
"""
import re

from .errors import GenerationError
from .types import opaque


class ReferenceNodeRoute:
    tools = ('create_node', 'read_node', 'update_node')

    def preflight(self, catalog, responses, policy):
        for name in self.tools:
            catalog.tool(name)
        responses.require('create_node', policy, ('projectId', 'nodeId'))
        responses.require('read_node', policy, ('projectId', 'nodeId', 'nodeType', 'model',
                          'prompt', 'params', 'inputs', 'revision', 'taskId', 'persisted'))
        responses.require('update_node', policy, ('projectId', 'nodeId', 'taskId'))

    def _read(self, client, receipt, record, inputs=None):
        contract = client.a.responses.require('read_node', client.a.policy)
        body = client._call('read_node', {'node': receipt['nodeId'], 'projectId': receipt['projectId']})
        expected = {'projectId': receipt['projectId'], 'nodeId': receipt['nodeId'], 'nodeType': 'image',
                    'model': record['prepared']['modelKey'], 'prompt': record['spec']['prompt'],
                    'params': record['params'], 'persisted': True}
        if inputs is not None:
            expected['inputs'] = inputs
        if any(contract.read(body, k) != value for k, value in expected.items()):
            raise GenerationError('PROVIDER_RECEIPT_MISMATCH', receipt=receipt)
        return contract, body

    def submit(self, client, local_task, record, uploaded, key):
        project = record['prepared']['providerReceipt']['projectId']
        args = {'name': 'asset_' + local_task, 'nodeType': 'image', 'idempotencyKey': key + ':node',
                'model': record['prepared']['modelKey'], 'projectId': project,
                'prompt': record['spec']['prompt'], 'params': record['params'],
                'left': [row['nodeId'] for row in uploaded], 'run': False}
        client.a.catalog.request('create_node', args)
        cached = client._claim(local_task, 'reference_node', args)
        if cached is None:
            client.a.bridge.check(local_task, client._owner, record['prepared']['requestHash'], key)
            body = client._call('create_node', args)
            contract = client.a.responses.require('create_node', client.a.policy)
            if contract.read(body, 'projectId') != project:
                raise GenerationError('PROVIDER_RECEIPT_MISMATCH')
            cached = {'projectId': project, 'nodeId': opaque(contract.read(body, 'nodeId'))}
            client._checkpoint(local_task, cached)
            client._finish(local_task, 'reference_node', cached)
        # This exact node ID reaches the task repository before the charged call.
        receipt = client._checkpoint(local_task, cached)
        with client.a.journal.edit(client._owner, local_task) as state:
            state['referenceInputs'] = args['left']
            state['referenceSubmissionKey'] = key
        contract, body = self._read(client, receipt, record, args['left'])
        if contract.read(body, 'taskId') is not None:
            # A supposedly unrun node already has a task: never trigger another one.
            raise GenerationError('SUBMISSION_UNKNOWN', receipt=receipt)
        revision = contract.read(body, 'revision')
        if not isinstance(revision, str) or not re.fullmatch('sha256-[a-f0-9]{64}', revision):
            raise GenerationError('PROVIDER_PROTOCOL_ERROR', receipt=receipt)
        run = {'node': receipt['nodeId'], 'projectId': project, 'idempotencyKey': key,
               'model': args['model'], 'prompt': args['prompt'], 'params': args['params'],
               'leftEnsure': args['left'], 'expectedRevision': revision, 'run': True}
        client.a.catalog.request('update_node', run)
        done = client._claim(local_task, 'generation', run)
        if done is not None:
            return done
        client.a.bridge.check(local_task, client._owner, record['prepared']['requestHash'], key)
        # Source review/bytes and model selection cannot change while uploads run.
        client._sources(record['sources'], record['spec']['sourceRevisionIds'], record['spec']['recipe'])
        current_model = client._model(record['spec'])
        expected = record['prepared']
        if (current_model != (expected['modelKey'], record['params'], expected['count'], expected['schemaHash'])
                or client._project(record['spec']['projectId']) != project):
            raise GenerationError('SOURCE_CHANGED', receipt=receipt)
        client.a.bridge.check(local_task, client._owner, record['prepared']['requestHash'], key)
        try:
            result = client._call('update_node', run)
            contract = client.a.responses.require('update_node', client.a.policy)
            if (contract.read(result, 'nodeId') != receipt['nodeId']
                    or contract.read(result, 'projectId') != project):
                raise GenerationError('PROVIDER_RECEIPT_MISMATCH')
            task_id = opaque(contract.read(result, 'taskId'))
            if task_id.startswith('cop_'):
                raise GenerationError('PROVIDER_PROTOCOL_ERROR')
            receipt = client._checkpoint(local_task, {**receipt, 'taskId': task_id})
            result = {'status': 'queued', 'providerReceipt': receipt}
            client._finish(local_task, 'generation', result)
            return result
        except GenerationError as exc:
            if exc.provider_receipt is None:
                exc.provider_receipt = receipt
            raise

    def recover_task(self, client, local_task, record, receipt):
        """Only read the persisted dedicated node after an ambiguous charged run."""
        with client.a.journal.edit(client._owner, local_task) as state:
            attempt = state['steps'].get('generation')
            inputs = state.get('referenceInputs')
            key = state.get('referenceSubmissionKey')
        if not attempt or not attempt.get('attempted') or not inputs or not key:
            raise GenerationError('ORIGINAL_RECEIPT_REQUIRED', receipt=receipt)
        contract, body = self._read(client, receipt, record, inputs)
        # The node might have been run manually after the ambiguous request.
        if contract.read(body, 'taskRequestKey') != key:
            raise GenerationError('SUBMISSION_UNKNOWN', receipt=receipt)
        remote_task = contract.read(body, 'taskId')
        if not remote_task:
            raise GenerationError('SUBMISSION_UNKNOWN', receipt=receipt)
        remote_task = opaque(remote_task)
        if remote_task.startswith('cop_'):
            raise GenerationError('SUBMISSION_UNKNOWN', receipt=receipt)
        return client._checkpoint(local_task, {**receipt, 'taskId': remote_task})
