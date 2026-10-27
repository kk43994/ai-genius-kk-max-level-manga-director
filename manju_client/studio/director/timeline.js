// All times are absolute seconds. Sampling never depends on playback history.
export const DURATION=15, FPS=30;
export const ACTORS=[
 {id:'ye',name:'叶宇',color:'#5b9cf5',height:1.88,heads:8.8,p:[-.58,0,0],yaw:90},
 {id:'shi',name:'师心水',color:'#f087ae',height:1.28,heads:6.5,p:[.50,0,0],yaw:-90},
 {id:'feng',name:'封不平',color:'#74bf9a',height:1.83,heads:8.2,p:[1.65,0,-.95],yaw:-25}
];
const k=(t,p,target,lens)=>({t,p,target,lens});
export function createProject(){return {
 schema:'dashixiong-director/1',title:'探查神体',scene:'residence-hall',duration:DURATION,fps:FPS,aspect:'16:9',
 actors:structuredClone(ACTORS),
 shots:[
 {id:'S01',name:'伸手 · 试探',start:0,end:2,space:'hall',color:'#87b5da',move:'缓推 / 双人中景',note:'师心水犹豫着伸手，叶宇身体微微前倾。先建立两人的位置与身高差。',action:'伸手 → 接触',keys:[k(0,[2.7,1.7,4.2],[.15,1.02,0],42),k(2,[2.2,1.5,3.3],[.05,1.01,0],46)]},
 {id:'S02',name:'接触 · 灵识进入',start:2,end:4,space:'hall',color:'#a7c9c0',move:'推进 / 手部特写',note:'金色灵识在手掌接触处亮起。摄影机沿手腕方向靠近，为进入异象做衔接。',action:'手部接触 · 金光',keys:[k(2,[.7,1.27,1.2],[.04,.9,-.20],60),k(4,[.37,1.08,.64],[.04,.9,-.20],65)]},
 {id:'S03',name:'星脉 · 日月',start:4,end:7,space:'vision',color:'#c6a86e',move:'穿行 / 主观镜头',note:'抽象体内空间：摄影机沿金色星脉前进，日月轮廓在前方出现。这是视效预演，不是正堂内的真实物件。',action:'灵识向内穿行',keys:[k(4,[0,1,9],[0,1,-6],28),k(5.5,[.5,1.3,3],[0,1,-8],28),k(7,[0,1,-4],[0,1,-13],32)]},
 {id:'S04',name:'神祇 · 显现',start:7,end:10,space:'vision',color:'#d5ae6a',move:'抬升 / 尺度揭示',note:'速度放缓，抬头看见巨大的神祇轮廓。这里只确定体量、遮挡和镜头节奏，面貌仍待美术设计。',action:'显现 → 停顿',keys:[k(7,[0,1,-5],[0,3,-22],30),k(10,[.5,2.1,-10],[0,6,-23],30)]},
 {id:'S05',name:'动念 · 搜魂',start:10,end:12,space:'hall',color:'#94b3d5',move:'微推 / 叶宇近景',note:'回到正堂。叶宇头部微抬，视线转向小师妹。心声提示：“要不要……搜魂？”',action:'抬眼 · 动念',keys:[k(10,[1.45,1.48,1.05],[-.44,1.40,.04],70),k(12,[1.18,1.47,.94],[-.44,1.40,.04],75)]},
 {id:'S06',name:'抽手 · 退避',start:12,end:15,space:'hall',color:'#d399b2',move:'拉开 / 反应双人景',note:'师心水骤然抽手、起身，退到封不平椅侧。叶宇的手短暂停留，再转头追随她。',action:'抽手 → 起身 → 退避',keys:[k(12,[2.5,1.75,3.6],[.3,1.02,-.12],45),k(15,[3.65,2.1,4.6],[.7,1.10,-.45],43)]}
 ]};}
