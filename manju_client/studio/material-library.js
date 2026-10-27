import * as T from 'three';

// Shared material palette: a scene keeps these surfaces when the camera changes.
export const MATERIAL_VERSION='scene-pbr-2';
const profiles={
 stone:{color:'#c0c5c0',roughness:.89,bump:.035},stoneAlt:{color:'#a4aca7',roughness:.94,bump:.043},stoneDark:{color:'#6d7975',roughness:.92,bump:.035},
 earth:{color:'#b7a88b',roughness:1,bump:.08},wood:{color:'#b6a087',roughness:.58,bump:.018},woodDark:{color:'#776858',roughness:.72,bump:.026},
 gold:{color:'#b49b6b',roughness:.34,metalness:.82,bump:.004},jade:{color:'#8daea1',roughness:.3,metalness:0,bump:.003},
 roof:{color:'#819495',roughness:.74,bump:.022},plaster:{color:'#f5eedf',roughness:.96,bump:.018},cream:{color:'#e8d5ac',roughness:.9,bump:.012},
 rock:{color:'#a7ada2',roughness:1,bump:.10},grass:{color:'#8a9564',roughness:1,bump:.028},moss:{color:'#657c4e',roughness:1,bump:.018},
 leaf:{color:'#4d6844',roughness:.9},leafLight:{color:'#6b7e4b',roughness:.86},leafDark:{color:'#304d35',roughness:.95},
 glass:{color:'#cad8d4',roughness:.18,metalness:0},mural:{color:'#ffffff',roughness:1},grandMural:{color:'#ffffff',roughness:1}
};
const textureCache=new Map(),loader=new T.TextureLoader();
function texture(name,color=true){const key=name+color;if(!textureCache.has(key))textureCache.set(key,loader.loadAsync(new URL('./textures/'+name+'.jpg',import.meta.url).href).then(t=>{t.colorSpace=color?T.SRGBColorSpace:T.NoColorSpace;t.wrapS=t.wrapT=T.RepeatWrapping;return t}));return textureCache.get(key)}
// Deterministic micro-roughness, not a painted shadow or view-dependent texture.
function roughnessMap(){const n=128,data=new Uint8Array(n*n*4);for(let y=0;y<n;y++)for(let x=0;x<n;x++){const v=Math.round(226+14*Math.sin(x*.39)*Math.cos(y*.47)+8*Math.sin(x*1.31+y*2.07));data.set([v,v,v,255],4*(y*n+x))}const map=new T.DataTexture(data,n,n,T.RGBAFormat);map.wrapS=map.wrapT=T.RepeatWrapping;map.minFilter=T.LinearMipmapLinearFilter;map.magFilter=T.LinearFilter;map.generateMipmaps=true;map.needsUpdate=true;return map}
const grain=roughnessMap();
export async function applySceneMaterials(mats,renderer){
 await Promise.all(Object.entries(mats).map(async([name,m])=>{
  const p=profiles[name]||{},tex=m.userData.texture;m.color.set(p.color||'#ffffff');m.roughness=p.roughness??.9;m.metalness=p.metalness??0;m.envMapIntensity=name==='gold'?.85:.28;
  if(tex){m.map=await texture(tex);m.map.anisotropy=Math.min(renderer?.capabilities.getMaxAnisotropy()||4,8);if(!tex.includes('mural')){m.bumpMap=await texture(tex+'-bump',false);m.bumpScale=p.bump??.02;m.roughnessMap=grain;}}
  if(name==='glass'){m.opacity=.19;m.transparent=true;m.depthWrite=false;}
  if(name.startsWith('leaf')){m.roughnessMap=grain;m.envMapIntensity=.12;}
  m.userData={...m.userData,materialVersion:MATERIAL_VERSION,surfaceProfile:name};m.needsUpdate=true;
 }));
 return Object.entries(mats).map(([name,m])=>({name,color:'#'+m.color.getHexString(),roughness:m.roughness,metalness:m.metalness,bumpScale:m.bumpScale,baseColorMap:!!m.map,roughnessMap:!!m.roughnessMap,bumpMap:!!m.bumpMap,version:MATERIAL_VERSION}));
}
