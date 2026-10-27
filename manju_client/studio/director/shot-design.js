import {createProject,validateProject} from './timeline.js';

export const DIRECTION_VERSION='cinematic-v2';
const key=(t,p,target,lens)=>({t,p,target,lens});

// The shot rhythm is authored in seconds. Constant lens per shot separates
// a physical camera move from optical zoom; repeated keys create real holds.
export function createDirectedProject(source=createProject()){
 const p=structuredClone(validateProject(structuredClone(source)));
 p.directionVersion=DIRECTION_VERSION;p.directionTitle='接触未知 · 导演设计版';
 p.actors.forEach(a=>a.performance=DIRECTION_VERSION);
 const plans=[
  {name:'试探 · 关系建立',move:'横移 / 双人中景',action:'伸手 · 留一拍',
   note:'先停 0.35 秒认清两人的位置；短距离横移，让椅背产生视差。手进入接触状态后停住，把剪辑点交给下一镜的手部。',
   direction:{method:'双人中景 · 轻横移后停住',purpose:'保留两人身高差和椅子作为空间参照，让伸手成为画面主动作。',continuity:'摄影机保持人物轴线正 Z 一侧；叶宇在左、师心水在右。下一镜放大同一个接触点。',cut:'在接触保持中切到手部特写；人物方向不翻转。'},
   keys:[key(0,[1.38,1.24,3.30],[.08,1.04,-.02],48),key(.35,[1.38,1.24,3.30],[.08,1.04,-.02],48),key(1.65,[.98,1.24,3.30],[-.02,1.04,-.02],48),key(2,[.98,1.24,3.30],[-.02,1.04,-.02],48)]},
  {name:'接触 · 进入未知',move:'推进 / 手部特写',action:'接触金光 → 异象',
   note:'65 mm 固定焦距，慢推到双手接触处；最后 0.25 秒停住。接触点放在画面中心，与下一镜的前进通道形成视觉衔接。',
   direction:{method:'手部特写 · 一次受控推进',purpose:'明确“接触触发异象”的因果，让观众知道接下来是体内的主观空间。',continuity:'沿用上一镜的左右关系、手掌位置与日光方向；不越轴，不同时改变焦距。',cut:'中心接触光点硬切至中心星脉通道；这里使用构图匹配，不模拟闪白。'},
   keys:[key(2,[.12,1.19,1.16],[.0464,.90,-.20],65),key(3.75,[.10,1.12,.88],[.0464,.90,-.20],65),key(4,[.10,1.12,.88],[.0464,.90,-.20],65)]},
  {name:'星脉 · 被吸入',move:'加速穿行 / 主观镜头',action:'进入 → 加速 → 刹住',
   note:'26 mm 广角沿单一方向穿过星脉，先缓后快，临近太阳与月亮再减速。此镜看不到神祇，把揭示留给下一镜。',
   direction:{method:'主观穿行 · 连续速度曲线',purpose:'用近处星脉的视差体现进入身体深处的速度，把注意力带向前方。',continuity:'全程沿负 Z 方向推进，没有左右蛇形摆动；神祇到 7 秒才出现。',cut:'日月与星脉的前进镜头切至低机位神祇局部，仍向同一深处观看。'},
   ease:'baked',keys:sampleFlight()},
  {name:'神祇 · 仰视显现',move:'仰摇 / 低机位揭示',action:'由下向上 → 停住仰望',
   note:'摄影机固定在低处，只向上仰摇。先见神祇下半身，再显露头部与光环；最后 0.7 秒停住，给观众看清体量的时间。',
   direction:{method:'低机位仰摇 · 揭示后停顿',purpose:'用观看角度和体量差产生压迫感，避免快速接近把巨物拍成普通人像。',continuity:'保持空间前进方向；摄影机位置和 26 mm 焦距固定，只改变注视高度。',cut:'在神祇完整显现并停住之后，硬切回叶宇近景，形成奇观到人物的尺度反差。'},
   keys:[key(7,[1.3,.32,-13.5],[0,1.9,-27],26),key(7.25,[1.3,.32,-13.5],[0,1.9,-27],26),key(9.3,[1.3,.32,-13.5],[0,5.0,-27],26),key(10,[1.3,.32,-13.5],[0,5.0,-27],26)]},
  {name:'动念 · 危险的停顿',move:'静后微推 / 叶宇近景',action:'抬眼 → 动念 → 留白',
   note:'先静止 0.4 秒，让观众重新落到叶宇脸上；再用 75 mm 固定焦距微推，末尾留 0.35 秒停顿。心声“要不要……搜魂？”是后续声音设计提示，本预演没有合成配音。',
   direction:{method:'人物近景 · 先静后微推',purpose:'把奇观收束为叶宇的一个念头，使下一镜小师妹的退避有可感知的触发。',continuity:'回到原有人物轴线同侧；叶宇视线朝师心水，保持侧向空间关系。',cut:'叶宇停住的一瞬切到双人反应景，抽手发生在新镜头内。'},
   keys:[key(10,[.69,1.43,1.36],[-.46,1.42,0],75),key(10.4,[.69,1.43,1.36],[-.46,1.42,0],75),key(11.65,[.58,1.43,1.23],[-.46,1.42,0],75),key(12,[.58,1.43,1.23],[-.46,1.42,0],75)]},
  {name:'惊退 · 关系拉开',move:'后撤 / 三人关系重建',action:'抽手 → 退向师父 → 定住',
   note:'开头先让抽手发生；摄影机随后退开，保留叶宇在左侧、师心水向右后方退避的完整方向。最后 0.55 秒停住，让她与师父、叶宇的距离成为结尾。',
   direction:{method:'动作触发后撤 · 结尾停在关系全景',purpose:'摄影机晚于人物动作启动，从接触的两人关系变成拉开距离的三人关系。',continuity:'保持叶宇在左、师心水向右后方移动；不切反面追拍，避免退避方向翻转。',cut:'14.45 秒后摄影机和退避动作都停住，保留结尾画面，可衔接下一段对白。'},
   keys:[key(12,[1.45,1.44,3.18],[.12,1.02,-.05],38),key(12.3,[1.45,1.44,3.18],[.12,1.02,-.05],38),key(14.45,[2.25,1.72,4.30],[.65,1.07,-.35],38),key(15,[2.25,1.72,4.30],[.65,1.07,-.35],38)]}
 ];
 // Respect the current cast placement. Hall cameras rotate and translate with
 // the two-character axis; the abstract inner space uses its own coordinates.
 const A=p.actors[0].p,B=p.actors[1].p,angle=Math.atan2(B[2]-A[2],B[0]-A[0]);
 const transform=v=>[A[0]+(v[0]+.58)*Math.cos(angle)-v[2]*Math.sin(angle),v[1]+A[1],A[2]+(v[0]+.58)*Math.sin(angle)+v[2]*Math.cos(angle)];
 p.shots=p.shots.map((shot,i)=>{const out={...shot,...plans[i],ease:plans[i].ease||'smooth'};delete out.preset;if(out.space==='hall')out.keys=out.keys.map(k=>({...k,p:transform(k.p),target:transform(k.target)}));return out;});
 return validateProject(p);
}

function sampleFlight(){
 const keys=[];
 for(let i=0;i<=60;i++){
  const u=i/60,progress=u*u*(3-2*u);
  keys.push(key(4+3*u,[.18,1.25,8-13.5*progress],[.18,1.4,-22],26));
 }
 return keys;
}
