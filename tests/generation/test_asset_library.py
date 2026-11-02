import unittest
from backend.generation.asset_library import catalog,details,with_previews
from backend.generation.errors import GenerationError


class AssetLibrary(unittest.TestCase):
    def fixture(self):
        return {'projectId':'remote-project','scope':'personal','asset':{'assetId':'asset-synthetic',
            'name':'合成场景','assetVersion':'sha256-'+'a'*64,'items':[{'index':0,'type':'image',
            'mediaUrls':['https://libtv-res.liblib.art/fixture.png'],'contentWidth':32,'contentHeight':24}]}}

    def test_v2_asset_uses_nested_version_and_exact_persisted_image_urls(self):
        item=details(self.fixture())
        self.assertEqual(item['id'],'asset-synthetic');self.assertEqual(item['images'][0]['itemIndex'],0)
        self.assertEqual(item['version'],'sha256-'+'a'*64)

    def test_nonimage_protected_and_unknown_hosts_are_never_importable(self):
        for change in ({'type':'video'},{'mediaUrls':[]},{'mediaUrls':['https://private.invalid/secret.png']},
                       {'mediaUrls':['http://127.0.0.1:18884/private.png']}):
            body=self.fixture();body['asset']['items'][0].update(change)
            with self.assertRaises(GenerationError):details(body)

    def test_library_catalog_preserves_ids_and_escapes_in_frontend(self):
        result=catalog({'items':[{'assetId':'a','name':'<scene>','assetVersion':'sha256-'+'b'*64}]})
        self.assertEqual(result['items'][0]['id'],'a');self.assertEqual(result['items'][0]['name'],'<scene>')

    def test_thumbnail_is_raster_data_not_provider_url(self):
        import io
        from PIL import Image
        buffer=io.BytesIO();Image.new('RGB',(1024,768),'white').save(buffer,format='PNG')
        class Media:
            def get_image(self,url,**limits):
                assert limits=={'max_bytes':8*1024*1024,'max_pixels':40_000_000}
                return buffer.getvalue(),'image/png'
        item=with_previews(details(self.fixture()),Media())
        self.assertTrue(item['images'][0]['preview'].startswith('data:image/jpeg;base64,'))
        self.assertNotIn('url',item['images'][0])
