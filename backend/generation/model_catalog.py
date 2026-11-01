"""Read-only image model discovery. Names never imply an upstream model ID."""
import copy
import logging
import re

from .errors import GenerationError
from .service import RESERVED
from .types import digest, opaque

DEFAULT_MODEL = 'Lib Image 2.5 Pro'


def model_rows(body):
    """Accept explicitly labelled model records, never manufacture model keys."""
    rows = []
    def visit(value):
        if isinstance(value, list):
            for item in value: visit(item)
        elif isinstance(value, dict):
            identity = value.get('modelId') or value.get('modelKey')
            name = value.get('displayName') or value.get('name') or value.get('modelName')
            modality = value.get('nodeType', value.get('modality', 'image'))
            if isinstance(identity, str) and isinstance(name, str) and modality == 'image' and ('nodeTypes' not in value or 'image' in value['nodeTypes']):
                rows.append({'id': opaque(identity), 'name': name[:200]})
            else:
                for key in ('matches', 'models', 'items', 'data', 'results', 'groups'):
                    if key in value: visit(value[key])
    visit(body)
    unique = {r['id']: r for r in rows}
    if not unique:
        def shape(v, depth=0):
            if depth > 4: return type(v).__name__
            if isinstance(v, dict): return {k: shape(x, depth+1) for k,x in v.items()}
            if isinstance(v, list): return [shape(x, depth+1) for x in v[:1]]
            return type(v).__name__
        logging.getLogger(__name__).error('Image model catalog response shape: %s', shape(body))
        raise GenerationError('MODEL_CONTRACT_UNVERIFIED')
    return {'items': list(unique.values()), 'defaultModel': DEFAULT_MODEL, 'source': 'LibTV live search_models'}


def model_contract(body):
    contract = body.get('inputContract', {})
    schema = contract.get('parameterSchemas', {}).get('generate')
    if contract.get('modality') != 'image' or not isinstance(schema, dict):
        raise GenerationError('MODEL_CONTRACT_UNVERIFIED')
    model = opaque(contract.get('model'))
    # Expose only creative controls; transport and reference edges stay server-owned.
    public = copy.deepcopy(schema)
    public['properties'] = {k: v for k, v in public.get('properties', {}).items()
                            if k not in RESERVED and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,79}', k)}
    public['required'] = [k for k in public.get('required', []) if k in public['properties']]
    return {'id': model, 'schema': public, 'schemaHash': digest(contract), 'verified': True}


def read_catalog(service, ctx, model=None):
    selected = service._selection(ctx)
    owner = service._owner(ctx, selected)
    client = service._client(ctx, owner)
    result = model_contract(client.get_model(model)) if model else model_rows(client.list_models())
    return {**result, 'selectionRevision': selected['revision']}
