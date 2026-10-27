import {clamp,mix,mix3,smooth} from './timeline.js';
import {blockingState} from './blocking.js';

export const PRESETS=[
 {id:'locked',name:'固定镜头',en:'Locked-off',group:'基础运镜',description:'摄影机、朝向与焦距固定，让人物自己完成动作。',purpose:'对话、等待、观察，给表演留下空间。'},
 {id:'push',name:'缓慢推进',en:'Dolly in',group:'基础运镜',description:'摄影机向主体靠近，焦距保持不变，空间透视随距离改变。',purpose:'聚焦细节、加强压力、靠近人物的决定。'},
 {id:'pull',name:'拉远揭示',en:'Dolly out',group:'基础运镜',description:'摄影机逐渐后退，让更多环境进入画面。',purpose:'交代处境、孤立人物或揭示更大的空间。'},
 {id:'truck',name:'横向移镜',en:'Truck',group:'基础运镜',direction:true,description:'摄影机横向移动，保持原来的拍摄朝向与焦距。',purpose:'利用前后景视差展示空间层次。'},
 {id:'pan',name:'水平摇镜',en:'Pan',group:'基础运镜',direction:true,description:'摄影机位置固定，镜头左右转动扫过主体。',purpose:'把注意力从画面一侧引向另一侧。'},
 {id:'tilt',name:'上下摇镜',en:'Tilt',group:'基础运镜',direction:'vertical',description:'摄影机位置固定，镜头从低处向上摇或从高处向下摇。',purpose:'逐步介绍人物、物件或建筑高度。'},
 {id:'pedestal',name:'垂直升降',en:'Pedestal',group:'基础运镜',direction:'vertical',description:'摄影机整体升降，注视点同步升降，保持拍摄朝向。',purpose:'改变观看高度，观察上下空间关系。'},
 {id:'arc',name:'弧线环绕',en:'Arc',group:'空间与光学',direction:true,description:'摄影机沿一段圆弧围绕主体，持续看向主体。',purpose:'揭示人物侧面和背景关系；幅度越大，空间变化越明显。'},
 {id:'orbit',name:'完整环绕',en:'Orbit 360°',group:'空间与光学',direction:true,description:'摄影机绕主体一整圈，始终朝向中心；会经过轴线两侧。',purpose:'研究完整空间关系；室内使用时需要检查沿途遮挡。'},
 {id:'follow',name:'跟随人物',en:'Tracking',group:'空间与光学',description:'摄影机跟随人物实际位移，与人物保持相对位置。',purpose:'研究走位与摄影机同步。师心水在 S06 的退避最便于观察。'},
 {id:'zoom',name:'光学变焦',en:'Zoom in',group:'空间与光学',description:'摄影机位置与朝向固定，仅改变焦距，使取景逐渐收紧。',purpose:'比较变焦与推进：变焦不改变摄影机的空间位置。'},
 {id:'dolly-zoom',name:'推拉变焦',en:'Dolly zoom',group:'空间与光学',description:'摄影机后退，同时增大焦距，让注视点所在平面的主体大小基本不变。',purpose:'让背景透视改变，表现惊觉、失衡或心理冲击。'},
 {id:'two-shot',name:'双人关系机位',en:'Two-shot',group:'人物机位',forcedTarget:'pair',description:'按叶宇与师心水的位置计算双人构图，摄影机固定。',purpose:'先交代两人的距离、朝向和关系，再切到单人镜头。'},
 {id:'ots-ye',name:'越肩看叶宇',en:'OTS → 叶宇',group:'人物机位',forcedTarget:'ye',hallOnly:true,description:'从师心水肩后看向叶宇，保留近处人物作为前景。',purpose:'让叶宇的反应和对话关系同时可见。'},
 {id:'ots-shi',name:'越肩看师心水',en:'OTS → 师心水',group:'人物机位',forcedTarget:'shi',hallOnly:true,description:'从叶宇肩后看向师心水，与另一越肩机位配合查看正反打。',purpose:'观察小师妹的反应，保留两人之间的空间联系。'}
];
export const getPreset=id=>PRESETS.find(p=>p.id===id);
const add=(a,b)=>a.map((n,i)=>n+b[i]),sub=(a,b)=>a.map((n,i)=>n-b[i]),scale=(a,s)=>a.map(n=>n*s);
const dot=(a,b)=>a.reduce((s,n,i)=>s+n*b[i],0),length=a=>Math.hypot(...a),unit=a=>scale(a,1/(length(a)||1));
const rotate=(v,a)=>[v[0]*Math.cos(a)+v[2]*Math.sin(a),v[1],-v[0]*Math.sin(a)+v[2]*Math.cos(a)];
const actorIds=target=>target==='pair'?['ye','shi']:target==='all'?['ye','shi','feng']:[target];
export const actorSignature=project=>JSON.stringify(project.actors.map(a=>[a.id,...a.p,a.yaw]));

