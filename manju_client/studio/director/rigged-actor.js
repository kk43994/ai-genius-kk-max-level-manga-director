import * as T from 'three';
import {GLTFLoader} from '../vendor/examples/jsm/loaders/GLTFLoader.js';
import {clone} from '../vendor/examples/jsm/utils/SkeletonUtils.js';
const cache=new Map(),loader=new GLTFLoader(),V=a=>new T.Vector3(...a),rad=T.MathUtils.degToRad,clamp=T.MathUtils.clamp;
export const DEFAULT_RIGS={ye:{bodyType:'male',heads:9},shi:{bodyType:'female',heads:7},feng:{bodyType:'male',heads:8}};
export const RIG_STORE='dashixiong:anime-rigs:v1';
export function rigPreferences(){try{return {...DEFAULT_RIGS,...JSON.parse(localStorage.getItem(RIG_STORE)||'{}')};}catch{return {...DEFAULT_RIGS};}}
export const JOINT_LIMITS={elbow:[.5,145],knee:[.5,148],wristTwist:[-75,75],wristFlex:[-65,65],wristSide:[-25,25],headYaw:[-65,65],headPitch:[-35,35],anklePitch:[-30,45],ankleRoll:[-18,18],toe:[0,40]};
export async function loadAnimeRig(bodyType='male',heads=8,color='#c7d0d9',height=1.8){
 if(!['male','female'].includes(bodyType)||![7,8,9].includes(+heads))throw Error('无效的白模规格');
 const key=`${bodyType}-${heads}h`,url=new URL(`../models/actors/anime-${key}.glb?v=joint2-final`,import.meta.url).href;
 if(!cache.has(key))cache.set(key,loader.loadAsync(url).catch(e=>{cache.delete(key);throw e;}));
 const source=await cache.get(key),model=clone(source.scene),root=new T.Group();root.name=`动漫白模 ${key}`;root.add(model);model.scale.multiplyScalar(height/1.8);
 const mat=new T.MeshStandardMaterial({color,roughness:.72,metalness:.02,side:T.DoubleSide});model.traverse(o=>{if(o.isMesh){o.material=mat;o.castShadow=true;o.receiveShadow=true;o.frustumCulled=false;}});
 const B={},rest=new Map();model.traverse(o=>{if(o.isBone){B[o.name]=o;rest.set(o,{p:o.position.clone(),q:o.quaternion.clone(),s:o.scale.clone()});}});
 const male=bodyType==='male',names=male?{hips:'Sacrum',spine:'Spine1',mid:'Spine2',chest:'Spine3',neck:'Spine3_002',head:'head',shoulder:s=>`Clavicle_${s}`,upperArm:s=>`Humerus_${s}`,forearm:s=>`LowerArm_${s}`,twist:s=>`LowerArm_${s}_001`,hand:s=>`hand001_${s}`,thigh:s=>`Femur_${s}`,shin:s=>`Tibia_${s}`,foot:s=>`Foot_${s}`,toe:s=>`Foot_${s}_001`}:{hips:'J_Bip_C_Hips',spine:'J_Bip_C_Spine',mid:'J_Bip_C_Chest',chest:'J_Bip_C_UpperChest',neck:'J_Bip_C_Neck',head:'J_Bip_C_Head',shoulder:s=>`J_Bip_${s}_Shoulder`,upperArm:s=>`J_Bip_${s}_UpperArm`,forearm:s=>`J_Bip_${s}_LowerArm`,twist:s=>`J_Roll_${s}_LowerArm`,hand:s=>`J_Bip_${s}_Hand`,thigh:s=>`J_Bip_${s}_UpperLeg`,shin:s=>`J_Bip_${s}_LowerLeg`,foot:s=>`J_Bip_${s}_Foot`,toe:s=>`J_Bip_${s}_ToeBase`};
 const bone=(n,s)=>B[typeof names[n]==='function'?names[n](s):names[n]];
 for(const n of ['hips','spine','mid','chest','neck','head'])if(!bone(n))throw Error(`骨骼缺失 ${key} ${n}`);
 for(const n of ['shoulder','upperArm','forearm','hand','thigh','shin','foot'])for(const s of ['L','R'])if(!bone(n,s))throw Error(`骨骼缺失 ${key} ${n} ${s}`);
 const world=o=>o.getWorldPosition(new T.Vector3()),worldQ=o=>o.getWorldQuaternion(new T.Quaternion());root.updateMatrixWorld(true);
 const restHip=root.worldToLocal(world(bone('hips'))).y,ankleHeight=root.worldToLocal(world(bone('foot','L'))).y,footQ={},palm={},fingerAxes=new Map(),fingers={};
 for(const s of ['L','R']){
  footQ[s]=worldQ(bone('foot',s));
  fingers[s]=male?[[2,3,4],[5,7,8],[9,10,11],[12,13,14],[15,16,17]].map(f=>f.map(n=>B[`hand${String(n).padStart(3,'0')}_${s}`])):['Thumb','Index','Middle','Ring','Little'].map(f=>[1,2,3].map(n=>B[`J_Bip_${s}_${f}${n}`]));
  if(fingers[s].flat().some(x=>!x))throw Error(`手指骨骼缺失 ${key} ${s}`);
  const hand=bone('hand',s),direction=world(fingers[s][2][0]).sub(world(hand)).normalize(),across=world(fingers[s][1][0]).sub(world(fingers[s][4][0])).normalize();let normal=across.clone().cross(direction).normalize();if(normal.y>0)normal.negate();const inv=worldQ(hand).invert();palm[s]={direction:direction.clone().applyQuaternion(inv),normal:normal.clone().applyQuaternion(inv)};
  for(const chain of fingers[s])for(let i=0;i<3;i++){const b=chain[i],dir=i<2?world(chain[i+1]).sub(world(b)).normalize():world(b).sub(world(chain[i-1])).normalize();const axis=dir.cross(normal).normalize().applyQuaternion(worldQ(b).invert());fingerAxes.set(b,axis);}
 }
 const secondary=[];
 if(!male)for(const side of ['L','R']){
  for(const [helper,source]of [['UpperLeg','LowerLeg'],['Shoulder','LowerArm'],['TopsUpperArm','LowerArm']]){const a=B[`J_Aim_${side}_${helper}`],b=B[`J_Bip_${side}_${source}`];secondary.push({kind:'aim',a,b,axis:world(b).sub(world(a)).normalize().applyQuaternion(worldQ(a).invert())});}
  for(const [helper,source,weight,axis]of [['UpperArm','UpperArm',.5,[1,0,0]],['Hand','Hand',1,[1,0,0]],['LowerArm','Hand',.5,[1,0,0]],['Elbow','LowerArm',.5,[0,1,0]]]){const a=B[`J_Roll_${side}_${helper}`],b=B[`J_Bip_${side}_${source}`];secondary.push({kind:'roll',a,b,weight,sourceAxis:V(axis).applyQuaternion(worldQ(b).invert()),helperAxis:V(axis).applyQuaternion(worldQ(a).invert())});}
 }
 function updateSecondary(){for(const c of secondary){if(c.kind==='aim'){const from=c.axis.clone().applyQuaternion(worldQ(c.a)),to=world(c.b).sub(world(c.a)).normalize();setWorldQ(c.a,new T.Quaternion().setFromUnitVectors(from,to).multiply(worldQ(c.a)));}else{const delta=rest.get(c.b).q.clone().invert().multiply(c.b.quaternion),axis=c.sourceAxis,dot=delta.x*axis.x+delta.y*axis.y+delta.z*axis.z;let angle=2*Math.atan2(dot,delta.w);if(angle>Math.PI)angle-=Math.PI*2;if(angle<-Math.PI)angle+=Math.PI*2;c.a.quaternion.copy(rest.get(c.a).q).multiply(new T.Quaternion().setFromAxisAngle(c.helperAxis,angle*c.weight));c.a.updateMatrixWorld(true);}}}
 const restWorld=new Map();rest.forEach((_,b)=>restWorld.set(b,worldQ(b)));
 const diagnostics={clamped:[],angles:{},targetErrors:{}};
 function reset(){rest.forEach((r,b)=>{b.position.copy(r.p);b.quaternion.copy(r.q);b.scale.copy(r.s);});root.updateMatrixWorld(true);}
 function setWorldQ(b,q){b.quaternion.copy(worldQ(b.parent).invert().multiply(q));b.updateMatrixWorld(true);}
 function rotateWorld(b,axis,angle){if(b&&Math.abs(angle)>.000001)setWorldQ(b,new T.Quaternion().setFromAxisAngle(axis.clone().normalize(),angle).multiply(worldQ(b)));}
 function aim(b,child,target){const from=world(child).sub(world(b)).normalize(),to=target.clone().sub(world(b)).normalize();if(to.lengthSq()<.01)return;setWorldQ(b,new T.Quaternion().setFromUnitVectors(from,to).multiply(worldQ(b)));}
 const targetWorld=p=>root.localToWorld(V(p));
 function ik(a,b,c,target,pole,kind,label){const A=world(a),B0=world(b),C0=world(c),l1=A.distanceTo(B0),l2=B0.distanceTo(C0),delta=target.clone().sub(A),requested=delta.length(),axis=requested>.00001?delta.normalize():C0.sub(A).normalize();const [minFlex,maxFlex]=JOINT_LIMITS[kind];
  const lengthAt=angle=>Math.sqrt(l1*l1+l2*l2+2*l1*l2*Math.cos(rad(angle)));const d=clamp(requested,lengthAt(maxFlex),lengthAt(minFlex));if(Math.abs(d-requested)>.002)diagnostics.clamped.push(label);
  const end=A.clone().addScaledVector(axis,d),x=(l1*l1-l2*l2+d*d)/(2*d),y=Math.sqrt(Math.max(0,l1*l1-x*x));const dir=pole.clone().addScaledVector(axis,-pole.dot(axis));if(dir.lengthSq()<.00001){dir.copy(V([0,0,1])).addScaledVector(axis,-axis.z);if(dir.lengthSq()<.00001)dir.copy(V([1,0,0])).addScaledVector(axis,-axis.x);}dir.normalize();const elbow=A.clone().addScaledVector(axis,x).addScaledVector(dir,y);aim(a,b,elbow);aim(b,c,end);diagnostics.angles[label]=T.MathUtils.radToDeg(Math.acos(clamp((d*d-l1*l1-l2*l2)/(2*l1*l2),-1,1)));diagnostics.targetErrors[label]=world(c).distanceTo(target);
 }
 function pose({hipY,hipX=0,hipZ=0,lean=0,hipTilt=0,hipRoll=0,hipYaw=0,chestYaw=0,chestRoll=0,breath=0,headYaw=0,headPitch=0,hands,feet,palmAim={},grip=.06,wrists={},ankles={},elbowPoles={},motion,handBlend={},grounded=false}={}){
  reset();diagnostics.clamped=[];diagnostics.angles={};diagnostics.targetErrors={};const rotation=worldQ(root),axisX=V([1,0,0]).applyQuaternion(rotation),axisY=V([0,1,0]).applyQuaternion(rotation),axisZ=V([0,0,1]).applyQuaternion(rotation),hip=bone('hips'),p=root.worldToLocal(world(hip));p.y=hipY??(restHip+(motion?.hip[1]||0)*height/(motion?.height||height));p.x+=hipX;p.z+=hipZ;hip.position.copy(hip.parent.worldToLocal(root.localToWorld(p)));root.updateMatrixWorld(true);
  if(motion){for(const n of ['hips','spine','mid','chest','neck','head','shoulderL','shoulderR']){const side=/[LR]$/.test(n)?n.slice(-1):undefined,key=side?n.slice(0,-1):n,b=bone(key,side);setWorldQ(b,rotation.clone().multiply(new T.Quaternion().fromArray(motion.q[n])).multiply(restWorld.get(b)));}}
  rotateWorld(hip,axisY,clamp(hipYaw,-.35,.35));rotateWorld(hip,axisX,clamp(hipTilt,-.25,.25));rotateWorld(hip,axisZ,clamp(hipRoll,-.18,.18));const bend=clamp(Math.atan2(lean,height*.25),-.35,.45);for(const [name,f] of [['spine',.25],['mid',.35],['chest',.4]])rotateWorld(bone(name),axisX,bend*f);
  rotateWorld(bone('mid'),axisY,chestYaw*.4);rotateWorld(bone('chest'),axisY,chestYaw*.6);rotateWorld(bone('chest'),axisZ,chestRoll);rotateWorld(bone('chest'),axisX,breath*.008);
  const yaw=clamp(headYaw,rad(-65),rad(65)),pitch=clamp(headPitch,rad(-35),rad(35));for(const [name,f] of [['neck',.4],['head',.6]]){rotateWorld(bone(name),axisY,yaw*f);rotateWorld(bone(name),axisX,pitch*f);}
  if(grounded&&feet){let down=0;for(const s of ['L','R']){if(!feet[s])continue;const a=bone('thigh',s),b=bone('shin',s),c=bone('foot',s),A=world(a),B0=world(b),C=world(c),len=(A.distanceTo(B0)+B0.distanceTo(C))*.985,localA=root.worldToLocal(A.clone()),f=feet[s],horizontal=Math.hypot(localA.x-f[0],localA.z-f[2]);down=Math.max(down,localA.y-f[1]-Math.sqrt(Math.max(.01,len*len-horizontal*horizontal)));}if(down>0){const v=root.worldToLocal(world(hip));v.y-=Math.min(down,height*.24);hip.position.copy(hip.parent.worldToLocal(root.localToWorld(v)));root.updateMatrixWorld(true);}}
  for(const s of ['L','R']){const sign=s==='L'?1:-1;let handTarget=hands?.[s]??[sign*height*.14,height*.44,height*.035],footTarget=feet?.[s]??[sign*height*.055,ankleHeight,0];
   let motionPole;
   if(motion){const a=bone('upperArm',s),b=bone('forearm',s),c=bone('hand',s),A=world(a),B0=world(b),C=world(c),d=motion.limbs['arm'+s],d1=V(d[0]).applyQuaternion(rotation),d2=V(d[1]).applyQuaternion(rotation),animated=root.worldToLocal(A.clone().addScaledVector(d1,A.distanceTo(B0)).addScaledVector(d2,B0.distanceTo(C))).toArray();motionPole=d[0];handTarget=V(animated).lerp(V(handTarget),hands?.[s]?(handBlend[s]??1):0).toArray();}
   // The clavicle contributes to a high reach before the humerus solves the remainder.
   const shoulder=bone('shoulder',s),upper=bone('upperArm',s),upperP=root.worldToLocal(world(upper)),elevation=clamp((handTarget[1]-upperP.y)/height,0,.3);if(elevation>0){const target=world(upper).add(V([sign*height*elevation*.025,height*elevation*.20,0]).applyQuaternion(rotation));aim(shoulder,upper,target);}
   ik(upper,bone('forearm',s),bone('hand',s),targetWorld(handTarget),V(elbowPoles[s]??motionPole??[sign*.45,-.6,-.65]).applyQuaternion(rotation),'elbow',`elbow${s}`);
   ik(bone('thigh',s),bone('shin',s),bone('foot',s),targetWorld(footTarget),axisZ.clone(),'knee',`knee${s}`);
   if(motion){const hand=bone('hand',s);setWorldQ(hand,rotation.clone().multiply(new T.Quaternion().fromArray(motion.q['hand'+s])).multiply(restWorld.get(hand)));}
   const w=wrists[s]||{},twist=rad(clamp(w.twist||0,...JOINT_LIMITS.wristTwist)),hand=bone('hand',s),fore=bone('forearm',s),axis=world(hand).sub(world(fore)).normalize();if(male&&bone('twist',s))rotateWorld(bone('twist',s),axis,twist*.55);rotateWorld(hand,axis,twist*(male?.45:1));
   const handQ=worldQ(hand),forward=palm[s].direction.clone().applyQuaternion(handQ),normal=palm[s].normal.clone().applyQuaternion(handQ),side=forward.clone().cross(normal).normalize();rotateWorld(hand,side,rad(clamp(w.flex||0,...JOINT_LIMITS.wristFlex)));rotateWorld(hand,normal,rad(clamp(w.side||0,...JOINT_LIMITS.wristSide)));
   const intent=palmAim[s];if(intent){
    // Two palm axes determine roll as well as finger direction; blend from the current pose.
    const basis=(direction,normal)=>{const z=direction.clone().normalize(),y=normal.clone().addScaledVector(z,-normal.dot(z)).normalize(),x=y.clone().cross(z).normalize();return new T.Quaternion().setFromRotationMatrix(new T.Matrix4().makeBasis(x,y,z));};
    const localBasis=basis(palm[s].direction,palm[s].normal),targetBasis=basis(V(intent.direction).applyQuaternion(rotation),V(intent.normal).applyQuaternion(rotation));
    const targetQ=targetBasis.multiply(localBasis.invert()),q=worldQ(hand).slerp(targetQ,clamp(intent.weight??1,0,1));setWorldQ(hand,q);
   }
   const handGrip=typeof grip==='number'?grip:grip[s]??.06;fingers[s].forEach((chain,f)=>chain.forEach((b,i)=>{const curl=clamp(typeof handGrip==='number'?handGrip:handGrip[['thumb','index','middle','ring','little'][f]]??.06,0,1);const deg=(f===0?[24,43,30]:[55,78,48])[i]*curl;b.quaternion.multiply(new T.Quaternion().setFromAxisAngle(fingerAxes.get(b),rad(deg)));b.updateMatrixWorld(true);}));
   const a=ankles[s]||{};setWorldQ(bone('foot',s),rotation.clone().multiply(footQ[s]));rotateWorld(bone('foot',s),axisX,rad(clamp(a.pitch||0,...JOINT_LIMITS.anklePitch)));rotateWorld(bone('foot',s),axisZ,rad(clamp(a.roll||0,...JOINT_LIMITS.ankleRoll)));rotateWorld(bone('toe',s),axisX,rad(clamp(a.toe||0,...JOINT_LIMITS.toe)));
  }
  updateSecondary();root.updateMatrixWorld(true);
 }
 const joints=()=>Object.fromEntries(['hips','spine','mid','chest','neck','head'].map(n=>[n,world(bone(n))]).concat(['L','R'].flatMap(s=>['shoulder','upperArm','forearm','hand','thigh','shin','foot','toe'].filter(n=>bone(n,s)).map(n=>[n+s,world(bone(n,s))]))));
 return {root,model,bodyType,heads,height,bones:B,restHip,ankleHeight,pose,reset,bone,fingers,joints,diagnostics,headPoint:new T.Vector3(),getHeadPoint(){return world(bone('head'));},setColor(c){mat.color.set(c);},dispose(){mat.dispose();},stats:{bones:rest.size,source:key,bindingVersion:2,fingerJoints:30}};
}
