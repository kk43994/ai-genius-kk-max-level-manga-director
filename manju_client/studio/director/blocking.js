import {ACTORS,smooth,mix} from './timeline.js';

// Shared by the puppet and camera planner, so a tracking preset follows the
// same evaluated performance at any time, including when scrubbing backwards.
export function blockingState(config,t){
 const spec=ACTORS.find(a=>a.id===config.id);
 if(!spec)throw Error('未知人物');
 const h=spec.height,child=spec.id==='shi',elder=spec.id==='feng';
 const directed=config.performance==='cinematic-v2';
 const fear=smooth((t-12.15)/(directed?.28:1.6)),reach=smooth((t-.2)/1.1);
 const standing=child?smooth((t-12.35)/.8):0,move=child?smooth((t-12.75)/(directed?1.6:1.8)):0;
 const p=[config.p[0]+move*1.5,config.p[1],config.p[2]-move*.75];
 const yaw=config.yaw*Math.PI/180+(child?move*.8:0);
 const lean=!elder?(child?.11:.12)*reach*(1-fear):0;
 const hipY=mix(.35*h,.52*h,standing),shoulderY=mix(.64*h,.82*h,standing),headY=mix(.75*h,h-h/spec.heads/2,standing);
 const head=[p[0]+Math.sin(yaw)*lean,p[1]+headY,p[2]+Math.cos(yaw)*lean];
 const withdraw=child?fear:directed?smooth((t-12.65)/.8):Math.max(0,(fear-.5)*.45);
 return {p,yaw,h,head,headSize:h/spec.heads,child,elder,fear,withdraw,reach,standing,move,lean,hipY,shoulderY,headY};
}