function subject(project,shot,target,framing,t){
 if(shot.space==='vision'){
  const center=shot.id==='S04'?[0,5,-27]:[0,1.5,-13],size=shot.id==='S04'?[12,10,3]:[4,4,2];
  const factor=framing==='close'?.45:framing==='wide'?1.3:1;
  return {center,min:sub(center,scale(size,.5*factor)),max:add(center,scale(size,.5*factor)),height:size[1]*factor};
 }
 const marks=actorIds(target).map(id=>blockingState(project.actors.find(a=>a.id===id),t));
 const boxes=marks.map(m=>{
  const width=m.h*(framing==='close'?.16:.23);
  const low=framing==='wide'?m.p[1]+.05:m.head[1]-m.h*(framing==='close'?.16:.48);
  const high=m.head[1]+m.headSize*.68;
  return {min:[m.head[0]-width,low,m.head[2]-m.h*.16],max:[m.head[0]+width,high,m.head[2]+m.h*.16]};
 });
 const min=[0,1,2].map(i=>Math.min(...boxes.map(b=>b.min[i]))),max=[0,1,2].map(i=>Math.max(...boxes.map(b=>b.max[i])));
 return {min,max,center:mix3(min,max,.5),height:max[1]-min[1]};
}

// Match Three.PerspectiveCamera's 35 mm film gauge across portrait and landscape.
export function sensorSize(aspect){return {w:35*Math.min(aspect,1),h:35/Math.max(aspect,1)};}
function fitDistance(bounds,outward,lens,aspect){
 const right=unit([outward[2],0,-outward[0]]),up=unit([outward[1]*right[2],outward[2]*right[0]-outward[0]*right[2],-outward[1]*right[0]]),sensor=sensorSize(aspect);
 let distance=.4;
 for(const x of [bounds.min[0],bounds.max[0]])for(const y of [bounds.min[1],bounds.max[1]])for(const z of [bounds.min[2],bounds.max[2]]){
  const d=sub([x,y,z],bounds.center),depth=dot(d,outward);
  distance=Math.max(distance,depth+1.16*Math.abs(dot(d,right))*lens/(sensor.w/2),depth+1.16*Math.abs(dot(d,up))*lens/(sensor.h/2));
 }
 return distance;
}

