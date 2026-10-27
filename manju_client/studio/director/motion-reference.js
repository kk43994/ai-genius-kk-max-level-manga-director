// Deterministic, planted-foot performance. Time is local to the 5 s retreat shot.
import {smooth,mix,mix3,ACTORS} from './timeline.js';
const phase=(t,a,b)=>smooth((t-a)/(b-a));
const transform=(p,yaw,v)=>[p[0]+Math.cos(yaw)*v[0]+Math.sin(yaw)*v[2],p[1]+v[1],p[2]-Math.sin(yaw)*v[0]+Math.cos(yaw)*v[2]];
export const MOTION_ACTORS=ACTORS.map(a=>({...a,performance:'articulated-v3',p:a.id==='ye'?[-.43,0,.16]:a.id==='shi'?[.36,0,.16]:[1.04,0,-.87],yaw:a.id==='feng'?0:a.yaw}));
export const MOTION_BEATS=[
 {t:0,label:'掌心接触',action:'叶宇托住手掌，师心水注视他。'},
 {t:.65,label:'惊觉抽手',action:'师心水肩膀先缩，左肘弯曲，手掌收向胸口。'},
 {t:1.3,label:'转身退步',action:'躯干转约 35°，左脚抬起后落地，右脚承重。'},
 {t:2.1,label:'换脚承重',action:'重心转到左腿，右脚向椅侧后撤，双臂护胸。'},
 {t:3.25,label:'收步站稳',action:'左脚收至右脚旁，两膝回弹；封不平抬手护住肩侧。'},
 {t:4.8,label:'反应停留',action:'师心水回头看叶宇，叶宇收回悬空的手；三人停稳。'}
];
function foot(t,start,end,a,b){const u=phase(t,a,b);const p=mix3(start,end,u);p[1]+=.07*Math.sin(Math.PI*u);return p;}
export function performanceAt(config,t){
 const spec=ACTORS.find(a=>a.id===config.id),h=spec.height,child=config.id==='shi',elder=config.id==='feng';
 const fear=phase(t,.4,.8),reach=1,withdraw=child?fear:phase(t,.9,1.7);
 const p=[...config.p];let yaw=config.yaw*Math.PI/180;
 let hipY=elder?h*.35:h*.55+.06,shoulderY=elder?h*.64:h*.82,headY=elder?h*.75:h-h/spec.heads/2;
 if(child){
  const path=[{t:0,p:[0,0,0]},{t:.85,p:[0,0,0]},{t:1.65,p:[.25,0,-.04]},{t:2.45,p:[.66,0,-.16]},{t:3.2,p:[1.17,0,-.39]},{t:3.9,p:[1.31,0,-.73]},{t:5,p:[1.31,0,-.73]}];
  const n=path.findIndex((k,i)=>i<path.length-1&&t>=k.t&&t<path[i+1].t);const a=path[Math.max(0,n)],b=n<0?path.at(-1):path[n+1];
  const d=n<0?b.p:mix3(a.p,b.p,phase(t,a.t,b.t));for(let i=0;i<3;i++)p[i]+=d[i];
  const compression=.045*phase(t,.4,.8)*(1-phase(t,3.6,4.1));hipY-=compression;shoulderY-=compression;headY-=compression;
  yaw+=.61*phase(t,.65,1.3);
 }
 const lean=elder?.02:child?-.055*fear:.10*(1-.7*withdraw);
 const hands={};for(const side of ['L','R']){const sign=side==='R'?1:-1;
  let local=[sign*h*.14,hipY-.20,h*.035];
  if(child)local=mix3(local,[sign*h*.10,shoulderY+.015,h*.09],fear);
  let world=transform(p,yaw,local);
  if((child&&side==='L')||(!child&&!elder&&side==='R'))world=mix3([.01,1.03,.16],world,withdraw);
  if(elder&&side==='R')world=mix3(world,[1.53,1.10,-.60],phase(t,3.1,3.9));
  hands[side]=world;
 }
 const feet={};
 if(child){
  const L=[config.p[0],.16,config.p[2]-.09],R=[config.p[0],.16,config.p[2]+.09];
  const L1=[config.p[0]+.52,.16,config.p[2]-.15],L2=[config.p[0]+1.28,.16,config.p[2]-.58],R1=[config.p[0]+.92,.16,config.p[2]-.22],R2=[config.p[0]+1.38,.16,config.p[2]-.85];
  feet.L=t<2.4?foot(t,L,L1,.9,1.65):foot(t,L1,L2,2.4,3.2);
  feet.R=t<3.15?foot(t,R,R1,1.6,2.45):foot(t,R1,R2,3.15,3.9);
 }else for(const side of ['L','R']){const sign=side==='R'?1:-1;feet[side]=transform(p,yaw,[sign*h*.075,.16,elder?h*.23:.02]);}
 const head=transform(p,yaw,[0,headY,lean]);
 return {p,yaw,h,head,headSize:h/spec.heads,child,elder,fear,withdraw,reach,standing:elder?0:1,move:phase(t,.85,3.2),lean,hipY,shoulderY,headY,hands,feet,articulated:true,hipOffset:child?-.045*phase(t,.4,.8)*(1-phase(t,3.6,4.1)):0,headTurn:child?-.35*phase(t,3.2,4):elder?.2*phase(t,2.5,3.2):-.15*withdraw};
}
