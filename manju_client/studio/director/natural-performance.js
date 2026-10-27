import * as T from 'three';
import {blendMotion} from './motion-library.js';
const sat=x=>Math.max(0,Math.min(1,x));
export const phase=(t,a,b)=>{const x=sat((t-a)/(b-a));return x*x*x*(x*(x*6-15)+10)};
const mix=(a,b,u)=>a+(b-a)*u,mix3=(a,b,u)=>a.map((x,i)=>mix(x,b[i],u));
export const transform=(p,y,v)=>[p[0]+Math.cos(y)*v[0]+Math.sin(y)*v[2],p[1]+v[1],p[2]-Math.sin(y)*v[0]+Math.cos(y)*v[2]];
const local=(p,y,v)=>{const d=v.map((x,i)=>x-p[i]);return [Math.cos(y)*d[0]-Math.sin(y)*d[2],d[1],Math.sin(y)*d[0]+Math.cos(y)*d[2]]};
export function plantedStep(t,start,end,a,b,lift=.075){const u=phase(t,a,b),p=mix3(start,end,u);p[1]+=lift*Math.sin(Math.PI*u);return {p,contact:t<=a||t>=b,u};}
// All sampling is absolute-time: backwards scrubs produce the same planted feet.
export function naturalStage(config,t,rig,library,contact){
 const h=rig.height,child=config.id==='shi',elder=config.id==='feng',start=config.yaw*Math.PI/180;
 const fear=phase(t,12.1,12.48),stand=child?phase(t,12.45,13.25):0,travel=child?phase(t,13.02,14.72):0,turn=child?phase(t,12.7,13.55):0;
 const delta=[-.65*Math.cos(start)-.68*Math.sin(start),0,.65*Math.sin(start)-.68*Math.cos(start)];
 const p=config.p.map((v,i)=>v+travel*delta[i]),yaw=start+.55*turn;
 let motion=library.sample(elder?'Sitting_Talking_Loop':'Sitting_Idle_Loop',t*.64+(child?.6:0));
 if(child){const exit=library.sample('Sitting_Exit',Math.max(0,t-12.45)/.8*library.duration('Sitting_Exit'),{loop:false});motion=blendMotion(motion,exit,phase(t,12.3,12.55));motion=blendMotion(motion,library.sample('Idle_Loop',t),phase(t,13.15,13.7));}
 const planted={},feet={},contacts={},ankles={};
 for(const side of ['L','R']){
  const sign=side==='L'?1:-1,initial=transform(config.p,start,[sign*h*.07,rig.ankleHeight+.075,h*.23]);let step={p:initial,contact:true,u:0};
  if(child){const end=transform(config.p.map((v,i)=>v+delta[i]),start+.55,[sign*h*.07,rig.ankleHeight+.075,.03]);
   if(side==='R'){const mid=transform(config.p,start,[-h*.34,rig.ankleHeight+.075,h*.23]);step=t<14?plantedStep(t,initial,mid,13,13.45,.09):plantedStep(t,mid,end,14,14.45,.085)}
   else{const mid=transform(config.p,start,[-h*.44,rig.ankleHeight+.075,-h*.10]);step=t<14.5?plantedStep(t,initial,mid,13.5,13.95,.085):plantedStep(t,mid,end,14.5,14.95,.065)}
  }
  planted[side]=step.p;contacts[side]=step.contact;feet[side]=local(p,yaw,step.p);ankles[side]={pitch:step.contact?0:-12*Math.sin(Math.PI*step.u),toe:step.contact?0:8*Math.sin(Math.PI*step.u)};
 }
 if(child){const center=planted.L.map((v,i)=>(v+planted.R[i])/2),balance=phase(t,12.45,13.2);p[0]=mix(config.p[0],center[0],balance);p[2]=mix(config.p[2],center[2],balance);for(const side of ['L','R'])feet[side]=local(p,yaw,planted[side]);}
 const reach=phase(t,.25,1.55),withdraw=child?fear:phase(t,12.6,13.35),target=local(p,yaw,contact),hands={},handBlend={};
 const active=child?'L':'R';if(!elder){hands[active]=mix3(target,[active==='L'?h*.12:-h*.14,mix(h*.59,h*.77,stand),h*.18],withdraw);handBlend[active]=Math.max(reach*(1-withdraw),withdraw);}
 if(child){hands.R=[-h*.14,mix(h*.59,h*.73,stand),h*.15];handBlend.R=fear*.9;}
 const breath=Math.sin(t*1.8+(child?1:elder?2:0));
 const sitHip=h*.35,anticipate=child?.025*phase(t,12.2,12.48)*(1-phase(t,12.55,12.9)):0;
 const settle=child?.015*Math.sin((t-14.72)*9)*Math.exp(-Math.max(0,t-14.72)*5)*phase(t,14.72,14.9):0;
 const hipY=mix(sitHip,rig.restHip+.063,stand)-anticipate+settle+breath*.002;
 const hipX=child?-.018*Math.sin(travel*Math.PI*3)*stand:0;
 return {p,yaw,planted,contacts,pose:{grounded:true,motion,hipY,hipX,hipTilt:child?-.12*phase(t,12.22,12.75)*(1-phase(t,12.9,13.35)):0,lean:child?.075*phase(t,12.25,12.65)*(1-phase(t,12.85,13.3)):.04*reach*(1-withdraw),hipYaw:child?-.08*Math.sin(travel*Math.PI*3):0,chestYaw:child?.16*turn-.22*phase(t,14.05,14.8):elder?.08*phase(t,12.45,13.4):.04*withdraw,breath,hands,handBlend,feet,ankles,headYaw:child?.25*phase(t,12.38,12.8)-.52*phase(t,13.95,14.7):elder?.22*phase(t,12.3,13):-.12*withdraw,headPitch:child?.08*fear-.09*phase(t,13.8,14.6):0,grip:child?{L:.12+.35*fear,R:.1+.3*fear}:.1}};
}
// Short deliberate steps; each foot is fixed in world space during stance.
export function pathPerformance(a,x,time,library,elder=true){
 const t=Math.min(20,Math.max(15,time)),progress=phase(t,15,20),z=4.45-.75*progress,yaw=Math.PI;
 const ground=z=>Math.round((25-z)/1.22)*.23+.06;
 const startY=ground(4.45),endY=ground(3.7),y=mix(startY,endY,phase(t,16.25,18.5));
 const p=[x,y,z],h=a.height,feet={},contacts={},planted={},ankles={};
 const times=elder?[[15.18,16.05],[16.12,17],[17.08,17.96],[18.04,18.95]]:[[15.33,16.18],[16.27,17.13],[17.22,18.07],[18.16,19.09]];
 for(const side of ['L','R']){const sign=side==='L'?1:-1,xx=x-sign*h*.055,start=[xx,ground(4.45)+a.ankleHeight,4.45];let foot={p:start,contact:true,u:0};
  const idx=side==='L'?0:1,first=[xx,ground(4.45-.75*(idx===0?.43:.65))+a.ankleHeight,4.45-.75*(idx===0?.43:.65)],end=[xx,endY+a.ankleHeight,3.7];
  foot=t<times[idx+2][0]?plantedStep(t,start,first,...times[idx],.09):plantedStep(t,first,end,...times[idx+2],.08);
  planted[side]=foot.p;contacts[side]=foot.contact;feet[side]=local(p,yaw,foot.p);ankles[side]={pitch:-10*Math.sin(Math.PI*foot.u),toe:6*Math.sin(Math.PI*foot.u)};
 }
 const weight=phase(time,15,15.5)*(1-phase(time,19.1,20)),walking=library.sample(elder?'Walk_Formal_Loop':'Walk_Loop',(time-15)*.72+(elder?0:.3));
 let motion=blendMotion(library.sample('Idle_Loop',time*.8),walking,weight);
 const talking=elder?phase(time,20.25,21)*(1-phase(time,25.1,26.1)):phase(time,26.2,26.7)*(1-phase(time,29.25,30));
 motion=blendMotion(motion,library.sample('Idle_Talking_Loop',(time-(elder?20:26))*.8),talking*.7);
 const gesture=elder?phase(time,20.4,21.3)*(1-phase(time,24.7,26)):0,hands=elder?{R:[-.19,h*.81,h*.19]}:undefined;
 return {p,yaw,planted,contacts,pose:{grounded:true,motion,feet,ankles,hands,handBlend:{R:gesture*.8},hipY:a.restHip-.018+weight*.009*Math.cos((time-15)*6.8),hipX:weight*.014*Math.sin((time-15)*3.4),chestYaw:elder?-.12*talking:.12*talking,headYaw:elder?-.22*phase(time,20,20.7)*(1-phase(time,25.8,26.4)):.22*phase(time,26,26.6)*(1-phase(time,29.6,30.4)),headPitch:!elder?-.25*phase(time,50,52.5):0,breath:Math.sin(time*1.7),grip:.12}};
}