export function makePreset(project,shot,options={}){
 const preset=getPreset(options.id||'push');if(!preset)throw Error('请选择有效的镜头手法');
 if(shot.space==='vision'&&(preset.hallOnly||preset.id==='two-shot'||preset.id==='follow'))throw Error('此机位需要正堂中的人物，请先选择正堂镜头');
 const framing=['wide','medium','close'].includes(options.framing)?options.framing:'medium';
 const amount=['gentle','normal','strong'].includes(options.amount)?options.amount:'normal';
 const direction=options.direction===-1?-1:1;
 const target=shot.space==='vision'?'vision':preset.forcedTarget||(['ye','shi','feng','pair','all'].includes(options.target)?options.target:'pair');
 const [w,h]=project.aspect.split(':').map(Number),aspect=w/h;
 const bounds=subject(project,shot,target,framing,shot.start),focus=bounds.center;
 const A=project.actors.find(a=>a.id==='ye').p,B=project.actors.find(a=>a.id==='shi').p;
 let normal=shot.space==='vision'?[0,0,1]:unit([-(B[2]-A[2]),0,B[0]-A[0]]);
 if(length(normal)<.5)normal=[0,0,1];
 // Keep the initial pair's coverage on the same side as the sequence's first camera.
 const baseline=sub(project.shots[0].keys[0].p,A);
 if(shot.space==='hall'&&dot(normal,baseline)<0)normal=scale(normal,-1);
 const outward=unit(add(normal,[0,.08,0])),right=unit([normal[2],0,-normal[0]]);
 const lens=framing==='close'?70:framing==='wide'?35:50;
 const d=fitDistance(bounds,outward,lens,aspect),start=add(focus,scale(outward,d));
 const gain={gentle:.6,normal:1,strong:1.45}[amount];
 const travel=d*.26*gain,span=Math.max(bounds.height,bounds.max[0]-bounds.min[0],.5);
 const notes=[];let poseAt;
 const fixed=(p,target=focus,l=lens)=>({p:[...p],target:[...target],lens:l});
 switch(preset.id){
  case 'locked':case 'two-shot':poseAt=()=>fixed(start);break;
  case 'push':poseAt=u=>fixed(add(focus,scale(outward,d+travel*(1-2*u))));break;
  case 'pull':poseAt=u=>fixed(add(focus,scale(outward,d+travel*(2*u-1))));break;
  case 'truck':poseAt=u=>{const offset=scale(right,(u-.5)*span*.9*gain*direction);return fixed(add(start,offset),add(focus,offset));};break;
  case 'pan':poseAt=u=>fixed(start,add(focus,scale(right,(u-.5)*span*.9*gain*direction)));break;
  case 'tilt':poseAt=u=>fixed(start,add(focus,[0,(u-.5)*bounds.height*.9*gain*direction,0]));break;
  case 'pedestal':poseAt=u=>{const shift=[0,(u-.5)*Math.min(bounds.height*.65*gain,Math.max(.2,start[1]-.18))*direction,0];return fixed(add(start,shift),add(focus,shift));};break;
  case 'arc':case 'orbit':{
   const radians=(preset.id==='orbit'?360:{gentle:30,normal:60,strong:100}[amount])*Math.PI/180;
   poseAt=u=>fixed(add(focus,rotate(scale(outward,d),(preset.id==='orbit'?u:u-.5)*radians*direction)));
   if(preset.id==='orbit')notes.push('完整环绕会跨过人物轴线；请用空间总览检查沿途家具、人物与墙体。');
   break;
  }
  case 'follow':{
   poseAt=(u,t)=>{const here=subject(project,shot,target,framing,t).center,offset=sub(here,focus);return fixed(add(start,offset),here);};
   if(length(sub(subject(project,shot,target,framing,shot.end).center,focus))<.2)notes.push('当前镜头内主体移动较少；选 S06、师心水，可清楚看到跟拍位移。');
   break;
  }
  case 'zoom':poseAt=u=>fixed(start,focus,lens*(1+(u-.5)*.7*gain));break;
  case 'dolly-zoom':poseAt=u=>{const factor=1+(u-.5)*.65*gain;return fixed(add(focus,scale(outward,d*factor)),focus,lens*factor);};break;
  case 'ots-ye':case 'ots-shi':{
   const nearId=target==='ye'?'shi':'ye',near=blockingState(project.actors.find(a=>a.id===nearId),shot.start),far=blockingState(project.actors.find(a=>a.id===target),shot.start);
   const toward=unit([far.p[0]-near.p[0],0,far.p[2]-near.p[2]]);
   if(length(toward)<.5)throw Error('两个人物位置重合，先把他们分开再套用越肩机位');
   const aim=subject(project,shot,target,framing,shot.start);
   const back=framing==='wide'?1.25:framing==='close'?.65:.9;
   // Offset beyond the near actor's shoulder and chair back. A narrow offset
   // aimed at the much shorter child would look straight through the adult.
   const p=add(sub(near.p,scale(toward,back)),scale(normal,Math.max(.65,near.h*.75)));
   p[1]=(near.head[1]+far.head[1])*.5+.02;
   const dist=length(sub(p,aim.center)),fit=fitDistance(aim,unit(sub(p,aim.center)),50,aspect);
   poseAt=()=>fixed(p,aim.center,clamp(50*dist/fit,18,100));
   notes.push('两侧越肩机位保持在原关系轴线同侧；人物身高不同，拍摄高度分别适配。');
   break;
  }
 }
 const count=['locked','two-shot','ots-ye','ots-shi'].includes(preset.id)?2:preset.id==='orbit'?65:33;
 const keys=Array.from({length:count},(_,i)=>{
  const linear=i/(count-1),t=mix(shot.start,shot.end,linear),u=smooth(linear);
  const pose=poseAt(u,t);
  return {t,...pose};
 });
 if(keys.some(k=>[...k.p,...k.target,k.lens].some(n=>!Number.isFinite(n))||k.lens<12||k.lens>150||length(sub(k.p,k.target))<.02))throw Error('当前人物布局无法生成有效机位，请先调整人物间距');
 const pathLength=keys.slice(1).reduce((sum,k,i)=>sum+length(sub(k.p,keys[i].p)),0);
 if(shot.space==='hall'&&keys.some(k=>Math.abs(k.p[0])>5.5||Math.abs(k.p[2])>8.5||k.p[1]<.15))notes.push('轨迹接近或超出主要表演区域，请检查遮挡；可缩小运动幅度或收紧景别。');
 return {keys,ease:'baked',move:preset.name+' / '+({wide:'全景',medium:'中景',close:'近景'}[framing]),
  preset:{id:preset.id,target,framing,amount,direction,aspect:project.aspect,actorSignature:actorSignature(project),modified:false},
  stats:{pathLength,lensStart:keys[0].lens,lensEnd:keys.at(-1).lens,duration:shot.end-shot.start},notes,
  bounds,marks:shot.space==='hall'?project.actors.map(a=>({id:a.id,color:a.color,p:blockingState(a,shot.start).p})):[]};
}
