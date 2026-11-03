'use strict';
// Film-inspired 2.5D motion keeps the approved artwork intact. No audio or 3D-avatar claims.
(() => {
 const stage=document.querySelector('#film-stage'),camera=document.querySelector('.art-camera');
 const hero=document.querySelector('.hero'),caption=document.querySelector('.camera-caption');
 const intro=document.querySelector('.hero-intro'),pause=document.querySelector('#motion-toggle');
 const topFilm=document.querySelector('.film-upper'),bottomFilm=document.querySelector('.film-lower');
 const iris=document.querySelector('.iris-frame'),shade=document.querySelector('.cinema-shade');
 const glints=[...document.querySelectorAll('.glint')],dust=document.querySelector('.film-dust');
 const reduced=matchMedia('(prefers-reduced-motion: reduce)');
 let paused=reduced.matches,visible=!document.hidden,x=0,y=0,sx=0,sy=0,time=0,last=0,raf=0,dirty=true;
 const clamp=(n,a=0,b=1)=>Math.max(a,Math.min(b,n));
 const ease=n=>n*n*(3-2*n);
 function sync(){pause.textContent=paused?'播放动效':'暂停动效';pause.setAttribute('aria-pressed',String(paused));stage.classList.toggle('motion-paused',paused);dirty=true;}
 sync();pause.addEventListener('click',()=>{paused=!paused;sync();});
 reduced.addEventListener('change',()=>{paused=reduced.matches;sync();});
 window.addEventListener('pointermove',e=>{x=(e.clientX/innerWidth-.5)*2;y=(e.clientY/innerHeight-.5)*2;},{passive:true});
 window.addEventListener('scroll',()=>{dirty=true;},{passive:true});
 window.addEventListener('resize',()=>{dirty=true;},{passive:true});
 document.addEventListener('visibilitychange',()=>{visible=!document.hidden;last=0;dirty=true;});
 function render(ms){
  raf=requestAnimationFrame(render);if(!visible)return;
  const dt=Math.min((ms-(last||ms))/1000,.05);last=ms;
  const h=innerHeight,scroll=scrollY,progress=clamp(scroll/(hero.offsetHeight-h||1)),mobile=innerWidth<760;
  if(scroll>hero.offsetHeight+h&&!dirty)return;
  if(paused&&!dirty)return;
  if(!paused)time+=dt;
  const movement=!paused&&!reduced.matches;
  sx+=(movement?x-sx:-sx)*.04;sy+=(movement?y-sy:-sy)*.04;
  const push=paused?0:ease(clamp(progress/.75));
  const settled=scroll>=hero.offsetHeight-h;
  const scale=1+push*(mobile?.35:.64),pan=push*(mobile?-15:-17);
  camera.style.transform=`translate3d(${pan+sx*.35}%,${push*2+sy*.24}%,0) scale(${scale}) rotateY(${sx*.65}deg) rotateX(${-sy*.4}deg)`;
  intro.style.opacity=String(1-clamp(progress*3));
  intro.style.visibility=progress>.34?'hidden':'visible';
  caption.style.opacity=String(clamp((progress-.35)*3)*(1-clamp((progress-.85)*5)));
  caption.style.transform=`translateY(${(1-push)*30}px)`;
  const close=paused?0:ease(clamp((progress-.65)/.35));
  iris.style.opacity=String(close*.8);
  const aperture=Array.from({length:9},(_,i)=>{const a=-(i%8)*Math.PI/4+close*.14;return `${69+Math.cos(a)*(90-close*53)}% ${50+Math.sin(a)*(125-close*70)}%`;}).join(',');
  iris.style.clipPath=`polygon(evenodd,0 0,100% 0,100% 100%,0 100%,0 0,${aperture})`;
  shade.style.opacity=String(settled?.73:push*.32);
  document.querySelector('.shot-indicator small').textContent=progress<.35?'THE OPENING':progress<.75?'DOLLY IN':'THE NEXT SCENE';
  topFilm.setAttribute('transform',`translate(${Math.sin(time*.16)*3.8} ${Math.cos(time*.14)*1.2})`);
  bottomFilm.setAttribute('transform',`translate(${Math.sin(time*.19+1)*-6.5} ${Math.sin(time*.13)*1.6})`);
  glints.forEach((path,i)=>{path.style.strokeDashoffset=String(-time*35+i*310);path.style.opacity=String(.30+Math.sin(time*.35+i)*.2);});
  dust.setAttribute('transform',`translate(${Math.sin(time*.1)*3} ${Math.sin(time*.12)*-5})`);
  dirty=false;
 }
 raf=requestAnimationFrame(render);
 window.addEventListener('pagehide',()=>{cancelAnimationFrame(raf);raf=0;});
 window.addEventListener('pageshow',()=>{last=0;dirty=true;if(!raf)raf=requestAnimationFrame(render);});
})();
