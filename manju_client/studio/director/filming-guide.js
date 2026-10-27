// Original project notes informed by the sources in filming-resources.md.
// These are intended choices for the demo, not automatic approval of edited shots.
export const SHOT_GUIDE = {
 S01:{method:'双人关系镜头 · 缓慢推进',purpose:'先看懂谁在试探谁，再靠近两人，让注意力落到伸出的手。',continuity:'叶宇与师心水是主关系。接触前，先让两人的位置和伸手方向可见。'},
 S02:{method:'动作细节镜头 · 接触点推进',purpose:'把“接触引发异象”交代清楚，让下一镜进入体内有明确原因。',continuity:'对齐上一镜手的动作方向与接触位置；剪辑点落在动作进行中。'},
 S03:{method:'主观穿行 · 通向视觉落点',purpose:'带观众沿星脉进入未知空间，视线始终有一个前进目标。',continuity:'这是主观异象，沿用进入方向；不套用正堂人物轴线。'},
 S04:{method:'抬升揭示 · 体量对比',purpose:'放慢前进，再抬高视线，让巨大神祇逐步进入构图。',continuity:'先给局部，再给体量；不要在同一镜里叠加快速环绕与变焦。'},
 S05:{method:'人物近景 · 决定前的微推',purpose:'从奇观回到叶宇的念头，把关注点收回到他的目光与停顿。',continuity:'回到正堂原有空间关系，视线对向小师妹所在的一侧。'},
 S06:{method:'反应镜头 · 随退避拉开',purpose:'让抽手、离开座位、靠近师父的距离变化可读，完成这一段的反应。',continuity:'人物移动会改变关系轴线。让移动过程可见，结尾重新交代三人的位置。'}
};

// Signed perpendicular distance to the A→B line on the XZ ground plane.
export function axisSide(a,b,c,tolerance=.12){
 const dx=b[0]-a[0],dz=b[2]-a[2],length=Math.hypot(dx,dz);
 if(length<.05)return {side:null,distance:0};
 const distance=(dx*(c[2]-a[2])-dz*(c[0]-a[0]))/length;
 return {side:Math.abs(distance)<=tolerance?0:Math.sign(distance),distance};
}
