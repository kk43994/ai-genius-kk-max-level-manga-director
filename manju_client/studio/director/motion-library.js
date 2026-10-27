import * as T from 'three';
let promise;
const lerp=(a,b,u)=>a.map((v,i)=>v+(b[i]-v)*u),quat=(a,b,u)=>new T.Quaternion().fromArray(a).slerp(new T.Quaternion().fromArray(b),u).toArray();
export function blendMotion(a,b,u){
 if(!a)return b;if(!b)return a;u=T.MathUtils.clamp(u,0,1);
 return {height:a.height,hip:lerp(a.hip,b.hip,u),q:Object.fromEntries(Object.keys(a.q).map(k=>[k,quat(a.q[k],b.q[k],u)])),limbs:Object.fromEntries(Object.keys(a.limbs).map(k=>[k,a.limbs[k].map((v,i)=>new T.Vector3(...lerp(v,b.limbs[k][i],u)).normalize().toArray())]))};
}
export async function loadMotionLibrary(){
 if(!promise)promise=fetch(new URL('../models/motions/quaternius-standard.json',import.meta.url)).then(r=>{if(!r.ok)throw Error('动作库未加载');return r.json()}).catch(e=>{promise=null;throw e});
 const data=await promise;
 return {names:Object.keys(data.clips),sample(name,t,{loop}={}){const clip=data.clips[name];if(!clip)throw Error('未知动作 '+name);const repeat=loop??clip.loop,time=repeat?((t%clip.duration)+clip.duration)%clip.duration:T.MathUtils.clamp(t,0,clip.duration),f=time/clip.duration*(clip.frames.length-1),i=Math.floor(f),a={...clip.frames[i],height:data.height},b={...clip.frames[Math.min(i+1,clip.frames.length-1)],height:data.height};return blendMotion(a,b,f-i)},duration:name=>data.clips[name].duration};
}
