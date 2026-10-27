import * as T from 'three';
import {buildScene} from '../scenes.js';
import {Builder,materials,chair} from '../geometry.js';
import {clamp,smooth,mix,mix3,ACTORS} from './timeline.js';
import {blockingState} from './blocking.js';
import {performanceAt} from './motion-reference.js';
import {loadMotionLibrary} from './motion-library.js';
import {naturalStage} from './natural-performance.js';
import {loadAnimeRig,rigPreferences} from './rigged-actor.js';
const V=a=>new T.Vector3(...a),Y=new T.Vector3(0,1,0),Z=new T.Vector3(0,0,1);
const sphere=new T.SphereGeometry(1,20,14),cylinder=new T.CylinderGeometry(1,1,1,14),box=new T.BoxGeometry(1,1,1);
function mesh(geo,mat,parent){const m=new T.Mesh(geo,mat);m.castShadow=true;m.receiveShadow=true;parent.add(m);return m;}
function link(m,a,b,r1,r2=r1){const A=V(a),B=V(b),d=B.clone().sub(A);m.position.copy(A.add(B).multiplyScalar(.5));m.quaternion.setFromUnitVectors(Y,d.clone().normalize());m.scale.set(r1,d.length(),r2);}
function ellipsoid(parent,mat,p,s){const m=mesh(sphere,mat,parent);m.position.fromArray(p);m.scale.fromArray(s);return m;}
function twoBone(shoulder,hand,l1,l2,bend){const a=V(shoulder),c=V(hand),ac=c.clone().sub(a),dist=clamp(ac.length(),.001,l1+l2-.001),axis=ac.normalize();c.copy(a).addScaledVector(axis,dist);let x=(l1*l1-l2*l2+dist*dist)/(2*dist),h=Math.sqrt(Math.max(0,l1*l1-x*x));let b=V(bend);b.addScaledVector(axis,-b.dot(axis));if(b.length()<.001)b.set(0,0,1);b.normalize();return [a.toArray(),a.clone().addScaledVector(axis,x).addScaledVector(b,h).toArray(),c.toArray()];}
function importedActor(spec){
 const root=new T.Group();root.name=spec.name;root.userData.actorId=spec.id;
 const builder=new Builder(materials());builder.begin('预演座椅');chair(builder,0,0,0,spec.id==='shi'?.68:1.02);const seat=builder.done();seat.traverse(o=>{if(o.isMesh)o.material=new T.MeshStandardMaterial({color:'#787e76',roughness:.9});});
 const marker=new T.Mesh(new T.RingGeometry(.30,.32,48),new T.MeshBasicMaterial({color:spec.color,transparent:true,opacity:.7,side:T.DoubleSide}));marker.rotation.x=-Math.PI/2;
 const headPoint=new T.Vector3();let rig=null,version=0,last=null,motionLibrary=null;
 function pose(config,t,contact,natural=true){last=[config,t,contact,natural];const state=config.performance==='articulated-v3'?performanceAt(config,t):blockingState(config,t);const {h,child,elder,fear,withdraw,reach,standing,p,yaw,lean,hipY}=state;
  root.position.fromArray(p);root.rotation.y=yaw;root.updateMatrixWorld(true);seat.position.fromArray(config.p);seat.rotation.y=T.MathUtils.degToRad(config.yaw);seat.visible=!state.articulated||elder;marker.visible=false;
  if(!rig){headPoint.fromArray(state.head);return;}
  if(natural&&motionLibrary&&config.performance!=='articulated-v3'){const n=naturalStage(config,t,rig,motionLibrary,contact);root.position.fromArray(n.p);root.rotation.y=n.yaw;root.updateMatrixWorld(true);rig.pose(n.pose);headPoint.copy(rig.getHeadPoint()).add(new T.Vector3(0,h/rig.heads*.65,0));return;}
  const hands={},feet={},localContact=root.worldToLocal(V(contact)).toArray();
  for(const side of ['L','R']){const sign=side==='L'?1:-1;let hand=[sign*h*.14,hipY+.09,h*.23];const touching=(!child&&!elder&&side==='R')||(child&&side==='L');
   if(touching)hand=mix3(hand,localContact,reach*(1-withdraw));
   if(child&&fear>0)hand=mix3(hand,[sign*h*.16,hipY+h*.23,h*.24],fear);
   if(elder&&side==='R')hand=mix3(hand,[sign*h*.18,hipY+h*.24,h*.23],fear);
   hands[side]=hand;feet[side]=[sign*h*.07,rig.ankleHeight+.075,mix(h*.23,.015,standing)];
   if(state.articulated){const oldSide=side==='L'?'R':'L';hands[side]=root.worldToLocal(V(state.hands[oldSide])).toArray();feet[side]=root.worldToLocal(V(state.feet[oldSide])).toArray();feet[side][1]+=rig.ankleHeight+.075-.16;}
  }
  rig.pose({hipY:state.articulated&&!elder?rig.restHip+.075+state.hipOffset:hipY,lean,hands,feet,headYaw:state.headTurn||0,grip:state.articulated?(child?{L:.16+.46*fear,R:.12+.38*fear}:elder?{L:.10,R:.10+.15*fear}:{L:.12+.20*withdraw,R:.08}):.10,wrists:state.articulated&&child?{L:{flex:12*fear,twist:-12*fear},R:{flex:8*fear,twist:10*fear}}:{}});headPoint.copy(rig.getHeadPoint()).add(new T.Vector3(0,h/rig.heads*.65,0));
 }
 async function setRig(selection){const v=++version;const next=await loadAnimeRig(selection.bodyType,selection.heads,spec.color,spec.height);if(v!==version){next.dispose();return;}if(rig){root.remove(rig.root);rig.dispose();}rig=next;root.add(rig.root);root.userData.rig=rig.stats.source;if(last)pose(...last);}
 const ready=Promise.all([setRig(rigPreferences()[spec.id]),loadMotionLibrary().then(x=>{motionLibrary=x;if(last)pose(...last)})]);return {root,seat,marker,pose,headPoint,ready,setRig};
}