export const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
export const smooth=t=>{t=clamp(t,0,1);return t*t*(3-2*t);};
export const mix=(a,b,t)=>a+(b-a)*t;
export const mix3=(a,b,t)=>a.map((v,i)=>mix(v,b[i],t));
export function shotAt(project,time){const t=clamp(time,0,project.duration);return project.shots.find(s=>t>=s.start&&t<s.end)||project.shots.at(-1);}
export function sampleCamera(shot,time){
 const keys=[...shot.keys].sort((a,b)=>a.t-b.t),t=clamp(time,keys[0].t,keys.at(-1).t);
 let i=keys.findIndex((a,j)=>j<keys.length-1&&t>=a.t&&t<=keys[j+1].t);if(i<0)i=keys.length-2;
 const a=keys[i],b=keys[i+1],u=(t-a.t)/(b.t-a.t),f=['linear','baked'].includes(shot.ease)?u:smooth(u);
 return {p:mix3(a.p,b.p,f),target:mix3(a.target,b.target,f),lens:mix(a.lens,b.lens,f)};
}
export function keyAt(shot,time,eps=.03){return shot.keys.findIndex(k=>Math.abs(k.t-time)<eps);}
export function upsertKey(shot,time,pose){const t=clamp(time,shot.start,shot.end),index=keyAt(shot,t);const key={t,...structuredClone(pose)};if(index>=0)shot.keys[index]=key;else shot.keys.push(key);shot.keys.sort((a,b)=>a.t-b.t);return key;}
export function validateProject(p){
 if(p?.schema!=='dashixiong-director/1'||p.scene!=='residence-hall'||p.duration!==15||p.fps!==30)throw Error('不是本导演台的 15 秒工程');
 if(!['16:9','9:16','21:9'].includes(p.aspect))throw Error('画幅无效');
 if(!Array.isArray(p.shots)||p.shots.length!==6||!Array.isArray(p.actors)||p.actors.length!==3)throw Error('镜头或角色数量不正确');
 if(p.motionVersion!==undefined&&!['legacy','natural'].includes(p.motionVersion))throw Error('人物动作版本无效');
 const vector=a=>Array.isArray(a)&&a.length===3&&a.every(n=>Number.isFinite(n)&&Math.abs(n)<500);
 const orig=createProject();
 p.shots.forEach((s,i)=>{const o=orig.shots[i];if(s.id!==o.id||s.start!==o.start||s.end!==o.end||s.space!==o.space||typeof s.name!=='string'||typeof s.note!=='string')throw Error('镜头结构无效');if(!Array.isArray(s.keys)||s.keys.length<2||s.keys.length>100)throw Error('关键帧数量无效');if(s.keys[0].t!==s.start||s.keys.at(-1).t!==s.end)throw Error('缺少镜头首尾关键帧');s.keys.forEach((k,j)=>{if(!Number.isFinite(k.t)||k.t<s.start||k.t>s.end||(j&&k.t<=s.keys[j-1].t)||!vector(k.p)||!vector(k.target)||!Number.isFinite(k.lens)||k.lens<12||k.lens>150)throw Error('摄影机关键帧数据无效');if(Math.hypot(...k.p.map((v,n)=>v-k.target[n]))<.02)throw Error('摄影机与注视点不能重合');});});
 p.shots.forEach(s=>{
  if(s.ease!==undefined&&!['smooth','linear','baked'].includes(s.ease))throw Error('镜头节奏无效');
  if(typeof s.move!=='string'||typeof s.action!=='string'||typeof s.color!=='string'||!/^#[0-9a-f]{6}$/i.test(s.color))throw Error('镜头说明无效');
  if(s.preset!==undefined){const r=s.preset;if(!r||typeof r.id!=='string'||r.id.length>50||!['ye','shi','feng','pair','all','vision'].includes(r.target)||!['wide','medium','close'].includes(r.framing)||!['gentle','normal','strong'].includes(r.amount)||![1,-1].includes(r.direction)||!['16:9','9:16','21:9'].includes(r.aspect)||typeof r.actorSignature!=='string'||r.actorSignature.length>4096||typeof r.modified!=='boolean')throw Error('镜头预设记录无效');}
 });
 p.actors.forEach((a,i)=>{if(a.id!==ACTORS[i].id||typeof a.name!=='string'||!vector(a.p)||!Number.isFinite(a.yaw)||typeof a.color!=='string'||!/^#[0-9a-f]{6}$/i.test(a.color))throw Error('人物位置数据无效');});return p;
}
