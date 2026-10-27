"""Live project-space check through public project_info; no active-space fallback."""
from .errors import GenerationError
from .types import ProjectBinding, same_owner


class OfficialProjectResolver:
    def __init__(self, candidate_reader):
        # Internal repository callback, never a project ID supplied by the browser alone.
        self.candidates = candidate_reader

    def resolve(self, client, local_project_id):
        candidate = self.candidates(client._owner, local_project_id)
        if not isinstance(candidate, ProjectBinding) or not same_owner(candidate.ownership, client._owner):
            raise GenerationError('PROJECT_BINDING_REQUIRED')
        contract = client.a.responses.require('project_info', client.a.policy,
                                              ('projectId', 'spaceId', 'spaceKind'))
        body = client._call('project_info', {'project_id': candidate.project_id})
        expected = {'projectId': candidate.project_id, 'spaceId': client._owner['spaceId'],
                    'spaceKind': client._owner['spaceKind']}
        if any(contract.read(body, field) != value for field, value in expected.items()):
            raise GenerationError('OWNERSHIP_MISMATCH')
        return ProjectBinding(candidate.project_id, candidate.ownership, contract.evidence, verified=True)
