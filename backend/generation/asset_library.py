"""Read the user's official image library through the same bound account."""
import logging
import base64
import io
from urllib.parse import urlsplit
from .errors import GenerationError


def response_shape(value,depth=0):
    if depth>6:return type(value).__name__
    if isinstance(value,dict):return {k:response_shape(v,depth+1) for k,v in value.items()}
    if isinstance(value,list):return [response_shape(v,depth+1) for v in value[:1]]
    return type(value).__name__


def catalog(body):
    rows=[]
    def visit(v):
        if isinstance(v,list):
            for row in v:visit(row)
        elif isinstance(v,dict):
            identity=v.get('assetId') or v.get('uuid')
            name=v.get('name')
            if isinstance(identity,str) and isinstance(name,str):
                rows.append({'id':identity,'name':name[:200],'version':v.get('assetVersion',v.get('version'))})
            else:
                for key in ('assets','items','data','results','list'):
                    if key in v:visit(v[key])
    visit(body)
    if not rows:
        logging.getLogger(__name__).error('Asset library catalog response shape: %s',response_shape(body))
    return {'items':rows,'page':body.get('page',1),'hasMore':bool(body.get('hasMore',False))}


def details(body):
    # The public contract advertises V2 image items. Unknown variants remain
    # unavailable until their exact persisted-image shape has been verified.
    asset=body.get('asset',body)
    items=asset.get('items',[]) if isinstance(asset,dict) else []
    images=[]
    hosts=set()
    for i,item in enumerate(items):
        if not isinstance(item,dict):continue
        if item.get('type')!='image':continue
        for ui,url in enumerate(item.get('mediaUrls',[])):
            if not isinstance(url,str):continue
            parsed=urlsplit(url);hosts.add(parsed.hostname)
            if (parsed.scheme=='https' and not parsed.username and not parsed.password
                    and parsed.hostname in {'libtv-res.liblib.art','libtv-resource-prod.oss-accelerate.aliyuncs.com'}):
                images.append({'index':len(images),'itemIndex':item.get('index',i),'outputIndex':ui,'url':url})
    version=asset.get('assetVersion') if isinstance(asset,dict) else None
    if not images or not isinstance(version,str):
        logging.getLogger(__name__).error('Asset library detail response shape: %s',response_shape(body))
        logging.getLogger(__name__).error('Asset library image hosts: %s',sorted(str(h) for h in hosts))
        if isinstance(version,str) and isinstance(items,list):raise GenerationError('LIBRARY_IMAGE_UNAVAILABLE')
        raise GenerationError('PROVIDER_RESPONSE_CONTRACT_REQUIRED',missing='get_asset.image_items')
    return {'id':asset.get('assetId') or asset.get('uuid'),'name':str(asset.get('name','素材'))[:200],
            'version':version,'images':images}


def with_previews(item,media):
    """Render verified raster thumbnails under the app's existing self/data CSP."""
    from PIL import Image
    for image in item['images'][:20]:
        try:
            raw,_=media.get_image(image['url'],max_bytes=8*1024*1024,max_pixels=40_000_000)
            with Image.open(io.BytesIO(raw)) as im:
                im.thumbnail((720,720));out=io.BytesIO();im.convert('RGB').save(out,format='JPEG',quality=85)
            image['preview']='data:image/jpeg;base64,'+base64.b64encode(out.getvalue()).decode()
        except GenerationError as exc:
            image['previewError']=exc.message
    # Original provider URLs remain server-side; import re-reads the pinned item.
    for image in item['images']:image.pop('url',None)
    return item