function visionSpace(){
 const root=new T.Group();root.name='体内异象 · 抽象占位';let seed=188;const rand=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};
 const points=[],colors=[];for(let i=0;i<1600;i++){const a=rand()*Math.PI*2,r=1.5+rand()*6,z=12-rand()*58;points.push(Math.cos(a)*r,Math.sin(a)*r+1,z);const c=new T.Color().setHSL(.10+rand()*.08,.45,.5+rand()*.4);colors.push(c.r,c.g,c.b);}
 const g=new T.BufferGeometry();g.setAttribute('position',new T.Float32BufferAttribute(points,3));g.setAttribute('color',new T.Float32BufferAttribute(colors,3));const dust=new T.Points(g,new T.PointsMaterial({size:.035,vertexColors:true,sizeAttenuation:true}));root.add(dust);
 const lines=new T.Group();root.add(lines);const veinMat=new T.MeshBasicMaterial({color:'#b49254',transparent:true,opacity:.65});
 for(let j=0;j<12;j++){const pts=[];for(let n=0;n<30;n++){const a=j/12*Math.PI*2+n*.14;pts.push(new T.Vector3(Math.cos(a)*(2.3+Math.sin(n)*.2),1+Math.sin(a)*(2.3+Math.cos(n)*.2),12-n*1.4));}lines.add(new T.Mesh(new T.TubeGeometry(new T.CatmullRomCurve3(pts),100,.013,4,false),veinMat));}
 const sun=mesh(sphere,new T.MeshBasicMaterial({color:'#f8d598'}),root);sun.position.set(-.7,1.45,-12.7);sun.scale.setScalar(.6);
 const moon=mesh(sphere,new T.MeshStandardMaterial({color:'#abc7e1',emissive:'#29405a',roughness:1}),root);moon.position.set(.85,1.6,-13);moon.scale.setScalar(.46);
 for(const [r,a] of [[1.3,.25],[1.7,-.3]]){const ring=new T.Mesh(new T.TorusGeometry(r,.015,6,100),veinMat);ring.position.set(0,1.5,-13);ring.rotation.x=.5;ring.rotation.y=a;root.add(ring);}
 const gods=new T.Group();root.add(gods);
 for(let i=0;i<5;i++){const group=new T.Group();group.position.set((i-2)*6.8,0,-27-Math.abs(i-2)*3);const s=i===2?1:.70;group.scale.setScalar(s);const mat=new T.MeshStandardMaterial({color:'#8e8267',emissive:'#4c3b22',emissiveIntensity:.18,roughness:.95,transparent:true,opacity:.55});
  ellipsoid(group,mat,[0,8.2,0],[.8,1.1,.65]);ellipsoid(group,mat,[0,5.7,0],[1.65,1.7,.85]);ellipsoid(group,mat,[0,2.8,0],[2.1,2,.9]);
  for(const sign of [-1,1]){const upper=mesh(cylinder,mat,group),lower=mesh(cylinder,mat,group);link(upper,[sign*1.4,6.7,0],[sign*2.1,4.9,.2],.45);link(lower,[sign*2.1,4.9,.2],[sign*1.2,4.1,1],.34);}
  const halo=new T.Mesh(new T.TorusGeometry(1.7,.025,6,100),new T.MeshBasicMaterial({color:'#c1a367',transparent:true,opacity:.55}));halo.position.set(0,8.2,-.5);group.add(halo);gods.add(group);
 }
 return {root,update(t,directed=false,shotId){dust.rotation.z=(t-4)*.01;const reveal=shotId?shotId==='S04':t>=7;gods.visible=directed?reveal:t>=6.9;sun.visible=directed?!reveal:t<7.3;moon.visible=directed?!reveal:t<7.3;lines.visible=directed?!reveal:t<7.4;}};
}
export function createStage(scene){
 const built=buildScene('residence-hall');const hall=new T.Group();hall.name='府邸正堂预演';hall.add(built.root);scene.add(hall);
 const gray={ground:'#9ba39f',architecture:'#777e79',walls:'#929d97',roof:'#666e69',furniture:'#6e7771',nature:'#7c8c80'};
 built.root.children.forEach(p=>{if(p.userData.kind==='roof')p.visible=false;p.traverse(o=>{if(o.isMesh){o.material=new T.MeshStandardMaterial({color:gray[p.userData.kind]||'#8d9590',roughness:.94,side:T.DoubleSide});o.castShadow=true;o.receiveShadow=true;}});});
 const actors=new Map();for(const spec of ACTORS){const a=importedActor(spec);hall.add(a.root,a.seat,a.marker);actors.set(spec.id,a);}
 const glow=new T.Mesh(new T.SphereGeometry(.035,16,12),new T.MeshBasicMaterial({color:'#ffdb91'}));hall.add(glow);const glowLight=new T.PointLight('#ffc879',0,1.8);hall.add(glowLight);
 const vision=visionSpace();scene.add(vision.root);vision.root.visible=false;
 const hemi=new T.HemisphereLight('#e3eff4','#6c7165',2.6),sun=new T.DirectionalLight('#ffe8c8',3);sun.position.set(4,9,6);sun.castShadow=true;sun.shadow.mapSize.set(2048,2048);Object.assign(sun.shadow.camera,{left:-7,right:7,top:7,bottom:-7,near:.1,far:30});sun.shadow.normalBias=.03;sun.shadow.bias=-.0001;const fill=new T.DirectionalLight('#cbd9f0',1.1);fill.position.set(-5,4,-2);scene.add(hemi,sun,fill);
 let currentSpace='hall',naturalMotion=true;
 return {hall,actors,vision,setMotionMode(value){naturalMotion=value!=='legacy';},ready:Promise.all([...actors.values()].map(a=>a.ready)),refreshRigs(){const p=rigPreferences();return Promise.all([...actors].map(([id,a])=>a.setRig(p[id])));},update(project,time,space,shotId){
  const A=project.actors[0].p,B=project.actors[1].p,contact=[mix(A[0],B[0],.58),.90,mix(A[2],B[2],.5)-.20];
  project.actors.forEach(a=>actors.get(a.id).pose(a,time,contact,naturalMotion&&project.motionVersion!=='legacy'));glow.position.fromArray(contact);glowLight.position.copy(glow.position);const active=project.directionVersion==='articulated-v3'?0:smooth((time-1.5)/.4)*(1-smooth((time-3.5)/.5));glow.visible=active>.01;glow.scale.setScalar(1+active*.8);glowLight.intensity=active*2;
  hall.visible=space==='hall';vision.root.visible=space==='vision';vision.update(time,project.directionVersion==='cinematic-v2',shotId);
  if(currentSpace!==space){currentSpace=space;}scene.background=new T.Color(space==='hall'?'#566467':'#0a111d');scene.fog=space==='hall'?new T.Fog('#566467',16,45):new T.FogExp2('#0a111d',.013);
 },get space(){return currentSpace;}};
}
