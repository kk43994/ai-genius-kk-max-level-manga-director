import unittest
from types import SimpleNamespace
from backend.generation.model_catalog import model_rows, model_contract
from backend.generation.live import LiveImageClient
from backend.generation.errors import GenerationError
from backend.generation.types import RecipeBinding, GenerationPolicy
from backend.generation.contracts import ToolCatalog
from backend.tasks.model import validate_spec

OWNER={'tenantId':'t','provider':'libtv','providerAccountId':'a','providerIssuer':'https://mcp.liblib.tv/',
       'providerSubject':'u','spaceId':'s','spaceKind':'personal'}

class Models(unittest.TestCase):
    def test_catalog_only_uses_returned_ids_and_filters_modalities(self):
        rows=model_rows({'nodeType':'image','matches':[{'modelId':'pro-live','displayName':'Lib Image 2.5 Pro'},
            {'modelKey':'old-live','name':'Lib Image'},{'modelId':'video','name':'video','nodeType':'video'}]})
        self.assertEqual([r['id'] for r in rows['items']],['pro-live','old-live'])
        with self.assertRaises(GenerationError): model_rows({'models':[{'name':'Invented'}]})
    def test_contract_and_selected_model_pin_the_resolved_id(self):
        a=SimpleNamespace(recipes={'image25_asset':RecipeBinding('legacy')},policy=GenerationPolicy(),catalog=ToolCatalog.bundled())
        c=LiveImageClient(a,OWNER,None);seen=[]
        contract={'inputContract':{'model':'pro-live','modality':'image','parameterSchemas':{'generate':{'type':'object',
            'properties':{'count':{'enum':[1,2]},'style':{'enum':['raw']}},'additionalProperties':False}}}}
        def get(model): seen.append(model);return contract
        c.get_model=get
        spec={'projectId':'p','entityId':'e','recipe':'image25_asset','modelId':'Lib Image 2.5 Pro',
              'prompt':'synthetic','settings':{'count':2,'style':'raw'},'sourceRevisionIds':[]}
        self.assertEqual(validate_spec(spec)['modelId'],'Lib Image 2.5 Pro')
        self.assertEqual(c._model(spec)[0],'pro-live');self.assertEqual(seen,['Lib Image 2.5 Pro'])
        self.assertEqual(model_contract(contract)['id'],'pro-live')
        contract['inputContract']['modality']='video'
        with self.assertRaises(GenerationError): c._model(spec)
    def test_model_controls_cannot_carry_transport_or_credentials(self):
        spec={'projectId':'p','entityId':'e','recipe':'image25_style','prompt':'synthetic','settings':{'access_token':'secret'}}
        with self.assertRaises(Exception):validate_spec(spec)
